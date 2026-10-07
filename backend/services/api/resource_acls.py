from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection

from .authorization_policy import require_authorization_admin, require_organization_browse
from .database import get_connection
from .resource_authorization import governance_role_snapshot, require_global, require_resource_operation
from .schemas import (
    AclChangePreviewRead, AclMoveRequest, AclPrincipalGrant, AclReplace,
    ChildAggregationAclChangePreviewRead, ChildAggregationAclRead,
    ChildAggregationAclReplace, ChildRecordAclRead, ChildRecordAclReplace,
    CreationRoleOption, OwnershipCorrectionPreviewRead, OwnershipCorrectionRequest,
    PermissionRead, ResourceAclRead,
)


router = APIRouter(
    prefix="/api/v1", tags=["resource ACLs"],
)

TABLES = {
    "aggregation": ("aggregation_acl_grants", "aggregation_id", "aggregation"),
    "child_aggregation": ("aggregation_child_aggregation_acl_defaults", "aggregation_id", "aggregation"),
    "child_record": ("aggregation_child_record_acl_defaults", "aggregation_id", "record"),
    "record": ("record_acl_grants", "record_id", "record"),
}


@router.get("/{resource}/{resource_id}/acl-contextual-principals")
def contextual_principal_matches(
    resource: Literal["aggregations", "records"], resource_id: int,
    principal_type: Literal["owning_and_higher_level_unit_managers", "effective_file_administrator"],
    limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0),
    _authorization: Any = Depends(require_organization_browse),
    connection: Connection = Depends(get_connection, scope="function"),
):
    kind = "aggregation" if resource == "aggregations" else "record"
    require_resource_operation(connection, kind, resource_id, f"{kind}.acl.manage", f"{kind}.acl.manage", lock=False)
    owner = _resource(connection, resource, resource_id)["owning_org_unit_id"]
    rows = list(connection.execute(
        """WITH RECURSIVE chain AS (
             SELECT id,parent_org_unit_id,code,name,managing_role_id,file_administrator_role_id,0 AS depth
               FROM org_units WHERE id=%s
             UNION ALL
             SELECT parent.id,parent.parent_org_unit_id,parent.code,parent.name,
                    parent.managing_role_id,parent.file_administrator_role_id,child.depth+1
               FROM org_units parent JOIN chain child ON parent.id=child.parent_org_unit_id
           ), selected AS (
             SELECT *,managing_role_id AS designated_role_id FROM chain
               WHERE %s='owning_and_higher_level_unit_managers'
             UNION ALL
             SELECT *,file_administrator_role_id FROM
               (SELECT * FROM chain WHERE file_administrator_role_id IS NOT NULL ORDER BY depth LIMIT 1) nearest
               WHERE %s='effective_file_administrator'
           )
           SELECT selected.id AS org_unit_id,selected.code AS org_unit_code,
                  selected.name AS org_unit_name,role.id AS role_id,role.code AS role_code,
                  role.name AS role_name,COALESCE(role_effectively_active(role.id),false) AS active
             FROM selected LEFT JOIN roles role ON role.id=selected.designated_role_id
            ORDER BY depth LIMIT %s OFFSET %s""",
        (owner, principal_type, principal_type, limit + 1, offset),
    ).fetchall())
    return {"owning_org_unit_id": owner, "items": rows[:limit], "has_more": len(rows)>limit}


def _resource(connection: Connection, table: str, resource_id: int) -> dict[str, Any]:
    visibility = {
        "aggregations": "current_user_can_view_aggregation(id)",
        "records": "current_user_can_view_record(id)",
    }.get(table, "TRUE")
    row = connection.execute(
        f"SELECT * FROM {table} WHERE id=%s AND {visibility} FOR UPDATE", (resource_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="resource not found")
    return row


def _grant_rows(connection: Connection, scope: str, owner_id: int) -> list[dict[str, Any]]:
    table, owner_column, resource_type = TABLES[scope]
    return list(connection.execute(
        f"""SELECT grant_row.id,grant_row.principal_type,grant_row.role_id,
                   role.code AS role_code,role.name AS role_name,
                   permission.id AS permission_id,permission.code AS permission_code
            FROM {table} grant_row
            JOIN permissions permission ON permission.id=grant_row.permission_id
            LEFT JOIN roles role ON role.id=grant_row.role_id
            WHERE grant_row.{owner_column}=%s AND permission.resource_type=%s
            ORDER BY grant_row.principal_type,role.name,permission.code""",
        (owner_id, resource_type),
    ).fetchall())


def _group(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int | None], dict[str, Any]] = {}
    for row in rows:
        key = (row["principal_type"], row["role_id"])
        item = grouped.setdefault(key, {
            "principal_type": row["principal_type"], "role_id": row["role_id"],
            "display_name": {
                "everyone": "Everyone",
                "org_unit_members": "All org unit members",
                "owning_and_higher_level_unit_managers": "Owning and Higher-Level Unit Managers",
                "effective_file_administrator": "Effective File Administrator",
            }.get(row["principal_type"], row["role_name"]),
            "role_code": row["role_code"], "permission_codes": [],
        })
        item["permission_codes"].append(row["permission_code"])
    return list(grouped.values())


