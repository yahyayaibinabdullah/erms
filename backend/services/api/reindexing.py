from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import Connection
from psycopg.types.json import Jsonb

from .operation_policy import operation_policy
from .database import get_connection
from .resource_authorization import (
    require_component_operation, require_global, require_resource_operation,
)
from backend.services.text_indexer.config import MIME_TYPES


router = APIRouter(tags=["content indexing"])
EXTRACTION_CONFIG = "tika-4.0.0-ocr-eng-ara-v1"
INDEX_CONFIG = "fts-content-v1"
EXTRACTOR_VERSION = "4.0.0"


def _authorize_record_reindex(connection: Connection, record_id: int) -> dict:
    for privilege in ("record.component.reindex", "record.view", "record.component.view"):
        require_global(connection, privilege)
    record = require_resource_operation(
        connection, "record", record_id, "record.view", "record.view",
    )
    allowed = connection.execute(
        "SELECT current_user_can_record_component_operation(%s,'record.component.view','record.component.view') AS value",
        (record_id,),
    ).fetchone()["value"]
    if not allowed:
        raise HTTPException(status_code=403, detail={"code": "insufficient_resource_permission"})
    return record


def _authorize_component_reindex(connection: Connection, component_id: int) -> tuple[dict, dict]:
    for privilege in ("record.component.reindex", "record.view", "record.component.view"):
        require_global(connection, privilege)
    return require_component_operation(
        connection, component_id, "record.component.view", "record.component.view",
    )


def _queue(connection: Connection, component: dict, trigger: str) -> tuple[str, int | None, dict | None]:
    content = connection.execute(
        """SELECT content_set.id,content_set.checksum_algo,content_set.checksum_value
             FROM digital_component_content_sets content_set
            WHERE content_set.id=%s AND content_set.status='active'""",
        (component["active_content_set_id"],),
    ).fetchone() if component.get("active_content_set_id") else None
    if component["content_status"] != "available" or content is None or component["mime_type"] not in MIME_TYPES:
        return "unsupported_or_no_content", None, content
    existing = connection.execute(
        """SELECT id FROM content_indexing_jobs
            WHERE digital_component_id=%s AND content_set_id=%s
              AND extraction_config_version=%s AND index_config_version=%s AND extractor_version=%s
              AND status IN ('queued','leased') FOR UPDATE""",
        (component["id"], content["id"], EXTRACTION_CONFIG, INDEX_CONFIG, EXTRACTOR_VERSION),
    ).fetchone()
    if existing:
        return "already_in_progress", existing["id"], content
    connection.execute(
        """INSERT INTO digital_component_search_documents(
               digital_component_id,record_id,content_set_id,content_checksum_algo,content_checksum_value,
               status,extraction_config_version,index_config_version)
           VALUES (%s,%s,%s,%s,%s,'pending',%s,%s)
           ON CONFLICT(digital_component_id) DO UPDATE SET
               record_id=EXCLUDED.record_id,content_set_id=EXCLUDED.content_set_id,
               content_checksum_algo=EXCLUDED.content_checksum_algo,
               content_checksum_value=EXCLUDED.content_checksum_value,
               status=CASE WHEN digital_component_search_documents.content_set_id=EXCLUDED.content_set_id
                                AND digital_component_search_documents.indexed_at IS NOT NULL
                           THEN digital_component_search_documents.status ELSE 'pending' END,
               extraction_config_version=EXCLUDED.extraction_config_version,
               index_config_version=EXCLUDED.index_config_version,date_updated=CURRENT_TIMESTAMP""",
        (component["id"], component["record_id"], content["id"], content["checksum_algo"],
         content["checksum_value"], EXTRACTION_CONFIG, INDEX_CONFIG),
    )
    job = connection.execute(
        """INSERT INTO content_indexing_jobs(
               digital_component_id,record_id,content_set_id,content_checksum_algo,content_checksum_value,
               trigger,priority,extraction_config_version,index_config_version,extractor_version,required_capabilities)
           VALUES (%s,%s,%s,%s,%s,%s,20,%s,%s,%s,jsonb_build_object('mime_type',%s::text,'max_input_bytes',52428800))
           ON CONFLICT(digital_component_id,content_set_id,extraction_config_version,index_config_version,extractor_version)
               WHERE status IN ('queued','leased') DO NOTHING
           RETURNING id""",
        (component["id"],component["record_id"],content["id"],content["checksum_algo"],
         content["checksum_value"],trigger,EXTRACTION_CONFIG,INDEX_CONFIG,EXTRACTOR_VERSION,component["mime_type"]),
    ).fetchone()
    if job is None:
        job=connection.execute(
            """SELECT id FROM content_indexing_jobs
                WHERE digital_component_id=%s AND content_set_id=%s
                  AND extraction_config_version=%s AND index_config_version=%s AND extractor_version=%s
                  AND status IN ('queued','leased')""",
            (component["id"],content["id"],EXTRACTION_CONFIG,INDEX_CONFIG,EXTRACTOR_VERSION),
        ).fetchone()
        return "already_in_progress",job["id"],content
    return "queued", job["id"], content


