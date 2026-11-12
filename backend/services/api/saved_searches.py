from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing_extensions import Annotated

from .operation_policy import operation_policy
from .audit_context import decode_change_reason
from .concurrency import expected_version
from .database import get_connection
from .authorization_policy import require_global_privilege
from .schemas import SearchRequest
from .search import canonicalize_search_request, search_rows
from .entity_localization import localize_rows, localized_projection, preferred_language


router = APIRouter(prefix="/api/v1/saved-searches", tags=["saved searches"])
require_saved_search_save = require_global_privilege("search.saved_search.save")
require_saved_search_administrator = require_global_privilege("search.saved_search.administer")
require_saved_search_delete = require_global_privilege("search.saved_search.delete")
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SavedSearchDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    resource_type: Literal["record", "aggregation"]
    max_results: int = Field(default=1000, ge=1, le=5000)
    request: SearchRequest

    @model_validator(mode="after")
    def page_size_is_supported(self):
        if self.request.limit not in {25, 50, 100}:
            raise ValueError("saved-search page size must be 25, 50, or 100")
        if self.request.offset != 0:
            raise ValueError("saved-search definitions must begin at offset 0")
        if self.request.debug:
            raise ValueError("debug is runtime state and cannot be saved")
        return self


class SavedSearchWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[NonBlank, StringConstraints(max_length=120)]
    category: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    description: Annotated[str, StringConstraints(max_length=500)] | None = None
    definition: SavedSearchDefinition
    audience_mode: Literal["private", "shared"] = "private"
    role_ids: list[int] = Field(default_factory=list, max_length=100)
    org_unit_ids: list[int] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def audience_is_consistent(self):
        if len(set(self.role_ids)) != len(self.role_ids) or len(set(self.org_unit_ids)) != len(self.org_unit_ids):
            raise ValueError("audience IDs must be unique")
        has_grants = bool(self.role_ids or self.org_unit_ids)
        if self.audience_mode == "private" and has_grants:
            raise ValueError("private saved searches cannot have audience grants")
        if self.audience_mode == "shared" and not has_grants:
            raise ValueError("shared saved searches require at least one audience grant")
        if self.category == "":
            self.category = None
        return self


class SavedSearchExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: Literal[25, 50, 100] | None = None
    offset: int = Field(default=0, ge=0)
    debug: bool = False


def _current_user_id(connection: Connection) -> int:
    row = connection.execute("SELECT current_user_id() AS value").fetchone()
    if not row or row["value"] is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return int(row["value"])


def _has(connection: Connection, code: str) -> bool:
    return bool(connection.execute(
        "SELECT user_has_global_privilege(current_user_id(),%s) AS value", (code,),
    ).fetchone()["value"])


def _has_information_governance_role(connection: Connection) -> bool:
    return bool(connection.execute(
        """SELECT EXISTS (
               SELECT 1
                 FROM user_role_assignments assignment
                 JOIN roles role ON role.id=assignment.role_id
                WHERE assignment.user_id=current_user_id()
                  AND role.is_information_governance
                  AND assignment.valid_from<=CURRENT_TIMESTAMP
                  AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
                  AND role_effectively_active(role.id)
           ) AS value"""
    ).fetchone()["value"])


def _reason(request: Request, *, default: str | None = None) -> str:
    value = decode_change_reason(request.headers.get("X-Change-Reason", "")).strip()
    if not value and default is not None:
        return default
    if not value:
        raise HTTPException(status_code=422, detail={"code": "saved_search_change_reason_required"})
    return value


def _accessible_sql(alias: str = "saved") -> str:
    return f"""({alias}.owner_user_id=current_user_id()
      OR EXISTS (
        SELECT 1 FROM saved_search_role_grants grant_row
        JOIN user_role_assignments assignment ON assignment.role_id=grant_row.role_id
        WHERE grant_row.saved_search_id={alias}.id
          AND assignment.user_id=current_user_id()
          AND assignment.valid_from<=CURRENT_TIMESTAMP
          AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
          AND role_effectively_active(assignment.role_id))
      OR EXISTS (
        SELECT 1 FROM saved_search_org_unit_grants grant_row
        JOIN roles role ON role.org_unit_id=grant_row.org_unit_id
        JOIN user_role_assignments assignment ON assignment.role_id=role.id
        WHERE grant_row.saved_search_id={alias}.id
          AND assignment.user_id=current_user_id()
          AND assignment.valid_from<=CURRENT_TIMESTAMP
          AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
          AND role_effectively_active(role.id)))"""