def _effective_aggregation(connection: Connection, aggregation_id: int, seen: set[int] | None = None) -> tuple[str, int, list[dict[str, Any]]]:
    seen = seen or set()
    if aggregation_id in seen:
        raise HTTPException(status_code=409, detail="aggregation hierarchy cycle")
    seen.add(aggregation_id)
    aggregation = connection.execute(
        "SELECT id,parent_aggregation_id,inherit_acl_from_parent,default_child_aggregation_acl_mode FROM aggregations WHERE id=%s",
        (aggregation_id,),
    ).fetchone()
    if aggregation is None:
        raise HTTPException(status_code=404, detail="aggregation not found")
    if aggregation["parent_aggregation_id"] is None or not aggregation["inherit_acl_from_parent"]:
        return "resource_override", aggregation_id, _grant_rows(connection, "aggregation", aggregation_id)
    parent = connection.execute(
        "SELECT default_child_aggregation_acl_mode FROM aggregations WHERE id=%s",
        (aggregation["parent_aggregation_id"],),
    ).fetchone()
    if parent["default_child_aggregation_acl_mode"] == "custom":
        return "parent_custom_default", aggregation["parent_aggregation_id"], _grant_rows(connection, "child_aggregation", aggregation["parent_aggregation_id"])
    source, owner_id, rows = _effective_aggregation(connection, aggregation["parent_aggregation_id"], seen)
    return f"parent_mirror:{source}", owner_id, rows


def _effective_record(connection: Connection, record_id: int) -> tuple[str, int, list[dict[str, Any]]]:
    record = connection.execute("SELECT * FROM records WHERE id=%s", (record_id,)).fetchone()
    if record is None:
        raise HTTPException(status_code=404, detail="record not found")
    if not record["inherit_acl_from_parent"]:
        return "resource_override", record_id, _grant_rows(connection, "record", record_id)
    return "parent_default", record["aggregation_id"], _grant_rows(connection, "child_record", record["aggregation_id"])


def _validate_grants(connection: Connection, grants: list[AclPrincipalGrant], resource_type: str) -> list[tuple[str, int | None, int]]:
    result: list[tuple[str, int | None, int]] = []
    seen: set[tuple[str, int | None, str]] = set()
    for grant in grants:
        codes = set(grant.permission_codes)
        rows = connection.execute(
            "SELECT id,code FROM permissions WHERE resource_type=%s AND code=ANY(%s)",
            (resource_type, list(codes) or [""]),
        ).fetchall()
        by_code = {row["code"]: row["id"] for row in rows}
        if set(by_code) != codes:
            raise HTTPException(status_code=422, detail={"code": "unknown_permission", "permissions": sorted(codes-set(by_code))})
        if grant.role_id is not None and connection.execute("SELECT 1 FROM roles WHERE id=%s", (grant.role_id,)).fetchone() is None:
            raise HTTPException(status_code=422, detail={"code": "unknown_role", "role_id": grant.role_id})
        dependencies = connection.execute(
            """SELECT dependent.code,required.code AS required_code
               FROM permission_dependencies dependency
               JOIN permissions dependent ON dependent.id=dependency.permission_id
               JOIN permissions required ON required.id=dependency.required_permission_id
               WHERE dependency.permission_id=ANY(%s)""", (list(by_code.values()) or [0],),
        ).fetchall()
        missing = sorted({row["required_code"] for row in dependencies if row["required_code"] not in codes})
        if missing:
            raise HTTPException(status_code=422, detail={"code": "permission_dependency_violation", "missing": missing})
        for code, permission_id in by_code.items():
            key = (grant.principal_type, grant.role_id, code)
            if key in seen:
                raise HTTPException(status_code=422, detail={"code": "duplicate_acl_grant"})
            seen.add(key); result.append((grant.principal_type, grant.role_id, permission_id))
    return result


def _replace(connection: Connection, scope: str, owner_id: int, grants: list[AclPrincipalGrant]) -> None:
    table, owner_column, resource_type = TABLES[scope]
    values = _validate_grants(connection, grants, resource_type)
    role_ids = sorted({role_id for principal_type, role_id, _ in values if principal_type == "role" and role_id is not None})
    if role_ids:
        resource_table = "records" if scope == "record" else "aggregations"
        insufficient = connection.execute(
            f"""SELECT role.id,role.code FROM roles role
                 JOIN security_levels role_level ON role_level.id=role.security_level_id
                 JOIN {resource_table} resource ON resource.id=%s
                 JOIN security_levels resource_level ON resource_level.id=resource.security_level_id
                 WHERE role.id=ANY(%s) AND role_level.level_number<resource_level.level_number
                 ORDER BY role.id""", (owner_id, role_ids),
        ).fetchall()
        if insufficient:
            raise HTTPException(status_code=422, detail={
                "code": "role_clearance_below_resource", "roles": insufficient,
            })
    connection.execute(f"DELETE FROM {table} WHERE {owner_column}=%s", (owner_id,))
    for principal_type, role_id, permission_id in values:
        connection.execute(
            f"INSERT INTO {table}({owner_column},principal_type,role_id,permission_id) VALUES (%s,%s,%s,%s)",
            (owner_id, principal_type, role_id, permission_id),
        )


def _descendant_impact(connection: Connection, aggregation_id: int) -> dict[str, Any]:
    rows = connection.execute(
        """WITH RECURSIVE affected(id,depth) AS (
             SELECT child.id,1 FROM aggregations child WHERE child.parent_aggregation_id=%s AND child.inherit_acl_from_parent
             UNION ALL
             SELECT child.id,parent.depth+1 FROM aggregations child JOIN affected parent ON child.parent_aggregation_id=parent.id
             JOIN aggregations parent_row ON parent_row.id=parent.id
             WHERE child.inherit_acl_from_parent AND parent_row.default_child_aggregation_acl_mode='mirror_resource_acl')
           SELECT id,depth FROM affected ORDER BY depth,id""", (aggregation_id,),
    ).fetchall()
    ids = [row["id"] for row in rows]
    record_count = connection.execute(
        "SELECT count(*) AS count FROM records WHERE inherit_acl_from_parent AND aggregation_id=ANY(%s)",
        (ids or [aggregation_id],),
    ).fetchone()["count"]
    return {"affected_aggregation_ids": ids, "affected_aggregation_count": len(ids), "affected_record_count": record_count}


