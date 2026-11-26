"""Creation retries preserve identity, accepted translations and optimistic versions."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from frontend.webui.api_client import ApiError
from frontend.webui.entity_creation import EntityCreation


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [403, 409, 422, 503])
async def test_partial_creation_retries_only_pending_locales_and_never_rebases(status):
    draft = EntityCreation(('title', 'description'),
                           translations={'ar': {'title': 'عنوان'}, 'en': {'title': 'Alternate'}})
    calls = []
    failure = True

    async def patch(resource, identity, language, values, version, reason):
        calls.append((resource, identity, language, deepcopy(values), version, reason))
        if failure and language == 'en':
            raise ApiError(status, 'Rejected')
        return {'version': version + 1}

    api = SimpleNamespace(create=AsyncMock(return_value={'id': 91, 'version': 7}),
                          update_entity_translation=patch)
    with pytest.raises(ApiError):
        await draft.save(api, 'classifications', {'retention_rule': {'current_period_years': 2}})
    assert draft.row == {'id': 91, 'version': 8, 'translations': {'ar': {'title': 'عنوان'}}}
    assert draft.translations == {'ar': {'title': 'عنوان'}, 'en': {'title': 'Alternate'}}
    failure = False
    saved = await draft.save(api, 'classifications', {})
    api.create.assert_awaited_once()
    assert [(c[2], c[4]) for c in calls] == [('ar', 7), ('en', 8), ('en', 8)]
    assert all(c[5] == 'Initial translations supplied during creation' for c in calls)
    assert saved['version'] == 9 and saved['translations'] == draft.translations
    assert not draft.pending()


@pytest.mark.asyncio
async def test_revised_partially_saved_translations_send_field_and_locale_removals():
    draft = EntityCreation(('name', 'description'), row={'id': 91, 'version': 8},
                           translations={'ar': {'name': 'اسم'}},
                           applied={'ar': {'name': 'اسم', 'description': 'وصف'}, 'en': {'name': 'Old'}})
    api = SimpleNamespace(create=AsyncMock(), update_entity_translation=AsyncMock(
        side_effect=[{'version': 9}, {'version': 10}]))
    await draft.save(api, 'users', {})
    api.create.assert_not_awaited()
    assert api.update_entity_translation.call_args_list[0].args == (
        'users', 91, 'ar', {'name': 'اسم', 'description': None}, 8, 'Initial translations supplied during creation')
    assert api.update_entity_translation.call_args_list[1].args == (
        'users', 91, 'en', {'name': None, 'description': None}, 9, 'Initial translations supplied during creation')
    assert draft.row['translations'] == {'ar': {'name': 'اسم'}}


@pytest.mark.asyncio
async def test_failed_create_does_not_patch_and_can_be_corrected():
    api = SimpleNamespace(create=AsyncMock(side_effect=ApiError(422, 'Invalid')),
                          update_entity_translation=AsyncMock())
    draft = EntityCreation(('name',), translations={'ar': {'name': 'اسم'}})
    with pytest.raises(ApiError):
        await draft.save(api, 'users', {})
    assert draft.row is None and draft.translations == {'ar': {'name': 'اسم'}}
    api.update_entity_translation.assert_not_awaited()
