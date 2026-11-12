from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Mapping

from fastapi import HTTPException, Request
from psycopg import Connection

from .audit_context import (
    actor_email_context, actor_name_context, actor_type_context,
    actor_user_id_context, correlation_id_context, event_source_context,
    request_id_context,
)
from .database import pool
if TYPE_CHECKING:
    from .authentication import Principal


EVERYONE = "everyone"
ORG_UNIT_MEMBERS = "org_unit_members"


class DecisionCode(StrEnum):
    ALLOWED = "allowed"
    AUTHENTICATION_REQUIRED = "authentication_required"
    SESSION_REVOKED = "session_revoked"
    SESSION_EXPIRED = "session_expired"
    USER_INACTIVE = "user_inactive"
    USER_SUSPENDED = "user_suspended"
    USER_LOCKED = "user_locked"
    NO_EFFECTIVE_ROLE = "no_effective_role"
    OPERATION_NOT_ALLOWED = "operation_not_allowed"
    INSUFFICIENT_PRIVILEGE = "insufficient_privilege"
    INSUFFICIENT_CLEARANCE = "insufficient_clearance"
    INSUFFICIENT_RESOURCE_PERMISSION = "insufficient_resource_permission"


@dataclass(frozen=True)
class RoleCandidate:
    assignment_id: int
    role_id: int
    role_code: str
    role_name: str
    role_status: str
    org_unit_id: int
    org_unit_effective: bool
    valid_from: datetime
    valid_until: datetime | None
    profile_id: int
    profile_code: str
    profile_name: str
    security_level_id: int
    security_level_code: str
    clearance: int
    is_information_governance: bool
    privileges: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RoleExclusion:
    role_id: int
    role_code: str
    reason: str


@dataclass(frozen=True)
class EffectiveRole:
    role_id: int
    role_code: str
    role_name: str
    org_unit_id: int
    profile_id: int
    profile_code: str
    profile_name: str
    security_level_id: int
    security_level_code: str
    clearance: int
    is_information_governance: bool
    privileges: frozenset[str]


@dataclass(frozen=True)
class PolicyContext:
    user_id: int | None
    session_id: int | None
    evaluated_at: datetime
    authenticated: bool
    session_revoked: bool = False
    session_expires_at: datetime | None = None
    session_absolute_expires_at: datetime | None = None
    user_status: str | None = None
    locked_until: datetime | None = None
    effective_roles: tuple[EffectiveRole, ...] = ()
    excluded_roles: tuple[RoleExclusion, ...] = ()

    @property
    def effective_clearance(self) -> int | None:
        return max((role.clearance for role in self.effective_roles), default=None)


@dataclass(frozen=True)
class ResourceAcl:
    """The already-resolved effective ACL supplied to the Phase 3 engine.

    Phase 5 will resolve local/inherited ACL rows into this value.  Keeping the
    policy engine independent of storage makes its decision semantics testable
    now and prevents route-specific authorization logic later.
    """

    everyone_permissions: frozenset[str] = field(default_factory=frozenset)
    org_unit_member_permissions: frozenset[str] = field(default_factory=frozenset)
    role_permissions: Mapping[int, frozenset[str]] = field(default_factory=dict)
    source: str | None = None

    def __post_init__(self) -> None:
        normalized = {
            int(role_id): frozenset(permissions)
            for role_id, permissions in self.role_permissions.items()
        }
        object.__setattr__(self, "role_permissions", MappingProxyType(normalized))


@dataclass(frozen=True)
class AuthorizationRequest:
    operation: str
    required_privilege: str | None = None
    required_permissions: tuple[str, ...] = ()
    resource_levels: tuple[int, ...] = ()
    acl: ResourceAcl | None = None
    owning_org_unit_id: int | None = None
    integrity_allowed: bool = True
    integrity_reason: str | None = None


