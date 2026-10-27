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
