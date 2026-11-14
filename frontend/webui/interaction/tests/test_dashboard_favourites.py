"""Exercise favourite removal using the real dashboard factory and notifier."""
import asyncio
import copy
import gc
import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import Client, ui
from nicegui.functions.notify import notify as real_notify
from frontend.webui import dashboard
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import clear_active_messages, set_active_messages
from test_dashboard_identity import DashboardFixture, summary


def buttons(container, icon):
    return [e for e in container.descendants()
            if isinstance(e, ui.button) and e.props.get('icon') == icon]


def handler(button):
    return next(e.handler for e in button._event_listeners.values() if e.type == 'click')


@pytest.mark.asyncio
@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('resource', ['records', 'aggregations'])
@pytest.mark.parametrize('in_dialog', [False, True])
@pytest.mark.parametrize('outcome', ['success', 'last_item', 'rejected', 'abandoned'])
async def test_favourite_removal_feedback_cache_and_view_ownership(monkeypatch, language, resource, in_dialog, outcome):
    client = Client(ui.page('/dashboard-favourite-regression'), request=None)
    fixture = None
    notifications = []
    try:
        with client:
            messages = {r['message_key']: r['translated_text'] for r in json.loads(
                (Path(__file__).parents[2] / 'i18n/messages.ar.generated.json').read_text())['items']} if language == 'ar' else {}
            set_active_messages(messages)
            fixture = DashboardFixture(client)
            fixture.state['localization']['effective_language'] = language
            data = summary(2)
            data['favourites'][resource] = [
                {'id': i, 'title': f'Favourite {i}', 'record_number': f'R-{i}',
                 'aggregation_number': f'A-{i}'}
                for i in range(1, 2 if outcome == 'last_item' else 3)]
            fixture.api.dashboard_summary = AsyncMock(return_value=copy.deepcopy(data))
            fixture.api.unfavourite = AsyncMock()
            monkeypatch.setattr(dashboard, 'background_tasks', fixture.scope['background_tasks'])
            _, _, select = dashboard.build_dashboard(**{
                name: fixture.scope.get(name, Mock()) for name in inspect.signature(dashboard.build_dashboard).parameters})
            await select()
            if in_dialog:
                view_all = next(e for e in fixture.host.descendants() if isinstance(e, ui.button)
                                and e.text == dashboard.render_message('webui.render_favourites_dashboard.button.view_all_e1f7fcfb'))
                with view_all.parent_slot:
                    handler(view_all)(None)
                del view_all
                container = next(e for e in client.elements.values() if isinstance(e, ui.dialog) and e.value)
            else:
                container = fixture.host
            number_prefix = 'R' if resource == 'records' else 'A'
            for area in (fixture.host, container):
                identities = [e.text for e in area.descendants() if isinstance(e, ui.label)
                              and 'text-xs' in e.classes and 'truncate' in e.classes]
                assert dashboard.render_message('dashboard.resource.identity',
                    type=dashboard.render_message('dashboard.resource.record' if resource == 'records' else 'dashboard.resource.aggregation'),
                    number=f'{number_prefix}-1') in identities
            button = buttons(container, 'favorite')[0]
            slot, remove = button.parent_slot, handler(button)
            del button

            def notify(message, **kwargs):
                # Reproduce native event lifetime after rendering deletes its row.
                gc.collect()
                real_notify(message, **kwargs)
                notifications.append((str(message), kwargs.get('color')))
            monkeypatch.setattr(ui, 'notify', notify)

            async def unfavourite(kind, identifier):
                await asyncio.sleep(0)
                if outcome == 'rejected':
                    raise ApiError(409, 'Conflict')
                if outcome == 'abandoned':
                    fixture.state['resource'] = 'records'
                    fixture.host.clear()
            fixture.api.unfavourite.side_effect = unfavourite
            with slot:
                await remove(None)
            fixture.api.unfavourite.assert_awaited_once_with(resource, 1)
            fixture.api.dashboard_summary.assert_awaited_once()
            cached = fixture.state['dashboard_summary_cache']['favourites'][resource]
            if outcome in ('success', 'last_item'):
                expected = [] if outcome == 'last_item' else [2]
                assert [e['id'] for e in cached] == expected
                assert fixture.personal.favourite_ids[resource] == set(expected)
                panel = next(e for e in fixture.host.descendants() if 'dashboard-personal-panel' in e.classes)
                assert len(buttons(panel, 'favorite')) == len(expected)
                if in_dialog:
                    assert not container.is_deleted and container.value
                    assert len(buttons(container, 'favorite')) == len(expected)
                    if not expected:
                        assert dashboard.render_message('webui.render_complete_list.label.no_favourites_8952ca8c') in [
                            e.text for e in container.descendants() if isinstance(e, ui.label)]
                    close = buttons(container, 'close')[0]
                    with close.parent_slot:
                        handler(close)(None)
                    assert not container.value
                    fixture.host.clear()
                    assert container.is_deleted
                with client:
                    message = dashboard.render_message('webui.remove_dashboard_favourite.notify.removed_from_favourites_6953809b')
                assert notifications == [(str(message), 'positive')]
            elif outcome == 'rejected':
                assert [e['id'] for e in cached] == [1, 2]
                assert fixture.personal.favourite_ids[resource] == {1, 2}
                assert len(buttons(container, 'favorite')) == 2
                assert notifications == [('Conflict', 'negative')]
            else:
                assert [e['id'] for e in cached] == [1, 2]
                assert not notifications
                if in_dialog:
                    assert container.is_deleted
    finally:
        if fixture:
            await fixture.close()
        clear_active_messages(client.id)
        client.delete()
        set_active_messages({})
