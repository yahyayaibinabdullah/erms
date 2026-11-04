"""Regression coverage for the actual nested workspace callbacks (no database)."""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

SOURCE = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())


def callbacks(*names, **scope):
    if 'change_target' in names:
        # Exercise the real shared reset callback, including metadata clearing.
        names = tuple(dict.fromkeys((*names, 'new_condition', 'reset_search')))
        for name in ('search_name', 'search_category', 'search_description',
                     'max_results', 'page_size', 'sort_direction'):
            scope.setdefault(name, SimpleNamespace(value=None))
        scope.setdefault('freshness_host', Mock())
        scope.setdefault('status_label', SimpleNamespace(text='old results'))
        scope.setdefault('current_saved_signature', lambda: '{}')
    nodes = [next(node for node in ast.walk(SOURCE)
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
             for name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<search-callbacks>', 'exec'), scope)
    return SimpleNamespace(**scope)


@pytest.mark.asyncio
@pytest.mark.parametrize('saved', [None, {'id': 7}])
async def test_unchanged_new_target_is_silent_but_loaded_saved_target_confirms(saved):
    workspace = dict(resource='records', saved=saved, root={'children': [{}]}, baseline='original')
    confirm = AsyncMock(return_value=True)
    scope = callbacks('new_condition', 'change_target', Any=object, workspace=workspace,
                      target=SimpleNamespace(value='aggregations'), is_dirty=lambda: False,
                      current_saved_signature=lambda: 'new clean baseline',
                      search_view_is_current=lambda: True, confirm_target_reset=confirm,
                      results_host=Mock(), pagination=Mock(), render_builder=Mock(),
                      refresh_sort_options=Mock(), refresh_saved_actions=Mock(), persist_workspace=Mock())
    await scope.change_target(SimpleNamespace(value='aggregations'))
    if saved is None:
        confirm.assert_not_awaited()
    else:
        confirm.assert_awaited_once()
    assert workspace['resource'] == 'aggregations'
    assert workspace['saved'] is None
    assert workspace['baseline'] == 'new clean baseline'
    if saved is not None:
        assert saved == {'id': 7}  # The stored saved definition is never mutated.
    scope.persist_workspace.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [True, False])
async def test_dirty_target_switch_confirms_once_and_cancel_preserves_workspace(cancel):
    workspace = dict(resource='records', root={'value': 'edited'})
    original = copy.deepcopy(workspace)
    target = SimpleNamespace(value='aggregations', update=Mock())
    confirm = AsyncMock(return_value=not cancel)
    scope = callbacks('new_condition', 'change_target', Any=object, workspace=workspace,
                      target=target, is_dirty=lambda: True, search_view_is_current=lambda: True,
                      confirm_target_reset=confirm, results_host=Mock(), pagination=Mock(),
                      render_builder=Mock(), refresh_sort_options=Mock(),
                      refresh_saved_actions=Mock(), persist_workspace=Mock())
    await scope.change_target(SimpleNamespace(value='aggregations'))
    confirm.assert_awaited_once()
    if cancel:
        assert workspace == original
        assert target.value == 'records'
    else:
        assert workspace['resource'] == 'aggregations'


@pytest.mark.asyncio
@pytest.mark.parametrize('loading,current,event_value,target_value', [
    (True, True, 'records', 'records'),
    (False, False, 'aggregations', 'aggregations'),
    (False, True, 'records', 'aggregations'),
    (False, True, 'aggregations', 'aggregations'),
])
async def test_loading_abandoned_and_delayed_programmatic_events_are_ignored(loading,current,event_value,target_value):
    workspace = dict(resource='aggregations', loading=loading)
    confirm = AsyncMock()
    scope = callbacks('change_target', Any=object, workspace=workspace,
                      target=SimpleNamespace(value=target_value), is_dirty=lambda: True,
                      search_view_is_current=lambda: current, confirm_target_reset=confirm)
    await scope.change_target(SimpleNamespace(value=event_value))
    confirm.assert_not_awaited()


def test_page_size_does_not_dirty_saved_definition_and_reverted_edits_are_clean():
    payload = {'definition': {'request': {'limit': 25, 'where': {'value': 'budget'}}}}
    workspace = {}
    scope = callbacks('current_saved_signature', 'is_dirty', json=json, workspace=workspace,
                      current_saved_payload=lambda: copy.deepcopy(payload))
    workspace['baseline'] = scope.current_saved_signature()
    payload['definition']['request']['limit'] = 100
    assert not scope.is_dirty()
    payload['definition']['request']['where']['value'] = 'changed'
    assert scope.is_dirty()
    payload['definition']['request']['where']['value'] = 'budget'
    assert not scope.is_dirty()


@pytest.mark.parametrize('resource', ['record', 'aggregation'])
def test_loading_saved_search_clears_previous_execution_and_sets_clean_baseline(resource):
    workspace = dict(last_result={'items': [{'id': 99}]}, searched=True, total=1,
                     return_anchor='old-result', expanded_results=[99],
                     record_component_details={99: []}, record_capabilities={99: {}})
    saved = dict(id=7, name='Saved fixture', definition=dict(resource_type=resource,
                 request=dict(where={'field': 'title', 'operator': 'contains_ci', 'value': 'budget'})))
    controls = {name: SimpleNamespace(value=None) for name in
                ('search_name', 'search_category', 'search_description', 'target',
                 'max_results', 'page_size', 'sort_direction')}
    status = SimpleNamespace(text='previous results')
    scope = callbacks('load_saved_into_workspace', Any=object, workspace=workspace,
                      advanced_search_node_from_expression=lambda value: value,
                      results_host=Mock(), freshness_host=Mock(), pagination=Mock(),
                      render_builder=Mock(), current_saved_signature=lambda: 'clean',
                      refresh_saved_actions=Mock(), persist_workspace=Mock(),
                      status_label=status, **controls)
    scope.load_saved_into_workspace(saved)
    assert workspace['baseline'] == 'clean'
    assert workspace['loading'] is False
    assert workspace['resource'] == resource + 's'
    assert workspace['last_result'] is None and workspace['searched'] is False
    assert workspace['offset'] == workspace['total'] == 0
    assert workspace['expanded_results'] == []
    assert workspace['record_component_details'] == workspace['record_capabilities'] == {}
    assert 'return_anchor' not in workspace
    assert status.text == ''


def test_previously_persisted_baseline_does_not_become_dirty_after_upgrade():
    payload = {'definition': {'request': {'limit': 25, 'where': {'value': 'budget'}}}}
    workspace = {'baseline': json.dumps(payload)}
    scope = callbacks('current_saved_signature', 'is_dirty', json=json, workspace=workspace,
                      current_saved_payload=lambda: copy.deepcopy(payload))
    payload['definition']['request']['limit'] = 100
    assert not scope.is_dirty()
    payload['definition']['request']['where']['value'] = 'unsaved edit before upgrade'
    assert scope.is_dirty()


def test_incomplete_default_criteria_signature_ignores_page_size_and_detects_edits():
    workspace = dict(search_name='', search_category=None, search_description='',
                     root={'value': ''}, resource='records', sort_field='id',
                     sort_direction='asc', limit=25, audience_mode='private',
                     role_ids=[], org_unit_ids=[])
    def incomplete_payload():
        raise ValueError('Incomplete condition')
    scope = callbacks('current_saved_signature', 'is_dirty', json=json, workspace=workspace,
                      current_saved_payload=incomplete_payload,
                      max_results=SimpleNamespace(value=1000))
    previous = json.loads(scope.current_saved_signature())
    previous['limit'] = 25  # Signature stored by an earlier WebUI process.
    workspace['baseline'] = json.dumps(previous)
    workspace['limit'] = 100
    assert not scope.is_dirty()
    workspace['root']['value'] = 'partial edit'
    assert scope.is_dirty()
    workspace['root']['value'] = ''
    assert not scope.is_dirty()


@pytest.mark.asyncio
async def test_clean_navigation_guard_does_not_construct_any_dialog():
    scope = callbacks('confirm_discard_changes', is_dirty=lambda: False)
    assert await scope.confirm_discard_changes('leave this page') is True


@pytest.mark.asyncio
async def test_target_only_setup_then_open_saved_search_is_clean_but_later_edits_warn():
    workspace = dict(resource='records', saved=None, root={'value': ''})
    def payload():
        return {'definition': {'request': {'where': copy.deepcopy(workspace['root'])},
                               'resource_type': workspace['resource']}}
    target = SimpleNamespace(value='aggregations')
    confirm = AsyncMock(return_value=True)
    scope = callbacks('new_condition', 'current_saved_signature', 'is_dirty',
                      'confirm_discard_changes', 'change_target', json=json, Any=object,
                      workspace=workspace, target=target, current_saved_payload=payload,
                      search_view_is_current=lambda: True, confirm_target_reset=confirm,
                      results_host=Mock(), pagination=Mock(), render_builder=Mock(),
                      refresh_sort_options=Mock(), refresh_saved_actions=Mock(), persist_workspace=Mock())
    workspace['baseline'] = scope.current_saved_signature()
    for resource in ('aggregations', 'records', 'aggregations'):
        target.value = resource
        await scope.change_target(SimpleNamespace(value=resource))
        assert not scope.is_dirty()
        # No UI is supplied: any attempt to construct a warning fails the test.
        assert await scope.confirm_discard_changes('open another saved search')
        assert await scope.confirm_discard_changes('leave this page')
    confirm.assert_not_awaited()
    workspace['root']['children'][0]['value'] = 'new edit'
    assert scope.is_dirty()


@pytest.mark.asyncio
@pytest.mark.parametrize('resource,requested', [('records','aggregations'), ('aggregations','records')])
@pytest.mark.parametrize('accept', [False, True])
async def test_loaded_saved_target_change_cancels_safely_or_starts_detached_new_search(resource,requested,accept):
    workspace = dict(resource=resource, saved={'id':7},
                     root={'type':'group','operator':'and','children':[{'value':'saved criterion'}]},
                     last_result={'items':[{'id':3}]}, searched=True,
                     search_name='Original saved name', search_category='Original category',
                     search_description='Original description', audience_mode='roles_and_units',
                     role_ids=[11], org_unit_ids=[22], return_anchor='old-result',
                     expanded_results=[3], record_component_details={3: []},
                     record_capabilities={3: {}}, sort_field='title', sort_direction='desc',
                     max_results=500, limit=100)
    def payload():
        return {'definition': {'request': {'where': copy.deepcopy(workspace['root'])},
                               'resource_type': workspace['resource']}}
    target = SimpleNamespace(value=requested, update=Mock())
    confirm = AsyncMock(return_value=accept)
    scope = callbacks('new_condition', 'current_saved_signature', 'is_dirty', 'change_target',
                      json=json, Any=object, workspace=workspace, target=target,
                      current_saved_payload=payload, search_view_is_current=lambda:True,
                      confirm_target_reset=confirm, results_host=Mock(), pagination=Mock(),
                      render_builder=Mock(), refresh_sort_options=Mock(),
                      refresh_saved_actions=Mock(), persist_workspace=Mock())
    workspace['baseline'] = scope.current_saved_signature()
    original = copy.deepcopy(workspace)
    assert not scope.is_dirty()
    await scope.change_target(SimpleNamespace(value=requested))
    confirm.assert_awaited_once()
    if accept:
        assert workspace['resource'] == requested
        assert workspace['root']['children'][0]['value'] == ''
        assert workspace['last_result'] is None
        assert workspace['saved'] is None
        assert workspace['search_name'] == workspace['search_description'] == ''
        assert workspace['search_category'] is None
        assert workspace['audience_mode'] == 'private'
        assert workspace['role_ids'] == workspace['org_unit_ids'] == []
        assert workspace['sort_field'] == 'id' and workspace['sort_direction'] == 'asc'
        assert workspace['max_results'] == 1000 and workspace['limit'] == 25
        assert workspace['expanded_results'] == []
        assert workspace['record_component_details'] == workspace['record_capabilities'] == {}
        assert 'return_anchor' not in workspace
        assert scope.search_name.value == scope.search_description.value == ''
        assert scope.search_category.value is None
        assert not scope.is_dirty()
        workspace['root']['children'][0]['value'] = 'new search edit'
        assert scope.is_dirty()
        assert original['saved'] == {'id':7}
    else:
        assert workspace == original
        assert target.value == resource
        assert not scope.is_dirty()
        scope.persist_workspace.assert_not_called()
