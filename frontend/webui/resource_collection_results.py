"""Shared record and aggregation compact result paging, expansions and anchors."""
from __future__ import annotations
from typing import Any
from .component_presentation import component_is_previewable
from .i18n_catalogue import render_message
from nicegui import ui

def build_resource_collection_results(
    *, collection_state, open_aggregation, render_compact_resource_result, restore_compact_result_anchor, show_record_details,
):
    def render_entity_compact_results(spec: EntitySpec) -> None:
        resource = spec.key
        result_state = collection_state.setdefault("entity_result_states", {}).setdefault(resource, {
            "filter": "", "sort": "number", "page": 1, "page_size": 10,
            "expanded_results": set(), "return_anchor": None,
        })
        result_state["expanded_results"] = set(result_state.get("expanded_results") or [])
        number_field = "aggregation_number" if resource == "aggregations" else "record_number"

        ui.separator().classes("erms-results-divider")
        with ui.row().classes("w-full items-center px-5 pt-2 gap-2"):
            ui.icon("search", color="primary")
            ui.label(render_message("webui.render_entity_compact_results.label.search_results_66d40806")).classes("text-lg font-semibold")
            ui.badge(str(len(collection_state["rows"])), color="blue-grey").props("outline")

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
            query = str(filter_control.value or "").strip().casefold()
            result_state.update(filter=str(filter_control.value or ""), sort=sort_control.value,
                                page_size=int(page_size_control.value or 10))
            rows = list(collection_state["rows"])
            if query:
                rows = [row for row in rows if query in " ".join(str(value or "") for value in (
                    row.get(number_field), row.get("title"), row.get("medium"),
                    (row.get("aggregation_display") or {}).get("code"),
                    (row.get("aggregation_display") or {}).get("name"),
                )).casefold()]
            sort_field = {"number": number_field, "title": "title", "date": "date_originated" if resource == "records" else "date_opened", "medium": "medium"}[sort_control.value]
            rows.sort(key=lambda row: str(row.get(sort_field) or "").casefold())
            page_size = int(page_size_control.value or 10)
            page_count = max(1, (len(rows) + page_size - 1) // page_size)
            result_state["page"] = min(max(1, int(result_state.get("page", 1))), page_count)
            page_number = result_state["page"]
            start = (page_number - 1) * page_size
            page_rows = rows[start:start + page_size]
            summary.text = render_message("webui.render_results.text.showing_value_value_2_of_row_count_results_3d5b1825", value=start + 1 if page_rows else 0, value_2=start + len(page_rows), row_count=len(rows))
            page_label.text = render_message("webui.render_results.text.page_page_number_of_page_count_1680e7c0", page_number=page_number, page_count=page_count)
            first.set_enabled(page_number > 1); previous.set_enabled(page_number > 1)
            next_button.set_enabled(page_number < page_count); last.set_enabled(page_number < page_count)
            host.clear()
            with host:
                if not page_rows:
                    ui.label(render_message("webui.render_results.label.no_matching_results_e67e2811")).classes("w-full text-center text-slate-500 py-8")
                for item in page_rows:
                    capabilities = item.get("_record_capabilities") or {}
                    components = item.get("_components") or []
                    render_compact_resource_result(
                        resource, item, on_open=open_result,
                        components=components, show_medium=True,
                        can_preview=bool(resource == "records" and capabilities.get("view_component") and any(component_is_previewable(component) for component in components)),
                        can_expand_components=bool(resource == "records" and capabilities.get("list_components") and components),
                        initially_expanded=f"{resource}:{int(item['id'])}" in result_state["expanded_results"],
                        on_expansion_changed=lambda expanded, identifier=int(item["id"]): (
                            result_state["expanded_results"].add(f"{resource}:{identifier}") if expanded
                            else result_state["expanded_results"].discard(f"{resource}:{identifier}")
                        ),
                    )
            restore_compact_result_anchor(result_state.pop("return_anchor", None))

        def set_page(page_number: int) -> None:
            result_state["page"] = page_number
            render_results()

        filter_control.on_value_change(lambda _: (result_state.__setitem__("page", 1), render_results()))
        sort_control.on_value_change(lambda _: (result_state.__setitem__("page", 1), render_results()))
        page_size_control.on_value_change(lambda _: (result_state.__setitem__("page", 1), render_results()))
        first.on("click", lambda: set_page(1)); previous.on("click", lambda: set_page(result_state["page"] - 1))
        next_button.on("click", lambda: set_page(result_state["page"] + 1)); last.on("click", lambda: set_page(10**9))
        render_results()


    return render_entity_compact_results
