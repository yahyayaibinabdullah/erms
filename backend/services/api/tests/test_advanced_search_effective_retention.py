"""AS-ER: effective rules are resolved before authorization-aware pagination."""
import json
import os
from datetime import datetime, timezone

import psycopg
from psycopg import sql

from backend.services.api.schemas import SearchRequest
from backend.services.api.search import SEARCH_FIELDS, _compile_expression, _search_from, _resource_visibility
from backend.services.api.tests.test_phase7_mutation_authorization import (
    _grant_principal, _login_as_phase7, _set_aggregation_acl,
)
from backend.services.api.tests.test_saved_searches import _payload

PREFIX = 'effective_retention.'
CURRENT = PREFIX + 'current_period_years'
INTERMEDIATE = PREFIX + 'intermediate_period_years'
ACTION = PREFIX + 'final_disposition'


def leaf(field=CURRENT, operator='eq', value=5):
    return dict(field=field, operator=operator, value=value)


def search(client, where, **options):
    response = client.post('/api/v1/aggregations/search', json=dict(where=where, **options))
    assert response.status_code == 200, response.text
    return response.json()


def create(client, number, **changes):
    payload = dict(aggregation_number=number, title='Retention budget ' + number, classification_id=1)
    payload.update(changes)
    if payload.get('parent_aggregation_id'):
        payload.pop('classification_id', None)
    response = client.post('/api/v1/aggregations', json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def override(client, root, current=0, intermediate=7, action='transfer_to_external_archive'):
    response = client.put(f"/api/v1/aggregations/{root['id']}/retention-rule", json=dict(
        current_period_years=current, intermediate_period_years=intermediate,
        final_disposition=action, justification='Verify current effective retention'),
        headers={'X-Change-Reason': 'Verify current effective retention'})
    assert response.status_code == 200, response.text
    return response.json()


def test_inheritance_overrides_and_changes_follow_the_existing_resolver(client):
    branch = client.post('/api/v1/classifications', json=dict(
        classification_scheme_id=1, code='INHERITED', title='Inherited branch',
        retention_rule=dict(current_period_years=2, intermediate_period_years=5, final_disposition='destruction')))
    assert branch.status_code == 201, branch.text
    terminal = client.post('/api/v1/classifications', json=dict(
        classification_scheme_id=1, parent_classification_id=branch.json()['id'],
        code='INHERITED-LEAF', title='Inherited terminal', is_terminal=True))
    assert terminal.status_code == 201, terminal.text
    root = create(client, 'INHERITED-ROOT', classification_id=terminal.json()['id'])
    child = create(client, 'INHERITED-CHILD', parent_aggregation_id=root['id'])
    direct = create(client, 'DIRECT')
    criteria = {'and': [leaf(value=2), leaf(INTERMEDIATE, 'gte', 5), leaf(ACTION, 'eq', 'destruction')]}
    assert {x['id'] for x in search(client, criteria)['items']} == {root['id'], child['id']}
    assert [x['id'] for x in search(client, leaf())['items']] == [direct['id']]
    local = override(client, root)
    assert not search(client, criteria)['items']
    zero = {'and': [leaf(value=0), leaf(INTERMEDIATE, 'eq', 7), leaf(ACTION, 'eq', 'transfer_to_external_archive')]}
    assert {x['id'] for x in search(client, zero)['items']} == {root['id'], child['id']}
    deleted = client.delete(f"/api/v1/aggregations/{root['id']}/retention-rule", headers={
        'If-Match': str(local['version']), 'X-Change-Reason': 'Restore inherited retention'})
    assert deleted.status_code == 204, deleted.text
    assert {x['id'] for x in search(client, criteria)['items']} == {root['id'], child['id']}
    rule_url = f"/api/v1/classifications/{branch.json()['id']}/retention-rule"
    rule = client.get(rule_url).json()
    changed = client.put(rule_url, params={'version':rule['version']}, json=dict(current_period_years=3, intermediate_period_years=5, final_disposition='destruction'), headers={'X-Change-Reason':'Verify inheritance mutation'})
    assert changed.status_code == 200, changed.text
    assert not search(client, criteria)['items']
    assert {x['id'] for x in search(client, leaf(value=3))['items']} == {root['id'], child['id']}
    # Reparenting a child changes its governing root and therefore its rule.
    child = client.get(f"/api/v1/aggregations/{child['id']}").json()
    moved = client.patch(f"/api/v1/aggregations/{child['id']}", json={
        'aggregation_number': child['aggregation_number'], 'title': child['title'],
        'parent_aggregation_id': direct['id'],
    }, headers={'If-Match': str(child['version']), 'X-Change-Reason': 'Verify governing root change'})
    assert moved.status_code == 200, moved.text
    assert {x['id'] for x in search(client, leaf())['items']} == {direct['id'], child['id']}
    for item in (root, child, direct):
        rule = client.get(f"/api/v1/aggregations/{item['id']}/effective-retention-rule").json()
        exact = {'and': [leaf(PREFIX+key, 'eq', rule[key]) for key in (
            'current_period_years', 'intermediate_period_years', 'final_disposition')]}
        assert item['id'] in {x['id'] for x in search(client, exact)['items']}


def test_operators_boolean_pagination_and_closed_aggregations(client):
    roots = [create(client, f'OPERATORS-{i}') for i in range(4)]
    actions = ['destruction', 'transfer_to_external_archive', 'selective_preservation', 'retain_as_local_archives']
    for i, root in enumerate(roots):
        override(client, root, current=i, intermediate=i, action=actions[i])
    for field in (CURRENT, INTERMEDIATE):
        for op, value, expected in [
            ('eq', 1, {1}), ('ne', 1, {0,2,3}), ('gt', 1, {2,3}),
            ('gte', 1, {1,2,3}), ('lt', 1, {0}), ('lte', 1, {0,1}),
            ('between', [1,2], {1,2}), ('in', [0,3], {0,3}), ('not_in', [0,3], {1,2}),
        ]:
            assert {x['id'] for x in search(client, leaf(field, op, value))['items']} == {roots[i]['id'] for i in expected}
    for op, value, expected in [('eq', actions[0], {0}), ('ne', actions[0], {1,2,3}),
                               ('in', actions[:2], {0,1}), ('not_in', actions[:2], {2,3})]:
        assert {x['id'] for x in search(client, leaf(ACTION, op, value))['items']} == {roots[i]['id'] for i in expected}
    where = {'and': [{'or': [leaf(value=0), leaf(value=2)]}, {'not': leaf(ACTION, 'eq', actions[2])}]}
    assert [x['id'] for x in search(client, where)['items']] == [roots[0]['id']]
    page = search(client, leaf(CURRENT, 'gte', 0), limit=2, offset=1)
    assert page['total'] == 4 and [x['id'] for x in page['items']] == [roots[1]['id'], roots[2]['id']]
    assert all(not any(key.startswith(PREFIX) or key=='current_period_years' for key in x) for x in page['items'])
    root = roots[0]
    closed = client.patch(f"/api/v1/aggregations/{root['id']}", json={'date_closed':datetime.now(timezone.utc).isoformat()}, headers={'If-Match': str(client.get(f"/api/v1/aggregations/{root['id']}").json()['version'])})
    assert closed.status_code == 200, closed.text
    assert [x['id'] for x in search(client, leaf(value=0))['items']] == [root['id']]


def test_invalid_types_operators_targets_sorting_and_limits(client):
    invalid = [leaf(value=value) for value in [-1, 1.5, '1.5', True, None, {}, [1]]]
    invalid += [leaf(CURRENT, 'in', [-1, 2]), leaf(CURRENT, 'between', [0, -1]),
                leaf(CURRENT, 'in', []), leaf(CURRENT, 'in', list(range(101))),
                leaf(CURRENT, 'between', [1]), leaf(CURRENT, 'contains_ci', '1'),
                leaf(CURRENT, 'is_null', None), leaf(ACTION, 'eq', 'DROP TABLE aggregations'),
                leaf(ACTION, 'contains_ci', 'destruction'), leaf(ACTION, 'gt', 'destruction'),
                leaf(ACTION, 'in', ['destruction', 'invalid']),
                leaf(PREFIX+'instructions', 'eq', 'private'),
                {'and': [leaf()] * 51}]
    for where in invalid:
        response = client.post('/api/v1/aggregations/search', json={'where': where})
        assert response.status_code == 422, (where, response.text)
    deep = leaf()
    for _ in range(5):
        deep = {'not': deep}
    assert client.post('/api/v1/aggregations/search', json={'where': deep}).status_code == 422
    for field in (CURRENT, INTERMEDIATE, ACTION):
        assert client.post('/api/v1/records/search', json={'where': leaf(field, 'eq', 'destruction' if field==ACTION else 0)}).status_code == 422
        for resource in ('aggregations', 'records'):
            assert client.post(f'/api/v1/{resource}/search', json={'sort':[{'field':field,'direction':'asc'}]}).status_code == 422
        definition = {'schema_version': 1, 'resource_type':'aggregation', 'request':{'sort':[{'field':field,'direction':'asc'}]}}
        assert client.post('/api/v1/saved-searches', json=_payload(definition=definition)).status_code == 422


def test_saved_execution_uses_current_rule_and_stored_cap(client):
    roots = [create(client, f'SAVED-{i}') for i in range(3)]
    definition = dict(schema_version=1, resource_type='aggregation', max_results=2,
                      request={'where':leaf(), 'limit':25})
    created = client.post('/api/v1/saved-searches', json=_payload(definition=definition))
    assert created.status_code == 201, created.text
    saved = created.json()
    reopened = client.get(f"/api/v1/saved-searches/{saved['id']}").json()
    assert reopened['definition']['request']['where'] == leaf()
    url=f"/api/v1/saved-searches/{saved['id']}/execute"
    first=client.post(url,json={'limit':25}).json()
    assert first['total']==2 and first['returned']==2
    override(client, roots[0], current=9)
    fresh=client.post(url,json={}).json()
    assert fresh['items'][0]['id']==roots[1]['id']
    assert client.post(url,json={'offset':2}).status_code==422


def test_retention_filters_preserve_authorization_and_do_not_grant_disposition_privileges(client):
    visible=create(client,'VISIBLE'); hidden=create(client,'HIDDEN')
    _,role=_grant_principal({'aggregation.view'})
    _set_aggregation_acl(visible['id'],role,{'aggregation.view'})
    _set_aggregation_acl(hidden['id'],role,set())
    _login_as_phase7(client)
    page=search(client,leaf())
    assert page['total']==1 and [x['id'] for x in page['items']]==[visible['id']]
    assert client.get(f"/api/v1/aggregations/{hidden['id']}").status_code==404


def test_full_text_combines_with_retention(client):
    from backend.services.api.tests.test_application_settings_phase4 import save
    assert save(client, {'FULL_TEXT_SEARCH_ENABLED':True}).status_code==200
    root=create(client,'FULLTEXT')
    where={'and':[leaf(), {'full_text':{'query':'budget','sources':['metadata']}}]}
    assert [x['id'] for x in search(client,where)['items']]==[root['id']]
    global_page=client.post('/api/v1/full-text-search',json={'result_types':['aggregations'],'aggregation_where':where})
    assert global_page.status_code==200, global_page.text


def test_resolver_join_is_optional_and_shared_with_count_and_page(client):
    # Representative hierarchy: 100 roots, each with nine children (1,000 rows).
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute("SELECT set_config('app.event_source','seeding',true)")
        connection.execute("""INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,security_level_id)
            SELECT 'PERF-'||n,'Retention performance',1,1,(SELECT id FROM security_levels ORDER BY level_number LIMIT 1)
            FROM generate_series(1,100) n""")
        connection.execute("""INSERT INTO aggregations(aggregation_number,title,parent_aggregation_id,owning_org_unit_id,security_level_id)
            SELECT root.aggregation_number||'-'||n,'Retention child',root.id,1,root.security_level_id
            FROM aggregations root CROSS JOIN generate_series(1,9) n WHERE root.parent_aggregation_id IS NULL""")
        connection.execute('ANALYZE aggregations')
        request=SearchRequest.model_validate({'where':{'and':[leaf(),leaf(INTERMEDIATE,'eq',0),leaf(ACTION,'eq','destruction')]}})
        clause,parameters=_compile_expression(request.where,SEARCH_FIELDS['aggregations'],resource='aggregations',depth=1,condition_counter=[0])
        connection.execute("SELECT set_config('app.user_id','1',true)")
        source=_search_from(sql.Identifier('authorized_aggregations_for_search'),'aggregations',request.where)
        clause=sql.SQL('({}) AND ({})').format(clause,_resource_visibility('aggregations',request.where))
        assert source.as_string().count('aggregation_effective_retention_rule')==1
        assert 'aggregation_effective_retention_rule' not in _search_from(sql.Identifier('aggregations'),'aggregations',None).as_string()
        evidence={}
        for name,selection,suffix in [('count','count(*)',''),('page','resource.*',' ORDER BY resource.id LIMIT 25')]:
            query=sql.SQL('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT {} FROM {} WHERE {}{}').format(sql.SQL(selection),source,clause,sql.SQL(suffix))
            evidence[name]=connection.execute(query,parameters).fetchone()[0]
            plan=json.dumps(evidence[name])
            assert 'aggregation_effective_retention_rule' in plan
        print('Retention plan measurements: ' + json.dumps({name: {'planning_ms': plan[0]['Planning Time'], 'execution_ms': plan[0]['Execution Time']} for name, plan in evidence.items()}))
    assert search(client,leaf(),limit=25)['total']==1000
