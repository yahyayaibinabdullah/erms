"""Representative classification-tree API measurements; no application tuning."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import json
import math
import statistics
import time

import psycopg
from psycopg.rows import dict_row


PAGE_SIZE = 50


def seed(connection, output, *, root_count=50000):
    """Reshape the owned synthetic fixture; preserve overall repository size."""
    total = connection.execute('SELECT count(*) AS n FROM aggregations').fetchone()['n']
    assert 1000 <= root_count < total
    assert total-root_count <= root_count
    scheme = connection.execute("SELECT id FROM classification_schemes WHERE code='PERF'").fetchone()['id']
    original = connection.execute("SELECT id FROM classifications WHERE code='PERF'").fetchone()['id']
    leaf_count = math.ceil(root_count/100)
    connection.execute("SELECT set_config('app.event_source','seeding',true)")
    connection.execute("SET LOCAL session_replication_role='replica'")
    connection.execute('DELETE FROM classification_retention_rules WHERE classification_id=%s',(original,))
    connection.execute("UPDATE classifications SET is_terminal=false,code='TREE-GROUP-000',title='Tree group 0' WHERE id=%s",(original,))
    groups = [original]
    for index in range(1, math.ceil(leaf_count/100)):
        groups.append(connection.execute("""INSERT INTO classifications
            (classification_scheme_id,code,title,is_terminal) VALUES(%s,%s,%s,false) RETURNING id""",
            (scheme,f'TREE-GROUP-{index:03}',f'Tree group {index}')).fetchone()['id'])
    leaves = []
    for index in range(leaf_count):
        leaves.append(connection.execute("""INSERT INTO classifications
            (classification_scheme_id,parent_classification_id,code,title,is_terminal)
            VALUES(%s,%s,%s,%s,true) RETURNING id""",
            (scheme,groups[index//100],f'TREE-CLASS-{index:04}',f'Tree classification {index}')).fetchone()['id'])
    empty = connection.execute("""INSERT INTO classifications
        (classification_scheme_id,code,title,is_terminal)
        VALUES(%s,'TREE-EMPTY','Empty tree classification',true) RETURNING id""",(scheme,)).fetchone()['id']
    connection.execute("""INSERT INTO classification_retention_rules
        (classification_id,current_period_years,intermediate_period_years,final_disposition)
        SELECT id,5,0,'destruction' FROM unnest(%s::bigint[]) id""",([*leaves,empty],))
    connection.execute("""UPDATE aggregations SET parent_aggregation_id=NULL,
        classification_id=(%s::bigint[])[1+((id-1)/100)::integer] WHERE id<=%s""",(leaves,root_count))
    connection.execute("""UPDATE aggregations SET classification_id=NULL,
        parent_aggregation_id=1+100*((id-%s-1)/100) WHERE id>%s""",(root_count,root_count))
    # Two tested parents have 100 records each; the rest remain distributed.
    connection.execute("""WITH targets AS (SELECT array_agg(id ORDER BY id) AS ids
        FROM aggregations WHERE id<>ALL(%s::bigint[]))
        UPDATE records SET aggregation_id=CASE WHEN id<=100 THEN 1 WHEN id<=200 THEN 101
        ELSE ids[1+mod(id-201,cardinality(ids))::integer] END FROM targets""",([1,101,root_count],))
    connection.commit()
    connection.execute("SELECT set_config('app.event_source','seeding',true)")
    for kind in ('aggregation','record'):
        connection.execute("""INSERT INTO code_generators(name,kind,primary_field,pattern,max_code_length,enabled)
            VALUES(%s,%s,%s,'PERF-{SERIAL}',128,false)""",
            (f'Representative tree {kind} numbers',kind,kind+'_number'))
    connection.commit()
    connection.autocommit = True
    try:
        connection.execute('VACUUM ANALYZE')
    finally:
        connection.autocommit = False
    counts = connection.execute("""SELECT
        (SELECT count(*) FROM aggregations) AS aggregations,
        (SELECT count(*) FROM records) AS records,
        (SELECT max(n) FROM (SELECT count(*) n FROM aggregations WHERE parent_aggregation_id IS NOT NULL
            GROUP BY parent_aggregation_id) branches) AS maximum_child_aggregations,
        (SELECT max(n) FROM (SELECT count(*) n FROM aggregations WHERE parent_aggregation_id IS NULL
            GROUP BY classification_id) branches) AS maximum_roots_per_classification""").fetchone()
    assert counts['maximum_child_aggregations']==100
    assert counts['maximum_roots_per_classification']==100
    refs={'scheme':scheme,'group':groups[0],'leaf':leaves[0],'other_leaf':leaves[1],
          'empty_classification':empty,'empty_records_parent':root_count,
          'short_parent':1+100*((total-root_count-1)//100)}
    (output/'tree-fixture.json').write_text(json.dumps({
        'profile':'representative','page_size':PAGE_SIZE,'counts':counts,'references':refs,
        'root_aggregations':root_count,'terminal_classifications':leaf_count+1,
        'group_classifications':len(groups),'selected_parents':[1,101],
        'records_per_selected_parent':100,'disabled_number_generators_attached':True,
        'notes':'Branch distribution is a test profile, not application limits. File-text chunks are not needed by tree requests.'},indent=2))
    connection.commit()
    return refs


def cases(refs):
    return [
        ('classification_roots',f"classification-schemes/{refs['scheme']}/roots",'classifications','classification_scheme_id',refs['scheme'],'code',False,''),
        ('classification_children',f"classifications/{refs['group']}/children",'classifications','parent_classification_id',refs['group'],'code',False,''),
        ('root_aggregations',f"classifications/{refs['leaf']}/aggregations",'aggregations','classification_id',refs['leaf'],'aggregation_number',True,''),
        ('other_root_branch',f"classifications/{refs['other_leaf']}/aggregations",'aggregations','classification_id',refs['other_leaf'],'aggregation_number',True,''),
        ('filtered_roots',f"classifications/{refs['leaf']}/aggregations",'aggregations','classification_id',refs['leaf'],'aggregation_number',True,'PERF-1'),
        ('empty_root_filter',f"classifications/{refs['leaf']}/aggregations",'aggregations','classification_id',refs['leaf'],'aggregation_number',True,'ZZ-ABSENT'),
        ('empty_classification',f"classifications/{refs['empty_classification']}/aggregations",'aggregations','classification_id',refs['empty_classification'],'aggregation_number',True,''),
        ('short_children',f"aggregations/{refs['short_parent']}/children",'aggregations','parent_aggregation_id',refs['short_parent'],'aggregation_number',True,''),
        ('empty_children','aggregations/2/children','aggregations','parent_aggregation_id',2,'aggregation_number',True,''),
        ('empty_records',f"aggregations/{refs['empty_records_parent']}/records",'records','aggregation_id',refs['empty_records_parent'],'record_number',True,''),
        ('filtered_records','aggregations/1/records','records','aggregation_id',1,'record_number',True,'PERF-1'),
    ]


def expected(connection, case, identity):
    label,path,table,column,value,key,natural,query = case
    if identity=='denied' and table!='classifications':
        return []
    predicate = f'{column}=%s'
    if table=='classifications' and column=='classification_scheme_id':
        predicate += ' AND parent_classification_id IS NULL'
    if table=='aggregations' and column=='classification_id':
        predicate += ' AND parent_aggregation_id IS NULL'
    args = [value]
    if query:
        predicate += f" AND (coalesce({key},'') ILIKE %s OR coalesce(title,'') ILIKE %s)"
        args.extend([f'%{query}%']*2)
    collation='erms_code_natural' if natural else '"C"'
    return [row['id'] for row in connection.execute(
        f'SELECT id FROM {table} WHERE {predicate} ORDER BY {key} COLLATE {collation},id',args)]


def statistics_for(values):
    ordered=sorted(values)
    return {'samples':len(values),'median_seconds':statistics.median(values),
        'p95_seconds':ordered[math.ceil(.95*len(ordered))-1],'maximum_seconds':ordered[-1],
        'over_three_seconds':sum(value>3 for value in values)}


def exercise_owned(url, output, repeats):
    from backend.services.api.main import app
    from tools.check_search_performance import PASSWORD
    refs=json.loads((output.directory/'tree-fixture.json').read_text())['references']
    return exercise(url,output,repeats,refs,app,PASSWORD)


def exercise(url, output, repeats, refs, app, password, *, http_client=None):
    from fastapi.testclient import TestClient
    samples,expansions,expectations,diagnostics = [],[],{},[]
    completed=False
    manager=TestClient(app) if http_client is None else nullcontext(http_client)
    with psycopg.connect(url,row_factory=dict_row) as connection, manager as client:
        def request(identity,label,repeat,path,query='',cursor=None):
            params={'limit':PAGE_SIZE,**({'query':query} if query else {}),**({'cursor':cursor} if cursor else {})}
            started=time.perf_counter()
            response=client.get('/api/v1/browse/'+path,params=params)
            sample={'identity':identity,'case':label,'repeat':repeat,'page_kind':'next' if cursor else 'first',
                'seconds':time.perf_counter()-started,'status':response.status_code,'path':path,'parameters':params}
            samples.append(sample)
            return response

        def validate(response,ids,offset=0,denied=False):
            if denied:
                assert response.status_code==404,response.text
                return None,[]
            assert response.status_code==200,response.text
            body=response.json();page=body['items']
            if identity=='denied':
                assert all(row.get('root_aggregation_count',0)==0 for row in page)
            assert body['total']==len(ids),(body['total'],len(ids))
            assert [row['id'] for row in page]==ids[offset:offset+PAGE_SIZE]
            assert len(page)<=PAGE_SIZE
            assert bool(body['next_cursor'])==(offset+len(page)<len(ids))
            return body['next_cursor'],[row['id'] for row in page]

        try:
            for identity in ('reader','denied'):
                client.cookies.clear();client.headers.pop('X-CSRF-Token',None)
                login=client.post('/api/v1/auth/login',json={'email':identity+'@performance.invalid','password':password})
                assert login.status_code==200,login.text
                client.headers['X-CSRF-Token']=client.cookies['erms_csrf']
                for case in cases(refs):
                    label,path,table,column,value,key,natural,query=case
                    ids=None
                    for repeat in range(repeats):
                        cursor=None;received=[]
                        while True:
                            response=request(identity,label,repeat,path,query,cursor)
                            if ids is None:
                                ids=expected(connection,case,identity)
                                expectations[identity+'-'+label]=ids
                                connection.commit()
                            cursor,part=validate(response,ids,len(received),
                                denied=identity=='denied' and path.startswith('aggregations/'))
                            received.extend(part)
                            if not cursor:break
                        assert received==ids
                    diagnostics.append((identity,label,path,query))
                    print(json.dumps({'tree_case':label,'identity':identity,'matching':len(ids)}),flush=True)
                # Expanding an aggregation in the real tree fetches children
                # and records concurrently. Load-more requests remain per branch.
                for parent in (1,101):
                    definitions=[(f'children_{parent}',f'aggregations/{parent}/children','aggregations',
                        'parent_aggregation_id',parent,'aggregation_number',True,''),
                        (f'records_{parent}',f'aggregations/{parent}/records','records',
                        'aggregation_id',parent,'record_number',True,'')]
                    for repeat in range(repeats):
                        started=time.perf_counter()
                        with ThreadPoolExecutor(max_workers=2) as executor:
                            responses=list(executor.map(lambda case:request(identity,case[0],repeat,case[1]),definitions))
                        expansions.append({'identity':identity,'parent':parent,'repeat':repeat,
                            'seconds':time.perf_counter()-started,'concurrent_requests':2})
                        for case,response in zip(definitions,responses,strict=True):
                            ids=expected(connection,case,identity);connection.commit()
                            expectations[identity+'-'+case[0]]=ids
                            cursor,part=validate(response,ids,denied=identity=='denied')
                            received=part
                            while cursor:
                                response=request(identity,case[0],repeat,case[1],cursor=cursor)
                                cursor,part=validate(response,ids,len(received));received.extend(part)
                            assert received==ids
                    diagnostics.extend((identity,case[0],case[1],'') for case in definitions)
            assert connection.execute('SELECT count(*) n FROM code_generator_counters').fetchone()['n']==0
            completed=True
            # Capture the exact browse count/page SQL only after response timing.
            execute=psycopg.Cursor.execute
            captured=[]
            def capture(cursor,statement,params=None,*args,**kwargs):
                value=statement.as_string(cursor.connection) if hasattr(statement,'as_string') else statement
                if isinstance(value,str) and 'browse_source' in value:
                    captured.append((value,params))
                return execute(cursor,statement,params,*args,**kwargs)
            for identity in ('reader','denied'):
                client.cookies.clear()
                client.headers.pop('X-CSRF-Token',None)
                assert client.post('/api/v1/auth/login',json={'email':identity+'@performance.invalid','password':password}).status_code==200
                uid=connection.execute('SELECT id FROM users WHERE email=%s',(identity+'@performance.invalid',)).fetchone()['id']
                connection.execute("SELECT set_config('app.user_id',%s,true)",(str(uid),))
                for caller,label,path,query in diagnostics:
                    if caller!=identity:continue
                    captured.clear();psycopg.Cursor.execute=capture
                    try:
                        response=client.get('/api/v1/browse/'+path,params={'limit':PAGE_SIZE,'query':query})
                    finally:
                        psycopg.Cursor.execute=execute
                    assert response.status_code in (200,404)
                    plans=[]
                    for statement,params in captured:
                        plan=connection.execute('EXPLAIN (ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) '+statement,params).fetchone()['QUERY PLAN']
                        plans.append({'sql':statement,'parameters':params,'plan':plan})
                    (output/f'tree-plan-{identity}-{label}.json').write_text(json.dumps({
                        'jit':connection.execute('SHOW jit').fetchone()['jit'],'statements':plans},indent=2))
                connection.commit()
        finally:
            grouped={}
            for identity,label,page in sorted({(r['identity'],r['case'],r['page_kind']) for r in samples}):
                grouped[f'{identity}/{label}/{page}']=statistics_for([r['seconds'] for r in samples
                    if (r['identity'],r['case'],r['page_kind'])==(identity,label,page)])
            (output/'tree-results.json').write_text(json.dumps({'profile':'representative','page_size':PAGE_SIZE,
                'repeats':repeats,'correctness_complete':completed,'samples':samples,'by_case_caller_page':grouped,
                'summary':statistics_for([r['seconds'] for r in samples]) if samples else {},
                'above_target':[r for r in samples if r['seconds']>3],'expansion_pairs':expansions,
                'expansion_summary':statistics_for([r['seconds'] for r in expansions]) if expansions else {}},indent=2))
            (output/'tree-expected-ids.json').write_text(json.dumps(expectations,indent=2))
