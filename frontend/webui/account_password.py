"""Existing account password behavior with explicit session dependencies."""
from __future__ import annotations
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message


def build_account_password(
    *, api, get_principal, prepare_authenticated_workspace, select_dashboard, sign_out, error_message,
):
    async def show_change_password() -> None:
        forced_change = bool(
            (get_principal() or {}).get("must_change_password")
        )
        dialog = ui.dialog().props("persistent")
        with dialog, ui.card().classes("w-[480px] max-w-full"):
            ui.label(
                render_message("webui.show_change_password.label.set_a_new_password_f6a268ba") if forced_change else render_message("webui.show_change_password.label.change_password_01795a6b")
            ).classes("text-xl font-semibold")
            if forced_change:
                ui.label(
                    render_message("webui.show_change_password.label.your_temporary_password_must_be_replaced_b_2cba2da1")
                ).classes("text-sm text-slate-500")
            current = ui.input(
                render_message("webui.show_change_password.input.temporary_password_b83bc142") if forced_change else render_message("webui.show_change_password.input.current_password_00f4f73a"),
                password=True,
                password_toggle_button=True,
            ).props('outlined autocomplete=current-password input-style="direction: ltr; unicode-bidi: isolate;"').classes("w-full")
            new = ui.input(render_message("webui.show_change_password.input.new_password_28399c5b"), password=True, password_toggle_button=True).props("outlined").classes("w-full")
            confirm = ui.input(render_message("webui.show_change_password.input.confirm_new_password_abd1d774"), password=True).props("outlined").classes("w-full")

            async def save_password() -> None:
                if new.value != confirm.value:
                    ui.notify(render_message("webui.save_password.notify.new_passwords_do_not_match_26d93e32"), color="warning")
                    return
                try:
                    await api.change_password(current.value or "", new.value or "")
                    dialog.close()
                    ui.notify(render_message("webui.save_password.notify.password_changed_9140fb7f"), color="positive")
                    principal = await api.me()
                    if not await prepare_authenticated_workspace(principal):
                        return
                    await select_dashboard()
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)

            async def return_to_sign_in() -> None:
                # A forced-change session is deliberately restricted. Let the
                # person abandon it safely when the temporary password is no
                # longer available, instead of trapping them in this dialog.
                dialog.close()
                await sign_out()

            with ui.row().classes("w-full justify-end"):
                if forced_change:
                    ui.button(
                        render_message("webui.show_change_password.button.back_to_sign_in_a4e9c09d"), icon="arrow_back",
                        on_click=return_to_sign_in,
                    ).props("flat no-caps")
                else:
                    ui.button(render_message("webui.show_change_password.button.cancel_6a686362"), on_click=dialog.close).props("flat")
                ui.button(
                    render_message("webui.show_change_password.button.set_new_password_067753d1") if forced_change else render_message("webui.show_change_password.button.change_password_81533b94"),
                    icon="password",
                    on_click=save_password,
                ).props("unelevated")
        dialog.open()


    return show_change_password
