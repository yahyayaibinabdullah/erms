import os

import psycopg
from fastapi.testclient import TestClient


def _by_code(client: TestClient, path: str) -> dict[str, dict]:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return {item["code"]: item for item in response.json()}


def _create_profile(client: TestClient, code: str = "RECORDS_EDITOR") -> dict:
    response = client.post("/api/v1/profiles", json={
        "code": code,
        "name": code.replace("_", " ").title(),
        "description": "A deliberately composed test profile",
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_seeded_catalogue_profiles_and_existing_role_backfill(client: TestClient):
    privileges = _by_code(client, "/api/v1/privileges?limit=500")
    profiles = _by_code(client, "/api/v1/profiles?limit=500")
    separately_seeded = {
        "messaging.user_messages.exchange", "messaging.monitor",
        "messaging.notifications.administer",
    }
    assert len(set(privileges) - separately_seeded) == 61
    assert privileges["localization.administer"]["is_reserved"] is True
    assert {
        "classification_scheme.modify_metadata", "classification.modify_metadata",
        "user.modify_metadata", "role.modify_metadata", "org_unit.modify_metadata",
        "security_level.modify_metadata",
        "profile.modify_metadata",
    } <= set(privileges)
    assert "holds.administer" in privileges
    assert "holds.held_items.manage_all" in privileges
    assert "organization.browse" in privileges
    assert privileges["content.index.execute"]["account_type_restriction"] == "service"
    assert privileges["search.query.debug"]["account_type_restriction"] == "person"
    assert privileges["record.component.reindex"]["account_type_restriction"] == "person"
    assert privileges["identity.text_indexers.administer"]["account_type_restriction"] == "person"
    assert set(profiles) >= {
        "ALL_PRIVS", "SYS_ADMIN",
        "INFO_GOV_MGR", "INFO_GOV_OFFICER",
        "TEXT_INDEXER_SERVICE",
    }
    all_members = client.get(
        f"/api/v1/profiles/{profiles['ALL_PRIVS']['id']}/privileges"
    )
    assert all_members.status_code == 200
    assert {item["code"] for item in all_members.json()} == set(privileges)
    for profile_code in ("INFO_GOV_MGR", "INFO_GOV_OFFICER"):
        profile_members = client.get(
            f"/api/v1/profiles/{profiles[profile_code]['id']}/privileges"
        )
        assert profile_members.status_code == 200
        member_codes = {item["code"] for item in profile_members.json()}
        assert "holds.held_items.manage_all" in member_codes
        assert "holds.administer" not in member_codes
        assert {"record.component.reindex","search.query.debug"} <= member_codes
    system_members = client.get(
        f"/api/v1/profiles/{profiles['SYS_ADMIN']['id']}/privileges"
    ).json()
    assert {"record.component.reindex","search.query.debug","localization.administer","profile.modify_metadata"} <= {
        item["code"] for item in system_members
    }

    role = client.get("/api/v1/roles/1")
    assert role.status_code == 200
    assert role.json()["profile_id"] == profiles["ALL_PRIVS"]["id"]
    assert role.json()["is_information_governance"] is True


def test_composite_profile_dependencies_preview_assignment_and_audit(client: TestClient):
    privileges = _by_code(client, "/api/v1/privileges?limit=500")
    profile = _create_profile(client)

    invalid = client.put(
        f"/api/v1/profiles/{profile['id']}/privileges",
        json={"privilege_ids": [privileges["record.modify"]["id"]]},
        headers={"If-Match": str(profile["version"]), "X-Change-Reason": "Test invalid composition"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "privilege_dependency_violation"

    selected = [
        privileges["record.view"]["id"],
        privileges["record.modify"]["id"],
    ]
    replaced = client.put(
        f"/api/v1/profiles/{profile['id']}/privileges",
        json={"privilege_ids": selected},
        headers={"If-Match": str(profile["version"]), "X-Change-Reason": "Create records editor"},
    )
    assert replaced.status_code == 200, replaced.text
    assert {item["code"] for item in replaced.json()["privileges"]} == {
        "record.view", "record.modify",
    }
    stale_membership = client.put(
        f"/api/v1/profiles/{profile['id']}/privileges",
        json={"privilege_ids": selected},
        headers={"If-Match": str(profile["version"]), "X-Change-Reason": "Stale retry"},
    )
    assert stale_membership.status_code == 412

    role = client.post("/api/v1/roles", json={
        "org_unit_id": 1, "code": "EDITOR", "name": "Records Editor",
    }).json()
    impact = client.get(
        f"/api/v1/roles/{role['id']}/profile/impact",
        params={"profile_id": profile["id"]},
    )
    assert impact.status_code == 200
    assert impact.json()["assigned_user_count"] == 0
    assigned = client.put(
        f"/api/v1/roles/{role['id']}/profile",
        json={"profile_id": profile["id"]},
        headers={"If-Match": str(role["version"]), "X-Change-Reason": "Assign editor duties"},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["profile_id"] == profile["id"]
    assert client.get(f"/api/v1/profiles/{profile['id']}/impact").json()["role_count"] == 1
    listed_profile = next(
        item for item in client.get("/api/v1/profiles").json()
        if item["id"] == profile["id"]
    )
    assert listed_profile["role_count"] == 1
    assert listed_profile["privilege_count"] == 2

    history = client.get(f"/api/v1/roles/{role['id']}/history").json()
    assert "PROFILE_ASSIGNED" in {event["operation"] for event in history}

    profile_history = client.get(f"/api/v1/profiles/{profile['id']}/history")
    assert profile_history.status_code == 200, profile_history.text
    assert "PROFILE_PRIVILEGES_REPLACED" in {
        event["operation"] for event in profile_history.json()
    }


def test_profile_concurrency_and_referentially_safe_deletion(client: TestClient):
    profile = _create_profile(client, "TEMPORARY_PROFILE")
    updated = client.patch(
        f"/api/v1/profiles/{profile['id']}",
        json={"name": "Renamed profile"},
        headers={"If-Match": str(profile["version"]), "X-Change-Reason": "Clarify purpose"},
    )
    assert updated.status_code == 200
    stale = client.patch(
        f"/api/v1/profiles/{profile['id']}",
        json={"name": "Stale edit"},
        headers={"If-Match": str(profile["version"]), "X-Change-Reason": "Stale"},
    )
    assert stale.status_code == 412

    role = client.post("/api/v1/roles", json={
        "org_unit_id": 1, "code": "TEMP", "name": "Temporary",
        "profile_id": profile["id"],
    }).json()
    referenced = client.delete(
        f"/api/v1/profiles/{profile['id']}",
        headers={"If-Match": str(updated.json()["version"]), "X-Change-Reason": "No longer needed"},
    )
    assert referenced.status_code == 409

    all_profile = _by_code(client, "/api/v1/profiles?limit=500")["ALL_PRIVS"]
    reassigned = client.put(
        f"/api/v1/roles/{role['id']}/profile",
        json={"profile_id": all_profile["id"]},
        headers={"If-Match": str(role["version"]), "X-Change-Reason": "Retire temporary profile"},
    )
    assert reassigned.status_code == 200
    deleted = client.delete(
        f"/api/v1/profiles/{profile['id']}",
        headers={"If-Match": str(updated.json()["version"]), "X-Change-Reason": "No longer needed"},
    )
    assert deleted.status_code == 204


def test_profile_assignment_is_role_only_and_exactly_one(client: TestClient):
    profile = _create_profile(client, "NO_DIRECT_ASSIGNMENT")
    user = client.post("/api/v1/users", json={
        "name": "No Profile User", "email": "no-profile@example.test", "profile_id": profile["id"],
    })
    org = client.post("/api/v1/org-units", json={
        "code": "NO-PROFILE", "name": "No Profile Unit", "profile_id": profile["id"],
    })
    assert user.status_code == 422
    assert org.status_code == 422

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        role_id = connection.execute("SELECT id FROM roles LIMIT 1").fetchone()[0]
        try:
            connection.execute("UPDATE roles SET profile_id=NULL WHERE id=%s", (role_id,))
        except psycopg.errors.NotNullViolation:
            connection.rollback()
        else:
            raise AssertionError("roles.profile_id accepted NULL")


def test_last_authorization_administrator_is_protected(client: TestClient):
    profiles = _by_code(client, "/api/v1/profiles?limit=500")
    all_profile = profiles["ALL_PRIVS"]
    privileges = _by_code(client, "/api/v1/privileges?limit=500")
    selected = [
        item["id"] for code, item in privileges.items()
        if code != "authorization.administer"
    ]
    denied = client.put(
        f"/api/v1/profiles/{all_profile['id']}/privileges",
        json={"privilege_ids": selected},
        headers={"If-Match": str(all_profile["version"]), "X-Change-Reason": "Continuity test"},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"] == "last_authorization_administrator"


def test_last_highest_clearance_governance_custodian_is_protected(
    client: TestClient, aggregation: dict,
):
    profiles = _by_code(client, "/api/v1/profiles?limit=500")
    levels = _by_code(client, "/api/v1/security-levels?limit=500")
    role = client.post("/api/v1/roles", json={
        "org_unit_id": 1,
        "code": "UNIVERSAL-CUSTODIAN",
        "name": "Universal Custodian",
        "profile_id": profiles["INFO_GOV_MGR"]["id"],
        "security_level_id": levels["TS"]["id"],
        "is_information_governance": True,
    }).json()
    assignment = client.post("/api/v1/user-role-assignments", json={
        "user_id": 1, "role_id": role["id"],
    })
    assert assignment.status_code == 201

    custodian_profile = profiles["INFO_GOV_MGR"]
    current_privileges = client.get(
        f"/api/v1/profiles/{custodian_profile['id']}/privileges"
    ).json()
    denied_profile_weakening = client.put(
        f"/api/v1/profiles/{custodian_profile['id']}/privileges",
        json={"privilege_ids": [
            item["id"] for item in current_privileges
            if item["code"] != "authorization.explain"
        ]},
        headers={
            "If-Match": str(custodian_profile["version"]),
            "X-Change-Reason": "Continuity test",
        },
    )
    assert denied_profile_weakening.status_code == 409
    assert denied_profile_weakening.json()["detail"] == "last_governance_custodian"

    denied = client.patch(
        f"/api/v1/roles/{role['id']}",
        json={"is_information_governance": False},
        headers={"If-Match": str(role["version"]), "X-Change-Reason": "Continuity test"},
    )
    assert denied.status_code == 409
    assert denied.json()["detail"] == "last_governance_custodian"

    refreshed = client.get(f"/api/v1/roles/{role['id']}").json()
    assignment_row = assignment.json()
    denied_assignment = client.delete(
        f"/api/v1/user-role-assignments/{assignment_row['id']}",
        headers={"If-Match": str(assignment_row["version"])},
    )
    assert denied_assignment.status_code == 409
    assert client.get(f"/api/v1/roles/{refreshed['id']}").json()["is_information_governance"] is True


def test_privilege_catalogue_is_runtime_read_only(client: TestClient):
    response = client.post("/api/v1/privileges", json={
        "code": "invented", "name": "Invented", "description": "No", "category": "administration",
    })
    assert response.status_code == 405
