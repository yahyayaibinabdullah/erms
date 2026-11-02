import os

import psycopg
import pytest
from fastapi.testclient import TestClient


def levels(client: TestClient) -> dict[str, dict]:
    response = client.get("/api/v1/security-levels")
    assert response.status_code == 200, response.text
    return {item["code"]: item for item in response.json()}


def test_assignable_levels_follow_clearance_and_parent(client, aggregation):
    catalogue = levels(client)
    def choices(**params):
        response = client.get('/api/v1/security-levels/page', params={'assignable': True, **params})
        assert response.status_code == 200, response.text
        return response.json()
    assert [item['code'] for item in choices()['items']] == ['G']
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute('UPDATE roles SET security_level_id=%s WHERE id=1', (catalogue['S']['id'],))
    assert [item['code'] for item in choices()['items']] == ['G', 'R', 'S']
    assert [item['code'] for item in choices(parent_aggregation_id=aggregation['id'])['items']] == ['G']
    # Filtering precedes pagination/counting and applies equally to text searches.
    assert choices(q='TS')['total'] == 0
    page = choices(limit=1, offset=2)
    assert page['total'] == 3 and page['items'][0]['code'] == 'S'
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute('UPDATE user_role_assignments SET valid_until=CURRENT_TIMESTAMP WHERE user_id=1')
    assert choices()['items'] == []


def test_assignable_aggregation_update_respects_contents(client, aggregation, record):
    catalogue = levels(client)
    with psycopg.connect(os.environ['DATABASE_URL']) as connection:
        connection.execute('UPDATE roles SET security_level_id=%s WHERE id=1', (catalogue['TS']['id'],))
        connection.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s', (catalogue['S']['id'], aggregation['id']))
        connection.execute('UPDATE records SET security_level_id=%s WHERE id=%s', (catalogue['R']['id'], record['id']))
    response = client.get('/api/v1/security-levels/page', params={'assignable': True, 'aggregation_id': aggregation['id']})
    assert response.status_code == 200, response.text
    assert response.json()['minimum_level'] == 50
    assert [item['code'] for item in response.json()['items']] == ['R', 'S', 'TS']


def test_seeded_catalogue_and_lowest_level_defaults(client: TestClient, aggregation: dict, record: dict):
    catalogue = levels(client)
    assert [(code, catalogue[code]["level_number"]) for code in ("G", "R", "S", "TS")] == [
        ("G", 0), ("R", 50), ("S", 75), ("TS", 100),
    ]
    assert aggregation["security_level_id"] == catalogue["G"]["id"]
    assert record["security_level_id"] == catalogue["G"]["id"]
    role = client.get("/api/v1/roles/1")
    assert role.status_code == 200
    assert role.json()["security_level_id"] == catalogue["G"]["id"]
    assert catalogue["G"]["roles_assigned_count"] >= 1
    assert catalogue["G"]["aggregation_count"] >= 1
    assert catalogue["G"]["record_count"] >= 1
    for level in (catalogue[code] for code in ("G", "R", "S", "TS")):
        history = client.get(f"/api/v1/security-levels/{level['id']}/history")
        assert history.status_code == 200, history.text
        assert sum(event["operation"] == "CREATE" for event in history.json()) == 1


def test_security_level_history_uses_standard_event_history(client: TestClient):
    created = client.post("/api/v1/security-levels", json={
        "code": "HIST",
        "name": "History test level",
        "level_number": 60,
        "prevents_disposition": False,
    })
    assert created.status_code == 201, created.text

    history = client.get(f"/api/v1/security-levels/{created.json()['id']}/history")
    assert history.status_code == 200, history.text
    assert any(
        event["entity_type"] == "security_level"
        and event["entity_id"] == created.json()["id"]
        for event in history.json()
    )


