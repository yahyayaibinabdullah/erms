"""Per-client live mailbox, unread indicator and notification lifecycle."""
from __future__ import annotations
from .api_client import ErmsApiClient
from .messaging_live import LiveMailbox
from .config import api_url
from nicegui import app
from nicegui import background_tasks
import json
from .messaging_live import mailbox_cursor_key
from .i18n_catalogue import render_message
from .messaging_live import stream_events
from nicegui import ui

def build_message_stream(
    *, api, get_principal, get_resource, handle_unauthorized, message_live, message_unread_button, messaging_state, page_client, select_messages,
):
    async def open_live_delivery(event):
        if get_principal() is None:
            return
        identity = event.args
        if identity is not None:
            try:
                from uuid import UUID
                identity = str(UUID(identity))
            except (ValueError, TypeError):
                return
        await select_messages("inbox")
        workspace = messaging_state.get("messaging_workspace")
        if identity and workspace:
            await workspace["open"](identity)


    def show_message_notification(label, identity):
        # ui.notify's raw transport cannot serialize Python action callbacks.
        # The standard notification element supports dynamic Quasar actions;
        # ui.on / emitEvent is NiceGUI's supported browser-event bridge.
        notification = ui.notification(label, actions=[{
            "label": render_message("messaging.action.open"),
            ":handler": "() => emitEvent('messaging_open', " + json.dumps(identity) + ")",
        }], timeout=8, close_button=render_message("messaging.live.close"), html=False)
        notifications = message_live["notifications"]
        notifications[:] = [item for item in notifications if not item._deleted]
        notifications.append(notification)
        if len(notifications) > 32:
            notifications.pop(0).dismiss()


    def stop_message_stream() -> None:
        if message_live["adapter"]:
            message_live["adapter"].stop()
        if message_live["api"]:
            message_live["api"].cancel_pending_reads()
            background_tasks.create(message_live["api"].close())
        message_live.update(adapter=None, api=None, token=None)
        for notification in message_live["notifications"]:
            if not notification._deleted:
                notification.dismiss()
        message_live["notifications"].clear()


    async def refresh_message_unread() -> None:
        principal = get_principal()
        if principal is None:
            return
        result = await api.request("GET", "/api/v1/messages/unread-count")
        if get_principal() is principal:
            message_unread_button.text = render_message("messaging.live.unread", count=result["unread_count"])
            message_unread_button.set_visibility(True)


    async def start_message_stream() -> None:
        principal = get_principal()
        token = app.storage.user.get("session_token")
        if not principal or not token or principal.get("must_change_password"):
            return
        stop_message_stream()
        import hashlib
        cursor_key = mailbox_cursor_key(api_url(), principal["user"]["id"])
        legacy_cursor_key = "wathiq-message-cursor:" + str(principal["user"]["id"]) + ":" + hashlib.sha256(token.encode()).hexdigest()[:24]
        message_live["token"] = token
        is_active = lambda: get_principal() is principal and message_live["token"] == token and page_client.has_socket_connection

        async def load_cursor():
            return await page_client.run_javascript("localStorage.getItem(" + json.dumps(cursor_key) + ") ?? sessionStorage.getItem(" + json.dumps(legacy_cursor_key) + ")", timeout=5)

        async def save_cursor(value):
            if is_active():
                # Browser execution is synchronous: another tab cannot regress
                # this account's persisted checkpoint with an older page.
                script = "(() => { const key = " + json.dumps(cursor_key) + "; const incoming = BigInt(" + json.dumps(str(value)) + "); const stored = localStorage.getItem(key); const previous = stored && /^[0-9]+$/.test(stored) ? BigInt(stored) : 0n; localStorage.setItem(key, String(incoming > previous ? incoming : previous)); return true; })()"
                await page_client.run_javascript(script, timeout=5)

        async def present_message(kind, value):
            if not is_active():
                return
            with page_client:
                if kind == "unread":
                    message_unread_button.text = render_message("messaging.live.unread", count=value)
                    message_unread_button.set_visibility(True)
                elif kind == "summary":
                    label = render_message("messaging.live.test_summary", **value) if isinstance(value, dict) else (render_message("messaging.live.summary_one") if value == 1 else render_message("messaging.live.summary", count=value))
                    show_message_notification(label, None)
                elif kind == "message":
                    # Content was freshly authorized by catch-up. Restricted
                    # deliveries receive only a generic non-disclosing toast.
                    label = render_message("messaging.live.new_message")
                    if value.get("is_test"):
                        label = render_message("messaging.test.label") + " · " + label
                    if value.get("availability") == "available":
                        label += ": " + value.get("toast_subject", value["subject"])
                    show_message_notification(label, value["id"])
                elif kind == "refresh" and get_resource() == "messages-inbox":
                    workspace = messaging_state.get("messaging_workspace")
                    if workspace:
                        await workspace["refresh"]()

        # Navigation cancels ordinary page reads; the stream owns a separate
        # identity-scoped client so those cancellations cannot kill reconciliation.
        live_api = ErmsApiClient(api_url())
        live_api.set_session_token(token)
        live_api.set_unauthorized_handler(handle_unauthorized)
        message_live["api"] = live_api
        adapter = LiveMailbox(api=live_api, events=lambda transport: stream_events(api_url(), token, transport), load_cursor=load_cursor, save_cursor=save_cursor, present=present_message, active=is_active)
        message_live["adapter"] = adapter
        adapter.start()


    return open_live_delivery, show_message_notification, stop_message_stream, refresh_message_unread, start_message_stream
