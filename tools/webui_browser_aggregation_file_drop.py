"""AFD browser acceptance against the runner-owned disposable stack."""
import re
import base64
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import StaleElementReferenceException
from tools.check_webui_browser import plain


def check_aggregation_file_drop(page):
    base=page.api.post('/api/v1/aggregations/search',json={'where':{'field':'aggregation_number','operator':'eq','value':'TEST-AGG'},'limit':1}).json()['items'][0]
    created=page.api.post('/api/v1/aggregations',json={'aggregation_number':'DROP-ROOT','title':'Drop acceptance',
                           'classification_id':base['classification_id'],'medium':'mixed'})
    assert created.status_code==201,created.text
    root=created.json()
    # The second captured item has the earliest historical timestamp.
    for i in reversed(range(1,50)):
        historical_second = 1 if i == 49 else 0 if i == 48 else 49-i
        page.api.post('/api/v1/records',json={'aggregation_id':root['id'],'record_number':f'DROP-{i:02}',
                      'title':f'Existing {i:02}','medium':'digital',
                      'date_originated':f'2001-01-01T00:00:{historical_second:02}Z'}).raise_for_status()
    for i in reversed(range(1,12)):
        historical_second = 1 if i == 11 else 0 if i == 10 else 11-i
        page.api.post('/api/v1/aggregations',json={'parent_aggregation_id':root['id'],'aggregation_number':f'DROP-CHILD-{i:02}',
                      'title':f'Child {i:02}','date_opened':f'2001-01-01T00:00:{historical_second:02}Z'}).raise_for_status()

    def enter(number='DROP-ROOT'):
        page.drawer('aggregations')
        if page.visible('#aggregation-browser-tree'):
            page.click(page.t('webui.index.button.search_4d02b714'),page.one('.erms-shared-control.items-center'))
        page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'),number)
        page.click(page.t('webui.index.button.search_4d02b714'),page.one('.erms-shared-control.items-end'))
        page.activate(page.one('button[aria-label="Open aggregation"]',scope=page.one('.compact-result-item')))
        page.one('.resource-detail-header')
        page.one('.dashboard-personal-panel')
        page.wait.until(lambda _:not page.visible('.dashboard-personal-panel .q-spinner'))

    def records_section(): return page.visible('.resource-contents-section')[1]
    def entries():
        try:return page.visible('.compact-result-item',records_section())
        except StaleElementReferenceException:return []
    def drag(names,mode=None,*,title=None,cancel=None):
        page.wait.until(lambda _:not page.visible('.q-notification'))
        start=len(page.events())
        page.driver.execute_script('''
          window.dropTransfer=new DataTransfer();
          for(const name of arguments[0]) window.dropTransfer.items.add(new File(['data '+name],name,{type:'text/plain'}));
          window.dragKeepAlive=()=>document.querySelector('.resource-contents-section').dispatchEvent(new DragEvent('dragover',{bubbles:true,dataTransfer:window.dropTransfer}));
          window.dragKeepAlive();
          window.dragTimer=setInterval(window.dragKeepAlive,200);
        ''',names)
        page.wait.until(lambda _:page.visible('.record-component-drop-target'))
        if mode is None:return
        targets=page.visible('[data-drop-mode]')
        assert len(targets)==(1 if len(names)==1 else 2)
        page.driver.execute_script('''
          clearInterval(window.dragTimer);
          document.querySelector(`[data-drop-mode="${arguments[0]}"]`).dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:window.dropTransfer}));
        ''',mode)
        # Fixture normally has one effective role. Still exercise the actual
        # selector if other test setup introduces another effective role.
        page.wait.until(lambda _:page.visible('.q-dialog__inner > .q-card') or page.visible('.q-notification'))
        if page.visible('.q-dialog__inner > .q-card'):
            dialog=page.one('.q-dialog__inner > .q-card')
            assert not any(event['path'].endswith('/records/file-drop') for event in page.events()[start:])
            if mode=='combined':
                label=page.t('entity_metadata.field.title')+' *'
                field=page.field(label)
                assert field.get_attribute('value')==names[0]
                assert page.driver.execute_script('return getComputedStyle(arguments[0]).direction',field)==('rtl' if language=='ar' else 'ltr')
                pane=page.one('.aggregation-drop-files')
                assert page.driver.execute_script('return Array.from(arguments[0].querySelectorAll(".aggregation-drop-filename")).map(e=>e.textContent)',pane)==names
                if len(names)>5:
                    geometry=page.driver.execute_script('''
                        const container=arguments[0].querySelector('.q-scrollarea__container');
                        const box=container.getBoundingClientRect();
                        const rows=Array.from(arguments[0].querySelectorAll('.aggregation-drop-file'));
                        return {visible:rows.filter(e=>{const r=e.getBoundingClientRect();return r.top>=box.top && r.bottom<=box.bottom+1}).length,
                                scrollable:container.scrollHeight>container.clientHeight};
                    ''',pane)
                    assert geometry['visible']>=5 and geometry['scrollable'],geometry
                def move(index, earlier=True):
                    row=page.one(f'.aggregation-drop-file[data-file-index="{index}"]',scope=pane)
                    key='webui.render_component_cards.tooltip.move_earlier_0de89c72' if earlier else 'webui.render_component_cards.tooltip.move_later_71077211'
                    page.button(page.t(key),row).send_keys(Keys.ENTER)
                move(1)
                page.wait.until(lambda _:field.get_attribute('value')==names[1])
                page.capture('aggregation-title-confirmation-'+language+('-'+cancel if cancel else ''))
                geometry=page.driver.execute_script('''
                    const pane=arguments[0], box=pane.getBoundingClientRect();
                    const row=pane.querySelector('.aggregation-drop-file');
                    const nodes=[pane,pane.querySelector('.q-scrollarea__container'),pane.querySelector('.q-scrollarea__content'),row,...row.children];
                    return {nodes:nodes.map(e=>({classes:e.className,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,
                            direction:getComputedStyle(e).direction,flex:getComputedStyle(e).flexDirection,scrollWidth:e.scrollWidth,clientWidth:e.clientWidth})),
                            buttonsVisible:Array.from(row.querySelectorAll('button')).every(e=>{const b=e.getBoundingClientRect();return b.left>=box.left && b.right<=box.right;})};
                ''',pane)
                page.report.setdefault('file_order_geometry',[]).append({'language':language,**geometry})
                assert geometry['buttonsVisible'],geometry
                assert geometry['nodes'][3]['direction']==('rtl' if language=='ar' else 'ltr')
                assert geometry['nodes'][3]['flex']=='row'
                assert (geometry['nodes'][4]['left']>geometry['nodes'][-1]['right'])==(language=='ar')
                if cancel:
                    if cancel=='button':page.click(page.t('common.action.cancel'),dialog)
                    else:field.send_keys(Keys.ESCAPE)
                    page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
                    assert not any(event['path'].endswith('/records/file-drop') for event in page.events()[start:])
                    return
                if title is not None:
                    page.fill(label,'   ')
                    page.wait.until(lambda _:not page.button(page.t('aggregation_file_drop.create_record'),dialog).is_enabled())
                    page.fill(label,title)
                    page.wait.until(lambda _:page.button(page.t('aggregation_file_drop.create_record'),dialog).is_enabled())
                    move(1,False)
                    page.wait.until(lambda _:page.driver.execute_script('return arguments[0].querySelector(".aggregation-drop-file").dataset.fileIndex',pane)=='0')
                    assert field.get_attribute('value')==title
                    move(1)
                    page.wait.until(lambda _:page.driver.execute_script('return arguments[0].querySelector(".aggregation-drop-file").dataset.fileIndex',pane)=='1')
                    assert field.get_attribute('value')==title
                if len(names)>5:
                    move(len(names)-1)
                    page.wait.until(lambda _:page.driver.execute_script('return Array.from(arguments[0].querySelectorAll(".aggregation-drop-file")).at(-1).dataset.fileIndex',pane)==str(len(names)-2))
                    assert field.get_attribute('value')==(title or names[1])
            role_label=page.t('webui.open_record_draft_editor.select.create_for_857b2d59')
            if role_label in plain(dialog.text):
                field=page.field(page.t('webui.open_record_draft_editor.select.create_for_857b2d59'))
                page.activate(field)
                page.wait.until(lambda _:page.visible('.q-menu .q-item'))
                page.activate(page.visible('.q-menu .q-item')[0])
            page.click(page.t('aggregation_file_drop.create_records' if mode=='separate' else 'aggregation_file_drop.create_record'),page.one('.q-dialog__inner > .q-card'))
        count=len(names) if mode=='separate' else 1
        expected=page.t('aggregation_file_drop.created').format(count=count)
        page.wait.until(lambda _:any(expected in plain(n.text) for n in page.visible('.q-notification')))
        assert sum(expected in plain(n.text) for n in page.visible('.q-notification'))==1
        page.wait.until(lambda _:(title or (names[1] if mode=='combined' else names[0])) in plain(page.one('.dashboard-personal-panel').text))
        if mode=='combined':
            record=page.api.post('/api/v1/records/search',json={'where':{'field':'title','operator':'eq','value':title or names[1]},'limit':1}).json()['items'][0]
            components=page.api.post('/api/v1/digital-components/search',json={
                'where':{'field':'record_id','operator':'eq','value':record['id']},
                'sort':[{'field':'component_order','direction':'asc'}],'limit':100}).json()['items']
            expected_names=[names[1],names[0],*names[2:]]
            if len(names)>5:expected_names[-2:]=reversed(expected_names[-2:])
            assert [c['file_name'] for c in components]==expected_names
            assert [c['component_order'] for c in components]==list(range(1,len(names)+1))

    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('file drop, scoped activity and preserved paging '+language):
            start=len(page.events());enter()
            page.wait.until(lambda _:len(entries())==25)
            activity=page.one('.dashboard-personal-panel')
            left,right=page.driver.execute_script('return [arguments[0].getBoundingClientRect().left,arguments[1].getBoundingClientRect().left]',records_section(),activity)
            assert (left<right)==(language=='en')
            assert all(f'Existing {i:02}' in plain(row.text) for i,row in zip((48,49),entries()[:2]))
            assert 'Child 10' in plain(page.visible('.aggregation-child-preview')[0].text)
            requests=page.events()[start:]
            assert not any(re.fullmatch(r'/api/v1/records/\d+',e['path']) for e in requests)
            assert len([e for e in requests if e['path']=='/api/v1/auth/me/recent-activity' and str(e.get('query',{})).find('aggregation_id')>=0])<=1
            for section in page.visible('.resource-contents-section'):
                button=page.button(page.t('aggregation_file_drop.last_page'),section)
                button.send_keys(Keys.ENTER)
                page.wait.until(lambda _:not page.button(page.t('aggregation_file_drop.last_page'),section).is_enabled())
            assert 'Child 01' in plain(page.one('.aggregation-child-preview').text)
            before=len(entries())
            drag([f'single-{language}.txt'],'single')
            page.wait.until(lambda _:len(entries())==min(25,before+1))
            drag([f'separate-{language}.txt',f'attachment-{language}.txt'],'separate')
            page.wait.until(lambda _:len(entries())==min(25,before+3))
            if language=='en':
                # 49 -> 50 -> 52 records adds page 3 while page 2 remains selected.
                assert 'Existing 24' in plain(entries()[0].text)
                assert page.button(page.t('aggregation_file_drop.last_page'),records_section()).is_enabled()
            # Filtering deliberately excludes dropped names; unsubmitted text
            # must survive the upload and Last page must use submitted criteria.
            page.fill(page.t('webui.open_aggregation.input.filter_records_d5ad0981'),'Existing')
            page.click(page.t('webui.open_saved_search_dialog.button.apply_filters_63a71659'),records_section())
            page.wait.until(lambda _:len(entries())==25)
            page.fill(page.t('webui.open_aggregation.input.filter_records_d5ad0981'),'unsubmitted')
            for cancel in ('button','escape'):
                drag([f'z-cancelled-{language}.txt',f'a-cancelled-{language}.txt'],'combined',cancel=cancel)
            confirmed_title=f'Confirmed-{language}' if language=='ar' else f'a-component-{language}.txt'
            drag([f'z-combined-{language}.txt',f'a-component-{language}.txt',*[f'component-{i}-{language}.txt' for i in range(3,7)]],'combined',
                 title=confirmed_title if language=='ar' else None)
            page.wait.until(lambda _:len(entries())==25)
            assert page.field(page.t('webui.open_aggregation.input.filter_records_d5ad0981')).get_attribute('value')=='unsubmitted'
            page.button(page.t('aggregation_file_drop.last_page'),records_section()).send_keys(Keys.ENTER)
            page.wait.until(lambda _:len(entries())==24)
            start=len(page.events())
            page.click(page.t('webui.render_resource_personal_sections.button.view_all_a52a6926'),activity)
            dialog=page.one('.q-dialog__inner > .q-card')
            assert confirmed_title in plain(dialog.text)
            assert not any(re.fullmatch(r'/api/v1/records/\d+',e['path']) for e in page.events()[start:])
            page.activate(page.one('button',scope=dialog))
            page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
            page.capture('aggregation-file-drop-'+language)
            # The ordinary Add record action must refresh this same panel.
            page.click(page.t('webui.index.button.add_record_fc8125c4'),records_section())
            dialog=page.one('.q-dialog__inner > .q-card')
            page.fill(page.t('entity_metadata.field.record_number')+' *','MANUAL-'+language)
            page.fill(page.t('entity_metadata.field.title')+' *','Manual-'+language)
            page.click(page.t('webui.open_record_draft_editor.button.create_record_dd0193d6'),dialog)
            page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
            page.wait.until(lambda _:'Manual-'+language in plain(page.one('.dashboard-personal-panel').text))
        with page.check('child record and component previews refresh scoped activity '+language):
            response=page.api.post('/api/v1/records/search',json={
                'where':{'field':'record_number','operator':'eq','value':'DROP-26'},'limit':1})
            response.raise_for_status();record=response.json()['items'][0]
            image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1cAAAAASUVORK5CYII=')
            if language=='en':
                page.api.post(f"/api/v1/records/{record['id']}/digital-components/upload",
                    data={'component_order':'1'},files={'file':('preview.png',image,'image/png')}).raise_for_status()
            page.fill(page.t('webui.open_aggregation.input.filter_records_d5ad0981'),'Existing 26')
            page.click(page.t('webui.open_saved_search_dialog.button.apply_filters_63a71659'),records_section())
            page.wait.until(lambda _:len(entries())==1)
            page.fill(page.t('webui.open_aggregation.input.filter_records_d5ad0981'),'preview draft filter')
            for entry in ('record','component'):
                row=entries()[0]
                if entry=='component':
                    page.activate(page.button(page.t('webui.render_compact_resource_result.accessible_name.show_digital_components_08467816'),row))
                    page.one('.compact-result-component',scope=row)
                key=('webui.render_compact_resource_result.accessible_name.preview_digital_components_72d3f864'
                     if entry=='record' else 'webui.render_compact_resource_result.accessible_name.preview_digital_component_f8b12cac')
                start=len(page.events())
                page.activate(page.button(page.t(key),row))
                page.one('.q-dialog__inner .q-img')
                page.click(page.t('webui.select_component.accessible_name.close_viewer_7a596c99'),page.one('.component-viewer-toolbar'))
                page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
                page.wait.until(lambda _:any('Existing 26' in plain(item.text) and page.t('dashboard.activity.viewed') in plain(item.text)
                    for item in page.visible('.dashboard-personal-item',page.one('.dashboard-personal-panel'))))
                requests=page.events()[start:]
                assert sum(event['path']=='/api/v1/auth/me/recent-activity' for event in requests)==1
                assert not any(event['path']=='/api/v1/records/search' or re.fullmatch(r'/api/v1/records/\d+',event['path']) for event in requests)
                assert page.field(page.t('webui.open_aggregation.input.filter_records_d5ad0981')).get_attribute('value')=='preview draft filter'
                assert len(entries())==1
            page.capture('aggregation-preview-activity-'+language)
        with page.check('physical aggregation disables drop '+language):
            enter('TEST-AGG');drag(['physical.txt'])
            page.see(page.t('aggregation_file_drop.physical'))
            assert not page.visible('[data-drop-mode]')
            page.capture('aggregation-physical-drop-'+language)
            page.driver.execute_script("clearInterval(window.dragTimer);document.dispatchEvent(new DragEvent('dragend',{bubbles:true}))")
            page.wait.until(lambda _:not page.visible('.record-component-drop-target'))
