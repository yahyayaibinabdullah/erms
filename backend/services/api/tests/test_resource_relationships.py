"""Phase 1 relationship regressions; invoked only by the disposable DB runner."""
import os

import psycopg
import pytest
from psycopg.rows import dict_row


def types(client, kind='record', code='related_to'):
    return next(item for item in client.get(f'/api/v1/relationships/types/{kind}', params={'limit': 100}).json()['items']
                if item['code'] == code)


def another_record(client, aggregation, number='REC-002'):
    response = client.post('/api/v1/records', json={'aggregation_id': aggregation['id'], 'record_number': number, 'title': number})
    assert response.status_code == 201, response.text
    return response.json()


def test_symmetric_duplicate_and_atomic_reverse_removal(client, aggregation, record):
    second = another_record(client, aggregation)
    type_id = types(client)['id']
    base = f"/api/v1/relationships/record/{record['id']}"
    result = client.post(base, json={'target_id': second['id'], 'relationship_type_id': type_id})
    assert result.status_code == 201, result.text
    assert client.post(f"/api/v1/relationships/record/{second['id']}", json={'target_id': record['id'], 'relationship_type_id': type_id}).status_code == 409
    assert client.post(base, json={'target_id': record['id'], 'relationship_type_id': type_id}).status_code == 422
    assert client.delete(f"/api/v1/relationships/record/{second['id']}/{result.json()['id']}").status_code == 204
    assert client.get(base).json()['total'] == 0
    assert client.get(f"/api/v1/relationships/record/{second['id']}").json()['total'] == 0


def test_direction_types_scope_and_no_transitive_link(client, aggregation, record):
    b = another_record(client, aggregation)
    c = another_record(client, aggregation, 'REC-003')
    type_id = types(client, code='supersedes')['id']
    for source, target in [(record, b), (b, c)]:
        result = client.post(f"/api/v1/relationships/record/{source['id']}", json={'target_id': target['id'], 'relationship_type_id': type_id})
        assert result.status_code == 201, result.text
    items = client.get(f"/api/v1/relationships/record/{b['id']}").json()['items']
    assert {item['label'] for item in items} == {'supersedes', 'superseded by'}
    assert client.get(f"/api/v1/relationships/record/{record['id']}").json()['total'] == 1
    arabic = client.get(f"/api/v1/relationships/record/{b['id']}", params={'language_tag':'ar'}).json()['items']
    assert {item['label'] for item in arabic} == {'يحل محل', 'حل محله'}
    # Distinct types between the same pair are legitimate.
    assert client.post(f"/api/v1/relationships/record/{record['id']}", json={'target_id': b['id'], 'relationship_type_id': types(client)['id']}).status_code == 201
    assert client.post(f"/api/v1/relationships/record/{record['id']}", json={'target_id': c['id'], 'relationship_type_id': types(client, 'aggregation')['id']}).status_code == 422
    assert client.post(f"/api/v1/relationships/other/{record['id']}", json={'target_id': b['id'], 'relationship_type_id':type_id}).status_code == 422


def test_catalogue_deactivation_versions_and_protected_in_use_type(client, aggregation, record):
    payload = {'code':'test_attached', 'forward_name':'attached to', 'reverse_name':'has attachment',
               'arabic_forward_name':'مرفق بـ', 'arabic_reverse_name':'له مرفق'}
    created = client.post('/api/v1/relationships/types/record', json=payload)
    assert created.status_code == 201, created.text
    t = created.json()
    b = another_record(client, aggregation)
    base = f"/api/v1/relationships/record/{record['id']}"
    link = client.post(base, json={'target_id':b['id'], 'relationship_type_id':t['id']})
    assert link.status_code == 201
    update = {key:value for key,value in payload.items() if key != 'code'} | {'is_active':False}
    url = f"/api/v1/relationships/types/record/{t['id']}"
    changed = client.patch(url, json=update, headers={'If-Match':str(t['version'])})
    assert changed.status_code == 200, changed.text
    assert client.patch(url, json=update, headers={'If-Match':str(t['version'])}).status_code == 409
    c = another_record(client, aggregation, 'REC-003')
    assert client.post(base, json={'target_id':c['id'],'relationship_type_id':t['id']}).status_code == 422
    assert client.get(base).json()['items'][0]['label'] == 'attached to'
    blocked = client.delete(url, headers={'If-Match':str(changed.json()['version'])})
    assert blocked.status_code == 409
    assert blocked.json()['detail']['message_key'] == 'relationships.error.type_in_use'
    assert client.delete(f"{base}/{link.json()['id']}").status_code == 204
    assert client.delete(url, headers={'If-Match':str(changed.json()['version'])}).status_code == 204


