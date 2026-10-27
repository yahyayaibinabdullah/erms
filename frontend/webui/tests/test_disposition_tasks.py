"""Real NiceGUI task forms: exact Save payloads, optimistic failures and bounds."""
import asyncio
from copy import deepcopy
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from nicegui import ui,core
from frontend.webui.api_client import ApiError
from frontend.webui.locale_services import set_locale_context, current_locale_context
from frontend.webui.i18n_catalogue import set_active_messages,clear_active_messages
from frontend.webui.disposition.review import ReviewForm,workflow_panel
from frontend.webui.disposition.tasks import tasks_screen
from frontend.webui.disposition.messages import text

ROOT=Path(__file__).resolve().parents[3]


@pytest.fixture(params=['en','ar'])
def host(request,monkeypatch):
    h=ui.column()
    source=json.loads((ROOT/'frontend/webui/i18n/messages.en.json').read_text()) if request.param=='en' else json.loads((ROOT/'frontend/webui/i18n/messages.ar.generated.json').read_text())['items']
    catalogue={r['message_key']:r.get('default_text',r.get('translated_text')) for r in source}
    with h:set_active_messages(catalogue);set_locale_context(request.param,'Asia/Dubai')
    yield h
    with h:set_active_messages({});clear_active_messages(h.client.id)


def view(actions=('save','propose','submit'),route='standard'):
    return dict(job={'id':5,'version':2,'review_route':route,'workflow_stage':'officer_preparation','current_review_round':0},task={'id':8,'version':3,'task_type':'preparation','destination_user_id':1,'direct_assignee':'Assigned officer','role_queue':None,'claimant':None},roles=[{'id':7,'name':'Officer'}],management_roles=[],actions=list(actions))


class Api:
    def __init__(self):self.reads=[];self.writes=[];self.error=None
    async def disposition_page(self,path,**params):
        self.reads.append((path,params))
        if path.endswith('/review-work'):return dict(job_id=5,job_version=2,task_version=3,review_round=1,overall_reason='Previously saved reason',own_notes={'version':4,'review_notes':'Earlier notes'},submission_reason=None)
        if '/proposal-targets/' in path:return {'items':[dict(id=10,aggregation_id=10,code='ROOT-10',name='Governing unit',version=6)]}
        return {'items':[],'total':0}
    async def disposition_approval_summary(self,task_id,**params):
        self.reads.append(('approval-summary',deepcopy(params)))
        return {'job_version':2,'task_version':3,'membership_token':'a'*64,'proposals_token':'b'*64,
                'proposal_count':2,'proposal_counts':{'remove_aggregation_relationship':2},'next_step':'request','empty_return_stage':'officer_correction'}
    async def disposition_command(self,path,payload,**kw):
        self.writes.append((path,deepcopy(payload),kw))
        if self.error:raise self.error
        return {'job_version':3,'task_version':4,'note_version':5}


async def form(host,api=None,**kw):
    api=api or Api();after=[]
    async def refresh(result):after.append(result)
    with host:
        f=ReviewForm(api=api,workspace=view(**kw),active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=refresh,format_timestamp=str,open_resource=None)
        await f.load()
    return f,api,after


@pytest.mark.asyncio
async def test_explicit_save_persists_partial_reason_and_own_note_without_advancing(host,monkeypatch):
    notices=[];monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append((message,kw)))
    f,api,after=await form(host)
    f.comments.value='Saved personal observations'
    f.queued({'action':'create','governing_root_id':10,'target_aggregation_id':10,'target_version':6,'proposal_type':'make_vital','proposed_values':{}})
    await f.perform('save')
    assert len(api.writes)==1 and api.writes[0][0]=='tasks/8/review-work'
    payload=api.writes[0][1]
    assert payload['overall_reason']=='Saved personal observations' and payload['note_version']==4 and payload['review_notes']=='Saved personal observations'
    assert payload['task_version']==3 and api.writes[0][2]['version']==2
    assert not f.dirty() and after and notices[-1][1]['type']=='positive'
    assert {path for path,_ in api.reads}=={'tasks/8/review-work','jobs/5/proposals'}
    assert all(params['limit']==25 and params['offset']==0 for path,params in api.reads if path.startswith('jobs/'))


@pytest.mark.asyncio
async def test_stale_save_retains_draft_and_exact_retry_id_then_role_change_uses_new_id(host,monkeypatch):
    notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**kw:notices.append(kw))
    f,api,after=await form(host);f.comments.value='Still unsaved';api.error=ApiError(409,{'code':'disposition_stale_task'})
    await f.perform('save');await f.perform('save')
    assert f.dirty() and not after and notices[-1]['type']=='negative'
    assert api.writes[0][1]['command_id']==api.writes[1][1]['command_id']
    f.acting_role_id=9  # Refreshed eligible-role projection changes internal attribution.
    await f.perform('save')
    assert api.writes[-1][1]['command_id']!=api.writes[0][1]['command_id']


@pytest.mark.asyncio
async def test_submit_saves_visible_changes_first_and_uses_new_versions(host,monkeypatch):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,after=await form(host);f.comments.value='Ready for the next review'
    await f.perform('submit')
    assert [x[0] for x in api.writes]==['tasks/8/review-work','tasks/8/submit-review']
    assert api.writes[1][1]['task_version']==4 and api.writes[1][2]['version']==3
    assert api.writes[1][1]['overall_reason']=='Ready for the next review'


@pytest.mark.asyncio
async def test_blank_submission_warns_without_any_request(host,monkeypatch):
    notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**k:notices.append(k))
    f,api,_=await form(host);f.comments.value='  '
    with host:await f.perform('submit')
    assert api.writes==[] and notices[-1]['type']=='warning'


@pytest.mark.asyncio
async def test_queue_and_other_claimant_have_no_edit_or_decision_controls(host):
    f,api,_=await form(host,actions=('claim',))
    assert f.comments is None
    labels=[e.text for e in f.host.descendants() if isinstance(e,ui.button)]
    assert text('claim') in labels and not any(text(k) in labels for k in ('save','submit','approve','reject'))


@pytest.mark.asyncio
async def test_proposal_dialog_creates_draft_until_save_and_hydrates_only_target(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host)
    with host:
        await f.edit(root={'root_aggregation_id':10})
        button=next(e for e in reversed(list(host.descendants())) if isinstance(e,ui.button) and e.text==text('continue'))
        callback=next(iter(button._event_listeners.values())).handler
        response=callback(None)
        if inspect.isawaitable(response):await response
        await asyncio.sleep(0)
    assert not api.writes and len(f.pending)==1 and f.pending[0]['target_version']==6
    assert f.pending[0]['proposal_type']=='make_vital'
    assert api.reads[-1]==('tasks/8/proposal-targets/aggregations',{'root_id':10,'acting_role_id':7,'selected':10})