def _custodian_count(connection: Connection, level_id: int) -> int:
    return connection.execute(
        """SELECT count(DISTINCT account.id) AS count FROM users account
           JOIN user_role_assignments assignment ON assignment.user_id=account.id
           JOIN roles role ON role.id=assignment.role_id
           JOIN security_levels role_level ON role_level.id=role.security_level_id
           JOIN security_levels resource_level ON resource_level.id=%s
           JOIN profile_privileges membership ON membership.profile_id=role.profile_id
           JOIN privileges privilege ON privilege.id=membership.privilege_id AND privilege.code='authorization.administer'
           WHERE account.account_type='person' AND account.status='active'
             AND role.is_information_governance AND role_level.level_number>=resource_level.level_number
             AND role_effectively_active(role.id)
             AND assignment.valid_from<=CURRENT_TIMESTAMP
             AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)""", (level_id,),
    ).fetchone()["count"]


def _assert_continuity(connection: Connection, level_id: int) -> None:
    if _custodian_count(connection, level_id) == 0:
        raise HTTPException(status_code=409, detail={"code": "resource_without_effective_custodian"})


def _rows_as_inputs(rows: list[dict[str, Any]]) -> list[AclPrincipalGrant]:
    return [AclPrincipalGrant(**{
        key: value for key, value in item.items()
        if key in {"principal_type", "role_id", "permission_codes"}
    }) for item in _group(rows)]


def _permission_set(rows: list[dict[str, Any]]) -> set[tuple[str, int | None, str]]:
    return {(row["principal_type"], row["role_id"], row["permission_code"]) for row in rows}


def _rows_as_values(rows: list[dict[str, Any]]) -> list[tuple[str, int | None, int]]:
    return [(row["principal_type"],row["role_id"],row["permission_id"]) for row in rows]


def _preview_delta(
    connection: Connection, current: list[dict[str, Any]],
    proposed: list[tuple[str, int | None, int]], owner_org_unit_id: int,
) -> dict[str, Any]:
    permission_codes = {row["id"]: row["code"] for row in connection.execute("SELECT id,code FROM permissions").fetchall()}
    old = _permission_set(current)
    new = {(principal, role_id, permission_codes[permission_id]) for principal,role_id,permission_id in proposed}
    changed_roles = {role_id for _,role_id,_ in old.symmetric_difference(new) if role_id is not None}
    everyone_changed = any(principal == "everyone" for principal,_,_ in old.symmetric_difference(new))
    org_unit_members_changed = any(
        principal == "org_unit_members" for principal,_,_ in old.symmetric_difference(new)
    )
    if everyone_changed:
        user_count = connection.execute("SELECT count(*) AS count FROM users WHERE status='active'").fetchone()["count"]
    elif org_unit_members_changed or changed_roles:
        user_count = connection.execute(
            """SELECT count(DISTINCT assignment.user_id) AS count
               FROM user_role_assignments assignment
               JOIN roles role ON role.id=assignment.role_id
               WHERE (assignment.role_id=ANY(%s) OR (%s AND role.org_unit_id=%s))
                 AND assignment.valid_from<=CURRENT_TIMESTAMP
                 AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
                 AND role_effectively_active(role.id)""",
            (list(changed_roles) or [0], org_unit_members_changed, owner_org_unit_id),
        ).fetchone()["count"]
    else: user_count = 0
    return {"added_grants":len(new-old),"removed_grants":len(old-new),"potentially_affected_user_count":user_count}


def _lock_aggregation_subtree(connection: Connection, aggregation_id: int) -> None:
    ids = _descendant_impact(connection,aggregation_id)["affected_aggregation_ids"]
    if ids:
        connection.execute("SELECT id FROM aggregations WHERE id=ANY(%s) ORDER BY id FOR UPDATE",(ids,)).fetchall()


@router.get("/permissions", response_model=list[PermissionRead])
def list_permissions(resource_type: Literal["aggregation", "record"] | None = None, limit: int=Query(500,ge=1,le=500), connection: Connection=Depends(get_connection,scope="function")):
    allowed = connection.execute(
        """SELECT user_has_global_privilege(current_user_id(),'authorization.administer')
                  OR (%s::text IS NOT NULL AND user_has_global_privilege(current_user_id(),%s)) AS allowed""",
        (resource_type, f"{resource_type}.acl.manage" if resource_type else ""),
    ).fetchone()["allowed"]
    if not allowed:
        require_global(connection, "authorization.administer")
    if resource_type is None:
        return list(connection.execute(
            "SELECT * FROM permissions ORDER BY resource_type,code LIMIT %s", (limit,),
        ).fetchall())
    return list(connection.execute(
        "SELECT * FROM permissions WHERE resource_type=%s ORDER BY code LIMIT %s",
        (resource_type,limit),
    ).fetchall())


@router.get("/aggregations/{aggregation_id}/permissions", response_model=ResourceAclRead)
def aggregation_permissions(aggregation_id:int, connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"aggregation",aggregation_id,"aggregation.acl.manage","aggregation.acl.manage",lock=False)
    return _aggregation_permissions(aggregation_id, connection)


def _aggregation_permissions(aggregation_id: int, connection: Connection):
    aggregation=_resource(connection,"aggregations",aggregation_id)
    source,source_id,effective=_effective_aggregation(connection,aggregation_id)
    return {"inherit_acl_from_parent":aggregation["inherit_acl_from_parent"],"effective_acl":_group(effective),
            "effective_acl_source":source,"effective_acl_source_id":source_id,"override_acl":_group(_grant_rows(connection,"aggregation",aggregation_id)),
            "override_acl_is_dormant":bool(aggregation["parent_aggregation_id"] and aggregation["inherit_acl_from_parent"]),
            "resource_acl_version":aggregation["resource_acl_version"]}


