"""Phase 4 offline migration and database-only consumer acceptance."""
import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
import pytest

from backend.services.api.application_settings_migration import (
    MIGRATED_KEYS, GENERAL_INTERFACE_KEYS, MIGRATION_ID, MigrationInvalid, preview, apply_preview, readiness, source_values,
)
from backend.services.api.tests.test_application_settings import db, items, save

ROOT=Path(__file__).resolve().parents[4]


def source_file(tmp_path, **changes):
    values={'DEFAULT_WORKING_TIMEZONE':'UTC','DEFAULT_ROOT_AGGREGATION_MEDIUM':'digital',
            'REVIEW_WARNING_WINDOW_DAYS':'2','DASHBOARD_FAVOURITE_ITEM_LIMIT':'2',
            'DASHBOARD_RECENT_ITEM_LIMIT':'3','DASHBOARD_RECENT_DAYS':'14',
            'DASHBOARD_REVIEW_PREVIEW_LIMIT':'2','CLASSIFICATION_RECENT_SELECTION_LIMIT':'6',
            'USER_DETAILS_SESSION_LIMIT':'8',**changes}
    path=tmp_path/'legacy.env';path.write_text('DATABASE_URL=do-not-import-private-credential\n'+''.join(f'{k}={v}\n' for k,v in values.items()))
    return path


def plan_for(path, **options):
    with db() as c:return preview(c,source_values(path),**options)


def apply_plan(plan,path,user_id=1):
    with db() as c:return apply_preview(c,plan,source_values(path),user_id=user_id,reason='Review Phase 4 legacy settings')


def completions():
    with db() as c:return c.execute('SELECT key FROM application_settings_migration_keys WHERE migration_id=%s',(MIGRATION_ID,)).fetchall()


def test_preview_is_read_only_and_apply_preserves_custom_values_file_and_safe_audit(client,tmp_path):
    path=source_file(tmp_path);before=path.read_bytes();original=items(client)
    with db() as c:
        c.execute('SET TRANSACTION READ ONLY');plan=preview(c,source_values(path));assert not readiness(c,source_values(path))['ready']
    assert not plan['issues'] and 'do-not-import-private' not in json.dumps(plan)
    assert items(client)==original and completions()==[] and path.read_bytes()==before
    apply_plan(plan,path)
    assert len(completions())==len(MIGRATED_KEYS) and path.read_bytes()==before
    for row in plan['items']:assert items(client)[row['key']]['value']==row['proposed_value']
    with db() as c:
        assert readiness(c,source_values(path))['ready']
        events=c.execute("SELECT source,metadata FROM event_history WHERE entity_type='application_setting' AND operation='APPLICATION_SETTINGS_MIGRATION_COMPLETED'").fetchall()
        assert len(events)==len(MIGRATED_KEYS) and all(e['source']=='migration' for e in events)
        assert all(set(e['metadata'])=={'setting_key','migration_id'} for e in events)


def test_completed_rerun_ignores_later_env_edits_and_missing_values_preserve_configured_defaults(client,tmp_path):
    assert save(client,{'DASHBOARD_RECENT_ITEM_LIMIT':4}).status_code==200
    path=tmp_path/'legacy.env';path.write_text('DEFAULT_WORKING_TIMEZONE=UTC\n')
    plan=plan_for(path);row=next(r for r in plan['items'] if r['key']=='DASHBOARD_RECENT_ITEM_LIMIT')
    assert row['action']=='keep_database' and row['provenance']=='configured'
    apply_plan(plan,path);before=items(client)
    assert save(client,{'REVIEW_WARNING_WINDOW_DAYS':99}).status_code==200
    path.write_text('DEFAULT_WORKING_TIMEZONE=invalid-sensitive-value\nREVIEW_WARNING_WINDOW_DAYS=5\n')
    apply_plan(plan,path)
    assert items(client)['REVIEW_WARNING_WINDOW_DAYS']['value']==99
    assert items(client)['DEFAULT_WORKING_TIMEZONE']==before['DEFAULT_WORKING_TIMEZONE']
    assert len(completions())==len(MIGRATED_KEYS)


