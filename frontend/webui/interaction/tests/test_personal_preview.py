"""Exercise the live favourites preview and complete list, replacing a dead helper test."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import Client, ui
from frontend.webui.entities import ENTITIES
from frontend.webui.i18n_catalogue import clear_active_messages, set_active_messages
from frontend.webui.personal_resources import PersonalResourceState
from frontend.webui.personal_resource_views import build_personal_resource_views


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('resource', ['records', 'aggregations'])
@pytest.mark.parametrize('count', [0, 2, 3])
def test_configured_preview_limit_keeps_complete_list_reachable(language, resource, count):
    client = Client(ui.page('/personal-preview-contract'), request=None)
    try:
        with client:
            messages = json.loads((Path(__file__).parents[2] / 'i18n/messages.ar.generated.json').read_text())
            set_active_messages({item['message_key']: item['translated_text'] for item in messages['items']} if language == 'ar' else {})
            personal = PersonalResourceState()
            personal.favourites[resource] = [{'id': i, 'title': f'Favourite {i}'} for i in range(count)]
            api = Mock()
            views = build_personal_resource_views(
                api, personal, get_configuration=lambda: {'DASHBOARD_FAVOURITE_ITEM_LIMIT': 2},
                render_table=Mock(), open_aggregation=AsyncMock(), show_record_details=AsyncMock(),
                toggle_favourite=AsyncMock(), error_message=str,
                format_timestamp=str, personal_dialog_list_height=lambda count: 300,
            )
            views.render_resource_personal_sections(ENTITIES[resource])
            rows = [e for e in client.elements.values() if 'dashboard-personal-item' in e.classes]
            assert len(rows) == min(count, 2)
            panels = [e for e in client.elements.values() if 'dashboard-personal-panel' in e.classes]
            view_all = next(e for e in panels[0].descendants() if isinstance(e, ui.button))
            # View all remains available even when the preview is empty/full.
            next(e.handler for e in view_all._event_listeners.values() if e.type == 'click')(None)
            dialog = next(e for e in client.elements.values() if isinstance(e, ui.dialog))
            assert dialog.value
            complete = [e for e in dialog.descendants() if 'dashboard-personal-item' in e.classes]
            assert len(complete) == count
            api.get.assert_not_called()
    finally:
        clear_active_messages(client.id)
        client.delete()
        set_active_messages({})
