"""066–068 parity and historical row preservation, exclusively in disposable databases."""
from pathlib import Path
from uuid import uuid4
import os,sys,subprocess
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
from tools.check_disposition_approval_upgrade import full_catalogue as prior_catalogue
from tools.check_disposition_routing_upgrade import fixtures
MARKER='-- Durable digital destruction runs (066).\n'


from tools.historical_schema import historical_schema
from tools.historical_schema import PRE_CONSOLIDATION_REF


def full_catalogue(c):
    result=prior_catalogue(c)
    result['hold_guard']=c.execute("SELECT pg_get_functiondef('protect_held_resource()'::regprocedure)").fetchall()
    result['private_table_privileges']=c.execute("SELECT c.relname,c.relacl::text FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='disposition_private' AND c.relkind='r' ORDER BY 1").fetchall()
    result['all_functions']=c.execute("SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid),p.proacl::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('public','disposition_private') AND p.prokind='f' AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e') ORDER BY 1,2,3").fetchall()
    result['all_views']=c.execute("SELECT schemaname,viewname,definition FROM pg_views WHERE schemaname IN ('public','disposition_private') ORDER BY 1,2").fetchall()
    return result


def snapshot(c):
    # Compare every field of every pre-existing row, including request linkage.
    result={}
    for schema,table in c.execute("SELECT schemaname,tablename FROM pg_tables WHERE schemaname IN ('public','disposition_private') AND tablename<>'schema_migrations' ORDER BY 1,2").fetchall():
        result[schema+'.'+table]=c.execute(sql.SQL('SELECT to_jsonb(r) FROM {}.{} r ORDER BY to_jsonb(r)::text').format(sql.Identifier(schema),sql.Identifier(table))).fetchall()
    return result


def main():
    base={**dotenv_values(ROOT/'.env'),**os.environ}['DATABASE_URL'];admin=make_conninfo(base,dbname='postgres')
    schema=historical_schema();migrations=[(ROOT/'database/migrations'/name).read_text() for name in ('066_disposition_destruction_runs.sql','067_disposition_content_erasure.sql','068_disposition_retained_records.sql')]
    baseline=subprocess.check_output(['git','show',PRE_CONSOLIDATION_REF+':database/schema.sql'],cwd=ROOT,text=True)
    assert schema.split(MARKER,1)[1]==migrations[0]+'\n-- Controlled storage erasure (067).\n'+migrations[1]+'\n-- Retained disposition records (068).\n'+migrations[2]
    assert schema.split(MARKER,1)[0].rstrip()==baseline.rstrip(),'Earlier canonical schema changed'
    names=[]
    try:
        for kind in ('fresh','upgrade'):
            name='erms_disposition21_test_'+kind+'_'+uuid4().hex
            with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            names.append(name);print('Created disposable database '+name,flush=True)
            with psycopg.connect(make_conninfo(base,dbname=name)) as c:
                if kind=='fresh':c.execute(schema,prepare=False);c.commit();catalogue=full_catalogue(c)
                else:
                    c.execute(baseline.split('-- Disposition governed artifacts (056).',1)[0],prepare=False);c.commit();fixtures(c)
                    for version in ('058_disposition_routing','059_disposition_review','060_disposition_approval','061_disposition_review_save','062_disposition_external_approval','063_disposition_communications','064_disposition_physical','065_disposition_recovery'):
                        c.execute((ROOT/'database/migrations'/f'{version}.sql').read_text(),prepare=False);c.commit()
                    before=snapshot(c)
                    for migration in migrations:c.execute(migration,prepare=False);c.commit()
                    after=snapshot(c)
                    assert all(after[table]==rows for table,rows in before.items()),'Pre-existing rows changed'
                    assert full_catalogue(c)==catalogue,'Canonical/upgraded catalogue mismatch'
                    print('Passed: canonical/066–068 complete catalogue parity and every prior public/private row preserved.',flush=True)
    finally:
        failures=[]
        for name in reversed(names):
            try:
                with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)
            except Exception as error:failures.append((name,type(error).__name__))
        if failures:raise RuntimeError('Disposable cleanup failed: '+repr(failures))


if __name__=='__main__':main()