@dataclass(frozen=True)
class GateResult:
    gate: str
    passed: bool
    code: str
    detail: str | None = None


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    code: DecisionCode
    operation: str
    gates: tuple[GateResult, ...]
    effective_role_ids: tuple[int, ...]
    privilege_role_ids: tuple[int, ...] = ()
    clearance_role_ids: tuple[int, ...] = ()
    acl_role_ids_by_permission: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    everyone_permissions: tuple[str, ...] = ()
    org_unit_member_permissions: tuple[str, ...] = ()
    org_unit_member_role_ids_by_permission: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    governance_bypass_role_ids: tuple[int, ...] = ()
    effective_clearance: int | None = None
    required_clearance: int | None = None

    def __post_init__(self) -> None:
        normalized = {
            permission: tuple(role_ids)
            for permission, role_ids in self.acl_role_ids_by_permission.items()
        }
        object.__setattr__(self, "acl_role_ids_by_permission", MappingProxyType(normalized))
        org_unit_members = {
            permission: tuple(role_ids)
            for permission, role_ids in self.org_unit_member_role_ids_by_permission.items()
        }
        object.__setattr__(
            self, "org_unit_member_role_ids_by_permission",
            MappingProxyType(org_unit_members),
        )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def resolve_effective_roles(
    candidates: tuple[RoleCandidate, ...], evaluated_at: datetime
) -> tuple[tuple[EffectiveRole, ...], tuple[RoleExclusion, ...]]:
    at = _aware(evaluated_at)
    effective: list[EffectiveRole] = []
    excluded: list[RoleExclusion] = []
    for candidate in candidates:
        reason = None
        if candidate.role_status != "active":
            reason = "role_inactive"
        elif not candidate.org_unit_effective:
            reason = "organization_ancestry_inactive"
        elif _aware(candidate.valid_from) > at:
            reason = "assignment_not_started"
        elif candidate.valid_until is not None and _aware(candidate.valid_until) <= at:
            reason = "assignment_expired"
        if reason:
            excluded.append(RoleExclusion(candidate.role_id, candidate.role_code, reason))
            continue
        effective.append(EffectiveRole(
            role_id=candidate.role_id,
            role_code=candidate.role_code,
            role_name=candidate.role_name,
            org_unit_id=candidate.org_unit_id,
            profile_id=candidate.profile_id,
            profile_code=candidate.profile_code,
            profile_name=candidate.profile_name,
            security_level_id=candidate.security_level_id,
            security_level_code=candidate.security_level_code,
            clearance=candidate.clearance,
            is_information_governance=candidate.is_information_governance,
            privileges=candidate.privileges,
        ))
    return tuple(effective), tuple(excluded)


def _deny(
    context: PolicyContext,
    request: AuthorizationRequest,
    code: DecisionCode,
    gates: list[GateResult],
    **contributors: Any,
) -> AuthorizationDecision:
    return AuthorizationDecision(
        allowed=False,
        code=code,
        operation=request.operation,
        gates=tuple(gates),
        effective_role_ids=tuple(role.role_id for role in context.effective_roles),
        effective_clearance=context.effective_clearance,
        required_clearance=max(request.resource_levels, default=None),
        **contributors,
    )


