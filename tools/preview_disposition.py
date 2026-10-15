"""Disposable-only disposition browser fixture with isolated UI storage and cookies.

Run with the API Python environment. Ctrl-C stops owned servers and drops the
new database. No persistent ERMS database is initialized, tested or migrated.
"""
import os
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from dotenv import dotenv_values
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]


def preview_pdf():
    """Small valid PDF fixture, independent of document-generation tooling."""
    stream=b'BT /F1 16 Tf 72 720 Td (Disposable governed evidence - Phase 11) Tj ET'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
      b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
      b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
      b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
      b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    data=bytearray(b'%PDF-1.4\n');offsets=[]
    for number,obj in enumerate(objects,1):
        offsets.append(len(data));data.extend(str(number).encode()+b' 0 obj\n'+obj+b'\nendobj\n')
    start=len(data);data.extend(b'xref\n0 6\n0000000000 65535 f \n')
    for offset in offsets:data.extend(f'{offset:010} 00000 n \n'.encode())
    data.extend(b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(start).encode()+b'\n%%EOF\n')
    return bytes(data)


def seed(environment, phase=10):
    os.environ.update(environment)
    from backend.services.api.authentication import hash_password
    from backend.services.api.main import app
    from backend.services.api.localization import synchronize_generated_arabic_drafts
    from fastapi.testclient import TestClient
    with psycopg.connect(environment['DATABASE_URL'],row_factory=dict_row) as c:
        c.execute("SELECT set_config('app.event_source','seeding',true)")
        c.execute("INSERT INTO org_units(code,name) VALUES('DISP-PREVIEW','Disposition preview')")
        c.execute("INSERT INTO org_units(code,name,parent_org_unit_id) VALUES('DISP-BRANCH','Disposition branch',1)")
        for email,profile,code in [('admin@test.invalid','ALL_PRIVS','preview-administrator'),('officer@test.invalid','INFO_GOV_OFFICER','preview-officer')]:
            user=c.execute("INSERT INTO users(name,email) VALUES(%s,%s) RETURNING id",(code,email)).fetchone()['id']
            role=c.execute("INSERT INTO roles(org_unit_id,code,name,profile_id,security_level_id,is_information_governance) SELECT 1,%s,%s,p.id,l.id,true FROM profiles p CROSS JOIN security_levels l WHERE p.code=%s AND l.level_number=(SELECT CASE WHEN p.code='INFO_GOV_OFFICER' THEN min(level_number) ELSE max(level_number) END FROM security_levels) RETURNING id",(code,code,profile)).fetchone()['id']
            c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(user,role))
            c.execute('INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES(%s,%s,false)',(user,hash_password('Temporary-Test-Password-123!')))
        c.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) SELECT id,'ar','Asia/Dubai' FROM users WHERE email='officer@test.invalid'")
        c.execute("INSERT INTO classification_schemes(code,title,date_published) VALUES('DISP','Disposition preview',CURRENT_TIMESTAMP)")
        c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'T0001','Disposition preview',true)")
        c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(1,5,0,'destruction')")
    with TestClient(app) as client:
        client.headers['X-Event-Source']='seeding'
        assert client.post('/api/v1/auth/login',json={'email':'admin@test.invalid','password':'Temporary-Test-Password-123!'}).status_code==200
        client.headers['X-CSRF-Token']=client.cookies.get('erms_csrf')
        synchronize_generated_arabic_drafts()
        preview=client.get('/api/v1/admin/i18n/translations/ar/bulk-publication-preview').json()
        # Keep flagged drafts unreviewed. Only existing publication-ready
        # entries are published to this disposable preview, never a real DB.
        invalid={item['message_key'] for item in preview['invalid']}
        preview['items']=[item for item in preview['items'] if item['message_key'] not in invalid]
        if preview['items']:
            result=client.post('/api/v1/admin/i18n/translations/ar/bulk-review-publish',json={'items':preview['items']},headers={'X-Change-Reason':'Publish eligible disposable preview translations'})
            assert result.status_code==200,result.text
    from backend.services.api.disposition.eligibility import evaluate_root,worker_actor
    from backend.services.api.tests.test_disposition_foundation import ensure_officer
    from backend.services.api.tests.test_disposition_membership import actor
    from backend.services.api.disposition.membership import create_job
    with psycopg.connect(environment['DATABASE_URL'],row_factory=dict_row) as c:
        user=c.execute("SELECT id FROM users WHERE email='admin@test.invalid'").fetchone()['id']
        role=c.execute("SELECT id FROM roles WHERE code='preview-administrator'").fetchone()['id']
        actor(c,user); c.execute("SELECT set_config('app.event_source','seeding',true)")
        ensure_officer(c,user)
        classification=c.execute("SELECT id FROM classifications WHERE code='T0001'").fetchone()['id']
        if phase<11:
            c.execute("DELETE FROM profile_privileges WHERE profile_id=(SELECT id FROM profiles WHERE code='INFO_GOV_OFFICER') AND privilege_id=(SELECT id FROM privileges WHERE code='record.view')")
        for index in range(1,132):
            root=c.execute("INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,date_opened) VALUES(%s,%s,%s,%s,'1900-01-01') RETURNING id",(f'DISP-{index:04}',f'Disposition preview {index}',classification,1 if index<=65 else 2)).fetchone()['id']
            if index==1:
                child=c.execute("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title,is_vital) VALUES(%s,'BLOCKING-CHILD','Vital blocking child',true) RETURNING id",(root,)).fetchone()['id']
                c.execute("INSERT INTO records(aggregation_id,record_number,title,is_vital) VALUES(%s,'BLOCKING-RECORD','Vital blocking record',true)",(child,))
                c.execute("INSERT INTO records(aggregation_id,record_number,title,is_vital) VALUES(%s,'BLOCKING-RECORD-2','Second vital blocking record',true)",(child,))
            c.execute("UPDATE aggregations SET date_closed='2020-01-01T00:00:00Z' WHERE id=%s",(root,))
            worker_actor(c); evaluate_root(c,root); actor(c,user)
            c.execute("SELECT set_config('app.event_source','seeding',true)")
        c.execute("INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,date_opened) VALUES('DISP-OPEN','Open acceleration preview',1,1,'1900-01-01')")
        c.execute("SELECT set_config('app.actor_name','preview-administrator',true),set_config('app.actor_email','admin@test.invalid',true)")
        for index in range(1,29):
            create_job(c,job_number=f'PREVIEW-JOB-{index:02}',job_type='destruction',owning_org_unit_id=1,assigned_user_id=user,acting_role_id=role,reason='Seed disposable job fixture',command_id=uuid4())
        if phase>=11:
            from backend.services.api.tests.test_disposition_artifacts import configure,seed_document,root
            configure(c)
            destination=root(c,opened='2026-01-01')
            job=c.execute("SELECT * FROM disposition_jobs WHERE job_number='PREVIEW-JOB-28'").fetchone()
            content=preview_pdf()
            for index in range(1,29):
                seed_document(c,job,content=content)
            seed_document(c,job,'destruction_request',content=content)
            # Different configured evidence destination exercises the warning;
            # every earlier governed record retains the first root reference.
            cl=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'EVIDENCE-NEXT','Current evidence classification',true) RETURNING id").fetchone()['id']
            root(c,cl,opened='2026-02-01');configure(c,evidence=cl)
            manager=c.execute("INSERT INTO roles(org_unit_id,code,name,profile_id,is_information_governance) SELECT 1,'preview-records-manager','Preview Records Manager',id,true FROM profiles WHERE code='INFO_GOV_MGR' RETURNING id").fetchone()['id']
            c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(user,manager))
            from backend.services.api.disposition.membership import assign_job
            assigned=c.execute("SELECT id FROM users WHERE email='officer@test.invalid'").fetchone()['id']
            assign_job(c,job_id=job['id'],expected_version=job['version'],assigned_user_id=assigned,acting_role_id=role,reason='Seed assigned Arabic Officer preview',command_id=uuid4())
            if phase>=12:
                from backend.services.api.disposition import documents,document_snapshots
                from backend.services.api.disposition.membership import add_many
                from backend.services.api.application_settings import load_snapshot
                root_row=c.execute("SELECT id,version FROM aggregations WHERE aggregation_number='DISP-0002'").fetchone()
                job=c.execute('SELECT * FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone()
                add_many(c,job_id=job['id'],expected_version=job['version'],items=[{'root_id':root_row['id'],'expected_version':root_row['version']}],
                  acting_role_id=role,reason='Seed disposable report membership',command_id=uuid4())
                for index in range(28):
                    original=documents.current(c,'destruction_request')
                    documents.revise(c,job_id=job['id'],kind='destruction_request',expected_reference=original['reference'],command_id=uuid4(),
                      acting_role_id=manager,reason='Seed retained template revision history',content=original['content'],
                      filename=f'request-revision-{index+1:02}.docx',settings=load_snapshot(c))
                snapshot=document_snapshots.request_snapshot(c,job['id'],authority_name='Disposable authority / جهة الاختبار',
                  review_summaries={'file_administrator':'Fixture summary / ملخص الاختبار','unit_manager':'Fixture summary / ملخص الاختبار','records_manager':'Fixture summary / ملخص الاختبار'},
                  review_round=1,form_version=1,generated_at='2026-10-15T10:00:00Z')
                job=c.execute('SELECT * FROM disposition_jobs WHERE id=%s',(job['id'],)).fetchone();c.commit();actor(c,user)
                c.execute("SELECT set_config('app.event_source','seeding',true)")
                documents.generate(c,job_id=job['id'],expected_version=job['version'],kind='destruction_request',snapshot=snapshot,
                  command_id=uuid4(),acting_role_id=manager,reason='Seed representative Phase 12 snapshot PDF',
                  preview=documents.artifacts.destination(c,job['id'],'destruction_request'),settings=load_snapshot(c),
                  connection_factory=lambda:psycopg.connect(environment['DATABASE_URL'],row_factory=dict_row))




def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',type=int,choices=(10,11,12),default=12)
    phase=parser.parse_args().phase
    configuration={**dotenv_values(ROOT/'.env'),**os.environ}
    admin_url=make_conninfo(configuration['DATABASE_URL'],dbname='postgres')
    name='erms_messaging_test_acl_'+uuid4().hex
    url=make_conninfo(configuration['DATABASE_URL'],dbname=name)
    created=False;processes=[];logs=[]
    with tempfile.TemporaryDirectory(prefix='erms-disposition-preview-',dir='/private/tmp') as directory:
        try:
            with psycopg.connect(admin_url,autocommit=True) as c:
                c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created=True;print('Created disposable database '+name,flush=True)
            with psycopg.connect(url) as c:
                c.execute((ROOT/'database/schema.sql').read_text(),prepare=False)
                for seed_name in ('messaging.sql','hold-notification-producers.sql','relationship-types.sql'):
                    c.execute((ROOT/'database/seeds'/seed_name).read_text(),prepare=False)
            frontend_packages=ROOT/'frontend/webui/.venv/lib/python3.11/site-packages'
            environment={k:str(v) for k,v in configuration.items() if v is not None}
            environment.update(DATABASE_URL=url,AUTH_COOKIE_SECURE='false',APPLICATION_SETTINGS_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                DATABASE_DISPLAY_NAME=f'Phase {phase} disposable preview',DATABASE_DISPLAY_NAME_AR='معاينة التصرف المؤقتة',
                WEBUI_API_URL='http://127.0.0.1:18030',WEBUI_PORT='18083',WEBUI_HOST='127.0.0.1',WEBUI_RELOAD='false',
                NICEGUI_STORAGE_PATH=directory,WEBUI_STORAGE_SECRET=uuid4().hex,NICEGUI_REDIS_URL='',
                PYTHONPATH=os.pathsep.join([str(ROOT),str(frontend_packages)]))
            subprocess.run([sys.executable,'-c',f'from tools.preview_disposition import seed; import os; seed(dict(os.environ),phase={phase})'],cwd=ROOT,env=environment,check=True)
            for label,command in [('api',[sys.executable,'-m','uvicorn','backend.services.api.main:app','--host','127.0.0.1','--port','18030']),
                ('webui',[str(ROOT/'frontend/webui/.venv/bin/python'),'-c',"import os,runpy; from nicegui import app; from starlette.middleware.sessions import SessionMiddleware; app.add_middleware(SessionMiddleware,secret_key=os.environ['WEBUI_STORAGE_SECRET'],session_cookie='erms_settings_phase{phase}_preview'); runpy.run_module('frontend.webui.app',run_name='__main__')".replace("{phase}",str(phase))])]:
                path=Path(directory)/(label+'.log');handle=path.open('w');logs.append(handle)
                processes.append(subprocess.Popen(command,cwd=ROOT,env=environment,stdout=handle,stderr=subprocess.STDOUT))
            print('Disposable Disposition preview: http://127.0.0.1:18083/',flush=True)
            print('Isolated log directory: '+directory,flush=True)
            print('Fixture identities: admin@test.invalid (English), officer@test.invalid (Arabic); standard disposable test password.',flush=True)
            try:
                while all(p.poll() is None for p in processes):time.sleep(1)
            except KeyboardInterrupt:pass
            if any(p.poll() not in (None,0) for p in processes):
                for handle in logs:
                    handle.flush();print(Path(handle.name).read_text()[-6000:],flush=True)
                return 1
        finally:
            for p in processes:p.terminate()
            for p in processes:
                try:p.wait(timeout=10)
                except subprocess.TimeoutExpired:p.kill();p.wait()
            for handle in logs:handle.close()
            if created:
                with psycopg.connect(admin_url,autocommit=True) as c:
                    c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)
    return 0


if __name__=='__main__':sys.exit(main())
