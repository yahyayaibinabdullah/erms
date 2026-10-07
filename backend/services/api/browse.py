from __future__ import annotations

import base64
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg import Connection, sql

from .saved_searches import audience_eligibility_sql
from .search import record_destination_clause
from .database import get_connection
from .entity_localization import localized_projection, preferred_language
from .authorization_policy import require_organization_browse
from .schemas import (
    AggregationRead,
    BrowseAggregationNode,
    BrowseClassificationNode,
    BrowsePage,
    BrowseRecordNode,
    ClassificationSchemeRead,
)


router = APIRouter(prefix="/api/v1/browse", tags=["classification browser"])


ORG_UNIT_NODE_SQL = """
    WITH RECURSIVE ancestors AS (
        SELECT source.id AS source_id, source.id, source.parent_org_unit_id,
               source.status, source.code, source.name
          FROM org_units source
        UNION ALL
        SELECT ancestors.source_id, parent.id, parent.parent_org_unit_id,
               parent.status, parent.code, parent.name
          FROM ancestors
          JOIN org_units parent ON parent.id = ancestors.parent_org_unit_id
    )
    SELECT unit.id, unit.parent_org_unit_id, unit.code, unit.name, unit.translations,
           unit.description, unit.status, unit.date_created,
           unit.managing_role_id, unit.file_administrator_role_id,
           unit.date_deactivated, unit.version,
           CASE WHEN EXISTS (
               SELECT 1 FROM ancestors
                WHERE source_id=unit.id AND status='inactive'
           ) THEN 'inactive' ELSE 'active' END AS effective_status,
           (SELECT jsonb_build_object('id', inactive.id, 'code', inactive.code,
                                      'name', inactive.name)
              FROM ancestors inactive
             WHERE inactive.source_id=unit.id AND inactive.status='inactive'
             ORDER BY CASE WHEN inactive.id=unit.id THEN 0 ELSE 1 END, inactive.id
             LIMIT 1) AS inactive_source,
           (SELECT count(*) FROM org_units child
             WHERE child.parent_org_unit_id=unit.id) AS child_org_unit_count,
           (SELECT count(*) FROM roles role WHERE role.org_unit_id=unit.id) AS role_count
      FROM org_units unit
"""


ROLE_NODE_SQL = """
    WITH RECURSIVE ancestors AS (
        SELECT source.id AS source_id, source.id, source.parent_org_unit_id,
               source.status, source.code, source.name
          FROM org_units source
        UNION ALL
        SELECT ancestors.source_id, parent.id, parent.parent_org_unit_id,
               parent.status, parent.code, parent.name
          FROM ancestors
          JOIN org_units parent ON parent.id = ancestors.parent_org_unit_id
    )
    SELECT role.id, role.org_unit_id, role.supervisor_role_id, role.code,
           role.name, role.description, role.translations, role.status, role.date_created,
           role.date_deactivated, role.version, role.security_level_id,
           role.profile_id, role.is_information_governance, role.is_system,
           role.account_type_restriction,
           profile.code AS profile_code, profile.name AS profile_name,
           profile.translations AS profile_translations,
           security.code AS security_level_code,
           security.name AS security_level_name,
           security.translations AS security_level_translations,
           security.level_number AS security_level_number,
           unit.code AS org_unit_code, unit.name AS org_unit_name,
           unit.translations AS org_unit_translations,
           supervisor.code AS supervisor_role_code,
           supervisor.name AS supervisor_role_name,
           supervisor.translations AS supervisor_role_translations,
           CASE WHEN role.status='active' AND NOT EXISTS (
               SELECT 1 FROM ancestors
                WHERE source_id=role.org_unit_id AND status='inactive'
           ) THEN 'active' ELSE 'inactive' END AS effective_status,
           (SELECT count(*) FROM roles child
             WHERE child.supervisor_role_id=role.id) AS subordinate_role_count,
           (SELECT count(*) FROM user_role_assignments assignment
             WHERE assignment.role_id=role.id) AS assigned_user_count,
           (SELECT count(*) FROM user_role_assignments assignment
             WHERE assignment.role_id=role.id
               AND assignment.valid_from <= CURRENT_TIMESTAMP
               AND (assignment.valid_until IS NULL OR assignment.valid_until > CURRENT_TIMESTAMP)
           ) AS current_assignment_count
      FROM roles role
 LEFT JOIN org_units unit ON unit.id=role.org_unit_id
      JOIN security_levels security ON security.id=role.security_level_id
      JOIN profiles profile ON profile.id=role.profile_id
 LEFT JOIN roles supervisor ON supervisor.id=role.supervisor_role_id
"""


