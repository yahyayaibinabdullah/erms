"""All/untyped/selected-type applicability across the real SQL and API boundaries."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4
import json
import os

import psycopg
from psycopg.rows import dict_row
import pytest

from .test_code_generator_database import actor, c, generator, resource_type
from .test_code_generator_routes import PATH, configuration
from .test_code_generator_creation_baseline import stage_document
from .test_aggregation_file_drop import drop
from .test_global_privilege_enforcement import _account, _bearer


def typed(c,kind='record'):
    return c.execute('INSERT INTO resource_types(kind,name) VALUES(%s,%s) RETURNING id',
                     (kind,'Applicability '+uuid4().hex)).fetchone()['id']


@pytest.mark.parametrize('left,right,reject',[
    ('all','untyped',True),('untyped','all',True),('untyped','untyped',True),
    ('untyped','type',False),('type','untyped',False),('type','type',True),
])
def test_database_population_overlap_and_enabling(c,left,right,reject):
    tid=typed(c)
    args=lambda mode:dict(applies_to=mode,type_id=tid if mode=='type' else None)
    generator(c,**args(left))
    if reject:
        with pytest.raises((psycopg.errors.ExclusionViolation,psycopg.errors.UniqueViolation)),c.transaction():
            generator(c,**args(right))
        disabled=generator(c,enabled=False,**args(right));actor(c,reason='Enable applicability')
        with pytest.raises((psycopg.errors.ExclusionViolation,psycopg.errors.UniqueViolation)),c.transaction():
            c.execute('UPDATE code_generators SET enabled=true WHERE id=%s',(disabled['id'],))
    else:
        generator(c,**args(right))
        assert c.execute('SELECT count(*) AS n FROM code_generators WHERE enabled').fetchone()['n']==2


@pytest.mark.parametrize('isolation',['READ COMMITTED','REPEATABLE READ'])
@pytest.mark.parametrize('left,right,winners',[('all','untyped',1),('untyped','untyped',1),('untyped','type',2)])
def test_simultaneous_configuration_saves_enforce_disjoint_populations(c,isolation,left,right,winners):
    tid=typed(c);c.commit();ready=Barrier(2)
    def save(mode):
        try:
            with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as connection:
                connection.execute('SET TRANSACTION ISOLATION LEVEL '+isolation)
                actor(connection)
                connection.execute('SELECT count(*) FROM code_generators').fetchone()
                ready.wait(timeout=10)
                generator(connection,applies_to=mode,type_id=tid if mode=='type' else None)
            return True
        except (psycopg.errors.ExclusionViolation,psycopg.errors.UniqueViolation,psycopg.errors.SerializationFailure):
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(save,(left,right)))==winners


@pytest.mark.parametrize('mode,with_type,allowed',[
    ('all',False,True),('untyped',False,True),('type',True,True),
    ('all',True,False),('untyped',True,False),('type',False,False),
    ('other',False,False), (None,False,False),
])
def test_api_validates_explicit_applicability_shapes(client,c,mode,with_type,allowed):
    tid=typed(c) if with_type else None;c.commit()
    response=client.post(PATH,json=configuration(applies_to=mode,type_id=tid))
    assert response.status_code==(201 if allowed else 422),response.text
    if allowed:
        assert response.json()['applies_to']==mode
        assert response.json()['target_snapshot']['applies_to']==mode


def test_api_coexistence_list_audit_retarget_reason_and_legacy_bodies(client,c):
    tid=typed(c);c.commit()
    u=client.post(PATH,json=configuration(applies_to='untyped')).json()
    selected=client.post(PATH,json=configuration(type_id=tid))
    assert selected.status_code==201,selected.text
    assert selected.json()['applies_to']=='type'  # Legacy type-ID request.
    listed=client.get(PATH).json()['items']
    assert {row['applies_to'] for row in listed}=={'untyped','type'}
    response=client.post(PATH,json=configuration(applies_to='all'))
    assert response.status_code==409,response.text
    body=configuration(applies_to='all')
    headers={'If-Match':str(u['version'])}
    assert client.put(f"{PATH}/{u['id']}",json=body,headers=headers).status_code==422
    headers['X-Change-Reason']='Apply to all future items'
    assert client.put(f"{PATH}/{u['id']}",json=body,headers=headers).status_code==409
    assert client.get(f"{PATH}/{u['id']}").json()['applies_to']=='untyped'
    # Make the disjoint selected-type definition inactive, then retarget.
    selected=selected.json()
    assert client.put(f"{PATH}/{selected['id']}",json=configuration(type_id=tid,enabled=False),
        headers={'If-Match':str(selected['version']),'X-Change-Reason':'Retire selected-type series'}).status_code==200
    result=client.put(f"{PATH}/{u['id']}",json=body,headers=headers)
    assert result.status_code==200,result.text
    event=c.execute("SELECT before_state,after_state,reason,changed_fields FROM event_history WHERE entity_type='code_generator' AND entity_id=%s ORDER BY id DESC LIMIT 1",(u['id'],)).fetchone()
    assert event['before_state']['applies_to']=='untyped' and event['after_state']['applies_to']=='all'
    assert 'applies_to' in event['changed_fields'] and event['reason']==headers['X-Change-Reason']
    assert client.delete(f"{PATH}/{u['id']}/binding",headers={'If-Match':str(result.json()['version']),
        'X-Change-Reason':'Detach target'}).json()['applies_to']=='all'


@pytest.mark.parametrize('path',['record','root','child','draft','drop'])
def test_untyped_and_selected_type_creation_use_only_their_own_generator(client,c,aggregation,path):
    kind='aggregation' if path in {'root','child'} else 'record'
    tid=typed(c,kind);other=typed(c,kind)
    field=kind+'_number'
    untyped=generator(c,kind=kind,primary_field=field,applies_to='untyped',pattern='U{SERIAL}')
    selected=generator(c,kind=kind,primary_field=field,applies_to='type',type_id=tid,pattern='T{SERIAL}')
    c.commit()
    for identity,prefix in [(None,'U'),(tid,'T')]:
        body={'title':'Applicability creation',**({'type_id':identity} if identity else {})}
        if path=='root':body['classification_id']=aggregation['classification_id']
        elif path=='child':body['parent_aggregation_id']=aggregation['id']
        else:body['aggregation_id']=aggregation['id']
        if path=='draft':
            draft=client.post('/api/v1/record-drafts',json={key:value for key,value in body.items() if key!='type_id'})
            assert draft.status_code==201,draft.text
            assert c.execute('SELECT count(*) AS n FROM code_generator_counters').fetchone()['n']==(0 if identity is None else 1)
            stage_document(client,draft.json()['id'],b'Applicability evidence')
            response=client.post(f"/api/v1/record-drafts/{draft.json()['id']}/commit",json={'type_id':identity} if identity else {})
        elif path=='drop':
            response=drop(client,aggregation,separate=False,data={'type_id':str(identity)} if identity else {})
            assert response.status_code==201,response.text
            assert c.execute('SELECT record_number FROM records ORDER BY id DESC LIMIT 1').fetchone()['record_number']==prefix+'10'
            continue
        else:response=client.post('/api/v1/'+kind+'s',json=body)
        assert response.status_code==201,response.text
        assert response.json()[field]==prefix+'10'
    counters=c.execute('SELECT generator_id,last_serial FROM code_generator_counters ORDER BY generator_id').fetchall()
    assert [(row['generator_id'],row['last_serial']) for row in counters]==[(untyped['id'],10),(selected['id'],10)]
    # No applicable generator for a different type: do not consume U or T.
    if path in {'record','root','child'}:
        body['type_id']=other
        response=client.post('/api/v1/'+kind+'s',json=body)
        assert response.status_code==422,response.text
        assert [v['last_serial'] for v in c.execute('SELECT last_serial FROM code_generator_counters ORDER BY generator_id')]==[10,10]


@pytest.mark.parametrize('kind',['record','aggregation'])
def test_hints_and_recommendations_respect_all_three_populations(client,c,aggregation,kind):
    tid=typed(c,kind);other=typed(c,kind)
    u=generator(c,kind=kind,primary_field=kind+'_number',applies_to='untyped',pattern='U{SERIAL}')
    t=generator(c,kind=kind,primary_field=kind+'_number',applies_to='type',type_id=tid,pattern='T{SERIAL}')
    c.commit()
    for identity,expected,prefix in [(None,u,'U'),(tid,t,'T'),(other,None,None)]:
        params={'kind':kind,'parent_aggregation_id':aggregation['id'],**({'type_id':identity} if identity else {})}
        hints=client.get('/api/v1/code-generation/bindings',params=params)
        assert hints.status_code==200,hints.text
        assert [v['generator_id'] for v in hints.json()['items']]==([expected['id']] if expected else [])
        suggestion=client.get('/api/v1/number-suggestions/'+kind+'s',params={k:v for k,v in params.items() if k!='kind'})
        assert suggestion.status_code==200,suggestion.text
        if expected:
            assert suggestion.json()['suggested_number']==prefix+'10'
            assert suggestion.json()['generation_intent']['generator_id']==expected['id']
        else:assert suggestion.json().get('generation_intent',{}).get('source')!='generator'
    assert c.execute('SELECT count(*) AS n FROM code_generator_counters').fetchone()['n']==0


def test_new_applicability_does_not_bypass_administration_or_parent_access(client,c,aggregation):
    generator(c,applies_to='untyped');c.commit()
    token,_,_=_account(client,privileges=('record.create',))
    assert client.post(PATH,json=configuration(applies_to='untyped'),headers=_bearer(token)).status_code==403
    assert client.get('/api/v1/code-generation/bindings',params={'kind':'record','parent_aggregation_id':aggregation['id']},headers=_bearer(token)).status_code==404


@pytest.mark.skipif(not os.environ.get('ERMS_TEST_DEFERRED_MIGRATIONS'),reason='requires populated 126-to-127 upgrade runner')
def test_populated_applicability_upgrade_is_atomic_and_preserves_semantics(client):
    migrations=[Path(value) for value in os.environ['ERMS_TEST_DEFERRED_MIGRATIONS'].split(os.pathsep)]
    assert [p.name for p in migrations]==['126_custom_code_generators.sql','127_code_generator_applicability.sql']
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row,autocommit=True) as connection:
        connection.execute(migrations[0].read_text(),prepare=False)
        connection.execute("SELECT set_config('app.user_id','1',false),set_config('app.event_source','api',false),set_config('app.actor_type','user',false)")
        tid=connection.execute("INSERT INTO resource_types(kind,name) VALUES('record','Legacy contract') RETURNING id").fetchone()['id']
        for primary,type_id,pattern in [('record_number',None,'R{SERIAL}'),('description',tid,'D{SERIAL}')]:
            connection.execute("INSERT INTO code_generators(name,kind,primary_field,type_id,pattern,start,increment,max_code_length) VALUES(%s,'record',%s,%s,%s,10,10,64)",(primary,primary,type_id,pattern))
        root=client.post('/api/v1/aggregations',json={'aggregation_number':'OLD-ROOT','title':'Upgrade parent','classification_id':1}).json()
        for fields in [{},{'type_id':tid,'record_number':'OLD-TYPED'}]:
            created=client.post('/api/v1/records',json={'aggregation_id':root['id'],'title':'Before upgrade',**fields})
            assert created.status_code==201,created.text
        frozen={table:connection.execute(f'SELECT to_jsonb(t) AS row FROM {table} t ORDER BY id').fetchall() for table in ['code_generators','records','event_history']}
        counters=connection.execute('SELECT to_jsonb(t) AS row FROM code_generator_counters t ORDER BY generator_id').fetchall()
        connection.execute("CREATE FUNCTION pg_temp.reject_applicability_upgrade() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RAISE EXCEPTION 'Upgrade rollback probe'; END$$")
        connection.execute("CREATE TRIGGER reject_applicability_upgrade BEFORE INSERT ON schema_migrations FOR EACH ROW WHEN (NEW.version='127_code_generator_applicability') EXECUTE FUNCTION pg_temp.reject_applicability_upgrade()")
        with pytest.raises(psycopg.errors.RaiseException):connection.execute(migrations[1].read_text(),prepare=False)
        connection.execute('ROLLBACK')
        assert not connection.execute("SELECT 1 FROM information_schema.columns WHERE table_name='code_generators' AND column_name='applies_to'").fetchone()
        assert all(row['tgenabled']=='O' for row in connection.execute("SELECT tgenabled FROM pg_trigger WHERE tgname IN ('code_generators_guard','code_generators_history')"))
        connection.execute('DROP TRIGGER reject_applicability_upgrade ON schema_migrations')
        connection.execute(migrations[1].read_text(),prepare=False)
        updated=connection.execute('SELECT to_jsonb(t) AS row FROM code_generators t ORDER BY id').fetchall()
        for before,after in zip(frozen['code_generators'],updated,strict=True):
            value=after['row'].copy();mode=value.pop('applies_to')
            assert mode==('type' if before['row']['type_id'] else 'all')
            assert value==before['row']
        for table in ['records','event_history']:
            assert connection.execute(f'SELECT to_jsonb(t) AS row FROM {table} t ORDER BY id').fetchall()==frozen[table]
        assert connection.execute('SELECT to_jsonb(t) AS row FROM code_generator_counters t ORDER BY generator_id').fetchall()==counters
        response=client.post('/api/v1/records',json={'aggregation_id':root['id'],'title':'After upgrade'})
        assert response.status_code==201,response.text
        assert response.json()['record_number']=='R20'


@pytest.mark.parametrize('mode,with_type', [('all',True),('untyped',True),('type',False),('bad',False),(None,False)])
def test_direct_database_rejects_invalid_applicability_shapes(c,mode,with_type):
    tid=typed(c) if with_type else None
    with pytest.raises(psycopg.IntegrityError),c.transaction():
        generator(c,applies_to=mode,type_id=tid)


@pytest.mark.parametrize('mode,allowed',[('all',False),('untyped',False),('type',True)])
def test_type_specific_fields_require_their_selected_type(client,c,mode,allowed):
    from .test_code_generation_creation import field
    tid=typed(c);fid=field(c,tid,'Contract number',1);c.commit()
    response=client.post(PATH,json=configuration(primary_field=None,field_id=fid,type_id=tid,
        applies_to=mode,max_code_length=64))
    assert response.status_code==(201 if allowed else 422),response.text


def test_assigning_a_type_does_not_regenerate_an_existing_untyped_code(client,c,aggregation):
    tid=typed(c)
    generator(c,applies_to='untyped',pattern='U{SERIAL}')
    generator(c,applies_to='type',type_id=tid,pattern='T{SERIAL}');c.commit()
    first=client.post('/api/v1/records',json={'aggregation_id':aggregation['id'],'title':'Originally untyped'})
    assert first.status_code==201,first.text
    row=first.json()
    result=client.patch(f"/api/v1/records/{row['id']}",json={'type_id':tid,'confirm_type_change':True},
                        headers={'If-Match':str(row['version'])})
    assert result.status_code==200,result.text
    assert result.json()['record_number']=='U10'
    assert c.execute('SELECT count(*) AS n FROM code_generator_counters').fetchone()['n']==1
    second=client.post('/api/v1/records',json={'aggregation_id':aggregation['id'],'title':'New typed record','type_id':tid})
    assert second.status_code==201,second.text
    assert second.json()['record_number']=='T10'
