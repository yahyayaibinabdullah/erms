"""Existing aggregation behavior with explicit view dependencies."""
from __future__ import annotations
from typing import Any, Callable
from .api_client import ApiError
from .i18n_catalogue import render_message
from .relationship_select_styles import style_relationship_chip_select
from nicegui import ui

def build_aggregation_actions(
    *, api, bind_remote_relationship_select, error_message,
):
    async def show_reopen_aggregation(
        item: dict[str, Any], on_saved,
    ) -> None:
        dialog = ui.dialog()
        with dialog, ui.card().classes("w-[560px] max-w-full gap-4"):
            ui.label(render_message("webui.show_reopen_aggregation.label.reopen_aggregation_efcee1d6")).classes("text-xl font-semibold")
            ui.label(
                render_message("webui.show_reopen_aggregation.label.reopening_makes_this_aggregation_and_any_d_bd06dc73")
            ).classes("text-sm text-slate-600")
            reason = ui.textarea(
                render_message("webui.show_reopen_aggregation.textarea.reason_for_reopening_08c23aed"), placeholder=render_message("webui.show_reopen_aggregation.textarea.explain_why_this_aggregation_must_be_reope_b0247ea9"),
            ).props("outlined autogrow counter maxlength=2000").classes("w-full")

            async def submit() -> None:
                change_reason = str(reason.value or "").strip()
                if not change_reason:
                    ui.notify(render_message("webui.submit.notify.enter_a_reason_for_reopening_63c8fdd5"), color="warning")
                    reason.run_method("focus")
                    return
                try:
                    saved = await api.update(
                        "aggregations", item["id"], item["version"],
                        {"date_closed": None}, change_reason=change_reason,
                    )
                    dialog.close()
                    ui.notify(render_message("webui.submit.notify.aggregation_reopened_d22f4bc3"), color="positive")
                    await on_saved(saved)
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.show_reopen_aggregation.button.cancel_38de8fc5"), on_click=dialog.close).props("flat no-caps")
                ui.button(render_message("webui.show_reopen_aggregation.button.reopen_3a12b38d"), icon="lock_open", on_click=submit).props(
                    "unelevated no-caps color=primary"
                )
        dialog.open()


    async def show_governed_move(
        resource: str, item: dict[str, Any], on_saved,
    ) -> None:
        dialog = ui.dialog()
        preview_host: Any = None
        preview_state: dict[str, Any] = {}
        with dialog, ui.card().classes("w-[680px] max-w-full gap-4"):
            ui.label(render_message("webui.show_governed_move.label.move_rstrip_d9d67912", rstrip=resource.rstrip('s'))).classes("text-xl font-semibold")
            destination = ui.select({}, label=render_message("webui.show_governed_move.select.destination_aggregation_622d5aa3"), with_input=True).props(
                "outlined options-dense use-input input-debounce=0"
            ).classes("w-full")
            style_relationship_chip_select(destination, "aggregation_id")
            ui.label(
                render_message("webui.show_governed_move.label.only_destinations_compatible_with_this_res_70f37c56")
            ).classes("text-xs leading-5 text-slate-500 -mt-2")
            no_destinations = ui.label(
                render_message("webui.show_governed_move.label.no_compatible_destination_aggregation_is_c_7999f980")
            ).classes("text-sm text-amber-800")
            no_destinations.set_visibility(False)
            bind_remote_relationship_select(
                destination, "aggregations", ("aggregation_number", "title"),
                ("aggregation_number", "title"),
                exclude_id=item["id"] if resource == "aggregations" else None,
                item_filter=lambda row: (
                    row.get("medium", "mixed") == item.get("medium", "mixed")
                    if resource == "aggregations"
                    else row.get("medium", "mixed") in {"mixed", item.get("medium", "mixed")}
                ),
                # An empty bounded search must not prevent another query.
                on_options_resolved=lambda options: no_destinations.set_visibility(
                    not options and destination.value is None
                ),
                active=lambda: dialog.value,
            )
            keep_access = ui.checkbox(render_message("webui.show_governed_move.checkbox.keep_current_effective_access_as_a_local_o_896dc413"))
            reason = ui.textarea(render_message("webui.show_governed_move.textarea.reason_bfc77d50"), placeholder=render_message("webui.show_governed_move.textarea.required_5352a893")).props(
                "outlined autogrow"
            ).classes("w-full")
            preview_host = ui.column().classes("w-full gap-2")

            async def refresh_preview() -> None:
                preview_host.clear()
                preview_state.clear()
                if destination.value is None:
                    return
                try:
                    preview = await api.acl_move_preview(
                        resource, item["id"], int(destination.value),
                        keep_current_access_as_override=bool(keep_access.value),
                    )
                except ApiError as error:
                    with preview_host:
                        ui.label(error_message(error)).classes("text-sm text-negative")
                    return
                preview_state.update(preview)
                with preview_host:
                    ui.label(
                        render_message("webui.refresh_preview.label.acl_impact_added_count_grants_added_remove_7a89dbba", added_count=preview['added_count'], removed_count=preview['removed_count'])
                    ).classes("text-sm font-medium")
                    if resource == "aggregations":
                        impact = preview.get("affected_subtree", {})
                        ui.label(
                            render_message("webui.refresh_preview.label.subtree_get_aggregations_get_2_records_e9a4c3b8", get=impact.get('aggregation_count', 0), get_2=impact.get('record_count', 0))
                        ).classes("text-sm text-slate-600")
                    if preview.get("ownership_changes"):
                        ui.label(
                            render_message("webui.refresh_preview.label.this_move_changes_organizational_ownership_d0b5efd9")
                        ).classes("text-sm font-medium text-amber-900 bg-amber-50 rounded p-2")
                        ui.label(render_message("authorization.oversight.ownership_change")).classes("text-sm text-amber-900")

            destination.on_value_change(lambda _: refresh_preview())
            keep_access.on_value_change(lambda _: refresh_preview())

            async def submit() -> None:
                if destination.value is None or not (reason.value or "").strip():
                    ui.notify(render_message("webui.submit.notify.destination_and_reason_are_required_6216e905"), color="warning")
                    return
                if not preview_state:
                    await refresh_preview()
                if not preview_state:
                    return
                try:
                    saved = await api.move_with_acl(resource, item["id"], {
                        "destination_aggregation_id": int(destination.value),
                        "resource_version": item["version"],
                        "keep_current_access_as_override": bool(keep_access.value),
                        "confirm_ownership_change": bool(preview_state.get("ownership_changes")),
                        "reason": reason.value.strip(),
                    })
                    dialog.close()
                    ui.notify(render_message("webui.submit.notify.resource_moved_c17aeea4"), color="positive")
                    await on_saved(saved)
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.show_governed_move.button.cancel_ace0514f"), on_click=dialog.close).props("flat no-caps")
                ui.button(render_message("webui.show_governed_move.button.move_115a42b3"), icon="drive_file_move", on_click=submit).props("unelevated no-caps")
        dialog.open()


    async def show_ownership_correction(root: dict[str, Any], on_saved) -> None:
        try:
            rows = await api.ownership_correction_options()
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return
        rows = [row for row in rows if row["org_unit_id"] != root["owning_org_unit_id"]]
        dialog = ui.dialog()
        preview_host: Any = None
        preview_state: dict[str, Any] = {}
        with dialog, ui.card().classes("w-[680px] max-w-full gap-4"):
            ui.label(render_message("webui.show_ownership_correction.label.correct_ownership_11df57cb")).classes("text-xl font-semibold")
            ui.label(
                render_message("webui.show_ownership_correction.label.use_this_governed_correction_only_when_the_97d4cb0d")
            ).classes("text-sm text-slate-600")
            destination = ui.select(
                {row["role_id"]: row["label"] for row in rows},
                label=render_message("webui.show_ownership_correction.select.correct_owner_and_creator_acl_role_67d37f56"),
            ).props("outlined options-dense").classes("w-full")
            reason = ui.textarea(render_message("webui.show_ownership_correction.textarea.reason_e8df7b2d"), placeholder=render_message("webui.show_ownership_correction.textarea.required_3f1a5512")).props(
                "outlined autogrow"
            ).classes("w-full")
            preview_host = ui.column().classes("w-full gap-2")

            async def refresh_preview() -> None:
                preview_host.clear(); preview_state.clear()
                if destination.value is None:
                    return
                try:
                    preview = await api.ownership_correction_preview(
                        root["id"], int(destination.value)
                    )
                except ApiError as error:
                    with preview_host:
                        ui.label(error_message(error)).classes("text-sm text-negative")
                    return
                preview_state.update(preview)
                with preview_host:
                    ui.label(
                        render_message("webui.refresh_preview.label.affected_holdings_affected_aggregation_cou_8eb75b58", affected_aggregation_count=preview['affected_aggregation_count'], affected_record_count=preview['affected_record_count'])
                    ).classes("text-sm font-medium")
                    ui.label(
                        render_message("webui.refresh_preview.label.creator_role_grants_reassigned_creator_rol_c7ba8ad9", creator_role_grant_count=preview['creator_role_grant_count'])
                    ).classes("text-sm text-slate-600")
                    ui.label(
                        render_message("webui.refresh_preview.label.all_org_unit_members_will_immediately_refe_37d206d8")
                    ).classes("text-sm text-amber-900 bg-amber-50 rounded p-2")

            destination.on_value_change(lambda _: refresh_preview())

            async def submit() -> None:
                if destination.value is None or not (reason.value or "").strip():
                    ui.notify(render_message("webui.submit.notify.correct_owner_and_reason_are_required_d93eb8ea"), color="warning")
                    return
                if not preview_state:
                    await refresh_preview()
                if not preview_state:
                    return
                try:
                    saved = await api.correct_ownership(
                        root["id"], int(destination.value), reason.value.strip()
                    )
                    dialog.close()
                    ui.notify(render_message("webui.submit.notify.organizational_ownership_corrected_60d51623"), color="positive")
                    await on_saved(saved)
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.show_ownership_correction.button.cancel_d23390f6"), on_click=dialog.close).props("flat no-caps")
                ui.button(render_message("webui.show_ownership_correction.button.confirm_correction_3bd277b6"), icon="published_with_changes", on_click=submit).props(
                    "unelevated no-caps color=negative"
                )
        dialog.open()


    return show_reopen_aggregation, show_governed_move, show_ownership_correction
