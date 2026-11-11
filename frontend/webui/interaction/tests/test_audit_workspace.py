"""The audit owner keeps each root-page client's pending reads independent."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import ui
from nicegui.testing import User

from frontend.webui.audit_workspace import build_audit_workspace

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
