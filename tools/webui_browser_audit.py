"""Audit workspace baselines on disposable real-browser/API stacks."""
import subprocess
from urllib.parse import parse_qs
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC

CORRELATION = '66666666-6666-4666-8666-666666666666'


def check_audit(page):
    # Fixed synthetic events preserve deterministic history cards and details.
    # The future date only keeps these rows ahead of run-time login/seed events.
    subprocess.run([page.args.api_python, '-c', '''
import os, psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
url=os.environ['DATABASE_URL']
assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 record=c.execute("SELECT id FROM records WHERE record_number='TEST-REC'").fetchone()[0]
 for i in range(55):
  c.execute("""INSERT INTO event_history(id,occurred_at,transaction_id,entity_type,entity_id,operation,
   actor_name,actor_email,actor_type,source,correlation_id,before_state,after_state,changed_fields,reason,metadata)
   VALUES(%s,'2030-01-01'::timestamptz + %s*interval '1 second',6001,'record',%s,'UPDATE',
   'Historical actor','historical@test.invalid','user','seeding',%s,%s,%s,ARRAY['title'],
   'Synthetic audit baseline',%s)""",(900000+i,i,record,'66666666-6666-4666-8666-666666666666',
   Jsonb({'record_number':'TEST-REC','title':'Previous title'}),Jsonb({'record_number':'TEST-REC','title':f'Audit fixture {i:02}'}),
   Jsonb({'reference_snapshots':{'before':{'title':{'name':'Previous title'}},'after':{'title':{'name':f'Audit fixture {i:02}'}}}})))
 c.execute("""INSERT INTO event_history(id,occurred_at,transaction_id,entity_type,entity_id,operation,
               actor_name,actor_type,source)
               SELECT 920000+i,'2029-01-01 12:00:00+00'::timestamptz,6002,'record',%s,
                      'ACCESS_EXPLANATION_VIEWED','Record history fixture ' || lpad(i::text,3,'0'),
                      'automated_process','seeding'
                 FROM generate_series(0,202) i""", (record,))
'''], check=True, timeout=30)
    def key(s): return page.t('webui.select_audit_trail.' + s)
    correlation = lambda: key('input.correlation_id_e6872415')
    apply = lambda: key('button.apply_filters_bf49489c')
    def loaded(): page.wait.until(lambda _: bool(page.visible('.audit-event')))
    def replace_results(action):
        previous=page.visible('.audit-event')
        action()
        if previous: page.wait.until(EC.staleness_of(previous[0]))
    def filtered():
        page.fill(correlation(), CORRELATION)
        replace_results(lambda:page.click(apply()));page.see('Audit fixture 54')
    def capture(name): page.capture('audit-' + name + '-' + page.language)
    def detail():
        dialogs=len(page.visible('.q-dialog__inner > .q-card'))
        cards=page.visible('.audit-event')
        # Open is the first icon; detail is the final button in the event card.
        cards[0].find_elements('css selector','button')[-1].click()
        page.wait.until(lambda _: len(page.visible('.q-dialog__inner > .q-card'))>dialogs)
    def close():
        cards=page.visible('.q-dialog__inner > .q-card')
        card=cards[-1]
        buttons=card.find_elements('css selector','button')
        next(b for b in buttons if 'close' in b.text).click()
        page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card')) < len(cards))
    for language in ('en','ar'):
        if language=='ar': page.settings();page.language_change('ar')
        with page.check('audit drawer entry, bounded pagination, reset and keyboard focus'):
            page.drawer('audit_trail');loaded();filtered()
            assert len(page.visible('.audit-event'))==50
            capture('timeline')
            field=page.field(correlation());field.click();field.send_keys(Keys.TAB)
            focus=page.driver.switch_to.active_element
            sequence=[]
            for _ in range(4):
                sequence.append({'tag':focus.tag_name,'text':focus.text,'role':focus.get_attribute('role'),'aria_label':focus.get_attribute('aria-label')})
                if page.t('audit.filter.clear') in focus.text: break
                focus.send_keys(Keys.TAB);focus=page.driver.switch_to.active_element
            assert page.t('audit.filter.clear') in focus.text,sequence
            page.report.setdefault('audit_focus',[]).append({'language':language,'sequence':sequence})
            replace_results(lambda:page.click(key('button.next_4982f418')));page.see('Audit fixture 04')
            assert len(page.visible('.audit-event'))==5
            capture('second-page')
            replace_results(lambda:page.click(key('button.previous_928715e5')));page.see('Audit fixture 54')
            replace_results(lambda:page.click(page.t('audit.filter.clear')))
            page.wait.until(lambda _:page.field(correlation()).get_attribute('value')=='')
            filtered()
        with page.check('audit paging keeps the applied correlation filter until Apply'):
            draft='77777777-7777-4777-8777-777777777777'
            page.fill(correlation(),draft)
            started=len(page.events())
            replace_results(lambda:page.click(key('button.next_4982f418')))
            page.see('Audit fixture 04')
            assert len(page.visible('.audit-event'))==5
            assert page.field(correlation()).get_attribute('value')==draft
            reads=[e for e in page.events()[started:] if e['path']=='/api/v1/event-history/search']
            assert len(reads)==1 and reads[0]['status']==200
            capture('second-page-pending-filter')
            replace_results(lambda:page.click(apply()))
            page.see(page.t('webui.render_event_timeline.label.no_matching_events_bd2c227e'))
            assert not page.button(key('button.previous_928715e5')).is_enabled()
            filtered()
        with page.check('audit details preserve snapshots, collapsed technical section and current-record link'):
            detail();page.see('Previous title');page.see('Historical actor')
            capture('detail')
            assert not page.visible('.q-dialog pre')
            page.click(page.t('webui.show_event_detail.button.open_entity_ef774537'),page.one('.q-dialog__inner > .q-card'))
            page.one('button.detail-linked-entity')
            page.see('Test record')
            history_label=page.t('webui.show_entity_history.label.event_history_670b1156')
            page.click(page.t('webui.select_record_details.button.event_history_89d2205e'))
            page.see(history_label);page.see('Audit fixture 54')
            capture('entity-history')
            detail();capture('nested-detail');close();close()
        with page.check('record Event History pages past the former 200-event cutoff'):
            start = len(page.events())
            page.click(page.t('webui.select_record_details.button.event_history_89d2205e'))
            page.see(page.t('webui.show_entity_history.label.event_history_670b1156'))
            page.see('Audit fixture 54')
            for offset in range(25, 251, 25):
                old = page.visible('.audit-event')[0]
                page.activate(page.one('.entity-history-next'))
                page.wait.until(EC.staleness_of(old))
                page.wait.until(lambda _: page.visible('.audit-event'))
            page.see('Record history fixture 000')
            assert not page.one('.entity-history-next').is_enabled()
            badge = page.one('.entity-history-range')
            assert badge.text.startswith('251–')
            assert page.driver.execute_script('return getComputedStyle(arguments[0]).direction', badge) == 'ltr'
            capture('history-past-200')
            page.activate(page.one('.entity-history-previous'))
            page.see('Record history fixture 031')
            reads = [e for e in page.events()[start:] if e['path'].endswith('/history')]
            assert all(e['status'] == 200 for e in reads)
            assert [parse_qs(e['query']) for e in reads] == [
                {'limit': ['26'], 'offset': [str(offset)]} for offset in [*range(0, 251, 25), 225]
            ]
            close()
        with page.check('audit empty search, read errors, abandoned responses and restoration'):
            page.drawer('audit_trail');loaded()
            page.fill(correlation(),'77777777-7777-4777-8777-777777777777');page.click(apply())
            page.see(page.t('webui.render_event_timeline.label.no_matching_events_bd2c227e'));capture('empty')
            page.control(path='/api/v1/event-history/search', method='POST',status=503)
            page.click(apply());page.see(page.t('common.error.service_unavailable'))
            page.control();page.click(page.t('audit.filter.clear'));loaded()
            page.control(path='/api/v1/event-history/filter-options',hold=True)
            start=len(page.events('requests-started.jsonl'))
            page.drawer('audit_trail')
            page.wait.until(lambda _:any(e['controlled'] for e in page.events('requests-started.jsonl')[start:]))
            page.drawer('dashboard');page.one('.dashboard-overview-primary')
            start=len(page.events());page.control()
            page.wait.until(lambda _:any(e['controlled'] for e in page.events()[start:]))
            assert not page.visible('.audit-event')
            history=page.driver.execute_script('return history.length');url=page.driver.current_url
            page.drawer('audit_trail');loaded();page.reload();loaded()
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('message-monitor scoped audit link and Settings audit link'):
            page.activate(page.one('button.erms-nav-link', page.t('messaging.monitor.title')))
            start=len(page.events())
            page.click(page.t('messaging.monitor.audit'))
            def search_finished(since):
                return (any(e['method']=='POST' and e['path']=='/api/v1/event-history/search'
                            and e['status']==200 for e in page.events()[since:])
                        and not page.button(apply()).get_attribute('disabled'))
            page.wait.until(lambda _:search_finished(start))
            def scoped_type():
                # Quasar renders the selected label beside the search input.
                return 'System Notification' in page.driver.execute_script(
                    "return arguments[0].closest('.q-field').innerText",
                    page.field(key('select.entity_type_3b68096e')))
            page.wait.until(lambda _:scoped_type())
            start=len(page.events())
            page.click(page.t('audit.filter.clear'))
            page.wait.until(lambda _:search_finished(start))
            assert scoped_type()
            page.drawer('audit_trail');loaded()
            page.field(key('select.entity_type_3b68096e')).click()
            page.one('[role=option]',page.t('audit.entity.application_setting')).click()
            replace_results(lambda:page.click(apply()))
            label=page.t('webui.render_event_timeline.tooltip.open_current_entity_208e2a65')
            page.wait.until(lambda _: [b for b in page.visible('button[aria-label]') if b.get_attribute('aria-label')==label])[0].click()
            page.wait.until(lambda _:len(page.driver.find_elements('css selector','[role=tab]'))==7)
    with page.check('restricted identity has no audit administration and server denies audit search'):
        page.sign_out();page.login('viewer@test.invalid')
        assert not [b for b in page.visible('button.erms-nav-link') if page.t('navigation.item.audit_trail') in b.text]
        from tools.check_webui_browser import PASSWORD
        page.api.post('/api/v1/auth/logout').raise_for_status()
        page.api.post('/api/v1/auth/login',json={'email':'viewer@test.invalid','password':PASSWORD}).raise_for_status()
        page.api.headers['X-CSRF-Token']=page.api.cookies['erms_csrf']
        assert page.api.post('/api/v1/event-history/search',json={'limit':50,'offset':0}).status_code==403
    with page.check('audit browser errors and deliberate API failures'):
        page.errors()
        errors=[e for e in page.events() if e['status'] is None or e['status']>=400]
        assert all((e['controlled'] and e['status']==503) or (e['method']=='POST' and e['path']=='/api/v1/event-history/search' and e['status']==403) for e in errors),errors
