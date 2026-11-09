"""Durable acceptance, prominent nonmodal status and navigation in both languages."""
import asyncio
from types import SimpleNamespace
import pytest
from nicegui import ui,core
from nicegui.elements.dialog import Dialog
from frontend.webui.api_client import ApiError
from frontend.webui.disposition.messages import text
from frontend.webui.disposition.background import controls
from frontend.webui.tests.test_disposition_tasks import host,Api,form
from frontend.webui.tests.test_disposition_external import click


def progress(**extra):
    return dict(operation_id='work-1',job_id=5,task_id=8,operation='approve_proposals',state='running',phase='applying',approval_committed=False,last_error_code=None,**extra)


def test_processing_guidance_replaces_claim_instructions(host):
    from frontend.webui.disposition.review import ReviewForm
    from frontend.webui.tests.test_disposition_tasks import view
    workspace=view(actions=());workspace['operation']=progress()
    with host:
        f=ReviewForm(api=Api(),workspace=workspace,active=lambda:True,on_error=str,bind_remote=lambda *a,**kw:None,after=None,format_timestamp=str,open_resource=None)
    assert text('review_hint') not in [e.text for e in f.host.descendants() if isinstance(e,ui.label)]


@pytest.mark.asyncio
async def test_acceptance_returns_without_waiting_for_application_or_documents(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());notices=[]
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:notices.append(a))
    async def confirmed():return True
    monkeypatch.setattr(Dialog,'__await__',lambda self:confirmed().__await__())
    api=Api();send=api.disposition_command
    async def accepted(path,payload,**kw):
        await send(path,payload,**kw);return progress()
    api.disposition_command=accepted
    f,_,after=await form(host,api,actions=('save','propose','approve'),route='records_manager_only')
    f.work['own_notes']['review_notes']=f.comments.value;f.work['overall_reason']=f.comments.value
    results=[]
    async def open_results(result):results.append(result)
    f.on_approved=open_results
    with host:await f.perform('approve')
    assert len(api.writes)==1 and after[0]['operation_id']=='work-1'
    assert not f.busy and not f.has_changes() and not results
    assert not any(isinstance(e,ui.dialog) and e._props.get('persistent') for e in f.host.descendants())
    assert notices[-1]==(text('approval_queued'),)


@pytest.mark.asyncio
async def test_document_retry_recovers_lost_acceptance_response_without_new_request(host,monkeypatch):
    from copy import deepcopy
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    monkeypatch.setattr(ui,'timer',lambda *a,**kw:SimpleNamespace(activate=lambda:None,deactivate=lambda:None))
    sent=[];errors=[];refreshed=[]
    async def command(path,payload,**kw):
        sent.append((path,deepcopy(payload)))
        if len(sent)==1:raise ApiError(503,{'code':'connection_lost'})
        return progress()
    async def after(value):refreshed.append(value)
    value=progress();value.update(state='failed',phase='documents',approval_committed=True)
    f=SimpleNamespace(host=host,status_host=host,view={'operation':value},api=SimpleNamespace(disposition_command=command),
        alive=lambda:True,busy=False,actions={'retry_approval_documents'},job={'id':5},acting_role_id=7,retry={},after=after,error=errors.append)
    with host:
        controls(f)
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('approval_retry_documents'))
        await click(button)
        assert errors and not refreshed and not f.busy and not button._props.get('disable')
        await click(button)
    assert sent[0]==sent[1] and refreshed==[{}]
    assert sent[0][1]['acting_role_id']==7 and sent[0][1]['command_id']


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome',['running','documents','ready','failed','read_error','abandoned'])
async def test_nonmodal_status_polls_current_state_without_owning_work(host,monkeypatch,outcome):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    timers=[]
    monkeypatch.setattr(ui,'timer',lambda interval,callback,**kw:timers.append(SimpleNamespace(callback=callback,activate=lambda:None,deactivate=lambda:None)) or timers[-1])
    active=[True];after=[];results=[];inbox=[];reads=[];gate=asyncio.Future()
    async def request(path,**params):
        reads.append(path)
        if outcome=='abandoned':await gate
        if outcome=='read_error':raise ApiError(503,{'code':'connection_lost'})
        value=progress()
        if outcome=='documents':value.update(phase='documents',approval_committed=True)
        if outcome=='ready':value.update(state='succeeded',phase='ready',approval_committed=True)
        if outcome=='failed':value.update(state='failed',approval_committed=True,phase='documents')
        return value
    async def refreshed(result):after.append(result)
    async def approved(result):results.append(result)
    async def tasks(result):inbox.append(result)
    f=SimpleNamespace(host=host,status_host=host,view={'operation':progress()},api=SimpleNamespace(disposition_page=request),alive=lambda:active[0],busy=False,actions=[],job={'id':5},after=refreshed,on_approved=approved,on_submitted=tasks)
    with host:
        controls(f)
        assert not any(isinstance(e,ui.dialog) for e in host.descendants())
        assert any(isinstance(e,ui.label) and e.text==text('background_hint') for e in host.descendants())
        assert not any(isinstance(e,ui.button) and e.text==text('my_tasks') for e in host.descendants())
        assert not inbox and not f.busy
        if outcome=='abandoned':
            async def poll():
                with host:await timers[0].callback()
            pending=asyncio.create_task(poll());await asyncio.sleep(0);active[0]=False;gate.set_result(None);await pending
        else:await timers[0].callback()
        assert reads==['jobs/5/operation-progress']
        if outcome=='ready':assert results and not after
        elif outcome=='failed':assert after and not results
        elif outcome=='read_error':assert any(isinstance(e,ui.label) and e.text==text('progress_unavailable') for e in host.descendants()) and not after
        elif outcome=='documents':assert any(isinstance(e,ui.label) and e.text==text('approval_documents') for e in host.descendants())
        else:assert not after and not results
