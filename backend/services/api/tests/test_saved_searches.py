import os

import psycopg
from psycopg.types.json import Jsonb

from backend.services.api.authentication import hash_password


def _definition(*, maximum: int = 1000) -> dict:
    return {
        "schema_version": 1,
        "resource_type": "record",
        "max_results": maximum,
        "request": {
            "where": {"field": "title", "operator": "contains_ci", "value": "budget"},
            "sort": [{"field": "date_originated", "direction": "desc"}],
            "limit": 25,
            "offset": 0,
        },
    }


def _payload(**changes) -> dict:
    value = {
        "name": "Approved budgets",
        "category": "Finance",
        "description": "Current approved budget records",
        "definition": _definition(),
        "audience_mode": "private",
        "role_ids": [],
        "org_unit_ids": [],
    }
    value.update(changes)
    return value


def _restore_legacy_limit(saved_id: int, maximum: int) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("SELECT set_config('app.user_id','1',true), set_config('app.change_reason','Legacy test fixture',true)")
        connection.execute(
            "UPDATE saved_searches SET definition = definition || jsonb_build_object('max_results', %s::integer) WHERE id=%s",
            (maximum, saved_id),
        )


def test_owner_name_follows_viewer_language(client):
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("UPDATE users SET translations=%s WHERE id=1", (Jsonb({'ar': {'name': 'عمر إبراهيم'}}),))
        connection.execute("INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES (1,'ar','Asia/Dubai') ON CONFLICT(user_id) DO UPDATE SET language_tag='ar'")
    created = client.post('/api/v1/saved-searches', json=_payload()).json()
    saved_id = created['id']
    for value in (
        created,
        client.get(f'/api/v1/saved-searches/{saved_id}').json(),
        client.get('/api/v1/saved-searches').json()['items'][0],
        client.get('/api/v1/saved-searches/administration').json()['items'][0],
    ):
        assert value['owner']['localized']['name'] == 'عمر إبراهيم'
        assert 'translations' not in value['owner']
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("UPDATE user_preferences SET language_tag='en' WHERE user_id=1")
    owner = client.get(f'/api/v1/saved-searches/{saved_id}').json()['owner']
    assert owner['localized']['name'] == owner['name']


def test_create_canonicalize_update_history_and_delete(client):
    created = client.post("/api/v1/saved-searches", json=_payload())
    assert created.status_code == 201, created.text
    saved = created.json()
    assert saved["owner_user_id"] == 1
    assert saved["definition"]["request"]["sort"] == [
        {"field": "date_originated", "direction": "desc"},
        {"field": "id", "direction": "asc"},
    ]
    assert saved["capabilities"] == {
        "update": True, "manage_audience": True, "delete": True, "execute": True,
    }

    page = client.get("/api/v1/saved-searches", params={"scope": "owned"})
    assert page.status_code == 200
    assert page.json()["items"][0]["category"] == "Finance"

    updated = client.put(
        f"/api/v1/saved-searches/{saved['id']}", json=_payload(name="Renamed"),
        headers={"If-Match": str(saved["version"])},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == saved["version"] + 1
    stale = client.put(
        f"/api/v1/saved-searches/{saved['id']}", json=_payload(name="Stale"),
        headers={"If-Match": str(saved["version"]), "X-Change-Reason": "Stale change"},
    )
    assert stale.status_code == 409

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=psycopg.rows.dict_row) as connection:
        events = connection.execute(
            "SELECT operation,reason FROM event_history WHERE entity_type='saved_search' AND entity_id=%s ORDER BY id",
            (saved["id"],),
        ).fetchall()
    assert [event["operation"] for event in events] == ["CREATE", "UPDATE"]
    assert events[-1]["reason"] == "Updated saved search"

    deleted = client.delete(
        f"/api/v1/saved-searches/{saved['id']}",
        headers={"If-Match": str(updated.json()["version"]), "X-Change-Reason": "No longer required"},
    )
    assert deleted.status_code == 204


def test_definition_bounds_and_resource_validation(client):
    too_many = client.post("/api/v1/saved-searches", json=_payload(definition=_definition(maximum=5001)))
    assert too_many.status_code == 422
    invalid_field = _definition()
    invalid_field["request"]["where"]["field"] = "email"
    rejected = client.post("/api/v1/saved-searches", json=_payload(definition=invalid_field))
    assert rejected.status_code == 422
    runtime_debug = _definition()
    runtime_debug["request"]["debug"] = True
    rejected_debug = client.post("/api/v1/saved-searches", json=_payload(definition=runtime_debug))
    assert rejected_debug.status_code == 422


