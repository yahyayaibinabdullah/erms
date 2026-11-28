"""AFD-1–5: the real multipart route, transactional storage and scoped activity."""
import os

import psycopg
import pytest
from fastapi import HTTPException
from psycopg.rows import dict_row

from backend.services.api import main
from backend.services.api.tests.test_global_privilege_enforcement import _account, _bearer


@pytest.mark.parametrize('resource,parent_field,number_field,date_field', [
    ('records', 'aggregation_id', 'record_number', 'date_originated'),
    ('aggregations', 'parent_aggregation_id', 'aggregation_number', 'date_opened'),
])
def test_contents_historical_order_and_id_ties_across_pages(client, aggregation, resource, parent_field, number_field, date_field):
    identifiers = []
    for suffix in (1, 10, 2, 11):
        response = client.post(f'/api/v1/{resource}', json={
            parent_field: aggregation['id'], number_field: f'3110/6/2026.{suffix}',
            'title': 'Chronological child',
            date_field: '2001-01-01T00:00:00Z' if suffix == 2 else '2001-01-02T00:00:00Z',
            'medium': 'digital' if resource == 'records' else aggregation['medium'],
        })
        assert response.status_code == 201, response.text
        identifiers.append(response.json()['id'])
    # A later-captured historical item precedes earlier captures. Equal
    # historical dates cross a page boundary and use ID, not creation time.
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        from psycopg import sql
        connection.execute(sql.SQL("UPDATE {} SET date_created='2024-01-01' WHERE id=%s").format(
            sql.Identifier(resource)), (identifiers[3],))
    expected = [identifiers[2], identifiers[0], identifiers[1], identifiers[3]]
    for filtered in (False, True):
        conditions = [{'field': parent_field, 'operator': 'eq', 'value': aggregation['id']}]
        if filtered:
            conditions.append({'field': 'title', 'operator': 'contains_ci', 'value': 'Chronological'})
        received = []
        for offset in (0, 2):
            response = client.post(f'/api/v1/{resource}/search', json={
                'where': {'and': conditions}, 'limit': 2, 'offset': offset,
                'sort': [{'field': date_field, 'direction': 'asc'}, {'field': 'id', 'direction': 'asc'}],
            })
            assert response.status_code == 200, response.text
            assert response.json()['total'] == 4
            received.extend(item['id'] for item in response.json()['items'])
        assert received == expected


def drop(client, aggregation, *, separate=True, files=None, **kwargs):
    return client.post(f"/api/v1/aggregations/{aggregation['id']}/records/file-drop",
                       data={"separate_records": str(separate).lower(), **({"title": "first.txt"} if not separate else {}), **kwargs.pop('data', {})},
                       files=files or [("files", ("first.txt", b"first", "text/plain")),
                                       ("files", ("second.txt", b"second", "text/plain"))], **kwargs)


@pytest.mark.parametrize('separate,count', [(True, 2), (False, 1)])
def test_drop_creates_ordered_digital_records_and_components(client, aggregation, separate, count):
    result = drop(client, aggregation, separate=separate)
    assert result.status_code == 201, result.text
    assert result.json() == {'count': count}
    with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as c:
        records = c.execute('SELECT * FROM records ORDER BY id').fetchall()
        components = c.execute('SELECT * FROM digital_components ORDER BY record_id,component_order').fetchall()
        assert len(records) == count
        assert [r['title'] for r in records] == (['first.txt', 'second.txt'] if separate else ['first.txt'])
        assert [r['record_number'] for r in records] == [f"{aggregation['aggregation_number']}.{i}" for i in range(1, count+1)]
        assert all(r['medium'] == 'digital' and r['owning_org_unit_id'] == aggregation['owning_org_unit_id'] for r in records)
        assert [r['file_name'] for r in components] == ['first.txt', 'second.txt']
        assert [r['component_order'] for r in components] == ([1, 1] if separate else [1, 2])
        assert c.execute('SELECT count(*) AS n FROM record_relationships').fetchone()['n'] == 0
    for component, expected in zip(components, [b'first', b'second']):
        response = client.get(f"/api/v1/digital-components/{component['id']}/content")
        assert response.status_code == 200, response.text
        assert response.content == expected
    activity = client.get('/api/v1/auth/me/recent-activity', params={'entity_type': 'record', 'aggregation_id': aggregation['id']})
    assert activity.status_code == 200, activity.text
    assert {r['entity_id'] for r in activity.json() if r['operation'] == 'CREATE'} == {r['id'] for r in records}
    assert all('created_by' in r for r in activity.json())


