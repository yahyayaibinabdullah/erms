"""Historical actor suggestions, conservative indexing and bounded search."""
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from backend.services.api.main import app
from backend.services.api.audit_search import actor_suggestions
from backend.services.api.schemas import SearchRequest
from backend.services.api.search import search_rows


def search(client,where,**kwargs):
    return client.post('/api/v1/event-history/search',json={'where':where,**kwargs})


def test_suggestions_current_directory_and_historical_free_text(client,connection):
    uid=connection.execute("INSERT INTO users(name,email) VALUES ('Directory Person','directory-match@example.invalid') RETURNING id").fetchone()['id']
    connection.execute("INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_name,actor_email,actor_type) VALUES ('actor_fixture',1,'TEST',%s,'Codex publication','directory-match@example.invalid','automated_process')",(uid,))
    connection.execute("INSERT INTO users(name,email) VALUES ('Literal %_ Person','literal@example.invalid')")
    connection.commit()
    response=client.get('/api/v1/event-history/actors',params={'q':'DIRECTORY-MATCH'})
    assert response.status_code==200
    assert response.json()['items']==[{'actor_user_id':uid,'actor_name':'Directory Person','actor_email':'directory-match@example.invalid','actor_type':'user'}]
    assert len(client.get('/api/v1/event-history/actors',params={'q':'%_'}).json()['items'])==1
    connection.execute('DELETE FROM users WHERE id=%s',(uid,));connection.commit()
    assert client.get('/api/v1/event-history/actors',params={'q':'directory-match'}).json()['items']==[]
    # Deleted actors remain searchable through Apply using persisted snapshots.
    result=search(client,{'field':'actor_email','operator':'contains_ci','value':'directory-match'}).json()
    assert result['total']==1 and result['items'][0]['actor_name']=='Codex publication'
    assert client.get('/api/v1/event-history/actors',params={'q':'x'}).status_code==422
    assert client.get('/api/v1/event-history/actors',params={'q':'Directory','limit':26}).status_code==422
    anonymous=TestClient(app)
    try:
        assert anonymous.get('/api/v1/event-history/actors',params={'q':'Directory'}).status_code==401
    finally: anonymous.close()


def test_suggestions_query_never_reads_event_history():
    class Recorder:
        def execute(self,q,p):
            self.query,self.params=q,p
            return self
        def fetchall(self):return []
    recorder=Recorder()
    assert actor_suggestions(recorder,'yy')=={'items':[],'has_more':False}
    query=recorder.query.as_string()
    assert 'FROM users' in query and 'event_history' not in query
    assert 'current_user_can_view' not in query and recorder.params[-1]==26


def test_long_actor_snapshot_remains_valid(client,connection):
    import hashlib
    name='Long Snapshot '+''.join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(100))
    connection.execute("INSERT INTO event_history(entity_type,entity_id,operation,actor_name) VALUES ('long_actor_fixture',1,'TEST',%s)",(name,))
    connection.commit()
    result=search(client,{'field':'actor_name','operator':'contains_ci','value':'Long Snapshot'}).json()
    assert result['total']==1 and result['items'][0]['actor_name']==name


def test_suggestions_are_bounded(client,connection):
    connection.execute("INSERT INTO users(name,email) SELECT 'Bound Actor '||i,'bound-'||i||'@example.invalid' FROM generate_series(1,40) i")
    connection.commit()
    response=client.get('/api/v1/event-history/actors',params={'q':'Bound Actor'})
    assert response.status_code==200
    assert len(response.json()['items'])==25 and response.json()['has_more']


