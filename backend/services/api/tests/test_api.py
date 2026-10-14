import hashlib
import os
from pathlib import Path
import subprocess
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.rows import dict_row
from fastapi.testclient import TestClient

from backend.services.api.content_cleanup import cleanup_content
from backend.services.api import document_conversion

from backend.services.api.config import load_environment


def test_real_environment_overrides_dotenv(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PRECEDENCE_TEST=from-dotenv\n")
    monkeypatch.setenv("PRECEDENCE_TEST", "from-environment")

    load_environment(env_file)

    assert os.environ["PRECEDENCE_TEST"] == "from-environment"


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["full_text_search_enabled"] is True
    assert body["content_indexing_scheduling_enabled"] is True
    assert body["localization"]["ready"] is True


def test_event_history_operations_are_discovered_from_audit_data(client: TestClient):
    response = client.get("/api/v1/event-history/operations")

    assert response.status_code == 200
    operations = response.json()
    assert operations == sorted(set(operations))
    assert "CREATE" in operations
    assert "AUTHENTICATION_SUCCEEDED" in operations


def test_event_history_filter_options_are_discovered_from_audit_data(client: TestClient):
    response = client.get("/api/v1/event-history/filter-options")

    assert response.status_code == 200
    options = response.json()
    assert set(options) == {"entity_types", "operations", "sources", "actor_types"}
    assert "user" in options["entity_types"]
    assert "CREATE" in options["operations"]
    assert "AUTHENTICATION_SUCCEEDED" in options["operations"]
    for values in options.values():
        assert values == sorted(set(values))


def test_aggregation_crud_and_hierarchy(client: TestClient, aggregation: dict):
    child_response = client.post(
        "/api/v1/aggregations",
        json={
            "parent_aggregation_id": aggregation["id"],
            "aggregation_number": "AGG-002",
            "title": "Child aggregation",
        },
    )
    assert child_response.status_code == 201
    child = child_response.json()
    assert child["date_opened"] == child["date_created"]

    response = client.get(
        "/api/v1/aggregations",
        params={"parent_aggregation_id": aggregation["id"]},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [child["id"]]

    response = client.patch(
        f"/api/v1/aggregations/{child['id']}",
        json={"description": "Updated description"},
        headers={"If-Match": str(child["version"])},
    )
    assert response.status_code == 200
    assert response.json()["description"] == "Updated description"
    child = response.json()

    response = client.patch(
        f"/api/v1/aggregations/{aggregation['id']}",
        json={"parent_aggregation_id": child["id"]},
        headers={"If-Match": str(aggregation["version"])},
    )
    assert response.status_code == 409

    assert client.delete(f"/api/v1/aggregations/{child['id']}", headers={"If-Match": str(child["version"])}).status_code == 204
    assert client.get(f"/api/v1/aggregations/{child['id']}").status_code == 404


def test_medium_hierarchy_creation_and_empty_only_changes(client: TestClient):
    physical = client.post("/api/v1/aggregations", json={
        "aggregation_number": "PHY-001", "title": "Physical root",
        "classification_id": 1, "medium": "physical",
    }).json()
    assert physical["medium"] == "physical"

    child_response = client.post("/api/v1/aggregations", json={
        "parent_aggregation_id": physical["id"], "aggregation_number": "PHY-002",
        "title": "Physical child", "medium": "digital",
    })
    assert child_response.status_code == 422
    assert child_response.json()["detail"]["code"] == "aggregation_medium_mismatch"

    child = client.post("/api/v1/aggregations", json={
        "parent_aggregation_id": physical["id"], "aggregation_number": "PHY-003",
        "title": "Derived physical child",
    }).json()
    assert child["medium"] == "physical"

    record_response = client.post("/api/v1/records", json={
        "aggregation_id": physical["id"], "record_number": "PHY-R-1",
        "title": "Wrong digital record", "medium": "digital",
    })
    assert record_response.status_code == 422
    assert record_response.json()["detail"]["code"] == "record_medium_not_allowed_by_parent"

    change_response = client.patch(
        f"/api/v1/aggregations/{physical['id']}", json={"medium": "digital"},
        headers={"If-Match": str(physical["version"])},
    )
    assert change_response.status_code == 422
    assert change_response.json()["detail"]["code"] == "medium_change_requires_empty_aggregation"


def test_mixed_aggregation_accepts_every_record_medium(client: TestClient, aggregation: dict):
    assert aggregation["medium"] == "mixed"
    for index, medium in enumerate(("digital", "physical", "mixed"), 1):
        response = client.post("/api/v1/records", json={
            "aggregation_id": aggregation["id"], "record_number": f"MIX-{index}",
            "title": medium.title(), "medium": medium,
        })
        assert response.status_code == 201, response.text
        assert response.json()["medium"] == medium


def test_physical_record_rejects_components_and_reports_capability_reason(
    client: TestClient, aggregation: dict,
):
    record = client.post("/api/v1/records", json={
        "aggregation_id": aggregation["id"], "record_number": "PHYSICAL-1",
        "title": "Paper file", "medium": "physical",
    }).json()
    capabilities = client.get(f"/api/v1/records/{record['id']}/capabilities").json()
    assert capabilities["capabilities"]["add_component"] is False
    assert capabilities["capability_reasons"]["add_component"] == (
        "physical_record_disallows_digital_components"
    )

    response = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": "1"},
        files={"file": ("scan.pdf", b"scan", "application/pdf")},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == (
        "physical_record_disallows_digital_components"
    )


def test_record_medium_change_requires_reason_and_no_components(
    client: TestClient, aggregation: dict,
):
    record = client.post("/api/v1/records", json={
        "aggregation_id": aggregation["id"], "record_number": "MEDIUM-CHANGE-1",
        "title": "Convertible", "medium": "digital",
    }).json()
    missing_reason = client.patch(
        f"/api/v1/records/{record['id']}", json={"medium": "physical"},
        headers={"If-Match": str(record["version"])},
    )
    assert missing_reason.status_code == 422
    assert missing_reason.json()["detail"]["code"] == "medium_change_reason_required"

    changed = client.patch(
        f"/api/v1/records/{record['id']}", json={"medium": "physical"},
        headers={"If-Match": str(record["version"]), "X-Change-Reason": "Paper original received"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["medium"] == "physical"
    history = client.get(f"/api/v1/records/{record['id']}/history").json()
    event = next(item for item in history if item["operation"] == "MEDIUM_CHANGED")
    assert event["reason"] == "Paper original received"

    digital = client.post("/api/v1/records", json={
        "aggregation_id": aggregation["id"], "record_number": "MEDIUM-CHANGE-2",
        "title": "Has content", "medium": "digital",
    }).json()
    uploaded = client.post(
        f"/api/v1/records/{digital['id']}/digital-components/upload",
        data={"component_order": "1"}, files={"file": ("file.txt", b"content", "text/plain")},
    )
    assert uploaded.status_code == 201
    rejected = client.patch(
        f"/api/v1/records/{digital['id']}", json={"medium": "physical"},
        headers={"If-Match": str(digital["version"]), "X-Change-Reason": "Wrong medium"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "physical_record_has_digital_components"


def test_physical_draft_rejects_staging_and_staged_draft_cannot_become_physical(
    client: TestClient, aggregation: dict,
):
    physical = client.post("/api/v1/record-drafts", json={
        "aggregation_id": aggregation["id"], "medium": "physical",
    }).json()
    rejected = client.post(
        f"/api/v1/record-drafts/{physical['id']}/components",
        data={"component_order": "1"}, files={"file": ("scan.pdf", b"scan", "application/pdf")},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "physical_record_disallows_digital_components"

    digital = client.post("/api/v1/record-drafts", json={
        "aggregation_id": aggregation["id"], "medium": "digital",
    }).json()
    staged = client.post(
        f"/api/v1/record-drafts/{digital['id']}/components",
        data={"component_order": "1"}, files={"file": ("born-digital.txt", b"data", "text/plain")},
    )
    assert staged.status_code == 201
    change = client.patch(
        f"/api/v1/record-drafts/{digital['id']}", json={"medium": "physical"},
    )
    assert change.status_code == 422
    assert change.json()["detail"]["code"] == "physical_record_has_staged_components"


def test_vital_status_is_governed_and_blocks_resource_and_parent_deletion(client: TestClient, aggregation: dict):
    record = client.post("/api/v1/records", json={
        "aggregation_id": aggregation["id"], "record_number": "VITAL-1", "title": "Vital record",
    }).json()
    changed = client.post(f"/api/v1/records/{record['id']}/vital-status", json={
        "is_vital": True, "reason": "Required for service recovery",
    }, headers={"If-Match": str(record["version"])})
    assert changed.status_code == 200, changed.text
    assert changed.json()["is_vital"] is True
    assert client.delete(f"/api/v1/records/{record['id']}", headers={"If-Match": str(changed.json()["version"])}).status_code == 409
    assert client.delete(f"/api/v1/aggregations/{aggregation['id']}", headers={"If-Match": str(aggregation["version"])}).status_code == 409
    history = client.get(f"/api/v1/records/{record['id']}/history").json()
    assert any(item["operation"] == "VITAL_STATUS_CHANGED" for item in history)


def test_review_dates_must_be_future_but_can_be_cleared(client: TestClient, aggregation: dict):
    rejected = client.post(
        f"/api/v1/aggregations/{aggregation['id']}/review-date",
        json={"date_of_next_review": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), "reason": "Schedule review"},
        headers={"If-Match": str(aggregation["version"])},
    )
    assert rejected.status_code == 422
    future = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    scheduled = client.post(
        f"/api/v1/aggregations/{aggregation['id']}/review-date",
        json={"date_of_next_review": future, "reason": "Schedule review"}, headers={"If-Match": str(aggregation["version"])},
    )
    assert scheduled.status_code == 200, scheduled.text
    closed = client.patch(
        f"/api/v1/aggregations/{aggregation['id']}",
        json={"date_closed": datetime.now(timezone.utc).isoformat()},
        headers={"If-Match": str(scheduled.json()["version"])},
    )
    assert closed.status_code == 200, closed.text
    cleared = client.post(
        f"/api/v1/aggregations/{aggregation['id']}/review-date",
        json={"date_of_next_review": None, "reason": "Review no longer required"}, headers={"If-Match": str(closed.json()["version"])},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["date_of_next_review"] is None


def test_governed_locations_inherit_and_can_change_on_closed_aggregation(client: TestClient, aggregation: dict):
    changed = client.post(
        f"/api/v1/aggregations/{aggregation['id']}/location",
        json={"assigned_location": "STORE-A-01", "current_location": "DESK-07", "reason": "Initial physical placement"},
        headers={"If-Match": str(aggregation["version"])},
    )
    assert changed.status_code == 200, changed.text
    child = client.post("/api/v1/aggregations", json={
        "parent_aggregation_id": aggregation["id"], "aggregation_number": "LOC-CHILD", "title": "Location child",
    }).json()
    assert child["effective_assigned_location"] == "STORE-A-01"
    assert child["effective_assigned_location_source_aggregation_id"] == aggregation["id"]
    record = client.post("/api/v1/records", json={
        "aggregation_id": child["id"], "record_number": "LOC-REC", "title": "Inherited-location record",
    }).json()
    assert record["effective_assigned_location_source_aggregation_id"] == aggregation["id"]
    preview = client.post(
        f"/api/v1/aggregations/{aggregation['id']}/location-preview",
        json={"current_location": "STORE-A-02"},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["affected_descendant_count"] == 2
    assert {item["entity_type"] for item in preview.json()["affected_descendants"]} == {"aggregation", "record"}
    closed = client.patch(
        f"/api/v1/aggregations/{aggregation['id']}", json={"date_closed": datetime.now(timezone.utc).isoformat()},
        headers={"If-Match": str(changed.json()["version"])},
    )
    assert closed.status_code == 200, closed.text
    moved = client.post(
        f"/api/v1/aggregations/{aggregation['id']}/location",
        json={"current_location": "STORE-A-02", "reason": "Container moved after closure"},
        headers={"If-Match": str(closed.json()["version"])},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["effective_current_location"] == "STORE-A-02"
    history = client.get(f"/api/v1/aggregations/{aggregation['id']}/history").json()
    assert any(item["operation"] == "RESOURCE_LOCATION_CHANGED" for item in history)
    assert not any(
        item["operation"] == "UPDATE" and
        ({"assigned_location", "current_location"} & set(item.get("changed_fields") or []))
        for item in history
    )


def test_aggregation_date_constraint_has_an_accessible_primary_message(
    client: TestClient,
    aggregation: dict,
):
    response = client.patch(
        f"/api/v1/aggregations/{aggregation['id']}",
        json={"date_closed": "2000-01-01T00:00:00Z"},
        headers={"If-Match": str(aggregation["version"])},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "closure_before_opening"
    assert detail["message"] == (
        "This aggregation cannot be closed before its opening date. Choose a closing date "
        "that is the same as or later than the opening date."
    )
    assert detail["date_opened"].replace("+00:00", "Z") == aggregation["date_opened"]


def test_aggregation_number_must_be_unique(client: TestClient, aggregation: dict):
    response = client.post(
        "/api/v1/aggregations",
        json={"aggregation_number": aggregation["aggregation_number"], "title": "Duplicate", "classification_id": 1},
    )
    assert response.status_code == 409


def test_record_crud_and_required_aggregation(
    client: TestClient, aggregation: dict, record: dict
):
    assert record["date_originated"] == record["date_created"]

    response = client.get(
        "/api/v1/records", params={"aggregation_id": aggregation["id"]}
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [record["id"]]

    response = client.patch(
        f"/api/v1/records/{record['id']}", json={"title": "Updated record"},
        headers={"If-Match": str(record["version"])},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Updated record"
    record = response.json()

    response = client.post(
        "/api/v1/records",
        json={"aggregation_id": 999999, "record_number": "REC-002", "title": "Orphan"},
    )
    assert response.status_code == 409

    assert client.delete(f"/api/v1/records/{record['id']}", headers={"If-Match": str(record["version"])}).status_code == 204


def test_digital_component_crud_and_order(client: TestClient, record: dict):
    component_payload = {
        "record_id": record["id"],
        "file_name": "page-1.pdf",
        "mime_type": "application/pdf",
        "size_in_bytes": 2048,
        "checksum_algo": "SHA-256",
        "checksum_value": "a" * 64,
    }
    second_response = client.post(
        "/api/v1/digital-components",
        json={**component_payload, "component_order": 2, "file_name": "page-2.pdf"},
    )
    first_response = client.post(
        "/api/v1/digital-components",
        json={**component_payload, "component_order": 1},
    )
    assert first_response.status_code == 201
    assert second_response.status_code == 201
    first = first_response.json()
    assert first["date_originated"] == first["date_created"]

    response = client.get(
        "/api/v1/digital-components", params={"record_id": record["id"]}
    )
    assert response.status_code == 200
    assert [item["component_order"] for item in response.json()] == [1, 2]

    duplicate_response = client.post(
        "/api/v1/digital-components",
        json={**component_payload, "component_order": 1, "file_name": "duplicate.pdf"},
    )
    assert duplicate_response.status_code == 409

    response = client.patch(
        f"/api/v1/digital-components/{first['id']}",
        json={"file_name": "renamed.pdf"},
        headers={"If-Match": str(first["version"])},
    )
    assert response.status_code == 200
    assert response.json()["file_name"] == "renamed.pdf"
    first = response.json()

    assert client.delete(f"/api/v1/digital-components/{first['id']}", headers={"If-Match": str(first["version"])}).status_code == 204


def test_parent_deletion_is_rejected(client: TestClient, aggregation: dict, record: dict):
    response = client.delete(f"/api/v1/aggregations/{aggregation['id']}", headers={"If-Match": str(aggregation["version"])})
    assert response.status_code == 409


def test_record_deletion_cascades_to_components_and_content(client: TestClient, record: dict):
    component = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": 1},
        files={"file": ("delete-with-record.txt", b"content", "text/plain")},
    ).json()

    deleted = client.delete(
        f"/api/v1/records/{record['id']}",
        headers={"If-Match": str(record["version"])},
    )

    assert deleted.status_code == 204
    assert client.get(f"/api/v1/records/{record['id']}").status_code == 404
    assert client.get(f"/api/v1/digital-components/{component['id']}").status_code == 404
    assert client.get(f"/api/v1/digital-components/{component['id']}/content").status_code == 404


def test_closed_aggregation_makes_its_entire_subtree_immutable(client: TestClient):
    root = client.post("/api/v1/aggregations", json={
        "aggregation_number": "CLOSE-ROOT", "title": "Closed root", "classification_id": 1,
    }).json()
    child = client.post("/api/v1/aggregations", json={
        "parent_aggregation_id": root["id"], "aggregation_number": "CLOSE-CHILD",
        "title": "Child",
    }).json()
    sibling = client.post("/api/v1/aggregations", json={
        "aggregation_number": "CLOSE-SIBLING", "title": "Independent root", "classification_id": 1,
    }).json()
    record = client.post("/api/v1/records", json={
        "aggregation_id": child["id"], "record_number": "CLOSE-REC", "title": "Protected record",
    }).json()
    component = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": 1}, files={"file": ("locked.txt", b"locked", "text/plain")},
    ).json()
    client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": 2}, files={"file": ("also-locked.txt", b"locked", "text/plain")},
    )

    future = client.patch(
        f"/api/v1/aggregations/{root['id']}", json={"date_closed": "2999-01-01T00:00:00Z"},
        headers={"If-Match": str(root["version"])},
    )
    assert future.status_code == 422

    closed = client.patch(
        f"/api/v1/aggregations/{root['id']}", json={"date_closed": root["date_created"]},
        headers={"If-Match": str(root["version"])},
    )
    assert closed.status_code == 200
    root = closed.json()

    assert client.patch(
        f"/api/v1/aggregations/{root['id']}", json={"title": "Cannot rename"},
        headers={"If-Match": str(root["version"])},
    ).status_code == 409
    assert client.patch(
        f"/api/v1/aggregations/{root['id']}", json={"date_closed": "2026-01-01T00:00:00Z"},
        headers={"If-Match": str(root["version"])},
    ).status_code == 409
    assert client.patch(
        f"/api/v1/aggregations/{child['id']}", json={"description": "Cannot edit inherited closure"},
        headers={"If-Match": str(child["version"])},
    ).status_code == 409

    assert client.get(f"/api/v1/records/{record['id']}").status_code == 200
    assert client.get(f"/api/v1/digital-components/{component['id']}/content").content == b"locked"
    assert client.patch(
        f"/api/v1/records/{record['id']}", json={"title": "No"},
        headers={"If-Match": str(record["version"])},
    ).status_code == 409
    assert client.delete(
        f"/api/v1/digital-components/{component['id']}",
        headers={"If-Match": str(component["version"])},
    ).status_code == 409
    assert client.post(
        f"/api/v1/records/{record['id']}/digital-components/{component['id']}/move",
        json={"direction": 1},
    ).status_code == 409
    assert client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": 2}, files={"file": ("no.txt", b"no", "text/plain")},
    ).status_code == 409
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute(
                """UPDATE digital_component_blobs SET content = %s, segment_size = %s
                   WHERE content_set_id = (
                       SELECT active_content_set_id FROM digital_components WHERE id = %s
                   )""",
                (b"bypass", len(b"bypass"), component["id"]),
            )
        connection.rollback()
    assert client.post("/api/v1/records", json={
        "aggregation_id": child["id"], "record_number": "CLOSE-NO", "title": "No",
    }).status_code == 409
    assert client.post("/api/v1/aggregations", json={
        "parent_aggregation_id": child["id"], "aggregation_number": "CLOSE-NO-CHILD", "title": "No",
    }).status_code == 409
    assert client.delete(
        f"/api/v1/aggregations/{child['id']}", headers={"If-Match": str(child["version"])},
    ).status_code == 409

    missing_reason = client.patch(
        f"/api/v1/aggregations/{root['id']}", json={"date_closed": None},
        headers={"If-Match": str(root["version"])},
    )
    assert missing_reason.status_code == 422
    assert missing_reason.json()["detail"]["code"] == "reopen_reason_required"

    reopen_reason = "The file was closed before the review was complete."
    reopened = client.patch(
        f"/api/v1/aggregations/{root['id']}", json={"date_closed": None},
        headers={
            "If-Match": str(root["version"]),
            "X-Change-Reason": reopen_reason,
        },
    )
    assert reopened.status_code == 200
    history = client.post("/api/v1/event-history/search", json={
        "where": {
            "and": [
                {"field": "entity_type", "operator": "eq", "value": "aggregation"},
                {"field": "entity_id", "operator": "eq", "value": root["id"]},
                {"field": "operation", "operator": "eq", "value": "UPDATE"},
            ]
        },
        "sort": [{"field": "id", "direction": "desc"}],
        "limit": 1,
    })
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["reason"] == reopen_reason
    updated_record = client.patch(
        f"/api/v1/records/{record['id']}", json={"title": "Allowed again"},
        headers={"If-Match": str(record["version"])},
    )
    assert updated_record.status_code == 200

    child_closed = client.patch(
        f"/api/v1/aggregations/{child['id']}", json={"date_closed": child["date_created"]},
        headers={"If-Match": str(child["version"])},
    )
    assert child_closed.status_code == 200
    assert client.patch(
        f"/api/v1/records/{record['id']}", json={"title": "Still blocked"},
        headers={"If-Match": str(updated_record.json()["version"])},
    ).status_code == 409
    sibling_record = client.post("/api/v1/records", json={
        "aggregation_id": sibling["id"], "record_number": "CLOSE-SIB-REC", "title": "Independent",
    })
    assert sibling_record.status_code == 201


def test_request_validation(client: TestClient, record: dict):
    response = client.post(
        "/api/v1/digital-components",
        json={
            "record_id": record["id"],
            "component_order": 0,
            "file_name": "bad.txt",
            "mime_type": "text/plain",
            "size_in_bytes": -1,
            "checksum_algo": "SHA-256",
            "checksum_value": "abc",
        },
    )
    assert response.status_code == 422


def create_search_records(client: TestClient, aggregation: dict) -> list[dict]:
    records = []
    for record_number, title, description, originated in (
        ("REC-S-001", "Alpha Contract", None, "2025-02-01T00:00:00Z"),
        ("REC-S-002", "Draft contract", "Pending review", "2025-06-01T00:00:00Z"),
        ("REC-S-003", "Beta Note", "Final note", "2026-01-01T00:00:00Z"),
    ):
        response = client.post(
            "/api/v1/records",
            json={
                "aggregation_id": aggregation["id"],
                "record_number": record_number,
                "title": title,
                "description": description,
                "date_originated": originated,
            },
        )
        assert response.status_code == 201
        records.append(response.json())
    return records


def test_nested_boolean_search(client: TestClient, aggregation: dict):
    create_search_records(client, aggregation)
    response = client.post(
        "/api/v1/records/search",
        json={
            "where": {
                "and": [
                    {
                        "field": "aggregation_id",
                        "operator": "in",
                        "value": [aggregation["id"]],
                    },
                    {
                        "field": "date_originated",
                        "operator": "between",
                        "value": [
                            "2025-01-01T00:00:00Z",
                            "2025-12-31T23:59:59Z",
                        ],
                    },
                    {
                        "or": [
                            {
                                "field": "title",
                                "operator": "contains_ci",
                                "value": "alpha",
                            },
                            {"field": "description", "operator": "is_null"},
                        ]
                    },
                    {
                        "not": {
                            "field": "title",
                            "operator": "contains_ci",
                            "value": "draft",
                        }
                    },
                ]
            },
            "sort": [{"field": "record_number", "direction": "desc"}],
            "limit": 10,
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 1
    assert result["returned"] == 1
    assert result["limit"] == 10
    assert result["offset"] == 0
    assert [item["record_number"] for item in result["items"]] == ["REC-S-001"]


@pytest.mark.parametrize(
    ("expression", "expected_total"),
    [
        ({"field": "record_number", "operator": "eq", "value": "REC-S-001"}, 1),
        ({"field": "record_number", "operator": "ne", "value": "REC-S-001"}, 2),
        ({"field": "id", "operator": "gt", "value": 1}, 2),
        ({"field": "id", "operator": "gte", "value": 1}, 3),
        ({"field": "id", "operator": "lt", "value": 2}, 1),
        ({"field": "id", "operator": "lte", "value": 2}, 2),
        (
            {
                "field": "record_number",
                "operator": "not_in",
                "value": ["REC-S-001", "REC-S-002"],
            },
            1,
        ),
        ({"field": "description", "operator": "is_not_null"}, 2),
        ({"field": "title", "operator": "starts_with_ci", "value": "alpha"}, 1),
        ({"field": "title", "operator": "ends_with_ci", "value": "NOTE"}, 1),
    ],
)
def test_search_comparison_operators(
    client: TestClient,
    aggregation: dict,
    expression: dict,
    expected_total: int,
):
    create_search_records(client, aggregation)
    response = client.post("/api/v1/records/search", json={"where": expression})
    assert response.status_code == 200
    assert response.json()["total"] == expected_total


def test_search_pagination_and_literal_wildcards(
    client: TestClient, aggregation: dict
):
    create_search_records(client, aggregation)
    wildcard_record = client.post(
        "/api/v1/records",
        json={
            "aggregation_id": aggregation["id"],
            "record_number": "REC-S-004",
            "title": "Literal 100%_match",
        },
    )
    assert wildcard_record.status_code == 201

    response = client.post(
        "/api/v1/records/search",
        json={
            "where": {
                "field": "title",
                "operator": "contains_ci",
                "value": "100%_match",
            },
            "sort": [{"field": "title", "direction": "asc"}],
            "limit": 1,
            "offset": 0,
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 1
    assert result["returned"] == 1
    assert result["items"][0]["record_number"] == "REC-S-004"


def test_all_entity_search_endpoints(
    client: TestClient, aggregation: dict, record: dict
):
    aggregation_response = client.post(
        "/api/v1/aggregations/search",
        json={
            "where": {
                "field": "aggregation_number",
                "operator": "eq",
                "value": aggregation["aggregation_number"],
            }
        },
    )
    assert aggregation_response.status_code == 200
    assert aggregation_response.json()["total"] == 1

    component_response = client.post(
        "/api/v1/digital-components",
        json={
            "record_id": record["id"],
            "component_order": 1,
            "file_name": "searchable.pdf",
            "mime_type": "application/pdf",
            "size_in_bytes": 1024,
            "checksum_algo": "SHA-256",
            "checksum_value": "a" * 64,
        },
    )
    assert component_response.status_code == 201
    response = client.post(
        "/api/v1/digital-components/search",
        json={
            "where": {
                "field": "size_in_bytes",
                "operator": "between",
                "value": [1000, 2000],
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_search_rejects_unsafe_or_invalid_grammar(
    client: TestClient, aggregation: dict
):
    create_search_records(client, aggregation)

    unknown_field = client.post(
        "/api/v1/records/search",
        json={
            "where": {
                "field": "title; DROP TABLE records; --",
                "operator": "eq",
                "value": "anything",
            }
        },
    )
    assert unknown_field.status_code == 422

    wrong_operator_type = client.post(
        "/api/v1/records/search",
        json={
            "where": {
                "field": "id",
                "operator": "contains_ci",
                "value": "1",
            }
        },
    )
    assert wrong_operator_type.status_code == 422

    mixed_expression = client.post(
        "/api/v1/records/search",
        json={
            "where": {
                "not": {"field": "id", "operator": "eq", "value": 1},
                "value": "not allowed on a logical expression",
            }
        },
    )
    assert mixed_expression.status_code == 422

    oversized_in = client.post(
        "/api/v1/records/search",
        json={
            "where": {
                "field": "id",
                "operator": "in",
                "value": list(range(101)),
            }
        },
    )
    assert oversized_in.status_code == 422

    expression = {"field": "id", "operator": "eq", "value": 1}
    for _ in range(6):
        expression = {"not": expression}
    excessive_depth = client.post(
        "/api/v1/records/search", json={"where": expression}
    )
    assert excessive_depth.status_code == 422


def test_api_change_creates_correlated_history(client: TestClient):
    request_id = "11111111-1111-4111-8111-111111111111"
    correlation_id = "22222222-2222-4222-8222-222222222222"
    response = client.post(
        "/api/v1/aggregations",
        headers={
            "X-Request-ID": request_id,
            "X-Correlation-ID": correlation_id,
            "X-Change-Reason": "Created for audit testing",
        },
        json={"aggregation_number": "AUDIT-001", "title": "Audited item", "classification_id": 1},
    )
    assert response.status_code == 201
    aggregation = response.json()
    assert response.headers["X-Request-ID"] == request_id
    assert response.headers["X-Correlation-ID"] == correlation_id

    history_response = client.get(
        f"/api/v1/aggregations/{aggregation['id']}/history"
    )
    assert history_response.status_code == 200
    history = history_response.json()
    assert len(history) == 1
    event = history[0]
    assert event["entity_type"] == "aggregation"
    assert event["entity_id"] == aggregation["id"]
    assert event["operation"] == "CREATE"
    assert event["actor_user_id"] == 1
    assert event["actor_name"] == "Test Administrator"
    assert event["actor_email"] == "admin@test.invalid"
    assert event["actor_type"] == "user"
    assert event["source"] == "api"
    assert event["request_id"] == request_id
    assert event["correlation_id"] == correlation_id
    assert event["reason"] == "Created for audit testing"
    assert event["before_state"] is None
    assert event["after_state"]["title"] == "Audited item"
    assert "title" in event["changed_fields"]
    assert event["metadata"]["reference_snapshots"]["after"]["classification_id"] == {
        "id": 1, "code": "TEST-01", "title": "Test Classification",
    }
    assert event["metadata"]["reference_snapshots"]["entity"] == {
        "id": aggregation["id"], "code": "AUDIT-001", "title": "Audited item",
    }


def test_event_source_is_controlled(client: TestClient):
    rejected = client.post(
        "/api/v1/aggregations",
        headers={"X-Event-Source": "made-up-client"},
        json={"aggregation_number": "SOURCE-INVALID", "title": "Invalid source", "classification_id": 1},
    )
    assert rejected.status_code == 400

    created = client.post(
        "/api/v1/aggregations",
        headers={"X-Event-Source": "web_ui"},
        json={"aggregation_number": "SOURCE-WEB", "title": "Web source", "classification_id": 1},
    )
    assert created.status_code == 201
    history = client.get(
        f"/api/v1/aggregations/{created.json()['id']}/history"
    ).json()
    assert history[0]["source"] == "web_ui"


def test_update_and_delete_snapshots_remain_available(
    client: TestClient, record: dict
):
    update_response = client.patch(
        f"/api/v1/records/{record['id']}",
        json={"title": "Changed title", "description": "Changed description"},
        headers={"If-Match": str(record["version"])},
    )
    assert update_response.status_code == 200

    delete_response = client.delete(f"/api/v1/records/{record['id']}", headers={"If-Match": str(update_response.json()["version"])})
    assert delete_response.status_code == 204

    history_response = client.get(f"/api/v1/records/{record['id']}/history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert [
        event["operation"] for event in history
        if event["operation"] != "INFORMATION_GOVERNANCE_BYPASS_USED"
    ] == ["DELETE", "UPDATE", "CREATE"]

    update_event = next(event for event in history if event["operation"] == "UPDATE")
    assert update_event["before_state"]["title"] == "Example record"
    assert update_event["after_state"]["title"] == "Changed title"
    assert update_event["changed_fields"] == ["description", "title"]

    delete_event = next(event for event in history if event["operation"] == "DELETE")
    assert delete_event["before_state"]["title"] == "Changed title"
    assert delete_event["after_state"] is None


def test_event_history_is_read_only_and_searchable(
    client: TestClient, aggregation: dict
):
    history = client.get(
        "/api/v1/event-history",
        params={"entity_type": "aggregation", "entity_id": aggregation["id"]},
    )
    assert history.status_code == 200
    event = history.json()[0]

    get_response = client.get(f"/api/v1/event-history/{event['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == event["id"]

    search_response = client.post(
        "/api/v1/event-history/search",
        json={
            "where": {
                "and": [
                    {"field": "entity_type", "operator": "eq", "value": "aggregation"},
                    {"field": "operation", "operator": "eq", "value": "CREATE"},
                    {"field": "request_id", "operator": "is_not_null"},
                ]
            }
        },
    )
    assert search_response.status_code == 200
    assert search_response.json()["total"] == 1

    assert client.patch(
        f"/api/v1/event-history/{event['id']}", json={"reason": "tampered"}
    ).status_code == 405
    assert client.delete(f"/api/v1/event-history/{event['id']}").status_code == 405


def test_request_context_headers_are_validated(client: TestClient):
    response = client.get("/health", headers={"X-Correlation-ID": "not-a-uuid"})
    assert response.status_code == 400

    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == response.headers["X-Correlation-ID"]


def test_optimistic_concurrency_requires_current_version(
    client: TestClient, record: dict
):
    missing = client.patch(
        f"/api/v1/records/{record['id']}", json={"title": "No precondition"}
    )
    assert missing.status_code == 428

    updated = client.patch(
        f"/api/v1/records/{record['id']}",
        json={"title": "First writer"},
        headers={"If-Match": str(record["version"])},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == record["version"] + 1

    stale = client.patch(
        f"/api/v1/records/{record['id']}",
        json={"title": "Stale writer"},
        headers={"If-Match": str(record["version"])},
    )
    assert stale.status_code == 412
    assert stale.json()["detail"]["current_version"] == updated.json()["version"]


def test_upload_download_replace_and_delete_content(client: TestClient, record: dict):
    content = "مرحبا ERMS".encode()
    uploaded = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": "1"},
        files={"file": ("note.txt", content, "text/plain")},
    )
    assert uploaded.status_code == 201
    component = uploaded.json()
    assert component["content_status"] == "available"
    assert component["storage_backend"] == "postgresql"
    assert component["size_in_bytes"] == len(content)
    assert component["checksum_algo"] == "sha256"

    downloaded = client.get(
        f"/api/v1/digital-components/{component['id']}/content"
    )
    assert downloaded.status_code == 200
    assert downloaded.content == content

    replacement = b"replacement"
    replaced = client.put(
        f"/api/v1/digital-components/{component['id']}/content",
        files={"file": ("replacement.bin", replacement, "application/octet-stream")},
        headers={"If-Match": str(component["version"])},
    )
    assert replaced.status_code == 200
    component = replaced.json()
    assert component["version"] == 2
    assert client.get(
        f"/api/v1/digital-components/{component['id']}/content"
    ).content == replacement

    deleted = client.delete(
        f"/api/v1/digital-components/{component['id']}/content",
        headers={"If-Match": str(component["version"])},
    )
    assert deleted.status_code == 200
    assert deleted.json()["content_status"] == "deleted"
    assert client.get(
        f"/api/v1/digital-components/{component['id']}/content"
    ).status_code == 404

    history = client.get(
        f"/api/v1/digital-components/{component['id']}/history"
    ).json()
    operations = [event["operation"] for event in history]
    assert "CONTENT_UPLOADED" in operations
    assert "CONTENT_DOWNLOADED" in operations
    assert "CONTENT_REPLACED" in operations
    assert "CONTENT_DELETED" in operations
    domain_events = [event for event in history if event["operation"].startswith("CONTENT_")]
    assert all(event["before_state"] is None for event in domain_events)
    assert all(event["after_state"] is None for event in domain_events)


def test_segmented_content_and_byte_ranges(client: TestClient, record: dict, monkeypatch):
    set_content_settings(client, CONTENT_SEGMENT_SIZE_BYTES=4)
    payload = b"0123456789ABC"
    uploaded = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": "1"},
        files={"file": ("segmented.bin", payload, "application/octet-stream")},
    )
    assert uploaded.status_code == 201
    component = uploaded.json()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        segments = connection.execute(
            """SELECT segment_no, segment_size
               FROM digital_component_blobs
               WHERE content_set_id = %s ORDER BY segment_no""",
            (component["active_content_set_id"],),
        ).fetchall()
    assert segments == [(0, 4), (1, 4), (2, 4), (3, 1)]

    across_boundary = client.get(
        f"/api/v1/digital-components/{component['id']}/content",
        headers={"Range": "bytes=3-9"},
    )
    assert across_boundary.status_code == 206
    assert across_boundary.content == payload[3:10]
    assert across_boundary.headers["content-range"] == f"bytes 3-9/{len(payload)}"
    assert across_boundary.headers["accept-ranges"] == "bytes"

    head = client.head(f"/api/v1/digital-components/{component['id']}/content")
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == str(len(payload))
    assert head.headers["accept-ranges"] == "bytes"

    suffix = client.get(
        f"/api/v1/digital-components/{component['id']}/content",
        headers={"Range": "bytes=-4"},
    )
    assert suffix.status_code == 206
    assert suffix.content == payload[-4:]

    unsatisfiable = client.get(
        f"/api/v1/digital-components/{component['id']}/content",
        headers={"Range": "bytes=999-1000"},
    )
    assert unsatisfiable.status_code == 416
    assert unsatisfiable.headers["content-range"] == f"bytes */{len(payload)}"


def test_200_mib_upload_is_segmented_and_reconstructs_exactly(
    client: TestClient, record: dict, monkeypatch, tmp_path,
):
    """Exercise a genuinely large upload against the disposable PostgreSQL instance."""
    file_size = 200 * 1024 * 1024
    segment_size = 16 * 1024 * 1024
    source_path = tmp_path / "generated-200-mib.bin"
    source_digest = hashlib.sha256()
    write_block = bytes(range(256)) * 4096  # 1 MiB deterministic block

    set_content_settings(client, MAX_UPLOAD_SIZE_BYTES=file_size, CONTENT_SEGMENT_SIZE_BYTES=segment_size)

    try:
        with source_path.open("wb") as source:
            for _ in range(file_size // len(write_block)):
                source.write(write_block)
                source_digest.update(write_block)

        with source_path.open("rb") as source:
            uploaded = client.post(
                f"/api/v1/records/{record['id']}/digital-components/upload",
                data={"component_order": "1"},
                files={"file": (source_path.name, source, "application/octet-stream")},
            )

        assert uploaded.status_code == 201, uploaded.text
        component = uploaded.json()
        assert component["size_in_bytes"] == file_size
        assert component["checksum_value"] == source_digest.hexdigest()

        reconstructed_digest = hashlib.sha256()
        reconstructed_size = 0
        observed_sizes = []
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            with connection.cursor(name="large_file_segments") as cursor:
                cursor.execute(
                    """SELECT segment_no, segment_size, content
                       FROM digital_component_blobs
                       WHERE content_set_id = %s
                       ORDER BY segment_no""",
                    (component["active_content_set_id"],),
                )
                for expected_segment_no, row in enumerate(cursor):
                    segment_no, stored_size, content = row
                    assert segment_no == expected_segment_no
                    assert stored_size == len(content)
                    observed_sizes.append(stored_size)
                    reconstructed_size += len(content)
                    reconstructed_digest.update(content)

        assert observed_sizes == [segment_size] * 12 + [8 * 1024 * 1024]
        assert reconstructed_size == file_size
        assert reconstructed_digest.hexdigest() == source_digest.hexdigest()

        boundary_start = segment_size - 8
        ranged = client.get(
            f"/api/v1/digital-components/{component['id']}/content",
            headers={"Range": f"bytes={boundary_start}-{boundary_start + 15}"},
        )
        assert ranged.status_code == 206
        assert ranged.content == write_block[-8:] + write_block[:8]
        assert ranged.headers["content-range"] == (
            f"bytes {boundary_start}-{boundary_start + 15}/{file_size}"
        )
    finally:
        source_path.unlink(missing_ok=True)


def test_pdf_rendition_is_inline_and_audited(client: TestClient, record: dict):
    pdf = b"%PDF-1.4\n% minimal test fixture\n%%EOF"
    uploaded = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": "1"},
        files={"file": ("letter.pdf", pdf, "application/pdf")},
    ).json()
    response = client.get(f"/api/v1/digital-components/{uploaded['id']}/rendition")
    assert response.status_code == 200
    assert response.content == pdf
    assert response.headers["content-length"] == str(len(pdf))
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"].startswith("inline;")
    ranged = client.get(
        f"/api/v1/digital-components/{uploaded['id']}/rendition",
        headers={"Range": "bytes=5-11"},
    )
    assert ranged.status_code == 206
    assert ranged.content == pdf[5:12]
    assert ranged.headers["content-length"] == "7"
    assert ranged.headers["content-range"] == f"bytes 5-11/{len(pdf)}"
    history = client.get(f"/api/v1/digital-components/{uploaded['id']}/history").json()
    assert "CONTENT_VIEWED" in [event["operation"] for event in history]


def test_pdf_print_rendition_uses_print_authorization_route(client: TestClient, record: dict):
    pdf = b"%PDF-1.4\n% printable test fixture\n%%EOF"
    uploaded = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": "1"},
        files={"file": ("printable.pdf", pdf, "application/pdf")},
    ).json()
    response = client.get(
        f"/api/v1/digital-components/{uploaded['id']}/print-rendition"
    )
    assert response.status_code == 200
    assert response.content == pdf
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"].startswith("inline;")


@pytest.mark.parametrize(
    ("extension", "mime_type", "expected_method"),
    (
        (".md", "text/markdown", "libreoffice"),
        (".msg", "application/vnd.ms-outlook", "extract-msg+libreoffice"),
        (".eml", "message/rfc822", "stdlib-email+libreoffice"),
        (".html", "text/html", "libreoffice"),
        (".txt", "text/plain", "libreoffice"),
        (".xml", "application/xml", "escaped-xml+libreoffice"),
        (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx-fit-to-page+libreoffice"),
    ),
)
def test_additional_text_and_email_formats_use_libreoffice_pdf_conversion(
    client, monkeypatch, extension: str, mime_type: str, expected_method: str,
):
    expected_pdf = b"%PDF-1.7\n% converted test fixture\n%%EOF"

    monkeypatch.setattr(document_conversion, "_libreoffice_binary", lambda: "/test/soffice")

    def convert(command, **kwargs):
        if command[1].endswith(("email_to_html.py", "xml_to_html.py", "xlsx_to_preview.py")):
            Path(command[3]).write_bytes(b"prepared preview")
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")
        output = Path(command[command.index("--outdir") + 1])
        (output / "source.pdf").write_bytes(expected_pdf)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(document_conversion.subprocess, "run", convert)

    rendition, method = document_conversion.pdf_rendition(
        b"synthetic source", f"source{extension}", mime_type, settings=content_snapshot(),
    )

    assert rendition == expected_pdf
    assert method == expected_method


def test_email_extraction_timeout_fails_preview_safely(client, monkeypatch):
    monkeypatch.setattr(
        document_conversion.subprocess,
        "run",
        lambda command, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(command, kwargs["timeout"])
        ),
    )

    with pytest.raises(document_conversion.ConversionUnavailable, match="preview preparation timed out"):
        document_conversion.pdf_rendition(
            b"synthetic MSG", "message.msg", "application/vnd.ms-outlook", settings=content_snapshot(),
        )


def test_unsupported_preview_preserves_original_download(client: TestClient, record: dict):
    uploaded = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": "1"},
        files={"file": ("archive.zip", b"not really a zip", "application/zip")},
    ).json()
    assert client.get(f"/api/v1/digital-components/{uploaded['id']}/rendition").status_code == 415
    assert client.get(f"/api/v1/digital-components/{uploaded['id']}/content").content == b"not really a zip"


def test_browser_native_image_preview_preserves_mime_type_and_is_audited(client: TestClient, record: dict):
    image = b"\x89PNG\r\n\x1a\nsynthetic-test-image"
    uploaded = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": "1"},
        files={"file": ("scan.png", image, "image/png")},
    ).json()
    response = client.get(f"/api/v1/digital-components/{uploaded['id']}/rendition")
    assert response.status_code == 200
    assert response.content == image
    assert response.headers["content-type"].startswith("image/png")
    assert response.headers["content-disposition"].startswith("inline;")
    history = client.get(f"/api/v1/digital-components/{uploaded['id']}/history").json()
    viewed = next(event for event in history if event["operation"] == "CONTENT_VIEWED")
    assert viewed["metadata"]["rendering_method"] == "browser-native"
    dashboard = client.get("/api/v1/dashboard/summary", params={"recent_limit": 7})
    assert dashboard.status_code == 200, dashboard.text
    assert any(
        item["entity_type"] == "record"
        and item["entity_id"] == record["id"]
        and item["operation"] == "CONTENT_VIEWED"
        for item in dashboard.json()["recent_activity"]
    )
    personal_activity = client.get(
        "/api/v1/auth/me/recent-activity", params={"limit": 7},
    )
    assert personal_activity.status_code == 200, personal_activity.text
    viewed_resources = {
        (item["entity_type"], item["entity_id"])
        for item in personal_activity.json()
        if item["operation"] == "CONTENT_VIEWED"
    }
    assert ("record", record["id"]) in viewed_resources
    assert ("aggregation", record["aggregation_id"]) in viewed_resources


def test_upload_size_limit(client: TestClient, record: dict, monkeypatch):
    set_content_settings(client, MAX_UPLOAD_SIZE_BYTES=4)
    response = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": "1"},
        files={"file": ("too-large.bin", b"12345", "application/octet-stream")},
    )
    assert response.status_code == 413
def test_record_draft_commits_metadata_and_ordered_content_atomically(client, aggregation):
    draft_response = client.post("/api/v1/record-drafts", json={})
    assert draft_response.status_code == 201
    draft = draft_response.json()
    assert "status" not in draft
    updated = client.patch(f"/api/v1/record-drafts/{draft['id']}", json={
        "aggregation_id": aggregation["id"], "record_number": "REC-DRAFT-1",
        "title": "Created as a package", "description": "Metadata and files commit together",
    })
    assert updated.status_code == 200

    assert client.get("/api/v1/records").json() == []
    first = client.post(
        f"/api/v1/record-drafts/{draft['id']}/components",
        data={"component_order": "1"}, files={"file": ("first.txt", b"first", "text/plain")},
    )
    second = client.post(
        f"/api/v1/record-drafts/{draft['id']}/components",
        data={"component_order": "2"}, files={"file": ("second.pdf", b"second", "application/pdf")},
    )
    assert first.status_code == second.status_code == 201

    reordered = client.put(
        f"/api/v1/record-drafts/{draft['id']}/components/order",
        json={"components": [
            {"id": first.json()["id"], "component_order": 2},
            {"id": second.json()["id"], "component_order": 1},
        ]},
    )
    assert reordered.status_code == 204
    staged = client.get(f"/api/v1/record-drafts/{draft['id']}/components").json()
    assert [item["file_name"] for item in staged] == ["second.pdf", "first.txt"]
    assert all(item["content_status"] == "staged" for item in staged)

    committed = client.post(f"/api/v1/record-drafts/{draft['id']}/commit")
    assert committed.status_code == 201
    record = committed.json()
    components = client.get("/api/v1/digital-components", params={"record_id": record["id"]}).json()
    assert [item["file_name"] for item in components] == ["second.pdf", "first.txt"]
    assert client.get(f"/api/v1/digital-components/{components[0]['id']}/content").content == b"second"
    assert client.get(f"/api/v1/record-drafts/{draft['id']}").status_code == 404


def test_record_draft_contract_has_no_redundant_status_column():
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute(
            """SELECT EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='record_drafts'
                     AND column_name='status'
               )"""
        ).fetchone()[0] is False


def test_record_draft_component_can_be_removed_and_incomplete_commit_rolls_back(client, aggregation):
    draft = client.post("/api/v1/record-drafts", json={"aggregation_id": aggregation["id"]}).json()
    component = client.post(
        f"/api/v1/record-drafts/{draft['id']}/components",
        data={"component_order": "1"}, files={"file": ("remove.txt", b"remove", "text/plain")},
    ).json()
    removed = client.delete(f"/api/v1/record-drafts/{draft['id']}/components/{component['id']}")
    assert removed.status_code == 204
    assert client.get(f"/api/v1/record-drafts/{draft['id']}/components").json() == []
    failed = client.post(f"/api/v1/record-drafts/{draft['id']}/commit")
    assert failed.status_code == 422
    assert client.get("/api/v1/records").json() == []


def test_expired_draft_cleanup_removes_staged_segments(client, aggregation):
    draft = client.post("/api/v1/record-drafts", json={"aggregation_id": aggregation["id"]}).json()
    staged = client.post(
        f"/api/v1/record-drafts/{draft['id']}/components",
        data={"component_order": "1"},
        files={"file": ("temporary.bin", b"temporary-content", "application/octet-stream")},
    )
    assert staged.status_code == 201
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute(
            "UPDATE record_drafts SET expires_at = CURRENT_TIMESTAMP - interval '1 minute' WHERE id = %s",
            (draft["id"],),
        )
        dry_run = cleanup_content(connection, dry_run=True)
        assert dry_run.removed_drafts == 1
        assert connection.execute(
            "SELECT count(*) AS count FROM record_draft_component_blobs"
        ).fetchone()["count"] > 0
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        result = cleanup_content(connection)
        assert result.removed_drafts == 1
        assert result.reclaimed_bytes == len(b"temporary-content")
        assert connection.execute(
            "SELECT count(*) AS count FROM record_draft_component_blobs"
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT count(*) AS count FROM record_drafts WHERE id = %s", (draft["id"],)
        ).fetchone()["count"] == 0


def test_committed_components_can_be_reordered_and_removed_without_order_gaps(client, record):
    components = []
    for position, name in enumerate(("one.txt", "two.txt", "three.txt"), 1):
        response = client.post(
            f"/api/v1/records/{record['id']}/digital-components/upload",
            data={"component_order": str(position)}, files={"file": (name, name.encode(), "text/plain")},
        )
        assert response.status_code == 201
        components.append(response.json())
    response = client.put(
        f"/api/v1/records/{record['id']}/digital-components/order",
        json={"components": [
            {"id": components[2]["id"], "component_order": 1},
            {"id": components[0]["id"], "component_order": 2},
            {"id": components[1]["id"], "component_order": 3},
        ]},
    )
    assert response.status_code == 204
    reordered = client.get("/api/v1/digital-components", params={"record_id": record["id"]}).json()
    assert [item["file_name"] for item in reordered] == ["three.txt", "one.txt", "two.txt"]
    assert client.delete(
        f"/api/v1/digital-components/{reordered[1]['id']}",
        headers={"If-Match": str(reordered[1]["version"])},
    ).status_code == 204
    remaining = client.get("/api/v1/digital-components", params={"record_id": record["id"]}).json()
    assert [item["component_order"] for item in remaining] == [1, 2]


def test_component_search_pages_and_single_move_cross_page_boundary(client, record):
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO digital_components
                       (record_id,component_order,file_name,mime_type,size_in_bytes,
                        checksum_algo,checksum_value)
                   VALUES (%s,%s,%s,'text/plain',0,'sha256',%s)""",
                [
                    (record["id"], position, f"component-{position:03}.txt", f"sum-{position}")
                    for position in range(1, 106)
                ],
            )

    def page(offset: int):
        response = client.post("/api/v1/digital-components/search", json={
            "where": {"field": "record_id", "operator": "eq", "value": record["id"]},
            "sort": [{"field": "component_order", "direction": "asc"}],
            "limit": 25,
            "offset": offset,
        })
        assert response.status_code == 200, response.text
        return response.json()

    first = page(0)
    assert first["total"] == 105
    assert first["returned"] == 25
    assert [item["component_order"] for item in first["items"]] == list(range(1, 26))
    second = page(25)
    assert [item["component_order"] for item in second["items"]] == list(range(26, 51))
    last = page(100)
    assert last["returned"] == 5
    assert [item["component_order"] for item in last["items"]] == list(range(101, 106))

    boundary_component = second["items"][0]
    moved = client.post(
        f"/api/v1/records/{record['id']}/digital-components/{boundary_component['id']}/move",
        json={"direction": -1},
    )
    assert moved.status_code == 204, moved.text
    assert page(0)["items"][-1]["id"] == boundary_component["id"]
    assert page(25)["items"][0]["file_name"] == "component-025.txt"

    invalid = client.post(
        f"/api/v1/records/{record['id']}/digital-components/{boundary_component['id']}/move",
        json={"direction": 2},
    )
    assert invalid.status_code == 422


def set_content_settings(client, **values):
    current = {i['key']:i for i in client.get('/api/v1/application-settings').json()['items']}
    response = client.put('/api/v1/application-settings',json={'changes':[
        {'key':key,'expected_version':current[key]['version'],'value':value} for key,value in values.items()]},
        headers={'X-Change-Reason':'Set disposable content test policy'})
    assert response.status_code == 200,response.text


def content_snapshot():
    from backend.services.api.application_settings import load_snapshot
    from psycopg.rows import dict_row
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as connection:
        return load_snapshot(connection)
