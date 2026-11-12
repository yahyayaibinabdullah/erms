"""The audit owner keeps each root-page client's pending reads independent."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import ui
from nicegui.testing import User

from frontend.webui.audit_workspace import build_audit_workspace
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


async def test_workspace_revisions_are_independent(user: User):
    entered, release = asyncio.Event(), asyncio.Event()
    options = dict(entity_types=[], operations=[], sources=[], actor_types=[])
    workspaces = []

    async def slow_options():
        entered.set()
        await release.wait()
        return options

    first = SimpleNamespace(event_history_filter_options=AsyncMock(side_effect=slow_options),
                            search_request=AsyncMock(return_value={'items': [], 'total': 0}))
    second = SimpleNamespace(event_history_filter_options=AsyncMock(return_value=options),
                             search_request=AsyncMock(return_value={'items': [], 'total': 0}))

    @ui.page('/audit-independent-revisions')
    def page():
        for api in (first, second):
            workspaces.append(build_audit_workspace(
                api=api, table_container=ui.column(), principal=lambda:None, selected=lambda:True,
                enter=Mock(), error_message=str, format_timestamp=str, set_connection_status=Mock(),
                can_open_settings=lambda:False, open_settings=AsyncMock(), open_destination=AsyncMock(),
            ))

    await user.open('/audit-independent-revisions')
    with user:
        pending = asyncio.create_task(workspaces[0].select_audit_trail())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await workspaces[1].select_audit_trail()
            release.set()
            await pending
            first.search_request.assert_awaited_once()
            second.search_request.assert_awaited_once()
        finally:
            release.set()
            await pending


async def test_pagination_uses_applied_audit_filters_until_apply_or_clear(user: User):
    api = SimpleNamespace(
        event_history_filter_options=AsyncMock(return_value=dict(entity_types=[], operations=[], sources=[], actor_types=[])),
        search_request=AsyncMock(return_value={'items': [], 'total': 100}),
    )

    @ui.page('/audit-applied-filters')
    async def page():
        workspace = build_audit_workspace(
            api=api, table_container=ui.column(), principal=lambda:None, selected=lambda:True,
            enter=Mock(), error_message=str, format_timestamp=str, set_connection_status=Mock(),
            can_open_settings=lambda:False, open_settings=AsyncMock(), open_destination=AsyncMock(),
        )
        await workspace.select_audit_trail(initial_entity_type='record')

    async def click(key):
        user.find(t(key)).click()
        await asyncio.sleep(.1)

    await user.open('/audit-applied-filters')
    original = '66666666-6666-4666-8666-666666666666'
    draft = '77777777-7777-4777-8777-777777777777'
    field = next(i for i in user.find(ui.input).elements
                 if i.label == t('webui.select_audit_trail.input.correlation_id_e6872415'))
    with user:
        field.value = original
    apply = 'webui.select_audit_trail.button.apply_filters_bf49489c'
    await click(apply)
    applied = api.search_request.await_args.args[1]
    assert applied['offset'] == 0
    assert applied['where']['and'][1]['value'] == original

    with user:
        field.value = draft
    await click('webui.select_audit_trail.button.next_4982f418')
    api.search_request.assert_awaited_with('event-history', {**applied, 'offset': 50})
    assert field.value == draft
    await click('webui.select_audit_trail.button.previous_928715e5')
    api.search_request.assert_awaited_with('event-history', applied)

    await click(apply)
    submitted = api.search_request.await_args.args[1]
    assert submitted['offset'] == 0 and submitted['where']['and'][1]['value'] == draft
    await click('audit.filter.clear')
    cleared = api.search_request.await_args.args[1]
    assert cleared['offset'] == 0
    assert cleared['where'] == {'field': 'entity_type', 'operator': 'eq', 'value': 'record'}
    assert field.value is None
