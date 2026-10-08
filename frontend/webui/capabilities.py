from __future__ import annotations

from collections.abc import Iterable, Mapping


NAVIGATION_PRIVILEGES = {
    "relationship-types": "relationships.administer",
    "messages-monitor": "messaging.monitor",
    "messages-notifications": "messaging.notifications.administer",
    "messages-outbox": "messaging.user_messages.exchange",
    "messages-drafts": "messaging.user_messages.exchange",
    "aggregations": "aggregation.view",
    "records": "record.view",
    "classification-schemes": "classifications.administer",
    "org-units": "organization.administer",
    "roles": "organization.administer",
    "users": "identity.users.administer",
    "text-indexers": "identity.text_indexers.administer",
    "organization-browser": "organization.browse",
    "audit-trail": "audit.view",
    "login-sessions": "identity.sessions.administer",
    "security-levels": "security_levels.administer",
    "profiles": "authorization.administer",
    "governance-custody": "authorization.administer",
    "security-operations": "audit.view",
    "saved-search-administration": "search.saved_search.administer",
    "translations": "localization.administer",
}


def can_navigate(navigation_key: str, privileges: Iterable[str]) -> bool:
    if navigation_key == "advanced-search":
        granted = set(privileges)
        return bool({"aggregation.view", "record.view"} & granted)
    required = NAVIGATION_PRIVILEGES.get(navigation_key)
    return required is None or required in set(privileges)


def can_add_from_collection(resource_key: str, privileges: Iterable[str]) -> bool:
    """Return whether a collection page should offer its shared Add action."""
    granted = set(privileges)
    if resource_key == "aggregations":
        return bool({"aggregation.create_root", "aggregation.create_child"} & granted)
    if resource_key == "records":
        return "record.create" in granted
    return resource_key not in {"privileges", "permissions"}


def can_open_organization_detail(entity_type: str, privileges: Iterable[str]) -> bool:
    """Return whether a browser summary may offer its administrative detail page."""
    destination = {
        "org_unit": "org-units",
        "role": "roles",
        "user": "users",
    }.get(entity_type)
    return destination is not None and can_navigate(destination, privileges)


def dashboard_administration_resources(privileges: Iterable[str]) -> tuple[str, ...]:
    granted = set(privileges)
    resources: list[str] = []
    if "classifications.administer" in granted:
        resources.extend(("classification-schemes", "classifications"))
    if "organization.administer" in granted:
        resources.extend(("org-units", "roles"))
    if "identity.users.administer" in granted:
        resources.append("users")
    return tuple(resources)


def capability_allowed(capabilities: Mapping[str, bool] | None, name: str) -> bool:
    """Draft-only callers may omit capabilities; governed responses fail closed."""
    return capabilities is None or capabilities.get(name) is True
