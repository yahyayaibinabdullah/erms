"""Organization views, dialogs and tree on disposable browser stacks."""
import subprocess,time
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def check_organization(page):
    subprocess.run([page.args.api_python,'-c','''
import os,psycopg
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL'];assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 c.execute("SELECT set_config('app.event_source','seeding',true)")
 c.execute("UPDATE users SET date_created='2026-01-01T00:00:00Z'")
 c.execute("UPDATE org_units SET date_created='2026-01-01T00:00:00Z'")
 c.execute("UPDATE user_role_assignments SET valid_from='2026-01-01T00:00:00Z'")
'''],check=True,timeout=30)
    def capture(name):page.capture('organization-'+name+'-'+page.language)
    def dialog():return page.one('.q-dialog__inner > .q-card')
    def cancel(key):page.click(page.t(key),dialog());page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
    def icon(root,name):page.activate(next(b for b in root.find_elements('css selector','button') if any(i.text.strip()==name for i in b.find_elements('css selector','.q-icon'))))
    def query(value):
        field=page.visible('.erms-card input')[0];page.select_field_text(field)
        field.send_keys(value)
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        for resource,filter_value in (('org_units','WEBUI-TEST'),('roles','officer'),('users','viewer@test.invalid')):
            with page.check(resource+' list, detail, editor and cancellation'):
                page.drawer(resource);page.wait.until(lambda _:bool(page.visible('.governance-list-card')))
                query(filter_value);page.wait.until(lambda _:len(page.visible('.governance-list-card'))==1)
                page.activate(page.one('.governance-card-list'));capture(resource+'-list')
                page.errors()
                icon(page.one('.governance-list-card'),'open_in_new')
                page.one('.identity-command-layout')
                capture(resource+'-detail')
                # Select the command group's existing Edit button by icon.
                panel=page.one('.identity-command-actions')
                icon(panel,'edit');d=dialog()
                controls=[e for e in d.find_elements('css selector','input:not([type=checkbox]),textarea') if e.is_displayed() and e.is_enabled()]
                if controls:
                    page.activate(controls[0]);time.sleep(.5);controls[0].send_keys(Keys.TAB);time.sleep(.3)
                    focus=page.driver.switch_to.active_element
                    assert page.driver.execute_script('return arguments[0].contains(arguments[1])',d,focus)
                    page.report.setdefault('organization_focus',[]).append({'language':language,'resource':resource,'tag':focus.tag_name,'type':focus.get_attribute('type'),'label':focus.get_attribute('aria-label')})
                page.activate(d.find_element('css selector','.text-xl'));capture(resource+'-editor')
                cancel('webui.open_editor.button.cancel_c07bff03')
                if resource in {'roles','users'}:
                    icon(panel,'group');page.one('.membership-dialog')
                    capture(resource+'-memberships')
                    cancel('webui.show_memberships.button.close_4c7a508f')
                page.errors()
        with page.check('organization tree, repeated navigation and saved expansion'):
            page.drawer('organization_browser');page.one('#organization-browser-tree')
            disclosure=page.one('button.organization-browser-disclosure[aria-label*="WEBUI-TEST"]')
            if disclosure.get_attribute('aria-expanded')!='true':page.activate(disclosure)
            page.see('Test officer');capture('tree-expanded')
            url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            page.settings();page.drawer('organization_browser');page.see('Test officer')
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
            page.errors()
    check_membership_paging(page)
    check_organization_search_paging(page)
    with page.check('cancelled editors have no entity writes'):
        assert not [e for e in page.events() if e['method'] in {'POST','PUT','PATCH','DELETE'} and e['path'].startswith(('/api/v1/org-units','/api/v1/roles','/api/v1/users')) and '/search' not in e['path']]


