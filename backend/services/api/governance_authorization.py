from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from .authorization_policy import (
    AuthorizationRequest, ResourceAcl, authorize, load_user_policy_context,
    policy_context_from_request, require_authorization_admin,
)
from .authorization_admin import CUSTODY_PRIVILEGE_CODES
from .database import get_connection
from .entity_localization import localized_projection, preferred_language
from .resource_acls import _effective_aggregation, _effective_record, _grant_rows
from .schemas import AccessExplanationRead, ExplainableUserRead, GovernanceCustodyRead


router = APIRouter(prefix="/api/v1/authorization", tags=["authorization explanations"])


def require_authorization_explain(request: Request):
    context = policy_context_from_request(request)
    if not any("authorization.explain" in role.privileges for role in context.effective_roles):
        raise HTTPException(status_code=403, detail={"code": "insufficient_privilege"})
    return context


class AccessExplanationRequest(BaseModel):
    resource_type: Literal["aggregation", "record"]
    resource_id: int
    operation: str
    user_id: int | None = None


OPERATION_POLICY = {
    "aggregation.view": ("aggregation.view", "aggregation.view"),
    "aggregation.modify_metadata": ("aggregation.modify", "aggregation.modify_metadata"),
    "aggregation.delete": ("aggregation.delete", "aggregation.delete"),
    "aggregation.close": ("aggregation.close", "aggregation.close"),
    "aggregation.reopen": ("aggregation.reopen", "aggregation.reopen"),
    "aggregation.move": ("aggregation.move", "aggregation.move"),
    "aggregation.reclassify": ("aggregation.reclassify", "aggregation.reclassify"),
    "aggregation.security_level.change": ("aggregation.security_level.change", "aggregation.security_level.change"),
    "aggregation.vital_status.change": ("aggregation.vital_status.change", "aggregation.vital_status.change"),
    "aggregation.location.change": ("aggregation.location.change", "aggregation.location.change"),
    "aggregation.review_date.change": ("aggregation.review_date.change", "aggregation.review_date.change"),
    "aggregation.acl.manage": ("aggregation.acl.manage", "aggregation.acl.manage"),
    "aggregation.add_child": ("aggregation.create_child", "aggregation.add_child"),
    "aggregation.add_record": ("record.create", "aggregation.add_record"),
    "record.view": ("record.view", "record.view"),
    "record.modify_metadata": ("record.modify", "record.modify_metadata"),
    "record.delete": ("record.delete", "record.delete"),
    "record.move": ("record.move", "record.move"),
    "record.security_level.change": ("record.security_level.change", "record.security_level.change"),
    "record.vital_status.change": ("record.vital_status.change", "record.vital_status.change"),
    "record.review_date.change": ("record.review_date.change", "record.review_date.change"),
    "record.acl.manage": ("record.acl.manage", "record.acl.manage"),
    "record.component.list": ("record.view", "record.component.list"),
    "record.component.view": ("record.component.view", "record.component.view"),
    "record.component.download": ("record.component.download", "record.component.download"),
    "record.component.add": ("record.component.add", "record.component.add"),
    "record.component.replace": ("record.component.replace", "record.component.replace"),
    "record.component.remove": ("record.component.remove", "record.component.remove"),
    "record.component.reorder": ("record.component.reorder", "record.component.reorder"),
}


def _resource_for_examiner(
    connection: Connection, resource_type: str, resource_id: int,
) -> dict:
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