@pytest.mark.parametrize('separate', [True, False])
def test_drop_rolls_back_first_file_when_second_storage_fails(client, aggregation, monkeypatch, separate):
    original = main._store_uploaded_component
    def failing(connection, record_id, file, *args, **kwargs):
        if (getattr(file,'file_name',None) or getattr(file,'filename',None)) == 'second.txt':
            raise HTTPException(422, detail='Fixture rejects second file')
        return original(connection, record_id, file, *args, **kwargs)
    monkeypatch.setattr(main, '_store_uploaded_component', failing)
    result = drop(client, aggregation, separate=separate)
    assert result.status_code == 422, result.text
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        for table in ('records', 'digital_components', 'digital_component_blobs', 'digital_component_content_sets'):
            assert c.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_physical_aggregation_rejects_files(client, aggregation):
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute("UPDATE aggregations SET medium='physical' WHERE id=%s", (aggregation['id'],))
    result = drop(client, aggregation)
    assert result.status_code == 409, result.text
    assert result.json()['detail']['code'] == 'aggregation_file_drop_physical'


@pytest.mark.parametrize('governance', [False, True])
@pytest.mark.parametrize('separate', [False, True])
def test_drop_denies_unrelated_unit_even_with_governance(client, aggregation, governance, separate):
    token, user, role = _account(client, privileges=('record.create', 'aggregation.view'), suffix='drop-other-unit')
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute('UPDATE roles SET is_information_governance=%s WHERE id=%s', (governance, role))
        c.execute("INSERT INTO aggregation_acl_grants(aggregation_id,permission_id,principal_type) SELECT %s,id,'everyone' FROM permissions WHERE code IN ('aggregation.add_record','aggregation.view')", (aggregation['id'],))
    result = drop(client, aggregation, separate=separate, headers=_bearer(token), data={'creator_acl_role_id': role})
    assert result.status_code == 403, result.text
    assert result.json()['detail']['code'] == 'creator_acl_role_not_eligible'


@pytest.mark.parametrize('separate', [False, True])
def test_drop_requires_scoped_permission(client, aggregation, separate):
    token, _, role = _account(client, privileges=('record.create',), suffix='drop-no-access')
    result = drop(client, aggregation, separate=separate, headers=_bearer(token), data={'creator_acl_role_id': role})
    assert result.status_code in (403, 404), result.text
    client.cookies.clear()
    assert drop(client, aggregation, separate=separate).status_code == 401


def test_single_file_with_one_owning_role_uses_creation_permissions(client, aggregation):
    token, _, role = _account(client, privileges=('record.create','aggregation.view'), suffix='drop-owning-role')
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        c.execute('UPDATE roles SET org_unit_id=%s WHERE id=%s', (aggregation['owning_org_unit_id'],role))
        c.execute("INSERT INTO aggregation_acl_grants(aggregation_id,permission_id,principal_type) SELECT %s,id,'everyone' FROM permissions WHERE code IN ('aggregation.add_record','aggregation.view')", (aggregation['id'],))
    response=drop(client,aggregation,files=[('files',('single.pdf',b'%PDF fixture','application/pdf'))],headers=_bearer(token))
    assert response.status_code==201,response.text
    assert response.json()=={'count':1}
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        row=c.execute('SELECT * FROM records').fetchone()
        assert row['title']=='single.pdf' and row['medium']=='digital'
        assert c.execute('SELECT count(*) AS n FROM record_acl_grants WHERE record_id=%s AND role_id=%s',(row['id'],role)).fetchone()['n']>0


