"""Shared navigation presentation and pure operations for the in-app trail."""
from typing import Any

NAVIGATION_TRAIL_LIMIT = 20
NAVIGATION_VISIBLE_LIMIT = 5

# Sidebar entries and the authenticated page heading use the same glyphs.
PAGE_ICONS = {
    "dashboard": "dashboard",
    "advanced-search": "manage_search",
    "full-text-search": "search",
    "aggregations": "folder",
    "aggregation-details": "folder",
    "records": "description",
    "record-details": "description",
    "classification-schemes": "account_tree",
    "classification-workspace": "account_tree",
    "classification-scheme-details": "account_tree",
    "classification-details": "schema",
    "relationship-types": "link",
    "disposition-tasks": "task_alt",
    "disposition-task": "task_alt",
    "disposition-eligibility": "event_available",
    "disposition-jobs": "work_outline",
    "disposition-job": "work_outline",
    "disposition-templates": "description",
    "messages-inbox": "inbox",
    "messages-outbox": "outbox",
    "messages-drafts": "drafts",
    "messages-monitor": "monitor_heart",
    "messages-notifications": "notifications",
    "organization-browser": "lan",
    "org-units": "corporate_fare",
    "org-unit-details": "corporate_fare",
    "roles": "badge",
    "role-details": "badge",
    "users": "group",
    "user-details": "person",
    "audit-trail": "manage_history",
    "login-sessions": "devices",
    "security-operations": "monitor_heart",
    "saved-search-administration": "manage_search",
    "security-levels": "security",
    "profiles": "admin_panel_settings",
    "privileges": "key",
    "permissions": "verified_user",
    "governance-custody": "shield_person",
    "holds": "gavel",
    "hold-details": "gavel",
    "text-indexers": "manage_search",
    "text-indexer-details": "manage_search",
    "translations": "translate",
    "application-settings": "settings",
}


def navigation_entry_identity(entry: dict[str, Any]) -> tuple[str, int | None]:
    return str(entry["page"]), entry.get("entity_id")


def append_navigation_entry(
    trail: list[dict[str, Any]], entry: dict[str, Any],
    *, limit: int = NAVIGATION_TRAIL_LIMIT,
) -> list[dict[str, Any]]:
    """Append a page visit, collapsing only a consecutive logical duplicate."""
    updated = [dict(item) for item in trail]
    if updated and navigation_entry_identity(updated[-1]) == navigation_entry_identity(entry):
        updated[-1] = {**updated[-1], **entry}
    else:
        updated.append(dict(entry))
    return updated[-limit:]


def visible_navigation_indices(
    length: int, *, limit: int = NAVIGATION_VISIBLE_LIMIT,
) -> tuple[list[int], list[int]]:
    """Return visible and overflow indices while retaining first and recent pages."""
    if length <= limit:
        return list(range(length)), []
    recent_count = max(1, limit - 2)
    visible = [0, *range(length - recent_count - 1, length)]
    visible = sorted(set(visible))
    hidden = [index for index in range(length) if index not in visible]
    return visible, hidden
