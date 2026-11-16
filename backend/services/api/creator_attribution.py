"""Creator snapshots for resource rows that have already been authorized and paged."""

from collections.abc import Iterable
import logging
from typing import Any

from psycopg import Connection, Error

from .entity_localization import localized_projection


logger = logging.getLogger(__name__)
RESOURCE_KINDS = {"aggregations": "aggregation", "records": "record"}

CREATOR_NAMES_SQL = """WITH viewer_language AS MATERIALIZED (
                       SELECT coalesce(
                           (SELECT language.language_tag
                              FROM user_preferences preference
                              JOIN supported_languages language USING(language_tag)
                             WHERE preference.user_id=current_user_id() AND language.is_enabled),
                           (SELECT language_tag FROM supported_languages
                             WHERE is_enabled ORDER BY is_default DESC,id LIMIT 1), 'en'
                       ) AS tag
                   ) SELECT page.kind,page.id,viewer_language.tag,
                            coalesce(creator.name,nullif(btrim(creation.actor_name),'')) AS name,
                            creator.translations
                     FROM unnest(%s::text[],%s::bigint[]) AS page(kind,id)
                     CROSS JOIN viewer_language
                     CROSS JOIN LATERAL (
                         SELECT event.actor_user_id,event.actor_name
                           FROM event_history event
                          WHERE event.entity_type=page.kind AND event.entity_id=page.id
                            AND event.operation='CREATE'
                          ORDER BY event.occurred_at,event.id LIMIT 1
                     ) creation
                     LEFT JOIN users creator ON creator.id=creation.actor_user_id"""


def add_creator_names(
    connection: Connection,
    page: Iterable[tuple[str, dict[str, Any]]],
    *,
    id_key: str = "id",
) -> None:
    """Decorate only returned, visible resources, with one optional SQL statement.

    Resource visibility is the disclosure rule. Callers must supply the final
    authorized page, using a null ID for a redacted resource. Audit privileges
    do not apply to this single field; the rest of the event is never selected.
    """
    rows = [(kind, row) for kind, row in page if row.get(id_key) is not None]
    if not rows:
        return
    keys = list(dict.fromkeys((kind, row[id_key]) for kind, row in rows))
    kinds, ids = zip(*keys, strict=True)
    try:
        # An unavailable history lookup must not invalidate the listing or
        # leave its transaction aborted.
        with connection.transaction():
            names = connection.execute(
                CREATOR_NAMES_SQL,
                (list(kinds), list(ids)),
            ).fetchall()
    except Error:
        logger.warning("Creator snapshots could not be loaded for a resource page", exc_info=True)
        return
    by_key = {
        (entry["kind"], entry["id"]): localized_projection(entry, entry["tag"], "name")["name"]
        for entry in names if entry["name"]
    }
    for kind, row in rows:
        name = by_key.get((kind, row[id_key]))
        if name:
            row["created_by"] = name


def add_resource_page_creators(connection: Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if kind := RESOURCE_KINDS.get(table):
        add_creator_names(connection, ((kind, row) for row in rows))
