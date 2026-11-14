"""Disposition controller dispatch, saved views, guards and stale ownership."""
import ast
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from nicegui import ui
from frontend.webui import app as host
from frontend.webui.api_client import ApiError
from frontend.webui.disposition import templates
pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

def build(h):
    from frontend.webui.disposition import controller
    # Screen mocks isolate controller dispatch; all real screens retain their own tests.
    h.update(disposition_state=h['state'],get_principal=lambda:h['auth_state'].get('principal'),
        get_resource=lambda:h['state'].get('resource'),enter_disposition=lambda page:h['state'].update(resource=page),
        set_discard_guard=lambda guard:h['state'].__setitem__('discard_navigation_guard',guard))
    return controller.build_disposition_controller(**{k:h[k] for k in inspect.signature(controller.build_disposition_controller).parameters})

async def setup(user,monkeypatch,page='disposition-jobs',principal=True):
    h=dict(vars(host),state={},collection_state={},aggregation_state={},auth_state={'principal':{'user':{'id':7},'can_manage_disposition':True,'can_access_disposition_tasks':True,'can_manage_disposition_templates':True} if principal is True else principal},api=object(),navigation_controller=SimpleNamespace(trail=[]),register_navigation=Mock(),current_navigation_snapshot=lambda:{'saved':True},persist_navigation_trail=Mock(),show_authenticated_view=Mock(),error_message=lambda error:'Disposition service unavailable',bind_remote_relationship_select=Mock(),format_timestamp=str,event_label=str,preview_record_components=AsyncMock(),browse_advanced_aggregation=AsyncMock(),open_related_resource=AsyncMock())
    async def guarded(action):return await action()
    h['guarded_page_navigation']=AsyncMock(side_effect=guarded)
    for key in ('jobs_screen','job_screen','tasks_screen','eligibility_screen'):
        h[key]=AsyncMock()
        from frontend.webui.disposition import controller
        monkeypatch.setattr(controller,key,h[key])
    h['templates_screen']=AsyncMock();monkeypatch.setattr(templates,'templates_screen',h['templates_screen'])
    @ui.page('/disposition-contract')
    async def screen():
        for key in ('title','subtitle','guidance'):h[key]=ui.label('')
        for key in ('table_container','search_bar','aggregation_mode_bar','add_button','add_record_button'):h[key]=ui.column()
        h['open']=build(h);await h['open'](page)
    await user.open('/disposition-contract');return h

@pytest.mark.parametrize('page,screen',[('disposition-jobs','jobs_screen'),('disposition-eligibility','eligibility_screen'),('disposition-tasks','tasks_screen'),('disposition-templates','templates_screen')])
async def test_dispatch_permissions_and_existing_controls(user,monkeypatch,page,screen):
    h=await setup(user,monkeypatch,page);h[screen].assert_awaited_once();assert h['state']['resource']==page
    assert all(not h[k].visible for k in ('search_bar','aggregation_mode_bar','add_button','add_record_button'))
    assert h['collection_state']=={'rows':[],'searched':True};assert h['aggregation_state']['aggregation_detail'] is None

@pytest.mark.parametrize('principal',[None,{'user':{'id':7}}])
async def test_denied_entry_leaves_current_view_untouched(user,monkeypatch,principal):
    h=await setup(user,monkeypatch,principal=principal);h['jobs_screen'].assert_not_awaited();h['register_navigation'].assert_not_called();assert h['state']=={}

@pytest.mark.parametrize('boundary',['page','identity','newer'])
async def test_remember_and_errors_respect_page_identity_and_token(user,monkeypatch,boundary):
    h=await setup(user,monkeypatch);callbacks=h['jobs_screen'].await_args.kwargs
    h['navigation_controller'].trail=[{'page':'disposition-jobs','state':{}}]
    callbacks['remember']({'page':2});assert h['state']['disposition_view']=={'page':2};h['persist_navigation_trail'].assert_called_once()
    if boundary=='page':h['state']['resource']='records'
    elif boundary=='identity':h['auth_state']['principal']=dict(h['auth_state']['principal'])
    else:
        with user:await h['open']('disposition-jobs')
    assert not callbacks['active']();saved=dict(h['state'].get('disposition_view') or {});callbacks['remember']({'page':99});assert h['state']['disposition_view']==saved

async def test_task_and_job_callbacks_preserve_saved_identity_and_dirty_guard(user,monkeypatch):
    h=await setup(user,monkeypatch)
    with user:await h['open']('disposition-job',42,saved={'section':'documents'},task_id=17)
    c=h['job_screen'].await_args.kwargs;assert h['state']['resource']=='disposition-task';assert h['state']['disposition_view']=={'section':'documents','task_id':17,'job_id':42}
    assert c['identity']==42 and c['task_id']==17;h['register_navigation'].assert_called_with('disposition-task',h['title'].text,entity_id=17)
    dirty=[True];c['register_dirty'](lambda:dirty[0]);guard=h['state']['discard_navigation_guard']
    with user:assert await guard(None) is False
    dirty[0]=False;assert await guard(None) is True
    await c['open_resource']('records',8);h['guarded_page_navigation'].assert_awaited_once();h['open_related_resource'].assert_awaited_once_with('records',8)
    with user:await c['open_approval_results'](42)
    assert h['job_screen'].await_args.kwargs['saved']=={'section':'documents','approval_results':True}

@pytest.mark.parametrize('outcome',['active-error','abandoned-error','cancelled'])
async def test_load_failure_only_reports_to_active_workspace(user,monkeypatch,outcome):
    h=await setup(user,monkeypatch)
    async def fail(**kwargs):
        if outcome=='abandoned-error':h['state']['resource']='records'
        if outcome=='cancelled':raise asyncio.CancelledError()
        raise ApiError(503,'Unavailable')
    h['jobs_screen'].side_effect=fail
    with user:await h['open']('disposition-jobs')
    if outcome=='active-error':await user.should_see('Disposition service unavailable')
    else:await user.should_not_see('Disposition service unavailable')