@pytest.mark.asyncio
async def test_inbox_requests_real_offsets_and_keeps_server_claimant(host):
    calls=[];opened=[]
    async def request(path,**params):
        calls.append((path,params));return {'items':[dict(id=8,job_id=5,job_number='DEST-5',job_type='destruction',owner='Unit',task_type='preparation',workflow_stage='officer_preparation',task_state='claimed',claimant='Another reviewer',date_created='2026-10-19T00:00:00Z',age_seconds=172800,priority=0,root_count=1000,removal_required=True)],'total':100}
    async def open_task(*args):opened.append(args)
    with host:
        await tasks_screen(api=SimpleNamespace(disposition_page=request),container=host,active=lambda:True,on_error=str,open_task=open_task,format_timestamp=str,saved={'page':2,'size':10})
    table=next(e for e in host.descendants() if isinstance(e,ui.table))
    assert table.rows[0]['claimant']=='Another reviewer' and table.rows[0]['age_days']==2
    assert calls[0][1]['limit']==10 and calls[0][1]['offset']==10
    assert 'erms-page-table' in table.classes
    assert all(c['headerStyle']=='vertical-align: top' for c in table.columns)
    assert all(c['align']==('right' if text('my_tasks')=='مهامي' else 'left') for c in table.columns)


@pytest.mark.asyncio
async def test_task_filters_default_collapsed_remember_choice_without_refetch(host):
    api=Api();choices=[];current={'active':True}
    async def opened(*args):pass
    with host:
        await tasks_screen(api=api,container=host,active=lambda:current['active'],on_error=str,
                           open_task=opened,format_timestamp=str,remember_filters=choices.append)
    disclosure=next(e for e in host.descendants() if isinstance(e,ui.expansion))
    assert disclosure.value is False
    disclosure.open();await asyncio.sleep(0)
    assert choices==[True]
    disclosure.close();await asyncio.sleep(0)
    assert choices==[True,False]
    assert len(api.reads)==1
    current['active']=False
    disclosure.open();await asyncio.sleep(0)
    assert choices==[True,False]


@pytest.mark.asyncio
async def test_task_filters_restore_expanded_choice(host):
    api=Api()
    async def opened(*args):pass
    with host:
        await tasks_screen(api=api,container=host,active=lambda:True,on_error=str,
                           open_task=opened,format_timestamp=str,filters_expanded=True)
    assert next(e for e in host.descendants() if isinstance(e,ui.expansion)).value is True


@pytest.mark.parametrize('route,skipped',[('standard',0),('simplified',2),('records_manager_only',3)])
def test_native_workflow_tracker_saved_route(host,route,skipped):
    from frontend.webui.disposition.process import process_stages
    job=view(route=route)['job']
    if route=='records_manager_only':job['workflow_stage']='manager_preparation'
    steps=process_stages(job)
    assert sum(s['state']=='skipped' for s in steps)==skipped
    assert next(s['key'] for s in steps if s['state']=='tracker_current')==job['workflow_stage']
    with host:workflow_panel(job)
    assert not any(isinstance(e,ui.mermaid) for e in host.descendants())
    assert len([e for e in host.descendants() if isinstance(e,ui.badge)])==len(steps)+1  # round badge plus stage states
    assert steps[0]=={'key':'job_created','state':'completed'}


def test_tracker_correction_skips_physical_completion_and_termination():
    from frontend.webui.disposition.process import process_stages
    job={'review_route':'standard','workflow_stage':'officer_correction','lifecycle_state':'active','file_administrator_skipped':True}
    steps={s['key']:s['state'] for s in process_stages(job)}
    assert steps['officer_correction']=='tracker_current'
    assert steps['file_administrator_review']=='skipped'
    assert steps['unit_manager_review']=='tracker_upcoming'
    assert 'physical_destruction' not in steps
    job['workflow_stage']='physical_destruction'
    assert next(s for s in process_stages(job) if s['key']=='physical_destruction')['state']=='tracker_current'
    job['lifecycle_state']='terminated'
    steps={s['key']:s['state'] for s in process_stages(job)}
    assert steps['physical_destruction']=='terminated' and steps['completed']=='tracker_upcoming'
    job.update(workflow_stage='completed',lifecycle_state='completed')
    steps={s['key']:s['state'] for s in process_stages(job,physical={'physical_required':True,'confirmation':{'id':1}})}
    assert 'digital_destruction' not in steps and 'certificate_generation' not in steps
    assert steps['completed']=='completed' and steps['physical_destruction']=='completed'
    assert steps['file_administrator_review']=='skipped'
    steps=process_stages(job,destruction={'progress':{'state':'succeeded'}})
    assert next(s for s in steps if s['key']=='digital_destruction')['state']=='completed'


@pytest.mark.asyncio
async def test_history_is_lazy_retains_controls_and_refreshes_on_reopen(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    f,api,_=await form(host)
    section=next(e for e in f.host.descendants() if isinstance(e,ui.expansion) and e.text==text('review_comments'))
    assert not any(path.endswith('/review-notes') for path,_ in api.reads)
    with host:
        section.value=True;await asyncio.sleep(0);await asyncio.sleep(0)
        page=f.notes
        section.value=False;section.value=True;await asyncio.sleep(0);await asyncio.sleep(0)
    assert f.notes is page and sum(path.endswith('/review-notes') for path,_ in api.reads)==2


@pytest.mark.asyncio
async def test_committed_approval_report_failure_warns_and_refreshes_without_reexecution(host,monkeypatch):
    from nicegui.elements.dialog import Dialog
    notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**k:notices.append(k))
    async def confirmed():return True
    monkeypatch.setattr(Dialog,'__await__',lambda self:confirmed().__await__())
    api=Api();original=api.disposition_page
    async def request(path,**params):
        if path.endswith('/approval-preview'):return {'job_version':2,'task_version':3,'membership_token':'a'*64,'proposals_token':'b'*64}
        return await original(path,**params)
    api.disposition_page=request;f,api,after=await form(host,api,actions=('save','propose','approve'),route='records_manager_only')
    f.work['own_notes']['review_notes']=f.comments.value
    f.work['overall_reason']=f.comments.value
    api.error=ApiError(503,{'code':'disposition_execution_report_pending','approval_committed':True,'round_id':9})
    with host:await f.perform('approve')
    assert [x[0] for x in api.writes]==['tasks/8/approve-proposals']
    assert len(after)==1 and after[0]['approval_committed'] and notices[-1]['type']=='warning'


