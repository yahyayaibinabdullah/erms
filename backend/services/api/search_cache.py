"""One replaceable ordered result list per login session and NiceGUI browser tab.

All four search screens use the search_results_cache table and
that SAME primary key. Only IDs and scores are saved, never permission decisions
or display rows. Every page joins live permissions before hydrating its rows.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from psycopg import sql
from psycopg.types.json import Jsonb

from . import search as engine
from .application_settings import cache as settings_cache
from .crud import redact_hidden_relationships
from .search_page import page_details
from .search_execution import interactive_search
from .dashboard_visibility import visibility_ctes
from .search_projections import HOLD_FIELDS, LOCATION_FIELDS, requested_fields, projection_ctes


def _indexed_ids(table, id_column, phrase, configurations):
    statement, values = engine._indexed_text_ids(table, id_column, phrase, configurations)
    return sql.SQL('''WITH search_query AS MATERIALIZED (
        SELECT %s::text AS phrase,websearch_to_tsquery('pg_catalog.english',%s) AS english,
               websearch_to_tsquery('pg_catalog.arabic',%s) AS arabic
    ), other_search_queries AS MATERIALIZED (
        SELECT config.oid::regconfig AS config,websearch_to_tsquery(config.oid::regconfig,phrase) AS parsed
        FROM pg_catalog.pg_ts_config config CROSS JOIN search_query
    ) ''') + statement, [phrase, phrase, phrase, *values]


def _indexed_leaf(leaf, resource, ctes, parameters):
    """Indexable match sets, shared by all rows (including nested Boolean leaves)."""
    index = len(ctes)
    sources = engine._full_text_sources(resource, leaf.query, leaf.sources)
    terms = []
    candidates = []
    file_guard, record_guard = sql.SQL('true'), sql.SQL('true')
    if 'metadata' in sources:
        kind = 'record' if resource == 'records' else 'aggregation'
        statement, values = _indexed_ids(
            f'{kind}_search_documents', f'{kind}_id', leaf.query, ('pg_catalog.simple',),
        )
        name = sql.Identifier(f'text_metadata_{index}')
        ctes.append(sql.SQL('{} AS MATERIALIZED ({})').format(name, statement))
        parameters.extend(values)
        terms.append(sql.SQL('(page_access.id IS NOT NULL AND resource.id IN (SELECT id FROM {}))').format(name))
        candidates.append(sql.SQL('SELECT id FROM {}').format(name))
        # Metadata hits already satisfy this leaf. Keep file-only candidates
        # separate; page attribution and ranking still inspect their files.
        # The metadata PK/FK and disjoint configuration branches make this
        # exact-count coverage check equivalent to an anti-join existence test.
        file_guard = sql.SQL('(SELECT count(*) FROM {}) < (SELECT count(*) FROM records)').format(name)
        record_guard = sql.SQL('NOT EXISTS (SELECT 1 FROM {} metadata WHERE metadata.id=component.record_id)').format(name)
    if 'components' in sources:
        statement, values = _indexed_ids(
            'digital_component_search_chunks', 'digital_component_id', leaf.query,
            ('pg_catalog.simple', 'pg_catalog.english', 'pg_catalog.arabic'),
        )
        name = sql.Identifier(f'text_components_{index}')
        ctes.append(sql.SQL('''{} AS MATERIALIZED (
            SELECT DISTINCT id FROM (
            SELECT component.record_id AS id,
                   document.status IN ('indexed','processing') AND document.indexed_at IS NOT NULL
                   AND document.content_set_id=component.active_content_set_id AS searchable
            FROM (
                SELECT id FROM digital_components
                WHERE to_tsvector('pg_catalog.simple', coalesce(file_name,''))
                    @@ websearch_to_tsquery('pg_catalog.simple',%s)
                UNION SELECT id FROM ({}) chunks
            ) file JOIN digital_components component ON component.id=file.id
            JOIN digital_component_search_documents document ON document.digital_component_id=file.id
            WHERE ({}) AND ({})
            -- Keep the correlated content equality out of join selectivity.
            -- Without this boundary PostgreSQL estimated one matching file
            -- and nested-looped across the broad candidate set.
            OFFSET 0) component_rows WHERE searchable
        )''').format(name, statement, file_guard, record_guard))
        parameters.extend((leaf.query, *values))
        terms.append(sql.SQL('(coalesce(page_access.can_view_component,false) AND resource.id IN (SELECT id FROM {}))').format(name))
        candidates.append(sql.SQL('SELECT id FROM {}').format(name))
    return sql.SQL('({})').format(sql.SQL(' OR ').join(terms)), sql.SQL(' UNION ').join(candidates)


def _scores(resource, leaves, candidate_name='matched'):
    """Preserve Advanced Search's score formula, computing each language query once.

    In particular, do not score only chunks that match: exclusion queries can
    give a nonzero score to a nonmatching chunk. This retains the existing
    Advanced Search formula (which differs from Global Search's active-content
    score protection); changing that formula is a separate product decision.
    Narrow IDs flow through permissions, then vectors are reduced to scores in
    SQL. Python never downloads text vectors, evaluates criteria or ranks hits.
    """
    kind = 'record' if resource == 'records' else 'aggregation'
    definitions = [dict(ordinal=i, phrase=leaf.query,
                        metadata='metadata' in (leaf.sources or engine.FULL_TEXT_SOURCES[resource]),
                        components='components' in (leaf.sources or engine.FULL_TEXT_SOURCES[resource]))
                   for i, (_, leaf) in enumerate(leaves)]
    ctes = [sql.SQL("""leaves AS MATERIALIZED (
        SELECT * FROM jsonb_to_recordset(%s) AS leaf(ordinal int,phrase text,metadata boolean,components boolean)
    ), parsed AS MATERIALIZED (
        SELECT leaf.ordinal,config.oid::regconfig AS config,
               websearch_to_tsquery(config.oid::regconfig,phrase) AS query
        FROM leaves leaf CROSS JOIN pg_catalog.pg_ts_config config
    )""")]

    def parsed_query(alias, ordinal):
        # A config join carried wide vectors into an external sort and hid
        # candidate cardinality. Scalar common-config lookups are initplans;
        # the uncommon-config fallback still uses the document's own language.
        return sql.SQL("""CASE {alias}.text_search_config
            WHEN 'pg_catalog.simple'::regconfig THEN
                (SELECT query FROM parsed WHERE ordinal={ordinal} AND config='pg_catalog.simple'::regconfig)
            WHEN 'pg_catalog.english'::regconfig THEN
                (SELECT query FROM parsed WHERE ordinal={ordinal} AND config='pg_catalog.english'::regconfig)
            WHEN 'pg_catalog.arabic'::regconfig THEN
                (SELECT query FROM parsed WHERE ordinal={ordinal} AND config='pg_catalog.arabic'::regconfig)
            ELSE (SELECT query FROM parsed WHERE ordinal={ordinal} AND config={alias}.text_search_config) END
        """).format(alias=sql.Identifier(alias), ordinal=sql.Literal(ordinal))

    metadata = [d for d in definitions if d['metadata']]
    components = [d for d in definitions if d['components']]
    joins = []
    if metadata:
        columns = [sql.SQL('ts_rank_cd(document.search_vector,{}) AS {}').format(
            parsed_query('document', d['ordinal']), sql.Identifier(f"score_{d['ordinal']}")) for d in metadata]
        # As with chunk scores, retain the numeric batch once. A final join
        # estimated as one row can otherwise rescore every metadata document
        # for each actual candidate; OFFSET 0 is not an execution-count bound.
        ctes.append(sql.SQL("""metadata_scores AS MATERIALIZED (
            SELECT matched.id,{} FROM {} matched JOIN {} document ON document.{}=matched.id OFFSET 0
        )""").format(sql.SQL(',').join(columns), sql.Identifier(candidate_name), sql.Identifier(f'authorized_{kind}_search_documents'),
                     sql.Identifier(f'{kind}_id')))
        joins.append(sql.SQL('LEFT JOIN metadata_scores metadata USING(id)'))
    if components:
        ctes.append(sql.SQL("""eligible_components AS MATERIALIZED (
            SELECT document.record_id AS id,document.digital_component_id
            FROM {} matched JOIN digital_component_search_documents document ON document.record_id=matched.id
            WHERE document.status IN ('indexed','processing') AND document.indexed_at IS NOT NULL
        ), component_scan_strategy AS MATERIALIZED (
            SELECT count(*) > greatest(1000,(
                SELECT greatest(reltuples,0)*0.05 FROM pg_class WHERE oid='digital_components'::regclass
            )) AS bulk FROM eligible_components
        )""").format(sql.Identifier(candidate_name)))
        columns = [sql.SQL('ts_rank_cd(chunk.search_vector,{}) AS {}').format(
            parsed_query('chunk', d['ordinal']), sql.Identifier(f"score_{d['ordinal']}")) for d in components]
        # The measured broad plan did one chunk index lookup per record and
        # spilled vectors through its language join. As in Global Search, use
        # the actual eligible-file count to choose indexed or bulk retrieval,
        # and reduce vectors to narrow scores before any downstream joins.
        # This does not cap candidates or change the legacy score eligibility.
        # The same protection as Global Search: misleading selective-query
        # estimates can otherwise run the entire chunk-scoring batch for each
        # candidate. Retain only IDs and numeric per-leaf scores once, and also
        # retain the completed per-record aggregate before its final join.
        ctes.append(sql.SQL("""scored_component_chunks AS MATERIALIZED (
            SELECT chunk.digital_component_id, {columns}
            FROM digital_component_search_chunks chunk
            WHERE NOT (SELECT bulk FROM component_scan_strategy)
              AND chunk.digital_component_id=ANY(ARRAY(SELECT digital_component_id FROM eligible_components))
            UNION ALL
            SELECT chunk.digital_component_id, {columns}
            FROM (SELECT digital_component_id,search_vector,text_search_config
                  FROM digital_component_search_chunks OFFSET 0) chunk
            WHERE (SELECT bulk FROM component_scan_strategy)
              AND chunk.digital_component_id IN (SELECT digital_component_id FROM eligible_components)
            OFFSET 0
        ), component_scores AS MATERIALIZED (
            SELECT eligible.id,{aggregates}
            FROM eligible_components eligible JOIN scored_component_chunks chunk USING(digital_component_id)
            GROUP BY eligible.id
        )""").format(columns=sql.SQL(',').join(columns), aggregates=sql.SQL(',').join(
            sql.SQL('max(chunk.{0}) AS {0}').format(sql.Identifier(f"score_{d['ordinal']}")) for d in components)))
        joins.append(sql.SQL('LEFT JOIN component_scores components USING(id)'))
    # Preserve left-to-right float4 addition: summing unordered partial
    # aggregates can perturb equal-score ordering with multiple FTS leaves.
    terms = [sql.SQL('coalesce({}.{},0)').format(sql.Identifier(source), sql.Identifier(f"score_{d['ordinal']}"))
             for d in definitions for source in ('metadata', 'components') if d[source]]
    ctes.append(sql.SQL('scores AS MATERIALIZED (SELECT matched.id,({})::double precision AS score FROM {} matched {})').format(
        sql.SQL(' + ').join(terms), sql.Identifier(candidate_name), sql.SQL(' ').join(joins)))
    return sql.SQL(',').join(ctes), [Jsonb(definitions)]


def _source(resource, request):
    # Search views also project effective holds through a correlated lateral
    # aggregate. PostgreSQL cannot remove that aggregate even for SELECT id;
    # using the display view for broad candidates ran it 153,009 times. Use the
    # base relation for ordinary fields, and hydrate only the selected page.
    # Derived-field queries retain their existing projection semantics.
    needs_projection = bool(requested_fields(request) & (HOLD_FIELDS | LOCATION_FIELDS))
    table = 'search_resources' if needs_projection else resource
    source = sql.SQL('{} resource').format(sql.Identifier(table))
    if resource == 'aggregations' and any(field.startswith('effective_retention.') for field in requested_fields(request)):
        source += sql.SQL(' LEFT JOIN search_retention_values search_retention ON search_retention.id=resource.id')
    return source


def _statement(resource, request, canonical, display_filter, hits, cap):
    """Rank once on submission; on paging restrict all work to the saved IDs."""
    sole_expression = request.where
    while sole_expression is not None:
        children = sole_expression.and_ or sole_expression.or_
        if not children or len(children) != 1:
            break
        sole_expression = children[0]
    if (hits is None and sole_expression is not None and sole_expression.full_text is not None
            and not display_filter and canonical['sort'] == [
                {'field': '_relevance', 'direction': 'desc'}, {'field': 'id', 'direction': 'asc'}]):
        # A standalone relevance search needs the same candidate/ACL pipeline
        # as Global Search. The generic Boolean compiler otherwise rejoins the
        # whole candidate/resource set while matching, scoring AND sorting.
        # Reuse its compact ranked IDs, retaining Advanced Search's historical
        # score eligibility (matching permissions remain identical).
        ranked, parameters = engine._indexed_global_ranking(
            resource, sole_expression.full_text, cap + 1, protect_component_scores=False)
        prefix = [sql.SQL('''ranked AS MATERIALIZED (
            SELECT result.*,row_number() OVER (ORDER BY score DESC,id) AS ordinal FROM ({}) result
        )''').format(ranked)]
        return _project_page(resource, request, prefix, parameters, cap)
    parameters = []
    match_ctes = []
    match_parameters = []
    predicate = None
    text_candidates = None
    if hits is None:
        def predicate(leaf):
            nonlocal text_candidates
            clause, candidate_query = _indexed_leaf(leaf, resource, match_ctes, match_parameters)
            if request.where is not None and request.where.full_text is leaf:
                # A standalone positive leaf's text matches safely bound the
                # ACL work. Do not apply this shortcut to NOT/OR trees: their
                # authorized Boolean meaning can include nonmatching records.
                text_candidates = candidate_query
            return clause, []
    clauses = []
    where_parameters = []
    if request.where is not None:
        clause, where_parameters = engine._compile_expression(
            request.where, engine.SEARCH_FIELDS[resource], resource=resource, depth=1,
            condition_counter=[0], batch_permissions=True, full_text_predicate=predicate,
        )
        clauses.append(clause)
    if hits is None:
        # Structured criteria may narrow candidates before permission resolution.
        # A component predicate cannot move here: it requires the shared ACL set.
        prefilter = sql.SQL('')
        if (request.where is not None and not engine._full_text_leaves(request.where, positive=True)
                and not engine._full_text_leaves(request.where, positive=False)
                and not engine._expression_has_component_field(request.where)):
            prefilter = sql.SQL(' WHERE ') + clauses[0]
            parameters.extend(where_parameters)
        source = _source(resource, request)
        candidates = (sql.SQL('candidate_ids AS MATERIALIZED ({})').format(text_candidates)
                      if text_candidates is not None else
                      sql.SQL('candidate_ids AS MATERIALIZED (SELECT resource.id FROM {}{})').format(source, prefilter))
    else:
        candidates = sql.SQL('''saved AS MATERIALIZED (
            SELECT (value->>'id')::bigint AS id,(value->>'score')::double precision AS score,ordinality AS ordinal
            FROM jsonb_array_elements(%s) WITH ORDINALITY
        ), candidate_ids AS MATERIALIZED (SELECT id FROM saved)''')
        parameters.append(Jsonb(hits))
    kind = resource[:-1]
    permission_sets = sql.SQL(visibility_ctes(candidate_resource=resource, component_access=True))
    # Keep page-only projection views out of the full candidate pass. This is
    # the same canonical batch ACL used by Global Search, not a second policy.
    documents = sql.SQL('''authorized_{}_search_documents AS NOT MATERIALIZED (
        SELECT document.* FROM {} document JOIN {} access ON access.id=document.{}
    )''').format(sql.SQL(kind), sql.Identifier(f'{kind}_search_documents'),
                  sql.Identifier(f'authorized_{resource}'), sql.Identifier(f'{kind}_id'))
    prefix = [*projection_ctes(resource, request), candidates, permission_sets, documents, *match_ctes]
    parameters.extend(match_parameters)
    access = sql.SQL('page_access.id IS NOT NULL')
    if engine._filters_disposition(request.where):
        access = sql.SQL("(page_access.id IS NOT NULL OR (resource.disposition_status=10 AND disposition_private.retained_access({},resource.id,false)))").format(sql.Literal(resource[:-1]))
    clauses.append(access)
    source = _source(resource, request)
    source += sql.SQL(' JOIN candidate_ids candidate ON candidate.id=resource.id LEFT JOIN {} page_access ON page_access.id=resource.id').format(sql.Identifier(f'authorized_{resource}'))
    if display_filter:
        if resource == 'records':
            prefix.append(sql.SQL('main_candidate_ids AS MATERIALIZED (SELECT id FROM candidate_ids)'))
            prefix.append(sql.SQL('''visible_parents AS MATERIALIZED (
                WITH RECURSIVE candidate_ids AS MATERIALIZED (
                    SELECT DISTINCT aggregation_id AS id FROM records WHERE id IN (SELECT id FROM main_candidate_ids)
                ), {} SELECT id FROM authorized_aggregations
            )''').format(sql.SQL(visibility_ctes(candidate_resource='aggregations', ordinary_access=True))))
            source += sql.SQL(' LEFT JOIN aggregations parent ON parent.id=resource.aggregation_id AND parent.id IN (SELECT id FROM visible_parents)')
        columns = ('resource.record_number,resource.title,resource.medium,parent.aggregation_number,parent.title'
                   if resource == 'records' else 'resource.aggregation_number,resource.title,resource.medium')
        clauses.append(sql.SQL("concat_ws(' ', {}) ILIKE %s ESCAPE '\\'").format(sql.SQL(columns)))
        where_parameters.append(f'%{engine._escape_like(display_filter)}%')
    prefix.append(sql.SQL('matched AS MATERIALIZED (SELECT resource.id FROM {} WHERE {})').format(source, sql.SQL(' AND ').join(clauses)))
    parameters.extend(where_parameters)
    leaves = engine._full_text_leaves(request.where)
    if hits is None:
        score = sql.SQL('coalesce(scores.score,0)' if leaves else '0.0::double precision')
        join_scores = sql.SQL(' LEFT JOIN scores ON scores.id=resource.id' if leaves else '')
        sorts = []
        for item in canonical['sort']:
            field = item['field']
            term = score if field == '_relevance' else sql.SQL('resource.{}').format(sql.Identifier(field))
            if display_filter is not None and field != '_relevance' and engine.SEARCH_FIELDS[resource][field].type is engine.FieldType.TEXT:
                term = sql.SQL('lower({})').format(term)
            sorts.append(sql.SQL('{} {}').format(term, sql.SQL(item['direction'].upper())))
        order = sql.SQL(', ').join(sorts)
        ranking_candidates = 'matched'
        if leaves and all(item['field'] != '_relevance' for item in canonical['sort']):
            # With a field sort, relevance cannot affect membership/order. Match
            # and authorize every candidate, select the capped order in SQL,
            # then compute the unchanged score only for those retained rows.
            # Never apply this reduction to relevance sorting.
            ranking_candidates = 'score_candidates'
            prefix.append(sql.SQL('''score_candidates AS MATERIALIZED (
                SELECT resource.id FROM {} JOIN matched ON matched.id=resource.id ORDER BY {} LIMIT %s
            )''').format(_source(resource, request), order))
            parameters.append(cap + 1)
        if leaves:
            scores, values = _scores(resource, leaves, ranking_candidates)
            prefix.append(scores)
            parameters.extend(values)
        prefix.append(sql.SQL('''ranked AS MATERIALIZED (
            SELECT resource.id,{} AS score,row_number() OVER (ORDER BY {}) AS ordinal
            FROM {} JOIN {} matched ON matched.id=resource.id {}
            ORDER BY {} LIMIT %s
        )''').format(score, order, _source(resource, request), sql.Identifier(ranking_candidates), join_scores, order))
        parameters.append(cap + 1)
    else:
        prefix.append(sql.SQL('ranked AS MATERIALIZED (SELECT saved.* FROM saved JOIN matched USING(id))'))
    return _project_page(resource, request, prefix, parameters, cap)


def _project_page(resource, request, prefix, parameters, cap):
    """Hydrate the selected page and serialize the same bounded ranked list."""
    prefix.append(sql.SQL('''capped AS MATERIALIZED (SELECT * FROM ranked ORDER BY ordinal LIMIT %s),
        summary AS (SELECT count(*) AS total,LEAST(%s / %s,GREATEST(count(*)-1,0) / %s) * %s AS page_offset FROM capped),
        page AS MATERIALIZED (SELECT * FROM capped ORDER BY ordinal LIMIT %s OFFSET (SELECT page_offset FROM summary))'''))
    parameters.extend((cap, min(request.offset, cap-1), request.limit, request.limit, request.limit, request.limit))
    statement = sql.SQL('''WITH RECURSIVE {} SELECT resource.*,page.score AS _fts_relevance,
        CASE WHEN page.id IS NOT DISTINCT FROM (SELECT id FROM page ORDER BY ordinal LIMIT 1)
             THEN (SELECT jsonb_agg(jsonb_build_object('id',id,'score',score) ORDER BY ordinal) FROM capped)
        END AS _cache_hits,
        (SELECT count(*)>%s FROM ranked) AS _cache_truncated,
        summary.total AS _cache_total,summary.page_offset AS _cache_offset
        FROM summary LEFT JOIN page ON true LEFT JOIN {} resource ON resource.id=page.id
        ORDER BY page.ordinal''').format(sql.SQL(', ').join(prefix), sql.Identifier(f'authorized_{resource}_for_search'))
    parameters.append(cap)
    return statement, parameters


def pending_content(connection):
    statement = sql.SQL('''WITH RECURSIVE candidate_ids AS MATERIALIZED (
        SELECT DISTINCT record_id AS id FROM digital_component_search_documents
        WHERE status IN ('pending','processing','stale')
    ), {} SELECT EXISTS(SELECT 1 FROM authorized_records WHERE can_view_component) AS value''').format(
        sql.SQL(visibility_ctes(candidate_resource='records', component_access=True)))
    return bool(connection.execute(statement, prepare=False).fetchone()['value'])


@interactive_search
def cached_search_rows(connection, resource, request, *, session_id, user_id, endpoint,
                       display_filter, max_results, cache_version):
    if session_id is None or user_id is None:
        raise HTTPException(status_code=401, detail='authentication required')
    settings = settings_cache.for_connection(connection)
    leaves = engine._full_text_leaves(request.where)
    if leaves and not settings['FULL_TEXT_SEARCH_ENABLED']:
        raise HTTPException(status_code=503, detail={'code': 'full_text_search_disabled'})
    canonical = engine.canonicalize_search_request(connection, resource, request)
    canonical.pop('offset', None)
    canonical.pop('limit', None)
    cap = min(max_results or settings['SEARCH_RESULT_LIMIT'], settings['SEARCH_RESULT_LIMIT'])
    idle = settings['GLOBAL_SEARCH_CACHE_IDLE_MINUTES']
    fingerprint = hashlib.sha256(json.dumps(
        [resource, endpoint, canonical, display_filter, cache_version, cap, idle,
         settings.versions['SEARCH_RESULT_LIMIT'], settings.versions['GLOBAL_SEARCH_CACHE_IDLE_MINUTES']],
        sort_keys=True, separators=(',', ':'), ensure_ascii=False,
    ).encode()).hexdigest()
    hits = None
    truncated = False
    search_id = request.search_id
    if search_id is not None:
        try:
            hits, truncated = engine._read_global_search(
                connection, session_id, user_id, request.tab_id, search_id, fingerprint, True, idle,
            )
        except HTTPException as error:
            if error.status_code != 410:
                raise
            # Expiry, a crash of the UNLOGGED table, replacement by another
            # screen, or changed settings all rebuild the submitted criteria.
            # A foreign user's token never selects their list; it is a miss.
    statement, parameters = _statement(resource, request, canonical, display_filter, hits, cap)
    rows = connection.execute(statement, parameters, prepare=False).fetchall()
    row = rows[0]
    saved_hits, total, offset = row['_cache_hits'] or [], row['_cache_total'], row['_cache_offset']
    if hits is None:
        truncated = row['_cache_truncated']
        search_id = engine._save_global_search(
            connection, saved_hits, truncated, session_id, user_id, request.tab_id,
            fingerprint, True, idle,
        )
    items = redact_hidden_relationships(connection, resource, [item for item in rows if item['id'] is not None])
    for item in items:
        for key in ('_cache_hits', '_cache_total', '_cache_truncated', '_cache_offset'):
            item.pop(key, None)
    kind = resource[:-1]
    details = page_details(connection, [(kind, item) for item in items], {kind: leaves}) if items else {}
    for item in items:
        item.pop('effective_hold_ids', None)
        item.pop('ordinal', None)
        score = item.pop('_fts_relevance', 0.0)
        detail = details[kind, item['id']]
        if resource == 'records':
            item['_capabilities'] = {key: detail[key] for key in ('list_components', 'has_previewable_component', 'component_count')}
        if 'full_text_matches' in request.include:
            # This is only the selected page; matching evidence is batched above.
            item['_search'] = {'relevance': score, 'metadata_matched': detail['metadata_matched'],
                               'matching_components': detail['matching_components']} if resource == 'records' else {
                                   'relevance': score, 'metadata_matched': detail['metadata_matched'], 'matching_components': []}
    result = dict(items=items, total=total, offset=offset, limit=request.limit,
                  returned=len(items), result_cap=cap, truncated=truncated, search_id=str(search_id))
    if leaves or engine._full_text_leaves(request.where, positive=False):
        result['index_freshness'] = {'has_pending_content': pending_content(connection) if resource == 'records' else False}
    if request.debug:
        result['_debug'] = engine._debug(connection, endpoint, request.model_dump(mode='json', by_alias=True, exclude_none=True), canonical)
    return result
