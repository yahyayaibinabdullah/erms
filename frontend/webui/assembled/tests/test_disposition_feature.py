"""Real root/controller create, job/task navigation and saved list state."""
import json
import os
import subprocess
from pathlib import Path
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,drawer_buttons,click_one,eventually,plain
from frontend.webui.disposition.messages import text as dt
from frontend.webui.i18n_catalogue import render_message_plain as t,strip_diagnostic_metadata
pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

async def test_disposition_create_job_task_and_return_use_real_api(assembled):
    root=Path(__file__).resolve().parents[4]
    seeded=subprocess.run([str(root/'backend/services/api/.venv/bin/python'),'-m','tools.seed_webui_disposition'],cwd=root,env=os.environ,check=True,capture_output=True,text=True)
    try:
        user=assembled;await login(user);api=user.api_clients[0]
        def label(key):return strip_diagnostic_metadata(dt(key))
        def buttons(key):return [e for e in user.client.elements.values() if isinstance(e,ui.button) and e.visible and plain(e)==label(key)]
        click_one(user,[b for b in drawer_buttons(user) if plain(b)==label('jobs')]);await eventually(lambda:current_page(user)=='disposition-jobs' and user.pending_requests==0 and bool(buttons('create')))
        click_one(user,buttons('create'));await eventually(lambda:any(isinstance(e,ui.dialog) and e.value for e in user.client.elements.values()))
        dialog=next(e for e in user.client.elements.values() if isinstance(e,ui.dialog) and e.value)
        owner=next(e for e in dialog.descendants() if isinstance(e,ui.select) and plain(e)==label('owner'))
        choices=(await api.disposition_page('selectors/owners',query='WebUI',job_type='destruction'))['items'];assert choices
        owner.set_options({choices[0]['id']:choices[0]['name']},value=choices[0]['id'])
        save=next(e for e in dialog.descendants() if isinstance(e,ui.button) and plain(e)==label('save'))
        await eventually(lambda:save.enabled and user.pending_requests==0)
        click_one(user,[save]);await eventually(lambda:current_page(user)=='disposition-job' and user.pending_requests==0 and bool(buttons('current_task')))
        jobs=await api.disposition_page('jobs',limit=25,offset=0);job=jobs['items'][0]
        assert job['lifecycle_state']=='active';await user.should_see(job['job_number'])
        click_one(user,buttons('current_task'));await eventually(lambda:current_page(user)=='disposition-task' and user.pending_requests==0 and bool(buttons('workspace_details')))
        click_one(user,[b for b in buttons('workspace_details') if b.props.get('icon')=='open_in_new']);await eventually(lambda:current_page(user)=='disposition-job' and user.pending_requests==0)
        click_one(user,[b for b in drawer_buttons(user) if plain(b)==label('my_tasks')]);await eventually(lambda:current_page(user)=='disposition-tasks' and user.pending_requests==0)
        assert any(row.get('job_number')==job['job_number'] for e in user.client.elements.values() if isinstance(e,ui.table) for row in e.rows)
        assert not user.api_failures
    finally:
        subprocess.run([str(root/'backend/services/api/.venv/bin/python'),'-m','tools.seed_webui_disposition','cleanup'],cwd=root,env=os.environ,check=True,input=seeded.stdout,capture_output=True,text=True)
