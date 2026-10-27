import json
import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from frontend.webui.api_client import ApiError, ErmsApiClient


def test_api_client_bounds_concurrent_page_requests():
    active = 0
    maximum_active = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json={"ok": True})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await asyncio.gather(*(
                client.request("GET", f"/request/{index}") for index in range(20)
            ))
        finally:
            await client.close()

    asyncio.run(exercise())
    assert maximum_active == 4


def test_api_client_coalesces_identical_concurrent_reads_and_isolates_results():
    request_count = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"items": [{"id": 7}]})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            first, second = await asyncio.gather(
                client.request("GET", "/api/v1/reference", params={"limit": 500}),
                client.request("GET", "/api/v1/reference", params={"limit": 500}),
            )
            first["items"][0]["id"] = 99
            return first, second
        finally:
            await client.close()

    first, second = asyncio.run(exercise())
    assert request_count == 1
    assert first["items"][0]["id"] == 99
    assert second["items"][0]["id"] == 7


def test_api_client_does_not_coalesce_mutations():
    request_count = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"ok": True})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await asyncio.gather(
                client.request("POST", "/api/v1/actions", json={"value": 1}),
                client.request("POST", "/api/v1/actions", json={"value": 1}),
            )
        finally:
            await client.close()

    asyncio.run(exercise())
    assert request_count == 2


def test_reference_lists_are_cached_revalidated_and_invalidated_by_mutation():
    requests: list[tuple[str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.headers.get("if-none-match")))
        if request.method == "POST":
            return httpx.Response(200, json={"ok": True})
        if request.headers.get("if-none-match") == '"roles-1"':
            return httpx.Response(304, headers={"ETag": '"roles-1"'})
        return httpx.Response(
            200, json=[{"id": 1, "name": "Custodian"}],
            headers={"ETag": '"roles-1"'},
        )

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            first = await client.list("roles")
            second = await client.list("roles")
            next(iter(client._reference_cache.values()))["checked_at"] = 0
            revalidated = await client.list("roles")
            await client.request("POST", "/api/v1/actions", json={"ok": True})
            after_mutation = await client.list("roles")
            return first, second, revalidated, after_mutation
        finally:
            await client.close()

    values = asyncio.run(exercise())
    assert all(value == [{"id": 1, "name": "Custodian"}] for value in values)
    assert requests == [
        ("GET", None),
        ("GET", '"roles-1"'),
        ("POST", None),
        ("GET", None),
    ]


def test_navigation_can_cancel_an_abandoned_read():
    started = asyncio.Event()

    async def handler(_: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(10)
        return httpx.Response(200, json={"late": True})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            pending = asyncio.create_task(client.request("GET", "/api/v1/slow"))
            await started.wait()
            client.cancel_pending_reads()
            with pytest.raises(asyncio.CancelledError):
                await pending
        finally:
            await client.close()

    asyncio.run(exercise())


def test_dashboard_reviews_fetches_one_small_page_with_lookahead():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=[])

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.dashboard_reviews("overdue", limit=25, offset=50)
        finally:
            await client.close()

    assert asyncio.run(exercise()) == []
    assert captured == {
        "path": "/api/v1/dashboard/reviews",
        "params": {"state": "overdue", "limit": "26", "offset": "50"},
    }


def test_active_people_uses_filtered_server_side_search_page():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"items": [], "total": 0})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.active_people("yahya", limit=25, offset=25)
        finally:
            await client.close()

    assert asyncio.run(exercise()) == {"items": [], "total": 0}
    assert captured["path"] == "/api/v1/users/search"
    assert captured["body"]["limit"] == 25
    assert captured["body"]["offset"] == 25
    assert {condition.get("field") for condition in captured["body"]["where"]["and"][:2]} == {
        "status", "account_type",
    }
    assert len(captured["body"]["where"]["and"][2]["or"]) == 3