def test_aggregation_links_pagination_search_and_audit(client, aggregation):
    b = client.post('/api/v1/aggregations', json={'aggregation_number':'AGG-002', 'title':'Other', 'classification_id':1}).json()
    t = types(client, 'aggregation')
    response = client.post(f"/api/v1/relationships/aggregation/{aggregation['id']}", json={'target_id':b['id'],'relationship_type_id':t['id']})
    assert response.status_code == 201, response.text
    listing = client.get(f"/api/v1/relationships/aggregation/{b['id']}",params={'limit':1,'offset':1}).json()
    assert listing['total'] == 1 and listing['items'] == []
    targets = f"/api/v1/relationships/aggregation/{aggregation['id']}/targets"
    assert [row['id'] for row in client.get(targets,params={'selected_id':b['id'], 'q':'not matching'}).json()['items']] == [b['id']]
    assert client.get(targets, params={'q':'%'}).json()['items'] == []
    assert client.get(targets, params={'limit':51}).status_code == 422
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as c:
        events=c.execute("SELECT * FROM event_history WHERE entity_type='aggregation_relationship'").fetchall()
        assert len(events)==1 and events[0]['actor_user_id'] and events[0]['source']=='api'
        assert events[0]['after_state']['target_id']==b['id']
        assert c.execute('SELECT parent_aggregation_id FROM aggregations WHERE id=%s',(b['id'],)).fetchone()['parent_aggregation_id'] is None


def limited_profile(c, codes):
    profile=c.execute("INSERT INTO profiles(code,name) VALUES ('REL_TEST','Relationship test') RETURNING id").fetchone()[0]
    c.execute('INSERT INTO profile_privileges(profile_id,privilege_id) SELECT %s,id FROM privileges WHERE code=ANY(%s)',(profile,codes))
    c.execute('UPDATE roles SET profile_id=%s,is_information_governance=false WHERE code=\'system-administrator\'',(profile,))
    return profile


def test_view_only_acl_link_authority_and_redacted_endpoint(client, aggregation, record):
    b = another_record(client, aggregation)
    t = types(client)['id']
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        profile=limited_profile(c,['aggregation.view','record.view','relationships.link','audit.view'])
        c.execute("INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,permission_id) SELECT %s,'everyone',id FROM permissions WHERE code='aggregation.view' ON CONFLICT DO NOTHING", (aggregation['id'],))
        c.execute('UPDATE records SET inherit_acl_from_parent=false WHERE id=ANY(%s)',([record['id'],b['id']],))
        c.execute("INSERT INTO record_acl_grants(record_id,principal_type,permission_id) SELECT r.id,'everyone',p.id FROM records r CROSS JOIN permissions p WHERE p.code='record.view' ON CONFLICT DO NOTHING")
    base=f"/api/v1/relationships/record/{record['id']}"
    link=client.post(base,json={'target_id':b['id'],'relationship_type_id':t})
    assert link.status_code==201, link.text  # No metadata modification privilege or ACL.
    assert client.post('/api/v1/relationships/types/record',json={'code':'forbidden','forward_name':'x','reverse_name':'y','arabic_forward_name':'س','arabic_reverse_name':'ص'}).status_code==403
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute("DELETE FROM record_acl_grants WHERE record_id=%s",(b['id'],))
    related=client.get(base).json()['items'][0]['related']
    assert related=={'id':None,'number':None,'title':None,'redacted':True}
    assert client.delete(f"{base}/{link.json()['id']}").status_code==404
    assert client.get(base+'/targets',params={'selected_id':b['id']}).json()['items']==[]
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute("SELECT set_config('app.user_id','1',true)")
        assert c.execute("SELECT metadata,before_state,after_state FROM authorized_event_history WHERE entity_type='record_relationship'").fetchone()==({'redacted':True,'reason':'resource_access_denied'},None,None)
        c.execute("DELETE FROM profile_privileges WHERE profile_id=%s AND privilege_id=(SELECT id FROM privileges WHERE code='relationships.link')",(profile,))
    assert client.post(base,json={'target_id':b['id'],'relationship_type_id':t}).status_code==403


