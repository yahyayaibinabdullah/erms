"""Host live-mailbox ownership, cleanup, authorization and notification bounds."""
import ast
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
from uuid import uuid4
import pytest
from nicegui import app,ui
from frontend.webui import app as host
pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio
NAMES=['open_live_delivery','show_message_notification','stop_message_stream','refresh_message_unread','start_message_stream']

def build(h,monkeypatch):
    from frontend.webui import message_stream as owner
    for name in ('ErmsApiClient','LiveMailbox','api_url'):
        monkeypatch.setattr(owner,name,h[name])
    h.update(get_principal=lambda:h['auth_state'].get('principal'),get_resource=lambda:h['state'].get('resource'),messaging_state=h['state'])
    return dict(zip(NAMES,owner.build_message_stream(**{key:h[key] for key in inspect.signature(owner.build_message_stream).parameters})))

async def setup(user,monkeypatch):
    h=dict(vars(host),state={},auth_state={'principal':{'user':{'id':7}}},message_live={'adapter':None,'api':None,'token':None,'notifications':[]},api=SimpleNamespace(request=AsyncMock(return_value={'unread_count':4})),api_url=lambda:'http://127.0.0.1:1',select_messages=AsyncMock(),handle_unauthorized=AsyncMock())
    h['clients']=[];h['adapters']=[]
    def client(url):
        value=SimpleNamespace(set_session_token=Mock(),set_unauthorized_handler=Mock(),cancel_pending_reads=Mock(),close=AsyncMock());h['clients'].append(value);return value
    def adapter(**kwargs):
        value=SimpleNamespace(start=Mock(),stop=Mock(),kwargs=kwargs);h['adapters'].append(value);return value
    h['ErmsApiClient']=client;h['LiveMailbox']=adapter
    @ui.page('/mailbox-live-contract')
    async def page():
        h['message_unread_button']=ui.button('initial')
        class Page:
            has_socket_connection=True
            run_javascript=AsyncMock(return_value=None)
            def __enter__(self):return user.client.__enter__()
            def __exit__(self,*args):return user.client.__exit__(*args)
        h['page_client']=Page();app.storage.user['session_token']='synthetic-session';h['functions']=build(h,monkeypatch)
    await user.open('/mailbox-live-contract');return h

@pytest.mark.parametrize('reason',['anonymous','password','no-token'])
async def test_no_stream_for_ineligible_session(user,monkeypatch,reason):
    h=await setup(user,monkeypatch)
    with user:
        if reason=='anonymous':h['auth_state']['principal']=None
        elif reason=='password':h['auth_state']['principal']['must_change_password']=True
        else:app.storage.user.pop('session_token')
        await h['functions']['start_message_stream']()
    assert h['clients']==[] and h['adapters']==[]

async def test_restart_replaces_dedicated_client_and_stop_cleans_every_owned_resource(user,monkeypatch):
    h=await setup(user,monkeypatch);f=h['functions']
    with user:
        await f['start_message_stream']();first=h['clients'][0];adapter=h['adapters'][0]
        first.set_session_token.assert_called_once_with('synthetic-session');first.set_unauthorized_handler.assert_called_once_with(h['handle_unauthorized']);adapter.start.assert_called_once()
        assert adapter.kwargs['api'] is first and first is not h['api']
        for i in range(35):f['show_message_notification']('Synthetic notice',str(uuid4()))
        assert len(h['message_live']['notifications'])==32
        await f['start_message_stream']();await asyncio.sleep(.02)
        adapter.stop.assert_called_once();first.cancel_pending_reads.assert_called_once();first.close.assert_awaited_once()
        assert h['message_live']['notifications']==[] and h['message_live']['api'] is h['clients'][1]
        f['stop_message_stream']();await asyncio.sleep(.02)
    assert h['message_live']=={'adapter':None,'api':None,'token':None,'notifications':[]}
    h['clients'][1].close.assert_awaited_once()

@pytest.mark.parametrize('boundary',['identity','token','disconnect'])
async def test_late_stream_callbacks_cannot_present_into_another_session(user,monkeypatch,boundary):
    h=await setup(user,monkeypatch)
    with user:await h['functions']['start_message_stream']()
    c=h['adapters'][0].kwargs
    if boundary=='identity':h['auth_state']['principal']=dict(h['auth_state']['principal'])
    elif boundary=='token':h['message_live']['token']='replacement'
    else:h['page_client'].has_socket_connection=False
    assert not c['active']();await c['present']('unread',99);await c['save_cursor']('123')
    assert h['message_unread_button'].text=='initial';h['page_client'].run_javascript.assert_not_awaited()

async def test_active_refresh_only_refreshes_inbox_and_unread_is_identity_scoped(user,monkeypatch):
    h=await setup(user,monkeypatch);refresh=AsyncMock();h['state'].update(resource='messages-inbox',messaging_workspace={'refresh':refresh})
    with user:await h['functions']['start_message_stream']()
    c=h['adapters'][0].kwargs;await c['present']('refresh',None);refresh.assert_awaited_once()
    h['state']['resource']='records';await c['present']('refresh',None);refresh.assert_awaited_once()
    async def changed(*args):h['auth_state']['principal']=dict(h['auth_state']['principal']);return {'unread_count':99}
    h['api'].request.side_effect=changed
    with user:await h['functions']['refresh_message_unread']()
    assert h['message_unread_button'].text=='initial'

@pytest.mark.parametrize('identity',['invalid',None,'valid'])
async def test_notification_open_validates_id_and_uses_current_inbox_workspace(user,monkeypatch,identity):
    h=await setup(user,monkeypatch);opened=AsyncMock();h['state']['messaging_workspace']={'open':opened};value=str(uuid4()) if identity=='valid' else identity
    await h['functions']['open_live_delivery'](SimpleNamespace(args=value))
    if identity=='invalid':h['select_messages'].assert_not_awaited();opened.assert_not_awaited()
    else:
        h['select_messages'].assert_awaited_once_with('inbox')
        if value:opened.assert_awaited_once_with(value)
        else:opened.assert_not_awaited()
