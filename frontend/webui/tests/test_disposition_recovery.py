"""Native EN/AR recovery forms: explicit scope, warnings, exact retries and abandonment."""
import asyncio
import pytest
from nicegui import ui,core
from frontend.webui.tests.test_disposition_tasks import host,Api
from frontend.webui.tests.test_disposition_external import click
from frontend.webui.disposition.recovery import controls,resolve_unit
from frontend.webui.disposition.messages import text,status_label
from frontend.webui.api_client import ApiError


def build(host,*,active_job=False,active=lambda:True):
    api=Api();saved=[]
    async def after(result):saved.append(result)
    job={'id':5,'version':3,'lifecycle_state':'active' if active_job else 'terminated'}
    value={'roles':[{'id':7,'name':'Governance role'}],'physical_confirmed':True,'can_terminate':active_job,'can_resolve_bulk':not active_job}
    with host:controls(api=api,job=job,value=value,active=active,on_error=str,after=after)
    return api,saved,job,after


@pytest.mark.asyncio
async def test_bulk_requires_status_confirmation_and_reason_and_keeps_exact_retry(host,monkeypatch):
    notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**kw:notices.append(kw));monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    api,saved,job,_=build(host);reads=[]
    async def preview(path,**kw):reads.append(path);return {'affected_count':2,'scope_token':'a'*32}
    api.disposition_page=preview
    assert not reads
    with host:
        await click(next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('recover_all')))
        assert reads==['jobs/5/partial-recovery-preview']
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog))
        save=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        await click(save);assert not api.writes and notices[-1]['type']=='warning'
        status=next(e for e in dialog.descendants() if isinstance(e,ui.select) and 2 in e.options);status.value=4
        check=next(e for e in dialog.descendants() if isinstance(e,ui.checkbox));check.value=True
        await click(save);assert not api.writes
        reason=next(e for e in dialog.descendants() if isinstance(e,ui.textarea));reason.value='Treat the remaining material under the selected action'
        api.error=ApiError(409,{'code':'disposition_recovery_stale'})
        await click(save);assert dialog.value and notices[-1]['type']=='negative'
        api.error=None;await click(save)
    assert api.writes[0]==api.writes[1]
    payload=api.writes[1][1]
    assert payload['affected_count']==2 and payload['target_status']==4 and payload['confirmed'] and payload['scope_token']=='a'*32
    assert saved and notices[-1]['type']=='positive'


@pytest.mark.asyncio
async def test_termination_requires_confirmation_and_preserves_warning(host,monkeypatch):
    notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**kw:notices.append(kw));monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    api,saved,job,_=build(host,active_job=True)
    assert any(e.text==text('physical_recovery_warning') for e in host.descendants() if isinstance(e,ui.label))
    with host:
        await click(next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('terminate_job')))
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog))
        save=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        reason=next(e for e in dialog.descendants() if isinstance(e,ui.textarea));reason.value='Cannot continue the approved physical scope'
        await click(save);assert not api.writes
        next(e for e in dialog.descendants() if isinstance(e,ui.checkbox)).value=True
        await click(save)
    assert api.writes[0][0]=='jobs/5/terminate' and api.writes[0][1]['confirmed'] and saved


@pytest.mark.asyncio
async def test_single_resolution_has_no_implicit_status_and_targets_one_version(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**kw:None)
    api,saved,job,after=build(host)
    with host:
        await resolve_unit(api=api,job=job,row={'identity':'ROOT-9','root_aggregation_id':9,'root_version':13},roles=[{'id':7,'name':'Governance role'}],active=lambda:True,on_error=str,after=after)
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog))
        status=next(e for e in dialog.descendants() if isinstance(e,ui.select) and 2 in e.options);assert status.value is None
        status.value=5;next(e for e in dialog.descendants() if isinstance(e,ui.textarea)).value='Preserve in local archives'
        await click(next(e for e in dialog.descendants() if isinstance(e,ui.button) and e.text==text('save')))
    assert api.writes[0][0]=='jobs/5/partial-recovery/9' and api.writes[0][1]['root_version']==13 and api.writes[0][1]['target_status']==5


@pytest.mark.asyncio
async def test_abandoned_preview_does_not_open_dialog(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());state={'alive':True}
    api,*_=build(host,active=lambda:state['alive'])
    async def preview(*a,**kw):state['alive']=False;return {'affected_count':2,'scope_token':'a'*32}
    api.disposition_page=preview
    with host:await click(next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('recover_all')))
    assert not any(isinstance(e,ui.dialog) for e in host.descendants()) and not api.writes