@router.put("/aggregations/{aggregation_id}/permissions", response_model=ResourceAclRead)
def replace_aggregation_permissions(aggregation_id:int,payload:AclReplace,connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"aggregation",aggregation_id,"aggregation.acl.manage","aggregation.acl.manage")
    aggregation=_resource(connection,"aggregations",aggregation_id)
    if aggregation["resource_acl_version"]!=payload.version: raise HTTPException(status_code=409,detail="acl_version_conflict")
    inherit=aggregation["inherit_acl_from_parent"] if payload.inherit_acl_from_parent is None else payload.inherit_acl_from_parent
    if aggregation["parent_aggregation_id"] is None and inherit: raise HTTPException(status_code=422,detail="root_aggregation_cannot_inherit_acl")
    grants=payload.grants
    if payload.initialize_override_from_inherited:
        grants=[AclPrincipalGrant(**{k:v for k,v in item.items() if k in {"principal_type","role_id","permission_codes"}}) for item in _group(_effective_aggregation(connection,aggregation_id)[2])]
    _replace(connection,"aggregation",aggregation_id,grants)
    _assert_continuity(connection,aggregation["security_level_id"])
    connection.execute("UPDATE aggregations SET inherit_acl_from_parent=%s,resource_acl_version=resource_acl_version+1,version=version+1 WHERE id=%s",(inherit,aggregation_id))
    connection.execute("SELECT append_domain_event('aggregation',%s,'ACL_REPLACED',%s::jsonb,%s)",(aggregation_id,json.dumps({"inherit_acl_from_parent":inherit}),payload.reason))
    return _aggregation_permissions(aggregation_id,connection)


@router.get("/aggregations/{aggregation_id}/default-child-aggregation-permissions", response_model=ChildAggregationAclRead, dependencies=[Depends(require_authorization_admin)])
def child_aggregation_permissions(aggregation_id:int,connection:Connection=Depends(get_connection,scope="function")):
    aggregation=_resource(connection,"aggregations",aggregation_id)
    custom=_grant_rows(connection,"child_aggregation",aggregation_id)
    if aggregation["default_child_aggregation_acl_mode"]=="custom": effective=custom; source="custom"
    else: source="mirror_resource_acl"; effective=_effective_aggregation(connection,aggregation_id)[2]
    return {"mode":aggregation["default_child_aggregation_acl_mode"],"effective_acl":_group(effective),
            "custom_acl":_group(custom),"custom_acl_is_dormant":source!="custom",
            "version":aggregation["child_aggregation_acl_version"],**_descendant_impact(connection,aggregation_id)}


@router.put("/aggregations/{aggregation_id}/default-child-aggregation-permissions", response_model=ChildAggregationAclRead, dependencies=[Depends(require_authorization_admin)])
def replace_child_aggregation_permissions(aggregation_id:int,payload:ChildAggregationAclReplace,connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"aggregation",aggregation_id,"aggregation.acl.manage","aggregation.acl.manage")
    aggregation=_resource(connection,"aggregations",aggregation_id)
    if aggregation["child_aggregation_acl_version"]!=payload.version: raise HTTPException(status_code=409,detail="acl_version_conflict")
    _lock_aggregation_subtree(connection,aggregation_id)
    grants=payload.grants
    if payload.initialize_custom_from_mirrored:
        grants=[AclPrincipalGrant(**{k:v for k,v in item.items() if k in {"principal_type","role_id","permission_codes"}}) for item in _group(_effective_aggregation(connection,aggregation_id)[2])]
    _replace(connection,"child_aggregation",aggregation_id,grants)
    _assert_continuity(connection,aggregation["security_level_id"])
    connection.execute("UPDATE aggregations SET default_child_aggregation_acl_mode=%s,child_aggregation_acl_version=child_aggregation_acl_version+1,version=version+1 WHERE id=%s",(payload.mode,aggregation_id))
    connection.execute("SELECT append_domain_event('aggregation',%s,'DEFAULT_CHILD_AGGREGATION_ACL_REPLACED',%s::jsonb,%s)",(aggregation_id,json.dumps({"mode":payload.mode,**_descendant_impact(connection,aggregation_id)}),payload.reason))
    return child_aggregation_permissions(aggregation_id,connection)


@router.post("/aggregations/{aggregation_id}/default-child-aggregation-permissions/preview", response_model=ChildAggregationAclChangePreviewRead, dependencies=[Depends(require_authorization_admin)])
def preview_child_aggregation_permissions(aggregation_id:int,payload:ChildAggregationAclReplace,connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"aggregation",aggregation_id,"aggregation.acl.manage","aggregation.acl.manage",lock=False)
    aggregation=_resource(connection,"aggregations",aggregation_id)
    if aggregation["child_aggregation_acl_version"]!=payload.version: raise HTTPException(status_code=409,detail="acl_version_conflict")
    custom_proposed=_validate_grants(connection,payload.grants,"aggregation")
    current = (_grant_rows(connection,"child_aggregation",aggregation_id)
               if aggregation["default_child_aggregation_acl_mode"]=="custom"
               else _effective_aggregation(connection,aggregation_id)[2])
    proposed = (custom_proposed if payload.mode=="custom"
                else _rows_as_values(_effective_aggregation(connection,aggregation_id)[2]))
    return {**_preview_delta(connection,current,proposed,aggregation["owning_org_unit_id"]),**_descendant_impact(connection,aggregation_id),"mode":payload.mode,"version":payload.version}


@router.get("/aggregations/{aggregation_id}/default-child-record-permissions", response_model=ChildRecordAclRead, dependencies=[Depends(require_authorization_admin)])
def child_record_permissions(aggregation_id:int,connection:Connection=Depends(get_connection,scope="function")):
    aggregation=_resource(connection,"aggregations",aggregation_id)
    return {"effective_acl":_group(_grant_rows(connection,"child_record",aggregation_id)),"version":aggregation["child_record_acl_version"],
            "affected_record_count":connection.execute("SELECT count(*) AS count FROM records WHERE aggregation_id=%s AND inherit_acl_from_parent",(aggregation_id,)).fetchone()["count"]}


