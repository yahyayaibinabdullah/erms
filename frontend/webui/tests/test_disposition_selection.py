"""Real job picker controls, request bounds and lifecycle in English and Arabic."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import pytest
from nicegui import ui,core
from frontend.webui.api_client import ApiError
from frontend.webui.disposition.selection import add_aggregations_dialog
from frontend.webui.disposition.messages import text
from frontend.webui.tests.test_disposition_tasks import host
from frontend.webui.tests.test_disposition_bulk import click


class Api:
    def __init__(self):
        self.job=dict(id=5,version=2,job_number='DT-2026-4',job_type='destruction',owner='Records Unit',membership_add_role_id=99)
        self.rows=[dict(id=i,version=3,aggregation_number=f'ROOT-{i}',title='Candidate',owner='Records Unit',
            disposition_status=2,selectable=True,calculated_disposition_at=None,relationships_block_final=i==1) for i in range(1,31)]
        self.reads=[];self.writes=[];self.error=None;self.partial=False;self.wait=None
    async def disposition_page(self,path,**params):
        self.reads.append((path,deepcopy(params)))
        if self.wait:await self.wait.wait()
        assert path=='eligibility'
        rows=[r for r in self.rows if not params.get('query') or params['query'] in r['aggregation_number']]
        start=params['offset']
        return dict(items=deepcopy(rows[start:start+params['limit']]),total=len(rows),scope=deepcopy(self.job))
    async def disposition_command(self,path,payload,**kwargs):
        self.writes.append((path,deepcopy(payload),kwargs))
        if self.error:raise self.error
        result=[]
        for i,item in enumerate(payload['items']):
            success=not self.partial or i==0
            result.append({'root_id':item['root_id'],'success':success,**({} if success else {'code':'disposition_admission_blocked'})})
            if success:self.rows=[r for r in self.rows if r['id']!=item['root_id']]
        self.job['version']+=1
        return {'items':result,'job_version':self.job['version']}


async def build(host,monkeypatch,api=None,active=lambda:True):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    api=api or Api();after=[]
    async def refreshed():after.append(True)
    with host:
        dialog=await add_aggregations_dialog(api=api,job=api.job,context={'roles':[{'id':1}]},active=active,on_error=str,format_timestamp=str,after=refreshed)
    table=next(e for e in dialog.descendants() if isinstance(e,ui.table))
    return api,dialog,table.bulk_selection,after


def primary(dialog):
    return next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.icon=='playlist_add')


@pytest.mark.asyncio
async def test_scoped_dialog_paging_fixed_criteria_and_immediate_add(host,monkeypatch):
    api,dialog,selected,after=await build(host,monkeypatch)
    assert len(api.reads)==1 and api.reads[0][1]['job_id']==5
    assert api.reads[0][1]['limit']==25 and api.reads[0][1]['offset']==0
    assert not any(isinstance(e,ui.select) and e.label in (text('status'),text('owner'),text('job_type')) for e in dialog.descendants())
    assert any(isinstance(e,ui.label) and text('picker_owner_scope',type=text('destruction'),owner='Records Unit')==e.text for e in dialog.descendants())
    assert selected.page.table.rows[0]['relationship_label']==text('picker_relationship_warning')
    assert not primary(dialog).enabled
    with host:
        selected.select_page(SimpleNamespace(args=True));assert len(selected.rows)==25
        await selected.page.move(1);selected.select_page(SimpleNamespace(args=True));assert len(selected.rows)==30
        await click(primary(dialog))
    assert len(api.writes)==1 and len(api.writes[0][1]['items'])==30
    assert api.writes[0][1]['acting_role_id']==99 and api.writes[0][2]=={'reason':'','version':2}
    assert api.writes[0][0]=='jobs/5/memberships' and after==[True] and not dialog.value


@pytest.mark.asyncio
async def test_search_refresh_clear_snapshots_and_cancel_does_not_navigate_or_mutate(host,monkeypatch):
    api,dialog,selected,after=await build(host,monkeypatch)
    with host:
        selected.select_page(SimpleNamespace(args=True))
        query=next(e for e in dialog.descendants() if isinstance(e,ui.input) and e.label==text('picker_search'))
        query.value='ROOT-30'
        # Unapplied edits must not silently change page/sort criteria while
        # preserving selections made under a different filter.
        await selected.page.move(1)
        assert api.reads[-1][1]['query']=='' and len(selected.rows)==25
        await click(next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('filters')))
        assert not selected.rows and selected.page.total==1 and not primary(dialog).enabled
        assert api.reads[-1][1]['query']=='ROOT-30' and api.reads[-1][1]['offset']==0
        await click(next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('cancel')))
    assert not api.writes and not after and not dialog.value


@pytest.mark.asyncio
async def test_partial_add_stays_visible_refreshes_candidates_and_close_refreshes_job(host,monkeypatch):
    api=Api();api.partial=True
    api,dialog,selected,after=await build(host,monkeypatch,api)
    with host:
        selected.changed(SimpleNamespace(selection=selected.page.table.rows[:2]))
        await click(primary(dialog))
        assert dialog.value and not after and not selected.rows
        assert 1 not in {r['id'] for r in selected.page.table.rows} and 2 in {r['id'] for r in selected.page.table.rows}
        assert any(isinstance(e,ui.button) and e.text==text('addition_view_failures',count=1) for e in dialog.descendants())
        await click(next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('close')))
    assert after==[True] and len(api.writes)==1


@pytest.mark.asyncio
async def test_transport_retry_freezes_exact_payload_version_and_command_uuid(host,monkeypatch):
    api,dialog,selected,after=await build(host,monkeypatch)
    with host:
        selected.changed(SimpleNamespace(selection=selected.page.table.rows[:1]));api.error=ApiError(503,'Connection lost')
        await click(primary(dialog))
        assert primary(dialog).text==text('picker_retry') and dialog.value
        api.job['version']=9;api.error=None
        await click(primary(dialog))
    assert api.writes[0]==api.writes[1] and after==[True]


@pytest.mark.asyncio
async def test_definitive_conflict_requires_refresh_and_reselection(host,monkeypatch):
    api,dialog,selected,after=await build(host,monkeypatch)
    with host:
        selected.changed(SimpleNamespace(selection=selected.page.table.rows[:1]));api.error=ApiError(409,{'code':'disposition_stale_version'})
        await click(primary(dialog));assert primary(dialog).text==text('bulk_refresh_selection')
        api.error=None;api.job['version']=9
        await click(primary(dialog));assert not selected.rows and not primary(dialog).enabled and len(api.writes)==1
        selected.changed(SimpleNamespace(selection=selected.page.table.rows[:1]));await click(primary(dialog))
    assert api.writes[0][1]['command_id']!=api.writes[1][1]['command_id']
    assert api.writes[1][2]['version']==9 and after==[True]


@pytest.mark.asyncio
async def test_abandoned_page_cannot_mutate_or_render_late_candidate_response(host,monkeypatch):
    active=[True];api,dialog,selected,after=await build(host,monkeypatch,active=lambda:active[0])
    with host:
        api.wait=asyncio.Event();pending=asyncio.create_task(selected.page.move(1));await asyncio.sleep(0)
        active[0]=False;api.wait.set();await pending
        assert selected.page.table.rows[0]['id']==1
        selected.changed(SimpleNamespace(selection=selected.page.table.rows[:1]));await click(primary(dialog))
    assert not api.writes and not after


@pytest.mark.asyncio
async def test_empty_state_and_reopening_never_reuses_prior_candidates(host,monkeypatch):
    api=Api();api.rows=[]
    api,dialog,selected,after=await build(host,monkeypatch,api)
    assert selected.page.no_data.text==text('picker_empty') and not primary(dialog).enabled
    with host:await click(next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('cancel')))
    api.rows=[dict(id=90,version=4,aggregation_number='NEW',title='New candidate',owner='Unit',disposition_status=2,selectable=True)]
    _,new,selected,_=await build(host,monkeypatch,api)
    assert new!=dialog and selected.page.table.rows[0]['id']==90 and len(api.reads)==2


@pytest.mark.asyncio
@pytest.mark.parametrize('task_id',[None,8])
async def test_job_and_current_task_refresh_stay_on_active_aggregations_after_add(host,monkeypatch,task_id):
    from frontend.webui.disposition.screens import job_screen
    from frontend.webui.tests.test_disposition_tasks import Api as ReviewApi,view
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    picker=Api();workspace=view();workspace['job'].update(picker.job,lifecycle_state='active',
        assigned_user_id=1,owning_org_unit_id=1,membership_editable=True,membership_addable=True,owner_editable=False,assignee='Officer',disposition_status=6)
    workspace['management_roles']=[{'id':99}]
    class WorkspaceApi(ReviewApi):
        async def disposition_page(self,path,**params):
            if path.endswith('/workspace'):return deepcopy(workspace)
            if path=='eligibility':return await picker.disposition_page(path,**params)
            return await super().disposition_page(path,**params)
        async def disposition_command(self,*args,**kwargs):return await picker.disposition_command(*args,**kwargs)
    refreshed=[];navigated=[]
    async def refresh(saved):refreshed.append(saved)
    async def navigate(*args):navigated.append(args)
    with host:
        await job_screen(api=WorkspaceApi(),identity=5,task_id=task_id,container=host,active=lambda:True,
            on_error=str,bind_remote=lambda *a,**k:None,open_job=navigate,open_task=navigate,open_eligibility=navigate,
            open_resource=navigate,format_timestamp=str,event_label=str,refresh_workspace=refresh,saved={'section':'members'})
        buttons=[e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('add_aggregations')]
        assert len(buttons)==1
        panel=next(e for e in host.descendants() if isinstance(e,ui.tab_panel) and e._props['name']=='members')
        assert buttons[0] in list(panel.descendants())
        await click(buttons[0])
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        selected=next(e for e in dialog.descendants() if isinstance(e,ui.table)).bulk_selection
        selected.changed(SimpleNamespace(selection=selected.page.table.rows[:1]));await click(primary(dialog))
    assert not navigated and len(refreshed)==1
    assert refreshed[0]['section']=='members' and refreshed[0]['task_id']==task_id and refreshed[0]['job_id']==5
    assert refreshed[0]['members']=={'page':1,'size':25,'query':'','sort':'','descending':False}
