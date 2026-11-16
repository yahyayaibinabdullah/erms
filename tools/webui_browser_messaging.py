"""Native mailbox compose/draft controls, focus and administration destinations."""
from base64 import b64decode
from uuid import uuid4

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import plain


BODY_LINES = (
    'Prepared the handover register for the next transfer.',
    'Review the register.',
    'Confirm the next transfer.',
    'Add a note if needed.',
)


def type_multiline_body(editor):
    first, second, third, fourth = BODY_LINES
    editor.send_keys(first, Keys.ENTER, second, Keys.ENTER, Keys.ENTER, third,
                     Keys.SHIFT, Keys.ENTER, Keys.NULL, fourth)


def assert_multiline_body(element):
    rendered = element.get_property('innerText')
    assert tuple(line.strip() for line in rendered.splitlines() if line.strip()) == BODY_LINES, rendered
    assert any(
        not paragraph.get_property('textContent').strip() and paragraph.find_elements(By.TAG_NAME, 'br')
        for paragraph in element.find_elements(By.TAG_NAME, 'p')
    ), element.get_property('innerHTML')


def check_messaging(page):
    def text(key):return page.t('messaging.'+key)

    def nav(key):
        page.activate(page.one('button.erms-nav-link', text(key)))
        if key in {'navigation.inbox', 'navigation.outbox', 'navigation.drafts'}:
            page.one('button.erms-nav-link[aria-current=page]', text(key))
            page.one(f'.messaging-workspace[data-mailbox={key.rsplit(".", 1)[-1]}]')

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
            page.fill(text('field.subject'),subject);editor=page.one('[contenteditable=true]',scope=dialog);page.activate(editor);type_multiline_body(editor);capture('draft-content')
            page.click(text('action.save_draft'),dialog);page.see(text('state.saved'));draft=next(x for x in drafts() if x['subject']==subject)
            page.button(text('action.cancel'),dialog).send_keys(Keys.ENTER);page.wait.until(lambda _:not page.visible('[role=dialog]'))
            nav('navigation.drafts');page.wait.until(lambda _:len(rows(subject))==1);page.activate(rows(subject)[0]);page.field(text('field.subject'))
            assert_multiline_body(page.one('[contenteditable=true]'))
            page.click(text('action.discard'))
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
    officer_id = check_applied_message_filters(page, nav, text)
    preview_subject, record_title, aggregation_title = seed_linked_resources(page.api, officer_id)
    with page.check('recipient reading pane preserves typed paragraphs, a blank line, and a soft break'):
        page.sign_out()
        page.login('officer@test.invalid')
        nav('navigation.inbox')
        for language in ('en', 'ar'):
            subject = 'Browser messaging redesign workflow ' + language + ' edited'
            row = page.wait.until(lambda _: next(iter(rows(subject)), False))
            page.activate(row)
            page.one('.mailbox-letter [role=heading]', subject)
            assert_multiline_body(page.one('.mailbox-letter-body'))
        page.errors()

    with page.check('linked record opens its files and linked aggregation opens its contents'):
        page.activate(page.one('.mailbox-row-subject', preview_subject))
        heading = page.one('.mailbox-letter [role=heading]', preview_subject)
        page.see(text('reader.linked_resources'))
        url = page.driver.current_url
        page.click(record_title, page.one('.mailbox-letter'))
        viewer = page.one('[role=dialog]')
        page.one('.component-viewer-toolbar', scope=viewer)
        page.one('.component-switcher-filename', 'linked-1.png', viewer)
        page.one('.q-img', scope=viewer)
        switch = page.one('.component-switcher-button', '2', viewer)
        page.activate(switch)
        page.one('.component-switcher-filename', 'linked-2.png', viewer)
        page.one('.q-img', scope=viewer)
        page.click(page.t('webui.select_component.accessible_name.close_viewer_7a596c99'), viewer)
        page.wait.until(lambda _: not page.visible('[role=dialog]'))
        assert page.driver.current_url == url
        assert page.one('.mailbox-letter [role=heading]', preview_subject).id == heading.id
        page.click(aggregation_title, page.one('.mailbox-letter'))
        page.wait.until(lambda _: any(
            record_title in plain(section.text) for section in page.visible('.resource-contents-section')
        ))
        assert not page.visible('[role=dialog]')
        page.click(page.t('webui.open_aggregation.button.back_4d496e53'))
        page.one('.mailbox-row-subject', preview_subject)
        page.errors()