@router.put("/aggregations/{aggregation_id}/default-child-record-permissions", response_model=ChildRecordAclRead, dependencies=[Depends(require_authorization_admin)])
def replace_child_record_permissions(aggregation_id:int,payload:ChildRecordAclReplace,connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"aggregation",aggregation_id,"aggregation.acl.manage","aggregation.acl.manage")
    aggregation=_resource(connection,"aggregations",aggregation_id)
    if aggregation["child_record_acl_version"]!=payload.version: raise HTTPException(status_code=409,detail="acl_version_conflict")
    connection.execute("SELECT id FROM records WHERE aggregation_id=%s AND inherit_acl_from_parent ORDER BY id FOR UPDATE",(aggregation_id,)).fetchall()
    _replace(connection,"child_record",aggregation_id,payload.grants); _assert_continuity(connection,aggregation["security_level_id"])
    connection.execute("UPDATE aggregations SET child_record_acl_version=child_record_acl_version+1,version=version+1 WHERE id=%s",(aggregation_id,))
    connection.execute("SELECT append_domain_event('aggregation',%s,'DEFAULT_CHILD_RECORD_ACL_REPLACED',%s::jsonb,%s)",(aggregation_id,json.dumps({"affected_record_count":child_record_permissions(aggregation_id,connection)["affected_record_count"]}),payload.reason))
    return child_record_permissions(aggregation_id,connection)


@router.post("/aggregations/{aggregation_id}/default-child-record-permissions/preview", response_model=AclChangePreviewRead, dependencies=[Depends(require_authorization_admin)])
def preview_child_record_permissions(aggregation_id:int,payload:ChildRecordAclReplace,connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"aggregation",aggregation_id,"aggregation.acl.manage","aggregation.acl.manage",lock=False)
    aggregation=_resource(connection,"aggregations",aggregation_id)
    if aggregation["child_record_acl_version"]!=payload.version: raise HTTPException(status_code=409,detail="acl_version_conflict")
    proposed=_validate_grants(connection,payload.grants,"record")
    return {**_preview_delta(connection,_grant_rows(connection,"child_record",aggregation_id),proposed,aggregation["owning_org_unit_id"]),
            "affected_record_count":child_record_permissions(aggregation_id,connection)["affected_record_count"],"version":payload.version}


@router.get("/records/{record_id}/permissions", response_model=ResourceAclRead)
def record_permissions(record_id:int,connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"record",record_id,"record.acl.manage","record.acl.manage",lock=False)
    return _record_permissions(record_id, connection)


def _record_permissions(record_id: int, connection: Connection):
    record=_resource(connection,"records",record_id); source,source_id,effective=_effective_record(connection,record_id)
    return {"inherit_acl_from_parent":record["inherit_acl_from_parent"],"effective_acl":_group(effective),"effective_acl_source":source,
            "effective_acl_source_id":source_id,"override_acl":_group(_grant_rows(connection,"record",record_id)),
            "override_acl_is_dormant":record["inherit_acl_from_parent"],"resource_acl_version":record["resource_acl_version"]}


@router.put("/records/{record_id}/permissions", response_model=ResourceAclRead)
def replace_record_permissions(record_id:int,payload:AclReplace,connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"record",record_id,"record.acl.manage","record.acl.manage")
    record=_resource(connection,"records",record_id)
    if record["resource_acl_version"]!=payload.version: raise HTTPException(status_code=409,detail="acl_version_conflict")
    inherit=record["inherit_acl_from_parent"] if payload.inherit_acl_from_parent is None else payload.inherit_acl_from_parent
    grants=payload.grants
    if payload.initialize_override_from_inherited:
        grants=[AclPrincipalGrant(**{k:v for k,v in item.items() if k in {"principal_type","role_id","permission_codes"}}) for item in _group(_effective_record(connection,record_id)[2])]
    _replace(connection,"record",record_id,grants); _assert_continuity(connection,record["security_level_id"])
    connection.execute("UPDATE records SET inherit_acl_from_parent=%s,resource_acl_version=resource_acl_version+1,version=version+1 WHERE id=%s",(inherit,record_id))
    connection.execute("SELECT append_domain_event('record',%s,'ACL_REPLACED',%s::jsonb,%s)",(record_id,json.dumps({"inherit_acl_from_parent":inherit}),payload.reason))
    return _record_permissions(record_id,connection)


@router.get("/aggregations/{aggregation_id}/acl-move-preview")
def aggregation_acl_move_preview(aggregation_id:int,destination_aggregation_id:int,keep_current_access_as_override:bool=False,connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"aggregation",aggregation_id,"aggregation.move","aggregation.move",lock=False)
    require_resource_operation(connection,"aggregation",destination_aggregation_id,"aggregation.move","aggregation.receive_child",lock=False)
    aggregation=_resource(connection,"aggregations",aggregation_id); destination=_resource(connection,"aggregations",destination_aggregation_id)
    if aggregation["medium"] != destination["medium"]:
        raise HTTPException(status_code=422,detail={"code":"aggregation_medium_mismatch","message":"This aggregation and all its descendants must be compatible with the destination medium.","source_medium":aggregation["medium"],"destination_medium":destination["medium"]})
    current=_effective_aggregation(connection,aggregation_id)[2]
    if not aggregation["inherit_acl_from_parent"] or keep_current_access_as_override: proposed=current
    elif destination["default_child_aggregation_acl_mode"]=="custom": proposed=_grant_rows(connection,"child_aggregation",destination_aggregation_id)
    else: proposed=_effective_aggregation(connection,destination_aggregation_id)[2]
    old=_permission_set(current); new=_permission_set(proposed)
    return {"keep_current_access_as_override":keep_current_access_as_override,"added_count":len(new-old),"removed_count":len(old-new),
            "affected_subtree":_descendant_impact(connection,aggregation_id),"resource_version":aggregation["version"],
            "destination_child_acl_version":destination["child_aggregation_acl_version"],
            "contextual_access_may_change":aggregation["owning_org_unit_id"]!=destination["owning_org_unit_id"],
            "ownership_changes":aggregation["owning_org_unit_id"]!=destination["owning_org_unit_id"],
            "source_owning_org_unit_id":aggregation["owning_org_unit_id"],
            "destination_owning_org_unit_id":destination["owning_org_unit_id"]}


