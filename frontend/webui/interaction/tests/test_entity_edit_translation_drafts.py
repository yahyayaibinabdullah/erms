"""Real seven-entity Edit forms retain and save every language draft."""
from copy import deepcopy
from inspect import signature
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import ui
from frontend.webui.api_client import ApiError
from frontend.webui.entity_editor import build_entity_editor
from frontend.webui.interaction.tests.test_entity_creation_translations import ENTITIES, LANGUAGES, text, until
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


async def open_edit(user, resource, primary, right, *, protected=False):
    row = {'id': 91, 'version': 7, 'code': 'TEXT_INDEXER_SERVICE' if protected and resource == 'profiles' else 'EDIT_TEST',
           'name': 'Canonical', 'title': 'Canonical', 'level_number': 88, 'org_unit_id': 1,
           'classification_scheme_id': 1, 'security_level_id': 1, 'is_terminal': False, 'is_system': protected,
           'is_information_governance': False, 'profile_id': 1, 'account_type': 'person',
           'translations': {'ar': {primary: 'الأصل', 'description': 'الوصف الأصلي'}}}
    stored = deepcopy(row)
    async def get(kind, identity):
        return deepcopy(stored if kind == resource and identity == 91 else
                        {'id': identity, 'code': 'REF', 'name': 'Reference', 'title': 'Reference', 'level_number': 1})
    async def read(kind, identity, language):
        return {'version': stored['version'], 'fields': deepcopy(stored['translations'].get(language, {}))}
    async def update(kind, identity, version, payload, **kwargs):
        assert version == stored['version']
        stored.update(payload, version=version + 1)
        return deepcopy(stored)
    async def patch(kind, identity, language, values, version, reason):
        assert version == stored['version'] and reason
        stored['translations'][language] = {key: value for key, value in values.items() if value}
        stored['version'] += 1
        return {'version': stored['version'], 'fields': deepcopy(values)}
    api = SimpleNamespace(get=AsyncMock(side_effect=get), entity_translation=AsyncMock(side_effect=read),
        update=AsyncMock(side_effect=update), update_entity_translation=AsyncMock(side_effect=patch),
        classification_retention_rule=AsyncMock(side_effect=ApiError(404, 'No rule')),
        list=AsyncMock(return_value=[{'id': 1, 'code': 'PUBLIC', 'name': 'Public', 'level_number': 1}]))
    dependencies = {name: Mock() for name in signature(build_entity_editor).parameters}
    dependencies.update(api=api, current_resource=lambda: resource, principal=lambda: {'global_privileges': [right]},
        localization=lambda: {'supported_languages': LANGUAGES}, localized_editor_entity=lambda *args: resource,
        validation_error_message=str, error_message=str, load_rows=AsyncMock(), load_recent=AsyncMock())
    saved = AsyncMock()
    @ui.page('/edit-drafts')
    async def page():
        await build_entity_editor(**dependencies)(row, on_saved=saved)
    await user.open('/edit-drafts')
    dialog = next(d for d in user.find(ui.dialog).elements if d.value)
    expansion = next(e for e in dialog.descendants() if isinstance(e, ui.expansion))
    controls = list(expansion.descendants())
    reason = next(e for e in dialog.descendants() if isinstance(e, ui.textarea)
                  and text(e) == t('webui.open_editor.textarea.reason_for_changing_this_profile_5882ddfb')) if resource == 'profiles' else next(
        e for e in controls if isinstance(e, ui.input) and text(e) == t('webui.open_editor.input.reason_for_translation_change_82d24ea1'))
    return dict(api=api, stored=stored, dialog=dialog, expansion=expansion, saved=saved, deps=dependencies,
                language=next(e for e in controls if isinstance(e, ui.select)), reason=reason,
                name=next(e for e in controls if isinstance(e, ui.input) and text(e) == t('entity_translation_editor.input.' + primary)),
                description=next(e for e in controls if isinstance(e, ui.textarea)),
                canonical=next(e for e in dialog.descendants() if isinstance(e, ui.input) and text(e) == t('entity_metadata.field.' + primary) + ' *'))


