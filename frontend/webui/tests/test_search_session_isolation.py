"""Search state must not survive an authentication boundary (no database needed)."""
import ast
import asyncio
from contextlib import nullcontext
import copy
import json
import pytest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock
from frontend.webui.global_search_state import new_global_search_state

SOURCE = ast.parse('\n'.join((Path(__file__).parents[1] / name).read_text() for name in ('app.py','global_search.py','advanced_search.py')))


def load(name, namespace):
    state=namespace['state']
    namespace.update(global_search_state=state, advanced_search_state=state, new_global_search_state=new_global_search_state,
        get_principal=lambda:namespace.get('auth_state',{}).get('principal'),
        get_resource=lambda:state.get('resource'),
        enter_global_search=lambda:state.update(resource='full-text-search'),
        discard_navigation_guard=lambda:state.pop('discard_navigation_guard',None),
        clear_advanced_workspace=lambda:state.pop('advanced_search_workspace',None),
        invalidate_advanced_session=lambda:state.__setitem__('advanced_search_session_revision',state.get('advanced_search_session_revision',0)+1),
        clear_collection_results=lambda:namespace['collection_state'].update(entity_result_states={}))
    node = next(n for n in ast.walk(SOURCE)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), namespace)
    return namespace[name]


def test_logout_discards_query_results_and_diagnostics():
    state = new_global_search_state('private query')
    state.update(global_search_revision=4, search_diagnostics_sent={'private': True},
                 global_search_streams={'record': ([{'record': {'id': 42}}], 'private cursor')},
                 global_search_totals={'records': 1, 'aggregations': 0})
    control = SimpleNamespace(value='private query', update=lambda: None)
    load('clear_global_search_session', {'state': state, 'collection_state': state, 'global_search_input': control})()
    assert control.value == state['global_search_query'] == ''
    assert state['global_search_streams'] == {}
    assert state['global_search_totals'] is None
    assert state['search_diagnostics_sent'] is None
    assert state['global_search_revision'] == 5


def test_old_search_response_cannot_repopulate_new_session():
    async def scenario():
        state = new_global_search_state('private query')
        state.update(resource='full-text-search', global_search_revision=0)
        principal = {'principal': {'id': 1}}
        started, release = asyncio.Event(), asyncio.Event()
        renders = []
        async def search(payload):
            started.set()
            await release.wait()
            return {'items': [{'type': 'aggregation', 'id': 42}]}
        control = SimpleNamespace(value='private query', update=lambda: None)
        namespace = dict(state=state,collection_state=state, auth_state=principal, Any=Any, json=json, asyncio=asyncio,
                         global_search_input=control, ApiError=RuntimeError,
                         global_search_payload=lambda *a, **k: {},
                         render_message=lambda *a: '', show_authenticated_view=lambda: None,
                         render_global_search_results=lambda: renders.append(True),
                         api=SimpleNamespace(full_text_search=search),
                         title=SimpleNamespace(text=''), subtitle=SimpleNamespace(text=''))
        for name in ('search_bar', 'aggregation_mode_bar', 'add_button', 'add_record_button'):
            namespace[name] = SimpleNamespace(set_visibility=lambda v: None)
        run = load('run_global_search', namespace)
        clear = load('clear_global_search_session', namespace)
        task = asyncio.create_task(run('private query', load_more=True))
        await started.wait()
        clear()
        principal['principal'] = {'id': 2}
        release.set()
        await task
        assert state['global_search_streams'] == {}
        assert state['global_search_query'] == ''
        assert len(renders) == 1  # only the original loading render
    asyncio.run(scenario())


