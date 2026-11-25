from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from psycopg import Connection
from psycopg.types.json import Jsonb


from .continuity_lock import acquire_continuity_shared_lock

ResourceType = Literal["aggregation", "record"]


def governance_role_snapshot(
    connection: Connection, security_level_ids: list[int], *, user_id: int | None = None,
) -> list[dict[str, Any]]:
    principal = user_id if user_id is not None else connection.execute(
        "SELECT current_user_id() AS id"
    ).fetchone()["id"]
    if principal is None:
        return []
    return list(connection.execute(
        """SELECT DISTINCT role.id,role.code,role.name,role.profile_id,
                  level.id AS security_level_id,level.code AS security_level_code,
                  level.level_number
           FROM user_role_assignments assignment JOIN roles role ON role.id=assignment.role_id
           JOIN security_levels level ON level.id=role.security_level_id
           JOIN security_levels required ON required.id=ANY(%s)
           WHERE assignment.user_id=%s AND role.is_information_governance
             AND assignment.valid_from<=CURRENT_TIMESTAMP
             AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
             AND role_effectively_active(role.id) AND level.level_number>=required.level_number
           ORDER BY role.id""", (security_level_ids, principal),
    ).fetchall())


def _audit_governance_bypass(
    connection: Connection, resource_type: ResourceType, resource_id: int,
    privilege: str, permission: str, security_level_id: int, *, type_bypass: bool=False,
) -> None:
    connection.execute(
        "SELECT append_domain_event(%s,%s,'INFORMATION_GOVERNANCE_BYPASS_USED',%s::jsonb)",
        (resource_type, resource_id, Jsonb({
            "authorization_basis": "information_governance",
            "resource_type_bypass": type_bypass,
            "required_privilege": privilege, "required_permission": permission,
            "qualifying_roles": governance_role_snapshot(connection, [security_level_id]),
        })),
    )


def audit_governance_view_if_used(
    connection: Connection, resource_type: ResourceType, resource: dict[str, Any],
) -> None:
    permission = f"{resource_type}.view"
    audit_resource_bypass(connection, resource_type, resource, permission, permission)


def audit_resource_bypass(connection, kind, resource, privilege, permission):
    fact = connection.execute(f"""SELECT user_has_{kind}_permission(current_user_id(),%s,%s) AS acl,
        user_has_type_grant(current_user_id(),%s,%s,type_operation_requires_use(%s)) AS type_grant""",
        (resource["id"],permission,kind,resource["type_id"],permission)).fetchone()
    if not (fact["acl"] and fact["type_grant"]):
        _audit_governance_bypass(connection,kind,resource["id"],privilege,permission,resource["security_level_id"],
                                type_bypass=not fact["type_grant"])


def require_type_use(connection, kind, resource, privilege, permission):
    """Additional Use check for a mutation whose existing ACL operation is View."""
    if resource["type_id"] is None:
        return
    access = connection.execute(
        """SELECT user_has_type_grant(current_user_id(),%s,%s,true) AS ordinary,
                  user_has_governance_clearance(current_user_id(),%s) AS governance""",
        (kind,resource["type_id"],resource["security_level_id"]),
    ).fetchone()
    if access["ordinary"]:
        return
    if not access["governance"]:
        raise HTTPException(403,detail={"code":"insufficient_type_access"})
    _audit_governance_bypass(connection,kind,resource["id"],privilege,permission,
                            resource["security_level_id"],type_bypass=True)


def require_global(connection: Connection, privilege: str) -> None:
    allowed = connection.execute(
        "SELECT user_has_global_privilege(current_user_id(),%s) AS allowed", (privilege,),
    ).fetchone()["allowed"]
    if not allowed:
        raise HTTPException(status_code=403, detail={"code": "insufficient_privilege"})


def require_clearance_for_level(connection: Connection, security_level_id: int) -> None:
    allowed = connection.execute(
        """SELECT EXISTS(
             SELECT 1 FROM user_role_assignments assignment
             JOIN roles role ON role.id=assignment.role_id
             JOIN security_levels role_level ON role_level.id=role.security_level_id
             JOIN security_levels required ON required.id=%s
             WHERE assignment.user_id=current_user_id()
               AND assignment.valid_from<=CURRENT_TIMESTAMP
               AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
               AND role_effectively_active(role.id)
               AND role_level.level_number>=required.level_number) AS allowed""",
        (security_level_id,),
    ).fetchone()["allowed"]
    if not allowed:
        raise HTTPException(status_code=403, detail={"code": "insufficient_clearance"})


