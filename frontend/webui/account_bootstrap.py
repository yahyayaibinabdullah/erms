"""Existing account bootstrap behavior with explicit session dependencies."""
from __future__ import annotations
from typing import Any
from nicegui import app, background_tasks
from .api_client import ApiError


def build_account_bootstrap(
    *, api, page_client, initial_language, initial_direction, apply_document_direction, load_localization_context, accept_application_configuration, get_configuration, populate_user_menu, load_authenticated_client_assets, start_message_stream, refresh_hold_navigation, set_principal, drawer, table_container, show_change_password, q, navigation_controller, run_global_search, restore_navigation_entry, render_navigation_breadcrumbs, select_dashboard, clear_signed_in_identity, set_connection_status, login_dialog,
):
    async def prepare_authenticated_workspace(principal: dict[str, Any]) -> bool:
        """Load ordinary application state only after password restrictions end."""
        if await load_localization_context():
            return False
        accept_application_configuration(get_configuration())
        populate_user_menu(principal)
        background_tasks.create(load_authenticated_client_assets())
        background_tasks.create(start_message_stream())
        await refresh_hold_navigation()
        return True


    async def load_login_animation() -> None:
        """Load and start the shared login/header animation off the critical path."""
        try:
            # This coroutine is deliberately scheduled as a background task, so
            # it must use the page's captured client instead of relying on
            # NiceGUI's ambient slot/client context.
            await page_client.run_javascript(
                "new Promise((resolve, reject) => {"
                "if (window.startWathiqLoginNetwork) { resolve(true); return; }"
                "const script = document.createElement('script');"
                "script.src = '/static/login/network-background.js?v=5';"
                "script.onload = () => resolve(true);"
                "script.onerror = () => reject(new Error('Login animation failed to load'));"
                "document.head.appendChild(script);"
                "})",
                timeout=15,
            )
            await page_client.run_javascript(
                "window.startWathiqLoginNetwork?.(); true", timeout=5,
            )
        except Exception:
            return


    async def initialize_authenticated_ui() -> None:
        # Signed-out pages need the same root and portal direction as signed-in
        # pages; localization bootstrap normally runs only after authentication.
        await apply_document_direction(initial_language, initial_direction)
        # The same asset drives both the sign-in background and the authenticated
        # header. Load it for every session, including restored sessions which
        # never display the sign-in dialog.
        background_tasks.create(load_login_animation())
        token = app.storage.user.get("session_token")
        if token:
            api.set_session_token(token)
            try:
                principal = await api.me()
                if principal["must_change_password"]:
                    set_principal(principal)
                    drawer.hide()
                    with table_container:
                        await show_change_password()
                    return
                if not await prepare_authenticated_workspace(principal):
                    return
                if q.strip():
                    navigation_controller.trail = []
                    await run_global_search(q)
                elif navigation_controller.trail:
                    navigation_controller.restoring = True
                    try:
                        await restore_navigation_entry(navigation_controller.trail[-1])
                    finally:
                        navigation_controller.restoring = False
                        render_navigation_breadcrumbs()
                else:
                    await select_dashboard()
                return
            except ApiError:
                app.storage.user.pop("session_token", None)
                api.set_session_token(None)
        clear_signed_in_identity()
        set_connection_status(True)
        drawer.hide()
        login_dialog.open()


    return prepare_authenticated_workspace, initialize_authenticated_ui
