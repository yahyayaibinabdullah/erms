from __future__ import annotations

import hashlib
import os

import psycopg
from psycopg.rows import dict_row

from backend.services.api.service_authentication import generate_api_key
from backend.services.api.text_indexing_maintenance import LOCK_KEY, cleanup, metrics, reconcile


CLAIM = {
    "worker_id": "phase2-worker-a", "instance_nonce": "phase2-instance-a",
    "requested_count": 1, "contract_version": "1", "extractor_version": "4.0.0",
    "extraction_config_version": "tika-4.0.0-ocr-eng-ara-v1",
    "index_config_version": "fts-content-v1", "supported_mime_types": ["text/plain"],
    "ocr_languages": ["eng", "ara"], "limits": {"max_input_bytes": 52428800},
}


def _service_key() -> str:
    key, identifier, digest = generate_api_key()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        account = connection.execute(
            "INSERT INTO users(name,external_id,account_type) VALUES ('Phase 2 worker','phase2-worker','service') RETURNING id"
        ).fetchone()[0]
        role = connection.execute("SELECT id FROM roles WHERE code='text-indexer-service'").fetchone()[0]
        connection.execute("INSERT INTO user_role_assignments(user_id,role_id) VALUES (%s,%s)",(account,role))
        connection.execute(
            """INSERT INTO service_account_credentials(service_user_id,name,credential_identifier,secret_hash,expires_at)
               VALUES (%s,'Phase 2 key',%s,%s,CURRENT_TIMESTAMP+interval '1 day')""",
            (account,identifier,digest),
        )
    return key


