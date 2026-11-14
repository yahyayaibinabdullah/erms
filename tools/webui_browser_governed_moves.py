"""Governed Move regression: real dialogs, bounded search, preview and saved placement."""
import httpx
from selenium.webdriver.common.keys import Keys
from tools.check_webui_browser import PASSWORD, plain
from tools.webui_browser_application import settled


def check_governed_moves(page):
    def read(resource, identifier):
        response = page.api.get(f'/api/v1/{resource}/{identifier}')
        response.raise_for_status()
        return response.json()

    def create(resource, payload):
        response = page.api.post('/api/v1/' + resource, json=payload)
        response.raise_for_status()
        return response.json()

    response = page.api.post('/api/v1/aggregations/search', json={
        'where': {'field': 'aggregation_number', 'operator': 'eq', 'value': 'TEST-AGG'},
        'limit': 1, 'offset': 0})
    response.raise_for_status()
    root = response.json()['items'][0]
    # Put the destination beyond an initial 25-row page. Search must still find it.
    for index in range(26):
        create('aggregations', {'parent_aggregation_id': root['id'],
            'aggregation_number': f'GM-A-{index:02}', 'title': f'Decoy {index:02}',
            'medium': 'physical', 'date_opened': '2026-01-01T00:00:00Z'})
    target = create('aggregations', {'parent_aggregation_id': root['id'],
        'aggregation_number': 'GM-Z-DEST', 'title': 'Move destination',
        'medium': 'physical', 'date_opened': '2026-01-01T00:00:00Z'})
    mixed = create('aggregations', {'classification_id': root['classification_id'],
        'aggregation_number': 'GM-Z-MIXED', 'title': 'Mixed destination',
        'medium': 'mixed', 'date_opened': '2026-01-01T00:00:00Z'})
    digital = create('aggregations', {'classification_id': root['classification_id'],
        'aggregation_number': 'GM-Z-DIGITAL', 'title': 'Incompatible destination',
        'medium': 'digital', 'date_opened': '2026-01-01T00:00:00Z'})

    def dialog():
        return page.one('.q-dialog__inner > .q-card')

    def closed():
        page.wait.until(lambda _: not page.visible('.q-dialog__inner > .q-card'))

    def open_detail(resource, item):
        page.drawer(resource)
        page.wait.until(lambda _:len(page.visible('.dashboard-personal-panel')) == 2
                        and not page.visible('.dashboard-personal-panel .q-spinner'))
        page.fill(page.t('webui.index.input.search_by_number_title_or_description_e21ed520'),
                  item['aggregation_number' if resource == 'aggregations' else 'record_number'])
        page.click(page.t('webui.index.button.search_4d02b714'), page.one('.erms-shared-control.items-end'))
        page.activate(page.one(f'button[aria-label="Open {resource[:-1]}"]', scope=page.one('.compact-result-item')))
        page.wait.until(lambda _:item['title'] in page.one('.erms-breadcrumb-row [aria-current=page]').text)

    def open_move(resource):
        advanced_key = ('webui.open_aggregation.expansion.advanced_2d1fcc81' if resource == 'aggregations'
                        else 'webui.select_record_details.expansion.advanced_73101adb')
        header = page.wait.until(lambda _:next((e for e in page.visible('.q-expansion-item__container > .q-item')
                      if page.t(advanced_key) in e.text), False))
        if header.get_attribute('aria-expanded') != 'true':
            page.activate(header)
        key = ('webui.open_aggregation.button.move_aeafbea8' if resource == 'aggregations'
               else 'webui.select_record_details.button.move_d812404c')
        page.click(page.t(key))
        expected = {
            ('en', 'aggregations'): 'Move aggregation', ('en', 'records'): 'Move record',
            ('ar', 'aggregations'): 'نقل ملف', ('ar', 'records'): 'نقل وثيقة',
        }[page.language, resource]
        page.wait.until(lambda _:plain(page.one('.text-xl', scope=dialog()).text) == expected)
        page.report.setdefault('move_titles', []).append({
            'resource': resource, 'language': page.language, 'title': expected})
        return dialog()

    def check_preview(resource):
        key = 'webui.refresh_preview.label.subtree_get_aggregations_get_2_records_e9a4c3b8'
        if resource == 'aggregations':
            expected = page.t(key).format(get=1, get_2=2)
            page.wait.until(lambda _:expected in plain(dialog().text))
            page.report.setdefault('subtree_previews', []).append({
                'language': page.language, 'aggregations': 1, 'records': 2, 'text': expected})
        else:
            assert 'Subtree:' not in dialog().text and 'الشجرة الفرعية' not in dialog().text

    def search_destination(query):
        field = page.field(page.t('webui.show_governed_move.select.destination_aggregation_622d5aa3'))
        # Real native typing; one replacement avoids intermediate debounce queries.
        page.activate(field)
        field.send_keys(Keys.COMMAND, 'a', Keys.NULL)
        field.send_keys(query if query else Keys.BACKSPACE)
        settled(page)
        return field

    def empty_message():
        return page.t('webui.show_governed_move.label.no_compatible_destination_aggregation_is_c_7999f980')

    def move_writes():
        return [e for e in page.events() if e['method'] == 'POST' and e['path'].endswith('/acl-move')]

    def grants(acl):
        return sorted((g['principal_type'], g.get('role_id') or 0,
                       tuple(sorted(g['permission_codes']))) for g in acl['effective_acl'])

    for language in ('en', 'ar'):
        if language == 'ar':
            page.settings()
            page.language_change('ar')
        aggregation = create('aggregations', {'parent_aggregation_id': root['id'],
            'aggregation_number': f'GM-SOURCE-{language}', 'title': f'Moving aggregation {language}',
            'medium': 'physical', 'date_opened': '2026-01-01T00:00:00Z'})
        nested = create('aggregations', {'parent_aggregation_id': aggregation['id'],
            'aggregation_number': f'GM-NESTED-{language}', 'title': f'Nested aggregation {language}',
            'medium': 'physical', 'date_opened': '2026-01-01T00:00:00Z'})
        nested_records = [create('records', {'aggregation_id': nested['id'],
            'record_number': f'GM-NESTED-RECORD-{language}-{index}',
            'title': f'Nested record {language} {index}', 'medium': 'physical',
            'date_originated': '2026-01-01T00:00:00Z'}) for index in range(2)]
        record = create('records', {'aggregation_id': root['id'],
            'record_number': f'GM-RECORD-{language}', 'title': f'Moving record {language}',
            'medium': 'physical', 'date_originated': '2026-01-01T00:00:00Z'})
        for resource, item in [('aggregations', aggregation), ('records', record)]:
            with page.check(f'{resource} move opens, validates, searches after empty results and cancels'):
                open_detail(resource, item)
                before = read(resource, item['id'])
                write_count = len(move_writes())
                open_move(resource)
                page.click(page.t('webui.show_governed_move.button.move_115a42b3'), dialog())
                page.see(page.t('webui.submit.notify.destination_and_reason_are_required_6216e905'))
                search_destination('definitely-no-destination')
                page.see(empty_message())
                field = search_destination(digital['aggregation_number'])
                page.wait.until(lambda _:not page.visible('[role=option]'))
                assert field.is_enabled()
                search_destination(target['aggregation_number'])
                option = page.one('[role=option]', target['aggregation_number'])
                page.activate(option)
                page.wait.until(lambda _:any(e['path'] == f'/api/v1/{resource}/{item["id"]}/acl-move-preview'
                                            and e['status'] == 200 for e in page.events()))
                page.wait.until(lambda _:empty_message() not in dialog().text)
                check_preview(resource)
                page.capture(f'move-{resource}-preview-{language}')
                page.click(page.t('webui.show_governed_move.button.cancel_ace0514f'), dialog())
                closed()
                assert len(move_writes()) == write_count
                assert read(resource, item['id'])['version'] == before['version']

            for keep in (False, True):
                destination = (target if resource == 'aggregations' else mixed) if not keep else root
                with page.check(f'{resource} committed move, keep access={keep}, fresh detail and reload'):
                    open_detail(resource, item)
                    before = read(resource, item['id'])
                    acl_response = page.api.get(f'/api/v1/{resource}/{item["id"]}/permissions')
                    acl_response.raise_for_status()
                    old_acl = acl_response.json()
                    assert old_acl['inherit_acl_from_parent']
                    open_move(resource)
                    preview_count = sum(e['path'].endswith('/acl-move-preview') for e in page.events())
                    search_destination(destination['aggregation_number'])
                    page.activate(page.one('[role=option]', destination['aggregation_number']))
                    page.wait.until(lambda _:sum(e['path'].endswith('/acl-move-preview') for e in page.events()) > preview_count)
                    if keep:
                        preview_count = sum(e['path'].endswith('/acl-move-preview') for e in page.events())
                        page.activate(page.one('[role=checkbox]', scope=dialog()))
                        page.wait.until(lambda _:sum(e['path'].endswith('/acl-move-preview') for e in page.events()) > preview_count)
                    check_preview(resource)
                    reason = f'Browser {language} {resource} keep={keep}'
                    page.fill(page.t('webui.show_governed_move.textarea.reason_bfc77d50'), reason)
                    page.click(page.t('webui.show_governed_move.button.move_115a42b3'), dialog())
                    closed()
                    parent_key = 'parent_aggregation_id' if resource == 'aggregations' else 'aggregation_id'
                    page.wait.until(lambda _:read(resource, item['id'])[parent_key] == destination['id'])
                    page.wait.until(lambda _:item['title'] in page.one('.erms-breadcrumb-row [aria-current=page]').text)
                    current = read(resource, item['id'])
                    assert current['version'] > before['version']
                    assert all(current[key] == before[key] for key in ('id', 'title', 'medium'))
                    acl_response = page.api.get(f'/api/v1/{resource}/{item["id"]}/permissions')
                    acl_response.raise_for_status()
                    acl = acl_response.json()
                    assert acl['inherit_acl_from_parent'] == (not keep)
                    if keep:
                        assert grants(acl) == grants(old_acl)
                    if resource == 'aggregations':
                        assert read('aggregations', nested['id'])['parent_aggregation_id'] == item['id']
                        assert all(read('records', child['id'])['aggregation_id'] == nested['id']
                                   for child in nested_records)
                    page.wait.until(lambda _:any(destination['aggregation_number'] in b.text
                                                for b in page.visible('button.detail-linked-entity')))
                    page.driver.refresh()
                    page.wait.until(lambda _:item['title'] in page.one('.erms-breadcrumb-row [aria-current=page]').text)
                    page.wait.until(lambda _:any(destination['aggregation_number'] in b.text
                                                for b in page.visible('button.detail-linked-entity')))
                    page.capture(f'move-{resource}-saved-{language}-{keep}')
                    page.errors()
                    page.report.setdefault('moves', []).append({'resource': resource, 'language': language,
                        'keep_access': keep, 'id': item['id'], 'destination': destination['id'],
                        'before_version': before['version'], 'after_version': current['version'],
                        'inherit_acl_from_parent': acl['inherit_acl_from_parent']})
    denied_paths = []
    with page.check('unauthorized move preview conceals both resource types'):
        with httpx.Client(base_url=page.args.api, trust_env=False, timeout=20) as viewer:
            response = viewer.post('/api/v1/auth/login', json={'email':'viewer@test.invalid', 'password':PASSWORD})
            response.raise_for_status()
            for resource, item in [('aggregations', aggregation), ('records', record)]:
                denied = viewer.get(f'/api/v1/{resource}/{item["id"]}/acl-move-preview',
                                    params={'destination_aggregation_id': target['id']})
                assert denied.status_code == 404, denied.text
                denied_paths.append(f'/api/v1/{resource}/{item["id"]}/acl-move-preview')
    assert not [e for e in page.events() if e['method'] == 'GET' and e['path'] == '/api/v1/aggregations']
    assert len(move_writes()) == 8
    assert all(e['status'] == 200 for e in move_writes())
    failures = [e for e in page.events() if e['status'] is None or e['status'] >= 400]
    assert len(failures) == 2 and {e['path'] for e in failures} == set(denied_paths)
    assert all(e['method'] == 'GET' and e['status'] == 404 for e in failures)
    page.report['expected_denied_previews'] = failures
