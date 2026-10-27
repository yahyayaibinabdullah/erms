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


@pytest.mark.asyncio
@pytest.mark.parametrize('state',['queued','running','failed'])
async def test_digital_task_exposes_automatic_certificate_progress_and_certificate_only_retry(host,monkeypatch,state):
    from frontend.webui.disposition.review import ReviewForm
    from frontend.webui.tests.test_disposition_tasks import view
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    value=view(actions=('retry_certificate',) if state=='failed' else ())
    value['job'].update(workflow_stage='digital_destruction',lifecycle_state='active')
    value['task'].update(task_type='digital_destruction',workflow_stage='digital_destruction')
    value['destruction']={'progress':dict(state='succeeded',overall_completed_units=1,overall_total_units=1,queued_units=0,running_units=0,failed_units=0)}
    value['completion']={'completed':False,'progress':{'state':state,'last_error_code':'disposition_certificate_generation_failed' if state=='failed' else None}}
    async def after(*a):pass
    with host:
        form=ReviewForm(api=Api(),workspace=value,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=after,format_timestamp=str,open_resource=None)
        await form.load()
        labels=[e.text for e in host.descendants() if isinstance(e,ui.label)]
        buttons=[e.text for e in host.descendants() if isinstance(e,ui.button)]
        assert text('digital_completion_failed' if state=='failed' else 'digital_completion_processing') in labels
        assert (text('retry_certificate') in buttons)==(state=='failed')
        assert not any(text(k) in buttons for k in ('destroy_digital','retry_digital'))
        assert text('digital_done_completion_pending') not in labels


@pytest.mark.asyncio
async def test_explicit_complete_returns_to_inbox_without_download(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    monkeypatch.setattr(ui,'timer',lambda *a,**k:SimpleNamespace(deactivate=lambda:None))
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    api=Api();returned=[]
    async def inbox():returned.append(True)
    async def after(result):raise AssertionError('Must return to My Tasks')
    with host:
        form=SimpleNamespace(api=api,view={'completion':{'completed':False,'progress':{'state':'succeeded'},'certificate':{'id':9,'can_download':False,'file_name':'saved.pdf'}}},host=host,alive=lambda:True,job={'id':7,'version':4},task={'id':8,'version':3,'task_type':'certificate_download'},actions={'complete_certificate'},retry={},busy=False,acting_role_id=2,on_submitted=inbox,after=after,error=lambda e:None)
        controls(form)
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('complete_this_task'))
        await click(button)
    assert returned==[True]
    assert api.writes[0][0]=='jobs/7/complete-certificate-task'
    assert api.writes[0][1]['task_version']==3
    assert api.writes[0][2]['reason']==''
    assert not api.reads
