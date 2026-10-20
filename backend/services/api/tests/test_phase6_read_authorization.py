import os

import psycopg

from backend.services.api.authentication import hash_password
from backend.services.api.crud import redact_hidden_relationships


class _CountingConnection:
    def __init__(self):
        self.calls = 0

    def execute(self, _query, _parameters):
        self.calls += 1
        return self

    def fetchall(self):
        return [{"id": 1}]


def test_relationship_redaction_query_count_is_bounded():
    connection = _CountingConnection()
    rows = [{"id": item, "aggregation_id": (item % 2) + 1} for item in range(1, 501)]
    redacted = redact_hidden_relationships(connection, "records", rows)
    assert connection.calls == 1
    assert all(row["aggregation_id"] == 1 for row in redacted if row["id"] % 2 == 0)
    assert all(row["aggregation_id"] is None for row in redacted if row["id"] % 2 == 1)
    assert all(row["aggregation_state"] == "visible" for row in redacted if row["id"] % 2 == 0)
    assert all(row["aggregation_state"] == "redacted" for row in redacted if row["id"] % 2 == 1)


def _login(client, email: str, password: str) -> None:
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = client.cookies.get("erms_csrf")


def test_hidden_resources_are_non_disclosing_across_read_surfaces(client):
    visible = client.post("/api/v1/aggregations", json={
        "aggregation_number": "VISIBLE", "title": "Visible", "classification_id": 1,
    }).json()
    hidden = client.post("/api/v1/aggregations", json={
        "aggregation_number": "HIDDEN", "title": "Hidden", "classification_id": 1,
    }).json()
    visible_child_of_hidden = client.post("/api/v1/aggregations", json={
        "parent_aggregation_id": hidden["id"],
        "aggregation_number": "VISIBLE-CHILD-HIDDEN-PARENT",
        "title": "Visible child with hidden parent",
    }).json()
    hidden_record = client.post("/api/v1/records", json={
        "aggregation_id": visible["id"], "record_number": "SECRET-RECORD", "title": "Hidden record",
    }).json()
    component = client.post("/api/v1/digital-components", json={
        "record_id": hidden_record["id"], "component_order": 1, "file_name": "secret.pdf",
        "mime_type": "application/pdf", "size_in_bytes": 0,
        "checksum_algo": "sha256", "checksum_value": "0" * 64,
    }).json()

    password = "Phase-6-Test-Password-123!"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        org_id = connection.execute("SELECT id FROM org_units ORDER BY id LIMIT 1").fetchone()[0]
        baseline = connection.execute("SELECT id FROM security_levels ORDER BY level_number LIMIT 1").fetchone()[0]
        profile = connection.execute("SELECT id FROM profiles WHERE code='ALL_PRIVS'").fetchone()[0]
        user_id = connection.execute(
            "INSERT INTO users(name,email) VALUES ('Phase Six Reader','phase6@test.invalid') RETURNING id"
        ).fetchone()[0]
        role_id = connection.execute(
            """INSERT INTO roles(org_unit_id,code,name,security_level_id,profile_id)
               VALUES (%s,'PHASE6','Phase Six Reader',%s,%s) RETURNING id""",
            (org_id, baseline, profile),
        ).fetchone()[0]
        connection.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)", (user_id, role_id))
        connection.execute(
            "INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES (%s,%s,false)",
            (user_id, hash_password(password)),
        )
        connection.execute("UPDATE records SET inherit_acl_from_parent=false WHERE id=%s", (hidden_record["id"],))
        connection.execute("DELETE FROM aggregation_acl_grants WHERE aggregation_id=%s", (hidden["id"],))
        connection.execute(
            "UPDATE aggregations SET inherit_acl_from_parent=false WHERE id=%s",
            (visible_child_of_hidden["id"],),
        )
        connection.execute(
            "DELETE FROM aggregation_acl_grants WHERE aggregation_id=%s",
            (visible_child_of_hidden["id"],),
        )
        connection.execute(
            """INSERT INTO aggregation_acl_grants(
                   aggregation_id,principal_type,role_id,permission_id
               ) SELECT %s,'role',%s,id FROM permissions
                  WHERE code='aggregation.view'""",
            (visible_child_of_hidden["id"], role_id),
        )
        connection.execute("DELETE FROM record_acl_grants WHERE record_id=%s", (hidden_record["id"],))
        connection.execute(
            "INSERT INTO user_favourite_aggregations(user_id,aggregation_id) VALUES (%s,%s)",
            (user_id, hidden["id"]),
        )
        connection.execute(
            "INSERT INTO user_favourite_records(user_id,record_id) VALUES (%s,%s)",
            (user_id, hidden_record["id"]),
        )

    _login(client, "phase6@test.invalid", password)

    hidden_response = client.get(f"/api/v1/aggregations/{hidden['id']}")
    absent_response = client.get("/api/v1/aggregations/999999999")
    assert hidden_response.status_code == absent_response.status_code == 404
    assert hidden_response.json() == absent_response.json()
    visible_aggregations = client.get("/api/v1/aggregations?limit=500").json()
    assert {row["id"] for row in visible_aggregations} == {
        visible["id"], visible_child_of_hidden["id"],
    }
    protected_child = next(
        row for row in visible_aggregations
        if row["id"] == visible_child_of_hidden["id"]
    )
    assert protected_child["parent_aggregation_id"] is None
    assert protected_child["parent_aggregation_state"] == "redacted"
    roots = client.post("/api/v1/aggregations/search", json={
        "where": {"field": "parent_aggregation_id", "operator": "is_null"},
        "limit": 50, "offset": 0,
    }).json()
    assert visible_child_of_hidden["id"] not in {row["id"] for row in roots["items"]}
    assert all(row["parent_aggregation_state"] == "none" for row in roots["items"])
    search = client.post("/api/v1/aggregations/search", json={
        "where": {"field": "title", "operator": "contains_ci", "value": "Hidden"},
        "limit": 50, "offset": 0,
    }).json()
    assert {row["id"] for row in search["items"]} == {visible_child_of_hidden["id"]}
    assert search["items"][0]["parent_aggregation_id"] is None
    assert search["items"][0]["parent_aggregation_state"] == "redacted"
    dashboard = client.get("/api/v1/dashboard/summary", params={"recent_limit": 7})
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["unclassified_root_count"] == 0
    assert client.get(f"/api/v1/browse/aggregations/{hidden['id']}/summary").status_code == 404
    assert client.get(f"/api/v1/aggregations/{hidden['id']}/capabilities").status_code == 404

    assert client.get(f"/api/v1/records/{hidden_record['id']}").status_code == 404
    assert client.get(f"/api/v1/digital-components/{component['id']}").status_code == 404
    assert client.get(f"/api/v1/digital-components?record_id={hidden_record['id']}").json() == []
    favourites = client.get("/api/v1/favourites").json()
    assert set(favourites) == {"aggregations", "records", "application_configuration"}
    assert favourites["aggregations"] == [] and favourites["records"] == []
    assert isinstance(favourites["application_configuration"], dict)

    audit = client.get("/api/v1/event-history", params={
        "entity_type": "aggregation", "entity_id": hidden["id"], "limit": 10,
    })
    assert audit.status_code == 200
    assert audit.json()
    assert all(event["before_state"] is None and event["after_state"] is None for event in audit.json())
    assert all(event["metadata"].get("redacted") is True for event in audit.json())


