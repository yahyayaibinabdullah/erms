"""Cross-screen cache ownership and exact cached/uncached search parity."""
import os
from uuid import uuid4

import psycopg
import pytest

from .test_full_text_search_phase3 import _grant_phase3_privileges, _upload, _publish_component


@pytest.fixture(autouse=True)
def enabled(client, clean_database):
    _grant_phase3_privileges()
    from .test_application_settings import save
    assert save(client, {'FULL_TEXT_SEARCH_ENABLED': True}).status_code == 200


def post(client, path, payload):
    response = client.post('/api/v1/' + path, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def slots():
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        return connection.execute('SELECT tab_id,search_id FROM search_results_cache ORDER BY tab_id').fetchall()


@pytest.mark.parametrize('resource', ['records', 'aggregations'])
@pytest.mark.parametrize('criteria', ['structured', 'metadata', 'combined', 'nested', 'negative'])
def test_cached_search_preserves_results_sort_and_scores(client, record, resource, criteria):
    _grant_phase3_privileges()
    _publish_component(_upload(client, record))
    structured = {'field': 'id', 'operator': 'gt', 'value': 0}
    leaf = {'full_text': {'query': 'record OR aggregation OR budget', 'sources': ['metadata']}}
    if criteria == 'combined' and resource == 'records':
        leaf['full_text']['sources'].append('components')
    where = {'structured': structured, 'metadata': leaf, 'combined': leaf,
             'nested': {'or': [structured, {'and': [leaf, {'not': {'field': 'id', 'operator': 'lt', 'value': 0}}]}]},
             'negative': {'and': [structured, {'not': {'full_text': {'query': 'absenttoken'}}}]}}[criteria]
    payload = {'where': where, 'sort': [] if criteria in {'metadata', 'combined'} else
               [{'field': 'title', 'direction': 'desc'}], 'limit': 1}
    if criteria not in ('structured', 'negative'):
        payload['include'] = ['full_text_matches']
    expected = post(client, resource + '/search', payload)
    cached = post(client, resource + '/search', {**payload, 'tab_id': str(uuid4())})
    for item in cached['items']:
        item.pop('_capabilities', None)
    assert cached['items'] == expected['items']
    assert cached['total'] == expected['total']
    assert len(slots()) == 1


def test_one_slot_shared_across_screens_rebuilds_expired_or_replaced_page(client, record):
    _grant_phase3_privileges()
    tab = str(uuid4())
    global_payload = {'result_types': ['records'], 'record_where': {'full_text': {'query': 'record'}}, 'tab_id': tab}
    first = post(client, 'full-text-search', global_payload)
    payload = {'tab_id': tab, 'where': {'field': 'id', 'operator': 'gt', 'value': 0}, 'limit': 1}
    advanced = post(client, 'records/advanced-search', payload)
    aggregation = post(client, 'aggregations/search', payload)
    assert len(slots()) == 1 and str(slots()[0][1]) == aggregation['search_id']
    returned = post(client, 'records/advanced-search', {**payload, 'search_id': advanced['search_id'], 'offset': 100})
    assert returned['search_id'] != advanced['search_id']
    assert returned['offset'] == 0 and returned['items'][0]['id'] == record['id']
    continued = post(client, 'records/advanced-search', {**payload, 'search_id': returned['search_id']})
    assert continued['search_id'] == returned['search_id']
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute('UPDATE search_results_cache SET expires_at=clock_timestamp()')
    expired = post(client, 'records/advanced-search', {**payload, 'search_id': continued['search_id']})
    assert expired['search_id'] != continued['search_id']
    # A copied token in another tab never fetches the original slot.
    other = post(client, 'records/advanced-search', {**payload, 'tab_id': str(uuid4()), 'search_id': expired['search_id']})
    assert other['search_id'] != expired['search_id'] and len(slots()) == 2
    assert client.post('/api/v1/full-text-search', json={**global_payload, 'search_id': first['search_id']}).status_code == 410


def test_filtered_search_uses_admin_cap_and_rechecks_permissions(client, record):
    _grant_phase3_privileges()
    from .test_application_settings import save
    assert save(client, {'SEARCH_RESULT_LIMIT': 1}).status_code == 200
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute('''INSERT INTO records(record_number,title,aggregation_id,owning_org_unit_id,security_level_id)
            SELECT 'OTHER','Other',aggregation_id,owning_org_unit_id,security_level_id FROM records WHERE id=%s''', (record['id'],))
    payload = {'tab_id': str(uuid4()), 'limit': 10}
    first = post(client, 'records/search', payload)
    assert first['total'] == 1 and first['truncated'] is True and first['result_cap'] == 1
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute("DELETE FROM user_role_assignments WHERE user_id=1")
    denied = post(client, 'records/search', {**payload, 'search_id': first['search_id']})
    assert denied['items'] == [] and denied['total'] == 0
    assert denied['search_id'] == first['search_id']


def test_fingerprint_blocks_reuse_with_different_criteria_sort_or_endpoint(client, record):
    tab = str(uuid4())
    base = {'tab_id': tab, 'where': {'field': 'id', 'operator': 'gt', 'value': 0}}
    original = post(client, 'records/search', base)
    changed = post(client, 'records/search', {**base, 'search_id': original['search_id'],
                    'where': {'field': 'id', 'operator': 'lt', 'value': 0}})
    assert changed['items'] == [] and changed['search_id'] != original['search_id']
    different_endpoint = post(client, 'records/advanced-search', {**base, 'search_id': changed['search_id']})
    assert different_endpoint['items'][0]['id'] == record['id']
    assert different_endpoint['search_id'] != changed['search_id'] and len(slots()) == 1
    sorted_again = post(client, 'records/advanced-search', {**base, 'search_id': different_endpoint['search_id'],
                        'sort': [{'field': 'id', 'direction': 'desc'}]})
    assert sorted_again['search_id'] != different_endpoint['search_id']


def test_saved_execution_shares_slot_but_checks_current_audience(client, record):
    from .test_saved_searches import _payload
    saved = client.post('/api/v1/saved-searches', json=_payload())
    assert saved.status_code == 201, saved.text
    identifier = saved.json()['id']
    tab = str(uuid4())
    body = {'tab_id': tab, 'limit': 25}
    first = post(client, f'saved-searches/{identifier}/execute', body)
    renamed = client.put(f'/api/v1/saved-searches/{identifier}', json=_payload(name='Renamed cached search'),
                         headers={'If-Match': str(saved.json()['version'])})
    assert renamed.status_code == 200, renamed.text
    revised = post(client, f'saved-searches/{identifier}/execute', {**body, 'search_id': first['search_id']})
    assert revised['search_id'] != first['search_id']  # Version alone invalidates an otherwise identical query.
    first = revised
    other = post(client, 'records/search', {'tab_id': tab})
    rebuilt = post(client, f'saved-searches/{identifier}/execute', {**body, 'search_id': first['search_id']})
    assert rebuilt['search_id'] not in {first['search_id'], other['search_id']}
    assert len(slots()) == 1
    definition = _payload()
    definition['definition']['request']['tab_id'] = tab
    assert client.post('/api/v1/saved-searches', json=definition).status_code == 422
    # Leave global privileges intact but remove governance and all resource ACLs.
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute("UPDATE roles SET is_information_governance=false WHERE code='system-administrator'")
        connection.execute('DELETE FROM record_acl_grants')
        connection.execute('DELETE FROM aggregation_child_record_acl_defaults')
    denied = post(client, 'records/search', {'tab_id': tab, 'search_id': other['search_id']})
    assert denied['items'] == []


def test_login_identity_is_separate_even_with_copied_tab_and_search_id(client, record):
    tab = str(uuid4())
    first = post(client, 'records/search', {'tab_id': tab})
    cookies = dict(client.cookies)
    client.cookies.clear()
    login = client.post('/api/v1/auth/login', json={'email': 'admin@test.invalid', 'password': 'Temporary-Test-Password-123!'})
    assert login.status_code == 200, login.text
    client.headers['X-CSRF-Token'] = client.cookies['erms_csrf']
    second = post(client, 'records/search', {'tab_id': tab, 'search_id': first['search_id']})
    assert second['search_id'] != first['search_id'] and len(slots()) == 2
    client.cookies.clear();client.cookies.update(cookies)
    client.headers['X-CSRF-Token'] = client.cookies['erms_csrf']
    assert post(client, 'records/search', {'tab_id': tab, 'search_id': first['search_id']})['search_id'] == first['search_id']


def test_migration_111_preserves_entries_unlogged_storage_and_login_cascade(client, record):
    from pathlib import Path
    first = post(client, 'records/search', {'tab_id': str(uuid4())})
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        # Reconstruct the pre-111 names in this disposable database only.
        for suffix in ('pkey', 'hits_check', 'session_id_fkey'):
            connection.execute(f'ALTER TABLE search_results_cache RENAME CONSTRAINT search_results_cache_{suffix} TO global_search_results_{suffix}')
        connection.execute('ALTER INDEX search_results_cache_expiry_idx RENAME TO global_search_results_expiry_idx')
        connection.execute('ALTER TABLE search_results_cache RENAME TO global_search_results')
        connection.execute("DELETE FROM schema_migrations WHERE version='111_shared_search_results_cache'")
        connection.commit()
        migration = Path('database/migrations/111_shared_search_results_cache.sql').read_text()
        connection.execute(migration, prepare=False)
        assert connection.execute("SELECT relpersistence FROM pg_class WHERE oid='search_results_cache'::regclass").fetchone() == ('u',)
        session = connection.execute('SELECT session_id FROM search_results_cache WHERE search_id=%s', (first['search_id'],)).fetchone()[0]
        connection.execute('DELETE FROM login_sessions WHERE id=%s', (session,))
        assert connection.execute('SELECT count(*) FROM search_results_cache').fetchone()[0] == 0


@pytest.mark.parametrize('resource', ['records', 'aggregations'])
def test_inherited_hold_and_location_criteria_keep_canonical_values(client, record, resource):
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute("SELECT set_config('app.user_id','1',true),set_config('app.change_reason','Cache projection fixture',true),set_config('app.location_change_authorized','authorized',true)")
        connection.execute("UPDATE aggregations SET assigned_location='Archive',current_location='Room 5' WHERE id=%s", (record['aggregation_id'],))
        hold = connection.execute("INSERT INTO holds(code,name,valid_from,owner_user_id,preserve_resource_state) VALUES('CACHE','Cache hold',now()-interval '1 day',1,true) RETURNING id").fetchone()[0]
        connection.execute('INSERT INTO hold_aggregation_assignments(hold_id,aggregation_id) VALUES(%s,%s)', (hold, record['aggregation_id']))
        # Same hold both directly and by inheritance must still count only once.
        connection.execute('INSERT INTO hold_record_assignments(hold_id,record_id) VALUES(%s,%s)', (hold, record['id']))
    for field, operator, value in [('on_effective_hold', 'eq', True), ('resource_state_changes_blocked', 'eq', True),
                                    ('effective_hold_id', 'eq', hold), ('effective_assigned_location', 'eq', 'Archive'),
                                    ('effective_current_location', 'eq', 'Room 5')]:
        payload = {'where': {'field': field, 'operator': operator, 'value': value}}
        expected = post(client, resource + '/search', payload)
        cached = post(client, resource + '/search', {**payload, 'tab_id': str(uuid4())})
        for item in cached['items']:
            item.pop('_capabilities', None)
            assert 'effective_hold_ids' not in item
        assert cached['items'] == expected['items'] and cached['total'] == expected['total'] == 1


def test_multiple_full_text_leaf_scores_and_same_component_scope_are_preserved(client, record):
    from .test_advanced_search_component_metadata import _component
    _publish_component(_upload(client, record), text='approved budget evidence ' * 7)
    _component(client, record['id'], 2, 'other.pdf', 500)
    expressions = [
        {'or': [{'full_text': {'query': 'budget'}}, {'full_text': {'query': 'record OR evidence'}}]},
        {'and': [{'field': 'component.file_name', 'operator': 'contains_ci', 'value': 'other'},
                 {'field': 'component.size_in_bytes', 'operator': 'gt', 'value': 400}]},
    ]
    for expression in expressions:
        payload = {'where': expression}
        if 'or' in expression:
            payload['include'] = ['full_text_matches']
        expected = post(client, 'records/search', payload)
        cached = post(client, 'records/search', {**payload, 'tab_id': str(uuid4())})
        for item in cached['items']:
            item.pop('_capabilities', None)
        assert cached['items'] == expected['items']


def test_inherited_retention_cache_matches_canonical_resolver_and_rechecks_changes(client, aggregation):
    from .test_advanced_search_effective_retention import create, override
    child = create(client, 'CACHE-CHILD', parent_aggregation_id=aggregation['id'])
    for years in (5, 2):
        if years == 2:
            override(client, aggregation, current=2)
        payload = {'where': {'field': 'effective_retention.current_period_years', 'operator': 'eq', 'value': years}}
        expected = post(client, 'aggregations/search', payload)
        cached = post(client, 'aggregations/search', {**payload, 'tab_id': str(uuid4())})
        assert cached['items'] == expected['items']
        assert {item['id'] for item in cached['items']} == {aggregation['id'], child['id']}


def test_explicit_resubmission_refreshes_membership_and_cached_pages_recheck_criteria(client, record):
    payload = {'tab_id': str(uuid4()), 'where': {'field': 'title', 'operator': 'contains_ci', 'value': 'Example'}}
    first = post(client, 'records/search', payload)
    created = client.post('/api/v1/records', json={'aggregation_id': record['aggregation_id'],
                          'record_number': 'CACHE-NEW', 'title': 'Example newly inserted'})
    assert created.status_code == 201, created.text
    cached = post(client, 'records/search', {**payload, 'search_id': first['search_id']})
    assert [item['id'] for item in cached['items']] == [record['id']]
    fresh = post(client, 'records/search', payload)
    assert fresh['total'] == 2 and fresh['search_id'] != first['search_id']
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute("SELECT set_config('app.user_id','1',true),set_config('app.change_reason','Criteria freshness fixture',true)")
        connection.execute("UPDATE records SET title='No longer matching' WHERE id=%s", (record['id'],))
    changed = post(client, 'records/search', {**payload, 'search_id': fresh['search_id']})
    assert [item['id'] for item in changed['items']] == [created.json()['id']]
    assert changed['search_id'] == fresh['search_id'] and changed['total'] == 1


def test_shared_ranker_preserves_advanced_score_formula_without_exposing_file_evidence(client, record):
    component = _upload(client, record)
    _publish_component(component, 'budget budget', configuration='pg_catalog.simple')
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute("UPDATE roles SET is_information_governance=false WHERE code='system-administrator'")
        for table in ('record_acl_grants', 'aggregation_child_record_acl_defaults'):
            connection.execute(f'DELETE FROM {table}')
        connection.execute('''INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,permission_id)
            SELECT %s,'everyone',id FROM permissions WHERE code='record.view' ON CONFLICT DO NOTHING''',
                           (record['aggregation_id'],))
    where = {'full_text': {'query': 'record OR budget'}}
    payload = {'where': where, 'include': ['full_text_matches']}
    legacy = post(client, 'records/advanced-search', payload)
    cached = post(client, 'records/advanced-search', {**payload, 'tab_id': str(uuid4())})
    assert len(legacy['items']) == len(cached['items']) == 1
    assert cached['items'][0]['_search'] == legacy['items'][0]['_search']
    assert cached['items'][0]['_search']['matching_components'] == []
    global_result = post(client, 'full-text-search', {'result_types': ['records'], 'record_where': where})
    # Global has always protected component-score contributions; reusing the
    # SQL must preserve the existing difference as well as visible results.
    assert global_result['items'][0]['score'] < cached['items'][0]['_search']['relevance']