def test_child_aggregation_defaults_to_parent_but_record_defaults_to_baseline(
    client: TestClient, aggregation: dict
):
    catalogue = levels(client)
    # This test intentionally creates Secret information, so its test actor must
    # first hold a clearance at least as high as the requested resource level.
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "UPDATE roles SET security_level_id=%s WHERE id=1", (catalogue["TS"]["id"],),
        )
    upgraded = client.patch(
        f"/api/v1/aggregations/{aggregation['id']}",
        json={"security_level_id": catalogue["S"]["id"]},
        headers={"If-Match": str(aggregation["version"]), "X-Change-Reason": "Classification changed"},
    )
    assert upgraded.status_code == 200, upgraded.text
    child = client.post("/api/v1/aggregations", json={
        "parent_aggregation_id": aggregation["id"],
        "aggregation_number": "AGG-CHILD",
        "title": "Inherited parent level",
    })
    assert child.status_code == 201, child.text
    assert child.json()["security_level_id"] == catalogue["S"]["id"]
    created_record = client.post("/api/v1/records", json={
        "aggregation_id": aggregation["id"], "record_number": "REC-G", "title": "Baseline",
    })
    assert created_record.status_code == 201, created_record.text
    assert created_record.json()["security_level_id"] == catalogue["G"]["id"]


def test_parent_must_not_be_lower_than_child_and_lowering_requires_reason(
    client: TestClient, aggregation: dict, record: dict
):
    catalogue = levels(client)
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("UPDATE roles SET security_level_id=%s WHERE id=1", (catalogue["TS"]["id"],))
    invalid = client.patch(
        f"/api/v1/records/{record['id']}",
        json={"security_level_id": catalogue["R"]["id"]},
        headers={"If-Match": str(record["version"]), "X-Change-Reason": "Classification changed"},
    )
    assert invalid.status_code == 409
    parent = client.patch(
        f"/api/v1/aggregations/{aggregation['id']}",
        json={"security_level_id": catalogue["R"]["id"]},
        headers={"If-Match": str(aggregation["version"]), "X-Change-Reason": "Classification changed"},
    )
    assert parent.status_code == 200, parent.text
    record = client.get(f"/api/v1/records/{record['id']}").json()
    raised = client.patch(
        f"/api/v1/records/{record['id']}",
        json={"security_level_id": catalogue["R"]["id"]},
        headers={"If-Match": str(record["version"]), "X-Change-Reason": "Classification changed"},
    )
    assert raised.status_code == 200, raised.text
    no_reason = client.patch(
        f"/api/v1/records/{record['id']}",
        json={"security_level_id": catalogue["G"]["id"]},
        headers={"If-Match": str(raised.json()["version"])},
    )
    assert no_reason.status_code == 422
    lowered = client.patch(
        f"/api/v1/records/{record['id']}",
        json={"security_level_id": catalogue["G"]["id"]},
        headers={"If-Match": str(raised.json()["version"]), "X-Change-Reason": "Reclassified"},
    )
    assert lowered.status_code == 200, lowered.text
    history = client.get(f"/api/v1/records/{record['id']}/history").json()
    assert "SECURITY_LEVEL_UPGRADED" in {event["operation"] for event in history}
    assert "SECURITY_LEVEL_DOWNGRADED" in {event["operation"] for event in history}


