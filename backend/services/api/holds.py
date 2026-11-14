from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from psycopg import Connection
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .operation_policy import operation_policy
from .audit_context import decode_change_reason
from .concurrency import expected_version
from .database import get_connection, get_consistent_connection
from .hold_notifications import notify_assignments
from .entity_localization import localize_rows, localized_projection, preferred_language
from .resource_authorization import require_resource_operation
from .authorization_policy import require_global_privilege


router = APIRouter(prefix="/api/v1", tags=["legal holds"])
require_holds_administer = require_global_privilege("holds.administer")


class HoldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    valid_from: datetime
    valid_to: datetime | None = None
    owner_user_id: int
    preserve_resource_state: bool = False
    contributor_user_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_dates_and_people(self):
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        if self.owner_user_id in self.contributor_user_ids:
            raise ValueError("the owner cannot also be a contributor")
        if len(set(self.contributor_user_ids)) != len(self.contributor_user_ids):
            raise ValueError("contributors must be unique")
        return self


class HoldUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    owner_user_id: int | None = None
    preserve_resource_state: bool | None = None


class ContributorReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_ids: list[int]


class HoldHeldItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_type: Literal["aggregation", "record"]
    resource_id: int


class HoldHeldItemsBulkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    held_items: list[HoldHeldItemCreate] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_unique_held_items(self):
        keys = [(held_item.resource_type, held_item.resource_id) for held_item in self.held_items]
        if len(keys) != len(set(keys)):
            raise ValueError("held_items must be unique")
        return self


class HoldHeldItemRemove(HoldHeldItemCreate):
    version: int = Field(ge=1)


class HoldHeldItemsBulkRemove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    held_items: list[HoldHeldItemRemove] = Field(min_length=1, max_length=1000)


class ResourceHoldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hold_id: int


class UserReference(BaseModel):
    id: int
    name: str
    email: str | None = None
    status: str
    localized: dict[str, Any] | None = None


class HoldCapabilities(BaseModel):
    update: bool
    delete: bool
    manage_contributors: bool
    manage_held_items: bool