def test_activity_scopes_direct_children_before_cap_and_rechecks_visibility(client, aggregation):
    response=drop(client,aggregation);assert response.status_code==201,response.text
    child=client.post('/api/v1/aggregations',json={'parent_aggregation_id':aggregation['id'],'aggregation_number':'CHILD','title':'Nested'}).json()
    assert drop(client,child).status_code==201
    scope={'entity_type':'record','aggregation_id':aggregation['id'],'limit':1}
    result=client.get('/api/v1/auth/me/recent-activity',params=scope)
    assert result.status_code==200,result.text
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        expected=c.execute('SELECT id FROM records WHERE aggregation_id=%s ORDER BY id DESC LIMIT 1',(aggregation['id'],)).fetchone()['id']
    assert [r['entity_id'] for r in result.json()]==[expected]
    token,_,_=_account(client,privileges=('record.view','aggregation.view'),suffix='activity-denied')
    assert client.get('/api/v1/auth/me/recent-activity',params=scope,headers=_bearer(token)).json()==[]
    assert client.get('/api/v1/auth/me/recent-activity',params={**scope,'entity_type':'aggregation'}).status_code==422


@pytest.mark.parametrize('title', ['z-first.pdf', '  Confirmed report  '])
def test_combined_confirmed_title_preserves_component_names_order_and_content(client, aggregation, title):
    names=['z-first.pdf','a-second.pdf']
    result=drop(client,aggregation,separate=False,data={'title':title},
                files=[('files',(name,content,'application/pdf')) for name,content in zip(names,[b'first',b'second'])])
    assert result.status_code==201,result.text
    assert result.json()=={'count':1}
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        record=c.execute('SELECT * FROM records').fetchone()
        assert record['title']==title.strip()
        components=c.execute('SELECT * FROM digital_components ORDER BY component_order').fetchall()
        assert [row['file_name'] for row in components]==names
        assert [row['record_id'] for row in components]==[record['id']]*2
    for component,content in zip(components,[b'first',b'second']):
        assert client.get(f"/api/v1/digital-components/{component['id']}/content").content==content


@pytest.mark.parametrize('title', [None, '', '   '])
def test_combined_requires_nonblank_confirmed_title_before_creation(client, aggregation, title):
    result=drop(client,aggregation,separate=False,data={'title':title})
    assert result.status_code==422,result.text
    assert any(error['loc']==['body','title'] for error in result.json()['detail'])
    with psycopg.connect(os.environ['DATABASE_URL']) as c:
        for table in ('records','digital_components','digital_component_blobs','digital_component_content_sets'):
            assert c.execute(f'SELECT count(*) FROM {table}').fetchone()[0]==0


def test_combined_preserves_confirmed_order_for_duplicate_filenames(client, aggregation):
    # Two same-named files remain distinct after the UI moves the second first.
    result=drop(client,aggregation,separate=False,data={'title':'Custom title'},files=[
        ('files',('same.txt',b'second original file','text/plain')),
        ('files',('middle.txt',b'middle file','text/plain')),
        ('files',('same.txt',b'first original file','text/plain')),
    ])
    assert result.status_code==201,result.text
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        records=c.execute('SELECT * FROM records').fetchall()
        assert len(records)==1 and records[0]['title']=='Custom title'
        components=c.execute('SELECT * FROM digital_components ORDER BY component_order').fetchall()
        assert [row['file_name'] for row in components]==['same.txt','middle.txt','same.txt']
        assert [row['component_order'] for row in components]==[1,2,3]
        assert all(row['record_id']==records[0]['id'] for row in components)
    for component,expected in zip(components,[b'second original file',b'middle file',b'first original file']):
        assert client.get(f"/api/v1/digital-components/{component['id']}/content").content==expected
