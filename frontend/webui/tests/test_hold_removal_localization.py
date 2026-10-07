"""Hold-removal callbacks localize their indirectly rendered dialog strings."""
import ast
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

from frontend.webui.i18n_catalogue import render_message, set_active_messages


def test_record_and_aggregation_hold_removal_dialogs_use_arabic():
    root = Path(__file__).parents[1]
    arabic = {i['message_key']: i['translated_text'] for i in
              json.loads((root / 'i18n/messages.ar.generated.json').read_text())['items']}
    tree = ast.parse((root / 'app.py').read_text())
    set_active_messages(arabic)
    try:
        for name in ('remove_record_from_all_holds', 'remove_aggregation_from_all_holds'):
            function = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
            dialog = AsyncMock()
            scope = dict(render_message=render_message, hold_reason_dialog=dialog)
            exec(compile(ast.Module(body=[function], type_ignores=[]), '<hold-removal>', 'exec'), scope)
            asyncio.run(scope[name]())
            title, action, _ = dialog.call_args.args
            assert title == arabic['webui.hold_reason_dialog.remove_all_confirmation']
            assert action == arabic['webui.open_aggregation.button.remove_direct_holds_d5ecb7ae']
    finally:
        set_active_messages({})


def test_hold_update_reason_dialog_localizes_title_and_action_in_both_languages():
    root = Path(__file__).parents[1]
    arabic = {item['message_key']: item['translated_text'] for item in
              json.loads((root / 'i18n/messages.ar.generated.json').read_text())['items']}
    tree = ast.parse((root / 'app.py').read_text())
    editor = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == 'open_hold_editor')
    save = next(n for n in ast.walk(editor) if isinstance(n, ast.AsyncFunctionDef)
                and n.name == 'save')
    for messages, expected in [({}, ('Reason for updating this hold', 'Update hold')),
                               (arabic, (arabic['webui.hold_reason_dialog.update_title'], arabic['webui.hold_reason_dialog.update_action']))]:
        set_active_messages(messages)
        try:
            dialog, persist = AsyncMock(), AsyncMock()
            scope = dict(render_message=render_message, hold_reason_dialog=dialog,
                         editing=True, persist=persist)
            exec(compile(ast.Module(body=[save], type_ignores=[]), '<hold-update>', 'exec'), scope)
            asyncio.run(scope['save']())
            assert dialog.call_args.args == (*expected, persist)
            persist.assert_not_called()
        finally:
            set_active_messages({})
