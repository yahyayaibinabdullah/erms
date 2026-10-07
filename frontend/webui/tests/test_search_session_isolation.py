"""Search state must not survive an authentication boundary (no database needed)."""
import ast
import asyncio
import json
import pytest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

SOURCE = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())


def load(name, namespace):
    node = next(n for n in ast.walk(SOURCE)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'app.py', 'exec'), namespace)
    return namespace[name]


def test_logout_discards_query_results_and_diagnostics():
    state = dict(global_search_revision=4, global_search_query='private query',
                 global_search_items=[{'record': {'id': 42}}], search_diagnostics_sent={'private': True})
    control = SimpleNamespace(value='private query', update=lambda: None)
    load('clear_global_search_session', {'state': state, 'global_search_input': control})()
    assert control.value == state['global_search_query'] == ''
    assert state['global_search_items'] == []
    assert state['search_diagnostics_sent'] is None
    assert state['global_search_revision'] == 5


def test_old_search_response_cannot_repopulate_new_session():
    async def scenario():
        state = dict(resource='full-text-search', global_search_revision=0,
                     search_diagnostics_enabled=False, global_search_items=[])
        principal = {'principal': {'id': 1}}
        started, release = asyncio.Event(), asyncio.Event()
        renders = []
        async def search(payload):
            started.set()
            await release.wait()
            return {'items': [{'type': 'aggregation', 'id': 42}]}
        control = SimpleNamespace(value='private query', update=lambda: None)
        namespace = dict(state=state, auth_state=principal, Any=Any, json=json, asyncio=asyncio,
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
        assert state['global_search_items'] == []
        assert state['global_search_query'] == ''
        assert len(renders) == 1  # only the original loading render
    asyncio.run(scenario())


def test_advanced_workspace_is_cleared_and_old_callbacks_cannot_restore_it():
    import copy
    state = {'discard_navigation_guard': lambda: None,
             'advanced_search_workspace': {'root': {'value': 'private'},
             'last_result': {'items': [{'id': 42}]}, 'saved': {'id': 7}}}
    principal = {'principal': {'user': {'id': 1}}}
    namespace = dict(state=state, auth_state=principal, copy=copy,
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
        ns = dict(state=state, auth_state=principal, search_principal=principal['principal'],
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
def test_criteria_changes_reset_later_page_before_persisting(change):
    import copy
    root = {'type': 'group', 'operator': 'and', 'children': [
        {'type': 'condition', 'kind': 'structured', 'field': 'title', 'operator': 'contains_ci', 'value': 'old'},
        {'type': 'condition', 'kind': 'full_text', 'query': 'old', 'sources': ['metadata']},
    ]}
    workspace = {'root': root, 'offset': 75, 'sort_field': 'id'}
    state = {'advanced_search_workspace': copy.deepcopy(workspace)}
    persist = load('persist_workspace', dict(state=state, workspace=workspace, copy=copy,
                                            search_session_is_current=lambda: True))
    if change == 'value': root['children'][0]['value'] = 'new'
    elif change == 'operator': root['children'][0]['operator'] = 'eq'
    elif change == 'add': root['children'].append(copy.deepcopy(root['children'][0]))
    elif change == 'remove': root['children'].pop()
    elif change == 'group': root['operator'] = 'or'
    elif change == 'full_text': root['children'][1]['query'] = 'new'
    else: workspace['sort_field'] = 'title'
    persist()
    assert workspace['offset'] == state['advanced_search_workspace']['offset'] == 0
    # Normal pagination for unchanged criteria must still work.
    workspace['offset'] = 25
    persist()
    assert state['advanced_search_workspace']['offset'] == 25