@router.post("/aggregations/{aggregation_id}/acl-move")
def move_aggregation_with_acl(aggregation_id:int,payload:AclMoveRequest,connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"aggregation",aggregation_id,"aggregation.move","aggregation.move")
    require_resource_operation(connection,"aggregation",payload.destination_aggregation_id,"aggregation.move","aggregation.receive_child")
    aggregation=_resource(connection,"aggregations",aggregation_id); destination=_resource(connection,"aggregations",payload.destination_aggregation_id)
    if aggregation["medium"] != destination["medium"]:
        raise HTTPException(status_code=422,detail={"code":"aggregation_medium_mismatch","message":"This aggregation and all its descendants must be compatible with the destination medium.","source_medium":aggregation["medium"],"destination_medium":destination["medium"]})
    ownership_changes=aggregation["owning_org_unit_id"]!=destination["owning_org_unit_id"]
    if ownership_changes and not payload.confirm_ownership_change:
        raise HTTPException(status_code=422,detail={"code":"ownership_change_requires_confirmation","message":"Confirm the organizational ownership change before moving this aggregation."})
    if ownership_changes:
        connection.execute("SELECT set_config('app.ownership_move_confirmed','true',true),set_config('app.change_reason',%s,true)",(payload.reason,))
    if aggregation["version"]!=payload.resource_version: raise HTTPException(status_code=409,detail="resource_version_conflict")
    if aggregation["inherit_acl_from_parent"] and payload.keep_current_access_as_override:
        _replace(connection,"aggregation",aggregation_id,_rows_as_inputs(_effective_aggregation(connection,aggregation_id)[2]))
        inherit=False
    else: inherit=aggregation["inherit_acl_from_parent"]
    _assert_continuity(connection,aggregation["security_level_id"])
    old_hold_ids=[row["hold_id"] for row in connection.execute("SELECT hold_id FROM effective_holds_for_aggregation(%s) ORDER BY hold_id",(aggregation_id,)).fetchall()]
    updated=connection.execute("UPDATE aggregations SET parent_aggregation_id=%s,inherit_acl_from_parent=%s,resource_acl_version=resource_acl_version+1 WHERE id=%s RETURNING *",(payload.destination_aggregation_id,inherit,aggregation_id)).fetchone()
    new_hold_ids=[row["hold_id"] for row in connection.execute("SELECT hold_id FROM effective_holds_for_aggregation(%s) ORDER BY hold_id",(aggregation_id,)).fetchall()]
    connection.execute("SELECT append_domain_event('aggregation',%s,'MOVED_WITH_ACL_POLICY',%s::jsonb,%s)",(aggregation_id,json.dumps({"destination_aggregation_id":payload.destination_aggregation_id,"keep_current_access_as_override":payload.keep_current_access_as_override,"ownership_changed":ownership_changes,"old_owning_org_unit_id":aggregation["owning_org_unit_id"],"new_owning_org_unit_id":destination["owning_org_unit_id"]}),payload.reason))
    if old_hold_ids or new_hold_ids:
        connection.execute("SELECT append_domain_event('aggregation',%s,'HELD_RESOURCE_MOVED',%s::jsonb,%s)",(aggregation_id,json.dumps({"old_parent_aggregation_id":aggregation["parent_aggregation_id"],"new_parent_aggregation_id":payload.destination_aggregation_id,"old_effective_hold_ids":old_hold_ids,"new_effective_hold_ids":new_hold_ids}),payload.reason))
    return updated


@router.get("/records/{record_id}/acl-move-preview")
def record_acl_move_preview(record_id:int,destination_aggregation_id:int,keep_current_access_as_override:bool=False,connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"record",record_id,"record.move","record.move",lock=False)
    require_resource_operation(connection,"aggregation",destination_aggregation_id,"record.move","aggregation.receive_record",lock=False)
    record=_resource(connection,"records",record_id); destination=_resource(connection,"aggregations",destination_aggregation_id)
    if destination["medium"] != "mixed" and record["medium"] != destination["medium"]:
        raise HTTPException(status_code=422,detail={"code":"record_medium_not_allowed_by_parent","message":f"A {destination['medium']} aggregation can only contain {destination['medium']} records.","record_medium":record["medium"],"destination_medium":destination["medium"]})
    current=_effective_record(connection,record_id)[2]
    proposed=current if not record["inherit_acl_from_parent"] or keep_current_access_as_override else _grant_rows(connection,"child_record",destination_aggregation_id)
    old=_permission_set(current); new=_permission_set(proposed)
    return {"keep_current_access_as_override":keep_current_access_as_override,"added_count":len(new-old),"removed_count":len(old-new),"resource_version":record["version"],
            "contextual_access_may_change":record["owning_org_unit_id"]!=destination["owning_org_unit_id"],
            "ownership_changes":record["owning_org_unit_id"]!=destination["owning_org_unit_id"],
            "source_owning_org_unit_id":record["owning_org_unit_id"],
            "destination_owning_org_unit_id":destination["owning_org_unit_id"]}