def check_organization_search_paging(page):
    from urllib.parse import parse_qs

    subprocess.run([page.args.api_python, '-c', '''
import psycopg
from tools.seed_webui_regression import disposable_url

with psycopg.connect(disposable_url()) as connection:
    connection.execute("SELECT set_config('app.event_source','seeding',true)")
    connection.execute("""
        INSERT INTO org_units(code,name,translations)
        SELECT 'ORG-PAGE-U-' || n, 'Organization page fixture unit ' || n,
               jsonb_build_object('ar', jsonb_build_object('name','اختبار صفحات الهيكل وحدة ' || n))
          FROM generate_series(100,125) n
    """)
    connection.execute("""
        INSERT INTO roles(code,name,org_unit_id,translations)
        SELECT 'ORG-PAGE-R-' || n, 'Organization page fixture role ' || n, unit.id,
               jsonb_build_object('ar', jsonb_build_object('name','اختبار صفحات الهيكل دور ' || n))
          FROM generate_series(100,125) n CROSS JOIN org_units unit
         WHERE unit.code='WEBUI-TEST'
    """)
    connection.execute("""
        INSERT INTO users(name,email,translations)
        VALUES ('Organization page fixture person', 'org-page-user@test.invalid',
                '{"ar":{"name":"اختبار صفحات الهيكل مستخدم"}}')
    """)
'''], check=True, timeout=30)

    for language, term in (('en', 'Organization page fixture'), ('ar', 'اختبار صفحات الهيكل')):
        if page.language != language:
            page.settings()
            page.language_change(language)
        with page.check('organization search reaches mixed matches beyond 50'):
            page.drawer('organization_browser')
            page.one('#organization-browser-tree')
            field = page.field(page.t('webui.show_organization_structure.input.search_organization_structure_b22c915b'))
            page.select_field_text(field)
            field.send_keys(term)
            start = len(page.events())
            field.send_keys(Keys.ENTER)

            def expect(offset, first, last, count):
                def matches(_):
                    items = page.visible('.organization-search-results button')
                    return len(items) == count and first in items[0].text and last in items[-1].text
                page.wait.until(matches, f'Unexpected organization matches at offset {offset}')

            expect(0, 'ORG-PAGE-U-100', 'ORG-PAGE-U-124', 25)
            assert not page.one('.organization-search-previous').is_enabled()
            page.select_field_text(field)
            field.send_keys('unsubmitted draft')
            page.activate(page.one('.organization-search-next'))
            expect(25, 'ORG-PAGE-U-125', 'ORG-PAGE-R-123', 25)
            page.activate(page.one('.organization-search-next'))
            expect(50, 'ORG-PAGE-R-124', 'org-page-user@test.invalid', 3)
            assert not page.one('.organization-search-next').is_enabled()
            page.capture(f'organization-search-past-50-{language}')
            page.activate(page.one('.organization-search-previous'))
            expect(25, 'ORG-PAGE-U-125', 'ORG-PAGE-R-123', 25)
            assert field.get_attribute('value') == 'unsubmitted draft'

            requests = [e for e in page.events()[start:] if '/browse/organization/' in e['path']]
            assert all(e['path'].endswith('/organization/search') and e['status'] == 200 for e in requests)
            assert [parse_qs(e['query']) for e in requests] == [
                {'query': [term], 'entity_type': ['all'], 'status': ['all'],
                 'limit': ['26'], 'offset': [str(offset)]}
                for offset in (0, 25, 50, 25)
            ]

            field.send_keys(Keys.ENTER)
            page.see(page.t('webui.run_search.label.no_matching_organization_units_roles_or_us_29cce504'))
            assert not page.visible('.organization-search-pager')
            page.errors()


