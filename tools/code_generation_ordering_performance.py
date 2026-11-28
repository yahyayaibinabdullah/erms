"""Natural-code ordering on the search gate's owned large disposable fixture."""
import json
import math
import time
from uuid import uuid4

from psycopg import sql


def seed(connection, output):
    # The base search reader has View only. Destination-selector cases also
    # require Add record on the aggregation. Grant it to that synthetic reader
    # only; the denied caller remains unchanged. This fixture runs after the
    # ordinary search measurements and never changes production permissions.
    connection.execute("SELECT set_config('app.event_source','seeding',true)")
    connection.execute("SET LOCAL session_replication_role='replica'")
    connection.execute("""INSERT INTO aggregation_acl_grants
        (aggregation_id,principal_type,role_id,permission_id)
        SELECT aggregation.id,'role',role.id,permission.id
        FROM aggregations aggregation CROSS JOIN roles role CROSS JOIN permissions permission
        WHERE role.code='PERF' AND permission.code='aggregation.add_record'
        ON CONFLICT DO NOTHING""")
    connection.commit()
    definitions = {}
    for kind in ('record', 'aggregation'):
        connection.execute("""SELECT set_config('app.user_id','',true),set_config('app.actor_type','',true),
            set_config('app.event_source','seeding',true)""")
        for target in (kind + '_number', 'title', 'description'):
            connection.execute("""INSERT INTO code_generators(name,kind,primary_field,pattern,max_code_length,enabled)
                VALUES(%s,%s,%s,'PERF-{SERIAL}',200,false)""", (f'Performance {kind} {target}', kind, target))
        field = connection.execute("""INSERT INTO resource_type_fields(kind,type_id,name,data_type,max_length,display_order)
            SELECT kind,id,'Code ordering benchmark','text',128,50 FROM resource_types
            WHERE kind=%s AND name='General' RETURNING id,type_id""", (kind,)).fetchone()
        assert field is not None, 'Natural ordering requires the mixed resource-type fixture'
        connection.execute("""INSERT INTO code_generators(name,kind,type_id,field_id,applies_to,pattern,max_code_length,enabled)
            VALUES(%s,%s,%s,%s,'type','DEPT-{SERIAL}',64,false)""", (f'Performance {kind} typed code',kind,field['type_id'],field['id']))
        connection.execute("SET LOCAL session_replication_role='replica'")
        inserted = connection.execute(sql.SQL("""INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,
            data_type,text_capacity,value) SELECT %s,id,type_id,%s,'text',128,resource_field_decode('text',to_jsonb(
                'DEPT-' || CASE WHEN id%%5=0 THEN lpad((id%%21)::text,3,'0') ELSE (id%%21)::text END
                || '-REF' || (id%%17)::text)) FROM {} WHERE type_id=%s""").format(sql.Identifier(kind+'s')),
            (kind,field['id'],field['type_id'])).rowcount
        connection.commit()
        # Keep the actual metadata documents current after fixture-only bulk SQL.
        connection.execute("""SELECT refresh_type_metadata_documents(kind,array_agg(DISTINCT resource_id ORDER BY resource_id))
            FROM resource_type_values WHERE kind=%s AND field_id=%s GROUP BY kind,resource_id / 10000
            ORDER BY kind,resource_id / 10000""", (kind,field['id']))
        connection.commit()
        definitions[kind] = {**field,'values':inserted}
    connection.autocommit = True
    try:
        connection.execute('VACUUM ANALYZE')
    finally:
        connection.autocommit = False
    counts = connection.execute("""SELECT (SELECT count(*) FROM records) AS records,
        (SELECT count(*) FROM aggregations) AS aggregations,(SELECT count(*) FROM code_generators) AS generators,
        (SELECT count(*) FROM code_generator_counters) AS counters,
        (SELECT count(*) FROM digital_component_search_chunks) AS chunks""").fetchone()
    (output/'code-order-fixture.json').write_text(json.dumps({'counts':counts,'fields':definitions,
        'definitions_disabled_but_attached':True,'stored_code_representations':1},indent=2))
    return definitions


