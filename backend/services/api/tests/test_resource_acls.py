import os

import psycopg
import pytest
from fastapi.testclient import TestClient


def _make_custodian() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            """UPDATE roles SET is_information_governance=true,
                      security_level_id=(SELECT id FROM security_levels ORDER BY level_number DESC LIMIT 1)
                 WHERE id=1"""
        )


def _everyone(*codes: str) -> dict:
    return {"principal_type": "everyone", "role_id": None, "permission_codes": list(codes)}


def _create_child(client: TestClient, parent_id: int, number: str) -> dict:
    response = client.post("/api/v1/aggregations", json={
        "parent_aggregation_id": parent_id, "aggregation_number": number, "title": number,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_catalogue_organizational_defaults_and_no_synthetic_role(client: TestClient, aggregation: dict, record: dict):
    catalogue = client.get("/api/v1/permissions")
    assert catalogue.status_code == 200
    assert len(catalogue.json()) == 35
    aggregation_acl = client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").json()
    record_acl = client.get(f"/api/v1/records/{record['id']}/permissions").json()
    assert aggregation_acl["inherit_acl_from_parent"] is False
    aggregation_grants = {grant["principal_type"]: set(grant["permission_codes"]) for grant in aggregation_acl["effective_acl"]}
    assert aggregation_grants["org_unit_members"] == {"aggregation.view", "aggregation.history.view"}
    assert aggregation_grants["role"] == {
        "aggregation.view", "aggregation.modify_metadata", "aggregation.add_child",
        "aggregation.add_record", "aggregation.close",
        "aggregation.history.view",
    }
    assert record_acl["inherit_acl_from_parent"] is True
    assert record_acl["effective_acl_source"] == "parent_default"
    record_grants = {grant["principal_type"]: set(grant["permission_codes"]) for grant in record_acl["effective_acl"]}
    assert record_grants["org_unit_members"] == {
        "record.view", "record.component.list", "record.component.view",
        "record.component.download",
    }
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute("SELECT count(*) FROM roles WHERE lower(code)='everyone'").fetchone()[0] == 0
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute("INSERT INTO roles(org_unit_id,code,name) VALUES (1,'Everyone','Fake')")


def test_live_mirror_chain_custom_boundary_and_dormant_override(client: TestClient, aggregation: dict):
    _make_custodian()
    child = _create_child(client, aggregation["id"], "CHILD")
    grandchild = _create_child(client, child["id"], "GRANDCHILD")
    before = client.get(f"/api/v1/aggregations/{grandchild['id']}/permissions").json()
    assert before["effective_acl_source"].startswith("parent_mirror")
    assert before["effective_acl_source_id"] == aggregation["id"]

    root = client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").json()
    replaced = client.put(f"/api/v1/aggregations/{aggregation['id']}/permissions", json={
        "version": root["resource_acl_version"], "grants": [_everyone("aggregation.view")],
        "reason": "Restrict the branch",
    })
    assert replaced.status_code == 200, replaced.text
    assert client.get(f"/api/v1/aggregations/{grandchild['id']}/permissions").json()["effective_acl"][0]["permission_codes"] == ["aggregation.view"]

    child_default = client.get(f"/api/v1/aggregations/{child['id']}/default-child-aggregation-permissions").json()
    custom = client.put(f"/api/v1/aggregations/{child['id']}/default-child-aggregation-permissions", json={
        "version": child_default["version"], "mode": "custom",
        "grants": [_everyone("aggregation.view", "aggregation.history.view")],
        "reason": "Create a branch boundary",
    })
    assert custom.status_code == 200, custom.text
    effective = client.get(f"/api/v1/aggregations/{grandchild['id']}/permissions").json()
    assert effective["effective_acl_source"] == "parent_custom_default"
    assert set(effective["effective_acl"][0]["permission_codes"]) == {"aggregation.view", "aggregation.history.view"}

    grandchild_acl = client.get(f"/api/v1/aggregations/{grandchild['id']}/permissions").json()
    assert grandchild_acl["override_acl_is_dormant"] is True
    dormant = {grant["principal_type"]: set(grant["permission_codes"]) for grant in grandchild_acl["override_acl"]}
    assert dormant["org_unit_members"] == {"aggregation.view", "aggregation.history.view"}
    assert len(dormant["role"]) == 6

    preview = client.post(f"/api/v1/aggregations/{child['id']}/default-child-aggregation-permissions/preview", json={
        "version": custom.json()["version"], "mode": "mirror_resource_acl",
        "grants": [_everyone("aggregation.view", "aggregation.history.view")],
        "reason": "Preview mirror restoration",
    })
    assert preview.status_code == 200, preview.text
    assert preview.json()["affected_aggregation_count"] == 1
    assert preview.json()["removed_grants"] == 1


def test_api_and_deferred_database_dependency_enforcement(client: TestClient, aggregation: dict):
    _make_custodian()
    acl = client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").json()
    invalid = client.put(f"/api/v1/aggregations/{aggregation['id']}/permissions", json={
        "version": acl["resource_acl_version"],
        "grants": [_everyone("aggregation.delete")], "reason": "Invalid",
    })
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "permission_dependency_violation"
    after = client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").json()
    assert after["resource_acl_version"] == acl["resource_acl_version"]

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        delete_id = connection.execute("SELECT id FROM permissions WHERE code='aggregation.delete'").fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation, match="permission_dependency_violation"):
            with connection.transaction():
                connection.execute("DELETE FROM aggregation_acl_grants WHERE aggregation_id=%s", (aggregation["id"],))
                connection.execute("INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,permission_id) VALUES (%s,'everyone',%s)", (aggregation["id"],delete_id))
                connection.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_optimistic_concurrency_atomic_rollback_and_audit(client: TestClient, aggregation: dict):
    _make_custodian()
    acl = client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").json()
    ok = client.put(f"/api/v1/aggregations/{aggregation['id']}/permissions", json={
        "version": acl["resource_acl_version"], "grants": [_everyone("aggregation.view")],
        "reason": "Reduce ordinary access",
    })
    assert ok.status_code == 200, ok.text
    stale = client.put(f"/api/v1/aggregations/{aggregation['id']}/permissions", json={
        "version": acl["resource_acl_version"], "grants": [_everyone("aggregation.view")],
        "reason": "Stale write",
    })
    assert stale.status_code == 409
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        events = connection.execute("SELECT operation,reason FROM event_history WHERE entity_type='aggregation' AND entity_id=%s ORDER BY id", (aggregation["id"],)).fetchall()
    assert ("ACL_REPLACED", "Reduce ordinary access") in events


def test_record_inheritance_override_and_parent_default_live_change(client: TestClient, aggregation: dict, record: dict):
    _make_custodian()
    default = client.get(f"/api/v1/aggregations/{aggregation['id']}/default-child-record-permissions").json()
    changed = client.put(f"/api/v1/aggregations/{aggregation['id']}/default-child-record-permissions", json={
        "version": default["version"], "grants": [_everyone("record.view", "record.component.list")],
        "reason": "Limit inherited record access",
    })
    assert changed.status_code == 200, changed.text
    inherited = client.get(f"/api/v1/records/{record['id']}/permissions").json()
    assert set(inherited["effective_acl"][0]["permission_codes"]) == {"record.view", "record.component.list"}
    override = client.put(f"/api/v1/records/{record['id']}/permissions", json={
        "version": inherited["resource_acl_version"], "inherit_acl_from_parent": False,
        "grants": [_everyone("record.view")], "reason": "Record-specific restriction",
    })
    assert override.status_code == 200, override.text
    assert override.json()["effective_acl_source"] == "resource_override"
    assert override.json()["effective_acl"][0]["permission_codes"] == ["record.view"]


def test_orphan_prevention_rejects_without_governance_custodian(client: TestClient, aggregation: dict):
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        # Explicit legacy/manual grant: new creator defaults no longer grant ACL management.
        connection.execute("INSERT INTO aggregation_acl_grants(aggregation_id,principal_type,role_id,permission_id) SELECT %s,'role',1,id FROM permissions WHERE code='aggregation.acl.manage'", (aggregation["id"],))
        connection.execute("UPDATE roles SET is_information_governance=false WHERE id=1")
    acl = client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").json()
    denied = client.put(f"/api/v1/aggregations/{aggregation['id']}/permissions", json={
        "version": acl["resource_acl_version"], "grants": [_everyone("aggregation.view")],
        "reason": "Would leave no custodian",
    })
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "resource_without_effective_custodian"


def test_direct_user_org_and_deny_shapes_are_impossible(client: TestClient, aggregation: dict):
    acl = client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").json()
    for malformed in (
        {"principal_type": "user", "role_id": None, "permission_codes": ["aggregation.view"]},
        {"principal_type": "org_unit", "role_id": None, "permission_codes": ["aggregation.view"]},
        {"principal_type": "deny", "role_id": 1, "permission_codes": ["aggregation.view"]},
    ):
        response = client.put(f"/api/v1/aggregations/{aggregation['id']}/permissions", json={
            "version": acl["resource_acl_version"], "grants": [malformed], "reason": "Invalid principal",
        })
        assert response.status_code == 422


def test_custom_template_is_retained_dormant_when_switching_back_to_mirror(client: TestClient, aggregation: dict):
    _make_custodian()
    initial = client.get(f"/api/v1/aggregations/{aggregation['id']}/default-child-aggregation-permissions").json()
    custom = client.put(f"/api/v1/aggregations/{aggregation['id']}/default-child-aggregation-permissions", json={
        "version": initial["version"], "mode": "custom",
        "grants": [_everyone("aggregation.view", "aggregation.history.view")],
        "reason": "Define custom defaults",
    })
    assert custom.status_code == 200, custom.text
    mirrored = client.put(f"/api/v1/aggregations/{aggregation['id']}/default-child-aggregation-permissions", json={
        "version": custom.json()["version"], "mode": "mirror_resource_acl",
        "grants": [_everyone("aggregation.view", "aggregation.history.view")],
        "reason": "Return to live mirroring",
    })
    assert mirrored.status_code == 200, mirrored.text
    body = mirrored.json()
    assert body["custom_acl_is_dormant"] is True
    assert set(body["custom_acl"][0]["permission_codes"]) == {"aggregation.view", "aggregation.history.view"}
    effective = {grant["principal_type"]: set(grant["permission_codes"]) for grant in body["effective_acl"]}
    assert effective["org_unit_members"] == {"aggregation.view", "aggregation.history.view"}
    assert len(effective["role"]) == 6


def test_move_can_follow_destination_or_atomically_keep_current_access(client: TestClient, aggregation: dict):
    _make_custodian()
    second = client.post("/api/v1/aggregations", json={
        "aggregation_number": "ROOT-2", "title": "Second root", "classification_id": 1,
    }).json()
    child = _create_child(client, aggregation["id"], "MOVING")
    root_acl = client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").json()
    restricted = client.put(f"/api/v1/aggregations/{aggregation['id']}/permissions", json={
        "version": root_acl["resource_acl_version"], "grants": [_everyone("aggregation.view")],
        "reason": "Restrict source tree",
    })
    assert restricted.status_code == 200, restricted.text
    preview = client.get(
        f"/api/v1/aggregations/{child['id']}/acl-move-preview",
        params={"destination_aggregation_id": second["id"], "keep_current_access_as_override": True},
    )
    assert preview.status_code == 200, preview.text
    moved = client.post(f"/api/v1/aggregations/{child['id']}/acl-move", json={
        "destination_aggregation_id": second["id"],
        "resource_version": client.get(f"/api/v1/aggregations/{child['id']}").json()["version"],
        "keep_current_access_as_override": True, "reason": "Move but preserve access",
    })
    assert moved.status_code == 200, moved.text
    effective = client.get(f"/api/v1/aggregations/{child['id']}/permissions").json()
    assert effective["inherit_acl_from_parent"] is False
    assert effective["effective_acl"][0]["permission_codes"] == ["aggregation.view"]


def test_role_grant_cannot_exceed_role_clearance(client: TestClient, aggregation: dict):
    _make_custodian()
    levels = {item["code"]: item for item in client.get("/api/v1/security-levels").json()}
    upgraded = client.patch(
        f"/api/v1/aggregations/{aggregation['id']}",
        json={"security_level_id": levels["S"]["id"]},
        headers={"If-Match": str(aggregation["version"]), "X-Change-Reason": "Classification changed"},
    )
    assert upgraded.status_code == 200, upgraded.text
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        org_id = connection.execute("SELECT id FROM org_units LIMIT 1").fetchone()[0]
        role_id = connection.execute("INSERT INTO roles(org_unit_id,code,name) VALUES (%s,'LOW','Low clearance') RETURNING id", (org_id,)).fetchone()[0]
    acl = client.get(f"/api/v1/aggregations/{aggregation['id']}/permissions").json()
    denied = client.put(f"/api/v1/aggregations/{aggregation['id']}/permissions", json={
        "version": acl["resource_acl_version"],
        "grants": [{"principal_type":"role","role_id":role_id,"permission_codes":["aggregation.view"]}],
        "reason": "Invalid clearance",
    })
    assert denied.status_code == 422
    assert denied.json()["detail"]["code"] == "role_clearance_below_resource"
