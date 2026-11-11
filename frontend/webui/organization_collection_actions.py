"""Existing organization table actions and their explicit collection callbacks."""
from __future__ import annotations
from .api_client import ApiError
from .i18n_catalogue import render_message
from nicegui import ui


def build_issue_password(*, api, error_message, format_timestamp):
    async def issue_password(event) -> None:
        try:
            result = await api.issue_temporary_password(event.args["id"])
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return
        dialog = ui.dialog().props("persistent")
        with dialog, ui.card().classes("w-[520px] max-w-full"):
            ui.label(render_message("webui.issue_password.label.temporary_password_2069ddbc")).classes("text-xl font-semibold")
            ui.label(render_message("webui.issue_password.label.copy_this_password_now_it_will_not_be_show_289e8425")).classes("text-sm text-slate-500")
            ui.code(result["temporary_password"]).classes("w-full text-lg")
            ui.label(render_message("webui.issue_password.label.expires_format_timestamp_45b017c7", format_timestamp=format_timestamp(result['expires_at']))).classes("text-xs text-slate-400")
            with ui.row().classes("w-full justify-end"):
                ui.button(render_message("webui.issue_password.button.i_have_copied_it_2fc9a18e"), on_click=dialog.close).props("unelevated no-caps")
        dialog.open()

    return issue_password


def build_change_suspension(*, api, current_session_revoked, decorate_for_spec, get_principal, get_rows, render_table, set_rows, show_api_error, spec):
    async def change_suspension(event, *, suspended: bool) -> None:
        row = event.args
        action = render_message("webui.change_suspension.text.suspend_a1029af3") if suspended else render_message("webui.change_suspension.text.unsuspend_41fef4cf")
        dialog = ui.dialog()
        with dialog, ui.card().classes("w-[520px] max-w-full"):
            ui.label(render_message("webui.change_suspension.label.action_user_06f864cb", action=action)).classes("text-xl font-semibold")
            ui.label(row.get("name") or render_message("webui.change_suspension.label.id_deaa5a5b", id=row['id'])).classes("font-medium")
            ui.label(
                render_message("webui.change_suspension.label.all_active_sessions_will_be_revoked_the_us_e789a9b9")
                if suspended else
                render_message("webui.change_suspension.label.the_account_will_become_active_again_previ_fceeb526")
            ).classes("text-sm text-slate-600")

            async def proceed() -> None:
                try:
                    saved = await api.set_user_suspended(
                        row["id"], row["version"], suspended=suspended,
                    )
                    dialog.close()
                    if suspended and row["id"] == get_principal()["user"]["id"]:
                        current_session_revoked()
                        return
                    set_rows([
                        saved if item["id"] == saved["id"] else item
                        for item in get_rows()
                    ])
                    set_rows(await decorate_for_spec(spec, get_rows()))
                    render_table(spec)
                    ui.notify(render_message("webui.proceed.notify.user_lower_ed_9fe77e33", lower=action.lower()), color="positive")
                except ApiError as error:
                    show_api_error(error)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.change_suspension.button.cancel_7d52ce8e"), on_click=dialog.close).props("flat no-caps")
                ui.button(action, on_click=proceed).props("unelevated no-caps")
        dialog.open()

    return change_suspension


def build_confirm_lifecycle(*, api, current_session_revoked, decorate_for_spec, get_principal, get_rows, render_table, set_rows, show_api_error, spec):
    async def confirm_lifecycle(event) -> None:
        row = event.args
        activating = row.get("status") == "inactive"
        action = render_message("webui.confirm_lifecycle.text.activate_4a659dd4") if activating else render_message("webui.confirm_lifecycle.text.deactivate_dd352ea2")
        dialog = ui.dialog()
        with dialog, ui.card().classes("w-[520px] max-w-full"):
            ui.label(render_message("webui.confirm_lifecycle.label.action_singular_abe41001", action=action, singular=spec.singular)).classes("text-xl font-semibold")
            ui.label(row.get("name") or row.get("code") or render_message("webui.confirm_lifecycle.label.id_01b3b0e1", id=row['id'])).classes("font-medium")
            if spec.key == "org-units":
                message = (
                    render_message("webui.confirm_lifecycle.text.its_roles_and_descendant_unit_roles_become_d117ff90")
                    if activating else
                    render_message("webui.confirm_lifecycle.text.roles_in_this_unit_and_every_descendant_un_688329e2")
                )
            elif spec.key == "roles":
                message = (
                    render_message("webui.confirm_lifecycle.text.existing_assignments_can_contribute_author_ee495e15")
                    if activating else
                    render_message("webui.confirm_lifecycle.text.existing_users_and_assignments_remain_unch_49553f07")
                )
            else:
                message = (
                    render_message("webui.confirm_lifecycle.text.the_user_can_authenticate_again_existing_r_8ed548e9")
                    if activating else
                    render_message("webui.confirm_lifecycle.text.all_active_login_sessions_will_be_revoked_080d677f")
                )
            ui.label(message).classes("text-sm text-slate-600")

            async def proceed() -> None:
                try:
                    saved = await api.set_active(
                        spec.key, row["id"], row["version"], active=activating,
                    )
                    dialog.close()
                    if (
                        spec.key == "users" and not activating
                        and row["id"] == get_principal()["user"]["id"]
                    ):
                        current_session_revoked()
                        return
                    set_rows([
                        saved if item["id"] == saved["id"] else item
                        for item in get_rows()
                    ])
                    set_rows(await decorate_for_spec(spec, get_rows()))
                    render_table(spec)
                    ui.notify(
                        render_message(
                            "webui.proceed.notify.entity_activated"
                            if activating else
                            "webui.proceed.notify.entity_deactivated"
                        ),
                        color="positive",
                    )
                except ApiError as error:
                    show_api_error(error)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.confirm_lifecycle.button.cancel_4534950b"), on_click=dialog.close).props("flat no-caps")
                ui.button(action, on_click=proceed, icon="toggle_on" if activating else "toggle_off").props(
                    f"unelevated no-caps color={'positive' if activating else 'negative'}"
                )
        dialog.open()

    return confirm_lifecycle
