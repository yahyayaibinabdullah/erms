"""Click the Monitor button using the application's actual navigation wiring."""

import ast
import asyncio
import inspect
import json
from pathlib import Path
from typing import Any, Callable

import pytest
from nicegui import ui
from nicegui.testing import User

from frontend.webui.i18n_catalogue import render_message, render_message_plain, set_active_messages
from frontend.webui.audit_labels import audit_entity_type_label
from frontend.webui.api_client import ApiError
from frontend.webui.messaging_monitor import messaging_monitor
from frontend.webui.navigation_controller import NavigationController
from unittest.mock import Mock, AsyncMock
from frontend.webui.audit_workspace import build_audit_workspace
from frontend.webui.remote_select import RemoteSelect
from frontend.webui.audit_actor_select import bind_audit_actor_select, actor_condition
from nicegui import events as nicegui_events

pytest_plugins = ["nicegui.testing.user_plugin"]
pytestmark = pytest.mark.asyncio


def application_audit_callback(namespace):
    namespace["aggregation_state"] = {}
    tree = ast.parse((Path(__file__).parents[2] / "app.py").read_text())
    navigation = NavigationController(
        stored=[], write_trail=Mock(), prepare=Mock(), snapshot=Mock(), label_key=Mock(),
        get_guard=lambda: namespace['state'].get('discard_navigation_guard'),
        clear_guard=lambda: namespace['state'].pop('discard_navigation_guard', None),
        cancel_reads=namespace['api'].cancel_pending_reads, restore=Mock(), dashboard=Mock(),
        render=Mock(), notify=ui.notify, on_error=str,
    )
    namespace['guarded_page_navigation'] = navigation.guarded_page_navigation
    audit_page = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                      and n.name == "enter_audit_trail")
    exec(compile(ast.Module(body=[audit_page], type_ignores=[]), "app.py", "exec"), namespace)
    workspace=build_audit_workspace(
        api=namespace['api'],table_container=namespace['table_container'],
        principal=lambda:{'global_privileges':['audit.view']},
        selected=lambda:namespace['state'].get('resource')=='audit-trail',
        enter=namespace['enter_audit_trail'],error_message=str,format_timestamp=str,
        set_connection_status=namespace['set_connection_status'],
        can_open_settings=lambda:False,open_settings=AsyncMock(),open_destination=AsyncMock(),
    )
    namespace['select_audit_trail']=workspace.select_audit_trail
    monitor = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Name) and n.func.id == "messaging_monitor")
    callback = next(k.value for k in monitor.keywords if k.arg == "open_audit")
    return eval(compile(ast.Expression(callback), "app.py", "eval"), namespace)


