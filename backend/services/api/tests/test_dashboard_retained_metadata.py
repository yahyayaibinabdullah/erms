"""Disposed metadata is excluded early; inherited access/holds remain correct."""
import os
from datetime import datetime,timedelta,timezone

import psycopg
import pytest
from psycopg.rows import dict_row

from backend.services.api.dashboard import _resource_metrics
from backend.services.api.dashboard_visibility import VISIBILITY_CTES
from backend.services.api.tests.test_dashboard_set_visibility import assert_equivalent
from backend.services.api.tests.test_legal_holds_api import _create_hold


def seed_history_heavy_fixture(connection, live_records=1840, live_aggregations=840):
    """Add 95% unrelated disposed metadata across terminal statuses 10/11/12.

    Synthetic read fixtures deliberately skip resource mutation/audit triggers;
    restore every trigger before querying. FK/check constraints remain enabled.
    This is never a shortcut through the destruction workflow itself.
    """
    c=connection
    assert c.execute('SELECT current_database() AS name').fetchone()['name'].startswith('erms_messaging_test_acl_')
    root=c.execute('SELECT id,owning_org_unit_id,security_level_id,classification_id FROM aggregations LIMIT 1').fetchone()
    c.commit()
    try:
        for table in ('aggregations','records'):
            c.execute(f'ALTER TABLE {table} DISABLE TRIGGER USER')
        parameters=(root['id'],root['owning_org_unit_id'],root['security_level_id'],live_aggregations)
        c.execute("""INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title,
                   owning_org_unit_id,security_level_id,date_of_next_review)
            SELECT %s,'LIVE-AGG-'||i,'Live aggregation '||i,%s,%s,CURRENT_TIMESTAMP+INTERVAL '1 day'
              FROM generate_series(2,%s) i""",parameters)
        dead_root=c.execute("""INSERT INTO aggregations(aggregation_number,title,classification_id,
                   owning_org_unit_id,security_level_id,inherit_acl_from_parent,disposition_status,date_of_next_review)
            VALUES('DESTROYED-ROOT','Destroyed root',%s,%s,%s,false,10,CURRENT_TIMESTAMP+INTERVAL '1 day') RETURNING id""",
            (root['classification_id'],root['owning_org_unit_id'],root['security_level_id'])).fetchone()['id']
        c.execute("""INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title,
                   owning_org_unit_id,security_level_id,disposition_status,date_of_next_review)
            SELECT %s,'DESTROYED-AGG-'||i,'Disposed aggregation '||i,%s,%s,10+(i%%3),CURRENT_TIMESTAMP+INTERVAL '1 day'
              FROM generate_series(2,%s) i""",
            (dead_root,root['owning_org_unit_id'],root['security_level_id'],live_aggregations*19))
        c.execute("""WITH containers AS (
                SELECT id,row_number() OVER(ORDER BY id) AS position
                  FROM aggregations WHERE disposition_status NOT IN (10,11,12)
            ) INSERT INTO records(aggregation_id,record_number,title,owning_org_unit_id,
                   security_level_id,date_of_next_review)
            SELECT container.id,'LIVE-REC-'||i,'Live record '||i,%s,%s,CURRENT_TIMESTAMP+INTERVAL '1 day'
              FROM generate_series(2,%s) i JOIN containers container ON container.position=(i-1)%%%s+1""",
            (root['owning_org_unit_id'],root['security_level_id'],live_records,live_aggregations))
        c.execute("""INSERT INTO records(aggregation_id,record_number,title,owning_org_unit_id,
                   security_level_id,disposition_status,date_of_next_review)
            SELECT %s,'DESTROYED-REC-'||i,'Disposed record '||i,%s,%s,10+(i%%3),CURRENT_TIMESTAMP+INTERVAL '1 day'
              FROM generate_series(1,%s) i""",
            (dead_root,root['owning_org_unit_id'],root['security_level_id'],live_records*19))
        c.commit()
    finally:
        c.rollback()
        for table in ('aggregations','records'):
            c.execute(f'ALTER TABLE {table} ENABLE TRIGGER USER')
        c.commit()
    c.execute("SELECT set_config('app.event_source','seeding',true)")
    c.execute("""INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,permission_id)
        SELECT resource.id,'org_unit_members',permission.id FROM aggregations resource CROSS JOIN permissions permission
         WHERE resource.disposition_status NOT IN (10,11,12) AND permission.code='record.view' ON CONFLICT DO NOTHING""")
    c.execute('ANALYZE aggregations,records')
    c.commit()
    return dead_root