def test_localization_catalogue_uses_etag_and_handles_not_modified():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["if_none_match"] = request.headers.get("if-none-match")
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(304, headers={"ETag": '"ar-17"'})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        client.set_session_token("session-token")
        try:
            return await client.localization_catalogue("ar", etag='"ar-16"')
        finally:
            await client.close()

    result = asyncio.run(exercise())
    assert captured == {
        "path": "/api/v1/i18n/catalogues/ar",
        "if_none_match": '"ar-16"',
        "authorization": "Bearer session-token",
    }
    assert result == {"not_modified": True, "etag": '"ar-17"'}


def test_search_builds_controlled_or_grammar():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"items": [{"id": 4}], "total": 1})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.search("records", "annual", ("record_number", "title"))
        finally:
            await client.close()

    rows = asyncio.run(exercise())

    assert rows == [{"id": 4}]
    assert captured["path"] == "/api/v1/records/search"
    assert captured["body"]["where"] == {
        "or": [
            {"field": "record_number", "operator": "contains_ci", "value": "annual"},
            {"field": "title", "operator": "contains_ci", "value": "annual"},
        ]
    }


def test_saved_search_execution_uses_the_dedicated_endpoint():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"items": [], "total": 0})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.execute_saved_search(17, {"limit": 50, "offset": 100})
        finally:
            await client.close()

    asyncio.run(exercise())
    assert captured == {
        "method": "POST", "path": "/api/v1/saved-searches/17/execute",
        "body": {"limit": 50, "offset": 100},
    }


def test_saved_search_update_sends_version_and_reason_headers():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(
            method=request.method, path=request.url.path,
            version=request.headers.get("if-match"),
            reason=request.headers.get("x-change-reason"),
        )
        return httpx.Response(200, json={"id": 8, "version": 4})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.update_saved_search(8, 3, {"name": "Quarterly"}, "Refine criteria")
        finally:
            await client.close()

    asyncio.run(exercise())
    assert captured == {
        "method": "PUT", "path": "/api/v1/saved-searches/8",
        "version": "3", "reason": "Refine criteria",
    }


def test_saved_search_update_does_not_require_a_user_reason():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(
            version=request.headers.get("if-match"),
            reason=request.headers.get("x-change-reason"),
        )
        return httpx.Response(200, json={"id": 8, "version": 4})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.update_saved_search(8, 3, {"name": "Quarterly"})
        finally:
            await client.close()

    asyncio.run(exercise())
    assert captured == {"version": "3", "reason": None}


def test_entity_translation_update_is_locale_scoped_and_versioned():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(
            method=request.method,
            path=request.url.path,
            body=json.loads(request.content),
            version=request.headers.get("if-match"),
            reason=request.headers.get("x-change-reason"),
        )
        return httpx.Response(200, json={"entity_id": 7, "version": 4})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.update_entity_translation(
                "roles", 7, "ar", {"name": "مدير"}, 3, "Add Arabic name"
            )
        finally:
            await client.close()

    asyncio.run(exercise())
    assert captured == {
        "method": "PATCH", "path": "/api/v1/entity-translations/roles/7/ar",
        "body": {"name": "مدير"}, "version": "3", "reason": "Add Arabic name",
    }


def test_classification_search_uses_literal_case_insensitive_containment():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"items": [], "total": 0})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.search("classifications", "finance", ("code", "title"))
        finally:
            await client.close()

    asyncio.run(exercise())
    assert captured["body"]["where"]["or"][0] == {
        "field": "code", "operator": "contains_ci", "value": "finance",
    }


def test_resource_search_can_scope_results_to_an_organizational_owner():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"items": [], "total": 0})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.search(
                "records", "finance", ("record_number", "title"),
                owning_org_unit_id=14,
            )
        finally:
            await client.close()

    asyncio.run(exercise())
    assert captured["body"]["where"]["and"][1] == {
        "field": "owning_org_unit_id", "operator": "eq", "value": 14,
    }


def test_event_history_operations_uses_authoritative_filter_endpoint():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json=["AUTHENTICATION_SUCCEEDED", "CREATE"])

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.event_history_operations()
        finally:
            await client.close()

    assert asyncio.run(exercise()) == ["AUTHENTICATION_SUCCEEDED", "CREATE"]
    assert captured["path"] == "/api/v1/event-history/operations"


