"""API-owned search/indexing policy and completed configuration cutover."""
from pathlib import Path
import os
import pytest
from backend.services.api import application_settings_migration as migration, search, service_authentication
from backend.services.api import text_indexing_maintenance as maintenance
from backend.services.api.application_settings import cache,load_snapshot,SettingsCache
from backend.services.api.schemas import SearchRequest
from backend.services.api.tests.test_application_settings_phase4 import db,save,items,plan_for,apply_plan
ROOT=Path(__file__).resolve().parents[4]


def test_api_flags_health_and_scheduling_ignore_environment_and_refresh(client,record,monkeypatch):
    for key in migration.SEARCH_KEYS:monkeypatch.setenv(key,'invalid-obsolete-value')
    monkeypatch.setenv('WEBUI_FULL_TEXT_SEARCH_ENABLED','true')
    for response in (client.get('/health'),client.get('/api/v1/i18n/bootstrap'),client.get('/api/v1/application-configuration')):
        assert response.status_code==200,response.text
        value=response.json();configuration=value.get('application_configuration',value)
        assert configuration.get('FULL_TEXT_SEARCH_ENABLED',value.get('full_text_search_enabled')) is False
    assert client.post('/api/v1/full-text-search',json={'record_where':{'full_text':{'query':'water'}},'result_types':['records']}).status_code==503
    assert client.post('/api/v1/records/search',json={'where':{'field':'title','operator':'contains_ci','value':'a'}}).status_code==200
    assert save(client,{'FULL_TEXT_SEARCH_ENABLED':True,'CONTENT_INDEXING_SCHEDULING_ENABLED':True}).status_code==200
    health=client.get('/health').json();assert health['full_text_search_enabled'] and health['content_indexing_scheduling_enabled']
    response=client.post(f"/api/v1/records/{record['id']}/digital-components/upload",data={'component_order':1},files={'file':('phase6.txt',b'water evidence','text/plain')})
    assert response.status_code==201,response.text
    with db() as c:assert c.execute('SELECT count(*) AS n FROM content_indexing_jobs WHERE digital_component_id=%s',(response.json()['id'],)).fetchone()['n']==1
    assert save(client,{'FULL_TEXT_SEARCH_ENABLED':False,'CONTENT_INDEXING_SCHEDULING_ENABLED':False}).status_code==200
    assert client.get('/api/v1/dashboard/summary').json()['application_configuration']['FULL_TEXT_SEARCH_ENABLED'] is False


def test_audit_cap_is_one_snapshot_for_count_page_and_response_and_no_env_fallback(client,monkeypatch):
    monkeypatch.setenv('AUDIT_TRAIL_SEARCH_RESULT_LIMIT','99999')
    with db() as c:c.execute("INSERT INTO event_history(entity_type,entity_id,operation,source) SELECT 'phase6-audit',i,'TEST','seeding' FROM generate_series(1,20) i")
    assert save(client,{'AUDIT_TRAIL_SEARCH_RESULT_LIMIT':7}).status_code==200
    condition={'field':'entity_type','operator':'eq','value':'phase6-audit'}
    response=client.post('/api/v1/event-history/search',json={'where':condition,'limit':10})
    assert response.status_code==200,response.text
    result=response.json();assert result['total']==result['result_cap']==len(result['items'])==7 and result['truncated']
    assert len(client.post('/api/v1/event-history/search',json={'where':condition,'limit':10,'offset':5}).json()['items'])==2
    assert client.post('/api/v1/event-history/search',json={'where':condition,'offset':7}).status_code==422
    # Swap the setting while the count is executing; the captured snapshot must
    # still govern this operation's page and returned cap.
    with db() as c:
        c.execute("SELECT set_config('app.user_id','1',true)")
        old=load_snapshot(c)
        class Recorder:
            info=c.info
            def execute(self,query,params=None):
                if 'audit_count' in str(query):
                    assert save(client,{'AUDIT_TRAIL_SEARCH_RESULT_LIMIT':11}).status_code==200
                return c.execute(query,params)
        with monkeypatch.context() as patch:
            patch.setattr(search.settings_cache,'for_connection',lambda connection:old)
            result=search.search_rows(Recorder(),'event_history',SearchRequest.model_validate({'where':condition,'limit':10}))
    assert result['result_cap']==result['total']==len(result['items'])==7
    assert client.post('/api/v1/event-history/search',json={'where':condition}).json()['result_cap']==11
    assert save(client,{'AUDIT_TRAIL_SEARCH_RESULT_LIMIT':9223372036854775807}).status_code==200
    assert client.post('/api/v1/event-history/search',json={'where':condition}).status_code==200


