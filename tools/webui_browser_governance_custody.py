"""Custody report, pagers and connected destinations in native browser sessions."""
import subprocess
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from tools.check_webui_browser import plain


def check_governance_custody(page):
    subprocess.run([page.args.api_python,'-c','''
import os,psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL'];assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 c.execute("SELECT set_config('app.event_source','seeding',true)")
 role=c.execute("SELECT id FROM roles WHERE code='officer'").fetchone()[0]
 for active in (True,False):
  for i in range(6):
   name=('Custodian' if active else 'Attention')+f' {i:02}'
   user=c.execute("INSERT INTO users(name,email,date_created) VALUES(%s,%s,'2026-01-01') RETURNING id",(name,name.lower().replace(' ','')+'@test.invalid')).fetchone()[0]
   c.execute("INSERT INTO user_role_assignments(user_id,role_id,valid_from,valid_until) VALUES(%s,%s,'2026-01-01',%s)",(user,role,None if active else '2026-01-02'))
 c.execute("UPDATE user_role_assignments SET valid_from='2026-01-01'")
 c.execute("UPDATE roles SET date_created='2026-01-01' WHERE code IN ('admin','officer')")
 c.execute("UPDATE users SET date_created='2026-01-01'")
'''],check=True,timeout=30)
    def enter():
        page.drawer('governance_custody');page.wait.until(lambda _:len(page.visible('.governance-metric-card'))==3 and len(page.visible('.governance-card-list'))==2)
    def lists():return page.visible('.governance-card-list')
    def cards(index):return page.visible('.governance-custody-assignment-card',lists()[index])
    def capture(name,target=None):page.capture('custody-'+name+'-'+page.language,target=target)
    def next_page(index):
        old=cards(index)[0];buttons=[b for b in page.visible('button') if plain(b.text).endswith(page.t('webui.select_governance_custody.button.next_1b4b15c1'))]
        page.activate(buttons[index]);page.wait.until(EC.staleness_of(old))
    def icon(name,card):return next(b for b in card.find_elements('css selector','button') if any(e.text==name for e in b.find_elements('css selector','.q-icon')))
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('custody status, refresh focus and two independent pagers'):
            enter();url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            refresh=page.button(page.t('settings.action.refresh'));page.activate(refresh);page.wait.until(EC.staleness_of(refresh));page.wait.until(lambda _:len(cards(0))==5)
            refresh=page.button(page.t('settings.action.refresh'));refresh.send_keys(Keys.TAB)
            active=page.driver.switch_to.active_element;assert active.tag_name=='button' and plain(active.text).endswith(page.t('settings.custody.open'))
            page.report.setdefault('focus',[]).append({'language':language,'from':'refresh','to':'open settings'})
            capture('overview');capture('custodians',cards(0)[0]);capture('attention',cards(1)[0])
            next_page(0);assert len(cards(0))==3;capture('custodians-next',cards(0)[0])
            next_page(1);assert len(cards(1))==1;capture('attention-next',cards(1)[0])
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('custody Settings, user and role destinations with return'):
            page.click(page.t('settings.custody.open'));page.one('.application-settings-page');page.wait.until(lambda _:plain(page.one('[role=tab][aria-selected=true]').text)==page.t('settings.category.disposition'));capture('settings')
            enter();page.activate(icon('person',cards(0)[0]));page.one('.identity-command-layout');capture('user')
            enter();page.activate(icon('badge',cards(0)[0]));page.one('.identity-command-layout');capture('role')
            enter();capture('return')
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
            page.errors()