def _encode_cursor(scope: str, key: str, entity_id: int, query: str) -> str:
    payload = json.dumps(
        {"scope": scope, "key": key, "id": entity_id, "query": query},
        separators=(",", ":"), sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str | None, scope: str, query: str) -> tuple[str, int] | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if payload.get("scope") != scope or payload.get("query") != query:
            raise ValueError
        return str(payload["key"]), int(payload["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="invalid or mismatched browse cursor")


def _page(
    connection: Connection,
    *,
    scope: str,
    source_sql: str,
    parameters: list[Any],
    key_column: str,
    query: str,
    query_columns: tuple[str, ...],
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    normalized_query = query.strip()
    filters: list[str] = []
    filter_parameters: list[Any] = []
    if normalized_query:
        filters.append("(" + " OR ".join(
            f"COALESCE({column}, '') ILIKE %s" for column in query_columns
        ) + ")")
        filter_parameters.extend([f"%{normalized_query}%"] * len(query_columns))

    decoded = _decode_cursor(cursor, scope, normalized_query)
    page_filters = list(filters)
    page_parameters = [*parameters, *filter_parameters]
    if decoded:
        page_filters.append(f"({key_column} COLLATE \"C\", id) > (%s COLLATE \"C\", %s)")
        page_parameters.extend(decoded)

    where_suffix = (" WHERE " + " AND ".join(filters)) if filters else ""
    page_where_suffix = (" WHERE " + " AND ".join(page_filters)) if page_filters else ""
    total = connection.execute(
        f"SELECT count(*) AS total FROM ({source_sql}) browse_source{where_suffix}",
        [*parameters, *filter_parameters],
    ).fetchone()["total"]
    rows = list(connection.execute(
        f"SELECT * FROM ({source_sql}) browse_source{page_where_suffix} "
        f"ORDER BY {key_column} COLLATE \"C\", id LIMIT %s",
        [*page_parameters, limit + 1],
    ).fetchall())
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = _encode_cursor(
            scope, str(last[key_column]), int(last["id"]), normalized_query,
        )
    return {"items": items, "next_cursor": next_cursor, "total": int(total)}


CLASSIFICATION_SOURCE = """
    SELECT c.id, c.classification_scheme_id, c.parent_classification_id,
           c.code, c.title, c.description, c.is_terminal, c.date_deactivated,
           (SELECT count(*) FROM classifications child
             WHERE child.parent_classification_id = c.id) AS child_classification_count,
           (SELECT count(*) FROM aggregations aggregation
             WHERE aggregation.classification_id = c.id
               AND aggregation.parent_aggregation_id IS NULL
               AND current_user_can_view_aggregation(aggregation.id)) AS root_aggregation_count
      FROM classifications c
"""

AGGREGATION_SOURCE = """
    SELECT a.id,
           CASE WHEN a.parent_aggregation_id IS NULL OR current_user_can_view_aggregation(a.parent_aggregation_id)
                THEN a.parent_aggregation_id END AS parent_aggregation_id,
           a.classification_id,
           classification.code AS classification_code,
           classification.title AS classification_title,
           a.aggregation_number, a.title, a.description, a.date_created,
           a.date_opened, a.date_closed, a.medium, a.is_vital,
           aggregation_has_vital_descendants(a.id) AS has_vital_descendants,
           a.date_of_next_review, a.assigned_location, a.current_location,
           aggregation_effective_assigned_location(a.id) AS effective_assigned_location,
           aggregation_effective_current_location(a.id) AS effective_current_location,
           CASE WHEN current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(a.id)) THEN aggregation_effective_assigned_location_source_id(a.id) END AS effective_assigned_location_source_aggregation_id,
           CASE WHEN current_user_can_view_aggregation(aggregation_effective_current_location_source_id(a.id)) THEN aggregation_effective_current_location_source_id(a.id) END AS effective_current_location_source_aggregation_id,
           a.owning_org_unit_id, owning_unit.code AS owning_org_unit_code,
           owning_unit.name AS owning_org_unit_name,
           hold_status.effective_hold_count,
           hold_status.resource_state_changes_blocked,
           (SELECT count(*) FROM aggregations child
             WHERE child.parent_aggregation_id = a.id
               AND current_user_can_view_aggregation(child.id)) AS child_aggregation_count,
           (SELECT count(*) FROM records record
             WHERE record.aggregation_id = a.id
               AND current_user_can_view_record(record.id)) AS record_count
      FROM aggregations a
 LEFT JOIN classifications classification ON classification.id = a.classification_id
      JOIN org_units owning_unit ON owning_unit.id = a.owning_org_unit_id
 LEFT JOIN LATERAL (SELECT count(*)::integer effective_hold_count,
                           COALESCE(bool_or(preserve_resource_state),false) resource_state_changes_blocked
                      FROM effective_holds_for_aggregation(a.id)) hold_status ON true
     WHERE current_user_can_view_aggregation(a.id)
"""

RECORD_SOURCE = """
    SELECT r.id,
           CASE WHEN current_user_can_view_aggregation(r.aggregation_id) THEN r.aggregation_id END AS aggregation_id,
           CASE WHEN current_user_can_view_aggregation(r.aggregation_id) THEN owner.aggregation_number END AS aggregation_number,
           CASE WHEN current_user_can_view_aggregation(r.aggregation_id) THEN owner.title END AS aggregation_title,
           r.record_number, r.title, r.description,
           r.date_created, r.date_originated, r.medium, r.is_vital,
           r.date_of_next_review,
           aggregation_effective_assigned_location(r.aggregation_id) AS effective_assigned_location,
           aggregation_effective_current_location(r.aggregation_id) AS effective_current_location,
           CASE WHEN current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(r.aggregation_id)) THEN aggregation_effective_assigned_location_source_id(r.aggregation_id) END AS effective_assigned_location_source_aggregation_id,
           CASE WHEN current_user_can_view_aggregation(aggregation_effective_current_location_source_id(r.aggregation_id)) THEN aggregation_effective_current_location_source_id(r.aggregation_id) END AS effective_current_location_source_aggregation_id,
           r.owning_org_unit_id, owning_unit.code AS owning_org_unit_code,
           owning_unit.name AS owning_org_unit_name,
           hold_status.effective_hold_count,
           hold_status.resource_state_changes_blocked,
           (SELECT count(*) FROM digital_components component
             WHERE component.record_id = r.id) AS digital_component_count
      FROM records r
      JOIN aggregations owner ON owner.id = r.aggregation_id
      JOIN org_units owning_unit ON owning_unit.id = r.owning_org_unit_id
 LEFT JOIN LATERAL (SELECT count(*)::integer effective_hold_count,
                           COALESCE(bool_or(preserve_resource_state),false) resource_state_changes_blocked
                      FROM effective_holds_for_record(r.id)) hold_status ON true
     WHERE current_user_can_view_record(r.id)
"""


@router.get("/classification-schemes", response_model=list[ClassificationSchemeRead])
def browse_schemes(
    q: str = Query("", max_length=200),
    limit: int = Query(25, ge=1, le=50), offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    return list(connection.execute(
        """SELECT * FROM classification_schemes
            WHERE date_published IS NOT NULL AND date_published <= CURRENT_TIMESTAMP
              AND (%s = '' OR code ILIKE '%%'||%s||'%%' OR title ILIKE '%%'||%s||'%%')
            ORDER BY title COLLATE \"C\", id LIMIT %s OFFSET %s""",
        (q, q, q, limit, offset),
    ).fetchall())


@router.get(
    "/classification-schemes/{scheme_id}/roots",
    response_model=BrowsePage[BrowseClassificationNode],
)
def browse_classification_roots(
    scheme_id: int, limit: int = Query(50, ge=1, le=100), cursor: str | None = None,
    query: str = Query("", max_length=200),
    connection: Connection = Depends(get_connection, scope="function"),
):
    scheme = connection.execute(
        "SELECT id FROM classification_schemes WHERE id=%s AND date_published IS NOT NULL AND date_published <= CURRENT_TIMESTAMP",
        (scheme_id,),
    ).fetchone()
    if scheme is None:
        raise HTTPException(status_code=404, detail="published classification scheme not found")
    return _page(
        connection, scope=f"scheme:{scheme_id}:roots",
        source_sql=CLASSIFICATION_SOURCE + " WHERE c.classification_scheme_id=%s AND c.parent_classification_id IS NULL",
        parameters=[scheme_id], key_column="code", query=query,
        query_columns=("code", "title"), limit=limit, cursor=cursor,
    )


@router.get(
    "/classifications/{classification_id}/children",
    response_model=BrowsePage[BrowseClassificationNode],
)
def browse_classification_children(
    classification_id: int, limit: int = Query(50, ge=1, le=100), cursor: str | None = None,
    query: str = Query("", max_length=200),
    connection: Connection = Depends(get_connection, scope="function"),
):
    if connection.execute("SELECT 1 FROM classifications WHERE id=%s", (classification_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="classification not found")
    return _page(
        connection, scope=f"classification:{classification_id}:children",
        source_sql=CLASSIFICATION_SOURCE + " WHERE c.parent_classification_id=%s",
        parameters=[classification_id], key_column="code", query=query,
        query_columns=("code", "title"), limit=limit, cursor=cursor,
    )


@router.get(
    "/classifications/{classification_id}/aggregations",
    response_model=BrowsePage[BrowseAggregationNode],
)
def browse_classification_aggregations(
    classification_id: int, limit: int = Query(50, ge=1, le=100), cursor: str | None = None,
    query: str = Query("", max_length=200),
    owning_org_unit_id: int | None = None,
    record_creation: bool = False,
    digital_only: bool = False,
    connection: Connection = Depends(get_connection, scope="function"),
):
    classification = connection.execute(
        "SELECT is_terminal FROM classifications WHERE id=%s", (classification_id,),
    ).fetchone()
    if classification is None:
        raise HTTPException(status_code=404, detail="classification not found")
    if not classification["is_terminal"]:
        raise HTTPException(status_code=409, detail="only terminal classifications govern aggregations")
    owner_sql = " AND a.owning_org_unit_id=%s" if owning_org_unit_id is not None else ""
    destination_sql = " AND " + record_destination_clause("a", digital_only=digital_only) if record_creation else ""
    return _page(
        connection, scope=f"classification:{classification_id}:aggregations:owner:{owning_org_unit_id}:create:{record_creation}:digital:{digital_only}",
        source_sql=AGGREGATION_SOURCE + " AND a.classification_id=%s AND a.parent_aggregation_id IS NULL" + owner_sql + destination_sql,
        parameters=[classification_id, *([owning_org_unit_id] if owning_org_unit_id is not None else [])], key_column="aggregation_number", query=query,
        query_columns=("aggregation_number", "title"), limit=limit, cursor=cursor,
    )


@router.get(
    "/aggregations/{aggregation_id}/children",
    response_model=BrowsePage[BrowseAggregationNode],
)
def browse_aggregation_children(
    aggregation_id: int, limit: int = Query(50, ge=1, le=100), cursor: str | None = None,
    query: str = Query("", max_length=200),
    owning_org_unit_id: int | None = None,
    record_creation: bool = False,
    digital_only: bool = False,
    connection: Connection = Depends(get_connection, scope="function"),
):
    if connection.execute("SELECT 1 FROM aggregations WHERE id=%s AND current_user_can_view_aggregation(id)", (aggregation_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="aggregation not found")
    owner_sql = " AND a.owning_org_unit_id=%s" if owning_org_unit_id is not None else ""
    destination_sql = " AND " + record_destination_clause("a", digital_only=digital_only) if record_creation else ""
    return _page(
        connection, scope=f"aggregation:{aggregation_id}:children:owner:{owning_org_unit_id}:create:{record_creation}:digital:{digital_only}",
        source_sql=AGGREGATION_SOURCE + " AND a.parent_aggregation_id=%s" + owner_sql + destination_sql,
        parameters=[aggregation_id, *([owning_org_unit_id] if owning_org_unit_id is not None else [])], key_column="aggregation_number", query=query,
        query_columns=("aggregation_number", "title"), limit=limit, cursor=cursor,
    )


@router.get(
    "/aggregations/{aggregation_id}/records",
    response_model=BrowsePage[BrowseRecordNode],
)
def browse_aggregation_records(
    aggregation_id: int, limit: int = Query(50, ge=1, le=100), cursor: str | None = None,
    query: str = Query("", max_length=200),
    owning_org_unit_id: int | None = None,
    connection: Connection = Depends(get_connection, scope="function"),
):
    if connection.execute("SELECT 1 FROM aggregations WHERE id=%s AND current_user_can_view_aggregation(id)", (aggregation_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="aggregation not found")
    owner_sql = " AND r.owning_org_unit_id=%s" if owning_org_unit_id is not None else ""
    return _page(
        connection, scope=f"aggregation:{aggregation_id}:records:owner:{owning_org_unit_id}",
        source_sql=RECORD_SOURCE + " AND r.aggregation_id=%s" + owner_sql,
        parameters=[aggregation_id, *([owning_org_unit_id] if owning_org_unit_id is not None else [])], key_column="record_number", query=query,
        query_columns=("record_number", "title"), limit=limit, cursor=cursor,
    )


@router.get("/aggregations/{aggregation_id}/summary", response_model=BrowseAggregationNode)
def browse_aggregation_summary(
    aggregation_id: int, connection: Connection = Depends(get_connection, scope="function"),
):
    row = connection.execute(
        f"SELECT * FROM ({AGGREGATION_SOURCE}) browse_source WHERE id=%s", (aggregation_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="aggregation not found")
    return row


@router.get("/records/{record_id}/summary", response_model=BrowseRecordNode)
def browse_record_summary(
    record_id: int, connection: Connection = Depends(get_connection, scope="function"),
):
    row = connection.execute(
        f"SELECT * FROM ({RECORD_SOURCE}) browse_source WHERE id=%s", (record_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="record not found")
    return row


def audience_tree_sources(connection: Connection, audience: str | None) -> tuple[str, str]:
    """Filter before branch pagination; retain only paths to eligible choices."""
    if audience is None:
        return (f"SELECT node.*, true AS audience_selectable FROM ({ORG_UNIT_NODE_SQL}) node",
                f"SELECT node.*, true AS audience_selectable FROM ({ROLE_NODE_SQL}) node")
    administrator = connection.execute(
        "SELECT user_has_global_privilege(current_user_id(),'search.saved_search.administer') AS allowed"
    ).fetchone()["allowed"]
    roles = audience_eligibility_sql("roles", administrator=administrator)
    units = audience_eligibility_sql("org-units", administrator=administrator)
    seeds = ("SELECT org_unit_id AS id FROM eligible_roles" if audience == "roles"
             else "SELECT id FROM eligible_units")
    cte = f"""WITH RECURSIVE eligible_roles AS (
        SELECT target.id, target.org_unit_id FROM roles target WHERE {roles}
    ), eligible_units AS (
        SELECT target.id FROM org_units target WHERE {units}
    ), visible_units(id) AS (
        {seeds}
        UNION
        SELECT parent.parent_org_unit_id FROM org_units parent
        JOIN visible_units child ON child.id=parent.id
        WHERE parent.parent_org_unit_id IS NOT NULL
    ) """
    return (
        cte + f"""SELECT node.*, (node.id IN (SELECT id FROM eligible_units)
                      AND '{audience}'='org-units') AS audience_selectable
                   FROM ({ORG_UNIT_NODE_SQL}) node
                  WHERE node.id IN (SELECT id FROM visible_units)""",
        cte + f"""SELECT node.*, true AS audience_selectable FROM ({ROLE_NODE_SQL}) node
                  WHERE node.id IN (SELECT id FROM eligible_roles) AND '{audience}'='roles'""",
    )


@router.get("/organization/roots", tags=["organization browser"])
def browse_organization_roots(
    request: Request,
    limit: int = Query(25, ge=1, le=50), offset: int = Query(0, ge=0),
    audience: Literal["roles", "org-units"] | None = None,
    _authorization: Any = Depends(require_organization_browse),
    connection: Connection = Depends(get_connection, scope="function"),
):
    unit_source, role_source = audience_tree_sources(connection, audience)
    rows = list(connection.execute(
        f"SELECT * FROM ({unit_source}) source "
        "WHERE parent_org_unit_id IS NULL ORDER BY code COLLATE erms_code_natural, id LIMIT %s OFFSET %s",
        (limit, offset),
    ).fetchall())
    language_tag = preferred_language(connection, request)
    for row in rows:
        localized = localized_projection(row, language_tag, "name")
        row["name"] = localized["name"]
        row["description"] = localized["description"]
    return rows


@router.get("/organization/org-units/{org_unit_id}/children", tags=["organization browser"])
def browse_organization_children(
    org_unit_id: int, request: Request, include_roles: bool = True,
    limit: int = Query(25, ge=1, le=50),
    unit_offset: int = Query(0, ge=0), role_offset: int = Query(0, ge=0),
    audience: Literal["roles", "org-units"] | None = None,
    _authorization: Any = Depends(require_organization_browse),
    connection: Connection = Depends(get_connection, scope="function"),
):
    unit_source, role_source = audience_tree_sources(connection, audience)
    if connection.execute("SELECT 1 FROM org_units WHERE id=%s", (org_unit_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="organization unit not found")
    units = list(connection.execute(
        f"SELECT * FROM ({unit_source}) source "
        "WHERE parent_org_unit_id=%s ORDER BY code COLLATE erms_code_natural, id LIMIT %s OFFSET %s",
        (org_unit_id, limit + 1, unit_offset),
    ).fetchall())
    more_units = len(units) > limit
    roles = []
    if include_roles:
        roles = list(connection.execute(
            f"SELECT * FROM ({role_source}) source "
            "WHERE org_unit_id=%s ORDER BY code COLLATE erms_code_natural, id LIMIT %s OFFSET %s",
            (org_unit_id, 1 if more_units else limit + 1, role_offset),
        ).fetchall())
    language_tag = preferred_language(connection, request)
    for row in [*units, *roles]:
        localized = localized_projection(row, language_tag, "name")
        row["name"] = localized["name"]
        row["description"] = localized["description"]
    return {
        "org_units": units[:limit], "roles": [] if more_units else roles[:limit],
        "more_org_units": more_units,
        "more_roles": bool(roles) if more_units else len(roles) > limit,
    }


@router.get("/organization/roles/{role_id}/users", tags=["organization browser"])
def browse_role_users(
    role_id: int, request: Request,
    validity: Literal["all", "current", "future", "expired"] = "all",
    limit: int = Query(25, ge=1, le=50), offset: int = Query(0, ge=0),
    _authorization: Any = Depends(require_organization_browse),
    connection: Connection = Depends(get_connection, scope="function"),
):
    role = connection.execute("SELECT id FROM roles WHERE id=%s", (role_id,)).fetchone()
    if role is None:
        raise HTTPException(status_code=404, detail="role not found")
    validity_sql = {
        "all": "TRUE",
        "current": "assignment.valid_from <= CURRENT_TIMESTAMP AND (assignment.valid_until IS NULL OR assignment.valid_until > CURRENT_TIMESTAMP)",
        "future": "assignment.valid_from > CURRENT_TIMESTAMP",
        "expired": "assignment.valid_until IS NOT NULL AND assignment.valid_until <= CURRENT_TIMESTAMP",
    }[validity]
    language_tag = preferred_language(connection, request)
    # Resolve only installed ICU collations; quote the identifier separately from SQL.
    parts = language_tag.split("-")
    candidates = ["-".join(parts[:length]) + "-x-icu" for length in range(len(parts), 0, -1)]
    candidates.append("und-x-icu")
    collation = connection.execute(
        "SELECT collname FROM pg_catalog.pg_collation "
        "WHERE collnamespace='pg_catalog'::regnamespace AND collprovider='i' "
        "AND collname=ANY(%s) ORDER BY array_position(%s, collname::text) LIMIT 1",
        (candidates, candidates),
    ).fetchone()["collname"]
    # Match localized_projection: choose a nonempty exact/base locale object,
    # then fall back to the canonical name if that object has no name.
    display_name = """COALESCE(NULLIF(COALESCE(
        NULLIF(NULLIF(person.translations -> %s, '{}'::jsonb), 'null'::jsonb),
        person.translations -> %s, '{}'::jsonb) ->> 'name', ''), person.name)"""
    rows = list(connection.execute(
        sql.SQL(f"""SELECT assignment.id AS assignment_id, assignment.role_id,
                   assignment.valid_from, assignment.valid_until,
                   assignment.version AS assignment_version,
                   CASE WHEN assignment.valid_from > CURRENT_TIMESTAMP THEN 'future'
                        WHEN assignment.valid_until IS NOT NULL AND assignment.valid_until <= CURRENT_TIMESTAMP THEN 'expired'
                        ELSE 'current' END AS assignment_validity,
                   role.code AS role_code, role.name AS role_name,
                   role.translations AS role_translations,
                   person.id, person.name, person.translations,
                   person.email, person.external_id,
                   person.account_type, person.status, person.date_created,
                   person.date_deactivated, person.date_suspended, person.version
              FROM user_role_assignments assignment
              JOIN users person ON person.id=assignment.user_id
              JOIN roles role ON role.id=assignment.role_id
             WHERE assignment.role_id=%s AND {validity_sql}
             ORDER BY {{display_name}} COLLATE {{collation}}, person.id, assignment.id
             LIMIT %s OFFSET %s""").format(display_name=sql.SQL(display_name), collation=sql.Identifier("pg_catalog", collation)),
        (role_id, language_tag, language_tag.split("-", 1)[0], limit, offset),
    ).fetchall())
    for row in rows:
        row["name"] = localized_projection(row, language_tag, "name")["name"]
        row["role_name"] = localized_projection(
            {"name": row.get("role_name"), "translations": row.get("role_translations")},
            language_tag,
            "name",
        )["name"]
    return rows


@router.get("/organization/org-units/{org_unit_id}/summary", tags=["organization browser"])
def browse_org_unit_summary(
    org_unit_id: int,
    request: Request,
    _authorization: Any = Depends(require_organization_browse),
    connection: Connection = Depends(get_connection, scope="function"),
):
    row = connection.execute(
        f"SELECT * FROM ({ORG_UNIT_NODE_SQL}) source WHERE id=%s", (org_unit_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="organization unit not found")
    language_tag = preferred_language(connection, request)
    localized = localized_projection(row, language_tag, "name")
    row["name"] = localized["name"]
    row["description"] = localized["description"]
    row.pop("translations", None)
    designated_roles = {
        role["id"]: role for role in connection.execute(
            "SELECT id,code,name,translations FROM roles WHERE id=ANY(%s)",
            ([role_id for role_id in (row.get("managing_role_id"), row.get("file_administrator_role_id")) if role_id is not None],),
        ).fetchall()
    }
    for field in ("managing_role", "file_administrator_role"):
        role = designated_roles.get(row.get(field + "_id"))
        if role is not None:
            role = {"id": role["id"], "code": role["code"],
                    "name": localized_projection(role, language_tag, "name")["name"]}
        row[field] = role
    if row["parent_org_unit_id"]:
        row["parent"] = connection.execute(
            "SELECT id, code, name, translations FROM org_units WHERE id=%s", (row["parent_org_unit_id"],),
        ).fetchone()
        row["parent"]["name"] = localized_projection(
            row["parent"], language_tag, "name",
        )["name"]
        row["parent"].pop("translations", None)
    else:
        row["parent"] = None
    row["ancestors"] = list(connection.execute(
        """WITH RECURSIVE ancestors AS (
               SELECT parent.id,parent.parent_org_unit_id,parent.code,parent.name,
                      parent.translations,1 AS depth
                 FROM org_units current_unit
                 JOIN org_units parent ON parent.id=current_unit.parent_org_unit_id
                WHERE current_unit.id=%s
               UNION ALL
               SELECT parent.id,parent.parent_org_unit_id,parent.code,parent.name,
                      parent.translations,ancestors.depth + 1
                 FROM ancestors
                 JOIN org_units parent ON parent.id=ancestors.parent_org_unit_id
           )
           SELECT id,code,name,translations
             FROM ancestors
            ORDER BY depth DESC""",
        (org_unit_id,),
    ).fetchall())
    for ancestor in row["ancestors"]:
        ancestor["name"] = localized_projection(
            ancestor, language_tag, "name",
        )["name"]
        ancestor.pop("translations", None)
    if row.get("inactive_source"):
        inactive = connection.execute(
            "SELECT id,code,name,translations FROM org_units WHERE id=%s",
            (row["inactive_source"]["id"],),
        ).fetchone()
        if inactive:
            row["inactive_source"]["name"] = localized_projection(
                inactive, language_tag, "name",
            )["name"]
    row["holdings_metrics"] = connection.execute(
        """WITH aggregation_metrics AS (
               SELECT count(*) AS aggregation_count,
                      count(*) FILTER (WHERE date_closed IS NULL) AS open_aggregation_count,
                      count(*) FILTER (WHERE date_closed IS NOT NULL) AS closed_aggregation_count,
                      count(*) FILTER (WHERE medium='physical') AS physical_aggregation_count,
                      count(*) FILTER (WHERE medium='digital') AS digital_aggregation_count,
                      count(*) FILTER (WHERE medium='mixed') AS mixed_aggregation_count
                 FROM aggregations aggregation
                WHERE aggregation.owning_org_unit_id=%s
                  AND current_user_can_view_aggregation(aggregation.id)
           ), record_metrics AS (
               SELECT count(*) AS record_count,
                      count(*) FILTER (WHERE medium='physical') AS physical_record_count,
                      count(*) FILTER (WHERE medium='digital') AS digital_record_count,
                      count(*) FILTER (WHERE medium='mixed') AS mixed_record_count,
                      count(*) FILTER (WHERE is_vital) AS vital_record_count
                 FROM records record
                WHERE record.owning_org_unit_id=%s
                  AND current_user_can_view_record(record.id)
           ), component_metrics AS (
               SELECT coalesce(sum(component.size_in_bytes),0) AS storage_size_in_bytes
                 FROM records record
                 JOIN digital_components component ON component.record_id=record.id
                WHERE record.owning_org_unit_id=%s
                  AND current_user_can_view_record(record.id)
           )
           SELECT aggregation_metrics.*,record_metrics.*,component_metrics.*
             FROM aggregation_metrics,record_metrics,component_metrics""",
        (org_unit_id, org_unit_id, org_unit_id),
    ).fetchone()
    return row


@router.get("/organization/roles/{role_id}/summary", tags=["organization browser"])
def browse_role_summary(
    role_id: int,
    request: Request,
    _authorization: Any = Depends(require_organization_browse),
    connection: Connection = Depends(get_connection, scope="function"),
):
    row = connection.execute(
        f"SELECT * FROM ({ROLE_NODE_SQL}) source WHERE id=%s", (role_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="role not found")
    language_tag = preferred_language(connection, request)
    localized = localized_projection(row, language_tag, "name")
    row["name"] = localized["name"]
    row["description"] = localized["description"]
    row["profile_name"] = localized_projection(
        {
            "name": row.get("profile_name"),
            "translations": row.pop("profile_translations", {}),
        },
        language_tag,
        "name",
    )["name"]
    row["org_unit_name"] = localized_projection(
        {"name": row.get("org_unit_name"), "translations": row.pop("org_unit_translations", {})},
        language_tag,
        "name",
    )["name"]
    row["security_level_name"] = localized_projection(
        {
            "name": row.get("security_level_name"),
            "translations": row.pop("security_level_translations", {}),
        },
        language_tag,
        "name",
    )["name"]
    row["supervisor_role_name"] = localized_projection(
        {
            "name": row.get("supervisor_role_name"),
            "translations": row.pop("supervisor_role_translations", {}),
        },
        language_tag,
        "name",
    )["name"]
    counts = connection.execute(
        """SELECT count(*) FILTER (WHERE valid_from > CURRENT_TIMESTAMP) AS future_assignment_count,
                  count(*) FILTER (WHERE valid_until IS NOT NULL AND valid_until <= CURRENT_TIMESTAMP) AS expired_assignment_count
             FROM user_role_assignments WHERE role_id=%s""", (role_id,),
    ).fetchone()
    profile_privileges = list(connection.execute(
        """SELECT privilege.id,privilege.code,privilege.name,privilege.description,
                  privilege.category,privilege.is_reserved
             FROM profile_privileges membership
             JOIN privileges privilege ON privilege.id=membership.privilege_id
            WHERE membership.profile_id=%s
            ORDER BY privilege.category,privilege.name,privilege.code""",
        (row["profile_id"],),
    ).fetchall())
    return {**row, **counts, "profile_privileges": profile_privileges}


@router.get("/organization/search", tags=["organization browser"])
def search_organization_structure(
    request: Request,
    query: str = Query(min_length=1, max_length=200),
    entity_type: Literal["all", "org_unit", "role", "user"] = "all",
    status: Literal["all", "active", "inactive", "suspended"] = "all",
    limit: int = Query(50, ge=1, le=100),
    audience: Literal["roles", "org-units"] | None = None,
    _authorization: Any = Depends(require_organization_browse),
    connection: Connection = Depends(get_connection, scope="function"),
):
    unit_source, role_source = audience_tree_sources(connection, audience)
    if audience is not None:
        entity_type = "role" if audience == "roles" else "org_unit"
    pattern = f"%{query.strip()}%"
    status_filter = "TRUE" if status == "all" else "source.effective_status=%s"
    status_parameters: tuple[Any, ...] = () if status == "all" else (status,)
    results: list[dict[str, Any]] = []
    if entity_type in {"all", "org_unit"}:
        results.extend({"type": "org_unit", **row} for row in connection.execute(
            f"""WITH RECURSIVE paths AS (
                    SELECT unit.id, unit.parent_org_unit_id,
                           ARRAY[unit.id]::bigint[] AS reverse_path
                      FROM org_units unit
                    UNION ALL
                    SELECT paths.id, parent.parent_org_unit_id,
                           paths.reverse_path || parent.id
                      FROM paths JOIN org_units parent
                        ON parent.id=paths.parent_org_unit_id
                )
                SELECT source.id, source.code, source.name, source.description,
                       source.translations, source.status,
                       source.effective_status, source.audience_selectable,
                       (SELECT array_agg(path_id ORDER BY ordinal DESC)
                          FROM unnest(path.reverse_path) WITH ORDINALITY p(path_id, ordinal)
                       ) AS org_unit_path
                  FROM ({unit_source}) source
                  JOIN paths path ON path.id=source.id AND path.parent_org_unit_id IS NULL
                 WHERE (source.code ILIKE %s OR source.name ILIKE %s OR COALESCE(source.description,'') ILIKE %s
                        OR COALESCE(source.translations::text, '') ILIKE %s)
                   AND {status_filter} AND source.audience_selectable
                 ORDER BY source.code LIMIT %s""",
            (pattern, pattern, pattern, pattern, *status_parameters, limit),
        ).fetchall())
    if entity_type in {"all", "role"}:
        results.extend({"type": "role", **row} for row in connection.execute(
            f"""WITH RECURSIVE paths AS (
                    SELECT unit.id, unit.parent_org_unit_id,
                           ARRAY[unit.id]::bigint[] AS reverse_path
                      FROM org_units unit
                    UNION ALL
                    SELECT paths.id, parent.parent_org_unit_id,
                           paths.reverse_path || parent.id
                      FROM paths JOIN org_units parent
                        ON parent.id=paths.parent_org_unit_id
                )
                SELECT source.id, source.code, source.name, source.description,
                       source.translations, source.status,
                       source.effective_status, source.audience_selectable, source.org_unit_id,
                       (SELECT array_agg(path_id ORDER BY ordinal DESC)
                          FROM unnest(path.reverse_path) WITH ORDINALITY p(path_id, ordinal)
                       ) AS org_unit_path
                  FROM ({role_source}) source
                  JOIN paths path ON path.id=source.org_unit_id AND path.parent_org_unit_id IS NULL
                 WHERE (source.code ILIKE %s OR source.name ILIKE %s OR COALESCE(source.description,'') ILIKE %s
                        OR COALESCE(source.translations::text, '') ILIKE %s)
                   AND {status_filter} AND source.audience_selectable
                 ORDER BY source.code LIMIT %s""",
            (pattern, pattern, pattern, pattern, *status_parameters, limit),
        ).fetchall())
    if entity_type in {"all", "user"}:
        results.extend({"type": "user", **row} for row in connection.execute(
            f"""WITH RECURSIVE paths AS (
                    SELECT unit.id, unit.parent_org_unit_id,
                           ARRAY[unit.id]::bigint[] AS reverse_path
                      FROM org_units unit
                    UNION ALL
                    SELECT paths.id, parent.parent_org_unit_id,
                           paths.reverse_path || parent.id
                      FROM paths JOIN org_units parent
                        ON parent.id=paths.parent_org_unit_id
                )
                SELECT DISTINCT person.id, person.name, person.translations,
                              person.email, person.status,
                              assignment.role_id, assignment.id AS assignment_id,
                              role.code AS role_code, role.name AS role_name,
                              role.translations AS role_translations,
                              (SELECT array_agg(path_id ORDER BY ordinal DESC)
                                 FROM unnest(path.reverse_path) WITH ORDINALITY p(path_id, ordinal)
                              ) AS org_unit_path
                   FROM users person
              LEFT JOIN user_role_assignments assignment ON assignment.user_id=person.id
              LEFT JOIN roles role ON role.id=assignment.role_id
              LEFT JOIN paths path ON path.id=role.org_unit_id AND path.parent_org_unit_id IS NULL
                  WHERE (person.name ILIKE %s OR COALESCE(person.email,'') ILIKE %s
                         OR COALESCE(person.translations::text, '') ILIKE %s)
                    AND {status_filter.replace('source.effective_status', 'person.status')}
               ORDER BY person.name, person.id LIMIT %s""",
            (pattern, pattern, pattern, *status_parameters, limit),
        ).fetchall())
    language_tag = preferred_language(connection, request)
    for row in results:
        if row["type"] in {"org_unit", "role", "user"}:
            row["name"] = localized_projection(row, language_tag, "name")["name"]
        if row["type"] == "user" and row.get("role_name"):
            row["role_name"] = localized_projection(
                {"name": row["role_name"], "translations": row.get("role_translations")},
                language_tag,
                "name",
            )["name"]
    return results[:limit]
