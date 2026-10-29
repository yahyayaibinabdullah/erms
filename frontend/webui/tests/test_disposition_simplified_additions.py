"""Review additions expose only the projected action and task-specific role."""
import asyncio
import inspect
from copy import deepcopy
from types import SimpleNamespace
import pytest
from nicegui import ui,core
from frontend.webui.tests.test_disposition_tasks import host,Api,view
from frontend.webui.disposition import screens
from frontend.webui.disposition.messages import text


async def click(button):
    result=next(e.handler for e in button._event_listeners.values() if e.type=='click')(None)
    if inspect.isawaitable(result):await result
    await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize('addable',[False,True])
async def test_review_task_add_action_is_separate_from_removal_and_protects_unsaved_work(host,monkeypatch,addable):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    workspace=view(actions=('save','propose','approve','reject'),route='simplified')
    workspace['job'].update(job_number='DT-2026-1',job_type='destruction',lifecycle_state='active',disposition_status=6,workflow_stage='records_manager_review',owner='Unit',assignee='Officer',membership_editable=False,membership_addable=addable,owner_editable=False)
    workspace['management_roles']=[{'id':7,'name':'Manager'}]
    class WorkspaceApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/workspace'):return deepcopy(workspace)
            return await super().disposition_page(path,**params)
    opened=[];notices=[]
    async def open_selection(identity):opened.append(identity)
    monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append(message))
    api=WorkspaceApi()
    with host:
        await screens.job_screen(api=api,identity=5,task_id=8,container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=open_selection,open_eligibility=open_selection,open_resource=open_selection,format_timestamp=str,event_label=str,saved={'section':'members'})
        buttons=[e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('add_aggregations')]
        assert bool(buttons)==addable
        if addable:
            await click(buttons[0]);assert opened==[5]
            editor=next(e for e in host.descendants() if isinstance(e,ui.textarea) and e.label==text('review_comments'))
            editor.value='Unsaved Manager comments'
            await click(buttons[0]);assert opened==[5] and notices[-1]==text('unsaved_warning')
        assert not api.writes


@pytest.mark.asyncio
async def test_eligibility_addition_uses_projected_claim_role_instead_of_other_global_role(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    captured={};calls=[]
    async def request(path,**params):
        calls.append(path)
        if path=='context':return {'roles':[{'id':1,'name':'Other governance role'},{'id':99,'name':'Review Manager'}]}
        if path=='jobs/5':return {'job_number':'DT-5','version':4,'membership_add_role_id':99}
        return {'items':[],'total':0}
    async def dialog(**kw):captured.update(kw)
    async def noop(*args):pass
    monkeypatch.setattr(screens,'command_dialog',dialog)
    with host:
        await screens.eligibility_screen(api=SimpleNamespace(disposition_page=request),container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=noop,open_resource=noop,format_timestamp=str,target_job=5)
        table=next(e for e in host.descendants() if isinstance(e,ui.table))
        table.selected=[dict(id=10,identity='AGG-10',selectable=True,redacted=False,version=3)]
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('add'))
        await click(button)
        assert captured['context']=={'roles':[{'id':99}]}
        assert captured['path']=='jobs/5/memberships' and captured['version']==4
        assert not captured['reason_required']
        assert calls==['context','eligibility','jobs/5']