@router.post("/records/{record_id}/acl-move")
def move_record_with_acl(record_id:int,payload:AclMoveRequest,connection:Connection=Depends(get_connection,scope="function")):
    require_resource_operation(connection,"record",record_id,"record.move","record.move")
    require_resource_operation(connection,"aggregation",payload.destination_aggregation_id,"record.move","aggregation.receive_record")
    record=_resource(connection,"records",record_id); destination=_resource(connection,"aggregations",payload.destination_aggregation_id)
    if destination["medium"] != "mixed" and record["medium"] != destination["medium"]:
        raise HTTPException(status_code=422,detail={"code":"record_medium_not_allowed_by_parent","message":f"A {destination['medium']} aggregation can only contain {destination['medium']} records.","record_medium":record["medium"],"destination_medium":destination["medium"]})
    ownership_changes=record["owning_org_unit_id"]!=destination["owning_org_unit_id"]
    if ownership_changes and not payload.confirm_ownership_change:
        raise HTTPException(status_code=422,detail={"code":"ownership_change_requires_confirmation","message":"Confirm the organizational ownership change before moving this record."})
    if ownership_changes:
        connection.execute("SELECT set_config('app.ownership_move_confirmed','true',true),set_config('app.change_reason',%s,true)",(payload.reason,))
    if record["version"]!=payload.resource_version: raise HTTPException(status_code=409,detail="resource_version_conflict")
    if record["inherit_acl_from_parent"] and payload.keep_current_access_as_override:
        _replace(connection,"record",record_id,_rows_as_inputs(_effective_record(connection,record_id)[2])); inherit=False
    else: inherit=record["inherit_acl_from_parent"]
    _assert_continuity(connection,record["security_level_id"])
    old_hold_ids=[row["hold_id"] for row in connection.execute("SELECT hold_id FROM effective_holds_for_record(%s) ORDER BY hold_id",(record_id,)).fetchall()]
    updated=connection.execute("UPDATE records SET aggregation_id=%s,inherit_acl_from_parent=%s,resource_acl_version=resource_acl_version+1 WHERE id=%s RETURNING *",(payload.destination_aggregation_id,inherit,record_id)).fetchone()
    new_hold_ids=[row["hold_id"] for row in connection.execute("SELECT hold_id FROM effective_holds_for_record(%s) ORDER BY hold_id",(record_id,)).fetchall()]
    connection.execute("SELECT append_domain_event('record',%s,'MOVED_WITH_ACL_POLICY',%s::jsonb,%s)",(record_id,json.dumps({"destination_aggregation_id":payload.destination_aggregation_id,"keep_current_access_as_override":payload.keep_current_access_as_override,"ownership_changed":ownership_changes,"old_owning_org_unit_id":record["owning_org_unit_id"],"new_owning_org_unit_id":destination["owning_org_unit_id"]}),payload.reason))
    if old_hold_ids or new_hold_ids:
        connection.execute("SELECT append_domain_event('record',%s,'HELD_RESOURCE_MOVED',%s::jsonb,%s)",(record_id,json.dumps({"old_aggregation_id":record["aggregation_id"],"new_aggregation_id":payload.destination_aggregation_id,"old_effective_hold_ids":old_hold_ids,"new_effective_hold_ids":new_hold_ids}),payload.reason))
    return updated


def _require_ownership_correction(connection: Connection, root: dict[str, Any]) -> None:
    require_global(connection, "organization.ownership.correct")
    if not governance_role_snapshot(connection, [root["security_level_id"]]):
        raise HTTPException(status_code=403, detail={"code": "governance_correction_required"})
    if root["parent_aggregation_id"] is not None:
        raise HTTPException(status_code=422, detail={
            "code": "root_ownership_correction_only",
            "message": "Move a child aggregation to change its owning organizational unit.",
        })


def _ownership_correction_preview(
    connection: Connection, aggregation_id: int, destination_role_id: int,
) -> dict[str, Any]:
    root = _resource(connection, "aggregations", aggregation_id)
    _require_ownership_correction(connection, root)
    role = connection.execute(
        """SELECT role.id AS role_id,role.code AS role_code,role.name AS role_name,
                  unit.id AS org_unit_id,unit.code AS org_unit_code,unit.name AS org_unit_name
             FROM roles role JOIN org_units unit ON unit.id=role.org_unit_id
            WHERE role.id=%s AND role_effectively_active(role.id)""",
        (destination_role_id,),
    ).fetchone()
    if role is None:
        raise HTTPException(status_code=422, detail="destination role must be active")
    if role["org_unit_id"] == root["owning_org_unit_id"]:
        raise HTTPException(status_code=422, detail="destination role belongs to the current owner")
    counts = connection.execute(
        """WITH RECURSIVE subtree(id) AS (
             SELECT %s::bigint UNION ALL SELECT child.id FROM subtree parent
             JOIN aggregations child ON child.parent_aggregation_id=parent.id)
           SELECT count(*)::int AS aggregation_count,
                  (SELECT count(*)::int FROM records WHERE aggregation_id IN (SELECT id FROM subtree)) AS record_count
             FROM subtree""", (aggregation_id,),
    ).fetchone()
    creator = connection.execute(
        """SELECT NULLIF(metadata->>'creator_acl_role_id','')::bigint AS role_id
             FROM event_history WHERE entity_type='aggregation' AND entity_id=%s
              AND operation='CREATE' ORDER BY id LIMIT 1""", (aggregation_id,),
    ).fetchone()
    creator_role_id = creator["role_id"] if creator else None
    grant_count = 0
    if creator_role_id is not None:
        grant_count = connection.execute(
            """WITH RECURSIVE subtree(id) AS (
                 SELECT %s::bigint UNION ALL SELECT child.id FROM subtree parent
                 JOIN aggregations child ON child.parent_aggregation_id=parent.id),
               affected AS (
                 SELECT id FROM aggregation_acl_grants WHERE aggregation_id IN (SELECT id FROM subtree) AND role_id=%s
                 UNION ALL SELECT id FROM aggregation_child_aggregation_acl_defaults WHERE aggregation_id IN (SELECT id FROM subtree) AND role_id=%s
                 UNION ALL SELECT id FROM aggregation_child_record_acl_defaults WHERE aggregation_id IN (SELECT id FROM subtree) AND role_id=%s
                 UNION ALL SELECT grant_row.id FROM record_acl_grants grant_row JOIN records record ON record.id=grant_row.record_id
                   WHERE record.aggregation_id IN (SELECT id FROM subtree) AND grant_row.role_id=%s)
               SELECT count(*)::int AS count FROM affected""",
            (aggregation_id, creator_role_id, creator_role_id, creator_role_id, creator_role_id),
        ).fetchone()["count"]
    return {
        "root_aggregation_id": aggregation_id,
        "source_owning_org_unit_id": root["owning_org_unit_id"],
        "destination_owning_org_unit_id": role["org_unit_id"],
        "destination_role_id": role["role_id"], "destination_role_code": role["role_code"],
        "destination_role_name": role["role_name"],
        "affected_aggregation_count": counts["aggregation_count"],
        "affected_record_count": counts["record_count"],
        "creator_role_id": creator_role_id, "creator_role_grant_count": grant_count,
    }


