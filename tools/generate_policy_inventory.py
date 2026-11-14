#!/usr/bin/env python3
"""Generate the API authorization inventory from registered routes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

from fastapi import FastAPI, routing

from backend.services.api.main import app
from backend.services.api.operation_policy import AccessClass, OperationPolicy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "security" / "operation-policy-registry.json"


def api_routes(application: FastAPI):
    """Read effective FastAPI routes, including HTTP methods hidden from OpenAPI."""
    # New FastAPI releases keep included routers nested until inspection.
    # Earlier supported releases flatten them into application.routes.
    iter_contexts = getattr(routing, "iter_route_contexts", None)
    routes = iter_contexts(application.routes) if iter_contexts else application.routes
    for route in routes:
        if not isinstance(getattr(route, "original_route", route), routing.APIRoute):
            continue
        path = route.path_format
        if path == "/health" or path.startswith("/api/"):
            yield route


def operation_policy_for(route, method: str) -> OperationPolicy:
    declared = getattr(route.endpoint, "__erms_operation_policy__", None)
    privileges = {
        privilege
        for dependency in route.dependant.dependencies
        if (privilege := getattr(dependency.call, "__erms_global_privilege__", None))
    }
    operation = f"{method} {route.path_format}"
    if declared is None:
        if len(privileges) == 1:
            return OperationPolicy("globally_privileged", privileges.pop())
        raise ValueError(f"API operation {operation} has no explicit policy classification")
    if declared.target_policy_class not in get_args(AccessClass):
        raise ValueError(f"API operation {operation} uses an unknown policy class")
    if declared.target_policy_class == "globally_privileged":
        if not declared.global_privilege:
            raise ValueError(f"API operation {operation} must declare its global privilege")
        if privileges and declared.global_privilege not in privileges:
            raise ValueError(f"API operation {operation} declares a privilege absent from its dependencies")
    return declared


def api_operations(application: FastAPI = app) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for route in api_routes(application):
        path = route.path_format
        for upper_method in route.methods:
            if (upper_method, path) in seen:
                raise ValueError(f"Duplicate API operation {upper_method} {path}")
            seen.add((upper_method, path))
            policy = operation_policy_for(route, upper_method)
            conditional = {}
            if policy.conditional_global_privileges is not None:
                conditional["conditional_global_privileges"] = policy.conditional_global_privileges
            if policy.conditional_resource_authorization is not None:
                conditional["conditional_resource_authorization"] = policy.conditional_resource_authorization
            phase_7_enforced = (
                path.endswith("/capabilities")
                or "/acl-move" in path
                or "ownership-correction" in path
                or path.endswith("/correct-ownership")
                or path.startswith("/api/v1/security-level-changes/")
                or (
                    path in {
                        "/api/v1/aggregations",
                        "/api/v1/aggregations/{aggregation_id}",
                        "/api/v1/records",
                        "/api/v1/records/{record_id}",
                    }
                    and upper_method in {"POST", "PATCH", "DELETE"}
                )
                or (
                    "permissions" in path
                    and upper_method in {"PUT", "POST"}
                    and path.startswith(("/api/v1/aggregations/", "/api/v1/records/"))
                )
            )
            phase_8_enforced = (
                path.startswith("/api/v1/record-drafts")
                or "digital-components" in path
                or path.endswith("/correct-placement")
                or path == "/api/v1/records/{record_id}/capabilities"
            )
            phase_9_enforced = (
                path.startswith("/api/v1/authorization/")
                or path.endswith("/capabilities")
                or path in {
                    "/api/v1/aggregations/{aggregation_id}",
                    "/api/v1/records/{record_id}",
                }
            )
            phase_11_enforced = path.startswith("/api/v1/security-operations/")
            phase_12_enforced = (
                path.startswith(("/api/v1/users/", "/api/v1/roles/", "/api/v1/org-units/"))
                and (path.endswith("/deletion-preflight") or upper_method == "DELETE")
            )
            operations.append(
                {
                    "id": f"{upper_method}:{path}",
                    "method": upper_method,
                    "path": path,
                    "current_access_class": policy.current_access_class,
                    "target_policy_class": policy.target_policy_class,
                    "global_privilege": policy.global_privilege,
                    "resource_permission": policy.resource_permission,
                    **conditional,
                    "phase_0_enforced": False,
                    "phase_4_enforced": policy.target_policy_class == "globally_privileged",
                    "phase_5_enforced": (
                        path == "/api/v1/permissions"
                        or ((("permissions" in path) or "/acl-move" in path) and path.startswith(("/api/v1/aggregations/", "/api/v1/records/")))
                    ),
                    "phase_7_enforced": phase_7_enforced,
                    "phase_8_enforced": phase_8_enforced,
                    "phase_9_enforced": phase_9_enforced,
                    "phase_11_enforced": phase_11_enforced,
                    "phase_12_enforced": phase_12_enforced,
                }
            )
    return sorted(operations, key=lambda item: (item["path"], item["method"]))


def build_inventory() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "specification_revision": "0.6",
        "phase": 12,
        "enforcement_status": "authorization_dependent_permanent_deletion_enforced",
        "scope": "api_authorization_boundary",
        "client_policy": (
            "Clients are untrusted API consumers. Client action inventories are optional "
            "UX artefacts and are not part of this security registry."
        ),
        "access_classes": list(get_args(AccessClass)),
        "api_operations": api_operations(),
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_inventory(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
