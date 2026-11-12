"""Exercise the collection loader's real filter payload against the API schema."""
import ast
import asyncio
from pathlib import Path
from typing import Any, Callable
from unittest.mock import AsyncMock, Mock

import pytest

from backend.services.api.schemas import SearchRequest
from frontend.webui.entities import ENTITIES
from frontend.webui.tests.shared_controls_fixture import collection_loader


@pytest.mark.parametrize('resource,fields', [
    ('roles', {'code', 'name', 'description'}),
    ('org-units', {'code', 'name', 'description'}),
    ('users', {'name', 'email', 'external_id'}),
])
@pytest.mark.parametrize('query', ['exe', 'تنفيذي', ''])
@pytest.mark.parametrize('results_only', [False, True])
def test_collection_filter_request_is_valid(resource, fields, query, results_only):
    source = Path(__file__).parents[1] / 'app.py'
    api = Mock()
    api.search_request = AsyncMock(return_value={'items': [], 'total': 0})
    page = dict(query=query, sort='name', limit=25, offset=0, status='all', account_type='all')
    state = dict(resource=resource, collection_pages={resource: page})
    scope = dict(ENTITIES=ENTITIES, state=state, collection_state=state, api=api, Any=Any, Callable=Callable,
                 decorate_for_spec=AsyncMock(return_value=[]),
                 set_connection_status=Mock(), render_table=Mock())
    scope['load_rows'] = collection_loader(scope)
    refresh_results = Mock()
    asyncio.run(scope['load_rows'](on_loaded=refresh_results if results_only else None))
    args, kwargs = api.search_request.call_args
    assert args[0] == resource
    request = SearchRequest.model_validate(args[1])
    assert request.limit == 25 and request.offset == 0
    if query:
        assert {condition.field for condition in request.where.or_} == fields
        assert all(condition.value == query and condition.operator == 'contains_ci'
                   for condition in request.where.or_)
    else:
        assert request.where is None
    assert kwargs['include_system'] == (True if resource == 'roles' else None)
    if results_only:
        refresh_results.assert_called_once_with()
        scope['render_table'].assert_not_called()
    else:
        scope['render_table'].assert_called_once_with(ENTITIES[resource])


def test_collection_ignores_stale_and_abandoned_filter_responses():
    source = Path(__file__).parents[1] / 'app.py'
    async def run():
        gate = asyncio.Event()
        started = asyncio.Event()
        async def search(resource, payload, **kwargs):
            query = payload['where']['or'][0]['value']
            if query == 'e':
                started.set()
                await gate.wait()
            return {'items': [{'name': query}], 'total': 1}
        async def decorate(spec, rows):
            return rows
        api = Mock(search_request=search)
        page = dict(query='e', sort='name', limit=25, offset=0, status='all')
        state = dict(resource='roles', collection_pages={'roles': page}, rows=[])
        callback = Mock()
        scope = dict(ENTITIES=ENTITIES, state=state, collection_state=state, api=api, Any=Any, Callable=Callable,
                     decorate_for_spec=decorate, set_connection_status=Mock(), render_table=Mock())
        scope['load_rows'] = collection_loader(scope)
        old = asyncio.create_task(scope['load_rows'](on_loaded=callback))
        await started.wait()
        page['query'] = 'exe'
        await scope['load_rows'](on_loaded=callback)
        gate.set()
        await old
        assert state['rows'] == [{'name': 'exe'}]
        callback.assert_called_once()
        callback.reset_mock()
        await scope['load_rows'](on_loaded=callback, is_current=lambda: False)
        callback.assert_not_called()
        scope['render_table'].assert_not_called()
    asyncio.run(run())


@pytest.mark.parametrize('resource', ['aggregations', 'records'])
def test_clear_search_discards_pending_results_and_resets_result_controls(resource):
    from types import SimpleNamespace
    source = Path(__file__).parents[1] / 'app.py'
    tree = ast.parse(source.read_text())
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                 and n.name == 'clear_collection_search']
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def search(*args, **kwargs):
            started.set()
            await release.wait()
            return {'items': [{'id': 408}], 'total': 1}
        async def decorate(spec, rows):
            return rows
        search_input = Mock(value='سجل')
        state = dict(resource=resource, searched=True, rows=[{'id': 1}],
                     entity_result_states={resource: {'filter': 'old', 'page': 3}})
        scope = dict(ENTITIES=ENTITIES, state=state, collection_state=state, api=Mock(search_request=search),
                     Any=Any, Callable=Callable, search_input=search_input,
                     decorate_for_spec=decorate, set_connection_status=Mock(),
                     render_table=Mock(), page_client=SimpleNamespace(_deleted=False))
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), scope)
        scope['load_rows'] = collection_loader(scope)
        pending = asyncio.create_task(scope['load_rows']())
        await started.wait()
        await scope['clear_collection_search']()
        release.set()
        await pending
        assert state['searched'] is False and state['rows'] == []
        assert resource not in state['entity_result_states']
        assert search_input.value == ''
        search_input.run_method.assert_called_once_with('focus')
        scope['render_table'].assert_called_once_with(ENTITIES[resource])
    asyncio.run(run())


@pytest.mark.parametrize('resource', ['aggregations', 'records'])
def test_compact_search_requests_only_visible_page_and_keeps_submitted_query(resource):
    async def run():
        api = Mock(search_request=AsyncMock(return_value={'items': [{'id': 103}], 'total': 103}))
        search = Mock(value='Submitted')
        state = {'resource': resource}
        decorate = AsyncMock(side_effect=lambda spec, rows: rows)
        decorate_components = AsyncMock(side_effect=lambda rows: rows)
        loader = collection_loader(dict(
            state=state, search_input=search, api=api, decorate_for_spec=decorate,
            decorate_record_search_components=decorate_components,
            set_connection_status=Mock(), render_table=Mock(),
        ))
        await loader()
        result = state['entity_result_states'][resource]
        assert result['total'] == 103
        search.value = 'Draft'
        await loader(compact_state={**result, 'page': 11})
        args, kwargs = api.search_request.call_args
        assert args[0] == resource
        request = SearchRequest.model_validate(args[1])
        assert (request.limit, request.offset) == (10, 100)
        assert all(condition.value == 'Submitted' for condition in request.where.or_)
        assert kwargs == {'display_filter': ''}
        assert state['entity_result_states'][resource]['page'] == 11
        assert state['rows'] == [{'id': 103}]
        assert decorate_components.await_count == (2 if resource == 'records' else 0)
    asyncio.run(run())


def test_dashboard_scope_is_kept_when_unclassified_roots_are_paged_or_refreshed():
    async def run():
        api = Mock(search_request=AsyncMock(return_value={'items': [], 'total': 111}))
        state = {'resource': 'aggregations'}
        loader = collection_loader(dict(
            state=state, search_input=Mock(value='Draft'), api=api,
            decorate_for_spec=AsyncMock(return_value=[]),
            set_connection_status=Mock(), render_table=Mock(),
        ))
        await loader(compact_state={'query': '', 'unclassified_roots': True, 'page': 11})
        await loader(repeat_search=True)
        assert api.search_request.await_count == 2
        for call in api.search_request.await_args_list:
            request = SearchRequest.model_validate(call.args[1])
            assert (request.limit, request.offset) == (10, 100)
            assert {leaf.field for leaf in request.where.and_} == {'parent_aggregation_id', 'classification_id'}
            assert all(leaf.operator == 'is_null' for leaf in request.where.and_)
    asyncio.run(run())