def test_advanced_workspace_is_cleared_and_old_callbacks_cannot_restore_it():
    import copy
    state = {'discard_navigation_guard': lambda: None,
             'advanced_search_workspace': {'root': {'value': 'private'},
             'last_result': {'items': [{'id': 42}]}, 'saved': {'id': 7}}}
    principal = {'principal': {'user': {'id': 1}}}
    namespace = dict(state=state,collection_state=state, auth_state=principal, copy=copy,
                     search_principal=principal['principal'], search_session_revision=0,
                     workspace=copy.deepcopy(state['advanced_search_workspace']),
                     global_search_input=SimpleNamespace(value='', update=lambda: None))
    namespace['search_session_is_current'] = load('search_session_is_current', namespace)
    persist = load('persist_workspace', namespace)
    clear = load('clear_global_search_session', namespace)
    persist()  # Ordinary same-session navigation still preserves the workspace.
    assert state['advanced_search_workspace'] == namespace['workspace']
    clear()  # Sign-out / expiry.
    clear()  # Successful login also clears state, even for the same account.
    principal['principal'] = {'user': {'id': 2}}
    persist()  # Late callback from the original page.
    assert 'advanced_search_workspace' not in state
    assert state['advanced_search_session_revision'] == 2
    assert 'discard_navigation_guard' not in state


@pytest.mark.parametrize("outcome", ["success", "error", "cancelled", "navigation", "component_details"])
def test_advanced_search_late_response_does_not_render_or_restore_private_results(outcome):
    async def scenario():
        import copy
        state = {'resource': 'advanced-search'}
        principal = {'principal': {'user': {'id': 1}}}
        started, release = asyncio.Event(), asyncio.Event()
        renders = []
        async def search(*args):
            if outcome != 'component_details':
                started.set()
                await release.wait()
            if outcome == 'error':
                raise RuntimeError('old-session failure')
            if outcome == 'cancelled':
                raise asyncio.CancelledError
            return {'items': [{'id': 42, 'title': 'private result'}], 'total': 1}
        async def component_details(*args, **kwargs):
            started.set()
            await release.wait()
            return {"items": []}
        class Host:
            is_deleted = False
            def clear(self): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
        workspace = dict(root={}, resource='records' if outcome == 'component_details' else 'aggregations', sort_field='id', sort_direction='asc',
                         limit=25, offset=0, saved=None)
        ns = dict(state=state,collection_state=state, auth_state=principal, search_principal=principal['principal'],
                  search_session_revision=0, workspace=workspace, copy=copy, Any=Any,
                  asyncio=asyncio, ApiError=RuntimeError, results_host=Host(),
                  validate_builder=lambda: ({'field': 'title', 'operator': 'contains_ci', 'value': 'private'}, None),
                  search_advanced=SimpleNamespace(disable=lambda: None, enable=lambda: renders.append('enabled')),
                  status_label=SimpleNamespace(text=''), max_results=SimpleNamespace(value=1000),
                  render_message=lambda *a: '',
                  ui=SimpleNamespace(spinner=lambda **k: SimpleNamespace(classes=lambda *a: None)),
                  advanced_search_has_positive_full_text=lambda root: False,
                  api=SimpleNamespace(search_request=search, component_page=component_details,
                                      resource_capabilities=component_details), render_results=renders.append,
                  global_search_input=SimpleNamespace(value='', update=lambda: None))
        for name in ('search_session_is_current', 'search_view_is_current', 'persist_workspace'):
            ns[name] = load(name, ns)
        clear = load('clear_global_search_session', ns)
        task = asyncio.create_task(load('execute_search', ns)())
        await started.wait()
        if outcome == 'navigation':
            state['resource'] = 'dashboard'
        else:
            clear()
            principal['principal'] = {'user': {'id': 2}}
        state['advanced_search_workspace'] = {'root': 'new user query'}
        release.set()
        if outcome == 'cancelled':
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        assert renders == []
        assert state['advanced_search_workspace'] == {'root': 'new user query'}
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['value', 'operator', 'add', 'remove', 'group', 'full_text', 'sort'])
def test_draft_edits_preserve_the_displayed_page_when_persisted(change):
    import copy
    root = {'type': 'group', 'operator': 'and', 'children': [
        {'type': 'condition', 'kind': 'structured', 'field': 'title', 'operator': 'contains_ci', 'value': 'old'},
        {'type': 'condition', 'kind': 'full_text', 'query': 'old', 'sources': ['metadata']},
    ]}
    workspace = {'root': root, 'offset': 75, 'sort_field': 'id'}
    state = {'advanced_search_workspace': copy.deepcopy(workspace)}
    persist = load('persist_workspace', dict(state=state,collection_state=state, workspace=workspace, copy=copy,
                                            search_session_is_current=lambda: True))
    if change == 'value': root['children'][0]['value'] = 'new'
    elif change == 'operator': root['children'][0]['operator'] = 'eq'
    elif change == 'add': root['children'].append(copy.deepcopy(root['children'][0]))
    elif change == 'remove': root['children'].pop()
    elif change == 'group': root['operator'] = 'or'
    elif change == 'full_text': root['children'][1]['query'] = 'new'
    else: workspace['sort_field'] = 'title'
    persist()
    assert workspace['offset'] == state['advanced_search_workspace']['offset'] == 75
    assert state['advanced_search_workspace']['root'] == root
    assert state['advanced_search_workspace']['sort_field'] == workspace['sort_field']


