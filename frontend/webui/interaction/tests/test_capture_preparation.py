"""Run the real shared record editor while PDF preparation is deliberately blocked."""
from frontend.webui.entity_selectors import build_relationship_selector
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from nicegui import ui, background_tasks
from frontend.webui import app as webapp
from frontend.webui.api_client import ApiError
from frontend.webui.interaction.tests import test_messaging_workspace as fixture

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio
TREE = ast.parse((Path(__file__).parents[2] / 'record_capture.py').read_text())

async def setup(user, outcome='success', active=None):
    ready=asyncio.Event()
    started=asyncio.Event()
    api=SimpleNamespace(
        list=AsyncMock(return_value=[{'id':1,'name':'General','level_number':0}]),
        creation_role_options=AsyncMock(return_value=[]),
        draft_components=AsyncMock(return_value=[{'id':1,'file_name':'message.pdf'}]),
        discard_record_draft=AsyncMock(),
    )
    async def prepare():
        started.set()
        await ready.wait()
        if outcome=='error':raise ApiError(409, {'code':'message_capture_pdf_nonconforming'})
        return {'id':99,'title':'Original subject','medium':'digital','security_level_id':1}
    scope=dict(vars(webapp),api=api,
        bind_resource_security_select=lambda *a,**k:None,
        add_number_suggestion=lambda *a,**k:None,
        browse_advanced_aggregation=AsyncMock(),
        render_component_cards=lambda *a,**k:ui.label('Validated PDF').mark('prepared-pdf'),
        error_message=lambda error:'Validation failed')
    scope["bind_remote_relationship_select"] = build_relationship_selector(scope["api"], error_message=str)
    node=next(n for n in ast.walk(TREE) if isinstance(n,ast.AsyncFunctionDef) and n.name=='open_record_draft_editor')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<editor>','exec'),scope)
    async def open_editor():
        webapp.set_locale_context("en", "Asia/Dubai")
        await scope['open_record_draft_editor'](existing_capture_draft={
            'title':'Original subject','medium':'digital','security_level_id':1,
            'components':[{'title':'Original subject','file_name':'message.pdf'}]},
            capture_loader=prepare,capture_active=active)
    @ui.page('/')
    def page():
        container=ui.column()
        async def start():
            with container:await open_editor()
        background_tasks.create(start())
    await user.open('/')
    await asyncio.wait_for(started.wait(), 3)
    return ready,api

async def test_preparation_shows_editable_metadata_and_blocks_creation(user):
    ready,api=await setup(user)
    create=user.find(marker='capture-create').elements.pop()
    assert not create.enabled
    title=next(e for e in user.client.elements.values() if isinstance(e,ui.input) and e.value=='Original subject')
    title.set_value('Edited during conversion')
    await user.should_see('message.pdf')
    assert not api.draft_components.called
    ready.set()
    await user.should_see(marker='prepared-pdf')
    assert create.enabled and title.value=='Edited during conversion'
    api.draft_components.assert_awaited_once_with(99)

@pytest.mark.parametrize('abandon', [False,True])
async def test_closed_or_abandoned_capture_discards_finished_draft(user,abandon):
    current={'active':True}
    ready,api=await setup(user,active=lambda:current['active'])
    if abandon:current['active']=False
    else:
        user.find(marker='capture-cancel').click()
        await asyncio.sleep(.01)
    ready.set()
    for _ in range(30):
        if api.discard_record_draft.called:break
        await asyncio.sleep(.01)
    api.discard_record_draft.assert_awaited_once_with(99)
    assert not api.draft_components.called
    assert not any(isinstance(e,ui.dialog) and e.value for e in user.client.elements.values())

async def test_failed_validation_keeps_creation_disabled_and_allows_cancel(user):
    ready,api=await setup(user,'error')
    ready.set()
    await user.should_see(marker='capture-preparation-error')
    assert not user.find(marker='capture-create').elements.pop().enabled
    user.find(marker='capture-cancel').click()
    assert not api.draft_components.called and not api.discard_record_draft.called

async def test_dialog_opens_before_even_the_capture_manifest_returns(user):
    preview_ready=asyncio.Event()
    preview_started=asyncio.Event()
    principal={}
    async def request(method,*args,**kwargs):
        assert method=='GET'
        preview_started.set()
        await preview_ready.wait()
        return {'title':'Original subject'}
    editor=AsyncMock()
    scope=dict(vars(webapp),api=SimpleNamespace(request=request),
        auth_state={'principal':principal},principal=principal,
        state={'messaging_workspace_token':'token'},token='token',mailbox='inbox',
        select_messages=AsyncMock(),open_record_draft_editor=editor)
    scope.update(get_principal=lambda:scope['auth_state'].get('principal'),messaging_state=scope['state'])
    node=next(n for n in ast.walk(ast.parse((Path(__file__).parents[2] / 'messaging_controller.py').read_text())) if isinstance(n,ast.AsyncFunctionDef) and n.name=='capture_message')
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<capture>','exec'),scope)
    @ui.page('/')
    def page():
        ui.button('Capture',on_click=lambda:scope['capture_message']('message',None))
    await user.open('/')
    user.find('Capture').click()
    await asyncio.wait_for(preview_started.wait(),3)
    assert any(isinstance(e,ui.dialog) and e.value for e in user.client.elements.values())
    assert not editor.called
    preview_ready.set()
    for _ in range(30):
        if editor.called:break
        await asyncio.sleep(.01)
    assert editor.await_count==1
    assert callable(editor.call_args.kwargs['capture_loader'])
