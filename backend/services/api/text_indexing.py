from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Query, APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from psycopg import Connection

from .content_storage import ContentLocation, configured_storage
from .database import get_connection
from .service_authentication import ServicePrincipal


router = APIRouter(prefix="/api/v1/internal/text-indexing", tags=["internal text indexing"])
LEASE_SECONDS = 300
MAX_CLAIM_BATCH = 20
MAX_CHUNK_CHARACTERS = 20_000
MAX_TOTAL_CHARACTERS = 5_000_000
CONTRACT_VERSION = "1"
LANGUAGE_CONFIG = {
    "english": "pg_catalog.english", "arabic": "pg_catalog.arabic",
    "mixed": "pg_catalog.simple", "unknown": "pg_catalog.simple",
    "short": "pg_catalog.simple", "low_confidence": "pg_catalog.simple",
    "unsupported_script": "pg_catalog.simple", "code_like": "pg_catalog.simple",
}


class ClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=200)
    instance_nonce: str = Field(min_length=16, max_length=200)
    requested_count: int = Field(default=4, ge=1, le=MAX_CLAIM_BATCH)
    contract_version: Literal["1"] = "1"
    extractor_version: str = Field(min_length=1, max_length=100)
    extraction_config_version: str = Field(min_length=1, max_length=200)
    index_config_version: str = Field(min_length=1, max_length=200)
    supported_mime_types: list[str] = Field(min_length=1, max_length=100)
    ocr_languages: list[str] = Field(default_factory=list, max_length=20)
    limits: dict[str, int] = Field(default_factory=dict)
    processing_copy_protocol: Literal[0,1] = 0


class LeaseRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=200)
    lease_token: UUID
    lease_generation: int = Field(ge=1)


class HeartbeatRequest(LeaseRequest):
    progress: dict[str, int | float | str] = Field(default_factory=dict)


