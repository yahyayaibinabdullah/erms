"""Complete-request measurements, separate from the large search latency gate."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Barrier
from time import perf_counter
from uuid import uuid4
import psycopg

from .test_code_generator_database import actor, c, generator, resource_type


def test_complete_requests_with_concentrated_and_independent_counters(client,c,aggregation,monkeypatch):
    root=Path(__file__).resolve().parents[4]
    samples=[];calls=[];batches=[];errors=[]
    execute=psycopg.Cursor.execute
    def counted(cursor,*args,**kwargs):
        calls.append(None)
        try:return execute(cursor,*args,**kwargs)
        except psycopg.Error as error:
            errors.append(dict(sqlstate=error.sqlstate,message=error.diag.message_primary,
                               detail=error.diag.message_detail,context=error.diag.context))
            raise
    monkeypatch.setattr(psycopg.Cursor,'execute',counted)

    def measured(label,method,path,expected,**kwargs):
        started=perf_counter();before=len(calls)
        response=client.request(method,path,**kwargs)
        elapsed=perf_counter()-started
        assert response.status_code in (expected if isinstance(expected,tuple) else (expected,)),(response.text,errors)
        samples.append(dict(operation=label,seconds=elapsed,status=response.status_code,
                            cursor_execute_calls=None if label.endswith('_concurrent') else len(calls)-before))
        return response.json()

    definition=generator(c,pattern='LOAD-{SERIAL}')
    c.commit()
    body={'aggregation_id':aggregation['id'],'title':'Request measurement'}
    for _ in range(3):
        measured('recommendation','GET','/api/v1/number-suggestions/records',200,
                 params={'parent_aggregation_id':aggregation['id']})
    assert c.execute('SELECT count(*) AS n FROM code_generator_counters').fetchone()['n']==0

    barrier=Barrier(8)
    def concentrated(_):
        barrier.wait(timeout=15)
        return measured('concentrated_concurrent','POST','/api/v1/records',201,
                        headers={'Idempotency-Key':str(uuid4())},json=body)
    before=len(calls);started=perf_counter()
    with ThreadPoolExecutor(max_workers=8) as workers:
        rows=list(workers.map(concentrated,range(8)))
    batches.append(dict(workload='concentrated',seconds=perf_counter()-started,cursor_execute_calls=len(calls)-before))
    assert {r['record_number'] for r in rows}=={f'LOAD-{n}' for n in range(10,90,10)}
    assert c.execute('SELECT last_serial FROM code_generator_counters WHERE generator_id=%s',
                     (definition['id'],)).fetchone()['last_serial']==80

    # Manual values occupy the next two candidates without advancing a counter.
    for number in ('LOAD-90','LOAD-100'):
        measured('manual_occupancy','POST','/api/v1/records',201,
                 headers={'Idempotency-Key':str(uuid4())},json={**body,'record_number':number})
    headers={'Idempotency-Key':str(uuid4())}
    created=measured('skip_occupied','POST','/api/v1/records',201,headers=headers,json=body)
    assert created['record_number']=='LOAD-110'
    for _ in range(3):
        assert measured('completed_replay','POST','/api/v1/records',201,headers=headers,json=body)==created
    assert c.execute('SELECT last_serial FROM code_generator_counters WHERE generator_id=%s',
                     (definition['id'],)).fetchone()['last_serial']==110

    # Retire the broad binding, retain its counter and create disjoint typed ones.
    actor(c,reason='Measure independent counters')
    c.execute('UPDATE code_generators SET enabled=false WHERE id=%s',(definition['id'],))
    types=[resource_type(c,f'Load {i}') for i in range(8)]
    definitions=[generator(c,type_id=identity,pattern=f'T{i}-{{SERIAL}}') for i,identity in enumerate(types)]
    c.commit()
    barrier=Barrier(12)
    def independent(index):
        barrier.wait(timeout=15)
        if index==8:
            from .test_code_generator_routes import configuration
            return measured('rename_concurrent','PUT',f"/api/v1/code-generators/{definitions[0]['id']}",200,
                headers={'If-Match':'1','X-Change-Reason':'Load-test rename'},
                json=configuration(name='Renamed load series',type_id=types[0],pattern='T0-{SERIAL}',max_code_length=64))
        if index==9:
            return measured('advance_concurrent','POST',f"/api/v1/code-generators/{definitions[0]['id']}/counter/advance",(200,412),
                headers={'If-Match':'0','X-Change-Reason':'Load-test forward adjustment'},json={'next_number':'1000'})
        if index==10:
            return measured('manual_concurrent','POST','/api/v1/records',201,
                headers={'Idempotency-Key':str(uuid4())},json={**body,'record_number':'MANUAL-LOAD'})
        if index==11:
            return measured('search_concurrent','POST','/api/v1/records/search',200,
                json={'where':{'field':'aggregation_id','operator':'eq','value':aggregation['id']},'limit':25})
        row=measured('independent_concurrent','POST','/api/v1/records',201,
                     headers={'Idempotency-Key':str(uuid4())},json={**body,'type_id':types[index]})
        assert row['record_number'] in ({'T0-10','T0-1000'} if index==0 else {f'T{index}-10'})
        return row
    before=len(calls);started=perf_counter()
    with ThreadPoolExecutor(max_workers=12) as workers:
        assert len(list(workers.map(independent,range(12))))==12
    batches.append(dict(workload='independent_with_mutation_adjustment_manual_and_search',
                        seconds=perf_counter()-started,cursor_execute_calls=len(calls)-before))
    assert c.execute('SELECT count(*) AS n FROM code_generator_counters WHERE generator_id=ANY(%s) AND last_serial=10',
                     ([d['id'] for d in definitions[1:]],)).fetchone()['n']==7

    database=c.execute('SELECT current_database() AS name').fetchone()['name']
    output=root/'.runtime/custom-code-generators/request-metrics'
    output.mkdir(parents=True,exist_ok=True)
    (output/f'{database}.json').write_text(json.dumps(dict(database=database,
        concentrated_workers=8,independent_workers=12,samples=samples,batches=batches,
        note='Complete TestClient requests including authentication; no search-latency or production-throughput claim.'),indent=2))