def test_history_heavy_dashboard_prunes_all_disposed_rows_and_uses_live_indexes(client,aggregation,record):
    plans=[]
    class PlannedConnection:
        def __init__(self,c):self.connection=c
        def execute(self,query,params):
            plans.append(self.connection.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+query,params).fetchone()['QUERY PLAN'])
            return self.connection.execute(query,params)
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        dead_root=seed_history_heavy_fixture(c)
        for table in ('records','aggregations'):
            statuses=c.execute(f'SELECT disposition_status,count(*) AS total FROM {table} GROUP BY disposition_status').fetchall()
            assert {row['disposition_status'] for row in statuses}=={1,10,11,12}
        c.execute('UPDATE roles SET is_information_governance=false WHERE id IN (SELECT role_id FROM user_role_assignments WHERE user_id=1)')
        dead_record=c.execute('SELECT id FROM records WHERE disposition_status=10 LIMIT 1').fetchone()['id']
        c.execute('INSERT INTO user_favourite_aggregations(user_id,aggregation_id) VALUES(1,%s)',(dead_root,))
        c.execute('INSERT INTO user_favourite_records(user_id,record_id) VALUES(1,%s)',(dead_record,))
        c.execute("SELECT set_config('app.user_id','1',true)")
        metrics=_resource_metrics(PlannedConnection(c),3,5)
        assert sum(row['total'] for row in metrics['records'])==1840
        assert sum(row['total'] for row in metrics['aggregations'])==840
        assert metrics['upcoming_review_count']==1839+839
        assert metrics['favourite_aggregations']==metrics['favourite_records']==[]
        assert all('Disposed' not in str(row) and 'Destroyed' not in str(row) for row in metrics['recent_activity']+metrics['upcoming_reviews'])
        counts=c.execute(f"""WITH RECURSIVE {VISIBILITY_CTES}
            SELECT (SELECT count(*) FROM live_records) AS records,
                   (SELECT count(*) FROM live_aggregations) AS aggregations,
                   (SELECT count(*) FROM required_aggregation_rows) AS required,
                   (SELECT count(*) FROM aggregation_sources) AS sources""").fetchone()
        assert counts=={'records':1840,'aggregations':840,'required':840,'sources':840}
        # Reuse the same connection after changing identity; the new indexes
        # and statement-local sets must not become an authorization cache.
        for identity in ('','1',''):
            c.execute("SELECT set_config('app.user_id',%s,true)",(identity,))
            result=_resource_metrics(c,3,5)
            assert sum(row['total'] for row in result['records'])==(1840 if identity else 0)
    def nodes(node):
        yield node
        for child in node.get('Plans',[]):yield from nodes(child)
    scans=list(nodes(plans[0][0]['Plan']))
    index_names={node.get('Index Name') for node in scans}
    assert {'records_dashboard_live_idx','aggregations_dashboard_live_idx'}<=index_names
    # A history-heavy cardinality estimate previously selected a nested-loop
    # record/ACL join, comparing every live record with every matched source.
    # Check actual work rather than demanding a particular physical join type.
    assert all(node.get('Rows Removed by Join Filter',0)*node['Actual Loops']<1840*10 for node in scans)
    for name,total in (('live_records',1840),('live_aggregations',840),('required_aggregation_rows',840),('aggregation_sources',840)):
        materialized=[node for node in scans if node.get('Subplan Name')=='CTE '+name]
        assert len(materialized)==1
        assert materialized[0]['Actual Rows']==total


