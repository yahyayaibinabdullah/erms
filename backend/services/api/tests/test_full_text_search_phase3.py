from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from backend.services.api.authentication import hash_password


def _grant_phase3_privileges() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            """UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='ALL_PRIVS')
                WHERE code='system-administrator'"""
        )


def _upload(client, record: dict, name: str = "approved-budget.txt", *, order: int = 1) -> dict:
    response = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": order},
        files={"file": (name,b"approved budget expenditure evidence","text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _publish_component(
    component: dict,
    text: str | None = "The board approved the annual budget expenditure ceiling.",
    *,
    configuration: str = "pg_catalog.english",
) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        document = connection.execute(
            "SELECT * FROM digital_component_search_documents WHERE digital_component_id=%s",
            (component["id"],),
        ).fetchone()
        connection.execute("DELETE FROM content_indexing_jobs WHERE digital_component_id=%s",(component["id"],))
        connection.execute(
            """UPDATE digital_component_search_documents SET status='indexed',indexed_at=CURRENT_TIMESTAMP
                WHERE digital_component_id=%s""",(component["id"],),
        )
        if text is not None:
            connection.execute(
                """INSERT INTO digital_component_search_chunks(
                       digital_component_id,chunk_no,extracted_text,search_vector,text_search_config)
                   VALUES (%s,0,%s,to_tsvector(%s::regconfig,%s),%s::regconfig)""",
                (component["id"], text, configuration, text, configuration),
            )


def test_full_text_grammar_ranking_attribution_and_debug(client, record):
    _grant_phase3_privileges()
    component = _upload(client,record)
    _publish_component(component)
    payload = {
        "where":{"and":[
            {"field":"aggregation_id","operator":"eq","value":record["aggregation_id"]},
            {"full_text":{"query":"approved budget -draft","sources":["components","metadata"]}},
        ]},
        "sort":[{"field":"_relevance","direction":"desc"}],
        "include":["full_text_matches"],"debug":True,"limit":25,
    }
    response=client.post("/api/v1/records/search",json=payload)
    assert response.status_code==200,response.text
    result=response.json()
    assert [item["id"] for item in result["items"]]==[record["id"]]
    assert result["items"][0]["_search"]["matching_components"][0]["id"]==component["id"]
    assert "⟦" in result["items"][0]["_search"]["matching_components"][0]["snippet"]
    assert result["items"][0]["_search"]["matching_components"][0]["leaf_ids"]==["fts_1"]
    match = result["items"][0]["_search"]["matching_components"][0]
    assert (match["mime_type"], match["content_status"]) == ("text/plain", "available")
    assert result["_debug"]["received_request"]==payload
    assert result["_debug"]["canonical_query"]["sort"][-1]=={"field":"id","direction":"asc"}
    serialized=str(result["_debug"]).lower()
    assert all(secret not in serialized for secret in ("select ","cookie","authorization","password","lease_token"))


def test_preview_pages_count_only_supported_available_components_and_find_the_selected_page(client, record):
    _grant_phase3_privileges()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            """INSERT INTO digital_components(record_id,component_order,file_name,mime_type,
                                              size_in_bytes,checksum_algo,checksum_value)
               SELECT %s,i,'pending.pdf','application/pdf',0,'sha256','pending'
                 FROM generate_series(1,51) i""",
            (record["id"],),
        )
    first = _upload(client, record, "first.TXT", order=52)
    second = _upload(client, record, "second.txt", order=90)
    unsupported = _upload(client, record, ".txt", order=99)
    path = f"/api/v1/records/{record['id']}"
    capabilities = client.get(f"{path}/capabilities").json()["capabilities"]
    assert capabilities["component_count"] == 54
    assert capabilities["has_previewable_component"] is True
    page_url = f"{path}/digital-components/previewable"
    page = client.get(page_url, params={"limit": 1})
    assert page.status_code == 200, page.text
    assert page.json() == {"items": [first], "total": 2, "offset": 0, "limit": 1, "returned": 1}
    focused = client.get(page_url, params={"limit": 1, "selected_component_id": second["id"]})
    assert focused.status_code == 200, focused.text
    assert focused.json() == {"items": [second], "total": 2, "offset": 1, "limit": 1, "returned": 1}
    assert client.get(page_url, params={"limit": 1, "offset": 1}).json() == focused.json()
    assert client.get(page_url, params={"selected_component_id": unsupported["id"]}).status_code == 404
    assert client.get(page_url, params={"limit": 101}).status_code == 422


