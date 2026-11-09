"""Task-local proposal overlays never imply that governance changes took effect."""
import asyncio
from copy import deepcopy
import inspect
from types import SimpleNamespace
import pytest
from nicegui import ui,core
from frontend.webui.tests.test_disposition_tasks import host,Api,form,view
from frontend.webui.api_client import ApiError
from frontend.webui.disposition.messages import text


@pytest.mark.asyncio
@pytest.mark.parametrize('target_id',[10,11])
async def test_added_proposal_is_persisted_and_counts_refresh_without_saving_comments(host,monkeypatch,target_id):
    from frontend.webui.disposition import review
    from frontend.webui.disposition.screens import job_screen
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    forms=[]
    class CapturedForm(review.ReviewForm):
        def __init__(self,**kw):super().__init__(**kw);forms.append(self)
    monkeypatch.setattr(review,'ReviewForm',CapturedForm)
    workspace=view()
    workspace['job'].update(job_number='DT-2026-1',job_type='destruction',lifecycle_state='active',disposition_status=6,owner='Unit',assignee='Officer',assigned_user_id=1,owning_org_unit_id=1,membership_editable=True,owner_editable=True)
    member=dict(id=1,root_aggregation_id=10,aggregation_number='AGG-10',title='Member',redacted=False,membership_state='active',disposition_status=6,added_at='2026-10-29',proposal_count=0,held=False)
    class MembersApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/workspace'):self.reads.append((path,params));return workspace
            if path.endswith('/memberships'):
                self.reads.append((path,params))
                return {'items':[deepcopy(member),dict(member,id=2,root_aggregation_id=20,proposal_count=0)],'total':2}
            if '/proposal-targets/' in path:
                self.reads.append((path,params));selected=params.get('selected',10)
                return {'items':[dict(id=selected,aggregation_id=selected,code=f'AGG-{selected}',name='Selected aggregation',version=6)]}
            return await super().disposition_page(path,**params)
        async def disposition_command(self,*args,**kw):
            result=await super().disposition_command(*args,**kw)
            member['proposal_count']=1
            return result
    api=MembersApi();mounted=[True]
    async def noop(*args):pass
    with host:
        await job_screen(api=api,identity=5,container=host,active=lambda:mounted[0],on_error=str,bind_remote=lambda *a,**k:None,open_job=noop,open_eligibility=noop,open_resource=noop,format_timestamp=str,event_label=str,task_id=8,saved={'section':'members'})
        f=forms[0]
        table=next(e for e in host.descendants() if isinstance(e,ui.table) and any(c['name']=='proposal_count' for c in e.columns))
        f.comments.value='Unsaved observations'
        await f.edit(root=table.rows[0])
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        kind=next(e for e in dialog.descendants() if isinstance(e,ui.select) and e.label==text('proposal_type'))
        kind.value='add_to_holds';await asyncio.sleep(.02)
        if target_id!=10:
            target=next(e for e in dialog.descendants() if isinstance(e,ui.select) and e.label==text('target'))
            target.set_options({11:'AGG-11 · Descendant aggregation'},value=11);await asyncio.sleep(.02)
        holds=next(e for e in dialog.descendants() if isinstance(e,ui.select) and e.label==text('hold_ids'))
        holds.set_options({3:'LH-3 · Litigation hold'},value=[3])
        reason=next(e for e in dialog.descendants() if isinstance(e,ui.textarea) and e.label==text('reason_optional'))
        reason.value='Preserve for litigation'
        button=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('add_proposal'))
        response=next(iter(button._event_listeners.values())).handler(None)
        if inspect.isawaitable(response):await response
        await asyncio.sleep(.02)
        assert len(api.writes)==1 and not dialog.value
        change=api.writes[0][1]['changes'][0]
        assert change['target_aggregation_id']==target_id and change['proposal_type']=='add_to_holds'
        assert 'review_notes' not in api.writes[0][1] and 'overall_reason' not in api.writes[0][1]
        assert f.comments.value=='Unsaved observations' and f.has_changes()
        assert table.rows[0]['proposal_count']==1 and not table.rows[0]['held']
        assert table.rows[1]['proposal_count']==0
        member_reads=[params for path,params in api.reads if path.endswith('/memberships')]
        assert len(member_reads)==2 and all(p['limit']==25 for p in member_reads)
        navigation=next(e for e in host.descendants() if isinstance(e,ui.tabs))
        assert navigation.value=='members'
        navigation.value='current_task';await asyncio.sleep(.02)
        navigation.value='members';await asyncio.sleep(.02)
        assert table.rows[0]['proposal_count']==1 and f.comments.value=='Unsaved observations'
        await f.perform('save')
        assert len(api.writes)==2 and api.writes[-1][1]['changes']==[]
        assert api.writes[-1][1]['review_notes']=='Unsaved observations'


@pytest.mark.asyncio
async def test_add_failure_retains_input_and_exact_retry_then_saves_without_comment(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host);f.comments.value='Do not save this yet'
    with host:
        await f.edit(root={'root_aggregation_id':10})
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        kind=next(e for e in dialog.descendants() if isinstance(e,ui.select) and e.label==text('proposal_type'))
        kind.value='remove_from_job';await asyncio.sleep(.02)
        button=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('add_proposal'))
        accept=next(iter(button._event_listeners.values())).handler
        api.error=ApiError(409,{'code':'disposition_stale_task'})
        from frontend.webui.tests.test_disposition_shared_footer import click
        await click(button);await click(button)
        assert dialog.value and f.comments.value=='Do not save this yet'
        assert api.writes[0][1]['command_id']==api.writes[1][1]['command_id']
        assert f.feedback.text
        api.error=None;await click(button)
        assert not dialog.value and api.writes[-1][1]['changes'][0]['reason'] is None
        assert f.has_changes() and f.work['own_notes']['version']==4
        assert 'review_notes' not in api.writes[-1][1]


@pytest.mark.asyncio
async def test_abandoned_proposal_save_does_not_repaint_or_refresh_another_view(host,monkeypatch):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,after=await form(host);entered=asyncio.Event();finish=asyncio.Event()
    original=api.disposition_command
    async def slow(*args,**kwargs):
        entered.set();await finish.wait();return await original(*args,**kwargs)
    api.disposition_command=slow
    mounted=[True];f.active=lambda:mounted[0]
    with host:
        feedback=ui.label('')
        task=asyncio.create_task(f.save_proposals([dict(action='withdraw',proposal_id=1,expected_version=1)],feedback))
        await entered.wait();mounted[0]=False;reads=len(api.reads);finish.set()
        assert await task
    assert len(api.reads)==reads and not after and f.work['job_version']==2