def _acl(connection: Connection, resource_type: str, resource_id: int, subject_role_ids: list[int]) -> tuple[ResourceAcl, dict]:
    if resource_type == "aggregation":
        source, owner_id, rows = _effective_aggregation(connection, resource_id)
        resource_type_for_permission = "aggregation"
        resource = connection.execute(
            "SELECT inherit_acl_from_parent,owning_org_unit_id FROM aggregations WHERE id=%s", (resource_id,),
        ).fetchone()
        dormant = _grant_rows(connection, "aggregation", resource_id) if resource["inherit_acl_from_parent"] else []
    else:
        source, owner_id, rows = _effective_record(connection, resource_id)
        resource_type_for_permission = "record"
        resource = connection.execute(
            "SELECT inherit_acl_from_parent,owning_org_unit_id FROM records WHERE id=%s", (resource_id,),
        ).fetchone()
        dormant = _grant_rows(connection, "record", resource_id) if resource["inherit_acl_from_parent"] else []
    everyone = frozenset(
        row["permission_code"] for row in rows if row["principal_type"] == "everyone"
    )
    org_unit_members = frozenset(
        row["permission_code"]
        for row in rows if row["principal_type"] == "org_unit_members"
    )
    by_role: dict[int, set[str]] = {}
    contextual_matches = []
    resolved = {}
    for row in rows:
        if row["principal_type"] == "role":
            by_role.setdefault(row["role_id"], set()).add(row["permission_code"])
        elif row["principal_type"] in {"owning_and_higher_level_unit_managers", "effective_file_administrator"}:
            if row["principal_type"] not in resolved:
                resolved[row["principal_type"]] = connection.execute(
                    "SELECT * FROM contextual_acl_roles(%s,%s) WHERE role_id=ANY(%s::bigint[])",
                    (resource["owning_org_unit_id"], row["principal_type"], subject_role_ids),
                ).fetchall()
            for match in resolved[row["principal_type"]]:
                by_role.setdefault(match["role_id"], set()).add(row["permission_code"])
                contextual_matches.append({**match, "principal_type": row["principal_type"], "permission_code": row["permission_code"]})
    acl = ResourceAcl(
        everyone_permissions=everyone,
        org_unit_member_permissions=org_unit_members,
        role_permissions={key: frozenset(value) for key, value in by_role.items()},
        source=source,
    )
    detail = {
        "resource_type": resource_type_for_permission, "source": source,
        "source_resource_id": owner_id, "inherit_acl_from_parent": resource["inherit_acl_from_parent"],
        "effective_grants": rows, "dormant_override_grants": dormant,
        "contextual_matches": contextual_matches,
    }
    return acl, detail


def _serialize_context(context) -> dict:
    return {
        "user_id": context.user_id,
        "effective_clearance": context.effective_clearance,
        "effective_roles": [
            {**asdict(role), "privileges": sorted(role.privileges)}
            for role in context.effective_roles
        ],
        "excluded_roles": [asdict(role) for role in context.excluded_roles],
    }


