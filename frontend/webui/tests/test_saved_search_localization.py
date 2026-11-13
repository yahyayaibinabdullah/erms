"""Dynamic saved-search actions resolve translations for their owning page."""
import ast
import json
from pathlib import Path
from unittest.mock import MagicMock

from nicegui import Client, ui

from frontend.webui.i18n_catalogue import (
    clear_active_messages, render_message, set_active_messages,
)


def test_saved_search_refresh_uses_owning_page_catalogue():
    root = Path(__file__).parents[1]
    arabic = {item['message_key']: item['translated_text'] for item in
              json.loads((root / 'i18n/messages.ar.generated.json').read_text())['items']}
    function = next(node for node in ast.walk(ast.parse((root / 'advanced_search.py').read_text()))
                    if isinstance(node, ast.FunctionDef) and node.name == 'refresh_saved_actions')
    client = Client(ui.page('/saved-search-localization-test'), request=None)
    try:
        with client:
            set_active_messages(arabic)
            button = ui.button('')
        scope = {name: MagicMock() for name in (
            'search_name', 'search_category', 'search_description', 'target',
            'sort_field', 'sort_direction', 'page_size',
            'reset_advanced', 'builder_host', 'search_advanced',
            'edit_details_button', 'save_as_button', 'delete_button',
            'render_saved_context',
        )}
        workspace = {'busy': False, 'saved': {'capabilities': {'update': True, 'execute': True}}}
        scope.update(workspace=workspace, privileges={'search.saved_search.save'},
                     validate_builder=lambda: (None, None), save_button=button,
                     render_message=render_message)
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<saved-actions>', 'exec'), scope)
        # Simulate a navigation callback with an English ambient context.
        set_active_messages({})
        for saved, key in (
            (workspace['saved'], 'webui.refresh_saved_actions.text.update_saved_search_31788e51'),
            (None, 'webui.refresh_saved_actions.text.save_search_76b8ff5b'),
            (workspace['saved'], 'webui.refresh_saved_actions.text.update_saved_search_31788e51'),
        ):
            workspace['saved'] = saved
            scope['refresh_saved_actions']()
            assert button.text == arabic[key]
    finally:
        clear_active_messages(client.id)
        client.delete()
        set_active_messages({})
