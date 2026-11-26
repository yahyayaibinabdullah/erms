"""Creation-time translations through the real root and disposable REST service."""
import pytest
from nicegui import ui

from frontend.webui.assembled.tests.test_application import (
    assembled, disposable_only, login, current_page, drawer_buttons, click_one, eventually,
)
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


def click(user, label, root=None):
    elements = root.descendants() if root else user.find(ui.button).elements
    click_one(user, [e for e in elements if isinstance(e, ui.button) and plain(e) == label])


async def dialog(user):
    await eventually(lambda: any(d.value for d in user.find(ui.dialog).elements))
    return next(d for d in user.find(ui.dialog).elements if d.value)


def fields(root):
    result = {}
    for e in root.descendants():
        if isinstance(e, (ui.input, ui.number, ui.select, ui.textarea)):
            result.setdefault(plain(e).removesuffix(' *'), e)
    return result


async def save(user, editor):
    click(user, 'Save', editor)
    await eventually(lambda: not editor.value and user.pending_requests == 0)


@pytest.mark.parametrize('resource,navigation,primary', [
    ('classification-schemes', 'Classification schemes', 'Title'),
    ('classifications', 'Classification schemes', 'Title'),
    ('users', 'Users', 'Name'),
    ('roles', 'Roles', 'Name'),
    ('org-units', 'Organization units', 'Name'),
    ('security-levels', 'Security levels', 'Name'),
    ('profiles', 'Profiles', 'Name'),
])
async def test_seven_entity_create_forms_persist_initial_translations(assembled, resource, navigation, primary):
    user = assembled
    await login(user)
    api = user.api_clients[0]
    click_one(user, [b for b in drawer_buttons(user) if plain(b) == navigation])
    page = 'classification-workspace' if resource in {'classification-schemes', 'classifications'} else resource
    await eventually(lambda: current_page(user) == page and user.pending_requests == 0)
    code = 'CREATE_TRANSLATIONS_' + resource.replace('-', '_').upper()
    click(user, 'Add scheme' if page == 'classification-workspace' else 'Add')
    editor = await dialog(user)
    if resource == 'classifications':
        with user:
            fields(editor)['Code'].value = code + '_SCHEME'
            fields(editor)['Title'].value = 'Creation translation scheme'
        await save(user, editor)
        await user.should_see(t('classification_browser.add_root'), retries=100)
        click(user, t('classification_browser.add_root'))
        editor = await dialog(user)
    with user:
        canonical = fields(editor)
        if 'Code' in canonical:
            canonical['Code'].value = code
        canonical[primary].value = code
        if resource == 'security-levels':
            canonical['Level number'].value = 88
    if resource == 'roles':
        units = await api.search_request('org-units', {'limit': 1})
        unit = units['items'][0]
        with user:
            canonical['Organization unit'].set_options({unit['id']: unit['name']}, value=unit['id'])
    expansion = next(e for e in editor.descendants() if isinstance(e, ui.expansion))
    language = next(e for e in expansion.descendants() if isinstance(e, ui.select))
    with user:
        expansion.open()
        language.value = 'ar'
    await user.should_see(t('entity_translation_editor.status.loaded'), retries=100)
    translated = fields(expansion)
    with user:
        translated[primary].value = 'عنوان الاختبار' if primary == 'Title' else 'اسم الاختبار'
        translated['Description'].value = 'وصف الاختبار'
    assert not any(isinstance(e, ui.input) and plain(e).startswith('Reason for')
                   for e in expansion.descendants())
    await save(user, editor)
    result = await api.administration_reference_page(
        resource, query=code, limit=1,
    ) if resource in {'security-levels', 'profiles'} else await api.search_request(resource, {
        'where': {'field': 'name' if resource == 'users' else 'code', 'operator': 'eq', 'value': code},
        'limit': 1,
    })
    assert len(result['items']) == 1
    stored = result['items'][0]
    translation = await api.entity_translation(resource, stored['id'], 'ar')
    assert translation['fields'] == {
        primary.lower(): 'عنوان الاختبار' if primary == 'Title' else 'اسم الاختبار',
        'description': 'وصف الاختبار',
    }
    assert translation['version'] == stored['version']
    # Reproduce reopening and selecting a different language before Arabic.
    if resource == 'classification-schemes':
        await user.should_see('Edit scheme', retries=100)
        click(user, 'Edit scheme')
    elif resource == 'classifications':
        await user.should_see('Edit', retries=100)
        click(user, 'Edit')
    else:
        filter_control = next(e for e in user.find(ui.input).elements if plain(e).startswith('Filter '))
        with user:
            filter_control.value = code
        def matching_cards():
            return [c for c in user.find(ui.card).elements if 'governance-list-card' in c.classes]
        await eventually(lambda: len(matching_cards()) == 1 and user.pending_requests == 0)
        click_one(user, [e for e in matching_cards()[0].descendants()
                         if isinstance(e, ui.button) and e.props.get('icon') == 'edit'])
    reopened = await dialog(user)
    reopened_expansion = next(e for e in reopened.descendants() if isinstance(e, ui.expansion))
    reopened_language = next(e for e in reopened_expansion.descendants() if isinstance(e, ui.select))
    reopened_fields = fields(reopened_expansion)
    with user:
        reopened_expansion.open()
        reopened_language.value = 'en'
    await eventually(lambda: reopened_fields[primary].enabled and user.pending_requests == 0)
    assert not reopened_fields[primary].value
    with user:
        reopened_language.value = 'ar'
    await eventually(lambda: reopened_fields[primary].value == translation['fields'][primary.lower()]
                     and reopened_fields['Description'].value == 'وصف الاختبار')
    # Keep English unsaved while inspecting and changing the saved Arabic locale.
    with user:
        reopened_language.value = 'en'
    await eventually(lambda: reopened_fields[primary].enabled and reopened_fields[primary].value == '')
    reason_key = ('webui.open_editor.textarea.reason_for_changing_this_profile_5882ddfb' if resource == 'profiles'
                  else 'webui.open_editor.input.reason_for_translation_change_82d24ea1')
    reason = next(e for e in reopened.descendants() if isinstance(e, (ui.input, ui.textarea)) and plain(e) == t(reason_key))
    with user:
        reopened_fields[primary].value = 'English edit draft'
        reopened_fields['Description'].value = 'English description draft'
        reason.value = 'English review'
        reopened_language.value = 'ar'
    await eventually(lambda: reopened_fields[primary].value == translation['fields'][primary.lower()])
    with user:
        reopened_fields[primary].value = 'مسودة عربية'
        reopened_fields['Description'].value = 'وصف المسودة'
        reason.value = 'Arabic review'
        reopened_language.value = 'en'
    await eventually(lambda: reopened_fields[primary].value == 'English edit draft')
    assert reopened_fields['Description'].value == 'English description draft'
    assert reason.value == ('Arabic review' if resource == 'profiles' else 'English review')
    await save(user, reopened)
    for tag, expected in [('en', {primary.lower(): 'English edit draft', 'description': 'English description draft'}),
                          ('ar', {primary.lower(): 'مسودة عربية', 'description': 'وصف المسودة'})]:
        assert (await api.entity_translation(resource, stored['id'], tag))['fields'] == expected
    writes = [r for r in user.api_requests if r['method'] in {'POST', 'PATCH'}]
    assert sum(r['method'] == 'POST' and r['path'] == '/api/v1/' + resource for r in writes) == 1
    assert sum('/entity-translations/' + resource + '/' in r['path'] for r in writes) == 3
    assert not [f for f in user.api_failures
                if not (f[0] == 'GET' and f[1].endswith('/effective-retention-rule') and f[2] == 404)]
