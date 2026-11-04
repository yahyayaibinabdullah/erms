"""Benchmark real dashboard HTTP requests in a new disposable database.

Run with the API virtual environment. --serve keeps the isolated API/WebUI
available for browser population measurements until Ctrl-C. Every exit path
stops only owned processes and drops the uniquely named database.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo, conninfo_to_dict
from psycopg.rows import dict_row
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.initialize_database import initialize

PASSWORD = 'Temporary-Test-Password-123!'


def seed(environment, records):
    os.environ.update(environment)
    from backend.services.api.authentication import hash_password
    assert conninfo_to_dict(environment['DATABASE_URL'])['dbname'].startswith('erms_messaging_test_acl_')
    aggregations = records * 840 // 1840
    with psycopg.connect(environment['DATABASE_URL']) as c:
        c.execute("SELECT set_config('app.event_source','seeding',true)")
        unit = c.execute("INSERT INTO org_units(code,name) VALUES('DASHBOARD-BENCH','Dashboard benchmark') RETURNING id").fetchone()[0]
        for name,governance in (('admin',True),('reader',False),('denied',False)):
            user = c.execute('INSERT INTO users(name,email) VALUES(%s,%s) RETURNING id',
                             (name,name+'@test.invalid')).fetchone()[0]
            if name != 'denied':
                role = c.execute("""INSERT INTO roles(org_unit_id,code,name,profile_id,security_level_id,is_information_governance)
                    SELECT %s,%s,%s,profile.id,level.id,%s FROM profiles profile CROSS JOIN security_levels level
                     WHERE profile.code='ALL_PRIVS' AND level.level_number=(SELECT max(level_number) FROM security_levels)
                     RETURNING id""",(unit,name,name,governance)).fetchone()[0]
                c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(user,role))
            c.execute('INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES(%s,%s,false)',
                      (user,hash_password(PASSWORD)))
        scheme = c.execute("INSERT INTO classification_schemes(code,title,date_published) VALUES('BENCH','Benchmark',CURRENT_TIMESTAMP) RETURNING id").fetchone()[0]
        branch = c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(%s,'BRANCH','Branch',false) RETURNING id",(scheme,)).fetchone()[0]
        c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')",(branch,))
        c.execute("INSERT INTO classifications(classification_scheme_id,parent_classification_id,code,title,is_terminal) SELECT %s,%s,'T'||i,'Terminal '||i,true FROM generate_series(1,1000) i",(scheme,branch))
        terminal=c.execute("SELECT id FROM classifications WHERE code='T1'").fetchone()[0]
        c.commit()
        # All synthetic resources start at status 1, with no disposition jobs.
        # Avoid revalidating that same complete unit once per inserted member
        # at commit. Restore these two triggers before any measured request.
        # Other hierarchy, ACL, FK and security constraints stay enabled.
        bulk_triggers=(('aggregations','aggregations_disposition_insert_consistency'),
                       ('records','records_disposition_insert_consistency'))
        for table,trigger in bulk_triggers:
            c.execute(sql.SQL('ALTER TABLE {} DISABLE TRIGGER {}').format(sql.Identifier(table),sql.Identifier(trigger)))
        c.execute("SELECT set_config('app.event_source','seeding',true)")
        # A balanced four-level hierarchy; parents always precede children.
        c.execute("INSERT INTO aggregations(aggregation_number,title,owning_org_unit_id,medium,classification_id) VALUES('BENCH-1','Benchmark root',%s,'digital',%s)",(unit,terminal))
        c.execute("""INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title,owning_org_unit_id,medium,date_of_next_review)
            SELECT parent.id,'BENCH-'||i,'Benchmark aggregation '||i,%s,'digital',CURRENT_TIMESTAMP+(i%%8+1)*INTERVAL '1 day'
              FROM generate_series(2,21) i CROSS JOIN aggregations parent WHERE parent.aggregation_number='BENCH-1'""",(unit,))
        c.execute("""INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title,owning_org_unit_id,medium,date_of_next_review)
            SELECT parent.id,'BENCH-'||i,'Benchmark aggregation '||i,%s,'digital',CURRENT_TIMESTAMP+(i%%8+1)*INTERVAL '1 day'
              FROM generate_series(22,421) i JOIN aggregations parent ON parent.aggregation_number='BENCH-'||((i-22)%%20+2)""",(unit,))
        c.execute("""INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title,owning_org_unit_id,medium,date_of_next_review)
            SELECT parent.id,'BENCH-'||i,'Benchmark aggregation '||i,%s,'digital',CURRENT_TIMESTAMP+(i%%8+1)*INTERVAL '1 day'
              FROM generate_series(422,%s) i JOIN aggregations parent ON parent.aggregation_number='BENCH-'||((i-422)%%400+22)""",(unit,aggregations))
        c.execute("""INSERT INTO records(aggregation_id,record_number,title,owning_org_unit_id,medium,date_of_next_review)
            SELECT aggregation.id,'BENCH-REC-'||i,'Benchmark record '||i,%s,'digital',CURRENT_TIMESTAMP+(i%%8+1)*INTERVAL '1 day'
              FROM generate_series(1,%s) i JOIN aggregations aggregation ON aggregation.aggregation_number='BENCH-'||((i-1)%% %s+1)""",(unit,records,aggregations))
        c.execute("""INSERT INTO digital_components(record_id,component_order,file_name,mime_type,size_in_bytes,checksum_algo,checksum_value)
            SELECT record.id,number,'synthetic.txt','text/plain',1024,'sha256','synthetic-fixture-only'
              FROM records record CROSS JOIN generate_series(1,2) number""")
        # Explicitly grant the same-unit reader visibility; direct SQL fixture
        # insertion does not apply the API's create-time ACL assignment.
        c.execute("""INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,permission_id)
            SELECT resource.id,'org_unit_members',permission.id FROM aggregations resource CROSS JOIN permissions permission
             WHERE permission.code='aggregation.view' ON CONFLICT DO NOTHING""")
        c.execute("""INSERT INTO aggregation_child_record_acl_defaults(aggregation_id,principal_type,permission_id)
            SELECT resource.id,'org_unit_members',permission.id FROM aggregations resource CROSS JOIN permissions permission
             WHERE permission.code='record.view' ON CONFLICT DO NOTHING""")
        c.execute("UPDATE records SET inherit_acl_from_parent=true")
        c.commit()
        for table,trigger in bulk_triggers:
            c.execute(sql.SQL('ALTER TABLE {} ENABLE TRIGGER {}').format(sql.Identifier(table),sql.Identifier(trigger)))
        assert c.execute('SELECT count(*) FROM disposition_jobs').fetchone()[0]==0
        for table in ('records','aggregations'):
            assert c.execute(sql.SQL('SELECT count(*) FROM {} WHERE disposition_status<>1').format(sql.Identifier(table))).fetchone()[0]==0
        # The history volume is synthetic; avoid running reference-snapshot
        # construction hundreds of thousands of times during fixture setup.
        # Immutable-history guards, constraints and every query remain enabled.
        snapshot_triggers=('event_history_populate_actor_snapshot','event_history_populate_reference_snapshots',
                           'event_history_populate_relationship_snapshot','event_history_z_hold_reference_snapshots')
        for trigger in snapshot_triggers:
            c.execute(sql.SQL('ALTER TABLE event_history DISABLE TRIGGER {}').format(sql.Identifier(trigger)))
        # 60 immutable events per record, including audited component views.
        for actor in ('admin','reader'):
            c.execute("""INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_type,source,before_state,after_state,occurred_at)
                SELECT CASE WHEN i%%3=0 THEN 'digital_component' ELSE 'record' END,
                       CASE WHEN i%%3=0 THEN component.id ELSE record.id END,
                       CASE WHEN i%%3=0 THEN 'CONTENT_VIEWED' WHEN i%%3=1 THEN 'CREATE' ELSE 'UPDATE' END,
                       actor.id,'user','seeding',CASE WHEN i%%3=1 THEN NULL ELSE '{}'::jsonb END,'{}'::jsonb,CURRENT_TIMESTAMP-(i%%14)*INTERVAL '1 day'-(i/14)*INTERVAL '1 millisecond'
                  FROM generate_series(1,%s) i
                  JOIN records record ON record.record_number='BENCH-REC-'||((i-1)%% %s+1)
                  JOIN digital_components component ON component.record_id=record.id AND component.component_order=1
                  CROSS JOIN users actor WHERE actor.email=%s""",(records*30,records,actor+'@test.invalid'))
        for trigger in snapshot_triggers:
            c.execute(sql.SQL('ALTER TABLE event_history ENABLE TRIGGER {}').format(sql.Identifier(trigger)))
        c.execute("INSERT INTO user_favourite_aggregations(user_id,aggregation_id) SELECT actor.id,aggregation.id FROM users actor CROSS JOIN aggregations aggregation WHERE actor.email='admin@test.invalid' AND aggregation.id<=4")
        c.execute("INSERT INTO user_favourite_records(user_id,record_id) SELECT actor.id,record.id FROM users actor CROSS JOIN records record WHERE actor.email='admin@test.invalid' AND record.id<=4")
        c.execute('ANALYZE')
        assert c.execute('SELECT count(*) FROM records').fetchone()[0] == records
        assert c.execute('SELECT count(*) FROM aggregations').fetchone()[0] == aggregations
        c.commit()
        c.autocommit=True
        c.execute('VACUUM ANALYZE')


def capture_plans(environment, output, label):
    """Inspect all dashboard SQL independently of the timed HTTP samples."""
    os.environ.update(environment)
    from datetime import datetime,timedelta,timezone
    from types import SimpleNamespace
    from starlette.requests import Request
    from backend.services.api.dashboard import dashboard_summary
    destination=Path(output)
    class PlannedConnection:
        def __init__(self,connection):self.connection=connection;self.plans=[]
        def __getattr__(self,name):return getattr(self.connection,name)
        def execute(self,query,params=None,**kwargs):
            self.plans.append({'sql':str(query),'plan':self.connection.execute(
                'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+query,params).fetchone()['QUERY PLAN']})
            return self.connection.execute(query,params,**kwargs)
    for actor in ('admin','reader','denied'):
        with psycopg.connect(environment['DATABASE_URL'],row_factory=dict_row) as c:
            identity=c.execute('SELECT id FROM users WHERE email=%s',(actor+'@test.invalid',)).fetchone()['id']
            c.execute("SELECT set_config('app.user_id',%s,true)",(str(identity),))
            planned=PlannedConnection(c)
            body=dashboard_summary(Request({'type':'http','headers':[]}),recent_limit=4,
                recent_since=datetime.now(timezone.utc)-timedelta(days=30),
                principal=SimpleNamespace(user_id=identity),connection=planned)
            (destination/f'{label}-{actor}-plans.json').write_text(json.dumps(planned.plans,indent=2)+'\n')
            (destination/f'{label}-{actor}-summary.json').write_text(json.dumps(body,default=str,indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records',type=int,choices=(1840,18400),required=True)
    parser.add_argument('--serve',action='store_true')
    parser.add_argument('--samples',type=int,default=7)
    args = parser.parse_args()
    if args.samples<1:parser.error('--samples must be positive')
    # Refuse to reuse an unrelated service at either benchmark endpoint.
    for port in ((18030,18083) if args.serve else (18030,)):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            probe.bind(('127.0.0.1',port))
    configuration = {**dotenv_values(ROOT/'.env'),**os.environ}
    name = 'erms_messaging_test_acl_'+uuid4().hex
    admin_url = make_conninfo(configuration['DATABASE_URL'],dbname='postgres')
    environment = {k:str(v) for k,v in configuration.items() if v is not None}
    processes=[];created=False;handles=[]
    output=ROOT/'.runtime/dashboard-verification'/str(args.records)
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='erms-dashboard-bench-',dir='/private/tmp') as directory:
        try:
            with psycopg.connect(admin_url,autocommit=True) as c:
                c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created=True
            print('Created disposable database '+name,flush=True)
            environment.update(DATABASE_URL=make_conninfo(configuration['DATABASE_URL'],dbname=name),
                AUTH_COOKIE_SECURE='false',DATABASE_DISPLAY_NAME=f'Disposable dashboard benchmark ({args.records:,} records)',
                DATABASE_DISPLAY_NAME_AR=f'اختبار مؤقت للوحة المعلومات ({args.records:,} وثيقة)',
                WEBUI_API_URL='http://127.0.0.1:18030',WEBUI_PORT='18083',WEBUI_HOST='127.0.0.1',WEBUI_RELOAD='false',
                NICEGUI_STORAGE_PATH=directory,WEBUI_STORAGE_SECRET=uuid4().hex,NICEGUI_REDIS_URL='',
                PYTHONPATH=os.pathsep.join([str(ROOT),str(ROOT/'frontend/webui/.venv/lib/python3.11/site-packages')]))
            with psycopg.connect(environment['DATABASE_URL']) as c:
                initialize(c)
                for filename in ('messaging.sql','hold-notification-producers.sql','relationship-types.sql'):
                    c.execute((ROOT/'database/seeds'/filename).read_text(),prepare=False)
            subprocess.run([sys.executable,'-c',
                f'from tools.benchmark_dashboard import seed; import os; seed(dict(os.environ),{args.records})'],
                cwd=ROOT,env=environment,check=True)
            for label,command in [('api',[sys.executable,'-m','uvicorn','backend.services.api.main:app','--host','127.0.0.1','--port','18030']),
                ('webui',[str(ROOT/'frontend/webui/.venv/bin/python'),'-c',
                    "import os,runpy; from nicegui import app; from starlette.middleware.sessions import SessionMiddleware; app.add_middleware(SessionMiddleware,secret_key=os.environ['WEBUI_STORAGE_SECRET'],session_cookie='erms_dashboard_benchmark'); runpy.run_module('frontend.webui.app',run_name='__main__')"])]:
                if label=='webui' and not args.serve:continue
                handle=(output/(label+'.log')).open('w');handles.append(handle)
                processes.append(subprocess.Popen(command,cwd=ROOT,env=environment,stdout=handle,stderr=subprocess.STDOUT))
            with httpx.Client(base_url='http://127.0.0.1:18030',timeout=60) as client:
                for attempt in range(120):
                    if processes[0].poll() is not None:raise RuntimeError('API exited; inspect '+str(output/'api.log'))
                    try:
                        response=client.get('/health')
                        if response.status_code==200:break
                    except httpx.TransportError:pass
                    time.sleep(.5)
                else:raise RuntimeError('Isolated API did not become ready')
                report={'records':args.records,'aggregations':args.records*840//1840,'components':args.records*2,
                        'synthetic_activity_events':args.records*60,'database':name,'api':{}}
                for actor in ('admin','reader','denied'):
                    client.cookies.clear()
                    login=client.post('/api/v1/auth/login',json={'email':actor+'@test.invalid','password':PASSWORD})
                    login.raise_for_status()
                    samples=[]
                    for sample in range(args.samples+1):
                        started=time.perf_counter();response=client.get('/api/v1/dashboard/summary')
                        elapsed=(time.perf_counter()-started)*1000
                        response.raise_for_status();body=response.json()
                        assert body['overview_counts']['records']==(0 if actor=='denied' else args.records),(actor,body['overview_counts'])
                        if actor=='denied':
                            assert body['favourites']=={'aggregations':[],'records':[]}
                            assert body['recent_activity']==body['ownership_counts']==[]
                        if sample==0:first=elapsed
                        else:samples.append(elapsed)
                    report['api'][actor]={'first_ms':first,'warm_ms':samples,'median_ms':statistics.median(samples),'min_ms':min(samples),'max_ms':max(samples)}
                (output/'timings.json').write_text(json.dumps(report,indent=2)+'\n')
                print(json.dumps(report),flush=True)
            if args.serve:
                # Keep connection details private and ephemeral for plan inspection.
                Path(directory,'database-url').write_text(environment['DATABASE_URL'])
                print('Browser: http://127.0.0.1:18083/; fixture directory: '+directory,flush=True)
                while all(process.poll() is None for process in processes):time.sleep(1)
        except KeyboardInterrupt:pass
        finally:
            for process in processes:process.terminate()
            for process in processes:
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
            for handle in handles:handle.close()
            if created:
                with psycopg.connect(admin_url,autocommit=True) as c:
                    c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)


if __name__=='__main__':main()
