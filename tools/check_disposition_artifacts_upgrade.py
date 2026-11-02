"""Phase 11 canonical/056 parity and preservation of existing governed evidence."""
import hashlib
import os
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values
from tools.check_disposition_foundation_upgrade import baseline_data,catalogue
from tools.check_disposition_eligibility_upgrade import existing_command

ROOT=Path(__file__).resolve().parents[1]
MARKER='-- Disposition governed artifacts (056).\n'
ADDED=['origin','supersedes_document_id','evidence_version','classification_scheme_id','classification_id','aggregation_id','acting_role_id','provenance']


from tools.historical_schema import historical_schema


def snapshot(c):
    tables=['aggregations','records','digital_components','digital_component_content_sets','digital_component_blobs',
      'event_history','application_settings','disposition_jobs','disposition_job_documents','disposition_private.command_receipts']
    return {table:c.execute(sql.SQL('SELECT to_jsonb(t)-%s::text[] FROM {} t ORDER BY {}').format(sql.Identifier(*table.split('.')),sql.Identifier('command_id' if table.endswith('receipts') else 'id')),(ADDED if table=='disposition_job_documents' else [],)).fetchall() for table in tables}


def full_catalogue(c):
    result=catalogue(c)
    result['content_triggers']=c.execute("SELECT cl.relname,t.tgname,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class cl ON cl.oid=t.tgrelid WHERE NOT t.tgisinternal AND cl.relname IN ('digital_components','digital_component_content_sets','digital_component_blobs') ORDER BY 1,2").fetchall()
    return result


def legacy_evidence(c):
    baseline_data(c)
    officer=c.execute("INSERT INTO roles(org_unit_id,code,name,profile_id,is_information_governance) SELECT 1,'legacy-officer','Legacy Officer',id,true FROM profiles WHERE code='INFO_GOV_OFFICER' RETURNING id").fetchone()[0]
    c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(1,%s)',(officer,))
    existing_command(c)
    c.execute("INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id) VALUES('legacy-evidence','Legacy evidence root',1,1)")
    c.execute("INSERT INTO records(aggregation_id,record_number,title,medium) VALUES(3,'legacy-evidence','Legacy evidence','digital')")
    checksum=hashlib.sha256(b'original').hexdigest()
    component=c.execute("INSERT INTO digital_components(record_id,component_order,file_name,mime_type,size_in_bytes,checksum_algo,checksum_value,content_status) VALUES(2,1,'legacy.pdf','application/pdf',8,'sha256',%s,'available') RETURNING id",(checksum,)).fetchone()[0]
    content=c.execute("INSERT INTO digital_component_content_sets(digital_component_id,status,size_in_bytes,segment_count,checksum_algo,checksum_value,date_completed) VALUES(%s,'active',8,1,'sha256',%s,CURRENT_TIMESTAMP) RETURNING id",(component,checksum)).fetchone()[0]
    c.execute('INSERT INTO digital_component_blobs(content_set_id,segment_no,segment_size,content) VALUES(%s,0,8,%s)',(content,b'original'))
    c.execute('UPDATE digital_components SET active_content_set_id=%s,upload_completed_at=CURRENT_TIMESTAMP WHERE id=%s',(content,component))
    role=c.execute("SELECT id FROM roles WHERE code='existing'").fetchone()[0]
    c.execute("SELECT disposition_private.begin_command(%s,'document_save','{}',%s,'Store existing evidence before upgrade')",(uuid4(),role))
    c.execute("INSERT INTO disposition_job_documents(job_id,document_type,document_state,record_id,digital_component_id,created_by_user_id,checksum_algo,checksum) VALUES(1,'external_approval_letter','available',2,%s,1,'sha256',%s)",(component,checksum))
    c.execute("SELECT disposition_private.finish_command('{}')")


def main():
    config={**dotenv_values(ROOT/'.env'),**os.environ};base=config['DATABASE_URL'];admin_url=make_conninfo(base,dbname='postgres')
    schema=historical_schema().split('-- Disposition controlled templates (057).',1)[0].rstrip()+'\n';old=schema.split(MARKER)[0];migration=(ROOT/'database/migrations/056_disposition_artifacts.sql').read_text();names=[]
    try:
        for kind in ('fresh','upgrade'):
            name='erms_disposition11_test_'+kind+'_'+uuid4().hex
            with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            names.append(name);print('Created disposable database '+name,flush=True)
            with psycopg.connect(make_conninfo(base,dbname=name)) as c:
                c.execute(schema if kind=='fresh' else old,prepare=False);c.commit()
                if kind=='fresh':fresh=full_catalogue(c)
                else:
                    legacy_evidence(c);c.commit();before=snapshot(c)
                    c.execute(migration,prepare=False);c.commit()
                    assert snapshot(c)==before,'Existing governed records/content/jobs/history changed'
                    assert c.execute('SELECT origin,evidence_version,classification_scheme_id,classification_id,aggregation_id,acting_role_id,provenance FROM disposition_job_documents').fetchone()==('uploaded',1,1,1,3,None,{'legacy_destination_reconstructed':True})
                    assert full_catalogue(c)==fresh,'Canonical/056 catalogue mismatch'
                    print('Passed: exact canonical/056 catalogue parity; existing evidence bytes, links, receipts, resources, jobs, settings and immutable events preserved; no uploader role invented.',flush=True)
    finally:
        failures=[]
        for name in reversed(names):
            try:
                with psycopg.connect(admin_url,autocommit=True) as admin:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)
            except Exception as error:failures.append((name,type(error).__name__))
        if failures:raise RuntimeError('Disposable database cleanup failed: '+repr(failures))


if __name__=='__main__':main()
