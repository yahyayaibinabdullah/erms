"""061 canonical/upgrade parity and preservation; uniquely disposable DBs only."""
from pathlib import Path
from uuid import uuid4
import os
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
from tools.check_disposition_approval_upgrade import full_catalogue
from tools.check_disposition_routing_upgrade import fixtures

ROOT=Path(__file__).resolve().parents[1]
MARKER='-- Preserve review claims across save transactions (061).\n'


def snapshot(c):
    result={}
    for schema,table in c.execute("SELECT schemaname,tablename FROM pg_tables WHERE schemaname IN ('public','disposition_private') AND tablename<>'schema_migrations' ORDER BY 1,2").fetchall():
        result[schema+'.'+table]=c.execute(sql.SQL('SELECT to_jsonb(r) FROM {}.{} r ORDER BY to_jsonb(r)::text').format(sql.Identifier(schema),sql.Identifier(table))).fetchall()
    return result


def main():
    config={**dotenv_values(ROOT/'.env'),**os.environ};base=config['DATABASE_URL'];admin=make_conninfo(base,dbname='postgres')
    schema=(ROOT/'database/schema.sql').read_text().split('-- External requests and decisions (062).\n',1)[0];migration=(ROOT/'database/migrations/061_disposition_review_save.sql').read_text();assert schema.split(MARKER,1)[1]==migration
    names=[]
    try:
        for kind in ('fresh','upgrade'):
            name='erms_disposition16_test_'+kind+'_'+uuid4().hex
            with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            names.append(name);print('Created disposable database '+name,flush=True)
            with psycopg.connect(make_conninfo(base,dbname=name)) as c:
                if kind=='fresh':c.execute(schema,prepare=False);c.commit();catalogue=full_catalogue(c)
                else:
                    baseline=schema.split(MARKER,1)[0]
                    c.execute(baseline.split('-- Disposition governed artifacts (056).',1)[0],prepare=False);c.commit();fixtures(c)
                    for version in ('058_disposition_routing','059_disposition_review','060_disposition_approval'):
                        c.execute((ROOT/'database/migrations'/f'{version}.sql').read_text(),prepare=False);c.commit()
                    before=snapshot(c);c.execute(migration,prepare=False);c.commit()
                    assert snapshot(c)==before,'Existing rows changed during 061'
                    assert full_catalogue(c)==catalogue,'Canonical/upgraded catalogue mismatch'
                    print('Passed: 060/061 catalogue parity and every existing table row preserved.',flush=True)
    finally:
        failures=[]
        for name in reversed(names):
            try:
                with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)
            except Exception as e:failures.append((name,type(e).__name__))
        if failures:raise RuntimeError('Disposable database cleanup failed: '+repr(failures))


if __name__=='__main__':main()
