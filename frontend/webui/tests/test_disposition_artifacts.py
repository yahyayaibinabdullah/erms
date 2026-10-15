"""Guarded document requests, standard controls and correction feedback."""
import asyncio
import inspect
from types import SimpleNamespace
import pytest
from nicegui import ui,core
from frontend.webui.locale_services import set_locale_context
from frontend.webui.disposition.artifacts import documents_panel,correction_dialog
from frontend.webui.disposition.screens import column


@pytest.fixture
def host():
    return ui.column()


@pytest.mark.asyncio
async def test_document_panel_uses_one_bounded_page_and_parallel_destinations(host):
    calls=[];barrier=asyncio.Event()
    async def request(path,**params):
        calls.append((path,params))
        if len(calls)==3:barrier.set()
        await asyncio.wait_for(barrier.wait(),1)
        if path.endswith('/documents'):return {'items':[],'total':0,'correction_roles':[]}
        return {'warning':'disposition_destination_unset','changed':False,'destination':None,'previous_destination':None,'ready':False,'token':'x'*64}
    with host:
        set_locale_context('en','Asia/Dubai')
        load=documents_panel(api=SimpleNamespace(disposition_page=request),job={'id':1},active=lambda:True,on_error=str,after=lambda r:None,open_resource=lambda *a:None,preview=None,format_timestamp=str,column=column)
        await load()
    assert len(calls)==3
    assert next(params for path,params in calls if path.endswith('/documents'))['limit']==25
    table=next(x for x in host.descendants() if isinstance(x,ui.table))
    assert 'erms-page-table' in table._classes
    assert table._props.get('wrap-cells') is True


@pytest.mark.asyncio
async def test_abandoned_document_panel_does_not_render_late_warning(host):
    pending=[];alive=[True]
    async def request(path,**params):
        f=asyncio.get_running_loop().create_future();pending.append((path,f));return await f
    with host:
        set_locale_context('en','Asia/Dubai')
        load=documents_panel(api=SimpleNamespace(disposition_page=request),job={'id':1},active=lambda:alive[0],on_error=str,after=lambda r:None,open_resource=lambda *a:None,preview=None,format_timestamp=str,column=column)
        task=asyncio.create_task(load())
        for _ in range(4):await asyncio.sleep(0)
        alive[0]=False
        for path,f in pending:f.set_result({'items':[],'total':0,'correction_roles':[]} if path.endswith('/documents') else {'warning':'disposition_destination_unset','changed':False,'destination':None})
        await task
    assert not any(isinstance(x,ui.label) and x.text.startswith('Configure the classification') for x in host.descendants())


@pytest.mark.asyncio
async def test_correction_native_upload_and_missing_reason_toast(monkeypatch,host):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    notices=[];calls=[]
    monkeypatch.setattr(ui,'notify',lambda message,**options:notices.append((message,options.get('type'))))
    async def request(*a,**k):return {'warning':None,'changed':True,'destination':None,'previous_destination':None,'ready':True,'token':'x'*64}
    async def submit(*a,**k):calls.append((a,k));return {'id':2}
    with host:
        set_locale_context('en','Asia/Dubai')
        await correction_dialog(api=SimpleNamespace(disposition_page=request,correct_disposition_evidence=submit),job={'id':1,'version':1},row={'id':1,'file_name':'evidence.pdf','document_type':'external_approval_letter'},roles=[{'id':2,'name':'Records Manager'}],active=lambda:True,on_error=str,after=lambda r:None)
        button=next(x for x in host.descendants() if isinstance(x,ui.button) and x.text=='Save')
        handler=next(iter(button._event_listeners.values())).handler
        response=handler(None)
        if inspect.isawaitable(response):await response
        await asyncio.sleep(0)
    assert any(isinstance(x,ui.upload) for x in host.descendants())
    assert not calls and notices[-1][1]=='warning'
    assert 'have not been saved' in notices[-1][0]


@pytest.mark.asyncio
async def test_native_upload_retains_spooled_file_and_success_feedback(monkeypatch,host):
    from io import BytesIO
    from fastapi import UploadFile
    from frontend.webui.api_client import ApiError
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    notices=[];calls=[];saved=[]
    monkeypatch.setattr(ui,'notify',lambda message,**options:notices.append((message,options.get('type'))))
    async def request(*a,**k):return {'warning':None,'changed':False,'destination':None,'previous_destination':None,'ready':True,'token':'x'*64}
    async def submit(*a,**k):
        calls.append((k['command_id'],k['content'].read()))
        if len(calls)==1:raise ApiError(503,{'code':'temporary_unavailable'})
        return {'id':2}
    async def after(result):saved.append(result)
    with host:
        set_locale_context('en','Asia/Dubai')
        await correction_dialog(api=SimpleNamespace(disposition_page=request,correct_disposition_evidence=submit),job={'id':1,'version':1},row={'id':1,'file_name':'evidence.pdf','document_type':'external_approval_letter'},roles=[{'id':2,'name':'Records Manager'}],active=lambda:True,on_error=str,after=after)
        uploader=next(x for x in host.descendants() if isinstance(x,ui.upload))
        uploader.handle_uploads([UploadFile(BytesIO(b'corrected evidence'),filename='corrected.pdf')])
        reason=next(x for x in host.descendants() if isinstance(x,ui.textarea));reason.value='Correct mistaken evidence'
        button=next(x for x in host.descendants() if isinstance(x,ui.button) and x.text=='Save')
        handler=next(iter(button._event_listeners.values())).handler
        for _ in range(2):
            result=handler(None)
            if inspect.isawaitable(result):await result
            await asyncio.sleep(0)
    assert len(calls)==2 and calls[0]==calls[1]
    assert calls[0][1]==b'corrected evidence'
    assert saved==[{'id':2}] and notices[-1]==('Changes saved','positive')
