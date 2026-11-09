"""Run the actual editor Save and collection loader with an in-memory API."""
import ast
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import AsyncMock, Mock

import pytest
from frontend.webui.api_client import ApiError
from frontend.webui.entities import ENTITIES
from frontend.webui.i18n_catalogue import render_message, strip_diagnostic_metadata

TREE = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())
EDITOR = next(n for n in ast.walk(TREE) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'open_editor')
SAVE = next(n for n in ast.walk(EDITOR) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'save')
LOADER = next(n for n in ast.walk(TREE) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'load_rows')


@pytest.mark.parametrize('action', ['create', 'update', 'translation'])
@pytest.mark.parametrize('sort,query,offset', [('name', '', 0), ('code', '', 0), ('name', 'visible', 0), ('status', '', 25)])
@pytest.mark.parametrize('arabic', [False, True])
def test_save_requeries_the_selected_bounded_page(action, sort, query, offset, arabic):
    async def run():
        rows = [{'id': i, 'name': f'visible {i:02}', 'code': f'R{40-i:02}', 'status': 'active',
                 'version': 1, 'localized': {'name': f'اسم {40-i:02}' if arabic else f'visible {i:02}'}}
                for i in range(1, 36)]
        row = rows[0]
        name = 'اسم جديد' if arabic else 'A new role'
        saved = dict(row, id=36 if action == 'create' else row['id'], name=name,
                     localized={'name': name}, version=2)
        page = dict(query=query, sort=sort, offset=offset, limit=25, status='all', account_type='all')
        state = dict(resource='roles', rows=deepcopy(rows[:25]), collection_pages={'roles': page})
        writes, requests = [], []
        async def write(*args, **kwargs):
            writes.append((args, kwargs))
            if action == 'create': rows.append(saved)
            else: rows[0] = saved
            return deepcopy(saved)
        async def search(resource, payload, **kwargs):
            requests.append((resource, deepcopy(payload), kwargs))
            ordered = [r for r in rows if not query or query in r['name']]
            ordered.sort(key=lambda r: ((r['localized']['name'] if sort == 'name' else r[sort]), r['id']))
            return dict(items=deepcopy(ordered[offset:offset+25]), total=len(ordered))
        async def decorate(spec, data):return data
        rendered = []
        scope = dict(Any=Any, Callable=Callable, ApiError=ApiError, ENTITIES=ENTITIES, state=state,
                     spec=ENTITIES['roles'], row=deepcopy(row), controls={}, creating=action=='create',
                     translation_only=action=='translation', on_saved=None, editor_entity='role',
                     prepare_entity_translation_update=(lambda: ('ar', {'name': name}, 'Correct name')) if action=='translation' else None,
                     api=SimpleNamespace(create=write, update=write, update_entity_translation=write, search_request=search),
                     form_payload=lambda *a, **k: {'name': name}, role_change_requires_reason=lambda *a: False,
                     lookup_rows_by_field={}, resource_change_reason=None, profile_change_reason=None,
                     dialog=Mock(), ui=Mock(), render_message=render_message, strip_diagnostic_metadata=strip_diagnostic_metadata,
                     decorate_for_spec=decorate, set_connection_status=Mock(),
                     render_table=lambda spec: rendered.append(deepcopy(state['rows'])),
                     page_client=SimpleNamespace(_deleted=False))
        exec(compile(ast.Module(body=[SAVE, LOADER], type_ignores=[]), '<actual-editor-save-and-loader>', 'exec'), scope)
        await scope['save']()
        assert len(writes) == len(requests) == len(rendered) == 1
        resource, payload, kwargs = requests[0]
        assert resource == 'roles' and kwargs == {'include_system': True}
        assert payload['sort'] == [{'field':sort,'direction':'asc'}, {'field':'id','direction':'asc'}]
        assert payload['limit'] == 25 and payload['offset'] == offset
        if query: assert payload['where']['or'][0]['value'] == query
        expected = sorted([r for r in rows if not query or query in r['name']],
                          key=lambda r: ((r['localized']['name'] if sort=='name' else r[sort]),r['id']))
        assert state['rows'] == expected[offset:offset+25]
        assert page['total'] == len(expected)
        assert rendered[0] == state['rows']
    asyncio.run(run())


def test_save_finished_after_navigation_keeps_the_new_page():
    async def run():
        state = dict(resource='roles', rows=[{'id':1,'name':'Earlier'}])
        destination_rows = [{'id':9,'name':'Organization page'}]
        async def create(*args):
            # The user navigates while the save request is in flight.
            state.update(resource='org-units',rows=destination_rows)
            return {'id':2,'name':'New role','version':1}
        scope = dict(ApiError=ApiError, state=state, spec=ENTITIES['roles'],
                     creating=True, translation_only=False, on_saved=None,
                     prepare_entity_translation_update=None, controls={},
                     form_payload=lambda *a, **k:{'name':'New role'},
                     api=SimpleNamespace(create=create), dialog=Mock(), ui=Mock(),
                     render_message=render_message, strip_diagnostic_metadata=strip_diagnostic_metadata,
                     editor_entity='role', load_rows=AsyncMock())
        exec(compile(ast.Module(body=[SAVE],type_ignores=[]),'<actual-editor-save>','exec'),scope)
        await scope['save']()
        scope['load_rows'].assert_not_awaited()
        assert state['resource']=='org-units' and state['rows'] is destination_rows
    asyncio.run(run())
