"""Relationship-type administration parity through native Chrome/Edge interactions."""
from urllib.parse import parse_qs

from selenium.webdriver.common.keys import Keys


def check_relationships(page):
    def t(key): return page.t('relationships.ui.' + key)
    def enter():
        before = len(page.events())
        page.activate(page.one('button.erms-nav-link', t('catalogue')))
        page.wait.until(lambda _: any(e['path'] == '/api/v1/relationships/types/aggregation'
                                     and e['status'] == 200 for e in page.events()[before:]))
        page.one('.erms-page-table')
    def rows(): return page.visible('.erms-page-table tbody tr')
    def row(code): return page.wait.until(lambda _: next((r for r in rows() if code in r.text), False))
    def dialog(): return page.one('.q-dialog .q-card')
    def closed(): page.wait.until(lambda _: not page.visible('.q-dialog .q-card'))
    def snapshot(name): page.capture('relationships-' + name + '-' + page.language)
    def request_count():
        return len([e for e in page.events() if e['path'].startswith('/api/v1/relationships/types/')])
    def settle_after(count): page.wait.until(lambda _: request_count() > count)

    # Synthetic fixture rows create a genuine second server page in both kinds.
    for kind in ('aggregation', 'record'):
        for number in range(28):
            response = page.api.post('/api/v1/relationships/types/' + kind, json={
                'code': f'fixture_{number:02}', 'forward_name': f'Fixture {number:02}',
                'reverse_name': f'Reverse {number:02}', 'is_symmetric': False,
                'translations': {'ar': {'forward_name': f'علاقة {number:02}', 'reverse_name': f'عكس {number:02}'}}})
            response.raise_for_status()

    for language in ('en', 'ar'):
        if language == 'ar':
            page.settings(); page.language_change('ar')
        with page.check('relationship catalogue entry, repeated visits, URL and restoration'):
            enter()
            history = page.driver.execute_script('return history.length')
            url = page.driver.current_url
            page.settings(); enter()
            assert page.driver.current_url == url
            assert page.driver.execute_script('return history.length') == history
            page.reload()
            page.one('.erms-page-table'); row('fixture_00')
            assert page.driver.current_url == url
            assert len(rows()) == 25
            snapshot('table')
        with page.check('relationship kind tabs, server pagination, sorting and empty search'):
            count = request_count(); page.click(t('next')); settle_after(count)
            page.wait.until(lambda _: any('offset=25' in e['query'] for e in page.events()[-8:]
                                         if e['path'].endswith('/types/aggregation')))
            assert 0 < len(rows()) < 25
            page.click(t('previous')); row('fixture_00')
            page.activate(page.one('[role=tab]', t('record')))
            page.wait.until(lambda _: page.one('[role=tab][aria-selected=true]').text.casefold() == t('record').casefold())
            row('fixture_00')
            count = request_count(); page.one('.erms-page-table th', t('code')).click(); settle_after(count)
            page.fill(t('search'), 'no-such-type'); page.see(t('no_types'))
            snapshot('empty')
            page.fill(t('search'), ''); row('fixture_00')
        with page.check('relationship creation validation, Arabic names and keyboard focus'):
            page.fill(t('search'), 'new_'); page.see(t('no_types'))
            page.click(t('new_type')); dialog()
            page.click(t('save'), scope=dialog()); page.see(t('required'))
            snapshot('required')
            for key, value in [('code', 'new_' + language), ('english_forward', 'Forward'), ('english_reverse', 'Reverse')]:
                page.fill(t(key), value)
            page.click(t('save'), scope=dialog())
            page.see(page.t('relationships.error.arabic_labels_required'))
            page.one('.q-expansion-item .q-item').click()
            page.field(page.t('webui.open_editor.select.language_a1337600')).click()
            page.one('[role=option]', 'العربية · Arabic').click()
            page.fill(t('forward'), 'أمام'); page.fill(t('reverse'), 'خلف')
            field = page.field(t('english_forward'))
            field.click(); field.send_keys(Keys.TAB)
            focused = page.driver.switch_to.active_element
            assert focused == page.field(t('english_reverse'))
            page.report.setdefault('focus', []).append({'language': language, 'from': 'english_forward',
                                                        'to': 'english_reverse', 'tag': focused.tag_name})
            snapshot('create')
            page.click(t('save'), scope=dialog()); closed(); row('new_' + language)
            result = page.api.get('/api/v1/relationships/types/record', params={'q': 'new_' + language}).json()['items']
            assert len(result) == 1 and result[0]['forward_name'] == 'Forward'
        with page.check('relationship editing refreshes data and preserves immutable fields'):
            page.one('button', t('edit'), scope=row('new_' + language)).click()
            dialog()
            assert not page.field(t('code')).is_enabled()
            page.fill(t('english_forward'), 'Changed')
            snapshot('edit')
            identity = result[0]['id']
            page.control(path=f'/api/v1/relationships/types/record/{identity}', method='PATCH', status=409)
            page.click(t('save'), scope=dialog()); page.see(page.t('common.error.conflict'))
            assert page.field(t('english_forward')).get_attribute('value') == 'Changed'
            snapshot('conflict')
            page.control()
            page.click(t('save'), scope=dialog()); closed()
            result = page.api.get('/api/v1/relationships/types/record', params={'q': 'new_' + language}).json()['items']
            assert result[0]['forward_name'] == 'Changed'
            identity = result[0]['id']
            page.one('button', t('edit'), scope=row('new_' + language)).click()
            page.wait.until(lambda _: page.field(t('english_forward')).get_attribute('value') == 'Changed')
            page.click(t('cancel'), scope=dialog()); closed()
        with page.check('relationship deletion cancellation and confirmed removal'):
            page.one('button', t('delete_type'), scope=row('new_' + language)).click()
            snapshot('delete')
            page.click(t('cancel'), scope=dialog()); closed(); row('new_' + language)
            page.one('button', t('delete_type'), scope=row('new_' + language)).click()
            page.click(t('delete_type'), scope=dialog()); closed()
            page.wait.until(lambda _: not any('new_' + language in r.text for r in rows()))
            assert not page.api.get('/api/v1/relationships/types/record', params={'q':'new_' + language}).json()['items']
        with page.check('relationship read failure and abandoned response preserve next view'):
            path = '/api/v1/relationships/types/aggregation'
            page.control(path=path, status=503)
            page.activate(page.one('button.erms-nav-link', t('catalogue')))
            page.see(page.t('common.error.service_unavailable'))
            snapshot('error')
            page.control(); enter(); row('fixture_00')
            page.control(path=path, hold=True)
            start = len(page.events('requests-started.jsonl'))
            page.click(t('refresh'))
            page.wait.until(lambda _: any(e['controlled'] for e in page.events('requests-started.jsonl')[start:]))
            page.drawer('dashboard'); page.one('.dashboard-overview-primary')
            count = len(page.events()); page.control()
            page.wait.until(lambda _: any(e['controlled'] and e['path'] == path for e in page.events()[count:]))
            assert page.visible('.dashboard-overview-primary') and not page.visible('.erms-page-table')
            enter(); row('fixture_00')

    with page.check('restricted identity cannot enter relationship administration'):
        page.sign_out(); page.login('viewer@test.invalid')
        assert not [e for e in page.visible('button.erms-nav-link') if t('catalogue') in e.text]
        response = page.api.post('/api/v1/auth/logout'); response.raise_for_status()
        from tools.check_webui_browser import PASSWORD
        response = page.api.post('/api/v1/auth/login', json={'email':'viewer@test.invalid','password':PASSWORD})
        response.raise_for_status()
        page.api.headers['X-CSRF-Token'] = page.api.cookies['erms_csrf']
        assert page.api.post('/api/v1/relationships/types/aggregation', json={
            'code': 'denied', 'forward_name': 'Denied', 'reverse_name': 'Denied',
            'translations': {'ar': {'forward_name': 'رفض', 'reverse_name': 'رفض'}}}).status_code == 403
        snapshot('restricted')
    with page.check('relationship browser errors and bounded API requests'):
        page.errors()
        requests = [e for e in page.events() if e['path'].startswith('/api/v1/relationships/types/')]
        for e in requests:
            if e['method'] == 'GET' and e['path'].split('/')[-1] in ('record', 'aggregation'):
                query = parse_qs(e['query'])
                if 'limit' in query: assert int(query['limit'][0]) <= 25
            assert e['status'] is not None and (e['status'] < 400 or
                   (e['controlled'] and e['status'] in (409, 503)) or e['status'] == 403), e
        page.report['relationship_requests'] = requests
