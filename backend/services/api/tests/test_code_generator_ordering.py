"""CG-08: field attachment changes SQL order, paging and cache semantics only."""
import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.services.api.crud import list_rows
from .test_code_generator_database import c, generator, resource_type, actor
from .test_code_generation_creation import field
from .test_saved_searches import _payload


def ok(response,status=200):
    assert response.status_code==status,response.text
    return response.json()


def records(client,aggregation,numbers):
    return [ok(client.post('/api/v1/records',json={'aggregation_id':aggregation['id'],
        'record_number':number,'title':'Code order fixture'}),201) for number in numbers]


@pytest.mark.parametrize('resource',['records','aggregations'])
def test_primary_code_order_and_browse_cursors_follow_attachment_even_when_disabled(client,c,aggregation,resource):
    number='record_number' if resource=='records' else 'aggregation_number'
    codes=['EMP-11','EMP-1','EMP-10','EMP-2','EMP-001']
    if resource=='records':
        rows=records(client,aggregation,codes)
        parent={'aggregation_id':aggregation['id']}
        path=f"/api/v1/browse/aggregations/{aggregation['id']}/records"
    else:
        parent={'parent_aggregation_id':aggregation['id']}
        rows=[ok(client.post('/api/v1/aggregations',json={**parent,number:code,'title':'Code order fixture'}),201) for code in codes]
        path=f"/api/v1/browse/aggregations/{aggregation['id']}/children"
    ids=[row['id'] for row in rows]
    criteria={'where':{'field':'id','operator':'in','value':ids},'sort':[{'field':number,'direction':'asc'}]}
    def search(**changes):
        return ok(client.post(f'/api/v1/{resource}/search',json={**criteria,**changes}))
    assert [r[number] for r in search()['items']]==sorted(codes)
    old=ok(client.get(path,params={'limit':2,'query':'EMP-'}))['next_cursor']
    definition=generator(c,kind=resource[:-1],primary_field=number,pattern='EMP-{SERIAL}',enabled=False)
    c.commit()
    expected=['EMP-001','EMP-1','EMP-2','EMP-10','EMP-11']
    assert [r[number] for r in search()['items']]==expected
    assert [r[number] for r in search(sort=[{'field':number,'direction':'desc'}])['items']]==expected[::-1]
    actor(c)
    assert [r[number] for r in list_rows(c,resource,limit=10,offset=0,filters=parent,order_by=(number,))]==expected
    assert client.get(path,params={'limit':2,'query':'EMP-','cursor':old}).status_code==400
    cursor=None
    found=[]
    for _ in range(3):
        page=ok(client.get(path,params={'limit':2,'query':'EMP-',**({'cursor':cursor} if cursor else {})}))
        found.extend(row[number] for row in page['items'])
        cursor=page['next_cursor']
    assert found==expected and cursor is None
    actor(c,reason='Remove the field attachment')
    c.execute('UPDATE code_generators SET primary_field=NULL WHERE id=%s',(definition['id'],))
    c.commit()
    assert [r[number] for r in search()['items']]==sorted(codes)
    assert c.execute('SELECT count(*) AS n FROM code_generator_counters').fetchone()['n']==0


