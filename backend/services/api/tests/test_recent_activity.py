import os

import psycopg
from psycopg.rows import dict_row

from backend.services.api.tests.test_global_privilege_enforcement import _account, _bearer

ACTIVITY = "/api/v1/auth/me/recent-activity"


def test_cards_authorize_before_limit_and_keep_latest_event_order(client, aggregation, record):
    token, user, _ = _account(client, privileges=("record.view",), suffix="recent")
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('app.event_source','seeding',true)")
        records = connection.execute("""
            INSERT INTO records(aggregation_id,owning_org_unit_id,title,record_number,inherit_acl_from_parent)
            SELECT aggregation.id,aggregation.owning_org_unit_id,'Activity '||i,'ACTIVITY-'||i,false
              FROM aggregations aggregation CROSS JOIN generate_series(1,52) i
             WHERE aggregation.id=%s
            RETURNING id,title,record_number
        """, (aggregation["id"],)).fetchall()
        connection.execute("""
            INSERT INTO record_acl_grants(record_id,permission_id,principal_type)
            SELECT identifier,permission.id,'everyone'
              FROM unnest(%s::bigint[]) identifier CROSS JOIN permissions permission
             WHERE permission.code='record.view'
        """, ([row["id"] for row in records[:-1]],))
        connection.execute("""
            INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_type,source,before_state,after_state,occurred_at)
            SELECT 'record',identifier,op.operation,%s,'user','seeding',
                   CASE WHEN op.operation='UPDATE' THEN '{}'::jsonb END,'{}'::jsonb,
                   transaction_timestamp() - op.age
              FROM unnest(%s::bigint[]) identifier
             CROSS JOIN (VALUES ('CREATE',interval '1 hour'),('UPDATE',interval '1 minute'),
                                ('UPDATE',interval '1 day')) op(operation,age)
        """, (user,[row["id"] for row in records]))
    headers = _bearer(token)
    response = client.get(ACTIVITY, params={"entity_type":"record","limit":50}, headers=headers)
    assert response.status_code == 200, response.text
    cards = response.json()
    assert len(cards) == 100
    # All event times tie within each operation. The top 50 are selected by
    # event ID descending, then the public display order is resource ID ascending.
    expected = records[1:-1]
    assert [item["operation"] for item in cards] == ["UPDATE"]*50 + ["CREATE"]*50
    assert [(item["entity_id"],item["title"],item["number"]) for item in cards] == [
        (row["id"],row["title"],row["record_number"]) for row in expected*2
    ]
    assert {item["occurred_at"] for item in cards[:50]} == {cards[0]["occurred_at"]}
    assert client.get(ACTIVITY, params={"entity_type":"aggregation","limit":50}, headers=headers).json() == []
    assert client.get(ACTIVITY, params={"entity_type":"record","limit":51}, headers=headers).status_code == 422
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("DELETE FROM record_acl_grants WHERE record_id=%s", (expected[-1]["id"],))
    fresh = client.get(ACTIVITY, params={"entity_type":"record","limit":50}, headers=headers).json()
    assert [item["entity_id"] for item in fresh[:50]] == [row["id"] for row in records[:-2]]
    client.cookies.clear()
    assert client.get(ACTIVITY, params={"entity_type":"record"}).status_code == 401


def test_scoped_cards_audit_governance_once_per_resource(client, aggregation):
    token,user,role = _account(client, privileges=("aggregation.view",), suffix="governance-activity")
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("UPDATE roles SET is_information_governance=true WHERE id=%s", (role,))
        connection.execute("SELECT set_config('app.event_source','seeding',true)")
        connection.execute("""
            INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_type,source,before_state,after_state)
            SELECT 'aggregation',%s,operation,%s,'user','seeding',
                   CASE WHEN operation='UPDATE' THEN '{}'::jsonb END,'{}'::jsonb
              FROM (VALUES ('CREATE'),('UPDATE')) actions(operation)
        """, (aggregation["id"],user))
    response = client.get(ACTIVITY, params={"entity_type":"aggregation","limit":50}, headers=_bearer(token))
    assert response.status_code == 200, response.text
    assert {(row["title"],row["number"],row["operation"]) for row in response.json()} == {
        (aggregation["title"],aggregation["aggregation_number"],operation) for operation in ("CREATE","UPDATE")
    }
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        audit = connection.execute("""
            SELECT entity_type,entity_id,metadata FROM event_history
             WHERE actor_user_id=%s AND operation='INFORMATION_GOVERNANCE_BYPASS_USED'
        """, (user,)).fetchall()
    assert [(event["entity_type"],event["entity_id"]) for event in audit] == [("aggregation",aggregation["id"])]
    metadata = audit[0]["metadata"]
    assert metadata["required_privilege"] == metadata["required_permission"] == "aggregation.view"
    assert [item["id"] for item in metadata["qualifying_roles"]] == [role]
