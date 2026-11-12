"""Entity history keeps the same event scope across bounded pages."""

import os

import psycopg

from backend.services.api.tests.test_legal_holds_api import _create_hold


def test_entity_history_can_read_past_the_old_limits(client):
    hold = _create_hold(client)
    targets = [
        ("org-units", "org_unit", "SELECT min(id) FROM org_units"),
        ("roles", "role", "SELECT min(id) FROM roles"),
        ("users", "user", "SELECT min(id) FROM users"),
        ("profiles", "profile", "SELECT id FROM profiles WHERE code='ALL_PRIVS'"),
        ("security-levels", "security_level", "SELECT min(id) FROM security_levels"),
        ("classification-schemes", "classification_scheme", "SELECT min(id) FROM classification_schemes"),
        ("classifications", "classification", "SELECT min(id) FROM classifications"),
    ]
    histories = []
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("SELECT set_config('app.event_source','seeding',true)")
        for resource, entity_type, lookup in targets:
            entity_id = connection.execute(lookup).fetchone()[0]
            assert entity_id is not None
            rows = connection.execute(
                """INSERT INTO event_history(occurred_at,entity_type,entity_id,operation,source)
                   SELECT '2030-01-01T12:00:00Z',%s,%s,'ACCESS_EXPLANATION_VIEWED','seeding'
                     FROM generate_series(1,502)
                   RETURNING id""",
                (entity_type, entity_id),
            ).fetchall()
            histories.append((resource, entity_id, 500, sorted((row[0] for row in rows), reverse=True)))
        # Hold history includes related events tagged with a hold ID.
        rows = connection.execute(
            """INSERT INTO event_history(occurred_at,entity_type,entity_id,operation,source,metadata)
               SELECT '2030-01-01T12:00:00Z','hold',%s,'ACCESS_EXPLANATION_VIEWED','seeding',
                      jsonb_build_object('hold_id',%s::text)
                 FROM generate_series(1,202)
               RETURNING id""",
            (hold["id"], hold["id"]),
        ).fetchall()
        histories.append(("holds", hold["id"], 200, sorted((row[0] for row in rows), reverse=True)))

    for resource, entity_id, old_cutoff, ids in histories:
        endpoint = f"/api/v1/{resource}/{entity_id}/history"
        page = client.get(endpoint, params={"limit": 2, "offset": old_cutoff})
        assert page.status_code == 200, page.text
        assert [item["id"] for item in page.json()] == ids[old_cutoff:old_cutoff + 2]
        assert client.get(endpoint, params={"offset": -1}).status_code == 422