@router.get("/ownership-correction-options", response_model=list[CreationRoleOption])
def ownership_correction_options(connection: Connection = Depends(get_connection, scope="function")):
    require_global(connection, "organization.ownership.correct")
    if not governance_role_snapshot(connection, [connection.execute("SELECT lowest_security_level_id() AS id").fetchone()["id"]]):
        raise HTTPException(status_code=403, detail={"code": "governance_correction_required"})
    rows = connection.execute(
        """SELECT role.id AS role_id,role.code AS role_code,role.name AS role_name,
                  unit.id AS org_unit_id,unit.code AS org_unit_code,unit.name AS org_unit_name
             FROM roles role JOIN org_units unit ON unit.id=role.org_unit_id
            WHERE role_effectively_active(role.id)
            ORDER BY unit.name COLLATE "C",role.name COLLATE "C",role.id"""
    ).fetchall()
    return [{**row,"label":f"{row['org_unit_name']} — {row['role_name']}"} for row in rows]


@router.get("/aggregations/{aggregation_id}/ownership-correction-preview", response_model=OwnershipCorrectionPreviewRead)
def ownership_correction_preview(aggregation_id:int,destination_role_id:int,connection:Connection=Depends(get_connection,scope="function")):
    return _ownership_correction_preview(connection,aggregation_id,destination_role_id)


@router.post("/aggregations/{aggregation_id}/correct-ownership")
def correct_root_ownership(aggregation_id:int,payload:OwnershipCorrectionRequest,connection:Connection=Depends(get_connection,scope="function")):
    preview=_ownership_correction_preview(connection,aggregation_id,payload.destination_role_id)
    old_role_id=preview["creator_role_id"]
    if old_role_id is not None and old_role_id != payload.destination_role_id:
        scopes=(
            ("aggregation_acl_grants","aggregation_id","SELECT id FROM subtree"),
            ("aggregation_child_aggregation_acl_defaults","aggregation_id","SELECT id FROM subtree"),
            ("aggregation_child_record_acl_defaults","aggregation_id","SELECT id FROM subtree"),
        )
        for table,owner_column,owners in scopes:
            connection.execute(f"""WITH RECURSIVE subtree(id) AS (
                SELECT %s::bigint UNION ALL SELECT child.id FROM subtree parent JOIN aggregations child ON child.parent_aggregation_id=parent.id)
                INSERT INTO {table}({owner_column},principal_type,role_id,permission_id)
                SELECT grant_row.{owner_column},'role',%s,grant_row.permission_id FROM {table} grant_row
                WHERE grant_row.{owner_column} IN ({owners}) AND grant_row.principal_type='role' AND grant_row.role_id=%s
                ON CONFLICT DO NOTHING""",(aggregation_id,payload.destination_role_id,old_role_id))
            connection.execute(f"""WITH RECURSIVE subtree(id) AS (
                SELECT %s::bigint UNION ALL SELECT child.id FROM subtree parent JOIN aggregations child ON child.parent_aggregation_id=parent.id)
                DELETE FROM {table} WHERE {owner_column} IN ({owners}) AND principal_type='role' AND role_id=%s""",(aggregation_id,old_role_id))
        connection.execute("""WITH RECURSIVE subtree(id) AS (
            SELECT %s::bigint UNION ALL SELECT child.id FROM subtree parent JOIN aggregations child ON child.parent_aggregation_id=parent.id)
            INSERT INTO record_acl_grants(record_id,principal_type,role_id,permission_id)
            SELECT grant_row.record_id,'role',%s,grant_row.permission_id FROM record_acl_grants grant_row
            JOIN records record ON record.id=grant_row.record_id WHERE record.aggregation_id IN (SELECT id FROM subtree)
              AND grant_row.principal_type='role' AND grant_row.role_id=%s ON CONFLICT DO NOTHING""",(aggregation_id,payload.destination_role_id,old_role_id))
        connection.execute("""WITH RECURSIVE subtree(id) AS (
            SELECT %s::bigint UNION ALL SELECT child.id FROM subtree parent JOIN aggregations child ON child.parent_aggregation_id=parent.id)
            DELETE FROM record_acl_grants grant_row USING records record
            WHERE record.id=grant_row.record_id AND record.aggregation_id IN (SELECT id FROM subtree)
              AND grant_row.principal_type='role' AND grant_row.role_id=%s""",(aggregation_id,old_role_id))
    connection.execute("SELECT set_config('app.ownership_correction_authorized','authorized',true),set_config('app.change_reason',%s,true)",(payload.reason,))
    updated=connection.execute("UPDATE aggregations SET owning_org_unit_id=%s WHERE id=%s RETURNING *",(preview["destination_owning_org_unit_id"],aggregation_id)).fetchone()
    connection.execute("SELECT append_domain_event('aggregation',%s,'OWNERSHIP_CORRECTED',%s::jsonb,%s)",(aggregation_id,json.dumps(preview),payload.reason))
    return updated