@pytest.mark.parametrize('cap',[1000,75])
def test_configurable_cap_counts_pagination_and_default_order(client,connection,monkeypatch,cap):
    response=client.get('/api/v1/application-settings');assert response.status_code==200,response.text
    row=next(i for i in response.json()['items'] if i['key']=='AUDIT_TRAIL_SEARCH_RESULT_LIMIT')
    response=client.put('/api/v1/application-settings',json={'changes':[{'key':row['key'],'expected_version':row['version'],'value':cap}]},headers={'X-Change-Reason':'Set disposable audit cap'})
    assert response.status_code==200,response.text
    category='cap_fixture_'+str(cap)
    connection.execute("INSERT INTO event_history(entity_type,entity_id,operation,occurred_at) SELECT %s,i,'TEST','2026-01-01'::timestamptz+i*interval '1 second' FROM generate_series(1,1200) i",(category,))
    connection.commit()
    condition={'field':'entity_type','operator':'eq','value':category}
    result=search(client,condition,limit=50).json()
    assert result['total']==cap and result['result_cap']==cap and result['truncated']
    assert [r['entity_id'] for r in result['items']]==list(range(1200,1150,-1))
    tail=search(client,condition,limit=50,offset=cap-10).json()
    assert len(tail['items'])==10 and tail['total']==cap
    assert search(client,condition,offset=cap).status_code==422
    refined=search(client,{'and':[condition,{'field':'entity_id','operator':'lte','value':10}]}).json()
    assert refined['total']==10 and not refined['truncated']


def test_candidate_predicate_does_not_change_null_negated_or_or_semantics(client,connection):
    hidden=connection.execute("INSERT INTO event_history(entity_type,entity_id,operation,actor_name,actor_email) VALUES ('aggregation',909090,'TEST','Hidden Prefilter','hidden-prefilter@example.invalid') RETURNING id").fetchone()['id']
    connection.commit()
    id_filter={'field':'id','operator':'eq','value':hidden}
    for expression in ({'field':'actor_name','operator':'is_null'}, {'not':{'field':'actor_name','operator':'eq','value':'Someone'}}, {'or':[{'field':'actor_name','operator':'eq','value':'Someone'},id_filter]}):
        result=search(client,{'and':[id_filter,expression]})
        assert result.status_code==200,result.text
        expected = 0 if 'not' in expression else 1
        assert result.json()['total']==expected
        if expected:
            assert result.json()['items'][0]['actor_name'] is None
    assert search(client,{'and':[id_filter,{'field':'actor_name','operator':'eq','value':'Hidden Prefilter'}]}).json()['total']==0


def test_audit_indexes_upgrade_matches_canonical(connection):
    root=Path(__file__).resolve().parents[5]
    expected={r['indexname']:r['indexdef'] for r in connection.execute("SELECT indexname,indexdef FROM pg_indexes WHERE tablename='event_history'")}
    connection.execute('DROP INDEX event_history_actor_name_trgm_idx; DROP INDEX event_history_actor_email_trgm_idx; DROP INDEX event_history_actor_identity_idx; DROP INDEX event_history_actor_timeline_idx; DROP INDEX event_history_occurred_at_idx; CREATE INDEX event_history_actor_timeline_idx ON event_history(actor_user_id,occurred_at DESC) WHERE actor_user_id IS NOT NULL; CREATE INDEX event_history_occurred_at_idx ON event_history(occurred_at DESC)')
    connection.commit()
    connection.execute((root/'database/migrations/047_audit_actor_search_indexes.sql').read_text())
    actual={r['indexname']:r['indexdef'] for r in connection.execute("SELECT indexname,indexdef FROM pg_indexes WHERE tablename='event_history'")}
    assert actual==expected


