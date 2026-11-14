"""Existing global search URLs, bounded result paging and destination restoration."""
import subprocess
import json
import time
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from tools.check_webui_browser import plain


def check_global_search(page):
    response=page.api.post('/api/v1/aggregations/search',json={'where':{'field':'aggregation_number','operator':'eq','value':'TEST-AGG'},'limit':1,'offset':0});response.raise_for_status();parent=response.json()['items'][0]
    for i in range(27):
        response=page.api.post('/api/v1/aggregations',json={'aggregation_number':f'QS-{i:02}','title':f'Quasararchive aggregation {i:02}','classification_id':parent['classification_id'],'medium':'physical','date_opened':'2026-01-01T00:00:00Z'});response.raise_for_status()
    for i in range(2):
        response=page.api.post('/api/v1/records',json={'record_number':f'QS-REC-{i:02}','title':f'Quasararchive record {i:02}','aggregation_id':parent['id'],'medium':'physical','date_originated':'2026-01-01T00:00:00Z'});response.raise_for_status()
    subprocess.run([page.args.api_python,'-c',"""
import os,psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL'];assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 c.execute("SELECT set_config('app.event_source','seeding',true)")
 c.execute("UPDATE records SET date_created='2026-01-01T00:00:00Z' WHERE record_number LIKE 'QS-REC-%'")
"""],check=True,timeout=30)
    def tab_id():
        return page.driver.execute_script('return sessionStorage.__nicegui_tab_id')
    def cached_slots():
        value = subprocess.check_output([page.args.api_python, '-c', """
import os,json,psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL'];assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 print(json.dumps(c.execute('SELECT tab_id::text,search_id::text FROM search_results_cache').fetchall()))
"""], text=True, timeout=30)
        return dict(json.loads(value))
    def search(query):
        field=page.one('header input');page.activate(field);field.send_keys(Keys.COMMAND,'a',Keys.NULL)
        for character in query:field.send_keys(character);time.sleep(.05)
        page.wait.until(lambda _:field.get_attribute('value')==query)
        count=sum(e['path']=='/api/v1/full-text-search' for e in page.events());field.send_keys(Keys.ENTER)
        page.wait.until(lambda _:sum(e['path']=='/api/v1/full-text-search' for e in page.events())>count and page.driver.current_url.endswith('/?q='+query))
        page.wait.until(lambda _:not page.visible('[role=status] .q-spinner') and (page.visible('.compact-result-item') or page.t('webui.render_global_search_results.label.no_results_found_ab1c85dc') in page.text()))
    def next_page():
        old=page.visible('.compact-result-item')[0];page.click(page.t('webui.render_global_search_results.accessible_name.next_page_c45c7218'));page.wait.until(EC.staleness_of(old));page.wait.until(lambda _:page.visible('.compact-result-item'))
    def requests():
        return sum(e['path']=='/api/v1/full-text-search' for e in page.events())
    def totals():
        for kind,count in [('all',29),('records',2),('aggregations',27)]:
            page.button(page.t(f'global_search.filter.{kind}').format(count=count))
    def capture(name):page.capture('global-'+name+'-'+page.language)
    for language in ('en','ar'):
        if language=='ar':
            page.driver.get(page.args.url+'/');page.one('.erms-breadcrumb-row [aria-current=page]')
            page.settings();page.language_change('ar')
        with page.check('global query, native focus, bounded paging and type filter'):
            history=page.driver.execute_script('return history.length');search('Quasararchive')
            assert page.driver.current_url.endswith('/?q=Quasararchive') and page.driver.execute_script('return history.length')==history
            field=page.one('header input');field.send_keys(Keys.TAB);active=page.driver.switch_to.active_element
            assert active.text=='cancel' and active.get_attribute('role')=='button';active.send_keys(Keys.TAB);active=page.driver.switch_to.active_element
            assert active.tag_name=='button' and plain(active.get_attribute('aria-label'))==page.t('webui.index.accessible_name.submit_global_search_d3d1329e')
            page.report.setdefault('focus',[]).append({'language':language,'sequence':['query','clear','submit']})
            totals()
            count=requests()
            assert len(page.visible('.compact-result-item'))==10;capture('first')
            next_page();assert len(page.visible('.compact-result-item'))==10;assert requests()==count+1;totals();capture('second')
            next_page();assert len(page.visible('.compact-result-item'))==9;assert requests()==count+2;totals();capture('third')
            previous=page.t('webui.render_global_search_results.accessible_name.previous_page_571d7f79')
            page.click(previous);page.wait.until(lambda _:len(page.visible('.compact-result-item'))==10)
            assert requests()==count+3
            page.click(page.t('global_search.filter.records').format(count=2));page.wait.until(lambda _:len(page.visible('.compact-result-item'))==2);capture('records')
            totals()
            assert not page.button(page.t('webui.render_global_search_results.accessible_name.next_page_c45c7218')).is_enabled()
            assert requests()==count+4  # The filter rechecks current access to its page.
            page.one('button[aria-label="Open record"]',scope=page.visible('.compact-result-item')[0]).click();page.one('.component-list');capture('record')
            label=page.t('webui.run_global_search.text.search_results_ecc13a7a')
            crumbs=[b for b in page.visible('button.max-w-52') if label in plain(b.text)];assert crumbs;page.activate(crumbs[-1]);page.wait.until(lambda _:len(page.visible('.compact-result-item'))==2);capture('return')
            assert requests()==count+5
            assert page.driver.current_url.endswith('/?q=Quasararchive') and page.driver.execute_script('return history.length')==history
        with page.check('existing query URL reload and empty search'):
            original_tab = tab_id()
            original_search = cached_slots()[original_tab]
            original_count = len(cached_slots())
            page.reload();page.wait.until(lambda _:len(page.visible('.compact-result-item'))==10);capture('reload')
            assert tab_id() == original_tab
            assert cached_slots()[original_tab] != original_search
            assert len(cached_slots()) == original_count
            # A new tab opened with an opener copies sessionStorage, just as a
            # duplicated tab does. NiceGUI must detect the copied open-tab marker
            # and issue a new ID rather than sharing the original cache slot.
            original_window = page.driver.current_window_handle
            page.driver.execute_script('window.open(location.href, "_blank")')
            page.wait.until(lambda _:len(page.driver.window_handles) == 2)
            duplicate = next(w for w in page.driver.window_handles if w != original_window)
            page.driver.switch_to.window(duplicate)
            page.wait.until(lambda _:len(page.visible('.compact-result-item')) == 10)
            duplicate_tab = tab_id()
            assert duplicate_tab != original_tab
            assert original_tab in cached_slots() and duplicate_tab in cached_slots()
            assert len(cached_slots()) == original_count + 1
            duplicate_search = cached_slots()[duplicate_tab]
            page.driver.close();page.driver.switch_to.window(original_window)
            search('Quasararchive')
            assert cached_slots()[duplicate_tab] == duplicate_search

            search('zz_phase6q_absent');page.see(page.t('webui.render_global_search_results.label.no_results_found_ab1c85dc'));capture('empty')
            page.reload();page.see(page.t('webui.render_global_search_results.label.no_results_found_ab1c85dc'))
            assert page.driver.current_url.endswith('/?q=zz_phase6q_absent');page.errors()
        with page.check('expired search silently rebuilds on the requested page'):
            search('Quasararchive');next_page()
            second = [plain(row.text) for row in page.visible('.compact-result-item')]
            subprocess.run([page.args.api_python,'-c',"""
import os,psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL'];assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 c.execute("UPDATE search_results_cache SET expires_at=clock_timestamp()")
"""],check=True,timeout=30)
            count=requests()
            next_page()
            assert len(page.visible('.compact-result-item'))==9 and requests()==count+2
            page.click(previous)
            page.wait.until(lambda _:len(page.visible('.compact-result-item'))==10)
            assert [plain(row.text) for row in page.visible('.compact-result-item')]==second
            assert requests()==count+3
            totals();page.errors()
        with page.check('Advanced and collection filters replace the same tab slot and old Next rebuilds'):
            active_tab = tab_id()
            global_id = cached_slots()[active_tab]
            slot_count = len(cached_slots())
            page.drawer('advanced_search');page.one('.advanced-search-page')
            page.activate(page.one('.advanced-search-target-row .q-select'))
            page.activate(page.one('.q-menu .q-item', page.t('advanced_search.resource.aggregations')))
            criterion = page.t('webui.render_condition.input.value_8dc59edc')
            page.fill(criterion, 'Quasararchive')
            page.click(page.t('webui.select_advanced_search.button.search_97989f23'), page.one('.advanced-search-submit-row'))
            page.wait.until(lambda _:len(page.visible('.compact-result-item')) == 25)
            advanced_id = cached_slots()[active_tab]
            assert advanced_id != global_id and len(cached_slots()) == slot_count
            page.drawer('aggregations')
            page.wait.until(lambda _:page.visible('.q-dialog__inner > .q-card') or page.visible('.dashboard-personal-panel'))
            if page.visible('.q-dialog__inner > .q-card'):
                page.click(page.t('webui.confirm_discard_changes.button.discard_changes_81df7dc9'))
            page.wait.until(lambda _:page.visible('.dashboard-personal-panel'))
            primary = page.t('webui.index.input.search_by_number_title_or_description_e21ed520')
            page.fill(primary, 'Quasararchive');page.field(primary).send_keys(Keys.ENTER)
            page.wait.until(lambda _:len(page.visible('.compact-result-item')) == 10)
            filter_id = cached_slots()[active_tab]
            assert filter_id != advanced_id and len(cached_slots()) == slot_count
            page.drawer('advanced_search');page.one('.advanced-search-page')
            page.wait.until(lambda _:len(page.visible('.compact-result-item')) == 25)
            # Even edited but unsubmitted controls must not alter the rebuild.
            page.fill(criterion, 'Unsubmitted absent draft')
            page.click(page.t('webui.select_advanced_search.accessible_name.next_page_d75b42e2'))
            page.wait.until(lambda _:len(page.visible('.compact-result-item')) == 2)
            assert all('Quasararchive' in plain(item.text) for item in page.visible('.compact-result-item'))
            assert cached_slots()[active_tab] not in {advanced_id, filter_id}
            assert len(cached_slots()) == slot_count
            assert page.field(criterion).get_attribute('value') == 'Unsubmitted absent draft'
            capture('cross-screen-cache');page.errors()
