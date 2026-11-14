"""Deterministic full-text correctness and latency gate; owns and drops its database."""
from pathlib import Path
import argparse
import functools
import hashlib
import json
import os
import platform
import signal
import sys
import time
import traceback
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.initialize_database import initialize

PASSWORD = "Disposable-Search-Performance-123!"
AGGREGATIONS = 51003
RECORDS = 153009
CASES = [
    # Time the broadest first request before any search/oracle warms this corpus.
    ("broad_combined", "common OR universal", 204012, None),
    ("empty", "zzabsent", 0, None),
    ("rare", "needle", 50, None),
    ("phrase", '"gold archive"', 160, None),
    ("and", "gold archive", 160, None),
    ("or", "needle OR copper", 450, None),
    ("exclude", "gold -draft", 80, None),
    ("arabic", "وثيقة", 200, None),
    ("filename", "filenameprobe", 23, None),
    ("content", "contentprobe", 73, None),
    ("structured", "common", 474, "metadata"),
    ("broad_metadata", "common", 204012, "metadata"),
    ("broad_content", "universal", 153009, "components"),
]


def seed(c, *, include_chunks=True):
    from backend.services.api.authentication import hash_password
    c.execute("SELECT set_config('app.event_source','seeding',true)")
    unit = c.execute("INSERT INTO org_units(code,name) VALUES('PERF','Performance') RETURNING id").fetchone()['id']
    profile = c.execute("SELECT id FROM profiles WHERE code='ALL_PRIVS'").fetchone()['id']
    level = c.execute("SELECT id FROM security_levels ORDER BY level_number LIMIT 1").fetchone()['id']
    role = c.execute("""INSERT INTO roles(code,name,org_unit_id,profile_id,security_level_id)
        VALUES('PERF','Performance reader',%s,%s,%s) RETURNING id""", (unit, profile, level)).fetchone()['id']
    denied_role = c.execute("""INSERT INTO roles(code,name,org_unit_id,profile_id,security_level_id)
        VALUES('DENIED','No resource grants',%s,%s,%s) RETURNING id""", (unit, profile, level)).fetchone()['id']
    for name in ('reader', 'denied'):
        user = c.execute("INSERT INTO users(name,email) VALUES(%s,%s) RETURNING id",
                         (name, name+'@performance.invalid')).fetchone()['id']
        c.execute("INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES(%s,%s,false)",
                  (user, hash_password(PASSWORD)))
        c.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)",
                  (user, role if name == 'reader' else denied_role))
    scheme=c.execute("INSERT INTO classification_schemes(code,title,date_published) VALUES('PERF','Performance',CURRENT_TIMESTAMP) RETURNING id").fetchone()['id']
    classification=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(%s,'PERF','Performance',true) RETURNING id",(scheme,)).fetchone()['id']
    c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')",(classification,))
    c.commit()
    # Bulk synthetic fixture only. Explicitly supply derived vectors, ACLs, and
    # active content identities. Normal triggers are restored before all requests.
    c.execute("SET LOCAL session_replication_role='replica'")
    c.execute("""UPDATE application_settings SET value=CASE key
        WHEN 'FULL_TEXT_SEARCH_ENABLED' THEN 'true'::jsonb
        WHEN 'SEARCH_RESULT_LIMIT' THEN '1000'::jsonb
        WHEN 'SEARCH_RATE_LIMIT_PER_MINUTE' THEN '100000'::jsonb END
        WHERE key IN ('FULL_TEXT_SEARCH_ENABLED','SEARCH_RESULT_LIMIT','SEARCH_RATE_LIMIT_PER_MINUTE')""")
    for table, number, count, divisor in [('aggregations','aggregation_number',AGGREGATIONS,3),('records','record_number',RECORDS,1)]:
        parent = ",aggregation_id" if table == 'records' else ',inherit_acl_from_parent,classification_id'
        values = ",(n-1)/3+1" if table == 'records' else f',false,{classification}'
        c.execute(sql.SQL("""INSERT INTO {} (id,{},title,description,owning_org_unit_id,security_level_id,medium{})
            SELECT n, 'PERF-' || n, repeat('common ',1+n%%3) ||
                CASE WHEN n<=%s THEN 'needle ' ELSE '' END ||
                CASE WHEN n>%s AND n<=%s THEN 'copper ' ELSE '' END ||
                CASE WHEN n<=%s THEN 'gold archive ' ELSE '' END ||
                CASE WHEN n<=%s THEN 'draft ' ELSE '' END ||
                CASE WHEN n<=%s THEN 'وثيقة ' ELSE '' END,
                repeat('ordinary description evidence ', 12), %s,%s,'digital' {}
            FROM generate_series(1,%s) n""").format(sql.Identifier(table),sql.Identifier(number),sql.SQL(parent),sql.SQL(values)),
            (37 if divisor==1 else 13, 120//divisor, 420//divisor,120//divisor,60//divisor,150//divisor,unit,level,count))
        kind = 'record' if table=='records' else 'aggregation'
        c.execute(sql.SQL("""INSERT INTO {} ({},search_vector,text_search_config,index_config_version)
            SELECT id,setweight(to_tsvector('simple',{}),'A') || setweight(to_tsvector('simple',title),'A')
                || setweight(to_tsvector('simple',description),'B'), 'simple','perf-v1' FROM {}""").format(
                sql.Identifier(kind+'_search_documents'),sql.Identifier(kind+'_id'),sql.Identifier(number),sql.Identifier(table)))
    for table in ('aggregation_acl_grants','aggregation_child_record_acl_defaults'):
        codes = ['aggregation.view'] if table=='aggregation_acl_grants' else ['record.view','record.component.list','record.component.view']
        c.execute(sql.SQL("""INSERT INTO {}(aggregation_id,principal_type,role_id,permission_id)
            SELECT a.id,'role',%s,p.id FROM aggregations a CROSS JOIN permissions p WHERE p.code=ANY(%s)""").format(sql.Identifier(table)),(role,codes))
    c.execute("""INSERT INTO digital_components
        (id,record_id,component_order,file_name,mime_type,size_in_bytes,checksum_algo,checksum_value,active_content_set_id,content_status)
        SELECT id,id,1,CASE WHEN id<=23 THEN 'filenameprobe evidence.txt' ELSE 'evidence.txt' END,
        'text/plain',4096,'sha256',repeat('a',64),id,'available' FROM records""")
    c.execute("""INSERT INTO digital_component_content_sets(id,digital_component_id,status,size_in_bytes,segment_count,checksum_algo,checksum_value)
        SELECT id,id,'active',4096,1,'sha256',repeat('a',64) FROM records""")
    c.execute("""INSERT INTO digital_component_search_documents(digital_component_id,record_id,content_set_id,
        content_checksum_algo,content_checksum_value,status,extraction_config_version,index_config_version,indexed_at)
        SELECT id,id,id,'sha256',repeat('a',64),'indexed','perf-v1','perf-v1',CURRENT_TIMESTAMP FROM records""")
    # The richer-text fixture supplies its own chunks. Avoid first writing
    # and then discarding this corpus (and its WAL) during that fixture's setup.
    if include_chunks:
        c.execute("""WITH templates AS MATERIALIZED (
        SELECT language,probe,text,config,to_tsvector(config,text) AS vector
        FROM generate_series(0,2) language CROSS JOIN (VALUES (true),(false)) p(probe)
        CROSS JOIN LATERAL (SELECT
          (repeat('universal ',1+language) || CASE WHEN probe THEN 'contentprobe ' ELSE '' END ||
           repeat('document evidence review archive retention department information ',20)) AS text,
          CASE language WHEN 0 THEN 'simple'::regconfig WHEN 1 THEN 'english'::regconfig ELSE 'arabic'::regconfig END AS config) t
    ) INSERT INTO digital_component_search_chunks(digital_component_id,chunk_no,extracted_text,search_vector,text_search_config)
        SELECT id,n,text || ' bucket' || id%1000,vector || to_tsvector('simple','bucket' || id%1000),config
        FROM records CROSS JOIN generate_series(0,1) n CROSS JOIN templates
        WHERE language=id%3 AND probe=(id<=73 AND n=0)""")
    c.commit()
    # Finish the bulk-load maintenance, as the dashboard benchmark does. With
    # checksums enabled, leaving fresh rows unvacuumed made the first SELECT
    # generate hundreds of MB of hint-bit full-page WAL images. No search or
    # oracle is run here, and safety settings remain unchanged.
    c.autocommit = True
    try:
        c.execute('VACUUM ANALYZE')
    finally:
        c.autocommit = False


def oracle(c, query, sources, maximum_id=None, kind=None, order_by_id=False):
    # Independent flat SQL over the seeded evidence, no production search helpers
    # or ACL shortcuts. The reader has explicit grants on every fixture container.
    rows = c.execute("""WITH q AS MATERIALIZED (
        SELECT websearch_to_tsquery('simple',%s) s,websearch_to_tsquery('english',%s) e,
               websearch_to_tsquery('arabic',%s) a
    ), file_scores AS (
        SELECT record_id AS id,
            bool_or(k.search_vector @@ CASE k.text_search_config WHEN 'simple'::regconfig THEN q.s
                WHEN 'english'::regconfig THEN q.e ELSE q.a END) AS matched,
            max(ts_rank_cd(k.search_vector,CASE k.text_search_config WHEN 'simple'::regconfig THEN q.s
                WHEN 'english'::regconfig THEN q.e ELSE q.a END)) AS score
        FROM digital_components dc JOIN digital_component_search_chunks k ON k.digital_component_id=dc.id CROSS JOIN q
        GROUP BY record_id
    ), hits AS (
        SELECT 'aggregation' AS type,d.aggregation_id AS id,ts_rank_cd(d.search_vector,q.s)::float8 AS score
        FROM aggregation_search_documents d CROSS JOIN q WHERE %s AND d.search_vector@@q.s
        UNION ALL
        SELECT 'record',d.record_id,
            ((CASE WHEN %s THEN ts_rank_cd(d.search_vector,q.s) ELSE 0 END)::real +
             (CASE WHEN %s THEN f.score ELSE 0 END)::real)::float8
        FROM record_search_documents d JOIN file_scores f ON f.id=d.record_id
        JOIN digital_components dc ON dc.record_id=d.record_id CROSS JOIN q
        WHERE (%s AND d.search_vector@@q.s)
           OR (%s AND (f.matched OR to_tsvector('simple',dc.file_name)@@q.s))
    ) SELECT *,count(*) OVER() AS total FROM hits WHERE (%s::bigint IS NULL OR id<=%s)
        AND (%s::text IS NULL OR type=%s)
      ORDER BY CASE WHEN %s THEN id END,score DESC,type,id LIMIT 1001""",
        (query,query,query,sources!='components',sources!='components',sources!='metadata',sources!='components',sources!='metadata',maximum_id,maximum_id,kind,kind,order_by_id)).fetchall()
    return rows


def exercise(output, repeats):
    from fastapi.testclient import TestClient
    from backend.services.api.main import app
    from backend.services.api import search
    from backend.services.api.schemas import GlobalSearchRequest
    results = []
    failures = []
    # Content-free timings only: no disk I/O inside a request and no extra SQL.
    # Keep initial ranking separate from cached-page checks/enrichment so a
    # threshold failure identifies which part needs an execution-plan review.
    stages = {}
    def timed(name):
        original = getattr(search, name)
        @functools.wraps(original)
        def measured(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                stages[name] = stages.get(name, 0) + time.perf_counter() - started
        return measured
    for name in ('_rank_global_search', '_save_global_search', '_read_global_search',
                 '_global_search_page', 'page_details'):
        setattr(search, name, timed(name))
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c, TestClient(app) as client:
        for identity in ('reader','denied'):
            client.cookies.clear()
            login=client.post('/api/v1/auth/login',json={'email':identity+'@performance.invalid','password':PASSWORD})
            assert login.status_code==200,login.text
            client.headers['X-CSRF-Token']=client.cookies['erms_csrf']
            for label,query,count,sources in CASES:
                expected=None
                leaf={'full_text':{'query':query}}
                if sources:leaf['full_text']['sources']=[sources]
                payload={'record_where':leaf,'result_types':['records'],'limit':100,'include_totals':True}
                if sources!='components':
                    payload.update(aggregation_where={'full_text':{'query':query,'sources':['metadata']}},result_types=['records','aggregations'])
                maximum_id = 237 if label == 'structured' else None
                if maximum_id is not None:
                    for branch in ('record_where','aggregation_where'):
                        payload[branch]={'and':[payload[branch], {'field':'id','operator':'lte','value':maximum_id}]}
                samples=[]
                for repeat in range(repeats):
                    request={**payload,'tab_id':str(uuid4())}
                    received=[]
                    while True:
                        stages.clear()
                        start=time.perf_counter()
                        response=client.post('/api/v1/full-text-search',json=request)
                        elapsed=time.perf_counter()-start
                        assert response.status_code==200,(label,response.status_code,response.text)
                        body=response.json()
                        if expected is None:
                            expected=oracle(c,query,sources,maximum_id) if identity=='reader' else []
                            assert (expected[0]['total'] if expected else 0)==(count if identity=='reader' else 0),(label,'fixture count')
                            expected=expected[:1000]
                            (output/f'{identity}-{label}-expected.json').write_text(json.dumps({
                                'request': payload, 'matching_count': count if identity=='reader' else 0,
                                'ranked_hits': expected}, indent=2))
                        sample={'repeat':repeat,'page':len(received)//100+1,'seconds':round(elapsed,4),
                                'stages_seconds': {key:round(value,4) for key,value in stages.items()}}
                        samples.append(sample)
                        if elapsed>3:failures.append({'identity':identity,'case':label,**sample})
                        received.extend({'type':i['type'],'id':i[i['type']]['id'],'score':i['score']} for i in body['items'])
                        if sample['page']==1:
                            assert sum(body['totals'].values())==len(expected)
                            assert body['truncated']==(count>1000 and identity=='reader')
                            cached=c.execute("SELECT hits FROM search_results_cache WHERE search_id=%s",(body['search_id'],)).fetchone()['hits']
                            assert cached==[{k:e[k] for k in ('type','id','score')} for e in expected],(identity,label,'ranked cache')
                        if not body['next_cursor']:break
                        request={**request,'cursor':body['next_cursor'],'include_totals':False}
                    assert received==[{k:e[k] for k in ('type','id','score')} for e in expected],(identity,label,'page sequence')
                    (output/f'{identity}-{label}-{repeat}-received.json').write_text(json.dumps(received,indent=2))
                result={'identity':identity,'case':label,'matches':count if identity=='reader' else 0,
                        'returned':len(expected),'samples':samples,'maximum_seconds':max(s['seconds'] for s in samples)}
                results.append(result);print(json.dumps({k:v for k,v in result.items() if k!='samples'}),flush=True)
                (output/'results.json').write_text(json.dumps({'results':results,'failures':failures},indent=2))
                # Plans are outside timing, captured for the same production SQL.
                if identity=='reader':
                    uid=c.execute("SELECT id FROM users WHERE email='reader@performance.invalid'").fetchone()['id']
                    c.execute("SELECT set_config('app.user_id',%s,true)",(str(uid),))
                    parsed=GlobalSearchRequest(**payload)
                    for resource,expression in [('records',parsed.record_where),('aggregations',parsed.aggregation_where)]:
                        if expression is None:continue
                        stmt,args=search._global_ranking_statement(c,resource,expression,1001)
                        from backend.services.api.search_execution import search_sql_execution
                        with search_sql_execution(c):
                            plan=c.execute(sql.SQL('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) ')+stmt,args).fetchone()['QUERY PLAN']
                        (output/f'{label}-{resource}-plan.json').write_text(json.dumps(plan,indent=2))
                        def indexes(node):
                            return {node.get('Index Name')} | set().union(*(indexes(p) for p in node.get('Plans', [])))
                        used = indexes(plan[0]['Plan'])
                        if label == 'rare':
                            assert ('record_search_documents_vector_gin' if resource=='records' else
                                    'aggregation_search_documents_vector_gin') in used, (label,resource,'missing GIN path')
                        if label == 'filename' and resource == 'records':
                            assert 'digital_components_filename_vector_gin' in used
                        if label == 'content' and resource == 'records':
                            assert 'component_search_chunks_vector_gin' in used
                    c.commit()
            from tools.search_cache_performance import exercise as exercise_tab_cache
            failures.extend(exercise_tab_cache(client, c, output, repeats, identity, oracle))
        assert not failures, f'{len(failures)} responses exceeded 3 seconds; see {output}/results.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'.runtime'/'search-performance'/uuid4().hex)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--vector-storage', choices=('current', 'uncompressed'), default='current',
                        help='Disposable-only storage comparison; application schema is unchanged')
    parser.add_argument('--settle-seconds',type=int,default=0,
                        help='Explicit idle interval after fixture maintenance, before any search; recorded in evidence')
    args=parser.parse_args()
    if args.repeats<1:parser.error('repeats must be positive')
    if not 0<=args.settle_seconds<=300:parser.error('settle-seconds must be between 0 and 300')
    args.output.mkdir(parents=True,exist_ok=False)
    source_hashes = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
        'tools/check_search_performance.py', 'backend/services/api/search.py',
        'backend/services/api/search_page.py', 'backend/services/api/search_cache.py',
        'backend/services/api/search_projections.py',
        'backend/services/api/search_execution.py',
        'tools/search_cache_performance.py', 'tools/search_storage_experiment.py',
        'tools/search_benchmark_support.py',
        'backend/services/api/authentication.py',
        'backend/services/api/main.py',
        'backend/services/api/dashboard_visibility.py', 'database/schema.sql',
        'database/seeds/000_required_reference_data.sql')}
    config={**dotenv_values(ROOT/'.env'),**os.environ}
    name='erms_search_perf_'+uuid4().hex
    admin=make_conninfo(config['DATABASE_URL'],dbname='postgres')
    url=make_conninfo(config['DATABASE_URL'],dbname=name)
    created=False
    from tools.search_benchmark_support import HostMonitor, BufferedOutput
    monitor = HostMonitor(args.output)
    monitor.thread.start()
    def interrupted(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    try:
        with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        created=True;print('Created disposable database '+name,flush=True)
        os.environ.update({k:str(v) for k,v in config.items() if v is not None})
        os.environ.update(DATABASE_URL=url,AUTH_COOKIE_SECURE='false')
        with psycopg.connect(url,row_factory=dict_row) as c:
            initialize(c)
            from tools.search_storage_experiment import configure, inspect
            configure(c, args.vector_storage)
            seed(c)
            assert c.execute('SELECT count(*) AS n FROM aggregations').fetchone()['n']>50000
            assert c.execute('SELECT count(*) AS n FROM records').fetchone()['n']>150000
            from backend.services.api.search_execution import search_sql_execution
            with search_sql_execution(c):
                search_settings=c.execute("SELECT current_setting('jit') AS jit,current_setting('work_mem') AS work_mem").fetchone()
            (args.output/'environment.json').write_text(json.dumps({
                'database':name,'postgres':c.execute('SELECT version() AS v').fetchone()['v'],
                'platform':platform.platform(),'aggregations':AGGREGATIONS,'records':RECORDS,
                'components':RECORDS,'chunks':RECORDS*2,'repeats':args.repeats,
                'threshold_seconds':3,'page_size':100,'result_cap':1000,
                'source_sha256':source_hashes,
                'storage_experiment':inspect(c, args.vector_storage),
                'work_mem':c.execute('SHOW work_mem').fetchone()['work_mem'],
                'search_execution':search_settings,
                'jit_default':c.execute('SHOW jit').fetchone()['jit'],
                'jit_available':c.execute('SELECT pg_jit_available() AS value').fetchone()['value'],
                'search_jit':'disabled only within search execution; previous setting restored',
                'data_checksums':c.execute('SHOW data_checksums').fetchone()['data_checksums'],
                'wal_log_hints':c.execute('SHOW wal_log_hints').fetchone()['wal_log_hints'],
                'fixture_maintenance':'VACUUM ANALYZE after bulk load; no search warm-up',
                'post_load_idle_seconds':args.settle_seconds,
                'diagnostics':'Artifact writes buffered until all requests finish; oracle and EXPLAIN remain between timed requests',
                'cpu_count':os.cpu_count()},indent=2))
        print('Fixture ready',flush=True)
        if args.settle_seconds:
            print(f'Idling {args.settle_seconds} seconds after bulk-load maintenance; no search warm-up',flush=True)
            time.sleep(args.settle_seconds)
        buffered = BufferedOutput(args.output)
        try:
            exercise(buffered,args.repeats)
        finally:
            buffered.flush()
    except BaseException as error:
        (args.output/'failure.json').write_text(json.dumps({
            'type':type(error).__name__, 'message':str(error),
            'traceback':traceback.format_exc()},indent=2))
        raise
    finally:
        try:
            if created:
                with psycopg.connect(admin,autocommit=True) as c:c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                (args.output/'cleanup.json').write_text(json.dumps({'database':name,'dropped':True}))
                print('Dropped disposable database '+name,flush=True)
        finally:
            monitor.close()


if __name__=='__main__':main()
