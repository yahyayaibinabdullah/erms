"""Security oversight, periods and resource links on disposable browser sessions."""
import subprocess
from tools.check_webui_browser import plain
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC


def check_security_operations(page):
    subprocess.run([page.args.api_python,'-c','''
import os,psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL'];assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 record=c.execute("SELECT id FROM records WHERE record_number='TEST-REC'").fetchone()[0]
 for i in range(11):
  c.execute("""INSERT INTO event_history(id,occurred_at,transaction_id,entity_type,entity_id,operation,actor_name,actor_type,source,reason)
    VALUES(%s,'2030-01-01'::timestamptz + %s*interval '1 second',6002,'record',%s,'ACCESS_EXPLANATION_VIEWED','Synthetic security actor','automated_process','seeding','Synthetic security baseline')""",(910000+i,i,record))
'''],check=True,timeout=30)
    def key(s):return page.t('webui.select_security_operations.'+s)
    def cards():return page.visible('.governance-custody-assignment-card')
    def capture(name,target=None):page.capture('security-operations-'+name+'-'+page.language,target=target)
    def choose_custom():
        page.activate(page.field(key('select.period_ed31c1a0')))
        page.wait.until(lambda _:page.visible('.q-menu'))
        item=page.wait.until(lambda _:next((e for e in page.visible('.q-menu .q-item') if plain(e.text)==key('select.custom_4d95447c')),False));page.activate(item)
        page.field(key('input.from_a135a152'))
    def dates(start,end):
        # Native date controls have locale-specific keystroke segments. Set their
        # DOM input values and dispatch their normal input/change events; all
        # validation, requests and rendering still run through the application.
        for label,value in [(key('input.from_a135a152'),start),(key('input.through_b5ed408a'),end)]:
            field=page.field(label)
            page.driver.execute_script("arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}));arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",field,value)
        page.click(key('button.apply_range_53faab3c'))
    def enter():
        page.drawer('security_operations');page.see(page.t('webui.load_security_operations.label.administrative_access_and_security_level_c_6d5dbfc3'))
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('security custom-period validation, keyboard focus and bounded event page'):
            enter();url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            choose_custom();start=len(page.events());page.click(key('button.apply_range_53faab3c'))
            page.wait.until(lambda _:page.visible('.q-notification'))
            assert not any(e['path'].endswith('/security-operations/summary') for e in page.events()[start:])
            first=page.field(key('input.from_a135a152'));page.activate(first)
            # Date fields contain native segments; Tab leaves the final year segment.
            first.send_keys(Keys.END,Keys.TAB)
            active=page.driver.switch_to.active_element
            assert active.tag_name in {'input','button'}
            page.report.setdefault('focus',[]).append({'language':language,'tag':active.tag_name,'type':active.get_attribute('type')})
            dates('2030-01-01','2030-01-02');page.wait.until(lambda _:len(cards())==10)
            capture('custom');capture('events',cards()[0])
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('security event paging and record destination return'):
            old=cards()[0];page.click(page.t('webui.load_security_operations.button.next_1b5d6dc7'));page.wait.until(EC.staleness_of(old));page.wait.until(lambda _:len(cards())==1);capture('next',cards()[0])
            target=next(e for e in cards()[0].find_elements('css selector','.cursor-pointer') if 'TEST-REC' in e.text);page.activate(target)
            page.see(page.t('webui.select_record_details.button.edit_metadata_d7742b94'));page.one('.component-list');capture('record')
            enter();choose_custom();dates('2030-01-01','2030-01-02');page.wait.until(lambda _:len(cards())==10)
            page.click(key('button.refresh_aa2c487e'));page.wait.until(lambda _:len(cards())==10);capture('return')
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
            page.errors()
