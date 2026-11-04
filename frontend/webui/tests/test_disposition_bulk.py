"""Real paginated controls and dialogs, in both maintained UI languages."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import inspect
import pytest
from nicegui import ui,core
from frontend.webui.api_client import ApiError
from frontend.webui.disposition.bulk import BulkSelection,bulk_dialog
from frontend.webui.disposition.messages import text
from frontend.webui.resource_relationships import PageTable
from frontend.webui.tests.test_disposition_tasks import host,Api,form,view


async def click(button):
    handler=next(event.handler for event in button._event_listeners.values() if event.type=='click')
    result=handler(None) if inspect.signature(handler).parameters else handler()
    if inspect.isawaitable(result):await result
    await asyncio.sleep(.01)


def row(identity,**extra):
    return dict(id=identity,version=2,target_label=f'ROOT-{identity}',editable=True,**extra)


@pytest.mark.asyncio
async def test_selection_pages_bound_versions_exclusions_and_clear(host,monkeypatch):
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    active=[True];requests=[];version=[2]
    async def fetch(p):
        requests.append((p.page,p.size));return {'items':[{'id':p.page,'version':version[0],'target_label':'Root','editable':True},{'id':100,'version':2,'target_label':'Restricted','editable':False}], 'total':40}
    with host:
        selected=BulkSelection(eligible=lambda r:r['editable'],label=lambda r:r['target_label'],active=lambda:active[0],actions=[])
        page=PageTable(columns=[{'name':'target_label','field':'target_label','label':'Target'}],fetch=fetch,active=lambda:active[0],on_error=str,empty='empty',selection='multiple',on_loaded=selected.loaded)
        selected.attach(page);await page.load()
        selected.select_page(SimpleNamespace(args=True));assert set(selected.rows)=={1}
        await page.move(1);selected.select_page(SimpleNamespace(args=True));assert set(selected.rows)=={1,2}
        version[0]=9;await page.load();assert selected.rows[2]['version']==2
        assert all(size==25 for _,size in requests) and len(requests)==3
        selected.clear();assert not page.table.selected and not selected.rows
        selected.changed(SimpleNamespace(selection=[row(i) for i in range(110)]));assert len(selected.rows)==100
        active[0]=False;selected.select_page(SimpleNamespace(args=False));assert len(selected.rows)==100


@pytest.mark.asyncio
@pytest.mark.parametrize('operation',['withdraw','propose','remove'])
async def test_confirmation_required_reason_and_one_call_per_selection(host,monkeypatch,operation):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());calls=[]
    async def execute(rows,reason,feedback):calls.append((rows,reason));return True
    async def refresh():pass
    with host:
        dialog=await bulk_dialog(operation=operation,rows=[row(1),row(2)],active=lambda:True,execute=execute,on_error=str,refresh=refresh)
        controls=list(dialog.descendants());reason=next(e for e in controls if isinstance(e,ui.textarea));button=next(e for e in controls if isinstance(e,ui.button) and e.text==text('bulk_'+operation+'_confirm',count=2))
        assert button.enabled==(operation!='remove')
        if operation=='remove':reason.value='Separate preparation';await asyncio.sleep(.01)
        await click(button)
        assert len(calls)==1 and len(calls[0][0])==2 and not dialog.value


@pytest.mark.asyncio
async def test_failed_selection_refresh_and_uncertain_retry_are_distinct(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());calls=[];refreshed=[];code=[409]
    async def execute(rows,reason,feedback):calls.append((rows,reason));raise ApiError(code[0],{'code':'disposition_stale_proposal'})
    async def refresh():refreshed.append(True)
    with host:
        dialog=await bulk_dialog(operation='withdraw',rows=[row(1)],active=lambda:True,execute=execute,on_error=lambda error:'Stale selection',refresh=refresh)
        button=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text!=text('cancel'))
        await click(button);assert button.text==text('bulk_refresh_selection') and dialog.value
        await click(button);assert refreshed and not dialog.value and len(calls)==1
        code[0]=503
        dialog=await bulk_dialog(operation='withdraw',rows=[row(1)],active=lambda:True,execute=execute,on_error=lambda error:'Connection interrupted',refresh=refresh)
        button=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text!=text('cancel'))
        await click(button);await click(button)
        assert button.text==text('bulk_withdraw_confirm',count=1) and len(calls)==3
        assert any(isinstance(e,ui.label) and text('bulk_uncertain') in e.text for e in dialog.descendants())


class ProposalApi(Api):
    def __init__(self):super().__init__();self.rows=[]
    async def disposition_page(self,path,**params):
        if path.endswith('/proposals'):
            self.reads.append((path,params));return {'items':deepcopy(self.rows),'total':len(self.rows)}
        return await super().disposition_page(path,**params)


def proposal(identity,**extra):
    return dict(id=identity,version=3,redacted=False,proposal_type='make_vital',proposal_state='active',review_round=1,
      in_current_membership=True,target_aggregation_id=identity,current_values={'aggregation_number':f'ROOT-{identity}','title':'Root'},
      proposed_values={},proposed_at='2026-11-04T08:00:00Z',proposer_stage='officer_preparation',**extra)


@pytest.mark.asyncio
async def test_bulk_withdraw_uses_one_request_preserves_comments_and_retries_identity(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    api=ProposalApi();api.rows=[proposal(11),proposal(12)]
    f,_,_=await form(host,api);f.comments.value='My unsaved comments'
    with host:
        selection=f.proposals.table.bulk_selection;selection.select_page(SimpleNamespace(args=True))
        assert len(selection.rows)==2
        dialog=await f.bulk_proposals('withdraw',selection.selected())
        button=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text!=text('cancel'))
        api.error=ApiError(503,'Temporary connection failure');await click(button)
        api.error=None;await click(button)
        assert len(api.writes)==2 and api.writes[0][1]['command_id']==api.writes[1][1]['command_id']
        payload=api.writes[-1][1];assert len(payload['changes'])==2 and 'review_notes' not in payload
        assert all(item['action']=='withdraw' and item['reason'] is None for item in payload['changes'])
        assert f.comments.value=='My unsaved comments' and f.has_changes() and not selection.rows


@pytest.mark.asyncio
async def test_bulk_proposed_removal_is_one_proposal_per_root_without_membership_command(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    f,api,_=await form(host)
    with host:
        dialog=await f.bulk_proposals('propose',[dict(id=41,root_aggregation_id=10,root_version=4),dict(id=42,root_aggregation_id=20,root_version=6)])
        button=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text!=text('cancel'));await click(button)
        assert len(api.writes)==1 and api.writes[0][0]=='tasks/8/review-work'
        changes=api.writes[0][1]['changes'];assert [item['target_aggregation_id'] for item in changes]==[10,20]
        assert all(item['proposal_type']=='remove_from_job' and item['reason'] is None for item in changes)


@pytest.mark.asyncio
async def test_selection_refresh_preserves_original_comment_version_and_unsaved_text(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    f,api,_=await form(host);f.comments.value='Unsaved local explanation'
    original=deepcopy(f.work['own_notes']);read=api.disposition_page
    async def latest(path,**params):
        result=await read(path,**params)
        if path.endswith('/review-work'):result.update(job_version=20,task_version=30,own_notes={'version':99,'review_notes':'Concurrent change'})
        return result
    api.disposition_page=latest
    with host:await f.refresh_bulk()
    assert f.comments.value=='Unsaved local explanation' and f.work['own_notes']==original
    assert f.work['job_version']==20 and f.work['task_version']==30 and f.has_changes()


@pytest.mark.asyncio
async def test_abandoned_confirmation_does_not_start_mutation(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());calls=[];active=[True]
    async def execute(*args):calls.append(True);return True
    async def refresh():pass
    with host:
        dialog=await bulk_dialog(operation='withdraw',rows=[row(1)],active=lambda:active[0],execute=execute,on_error=str,refresh=refresh)
        button=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text!=text('cancel'))
        active[0]=False;await click(button);assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize('direct',[True,False])
async def test_real_member_table_routes_bulk_action_and_clears_filter_selection(host,monkeypatch,direct):
    from frontend.webui.disposition.screens import job_screen
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    workspace=view();workspace['management_roles']=[{'id':7,'name':'Officer'}]
    workspace['job'].update(job_number='DT-2026-4',job_type='destruction',lifecycle_state='active',disposition_status=6,owner='Records Unit',assignee='Officer',assigned_user_id=1,owning_org_unit_id=1,membership_editable=direct,owner_editable=False)
    members=[dict(id=i,root_aggregation_id=100+i,root_version=6,version=2,aggregation_number=f'ROOT-{i}',title='Root',
      disposition_status=6,membership_state='active',redacted=False,added_at='2026-11-04T00:00:00Z',removed_at=None,removal_proposed=i==2) for i in (1,2)]
    class WorkspaceApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/workspace'):return deepcopy(workspace)
            if path.endswith('/memberships'):
                self.reads.append((path,params));return {'items':deepcopy(members),'total':len(members)}
            return await super().disposition_page(path,**params)
    api=WorkspaceApi()
    async def noop(*args):pass
    with host:
        await job_screen(api=api,identity=5,container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**kw:None,open_job=noop,open_eligibility=noop,open_resource=noop,format_timestamp=str,event_label=str,task_id=8)
        navigation=next(e for e in host.descendants() if isinstance(e,ui.tabs));navigation.value='members';await asyncio.sleep(.03)
        table=next(e for e in host.descendants() if isinstance(e,ui.table) and hasattr(e,'bulk_selection') and any(c['name']=='identity' for c in e.columns))
        selection=table.bulk_selection;selection.select_page(SimpleNamespace(args=True))
        assert len(selection.rows)==(2 if direct else 1)
        query=next(e for e in host.descendants() if isinstance(e,ui.input) and e.label==text('search_aggregations'))
        query.value='Changed filter';await asyncio.sleep(.02);assert not selection.rows
        selection.select_page(SimpleNamespace(args=True))
        action=next(e for e in selection.bar.descendants() if isinstance(e,ui.button) and e.text==text('bulk_remove_selected' if direct else 'bulk_propose_selected'))
        await click(action)
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        reason=next(e for e in dialog.descendants() if isinstance(e,ui.textarea));reason.value='Separate preparation';await asyncio.sleep(.01)
        confirm=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text!=text('cancel'));await click(confirm)
        assert len(api.writes)==1
        path,payload,options=api.writes[0]
        if direct:
            assert path=='jobs/5/memberships/remove' and len(payload['items'])==2
            assert payload['items'][0]=={'membership_id':1,'expected_version':2,'root_version':6}
            assert options['reason']=='Separate preparation'
        else:
            assert path=='tasks/8/review-work' and len(payload['changes'])==1
            assert payload['changes'][0]['target_aggregation_id']==101