async def choose(user, editor, tag, expected):
    with user:
        editor['language'].value = tag
    await until(lambda: editor['name'].enabled and editor['name'].value == expected)


def draft(user, editor, value, reason='Translation review'):
    with user:
        editor['name'].value = value
        editor['description'].value = value + ' description'
        editor['reason'].value = reason


def save(user, editor):
    button = next(e for e in editor['dialog'].descendants() if isinstance(e, ui.button)
                  and text(e) == t('webui.open_editor.button.save_46081ed6'))
    button.mark('save-edit-drafts')
    user.find(marker='save-edit-drafts').click()


@pytest.mark.parametrize('resource,primary,right', ENTITIES)
async def test_edit_retains_both_drafts_and_reasons_then_saves_all_languages(user, resource, primary, right):
    editor = await open_edit(user, resource, primary, right)
    await choose(user, editor, 'en', '')
    draft(user, editor, 'English draft', 'English review')
    await choose(user, editor, 'ar', 'الأصل')
    draft(user, editor, 'مسودة', 'Arabic review')
    await choose(user, editor, 'en', 'English draft')
    assert editor['description'].value == 'English draft description'
    assert editor['reason'].value == ('Arabic review' if resource == 'profiles' else 'English review')
    editor['api'].update_entity_translation.assert_not_awaited()
    save(user, editor)
    try:
        await until(lambda: not editor['dialog'].value)
    except TimeoutError:
        raise AssertionError({'notices': user.notify.messages, 'writes': editor['api'].update.call_args_list}) from None
    assert editor['stored']['translations'] == {
        'en': {primary: 'English draft', 'description': 'English draft description'},
        'ar': {primary: 'مسودة', 'description': 'مسودة description'},
    }
    assert [c.args[4] for c in editor['api'].update_entity_translation.call_args_list] == [8, 9]
    assert [c.args[5] for c in editor['api'].update_entity_translation.call_args_list] == (
        ['Arabic review', 'Arabic review'] if resource == 'profiles' else ['Arabic review', 'English review'])
    editor['api'].update.assert_awaited_once()
    editor['saved'].assert_awaited_once()


@pytest.mark.parametrize('resource,primary,right', ENTITIES)
async def test_partial_edit_retry_retains_pending_drafts_without_repeating_accepted_writes(user, resource, primary, right):
    editor = await open_edit(user, resource, primary, right)
    await choose(user, editor, 'ar', 'الأصل'); draft(user, editor, 'مسودة')
    await choose(user, editor, 'en', ''); draft(user, editor, 'English draft')
    patch = editor['api'].update_entity_translation.side_effect
    fail = [True]
    async def sometimes(*args):
        if args[2] == 'en' and fail[0]:
            raise ApiError(503, 'Unavailable')
        return await patch(*args)
    editor['api'].update_entity_translation.side_effect = sometimes
    save(user, editor)
    await until(lambda: editor['deps']['show_api_error'].called)
    assert editor['dialog'].value and not editor['canonical'].enabled
    assert editor['name'].value == 'English draft' and editor['name'].enabled
    editor['saved'].assert_not_awaited()
    fail[0] = False
    save(user, editor)
    await until(lambda: not editor['dialog'].value)
    assert [c.args[2] for c in editor['api'].update_entity_translation.call_args_list] == ['ar', 'en', 'en']
    assert [c.args[4] for c in editor['api'].update_entity_translation.call_args_list] == [8, 9, 9]
    editor['api'].update.assert_awaited_once()


@pytest.mark.parametrize('resource,primary,right', [case for case in ENTITIES if case[0] in {'roles', 'profiles'}])
async def test_protected_edit_saves_all_locales_without_canonical_update(user, resource, primary, right):
    editor = await open_edit(user, resource, primary, right, protected=True)
    await choose(user, editor, 'ar', 'الأصل'); draft(user, editor, 'مسودة')
    await choose(user, editor, 'en', ''); draft(user, editor, 'English draft')
    save(user, editor)
    await until(lambda: not editor['dialog'].value)
    editor['api'].update.assert_not_awaited()
    assert [c.args[4] for c in editor['api'].update_entity_translation.call_args_list] == [7, 8]