@pytest.mark.asyncio
async def test_native_save_button_dispatches_the_save_action(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host);f.comments.value='Verify native Save dispatch'
    with host:
        button=next(e for e in f.host.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        next(iter(button._event_listeners.values())).handler(None)
        await asyncio.sleep(0);await asyncio.sleep(0);await asyncio.sleep(0)
    assert api.writes and api.writes[0][0]=='tasks/8/review-work'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,proposed',[
    ('make_vital',{}),('remove_from_job',{}),
    ('blocking_security',{'security_level_id':3}),
    ('add_to_holds',{'hold_ids':[3]}),
    ('create_aggregation_relationship',{'direction':'outgoing','related_aggregation_id':3,'relationship_type_id':4}),
    ('remove_aggregation_relationship',{'relationship_id':99}),
    ('remove_record_relationship',{'relationship_id':99}),
    ('local_retention_override',{'current_period_years':5,'intermediate_period_years':1,'final_disposition':'destruction','instructions':None}),
])
async def test_revision_editors_preserve_identity_and_hydrate_selected_relationship(host,monkeypatch,kind,proposed):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    api=Api();original=api.disposition_page;link_reads=[]
    async def read(path,**params):
        if '/removal-candidates/' in path:return await request('GET',path,params)
        if '/review-candidates/' in path:return {'items':[{'id':params.get('selected',3),'code':'REF','name':'Selected reference'}]}
        return await original(path,**params)
    async def request(method,path,params):
        link_reads.append((path,params))
        rows=[{'id':99,'selectable':True,'already_proposed':False,'existing_proposal_id':None,'label':'Selected relationship','related':{'redacted':False,'number':'R-99','title':'Outside first page'}}] if params.get('selected_id') else []
        return {'items':rows,'total':len(rows)}
    api.disposition_page=read;api.request=request
    f,api,_=await form(host,api)
    existing=dict(id=12,version=4,editable=True,governing_root_id=10,target_aggregation_id=10,target_record_id=10 if kind=='remove_record_relationship' else None,proposal_type=kind,proposed_values=proposed,reason='Retain review reason',current_values={})
    with host:
        await f.edit(existing=existing)
        kind_control=next(e for e in host.descendants() if isinstance(e,ui.select) and e.label==text('proposal_type'))
        assert not kind_control.enabled
        targets=[e for e in host.descendants() if isinstance(e,ui.select) and e.label==text('target')]
        assert all(not e.enabled for e in targets)
        button=next(e for e in reversed(list(host.descendants())) if isinstance(e,ui.button) and e.text==text('continue'))
        response=next(iter(button._event_listeners.values())).handler(None)
        if inspect.isawaitable(response):await response
        await asyncio.sleep(0)
    assert not api.writes and f.pending[0]['action']=='revise'
    assert f.pending[0]['proposal_id']==12 and f.pending[0]['proposed_values']==proposed
    if 'relationship_id' in proposed:
        with host:
            assert all(params['language_tag']==current_locale_context()[0] for _,params in link_reads)
        assert link_reads[-1][1]['selected_id']==99


@pytest.mark.asyncio
async def test_proposal_security_and_hold_selectors_use_standard_search(host):
    calls=[];api=Api()
    with host:
        form=ReviewForm(api=api,workspace=view(),active=lambda:True,on_error=str,bind_remote=lambda *a,**k:calls.append((a,k)),after=lambda x:None,format_timestamp=str,open_resource=lambda *a:None)
        security=form.remote('security_levels','security_level_id')
        holds=form.remote('holds','hold_ids',multiple=True,selected=[{'id':11,'code':'H-11','name':'Hold'}])
        assert calls[0][0][1]=='security-levels' and calls[0][1]['min_query_length']==0
        assert calls[1][0][1]=='holds' and calls[1][1]['min_query_length']==2
        assert 'shield' in security.slots['prepend'].template and 'gavel' in holds.slots['prepend'].template
        assert holds.value==[11] and holds.options[11]=='H-11 · Hold'
        assert any(isinstance(e,ui.label) and e.text==text('selector_hint') for e in host.descendants())
        await calls[0][1]['page_loader']('')
        assert api.reads[-1]==('tasks/8/review-candidates/security_levels',{'acting_role_id':7,'query':''})
        await calls[1][1]['page_loader']('Ho')
        assert api.reads[-1][1]['query']=='Ho'


@pytest.mark.asyncio
async def test_related_aggregation_browser_revalidates_selection(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    class BrowserApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/review-candidates/aggregations'):
                self.reads.append((path,params));return {'items':[{'id':22,'code':'A22','name':'Related'}]}
            return await super().disposition_page(path,**params)
    api=BrowserApi();browsed=[]
    async def browse(control,**kw):
        browsed.append(control)
        await kw['on_select']({'id':22},lambda:True)
    with host:
        f=ReviewForm(api=api,workspace=view(),active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=lambda x:None,format_timestamp=str,open_resource=None,browse_resource=browse)
        await f.edit(root={'root_aggregation_id':10})
        kind=next(e for e in host.descendants() if isinstance(e,ui.select) and e.label==text('proposal_type'))
        kind.value='create_aggregation_relationship'
        await asyncio.sleep(.02)
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('browse'))
        next(iter(button._event_listeners.values())).handler(None)
        await asyncio.sleep(.02)
        assert browsed[0].value==22 and browsed[0].options[22]=='A22 · Related'
        assert api.reads[-1][1]=={'acting_role_id':7,'selected':22}


