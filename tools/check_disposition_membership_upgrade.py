"""Phase 9 latest-schema/independent-055 parity and preservation in disposable DBs."""
import os
from pathlib import Path
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
from tools.check_disposition_foundation_upgrade import baseline_data,catalogue
from tools.check_disposition_eligibility_upgrade import existing_command

ROOT=Path(__file__).resolve().parents[1]
MARKER='-- Disposition membership and atomic recalculation (055).\n'


def snapshot(c):
    tables=['aggregations','records','org_units','roles','users','user_role_assignments','event_history','profile_privileges','application_settings',
            'disposition_jobs','disposition_job_memberships','disposition_tasks','disposition_review_rounds','disposition_review_decisions','disposition_job_documents','disposition_private.command_receipts']
    result={}
    for table in tables:
        relation=sql.Identifier(*table.split('.'));order=sql.Identifier('command_id' if table.endswith('command_receipts') else 'id')
        omitted=['removal_required','removal_required_reason'] if table=='disposition_job_memberships' else []
        result[table]=c.execute(sql.SQL('SELECT to_jsonb(t)-%s::text[] FROM {} t ORDER BY {}').format(relation,order),(omitted,)).fetchall()
    return result


def full_catalogue(c):
    data=catalogue(c)
    data['policy_triggers']=c.execute("SELECT cl.relname,t.tgname,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class cl ON cl.oid=t.tgrelid WHERE NOT t.tgisinternal AND cl.relname IN ('classifications','aggregation_retention_rules','classification_retention_rules') ORDER BY 1,2").fetchall()
    data['hold_guard']=c.execute("SELECT pg_get_functiondef('protect_held_resource()'::regprocedure)").fetchone()
    data['private_acl']=c.execute("SELECT c.relname,c.relacl::text FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='disposition_private' AND c.relkind='r' ORDER BY 1").fetchall()
    return data


def existing_membership(c):
    # Pre-055 common primitives are intentionally used as the upgrade fixture.
    role=c.execute("SELECT id FROM roles WHERE code='existing'").fetchone()[0]
    c.execute("SELECT disposition_private.begin_command(%s,'eligibility_evaluate','{}',%s,'Pre-upgrade eligible state')",(uuid.uuid4(),role))
    version=c.execute('SELECT version FROM aggregations WHERE id=1').fetchone()[0]
    c.execute('SELECT disposition_private.transition_unit(1,%s,2)',(version,));c.execute("SELECT disposition_private.finish_command('{}')")
    c.execute("SELECT disposition_private.begin_command(%s,'membership_add','{}',%s,'Pre-upgrade active membership')",(uuid.uuid4(),role))
    c.execute('INSERT INTO disposition_job_memberships(job_id,root_aggregation_id,added_by_user_id) VALUES(1,1,1)')
    version=c.execute('SELECT version FROM aggregations WHERE id=1').fetchone()[0]
    c.execute('SELECT disposition_private.transition_unit(1,%s,6)',(version,));c.execute("SELECT disposition_private.finish_command('{}')")


def main():
    config={**dotenv_values(ROOT/'.env'),**os.environ};base=config['DATABASE_URL'];admin_url=make_conninfo(base,dbname='postgres')
    schema=(ROOT/'database/schema.sql').read_text();old=schema.split(MARKER)[0]
    migration=(ROOT/'database/migrations/055_disposition_membership.sql').read_text();assert schema.split(MARKER,1)[1]==migration
    names=[]
    try:
        for kind in ['fresh','upgrade']:
            name='erms_disposition9_test_'+kind+'_'+uuid.uuid4().hex
            with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            names.append(name);print('Created disposable database '+name,flush=True)
            with psycopg.connect(make_conninfo(base,dbname=name)) as c:
                c.execute(schema if kind=='fresh' else old,prepare=False);c.commit()
                if kind=='upgrade':
                    baseline_data(c);existing_command(c);existing_membership(c);c.commit();before=snapshot(c)
                    c.execute(migration,prepare=False);c.commit()
                    assert snapshot(c)==before,'existing state/history changed during 055'
                    assert c.execute('SELECT removal_required,removal_required_reason FROM disposition_job_memberships').fetchall()==[(False,None)]
                    assert full_catalogue(c)==fresh,'fresh/upgrade catalogue mismatch'
                    print('Passed: exact catalogue parity and prior active membership, job, receipts, resources, settings, identity, grants and history preservation',flush=True)
                else:fresh=full_catalogue(c)
    finally:
        failures=[]
        for name in reversed(names):
            try:
                with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)
            except Exception as error:failures.append((name,type(error).__name__))
        if failures:raise RuntimeError('Disposable database cleanup failed: '+repr(failures))


if __name__=='__main__':main()
