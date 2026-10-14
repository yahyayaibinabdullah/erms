"""Settings events use the real shared timeline/detail/navigation callbacks."""
import ast
import asyncio
import copy
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import ui
from nicegui.testing import User
from frontend.webui.api_client import ApiError
from frontend.webui.audit_labels import audit_entity_type_label
from frontend.webui.capabilities import can_navigate
from frontend.webui.event_labels import event_label, EVENT_MESSAGE_KEYS
from frontend.webui.i18n_catalogue import render_message, render_message_plain, set_active_messages, strip_diagnostic_metadata

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio
ROOT=Path(__file__).parents[4]
TREE=ast.parse((ROOT/'frontend/webui/app.py').read_text())
NAMES={'event_reference_value','event_value','event_entity_identity','event_actor_identity','can_open_event_entity','navigate_to_event_entity','show_event_detail','render_event_timeline','guarded_page_navigation'}
FUNCTIONS=[n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in NAMES]
AR={r['message_key']:r['translated_text'] for r in json.loads((ROOT/'frontend/webui/i18n/messages.ar.generated.json').read_text())['items']}
OPERATIONS=['APPLICATION_SETTING_CHANGED','APPLICATION_SETTING_SEEDED','APPLICATION_SETTINGS_MIGRATION_COMPLETED']


@pytest.mark.parametrize('language',['en','ar'])
@pytest.mark.parametrize('authorized,can_leave',[(True,True),(True,False),(False,True)])
async def test_old_settings_events_have_shared_labels_and_guarded_open_links(user:User,language,authorized,can_leave):
    opened=[];holder={}
    api=SimpleNamespace(get=AsyncMock(),cancel_pending_reads=Mock())
    rows=[dict(id=i,entity_type='application_setting',entity_id=38,operation=operation,
               metadata={'setting_key':'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID'},
               actor_name='Fixture Administrator',actor_email='fixture@test.invalid',source='web_ui',occurred_at='2026-10-14T16:00:00Z') for i,operation in enumerate(OPERATIONS,1)]
    original=copy.deepcopy(rows)
    async def select_application_settings(**kwargs):opened.append(kwargs['initial_setting_key'])
    async def discard_guard(_):return can_leave
    @ui.page('/settings-audit-test')
    def page():
        set_active_messages(AR if language=='ar' else {})
        host=ui.column()
        scope=dict(ui=ui,Any=Any,Callable=Callable,asyncio=asyncio,inspect=inspect,json=json,api=api,ApiError=ApiError,
                   auth_state={'principal':{'global_privileges':['app.settings.manage'] if authorized else []}},
                   state={'discard_navigation_guard':discard_guard},can_navigate=can_navigate,
                   render_message=render_message,render_message_plain=render_message_plain,event_label=event_label,
                   audit_entity_type_label=audit_entity_type_label,error_message=str,format_timestamp=lambda v:v,
                   select_application_settings=select_application_settings,table_container=host)
        exec(compile(ast.Module(body=FUNCTIONS,type_ignores=[]),'app.py','exec'),scope)
        holder.update(scope=scope,host=host)
        scope['render_event_timeline'](rows,host)
    await user.open('/settings-audit-test')
    labels=[strip_diagnostic_metadata(label.text) for label in user.find(ui.label).elements]
    for operation in OPERATIONS:
        expected=AR[EVENT_MESSAGE_KEYS[operation]] if language=='ar' else operation.replace('_',' ').title()
        assert expected in labels and operation not in labels
    assert rows==original
    open_key='webui.render_event_timeline.tooltip.open_current_entity_208e2a65'
    open_label=AR[open_key] if language=='ar' else render_message_plain(open_key)
    buttons=[b for b in user.find(ui.button).elements if b._props.get('aria-label')==open_label]
    assert len(buttons)==(3 if authorized else 0)
    if buttons:
        buttons[0].mark('open-setting')
        user.find(marker='open-setting').click();await asyncio.sleep(.03)
    else:
        with user:await holder['scope']['navigate_to_event_entity'](rows[0])
    assert opened==(['DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID'] if authorized and can_leave else [])
    api.get.assert_not_awaited()
    assert api.cancel_pending_reads.call_count==int(authorized and can_leave)
    with user:holder['scope']['show_event_detail'](rows[0])
    detail_buttons=[b for b in user.find(ui.button).elements if b._props.get('icon')=='open_in_new' and b.text]
    assert len(detail_buttons)==int(authorized)