@pytest.mark.parametrize('resource,primary,right', ENTITIES)
async def test_unsaved_edit_cancel_never_writes(user, resource, primary, right):
    editor = await open_edit(user, resource, primary, right)
    await choose(user, editor, 'en', ''); draft(user, editor, 'English draft')
    await choose(user, editor, 'ar', 'الأصل'); draft(user, editor, 'مسودة')
    with user: editor['dialog'].close()
    editor['api'].update.assert_not_awaited()
    editor['api'].update_entity_translation.assert_not_awaited()


@pytest.mark.parametrize('resource,primary,right', [case for case in ENTITIES if case[0] != 'profiles'])
async def test_all_pending_reasons_are_validated_before_any_write(user, resource, primary, right):
    editor = await open_edit(user, resource, primary, right)
    await choose(user, editor, 'en', ''); draft(user, editor, 'English draft', '')
    await choose(user, editor, 'ar', 'الأصل'); draft(user, editor, 'مسودة', 'Arabic review')
    save(user, editor)
    await until(lambda: editor['language'].value == 'en' and editor['name'].enabled)
    assert editor['name'].value == 'English draft' and editor['reason'].value == ''
    editor['api'].update.assert_not_awaited()
    editor['api'].update_entity_translation.assert_not_awaited()


async def test_edit_save_disables_controls_and_cannot_overlap(user):
    import asyncio
    resource, primary, right = next(case for case in ENTITIES if case[0] == 'users')
    editor = await open_edit(user, resource, primary, right)
    await choose(user, editor, 'en', ''); draft(user, editor, 'English draft')
    release = asyncio.Event()
    patch = editor['api'].update_entity_translation.side_effect
    async def delayed(*args):
        await release.wait()
        return await patch(*args)
    editor['api'].update_entity_translation.side_effect = delayed
    save(user, editor)
    await until(lambda: editor['api'].update_entity_translation.await_count == 1)
    assert not editor['name'].enabled and not editor['language'].enabled
    save(user, editor)
    release.set()
    await until(lambda: not editor['dialog'].value)
    editor['api'].update.assert_awaited_once()
    editor['api'].update_entity_translation.assert_awaited_once()


async def test_remove_keeps_other_drafts_and_save_cannot_overlap_it(user):
    import asyncio
    resource, primary, right = next(case for case in ENTITIES if case[0] == 'users')
    editor = await open_edit(user, resource, primary, right)
    await choose(user, editor, 'en', ''); draft(user, editor, 'English draft', 'English review')
    await choose(user, editor, 'ar', 'الأصل')
    with user: editor['reason'].value = 'Remove Arabic'
    release = asyncio.Event()
    patch = editor['api'].update_entity_translation.side_effect
    async def delayed(*args):
        if args[2] == 'ar': await release.wait()
        return await patch(*args)
    editor['api'].update_entity_translation.side_effect = delayed
    remove = next(e for e in editor['expansion'].descendants() if isinstance(e, ui.button) and e.props.get('icon') == 'delete_outline')
    remove.mark('remove-edit-locale')
    user.find(marker='remove-edit-locale').click()
    await until(lambda: editor['api'].update_entity_translation.await_count == 1)
    save(user, editor)
    editor['api'].update.assert_not_awaited()
    release.set()
    await until(lambda: editor['name'].enabled and editor['name'].value == '')
    await choose(user, editor, 'en', 'English draft')
    assert editor['reason'].value == 'English review'
    save(user, editor)
    await until(lambda: not editor['dialog'].value)
    assert [c.args[2] for c in editor['api'].update_entity_translation.call_args_list] == ['ar', 'en']
    assert [c.args[4] for c in editor['api'].update_entity_translation.call_args_list] == [7, 9]
