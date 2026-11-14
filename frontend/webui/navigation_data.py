"""Pure data operations for the existing in-app navigation trail."""
from typing import Any

NAVIGATION_TRAIL_LIMIT = 20
NAVIGATION_VISIBLE_LIMIT = 5


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
