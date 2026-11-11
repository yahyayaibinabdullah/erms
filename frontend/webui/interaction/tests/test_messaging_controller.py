"""Mailbox controller routing, permissions and resource/disposition callbacks."""
import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from nicegui import ui
from frontend.webui import app as host
pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

def build(h,monkeypatch):
    from frontend.webui import messaging_controller as owner
    for name in ('messaging_workspace','messaging_monitor','notification_administration','resource_inspector'):
        monkeypatch.setattr(owner,name,h[name])
    h.update(get_principal=lambda:h['auth_state'].get('principal'),get_resource=lambda:h['state'].get('resource'),enter_messages=lambda key:h['state'].update(resource=key),messaging_state=h['state'])
    return owner.build_messaging_controller(**{key:h[key] for key in inspect.signature(owner.build_messaging_controller).parameters})

async def setup(user,monkeypatch,mailbox='inbox',privileges=None):
    privileges=['messaging.user_messages.exchange','messaging.monitor','messaging.notifications.administer','record.create','organization.browse'] if privileges is None else privileges
    h=dict(vars(host),state={},auth_state={'principal':{'global_privileges':privileges}},collection_state={},aggregation_state={},api=SimpleNamespace(get=AsyncMock(side_effect=lambda resource,identity:{'id':identity,'record_id':8})),localized_navigation={'messages-'+key:key for key in ('inbox','outbox','drafts','monitor','notifications')},show_authenticated_view=Mock(),register_navigation=Mock(),format_timestamp=str,error_message=str,bind_remote_relationship_select=Mock())
    for key in ('preview_record_components','open_aggregation','show_record_details','open_record_draft_editor','select_audit_trail','select_disposition','show_organization_structure','refresh_message_unread','resource_inspector','messaging_monitor','notification_administration'):h[key]=AsyncMock()
    h['messaging_workspace']=AsyncMock(return_value={'open':AsyncMock(),'refresh':AsyncMock()})
    async def guarded(action):return await action()
    h['guarded_page_navigation']=AsyncMock(side_effect=guarded)
    @ui.page('/mailbox-controller-contract')
    async def page():
        for key in ('title','subtitle','guidance'):h[key]=ui.label('')
        for key in ('search_bar','aggregation_mode_bar','add_button','add_record_button','table_container'):h[key]=ui.column()
        h['open']=build(h,monkeypatch);await h['open'](mailbox)
    await user.open('/mailbox-controller-contract');return h

@pytest.mark.parametrize('mailbox,consumer',[('inbox','messaging_workspace'),('outbox','messaging_workspace'),('drafts','messaging_workspace'),('monitor','messaging_monitor'),('notifications','notification_administration')])
async def test_existing_mailboxes_dispatch_once_with_current_owner(user,monkeypatch,mailbox,consumer):
    h=await setup(user,monkeypatch,mailbox);h[consumer].assert_awaited_once();c=h[consumer].await_args.kwargs
    assert c['active']() and h['state']['resource']=='messages-'+mailbox
    assert all(not h[key].visible for key in ('search_bar','aggregation_mode_bar','add_button','add_record_button'))
    h['auth_state']['principal']=dict(h['auth_state']['principal']);assert not c['active']()

@pytest.mark.parametrize('mailbox',['monitor','notifications'])
async def test_denied_administration_does_not_replace_workspace(user,monkeypatch,mailbox):
    h=await setup(user,monkeypatch,mailbox,privileges=[]);assert h['state']=={};h['register_navigation'].assert_not_called()

async def test_inbox_without_exchange_capture_or_browse_keeps_existing_capabilities(user,monkeypatch):
    h=await setup(user,monkeypatch,privileges=[]);c=h['messaging_workspace'].await_args.kwargs
    assert not c['can_exchange'] and c['capture_record'] is None and c['browse_recipients'] is None

@pytest.mark.parametrize('kind',['aggregation','record','digital_component'])
async def test_link_open_uses_current_resource_fetch_and_existing_destination(user,monkeypatch,kind):
    h=await setup(user,monkeypatch);c=h['messaging_workspace'].await_args.kwargs
    await c['open_resource'](kind,3)
    if kind=='aggregation':h['open_aggregation'].assert_awaited_once_with({'id':3,'record_id':8})
    elif kind=='record':h['show_record_details'].assert_awaited_once_with({'id':3,'record_id':8})
    else:
        h['api'].get.assert_any_await('digital-components',3);h['api'].get.assert_awaited_with('records',8);h['show_record_details'].assert_awaited_once_with({'id':8,'record_id':8})

async def test_disposition_links_keep_existing_guard_and_selected_ids(user,monkeypatch):
    h=await setup(user,monkeypatch);c=h['messaging_workspace'].await_args.kwargs
    await c['open_disposition_eligibility']();h['select_disposition'].assert_awaited_with('disposition-eligibility')
    await c['open_disposition_job'](7);h['select_disposition'].assert_awaited_with('disposition-job',7)
    await c['open_disposition_task'](7,9);h['select_disposition'].assert_awaited_with('disposition-job',7,task_id=9)
    assert h['guarded_page_navigation'].await_count==3
