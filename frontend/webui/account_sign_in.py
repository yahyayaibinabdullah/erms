"""Existing sign-in dialog; SessionContext continues to own authentication."""
from __future__ import annotations
from nicegui import ui, context
from .api_client import ApiError
from .i18n_catalogue import render_message, render_message_plain


def build_login_error_message(error_message):
    def login_error_message(error: ApiError) -> str:
        """Distinguish rejected credentials from an expired authenticated session."""
        if error.status_code == 401:
            return render_message_plain("authentication.error.credentials_not_accepted")
        return error_message(error)

    return login_error_message


def build_sign_in(
    *, session, initial_direction, initial_language, set_principal, drawer,
    table_container, show_change_password, prepare_authenticated_workspace,
    select_dashboard, login_error_message,
):
    login_dialog = ui.dialog().props("persistent")
    with login_dialog:
        ui.element("canvas").classes(
            "wathiq-network-canvas wathiq-login-network"
        ).props(
            'aria-label=' + repr(render_message("webui.index.accessible_name.slowly_moving_connected_node_background_acc8bb9e"))
        )
        with ui.card().classes("wathiq-login-card").props(f"dir={initial_direction} lang={initial_language}"):
            with ui.row().classes("w-full items-stretch no-wrap gap-0"):
                with ui.column().classes(
                    "wathiq-login-brand-panel shrink-0 justify-between gap-0"
                ):
                    with ui.column().classes("gap-6"):
                        with ui.row().classes("items-center gap-3 no-wrap"):
                            ui.image("/static/brand/wathiq-mark.svg?v=2").classes(
                                "wathiq-login-mark"
                            ).props("fit=contain alt='Wathiq mark'")
                            ui.label(render_message("webui.index.label.wathiq_d1dfb800")).classes("wathiq-login-word")
                        with ui.column().classes("gap-2"):
                            ui.label(render_message("webui.index.label.your_records_your_evidence_in_order_68fc50b3")).classes(
                                "text-2xl font-semibold leading-tight whitespace-pre-line"
                            )
                            ui.label(
                                render_message("webui.index.label.secure_access_to_the_sharjah_archives_reco_bb9eea0d")
                            ).classes("text-sm leading-5 text-slate-600")
                    ui.label(
                        render_message("webui.index.label.reliable_stewardship_accountable_governanc_24177911")
                    ).classes("text-xs leading-5 text-slate-500 whitespace-pre-line")
                with ui.column().classes("wathiq-login-form gap-3"):
                    ui.label(render_message("webui.index.label.sign_in_01f3842a")).classes("text-2xl font-semibold")
                    ui.label(render_message("webui.index.label.use_your_organization_credentials_to_conti_01d4d0eb")).classes(
                        "text-sm text-slate-500 mb-2"
                    )
                    login_email = ui.input(render_message("webui.index.input.email_address_2569f0e9")).props(
                        'outlined autocomplete=username input-style="direction: ltr; unicode-bidi: isolate;"'
                    ).classes("w-full")
                    login_password = ui.input(
                        render_message("webui.index.input.password_f76ddde6"), password=True, password_toggle_button=True
                    ).props('outlined autocomplete=current-password input-style="direction: ltr; unicode-bidi: isolate;"').classes("w-full")
                    login_error = ui.label().classes(
                        "wathiq-login-error text-negative text-sm"
                    )
                    login_submit = ui.button(
                        render_message("webui.index.button.continue_to_wathiq_9cc920d0"),
                        icon=None if initial_direction == "rtl" else "login",
                    ).props(
                        "unelevated no-caps"
                    ).classes("w-full wathiq-login-submit")
                    if initial_direction == "rtl":
                        login_submit.props("icon-right=login")
                    ui.label(render_message("webui.index.label.need_help_contact_your_system_administrato_9f127b23")).classes(
                        "w-full text-center text-xs text-slate-400 mt-1"
                    )

        async def submit_login() -> None:
            login_error.text = ""
            try:
                principal = await session.sign_in(
                    login_email.value or "", login_password.value or "",
                    user_agent=context.client.request.headers.get("user-agent"),
                )
                login_password.value = ""
                login_dialog.close()
                if principal["must_change_password"]:
                    # Until the password is replaced, FastAPI intentionally
                    # rejects every endpoint except /auth/me, change-password,
                    # and logout.  Do not make ordinary application requests
                    # (such as favourites) before showing this dialog.
                    set_principal(principal)
                    drawer.hide()
                    with table_container:
                        await show_change_password()
                    return
                if not await prepare_authenticated_workspace(principal):
                    return
                await select_dashboard()
            except ApiError as error:
                login_error.text = login_error_message(error)

        login_submit.on("click", submit_login)
        login_password.on("keydown.enter", submit_login)

    return login_dialog
