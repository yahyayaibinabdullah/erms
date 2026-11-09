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
async def test_review_comments_count_and_disclosure_are_local(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host)
    controls=f.draft_controls
    assert controls.count()==0 and not controls.save.enabled and not controls.review.enabled
    f.comments.value='Updated review comments';await asyncio.sleep(0)
    assert controls.count()==1 and controls.status.text==text('unsaved_change_one')
    with host:
        controls.show_review()
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        assert any(isinstance(e,ui.label) and e.text=='Updated review comments' for e in dialog.descendants())
        assert not any(isinstance(e,ui.button) and e.text==text('discard_draft') for e in dialog.descendants())
        assert not api.writes
        f.comments.value=f.saved_comments;await asyncio.sleep(0)
        assert controls.count()==0 and not controls.save.enabled
        dialog.close();await asyncio.sleep(0)
        assert not f.pending_disclosures and not controls.dialogs


@pytest.mark.asyncio
async def test_comment_save_failure_visible_in_footer_and_retry_uses_same_id(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host);f.comments.value='Keep this work'
    with host:
        f.draft_controls.show_review()
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        save=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('save_changes'))
        api.error=ApiError(409,{'code':'disposition_stale_task'});await click(save)
        assert dialog.value and f.draft_controls.feedback.text==f.feedback.text and f.feedback.text
        api.error=None;await click(save)
        assert not dialog.value and not f.draft_controls.save.enabled
        assert api.writes[0][1]['command_id']==api.writes[1][1]['command_id']
        assert all(w[1]['changes']==[] for w in api.writes)


@pytest.mark.asyncio
async def test_saving_comments_blocks_repeated_save_and_proposal_mutations(host,monkeypatch):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    entered=asyncio.Event();finish=asyncio.Event()
    class SlowApi(Api):
        async def disposition_command(self,*args,**kw):
            entered.set();await finish.wait();return await super().disposition_command(*args,**kw)
    f,api,_=await form(host,SlowApi());f.comments.value='In progress'
    with host:
        saving=asyncio.create_task(f.perform('save'));await entered.wait()
        assert f.busy and not f.draft_controls.save.enabled and not f.comments.enabled
        await f.perform('save');await f.edit(root={'root_aggregation_id':10})
        finish.set();await saving
    assert len(api.writes)==1 and f.comments.enabled and not f.draft_controls.save.enabled


@pytest.mark.asyncio
async def test_withdraw_saves_immediately_without_saving_comments(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host);f.comments.value='Still unsaved'
    with host:
        await f.withdraw(dict(id=9,version=2,editable=True,governing_root_id=10,target_aggregation_id=11,proposal_type='make_vital'))
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        assert any(isinstance(e,ui.textarea) and e.label==text('reason_optional') for e in dialog.descendants())
        await click(next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('withdraw')))
        assert not dialog.value and f.draft_controls.count()==1
        assert api.writes[0][1]['changes']==[dict(action='withdraw',proposal_id=9,expected_version=2,reason=None)]
        assert 'review_notes' not in api.writes[0][1]


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
            assert all(p['limit']==10 and p['offset']==10 and p['query']=='AGG' and p['state']=='retained' for p in member_reads)
        else:assert not member_reads
        assert saved[-1]['section']==initial_section
        before=len(api.reads);mounted[0]=False
        await f.perform('save')
        assert len(api.reads)==before and len(api.writes)==1
