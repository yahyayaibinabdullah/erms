from dataclasses import replace
from datetime import datetime, timedelta, timezone

import os
import psycopg
import pytest
from psycopg.rows import dict_row

from backend.services.api.authentication import Principal
from backend.services.api.authorization_policy import (
    AuthorizationRequest,
    DecisionCode,
    EffectiveRole,
    PolicyContext,
    ResourceAcl,
    RoleCandidate,
    authorize,
    load_policy_context,
    resolve_effective_roles,
)


NOW = datetime(2026, 9, 19, 8, 0, tzinfo=timezone.utc)


def role(
    role_id: int,
    *,
    org_unit_id: int = 1,
    clearance: int = 10,
    privileges: tuple[str, ...] = ("record.view",),
    governance: bool = False,
) -> EffectiveRole:
    return EffectiveRole(
        role_id=role_id, role_code=f"R{role_id}", role_name=f"Role {role_id}",
        org_unit_id=org_unit_id,
        profile_id=role_id, profile_code=f"P{role_id}", profile_name=f"Profile {role_id}",
        security_level_id=role_id, security_level_code=f"L{clearance}",
        clearance=clearance, is_information_governance=governance,
        privileges=frozenset(privileges),
    )


def context(*roles: EffectiveRole, **changes) -> PolicyContext:
    base = PolicyContext(
        user_id=1, session_id=1, evaluated_at=NOW, authenticated=True,
        session_expires_at=NOW + timedelta(hours=1),
        session_absolute_expires_at=NOW + timedelta(hours=8),
        user_status="active", effective_roles=roles,
    )
    return replace(base, **changes)


def candidate(role_id: int, **changes) -> RoleCandidate:
    base = RoleCandidate(
        assignment_id=role_id, role_id=role_id, role_code=f"R{role_id}",
        role_name=f"Role {role_id}", role_status="active", org_unit_id=1,
        org_unit_effective=True, valid_from=NOW - timedelta(days=1), valid_until=None,
        profile_id=1, profile_code="ONE", profile_name="One profile",
        security_level_id=1, security_level_code="G", clearance=10,
        is_information_governance=False, privileges=frozenset({"record.view"}),
    )
    return replace(base, **changes)


@pytest.mark.parametrize(("changes", "code"), [
    ({"authenticated": False}, DecisionCode.AUTHENTICATION_REQUIRED),
    ({"session_revoked": True}, DecisionCode.SESSION_REVOKED),
    ({"session_expires_at": NOW}, DecisionCode.SESSION_EXPIRED),
    ({"session_absolute_expires_at": NOW}, DecisionCode.SESSION_EXPIRED),
    ({"user_status": "inactive"}, DecisionCode.USER_INACTIVE),
    ({"user_status": "suspended"}, DecisionCode.USER_SUSPENDED),
    ({"locked_until": NOW + timedelta(minutes=1)}, DecisionCode.USER_LOCKED),
])
def test_authentication_gate_has_stable_reason_codes(changes, code):
    decision = authorize(context(role(1), **changes), AuthorizationRequest("record.open"))
    assert not decision.allowed
    assert decision.code == code
    assert decision.gates[-1].gate == "authentication"


@pytest.mark.parametrize(("changes", "reason"), [
    ({"role_status": "inactive"}, "role_inactive"),
    ({"org_unit_effective": False}, "organization_ancestry_inactive"),
    ({"valid_from": NOW + timedelta(seconds=1)}, "assignment_not_started"),
    ({"valid_until": NOW}, "assignment_expired"),
])
def test_effective_role_resolution_explains_exclusions(changes, reason):
    effective, excluded = resolve_effective_roles((candidate(1, **changes),), NOW)
    assert effective == ()
    assert excluded[0].reason == reason


