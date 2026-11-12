"""Record detail view and existing actions with explicit shared destinations."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from .entities import ENTITIES
from .record_presentation import RECORD_DETAIL_HEADER_CLASSES
from .record_presentation import RECORD_DETAIL_TITLE_CLASSES
import asyncio
from frontend.webui.disposition.messages import status_label as disposition_status_label
from frontend.webui.disposition.messages import text as disposition_text
from .resource_relationships import relationship_panel
from .i18n_catalogue import render_message
from nicegui import ui

def build_record_details(
    *, add_button, add_record_button, add_resource_to_hold_dialog, aggregation_mode_bar, api, bind_remote_relationship_select, breadcrumb_back, browse_advanced_aggregation, clear_collection, current_direction, decorate_for_spec, enter_record_details, error_message, favourite_button, format_timestamp, get_aggregation_detail, get_relationship_page_token, get_resource, guidance, hold_reason_dialog, load_recent, medium_label, open_aggregation, open_editor, open_related_resource, preview_record_components, principal, record_state, register_navigation, review_datetime_input_minimum, review_datetime_input_value, review_datetime_payload, review_display, search_bar, select_entity, set_relationship_page_token, show_access_explanation, show_acl_editor, show_authenticated_view, show_components, show_effective_holds_dialog, show_entity_history, show_governed_move, show_security_level_change, subtitle, table_container, title,
):
    async def show_record_details(record: dict[str, Any]) -> None:
        """Navigate to the dedicated details page for a record."""
        await select_record_details(record["id"])


    async def select_record_details(record_id: int) -> None:
        relationship_token = object()
        relationship_principal = principal()
        set_relationship_page_token(relationship_token)
        register_navigation("record-details", f"Record #{record_id}", entity_id=record_id)
        previous_resource = get_resource()
        if previous_resource != "record-details":
            record_state["record_detail_return_resource"] = previous_resource
            record_state["record_detail_return_aggregation"] = get_aggregation_detail()
        show_authenticated_view()
        enter_record_details(); record_state.update(record_detail_id=record_id); clear_collection()
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        table_container.clear()

        try:
            fetched = await api.get("records", record_id)
            record = (await decorate_for_spec(ENTITIES["records"], [fetched]))[0]
            security_level, owning_org_unit, capabilities, effective_holds = await asyncio.gather(
                api.get("security-levels", record["security_level_id"]),
                api.get("org-units", record["owning_org_unit_id"]),
                api.resource_capabilities("records", record_id),
                api.effective_holds("record", record_id),
            )
            location_source_ids = {
                record.get("effective_assigned_location_source_aggregation_id"),
                record.get("effective_current_location_source_aggregation_id"),
            } - {None}
            location_sources = {
                source_id: await api.get("aggregations", source_id)
                for source_id in location_source_ids
            }
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return

        title.text = record["title"]
        subtitle.text = render_message("webui.select_record_details.text.record_record_number_6c5c5dcc", record_number=record['record_number'])
        register_navigation(
            "record-details", record["title"], entity_id=record_id,
            accessible_label=f"{record['title']} — {record['record_number']}",
        )

        async def refresh_record_view(saved: dict[str, Any] | None = None) -> None:
            await select_record_details((saved or record)["id"])

        async def reindex_record_components() -> None:
            try:
                result=await api.reindex_record(record["id"])
                ui.notify(
                    render_message("webui.reindex_record_components.notify.reindex_batch_queued_queued_new_already_in_952147c5", queued=result['queued'], already_in_progress=result['already_in_progress'], unsupported_or_no_content=result['unsupported_or_no_content']),
                    color="info",close_button=True,
                )
            except ApiError as error:
                ui.notify(error_message(error),color="negative",close_button=True)

        async def leave_record_page() -> None:
            await breadcrumb_back(lambda: select_entity("records"))

        async def open_containing_aggregation() -> None:
            try:
                await open_aggregation(await api.get("aggregations", record["aggregation_id"]))
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)

        async def confirm_delete_record() -> None:
            confirmation = ui.dialog()
            try:
                component_total = await api.component_count(record["id"])
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                return
            with confirmation, ui.card().classes("w-[500px] max-w-full"):
                ui.label(render_message("webui.confirm_delete_record.label.delete_record_44486e61")).classes("text-xl font-semibold")
                ui.label(
                    render_message("webui.confirm_delete_record.label.record_number_title_will_be_permanently_de_fd38dfa9", record_number=record['record_number'], title=record['title'])
                ).classes("text-sm text-slate-700")
                if component_total:
                    ui.label(
                        render_message("webui.confirm_delete_record.label.its_component_count_digital_component_valu_7b85da08", component_count=component_total, value='s' if component_total != 1 else '')
                    ).classes("text-sm font-medium text-negative")
                ui.label(render_message("webui.confirm_delete_record.label.the_immutable_event_history_will_be_retain_daa89bf7")).classes("text-xs text-slate-500")

                async def delete_record() -> None:
                    try:
                        await api.delete("records", record["id"], record["version"])
                        confirmation.close()
                        ui.notify(render_message("webui.delete_record.notify.record_deleted_87ce6f8a"), color="positive")
                        await load_recent(ENTITIES["records"])
                        await leave_record_page()
                    except ApiError as error:
                        ui.notify(error_message(error), color="negative", close_button=True)

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.confirm_delete_record.button.cancel_8987a97b"), on_click=confirmation.close).props("flat no-caps")
                    ui.button(
                        render_message("webui.confirm_delete_record.button.delete_record_2a62e6e1"), icon="delete_forever", color="negative",
                        on_click=delete_record,
                    ).props("unelevated no-caps")
            confirmation.open()

        async def remove_record_from_all_holds() -> None:
            async def remove(reason: str) -> None:
                await api.remove_all_direct_holds("record", record_id, reason)
                ui.notify(render_message("webui.remove.notify.record_removed_from_all_directly_assigned_3c5f5d03"), color="positive")
                await select_record_details(record_id)

            await hold_reason_dialog(
                render_message("webui.hold_reason_dialog.remove_all_confirmation"),
                render_message("webui.open_aggregation.button.remove_direct_holds_d5ecb7ae"),
                remove,
            )

        with table_container, ui.column().classes("w-full p-5 gap-5"):
            with ui.element("div").classes("record-command-layout w-full"):
                with ui.column().classes("record-command-controls"):
                    with ui.card().classes("detail-surface w-full shadow-none p-4 gap-3"):
                        ui.label(render_message("webui.select_record_details.label.hold_controls_c055620a")).classes("aggregation-panel-heading w-full")
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            if effective_holds:
                                ui.button(
                                    render_message("webui.select_record_details.button.view_holds_73f90e5b"), icon="visibility",
                                    on_click=lambda: show_effective_holds_dialog(
                                        effective_holds, "record", record_id,
                                        lambda: select_record_details(record_id),
                                    ),
                                ).props("outline dense no-caps color=primary")
                            if capabilities.get("add_to_hold"):
                                ui.button(
                                    render_message("webui.select_record_details.button.add_to_hold_e811b460"), icon="add_link",
                                    on_click=lambda: add_resource_to_hold_dialog(
                                        "record", record_id, lambda: select_record_details(record_id),
                                    ),
                                ).props("outline dense no-caps color=primary")
                            if capabilities.get("remove_all_direct_hold_assignments"):
                                ui.button(
                                    render_message("webui.select_record_details.button.remove_direct_holds_4c99e462"), icon="link_off",
                                    on_click=remove_record_from_all_holds,
                                ).props("outline dense no-caps color=negative")
                            if not effective_holds and not capabilities.get("add_to_hold"):
                                ui.label(render_message("webui.select_record_details.label.no_hold_actions_are_available_41ed8e8a")).classes("text-xs text-slate-500")
                    with ui.card().classes("detail-surface w-full shadow-none p-4 gap-3"):
                        ui.label(render_message("webui.select_record_details.label.record_actions_ae672368")).classes("aggregation-panel-heading w-full")
                        ui.label(render_message("webui.select_record_details.label.metadata_and_review_185a8164")).classes("record-action-group-label")
                        record_metadata_actions = ui.row().classes("w-full gap-2 flex-wrap")
                        ui.label(render_message("webui.select_record_details.label.security_access_and_audit_355a3bbe")).classes("record-action-group-label")
                        record_security_actions = ui.row().classes("w-full gap-2 flex-wrap")
                        ui.label(render_message("webui.select_record_details.label.lifecycle_0a37135c")).classes("record-action-group-label")
                        record_lifecycle_actions = ui.row().classes("w-full gap-2 flex-wrap")
                        if not record.get("_effectively_closed") and capabilities.get("move"):
                            with ui.expansion(
                                render_message("webui.select_record_details.expansion.advanced_73101adb"), caption=render_message("record_details.guidance.specialist_actions"),
                                icon="tune", value=False,
                            ).classes("w-full border-t border-slate-100"):
                                record_advanced_actions = ui.row().classes(
                                    "w-full justify-start gap-2 pb-2"
                                )
                        else:
                            record_advanced_actions = None
                record_command_overview = ui.card().classes(
                    "detail-surface record-command-overview w-full shadow-none p-0 gap-0 overflow-hidden"
                )
                record_command_overview.__enter__()
                with ui.row().classes("w-full items-center px-5 py-3 border-b border-slate-100"):
                    ui.icon("description", color="primary", size="21px")
                    ui.label(render_message("webui.select_record_details.label.record_details_4a7ba94d")).classes("font-semibold")
                record_preview_available = (
                    record.get("medium") != "physical"
                    and capabilities.get("has_previewable_component")
                )
                with ui.grid(columns="auto minmax(0, 1fr) auto").classes(
                    f"record-detail-identity-header w-full {RECORD_DETAIL_HEADER_CLASSES} gap-3 px-5 py-5"
                ):
                    ui.avatar(icon="description", color="blue-1", text_color="primary", size="52px")
                    with ui.column().classes(RECORD_DETAIL_TITLE_CLASSES):
                        ui.label(record["record_number"]).classes("text-xs text-primary font-semibold")
                        ui.label(record["title"]).classes("text-lg font-semibold break-words")
                    with ui.grid(
                        columns=f"repeat({3 if record_preview_available else 2}, max-content)"
                    ).classes("record-detail-header-actions items-center gap-2"):
                        favourite_button("records", record["id"])
                        if record_preview_available:
                            ui.button(
                                icon="visibility",
                                on_click=lambda: preview_record_components(record),
                            ).props(
                                'flat round dense color=primary aria-label=' + repr(render_message("webui.select_record_details.accessible_name.preview_digital_components_d68f8cab"))
                            ).tooltip(render_message("webui.select_record_details.tooltip.preview_digital_components_b4905386"))
                        ui.button(
                            render_message("webui.select_record_details.button.back_f6cea7ff"),
                            icon=None if current_direction["value"] == "rtl" else "arrow_back",
                            on_click=leave_record_page,
                        ).props(
                            "flat no-caps color=blue-grey-8"
                            + (" icon-right=arrow_forward" if current_direction["value"] == "rtl" else "")
                        )
                    if capabilities.get("change_security_level"):
                        with record_security_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.security_level_2f483a84"), icon="security",
                                on_click=lambda: show_security_level_change(
                                    "record", record, refresh_record_view,
                                ),
                            ).props("outline dense no-caps").tooltip(render_message("webui.select_record_details.tooltip.change_the_record_security_level_8289e1f4"))
                    if not record.get("_effectively_closed") and capabilities.get("modify_metadata"):
                        with record_metadata_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.edit_metadata_d7742b94"), icon="edit",
                                on_click=lambda: open_editor(
                                    record, on_saved=refresh_record_view, resource_key="records",
                                ),
                            ).props("outline dense no-caps color=primary")
                    if not record.get("_effectively_closed") and capabilities.get("delete"):
                        with record_lifecycle_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.delete_962597c5"), icon="delete_outline", color="negative",
                                on_click=confirm_delete_record,
                            ).props("outline dense no-caps")
                    with record_security_actions:
                        ui.button(
                            render_message("webui.select_record_details.button.event_history_89d2205e"), icon="history",
                            on_click=lambda: show_entity_history("records", record),
                        ).props("outline dense no-caps")
                        ui.button(
                            render_message("webui.select_record_details.button.why_this_access_a28abcce"), icon="fact_check",
                            on_click=lambda: show_access_explanation("record", record["id"]),
                        ).props("outline dense no-caps").tooltip(render_message("webui.select_record_details.tooltip.explain_the_authorization_decision_gate_by_cc6d9083"))
                        if capabilities.get("reindex_components"):
                            ui.button(
                                render_message("webui.select_record_details.button.reindex_components_c8b4317c"),icon="manage_search",
                                on_click=reindex_record_components,
                            ).props("outline dense no-caps").tooltip(
                                render_message("webui.select_record_details.tooltip.queue_a_background_reindex_for_every_eligi_b41c4630")
                            )
                    if capabilities.get("manage_acl"):
                        with record_security_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.access_489ef75d"), icon="policy",
                                on_click=lambda: show_acl_editor(
                                    "records", record["id"], on_saved=lambda: refresh_record_view(),
                                ),
                            ).props("outline dense no-caps")
                    if capabilities.get("change_vital_status"):
                        async def change_vital() -> None:
                            dialog = ui.dialog()
                            with dialog, ui.card().classes("w-[520px] max-w-full"):
                                ui.label(render_message("webui.change_vital.label.change_vital_status_4cad0b01")).classes("text-xl font-semibold")
                                value = ui.checkbox(render_message("webui.change_vital.checkbox.vital_record_1d96a258"), value=bool(record.get("is_vital")))
                                reason = ui.textarea(render_message("webui.change_vital.textarea.reason_6aae1911")).props("outlined autogrow").classes("w-full")
                                async def submit() -> None:
                                    if not (reason.value or "").strip():
                                        ui.notify(render_message("webui.submit.notify.enter_a_reason_f7e81e79"), color="warning"); return
                                    try:
                                        saved = await api.change_vital_status("records", record["id"], record["version"], bool(value.value), reason.value.strip())
                                        dialog.close(); await refresh_record_view(saved)
                                    except ApiError as error: ui.notify(error_message(error), color="negative", close_button=True)
                                ui.button(render_message("webui.change_vital.button.save_9787450d"), on_click=submit).props("unelevated")
                            dialog.open()
                        with record_metadata_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.vital_status_e3b08bfe"), icon="emergency", on_click=change_vital,
                            ).props("outline dense no-caps").tooltip(
                                render_message("webui.select_record_details.tooltip.change_whether_this_record_is_protected_as_f1c5619f")
                            )
                    if capabilities.get("change_review_date"):
                        async def change_record_review_date() -> None:
                            dialog = ui.dialog()
                            with dialog, ui.card().classes("w-[520px] max-w-full"):
                                ui.label(render_message("webui.change_record_review_date.label.schedule_next_review_ea5d874d")).classes("text-xl font-semibold")
                                ui.label(render_message("webui.change_record_review_date.label.set_a_future_date_or_clear_it_when_no_revi_45f20a16")).classes("text-sm text-slate-500")
                                review_date = ui.input(render_message("webui.change_record_review_date.input.date_of_next_review_2e08f279"), value=review_datetime_input_value(record.get("date_of_next_review"))).props(f"outlined clearable type=datetime-local min={review_datetime_input_minimum()}").classes("w-full")
                                reason = ui.textarea(render_message("webui.change_record_review_date.textarea.reason_f2cf789a")).props("outlined autogrow").classes("w-full")
                                async def submit() -> None:
                                    if not (reason.value or "").strip(): ui.notify(render_message("webui.submit.notify.enter_a_reason_f7e81e79"), color="warning"); return
                                    value = review_datetime_payload(review_date.value)
                                    try:
                                        saved = await api.change_review_date("records", record["id"], record["version"], value, reason.value.strip())
                                        dialog.close(); await refresh_record_view(saved)
                                    except (ApiError, ValueError) as error: ui.notify(error_message(error) if isinstance(error, ApiError) else render_message("webui.submit.notify.choose_a_valid_future_date_d0f7285f"), color="negative", close_button=True)
                                ui.button(render_message("webui.change_record_review_date.button.save_67ef4f4f"), on_click=submit).props("unelevated")
                            dialog.open()
                        with record_metadata_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.next_review_4e7a14e8"), icon="event", on_click=change_record_review_date,
                            ).props("outline dense no-caps").tooltip(
                                render_message("webui.select_record_details.tooltip.schedule_or_clear_this_record_s_next_gover_b9fd992b")
                            )
                if record_advanced_actions is not None:
                    with record_advanced_actions:
                        ui.button(
                            render_message("webui.select_record_details.button.move_d812404c"), icon="drive_file_move",
                            on_click=lambda: show_governed_move(
                                "records", record, refresh_record_view,
                            ),
                        ).props("outline dense no-caps")
                ui.separator()
                with ui.column().classes("w-full px-5 py-4 gap-4"):
                    if record.get("_effectively_closed"):
                        with ui.row().classes("detail-status-notice w-full items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg"):
                            ui.icon("lock", color="amber-8")
                            ui.label(render_message("webui.select_record_details.label.this_record_is_read_only_because_its_aggre_39233ef1")).classes("text-sm text-amber-900")
                    if record.get("is_vital"):
                        with ui.row().classes(
                            "detail-status-notice w-full items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg"
                        ):
                            ui.icon("emergency", color="red-8")
                            with ui.column().classes("detail-status-notice-copy gap-0"):
                                ui.label(render_message("webui.select_record_details.label.vital_record_26408a5c")).classes("text-sm font-semibold text-red-900")
                                ui.label(
                                    render_message("webui.select_record_details.label.this_record_is_protected_from_deletion_whi_70e8fed6")
                                ).classes("text-xs text-red-800")
                    if effective_holds:
                        with ui.row().classes(
                            "detail-status-notice w-fit max-w-full items-center gap-2 flex-wrap rounded-xl "
                            "border border-amber-200 bg-amber-50 px-3 py-2"
                        ):
                            ui.icon("gavel", color="warning").classes("shrink-0")
                            hold_count = len(effective_holds)
                            ui.label(
                                render_message("webui.select_record_details.label.protected_by_hold_count_effective_value_fdfb1fe2", hold_count=hold_count)
                            ).classes("text-sm font-semibold text-amber-900")
                            ui.button(
                                render_message("webui.select_record_details.button.view_holds_73f90e5b"), icon="visibility",
                                on_click=lambda: show_effective_holds_dialog(
                                    effective_holds, "record", record_id,
                                    lambda: select_record_details(record_id),
                                ),
                            ).props("flat dense no-caps color=warning")
                    with ui.grid(columns=2).classes("w-full gap-x-8 gap-y-0"):
                        record_metadata = [
                            (
                                "security_level", render_message("entity_metadata.field.security_level"),
                                f"{security_level['code']} — {(security_level.get('localized') or {}).get('name') or security_level['name']}",
                            ),
                            (
                                "owning_org_unit",
                                render_message("advanced_search.field.owning_org_unit"),
                                f"{owning_org_unit['code']} — {(owning_org_unit.get('localized') or {}).get('name') or owning_org_unit['name']}",
                            ),
                            ("medium", render_message("entity_metadata.field.medium"), medium_label(record.get("medium"))),
                            (
                                "vital_status",
                                render_message("webui.select_record_details.button.vital_status_e3b08bfe"),
                                render_message("translation_inspector.value.yes")
                                if record.get("is_vital") else
                                render_message("translation_inspector.value.no"),
                            ),
                            ("originated", render_message("entity_metadata.field.date_originated"), format_timestamp(record.get("date_originated"))),
                            ("created", render_message("advanced_search.field.date_created"), format_timestamp(record.get("date_created"))),
                        ]
                        if record.get("medium") != "digital":
                            record_metadata.extend([
                                (
                                    "inherited_assigned_location",
                                    f'{render_message("entity_metadata.field.assigned_location")} · {render_message("entity_metadata.field.inherited_location")}',
                                    record.get("effective_assigned_location") or render_message("webui.render_detail_content.text.unknown_d3c1ce73"),
                                ),
                                (
                                    "inherited_current_location",
                                    f'{render_message("entity_metadata.field.current_location")} · {render_message("entity_metadata.field.inherited_location")}',
                                    record.get("effective_current_location") or render_message("webui.render_detail_content.text.unknown_d3c1ce73"),
                                ),
                            ])
                        record_metadata.extend([
                            ("disposition_status", disposition_text("status"), disposition_status_label(record.get("disposition_status", 1))),
                            ("review", render_message("entity_metadata.field.review"), review_display(record.get("date_of_next_review"))),
                            # The state disambiguates a protected existing
                            # container from an absent relationship; records
                            # structurally always have a container.
                            (
                                "containing_aggregation",
                                render_message("advanced_search.field.parent_aggregation"),
                                render_message("webui.open_aggregation.label.parent_aggregation_restricted_684099c8")
                                if record.get("aggregation_state") == "redacted"
                                else record.get("aggregation_display"),
                            ),
                        ])
                        for field_key, label, value in record_metadata:
                            with ui.column().classes("detail-field gap-1"):
                                ui.label(label).classes("detail-field-label")
                                if field_key == "containing_aggregation" and isinstance(value, dict):
                                    with ui.button(on_click=open_containing_aggregation).props(
                                        "flat dense no-caps color=primary"
                                    ).classes("detail-linked-entity self-start -m-2 p-2"):
                                        with ui.column().classes("detail-linked-entity-content"):
                                            ui.label(value.get("name") or "—").classes(
                                                "detail-linked-entity-title"
                                            )
                                            if value.get("code"):
                                                ui.label(value["code"]).classes(
                                                    "detail-linked-entity-identifier"
                                                )
                                elif field_key == "vital_status":
                                    ui.badge(
                                        str(value),
                                        color="red-8" if record.get("is_vital") else "blue-grey-7",
                                    ).props("outline")
                                else:
                                    ui.label(str(value or "—")).classes("detail-field-value")
                                    if field_key.startswith("inherited_"):
                                        source_key = "effective_assigned_location_source_aggregation_id" if field_key == "inherited_assigned_location" else "effective_current_location_source_aggregation_id"
                                        source = location_sources.get(record.get(source_key))
                                        if source:
                                            ui.label(render_message("webui.select_record_details.label.inherited_from_aggregation_number_title_ab7fbcfd", aggregation_number=source['aggregation_number'], title=source['title'])).classes("text-xs text-slate-500")
                        with ui.column().classes("detail-field col-span-full gap-1"):
                            ui.label(
                                render_message("webui.select_record_details.label.description_918dd932")
                            ).classes("detail-field-label")
                            ui.label(record.get("description") or "—").props("dir=auto").classes(
                                "detail-field-value whitespace-pre-wrap break-words leading-6"
                            )

                record_command_overview.__exit__(None, None, None)
            await relationship_panel(
                api=api, kind="record", identity=record_id,
                source_label=" · ".join(filter(None, (record.get("record_number"), record.get("title")))),
                can_link="relationships.link" in (principal() or {}).get("global_privileges", []),
                active=lambda: principal() is relationship_principal and get_resource() == "record-details" and get_relationship_page_token() is relationship_token,
                open_target=open_related_resource, bind_remote=bind_remote_relationship_select, on_error=error_message,
                browse_resource=browse_advanced_aggregation,
            )
            with ui.card().classes("detail-surface w-full shadow-none p-5 gap-4"):
                with ui.row().classes("w-full items-center gap-3"):
                    ui.icon("attach_file", color="primary", size="28px")
                    with ui.column().classes("gap-0 grow"):
                        ui.label(render_message("webui.select_record_details.label.digital_components_c5a1a49d")).classes("text-xl font-semibold")
                        ui.label(render_message("webui.select_record_details.label.files_belonging_to_this_record_can_be_mana_7c78350c")).classes("text-sm text-slate-500")
                components_host = ui.column().classes("w-full gap-3")
                await show_components(record, container=components_host)


    return show_record_details, select_record_details