def _audience(connection: Connection, saved_search_id: int) -> tuple[list[int], list[int]]:
    roles = [row["role_id"] for row in connection.execute(
        "SELECT role_id FROM saved_search_role_grants WHERE saved_search_id=%s ORDER BY role_id",
        (saved_search_id,),
    ).fetchall()]
    units = [row["org_unit_id"] for row in connection.execute(
        "SELECT org_unit_id FROM saved_search_org_unit_grants WHERE saved_search_id=%s ORDER BY org_unit_id",
        (saved_search_id,),
    ).fetchall()]
    return roles, units


def _is_accessible(connection: Connection, saved_search_id: int) -> bool:
    return bool(connection.execute(
        f"SELECT EXISTS(SELECT 1 FROM saved_searches saved WHERE saved.id=%s AND {_accessible_sql()}) AS value",
        (saved_search_id,),
    ).fetchone()["value"])


def _capabilities(connection: Connection, row: dict[str, Any]) -> tuple[dict[str, bool], dict[str, str | None]]:
    owner = row["owner_user_id"] == _current_user_id(connection)
    administrator = _has(connection, "search.saved_search.administer")
    save = _has(connection, "search.saved_search.save")
    delete_privilege = _has(connection, "search.saved_search.delete")
    target_view = _has(connection, f"{row['resource_type']}.view")
    accessible = _is_accessible(connection, row["id"])
    governance_bypass = _has_information_governance_role(connection)
    values = {
        "update": owner or administrator,
        "manage_audience": administrator or (owner and save),
        "delete": owner or (delete_privilege and administrator),
        "execute": (accessible or governance_bypass) and target_view,
    }
    reasons = {
        "update": None if values["update"] else "saved_search_owner_or_administrator_required",
        "manage_audience": None if values["manage_audience"] else "saved_search_save_or_administrator_required",
        "delete": None if values["delete"] else "saved_search_delete_and_administration_required",
        "execute": None if values["execute"] else (
            "resource_view_required" if accessible or governance_bypass else "saved_search_not_accessible"
        ),
    }
    return values, reasons


def _serialize(connection: Connection, row: dict[str, Any], language: str) -> dict[str, Any]:
    result = dict(row)
    roles, units = _audience(connection, row["id"])
    result["role_ids"] = roles
    result["org_unit_ids"] = units
    result["owner"] = connection.execute(
        "SELECT id,name,email,status,translations FROM users WHERE id=%s", (row["owner_user_id"],),
    ).fetchone()
    if result["owner"] is not None:
        result["owner"]["localized"] = localized_projection(result["owner"], language, "name")
        result["owner"].pop("translations", None)
    result["capabilities"], result["capability_reasons"] = _capabilities(connection, row)
    return result


def _get(
    connection: Connection, saved_search_id: int, *, lock: bool = False,
    administration: bool = True, governance_bypass: bool = False,
) -> dict[str, Any]:
    admin_clause = " OR user_has_global_privilege(current_user_id(),'search.saved_search.administer')" if administration else ""
    governance_clause = " OR %s" if governance_bypass else ""
    parameters: tuple[Any, ...] = (
        (saved_search_id, _has_information_governance_role(connection))
        if governance_bypass else (saved_search_id,)
    )
    row = connection.execute(
        f"SELECT * FROM saved_searches saved WHERE saved.id=%s AND ({_accessible_sql()}{admin_clause}{governance_clause})"
        + (" FOR UPDATE" if lock else ""),
        parameters,
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "saved_search_unavailable", "message_key": "saved_search.error.unavailable"})
    return row


def _canonical_definition(connection: Connection, definition: SavedSearchDefinition) -> dict[str, Any]:
    resource = "records" if definition.resource_type == "record" else "aggregations"
    canonical = canonicalize_search_request(connection, resource, definition.request)
    canonical["offset"] = 0
    return {
        "schema_version": 1,
        "resource_type": definition.resource_type,
        "max_results": definition.max_results,
        "request": canonical,
    }