def test_event_history_filter_options_uses_authoritative_filter_endpoint():
    captured = {}
    expected = {
        "entity_types": ["aggregation", "user"],
        "operations": ["AUTHENTICATION_SUCCEEDED", "CREATE"],
        "sources": ["api", "web_ui"],
        "actor_types": ["automated_process", "user"],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json=expected)

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.event_history_filter_options()
        finally:
            await client.close()

    assert asyncio.run(exercise()) == expected
    assert captured["path"] == "/api/v1/event-history/filter-options"


def test_my_recent_activity_uses_the_self_only_endpoint():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=[])

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.my_recent_activity(limit=5)
        finally:
            await client.close()

    assert asyncio.run(exercise()) == []
    assert captured == {
        "path": "/api/v1/auth/me/recent-activity",
        "params": {"limit": "5"},
    }


def test_dashboard_summary_uses_one_consolidated_request():
    captured = {}
    expected = {"overview_counts": {"records": 3}}
    since = datetime(2026, 9, 1, tzinfo=timezone.utc)

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=expected)

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.dashboard_summary(recent_limit=7, recent_since=since)
        finally:
            await client.close()

    assert asyncio.run(exercise()) == expected
    assert captured == {
        "method": "GET",
        "path": "/api/v1/dashboard/summary",
        "params": {"recent_limit": "7", "recent_since": since.isoformat()},
    }


def test_resource_acl_normalizes_the_real_api_source_contract():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/records/19/permissions"
        return httpx.Response(200, json={
            "inherit_acl_from_parent": True,
            "effective_acl_source": "parent_default",
            "effective_acl_source_id": 184,
            "effective_acl": [], "override_acl": [],
            "override_acl_is_dormant": True, "resource_acl_version": 3,
        })

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.resource_acl("records", 19)
        finally:
            await client.close()

    result = asyncio.run(exercise())
    assert result["source"] == "parent_default"
    assert result["source_resource_id"] == 184


def test_browse_page_preserves_opaque_cursor_and_scoped_filter():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"items": [], "next_cursor": None, "total": 0})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.browse_page(
                "aggregations/8/records", cursor="opaque-token", query="annual", limit=25,
                owning_org_unit_id=14,
            )
        finally:
            await client.close()

    result = asyncio.run(exercise())
    assert result["total"] == 0
    assert captured["path"] == "/api/v1/browse/aggregations/8/records"
    assert captured["params"] == {
        "limit": "25", "cursor": "opaque-token", "query": "annual",
        "owning_org_unit_id": "14",
    }


def test_personal_classification_recent_activity_uses_audit_events():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/api/v1/event-history/search":
            return httpx.Response(200, json={
                "items": [{"entity_id": 9, "occurred_at": "2026-09-16T10:00:00Z"}],
                "total": 1,
            })
        return httpx.Response(200, json={"id": 9, "code": "FIN", "title": "Finance"})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.recently_created(
                "classifications", actor_user_id=4, limit=4,
            )
        finally:
            await client.close()

    rows = asyncio.run(exercise())
    assert rows[0]["id"] == 9
    event_request = requests[0][2]
    assert {"field": "entity_type", "operator": "eq", "value": "classification"} in event_request["where"]["and"]
    assert {"field": "actor_user_id", "operator": "eq", "value": 4} in event_request["where"]["and"]


def test_update_sends_if_match_version():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["if_match"] = request.headers["if-match"]
        return httpx.Response(200, json={"id": 7, "version": 4})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.update("users", 7, 3, {"name": "New name"})
        finally:
            await client.close()

    result = asyncio.run(exercise())

    assert captured["if_match"] == "3"
    assert result["version"] == 4


def test_webui_requests_identify_their_event_source():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["source"] = request.headers.get("x-event-source")
        return httpx.Response(200, json={"items": [], "total": 0})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.count("records")
        finally:
            await client.close()

    asyncio.run(exercise())
    assert captured["source"] == "web_ui"


