"""Audit page selection must not project the entire immutable history."""
import os

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row

from backend.services.api.schemas import SearchRequest
from backend.services.api.search import search_rows
from backend.services.api.tests.test_phase7_mutation_authorization import (
    _grant_principal, _login_as_phase7,
)


def nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from nodes(child)


@pytest.mark.parametrize("offset", [0, 50, 990])
def test_only_returned_page_projects_resource_history(client, aggregation, offset):
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('app.event_source','seeding',true)")
        connection.execute("""INSERT INTO event_history
            (entity_type,entity_id,operation,occurred_at,actor_name,after_state)
            SELECT 'aggregation',%s,'AUDIT_PAGE_PROBE',
                   '2025-01-01'::timestamptz + (n/3)*interval '1 second',
                   'Immutable actor',jsonb_build_object('title','Historical title '||n)
              FROM generate_series(1,1105) n""", (aggregation["id"],))
        connection.commit()
        connection.execute("SELECT set_config('app.user_id','1',true)")

        class Recorder:
            info = connection.info

            def __init__(self):
                self.queries = []

            def execute(self, query, params=None):
                self.queries.append((query, params))
                return connection.execute(query, params)

        recorder = Recorder()
        payload = {"where": {"field": "operation", "operator": "eq", "value": "AUDIT_PAGE_PROBE"},
                   "limit": 50, "offset": offset}
        result = search_rows(recorder, "event_history", SearchRequest.model_validate(payload))
        expected_size = min(50, 1000-offset)
        assert result["total"] == result["result_cap"] == 1000
        assert result["truncated"] and len(result["items"]) == expected_size
        expected = connection.execute("""SELECT id FROM event_history
            WHERE operation='AUDIT_PAGE_PROBE' ORDER BY occurred_at DESC,id DESC
            LIMIT %s OFFSET %s""", (expected_size, offset)).fetchall()
        assert [row["id"] for row in result["items"]] == [row["id"] for row in expected]
        assert all(row["actor_name"] == "Immutable actor" for row in result["items"])
        query, params = next((q, p) for q, p in recorder.queries if "_fts_relevance" in str(q))
        plan = connection.execute(sql.SQL("EXPLAIN (ANALYZE,VERBOSE,FORMAT JSON) ") + query,
                                  params).fetchone()["QUERY PLAN"][0]["Plan"]
        projections = [node for node in nodes(plan) if node["Node Type"] == "Result"
                       and any(value.startswith("current_user_can_view_event_resource(")
                               for value in node.get("Output", []))]
        assert projections
        assert sum(node["Actual Rows"] * node["Actual Loops"] for node in projections) == expected_size
        response = client.post("/api/v1/event-history/search", json=payload)
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()["items"]] == [row["id"] for row in expected]


def test_actor_filter_and_sort_use_redacted_values_before_page_selection(client, aggregation):
    _grant_principal({"audit.view"}, clearance_code="G")
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("SELECT set_config('app.event_source','seeding',true)")
        connection.execute("UPDATE aggregations SET security_level_id=(SELECT id FROM security_levels WHERE code='S') WHERE id=%s",
                           (aggregation["id"],))
        hidden = connection.execute("""INSERT INTO event_history
            (entity_type,entity_id,operation,actor_name,after_state)
            VALUES ('aggregation',%s,'AUDIT_ACTOR_PROBE','Protected actor','{"title":"Secret"}')
            RETURNING id""", (aggregation["id"],)).fetchone()["id"]
        visible = connection.execute("""INSERT INTO event_history
            (entity_type,entity_id,operation,actor_name)
            VALUES ('user',1,'AUDIT_ACTOR_PROBE','Visible actor') RETURNING id""").fetchone()["id"]
    _login_as_phase7(client)
    scope = {"field": "operation", "operator": "eq", "value": "AUDIT_ACTOR_PROBE"}
    response = client.post("/api/v1/event-history/search", json={"where": scope, "limit": 1,
                           "sort": [{"field": "actor_name", "direction": "asc"}]})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 2 and response.json()["items"][0]["id"] == visible
    hidden_page = client.post("/api/v1/event-history/search", json={"where": scope, "limit": 1,
                              "sort": [{"field": "actor_name", "direction": "asc"}], "offset": 1}).json()
    assert hidden_page["items"][0]["id"] == hidden
    assert hidden_page["items"][0]["actor_name"] is None
    assert hidden_page["items"][0]["after_state"] is None
    assert hidden_page["items"][0]["metadata"]["redacted"]
    for name, expected in (("Protected actor", 0), ("Visible actor", 1)):
        response = client.post("/api/v1/event-history/search", json={"where": {"and": [scope,
                               {"field": "actor_name", "operator": "eq", "value": name}]}, "limit": 1})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == expected
        assert len(response.json()["items"]) == expected


def test_audit_search_still_requires_audit_privilege(client):
    _grant_principal(set())
    _login_as_phase7(client)
    assert client.post("/api/v1/event-history/search", json={"limit": 50}).status_code == 403