def test_lower_clearance_role_does_not_veto_maximum_effective_clearance(client):
    resource = client.post("/api/v1/aggregations", json={
        "aggregation_number": "CLEARANCE", "title": "Clearance union", "classification_id": 1,
    }).json()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        levels = connection.execute("SELECT code,id FROM security_levels").fetchall()
        by_code = {code: level_id for code, level_id in levels}
        connection.execute("UPDATE aggregations SET security_level_id=%s WHERE id=%s", (by_code["TS"], resource["id"]))
        user_id = connection.execute("SELECT id FROM users WHERE email='admin@test.invalid'").fetchone()[0]
        org_id = connection.execute("SELECT id FROM org_units ORDER BY id LIMIT 1").fetchone()[0]
        profile = connection.execute("SELECT id FROM profiles WHERE code='ALL_PRIVS'").fetchone()[0]
        connection.execute("UPDATE roles SET security_level_id=%s WHERE id=1", (by_code["TS"],))
        low_role = connection.execute(
            "INSERT INTO roles(org_unit_id,code,name,security_level_id,profile_id) VALUES (%s,'LOW','Low',%s,%s) RETURNING id",
            (org_id, by_code["G"], profile),
        ).fetchone()[0]
        connection.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)", (user_id, low_role))
    assert client.get(f"/api/v1/aggregations/{resource['id']}").status_code == 200