def test_full_text_validation_and_non_indexable_queries(client, record):
    invalid=client.post("/api/v1/aggregations/search",json={
        "where":{"full_text":{"query":"budget","sources":["components"]}}
    })
    assert invalid.status_code==422
    raw=client.post("/api/v1/records/search",json={
        "where":{"full_text":{"query":"budget","sources":["metadata"],"configuration":"english"}}
    })
    assert raw.status_code==422
    stop=client.post("/api/v1/records/search",json={"where":{"full_text":{"query":"---"}}})
    assert stop.status_code==422 and stop.json()["detail"]["code"]=="non_indexable_full_text_query"
    relevance=client.post("/api/v1/records/search",json={"sort":[{"field":"_relevance"}]})
    assert relevance.status_code==422


def test_component_and_record_reindex_are_forced_bounded_and_status_safe(client, record):
    _grant_phase3_privileges()
    component=_upload(client,record)
    _publish_component(component)
    first=client.post(f"/api/v1/digital-components/{component['id']}/reindex")
    assert first.status_code==202,first.text
    assert first.json()["already_in_progress"] is False
    duplicate=client.post(f"/api/v1/digital-components/{component['id']}/reindex")
    assert duplicate.status_code==202 and duplicate.json()["attempt_id"]==first.json()["attempt_id"]
    assert duplicate.json()["already_in_progress"] is True
    status=client.get(first.json()["status_url"])
    assert status.status_code==200 and status.json()["digital_component_id"]==component["id"]
    batch=client.post(f"/api/v1/records/{record['id']}/reindex")
    assert batch.status_code==202,batch.text
    assert batch.json()["total_components"]==1
    assert batch.json()["already_in_progress"]==1
    batch_status=client.get(batch.json()["status_url"])
    assert batch_status.status_code==200
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        operations=connection.execute(
            """SELECT operation FROM event_history
                WHERE operation IN ('CONTENT_REINDEX_REQUESTED','RECORD_CONTENT_REINDEX_REQUESTED')
                ORDER BY id"""
        ).fetchall()
        assert [row[0] for row in operations]==[
            'CONTENT_REINDEX_REQUESTED','CONTENT_REINDEX_REQUESTED','RECORD_CONTENT_REINDEX_REQUESTED'
        ]


def test_global_search_requires_matching_branches_and_returns_opaque_cursor_contract(client, record, aggregation):
    _grant_phase3_privileges()
    component=_upload(client,record)
    _publish_component(component)
    payload={
        "record_where":{"full_text":{"query":"approved budget","sources":["components"]}},
        "aggregation_where":{"full_text":{"query":"root aggregation","sources":["metadata"]}},
        "result_types":["records","aggregations"],"limit":1,
    }
    first=client.post("/api/v1/full-text-search",json=payload)
    assert first.status_code==200,first.text
    body=first.json(); assert len(body["items"])==1 and body["next_cursor"]
    assert "totals" not in body
    assert set(body["index_freshness"])=={"has_pending_content"}
    counted=client.post("/api/v1/full-text-search",json={**payload,"include_totals":True})
    assert counted.status_code==200,counted.text
    assert counted.json()["totals"]=={"records":1,"aggregations":1}
    assert counted.json()["items"]==body["items"]
    second=client.post("/api/v1/full-text-search",json={**payload,"cursor":body["next_cursor"]})
    assert second.status_code==200 and len(second.json()["items"])==1
    assert "totals" not in second.json()
    for item in body["items"] + second.json()["items"]:
        resource = item[item["type"]]
        assert isinstance(resource["security_level_id"], int)
        assert "description" in resource
    mismatch=client.post("/api/v1/full-text-search",json={
        "record_where":payload["record_where"],"result_types":["records","aggregations"]
    })
    assert mismatch.status_code==422


