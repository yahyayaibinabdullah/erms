"""Existing aggregation behavior with explicit view dependencies."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from .entities import ENTITIES
from frontend.webui.disposition.screens import accelerate_dialog
import asyncio
from .locale_services import current_locale_context
from datetime import datetime
from .aggregation_presentation import direct_classification_label
from frontend.webui.disposition.messages import status_label as disposition_status_label
from frontend.webui.disposition.messages import text as disposition_text
from .resource_relationships import relationship_panel
from .retention_timeline import render_disposition_date
from .i18n_catalogue import render_message
from .i18n_catalogue import render_message_plain
from .retention_timeline import render_retention_stages
from datetime import timezone
from nicegui import ui
from .creator_labels import render_creator_name
from .resource_detail_header import detail_action_group, detail_read, metadata_layout, open_details_dialog, read_closure, render_resource_detail_header

def build_aggregation_details(
    *, add_button, add_record_button, add_child, add_record, add_resource_to_hold_dialog, aggregation_mode_bar, aggregation_state, api, bind_remote_relationship_select, breadcrumb_back, browse_advanced_aggregation, current_direction, enter_details, error_message, favourite_button, format_timestamp, get_configuration, get_record_detail_id, get_relationship_page_token, get_resource, guidance, hold_reason_dialog, load_recent, localized_disposition_value, medium_label, open_editor, open_related_resource, principal, register_navigation, render_compact_resource_result, restore_compact_result_anchor, review_datetime_input_minimum, review_datetime_input_value, review_datetime_payload, review_display, search_bar, select_classification_workspace, select_entity, set_relationship_page_token, show_access_explanation, show_acl_editor, show_authenticated_view, render_effective_holds, show_entity_history, show_governed_move, show_ownership_correction, show_record_details, show_reopen_aggregation, show_security_level_change, subtitle, table_container, title,
):
    async def open_aggregation(aggregation: dict[str, Any], *, details_tab: str | None = None,
                               from_authorized_read: bool = False, refresh_contents: bool = False) -> None:
        show_authenticated_view()
        relationship_token = object()
        relationship_principal = principal()
        set_relationship_page_token(relationship_token)
        register_navigation(
            "aggregation-details", aggregation.get("title") or f"Aggregation #{aggregation['id']}",
            entity_id=aggregation["id"],
            accessible_label=" — ".join(filter(None, (
                aggregation.get("title"), aggregation.get("aggregation_number"),
            ))),
        )
        previous_resource = get_resource()
        if previous_resource != "aggregation-details":
            aggregation_state["aggregation_detail_return_resource"] = previous_resource
            aggregation_state["aggregation_detail_return_record_id"] = get_record_detail_id()
        enter_details()
        def active():
            return (get_resource() == "aggregation-details"
                    and get_relationship_page_token() is relationship_token
                    and principal() is relationship_principal)

        def notify_error(error):
            if active():
                ui.notify(error_message(error), color="negative", close_button=True)

        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        title.text = ""
        subtitle.text = ""
        guidance.text = ""
        table_container.clear()
        try:
            current = aggregation if from_authorized_read else await api.get("aggregations", aggregation["id"])
            if not active():
                return
            if current.get("title") != aggregation.get("title"):
                register_navigation(
                    "aggregation-details", current["title"], entity_id=current["id"],
                    accessible_label=f"{current['title']} — {current['aggregation_number']}",
                )
            identifier = int(current["id"])
            aggregation_state["aggregation_detail"] = current
            client = table_container.client
            capabilities = {}
            closure = None
            closure_known = False
            hold_count = None
            child_total = None
            all_record_total = None
            classification_path = []
            # Paths are authorized for this mounted page. Refreshing or leaving
            # the page discards them with the other detail data.
            classification_paths = {}
            local_retention_rule = None
            aggregation_context_by_id = {identifier: current}
            is_root = not current.get("parent_aggregation_id") and current.get("parent_aggregation_state") != "redacted"

            async def get_holds():
                return await api.effective_holds("aggregation", identifier)

            async def refresh(saved=None, *, section="metadata"):
                if active():
                    await open_aggregation(saved or current, details_tab=section, refresh_contents=True)

            with table_container:
                async def leave_aggregation_page() -> None:
                    await breadcrumb_back(lambda: select_entity("aggregations"))

                async def open_parent_aggregation() -> None:
                    parent = aggregation_context_by_id.get(current.get("parent_aggregation_id"))
                    if parent:
                        close_details()
                        await open_aggregation(parent)

                async def open_parent_classification() -> None:
                    path = await metadata_classification_path()
                    if not path or not active():
                        return
                    close_details()
                    classification = path[-1]
                    await select_classification_workspace(
                        initial_scheme_id=classification["classification_scheme_id"],
                        initial_classification_id=classification["id"],
                    )

                async def remove_aggregation_from_all_holds() -> None:
                    async def remove(reason: str) -> None:
                        await api.remove_all_direct_holds("aggregation", current["id"], reason)
                        ui.notify(render_message("webui.remove.notify.aggregation_removed_from_all_directly_assi_dfa06ec9"), color="positive")
                        await refresh(section="holds")

                    await hold_reason_dialog(
                        render_message("webui.hold_reason_dialog.remove_all_confirmation"),
                        render_message("webui.open_aggregation.button.remove_direct_holds_d5ecb7ae"),
                        remove,
                    )

                async def reopen_current() -> None:
                    async def reopened(saved: dict[str, Any]) -> None:
                        await load_recent(ENTITIES["aggregations"])
                        await refresh(saved)

                    await show_reopen_aggregation(current, reopened)

                async def close_current() -> None:
                    try:
                        closed = await api.update(
                            "aggregations", current["id"], current["version"],
                            {"date_closed": datetime.now(timezone.utc).isoformat()},
                        )
                        ui.notify(render_message("webui.close_current.notify.aggregation_closed_cf4843ed"), color="positive")
                        await load_recent(ENTITIES["aggregations"])
                        await refresh(closed)
                    except ApiError as error:
                        ui.notify(error_message(error), color="negative", close_button=True)

                async def manage_local_retention_rule() -> None:
                    dialog = ui.dialog()
                    existing = local_retention_rule or {}
                    with dialog, ui.card().classes("w-[680px] max-w-full"):
                        ui.label(render_message("webui.manage_local_retention_rule.label.local_retention_override_5527d4e3")).classes("text-xl font-semibold")
                        ui.label(
                            render_message("webui.manage_local_retention_rule.label.this_root_only_rule_overrides_the_classifi_9e9ad680")
                        ).classes("text-sm text-slate-500")
                        with ui.grid(columns=2).classes("w-full gap-3"):
                            current_years = ui.number(
                                render_message("webui.manage_local_retention_rule.number.current_retention_years_e5bac82b"), value=existing.get("current_period_years"),
                                min=0, format="%.0f",
                            ).props("outlined").classes("w-full")
                            intermediate_years = ui.number(
                                render_message("webui.manage_local_retention_rule.number.intermediate_retention_years_94590fa4"), value=existing.get("intermediate_period_years"),
                                min=0, format="%.0f",
                            ).props("outlined").classes("w-full")
                        disposition = ui.select({
                            "destruction": render_message("webui.manage_local_retention_rule.select.destruction_b012be28"),
                            "transfer_to_external_archive": render_message("webui.manage_local_retention_rule.select.permanent_preservation_external_archive_e21679e7"),
                            "selective_preservation": render_message("webui.manage_local_retention_rule.select.selective_preservation_1054f692"),
                            "retain_as_local_archives": render_message("webui.manage_local_retention_rule.select.retain_as_local_archives_0508fb16"),
                        }, label=render_message("webui.manage_local_retention_rule.select.final_disposition_4becf8e1"), value=existing.get("final_disposition")).props("outlined").classes("w-full")
                        instructions = ui.textarea(
                            render_message("webui.manage_local_retention_rule.textarea.retention_and_disposal_instructions_a3815ea6"), value=existing.get("instructions") or "",
                        ).props("outlined autogrow").classes("w-full")
                        justification = ui.textarea(
                            render_message("webui.manage_local_retention_rule.textarea.justification_143f855a"), value=existing.get("justification") or "",
                        ).props("outlined autogrow").classes("w-full")

                        async def save_rule() -> None:
                            if current_years.value is None or intermediate_years.value is None or not disposition.value:
                                ui.notify(render_message("webui.save_rule.notify.both_periods_and_a_final_disposition_are_r_6dd63826"), color="warning")
                                return
                            if not (justification.value or "").strip():
                                ui.notify(render_message("webui.save_rule.notify.a_justification_is_required_6e06d373"), color="warning")
                                return
                            payload = {
                                "current_period_years": int(current_years.value),
                                "intermediate_period_years": int(intermediate_years.value),
                                "final_disposition": disposition.value,
                                "instructions": (instructions.value or "").strip() or None,
                                "justification": justification.value.strip(),
                            }
                            try:
                                await api.put_aggregation_retention_rule(
                                    current["id"], payload, existing.get("version"),
                                )
                                dialog.close()
                                ui.notify(render_message("webui.save_rule.notify.local_retention_override_saved_0fd4260d"), color="positive")
                                await refresh(section="retention")
                            except ApiError as error:
                                ui.notify(error_message(error), color="negative", close_button=True)

                        async def remove_rule() -> None:
                            reason = (justification.value or "").strip()
                            if not reason:
                                ui.notify(render_message("webui.remove_rule.notify.enter_a_justification_for_removing_the_ove_02112188"), color="warning")
                                return
                            try:
                                await api.delete_aggregation_retention_rule(current["id"], existing["version"], reason)
                                dialog.close()
                                ui.notify(render_message("webui.remove_rule.notify.local_retention_override_removed_3ca4941f"), color="positive")
                                await refresh(section="retention")
                            except ApiError as error:
                                ui.notify(error_message(error), color="negative", close_button=True)

                        with ui.row().classes("w-full justify-end gap-2"):
                            if existing:
                                ui.button(render_message("webui.manage_local_retention_rule.button.remove_override_f21897cb"), icon="delete_outline", color="negative", on_click=remove_rule).props("flat no-caps")
                            ui.button(render_message("webui.manage_local_retention_rule.button.cancel_e8913c84"), on_click=dialog.close).props("flat no-caps")
                            ui.button(render_message("webui.manage_local_retention_rule.button.save_override_8ac0707c"), icon="save", on_click=save_rule).props("unelevated no-caps")
                    dialog.open()

                async def confirm_delete_current() -> None:
                    confirmation = ui.dialog()
                    with confirmation, ui.card().classes("w-[500px] max-w-full"):
                        ui.label(render_message("webui.confirm_delete_current.label.delete_aggregation_6ac41d4a")).classes("text-xl font-semibold")
                        ui.label(
                            render_message("webui.confirm_delete_current.label.aggregation_number_title_will_be_permanent_43423da7", aggregation_number=current['aggregation_number'], title=current['title'])
                        ).classes("text-sm text-slate-700")
                        ui.label(
                            render_message("webui.confirm_delete_current.label.only_an_open_empty_aggregation_can_be_dele_6de7637e")
                        ).classes("text-xs text-slate-500")

                        async def delete_current() -> None:
                            try:
                                await api.delete(
                                    "aggregations", current["id"], current["version"]
                                )
                                confirmation.close()
                                ui.notify(render_message("webui.delete_current.notify.aggregation_deleted_f893101c"), color="positive")
                                await load_recent(ENTITIES["aggregations"])
                                parent = aggregation_context_by_id.get(current.get("parent_aggregation_id"))
                                if parent:
                                    await open_aggregation(parent)
                                else:
                                    await select_entity("aggregations")
                            except ApiError as error:
                                ui.notify(error_message(error), color="negative", close_button=True)

                        with ui.row().classes("w-full justify-end gap-2"):
                            ui.button(render_message("webui.confirm_delete_current.button.cancel_dc05f882"), on_click=confirmation.close).props("flat no-caps")
                            ui.button(
                                render_message("webui.confirm_delete_current.button.delete_aggregation_a57f0f28"), icon="delete_forever", color="negative",
                                on_click=delete_current,
                            ).props("unelevated no-caps")
                    confirmation.open()

                async def load_metadata():
                    nonlocal all_record_total
                    async def count_unfiltered_records():
                        if not record_query or all_record_total is not None:
                            return all_record_total
                        try:
                            unfiltered = await api.search_request("records", {
                                "where": {"field": "aggregation_id", "operator": "eq", "value": identifier},
                                "limit": 1,
                            })
                            return int(unfiltered["total"])
                        except ApiError:
                            return None

                    security_level, owning_org_unit, metadata_path, unfiltered_count = await asyncio.gather(
                        api.get("security-levels", current["security_level_id"]),
                        api.get("org-units", current["owning_org_unit_id"]),
                        metadata_classification_path(),
                        count_unfiltered_records(),
                    )
                    if not active():
                        return
                    if unfiltered_count is not None:
                        all_record_total = unfiltered_count
                    parent_id = current.get("parent_aggregation_id")
                    if parent_id and parent_id not in aggregation_context_by_id:
                        await load_ancestors(parent_id)
                    if not active():
                        return
                    facts, actions = metadata_layout()
                    with facts:
                        if closure:
                            with ui.row().classes(
                                "detail-status-notice w-full items-center gap-3 rounded-xl border border-amber-200 "
                                "bg-amber-50 px-4 py-3"
                            ):
                                ui.icon("lock", color="amber-8").classes("shrink-0")
                                with ui.column().classes("detail-status-notice-copy gap-0 grow min-w-0"):
                                    if closure.get("id") == current["id"]:
                                        ui.label(render_message("webui.open_aggregation.label.closed_directly_77d7dcfc")).classes(
                                            "text-sm font-semibold text-amber-900"
                                        )
                                    else:
                                        ui.label(render_message("webui.open_aggregation.label.closed_by_an_ancestor_aggregation_dab7c6d7")).classes(
                                            "text-sm font-semibold text-amber-900"
                                        )
                                        if closure.get("restricted"):
                                            ui.label(render_message("resource_details.closure_source_restricted"))
                                    if not closure.get("restricted"):
                                        ui.label(
                                            render_message("webui.open_aggregation.label.aggregation_number_title_a5ebf4f9", aggregation_number=closure['aggregation_number'], title=closure['title'])
                                        ).classes("text-xs text-amber-800 break-words")
                                        ui.label(
                                            format_timestamp(closure.get("date_closed"))
                                        ).classes("text-xs text-amber-700")
                                if closure.get("id") == current["id"] and capabilities.get("reopen"):
                                    ui.button(
                                        render_message("webui.open_aggregation.button.reopen_96cb2ac2"), icon="lock_open", on_click=reopen_current,
                                    ).props("flat dense no-caps color=primary").tooltip(
                                        render_message("webui.open_aggregation.tooltip.clear_the_closure_date_all_other_metadata_1cc0adcd")
                                    )
                        if current.get("is_vital") or current.get("has_vital_descendants"):
                            with ui.row().classes("detail-status-notice w-full items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3"):
                                ui.icon("emergency" if current.get("is_vital") else "o_emergency", color="red-8")
                                ui.label(render_message("webui.open_aggregation.label.vital_1334921b") if current.get("is_vital") else render_message("webui.open_aggregation.label.contains_vital_resources_006b2b72")).classes("text-sm font-semibold text-red-900")
                                ui.label(render_message("webui.open_aggregation.label.this_aggregation_cannot_be_deleted_while_v_e9204a66")).classes("text-xs text-red-800")
                        if current.get("parent_aggregation_state") == "redacted":
                            # A null ID with redacted state means the parent
                            # exists; it must never be interpreted as a root.
                            with ui.row().classes(
                                "detail-status-notice w-full items-center gap-2 rounded-xl border border-slate-200 "
                                "bg-slate-50 px-4 py-3"
                            ):
                                ui.icon("visibility_off", color="blue-grey-7")
                                ui.label(render_message("webui.open_aggregation.label.parent_aggregation_restricted_684099c8")).classes(
                                    "text-sm font-semibold text-slate-700"
                                )
                        with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-0"):
                            aggregation_metadata = [
                                (
                                    "status", render_message("entity_metadata.field.status"),
                                    render_message("webui.open_aggregation.badge.closed_30c24826")
                                    if closure else render_message("webui.open_aggregation.badge.open_88407b0f")
                                    if closure_known else render_message("resource_details.unavailable"),
                                ),
                                (
                                    "security_level", render_message("entity_metadata.field.security_level"),
                                    f"{security_level['code']} — {(security_level.get('localized') or {}).get('name') or security_level['name']}",
                                ),
                                (
                                    "owning_org_unit",
                                    render_message("advanced_search.field.owning_org_unit"),
                                    f"{owning_org_unit['code']} — {(owning_org_unit.get('localized') or {}).get('name') or owning_org_unit['name']}",
                                ),
                                ("medium", render_message("entity_metadata.field.medium"), medium_label(current.get("medium"))),
                                (
                                    "vital_status",
                                    render_message("webui.open_aggregation.button.vital_status_69064d77"),
                                    render_message("translation_inspector.value.yes")
                                    if current.get("is_vital") else
                                    render_message("translation_inspector.value.no"),
                                ),
                                ("date_opened", render_message("entity_metadata.field.date_opened"), format_timestamp(current.get("date_opened"))),
                            ]
                            if current.get("medium") != "digital":
                                aggregation_metadata.extend([
                                    (
                                        "assigned_location", render_message("entity_metadata.field.assigned_location"),
                                        current.get("effective_assigned_location") or render_message("webui.render_detail_content.text.unknown_d3c1ce73"),
                                    ),
                                    (
                                        "current_location", render_message("entity_metadata.field.current_location"),
                                        current.get("effective_current_location") or render_message("webui.render_detail_content.text.unknown_d3c1ce73"),
                                    ),
                                ])
                            direct_classification = metadata_path[-1] if metadata_path else None
                            parent_aggregation = aggregation_context_by_id.get(
                                current.get("parent_aggregation_id")
                            )
                            governing_relationship = (
                                (
                                    "parent_aggregation", render_message("entity_metadata.field.parent_aggregation"),
                                    parent_aggregation or render_message("webui.open_aggregation.label.parent_aggregation_restricted_684099c8"),
                                )
                                if not is_root
                                else (
                                    "parent_classification", render_message("entity_metadata.field.parent_classification"),
                                    direct_classification or direct_classification_label(metadata_path),
                                )
                            )
                            aggregation_metadata.extend([
                                ("disposition_status", disposition_text("status"), disposition_status_label(current.get("disposition_status", 1))),
                                ("review", render_message("entity_metadata.field.review"), review_display(current.get("date_of_next_review"))),
                                governing_relationship,
                                ("contains", render_message("webui.render_governance_cards.text.assigned_content_6b3ceaf7"),
                                 (child_total, all_record_total)),
                            ])
                            def render_fields(fields):
                                for field_key, label, value in fields:
                                    with ui.column().classes("detail-field gap-1"):
                                        ui.label(label).classes("detail-field-label")
                                        if field_key == "status":
                                            ui.badge(
                                                str(value), color="amber-8" if closure else "positive",
                                            ).props("outline")
                                        elif field_key == "vital_status":
                                            ui.badge(
                                                str(value),
                                                color="red-8" if current.get("is_vital") else "blue-grey-7",
                                            ).props("outline")
                                        elif field_key == "contains":
                                            children, records = value
                                            for caption, count in (
                                                (render_message("webui.open_aggregation.label.child_aggregations_cd3bce3a"), children),
                                                (render_message("navigation.item.records"), records),
                                            ):
                                                with ui.row().classes("items-baseline gap-1", remove="row"):
                                                    ui.label(caption).classes("text-xs text-slate-600")
                                                    ui.label(str(count) if count is not None else "—").classes("text-xs font-semibold")
                                        elif field_key == "parent_classification" and isinstance(value, dict):
                                            with ui.button(on_click=open_parent_classification).props(
                                                "flat dense no-caps color=primary"
                                            ).classes("detail-linked-entity self-start -m-2 p-2"):
                                                with ui.column().classes("detail-linked-entity-content"):
                                                    ui.label(value.get("title") or "—").classes(
                                                        "detail-linked-entity-title"
                                                    )
                                                    if value.get("code"):
                                                        ui.label(value["code"]).classes(
                                                            "detail-linked-entity-identifier"
                                                        )
                                        elif field_key == "parent_aggregation" and isinstance(value, dict):
                                            with ui.button(on_click=open_parent_aggregation).props(
                                                "flat dense no-caps color=primary"
                                            ).classes("detail-linked-entity self-start -m-2 p-2"):
                                                with ui.column().classes("detail-linked-entity-content"):
                                                    ui.label(value.get("title") or "—").classes(
                                                        "detail-linked-entity-title"
                                                    )
                                                    if value.get("aggregation_number"):
                                                        ui.label(value["aggregation_number"]).classes(
                                                            "detail-linked-entity-identifier"
                                                        )
                                        else:
                                            ui.label(str(value or "—")).classes("detail-field-value")
                                            if field_key in {"assigned_location", "current_location"}:
                                                source_key = "effective_assigned_location_source_aggregation_id" if field_key == "assigned_location" else "effective_current_location_source_aggregation_id"
                                                source_id = current.get(source_key)
                                                source = aggregation_context_by_id.get(source_id)
                                                if source_id == current["id"]:
                                                    ui.label(render_message("webui.open_aggregation.label.set_on_this_aggregation_85415ad9")).classes("text-xs text-slate-500")
                                                elif source:
                                                    ui.label(render_message("webui.open_aggregation.label.inherited_from_aggregation_number_title_fdcc3805", aggregation_number=source['aggregation_number'], title=source['title'])).classes("text-xs text-slate-500")
                            secondary = {"security_level", "date_opened", "assigned_location", "current_location"}
                            render_fields(field for field in aggregation_metadata if field[0] not in secondary)
                            if current.get("description"):
                                with ui.column().classes("detail-field col-span-full gap-1"):
                                    ui.label(
                                        render_message("webui.open_aggregation.label.description_27051c3b")
                                    ).classes("detail-field-label")
                                    ui.label(current["description"]).props("dir=auto").classes(
                                        "detail-field-value whitespace-pre-wrap break-words leading-6"
                                    )
                            with ui.expansion(render_message("resource_details.advanced_metadata")).classes("w-full col-span-full"):
                                with ui.grid(columns=2).classes("w-full gap-x-4"):
                                    render_fields(field for field in aggregation_metadata if field[0] in secondary)

                    def render_advanced_actions():
                        with detail_action_group(render_message("webui.open_aggregation.label.metadata_and_review_8b297ce3")) as metadata_review:
                            metadata_review.set_visibility(any(
                                capabilities.get(action) for action in ("change_location", "change_vital_status", "change_review_date")
                            ))
                            if capabilities.get("change_location"):
                                async def change_location() -> None:
                                    dialog = ui.dialog()
                                    with dialog, ui.card().classes("w-[520px] max-w-full"):
                                        ui.label(render_message("webui.change_location.label.change_location_ee3c1037")).classes("text-xl font-semibold")
                                        ui.label(render_message("webui.change_location.label.leave_a_location_blank_to_clear_its_local_448d79ab")).classes("text-sm text-slate-500")
                                        assigned = ui.input(render_message("webui.change_location.input.assigned_location_7abee0ea"), value=current.get("assigned_location") or "").classes("w-full")
                                        current_location = ui.input(render_message("webui.change_location.input.current_location_53a3ef86"), value=current.get("current_location") or "").classes("w-full")
                                        impact_host = ui.column().classes("w-full gap-1 rounded-lg bg-slate-50 p-3")
                                        impact_host.set_visibility(False)
                                        initial_locations = (
                                            current.get("assigned_location") or "",
                                            current.get("current_location") or "",
                                        )
                                        async def refresh_location_impact() -> None:
                                            impact_host.clear()
                                            proposed_locations = (
                                                (assigned.value or "").strip(),
                                                (current_location.value or "").strip(),
                                            )
                                            if proposed_locations == initial_locations:
                                                impact_host.set_visibility(False)
                                                return
                                            impact_host.set_visibility(True)
                                            try:
                                                preview = await api.preview_aggregation_location(current["id"], {
                                                    "assigned_location": proposed_locations[0] or None,
                                                    "current_location": proposed_locations[1] or None,
                                                })
                                            except ApiError as error:
                                                with impact_host:
                                                    ui.label(
                                                        render_message("webui.refresh_location_impact.label.the_descendant_impact_preview_could_not_be_43c4fd0e")
                                                    ).classes("text-sm text-negative")
                                                return
                                            with impact_host:
                                                count = preview["affected_descendant_count"]
                                                ui.label(render_message("webui.refresh_location_impact.label.descendant_impact_count_resource_value_b7d4133c", count=count, value='s' if count != 1 else '')).classes("text-sm font-semibold")
                                                if not count:
                                                    ui.label(render_message("webui.refresh_location_impact.label.no_descendant_s_effective_location_will_ch_daa579cd")).classes("text-xs text-slate-500")
                                                for descendant in preview["affected_descendants"]:
                                                    kind = "Aggregation" if descendant["entity_type"] == "aggregation" else "Record"
                                                    ui.label(render_message("webui.refresh_location_impact.label.kind_number_title_a042b696", kind=kind, number=descendant['number'], title=descendant['title'])).classes("text-xs text-slate-600")
                                                if preview.get("preview_truncated"):
                                                    ui.label(render_message("webui.refresh_location_impact.label.only_the_first_50_affected_descendants_are_d865e3b2")).classes("text-xs text-slate-500")
                                        assigned.on_value_change(lambda _: refresh_location_impact())
                                        current_location.on_value_change(lambda _: refresh_location_impact())
                                        reason = ui.textarea(render_message("webui.change_location.textarea.reason_f58258f8")).props("outlined autogrow").classes("w-full")
                                        async def submit() -> None:
                                            if not (reason.value or "").strip(): ui.notify(render_message("webui.submit.notify.enter_a_reason_f7e81e79"), color="warning"); return
                                            if ((assigned.value or "").strip(), (current_location.value or "").strip()) == initial_locations:
                                                ui.notify(render_message("webui.submit.notify.no_location_changes_have_been_entered_3a447a79"), color="warning"); return
                                            try:
                                                saved = await api.change_aggregation_location(current["id"], current["version"], {"assigned_location": assigned.value.strip() or None, "current_location": current_location.value.strip() or None, "reason": reason.value.strip()})
                                                dialog.close()
                                                await refresh(saved)
                                            except ApiError as error: ui.notify(error_message(error), color="negative", close_button=True)
                                        ui.button(render_message("webui.change_location.button.save_b8a2bd1a"), on_click=submit).props("unelevated")
                                    dialog.open()
                                ui.button(
                                    render_message("webui.open_aggregation.button.location_5c67a431"), icon="location_on", on_click=change_location,
                                ).props("flat dense no-caps align=start").classes("w-full text-start").tooltip(
                                    render_message("webui.open_aggregation.tooltip.change_this_aggregation_s_assigned_or_curr_2b6fc205")
                                )
                            if capabilities.get("change_vital_status"):
                                async def change_vital_aggregation() -> None:
                                    dialog = ui.dialog()
                                    with dialog, ui.card().classes("w-[520px] max-w-full"):
                                        ui.label(render_message("webui.change_vital_aggregation.label.change_vital_status_e7417d42")).classes("text-xl font-semibold")
                                        value = ui.checkbox(render_message("webui.change_vital_aggregation.checkbox.vital_aggregation_cba8512c"), value=bool(current.get("is_vital")))
                                        reason = ui.textarea(render_message("webui.change_vital_aggregation.textarea.reason_bb22de70")).props("outlined autogrow").classes("w-full")
                                        async def submit() -> None:
                                            if not (reason.value or "").strip(): ui.notify(render_message("webui.submit.notify.enter_a_reason_f7e81e79"), color="warning"); return
                                            try:
                                                saved = await api.change_vital_status("aggregations", current["id"], current["version"], bool(value.value), reason.value.strip())
                                                dialog.close(); await refresh(saved)
                                            except ApiError as error: ui.notify(error_message(error), color="negative", close_button=True)
                                        ui.button(render_message("webui.change_vital_aggregation.button.save_7cfd22dd"), on_click=submit).props("unelevated")
                                    dialog.open()
                                ui.button(
                                    render_message("webui.open_aggregation.button.vital_status_69064d77"), icon="emergency", on_click=change_vital_aggregation,
                                ).props("flat dense no-caps align=start").classes("w-full text-start").tooltip(
                                    render_message("webui.open_aggregation.tooltip.change_whether_this_aggregation_is_protect_1b3beacd")
                                )
                            if capabilities.get("change_review_date"):
                                async def change_aggregation_review_date() -> None:
                                    dialog = ui.dialog()
                                    with dialog, ui.card().classes("w-[520px] max-w-full"):
                                        ui.label(render_message("webui.change_aggregation_review_date.label.schedule_next_review_5b8f3054")).classes("text-xl font-semibold")
                                        ui.label(render_message("webui.change_aggregation_review_date.label.set_a_future_date_or_clear_it_when_no_revi_df572311")).classes("text-sm text-slate-500")
                                        review_date = ui.input(render_message("webui.change_aggregation_review_date.input.date_of_next_review_a2774fe0"), value=review_datetime_input_value(current.get("date_of_next_review"))).props(f"outlined clearable type=datetime-local min={review_datetime_input_minimum()}").classes("w-full")
                                        reason = ui.textarea(render_message("webui.change_aggregation_review_date.textarea.reason_62653c9f")).props("outlined autogrow").classes("w-full")
                                        async def submit() -> None:
                                            if not (reason.value or "").strip(): ui.notify(render_message("webui.submit.notify.enter_a_reason_f7e81e79"), color="warning"); return
                                            value = review_datetime_payload(review_date.value)
                                            try:
                                                saved = await api.change_review_date("aggregations", current["id"], current["version"], value, reason.value.strip())
                                                dialog.close(); await refresh(saved)
                                            except (ApiError, ValueError) as error: ui.notify(error_message(error) if isinstance(error, ApiError) else render_message("webui.submit.notify.choose_a_valid_future_date_d0f7285f"), color="negative", close_button=True)
                                        ui.button(render_message("webui.change_aggregation_review_date.button.save_3a2dff2e"), on_click=submit).props("unelevated")
                                    dialog.open()
                                ui.button(render_message("webui.open_aggregation.button.next_review_699d407b"), icon="event", on_click=change_aggregation_review_date).props("flat dense no-caps align=start").classes("w-full text-start").tooltip(render_message("webui.open_aggregation.tooltip.schedule_or_clear_this_aggregation_s_next_4f66006e"))
                        with detail_action_group(render_message("webui.open_aggregation.label.security_access_and_audit_503e702e")):
                            if capabilities.get("change_security_level"):
                                ui.button(
                                    render_message("webui.open_aggregation.button.security_level_5d0b4408"), icon="security",
                                    on_click=lambda: show_security_level_change(
                                        "aggregation", current,
                                        refresh,
                                    ),
                                ).props("flat dense no-caps align=start").classes("w-full text-start").tooltip(
                                    render_message("webui.open_aggregation.tooltip.change_the_aggregation_security_level_00937d90")
                                )
                            ui.button(
                                render_message("webui.open_aggregation.button.why_this_access_bb85ae4d"), icon="fact_check",
                                on_click=lambda: show_access_explanation("aggregation", current["id"]),
                            ).props("flat dense no-caps align=start").classes("w-full text-start").tooltip(
                                render_message("webui.open_aggregation.tooltip.explain_the_authorization_decision_gate_by_231294dc")
                            )
                            if capabilities.get("manage_acl"):
                                ui.button(
                                    render_message("webui.open_aggregation.button.access_2361cbee"), icon="policy",
                                    on_click=lambda: show_acl_editor(
                                        "aggregations", current["id"], on_saved=refresh,
                                    ),
                                ).props("flat dense no-caps align=start").classes("w-full text-start")
                        show_aggregation_move = (
                            closure is None
                            and current.get("parent_aggregation_id") is not None
                            and capabilities.get("move")
                        )
                        show_ownership_correction_action = (
                            closure is None and capabilities.get("correct_ownership")
                        )
                        # Default ACL endpoints also require authorization administration;
                        # ordinary resource ACL management alone is insufficient.
                        show_acl_defaults = bool(
                            capabilities.get("manage_acl")
                            and "authorization.administer" in set(
                                (principal() or {}).get("global_privileges", [])
                            )
                        )
                        show_delete = closure_known and closure is None and capabilities.get("delete")
                        if show_aggregation_move or show_ownership_correction_action or show_acl_defaults or show_delete:
                            with detail_action_group(render_message("resource_details.aggregation_management")):
                                if show_aggregation_move:
                                    ui.button(
                                        render_message("webui.open_aggregation.button.move_aeafbea8"), icon="drive_file_move",
                                        on_click=lambda: show_governed_move(
                                            "aggregations", current, open_aggregation,
                                        ),
                                    ).props("flat dense no-caps align=start").classes("w-full text-start")
                                if show_ownership_correction_action:
                                    ui.button(
                                        render_message("webui.open_aggregation.button.correct_ownership_07b940fe"), icon="published_with_changes",
                                        on_click=lambda: show_ownership_correction(
                                            current, open_aggregation,
                                        ),
                                    ).props("flat dense no-caps color=negative align=start").classes("w-full text-start")
                                if show_acl_defaults:
                                    ui.button(
                                        render_message("webui.open_aggregation.button.child_defaults_8ac3012b"), icon="account_tree",
                                    ).props("flat dense no-caps align=start").classes("w-full text-start").on(
                                        "click", lambda: show_acl_editor(
                                            "aggregations", current["id"], scope="aggregation"
                                        )
                                    )
                                    ui.button(
                                        render_message("webui.open_aggregation.button.record_defaults_3e8c0414"), icon="description",
                                    ).props("flat dense no-caps align=start").classes("w-full text-start").on(
                                        "click", lambda: show_acl_editor(
                                            "aggregations", current["id"], scope="record"
                                        )
                                    )
                                if show_delete:
                                    delete_button = ui.button(
                                        render_message("webui.open_aggregation.button.delete_dad73ebe"), icon="delete_outline", color="negative",
                                        on_click=confirm_delete_current,
                                    ).props("flat dense no-caps align=start").classes("w-full text-start")
                                    if child_total is None or all_record_total is None or child_total or all_record_total:
                                        delete_button.disable()
                                        delete_button.tooltip(
                                            render_message("webui.open_aggregation.tooltip.remove_or_move_all_child_aggregations_and_19f76f7b")
                                        )

                    with actions:
                        ui.label(render_message("webui.open_aggregation.label.aggregation_actions_ef188212")).classes("text-xs font-semibold text-slate-600 px-2")
                        if closure_known and closure is None and capabilities.get("modify_metadata"):
                            ui.button(
                                render_message("webui.open_aggregation.button.edit_metadata_3ee4d255"), icon="edit",
                                on_click=lambda: open_editor(current, on_saved=refresh, resource_key="aggregations"),
                            ).props("flat dense no-caps align=start").classes("w-full")
                        ui.button(
                            render_message("webui.open_aggregation.button.event_history_77f15b1e"), icon="history",
                            on_click=lambda: show_entity_history("aggregations", current),
                        ).props("flat dense no-caps align=start").classes("w-full")
                        if closure_known and closure is None and capabilities.get("close"):
                            ui.button(
                                render_message("webui.open_aggregation.button.close_5dfd4eee"), icon="lock",
                                on_click=close_current,
                            ).props("flat dense no-caps align=start").classes("w-full").tooltip(
                                render_message("webui.open_aggregation.tooltip.close_this_aggregation_using_the_current_d_a8421be4")
                            )
                        with ui.expansion(render_message("webui.open_aggregation.expansion.advanced_2d1fcc81"),
                                          value=False).props("dense").classes("resource-advanced-actions w-full"):
                            with ui.column().classes("w-full gap-3 pb-2"):
                                render_advanced_actions()


                async def load_classification_path(classification_id):
                    if classification_id not in classification_paths:
                        classification_paths[classification_id] = await api.classification_path(classification_id)
                    return classification_paths[classification_id]

                async def metadata_classification_path():
                    classification_id = current.get("classification_id")
                    if is_root and classification_id:
                        return await load_classification_path(classification_id)
                    return []

                async def fetch_rule():
                    nonlocal classification_path
                    classification_path = []
                    try:
                        rule = await api.effective_retention_rule(identifier)
                    except ApiError as error:
                        if error.status_code != 404:
                            raise
                        return None
                    if rule.get("classification_id"):
                        try:
                            classification_path = await load_classification_path(rule["classification_id"])
                        except ApiError as error:
                            if error.status_code not in {403, 404}:
                                raise
                    return rule

                async def load_ancestors(parent_id):
                    seen = {identifier}
                    while parent_id and parent_id not in seen and active():
                        seen.add(parent_id)
                        try:
                            parent = await api.get("aggregations", parent_id)
                        except ApiError as error:
                            if error.status_code not in {403, 404}:
                                raise
                            return
                        aggregation_context_by_id[parent_id] = parent
                        parent_id = parent.get("parent_aggregation_id")

                async def load_retention():
                    nonlocal local_retention_rule
                    effective_rule = await fetch_rule()
                    if not active():
                        return
                    if effective_rule:
                        async def get_override():
                            try:
                                return await api.aggregation_retention_rule(identifier)
                            except ApiError as error:
                                if error.status_code != 404:
                                    raise
                                return None

                        governing_root_id = effective_rule["governing_root_aggregation_id"]
                        if governing_root_id not in aggregation_context_by_id:
                            await load_ancestors(current.get("parent_aggregation_id"))
                        can_override = (is_root and closure_known and closure is None
                                        and "classifications.administer" in (principal() or {}).get("global_privileges", ()))
                        if can_override:
                            local_retention_rule = await get_override()
                        if not active():
                            return
                        with ui.card().classes(
                            "aggregation-retention-compact w-full min-w-0 shadow-none p-0 gap-3"
                        ):
                            with ui.row().classes("detail-action-row w-full items-center gap-2 p-3 bg-blue-50 rounded-lg", remove="row"):
                                ui.icon("schedule", color="primary", size="20px").classes("shrink-0")
                                with ui.column().classes("gap-0 grow min-w-0"):
                                    if effective_rule["rule_source"] == "aggregation":
                                        source_text = render_message("webui.open_aggregation.text.specified_locally_for_the_governing_root_a_e8018e53")
                                    elif effective_rule.get("inheritance_depth", 0) == 0:
                                        source_text = render_message("webui.open_aggregation.text.specified_by_its_classification_11387963")
                                    else:
                                        source_text = render_message("webui.open_aggregation.text.inherited_from_an_ancestor_classification_297425fa")
                                    if not is_root:
                                        governing_root_id = effective_rule["governing_root_aggregation_id"]
                                        governing_root = aggregation_context_by_id.get(governing_root_id)
                                        root_reference = (
                                            f"{governing_root['aggregation_number']} — {governing_root['title']}"
                                            if governing_root else render_message("webui.open_aggregation.label.parent_aggregation_restricted_684099c8")
                                        )
                                        source_text = render_message(
                                            "webui.open_aggregation.text.governed_by_root_aggregation",
                                            source=render_message_plain(
                                                "webui.open_aggregation.text.specified_locally_for_the_governing_root_a_e8018e53"
                                                if effective_rule["rule_source"] == "aggregation"
                                                else "webui.open_aggregation.text.specified_by_its_classification_11387963"
                                                if effective_rule.get("inheritance_depth", 0) == 0
                                                else "webui.open_aggregation.text.inherited_from_an_ancestor_classification_297425fa"
                                            ),
                                            root_reference=root_reference,
                                        )
                                    ui.label(source_text).classes("text-sm font-medium text-slate-800 break-words w-full")
                            render_retention_stages(effective_rule, localized_disposition_value, compact=True)
                            render_disposition_date(
                                effective_rule,
                                aggregation_context_by_id.get(effective_rule["governing_root_aggregation_id"]),
                                *current_locale_context(),
                            )
                            with ui.expansion(render_message("resource_details.rule_details")).classes("w-full border-t border-slate-200"):
                                with ui.column().classes("resource-retention-details w-full min-w-0 gap-3 px-3 pb-3"):
                                    if classification_path:
                                        with ui.column().classes("w-full gap-1 min-w-0"):
                                            ui.label(render_message("entity_metadata.field.classification")).classes("text-xs font-semibold text-slate-600")
                                            with ui.column().classes("w-full gap-1 ps-2 border-s border-slate-200"):
                                                for item in classification_path:
                                                    with ui.row().classes("w-full items-baseline no-wrap gap-2", remove="row"):
                                                        ui.label(item['code']).classes("text-xs text-slate-600 break-all max-w-[40%]").props("dir=ltr")
                                                        ui.label(item['title']).classes("text-sm text-slate-800 min-w-0 break-words").props("dir=auto")
                                    instructions = effective_rule.get("instructions") or ""
                                    with ui.column().classes("retention-rule-instructions w-full gap-1 min-w-0"):
                                        ui.label(render_message("entity_metadata.field.retention_disposal_instructions")).classes("text-xs font-semibold text-slate-600")
                                        ui.label(instructions if instructions.strip() else "—").classes(
                                            "text-sm text-slate-800 w-full whitespace-pre-wrap break-words",
                                        ).props("dir=auto")
                            with ui.row().classes("detail-action-row w-full items-center gap-2", remove="row"):
                                if is_root and current.get("disposition_status",1)==1 and (principal() or {}).get("can_manage_disposition"):
                                    async def accelerated(result):
                                        await refresh(section="retention")
                                    ui.button(disposition_text("accelerate"),icon="event_available",on_click=lambda:accelerate_dialog(
                                        api=api,root=current,active=lambda:get_resource()=="aggregation-details" and (aggregation_state.get("aggregation_detail") or {}).get("id")==current["id"],
                                        on_error=error_message,after=accelerated)).props("outline dense no-caps")
                                if can_override:
                                    ui.button(
                                        render_message("webui.open_aggregation.button.edit_override_c8b224ea") if local_retention_rule else render_message("webui.open_aggregation.button.set_override_76c53fa2"),
                                        icon="tune", on_click=manage_local_retention_rule,
                                    ).props("flat dense no-caps color=primary")
                    else:
                        with ui.card().classes(
                            "detail-surface aggregation-retention-compact shadow-none p-4 gap-3"
                        ):
                            with ui.row().classes("items-center gap-3"):
                                ui.avatar(icon="schedule", color="blue-1", text_color="primary", size="44px")
                                with ui.column().classes("gap-0"):
                                    ui.label(render_message("webui.open_aggregation.label.effective_retention_rule_4dce9765")).classes("text-lg font-semibold")
                                    ui.label(render_message("webui.open_aggregation.label.no_effective_retention_rule_is_available_67150eb4")).classes("text-sm text-slate-500")

                async def load_holds():
                    holds = await get_holds()
                    if not active():
                        return
                    if holds:
                        render_effective_holds(holds, "aggregation", identifier,
                                               lambda: refresh(section="holds"), close_details)
                    else:
                        ui.label(render_message("resource_details.no_active_holds"))
                    with ui.row().classes("w-full gap-2 flex-wrap"):
                        if capabilities.get("add_to_hold"):
                            ui.button(
                                render_message("webui.open_aggregation.button.add_to_hold_8e80a4dc"), icon="add_link",
                                on_click=lambda: add_resource_to_hold_dialog(
                                    "aggregation", identifier, lambda: refresh(section="holds"),
                                ),
                            ).props("flat dense no-caps")
                        if capabilities.get("remove_all_direct_hold_assignments"):
                            ui.button(
                                render_message("webui.open_aggregation.button.remove_direct_holds_d5ecb7ae"),
                                icon="link_off", color="negative", on_click=remove_aggregation_from_all_holds,
                            ).props("flat dense no-caps")

                async def follow_relationship(kind, target):
                    close_details()
                    await open_related_resource(kind, target)

                async def load_relationships():
                    await relationship_panel(
                        api=api, kind="aggregation", identity=identifier,
                        source_label=f"{current['aggregation_number']} · {current['title']}",
                        can_link="relationships.link" in (principal() or {}).get("global_privileges", []),
                        active=active, open_target=follow_relationship,
                        bind_remote=bind_remote_relationship_select, on_error=error_message,
                        browse_resource=browse_advanced_aggregation,
                    )

                show_details, close_details, set_details_trigger = open_details_dialog(
                    current, current["aggregation_number"],
                    {"metadata": load_metadata, "retention": load_retention,
                     "relationships": load_relationships, "holds": load_holds}, active,
                )

                def render_actions():
                    favourite_button("aggregations", identifier)
                    ui.button(
                        render_message("webui.open_aggregation.button.back_4d496e53"),
                        icon=None if current_direction["value"] == "rtl" else "arrow_back",
                        on_click=leave_aggregation_page,
                    ).props("flat dense no-caps" + (" icon-right=arrow_forward" if current_direction["value"] == "rtl" else ""))

                header = ui.column().classes("w-full gap-0")
                child_page_state = aggregation_state.setdefault("aggregation_children_page", {})
                page_state = aggregation_state.setdefault("aggregation_contents", {}).setdefault(identifier, {})
                if refresh_contents:
                    page_state.pop("search_id", None)
                record_query = page_state.get("filter", "")
                expanded = set(page_state.get("expanded_records", ()))
                anchor = page_state.pop("anchor", None)
                records_heading = f"aggregation-records-{identifier}"
                with ui.column().classes("w-full px-4 pb-4 gap-3"):
                    with ui.column().classes("resource-contents-section w-full gap-0 rounded-lg border border-slate-200"):
                        with ui.row().classes("w-full items-center justify-between gap-2 px-3 py-1 bg-blue-50 rounded-t-lg", remove="row").style("flex-wrap: wrap"):
                            with ui.row().classes("items-center gap-2", remove="row"):
                                ui.label(render_message("webui.open_aggregation.label.child_aggregations_cd3bce3a")).classes("text-sm font-semibold")
                                child_count = ui.badge(color="blue-2", text_color="blue-10").props("rounded")
                                child_count.set_visibility(False)
                            add_child_control = ui.button(render_message("webui.open_aggregation.text.add_child_aggregation_13879ca9"),
                                                          icon="add", on_click=add_child).props("flat dense no-caps").classes("max-w-full text-start")
                            add_child_control.set_visibility(False)
                        child_host = ui.column().classes("w-full px-3 py-2 gap-2")
                    with ui.column().classes("resource-contents-section w-full gap-0 rounded-lg border border-slate-200"):
                        with ui.row().classes("w-full items-center justify-between gap-2 px-3 py-1 bg-blue-50 rounded-t-lg", remove="row").style("flex-wrap: wrap"):
                            with ui.row().classes("items-center gap-2", remove="row"):
                                ui.label(render_message("webui.open_aggregation.label.records_in_this_aggregation_db111558")).props(
                                    f"id={records_heading} tabindex=-1",
                                ).classes("text-sm font-semibold")
                                record_count = ui.badge(color="blue-2", text_color="blue-10").props("rounded")
                                record_count.set_visibility(False)
                            add_record_control = ui.button(render_message("webui.index.button.add_record_fc8125c4"),
                                                           icon="note_add", on_click=add_record).props("flat dense no-caps").classes("max-w-full text-start")
                            add_record_control.set_visibility(False)
                        with ui.row().classes("items-center w-full px-3 pt-2 gap-2", remove="row").style("flex-wrap: wrap"):
                            record_filter = ui.input(
                                render_message("webui.open_aggregation.input.filter_records_d5ad0981"),
                                value=page_state.get("filter_draft", record_query),
                            ).props("outlined dense clearable").classes("grow min-w-0").style("flex-basis: 10rem; max-width: 16rem")
                            ui.button(render_message("webui.open_saved_search_dialog.button.apply_filters_63a71659"),
                                      on_click=lambda: load_records(1, submit=True)).props("flat dense no-caps")
                        records_host = ui.column().classes("w-full px-3 py-2 gap-2")

                configuration = get_configuration()
                child_limit = configuration["CHILD_AGGREGATION_PAGE_SIZE"]
                record_limit = configuration["CONTAINED_RECORD_PAGE_SIZE"]
                if page_state.get("child_limit", child_limit) != child_limit:
                    child_page_state.pop(identifier, None)
                if page_state.get("record_limit", record_limit) != record_limit:
                    page_state.pop("page", None)
                page_state.update(child_limit=child_limit, record_limit=record_limit)
                request_serial = {"children": 0, "records": 0}

                async def open_record(record):
                    page_state.update(filter_draft=record_filter.value or "",
                                      expanded_records=sorted(expanded),
                                      anchor=f"compact-result-records-{int(record['id'])}")
                    await show_record_details(record)

                def set_expanded(record_id, value):
                    (expanded.add if value else expanded.discard)(record_id)
                    page_state["expanded_records"] = sorted(expanded)

                def pager(total, page, limit, on_change):
                    if total > limit:
                        ui.pagination(1, (total + limit - 1) // limit, value=page,
                                      on_change=lambda event: on_change(int(event.value))).props(
                            "direction-links boundary-links color=primary",
                        )

                def show_failure(retry):
                    ui.label(render_message("resource_details.list_unavailable"))
                    ui.button(render_message("resource_details.retry"), on_click=retry).props("flat no-caps")

                async def load_children(page):
                    nonlocal child_total
                    request_serial["children"] += 1
                    serial = request_serial["children"]
                    with child_host:
                        spinner = ui.spinner()
                    try:
                        result = await api.relationship_page(
                            "aggregations", ("aggregation_number", "title"), limit=child_limit,
                            offset=(page - 1) * child_limit, filters={"parent_aggregation_id": identifier},
                        )
                    except ApiError:
                        if active() and serial == request_serial["children"]:
                            child_count.set_visibility(False)
                            child_host.clear()
                            with child_host:
                                show_failure(lambda: load_children(page))
                        return
                    finally:
                        if not spinner.is_deleted:
                            spinner.delete()
                    if not active() or serial != request_serial["children"]:
                        return
                    child_total = int(result["total"])
                    last = max(1, (child_total + child_limit - 1) // child_limit)
                    if page > last:
                        await load_children(last)
                        return
                    child_page_state[identifier] = page
                    child_host.clear()
                    child_count.set_text(str(child_total))
                    child_count.set_visibility(True)
                    with child_host:
                        if not result["items"]:
                            ui.label(render_message("webui.open_aggregation.label.no_child_aggregations_7e6e2073")).classes("text-sm text-slate-500")
                        else:
                            with ui.element("div").classes("aggregation-child-preview-grid w-full"):
                                for child in result["items"]:
                                    with ui.element("button").classes("aggregation-child-preview cursor-pointer text-start").on(
                                        "click", lambda _, item=child: open_aggregation(item),
                                    ):
                                        with ui.row().classes("items-start no-wrap gap-2", remove="row"):
                                            ui.icon("folder", color="primary", size="19px")
                                            with ui.column().classes("gap-0 min-w-0"):
                                                ui.label(child["title"]).classes("text-sm font-semibold line-clamp-2").props("dir=auto")
                                                ui.label(child["aggregation_number"]).classes("text-xs text-slate-500").props("dir=ltr")
                                                render_creator_name(child)
                                                if child.get("date_closed"):
                                                    ui.label(render_message("webui.open_aggregation.badge.closed_30c24826")).classes("text-xs text-slate-600")
                                                elif child.get("is_vital"):
                                                    ui.label(render_message("webui.open_aggregation.label.vital_1334921b")).classes("text-xs text-slate-600")
                                                else:
                                                    ui.label(render_message("webui.open_aggregation.badge.open_88407b0f")).classes("text-xs text-slate-600")
                        pager(child_total, page, child_limit, load_children)

                async def load_records(page, *, submit=False):
                    nonlocal record_query, all_record_total, anchor
                    request_serial["records"] += 1
                    serial = request_serial["records"]
                    if submit:
                        record_query = str(record_filter.value or "").strip()
                        page_state.update(filter=record_query, filter_draft=record_filter.value or "",
                                          search_id=None, page=1)
                    query = record_query
                    conditions = [{"field": "aggregation_id", "operator": "eq", "value": identifier}]
                    payload = {"where": {"and": conditions}, "limit": record_limit,
                               "offset": (page - 1) * record_limit,
                               "include": ["record_capabilities"],
                               "sort": [{"field": "record_number", "direction": "asc"}]}
                    if query:
                        conditions.append({"or": [
                            {"field": field, "operator": "contains_ci", "value": query}
                            for field in ("record_number", "title")
                        ]})
                    with records_host:
                        spinner = ui.spinner()
                    try:
                        if query:
                            await client.connected()
                            if not active() or serial != request_serial["records"]:
                                return
                            payload["tab_id"] = client.tab_id
                            if page_state.get("search_id"):
                                payload["search_id"] = page_state["search_id"]
                        result = await api.search_request("records", payload)
                    except ApiError:
                        if active() and serial == request_serial["records"]:
                            record_count.set_visibility(False)
                            records_host.clear()
                            with records_host:
                                show_failure(lambda: load_records(page))
                            if anchor:
                                restore_compact_result_anchor(anchor, fallback_id=records_heading)
                                anchor = None
                        return
                    finally:
                        if not spinner.is_deleted:
                            spinner.delete()
                    if not active() or serial != request_serial["records"]:
                        return
                    record_total = int(result["total"])
                    if not query:
                        all_record_total = record_total
                    page_state["search_id"] = result.get("search_id")
                    last = max(1, (record_total + record_limit - 1) // record_limit)
                    if not query and page > last:
                        await load_records(last)
                        return
                    page = int(result["offset"]) // record_limit + 1
                    page_state["page"] = page
                    records_host.clear()
                    record_count.set_text(str(record_total))
                    record_count.set_visibility(True)
                    with records_host:
                        if result.get("truncated"):
                            ui.label(render_message("resource_details.filtered_cap", limit=result["result_cap"]))
                        if not result["items"]:
                            ui.label(
                                render_message("webui.render_contained_records.label.no_records_match_this_filter_1041b4b7")
                                if query else render_message("webui.open_aggregation.label.this_aggregation_does_not_contain_any_reco_4b0da9c6")
                            ).classes("text-sm text-slate-500")
                        else:
                            with ui.column().classes("compact-result-list w-full gap-0"):
                                for record in result["items"]:
                                    flags = record.get("_capabilities") or {}
                                    count = int(flags.get("component_count", 0))
                                    render_compact_resource_result(
                                        "records", record, on_open=open_record, component_total=count,
                                        contained_record=True,
                                        can_preview=bool(flags.get("has_previewable_component")),
                                        can_expand_components=bool(count),
                                        initially_expanded=int(record["id"]) in expanded,
                                        on_expansion_changed=lambda value, rid=int(record["id"]): set_expanded(rid, value),
                                    )
                        pager(record_total, page, record_limit, load_records)
                    if anchor:
                        restore_compact_result_anchor(anchor, fallback_id=records_heading)
                        anchor = None

                record_filter.on("keydown.enter", lambda: load_records(1, submit=True))
                record_filter.on_value_change(lambda event: page_state.update(filter_draft=event.value or ""))

                async def load_header():
                    nonlocal capabilities, closure, closure_known, hold_count
                    capability_result, closure_result = await asyncio.gather(
                        detail_read(api.resource_capabilities("aggregations", identifier), notify_error),
                        read_closure(api.effective_aggregation_closure(identifier), notify_error),
                    )
                    if not active():
                        return
                    capabilities = capability_result or {}
                    hold_count = capabilities.get("effective_hold_count")
                    closure_known, closure = closure_result
                    add_child_control.set_visibility(closure_known and closure is None and bool(capabilities.get("add_child")))
                    add_record_control.set_visibility(closure_known and closure is None and bool(capabilities.get("add_record")))
                    with header:
                        render_resource_detail_header(
                            current, kind="aggregation", closure=closure, closure_known=closure_known,
                            hold_count=hold_count, get_holds=get_holds, open_details=show_details,
                            set_default_trigger=set_details_trigger,
                            format_timestamp=format_timestamp, render_actions=render_actions,
                        )

                await asyncio.gather(load_header(), load_children(child_page_state.get(identifier, 1)),
                                     load_records(page_state.get("page", 1)))
                if details_tab and active():
                    await show_details(details_tab)
        except ApiError as error:
            notify_error(error)

    return open_aggregation
