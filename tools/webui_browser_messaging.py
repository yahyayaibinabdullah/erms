"""Native mailbox compose/draft controls, focus and administration destinations."""
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


def check_messaging(page):
    def text(key):return page.t('messaging.'+key)
    def nav(key):page.activate(page.one('button.erms-nav-link',text(key)))
    def capture(key):page.capture('messaging-'+key+'-'+page.language)
    def rows(subject):return [e for e in page.visible('[role=button].cursor-pointer') if subject in plain(e.text)]
    def drafts(deleted=False):
        r=page.api.get('/api/v1/messages/drafts',params={'deleted':deleted});r.raise_for_status();return r.json()['items']
    for language in ('en','ar'):
        if language=='ar':page.settings();page.language_change('ar')
        subject='Browser draft '+language
        with page.check('mailbox compose, native focus, draft save and existing URL/history'):
            nav('navigation.inbox');page.see(text('state.empty'));url=page.driver.current_url;history=page.driver.execute_script('return history.length');capture('inbox')
            page.click(text('action.compose'));dialog=page.one('[role=dialog]');field=page.field(text('field.subject'));capture('compose')
            page.activate(field);field.send_keys(Keys.TAB);active=page.driver.switch_to.active_element
            page.report.setdefault('focus',[]).append({'language':language,'tag':active.tag_name,'role':active.get_attribute('role'),'label':plain(active.get_attribute('aria-label') or '')})
            page.fill(text('field.subject'),subject);editor=page.one('[contenteditable=true]',scope=dialog);page.activate(editor);editor.send_keys('Preserved draft content');capture('draft-content')
            page.click(text('action.save_draft'),dialog);page.see(text('state.saved'));draft=next(x for x in drafts() if x['subject']==subject)
            page.button(text('action.cancel'),dialog).send_keys(Keys.ENTER);page.wait.until(lambda _:not page.visible('[role=dialog]'))
            nav('navigation.drafts');page.wait.until(lambda _:len(rows(subject))==1);page.activate(rows(subject)[0]);page.field(text('field.subject'));page.click(text('action.discard'))
            page.wait.until(lambda _:not page.visible('[role=dialog]') and not rows(subject));assert draft['id'] not in {r['id'] for r in drafts()}
            switch=page.one('.q-toggle');page.activate(switch);page.wait.until(lambda _:len(rows(subject))==1);page.activate(rows(subject)[0]);page.click(text('action.restore'))
            page.wait.until(lambda _:not page.visible('[role=dialog]') and not rows(subject));assert draft['id'] in {r['id'] for r in drafts()}
            # Delete only this synthetic draft through the existing API so the
            # next language starts with the same empty active mailbox.
            saved=next(r for r in drafts() if r['id']==draft['id']);response=page.api.delete('/api/v1/messages/drafts/'+draft['id'],headers={'If-Match':str(saved['version'])});response.raise_for_status()
            assert page.driver.current_url==url and page.driver.execute_script('return history.length')==history
        with page.check('message monitor and notification administration remain reachable'):
            monitor_reads=sum(e['path']=='/api/v1/messages/monitor/producers' for e in page.events());nav('monitor.title');page.see(text('monitor.title'));page.wait.until(lambda _:sum(e['path']=='/api/v1/messages/monitor/producers' and e['status']==200 for e in page.events())>monitor_reads);capture('monitor')
            nav('admin.title');page.see(text('admin.title'));page.wait.until(lambda _:not page.visible('.q-inner-loading'));capture('notifications')
            page.errors();page.settings()
    check_applied_message_filters(page, nav, text)


