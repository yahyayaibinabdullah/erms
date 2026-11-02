"""Dependency failures retain the actionable prerequisite details."""
import ast
from pathlib import Path
from types import SimpleNamespace
from frontend.webui.i18n_catalogue import render_message_plain


def test_missing_prerequisites_are_named_in_save_feedback():
    tree = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'error_message')
    namespace = {'ApiError': object, 'render_message_plain': render_message_plain}
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'app.py', 'exec'), namespace)
    message = namespace['error_message'](SimpleNamespace(status_code=422, message='', detail={
        'code': 'privilege_dependency_violation', 'missing': [
            {'privilege_code': 'record.modify', 'required_code': 'record.view'},
            {'privilege_code': 'aggregation.modify', 'required_code': 'aggregation.view'},
        ],
    }))
    for code in ('record.modify', 'record.view', 'aggregation.modify', 'aggregation.view'):
        assert code in message
    assert 'Select the required privilege before saving.' in message
    assert 'highlighted information' not in message
