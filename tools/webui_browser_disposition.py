"""Existing disposition pages, bounded selectors, focus and filter persistence."""
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def check_disposition(page):
    def text(key):return page.t('disposition.ui.'+key)
    def workspace():return page.one('.detail-surface.messaging-workspace')
    def enter(key):
        old=workspace().get_attribute('id') if page.visible('.detail-surface.messaging-workspace') else None
        page.activate(page.one('button.erms-nav-link',text({'disposition-jobs':'jobs','disposition-eligibility':'eligibility','disposition-tasks':'my_tasks'}[key])))
        page.wait.until(lambda _:workspace().get_attribute('id')!=old)
        page.wait.until(lambda _:not page.visible('.q-inner-loading'))
    def capture(key):page.capture('disposition-'+key+'-'+page.language)
    def expand(value=True):
        control=page.one('.q-expansion-item > .q-expansion-item__container > .q-item',scope=workspace())
        if (control.get_attribute('aria-expanded')=='true')!=value:page.activate(control)
        page.wait.until(lambda _:(control.get_attribute('aria-expanded')=='true')==value)
        page.wait.until(lambda _:page.driver.execute_script('return arguments[0].getAnimations({subtree:true}).every(a=>a.playState!=="running")',workspace()))
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        with page.check('disposition jobs filters, bounded create selectors and keyboard focus'):
            enter('disposition-jobs');page.see(text('empty'));url=page.driver.current_url;history=page.driver.execute_script('return history.length');capture('jobs')
            expand();query=page.field(text('search'));query.send_keys(Keys.TAB);active=page.driver.switch_to.active_element
            page.report.setdefault('focus',[]).append({'language':language,'tag':active.tag_name,'role':active.get_attribute('role'),'label':plain(active.get_attribute('aria-label') or '')})
            capture('filters');expand(False);page.click(text('create'),workspace());dialog=page.one('[role=dialog]');page.field(text('owner'));page.wait.until(lambda _:text('loading') not in plain(dialog.text));capture('create')
            page.click(text('cancel'),dialog);page.wait.until(lambda _:not page.visible('[role=dialog]'))
            expand();page.settings();enter('disposition-jobs');assert page.field(text('search')).is_displayed()
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('disposition eligibility and task pages retain existing navigation and empty states'):
            enter('disposition-eligibility');page.see(text('empty'));capture('eligibility')
            enter('disposition-tasks');page.see(text('empty'));capture('tasks')
            page.activate(page.one('button.erms-nav-link',text('templates')));page.see(text('repository_default'));capture('templates')
            page.errors();page.settings()
    check_disposition_applied_filters(page, enter, expand, workspace, text)


