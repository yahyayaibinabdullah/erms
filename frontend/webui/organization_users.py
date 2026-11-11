"""Existing organization users view with explicit per-client dependencies."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
import asyncio
from datetime import datetime
import json
from .i18n_catalogue import render_message
from datetime import timedelta
from datetime import timezone
from nicegui import ui
from .config import user_details_session_limit


def build_organization_users(
    *, accept_application_configuration, add_button, add_record_button, aggregation_mode_bar, api, breadcrumb_back, confirm_identity_deletion, current_page, direction, enter_organization_users, error_message, format_timestamp, get_principal, guidance, localized_account_type, localized_lifecycle_value, open_editor, register_navigation, render_user_avatar, search_bar, select_entity, select_role_details, select_text_indexer_details, show_api_error, show_authenticated_view, show_entity_history, show_memberships, subtitle, table_container, title,
):
    view_token = None
    async def select_user_details(user_id: int) -> None:
        """Render the extensible single-user management view."""
        nonlocal view_token
        principal = get_principal()
        token = object()
        register_navigation("user-details", f"User #{user_id}", entity_id=user_id)
        show_authenticated_view()
        enter_organization_users()
        view_token = token
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        table_container.clear()
        try:
            person, assignment_page_result, session_configuration = await asyncio.gather(
                api.get("users", user_id), api.user_roles(user_id, limit=50, offset=0),
                api.application_configuration(),
            )
            if get_principal() is not principal or current_page() != "user-details" or view_token is not token:
                return
            # This setting is a maximum; transport/rendering windows remain bounded.
            accept_application_configuration(session_configuration)
            session_page_size = min(user_details_session_limit(session_configuration), 50)
            assignments = list(assignment_page_result.get("items") or [])
            roles = [item.get("counterpart") or {} for item in assignments]
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return
        if (
            person.get("account_type") == "service"
            and "identity.text_indexers.administer" in set(
                (get_principal() or {}).get("global_privileges", [])
            )
        ):
            try:
                await api.text_indexer(user_id)
            except ApiError as error:
                if error.status_code != 404:
                    raise
            else:
                await select_text_indexer_details(user_id)
                return
        person = dict(person)
        person["name"] = (
            (person.get("localized") or {}).get("name") or person["name"]
        )
        roles = [role for role in roles if role.get("id") is not None]
        title.text = person["name"]
        subtitle.text = render_message("webui.select_user_details.text.user_details_and_account_administration_b2c8f493")
        register_navigation(
            "user-details", person["name"], entity_id=user_id,
            accessible_label=" — ".join(filter(None, (person["name"], person.get("email")))),
        )
        role_by_id = {item["id"]: item for item in roles}
        can_administer_text_indexers = "identity.text_indexers.administer" in set(
            (get_principal() or {}).get("global_privileges", [])
        ) and person.get("account_type") != "service"
        service_credentials = (
            await api.service_credentials(user_id)
            if person.get("account_type") == "service" and can_administer_text_indexers
            else []
        )

        async def refresh_user(_: Any = None) -> None:
            await select_user_details(user_id)

        async def change_status(action: str) -> None:
            try:
                if action in {"suspend", "unsuspend"}:
                    await api.set_user_suspended(
                        user_id, person["version"], suspended=action == "suspend",
                    )
                else:
                    await api.set_active(
                        "users", user_id, person["version"], active=action == "activate",
                    )
                ui.notify(render_message("webui.change_status.notify.user_action_d_c6c09142", action=action), color="positive")
                await refresh_user()
            except ApiError as error:
                show_api_error(error)

        async def issue_password() -> None:
            try:
                result = await api.issue_temporary_password(user_id)
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                return
            dialog = ui.dialog().props("persistent")
            with dialog, ui.card().classes("w-[520px] max-w-full"):
                ui.label(render_message("webui.issue_password.label.temporary_password_issued_ac83bd55")).classes("text-xl font-semibold")
                ui.label(result["temporary_password"]).classes(
                    "font-mono text-lg bg-slate-100 rounded p-3 select-all"
                )
                ui.label(render_message("webui.issue_password.label.copy_it_now_it_will_not_be_shown_again_9f3cfc5a")).classes("text-sm text-slate-500")
                ui.button(render_message("webui.issue_password.button.i_have_copied_it_2fc9a18e"), on_click=dialog.close).props("unelevated no-caps").classes("self-end")
            dialog.open()

        def reveal_api_key(result: dict[str, Any]) -> None:
            api_key = result.pop("api_key")
            dialog = ui.dialog().props("persistent")
            with dialog, ui.card().classes("w-[680px] max-w-full"):
                ui.label(render_message("webui.reveal_api_key.label.new_api_key_b23471a4")).classes("text-xl font-semibold")
                with ui.row().classes("w-full items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 p-3"):
                    ui.icon("warning", color="warning")
                    ui.label(render_message("webui.reveal_api_key.label.copy_and_store_this_key_now_it_will_not_be_b8730498")).classes("text-sm font-medium")
                ui.label(api_key).classes("w-full font-mono text-sm bg-slate-100 rounded p-3 break-all select-all")
                with ui.row().classes("w-full justify-between gap-2 flex-wrap"):
                    ui.button(
                        render_message("webui.reveal_api_key.button.copy_99572524"), icon="content_copy",
                        on_click=lambda: ui.run_javascript(
                            f"navigator.clipboard.writeText({json.dumps(api_key)}).then(() => true)", timeout=5,
                        ),
                    ).props("outline no-caps")
                    ui.button(
                        render_message("webui.reveal_api_key.button.download_credential_file_443fee8e"), icon="download",
                        on_click=lambda: ui.run_javascript(
                            "(() => { const b=new Blob([" + json.dumps("TEXT_INDEXER_API_KEY=" + api_key + "\n") + "],{type:'text/plain'});"
                            "const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='wathiq-text-indexer.env';a.click();URL.revokeObjectURL(a.href);return true;})()",
                            timeout=5,
                        ),
                    ).props("flat no-caps color=warning").tooltip(render_message("webui.reveal_api_key.tooltip.downloads_a_sensitive_plaintext_file_c936fa58"))
                    async def close_reveal() -> None:
                        nonlocal api_key
                        api_key = ""
                        dialog.close()
                        await select_user_details(user_id)
                    ui.button(render_message("webui.reveal_api_key.button.i_have_stored_it_safely_e410add0"), on_click=close_reveal).props("unelevated no-caps")
            dialog.open()

        def credential_dialog(existing: dict[str, Any] | None = None) -> None:
            dialog = ui.dialog().props("persistent")
            with dialog, ui.card().classes("w-[540px] max-w-full"):
                ui.label(render_message("webui.credential_dialog.label.rotate_api_key_dc0e85ed") if existing else render_message("webui.credential_dialog.label.generate_api_key_e9cdd1d3")).classes("text-xl font-semibold")
                name = ui.input(render_message("webui.credential_dialog.input.credential_name_b670464d"), value=(existing or {}).get("name", "")).props("outlined").classes("w-full")
                expiry = ui.input(
                    render_message("webui.credential_dialog.input.expiry_iso_8601_222d3b9f"),
                    value=(datetime.now(timezone.utc) + timedelta(days=90)).replace(microsecond=0).isoformat(),
                ).props("outlined").classes("w-full")
                ui.input(render_message("webui.credential_dialog.input.allowed_route_d805736a"), value="Internal text-indexing API only").props("outlined readonly").classes("w-full")
                overlap = None
                if existing:
                    overlap = ui.input(render_message("webui.credential_dialog.input.old_key_overlap_until_optional_maximum_7_d_eec9eb31")).props("outlined clearable").classes("w-full")
                async def submit_credential() -> None:
                    payload = {"name": (name.value or "").strip(), "expires_at": (expiry.value or "").strip()}
                    if existing and overlap and overlap.value:
                        payload["overlap_until"] = overlap.value.strip()
                    try:
                        result = (
                            await api.rotate_service_credential(user_id, existing["id"], payload)
                            if existing else await api.create_service_credential(user_id, payload)
                        )
                    except ApiError as error:
                        show_api_error(error); return
                    dialog.close()
                    reveal_api_key(result)
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.credential_dialog.button.cancel_f4440fc5"), on_click=dialog.close).props("flat no-caps")
                    ui.button(render_message("webui.credential_dialog.button.rotate_key_abe27125") if existing else render_message("webui.credential_dialog.button.generate_api_key_f5d573fe"), icon="key", on_click=submit_credential).props("unelevated no-caps")
            dialog.open()

        def confirm_revoke_credential(credential: dict[str, Any]) -> None:
            dialog = ui.dialog()
            with dialog, ui.card().classes("w-[520px] max-w-full"):
                ui.label(render_message("webui.confirm_revoke_credential.label.revoke_api_key_9a9c0b6c")).classes("text-xl font-semibold")
                ui.label(render_message("webui.confirm_revoke_credential.label.revoke_name_credential_identifier_77c5681a", name=credential['name'], credential_identifier=credential['credential_identifier'])).classes("font-medium")
                ui.label(render_message("webui.confirm_revoke_credential.label.affected_indexer_instances_will_fail_on_th_c333a64b")).classes("text-sm text-slate-600")
                async def revoke() -> None:
                    try:
                        await api.revoke_service_credential(user_id, credential["id"])
                    except ApiError as error:
                        show_api_error(error); return
                    dialog.close(); ui.notify(render_message("webui.revoke.notify.api_key_revoked_0fb47669"), color="positive")
                    await select_user_details(user_id)
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.confirm_revoke_credential.button.cancel_8c31a153"), on_click=dialog.close).props("flat no-caps")
                    ui.button(render_message("webui.confirm_revoke_credential.button.revoke_2c13599b"), icon="block", color="negative", on_click=revoke).props("unelevated no-caps")
            dialog.open()

        with table_container:
            with ui.column().classes("w-full p-5 gap-4"):
                with ui.element("div").classes("identity-command-layout w-full"):
                    with ui.card().classes(
                        "detail-surface identity-command-actions shadow-none p-4 gap-3"
                    ):
                        ui.label(render_message("webui.select_user_details.label.user_actions_e28b2e51")).classes("aggregation-panel-heading w-full")
                        ui.label(render_message("webui.select_user_details.label.account_and_assignments_3ec90491")).classes("record-action-group-label")
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            if person.get("account_type") == "person":
                                ui.button(render_message("webui.select_user_details.button.edit_244de988"), icon="edit", on_click=lambda: open_editor(person, on_saved=refresh_user, resource_key="users")).props("outline dense no-caps")
                                ui.button(render_message("webui.select_user_details.button.role_assignments_adaadc55"), icon="group", on_click=lambda: show_memberships(person, for_user=True)).props("outline dense no-caps")
                                ui.button(render_message("webui.select_user_details.button.temporary_password_f49a662a"), icon="password", on_click=issue_password).props("outline dense no-caps color=orange")
                            elif can_administer_text_indexers:
                                ui.button(
                                    render_message("webui.select_user_details.button.open_text_indexer_administration_7136e2f6"), icon="manage_search",
                                    on_click=lambda: select_text_indexer_details(user_id),
                                ).props("outline dense no-caps")
                        ui.label(render_message("webui.select_user_details.label.status_and_access_047cbffa")).classes("record-action-group-label")
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            if person.get("account_type") == "person":
                                if person["status"] == "inactive":
                                    ui.button(render_message("webui.select_user_details.button.activate_98e0f841"), icon="toggle_on", on_click=lambda: change_status("activate")).props("outline dense no-caps color=positive")
                                else:
                                    ui.button(render_message("webui.select_user_details.button.deactivate_3a9a81d4"), icon="toggle_off", on_click=lambda: change_status("deactivate")).props("outline dense no-caps color=negative")
                                if person["status"] == "suspended":
                                    ui.button(render_message("webui.select_user_details.button.unsuspend_11dc5fcc"), icon="play_circle", on_click=lambda: change_status("unsuspend")).props("outline dense no-caps color=positive")
                                else:
                                    suspend = ui.button(render_message("webui.select_user_details.button.suspend_30cd8b2a"), icon="pause_circle", on_click=lambda: change_status("suspend")).props("outline dense no-caps color=warning")
                                    if person["status"] != "active":
                                        suspend.disable(); suspend.tooltip(render_message("webui.select_user_details.tooltip.activate_the_user_before_suspending_2989ce61"))
                            else:
                                ui.label(render_message("webui.select_user_details.label.managed_through_the_dedicated_text_indexer_0fdd7ff8")).classes("text-sm text-slate-500")
                        ui.label(render_message("webui.select_user_details.label.audit_and_lifecycle_a0bd6725")).classes("record-action-group-label")
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            ui.button(render_message("webui.select_user_details.button.history_637192b2"), icon="history", on_click=lambda: show_entity_history("users", person)).props("outline dense no-caps")
                            if person.get("account_type") == "person":
                                ui.button(
                                    render_message("webui.select_user_details.button.permanently_delete_6dc8484c"), icon="delete_forever", color="negative",
                                    on_click=lambda: confirm_identity_deletion(
                                        "users", person, label="user", on_deleted=lambda: select_entity("users"),
                                    ),
                                ).props("outline dense no-caps")
                    user_metadata_panel = ui.card().classes(
                        "detail-surface identity-command-metadata shadow-none p-5"
                    )
                    user_metadata_panel.__enter__()
                    with ui.grid(columns="auto minmax(0, 1fr) auto").classes("identity-detail-header w-full items-start gap-4"):
                        render_user_avatar(person, size="64px")
                        with ui.column().classes("gap-1 min-w-0 break-words"):
                            ui.label(person["name"]).classes("text-xl font-semibold")
                            ui.label(
                                render_message(
                                    "webui.select_user_details.label.title_account_value_7ffc8b75",
                                    title=localized_account_type(person["account_type"]),
                                    value=person.get("email") or render_message("webui.select_user_details.label.no_email_address_1d665180"),
                                )
                            ).classes("text-sm text-slate-500")
                            if person.get("account_type") == "service":
                                with ui.row().classes("items-center gap-1"):
                                    ui.badge(render_message("webui.select_user_details.badge.service_account_f2f0513b"), color="primary").props("outline")
                                    ui.badge(render_message("webui.select_user_details.badge.non_interactive_bcf1ef6e"), color="blue-grey").props("outline")
                        with ui.row().classes("gap-1"):
                            ui.button(
                                render_message("webui.select_user_details.button.back_fd96364b"), icon=None if direction() == "rtl" else "arrow_back",
                                on_click=lambda: breadcrumb_back(lambda: select_entity("users")),
                            ).props("flat no-caps" + (" icon-right=arrow_forward" if direction() == "rtl" else ""))
                    with ui.grid(columns=3).classes("w-full gap-4 mt-3"):
                        with ui.column().classes("gap-1 border-b border-slate-100 pb-1.5"):
                            ui.label(render_message("webui.select_user_details.label.email_address_db7b1f8d")).classes("detail-field-label")
                            ui.label(person.get("email") or render_message("webui.select_user_details.label.no_email_address_1d665180")).classes("font-medium")
                        with ui.column().classes("gap-1 border-b border-slate-100 pb-1.5"):
                            ui.label(render_message("webui.select_user_details.label.account_type_c01f9019")).classes("detail-field-label")
                            ui.badge(localized_account_type(person["account_type"]), color="blue-grey").props("outline")
                        with ui.column().classes("gap-1 border-b border-slate-100 pb-1.5"):
                            ui.label(render_message("webui.select_user_details.label.status_50b881c8")).classes("detail-field-label")
                            with ui.row().classes("classification-detail-title-status items-center gap-2"):
                                ui.badge(
                                    localized_lifecycle_value(person["status"]),
                                    color={"active": "positive", "suspended": "warning"}.get(
                                        person["status"], "grey-7",
                                    ),
                                )
                                if person.get("date_suspended"):
                                    ui.label(
                                        render_message("webui.select_user_details.label.since_format_timestamp_82564a09", format_timestamp=format_timestamp(person['date_suspended']))
                                    ).classes("text-xs text-amber-700")
                                elif person.get("date_deactivated"):
                                    ui.label(
                                        render_message("webui.select_user_details.label.since_format_timestamp_82564a09", format_timestamp=format_timestamp(person['date_deactivated']))
                                    ).classes("text-xs text-slate-500")
                        with ui.column().classes("gap-1 border-b border-slate-100 pb-1.5"):
                            ui.label(render_message("webui.select_user_details.label.external_id_839b0605")).classes("detail-field-label")
                            ui.label(person.get("external_id") or "—").classes("font-medium")
                        with ui.column().classes("gap-1 border-b border-slate-100 pb-1.5"):
                            ui.label(render_message("webui.select_user_details.label.created_fabff4f0")).classes("detail-field-label")
                            ui.label(format_timestamp(person.get("date_created"))).classes(
                                "font-medium"
                            )
                        with ui.column().classes("gap-1 border-b border-slate-100 pb-1.5"):
                            ui.label(render_message("webui.select_user_details.label.user_id_2afe38aa")).classes("detail-field-label")
                            ui.label(str(person["id"])).classes("font-medium tabular-nums")
                    user_metadata_panel.__exit__(None, None, None)
                if person.get("account_type") == "service" and can_administer_text_indexers:
                    with ui.row().classes("dashboard-overview-heading w-full items-center"):
                        with ui.column().classes("gap-0 grow"):
                            ui.label(render_message("webui.select_user_details.label.api_credentials_ba1a3b5a")).classes("text-lg font-semibold")
                            ui.label(render_message("webui.select_user_details.label.internal_text_indexing_api_only_non_intera_4daa19fa")).classes("text-sm text-slate-500")
                        if "identity.users.administer" in set((get_principal() or {}).get("global_privileges", [])):
                            generate_key = ui.button(render_message("webui.select_user_details.button.generate_api_key_ef560394"), icon="add", on_click=credential_dialog).props("unelevated no-caps")
                            if person.get("status") != "active":
                                generate_key.disable(); generate_key.tooltip(render_message("webui.select_user_details.tooltip.activate_the_service_account_before_genera_a079c01d"))
                    if not service_credentials:
                        with ui.card().classes("governance-empty-state shadow-none"):
                            ui.icon("key_off", size="34px").classes("text-slate-300")
                            ui.label(render_message("webui.select_user_details.label.no_api_credentials_a9b21956")).classes("font-semibold")
                            ui.label(render_message("webui.select_user_details.label.generate_a_key_when_this_text_indexer_depl_a9bfa2d3")).classes("text-sm text-slate-500")
                    for credential in service_credentials:
                        with ui.card().classes("governance-list-card shadow-none"):
                            with ui.row().classes("w-full items-start gap-3 no-wrap"):
                                with ui.element("div").classes("governance-card-icon"):
                                    ui.icon("key", size="20px")
                                with ui.column().classes("gap-0 grow min-w-0"):
                                    ui.label(credential["name"]).classes("font-semibold")
                                    ui.label(render_message("webui.select_user_details.label.id_wti_credential_identifier_internal_text_cd88df6a", credential_identifier=credential['credential_identifier'])).classes("text-xs text-slate-500 break-all")
                                ui.badge(credential["status"].title(), color={"active": "positive", "expiring": "warning", "expired": "grey-7", "revoked": "negative"}.get(credential["status"], "grey-7")).props("outline")
                                if person.get("status") != "active" and credential["status"] in {"active", "expiring"}:
                                    ui.badge(render_message("webui.select_user_details.badge.disabled_with_account_28927de6"), color="negative").props("outline")
                            with ui.grid(columns=3).classes("w-full gap-3"):
                                for label, value in (
                                    ("Created", format_timestamp(credential.get("date_created"))),
                                    ("Expires", format_timestamp(credential.get("expires_at"))),
                                    ("Last used", format_timestamp(credential.get("last_used_at")) if credential.get("last_used_at") else "Never"),
                                    ("Created by", credential.get("created_by_name") or "System"),
                                    ("Last worker", credential.get("last_worker_id") or "—"),
                                ):
                                    with ui.column().classes("gap-0"):
                                        ui.label(label).classes("detail-field-label")
                                        ui.label(value).classes("text-sm")
                            if credential["status"] == "active" and "identity.users.administer" in set((get_principal() or {}).get("global_privileges", [])):
                                with ui.row().classes("detail-action-row w-full justify-start gap-2 border-t border-slate-100 pt-2"):
                                    ui.button(render_message("webui.select_user_details.button.rotate_65fa1eea"), icon="sync", on_click=lambda _, item=credential: credential_dialog(item)).props("outline dense no-caps")
                                    ui.button(render_message("webui.select_user_details.button.revoke_fd5240c0"), icon="block", color="negative", on_click=lambda _, item=credential: confirm_revoke_credential(item)).props("outline dense no-caps")

                ui.label(render_message("webui.select_user_details.label.role_assignments_f60546c5")).classes("text-lg font-semibold")
                if not assignments:
                    ui.label(render_message("webui.select_user_details.label.no_role_assignments_4a7fa329")).classes("text-slate-400")
                else:
                    now = datetime.now(timezone.utc)
                    assignment_rows = []
                    for item in assignments:
                        role = role_by_id.get(item["role_id"], {})
                        valid_from = datetime.fromisoformat(str(item["valid_from"]).replace("Z", "+00:00"))
                        valid_until = datetime.fromisoformat(str(item["valid_until"]).replace("Z", "+00:00")) if item.get("valid_until") else None
                        validity = "future" if valid_from > now else "expired" if valid_until and valid_until <= now else "current"
                        assignment_rows.append({
                            **item, "role": " — ".join(filter(None, (role.get("code"), role.get("name")))) or str(item["role_id"]),
                            "role_status": role.get("effective_status", role.get("status", "unknown")),
                            "validity": validity,
                        })
                    with ui.row().classes("w-full items-end gap-2"):
                        assignment_search = ui.input(render_message("webui.select_user_details.input.filter_role_name_or_code_e534534c")).props("outlined dense clearable").classes("grow")
                        assignment_status = ui.select({"all": render_message("webui.select_user_details.select.all_role_statuses_cfa1f6a9"), "active": render_message("webui.select_user_details.select.active_f7618f84"), "inactive": render_message("webui.select_user_details.select.inactive_1875b5d5")}, value="all", label=render_message("webui.select_user_details.select.role_status_d3fdf1df")).props("outlined dense options-dense").classes("w-44")
                        assignment_validity = ui.select({"all": render_message("webui.select_user_details.select.all_validity_c7af57fc"), "current": render_message("webui.select_user_details.select.current_e6f547bc"), "future": render_message("webui.select_user_details.select.future_b677d9db"), "expired": render_message("webui.select_user_details.select.expired_2de6a536")}, value="all", label=render_message("webui.select_user_details.select.assignment_validity_df0ff7b6")).props("outlined dense options-dense").classes("w-48")
                    assignment_results = ui.element("div").classes(
                        "governance-card-list w-full"
                    )
                    assignment_page_size = 5
                    assignment_state: dict[str, Any] = {
                        "offset": 0, "filtered_rows": assignment_rows,
                    }

                    def confirm_remove_role_assignment(row: dict[str, Any]) -> None:
                        dialog = ui.dialog()

                        async def remove_assignment() -> None:
                            try:
                                await api.delete_assignment(row["id"], row["version"])
                            except ApiError as error:
                                show_api_error(error)
                                return
                            dialog.close()
                            ui.notify(render_message("webui.remove_assignment.notify.role_assignment_removed_5584007c"), color="positive")
                            await select_user_details(user_id)

                        with dialog, ui.card().classes("w-[500px] max-w-full"):
                            ui.label(render_message("webui.confirm_remove_role_assignment.label.remove_role_assignment_e3bcfb9e")).classes(
                                "text-lg font-semibold"
                            )
                            ui.label(
                                render_message("webui.confirm_remove_role_assignment.label.remove_name_from_role_037a277b", name=person['name'], role=row['role'])
                            ).classes("text-sm text-slate-600")
                            with ui.row().classes("w-full justify-end gap-2"):
                                ui.button(render_message("webui.confirm_remove_role_assignment.button.cancel_a267a8b7"), on_click=dialog.close).props(
                                    "flat no-caps"
                                )
                                ui.button(
                                    render_message("webui.confirm_remove_role_assignment.button.remove_assignment_35684f6c"), icon="person_remove",
                                    color="negative", on_click=remove_assignment,
                                ).props("unelevated no-caps")
                        dialog.open()

                    def render_assignment_cards() -> None:
                        rows = assignment_state["filtered_rows"]
                        offset = assignment_state["offset"]
                        page_rows = rows[offset:offset + assignment_page_size]
                        assignment_results.clear()
                        with assignment_results:
                            if not rows:
                                ui.label(render_message("webui.render_assignment_cards.label.no_role_assignments_match_these_filters_649ccfe0")).classes(
                                    "w-full text-center text-slate-400 py-8"
                                )
                            for row in page_rows:
                                card = ui.card().classes(
                                    "governance-list-card user-role-assignment-card shadow-none"
                                ).on(
                                    "click",
                                    lambda _, role_id=row["role_id"]: select_role_details(role_id),
                                )
                                with card:
                                    with ui.row().classes("w-full items-start no-wrap gap-3"):
                                        with ui.element("div").classes("governance-card-icon"):
                                            ui.icon("badge", size="18px")
                                        with ui.column().classes("gap-0.5 min-w-0 grow"):
                                            ui.label(row["role"]).classes(
                                                "text-sm font-semibold leading-tight"
                                            )
                                            with ui.row().classes("items-center gap-2 flex-wrap"):
                                                ui.badge(
                                                    localized_lifecycle_value(row["role_status"]),
                                                    color=(
                                                        "positive" if row["role_status"] == "active"
                                                        else "grey-7"
                                                    ),
                                                ).props("outline")
                                                ui.badge(
                                                    localized_lifecycle_value(row["validity"]),
                                                    color={
                                                        "current": "primary", "future": "warning",
                                                        "expired": "grey-7",
                                                    }.get(row["validity"], "grey-7"),
                                                ).props("outline")
                                        if person.get("account_type") == "person":
                                            remove_button = ui.button(icon="person_remove").props(
                                                'flat round dense color=negative aria-label=' + repr(render_message("webui.render_assignment_cards.accessible_name.remove_role_assignment_4511524e"))
                                            ).tooltip(render_message("webui.render_assignment_cards.tooltip.remove_role_assignment_5541cf2e"))
                                            remove_button.on(
                                                "click.stop",
                                                lambda _, item=row: confirm_remove_role_assignment(item),
                                            )
                                    with ui.element("div").classes(
                                        "governance-list-facts user-role-assignment-facts"
                                    ):
                                        for label, value in (
                                            (
                                                render_message("governance_custody.field.valid_from"),
                                                format_timestamp(row.get("valid_from")),
                                            ),
                                            (
                                                render_message("governance_custody.field.valid_until"),
                                                format_timestamp(row.get("valid_until"))
                                                if row.get("valid_until") else render_message("common.value.no_expiry"),
                                            ),
                                        ):
                                            with ui.column().classes("gap-0 min-w-0"):
                                                ui.label(label).classes("detail-field-label")
                                                ui.label(value).classes("text-sm")
                        start = offset + 1 if rows else 0
                        end = min(offset + assignment_page_size, len(rows))
                        assignment_page_label.text = render_message("webui.render_assignment_cards.text.start_end_of_row_count_f306a12a", start=start, end=end, row_count=len(rows))
                        assignment_page_label.update()
                        (
                            assignment_previous.enable
                            if offset > 0 else assignment_previous.disable
                        )()
                        (
                            assignment_next.enable
                            if offset + assignment_page_size < len(rows)
                            else assignment_next.disable
                        )()

                    with ui.row().classes("w-full items-center justify-end gap-2"):
                        assignment_page_label = ui.label().classes(
                            "text-sm text-slate-500"
                        )
                        assignment_previous = ui.button(
                            render_message("webui.select_user_details.button.previous_c3ab235e"), icon="chevron_left",
                        ).props("flat dense no-caps")
                        assignment_next = ui.button(
                            render_message("webui.select_user_details.button.next_8ec4fd0d"), icon="chevron_right",
                        ).props("flat dense no-caps")

                    def previous_assignment_page() -> None:
                        assignment_state["offset"] = max(
                            0, assignment_state["offset"] - assignment_page_size,
                        )
                        render_assignment_cards()

                    def next_assignment_page() -> None:
                        assignment_state["offset"] += assignment_page_size
                        render_assignment_cards()

                    assignment_previous.on("click", previous_assignment_page)
                    assignment_next.on("click", next_assignment_page)

                    def filter_assignments() -> None:
                        query = (assignment_search.value or "").strip().casefold()
                        assignment_state["filtered_rows"] = [row for row in assignment_rows if (
                            (not query or query in row["role"].casefold())
                            and (assignment_status.value == "all" or row["role_status"] == assignment_status.value)
                            and (assignment_validity.value == "all" or row["validity"] == assignment_validity.value)
                        )]
                        assignment_state["offset"] = 0
                        render_assignment_cards()
                    for control in (assignment_search, assignment_status, assignment_validity):
                        control.on_value_change(filter_assignments)
                    render_assignment_cards()

                ui.label(render_message("webui.select_user_details.label.login_sessions_de5397b3")).classes("text-lg font-semibold")
                session_state = {"offset": 0, "total": 0}
                with ui.row().classes("w-full items-end gap-2"):
                    session_query = ui.input(render_message("webui.select_user_details.input.filter_ip_address_or_client_64fa5df1")).props("outlined dense clearable").classes("grow")
                    session_status = ui.select({"all": render_message("webui.select_user_details.select.all_statuses_b9224edc"), "active": render_message("webui.select_user_details.select.active_f7618f84"), "expired": render_message("webui.select_user_details.select.expired_2de6a536"), "revoked": render_message("webui.select_user_details.select.revoked_b00af086")}, value="all", label=render_message("webui.select_user_details.select.status_c70ce87f")).props("outlined dense options-dense").classes("w-40")
                    session_sort = ui.select({"date_created": render_message("webui.select_user_details.select.signed_in_a135bd95"), "last_seen_at": render_message("webui.select_user_details.select.last_activity_5d50cd9c"), "expires_at": render_message("webui.select_user_details.select.expiry_eac3052e"), "status": render_message("webui.select_user_details.select.status_c70ce87f"), "client_ip": render_message("webui.select_user_details.select.ip_address_fa3c293f")}, value="date_created", label=render_message("webui.select_user_details.select.sort_by_1afd841f")).props("outlined dense options-dense").classes("w-40")
                    session_direction = ui.select({True: render_message("webui.select_user_details.select.newest_descending_39a02332"), False: render_message("webui.select_user_details.select.oldest_ascending_e8d9a6e3")}, value=True, label=render_message("webui.select_user_details.select.direction_fe0bb3f8")).props("outlined dense options-dense").classes("w-48")
                session_results = ui.element("div").classes("login-session-card-grid w-full")
                with ui.row().classes("w-full items-center justify-end gap-2"):
                    session_page_label = ui.label().classes("text-sm text-slate-500")
                    session_previous = ui.button(render_message("webui.select_user_details.button.previous_c3ab235e"), icon="chevron_left").props("flat dense no-caps")
                    session_next = ui.button(render_message("webui.select_user_details.button.next_8ec4fd0d"), icon="chevron_right").props("flat dense no-caps")

                def session_client_summary(user_agent: str | None) -> tuple[str, str]:
                    value = user_agent or render_message("webui.session_client_summary.text.unknown_client_4f0f1eaa")
                    browser = next((
                        name for token, name in (
                            ("Edg/", "Microsoft Edge"), ("Chrome/", "Google Chrome"),
                            ("Firefox/", "Mozilla Firefox"), ("Safari/", "Safari"),
                        ) if token in value
                    ), "Browser")
                    platform = next((
                        name for token, name in (
                            ("Macintosh", "macOS"), ("Windows", "Windows"),
                            ("Android", "Android"), ("iPhone", "iOS"), ("Linux", "Linux"),
                        ) if token in value
                    ), "Unknown platform")
                    return browser, platform

                def render_user_session_card(row: dict[str, Any]) -> None:
                    browser, platform = session_client_summary(row.get("user_agent"))
                    with ui.card().classes("login-session-card shadow-none"):
                        with ui.row().classes("w-full items-start no-wrap gap-3"):
                            with ui.element("div").classes("governance-card-icon"):
                                ui.icon("devices", size="20px")
                            with ui.column().classes("gap-0 min-w-0 grow"):
                                ui.label(render_message("webui.render_user_session_card.label.browser_on_platform_25d1de9d", browser=browser, platform=platform)).classes(
                                    "font-semibold leading-tight"
                                )
                                ui.label(row.get("client_ip") or render_message("webui.render_user_session_card.label.no_ip_address_7ed4d5af")).classes(
                                    "text-xs text-slate-500"
                                )
                                if row.get("is_current"):
                                    ui.badge(render_message("webui.render_user_session_card.badge.current_session_147b14e1"), color="primary").props(
                                        "outline"
                                    ).classes("mt-1")
                            ui.badge(
                                localized_lifecycle_value(row.get("status")),
                                color={
                                    "active": "positive", "revoked": "negative",
                                    "expired": "grey-7",
                                }.get(row.get("status"), "grey-7"),
                            ).props("outline")
                        with ui.grid(columns=3).classes("w-full gap-x-4 gap-y-3"):
                            session_facts = (
                                (render_message("webui.render_user_session_card.text.signed_in_9afb1dc2"), format_timestamp(row.get("date_created"))),
                                (render_message("webui.render_user_session_card.text.last_activity_d589888e"), format_timestamp(row.get("last_seen_at"))),
                                (render_message("webui.render_user_session_card.text.expires_7fe8054a"), format_timestamp(row.get("expires_at"))),
                            )
                            for label, value in session_facts:
                                with ui.column().classes("gap-0 min-w-0"):
                                    ui.label(label).classes("detail-field-label")
                                    ui.label(value).classes("text-xs truncate w-full").tooltip(value)
                        with ui.row().classes(
                            "w-full items-center no-wrap border-t border-slate-100 pt-2 gap-2"
                        ):
                            ui.icon("devices", color="primary", size="18px")
                            user_agent = row.get("user_agent") or render_message("webui.render_user_session_card.text.unknown_client_9a92525c")
                            ui.label(user_agent).classes(
                                "text-xs text-slate-500 truncate grow"
                            ).tooltip(user_agent)
                            if row.get("status") == "active":
                                ui.button(
                                    icon="logout",
                                    on_click=lambda _, item=row: revoke_user_session_by_row(item),
                                ).props("outline dense color=negative").classes(
                                    "login-session-action-button"
                                ).tooltip(render_message("webui.render_user_session_card.tooltip.force_sign_out_this_session_e9c1809a"))

                async def load_session_page(*, reset: bool = False) -> None:
                    nonlocal session_page_size
                    if reset: session_state["offset"] = 0
                    try:
                        page = await api.login_sessions_page(
                            user_id, limit=None, offset=session_state["offset"],
                            query=session_query.value or "", session_status=session_status.value or "all",
                            sort_by=session_sort.value or "date_created", descending=bool(session_direction.value),
                        )
                    except ApiError as error:
                        ui.notify(error_message(error), color="negative", close_button=True); return
                    if get_principal() is not principal or current_page() != "user-details" or view_token is not token:
                        return
                    session_page_size = page["limit"]
                    session_state["total"] = page["total"]
                    session_results.clear()
                    with session_results:
                        if not page["items"]:
                            ui.label(render_message("webui.load_session_page.label.no_login_sessions_match_these_filters_2d61ac49")).classes(
                                "w-full text-center text-slate-400 py-8"
                            )
                        for session_row in page["items"]:
                            render_user_session_card(session_row)
                    start = session_state["offset"] + 1 if page["total"] else 0
                    end = min(session_state["offset"] + len(page["items"]), page["total"])
                    session_page_label.text = render_message("webui.load_session_page.text.start_end_of_total_f25c586b", start=start, end=end, total=page['total']); session_page_label.update()
                    (session_previous.enable if session_state["offset"] > 0 else session_previous.disable)()
                    (session_next.enable if session_state["offset"] + session_page_size < page["total"] else session_next.disable)()

                async def previous_sessions() -> None:
                    session_state["offset"] = max(0, session_state["offset"] - session_page_size); await load_session_page()
                async def next_sessions() -> None:
                    session_state["offset"] += session_page_size; await load_session_page()
                session_previous.on("click", previous_sessions); session_next.on("click", next_sessions)
                for control in (session_query, session_status, session_sort, session_direction):
                    control.on_value_change(lambda: load_session_page(reset=True))
                async def revoke_user_session_by_row(row: dict[str, Any]) -> None:
                    try:
                        await api.revoke_session(row["id"])
                        ui.notify(render_message("webui.revoke_user_session_by_row.notify.login_session_revoked_d6338377"), color="positive")
                        await load_session_page()
                    except ApiError as error:
                        ui.notify(error_message(error), color="negative", close_button=True)
                await load_session_page()


    return select_user_details
