"""Existing account profile behavior with explicit session dependencies."""
from __future__ import annotations
from typing import Any
from nicegui import ui, background_tasks
from .api_client import ApiError
from .i18n_catalogue import render_message
from .identity_presentation import user_avatar


def build_account_profile(
    *, api, get_principal, set_principal, drawer, mobile_navigation, header_network, holds_navigation, refresh_drawer_visibility, synchronize_translation_inspector, current_user_name, current_user_email, current_user_avatar_initials, current_user_avatar, current_user_last_login, current_user_roles, format_timestamp,
):
    def populate_user_menu(principal: dict[str, Any]) -> None:
        drawer.show()
        mobile_navigation.set_visibility(True)
        header_network.set_visibility(True)
        set_principal(principal)
        privileges = set(principal.get("global_privileges", []))
        holds_navigation.set_visibility(False)
        refresh_drawer_visibility(privileges)
        background_tasks.create(synchronize_translation_inspector(privileges))
        user = principal["user"]
        display_user = {**user, "name": (user.get("localized") or {}).get("name") or user["name"]}
        current_user_name.text = display_user["name"]
        current_user_email.text = user.get("email") or user["account_type"].title()
        avatar = user_avatar(display_user)
        current_user_avatar_initials.text = avatar["initials"]
        current_user_avatar.style(
            replace=(
                f"background:{avatar['color']} !important;"
                f"color:{avatar['text_color']} !important"
            )
        )
        previous_login_at = principal.get("previous_login_at")
        current_user_last_login.text = (
            format_timestamp(previous_login_at) if previous_login_at else render_message("webui.populate_user_menu.text.first_sign_in_42778cbf")
        )
        current_user_roles.clear()
        with current_user_roles:
            if not principal["roles"]:
                ui.label(render_message("webui.populate_user_menu.label.no_assigned_roles_2628632d")).classes("text-xs text-slate-400")
            for role in principal["roles"]:
                with ui.row().classes("erms-profile-role-row w-full items-center gap-2 no-wrap"):
                    ui.icon("badge", size="18px").classes("text-primary")
                    with ui.column().classes("erms-profile-role-copy gap-0 min-w-0"):
                        ui.label((role.get("localized") or {}).get("name") or role["name"]).classes("text-sm font-medium line-clamp-1")
                        unit = role["org_unit"]
                        ui.label((unit.get("localized") or {}).get("name") or unit["name"]).classes("text-xs text-slate-400 line-clamp-1")


    async def refresh_user_profile() -> None:
        if get_principal():
            try:
                populate_user_menu(await api.me())
            except ApiError:
                # The shared unauthorized handler presents sign-in when needed.
                pass


    return populate_user_menu, refresh_user_profile
