"""Dashboard batching must preserve authorization, lifecycle and hold semantics."""
import os
from datetime import datetime,timedelta,timezone

import psycopg
import pytest
from psycopg.rows import dict_row
from backend.services.api.dashboard import _resource_metrics
from backend.services.api.tests.test_legal_holds_api import _create_hold


@pytest.mark.parametrize('governance',[False,True])
@pytest.mark.parametrize('status',[10,11,12,13])
def test_dashboard_live_counts_exclude_all_disposed_statuses_for_every_role(client,aggregation,record,governance,status):
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        assert c.execute('SELECT current_database()').fetchone()[0].startswith('erms_messaging_test_acl_')
        # Synthetic terminal fixtures, not a transfer-workflow test. Restore
        # triggers before exercising the real summary and visibility functions.
        for table in ('aggregations','records'):
            c.execute(f'ALTER TABLE {table} DISABLE TRIGGER USER')
            try:c.execute(f'UPDATE {table} SET disposition_status=%s',(status,))
            finally:c.execute(f'ALTER TABLE {table} ENABLE TRIGGER USER')
        c.execute('UPDATE roles SET is_information_governance=%s WHERE id IN (SELECT role_id FROM user_role_assignments WHERE user_id=1)',(governance,))
    response=client.get('/api/v1/dashboard/summary')
    assert response.status_code==200,response.text
    body=response.json()
    expected=int(status==13)
    assert body['overview_counts']['aggregations']==expected
    assert body['overview_counts']['records']==expected
    assert body['ownership_counts'][0]['aggregation_count']==expected
    assert body['ownership_counts'][0]['record_count']==expected


@pytest.mark.parametrize('direct',[False,True])
def test_batched_dashboard_preserves_direct_and_inherited_hold_totals(client,aggregation,record,direct):
    hold=_create_hold(client)
    resource='records' if direct else 'aggregations'
    identifier=record['id'] if direct else aggregation['id']
    attached=client.post(f'/api/v1/{resource}/{identifier}/holds',json={'hold_id':hold['id']},
                         headers={'X-Change-Reason':'Dashboard hold regression'})
    assert attached.status_code==201,attached.text
    response=client.get('/api/v1/dashboard/summary')
    assert response.status_code==200,response.text
    attention=response.json()['overview_resource_attention_counts']
    assert attention['records']['held']==1
    assert attention['aggregations']['held']==(0 if direct else 1)


def test_batched_dashboard_component_join_does_not_multiply_record_totals(client,aggregation,record):
    for order,size in ((1,111),(2,222)):
        response=client.post('/api/v1/digital-components',json={
            'record_id':record['id'],'component_order':order,'file_name':f'fixture-{order}.txt',
            'mime_type':'text/plain','size_in_bytes':size,'checksum_algo':'sha256','checksum_value':'0'*64})
        assert response.status_code==201,response.text
    response=client.get('/api/v1/dashboard/summary')
    assert response.status_code==200,response.text
    body=response.json()
    assert body['overview_counts']['records']==1
    assert body['overview_digital_component_metrics']=={'component_count':2,'storage_size_in_bytes':333}
    assert body['ownership_counts'][0]['record_count']==1
    assert body['ownership_counts'][0]['storage_size_in_bytes']==333


def test_resource_rollup_plan_scans_each_authorized_resource_set_once(client,aggregation,record):
    plans=[]
    class PlannedConnection:
        def __init__(self,c):self.connection=c
        def execute(self,query,params):
            plans.append(self.connection.execute('EXPLAIN (FORMAT JSON) '+query,params).fetchone()['QUERY PLAN'])
            return self.connection.execute(query,params)
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        c.execute("SELECT set_config('app.user_id','1',true)")
        metrics=_resource_metrics(PlannedConnection(c),3,5)
    assert len(plans)==1
    assert metrics['records'][0]['total']==1
    def nodes(plan):
        yield plan
        for child in plan.get('Plans',[]):yield from nodes(child)
    scans=list(nodes(plans[0][0]['Plan']))
    assert sum(n.get('Subplan Name')=='CTE visible_records' for n in scans)==1
    assert sum(n.get('Subplan Name')=='CTE visible_aggregations' for n in scans)==1
    assert not any(n.get('Subplan Name') in ('CTE ancestry','CTE record_row') for n in scans)
    assert sum(n.get('Subplan Name')=='CTE authorized_records' for n in scans)==1
    assert sum(n.get('Subplan Name')=='CTE authorized_aggregations' for n in scans)==1
    # Hierarchy traversal is recursive set processing, never a function call
    # repeated for every resource, grant, component or classification.
    plan_text=str(plans)
    for function in ('current_user_can_view_', 'user_has_aggregation_permission',
                     'user_has_record_permission', 'role_effectively_active',
                     'user_matches_contextual_acl', 'effective_holds_for_'):
        assert function not in plan_text