@pytest.mark.asyncio
async def test_relationship_direction_order_and_selected_label(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    class DirectionApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/review-candidates/relationship_types'):
                self.reads.append((path,params))
                return {'items':[{'id':22,'code':'REL','name':'Reverse' if params.get('direction')=='incoming' else 'Forward'}]}
            return await super().disposition_page(path,**params)
    api=DirectionApi()
    with host:
        f=ReviewForm(api=api,workspace=view(),active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=lambda x:None,format_timestamp=str,open_resource=None)
        await f.edit(root={'root_aggregation_id':10})
        kind=next(e for e in host.descendants() if isinstance(e,ui.select) and e.label==text('proposal_type'))
        kind.value='create_aggregation_relationship'
        await asyncio.sleep(.02)
        selects=[e for e in host.descendants() if isinstance(e,ui.select)]
        labels=[e.label for e in selects]
        assert labels.index(text('related_aggregation_id'))<labels.index(text('direction'))<labels.index(text('relationship_type_id'))
        relation=next(e for e in selects if e.label==text('relationship_type_id'))
        relation.set_options({22:'REL · Forward'},value=22)
        direction=next(e for e in selects if e.label==text('direction'))
        for value,label in [('incoming','Reverse'),('outgoing','Forward')]:
            direction.value=value
            await asyncio.sleep(.02)
            relation=next(e for e in host.descendants() if isinstance(e,ui.select) and e.label==text('relationship_type_id'))
            assert relation.value==22 and relation.options[22]=='REL · '+label
            assert api.reads[-1][1]['direction']==value


@pytest.mark.parametrize('stage,expected',[
    ('officer_preparation',set()),('manager_preparation',set()),
    ('officer_correction',set()),('manager_correction',set()),
    ('file_administrator_review',set()),('unit_manager_review',set()),
    ('records_manager_review',set()),('external_approval_pending',{'external'}),
    ('physical_destruction',{'physical'}),('digital_destruction',{'digital'}),
    ('certificate_generation',{'completion'}),('completed',{'completion'}),
])
@pytest.mark.asyncio
async def test_current_stage_excludes_other_stage_controls(host,monkeypatch,stage,expected):
    from frontend.webui.disposition import external,physical,destruction,completion,email
    seen=[]
    for name,module,method in [('external',external,'request_controls'),('physical',physical,'controls'),('completion',completion,'controls')]:
        monkeypatch.setattr(module,method,lambda form,host=None,n=name:seen.append(n))
    monkeypatch.setattr(destruction,'controls',lambda form:seen.append('digital') if form.job['workflow_stage']=='digital_destruction' else None)
    monkeypatch.setattr(email,'controls',lambda form,host=None:None)
    workspace=view(actions=());workspace.update(task=None,roles=[])
    workspace['job']['workflow_stage']=stage
    with host:
        history=ui.column();documents=ui.column()
        f=ReviewForm(api=Api(),workspace=workspace,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=lambda x:None,format_timestamp=str,open_resource=None,history_host=history,documents_host=documents)
        await f.load()
    assert set(seen)==expected
    assert not list(e for e in f.host.descendants() if isinstance(e,ui.expansion))
    assert len([e for e in history.descendants() if isinstance(e,ui.expansion)])==4
    assert f.api.reads==[]


@pytest.mark.asyncio
async def test_workspace_tabs_lazy_refresh_and_preserve_unsaved_work(host,monkeypatch):
    from frontend.webui.disposition.screens import job_screen
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    workspace=view()
    workspace['job'].update(job_number='DT-2026-1',job_type='destruction',lifecycle_state='active',disposition_status=6,owner='Unit',assignee='Officer',assigned_user_id=1,owning_org_unit_id=1,membership_editable=True,owner_editable=True)
    class WorkspaceApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/workspace'):
                self.reads.append((path,params));return workspace
            return await super().disposition_page(path,**params)
    api=WorkspaceApi();dirty=[];mounted=[True]
    async def noop(*args):pass
    with host:
        await job_screen(api=api,identity=5,container=host,active=lambda:mounted[0],on_error=str,bind_remote=lambda *a,**k:None,open_job=noop,open_eligibility=noop,open_resource=noop,format_timestamp=str,event_label=str,register_dirty=dirty.append,task_id=8)
        navigation=next(e for e in host.descendants() if isinstance(e,ui.tabs))
        assert navigation.value=='current_task'
        assert not any(p.endswith(('/memberships','/history','/documents','/templates')) for p,_ in api.reads)
        notes=next(e for e in host.descendants() if isinstance(e,ui.textarea) and e.label==text('review_comments'))
        notes.value='Unsaved observations'
        for section in ('members','current_task','members','current_task'):
            navigation.value=section
            await asyncio.sleep(.02)
        assert notes.value=='Unsaved observations' and dirty[0]()
        assert sum(p.endswith('/memberships') for p,_ in api.reads)==2
        assert sum(p.endswith('/history') for p,_ in api.reads)==0
        assert not any(p.endswith('/templates') for p,_ in api.reads)
        before=len(api.reads);mounted[0]=False;navigation.value='members'
        await asyncio.sleep(.02)
        assert len(api.reads)==before


@pytest.mark.parametrize('task_id',[None,8])
@pytest.mark.asyncio
async def test_job_and_task_details_have_distinct_focus(host,monkeypatch,task_id):
    from frontend.webui.disposition.screens import job_screen
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    workspace=view()
    workspace['job'].update(job_number='DT-2026-1',job_type='destruction',lifecycle_state='active',disposition_status=6,owner='Unit',assignee='Officer',assigned_user_id=1,owning_org_unit_id=1,membership_editable=True,owner_editable=True)
    workspace['management_roles']=[{'id':7,'name':'Officer','profile_code':'INFO_GOV_OFFICER'}]
    class WorkspaceApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/workspace'):
                self.reads.append((path,params));return workspace
            return await super().disposition_page(path,**params)
    api=WorkspaceApi();opened=[]
    async def open_job(identity):opened.append(('job',identity))
    async def open_task(identity,task):opened.append(('task',identity,task))
    with host:
        await job_screen(api=api,identity=5,container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=open_job,open_task=open_task,open_eligibility=open_job,open_resource=open_job,format_timestamp=str,event_label=str,task_id=task_id)
        navigation=next(e for e in host.descendants() if isinstance(e,ui.tabs))
        tabs=[e._props['name'] for e in host.descendants() if isinstance(e,ui.tab)]
        assert navigation.value==('current_task' if task_id else 'workspace_details')
        headings=[e.text for e in host.descendants() if isinstance(e,ui.label) and 'text-2xl' in e.classes]
        assert headings==[text('stage')+' · '+text(workspace['job']['workflow_stage'])] if task_id else headings==[text('workspace_details')]
        assert 'templates' not in tabs
        assert ('history' in tabs)==(task_id is None)
        assert any(p.endswith('/review-work') for p,_ in api.reads)==(task_id is not None)
        assert any(isinstance(e,ui.textarea) and e.label==text('review_comments') for e in host.descendants())==(task_id is not None)
        progress=[e for e in host.descendants() if isinstance(e,ui.expansion) and e._props.get('label')==text('workflow')]
        assert bool(progress)==(task_id is None)
        if progress:assert progress[0].value
        refresh=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('refresh'))
        result=next(iter(refresh._event_listeners.values())).handler(None)
        if inspect.isawaitable(result):await result
        await asyncio.sleep(.02)
        assert opened==[('task',5,8)] if task_id else opened==[('job',5)]


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['remove_aggregation_relationship','remove_record_relationship'])
async def test_multiple_relationship_removals_queue_and_save_as_one_batch(host,monkeypatch,kind):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    api=Api()
    links=[{'id':i,'label':'related to','related':{'redacted':False,'number':f'LINK-{i}','title':f'Related {i}'}} for i in (101,102)]
    original=api.disposition_page
    async def request(path,**params):
        if '/removal-candidates/' in path:return {'items':deepcopy(links),'total':2}
        return await original(path,**params)
    api.disposition_page=request
    f,api,_=await form(host,api)
    with host:
        await f.edit(root={'root_aggregation_id':10})
        control=next(e for e in host.descendants() if isinstance(e,ui.select) and e.label==text('proposal_type'))
        control.value=kind
        await asyncio.sleep(.05)
        if kind=='remove_record_relationship':
            target_control=next(e for e in reversed(list(host.descendants())) if isinstance(e,ui.select) and e.label==text('target'))
            target_control.set_options({10:'Record 10'},value=10)
            await asyncio.sleep(.05)
        table=next(e for e in reversed(list(host.descendants())) if isinstance(e,ui.table) and e.selection=='multiple')
        table.selected=deepcopy(links)
        reason=next(e for e in reversed(list(host.descendants())) if isinstance(e,ui.textarea) and e.label==text('reason'))
        reason.value='Remove both outside links'
        button=next(e for e in reversed(list(host.descendants())) if isinstance(e,ui.button) and e.text==text('continue'))
        result=next(iter(button._event_listeners.values())).handler(None)
        if inspect.isawaitable(result):await result
        await asyncio.sleep(0)
    assert len(f.pending)==2 and not api.writes
    assert [x['proposed_values'] for x in f.pending]==[{'relationship_id':101},{'relationship_id':102}]
    assert all(x['proposal_type']==kind and x['reason']=='Remove both outside links' for x in f.pending)
    await f.perform('save')
    assert len(api.writes)==1 and len(api.writes[0][1]['changes'])==2


