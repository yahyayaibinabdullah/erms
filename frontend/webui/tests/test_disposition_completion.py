"""Certificate recovery, post-completion controls and abandoned progress reads."""
import asyncio
from types import SimpleNamespace
import pytest
from nicegui import ui,core
from frontend.webui.tests.test_disposition_tasks import host,Api
from frontend.webui.tests.test_disposition_external import click
from frontend.webui.disposition.completion import controls
from frontend.webui.disposition.messages import text


def build(host,value,alive=lambda:True):
    api=Api();saved=[]
    async def after(result):saved.append(result)
    with host:
        form=SimpleNamespace(api=api,view={'completion':value},host=host,alive=alive,job={'id':7,'version':4},task={'id':8,'version':3},actions={'retry_certificate'},retry={},busy=False,after=after,error=lambda e:None)
        form.acting_role_id=2
        controls(form)
    return form,saved


@pytest.mark.asyncio
async def test_retry_only_certificate_reuses_submission_identity(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    form,saved=build(host,{'completed':False,'progress':{'state':'failed','last_error_code':'disposition_certificate_generation_failed'}})
    button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('retry_certificate'))
    with host:await click(button);await click(button)
    assert len(form.api.writes)==2 and form.api.writes[0]==form.api.writes[1]
    assert form.api.writes[0][0]=='jobs/7/retry-certificate' and saved
    assert 'confirmed' not in form.api.writes[0][1]


def test_completed_job_has_external_copies_warning_and_saved_download(host,monkeypatch):
    monkeypatch.setattr(ui,'timer',lambda *a,**k:SimpleNamespace(deactivate=lambda:None))
    build(host,{'completed':True,'progress':{'state':'succeeded'},'certificate':{'id':9,'can_download':True,'file_name':'saved.pdf'}})
    assert any(isinstance(e,ui.label) and e.text==text('completion_external_copies_warning') for e in host.descendants())
    assert any(isinstance(e,ui.button) and e.text==text('download_digital_certificate') for e in host.descendants())
    assert not any(isinstance(e,ui.button) and e.text==text('retry_certificate') for e in host.descendants())


@pytest.mark.asyncio
async def test_abandoned_progress_response_cannot_reload(host,monkeypatch):
    timers=[]
    class Timer:
        def __init__(self,interval,callback,active=True):self.callback=callback;self.active=active;timers.append(self)
        def deactivate(self):self.active=False
    monkeypatch.setattr(ui,'timer',Timer);state={'alive':True}
    form,saved=build(host,{'completed':False,'progress':{'state':'running'}},alive=lambda:state['alive'])
    async def read(*a,**kw):state['alive']=False;return {'completed':True,'progress':{'state':'succeeded'}}
    form.api.disposition_page=read
    await timers[0].callback()
    assert not saved and not timers[0].active


@pytest.mark.asyncio
async def test_certificate_task_exposes_email_history_before_download(host,monkeypatch):
    from frontend.webui.disposition.review import ReviewForm
    from frontend.webui.tests.test_disposition_tasks import view
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    value=view(actions=());value['job'].update(workflow_stage='certificate_generation',lifecycle_state='completed')
    value['task'].update(task_type='certificate_download',workflow_stage='certificate_generation')
    async def after(*a):pass
    with host:
        form=ReviewForm(api=Api(),workspace=value,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=after,format_timestamp=str,open_resource=None)
        await form.load()
    assert any(isinstance(e,ui.expansion) and e.text==text('email_attempts') for e in host.descendants())
    assert not any(path.endswith('review-work') for path,_ in form.api.reads)
