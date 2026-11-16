import os
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from backend.services.api import creator_attribution, search_page

from .test_resource_relationships import another_record


def set_view_permissions(connection, privileges):
    code = f"DETAIL-{uuid4().hex[:12]}"
    profile_id = connection.execute(
        "INSERT INTO profiles(code,name) VALUES (%s,%s) RETURNING id",
        (code, f"Detail page test {code}"),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO profile_privileges(profile_id,privilege_id) SELECT %s,id FROM privileges WHERE code=ANY(%s)",
        (profile_id, privileges),
    )
    connection.execute(
        "UPDATE roles SET profile_id=%s,is_information_governance=false WHERE code='system-administrator'",
        (profile_id,),
    )


def test_record_closure_redacts_inaccessible_source(client, aggregation, record):
    record_path = f"/api/v1/records/{record['id']}/effective-closure"
    aggregation_path = f"/api/v1/aggregations/{aggregation['id']}/effective-closure"
    assert client.get(record_path).json() == {"closure": None}
    assert client.get(aggregation_path).json() == {"closure": None}

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("UPDATE records SET inherit_acl_from_parent=false WHERE id=%s", (record["id"],))
        connection.execute(
            """INSERT INTO record_acl_grants(record_id,principal_type,permission_id)
               SELECT %s,'everyone',id FROM permissions WHERE code='record.view' ON CONFLICT DO NOTHING""",
            (record["id"],),
        )
        connection.execute(
            "UPDATE aggregations SET date_closed=CURRENT_TIMESTAMP WHERE id=%s", (aggregation["id"],),
        )
    visible_closure = client.get(record_path).json()["closure"]
    assert visible_closure == client.get(aggregation_path).json()["closure"]
    assert visible_closure["id"] == aggregation["id"]
    assert visible_closure["aggregation_number"] == aggregation["aggregation_number"]
    assert visible_closure["date_closed"]

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        set_view_permissions(connection, ["aggregation.view", "record.view"])
        connection.execute("DELETE FROM aggregation_acl_grants WHERE aggregation_id=%s", (aggregation["id"],))

    assert client.get(record_path).json() == {"closure": {"restricted": True}}
    assert client.get(aggregation_path).status_code in {403, 404}
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("DELETE FROM record_acl_grants WHERE record_id=%s", (record["id"],))
    assert client.get(record_path).status_code in {403, 404}


def test_contained_record_page_includes_only_current_capabilities(client, aggregation, record):
    hidden = another_record(client, aggregation)
    path = '/api/v1/records/search'
    query = {
        'where': {'field': 'aggregation_id', 'operator': 'eq', 'value': aggregation['id']},
        'include': ['record_capabilities'], 'limit': 25,
        'sort': [{'field': 'record_number', 'direction': 'asc'}],
    }
    response = client.post(path, json=query)
    assert response.status_code == 200, response.text
    assert response.json()['total'] == 2
    for item in response.json()['items']:
        actual = client.get(f"/api/v1/records/{item['id']}/capabilities").json()['capabilities']
        assert item['_capabilities'] == {
            'list_components': actual['list_components'],
            'component_count': actual.get('component_count', 0),
            'has_previewable_component': actual.get('has_previewable_component', False),
        }

    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        set_view_permissions(connection, ['record.view'])
        connection.execute('UPDATE records SET inherit_acl_from_parent=false WHERE id=ANY(%s)',
                           ([record['id'], hidden['id']],))
        connection.execute('DELETE FROM record_acl_grants WHERE record_id=ANY(%s)', ([record['id'], hidden['id']],))
        connection.execute(
            """INSERT INTO record_acl_grants(record_id,principal_type,permission_id)
               SELECT %s,'everyone',id FROM permissions WHERE code='record.view'""",
            (record['id'],),
        )

    tab = str(uuid4())
    for context in ({}, {'tab_id': tab}):
        response = client.post(path, json={**query, **context})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['total'] == 1
        assert [item['id'] for item in body['items']] == [record['id']]
        assert body['items'][0]['_capabilities'] == {
            'list_components': False, 'component_count': 0, 'has_previewable_component': False,
        }


def test_contained_record_page_keeps_authorized_rows_if_capabilities_fail(client, aggregation, record, monkeypatch):
    def fail_capabilities(connection, *_):
        connection.execute("SELECT 1 / 0")

    monkeypatch.setattr(search_page, 'page_details', fail_capabilities)
    query = {
        'where': {'field': 'aggregation_id', 'operator': 'eq', 'value': aggregation['id']},
        'include': ['record_capabilities'], 'limit': 25,
    }
    for context in ({}, {'tab_id': str(uuid4())}):
        response = client.post('/api/v1/records/search', json={**query, **context})
        assert response.status_code == 200, response.text
        assert response.json()['total'] == 1
        item, = response.json()['items']
        assert item['id'] == record['id']
        assert '_capabilities' not in item