@pytest.mark.asyncio
@pytest.mark.parametrize('unclaimed',[False,True])
async def test_task_return_restores_members_page_and_marks_opened_row(host,monkeypatch,unclaimed):
    from frontend.webui.disposition.screens import job_screen
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    workspace=view(actions=('claim',) if unclaimed else ('save','propose','submit'));workspace['job'].update(job_number='DT-2026-1',job_type='destruction',lifecycle_state='active',disposition_status=6,owner='Unit',assignee='Officer',membership_editable=True)
    class ReturnApi(Api):
        async def disposition_page(self,path,**params):
            if path.endswith('/workspace'):return workspace
            if path.endswith('/memberships'):
                self.reads.append((path,params))
                return {'items':[dict(id=i,root_aggregation_id=i,redacted=False,aggregation_number=str(i),title='Review root',membership_state='active',disposition_status=6,medium='digital',added_at='2026-10-23') for i in (51,52)],'total':100}
            return await super().disposition_page(path,**params)
    api=ReturnApi();remembered=[];opened=[]
    async def open_resource(*args):opened.append(args)
    saved={'task_id':8,'job_id':5,'section':'members','opened_member':52,'members':{'page':3,'size':25,'sort':'identity','descending':False,'query':'Review','state':'active'}}
    with host:
        await job_screen(api=api,identity=5,container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=open_resource,open_eligibility=open_resource,open_resource=open_resource,format_timestamp=str,event_label=str,task_id=8,saved=saved,remember=remembered.append)
        assert next(e for e in host.descendants() if isinstance(e,ui.tabs)).value=='members'
        request=next(params for path,params in api.reads if path.endswith('/memberships'))
        assert request==dict(limit=25,offset=50,query='Review',state='active',sort='identity',descending=False)
        table=next(e for e in host.descendants() if isinstance(e,ui.table) and any(r.get('last_viewed') for r in e.rows))
        assert [r['id'] for r in table.rows if r['last_viewed']]==[52]
        assert all(r['needs_claim']==unclaimed and r['can_propose']!=unclaimed for r in table.rows)
        assert ':disable="props.row.needs_claim"' in table.slots['body-cell-actions'].template
        handler=next(e.handler for e in table._event_listeners.values() if e.type in ('open-root','openRoot'))
        result=handler(SimpleNamespace(args=51))
        if inspect.isawaitable(result):await result
        await asyncio.sleep(0)
    assert remembered[-1]['opened_member']==51 and remembered[-1]['members']['page']==3
    assert opened==[('aggregation',51)]


@pytest.mark.asyncio
async def test_legacy_notes_and_reason_share_one_clean_editor_without_auto_writes(host):
    f,api,_=await form(host)
    assert f.comments.value=='Previously saved reason\n\nEarlier notes'
    assert not f.has_changes() and not api.writes
    assert len([e for e in host.descendants() if isinstance(e,ui.textarea)])==1
    assert f.comments.label==text('review_comments')


@pytest.mark.asyncio
@pytest.mark.parametrize('route',['standard','simplified','records_manager_only'])
async def test_empty_comments_can_be_saved_as_a_draft(host,monkeypatch,route):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host,route=route)
    f.comments.value=''
    await f.perform('save')
    assert api.writes[0][1]['review_notes']==api.writes[0][1]['overall_reason']==''


@pytest.mark.asyncio
@pytest.mark.parametrize('action,route',[('submit','standard'),('submit','simplified'),('approve','records_manager_only'),('reject','standard')])
async def test_required_review_comments_stop_action_before_any_save(host,monkeypatch,action,route):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host,actions=('save',action),route=route)
    f.comments.value='  '
    await f.perform(action)
    assert not api.writes and f.feedback.text==text('review_comments_required')


@pytest.mark.asyncio
async def test_routine_review_allows_blank_comments_and_return_uses_same_editor(host,monkeypatch):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host,actions=('save','complete_review','reject'))
    f.comments.value=''
    await f.perform('complete_review')
    assert api.writes[-1][1]['decision_reason']==''
    f.comments.value='Correct the relationship proposals'
    await f.perform('reject')
    assert api.writes[-1][1]['decision_reason']=='Correct the relationship proposals'
    assert api.writes[-2][1]['review_notes']=='Correct the relationship proposals'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure',[False,True])
async def test_successful_submission_returns_to_tasks_but_failure_keeps_form(host,monkeypatch,failure):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,after=await form(host)
    destinations=[]
    async def return_to_tasks():destinations.append('my_tasks')
    f.on_submitted=return_to_tasks
    f.comments.value='Ready for review'
    original=api.disposition_command
    async def command(path,payload,**kw):
        if failure and path.endswith('/submit-review'):
            raise ApiError(409,{'code':'disposition_stale_task'})
        return await original(path,payload,**kw)
    api.disposition_command=command
    with host:await f.perform('submit')
    assert destinations==([] if failure else ['my_tasks'])
    assert f.comments.value=='Ready for review'
    if failure:
        assert all(result.get('_saved_work') for result in after)
    else:
        assert not after