@pytest.mark.parametrize('window',['future','expired','open'])
def test_batched_hold_propagation_matches_canonical_windows_and_ignores_acl_inheritance(client,aggregation,record,window):
    child=client.post('/api/v1/aggregations',json={
        'parent_aggregation_id':aggregation['id'],'aggregation_number':'HOLD-CHILD',
        'title':'Held child'})
    assert child.status_code==201,child.text
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute('UPDATE aggregations SET inherit_acl_from_parent=false WHERE id=%s',(child.json()['id'],))
    hold=_create_hold(client,preserve=False)
    attached=client.post(f"/api/v1/aggregations/{aggregation['id']}/holds",json={'hold_id':hold['id']},
                         headers={'X-Change-Reason':'Hold propagation regression'})
    assert attached.status_code==201,attached.text
    now=datetime.now(timezone.utc)
    patch=({'valid_from':(now+timedelta(days=1)).isoformat()} if window=='future' else
           {'valid_to':(now-timedelta(minutes=1)).isoformat()} if window=='expired' else {'valid_to':None})
    changed=client.patch(f"/api/v1/holds/{hold['id']}",json=patch,
        headers={'If-Match':str(hold['version']),'X-Change-Reason':'Exercise validity window'})
    assert changed.status_code==200,changed.text
    response=client.get('/api/v1/dashboard/summary')
    assert response.status_code==200,response.text
    attention=response.json()['overview_resource_attention_counts']
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute("SELECT set_config('app.user_id','1',true)")
        for resource,kind in (('aggregations','aggregation'),('records','record')):
            expected=c.execute(f'SELECT count(*) FROM authorized_{resource}_for_search WHERE current_user_can_view_{kind}(id) AND on_effective_hold').fetchone()[0]
            assert attention[resource]['held']==expected
    assert attention['aggregations']['held']==(2 if window=='open' else 0)
    assert attention['records']['held']==(1 if window=='open' else 0)


@pytest.mark.parametrize('version,index',[
    ('098_dashboard_resource_activity_index','event_history_dashboard_resource_latest_idx'),
    ('099_dashboard_content_activity_index','event_history_dashboard_content_views_idx'),
    ('100_dashboard_component_storage_index','digital_components_dashboard_storage_idx'),
    ('102_dashboard_nonterminal_resource_indexes','aggregations_dashboard_live_idx'),
    ('102_dashboard_nonterminal_resource_indexes','records_dashboard_live_idx'),
])
def test_dashboard_activity_index_is_canonical_and_upgrade_is_idempotent(client,version,index):
    from pathlib import Path
    migration=Path(__file__).parents[4]/f'database/migrations/{version}.sql'
    with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as c:
        assert c.execute('SELECT current_database()').fetchone()[0].startswith('erms_messaging_test_acl_')
        original=c.execute('SELECT indexdef FROM pg_indexes WHERE indexname=%s',(index,)).fetchone()[0]
        from psycopg import sql
        c.execute(sql.SQL('DROP INDEX {}').format(sql.Identifier(index)))
        c.execute('DELETE FROM schema_migrations WHERE version=%s',(version,))
        for _ in range(2):c.execute(migration.read_text(),prepare=False)
        upgraded=c.execute('SELECT indexdef FROM pg_indexes WHERE indexname=%s',(index,)).fetchone()[0]
        assert upgraded==original
        assert c.execute('SELECT count(*) FROM schema_migrations WHERE version=%s',(version,)).fetchone()[0]==1


def test_dashboard_live_indexes_upgrade_from_deployed_status_10_only_predicate(client):
    from pathlib import Path
    from psycopg import sql
    root=Path(__file__).parents[4]
    indexes=('aggregations_dashboard_live_idx','records_dashboard_live_idx')
    with psycopg.connect(os.environ['DATABASE_URL'],autocommit=True) as c:
        assert c.execute('SELECT current_database()').fetchone()[0].startswith('erms_messaging_test_acl_')
        expected={index:c.execute('SELECT pg_get_indexdef(%s::regclass)',(index,)).fetchone()[0] for index in indexes}
        for index in indexes:c.execute(sql.SQL('DROP INDEX {}').format(sql.Identifier(index)))
        c.execute((root/'database/migrations/101_dashboard_live_resource_indexes.sql').read_text(),prepare=False)
        for index in indexes:
            legacy=c.execute('SELECT pg_get_indexdef(%s::regclass)',(index,)).fetchone()[0]
            assert legacy!=expected[index]
        for _ in range(2):
            c.execute((root/'database/migrations/102_dashboard_nonterminal_resource_indexes.sql').read_text(),prepare=False)
        for index in indexes:
            assert c.execute('SELECT pg_get_indexdef(%s::regclass)',(index,)).fetchone()[0]==expected[index]
        assert c.execute("SELECT count(*) FROM schema_migrations WHERE version='102_dashboard_nonterminal_resource_indexes'").fetchone()[0]==1


def test_overlapping_direct_and_inherited_holds_count_each_visible_resource_once(client,aggregation,record):
    first=_create_hold(client)
    second=client.post('/api/v1/holds',json={
        'code':'DASHBOARD-OVERLAP','name':'Overlapping hold','owner_user_id':1,
        'valid_from':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),
        'valid_to':None,'preserve_resource_state':False})
    assert second.status_code==201,second.text
    for kind,identifier,hold in (('aggregations',aggregation['id'],first),
                                  ('aggregations',aggregation['id'],second.json()),
                                  ('records',record['id'],second.json())):
        response=client.post(f'/api/v1/{kind}/{identifier}/holds',json={'hold_id':hold['id']},
            headers={'X-Change-Reason':'Overlapping dashboard hold regression'})
        assert response.status_code==201,response.text
    response=client.get('/api/v1/dashboard/summary')
    assert response.status_code==200,response.text
    assert response.json()['overview_resource_attention_counts']=={
        'aggregations':{'vital':0,'held':1},'records':{'vital':0,'held':1}}