def test_direct_sql_link_checks_and_seed_grants(client, aggregation, record):
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        assert c.execute("SELECT count(*) FROM profile_privileges pp JOIN profiles p ON p.id=pp.profile_id JOIN privileges v ON v.id=pp.privilege_id WHERE p.code='SYS_ADMIN' AND v.code LIKE 'relationships.%'").fetchone()[0]==0
        assert c.execute("SELECT count(*) FROM relationship_types WHERE translations->'ar'->>'forward_name' IS NOT NULL").fetchone()[0]>=11
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with c.transaction():
                c.execute('INSERT INTO record_relationships(relationship_type_id,source_id,target_id) VALUES (%s,%s,%s)',(types(client)['id'],record['id'],record['id']))


def test_resource_deletion_cascades_links_and_retains_audit_without_link_privilege(client, aggregation, record):
    b = another_record(client, aggregation)
    result = client.post(f"/api/v1/relationships/record/{record['id']}", json={'target_id':b['id'], 'relationship_type_id':types(client)['id']})
    assert result.status_code == 201
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        profile = c.execute("INSERT INTO profiles(code,name) VALUES ('REL_DELETE','Delete resources') RETURNING id").fetchone()[0]
        c.execute("INSERT INTO profile_privileges(profile_id,privilege_id) SELECT %s,id FROM privileges WHERE code IN ('aggregation.view','record.view','record.delete')", (profile,))
        c.execute("UPDATE roles SET profile_id=%s WHERE code='system-administrator'", (profile,))
    response = client.delete(f"/api/v1/records/{b['id']}", headers={'If-Match':str(b['version'])})
    assert response.status_code == 204, response.text
    assert client.get(f"/api/v1/relationships/record/{record['id']}").json()['total'] == 0
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        events=c.execute("SELECT operation,actor_user_id,before_state FROM event_history WHERE entity_type='record_relationship' ORDER BY id").fetchall()
        assert [row[0] for row in events]==['CREATE','DELETE']
        assert events[-1][1] and events[-1][2]['target_id']==b['id']


def test_concurrent_reverse_symmetric_writes_create_one_link(client, aggregation, record):
    from concurrent.futures import ThreadPoolExecutor
    b = another_record(client, aggregation)
    type_id = types(client)['id']

    def insert(source, target):
        try:
            with psycopg.connect(os.environ['DATABASE_URL']) as c:
                c.execute("SET LOCAL lock_timeout='10s'")
                c.execute("SELECT set_config('app.user_id','1',true),set_config('app.actor_type','user',true)")
                c.execute('INSERT INTO record_relationships(relationship_type_id,source_id,target_id) VALUES (%s,%s,%s)', (type_id, source, target))
            return 'created'
        except psycopg.errors.UniqueViolation:
            return 'duplicate'

    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(lambda pair: insert(*pair), [(record['id'], b['id']), (b['id'],record['id'])]))
    assert sorted(results)==['created','duplicate']
    assert client.get(f"/api/v1/relationships/record/{record['id']}").json()['total']==1
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute("SELECT set_config('app.user_id','1',true)")
        with pytest.raises(psycopg.errors.CheckViolation):
            with c.transaction():
                c.execute('UPDATE record_relationships SET target_id=source_id')


