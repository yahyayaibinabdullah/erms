"""Aggregation browse/detail/editor parity against bounded real API fixtures."""
import time
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains


def check_aggregations(page):
    response=page.api.post('/api/v1/aggregations/search',json={'where':{'field':'aggregation_number','operator':'eq','value':'TEST-AGG'},'limit':1,'offset':0});response.raise_for_status();root=response.json()['items'][0]
    for i in range(1,52):
        response=page.api.post('/api/v1/aggregations',json={'parent_aggregation_id':root['id'],'aggregation_number':f'AGG-{i:02}','title':f'Child fixture {i:02}','medium':'physical','date_opened':'2026-01-01T00:00:00Z'});response.raise_for_status()
    for i in range(1,13):
        response=page.api.post('/api/v1/records',json={'aggregation_id':root['id'],'record_number':f'REC-{i:02}','title':f'Record fixture {i:02}','medium':'physical','date_originated':'2026-01-01T00:00:00Z'});response.raise_for_status()
    def click(key,scope=None):page.click(page.t(key),scope)
    def dialog():return page.one('.q-dialog__inner > .q-card')
    def closed():page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
    def capture(name,target=None):page.capture('aggregations-'+name+'-'+page.language,target=target)
    def record_rows():return page.visible('.compact-result-item')
    def child_rows():return page.visible('.aggregation-child-preview')
    def record_filter_label():
        return page.t('webui.open_aggregation.input.filter_records_d5ad0981')
    def submit_record_filter():
        field=page.field(record_filter_label());page.activate(field)
        time.sleep(.4)  # Existing input debounce before the Enter-triggered request.
        field.send_keys(Keys.ENTER)
    def filter_records(value):
        page.fill(record_filter_label(),value)
        submit_record_filter()
    def expect_empty_filter(value):
        empty=page.t('webui.render_contained_records.label.no_records_match_this_filter_1041b4b7')
        page.see(empty)
        field=page.field(page.t('webui.open_aggregation.input.filter_records_d5ad0981'))
        assert field.is_enabled() and field.get_attribute('value')==value
        assert not record_rows() and len(page.visible('.q-pagination'))==1
        assert len(child_rows())==1
        return field
    def personal_ready():
        page.wait.until(lambda _:len(page.visible('.dashboard-personal-panel'))==2 and not page.visible('.dashboard-personal-panel .q-spinner'))
    def page_number(pager, number):
        buttons=page.visible('button',pager)
        page.report.setdefault('paging_controls',[]).append([{'text':b.text,'label':b.get_attribute('aria-label')} for b in buttons])
        page.activate(next(b for b in buttons if b.text.strip()==str(number)))
    def enter_detail():
        page.drawer('aggregations')
        # Return from the hierarchy preserves the selected mode; choose Search explicitly.
        if page.visible('#aggregation-browser-tree'):
            click('webui.index.button.search_4d02b714',page.one('.erms-shared-control.items-center'))
        personal_ready()
        page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'),'TEST-AGG')
        click('webui.index.button.search_4d02b714',page.one('.erms-shared-control.items-end'))
        page.one('button[aria-label="Open aggregation"]',scope=page.one('.compact-result-item')).click()
        page.wait.until(lambda _:len(child_rows()) in (25,1) and len(record_rows())==10)
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('aggregation search, detail and bounded child/record paging'):
            enter_detail();capture('detail')
            # Two independent server pagers: child aggregations then contained records.
            page_number(page.visible('.q-pagination')[0],3);page.wait.until(lambda _:len(child_rows())==1);capture('children-last',page.one('.aggregation-child-preview-grid'))
            page_number(page.visible('.q-pagination')[1],2);page.wait.until(lambda _:len(record_rows())==3);capture('records-last',page.one('.compact-result-list'))
            first=record_rows()[0];page.one('button[aria-label="Open record"]',scope=first).click()
            page.see(page.t('webui.render_component_section.label.this_is_a_physical_record_5a1bd071'))
            page.one('button.detail-linked-entity').click();page.wait.until(lambda _:len(record_rows())==3 and len(child_rows())==1)
            capture('record-return',page.one('.compact-result-list'))
            filter_records('no-record-match')
            field=expect_empty_filter('no-record-match');capture('record-empty',field)
            filter_records('REC-11')
            page.wait.until(lambda _:len(record_rows())==1 and 'REC-11' in record_rows()[0].text)
            assert len(child_rows())==1 and len(page.visible('.q-pagination'))==1
            capture('record-filter-recovered',page.one('.compact-result-list'))
            page.activate(page.one('button[aria-label="Open record"]',scope=record_rows()[0]))
            page.see(page.t('webui.render_component_section.label.this_is_a_physical_record_5a1bd071'))
            page.activate(page.one('button.detail-linked-entity'))
            page.wait.until(lambda _:len(record_rows())==1 and 'REC-11' in record_rows()[0].text)
            assert page.field(page.t('webui.open_aggregation.input.filter_records_d5ad0981')).get_attribute('value')=='REC-11'
            filter_records('another-no-match');expect_empty_filter('another-no-match')
            filter_records('')
            page.wait.until(lambda _:len(record_rows())==10 and len(page.visible('.q-pagination'))==2)
            assert len(child_rows())==1
            assert page.field(page.t('webui.open_aggregation.input.filter_records_d5ad0981')).get_attribute('value')==''
            capture('record-filter-cleared',page.one('.compact-result-list'))
            page_number(page.visible('.q-pagination')[1],2);page.wait.until(lambda _:len(record_rows())==3)
            page.report.setdefault('empty_filter_recovery',[]).append({'language':language,
                'filter_retained':True,'changed_query_recovers':True,'filtered_record_return':True,
                'second_empty_query':True,'clear_recovers_without_reload':True,
                'record_paging_restored':True,'child_page_preserved':True})
            page.driver.refresh();page.wait.until(lambda _:len(record_rows())==10 and len(child_rows())==25)
        with page.check('contained-record paging and return preserve the submitted filter and pending draft'):
            filter_records('Record fixture')
            page.see(page.t('webui.open_aggregation.label.record_count_records_ca93489a').format(record_count=12))
            page.fill(record_filter_label(),'REC-11')
            time.sleep(.4)
            page_number(page.visible('.q-pagination')[1],2)
            def second_page():
                rows=record_rows()
                return len(rows)==2 and 'REC-11' in rows[0].text and 'REC-12' in rows[1].text
            page.wait.until(lambda _:second_page())
            assert page.field(record_filter_label()).get_attribute('value')=='REC-11'
            capture('records-pending-filter',page.one('.compact-result-list'))
            page.activate(page.one('button[aria-label="Open record"]',scope=record_rows()[1]))
            page.see(page.t('webui.render_component_section.label.this_is_a_physical_record_5a1bd071'))
            page.activate(page.one('button.detail-linked-entity'))
            page.wait.until(lambda _:second_page())
            assert page.field(record_filter_label()).get_attribute('value')=='REC-11'
            submit_record_filter()
            page.wait.until(lambda _:len(record_rows())==1 and 'REC-11' in record_rows()[0].text)
            assert len(page.visible('.q-pagination'))==1
            filter_records('')
            page.wait.until(lambda _:len(record_rows())==10 and len(page.visible('.q-pagination'))==2)
        with page.check('aggregation metadata keyboard focus and unchanged action dialogs'):
            click('webui.open_aggregation.button.edit_metadata_3ee4d255');d=dialog()
            title=page.field(page.t('entity_metadata.field.title')+' *');page.activate(title);title.send_keys(Keys.TAB)
            assert page.driver.switch_to.active_element==page.field(page.t('entity_metadata.field.description'))
            page.report.setdefault('focus',[]).append({'language':language,'from':'title','to':'description'})
            page.activate(d.find_element('css selector','.text-xl'));capture('editor')
            click('webui.open_editor.button.cancel_c07bff03',d);closed()
            for key,name in [('webui.open_aggregation.button.location_5c67a431','location'),('webui.open_aggregation.button.vital_status_69064d77','vital'),('webui.open_aggregation.button.next_review_699d407b','review')]:
                click(key);dialog();capture(name);ActionChains(page.driver).send_keys(Keys.ESCAPE).perform();closed()
        with page.check('active aggregation close/reopen refresh and restored detail'):
            before=page.api.get(f'/api/v1/aggregations/{root["id"]}');before.raise_for_status()
            assert before.json()['date_closed'] is None
            click('webui.open_aggregation.button.close_5dfd4eee')
            page.see(page.t('webui.open_aggregation.label.closed_directly_77d7dcfc'))
            closed_row=page.api.get(f'/api/v1/aggregations/{root["id"]}');closed_row.raise_for_status()
            assert closed_row.json()['date_closed'] is not None
            capture('closed')
            click('webui.open_aggregation.button.reopen_96cb2ac2');dialog()
            page.fill(page.t('webui.show_reopen_aggregation.textarea.reason_for_reopening_08c23aed'),
                      'Verify existing reopen refresh')
            click('webui.show_reopen_aggregation.button.reopen_3a12b38d',dialog());closed()
            page.see(page.t('webui.open_aggregation.button.close_5dfd4eee'))
            after=page.api.get(f'/api/v1/aggregations/{root["id"]}');after.raise_for_status()
            assert after.json()['date_closed'] is None
            assert after.json()['version'] > closed_row.json()['version'] > before.json()['version']
            assert after.json()['title']==before.json()['title']
            capture('reopened')
            page.reload();page.see(page.t('webui.open_aggregation.button.close_5dfd4eee'))
            page.wait.until(lambda _:len(record_rows())==10 and len(child_rows())==25)
            assert not page.errors(),page.errors()
        with page.check('hierarchy expansion, branch continuation and return restoration'):
            page.drawer('aggregations');personal_ready();click('webui.index.button.browse_classification_9c15150f')
            page.one('#aggregation-browser-tree');page.wait.until(lambda _:page.visible('.aggregation-browser-tree-row'))
            terminal=page.one(f'#aggregation-browser-classification-{root["classification_id"]}')
            disclosure=terminal.find_element('css selector','button[aria-expanded]')
            if disclosure.get_attribute('aria-expanded')=='false':page.activate(disclosure)
            root_row=page.one(f'#aggregation-browser-aggregation-{root["id"]}')
            disclosure=root_row.find_element('css selector','button[aria-expanded]')
            if disclosure.get_attribute('aria-expanded')=='false':page.activate(disclosure)
            page.see('Child fixture 50')
            more=page.wait.until(lambda _:next((b for b in page.visible('button',page.one('#aggregation-browser-tree')) if any(i.text=='more_horiz' for i in b.find_elements('css selector','.q-icon')) and '50' in b.text and '51' in b.text),False))
            page.activate(more);page.see('Child fixture 51');capture('tree')
            row=next(r for r in page.visible('.aggregation-browser-tree-row') if 'Child fixture 51' in r.text)
            page.activate(row.find_element('css selector','.aggregation-browser-node-link'))
            page.see(page.t('webui.open_aggregation.label.no_child_aggregations_7e6e2073'))
            page.see(page.t('webui.open_aggregation.label.this_aggregation_does_not_contain_any_reco_4b0da9c6'))
            assert not any(page.t('webui.open_aggregation.input.filter_records_d5ad0981') in e.text for e in page.visible('.q-field'))
            url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            page.drawer('aggregations');page.see('Child fixture 51');page.one('#aggregation-browser-tree');capture('tree-return')
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
            page.errors()
    assert not [event for event in page.events() if event['status'] is None or event['status']>=400]
