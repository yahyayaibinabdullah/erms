"""Route-local authorization declarations for the generated inventory."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeVar


AccessClass = Literal[
    "public",
    "authenticated_only",
    "system_administrator",
    "globally_privileged",
    "resource_scoped",
    "relationship_scoped",
    "governance_exception",
    "service_lease_scoped",
]
Endpoint = TypeVar("Endpoint", bound=Callable[..., Any])


@dataclass(frozen=True)
class OperationPolicy:
    target_policy_class: AccessClass
    global_privilege: str | None = None
    resource_permission: str | None = None
    conditional_global_privileges: dict[str, Any] | None = None
    conditional_resource_authorization: dict[str, Any] | None = None

    @property
    def current_access_class(self) -> AccessClass:
        if self.target_policy_class in {"public", "system_administrator", "globally_privileged"}:
            return self.target_policy_class
        return "authenticated_only"


def operation_policy(
    target_policy_class: AccessClass,
    global_privilege: str | None = None,
    resource_permission: str | None = None,
    *,
    conditional_global_privileges: dict[str, Any] | None = None,
    conditional_resource_authorization: dict[str, Any] | None = None,
) -> Callable[[Endpoint], Endpoint]:
    """Describe access enforced by the route without wrapping its endpoint."""
    policy = OperationPolicy(
        target_policy_class, global_privilege, resource_permission,
        conditional_global_privileges, conditional_resource_authorization,
    )

    def declare(endpoint: Endpoint) -> Endpoint:
        setattr(endpoint, "__erms_operation_policy__", policy)
        return endpoint

    return declare