def _eligible_ids(connection: Connection, *, administrator: bool) -> tuple[set[int], set[int]]:
    if administrator:
        roles = connection.execute(
            """SELECT id FROM roles WHERE NOT is_system AND account_type_restriction IS NULL
                 AND role_effectively_active(id)"""
        ).fetchall()
        units = connection.execute(
            "SELECT id FROM org_units WHERE org_unit_effectively_active(id)"
        ).fetchall()
    else:
        roles = connection.execute(
            """SELECT DISTINCT role.id FROM user_role_assignments assignment
                 JOIN roles role ON role.id=assignment.role_id
                WHERE assignment.user_id=current_user_id()
                  AND assignment.valid_from<=CURRENT_TIMESTAMP
                  AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
                  AND NOT role.is_system AND role.account_type_restriction IS NULL
                  AND role_effectively_active(role.id)"""
        ).fetchall()
        units = connection.execute(
            """SELECT DISTINCT role.org_unit_id AS id FROM user_role_assignments assignment
                 JOIN roles role ON role.id=assignment.role_id
                WHERE assignment.user_id=current_user_id()
                  AND assignment.valid_from<=CURRENT_TIMESTAMP
                  AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
                  AND role.org_unit_id IS NOT NULL AND role_effectively_active(role.id)"""
        ).fetchall()
    return {row["id"] for row in roles}, {row["id"] for row in units}


def _validate_audience(connection: Connection, payload: SavedSearchWrite, *, administrator: bool) -> None:
    eligible_roles, eligible_units = _eligible_ids(connection, administrator=administrator)
    if not set(payload.role_ids) <= eligible_roles or not set(payload.org_unit_ids) <= eligible_units:
        raise HTTPException(status_code=403, detail={"code": "saved_search_audience_not_permitted"})


def _replace_audience(connection: Connection, saved_search_id: int, payload: SavedSearchWrite) -> None:
    connection.execute("DELETE FROM saved_search_role_grants WHERE saved_search_id=%s", (saved_search_id,))
    connection.execute("DELETE FROM saved_search_org_unit_grants WHERE saved_search_id=%s", (saved_search_id,))
    for role_id in payload.role_ids:
        connection.execute(
            "INSERT INTO saved_search_role_grants(saved_search_id,role_id) VALUES (%s,%s)",
            (saved_search_id, role_id),
        )
    for org_unit_id in payload.org_unit_ids:
        connection.execute(
            "INSERT INTO saved_search_org_unit_grants(saved_search_id,org_unit_id) VALUES (%s,%s)",
            (saved_search_id, org_unit_id),
        )


