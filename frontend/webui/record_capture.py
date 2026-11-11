"""Per-dialog record draft capture, staging, validation, commit and abandonment."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from .entities import ENTITIES
from .record_presentation import RECORD_UPLOAD_WAIT_MESSAGE
import asyncio
from nicegui import background_tasks
from .upload_buffers import buffer_upload_batch
from .component_presentation import component_uploader
from nicegui import events
from .entity_editor_controls import field_input
from .entity_editor_controls import form_payload
from .entity_editor_controls import medium_options
from .record_editor import record_draft_component_context
from .entity_selectors import relationship_options
from .i18n_catalogue import render_message
from .relationship_select_styles import style_relationship_chip_select
from nicegui import ui

def build_record_capture(
    *, add_number_suggestion, api, bind_remote_relationship_select, bind_resource_security_select, browse_advanced_aggregation, error_message, load_recent, preview_record_components, render_component_cards, render_table, set_searched, show_number_conflict, validation_error_message,
):
    async def open_record_draft_editor(
        target_aggregation_id: int | None = None, on_committed=None, existing_capture_draft=None, capture_active=None,
        capture_loader=None, capture_dialog=None,
    ) -> None:
        spec = ENTITIES["records"]
        try:
            draft = existing_capture_draft or await api.create_record_draft()
            security_levels, creation_roles = await asyncio.gather(
                api.list("security-levels", limit=25),
                api.creation_role_options(target_aggregation_id),
            )
            target_aggregation = (
                await api.get("aggregations", target_aggregation_id)
                if target_aggregation_id is not None else None
            )
            aggregations_by_id = (
                {target_aggregation["id"]: target_aggregation}
                if target_aggregation is not None else {}
            )
        except ApiError as error:
            if capture_dialog is not None:capture_dialog.close()
            if capture_active is not None and not capture_active():return
            ui.notify(error_message(error), color="negative", close_button=True)
            return

        if capture_active is not None and not capture_active():
            if capture_dialog is not None:capture_dialog.close()
            return

        dialog = capture_dialog or ui.dialog().props("persistent")
        dialog.clear()
        capture_preparation = {"closed": False, "ready": capture_loader is None}
        controls: dict[str, Any] = {}
        current_rows: list[dict[str, Any]] = []
        component_area: Any = None
        upload_lock = asyncio.Lock()
        upload_state = {"pending": 0}
        action_controls: dict[str, Any] = {}
        uploader_control: dict[str, Any] = {}

        async def refresh_draft_components() -> bool:
            try:
                rows = await api.draft_components(draft["id"])
                if capture_active is not None and not capture_active():return
                current_rows.clear()
                current_rows.extend(rows)
                component_area.clear()
                component_list.set_visibility(bool(rows))
                with component_area:
                    if rows:
                        render_component_cards(
                            rows, move_draft_component, remove_draft_component,
                            on_view=lambda component: preview_record_components(
                                None, component["id"], draft_id=draft["id"], staged_components=list(current_rows),
                                source_active=lambda: dialog.value and not dialog._deleted and (capture_active is None or capture_active()),
                            ),
                            readonly=existing_capture_draft is not None, staged_preview=True,
                        )
                return True
            except ApiError as error:
                if capture_active is not None and not capture_active():return
                with component_area:
                    ui.notify(error_message(error), color="negative")
                return False

        async def move_draft_component(component: dict[str, Any], direction: int) -> None:
            index = next((i for i, item in enumerate(current_rows) if item["id"] == component["id"]), -1)
            target = index + direction
            if index < 0 or target < 0 or target >= len(current_rows):
                return
            reordered = list(current_rows)
            reordered[index], reordered[target] = reordered[target], reordered[index]
            try:
                await api.reorder_draft_components(draft["id"], [
                    {"id": item["id"], "component_order": position}
                    for position, item in enumerate(reordered, 1)
                ])
                await refresh_draft_components()
            except ApiError as error:
                ui.notify(error_message(error), color="negative")

        async def remove_draft_component(component: dict[str, Any]) -> None:
            try:
                await api.delete_draft_component(draft["id"], component["id"])
                ui.notify(render_message("webui.remove_draft_component.notify.staged_file_removed_5c3ae99e"), color="positive")
                await refresh_draft_components()
            except ApiError as error:
                ui.notify(error_message(error), color="negative")

        def upload_to_draft(event: events.MultiUploadEventArguments) -> None:
            try:
                buffered_files = buffer_upload_batch(event)
                # Form controls are client-side state. Persist the relationship
                # and medium before the component endpoint validates the draft.
                component_context = record_draft_component_context(
                    target_aggregation_id
                    if target_aggregation_id is not None
                    else controls["aggregation_id"].value,
                    controls["medium"].value,
                )
            except OSError as error:
                ui.notify(render_message("webui.upload_to_draft.notify.could_not_read_an_uploaded_file_error_17327476", error=error), color="negative", close_button=True)
                return
            except ValueError as error:
                ui.notify(validation_error_message(error), color="warning", close_button=True)
                return
            upload_state["pending"] += 1
            action_controls["commit"].disable()
            action_controls["upload_wait"].set_visibility(True)

            async def stage_buffered_files() -> None:
                try:
                    async with upload_lock:
                        await api.update_record_draft(draft["id"], component_context)
                        await refresh_draft_components()
                        first_position = len(current_rows) + 1
                        for offset, (content, name, mime_type) in enumerate(buffered_files):
                            await api.upload_draft_component(
                                draft["id"], first_position + offset, name, content, mime_type,
                            )
                            await refresh_draft_components()
                    with component_area:
                        ui.notify(
                            render_message("webui.stage_buffered_files.notify.buffered_file_count_file_value_staged_for_45b0562d", buffered_file_count=len(buffered_files), value='s' if len(buffered_files) != 1 else ''),
                            color="positive",
                        )
                    uploader_control["uploader"].reset()
                except ApiError as error:
                    with component_area:
                        ui.notify(error_message(error), color="negative", close_button=True)
                finally:
                    upload_state["pending"] -= 1
                    if upload_state["pending"] == 0:
                        action_controls["commit"].enable()
                        action_controls["upload_wait"].set_visibility(False)

            background_tasks.create(
                stage_buffered_files(), name=f"stage components for draft {draft['id']}"
            )

        async def discard() -> None:
            capture_preparation["closed"] = True
            if draft.get("id") is None:
                dialog.close()
                return
            try:
                await api.discard_record_draft(draft["id"])
            except ApiError as error:
                if error.status_code != 404:
                    ui.notify(error_message(error), color="negative")
                    return
            dialog.close()

        async def commit() -> None:
            if not capture_preparation["ready"] or capture_preparation["closed"]:
                return
            if existing_capture_draft is not None:
                action_controls["commit"].disable()
                action_controls["commit"].props("loading")
            try:
                payload = form_payload(spec, controls, creating=True)
                if target_aggregation_id is not None:
                    # The aggregation-details route owns this relationship.
                    # Bind it from route context instead of trusting a
                    # read-only presentation control to submit its value.
                    payload["aggregation_id"] = int(target_aggregation_id)
                creator_role_id = controls["creator_acl_role_id"].value
                if creator_role_id is None:
                    raise ValueError("Select who this record is being created for")
                await api.update_record_draft(draft["id"], payload)
                committed_record = await api.commit_record_draft(
                    draft["id"], int(creator_role_id), capture=existing_capture_draft is not None,
                )
                if capture_active is not None and not capture_active():return
                dialog.close()
                ui.notify(render_message("webui.commit.notify.record_and_digital_components_created_c1c2938b"), color="positive")
                if existing_capture_draft is None:
                    await load_recent(spec)
                if capture_active is not None and not capture_active():return
                if on_committed is not None:
                    await on_committed(committed_record)
                    return
                set_searched(False)
                render_table(spec)
            except ValueError as error:
                ui.notify(validation_error_message(error), color="warning")
            except ApiError as error:
                if capture_active is not None and not capture_active():return
                if await show_number_conflict(error, "records", controls["record_number"]):
                    return
                ui.notify(error_message(error), color="negative", close_button=True)

            finally:
                if existing_capture_draft is not None and (capture_active is None or capture_active()):
                    action_controls["commit"].props(remove="loading")
                    action_controls["commit"].enable()

        with dialog, ui.card().classes("max-h-[calc(100vh-32px)] p-0").style("width: 1050px; max-width: calc(100vw - 32px)"):
            with ui.row().classes("w-full items-center no-wrap px-6 pt-5"):
                ui.avatar(icon="note_add", color="blue-1", text_color="primary")
                with ui.column().classes("gap-0 grow"):
                    ui.label(render_message("webui.open_record_draft_editor.label.create_record_080740e1")).classes("text-xl font-semibold")
                    ui.label(render_message("webui.open_record_draft_editor.label.assemble_the_metadata_and_files_then_creat_ba4447db")).classes("text-sm text-slate-500")
                ui.badge(render_message("webui.open_record_draft_editor.badge.draft_59a3031a"), color="primary").props("outline")
            with ui.element("div").classes("w-full overflow-y-auto px-6 pb-2 max-h-[calc(100vh-190px)]"):
                ui.label(render_message("webui.open_record_draft_editor.label.record_details_e88ae30c")).classes("text-base font-semibold mt-4 mb-2")
                ui.label(render_message("webui.open_record_draft_editor.label.required_fields_40cea53e")).classes("text-xs text-slate-500 -mt-1 mb-2")
                with ui.grid(columns=2).classes("w-full gap-3"):
                    aggregation_field = next(
                        field for field in spec.fields if field.name == "aggregation_id"
                    )
                    controls["aggregation_id"] = field_input(
                        aggregation_field,
                        value=target_aggregation_id,
                        options=relationship_options(
                            list(aggregations_by_id.values()),
                            aggregation_field.lookup_label_fields,
                        ),
                    )
                    controls["aggregation_id"].classes("col-span-2").props("clearable")
                    style_relationship_chip_select(
                        controls["aggregation_id"], "aggregation_id",
                    )
                    if target_aggregation_id is None:
                        async def destinations(query):
                            if len(query.strip()) < 2:
                                return {"items": []}
                            return await api.search_request("aggregations", {
                                "where": {"or": [{"field": field, "operator": "contains_ci", "value": query.strip()}
                                    for field in ("aggregation_number", "title", "description")]},
                                "sort": [{"field": "aggregation_number", "direction": "asc"}], "limit": 25,
                            }, record_creation=True, digital_only=existing_capture_draft is not None)
                        bind_remote_relationship_select(
                            controls["aggregation_id"], "aggregations",
                            ("aggregation_number", "title"),
                            aggregation_field.lookup_label_fields,
                            page_loader=destinations,
                            active=lambda: dialog.value and (capture_active is None or capture_active()),
                        )
                        ui.button(
                            render_message("webui.show_memberships.button.browse_aed12689"),
                            icon="account_tree",
                            on_click=lambda: browse_advanced_aggregation(controls["aggregation_id"], record_creation=True, digital_only=existing_capture_draft is not None),
                        ).props("flat dense no-caps").classes("col-span-2 justify-self-start")
                    if target_aggregation_id is not None:
                        # Read-only keeps the selected parent visible in the
                        # form. Saving is independently guarded by binding the
                        # route's target_aggregation_id into the payload.
                        controls["aggregation_id"].props("readonly")
                        ui.label(
                            render_message("webui.open_record_draft_editor.label.the_parent_aggregation_is_fixed_because_th_767330a4")
                        ).classes("text-xs leading-5 text-slate-500 col-span-2 -mt-2")

                    role_options = {
                        item["role_id"]: item["label"] for item in creation_roles
                    } if target_aggregation_id is not None else {}
                    controls["creator_acl_role_id"] = ui.select(
                        role_options,
                        value=(
                            creation_roles[0]["role_id"]
                            if target_aggregation_id is not None and len(creation_roles) == 1
                            else None
                        ),
                        label=render_message("webui.open_record_draft_editor.select.create_for_857b2d59"),
                    ).props("outlined options-dense").classes("w-full col-span-2")
                    # A sole eligible role is fixed by policy but must remain
                    # visibly populated; readonly avoids the empty rendering
                    # observed with a disabled NiceGUI select.
                    if len(creation_roles) == 1:
                        controls["creator_acl_role_id"].props("readonly")
                    elif not creation_roles:
                        controls["creator_acl_role_id"].disable()
                    ui.label(
                        render_message("webui.open_record_draft_editor.label.select_the_role_that_will_receive_creator_410b59fa")
                    ).classes("text-xs leading-5 text-slate-500 col-span-2 -mt-2")
                    creation_role_status = ui.label(
                        render_message("webui.open_record_draft_editor.label.select_a_parent_aggregation_before_choosin_e92b6402")
                        if target_aggregation_id is None
                        else (
                            render_message("webui.open_record_draft_editor.label.create_for_was_set_automatically_because_y_974126aa")
                            if len(creation_roles) == 1
                            else (
                                render_message("webui.open_record_draft_editor.label.you_do_not_have_an_effective_role_in_the_p_124c1ce3")
                                if not creation_roles
                                else render_message("webui.open_record_draft_editor.label.choose_one_of_your_roles_in_the_parent_agg_e5eca9a8")
                            )
                        )
                    ).props('role="status" aria-live="polite"').classes(
                        "text-xs leading-5 text-amber-800 col-span-2 -mt-2"
                    )
                    for field in spec.fields:
                        if field.name == "aggregation_id":
                            continue
                        lookup_rows = (
                            list(aggregations_by_id.values()) if field.lookup_resource == "aggregations"
                            else security_levels if field.lookup_resource == "security-levels"
                            else []
                        )
                        options = relationship_options(lookup_rows, field.lookup_label_fields) if field.lookup_resource else None
                        initial_value = None
                        if field.name == "security_level_id" and security_levels:
                            initial_value = min(
                                security_levels, key=lambda item: (item["level_number"], item["id"])
                            )["id"]
                        if field.name == "medium":
                            parent = aggregations_by_id.get(controls["aggregation_id"].value)
                            initial_value = parent.get("medium", "mixed") if parent else "mixed"
                        if existing_capture_draft is not None and field.name in draft:
                            initial_value = draft[field.name]
                        controls[field.name] = field_input(field, value=initial_value, options=options)
                        if field.name == "record_number":
                            add_number_suggestion(controls[field.name], "records", controls)
                        if field.name == "security_level_id":
                            bind_resource_security_select(
                                controls[field.name], parent_control=controls["aggregation_id"],
                            )
                        if field.kind == "textarea":
                            controls[field.name].classes("col-span-2")
                    def constrain_record_medium() -> None:
                        parent = aggregations_by_id.get(controls["aggregation_id"].value)
                        medium_control = controls["medium"]
                        if existing_capture_draft is not None:
                            medium_control.set_options({"digital": medium_options()["digital"]}, value="digital")
                            medium_control.disable()
                            return
                        if not parent:
                            medium_control.set_options({"digital": medium_options()["digital"]} if existing_capture_draft is not None else {},
                                                       value="digital" if existing_capture_draft is not None else None)
                            medium_control.disable()
                            return
                        parent_medium = parent.get("medium", "mixed")
                        if parent_medium == "mixed":
                            medium_control.set_options(
                                medium_options(),
                                value=medium_control.value or "mixed",
                            )
                            medium_control.enable()
                        else:
                            medium_control.set_options(
                                {parent_medium: medium_options()[parent_medium]}, value=parent_medium,
                            )
                            medium_control.disable()
                        medium_control.update()
                    async def refresh_record_creation_roles() -> None:
                        aggregation_id = controls["aggregation_id"].value
                        role_control = controls["creator_acl_role_id"]
                        previous_role_id = role_control.value
                        if aggregation_id is None:
                            role_control.set_options({}, value=None)
                            role_control.disable()
                            creation_role_status.set_text(
                                render_message('webui.open_record_draft_editor.label.select_a_parent_aggregation_before_choosin_e92b6402'))
                            return
                        try:
                            rows = await api.creation_role_options(int(aggregation_id))
                            if controls["aggregation_id"].value != aggregation_id or (capture_active is not None and not capture_active()):
                                return
                        except ApiError as error:
                            ui.notify(error_message(error), color="negative", close_button=True)
                            return
                        eligible_role_ids = {item["role_id"] for item in rows}
                        previous_role_was_cleared = (
                            previous_role_id is not None
                            and previous_role_id not in eligible_role_ids
                        )
                        selected_role_id = (
                            previous_role_id if previous_role_id in eligible_role_ids
                            else rows[0]["role_id"] if len(rows) == 1
                            else None
                        )
                        role_control.set_options(
                            {item["role_id"]: item["label"] for item in rows},
                            value=selected_role_id,
                        )
                        role_control.props(remove="readonly")
                        if len(rows) == 1:
                            role_control.enable()
                            role_control.props("readonly")
                        elif rows:
                            role_control.enable()
                        else:
                            role_control.disable()
                        if not rows:
                            creation_role_status.set_text(
                                render_message("webui.open_record_draft_editor.label.you_do_not_have_an_effective_role_in_the_p_124c1ce3")
                            )
                        elif previous_role_was_cleared:
                            creation_role_status.set_text(
                                render_message("messaging.capture.creator_role_cleared")
                            )
                        elif len(rows) == 1:
                            creation_role_status.set_text(
                                render_message('webui.open_record_draft_editor.label.create_for_was_set_automatically_because_y_974126aa'))
                        else:
                            creation_role_status.set_text(
                                render_message('webui.open_record_draft_editor.label.choose_one_of_your_roles_in_the_parent_agg_e5eca9a8'))

                    async def apply_selected_aggregation() -> None:
                        aggregation_id = controls["aggregation_id"].value
                        if (
                            aggregation_id is not None
                            and int(aggregation_id) not in aggregations_by_id
                        ):
                            try:
                                aggregations_by_id[int(aggregation_id)] = await api.get(
                                    "aggregations", int(aggregation_id),
                                )
                            except ApiError as error:
                                ui.notify(error_message(error), color="negative", close_button=True)
                                return
                        if controls["aggregation_id"].value != aggregation_id or (capture_active is not None and not capture_active()):
                            return
                        with dialog:
                            constrain_record_medium()
                            await refresh_record_creation_roles()

                    controls["aggregation_id"].on_value_change(
                        lambda: background_tasks.create(apply_selected_aggregation())
                    )
                    constrain_record_medium()
                with ui.column().classes("w-full gap-0 mt-5 mb-2"):
                    ui.label(render_message("webui.open_record_draft_editor.label.digital_components_21c9474b")).classes("w-full text-start text-base font-semibold")
                    ui.label(render_message("webui.open_record_draft_editor.label.files_remain_staged_until_you_create_the_r_ec0dd8d9")).classes("w-full text-start text-xs text-slate-500")
                with ui.column().classes("w-full") as draft_upload_area:
                    uploader_control["uploader"] = component_uploader(upload_to_draft)
                with ui.row().classes(
                    "w-full items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3"
                ) as physical_draft_notice:
                    ui.icon("inventory_2", color="primary")
                    with ui.column().classes("gap-0 grow"):
                        ui.label(render_message("webui.open_record_draft_editor.label.this_is_a_physical_record_399cc6c8")).classes("font-semibold text-blue-900")
                        ui.label(render_message("webui.open_record_draft_editor.label.digital_files_cannot_be_added_a2f23cff")).classes("text-sm text-blue-800")

                def update_draft_component_controls() -> None:
                    selected_medium = controls["medium"].value
                    draft_upload_area.set_visibility(existing_capture_draft is None and selected_medium in {"digital", "mixed"})
                    physical_draft_notice.set_visibility(selected_medium == "physical")

                controls["medium"].on_value_change(
                    lambda _: update_draft_component_controls()
                )
                controls["aggregation_id"].on_value_change(
                    lambda _: update_draft_component_controls()
                )
                update_draft_component_controls()
                with ui.element("div").classes("component-list w-full mt-3") as component_list:
                    component_area = ui.element("div").classes("component-grid w-full")
                component_list.set_visibility(capture_loader is not None)
                if capture_loader is not None:
                    with component_area:
                        for component in draft.get("components", []):
                            with ui.card().classes("w-full gap-1").props("flat bordered"):
                                with ui.grid(columns="auto minmax(0, 1fr)").classes("w-full items-center gap-2"):
                                    ui.spinner(size="sm")
                                    ui.label(component["title"]).classes("font-semibold grow break-words")
                                ui.label(component["file_name"]).classes("text-xs text-slate-500 break-all")
                                ui.label(render_message("messaging.capture.preparing")).classes("text-sm text-slate-500")
            ui.separator()
            with ui.row().classes("w-full justify-end gap-2 px-6 py-4"):
                with ui.row().classes(
                    "items-center gap-1 text-sm text-slate-500 mr-2"
                ) as upload_wait:
                    ui.icon("hourglass_top", size="18px")
                    ui.label(RECORD_UPLOAD_WAIT_MESSAGE)
                upload_wait.set_visibility(False)
                action_controls["upload_wait"] = upload_wait
                ui.button(render_message("webui.open_record_draft_editor.button.cancel_draft_84ea17b5"), on_click=discard).props("flat color=grey-7").mark("capture-cancel" if capture_loader is not None else "record-draft-cancel")
                action_controls["commit"] = ui.button(render_message("webui.open_record_draft_editor.button.create_record_dd0193d6"), icon="check", on_click=commit).props("unelevated")
                if capture_loader is not None:
                    action_controls["commit"].disable()
                    action_controls["commit"].mark("capture-create")
        dialog.open()
        if capture_loader is not None:
            try:
                prepared = await capture_loader()
            except ApiError as error:
                if not capture_preparation["closed"] and (capture_active is None or capture_active()):
                    action_controls["upload_wait"].set_visibility(False)
                    component_area.clear()
                    with component_area:
                        ui.label(error_message(error)).classes("text-negative").mark("capture-preparation-error")
                else:
                    dialog.close()
                return
            if capture_preparation["closed"] or (capture_active is not None and not capture_active()):
                await api.discard_record_draft(prepared["id"])
                dialog.close()
                return
            # Keep metadata the user has edited while conversion was running.
            # The server rechecks the chain and its security floor at commit.
            draft = prepared
            components_loaded = await refresh_draft_components()
            if capture_preparation["closed"] or (capture_active is not None and not capture_active()):
                if not capture_preparation["closed"]:
                    await api.discard_record_draft(prepared["id"])
                dialog.close()
                return
            if not components_loaded:
                return
            capture_preparation["ready"] = True
            action_controls["upload_wait"].set_visibility(False)
            action_controls["commit"].enable()
            return
        await refresh_draft_components()


    return open_record_draft_editor
