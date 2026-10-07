#!/usr/bin/env python3
"""Generate the authoritative API operation-policy inventory.

The output is deliberately deterministic. An API route or policy-classification
change therefore fails the characterization test until the security impact is
reviewed and the inventory is regenerated. Client controls are intentionally
excluded: authorization is enforced at the API/database boundary, and each
client may evolve independently without creating security-policy churn.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.services.api.main import app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "security" / "operation-policy-registry.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _current_access(method: str, path: str) -> str:
    if path == "/health" or (method == "POST" and path == "/api/v1/auth/login"):
        return "public"
    if path in {
        "/api/v1/auth/users/{user_id}/sessions",
        "/api/v1/auth/users/{user_id}/temporary-password",
    }:
        return "system_administrator"
    return "authenticated_only"


def _target_policy(method: str, path: str) -> tuple[str, str | None, str | None]:
    """Return target class, global privilege, and resource permission.

    Phase 0 records the intended policy hook without enforcing it. Fine-grained
    source/destination and component rules remain defined by the approved spec.
    """
    if path == "/health" or (method == "POST" and path == "/api/v1/auth/login"):
        return "public", None, None
    if path == "/api/v1/messages/stream/sse":
        return "relationship_scoped", None, None
    if path.startswith("/api/v1/messages/monitor"):
        return "globally_privileged", "messaging.monitor", None
    if path in {"/api/v1/messages/{envelope_id}/capture", "/api/v1/messages/{envelope_id}/capture-preview"}:
        return "relationship_scoped", "record.create", None
    if path.startswith("/api/v1/messages/recently-deleted/") or path in {"/api/v1/messages/{mailbox}/{identity}", "/api/v1/messages/{mailbox}/{identity}/restore"}:
        return "relationship_scoped", None, None
    if path.startswith("/api/v1/notification-administration/"):
        return "globally_privileged", "messaging.notifications.administer", None
    if (method, path) in {
        ("GET", "/api/v1/messages/linked/{root_id}/{target_id}"),
        ("POST", "/api/v1/messages/outbox/{envelope_id}/amendments"),
        ("GET", "/api/v1/messages/{envelope_id}/amendments"),
        ("GET", "/api/v1/messages/drafts"), ("POST", "/api/v1/messages/drafts"),
        ("GET", "/api/v1/messages/drafts/{draft_id}"), ("PUT", "/api/v1/messages/drafts/{draft_id}"),
        ("DELETE", "/api/v1/messages/drafts/{draft_id}"),
        ("POST", "/api/v1/messages/drafts/{draft_id}/restore"),
        ("POST", "/api/v1/messages/drafts/{draft_id}/send"),
    }:
        return "relationship_scoped", "messaging.user_messages.exchange", None
    messaging_global_operations = {
        ("GET", "/api/v1/messages/capabilities"),
        ("GET", "/api/v1/messages/recipients/{kind}"),
        ("POST", "/api/v1/messages/recipients/validate"),
        ("POST", "/api/v1/messages/send"),
    }
    if (method, path) in messaging_global_operations:
        return "globally_privileged", "messaging.user_messages.exchange", None
    if method == "GET" and path in {
        "/api/v1/messages/resources/{kind}", "/api/v1/messages/outbox",
        "/api/v1/messages/outbox/{envelope_id}",
        "/api/v1/messages/outbox/{envelope_id}/recipients",
    }:
        return "relationship_scoped", "messaging.user_messages.exchange", None
    if (method, path) in {
        ("GET", "/api/v1/messages/inbox"),
        ("GET", "/api/v1/messages/inbox/{delivery_id}"),
        ("GET", "/api/v1/messages/catch-up"),
        ("GET", "/api/v1/messages/unread-count"),
        ("POST", "/api/v1/messages/inbox/{delivery_id}/read"),
    }:
        # Owner-scoped; exchange is conditional on human versus system content.
        return "relationship_scoped", None, None
    if path.startswith("/api/v1/internal/text-indexing/"):
        return "service_lease_scoped", "content.index.execute", None
    if path == "/api/v1/full-text-search":
        return "resource_scoped", "record.view", "record.view"
    if path in {"/api/v1/preferences", "/api/v1/i18n/bootstrap"}:
        return "authenticated_only", None, None
    if path.startswith("/api/v1/i18n/catalogues/"):
        return "authenticated_only", None, None
    if path.startswith("/api/v1/admin/i18n/"):
        return "globally_privileged", "localization.administer", None
    if path.startswith("/api/v1/entity-translations/"):
        entity_privileges = {
            "classification-schemes": "classification_scheme.modify_metadata",
            "classifications": "classification.modify_metadata",
            "users": "user.modify_metadata",
            "roles": "role.modify_metadata",
            "org-units": "org_unit.modify_metadata",
            "security-levels": "security_level.modify_metadata",
            "profiles": "profile.modify_metadata",
        }
        entity_type = path.split("/")[4]
        privilege = entity_privileges.get(entity_type)
        if privilege is None:
            raise ValueError(f"{method} {path} has no approved entity translation privilege")
        return "globally_privileged", privilege, None
    if path.startswith("/api/v1/saved-searches"):
        if method == "POST" and path == "/api/v1/saved-searches":
            return "globally_privileged", "search.saved_search.save", None
        if path == "/api/v1/saved-searches/administration":
            return "globally_privileged", "search.saved_search.administer", None
        if method == "DELETE":
            return "relationship_scoped", None, None
        return "relationship_scoped", None, None
    if method == "GET" and path == "/api/v1/number-suggestions/{resource}":
        # The resource path parameter selects the creation privilege at runtime:
        # record.create, or aggregation.create_root/aggregation.create_child.
        # Parent-derived suggestions additionally require visibility of that
        # parent, so this cannot be represented by one static privilege field.
        return "relationship_scoped", None, None
    if path.startswith("/api/v1/content-indexing/"):
        return "resource_scoped", "record.component.view", "record.component.view"
    if path.endswith("/reindex"):
        return "resource_scoped", "record.component.reindex", "record.component.view"
    if path.endswith("/indexing-status"):
        return "resource_scoped", "record.component.view", "record.component.view"
    if path.startswith("/api/v1/auth/"):
        if "/users/" in path or path in {"/api/v1/auth/sessions", "/api/v1/auth/sessions/page"}:
            return "globally_privileged", "identity.sessions.administer", None
        return "authenticated_only", None, None
    if path.startswith("/api/v1/text-indexers"):
        return "globally_privileged", "identity.text_indexers.administer", None
    if path.startswith("/api/v1/holds"):
        if method in {"POST", "PATCH", "DELETE", "PUT"} and not "/held-items" in path:
            return "globally_privileged", "holds.administer", None
        return "relationship_scoped", None, None
    if path.startswith(("/api/v1/aggregations/", "/api/v1/records/")) and (
        path.endswith("/effective-holds") or "/holds" in path
    ):
        resource_type = "aggregation" if path.startswith("/api/v1/aggregations/") else "record"
        return "resource_scoped", f"{resource_type}.view", f"{resource_type}.view"
    if path.startswith("/api/v1/event-history") or path.endswith("/history"):
        permission = None
        if path.startswith("/api/v1/aggregations/"):
            permission = "aggregation.history.view"
        elif path.startswith("/api/v1/records/") or path.startswith("/api/v1/digital-components/"):
            permission = "record.history.view"
        return ("resource_scoped" if permission else "globally_privileged", "audit.view", permission)
    reference_operations = {
        ("GET", "/api/v1/users"),
        ("POST", "/api/v1/users/search"),
        ("GET", "/api/v1/users/{user_id}"),
        ("GET", "/api/v1/roles"),
        ("POST", "/api/v1/roles/search"),
        ("GET", "/api/v1/roles/{role_id}"),
        ("GET", "/api/v1/org-units"),
        ("POST", "/api/v1/org-units/search"),
        ("GET", "/api/v1/org-units/{org_unit_id}"),
        ("GET", "/api/v1/profiles/reference"),
        ("GET", "/api/v1/classification-schemes"),
        ("POST", "/api/v1/classification-schemes/search"),
        ("GET", "/api/v1/classification-schemes/{scheme_id}"),
        ("GET", "/api/v1/classifications"),
        ("POST", "/api/v1/classifications/search"),
        ("GET", "/api/v1/classifications/recent"),
        ("GET", "/api/v1/classifications/{classification_id}"),
        ("GET", "/api/v1/classifications/{classification_id}/retention-rule"),
        ("GET", "/api/v1/classifications/{classification_id}/effective-retention-rule"),
    }
    if (method, path) in reference_operations:
        return "authenticated_only", None, None
    authenticated_operations = {
        ("GET", "/api/v1/authorization/explainable-users"),
        ("GET", "/api/v1/creation-role-options"),
        ("GET", "/api/v1/dashboard/ownership-counts"),
        ("GET", "/api/v1/dashboard/reviews"),
        ("GET", "/api/v1/dashboard/summary"),
    }
    if (method, path) in authenticated_operations:
        return "authenticated_only", None, None
    if path.startswith("/api/v1/users"):
        if "/api-credentials" in path:
            return "globally_privileged", "identity.text_indexers.administer", None
        return "globally_privileged", "identity.users.administer", None
    if path == "/api/v1/authorization/explain":
        return "resource_scoped", "authorization.explain", None
    if path == "/api/v1/{resource}/{resource_id}/acl-contextual-principals":
        # Organization disclosure plus resource-type-specific ACL management.
        return "resource_scoped", "organization.browse", None
    if path == "/api/v1/authorization/governance-custody":
        return "globally_privileged", "authorization.administer", None
    if path == "/api/v1/security-operations/summary":
        return "globally_privileged", "audit.view", None
    if path == "/api/v1/security-operations/reconciliation":
        return "globally_privileged", "authorization.administer", None
    if path.startswith(("/api/v1/profiles", "/api/v1/privileges")) or "/profile" in path:
        return "globally_privileged", "authorization.administer", None
    if method == "GET" and path == "/api/v1/permissions":
        # The resource_type query parameter selects an alternative global
        # privilege; there is no resource-instance ACL gate for this catalogue.
        return "relationship_scoped", None, None
    if path.startswith(("/api/v1/roles", "/api/v1/org-units", "/api/v1/user-role-assignments")):
        return "globally_privileged", "organization.administer", None
    if method == "GET" and path == "/api/v1/classifications/{classification_id}/path":
        return "authenticated_only", None, None
    if path.startswith(("/api/v1/classification-schemes", "/api/v1/classifications")):
        return "globally_privileged", "classifications.administer", None
    if method == "GET" and path.startswith("/api/v1/security-levels"):
        return "authenticated_only", None, None
    if path.startswith("/api/v1/security-level-changes"):
        return "resource_scoped", None, None
    if path.startswith("/api/v1/security-levels"):
        return "globally_privileged", "security_levels.administer", None
    if path.startswith("/api/v1/browse/organization"):
        return "globally_privileged", "organization.browse", None
    if path.startswith("/api/v1/favourites"):
        return "authenticated_only", None, None
    if path == "/api/v1/ownership-correction-options" or "ownership-correction" in path or path.endswith("/correct-ownership"):
        return "governance_exception", "organization.ownership.correct", None
    if path.startswith("/api/v1/aggregations/") and "permissions" in path:
        return "resource_scoped", "authorization.administer", "aggregation.acl.manage"
    if path.startswith("/api/v1/records/") and path.endswith("permissions"):
        return "resource_scoped", "authorization.administer", "record.acl.manage"
    if path.startswith("/api/v1/aggregations/") and "/acl-move" in path:
        return "resource_scoped", "aggregation.move", "aggregation.move"
    if path.startswith("/api/v1/records/") and "/acl-move" in path:
        return "resource_scoped", "record.move", "record.move"

    if path.startswith("/api/v1/record-drafts"):
        if path.endswith("/commit-placement-correction"):
            return "resource_scoped", "record.create", "aggregation.add_record"
        if path.endswith("/commit"):
            return "resource_scoped", "record.create", "aggregation.add_record"
        return "resource_scoped", "record.create", None

    if "digital-components" in path:
        if path.endswith("/rendition"):
            return "resource_scoped", "record.component.view", "record.component.view"
        if method == "GET" and path.endswith("/content"):
            return "resource_scoped", "record.component.download", "record.component.download"
        if method == "PUT" and path.endswith("/content"):
            return "resource_scoped", "record.component.replace", "record.component.replace"
        if method == "DELETE" and path.endswith("/content"):
            return "resource_scoped", "record.component.remove", "record.component.remove"
        if path.endswith("/order") or path.endswith("/move"):
            return "resource_scoped", "record.component.reorder", "record.component.reorder"
        if method == "POST" and (path.endswith("/upload") or path.endswith("/components")):
            return "resource_scoped", "record.component.add", "record.component.add"
        if method == "DELETE":
            return "resource_scoped", "record.component.remove", "record.component.remove"
        if method == "PATCH":
            return "resource_scoped", "record.component.replace", "record.component.replace"
        if method == "POST":
            return "resource_scoped", "record.component.add", "record.component.add"
        return "resource_scoped", "record.view", "record.component.list"

    if path.startswith("/api/v1/records"):
        if method == "POST" and path == "/api/v1/records":
            return "resource_scoped", "record.create", "aggregation.add_record"
        if path.endswith("/correct-placement"):
            return "resource_scoped", "closure.correct_record_placement", "record.move"
        mapping = {
            "GET": ("record.view", "record.view"),
            "PATCH": ("record.modify", "record.modify_metadata"),
            "DELETE": ("record.delete", "record.delete"),
            "POST": ("record.view", "record.view"),
        }
        privilege, permission = mapping[method]
        return "resource_scoped", privilege, permission

    if path.startswith("/api/v1/aggregations") or path.startswith("/api/v1/browse/"):
        if "retention-rule" in path:
            privilege = "classifications.administer" if method != "GET" else "aggregation.view"
            return "resource_scoped", privilege, "aggregation.view"
        if method == "POST" and path == "/api/v1/aggregations":
            return "resource_scoped", "aggregation.create_root", None
        mapping = {
            "GET": ("aggregation.view", "aggregation.view"),
            "PATCH": ("aggregation.modify", "aggregation.modify_metadata"),
            "DELETE": ("aggregation.delete", "aggregation.delete"),
            "POST": ("aggregation.view", "aggregation.view"),
        }
        privilege, permission = mapping[method]
        return "resource_scoped", privilege, permission
    raise ValueError(
        f"API operation {method} {path} has no explicit policy classification"
    )


def api_operations() -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for path, path_item in app.openapi()["paths"].items():
        if path not in {"/health"} and not path.startswith("/api/v1/"):
            continue
        for method, definition in path_item.items():
            if method not in HTTP_METHODS:
                continue
            upper_method = method.upper()
            target_class, privilege, permission = _target_policy(upper_method, path)
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
                    "current_access_class": (
                        target_class if target_class == "globally_privileged"
                        else _current_access(upper_method, path)
                    ),
                    "target_policy_class": target_class,
                    "global_privilege": privilege,
                    "resource_permission": permission,
                    **({"conditional_global_privileges": {
                        "query_parameter": "resource_type",
                        "match": "any",
                        "when_omitted": ["authorization.administer"],
                        "by_value": {
                            "aggregation": ["authorization.administer", "aggregation.acl.manage"],
                            "record": ["authorization.administer", "record.acl.manage"],
                        },
                    }} if (upper_method, path) == ("GET", "/api/v1/permissions") else {}),
                    **({"conditional_resource_authorization": {
                        "path_parameter": "resource",
                        "by_value": {
                            "aggregations": {"global_privilege": "aggregation.acl.manage", "resource_permission": "aggregation.acl.manage"},
                            "records": {"global_privilege": "record.acl.manage", "resource_permission": "record.acl.manage"},
                        },
                    }} if path == "/api/v1/{resource}/{resource_id}/acl-contextual-principals" else {}),
                    "phase_0_enforced": False,
                    "phase_4_enforced": target_class == "globally_privileged",
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
        "access_classes": [
            "public",
            "authenticated_only",
            "system_administrator",
            "globally_privileged",
            "resource_scoped",
            "relationship_scoped",
            "governance_exception",
            "service_lease_scoped",
        ],
        "api_operations": api_operations(),
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(build_inventory(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