def _expected(connection, resource, field, label, definition):
    """Flat fixture oracle, independent of production compilation and ranking.

    The fixture reader has explicit ACL grants on all containers and See grants
    on both types. The denied caller has no resource grants. Matching remains
    ordinary PostgreSQL text matching; only order expressions use the collation.
    """
    number = resource[:-1] + '_number'
    typed = label.startswith('typed_')
    join = sql.SQL(' LEFT JOIN resource_type_values v ON v.kind={} AND v.resource_id=r.id AND v.field_id={}').format(
        sql.Literal(resource[:-1]),sql.Literal(definition['id'])) if typed else sql.SQL('')
    value = sql.SQL('(v.value).text_value') if typed else sql.SQL('r.{}').format(sql.Identifier(field))
    predicate = sql.SQL('true')
    params = []
    if label == 'prefix':
        if resource == 'records':
            join += sql.SQL(' LEFT JOIN aggregations parent ON parent.id=r.aggregation_id')
            predicate = sql.SQL("concat_ws(' ',r.record_number,r.title,r.medium,parent.aggregation_number,parent.title) ILIKE %s")
        else:
            predicate = sql.SQL("concat_ws(' ',r.aggregation_number,r.title,r.medium) ILIKE %s")
        params.append('%PERF-15%')
    elif label == 'empty':
        predicate = sql.SQL('r.{} ILIKE %s').format(sql.Identifier(number)); params.append('ZZ-ABSENT%')
    elif label == 'selective':
        predicate = sql.SQL('r.id<=37')
    elif label == 'typed_missing':
        predicate = sql.SQL('r.id=ANY(%s)'); params.append([1,2,3,4,5,6])
    descending = label in ('descending','typed_descending')
    direction = sql.SQL('DESC' if descending else 'ASC')
    secondary = sql.SQL(',r.{} COLLATE erms_code_natural DESC').format(sql.Identifier(number)) if typed else sql.SQL('')
    score = sql.SQL("ts_rank_cd(d.search_vector,websearch_to_tsquery('simple','common'))::float8") if label == 'metadata' else sql.SQL('0.0::float8')
    if label == 'metadata':
        join += sql.SQL(' JOIN {} d ON d.{}=r.id').format(sql.Identifier(resource[:-1]+'_search_documents'),sql.Identifier(resource[:-1]+'_id'))
        predicate = sql.SQL("d.search_vector @@ websearch_to_tsquery('simple','common')")
    statement = sql.SQL('''SELECT r.id,{} AS score,count(*) OVER() AS matching FROM {} r {} WHERE {}
        ORDER BY {} COLLATE erms_code_natural {} NULLS LAST {},r.id LIMIT 1001''').format(
        score,sql.Identifier(resource),join,predicate,value,direction,secondary)
    rows = connection.execute(statement,params).fetchall()
    return rows[:1000], rows[0]['matching'] if rows else 0


