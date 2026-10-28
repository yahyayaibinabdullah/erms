"""Disposable-only Phases 3–6 browser fixture with isolated UI storage and cookies.

Run with the API Python environment. Ctrl-C stops owned servers and drops the
new database. No persistent ERMS database is initialized, tested or migrated.
"""
import os
import argparse
from pathlib import Path
import signal
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
sys.path.insert(0, str(ROOT))


from tools.initialize_database import initialize


def seed(environment):
    os.environ.update(environment)
    from backend.services.api.authentication import hash_password
    from backend.services.api.main import app
    from backend.services.api.localization import synchronize_generated_arabic_drafts
    from fastapi.testclient import TestClient
    password='Temporary-Test-Password-123!'
    with psycopg.connect(environment['DATABASE_URL'],row_factory=dict_row) as c:
        c.execute("SELECT set_config('app.event_source','seeding',true)")
        unit=c.execute("INSERT INTO org_units(code,name) VALUES('SETTINGS-PREVIEW','Settings preview') RETURNING id").fetchone()['id']
        for email,profile,code in [('admin@test.invalid','ALL_PRIVS','preview-administrator'),('officer@test.invalid','INFO_GOV_OFFICER','preview-officer')]:
            user=c.execute("INSERT INTO users(name,email) VALUES(%s,%s) RETURNING id",(code,email)).fetchone()['id']
            role=c.execute("INSERT INTO roles(org_unit_id,code,name,profile_id,security_level_id,is_information_governance) SELECT %s,%s,%s,p.id,l.id,true FROM profiles p CROSS JOIN security_levels l WHERE p.code=%s AND l.level_number=(SELECT max(level_number) FROM security_levels) RETURNING id",(unit,code,code,profile)).fetchone()['id']
            c.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)",(user,role))
            c.execute("INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES(%s,%s,false)",(user,hash_password(password)))
        viewer=c.execute("INSERT INTO users(name,email) VALUES('Preview viewer','viewer@test.invalid') RETURNING id").fetchone()['id']
        c.execute("INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES(%s,%s,false)",(viewer,hash_password(password)))
        for i in range(1,29):
            c.execute("INSERT INTO classification_schemes(code,title,translations,date_published) VALUES(%s,%s,jsonb_build_object('ar',jsonb_build_object('title',%s::text)),CURRENT_TIMESTAMP)",(f'S{i:02}',f'Scheme {i}',f'نظام التصنيف {i}'))
        scheme=c.execute("SELECT id FROM classification_schemes WHERE code='S01'").fetchone()['id']
        branch=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal,translations) VALUES(%s,'B01','Branch 1',false,'{\"ar\":{\"title\":\"الفرع الأول\"}}') RETURNING id",(scheme,)).fetchone()['id']
        c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')",(branch,))
        c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) SELECT %s,'B'||lpad(i::text,2,'0'),'Branch '||i,false FROM generate_series(2,28) i",(scheme,))
        c.execute("INSERT INTO classifications(classification_scheme_id,parent_classification_id,code,title,is_terminal,translations) SELECT %s,%s,'T'||lpad(i::text,4,'0'),'Terminal '||i,true,jsonb_build_object('ar',jsonb_build_object('title','التصنيف النهائي '||i)) FROM generate_series(1,1000) i",(scheme,branch))
        # Seven deep branches, each independently loaded; terminal inherits rule.
        parent=branch
        for depth in range(1,8):
            parent=c.execute("INSERT INTO classifications(classification_scheme_id,parent_classification_id,code,title,is_terminal) VALUES(%s,%s,%s,%s,false) RETURNING id",(scheme,parent,f'D{depth:02}',f'Deep branch {depth}')).fetchone()['id']
        c.execute("INSERT INTO classifications(classification_scheme_id,parent_classification_id,code,title,is_terminal) VALUES(%s,%s,'DEEP-TERM','Deep terminal',true)",(scheme,parent))
    with TestClient(app) as client:
        client.headers['X-Event-Source']='seeding'
        login=client.post('/api/v1/auth/login',json={'email':'admin@test.invalid','password':password})
        assert login.status_code==200
        client.headers['X-CSRF-Token']=client.cookies.get('erms_csrf')
        synchronize_generated_arabic_drafts()  # Explicitly selected disposable DB.
        preview=client.get('/api/v1/admin/i18n/translations/ar/bulk-publication-preview').json()
        assert not preview['invalid'],preview['invalid']
        published=client.post('/api/v1/admin/i18n/translations/ar/bulk-review-publish',json={'items':preview['items']},headers={'X-Change-Reason':'Publish disposable browser language fixtures'})
        assert published.status_code==200,published.text
        before=client.get('/api/v1/application-settings').json()['items']
        smtp=[{'key':i['key'],'expected_version':i['version'], **({'secret_value':'disposable-smtp-fixture-only'} if i['key']=='SMTP_PASSWORD' else {})} for i in before if i['category']=='email']
        result=client.put('/api/v1/application-settings',json={'changes':smtp},headers={'X-Change-Reason':'Prepare masked credential fixture'})
        assert result.status_code==200,result.text
        if environment.get('DATABASE_DISPLAY_NAME') in {'Phase 4 disposable preview','Phase 6 disposable preview'}:
            from datetime import datetime,timedelta,timezone
            values={'DEFAULT_WORKING_TIMEZONE':'UTC','DEFAULT_ROOT_AGGREGATION_MEDIUM':'digital',
                'REVIEW_WARNING_WINDOW_DAYS':3,'DASHBOARD_FAVOURITE_ITEM_LIMIT':2,
                'DASHBOARD_RECENT_ITEM_LIMIT':3,'DASHBOARD_RECENT_DAYS':14,
                'DASHBOARD_REVIEW_PREVIEW_LIMIT':2,'CLASSIFICATION_RECENT_SELECTION_LIMIT':6,'USER_DETAILS_SESSION_LIMIT':3}
            if environment.get('DATABASE_DISPLAY_NAME')=='Phase 6 disposable preview':values.update(FULL_TEXT_SEARCH_ENABLED=True,CONTENT_INDEXING_SCHEDULING_ENABLED=True)
            current={i['key']:i for i in client.get('/api/v1/application-settings').json()['items']}
            changed=client.put('/api/v1/application-settings',json={'changes':[{'key':k,'expected_version':current[k]['version'],'value':v} for k,v in values.items()]},headers={'X-Change-Reason':'Prepare disposable Phase 4 settings fixtures'})
            assert changed.status_code==200,changed.text
            with psycopg.connect(environment['DATABASE_URL'],row_factory=dict_row) as c:
                classification=c.execute("SELECT id FROM classifications WHERE code='T0001'").fetchone()['id']
            for i in range(1,9):
                row=client.post('/api/v1/aggregations',json={'aggregation_number':f'PH4-ROOT-{i}',
                    'title':f'Phase 4 root {i}','classification_id':classification,
                    'date_of_next_review':(datetime.now(timezone.utc)+timedelta(days=i)).isoformat()})
                assert row.status_code==201,row.text
                if i<=4:assert client.put(f"/api/v1/favourites/aggregations/{row.json()['id']}").status_code==204
            physical=client.post('/api/v1/aggregations',json={'aggregation_number':'PH4-RECORDS',
                'title':'Phase 4 physical record fixtures','medium':'physical','classification_id':classification})
            assert physical.status_code==201,physical.text
            for i in range(1,6):
                record=client.post('/api/v1/records',json={'record_number':f'PH4-RECORD-{i}',
                    'title':f'Phase 4 record {i}','aggregation_id':physical.json()['id'],'medium':'physical'})
                assert record.status_code==201,record.text
            for _ in range(6):
                assert client.post('/api/v1/auth/login',json={'email':'admin@test.invalid','password':password}).status_code==200
                client.headers['X-CSRF-Token']=client.cookies.get('erms_csrf')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase',type=int,choices=(3,4,6),default=3)
    phase=parser.parse_args().phase
    configuration={**dotenv_values(ROOT/'.env'),**os.environ}
    admin_url=make_conninfo(configuration['DATABASE_URL'],dbname='postgres')
    name='erms_messaging_test_acl_'+uuid4().hex
    url=make_conninfo(configuration['DATABASE_URL'],dbname=name)
    created=False;processes=[];logs=[]
    with tempfile.TemporaryDirectory(prefix='erms-settings-preview-',dir='/private/tmp') as directory:
        try:
            with psycopg.connect(admin_url,autocommit=True) as c:
                c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created=True;print('Created disposable database '+name,flush=True)
            with psycopg.connect(url) as c:
                initialize(c)
                for seed_name in ('messaging.sql','hold-notification-producers.sql','relationship-types.sql'):
                    c.execute((ROOT/'database/seeds'/seed_name).read_text(),prepare=False)
            frontend_packages=ROOT/'frontend/webui/.venv/lib/python3.11/site-packages'
            environment={k:str(v) for k,v in configuration.items() if v is not None}
            environment.update(DATABASE_URL=url,AUTH_COOKIE_SECURE='false',APPLICATION_SETTINGS_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                DATABASE_DISPLAY_NAME=f'Phase {phase} disposable preview',DATABASE_DISPLAY_NAME_AR={3:'معاينة المرحلة الثالثة المؤقتة',4:'معاينة المرحلة الرابعة المؤقتة',6:'معاينة المرحلة السادسة المؤقتة'}[phase],
                WEBUI_API_URL='http://127.0.0.1:18030',WEBUI_PORT='18083',WEBUI_HOST='127.0.0.1',WEBUI_RELOAD='false',
                NICEGUI_STORAGE_PATH=directory,WEBUI_STORAGE_SECRET=uuid4().hex,NICEGUI_REDIS_URL='',
                PYTHONPATH=os.pathsep.join([str(ROOT),str(frontend_packages)]))
            subprocess.run([sys.executable,'-c','from tools.preview_application_settings import seed; import os; seed(dict(os.environ))'],cwd=ROOT,env=environment,check=True)
            for label,command in [('api',[sys.executable,'-m','uvicorn','backend.services.api.main:app','--host','127.0.0.1','--port','18030']),
                ('webui',[str(ROOT/'frontend/webui/.venv/bin/python'),'-c',"import os,runpy; from nicegui import app; from starlette.middleware.sessions import SessionMiddleware; app.add_middleware(SessionMiddleware,secret_key=os.environ['WEBUI_STORAGE_SECRET'],session_cookie='erms_settings_phase{phase}_preview'); runpy.run_module('frontend.webui.app',run_name='__main__')".replace("{phase}",str(phase))])]:
                path=Path(directory)/(label+'.log');handle=path.open('w');logs.append(handle)
                processes.append(subprocess.Popen(command,cwd=ROOT,env=environment,stdout=handle,stderr=subprocess.STDOUT))
            print('Disposable Settings preview: http://127.0.0.1:18083/',flush=True)
            print('Isolated log directory: '+directory,flush=True)
            print('Fixture identities: admin@test.invalid, officer@test.invalid, viewer@test.invalid; standard disposable test password.',flush=True)
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
