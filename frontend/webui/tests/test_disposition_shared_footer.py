"""Shared footer: local draft review, explicit atomic Save, scope and busy guards."""
import asyncio
from copy import deepcopy
import inspect
import pytest
from nicegui import ui,core
from frontend.webui.api_client import ApiError
from frontend.webui.disposition.messages import text
from frontend.webui.tests.test_disposition_tasks import host,Api,form,view


async def click(button):
    result=next(iter(button._event_listeners.values())).handler(None)
    if inspect.isawaitable(result):await result
    await asyncio.sleep(.02)


@pytest.mark.asyncio
async def test_review_discard_and_comment_count_are_local(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host)
    controls=f.draft_controls
    assert controls.count()==0 and not controls.save.enabled and not controls.review.enabled
    assert controls.status.text==text('all_changes_saved')
    f.comments.value='Updated review comments'
    await asyncio.sleep(0)
    assert controls.count()==1 and controls.status.text==text('unsaved_change_one')
    draft=dict(action='create',proposal_type='add_to_holds',governing_root_id=10,target_aggregation_id=10,target_version=6,proposed_values={'hold_ids':[3]},reason='Legal review')
    with host:
        f.queued(draft,{'target':'AGG-10','hold_ids':'LH-3 · Litigation hold'})
        assert controls.status.text==text('unsaved_changes_count',count=2)
        reads=list(api.reads)
        controls.show_review()
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        assert any(isinstance(e,ui.label) and e.text=='Updated review comments' for e in dialog.descendants())
        discard=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('discard_draft'))
        await click(discard)
        assert not f.pending and controls.count()==1 and not api.writes and reads==api.reads
        f.comments.value=f.saved_comments;await asyncio.sleep(0)
        assert controls.count()==0 and not controls.save.enabled
        assert any(isinstance(e,ui.label) and e.text==text('no_unsaved_changes') for e in dialog.descendants())
        dialog.close();await asyncio.sleep(0)
        assert not f.pending_disclosures and not controls.dialogs


@pytest.mark.asyncio
async def test_save_failure_is_visible_in_footer_and_dialog_and_retry_closes_only_on_success(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host)
    with host:
        f.queued(dict(action='create',proposal_type='make_vital',governing_root_id=10,target_aggregation_id=10,target_version=6,proposed_values={}))
        await f.show_proposals(dict(identity='AGG-10',root_aggregation_id=10))
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        discard=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('discard_draft'))
        assert discard.enabled
        save=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('save_changes'))
        api.error=ApiError(409,{'code':'disposition_stale_task'})
        await click(save)
        assert dialog.value and f.pending and f.draft_controls.feedback.text==f.feedback.text
        assert f.draft_controls.feedback.visible and f.feedback.text
        assert f.draft_controls.dialogs[0][2].text==f.feedback.text
        api.error=None
        await click(save)
        assert not dialog.value and not f.pending and not f.draft_controls.save.enabled
        assert api.writes[0][1]['command_id']==api.writes[1][1]['command_id']
        assert all(p=='tasks/8/review-work' for p,_,_ in api.writes)


@pytest.mark.asyncio
async def test_saving_disables_all_draft_mutations_and_rejects_repeated_save(host,monkeypatch):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    entered=asyncio.Event();finish=asyncio.Event()
    class SlowApi(Api):
        async def disposition_command(self,*args,**kw):
            entered.set();await finish.wait();return await super().disposition_command(*args,**kw)
    f,api,_=await form(host,SlowApi())
    with host:
        draft=dict(action='create',proposal_type='make_vital',governing_root_id=10,target_aggregation_id=10,target_version=6,proposed_values={})
        f.queued(draft)
        saving=asyncio.create_task(f.perform('save'));await entered.wait()
        assert f.busy and not f.draft_controls.save.enabled and not f.draft_controls.review.enabled
        assert not f.comments.enabled and all(not b.enabled for b in f.draft_buttons)
        f.discard_pending(draft);f.queued(dict(draft));await f.perform('save')
        assert len(f.pending)==1
        finish.set();await saving
    assert len(api.writes)==1 and not f.pending and f.comments.enabled
    assert not f.draft_controls.save.enabled


