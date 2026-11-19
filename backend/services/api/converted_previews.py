"""Private, per-viewer PDF bytes. PostgreSQL shares a conversion across API workers."""
from contextlib import nullcontext
from datetime import timedelta
from hashlib import file_digest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from . import document_conversion
from .database import get_connection, pool
from .operation_policy import operation_policy
from .processing_copies import draft_conversion_workspace

BLOCK_SIZE = 256 * 1024
RENDITION_TTL = timedelta(minutes=10)


router = APIRouter(prefix="/api/v1/preview-renditions", tags=["digital component content"])
RENEW_PATH = "/api/v1/preview-renditions/renew"
OpenIds = Annotated[list[UUID], Body(min_length=1, max_length=100)]


@router.post("/renew", status_code=204)
@operation_policy("resource_scoped")
def renew_viewer_renditions(ids: OpenIds, request: Request, connection=Depends(get_connection, scope="function")):
    # Lifecycle requests never return content or revive expired rows. Every
    # component selection and binary request still authorizes the current source.
    connection.execute(
        """UPDATE preview_renditions SET expires_at = statement_timestamp() + %s::interval
           WHERE session_id=%s AND open_id=ANY(%s) AND expires_at > statement_timestamp()""",
        (RENDITION_TTL, request.state.principal.session_id, ids),
    )
    return Response(status_code=204)


@router.post("/release", status_code=204)
@operation_policy("resource_scoped")
def release_viewer_renditions(ids: OpenIds, request: Request, connection=Depends(get_connection, scope="function")):
    connection.execute("DELETE FROM preview_renditions WHERE session_id=%s AND open_id=ANY(%s)",
                       (request.state.principal.session_id, ids))
    return Response(status_code=204)


def open_id(value):
    try:
        return UUID(value)
    except (TypeError, ValueError):
        raise HTTPException(412, detail="invalid converted preview")


def find(connection, identity, session, component, draft):
    return connection.execute(
        """UPDATE preview_renditions SET expires_at = statement_timestamp() + %s::interval
           WHERE open_id=%s AND session_id=%s AND source_checksum=%s
             AND content_set_id IS NOT DISTINCT FROM %s AND draft_component_id IS NOT DISTINCT FROM %s
             AND expires_at > statement_timestamp()
           RETURNING size_in_bytes, checksum, rendering_method""",
        (RENDITION_TTL, identity, session, component["checksum_value"],
         None if draft else component["active_content_set_id"], component["id"] if draft else None),
    ).fetchone()


def prepare(connection, identity, session, component, draft, chunks, size, settings, root):
    """Stage bounded source blocks, run the converter once, and atomically publish its output."""
    suffix = Path(component["file_name"]).suffix.lower()
    owner = draft_conversion_workspace() if draft else nullcontext(root)
    with owner as parent, TemporaryDirectory(prefix="erms-open-pdf-", dir=parent) as workdir:
        workspace = Path(workdir)
        source = workspace / ("source" + suffix)
        with source.open("wb") as writer:
            for chunk in chunks:
                writer.write(chunk)
            if writer.tell() != size:
                raise HTTPException(500, detail="incomplete conversion source")
        try:
            output, method = document_conversion.convert_file(source, workspace, settings)
        except document_conversion.UnsupportedPreview as error:
            raise HTTPException(415, detail=str(error)) from error
        except document_conversion.ConversionUnavailable as error:
            raise HTTPException(503, detail=str(error)) from error
        with output.open("rb") as reader:
            length = output.stat().st_size
            if not 0 < length <= settings["MAX_RENDITION_SIZE_BYTES"]:
                raise HTTPException(503, detail="invalid converted PDF size")
            checksum = file_digest(reader, "sha256").hexdigest()
            if not draft:
                # Replacement can run while LibreOffice works. Publish only while the
                # source is still current and serialize with eviction on replacement.
                current = connection.execute(
                    "SELECT active_content_set_id FROM digital_components WHERE id=%s FOR SHARE",
                    (component["id"],),
                ).fetchone()
                if current is None or current["active_content_set_id"] != component["active_content_set_id"]:
                    raise HTTPException(412, detail="PDF version changed")
            row = connection.execute(
                """INSERT INTO preview_renditions
                   (open_id,session_id,content_set_id,draft_component_id,source_checksum,
                    size_in_bytes,checksum,rendering_method,expires_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,statement_timestamp() + %s::interval)
                   RETURNING size_in_bytes,checksum,rendering_method""",
                (identity, session, None if draft else component["active_content_set_id"],
                 component["id"] if draft else None, component["checksum_value"], length, checksum, method, RENDITION_TTL),
            ).fetchone()
            reader.seek(0)
            for number, block in enumerate(iter(lambda: reader.read(BLOCK_SIZE), b"")):
                connection.execute(
                    "INSERT INTO preview_rendition_chunks(open_id,chunk_no,content) VALUES (%s,%s,%s)",
                    (identity, number, block),
                )
            return row


def read_range(identity, start, end):
    while start < end:
        number, offset = divmod(start, BLOCK_SIZE)
        length = min(end - start, BLOCK_SIZE - offset)
        with pool.connection() as reader:
            row = reader.execute(
                """SELECT substring(content FROM %s FOR %s) AS part FROM preview_rendition_chunks
                   WHERE open_id=%s AND chunk_no=%s""",
                (offset + 1, length, identity, number),
            ).fetchone()
        if row is None or len(row["part"]) != length:
            raise RuntimeError("converted preview closed during transfer")
        yield bytes(row["part"])
        start += length


def cleanup_expired(connection):
    connection.execute(
        """DELETE FROM preview_renditions WHERE open_id IN
           (SELECT open_id FROM preview_renditions WHERE expires_at <= statement_timestamp()
            ORDER BY expires_at LIMIT 100 FOR UPDATE SKIP LOCKED)"""
    )