def seed_linked_resources(api, recipient_id):
    def create(path, **kwargs):
        response = api.post('/api/v1/' + path, **kwargs)
        response.raise_for_status()
        return response.json()

    parent = create('aggregations/search', json={
        'where': {'field': 'aggregation_number', 'operator': 'eq', 'value': 'TEST-AGG'},
        'limit': 1, 'offset': 0,
    })['items'][0]
    aggregation = create('aggregations', json={
        'aggregation_number': 'MAIL-PREVIEW', 'title': 'Mailbox preview aggregation',
        'classification_id': parent['classification_id'], 'medium': 'digital',
    })
    record = create('records', json={
        'aggregation_id': aggregation['id'], 'record_number': 'MAIL-FILES',
        'title': 'Mailbox preview record', 'medium': 'digital',
    })
    png = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jP1cAAAAASUVORK5CYII=')
    for order in (1, 2):
        create(f"records/{record['id']}/digital-components/upload",
               data={'component_order': str(order)}, files={'file': (f'linked-{order}.png', png, 'image/png')})

    links = [
        {'link_token': str(uuid4()), 'resource_kind': kind, 'target_id': resource['id']}
        for kind, resource in (('record', record), ('aggregation', aggregation))
    ]
    subject = 'Browser linked resource preview'
    create('messages/send', json={
        'request_id': str(uuid4()), 'subject': subject,
        'body_rich_text': '<p>Open the linked files.</p>' + ''.join(
            f'<span data-wathiq-link="{link["link_token"]}"></span>' for link in links
        ),
        'resource_links': links,
        'selectors': [{'selector_kind': 'user', 'target_id': recipient_id, 'recipient_type': 'to'}],
    })
    return subject, record['title'], aggregation['title']


