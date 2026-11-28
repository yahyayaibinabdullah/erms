"""Creation guarantees that custom generators must preserve (CG-06 and CG-10)."""

import os

import psycopg
from psycopg.rows import dict_row
import pytest

from backend.services.api.content_storage import configured_storage


def stage_document(client, draft_id, content):
    response = client.post(
        f"/api/v1/record-drafts/{draft_id}/components",
        data={"component_order": "1"},
        files={"file": ("numbered-document.txt", content, "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def assert_staged_document(client, draft_id, component, content):
    assert client.get(f"/api/v1/record-drafts/{draft_id}/components").json() == [
        component
    ]
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        assert configured_storage().read_draft(connection, component["id"]) == content


@pytest.mark.parametrize("number_input", [{}, {"record_number": None}])
def test_numberless_draft_saves_and_reopens_with_staged_document(
    client, aggregation, number_input
):
    created = client.post(
        "/api/v1/record-drafts",
        json={"aggregation_id": aggregation["id"], **number_input},
    )
    assert created.status_code == 201, created.text
    draft_id = created.json()["id"]
    component = stage_document(client, draft_id, b"An unfinished document")

    saved = client.patch(
        f"/api/v1/record-drafts/{draft_id}",
        json={"title": "Unfinished work", "record_number": None},
    )
    assert saved.status_code == 200, saved.text
    reopened = client.get(f"/api/v1/record-drafts/{draft_id}")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["record_number"] is None
    assert reopened.json()["title"] == "Unfinished work"
    assert client.get("/api/v1/records").json() == []
    assert_staged_document(
        client, draft_id, component, b"An unfinished document"
    )


def test_duplicate_final_number_preserves_draft_metadata_and_staged_document(
    client, record
):
    number = record["record_number"]
    created = client.post(
        "/api/v1/record-drafts",
        json={
            "aggregation_id": record["aggregation_id"],
            "record_number": number,
            "title": "Document already contains the chosen number",
            "description": "Keep this work after a numbering conflict",
        },
    )
    assert created.status_code == 201, created.text
    draft = created.json()
    component = stage_document(client, draft["id"], number.encode("utf-8"))

    failed = client.post(f"/api/v1/record-drafts/{draft['id']}/commit")
    assert failed.status_code == 409, failed.text
    reopened = client.get(f"/api/v1/record-drafts/{draft['id']}")
    assert reopened.status_code == 200, reopened.text
    for field in ("record_number", "title", "description"):
        assert reopened.json()[field] == draft[field]
    assert_staged_document(client, draft["id"], component, number.encode("utf-8"))
    assert client.get(f"/api/v1/records/{record['id']}").json()["record_number"] == number
    assert len(client.get("/api/v1/records").json()) == 1