def test_assignment_end_is_exclusive_and_each_role_has_one_profile():
    effective, excluded = resolve_effective_roles((
        candidate(1, valid_until=NOW + timedelta(microseconds=1)),
        candidate(2, valid_until=NOW),
    ), NOW)
    assert [item.role_id for item in effective] == [1]
    assert effective[0].profile_id == 1
    assert effective[0].profile_code == "ONE"
    assert excluded[0].role_id == 2


def test_no_effective_role_is_denied_before_privilege_checks():
    decision = authorize(context(), AuthorizationRequest(
        "record.open", required_privilege="record.view"
    ))
    assert decision.code == DecisionCode.NO_EFFECTIVE_ROLE
    assert [gate.gate for gate in decision.gates] == ["authentication", "effective_roles"]


def test_system_administrator_name_has_no_policy_bypass():
    administrator = replace(
        role(1, privileges=()), role_code="system-administrator",
        role_name="System Administrator",
    )
    decision = authorize(context(administrator), AuthorizationRequest(
        "record.open", required_privilege="record.view",
    ))
    assert decision.code == DecisionCode.INSUFFICIENT_PRIVILEGE


def test_union_based_rbac_tracks_different_contributing_roles():
    ctx = context(
        role(1, clearance=10, privileges=("record.modify",)),
        role(2, clearance=100, privileges=()),
        role(3, clearance=5, privileges=()),
    )
    decision = authorize(ctx, AuthorizationRequest(
        "record.modify", required_privilege="record.modify",
        resource_levels=(50,), required_permissions=("record.modify_metadata",),
        acl=ResourceAcl(role_permissions={3: frozenset({"record.modify_metadata"})}),
    ))
    assert decision.allowed
    assert decision.privilege_role_ids == (1,)
    assert decision.clearance_role_ids == (2,)
    assert decision.acl_role_ids_by_permission["record.modify_metadata"] == (3,)


def test_lower_clearance_role_does_not_veto_maximum_clearance():
    decision = authorize(context(role(1, clearance=10), role(2, clearance=100)),
        AuthorizationRequest("record.open", required_privilege="record.view", resource_levels=(50,)))
    assert decision.allowed
    assert decision.effective_clearance == 100


def test_all_involved_resources_must_pass_clearance():
    decision = authorize(context(role(1, clearance=50)), AuthorizationRequest(
        "record.move", required_privilege="record.view", resource_levels=(10, 100)
    ))
    assert decision.code == DecisionCode.INSUFFICIENT_CLEARANCE
    assert decision.required_clearance == 100


def test_every_required_permission_must_be_present_but_may_be_split_across_roles():
    acl = ResourceAcl(role_permissions={
        1: frozenset({"record.view"}), 2: frozenset({"record.component.download"}),
    })
    request = AuthorizationRequest(
        "component.download", required_privilege="record.component.download",
        required_permissions=("record.view", "record.component.download"), acl=acl,
    )
    allowed = authorize(context(
        role(1, privileges=("record.component.download",)), role(2, privileges=())
    ), request)
    denied = authorize(context(role(1, privileges=("record.component.download",))), request)
    assert allowed.allowed
    assert denied.code == DecisionCode.INSUFFICIENT_RESOURCE_PERMISSION
    assert denied.gates[-1].detail == "record.component.download"


def test_everyone_grant_is_an_acl_contributor():
    decision = authorize(context(role(1)), AuthorizationRequest(
        "record.open", required_privilege="record.view",
        required_permissions=("record.view",),
        acl=ResourceAcl(everyone_permissions=frozenset({"record.view"})),
    ))
    assert decision.allowed
    assert decision.everyone_permissions == ("record.view",)


def test_org_unit_members_grant_matches_only_roles_in_the_resource_owner():
    request = AuthorizationRequest(
        operation="record.view",
        required_privilege="record.view",
        required_permissions=("record.view",),
        owning_org_unit_id=7,
        acl=ResourceAcl(org_unit_member_permissions=frozenset({"record.view"})),
    )
    allowed = authorize(context(role(1, org_unit_id=7)), request)
    denied = authorize(context(role(2, org_unit_id=8)), request)

    assert allowed.allowed
    assert allowed.org_unit_member_permissions == ("record.view",)
    assert allowed.org_unit_member_role_ids_by_permission == {"record.view": (1,)}
    assert denied.code == DecisionCode.INSUFFICIENT_RESOURCE_PERMISSION


