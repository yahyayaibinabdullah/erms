"""Existing record/resource presentation and editor rules."""
from __future__ import annotations
from typing import Any
from .entity_editor_controls import medium_options

def record_draft_component_context(
    aggregation_id: Any, medium: Any,
) -> dict[str, Any]:
    """Return the persisted draft context required before staging content."""
    if aggregation_id in (None, "") or medium in (None, ""):
        raise ValueError(
            "Select the parent aggregation and record medium before adding digital files."
        )
    return {"aggregation_id": int(aggregation_id), "medium": str(medium)}


def configure_record_medium(controls, lookup_rows_by_field):
    aggregation_rows = lookup_rows_by_field.get("aggregation_id", [])

    def constrain_edited_record_medium() -> None:
        parent = next(
            (item for item in aggregation_rows
             if item["id"] == controls["aggregation_id"].value),
            None,
        )
        medium_control = controls["medium"]
        if not parent:
            return
        parent_medium = parent.get("medium", "mixed")
        if parent_medium == "mixed":
            medium_control.set_options(
                medium_options(), value=medium_control.value or "mixed",
            )
            medium_control.enable()
        else:
            medium_control.set_options(
                {parent_medium: medium_options()[parent_medium]}, value=parent_medium,
            )
            medium_control.disable()
        medium_control.update()

    controls["aggregation_id"].on_value_change(
        lambda _: constrain_edited_record_medium()
    )
    constrain_edited_record_medium()
