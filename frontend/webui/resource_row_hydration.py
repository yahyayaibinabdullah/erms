"""Bounded collection row hydration and existing record component enrichment."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
import asyncio
from .classification_editor import decorate_classifications
from .organization_collections import decorate_organization_rows
from .resource_row_presentation import decorate_relationship_rows
from .resource_row_presentation import relationship_cell

def build_resource_row_hydration(
    *, api, get_row_hydrators, medium_label, review_display,
):
    async def decorate_for_spec(
        spec: EntitySpec,
        rows: list[dict[str, Any]],
        *,
        aggregation_rows: list[dict[str, Any]] | None = None,
        related_rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        rows_by_id = get_row_hydrators().rows_by_id
        closure_flags = get_row_hydrators().closure_flags
        org_unit_context = get_row_hydrators().org_unit_context



        if spec.key == "classifications":
            return await decorate_classifications(rows, rows_by_id=rows_by_id, relationship_cell=relationship_cell)
        if spec.key == "aggregations":
            closed_by_id = await closure_flags(rows, "id")
            return [
                {
                    **item,
                    "medium_display": medium_label(item.get("medium")),
                    "vital_display": "Vital" if item.get("is_vital") else "Contains vital resources" if item.get("has_vital_descendants") else "Not vital",
                    "review_display": review_display(item.get("date_of_next_review")),
                    "location_display": item.get("effective_current_location") or item.get("effective_assigned_location") or "Unknown",
                    "_effectively_closed": closed_by_id.get(int(item["id"]), False),
                    "_directly_closed": bool(item.get("date_closed")),
                }
                for item in rows
            ]
        if spec.key in {"org-units", "roles", "users"}:
            return await decorate_organization_rows(
                spec, rows, org_unit_context=org_unit_context, rows_by_id=rows_by_id,
                decorate_relationship_rows=decorate_relationship_rows, relationship_cell=relationship_cell,
            )
        if spec.key == "records":
            aggregations_by_id = await rows_by_id(
                "aggregations", {item.get("aggregation_id") for item in rows},
            )
            closed_by_id = await closure_flags(rows, "aggregation_id")
            decorated = decorate_relationship_rows(
                spec.key, rows, list(aggregations_by_id.values()),
            )
            return [
                {
                    **item,
                    "medium_display": medium_label(item.get("medium")),
                    "vital_display": "Vital" if item.get("is_vital") else "Not vital",
                    "review_display": review_display(item.get("date_of_next_review")),
                    "location_display": item.get("effective_current_location") or item.get("effective_assigned_location") or "Unknown",
                    "_effectively_closed": closed_by_id.get(
                        int(item["aggregation_id"]), False,
                    ),
                }
                for item in decorated
            ]
        return rows


    async def decorate_record_search_components(
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        async def context(record: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            try:
                capabilities = await api.resource_capabilities("records", int(record["id"]))
                components = (
                    (await api.component_page(int(record["id"]), limit=25))["items"]
                    if capabilities.get("list_components") else []
                )
                return capabilities, components
            except ApiError:
                return {}, []

        contexts = await asyncio.gather(*(context(record) for record in rows))
        return [
            {
                **record,
                "_record_capabilities": capabilities,
                "_components": components,
            }
            for record, (capabilities, components) in zip(rows, contexts)
        ]


    return decorate_for_spec, decorate_record_search_components