@router.post("/api/v1/digital-components/{component_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
@operation_policy("resource_scoped", "record.component.reindex", "record.component.view")
def reindex_component(component_id: int, connection: Connection = Depends(get_connection, scope="function")):
    component, _ = _authorize_component_reindex(connection, component_id)
    disposition, job_id, content = _queue(connection, component, "manual_component")
    if disposition == "unsupported_or_no_content":
        raise HTTPException(status_code=409, detail={"code": "content_not_available"})
    connection.execute(
        "SELECT append_domain_event('digital_component',%s,'CONTENT_REINDEX_REQUESTED',%s::jsonb,%s)",
        (component_id, Jsonb({"attempt_id": job_id, "active_content_set_id": content["id"],
                             "checksum_algo": content["checksum_algo"],
                             "checksum_value": content["checksum_value"],
                             "already_in_progress": disposition == "already_in_progress"}), "manual"),
    )
    return {"attempt_id": job_id, "status": "queued" if disposition == "queued" else "processing",
            "status_url": f"/api/v1/content-indexing/attempts/{job_id}",
            "already_in_progress": disposition == "already_in_progress"}


@router.post("/api/v1/records/{record_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
@operation_policy("resource_scoped", "record.component.reindex", "record.component.view")
def reindex_record(record_id: int, connection: Connection = Depends(get_connection, scope="function")):
    _authorize_record_reindex(connection, record_id)
    # Locking the component snapshot prevents concurrent replacement from being silently folded into this batch.
    components = connection.execute(
        "SELECT * FROM digital_components WHERE record_id=%s ORDER BY id FOR UPDATE", (record_id,),
    ).fetchall()
    batch_id = uuid4()
    counts = {"queued": 0, "already_in_progress": 0, "unsupported_or_no_content": 0}
    items = []
    for component in components:
        disposition, job_id, _ = _queue(connection, component, "manual_record")
        counts[disposition] += 1
        items.append((component["id"], job_id, disposition))
    actor = connection.execute("SELECT current_user_id() AS id").fetchone()["id"]
    connection.execute(
        """INSERT INTO content_indexing_batches(
               id,record_id,requested_by_user_id,total_components,queued_count,
               already_in_progress_count,unavailable_count)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (batch_id,record_id,actor,len(components),counts["queued"],counts["already_in_progress"],
         counts["unsupported_or_no_content"]),
    )
    for component_id, job_id, disposition in items:
        connection.execute(
            """INSERT INTO content_indexing_batch_items(
                   batch_id,digital_component_id,job_id,disposition,component_identifier)
               VALUES (%s,%s,%s,%s,%s)""",
            (batch_id,component_id,job_id,disposition,component_id),
        )
    connection.execute(
        "UPDATE records SET title=title WHERE id=%s", (record_id,),
    )
    connection.execute(
        "SELECT append_domain_event('record',%s,'RECORD_CONTENT_REINDEX_REQUESTED',%s::jsonb,%s)",
        (record_id,Jsonb({"batch_id":str(batch_id),"counts":counts}),"manual"),
    )
    return {"batch_id": batch_id, "status_url": f"/api/v1/content-indexing/batches/{batch_id}",
            "total_components": len(components), **counts}


@router.get("/api/v1/content-indexing/attempts/{attempt_id}")
@operation_policy("resource_scoped", "record.component.view", "record.component.view")
def indexing_attempt_status(attempt_id: int, connection: Connection = Depends(get_connection, scope="function")):
    row = connection.execute(
        """SELECT job.id AS attempt_id,job.digital_component_id,job.record_id,job.status,
                  job.queued_at,job.started_at,job.completed_at,job.attempt_no,
                  attempt.error_code,attempt.completed_at AS attempt_completed_at
             FROM content_indexing_jobs job
             LEFT JOIN LATERAL (SELECT error_code,completed_at FROM content_indexing_attempts
                 WHERE job_id=job.id ORDER BY attempt_no DESC LIMIT 1) attempt ON true
            WHERE job.id=%s AND current_user_can_view_record(job.record_id)
              AND current_user_can_record_component_operation(job.record_id,'record.component.view','record.component.view')""",
        (attempt_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="indexing attempt not found")
    return row


@router.get("/api/v1/digital-components/{component_id}/indexing-status")
@operation_policy("resource_scoped", "record.component.view", "record.component.view")
def component_indexing_status(component_id: int, connection: Connection = Depends(get_connection, scope="function")):
    for privilege in ("record.view", "record.component.view"):
        require_global(connection, privilege)
    component, _ = require_component_operation(
        connection,component_id,"record.component.view","record.component.view",
    )
    state = connection.execute(
        """SELECT status,indexed_at,last_attempt_at,last_error_code,date_updated
             FROM digital_component_search_documents WHERE digital_component_id=%s""",
        (component["id"],),
    ).fetchone()
    return state or {"status":"pending","indexed_at":None,"last_attempt_at":None,
                     "last_error_code":None,"date_updated":None}


@router.get("/api/v1/content-indexing/batches/{batch_id}")
@operation_policy("resource_scoped", "record.component.view", "record.component.view")
def indexing_batch_status(batch_id: UUID, connection: Connection = Depends(get_connection, scope="function")):
    batch = connection.execute(
        """SELECT * FROM content_indexing_batches
            WHERE id=%s AND record_id IS NOT NULL AND current_user_can_view_record(record_id)
              AND current_user_can_record_component_operation(record_id,'record.component.view','record.component.view')""",
        (batch_id,),
    ).fetchone()
    if batch is None:
        raise HTTPException(status_code=404, detail="indexing batch not found")
    outcomes = connection.execute(
        """SELECT coalesce(job.status,item.disposition) AS status,count(*) AS count
             FROM content_indexing_batch_items item LEFT JOIN content_indexing_jobs job ON job.id=item.job_id
            WHERE item.batch_id=%s GROUP BY coalesce(job.status,item.disposition)""",
        (batch_id,),
    ).fetchall()
    result = dict(batch)
    result["outcomes"] = {row["status"]: row["count"] for row in outcomes}
    return result