def _upload(client, record: dict, content: bytes = b"approved budget evidence") -> dict:
    response = client.post(
        f"/api/v1/records/{record['id']}/digital-components/upload",
        data={"component_order": 1}, files={"file": ("evidence.txt",content,"text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_claim_content_stage_publish_and_terminal_retry_are_lease_scoped(client, record):
    component = _upload(client,record)
    key = _service_key()
    headers = {"Authorization": f"Bearer {key}"}
    claimed = client.post("/api/v1/internal/text-indexing/jobs/claim",headers=headers,json=CLAIM)
    assert claimed.status_code == 200,claimed.text
    job = claimed.json()["jobs"][0]
    lease = {"worker_id":CLAIM["worker_id"],"lease_token":job["lease_token"],
             "lease_generation":job["lease_generation"]}
    download_headers = {**headers,"X-Worker-ID":lease["worker_id"],"X-Lease-Token":lease["lease_token"],
                        "X-Lease-Generation":str(lease["lease_generation"])}
    content = client.get(f"/api/v1/internal/text-indexing/jobs/{job['job_id']}/content",headers=download_headers)
    assert content.status_code == 200
    assert content.content == b"approved budget evidence"
    text = "Approved budget evidence for the authoritative records programme. " * 4
    chunk = {**lease,"idempotency_key":"chunk-0","text":text,
             "text_digest":hashlib.sha256(text.encode()).hexdigest(),"language_decision":"english",
             "detected_language":"en"}
    url=f"/api/v1/internal/text-indexing/jobs/{job['job_id']}/chunks/0"
    assert client.put(url,headers=headers,json=chunk).status_code == 200
    assert client.put(url,headers=headers,json=chunk).json()["idempotent"] is True
    complete={**lease,"idempotency_key":"complete-0","chunk_count":1,
              "detected_mime_type":"text/plain","detected_language":"en","extractor_name":"Apache Tika",
              "extractor_version":"4.0.0","characters_extracted":len(text),"ocr_used":False}
    terminal=client.post(f"/api/v1/internal/text-indexing/jobs/{job['job_id']}/complete",headers=headers,json=complete)
    assert terminal.status_code == 200,terminal.text
    assert client.post(f"/api/v1/internal/text-indexing/jobs/{job['job_id']}/complete",headers=headers,json=complete).json()==terminal.json()
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        state=connection.execute("SELECT status FROM digital_component_search_documents WHERE digital_component_id=%s",(component["id"],)).fetchone()[0]
        vector=connection.execute("SELECT search_vector@@websearch_to_tsquery('pg_catalog.english','approved budget') FROM digital_component_search_chunks WHERE digital_component_id=%s",(component["id"],)).fetchone()[0]
        assert state=="indexed" and vector
    replaced=client.put(
        f"/api/v1/digital-components/{component['id']}/content",
        files={"file":("replacement.txt",b"replacement generation","text/plain")},
        headers={"If-Match":str(component["version"])},
    )
    assert replaced.status_code==200,replaced.text
    with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as connection:
        state=connection.execute(
            "SELECT status,content_set_id FROM digital_component_search_documents WHERE digital_component_id=%s",
            (component["id"],),
        ).fetchone()
        assert state["status"]=="pending"
        assert connection.execute(
            "SELECT count(*) AS count FROM content_indexing_jobs WHERE digital_component_id=%s AND content_set_id=%s AND status='queued'",
            (component["id"],state["content_set_id"]),
        ).fetchone()["count"]==1


def test_expired_lease_is_reclaimed_and_old_generation_is_fenced(client, record):
    _upload(client,record,b"lease recovery")
    key=_service_key(); headers={"Authorization":f"Bearer {key}"}
    first=client.post("/api/v1/internal/text-indexing/jobs/claim",headers=headers,json=CLAIM).json()["jobs"][0]
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        connection.execute("UPDATE content_indexing_jobs SET lease_expires_at=CURRENT_TIMESTAMP-interval '1 second' WHERE id=%s",(first["job_id"],))
    second_claim={**CLAIM,"worker_id":"phase2-worker-b","instance_nonce":"phase2-instance-b"}
    second=client.post("/api/v1/internal/text-indexing/jobs/claim",headers=headers,json=second_claim).json()["jobs"][0]
    assert second["job_id"]==first["job_id"]
    assert second["lease_generation"]==first["lease_generation"]+1
    old={"worker_id":CLAIM["worker_id"],"lease_token":first["lease_token"],"lease_generation":first["lease_generation"],
         "progress":{}}
    rejected=client.post(f"/api/v1/internal/text-indexing/jobs/{first['job_id']}/heartbeat",headers=headers,json=old)
    assert rejected.status_code==409
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute(
            "SELECT status FROM content_indexing_attempts WHERE job_id=%s AND lease_generation=%s",
            (first["job_id"],first["lease_generation"]),
        ).fetchone()[0]=="lease_lost"


def test_reconciliation_is_bounded_and_idempotent(client,record):
    component=_upload(client,record,b"reconciliation")
    with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as connection:
        connection.execute("DELETE FROM digital_component_search_documents WHERE digital_component_id=%s",(component["id"],))
        first=reconcile(connection,500,False)
        assert first=={"drifted":1,"queued":0}
    with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as connection:
        assert reconcile(connection,500,False)=={"drifted":0,"queued":0}


def test_cleanup_retention_boundaries_and_single_leader(client,record):
    component=_upload(client,record,b"cleanup")
    with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as connection:
        job=connection.execute("SELECT * FROM content_indexing_jobs WHERE digital_component_id=%s",(component["id"],)).fetchone()
        connection.execute("UPDATE content_indexing_jobs SET status='failed',completed_at=CURRENT_TIMESTAMP WHERE id=%s",(job["id"],))
        connection.execute(
            """INSERT INTO content_indexing_attempts(digital_component_id,record_id,content_set_id,
                 content_checksum_algo,content_checksum_value,trigger,job_id,worker_id,lease_generation,status,
                 attempt_no,queued_at,completed_at,extraction_config_version,index_config_version)
               VALUES (%s,%s,%s,%s,%s,'upload',%s,'worker',1,'failed',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,%s,%s)""",
            (job["digital_component_id"],job["record_id"],job["content_set_id"],job["content_checksum_algo"],
             job["content_checksum_value"],job["id"],job["extraction_config_version"],job["index_config_version"]),
        )
        connection.execute(
            """INSERT INTO content_indexing_result_chunks(job_id,lease_generation,chunk_no,extracted_text,text_digest,
                 language_decision,text_search_config,characters_count)
               VALUES (%s,1,0,'stale',%s,'english','pg_catalog.english',5)""",
            (job["id"],hashlib.sha256(b"stale").hexdigest()),
        )
        result=cleanup(connection,500,365,False)
        assert result["staging"]==1 and result["jobs"]==0 and result["attempts"]==0
        snapshot=metrics(connection)
        assert set(snapshot)=={"queue","stale_documents","oldest_queued_seconds","outcomes","input",
                              "workers","recovery","staged_chunks"}
        assert "extracted_text" not in str(snapshot)
        connection.execute("UPDATE content_indexing_jobs SET completed_at=CURRENT_TIMESTAMP-interval '366 days' WHERE id=%s",(job["id"],))
        connection.execute("UPDATE content_indexing_attempts SET completed_at=CURRENT_TIMESTAMP-interval '366 days' WHERE job_id=%s",(job["id"],))
        result=cleanup(connection,500,365,False)
        assert result["jobs"]==1 and result["attempts"]==1
        service_user=connection.execute(
            "INSERT INTO users(name,external_id,account_type) VALUES ('Cleanup indexer','cleanup-indexer','service') RETURNING id"
        ).fetchone()["id"]
        connection.execute(
            """INSERT INTO service_account_credentials(
                   service_user_id,name,credential_identifier,secret_hash,status,date_created,
                   expires_at,date_revoked)
               VALUES
                   (%s,'old revoked','00000000000000000000000001',%s,'revoked',CURRENT_TIMESTAMP-interval '500 days',CURRENT_TIMESTAMP-interval '400 days',CURRENT_TIMESTAMP-interval '400 days'),
                   (%s,'old expired','00000000000000000000000002',%s,'active',CURRENT_TIMESTAMP-interval '500 days',CURRENT_TIMESTAMP-interval '400 days',NULL),
                   (%s,'recent revoked','00000000000000000000000003',%s,'revoked',CURRENT_TIMESTAMP-interval '10 days',CURRENT_TIMESTAMP+interval '10 days',CURRENT_TIMESTAMP-interval '1 day'),
                   (%s,'active','00000000000000000000000004',%s,'active',CURRENT_TIMESTAMP-interval '10 days',CURRENT_TIMESTAMP+interval '10 days',NULL)""",
            (service_user,"a"*64,service_user,"b"*64,service_user,"c"*64,service_user,"d"*64),
        )
        result=cleanup(connection,500,365,False,365)
        assert result["credentials"]==2
        remaining=connection.execute(
            "SELECT name FROM service_account_credentials WHERE service_user_id=%s ORDER BY name",
            (service_user,),
        ).fetchall()
        assert [row["name"] for row in remaining]==["active","recent revoked"]
    first=psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row); second=psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row)
    try:
        first.execute("BEGIN"); assert first.execute("SELECT pg_try_advisory_xact_lock(%s)",(LOCK_KEY,)).fetchone()["pg_try_advisory_xact_lock"]
        blocked=cleanup(second,10,365,False)
        assert blocked["leader"] is False and blocked["credentials"]==0
    finally:
        first.rollback(); first.close(); second.close()


import pytest
@pytest.fixture(autouse=True)
def enabled_indexing_policy(client):
    from backend.services.api.tests.test_application_settings import save
    assert save(client,{'FULL_TEXT_SEARCH_ENABLED':True,'CONTENT_INDEXING_SCHEDULING_ENABLED':True}).status_code==200