def check_applied_message_filters(page, nav, text):
    import subprocess
    from urllib.parse import parse_qs
    from uuid import uuid4

    import httpx
    from tools.check_webui_browser import PASSWORD

    subprocess.run([page.args.api_python,'-c','''
import psycopg
from tools.seed_webui_regression import disposable_url
with psycopg.connect(disposable_url()) as c:
    c.execute("SELECT set_config('app.event_source','seeding',true)")
    c.execute("""
        INSERT INTO profile_privileges(profile_id,privilege_id)
        SELECT p.id,v.id FROM profiles p CROSS JOIN privileges v
        WHERE p.code='INFO_GOV_OFFICER' AND v.code='messaging.user_messages.exchange'
        ON CONFLICT DO NOTHING
    """)
    c.execute("""
        INSERT INTO system_notification_producers
            (producer_code,feature_code,event_type,required_for_business_commit,contract_version,contract_definition,name)
        SELECT 'paging-fixture.'||lpad(i::text,2,'0'),'paging-fixture','test',false,1,'{}',
               'Producer paging fixture '||lpad(i::text,2,'0')
        FROM generate_series(0,26) i
    """)
'''], check=True, timeout=30)

    admin = page.api.get('/api/v1/auth/me').json()['user']['id']
    with httpx.Client(base_url=page.args.api, trust_env=False, timeout=20) as officer:
        login = officer.post('/api/v1/auth/login', json={'email':'officer@test.invalid','password':PASSWORD})
        login.raise_for_status()
        officer.headers['X-CSRF-Token'] = officer.cookies['erms_csrf']
        officer_id = officer.get('/api/v1/auth/me').json()['user']['id']
        for i in range(27):
            for sender, target in ((page.api, officer_id), (officer, admin)):
                response = sender.post('/api/v1/messages/send', json={
                    'request_id':str(uuid4()),'subject':f'Mail paging fixture {i:02}',
                    'body_rich_text':'<p>Synthetic paging fixture</p>',
                    'selectors':[{'selector_kind':'user','target_id':target,'recipient_type':'to'}],
                })
                assert response.is_success, response.text
            response = page.api.post('/api/v1/messages/drafts', json={'subject':f'Draft paging fixture {i:02}'})
            assert response.is_success, response.text

    def page_read(action, endpoint, *, cursor_key, cursor, **filters):
        started = len(page.events())
        action()
        def reads():
            return [e for e in page.events()[started:] if e['path']==endpoint and e['method']=='GET']
        page.wait.until(lambda _:bool(reads()))
        result=reads()
        assert len(result)==1 and result[0]['status']==200, result
        params = parse_qs(result[0]['query'], keep_blank_values=True)
        assert bool(params.get(cursor_key, [''])[0]) == cursor, params
        for key, value in filters.items():
            assert params.get(key) == ([value] if value is not None else None), params

    for language in (page.language, 'ar' if page.language=='en' else 'en'):
        if page.language != language:
            page.settings()
            page.wait.until(lambda _:not page.visible('.q-notification'))
            page.language_change(language)
        page.wait.until(lambda _:not page.visible('.q-notification'))
        with page.check('outbox pagination keeps the submitted subject'):
            nav('navigation.outbox')
            endpoint='/api/v1/messages/outbox'
            search=text('field.search')
            page.fill(search,'Mail paging fixture')
            page_read(lambda:page.click(search),endpoint,cursor_key='cursor',cursor=False,q='Mail paging fixture')
            page.fill(search,'unsubmitted-subject')
            page_read(lambda:page.click(text('action.next')),endpoint,cursor_key='cursor',cursor=True,q='Mail paging fixture')
            page_read(lambda:page.click(text('action.previous')),endpoint,cursor_key='cursor',cursor=False,q='Mail paging fixture')
            assert page.field(search).get_attribute('value')=='unsubmitted-subject'
            page_read(lambda:page.click(search),endpoint,cursor_key='cursor',cursor=False,q='unsubmitted-subject')
            page.see(text('state.empty'))

        with page.check('inbox pagination keeps the submitted read filter'):
            nav('navigation.inbox')
            endpoint='/api/v1/messages/inbox'
            page.see('Mail paging fixture 26')
            field = page.field(text('field.read'))
            page.activate(field)
            page.activate(page.wait.until(lambda _:next(
                (option for option in page.visible('[role=option]') if plain(option.text)==text('field.read')), False,
            )))
            page_read(lambda:page.click(text('action.next')),endpoint,cursor_key='cursor',cursor=True,is_read=None)
            page_read(lambda:page.click(text('field.search')),endpoint,cursor_key='cursor',cursor=False,is_read='true')

        with page.check('draft pagination keeps the submitted recipient'):
            nav('navigation.drafts')
            endpoint='/api/v1/messages/drafts'
            page.see('Draft paging fixture 26')
            field = page.field(text('field.recipient'))
            page.activate(field)
            field.send_keys('Test officer')
            page.activate(page.wait.until(lambda _:next((
                option for option in page.visible('[role=option]')
                if 'Test officer' in plain(option.text) and text('field.user') in plain(option.text)
            ), False)))
            page_read(lambda:page.click(text('action.next')),endpoint,cursor_key='cursor',cursor=True,recipient_id=None)
            page_read(lambda:page.click(text('field.search')),endpoint,cursor_key='cursor',cursor=False,recipient_id=str(officer_id))
            page.see(text('state.empty'))

        with page.check('notification producer pagination keeps the submitted search'):
            nav('admin.title')
            endpoint='/api/v1/notification-administration/producers'
            search=page.t('messaging.admin.search')
            page.fill(search,'paging-fixture')
            page_read(lambda:page.click(search),endpoint,cursor_key='after',cursor=False,q='paging-fixture')
            page.fill(search,'paging-fixture.26')
            page_read(lambda:page.click(text('action.next')),endpoint,cursor_key='after',cursor=True,q='paging-fixture')
            page.see('Producer paging fixture 26')
            assert page.field(search).get_attribute('value')=='paging-fixture.26'
            page_read(lambda:page.click(search),endpoint,cursor_key='after',cursor=False,q='paging-fixture.26')
            page.see('Producer paging fixture 26')
            page.errors()
