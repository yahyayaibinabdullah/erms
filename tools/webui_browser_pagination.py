"""Native pagination checks for every former Boolean icon-right consumer."""
import subprocess
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from tools.check_webui_browser import plain


def check_pagination(page):
    # Create a service identity through its real contract; discard its one-time key.
    response = page.api.post('/api/v1/text-indexers', json={
        'name':'Pager icon credential fixture', 'external_id':'pagination-icon-service',
        'credential_name':'PAGINATIONFIX key 00',
        'expires_at':(datetime.now(timezone.utc)+timedelta(days=90)).isoformat()})
    response.raise_for_status()
    del response
    subprocess.run([page.args.api_python, '-c', '''
import os,psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL'];assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 c.execute("SELECT set_config('app.event_source','seeding',true)")
 level=c.execute('SELECT id FROM security_levels ORDER BY level_number LIMIT 1').fetchone()[0]
 maximum=c.execute('SELECT max(level_number) FROM security_levels').fetchone()[0]
 profile=c.execute('SELECT id FROM profiles ORDER BY id LIMIT 1').fetchone()[0]
 unit=c.execute("SELECT id FROM org_units WHERE code='WEBUI-TEST'").fetchone()[0]
 viewer=c.execute("SELECT id FROM users WHERE email='viewer@test.invalid'").fetchone()[0]
 service=c.execute("SELECT id FROM users WHERE external_id='pagination-icon-service'").fetchone()[0]
 for i in range(51):
  code=f'PAGINATIONFIX-{i:02}';name=f'PAGINATIONFIX {i:02}'
  c.execute('INSERT INTO profiles(code,name) VALUES(%s,%s)',(code,name))
  c.execute('INSERT INTO security_levels(code,name,level_number) VALUES(%s,%s,%s)',(code,name,maximum+i+1))
  c.execute('INSERT INTO org_units(code,name) VALUES(%s,%s)',(code,name))
  c.execute('INSERT INTO roles(code,name,profile_id,security_level_id,org_unit_id) VALUES(%s,%s,%s,%s,%s)',(code,name,profile,level,unit))
  c.execute('INSERT INTO users(name,email) VALUES(%s,%s)',(name,f'paginationfix-{i:02}@test.invalid'))
 for i in range(41):
  c.execute("""INSERT INTO login_sessions(user_id,session_token_hash,csrf_token_hash,date_created,last_seen_at,expires_at,absolute_expires_at,client_ip,user_agent)
   VALUES(%s,%s,%s,'2026-01-01'::timestamptz + %s * interval '1 second','2026-01-01','2026-01-02','2026-01-02','127.0.0.1',%s)""",(viewer,os.urandom(32),os.urandom(32),i,f'PAGINATIONFIX Chrome/1 Macintosh {i:02}'))
 for i in range(1,11):
  c.execute("""INSERT INTO service_account_credentials(service_user_id,name,credential_identifier,secret_hash,expires_at)
   VALUES(%s,%s,%s,%s,'2099-01-01')""",(service,f'PAGINATIONFIX key {i:02}',str(i).zfill(26),os.urandom(32).hex()))
'''], check=True, timeout=30)

    keys = {'first':'first_6e0613a1','previous':'previous_ff5ac91d','next':'next_7c669a6d','last':'last_cb5252cb'}
    sessions = {'first':'first_3e9443bf','previous':'previous_6631329f','next':'next_b09718d5','last':'last_5cfe5c95'}
    filters = {'security_levels':'filter_security_levels_f290cff4','profiles':'filter_profiles_2f4a2c88',
               'users':'filter_users_87c1f82f','roles':'filter_roles_89b2d475','org_units':'filter_organization_units_472aad07'}
    def button(kind, family='cards'):
        if family=='credentials':
            key='webui.select_text_indexer_details.button.'+{'previous':'previous_86972be8','next':'next_e284c9ef'}[kind]
        else:
            key=('webui.render_table.button.' if family=='cards' else 'webui.select_login_sessions.button.')+(keys if family=='cards' else sessions)[kind]
        return page.button(page.t(key))
    def icons(family='cards'):
        expected={'first':'first_page','previous':'chevron_left','next':'chevron_right','last':'last_page'}
        if family=='credentials':
            expected={k:v for k,v in expected.items() if k in {'previous','next'}}
            if page.language=='ar':expected={'previous':'chevron_right','next':'chevron_left'}
        for kind, icon in expected.items():
            found=page.visible('.q-icon',button(kind,family))
            assert len(found)==1 and found[0].text==icon, (family,kind,[i.text for i in found])
    def capture(name):page.capture('pagination-'+name+'-'+page.language)
    def credentials():
        return [c for c in page.visible('.governance-list-card') if 'PAGINATIONFIX key' in plain(c.text)]
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        for resource,filter_key in filters.items():
            with page.check(resource+' icons, four paging actions and empty boundary'):
                previous=page.visible('.governance-card-list')
                page.drawer(resource)
                if previous:page.wait.until(EC.staleness_of(previous[0]))
                page.wait.until(lambda _:page.visible('.governance-list-card'))
                page.fill(page.t('webui.render_table.input.'+filter_key),'PAGINATIONFIX-')
                # Users search by name/email, the other resources also search code.
                if resource=='users':page.fill(page.t('webui.render_table.input.'+filter_key),'paginationfix-')
                def rows():return page.visible('.governance-list-card')
                def ready(offset):
                    matches=rows()
                    return len(matches)==min(25,51-offset) and plain(matches[0].find_element('css selector','.font-semibold.text-base').text)==f'PAGINATIONFIX {offset:02}'
                page.wait.until(lambda _:ready(0));icons()
                assert not button('first').is_enabled() and not button('previous').is_enabled()
                capture(resource+'-first')
                for kind, offset in [('next',25),('last',50),('previous',25),('first',0)]:
                    assert button(kind).is_enabled()
                    # Keyboard activation verifies the same actual event path as mouse use.
                    button(kind).send_keys(Keys.ENTER)
                    page.wait.until(lambda _:ready(offset));icons();page.errors()
                    assert button('last').is_enabled()==(offset<50)
                    assert button('first').is_enabled()==(offset>0)
                    if offset==50:capture(resource+'-last')
                page.fill(page.t('webui.render_table.input.'+filter_key),'paginationfix-absent')
                page.see(page.t('webui.render_governance_cards.label.no_matching_items_38db9ba1'))
                assert all(not button(k).is_enabled() for k in keys)
                page.errors()
                page.report.setdefault('pagination',[]).append({'language':language,'consumer':resource,'offsets':[0,25,50,25,0],
                    'icons_valid':True,'keyboard':True,'empty_boundary':True})
        with page.check('login-session icons, four paging actions and empty boundary'):
            page.drawer('login_sessions');page.one('.login-session-card-grid')
            field='webui.select_login_sessions.input.user_or_client_e41c0521'
            page.fill(page.t(field),'PAGINATIONFIX');page.field(page.t(field)).send_keys(Keys.ENTER)
            def session_rows():return page.visible('.login-session-card')
            page.wait.until(lambda _:len(session_rows())==20);icons('sessions');capture('sessions-first')
            for kind,offset,count in [('next',20,20),('last',40,1),('previous',20,20),('first',0,20)]:
                start=len(page.events());button(kind,'sessions').send_keys(Keys.ENTER)
                page.wait.until(lambda _:any(e['path']=='/api/v1/auth/sessions/page' and e['status']==200
                    and parse_qs(e['query']).get('offset')==[str(offset)] for e in page.events()[start:]))
                page.wait.until(lambda _:len(session_rows())==count);icons('sessions')
                assert button('last','sessions').is_enabled()==(offset<40)
                assert button('first','sessions').is_enabled()==(offset>0)
                if offset==40:capture('sessions-last')
            page.fill(page.t(field),'PAGINATIONFIX absent');page.field(page.t(field)).send_keys(Keys.ENTER)
            page.see(page.t('webui.select_login_sessions.label.no_login_sessions_match_these_filters_2c8578fd'))
            assert all(not button(k,'sessions').is_enabled() for k in keys);page.errors()
            page.report.setdefault('pagination',[]).append({'language':language,'consumer':'login_sessions','offsets':[0,20,40,20,0],
                'icons_valid':True,'keyboard':True,'empty_boundary':True})
        with page.check('credential icons, RTL direction and bounded next/previous'):
            page.drawer('text_indexers');page.see('Pager icon credential fixture')
            page.activate(next(c for c in page.visible('.governance-list-card') if 'Pager icon credential fixture' in plain(c.text)))
            page.wait.until(lambda _:len(credentials())==5);icons('credentials');capture('credentials-first')
            assert not button('previous','credentials').is_enabled()
            for kind,offset,count in [('next',5,5),('next',10,1),('previous',5,5),('previous',0,5)]:
                start=len(page.events());button(kind,'credentials').send_keys(Keys.ENTER)
                page.wait.until(lambda _:any(e['path'].endswith('/credentials') and e['status']==200
                    and parse_qs(e['query']).get('offset')==[str(offset)] for e in page.events()[start:]))
                page.wait.until(lambda _:len(credentials())==count);icons('credentials')
                assert button('next','credentials').is_enabled()==(offset<10)
                if offset==10:capture('credentials-last')
            page.errors()
            page.report.setdefault('pagination',[]).append({'language':language,'consumer':'credentials','offsets':[0,5,10,5,0],
                'icons_valid':True,'keyboard':True,'rtl_direction':True})
            page.settings()
    assert not [e for e in page.events() if e['status'] is None or e['status']>=400]
    # The browser journeys only read; mutations above are explicitly synthetic setup.
    assert not [e for e in page.events() if e['method']=='DELETE']