def _integrity_gate(
    connection: Connection, resource_type: str, resource: dict, operation: str,
    subject_user_id: int | None, examiner_user_id: int | None,
) -> tuple[bool, str | None, list[dict]]:
    hold_rows = list(connection.execute(
        f"SELECT * FROM effective_holds_for_{resource_type}(%s) ORDER BY hold_id",
        (resource["id"],),
    ).fetchall())
    hold_effect = None
    if operation.endswith(".delete") and hold_rows:
        hold_effect = "deletion"
    elif operation in {"record.component.add", "record.component.remove", "record.component.replace", "record.component.reorder"} and hold_rows:
        hold_effect = operation.rsplit(".", 1)[-1].replace("add", "addition").replace("remove", "removal").replace("replace", "replacement").replace("reorder", "reordering")
    elif operation.endswith(("modify_metadata", ".close", ".reopen", ".reclassify", "vital_status.change", "review_date.change")) and any(row["preserve_resource_state"] for row in hold_rows):
        hold_effect = "metadata_change"
    elif operation.endswith(".move") and any(row["preserve_resource_state"] for row in hold_rows):
        hold_effect = "movement"
    elif operation.endswith(".move") and hold_rows and subject_user_id is not None:
        unmanaged = connection.execute(
            """SELECT EXISTS(SELECT 1 FROM unnest(%s::bigint[]) hold_id
                 WHERE NOT EXISTS(SELECT 1 FROM holds h WHERE h.id=hold_id AND h.owner_user_id=%s)
                   AND NOT EXISTS(SELECT 1 FROM hold_contributors c JOIN users u ON u.id=c.user_id
                     WHERE c.hold_id=hold_id AND c.user_id=%s AND u.date_deactivated IS NULL AND u.date_suspended IS NULL)) value""",
            ([row["hold_id"] for row in hold_rows], subject_user_id, subject_user_id),
        ).fetchone()["value"]
        if unmanaged:
            hold_effect = "movement_held_item_management"
    constraints = []
    if hold_effect:
        visible_ids = set()
        if examiner_user_id is not None:
            visible_ids = {row["id"] for row in connection.execute(
                """SELECT hold.id FROM holds hold WHERE hold.id=ANY(%s::bigint[]) AND
                    (user_has_global_privilege(%s,'holds.administer') OR EXISTS(
                       SELECT 1 FROM user_role_assignments ga JOIN roles gr ON gr.id=ga.role_id
                       WHERE ga.user_id=%s AND gr.is_information_governance
                         AND ga.valid_from<=CURRENT_TIMESTAMP AND (ga.valid_until IS NULL OR ga.valid_until>CURRENT_TIMESTAMP)
                         AND role_effectively_active(gr.id)) OR hold.owner_user_id=%s OR EXISTS(
                      SELECT 1 FROM hold_contributors c JOIN users u ON u.id=c.user_id
                      WHERE c.hold_id=hold.id AND c.user_id=%s AND u.date_deactivated IS NULL AND u.date_suspended IS NULL))""",
                ([row["hold_id"] for row in hold_rows], examiner_user_id, examiner_user_id,
                 examiner_user_id, examiner_user_id),
            ).fetchall()}
        detail = []
        for row in hold_rows:
            if row["hold_id"] in visible_ids:
                detail.append({"id": row["hold_id"], "code": row["code"], "name": row["name"],
                               "source": "both" if row["is_direct"] and row["is_inherited"] else ("direct" if row["is_direct"] else "inherited"),
                               "assigning_ancestor_id": row["nearest_assigned_aggregation_id"],
                               "preserve_resource_state": row["preserve_resource_state"]})
        constraints.append({"kind": "effective_hold", "effect": "movement" if hold_effect == "movement_held_item_management" else hold_effect,
                            "source": "both" if any(r["is_direct"] for r in hold_rows) and any(r["is_inherited"] for r in hold_rows) else ("direct" if any(r["is_direct"] for r in hold_rows) else "inherited"),
                            "effective_hold_count": len(hold_rows), "holds": detail})
        reason = "hold_held_item_management_required_for_held_move" if hold_effect == "movement_held_item_management" else {
            "deletion": "effective_hold_prevents_deletion", "metadata_change": "effective_hold_prevents_metadata_change",
            "movement": "effective_hold_prevents_metadata_change", "addition": "effective_hold_prevents_component_addition",
            "removal": "effective_hold_prevents_component_deletion", "replacement": "effective_hold_prevents_component_replacement",
            "reordering": "effective_hold_prevents_component_reordering",
        }[hold_effect]
        return False, reason, constraints
    aggregation_id = resource["id"] if resource_type == "aggregation" else resource["aggregation_id"]
    closed = connection.execute(
        """WITH RECURSIVE ancestry AS (
             SELECT id,parent_aggregation_id,date_closed FROM aggregations WHERE id=%s
             UNION ALL SELECT parent.id,parent.parent_aggregation_id,parent.date_closed
             FROM aggregations parent JOIN ancestry child ON child.parent_aggregation_id=parent.id)
           SELECT EXISTS(SELECT 1 FROM ancestry WHERE date_closed IS NOT NULL) AS value""",
        (aggregation_id,),
    ).fetchone()["value"]
    if not closed:
        return True, None, constraints
    read_only = {
        "aggregation.view", "record.view", "record.component.list",
        "record.component.view", "record.component.download",
    }
    if operation in read_only:
        return True, None, constraints
    governed_closed_exceptions = {
        "aggregation.vital_status.change", "aggregation.location.change",
        "aggregation.review_date.change", "record.vital_status.change",
        "record.review_date.change",
    }
    if operation in governed_closed_exceptions:
        return True, None, constraints
    if resource_type == "aggregation" and operation == "aggregation.reopen" and resource["date_closed"] is not None:
        return True, None, constraints
    return False, "resource_is_effectively_closed", constraints