class HoldResponse(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None
    valid_from: datetime
    valid_to: datetime | None = None
    owner_user_id: int
    owner: UserReference
    preserve_resource_state: bool
    date_created: datetime
    date_updated: datetime
    version: int
    state: Literal["scheduled", "active", "expired"]
    is_effective: bool
    contributors: list[UserReference]
    direct_held_item_count: int
    capabilities: HoldCapabilities
    capability_reasons: dict[str, str | None]


class HoldPage(BaseModel):
    items: list[HoldResponse]
    total: int
    limit: int
    offset: int
    returned: int


class HoldHeldItemResponse(BaseModel):
    id: int
    version: int
    resource_type: Literal["aggregation", "record"]
    resource_id: int
    number: str
    title: str
    description: str | None = None
    security_level_id: int
    security_level_code: str
    security_level_name: str
    assigned_at: datetime
    assigned_by_user_id: int | None = None
    assigned_by_name: str | None = None


class HoldHeldItemPage(BaseModel):
    items: list[HoldHeldItemResponse]
    total: int
    limit: int
    offset: int
    returned: int


class CandidateResponse(BaseModel):
    resource_type: Literal["aggregation", "record"]
    resource_id: int
    number: str
    title: str
    description: str | None = None


class CandidatePage(BaseModel):
    items: list[CandidateResponse]
    total: int
    limit: int
    offset: int


class EffectiveHoldResponse(BaseModel):
    kind: Literal["effective_hold"] = "effective_hold"
    source: Literal["direct", "inherited", "both"]
    directly_assigned_resource: bool
    preserve_resource_state: bool
    hold_id: int | None = None
    code: str | None = None
    name: str | None = None
    is_direct: bool | None = None
    is_inherited: bool | None = None
    nearest_assigned_aggregation_id: int | None = None
    direct_assignment_version: int | None = None
    can_manage_held_items: bool = False


def _reason(request: Request) -> str:
    value = decode_change_reason(request.headers.get("X-Change-Reason", "")).strip()
    if not value:
        raise HTTPException(status_code=422, detail={"code": "hold_change_reason_required"})
    return value


def _is_admin(connection: Connection) -> bool:
    return bool(connection.execute(
        "SELECT user_has_global_privilege(current_user_id(),'holds.administer') AS allowed"
    ).fetchone()["allowed"])


def _require_admin(connection: Connection) -> None:
    if not _is_admin(connection):
        raise HTTPException(status_code=403, detail={"code": "insufficient_privilege"})


def _visibility_sql(alias: str = "hold") -> str:
    return f"""(user_has_global_privilege(current_user_id(),'holds.administer')
      OR user_has_global_privilege(current_user_id(),'holds.held_items.manage_all')
      OR EXISTS (SELECT 1 FROM user_role_assignments governance_assignment
                 JOIN roles governance_role ON governance_role.id=governance_assignment.role_id
                 WHERE governance_assignment.user_id=current_user_id()
                   AND governance_role.is_information_governance
                   AND governance_assignment.valid_from<=CURRENT_TIMESTAMP
                   AND (governance_assignment.valid_until IS NULL OR governance_assignment.valid_until>CURRENT_TIMESTAMP)
                   AND role_effectively_active(governance_role.id))
      OR {alias}.owner_user_id=current_user_id()
      OR EXISTS (SELECT 1 FROM hold_contributors contributor
                 JOIN users contributor_user ON contributor_user.id=contributor.user_id
                 WHERE contributor.hold_id={alias}.id AND contributor.user_id=current_user_id()
                   AND contributor_user.date_deactivated IS NULL
                   AND contributor_user.date_suspended IS NULL))"""


def _hold(connection: Connection, hold_id: int, *, lock: bool = False) -> dict:
    row = connection.execute(
        f"SELECT * FROM holds hold WHERE hold.id=%s AND {_visibility_sql()}" + (" FOR UPDATE" if lock else ""),
        (hold_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="hold not found")
    return row


def _state(row: dict) -> str:
    now = row.get("server_time") or datetime.now(row["valid_from"].tzinfo)
    if now < row["valid_from"]:
        return "scheduled"
    if row["valid_to"] is not None and now >= row["valid_to"]:
        return "expired"
    return "active"


def _serialize_hold(connection: Connection, row: dict, language_tag: str = "en") -> dict:
    result = dict(row)
    result.pop("server_time", None)
    result["state"] = _state(row)
    result["is_effective"] = result["state"] == "active"
    result["contributors"] = list(connection.execute(
        """SELECT user_account.id,user_account.name,user_account.email,user_account.status,user_account.translations
             FROM hold_contributors contributor JOIN users user_account ON user_account.id=contributor.user_id
            WHERE contributor.hold_id=%s ORDER BY user_account.name,user_account.id""", (row["id"],),
    ).fetchall())
    localize_rows(result["contributors"], language_tag, "name")
    result["owner"] = connection.execute(
        "SELECT id,name,email,status,translations FROM users WHERE id=%s", (row["owner_user_id"],),
    ).fetchone()
    if result["owner"] is None:
        raise RuntimeError(f"hold {row['id']} references a missing owner")
    localize_rows([result["owner"]], language_tag, "name")
    result["direct_held_item_count"] = connection.execute(
        """SELECT (SELECT count(*) FROM hold_aggregation_assignments assignment
                    WHERE assignment.hold_id=%s AND current_user_can_view_aggregation(assignment.aggregation_id))
                + (SELECT count(*) FROM hold_record_assignments assignment
                    WHERE assignment.hold_id=%s AND current_user_can_view_record(assignment.record_id)) AS value""",
        (row["id"], row["id"]),
    ).fetchone()["value"]
    manager = connection.execute(
        "SELECT current_hold_actor_is_manager(%s) AS value", (row["id"],),
    ).fetchone()["value"]
    admin = _is_admin(connection)
    result["capabilities"] = {
        "update": admin, "delete": admin and result["direct_held_item_count"] == 0, "manage_contributors": admin,
        "manage_held_items": manager,
    }
    result["capability_reasons"] = {
        "update": None if admin else "holds_administer_required",
        "delete": (None if admin and result["direct_held_item_count"] == 0
                   else "hold_not_empty" if admin else "holds_administer_required"),
        "manage_contributors": None if admin else "holds_administer_required",
        "manage_held_items": None if manager else "hold_held_item_manager_required",
    }
    return result


def _serialize_holds(connection: Connection, rows: list[dict], language_tag: str = "en") -> list[dict]:
    """Serialize a page with set-based related-data reads (no per-row queries)."""
    if not rows:
        return []
    hold_ids=[row["id"] for row in rows]
    owner_ids=list({row["owner_user_id"] for row in rows})
    owners={row["id"]:row for row in connection.execute(
        "SELECT id,name,email,status,translations FROM users WHERE id=ANY(%s::bigint[])",(owner_ids,),
    ).fetchall()}
    localize_rows(list(owners.values()), language_tag, "name")
    contributors:dict[int,list[dict]]={hold_id:[] for hold_id in hold_ids}
    for contributor in connection.execute(
        """SELECT c.hold_id,u.id,u.name,u.email,u.status,u.translations FROM hold_contributors c
             JOIN users u ON u.id=c.user_id WHERE c.hold_id=ANY(%s::bigint[])
             ORDER BY c.hold_id,u.name,u.id""",(hold_ids,),
    ).fetchall():
        hold_id=contributor.pop("hold_id"); contributors[hold_id].append(contributor)
    for hold_contributors in contributors.values():
        localize_rows(hold_contributors, language_tag, "name")
    counts={row["hold_id"]:row["value"] for row in connection.execute(
        """SELECT requested.hold_id,
                  (SELECT count(*) FROM hold_aggregation_assignments a WHERE a.hold_id=requested.hold_id AND current_user_can_view_aggregation(a.aggregation_id))
                + (SELECT count(*) FROM hold_record_assignments r WHERE r.hold_id=requested.hold_id AND current_user_can_view_record(r.record_id)) value
             FROM unnest(%s::bigint[]) requested(hold_id)""",(hold_ids,),
    ).fetchall()}
    managers={row["hold_id"]:row["value"] for row in connection.execute(
        "SELECT id hold_id,current_hold_actor_is_manager(id) value FROM holds WHERE id=ANY(%s::bigint[])",(hold_ids,),
    ).fetchall()}
    admin=_is_admin(connection); results=[]
    for row in rows:
        result=dict(row); result.pop("server_time",None)
        result["state"]=_state(row); result["is_effective"]=result["state"]=="active"
        result["owner"]=owners[row["owner_user_id"]]; result["contributors"]=contributors[row["id"]]
        result["direct_held_item_count"]=counts[row["id"]]; manager=managers[row["id"]]
        result["capabilities"]={"update":admin,"delete":admin and not counts[row["id"]],"manage_contributors":admin,"manage_held_items":manager}
        result["capability_reasons"]={"update":None if admin else "holds_administer_required",
            "delete":None if admin and not counts[row["id"]] else "hold_not_empty" if admin else "holds_administer_required",
            "manage_contributors":None if admin else "holds_administer_required",
            "manage_held_items":None if manager else "hold_held_item_manager_required"}
        results.append(result)
    return results


@router.get("/holds", response_model=HoldPage)
@operation_policy("relationship_scoped")
def list_holds(
    request: Request,
    q: str | None = None, state_filter: Literal["scheduled", "active", "expired"] | None = Query(None, alias="state"),
    owner_user_id: int | None = None, contributor_user_id: int | None = None,
    valid_from_gte: datetime | None = None, valid_from_lt: datetime | None = None,
    valid_to_gte: datetime | None = None, valid_to_lt: datetime | None = None,
    preserve_resource_state: bool | None = None,
    sort: Literal["code", "name", "state", "valid_from", "valid_to", "owner", "created", "updated"] = "code",
    descending: bool = False, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    order = {"code": "lower(hold.code)", "name": "lower(hold.name)", "state": "state", "valid_from": "hold.valid_from", "valid_to": "hold.valid_to", "owner": "lower(owner.name)", "created": "hold.date_created", "updated": "hold.date_updated"}[sort]
    predicates = f"""WHERE {_visibility_sql()}
                AND (%s::text IS NULL OR hold.code ILIKE '%%'||%s||'%%' OR hold.name ILIKE '%%'||%s||'%%')
                AND (%s::bigint IS NULL OR hold.owner_user_id=%s)
                AND (%s::bigint IS NULL OR EXISTS(SELECT 1 FROM hold_contributors c WHERE c.hold_id=hold.id AND c.user_id=%s))
                AND (%s::boolean IS NULL OR hold.preserve_resource_state=%s)
                AND (%s::text IS NULL OR CASE WHEN CURRENT_TIMESTAMP<hold.valid_from THEN 'scheduled'
                         WHEN hold.valid_to IS NOT NULL AND CURRENT_TIMESTAMP>=hold.valid_to THEN 'expired' ELSE 'active' END=%s)
                AND (%s::timestamptz IS NULL OR hold.valid_from >= %s)
                AND (%s::timestamptz IS NULL OR hold.valid_from < %s)
                AND (%s::timestamptz IS NULL OR hold.valid_to >= %s)
                AND (%s::timestamptz IS NULL OR hold.valid_to < %s)"""
    parameters = (q,q,q,owner_user_id,owner_user_id,contributor_user_id,contributor_user_id,
                  preserve_resource_state,preserve_resource_state,state_filter,state_filter,
                  valid_from_gte,valid_from_gte,valid_from_lt,valid_from_lt,
                  valid_to_gte,valid_to_gte,valid_to_lt,valid_to_lt)
    total = connection.execute(
        f"SELECT count(*) value FROM holds hold JOIN users owner ON owner.id=hold.owner_user_id {predicates}",
        parameters,
    ).fetchone()["value"]
    rows = connection.execute(
        f"""SELECT hold.*,CURRENT_TIMESTAMP server_time,
                    CASE WHEN CURRENT_TIMESTAMP<hold.valid_from THEN 'scheduled'
                         WHEN hold.valid_to IS NOT NULL AND CURRENT_TIMESTAMP>=hold.valid_to THEN 'expired'
                         ELSE 'active' END state
               FROM holds hold JOIN users owner ON owner.id=hold.owner_user_id
              {predicates}
              ORDER BY {order} {'DESC' if descending else 'ASC'},hold.id LIMIT %s OFFSET %s""",
        (*parameters,limit,offset),
    ).fetchall()
    items = _serialize_holds(connection, list(rows), preferred_language(connection, request))
    return {"items": items, "total": total, "limit": limit, "offset": offset, "returned": len(items)}


@router.post("/holds", status_code=201, dependencies=[Depends(require_holds_administer)], response_model=HoldResponse)
def create_hold(payload: HoldCreate, request: Request, connection: Connection = Depends(get_consistent_connection, scope="function")):
    _require_admin(connection)
    connection.execute(
        "SELECT set_config('app.hold_contributor_ids',%s,true)",
        (json.dumps(sorted(payload.contributor_user_ids)),),
    )
    values = payload.model_dump(exclude={"contributor_user_ids"})
    values["code"] = values["code"].strip(); values["name"] = values["name"].strip()
    columns = ",".join(values); placeholders = ",".join(["%s"] * len(values))
    row = connection.execute(
        f"INSERT INTO holds ({columns}) VALUES ({placeholders}) RETURNING *,CURRENT_TIMESTAMP server_time",
        tuple(values.values()),
    ).fetchone()
    for user_id in payload.contributor_user_ids:
        connection.execute("INSERT INTO hold_contributors(hold_id,user_id) VALUES (%s,%s)", (row["id"], user_id))
    notify_assignments(connection, row["id"], [payload.owner_user_id, *payload.contributor_user_ids], _user_id(connection))
    return _serialize_hold(connection, row, preferred_language(connection, request))


@router.get("/holds/people", response_model=list[UserReference])
@operation_policy("relationship_scoped")
def list_hold_people(request: Request, connection: Connection = Depends(get_connection, scope="function")):
    rows = list(connection.execute(
        f"""SELECT DISTINCT person.id,person.name,person.email,person.status,person.translations
              FROM users person
             WHERE EXISTS(SELECT 1 FROM holds hold WHERE hold.owner_user_id=person.id AND {_visibility_sql()})
                OR EXISTS(SELECT 1 FROM hold_contributors c JOIN holds hold ON hold.id=c.hold_id
                            WHERE c.user_id=person.id AND {_visibility_sql()})
             ORDER BY person.name,person.id"""
    ).fetchall())
    return localize_rows(rows, preferred_language(connection, request), "name")


@router.get("/holds/{hold_id}", response_model=HoldResponse)
@operation_policy("relationship_scoped")
def get_hold(hold_id: int, request: Request, connection: Connection = Depends(get_connection, scope="function")):
    row = _hold(connection, hold_id)
    row["server_time"] = connection.execute("SELECT CURRENT_TIMESTAMP value").fetchone()["value"]
    return _serialize_hold(connection, row, preferred_language(connection, request))


@router.patch("/holds/{hold_id}", dependencies=[Depends(require_holds_administer)], response_model=HoldResponse)
def update_hold(hold_id: int, payload: HoldUpdate, request: Request, version: int = Depends(expected_version), connection: Connection = Depends(get_consistent_connection, scope="function")):
    _require_admin(connection); _reason(request)
    existing = _hold(connection, hold_id, lock=True)
    if existing["version"] != version:
        raise HTTPException(status_code=409, detail={"code": "stale_version"})
    values = payload.model_dump(exclude_unset=True)
    if not values:
        existing["server_time"] = datetime.now(existing["valid_from"].tzinfo); return _serialize_hold(connection, existing, preferred_language(connection, request))
    if "code" in values: values["code"] = values["code"].strip()
    if "name" in values: values["name"] = values["name"].strip()
    assignments = ",".join(f"{key}=%s" for key in values)
    row = connection.execute(f"UPDATE holds SET {assignments} WHERE id=%s AND version=%s RETURNING *,CURRENT_TIMESTAMP server_time", (*values.values(),hold_id,version)).fetchone()
    if row is None: raise HTTPException(status_code=409, detail={"code": "stale_version"})
    if row["owner_user_id"] != existing["owner_user_id"]:
        notify_assignments(connection, hold_id, [row["owner_user_id"]], _user_id(connection))
    return _serialize_hold(connection, row, preferred_language(connection, request))


@router.delete("/holds/{hold_id}", status_code=204, dependencies=[Depends(require_holds_administer)])
def delete_hold(hold_id: int, request: Request, version: int = Depends(expected_version), connection: Connection = Depends(get_connection, scope="function")):
    _require_admin(connection); _reason(request); _hold(connection, hold_id, lock=True)
    held_item_count = connection.execute(
        "SELECT (SELECT count(*) FROM hold_aggregation_assignments WHERE hold_id=%s) + "
        "(SELECT count(*) FROM hold_record_assignments WHERE hold_id=%s) value",
        (hold_id, hold_id),
    ).fetchone()["value"]
    if held_item_count:
        raise HTTPException(status_code=409, detail={"code": "hold_not_empty", "held_item_count": held_item_count})
    row = connection.execute("DELETE FROM holds WHERE id=%s AND version=%s RETURNING id", (hold_id,version)).fetchone()
    if row is None: raise HTTPException(status_code=409, detail={"code": "stale_version"})
    return Response(status_code=204)


@router.get("/holds/{hold_id}/contributors")
@operation_policy("relationship_scoped")
def list_contributors(hold_id: int, request: Request, connection: Connection = Depends(get_connection, scope="function")):
    _hold(connection, hold_id)
    rows = list(connection.execute("SELECT user_account.id,user_account.name,user_account.email,user_account.status,user_account.translations FROM hold_contributors c JOIN users user_account ON user_account.id=c.user_id WHERE c.hold_id=%s ORDER BY user_account.name,user_account.id", (hold_id,)).fetchall())
    return localize_rows(rows, preferred_language(connection, request), "name")


@router.put("/holds/{hold_id}/contributors", dependencies=[Depends(require_holds_administer)])
def replace_contributors(hold_id: int, payload: ContributorReplace, request: Request, version: int = Depends(expected_version), connection: Connection = Depends(get_consistent_connection, scope="function")):
    _require_admin(connection); reason = _reason(request); hold = _hold(connection, hold_id, lock=True)
    if hold["version"] != version: raise HTTPException(status_code=409, detail={"code": "stale_version"})
    if len(set(payload.user_ids)) != len(payload.user_ids) or hold["owner_user_id"] in payload.user_ids:
        raise HTTPException(status_code=422, detail={"code": "invalid_hold_contributors"})
    old_ids = [row["user_id"] for row in connection.execute(
        "SELECT user_id FROM hold_contributors WHERE hold_id=%s ORDER BY user_id FOR UPDATE", (hold_id,),
    ).fetchall()]
    connection.execute("DELETE FROM hold_contributors WHERE hold_id=%s", (hold_id,))
    for user_id in payload.user_ids:
        connection.execute("INSERT INTO hold_contributors(hold_id,user_id) VALUES (%s,%s)", (hold_id,user_id))
    row = connection.execute("UPDATE holds SET version=version+1,date_updated=CURRENT_TIMESTAMP WHERE id=%s RETURNING *,CURRENT_TIMESTAMP server_time", (hold_id,)).fetchone()
    connection.execute(
        "SELECT append_domain_event('hold',%s,'HOLD_CONTRIBUTORS_REPLACED',%s::jsonb,%s)",
        (hold_id, json.dumps({"added_user_ids": sorted(set(payload.user_ids) - set(old_ids)),
                              "removed_user_ids": sorted(set(old_ids) - set(payload.user_ids)),
                              "before_user_ids": old_ids, "after_user_ids": sorted(payload.user_ids)}), reason),
    )
    notify_assignments(connection, hold_id, set(payload.user_ids) - set(old_ids), _user_id(connection))
    return _serialize_hold(connection,row,preferred_language(connection, request))


def _resource_visible(connection: Connection, resource_type: str, resource_id: int) -> dict:
    require_resource_operation(connection, resource_type, resource_id, f"{resource_type}.view", f"{resource_type}.view")
    table = "aggregations" if resource_type == "aggregation" else "records"
    return connection.execute(f"SELECT * FROM {table} WHERE id=%s", (resource_id,)).fetchone()


def _held_item(connection: Connection, hold_id: int, resource_type: str, resource_id: int) -> dict:
    table = f"hold_{resource_type}_assignments" if resource_type == "record" else "hold_aggregation_assignments"
    column = f"{resource_type}_id"
    return connection.execute(f"SELECT * FROM {table} WHERE hold_id=%s AND {column}=%s", (hold_id,resource_id)).fetchone()


def _require_hold_manager(connection: Connection, hold_id: int) -> None:
    if not connection.execute(
        "SELECT current_hold_actor_is_manager(%s) AS allowed", (hold_id,),
    ).fetchone()["allowed"]:
        raise HTTPException(status_code=403, detail={"code": "hold_held_item_manager_required"})


@router.get("/holds/{hold_id}/held-item-candidates", response_model=CandidatePage)
@operation_policy("relationship_scoped")
def list_hold_held_item_candidates(
    hold_id: int, q: str | None = None,
    resource_type: Literal["aggregation", "record"] | None = None,
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _hold(connection, hold_id)
    _require_hold_manager(connection, hold_id)
    parameters = (hold_id, hold_id, resource_type, resource_type, q, q, q, q)
    cte = """WITH candidates AS (
      SELECT 'aggregation'::text resource_type,a.id resource_id,
             a.aggregation_number number,a.title,a.description
        FROM aggregations a
       WHERE current_user_can_view_aggregation(a.id)
         AND NOT EXISTS (SELECT 1 FROM hold_aggregation_assignments x
                          WHERE x.hold_id=%s AND x.aggregation_id=a.id)
      UNION ALL
      SELECT 'record'::text,r.id,r.record_number,r.title,r.description
        FROM records r
       WHERE current_user_can_view_record(r.id)
         AND NOT EXISTS (SELECT 1 FROM hold_record_assignments x
                          WHERE x.hold_id=%s AND x.record_id=r.id)
    )"""
    where = """ WHERE (%s::text IS NULL OR resource_type=%s)
                    AND (%s::text IS NULL OR number ILIKE '%%'||%s||'%%'
                                          OR title ILIKE '%%'||%s||'%%'
                                          OR description ILIKE '%%'||%s||'%%')"""
    total = connection.execute(cte + " SELECT count(*) value FROM candidates" + where, parameters).fetchone()["value"]
    items = connection.execute(
        cte + " SELECT * FROM candidates" + where
        + " ORDER BY lower(number),resource_type,resource_id LIMIT %s OFFSET %s",
        (*parameters, limit, offset),
    ).fetchall()
    return {"items": list(items), "total": total, "limit": limit, "offset": offset}


@router.get("/holds/{hold_id}/held-items", response_model=HoldHeldItemPage)
@operation_policy("relationship_scoped")
def list_hold_held_items(
    hold_id: int, request: Request, q: str | None = None,
    resource_type: Literal["aggregation","record"] | None = None,
    assigned_by_user_id: int | None = None,
    assigned_from: datetime | None = None, assigned_before: datetime | None = None,
    sort: Literal["number","title","type","assigned_at","assigned_by","security_level"]="assigned_at",
    descending: bool=False, limit: int=Query(25,ge=1,le=100), offset: int=Query(0,ge=0),
    connection: Connection=Depends(get_connection,scope="function"),
):
    _hold(connection,hold_id)
    order={"number":"lower(number)","title":"lower(title)","type":"resource_type","assigned_at":"assigned_at",
           "assigned_by":"lower(assigned_by_name)","security_level":"security_level_number"}[sort]
    cte = """WITH held_items AS (
      SELECT x.id,x.version,'aggregation'::text resource_type,a.id resource_id,a.aggregation_number number,
             a.title,a.description,a.security_level_id,x.assigned_at,x.assigned_by_user_id
      FROM hold_aggregation_assignments x JOIN aggregations a ON a.id=x.aggregation_id
      WHERE x.hold_id=%s AND current_user_can_view_aggregation(a.id)
      UNION ALL
      SELECT x.id,x.version,'record',r.id,r.record_number,r.title,r.description,r.security_level_id,x.assigned_at,x.assigned_by_user_id
      FROM hold_record_assignments x JOIN records r ON r.id=x.record_id
      WHERE x.hold_id=%s AND current_user_can_view_record(r.id)), enriched AS (
      SELECT held_items.*,u.name assigned_by_name,u.translations assigned_by_translations,
             sl.code security_level_code,sl.translations security_level_translations,
             sl.name security_level_name,sl.level_number security_level_number
      FROM held_items LEFT JOIN users u ON u.id=assigned_by_user_id JOIN security_levels sl ON sl.id=security_level_id)"""
    where = """ WHERE (%s::text IS NULL OR resource_type=%s)
      AND (%s::text IS NULL OR number ILIKE '%%'||%s||'%%' OR title ILIKE '%%'||%s||'%%' OR description ILIKE '%%'||%s||'%%')
      AND (%s::bigint IS NULL OR assigned_by_user_id=%s)
      AND (%s::timestamptz IS NULL OR assigned_at >= %s)
      AND (%s::timestamptz IS NULL OR assigned_at < %s)"""
    parameters = (hold_id,hold_id,resource_type,resource_type,q,q,q,q,
                  assigned_by_user_id,assigned_by_user_id,assigned_from,assigned_from,assigned_before,assigned_before)
    total = connection.execute(cte + " SELECT count(*) value FROM enriched" + where, parameters).fetchone()["value"]
    rows = connection.execute(
        cte + " SELECT * FROM enriched" + where
        + f" ORDER BY {order} {'DESC' if descending else 'ASC'},resource_type,resource_id LIMIT %s OFFSET %s",
        (*parameters,limit,offset),
    ).fetchall()
    language_tag = preferred_language(connection, request)
    for row in rows:
        for field in ("assigned_by", "security_level"):
            row[f"{field}_name"] = localized_projection({
                "name": row[f"{field}_name"],
                "translations": row.pop(f"{field}_translations", None),
            }, language_tag, "name")["name"]
    return {"items": list(rows), "total": total, "limit": limit, "offset": offset, "returned": len(rows)}


def _add_held_item(connection: Connection, hold_id: int, resource_type: str, resource_id: int, request: Request):
    _hold(connection,hold_id); _reason(request); _resource_visible(connection,resource_type,resource_id)
    existing=_held_item(connection,hold_id,resource_type,resource_id)
    if existing is not None: return existing
    table="hold_aggregation_assignments" if resource_type=="aggregation" else "hold_record_assignments"; column=f"{resource_type}_id"
    return connection.execute(f"INSERT INTO {table}(hold_id,{column}) VALUES (%s,%s) RETURNING *",(hold_id,resource_id)).fetchone()


@router.post("/holds/{hold_id}/held-items", status_code=201)
@operation_policy("relationship_scoped")
def add_hold_held_item(hold_id:int,payload:HoldHeldItemCreate,request:Request,connection:Connection=Depends(get_connection,scope="function")):
    _require_hold_manager(connection, hold_id)
    return _add_held_item(connection,hold_id,payload.resource_type,payload.resource_id,request)


@router.post("/holds/{hold_id}/held-items/bulk", status_code=201)
@operation_policy("relationship_scoped")
def add_hold_held_items_bulk(
    hold_id: int, payload: HoldHeldItemsBulkCreate, request: Request,
    connection: Connection = Depends(get_connection, scope="function"),
):
    _hold(connection, hold_id)
    _require_hold_manager(connection, hold_id)
    _reason(request)
    added = 0
    already_held_items = 0
    for held_item in payload.held_items:
        _resource_visible(connection, held_item.resource_type, held_item.resource_id)
        table = ("hold_aggregation_assignments" if held_item.resource_type == "aggregation"
                 else "hold_record_assignments")
        column = f"{held_item.resource_type}_id"
        row = connection.execute(
            f"INSERT INTO {table}(hold_id,{column}) VALUES (%s,%s) "
            f"ON CONFLICT (hold_id,{column}) DO NOTHING RETURNING id",
            (hold_id, held_item.resource_id),
        ).fetchone()
        if row is None:
            already_held_items += 1
        else:
            added += 1
    return {"requested": len(payload.held_items), "added": added,
            "already_held_items": already_held_items}


@router.delete("/holds/{hold_id}/held-items/{resource_type}/{resource_id}",status_code=204)
@operation_policy("relationship_scoped")
def remove_hold_held_item(hold_id:int,resource_type:Literal["aggregation","record"],resource_id:int,request:Request,version:int=Depends(expected_version),connection:Connection=Depends(get_connection,scope="function")):
    _hold(connection,hold_id); _require_hold_manager(connection, hold_id); _reason(request); _resource_visible(connection,resource_type,resource_id)
    table="hold_aggregation_assignments" if resource_type=="aggregation" else "hold_record_assignments"; column=f"{resource_type}_id"
    deleted=connection.execute(f"DELETE FROM {table} WHERE hold_id=%s AND {column}=%s AND version=%s RETURNING id",(hold_id,resource_id,version)).fetchone()
    if deleted is None:
        exists = _held_item(connection, hold_id, resource_type, resource_id)
        raise HTTPException(status_code=409 if exists else 404,detail={"code":"stale_version" if exists else "hold_assignment_not_found"})
    return Response(status_code=204)


@router.post("/holds/{hold_id}/held-items/bulk-remove")
@operation_policy("relationship_scoped")
def remove_hold_held_items_bulk(
    hold_id: int, payload: HoldHeldItemsBulkRemove, request: Request,
    connection: Connection = Depends(get_connection, scope="function"),
):
    _hold(connection,hold_id); _require_hold_manager(connection,hold_id); _reason(request)
    if len({(item.resource_type,item.resource_id) for item in payload.held_items}) != len(payload.held_items):
        raise HTTPException(status_code=422,detail={"code":"duplicate_hold_assignments"})
    for item in payload.held_items:
        _resource_visible(connection,item.resource_type,item.resource_id)
        table="hold_aggregation_assignments" if item.resource_type=="aggregation" else "hold_record_assignments"
        column=f"{item.resource_type}_id"
        deleted=connection.execute(
            f"DELETE FROM {table} WHERE hold_id=%s AND {column}=%s AND version=%s RETURNING id",
            (hold_id,item.resource_id,item.version),
        ).fetchone()
        if deleted is None:
            raise HTTPException(status_code=409,detail={"code":"stale_version","resource_type":item.resource_type,"resource_id":item.resource_id})
    return {"removed":len(payload.held_items)}


def _effective_holds(connection:Connection,resource_type:str,resource_id:int):
    _resource_visible(connection,resource_type,resource_id)
    rows=connection.execute(f"SELECT * FROM effective_holds_for_{resource_type}(%s) ORDER BY code,hold_id",(resource_id,)).fetchall()
    result=[]
    for row in rows:
        visible=connection.execute(f"SELECT {_visibility_sql()} value FROM holds hold WHERE id=%s",(row["hold_id"],)).fetchone()["value"]
        item={"kind":"effective_hold","source":"both" if row["is_direct"] and row["is_inherited"] else ("direct" if row["is_direct"] else "inherited"),"directly_assigned_resource":row["is_direct"],"preserve_resource_state":row["preserve_resource_state"]}
        item["can_manage_held_items"] = bool(connection.execute(
            "SELECT current_hold_actor_is_manager(%s) value", (row["hold_id"],),
        ).fetchone()["value"])
        if row["is_direct"]:
            assignment = _held_item(connection, row["hold_id"], resource_type, resource_id)
            item["direct_assignment_version"] = assignment["version"] if assignment else None
        if visible: item.update(dict(row))
        result.append(item)
    return result


@router.get("/aggregations/{resource_id}/effective-holds", response_model=list[EffectiveHoldResponse])
@operation_policy("resource_scoped", "aggregation.view", "aggregation.view")
def aggregation_effective_holds(resource_id:int,connection:Connection=Depends(get_connection,scope="function")): return _effective_holds(connection,"aggregation",resource_id)
@router.get("/records/{resource_id}/effective-holds", response_model=list[EffectiveHoldResponse])
@operation_policy("resource_scoped", "record.view", "record.view")
def record_effective_holds(resource_id:int,connection:Connection=Depends(get_connection,scope="function")): return _effective_holds(connection,"record",resource_id)


def _resource_add(resource_type:str,resource_id:int,payload:ResourceHoldCreate,request:Request,connection:Connection): return _add_held_item(connection,payload.hold_id,resource_type,resource_id,request)
@router.post("/aggregations/{resource_id}/holds",status_code=201)
@operation_policy("resource_scoped", "aggregation.view", "aggregation.view")
def add_aggregation_hold(resource_id:int,payload:ResourceHoldCreate,request:Request,connection:Connection=Depends(get_connection,scope="function")): return _resource_add("aggregation",resource_id,payload,request,connection)
@router.post("/records/{resource_id}/holds",status_code=201)
@operation_policy("resource_scoped", "record.view", "record.view")
def add_record_hold(resource_id:int,payload:ResourceHoldCreate,request:Request,connection:Connection=Depends(get_connection,scope="function")): return _resource_add("record",resource_id,payload,request,connection)


def _remove_direct(connection:Connection,resource_type:str,resource_id:int,request:Request,hold_id:int|None):
    reason = _reason(request); _resource_visible(connection,resource_type,resource_id)
    table="hold_aggregation_assignments" if resource_type=="aggregation" else "hold_record_assignments"; column=f"{resource_type}_id"
    rows=connection.execute(f"SELECT hold_id FROM {table} WHERE {column}=%s"+(" AND hold_id=%s" if hold_id else "")+" FOR UPDATE",(resource_id,hold_id) if hold_id else (resource_id,)).fetchall()
    if hold_id and not rows: raise HTTPException(status_code=404,detail={"code":"hold_assignment_not_found"})
    if any(not connection.execute("SELECT current_hold_actor_is_manager(%s) value",(r["hold_id"],)).fetchone()["value"] for r in rows): raise HTTPException(status_code=403,detail={"code":"hold_held_item_manager_required"})
    connection.execute(f"DELETE FROM {table} WHERE {column}=%s"+(" AND hold_id=%s" if hold_id else ""),(resource_id,hold_id) if hold_id else (resource_id,))
    remaining = _effective_holds(connection,resource_type,resource_id)
    removed_ids = [r["hold_id"] for r in rows]
    if hold_id is None and removed_ids:
        connection.execute(
            "SELECT append_domain_event(%s,%s,'ALL_DIRECT_HOLDS_REMOVED',%s::jsonb,%s)",
            (resource_type, resource_id, json.dumps({"removed_hold_ids": removed_ids,
             "remaining_effective_hold_ids": [item.get("hold_id") for item in remaining if item.get("hold_id")]}), reason),
        )
    return {"removed_hold_ids":removed_ids,"remaining_effective_holds":remaining}


@router.delete("/aggregations/{resource_id}/holds/{hold_id}")
@operation_policy("resource_scoped", "aggregation.view", "aggregation.view")
def remove_aggregation_hold(resource_id:int,hold_id:int,request:Request,connection:Connection=Depends(get_connection,scope="function")): return _remove_direct(connection,"aggregation",resource_id,request,hold_id)
@router.delete("/records/{resource_id}/holds/{hold_id}")
@operation_policy("resource_scoped", "record.view", "record.view")
def remove_record_hold(resource_id:int,hold_id:int,request:Request,connection:Connection=Depends(get_connection,scope="function")): return _remove_direct(connection,"record",resource_id,request,hold_id)
@router.delete("/aggregations/{resource_id}/holds")
@operation_policy("resource_scoped", "aggregation.view", "aggregation.view")
def remove_all_aggregation_holds(resource_id:int,request:Request,connection:Connection=Depends(get_connection,scope="function")): return _remove_direct(connection,"aggregation",resource_id,request,None)
@router.delete("/records/{resource_id}/holds")
@operation_policy("resource_scoped", "record.view", "record.view")
def remove_all_record_holds(resource_id:int,request:Request,connection:Connection=Depends(get_connection,scope="function")): return _remove_direct(connection,"record",resource_id,request,None)


@router.get("/holds/{hold_id}/history")
@operation_policy("relationship_scoped")
def hold_history(
    hold_id: int, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _hold(connection,hold_id)
    return list(connection.execute(
        """SELECT *,occurred_at AS event_timestamp FROM event_history
            WHERE (entity_type='hold' AND entity_id=%s) OR metadata->>'hold_id'=%s
            ORDER BY occurred_at DESC,id DESC LIMIT %s OFFSET %s""",
        (hold_id, str(hold_id), limit, offset),
    ).fetchall())


def _user_id(connection):
    return connection.execute("SELECT current_setting('app.user_id')::bigint AS id").fetchone()['id']
