"""Aggregation browse/detail/editor parity against bounded real API fixtures."""
import re
import time
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from tools.check_webui_browser import plain
from tools.webui_browser_shell import record_resize_notifications, viewport


def check_aggregations(page):
    response=page.api.post('/api/v1/aggregations/search',json={'where':{'field':'aggregation_number','operator':'eq','value':'TEST-AGG'},'limit':1,'offset':0});response.raise_for_status();root=response.json()['items'][0]
    rule_instructions = ('تُنظَّم الملفات والوثائق حسب السنة، وتُنقل إلى مخزن الوثائق عند انتهاء مدة الحفظ الجارية. ' * 4).strip()
    reason = 'Verify retention wrapping with long instructions'
    rule = page.api.put(f'/api/v1/aggregations/{root["id"]}/retention-rule', headers={'X-Change-Reason': reason}, json={
        'current_period_years': 2, 'intermediate_period_years': 10,
        'final_disposition': 'selective_preservation', 'instructions': rule_instructions,
        'justification': reason,
    })
    rule.raise_for_status()
    leaf_title = 'ملف المعاملات الإدارية الطويلة لاختبار العرض — ' + 'Long title ' * 12
    leaf = page.api.post('/api/v1/aggregations', json={
        'aggregation_number': 'LAYOUT-LEAF', 'title': leaf_title.strip(),
        'classification_id': root['classification_id'], 'medium': 'physical',
        'date_opened': '2026-01-01T00:00:00Z',
    })
    leaf.raise_for_status()
    page.api.post('/api/v1/records', json={
        'aggregation_id': leaf.json()['id'], 'record_number': 'LAYOUT-REC',
        'title': 'One record in this aggregation', 'medium': 'physical',
        'date_originated': '2026-01-01T00:00:00Z',
    }).raise_for_status()
    for i in range(1,52):
        response=page.api.post('/api/v1/aggregations',json={'parent_aggregation_id':root['id'],'aggregation_number':f'AGG-{i:02}','title':f'Child fixture {i:02}','medium':'physical','date_opened':'2026-01-01T00:00:00Z'});response.raise_for_status()
    for i in range(1,28):
        response=page.api.post('/api/v1/records',json={'aggregation_id':root['id'],'record_number':f'REC-{i:02}','title':f'Record fixture {i:02}','medium':'physical','date_originated':'2026-01-01T00:00:00Z'});response.raise_for_status()
        if i == 1:
            first_record = response.json()
    def click(key,scope=None):page.click(page.t(key),scope)
    def dialog():
        return page.wait.until(lambda _: (page.visible('.q-dialog__inner > .q-card') or [False])[-1])
    def open_details():
        if not page.visible('.q-dialog__inner > .q-card'):
            click('resource_details.details',page.one('.resource-detail-header'))
        page.button(page.t('webui.open_aggregation.button.edit_metadata_3ee4d255'),dialog())
        return dialog()
    def aggregation_close_action():
        return page.wait.until(lambda _:next((button for button in page.visible('button',dialog())
            if any(icon.text=='lock' for icon in button.find_elements('css selector','.q-icon'))),False))
    def close_details():
        page.activate(dialog().find_element('css selector','button'))
        closed()
    def closed():page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
    def capture(name,target=None):page.capture('aggregations-'+name+'-'+page.language,target=target)
    def record_rows():return page.visible('.compact-result-item')
    def child_rows():return page.visible('.aggregation-child-preview')
    def check_status_tooltip(button, expected):
        assert expected in plain(button.get_attribute('aria-description'))
        ActionChains(page.driver).move_to_element(button).perform()
        page.wait.until(lambda _:any(expected in plain(tooltip.text) for tooltip in page.visible('.q-tooltip')))

    def assert_layout():
        result = page.driver.execute_script('''
          const card = document.querySelector('.q-dialog__inner > .q-card');
          const detail = card.querySelector('.resource-retention-details');
          const b = card.getBoundingClientRect();
          return detail && [...detail.querySelectorAll('div')].every(e => {
            const r = e.getBoundingClientRect();
            return r.left >= b.left - 1 && r.right <= b.right + 1 && e.scrollWidth <= e.clientWidth + 1;
          });
        ''')
        assert result
    def expand_rule_details():
        page.activate(page.one('.q-expansion-item .q-item__label',page.t('resource_details.rule_details'),scope=dialog()))
        instructions = page.one('.retention-rule-instructions',scope=dialog())
        assert page.t('entity_metadata.field.retention_disposal_instructions') in plain(instructions.text)
        page.see(rule_instructions)
        assert_layout()
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
        page.wait.until(lambda _:len(child_rows()) in (10,1) and len(record_rows())==25)
    def check_phone_layout():
        with page.check('single-record layout fits a phone-sized viewport'):
            page.drawer('aggregations')
            if page.visible('#aggregation-browser-tree'):
                click('webui.index.button.search_4d02b714',page.one('.erms-shared-control.items-center'))
            personal_ready()
            page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'),'LAYOUT-LEAF')
            click('webui.index.button.search_4d02b714',page.one('.erms-shared-control.items-end'))
            page.activate(page.one('button[aria-label="Open aggregation"]',scope=page.one('.compact-result-item')))
            page.wait.until(lambda _:len(record_rows())==1)
            page.see(page.t('webui.open_aggregation.label.no_child_aggregations_7e6e2073'))
            originated = '1 يناير 2026' if page.language == 'ar' else '1 Jan 2026'
            expected = page.t('resource_details.contained_record_originated').format(date=originated)
            assert plain(page.one('.contained-record-metadata', scope=record_rows()[0]).text) == expected
            medium = page.one('.contained-record-medium', scope=record_rows()[0])
            medium_name = page.t('advanced_search.value.physical')
            assert plain(medium.get_attribute('aria-label')) == medium_name
            ActionChains(page.driver).move_to_element(page.one('.q-icon', 'inventory_2', scope=medium)).perform()
            page.wait.until(lambda _: any(plain(tip.text) == medium_name for tip in page.visible('.q-tooltip')))
            if page.args.browser not in {'chrome','edge'}:
                return
            page.driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride',
                                        {'width':390,'height':820,'deviceScaleFactor':1,'mobile':False})
            try:
                # The drawer's overlay mode settles after the viewport width changes.
                page.wait.until(lambda _:page.driver.execute_script('''return innerWidth === 390 &&
                    document.querySelector('.resource-detail-header').clientWidth > 280'''))
                overflows = page.driver.execute_script('''return [...document.querySelectorAll('.resource-contents-section, .resource-detail-header')]
                    .filter(e => e.scrollWidth > e.clientWidth + 1).map(e => ({className:e.className, width:e.clientWidth, scroll:e.scrollWidth,
                    children:[...e.children].map(c=>[c.className,c.clientWidth,c.scrollWidth])}))''')
                if overflows:
                    capture('phone-overflow')
                assert not overflows, overflows
                assert page.driver.execute_script('''const row=document.querySelector('.compact-result-row');
                    return row.querySelector('.compact-result-actions').getBoundingClientRect().top >=
                           row.querySelector('.compact-result-identity').getBoundingClientRect().bottom;''')
                capture('single-record-phone')
                open_details()
                assert page.driver.execute_script('''const e=arguments[0], a=e.querySelector('.resource-metadata-actions');
                    const facts=e.querySelector('.resource-metadata-facts').getBoundingClientRect();
                    return e.scrollWidth <= e.clientWidth + 1 && getComputedStyle(a).flexDirection === 'column'
                        && a.getBoundingClientRect().top >= facts.bottom;''',dialog())
                capture('metadata-phone')
                page.activate(page.one('[role="tab"]',page.t('resource_details.retention_rule'),scope=dialog()))
                page.activate(page.one('.q-expansion-item .q-item__label',page.t('resource_details.rule_details'),scope=dialog()))
                page.one('.resource-retention-details')
                assert_layout()
                capture('retention-phone')
                close_details()
            finally:
                page.driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
                record_resize_notifications(page)

    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        check_phone_layout()
        with page.check('aggregation search, detail and bounded child/record paging'):
            start=len(page.events());enter_detail();capture('detail')
            started=page.events()[start:]
            assert not any(re.fullmatch(r'/api/v1/records/\d+/capabilities',e['path']) for e in started)
            assert not any(e['path'].endswith('/effective-retention-rule') or '/relationships/aggregation/' in e['path'] for e in started)
            start=len(page.events())
            # Two independent server pagers: child aggregations then contained records.
            page_number(page.visible('.q-pagination')[0],6);page.wait.until(lambda _:len(child_rows())==1);assert not any(e['path']=='/api/v1/records/search' for e in page.events()[start:]);capture('children-last',page.one('.aggregation-child-preview-grid'))
            page_number(page.visible('.q-pagination')[1],2);page.wait.until(lambda _:len(record_rows())==3);capture('records-last',page.one('.compact-result-list'))
            first=record_rows()[0];page.one('button[aria-label="Open record"]',scope=first).click()
            page.see(page.t('webui.render_component_section.label.this_is_a_physical_record_5a1bd071'))
            page.one('button.resource-detail-parent').click();page.wait.until(lambda _:len(record_rows())==3 and len(child_rows())==1)
            page.wait.until(lambda _:page.driver.switch_to.active_element.get_attribute('aria-label')=='Open record')
            capture('record-return',page.one('.compact-result-list'))
            filter_records('no-record-match')
            field=expect_empty_filter('no-record-match');capture('record-empty',field)
            filter_records('REC-11')
            page.wait.until(lambda _:len(record_rows())==1 and 'REC-11' in record_rows()[0].text)
            assert len(child_rows())==1 and len(page.visible('.q-pagination'))==1
            capture('record-filter-recovered',page.one('.compact-result-list'))
            page.activate(page.one('button[aria-label="Open record"]',scope=record_rows()[0]))
            page.see(page.t('webui.render_component_section.label.this_is_a_physical_record_5a1bd071'))
            page.activate(page.one('button.resource-detail-parent'))
            page.wait.until(lambda _:len(record_rows())==1 and 'REC-11' in record_rows()[0].text)
            assert page.field(page.t('webui.open_aggregation.input.filter_records_d5ad0981')).get_attribute('value')=='REC-11'
            filter_records('another-no-match');expect_empty_filter('another-no-match')
            filter_records('')
            page.wait.until(lambda _:len(record_rows())==25 and len(page.visible('.q-pagination'))==2)
            assert len(child_rows())==1
            assert page.field(page.t('webui.open_aggregation.input.filter_records_d5ad0981')).get_attribute('value')==''
            capture('record-filter-cleared',page.one('.compact-result-list'))
            page_number(page.visible('.q-pagination')[1],2);page.wait.until(lambda _:len(record_rows())==3)
            page.report.setdefault('empty_filter_recovery',[]).append({'language':language,
                'filter_retained':True,'changed_query_recovers':True,'filtered_record_return':True,
                'second_empty_query':True,'clear_recovers_without_reload':True,
                'record_paging_restored':True,'child_page_preserved':True})
            page.driver.refresh();page.wait.until(lambda _:len(record_rows())==25 and len(child_rows())==10)
        with page.check('contained-record paging and return preserve the submitted filter and pending draft'):
            filter_records('Record fixture')
            page.one('.resource-contents-section .q-badge', '27')
            page.fill(record_filter_label(),'REC-27')
            time.sleep(.4)
            page_number(page.visible('.q-pagination')[1],2)
            def second_page():
                rows=record_rows()
                return len(rows)==2 and 'REC-26' in rows[0].text and 'REC-27' in rows[1].text
            page.wait.until(lambda _:second_page())
            assert page.field(record_filter_label()).get_attribute('value')=='REC-27'
            capture('records-pending-filter',page.one('.compact-result-list'))
            page.activate(page.one('button[aria-label="Open record"]',scope=record_rows()[1]))
            page.see(page.t('webui.render_component_section.label.this_is_a_physical_record_5a1bd071'))
            page.activate(page.one('button.resource-detail-parent'))
            page.wait.until(lambda _:second_page())
            assert page.field(record_filter_label()).get_attribute('value')=='REC-27'
            submit_record_filter()
            page.wait.until(lambda _:len(record_rows())==1 and 'REC-27' in record_rows()[0].text)
            assert len(page.visible('.q-pagination'))==1
            filter_records('')
            page.wait.until(lambda _:len(record_rows())==25 and len(page.visible('.q-pagination'))==2)
        with page.check('status summaries and lazy Details tabs'):
            assert all(page.t('disposition.ui.status_1') not in row.text for row in record_rows())
            assert all(page.visible('.contained-record-metadata', row) for row in record_rows())
            for key, expected in (
                ('webui.open_aggregation.button.vital_status_69064d77', 'resource_details.not_marked_vital'),
                ('resource_details.closure', 'webui.open_aggregation.badge.open_88407b0f'),
                ('navigation.item.holds', 'resource_details.no_active_holds'),
            ):
                icon=page.one(f'.resource-detail-header button[aria-label="{page.t(key)}"]')
                check_status_tooltip(icon, page.t(expected))
                page.activate(icon)
                page.wait.until(lambda _:any(page.t(expected) in menu.text for menu in page.visible('.resource-status-summary')))
                ActionChains(page.driver).send_keys(Keys.ESCAPE).perform()
                page.wait.until(lambda _:not page.visible('.resource-status-summary'))
                page.wait.until(lambda _:page.driver.switch_to.active_element==icon)
            open_details()
            tabs=page.visible('[role="tab"]',dialog())
            assert len(tabs)==4
            start=len(page.events())
            page.activate(tabs[1]);page.wait.until(lambda _:page.visible('.aggregation-retention-compact'))
            assert sum(e['path'].endswith('/effective-retention-rule') for e in page.events()[start:])==1
            expand_rule_details();capture('retention')
            page.activate(tabs[2]);page.wait.until(lambda _:any('/relationships/aggregation/' in e['path'] for e in page.events()[start:]))
            close_details()
        with page.check('failed and abandoned status reads'):
            holds_path = f'/api/v1/aggregations/{root["id"]}/effective-holds'
            icon = page.one(f'.resource-detail-header button[aria-label="{page.t("navigation.item.holds")}"]')
            try:
                page.control(path=holds_path, status=503)
                page.activate(icon)
                page.see(page.t('resource_details.unavailable'))
                assert page.t('resource_details.no_active_holds') not in page.one('.resource-status-summary').text
                ActionChains(page.driver).send_keys(Keys.ESCAPE).perform()
                page.wait.until(lambda _:not page.visible('.resource-status-summary'))
                page.control(path=holds_path, hold=True)
                started=len(page.events('requests-started.jsonl'))
                page.activate(icon)
                page.wait.until(lambda _:any(e['path']==holds_path and e['controlled'] for e in page.events('requests-started.jsonl')[started:]))
                page.drawer('dashboard');page.one('.dashboard-overview-primary')
            finally:
                completed=len(page.events());page.control()
            page.wait.until(lambda _:any(e['path']==holds_path and e['controlled'] for e in page.events()[completed:]))
            assert not page.visible('.resource-detail-header') and not page.visible('.resource-status-summary')
            enter_detail()
        with page.check('narrow aggregation and record detail dialogs'):
            width,height=page.driver.execute_script('return [innerWidth,innerHeight]')
            try:
                viewport(page, 600, 844)
                open_details()
                assert page.driver.execute_script('return arguments[0].getBoundingClientRect().width <= innerWidth',dialog())
                capture('narrow')
                page.activate(page.one('[role="tab"]',page.t('resource_details.retention_rule'),scope=dialog()))
                expand_rule_details();capture('retention-narrow')
                close_details()
                icon=page.one(f'.resource-detail-header button[aria-label="{page.t("navigation.item.holds")}"]')
                page.activate(icon)
                summary=page.one('.resource-status-summary')
                assert page.driver.execute_script('const r=arguments[0].getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth',summary)
                click('webui.open_aggregation.button.view_holds_b4a3f017',summary)
                page.wait.until(lambda _: page.t('resource_details.no_active_holds') in dialog().text)
                close_details()
                page.wait.until(lambda _:page.driver.switch_to.active_element==icon)
                page.activate(page.one('button[aria-label="Open record"]',scope=record_rows()[0]))
                page.see(page.t('webui.render_component_section.label.this_is_a_physical_record_5a1bd071'))
                click('resource_details.details',page.one('.resource-detail-header'))
                page.wait.until(lambda _:len(page.visible('[role="tab"]',dialog()))==3)
                assert page.driver.execute_script('return arguments[0].getBoundingClientRect().width <= innerWidth',dialog())
                capture('record-narrow')
                close_details()
                page.activate(page.one('button.resource-detail-parent'))
                page.wait.until(lambda _:len(record_rows())==25)
            finally:
                viewport(page, width, height)
                record_resize_notifications(page)
        with page.check('hold summary limits names and reflects changes'):
            owner=page.api.get('/api/v1/auth/me').json()['user']['id']
            record_path=f'/api/v1/records/{first_record["id"]}'
            assignments=[]
            reason={'X-Change-Reason':'Verify the hold summary'}
            try:
                for i in range(4):
                    hold=page.api.post('/api/v1/holds',json=dict(code=f'SUM-{language}-{i}',name=f'Summary hold {i}',valid_from='2020-01-01T00:00:00Z',owner_user_id=owner,contributor_user_ids=[],preserve_resource_state=False))
                    hold.raise_for_status();hold_id=hold.json()['id']
                    page.api.post(record_path+'/holds',json={'hold_id':hold_id},headers=reason).raise_for_status()
                    assignments.append(hold_id)
                effective=page.api.get(record_path+'/effective-holds').json()
                assert len(effective)==4
                page.activate(page.one('button[aria-label="Open record"]',scope=record_rows()[0]))
                page.see(page.t('webui.render_component_section.label.this_is_a_physical_record_5a1bd071'))
                icon=page.one(f'.resource-detail-header button[aria-label="{page.t("navigation.item.holds")}"]')
                held = page.t('webui.open_aggregation.label.protected_by_hold_count_effective_value_065566e7').format(hold_count=len(effective))
                check_status_tooltip(icon, held)
                icon.send_keys(Keys.ENTER)
                page.wait.until(lambda _: all(hold['name'] in page.one('.resource-status-summary').text for hold in effective[:3]))
                summary=page.one('.resource-status-summary').text
                assert '…' in summary and effective[3]['name'] not in summary
                ActionChains(page.driver).send_keys(Keys.ESCAPE).perform()
                page.wait.until(lambda _:not page.visible('.resource-status-summary'))
            finally:
                for hold_id in assignments:
                    page.api.delete(f'{record_path}/holds/{hold_id}',headers=reason).raise_for_status()
            page.activate(icon);page.see(page.t('resource_details.no_active_holds'))
            page.wait.until(lambda _:icon.get_attribute('aria-description')==page.t('resource_details.no_active_holds'))
            ActionChains(page.driver).send_keys(Keys.ESCAPE).perform()
            page.activate(page.one('button.resource-detail-parent'))
            page.wait.until(lambda _:len(record_rows())==25)
        with page.check('aggregation metadata keyboard focus and unchanged action dialogs'):
            open_details();click('webui.open_aggregation.button.edit_metadata_3ee4d255');page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card'))==2);d=dialog()
            title=page.field(page.t('entity_metadata.field.title')+' *');page.activate(title);title.send_keys(Keys.TAB)
            assert page.driver.switch_to.active_element==page.field(page.t('entity_metadata.field.description'))
            page.report.setdefault('focus',[]).append({'language':language,'from':'title','to':'description'})
            capture('editor')
            click('webui.open_editor.button.cancel_c07bff03',d);page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card'))==1)
            page.activate(page.one('.resource-advanced-actions .q-item__label',scope=dialog()))
            for key,name in [('webui.open_aggregation.button.location_5c67a431','location'),('webui.open_aggregation.button.vital_status_69064d77','vital'),('webui.open_aggregation.button.next_review_699d407b','review')]:
                click(key,dialog());page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card'))==2);capture(name);ActionChains(page.driver).send_keys(Keys.ESCAPE).perform();page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card'))==1)
        with page.check('active aggregation close/reopen refresh and restored detail'):
            open_details()
            before=page.api.get(f'/api/v1/aggregations/{root["id"]}');before.raise_for_status()
            assert before.json()['date_closed'] is None
            page.activate(aggregation_close_action())
            page.see(page.t('webui.open_aggregation.label.closed_directly_77d7dcfc'))
            closed_row=page.api.get(f'/api/v1/aggregations/{root["id"]}');closed_row.raise_for_status()
            assert closed_row.json()['date_closed'] is not None
            capture('closed')
            close_details()
            icon=page.one(f'.resource-detail-header button[aria-label="{page.t("resource_details.closure")}"]')
            check_status_tooltip(icon, page.t('webui.open_aggregation.label.closed_directly_77d7dcfc'))
            page.activate(icon)
            direct=page.t('webui.open_aggregation.label.closed_directly_77d7dcfc')
            page.wait.until(lambda _:any(direct in menu.text for menu in page.visible('.resource-status-summary')))
            ActionChains(page.driver).send_keys(Keys.ESCAPE).perform()
            page.wait.until(lambda _:not page.visible('.resource-status-summary'))
            page.activate(page.one('button[aria-label="Open record"]',scope=record_rows()[0]))
            page.see(page.t('webui.render_component_section.label.digital_components_are_read_only_15f586a5'))
            icon=page.one(f'.resource-detail-header button[aria-label="{page.t("resource_details.closure")}"]')
            check_status_tooltip(icon, page.t('resource_details.closed_by_aggregation'))
            page.activate(icon)
            page.wait.until(lambda _:any(
                root['aggregation_number'] in menu.text and page.t('resource_details.closed_by_aggregation') in menu.text
                for menu in page.visible('.resource-status-summary')
            ))
            ActionChains(page.driver).send_keys(Keys.ESCAPE).perform()
            page.wait.until(lambda _:not page.visible('.resource-status-summary'))
            page.activate(page.one('button.resource-detail-parent'))
            page.wait.until(lambda _:len(record_rows())==25)
            click('resource_details.details',page.one('.resource-detail-header'))
            click('webui.open_aggregation.button.reopen_96cb2ac2');page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card'))==2)
            page.fill(page.t('webui.show_reopen_aggregation.textarea.reason_for_reopening_08c23aed'),
                      'Verify existing reopen refresh')
            click('webui.show_reopen_aggregation.button.reopen_3a12b38d',dialog())
            aggregation_close_action()
            after=page.api.get(f'/api/v1/aggregations/{root["id"]}');after.raise_for_status()
            assert after.json()['date_closed'] is None
            assert after.json()['version'] > closed_row.json()['version'] > before.json()['version']
            assert after.json()['title']==before.json()['title']
            capture('reopened')
            close_details()
            page.reload();page.see(page.t('webui.open_aggregation.label.child_aggregations_cd3bce3a'))
            page.wait.until(lambda _:len(record_rows())==25 and len(child_rows())==10)
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
            assert page.field(record_filter_label()).is_enabled()
            url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            page.drawer('aggregations');page.see('Child fixture 51');page.one('#aggregation-browser-tree');capture('tree-return')
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
            page.errors()
    assert not [event for event in page.events() if not event['controlled'] and (event['status'] is None or event['status']>=400)]