@router.post("/explain", response_model=AccessExplanationRead)
def explain_access(
    payload: AccessExplanationRequest, request: Request,
    connection: Connection = Depends(get_connection, scope="function"),
):
    policy = OPERATION_POLICY.get(payload.operation)
    if policy is None or not payload.operation.startswith(f"{payload.resource_type}."):
        raise HTTPException(status_code=422, detail={"code": "unknown_resource_operation"})
    resource = _resource_for_examiner(connection, payload.resource_type, payload.resource_id)
    examiner = policy_context_from_request(request)
    selected_user_id = payload.user_id or examiner.user_id
    if selected_user_id is None:
        raise HTTPException(status_code=401, detail="authentication required")
    other_user = selected_user_id != examiner.user_id
    if other_user and not any(
        "authorization.explain" in role.privileges for role in examiner.effective_roles
    ):
        raise HTTPException(status_code=403, detail={"code": "insufficient_privilege"})
    subject = examiner if not other_user else load_user_policy_context(connection, selected_user_id)
    acl, acl_detail = _acl(connection, payload.resource_type, payload.resource_id, [role.role_id for role in subject.effective_roles])
    privilege, permission = policy
    integrity_allowed, integrity_reason, resource_state_constraints = _integrity_gate(
        connection, payload.resource_type, resource, payload.operation,
        subject.user_id, examiner.user_id,
    )
    decision = authorize(subject, AuthorizationRequest(
        operation=payload.operation, required_privilege=privilege,
        required_permissions=(permission,),
        resource_levels=(connection.execute(
            "SELECT level_number FROM security_levels WHERE id=%s",
            (resource["security_level_id"],),
        ).fetchone()["level_number"],),
        acl=acl,
        owning_org_unit_id=resource["owning_org_unit_id"],
        integrity_allowed=integrity_allowed, integrity_reason=integrity_reason,
    ))
    required_security_level = connection.execute(
        "SELECT id,code,name,level_number FROM security_levels WHERE id=%s",
        (resource["security_level_id"],),
    ).fetchone()
    effective_security_level = None
    if decision.effective_clearance is not None:
        effective_security_level = connection.execute(
            """SELECT id,code,name,level_number FROM security_levels
               WHERE level_number=%s ORDER BY id LIMIT 1""",
            (decision.effective_clearance,),
        ).fetchone()
    result = {
        "resource_type": payload.resource_type, "resource_id": payload.resource_id,
        "operation": payload.operation, "selected_user_id": selected_user_id,
        "other_user_diagnostic": other_user, "allowed": decision.allowed,
        "decision_code": decision.code.value,
        "gates": [asdict(gate) for gate in decision.gates],
        "contributors": {
            "privilege_role_ids": list(decision.privilege_role_ids),
            "clearance_role_ids": list(decision.clearance_role_ids),
            "acl_role_ids_by_permission": {
                key: list(value) for key, value in decision.acl_role_ids_by_permission.items()
            },
            "everyone_permissions": list(decision.everyone_permissions),
            "org_unit_member_permissions": list(decision.org_unit_member_permissions),
            "org_unit_member_role_ids_by_permission": {
                key: list(value)
                for key, value in decision.org_unit_member_role_ids_by_permission.items()
            },
            "governance_bypass_role_ids": list(decision.governance_bypass_role_ids),
        },
        "subject": _serialize_context(subject), "acl": acl_detail,
        "required_privilege": privilege, "required_permission": permission,
        "required_clearance": decision.required_clearance,
        "effective_security_level": effective_security_level,
        "required_security_level": required_security_level,
        "resource_state_constraints": resource_state_constraints,
    }
    if other_user:
        connection.execute(
            "SELECT append_domain_event(%s,%s,'ACCESS_EXPLANATION_VIEWED',%s::jsonb)",
            (payload.resource_type, payload.resource_id, Jsonb({
                "examiner_user_id": examiner.user_id, "selected_user_id": selected_user_id,
                "operation": payload.operation, "allowed": decision.allowed,
                "decision_code": decision.code.value,
                "effective_hold_constraints_evaluated": bool(resource_state_constraints),
            })),
        )
    return result