def test_typed_text_natural_sort_keeps_secondary_keys_nulls_and_single_stored_values(client,c,aggregation):
    type_id=resource_type(c)
    fid=field(c,type_id,'Code reference',1)
    c.commit()
    values=['EMP-1','EMP-10','EMP-2',None,'EMP-2']
    rows=[ok(client.post('/api/v1/records',json={'aggregation_id':aggregation['id'],'record_number':f'O-{index}',
        'title':'Typed code','type_id':type_id,'field_values':{str(fid):value}}),201) for index,value in enumerate(values,1)]
    actor(c)
    generator(c,primary_field=None,type_id=type_id,field_id=fid,pattern='EMP-{SERIAL}')
    c.commit()
    key=f'type.{type_id}.field.{fid}'
    for direction,positions in [('asc',[0,4,2,1,3]),('desc',[1,4,2,0,3])]:
        criteria={'where':{'field':'id','operator':'in','value':[r['id'] for r in rows]},
            'sort':[{'field':key,'direction':direction},{'field':'record_number','direction':'desc'}]}
        expected=[rows[index]['id'] for index in positions]
        ordinary=ok(client.post('/api/v1/records/advanced-search',json=criteria))
        assert [r['id'] for r in ordinary['items']]==expected
        tab=str(uuid4())
        first=ok(client.post('/api/v1/records/advanced-search',json={**criteria,'tab_id':tab,'limit':2}))
        found=[r['id'] for r in first['items']]
        for offset in (2,4):
            page=ok(client.post('/api/v1/records/advanced-search',json={**criteria,'tab_id':tab,
                'search_id':first['search_id'],'limit':2,'offset':offset}))
            found.extend(r['id'] for r in page['items'])
            assert page['search_id']==first['search_id']
        assert found==expected
    assert [ok(client.get(f"/api/v1/records/{row['id']}"))['field_values'].get(str(fid)) for row in rows]==values
    generated=ok(client.post('/api/v1/records',json={'aggregation_id':aggregation['id'],'record_number':'O-6',
        'title':'Generated typed code','type_id':type_id}),201)
    assert generated['field_values']=={str(fid):'EMP-10'}  # Typed uniqueness is deferred.


def test_ranked_slot_rebuilds_for_changed_order_but_not_name_or_enabled_changes(client,c,aggregation):
    rows=records(client,aggregation,['R-1','R-10','R-2'])
    criteria={'where':{'field':'id','operator':'in','value':[r['id'] for r in rows]},
              'sort':[{'field':'record_number','direction':'asc'}]}
    payload={'tab_id':str(uuid4()),'limit':2,**criteria}
    first=ok(client.post('/api/v1/records/advanced-search',json=payload))
    assert [r['record_number'] for r in first['items']]==['R-1','R-10']
    definition=generator(c,pattern='R-{SERIAL}')
    c.commit()
    changed=ok(client.post('/api/v1/records/advanced-search',json={**payload,'search_id':first['search_id']}))
    assert changed['search_id']!=first['search_id']
    assert [r['record_number'] for r in changed['items']]==['R-1','R-2']
    actor(c,reason='Rename and pause future allocation')
    c.execute("UPDATE code_generators SET name='New display name',enabled=false,pattern='NEW{SERIAL}' WHERE id=%s",(definition['id'],))
    c.commit()
    retained=ok(client.post('/api/v1/records/advanced-search',json={**payload,'search_id':changed['search_id'],'offset':2}))
    assert retained['search_id']==changed['search_id'] and retained['items'][0]['record_number']=='R-10'
    saved=ok(client.post('/api/v1/saved-searches',json=_payload(definition={'schema_version':1,
        'resource_type':'record','max_results':1000,'request':{**criteria,'limit':25,'offset':0}})),201)
    executed=ok(client.post(f"/api/v1/saved-searches/{saved['id']}/execute",json={'tab_id':payload['tab_id']}))
    assert [r['record_number'] for r in executed['items']]==['R-1','R-2','R-10']
    assert c.execute('SELECT count(*) AS n FROM search_results_cache').fetchone()['n']==1


def test_icu_digit_run_diagnostic_records_the_actual_boundary(c):
    cases=[]
    for digits in (253,254,255,256):
        left='9'*digits
        right='1'+'0'*digits
        comparison=c.execute('SELECT %s COLLATE erms_code_natural < %s COLLATE erms_code_natural AS ordered',
                             (left,right)).fetchone()['ordered']
        cases.append({'left_digits':digits,'right_digits':digits+1,'expected_numeric_less':True,'icu_less':comparison})
    coll=c.execute("""SELECT collprovider,collisdeterministic,collversion,pg_collation_actual_version(oid) AS actual_version
        FROM pg_collation WHERE collname='erms_code_natural'""").fetchone()
    directory=Path(__file__).resolve().parents[4]/'.runtime/custom-code-generators/ordering-metrics'
    directory.mkdir(parents=True,exist_ok=True)
    (directory/f'{c.info.dbname}-icu-boundary.json').write_text(json.dumps({'collation':coll,'cases':cases},indent=2)+'\n')
    assert cases[0]['icu_less'] is True
    assert c.execute("""SELECT %s COLLATE erms_code_natural < %s COLLATE erms_code_natural AS ordered""",
        ('1'*254,'2'*254)).fetchone()['ordered'] is True
    assert c.execute("""SELECT %s COLLATE erms_code_natural < %s COLLATE erms_code_natural AS ordered""",
        ('0'*1000+'2','0'*1000+'10')).fetchone()['ordered'] is True


