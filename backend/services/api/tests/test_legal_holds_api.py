from datetime import datetime, timedelta, timezone
import os

import psycopg
import pytest

from fastapi.testclient import TestClient
from backend.services.api.authentication import hash_password


def _create_hold(client: TestClient, owner_user_id: int = 1, *, preserve: bool = True) -> dict:
    now = datetime.now(timezone.utc)
    response = client.post("/api/v1/holds", json={
        "code": "LIT-2026-001", "name": "Litigation hold",
        "description": "Preserve the responsive material.",
        "valid_from": (now - timedelta(hours=1)).isoformat(),
        "valid_to": (now + timedelta(days=30)).isoformat(),
        "owner_user_id": owner_user_id,
        "preserve_resource_state": preserve,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_hold_lifecycle_held_items_capabilities_and_explainer(
    client: TestClient, aggregation: dict, record: dict,
):
    hold = _create_hold(client)
    assert hold["state"] == "active"
    assert hold["owner"] == {
        "id": 1, "name": "Test Administrator", "email": "admin@test.invalid", "status": "active",
        "localized": {"language_tag": "en", "name": "Test Administrator",
                      "description": None, "used_canonical_fallback": True},
    }
    assert hold["is_effective"] is True
    assert hold["capabilities"]["manage_held_items"] is True

    missing_reason = client.post(
        f"/api/v1/holds/{hold['id']}/held-items",
        json={"resource_type": "aggregation", "resource_id": aggregation["id"]},
    )
    assert missing_reason.status_code == 422
    assert missing_reason.json()["detail"]["code"] == "hold_change_reason_required"

    added = client.post(
        f"/api/v1/aggregations/{aggregation['id']}/holds",
        json={"hold_id": hold["id"]}, headers={"X-Change-Reason": "Preservation notice received"},
    )
    assert added.status_code == 201, added.text
    repeated = client.post(
        f"/api/v1/aggregations/{aggregation['id']}/holds",
        json={"hold_id": hold["id"]}, headers={"X-Change-Reason": "Repeat request"},
    )
    assert repeated.status_code == 201
    assert repeated.json()["id"] == added.json()["id"]

    effective = client.get(f"/api/v1/records/{record['id']}/effective-holds")
    assert effective.status_code == 200
    assert effective.json()[0]["source"] == "inherited"
    assert effective.json()[0]["code"] == "LIT-2026-001"

    capabilities = client.get(f"/api/v1/records/{record['id']}/capabilities").json()
    assert capabilities["capabilities"]["is_on_effective_hold"] is True
    assert capabilities["capabilities"]["effective_hold_count"] == 1
    assert capabilities["capabilities"]["delete"] is False
    assert capabilities["capability_reasons"]["delete"] == "effective_hold_prevents_deletion"

    explanation = client.post("/api/v1/authorization/explain", json={
        "resource_type": "record", "resource_id": record["id"], "operation": "record.delete",
    })
    assert explanation.status_code == 200, explanation.text
    body = explanation.json()
    assert body["allowed"] is False
    assert body["resource_state_constraints"][0]["kind"] == "effective_hold"
    assert body["resource_state_constraints"][0]["effect"] == "deletion"
    assert body["resource_state_constraints"][0]["holds"][0]["code"] == "LIT-2026-001"

    blocked = client.delete(f"/api/v1/records/{record['id']}", headers={"If-Match": str(record["version"])})
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "effective_hold_prevents_deletion"

    removed = client.delete(
        f"/api/v1/aggregations/{aggregation['id']}/holds",
        headers={"X-Change-Reason": "Matter released"},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["removed_hold_ids"] == [hold["id"]]
    assert removed.json()["remaining_effective_holds"] == []


def test_hold_update_requires_reason_and_version(client: TestClient):
    hold = _create_hold(client, preserve=False)
    response = client.patch(
        f"/api/v1/holds/{hold['id']}", json={"code": "RENAMED"},
        headers={"If-Match": str(hold["version"])},
    )
    assert response.status_code == 422
    updated = client.patch(
        f"/api/v1/holds/{hold['id']}", json={"code": "RENAMED"},
        headers={"If-Match": str(hold["version"]), "X-Change-Reason": "Correct matter code"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["code"] == "RENAMED"
    stale = client.patch(
        f"/api/v1/holds/{hold['id']}", json={"name": "Stale"},
        headers={"If-Match": str(hold["version"]), "X-Change-Reason": "Stale edit"},
    )
    assert stale.status_code == 409


def test_hold_candidate_search_and_atomic_bulk_add(
    client: TestClient, aggregation: dict, record: dict,
):
    hold = _create_hold(client)
    described = client.post("/api/v1/aggregations", json={
        "aggregation_number": "AGG-DESCRIPTION-ONLY",
        "title": "Unrelated heading",
        "description": "Material concerning the Falcon inquiry",
        "classification_id": 1,
    })
    assert described.status_code == 201, described.text
    description_match = client.get(
        f"/api/v1/holds/{hold['id']}/held-item-candidates", params={"q": "Falcon inquiry"},
    )
    assert description_match.status_code == 200, description_match.text
    assert description_match.json()["total"] == 1
    assert description_match.json()["items"][0]["description"] == "Material concerning the Falcon inquiry"
    candidates = client.get(
        f"/api/v1/holds/{hold['id']}/held-item-candidates",
        params={"q": aggregation["aggregation_number"]},
    )
    assert candidates.status_code == 200, candidates.text
    assert candidates.json()["total"] == 1
    assert candidates.json()["items"][0]["resource_type"] == "aggregation"

    missing_reason = client.post(
        f"/api/v1/holds/{hold['id']}/held-items/bulk",
        json={"held_items": [
            {"resource_type": "aggregation", "resource_id": aggregation["id"]},
            {"resource_type": "record", "resource_id": record["id"]},
        ]},
    )
    assert missing_reason.status_code == 422

    added = client.post(
        f"/api/v1/holds/{hold['id']}/held-items/bulk",
        json={"held_items": [
            {"resource_type": "aggregation", "resource_id": aggregation["id"]},
            {"resource_type": "record", "resource_id": record["id"]},
        ]},
        headers={"X-Change-Reason": "Bulk preservation scope import"},
    )
    assert added.status_code == 201, added.text
    assert added.json() == {"requested": 2, "added": 2, "already_held_items": 0}

    page = client.get(
        f"/api/v1/holds/{hold['id']}/held-items",
        params={"limit": 1, "sort": "number"},
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 2
    assert page.json()["returned"] == 1
    assert page.json()["items"][0]["security_level_name"]
    assert page.json()["items"][0]["security_level_code"]
    assignment = page.json()["items"][0]
    stale_remove = client.delete(
        f"/api/v1/holds/{hold['id']}/held-items/{assignment['resource_type']}/{assignment['resource_id']}",
        headers={"If-Match": str(assignment["version"] + 1), "X-Change-Reason": "Stale removal"},
    )
    assert stale_remove.status_code == 409
    removed = client.delete(
        f"/api/v1/holds/{hold['id']}/held-items/{assignment['resource_type']}/{assignment['resource_id']}",
        headers={"If-Match": str(assignment["version"]), "X-Change-Reason": "Scope corrected"},
    )
    assert removed.status_code == 204

    holds_page = client.get("/api/v1/holds", params={"limit": 1})
    assert holds_page.status_code == 200
    assert holds_page.json()["total"] >= 1
    assert holds_page.json()["items"][0]["owner"]["name"] == "Test Administrator"

    remaining = client.get(f"/api/v1/holds/{hold['id']}/held-item-candidates")
    assert remaining.status_code == 200
    keys = {(item["resource_type"], item["resource_id"]) for item in remaining.json()["items"]}
    assert (assignment["resource_type"], assignment["resource_id"]) in keys
    still_assigned = ({("aggregation", aggregation["id"]), ("record", record["id"])}
                      - {(assignment["resource_type"], assignment["resource_id"])})
    assert not (still_assigned & keys)


def test_information_governance_profile_can_manage_held_items_without_hold_administration(
    client: TestClient, aggregation: dict,
):
    hold = _create_hold(client)
    password = "Governance-Viewer-Test-123!"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        user_id = connection.execute(
            "INSERT INTO users(name,email) VALUES ('Governance Viewer','governance-viewer@test.invalid') RETURNING id"
        ).fetchone()[0]
        role_id = connection.execute(
            """INSERT INTO roles(org_unit_id,code,name,profile_id,is_information_governance)
                 VALUES (1,'hold-governance-viewer','Hold Governance Viewer',
                         (SELECT id FROM profiles WHERE code='INFO_GOV_OFFICER'),true) RETURNING id"""
        ).fetchone()[0]
        connection.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)",(user_id,role_id))
        connection.execute("INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES (%s,%s,false)",(user_id,hash_password(password)))
    login=client.post("/api/v1/auth/login",json={"email":"governance-viewer@test.invalid","password":password})
    assert login.status_code==200
    client.headers["X-CSRF-Token"]=client.cookies.get("erms_csrf")
    assert "holds.administer" not in login.json()["global_privileges"]
    assert "holds.held_items.manage_all" in login.json()["global_privileges"]
    visible=client.get(f"/api/v1/holds/{hold['id']}")
    assert visible.status_code==200
    assert visible.json()["capabilities"]["manage_held_items"] is True
    added=client.post(
        f"/api/v1/aggregations/{aggregation['id']}/holds",
        json={"hold_id":hold["id"]},
        headers={"X-Change-Reason":"Governance preservation direction"},
    )
    assert added.status_code==201, added.text
    removed=client.delete(
        f"/api/v1/aggregations/{aggregation['id']}/holds",
        headers={"X-Change-Reason":"Governance release direction"},
    )
    assert removed.status_code==200, removed.text
    assert removed.json()["removed_hold_ids"]==[hold["id"]]
    denied=client.post("/api/v1/holds",json={
        "code":"DENIED","name":"Must not create","valid_from":datetime.now(timezone.utc).isoformat(),
        "owner_user_id":user_id,
    })
    assert denied.status_code==403


def test_held_item_names_follow_language_and_translation_updates(client, aggregation, record):
    """Both card types resolve related names without stale locale/entity caches."""
    hold = _create_hold(client)
    response = client.post(
        f"/api/v1/holds/{hold['id']}/held-items/bulk",
        json={"held_items": [
            {"resource_type": "aggregation", "resource_id": aggregation["id"]},
            {"resource_type": "record", "resource_id": record["id"]},
        ]}, headers={"X-Change-Reason": "Test translated hold cards"},
    )
    assert response.status_code == 201, response.text
    url = f"/api/v1/holds/{hold['id']}/held-items"
    canonical = client.get(url).json()["items"]
    level_ids = {row["security_level_id"] for row in canonical}
    for resource, identifier, name in [
        ("users", 1, "مدير الاختبار"),
        *(("security-levels", identifier, "عام") for identifier in level_ids),
    ]:
        entity = client.get(f"/api/v1/{resource}/{identifier}").json()
        saved = client.patch(
            f"/api/v1/entity-translations/{resource}/{identifier}/ar",
            json={"name": name},
            headers={"If-Match": str(entity["version"]), "X-Change-Reason": "Translate related name"},
        )
        assert saved.status_code == 200, saved.text

    def language(tag):
        preference = client.get("/api/v1/preferences").json()
        saved = client.put("/api/v1/preferences", json={
            "language_tag": tag, "working_timezone": "Asia/Dubai",
        }, headers={"If-Match": str(preference["version"])})
        assert saved.status_code == 200, saved.text

    language("ar")
    for _ in range(2):
        page = client.get(url, params={"limit": 1, "offset": 1}).json()
        assert page["total"] == 2 and page["returned"] == 1
        rows = client.get(url).json()["items"]
        assert {row["resource_type"] for row in rows} == {"record", "aggregation"}
        assert all(row["assigned_by_name"] == "مدير الاختبار" for row in rows)
        assert all(row["security_level_name"] == "عام" for row in rows)
    user = client.get("/api/v1/users/1").json()
    updated = client.patch("/api/v1/entity-translations/users/1/ar", json={"name": "مدير محدث"},
        headers={"If-Match": str(user["version"]), "X-Change-Reason": "Update translated name"})
    assert updated.status_code == 200, updated.text
    assert all(row["assigned_by_name"] == "مدير محدث" for row in client.get(url).json()["items"])
    language("en")
    restored = client.get(url).json()["items"]
    assert [(r["assigned_by_name"], r["security_level_name"]) for r in restored] == [
        (r["assigned_by_name"], r["security_level_name"]) for r in canonical
    ]


@pytest.mark.parametrize("session_status", ["completed", "failed", "uploading"])
def test_held_upload_cleanup_and_table_specific_trigger_fields(client, record, session_status):
    from psycopg.rows import dict_row
    from backend.services.api.content_cleanup import cleanup_content

    uploaded = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": "1"},
        files={"file": ("held.txt", b"preserve", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    component = uploaded.json()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        content_set = connection.execute(
            "SELECT active_content_set_id FROM digital_components WHERE id=%s", (component['id'],)
        ).fetchone()[0]
        session = connection.execute(
            """INSERT INTO content_upload_sessions(digital_component_id,content_set_id,status,expires_at)
               VALUES(%s,%s,%s,CURRENT_TIMESTAMP - interval '1 day') RETURNING id""",
            (component['id'], content_set, session_status),
        ).fetchone()[0]
    hold = _create_hold(client)
    assigned = client.post(
        f"/api/v1/records/{record['id']}/holds", json={"hold_id": hold['id']},
        headers={"X-Change-Reason": "Preserve uploaded evidence"},
    )
    assert assigned.status_code == 201, assigned.text
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        for statement, reason in [
            ("DELETE FROM content_upload_sessions WHERE id=%s", 'effective_hold_prevents_component_deletion'),
            ("UPDATE content_upload_sessions SET status='expired' WHERE id=%s", 'effective_hold_prevents_component_replacement'),
            ("UPDATE digital_components SET component_order=2 WHERE id=%s", 'effective_hold_prevents_component_reordering'),
        ]:
            with pytest.raises(psycopg.errors.RaiseException, match=reason):
                with connection.transaction():
                    connection.execute(statement, (component['id'] if 'digital_components SET' in statement else session,))
        cleanup_content(connection)
        assert connection.execute("SELECT id FROM content_upload_sessions WHERE id=%s", (session,)).fetchone()
    removed = client.delete(
        f"/api/v1/records/{record['id']}/holds",
        headers={"X-Change-Reason": "Release preservation"},
    )
    assert removed.status_code == 200, removed.text
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        cleanup_content(connection)
        assert connection.execute("SELECT id FROM content_upload_sessions WHERE id=%s", (session,)).fetchone() is None
