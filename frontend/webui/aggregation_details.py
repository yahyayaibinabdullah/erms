"""Existing aggregation behavior with explicit view dependencies."""
from __future__ import annotations
from typing import Any, Callable
from .aggregation_presentation import AGGREGATION_SUMMARY_LAYOUT_CLASSES
from .api_client import ApiError
from .entities import ENTITIES
from frontend.webui.disposition.screens import accelerate_dialog
import asyncio
from .component_presentation import component_is_previewable
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

def build_aggregation_details(
    *, add_button, add_record_button, add_resource_to_hold_dialog, aggregation_mode_bar, aggregation_state, api, bind_remote_relationship_select, breadcrumb_back, browse_advanced_aggregation, current_direction, enter_details, error_message, favourite_button, format_timestamp, get_record_detail_id, get_relationship_page_token, get_resource, guidance, hold_reason_dialog, load_recent, localized_disposition_value, medium_label, open_editor, open_related_resource, principal, register_navigation, render_compact_resource_result, restore_compact_result_anchor, review_datetime_input_minimum, review_datetime_input_value, review_datetime_payload, review_display, search_bar, select_classification_workspace, select_entity, set_relationship_page_token, show_access_explanation, show_acl_editor, show_authenticated_view, show_effective_holds_dialog, show_entity_history, show_governed_move, show_ownership_correction, show_record_details, show_reopen_aggregation, show_security_level_change, subtitle, table_container, title,
):
    async def open_aggregation(aggregation: dict[str, Any]) -> None:
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
        try:
            current = await api.get("aggregations", aggregation["id"])
            security_level, owning_org_unit, capabilities, effective_holds, closure = await asyncio.gather(
                api.get("security-levels", current["security_level_id"]),
                api.get("org-units", current["owning_org_unit_id"]),
                api.resource_capabilities("aggregations", current["id"]),
                api.effective_holds("aggregation", current["id"]),
                api.effective_aggregation_closure(current["id"]),
            )
            ancestors = []
            seen = {current["id"]}
            parent_id = current.get("parent_aggregation_id")
            while parent_id and parent_id not in seen:
                parent = await api.get("aggregations", int(parent_id))
                ancestors.append(parent)
                seen.add(parent_id)
                parent_id = parent.get("parent_aggregation_id")
            ancestors.reverse()
            aggregation_context_by_id = {
                int(item["id"]): item for item in [*ancestors, current]
            }
            child_page_state = aggregation_state.setdefault("aggregation_children_page", {})
            child_page_number = max(1, int(child_page_state.get(current["id"], 1)))
            child_page = await api.relationship_page(
                "aggregations", ("aggregation_number", "title"), limit=25,
                offset=(child_page_number - 1) * 25,
                filters={"parent_aggregation_id": current["id"]},
            )
            children = child_page["items"]
            child_total = int(child_page["total"])
            child_return = aggregation_state.get("aggregation_child_return") or {}
            if int(child_return.get("aggregation_id") or 0) != int(current["id"]):
                child_return = {}
            record_page_number = max(1, int(child_return.get("page") or 1))
            record_query = str(child_return.get("filter") or "").strip()
            record_conditions: list[dict[str, Any]] = [{
                "field": "aggregation_id", "operator": "eq", "value": current["id"],
            }]
            if record_query:
                record_conditions.append({"or": [
                    {"field": field, "operator": "contains_ci", "value": record_query}
                    for field in ("record_number", "title")
                ]})
            record_page_result = await api.search_request("records", {
                "where": {"and": record_conditions},
                "sort": [{"field": "record_number", "direction": "asc"}],
                "limit": 10, "offset": (record_page_number - 1) * 10,
            })
            records = record_page_result["items"]
            record_total = int(record_page_result["total"])
            async def load_record_result_context(
                record: dict[str, Any],
            ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
                if record.get("medium") == "physical":
                    try:
                        return await api.resource_capabilities("records", record["id"]), []
                    except ApiError:
                        return {}, []
                try:
                    record_capabilities, components = await asyncio.gather(
                        api.resource_capabilities("records", record["id"]),
                        api.component_page(record["id"], limit=25),
                    )
                except ApiError:
                    return {}, []
                return record_capabilities, components["items"]

            record_contexts = await asyncio.gather(*[
                load_record_result_context(record) for record in records
            ])
            for record, (record_capabilities, components) in zip(records, record_contexts):
                record["_components"] = components if record_capabilities.get("list_components") else []
                record["_can_expand_components"] = bool(
                    record_capabilities.get("list_components") and record["_components"]
                )
                record["_can_preview"] = bool(
                    record_capabilities.get("view_component")
                    and any(component_is_previewable(item) for item in record["_components"])
                )
                record["on_effective_hold"] = bool(
                    record.get("on_effective_hold")
                    or record_capabilities.get("is_on_effective_hold")
                )
            effective_rule = None
            local_retention_rule = None
            classification_path = []
            try:
                effective_rule = await api.effective_retention_rule(current["id"])
                if current.get("parent_aggregation_id") is None:
                    local_retention_rule = await api.aggregation_retention_rule(current["id"])
                if effective_rule.get("classification_id"):
                    classification_path = await api.classification_path(
                        effective_rule["classification_id"]
                    )
            except ApiError as error:
                if error.status_code != 404:
                    raise
            for record in records:
                record["_effectively_closed"] = closure is not None
            aggregation_state["aggregation_detail"] = current
            if closure is None and capabilities.get("add_child"):
                add_button.text = render_message("webui.open_aggregation.text.add_child_aggregation_13879ca9")
                add_button.update()
                add_button.set_visibility(True)
            else:
                add_button.set_visibility(False)
            if closure is None and capabilities.get("add_record"):
                add_record_button.set_visibility(True)
            else:
                add_record_button.set_visibility(False)
            search_bar.set_visibility(False)
            aggregation_mode_bar.set_visibility(False)
            guidance.text = ""
            title.text = current["title"]
            subtitle.text = current["aggregation_number"]
            table_container.clear()
            with table_container:
                async def leave_aggregation_page() -> None:
                    await breadcrumb_back(lambda: select_entity("aggregations"))

                async def open_parent_aggregation() -> None:
                    parent = aggregation_context_by_id.get(current.get("parent_aggregation_id"))
                    if parent:
                        await open_aggregation(parent)

                async def open_parent_classification() -> None:
                    if not classification_path:
                        return
                    classification = classification_path[-1]
                    await select_classification_workspace(
                        initial_scheme_id=classification["classification_scheme_id"],
                        initial_classification_id=classification["id"],
                    )

                async def remove_aggregation_from_all_holds() -> None:
                    async def remove(reason: str) -> None:
                        await api.remove_all_direct_holds("aggregation", current["id"], reason)
                        ui.notify(render_message("webui.remove.notify.aggregation_removed_from_all_directly_assi_dfa06ec9"), color="positive")
                        await open_aggregation(current)

                    await hold_reason_dialog(
                        render_message("webui.hold_reason_dialog.remove_all_confirmation"),
                        render_message("webui.open_aggregation.button.remove_direct_holds_d5ecb7ae"),
                        remove,
                    )

                async def reopen_current() -> None:
                    async def reopened(saved: dict[str, Any]) -> None:
                        await load_recent(ENTITIES["aggregations"])
                        await open_aggregation(saved)

                    await show_reopen_aggregation(current, reopened)

                async def close_current() -> None:
                    try:
                        closed = await api.update(
                            "aggregations", current["id"], current["version"],
                            {"date_closed": datetime.now(timezone.utc).isoformat()},
                        )
                        ui.notify(render_message("webui.close_current.notify.aggregation_closed_cf4843ed"), color="positive")
                        await load_recent(ENTITIES["aggregations"])
                        await open_aggregation(closed)
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
                                await open_aggregation(current)
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
                                await open_aggregation(current)
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

                with ui.row().classes("w-full items-center px-5 pt-4 gap-1 text-sm"):
                    ui.button(render_message("webui.open_aggregation.button.aggregations_8a85acd2"), icon="folder", on_click=lambda: select_entity("aggregations")).props("flat dense no-caps").classes("breadcrumb-link")
                    for ancestor in ancestors:
                        ui.icon("chevron_right").classes("text-slate-400")
                        ui.button(
                            ancestor["title"],
                            on_click=lambda _, item=ancestor: open_aggregation(item),
                        ).props("flat dense no-caps").classes("breadcrumb-link")
                    ui.icon("chevron_right").classes("text-slate-400")
                    ui.label(current["title"]).classes("font-semibold text-slate-800")

                with ui.element("div").classes("aggregation-command-layout w-full p-5"):
                    with ui.column().classes("aggregation-command-controls"):
                        aggregation_hold_host = ui.card().classes(
                            "detail-surface aggregation-hold-controls shadow-none p-4 gap-3"
                        )
                        aggregation_actions_host = ui.card().classes(
                            "detail-surface aggregation-actions-panel shadow-none p-4 gap-3"
                        )
                    with ui.card().classes(
                        AGGREGATION_SUMMARY_LAYOUT_CLASSES
                    ):
                        with ui.row().classes("aggregation-panel-heading w-full items-center"):
                            ui.label(render_message("webui.open_aggregation.label.aggregation_overview_bb8398e3"))
                            ui.space()
                            ui.badge(render_message("webui.open_aggregation.badge.closed_30c24826") if closure else render_message("webui.open_aggregation.badge.open_88407b0f"), color="amber-8" if closure else "positive").props("outline")
                        with ui.grid(columns="auto minmax(0, 1fr) auto").classes(
                            "aggregation-detail-identity-header w-full items-center gap-3"
                        ):
                            ui.avatar(icon="folder", color="primary", text_color="white")
                            with ui.column().classes("gap-0 grow min-w-0"):
                                ui.label(current["aggregation_number"]).classes("text-xs text-primary font-semibold")
                                ui.label(current["title"]).classes("text-lg font-semibold break-words")
                            with ui.grid(columns="repeat(2, max-content)").classes(
                                "aggregation-detail-header-actions items-center gap-2"
                            ):
                                favourite_button("aggregations", current["id"])
                                ui.button(
                                    render_message("webui.open_aggregation.button.back_4d496e53"),
                                    icon=None if current_direction["value"] == "rtl" else "arrow_back",
                                    on_click=leave_aggregation_page,
                                ).props(
                                    "flat dense no-caps"
                                    + (" icon-right=arrow_forward" if current_direction["value"] == "rtl" else "")
                                )
                        if closure:
                            with ui.row().classes(
                                "detail-status-notice w-full items-center gap-3 rounded-xl border border-amber-200 "
                                "bg-amber-50 px-4 py-3"
                            ):
                                ui.icon("lock", color="amber-8").classes("shrink-0")
                                with ui.column().classes("detail-status-notice-copy gap-0 grow min-w-0"):
                                    if closure["id"] == current["id"]:
                                        ui.label(render_message("webui.open_aggregation.label.closed_directly_77d7dcfc")).classes(
                                            "text-sm font-semibold text-amber-900"
                                        )
                                    else:
                                        ui.label(render_message("webui.open_aggregation.label.closed_by_an_ancestor_aggregation_dab7c6d7")).classes(
                                            "text-sm font-semibold text-amber-900"
                                        )
                                        ui.label(
                                            render_message("webui.open_aggregation.label.aggregation_number_title_a5ebf4f9", aggregation_number=closure['aggregation_number'], title=closure['title'])
                                        ).classes("text-xs text-amber-800 truncate")
                                    ui.label(
                                        format_timestamp(closure.get("date_closed"))
                                    ).classes("text-xs text-amber-700")
                                if closure["id"] == current["id"] and capabilities.get("reopen"):
                                    ui.button(
                                        render_message("webui.open_aggregation.button.reopen_96cb2ac2"), icon="lock_open", on_click=reopen_current,
                                    ).props("flat dense no-caps color=primary").tooltip(
                                        render_message("webui.open_aggregation.tooltip.clear_the_closure_date_all_other_metadata_1cc0adcd")
                                    )
                        if current.get("is_vital") or current.get("has_vital_descendants"):
                            with ui.row().classes("detail-status-notice w-full items-center gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3"):
                                ui.icon("emergency", color="red-8")
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
                        if effective_holds:
                            with ui.row().classes(
                                "detail-status-notice w-fit max-w-full items-center gap-2 flex-wrap rounded-xl "
                                "border border-amber-200 bg-amber-50 px-3 py-2"
                            ):
                                ui.icon("gavel", color="warning").classes("shrink-0")
                                hold_count = len(effective_holds)
                                ui.label(
                                    render_message("webui.open_aggregation.label.protected_by_hold_count_effective_value_065566e7", hold_count=hold_count)
                                ).classes("text-sm font-semibold text-amber-900")
                                ui.button(
                                    render_message("webui.open_aggregation.button.view_holds_b4a3f017"), icon="visibility",
                                    on_click=lambda: show_effective_holds_dialog(
                                        effective_holds, "aggregation", current["id"],
                                        lambda: open_aggregation(current),
                                    ),
                                ).props("flat dense no-caps color=warning")
                        with ui.grid(columns=2).classes("w-full gap-x-8 gap-y-0"):
                            aggregation_metadata = [
                                (
                                    "status", render_message("entity_metadata.field.status"),
                                    render_message("webui.open_aggregation.badge.closed_30c24826")
                                    if closure else render_message("webui.open_aggregation.badge.open_88407b0f"),
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
                            direct_classification = classification_path[-1] if classification_path else None
                            parent_aggregation = aggregation_context_by_id.get(
                                current.get("parent_aggregation_id")
                            )
                            governing_relationship = (
                                (
                                    "parent_aggregation", render_message("entity_metadata.field.parent_aggregation"),
                                    parent_aggregation or render_message("webui.open_aggregation.label.parent_aggregation_restricted_684099c8"),
                                )
                                if current.get("parent_aggregation_id") is not None
                                else (
                                    "parent_classification", render_message("entity_metadata.field.parent_classification"),
                                    direct_classification or direct_classification_label(classification_path),
                                )
                            )
                            aggregation_metadata.extend([
                                ("disposition_status", disposition_text("status"), disposition_status_label(current.get("disposition_status", 1))),
                                ("review", render_message("entity_metadata.field.review"), review_display(current.get("date_of_next_review"))),
                                governing_relationship,
                                (
                                    "contains", render_message("webui.render_governance_cards.text.assigned_content_6b3ceaf7"),
                                    render_message(
                                        "webui.render_governance_cards.text.get_aggregations_get_2_records_5bb78a16",
                                        get=child_total, get_2=record_total,
                                    ),
                                ),
                            ])
                            for field_key, label, value in aggregation_metadata:
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
                            if current.get("description"):
                                with ui.column().classes("detail-field col-span-full gap-1"):
                                    ui.label(
                                        render_message("webui.open_aggregation.label.description_27051c3b")
                                    ).classes("detail-field-label")
                                    ui.label(current["description"]).props("dir=auto").classes(
                                        "detail-field-value whitespace-pre-wrap break-words leading-6"
                                    )
                        aggregation_actions_host.__enter__()
                        ui.label(render_message("webui.open_aggregation.label.aggregation_actions_ef188212")).classes("aggregation-panel-heading w-full")
                        ui.label(render_message("webui.open_aggregation.label.metadata_and_review_8b297ce3")).classes("aggregation-action-group-label")
                        with ui.row().classes("aggregation-overview-actions w-full"):
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
                                                dialog.close(); await open_aggregation(saved)
                                            except ApiError as error: ui.notify(error_message(error), color="negative", close_button=True)
                                        ui.button(render_message("webui.change_location.button.save_b8a2bd1a"), on_click=submit).props("unelevated")
                                    dialog.open()
                                ui.button(
                                    render_message("webui.open_aggregation.button.location_5c67a431"), icon="location_on", on_click=change_location,
                                ).props("flat dense no-caps").tooltip(
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
                                                dialog.close(); await open_aggregation(saved)
                                            except ApiError as error: ui.notify(error_message(error), color="negative", close_button=True)
                                        ui.button(render_message("webui.change_vital_aggregation.button.save_7cfd22dd"), on_click=submit).props("unelevated")
                                    dialog.open()
                                ui.button(
                                    render_message("webui.open_aggregation.button.vital_status_69064d77"), icon="emergency", on_click=change_vital_aggregation,
                                ).props("flat dense no-caps").tooltip(
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
                                                dialog.close(); await open_aggregation(saved)
                                            except (ApiError, ValueError) as error: ui.notify(error_message(error) if isinstance(error, ApiError) else render_message("webui.submit.notify.choose_a_valid_future_date_d0f7285f"), color="negative", close_button=True)
                                        ui.button(render_message("webui.change_aggregation_review_date.button.save_3a2dff2e"), on_click=submit).props("unelevated")
                                    dialog.open()
                                ui.button(render_message("webui.open_aggregation.button.next_review_699d407b"), icon="event", on_click=change_aggregation_review_date).props("flat dense no-caps").tooltip(render_message("webui.open_aggregation.tooltip.schedule_or_clear_this_aggregation_s_next_4f66006e"))
                            if closure is None and (
                                capabilities.get("close") or capabilities.get("delete")
                            ):
                                ui.label(render_message("webui.open_aggregation.label.lifecycle_118239ec")).classes("aggregation-action-group-label w-full")
                            if closure is None and capabilities.get("close"):
                                ui.button(
                                    render_message("webui.open_aggregation.button.close_5dfd4eee"), icon="lock",
                                    on_click=close_current,
                                ).props("flat dense no-caps").tooltip(
                                    render_message("webui.open_aggregation.tooltip.close_this_aggregation_using_the_current_d_a8421be4")
                                )
                            if closure is None and capabilities.get("delete"):
                                delete_button = ui.button(
                                    render_message("webui.open_aggregation.button.delete_dad73ebe"), icon="delete_outline", color="negative",
                                    on_click=confirm_delete_current,
                                ).props("flat dense no-caps")
                                if children or records:
                                    delete_button.disable()
                                    delete_button.tooltip(
                                        render_message("webui.open_aggregation.tooltip.remove_or_move_all_child_aggregations_and_19f76f7b")
                                    )
                            ui.label(render_message("webui.open_aggregation.label.security_access_and_audit_503e702e")).classes(
                                "aggregation-action-group-label w-full"
                            )
                            if capabilities.get("change_security_level"):
                                ui.button(
                                    render_message("webui.open_aggregation.button.security_level_5d0b4408"), icon="security",
                                    on_click=lambda: show_security_level_change(
                                        "aggregation", current,
                                        lambda saved: open_aggregation(saved),
                                    ),
                                ).props("flat dense no-caps").tooltip(
                                    render_message("webui.open_aggregation.tooltip.change_the_aggregation_security_level_00937d90")
                                )
                            if closure is None and capabilities.get("modify_metadata"):
                                ui.button(
                                    render_message("webui.open_aggregation.button.edit_metadata_3ee4d255"), icon="edit",
                                    on_click=lambda: open_editor(
                                        current, on_saved=open_aggregation,
                                        resource_key="aggregations",
                                    ),
                                ).props("flat dense no-caps")
                            ui.button(
                                render_message("webui.open_aggregation.button.event_history_77f15b1e"), icon="history",
                                on_click=lambda: show_entity_history("aggregations", current),
                            ).props("flat dense no-caps")
                            ui.button(
                                render_message("webui.open_aggregation.button.why_this_access_bb85ae4d"), icon="fact_check",
                                on_click=lambda: show_access_explanation("aggregation", current["id"]),
                            ).props("flat dense no-caps").tooltip(
                                render_message("webui.open_aggregation.tooltip.explain_the_authorization_decision_gate_by_231294dc")
                            )
                            if capabilities.get("manage_acl"):
                                ui.button(
                                    render_message("webui.open_aggregation.button.access_2361cbee"), icon="policy",
                                    on_click=lambda: show_acl_editor(
                                        "aggregations", current["id"], on_saved=lambda: open_aggregation(current),
                                    ),
                                ).props("flat dense no-caps")
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
                        if (
                            show_aggregation_move
                            or show_ownership_correction_action
                            or show_acl_defaults
                        ):
                            with ui.expansion(
                                render_message("webui.open_aggregation.expansion.advanced_2d1fcc81"), caption=render_message("aggregation_details.guidance.specialist_actions"),
                                icon="tune", value=False,
                            ).classes(
                                "w-full border-t border-slate-100"
                            ):
                                with ui.row().classes("w-full justify-start gap-2 pb-2"):
                                    if show_aggregation_move:
                                        ui.button(
                                            render_message("webui.open_aggregation.button.move_aeafbea8"), icon="drive_file_move",
                                            on_click=lambda: show_governed_move(
                                                "aggregations", current, open_aggregation,
                                            ),
                                        ).props("flat dense no-caps")
                                    if show_ownership_correction_action:
                                        ui.button(
                                            render_message("webui.open_aggregation.button.correct_ownership_07b940fe"), icon="published_with_changes",
                                            on_click=lambda: show_ownership_correction(
                                                current, open_aggregation,
                                            ),
                                        ).props("flat dense no-caps color=negative")
                                    if show_acl_defaults:
                                        ui.button(
                                            render_message("webui.open_aggregation.button.child_defaults_8ac3012b"), icon="account_tree",
                                        ).props("flat dense no-caps").on(
                                            "click", lambda: show_acl_editor(
                                                "aggregations", current["id"], scope="aggregation"
                                            )
                                        )
                                        ui.button(
                                            render_message("webui.open_aggregation.button.record_defaults_3e8c0414"), icon="description",
                                        ).props("flat dense no-caps").on(
                                            "click", lambda: show_acl_editor(
                                                "aggregations", current["id"], scope="record"
                                            )
                                        )
                        aggregation_actions_host.__exit__(None, None, None)
                    aggregation_command_side = ui.column().classes("aggregation-command-side")
                    aggregation_command_side.__enter__()
                    if effective_rule:
                        with ui.card().classes(
                            "retention-card aggregation-retention-compact shadow-none p-4 gap-3"
                        ):
                            with ui.row().classes("detail-action-row w-full items-center gap-3"):
                                ui.avatar(icon="schedule", color="blue-1", text_color="primary", size="38px")
                                with ui.column().classes("gap-0 grow"):
                                    ui.label(render_message("webui.open_aggregation.label.effective_retention_rule_4dce9765")).classes("text-base font-semibold text-slate-900")
                                    if effective_rule["rule_source"] == "aggregation":
                                        source_text = render_message("webui.open_aggregation.text.specified_locally_for_the_governing_root_a_e8018e53")
                                    elif effective_rule.get("inheritance_depth", 0) == 0:
                                        source_text = render_message("webui.open_aggregation.text.specified_by_its_classification_11387963")
                                    else:
                                        source_text = render_message("webui.open_aggregation.text.inherited_from_an_ancestor_classification_297425fa")
                                    if current.get("parent_aggregation_id") is not None:
                                        governing_root_id = effective_rule["governing_root_aggregation_id"]
                                        governing_root = aggregation_context_by_id.get(governing_root_id)
                                        root_reference = (
                                            f"{governing_root['aggregation_number']} — {governing_root['title']}"
                                            if governing_root else f"#{governing_root_id}"
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
                                    ui.label(source_text).classes("text-xs text-sky-700")
                                ui.badge(render_message("webui.open_aggregation.badge.effective_a28f890c"), color="primary").props("outline")
                                if current.get("parent_aggregation_id") is None and current.get("disposition_status",1)==1 and (principal() or {}).get("can_manage_disposition"):
                                    async def accelerated(result):await open_aggregation(await api.get("aggregations",current["id"]))
                                    ui.button(disposition_text("accelerate"),icon="event_available",on_click=lambda:accelerate_dialog(
                                        api=api,root=current,active=lambda:get_resource()=="aggregation-details" and (aggregation_state.get("aggregation_detail") or {}).get("id")==current["id"],
                                        on_error=error_message,after=accelerated)).props("outline dense no-caps")
                            render_retention_stages(effective_rule, localized_disposition_value)
                            render_disposition_date(
                                effective_rule,
                                aggregation_context_by_id.get(effective_rule["governing_root_aggregation_id"]),
                                *current_locale_context(),
                            )
                            with ui.element("div").classes("aggregation-retention-footer detail-action-row w-full"):
                                if classification_path:
                                    classification_text = " › ".join(
                                        f"{item['code']} — {item['title']}" for item in classification_path
                                    )
                                    ui.label(render_message("webui.open_aggregation.label.classification_classification_text_6200f5a0", classification_text=classification_text)).classes(
                                        "aggregation-retention-chip"
                                    ).tooltip(classification_text)
                                if effective_rule.get("instructions"):
                                    ui.label(render_message("webui.open_aggregation.label.instructions_instructions_a62c4c64", instructions=effective_rule['instructions'])).classes(
                                        "aggregation-retention-chip"
                                    ).tooltip(effective_rule["instructions"])
                                if current.get("parent_aggregation_id") is None and closure is None:
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

                    with aggregation_hold_host:
                        ui.label(render_message("webui.open_aggregation.label.hold_controls_e01cb162")).classes("aggregation-panel-heading w-full")
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            if effective_holds:
                                ui.button(
                                    render_message("webui.open_aggregation.button.view_holds_b4a3f017"), icon="visibility",
                                    on_click=lambda: show_effective_holds_dialog(
                                        effective_holds, "aggregation", current["id"],
                                        lambda: open_aggregation(current),
                                    ),
                                ).props("outline dense no-caps color=primary")
                            if capabilities.get("add_to_hold"):
                                ui.button(
                                    render_message("webui.open_aggregation.button.add_to_hold_8e80a4dc"), icon="add_link",
                                    on_click=lambda: add_resource_to_hold_dialog(
                                        "aggregation", current["id"], lambda: open_aggregation(current),
                                    ),
                                ).props("outline dense no-caps color=primary")
                            if capabilities.get("remove_all_direct_hold_assignments"):
                                ui.button(
                                    render_message("webui.open_aggregation.button.remove_direct_holds_d5ecb7ae"), icon="link_off",
                                    on_click=remove_aggregation_from_all_holds,
                                ).props("outline dense no-caps color=negative")
                            if not effective_holds and not capabilities.get("add_to_hold"):
                                ui.label(render_message("webui.open_aggregation.label.no_hold_actions_are_available_c0a40db4")).classes("text-xs text-slate-500")
                    aggregation_command_side.__exit__(None, None, None)

                await relationship_panel(
                    api=api, kind="aggregation", identity=current["id"],
                    source_label=" · ".join(filter(None, (current.get("aggregation_number"), current.get("title")))),
                    can_link="relationships.link" in (principal() or {}).get("global_privileges", []),
                    active=lambda: principal() is relationship_principal and get_resource() == "aggregation-details" and get_relationship_page_token() is relationship_token,
                    open_target=open_related_resource, bind_remote=bind_remote_relationship_select, on_error=error_message,
                browse_resource=browse_advanced_aggregation,
                )
                with ui.row().classes(
                    "aggregation-child-section-heading w-full items-center px-5 pt-1"
                ):
                    ui.label(render_message("webui.open_aggregation.label.child_aggregations_cd3bce3a")).classes("text-base font-semibold text-slate-800")
                    ui.space()
                    ui.label(render_message("webui.open_aggregation.label.children_count_children_0b322dbd", children_count=child_total)).classes("text-xs text-slate-500")
                if children:
                    with ui.element("div").classes("aggregation-child-preview-grid mx-5 mb-3"):
                        for child in children:
                            child_closure = child.get("date_closed")
                            with ui.element("button").classes(
                                "aggregation-child-preview cursor-pointer text-left"
                            ).on("click", lambda _, item=child: open_aggregation(item)):
                                with ui.row().classes("items-start no-wrap gap-2"):
                                    ui.icon("folder", color="primary", size="19px").classes("mt-0.5")
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(child["title"]).classes("text-xs font-semibold line-clamp-2")
                                        child_status = "Closed" if child_closure else (
                                            "Vital" if child.get("is_vital") else "Open"
                                        )
                                        ui.label(
                                            render_message("webui.open_aggregation.label.aggregation_number_child_status_20b87630", aggregation_number=child['aggregation_number'], child_status=child_status)
                                        ).classes("text-[10px] text-slate-500 truncate")
                    if child_total > 25:
                        child_pagination = ui.pagination(
                            1, max(1, (child_total + 24) // 25), value=child_page_number,
                        ).props("direction-links boundary-links color=primary").classes("self-center mb-3")

                        async def reload_child_aggregations() -> None:
                            child_page_state[current["id"]] = int(child_pagination.value or 1)
                            await open_aggregation(current)

                        child_pagination.on_value_change(lambda _: reload_child_aggregations())
                else:
                    ui.label(render_message("webui.open_aggregation.label.no_child_aggregations_7e6e2073")).classes("px-5 pb-3 text-sm text-slate-400")

                ui.label(render_message("webui.open_aggregation.label.records_in_this_aggregation_db111558")).classes("px-5 pt-2 text-base font-semibold")
                if not records and not record_query:
                    ui.label(render_message("webui.open_aggregation.label.this_aggregation_does_not_contain_any_reco_4b0da9c6")).classes("px-5 pb-6 text-slate-500")
                else:
                    expanded_child_records = set(
                        int(value) for value in child_return.get("expanded_records", [])
                    )
                    with ui.row().classes("w-full items-center px-5 pt-2 gap-3"):
                        contained_record_filter = ui.input(
                            render_message("webui.open_aggregation.input.filter_records_d5ad0981"),
                            placeholder=render_message("webui.open_aggregation.input.number_title_or_date_6fab14e9"),
                            value=str(child_return.get("filter") or ""),
                        ).props("outlined dense clearable debounce=250").classes("w-80 max-w-full")
                        ui.space()
                        ui.label(render_message("webui.open_aggregation.label.record_count_records_ca93489a", record_count=record_total)).classes("text-sm text-slate-500")
                    contained_records_host = ui.column().classes("w-full px-5 pt-2 gap-2")
                    contained_record_page = ui.pagination(
                        1, max(1, (record_total + 9) // 10),
                        value=max(1, int(child_return.get("page") or 1)),
                    ).props("direction-links boundary-links color=primary")

                    async def open_contained_record(record: dict[str, Any]) -> None:
                        aggregation_state["aggregation_child_return"] = {
                            "aggregation_id": int(current["id"]),
                            "page": int(contained_record_page.value or 1),
                            "filter": str(contained_record_filter.value or ""),
                            "anchor": f"compact-result-records-{int(record['id'])}",
                            "expanded_records": sorted(expanded_child_records),
                        }
                        await show_record_details(record)

                    def set_child_record_expansion(identifier: int, expanded: bool) -> None:
                        (expanded_child_records.add if expanded else expanded_child_records.discard)(
                            int(identifier)
                        )

                    def render_contained_records() -> None:
                        matching_records = records
                        contained_record_page.set_visibility(record_total > 10)
                        contained_record_page.update()
                        contained_records_host.clear()
                        with contained_records_host:
                            if not matching_records:
                                ui.label(render_message("webui.render_contained_records.label.no_records_match_this_filter_1041b4b7")).classes(
                                    "w-full py-6 text-center text-sm text-slate-500"
                                )
                                return
                            with ui.column().classes("compact-result-list w-full gap-0"):
                                for record in matching_records:
                                    render_compact_resource_result(
                                        "records", record,
                                        on_open=open_contained_record,
                                        components=record.get("_components", []),
                                        can_preview=bool(record.get("_can_preview")),
                                        can_expand_components=bool(record.get("_can_expand_components")),
                                        initially_expanded=int(record["id"]) in expanded_child_records,
                                        on_expansion_changed=lambda expanded, identifier=int(record["id"]):
                                            set_child_record_expansion(identifier, expanded),
                                    )

                    async def reload_contained_records(*, reset: bool = False) -> None:
                        aggregation_state["aggregation_child_return"] = {
                            "aggregation_id": int(current["id"]),
                            "page": 1 if reset else int(contained_record_page.value or 1),
                            "filter": str(contained_record_filter.value or ""),
                            "expanded_records": sorted(expanded_child_records),
                        }
                        await open_aggregation(current)

                    contained_record_filter.on("keydown.enter", lambda: reload_contained_records(reset=True))
                    contained_record_page.on_value_change(lambda _: reload_contained_records())
                    render_contained_records()
                    restore_compact_result_anchor(child_return.get("anchor"))
                    if child_return:
                        aggregation_state.pop("aggregation_child_return", None)
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)


    return open_aggregation