def test_realistic_volume_plan_and_bounded_execution(client,connection):
    row=next(i for i in client.get('/api/v1/application-settings').json()['items'] if i['key']=='AUDIT_TRAIL_SEARCH_RESULT_LIMIT')
    assert client.put('/api/v1/application-settings',json={'changes':[{'key':row['key'],'expected_version':row['version'],'value':1000}]},headers={'X-Change-Reason':'Restore performance fixture cap'}).status_code==200
    from psycopg import sql
    uid=connection.execute("SELECT id FROM users WHERE email='transfer@test.invalid'").fetchone()['id']
    connection.execute("INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_name,actor_email,actor_type,source) SELECT 'audit_perf_fixture',i,'TEST',CASE WHEN i<=50 THEN 999001 ELSE %s END,CASE WHEN i<=50 THEN 'Unique Needle Actor' ELSE 'Bulk Actor' END,CASE WHEN i<=50 THEN 'needle@example.invalid' ELSE 'bulk@example.invalid' END,'user','seeding' FROM generate_series(1,50000) i",(uid,))
    connection.commit()
    connection.execute('ANALYZE event_history')
    connection.execute("SELECT set_config('app.user_id',%s,true)",(str(uid),))
    class Recorder:
        def __init__(self): self.queries=[];self.info=connection.info
        def execute(self,query,params=None):
            self.queries.append((query,params))
            return connection.execute(query,params)
    recorded=Recorder()
    request=SearchRequest.model_validate({'where':{'or':[{'field':'actor_name','operator':'contains_ci','value':'Unique Needle'},{'field':'actor_email','operator':'contains_ci','value':'Unique Needle'}]},'limit':50})
    started=time.perf_counter();result=search_rows(recorded,'event_history',request);elapsed=time.perf_counter()-started
    assert result['total']==50 and len(result['items'])==50
    count_query,count_params=next((q,p) for q,p in recorded.queries if 'audit_count' in str(q))
    plan=connection.execute(sql.SQL('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) ')+count_query,count_params).fetchone()['QUERY PLAN'][0]
    assert 'event_history_actor_name_trgm_idx' in json.dumps(plan)
    assert 'LIMIT 1001' in count_query.as_string(connection)
    started=time.perf_counter();suggestions=actor_suggestions(connection,'tr');suggestion_seconds=time.perf_counter()-started
    assert suggestions['items'] and len(suggestions['items'])<=25
    identity_request=SearchRequest.model_validate({'where':{'field':'actor_user_id','operator':'eq','value':999001},'limit':50})
    identity_recorded=Recorder();identity=search_rows(identity_recorded,'event_history',identity_request)
    iq,ip=next((q,p) for q,p in identity_recorded.queries if 'audit_count' in str(q))
    identity_plan=connection.execute(sql.SQL('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) ')+iq,ip).fetchone()['QUERY PLAN'][0]
    assert identity['total']==50
    assert any(index in json.dumps(identity_plan) for index in ('event_history_actor_timeline_idx','event_history_actor_identity_idx'))
    # Record timings, not flaky machine-speed assertions. Passing plan assertions
    # prove selective matches use indexes, and SQL proves count work is bounded.
    baseline_plan=connection.execute("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT count(*) FROM authorized_event_history WHERE actor_name ILIKE %s OR actor_email ILIKE %s",('%Unique Needle%','%Unique Needle%')).fetchone()['QUERY PLAN'][0]
    evidence={'baseline_substring_count_plan':baseline_plan,'rows':50000,'substring_search_seconds':elapsed,'two_character_suggestions_seconds':suggestion_seconds,'substring_count_plan':plan,'selected_actor_count_plan':identity_plan}
    output=os.environ.get('AUDIT_SEARCH_QA_DIR')
    if output:
        Path(output).mkdir(parents=True,exist_ok=True)
        (Path(output)/'query-plans.json').write_text(json.dumps(evidence,indent=2))

@pytest.mark.parametrize('value',[0,-1,'invalid',True])
def test_cap_configuration_rejects_nonpositive_or_noninteger(client,value):
    row=next(i for i in client.get('/api/v1/application-settings').json()['items'] if i['key']=='AUDIT_TRAIL_SEARCH_RESULT_LIMIT')
    response=client.put('/api/v1/application-settings',json={'changes':[{'key':row['key'],'expected_version':row['version'],'value':value}]},headers={'X-Change-Reason':'Reject invalid cap'})
    assert response.status_code==422


def test_suggestions_require_only_audit_view_and_deny_without_it(client,connection):
    profile=connection.execute("SELECT profile_id FROM roles WHERE code='transfer-admin'").fetchone()['profile_id']
    grants=connection.execute('SELECT privilege_id FROM profile_privileges WHERE profile_id=%s',(profile,)).fetchall()
    connection.execute("DELETE FROM profile_privileges WHERE profile_id=%s AND privilege_id<>(SELECT id FROM privileges WHERE code='audit.view')",(profile,))
    connection.commit()
    try:
        response=client.get('/api/v1/event-history/actors',params={'q':'Transfer'})
        assert response.status_code==200,response.text
        connection.execute('DELETE FROM profile_privileges WHERE profile_id=%s',(profile,));connection.commit()
        assert client.get('/api/v1/event-history/actors',params={'q':'Transfer'}).status_code==403
    finally:
        for grant in grants:
            connection.execute('INSERT INTO profile_privileges(profile_id,privilege_id) VALUES (%s,%s) ON CONFLICT DO NOTHING',(profile,grant['privilege_id']))
        connection.commit()