def authorize(context: PolicyContext, request: AuthorizationRequest) -> AuthorizationDecision:
    gates: list[GateResult] = []
    now = _aware(context.evaluated_at)
    auth_code: DecisionCode | None = None
    if not context.authenticated:
        auth_code = DecisionCode.AUTHENTICATION_REQUIRED
    elif context.session_revoked:
        auth_code = DecisionCode.SESSION_REVOKED
    elif (
        (context.session_expires_at and _aware(context.session_expires_at) <= now)
        or (context.session_absolute_expires_at and _aware(context.session_absolute_expires_at) <= now)
    ):
        auth_code = DecisionCode.SESSION_EXPIRED
    elif context.user_status == "inactive":
        auth_code = DecisionCode.USER_INACTIVE
    elif context.user_status == "suspended":
        auth_code = DecisionCode.USER_SUSPENDED
    elif context.locked_until and _aware(context.locked_until) > now:
        auth_code = DecisionCode.USER_LOCKED
    elif context.user_status != "active":
        auth_code = DecisionCode.AUTHENTICATION_REQUIRED
    if auth_code:
        gates.append(GateResult("authentication", False, auth_code.value))
        return _deny(context, request, auth_code, gates)
    gates.append(GateResult("authentication", True, DecisionCode.ALLOWED.value))

    if not context.effective_roles:
        gates.append(GateResult("effective_roles", False, DecisionCode.NO_EFFECTIVE_ROLE.value))
        return _deny(context, request, DecisionCode.NO_EFFECTIVE_ROLE, gates)
    gates.append(GateResult("effective_roles", True, DecisionCode.ALLOWED.value))

    if not request.integrity_allowed:
        gates.append(GateResult(
            "operation_integrity", False, DecisionCode.OPERATION_NOT_ALLOWED.value,
            request.integrity_reason,
        ))
        return _deny(context, request, DecisionCode.OPERATION_NOT_ALLOWED, gates)
    gates.append(GateResult("operation_integrity", True, DecisionCode.ALLOWED.value))

    privilege_roles = tuple(
        role.role_id for role in context.effective_roles
        if request.required_privilege is None or request.required_privilege in role.privileges
    )
    if request.required_privilege and not privilege_roles:
        gates.append(GateResult("global_privilege", False, DecisionCode.INSUFFICIENT_PRIVILEGE.value))
        return _deny(context, request, DecisionCode.INSUFFICIENT_PRIVILEGE, gates)
    gates.append(GateResult("global_privilege", True, DecisionCode.ALLOWED.value))

    required_clearance = max(request.resource_levels, default=None)
    effective_clearance = context.effective_clearance
    clearance_roles = tuple(
        role.role_id for role in context.effective_roles
        if required_clearance is not None and role.clearance == effective_clearance
    )
    if required_clearance is not None and (
        effective_clearance is None or effective_clearance < required_clearance
    ):
        gates.append(GateResult("security_clearance", False, DecisionCode.INSUFFICIENT_CLEARANCE.value))
        return _deny(
            context, request, DecisionCode.INSUFFICIENT_CLEARANCE, gates,
            privilege_role_ids=privilege_roles,
        )
    gates.append(GateResult("security_clearance", True, DecisionCode.ALLOWED.value))

    permission_roles: dict[str, tuple[int, ...]] = {}
    everyone = tuple(
        permission for permission in request.required_permissions
        if request.acl and permission in request.acl.everyone_permissions
    )
    org_unit_members = tuple(
        permission for permission in request.required_permissions
        if request.acl and permission in request.acl.org_unit_member_permissions
        and request.owning_org_unit_id is not None
        and any(
            role.org_unit_id == request.owning_org_unit_id
            for role in context.effective_roles
        )
    )
    org_unit_member_roles = {
        permission: tuple(
            role.role_id for role in context.effective_roles
            if request.owning_org_unit_id is not None
            and role.org_unit_id == request.owning_org_unit_id
        ) if permission in org_unit_members else ()
        for permission in request.required_permissions
    }
    missing: list[str] = []
    for permission in request.required_permissions:
        contributors = tuple(
            role.role_id for role in context.effective_roles
            if request.acl and permission in request.acl.role_permissions.get(role.role_id, frozenset())
        )
        permission_roles[permission] = contributors
        if permission not in everyone and permission not in org_unit_members and not contributors:
            missing.append(permission)

    governance_roles = tuple(
        role.role_id for role in context.effective_roles
        if role.is_information_governance
        and (required_clearance is None or role.clearance >= required_clearance)
    )
    bypass = governance_roles if missing else ()
    if missing and not bypass:
        gates.append(GateResult(
            "resource_acl", False, DecisionCode.INSUFFICIENT_RESOURCE_PERMISSION.value,
            ",".join(missing),
        ))
        return _deny(
            context, request, DecisionCode.INSUFFICIENT_RESOURCE_PERMISSION, gates,
            privilege_role_ids=privilege_roles,
            clearance_role_ids=clearance_roles,
            acl_role_ids_by_permission=permission_roles,
            everyone_permissions=everyone,
            org_unit_member_permissions=org_unit_members,
            org_unit_member_role_ids_by_permission=org_unit_member_roles,
        )
    gates.append(GateResult(
        "resource_acl", True, DecisionCode.ALLOWED.value,
        "information_governance_bypass" if bypass else None,
    ))
    return AuthorizationDecision(
        allowed=True,
        code=DecisionCode.ALLOWED,
        operation=request.operation,
        gates=tuple(gates),
        effective_role_ids=tuple(role.role_id for role in context.effective_roles),
        privilege_role_ids=privilege_roles,
        clearance_role_ids=clearance_roles,
        acl_role_ids_by_permission=permission_roles,
        everyone_permissions=everyone,
        org_unit_member_permissions=org_unit_members,
        org_unit_member_role_ids_by_permission=org_unit_member_roles,
        governance_bypass_role_ids=bypass,
        effective_clearance=effective_clearance,
        required_clearance=required_clearance,
    )


