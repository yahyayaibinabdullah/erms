"""063 canonical/upgrade parity and prior-row preservation; disposable databases only."""
from pathlib import Path
from uuid import uuid4
import os,sys,subprocess
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
from tools.check_disposition_approval_upgrade import full_catalogue
from tools.check_disposition_routing_upgrade import fixtures

MARKER='-- External document email and reminders (063).\n'


from tools.historical_schema import historical_schema
from tools.historical_schema import PRE_CONSOLIDATION_REF


def snapshot(c):
    result={}
    for schema,table in c.execute("SELECT schemaname,tablename FROM pg_tables WHERE schemaname IN ('public','disposition_private') AND tablename<>'schema_migrations' ORDER BY 1,2").fetchall():
        result[schema+'.'+table]=c.execute(sql.SQL('SELECT to_jsonb(r)-%s::text[] FROM {}.{} r ORDER BY (to_jsonb(r)-%s::text[])::text').format(sql.Identifier(schema),sql.Identifier(table)),(['request_document_id'] if table=='disposition_tasks' else [],)*2).fetchall()
    return result


def main():
    base={**dotenv_values(ROOT/'.env'),**os.environ}['DATABASE_URL'];admin=make_conninfo(base,dbname='postgres')
    schema=historical_schema().split('\n-- Physical preparation and confirmation (064).',1)[0];migration=(ROOT/'database/migrations/063_disposition_communications.sql').read_text()
    assert schema.split(MARKER,1)[1]==migration
    baseline=subprocess.check_output(['git','show',PRE_CONSOLIDATION_REF+':database/schema.sql'],cwd=ROOT,text=True)
    phase17=(baseline+'-- External requests and decisions (062).\n'+(ROOT/'database/migrations/062_disposition_external_approval.sql').read_text()).rstrip()
    assert schema.split(MARKER,1)[0].rstrip()==phase17,'Earlier canonical schema changed'
    names=[]
    try:
        for kind in ('fresh','upgrade'):
            name='erms_disposition18_test_'+kind+'_'+uuid4().hex
            with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            names.append(name);print('Created disposable database '+name,flush=True)
            with psycopg.connect(make_conninfo(base,dbname=name)) as c:
                if kind=='fresh':c.execute(schema,prepare=False);c.commit();catalogue=full_catalogue(c)
                else:
                    c.execute(baseline.split('-- Disposition governed artifacts (056).',1)[0],prepare=False);c.commit();fixtures(c)
                    for version in ('058_disposition_routing','059_disposition_review','060_disposition_approval','061_disposition_review_save'):
                        c.execute((ROOT/'database/migrations'/f'{version}.sql').read_text(),prepare=False);c.commit()
                    c.execute("SELECT set_config('app.user_id','1',true),set_config('app.actor_type','user',true),set_config('app.event_source','seeding',true)")
                    role=c.execute("SELECT id FROM roles WHERE code='legacy-officer'").fetchone()[0]
                    c.execute("SELECT disposition_private.begin_command(%s,'review_decide','{\"job_id\":1}',%s,'Preserve supplied legacy number')",(uuid4(),role))
                    c.execute("UPDATE disposition_jobs SET destruction_number='LEGACY / #1' WHERE id=1")
                    c.execute("SELECT disposition_private.finish_command('{}')");c.commit()
                    c.execute((ROOT/'database/migrations/062_disposition_external_approval.sql').read_text(),prepare=False);c.commit()
                    before=snapshot(c);c.execute(migration,prepare=False);c.commit();after=snapshot(c)
                    assert all(after[table]==rows for table,rows in before.items()),'Existing row values changed during 063'
                    assert c.execute('SELECT number,job_id FROM disposition_private.destruction_numbers').fetchall()==[('LEGACY / #1',1)]
                    assert full_catalogue(c)==catalogue,'Canonical/upgraded catalogue mismatch'
                    print('Passed: 062/063 complete catalogue parity; every pre-existing row preserved; legacy number permanently reserved.',flush=True)
    finally:
        failures=[]
        for name in reversed(names):
            try:
                with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)
            except Exception as error:failures.append((name,type(error).__name__))
        if failures:raise RuntimeError('Disposable cleanup failed: '+repr(failures))


if __name__=='__main__':main()
