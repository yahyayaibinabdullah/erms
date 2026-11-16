"""Existing component behavior and per-view state with explicit dependencies."""
from __future__ import annotations
import asyncio
import json
from typing import Any
from nicegui import background_tasks, events, ui
from .api_client import ApiError
from .capabilities import capability_allowed
from .i18n_catalogue import render_message
from .component_presentation import RecordComponentDropTarget, component_uploader
from .upload_buffers import buffer_upload_batch

def build_components(*, api, error_message, show_entity_history, preview_record_components, render_component_cards):
    async def show_components(
        record: dict[str, Any], *, container: Any | None = None,
        focused_component_id: int | None = None, active=lambda: True,
        load_access=None, on_refresh=None, upload_host=None, drop_scope=None,
    ) -> None:
        if load_access is None:
            try:
                closure, component_capabilities = await asyncio.gather(
                    api.effective_record_closure(record["id"]),
                    api.resource_capabilities("records", record["id"]),
                )
                closure_known = True
            except ApiError as error:
                if active():
                    ui.notify(error_message(error), color="negative", close_button=True)
                return
        else:
            component_capabilities, (closure_known, closure) = await load_access
            component_capabilities = component_capabilities or {}
        if not active():
            return
        readonly = not closure_known or closure is not None
        rows_layout = upload_host is not None
        can_upload = not readonly and record.get("medium") != "physical" and capability_allowed(component_capabilities, "add_component")
        current_rows: list[dict[str, Any]] = []
        component_page = {"limit": 25, "offset": 0, "total": 0}
        upload_lock = asyncio.Lock()
        uploader_control: dict[str, Any] = {}
        expanded_component_ids: set[int] = set()

        async def download_component(component: dict[str, Any]) -> None:
            try:
                content = await api.download_component(component["id"])
                ui.download(content, component["file_name"], component.get("mime_type") or "application/octet-stream")
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)

        async def reindex_component(component: dict[str, Any]) -> None:
            try:
                result = await api.reindex_component(component["id"])
                if not active():
                    return
                component["_indexing"] = {"status": result["status"]}
                render_current_components()
                with component_area:
                    ui.notify(
                        render_message("webui.reindex_component.notify.component_indexing_is_already_in_progress_f9c08cd9") if result.get("already_in_progress")
                        else render_message("webui.reindex_component.notify.component_reindex_queued_processing_contin_9faeb3e5"),
                        color="info",
                    )
            except ApiError as error:
                if active():
                    ui.notify(error_message(error), color="negative", close_button=True)

        def uploaded(event: events.MultiUploadEventArguments) -> None:
            if not active() or not can_upload:
                return
            try:
                buffered_files = buffer_upload_batch(event)
            except (OSError, ValueError) as error:
                ui.notify(render_message("webui.uploaded.notify.could_not_read_an_uploaded_file_error_4a253d6b", error=error), color="negative", close_button=True)
                return

            async def stage_buffered_files() -> None:
                saved = 0
                failure = None
                try:
                    async with upload_lock:
                        try:
                            first_position = await api.component_count(record["id"]) + 1
                            for offset, (content, name, mime_type) in enumerate(buffered_files):
                                await api.upload_component(
                                    record["id"], first_position + offset, name, content, mime_type,
                                )
                                saved += 1
                        finally:
                            if saved and active():
                                await refresh_components()
                except ApiError as error:
                    failure = error
                if active() and on_refresh and saved:
                    await on_refresh()
                if active():
                    with component_area:
                        if saved:
                            ui.notify(
                                render_message("webui.stage_buffered_files.notify.buffered_file_count_digital_component_valu_e0a402d5", buffered_file_count=saved, value='s' if saved != 1 else ''),
                                color="positive",
                            )
                        if failure is not None:
                            ui.notify(error_message(failure), color="negative", close_button=True)
                    if not uploader_control["uploader"].is_deleted:
                        uploader_control["uploader"].run_method("removeUploadedFiles")

            background_tasks.create(
                stage_buffered_files(), name=f"stage components for record {record['id']}"
            )

        dialog = None
        component_area: Any = None

        def render_current_components() -> None:
            component_area.clear()
            with component_area:
                if not current_rows and record.get("medium") != "physical":
                    with ui.column().classes(
                        "col-span-full w-full items-center justify-center py-10 gap-2 text-center text-slate-400"
                    ):
                        ui.icon("cloud_upload").classes("text-4xl")
                        ui.label(render_message("webui.render_current_components.label.no_digital_components_have_been_uploaded_y_3f61a29a"))
                elif current_rows:
                    render_component_cards(
                        current_rows, move_component, remove_component,
                        lambda item: show_entity_history("digital-components", item),
                        lambda item: preview_record_components(record, item["id"]),
                        download_component, reindex_component, readonly=readonly,
                        capabilities=component_capabilities,
                        focused_component_id=focused_component_id,
                        **({
                            "expanded": expanded_component_ids,
                            "read_indexing": read_indexing if capability_allowed(component_capabilities, "reindex_components") else None,
                            "offset": component_page["offset"],
                            "total": component_page["total"],
                        } if rows_layout else {}),
                    )
                total = int(component_page["total"])
                if total > component_page["limit"]:
                    first = int(component_page["offset"]) + 1
                    last = int(component_page["offset"]) + len(current_rows)
                    with ui.row().classes("w-full items-center justify-center gap-2 pt-3"):
                        previous = ui.button(icon="chevron_left").props(
                            'flat round aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.previous_page_2ba84275"))
                        )
                        ui.badge(f"{first}–{last} / {total}", color="blue-grey").props("outline")
                        next_button = ui.button(icon="chevron_right").props(
                            'flat round aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.next_page_66adc3fc"))
                        )
                        if component_page["offset"] <= 0:
                            previous.disable()
                        if last >= total:
                            next_button.disable()
                        previous.on("click", lambda: change_component_page(-1))
                        next_button.on("click", lambda: change_component_page(1))

        async def change_component_page(direction: int) -> None:
            expanded_component_ids.clear()
            component_page["offset"] = max(
                0,
                int(component_page["offset"]) + direction * int(component_page["limit"]),
            )
            await refresh_components()

        async def read_indexing(component_id):
            try:
                return await api.component_indexing_status(component_id)
            except ApiError:
                return None

        async def refresh_components() -> None:
            try:
                result = await api.component_page(
                    record["id"], limit=int(component_page["limit"]),
                    offset=int(component_page["offset"]),
                )
                if not result["items"] and result["total"] and component_page["offset"]:
                    component_page["offset"] = max(
                        0,
                        ((int(result["total"]) - 1) // int(component_page["limit"]))
                        * int(component_page["limit"]),
                    )
                    result = await api.component_page(
                        record["id"], limit=int(component_page["limit"]),
                        offset=int(component_page["offset"]),
                    )
                if not active():
                    return
                rows = result["items"]
                component_page["total"] = int(result["total"])
                indexed_rows = [item for item in rows if not rows_layout or item["id"] in expanded_component_ids]
                if indexed_rows and capability_allowed(component_capabilities, "reindex_components"):
                    statuses=await asyncio.gather(*[
                        read_indexing(item["id"]) for item in indexed_rows
                    ])
                    for item,indexing in zip(indexed_rows, statuses):
                        if isinstance(indexing,dict): item["_indexing"]=indexing
                if not active():
                    return
                current_rows.clear()
                current_rows.extend(rows)
                render_current_components()
            except ApiError as error:
                if active():
                    if not current_rows:
                        component_area.clear()
                        with component_area:
                            ui.label(error_message(error)).classes("text-sm text-negative").props("role=alert")
                            ui.button(render_message("resource_details.retry"), on_click=refresh_components).props("flat dense no-caps")
                    ui.notify(error_message(error), color="negative")

        async def move_component(component: dict[str, Any], direction: int) -> None:
            try:
                await api.move_component(record["id"], component["id"], direction)
                await refresh_components()
            except ApiError as error:
                ui.notify(error_message(error), color="negative")

        async def remove_component(component: dict[str, Any]) -> None:
            previous_rows = list(current_rows)
            current_rows[:] = [item for item in current_rows if item["id"] != component["id"]]
            render_current_components()
            # The optimistic redraw deletes the clicked card's event slot.
            # Keep feedback and refresh in the surviving, language-scoped host.
            with component_area:
                try:
                    await api.delete_component(component["id"], component["version"])
                    expanded_component_ids.discard(component["id"])
                    if not active():
                        return
                    ui.notify(render_message("webui.remove_component.notify.digital_component_removed_3af94a83"), color="positive")
                    await refresh_components()
                    if on_refresh and active():
                        await on_refresh()
                except ApiError as error:
                    if not active():
                        return
                    current_rows[:] = previous_rows
                    render_current_components()
                    ui.notify(error_message(error), color="negative")

        async def render_component_section(*, standalone: bool) -> None:
            nonlocal component_area
            if standalone:
                with ui.row().classes("w-full items-start no-wrap"):
                    with ui.column().classes("gap-0 grow"):
                        ui.label(render_message("webui.render_component_section.label.digital_components_ffe75eb9")).classes("text-xl font-semibold")
                        ui.label(render_message("webui.render_component_section.label.record_record_number_644e601d", record_number=record['record_number'])).classes("text-sm text-slate-500")
                    ui.button(icon="close", on_click=dialog.close).props("flat round dense")
            scroll_classes = (
                "w-full overflow-y-auto max-h-[calc(100vh-190px)] pr-1"
                if standalone else "w-full"
            )
            if rows_layout and can_upload:
                with upload_host:
                    uploader_control["uploader"] = component_uploader(uploaded, compact=True)
                    RecordComponentDropTarget(uploader_control["uploader"], drop_scope)
            with ui.element("div").classes(scroll_classes):
                if readonly:
                    with ui.row().classes("w-full items-start gap-3 p-3 bg-amber-50 border border-amber-200 rounded-lg"):
                        ui.icon("lock", color="amber-8")
                        with ui.column().classes("gap-0 grow"):
                            ui.label(render_message("webui.render_component_section.label.digital_components_are_read_only_15f586a5")).classes("font-semibold text-amber-900")
                            ui.label(
                                render_message("resource_details.closure_source_restricted")
                                if closure and closure.get("restricted") else
                                render_message("resource_details.unavailable") if not closure_known else render_message("webui.render_component_section.label.closed_by_aggregation_number_title_files_m_69c0e22c", aggregation_number=closure['aggregation_number'], title=closure['title'])
                            ).classes("text-sm text-amber-800")
                elif record.get("medium") == "physical":
                    with ui.row().classes("w-full items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3"):
                        ui.icon("inventory_2", color="primary")
                        with ui.column().classes("gap-0 grow"):
                            ui.label(render_message("webui.render_component_section.label.this_is_a_physical_record_5a1bd071")).classes("font-semibold text-blue-900")
                            ui.label(render_message("webui.render_component_section.label.digital_files_cannot_be_added_7800d8c2")).classes("text-sm text-blue-800")
                elif can_upload:
                    if not rows_layout:
                        uploader_control["uploader"] = component_uploader(uploaded)
                else:
                    with ui.row().classes("w-full items-start gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3"):
                        ui.icon("lock", color="blue-grey")
                        ui.label(render_message("webui.render_component_section.label.adding_digital_components_is_unavailable_u_6f6dc0a1")).classes("text-sm text-slate-600")
                with ui.element("div").classes("w-full" if rows_layout else "component-list w-full mt-3"):
                    component_area = ui.element("div").classes("component-list record-file-list w-full" if rows_layout else "component-grid w-full")
                    with component_area:
                        ui.spinner()

            if standalone:
                with ui.row().classes("w-full justify-end"):
                    ui.button(render_message("webui.render_component_section.button.close_0f34a40c"), on_click=dialog.close).props("flat")
            await refresh_components()
            if focused_component_id is not None and active():
                await ui.run_javascript(
                    "document.getElementById(" + json.dumps(
                        f"digital-component-{focused_component_id}"
                    ) + ")?.scrollIntoView({behavior:'smooth',block:'center'})"
                )

        if container is None:
            dialog = ui.dialog()
            with dialog, ui.card().classes("max-h-[calc(100vh-32px)]").style("width: 920px; max-width: calc(100vw - 32px)"):
                await render_component_section(standalone=True)
        else:
            with container:
                await render_component_section(standalone=False)
        if dialog is not None:
            dialog.open()

    return show_components