def test_global_search_saved_list_is_bound_to_tab_and_login_and_expires(client, record):
    _grant_phase3_privileges()
    advanced = client.post("/api/v1/records/advanced-search", json={"limit": 1})
    assert advanced.status_code == 200, advanced.text
    assert [item["id"] for item in advanced.json()["items"]] == [record["id"]]
    tab = str(uuid4())
    payload = {
        "tab_id": tab, "result_types": ["records"],
        "record_where": {"full_text": {"query": "Example record"}}, "include_totals": True,
    }
    endpoint = "/api/v1/full-text-search"
    first = client.post(endpoint, json=payload)
    assert first.status_code == 200, first.text
    first_page = {**payload, "search_id": first.json()["search_id"]}
    assert client.post(endpoint, json={**first_page, "tab_id": str(uuid4())}).status_code == 410
    other_tab = client.post(endpoint, json={**payload, "tab_id": str(uuid4())})
    assert other_tab.status_code == 200, other_tab.text
    assert client.post(endpoint, json=first_page).status_code == 200

    replacement = client.post(endpoint, json=payload)
    assert replacement.status_code == 200, replacement.text
    assert client.post(endpoint, json=first_page).status_code == 410
    current_page = {**payload, "search_id": replacement.json()["search_id"]}
    original_cookies = dict(client.cookies)
    client.cookies.clear()
    login = client.post("/api/v1/auth/login", json={
        "email": "admin@test.invalid", "password": "Temporary-Test-Password-123!",
    })
    assert login.status_code == 200, login.text
    client.headers["X-CSRF-Token"] = client.cookies["erms_csrf"]
    assert client.post(endpoint, json=current_page).status_code == 410
    client.cookies.clear()
    client.cookies.update(original_cookies)
    client.headers["X-CSRF-Token"] = client.cookies["erms_csrf"]
    assert client.post(endpoint, json=current_page).status_code == 200

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "UPDATE search_results_cache SET expires_at=clock_timestamp() WHERE search_id=%s",
            (current_page["search_id"],),
        )
    assert client.post(endpoint, json=current_page).status_code == 410
    from backend.services.api.session_cleanup import cleanup_search_cache
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        cleanup_search_cache(connection, batch_size=25)
        assert connection.execute(
            "SELECT 1 FROM search_results_cache WHERE search_id=%s", (current_page["search_id"],),
        ).fetchone() is None