def test_all_three_rate_limits_are_api_database_values(client,record,monkeypatch):
    for key in ('SEARCH_RATE_LIMIT_PER_MINUTE','MANUAL_REINDEX_RATE_LIMIT_PER_MINUTE','TEXT_INDEXER_RATE_LIMIT_PER_MINUTE'):monkeypatch.setenv(key,'invalid-obsolete')
    assert save(client,{'SEARCH_RATE_LIMIT_PER_MINUTE':1,'MANUAL_REINDEX_RATE_LIMIT_PER_MINUTE':1,'TEXT_INDEXER_RATE_LIMIT_PER_MINUTE':1}).status_code==200
    from backend.services.api.tests.test_full_text_search_phase3 import _grant_phase3_privileges
    _grant_phase3_privileges()
    service_authentication._RATE_WINDOWS.clear()
    assert client.post('/api/v1/records/search',json={}).status_code==200
    assert client.post('/api/v1/records/search',json={}).status_code==429
    assert save(client,{'SEARCH_RATE_LIMIT_PER_MINUTE':2}).status_code==200
    assert client.post('/api/v1/records/search',json={}).status_code==200
    assert client.post(f"/api/v1/records/{record['id']}/reindex").status_code==202
    assert client.post(f"/api/v1/records/{record['id']}/reindex").status_code==429
    # Existing service fixture supplies a separate authenticated credential.
    from backend.services.api.tests.test_text_indexing import _service_key
    token=_service_key()
    headers={'Authorization':'Bearer '+token,'X-Worker-ID':'phase2-worker-a'}
    path='/api/v1/internal/text-indexing/jobs/claim'
    from backend.services.api.tests.test_text_indexing import CLAIM
    assert client.post(path,json=CLAIM,headers=headers).status_code==200
    assert client.post(path,json=CLAIM,headers=headers).status_code==429
    service_authentication._RATE_WINDOWS.clear()


def test_search_migration_extends_completed_keys_reports_removed_alias_and_preserves_cap(client,tmp_path,monkeypatch):
    original=migration.MIGRATED_KEYS
    path=tmp_path/'legacy.env';path.write_text('MAX_UPLOAD_SIZE_BYTES=12345\nFULL_TEXT_SEARCH_ENABLED=yes\nWEBUI_FULL_TEXT_SEARCH_ENABLED=false\nAUDIT_TRAIL_SEARCH_RESULT_LIMIT=77\n')
    monkeypatch.setattr(migration,'MIGRATED_KEYS',migration.GENERAL_INTERFACE_KEYS+migration.CONTENT_KEYS+migration.AUTHENTICATION_KEYS)
    apply_plan(plan_for(path),path);before=items(client)['MAX_UPLOAD_SIZE_BYTES']
    monkeypatch.setattr(migration,'MIGRATED_KEYS',original)
    path.write_text('MAX_UPLOAD_SIZE_BYTES=invalid-later-edit\nFULL_TEXT_SEARCH_ENABLED=yes\nWEBUI_FULL_TEXT_SEARCH_ENABLED=false\nAUDIT_TRAIL_SEARCH_RESULT_LIMIT=77\n')
    source=path.read_bytes();plan=plan_for(path)
    assert 'WEBUI_FULL_TEXT_SEARCH_ENABLED' in plan['obsolete_entries'] and not plan['issues']
    assert not any(i['key']=='WEBUI_FULL_TEXT_SEARCH_ENABLED' for i in plan['items'])
    apply_plan(plan,path)
    assert path.read_bytes()==source and items(client)['MAX_UPLOAD_SIZE_BYTES']==before
    assert items(client)['FULL_TEXT_SEARCH_ENABLED']['value'] is True and items(client)['AUDIT_TRAIL_SEARCH_RESULT_LIMIT']['value']==77
    assert save(client,{'AUDIT_TRAIL_SEARCH_RESULT_LIMIT':88}).status_code==200
    apply_plan(plan,path);assert items(client)['AUDIT_TRAIL_SEARCH_RESULT_LIMIT']['value']==88


