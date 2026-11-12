"""Exercise saved-navigation scheme table actions with the real bounded loader."""
import asyncio
import inspect
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from nicegui import events, ui

from frontend.webui import i18n_catalogue as i18n
from frontend.webui.api_client import ApiError
from frontend.webui.collection_controls import build_collection_loader
from frontend.webui.collection_table import build_collection_table

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


class Api:
    def __init__(self):
        self.row = dict(id=7, version=3, code='S07', title='Scheme', date_published=None,
                        date_deactivated=None)
        self.reads = []
        self.writes = []
        self.hold = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.failure = None
        self.empty = False

    async def request(self, method, path, **kwargs):
        self.writes.append((method, path, kwargs))
        if self.hold == 'mutation':
            self.started.set()
            await self.release.wait()
        if self.failure == 'mutation':
            raise ApiError(409, 'Version conflict')
        action = path.rsplit('/', 1)[1]
        assert action in {'publish', 'deactivate', 'reactivate'}
        assert kwargs['headers']['If-Match'] == str(self.row['version'])
        if action != 'publish':
            assert kwargs['headers']['X-Change-Reason'] == f'{action.title()} from classification administration'
        self.row['version'] += 1
        self.row['date_published' if action == 'publish' else 'date_deactivated'] = (
            None if action == 'reactivate' else '2026-01-01T00:00:00Z'
        )
        return dict(self.row)

    async def search_request(self, resource, payload, **kwargs):
        self.reads.append((resource, payload))
        assert resource == 'classification-schemes'
        assert payload['sort'][0]['field'] in {'title', 'code'}
        if self.hold == 'read':
            self.started.set()
            await self.release.wait()
        if self.failure == 'read':
            raise ApiError(503, 'Read unavailable')
        return dict(items=[] if self.empty else [dict(self.row)], total=0 if self.empty else 36)


async def open_collection(user, language='en', page_settings=None):
    api = Api()
    state = dict(resource='classification-schemes', rows=[], searched=False)
    pages = {'classification-schemes': dict(page_settings)} if page_settings else {}
    view = {}

    @ui.page('/')
    async def page():
        if language == 'ar':
            artifact = json.loads((Path(__file__).parents[2] / 'i18n/messages.ar.generated.json').read_text())
            i18n.set_active_messages({i['message_key']: i['translated_text'] for i in artifact['items']})
        else:
            i18n.set_active_messages({})
        container = view['container'] = ui.column()
        async def decorate(spec, rows):
            return rows
        dependencies = {name: Mock() for name in inspect.signature(build_collection_table).parameters}
        dependencies.update(
            RELATIONSHIP_DISPLAY_FIELDS={}, api=api, collection_state=state,
            guidance=ui.label(), subtitle=ui.label(), table_container=container,
            error_message=str, load_rows=lambda **kwargs: view['load'](**kwargs),
        )
        render = build_collection_table(**dependencies)
        view['load'] = build_collection_loader(
            api, get_resource=lambda: state['resource'], get_query=lambda: '', pages=pages,
            accept_results=lambda rows, searched: state.update(rows=rows, searched=searched),
            clear_result_state=Mock(), decorate_for_spec=decorate,
            decorate_record_search_components=None, page_client=container.client,
            set_connection_status=Mock(), render_table=render, error_message=str,
        )
        with container:
            await view['load']()

    await user.open('/')
    return api, state, pages, view


def table(user):
    return next(e for e in user.client.elements.values() if isinstance(e, ui.table) and not e.is_deleted)


async def act(user, action):
    current = table(user)
    event = 'publish_scheme' if action == 'publish' else 'scheme_lifecycle'
    callback = next(v.handler for v in current._event_listeners.values() if v.type == event)
    with current:
        await callback(events.GenericEventArguments(sender=current, client=user.client, args=dict(current.rows[0])))


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('custom_page', [False, True])
async def test_publish_deactivate_reactivate_refresh_versions_and_keep_page(user, language, custom_page):
    settings = dict(offset=25, limit=10, total=36, query='Scheme', status='all',
                    account_type='all', sort='code') if custom_page else None
    api, state, pages, _ = await open_collection(user, language, settings)
    original_payload = api.reads[0][1]
    for action in ('publish', 'deactivate', 'reactivate'):
        old = table(user)
        await act(user, action)
        assert old.is_deleted
        assert table(user).rows[0]['version'] == api.row['version']
        assert table(user).rows[0]['date_deactivated'] == api.row['date_deactivated']
        assert table(user).rows[0]['date_published'] == api.row['date_published']
        assert api.reads[-1][1] == original_payload
    assert len(api.reads) == 4 and len(api.writes) == 3
    assert state['resource'] == 'classification-schemes'
    assert pages['classification-schemes']['offset'] == (25 if custom_page else 0)


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('stage', ['mutation', 'read'])
async def test_late_completion_does_not_read_or_repaint_new_page(user, language, stage):
    api, state, _, view = await open_collection(user, language)
    api.hold = stage
    task = asyncio.create_task(act(user, 'publish'))
    await asyncio.wait_for(api.started.wait(), 2)
    with user:
        state['resource'] = 'users'
        view['container'].clear()
        with view['container']:
            ui.label('New destination')
    api.release.set()
    await task
    assert len(api.reads) == (1 if stage == 'mutation' else 2)
    assert not any(isinstance(e, ui.table) and not e.is_deleted for e in user.client.elements.values())
    await user.should_see('New destination')


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('failure', ['mutation', 'read'])
async def test_failures_do_not_replace_existing_table_or_repeat_mutation(user, language, failure):
    api, _, _, _ = await open_collection(user, language)
    original = table(user)
    api.failure = failure
    await act(user, 'publish')
    assert table(user) is original and original.rows[0]['version'] == 3
    assert len(api.writes) == 1
    assert len(api.reads) == (1 if failure == 'mutation' else 2)


@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_empty_refresh_removes_stale_rows(user, language):
    api, _, _, _ = await open_collection(user, language)
    api.empty = True
    await act(user, 'publish')
    assert table(user).rows == []
    assert len(api.reads) == 2
