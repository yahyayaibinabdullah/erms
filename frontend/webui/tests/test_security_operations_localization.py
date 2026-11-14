"""Security explanations must resolve per session rather than at module import."""
import ast
import json
from pathlib import Path

from frontend.webui.i18n_catalogue import render_message, set_active_messages


def test_security_explanations_follow_current_session_language():
    root = Path(__file__).parents[1]
    module = ast.parse((root / 'security_operations.py').read_text())
    loader = next(node for node in ast.walk(module)
                  if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == 'render_security_operations')
    assignments = [node for node in loader.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id in {
                       'security_event_help', 'authorization_denial_help'
                   } for target in node.targets)]
    assert len(assignments) == 2
    code = compile(ast.Module(body=assignments, type_ignores=[]), '<security-help>', 'exec')
    arabic = {item['message_key']: item['translated_text'] for item in
              json.loads((root / 'i18n/messages.ar.generated.json').read_text())['items']}
    english = {item['message_key']: item['default_text'] for item in
               json.loads((root / 'i18n/messages.en.json').read_text())}
    try:
        # Repeated rendering and switching back must not retain another session's text.
        for messages in (english, arabic, english, arabic):
            set_active_messages(messages)
            scope = {'render_message': render_message}
            exec(code, scope)
            for key, value in zip(assignments[0].value.keys, assignments[0].value.values):
                assert scope['security_event_help'][key.value] == messages[value.args[0].value]
            assert scope['authorization_denial_help'] == messages[assignments[1].value.args[0].value]
    finally:
        set_active_messages({})


def test_event_catalogue_covers_emitters_and_preserves_codes():
    import re
    from frontend.webui.event_labels import EVENT_MESSAGE_KEYS, event_label
    root = Path(__file__).parents[3]
    sources = [root / 'database/schema.sql', *sorted((root / 'backend/services/api').glob('*.py'))]
    codes = {'CREATE', 'UPDATE', 'DELETE'}
    for path in sources:
        text = path.read_text()
        # Literal SQL emitters, including SQL embedded in Python.
        codes.update(re.findall(r"append_domain_event\([^,]+,[^,]+,\s*'([A-Z_]+)'", text))
        if path.suffix == '.py':
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'_append_event', '_append_content_event'} and len(node.args) >= 3:
                    codes.update(child.value for child in ast.walk(node.args[2]) if isinstance(child, ast.Constant) and isinstance(child.value, str) and re.fullmatch('[A-Z_]+', child.value))
            if path.name == 'security_operations.py':
                assignment = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SECURITY_OPERATIONS' for t in n.targets))
                codes.update(ast.literal_eval(assignment.value))
    assert codes <= EVENT_MESSAGE_KEYS.keys(), codes - EVENT_MESSAGE_KEYS.keys()
    artifact = json.loads((root / 'frontend/webui/i18n/messages.ar.generated.json').read_text())
    arabic = {i['message_key']: i['translated_text'] for i in artifact['items']}
    try:
        set_active_messages(arabic)
        for code, key in EVENT_MESSAGE_KEYS.items():
            assert event_label(code) == arabic[key]
        assert event_label('INTEGRATION_UNKNOWN_EVENT') == 'INTEGRATION_UNKNOWN_EVENT'
    finally:
        set_active_messages({})


def test_security_refresh_restores_client_context_before_rendering():
    tree = ast.parse((Path(__file__).parents[1] / 'security_operations.py').read_text())
    loader = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'load_security_operations')
    assert isinstance(loader.body[0], ast.With)
    assert loader.body[0].items[0].context_expr.id == 'page_client'
    assert loader.body[0].body[0].value.value.func.id == 'render_security_operations'