def test_contained_filter_rebuilds_replaced_list_and_keeps_requested_page(client, aggregation, record):
    other = another_record(client, aggregation)
    tab_id = str(uuid4())
    request = {
        'tab_id': tab_id, 'limit': 1, 'include': ['record_capabilities'],
        'where': {'field': 'aggregation_id', 'operator': 'eq', 'value': aggregation['id']},
        'sort': [{'field': 'record_number', 'direction': 'asc'}],
    }
    path = '/api/v1/records/search'
    original = client.post(path, json=request)
    assert original.status_code == 200, original.text
    replacement = client.post(path, json={**request, 'where': {'field': 'id', 'operator': 'eq', 'value': other['id']}})
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()['search_id'] != original.json()['search_id']
    rebuilt = client.post(path, json={**request, 'search_id': original.json()['search_id'], 'offset': 1})
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()['search_id'] not in {original.json()['search_id'], replacement.json()['search_id']}
    assert rebuilt.json()['total'] == 2
    expected = max((record, other), key=lambda row: row['record_number'])
    assert [item['id'] for item in rebuilt.json()['items']] == [expected['id']]


def test_creator_names_follow_item_access_and_only_load_the_returned_page(client, aggregation, record, monkeypatch):
    archived = another_record(client, aggregation)
    missing = another_record(client, aggregation, 'REC-003')
    hidden = another_record(client, aggregation, 'REC-004')
    records = [record['id'], archived['id'], missing['id'], hidden['id']]
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        actor, = connection.execute("""SELECT actor_user_id FROM event_history
            WHERE entity_type='record' AND entity_id=%s AND operation='CREATE'""", (record['id'],)).fetchone()
        connection.execute('UPDATE users SET name=%s,translations=%s WHERE id=%s',
                           ('Current creator', Jsonb({'ar': {'name': 'منشئ الوثيقة'}}), actor))
        connection.execute("""INSERT INTO user_preferences(user_id,language_tag,working_timezone)
            VALUES (%s,'ar','Asia/Dubai') ON CONFLICT (user_id) DO UPDATE SET language_tag='ar'""", (actor,))
        set_view_permissions(connection, ['aggregation.view', 'record.view'])
        connection.execute('UPDATE records SET inherit_acl_from_parent=false WHERE id=ANY(%s)', (records,))
        connection.execute('DELETE FROM record_acl_grants WHERE record_id=ANY(%s)', (records,))
        connection.execute("""INSERT INTO record_acl_grants(record_id,principal_type,permission_id)
            SELECT record_id,'everyone',permissions.id FROM unnest(%s::bigint[]) record_id
            CROSS JOIN permissions WHERE code='record.view'""", (records[:3],))
        connection.execute("SET LOCAL session_replication_role='replica'")
        connection.execute("""UPDATE event_history SET actor_user_id=NULL,actor_name='Archived creator'
            WHERE entity_type='record' AND entity_id=%s AND operation='CREATE'""", (archived['id'],))
        connection.execute("DELETE FROM event_history WHERE entity_type='record' AND entity_id=%s AND operation='CREATE'",
                           (missing['id'],))

    assert client.get('/api/v1/event-history').status_code == 403
    lookups = []
    original = creator_attribution.add_creator_names
    def trace(connection, page, *, id_key='id'):
        rows = list(page)
        lookups.append([(kind, row[id_key]) for kind, row in rows])
        original(connection, rows, id_key=id_key)

    monkeypatch.setattr(creator_attribution, 'add_creator_names', trace)
    query = {'where': {'field': 'aggregation_id', 'operator': 'eq', 'value': aggregation['id']},
             'include': ['record_capabilities'], 'limit': 1}
    expected = [(record['id'], 'منشئ الوثيقة'), (archived['id'], 'Archived creator'), (missing['id'], None)]
    for offset, (identifier, name) in enumerate(expected):
        lookups.clear()
        response = client.post('/api/v1/records/search', json={**query, 'offset': offset})
        assert response.status_code == 200, response.text
        assert response.json()['total'] == 3
        row, = response.json()['items']
        assert (row['id'], row.get('created_by')) == (identifier, name)
        assert lookups == [[('record', identifier)]]

    response = client.get('/api/v1/aggregations', params={'limit': 1})
    assert response.status_code == 200
    assert response.json()[0]['created_by'] == 'منشئ الوثيقة'


def test_creator_lookup_error_does_not_break_a_listing(client, record, monkeypatch):
    monkeypatch.setattr(creator_attribution, 'CREATOR_NAMES_SQL', 'SELECT missing_creator_table')
    result = client.get('/api/v1/records', params={'limit': 1})
    assert result.status_code == 200, result.text
    row, = result.json()
    assert row['id'] == record['id']
    assert row.get('created_by') is None