@pytest.mark.asyncio
async def test_withdrawal_review_identifies_the_saved_proposal_and_discard_reverses_only_local_change(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host)
    with host:
        await f.withdraw(dict(id=9,version=2,editable=True,governing_root_id=10,target_aggregation_id=11,target_label='AGG-11 · Descendant',proposal_type='make_vital'))
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        await click(next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('withdraw')))
        f.draft_controls.show_review()
        review=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        labels=[e.text for e in review.descendants() if isinstance(e,ui.label)]
        assert text('target')+' · AGG-11 · Descendant' in labels
        assert text('proposal_type')+' · '+text('make_vital') in labels
        await click(next(e for e in review.descendants() if isinstance(e,ui.button) and e.text==text('discard_draft')))
        assert not f.pending and f.draft_controls.count()==0 and not api.writes


@pytest.mark.asyncio
@pytest.mark.parametrize('actions',[(),('claim',),('release',)])
async def test_read_only_or_unclaimed_task_has_no_shared_save_footer(host,actions):
    f,_,_=await form(host,actions=actions)
    assert f.draft_controls is None
    assert not any(isinstance(e,ui.page_sticky) for e in host.descendants())


@pytest.mark.asyncio
@pytest.mark.parametrize('initial_section',['members','documents'])
async def test_footer_is_shared_across_tabs_and_save_preserves_member_filters_page_and_section(host,monkeypatch,initial_section):
    from frontend.webui.disposition import review
    from frontend.webui.disposition.screens import job_screen
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    forms=[]
    class CapturedForm(review.ReviewForm):
        def __init__(self,**kw):super().__init__(**kw);forms.append(self)
    monkeypatch.setattr(review,'ReviewForm',CapturedForm)
    workspace=view();workspace['job'].update(job_number='DT-5',job_type='destruction',lifecycle_state='active',disposition_status=6,owner='Unit',assignee='Officer',membership_editable=False,owner_editable=False)
    member=dict(id=21,root_aggregation_id=10,aggregation_number='AGG-10',title='Member',redacted=False,membership_state='active',disposition_status=6,added_at='2026-10-30',proposal_count=0)
    class WorkspaceApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/workspace'):return workspace
            if path.endswith('/documents'):
                self.reads.append((path,params));return {'items':[],'total':0,'correction_roles':[]}
            if path.endswith('/artifact-destination'):return {'warning':None,'destination':None,'changed':False}
            if path.endswith('/memberships'):
                self.reads.append((path,params));return {'items':[deepcopy(member)],'total':25}
            return await super().disposition_page(path,**params)
    api=WorkspaceApi();saved=[];mounted=[True]
    async def noop(*a):pass
    with host:
        await job_screen(api=api,identity=5,container=host,active=lambda:mounted[0],on_error=str,bind_remote=lambda *a,**k:None,open_job=noop,open_eligibility=noop,open_resource=noop,format_timestamp=str,event_label=str,task_id=8,saved={'section':initial_section,'members':{'page':2,'size':10,'query':'AGG','state':'active'}},remember=saved.append)
        f=forms[0];nav=next(e for e in host.descendants() if isinstance(e,ui.tabs))
        assert not any(f.draft_controls.sticky in list(p.descendants()) for p in host.descendants() if isinstance(p,ui.tab_panel))
        f.comments.value='Save from this tab';await asyncio.sleep(0)
        await click(f.draft_controls.save)
        assert nav.value==initial_section and len(api.writes)==1
        assert api.writes[0][0]=='tasks/8/review-work' and not f.draft_controls.save.enabled
        member_reads=[params for path,params in api.reads if path.endswith('/memberships')]
        if initial_section=='members':
            assert len(member_reads)==2
            assert all(p['limit']==10 and p['offset']==10 and p['query']=='AGG' and p['state']=='active' for p in member_reads)
        else:assert not member_reads
        assert saved[-1]['section']==initial_section
        before=len(api.reads);mounted[0]=False
        await f.perform('save')
        assert len(api.reads)==before and len(api.writes)==1
