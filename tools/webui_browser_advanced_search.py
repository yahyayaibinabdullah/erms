"""Saved-query restoration, sharing controls, unsaved guard and administration."""
import subprocess
import json
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def check_advanced_search(page):
    roles=page.api.get('/api/v1/saved-searches/audience-options/roles',params={'q':'admin','limit':25,'offset':0});roles.raise_for_status()
    role=roles.json()['items'][0]['id']
    payload={'name':'Browser saved query','category':'Regression','description':'Synthetic search fixture','audience_mode':'shared','role_ids':[role],'org_unit_ids':[],
             'definition':{'schema_version':1,'resource_type':'record','max_results':1000,'request':{'where':{'and':[{'field':'title','operator':'contains_ci','value':'Test'}]},'sort':[{'field':'id','direction':'asc'}],'limit':25,'offset':0}}}
    subprocess.run([page.args.api_python,'-c',"""
import os,psycopg,sys,json
from psycopg.types.json import Jsonb
from psycopg.conninfo import conninfo_to_dict
url=os.environ['DATABASE_URL'];assert conninfo_to_dict(url)['dbname'].startswith('erms_webui_test_')
with psycopg.connect(url) as c:
 c.execute("SELECT set_config('app.event_source','seeding',true)")
 payload=json.loads(sys.argv[1])
 owner=c.execute("SELECT id FROM users WHERE email='admin@test.invalid'").fetchone()[0]
 saved=c.execute("INSERT INTO saved_searches(owner_user_id,name,category,description,resource_type,definition,audience_mode,date_created,date_updated) VALUES(%s,%s,%s,%s,'record',%s,'shared','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z') RETURNING id",(owner,payload['name'],payload['category'],payload['description'],Jsonb(payload['definition']))).fetchone()[0]
 c.execute("INSERT INTO saved_search_role_grants(saved_search_id,role_id) VALUES(%s,%s)",(saved,payload['role_ids'][0]))
""",json.dumps(payload)],check=True,timeout=30)
    def click(key,scope=None):page.click(page.t(key),scope)
    def dialog():return page.one('.q-dialog__inner > .q-card')
    def closed():page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))
    def capture(name):page.capture('advanced-'+name+'-'+page.language)
    value='webui.render_condition.input.value_8dc59edc'
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('saved search opens, executes and retains sharing controls'):
            page.drawer('advanced_search');page.one('.advanced-search-page');url=page.driver.current_url;history=page.driver.execute_script('return history.length')
            click('webui.select_advanced_search.button.open_saved_search_8bef667f');d=dialog();page.see('Browser saved query');capture('saved-list')
            click('webui.load_saved_page.button.open_2606a7e0',d);closed();page.wait.until(lambda _:page.field(page.t(value)).get_attribute('value')=='Test')
            field=page.field(page.t(value));page.activate(field);field.send_keys(Keys.TAB);active=page.driver.switch_to.active_element
            assert active.text=='cancel' and active.get_attribute('role')=='button';active.send_keys(Keys.TAB);active=page.driver.switch_to.active_element
            assert plain(active.get_attribute('aria-label'))==page.t('webui.render_condition.accessible_name.negate_condition_0ee5684b')
            page.report.setdefault('focus',[]).append({'language':language,'sequence':['criterion value','clear','negate']});capture('builder')
            click('webui.select_advanced_search.button.search_97989f23',page.one('.advanced-search-submit-row'));page.wait.until(lambda _:page.visible('.compact-result-item'));capture('results')
            click('webui.open_aggregation.button.edit_metadata_3ee4d255');d=dialog();page.see(page.t('webui.saved_audience.roles_help'));capture('sharing')
            click('webui.save_search.button.cancel_6ad2d1bd',d);closed()
        with page.check('unsaved guard, retained editing, discard and administration destination'):
            page.fill(page.t(value),'Changed fixture');page.drawer('dashboard');d=dialog();capture('guard')
            click('webui.confirm_discard_changes.button.keep_editing_965cc0ca',d);closed();assert page.field(page.t(value)).get_attribute('value')=='Changed fixture'
            page.drawer('dashboard');click('webui.confirm_discard_changes.button.discard_changes_81df7dc9',dialog());closed();page.one('.dashboard-overview-primary')
            page.click(page.t('privilege.search.saved_search.administrator.name'));page.see('Browser saved query');capture('administration')
            edit=next(b for b in page.visible('.erms-card button') if any(i.text=='edit' for i in b.find_elements('css selector','.q-icon')));page.activate(edit)
            page.one('.advanced-search-page');page.wait.until(lambda _:page.field(page.t(value)).get_attribute('value')=='Test');capture('administration-open')
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
            page.errors();page.settings()

    def read_saved(identifier):
        response=page.api.get(f'/api/v1/saved-searches/{identifier}');response.raise_for_status()
        return response.json()
    def open_named(name):
        click('webui.select_advanced_search.button.open_saved_search_8bef667f')
        d=dialog()
        card=page.wait.until(lambda _:next((c for c in page.visible('.q-card',d)
            if any(plain(label.text)==name for label in c.find_elements('css selector','.font-semibold'))),False))
        click('webui.load_saved_page.button.open_2606a7e0',card);closed()
    def expected_results(identifier):
        response=page.api.post(f'/api/v1/saved-searches/{identifier}/execute',json={'limit':25,'offset':0})
        response.raise_for_status();return response.json()
    def result_ids(resource):
        prefix=f'compact-result-{resource}-'
        return [int(e.get_attribute('id').removeprefix(prefix)) for e in page.visible('.compact-result-item')]

    for language in ('en','ar'):
        if page.language!=language:page.settings();page.language_change(language)
        for resource in ('records','aggregations'):
            with page.check(f'bare-condition {resource} reopen, clean execution, edit, save and reopen'):
                name=f'Bare {resource} {language}'
                leaf={'field':'title','operator':'contains_ci','value':'Test'}
                request={'name':name,'category':'Regression','description':'Bare-condition regression fixture',
                    'audience_mode':'private','role_ids':[],'org_unit_ids':[],
                    'definition':{'schema_version':1,'resource_type':resource[:-1],'max_results':1000,
                        'request':{'where':leaf,'sort':[{'field':'id','direction':'asc'}],'limit':25,'offset':0}}}
                response=page.api.post('/api/v1/saved-searches',json=request);response.raise_for_status();saved=response.json()
                identifier=saved['id'];assert saved['definition']['request']['where']==leaf
                expected=expected_results(identifier);assert expected['items']
                page.drawer('advanced_search');page.one('.advanced-search-page');open_named(name)
                page.wait.until(lambda _:page.field(page.t(value)).get_attribute('value')=='Test')
                assert read_saved(identifier)['definition']==saved['definition']
                assert read_saved(identifier)['version']==saved['version']
                capture(f'bare-{resource}-opened')
                # Merely opening the saved query must not create a discard prompt.
                page.drawer('dashboard');page.one('.dashboard-overview-primary')
                assert not page.visible('.q-dialog__inner > .q-card')
                page.drawer('advanced_search');page.one('.advanced-search-page')
                started=len(page.events())
                click('webui.select_advanced_search.button.search_97989f23',page.one('.advanced-search-submit-row'))
                page.wait.until(lambda _:result_ids(resource)==[item['id'] for item in expected['items']])
                assert any(e['path']==f'/api/v1/saved-searches/{identifier}/execute' and e['status']==200 for e in page.events()[started:])
                edited=expected['items'][0]['title'];assert edited!='Test'
                page.fill(page.t(value),edited)
                click('webui.refresh_saved_actions.text.update_saved_search_31788e51')
                page.wait.until(lambda _:read_saved(identifier)['version']>saved['version'])
                page.wait.until(lambda _:page.button(page.t('webui.refresh_saved_actions.text.update_saved_search_31788e51')).is_enabled())
                updated=read_saved(identifier)
                assert updated['definition']['request']['where']=={'and':[dict(leaf,value=edited)]}
                assert updated['definition']['resource_type']==saved['definition']['resource_type']
                assert updated['definition']['max_results']==saved['definition']['max_results']
                assert updated['audience_mode']==saved['audience_mode'] and updated['owner_user_id']==saved['owner_user_id']
                open_named(name)
                page.wait.until(lambda _:page.field(page.t(value)).get_attribute('value')==edited)
                expected=expected_results(identifier)
                click('webui.select_advanced_search.button.search_97989f23',page.one('.advanced-search-submit-row'))
                page.wait.until(lambda _:result_ids(resource)==[item['id'] for item in expected['items']])
                capture(f'bare-{resource}-saved-reopened');page.errors()
                page.report.setdefault('bare_condition_reopening',[]).append({'resource':resource,'language':language,
                    'stored_definition_unchanged_on_open':True,'clean_navigation':True,
                    'saved_execution_matches_api':True,'edited_value_retained':True,
                    'before_version':saved['version'],'after_version':updated['version']})
                page.settings()
    assert not [e for e in page.events() if e['status'] is None or e['status']>=400]
