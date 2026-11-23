"""Classification display preserves canonical data and session-local navigation."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from frontend.webui.api_client import ApiError
from frontend.webui.classification_labels import (
    classification_title, refresh_classification_navigation, update_classification_navigation,
)
from frontend.webui.aggregation_presentation import direct_classification_label


@pytest.mark.parametrize('localized,expected', [
    (None, 'Canonical'), ({}, 'Canonical'), ({'title': None}, 'Canonical'),
    ({'title': ''}, 'Canonical'), ({'title': '\u2003 \t'}, 'Canonical'),
    ({'title': 'عنوان الاختبار'}, 'عنوان الاختبار'),
    ({'title': 'English title'}, 'English title'),
])
def test_effective_title_fallback_preserves_entity(localized, expected):
    row = dict(id=1, code='001', title='Canonical', localized=localized,
               translations={'ar': {'title': 'Must not select client-side'}})
    before = deepcopy(row)
    assert classification_title(row) == expected
    assert direct_classification_label([row]) == f'001 — {expected}'
    assert row == before


def test_breadcrumbs_revalidate_once_per_reference_and_destination_uses_detail_response():
    async def exercise():
        scheme = dict(id=1, code='S', title='Scheme', localized={'title': 'المخطط'})
        node = dict(id=2, code='C', title='Node', localized={'title': 'التصنيف'})
        trail = [dict(page='classification-scheme-details', entity_id=1, label='old') for _ in range(2)]
        trail += [dict(page='classification-details', entity_id=2, label='old')]
        api = SimpleNamespace(get=AsyncMock(return_value=scheme))
        await refresh_classification_navigation(api, trail)
        api.get.assert_awaited_once_with('classification-schemes', 1)
        assert [entry['label'] for entry in trail[:2]] == ['S — المخطط'] * 2
        update_classification_navigation(trail, 'classification-details', node)
        assert trail[-1]['label'] == trail[-1]['accessible_label'] == 'C — التصنيف'
        # A reload in English obtains the new projection rather than cached Arabic.
        api.get.return_value = {**scheme, 'localized': {'title': 'Scheme'}}
        await refresh_classification_navigation(api, trail)
        assert trail[0]['label'] == 'S — Scheme'
        assert scheme['title'] == 'Scheme'
    asyncio.run(exercise())


def test_navigation_refresh_removes_unavailable_references_and_uses_identity_on_transient_failure():
    async def exercise():
        trail = [dict(page='classification-details', entity_id=2, label='Private'), dict(page='dashboard')]
        api = SimpleNamespace(get=AsyncMock(side_effect=ApiError(403, 'Denied')))
        await refresh_classification_navigation(api, trail)
        assert trail == [dict(page='dashboard')]
        trail.insert(0, dict(page='classification-details', entity_id=2, label='C — Previous language'))
        api.get.side_effect = ApiError(503, 'Unavailable')
        await refresh_classification_navigation(api, trail)
        assert trail[0]["label"] == trail[0]["accessible_label"] == "C"
    asyncio.run(exercise())


def test_navigation_labels_are_not_shared_across_clients():
    async def exercise():
        a = [dict(page='classification-details', entity_id=1), dict(page='dashboard')]
        b = deepcopy(a)
        api_a = SimpleNamespace(get=AsyncMock(return_value=dict(id=1, code='C', title='Canonical', localized={'title': 'عربي'})))
        api_b = SimpleNamespace(get=AsyncMock(return_value=dict(id=1, code='C', title='Canonical', localized={'title': 'English'})))
        await asyncio.gather(refresh_classification_navigation(api_a, a), refresh_classification_navigation(api_b, b))
        assert a[0]['label'] == 'C — عربي'
        assert b[0]['label'] == 'C — English'
    asyncio.run(exercise())


def test_initial_id_only_destination_does_not_replace_navigation_label():
    trail = [dict(page='classification-details', entity_id=2, label='Previous title')]
    update_classification_navigation(trail, 'classification-details', {'id': 2})
    assert trail[0]['label'] == 'Previous title'
    update_classification_navigation(trail, 'classification-details', {
        'id': 2, 'code': 'C', 'title': 'Canonical', 'localized': {'title': 'التصنيف'},
    })
    assert trail[0]['label'] == trail[0]['accessible_label'] == 'C — التصنيف'
