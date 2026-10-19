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

async def build(host,*,released=False):
    api=Api();saved=[]
    async def after(result):saved.append(result)
    v=view(actions=('check_physical_work','confirm_physical') if released else ())
    v['job'].update(workflow_stage='physical_destruction');v['task'].update(task_type='physical_destruction')
    v['physical']={'report':None,'released':released,'confirmation':None,'can_generate':True,'manager_roles':[{'id':7,'name':'Manager'}]}
    with host:
        f=ReviewForm(api=api,workspace=v,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=after,format_timestamp=str,open_resource=None)
        await f.load()
    return f,api,saved

@pytest.mark.asyncio
async def test_release_gate_preparation_no_internal_review_downloads_or_confirmation(host):
    f,api,_=await build(host)
    assert not api.reads
    labels=[e.text for e in host.descendants() if isinstance(e,ui.button)]
    assert text('generate_physical_report') in labels
    assert text('confirm_physical') not in labels and text('check_physical_work') not in labels
    assert any(e.text==text('disposition_physical_release_pending') for e in host.descendants() if isinstance(e,ui.label))

@pytest.mark.asyncio
async def test_native_form_requires_checkbox_reference_and_file_and_keeps_retry(host,monkeypatch):
    notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**kw:notices.append(kw));monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    f,api,saved=await build(host,released=True);calls=[]
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