def test_delete_sends_if_match_version():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(method=request.method, path=request.url.path, version=request.headers["if-match"])
        return httpx.Response(204)

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.delete("records", 17, 6)
        finally:
            await client.close()

    asyncio.run(exercise())
    assert captured == {"method": "DELETE", "path": "/api/v1/records/17", "version": "6"}


def test_favourite_client_uses_expected_routes():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"aggregations": [], "records": []})
        return httpx.Response(204)

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.favourites()
            await client.favourite("aggregations", 7)
            await client.unfavourite("records", 8)
            with pytest.raises(ValueError):
                await client.favourite("users", 9)
        finally:
            await client.close()

    asyncio.run(exercise())
    assert requests == [
        ("GET", "/api/v1/favourites"),
        ("PUT", "/api/v1/favourites/aggregations/7"),
        ("DELETE", "/api/v1/favourites/records/8"),
    ]


def test_api_error_preserves_conflict_details():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            412,
            json={"detail": {"message": "entity has changed", "current_version": 9}},
        )

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.update("records", 2, 8, {"title": "Stale"})
        finally:
            await client.close()

    with pytest.raises(ApiError) as caught:
        asyncio.run(exercise())

    assert caught.value.status_code == 412
    assert caught.value.detail["current_version"] == 9


def test_membership_navigation_and_delete_use_expected_routes():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, request.headers.get("if-match")))
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"items": [], "total": 0, "limit": 25, "offset": 0})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.user_roles(4)
            await client.role_users(8)
            await client.delete_assignment(12, 3)
        finally:
            await client.close()

    asyncio.run(exercise())
    assert requests == [
        ("GET", "/api/v1/users/4/roles", None),
        ("GET", "/api/v1/roles/8/users", None),
        ("DELETE", "/api/v1/user-role-assignments/12", "3"),
    ]


def test_saved_search_audience_lookup_is_scoped_and_bounded():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"items": [], "total": 0, "limit": 25, "offset": 0})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.saved_search_audience_options(
                "roles", query="aud", ids=[2, 7], limit=25, offset=0,
            )
        finally:
            await client.close()

    asyncio.run(exercise())
    assert captured == {
        "path": "/api/v1/saved-searches/audience-options/roles",
        "params": {"q": "aud", "limit": "25", "offset": "0", "ids": "2,7"},
    }


def test_recently_created_uses_date_sort():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"items": [{"id": 9}], "total": 1})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.recently_created("aggregations")
        finally:
            await client.close()

    assert asyncio.run(exercise()) == [{"id": 9}]
    assert captured["sort"] == [{"field": "date_created", "direction": "desc"}]


def test_recently_updated_uses_self_activity_without_audit_access():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/api/v1/auth/me/recent-activity":
            return httpx.Response(200, json=[{
                "entity_type": "record", "entity_id": 11,
                "operation": "UPDATE", "occurred_at": "2026-09-20T08:00:00Z",
            }])
        assert request.url.path == "/api/v1/records/11"
        return httpx.Response(200, json={"id": 11, "title": "Visible record"})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.recently_updated("records")
        finally:
            await client.close()

    assert asyncio.run(exercise()) == [{
        "id": 11, "title": "Visible record",
        "_activity_at": "2026-09-20T08:00:00Z",
    }]
    assert requests == [
        "/api/v1/auth/me/recent-activity", "/api/v1/records/11",
    ]


def test_recent_resource_activity_hydrates_content_views_for_aggregations():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/api/v1/auth/me/recent-activity":
            return httpx.Response(200, json=[{
                "entity_type": "aggregation", "entity_id": 8,
                "operation": "CONTENT_VIEWED", "occurred_at": "2026-09-25T18:00:00Z",
            }])
        assert request.url.path == "/api/v1/aggregations/8"
        return httpx.Response(200, json={"id": 8, "title": "Parent aggregation"})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.recent_resource_activity("aggregations")
        finally:
            await client.close()

    assert asyncio.run(exercise()) == [{
        "id": 8, "title": "Parent aggregation",
        "_activity_at": "2026-09-25T18:00:00Z",
        "_operation": "CONTENT_VIEWED",
    }]
    assert requests == [
        "/api/v1/auth/me/recent-activity", "/api/v1/aggregations/8",
    ]


