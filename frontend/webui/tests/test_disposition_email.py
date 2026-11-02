"""Durable email controls retain uncertain submissions and refresh bounded history."""
import asyncio,inspect
from copy import deepcopy
from nicegui import ui,core
import pytest
from frontend.webui.tests.test_disposition_tasks import host,Api,view
from frontend.webui.disposition.review import ReviewForm
from frontend.webui.disposition.email import attempts_panel
from frontend.webui.disposition.messages import text
from frontend.webui.api_client import ApiError


async def build(host):
    api=Api();v=view(actions=());v['task']=None
    v['email']={'recipient':'authority@test.invalid','roles':[{'id':7,'name':'Records Officer'}],'documents':[{'id':99,'file_name':'request.pdf','document_type':'destruction_request','role_ids':[7]}]}
    async def after(*a):pass
    with host:
        f=ReviewForm(api=api,workspace=v,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=after,format_timestamp=str,open_resource=None)
        await f.load()
    return f,api


async def click(button):
    result=next(iter(button._event_listeners.values())).handler(None)
    if inspect.isawaitable(result):await result
    await asyncio.sleep(0);await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_send_keeps_uncertain_identity_but_separates_deliberate_resends(host,monkeypatch):
    notices=[];monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append((message,kw)));monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    f,api=await build(host);calls=[]
    async def send(path,payload,*,reason,**kwargs):
        calls.append((path,deepcopy(payload)))
        if len(calls)==1:raise ApiError(503,{'code':'disposition_email_unknown'})
        return {'attempt_id':3}
    api.disposition_command=send
    button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('send_email'))
    with host:
        await click(button);await click(button);await click(button)
    assert len(calls)==3
    assert calls[0]==calls[1] and calls[1][1]['command_id']!=calls[2][1]['command_id']
    assert calls[0][1]['expected_recipient']=='authority@test.invalid'
    assert notices[-1][0]==text('email_queued') and notices[-1][1]['type']=='positive'
    assert not f.busy and button.enabled


@pytest.mark.asyncio
async def test_email_history_is_lazy_bounded_and_survives_readonly_task_completion(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());f,api=await build(host)
    assert not any(p.endswith('email-attempts') for p,_ in api.reads)
    section=next(e for e in host.descendants() if isinstance(e,ui.expansion) and e.text==text('email_attempts'))
    with host:section.value=True;await asyncio.sleep(0);await asyncio.sleep(0)
    assert api.reads[-1]==('jobs/5/email-attempts',{'limit':25,'offset':0,'sort':'requested_at','descending':True})


@pytest.mark.asyncio
async def test_abandoned_send_does_not_render_stale_feedback(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());f,api=await build(host);alive=[True];f.alive=lambda:alive[0];notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**k:notices.append(a))
    async def send(*a,**kw):alive[0]=False;return {'attempt_id':5}
    api.disposition_command=send;button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('send_email'))
    with host:await click(button)
    assert not notices and not f.busy


@pytest.mark.asyncio
async def test_history_lives_in_documents_and_refreshes_only_while_visible(host,monkeypatch):
    from frontend.webui.disposition.email import controls
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    api=Api();v=view(actions=());v['task']=None;v['email']={'recipient':'authority@test.invalid','documents':[],'roles':[]}
    visible=[False]
    async def after(*a):pass
    with host:
        documents=ui.column();history=ui.column()
        f=ReviewForm(api=api,workspace=v,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=after,format_timestamp=str,open_resource=None,documents_host=documents,history_host=history,documents_active=lambda:visible[0])
        await f.load()
        controls(f,host=documents)  # Rebuilding controls must not duplicate history.
    sections=[e for e in documents.descendants() if isinstance(e,ui.expansion) and e.text==text('email_attempts')]
    assert len(sections)==1
    assert not any(isinstance(e,ui.expansion) and e.text==text('email_attempts') for e in history.descendants())
    with host:
        sections[0].value=True;await asyncio.sleep(0);await asyncio.sleep(0)
        assert not api.reads
        visible[0]=True;await f.refresh_email_history()
        assert len(api.reads)==1 and api.reads[0][1]['limit']==25
        visible[0]=False;await f.refresh_email_history()
        assert len(api.reads)==1
        visible[0]=True;await f.refresh_email_history()
        assert len(api.reads)==2  # Re-entry refreshes; there is no result cache.
        f.active=lambda:False;await f.refresh_email_history()
        assert len(api.reads)==2


