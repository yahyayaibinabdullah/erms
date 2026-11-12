"""Supported collection entries keep their specialized views and refresh paths."""
import inspect
from unittest.mock import Mock

import pytest
from nicegui import ui

from frontend.webui.collection_table import build_collection_table
from frontend.webui.collection_controls import build_collection_loader
from frontend.webui.collection_navigation import build_collection_navigation
from frontend.webui.entities import ENTITIES
from frontend.webui import i18n_catalogue as i18n

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


async def test_resource_without_collection_cannot_render_load_or_navigate():
    dependencies = {name: Mock() for name in inspect.signature(build_collection_table).parameters}
    with pytest.raises(ValueError, match='no collection page'):
        build_collection_table(**dependencies)(ENTITIES['classification-schemes'])
    dependencies['table_container'].clear.assert_not_called()

    for factory in (build_collection_loader, build_collection_navigation):
        values = {name: Mock() for name in inspect.signature(factory).parameters}
        if factory is build_collection_loader:
            values['get_resource'] = lambda: 'classification-schemes'
            with pytest.raises(KeyError):
                await factory(**values)()
            values['api'].search_request.assert_not_called()
        else:
            with pytest.raises(KeyError):
                await factory(**values)('classification-schemes')
            values['register_navigation'].assert_not_called()
            values['set_resource'].assert_not_called()


@pytest.mark.parametrize('resource', ['aggregations', 'records'])
@pytest.mark.parametrize('searched', [False, True])
@pytest.mark.parametrize('arabic', [False, True])
async def test_resource_refresh_keeps_compact_results_and_personal_sections(
    user, resource, searched, arabic,
):
    calls = []
    key = 'webui.select_entity.text.search_required_before_loading_results_88549c49'
    labels = {key: 'يجب إجراء بحث قبل تحميل النتائج'} if arabic else {}

    @ui.page('/')
    def page():
        i18n.set_active_messages(labels)
        dependencies = {name: Mock(side_effect=AssertionError(name))
                        for name in inspect.signature(build_collection_table).parameters}
        dependencies.update(
            collection_state={'searched': searched, 'rows': []},
            guidance=ui.label(), subtitle=ui.label(), table_container=ui.column(),
            render_entity_compact_results=lambda spec: calls.append(('compact', spec.key)),
            render_resource_personal_sections=lambda spec: calls.append(('personal', spec.key)),
        )
        render = build_collection_table(**dependencies)
        # Initial presentation and repeated refresh must never fall through to
        # the obsolete generic-table actions or require their dependencies.
        render(ENTITIES[resource])
        render(ENTITIES[resource])
        assert dependencies['subtitle'].text == (
            '' if searched else labels.get(key, i18n.render_english(key))
        )

    await user.open('/')
    expected = ([('compact', resource)] if searched else []) + [('personal', resource)]
    assert calls == expected * 2
    assert not any(isinstance(element, ui.table) for element in user.client.elements.values())