def test_reverse_direction_recreates_same_link_and_selected_type_read(client, aggregation, record):
    b = another_record(client, aggregation)
    t = types(client, code='supersedes')
    base=f"/api/v1/relationships/record/{record['id']}"
    result=client.post(base,json={'target_id':b['id'],'relationship_type_id':t['id']})
    assert result.status_code==201
    assert client.post(f"/api/v1/relationships/record/{b['id']}",json={'target_id':record['id'],'relationship_type_id':t['id'],'direction':'reverse'}).status_code==409
    assert client.get(f"/api/v1/relationships/types/record/{t['id']}", params={'language_tag':'ar'}).json()['forward_label']=='يحل محل'
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute("SELECT set_config('app.user_id','1',true)")
        with pytest.raises(psycopg.errors.CheckViolation):
            with c.transaction():
                c.execute('UPDATE relationship_types SET is_symmetric=true WHERE id=%s',(t['id'],))


def test_catalogue_search_is_bounded_and_language_aware(client):
    response=client.get('/api/v1/relationships/types/record',params={'q':'له نسخة','language_tag':'ar','limit':1})
    assert response.status_code==200, response.text
    assert response.json()['total']==1
    assert response.json()['items'][0]['code']=='copy_of'
    assert client.get('/api/v1/relationships/types/record',params={'q':'%'}).json()['total']==0
    assert client.get('/api/v1/relationships/types/record',params={'limit':101}).status_code==422


def test_separate_catalogue_seed_is_idempotent_and_preserves_existing_rows(client):
    from pathlib import Path
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as c:
        before=c.execute('SELECT * FROM relationship_types ORDER BY id').fetchall()
        c.execute(Path('database/seeds/relationship-types.sql').read_text(), prepare=False)
        after=c.execute('SELECT * FROM relationship_types ORDER BY id').fetchall()
        assert before==after
        assert c.execute("SELECT count(*) AS n FROM event_history WHERE entity_type='relationship_type' AND source='seeding'").fetchone()['n']==0


def test_catalogue_ui_sorting_is_server_side(client):
    url='/api/v1/relationships/types/record'
    ascending=client.get(url,params={'active_only':False,'limit':100}).json()['items']
    descending=client.get(url,params={'active_only':False,'limit':2,'descending':True}).json()
    assert descending['total']==len(ascending)
    assert [row['id'] for row in descending['items']]==[row['id'] for row in reversed(ascending)][:2]
    page=client.get(url,params={'limit':2,'offset':2,'descending':True}).json()
    assert [row['id'] for row in page['items']]==[row['id'] for row in reversed(ascending)][2:4]


