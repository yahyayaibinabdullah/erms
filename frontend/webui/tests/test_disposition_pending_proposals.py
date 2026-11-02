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
async def test_legal_hold_draft_updates_member_before_save_and_survives_tab_entry(host,monkeypatch,target_id):
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
        await f.edit(root=table.rows[0])
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        kind=next(e for e in dialog.descendants() if isinstance(e,ui.select) and e.label==text('proposal_type'))
        kind.value='add_to_holds';await asyncio.sleep(.02)
        if target_id!=10:
            target=next(e for e in dialog.descendants() if isinstance(e,ui.select) and e.label==text('target'))
            target.set_options({11:'AGG-11 · Descendant aggregation'},value=11);await asyncio.sleep(.02)
        holds=next(e for e in dialog.descendants() if isinstance(e,ui.select) and e.label==text('hold_ids'))
        holds.set_options({3:'LH-3 · Litigation hold'},value=[3])
        reason=next(e for e in dialog.descendants() if isinstance(e,ui.textarea) and e.label==text('reason'))
        reason.value='Preserve for litigation'
        button=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('add_draft_proposal'))
        response=next(iter(button._event_listeners.values())).handler(None)
        if inspect.isawaitable(response):await response
        await asyncio.sleep(.02)
        assert len(f.pending)==1
        assert f.pending[0]['target_aggregation_id']==target_id
        assert table.rows[0]['proposal_count']==1 and table.rows[1]['proposal_count']==0
        assert table.rows[0]['pending_proposals_label']==text('pending_changes')+' · 1'
        assert not table.rows[0]['held'] and not table.rows[0]['blocked'] and not api.writes
        # No extra reads just to show the pending count; the server still has zero.
        assert sum(path.endswith('/memberships') for path,_ in api.reads)==1
        show=next(e.handler for e in table._event_listeners.values() if e.type in ('show-proposals','showProposals'))
        await show(SimpleNamespace(args=1))
        disclosure=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        labels=[e.text for e in disclosure.descendants() if isinstance(e,ui.label)]
        assert text('pending_changes') in labels and text('add_to_holds') in labels
        assert text('hold_ids')+' · LH-3 · Litigation hold' in labels
        assert text('reason')+' · Preserve for litigation' in labels
        disclosure.close();await asyncio.sleep(0)
        assert not f.pending_disclosures
        navigation=next(e for e in host.descendants() if isinstance(e,ui.tabs))
        navigation.value='current_task';await asyncio.sleep(.02)
        navigation.value='members';await asyncio.sleep(.02)
        assert table.rows[0]['saved_proposal_count']==0 and table.rows[0]['proposal_count']==1
        # Repeated overlays never add the same draft twice.
        f.render_pending();f.render_pending()
        assert table.rows[0]['proposal_count']==1
        draft=f.pending[0]
        f.discard_pending(draft)
        assert table.rows[0]['proposal_count']==0 and not table.rows[0]['pending_proposals_label']
        f.queued(draft,{'hold_ids':'LH-3 · Litigation hold'})
        api.error=ApiError(409,{'code':'disposition_stale_task'})
        await f.perform('save')
        assert table.rows[0]['proposal_count']==1 and table.rows[0]['pending_proposals_label']
        api.error=None
        await f.perform('save')
        assert table.rows[0]['saved_proposal_count']==table.rows[0]['proposal_count']==1
        assert not table.rows[0]['pending_proposals_label'] and not table.rows[0]['held']
        assert not f.pending and not f.pending_roots and not f.pending_meta
        assert len(api.writes)==2
        assert api.writes[-1][1]['changes']==[draft]
        # Disposed workspaces cannot be repainted by a local draft notification.
        mounted[0]=False
        f.queued(dict(draft,governing_root_id=20))
        assert table.rows[1]['proposal_count']==0


@pytest.mark.asyncio
async def test_revisions_withdrawals_and_redacted_or_historical_members(host,monkeypatch):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host)
    rows=[dict(id=1,root_aggregation_id=10,proposal_count=2,membership_state='active'),
          dict(id=2,root_aggregation_id=20,proposal_count=1,membership_state='active'),
          dict(id=3,root_aggregation_id=10,proposal_count=None,redacted=True,membership_state='active'),
          dict(id=4,root_aggregation_id=10,proposal_count=2,membership_state='removed')]
    with host:
        f.queued(dict(action='revise',proposal_id=9,proposed_values={'hold_ids':[3]}),root_id=10)
        f.decorate_member_proposals(rows)
        assert rows[0]['proposal_count']==2 and rows[0]['pending_proposals_label']
        f.queued(dict(action='withdraw',proposal_id=9),root_id=10)
        f.decorate_member_proposals(rows)
        assert len(f.pending)==len(f.pending_roots)==len(f.pending_meta)==1
        assert rows[0]['proposal_count']==1 and rows[1]['proposal_count']==1
        assert rows[2]['proposal_count'] is None and not rows[2]['pending_proposals_label']
        assert rows[3]['proposal_count']==2 and not rows[3]['pending_proposals_label']
        await f.show_proposals(dict(identity='AGG-10',root_aggregation_id=10))
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        assert any(isinstance(e,ui.label) and e.text==text('withdraw') for e in dialog.descendants())
        f.discard_pending(f.pending[0]);f.decorate_member_proposals(rows)
        assert rows[0]['proposal_count']==2 and not rows[0]['pending_proposals_label']
        assert not any(isinstance(e,ui.label) and e.text==text('pending_changes') for e in dialog.descendants())
    assert not api.writes