def check_applied_message_filters(page, nav, text):
    import subprocess
    from urllib.parse import parse_qs

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
    c.execute("""
        WITH recipients AS (
            INSERT INTO users(name,email)
            SELECT 'Receipt test recipient '||n, 'receipt-'||n||'@test.invalid'
            FROM generate_series(1,3) n RETURNING id
        )
        INSERT INTO user_role_assignments(user_id,role_id)
        SELECT recipients.id,roles.id FROM recipients CROSS JOIN roles WHERE roles.code='officer'
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
                    'priority':'high' if i in (25, 26) else 'normal',
                    'selectors':[{'selector_kind':'user','target_id':target,'recipient_type':'to'}],
                })
                assert response.is_success, response.text
            response = page.api.post('/api/v1/messages/drafts', json={'subject':f'Draft paging fixture {i:02}'})
            assert response.is_success, response.text
        receipt_message = seed_outbox_receipts(page, officer, admin, officer_id)

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

    def enter_language(language):
        if page.language != language:
            page.settings()
            page.wait.until(lambda _:not page.visible('.q-notification'))
            page.language_change(language)
        page.wait.until(lambda _:not page.visible('.q-notification'))

    with page.check('configured mailbox limit and ranges are shared by Inbox, Outbox and Drafts'):
        def set_page_size(value):
            path = '/api/v1/application-settings'
            settings = page.api.get(path)
            settings.raise_for_status()
            item = next(item for item in settings.json()['items'] if item['key'] == 'MESSAGES_PAGE_SIZE')
            response = page.api.put(path, headers={'X-Change-Reason': 'Verify mailbox pagination'}, json={
                'changes': [{'key': item['key'], 'expected_version': item['version'], 'value': value}],
            })
            response.raise_for_status()

        enter_language('en' if page.language == 'ar' else 'ar')
        set_page_size(10)
        for mailbox in ('inbox', 'outbox', 'drafts'):
            endpoint = '/api/v1/messages/' + mailbox
            page_read(lambda: nav('navigation.' + mailbox), endpoint, cursor_key='cursor', cursor=False, limit='10')
            page.one('.mailbox-pagination [role=status]', '1–10')
            page_read(lambda: page.click(text('action.next')), endpoint, cursor_key='cursor', cursor=True, limit='10')
            page.one('.mailbox-pagination [role=status]', '11–20')
        set_page_size(25)
        for mailbox in ('inbox', 'outbox', 'drafts'):
            page_read(lambda: nav('navigation.' + mailbox), '/api/v1/messages/' + mailbox,
                      cursor_key='cursor', cursor=False, limit='25')
            page.one('.mailbox-pagination [role=status]', '1–25')

    languages = (page.language, 'ar' if page.language == 'en' else 'en')
    for language in languages:
        enter_language(language)
        check_outbox_receipts(page, nav, text, receipt_message, page_read)
    for language in languages:
        enter_language(language)
        check_mailbox_presentation(page, nav, text)
        check_connected_mailboxes(page, nav, text, PASSWORD)
        with page.check('outbox pagination and list refresh keep the submitted subject'):
            nav('navigation.outbox')
            endpoint='/api/v1/messages/outbox'
            search=text('field.search')
            page.fill(search,'Mail paging fixture')
            page_read(lambda:page.click(search),endpoint,cursor_key='cursor',cursor=False,q='Mail paging fixture')
            page.fill(search,'unsubmitted-subject')
            page_read(lambda:page.click(text('action.next')),endpoint,cursor_key='cursor',cursor=True,q='Mail paging fixture')
            row = page.one('.mailbox-row-subject', 'Mail paging fixture 00')
            page.activate(row)
            heading = page.one('.mailbox-letter [role=heading]', 'Mail paging fixture 00')
            navigation = page.driver.execute_script('return [location.href, history.length, performance.timeOrigin]')
            started = len(page.events())
            refresh = page.one('.mailbox-list button', text('action.refresh'))
            page_read(lambda: page.activate(refresh), endpoint, cursor_key='cursor', cursor=True, q='Mail paging fixture')
            page.wait.until(lambda _: page.one('.mailbox-row-subject', 'Mail paging fixture 00').id != row.id)
            assert page.one('.mailbox-letter [role=heading]', 'Mail paging fixture 00').id == heading.id
            assert page.one('.mailbox-list [aria-current=true] .mailbox-row-subject', 'Mail paging fixture 00')
            assert page.driver.execute_script('return [location.href, history.length, performance.timeOrigin]') == navigation
            assert not any(e['path'].startswith(endpoint + '/') for e in page.events()[started:])
            page_read(lambda:page.click(text('action.previous')),endpoint,cursor_key='cursor',cursor=False,q='Mail paging fixture')
            assert page.field(search).get_attribute('value')=='unsubmitted-subject'
            page_read(lambda:page.click(search),endpoint,cursor_key='cursor',cursor=False,q='unsubmitted-subject')
            page.see(text('state.empty'))

        with page.check('inbox pagination keeps the submitted read filter'):
            nav('navigation.inbox')
            endpoint='/api/v1/messages/inbox'
            page.see('Mail paging fixture 26')
            page.activate(page.one('button[aria-controls=mailbox-filters]'))
            filter_heights = page.driver.execute_script('''
                return [...document.querySelectorAll('#mailbox-filters .q-field__control')]
                    .map(control => control.getBoundingClientRect().height);
            ''')
            assert len(filter_heights) >= 7 and max(filter_heights) - min(filter_heights) <= 1, filter_heights
            field = page.field(text('field.read'))
            page.activate(field)
            page.activate(page.wait.until(lambda _:next(
                (option for option in page.visible('[role=option]') if plain(option.text)==text('field.read')), False,
            )))
            page_read(lambda:page.click(text('action.next')),endpoint,cursor_key='cursor',cursor=True,is_read=None)
            page_read(lambda:page.click(text('action.apply_filters')),endpoint,cursor_key='cursor',cursor=False,is_read='true')

        with page.check('draft pagination keeps the submitted recipient'):
            nav('navigation.drafts')
            endpoint='/api/v1/messages/drafts'
            page.see('Draft paging fixture 26')
            page.activate(page.one('button[aria-controls=mailbox-filters]'))
            field = page.field(text('field.recipient'))
            page.activate(field)
            field.send_keys('Test officer')
            page.activate(page.wait.until(lambda _:next((
                option for option in page.visible('[role=option]')
                if 'Test officer' in plain(option.text) and text('field.user') in plain(option.text)
            ), False)))
            page_read(lambda:page.click(text('action.next')),endpoint,cursor_key='cursor',cursor=True,recipient_id=None)
            page_read(lambda:page.click(text('action.apply_filters')),endpoint,cursor_key='cursor',cursor=False,recipient_id=str(officer_id))
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

        with page.check('all mailboxes submit subject, message body and linked content together'):
            for folder in ('inbox', 'outbox', 'drafts'):
                nav('navigation.' + folder)
                page.activate(page.one('button[aria-controls=mailbox-filters]'))
                page.fill(text('field.search'), 'Mailbox subject')
                page.fill(text('field.search_body'), 'Visible paragraph')
                page.fill(text('field.search_linked_content'), 'Indexed phrase')
                endpoint = f'/api/v1/messages/{folder}'
                page_read(lambda: page.click(text('action.apply_filters')), endpoint, cursor_key='cursor',
                          cursor=False, q='Mailbox subject', body_q='Visible paragraph', linked_q='Indexed phrase')
                page.see(text('state.empty'))
                page.activate(page.one('button[aria-controls=mailbox-filters]'))
                clear = page.one('button.mailbox-clear-filters', text('action.clear_filters'))
                page_read(lambda: page.activate(clear), endpoint, cursor_key='cursor',
                          cursor=False, q=None, body_q=None, linked_q=None)
                page.wait.until(lambda _: not clear.is_enabled())
                assert page.field(text('field.search')).get_attribute('value') == ''
            page.errors()
    return officer_id


def seed_outbox_receipts(page, officer, admin, officer_id):
    from datetime import date, timedelta

    path = '/api/v1/messages'
    targets = page.api.get(path + '/recipients/user', params={'q': 'Receipt test recipient', 'limit': 3})
    targets.raise_for_status()
    ids = sorted(row['id'] for row in targets.json()['items'])
    assert len(ids) == 3
    subject = 'Outbox receipt acceptance'
    original = page.api.post(path + '/send', json={
        'request_id': str(uuid4()), 'subject': subject, 'body_rich_text': '<p>Please confirm the review.</p>',
        'action_required': True, 'action_due_date': (date.today() + timedelta(days=2)).isoformat(),
        'read_receipt_requested': True,
        'selectors': [
            {'selector_kind': 'user', 'target_id': target, 'recipient_type': 'to' if i < 2 else 'cc'}
            for i, target in enumerate([officer_id, *ids])
        ],
    })
    original.raise_for_status()
    original = original.json()
    delivery = next(row['id'] for row in original['deliveries'] if row['recipient_user_id'] == officer_id)
    officer.post(path + '/inbox/' + delivery + '/read').raise_for_status()
    officer.post(path + '/send', json={
        'request_id': str(uuid4()), 'subject': 'Receipt acceptance completed', 'body_rich_text': '<p>Done.</p>',
        'relationship_kind': 'reply', 'related_delivery_id': delivery, 'complete_action': True,
        'selectors': [{'selector_kind': 'user', 'target_id': admin, 'recipient_type': 'to'}],
    }).raise_for_status()
    return {'subject': subject, 'path': path + '/outbox/' + original['envelope_id'], 'next': ids[1]}


def assert_pane_heading_font_matches(page, pane):
    heading = page.one('.mailbox-pane-title', scope=pane)
    list_heading = page.one('.mailbox-list .mailbox-pane-title')
    for property_name in ('font-family', 'font-size', 'font-weight'):
        assert heading.value_of_css_property(property_name) == list_heading.value_of_css_property(property_name), property_name


def check_outbox_receipts(page, nav, text, message, page_read):
    def label(key, **parameters):
        return text('outbox.' + key).format(**parameters)

    with page.check('Outbox receipt counts, status rows and navigation match the prototype'):
        nav('navigation.outbox')
        row = page.one('.mailbox-row-subject', message['subject'])
        message_row = row.find_element(By.XPATH, './ancestor::*[contains(@class, "mailbox-message-row")]')
        security_badge = plain(page.one('.mailbox-security-level', scope=message_row).text)
        started = len(page.events())
        page.activate(row)
        reader = page.one('.mailbox-outbox')
        assert_pane_heading_font_matches(page, reader)
        section = page.one('.mailbox-receipts', scope=reader)
        disclosure = page.one('[aria-expanded=false]', scope=section)
        counts = page.one('.mailbox-receipt-counts', scope=disclosure)
        for key, params in (
            ('delivered_count', {'count': 4}), ('read_count', {'count': 1}),
            ('completed_count', {'completed': 1, 'total': 2}),
        ):
            assert plain(label(key, **params)) in plain(counts.text)
        assert not any(event['path'] == message['path'] + '/recipients' for event in page.events()[started:])
        cells = page.one('.mailbox-headers', scope=reader).find_elements(By.XPATH, './*')
        assert len(cells) == 6 and float(cells[0].value_of_css_property('font-size').removesuffix('px')) \
            < float(cells[1].value_of_css_property('font-size').removesuffix('px'))
        assert security_badge == plain(cells[-1].text).rsplit(' · ', 1)[0]
        banner = page.one('.mailbox-action-summary', scope=reader)
        assert text('state.outstanding') in plain(banner.text)
        assert page.button(text('action.amend'), banner).is_displayed()
        page.capture('messaging-receipts-collapsed-' + page.language, target=reader)

        endpoint = message['path'] + '/recipients'
        page_read(lambda: page.activate(disclosure), endpoint, cursor_key='after', cursor=True, limit='3', after='0')
        page.one('[role=status]', label('recipient_range', first=1, last=3, total=4), section)
        first_page = page.one('ul', scope=section).find_elements(By.TAG_NAME, 'li')
        assert len(first_page) == 3
        delivery_prefix = label('receipt_delivered_at', time='').strip()
        assert all(plain(page.one('.mailbox-recipient-delivery', scope=row).text).startswith(delivery_prefix)
                   for row in first_page)
        assert text('state.completed') in plain(page.one('.mailbox-badge--done', scope=first_page[0]).text)
        assert label('receipt_read_at', time='').strip() in plain(first_page[0].text)
        assert text('field.cc') in plain(first_page[-1].text)
        name = page.one('.mailbox-recipient-name', scope=first_page[0])
        details = page.one('.mailbox-recipient-details', scope=first_page[0])
        assert name.rect['y'] < details.rect['y']
        previous = page.button(label('previous_recipients'), section)
        following = page.button(label('next_recipients'), section)
        assert not previous.is_enabled() and following.is_enabled()
        assert following.find_element(By.CLASS_NAME, 'q-icon').value_of_css_property('transform') == (
            'matrix(-1, 0, 0, 1, 0, 0)' if page.language == 'ar' else 'none'
        )
        page_read(lambda: page.activate(following), endpoint, cursor_key='after', cursor=True, limit='3',
                  after=str(message['next']))
        page.one('[role=status]', label('recipient_range', first=4, last=4, total=4), section)
        assert plain(page.one('.mailbox-recipient-delivery', scope=section).text).startswith(delivery_prefix)
        assert previous.is_enabled() and not following.is_enabled()
        page_read(lambda: page.activate(previous), endpoint, cursor_key='after', cursor=True, limit='3', after='0')
        page.one('[role=status]', label('recipient_range', first=1, last=3, total=4), section)
        page.capture('messaging-receipts-expanded-' + page.language, target=reader)
        page.click(label('open_completion_reply'), section)
        dialog = page.one('[role=dialog]')
        page.one('[role=heading]', 'Receipt acceptance completed', dialog)
        page.click(page.t('messaging.live.close'), dialog)
        capture_phone_pane(page, reader, 'messaging-receipts-narrow')
        page.activate(page.one('.mailbox-row-subject', 'Mail paging fixture 26'))
        page.one('.mailbox-outbox [role=heading]', 'Mail paging fixture 26')
        section = page.one('.mailbox-receipts')
        page.activate(page.one('[aria-expanded=false]', scope=section))
        assert plain(page.one('.mailbox-recipient-delivery', scope=section).text).startswith(delivery_prefix)
        assert label('receipt_read_at', time='').strip() not in plain(section.text)
        assert text('field.unread') not in plain(section.text)
        page.errors()


def capture_phone_pane(page, pane, name):
    if page.args.browser not in {'chrome', 'edge'}:
        return
    from tools.webui_browser_shell import record_resize_notifications

    # The existing desktop drawer reserves 300px when expanded.
    desktop_width = page.driver.execute_script('return innerWidth')
    page.activate(page.one('.erms-drawer-toggle'))
    page.one('.erms-drawer--collapsed')
    page.driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
        'width': 390, 'height': 820, 'deviceScaleFactor': 1, 'mobile': False,
    })
    try:
        page.wait.until(lambda _: page.driver.execute_script(
            '''return innerWidth === 390 && arguments[0].clientWidth > 200 &&
               arguments[0].scrollWidth <= arguments[0].clientWidth + 1''', pane,
        ))
        page.capture(name + '-' + page.language, target=pane)
    finally:
        page.driver.execute_cdp_cmd('Emulation.clearDeviceMetricsOverride', {})
        page.wait.until(lambda _: page.driver.execute_script('return innerWidth') == desktop_width)
        # The toggle moves as Quasar repositions the drawer after the resize.
        page.one('.erms-drawer-toggle').send_keys(Keys.ENTER)
        page.wait.until(lambda _: not page.visible('.erms-drawer--collapsed'))
    record_resize_notifications(page)


def check_mailbox_presentation(page, nav, text):
    with page.check('sidebar mailbox navigation and Compose survive an account profile refresh'):
        nav('navigation.inbox')
        page.see('Mail paging fixture 26')
        start = len(page.events())
        profile_trigger = page.one('header button[data-inspector-ignore=true]')
        page.activate(profile_trigger)
        page.one('.erms-profile-menu')
        page.wait.until(lambda _: any(
            event['path'] == '/api/v1/auth/me' and event['status'] == 200
            for event in page.events()[start:]
        ))
        if page.visible('.erms-profile-menu'):
            page.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
        page.wait.until(lambda _: not page.visible('.erms-profile-menu'))
        page.click(text('action.compose'))
        dialog = page.one('[role=dialog]')
        page.field(text('field.subject'))
        page.click(text('action.cancel'), dialog)
        page.wait.until(lambda _: not page.visible('[role=dialog]'))
        for folder in ('outbox', 'drafts', 'inbox'):
            nav('navigation.' + folder)
            assert not page.visible('.messaging-workspace nav')

    with page.check('mailbox colors, selected edge, unread state, reading pane, retention, and pager'):
        subject = 'Mail paging fixture 25' if page.language == 'en' else 'Mail paging fixture 26'
        row = page.wait.until(
            lambda _: next((r for r in page.visible('.mailbox-message-row') if subject in plain(r.text)), False)
        )

        row_styles = """
            const row = arguments[0], style = getComputedStyle(row);
            const dot = getComputedStyle(row.querySelector('.mailbox-row-dot'));
            const subject = getComputedStyle(row.querySelector('.mailbox-row-subject'));
            const warning = getComputedStyle(row.querySelector('.mailbox-badge--warning'));
            return {edge:style.borderInlineStartColor, width:style.borderInlineStartWidth,
                    physical:style.direction === 'rtl' ? style.borderRightColor : style.borderLeftColor,
                    opposite:style.direction === 'rtl' ? style.borderLeftColor : style.borderRightColor,
                    background:style.backgroundColor, dot:dot.backgroundColor,
                    weight:Number(subject.fontWeight), warning:warning.backgroundColor};
        """
        unread = page.driver.execute_script(row_styles, row)
        assert row.get_attribute('data-unread') == 'true'
        assert unread['dot'] != 'rgba(0, 0, 0, 0)' and unread['weight'] == 700
        assert unread['warning'] == 'rgb(255, 245, 228)', unread
        security_badge = plain(page.one('.mailbox-security-level', scope=row).text)
        assert [plain(badge.text) for badge in page.visible('.mailbox-badge--warning', row)] == [text('priority.high')]
        assert text('field.expiry') not in plain(page.one('.mailbox-list').text)
        page.activate(row)
        reader = page.one('.mailbox-letter')
        page.one('[role=heading]', subject, reader)
        assert row.get_attribute('aria-current') == 'true' and row.get_attribute('data-unread') == 'false'
        read = page.driver.execute_script(row_styles, row)
        assert read['width'] == '3px' and read['edge'] == read['physical'] == unread['dot'], read
        assert read['edge'] != read['opposite'] and read['background'] == 'rgb(229, 241, 253)', read
        assert read['dot'] == 'rgba(0, 0, 0, 0)' and read['weight'] < unread['weight']
        page.one('.mailbox-byline .q-avatar', scope=reader)
        headers = page.one('.mailbox-headers', scope=reader)
        assert [plain(label.text) for label in page.visible('.mailbox-header-label', headers)] == [
            text('field.to'), text('outbox.security'),
        ]
        security_value = page.visible('.mailbox-header-value', headers)[-1]
        assert security_badge == plain(security_value.text).rsplit(' · ', 1)[0]
        style = page.driver.execute_script('''
            const headers = arguments[0];
            return Array.from(headers.querySelectorAll('.mailbox-header-label')).map(label => {
              const value = label.nextElementSibling;
              const a = getComputedStyle(label), b = getComputedStyle(value);
              return parseFloat(a.fontSize) < parseFloat(b.fontSize) &&
                Number(a.fontWeight) > Number(b.fontWeight) && a.color !== b.color;
            });
        ''', headers)
        assert style == [True, True]
        assert page.one('.mailbox-byline', scope=reader).rect['y'] < headers.rect['y']
        page.one('.mailbox-letter-body', scope=reader)
        assert text('field.expiry') in plain(reader.text)
        toolbar = page.one('.mailbox-reader-toolbar', scope=reader)
        assert_pane_heading_font_matches(page, toolbar)
        assert toolbar.rect['y'] < page.one('[role=heading]', subject, reader).rect['y']
        assert toolbar.value_of_css_property('background-color') == page.one(
            '.mailbox-list > .nicegui-row:first-child'
        ).value_of_css_property('background-color')
        pager = page.one('.mailbox-list > .mailbox-pagination')
        page_range = page.one('[role=status]', scope=pager)
        assert plain(page_range.text) == '1–25' and page_range.value_of_css_property('direction') == 'ltr'
        previous = page.one('button.mailbox-page-button', text('action.previous'), pager)
        next_button = page.one('button.mailbox-page-button', text('action.next'), pager)
        assert not previous.is_enabled() and next_button.is_enabled()
        assert 'chevron_left' in previous.text and 'chevron_right' in next_button.text
        assert page.driver.execute_script("return getComputedStyle(arguments[0].querySelector('.q-icon')).transform", next_button) == (
            'matrix(-1, 0, 0, 1, 0, 0)' if page.language == 'ar' else 'none'
        )
        page.capture('messaging-fidelity-inbox-' + page.language)
        capture_phone_pane(page, reader, 'messaging-fidelity-inbox-narrow')
        page.errors()


def check_connected_mailboxes(page, nav, text, password):
    import httpx

    def folder_button(folder):
        return page.one('button.erms-nav-link', text('navigation.' + folder))
    subject = "Browser messaging redesign workflow " + page.language
    editor_selector = '[contenteditable=true]'

    def matching_rows(value):
        return [row for row in page.visible('.mailbox-columns [role=button].cursor-pointer')
                if value in plain(row.text)]

    def select_row(value, *, replaced=None):
        return page.wait.until(lambda _: next((
            row for row in matching_rows(value) if row.id != replaced
        ), False))

    def recipient():
        field = page.field(text('field.to'))
        page.activate(field)
        field.send_keys('Test officer')
        page.activate(page.wait.until(lambda _: next((
            option for option in page.visible('[role=option]')
            if 'Test officer' in plain(option.text) and option.get_attribute('aria-disabled') != 'true'
        ), False)))

    def fill_message(value):
        page.fill(text('field.subject'), value)
        editor = page.one(editor_selector)
        page.activate(editor)
        type_multiline_body(editor)

    page.wait.until(lambda _: not page.visible('.q-notification'))
    with page.check('compose, save, open draft, send, open filtered Outbox and verify delivery'):
        nav('navigation.outbox')
        page.fill(text('field.search'), 'Mail paging fixture')
        page.click(text('field.search'))
        page.see('Mail paging fixture 26')
        page.click(text('action.next'))
        page.see('Mail paging fixture 00')
        nav('navigation.inbox')
        page.click(text('action.compose'))
        compose = page.one('.mailbox-compose-dialog')
        page.wait.until(lambda _: abs(compose.rect['width'] - 840) <= 1)
        fill_message(subject)
        recipient()
        chip = page.one('.mailbox-compose-address .q-chip__content > .ellipsis', scope=compose)
        assert 'Test officer' in plain(chip.text)
        assert chip.value_of_css_property('white-space') == 'normal'
        page.click(text('action.save_draft'))
        page.click(text('action.open_draft'))
        assert page.field(text('field.subject')).get_attribute('value') == subject
        assert not page.visible('[role=dialog]')
        draft_editor = page.one('.mailbox-draft-editor')
        assert_pane_heading_font_matches(page, draft_editor)
        page.one('[role=heading]', text('section.edit_draft'), draft_editor)
        assert page.one('.mailbox-draft-heading', scope=draft_editor).rect['y'] < page.field(text('field.subject')).rect['y']
        labels = page.visible('.mailbox-draft-field.q-field--float .q-field__label > div', draft_editor)
        for key in ('field.to', 'field.cc', 'outbox.security'):
            label = next((entry for entry in labels if plain(entry.text) == text(key)), None)
            assert label is not None and label.value_of_css_property('font-weight') == '600', key
        page.one('.mailbox-draft-footer', scope=draft_editor)
        page.capture('messaging-fidelity-draft-' + page.language)
        capture_phone_pane(page, draft_editor, 'messaging-fidelity-draft-narrow')
        assert_multiline_body(page.one(editor_selector))
        page.fill(text('field.subject'), subject + ' edited')
        send = page.button(text('action.send'))
        page.wait.until(lambda _: send.is_enabled())
        page.activate(send)
        feedback = page.one('.mailbox-send-feedback')
        page.one('[role=status]', text('state.sent'), feedback)
        page.button(text('live.close'), feedback)
        assert feedback.find_element(By.XPATH, 'ancestor::*[contains(@class, "q-page-sticky")][1]')
        page.click(text('action.view_sent'), feedback)
        page.see(subject + ' edited')
        assert_multiline_body(page.one('.mailbox-letter-body'))
        for folder in ('inbox', 'outbox', 'drafts'):
            assert folder_button(folder).is_displayed()
        assert page.field(text('field.search')).get_attribute('value') == 'Mail paging fixture'
        assert page.button(text('action.previous')).is_enabled()
        with httpx.Client(base_url=page.args.api, trust_env=False, timeout=20) as officer:
            officer.post('/api/v1/auth/login', json={'email': 'officer@test.invalid', 'password': password}).raise_for_status()
            inbox = officer.get('/api/v1/messages/inbox', params={'limit': 1})
            inbox.raise_for_status()
            assert inbox.json()['items'][0]['subject'] == subject + ' edited'
        page.wait.until(lambda _: page.driver.execute_script(
            "return document.activeElement.getAttribute('role')"
        ) == "heading")
        compare_mailbox_layout(page, subject + ' edited')
        page.errors()
    if page.language == 'en':
        with page.check('forward and follow-up send new linked content from Outbox'):
            root = next(row for row in page.api.get('/api/v1/messages/outbox').json()['items']
                        if row['subject'] == subject + ' edited')
            for relation, action in (('forward', 'action.forward'), ('follow-up', 'action.follow_up')):
                page.click(text(action))
                assert page.field(text('field.subject')).get_attribute('value') == ''
                assert not page.one(editor_selector).text.strip()
                assert page.field(text('field.to')).get_attribute('value') == ''
                new_subject = f'{subject} {relation}'
                fill_message(new_subject)
                recipient()
                send = page.button(text('action.send'))
                page.wait.until(lambda _: send.is_enabled())
                page.activate(send)
                page.click(text('action.view_sent'))
                page.see(new_subject)
                sent = page.api.get('/api/v1/messages/outbox', params={'limit': 1}).json()['items'][0]
                assert sent['subject'] == new_subject
                detail = page.api.get(f"/api/v1/messages/outbox/{sent['id']}")
                detail.raise_for_status()
                assert detail.json()['linked_envelope_id'] == root['id']
                page.click(text('action.open_original'))
                dialog = page.one('[role=dialog]')
                page.wait.until(lambda _: subject + ' edited' in plain(dialog.text))
                page.click(text('live.close'), dialog)
                page.wait.until(lambda _: not page.visible('[role=dialog]'))
                page.wait.until(lambda _: not page.visible('.q-notification'))
                page.fill(text('field.search'), subject + ' edited')
                previous_row = next(iter(matching_rows(subject + ' edited')), None)
                page.click(text('field.search'))
                page.activate(select_row(subject + ' edited', replaced=previous_row.id if previous_row else None))
                page.one('.mailbox-columns [role=heading]', subject + ' edited')
            page.errors()

        with page.check('Reply draft preserves completion and acknowledges the original action on send'):
            from uuid import uuid4

            admin_id = page.api.get('/api/v1/auth/me').json()['user']['id']
            original_subject = subject + ' action'
            with httpx.Client(base_url=page.args.api, trust_env=False, timeout=20) as officer:
                officer.post('/api/v1/auth/login', json={'email': 'officer@test.invalid', 'password': password}).raise_for_status()
                officer.headers['X-CSRF-Token'] = officer.cookies['erms_csrf']
                response = officer.post('/api/v1/messages/send', json={
                    'request_id': str(uuid4()), 'subject': original_subject,
                    'body_rich_text': '<p>Please verify this action.</p>', 'action_required': True,
                    'selectors': [{'selector_kind': 'user', 'target_id': admin_id, 'recipient_type': 'to'}],
                })
                response.raise_for_status()
                delivery_id = response.json()['deliveries'][0]['id']
            nav('navigation.inbox')
            page.wait.until(lambda _: not page.visible('.q-notification'))
            row = select_row(original_subject)
            row.send_keys(Keys.SPACE)
            reader = page.one('.mailbox-letter')
            pane = page.one('.mailbox-action-summary', scope=reader)
            assert text('state.outstanding') in plain(pane.text)
            assert text('outbox.no_due_date') in plain(pane.text)
            page.one('.mailbox-letter-disclosure [aria-expanded=false]', text('section.action_history'), reader)
            page.click(text('action.reply'))
            reply_subject = page.field(text('field.subject')).get_attribute('value')
            assert reply_subject == 'Re: ' + original_subject
            editor = page.one(editor_selector)
            page.activate(editor)
            editor.send_keys('Verified and complete.')
            check = page.one('[role=checkbox]', text('field.complete'))
            page.activate(check)
            page.wait.until(lambda _: check.get_attribute('aria-checked') == 'true')
            page.click(text('action.save_draft'))
            page.click(text('action.open_draft'))
            draft_editor = page.one('.mailbox-draft-editor')
            reopened = page.one('[role=checkbox]', text('field.complete'), draft_editor)
            assert reopened.get_attribute('aria-checked') == 'true'
            original_path = f'/api/v1/messages/inbox/{delivery_id}'
            started = len(page.events())
            page.click(text('action.open_original'), draft_editor)
            dialog = page.one('[role=dialog]')
            page.one('[role=heading]', original_subject, dialog)
            requests = [event for event in page.events()[started:] if event['path'].startswith(original_path)]
            assert [(event['method'], event['path']) for event in requests] == [('GET', original_path)]
            page.click(text('live.close'), dialog)
            page.wait.until(lambda _: not page.visible('[role=dialog]'))
            assert reopened.get_attribute('aria-checked') == 'true'
            status = page.api.get(original_path)
            status.raise_for_status()
            assert status.json()['action_status'] == 'outstanding'
            send = page.button(text('action.send'), draft_editor)
            page.wait.until(lambda _: send.is_enabled())
            page.activate(send)
            page.click(text('action.view_sent'))
            page.see(reply_subject)
            status = page.api.get(original_path)
            status.raise_for_status()
            assert status.json()['action_status'] == 'completed'
            page.errors()


def compare_mailbox_layout(page, subject):
    from tools.webui_browser_shell import record_resize_notifications, viewport

    page.errors()
    cols = page.one('.mailbox-columns')
    grid_positions = """
        const [list, pane] = arguments[0].children;
        const a=list.getBoundingClientRect(), b=pane.getBoundingClientRect();
        return {listX:a.left, paneX:b.left, listBottom:a.bottom, paneY:b.top,
                fits:arguments[0].scrollWidth <= arguments[0].clientWidth + 1};
    """
    layout = lambda: page.driver.execute_script(grid_positions, cols)
    desktop = layout()
    assert desktop['fits']
    assert (desktop['listX'] > desktop['paneX']) == (page.language == 'ar')
    page.capture('messaging-redesign-outbox-' + page.language)
    size = page.driver.execute_script('return [innerWidth, innerHeight]')
    try:
        viewport(page, 720, size[1])
        page.wait.until(lambda _: layout()['paneY'] >= layout()['listBottom'])
        assert layout()['fits']
        page.see(subject)
        page.capture('messaging-redesign-narrow-' + page.language, target=cols)
    finally:
        viewport(page, *size)
    record_resize_notifications(page)
