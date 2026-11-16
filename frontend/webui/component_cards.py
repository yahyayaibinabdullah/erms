"""Existing component card presentation with shared formatters supplied at assembly."""
from __future__ import annotations
from typing import Any
from nicegui import ui
from .capabilities import capability_allowed
from .i18n_catalogue import render_message, render_message_plain
from .component_presentation import component_file_icon, component_is_previewable, localized_component_status, localized_indexing_status


def build_component_cards(*, format_timestamp, format_file_size):
    def row_action(icon, key, callback, *, disabled=False, color="primary"):
        label = render_message(key)
        button = ui.button(icon=icon, color=color, on_click=callback).props("flat round dense").tooltip(label)
        button.props["aria-label"] = render_message_plain(key)
        if disabled:
            button.disable()

    def render_rows(
        rows, on_move, on_remove, on_history, on_view, on_download, on_reindex, *,
        readonly, capabilities, focused_component_id, expanded, read_indexing, offset, total,
    ):
        def render_row(component, position):
            identifier = component["id"]
            is_open = identifier in expanded
            available = component.get("content_status") == "available"
            can_reorder = not readonly and capability_allowed(capabilities, "reorder_components")
            mime_type = component.get("mime_type")
            filename = component.get("file_name") or render_message("webui.render_component_cards.text.unnamed_file_c7b0e1b2")

            def render_details():
                facts.clear()
                with facts:
                    indexing = component.get("_indexing")
                    fields = [
                        (render_message("components.record.file_type"), mime_type or render_message("webui.render_component_cards.text.unknown_file_type_b64b244a")),
                        (render_message("entity_metadata.field.date_originated"), format_timestamp(component.get("date_originated"))),
                        (render_message("advanced_search.field.date_created"), format_timestamp(component.get("date_created"))),
                    ]
                    if indexing:
                        fields.append((
                            render_message("components.record.index_status"),
                            localized_indexing_status(indexing.get("status")),
                        ))
                        if indexing.get("indexed_at"):
                            fields.append((
                                render_message("components.record.last_indexed"), format_timestamp(indexing["indexed_at"]),
                            ))
                    fields.extend([
                        (render_message("components.field.storage_backend"), component.get("storage_backend") or "—"),
                        (render_message("components.record.position"), component.get("component_order", "—")),
                        (component.get("checksum_algo") or render_message("advanced_search.field.checksum_value"), component.get("checksum_value") or "—"),
                    ])
                    for label, value in fields:
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(label).classes("text-xs text-slate-600")
                            ui.label(str(value)).props("dir=auto").classes("text-sm break-all")

            async def toggle():
                if identifier in expanded:
                    expanded.remove(identifier)
                    details.set_visibility(False)
                    disclosure.props("aria-expanded=false")
                    chevron.set_name("chevron_right")
                    return
                expanded.add(identifier)
                details.set_visibility(True)
                disclosure.props("aria-expanded=true")
                chevron.set_name("expand_more")
                if read_indexing is not None and "_indexing" not in component:
                    indexing = await read_indexing(identifier)
                    if not details.is_deleted and indexing is not None:
                        component["_indexing"] = indexing
                        render_details()

            with ui.column().classes(
                "record-file-row w-full gap-0 border-b border-slate-200"
                + (" bg-blue-50" if identifier == focused_component_id else "")
            ).props(f'id="digital-component-{identifier}"'):
                with ui.row().classes("w-full items-center justify-between gap-1 px-2 py-1 flex-wrap", remove="row"):
                    with ui.button(on_click=toggle, color="blue-grey-10").props(
                        "flat dense no-caps align=start",
                    ).classes("record-file-disclosure grow min-w-0 text-start px-1") as disclosure:
                        with ui.row().classes("w-full items-center no-wrap gap-2 min-w-0", remove="row"):
                            chevron = ui.icon("expand_more" if is_open else "chevron_right", size="18px").classes(
                                "record-file-chevron shrink-0 text-primary",
                            )
                            ui.avatar(icon=component_file_icon(mime_type), color="blue-1", text_color="primary", size="30px").props(
                                "rounded",
                            ).classes("shrink-0")
                            ui.label(filename).props("dir=auto").classes("record-file-name min-w-0 font-semibold")
                    with ui.row().classes("record-file-summary items-center justify-between gap-x-3 gap-y-0", remove="row"):
                        ui.label(format_file_size(component.get("size_in_bytes"))).classes("text-xs text-slate-600 whitespace-nowrap")
                        status = component.get("content_status", "pending")
                        color = {"available": "positive", "failed": "negative", "pending": "warning", "quarantined": "orange"}.get(status, "blue-grey")
                        ui.badge(localized_component_status(status), color=color).props("outline")
                        with ui.row().classes("items-center justify-end gap-0 min-w-16", remove="row"):
                            if on_view is not None and available and capability_allowed(capabilities, "view_component") and component_is_previewable(component):
                                row_action("visibility", "webui.render_component_cards.tooltip.view_document_92d64052", lambda: on_view(component))
                            if on_download is not None and available and capability_allowed(capabilities, "download_component"):
                                row_action("download", "webui.render_component_cards.tooltip.download_original_bbc9b167", lambda: on_download(component))
                with ui.column().classes("w-full gap-3 bg-slate-50 border-t border-slate-200 px-4 py-3") as details:
                    facts = ui.grid(columns=2).classes("w-full gap-x-4 gap-y-2")
                    render_details()
                    with ui.row().classes("detail-action-row items-center gap-1", remove="row"):
                        if can_reorder:
                            row_action("arrow_upward", "webui.render_component_cards.tooltip.move_earlier_0de89c72", lambda: on_move(component, -1), disabled=position == 0)
                            row_action("arrow_downward", "webui.render_component_cards.tooltip.move_later_71077211", lambda: on_move(component, 1), disabled=position + 1 == total)
                        if on_reindex is not None and capability_allowed(capabilities, "reindex_components"):
                            row_action("manage_search", "webui.render_component_cards.tooltip.reindex_component_content_3ce189d9", lambda: on_reindex(component), disabled=not available)
                        if on_history is not None:
                            row_action("history", "webui.render_component_cards.tooltip.event_history_bbccf5f1", lambda: on_history(component))
                        if not readonly and capability_allowed(capabilities, "remove_component"):
                            row_action("delete_outline", "webui.render_component_cards.tooltip.remove_component_34d21bd2", lambda: on_remove(component), color="negative")
                details.set_visibility(is_open)
                disclosure.props["aria-expanded"] = str(is_open).lower()
                disclosure.props["aria-controls"] = f"c{details.id}"

        for position, component in enumerate(rows, start=offset):
            render_row(component, position)

    def render_component_cards(
        rows: list[dict[str, Any]], on_move, on_remove, on_history=None,
        on_view=None, on_download=None, on_reindex=None, *, readonly: bool = False,
        capabilities: dict[str, bool] | None = None,
        focused_component_id: int | None = None, staged_preview: bool = False,
        expanded: set[int] | None = None, read_indexing=None, offset: int = 0, total: int = 0,
    ) -> None:
        if expanded is not None:
            render_rows(
                rows, on_move, on_remove, on_history, on_view, on_download, on_reindex,
                readonly=readonly, capabilities=capabilities, focused_component_id=focused_component_id,
                expanded=expanded, read_indexing=read_indexing, offset=offset, total=total,
            )
            return
        for index, component in enumerate(rows):
            status = component.get("content_status", "pending")
            status_color = {
                "available": "positive", "staged": "primary", "pending": "warning",
                "failed": "negative", "quarantined": "orange", "deleted": "grey",
            }.get(status, "grey")
            checksum = component.get("checksum_value") or "—"
            checksum_short = checksum if len(checksum) <= 18 else f"{checksum[:10]}…{checksum[-6:]}"
            focused = component.get("id") == focused_component_id
            with ui.card().classes(
                "component-card w-full p-4 gap-3"
                + (" ring-2 ring-primary bg-blue-50" if focused else "")
            ).props(f'id="digital-component-{component.get("id")}"'):
                with ui.row().classes("w-full items-start no-wrap gap-3"):
                    ui.avatar(icon=component_file_icon(component.get("mime_type")), color="blue-1", text_color="primary").props("rounded")
                    with ui.column().classes("gap-1 grow min-w-0"):
                        component_name = component.get("file_name") or render_message("webui.render_component_cards.text.unnamed_file_c7b0e1b2")
                        ui.label(component_name).classes(
                            "component-filename font-semibold text-slate-800"
                        ).tooltip(component_name)
                        mime_type = component.get("mime_type") or render_message("webui.render_component_cards.text.unknown_file_type_b64b244a")
                        ui.label(mime_type).classes(
                            "component-mime-type text-xs text-slate-500"
                        ).tooltip(mime_type)
                    ui.badge(render_message("webui.render_component_cards.badge.get_a17efdc9", get=component.get('component_order', '—'))).props(
                        "outline color=primary"
                    ).classes("shrink-0")
                with ui.row().classes("component-card-actions w-full items-center justify-end gap-0 no-wrap"):
                    if on_view is not None and (not staged_preview or component_is_previewable(component, staged=True)):
                        preview_label = render_message("webui.render_compact_resource_result.tooltip.preview_digital_component_71925875") if staged_preview else render_message("webui.render_component_cards.tooltip.view_document_92d64052")
                        ui.button(icon="visibility", on_click=lambda _, item=component: on_view(item)).props(
                            "flat round dense" + (" disable" if status != ("staged" if staged_preview else "available") or not capability_allowed(capabilities, "view_component") else "")
                        ).props(f'aria-label={preview_label!r}').tooltip(preview_label if capability_allowed(capabilities, "view_component") else render_message("webui.render_component_cards.tooltip.your_effective_roles_do_not_grant_componen_ac7b50e0"))
                    if on_download is not None:
                        ui.button(icon="download", on_click=lambda _, item=component: on_download(item)).props(
                            "flat round dense" + (" disable" if status != "available" or not capability_allowed(capabilities, "download_component") else "")
                        ).tooltip(render_message("webui.render_component_cards.tooltip.download_original_bbc9b167") if capability_allowed(capabilities, "download_component") else render_message("webui.render_component_cards.tooltip.your_effective_roles_do_not_grant_componen_c83f01c9"))
                    if on_reindex is not None and capability_allowed(capabilities, "reindex_components"):
                        ui.button(icon="manage_search", on_click=lambda _, item=component: on_reindex(item)).props(
                            "flat round dense" + (" disable" if status != "available" else "")
                        ).tooltip(render_message("webui.render_component_cards.tooltip.reindex_component_content_3ce189d9"))
                    ui.button(icon="arrow_upward", on_click=lambda _, item=component: on_move(item, -1)).props(
                        "flat round dense" + (" disable" if readonly or not capability_allowed(capabilities, "reorder_components") or index == 0 else "")
                    ).tooltip(render_message("webui.render_component_cards.tooltip.move_earlier_0de89c72"))
                    ui.button(icon="arrow_downward", on_click=lambda _, item=component: on_move(item, 1)).props(
                        "flat round dense" + (" disable" if readonly or not capability_allowed(capabilities, "reorder_components") or index == len(rows) - 1 else "")
                    ).tooltip(render_message("webui.render_component_cards.tooltip.move_later_71077211"))
                    ui.button(icon="delete_outline", color="negative", on_click=lambda _, item=component: on_remove(item)).props(
                        "flat round dense" + (" disable" if readonly or not capability_allowed(capabilities, "remove_component") else "")
                    ).tooltip(render_message("webui.render_component_cards.tooltip.remove_component_34d21bd2") if not readonly and capability_allowed(capabilities, "remove_component") else render_message("webui.render_component_cards.tooltip.this_operation_is_unavailable_under_the_cu_9d386e97"))
                    if on_history is not None:
                        ui.button(icon="history", color="blue-grey", on_click=lambda _, item=component: on_history(item)).props("flat round dense").tooltip(render_message("webui.render_component_cards.tooltip.event_history_bbccf5f1"))
                with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                    ui.badge(localized_component_status(status), color=status_color).props("rounded")
                    indexing = component.get("_indexing")
                    if indexing:
                        index_status = indexing.get("status", "pending")
                        ui.badge(render_message("webui.render_component_cards.badge.index_title_c266923f", title=localized_indexing_status(index_status)), color={
                            "indexed":"positive","succeeded":"positive","failed":"negative",
                            "unsupported":"orange","processing":"primary","leased":"primary",
                            "queued":"warning","pending":"warning","stale":"warning",
                        }.get(index_status,"blue-grey")).props("outline rounded")
                        if indexing.get("indexed_at"):
                            ui.label(render_message("webui.render_component_cards.label.last_indexed_format_timestamp_cc1a7293", format_timestamp=format_timestamp(indexing['indexed_at']))).classes("text-xs text-slate-500")
                    ui.label(format_file_size(component.get("size_in_bytes"))).classes("text-sm font-medium text-slate-600")
                ui.separator()
                with ui.grid(columns=2).classes("w-full gap-x-6 gap-y-3"):
                    for label, value in (
                        (render_message("entity_metadata.field.date_originated"), format_timestamp(component.get("date_originated"))),
                        (render_message("advanced_search.field.date_created"), format_timestamp(component.get("date_created"))),
                        (render_message("components.field.storage_backend"), str(component.get("storage_backend") or "—")),
                        (component.get("checksum_algo") or render_message("advanced_search.field.checksum_value"), checksum_short),
                    ):
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(label).classes("component-meta-label")
                            value_label = ui.label(value).classes("component-meta-value truncate max-w-full")
                            if value == checksum_short and checksum != "—":
                                value_label.tooltip(checksum)

    return render_component_cards
