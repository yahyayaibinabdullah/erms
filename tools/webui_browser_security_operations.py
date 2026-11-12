"""Security oversight, periods and resource links on disposable browser sessions."""
import subprocess
from datetime import datetime
from urllib.parse import parse_qs
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
 c.execute("""INSERT INTO event_history(id,occurred_at,transaction_id,entity_type,entity_id,operation,actor_name,actor_type,source,reason)
    SELECT 910000+i,'2030-01-01 12:00:00+00'::timestamptz + (i/2)*interval '1 second',
           6002,'record',%s,'ACCESS_EXPLANATION_VIEWED','Security paging actor ' || i,
           'automated_process','seeding','Synthetic security baseline'
      FROM generate_series(0,102) AS i""", (record,))
 c.execute("""INSERT INTO event_history(id,occurred_at,transaction_id,entity_type,entity_id,operation,actor_type,source,reason)
    VALUES(910103,'2030-01-01 12:00:00+00',6002,'record',%s,'CONTENT_VIEWED','automated_process','seeding','Outside operation scope'),
          (910104,'2030-01-03 12:00:00+00',6002,'record',%s,'ACCESS_EXPLANATION_VIEWED','automated_process','seeding','Outside date range')""",
    (record, record))
 c.execute("""INSERT INTO event_history(id,occurred_at,transaction_id,entity_type,entity_id,operation,actor_type,source,metadata)
     SELECT 930000+i,'2031-01-01 12:00:00+00',6003,'record',%s,'AUTHORIZATION_DENIED',
            'automated_process','seeding',jsonb_build_object('decision_code','insufficient_privilege',
             'required_privilege','paging.denial.' || lpad((i %% 53)::text,3,'0'))
       FROM generate_series(0,53) i""", (record,))