def exercise(client, connection, output, repeats, definitions):
    from backend.services.api import search
    from backend.services.api.schemas import SearchRequest
    from backend.services.api.search_cache import _statement
    from backend.services.api.search_execution import search_sql_execution
    from tools.check_search_performance import PASSWORD
    samples, failures, expected_log = [], [], []

    def measured(method, endpoint, *, info, **kwargs):
        started = time.perf_counter()
        response = client.request(method,endpoint,**kwargs)
        sample = {**info,'seconds':time.perf_counter()-started,'status':response.status_code}
        samples.append(sample)
        if sample['seconds'] > 3:
            failures.append(sample)
        (output/'code-order-results.json').write_text(json.dumps({'samples':samples,'failures':failures},indent=2))
        return response

    for identity in ('reader','denied'):
        client.cookies.clear(); client.headers.pop('X-CSRF-Token',None)
        login = client.post('/api/v1/auth/login',json={'email':identity+'@performance.invalid','password':PASSWORD})
        assert login.status_code == 200,login.text
        client.headers['X-CSRF-Token'] = client.cookies['erms_csrf']
        tab = str(uuid4())
        for resource in ('records','aggregations'):
            definition = definitions[resource[:-1]]
            number = resource[:-1] + '_number'
            typed_key = f"type.{definition['type_id']}.field.{definition['id']}"
            for label in ('ascending','descending','prefix','empty','selective','metadata','title','description',
                          'typed_ascending','typed_descending','typed_missing','saved'):
                typed = label.startswith('typed_')
                field = typed_key if typed else label if label in ('title','description') else number
                criteria = {'sort':[{'field':field,'direction':'desc' if label in ('descending','typed_descending') else 'asc'}]}
                if typed:
                    criteria['sort'].append({'field':number,'direction':'desc'})
                if label == 'selective':
                    criteria['where'] = {'field':'id','operator':'lte','value':37}
                elif label == 'empty':
                    criteria['where'] = {'field':number,'operator':'starts_with_ci','value':'ZZ-ABSENT'}
                elif label == 'typed_missing':
                    criteria['where'] = {'field':'id','operator':'in','value':[1,2,3,4,5,6]}
                elif label == 'metadata':
                    criteria['where'] = {'full_text':{'query':'common','sources':['metadata']}}
                    criteria['include'] = ['full_text_matches']
                params = {'display_filter':'PERF-15'} if label == 'prefix' else {}
                endpoint = f'/api/v1/{resource}/search'
                if label == 'saved':
                    saved = client.post('/api/v1/saved-searches',json={'name':f'Code ordering {identity} {resource}',
                        'definition':{'resource_type':resource[:-1],'request':criteria}})
                    assert saved.status_code == 201,saved.text
                    endpoint = f"/api/v1/saved-searches/{saved.json()['id']}/execute"
                expected, matching = (None,None) if identity == 'reader' else ([],0)
                for repeat in range(repeats):
                    request = {'tab_id':tab,'limit':100,**({} if label == 'saved' else criteria)}
                    received = []
                    while True:
                        response = measured('POST',endpoint,json=request,params=params,info={'identity':identity,
                            'resource':resource,'case':label,'repeat':repeat,'offset':request.get('offset',0)})
                        if identity == 'denied' and typed:
                            assert response.status_code == 403,response.text
                            break
                        assert response.status_code == 200,response.text
                        body = response.json()
                        # First measure the real request. The independent
                        # oracle must not warm this case before its first sample.
                        if expected is None:
                            expected, matching = _expected(connection,resource,field,label,definition)
                            expected_log.append({'identity':identity,'resource':resource,'case':label,'matching':matching,
                                'capped':len(expected),'ranked':expected})
                            (output/'code-order-expected.json').write_text(json.dumps(expected_log,indent=2))
                        assert body['total'] == len(expected),(resource,label,body['total'],len(expected))
                        if request.get('search_id'):
                            assert body['search_id'] == request['search_id']
                        received.extend({'id':row['id'],'score':row.get('_search',{}).get('relevance',0.0)} for row in body['items'])
                        if len(received) >= len(expected):
                            break
                        assert body['items'],(resource,label,'empty page before the result end')
                        request.update(search_id=body['search_id'],offset=len(received))
                    if not (identity == 'denied' and typed):
                        assert [row['id'] for row in received] == [row['id'] for row in expected],(resource,label)
                        assert all(math.isclose(a['score'],b['score'],rel_tol=1e-6,abs_tol=1e-7)
                                   for a,b in zip(received,expected,strict=True)),(resource,label)
                    (output/f'code-order-{identity}-{resource}-{label}-{repeat}.json').write_text(json.dumps(received))
                if identity == 'reader':
                    uid = connection.execute("SELECT id FROM users WHERE email='reader@performance.invalid'").fetchone()['id']
                    connection.execute("SELECT set_config('app.user_id',%s,true)",(str(uid),))
                    parsed = SearchRequest(**criteria,tab_id=tab)
                    fields, _ = search.search_fields(connection,resource,parsed)
                    canonical = search.canonicalize_search_request(connection,resource,parsed,fields=fields)
                    statement, arguments = _statement(resource,parsed,canonical,params.get('display_filter'),None,1000,fields)
                    with search_sql_execution(connection):
                        plan = connection.execute(sql.SQL('EXPLAIN (ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) ')+statement,arguments).fetchone()['QUERY PLAN']
                    (output/f'code-order-{resource}-{label}-plan.json').write_text(json.dumps({'sql':statement.as_string(connection),
                        'parameters':arguments,'plan':plan},indent=2,default=str))
                    connection.commit()
                print(json.dumps({'identity':identity,'resource':resource,'code_order':label,'returned':len(expected)}),flush=True)
        failures.extend(exercise_navigation(client,connection,output,repeats,identity,tab))
    assert connection.execute('SELECT count(*) AS n FROM code_generator_counters').fetchone()['n'] == 0
    (output/'code-order-expected.json').write_text(json.dumps(expected_log,indent=2))
    (output/'code-order-results.json').write_text(json.dumps({'samples':samples,'failures':failures},indent=2))
    return failures


