"""Compare batched page evidence with the existing per-record reference."""
import os
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from backend.services.api.schemas import SearchExpression
from backend.services.api.search import _attribution, _full_text_leaves, _global_retained_current_rows
from backend.services.api.tests.test_full_text_search_phase3 import (
    _grant_phase3_privileges, _publish_component, _upload,
)


def test_page_batch_preserves_evidence_scores_and_capabilities(client, record):
    from .test_application_settings import save
    _grant_phase3_privileges()
    assert save(client, {"FULL_TEXT_SEARCH_ENABLED": True}).status_code == 200
    for index in range(5):
        component = _upload(client, record, f"budget evidence {index}.txt", order=index + 1)
        _publish_component(component, text="approved budget expenditure " * (index + 1))
    expressions = [
        {"full_text": {"query": "budget"}},
        {"full_text": {"query": "Example record", "sources": ["metadata"]}},
        {"full_text": {"query": "approved -draft", "sources": ["components"]}},
        {"or": [{"full_text": {"query": "budget"}}, {"full_text": {"query": "expenditure"}}]},
        {"and": [{"full_text": {"query": "budget"}}, {"field": "id", "operator": "eq", "value": record["id"]}]},
    ]
    expected_capabilities = client.get(f"/api/v1/records/{record['id']}/capabilities").json()["capabilities"]
    for expression in expressions:
        payload = {"tab_id": str(uuid4()), "result_types": ["records"], "record_where": expression, "limit": 10}
        first = client.post("/api/v1/full-text-search", json=payload)
        assert first.status_code == 200, first.text
        cached = client.post("/api/v1/full-text-search", json={**payload, "search_id": first.json()["search_id"], "page": 1})
        assert cached.status_code == 200, cached.text
        assert cached.json()["items"] == first.json()["items"]
        item, = first.json()["items"]
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
            connection.execute("SELECT set_config('app.user_id','1',true)")
            parsed = SearchExpression.model_validate(expression)
            legacy_row, = _global_retained_current_rows(connection, "records", parsed, [record["id"]])
            expected = _attribution(connection, "records", legacy_row, _full_text_leaves(parsed), legacy_row["score"])
        assert item["score"] == expected["relevance"]
        assert item["matched_record_metadata"] == expected["metadata_matched"]
        assert item["matching_components"] == expected["matching_components"]
        assert item["record_capabilities"] == {
            key: expected_capabilities[key] for key in ("list_components", "has_previewable_component")
        }
    # Saved ranking scores do not replace fresh page evidence/scores. Filename
    # matches remain, but replacing the text must remove stale snippets/ranks.
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("""UPDATE digital_component_search_chunks
            SET extracted_text='changed evidence',
                search_vector=to_tsvector(text_search_config,'changed evidence')""")
    refreshed = client.post("/api/v1/full-text-search", json={
        **payload, "search_id": first.json()["search_id"], "page": 1,
    })
    assert refreshed.status_code == 200, refreshed.text
    refreshed_item, = refreshed.json()["items"]
    assert refreshed_item["score"] == 0
    assert refreshed_item["matching_components"]
    assert all(component["snippet"] is None for component in refreshed_item["matching_components"])


def test_metadata_and_additional_file_candidates_keep_overlap_evidence_and_order(client, record):
    from .test_application_settings import save
    _grant_phase3_privileges()
    assert save(client, {"FULL_TEXT_SEARCH_ENABLED": True}).status_code == 200
    records = [record]
    for title in ("File evidence only", "Example metadata only"):
        response = client.post("/api/v1/records", json={
            "aggregation_id": record["aggregation_id"], "title": title,
            "record_number": f"PAGE-BATCH-{len(records)}",
        })
        assert response.status_code == 201, response.text
        records.append(response.json())
    for row in records[:2]:
        component = _upload(client, row, "evidence.txt")
        _publish_component(component, text="contentonly evidence")
    expression = SearchExpression.model_validate({"full_text": {"query": "Example OR contentonly"}})
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('app.user_id','1',true)")
        legacy = _global_retained_current_rows(connection, "records", expression, [row["id"] for row in records])
        expected = sorted([(row["id"], row["score"]) for row in legacy], key=lambda row: (-row[1], row[0]))
    payload = {"tab_id": str(uuid4()), "result_types": ["records"],
               "record_where": expression.model_dump(by_alias=True, exclude_none=True), "limit": 2}
    first = client.post("/api/v1/full-text-search", json=payload)
    assert first.status_code == 200, first.text
    following = client.post("/api/v1/full-text-search", json={**payload, "cursor": first.json()["next_cursor"]})
    assert following.status_code == 200, following.text
    items = first.json()["items"] + following.json()["items"]
    assert [(item["record"]["id"], item["score"]) for item in items] == expected
    by_id = {item["record"]["id"]: item for item in items}
    assert by_id[records[0]["id"]]["matched_record_metadata"]
    assert by_id[records[0]["id"]]["matching_components"]
    assert not by_id[records[1]["id"]]["matched_record_metadata"]
    assert by_id[records[1]["id"]]["matching_components"]
    assert by_id[records[2]["id"]]["matched_record_metadata"]
    assert by_id[records[2]["id"]]["matching_components"] == []