class ChunkRequest(LeaseRequest):
    idempotency_key: str = Field(min_length=1, max_length=200)
    text: str = Field(max_length=MAX_CHUNK_CHARACTERS)
    text_digest: str
    language_decision: Literal[
        "english", "arabic", "mixed", "unknown", "short", "low_confidence",
        "unsupported_script", "code_like",
    ]
    detected_language: str | None = Field(default=None, max_length=35)
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)

    @field_validator("text_digest")
    @classmethod
    def digest_is_hex(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("text_digest must be 64 lowercase hexadecimal characters")
        return value


class CompleteRequest(LeaseRequest):
    idempotency_key: str = Field(min_length=1, max_length=200)
    chunk_count: int = Field(ge=0, le=100_000)
    detected_mime_type: str = Field(min_length=1, max_length=255)
    detected_language: str | None = Field(default=None, max_length=35)
    extractor_name: str = Field(min_length=1, max_length=100)
    extractor_version: str = Field(min_length=1, max_length=100)
    characters_extracted: int = Field(ge=0, le=MAX_TOTAL_CHARACTERS)
    ocr_used: bool = False


class FailRequest(LeaseRequest):
    idempotency_key: str = Field(min_length=1, max_length=200)
    error_code: Literal[
        "unsupported", "corrupt", "password_protected", "limit_exceeded",
        "timeout", "checksum_mismatch", "extractor_unavailable", "transient_io",
    ]
    error_summary: str = Field(min_length=1, max_length=500)
    retryable: bool = False


def _principal(request: Request) -> ServicePrincipal:
    principal = getattr(request.state, "service_principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


def _token(value: UUID) -> UUID:
    return value


def _lease(
    connection: Connection, job_id: int, payload: LeaseRequest, *, lock: bool = False,
    allow_terminal: bool = False,
) -> dict:
    suffix = " FOR UPDATE" if lock else ""
    statuses = "('leased','succeeded','failed','unsupported','cancelled')" if allow_terminal else "('leased')"
    row = connection.execute(
        f"""SELECT * FROM content_indexing_jobs
             WHERE id=%s AND lease_owner=%s AND lease_token=%s
               AND lease_generation=%s AND status IN {statuses}{suffix}""",
        (job_id, payload.worker_id, _token(payload.lease_token), payload.lease_generation),
    ).fetchone()
    if row is None or (row["status"] == "leased" and row["lease_expires_at"] <= datetime.now(row["lease_expires_at"].tzinfo)):
        raise HTTPException(status_code=409, detail={"code": "lease_lost"})
    return row


def _operation_response(
    connection: Connection, job_id: int, generation: int, operation: str, key: str,
) -> dict | None:
    row = connection.execute(
        """SELECT response FROM content_indexing_operations
            WHERE job_id=%s AND lease_generation=%s AND operation=%s AND idempotency_key=%s""",
        (job_id, generation, operation, key),
    ).fetchone()
    return row["response"] if row else None


@router.post("/jobs/claim")
def claim_jobs(
    payload: ClaimRequest, principal: ServicePrincipal = Depends(_principal),
    connection: Connection = Depends(get_connection, scope="function"),
):
    connection.execute('SELECT pg_advisory_xact_lock(7357,1)')
    existing = connection.execute(
        """SELECT capabilities,active_until FROM text_indexing_workers
            WHERE service_user_id=%s AND worker_id=%s FOR UPDATE""",
        (principal.user_id, payload.worker_id),
    ).fetchone()
    if existing and existing["active_until"] > datetime.now(existing["active_until"].tzinfo):
        if existing["capabilities"].get("instance_nonce") != payload.instance_nonce:
            raise HTTPException(status_code=409, detail={"code": "worker_id_already_active"})
    capabilities = {
        "processing_copy_protocol":payload.processing_copy_protocol,
        "instance_nonce": payload.instance_nonce,
        "supported_mime_types": sorted(set(payload.supported_mime_types)),
        "ocr_languages": sorted(set(payload.ocr_languages)),
        "limits": payload.limits,
    }
    connection.execute(
        """INSERT INTO text_indexing_workers(
               service_user_id,worker_id,contract_version,extractor_version,
               extraction_config_version,index_config_version,capabilities,active_until
           ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,CURRENT_TIMESTAMP+interval '10 minutes')
           ON CONFLICT(service_user_id,worker_id) DO UPDATE SET
               contract_version=EXCLUDED.contract_version,
               extractor_version=EXCLUDED.extractor_version,
               extraction_config_version=EXCLUDED.extraction_config_version,
               index_config_version=EXCLUDED.index_config_version,
               capabilities=EXCLUDED.capabilities,last_contact_at=CURRENT_TIMESTAMP,
               active_until=EXCLUDED.active_until""",
        (principal.user_id,payload.worker_id,payload.contract_version,payload.extractor_version,
         payload.extraction_config_version,payload.index_config_version,
         __import__("json").dumps(capabilities)),
    )
    jobs = []
    supported = payload.supported_mime_types
    for _ in range(payload.requested_count):
        lease_token = uuid4()
        job = connection.execute(
            """WITH candidate AS (
                   SELECT id FROM content_indexing_jobs
                    WHERE not_before<=CURRENT_TIMESTAMP AND NOT disposition_private.content_reserved(record_id)
                      AND (status='queued' OR (status='leased' AND lease_expires_at<CURRENT_TIMESTAMP))
                      AND extractor_version=%s AND extraction_config_version=%s
                      AND index_config_version=%s
                      AND ((required_capabilities->>'mime_type')=ANY(%s) OR '*'=ANY(%s))
                    ORDER BY priority DESC,not_before,id
                    FOR UPDATE SKIP LOCKED LIMIT 1
               )
               UPDATE content_indexing_jobs job SET
                   status='leased',lease_owner=%s,lease_token=%s,
                   lease_generation=job.lease_generation+1,
                   lease_expires_at=CURRENT_TIMESTAMP+(%s*interval '1 second'),
                   attempt_no=job.attempt_no+1,
                   started_at=COALESCE(job.started_at,CURRENT_TIMESTAMP),date_updated=CURRENT_TIMESTAMP
               FROM candidate WHERE job.id=candidate.id RETURNING job.*""",
            (payload.extractor_version,payload.extraction_config_version,payload.index_config_version,
             supported,supported,payload.worker_id,lease_token,LEASE_SECONDS),
        ).fetchone()
        if not job:
            break
        connection.execute(
            """UPDATE content_indexing_attempts SET status='lease_lost',completed_at=CURRENT_TIMESTAMP,
                      error_code='lease_expired',error_summary='Lease expired before completion'
                 WHERE job_id=%s AND status='processing'""", (job["id"],),
        )
        connection.execute(
            """INSERT INTO content_indexing_attempts(
                   digital_component_id,record_id,content_set_id,content_checksum_algo,
                   content_checksum_value,trigger,job_id,worker_id,lease_generation,status,
                   attempt_no,queued_at,started_at,extractor_version,
                   extraction_config_version,index_config_version,request_id,correlation_id
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'processing',%s,%s,CURRENT_TIMESTAMP,
                         %s,%s,%s,NULLIF(current_setting('app.request_id',true),''),
                         NULLIF(current_setting('app.correlation_id',true),''))""",
            (job["digital_component_id"],job["record_id"],job["content_set_id"],
             job["content_checksum_algo"],job["content_checksum_value"],job["trigger"],job["id"],
             payload.worker_id,job["lease_generation"],job["attempt_no"],job["queued_at"],
             payload.extractor_version,payload.extraction_config_version,payload.index_config_version),
        )
        connection.execute(
            """UPDATE digital_component_search_documents SET status='processing',
                      last_attempt_at=CURRENT_TIMESTAMP,date_updated=CURRENT_TIMESTAMP
                 WHERE digital_component_id=%s AND content_set_id=%s""",
            (job["digital_component_id"],job["content_set_id"]),
        )
        content_size = connection.execute(
            "SELECT size_in_bytes FROM digital_component_content_sets WHERE id=%s",
            (job["content_set_id"],),
        ).fetchone()["size_in_bytes"]
        jobs.append({
            "job_id": job["id"], "lease_token": str(job["lease_token"]),
            "lease_generation": job["lease_generation"],
            "lease_expires_at": job["lease_expires_at"],
            "content_size": content_size,
            "content_checksum_algo": job["content_checksum_algo"],
            "content_checksum_value": job["content_checksum_value"],
            "required_capabilities": job["required_capabilities"],
        })
    return {"contract_version": CONTRACT_VERSION, "jobs": jobs}


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat(job_id: int, payload: HeartbeatRequest, principal: ServicePrincipal = Depends(_principal), connection: Connection = Depends(get_connection, scope="function")):
    _lease(connection, job_id, payload, lock=True)
    connection.execute(
        """UPDATE content_indexing_jobs SET lease_expires_at=CURRENT_TIMESTAMP+(%s*interval '1 second'),date_updated=CURRENT_TIMESTAMP
            WHERE id=%s""", (LEASE_SECONDS,job_id),
    )
    connection.execute(
        """UPDATE text_indexing_workers SET last_contact_at=CURRENT_TIMESTAMP,
                  active_until=CURRENT_TIMESTAMP+interval '10 minutes',current_job_id=%s
            WHERE service_user_id=%s AND worker_id=%s""",
        (job_id,principal.user_id,payload.worker_id),
    )
    return {"status":"leased","lease_seconds":LEASE_SECONDS}


@router.get("/jobs/{job_id}/content")
def job_content(
    job_id: int, request: Request, worker_id: str = Header(alias="X-Worker-ID"),
    lease_token: UUID = Header(alias="X-Lease-Token"),
    lease_generation: int = Header(alias="X-Lease-Generation"),
    principal: ServicePrincipal = Depends(_principal),
    connection: Connection = Depends(get_connection, scope="function"),
):
    payload = LeaseRequest(worker_id=worker_id,lease_token=lease_token,lease_generation=lease_generation)
    job = _lease(connection,job_id,payload)
    if not connection.execute("SELECT 1 FROM disposition_private.processing_copies WHERE component_id=%s AND owner_user_id=%s AND kind='text_indexing' AND worker_id=%s AND indexing_job_id=%s AND indexing_generation=%s",(job['digital_component_id'],principal.user_id,worker_id,job_id,lease_generation)).fetchone():
        raise HTTPException(409,detail={'code':'processing_copy_required'})
    content_set = connection.execute(
        """SELECT size_in_bytes,segment_count,checksum_algo,checksum_value
             FROM digital_component_content_sets
            WHERE id=%s AND digital_component_id=%s""",
        (job["content_set_id"],job["digital_component_id"]),
    ).fetchone()
    if not content_set:
        raise HTTPException(status_code=409,detail={"code":"content_identity_changed"})
    start,end=0,content_set["size_in_bytes"]
    response_status=200
    range_header=request.headers.get("range")
    if range_header:
        try:
            unit,bounds=range_header.split("=",1); first,last=bounds.split("-",1)
            if unit!="bytes" or "," in bounds: raise ValueError
            start=int(first); end=min(int(last)+1 if last else end,end)
            if start<0 or start>=end: raise ValueError
            response_status=206
        except ValueError as exc:
            raise HTTPException(status_code=416,detail="invalid byte range") from exc
    location=ContentLocation(job["content_set_id"],content_set["size_in_bytes"],content_set["segment_count"])
    headers={
        "Accept-Ranges":"bytes", "X-Content-Checksum-Algorithm":job["content_checksum_algo"],
        "X-Content-Checksum-Value":job["content_checksum_value"],
        "Content-Length":str(end-start),
    }
    if response_status==206:
        headers["Content-Range"]=f"bytes {start}-{end-1}/{content_set['size_in_bytes']}"
    return StreamingResponse(configured_storage().iter_content(location,start,end),status_code=response_status,
                             media_type="application/octet-stream",headers=headers)


@router.put("/jobs/{job_id}/chunks/{chunk_no}")
def put_chunk(job_id: int, chunk_no: int, payload: ChunkRequest, principal: ServicePrincipal = Depends(_principal), connection: Connection = Depends(get_connection, scope="function")):
    if chunk_no<0: raise HTTPException(status_code=422,detail="chunk number must be non-negative")
    _lease(connection,job_id,payload,lock=True)
    digest=hashlib.sha256(payload.text.encode("utf-8")).hexdigest()
    if digest!=payload.text_digest:
        raise HTTPException(status_code=409,detail={"code":"chunk_digest_mismatch"})
    existing=connection.execute(
        """SELECT text_digest FROM content_indexing_result_chunks
            WHERE job_id=%s AND lease_generation=%s AND chunk_no=%s""",
        (job_id,payload.lease_generation,chunk_no),
    ).fetchone()
    if existing:
        if existing["text_digest"]!=digest:
            raise HTTPException(status_code=409,detail={"code":"idempotency_conflict"})
        return {"status":"staged","chunk_no":chunk_no,"idempotent":True}
    config=LANGUAGE_CONFIG[payload.language_decision]
    connection.execute(
        """INSERT INTO content_indexing_result_chunks(
               job_id,lease_generation,chunk_no,page_from,page_to,extracted_text,text_digest,
               detected_language,language_decision,text_search_config,characters_count
           ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::regconfig,%s)""",
        (job_id,payload.lease_generation,chunk_no,payload.page_from,payload.page_to,payload.text,
         digest,payload.detected_language,payload.language_decision,config,len(payload.text)),
    )
    return {"status":"staged","chunk_no":chunk_no,"idempotent":False}


@router.post("/jobs/{job_id}/complete")
def complete_job(job_id: int, payload: CompleteRequest, principal: ServicePrincipal = Depends(_principal), connection: Connection = Depends(get_connection, scope="function")):
    _lease(connection,job_id,payload,allow_terminal=True)
    prior=_operation_response(connection,job_id,payload.lease_generation,"complete",payload.idempotency_key)
    if prior is not None: return prior
    job=_lease(connection,job_id,payload,lock=True)
    chunks=connection.execute(
        """SELECT * FROM content_indexing_result_chunks
            WHERE job_id=%s AND lease_generation=%s ORDER BY chunk_no""",
        (job_id,payload.lease_generation),
    ).fetchall()
    if len(chunks)!=payload.chunk_count or [row["chunk_no"] for row in chunks]!=list(range(payload.chunk_count)):
        raise HTTPException(status_code=409,detail={"code":"incomplete_staging"})
    if sum(row["characters_count"] for row in chunks)!=payload.characters_extracted:
        raise HTTPException(status_code=409,detail={"code":"character_count_mismatch"})
    active=connection.execute(
        """SELECT component.active_content_set_id,component.content_status,content_set.checksum_algo,
                  content_set.checksum_value
             FROM digital_components component
             JOIN digital_component_content_sets content_set ON content_set.id=component.active_content_set_id
            WHERE component.id=%s FOR UPDATE OF component""", (job["digital_component_id"],),
    ).fetchone()
    if not active or active["content_status"]!='available' or active["active_content_set_id"]!=job["content_set_id"] or active["checksum_algo"]!=job["content_checksum_algo"] or active["checksum_value"]!=job["content_checksum_value"]:
        connection.execute("UPDATE content_indexing_jobs SET status='cancelled',completed_at=CURRENT_TIMESTAMP,date_updated=CURRENT_TIMESTAMP WHERE id=%s",(job_id,))
        connection.execute("UPDATE content_indexing_attempts SET status='cancelled',completed_at=CURRENT_TIMESTAMP,error_code='content_identity_changed',error_summary='Active content changed before publication' WHERE job_id=%s AND lease_generation=%s",(job_id,payload.lease_generation))
        connection.commit()
        raise HTTPException(status_code=409,detail={"code":"content_identity_changed"})
    connection.execute("DELETE FROM digital_component_search_chunks WHERE digital_component_id=%s",(job["digital_component_id"],))
    connection.execute(
        """INSERT INTO digital_component_search_chunks(
               digital_component_id,chunk_no,page_from,page_to,extracted_text,search_vector,text_search_config
           ) SELECT %s,chunk_no,page_from,page_to,extracted_text,
                    to_tsvector(text_search_config,extracted_text),text_search_config
               FROM content_indexing_result_chunks WHERE job_id=%s AND lease_generation=%s ORDER BY chunk_no""",
        (job["digital_component_id"],job_id,payload.lease_generation),
    )
    connection.execute(
        """UPDATE digital_component_search_documents SET status='indexed',detected_mime_type=%s,
                  detected_language=%s,extractor_name=%s,extractor_version=%s,indexed_at=CURRENT_TIMESTAMP,
                  last_attempt_at=CURRENT_TIMESTAMP,last_error_code=NULL,last_error_summary=NULL,date_updated=CURRENT_TIMESTAMP
            WHERE digital_component_id=%s AND content_set_id=%s""",
        (payload.detected_mime_type,payload.detected_language,payload.extractor_name,payload.extractor_version,
         job["digital_component_id"],job["content_set_id"]),
    )
    connection.execute("UPDATE content_indexing_jobs SET status='succeeded',completed_at=CURRENT_TIMESTAMP,date_updated=CURRENT_TIMESTAMP WHERE id=%s",(job_id,))
    connection.execute(
        """UPDATE content_indexing_attempts SET status='succeeded',completed_at=CURRENT_TIMESTAMP,
                  extractor_name=%s,extractor_version=%s,characters_extracted=%s,chunks_created=%s,ocr_used=%s
            WHERE job_id=%s AND lease_generation=%s""",
        (payload.extractor_name,payload.extractor_version,payload.characters_extracted,payload.chunk_count,
         payload.ocr_used,job_id,payload.lease_generation),
    )
    connection.execute("DELETE FROM content_indexing_result_chunks WHERE job_id=%s AND lease_generation=%s",(job_id,payload.lease_generation))
    response={"status":"succeeded","job_id":job_id,"chunks_published":payload.chunk_count}
    connection.execute("INSERT INTO content_indexing_operations(job_id,lease_generation,operation,idempotency_key,response) VALUES (%s,%s,'complete',%s,%s::jsonb)",(job_id,payload.lease_generation,payload.idempotency_key,__import__('json').dumps(response)))
    return response


@router.post("/jobs/{job_id}/fail")
def fail_job(job_id: int, payload: FailRequest, principal: ServicePrincipal = Depends(_principal), connection: Connection = Depends(get_connection, scope="function")):
    _lease(connection,job_id,payload,allow_terminal=True)
    prior=_operation_response(connection,job_id,payload.lease_generation,"fail",payload.idempotency_key)
    if prior is not None: return prior
    job=_lease(connection,job_id,payload,lock=True)
    retry=payload.retryable and payload.error_code in {'timeout','extractor_unavailable','transient_io'} and job['attempt_no']<3
    new_status='queued' if retry else ('unsupported' if payload.error_code=='unsupported' else 'failed')
    connection.execute(
        """UPDATE content_indexing_jobs SET status=%s,not_before=CASE WHEN %s THEN CURRENT_TIMESTAMP+(power(2,attempt_no)*interval '5 seconds') ELSE not_before END,
                  lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                  completed_at=CASE WHEN %s THEN NULL ELSE CURRENT_TIMESTAMP END,date_updated=CURRENT_TIMESTAMP WHERE id=%s""",
        (new_status,retry,retry,job_id),
    )
    attempt_status='failed' if payload.error_code!='unsupported' else 'unsupported'
    connection.execute(
        """UPDATE content_indexing_attempts SET status=%s,completed_at=CURRENT_TIMESTAMP,error_code=%s,error_summary=%s
            WHERE job_id=%s AND lease_generation=%s""",
        (attempt_status,payload.error_code,payload.error_summary,job_id,payload.lease_generation),
    )
    connection.execute(
        """UPDATE digital_component_search_documents SET
                  status=CASE WHEN indexed_at IS NOT NULL THEN 'indexed' WHEN %s THEN 'pending' WHEN %s='unsupported' THEN 'unsupported' ELSE 'failed' END,
                  last_attempt_at=CURRENT_TIMESTAMP,last_error_code=%s,last_error_summary=%s,date_updated=CURRENT_TIMESTAMP
            WHERE digital_component_id=%s AND content_set_id=%s""",
        (retry,payload.error_code,payload.error_code,payload.error_summary,job['digital_component_id'],job['content_set_id']),
    )
    response={"status":new_status,"job_id":job_id,"retry_scheduled":retry}
    connection.execute("INSERT INTO content_indexing_operations(job_id,lease_generation,operation,idempotency_key,response) VALUES (%s,%s,'fail',%s,%s::jsonb)",(job_id,payload.lease_generation,payload.idempotency_key,__import__('json').dumps(response)))
    return response


@router.get("/workers/{worker_id}")
def worker_status(worker_id: str, principal: ServicePrincipal = Depends(_principal), connection: Connection = Depends(get_connection, scope="function")):
    row=connection.execute(
        """SELECT worker_id,contract_version,extractor_version,extraction_config_version,
                  index_config_version,capabilities,registered_at,last_contact_at,active_until,current_job_id
             FROM text_indexing_workers WHERE service_user_id=%s AND worker_id=%s""",
        (principal.user_id,worker_id),
    ).fetchone()
    if not row: raise HTTPException(status_code=404,detail="worker not registered")
    return row


class ProcessingCopyRequest(LeaseRequest):
    token: UUID


@router.post('/jobs/{job_id}/processing-copy')
def register_copy(job_id:int,payload:ProcessingCopyRequest,principal:ServicePrincipal=Depends(_principal),connection:Connection=Depends(get_connection,scope='function')):
    connection.execute('SELECT pg_advisory_xact_lock(7357,1)')
    job=_lease(connection,job_id,payload,lock=True)
    try:connection.execute("SELECT disposition_private.register_processing_copy(%s,%s,%s,'text_indexing',%s,%s,%s)",(payload.token,job['digital_component_id'],principal.user_id,payload.worker_id,job_id,payload.lease_generation))
    except __import__('psycopg').Error:raise HTTPException(409,detail={'code':'lease_lost'}) from None
    return {'registered':True}


@router.delete('/processing-copies/{token}')
def acknowledge_copy(token:UUID,worker_id:str=Query(min_length=1,max_length=200),principal:ServicePrincipal=Depends(_principal),connection:Connection=Depends(get_connection,scope='function')):
    # Cleanup receipts remain valid after lease expiry, but only for their
    # authenticated service owner and exact worker/token. No deletion authority.
    row=connection.execute('SELECT owner_user_id,worker_id FROM disposition_private.processing_copies WHERE token=%s',(token,)).fetchone()
    if row and (row['owner_user_id']!=principal.user_id or row['worker_id']!=worker_id):raise HTTPException(403,detail={'code':'processing_copy_owner_required'})
    connection.execute("DELETE FROM disposition_private.processing_copies WHERE token=%s AND owner_user_id=%s AND kind='text_indexing' AND worker_id=%s",(token,principal.user_id,worker_id))
    return {'cleaned':True}
