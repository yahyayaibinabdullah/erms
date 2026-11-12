"""Shared record and aggregation compact result paging, expansions and anchors."""
from __future__ import annotations
from typing import Any
from .entities import EntitySpec
from .i18n_catalogue import render_message
from nicegui import ui

def build_resource_collection_results(
    *, collection_state, guidance, load_rows, open_aggregation, render_compact_resource_result, restore_compact_result_anchor, show_record_details,
):
    def render_entity_compact_results(spec: EntitySpec) -> None:
        resource = spec.key
        result_state = collection_state["entity_result_states"][resource]
        result_state["expanded_results"] = set(result_state.get("expanded_results") or [])

        ui.separator().classes("erms-results-divider")
        with ui.row().classes("w-full items-center px-5 pt-2 gap-2"):
            ui.icon("search", color="primary")
            ui.label(render_message("webui.render_entity_compact_results.label.search_results_66d40806")).classes("text-lg font-semibold")
            count = ui.badge(str(result_state["total"]), color="blue-grey").props("outline")

        controls = ui.row().classes("w-full items-end gap-3 px-5 pt-2 flex-wrap")
        with controls:
            filter_control = ui.input(
                render_message("webui.render_entity_compact_results.input.filter_results_bb36c793"), value=result_state.get("filter", ""),
            ).props("outlined dense clearable debounce=200").classes("grow min-w-[250px]")
            sort_control = ui.select(
                {"number": render_message("webui.render_entity_compact_results.select.number_13b108c8"), "title": render_message("webui.render_entity_compact_results.select.title_c402fbea"), "date": render_message("webui.render_entity_compact_results.select.date_originated_66ee2579") if resource == "records" else render_message("webui.render_entity_compact_results.select.date_opened_8e338da3"), "medium": render_message("webui.render_entity_compact_results.select.medium_d8693777")},
                value=result_state.get("sort", "number"), label=render_message("webui.render_entity_compact_results.select.sort_by_26eae3a9"),
            ).props("outlined dense options-dense").classes("w-44")
            page_size_control = ui.select(
                {10: "10", 25: "25", 50: "50", 100: "100"},
                value=int(result_state.get("page_size", 10)), label=render_message("webui.render_entity_compact_results.select.per_page_d6d26cbd"),
            ).props("outlined dense options-dense").classes("w-28")
        summary = ui.label().classes("text-sm text-slate-500 px-5")
        host = ui.column().classes("compact-result-list w-[calc(100%-2.5rem)] mx-5 gap-0")
        pager = ui.row().classes("w-full items-center justify-center gap-2 px-5 pb-5")
        with pager:
            first = ui.button(icon="first_page").props('flat round aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.first_page_99404add"))).tooltip(render_message("webui.render_entity_compact_results.tooltip.first_page_36860f7f"))
            previous = ui.button(icon="chevron_left").props('flat round aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.previous_page_2ba84275"))).tooltip(render_message("webui.render_entity_compact_results.tooltip.previous_page_e175a9ce"))
            page_label = ui.label().classes("text-sm text-slate-600 min-w-20 text-center")
            next_button = ui.button(icon="chevron_right").props('flat round aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.next_page_66adc3fc"))).tooltip(render_message("webui.render_entity_compact_results.tooltip.next_page_e62c6c59"))
            last = ui.button(icon="last_page").props('flat round aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.last_page_9a6fde18"))).tooltip(render_message("webui.render_entity_compact_results.tooltip.last_page_00e9ef30"))

        async def open_result(item: dict[str, Any]) -> None:
            result_state["return_anchor"] = f"compact-result-{resource}-{int(item['id'])}"
            if resource == "aggregations":
                await open_aggregation(item)
            else:
                await show_record_details(item)

        def render_results() -> None:
            nonlocal result_state
            result_state = collection_state["entity_result_states"][resource]
            total = result_state["total"]
            page_size = result_state["page_size"]
            page_count = max(1, (total + page_size - 1) // page_size)
            page_number = result_state["page"]
            start = (page_number - 1) * page_size
            page_rows = collection_state["rows"]
            count.text = str(total)
            if result_state.get("unclassified_roots"):
                guidance.text = render_message("webui.show_unclassified_roots.text.showing_row_count_of_total_unclassified_ro_823f8b47", row_count=len(page_rows), total=total)
            summary.text = render_message("webui.render_results.text.showing_value_value_2_of_row_count_results_3d5b1825", value=start + 1 if page_rows else 0, value_2=start + len(page_rows), row_count=total)
            page_label.text = render_message("webui.render_results.text.page_page_number_of_page_count_1680e7c0", page_number=page_number, page_count=page_count)
            first.set_enabled(page_number > 1); previous.set_enabled(page_number > 1)
            next_button.set_enabled(page_number < page_count); last.set_enabled(page_number < page_count)
            host.clear()
            with host:
                if not page_rows:
                    ui.label(render_message("webui.render_results.label.no_matching_results_e67e2811")).classes("w-full text-center text-slate-500 py-8")
                for item in page_rows:
                    capabilities = item.get("_record_capabilities") or {}
                    render_compact_resource_result(
                        resource, item, on_open=open_result,
                        component_total=int(capabilities.get("component_count", 0)), show_medium=True,
                        can_preview=bool(capabilities.get("has_previewable_component")),
                        can_expand_components=bool(capabilities.get("list_components")),
                        initially_expanded=f"{resource}:{int(item['id'])}" in result_state["expanded_results"],
                        on_expansion_changed=lambda expanded, identifier=int(item["id"]): (
                            result_state["expanded_results"].add(f"{resource}:{identifier}") if expanded
                            else result_state["expanded_results"].discard(f"{resource}:{identifier}")
                        ),
                    )
            restore_compact_result_anchor(result_state.pop("return_anchor", None))

        request_revision = 0
        pending_revision = None

        async def load_page(page_number: int, **changes) -> None:
            nonlocal request_revision, pending_revision
            if host.is_deleted or (pending_revision is not None and not changes):
                return
            request_revision += 1
            revision = pending_revision = request_revision
            try:
                await load_rows(
                    compact_state={**result_state, **changes, "page": page_number},
                    on_loaded=render_results, is_current=lambda: not host.is_deleted,
                )
            finally:
                if pending_revision == revision:
                    pending_revision = None

        def set_page(page_number: int):
            return load_page(max(1, page_number))

        async def change_controls() -> None:
            await load_page(1, filter=str(filter_control.value or ""),
                            sort=sort_control.value, page_size=int(page_size_control.value or 10))

        filter_control.on_value_change(change_controls)
        sort_control.on_value_change(change_controls)
        page_size_control.on_value_change(change_controls)
        first.on("click", lambda: set_page(1))
        previous.on("click", lambda: set_page(result_state["page"] - 1))
        next_button.on("click", lambda: set_page(result_state["page"] + 1))
        last.on("click", lambda: set_page((result_state["total"] + result_state["page_size"] - 1) // result_state["page_size"]))
        render_results()


    return render_entity_compact_results
