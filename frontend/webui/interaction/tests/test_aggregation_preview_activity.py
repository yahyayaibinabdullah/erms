"""Successful child previews refresh the batched activity projection only."""
import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nicegui import ui
from nicegui.client import Client

from frontend.webui.aggregation_recent_activity import AggregationRecentActivity
from frontend.webui.api_client import ApiError
from frontend.webui.compact_resource_view import build_compact_resource_view
from frontend.webui.component_preview import build_component_preview
from frontend.webui.component_presentation import component_is_previewable
from frontend.webui.locale_services import set_locale_context

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1cAAAAASUVORK5CYII=')

class JSResult:
    def __await__(self):
        async def result():return True
        return result().__await__()

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('entry', ['record', 'component'])
@pytest.mark.parametrize('outcome', ['image', 'pdf', 'failed', 'abandoned'])
async def test_preview_refreshes_activity_after_success_without_row_lookups(user, monkeypatch, entry, outcome):
    monkeypatch.setattr(Client, 'run_javascript', lambda *args, **kwargs: JSResult())
    active = [True]
    component = dict(id=12, record_id=7, file_name='scan.png', mime_type='application/pdf' if outcome=='pdf' else 'image/png',
                     content_status='available', component_order=1)
    created = dict(id=7, title='Child record', record_number='R-7', _operation='CREATE', _activity_at='2026-11-17')
    api = SimpleNamespace(
        recent_resource_activity=AsyncMock(return_value=[created]), get=AsyncMock(),
        resource_capabilities=AsyncMock(return_value={'list_components':True,'view_component':True}),
        previewable_component_page=AsyncMock(return_value={'items':[component],'total':1,'offset':0}),
    )
    async def rendition(*_):
        if outcome=='failed':raise ApiError(403, 'Denied')
        if outcome=='abandoned':active[0]=False
        api.recent_resource_activity.return_value=[{**created, '_operation':'CONTENT_VIEWED'}]
        return '/preview-pdf/fixture' if outcome=='pdf' else PNG
    api.open_original_pdf=AsyncMock(side_effect=rendition)
    api.view_component_pdf=AsyncMock(side_effect=rendition)
    state={}
    @ui.page('/aggregation-preview')
    async def page():
        set_locale_context('en','UTC')
        panel=AggregationRecentActivity(api=api,aggregation_id=3,active=lambda:active[0],
             configuration={'DASHBOARD_RECENT_DAYS':30,'DASHBOARD_RECENT_ITEM_LIMIT':4},format_timestamp=str,
             show_record_details=AsyncMock(),error_message=str)
        state['panel']=panel
        await panel.load()
        render=build_compact_resource_view(tree_expander_icon=lambda _: 'expand_more', favourite_button=lambda *_:None,
              render_safe_snippet=lambda *_:None, preview_record_components=build_component_preview(api=api,error_message=str),
              format_date=str,medium_label=str,component_is_previewable=component_is_previewable,
              api=api,direction=lambda:'ltr',error_message=str)
        render('records',created,on_open=None,can_favourite=False,can_preview=True,
               components=[component],components_are_matches=True,can_expand_components=True,initially_expanded=True,
               contained_record=True,on_component_viewed=panel.load,source_active=lambda:active[0])
    await user.open('/aggregation-preview')
    buttons=[e for e in user.client.elements.values() if isinstance(e,ui.button) and e._props.get('icon')=='visibility']
    button=buttons[0 if entry=='record' else 1]
    button.mark('preview-child');user.find(marker='preview-child').click()
    await asyncio.sleep(.15)
    success=outcome in {'image','pdf'}
    assert api.recent_resource_activity.await_count==(2 if success else 1)
    assert state['panel'].items[0]['_operation']==('CONTENT_VIEWED' if success else 'CREATE')
    api.get.assert_not_awaited()
    if success:
        with user:state['panel'].show_all()
        assert api.recent_resource_activity.await_count==2
        api.get.assert_not_awaited()


async def test_staged_preview_does_not_refresh_saved_activity(user):
    api=SimpleNamespace(view_draft_component=AsyncMock(return_value=PNG))
    viewed=AsyncMock()
    @ui.page('/staged-preview-activity')
    async def page():
        set_locale_context('en','UTC')
        await build_component_preview(api=api,error_message=str)(None,draft_id=1,
            staged_components=[dict(id=1,file_name='draft.png',mime_type='image/png',content_status='staged',component_order=1)],
            on_viewed=viewed)
    await user.open('/staged-preview-activity')
    api.view_draft_component.assert_awaited_once()
    viewed.assert_not_awaited()