@pytest.mark.asyncio
@pytest.mark.parametrize('recipient_kind',['person','role_queue'])
async def test_submission_toast_identifies_shared_queue_before_navigation(host,monkeypatch,recipient_kind):
    events=[]
    monkeypatch.setattr(ui,'notify',lambda message,**kw:events.append(message))
    f,api,_=await form(host)
    original=api.disposition_command
    async def command(path,payload,**kw):
        result=await original(path,payload,**kw)
        return {**result,'next_recipients':[{'kind':recipient_kind,'name':'Review team'}]}
    async def navigate():events.append('navigated')
    api.disposition_command=command;f.on_submitted=navigate
    f.comments.value='Ready'
    with host:
        await f.perform('submit')
        assert events[-2]==text('submitted_to',recipients=text('next_role_queue',name='Review team') if recipient_kind=='role_queue' else 'Review team')
    assert events[-1]=='navigated'


@pytest.mark.asyncio
@pytest.mark.parametrize('action',['claim','release'])
async def test_claim_needs_no_reason_but_release_still_does(host,monkeypatch,action):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    f,api,after=await form(host,actions=(action,))
    with host:
        await f.queue_action(action)
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        reasons=[e for e in dialog.descendants() if isinstance(e,ui.textarea)]
        assert bool(reasons)==(action=='release')
        button=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        handler=next(e for e in button._event_listeners.values() if e.type=='click').handler
        result=handler(None)
        if inspect.isawaitable(result):await result
        await asyncio.sleep(0)
    if action=='claim':
        assert api.writes[-1][0]=='tasks/8/claim' and api.writes[-1][2]['reason']==''
        assert after
    else:
        assert not api.writes and not after