def exercise_navigation(client, connection, output, repeats, identity, tab):
    """Changed keyset selectors and uncapped contents, with their actual plans."""
    from backend.services.api.browse import _aggregation_browse_source, RECORD_SOURCE
    from backend.services.api.search_page import contained_record_page_statement
    from backend.services.api.search_execution import search_sql_execution
    samples, failures = [], []
    classification = connection.execute("SELECT id FROM classifications WHERE code='PERF'").fetchone()['id']
    slot_before = connection.execute('SELECT search_id FROM search_results_cache WHERE tab_id=%s',(tab,)).fetchone()

    def request(method,path,info,**kwargs):
        started=time.perf_counter()
        response=client.request(method,path,**kwargs)
        sample={**info,'seconds':time.perf_counter()-started,'status':response.status_code}
        samples.append(sample)
        if sample['seconds']>3:failures.append(sample)
        (output/f'code-navigation-{identity}.json').write_text(json.dumps({'samples':samples,'failures':failures},indent=2))
        return response

    for label in ('contained_records','record_selector','child_selector','root_selector','root_broad',
                  'root_creation_prefix','root_creation_broad'):
        root_creation=label.startswith('root_creation')
        root_prefix=label in ('root_selector','root_creation_prefix')
        first_page_only=label in ('root_broad','root_creation_broad')
        owner=connection.execute("SELECT id FROM org_units WHERE code='PERF'").fetchone()['id'] if root_creation else None
        expected=None if identity=='reader' else []
        for repeat in range(repeats):
            received=[];cursor=None;offset=0
            while True:
                info={'case':label,'repeat':repeat,'offset':offset}
                if label=='contained_records':
                    response=request('POST','/api/v1/records/search',info,json={
                        'where':{'field':'aggregation_id','operator':'eq','value':1},
                        'sort':[{'field':'record_number','direction':'asc'}],'include':['record_capabilities'],
                        'limit':100,'offset':offset})
                else:
                    path=('/api/v1/browse/aggregations/1/records' if label=='record_selector' else
                          '/api/v1/browse/aggregations/1/children' if label=='child_selector' else
                          f'/api/v1/browse/classifications/{classification}/aggregations')
                    response=request('GET',path,info,params={'limit':100,'query':'PERF-15' if root_prefix else '',
                        **({'record_creation':True,'digital_only':True,'owning_org_unit_id':owner} if root_creation else {}),
                        **({'cursor':cursor} if cursor else {})})
                if identity=='denied' and label in ('child_selector','record_selector'):
                    assert response.status_code==404,response.text
                    break
                assert response.status_code==200,response.text
                body=response.json()
                if expected is None:
                    if label in ('contained_records','record_selector'):
                        expected=[row['id'] for row in connection.execute('SELECT id FROM records WHERE aggregation_id=1 ORDER BY record_number COLLATE erms_code_natural,id')]
                    else:
                        clause='parent_aggregation_id=1' if label=='child_selector' else 'parent_aggregation_id IS NULL AND classification_id=%s'
                        parameters=[] if label=='child_selector' else [classification]
                        if root_prefix:
                            clause+=" AND (aggregation_number ILIKE 'PERF-15%%' OR title ILIKE 'PERF-15%%')"
                        if root_creation:
                            # The fixed reader has View/Add record, a current
                            # role in PERF and global record.create. Its typed
                            # grants deny Use, so only untyped open digital
                            # roots are destinations.
                            clause+=" AND type_id IS NULL AND date_closed IS NULL AND medium IN ('digital','mixed') AND owning_org_unit_id=%s"
                            parameters.append(owner)
                        expected=[row['id'] for row in connection.execute('SELECT id FROM aggregations WHERE '+clause+
                            ' ORDER BY aggregation_number COLLATE erms_code_natural,id',parameters)]
                    (output/f'code-navigation-{label}-expected.json').write_text(json.dumps({'matching':len(expected),'ids':expected}))
                assert body['total']==len(expected),(label,body['total'],len(expected))
                received.extend(row['id'] for row in body['items'])
                if first_page_only:
                    # Measure broad candidate/count/sort work without a filter;
                    # complete reachability is checked by the >1,000-row branch
                    # and prefix traversals, whose every response is measured.
                    assert received==expected[:len(received)]
                    break
                if len(received)>=len(expected):break
                assert body['items'],(label,'empty before the end')
                offset=len(received)
                cursor=body.get('next_cursor')
                if label!='contained_records':assert cursor
            if not first_page_only:assert received==expected,(identity,label)
        if identity=='reader':
            uid=connection.execute("SELECT id FROM users WHERE email='reader@performance.invalid'").fetchone()['id']
            connection.execute("SELECT set_config('app.user_id',%s,true)",(str(uid),))
            if label=='contained_records':
                statement=contained_record_page_statement(number_order=True,natural_number=True)
                arguments=[1,100,0]
                with search_sql_execution(connection):
                    plan=connection.execute(sql.SQL('EXPLAIN (ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) ')+statement,arguments).fetchone()['QUERY PLAN']
                (output/'code-navigation-contents-plan.json').write_text(json.dumps(plan,indent=2))
            else:
                source=(RECORD_SOURCE+' AND r.aggregation_id=%s' if label=='record_selector' else
                        _aggregation_browse_source(root_creation,root_creation,children=label=='child_selector')+
                        ('' if label=='child_selector' else ' AND a.classification_id=%s AND a.parent_aggregation_id IS NULL'+
                         (' AND a.owning_org_unit_id=%s' if root_creation else '')))
                arguments=[1] if label in ('child_selector','record_selector') else [classification,*([owner] if root_creation else [])]
                filters=" WHERE (coalesce(aggregation_number,'') ILIKE %s OR coalesce(title,'') ILIKE %s)" if root_prefix else ''
                if root_prefix:arguments.extend(['%PERF-15%']*2)
                key='record_number' if label=='record_selector' else 'aggregation_number'
                for mode in ('count','page'):
                    statement=('SELECT count(*) FROM ('+source+') code_source'+filters if mode=='count' else
                        'SELECT * FROM ('+source+') code_source'+filters+f' ORDER BY {key} COLLATE erms_code_natural,id LIMIT 101')
                    plan=connection.execute('EXPLAIN (ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) '+statement,arguments).fetchone()['QUERY PLAN']
                    (output/f'code-navigation-{label}-{mode}-plan.json').write_text(json.dumps({'sql':statement,'parameters':arguments,'plan':plan},indent=2))
            connection.commit()
    assert connection.execute('SELECT search_id FROM search_results_cache WHERE tab_id=%s',(tab,)).fetchone()==slot_before
    return failures


def exercise_owned(url, output, repeats):
    import psycopg
    from psycopg.rows import dict_row
    from fastapi.testclient import TestClient
    from backend.services.api.main import app
    with psycopg.connect(url,row_factory=dict_row) as connection, TestClient(app) as client:
        definitions = seed(connection,output)
        failures = exercise(client,connection,output,repeats,definitions)
    assert not failures,f'{len(failures)} natural-code responses exceeded 3 seconds; see code-order-results.json'
