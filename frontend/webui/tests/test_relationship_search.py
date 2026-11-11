from types import SimpleNamespace

import pytest
from nicegui import ui

from frontend.webui.entity_selectors import apply_relationship_selection
from frontend.webui.entity_selectors import relationship_options
from frontend.webui.entity_selectors import relationship_search_query
from frontend.webui.i18n_catalogue import (
    disable_diagnostic_metadata, enable_diagnostic_metadata,
    render_message, set_active_messages,
)


@pytest.mark.parametrize('language,name,level', [('en', 'General', 'Level'), ('ar', 'عام', 'المستوى')])
@pytest.mark.parametrize('inspector', [False, True])
def test_security_level_options_are_plain_with_or_without_inspector(language, name, level, inspector):
    key = 'webui.render_table.text.level_167db239'
    with ui.column() as host:
        client_id = host.client.id
        set_active_messages({key: level})
        if inspector:
            enable_diagnostic_metadata(client_id)
        try:
            # Prove inspector mode is active while the option remains plain.
            if inspector:
                assert '\u2063' in render_message(key)
            options = relationship_options(
                [{'id': 1, 'code': 'G', 'name': 'General',
                  'localized': {'name': name}, 'level_number': 0}],
                ('code', 'name'), include_level_number=True,
            )
            assert options == {1: f'G · {name} · {level} 0'}
        finally:
            disable_diagnostic_metadata(client_id)
            set_active_messages({})


@pytest.mark.parametrize('label', ['G · General · Level 0', 'G · عام · المستوى 0'])
def test_selected_label_echo_is_ignored_without_suppressing_searches(label):
    control = SimpleNamespace(value=1, options={1: label, 2: 'Confidential'}, multiple=False)
    assert relationship_search_query(control, label) is None
    assert relationship_search_query(control, 'G') == 'G'
    assert relationship_search_query(control, 'عام') == 'عام'
    assert relationship_search_query(control, 'Confidential') == 'Confidential'
    assert relationship_search_query(control, '') == ''
    control.value = None
    assert relationship_search_query(control, label) == label
    control.multiple = True
    control.value = [1]
    assert relationship_search_query(control, label) == label


@pytest.mark.parametrize('title', ['Employment records', 'ملفات التوظيف'])
def test_browsed_classification_populates_empty_remote_select(title):
    item = {'id': 42, 'code': '1111', 'title': 'Employment records',
            'localized': {'title': title}}
    with ui.column():
        control = ui.select({}, with_input=True)
        apply_relationship_selection(
            control, item['id'], relationship_options([item], ('code', 'title'))[item['id']],
        )
        assert control.value == 42
        assert control.options == {42: f'1111 · {title}'}
        assert relationship_search_query(control, control.options[42]) is None


@pytest.mark.parametrize('resource,fields,expected', [
    ('aggregations', ('aggregation_number', 'title'), ['aggregation_number', 'title', 'description']),
    ('records', ('title',), ['title', 'description']),
    ('records', ('title', 'description'), ['title', 'description']),
    ('roles', ('code', 'name'), ['code', 'name']),
])
@pytest.mark.parametrize('query', ['unique description', 'وصف مميز'])
def test_relationship_description_search_preserves_bounds_and_filters(resource, fields, expected, query):
    import asyncio
    from frontend.webui.api_client import ErmsApiClient
    calls = []
    async def search(resource, payload, **kwargs):
        calls.append((resource, payload, kwargs))
        return {'items': [], 'total': 0}
    client = SimpleNamespace(search_request=search)
    asyncio.run(ErmsApiClient.relationship_page(
        client, resource, fields, query, limit=25, offset=25, filters={'status': 'active'},
    ))
    _, payload, _ = calls[0]
    assert payload['limit'] == 25 and payload['offset'] == 25
    assert payload['sort'] == [{'field': fields[0], 'direction': 'asc'}]
    clauses = payload['where']['and']
    assert clauses[0] == {'field': 'status', 'operator': 'eq', 'value': 'active'}
    assert clauses[1]['or'] == [
        {'field': field, 'operator': 'contains_ci', 'value': query} for field in expected
    ]