@pytest.mark.asyncio
async def test_unclaimed_task_explains_claim_and_keeps_readable_redacted_target(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    api=Api();original=api.disposition_page
    async def request(path,**params):
        if path.endswith('/proposals'):
            return {'items':[{'id':1,'version':1,'redacted':True,'target_summary':{'number':'1141/DEMO/011/2026','title':'Readable target'}},{'id':2,'version':1,'redacted':True}],'total':2}
        return await original(path,**params)
    api.disposition_page=request
    f,api,_=await form(host,api,actions=('claim',))
    assert any(isinstance(e,ui.label) and e.text==text('claim_before_proposals') for e in host.descendants())
    assert f.proposals.table.rows[0]['target_label']=='1141/DEMO/011/2026 · Readable target'
    assert f.proposals.table.rows[0]['target_notice']==text('restricted_proposal_details')
    assert f.proposals.table.rows[1]['target_label']==text('restricted_resource')
    assert all(not r['editable'] for r in f.proposals.table.rows)
    with host:
        await f.queue_action('claim')
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        assert any(isinstance(e,ui.label) and e.text==text('claim_explanation') for e in dialog.descendants())
        assert not any(isinstance(e,ui.textarea) for e in dialog.descendants())


@pytest.mark.asyncio
async def test_partial_proposal_keeps_metadata_and_read_only_details(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    api=Api();original=api.disposition_page
    metadata=dict(id=1,version=1,redacted=True,partial=True,target_summary={'number':'ROOT-1','title':'Readable target'},proposal_type='remove_aggregation_relationship',proposal_state='active',proposer_name='Original reviewer',proposer_role_name='Records Officer',proposer_stage='officer_preparation',review_round=1,proposed_at='2026-10-26',last_revised_at='2026-10-26',editor_name='Editor')
    async def request(path,**params):
        if path.endswith('/proposals'):return {'items':[deepcopy(metadata)],'total':1}
        return await original(path,**params)
    api.disposition_page=request
    f,api,_=await form(host,api)
    row=f.proposals.table.rows[0]
    assert row['details_available'] and not row['editable']
    assert row['type_label']==text('remove_aggregation_relationship') and row['proposer_name']=='Original reviewer'
    with host:
        await f.details(row)
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        labels=[e.text for e in dialog.descendants() if isinstance(e,ui.label)]
        assert any('Original reviewer' in label for label in labels)
        assert any('ROOT-1' in label for label in labels)
        assert text('restricted_text') in labels
        assert not any(isinstance(e,ui.button) and e.text in (text('revise'),text('withdraw')) for e in dialog.descendants())
    assert not api.writes


@pytest.mark.asyncio
async def test_blockers_dialog_shows_partial_relationships_pagination_and_inline_errors(host,monkeypatch):
    from frontend.webui.disposition.screens import blockers_dialog
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    calls=[]
    async def request(path,**params):
        calls.append(params)
        if len(calls)==1:raise ApiError(403,{'code':'insufficient_privilege'})
        return {'items':[],'relationships_block_final':True,'relationships':[dict(source={'number':'ROOT-1','title':'Readable root'},target=None,relationship_label='مرتبط بـ' if current_locale_context()[0]=='ar' else 'related to',blocks_final=True,redacted=True)],'has_more':len(calls)==2}
    with host:
        await blockers_dialog(api=SimpleNamespace(disposition_page=request),root={'id':1,'aggregation_number':'ROOT-1','title':'Readable root'},active=lambda:True,on_error=lambda e:'Cannot load blockers',open_resource=None)
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        assert any(isinstance(e,ui.label) and e.text=='Cannot load blockers' for e in dialog.descendants())
        retry=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('blockers_retry'))
        handler=next(e.handler for e in retry._event_listeners.values() if e.type=='click')
        for _ in range(2):
            result=handler(None)
            if inspect.isawaitable(result):await result
            await asyncio.sleep(0)
        labels=[e.text for e in dialog.descendants() if isinstance(e,ui.label)]
        assert text('blocker_source')+' ·' in labels and 'ROOT-1' in labels and 'Readable root' in labels
        assert text('blocker_target')+' ·' in labels and text('restricted_resource') in labels
        number=next(e for e in dialog.descendants() if isinstance(e,ui.label) and e.text=='ROOT-1')
        assert number._props['dir']=='ltr'
        assert text('final_blocked') in labels and text('blockers_empty_all') not in labels
        assert [x['offset'] for x in calls]==[0,0,1]
        assert all(x['limit']==25 for x in calls)


@pytest.mark.asyncio
async def test_removal_picker_disables_saved_queued_and_restricted_rows_and_links_details(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    api=Api();original=api.disposition_page;reads=[]
    rows=[dict(id=i,label='related to',related={'redacted':i in (103,104),'number':f'REL-{i}','title':'Related'},already_proposed=i in (102,103),existing_proposal_id=12 if i==102 else None,selectable=i==101) for i in (101,102,103,104)]
    async def request(path,**params):
        reads.append((path,params))
        if '/removal-candidates/' in path:return {'items':deepcopy(rows),'total':4}
        if path.endswith('/proposals') and params.get('proposal_id'):return {'items':[{'id':12,'partial':True,'redacted':True}],'total':1}
        return await original(path,**params)
    api.disposition_page=request;f,api,_=await form(host,api)
    shown=[]
    async def details(row):shown.append(row)
    monkeypatch.setattr(f,'details',details)
    with host:
        await f.edit(root={'root_aggregation_id':10})
        kind=next(e for e in reversed(list(host.descendants())) if isinstance(e,ui.select) and e.label==text('proposal_type'))
        kind.value='remove_aggregation_relationship';await asyncio.sleep(.05)
        table=next(e for e in reversed(list(host.descendants())) if isinstance(e,ui.table) and e.selection=='multiple')
        assert [r['id'] for r in table.rows if r['selectable']]==[101]
        assert text('removal_already_proposed') in table.rows[1]['selection_label']
        assert text('removal_access_required') in table.rows[2]['selection_label']
        assert table.rows[3]['target_label']==text('restricted_resource')
        assert ':disable="!props.row.selectable"' in table.slots['body-selection'].template
        handler=next(e.handler for e in table._event_listeners.values() if e.type in ('select-available','selectAvailable'))
        handler(SimpleNamespace(args=True));assert [r['id'] for r in table.selected]==[101]
        handler(SimpleNamespace(args=False));assert not table.selected
        existing=next(e.handler for e in table._event_listeners.values() if e.type in ('existing-proposal','existingProposal'))
        result=existing(SimpleNamespace(args=12))
        if inspect.isawaitable(result):await result
        await asyncio.sleep(0)
        assert shown==[{'id':12,'partial':True,'redacted':True}]
        button=next(e for e in reversed(list(host.descendants())) if isinstance(e,ui.button) and e.text==text('continue'))
        accept=next(e.handler for e in button._event_listeners.values() if e.type=='click')
        table.selected=deepcopy(table.rows)
        result=accept(None)
        if inspect.isawaitable(result):await result
        await asyncio.sleep(0);assert not f.pending
        table.selected=[table.rows[0]]
        result=accept(None)
        if inspect.isawaitable(result):await result
        await asyncio.sleep(0)
        assert len(f.pending)==1 and f.pending[0]['proposed_values']=={'relationship_id':101}
    assert not api.writes
    assert any(params.get('proposal_id')==12 and params['limit']==1 for _,params in reads)
    assert all(params['limit']==25 and params['offset']==0 for path,params in reads if '/removal-candidates/' in path)


@pytest.mark.asyncio
@pytest.mark.parametrize('recipient_kind', ['person', 'role_queue', 'none'])
async def test_completion_toast_names_actual_next_recipient_without_extra_lookup(host, monkeypatch, recipient_kind):
    events=[]
    monkeypatch.setattr(ui, 'notify', lambda message, **kw: events.append((message,kw)))
    f,api,after=await form(host,actions=('save','complete_review'))
    original=api.disposition_command
    async def command(path,payload,**kw):
        result=await original(path,payload,**kw)
        return {**result,'next_recipients':[] if recipient_kind=='none' else [{'kind':recipient_kind,'name':'مدير الوحدة'}]}
    api.disposition_command=command
    reads_before=list(api.reads)
    with host:
        await f.perform('complete_review')
        expected=text('review_completed') if recipient_kind=='none' else text('review_completed_to',recipients=text('next_role_queue',name='مدير الوحدة') if recipient_kind=='role_queue' else 'مدير الوحدة')
        assert events[-1][0]==expected and events[-1][1]['timeout']==8000
    assert after and api.reads==reads_before
    assert [p for p,_,_ in api.writes]==['tasks/8/review-decision']


@pytest.mark.parametrize('message_key', ['submitted','review_completed','external_approved','external_rejected','physical_confirmed','digital_done_completion_pending'])
def test_every_stage_completion_uses_same_recipient_confirmation(host, monkeypatch, message_key):
    from frontend.webui.disposition.handoff import notify_completion
    notices=[]
    monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append((message,kw)))
    with host:
        notify_completion({'next_recipients':[{'kind':'person','name':'أحمد المنصوري'}]},message_key)
        expected=text('submitted_to' if message_key=='submitted' else 'review_completed_to',recipients='أحمد المنصوري') if message_key in ('submitted','review_completed') else text('completion_next_task',message=text(message_key),recipients='أحمد المنصوري')
        assert notices[-1]==(expected,{'type':'positive','timeout':8000})


def test_automatic_and_final_stage_messages_do_not_invent_a_recipient(host, monkeypatch):
    from frontend.webui.disposition.handoff import notify_completion
    notices=[]
    monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append(message))
    with host:
        notify_completion({'next_stage':'certificate_generation','next_recipients':[]},'digital_done_completion_pending')
        assert notices[-1]==text('completion_next_automatic',message=text('digital_done_completion_pending'),stage=text('certificate_generation'))
        notify_completion({'workflow_completed':True,'next_recipients':[{'kind':'person','name':'مدير الوثائق'}]},'job_completed')
        assert notices[-1]==text('completion_next_task',message=text('job_completed'),recipients='مدير الوثائق')
        notify_completion({'workflow_completed':True,'next_recipients':[]},'physical_confirmed')
        assert notices[-1]==text('job_completed')


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['officer_preparation','officer_correction','file_administrator_review','unit_manager_review','records_manager_review','external_approval','physical_destruction'])
async def test_completed_task_returns_to_inbox_after_confirmation(host, monkeypatch, stage):
    from frontend.webui.disposition.handoff import task_finished,notify_completion
    events=[]
    async def inbox():events.append('inbox')
    async def refresh(result):events.append('refresh')
    monkeypatch.setattr(ui,'notify',lambda message,**kw:events.append('confirmation'))
    f=SimpleNamespace(alive=lambda:True,task={'task_type':stage},job={'workflow_stage':stage},on_submitted=inbox,after=refresh)
    with host:
        notify_completion({'next_recipients':[{'kind':'person','name':'Next reviewer'}]},'review_completed')
        await task_finished(f,{'next_stage':'digital_destruction'})
    assert events==['confirmation','inbox']


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['digital','certificate','completed','overview','abandoned','committed_report_pending'])
async def test_task_completion_preserves_progress_final_overview_and_page_liveness(host, case):
    from frontend.webui.disposition.handoff import task_finished
    events=[]
    async def inbox():events.append('inbox')
    async def refresh(result):events.append('refresh')
    f=SimpleNamespace(alive=lambda:case!='abandoned',task={'task_type':'digital_destruction' if case=='digital' else 'certificate_download' if case=='certificate' else 'records_manager_review'},job={'workflow_stage':'certificate_generation' if case=='certificate' else 'records_manager_review'},on_submitted=None if case=='overview' else inbox,after=refresh)
    result={'workflow_completed':case=='completed','approval_committed':case=='committed_report_pending'}
    await task_finished(f,result)
    assert events==([] if case=='abandoned' else ['inbox'] if case=='committed_report_pending' else ['refresh'])


