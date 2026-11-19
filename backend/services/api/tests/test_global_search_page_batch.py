"""Compare batched page evidence with the existing per-record reference."""
import os
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest

from backend.services.api.schemas import SearchExpression
from backend.services.api.search import _attribution, _full_text_leaves, _global_retained_current_rows
from backend.services.api.tests.test_full_text_search_phase3 import (
    _grant_phase3_privileges, _publish_component, _upload,
)


@pytest.mark.parametrize('chunk_count', [1, 10, 12, 100])
def test_one_headline_per_component_preserves_snippet_order_and_cap(client, record, chunk_count):
    from .test_application_settings import save
    _grant_phase3_privileges()
    assert save(client, {'FULL_TEXT_SEARCH_ENABLED': True}).status_code == 200
    # Multiple components plus tied/distinct scores protect the exact top-12
    # window, first chunk per component, filename precedence and capped flag.
    for index in range(3):
        component = _upload(client, record, f'evidence-{index}.txt', order=index + 1)
        _publish_component(component, None)
        with psycopg.connect(os.environ['DATABASE_URL']) as c:
            for number in range(chunk_count):
                text = f'Opening {number} ' + 'budget expenditure ' * (1 + number % 4) + f' ending {index}'
                c.execute('''INSERT INTO digital_component_search_chunks
                    (digital_component_id,chunk_no,extracted_text,search_vector,text_search_config)
                    VALUES (%s,%s,%s,to_tsvector('english',%s),'english')''',
                    (component['id'], number, text, text))
    for query in ('budget', 'budget OR evidence', 'budget -draft'):
        expression = SearchExpression.model_validate({'full_text': {'query': query, 'sources': ['components']}})
        with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as c:
            c.execute("SELECT set_config('app.user_id','1',true)")
            legacy_row, = _global_retained_current_rows(c, 'records', expression, [record['id']])
            expected = _attribution(c, 'records', legacy_row, _full_text_leaves(expression), legacy_row['score'])
        response = client.post('/api/v1/full-text-search', json={
            'tab_id': str(uuid4()), 'result_types': ['records'],
            'record_where': expression.model_dump(by_alias=True, exclude_none=True)})
        assert response.status_code == 200, response.text
        item, = response.json()['items']
        assert item['matching_components'] == expected['matching_components']
        assert item['score'] == expected['relevance']


def test_first_and_cached_pages_serialize_resource_timestamps_identically(client):
    from .test_application_settings import save
    _grant_phase3_privileges()
    assert save(client, {"FULL_TEXT_SEARCH_ENABLED": True}).status_code == 200
    timestamp = "2026-01-12T07:06:01.789680+00:00"
    title = "Serialization fixture"
    parent = client.post("/api/v1/aggregations", json={
        "aggregation_number": "TIMESTAMP-A", "title": title,
        "classification_id": 1, "date_opened": timestamp,
    })
    assert parent.status_code == 201
    child = client.post("/api/v1/records", json={
        "record_number": "TIMESTAMP-R", "title": title,
        "aggregation_id": parent.json()["id"], "date_originated": timestamp,
    })
    assert child.status_code == 201
    criteria = {"full_text": {"query": "Serialization", "sources": ["metadata"]}}
    payload = {"tab_id": str(uuid4()), "result_types": ["records", "aggregations"],
               "record_where": criteria, "aggregation_where": criteria}
    first = client.post("/api/v1/full-text-search", json=payload)
    assert first.status_code == 200
    items = first.json()["items"]
    assert {item["type"] for item in items} == {"record", "aggregation"}
    for item in items:
        kind = item["type"]
        assert item[kind]["date_originated" if kind == "record" else "date_opened"] == timestamp
    cached = client.post("/api/v1/full-text-search", json={
        **payload, "search_id": first.json()["search_id"], "page": 1,
    })
    assert cached.status_code == 200
    assert cached.json()["items"] == items


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


def test_only_the_initial_global_ranking_select_runs_with_synchronous_reads(client, record, monkeypatch):
    from backend.services.api import search
    from .test_application_settings import save

    _grant_phase3_privileges()
    assert save(client, {'FULL_TEXT_SEARCH_ENABLED': True}).status_code == 200
    timings_scope = []
    original_rank = search._rank_global_search
    execute = psycopg.Connection.execute

    def observe_sql(connection, statement, *args, **kwargs):
        if isinstance(statement, psycopg.sql.Composable) and 'WITH ranked AS MATERIALIZED' in statement.as_string(connection):
            current = execute(connection, 'SHOW effective_io_concurrency').fetchone()
            timings_scope.append(('ranking', current['effective_io_concurrency']))
        return execute(connection, statement, *args, **kwargs)

    def rank(connection, *args):
        connection.execute('SET LOCAL effective_io_concurrency=37')
        result = original_rank(connection, *args)
        timings_scope.append(('before cache save', connection.execute('SHOW effective_io_concurrency').fetchone()['effective_io_concurrency']))
        return result

    monkeypatch.setattr(psycopg.Connection, 'execute', observe_sql)
    monkeypatch.setattr(search, '_rank_global_search', rank)
    request = {'tab_id': str(uuid4()), 'result_types': ['records'], 'limit': 10,
               'record_where': {'full_text': {'query': 'Example', 'sources': ['metadata']}}}
    first = client.post('/api/v1/full-text-search', json=request)
    assert first.status_code == 200, first.text
    again = client.post('/api/v1/full-text-search', json={**request, 'search_id': first.json()['search_id'], 'page': 1})
    assert again.status_code == 200, again.text
    assert again.json()['items'] == first.json()['items']
    assert timings_scope == [('ranking', '0'), ('before cache save', '37')]
