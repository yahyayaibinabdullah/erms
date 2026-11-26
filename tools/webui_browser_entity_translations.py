"""Native seven-entity draft/save regressions; disposable runner only."""
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.webdriver.support import expected_conditions as EC
from tools.check_webui_browser import plain


def _settled_activate(page, element):
    # QDialog has an entrance animation: inspect stable bounds and the hit target
    # before native input. Do not alter CSS or write values through JavaScript.
    page.driver.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});", element)
    previous = [None]
    def ready(_):
        observed = page.driver.execute_script("""
            const e=arguments[0], r=e.getBoundingClientRect();
            const top=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
            return {rect:[r.x,r.y,r.width,r.height].map(Math.round),hit:top===e||e.contains(top)};
        """, element)
        settled = observed['rect'] == previous[0]
        previous[0] = observed['rect']
        if settled and observed['hit']:
            try:
                element.click()
                return True
            except ElementClickInterceptedException:
                previous[0] = None
        return False
    page.wait.until(ready)


def check_entity_translations(page):
    activate = page.activate
    page.activate = lambda element: _settled_activate(page, element)
    try:
        for language in ('en', 'ar'):
            if page.language != language:
                page.settings()
                page.language_change(language)
            _check_language(page, language)
    finally:
        page.activate = activate


