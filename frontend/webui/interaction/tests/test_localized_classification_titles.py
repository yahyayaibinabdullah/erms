"""Exercise PR #72 behavior through NiceGUI without importing its new helper."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nicegui import ui

from frontend.webui.interaction.tests import test_classification_workspace as workspace_tests
from frontend.webui.interaction.tests.test_classification_selectors import picker

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('direction,scheme_title,branch_title,node_title', [
    ('rtl', 'المخطط المترجم', 'الفرع المترجم', 'التصنيف المترجم'),
    ('ltr', 'Translated scheme', 'Translated branch', 'Translated classification'),
])
async def test_workspace_uses_effective_titles_and_keeps_canonical_editor_values(
    user, monkeypatch, direction, scheme_title, branch_title, node_title,
):
    api = workspace_tests.Api()
    for row, title in [(api.schemes[0], scheme_title), (api.nodes[0], branch_title),
                        (api.nodes[-1], node_title)]:
        # An Arabic canonical value with an English projection exercises the
        # reverse direction as well as the ordinary English-to-Arabic case.
        if direction == 'ltr':
            row['title'] = 'العنوان الأصلي'
        row['localized'] = {'title': title}
    canonical = deepcopy(api.nodes[-1])
    monkeypatch.setattr(workspace_tests, 'Api', lambda: api)
    _, editor, pages, _ = await workspace_tests.open_workspace(
        user, preferences={'expanded_schemes': [1], 'expanded': [1]}, direction=direction,
    )
    await user.should_see('— ' + scheme_title)
    await user.should_see('— ' + branch_title)
    await user.should_see('— ' + node_title)
    await user.should_see('— Node 2')  # Missing projections retain canonical labels.
    workspace_tests.button(user, label='1000 — ' + node_title).click()
    await user.should_see('0001 — ' + branch_title)
    assert pages[-1][1]['title'] == canonical['title']
    workspace_tests.button(user, label='Edit').click()
    await asyncio.sleep(.03)
    assert editor.call_args.args[0]['title'] == canonical['title']
    assert api.nodes[-1] == canonical


@pytest.mark.parametrize('kind', ['editor', 'advanced'])
@pytest.mark.parametrize('direction,translated', [('rtl', 'العنوان المترجم'),
                                                ('ltr', 'Translated title')])
async def test_classification_picker_displays_translation_and_selects_stable_id(
    user, kind, direction, translated,
):
    canonical = 'Canonical title' if direction == 'rtl' else 'العنوان الأصلي'
    scheme_title = 'مخطط مترجم' if direction == 'rtl' else 'Translated scheme'
    rows = {
        'classification-schemes': [dict(id=1, code='S', title=canonical,
                                       localized={'title': scheme_title})],
        'classifications': [dict(id=2, code='C', title=canonical, is_terminal=True,
                                localized={'title': translated})],
    }
    before = deepcopy(rows)
    api = SimpleNamespace(list=AsyncMock(side_effect=lambda resource, **_: rows[resource]))
    holder = {}

    @ui.page('/localized-title-regression')
    async def page():
        holder['control'] = ui.select({99: 'Existing selection'}, value=99)
        await picker(api, kind, direction)(holder['control'])

    def choose_visible_title(text):
        label = next(e for e in user.find(ui.label).elements if e.text == text)
        card = label.parent_slot.parent
        while not isinstance(card, ui.card):
            card = card.parent_slot.parent
        marker = f'translated-choice-{card.id}'
        card.mark(marker)
        user.find(marker=marker).click()

    await user.open('/localized-title-regression')
    await user.should_see(scheme_title)
    choose_visible_title(scheme_title)
    await user.should_see(translated)
    choose_visible_title(translated)
    await asyncio.sleep(.03)
    assert holder['control'].value == 2
    assert holder['control'].options[2] == 'C · ' + translated
    assert holder['control'].options[99] == 'Existing selection'
    assert rows == before