@pytest.mark.parametrize(
    ("method_name", "operation"),
    (("recently_created", "CREATE"), ("recently_updated", "UPDATE")),
)
def test_personal_recent_activity_filters_audit_events_by_current_user(
    method_name, operation,
):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/event-history/search":
            captured.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "items": [{"entity_id": 9, "occurred_at": "2026-09-16T01:02:03Z"}],
                    "total": 1,
                },
            )
        assert request.url.path == "/api/v1/records/9"
        return httpx.Response(200, json={"id": 9, "title": "Mine"})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            method = getattr(client, method_name)
            return await method(
                "records", actor_user_id=42, since="2026-08-17T00:00:00+00:00"
            )
        finally:
            await client.close()

    assert asyncio.run(exercise()) == [{
        "id": 9,
        "title": "Mine",
        "_activity_at": "2026-09-16T01:02:03Z",
    }]
    assert captured["where"]["and"] == [
        {"field": "entity_type", "operator": "eq", "value": "record"},
        {"field": "operation", "operator": "eq", "value": operation},
        {"field": "actor_user_id", "operator": "eq", "value": 42},
        {
            "field": "occurred_at",
            "operator": "gte",
            "value": "2026-08-17T00:00:00+00:00",
        },
    ]


def test_count_uses_search_total_without_loading_all_rows():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"items": [{"id": 1}], "total": 417})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.count("records")
        finally:
            await client.close()

    assert asyncio.run(exercise()) == 417
    assert captured == {
        "path": "/api/v1/records/search",
        "body": {"limit": 1, "offset": 0},
    }


def test_login_extracts_opaque_cookie_and_forwards_browser_identity():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["user_agent"] = request.headers["user-agent"]
        return httpx.Response(
            200,
            json={"user": {"id": 1}, "roles": [], "session": {"id": 2}, "must_change_password": False},
            headers={"set-cookie": "erms_session=opaque-token; HttpOnly; Path=/; SameSite=Lax"},
        )

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.login("user@example.org", "secret", user_agent="Browser/Test")
        finally:
            await client.close()

    principal, token = asyncio.run(exercise())
    assert principal["user"]["id"] == 1
    assert token == "opaque-token"
    assert captured["user_agent"] == "Browser/Test"


def test_page_scoped_token_survives_parallel_background_requests():
    authorization_headers = []

    async def handler(request: httpx.Request) -> httpx.Response:
        authorization_headers.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"items": [], "total": 0})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        client.set_session_token("page-specific-token")
        try:
            await asyncio.gather(client.count("records"), client.count("aggregations"))
        finally:
            await client.close()

    asyncio.run(exercise())
    assert authorization_headers == ["Bearer page-specific-token"] * 2


def test_unauthorized_response_clears_page_through_handler():
    handled = []

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "authentication required"})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        client.set_session_token("expired-token")
        client.set_unauthorized_handler(lambda: handled.append(True))
        try:
            with pytest.raises(ApiError):
                await client.me()
        finally:
            await client.close()

    asyncio.run(exercise())
    assert handled == [True]


def test_component_download_view_and_print_use_distinct_authorized_routes():
    paths = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, content=b"document", headers={"content-type": "application/pdf"})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            assert await client.download_component(8) == b"document"
            assert await client.view_component_pdf(8) == b"document"
            assert await client.print_component_pdf(8) == b"document"
        finally:
            await client.close()

    asyncio.run(exercise())
    assert paths == [
        "/api/v1/digital-components/8/content",
        "/api/v1/digital-components/8/rendition",
        "/api/v1/digital-components/8/print-rendition",
    ]


