"""Shared compact result presentation for resource and search screens."""
from __future__ import annotations
from typing import Any, Callable
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message
from .disposition.messages import text as disposition_text, status_label as disposition_status_label
from .personal_resources import STOP_PROPAGATION_CLICK_HANDLER

def build_compact_resource_view(*, tree_expander_icon: Callable, favourite_button: Callable,
    render_safe_snippet: Callable, preview_record_components: Callable,
    format_date: Callable, medium_label: Callable, component_is_previewable: Callable,
    api, direction: Callable, error_message: Callable):
    def render_compact_resource_result(
        resource: str,
        item: dict[str, Any],
        *,
        on_open: Any,
        components: list[dict[str, Any]] | None = None,
        component_total: int = 0,
        metadata_matched: bool = False,
        content_matched: bool = False,
        show_medium: bool = False,
        can_favourite: bool = True,
        can_preview: bool = False,
        can_expand_components: bool = False,
        components_are_matches: bool = False,
        initially_expanded: bool = False,
        on_expansion_changed: Any | None = None,
    ) -> None:
        """Render the shared compact record/aggregation result treatment."""
        is_record = resource == "records"
        number = item.get("record_number" if is_record else "aggregation_number") or render_message("webui.render_compact_resource_result.text.id_8f7a97fe", id=item['id'])
        date_value = item.get("date_originated" if is_record else "date_opened")
        component_rows = list(components or []) if is_record and can_expand_components else []
        component_count = (len(component_rows) if components_are_matches else component_total) if can_expand_components else 0
        result_id = f"compact-result-{resource}-{int(item['id'])}"
        with ui.column().classes("compact-result-item gap-0").props(f"id={result_id}"):
            with ui.row().classes("compact-result-row w-full items-center no-wrap"):
                with ui.element("div").classes("compact-result-identity"):
                    with ui.element("div").classes("compact-result-type"):
                        ui.icon("description" if is_record else "folder", size="20px").tooltip(
                            render_message("webui.render_compact_resource_result.tooltip.record_1b123585") if is_record else render_message("webui.render_compact_resource_result.tooltip.aggregation_fbf8ea6e")
                        )
                    with ui.column().classes("compact-result-title gap-0"):
                        with ui.row().classes("compact-result-primary w-full items-center no-wrap gap-2 min-w-0"):
                            ui.label(str(number)).classes("text-sm font-semibold text-slate-800 shrink-0")
                            ui.label("·").classes("text-slate-300 shrink-0")
                            ui.label(item.get("title") or render_message("webui.render_compact_resource_result.label.untitled_84d7d2e0")).classes(
                                "text-sm font-semibold text-slate-800 truncate"
                            ).tooltip(item.get("title") or render_message("webui.render_compact_resource_result.tooltip.untitled_72cde12a"))
                        with ui.row().classes("compact-result-meta w-full items-center no-wrap gap-1"):
                            ui.label(disposition_status_label(item.get("disposition_status", 1))).classes("text-xs text-slate-600").tooltip(disposition_text("status"))
                            ui.label(format_date(date_value)).classes(
                                "compact-result-date"
                            ).tooltip(render_message("webui.render_compact_resource_result.tooltip.originated_d00c8b65") if is_record else render_message("webui.render_compact_resource_result.tooltip.opened_4b8fc56f"))
                            with ui.row().classes("compact-result-indicators items-center no-wrap"):
                                if item.get("is_vital"):
                                    ui.icon("emergency", color="red-8", size="18px").classes(
                                        "compact-result-indicator"
                                    ).tooltip(render_message("webui.render_compact_resource_result.tooltip.vital_record_9db00737") if is_record else render_message("webui.render_compact_resource_result.tooltip.vital_aggregation_8c3d9591"))
                                if item.get("on_effective_hold") or item.get("is_on_effective_hold"):
                                    ui.icon("gavel", color="warning", size="18px").classes(
                                        "compact-result-indicator"
                                    ).tooltip(render_message("webui.render_compact_resource_result.tooltip.on_effective_legal_hold_07877134"))
                                if metadata_matched:
                                    ui.icon("manage_search", color="blue-grey-7", size="18px").classes(
                                        "compact-result-indicator"
                                    ).tooltip(render_message("webui.render_compact_resource_result.tooltip.record_metadata_matched_2ba2a770") if is_record else render_message("webui.render_compact_resource_result.tooltip.aggregation_metadata_matched_5dbe7774"))
                                if content_matched:
                                    ui.icon("text_snippet", color="blue-grey-7", size="18px").classes(
                                        "compact-result-indicator"
                                    ).tooltip(render_message("webui.render_compact_resource_result.tooltip.digital_component_content_matched_35625a16"))
                                if show_medium and item.get("medium"):
                                    medium = str(item["medium"]).lower()
                                    medium_icon = {
                                        "physical": "inventory_2", "digital": "computer", "mixed": "layers",
                                    }.get(medium, "category")
                                    ui.icon(medium_icon, color="blue-grey-7", size="18px").classes(
                                        "compact-result-indicator"
                                    ).tooltip(render_message("webui.render_compact_resource_result.tooltip.medium_medium_label_f8be324f", medium_label=medium_label(medium)))
                with ui.row().classes("compact-result-actions items-center no-wrap"):
                    component_host = None
                    expand_button = None
                    if component_count:
                        expand_button = ui.button(icon=tree_expander_icon(False)).props(
                            'flat round dense color=primary aria-label=' + repr(render_message("webui.render_compact_resource_result.accessible_name.show_digital_components_08467816"))
                        )
                        component_badge = ui.badge(str(component_count), color="warning").props(
                            "outline"
                        ).classes("compact-result-component-badge").tooltip(
                            render_message("webui.render_compact_resource_result.tooltip.component_row_count_value_digital_componen_6ee517ef", component_row_count=component_count, value='matching ' if components_are_matches else '', value_2='s' if component_count != 1 else '')
                        )
                    if can_favourite:
                        favourite_button(resource, int(item["id"]))
                    if is_record and can_preview:
                        ui.button(
                            icon="visibility", on_click=lambda _, selected=item: preview_record_components(selected),
                        ).props(
                            'flat round dense color=primary aria-label=' + repr(render_message("webui.render_compact_resource_result.accessible_name.preview_digital_components_72d3f864"))
                        ).tooltip(render_message("webui.render_compact_resource_result.tooltip.preview_digital_components_81745e00"))
                    if on_open is not None:
                        ui.button(
                            icon="open_in_new", on_click=lambda _, selected=item: on_open(selected),
                        ).props(
                            f"flat round dense color=primary aria-label='Open {'record' if is_record else 'aggregation'}'"
                        ).tooltip(render_message("webui.render_compact_resource_result.tooltip.open_record_3e4dcd53") if is_record else render_message("webui.render_compact_resource_result.tooltip.open_aggregation_2f0f3e73"))
            if component_count:
                component_host = ui.column().classes("compact-result-components w-full gap-0")
                component_host.set_visibility(initially_expanded)
                page_size = 25
                loaded = components_are_matches
                loading = False

                def render_component_page(rows, *, offset=0, total=0):
                    component_host.clear()
                    for component in rows:
                        with ui.row().classes("compact-result-component w-full items-center no-wrap gap-2"):
                            ui.icon("attach_file", size="17px").classes("text-slate-500 shrink-0")
                            with ui.column().classes("gap-0 grow min-w-0"):
                                ui.label(component.get("file_name") or render_message("webui.render_compact_resource_result.label.unnamed_file_d47632b1")).classes(
                                    "text-xs font-semibold text-slate-800 truncate"
                                ).tooltip(component.get("file_name") or render_message("webui.render_compact_resource_result.tooltip.unnamed_file_4f8f400c"))
                                if component.get("snippet"):
                                    with ui.row().classes("compact-result-snippet w-full text-xs text-slate-500 no-wrap"):
                                        render_safe_snippet(component.get("snippet"), compact=True)
                            if can_preview and component_is_previewable(component):
                                ui.button(
                                    icon="visibility",
                                    on_click=lambda _, selected=item, component_id=int(component["id"]):
                                        preview_record_components(selected, component_id),
                                ).props(
                                    'flat round dense color=primary aria-label=' + repr(render_message("webui.render_compact_resource_result.accessible_name.preview_digital_component_f8b12cac"))
                                ).tooltip(render_message("webui.render_compact_resource_result.tooltip.preview_digital_component_71925875"))
                    if total > page_size:
                        rtl = direction() == "rtl"
                        with ui.row().classes("w-full items-center justify-center gap-2"):
                            previous = ui.button(
                                icon="chevron_right" if rtl else "chevron_left",
                                on_click=lambda: load_component_page(offset - page_size),
                            ).props(
                                'flat round dense aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.previous_page_2ba84275"))
                            )
                            ui.badge(f"{offset + 1}–{offset + len(rows)} / {total}", color="blue-grey").props("outline")
                            next_page = ui.button(
                                icon="chevron_left" if rtl else "chevron_right",
                                on_click=lambda: load_component_page(offset + page_size),
                            ).props(
                                'flat round dense aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.next_page_66adc3fc"))
                            )
                            previous.set_enabled(offset > 0)
                            next_page.set_enabled(offset + len(rows) < total)

                async def load_component_page(offset=0):
                    nonlocal loaded, loading
                    if loading or component_host.is_deleted:
                        return
                    loading = True
                    try:
                        result = await api.component_page(int(item["id"]), limit=page_size, offset=offset)
                        total = int(result["total"])
                        if not result["items"] and total and offset:
                            offset = (total - 1) // page_size * page_size
                            result = await api.component_page(int(item["id"]), limit=page_size, offset=offset)
                    except ApiError as error:
                        if not component_host.is_deleted:
                            ui.notify(error_message(error), color="negative", close_button=True)
                        return
                    finally:
                        loading = False
                    if component_host.is_deleted:
                        return
                    loaded = True
                    component_badge.set_text(str(result["total"]))
                    with component_host:
                        render_component_page(result["items"], offset=offset, total=int(result["total"]))

                if components_are_matches:
                    with component_host:
                        render_component_page(component_rows)
                elif initially_expanded:
                    with component_host:
                        ui.timer(0, load_component_page, once=True)

                expanded = {"value": initially_expanded}
                if initially_expanded:
                    expand_button.props(remove="icon aria-label")
                    expand_button.props('icon=expand_more aria-label=' + repr(render_message("webui.render_compact_resource_result.accessible_name.hide_digital_components_53390064")))
                    expand_button.update()

                async def toggle_components() -> None:
                    expanded["value"] = not expanded["value"]
                    component_host.set_visibility(expanded["value"])
                    expand_button.props(remove="icon aria-label")
                    expand_button.props(
                        f"icon={tree_expander_icon(expanded['value'])} "
                        f"aria-label='{'Hide' if expanded['value'] else 'Show'} digital components'"
                    )
                    expand_button.update()
                    if on_expansion_changed is not None:
                        on_expansion_changed(expanded["value"])
                    if expanded["value"] and not loaded:
                        await load_component_page()

                expand_button.on("click", toggle_components, js_handler=STOP_PROPAGATION_CLICK_HANDLER)

    return render_compact_resource_result