@pytest.mark.asyncio
async def test_review_completion_returns_to_inbox_without_reload(host, monkeypatch):
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    events=[]
    f,api,after=await form(host,actions=('save','complete_review'))
    async def inbox():events.append('inbox')
    f.on_submitted=inbox
    with host:await f.perform('complete_review')
    assert events==['inbox'] and not after


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['complete_review','reject','approve'])
@pytest.mark.parametrize('outcome', ['success','failed','committed_pending'])
async def test_review_stage_actions_navigate_only_after_committed_completion(host, monkeypatch, action, outcome):
    from nicegui.elements.dialog import Dialog
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    async def confirmed():return True
    monkeypatch.setattr(Dialog,'__await__',lambda self:confirmed().__await__())
    f,api,after=await form(host,actions=('save',action))
    f.work['own_notes']['review_notes']=f.comments.value
    f.work['overall_reason']=f.comments.value
    events=[]
    async def inbox():events.append('inbox')
    f.on_submitted=inbox
    original=api.disposition_page
    async def request(path,**params):
        if path.endswith('/approval-preview'):return {'job_version':2,'task_version':3,'membership_token':'a'*64,'proposals_token':'b'*64}
        return await original(path,**params)
    api.disposition_page=request
    if outcome=='failed':api.error=ApiError(409,{'code':'disposition_stale_task'})
    if outcome=='committed_pending':api.error=ApiError(503,{'code':'disposition_execution_report_pending','approval_committed':True})
    with host:await f.perform(action)
    assert events==([] if outcome=='failed' else ['inbox'])
    assert not any(not r.get('_saved_work') for r in after)


@pytest.mark.asyncio
@pytest.mark.parametrize('job_type', ['destruction','permanent_transfer'])
async def test_inbox_blocker_describes_final_action_not_job_admission(host, job_type):
    from frontend.webui.disposition.messages import action_required_label
    calls=[]
    async def request(path,**params):
        calls.append(params)
        return {'items':[dict(id=8,job_id=5,job_number='DT-2026-1',job_type=job_type,task_type='records_manager_review',workflow_stage='records_manager_review',task_state='open',date_created='2026-10-26',age_seconds=0,root_count=1,blocked=True)],'total':1}
    async def open_task(*a):pass
    with host:
        await tasks_screen(api=SimpleNamespace(disposition_page=request),container=host,active=lambda:True,on_error=str,open_task=open_task,format_timestamp=str,saved={'indicator':'blocked'})
        table=next(e for e in host.descendants() if isinstance(e,ui.table))
        assert table.rows[0]['indicator']==text('destruction_blocked' if job_type=='destruction' else 'disposition_blocked')
        assert table.rows[0]['indicator']!=text('blocked')
        select=next(e for e in host.descendants() if isinstance(e,ui.select) and e._props.get('label')==text('action_required'))
        assert select.options['blocked']==text('disposition_blocked')
        assert action_required_label('blocked',job_type)==table.rows[0]['indicator']
    assert calls[0]['indicator']=='blocked'


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome',['request','empty','conditional'])
async def test_approval_dialog_counts_complete_set_and_cancel_never_saves(host,monkeypatch,outcome):
    from nicegui.elements.dialog import Dialog
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    f,api,after=await form(host,actions=('save','approve'))
    f.pending=[dict(action='create',proposal_type='make_vital',governing_root_id=10,target_aggregation_id=10,target_version=6,proposed_values={})]
    async def summary(task_id,**params):
        assert params['changes']==f.pending
        return {'job_version':2,'task_version':3,'membership_token':'a','proposals_token':'b','proposal_count':1201,'proposal_counts':{'make_vital':1,'remove_aggregation_relationship':1200},'next_step':outcome,'empty_return_stage':'officer_correction'}
    api.disposition_approval_summary=summary
    async def cancel():
        labels=[e.text for e in host.descendants() if isinstance(e,ui.label)]
        assert text('approval_summary',count=1201,counts=' · '.join([text('approval_type_count',kind=text('make_vital'),count=1),text('approval_type_count',kind=text('remove_aggregation_relationship'),count=1200)])) in labels
        assert text('approval_no_destruction') in labels
        assert text('approval_next_empty',stage=text('officer_correction')) in labels if outcome=='empty' else text('approval_next_request' if outcome=='request' else 'approval_next_conditional') in labels
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog))
        assert any(isinstance(e,ui.button) and e.text==text('approve_apply') for e in dialog.descendants())
        assert not any(isinstance(e,ui.expansion) for e in dialog.descendants())
        return False
    monkeypatch.setattr(Dialog,'__await__',lambda self:cancel().__await__())
    with host:await f.perform('approve')
    assert not api.writes and not after and len(f.pending)==1


@pytest.mark.asyncio
async def test_approval_summary_reused_without_save_and_refreshed_only_after_save(host,monkeypatch):
    from nicegui.elements.dialog import Dialog
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    async def yes():return True
    monkeypatch.setattr(Dialog,'__await__',lambda self:yes().__await__())
    f,api,_=await form(host,actions=('save','approve'))
    f.work['own_notes']['review_notes']=f.comments.value;f.work['overall_reason']=f.comments.value
    with host:await f.perform('approve')
    assert [p for p,_,_ in api.writes]==['tasks/8/approve-proposals']
    assert not any(p.endswith('/approval-preview') for p,_ in api.reads)
    api.writes.clear();api.reads.clear();f.comments.value+=' updated'
    original=api.disposition_page
    async def read(path,**params):
        if path.endswith('/approval-preview'):return {'job_version':3,'task_version':4,'membership_token':'fresh-members','proposals_token':'fresh-proposals'}
        return await original(path,**params)
    api.disposition_page=read
    with host:await f.perform('approve')
    assert [p for p,_,_ in api.writes]==['tasks/8/review-work','tasks/8/approve-proposals']
    assert api.writes[-1][1]['proposals_token']=='fresh-proposals'


@pytest.mark.parametrize('pending',[False,True])
@pytest.mark.asyncio
async def test_approval_opens_document_results_instead_of_inbox(host,monkeypatch,pending):
    from nicegui.elements.dialog import Dialog
    async def confirmed():return True
    monkeypatch.setattr(Dialog,'__await__',lambda self:confirmed().__await__())
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    f,api,after=await form(host,actions=('save','approve'))
    events=[]
    async def approved(result):events.append(('documents',result))
    async def inbox():events.append(('inbox',None))
    f.on_approved=approved;f.on_submitted=inbox
    if pending:api.error=ApiError(503,{'approval_committed':True,'code':'disposition_execution_report_pending'})
    with host:await f.perform('approve')
    assert len(events)==1 and events[0][0]=='documents'
    assert not after