def test_indexing_cleanup_captures_defaults_retention_batch_interval_and_override(client,monkeypatch):
    assert save(client,{'CONTENT_INDEXING_HISTORY_RETENTION_DAYS':31,'CONTENT_INDEXING_CLEANUP_INTERVAL_SECONDS':7,'CONTENT_INDEXING_CLEANUP_BATCH_SIZE':2,'TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS':47}).status_code==200
    called=[]
    def cleanup(connection,batch,retention,dry,credentials):
        called.append((batch,retention,dry,credentials));return {'leader':True}
    monkeypatch.setattr(maintenance,'cleanup',cleanup)
    assert maintenance._run_cleanup_pass(dry_run=True)[1]==7
    assert called[-1]==(2,31,True,47)
    assert save(client,{'CONTENT_INDEXING_CLEANUP_INTERVAL_SECONDS':9,'CONTENT_INDEXING_HISTORY_RETENTION_DAYS':0}).status_code==200
    assert maintenance._run_cleanup_pass(watch=True)[1]==9 and called[-1]==(2,0,False,47)
    assert maintenance._run_cleanup_pass(batch_size=3,retention_days=4,credential_retention_days=5,interval_seconds=6)[1]==6
    assert called[-1]==(3,4,False,5)
    def fail(*args):raise RuntimeError('unavailable')
    monkeypatch.setattr(maintenance,'load_snapshot',fail)
    before=len(called)
    with pytest.raises(RuntimeError):maintenance.run_cleanup_once()
    assert len(called)==before


def test_direct_database_indexing_policy_and_upgrade_match_canonical(client,record):
    response=client.post(f"/api/v1/records/{record['id']}/digital-components/upload",data={'component_order':1},files={'file':('direct.txt',b'direct','text/plain')})
    assert response.status_code==201
    component=response.json()['id']
    with db() as c:
        expected=c.execute("SELECT pg_get_functiondef('schedule_component_content_indexing()'::regprocedure) AS definition").fetchone()['definition']
        migration_sql=(ROOT/'database/migrations/051_database_indexing_policy.sql').read_text()
        c.execute(migration_sql,prepare=False);c.execute(migration_sql,prepare=False)
        assert c.execute("SELECT pg_get_functiondef('schedule_component_content_indexing()'::regprocedure) AS definition").fetchone()['definition']==expected
        c.execute("UPDATE digital_components SET content_status=content_status WHERE id=%s",(component,))
        assert c.execute('SELECT count(*) AS n FROM content_indexing_jobs WHERE digital_component_id=%s',(component,)).fetchone()['n']==0
    assert save(client,{'CONTENT_INDEXING_SCHEDULING_ENABLED':True}).status_code==200
    with db() as c:
        c.execute("UPDATE digital_components SET content_status=content_status WHERE id=%s",(component,))
        assert c.execute('SELECT count(*) AS n FROM content_indexing_jobs WHERE digital_component_id=%s',(component,)).fetchone()['n']==1


def test_credential_page_retention_refresh_and_index_worker_upgrade_readiness(client,tmp_path):
    from backend.services.api.tests.test_full_text_search_phase4_credentials import _service_user
    account=_service_user(client)
    assert save(client,{'TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS':17}).status_code==200
    response=client.get(f"/api/v1/text-indexers/{account['id']}/credentials")
    assert response.status_code==200 and response.json()['retention_days']==17
    path=tmp_path/'legacy.env';path.write_text('')
    try:
        with db() as c:
            c.execute('ALTER TABLE application_settings_state DISABLE TRIGGER application_settings_state_immutable')
            c.execute("UPDATE application_settings_state SET installation_kind='upgrade'")
            c.execute('ALTER TABLE application_settings_state ENABLE TRIGGER application_settings_state_immutable')
        with pytest.raises(migration.MigrationInvalid,match='migration_incomplete'):maintenance._run_cleanup_pass(dry_run=True)
        apply_plan(plan_for(path),path)
        assert maintenance._run_cleanup_pass(dry_run=True)[1]>0
    finally:
        with db() as c:
            c.execute('ALTER TABLE application_settings_state DISABLE TRIGGER application_settings_state_immutable')
            c.execute("UPDATE application_settings_state SET installation_kind='fresh'")
            c.execute('ALTER TABLE application_settings_state ENABLE TRIGGER application_settings_state_immutable')