def check_membership_paging(page):
    """Exercise both assignment directions through the real filtered APIs."""
    from urllib.parse import parse_qs
    from selenium.common.exceptions import ElementNotInteractableException

    result = subprocess.run([page.args.api_python, '-c', '''
import json
import psycopg
from psycopg.types.json import Jsonb
from tools.seed_webui_regression import disposable_url

with psycopg.connect(disposable_url()) as c:
    c.execute("SELECT set_config('app.event_source','seeding',true)")
    viewer = c.execute("SELECT id FROM users WHERE email='viewer@test.invalid'").fetchone()[0]
    unit = c.execute("SELECT id FROM org_units WHERE code='WEBUI-TEST'").fetchone()[0]
    anchor = c.execute(
        "INSERT INTO roles(code,name,org_unit_id) VALUES('MEMBERSHIP-FIXTURE','Membership paging fixture',%s) RETURNING id",
        (unit,),
    ).fetchone()[0]
    for i in range(55):
        en = 'Earlier assignment' if i < 25 else 'Paging match'
        ar = 'تعيين سابق' if i < 25 else 'مطابقة التعيين'
        translated = Jsonb({'ar':{'name':f'{ar} {i:03}'}})
        role = c.execute("INSERT INTO roles(code,name,org_unit_id,translations) VALUES(%s,%s,%s,%s) RETURNING id",
                         (f'MEMROLE-{i:03}',f'{en} {i:03}',unit,translated)).fetchone()[0]
        user = c.execute("INSERT INTO users(name,email,translations) VALUES(%s,%s,%s) RETURNING id",
                         (f'{en} {i:03}',f'memuser-{i:03}@test.invalid',translated)).fetchone()[0]
        valid_from = '2026-06-02T00:00:00Z' if i == 52 else '2026-01-01T00:00:00Z'
        valid_until = {25:'2026-06-01T12:00:00Z',53:'2026-05-31T23:59:59Z'}.get(i)
        c.execute("""INSERT INTO user_role_assignments(user_id,role_id,valid_from,valid_until)
                     VALUES(%s,%s,%s,%s),(%s,%s,%s,%s)""",
                  (viewer,role,valid_from,valid_until,user,anchor,valid_from,valid_until))
        if i == 54:
            c.execute("UPDATE roles SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s", (role,))
            c.execute("UPDATE users SET date_suspended=CURRENT_TIMESTAMP WHERE id=%s", (user,))
print(json.dumps({'viewer':viewer,'role':anchor}))
'''], check=True, timeout=45, capture_output=True, text=True)
    import json
    identities = json.loads(result.stdout)
    range_key = 'webui.load_held_itemships.label.start_end_total_caa5dacc'
    filter_key = 'webui.load_held_itemships.button.filters_d7704feb'
    start_key = 'webui.load_held_itemships.input.valid_during_or_after_426a5d0b'
    end_key = 'webui.load_held_itemships.input.valid_during_or_before_d4e95a3d'
    status_key = 'webui.load_held_itemships.select.status_f583ecf6'
    clear_key = 'webui.load_held_itemships.accessible_name.clear_filters_2f8c06a6'

    def choose_icon(scope, icon):
        return page.wait.until(lambda _:next((
            button for button in page.visible('button',scope)
            if any(i.text.strip() == icon for i in button.find_elements('css selector','.q-icon'))
        ), False))

    def set_date(field, value):
        # Drive the same date input events as the native date picker.
        page.driver.execute_script("""
            arguments[0].value = arguments[1];
            arguments[0].dispatchEvent(new Event('input', {bubbles:true}));
            arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
        """, field, value)

    def dialog_field(dialog, label):
        def matching(_):
            fields = [control for control in page.visible('.q-field',dialog)
                      if any(plain(item.text)==label for item in control.find_elements('css selector','.q-field__label'))]
            return fields[0].find_element('css selector','input') if len(fields)==1 else False
        return page.wait.until(matching, f'Missing assignment filter {label}')

    for language in (page.language, 'ar' if page.language=='en' else 'en'):
        if language != page.language:
            page.settings()
            page.language_change(language)
        for resource, for_user in (('users',True),('roles',False)):
            with page.check(f'Manage Assignments from {resource} filters the full collection and retains filters'):
                if for_user:
                    name, card_search = 'viewer@test.invalid', 'webui.render_table.input.filter_users_87c1f82f'
                    path = f"/api/v1/users/{identities['viewer']}/roles"
                    counterpart = page.t('entity_metadata.field.role')
                    suffix = 'code'
                    status_param = 'role_status'
                    last_row = 'MEMROLE-051'
                else:
                    name, card_search = 'Membership paging fixture', 'webui.render_table.input.filter_roles_89b2d475'
                    path = f"/api/v1/roles/{identities['role']}/users"
                    counterpart = page.t('entity_metadata.field.user')
                    suffix = 'email'
                    status_param = 'user_status'
                    last_row = 'memuser-051@test.invalid'
                navigation_read = len(page.events())
                page.drawer(resource)
                page.wait.until(lambda _:any(
                    e['path']==f'/api/v1/{resource}/search' and e['status']==200
                    for e in page.events()[navigation_read:]
                ))

                def filter_cards(_):
                    card_field = page.field(page.t(card_search))
                    try:
                        page.select_field_text(card_field)
                        card_field.send_keys(name)
                    except ElementNotInteractableException:
                        return False
                    return True

                page.wait.until(filter_cards)
                def filtered_card(_):
                    cards = page.visible('.governance-list-card')
                    return cards[0] if len(cards)==1 and name in plain(cards[0].text) else False

                card = page.wait.until(filtered_card)
                page.activate(choose_icon(card,'group'))
                dialog = page.one('.membership-dialog')
                label = page.t(f'webui.show_memberships.input.search_counterpart_name_or_{suffix}').format(counterpart=counterpart)
                range_text = page.t(range_key)

                def visible_range(start,end,total):
                    page.see(range_text.format(start=start,end=end,total=total))

                def read(action, offset, total, *, sort='counterpart', **filters):
                    index = len(page.events())
                    action()
                    def relevant_reads():
                        return [e for e in page.events()[index:] if e['method']=='GET' and e['path']==path]
                    page.wait.until(lambda _:bool(relevant_reads()))
                    visible_range(offset+1 if total else 0, min(offset+25,total),total)
                    reads = relevant_reads()
                    assert len(reads)==1 and reads[0]['status']==200, reads
                    params = parse_qs(reads[0]['query'])
                    assert params['offset']==[str(offset)] and params['limit']==['25'], params
                    assert params['sort']==[sort] and params['descending']==['false'], params
                    assert {key: values[0] for key,values in params.items()
                            if key not in ('offset','limit','sort','descending')}==filters, params

                visible_range(1,25,55)
                assert len(dialog.find_elements('css selector','.membership-table tbody tr'))==25
                term = 'مطابقة التعيين' if language=='ar' else 'Paging match'
                search = dialog_field(dialog,label)

                def replace_query(value):
                    page.select_field_text(search)
                    search.send_keys(value or Keys.BACKSPACE)
                    page.wait.until(lambda _:search.get_attribute('value')==value)

                read(lambda:replace_query(term),0,30,membership_q=term)
                page.click(page.t(filter_key),dialog)
                status = dialog_field(dialog,page.t(status_key))

                def select_active():
                    page.activate(status)
                    active = page.t('webui.load_held_itemships.text.active_9406c1d5')
                    option = page.wait.until(lambda _:next((
                        item for item in page.visible('[role=option]') if plain(item.text)==active
                    ), False))
                    page.activate(option)

                filters = {'membership_q':term,status_param:'active'}
                read(select_active,0,29,**filters)
                valid_from = dialog_field(dialog,page.t(start_key))
                valid_until = dialog_field(dialog,page.t(end_key))
                filters['valid_from'] = '2026-06-01'
                read(lambda:set_date(valid_from,filters['valid_from']),0,28,**filters)
                filters['valid_until'] = '2026-06-01'
                read(lambda:set_date(valid_until,filters['valid_until']),0,27,**filters)

                read(lambda:choose_icon(dialog,'chevron_right').send_keys(Keys.ENTER),25,27,**filters)
                assert len(dialog.find_elements('css selector','.membership-table tbody tr'))==2
                page.see(last_row)
                assert search.get_attribute('value')==term
                assert valid_from.get_attribute('value')==valid_until.get_attribute('value')=='2026-06-01'
                assert not choose_icon(dialog,'chevron_right').is_enabled()
                page.capture(f'membership-{resource}-filtered-page-two-{language}')
                read(lambda:choose_icon(dialog,'chevron_left').send_keys(Keys.ENTER),0,27,**filters)
                page.see('MEMROLE-025' if for_user else 'memuser-025@test.invalid')
                read(lambda:replace_query('unmatched-fixture'),0,0,**{**filters,'membership_q':'unmatched-fixture'})
                page.see(page.t('webui.render_governance_cards.label.no_matching_items_38db9ba1'))
                assert search.is_displayed() and valid_from.is_displayed()
                read(lambda:replace_query(term),0,27,**filters)
                read(lambda:page.button(page.t(clear_key),dialog).send_keys(Keys.ENTER),0,30,membership_q=term)
                header = page.wait.until(lambda _:next((
                    item for item in page.visible('th',dialog) if page.t('webui.show_memberships.table.valid_from') in plain(item.text)
                ), False))
                read(lambda:page.activate(header),0,30,sort='valid_from',membership_q=term)
                page.button(page.t('webui.show_memberships.button.close_4c7a508f'),dialog).send_keys(Keys.ENTER)
                page.wait.until(lambda _:not page.driver.find_elements('css selector','.q-dialog'))
                page.errors()