@pytest.mark.parametrize('status',[10,11,12])
def test_pruning_retained_ancestors_preserves_canonical_acl_and_hold_semantics(client,aggregation,record,status):
    middle=client.post('/api/v1/aggregations',json={
        'parent_aggregation_id':aggregation['id'],'aggregation_number':'RETAINED-MIDDLE','title':'Retained middle'})
    assert middle.status_code==201,middle.text
    child=client.post('/api/v1/aggregations',json={
        'parent_aggregation_id':middle.json()['id'],'aggregation_number':'LIVE-CHILD','title':'Live child'})
    assert child.status_code==201,child.text
    hold=_create_hold(client,preserve=False)
    response=client.post(f"/api/v1/aggregations/{aggregation['id']}/holds",json={'hold_id':hold['id']},
                         headers={'X-Change-Reason':'Retained ancestor regression'})
    assert response.status_code==201,response.text
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        assert c.execute('SELECT current_database() AS name').fetchone()['name'].startswith('erms_messaging_test_acl_')
        c.execute('UPDATE roles SET is_information_governance=false WHERE id IN (SELECT role_id FROM user_role_assignments WHERE user_id=1)')
        c.execute("UPDATE aggregations SET default_child_aggregation_acl_mode='custom' WHERE id=%s",(middle.json()['id'],))
        c.execute("""INSERT INTO aggregation_child_aggregation_acl_defaults(aggregation_id,principal_type,permission_id)
            SELECT %s,'everyone',id FROM permissions WHERE code='aggregation.view' ON CONFLICT DO NOTHING""",(middle.json()['id'],))
        c.execute("""INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,permission_id)
            SELECT %s,'everyone',id FROM permissions WHERE code='record.view' ON CONFLICT DO NOTHING""",(aggregation['id'],))
        c.execute('UPDATE records SET inherit_acl_from_parent=true WHERE id=%s',(record['id'],))
        c.commit()
        # These inconsistent terminal units cannot be created by the normal
        # workflow. Still preserve canonical semantics for legacy data rather
        # than accidentally severing a live resource's ancestor ACL/hold.
        c.execute('ALTER TABLE aggregations DISABLE TRIGGER USER')
        try:c.execute('UPDATE aggregations SET disposition_status=%s WHERE id IN(%s,%s)',(status,aggregation['id'],middle.json()['id']))
        finally:c.execute('ALTER TABLE aggregations ENABLE TRIGGER USER')
        assert_equivalent(c,1)
        metrics=_resource_metrics(c,3,5)
        assert sum(row['total'] for row in metrics['aggregations'])==1
        assert sum(row['total'] for row in metrics['records'])==1
        assert sum(row['held'] for row in metrics['aggregations'])==1
        assert sum(row['held'] for row in metrics['records'])==1

        for table,kind in (('aggregations','aggregation'),('records','record')):
            expected=c.execute(f"SELECT count(*) AS held FROM authorized_{table}_for_search WHERE current_user_can_view_{kind}(id) AND on_effective_hold").fetchone()['held']
            assert sum(row['held'] for row in metrics[table])==expected
        # Also exercise the missing-container seed with no live aggregation.
        c.commit()
        c.execute('ALTER TABLE aggregations DISABLE TRIGGER USER')
        try:c.execute('UPDATE aggregations SET disposition_status=%s',(status,))
        finally:c.execute('ALTER TABLE aggregations ENABLE TRIGGER USER')
        assert_equivalent(c,1)
        metrics=_resource_metrics(c,3,5)
        assert metrics['aggregations']==[]
        assert sum(row['total'] for row in metrics['records'])==1
        assert sum(row['held'] for row in metrics['records'])==1