async def certificate_form(host,monkeypatch,*,latest=None,allowed=True):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    v=view(actions=('complete_certificate',));v['job'].update(workflow_stage='certificate_generation',lifecycle_state='active')
    v['task'].update(task_type='certificate_download',workflow_stage='certificate_generation')
    cert=dict(id=99,file_name='certificate.pdf',can_download=True,document_type='digital_destruction_certificate',role_ids=[7],latest_attempt=latest)
    v['email']=dict(recipient='authority@test.invalid',roles=[dict(id=7,name='Records Manager')],documents=[cert] if allowed else [])
    v['completion']=dict(completed=False,progress=dict(state='succeeded'),certificate=cert)
    selected=['task'];alive=[True];api=Api()
    async def after(*a):pass
    with host:
        documents=ui.column()
        f=ReviewForm(api=api,workspace=v,active=lambda:alive[0],on_error=str,bind_remote=lambda *a,**kw:None,after=after,format_timestamp=str,open_resource=None,documents_host=documents,documents_active=lambda:selected[0]=='documents',task_active=lambda:selected[0]=='task')
        await f.load()
    return f,api,documents,selected,alive


async def request_form(host,monkeypatch,*,latest=None,allowed=True):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    v=view(actions=('external_decide',));v['job'].update(workflow_stage='external_approval_pending',lifecycle_state='active')
    v['task'].update(task_type='external_approval',workflow_stage='external_approval_pending',request_document_id=99)
    request=dict(id=99,record_id=4,digital_component_id=5,file_name='request.pdf',document_type='destruction_request',role_ids=[7],latest_attempt=latest)
    v['external']=dict(round_id=10,request=request,can_generate=False,can_renew=False,approval_current=True,manager_roles=[],renew_roles=[])
    v['email']=dict(recipient='authority@test.invalid',roles=[dict(id=7,name='Records Officer')],documents=[request] if allowed else [])
    selected=['task'];alive=[True];api=Api()
    async def noop(*a):pass
    with host:
        documents=ui.column()
        f=ReviewForm(api=api,workspace=v,active=lambda:alive[0],on_error=str,bind_remote=noop,after=noop,format_timestamp=str,open_resource=None,preview=noop,documents_host=documents,documents_active=lambda:selected[0]=='documents',task_active=lambda:selected[0]=='task')
        await f.load()
    return f,api,documents,selected,alive


@pytest.mark.asyncio
@pytest.mark.parametrize('allowed',[True,False])
async def test_request_actions_share_row_and_respect_current_send_authority(host,monkeypatch,allowed):
    f,api,documents,_,_=await request_form(host,monkeypatch,allowed=allowed)
    buttons=[e for e in f.body.descendants() if isinstance(e,ui.button)]
    preview=next(e for e in buttons if e.text==text('preview_request'))
    download=next(e for e in buttons if e.text==text('download_request'))
    assert preview.parent_slot==download.parent_slot
    sends=[e for e in buttons if e.text==text('send_email')]
    assert len(sends)==int(allowed)
    if allowed:
        assert sends[0].parent_slot==preview.parent_slot
        assert len(f.email_sends[99]['buttons'])==2
        assert any(isinstance(e,ui.label) and e.text=='authority@test.invalid' for e in f.body.descendants())
        assert any(isinstance(e,ui.label) and e.text==text('email_not_sent') for e in f.body.descendants())
    assert text('external_approve') in [b.text for b in buttons]
    assert text('external_reject') in [b.text for b in buttons]
    assert not any(p.endswith('email-attempts') for p,_ in api.reads) and not api.writes


@pytest.mark.asyncio
async def test_certificate_send_present_in_both_tabs_without_initial_extra_read(host,monkeypatch):
    f,api,documents,_,_=await certificate_form(host,monkeypatch)
    assert len([e for e in f.host.descendants() if isinstance(e,ui.button) and e.text==text('send_email')])==1
    assert len([e for e in documents.descendants() if isinstance(e,ui.button) and e.text==text('send_email')])==1
    assert any(isinstance(e,ui.label) and e.text==text('certificate_email_hint') for e in f.host.descendants())
    assert any(isinstance(e,ui.label) and e.text==text('email_not_sent') for e in f.host.descendants())
    assert api.reads==[] and api.writes==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('form_builder',[certificate_form,request_form],ids=['certificate','request'])
