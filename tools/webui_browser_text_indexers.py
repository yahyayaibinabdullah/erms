"""Indexer UI comparison; no secret reveal or download enters browser evidence."""
import subprocess
from datetime import datetime,timedelta,timezone
from selenium.webdriver.common.keys import Keys


def check_text_indexers(page):
    expiry=(datetime.now(timezone.utc)+timedelta(days=90)).replace(microsecond=0).isoformat()
    response=page.api.post('/api/v1/text-indexers',json={'name':'Phase6H indexer','external_id':'phase6h-browser','credential_name':'Fixture key','expires_at':expiry})
    assert response.status_code==201
    # Discard the one-time secret; browser evidence contains public metadata only.
    del response
    subprocess.run([page.args.api_python,'-c','''
import os,psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL'];assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 c.execute("SELECT set_config('app.event_source','seeding',true)")
 c.execute("UPDATE users SET date_created='2026-01-01' WHERE external_id='phase6h-browser'")
 c.execute("UPDATE service_account_credentials SET date_created='2026-01-01',expires_at='2099-01-01',credential_identifier='00000000000000000000000001' WHERE service_user_id=(SELECT id FROM users WHERE external_id='phase6h-browser')")
'''],check=True,timeout=30)
    fixture_request_end=len(page.events())
    def capture(name):page.capture('indexers-'+name+'-'+page.language)
    def click(key,root=None):page.click(page.t(key),root)
    def cancel(key):
        click(key,page.one('.q-dialog__inner > .q-card'))
        page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('indexer list filter, operational dialogs and cancelled writes'):
            page.drawer('text_indexers');page.see('Phase6H indexer')
            # Record the real observation-time region, without altering the UI.
            observed=next(e for e in page.visible('.text-xs.text-slate-500') if page.t('webui.select_text_indexers.text.observed_format_timestamp_2519c007').split('{')[0] in e.text)
            page.report.setdefault('observation_regions',[]).append({'language':language,'rect':observed.rect,'text':observed.text})
            capture('list')
            assert page.button(page.t('webui.select_text_indexers.button.retry_failed_d128e4bd')).get_attribute('disabled')
            for icon,submit_cancel,name in [('playlist_add','webui.queue_backfill_dialog.button.cancel_3c7e55da','backfill')]:
                page.activate(next(b for b in page.visible('button') if any(i.text==icon for i in b.find_elements('css selector','.q-icon'))))
                page.one('.q-dialog__inner > .q-card');capture(name);cancel(submit_cancel)
            field=page.field(page.t('webui.select_text_indexers.input.filter_by_name_or_external_id_3d14f34f'))
            page.activate(field);field.send_keys('no-match')
            page.see(page.t('webui.render.label.no_matching_text_indexers_064a7cfd'));capture('empty')
            field.send_keys(Keys.COMMAND,'a',Keys.NULL,Keys.BACKSPACE)
            page.see('Phase6H indexer')
        with page.check('indexer details, credential metadata and keyboard cancellation'):
            page.activate(page.one('.governance-list-card'))
            page.see(page.t('webui.select_text_indexer_details.label.api_credentials_66a20b8e'))
            page.see('Fixture key');capture('detail');page.errors()
            click('webui.select_text_indexer_details.button.generate_api_key_35bdc780')
            d=page.one('.q-dialog__inner > .q-card')
            expiryfield=page.field(page.t('webui.credential_dialog.input.expiry_iso_8601_222d3b9f'))
            expiryfield.send_keys(Keys.COMMAND,'a',Keys.NULL,'2099-01-01T00:00:00Z',Keys.TAB)
            focus=page.driver.switch_to.active_element
            assert page.driver.execute_script('return arguments[0].contains(arguments[1])',d,focus)
            page.report.setdefault('indexer_focus',[]).append({'language':language,'tag':focus.tag_name,'type':focus.get_attribute('type'),'label':focus.get_attribute('aria-label')})
            page.activate(d.find_element('css selector','.text-xl'));capture('generate');cancel('webui.credential_dialog.button.cancel_f4440fc5')
            click('webui.render_credentials.button.revoke_4fc0db3b');page.one('.q-dialog__inner > .q-card');capture('revoke');cancel('webui.confirm_revoke.button.cancel_9fc0545b')
            url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            click('webui.select_text_indexer_details.button.back_to_text_indexers_34b66935')
            page.field(page.t('webui.select_text_indexers.input.filter_by_name_or_external_id_3d14f34f'))
            page.one('.governance-card-list');page.see('Phase6H indexer')
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('indexer browser errors and no cancelled mutations'):
            assert not [e for e in page.events()[fixture_request_end:] if e['method'] in {'POST','PUT','DELETE'} and e['path'].startswith('/api/v1/text-indexers')]
            page.errors()