def check_disposition_applied_filters(page, enter, expand, workspace, text):
    import subprocess
    from urllib.parse import parse_qs
    from uuid import uuid4

    base = '/api/v1/disposition/'
    context = page.api.get(base+'context')
    context.raise_for_status()
    context = context.json()
    admin = context['current_user']['id']
    role = next(r['id'] for r in context['roles'] if r['profile_code']=='INFO_GOV_OFFICER')
    root = page.api.post('/api/v1/aggregations/search', json={
        'where':{'field':'aggregation_number','operator':'eq','value':'TEST-AGG'}, 'limit':1,
    }).json()['items'][0]
    unit = root['owning_org_unit_id']
    jobs = []
    for _ in range(27):
        response = page.api.post(base+'jobs', json={
            'job_type':'destruction','owning_org_unit_id':unit,'assigned_user_id':admin,
            'acting_role_id':role,'command_id':str(uuid4()),
        })
        assert response.status_code == 201, response.text
        jobs.append(response.json())
    job = jobs[-1]

    subprocess.run([page.args.api_python, '-c', '''
import psycopg
from psycopg.rows import dict_row
from backend.services.api.disposition.eligibility import evaluate_root, worker_actor
from tools.seed_webui_regression import disposable_url
with psycopg.connect(disposable_url()) as c:
    c.execute("SELECT set_config('app.event_source','seeding',true)")
    classification, unit = c.execute(
        "SELECT classification_id,owning_org_unit_id FROM aggregations WHERE aggregation_number='TEST-AGG'"
    ).fetchone()
    c.execute("""
        INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,
                                 medium,date_opened,date_closed)
        SELECT 'DISP-PAGE-'||lpad(i::text,3,'0'),'Disposition page fixture '||i,%s,%s,
               'physical','2015-01-01','2016-01-01'
        FROM generate_series(0,55) i
    """, (classification,unit))
with psycopg.connect(disposable_url()) as c:
    identifiers = c.execute("SELECT id FROM aggregations WHERE aggregation_number LIKE 'DISP-PAGE-%'").fetchall()
for (identifier,) in identifiers:
    with psycopg.connect(disposable_url(),row_factory=dict_row) as c:
        worker_actor(c)
        c.execute("SELECT set_config('app.event_source','seeding',true)")
        outcome = evaluate_root(c,identifier)
        assert outcome['changed'], outcome
'''], check=True, timeout=40)
    roots = page.api.post('/api/v1/aggregations/search', json={
        'where':{'field':'aggregation_number','operator':'starts_with_ci','value':'DISP-PAGE-'},
        'limit':27,'sort':[{'field':'aggregation_number','direction':'asc'}],
    }).json()['items']
    response = page.api.post(base+f"jobs/{job['id']}/memberships", headers={'If-Match':str(job['version'])}, json={
        'acting_role_id':role,'command_id':str(uuid4()),
        'items':[{'root_id':r['id'],'expected_version':r['version']} for r in roots],
    })
    assert response.is_success, response.text
    members = page.api.get(base+f"jobs/{job['id']}/memberships")
    assert members.is_success and members.json()['total'] == 27, response.text

    def read(action, endpoint, offset, **filters):
        before = len(page.events())
        action()
        def requests():
            return [e for e in page.events()[before:] if e['path']==base+endpoint and e['method']=='GET']
        page.wait.until(lambda _: any(parse_qs(e['query']).get('offset')==[str(offset)] for e in requests()))
        result = requests()
        assert len(result) == 1 and result[0]['status']==200, result
        params = parse_qs(result[0]['query'], keep_blank_values=True)
        assert all(params.get(key)==[value] for key,value in filters.items()), params

    def next_page(scope):
        page.button(page.t('relationships.ui.next'),scope).send_keys(Keys.ENTER)

    def enter_query(key):
        page.field(text(key)).send_keys(Keys.ENTER)

    for language in ('en','ar'):
        if page.language != language:
            page.settings()
            page.language_change(language)
        for section, endpoint in (('disposition-jobs','jobs'),('disposition-tasks','tasks')):
            with page.check(f'Disposition {endpoint} pagination keeps the submitted search'):
                enter(section)
                expand()
                submitted = job['job_number'].rsplit('-',1)[0]
                page.fill(text('search'), submitted)
                read(lambda:enter_query('search'), endpoint, 0, query=submitted)
                page.fill(text('search'), 'unsubmitted-disposition')
                read(lambda:next_page(workspace()), endpoint, 25, query=submitted)
                assert page.field(text('search')).get_attribute('value')=='unsubmitted-disposition'
                read(lambda:enter_query('search'), endpoint, 0, query='unsubmitted-disposition')

        with page.check('Disposition eligibility keeps applied filters across pages'):
            enter('disposition-eligibility')
            expand()
            group = page.one('[role=checkbox]',text('group_owner'),scope=workspace())
            page.activate(group)
            read(lambda:next_page(workspace()), 'eligibility', 25, group_owner='false')
            apply_button = page.button(text('filters'),scope=workspace())
            read(lambda:page.activate(apply_button), 'eligibility', 0, group_owner='true')
            page.button(text('eligibility_select_page'),scope=workspace()).send_keys(Keys.ENTER)
            page.click(text('add'),workspace())
            dialog = page.one('.q-dialog__inner > .q-card')
            page.see(text('select_job'))
            page.fill(text('search'), 'unsubmitted-job')
            read(lambda:next_page(dialog), 'jobs', 25, query='')
            read(lambda:enter_query('search'), 'jobs', 0, query='unsubmitted-job')
            page.click(text('cancel'),dialog)
            page.wait.until(lambda _:not page.visible('.q-dialog__inner > .q-card'))

        with page.check('Disposition job aggregations keep the submitted search across pages'):
            enter('disposition-jobs')
            expand()
            page.fill(text('search'),job['job_number'])
            read(lambda:enter_query('search'),'jobs',0,query=job['job_number'])
            row = page.wait.until(lambda _:next((r for r in page.visible('tbody tr',workspace())
                                                if job['job_number'] in plain(r.text)),False))
            page.activate(page.one('button',text('open'),scope=row))
            page.activate(page.one('[role=tab]',text('workspace_members')))
            page.fill(text('search_aggregations'),'DISP-PAGE-')
            path = f"jobs/{job['id']}/memberships"
            read(lambda:enter_query('search_aggregations'), path, 0, query='DISP-PAGE-')
            page.fill(text('search_aggregations'),'unsubmitted-aggregation')
            read(lambda:next_page(workspace()), path, 25, query='DISP-PAGE-')
            read(lambda:enter_query('search_aggregations'), path, 0, query='unsubmitted-aggregation')
            page.errors()

    # Add holds after admission to exercise live blockers on an existing member.
    root_id = roots[0]['id']
    subprocess.run([page.args.api_python, '-c', '''
import sys, psycopg
from tools.seed_webui_regression import disposable_url
with psycopg.connect(disposable_url()) as c:
    c.execute("""SELECT set_config('app.event_source','seeding',true),
                        set_config('app.user_id',%s,true),
                        set_config('app.actor_type','user',true),
                        set_config('app.change_reason','Seed Blockers overflow fixture',true)""",
              (sys.argv[1],))
    c.execute("""
        INSERT INTO holds(code,name,valid_from,owner_user_id)
        SELECT 'BLOCKER-'||lpad(i::text,2,'0'),'Blocker notice fixture '||i,
               CURRENT_TIMESTAMP-INTERVAL '1 day',%s
        FROM generate_series(1,26) i
    """, (int(sys.argv[1]),))
    c.execute("""
        INSERT INTO hold_aggregation_assignments(hold_id,aggregation_id)
        SELECT id,%s FROM holds WHERE code LIKE 'BLOCKER-%%'
    """, (int(sys.argv[2]),))
''', str(admin), str(root_id)], check=True, timeout=30)
    for language in ('en', 'ar'):
        if page.language != language:
            page.settings()
            page.language_change(language)
        with page.check('Disposition Blockers displays a localized notice after 25 hold names'):
            enter('disposition-jobs')
            expand()
            page.fill(text('search'),job['job_number'])
            read(lambda:enter_query('search'),'jobs',0,query=job['job_number'])
            row = page.wait.until(lambda _:next((r for r in page.visible('tbody tr',workspace())
                                                if job['job_number'] in plain(r.text)),False))
            page.activate(page.one('button',text('open'),scope=row))
            page.activate(page.one('[role=tab]',text('workspace_members')))
            page.fill(text('search_aggregations'), roots[0]['aggregation_number'])
            read(lambda:enter_query('search_aggregations'), path, 0, query=roots[0]['aggregation_number'])
            row = page.wait.until(lambda _:next((r for r in page.visible('tbody tr',workspace())
                if roots[0]['aggregation_number'] in plain(r.text)),False))
            read(lambda:page.click(text('blockers'),row), f'aggregations/{root_id}/blockers', 0)
            dialog = page.one('.q-dialog__inner > .q-card')
            notice = page.one('[role=status]',text('blockers_holds_more'),scope=dialog)
            assert notice.is_displayed()
            assert plain(dialog.text).count('Blocker notice fixture ') == 25
            assert 'BLOCKER-26' not in plain(dialog.text)
            page.capture('disposition-blockers-more-holds-' + language, target=dialog)
            page.click(text('cancel'),dialog)
            page.errors()
