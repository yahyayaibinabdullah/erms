"""Independent HEAD/058 upgrade, canonical parity and historical preservation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
from tools.check_disposition_artifacts_upgrade import legacy_evidence,full_catalogue as disposition_catalogue

ROOT=Path(__file__).resolve().parents[1]
MARKER='-- Destruction routing and shared tasks (058).\n'


from tools.historical_schema import historical_schema
from tools.historical_schema import PRE_CONSOLIDATION_REF


def full_catalogue(c):
    result=disposition_catalogue(c)
    result['messaging_snapshot_guard']=c.execute("SELECT pg_get_functiondef('messaging_snapshot_insert()'::regprocedure)").fetchall()
    return result


def snapshot(c):
    tables=['aggregations','records','digital_components','digital_component_content_sets','digital_component_blobs',
      'application_settings','disposition_jobs','disposition_job_documents','disposition_tasks','disposition_review_rounds',
      'disposition_review_decisions','disposition_template_revisions','disposition_private.command_receipts','event_history']
    return {t:c.execute(sql.SQL('SELECT to_jsonb(t)-%s::text[] FROM {} t ORDER BY {}').format(
      sql.Identifier(*t.split('.')),sql.Identifier('command_id' if t.endswith('receipts') else 'id')),
      (['review_route'] if t=='disposition_jobs' else ['routing_org_unit_id'] if t=='disposition_tasks' else [],)).fetchall() for t in tables}


def fixtures(c):
    # The prior evidence probe captures real pre-056 governed bytes and upgrades
    # through 057 before applying this migration. No persistent database is used.
    legacy_evidence(c);c.commit()
    for version in ('056_disposition_artifacts','057_disposition_templates'):
        c.execute((ROOT/'database/migrations'/f'{version}.sql').read_text(),prepare=False);c.commit()
    c.execute("SELECT set_config('app.user_id','1',true),set_config('app.actor_type','user',true),set_config('app.event_source','api',true)")
    role=c.execute("SELECT id FROM roles WHERE code='legacy-officer'").fetchone()[0]
    content=(ROOT/'templates/disposition/destruction/request-for-destruction.default.v1.docx').read_bytes()
    checksum=hashlib.sha256(content).hexdigest()
    payload={'template_upload':True,'checksum':checksum,'kind':'destruction_request','filename':'legacy.docx','job_id':1}
    c.execute("SELECT disposition_private.begin_command(%s,'document_save',%s,%s,'Preserve existing template')",(uuid4(),json.dumps(payload),role))
    c.execute("""INSERT INTO disposition_template_revisions(document_type,revision_number,original_filename,content,checksum,uploaded_by_user_id,acting_role_id,uploaded_from_job_id)
      VALUES('destruction_request',1,'legacy.docx',%s,%s,1,%s,1)""",(content,checksum,role))
    c.execute("SELECT disposition_private.finish_command('{}')")
    # Existing direct task must survive exactly; a second assigned job receives
    # its missing preparation task through a migration-attributed backfill.
    c.execute("SELECT disposition_private.begin_command(%s,'job_create','{}',%s,'Preserve existing task')",(uuid4(),role))
    c.execute("INSERT INTO disposition_tasks(job_id,task_type,workflow_stage,destination_user_id) VALUES(1,'preparation','officer_preparation',1)")
    c.execute("SELECT disposition_private.create_job('BACKFILL','destruction',1,1)")
    c.execute("SELECT disposition_private.finish_command('{}')");c.commit()


def main():
    base={**dotenv_values(ROOT/'.env'),**os.environ}['DATABASE_URL'];admin_url=make_conninfo(base,dbname='postgres')
    schema=historical_schema().split('-- Destruction proposals and review decisions (059).',1)[0].rstrip()+'\n';migration=(ROOT/'database/migrations/058_disposition_routing.sql').read_text()
    assert schema.split(MARKER,1)[1]==migration
    baseline=subprocess.check_output(['git','show',PRE_CONSOLIDATION_REF+':database/schema.sql'],cwd=ROOT,text=True)
    assert schema.split(MARKER,1)[0].rstrip()==baseline.rstrip(),'Earlier canonical schema was changed'
    names=[]
    try:
        for kind in ('fresh','upgrade'):
            name='erms_disposition13_test_'+kind+'_'+uuid4().hex
            with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            names.append(name);print('Created disposable database '+name,flush=True)
            with psycopg.connect(make_conninfo(base,dbname=name)) as c:
                if kind=='fresh':c.execute(schema,prepare=False);c.commit();fresh=full_catalogue(c)
                else:
                    c.execute(baseline.split('-- Disposition governed artifacts (056).',1)[0],prepare=False);c.commit();fixtures(c)
                    before=snapshot(c);c.execute(migration,prepare=False);c.commit();after=snapshot(c)
                    for table,rows in before.items():
                        assert after[table][:len(rows)]==rows,table+' historical content changed'
                    assert full_catalogue(c)==fresh,'Canonical/058 catalogue mismatch'
                    assert c.execute("SELECT count(*) FROM disposition_jobs WHERE review_route='standard'").fetchone()[0]==2
                    assert len(after['disposition_tasks'])==len(before['disposition_tasks'])+1
                    assert c.execute("SELECT source FROM event_history WHERE operation='TASK_ROUTED' ORDER BY id DESC LIMIT 1").fetchone()[0]=='migration'
                    print('Passed: HEAD/058 upgrade, canonical catalogue parity; existing evidence bytes, templates, jobs, tasks, receipts, settings and all earlier audit events preserved; missing direct task backfilled with migration attribution.',flush=True)
    finally:
        failures=[]
        for name in reversed(names):
            try:
                with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)
            except Exception as error:failures.append((name,type(error).__name__))
        if failures:raise RuntimeError('Disposable database cleanup failed: '+repr(failures))


if __name__=='__main__':main()
