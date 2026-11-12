"""Aggregation reopen and ownership-correction contracts."""
from frontend.webui.i18n_catalogue import strip_diagnostic_metadata as _owner_strip_diagnostic_metadata
import ast,asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from nicegui import ui
from frontend.webui import app as host
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

def build(name,values):
    from frontend.webui.aggregation_actions import build_aggregation_actions
    actions=build_aggregation_actions(api=values['api'],error_message=host.error_message,bind_remote_relationship_select=values.get('bind_remote_relationship_select',Mock()))
    return dict(zip(('show_reopen_aggregation','show_governed_move','show_ownership_correction'),actions))[name]

def click(user,label):
    button=next(b for b in user.find(ui.button).elements if _owner_strip_diagnostic_metadata(b.text)==label)
    button.mark(f'aggregation-action-{button.id}');user.find(marker=f'aggregation-action-{button.id}').click()
async def settle():await asyncio.sleep(.1)

@pytest.mark.parametrize('failure',[False,True])
async def test_reopen_requires_reason_preserves_version_and_handles_failure(user,failure):
    api=SimpleNamespace(update=AsyncMock(return_value={'id':7,'version':5,'date_closed':None}))
    if failure:api.update.side_effect=ApiError(409,'Conflict')
    saved=AsyncMock()
    @ui.page('/reopen-contract')
    async def page():await build('show_reopen_aggregation',{'api':api})({'id':7,'version':4},saved)
    await user.open('/reopen-contract')
    click(user,t('webui.show_reopen_aggregation.button.reopen_3a12b38d'));await settle();api.update.assert_not_awaited()
    with user:next(iter(user.find(ui.textarea).elements)).value='  Approved reopening  '
    click(user,t('webui.show_reopen_aggregation.button.reopen_3a12b38d'));await settle()
    api.update.assert_awaited_once_with('aggregations',7,4,{'date_closed':None},change_reason='Approved reopening')
    assert any(d.value for d in user.find(ui.dialog).elements)==failure
    assert saved.await_count==(0 if failure else 1)

@pytest.mark.parametrize('failure',['none','options','preview','write'])
async def test_ownership_correction_filters_current_owner_and_preserves_preview_gate(user,failure):
    api=SimpleNamespace(ownership_correction_options=AsyncMock(return_value=[{'role_id':1,'org_unit_id':10,'label':'Current'},{'role_id':2,'org_unit_id':20,'label':'New owner'}]),ownership_correction_preview=AsyncMock(return_value={'affected_aggregation_count':2,'affected_record_count':3,'creator_role_grant_count':1}),correct_ownership=AsyncMock(return_value={'id':7,'owning_org_unit_id':20}))
    for stage,method in [('options','ownership_correction_options'),('preview','ownership_correction_preview'),('write','correct_ownership')]:
        if failure==stage:getattr(api,method).side_effect=ApiError(403,'Denied')
    saved=AsyncMock()
    @ui.page('/ownership-contract')
    async def page():
        ui.label('Fixture host')
        await build('show_ownership_correction',{'api':api})({'id':7,'owning_org_unit_id':10},saved)
    await user.open('/ownership-contract')
    if failure=='options':
        assert not any(isinstance(d,ui.dialog) and d.value for d in user.client.elements.values());api.correct_ownership.assert_not_awaited();return
    destination=next(iter(user.find(ui.select).elements));assert destination.options=={2:'New owner'}
    click(user,t('webui.show_ownership_correction.button.confirm_correction_3bd277b6'));await settle();api.correct_ownership.assert_not_awaited()
    with user:destination.value=2;next(iter(user.find(ui.textarea).elements)).value='  Correct fixture ownership  '
    await settle();api.ownership_correction_preview.assert_awaited_once_with(7,2)
    click(user,t('webui.show_ownership_correction.button.confirm_correction_3bd277b6'));await settle()
    if failure=='preview':
        api.correct_ownership.assert_not_awaited();assert api.ownership_correction_preview.await_count==2
    else:api.correct_ownership.assert_awaited_once_with(7,2,'Correct fixture ownership')
    assert any(d.value for d in user.find(ui.dialog).elements)==(failure!='none')
    assert saved.await_count==(1 if failure=='none' else 0)