def test_preview_and_apply_can_raise_ancestors_atomically(client: TestClient, aggregation: dict):
    catalogue = levels(client)
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("UPDATE roles SET security_level_id=%s WHERE id=1", (catalogue["TS"]["id"],))
    child = client.post("/api/v1/aggregations", json={
        "parent_aggregation_id": aggregation["id"],
        "aggregation_number": "AGG-CHILD", "title": "Child",
    }).json()
    preview_payload = {
        "resource_type": "aggregation", "resource_id": child["id"],
        "target_security_level_id": catalogue["TS"]["id"],
        "remedy": "raise_ancestors",
    }
    preview = client.post("/api/v1/security-level-changes/preview", json=preview_payload)
    assert preview.status_code == 200, preview.text
    assert "preview_token" not in preview.json()
    assert preview.json()["conflict"] is True
    assert [row["id"] for row in preview.json()["affected_aggregations"]] == [aggregation["id"]]
    applied = client.post(
        "/api/v1/security-level-changes/apply",
        json={
            **preview_payload,
            "reviewed_versions": preview.json()["reviewed_versions"],
        },
        headers={"X-Change-Reason": "Required classification"},
    )
    assert applied.status_code == 200, applied.text
    assert client.get(f"/api/v1/aggregations/{aggregation['id']}").json()["security_level_id"] == catalogue["TS"]["id"]
    assert client.get(f"/api/v1/aggregations/{child['id']}").json()["security_level_id"] == catalogue["TS"]["id"]


def test_review_then_apply_changes_only_root_aggregation_from_general_to_restricted(
    client: TestClient, aggregation: dict,
):
    catalogue = levels(client)
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "UPDATE roles SET security_level_id=%s WHERE id=1",
            (catalogue["TS"]["id"],),
        )
    for suffix in ("1", "2"):
        created = client.post(
            "/api/v1/records",
            json={
                "aggregation_id": aggregation["id"],
                "record_number": f"{aggregation['aggregation_number']}.{suffix}",
                "title": f"Contained record {suffix}",
            },
        )
        assert created.status_code == 201, created.text

    current = client.get(f"/api/v1/aggregations/{aggregation['id']}").json()
    closed = client.patch(
        f"/api/v1/aggregations/{aggregation['id']}",
        json={"date_closed": current["date_created"]},
        headers={"If-Match": str(current["version"])},
    )
    assert closed.status_code == 200, closed.text

    preview_payload = {
        "resource_type": "aggregation",
        "resource_id": aggregation["id"],
        "target_security_level_id": catalogue["R"]["id"],
        "remedy": "none",
    }
    preview = client.post(
        "/api/v1/security-level-changes/preview", json=preview_payload,
    )
    assert preview.status_code == 200, preview.text
    reviewed = preview.json()
    assert reviewed["conflict"] is False
    assert reviewed["affected_aggregations"] == []
    assert reviewed["affected_records"] == []
    assert "preview_token" not in reviewed

    applied = client.post(
        "/api/v1/security-level-changes/apply",
        json={
            **preview_payload,
            "reviewed_versions": reviewed["reviewed_versions"],
        },
        headers={"X-Change-Reason": "Archive security development"},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["resource"]["security_level_id"] == catalogue["R"]["id"]

    records = client.get(
        f"/api/v1/records?aggregation_id={aggregation['id']}"
    )
    assert records.status_code == 200, records.text
    assert len(records.json()) == 2
    assert {
        row["security_level_id"] for row in records.json()
    } == {catalogue["G"]["id"]}


def test_apply_rejects_versions_that_changed_after_review(
    client: TestClient, aggregation: dict,
):
    catalogue = levels(client)
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "UPDATE roles SET security_level_id=%s WHERE id=1",
            (catalogue["TS"]["id"],),
        )
    preview_payload = {
        "resource_type": "aggregation",
        "resource_id": aggregation["id"],
        "target_security_level_id": catalogue["R"]["id"],
        "remedy": "none",
    }
    preview = client.post(
        "/api/v1/security-level-changes/preview", json=preview_payload,
    )
    assert preview.status_code == 200, preview.text

    changed = client.patch(
        f"/api/v1/aggregations/{aggregation['id']}",
        json={"title": "Changed after review"},
        headers={"If-Match": str(aggregation["version"])},
    )
    assert changed.status_code == 200, changed.text

    stale = client.post(
        "/api/v1/security-level-changes/apply",
        json={
            **preview_payload,
            "reviewed_versions": preview.json()["reviewed_versions"],
        },
        headers={"X-Change-Reason": "Required classification"},
    )
    assert stale.status_code == 412, stale.text
    assert (
        client.get(f"/api/v1/aggregations/{aggregation['id']}").json()[
            "security_level_id"
        ]
        == catalogue["G"]["id"]
    )


