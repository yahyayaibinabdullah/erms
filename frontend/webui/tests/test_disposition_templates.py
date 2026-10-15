"""Standard template controls, bounded history, abandoned reads and retry UX."""
import asyncio
import inspect
from io import BytesIO
from types import SimpleNamespace
import pytest
from nicegui import ui,core
from starlette.datastructures import UploadFile
from frontend.webui.api_client import ApiError
from frontend.webui.locale_services import set_locale_context
from frontend.webui.disposition.templates import templates_panel,upload_dialog,history_dialog
from frontend.webui.disposition.screens import column


@pytest.fixture
def host():return ui.column()


def row():return dict(id=None,document_type='destruction_request',revision_number=0,reference='default.v1:'+'a'*64,original_filename='request.docx',checksum='a'*64,uploaded_at=None)


@pytest.mark.asyncio
async def test_four_fixed_templates_load_once_and_refresh_after_upload(host):
    calls=[]
    async def request(path,**params):calls.append((path,params));return {'items':[row()],'roles':[{'id':2,'name':'Officer'}]}
    with host:
        set_locale_context('en','Asia/Dubai')
        load=templates_panel(api=SimpleNamespace(disposition_page=request),job={'id':1,'job_type':'destruction'},context={'roles':[{'profile_code':'INFO_GOV_OFFICER'}]},active=lambda:True,on_error=str,format_timestamp=str,column=column)
        await load();await load()
    assert calls==[('jobs/1/templates',{}),('jobs/1/templates',{})]
    assert len([x for x in host.descendants() if isinstance(x,ui.button) and x.text=='Download Word template'])==1


@pytest.mark.asyncio
async def test_ineligible_roles_do_not_request_templates(host):
    async def request(*a,**k):pytest.fail('Ineligible role must not add a request')
    with host:
        load=templates_panel(api=SimpleNamespace(disposition_page=request),job={'id':1,'job_type':'destruction'},context={'roles':[{'profile_code':'ALL_PRIVS'}]},active=lambda:True,on_error=str,format_timestamp=str,column=column)
        await load()


@pytest.mark.asyncio
async def test_abandoned_template_read_cannot_update_page(host):
    future=asyncio.get_running_loop().create_future();active=[True]
    async def request(*a,**k):return await future
    with host:
        load=templates_panel(api=SimpleNamespace(disposition_page=request),job={'id':1,'job_type':'destruction'},context={'roles':[{'profile_code':'INFO_GOV_MGR'}]},active=lambda:active[0],on_error=str,format_timestamp=str,column=column)
        task=asyncio.create_task(load());await asyncio.sleep(0);active[0]=False;future.set_result({'items':[row()],'roles':[]});await task
    assert not any(isinstance(x,ui.button) and x.text=='Upload template revision' for x in host.descendants())


@pytest.mark.asyncio
async def test_native_upload_missing_reason_toast_exact_retry_and_success(monkeypatch,host):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());notices=[];calls=[];saved=[]
    monkeypatch.setattr(ui,'notify',lambda message,**options:notices.append((message,options.get('type'))))
    async def revise(*a,**kwargs):
        calls.append({**kwargs,'bytes':kwargs['content'].read()})
        if len(calls)==1:raise ApiError(503,{'detail':{'code':'temporary'}})
        return {'id':1}
    async def after(result):saved.append(result)
    with host:
        set_locale_context('en','Asia/Dubai')
        await upload_dialog(api=SimpleNamespace(revise_disposition_template=revise),job={'id':1},row=row(),roles=[{'id':2,'name':'Officer'}],active=lambda:True,on_error=str,after=after)
        button=next(x for x in host.descendants() if isinstance(x,ui.button) and x.text=='Save');handler=next(iter(button._event_listeners.values())).handler
        result=handler(None)
        if inspect.isawaitable(result):await result
        await asyncio.sleep(0)
        assert notices[-1][1]=='warning' and not calls
        uploader=next(x for x in host.descendants() if isinstance(x,ui.upload))
        uploader.handle_uploads([UploadFile(BytesIO(b'Word bytes'),filename='revised.docx')])
        reason=next(x for x in host.descendants() if isinstance(x,ui.textarea));reason.value='Revise the bilingual layout'
        for _ in range(2):
            result=handler(None)
            if inspect.isawaitable(result):await result
            await asyncio.sleep(0)
    assert len(calls)==2 and calls[0]['command_id']==calls[1]['command_id']
    assert calls[0]['bytes']==calls[1]['bytes']==b'Word bytes'
    assert calls[0]['expected_reference']==row()['reference'] and saved==[{'id':1}]
    assert notices[-1][1]=='positive'


@pytest.mark.asyncio
async def test_history_reuses_wathiq_table_and_true_page_offsets(host):
    calls=[]
    async def request(path,**params):calls.append(params);return {'items':[row()],'total':30}
    with host:
        set_locale_context('en','Asia/Dubai')
        await history_dialog(api=SimpleNamespace(disposition_page=request),job={'id':1},kind='destruction_request',active=lambda:True,on_error=str,format_timestamp=str,column=column)
        table=next(x for x in host.descendants() if isinstance(x,ui.table))
    assert 'erms-page-table' in table._classes and table._props['wrap-cells']
    assert calls[0]['limit']==25 and calls[0]['offset']==0
    assert len(table.rows)==1 and table.rows[0]['uploaded_at_label']=='Repository default v1'
