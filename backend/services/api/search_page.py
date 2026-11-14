"""Statement-local permissions and enrichment for a Global Search page."""

from psycopg import sql
from psycopg.types.json import Jsonb

from .component_pages import PREVIEWABLE
from .dashboard_visibility import visibility_ctes


def page_permission_ctes():
    """The caller supplies page_record_ids and page_aggregation_ids CTEs."""
    return sql.SQL(visibility_ctes(component_access=True, page_access=True)) + sql.SQL(""",
        authorized_record_search_documents AS MATERIALIZED (
            SELECT document.* FROM record_search_documents document
            JOIN authorized_records access ON access.id=document.record_id
        ), authorized_aggregation_search_documents AS MATERIALIZED (
            SELECT document.* FROM aggregation_search_documents document
            JOIN authorized_aggregations access ON access.id=document.aggregation_id
        )
    """)


def page_details(connection, page, leaves_by_kind):
    """One query for all snippets, parent labels and the two display flags.

    SQL matches/scores/orders the evidence. Python below only assembles the
    already bounded evidence using the existing filename-before-content rule.
    No permission result survives this request.
    """
    leaves = [
        {"kind": kind, "leaf_id": leaf_id, "ordinal": ordinal, "phrase": leaf.query,
         "metadata": "metadata" in (leaf.sources or ["metadata", "components"]),
         "components": kind == "record" and "components" in (leaf.sources or ["metadata", "components"])}
        for kind, kind_leaves in leaves_by_kind.items()
        for ordinal, (leaf_id, leaf) in enumerate(kind_leaves)
    ]
    statement = sql.SQL("""
        WITH RECURSIVE page AS MATERIALIZED (
            SELECT * FROM jsonb_to_recordset(%s) AS item(kind text, id bigint)
        ), page_record_ids AS MATERIALIZED (
            SELECT id FROM page WHERE kind='record'
        ), page_aggregation_ids AS MATERIALIZED (
            SELECT id FROM page WHERE kind='aggregation'
            UNION SELECT aggregation_id FROM records JOIN page_record_ids USING(id)
        ), {permissions}, leaves AS MATERIALIZED (
            SELECT * FROM jsonb_to_recordset(%s) AS leaf(
                kind text, leaf_id text, ordinal integer, phrase text, metadata boolean, components boolean)
        ), parsed AS MATERIALIZED (
            SELECT leaf.*, config.oid::regconfig AS config,
                   websearch_to_tsquery(config.oid::regconfig, leaf.phrase) AS query
            FROM leaves leaf CROSS JOIN pg_catalog.pg_ts_config config
        ), record_evidence AS MATERIALIZED (
            SELECT access.id, leaf.ordinal, leaf.leaf_id,
                   coalesce(leaf.metadata AND metadata.search_vector @@ query.query, false) AS metadata_matched,
                   files.items AS files, chunks.items AS chunks
            FROM authorized_records access
            JOIN leaves leaf ON leaf.kind='record'
            LEFT JOIN authorized_record_search_documents metadata ON metadata.record_id=access.id
            LEFT JOIN parsed query ON query.kind=leaf.kind AND query.ordinal=leaf.ordinal
                                  AND query.config=metadata.text_search_config
            LEFT JOIN LATERAL (
                SELECT jsonb_agg(to_jsonb(matched) ORDER BY matched.id) AS items FROM (
                    SELECT component.id,component.file_name,component.mime_type,component.content_status
                    FROM digital_components component
                    WHERE component.record_id=access.id AND access.can_view_component AND leaf.components
                      AND component.content_status='available'
                      AND to_tsvector('pg_catalog.simple',coalesce(component.file_name,'')) @@ (
                          SELECT query FROM parsed WHERE kind=leaf.kind AND ordinal=leaf.ordinal
                            AND config='pg_catalog.simple'::regconfig)
                    ORDER BY component.id LIMIT 4
                ) matched
            ) files ON true
            LEFT JOIN LATERAL (
                SELECT jsonb_agg(jsonb_build_object(
                    'id',matched.id,'file_name',matched.file_name,'mime_type',matched.mime_type,
                    'content_status',matched.content_status,
                    'match_count_is_capped',matched.match_count_is_capped,
                    'snippet',ts_headline(matched.config,matched.extracted_text,matched.query,
                        'StartSel=⟦,StopSel=⟧,MaxWords=35,MinWords=12,MaxFragments=1'))
                    ORDER BY matched.score DESC,matched.id,matched.chunk_no) AS items
                FROM (
                    -- Keep the same top-12 evidence window and capped flag,
                    -- but create a headline only for the first chunk of each
                    -- component. Python previously discarded the other 9/11
                    -- headlines for multi-chunk files after paying to parse
                    -- their text. The ordering below selects exactly the same
                    -- snippet and component order as that existing behavior.
                    SELECT selected.*,
                           row_number() OVER (PARTITION BY id ORDER BY score DESC,chunk_no) AS component_position,
                           count(*) OVER () >= 12 AS match_count_is_capped
                    FROM (
                    SELECT component.id,component.file_name,component.mime_type,component.content_status,
                           chunk.chunk_no,chunk.extracted_text,query.config,query.query,
                           ts_rank_cd(chunk.search_vector,query.query) AS score
                    FROM digital_components component
                    JOIN digital_component_search_documents document ON document.digital_component_id=component.id
                    JOIN digital_component_search_chunks chunk ON chunk.digital_component_id=component.id
                    JOIN parsed query ON query.kind=leaf.kind AND query.ordinal=leaf.ordinal
                                     AND query.config=chunk.text_search_config
                    WHERE component.record_id=access.id AND access.can_view_component AND leaf.components
                      AND document.status IN ('indexed','processing') AND document.indexed_at IS NOT NULL
                      AND document.content_set_id=component.active_content_set_id
                      AND chunk.search_vector @@ query.query
                    ORDER BY score DESC,component.id,chunk.chunk_no LIMIT 12
                    ) selected
                ) matched
                WHERE matched.component_position=1
            ) chunks ON true
        )
        SELECT page.kind,page.id,
               CASE WHEN page.kind='record' THEN (
                   SELECT aggregation_number FROM aggregations parent
                   JOIN authorized_aggregations access ON access.id=parent.id
                   WHERE parent.id=record.aggregation_id) END AS aggregation_number,
               coalesce(access.can_list_components,false) AS list_components,
               CASE WHEN access.can_list_components THEN (
                   SELECT count(*) FROM digital_components WHERE record_id=page.id
               ) ELSE 0 END AS component_count,
               coalesce(access.can_list_components AND access.can_view_component,false)
                 AND EXISTS(SELECT 1 FROM digital_components WHERE record_id=page.id AND ({previewable}))
                   AS has_previewable_component,
               (SELECT jsonb_agg(to_jsonb(evidence) ORDER BY ordinal)
                FROM record_evidence evidence WHERE evidence.id=page.id AND page.kind='record') AS evidence,
               page.kind='aggregation' AND EXISTS (
                   SELECT 1 FROM authorized_aggregation_search_documents document
                   JOIN parsed query ON query.kind='aggregation' AND query.metadata
                                     AND query.config=document.text_search_config
                   WHERE document.aggregation_id=page.id AND document.search_vector @@ query.query
               ) AS aggregation_metadata_matched,
               CASE WHEN page.kind='aggregation' THEN (
                   SELECT ts_headline('pg_catalog.simple',concat_ws(' ',aggregation_number,title,description),
                       (SELECT query FROM parsed WHERE kind='aggregation' AND ordinal=0
                          AND config='pg_catalog.simple'::regconfig),
                       'StartSel=⟦,StopSel=⟧,MaxWords=35,MinWords=12,MaxFragments=1')
                   FROM aggregations aggregation JOIN authorized_aggregations access ON access.id=aggregation.id
                   WHERE aggregation.id=page.id) END AS snippet
        FROM page
        LEFT JOIN records record ON page.kind='record' AND record.id=page.id
        LEFT JOIN authorized_records access ON page.kind='record' AND access.id=page.id
    """).format(permissions=page_permission_ctes(), previewable=PREVIEWABLE)
    rows = connection.execute(statement, (
        Jsonb([{"kind": kind, "id": row["id"]} for kind, row in page]), Jsonb(leaves),
    ), prepare=False).fetchall()
    details = {}
    for row in rows:
        components = {}
        metadata_matched = row.pop("aggregation_metadata_matched")
        for evidence in row.pop("evidence") or []:
            leaf_id = evidence["leaf_id"]
            metadata_matched |= evidence["metadata_matched"]
            files, chunks = evidence["files"] or [], evidence["chunks"] or []
            for component in files:
                if component["id"] not in components and len(components) < 3:
                    components[component["id"]] = {
                        **component, "snippet": None, "leaf_ids": [leaf_id],
                        "match_count_is_capped": len(files) > 3,
                    }
            for component in chunks:
                identifier = component["id"]
                if identifier not in components and len(components) < 3:
                    components[identifier] = {
                        **component, "leaf_ids": [leaf_id],
                    }
                elif identifier in components and leaf_id not in components[identifier]["leaf_ids"]:
                    components[identifier]["leaf_ids"].append(leaf_id)
                if identifier in components and not components[identifier].get("snippet"):
                    components[identifier]["snippet"] = component["snippet"]
        details[row["kind"], row["id"]] = {
            **row, "metadata_matched": metadata_matched, "matching_components": list(components.values()),
        }
    return details
