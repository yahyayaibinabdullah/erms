"""Existing aggregation behavior with explicit view dependencies."""
from __future__ import annotations
from typing import Any, Callable

def build_aggregation_toolbar(
    *, aggregation_state, open_aggregation, open_editor, open_record_draft_editor,
):
    async def add_for_current_context() -> None:
        current = aggregation_state.get("aggregation_detail")
        if not current:
            await open_editor()
            return

        async def refresh_parent(_: dict[str, Any]) -> None:
            await open_aggregation(current)

        await open_editor(
            initial_values={"parent_aggregation_id": current["id"]},
            locked_fields={"parent_aggregation_id"},
            on_saved=refresh_parent, resource_key="aggregations",
        )


    async def add_record_for_current_aggregation() -> None:
        current = aggregation_state.get("aggregation_detail")
        if current is None:
            return

        async def refresh_parent(_: dict[str, Any]) -> None:
            await open_aggregation(current)

        await open_record_draft_editor(
            target_aggregation_id=current["id"], on_committed=refresh_parent,
        )


    return add_for_current_context, add_record_for_current_aggregation