SECURITY_LEVEL_CODES = ("G", "R", "S", "TS")
HIERARCHY_REMEDIES = ("none", "raise_ancestors", "downgrade_subtree")
SECURITY_CHANGE_MATRIX = [
    pytest.param(resource_type, source, target, remedy, lifecycle_state,
                 id=f"{lifecycle_state}-{resource_type}-{source}-to-{target}-{remedy}")
    for resource_type in ("aggregation", "record")
    for source in SECURITY_LEVEL_CODES
    for target in SECURITY_LEVEL_CODES
    for remedy in HIERARCHY_REMEDIES
    for lifecycle_state in ("open", "closed")
]


@pytest.mark.parametrize(
    ("resource_type", "source_code", "target_code", "remedy", "lifecycle_state"),
    SECURITY_CHANGE_MATRIX,
)
def test_security_level_review_apply_covers_every_level_and_hierarchy_scope(
    client: TestClient,
    aggregation: dict,
    resource_type: str,
    source_code: str,
    target_code: str,
    remedy: str,
    lifecycle_state: str,
):
    """Cover every G/R/S/TS transition, hierarchy remedy, and lifecycle state."""
    catalogue = levels(client)
    level_rank = {
        code: catalogue[code]["level_number"] for code in SECURITY_LEVEL_CODES
    }
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "UPDATE roles SET security_level_id=%s WHERE id=1",
            (catalogue["TS"]["id"],),
        )

    child_response = client.post(
        "/api/v1/aggregations",
        json={
            "parent_aggregation_id": aggregation["id"],
            "aggregation_number": "MATRIX-CHILD",
            "title": "Matrix child",
        },
    )
    assert child_response.status_code == 201, child_response.text
    child = child_response.json()
    grandchild_response = client.post(
        "/api/v1/aggregations",
        json={
            "parent_aggregation_id": child["id"],
            "aggregation_number": "MATRIX-GRANDCHILD",
            "title": "Matrix grandchild",
        },
    )
    assert grandchild_response.status_code == 201, grandchild_response.text
    grandchild = grandchild_response.json()
    record_response = client.post(
        "/api/v1/records",
        json={
            "aggregation_id": grandchild["id"],
            "record_number": "MATRIX-RECORD",
            "title": "Matrix record",
        },
    )
    assert record_response.status_code == 201, record_response.text
    record = record_response.json()

    source_id = catalogue[source_code]["id"]
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        # Raising parents before descendants preserves the hierarchy while the
        # matrix fixture is moved from the G seed level to its source level.
        connection.execute(
            "UPDATE aggregations SET security_level_id=%s WHERE id=%s",
            (source_id, aggregation["id"]),
        )
        connection.execute(
            "UPDATE aggregations SET security_level_id=%s WHERE id=%s",
            (source_id, child["id"]),
        )
        connection.execute(
            "UPDATE aggregations SET security_level_id=%s WHERE id=%s",
            (source_id, grandchild["id"]),
        )
        connection.execute(
            "UPDATE records SET security_level_id=%s WHERE id=%s",
            (source_id, record["id"]),
        )

    if lifecycle_state == "closed":
        current = client.get(f"/api/v1/aggregations/{aggregation['id']}").json()
        closed = client.patch(
            f"/api/v1/aggregations/{aggregation['id']}",
            json={"date_closed": current["date_created"]},
            headers={"If-Match": str(current["version"])},
        )
        assert closed.status_code == 200, closed.text

    source_rank = level_rank[source_code]
    target_rank = level_rank[target_code]
    if resource_type == "aggregation":
        resource_id = child["id"]
        conflict = target_rank != source_rank
        resolving_remedy = (
            "raise_ancestors" if target_rank > source_rank
            else "downgrade_subtree" if target_rank < source_rank
            else None
        )
    else:
        resource_id = record["id"]
        conflict = target_rank > source_rank
        resolving_remedy = "raise_ancestors" if conflict else None

    payload = {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "target_security_level_id": catalogue[target_code]["id"],
        "remedy": remedy,
    }
    preview_response = client.post(
        "/api/v1/security-level-changes/preview", json=payload,
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["conflict"] is conflict
    assert "preview_token" not in preview

    expected_aggregation_impact = 0
    expected_record_impact = 0
    if remedy == "raise_ancestors" and target_rank > source_rank:
        expected_aggregation_impact = 1 if resource_type == "aggregation" else 3
    elif (
        resource_type == "aggregation"
        and remedy == "downgrade_subtree"
        and target_rank < source_rank
    ):
        expected_aggregation_impact = 2
        expected_record_impact = 1
    assert len(preview["affected_aggregations"]) == expected_aggregation_impact
    assert len(preview["affected_records"]) == expected_record_impact

    should_apply = not conflict or remedy == resolving_remedy
    apply_response = client.post(
        "/api/v1/security-level-changes/apply",
        json={**payload, "reviewed_versions": preview["reviewed_versions"]},
        headers={"X-Change-Reason": "Complete security-level matrix"},
    )
    assert apply_response.status_code == (200 if should_apply else 409), (
        apply_response.text
    )

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        aggregation_levels = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT id,security_level_id FROM aggregations WHERE id=ANY(%s)",
                ([aggregation["id"], child["id"], grandchild["id"]],),
            ).fetchall()
        }
        record_level = connection.execute(
            "SELECT security_level_id FROM records WHERE id=%s", (record["id"],)
        ).fetchone()[0]

    target_id = catalogue[target_code]["id"]
    if not should_apply:
        assert set(aggregation_levels.values()) == {source_id}
        assert record_level == source_id
    elif resource_type == "aggregation" and target_rank > source_rank:
        assert aggregation_levels[aggregation["id"]] == target_id
        assert aggregation_levels[child["id"]] == target_id
        assert aggregation_levels[grandchild["id"]] == source_id
        assert record_level == source_id
    elif resource_type == "aggregation" and target_rank < source_rank:
        assert aggregation_levels[aggregation["id"]] == source_id
        assert aggregation_levels[child["id"]] == target_id
        assert aggregation_levels[grandchild["id"]] == target_id
        assert record_level == target_id
    elif resource_type == "aggregation":
        assert set(aggregation_levels.values()) == {source_id}
        assert record_level == source_id
    elif target_rank > source_rank:
        assert set(aggregation_levels.values()) == {target_id}
        assert record_level == target_id
    else:
        assert set(aggregation_levels.values()) == {source_id}
        assert record_level == target_id


def test_referenced_and_baseline_levels_cannot_be_deleted(client: TestClient):
    catalogue = levels(client)
    baseline = client.delete(
        f"/api/v1/security-levels/{catalogue['G']['id']}",
        headers={"If-Match": str(catalogue["G"]["version"])},
    )
    assert baseline.status_code == 409
    referenced = client.delete(
        f"/api/v1/security-levels/{catalogue['R']['id']}",
        headers={"If-Match": str(catalogue["R"]["version"])},
    )
    assert referenced.status_code == 204
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        role_id = connection.execute("SELECT id FROM roles LIMIT 1").fetchone()[0]
        connection.execute(
            "UPDATE roles SET security_level_id=%s WHERE id=%s",
            (catalogue["S"]["id"], role_id),
        )
    refreshed = client.get(f"/api/v1/security-levels/{catalogue['S']['id']}").json()
    denied = client.delete(
        f"/api/v1/security-levels/{refreshed['id']}",
        headers={"If-Match": str(refreshed["version"])},
    )
    assert denied.status_code == 409