def test_other_fields_keep_their_order_and_long_manual_text_remains_writable(client,c,aggregation):
    rows=[ok(client.post('/api/v1/records',json={'aggregation_id':aggregation['id'],'record_number':f'M{index}',
        'title':f'Title {value}'}),201) for index,value in enumerate((1,10,2),1)]
    generator(c,pattern='M{SERIAL}')
    c.commit()
    def ordered(ids,field='title',**extras):
        return ok(client.post('/api/v1/records/search',json={
            'where':{'field':'id','operator':'in','value':ids},'sort':[{'field':field,'direction':'asc'}],**extras}))
    ids=[row['id'] for row in rows]
    assert [r['id'] for r in ordered(ids)['items']]==ids
    actor(c)
    generator(c,primary_field='title',pattern='T{SERIAL}',enabled=False,max_code_length=20)
    c.commit()
    assert [r['id'] for r in ordered(ids)['items']]==[ids[0],ids[2],ids[1]]
    prefix='文'*20000
    long=[ok(client.post('/api/v1/records',json={'aggregation_id':aggregation['id'],'record_number':f'M{index}',
        'title':prefix+str(value)}),201) for index,value in ((4,10),(5,2))]
    assert [r['id'] for r in ordered([r['id'] for r in long])['items']]==[long[1]['id'],long[0]['id']]
    # The uncached parent shortcut must use the same collation in both its
    # page selection and final projection.
    page=ok(client.post('/api/v1/records/search',json={'where':{'field':'aggregation_id','operator':'eq',
        'value':aggregation['id']},'sort':[{'field':'record_number','direction':'asc'}],
        'include':['record_capabilities'],'limit':2,'offset':2}))
    assert [r['record_number'] for r in page['items']]==['M3','M4']


def test_report_rows_use_the_attached_aggregation_number_order(client,c):
    from backend.services.api.disposition.report_presentation import aggregation_rows
    folders=[ok(client.post('/api/v1/aggregations',json={'classification_id':1,
        'aggregation_number':number,'title':'Code order report'}),201) for number in ('R-1','R-10','R-2')]
    ids=[row['id'] for row in folders]
    data={'results':[{'governing_root_id':identity,'effect':{'effects':[]}} for identity in ids],
          'reviewed_membership':[{'root_id':identity} for identity in ids]}
    assert [row['aggregation.number'] for row in aggregation_rows(c,data,'Asia/Dubai','en')]==['R-1','R-10','R-2']
    generator(c,kind='aggregation',primary_field='aggregation_number',pattern='R-{SERIAL}',enabled=False)
    c.commit()
    actor(c)
    actual=aggregation_rows(c,data,'Asia/Dubai','en')
    assert [row['aggregation.number'] for row in actual]==['R-1','R-2','R-10']
    assert [row['aggregation.serial_number'] for row in actual]==[1,2,3]


def test_icu_run_limit_does_not_add_a_serial_or_padding_validation_cap(client,c,aggregation):
    start='9'*300
    generator(c,primary_field='title',pattern='X{SERIAL}',start=start,padding_width=350,max_code_length=400)
    c.commit()
    row=ok(client.post('/api/v1/records',json={'aggregation_id':aggregation['id'],'record_number':'LONG-SERIAL'}),201)
    assert row['title']=='X'+start.zfill(350)
    assert c.execute('SELECT last_serial::text AS value FROM code_generator_counters').fetchone()['value']==start
