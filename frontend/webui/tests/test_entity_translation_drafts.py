"""Draft acknowledgements, version fences and exact retry boundaries."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from frontend.webui.api_client import ApiError
from frontend.webui.entity_translation_drafts import EntityTranslationDrafts


def state():
    drafts = EntityTranslationDrafts(('title', 'description'))
    row = {'id': 17, 'version': 3, 'translations': {'ar': {'title': 'الأصل', 'description': 'قديم'}}}
    drafts.loaded('ar', {'version': 3, 'fields': row['translations']['ar']}, row)
    drafts.loaded('en', {'version': 3, 'fields': {}}, row)
    return drafts, row


@pytest.mark.asyncio
async def test_partial_acknowledgements_chain_versions_and_retry_only_unsaved_locales():
    drafts, row = state()
    drafts.values['ar'] = {'title': 'جديد', 'description': ''}
    drafts.values['en'] = {'title': 'English', 'description': 'Description'}
    drafts.reasons = {'ar': 'Arabic review', 'en': 'English review'}
    api = SimpleNamespace(update_entity_translation=AsyncMock(side_effect=[{'version': 4}, ApiError(503, 'Unavailable')]))
    with pytest.raises(ApiError):
        await drafts.save(api, 'classifications', row, drafts.updates())
    assert row['version'] == 4 and row['translations']['ar'] == {'title': 'جديد'}
    assert drafts.dirty_languages() == ['en']
    assert api.update_entity_translation.call_args_list[0].args[3] == {'title': 'جديد', 'description': None}
    api.update_entity_translation.side_effect = None
    api.update_entity_translation.return_value = {'version': 5}
    await drafts.save(api, 'classifications', row, drafts.updates())
    assert [c.args[4] for c in api.update_entity_translation.call_args_list] == [3, 4, 4]
    assert drafts.dirty_languages() == [] and row['version'] == 5


def test_reverted_locale_is_not_saved_and_profile_reason_is_shared():
    drafts, _ = state()
    drafts.values['ar']['title'] = 'Changed'
    drafts.values['ar']['title'] = 'الأصل'
    drafts.values['en']['title'] = 'English'
    drafts.reasons['en'] = 'Local reason'
    assert drafts.updates() == [('en', {'title': 'English', 'description': None}, 'Local reason')]
    assert drafts.updates('Profile reason') == [('en', {'title': 'English', 'description': None}, 'Profile reason')]


def test_refresh_cannot_replace_dirty_values_or_rebase_a_different_version():
    drafts, row = state()
    drafts.values['ar']['title'] = 'Draft'
    drafts.loaded('ar', {'version': 3, 'fields': {'title': 'الأصل'}}, row)
    assert drafts.values['ar']['title'] == 'Draft'
    before = deepcopy((drafts.values, drafts.baselines, row))
    with pytest.raises(ApiError) as failure:
        drafts.loaded('en', {'version': 4, 'fields': {'title': 'Concurrent'}}, row)
    assert failure.value.status_code == 409
    assert (drafts.values, drafts.baselines, row) == before


@pytest.mark.asyncio
async def test_conflict_keeps_all_pending_values_reasons_and_last_accepted_version():
    drafts, row = state()
    drafts.values['en']['title'] = 'Draft'
    drafts.reasons['en'] = 'Review'
    api = SimpleNamespace(update_entity_translation=AsyncMock(side_effect=ApiError(409, 'Conflict')))
    before = deepcopy((drafts.values, drafts.baselines, drafts.reasons, row))
    with pytest.raises(ApiError):
        await drafts.save(api, 'classifications', row, drafts.updates())
    assert (drafts.values, drafts.baselines, drafts.reasons, row) == before
    assert not drafts.applied_any


def test_accepting_remove_drops_selected_translation_and_preserves_other_drafts():
    drafts, row = state()
    drafts.values['en']['title'] = 'Draft'
    drafts.reasons['en'] = 'Review'
    drafts.accepted('ar', {}, {'version': 4}, row)
    assert row['translations'] is None and row['version'] == 4
    assert drafts.values['ar'] == {'title': '', 'description': ''}
    assert drafts.dirty_languages() == ['en'] and drafts.reasons['en'] == 'Review'


def test_first_translation_on_json_null_cache_preserves_protected_row_shape():
    drafts = EntityTranslationDrafts(('name', 'description'))
    row = {'id': 1, 'version': 1, 'translations': None}
    drafts.loaded('ar', {'version': 1, 'fields': {}}, row)
    drafts.accepted('ar', {'name': 'اسم', 'description': None}, {'version': 2}, row)
    assert row['translations'] == {'ar': {'name': 'اسم'}} and row['version'] == 2


def test_new_clean_version_invalidates_older_language_snapshots_without_losing_reasons():
    drafts, row = state()
    drafts.reasons['ar'] = 'Review note'
    drafts.loaded('en', {'version': 4, 'fields': {'title': 'New English'}}, row)
    assert row['version'] == 4 and set(drafts.values) == {'en'}
    assert 'ar' not in drafts.baselines and drafts.reasons['ar'] == 'Review note'
    drafts.loaded('ar', {'version': 4, 'fields': {'title': 'Concurrent Arabic'}}, row)
    assert drafts.values['ar']['title'] == 'Concurrent Arabic'
