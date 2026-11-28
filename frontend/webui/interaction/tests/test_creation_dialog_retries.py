"""Actual draft dialog: blank generated fields and lost final response."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nicegui import ui

from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message as t
from frontend.webui.locale_services import set_locale_context
from frontend.webui.record_capture import build_record_capture
from frontend.webui.resource_number_controls import build_number_controls

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


async def test_lost_draft_response_retries_original_commit_without_updating_a_deleted_draft(user):
    calls=[]
    parent={'id':7,'aggregation_number':'A7','title':'Parent','owning_org_unit_id':1,
            'security_level_id':1,'medium':'mixed'}
    async def commit(draft_id,role,**kwargs):
        calls.append((draft_id,role,kwargs))
        if len(calls)==1:
            raise ApiError(503,'Response lost after creation')
        return {'id':71,'record_number':'R10','title':'T10'}
    api=SimpleNamespace(
        create_record_draft=AsyncMock(return_value={'id':99}),
        list=AsyncMock(return_value=[{'id':1,'name':'General','level_number':0}]),
        creation_role_options=AsyncMock(return_value=[{'role_id':1,'org_unit_id':1,'label':'Creator'}]),
        get=AsyncMock(return_value=parent),draft_components=AsyncMock(return_value=[]),
        request=AsyncMock(return_value=[]), update_record_draft=AsyncMock(),
        commit_record_draft=AsyncMock(side_effect=commit),discard_record_draft=AsyncMock(),
        code_generation_bindings=AsyncMock(return_value={'total':2,'items':[
            {'generator_id':1,'primary_field':'record_number','field_id':None},
            {'generator_id':2,'primary_field':'title','field_id':None}]}))
    committed=AsyncMock()
    @ui.page('/draft-retry')
    async def page():
        set_locale_context("en", "Asia/Dubai")
        number=build_number_controls(api,show_api_error=lambda e:ui.notify(str(e)))
        open_editor=build_record_capture(add_number_suggestion=number.add_number_suggestion,
            api=api,bind_remote_relationship_select=lambda *a,**k:None,
            bind_resource_security_select=lambda *a,**k:None,browse_advanced_aggregation=AsyncMock(),
            error_message=str,load_recent=AsyncMock(),preview_record_components=AsyncMock(),
            render_component_cards=lambda *a,**k:None,render_table=lambda *a:None,
            set_searched=lambda *a:None,show_number_conflict=number.show_number_conflict,
            validation_error_message=str)
        await open_editor(7,on_committed=committed)
    await user.open('/draft-retry')
    user.find(t('webui.open_record_draft_editor.button.create_record_dd0193d6')).click()
    await user.should_see(t('code_generation.action.retry_original'))
    assert api.update_record_draft.await_count==1
    assert len(calls)==1
    fields=[e for e in user.client.elements.values() if isinstance(e,ui.input)]
    assert fields and all(not e.enabled for e in fields)
    user.find(t('code_generation.action.retry_original')).click()
    for _ in range(50):
        if committed.called:break
        await asyncio.sleep(.01)
    committed.assert_awaited_once_with({'id':71,'record_number':'R10','title':'T10'})
    assert calls[0]==calls[1]
    assert api.update_record_draft.await_count==1
    saved=api.update_record_draft.call_args.args[1]
    assert saved['aggregation_id']==7 and saved['record_number'] is None and saved['title'] is None
