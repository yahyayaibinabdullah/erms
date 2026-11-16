"""Mailbox controller routing, permissions and resource/disposition callbacks."""
import ast
import asyncio
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
    return owner.build_messaging_controller(**{key:h[key] for key in inspect.signature(owner.build_messaging_controller).parameters if key in h})

async def setup(user,monkeypatch,mailbox='inbox',privileges=None,load_page_size=None):
    privileges=['messaging.user_messages.exchange','messaging.monitor','messaging.notifications.administer','record.create','organization.browse'] if privileges is None else privileges
    principal = {'user': {'id': 7}, 'session': {'id': 'login-1'}, 'global_privileges': privileges}
    h=dict(vars(host),state={},auth_state={'principal':principal},collection_state={},aggregation_state={},api=SimpleNamespace(get=AsyncMock(side_effect=lambda resource,identity:{'id':identity,'record_id':8})),localized_navigation={'messages-'+key:key for key in ('inbox','outbox','drafts','monitor','notifications')},show_authenticated_view=Mock(),register_navigation=Mock(),format_timestamp=str,error_message=str,bind_remote_relationship_select=Mock())
    for key in ('preview_record_components','open_aggregation','show_record_details','open_record_draft_editor','select_audit_trail','select_disposition','show_organization_structure','refresh_message_unread','resource_inspector','messaging_monitor','notification_administration'):h[key]=AsyncMock()
    h['messaging_workspace']=AsyncMock(return_value={'open':AsyncMock(),'refresh':AsyncMock()})
    if load_page_size is not None:
        h['load_page_size'] = load_page_size
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
    h['auth_state']['principal'] = dict(h['auth_state']['principal'])
    assert c['active']() == (consumer == 'messaging_workspace')


async def test_abandoned_settings_request_cannot_replace_the_current_mailbox(user, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    configured_size = AsyncMock(return_value=25)
    h = await setup(user, monkeypatch, load_page_size=configured_size)

    async def delayed_size():
        started.set()
        await release.wait()
        return 25

    configured_size.side_effect = delayed_size
    task = asyncio.create_task(h['open']('outbox'))
    await asyncio.wait_for(started.wait(), 1)
    configured_size.side_effect = None
    configured_size.return_value = 10
    await h['open']('drafts')
    release.set()
    await task
    mounted = h['messaging_workspace'].await_args_list
    assert [(c.kwargs['mailbox'], c.kwargs['page_size']) for c in mounted] == [('inbox', 25), ('drafts', 10)]
    assert mounted[-1].kwargs['active']()


@pytest.mark.parametrize('changed', [
    None,
    {'user': {'id': 8}},
    {'session': {'id': 'login-2'}},
    {'global_privileges': []},
])
async def test_personal_mailbox_rejects_callbacks_after_its_login_or_capabilities_change(user, monkeypatch, changed):
    h = await setup(user, monkeypatch)
    workspace = h['messaging_workspace'].await_args.kwargs
    h['auth_state']['principal'] = (
        None if changed is None else {**h['auth_state']['principal'], **changed}
    )
    assert not workspace['active']()
    await workspace['navigate_mailbox']('drafts')
    h['guarded_page_navigation'].assert_not_awaited()

@pytest.mark.parametrize('mailbox',['monitor','notifications'])
async def test_denied_administration_does_not_replace_workspace(user,monkeypatch,mailbox):
    h=await setup(user,monkeypatch,mailbox,privileges=[]);assert h['state']=={};h['register_navigation'].assert_not_called()

async def test_inbox_without_exchange_capture_or_browse_keeps_existing_capabilities(user,monkeypatch):
    h=await setup(user,monkeypatch,privileges=[]);c=h['messaging_workspace'].await_args.kwargs
    assert not c['can_exchange'] and c['capture_record'] is None and c['browse_recipients'] is None

@pytest.mark.parametrize('kind', ['aggregation', 'record', 'digital_component'])
async def test_link_opens_the_authorized_contents_or_direct_preview(user, monkeypatch, kind):
    h = await setup(user, monkeypatch)
    workspace = h['messaging_workspace'].await_args.kwargs
    active = workspace['active']
    await workspace['open_resource'](kind, 3, active)
    h['resource_inspector'].assert_not_awaited()
    if kind == 'aggregation':
        h['api'].get.assert_awaited_once_with('aggregations', 3)
        h['open_aggregation'].assert_awaited_once_with({'id': 3, 'record_id': 8}, from_authorized_read=True)
        h['preview_record_components'].assert_not_awaited()
    elif kind == 'record':
        h['api'].get.assert_not_awaited()
        h['preview_record_components'].assert_awaited_once_with({'id': 3}, source_active=active)
    else:
        h['api'].get.assert_awaited_once_with('digital-components', 3)
        h['preview_record_components'].assert_awaited_once_with(
            {'id': 8}, initial_component_id=3, source_active=active,
        )


async def test_aggregation_link_checks_its_message_again_after_authorized_read(user, monkeypatch):
    h = await setup(user, monkeypatch)
    workspace = h['messaging_workspace'].await_args.kwargs
    current = True

    async def read(*_):
        nonlocal current
        current = False
        return {'id': 3}

    h['api'].get.side_effect = read
    await workspace['open_resource']('aggregation', 3, lambda: current)
    h['open_aggregation'].assert_not_awaited()
    h['guarded_page_navigation'].assert_not_awaited()

async def test_disposition_links_keep_existing_guard_and_selected_ids(user,monkeypatch):
    h=await setup(user,monkeypatch);c=h['messaging_workspace'].await_args.kwargs
    await c['open_disposition_eligibility']();h['select_disposition'].assert_awaited_with('disposition-eligibility')
    await c['open_disposition_job'](7);h['select_disposition'].assert_awaited_with('disposition-job',7)
    await c['open_disposition_task'](7,9);h['select_disposition'].assert_awaited_with('disposition-job',7,task_id=9)
    assert h['guarded_page_navigation'].await_count==3


async def test_mailbox_shortcuts_keep_submitted_position_and_check_current_identity(user, monkeypatch):
    h = await setup(user, monkeypatch)
    inbox = h["messaging_workspace"].await_args.kwargs
    inbox["mailbox_position"].update(cursor="page-two", criteria={"is_read": "false"})

    h["auth_state"]["principal"] = {**h["auth_state"]["principal"], "previous_login_at": None}
    await inbox["navigate_mailbox"]("outbox", "sent-id")
    outbox = h["messaging_workspace"].await_args.kwargs
    assert outbox["initial_item"] == "sent-id"
    assert outbox["mailbox_position"] == {}
    assert not inbox["active"]()

    await inbox["navigate_mailbox"]("drafts", "stale-id")
    assert h["messaging_workspace"].await_count == 2
    await outbox["navigate_mailbox"]("inbox")
    restored = h["messaging_workspace"].await_args.kwargs
    assert restored["mailbox_position"] == {"cursor": "page-two", "criteria": {"is_read": "false"}}

    h["auth_state"]["principal"] = {**h["auth_state"]["principal"], "global_privileges": []}
    await h["open"]("outbox", initial_item="foreign-id")
    assert h["messaging_workspace"].await_count == 3
    await h["open"]("inbox")
    assert h["messaging_workspace"].await_args.kwargs["mailbox_position"] == {}
