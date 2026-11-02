import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from backend.services.api.schemas import SearchRequest
from backend.services.api.search import SEARCH_FIELDS, _compile_expression
from backend.services.api.tests.test_phase7_mutation_authorization import (
    _grant_principal, _login_as_phase7, _set_record_acl,
)


def _record(client: TestClient, aggregation_id: int, number: str, title: str) -> dict:
    response = client.post("/api/v1/records", json={
        "aggregation_id": aggregation_id, "record_number": number, "title": title,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _component(
    client: TestClient, record_id: int, order: int, name: str, size: int,
    *, mime_type: str = "application/pdf",
) -> dict:
    response = client.post("/api/v1/digital-components", json={
        "record_id": record_id,
        "component_order": order,
        "file_name": name,
        "mime_type": mime_type,
        "size_in_bytes": size,
        "checksum_algo": "SHA-256",
        "checksum_value": f"{record_id:08x}{order:08x}".ljust(64, "0"),
    })
    assert response.status_code == 201, response.text
    return response.json()


def _search(client: TestClient, where: dict, **extra) -> dict:
    response = client.post("/api/v1/records/search", json={"where": where, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_component_predicates_preserve_same_component_and_boolean_semantics(
    client: TestClient, aggregation: dict,
):
    split = _record(client, aggregation["id"], "CMP-001", "Split properties")
    same = _record(client, aggregation["id"], "CMP-002", "Same properties")
    other = _record(client, aggregation["id"], "CMP-003", "Other component")
    no_component = _record(client, aggregation["id"], "CMP-004", "Record-only branch")
    _component(client, split["id"], 1, "A-large.pdf", 1_000)
    _component(client, split["id"], 2, "B-small.pdf", 50)
    _component(client, same["id"], 1, "A-small.pdf", 50)
    _component(client, other["id"], 1, "C-medium.pdf", 500)

    same_component = _search(client, {"and": [
        {"field": "component.file_name", "operator": "starts_with_ci", "value": "A"},
        {"field": "component.size_in_bytes", "operator": "lt", "value": 100},
    ]})
    assert [item["record_number"] for item in same_component["items"]] == ["CMP-002"]

    nested_component_or = _search(client, {"and": [
        {"field": "component.size_in_bytes", "operator": "lt", "value": 100},
        {"or": [
            {"field": "component.file_name", "operator": "starts_with_ci", "value": "A"},
            {"field": "component.file_name", "operator": "starts_with_ci", "value": "B"},
        ]},
    ]}, sort=[{"field": "record_number", "direction": "asc"}])
    assert [item["record_number"] for item in nested_component_or["items"]] == ["CMP-001", "CMP-002"]

    independent_or = _search(client, {"or": [
        {"field": "component.file_name", "operator": "starts_with_ci", "value": "A"},
        {"field": "component.size_in_bytes", "operator": "eq", "value": 500},
    ]})
    assert {item["record_number"] for item in independent_or["items"]} == {"CMP-001", "CMP-002", "CMP-003"}

    complete_negation = _search(client, {"not": {
        "field": "component.file_name", "operator": "starts_with_ci", "value": "A",
    }})
    assert [item["record_number"] for item in complete_negation["items"]] == ["CMP-003", "CMP-004"]

    mixed = _search(client, {"and": [
        {"field": "title", "operator": "contains_ci", "value": "Same"},
        {"field": "component.mime_type", "operator": "eq", "value": "application/pdf"},
        {"field": "component.checksum_algorithm", "operator": "eq", "value": "SHA-256"},
        {"field": "component.content_status", "operator": "eq", "value": "pending"},
    ]})
    assert [item["record_number"] for item in mixed["items"]] == ["CMP-002"]
    assert mixed["items"][0]["id"] == same["id"]
    assert "file_name" not in mixed["items"][0]

    record_only_alternative = _search(client, {"and": [
        {"field": "title", "operator": "contains_ci", "value": "Record-only"},
        {"or": [
            {"field": "description", "operator": "is_null"},
            {"field": "component.file_name", "operator": "eq", "value": "absent.pdf"},
        ]},
    ]})
    assert [item["id"] for item in record_only_alternative["items"]] == [no_component["id"]]


@pytest.mark.parametrize("field", [
    "component.storage_key", "component.storage_backend", "component.extracted_content",
    "component.file_name; DROP TABLE records; --",
])
def test_component_search_rejects_internal_or_injected_fields(
    client: TestClient, field: str,
):
    response = client.post("/api/v1/records/search", json={
        "where": {"field": field, "operator": "eq", "value": "x"},
    })
    assert response.status_code == 422


def test_component_fields_are_records_only_filters_and_not_sort_fields(
    client: TestClient,
):
    aggregation_response = client.post("/api/v1/aggregations/search", json={
        "where": {"field": "component.file_name", "operator": "eq", "value": "a.pdf"},
    })
    assert aggregation_response.status_code == 422
    sort_response = client.post("/api/v1/records/search", json={
        "sort": [{"field": "component.size_in_bytes", "direction": "asc"}],
    })
    assert sort_response.status_code == 422


def test_record_metadata_combines_with_arabic_component_full_text(
    client: TestClient,
):
    from backend.services.api.tests.test_application_settings_phase4 import save
    assert save(client, {"FULL_TEXT_SEARCH_ENABLED": True}).status_code == 200
    response = client.post("/api/v1/records/search", json={
        "where": {"and": [
            {"field": "title", "operator": "contains_ci", "value": "ملف"},
            {"full_text": {"query": "التقارير", "sources": ["components"]}},
        ]},
        "sort": [{"field": "id", "direction": "desc"}],
        "limit": 25,
        "offset": 0,
        "include": ["full_text_matches"],
    })
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(("field", "operator", "value"), [
    ("component.file_name", "contains_ci", "catalogue"),
    ("component.mime_type", "eq", "application/pdf"),
    ("component.size_in_bytes", "between", [100, 200]),
    ("component.date_created", "gt", "2000-01-01T00:00:00Z"),
    ("component.date_originated", "lt", "2100-01-01T00:00:00Z"),
    ("component.checksum_algorithm", "eq", "SHA-256"),
    ("component.checksum_value", "starts_with_ci", "00000001"),
    ("component.content_status", "eq", "pending"),
])
def test_each_approved_component_field_uses_existing_typed_operators(
    client: TestClient, aggregation: dict, field: str, operator: str, value,
):
    record = _record(client, aggregation["id"], "CMP-CATALOGUE", "Catalogue")
    _component(client, record["id"], 1, "catalogue.pdf", 150)
    result = _search(client, {"field": field, "operator": operator, "value": value})
    assert [item["record_number"] for item in result["items"]] == ["CMP-CATALOGUE"]


def test_saved_search_definition_accepts_and_executes_component_metadata(
    client: TestClient, aggregation: dict,
):
    record = _record(client, aggregation["id"], "CMP-SAVED", "Saved component query")
    _component(client, record["id"], 1, "saved-component.pdf", 25)
    created = client.post("/api/v1/saved-searches", json={
        "name": "Small saved components",
        "definition": {
            "schema_version": 1,
            "resource_type": "record",
            "max_results": 100,
            "request": {
                "where": {"field": "component.size_in_bytes", "operator": "lt", "value": 100},
                "sort": [{"field": "record_number", "direction": "asc"}],
                "limit": 25,
                "offset": 0,
            },
        },
        "audience_mode": "private",
        "role_ids": [],
        "org_unit_ids": [],
    })
    assert created.status_code == 201, created.text
    executed = client.post(f"/api/v1/saved-searches/{created.json()['id']}/execute", json={})
    assert executed.status_code == 200, executed.text
    assert [item["record_number"] for item in executed.json()["items"]] == ["CMP-SAVED"]


def test_component_search_honors_authorization_before_matching(
    client: TestClient, aggregation: dict,
):
    hidden = _record(client, aggregation["id"], "CMP-HIDDEN", "Visible record")
    _component(client, hidden["id"], 1, "secret.pdf", 42)
    _, role_id = _grant_principal({"record.view"})
    _set_record_acl(hidden["id"], role_id, {"record.view"})
    _login_as_phase7(client)

    assert client.get(f"/api/v1/records/{hidden['id']}").status_code == 200
    result = _search(client, {
        "field": "component.file_name", "operator": "eq", "value": "secret.pdf",
    })
    assert result["total"] == 0
    assert result["items"] == []


def test_component_filters_respect_limit_and_use_record_correlation_index(
    client: TestClient, aggregation: dict,
):
    for index in range(3):
        record = _record(client, aggregation["id"], f"CMP-LIM-{index}", f"Limit {index}")
        _component(client, record["id"], 1, f"match-{index}.pdf", index + 1)
    result = _search(
        client,
        {"field": "component.file_name", "operator": "starts_with_ci", "value": "match-"},
        sort=[{"field": "record_number", "direction": "asc"}], limit=2,
    )
    assert result["total"] == 3
    assert result["returned"] == 2

    request = SearchRequest.model_validate({
        "where": {"field": "component.size_in_bytes", "operator": "gt", "value": 0},
    })
    clause, parameters = _compile_expression(
        request.where, SEARCH_FIELDS["records"], resource="records",
        depth=1, condition_counter=[0],
    )
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("SET LOCAL enable_seqscan=off")
        plan = connection.execute(
            sql.SQL("EXPLAIN (COSTS OFF) SELECT resource.id FROM records resource WHERE {}")
            .format(clause),
            parameters,
        ).fetchall()
    assert "digital_components_record_id_idx" in "\n".join(row[0] for row in plan)
