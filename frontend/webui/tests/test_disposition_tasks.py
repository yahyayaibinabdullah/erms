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


def test_workflow_has_start_creation_preparation_completed_end_and_saved_bypass(host):
    from frontend.webui.disposition.process import process_source
    with host:
        source=process_source(view(route='simplified')['job']);workflow_panel(view(route='simplified')['job'])
    assert 'START(["'+text('start')+'"]' in source
    assert 'START --> CREATE' in source and 'CREATE --> A' in source
    assert 'P --> END' in source
    assert text('job_created') in source and text('officer_preparation') in source
    assert source.count(text('skipped'))>=2
    # Mermaid is lazy: no diagram asset/component before the user expands it.
    assert not any(isinstance(e,ui.mermaid) for e in host.descendants())


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