def _check_language(page, language):
    def create(resource, payload):
        result = page.api.post('/api/v1/' + resource, json=payload)
        result.raise_for_status()
        return result.json()
    def read(path, **params):
        result = page.api.get('/api/v1/' + path, params=params)
        result.raise_for_status()
        return result.json()

    parent_code = 'REOPEN_PARENT_' + language
    parent_title = 'Reopen parent ' + language
    unit_title = 'Reopen unit ' + language
    create('classification-schemes', {'code': parent_code, 'title': parent_title})
    create('org-units', {'code': 'REOPEN_UNIT_' + language, 'name': unit_title})
    cases = [('classification-schemes', 'classification_schemes', 'title'),
             ('classifications', 'classification_schemes', 'title'), ('users', 'users', 'name'),
             ('roles', 'roles', 'name'), ('org-units', 'org_units', 'name'),
             ('security-levels', 'security_levels', 'name'), ('profiles', 'profiles', 'name')]
    for index, (resource, navigation, primary) in enumerate(cases):
        with page.check(resource + ' create/edit multilingual drafts, Save all, reopen and Cancel'):
            code = 'REOPEN_' + language + '_' + str(index)
            initial_ar = {primary: 'اسم عربي محفوظ', 'description': 'وصف عربي محفوظ'}
            initial_en = {primary: 'Initial English', 'description': 'Initial English description'}
            previous = page.visible('.governance-card-list')
            page.drawer(navigation)
            if previous:
                page.wait.until(EC.staleness_of(previous[0]))
            if resource in {'classification-schemes', 'classifications'}:
                page.see(page.t('webui.render_workspace_right.label.classification_tree_69593539'))
                if resource == 'classifications':
                    label = page.t('webui.select_classification_workspace.input.filter_schemes_a7f4591e')
                    page.fill(label, parent_code)
                    page.field(label).send_keys(Keys.ENTER)
                    page.activate(page.one('button.classification-node-button', parent_code + ' — ' + parent_title))
                    page.click(page.t('classification_browser.add_root'))
                else:
                    page.click(page.t('webui.select_classification_workspace.button.add_scheme_ff7a6bd6'))
            else:
                page.wait.until(lambda _: bool(page.visible('.governance-list-card')))
                page.click(page.t('webui.select_entity.text.add_6623ee14'))
            dialog = page.one('.q-dialog__inner > .q-card')
            primary_label = page.t('entity_translation_editor.input.' + primary)
            description_label = page.t('entity_translation_editor.input.description')
            reason_label = page.t('webui.open_editor.input.reason_for_translation_change_82d24ea1')
            def field(label):
                return page.wait.until(lambda _: next((control.find_element('css selector', 'input,textarea')
                    for control in page.visible('.q-expansion-item .q-field', dialog)
                    if any(plain(item.text) == label for item in control.find_elements('css selector', '.q-field__label'))), None))
            def choose(tag, expected):
                page.activate(field(page.t('webui.open_editor.select.language_a1337600')))
                page.activate(page.one('[role=option]', 'English · English' if tag == 'en' else 'العربية · Arabic'))
                page.wait.until(lambda _: field(primary_label).is_enabled()
                                and field(primary_label).get_attribute('value') == expected[primary]
                                and field(description_label).get_attribute('value') == expected['description'])
            def enter(values, reason=None):
                for label, value in [(primary_label, values[primary]), (description_label, values['description'])]:
                    control = field(label)
                    page.select_field_text(control); control.send_keys(value)
                if reason is not None:
                    control = (page.field(page.t('webui.open_editor.textarea.reason_for_changing_this_profile_5882ddfb'))
                               if resource == 'profiles' else field(reason_label))
                    page.select_field_text(control); control.send_keys(reason)
            def expand():
                page.activate(page.one('.q-expansion-item .q-item__label', page.t('entity_translation_editor.expansion.title'), scope=dialog))
            def save():
                page.click(page.t('webui.open_editor.button.save_46081ed6'), dialog)
            def close():
                page.click(page.t('webui.open_editor.button.cancel_c07bff03'), dialog)
                page.wait.until(lambda _: not page.visible('.q-dialog__inner > .q-card'))
            def reopen():
                if resource in {'classification-schemes', 'classifications'}:
                    panel = page.one('.classification-actions-panel')
                    page.click(page.t('webui.render_workspace_right.button.edit_scheme_4406dbed')
                               if resource == 'classification-schemes' else page.t('webui.render_workspace_right.button.edit_a536c992'), panel)
                else:
                    query = page.wait.until(lambda _: next(iter(page.visible('.erms-card input')), None))
                    page.select_field_text(query); query.send_keys(code)
                    page.wait.until(lambda _: len(page.visible('.governance-list-card')) == 1)
                    card = page.one('.governance-list-card')
                    page.activate(next(button for button in card.find_elements('css selector', 'button')
                                       if any(icon.text.strip() == 'edit' for icon in button.find_elements('css selector', '.q-icon'))))
                return page.one('.q-dialog__inner > .q-card')

            if resource != 'users': page.fill(page.t('entity_metadata.field.code') + ' *', code)
            page.fill(page.t('entity_metadata.field.' + primary) + ' *', code)
            if resource == 'security-levels': page.fill(page.t('entity_metadata.field.level_number') + ' *', 88 if language == 'en' else 89)
            if resource == 'roles':
                selector = page.field(page.t('entity_metadata.field.organization_unit') + ' *')
                page.activate(selector); selector.send_keys(unit_title)
                page.activate(page.wait.until(lambda _: next((option for option in page.visible('[role=option]') if unit_title in plain(option.text)), None)))
            expand()
            empty = {primary: '', 'description': ''}
            choose('ar', empty); enter(initial_ar)
            choose('en', empty); enter(initial_en)
            choose('ar', initial_ar); choose('en', initial_en); choose('ar', initial_ar)
            assert not any(reason_label in plain(item.text) for item in page.visible('.q-expansion-item .q-field', dialog))
            save(); page.wait.until(lambda _: not page.visible('.q-dialog__inner > .q-card'))
            if resource in {'profiles', 'security-levels'}:
                result = read(resource + '/page', q=code, limit=1)
            else:
                response = page.api.post('/api/v1/' + resource + '/search', json={
                    'where': {'field': 'name' if resource == 'users' else 'code', 'operator': 'eq', 'value': code}, 'limit': 1})
                response.raise_for_status(); result = response.json()
            assert len(result['items']) == 1
            row = result['items'][0]
            assert row['translations']['ar'] == initial_ar and row['translations']['en'] == initial_en
            path = '/api/v1/entity-translations/' + resource + '/' + str(row['id'])
            # Prepare the reported condition: stored Arabic, no stored English.
            prepared = page.api.patch(path + '/en', json={primary: None, 'description': None}, headers={
                'If-Match': str(row['version']), 'X-Change-Reason': 'Prepare unsaved English draft regression'})
            prepared.raise_for_status()
            dialog = reopen(); expand()
            # Cache a clean locale, then observe a newer version through another
            # language. Returning must fetch fresh values, never rebase stale ones.
            choose('ar', initial_ar)
            concurrent = page.api.patch(path + '/ar', json={'description': 'Concurrent Arabic description'}, headers={
                'If-Match': str(prepared.json()['version']), 'X-Change-Reason': 'Concurrent locale freshness regression'})
            concurrent.raise_for_status()
            initial_ar = dict(initial_ar, description='Concurrent Arabic description')
            english = {primary: 'Edited English ' + resource, 'description': 'Edited English description'}
            arabic = {primary: 'مسودة عربية محفوظة', 'description': 'وصف المسودة العربية'}
            choose('en', empty); enter(english, 'English review')
            choose('ar', initial_ar); enter(arabic, 'Arabic review')
            choose('en', english)
            if resource != 'profiles': assert field(reason_label).get_attribute('value') == 'English review'
            # A late explicit reload of English cannot replace the Arabic draft.
            page.control(path=path + '/en', hold=True)
            started = len(page.events('requests-started.jsonl'))
            finished = len(page.events())
            try:
                refresh = next(button for button in dialog.find_elements('css selector', '.q-expansion-item button')
                               if any(icon.text.strip() == 'refresh' for icon in button.find_elements('css selector', '.q-icon')))
                page.activate(refresh)
                page.wait.until(lambda _: any(e['path'] == path + '/en' and e.get('controlled') for e in page.events('requests-started.jsonl')[started:]))
                choose('ar', arabic)
                page.control()
                page.wait.until(lambda _: any(e['path'] == path + '/en' and e.get('controlled') for e in page.events()[finished:]))
                assert field(primary_label).get_attribute('value') == arabic[primary]
                assert field(description_label).get_attribute('value') == arabic['description']
                page.capture('edit-drafts-retained-' + language + '-' + resource)
            finally:
                page.control()
            before = len(page.events())
            if resource == 'classifications': page.control(method='PATCH', path=path + '/en', status=503)
            save()
            if resource == 'classifications':
                page.wait.until(lambda _: any(e['path'] == path + '/en' and e['status'] == 503 for e in page.events()[before:]))
                page.see(page.t('entity_translation_editor.status.edit_pending'))
                assert not page.field(page.t('entity_metadata.field.code') + ' *').is_enabled()
                choose('en', english)
                page.capture('edit-partial-retry-' + language)
                page.control(); save()
            page.wait.until(lambda _: not page.visible('.q-dialog__inner > .q-card'))
            writes = [e for e in page.events()[before:] if e['method'] == 'PATCH']
            assert sum(e['path'] == '/api/v1/' + resource + '/' + str(row['id']) for e in writes) == 1
            assert sum(e['path'] == path + '/ar' for e in writes) == 1
            assert sum(e['path'] == path + '/en' for e in writes) == (2 if resource == 'classifications' else 1)
            dialog = reopen(); expand()
            choose('en', english); choose('ar', arabic); choose('en', english)
            enter({primary: 'Discarded draft', 'description': 'Discarded description'}, 'Discard review')
            choose('ar', arabic)
            choose('en', {primary: 'Discarded draft', 'description': 'Discarded description'})
            close()
            dialog = reopen(); expand(); choose('en', english); choose('ar', arabic)
            page.capture('edit-saved-reopened-' + language + '-' + resource)
            close()
            for tag, expected in [('en', english), ('ar', arabic)]:
                assert read(path.removeprefix('/api/v1/') + '/' + tag)['fields'] == expected