async def test_cross_tab_uncertain_retry_shares_identity_and_updates_both_summaries(host,monkeypatch,form_builder):
    f,api,documents,selected,_=await form_builder(host,monkeypatch);calls=[]
    latest=dict(id=10,document_id=99,status='smtp_accepted',requested_at='09:00',outcome_at='09:01',recipient='authority@test.invalid')
    async def send(path,payload,**kw):
        calls.append((path,deepcopy(payload)))
        if len(calls)==1:raise ApiError(503,{'code':'disposition_email_unknown'})
        return {'attempt_id':10}
    async def read(path,**params):api.reads.append((path,params));return dict(items=[latest],total=1)
    api.disposition_command=send;api.disposition_page=read
    task_button=next(e for e in f.host.descendants() if isinstance(e,ui.button) and e.text==text('send_email'))
    doc_button=next(e for e in documents.descendants() if isinstance(e,ui.button) and e.text==text('send_email'))
    with host:
        await click(task_button);selected[0]='documents';await click(doc_button);await click(doc_button)
    assert calls[0]==calls[1] and calls[1][1]['command_id']!=calls[2][1]['command_id']
    assert calls[0][0]=='jobs/5/documents/99/email'
    assert f.task and f.job['lifecycle_state']=='active'
    assert all(p['document_id']==99 and p['limit']==1 for path,p in api.reads if path.endswith('email-attempts'))
    assert all(text('email_smtp_accepted') in target.text and '09:01' in target.text for target,_ in f.email_sends[99]['summaries'])


@pytest.mark.asyncio
@pytest.mark.parametrize('form_builder',[certificate_form,request_form],ids=['certificate','request'])
async def test_pending_summary_poll_and_reentry_respect_visibility_and_abandonment(host,monkeypatch,form_builder):
    pending=dict(status='sending',requested_at='09:00',outcome_at=None,recipient='authority@test.invalid')
    f,api,_,selected,alive=await form_builder(host,monkeypatch,latest=pending)
    state=f.email_sends[99];assert state['timer'].active
    before_reads=list(api.reads)
    selected[0]='members';await state['refresh']();assert api.reads==before_reads
    async def read(path,**params):api.reads.append((path,params));alive[0]=False;return dict(items=[],total=0)
    api.disposition_page=read;selected[0]='task';before=[label.text for label,_ in state['summaries']]
    await state['refresh']()
    assert [label.text for label,_ in state['summaries']]==before
    await state['timer'].callback();assert not state['timer'].active


@pytest.mark.asyncio
async def test_send_busy_disables_both_buttons_and_completion_remains_independent(host,monkeypatch):
    from frontend.webui.tests.test_disposition_external import click as finish_click
    f,api,documents,selected,_=await certificate_form(host,monkeypatch)
    task_button=next(e for e in f.host.descendants() if isinstance(e,ui.button) and e.text==text('send_email'))
    doc_button=next(e for e in documents.descendants() if isinstance(e,ui.button) and e.text==text('send_email'))
    entered=asyncio.Event();release=asyncio.Event()
    refreshed=asyncio.Event()
    async def send(*a,**kw):entered.set();await release.wait();return {'attempt_id':1}
    async def read(*a,**kw):refreshed.set();return dict(items=[],total=0)
    api.disposition_command=send
    api.disposition_page=read
    with host:
        sending=asyncio.create_task(click(task_button));await entered.wait()
        assert not task_button.enabled and not doc_button.enabled
        selected[0]='documents';await click(doc_button);release.set();await sending;await refreshed.wait()
    assert not f.busy and task_button.enabled and doc_button.enabled
    # A separate form can complete with no send and no download.
    f2,api2,_,_,_=await certificate_form(host,monkeypatch)
    finish=next(e for e in f2.host.descendants() if isinstance(e,ui.button) and e.text==text('complete_this_task'))
    with host:await finish_click(finish)
    assert [path for path,_,_ in api2.writes]==['jobs/5/complete-certificate-task']


@pytest.mark.asyncio
async def test_certificate_without_send_authority_keeps_completion_but_no_email_action(host,monkeypatch):
    f,api,_,_,_=await certificate_form(host,monkeypatch,allowed=False)
    buttons=[e.text for e in f.host.descendants() if isinstance(e,ui.button)]
    assert text('send_email') not in buttons and text('complete_this_task') in buttons and not api.reads
