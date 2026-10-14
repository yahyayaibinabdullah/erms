from __future__ import annotations

import hashlib
import os

import psycopg
from psycopg.rows import dict_row
from backend.services.api.authentication import hash_password


def _grant_phase3_privileges() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute(
            """UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='ALL_PRIVS')
                WHERE code='system-administrator'"""
        )


def _upload(client, record: dict, name: str = "approved-budget.txt") -> dict:
    response = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": 1},
        files={"file": (name,b"approved budget expenditure evidence","text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _publish_component(component: dict, text: str = "The board approved the annual budget expenditure ceiling.") -> None:
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
        connection.execute(
            """INSERT INTO digital_component_search_chunks(
                   digital_component_id,chunk_no,extracted_text,search_vector,text_search_config)
               VALUES (%s,0,%s,to_tsvector('pg_catalog.english',%s),'pg_catalog.english')""",
            (component["id"],text,text),
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
    assert result["_debug"]["received_request"]==payload
    assert result["_debug"]["canonical_query"]["sort"][-1]=={"field":"id","direction":"asc"}
    serialized=str(result["_debug"]).lower()
    assert all(secret not in serialized for secret in ("select ","cookie","authorization","password","lease_token"))


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
    assert set(body["index_freshness"])=={"has_pending_content"}
    second=client.post("/api/v1/full-text-search",json={**payload,"cursor":body["next_cursor"]})
    assert second.status_code==200 and len(second.json()["items"])==1
    for item in body["items"] + second.json()["items"]:
        resource = item[item["type"]]
        assert isinstance(resource["security_level_id"], int)
        assert "description" in resource
    mismatch=client.post("/api/v1/full-text-search",json={
        "record_where":payload["record_where"],"result_types":["records","aggregations"]
    })
    assert mismatch.status_code==422


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
    reindex=client.post(f"/api/v1/digital-components/{component['id']}/reindex")
    assert reindex.status_code in {403,404}


import pytest
@pytest.fixture(autouse=True)
def enabled_indexing_policy(client):
    from backend.services.api.tests.test_application_settings import save
    assert save(client,{'FULL_TEXT_SEARCH_ENABLED':True,'CONTENT_INDEXING_SCHEDULING_ENABLED':True}).status_code==200
