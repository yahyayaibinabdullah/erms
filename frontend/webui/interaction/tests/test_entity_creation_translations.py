"""All seven real shared create forms stage translations before any REST writes."""
import asyncio
from copy import deepcopy
from inspect import signature
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import ui

from frontend.webui.api_client import ApiError
from frontend.webui.entity_editor import build_entity_editor
from frontend.webui.i18n_catalogue import render_message_plain as t, strip_diagnostic_metadata

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio

ENTITIES = [
    ('classification-schemes', 'title', 'classification_scheme.modify_metadata'),
    ('classifications', 'title', 'classification.modify_metadata'),
    ('users', 'name', 'identity.users.administer'),
    ('roles', 'name', 'role.modify_metadata'),
    ('org-units', 'name', 'org_unit.modify_metadata'),
    ('security-levels', 'name', 'security_level.modify_metadata'),
    ('profiles', 'name', 'profile.modify_metadata'),
]
LANGUAGES = [{'language_tag': tag, 'native_name': tag, 'english_name': tag} for tag in ('ar', 'en')]


async def until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(.01)


def text(element):
    return strip_diagnostic_metadata(str(getattr(element, 'label', getattr(element, 'text', '')))).replace('\u2068', '').replace('\u2069', '')


def click(user, editor, key):
    button = next(e for e in editor['dialog'].descendants()
                  if isinstance(e, ui.button) and text(e) == t(key))
    marker = f'creation-action-{button.id}'
    button.mark(marker)
    user.find(marker=marker).click()


async def open_form(user, resource, primary, rights):
    async def create(kind, payload):
        return {'id': 91, 'version': 7, **deepcopy(payload)}

    async def patch(kind, identity, language, values, version, reason):
        return {'version': version + 1, 'fields': values}

    api = SimpleNamespace(
        get=AsyncMock(return_value={'id': 1, 'code': 'REF', 'title': 'Reference', 'name': 'Reference', 'level_number': 1}),
        list=AsyncMock(return_value=[{'id': 1, 'code': 'PUBLIC', 'name': 'Public', 'level_number': 1}]),
        administration_reference_page=AsyncMock(return_value={'items': [{'id': 1, 'code': 'ALL_PRIVS', 'name': 'All'}]}),
        create=AsyncMock(side_effect=create), update_entity_translation=AsyncMock(side_effect=patch),
        entity_translation=AsyncMock(),
    )
    dependencies = {name: Mock() for name in signature(build_entity_editor).parameters}
    dependencies.update(api=api, current_resource=lambda: resource,
                        principal=lambda: {'global_privileges': rights},
                        localization=lambda: {'supported_languages': LANGUAGES},
                        localized_editor_entity=lambda *args: resource,
                        validation_error_message=str, error_message=str,
                        load_rows=AsyncMock(), load_recent=AsyncMock())
    saved = AsyncMock()
    @ui.page('/entity-creation')
    async def page():
        await build_entity_editor(**dependencies)(
            initial_values={'classification_scheme_id': 1, 'org_unit_id': 1}, on_saved=saved)
    await user.open('/entity-creation')
    dialog = next(d for d in user.find(ui.dialog).elements if d.value)
    expansions = [e for e in dialog.descendants() if isinstance(e, ui.expansion)]
    result = dict(api=api, dialog=dialog, saved=saved, dependencies=dependencies)
    if expansions:
        expansion = expansions[0]
        result.update(expansion=expansion,
                      language=next(e for e in expansion.descendants() if isinstance(e, ui.select)),
                      translated=next(e for e in expansion.descendants() if isinstance(e, ui.input)
                                      and text(e) == t('entity_translation_editor.input.' + primary)))
        assert not any(isinstance(e, ui.input)
                       and text(e) == t('webui.open_editor.input.reason_for_translation_change_82d24ea1')
                       for e in expansion.descendants())
    inside = set(expansions[0].descendants()) if expansions else set()
    canonical = [e for e in dialog.descendants() if e not in inside and isinstance(e, (ui.input, ui.number))]
    with user:
        for control in canonical:
            if text(control).removesuffix(' *') in {'Code', 'Name', 'Title'}:
                control.value = 'CREATE_TEST'
            if text(control).removesuffix(' *') == 'Level number':
                control.value = 5
    result['canonical'] = canonical
    return result


async def enter_translation(user, editor, language, value):
    with user:
        editor['language'].value = language
    await until(lambda: editor['translated'].enabled and editor['translated'].value == '')
    with user:
        editor['translated'].value = value


@pytest.mark.parametrize('resource,primary,right', ENTITIES)
async def test_creation_stages_languages_and_saves_without_a_reason_input(user, resource, primary, right):
    editor = await open_form(user, resource, primary, [right])
    api = editor['api']
    await enter_translation(user, editor, 'ar', '  اسم عربي  ')
    await enter_translation(user, editor, 'en', 'Alternate')
    with user:
        editor['language'].value = 'ar'
    await until(lambda: editor['translated'].value == 'اسم عربي')
    api.entity_translation.assert_not_awaited()
    api.create.assert_not_awaited()
    click(user, editor, 'webui.open_editor.button.save_46081ed6')
    try:
        await until(lambda: not editor['dialog'].value)
    except TimeoutError:
        raise AssertionError({'notices': user.notify.messages,
                              'fields': [(text(e), e.value) for e in editor['canonical']],
                              'create': api.create.call_args_list,
                              'patch': api.update_entity_translation.call_args_list}) from None
    api.create.assert_awaited_once()
    assert 'translations' not in api.create.call_args.args[1]
    assert [c.args for c in api.update_entity_translation.call_args_list] == [
        (resource, 91, 'ar', {primary: 'اسم عربي', 'description': None}, 7, 'Initial translations supplied during creation'),
        (resource, 91, 'en', {primary: 'Alternate', 'description': None}, 8, 'Initial translations supplied during creation'),
    ]
    assert editor['saved'].call_args.args[0]['version'] == 9