def _load_candidates(connection: Connection, user_id: int) -> tuple[RoleCandidate, ...]:
    rows = connection.execute(
        """
        SELECT ura.id AS assignment_id, ura.valid_from, ura.valid_until,
               r.id AS role_id, r.code AS role_code, r.name AS role_name,
               r.status AS role_status, r.profile_id, r.is_information_governance,
               ou.id AS org_unit_id, org_unit_effectively_active(ou.id) AS org_unit_effective,
               profile.code AS profile_code, profile.name AS profile_name,
               level.id AS security_level_id, level.code AS security_level_code,
               level.level_number AS clearance,
               COALESCE(array_agg(privilege.code ORDER BY privilege.code)
                   FILTER (WHERE privilege.code IS NOT NULL), ARRAY[]::text[]) AS privileges
          FROM user_role_assignments ura
          JOIN roles r ON r.id = ura.role_id
          JOIN org_units ou ON ou.id = r.org_unit_id
          JOIN profiles profile ON profile.id = r.profile_id
          JOIN security_levels level ON level.id = r.security_level_id
          LEFT JOIN profile_privileges pp ON pp.profile_id = profile.id
          LEFT JOIN privileges privilege ON privilege.id = pp.privilege_id
         WHERE ura.user_id = %s
         GROUP BY ura.id, r.id, ou.id, profile.id, level.id
         ORDER BY r.id, ura.id
        """,
        (user_id,),
    ).fetchall()
    return tuple(RoleCandidate(
        assignment_id=row["assignment_id"], role_id=row["role_id"],
        role_code=row["role_code"], role_name=row["role_name"],
        role_status=row["role_status"], org_unit_id=row["org_unit_id"],
        org_unit_effective=row["org_unit_effective"], valid_from=row["valid_from"],
        valid_until=row["valid_until"], profile_id=row["profile_id"],
        profile_code=row["profile_code"], profile_name=row["profile_name"],
        security_level_id=row["security_level_id"],
        security_level_code=row["security_level_code"], clearance=row["clearance"],
        is_information_governance=row["is_information_governance"],
        privileges=frozenset(row["privileges"]),
    ) for row in rows)


def load_policy_context(
    connection: Connection,
    principal: Principal,
    *,
    evaluated_at: datetime | None = None,
) -> PolicyContext:
    at = evaluated_at or datetime.now(timezone.utc)
    account = connection.execute(
        """
        SELECT u.status AS user_status, credential.locked_until,
               session.revoked_at IS NOT NULL AS session_revoked,
               session.expires_at, session.absolute_expires_at
          FROM users u
          JOIN user_credentials credential ON credential.user_id = u.id
          JOIN login_sessions session ON session.id = %s AND session.user_id = u.id
         WHERE u.id = %s
        """,
        (principal.session_id, principal.user_id),
    ).fetchone()
    if account is None:
        return PolicyContext(
            user_id=principal.user_id, session_id=principal.session_id,
            evaluated_at=at, authenticated=False,
        )
    candidates = _load_candidates(connection, principal.user_id)
    effective, excluded = resolve_effective_roles(candidates, at)
    return PolicyContext(
        user_id=principal.user_id,
        session_id=principal.session_id,
        evaluated_at=at,
        authenticated=True,
        session_revoked=account["session_revoked"],
        session_expires_at=account["expires_at"],
        session_absolute_expires_at=account["absolute_expires_at"],
        user_status=account["user_status"],
        locked_until=account["locked_until"],
        effective_roles=effective,
        excluded_roles=excluded,
    )


