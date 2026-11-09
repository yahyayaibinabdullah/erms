"""Removal refresh retains the source tab and bounded membership view state."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import pytest
from nicegui import ui,core
from frontend.webui.api_client import ApiError
from frontend.webui.disposition.screens import job_screen
from frontend.webui.disposition.messages import text
from frontend.webui.tests.test_disposition_tasks import host,Api,view
from frontend.webui.tests.test_disposition_bulk import click


@pytest.mark.asyncio
@pytest.mark.parametrize('task_id',[None,8])
@pytest.mark.parametrize('operation',['single','bulk','bulk_conflict'])
async def test_removal_keeps_tab_filters_sort_and_last_valid_page(host,monkeypatch,task_id,operation):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    workspace=view(actions=())
    workspace['management_roles']=[{'id':7}]
    workspace['job'].update(job_number='DT-2026-4',job_type='destruction',lifecycle_state='active',
        disposition_status=6,owner='Records Unit',assignee='Officer',assigned_user_id=1,
        owning_org_unit_id=1,membership_editable=True,owner_editable=False)
    rows=[dict(id=i,root_aggregation_id=100+i,root_version=6,version=2,
        aggregation_number=f'ROOT-{i:02}',title='Removal review',disposition_status=6,
        membership_state='active',redacted=False,added_at='2026-11-05T08:00:00Z',removed_at=None) for i in range(1,23)]
    class WorkspaceApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/workspace'):return deepcopy(workspace)
            if path.endswith('/memberships'):
                self.reads.append((path,deepcopy(params)))
                items=[r for r in rows if r['membership_state']!='removed' and params.get('query','') in r['aggregation_number']]
                items.sort(key=lambda r:r['id'],reverse=params.get('descending',False))
                start=params['offset'];return {'items':deepcopy(items[start:start+params['limit']]),'total':len(items)}
            return await super().disposition_page(path,**params)
        async def disposition_command(self,path,payload,**kwargs):
            self.writes.append((path,deepcopy(payload),kwargs))
            if operation=='bulk_conflict':raise ApiError(409,{'code':'disposition_stale_version'})
            ids=[int(path.split('/')[1])] if operation=='single' else [r['membership_id'] for r in payload['items']]
            for row in rows:
                if row['id'] in ids:row['membership_state']='removed'
            workspace['job']['version']+=1
            # The individual endpoint deliberately has no job_version field.
            return {'membership_id':ids[0],'status':2} if operation=='single' else {'job_version':workspace['job']['version'],'items':[]}
    api=WorkspaceApi();navigated=[];refreshed=[]
    async def navigate(*args):navigated.append(args)
    async def refresh(saved):
        refreshed.append(deepcopy(saved));host.clear()
        with host:await mount(saved)
    async def mount(saved):
        await job_screen(api=api,identity=5,task_id=task_id,container=host,active=lambda:True,
            on_error=str,bind_remote=lambda *a,**k:None,open_job=navigate,open_task=navigate,
            open_eligibility=navigate,open_resource=navigate,format_timestamp=str,event_label=str,
            refresh_workspace=refresh,saved=saved)
    saved={'section':'members','members':{'page':3,'size':10,'query':'ROOT-','state':'active','sort':'identity','descending':False}}
    with host:
        await mount(saved)
        table=next(e for e in host.descendants() if isinstance(e,ui.table) and hasattr(e,'bulk_selection'))
        assert [r['id'] for r in table.rows]==[21,22]
        if operation=='single':
            handler=next(e.handler for e in table._event_listeners.values() if e.type in ('remove-member','removeMember'))
            await handler(SimpleNamespace(args=21))
        else:
            selection=table.bulk_selection;selection.select_page(SimpleNamespace(args=True))
            await click(next(e for e in selection.bar.descendants() if isinstance(e,ui.button) and e.text==text('bulk_remove_selected')))
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        reason=next(e for e in dialog.descendants() if isinstance(e,ui.textarea));reason.value='Prepare separately';await asyncio.sleep(.01)
        confirm=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text!=text('cancel'))
        await click(confirm)
        if operation=='bulk_conflict':
            assert not refreshed and not navigated and dialog.value
            assert confirm.text==text('bulk_refresh_selection');await click(confirm)
    assert not navigated and len(refreshed)==1
    assert refreshed[0]['section']=='members' and refreshed[0]['job_id']==5 and refreshed[0]['task_id']==task_id
    assert refreshed[0]['members']=={k:v for k,v in saved['members'].items() if k!='state'}
    navigation=next(e for e in host.descendants() if isinstance(e,ui.tabs));assert navigation.value=='members'
    table=next(e for e in host.descendants() if isinstance(e,ui.table) and hasattr(e,'bulk_selection'))
    expected=list(range(11,21)) if operation=='bulk' else [22] if operation=='single' else [21,22]
    assert [r['id'] for r in table.rows]==expected
    assert table.pagination['page']==(2 if operation=='bulk' else 3)
    reads=[p for path,p in api.reads if path.endswith('/memberships')]
    assert all(p['limit']==10 and p['query']=='ROOT-' and p['state']=='retained' and p['sort']=='identity' and not p['descending'] for p in reads)