def lock_visible_resource(
    connection: Connection, resource_type: ResourceType, resource_id: int,
) -> dict[str, Any]:
    table = "aggregations" if resource_type == "aggregation" else "records"
    predicate = (
        "current_user_can_view_aggregation(id)" if resource_type == "aggregation"
        else "current_user_can_view_record(id)"
    )
    row = connection.execute(
        f"SELECT * FROM {table} WHERE id=%s AND {predicate} FOR UPDATE", (resource_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{resource_type} not found")
    return row


def require_resource_operation(
    connection: Connection,
    resource_type: ResourceType,
    resource_id: int,
    privilege: str,
    permission: str,
    *,
    lock: bool = True,
) -> dict[str, Any]:
    if lock:
        acquire_continuity_shared_lock(connection)
    resource = (
        lock_visible_resource(connection, resource_type, resource_id)
        if lock else _visible_resource(connection, resource_type, resource_id)
    )
    require_global(connection, privilege)
    function = (
        "current_user_can_aggregation_operation" if resource_type == "aggregation"
        else "current_user_can_record_operation"
    )
    allowed = connection.execute(
        f"SELECT {function}(%s,%s,%s) AS allowed",
        (resource_id, privilege, permission),
    ).fetchone()["allowed"]
    if not allowed:
        raise HTTPException(
            status_code=403, detail={"code": "insufficient_resource_permission"},
        )
    audit_resource_bypass(connection,resource_type,resource,privilege,permission)
    return resource


def _visible_resource(
    connection: Connection, resource_type: ResourceType, resource_id: int,
) -> dict[str, Any]:
    table = "aggregations" if resource_type == "aggregation" else "records"
    predicate = (
        "current_user_can_view_aggregation(id)" if resource_type == "aggregation"
        else "current_user_can_view_record(id)"
    )
    row = connection.execute(
        f"SELECT * FROM {table} WHERE id=%s AND {predicate}", (resource_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{resource_type} not found")
    return row


def operation_allowed(
    connection: Connection, resource_type: ResourceType, resource_id: int,
    privilege: str, permission: str,
) -> bool:
    function = (
        "current_user_can_aggregation_operation" if resource_type == "aggregation"
        else "current_user_can_record_operation"
    )
    return bool(connection.execute(
        f"SELECT {function}(%s,%s,%s) AS allowed", (resource_id, privilege, permission),
    ).fetchone()["allowed"])


def require_component_operation(
    connection: Connection, component_id: int, privilege: str, permission: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    acquire_continuity_shared_lock(connection)
    component = connection.execute(
        """SELECT component.* FROM digital_components component
           WHERE component.id=%s
             AND current_user_can_list_record_components(component.record_id)
           FOR UPDATE""",
        (component_id,),
    ).fetchone()
    if component is None:
        raise HTTPException(status_code=404, detail="digital component not found")
    allowed = connection.execute(
        "SELECT current_user_can_record_component_operation(%s,%s,%s) AS allowed",
        (component["record_id"], privilege, permission),
    ).fetchone()["allowed"]
    if not allowed:
        raise HTTPException(
            status_code=403, detail={"code": "insufficient_resource_permission"},
        )
    record = lock_visible_resource(connection, "record", component["record_id"])
    audit_resource_bypass(connection,"record",record,privilege,permission)
    return component, record


def require_draft_owner(connection: Connection, draft_id: int) -> None:
    if not connection.execute(
        "SELECT current_user_owns_open_draft(%s) AS allowed", (draft_id,),
    ).fetchone()["allowed"]:
        raise HTTPException(status_code=404, detail="record draft not found")


def require_closed_placement_correction(
    connection: Connection, destination_aggregation_id: int,
    resource_security_level_id: int, ordinary_privilege: str,
) -> dict[str, Any]:
    destination = lock_visible_resource(
        connection, "aggregation", destination_aggregation_id,
    )
    require_global(connection, ordinary_privilege)
    require_global(connection, "closure.correct_record_placement")
    for level_id in {destination["security_level_id"], resource_security_level_id}:
        if not connection.execute(
            "SELECT user_has_governance_clearance(current_user_id(),%s) AS allowed",
            (level_id,),
        ).fetchone()["allowed"]:
            raise HTTPException(status_code=403, detail={"code": "governance_correction_required"})
    return destination


def require_destination_record_permission(
    connection: Connection, aggregation_id: int, security_level_id: int,
    privilege: str, permission: str,
) -> None:
    require_global(connection, privilege)
    require_clearance_for_level(connection, security_level_id)
    acl_allowed = connection.execute(
        "SELECT user_has_destination_record_permission(current_user_id(),%s,%s) AS allowed",
        (aggregation_id, permission),
    ).fetchone()["allowed"]
    governance = connection.execute(
        "SELECT user_has_governance_clearance(current_user_id(),%s) AS allowed",
        (security_level_id,),
    ).fetchone()["allowed"]
    if not (acl_allowed or governance):
        raise HTTPException(status_code=403, detail={"code": "insufficient_resource_permission"})