def test_language_keyed_translations_preserve_other_languages_and_fallback(client, aggregation, record):
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute("SELECT set_config('app.change_reason','Disposable multilingual relationship test',true)")
        c.execute("INSERT INTO supported_languages(language_tag,english_name,native_name,direction) VALUES ('fr','French','Français','ltr') ON CONFLICT DO NOTHING")
    payload = {'code':'multilingual','forward_name':'references','reverse_name':'referenced by',
               'translations': {'ar': {'forward_name':'يشير إلى','reverse_name':'أشار إليه'},
                                'fr': {'forward_name':'fait référence à','reverse_name':'référencé par'}}}
    response = client.post('/api/v1/relationships/types/record',json=payload)
    assert response.status_code == 201, response.text
    row = response.json()
    url = f"/api/v1/relationships/types/record/{row['id']}"
    assert client.get(url,params={'language_tag':'fr-CA'}).json()['forward_label']=='fait référence à'
    assert client.get('/api/v1/relationships/types/record',params={'q':'référencé','language_tag':'fr'}).json()['total']==1
    other = another_record(client, aggregation)
    assert client.post(f"/api/v1/relationships/record/{record['id']}",json={'relationship_type_id':row['id'],'target_id':other['id']}).status_code==201
    assert client.get(f"/api/v1/relationships/record/{other['id']}",params={'language_tag':'fr'}).json()['items'][0]['label']=='référencé par'
    update = {'forward_name':row['forward_name'],'reverse_name':row['reverse_name'],'is_active':True,
              'translations':{'fr':{'forward_name':'renvoie à','reverse_name':'mentionné par'}}}
    response = client.patch(url,json=update,headers={'If-Match':str(row['version'])})
    assert response.status_code==200,response.text
    row=response.json()
    assert row['translations']['ar']==payload['translations']['ar']
    update['translations']={'fr':None}
    response=client.patch(url,json=update,headers={'If-Match':str(row['version'])})
    assert response.status_code==200,response.text
    row=response.json()
    assert 'fr' not in row['translations']
    assert client.get(url,params={'language_tag':'fr'}).json()['forward_label']=='references'
    update['translations']={'ar':None}
    assert client.patch(url,json=update,headers={'If-Match':str(row['version'])}).status_code==422
    update['translations']={'zz':{'forward_name':'x','reverse_name':'y'}}
    assert client.patch(url,json=update,headers={'If-Match':str(row['version'])}).status_code==422
    update['translations']={'fr':{'forward_name':'  ','reverse_name':'y'}}
    assert client.patch(url,json=update,headers={'If-Match':str(row['version'])}).status_code==422


def test_english_translation_overrides_canonical_name_and_can_be_removed(client):
    payload={'code':'english_override','forward_name':'canonical name','reverse_name':'canonical reverse',
             'translations':{'ar':{'forward_name':'اسم','reverse_name':'اسم عكسي'},
                             'en':{'forward_name':'English override','reverse_name':'English reverse override'}}}
    response=client.post('/api/v1/relationships/types/record',json=payload)
    assert response.status_code==201,response.text
    row=response.json();url=f"/api/v1/relationships/types/record/{row['id']}"
    assert client.get(url,params={'language_tag':'en'}).json()['forward_label']=='English override'
    assert client.get(url,params={'language_tag':'en-US'}).json()['reverse_label']=='English reverse override'
    update={'forward_name':row['forward_name'],'reverse_name':row['reverse_name'],'is_active':True,'translations':{'en':None}}
    response=client.patch(url,json=update,headers={'If-Match':str(row['version'])})
    assert response.status_code==200,response.text
    assert client.get(url,params={'language_tag':'en'}).json()['forward_label']=='canonical name'


def test_target_search_waits_for_two_characters_and_includes_description(client, aggregation, record):
    other=client.post('/api/v1/records',json={'aggregation_id':aggregation['id'],'record_number':'FIND-002','title':'Distinct title','description':'descriptionneedle'}).json()
    url=f"/api/v1/relationships/record/{record['id']}/targets"
    for q in ('',' ','D'):
        assert client.get(url,params={'q':q}).json()['items']==[]
    for q in ('FIND','Distinct','descriptionneedle'):
        assert [r['id'] for r in client.get(url,params={'q':q}).json()['items']]==[other['id']]
    assert client.get(url,params={'selected_id':other['id']}).json()['items'][0]['id']==other['id']
    target=client.post('/api/v1/aggregations',json={'aggregation_number':'FIND-003','title':'Other','description':'aggregationdescriptionneedle','classification_id':1}).json()
    url=f"/api/v1/relationships/aggregation/{aggregation['id']}/targets"
    assert client.get(url,params={'q':''}).json()['items']==[]
    assert [r['id'] for r in client.get(url,params={'q':'aggregationdescriptionneedle'}).json()['items']]==[target['id']]
