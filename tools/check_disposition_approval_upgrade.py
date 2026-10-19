"""Independent 059/060 upgrade parity and preservation in disposable databases."""
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
from tools.check_disposition_routing_upgrade import full_catalogue as routing_catalogue,fixtures

ROOT=Path(__file__).resolve().parents[1]
MARKER='-- Atomic proposal approval and execution (060).\n'


def full_catalogue(c):
    result=routing_catalogue(c)
    result['execution_audit_trigger']=c.execute("SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname='event_history_disposition_execution'").fetchall()
    result['audit_redaction_view']=c.execute("SELECT definition FROM pg_views WHERE schemaname='public' AND viewname='authorized_event_history'").fetchall()
    return result


def snapshot(c):
    tables=c.execute("""SELECT schemaname,tablename FROM pg_tables WHERE schemaname IN ('public','disposition_private') ORDER BY 1,2""").fetchall()
    omitted={'schema_migrations'}
    result={}
    for schema,table in tables:
        if table in omitted:continue
        removed=['approval_execution'] if table=='disposition_review_rounds' else []
        result[schema+'.'+table]=c.execute(sql.SQL('SELECT to_jsonb(r)-%s::text[] AS row FROM {}.{} r ORDER BY (to_jsonb(r)-%s::text[])::text').format(sql.Identifier(schema),sql.Identifier(table)),(removed,removed)).fetchall()
    return result


def main():
    configuration={**dotenv_values(ROOT/'.env'),**os.environ};base=configuration['DATABASE_URL'];admin_url=make_conninfo(base,dbname='postgres')
    schema=(ROOT/'database/schema.sql').read_text().split('-- Preserve review claims across save transactions (061).',1)[0].rstrip()+'\n';migration=(ROOT/'database/migrations/060_disposition_approval.sql').read_text()
    assert schema.split(MARKER,1)[1]==migration
    baseline=schema.split(MARKER,1)[0]
    names=[]
    try:
        for kind in ('fresh','upgrade'):
            name='erms_disposition15_test_'+kind+'_'+uuid4().hex
            with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            names.append(name);print('Created disposable database '+name,flush=True)
            with psycopg.connect(make_conninfo(base,dbname=name)) as c:
                if kind=='fresh':c.execute(schema,prepare=False);c.commit();fresh=full_catalogue(c)
                else:
                    c.execute(baseline.split('-- Disposition governed artifacts (056).',1)[0],prepare=False);c.commit();fixtures(c)
                    c.execute((ROOT/'database/migrations/058_disposition_routing.sql').read_text(),prepare=False);c.commit()
                    c.execute((ROOT/'database/migrations/059_disposition_review.sql').read_text(),prepare=False);c.commit()
                    before=snapshot(c);c.execute(migration,prepare=False);c.commit();after=snapshot(c)
                    assert all(after[t]==rows for t,rows in before.items()),'Existing database rows changed'
                    assert full_catalogue(c)==fresh,'Canonical/059 catalogue mismatch'
                    assert all(c.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(*t.split('.')))).fetchone()[0]==0 for t in ('disposition_proposal_effects','disposition_private.approval_context'))
                    print('Passed: 059/060 upgrade, canonical catalogue parity; all existing rows, evidence bytes, tasks, templates, receipts, settings, and immutable audit preserved.',flush=True)
    finally:
        failures=[]
        for name in reversed(names):
            try:
                with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)
            except Exception as error:failures.append((name,type(error).__name__))
        if failures:raise RuntimeError('Disposable database cleanup failed: '+repr(failures))


if __name__=='__main__':main()
