"""Record detail view and existing actions with explicit shared destinations."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from .entities import ENTITIES
import asyncio
from frontend.webui.disposition.messages import status_label as disposition_status_label
from frontend.webui.disposition.messages import text as disposition_text
from .resource_relationships import relationship_panel
from .i18n_catalogue import render_message
from nicegui import ui
from .resource_detail_header import detail_action_group, detail_read, metadata_layout, open_details_dialog, read_closure, render_resource_detail_header

def build_record_details(
    *, add_button, add_record_button, add_resource_to_hold_dialog, aggregation_mode_bar, api, bind_remote_relationship_select, breadcrumb_back, browse_advanced_aggregation, clear_collection, current_direction, enter_record_details, error_message, favourite_button, format_timestamp, get_aggregation_detail, get_relationship_page_token, get_resource, guidance, hold_reason_dialog, invalidate_contained_records, load_recent, medium_label, open_aggregation, open_editor, open_related_resource, preview_record_components, principal, record_state, register_navigation, review_datetime_input_minimum, review_datetime_input_value, review_datetime_payload, review_display, search_bar, select_entity, set_relationship_page_token, show_access_explanation, show_acl_editor, show_authenticated_view, show_components, render_effective_holds, show_entity_history, show_governed_move, show_security_level_change, subtitle, table_container, title,
):
    async def show_record_details(record: dict[str, Any]) -> None:
        """Navigate to the dedicated details page for a record."""
        await select_record_details(record["id"])


    async def select_record_details(record_id: int, *, details_tab: str | None = None) -> None:
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
        title.text = ""
        subtitle.text = ""
        guidance.text = ""
        table_container.clear()

        def active():
            return (get_resource() == "record-details"
                    and get_relationship_page_token() is relationship_token
                    and principal() is relationship_principal)

        def notify_error(error):
            if active():
                ui.notify(error_message(error), color="negative", close_button=True)

        try:
            record = await api.get("records", record_id)
        except ApiError as error:
            notify_error(error)
            return
        if not active():
            return

        capabilities = {}
        closure = None
        closure_known = False

        async def get_holds():
            return await api.effective_holds("record", record_id)

        register_navigation(
            "record-details", record["title"], entity_id=record_id,
            accessible_label=f"{record['title']} — {record['record_number']}",
        )

        async def refresh_record_view(saved: dict[str, Any] | None = None, *, section="metadata") -> None:
            invalidate_contained_records(record.get("aggregation_id"))
            if saved and saved.get("aggregation_id") != record.get("aggregation_id"):
                invalidate_contained_records(saved.get("aggregation_id"))
            if active():
                await select_record_details((saved or record)["id"], details_tab=section)

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
                parent = await api.get("aggregations", record["aggregation_id"])
                if active():
                    close_details()
                    await open_aggregation(parent, from_authorized_read=True)
            except ApiError as error:
                notify_error(error)

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
                        invalidate_contained_records(record.get("aggregation_id"))
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
                await refresh_record_view(section="holds")

            await hold_reason_dialog(
                render_message("webui.hold_reason_dialog.remove_all_confirmation"),
                render_message("webui.open_aggregation.button.remove_direct_holds_d5ecb7ae"),
                remove,
            )

        async def read_aggregation(aggregation_id):
            try:
                return await api.get("aggregations", aggregation_id)
            except ApiError as error:
                if error.status_code not in {403, 404}:
                    raise
                return None

        async def get_location(source_id):
            if source_id == parent_id:
                return await asyncio.shield(parent_read)
            return await read_aggregation(source_id)

        async def load_metadata():
            location_ids = {
                record.get("effective_assigned_location_source_aggregation_id"),
                record.get("effective_current_location_source_aggregation_id"),
            } - {None}

            security_level, owning_org_unit, locations = await asyncio.gather(
                api.get("security-levels", record["security_level_id"]),
                api.get("org-units", record["owning_org_unit_id"]),
                asyncio.gather(*(get_location(source_id) for source_id in location_ids)),
            )
            if not active():
                return
            location_sources = dict(zip(location_ids, locations))
            facts, actions = metadata_layout()
            with facts:
                if closure:
                    with ui.row().classes("detail-status-notice w-full items-start no-wrap gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg"):
                        ui.icon("lock", color="amber-8", size="18px").classes("shrink-0")
                        with ui.column().classes("detail-status-notice-copy gap-0 grow min-w-0"):
                            ui.label(render_message("webui.open_aggregation.badge.closed_30c24826")).classes("text-sm font-semibold text-amber-900")
                            ui.label(render_message("webui.select_record_details.label.this_record_is_read_only_because_its_aggre_39233ef1")).classes("text-xs text-amber-800 break-words")
                if record.get("is_vital"):
                    with ui.row().classes(
                        "detail-status-notice w-full items-start no-wrap gap-2 p-3 bg-red-50 border border-red-200 rounded-lg"
                    ):
                        ui.icon("emergency", color="red-8", size="18px").classes("shrink-0")
                        with ui.column().classes("detail-status-notice-copy gap-0 grow min-w-0"):
                            ui.label(render_message("webui.select_record_details.label.vital_record_26408a5c")).classes("text-sm font-semibold text-red-900")
                            ui.label(
                                render_message("webui.select_record_details.label.this_record_is_protected_from_deletion_whi_70e8fed6")
                            ).classes("text-xs text-red-800 break-words")
                with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-0"):
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
                            else parent,
                        ),
                    ])
                    def render_fields(fields):
                        for field_key, label, value in fields:
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
                    secondary = {"security_level", "inherited_assigned_location", "inherited_current_location", "review"}
                    render_fields(field for field in record_metadata if field[0] not in secondary)
                    with ui.column().classes("detail-field col-span-full gap-1"):
                        ui.label(
                            render_message("webui.select_record_details.label.description_918dd932")
                        ).classes("detail-field-label")
                        ui.label(record.get("description") or "—").props("dir=auto").classes(
                            "detail-field-value whitespace-pre-wrap break-words leading-6"
                        )
                    with ui.expansion(render_message("resource_details.advanced_metadata")).classes("w-full col-span-full"):
                        with ui.grid(columns=2).classes("w-full gap-x-4"):
                            render_fields(field for field in record_metadata if field[0] in secondary)

            with actions:
                ui.label(render_message("webui.select_record_details.label.record_actions_ae672368")).classes("text-xs font-semibold text-slate-600 px-2")
                if closure_known and closure is None and capabilities.get("modify_metadata"):
                    ui.button(
                        render_message("webui.select_record_details.button.edit_metadata_d7742b94"), icon="edit",
                        on_click=lambda: open_editor(
                            record, on_saved=refresh_record_view, resource_key="records",
                        ),
                    ).props("flat dense no-caps align=start").classes("w-full text-start")
                ui.button(
                    render_message("webui.select_record_details.button.event_history_89d2205e"), icon="history",
                    on_click=lambda: show_entity_history("records", record),
                ).props("flat dense no-caps align=start").classes("w-full text-start")
                with (
                    ui.expansion(render_message("webui.select_record_details.expansion.advanced_73101adb"), value=False)
                    .props("dense").classes("resource-advanced-actions w-full"),
                    ui.column().classes("w-full gap-3 pb-2"),
                ):
                    with detail_action_group(render_message("webui.open_aggregation.label.metadata_and_review_8b297ce3")) as metadata_review:
                        metadata_review.set_visibility(bool(
                            capabilities.get("change_vital_status") or capabilities.get("change_review_date")
                        ))

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
                            ui.button(
                                render_message("webui.select_record_details.button.vital_status_e3b08bfe"), icon="emergency", on_click=change_vital,
                            ).props("flat dense no-caps align=start").classes("w-full text-start").tooltip(
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
                            ui.button(
                                render_message("webui.select_record_details.button.next_review_4e7a14e8"), icon="event", on_click=change_record_review_date,
                            ).props("flat dense no-caps align=start").classes("w-full text-start").tooltip(
                                render_message("webui.select_record_details.tooltip.schedule_or_clear_this_record_s_next_gover_b9fd992b")
                            )
                    with detail_action_group(render_message("webui.open_aggregation.label.security_access_and_audit_503e702e")):
                        if capabilities.get("change_security_level"):
                            ui.button(
                                render_message("webui.select_record_details.button.security_level_2f483a84"), icon="security",
                                on_click=lambda: show_security_level_change(
                                    "record", record, refresh_record_view,
                                ),
                            ).props("flat dense no-caps align=start").classes("w-full text-start").tooltip(
                                render_message("webui.select_record_details.tooltip.change_the_record_security_level_8289e1f4")
                            )
                        ui.button(
                            render_message("webui.select_record_details.button.why_this_access_a28abcce"), icon="fact_check",
                            on_click=lambda: show_access_explanation("record", record["id"]),
                        ).props("flat dense no-caps align=start").classes("w-full text-start").tooltip(
                            render_message("webui.select_record_details.tooltip.explain_the_authorization_decision_gate_by_cc6d9083")
                        )
                        if capabilities.get("manage_acl"):
                            ui.button(
                                render_message("webui.select_record_details.button.access_489ef75d"), icon="policy",
                                on_click=lambda: show_acl_editor(
                                    "records", record["id"], on_saved=lambda: refresh_record_view(),
                                ),
                            ).props("flat dense no-caps align=start").classes("w-full text-start")

                    editable = closure_known and closure is None
                    show_move = editable and capabilities.get("move")
                    show_delete = editable and capabilities.get("delete")
                    show_reindex = capabilities.get("reindex_components")
                    if show_move or show_reindex or show_delete:
                        with detail_action_group(render_message("resource_details.record_management")):
                            if show_move:
                                ui.button(
                                    render_message("webui.select_record_details.button.move_d812404c"), icon="drive_file_move",
                                    on_click=lambda: show_governed_move("records", record, refresh_record_view),
                                ).props("flat dense no-caps align=start").classes("w-full text-start")
                            if show_reindex:
                                ui.button(
                                    render_message("webui.select_record_details.button.reindex_components_c8b4317c"), icon="manage_search",
                                    on_click=reindex_record_components,
                                ).props("flat dense no-caps align=start").classes("w-full text-start").tooltip(
                                    render_message("webui.select_record_details.tooltip.queue_a_background_reindex_for_every_eligi_b41c4630")
                                )
                            if show_delete:
                                ui.button(
                                    render_message("webui.select_record_details.button.delete_962597c5"), icon="delete_outline", color="negative",
                                    on_click=confirm_delete_record,
                                ).props("flat dense no-caps align=start").classes("w-full text-start")

        async def load_holds():
            holds = await get_holds()
            if not active():
                return
            if holds:
                render_effective_holds(holds, "record", record_id,
                                       lambda: refresh_record_view(section="holds"), close_details)
            else:
                ui.label(render_message("resource_details.no_active_holds"))
            with ui.row().classes("w-full gap-2 flex-wrap"):
                if capabilities.get("add_to_hold"):
                    ui.button(
                        render_message("webui.select_record_details.button.add_to_hold_e811b460"), icon="add_link",
                        on_click=lambda: add_resource_to_hold_dialog(
                            "record", record_id, lambda: refresh_record_view(section="holds"),
                        ),
                    ).props("outline dense no-caps color=primary")
                if capabilities.get("remove_all_direct_hold_assignments"):
                    ui.button(
                        render_message("webui.select_record_details.button.remove_direct_holds_4c99e462"),
                        icon="link_off", on_click=remove_record_from_all_holds,
                    ).props("outline dense no-caps color=negative")

        async def follow_relationship(kind, target):
            close_details()
            await open_related_resource(kind, target)

        async def load_relationships():
            await relationship_panel(
                api=api, kind="record", identity=record_id,
                source_label=f"{record['record_number']} · {record['title']}",
                can_link="relationships.link" in (principal() or {}).get("global_privileges", []),
                active=active, open_target=follow_relationship, bind_remote=bind_remote_relationship_select,
                on_error=error_message, browse_resource=browse_advanced_aggregation,
            )

        def render_actions():
            favourite_button("records", record_id)
            if record.get("medium") != "physical" and capabilities.get("has_previewable_component"):
                ui.button(
                    icon="visibility", on_click=lambda: preview_record_components(record),
                ).props(
                    'flat round dense color=primary aria-label=' + repr(render_message("webui.select_record_details.accessible_name.preview_digital_components_d68f8cab"))
                ).tooltip(render_message("webui.select_record_details.tooltip.preview_digital_components_b4905386"))
            ui.button(
                render_message("webui.select_record_details.button.back_f6cea7ff"),
                icon=None if current_direction["value"] == "rtl" else "arrow_back", on_click=leave_record_page,
            ).props("flat no-caps" + (" icon-right=arrow_forward" if current_direction["value"] == "rtl" else ""))

        parent = None
        parent_id = record.get("aggregation_id")
        parent_host = None

        def render_parent_link():
            if parent_host is None or parent is None:
                return
            parent_host.clear()
            with parent_host, ui.row().classes("items-center gap-x-2 gap-y-0 min-w-0 max-w-full flex-wrap", remove="row"):
                ui.label(render_message("components.record.containing_aggregation")).classes("text-xs text-slate-600")
                with ui.button(on_click=open_containing_aggregation).props("flat dense no-caps").classes(
                    "resource-detail-parent min-w-0 max-w-full text-start px-1",
                ):
                    with ui.row().classes("items-center no-wrap gap-1 min-w-0", remove="row"):
                        ui.icon("folder_open", size="16px").classes("shrink-0")
                        ui.label(parent["name"]).props("dir=auto").classes("min-w-0 break-words underline")

        def render_header_context():
            nonlocal parent_host
            parent_host = ui.column().classes("max-w-full min-w-0 gap-0")
            render_parent_link()

        async def load_parent():
            nonlocal parent
            if parent_read is None:
                return
            parent_row = await detail_read(parent_read, notify_error)
            if not active() or not parent_row:
                return
            parent = {"name": parent_row["title"], "code": parent_row["aggregation_number"]}
            render_parent_link()

        with table_container:
            show_details, close_details, set_details_trigger = open_details_dialog(
                record, record["record_number"],
                {"metadata": load_metadata, "relationships": load_relationships, "holds": load_holds}, active,
            )
            header = ui.column().classes("w-full gap-0")
            with ui.column().classes("w-full px-4 pb-4 gap-0"):
                with ui.column().classes("resource-contents-section w-full gap-0 rounded-lg border border-slate-200"):
                    with ui.row().classes("w-full items-center justify-between gap-2 px-3 py-1 bg-blue-50 rounded-t-lg", remove="row").style("flex-wrap: wrap"):
                        with ui.row().classes("items-center gap-2", remove="row"):
                            ui.icon("attach_file", color="primary", size="18px")
                            ui.label(render_message("webui.select_record_details.label.digital_components_c5a1a49d")).classes("text-sm font-semibold")
                        upload_host = ui.column().classes("max-w-full gap-0")
                    components_host = ui.column().classes("w-full gap-0")
            def read_access():
                return asyncio.gather(
                    detail_read(api.resource_capabilities("records", record_id), notify_error),
                    read_closure(api.effective_record_closure(record_id), notify_error),
                )

            async def load_identity(access):
                nonlocal capabilities, closure, closure_known
                flags, closure_result = await access
                if not active():
                    return
                capabilities = flags or {}
                closure_known, closure = closure_result
                header.clear()
                with header:
                    render_resource_detail_header(
                        record, kind="record", closure=closure, closure_known=closure_known,
                        hold_count=capabilities.get("effective_hold_count"), get_holds=get_holds,
                        open_details=show_details, set_default_trigger=set_details_trigger,
                        format_timestamp=format_timestamp, render_actions=render_actions,
                        render_context=render_header_context,
                    )

            async def refresh_header():
                if active():
                    await load_identity(read_access())

            access = read_access()
            parent_read = asyncio.create_task(read_aggregation(parent_id)) if parent_id else None
            await asyncio.gather(load_identity(access), load_parent(),
                                 show_components(record, container=components_host, active=active,
                                                 upload_host=upload_host, drop_scope=table_container,
                                                 load_access=access, on_refresh=refresh_header))
            if not active():
                return
            if details_tab:
                await show_details(details_tab)


    return show_record_details, select_record_details
