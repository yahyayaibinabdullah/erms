"""Independent canonical/057 parity and byte-for-byte upgrade preservation."""
import os
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
from tools.check_disposition_artifacts_upgrade import full_catalogue,legacy_evidence

ROOT=Path(__file__).resolve().parents[1]
MARKER='-- Disposition controlled templates (057).\n'


def snapshot(c):
    tables=['aggregations','records','digital_components','digital_component_content_sets','digital_component_blobs',
      'event_history','application_settings','disposition_jobs','disposition_job_documents','disposition_private.command_receipts']
    return {table:c.execute(sql.SQL('SELECT to_jsonb(t) FROM {} t ORDER BY {}').format(sql.Identifier(*table.split('.')),sql.Identifier('command_id' if table.endswith('receipts') else 'id'))).fetchall() for table in tables}


def main():
    config={**dotenv_values(ROOT/'.env'),**os.environ};base=config['DATABASE_URL'];admin_url=make_conninfo(base,dbname='postgres')
    schema=(ROOT/'database/schema.sql').read_text().split('-- Destruction routing and shared tasks (058).',1)[0].rstrip()+'\n';migration=(ROOT/'database/migrations/057_disposition_templates.sql').read_text()
    assert schema.split(MARKER,1)[1]==migration
    names=[]
    try:
        for kind in ('fresh','upgrade'):
            name='erms_disposition12_test_'+kind+'_'+uuid4().hex
            with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            names.append(name);print('Created disposable database '+name,flush=True)
            with psycopg.connect(make_conninfo(base,dbname=name)) as c:
                if kind=='fresh':c.execute(schema,prepare=False);c.commit();fresh=full_catalogue(c)
                else:
                    old=schema.split('-- Disposition governed artifacts (056).',1)[0]
                    c.execute(old,prepare=False);c.commit();legacy_evidence(c);c.commit()
                    c.execute((ROOT/'database/migrations/056_disposition_artifacts.sql').read_text(),prepare=False);c.commit();before=snapshot(c)
                    c.execute(migration,prepare=False);c.commit()
                    assert snapshot(c)==before,'Existing evidence, resources, receipts, settings or history changed'
                    assert full_catalogue(c)==fresh,'Canonical/057 catalogue mismatch'
                    assert c.execute('SELECT count(*) FROM disposition_template_revisions').fetchone()[0]==0
                    print('Passed: exact canonical/057 catalogue parity; all earlier evidence bytes, links, provenance, settings, jobs, command receipts and immutable history preserved; no defaults disguised as migration seeds.',flush=True)
    finally:
        failures=[]
        for name in reversed(names):
            try:
                with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)
            except Exception as error:failures.append((name,type(error).__name__))
        if failures:raise RuntimeError('Disposable database cleanup failed: '+repr(failures))


if __name__=='__main__':main()