def test_advanced_pagination_uses_last_execution_until_search_is_submitted():
    from frontend.webui.advanced_search_model import compile_advanced_search_node

    async def scenario():
        condition = {'type': 'condition', 'kind': 'structured', 'field': 'title',
                     'operator': 'contains_ci', 'value': 'original'}
        dates = {'type': 'condition', 'kind': 'structured', 'field': 'date_opened',
                 'operator': 'between', 'value': ['2026-01-01', '2026-12-31']}
        workspace = dict(root={'type': 'group', 'operator': 'and', 'children': [condition, dates]},
                         resource='aggregations', sort_field='id', sort_direction='asc', limit=25)
        maximum = SimpleNamespace(value=62)
        search_request = AsyncMock(return_value={'items': [], 'total': 80})
        host = nullcontext()
        host.clear = Mock()
        namespace = dict(
            state={}, workspace=workspace, search_view_is_current=lambda: True, copy=copy,
            validate_builder=lambda: (compile_advanced_search_node(workspace['root'], 'aggregations'), None),
            advanced_search_has_positive_full_text=lambda root: False,
            api=SimpleNamespace(search_request=search_request), max_results=maximum,
            search_advanced=Mock(), ui=Mock(), results_host=host, status_label=SimpleNamespace(),
            render_message=lambda key: key, render_results=Mock(), refresh_saved_actions=Mock(),
            persist_workspace=Mock(), ApiError=RuntimeError,
        )
        execute = load('execute_search', namespace)
        move_page = load('move_page', namespace)
        await execute()
        original = copy.deepcopy(search_request.await_args.args[1])
        assert original['where']['and'][0]['value'] == 'original'
        condition['value'] = 'draft'
        dates['value'][0] = '2026-06-01'
        workspace.update(sort_field='title', sort_direction='desc', limit=100)
        maximum.value = 5
        for direction, offset, limit in (
            ('next', 25, 25), ('last', 50, 12), ('previous', 25, 25), ('first', 0, 25),
        ):
            await move_page(direction)
            assert workspace['offset'] == offset
            assert search_request.await_args.args == ('aggregations', {**original, 'offset': offset, 'limit': limit})
        assert search_request.await_count == 5
        await move_page('next')
        await execute()
        submitted = search_request.await_args.args[1]
        assert workspace['offset'] == submitted['offset'] == 0
        assert submitted['where']['and'][0]['value'] == 'draft'
        assert submitted['where']['and'][1]['value'][0] == '2026-06-01'
        assert submitted['sort'] == [{'field': 'title', 'direction': 'desc'}]
        assert submitted['limit'] == 5
    asyncio.run(scenario())


def test_global_search_state_factory_keeps_clients_independent():
    from frontend.webui.global_search_state import new_global_search_state
    first, second = new_global_search_state(' private '), new_global_search_state()
    first['global_search_streams']['record'] = ([{'type': 'record', 'record': {'id': 7}}], 'cursor')
    first['global_search_expanded_results'].add('records:7')
    first['search_diagnostics_sent'] = {'query': 'private'}
    assert first['global_search_query'] == 'private'
    assert second['global_search_query'] == ''
    assert second['global_search_streams'] == {}
    assert second['global_search_expanded_results'] == set()
    assert second['search_diagnostics_sent'] is None


def test_advanced_workspace_owner_is_private_to_each_client():
    from frontend.webui.advanced_search_state import new_advanced_search_state
    first, second = new_advanced_search_state(), new_advanced_search_state()
    first.update(advanced_search_workspace={'root': {'value': 'private'}},
                 admin_saved_search_id=17, advanced_search_session_revision=2)
    assert second == {}
