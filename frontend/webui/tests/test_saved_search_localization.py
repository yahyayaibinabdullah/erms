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


def test_open_rechecks_permission_after_the_list_was_loaded():
    import asyncio
    from unittest.mock import AsyncMock
    from frontend.webui.api_client import ApiError

    source = (Path(__file__).parents[1] / 'advanced_search.py').read_text()
    action = next(node for node in ast.walk(ast.parse(source))
                  if isinstance(node, ast.AsyncFunctionDef) and node.name == 'select_saved_search')
    old = {"id": 9, "definition": {"request": {"sort": [{"field": "type.3.field.5"}]}}}
    fresh = {"id": 9, "version": 4, "definition": {"request": {}}}
    api = MagicMock()
    api.saved_search = AsyncMock(side_effect=[
        ApiError(403, {"code": "saved_search_type_forbidden"}), fresh,
    ])
    load = MagicMock()
    update = AsyncMock()
    scope = dict(Any=object, api=api, ApiError=ApiError, ui=MagicMock(), error_message=str,
                 confirm_discard_changes=AsyncMock(return_value=True), dialog=MagicMock(),
                 search_view_is_current=lambda: True, load_saved_into_workspace=load,
                 load_saved_page=update, filters={"offset":25})
    exec(compile(ast.Module(body=[action],type_ignores=[]), '<open-saved>', 'exec'),scope)
    asyncio.run(scope['select_saved_search'](old))
    load.assert_not_called()
    update.assert_awaited_once_with(offset=25)
    asyncio.run(scope['select_saved_search'](old))
    load.assert_called_once_with(fresh)
