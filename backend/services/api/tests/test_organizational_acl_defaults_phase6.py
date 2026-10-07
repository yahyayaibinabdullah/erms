import os

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row


AGGREGATION_CREATOR = {
    "aggregation.view", "aggregation.modify_metadata", "aggregation.add_child",
    "aggregation.add_record", "aggregation.close",
    "aggregation.history.view",
}
AGGREGATION_MEMBERS = {"aggregation.view", "aggregation.history.view"}
RECORD_CREATOR = {
    "record.view", "record.history.view",
    "record.component.list", "record.component.view", "record.component.download",
    "record.component.share", "record.component.print",
}
RECORD_MEMBERS = {
    "record.view", "record.component.list", "record.component.view",
    "record.component.download",
}


def _add_role(*, same_unit: bool = False) -> tuple[int, int]:
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        user_id = connection.execute("SELECT id FROM users WHERE email='admin@test.invalid'").fetchone()["id"]
        if same_unit:
            unit_id = connection.execute("SELECT id FROM org_units WHERE code='test-root'").fetchone()["id"]
        else:
            unit_id = connection.execute(
                "INSERT INTO org_units(code,name) VALUES ('second-unit','Second Unit') RETURNING id"
            ).fetchone()["id"]
        role_id = connection.execute(
            "INSERT INTO roles(org_unit_id,code,name) VALUES (%s,'second-role','Second Role') RETURNING id",
            (unit_id,),
        ).fetchone()["id"]
        connection.execute(
            "INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)",
            (user_id, role_id),
        )
        return role_id, unit_id


def _permission_codes(table: str, owner_column: str, owner_id: int, principal: str) -> set[str]:
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        return {
            row["code"] for row in connection.execute(
                f"SELECT permission.code FROM {table} grant_row "
                "JOIN permissions permission ON permission.id=grant_row.permission_id "
                f"WHERE grant_row.{owner_column}=%s AND grant_row.principal_type=%s",
                (owner_id, principal),
            ).fetchall()
        }


def test_create_for_lists_each_effective_role_even_within_one_unit(client: TestClient):
    second_role_id, _ = _add_role(same_unit=True)
    response = client.get("/api/v1/creation-role-options")
    assert response.status_code == 200
    options = response.json()
    assert len(options) == 2
    assert {option["role_id"] for option in options} >= {second_role_id}
    assert len({option["org_unit_id"] for option in options}) == 1
    assert all(" — " in option["label"] for option in options)


def test_selected_role_derives_root_owner_and_initializes_exact_defaults(client: TestClient):
    role_id, unit_id = _add_role()
    response = client.post("/api/v1/aggregations", json={
        "aggregation_number": "PH6-ROOT", "title": "Phase 6 root",
        "classification_id": 1, "creator_acl_role_id": role_id,
    })
    assert response.status_code == 201, response.text
    aggregation = response.json()
    assert aggregation["owning_org_unit_id"] == unit_id
    assert aggregation["inherit_acl_from_parent"] is False
    assert _permission_codes("aggregation_acl_grants", "aggregation_id", aggregation["id"], "role") == AGGREGATION_CREATOR
    assert _permission_codes("aggregation_acl_grants", "aggregation_id", aggregation["id"], "org_unit_members") == AGGREGATION_MEMBERS
    assert _permission_codes("aggregation_child_aggregation_acl_defaults", "aggregation_id", aggregation["id"], "role") == AGGREGATION_CREATOR
    assert _permission_codes("aggregation_child_record_acl_defaults", "aggregation_id", aggregation["id"], "role") == RECORD_CREATOR
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        metadata = connection.execute(
            "SELECT metadata FROM event_history WHERE entity_type='aggregation' AND entity_id=%s AND operation='CREATE' ORDER BY id LIMIT 1",
            (aggregation["id"],),
        ).fetchone()["metadata"]
    assert metadata["creator_acl_role_id"] == role_id
    assert metadata["creator_org_unit_id"] == unit_id


def test_child_and_record_inherit_but_keep_dormant_organizational_defaults(client: TestClient):
    root = client.post("/api/v1/aggregations", json={
        "aggregation_number": "PH6-PARENT", "title": "Parent", "classification_id": 1,
    }).json()
    child = client.post("/api/v1/aggregations", json={
        "aggregation_number": "PH6-CHILD", "title": "Child",
        "parent_aggregation_id": root["id"],
    })
    assert child.status_code == 201, child.text
    child = child.json()
    record = client.post("/api/v1/records", json={
        "aggregation_id": root["id"], "record_number": "PH6-REC", "title": "Record",
    })
    assert record.status_code == 201, record.text
    record = record.json()
    assert child["inherit_acl_from_parent"] is True
    assert record["inherit_acl_from_parent"] is True
    assert _permission_codes("aggregation_acl_grants", "aggregation_id", child["id"], "role") == AGGREGATION_CREATOR
    assert _permission_codes("aggregation_acl_grants", "aggregation_id", child["id"], "org_unit_members") == AGGREGATION_MEMBERS
    assert _permission_codes("record_acl_grants", "record_id", record["id"], "role") == RECORD_CREATOR
    assert _permission_codes("record_acl_grants", "record_id", record["id"], "org_unit_members") == RECORD_MEMBERS


def test_creation_under_parent_requires_effective_role_in_owning_unit(client: TestClient):
    role_id, _ = _add_role()
    root = client.post("/api/v1/aggregations", json={
        "aggregation_number": "PH6-OTHER", "title": "Other owner",
        "classification_id": 1, "creator_acl_role_id": role_id,
    }).json()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("DELETE FROM user_role_assignments WHERE role_id=%s", (role_id,))
    response = client.post("/api/v1/aggregations", json={
        "aggregation_number": "PH6-DENIED", "title": "Denied",
        "parent_aggregation_id": root["id"],
    })
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "creator_acl_role_not_eligible"