def test_conflicts_invalid_inputs_and_explicit_resolutions_are_governed(client,tmp_path):
    assert save(client,{'REVIEW_WARNING_WINDOW_DAYS':30}).status_code==200
    path=source_file(tmp_path,DEFAULT_WORKING_TIMEZONE='invalid-private-value')
    plan=plan_for(path);assert {i['code'] for i in plan['issues']}=={'legacy_value_invalid','configured_value_conflict'}
    assert 'invalid-private-value' not in json.dumps(plan)
    with pytest.raises(MigrationInvalid):apply_plan(plan,path)
    assert completions()==[] and items(client)['REVIEW_WARNING_WINDOW_DAYS']['value']==30
    kept=plan_for(path,keep_database=['DEFAULT_WORKING_TIMEZONE','REVIEW_WARNING_WINDOW_DAYS'])
    apply_plan(kept,path);assert items(client)['REVIEW_WARNING_WINDOW_DAYS']['value']==30


def test_explicit_legacy_conflict_choice_checks_authority_and_records_migration_source(client,tmp_path):
    assert save(client,{'REVIEW_WARNING_WINDOW_DAYS':80}).status_code==200
    path=source_file(tmp_path);plan=plan_for(path,use_legacy=['REVIEW_WARNING_WINDOW_DAYS'])
    with pytest.raises(MigrationInvalid,match='settings_authority_required'):apply_plan(plan,path,user_id=999999)
    apply_plan(plan,path)
    assert items(client)['REVIEW_WARNING_WINDOW_DAYS']['value']==2
    with db() as c:
        event=c.execute("SELECT source,actor_user_id,reason FROM event_history WHERE entity_type='application_setting' AND operation='APPLICATION_SETTING_CHANGED' AND metadata->>'setting_key'='REVIEW_WARNING_WINDOW_DAYS' ORDER BY id DESC LIMIT 1").fetchone()
        assert event['source']=='migration' and event['actor_user_id']==1 and event['reason']=='Review Phase 4 legacy settings'


def test_stale_preview_and_audit_failure_roll_back_values_and_completion(client,tmp_path):
    path=source_file(tmp_path);plan=plan_for(path)
    assert save(client,{'DASHBOARD_RECENT_DAYS':15}).status_code==200
    with pytest.raises(MigrationInvalid,match='preview_stale'):apply_plan(plan,path)
    assert completions()==[]
    plan=plan_for(path,keep_database=['DASHBOARD_RECENT_DAYS']);before=items(client)
    with db() as c:
        with pytest.raises(psycopg.Error):
            with c.transaction():
                c.execute("CREATE FUNCTION pg_temp.reject_completion() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.operation='APPLICATION_SETTINGS_MIGRATION_COMPLETED' THEN RAISE EXCEPTION 'fixture audit failure'; END IF; RETURN NEW; END $$")
                c.execute('CREATE TRIGGER phase4_reject_completion BEFORE INSERT ON event_history FOR EACH ROW EXECUTE FUNCTION pg_temp.reject_completion()')
                apply_preview(c,plan,source_values(path),user_id=1,reason='Audit rollback fixture')
    assert items(client)==before and completions()==[]


