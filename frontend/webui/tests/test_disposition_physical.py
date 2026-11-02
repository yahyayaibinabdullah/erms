"""Physical workspace uses native controls and never offers unreleased actions."""
import asyncio
from io import BytesIO
import pytest
from fastapi import UploadFile
from nicegui import ui,core
from frontend.webui.tests.test_disposition_tasks import host,Api,view
from frontend.webui.tests.test_disposition_external import click
from frontend.webui.disposition.review import ReviewForm
from frontend.webui.disposition.physical import confirmation_dialog
from frontend.webui.disposition.messages import text
from frontend.webui.api_client import ApiError


def menu_label(item):
    return ''.join(e.text for e in item.descendants() if isinstance(e,ui.item_section))

async def build(host,*,authorized=False,report=None,can_generate=True,preview=None):
    api=Api();saved=[]
    async def after(result):saved.append(result)
    v=view(actions=('check_physical_work','confirm_physical') if authorized else ())
    v['job'].update(workflow_stage='physical_destruction');v['task'].update(task_type='physical_destruction')
    v['physical']={'report':report,'confirmation':None,'can_generate':can_generate,'manager_roles':[{'id':7,'name':'Manager'}]}
    with host:
        f=ReviewForm(api=api,workspace=v,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=after,format_timestamp=str,open_resource=None,preview=preview)
        await f.load()
    return f,api,saved

@pytest.mark.asyncio
async def test_release_gate_preparation_no_internal_review_downloads_or_confirmation(host):
    f,api,_=await build(host)
    assert not api.reads
    labels=[e.text for e in host.descendants() if isinstance(e,ui.button)]
    assert text('generate_physical_report') in labels
    assert text('confirm_physical') not in labels and text('check_physical_work') not in labels
    assert not any('release' in (e.text or '').lower() for e in host.descendants() if isinstance(e,ui.label))

@pytest.mark.asyncio
async def test_native_form_requires_checkbox_reference_and_file_and_keeps_retry(host,monkeypatch):
    notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**kw:notices.append(kw));monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    f,api,saved=await build(host,authorized=True);calls=[]
    async def destination(*a,**k):return {'ready':True,'token':'a'*64,'warning':None,'changed':False,'destination':None,'previous_destination':None}
    async def confirm(task_id,**kwargs):
        calls.append({k:v for k,v in kwargs.items() if k!='content'})
        if len(calls)==1:raise ApiError(409,{'code':'disposition_physical_reference_used'})
        return {'id':42}
    api.disposition_page=destination;api.confirm_physical=confirm
    with host:
        dialog=await confirmation_dialog(f)
        save=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        await click(save);assert notices[-1]['type']=='warning' and not calls
        number=next(e for e in dialog.descendants() if isinstance(e,ui.input));number.value='CERT/١'
        upload=next(e for e in dialog.descendants() if isinstance(e,ui.upload));upload.handle_uploads([UploadFile(BytesIO(b'certificate'),filename='certificate.pdf')])
        await click(save);assert not calls
        checkbox=next(e for e in dialog.descendants() if isinstance(e,ui.checkbox));checkbox.value=True
        await click(save);assert notices[-1]['type']=='negative' and dialog.value
        await click(save)
    assert calls[0]==calls[1] and calls[0]['successful'] and saved==[{'id':42}]
    assert notices[-1]['type']=='positive'

@pytest.mark.asyncio
async def test_abandoned_report_response_does_not_refresh_page(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    f,api,saved=await build(host)
    async def generate(*a,**k):f.active=lambda:False;return {'id':9}
    api.disposition_command=generate
    with host:
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('generate_physical_report'))
        await click(button)
    assert not saved


@pytest.mark.asyncio
@pytest.mark.parametrize('can_preview,can_download,can_generate',[
    (True,True,True),(False,True,True),(True,False,True),
    (True,True,False),(False,False,False),(False,False,True),
])
async def test_saved_report_actions_retain_independent_access_rules(host,can_preview,can_download,can_generate):
    report=dict(id=21,record_id=23,digital_component_id=24,file_name='preparation-1.pdf',can_preview=can_preview,can_download=can_download)
    async def preview(*args):pass
    f,api,_=await build(host,report=report,can_generate=can_generate,preview=preview)
    buttons=[e.text for e in f.host.descendants() if isinstance(e,ui.button)]
    items=[menu_label(e) for e in f.host.descendants() if isinstance(e,ui.menu_item)]
    assert (text('preview_physical_report') in buttons)==can_preview
    assert (text('physical_report_more') in buttons)==(can_download or can_generate)
    assert (text('download_physical_report') in items)==can_download
    assert (text('update_physical_report') in items)==can_generate
    assert text('generate_physical_report') not in buttons
    assert not api.reads and not api.writes


@pytest.mark.asyncio
async def test_saved_report_view_and_download_use_the_same_saved_document(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    previews=[];downloads=[];requests=[]
    report=dict(id=21,record_id=23,digital_component_id=24,file_name='preparation-1.pdf',can_preview=True,can_download=True)
    async def preview(*args):previews.append(args)
    f,api,_=await build(host,report=report,preview=preview)
    async def request(*args,**kwargs):requests.append((args,kwargs));return b'%PDF-saved-report'
    api.request=request
    monkeypatch.setattr(ui,'download',lambda *args:downloads.append(args))
    with host:
        await click(next(e for e in f.host.descendants() if isinstance(e,ui.button) and e.text==text('preview_physical_report')))
        await click(next(e for e in f.host.descendants() if isinstance(e,ui.menu_item) and menu_label(e)==text('download_physical_report')))
    assert previews==[({'id':23,'title':'preparation-1.pdf'},24)]
    assert requests==[(('GET','/api/v1/disposition/jobs/5/documents/21/content'),{'_cancellable_read':True})]
    assert downloads==[(b'%PDF-saved-report','preparation-1.pdf')]
    assert not api.writes


@pytest.mark.asyncio
async def test_updated_report_failure_keeps_retry_identity_then_refreshes(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    report=dict(id=21,record_id=23,digital_component_id=24,file_name='preparation-1.pdf')
    f,api,saved=await build(host,report=report)
    api.error=ApiError(503,{'code':'disposition_request_generation_pending'})
    item=next(e for e in f.host.descendants() if isinstance(e,ui.menu_item) and menu_label(e)==text('update_physical_report'))
    with host:
        await click(item)
        assert not saved and not f.busy and not item._props.get('disable',False)
        api.error=None
        await click(item)
    assert len(api.writes)==2 and api.writes[0]==api.writes[1]
    assert api.writes[0][0]=='jobs/5/physical-preparation-report'
    assert api.writes[0][1]['acting_role_id']==7
    assert api.writes[0][2]['version']==2
    assert len(saved)==1 and not f.busy
