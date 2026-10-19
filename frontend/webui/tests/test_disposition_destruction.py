"""Explicit EN/AR confirmation, exact retry and abandoned progress responses."""
import asyncio
from types import SimpleNamespace
import pytest
from nicegui import ui,core
from frontend.webui.tests.test_disposition_tasks import host,Api
from frontend.webui.tests.test_disposition_external import click
from frontend.webui.disposition.destruction import controls
from frontend.webui.disposition.messages import text
from frontend.webui.api_client import ApiError


def form(host,*,progress=None,alive=lambda:True,released=True):
    api=Api();saved=[]
    async def after(value):saved.append(value)
    f=SimpleNamespace(api=api,view={'destruction':{'released':released,'progress':progress}},job={'id':7,'version':5,'workflow_stage':'digital_destruction'},task={'id':9,'version':3},actions={'destroy_digital'} if released and not progress else set(),retry={},busy=False,host=host,alive=alive,after=after)
    with host:
        f.role=ui.select({2:'Current Manager'},value=2)
        f.error=lambda error:ui.notify(str(error),type='negative')
        controls(f)
    return f,saved


@pytest.mark.asyncio
async def test_confirmation_is_unchecked_and_button_disabled_until_explicit_choice(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**kw:notices.append(kw))
    f,saved=form(host)
    check=next(e for e in host.descendants() if isinstance(e,ui.checkbox));button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('destroy_digital'))
    assert not check.value and button._props['disable']
    with host:
        await click(button);assert not f.api.writes
        check.value=True;assert not button._props['disable']
        await click(button)
    assert f.api.writes[0][0]=='tasks/9/digital-destruction' and f.api.writes[0][1]['confirmed'] is True
    assert f.api.writes[0][1]['task_version']==3 and saved and notices[-1]['type']=='positive'


@pytest.mark.asyncio
async def test_failed_request_preserves_confirmation_and_exact_retry(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    f,saved=form(host);check=next(e for e in host.descendants() if isinstance(e,ui.checkbox));button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('destroy_digital'))
    with host:
        check.value=True;f.api.error=ApiError(409,{'code':'disposition_digital_scope_changed'});await click(button)
        assert check.value and not saved
        f.api.error=None;await click(button)
    assert f.api.writes[0]==f.api.writes[1] and saved


@pytest.mark.asyncio
async def test_progress_is_server_fresh_and_abandoned_response_does_not_reload(host,monkeypatch):
    callbacks=[]
    class Timer:
        def __init__(self,interval,callback,active=True):self.callback=callback;self.active=active;callbacks.append(self)
        def deactivate(self):self.active=False
    monkeypatch.setattr(ui,'timer',Timer)
    progress={'state':'running','overall_completed_units':1,'overall_total_units':3,'queued_units':1,'running_units':1,'failed_units':0,'last_error_code':None}
    state={'alive':True};f,saved=form(host,progress=progress,alive=lambda:state['alive'])
    reads=[]
    async def read(path,**kw):reads.append(path);state['alive']=False;return {**progress,'state':'succeeded','overall_completed_units':3}
    f.api.disposition_page=read
    await callbacks[0].callback()
    assert reads==['jobs/7/destruction-progress'] and not saved and not callbacks[0].active


def test_closed_release_shows_progress_without_execution_control(host):
    f,_=form(host,released=False)
    assert not any(isinstance(e,ui.checkbox) for e in host.descendants())
    assert any(isinstance(e,ui.label) and e.text==text('disposition_digital_release_pending') for e in host.descendants())


@pytest.mark.asyncio
async def test_destroyed_members_with_removed_names_render_retained_actions(host):
    from frontend.webui.disposition.screens import job_screen
    async def request(path,**params):
        if path=='jobs/1/workspace':return {'job':{'id':1,'job_number':'JOB','job_type':'destruction','review_route':'standard','current_review_round':1,'lifecycle_state':'active','disposition_status':6,'workflow_stage':'digital_destruction','owner':'Owner','assignee':'Officer','assigned_user_id':1,'owning_org_unit_id':1,'version':2,'membership_editable':False,'owner_editable':False},'task':None,'actions':[],'roles':[],'management_roles':[]}
        if path.endswith('/documents'):return {'items':[],'total':0,'correction_roles':[]}
        if path.endswith('/artifact-destination'):return {'ready':False,'changed':False,'destination':None,'previous_destination':None,'warning':'disposition_destination_unset','token':'x'*64}
        if path.endswith('/memberships'):return {'items':[{'id':7,'root_aggregation_id':91,'root_version':2,'version':2,'aggregation_number':None,'title':None,'destroyed':True,'disposition_status':10,'membership_state':'completed_history','redacted':False,'added_at':'2026-01-01T00:00:00Z','removed_at':None}],'total':1}
        return {'items':[],'total':0}
    with host:await job_screen(api=SimpleNamespace(disposition_page=request),identity=1,container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=lambda _:None,open_eligibility=lambda _:None,open_resource=lambda *a:None,format_timestamp=str,event_label=str)
    table=next(e for e in host.descendants() if isinstance(e,ui.table) and any(r.get('root_aggregation_id')==91 for r in e.rows))
    assert table.rows[0]['identity']==text('retained_unit',id=91) and not table.rows[0]['can_remove']
    assert 'retained-unit' in table.slots['body-cell-actions'].template
    assert '!props.row.destroyed' in table.slots['body-cell-actions'].template