def test_component_page_preserves_server_pagination_and_move_contract():
    captured = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        captured.append((request.method, request.url.path, body))
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={
                "items": [{"id": 31, "component_order": 26}],
                "total": 105, "limit": 25, "offset": 25, "returned": 1,
            })
        return httpx.Response(204)

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            page = await client.component_page(7, limit=25, offset=25)
            await client.move_component(7, 31, -1)
            return page
        finally:
            await client.close()

    page = asyncio.run(exercise())
    assert page["total"] == 105
    search = captured[0]
    assert search[0:2] == ("POST", "/api/v1/digital-components/search")
    assert search[2] == {
        "where": {"field": "record_id", "operator": "eq", "value": 7},
        "sort": [
            {"field": "component_order", "direction": "asc"},
            {"field": "id", "direction": "asc"},
        ],
        "limit": 25,
        "offset": 25,
    }
    assert captured[1] == (
        "POST", "/api/v1/records/7/digital-components/31/move", {"direction": -1},
    )


def test_entity_history_uses_read_only_timeline_route():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["limit"] = request.url.params["limit"]
        return httpx.Response(200, json=[{"id": 1, "operation": "CREATE"}])

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.history("records", 42)
        finally:
            await client.close()

    assert asyncio.run(exercise())[0]["operation"] == "CREATE"
    assert captured == {
        "method": "GET",
        "path": "/api/v1/records/42/history",
        "limit": "200",
    }


def test_authorization_ui_client_uses_explanation_and_custody_endpoints():
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json=[] if request.url.path.endswith("explainable-users") else {})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.explain_access({"resource_type": "record", "resource_id": 1, "operation": "record.view"})
            await client.explainable_users()
            await client.governance_custody()
        finally:
            await client.close()

    asyncio.run(exercise())
    assert seen == [
        ("POST", "/api/v1/authorization/explain"),
        ("GET", "/api/v1/authorization/explainable-users"),
        ("GET", "/api/v1/authorization/governance-custody"),
    ]


def test_security_operations_client_routes_are_read_only():
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.security_summary(hours=48)
            await client.security_reconciliation()
        finally:
            await client.close()

    asyncio.run(exercise())
    assert seen == [
        ("GET", "/api/v1/security-operations/summary", {"hours": "48"}),
        ("GET", "/api/v1/security-operations/reconciliation", {}),
    ]


def test_relationship_page_is_bounded_and_searches_on_the_server():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"items": [], "total": 0, "limit": 25, "offset": 50})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            await client.relationship_page(
                "roles", ("code", "name"), "records", limit=25, offset=50,
                filters={"status": "active"},
            )
        finally:
            await client.close()

    asyncio.run(exercise())
    assert captured["path"] == "/api/v1/roles/search"
    assert captured["payload"]["limit"] == 25
    assert captured["payload"]["offset"] == 50
    assert captured["payload"]["where"] == {"and": [
        {"field": "status", "operator": "eq", "value": "active"},
        {"or": [
            {"field": "code", "operator": "contains_ci", "value": "records"},
            {"field": "name", "operator": "contains_ci", "value": "records"},
        ]},
    ]}


def test_effective_closure_uses_narrow_resource_endpoint():
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"closure": {"id": 9, "date_closed": "2026-01-01"}})

    async def exercise():
        client = ErmsApiClient("http://api.test", transport=httpx.MockTransport(handler))
        try:
            return await client.effective_aggregation_closure(42)
        finally:
            await client.close()

    assert asyncio.run(exercise())["id"] == 9
    assert seen == ["/api/v1/aggregations/42/effective-closure"]


