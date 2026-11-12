"""Login-session administration on disposable Chrome/Edge stacks."""
import subprocess,time
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def check_login_sessions(page):
    subprocess.run([page.args.api_python,'-c', '''
import os,psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL'];assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 c.execute("SELECT set_config('app.event_source','seeding',true)")
 user=c.execute("SELECT id FROM users WHERE email='viewer@test.invalid'").fetchone()[0]
 for i in range(26):
  status='active' if i==0 else 'revoked' if i==1 else 'expired'
  c.execute("""INSERT INTO login_sessions(user_id,session_token_hash,csrf_token_hash,date_created,last_seen_at,expires_at,absolute_expires_at,revoked_at,client_ip,user_agent)
  VALUES(%s,%s,%s,'2026-01-01T12:00:00Z'::timestamptz + %s * interval '1 second','2026-01-01T12:00:00Z',%s,%s,%s,'127.0.0.1',%s)""",
  (user,os.urandom(32),os.urandom(32),i,'2099-01-01' if i==0 else '2026-01-02','2099-01-01','2026-01-01T13:00:00Z' if i==1 else None,f'Phase6F {status} {i:02} Chrome/1 Macintosh'))
'''],check=True,timeout=30)
    def capture(name):page.capture('login-sessions-'+name+'-'+page.language)
    def filter_query(query):
        field=page.field(page.t('webui.select_login_sessions.input.user_or_client_e41c0521'))
        page.activate(field);field.send_keys(Keys.COMMAND,'a',Keys.NULL);field.send_keys(query,Keys.ENTER)
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('session filters, server paging and keyboard focus'):
            page.drawer('login_sessions');page.one('.login-session-card-grid')
            filter_query('Phase6F');page.wait.until(lambda _:len(page.visible('.login-session-card'))==20)
            capture('page-one')
            page.click(page.t('webui.select_login_sessions.button.last_5cfe5c95'))
            page.wait.until(lambda _:len(page.visible('.login-session-card'))==6)
            capture('page-two')
            field=page.field(page.t('webui.select_login_sessions.input.user_or_client_e41c0521'))
            page.activate(field);field.send_keys(Keys.TAB)
            target=page.driver.switch_to.active_element
            assert target.tag_name!='body'
            page.report.setdefault('login_sessions_focus',[]).append({'language':language,'tag':target.tag_name,'type':target.get_attribute('type'),'label':target.get_attribute('aria-label')})
        with page.check('revocation cancellation, empty state and navigation'):
            filter_query('Phase6F active');page.wait.until(lambda _:len(page.visible('.login-session-card'))==1)
            card=page.one('.login-session-card');page.activate(next(b for b in card.find_elements('css selector','button') if b.text.strip()=='logout'))
            page.one('.q-dialog__inner > .q-card');capture('confirmation')
            page.click(page.t('webui.confirm_revoke.button.cancel_9fc0545b'))
            page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
            filter_query('Phase6F absent');page.see(page.t('webui.select_login_sessions.label.no_login_sessions_match_these_filters_2c8578fd'));capture('empty')
            page.errors()
            url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            page.settings();page.drawer('login_sessions');page.one('.login-session-card-grid')
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
            page.errors()
    with page.check('no cancelled revocation writes or unexpected browser errors'):
        assert not [e for e in page.events() if e['method']=='DELETE' and '/auth/' in e['path']]
        page.errors()
