"""Transactional permanent-deletion analysis for identity and organization data."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException, Request
from psycopg import Connection

from .audit_context import decode_change_reason
from .authorization_admin import (
    CUSTODY_PRIVILEGE_CODES,
    _effective_people_for_privilege,
    _universal_custodian_count,
)
from .continuity_lock import acquire_continuity_lock


EntityKind = Literal["user", "role", "org_unit"]


def _block(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details}


def _counts(connection: Connection, queries: dict[str, tuple[str, tuple[Any, ...]]]) -> dict[str, int]:
    return {
        name: int(connection.execute(query, params).fetchone()["count"])
        for name, (query, params) in queries.items()
    }


def _target(connection: Connection, kind: EntityKind, entity_id: int, *, lock: bool) -> dict[str, Any]:
    table = {"user": "users", "role": "roles", "org_unit": "org_units"}[kind]
    suffix = " FOR UPDATE" if lock else ""
    row = connection.execute(f"SELECT * FROM {table} WHERE id=%s{suffix}", (entity_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{kind.replace('_', ' ')} not found")
    return row


def _protected_count(connection: Connection) -> int:
    return int(connection.execute(
        "SELECT (SELECT count(*) FROM aggregations)+(SELECT count(*) FROM records) AS count"
    ).fetchone()["count"])


def analyze_deletion(
    connection: Connection, kind: EntityKind, entity_id: int,
    *, actor_user_id: int | None, lock: bool = False,
) -> dict[str, Any]:
    if lock:
        acquire_continuity_lock(connection)
    entity = _target(connection, kind, entity_id, lock=lock)
    blockers: list[dict[str, Any]] = []
    dependencies: dict[str, Any] = {}
    cascades: dict[str, int] = {}

    if kind == "user":
        if actor_user_id == entity_id:
            blockers.append(_block("self_deletion", "You cannot permanently delete your own account."))
        counts = _counts(connection, {
            "role_assignments": ("SELECT count(*) FROM user_role_assignments WHERE user_id=%s", (entity_id,)),
            "record_drafts": ("SELECT count(*) FROM record_drafts WHERE owner_user_id=%s", (entity_id,)),
            "credentials": ("SELECT count(*) FROM user_credentials WHERE user_id=%s", (entity_id,)),
            "login_sessions": ("SELECT count(*) FROM login_sessions WHERE user_id=%s", (entity_id,)),
            "favourite_aggregations": ("SELECT count(*) FROM user_favourite_aggregations WHERE user_id=%s", (entity_id,)),
            "favourite_records": ("SELECT count(*) FROM user_favourite_records WHERE user_id=%s", (entity_id,)),
            "classification_preferences": ("SELECT count(*) FROM user_classification_selections WHERE user_id=%s", (entity_id,)),
        })
        cascades.update(counts)

        admin_before = _effective_people_for_privilege(connection, "authorization.administer")
        custodian_before = _universal_custodian_count(connection)
        # Simulation is performed without changing live state.
        effective_admin_after = connection.execute(
            """SELECT count(DISTINCT u.id) AS count FROM users u
               JOIN user_role_assignments a ON a.user_id=u.id
               JOIN roles r ON r.id=a.role_id
               JOIN profile_privileges pp ON pp.profile_id=r.profile_id
               JOIN privileges p ON p.id=pp.privilege_id
               WHERE u.id<>%s AND p.code='authorization.administer'
                 AND u.account_type='person' AND u.status='active'
                 AND a.valid_from<=CURRENT_TIMESTAMP
                 AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
                 AND role_effectively_active(r.id)""", (entity_id,),
        ).fetchone()["count"]
        custodian_after = connection.execute(
            """SELECT count(DISTINCT u.id) AS count FROM users u
               JOIN user_role_assignments a ON a.user_id=u.id
               JOIN roles r ON r.id=a.role_id
               JOIN security_levels sl ON sl.id=r.security_level_id
               WHERE u.id<>%s AND r.is_information_governance
                 AND sl.level_number=(SELECT max(level_number) FROM security_levels)
                 AND u.account_type='person' AND u.status='active'
                 AND a.valid_from<=CURRENT_TIMESTAMP
                 AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
                 AND role_effectively_active(r.id)
                 AND (SELECT count(DISTINCT p.code) FROM profile_privileges pp
                      JOIN privileges p ON p.id=pp.privilege_id
                      WHERE pp.profile_id=r.profile_id AND p.code=ANY(%s))=%s""",
            (entity_id, list(CUSTODY_PRIVILEGE_CODES), len(CUSTODY_PRIVILEGE_CODES)),
        ).fetchone()["count"]
        dependencies.update({
            "authorization_administrators_before": admin_before,
            "authorization_administrators_after": effective_admin_after,
            "universal_human_custodians_before": custodian_before,
            "universal_human_custodians_after": custodian_after,
            "protected_resources": _protected_count(connection),
        })
        if admin_before and not effective_admin_after:
            blockers.append(_block("last_system_administrator", "Deletion would remove the last effective authorization administrator."))
        if dependencies["protected_resources"] and custodian_before and not custodian_after:
            blockers.append(_block(
                "content_access_continuity",
                "Deletion would leave protected resources without an effective highest-clearance human governance custodian.",
                affected_resources=dependencies["protected_resources"],
            ))

    elif kind == "role":
        if entity["code"].casefold() == "system-administrator":
            blockers.append(_block("reserved_role", "The reserved system-administrator role cannot be deleted."))
        counts = _counts(connection, {
            "subordinate_roles": ("SELECT count(*) FROM roles WHERE supervisor_role_id=%s", (entity_id,)),
            "unit_designations": ("SELECT count(*) FROM org_units WHERE managing_role_id=%s OR file_administrator_role_id=%s", (entity_id, entity_id)),
            "user_assignments": ("SELECT count(*) FROM user_role_assignments WHERE role_id=%s", (entity_id,)),
            "aggregation_acl_grants": ("SELECT count(*) FROM aggregation_acl_grants WHERE role_id=%s", (entity_id,)),
            "record_acl_grants": ("SELECT count(*) FROM record_acl_grants WHERE role_id=%s", (entity_id,)),
            "default_child_aggregation_acl_grants": ("SELECT count(*) FROM aggregation_child_aggregation_acl_defaults WHERE role_id=%s", (entity_id,)),
            "default_child_record_acl_grants": ("SELECT count(*) FROM aggregation_child_record_acl_defaults WHERE role_id=%s", (entity_id,)),
        })
        dependencies.update(counts)
        dependencies["profile_id"] = entity["profile_id"]
        cascades["user_assignments"] = counts["user_assignments"]
        if counts["subordinate_roles"]:
            blockers.append(_block("supervises_roles", "Assign or remove every subordinate role's supervisor before deletion.", count=counts["subordinate_roles"]))
        if counts["unit_designations"]:
            blockers.append(_block("role_designated_by_unit", "Clear or replace organizational-unit role designations before deletion.", count=counts["unit_designations"]))
        acl_count = sum(counts[name] for name in counts if "acl_grants" in name)
        if acl_count:
            blockers.append(_block("role_has_acl_grants", "Transfer or explicitly remove every live and default-child ACL grant before deletion.", count=acl_count, **{name: value for name, value in counts.items() if "acl_grants" in name}))

        # Role removal is simulated through all of its assignments.
        protected = _protected_count(connection)
        before_admins = _effective_people_for_privilege(connection, "authorization.administer")
        before_custodians = _universal_custodian_count(connection)
        after_admins = connection.execute(
            """SELECT count(DISTINCT u.id) AS count FROM users u JOIN user_role_assignments a ON a.user_id=u.id
               JOIN roles r ON r.id=a.role_id JOIN profile_privileges pp ON pp.profile_id=r.profile_id
               JOIN privileges p ON p.id=pp.privilege_id WHERE r.id<>%s AND p.code='authorization.administer'
               AND u.account_type='person' AND u.status='active' AND a.valid_from<=CURRENT_TIMESTAMP
               AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(r.id)""", (entity_id,),
        ).fetchone()["count"]
        after_custodians = connection.execute(
            """SELECT count(DISTINCT u.id) AS count FROM users u JOIN user_role_assignments a ON a.user_id=u.id
               JOIN roles r ON r.id=a.role_id JOIN security_levels sl ON sl.id=r.security_level_id
               WHERE r.id<>%s AND r.is_information_governance AND sl.level_number=(SELECT max(level_number) FROM security_levels)
               AND u.account_type='person' AND u.status='active' AND a.valid_from<=CURRENT_TIMESTAMP
               AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(r.id)
               AND (SELECT count(DISTINCT p.code) FROM profile_privileges pp JOIN privileges p ON p.id=pp.privilege_id
                    WHERE pp.profile_id=r.profile_id AND p.code=ANY(%s))=%s""",
            (entity_id, list(CUSTODY_PRIVILEGE_CODES), len(CUSTODY_PRIVILEGE_CODES)),
        ).fetchone()["count"]
        dependencies.update({"authorization_administrators_after": after_admins, "universal_human_custodians_after": after_custodians, "protected_resources": protected})
        if before_admins and not after_admins:
            blockers.append(_block("last_system_administrator", "Deletion would remove the last effective authorization administrator."))
        if protected and before_custodians and not after_custodians:
            blockers.append(_block("content_access_continuity", "Deletion would remove the last effective highest-clearance human governance custodian.", affected_resources=protected))

    else:
        if entity["code"].casefold() == "system":
            blockers.append(_block("reserved_org_unit", "The reserved SYSTEM organizational unit cannot be deleted."))
        counts = _counts(connection, {
            "child_org_units": ("SELECT count(*) FROM org_units WHERE parent_org_unit_id=%s", (entity_id,)),
            "roles": ("SELECT count(*) FROM roles WHERE org_unit_id=%s", (entity_id,)),
        })
        dependencies.update(counts)
        if counts["child_org_units"]:
            blockers.append(_block("org_unit_has_children", "Move or delete child organizational units first.", count=counts["child_org_units"]))
        if counts["roles"]:
            blockers.append(_block("org_unit_has_roles", "Move or explicitly delete roles owned by this organizational unit first.", count=counts["roles"]))

    return {
        "entity_type": kind,
        "entity_id": entity_id,
        "entity_version": entity["version"],
        "allowed": not blockers,
        "blockers": blockers,
        "dependencies": dependencies,
        "cascades": cascades,
    }


def permanently_delete(
    connection: Connection, request: Request, kind: EntityKind, entity_id: int, version: int,
) -> dict[str, Any]:
    reason = decode_change_reason(request.headers.get("X-Change-Reason", "")).strip()
    if not reason:
        raise HTTPException(status_code=422, detail="X-Change-Reason is required")
    principal = getattr(request.state, "principal", None)
    actor_user_id = principal.user_id if principal else None
    report = analyze_deletion(connection, kind, entity_id, actor_user_id=actor_user_id, lock=True)
    if report["entity_version"] != version:
        raise HTTPException(status_code=412, detail={"message": "entity has changed", "current_version": report["entity_version"]})
    if report["blockers"]:
        raise HTTPException(status_code=409, detail={"code": "deletion_blocked", **report})

    table = {"user": "users", "role": "roles", "org_unit": "org_units"}[kind]
    if kind == "user":
        session_snapshots = list(connection.execute(
            """SELECT id AS session_id,client_ip::text AS client_ip,
                      left(user_agent,1000) AS user_agent,
                      date_created AS session_created_at,last_seen_at,expires_at,
                      absolute_expires_at,revoked_at
               FROM login_sessions WHERE user_id=%s ORDER BY id""", (entity_id,),
        ).fetchall())
        connection.execute(
            "SELECT append_domain_event('user',%s,'TRANSIENT_USER_DATA_REMOVED',%s::jsonb,%s)",
            (entity_id, __import__("json").dumps({
                "revocation_reason": "user_deleted",
                "revocation_scope": "all",
                "sessions_revoked": len(session_snapshots),
                "sessions": session_snapshots,
                "cascade_counts": report["cascades"],
            }, default=str), reason),
        )
    deleted = connection.execute(
        f"DELETE FROM {table} WHERE id=%s AND version=%s RETURNING id", (entity_id, version),
    ).fetchone()
    if deleted is None:  # defensive; table locks make this unlikely
        raise HTTPException(status_code=412, detail="entity has changed")
    return report
