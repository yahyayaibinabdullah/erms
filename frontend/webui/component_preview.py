"""Existing component behavior and per-view state with explicit dependencies."""
from __future__ import annotations
import base64
import json
from typing import Any
from nicegui import context, ui
from .api_client import ApiError
from .i18n_catalogue import render_message
from .locale_services import current_locale_context
from .component_presentation import component_file_icon, component_is_previewable, native_preview_kind, requires_document_conversion

def build_component_preview(*, api, error_message):
    async def preview_record_components(
        record: dict[str, Any] | None, initial_component_id: int | None = None, *,
        draft_id: int | None = None, staged_components: list[dict[str, Any]] | None = None,
        source_active=None,
    ) -> None:
        """One viewer for saved records and private, uncommitted draft uploads."""
        # Async work and dynamic host clearing can delete the slot which originated
        # this callback (especially a q-table body slot). Keep a stable client
        # reference for the viewer's complete lifetime instead of resolving it
        # later through NiceGUI's implicit current-slot context.
        viewer_client = context.client
        if source_active is not None and not source_active():return
        preview_page = {"limit": 50, "offset": 0, "total": 0}
        staged_rows = sorted(
            (dict(item) for item in staged_components or [] if component_is_previewable(item, staged=True)),
            key=lambda item: item.get("component_order", 0),
        ) if draft_id is not None else []
        try:
            if draft_id is not None:
                # Reuse the mounted editor's metadata; every rendition request
                # independently checks current ownership, privilege and expiry.
                capabilities = {"view_component": True, "print_component": False, "download_component": False}
                record = {"id": f"draft-{draft_id}"}
                initial_index = next((i for i,item in enumerate(staged_rows) if item["id"]==initial_component_id),0)
                preview_page["offset"] = initial_index // preview_page["limit"] * preview_page["limit"]
                components = {"items": staged_rows[preview_page["offset"]:preview_page["offset"]+preview_page["limit"]], "total": len(staged_rows)}
            else:
                capabilities = await api.resource_capabilities("records", record["id"])
                components = {"items": [], "total": 0}
                if capabilities.get("list_components") and capabilities.get("view_component"):
                    components = await api.previewable_component_page(
                        record["id"], limit=preview_page["limit"], selected_component_id=initial_component_id,
                    )
                    preview_page["offset"] = components["offset"]
        except ApiError as error:
            if source_active is None or source_active():ui.notify(error_message(error), color="negative", close_button=True)
            return
        if source_active is not None and not source_active():return
        preview_page["total"] = int(components["total"])
        previewable = components["items"]
        if not capabilities.get("view_component") or not previewable:
            ui.notify(render_message("webui.preview_record_components.notify.no_previewable_digital_components_are_avai_8160d774"), color="warning")
            return
        selected = next(
            (item for item in previewable if item["id"] == initial_component_id),
            previewable[0],
        )
        viewer_state: dict[str, Any] = {
            "component": selected, "canvas_id": None, "loading_id": None, "request_id": 0, "closed": False,
        }
        dialog = ui.dialog().props("maximized transition-show=fade transition-hide=fade")

        async def download_component(component: dict[str, Any]) -> None:
            try:
                content = await api.download_component(component["id"])
                ui.download(
                    content, component["file_name"],
                    component.get("mime_type") or "application/octet-stream",
                )
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)

        async def print_component(component: dict[str, Any]) -> None:
            try:
                ui.notify(render_message("webui.print_component.notify.preparing_document_for_printing_21820277"), color="info")
                printable = await api.print_component_pdf(component["id"])
                encoded = base64.b64encode(printable).decode("ascii")
                print_mime_type = (
                    component.get("mime_type")
                    if native_preview_kind(component.get("mime_type")) == "image"
                    else "application/pdf"
                )
                await viewer_client.run_javascript(
                    "import('/static/pdfjs/erms-viewer.mjs').then(() => "
                    f"window.ermsPdfViewer.print({json.dumps(encoded)}, "
                    f"{json.dumps(print_mime_type)}))",
                    timeout=30,
                )
            except (ApiError, TimeoutError) as error:
                message = error_message(error) if isinstance(error, ApiError) else render_message("webui.print_component.text.the_print_view_did_not_finish_loading_58f6bfd9")
                ui.notify(message, color="negative", close_button=True)

        def close_viewer() -> None:
            viewer_state["closed"] = True
            viewer_state["request_id"] += 1
            canvas_id = viewer_state.get("canvas_id")
            if canvas_id:
                viewer_client.run_javascript(
                    f"window.ermsPdfViewer?.close({json.dumps(canvas_id)})"
                )
            dialog.close()

        switcher_host: Any = None
        toolbar_host: Any = None
        content_host: Any = None
        page_loading = False

        async def load_preview_page(direction: int) -> None:
            nonlocal previewable, page_loading
            if page_loading or viewer_state["closed"]:
                return
            page_loading = True
            target_offset = max(
                0,
                int(preview_page["offset"]) + direction * int(preview_page["limit"]),
            )
            try:
                if draft_id is not None:
                    result = {
                        "items": staged_rows[target_offset:target_offset+preview_page["limit"]],
                        "total": len(staged_rows), "offset": target_offset,
                    }
                else:
                    result = await api.previewable_component_page(
                        record["id"], limit=preview_page["limit"], offset=target_offset,
                    )
            except ApiError as error:
                if not viewer_state["closed"] and (source_active is None or source_active()):
                    ui.notify(error_message(error), color="negative", close_button=True)
                return
            finally:
                page_loading = False
            if viewer_state["closed"] or (source_active is not None and not source_active()):
                return
            candidates = result["items"]
            if not candidates:
                ui.notify(render_message("webui.preview_record_components.notify.no_previewable_digital_components_are_avai_8160d774"), color="warning")
                return
            preview_page.update(offset=result["offset"], total=int(result["total"]))
            previewable = candidates
            await select_component(previewable[0])

        def render_switcher() -> None:
            switcher_host.clear()
            active_id = viewer_state["component"]["id"]
            active_index = next(
                index for index, item in enumerate(previewable, start=1)
                if item["id"] == active_id
            )
            active_component = viewer_state["component"]
            total = preview_page["total"]
            first_index = preview_page["offset"] + 1
            with switcher_host:
                with ui.row().classes("component-switcher-bar w-full items-center no-wrap gap-3"):
                    ui.label(
                        render_message("webui.render_switcher.label.previewable_count_digital_component_value_6b9458a3", previewable_count=total, value='s' if current_locale_context()[0].split('-')[0]=='en' and total != 1 else '')
                    ).classes("component-switcher-summary")
                    ui.element("div").classes("component-switcher-divider")
                    with ui.row().classes("component-switcher-file items-center no-wrap gap-3"):
                        ui.icon(
                            component_file_icon(active_component.get("mime_type")),
                            color="primary", size="24px",
                        )
                        ui.label(
                            active_component.get("file_name") or render_message("webui.render_switcher.label.unnamed_file_ccc9edc2")
                        ).classes("component-switcher-filename").tooltip(
                            active_component.get("file_name") or render_message("webui.render_switcher.tooltip.unnamed_file_1e7c23b2")
                        )
                        ui.label(
                            render_message("webui.render_switcher.label.active_index_of_previewable_count_8114d6d6", active_index=preview_page["offset"] + active_index, previewable_count=total)
                        ).classes("component-switcher-position")
                    with ui.row().classes(
                        "component-switcher-scroll items-center no-wrap gap-2"
                    ):
                        for index, item in enumerate(previewable, start=first_index):
                            active = item["id"] == active_id
                            button = ui.button(
                                str(index),
                                on_click=lambda _, component=item: select_component(component),
                            ).props(
                                "flat dense no-caps"
                                + (" aria-pressed=true" if active else " aria-pressed=false")
                            ).classes(
                                "component-switcher-button"
                                + (" component-switcher-button--active" if active else "")
                            )
                            if viewer_state.get("loading_id") == item["id"]:
                                button.disable()
                            button.tooltip(item.get("file_name") or render_message("webui.render_switcher.tooltip.unnamed_file_1e7c23b2"))
                    previous_components = ui.button(icon="chevron_left").props(
                        'flat round dense aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.previous_page_2ba84275"))
                    )
                    next_components = ui.button(icon="chevron_right").props(
                        'flat round dense aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.next_page_66adc3fc"))
                    )
                    if preview_page["offset"] <= 0:
                        previous_components.disable()
                    if preview_page["offset"] + preview_page["limit"] >= preview_page["total"]:
                        next_components.disable()
                    previous_components.on("click", lambda: load_preview_page(-1))
                    next_components.on("click", lambda: load_preview_page(1))

        async def select_component(component: dict[str, Any]) -> None:
            if viewer_state["closed"] or (source_active is not None and not source_active()):return
            if viewer_state.get("loading_id") == component["id"]:
                return
            viewer_state["request_id"] += 1
            request_id = viewer_state["request_id"]
            old_canvas_id = viewer_state.get("canvas_id")
            if old_canvas_id:
                await viewer_client.run_javascript(
                    f"window.ermsPdfViewer?.close({json.dumps(old_canvas_id)}); true"
                )
            if viewer_state["closed"] or (source_active is not None and not source_active()):return
            viewer_state.update(component=component, canvas_id=None, loading_id=component["id"])
            render_switcher()
            toolbar_host.clear()
            content_host.clear()
            converting = requires_document_conversion(component)
            with toolbar_host:
                with ui.row().classes(
                    "component-viewer-toolbar w-full items-center no-wrap px-4 py-2 bg-white border-b"
                ):
                    ui.space()
                    ui.button(icon="close", on_click=close_viewer).props(
                        'flat round dense aria-label=' + repr(render_message("webui.select_component.accessible_name.close_viewer_7a596c99"))
                    ).tooltip(render_message("webui.select_component.tooltip.close_viewer_4ef26fde"))
            with content_host:
                with ui.column().classes("w-full h-full items-center justify-center gap-3"):
                    ui.spinner("dots", size="3em", color="primary")
                    ui.label(
                        render_message("webui.select_component.label.converting_this_document_to_pdf_larger_fil_00483fe4")
                        if converting else render_message("webui.select_component.label.loading_the_document_larger_files_may_take_0e9d50c1")
                    ).classes("text-sm text-slate-500")
            try:
                preview = await api.view_draft_component(draft_id, component["id"]) if draft_id is not None else await api.view_component_pdf(component["id"])
            except ApiError as error:
                if request_id != viewer_state["request_id"] or viewer_state["closed"] or (source_active is not None and not source_active()):
                    return
                viewer_state["loading_id"] = None
                render_switcher()
                content_host.clear()
                with content_host:
                    with ui.column().classes("w-full h-full items-center justify-center gap-3"):
                        ui.icon("error_outline", color="negative", size="42px")
                        ui.label(error_message(error)).classes("text-sm text-negative")
                        ui.label(render_message("webui.select_component.label.choose_another_component_or_try_this_compo_ad8750a1")).classes(
                            "text-xs text-slate-500"
                        )
                return

            if request_id != viewer_state["request_id"] or viewer_state["closed"] or (source_active is not None and not source_active()):
                return
            viewer_state["loading_id"] = None
            render_switcher()

            preview_kind = native_preview_kind(component.get("mime_type"))
            toolbar_host.clear()
            content_host.clear()
            with toolbar_host:
                with ui.row().classes(
                    "component-viewer-toolbar w-full items-center no-wrap px-4 py-2 bg-white border-b"
                ):
                    ui.space()
                    if not preview_kind:
                        canvas_id = f"erms-pdf-canvas-{record['id']}-{component['id']}"
                        viewer_state["canvas_id"] = canvas_id
                        ui.button(icon="chevron_left", on_click=lambda: viewer_client.run_javascript(
                            f"window.ermsPdfViewer.previous({json.dumps(canvas_id)})"
                        )).props('flat round dense aria-label=' + repr(render_message("webui.select_component.accessible_name.previous_page_9be2e903"))).tooltip(render_message("webui.select_component.tooltip.previous_page_4dc31a67"))
                        ui.label(render_message("webui.select_component.label.loading_db611d00")).props(f'id={canvas_id}-status').classes(
                            "text-sm text-slate-500 min-w-32 text-center"
                        )
                        ui.button(icon="chevron_right", on_click=lambda: viewer_client.run_javascript(
                            f"window.ermsPdfViewer.next({json.dumps(canvas_id)})"
                        )).props('flat round dense aria-label=' + repr(render_message("webui.select_component.accessible_name.next_page_7783d4cb"))).tooltip(render_message("webui.select_component.tooltip.next_page_9877cd5a"))
                        ui.button(icon="zoom_out", on_click=lambda: viewer_client.run_javascript(
                            f"window.ermsPdfViewer.zoomOut({json.dumps(canvas_id)})"
                        )).props('flat round dense aria-label=' + repr(render_message("webui.select_component.accessible_name.zoom_out_23d40a31"))).tooltip(render_message("webui.select_component.tooltip.zoom_out_011b8edf"))
                        ui.button(icon="zoom_in", on_click=lambda: viewer_client.run_javascript(
                            f"window.ermsPdfViewer.zoomIn({json.dumps(canvas_id)})"
                        )).props('flat round dense aria-label=' + repr(render_message("webui.select_component.accessible_name.zoom_in_1db29908"))).tooltip(render_message("webui.select_component.tooltip.zoom_in_5062398d"))
                    if (
                        capabilities.get("print_component")
                        and preview_kind not in {"audio", "video"}
                    ):
                        print_button = ui.button(icon="print").props(
                            'flat round dense aria-label=' + repr(render_message("webui.select_component.accessible_name.print_document_ce8c78a3"))
                        )
                        print_button.on(
                            "click",
                            lambda: print_component(component),
                            js_handler=(
                                "() => { const w = window.open('', '_blank'); "
                                "window.__ermsPrintWindow = w; "
                                "if (w) { w.document.write('<title>Preparing print view...</title>"
                                "<p style=\"font:16px Arial;padding:24px\">Preparing print view...</p>'); "
                                "w.document.close(); } emit(); }"
                            ),
                        )
                        print_button.tooltip(render_message("webui.select_component.tooltip.print_document_224d0560"))
                    if capabilities.get("download_component"):
                        ui.button(
                            icon="download", on_click=lambda: download_component(component),
                        ).props('flat round dense aria-label=' + repr(render_message("webui.select_component.accessible_name.download_original_45d7f998"))).tooltip(render_message("webui.select_component.tooltip.download_original_24db5a23"))
                    ui.button(icon="close", on_click=close_viewer).props(
                        'flat round dense aria-label=' + repr(render_message("webui.select_component.accessible_name.close_viewer_7a596c99"))
                    ).tooltip(render_message("webui.select_component.tooltip.close_viewer_4ef26fde"))

            if preview_kind:
                mime_type = component.get("mime_type") or render_message("webui.select_component.text.application_octet_stream_775de0d3")
                data_url = f"data:{mime_type};base64,{base64.b64encode(preview).decode('ascii')}"
                with content_host:
                    with ui.element("div").classes(
                        "w-full h-full overflow-auto flex items-center justify-center p-6"
                    ):
                        if preview_kind == "image":
                            ui.image(data_url).classes(
                                "max-w-full max-h-[calc(100vh-150px)] object-contain shadow-lg"
                            )
                        elif preview_kind == "audio":
                            with ui.card().classes("w-[680px] max-w-full p-8"):
                                ui.icon("audio_file", size="72px").classes("self-center text-primary")
                                ui.label(component["file_name"]).classes("self-center font-semibold")
                                ui.audio(data_url, controls=True).classes("w-full")
                        else:
                            ui.video(data_url, controls=True).classes(
                                "w-full max-w-[1200px] max-h-[calc(100vh-150px)] bg-black"
                            )
                return

            canvas_id = viewer_state["canvas_id"]
            with content_host:
                with ui.element("div").classes(
                    "w-full h-full overflow-auto flex justify-center items-start p-5"
                ):
                    ui.element("canvas").props(f"id={canvas_id} dir=ltr").classes("bg-white shadow-lg")
            encoded = base64.b64encode(preview).decode("ascii")
            try:
                await viewer_client.run_javascript(
                    "import('/static/pdfjs/erms-viewer.mjs').then(() => true)", timeout=15,
                )
                if request_id != viewer_state["request_id"] or viewer_state["closed"] or (source_active is not None and not source_active()):return
                await viewer_client.run_javascript(
                    f"window.ermsPdfViewer.open({json.dumps(canvas_id)}, {json.dumps(encoded)})",
                    timeout=30,
                )
            except TimeoutError:
                ui.notify(render_message("webui.select_component.notify.the_pdf_viewer_did_not_finish_loading_f32f23d1"), color="negative")

        with dialog, ui.card().classes("w-full h-full p-0 gap-0 bg-slate-100"):
            if draft_id is not None:
                ui.label(render_message("components.staged.preview_hint")).classes("w-full px-4 py-2 text-sm text-slate-600 bg-white")
            switcher_host = ui.column().classes("w-full gap-0 shrink-0")
            toolbar_host = ui.column().classes("w-full gap-0 shrink-0")
            content_host = ui.column().classes("w-full grow min-h-0 gap-0")
        dialog.on_value_change(lambda event: close_viewer() if not event.value and not viewer_state["closed"] else None)
        dialog.open()
        await select_component(selected)

    return preview_record_components