def load_user_policy_context(
    connection: Connection, user_id: int, *, evaluated_at: datetime | None = None,
) -> PolicyContext:
    """Load a user's policy attributes without impersonating or creating a session."""
    at = evaluated_at or datetime.now(timezone.utc)
    account = connection.execute(
        """SELECT account.status AS user_status, credential.locked_until
           FROM users account
           LEFT JOIN user_credentials credential ON credential.user_id=account.id
           WHERE account.id=%s""", (user_id,),
    ).fetchone()
    if account is None:
        raise HTTPException(status_code=404, detail="user not found")
    effective, excluded = resolve_effective_roles(_load_candidates(connection, user_id), at)
    return PolicyContext(
        user_id=user_id, session_id=None, evaluated_at=at, authenticated=True,
        user_status=account["user_status"], locked_until=account["locked_until"],
        effective_roles=effective, excluded_roles=excluded,
    )


def policy_context_from_request(request: Request) -> PolicyContext:
    context = getattr(request.state, "policy_context", None)
    if context is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return context


def require_global_privilege(privilege: str) -> Callable[[Request], AuthorizationDecision]:
    """Create a FastAPI dependency for a non-resource administrative operation."""

    def dependency(request: Request) -> AuthorizationDecision:
        context = policy_context_from_request(request)
        decision = authorize(
            context,
            AuthorizationRequest(
                operation=f"global:{privilege}",
                required_privilege=privilege,
            ),
        )
        if not decision.allowed:
            if context.user_id is not None:
                with pool.connection() as connection:
                    connection.execute(
                        """
                        SELECT set_config('app.user_id',%s,true),
                               set_config('app.actor_name',%s,true),
                               set_config('app.actor_email',%s,true),
                               set_config('app.actor_type',%s,true),
                               set_config('app.event_source',%s,true),
                               set_config('app.request_id',%s,true),
                               set_config('app.correlation_id',%s,true)
                        """,
                        (
                            actor_user_id_context.get(), actor_name_context.get(),
                            actor_email_context.get(), actor_type_context.get(),
                            event_source_context.get(), request_id_context.get(),
                            correlation_id_context.get(),
                        ),
                    )
                    connection.execute(
                        "SELECT append_domain_event('user',%s,'AUTHORIZATION_DENIED',%s::jsonb)",
                        (context.user_id, __import__("json").dumps({
                            "required_privilege": privilege,
                            "decision_code": decision.code.value,
                            "http_method": request.method,
                            "request_path": request.url.path,
                        })),
                    )
                    connection.commit()
            raise HTTPException(
                status_code=403,
                detail={
                    "code": decision.code.value,
                    "message": "The current account is not authorized for this operation",
                },
            )
        return decision

    dependency.__name__ = f"require_{privilege.replace('.', '_')}"
    setattr(dependency, "__erms_global_privilege__", privilege)
    return dependency


require_identity_users_admin = require_global_privilege("identity.users.administer")
require_identity_text_indexers_admin = require_global_privilege("identity.text_indexers.administer")
require_identity_sessions_admin = require_global_privilege("identity.sessions.administer")
require_organization_browse = require_global_privilege("organization.browse")
require_organization_admin = require_global_privilege("organization.administer")
require_ownership_correct = require_global_privilege("organization.ownership.correct")
require_authorization_admin = require_global_privilege("authorization.administer")
require_security_levels_admin = require_global_privilege("security_levels.administer")
require_classifications_admin = require_global_privilege("classifications.administer")
require_audit_view = require_global_privilege("audit.view")
