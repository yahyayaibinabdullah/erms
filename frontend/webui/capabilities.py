from __future__ import annotations

from collections.abc import Iterable, Mapping


NAVIGATION_PRIVILEGES = {
    "disposition-eligibility": "disposition.jobs.manage",
    "disposition-jobs": "disposition.jobs.manage",
    "disposition-templates": "disposition.jobs.manage",
    "application-settings": "app.settings.manage",
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


def can_edit_entity_translation(resource_key: str, privileges: Iterable[str]) -> bool:
    """Match the locale-scoped API's specified metadata right, not navigation."""
    required = {
        "classification-schemes": "classification_scheme.modify_metadata",
        "classifications": "classification.modify_metadata",
        "users": "identity.users.administer",
        "roles": "role.modify_metadata",
        "org-units": "org_unit.modify_metadata",
        "security-levels": "security_level.modify_metadata",
        "profiles": "profile.modify_metadata",
    }.get(resource_key)
    return required is not None and required in set(privileges)


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


def can_navigate_disposition(navigation_key: str, principal: Mapping | None) -> bool:
    """Use server-derived, current role eligibility; missing capabilities fail closed."""
    principal = principal or {}
    if navigation_key == "disposition-tasks":
        return principal.get("can_access_disposition_tasks") is True
    if navigation_key == "disposition-templates":
        return principal.get("can_manage_disposition_templates") is True
    if navigation_key in {"disposition-eligibility", "disposition-jobs"}:
        return principal.get("can_manage_disposition") is True
    return True