def test_upgrade_readiness_and_cross_database_plan_isolation(client,tmp_path):
    path=source_file(tmp_path);plan=plan_for(path)
    with db() as c:
        c.execute('ALTER TABLE application_settings_state DISABLE TRIGGER application_settings_state_immutable')
        c.execute("UPDATE application_settings_state SET installation_kind='upgrade'")
        assert not readiness(c)['ready'] and set(readiness(c)['pending'])==set(MIGRATED_KEYS)
        c.rollback()  # Upgrade-state probe is confined to this disposable transaction.
    name='erms_messaging_test_acl_'+uuid4().hex
    admin_url=make_conninfo(os.environ['DATABASE_URL'],dbname='postgres');other_url=make_conninfo(os.environ['DATABASE_URL'],dbname=name)
    created=False
    try:
        with psycopg.connect(admin_url,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        created=True;print('Created disposable isolation database '+name)
        with psycopg.connect(other_url,row_factory=dict_row) as c:
            c.execute((ROOT/'database/schema.sql').read_text(),prepare=False);c.commit()
            with pytest.raises(MigrationInvalid,match='preview_target_changed'):apply_preview(c,plan,source_values(path),user_id=1,reason='Wrong target rejected')
            c.rollback()
            assert readiness(c)['ready'] and not readiness(c,source_values(path))['ready']
    finally:
        if created:
            with psycopg.connect(admin_url,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
            print('Dropped disposable isolation database '+name)
    assert completions()==[]


def test_cli_runs_before_services_never_imports_unrelated_settings_and_checks_readiness(client,tmp_path):
    path=source_file(tmp_path);plan_path=tmp_path/'review.json';before=path.read_bytes()
    base=[sys.executable,str(ROOT/'tools/migrate_application_settings.py'),'--database-url',os.environ['DATABASE_URL'],'--source-env',str(path)]
    result=subprocess.run([*base,'--check'],capture_output=True,text=True)
    assert result.returncode==1 and '--preview' in result.stderr and '--apply' in result.stderr
    result=subprocess.run([*base,'--preview','--plan',str(plan_path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'do-not-import-private' not in result.stdout and completions()==[]
    result=subprocess.run([*base,'--apply','--plan',str(plan_path),'--actor-user-id','1','--reason','Reviewed offline migration'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert subprocess.run([*base,'--check'],capture_output=True).returncode==0
    assert path.read_bytes()==before


def test_runtime_timezone_medium_dashboard_and_public_subset_ignore_old_env(client,monkeypatch):
    for key in MIGRATED_KEYS:monkeypatch.setenv(key,'invalid-old-environment')
    assert save(client,{'DEFAULT_WORKING_TIMEZONE':'UTC','DEFAULT_ROOT_AGGREGATION_MEDIUM':'digital','REVIEW_WARNING_WINDOW_DAYS':2,'DASHBOARD_REVIEW_PREVIEW_LIMIT':2,'DASHBOARD_RECENT_ITEM_LIMIT':3}).status_code==200
    bootstrap=client.get('/api/v1/i18n/bootstrap').json()
    assert bootstrap['working_timezone']=='UTC' and set(bootstrap['application_configuration'])==set(GENERAL_INTERFACE_KEYS)
    assert client.get('/api/v1/application-configuration').json()==bootstrap['application_configuration']
    for i in range(5):
        result=client.post('/api/v1/aggregations',json={'aggregation_number':f'PH4-{i}','title':f'Phase 4 root {i}','classification_id':1,'date_of_next_review':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
        assert result.status_code==201,result.text
        assert result.json()['medium']=='digital'
    summary=client.get('/api/v1/dashboard/summary').json()
    assert summary['review_warning_window_days']==2 and len(summary['recent_activity'])<=3
    assert summary['application_configuration']['DASHBOARD_REVIEW_PREVIEW_LIMIT']==2
    assert summary['upcoming_review_count']>=5 and len(summary['upcoming_reviews'])==2
    assert save(client,{'REVIEW_WARNING_WINDOW_DAYS':0}).status_code==200
    assert client.get('/api/v1/dashboard/summary').json()['upcoming_review_count']==0
    assert save(client,{'REVIEW_WARNING_WINDOW_DAYS':9223372036854775807}).status_code==200
    huge=client.get('/api/v1/dashboard/summary')
    assert huge.status_code==200,huge.text
    assert huge.json()['upcoming_review_count']>=5
    assert client.get('/api/v1/dashboard/reviews',params={'state':'upcoming','limit':2}).status_code==200
    assert save(client,{'DEFAULT_WORKING_TIMEZONE':'Asia/Tokyo','DEFAULT_ROOT_AGGREGATION_MEDIUM':'physical'}).status_code==200
    assert client.get('/api/v1/i18n/bootstrap').json()['working_timezone']=='Asia/Tokyo'
    result=client.post('/api/v1/aggregations',json={'aggregation_number':'PH4-NEXT','title':'Next default','classification_id':1})
    assert result.status_code==201 and result.json()['medium']=='physical'


def test_saved_timezone_preference_is_preserved_when_shared_default_changes(client):
    before=client.get('/api/v1/preferences').json()
    result=client.put('/api/v1/preferences',headers={'If-Match':str(before['version'])},json={'language_tag':'en','working_timezone':'Europe/Paris'})
    assert result.status_code==200,result.text
    assert save(client,{'DEFAULT_WORKING_TIMEZONE':'Asia/Tokyo'}).status_code==200
    bootstrap=client.get('/api/v1/i18n/bootstrap').json()
    assert bootstrap['working_timezone']=='Europe/Paris' and bootstrap['uses_default_working_timezone'] is False
    assert bootstrap['application_configuration']['DEFAULT_WORKING_TIMEZONE']=='Asia/Tokyo'


def test_recent_selector_and_session_pages_use_runtime_limits_without_large_downloads(client):
    with db() as c:
        c.execute("SELECT set_config('app.event_source','seeding',true)")
        branch=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'PH4-B','Phase 4 branch',false) RETURNING id").fetchone()['id']
        c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')",(branch,))
        rows=c.execute("INSERT INTO classifications(classification_scheme_id,parent_classification_id,code,title,is_terminal) SELECT 1,%s,'PH4-'||i,'Terminal '||i,true FROM generate_series(1,10) i RETURNING id",(branch,)).fetchall()
        for row in rows:c.execute('INSERT INTO user_classification_selections(user_id,classification_id) VALUES(1,%s)',(row['id'],))
    assert save(client,{'CLASSIFICATION_RECENT_SELECTION_LIMIT':6,'USER_DETAILS_SESSION_LIMIT':8}).status_code==200
    assert len(client.get('/api/v1/classifications/recent').json())==6
    assert len(client.get('/api/v1/classifications/recent',params={'offset':5}).json())==1
    assert client.get('/api/v1/auth/sessions/page',params={'user_id':1}).json()['limit']==8
    assert save(client,{'CLASSIFICATION_RECENT_SELECTION_LIMIT':3,'USER_DETAILS_SESSION_LIMIT':9007199254740993}).status_code==200
    assert len(client.get('/api/v1/classifications/recent').json())==3
    assert client.get('/api/v1/auth/sessions/page',params={'user_id':1}).json()['limit']==50


def test_api_startup_blocks_unreviewed_upgrade_then_accepts_completed_migration(client,tmp_path):
    path=source_file(tmp_path);plan=plan_for(path)
    def installation(kind):
        with db() as c:
            c.execute('ALTER TABLE application_settings_state DISABLE TRIGGER application_settings_state_immutable')
            c.execute('UPDATE application_settings_state SET installation_kind=%s',(kind,))
            c.execute('ALTER TABLE application_settings_state ENABLE TRIGGER application_settings_state_immutable')
    probe="from fastapi.testclient import TestClient; from backend.services.api.main import app\ntry:\n with TestClient(app): pass\nexcept RuntimeError as e:\n print(str(e)); raise SystemExit(3)"
    try:
        installation('upgrade')
        result=subprocess.run([sys.executable,'-c',probe],capture_output=True,text=True)
        assert result.returncode==3 and 'application_settings_migration_incomplete' in result.stdout,result.stderr
        apply_plan(plan,path)
        result=subprocess.run([sys.executable,'-c',probe],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    finally:installation('fresh')
