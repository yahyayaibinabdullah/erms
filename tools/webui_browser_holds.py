"""Legal-hold list/dialog parity with bounded synthetic fixtures."""
import time
from urllib.parse import parse_qs
from selenium.webdriver.common.keys import Keys


def check_holds(page):
    owner=page.api.get('/api/v1/auth/me').json()['user']['id']
    for i in range(27):
        response=page.api.post('/api/v1/holds',json=dict(code=f'HOLD{i:02}',name=f'Hold fixture {i:02}',valid_from='2099-01-01T00:00:00Z' if i==1 else '2020-01-01T00:00:00Z',valid_to='2021-01-01T00:00:00Z' if i==2 else None,owner_user_id=owner,contributor_user_ids=[],preserve_resource_state=False))
        response.raise_for_status()
    def icon(name,scope=None):return page.wait.until(lambda _:next((b for b in page.visible('button',scope) if any(i.text==name for i in b.find_elements('css selector','.q-icon'))),False))
    def dialog():return page.one('.q-dialog__inner > .q-card')
    def closed():page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
    def capture(name):page.capture('holds-'+name+'-'+page.language)
    def enter():page.drawer('holds');page.one('main .governance-card-list')
    def cards():return page.visible('main .governance-list-card')
    def type_query(key,value):
        field = page.field(page.t(key))
        page.select_field_text(field)
        field.send_keys(value or Keys.BACKSPACE)
        field.send_keys(Keys.TAB)
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('hold list paging, states, repeated navigation and unchanged root history'):
            enter();page.wait.until(lambda _:len(cards())==25);history=page.driver.execute_script('return history.length');url=page.driver.current_url
            page.settings();enter();page.wait.until(lambda _:len(cards())==25)
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
            capture('list');page.click(page.t('webui.select_holds.button.next_4ca23c51'));page.wait.until(lambda _:len(cards())==2);capture('last-page')
            page.click(page.t('webui.select_holds.button.first_8a70bfa4'));page.wait.until(lambda _:len(cards())==25)
            type_query('webui.select_holds.input.search_code_or_name_79d187ac','no-hold-match');page.see(page.t('webui.load.label.no_holds_are_available_47c12f52'));capture('empty')
            type_query('webui.select_holds.input.search_code_or_name_79d187ac','HOLD00');page.wait.until(lambda _:len(cards())==1)
        with page.check('create hold keyboard focus, validation and cancellation'):
            page.click(page.t('webui.select_holds.button.create_hold_c7bae8dd'));d=dialog()
            field=page.field(page.t('webui.open_hold_editor.input.code_e91b9355'));page.activate(field);field.send_keys(Keys.TAB)
            assert page.driver.switch_to.active_element==page.field(page.t('webui.open_hold_editor.input.name_fc2e95e9'))
            page.report.setdefault('focus',[]).append({'language':language,'from':'code','to':'name'})
            page.click(page.t('webui.open_hold_editor.button.save_hold_c7de035c'),d)
            page.see(page.t('webui.persist.notify.code_name_owner_and_valid_from_are_require_c60f7fcf'))
            page.activate(d.find_element('css selector','.text-xl'));capture('create')
            page.click(page.t('webui.open_hold_editor.button.cancel_9df95680'),d);closed()
        with page.check('hold details, editor, reason gate and cancellation retain state'):
            page.activate(icon('open_in_new',cards()[0]));page.one('.hold-command-overview');capture('details')
            page.click(page.t('webui.select_hold_details.button.edit_hold_d034b7c2'));d=dialog();capture('edit')
            page.click(page.t('webui.open_hold_editor.button.save_hold_c7de035c'),d)
            reason=page.wait.until(lambda _:next((c for c in page.visible('.q-dialog__inner > .q-card') if page.t('webui.hold_reason_dialog.update_title') in c.text),False))
            capture('reason');page.click(page.t('webui.hold_reason_dialog.button.cancel_c97ff9b9'),reason)
            page.wait.until(lambda _:len(page.visible('.q-dialog__inner > .q-card'))==1)
            page.click(page.t('webui.open_hold_editor.button.cancel_9df95680'),d);closed()
        with page.check('contributors and candidate filters preserve cancellation'):
            page.click(page.t('webui.select_hold_details.button.manage_contributors_866ef148'));d=dialog();capture('contributors')
            page.click(page.t('webui.manage_contributors.button.cancel_551081d0'),d);closed()
            page.click(page.t('webui.select_hold_details.button.add_held_items_4cfdf56b'));d=dialog()
            page.wait.until(lambda _:len(page.visible('.governance-list-card',d))>0);capture('candidates')
            type_query('webui.show_add_held_item.input.search_number_title_or_description_f135a521','no-resource-match')
            page.wait.until(lambda _:not page.visible('.governance-list-card',d));capture('candidate-empty')
            page.activate(icon('close',d));closed();page.errors()
        with page.check('Add to Hold pages the submitted query until Enter'):
            page.drawer('records')
            page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'),'TEST-REC')
            page.click(page.t('webui.index.button.search_4d02b714'),page.one('.erms-card'))
            page.activate(page.one('button[aria-label="Open record"]',scope=page.one('.compact-result-item')))
            page.click(page.t('webui.select_record_details.button.add_to_hold_e811b460'))
            d=dialog()
            label=page.t('webui.select_holds.input.search_code_or_name_79d187ac')
            range_text=page.t('webui.load_hold_page.text.start_end_total_42ef8de2')
            page.see(range_text.format(start=1,end=25,total=27))
            def check_read(action, *, query, offset, end, total):
                started=len(page.events())
                action()
                def reads():
                    return [e for e in page.events()[started:] if e['path']=='/api/v1/holds' and e['method']=='GET']
                page.wait.until(lambda _:bool(reads()))
                page.see(range_text.format(start=offset+1,end=end,total=total))
                result=reads()
                assert len(result)==1 and result[0]['status']==200
                params=parse_qs(result[0]['query'])
                assert params['q']==[query] and params['offset']==[str(offset)] and params['limit']==['25']
            def submit_filter():
                field=page.field(label);page.activate(field);field.send_keys(Keys.ENTER)
            query='Hold fixture'
            page.fill(label,query);time.sleep(.4)  # Existing 300 ms input debounce.
            check_read(submit_filter,query=query,offset=0,end=25,total=27)
            draft='HOLD26'
            page.fill(label,draft);time.sleep(.4)
            check_read(lambda:page.activate(icon('chevron_right',d)),query=query,offset=25,end=27,total=27)
            assert page.field(label).get_attribute('value')==draft
            capture('add-to-hold-pending-filter')
            check_read(submit_filter,query=draft,offset=0,end=1,total=1)
            assert not icon('chevron_left',d).is_enabled()
            page.click(page.t('webui.add_resource_to_hold_dialog.button.cancel_b8201f0b'),d)
            closed();page.errors()
    searches=[e for e in page.events() if e['path']=='/api/v1/holds' and e['method']=='GET']
    assert searches and all(parse_qs(e['query']).get('limit') in (['25'],['1']) for e in searches)
    writes=[e for e in page.events() if e['path'].startswith('/api/v1/holds') and e['method'] in {'POST','PATCH','PUT','DELETE'}]
    assert len(writes)==27 and all(e['method']=='POST' and e['path']=='/api/v1/holds' for e in writes)
