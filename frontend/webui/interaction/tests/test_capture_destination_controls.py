"""Exercise the actual editor callbacks without an API or persistent database."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from nicegui import Client, ui

SOURCE = Path(__file__).parents[2] / 'record_capture.py'
TREE = ast.parse(SOURCE.read_text())


@pytest.fixture
def editor_client():
    """Own the control slot explicitly, independent of other tests' resets."""
    client = Client(ui.page('/capture-controls-test'), request=None)
    try:
        with client:
            yield client
    finally:
        client.delete()

def callback(name, scope):
    node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), scope)
    return scope[name]

@pytest.mark.parametrize('parent_medium', [None, 'digital', 'mixed'])
def test_capture_medium_remains_digital_before_and_after_parent_selection(parent_medium, editor_client):
    control = ui.select({'digital':'Digital','mixed':'Mixed'}, value='digital')
    scope = dict(controls={'medium':control,'aggregation_id':SimpleNamespace(value=1)},
                 aggregations_by_id={1:{'medium':parent_medium}} if parent_medium else {},
                 existing_capture_draft={'medium':'digital'},medium_options=lambda:{'digital':'Digital','mixed':'Mixed'})
    callback('constrain_record_medium', scope)()
    assert control.value == 'digital'
    assert not control.enabled
    assert list(control.options) == ['digital']

@pytest.mark.asyncio
async def test_destination_typeahead_is_bounded_and_does_not_preload():
    calls=[]
    async def search(*args,**kwargs):
        calls.append((args,kwargs))
        return {'items':[]}
    scope=dict(api=SimpleNamespace(search_request=search),existing_capture_draft={})
    search_destinations=callback('destinations',scope)
    assert await search_destinations('') == {'items':[]}
    assert await search_destinations('a') == {'items':[]}
    assert not calls
    await search_destinations('ab')
    assert calls[0][0][1]['limit']==25
    assert calls[0][1]=={'record_creation':True,'digital_only':True}


def test_ordinary_record_medium_remains_editable_in_mixed_parent(editor_client):
    control = ui.select({'digital':'Digital','mixed':'Mixed','physical':'Physical'}, value='mixed')
    scope = dict(controls={'medium':control,'aggregation_id':SimpleNamespace(value=1)},
                 aggregations_by_id={1:{'medium':'mixed'}},existing_capture_draft=None,
                 medium_options=lambda:{'digital':'Digital','mixed':'Mixed','physical':'Physical'})
    callback('constrain_record_medium', scope)()
    assert control.value == 'mixed' and control.enabled
    assert set(control.options) == {'digital','mixed','physical'}
