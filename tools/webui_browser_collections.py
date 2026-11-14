"""Shared entity controls exercised against a disposable real API."""
import subprocess
import time
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC


def check_collections(page):
    # The canonical seed creates administration rows at the current time.
    # Fix only their displayed timestamps in this runner-owned fixture, before
    # visiting those lists. Restore the touch trigger in the same transaction;
    # all application requests retain normal triggers and validation.
    subprocess.run([page.args.api_python, '-c', '''
import os, psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL']
assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as connection:
    connection.execute("SELECT set_config('app.event_source','seeding',true)")
    connection.execute("ALTER TABLE profiles DISABLE TRIGGER profiles_touch")
    connection.execute("UPDATE profiles SET date_updated='2026-01-01T00:00:00Z'")
    connection.execute("ALTER TABLE profiles ENABLE TRIGGER profiles_touch")
    connection.execute("UPDATE users SET date_created='2026-01-01T00:00:00Z'")
    connection.execute("UPDATE org_units SET date_created='2026-01-01T00:00:00Z'")
    assert connection.execute("SELECT tgenabled FROM pg_trigger WHERE tgname='profiles_touch'").fetchone()[0]=='O'
'''], check=True, timeout=30)
    page.report['collection_fixture_date'] = '2026-01-01T00:00:00Z'
    def capture(name):
        page.capture('collections-' + name + '-' + page.language)

    for language in ('en', 'ar'):
        if language == 'ar':
            page.settings()
            page.language_change('ar')
        for resource in ('security_levels', 'profiles', 'users', 'roles', 'org_units'):
            with page.check(resource + ' bounded cards, empty filter, editor and keyboard'):
                previous = page.visible('.governance-card-list')
                page.drawer(resource)
                if previous:
                    page.wait.until(EC.staleness_of(previous[0]))
                page.wait.until(lambda _: page.visible('.governance-list-card'))
                assert len(page.visible('.governance-list-card')) <= 25
                capture(resource)
                card = page.visible('.governance-list-card')[0]
                edit = next(b for b in card.find_elements('css selector', 'button') if b.text.strip() == 'edit')
                edit.click()
                dialog = page.one('.q-dialog__inner > .q-card')
                inputs = [e for e in dialog.find_elements('css selector', 'input,textarea') if e.is_enabled()]
                if inputs:
                    inputs[0].click()
                    # Opening a relationship menu starts its existing bounded
                    # option load. Let that update settle before observing Tab.
                    time.sleep(.6)
                    inputs[0].send_keys(Keys.TAB)
                    time.sleep(.3)
                    focus = page.driver.switch_to.active_element
                    assert page.driver.execute_script('return arguments[0].contains(arguments[1])', dialog, focus)
                    page.report.setdefault('collection_focus', []).append({
                        'language': language, 'resource': resource,
                        'tag': focus.tag_name, 'type': focus.get_attribute('type'),
                        'label': focus.get_attribute('aria-label'),
                    })
                # Observe keyboard focus above; use an ordinary click on the
                # non-interactive heading for a caret-free visual comparison.
                page.activate(dialog.find_element('css selector', '.text-xl'))
                capture(resource + '-editor')
                page.click(page.t('webui.open_editor.button.cancel_c07bff03'), dialog)
                page.wait.until(lambda _: not page.visible('.q-dialog__inner > .q-card'))
                field = page.visible('.erms-card input')[0]
                field.click()
                field.send_keys(Keys.COMMAND, 'a', Keys.NULL)
                field.send_keys('zz_phase6c_absent')
                page.see(page.t('webui.render_governance_cards.label.no_matching_items_38db9ba1'))
                page.activate(page.one('.governance-card-list'))
                capture(resource + '-empty')
                field.click()
                field.send_keys(Keys.COMMAND, 'a', Keys.NULL)
                field.send_keys(Keys.BACKSPACE)
                page.wait.until(lambda _: field.get_attribute('value') == '')
                field.send_keys(Keys.TAB)
                page.wait.until(lambda _: page.visible('.governance-list-card'))
                page.errors()

        with page.check('record compact results, favourites, personal panels and parent navigation'):
            page.drawer('records')
            page.wait.until(lambda _: len(page.visible('.dashboard-personal-panel')) == 2)
            page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'), 'TEST-REC')
            page.click(page.t('webui.index.button.search_4d02b714'), page.one('.erms-card'))
            row = page.one('.compact-result-item')
            capture('record-results')
            favourite = next(b for b in row.find_elements('css selector', 'button') if 'favorite' in b.text)
            def toggle():
                start = len(page.events())
                favourite.click()
                page.wait.until(lambda _: any(e['method'] in {'PUT', 'DELETE'}
                    and e['path'].startswith('/api/v1/favourites/records/') and e['status'] == 204
                    for e in page.events()[start:]))
                page.wait.until(lambda _: not favourite.get_attribute('disabled'))
            toggle()
            if 'favorite_border' in favourite.text:
                toggle()
            page.drawer('dashboard')
            page.one('.dashboard-overview-primary')
            page.see('Test record')
            page.drawer('records')
            page.wait.until(lambda _: len(page.visible('.dashboard-personal-panel')) == 2)
            capture('record-personal')
            page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'), 'TEST-REC')
            page.click(page.t('webui.index.button.search_4d02b714'), page.one('.erms-card'))
            page.one('button[aria-label="Open record"]', scope=page.one('.compact-result-item')).click()
            # The containing-aggregation link appears before the component
            # section finishes. Wait for the empty fixture's completed load so
            # before/after request counts do not depend on navigation timing.
            page.see(page.t('webui.render_current_components.label.no_digital_components_have_been_uploaded_y_3f61a29a'))
            page.one('button.detail-linked-entity').click()
            page.see(page.t('webui.open_aggregation.label.aggregation_overview_bb8398e3'))
            capture('aggregation-detail')
    with page.check('shared controls browser errors'):
        page.errors()
