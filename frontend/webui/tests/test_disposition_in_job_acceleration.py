"""Bilingual restoration confirmation preserves bounded concurrent reads."""
import asyncio
from types import SimpleNamespace
import pytest
from nicegui import ui
from frontend.webui.disposition import screens
from frontend.webui.disposition.messages import text
from frontend.webui.api_client import ApiError
from frontend.webui.tests.test_disposition_tasks import host


@pytest.mark.asyncio
async def test_acceleration_confirms_job_retention_and_review_requirements_without_more_reads(host,monkeypatch):
    calls=[];started=asyncio.Event();captured={}
    async def request(path,**params):
        calls.append(path)
        if len(calls)==2:started.set()
        await asyncio.wait_for(started.wait(),1)
        return {'roles':[]} if path=='context' else {'version':4,'eligible_status':2}
    async def dialog(**options):
        captured.update(options)
        with host:assert options['build'](lambda:True)()=={}
    monkeypatch.setattr(screens,'command_dialog',dialog)
    with host:
        await screens.accelerate_dialog(api=SimpleNamespace(disposition_page=request),root={'id':7,'aggregation_number':'AGG-7','title':'Reopened'},active=lambda:True,on_error=str,after=lambda _:None)
        labels=[e.text for e in host.descendants() if isinstance(e,ui.label)]
        assert text('accelerate_existing_job') in labels
        assert captured['path']=='aggregations/7/accelerate' and captured['version']==4
        assert sorted(calls)==['aggregations/7/eligibility','context']
        assert screens.failure(ApiError(409,{'code':'disposition_acceleration_state_invalid'}),lambda _:'Generic conflict')==text('disposition_acceleration_state_invalid')
        assert text('reopened')!= 'Reopened — must be removed from this job'