@pytest.mark.parametrize('reason', ['تصحيح الترجمة العربية', 'Arabic العربية — café 100%', 'Plain ASCII reason'])
def test_translation_change_reason_round_trips_as_utf8(reason):
    from starlette.datastructures import Headers
    from backend.services.api.audit_context import decode_change_reason

    async def handler(request: httpx.Request) -> httpx.Response:
        received = Headers(raw=[(name.lower(), value) for name, value in request.headers.raw])['x-change-reason']
        assert decode_change_reason(received) == reason
        assert request.headers['if-match'] == '3'
        return httpx.Response(200, json={'version': 4})

    async def exercise():
        client = ErmsApiClient('http://api.test', transport=httpx.MockTransport(handler))
        try:
            await client.update_localization_translation('test.key', 'ar', {'translated_text': 'ترجمة'}, 3, reason)
            await client.publish_localization_translation('test.key', 'ar', 3, reason)
        finally:
            await client.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(('wire', 'expected'), [
    (None, ''),
    ('Plain ASCII', 'Plain ASCII'),
    ('café', 'café'),
    ('تصحيح عربي', 'تصحيح عربي'),
    ('تصحيح عربي'.encode('utf-8').decode('latin-1'), 'تصحيح عربي'),
])
def test_change_reason_decoder_preserves_supported_inputs(wire, expected):
    from backend.services.api.audit_context import decode_change_reason
    assert decode_change_reason(wire) == expected


def test_classification_relationship_search_requests_eligible_partial_matches():
    captured = {}

    async def handler(request):
        captured['params'] = dict(request.url.params)
        captured['payload'] = __import__('json').loads(request.content)
        return httpx.Response(200, json={'items': [], 'total': 0})

    async def exercise():
        client = ErmsApiClient('http://api.test', transport=httpx.MockTransport(handler))
        try:
            await client.relationship_page(
                'classifications', ('code', 'title', 'description', 'keywords'),
                'part', eligible_classifications=True,
            )
        finally:
            await client.close()

    asyncio.run(exercise())
    assert captured['params'] == {'eligible': 'true'}
    assert captured['payload']['limit'] == 25
    assert captured['payload']['where']['and'] == [{'or': [
        {'field': field, 'operator': 'contains_ci', 'value': 'part'}
        for field in ('code', 'title', 'description', 'keywords')
    ]}]


def test_json_attachment_remains_download_bytes():
    payload = b'{"package_type":"classification_scheme_export"}'
    async def handler(request):
        return httpx.Response(200, content=payload, headers={
            'Content-Type':'application/json',
            'Content-Disposition':'attachment; filename="scheme.json"',
        })
    async def exercise():
        client = ErmsApiClient('http://api.test', transport=httpx.MockTransport(handler))
        try:
            return await client.request('GET','/api/v1/classification-schemes/1/export', params={'format':'json'})
        finally:
            await client.close()
    assert asyncio.run(exercise()) == payload


def test_audit_actor_read_can_cancel_transport_and_retains_normal_auth_headers():
    started = asyncio.Event()
    cancelled = []
    observed = []
    async def handler(request):
        observed.append((request.url.path, request.url.params['q'], request.headers['authorization']))
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
    async def exercise():
        client = ErmsApiClient('http://api.test', transport=httpx.MockTransport(handler))
        client.set_session_token('fixture-token')
        try:
            task = asyncio.create_task(client.audit_actors('Ab', entity_type='record'))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cancelled == [True]
        finally:
            await client.close()
    asyncio.run(exercise())
    assert observed == [('/api/v1/event-history/actors', 'Ab', 'Bearer fixture-token')]


def test_approval_summary_is_cancellable_read_only_post_and_preserves_reference_cache():
    captured=[]
    async def handler(request):
        captured.append(request)
        return httpx.Response(200,json={'proposal_count':0})
    async def exercise():
        client=ErmsApiClient('http://api.test',transport=httpx.MockTransport(handler))
        try:
            client._reference_cache['preserve']={'data':[]}
            result=await client.disposition_approval_summary(8,acting_role_id=7,task_version=3,changes=[],version=2)
            assert result['proposal_count']==0 and 'preserve' in client._reference_cache
        finally:await client.close()
    asyncio.run(exercise())
    assert captured[0].method=='POST' and captured[0].url.path=='/api/v1/disposition/tasks/8/approval-summary'
    assert captured[0].headers['if-match']=='2'
    assert json.loads(captured[0].content)=={'acting_role_id':7,'task_version':3,'changes':[]}