@pytest.mark.parametrize("tag", ["en", "ar"])
@pytest.mark.parametrize("authorized,can_leave", [(True, True), (True, False), (False, True)])
async def test_monitor_audit_button_routes_to_dedicated_page_with_navigation_guard(
    user: User, tag, authorized, can_leave,
):
    events = []
    searches = []
    delayed = asyncio.Event()
    translations = {
        r["message_key"]: r["translated_text"]
        for r in json.loads((Path(__file__).parents[2] / "i18n/messages.ar.generated.json").read_text())["items"]
    } if tag == "ar" else {}
    button_text = translations.get("messaging.monitor.audit") or render_message_plain("messaging.monitor.audit")
    title_key = "webui.select_audit_trail.text.audit_trail_2f72156b"
    title_text = translations.get(title_key) or render_message_plain(title_key)

    class Api:
        async def audit_actors(self, query, **kwargs):
            return {"items": [], "has_more": False}

        def cancel_pending_reads(self):
            events.append("cancel")

        async def request(self, method, path, **kwargs):
            if path.endswith(("/gateways", "/producers")):
                return {"items": [], "next_cursor": None}
            return {"alerts": [], "metrics": [], "retention": {}, "can_view_audit": authorized}

        async def event_history_filter_options(self):
            # No notification events yet: the shortcut must stay scoped anyway.
            return {"entity_types": ["record"], "operations": ["EXPORT"], "sources": ["api"], "actor_types": ["user"]}

        async def search_request(self, resource, payload):
            assert resource == "event-history"
            searches.append(payload)
            if "Delayed Actor" in str(payload):
                await delayed.wait()
                return {"items": [{"id": 999, "entity_type":"system_notification", "entity_id":999, "operation":"EXPORT", "occurred_at":"2026-01-01", "actor_name":"Delayed response actor"}], "total": 1}
            return {"items": [{"id": 1, "entity_type": "system_notification", "entity_id": 1, "operation":"EXPORT", "occurred_at":"2026-01-01", "actor_name":"Fixture actor"}], "total": 75}

    @ui.page("/monitor-audit-navigation")
    async def page():
        set_active_messages(translations)
        host = ui.column()
        api = Api()

        async def discard_guard(reason):
            assert reason == "leave this page"
            return can_leave

        namespace = {
            "state": {"discard_navigation_guard": discard_guard}, "api": api,
            "inspect": inspect, "Callable": Callable, "Any": Any,
            "ui": ui, "render_message": render_message,
            "RemoteSelect": RemoteSelect, "bind_audit_actor_select": bind_audit_actor_select,
            "actor_condition": actor_condition, "error_message": str,
            "audit_entity_type_label": audit_entity_type_label,
            "register_navigation": lambda *args: events.append("audit"),
            "show_authenticated_view": lambda: None,
            "title": ui.label(), "subtitle": ui.label(), "guidance": ui.label(),
            "add_button": ui.button(), "add_record_button": ui.button(),
            "search_bar": ui.row(), "aggregation_mode_bar": ui.row(),
            "table_container": host, "ApiError": ApiError,
            "set_connection_status": lambda connected: None,
            "event_label": str,
        }
        callback = application_audit_callback(namespace)
        ui.button("Sidebar audit fixture", on_click=lambda: namespace["guarded_page_navigation"](
            namespace["select_audit_trail"]
        )).mark("sidebar-audit")
        await messaging_monitor(api=api, container=host, active=lambda:True,
                                format_timestamp=str, open_audit=callback)

    await user.open("/monitor-audit-navigation")
    if not authorized:
        await user.should_not_see(button_text)
        assert events == []
        return
    user.find(button_text).click()
    if can_leave:
        await user.should_see(title_text)
        assert events == ["cancel", "audit"]
        assert searches[0]["where"] == {
            "field": "entity_type", "operator": "eq", "value": "system_notification",
        }
        assert searches[0]["limit"] == 50 and searches[0]["offset"] == 0
        assert any(control.value == "system_notification" for control in user.find(kind=ui.select).elements)
        await user.should_not_see(button_text)
        next_key = "webui.select_audit_trail.button.next_4982f418"
        user.find(translations.get(next_key) or render_message_plain(next_key)).click()
        await user.should_see("51")
        assert searches[-1]["offset"] == 50
        assert searches[-1]["where"] == searches[0]["where"]
        actor_label = translations.get("audit.filter.actor_identity") or render_message_plain("audit.filter.actor_identity")
        apply_label = translations.get("webui.select_audit_trail.button.apply_filters_bf49489c") or render_message_plain("webui.select_audit_trail.button.apply_filters_bf49489c")
        def label(key):
            return translations.get(key) or render_message_plain(key)

        for suffix, value in (("operation_c3539ad5", "EXPORT"), ("source_47e0b469", "api"), ("actor_type_1e26e211", "user")):
            next(c for c in user.find(kind=ui.select).elements
                 if c._props.get("label") == label("webui.select_audit_trail.select." + suffix)).value = value
        for suffix, value in (("from_0cee5608", "2026-01-01T00:00"), ("until_dafbbcb5", "2026-12-31T23:59"), ("correlation_id_e6872415", "11111111-1111-4111-8111-111111111111")):
            next(c for c in user.find(kind=ui.input).elements
                 if c._props.get("label") == label("webui.select_audit_trail.input." + suffix)).value = value
        next(c for c in user.find(kind=ui.number).elements
             if c._props.get("label") == label("webui.select_audit_trail.number.entity_id_39367eca")).value = 123
        actor_control = next(iter(user.find(actor_label).elements))
        def type_actor(text):
            with user.client:
                event = nicegui_events.GenericEventArguments(sender=actor_control, client=user.client, args=text)
                for listener in actor_control._event_listeners.values():
                    if listener.type == 'inputValue':
                        nicegui_events.handle_event(listener.handler,event)
        type_actor("  Someone%@Example  ")
        user.find(apply_label).click()
        await user.should_not_see("51")
        assert searches[-1]["offset"] == 0
        assert searches[-1]["where"] == {"and": [searches[0]["where"],
            {"field": "operation", "operator": "eq", "value": "EXPORT"},
            {"field": "source", "operator": "eq", "value": "api"},
            {"field": "actor_type", "operator": "eq", "value": "user"},
            {"field": "entity_id", "operator": "eq", "value": 123},
            {"field": "correlation_id", "operator": "eq", "value": "11111111-1111-4111-8111-111111111111"},
            {"field": "occurred_at", "operator": "gte", "value": "2026-01-01T00:00"},
            {"field": "occurred_at", "operator": "lte", "value": "2026-12-31T23:59"},
            {"or": [
            {"field": field, "operator": "contains_ci", "value": "Someone%@Example"}
            for field in ("actor_name", "actor_email")
        ]}]}
        user.find(translations.get("audit.filter.clear") or render_message_plain("audit.filter.clear")).click()
        await asyncio.sleep(0.1)
        await user.should_see(title_text)
        assert searches[-1]["where"] == searches[0]["where"]
        type_actor("Delayed Actor")
        user.find(apply_label).click()
        await asyncio.sleep(0.1)
        user.find(marker="sidebar-audit").click()
        await asyncio.sleep(0.1)
        await user.should_not_see("51")
        assert "where" not in searches[-1]
        assert searches[-1]["offset"] == 0
        delayed.set()
        await asyncio.sleep(0.1)
        await user.should_not_see("Delayed response actor")
        await user.should_see("Fixture actor")
    else:
        await user.should_see(button_text)
        assert events == []