@pytest.mark.parametrize('resource,primary,right', ENTITIES)
@pytest.mark.parametrize('rights', ['matching', 'catalogue', 'none'])
async def test_creation_disclosure_keeps_entity_specific_permissions(user, resource, primary, right, rights):
    granted = [right] if rights == 'matching' else ['localization.administer'] if rights == 'catalogue' else []
    editor = await open_form(user, resource, primary, granted)
    assert ('expansion' in editor) == (rights == 'matching')
    editor['api'].entity_translation.assert_not_awaited()


@pytest.mark.parametrize('resource,primary,right', ENTITIES)
async def test_local_removal_and_cancel_never_write(user, resource, primary, right):
    editor = await open_form(user, resource, primary, [right])
    await enter_translation(user, editor, 'ar', 'مسودة')
    remove = next(e for e in editor['expansion'].descendants()
                  if isinstance(e, ui.button) and e.props.get('icon') == 'delete_outline')
    remove.mark('remove-draft')
    user.find(marker='remove-draft').click()
    await until(lambda: editor['translated'].value == '')
    await enter_translation(user, editor, 'en', 'Draft')
    click(user, editor, 'webui.open_editor.button.cancel_c07bff03')
    await until(lambda: not editor['dialog'].value)
    editor['api'].create.assert_not_awaited()
    editor['api'].update_entity_translation.assert_not_awaited()
    editor['saved'].assert_not_awaited()


@pytest.mark.parametrize('resource,primary,right', ENTITIES)
@pytest.mark.parametrize('draft', ['untouched', 'blank', 'removed'])
async def test_optional_untouched_translations_do_not_block_creation(user, resource, primary, right, draft):
    editor = await open_form(user, resource, primary, [right])
    if draft != 'untouched':
        await enter_translation(user, editor, 'ar', '  ' if draft == 'blank' else 'مسودة')
        if draft == 'removed':
            remove = next(e for e in editor['expansion'].descendants()
                          if isinstance(e, ui.button) and e.props.get('icon') == 'delete_outline')
            remove.mark('discard-before-save')
            user.find(marker='discard-before-save').click()
            await until(lambda: editor['translated'].value == '')
    click(user, editor, 'webui.open_editor.button.save_46081ed6')
    await until(lambda: not editor['dialog'].value)
    editor['api'].create.assert_awaited_once()
    editor['api'].update_entity_translation.assert_not_awaited()


async def test_reverting_a_draft_after_failed_validation_uses_the_visible_value(user):
    editor = await open_form(user, 'users', 'name', ['identity.users.administer'])
    await enter_translation(user, editor, 'ar', 'Original')
    await enter_translation(user, editor, 'en', 'Alternate')
    with user:
        editor['language'].value = 'ar'
    await until(lambda: editor['translated'].value == 'Original')
    with user:
        editor['translated'].value = 'Changed'
        canonical_name = next(e for e in editor['canonical'] if text(e) == 'Name *')
        canonical_name.value = ''
    click(user, editor, 'webui.open_editor.button.save_46081ed6')
    await until(lambda: any('is required' in message for message in user.notify.messages))
    editor['api'].create.assert_not_awaited()
    with user:
        canonical_name.value = 'CREATE_TEST'
        editor['translated'].value = 'Original'
    click(user, editor, 'webui.open_editor.button.save_46081ed6')
    await until(lambda: not editor['dialog'].value)
    assert editor['api'].update_entity_translation.call_args_list[0].args[3]['name'] == 'Original'


@pytest.mark.parametrize('resource,primary,right', ENTITIES)
async def test_partial_failure_locks_canonical_fields_and_retries_without_duplicate_or_refresh(user, resource, primary, right):
    editor = await open_form(user, resource, primary, [right])
    await enter_translation(user, editor, 'ar', 'عنوان')
    editor['api'].update_entity_translation.side_effect = ApiError(503, 'Unavailable')
    click(user, editor, 'webui.open_editor.button.save_46081ed6')
    await until(lambda: editor['dependencies']['show_api_error'].called)
    assert editor['dialog'].value and editor['translated'].value == 'عنوان'
    assert all(not c.enabled for c in editor['canonical'])
    assert all(not b.enabled for b in editor['dialog'].descendants()
               if isinstance(b, ui.button) and 'Browse' in text(b))
    editor['saved'].assert_not_awaited()
    editor['dependencies']['load_rows'].assert_not_awaited()
    await user.should_see(t('entity_translation_editor.status.creation_pending'))
    editor['api'].update_entity_translation.side_effect = None
    editor['api'].update_entity_translation.return_value = {'version': 8}
    click(user, editor, 'webui.open_editor.button.save_46081ed6')
    await until(lambda: not editor['dialog'].value)
    editor['api'].create.assert_awaited_once()
    editor['saved'].assert_awaited_once()


async def test_overlapping_save_clicks_do_not_duplicate_creation(user):
    editor = await open_form(user, 'users', 'name', ['identity.users.administer'])
    release = asyncio.Event()
    async def slow_create(*args):
        await release.wait()
        return {'id': 91, 'version': 7}
    editor['api'].create.side_effect = slow_create
    click(user, editor, 'webui.open_editor.button.save_46081ed6')
    await until(lambda: editor['api'].create.await_count == 1)
    click(user, editor, 'webui.open_editor.button.save_46081ed6')
    release.set()
    await until(lambda: not editor['dialog'].value)
    editor['api'].create.assert_awaited_once()