def test_execute_saved_search_uses_fresh_results_and_enforces_stored_cap(client, aggregation):
    for number, title in (("REC-101", "Budget alpha"), ("REC-102", "Budget beta"), ("REC-103", "Budget gamma")):
        response = client.post("/api/v1/records", json={
            "aggregation_id": aggregation["id"], "record_number": number, "title": title,
        })
        assert response.status_code == 201, response.text
    created = client.post("/api/v1/saved-searches", json=_payload(definition=_definition(maximum=2)))
    assert created.status_code == 201, created.text
    saved = created.json()
    assert "max_results" not in saved["definition"]
    assert saved["result_cap"] == 1000
    _restore_legacy_limit(saved["id"], 2)
    saved = client.get(f"/api/v1/saved-searches/{saved['id']}").json()

    first = client.post(f"/api/v1/saved-searches/{saved['id']}/execute", json={"limit": 25, "offset": 0})
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["total"] == 2
    assert result["returned"] == 2
    assert result["limit"] == 2
    assert result["saved_search"] == {
        "id": saved["id"], "name": "Approved budgets", "version": saved["version"],
        "resource_type": "record", "max_results": 2,
    }
    assert result["index_freshness"] == {"has_pending_content": False}

    beyond = client.post(f"/api/v1/saved-searches/{saved['id']}/execute", json={"offset": 2})
    assert beyond.status_code == 422
    assert beyond.json()["detail"]["code"] == "saved_search_result_limit_exceeded"

    added = client.post("/api/v1/records", json={
        "aggregation_id": aggregation["id"], "record_number": "REC-104", "title": "Budget delta",
    })
    assert added.status_code == 201
    fresh = client.post(f"/api/v1/saved-searches/{saved['id']}/execute", json={})
    assert fresh.status_code == 200
    assert fresh.json()["total"] == 2
    from backend.services.api.tests.test_application_settings import save
    assert save(client, {"SEARCH_RESULT_LIMIT": 1}).status_code == 200
    reduced = client.post(f"/api/v1/saved-searches/{saved['id']}/execute", json={})
    assert reduced.status_code == 200
    assert reduced.json()["result_cap"] == 1 and reduced.json()["returned"] == 1