@router.get("/explainable-users", response_model=list[ExplainableUserRead], dependencies=[Depends(require_authorization_explain)])
def explainable_users(
    request: Request,
    q: str = Query("", max_length=120),
    limit: int = Query(25, ge=1, le=50),
    offset: int = Query(0, ge=0),
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Bounded identity search, including inactive people for access diagnosis."""
    language = preferred_language(connection, request)
    rows = list(connection.execute(
        """SELECT id,name,email,status,translations FROM users
           WHERE account_type='person' AND
             (%s='' OR name ILIKE '%%'||%s||'%%' OR email ILIKE '%%'||%s||'%%'
              OR COALESCE(translations->%s->>'name','') ILIKE '%%'||%s||'%%')
           ORDER BY lower(COALESCE(NULLIF(translations->%s->>'name',''),name)),id
           LIMIT %s OFFSET %s""",
        (q.strip(), q.strip(), q.strip(), language, q.strip(), language, limit, offset),
    ).fetchall())
    for row in rows:
        row['name'] = localized_projection(row, language, 'name')['name']
        row.pop('translations', None)
    return rows


@router.get("/governance-custody", response_model=GovernanceCustodyRead, dependencies=[Depends(require_authorization_admin)])
def governance_custody(
    request: Request,
    connection: Connection = Depends(get_connection, scope="function"),
):
    language_tag = preferred_language(connection, request)
    levels = list(connection.execute(
        "SELECT id,code,name,translations,level_number FROM security_levels ORDER BY level_number"
    ).fetchall())
    for level in levels:
        level["name"] = localized_projection(level, language_tag, "name")["name"]
        level.pop("translations", None)
    highest_level = levels[-1] if levels else None
    role_rows = list(connection.execute(
        """SELECT role.id,role.code,role.name,role.translations AS role_translations,
                  role.status,role.profile_id,
                  profile.code AS profile_code,profile.name AS profile_name,
                  level.id AS security_level_id,level.code AS security_level_code,
                  level.name AS security_level_name,
                  level.translations AS security_level_translations,level.level_number,
                  role_effectively_active(role.id) AS effective
           FROM roles role
           JOIN profiles profile ON profile.id=role.profile_id
           JOIN security_levels level ON level.id=role.security_level_id
           WHERE role.is_information_governance
           ORDER BY level.level_number DESC,role.name"""
    ).fetchall())
    profile_privileges: dict[int, set[str]] = {}
    for row in connection.execute(
        """SELECT membership.profile_id,privilege.code
           FROM profile_privileges membership
           JOIN privileges privilege ON privilege.id=membership.privilege_id"""
    ).fetchall():
        profile_privileges.setdefault(row["profile_id"], set()).add(row["code"])

    assignment_rows = list(connection.execute(
        """SELECT assignment.id,assignment.user_id,account.name AS user_name,
                  account.translations AS user_translations,
                  account.email AS user_email,account.status AS user_status,
                  account.account_type,
                  assignment.role_id,role.code AS role_code,role.name AS role_name,
                  role.translations AS role_translations,
                  assignment.valid_from,assignment.valid_until,
                  role_effectively_active(role.id) AS role_effective,
                  (assignment.valid_from<=CURRENT_TIMESTAMP
                   AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP))
                    AS assignment_current,
                  (account.status='active' AND assignment.valid_from<=CURRENT_TIMESTAMP
                   AND (assignment.valid_until IS NULL OR assignment.valid_until>CURRENT_TIMESTAMP)
                   AND role_effectively_active(role.id)) AS effective
           FROM user_role_assignments assignment JOIN users account ON account.id=assignment.user_id
           JOIN roles role ON role.id=assignment.role_id
           WHERE role.is_information_governance ORDER BY role.name,account.name"""
    ).fetchall())
    required_privileges = set(CUSTODY_PRIVILEGE_CODES)
    roles: list[dict] = []
    qualifying_role_ids: set[int] = set()
    for raw_role in role_rows:
        role = dict(raw_role)
        role["name"] = localized_projection(
            {"name": role["name"], "translations": role.pop("role_translations", {})},
            language_tag,
            "name",
        )["name"]
        role["security_level_name"] = localized_projection(
            {
                "name": role["security_level_name"],
                "translations": role.pop("security_level_translations", {}),
            },
            language_tag,
            "name",
        )["name"]
        supplied = profile_privileges.get(role["profile_id"], set())
        missing = sorted(required_privileges - supplied)
        role["is_highest_clearance"] = bool(
            highest_level and role["level_number"] == highest_level["level_number"]
        )
        role["has_required_custody_privileges"] = not missing
        role["qualifies_for_universal_custody"] = bool(
            role["effective"] and role["is_highest_clearance"] and not missing
        )
        role["missing_custody_privilege_codes"] = missing
        role_assignments = [row for row in assignment_rows if row["role_id"] == role["id"]]
        role["current_assignee_count"] = len({
            row["user_id"] for row in role_assignments if row["assignment_current"]
        })
        role["effective_assignee_count"] = len({
            row["user_id"] for row in role_assignments if row["effective"]
        })
        role["universal_custodian_count"] = len({
            row["user_id"] for row in role_assignments
            if role["qualifies_for_universal_custody"]
            and row["effective"] and row["account_type"] == "person"
        })
        if role["qualifies_for_universal_custody"]:
            qualifying_role_ids.add(role["id"])
        roles.append(role)

    assignments: list[dict] = []
    for raw_assignment in assignment_rows:
        assignment = dict(raw_assignment)
        assignment["user_name"] = localized_projection(
            {
                "name": assignment["user_name"],
                "translations": assignment.pop("user_translations", {}),
            },
            language_tag,
            "name",
        )["name"]
        assignment["role_name"] = localized_projection(
            {
                "name": assignment["role_name"],
                "translations": assignment.pop("role_translations", {}),
            },
            language_tag,
            "name",
        )["name"]
        reasons: list[str] = []
        if assignment["account_type"] != "person":
            reasons.append("service_account")
        if assignment["user_status"] != "active":
            reasons.append(f"user_{assignment['user_status']}")
        if not assignment["assignment_current"]:
            reasons.append("assignment_not_current")
        if not assignment["role_effective"]:
            reasons.append("role_or_organization_inactive")
        if assignment["role_id"] not in qualifying_role_ids:
            reasons.append("role_not_universal_custody_qualified")
        assignment["effective_for_universal_custody"] = not reasons
        assignment["ineffective_reasons"] = reasons
        assignment.pop("assignment_current", None)
        assignments.append(assignment)

    highest_people = len({
        row["user_id"] for row in assignments if row["effective_for_universal_custody"]
    })
    warnings = []
    if highest_people == 0:
        warnings.append({"code": "zero_universal_governance_custodians", "severity": "critical"})
    elif highest_people == 1:
        warnings.append({"code": "single_universal_governance_custodian", "severity": "advisory"})
    return {"security_levels": levels, "highest_security_level": highest_level,
            "required_custody_privilege_codes": sorted(required_privileges),
            "governance_roles": roles,
            "assignments": assignments, "highest_clearance_custodian_count": highest_people,
            "warnings": warnings}