'''],check=True,timeout=30)
    def key(s):return page.t('webui.select_security_operations.'+s)
    def cards():return page.visible('.governance-custody-assignment-card')
    def capture(name,target=None):page.capture('security-operations-'+name+'-'+page.language,target=target)
    def choose_custom():
        page.activate(page.field(key('select.period_ed31c1a0')))
        page.wait.until(lambda _:page.visible('.q-menu'))
        item=page.wait.until(lambda _:next((e for e in page.visible('.q-menu .q-item') if plain(e.text)==key('select.custom_4d95447c')),False));page.activate(item)
        page.field(key('input.from_a135a152'))
    def set_dates(start,end):
        # Native date controls have locale-specific keystroke segments. Set their
        # DOM input values and dispatch their normal input/change events; all
        # validation, requests and rendering still run through the application.
        for label,value in [(key('input.from_a135a152'),start),(key('input.through_b5ed408a'),end)]:
            field=page.field(label)
            page.driver.execute_script("arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}));arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",field,value)
    def dates(start,end):
        set_dates(start,end)
        page.click(key('button.apply_range_53faab3c'))
    def enter():
        page.drawer('security_operations');page.see(page.t('webui.load_security_operations.label.administrative_access_and_security_level_c_6d5dbfc3'))
    def pager_button(direction):
        message, icon = {
            'next': ('next_1b5d6dc7', 'chevron_right'),
            'previous': ('previous_49e3a635', 'chevron_left'),
        }[direction]
        label = page.t('webui.load_security_operations.button.' + message)
        return page.wait.until(lambda _: next((
            button for button in page.visible('button') if label in plain(button.text)
            and any(item.text == icon for item in button.find_elements('css selector', '.q-icon'))
        ), False))
    def expect_page(offset):
        expected = list(range(102-offset, max(-1, 92-offset), -1))
        def matches(_):
            shown = cards()
            if len(shown) != len(expected):
                return False
            return all(f'Security paging actor {number}' in card.text.splitlines()
                       for card, number in zip(shown, expected))
        page.wait.until(matches, f'Incorrect security event order or page size at offset {offset}')
        page.see(page.t('webui.render_security_event_cards.text.start_end_of_event_row_count_7e8f78d3').format(
            start=offset+1, end=offset+len(expected), event_row_count=103,
        ))
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
            dates('2030-01-01','2030-01-02');expect_page(0)
            summary_request = next(e for e in reversed(page.events()) if e['path'].endswith('/security-operations/summary'))
            applied = parse_qs(summary_request['query'])
            assert applied['recent_event_limit'] == ['10']
            capture('custom');capture('events',cards()[0])
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('security events beyond 100 use the applied range and bounded server pages'):
            assert not pager_button('previous').is_enabled()
            set_dates('2030-01-04','2030-01-05')
            start = len(page.events())
            for offset in range(10, 101, 10):
                page.activate(pager_button('next'))
                expect_page(offset)
            assert not pager_button('next').is_enabled()
            capture('past-100',cards()[0])
            page.activate(pager_button('previous'))
            expect_page(90)
            page.activate(pager_button('next'))
            expect_page(100)
            requests = [e for e in page.events()[start:] if '/security-operations/' in e['path']]
            assert all(e['path'].endswith('/security-operations/events') and e['status'] == 200 for e in requests), requests
            pages = [parse_qs(e['query']) for e in requests]
            for params in pages:
                for field in ('start_at', 'end_at'):
                    assert datetime.fromisoformat(params[field][0]) == datetime.fromisoformat(applied[field][0])
            assert pages == [
                {**pages[0], 'limit': ['10'], 'offset': [str(offset)]}
                for offset in [*range(10, 101, 10), 90, 100]
            ], pages
        with page.check('security event destination, refresh and empty period'):
            target=next(e for e in cards()[0].find_elements('css selector','.cursor-pointer') if 'TEST-REC' in e.text);page.activate(target)
            page.see(page.t('webui.select_record_details.button.edit_metadata_d7742b94'));page.one('.component-list');capture('record')
            enter();choose_custom();dates('2030-01-01','2030-01-02');expect_page(0)
            old = cards()[0]
            page.click(key('button.refresh_aa2c487e'))
            page.wait.until(EC.staleness_of(old))
            expect_page(0)
            capture('return')
            dates('2030-01-04','2030-01-05')
            page.see(page.t('webui.render_security_event_cards.label.no_recent_security_events_in_this_period_6d8fd436'))
            assert not cards() and not pager_button('previous').is_enabled() and not pager_button('next').is_enabled()
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
            page.errors()
        with page.check('denial monitoring shows all groups and the full event total'):
            dates('2031-01-01','2031-01-02')
            page.see('paging.denial.000')
            total_label = page.t('webui.load_security_operations.text.authorization_denials_09e48996')
            assert any(e.text == '54' and total_label in plain(e.find_element('xpath', '../..').text)
                       for e in page.visible('.text-3xl.font-semibold'))
            assert len(page.visible('.security-denial-group')) == 10
            assert not page.one('.security-denial-previous').is_enabled()
            set_dates('2031-01-04','2031-01-05')
            start = len(page.events())
            for offset in range(10, 51, 10):
                page.activate(page.one('.security-denial-next'))
                page.see(f'paging.denial.{offset:03}')
            assert len(page.visible('.security-denial-group')) == 3
            assert not page.one('.security-denial-next').is_enabled()
            page.see('paging.denial.052')
            capture('denial-groups-past-50')
            page.activate(page.one('.security-denial-previous'))
            page.see('paging.denial.040')
            reads = [e for e in page.events()[start:] if '/security-operations/' in e['path']]
            assert all(e['path'].endswith('/denial-groups') and e['status'] == 200 for e in reads)
            params = [parse_qs(e['query']) for e in reads]
            assert [p['offset'] for p in params] == [[str(n)] for n in (10, 20, 30, 40, 50, 40)]
            assert all(p['limit'] == ['11'] and p['start_at'][0].startswith('2031-01-01')
                       and p['end_at'][0].startswith('2031-01-02') for p in params)
            page.errors()
