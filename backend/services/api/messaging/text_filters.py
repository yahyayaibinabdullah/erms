"""SQL predicates for the searchable, user-visible text of a mailbox item."""

from dataclasses import dataclass

from fastapi import HTTPException
from psycopg import sql
from ..application_settings import cache as settings_cache
from ..dashboard_visibility import visibility_ctes
from ..search import _indexed_text_ids
from ..search_execution import search_sql_execution


@dataclass(frozen=True)
class TextFilters:
    q: str = ""
    body_q: str = ""
    linked_q: str = ""

    def predicates(self, *, subject: str, body: str):
        clauses = []
        args = []
        if self.q.strip():
            # Keep the existing Outbox subject pattern API.
            clauses.append(f"{subject} ILIKE %s")
            args.append(f"%{self.q}%")
        if term := " ".join(self.body_q.split()):
            # Stored HTML is already sanitized. Replace block boundaries with
            # spaces, drop markup (including resource markers), then decode the
            # three entities emitted by the sanitizer's text serializer.
            plain = (
                "regexp_replace(replace(replace(replace(replace("
                f"regexp_replace(regexp_replace({body}, "
                "'</?(p|br|li|ul|ol|h[123]|blockquote|pre)>', ' ', 'g'), "
                "'<[^>]+>', '', 'g'), '&lt;', '<'), '&gt;', '>'), '&amp;', '&'), "
                "chr(160), ' '), '[[:space:]]+', ' ', 'g')"
            )
            clauses.append(f"{plain} ILIKE %s")
            args.append("%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        return clauses, args


def mailbox_page(
    connection, *, projection, projection_args, source, source_args=(), clauses, args,
    order, limit, linked_query, row_id, envelope_id, level, draft=False,
):
    conditions = " AND ".join(clauses)
    result = f"SELECT {projection} FROM {source} WHERE "
    tail = f" ORDER BY {order} LIMIT %s"
    if not linked_query.strip():
        return connection.execute(result + conditions + tail,
                                  (*projection_args, *source_args, *args, limit)).fetchall()
    if not settings_cache.for_connection(connection)["FULL_TEXT_SEARCH_ENABLED"]:
        raise HTTPException(status_code=503, detail={
            "code": "full_text_search_disabled",
            "message": "Full-text search is temporarily disabled.",
        })

    # Envelopes and drafts use separate link tables. Only SQL owned by these
    # mailbox readers can supply the projection, aliases and filter predicates.
    link_table = "message_draft_resource_links" if draft else "message_resource_links"
    owner = "draft_id" if draft else "envelope_id"
    matches, match_args = _indexed_text_ids(
        "digital_component_search_chunks", "digital_component_id", linked_query,
        ("pg_catalog.simple", "pg_catalog.english", "pg_catalog.arabic"),
        candidates=sql.SQL("SELECT id FROM eligible_components"),
    )
    aggregation_matches, aggregation_args = _indexed_text_ids(
        "aggregation_search_documents", "aggregation_id", linked_query, ("pg_catalog.simple",),
        candidates=sql.SQL("SELECT id FROM eligible_aggregations"),
    )
    visibility = visibility_ctes(page_access=True, component_access=True)
    linked = sql.SQL(f"""
        WITH RECURSIVE mailbox_candidates AS MATERIALIZED (
            SELECT {row_id} AS id, {envelope_id} AS link_owner, {level} AS level_number
            FROM {source}
            WHERE {conditions} AND (SELECT messaging_user_clearance(current_user_id())) >= {level}
        ), scoped_links AS MATERIALIZED (
            SELECT mail.id, mail.level_number, link.record_id, link.aggregation_id
            FROM mailbox_candidates mail JOIN {link_table} link ON link.{owner}=mail.link_owner
            WHERE link.record_id IS NOT NULL OR link.aggregation_id IS NOT NULL
        ), page_aggregation_ids AS MATERIALIZED (
            SELECT DISTINCT aggregation_id AS id FROM scoped_links WHERE aggregation_id IS NOT NULL
        ), page_record_ids AS MATERIALIZED (
            SELECT DISTINCT record_id AS id FROM scoped_links WHERE record_id IS NOT NULL
        ), {visibility},
        eligible_aggregations AS MATERIALIZED (
            SELECT authorized.id, level.level_number
            FROM authorized_aggregations authorized JOIN aggregations resource USING (id)
            JOIN security_levels level ON level.id=resource.security_level_id
            JOIN (SELECT aggregation_id,max(level_number) AS message_level FROM scoped_links
                  WHERE aggregation_id IS NOT NULL GROUP BY aggregation_id) link ON link.aggregation_id=authorized.id
            WHERE level.level_number<=link.message_level
              AND (authorized.disposition_status NOT IN (11,12) OR (SELECT disposition_private.can_manage()))
        ), readable_records AS MATERIALIZED (
            SELECT authorized.id, level.level_number
            FROM authorized_records authorized JOIN records record USING (id)
            JOIN security_levels level ON level.id=record.security_level_id
            WHERE authorized.can_view_component
              AND (authorized.disposition_status NOT IN (11,12) OR (SELECT disposition_private.can_manage()))
        ), candidate_linked_records AS MATERIALIZED (
            SELECT record.id AS record_id FROM readable_records record
            JOIN (SELECT record_id, max(level_number) AS level_number
                  FROM scoped_links WHERE record_id IS NOT NULL GROUP BY record_id) link
              ON link.record_id=record.id
            WHERE record.level_number<=link.level_number
        ), eligible_components AS MATERIALIZED (
            SELECT component.id, record.record_id FROM candidate_linked_records record
            JOIN digital_component_search_documents document ON document.record_id=record.record_id
            JOIN digital_components component ON component.id=document.digital_component_id
              AND component.active_content_set_id=document.content_set_id
            WHERE document.status IN ('indexed', 'processing') AND document.indexed_at IS NOT NULL
        ), search_phrase AS MATERIALIZED (
            SELECT %s::text AS value
        ), search_query AS (
            SELECT websearch_to_tsquery('pg_catalog.english', value) AS english,
                   websearch_to_tsquery('pg_catalog.arabic', value) AS arabic
            FROM search_phrase
        ), other_search_queries AS MATERIALIZED (
            SELECT oid::regconfig AS config, websearch_to_tsquery(oid::regconfig, value) AS parsed
            FROM pg_catalog.pg_ts_config CROSS JOIN search_phrase
            WHERE oid NOT IN ('pg_catalog.simple'::regconfig, 'pg_catalog.english'::regconfig,
                              'pg_catalog.arabic'::regconfig)
        ), matching_files AS MATERIALIZED (
            SELECT DISTINCT id FROM ({{matches}}) file_hits
        ), found_records AS MATERIALIZED (
            SELECT DISTINCT record.id AS record_id, record.level_number
            FROM eligible_components eligible JOIN matching_files USING (id)
            JOIN readable_records record ON record.id=eligible.record_id
        ), matching_aggregations AS MATERIALIZED (
            SELECT DISTINCT id FROM ({{aggregation_matches}}) aggregation_hits
        ), found_mailbox AS (
            SELECT link.id FROM scoped_links link JOIN found_records record USING (record_id)
            WHERE record.level_number<=link.level_number
            UNION
            SELECT link.id FROM scoped_links link
            JOIN matching_aggregations match ON match.id=link.aggregation_id
            JOIN eligible_aggregations target ON target.id=match.id
            WHERE target.level_number<=link.level_number
        )
        {result} {row_id} IN (SELECT id FROM found_mailbox) {tail}
    """).format(matches=matches, aggregation_matches=aggregation_matches)
    with search_sql_execution(connection):
        return connection.execute(
            linked,
            (*source_args, *args, linked_query, *match_args, *aggregation_args,
             *projection_args, *source_args, limit),
            prepare=False,
        ).fetchall()
