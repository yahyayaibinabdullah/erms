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
        field=page.visible('.erms-card input')[0];page.activate(field)
        field.send_keys(Keys.COMMAND,'a',Keys.NULL);field.send_keys(value)
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        for resource,filter_value in (('org_units','WEBUI-TEST'),('roles','officer'),('users','viewer@test.invalid')):
            with page.check(resource+' list, detail, editor and cancellation'):
                page.drawer(resource);page.wait.until(lambda _:bool(page.visible('.governance-list-card')))
                query(filter_value);page.wait.until(lambda _:len(page.visible('.governance-list-card'))==1)
                page.activate(page.one('.governance-card-list'));capture(resource+'-list')
                errors=page.driver.execute_script('return window.__webuiTestErrors || []')
                assert errors==[{'kind':'error','message':'TypeError: u.match is not a function'}]*4,errors
                page.report.setdefault('existing_pagination_icon_errors',[]).append({'language':language,'resource':resource,'errors':errors})
                page.driver.execute_script('window.__webuiTestErrors=[]')
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
    with page.check('cancelled editors have no entity writes'):
        assert not [e for e in page.events() if e['method'] in {'POST','PUT','PATCH','DELETE'} and e['path'].startswith(('/api/v1/org-units','/api/v1/roles','/api/v1/users')) and '/search' not in e['path']]