def test_governance_bypasses_only_acl_using_its_own_clearance():
    request = AuthorizationRequest(
        "record.modify", required_privilege="record.modify", resource_levels=(50,),
        required_permissions=("record.modify_metadata",), acl=ResourceAcl(),
    )
    borrowed_clearance = authorize(context(
        role(1, clearance=10, privileges=("record.modify",), governance=True),
        role(2, clearance=100, privileges=()),
    ), request)
    qualified = authorize(context(
        role(1, clearance=50, privileges=("record.modify",), governance=True),
    ), request)
    no_privilege = authorize(context(
        role(1, clearance=100, privileges=(), governance=True),
    ), request)
    assert borrowed_clearance.code == DecisionCode.INSUFFICIENT_RESOURCE_PERMISSION
    assert qualified.allowed and qualified.governance_bypass_role_ids == (1,)
    assert no_privilege.code == DecisionCode.INSUFFICIENT_PRIVILEGE


def test_integrity_gate_is_independent_and_precedes_privilege():
    decision = authorize(context(role(1, privileges=())), AuthorizationRequest(
        "aggregation.add_record", required_privilege="record.create",
        integrity_allowed=False, integrity_reason="aggregation_closed",
    ))
    assert decision.code == DecisionCode.OPERATION_NOT_ALLOWED
    assert decision.gates[-1].detail == "aggregation_closed"


def test_policy_context_is_an_immutable_request_snapshot():
    original = context(role(1, privileges=("record.view",)))
    request = AuthorizationRequest("record.open", required_privilege="record.view")
    changed = replace(original, effective_roles=(role(1, privileges=()),))
    assert authorize(original, request).allowed
    assert authorize(changed, request).code == DecisionCode.INSUFFICIENT_PRIVILEGE
    assert authorize(original, request).allowed


def test_database_loader_materializes_profile_privileges_and_request_time_roles(client):
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        session = connection.execute(
            "SELECT id, user_id FROM login_sessions WHERE user_id=1 AND revoked_at IS NULL"
        ).fetchone()
        principal = Principal(
            user_id=session["user_id"], session_id=session["id"], name="Test Administrator",
            email="admin@test.invalid", account_type="person", must_change_password=False, roles=[],
        )
        loaded = load_policy_context(connection, principal, evaluated_at=datetime.now(timezone.utc))
        assert loaded.authenticated
        assert len(loaded.effective_roles) == 1
        loaded_role = loaded.effective_roles[0]
        assert loaded_role.profile_code == "ALL_PRIVS"
        assert "authorization.administer" in loaded_role.privileges
        assert loaded_role.security_level_code == "G"

        connection.execute(
            "UPDATE roles SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s",
            (loaded_role.role_id,),
        )
        refreshed = load_policy_context(connection, principal, evaluated_at=datetime.now(timezone.utc))
        assert loaded.effective_roles  # the already-materialized request remains stable
        assert refreshed.effective_roles == ()
        assert refreshed.excluded_roles[0].reason == "role_inactive"


def test_everyone_passes_only_the_type_gate_in_access_explanations():
    operation = AuthorizationRequest("record.open", required_privilege="record.view",
                                     resource_typed=True, type_access="see", type_everyone_grant=True)
    granted = authorize(context(role(1)), operation)
    assert granted.allowed and not granted.type_bypass_role_ids and not granted.type_role_ids
    assert next(g.detail for g in granted.gates if g.gate == "resource_type") == "everyone"
    assert authorize(context(), operation).code == DecisionCode.NO_EFFECTIVE_ROLE
    denied = authorize(context(role(1, privileges=())), operation)
    assert not denied.allowed and denied.gates[-1].gate == "global_privilege"
