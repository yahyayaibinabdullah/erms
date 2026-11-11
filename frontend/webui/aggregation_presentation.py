"""Existing aggregation labels, closure lookup and layout constants."""
from __future__ import annotations
from typing import Any
from .i18n_catalogue import render_message

CHILD_AGGREGATION_CLASSIFICATION_HELP = (
    render_message("webui.module.text.child_aggregations_inherit_classification_d422f011")
)


AGGREGATION_SUMMARY_LAYOUT_CLASSES = (
    "detail-surface aggregation-command-summary shadow-none flex-1 min-w-[520px] p-5 gap-4"
)


def direct_classification_label(classification_path: list[dict[str, Any]]) -> str:
    """Format only the classification directly assigned to the aggregation."""
    if not classification_path:
        return "—"
    classification = classification_path[-1]
    return f"{classification['code']} — {classification['title']}"


def effective_closure(
    aggregation: dict[str, Any] | None,
    aggregations_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    """Return the nearest directly closed aggregation, including the item itself."""
    current = aggregation
    seen: set[int] = set()
    while current and current.get("id") not in seen:
        seen.add(current["id"])
        if current.get("date_closed"):
            return current
        current = aggregations_by_id.get(current.get("parent_aggregation_id"))
    return None
