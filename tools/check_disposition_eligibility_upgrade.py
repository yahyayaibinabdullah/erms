"""Phase 8 fresh/upgrade parity and immutable existing-data verification."""
import os
from pathlib import Path
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
from tools.check_disposition_foundation_upgrade import baseline_data,catalogue

ROOT=Path(__file__).resolve().parents[1]
MARKER='-- Disposition eligibility and current blockers (054).\n'


def snapshot(c):
    tables=['aggregations','records','org_units','roles','users','user_role_assignments','event_history','profile_privileges','application_settings',
            'disposition_jobs','disposition_job_memberships','disposition_tasks','disposition_review_rounds','disposition_review_decisions','disposition_job_documents','disposition_private.command_receipts']
    result={}
    for table in tables:
        relation=sql.Identifier(*table.split('.'))
        order=sql.Identifier('command_id' if table.endswith('command_receipts') else 'id')
        result[table]=c.execute(sql.SQL('SELECT to_jsonb(t)-%s::text[] FROM {} t ORDER BY {}').format(relation,order),(['actor_type'] if table.endswith('command_receipts') else [],)).fetchall()
    return result


def existing_command(c):
    c.execute("SELECT set_config('app.user_id','1',true),set_config('app.actor_type','user',true),set_config('app.event_source','api',true)")
    role=c.execute("SELECT id FROM roles WHERE code='existing'").fetchone()[0]
    command=uuid.uuid4()
    c.execute("SELECT disposition_private.begin_command(%s,'job_create','{}',%s,'Existing foundation job')",(command,role))
    c.execute("INSERT INTO disposition_jobs(job_number,job_type,workflow_stage,disposition_status,owning_org_unit_id,assigned_user_id,created_by_user_id) VALUES('EXISTING','destruction','officer_preparation',6,1,1,1)")
    c.execute("SELECT disposition_private.finish_command('{}')")


def main():
    config={**dotenv_values(ROOT/'.env'),**os.environ};base=config['DATABASE_URL']
    admin_url=make_conninfo(base,dbname='postgres')
    schema=(ROOT/'database/schema.sql').read_text().split('-- Disposition membership and atomic recalculation (055).',1)[0].rstrip()+'\n';old=schema.split(MARKER)[0]
    migration=(ROOT/'database/migrations/054_disposition_eligibility.sql').read_text()
    assert schema.split(MARKER,1)[1]==migration
    names=[]
    try:
        for kind in ['fresh','upgrade']:
            name='erms_disposition8_test_'+kind+'_'+uuid.uuid4().hex
            with psycopg.connect(admin_url,autocommit=True) as admin: admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            names.append(name); print('Created disposable database '+name,flush=True)
            with psycopg.connect(make_conninfo(base,dbname=name)) as c:
                c.execute(schema if kind=='fresh' else old,prepare=False);c.commit()
                if kind=='upgrade':
                    baseline_data(c);existing_command(c);c.commit();before=snapshot(c)
                    c.execute(migration,prepare=False);c.commit();assert snapshot(c)==before,'pre-existing data/history changed'
                    # Include the legal-hold function whose narrow eligibility
                    # exception is also part of this upgrade.
                    current=catalogue(c)
                    current['hold_guard']=c.execute("SELECT pg_get_functiondef('protect_held_resource()'::regprocedure)").fetchone()
                    current['relationship_guards']=c.execute("SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname='disposition_relationship_coordination' ORDER BY tgrelid::regclass::text").fetchall()
                    assert current==fresh,'fresh/upgrade catalogue mismatch'
                    assert c.execute("SELECT DISTINCT actor_type FROM disposition_private.command_receipts").fetchall()==[('user',)]
                    print('Passed: catalogue parity and prior resources, commands, jobs, settings, grants and history preserved',flush=True)
                else:
                    fresh=catalogue(c)
                    fresh['hold_guard']=c.execute("SELECT pg_get_functiondef('protect_held_resource()'::regprocedure)").fetchone()
                    fresh['relationship_guards']=c.execute("SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname='disposition_relationship_coordination' ORDER BY tgrelid::regclass::text").fetchall()
    finally:
        failures=[]
        for name in reversed(names):
            try:
                with psycopg.connect(admin_url,autocommit=True) as admin: admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)
            except Exception as error: failures.append((name,type(error).__name__))
        if failures: raise RuntimeError('Disposable database cleanup failed: '+repr(failures))


if __name__=='__main__': main()