def test_role_sharing_is_visible_but_does_not_grant_administration(client):
    password = "Saved-Search-Recipient-123!"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        profile_id = connection.execute(
            "INSERT INTO profiles(code,name) VALUES ('SAVED_SEARCH_READER','Saved search reader') RETURNING id"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO profile_privileges(profile_id,privilege_id)
               SELECT %s,id FROM privileges WHERE code='record.view'""", (profile_id,),
        )
        user_id = connection.execute(
            "INSERT INTO users(name,email) VALUES ('Search Recipient','search-recipient@test.invalid') RETURNING id"
        ).fetchone()[0]
        role_id = connection.execute(
            """INSERT INTO roles(org_unit_id,code,name,profile_id)
               VALUES (1,'saved-search-reader-role','Saved search reader role',%s) RETURNING id""", (profile_id,),
        ).fetchone()[0]
        connection.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)", (user_id, role_id))
        connection.execute(
            "INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES (%s,%s,false)",
            (user_id, hash_password(password)),
        )

    created = client.post("/api/v1/saved-searches", json=_payload(
        audience_mode="shared", role_ids=[role_id],
    ))
    assert created.status_code == 201, created.text
    saved_id = created.json()["id"]

    login = client.post("/api/v1/auth/login", json={
        "email": "search-recipient@test.invalid", "password": password,
    })
    assert login.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("erms_csrf")
    shared = client.get("/api/v1/saved-searches", params={"scope": "shared_with_me"})
    assert shared.status_code == 200
    assert [item["id"] for item in shared.json()["items"]] == [saved_id]
    assert shared.json()["items"][0]["capabilities"]["execute"] is True
    executed = client.post(f"/api/v1/saved-searches/{saved_id}/execute", json={})
    assert executed.status_code == 200, executed.text
    assert shared.json()["items"][0]["capabilities"]["update"] is False
    denied_update = client.put(
        f"/api/v1/saved-searches/{saved_id}", json=_payload(name="Recipient edit"),
        headers={"If-Match": str(created.json()["version"]), "X-Change-Reason": "Must fail"},
    )
    assert denied_update.status_code == 403
    assert client.get("/api/v1/saved-searches/administration").status_code == 403


def test_sharing_definition_does_not_grant_record_view(client):
    password = "Saved-Search-No-View-123!"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        profile_id = connection.execute(
            "INSERT INTO profiles(code,name) VALUES ('SAVED_SEARCH_NO_VIEW','Saved search no view') RETURNING id"
        ).fetchone()[0]
        user_id = connection.execute(
            "INSERT INTO users(name,email) VALUES ('No View Recipient','no-view-recipient@test.invalid') RETURNING id"
        ).fetchone()[0]
        role_id = connection.execute(
            """INSERT INTO roles(org_unit_id,code,name,profile_id)
               VALUES (1,'saved-search-no-view-role','Saved search no view role',%s) RETURNING id""",
            (profile_id,),
        ).fetchone()[0]
        connection.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)", (user_id, role_id))
        connection.execute(
            "INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES (%s,%s,false)",
            (user_id, hash_password(password)),
        )
    created = client.post("/api/v1/saved-searches", json=_payload(
        audience_mode="shared", role_ids=[role_id],
    ))
    assert created.status_code == 201, created.text
    login = client.post("/api/v1/auth/login", json={
        "email": "no-view-recipient@test.invalid", "password": password,
    })
    assert login.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("erms_csrf")
    denied = client.post(f"/api/v1/saved-searches/{created.json()['id']}/execute", json={})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "resource_view_required"


def test_information_governance_role_bypasses_saved_search_audience(client):
    password = "Saved-Search-Governance-123!"
    created = client.post("/api/v1/saved-searches", json=_payload())
    assert created.status_code == 201, created.text
    saved_id = created.json()["id"]
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        profile_id = connection.execute(
            "INSERT INTO profiles(code,name) VALUES ('SAVED_SEARCH_GOV','Saved search governance') RETURNING id"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO profile_privileges(profile_id,privilege_id)
               SELECT %s,id FROM privileges WHERE code='record.view'""", (profile_id,),
        )
        user_id = connection.execute(
            "INSERT INTO users(name,email) VALUES ('Governance Search User','governance-search@test.invalid') RETURNING id"
        ).fetchone()[0]
        role_id = connection.execute(
            """INSERT INTO roles(org_unit_id,code,name,profile_id,is_information_governance)
               VALUES (1,'saved-search-governance-role','Saved search governance role',%s,true) RETURNING id""",
            (profile_id,),
        ).fetchone()[0]
        connection.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)", (user_id, role_id))
        connection.execute(
            "INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES (%s,%s,false)",
            (user_id, hash_password(password)),
        )
    login = client.post("/api/v1/auth/login", json={
        "email": "governance-search@test.invalid", "password": password,
    })
    assert login.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("erms_csrf")
    assert client.get("/api/v1/saved-searches", params={"scope": "all"}).json()["items"] == []
    executed = client.post(f"/api/v1/saved-searches/{saved_id}/execute", json={})
    assert executed.status_code == 200, executed.text


def test_administration_filters_and_execution_does_not_create_history(client):
    private = client.post("/api/v1/saved-searches", json=_payload(
        name="Small finance search", category="Finance", definition=_definition(maximum=50),
    ))
    assert private.status_code == 201, private.text
    _restore_legacy_limit(private.json()["id"], 50)
    other = client.post("/api/v1/saved-searches", json=_payload(
        name="Large legal search", category="Legal", definition=_definition(maximum=2000),
    ))
    assert other.status_code == 201, other.text

    filtered = client.get("/api/v1/saved-searches/administration", params={
        "category": "finance", "max_results_min": 40, "max_results_max": 60,
    })
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["items"]] == [private.json()["id"]]
    invalid = client.get("/api/v1/saved-searches/administration", params={
        "max_results_min": 100, "max_results_max": 50,
    })
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "invalid_max_results_range"

    before = client.get("/api/v1/event-history", params={
        "entity_type": "saved_search", "entity_id": private.json()["id"],
    })
    executed = client.post(f"/api/v1/saved-searches/{private.json()['id']}/execute", json={})
    assert executed.status_code == 200
    after = client.get("/api/v1/event-history", params={
        "entity_type": "saved_search", "entity_id": private.json()["id"],
    })
    assert after.status_code == before.status_code
    if before.status_code == 200:
        assert after.json() == before.json()
