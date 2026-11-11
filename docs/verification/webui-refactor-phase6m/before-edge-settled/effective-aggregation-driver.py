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
            field=page.field(page.t('webui.open_aggregation.input.filter_records_d5ad0981'));page.activate(field);field.send_keys('no-record-match');time.sleep(.4);field.send_keys(Keys.ENTER)
            empty=page.t('webui.open_aggregation.label.this_aggregation_does_not_contain_any_reco_4b0da9c6')
            page.see(empty);capture('record-empty',page.one('div.text-slate-500',empty))
            # Original empty-result branch removes the filter together with its list.
            assert not any(page.t('webui.open_aggregation.input.filter_records_d5ad0981') in e.text for e in page.visible('.q-field'))
            page.report.setdefault('existing_empty_filter_behavior',[]).append({'language':language,'filter_removed_when_empty':True,'recovery':'reload restores unfiltered details'})
            page.driver.refresh();page.wait.until(lambda _:len(record_rows())==10 and len(child_rows())==25)
        with page.check('aggregation metadata keyboard focus and unchanged action dialogs'):
            click('webui.open_aggregation.button.edit_metadata_3ee4d255');d=dialog()
            title=page.field(page.t('entity_metadata.field.title')+' *');page.activate(title);title.send_keys(Keys.TAB)
            assert page.driver.switch_to.active_element==page.field(page.t('entity_metadata.field.description'))
            page.report.setdefault('focus',[]).append({'language':language,'from':'title','to':'description'})
            page.activate(d.find_element('css selector','.text-xl'));capture('editor')
            click('webui.open_editor.button.cancel_c07bff03',d);closed()
            for key,name in [('webui.open_aggregation.button.location_5c67a431','location'),('webui.open_aggregation.button.vital_status_69064d77','vital'),('webui.open_aggregation.button.next_review_699d407b','review')]:
                click(key);dialog();capture(name);ActionChains(page.driver).send_keys(Keys.ESCAPE).perform();closed()
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
            url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            page.drawer('aggregations');page.see('Child fixture 51');page.one('#aggregation-browser-tree');capture('tree-return')
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
            page.errors()
