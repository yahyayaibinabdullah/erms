"""Exercise the actual condition renderer and NiceGUI numeric blur sanitizer."""
import ast
import json
from pathlib import Path

import pytest
from nicegui import Client, ui

from frontend.webui import app as webui
from frontend.webui.i18n_catalogue import clear_active_messages, set_active_messages

ROOT = Path(__file__).parents[2]
RENDER = next(node for node in ast.walk(ast.parse((ROOT / 'app.py').read_text()))
              if isinstance(node, ast.FunctionDef) and node.name == 'render_condition')


def render_condition(client, language, field, operator, value):
    with client:
        arabic = {item['message_key']: item['translated_text'] for item in
                  json.loads((ROOT / 'i18n/messages.ar.generated.json').read_text())['items']}
        set_active_messages(arabic if language == 'ar' else {})
        condition = dict(type='condition', kind='structured', field=field, operator=operator, value=value)
        scope = dict(vars(webui), workspace={'resource':'aggregations'},
                     auth_state={'principal':{}}, relation_sources={},
                     render_builder=lambda: None, update_search_enabled=lambda: None)
        exec(compile(ast.Module(body=[RENDER], type_ignores=[]), '<retention-condition>', 'exec'), scope)
        scope['render_condition'](condition, [condition], 0)
    return condition


@pytest.mark.parametrize('language', ['en','ar'])
@pytest.mark.parametrize('field', ['current_period_years','intermediate_period_years'])
@pytest.mark.parametrize('operator', ['eq','between'])
def test_retention_year_controls_accept_numeric_blur_without_type_errors(language,field,operator):
    client = Client(ui.page('/retention-numeric-check'), request=None)
    try:
        condition = render_condition(client, language, 'effective_retention.'+field,
                                     operator, [] if operator=='between' else None)
        controls = [element for element in client.elements.values() if isinstance(element,ui.number)]
        assert len(controls) == (2 if operator=='between' else 1)
        for control in controls:
            assert isinstance(control.min,(int,float)) and control.min==0
            assert control.props['step']==1
            control.value=0
            control.sanitize()  # Actual callback used by NiceGUI on blur.
            assert control.value==0
            control.value=5
            control.sanitize()
            assert control.value==5
        result=webui.compile_advanced_search_node(condition,'aggregations')
        assert result['value']==([5,5] if operator=='between' else 5)
    finally:
        clear_active_messages(client.id)
        client.delete()
        set_active_messages({})


@pytest.mark.parametrize('language', ['en','ar'])
def test_retention_action_set_uses_localized_multiselect_and_retains_values(language):
    client = Client(ui.page('/retention-action-check'), request=None)
    try:
        values=['destruction','selective_preservation']
        render_condition(client,language,'effective_retention.final_disposition','in',values)
        control=next(element for element in client.elements.values()
                     if isinstance(element,ui.select) and element.props.get('multiple'))
        assert control.value==values and len(control.options)==4
        assert control.options['destruction']==('الإتلاف' if language=='ar' else 'Destruction')
    finally:
        clear_active_messages(client.id)
        client.delete()
        set_active_messages({})
