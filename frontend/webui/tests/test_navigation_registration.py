"""Current registration order and restoration behavior before coordinator extraction."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from frontend.webui.navigation_data import append_navigation_entry
from frontend.webui.personal_resources import PersonalResourceState


def host():
    tree = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'prepare_navigation')
    calls = Mock()
    h = {'Any': object, 'api': SimpleNamespace(cancel_pending_reads=calls.cancel),
         'personal': PersonalResourceState(),
         'state': dict(search_diagnostics_sent='old', search_diagnostics_accepted='old', search_diagnostics_error='old'),
         'content_card': SimpleNamespace(classes=calls.classes), 'set_active_drawer_link': calls.drawer,
         'set_page_title_icon': calls.icon, 'navigation_state': {'trail': [{'page': 'dashboard', 'state': {}}], 'restoring': False},
         'current_navigation_snapshot': Mock(return_value={'search_text': 'retained'}),
         'breadcrumb_message_keys': {'records': 'navigation.item.records'},
         'append_navigation_entry': append_navigation_entry, 'persist_navigation_trail': calls.persist,
         'render_navigation_breadcrumbs': calls.render, 'calls': calls}
    h['global_search_state'] = h['state']
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<host presentation>', 'exec'), h)
    from frontend.webui.navigation_controller import NavigationController
    h['controller'] = NavigationController(
        stored=h['navigation_state']['trail'], write_trail=lambda trail: calls.persist(),
        prepare=h['prepare_navigation'], snapshot=h['current_navigation_snapshot'],
        label_key=h['breadcrumb_message_keys'].get, get_guard=lambda: None,
        clear_guard=Mock(), cancel_reads=calls.cancel, restore=Mock(), dashboard=Mock(),
        render=calls.render, notify=Mock(), on_error=str,
    )
    h['register_navigation'] = h['controller'].register_navigation
    return h


def test_registration_saves_previous_snapshot_then_new_visit():
    h = host()
    h['register_navigation']('records', 'Records', accessible_label='Open records')
    trail = h['controller'].trail
    assert trail[0]['state'] == {'search_text': 'retained'}
    assert trail[1] == {'page': 'records', 'label': 'Records', 'label_key': 'navigation.item.records',
                        'dynamic_label': False, 'entity_id': None, 'accessible_label': 'Open records', 'state': {}}
    assert [c[0] for c in h['calls'].mock_calls] == ['cancel', 'classes', 'drawer', 'icon', 'persist', 'render']
    assert all(value is None for value in h['state'].values())
    assert h['personal'].navigation_revision == 1


def test_restoration_updates_shell_and_cancels_reads_without_adding_history():
    h = host(); original = h['controller'].trail
    h['controller'].restoring = True
    h['register_navigation']('records', 'Records')
    assert h['controller'].trail is original
    assert original == [{'page': 'dashboard', 'state': {}}]
    h['current_navigation_snapshot'].assert_not_called()
    h['calls'].persist.assert_not_called()
    h['calls'].render.assert_not_called()
    assert [c[0] for c in h['calls'].mock_calls] == ['cancel', 'classes', 'drawer', 'icon']


def test_dynamic_entity_label_retains_identity_without_static_translation_key():
    h = host()
    h['register_navigation']('record-details', 'Record title', entity_id=8, dynamic_label=True)
    entry = h['controller'].trail[-1]
    assert entry['entity_id'] == 8 and entry['label_key'] is None
    assert entry['dynamic_label'] is True and entry['accessible_label'] == 'Record title'


@pytest.mark.parametrize('page,expected', [('dashboard', {'add': 'erms-dashboard-card'}), ('records', {'remove': 'erms-dashboard-card'})])
def test_existing_dashboard_card_presentation_is_selected(page, expected):
    h = host(); h['register_navigation'](page, page)
    h['calls'].classes.assert_called_once_with(**expected)


def test_search_registration_keeps_its_current_diagnostics():
    h = host(); h['register_navigation']('full-text-search', 'Search results')
    assert all(value == 'old' for value in h['state'].values())
