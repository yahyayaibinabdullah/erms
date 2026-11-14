"""Resolve only references needed by the current collection page."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Any, Callable

@dataclass(frozen=True)
class RowHydrators:
    rows_by_id: Callable
    closure_flags: Callable
    org_unit_context: Callable

def build_row_hydrators(api: Any):
    async def rows_by_id(resource: str, identifiers: set[int | None]) -> dict[int, dict[str, Any]]:
        wanted = sorted({int(value) for value in identifiers if value is not None})
        if not wanted:
            return {}
        resolved = await asyncio.gather(*(api.get(resource, value) for value in wanted))
        return {int(item["id"]): item for item in resolved}


    async def closure_flags(items: list[dict[str, Any]], field: str) -> dict[int, bool]:
        identifiers = sorted({int(item[field]) for item in items if item.get(field) is not None})
        closures = await asyncio.gather(*(
            api.effective_aggregation_closure(identifier) for identifier in identifiers
        ))
        return {
            identifier: closure is not None
            for identifier, closure in zip(identifiers, closures)
        }


    async def org_unit_context(
        identifiers: set[int | None],
    ) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        pending = {int(value) for value in identifiers if value is not None}
        while pending:
            batch = await rows_by_id("org-units", pending - set(result))
            if not batch:
                break
            result.update(batch)
            pending = {
                int(item["parent_org_unit_id"])
                for item in batch.values()
                if item.get("parent_org_unit_id") is not None
                and int(item["parent_org_unit_id"]) not in result
            }
        return result

    return RowHydrators(rows_by_id, closure_flags, org_unit_context)

