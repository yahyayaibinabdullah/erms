"""Legacy saved-navigation scheme actions, only on runner-owned disposable stacks."""
import os
from urllib.parse import urlsplit


FIXTURE_PATH = '/__webui_test__/restore-scheme-table'


def install_saved_navigation_fixture():
    """Seed an old navigation entry; the production root performs the restore.

    Registered only by the disposable runner for this scope. No renderer, API
    response, application callback, layout or localization is replaced.
    """
    from nicegui import app, ui
    from fastapi import HTTPException

    if 'dbname=erms_webui_test_' not in os.environ.get('DATABASE_URL', ''):
        raise RuntimeError('Saved navigation fixture requires the disposable owning runner')

    @ui.page(FIXTURE_PATH)
    def restore_fixture():
        if not app.storage.user.get('session_token'):
            raise HTTPException(403, 'Sign in to the disposable session first')
        app.storage.user['navigation_trail'] = [{
            'page': 'classification-schemes', 'label': 'Classification schemes',
            'label_key': 'navigation.item.classification_schemes',
            'dynamic_label': False, 'entity_id': None, 'state': {},
        }]
        ui.navigate.to('/')


def check_legacy_schemes(page):
    def row(code):
        return page.wait.until(
            lambda _: next((r for r in page.visible('.erms-page-table tbody tr')
                            if code in r.text), False))

    def restore(code):
        page.errors()
        page.driver.get(page.args.url + FIXTURE_PATH)
        page.wait.until(lambda _: urlsplit(page.driver.current_url).path == '/')
        page.one('.erms-page-table');row(code)

    def icon(code, name):
        return next(b for b in row(code).find_elements('css selector', 'button')
                    if any(i.text == name for i in b.find_elements('css selector', '.q-icon')))

    def state(identity):
        response = page.api.get(f'/api/v1/classification-schemes/{identity}')
        response.raise_for_status()
        return response.json()

    for language in ('en', 'ar'):
        if language == 'ar':
            page.settings();page.language_change('ar')
        code = 'REFRESH-' + language.upper()
        response = page.api.post('/api/v1/classification-schemes', json={
            'code': code, 'title': 'AAA callback refresh ' + language,
        })
        response.raise_for_status();identity = response.json()['id']
        with page.check('saved scheme navigation restores the existing bounded table'):
            restore(code)
            assert page.driver.execute_script('return document.documentElement.dir') == ('rtl' if language == 'ar' else 'ltr')
            assert len(page.visible('.erms-page-table tbody tr')) <= 25
            page.capture('legacy-scheme-restored-' + language)
            page.reload();row(code)
            icon(code, 'publish')
        with page.check('legacy publish/deactivate/reactivate refresh and keep navigation'):
            url = page.driver.current_url
            history = page.driver.execute_script('return history.length')
            for action, glyph, following in (
                ('publish', 'publish', 'toggle_off'),
                ('deactivate', 'toggle_off', 'toggle_on'),
                ('reactivate', 'toggle_on', 'toggle_off'),
            ):
                version = state(identity)['version']
                start = len(page.events())
                old_table = page.one('.erms-page-table')
                page.activate(icon(code, glyph))
                page.wait.until(lambda _: any(e['path'] == '/api/v1/classification-schemes/search'
                    and e['method'] == 'POST' and e['status'] == 200 for e in page.events()[start:]))
                from selenium.webdriver.support import expected_conditions as EC
                page.wait.until(EC.staleness_of(old_table))
                icon(code, following)
                updated = state(identity)
                assert updated['version'] == version + 1
                if action == 'publish':
                    assert updated['date_published']
                    assert not any(i.text == 'publish' for i in row(code).find_elements('css selector', '.q-icon'))
                else:
                    assert bool(updated['date_deactivated']) == (action == 'deactivate')
                writes = [e for e in page.events()[start:] if e['method'] == 'POST'
                          and e['path'] == f'/api/v1/classification-schemes/{identity}/{action}']
                reads = [e for e in page.events()[start:] if e['method'] == 'POST'
                         and e['path'] == '/api/v1/classification-schemes/search']
                assert len(writes) == len(reads) == 1
                assert writes[0]['status'] == 200
                assert page.driver.current_url == url
                assert page.driver.execute_script('return history.length') == history
                page.capture('legacy-scheme-' + action + '-' + language)
                assert not page.errors(), page.errors()
            page.reload();icon(code, 'toggle_off')
            assert state(identity)['date_published'] and state(identity)['date_deactivated'] is None
        with page.check('dedicated workspace still opens from menu and restores on reload'):
            page.drawer('classification_schemes')
            page.one('.classification-workspace')
            page.fill(page.t('webui.select_classification_workspace.input.filter_schemes_a7f4591e'), code)
            page.click(code + ' — AAA callback refresh ' + language)
            page.one('.classification-actions-panel')
            page.see(page.t('webui.render_workspace_right.button.deactivate_ee74ba2e'))
            page.reload();page.one('.classification-actions-panel')
            page.capture('legacy-scheme-workspace-return-' + language)
            assert not page.errors(), page.errors()
    assert not [e for e in page.events() if e['status'] is None or e['status'] >= 400]