@router.get("")
@operation_policy("relationship_scoped")
def list_saved_searches(
    request: Request,
    scope: Literal["all", "owned", "shared_with_me"] = "all",
    resource_type: Literal["record", "aggregation"] | None = None,
    q: str | None = None, category: str | None = None,
    limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    if scope == "owned":
        visibility = "saved.owner_user_id=current_user_id()"
    elif scope == "shared_with_me":
        visibility = f"saved.owner_user_id<>current_user_id() AND {_accessible_sql()}"
    else:
        visibility = _accessible_sql()
    where = f"""WHERE ({visibility})
      AND (%s::text IS NULL OR saved.resource_type=%s)
      AND (%s::text IS NULL OR saved.name ILIKE '%%'||%s||'%%')
      AND (%s::text IS NULL OR lower(saved.category)=lower(%s))"""
    params = (resource_type, resource_type, q, q, category, category)
    total = connection.execute(f"SELECT count(*) AS value FROM saved_searches saved {where}", params).fetchone()["value"]
    rows = connection.execute(
        f"SELECT saved.* FROM saved_searches saved {where} ORDER BY saved.date_updated DESC,saved.id DESC LIMIT %s OFFSET %s",
        (*params, limit, offset),
    ).fetchall()
    language = preferred_language(connection, request)
    items = [_serialize(connection, row, language) for row in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset, "returned": len(items)}


def audience_eligibility_sql(audience_kind: str, *, administrator: bool) -> str:
    """Shared eligibility predicate for typeahead and scoped organization trees."""
    if audience_kind == "roles":
        return (
            "NOT target.is_system AND target.account_type_restriction IS NULL AND role_effectively_active(target.id)"
            if administrator else
            """EXISTS (SELECT 1 FROM user_role_assignments assignment
                         WHERE assignment.role_id=target.id AND assignment.user_id=current_user_id()
                           AND assignment.valid_from<=CURRENT_TIMESTAMP
                           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP))
                 AND NOT target.is_system AND target.account_type_restriction IS NULL
                 AND role_effectively_active(target.id)"""
        )
    else:
        return (
            "org_unit_effectively_active(target.id)" if administrator else
            """EXISTS (SELECT 1 FROM roles role JOIN user_role_assignments assignment ON assignment.role_id=role.id
                         WHERE role.org_unit_id=target.id AND assignment.user_id=current_user_id()
                           AND assignment.valid_from<=CURRENT_TIMESTAMP
                           AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
                           AND role_effectively_active(role.id))"""
        )


@router.get("/audience-options/{audience_kind}")
@operation_policy("relationship_scoped")
def audience_options(
    audience_kind: Literal["roles", "org-units"],
    request: Request,
    q: str = Query("", max_length=120),
    ids: str | None = Query(None, max_length=1200),
    limit: int = Query(25, ge=1, le=50),
    offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Return a bounded audience lookup page; never preload either directory."""
    administrator = _has(connection, "search.saved_search.administer")
    language = preferred_language(connection, request)
    requested_ids: list[int] = []
    if ids:
        try:
            requested_ids = list(dict.fromkeys(int(value) for value in ids.split(",") if value.strip()))
        except ValueError as error:
            raise HTTPException(status_code=422, detail={"code": "invalid_audience_ids"}) from error
        if len(requested_ids) > 100:
            raise HTTPException(status_code=422, detail={"code": "too_many_audience_ids"})
    term = q.strip()
    eligibility = audience_eligibility_sql(audience_kind, administrator=administrator)
    if audience_kind == "roles":
        columns = "target.id,target.code,target.name,target.description,target.org_unit_id,target.translations"
        table = "roles"
    else:
        columns = "target.id,target.code,target.name,target.description,target.translations"
        table = "org_units"
    where = f"""WHERE ({eligibility})
      AND (%s::bigint[] IS NULL OR target.id=ANY(%s::bigint[]))
      AND (%s='' OR target.code ILIKE '%%'||%s||'%%' OR target.name ILIKE '%%'||%s||'%%'
           OR COALESCE(target.translations->%s->>'name','') ILIKE '%%'||%s||'%%')"""
    id_filter = requested_ids or None
    params = (id_filter, id_filter, term, term, term, language, term)
    total = connection.execute(
        f"SELECT count(*) AS value FROM {table} target {where}", params,
    ).fetchone()["value"]
    rows = list(connection.execute(
        f"""SELECT {columns} FROM {table} target {where}
             ORDER BY lower(COALESCE(NULLIF(target.translations->%s->>'name',''),target.name)),target.id
             LIMIT %s OFFSET %s""",
        (*params, language, limit, offset),
    ).fetchall())
    localize_rows(rows, language, "name")
    return {
        "items": rows, "total": total, "limit": limit, "offset": offset,
        "returned": len(rows), "administrator_scope": administrator,
    }


@router.get("/administration", dependencies=[Depends(require_saved_search_administrator)])
def administer_saved_searches(
    request: Request,
    owner_user_id: int | None = None, owner_q: str | None = None,
    resource_type: Literal["record", "aggregation"] | None = None,
    q: str | None = None, category: str | None = None,
    role_id: int | None = None, org_unit_id: int | None = None,
    max_results_min: int | None = Query(None, ge=1, le=5000),
    max_results_max: int | None = Query(None, ge=1, le=5000),
    created_from: datetime | None = None, created_before: datetime | None = None,
    updated_from: datetime | None = None, updated_before: datetime | None = None,
    limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    if not _has(connection, "search.saved_search.administer"):
        raise HTTPException(status_code=403, detail={"code": "insufficient_privilege"})
    if max_results_min is not None and max_results_max is not None and max_results_min > max_results_max:
        raise HTTPException(status_code=422, detail={"code": "invalid_max_results_range"})
    where = """WHERE (%s::bigint IS NULL OR saved.owner_user_id=%s)
      AND (%s::text IS NULL OR owner.name ILIKE '%%'||%s||'%%' OR owner.email ILIKE '%%'||%s||'%%')
      AND (%s::text IS NULL OR saved.resource_type=%s)
      AND (%s::text IS NULL OR saved.name ILIKE '%%'||%s||'%%')
      AND (%s::text IS NULL OR lower(saved.category)=lower(%s))
      AND (%s::bigint IS NULL OR EXISTS (SELECT 1 FROM saved_search_role_grants grant_row WHERE grant_row.saved_search_id=saved.id AND grant_row.role_id=%s))
      AND (%s::bigint IS NULL OR EXISTS (SELECT 1 FROM saved_search_org_unit_grants grant_row WHERE grant_row.saved_search_id=saved.id AND grant_row.org_unit_id=%s))
      AND (%s::integer IS NULL OR (saved.definition->>'max_results')::integer >= %s)
      AND (%s::integer IS NULL OR (saved.definition->>'max_results')::integer <= %s)
      AND (%s::timestamptz IS NULL OR saved.date_created >= %s::timestamptz)
      AND (%s::timestamptz IS NULL OR saved.date_created < %s::timestamptz)
      AND (%s::timestamptz IS NULL OR saved.date_updated >= %s::timestamptz)
      AND (%s::timestamptz IS NULL OR saved.date_updated < %s::timestamptz)"""
    params = (
        owner_user_id, owner_user_id, owner_q, owner_q, owner_q,
        resource_type, resource_type, q, q, category, category,
        role_id, role_id, org_unit_id, org_unit_id,
        max_results_min, max_results_min, max_results_max, max_results_max,
        created_from, created_from, created_before, created_before,
        updated_from, updated_from, updated_before, updated_before,
    )
    source = "saved_searches saved JOIN users owner ON owner.id=saved.owner_user_id"
    total = connection.execute(f"SELECT count(*) value FROM {source} {where}", params).fetchone()["value"]
    rows = connection.execute(
        f"SELECT saved.* FROM {source} {where} ORDER BY saved.date_updated DESC,saved.id DESC LIMIT %s OFFSET %s",
        (*params, limit, offset),
    ).fetchall()
    language = preferred_language(connection, request)
    items = [_serialize(connection, row, language) for row in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset, "returned": len(items)}


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_saved_search_save)])
def create_saved_search(payload: SavedSearchWrite, request: Request, connection: Connection = Depends(get_connection, scope="function")):
    if not _has(connection, "search.saved_search.save"):
        raise HTTPException(status_code=403, detail={"code": "insufficient_privilege"})
    administrator = _has(connection, "search.saved_search.administer")
    _validate_audience(connection, payload, administrator=administrator)
    definition = _canonical_definition(connection, payload.definition)
    connection.execute("SELECT set_config('app.event_metadata',%s,true)", (json.dumps({
        "audience_after": {
            "role_ids": sorted(payload.role_ids),
            "org_unit_ids": sorted(payload.org_unit_ids),
        },
    }),))
    row = connection.execute(
        """INSERT INTO saved_searches(owner_user_id,name,category,description,resource_type,definition,audience_mode)
           VALUES (current_user_id(),%s,%s,%s,%s,%s,%s) RETURNING *""",
        (payload.name, payload.category, payload.description, definition["resource_type"], Jsonb(definition), payload.audience_mode),
    ).fetchone()
    _replace_audience(connection, row["id"], payload)
    return _serialize(connection, row, preferred_language(connection, request))


@router.get("/{saved_search_id}")
@operation_policy("relationship_scoped")
def get_saved_search(saved_search_id: int, request: Request, connection: Connection = Depends(get_connection, scope="function")):
    return _serialize(connection, _get(connection, saved_search_id), preferred_language(connection, request))


@router.post("/{saved_search_id}/execute")
@operation_policy("relationship_scoped")
def execute_saved_search(
    saved_search_id: int, payload: SavedSearchExecution,
    connection: Connection = Depends(get_connection, scope="function"),
):
    # Administration permits governance of a saved search, but never grants
    # access to execute it or to see the resources it returns.
    row = _get(connection, saved_search_id, administration=False, governance_bypass=True)
    if not _has(connection, f"{row['resource_type']}.view"):
        raise HTTPException(status_code=403, detail={"code": "resource_view_required"})
    definition = row["definition"]
    if definition.get("schema_version") != 1:
        raise HTTPException(
            status_code=422,
            detail={"code": "saved_search_definition_unsupported"},
        )
    maximum = int(definition["max_results"])
    if payload.offset >= maximum:
        raise HTTPException(
            status_code=422,
            detail={"code": "saved_search_result_limit_exceeded", "max_results": maximum},
        )
    stored_request = SearchRequest.model_validate(definition["request"])
    requested_limit = payload.limit or stored_request.limit
    effective_limit = min(requested_limit, maximum - payload.offset)
    execution_request = stored_request.model_copy(update={
        "limit": effective_limit,
        "offset": payload.offset,
        "debug": payload.debug,
    })
    resource = "records" if row["resource_type"] == "record" else "aggregations"
    result = search_rows(
        connection, resource, execution_request,
        endpoint=f"/api/v1/saved-searches/{saved_search_id}/execute",
    )
    result["total"] = min(int(result["total"]), maximum)
    result["saved_search"] = {
        "id": row["id"], "name": row["name"], "version": row["version"],
        "resource_type": row["resource_type"], "max_results": maximum,
    }
    if row["resource_type"] == "record":
        pending = connection.execute(
            """SELECT EXISTS(SELECT 1 FROM digital_component_search_documents document
                 WHERE document.status IN ('pending','processing','stale')
                   AND current_user_can_view_record(document.record_id)
                   AND current_user_can_record_component_operation(
                       document.record_id,'record.component.view','record.component.view')) AS value"""
        ).fetchone()["value"]
        result["index_freshness"] = {"has_pending_content": bool(pending)}
    else:
        result["index_freshness"] = {"has_pending_content": False}
    return result


@router.put("/{saved_search_id}")
@operation_policy("relationship_scoped")
def update_saved_search(
    saved_search_id: int, payload: SavedSearchWrite, request: Request,
    version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    reason = _reason(request, default="Updated saved search")
    row = _get(connection, saved_search_id, lock=True)
    if row["version"] != version:
        raise HTTPException(status_code=409, detail={"code": "stale_version"})
    owner = row["owner_user_id"] == _current_user_id(connection)
    administrator = _has(connection, "search.saved_search.administer")
    if not (owner or administrator):
        raise HTTPException(status_code=403, detail={"code": "saved_search_owner_or_administrator_required"})
    old_roles, old_units = _audience(connection, saved_search_id)
    audience_changed = (
        row["audience_mode"] != payload.audience_mode
        or old_roles != sorted(payload.role_ids) or old_units != sorted(payload.org_unit_ids)
    )
    if audience_changed and not (administrator or (owner and _has(connection, "search.saved_search.save"))):
        raise HTTPException(status_code=403, detail={"code": "saved_search_save_or_administrator_required"})
    if audience_changed:
        _validate_audience(connection, payload, administrator=administrator)
    definition = _canonical_definition(connection, payload.definition)
    connection.execute("SELECT set_config('app.change_reason',%s,true)", (reason,))
    connection.execute("SELECT set_config('app.event_metadata',%s,true)", (json.dumps({
        "audience_before": {"role_ids": old_roles, "org_unit_ids": old_units},
        "audience_after": {"role_ids": sorted(payload.role_ids), "org_unit_ids": sorted(payload.org_unit_ids)},
    }),))
    updated = connection.execute(
        """UPDATE saved_searches SET name=%s,category=%s,description=%s,resource_type=%s,
                  definition=%s,audience_mode=%s
             WHERE id=%s AND version=%s RETURNING *""",
        (payload.name, payload.category, payload.description, definition["resource_type"], Jsonb(definition),
         payload.audience_mode, saved_search_id, version),
    ).fetchone()
    if updated is None:
        raise HTTPException(status_code=409, detail={"code": "stale_version"})
    if audience_changed:
        _replace_audience(connection, saved_search_id, payload)
    return _serialize(connection, updated, preferred_language(connection, request))


@router.delete("/{saved_search_id}", status_code=status.HTTP_204_NO_CONTENT)
@operation_policy("relationship_scoped")
def delete_saved_search(
    saved_search_id: int, request: Request, version: int = Depends(expected_version),
    connection: Connection = Depends(get_connection, scope="function"),
):
    reason = _reason(request)
    row = _get(connection, saved_search_id, lock=True)
    owner = row["owner_user_id"] == _current_user_id(connection)
    administrator = _has(connection, "search.saved_search.administer")
    if not owner and not (_has(connection, "search.saved_search.delete") and administrator):
        raise HTTPException(status_code=403, detail={"code": "saved_search_delete_required"})
    old_roles, old_units = _audience(connection, saved_search_id)
    connection.execute("SELECT set_config('app.change_reason',%s,true)", (reason,))
    connection.execute("SELECT set_config('app.event_metadata',%s,true)", (json.dumps({
        "audience_before": {"role_ids": old_roles, "org_unit_ids": old_units},
    }),))
    deleted = connection.execute(
        "DELETE FROM saved_searches WHERE id=%s AND version=%s RETURNING id", (saved_search_id, version),
    ).fetchone()
    if deleted is None:
        raise HTTPException(status_code=409, detail={"code": "stale_version"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
