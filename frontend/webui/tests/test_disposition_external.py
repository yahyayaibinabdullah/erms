"""External request controls: real native forms, exact retries and required evidence."""
import asyncio
import inspect
from io import BytesIO
from copy import deepcopy
from fastapi import UploadFile
from nicegui import ui,core
import pytest
from frontend.webui.tests.test_disposition_tasks import host,Api,view
from frontend.webui.disposition.review import ReviewForm
from frontend.webui.disposition.external import decision_dialog
from frontend.webui.disposition.messages import text
from frontend.webui.api_client import ApiError


async def build(host,api=None,*,manager=False):
    api=api or Api();saved=[]
    async def after(result):saved.append(result)
    v=view(actions=('external_decide',));v['job'].update(workflow_stage='external_approval_pending',current_review_round=1)
    v['task'].update(task_type='external_approval',request_document_id=99)
    v['external']={'round_id':10,'request':{'id':99,'record_id':4,'digital_component_id':5,'file_name':'request-round-1.pdf'},'can_generate':False,'can_renew':False,'approval_current':True,'manager_roles':[],'renew_roles':[]}
    if manager:
        v['task']=None;v['external'].update(request=None,can_generate=True,manager_roles=[{'id':7,'name':'Manager'}])
    with host:
        f=ReviewForm(api=api,workspace=v,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=after,format_timestamp=str,open_resource=None)
        await f.load()
    return f,api,saved


async def click(button):
    response=next(iter(button._event_listeners.values())).handler(None)
    if inspect.isawaitable(response):await response
    await asyncio.sleep(0);await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_external_task_does_not_request_review_work_or_offer_internal_proposals(host):
    f,api,_=await build(host)
    assert [p for p,_ in api.reads]==['jobs/5/proposals']
    buttons=[e.text for e in host.descendants() if isinstance(e,ui.button)]
    assert text('external_approve') in buttons and text('external_reject') in buttons
    assert not any(text(key) in buttons for key in ('submit','approve','save','propose'))
    assert not any(isinstance(e,ui.textarea) for e in host.descendants())


@pytest.mark.asyncio
@pytest.mark.parametrize('decision',['approved','rejected'])
async def test_missing_required_number_notes_or_letter_warns_without_request(host,monkeypatch,decision):
    notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**kw:notices.append(kw));monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    f,api,_=await build(host)
    async def destination(*a,**k):return {'warning':None,'changed':False,'destination':None,'previous_destination':None,'ready':True,'token':'a'*64}
    api.disposition_page=destination
    with host:
        await decision_dialog(f,decision)
        button=next(e for e in reversed(list(host.descendants())) if isinstance(e,ui.button) and e.text==text('save'))
        await click(button)
    assert not api.writes and notices[-1]['type']=='warning'


@pytest.mark.asyncio
@pytest.mark.parametrize('decision',['approved','rejected'])
async def test_external_save_retains_file_input_and_retry_identity_then_confirms(host,monkeypatch,decision):
    notices=[];monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append(kw));monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    f,api,saved=await build(host);calls=[]
    async def destination(*a,**k):return {'warning':None,'changed':False,'destination':None,'previous_destination':None,'ready':True,'token':'a'*64}
    async def submit(task_id,**kwargs):
        calls.append((task_id,{k:v for k,v in kwargs.items() if k!='content'},kwargs['content'].read()))
        if len(calls)==1:raise ApiError(409,{'code':'disposition_stale_task'})
        return {'id':12,'decision':decision}
    api.disposition_page=destination;api.record_external_decision=submit
    with host:
        dialog=await decision_dialog(f,decision)
        uploader=next(e for e in dialog.descendants() if isinstance(e,ui.upload));uploader.handle_uploads([UploadFile(BytesIO(b'Received authority letter'),filename='letter.pdf')])
        field=next(e for e in dialog.descendants() if isinstance(e,ui.input if decision=='approved' else ui.textarea));field.value='  سل/2026 #1  ' if decision=='approved' else 'Please correct the schedule'
        button=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        await click(button)
        assert dialog.value and field.value and notices[-1]['type']=='negative'
        await click(button)
    assert len(calls)==2 and calls[0]==calls[1] and calls[0][2]==b'Received authority letter'
    assert calls[0][1]['request_document_id']==99 and calls[0][1]['task_version']==3
    assert calls[0][1]['destruction_number']==('  سل/2026 #1  ' if decision=='approved' else None)
    assert saved==[{'id':12,'decision':decision}] and notices[-1]['type']=='positive'


@pytest.mark.asyncio
async def test_generation_retry_is_current_role_scoped_idempotent_and_warns_when_pending(host,monkeypatch):
    notices=[];monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append(kw));monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    f,api,saved=await build(host,manager=True)
    api.error=ApiError(503,{'code':'disposition_request_generation_pending'})
    with host:
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('generate_request'))
        await click(button);assert notices[-1]['type']=='negative'
        api.error=None
        async def command(path,payload,**kwargs):api.writes.append((path,deepcopy(payload),kwargs));return {'request_status':'pending'}
        api.disposition_command=command;await click(button)
    assert api.writes[0][1]['command_id']==api.writes[1][1]['command_id']
    assert api.writes[-1][0]=='jobs/5/review-rounds/10/request' and api.writes[-1][1]['acting_role_id']==7
    assert notices[-1]['type']=='warning' and saved==[{'request_status':'pending'}]


@pytest.mark.asyncio
async def test_external_history_is_lazy_bounded_and_sorts_on_server(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());f,api,_=await build(host)
    section=next(e for e in host.descendants() if isinstance(e,ui.expansion) and e.text==text('external_decisions'))
    assert not any(p.endswith('external-decisions') for p,_ in api.reads)
    with host:
        section.value=True;await asyncio.sleep(0);await asyncio.sleep(0)
    path,params=api.reads[-1]
    assert path=='jobs/5/external-decisions' and params=={'limit':25,'offset':0,'sort':'recorded_at','descending':True}


@pytest.mark.asyncio
async def test_saved_request_does_not_repeat_document_block_but_keeps_recovery(host):
    from frontend.webui.disposition.external import request_controls
    f,_,_=await build(host)
    with host:
        documents=ui.column()
        request_controls(f,host=documents)
    assert not list(documents.descendants())
    f.view['external'].update(can_generate=True,manager_roles=[{'id':7,'name':'Manager'}],generation_error='disposition_document_unavailable')
    with host:request_controls(f,host=documents)
    assert any(isinstance(e,ui.button) and e.text==text('generate_request') for e in documents.descendants())
    assert not any(isinstance(e,ui.label) and e.text=='request-round-1.pdf' for e in documents.descendants())


@pytest.mark.asyncio
@pytest.mark.parametrize('decision',['approved','rejected'])
@pytest.mark.parametrize('current',[True,False])
async def test_received_external_decision_does_not_leave_status_only_request_block(host,decision,current):
    from frontend.webui.disposition.external import request_controls
    f,_,_=await build(host)
    f.view['external'].update(received_decision=decision,approval_current=current)
    with host:
        documents=ui.column()
        request_controls(f,host=documents)
    assert not list(documents.descendants())
