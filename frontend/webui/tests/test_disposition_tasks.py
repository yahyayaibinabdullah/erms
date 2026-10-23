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
from frontend.webui.locale_services import set_locale_context
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
    f.note.value='Saved personal observations';f.overall.value=''
    f.queued({'action':'create','governing_root_id':10,'target_aggregation_id':10,'target_version':6,'proposal_type':'make_vital','proposed_values':{}})
    await f.perform('save')
    assert len(api.writes)==1 and api.writes[0][0]=='tasks/8/review-work'
    payload=api.writes[0][1]
    assert payload['overall_reason']=='' and payload['note_version']==4 and payload['review_notes']=='Saved personal observations'
    assert payload['task_version']==3 and api.writes[0][2]['version']==2
    assert not f.dirty() and after and notices[-1][1]['type']=='positive'
    assert {path for path,_ in api.reads}=={'tasks/8/review-work','jobs/5/proposals'}
    assert all(params['limit']==25 and params['offset']==0 for path,params in api.reads if path.startswith('jobs/'))


@pytest.mark.asyncio
async def test_stale_save_retains_draft_and_exact_retry_id_then_role_change_uses_new_id(host,monkeypatch):
    notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**kw:notices.append(kw))
    f,api,after=await form(host);f.note.value='Still unsaved';api.error=ApiError(409,{'code':'disposition_stale_task'})
    await f.perform('save');await f.perform('save')
    assert f.dirty() and not after and notices[-1]['type']=='negative'
    assert api.writes[0][1]['command_id']==api.writes[1][1]['command_id']
    f.role.options={7:'Officer',9:'Successor role'};f.role.value=9
    await f.perform('save')
    assert api.writes[-1][1]['command_id']!=api.writes[0][1]['command_id']


@pytest.mark.asyncio
async def test_submit_saves_visible_changes_first_and_uses_new_versions(host,monkeypatch):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,after=await form(host);f.overall.value='Ready for the next review';f.note.value='Current visible note'
    await f.perform('submit')
    assert [x[0] for x in api.writes]==['tasks/8/review-work','tasks/8/submit-review']
    assert api.writes[1][1]['task_version']==4 and api.writes[1][2]['version']==3
    assert api.writes[1][1]['overall_reason']=='Ready for the next review'


@pytest.mark.asyncio
async def test_blank_submission_warns_without_any_request(host,monkeypatch):
    notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**k:notices.append(k))
    f,api,_=await form(host);f.overall.value='  '
    with host:await f.perform('submit')
    assert api.writes==[] and notices[-1]['type']=='warning'


@pytest.mark.asyncio
async def test_queue_and_other_claimant_have_no_edit_or_decision_controls(host):
    f,api,_=await form(host,actions=('claim',))
    assert f.note is None and f.overall is None
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
    section=next(e for e in f.host.descendants() if isinstance(e,ui.expansion) and e.text==text('review_notes'))
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
    api.error=ApiError(503,{'code':'disposition_execution_report_pending','approval_committed':True,'round_id':9})
    with host:await f.perform('approve')
    assert [x[0] for x in api.writes]==['tasks/8/approve-proposals']
    assert len(after)==1 and after[0]['approval_committed'] and notices[-1]['type']=='warning'


@pytest.mark.asyncio
async def test_native_save_button_dispatches_the_save_action(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    f,api,_=await form(host);f.note.value='Verify native Save dispatch'
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
        if '/review-candidates/' in path:return {'items':[{'id':params.get('selected',3),'code':'REF','name':'Selected reference'}]}
        return await original(path,**params)
    async def request(method,path,params):
        link_reads.append((path,params))
        rows=[{'id':99,'label':'Selected relationship','related':{'redacted':False,'number':'R-99','title':'Outside first page'}}] if params.get('selected_id') else []
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
        assert link_reads[-1][1]=={'selected_id':99,'limit':1,'offset':0}


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
        monkeypatch.setattr(module,method,lambda form,n=name:seen.append(n))
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
    assert len([e for e in history.descendants() if isinstance(e,ui.expansion)])==5
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
        notes=next(e for e in host.descendants() if isinstance(e,ui.textarea) and e.label==text('review_notes'))
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
        assert any(isinstance(e,ui.textarea) and e.label==text('review_notes') for e in host.descendants())==(task_id is not None)
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
    async def request(*a,**k):return {'items':deepcopy(links),'total':2}
    api.request=request
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
