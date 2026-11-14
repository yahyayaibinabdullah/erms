from frontend.webui.tests.search_sources import search_sources
import ast
import asyncio
import pytest
from pathlib import Path
from types import SimpleNamespace


@pytest.mark.parametrize("multiple", [True, False])
def test_audience_paging_keeps_selected_values_and_resets_offset_for_new_query(multiple):
    source = ast.parse(search_sources())
    binder = next(n for n in ast.walk(source) if isinstance(n, ast.FunctionDef) and n.name == 'bind_remote_saved_audience_select')
    calls = []
    async def page(kind, **kwargs):
        calls.append(kwargs)
        offset = kwargs['offset']
        rows = [{'id': i, 'name': f'Role {i}', 'code': f'R{i}'} for i in range(offset + 1, min(offset + 26, 31))]
        return {'items': rows, 'total': 30}
    class Control:
        def __init__(self):
            self.multiple = multiple
            self.value = [99] if multiple else 99
            self.options = {99: 'Selected role'}
        def update(self): pass
        def on(self, *args): pass
        def on_value_change(self, callback): self.changed = callback
        def run_method(self, *args): self.method_call = args
    class Button:
        def set_visibility(self, value): self.visible = value
        def on(self, *args): pass
    namespace = {'Any': object, 'Callable': __import__('typing').Callable, 'asyncio': asyncio,
                 'api': SimpleNamespace(saved_search_audience_options=page),
                 'strip_diagnostic_metadata': lambda text: text, 'ApiError': RuntimeError}
    exec(compile(ast.Module(body=[binder], type_ignores=[]), 'binder', 'exec'), namespace)
    control, button = Control(), Button()
    load, _ = namespace['bind_remote_saved_audience_select'](control, 'roles', button)
    async def run():
        if multiple:
            control.changed()
            assert control.method_call == ('updateInputValue', '')
            assert control.value == [99]
        await load('Role')
        assert len(control.options) == 26 and button.visible
        await load('Role', append=True)
        assert len(control.options) == 31 and not button.visible
        assert control.options[99] == 'Selected role' and control.value == ([99] if multiple else 99)
        await load('Other')
        assert [call['offset'] for call in calls] == [0, 25, 0]
        assert all(call['limit'] == 25 for call in calls)
        assert 30 not in control.options and 99 in control.options
    asyncio.run(run())


def test_every_audience_binder_call_supplies_load_more_button():
    source = ast.parse(search_sources())
    calls = [node for node in ast.walk(source) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == 'bind_remote_saved_audience_select']
    assert len(calls) == 4
    assert all(len(call.args) == 3 for call in calls)


def test_saved_search_tabs_use_api_scope_ids_separate_from_translated_labels():
    source = ast.parse(search_sources())
    dialog = next(node for node in ast.walk(source) if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == 'open_saved_search_dialog')
    tabs = [node for node in ast.walk(dialog) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == 'tab']
    assert [ast.literal_eval(tab.args[0]) for tab in tabs] == ['all', 'owned', 'shared_with_me']
    assert all(any(keyword.arg == 'label' and isinstance(keyword.value, ast.Call)
                   for keyword in tab.keywords) for tab in tabs)


def test_saved_audience_ancestor_cannot_be_selected():
    source = ast.parse((Path(__file__).parents[1] / 'organization_browser.py').read_text())
    browser = next(n for n in ast.walk(source) if isinstance(n, ast.AsyncFunctionDef)
                   and n.name == 'show_organization_structure')
    predicate = next(n for n in ast.walk(browser) if isinstance(n, ast.FunctionDef)
                     and n.name == 'node_selectable')
    namespace = {'Any': object, 'is_selector': True, 'selection_mode': 'org_unit',
                 'saved_audience': 'org-units'}
    exec(compile(ast.Module(body=[predicate], type_ignores=[]), 'predicate', 'exec'), namespace)
    selectable = namespace['node_selectable']
    node = {'type': 'org_unit', 'status': 'active'}
    assert not selectable(node)
    assert not selectable({**node, 'audience_selectable': False})
    assert selectable({**node, 'audience_selectable': True})
    assert not selectable({**node, 'audience_selectable': True, 'effective_status': 'inactive'})
    namespace['saved_audience'] = None
    assert selectable(node)


def test_saved_audience_scope_survives_every_browser_page_and_search():
    source = ast.parse((Path(__file__).parents[1] / 'organization_browser.py').read_text())
    browser = next(n for n in ast.walk(source) if isinstance(n, ast.AsyncFunctionDef)
                   and n.name == 'show_organization_structure')
    calls = [n for n in ast.walk(browser) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr in
             {'organization_roots', 'organization_children', 'search_organization'}]
    params = next(node.value for node in ast.walk(browser) if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == 'params' for target in node.targets)
                  and isinstance(node.value, ast.Dict))
    assert {call.func.attr for call in calls} == {'organization_roots', 'organization_children', 'search_organization'}
    for call in calls:
        if call.func.attr == 'search_organization':
            assert any(k.arg is None and isinstance(k.value, ast.Name) and k.value.id == 'params'
                       for k in call.keywords)
            scope = next(value for key, value in zip(params.keys, params.values)
                         if isinstance(key, ast.Constant) and key.value == 'audience')
        else:
            scope = next(k.value for k in call.keywords if k.arg == 'audience')
        assert isinstance(scope, ast.Name) and scope.id == 'saved_audience'