@pytest.mark.parametrize('governance',[False,True])
@pytest.mark.parametrize('status',[10,11,12,13])
def test_dashboard_cards_and_review_pages_share_nonterminal_scope(client,aggregation,record,status,governance):
    live=client.post('/api/v1/aggregations',json={
        'aggregation_number':'LIVE-ROOT','title':'Live root','classification_id':1})
    assert live.status_code==201,live.text
    live_record=client.post('/api/v1/records',json={
        'aggregation_id':live.json()['id'],'record_number':'LIVE-RECORD','title':'Live record'})
    assert live_record.status_code==201,live_record.text
    for identifier,size in ((record['id'],999),(live_record.json()['id'],111)):
        response=client.post('/api/v1/digital-components',json={
            'record_id':identifier,'component_order':1,'file_name':'fixture.txt','mime_type':'text/plain',
            'size_in_bytes':size,'checksum_algo':'sha256','checksum_value':'0'*64})
        assert response.status_code==201,response.text
    for kind,identifier in (('aggregations',aggregation['id']),('aggregations',live.json()['id']),
                            ('records',record['id']),('records',live_record.json()['id'])):
        resource=client.get(f'/api/v1/{kind}/{identifier}').json()
        for operation,change in (('review-date',{'date_of_next_review':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}),
                                 ('vital-status',{'is_vital':True})):
            changed=client.post(f'/api/v1/{kind}/{identifier}/{operation}',
                json={**change,'reason':'Dashboard disposed-metadata regression'},
                headers={'If-Match':str(resource['version'])})
            assert changed.status_code==200,changed.text
            resource=changed.json()
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        assert c.execute('SELECT current_database()').fetchone()[0].startswith('erms_messaging_test_acl_')
        c.execute('INSERT INTO user_favourite_aggregations(user_id,aggregation_id) VALUES(1,%s)',(aggregation['id'],))
        c.execute('INSERT INTO user_favourite_records(user_id,record_id) VALUES(1,%s)',(record['id'],))
        c.commit()
        for table,identifier in (('aggregations',aggregation['id']),('records',record['id'])):
            c.execute(f'ALTER TABLE {table} DISABLE TRIGGER USER')
            try:c.execute(f'UPDATE {table} SET disposition_status=%s WHERE id=%s',(status,identifier))
            finally:c.execute(f'ALTER TABLE {table} ENABLE TRIGGER USER')
        c.execute('UPDATE roles SET is_information_governance=%s WHERE id IN (SELECT role_id FROM user_role_assignments WHERE user_id=1)',(governance,))
    response=client.get('/api/v1/dashboard/summary',params={'recent_limit':50})
    assert response.status_code==200,response.text
    body=response.json()
    expected=2 if status==13 else 1
    assert body['overview_counts']['aggregations']==expected
    assert body['overview_counts']['records']==expected
    assert body['overview_resource_attention_counts']=={
        'aggregations':{'vital':expected,'held':0},'records':{'vital':expected,'held':0}}
    expected_size=1110 if status==13 else 111
    assert body['overview_digital_component_metrics']=={'component_count':expected,'storage_size_in_bytes':expected_size}
    assert body['ownership_counts'][0]['aggregation_count']==expected
    assert body['ownership_counts'][0]['record_count']==expected
    assert body['ownership_counts'][0]['vital_record_count']==expected
    assert body['ownership_counts'][0]['storage_size_in_bytes']==expected_size
    assert len(body['favourites']['aggregations'])==int(status==13)
    assert len(body['favourites']['records'])==int(status==13)
    live_ids={('aggregation',live.json()['id']),('record',live_record.json()['id'])}
    if status==13:live_ids|={('aggregation',aggregation['id']),('record',record['id'])}
    assert all((item['entity_type'],item['entity_id']) in live_ids for item in body['recent_activity'])
    assert body['upcoming_review_count']==expected*2
    assert {(item['entity_type'],item['entity_id']) for item in body['upcoming_reviews']}==live_ids
    reviews=client.get('/api/v1/dashboard/reviews',params={'state':'upcoming'})
    assert reviews.status_code==200,reviews.text
    assert {(item['entity_type'],item['entity_id']) for item in reviews.json()}==live_ids