def test_global_and_advanced_search_caps_keep_browse_available(client, aggregation):
    _grant_phase3_privileges()
    from backend.services.api.tests.test_application_settings import save
    assert save(client, {"SEARCH_RESULT_LIMIT": 3, "GLOBAL_SEARCH_CACHE_IDLE_MINUTES": 7}).status_code == 200
    assert save(client, {"SEARCH_RESULT_LIMIT": 5001}).status_code == 422
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("""INSERT INTO aggregations
            (aggregation_number, title, classification_id, owning_org_unit_id, security_level_id)
            SELECT 'CAP-' || n, 'Root aggregation', classification_id, owning_org_unit_id, security_level_id
            FROM aggregations CROSS JOIN generate_series(1,3) n WHERE id=%s""", (aggregation["id"],))
    payload = {
        "aggregation_where": {"full_text": {"query": "root aggregation"}},
        "result_types": ["aggregations"], "limit": 1, "include_totals": True, "tab_id": str(uuid4()),
    }
    first = client.post("/api/v1/full-text-search", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["totals"] == {"aggregations": 3}
    assert first.json()["truncated"] is True
    assert first.json()["result_cap"] == 3
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        seconds = connection.execute(
            "SELECT extract(epoch FROM expires_at - clock_timestamp()) FROM search_results_cache WHERE search_id=%s",
            (first.json()["search_id"],),
        ).fetchone()[0]
    assert 400 < seconds <= 420
    missing_tab = {key: value for key, value in payload.items() if key != "tab_id"}
    missing_tab["cursor"] = first.json()["next_cursor"]
    assert client.post("/api/v1/full-text-search", json=missing_tab).status_code == 410
    next_payload = {**payload, "cursor": first.json()["next_cursor"]}
    second = client.post("/api/v1/full-text-search", json=next_payload)
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 1
    assert second.json()["next_cursor"]
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("UPDATE aggregations SET title='Different topic' WHERE id=%s",
                           (second.json()["items"][0]["aggregation"]["id"],))
    rechecked = client.post("/api/v1/full-text-search", json=next_payload)
    assert rechecked.status_code == 200, rechecked.text
    assert rechecked.json()["items"] != second.json()["items"]
    assert len(rechecked.json()["items"]) == 1 and rechecked.json()["next_cursor"] is None
    search_page = {"where": payload["aggregation_where"], "limit": 2, "offset": 1}
    assert save(client, {"SEARCH_RESULT_LIMIT": 2}).status_code == 200
    assert client.post("/api/v1/full-text-search", json=next_payload).status_code == 410
    assert client.post("/api/v1/aggregations/advanced-search", json={**search_page, "max_results": 3}).status_code == 422
    capped = client.post("/api/v1/aggregations/advanced-search", json=search_page)
    assert capped.status_code == 200, capped.text
    assert capped.json()["total"] == 2 and capped.json()["truncated"]
    assert len(capped.json()["items"]) == 1
    denied = client.post("/api/v1/aggregations/advanced-search", json={**search_page, "offset": 2})
    assert denied.status_code == 422
    browse = client.post("/api/v1/aggregations/search", json=search_page)
    assert browse.status_code == 200 and browse.json()["total"] == 3
    assert save(client, {"SEARCH_RESULT_LIMIT": 3}).status_code == 200
    assert client.post("/api/v1/full-text-search", json=next_payload).status_code == 410


def test_global_search_can_rebuild_on_requested_page_and_continue(client, aggregation):
    _grant_phase3_privileges()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("""INSERT INTO aggregations
            (aggregation_number, title, classification_id, owning_org_unit_id, security_level_id)
            SELECT 'REBUILD-' || n, 'Rebuild evidence', classification_id, owning_org_unit_id, security_level_id
            FROM aggregations CROSS JOIN generate_series(1,7) n WHERE id=%s""", (aggregation["id"],))
    endpoint = "/api/v1/full-text-search"
    where = {"full_text": {"query": "Rebuild evidence"}}
    payload = {"record_where": where, "aggregation_where": where, "result_types": ["records", "aggregations"],
               "result_filter": "aggregation", "limit": 2, "include_totals": True, "tab_id": str(uuid4())}
    first = client.post(endpoint, json=payload).json()
    second = client.post(endpoint, json={**payload, "cursor": first["next_cursor"]}).json()
    third = client.post(endpoint, json={**payload, "cursor": second["next_cursor"]}).json()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("DELETE FROM search_results_cache WHERE search_id=%s", (first["search_id"],))
    assert client.post(endpoint, json={**payload, "cursor": second["next_cursor"]}).status_code == 410
    rebuilt = client.post(endpoint, json={**payload, "page": 3})
    assert rebuilt.status_code == 200, rebuilt.text
    rebuilt = rebuilt.json()
    assert rebuilt["page"] == 3 and rebuilt["items"] == third["items"]
    assert rebuilt["search_id"] != first["search_id"]
    assert rebuilt["totals"] == {"records": 0, "aggregations": 7}
    previous = client.post(endpoint, json={**payload, "search_id": rebuilt["search_id"], "page": 2})
    assert previous.json()["items"] == second["items"]
    last = client.post(endpoint, json={**payload, "cursor": rebuilt["next_cursor"]}).json()
    assert len(last["items"]) == 1 and not last["next_cursor"]
    assert client.post(endpoint, json={**payload, "page": 3, "cursor": rebuilt["next_cursor"]}).status_code == 422
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("UPDATE aggregations SET title='Changed' WHERE aggregation_number IN ('REBUILD-5','REBUILD-6','REBUILD-7')")
    clamped = client.post(endpoint, json={**payload, "page": 3}).json()
    assert clamped["page"] == 2 and len(clamped["items"]) == 2
    assert not clamped["next_cursor"]


def test_global_search_respects_component_view_for_file_names_and_indexed_text(client, record):
    _grant_phase3_privileges()
    file_match = _upload(client, record, "filenameonly evidence.txt")
    _publish_component(file_match, text=None)
    content_match = _upload(client, record, "evidence.txt", order=2)
    _publish_component(content_match, text="contentonly")
    arabic_match = _upload(client, record, "arabic.txt", order=3)
    _publish_component(arabic_match, text="وثائق", configuration="pg_catalog.arabic")
    legacy_match = _upload(client, record, "legacy.txt", order=4)
    _publish_component(legacy_match, text="archives", configuration="pg_catalog.french")

    tab_id = str(uuid4())

    def search(query: str, search_id: str | None = None) -> dict:
        response = client.post("/api/v1/full-text-search", json={
            "record_where": {"full_text": {"query": query}},
            "result_types": ["records"],
            "include_totals": True,
            "tab_id": tab_id,
            "search_id": search_id,
        })
        assert response.status_code == 200, response.text
        return response.json()

    component_queries = {
        "filenameonly": file_match, "contentonly": content_match, "وثائق": arabic_match, "archives": legacy_match,
    }
    for query, component in component_queries.items():
        result = search(query)
        assert result["totals"] == {"records": 1}
        item, = result["items"]
        assert item["record"]["id"] == record["id"]
        assert not item["matched_record_metadata"]
        assert [match["id"] for match in item["matching_components"]] == [component["id"]]
    cached_search_id = result["search_id"]

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        profile_id = connection.execute(
            "INSERT INTO profiles(code,name) VALUES ('SEARCH_RECORD_ONLY','Record search only') RETURNING id"
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO profile_privileges(profile_id,privilege_id)
               SELECT %s,id FROM privileges WHERE code IN ('aggregation.view','record.view')""",
            (profile_id,),
        )
        connection.execute("UPDATE roles SET profile_id=%s WHERE code='system-administrator'", (profile_id,))

    assert search("archives", cached_search_id)["items"] == []
    for query in component_queries:
        result = search(query)
        assert result["totals"] == {"records": 0}
        assert result["items"] == []
    metadata_result = search("Example record")
    item, = metadata_result["items"]
    assert item["record"]["id"] == record["id"]
    assert item["matched_record_metadata"]
    assert item["matching_components"] == []


def test_reindex_requires_global_privilege_in_addition_to_resource_access(client, record):
    component=_upload(client,record)
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            "INSERT INTO profiles(code,name) VALUES ('NO_REINDEX','No Reindex') ON CONFLICT DO NOTHING"
        )
        profile_id=connection.execute("SELECT id FROM profiles WHERE code='NO_REINDEX'").fetchone()[0]
        connection.execute("UPDATE roles SET profile_id=%s WHERE code='system-administrator'",(profile_id,))
    response=client.post(f"/api/v1/digital-components/{component['id']}/reindex")
    assert response.status_code==403
    assert response.json()["detail"]["code"]=="insufficient_privilege"
    diagnostic=client.post("/api/v1/records/search",json={
        "where":{"field":"id","operator":"eq","value":record["id"]},"debug":True,
    })
    assert diagnostic.status_code==403
    assert diagnostic.json()["detail"]["code"]=="insufficient_privilege"
    ordinary=client.post("/api/v1/records/search",json={
        "where":{"field":"id","operator":"eq","value":record["id"]},
    })
    assert ordinary.status_code==200 and "_debug" not in ordinary.json()


def test_sys_admin_privilege_does_not_bypass_resource_acl_or_disclose_search(client, record):
    component=_upload(client,record)
    _publish_component(component)
    password="Phase3-SysAdmin-Password-123!"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        user_id=connection.execute(
            "INSERT INTO users(name,email) VALUES ('Platform only','platform@test.invalid') RETURNING id"
        ).fetchone()[0]
        role_id=connection.execute(
            """INSERT INTO roles(org_unit_id,code,name,profile_id,security_level_id)
               SELECT 1,'PLATFORM_ONLY','Platform only',profile.id,level.id
                 FROM profiles profile CROSS JOIN security_levels level
                WHERE profile.code='SYS_ADMIN' AND level.level_number=(SELECT max(level_number) FROM security_levels)
               RETURNING id"""
        ).fetchone()[0]
        connection.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)",(user_id,role_id))
        connection.execute(
            "INSERT INTO user_credentials(user_id,password_hash,must_change_password) VALUES (%s,%s,false)",
            (user_id,hash_password(password)),
        )
    client.cookies.clear(); client.headers.pop("X-CSRF-Token",None)
    login=client.post("/api/v1/auth/login",json={"email":"platform@test.invalid","password":password})
    assert login.status_code==200
    client.headers["X-CSRF-Token"]=client.cookies.get("erms_csrf")
    search=client.post("/api/v1/records/search",json={
        "where":{"full_text":{"query":"approved budget"}},"include":["full_text_matches"],
    })
    assert search.status_code==200 and search.json()["items"]==[] and search.json()["total"]==0
    global_search=client.post("/api/v1/full-text-search",json={
        "record_where":{"full_text":{"query":"approved budget"}},
        "aggregation_where":{"full_text":{"query":"root aggregation"}},
        "result_types":["records","aggregations"],
        "include_totals":True,
    })
    assert global_search.status_code==200,global_search.text
    assert global_search.json()["items"]==[]
    assert global_search.json()["totals"]=={"records":0,"aggregations":0}
    for resource in ("records", "aggregations"):
        advanced = client.post(f"/api/v1/{resource}/advanced-search", json={"limit": 1})
        assert advanced.status_code == 200, advanced.text
        assert advanced.json()["items"] == []
    preview_page = client.get(f"/api/v1/records/{record['id']}/digital-components/previewable")
    assert preview_page.status_code in {403,404}
    assert component["file_name"] not in preview_page.text
    reindex=client.post(f"/api/v1/digital-components/{component['id']}/reindex")
    assert reindex.status_code in {403,404}


import pytest
@pytest.fixture(autouse=True)
def enabled_indexing_policy(client):
    from backend.services.api.tests.test_application_settings import save
    assert save(client,{'FULL_TEXT_SEARCH_ENABLED':True,'CONTENT_INDEXING_SCHEDULING_ENABLED':True}).status_code==200
