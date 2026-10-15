import hashlib
import os
from dataclasses import dataclass
from contextlib import contextmanager
from typing import BinaryIO, Iterator, Protocol

from fastapi import HTTPException, UploadFile, status
from psycopg import Connection

from .application_settings import cache as settings_cache
from .database import pool


@dataclass(frozen=True)
class UploadedContent:
    size_in_bytes: int
    checksum_value: str
    segment_count: int


@dataclass(frozen=True)
class ContentLocation:
    content_set_id: int
    size_in_bytes: int
    segment_count: int


class ContentStorage(Protocol):
    def store_upload(self, connection: Connection, component_id: int, upload: UploadFile, *, settings=None) -> UploadedContent: ...
    def store_draft_upload(self, connection: Connection, draft_component_id: int, upload: UploadFile, *, settings=None) -> UploadedContent: ...
    def promote_draft(self, connection: Connection, draft_component_id: int, component_id: int) -> None: ...
    def location(self, connection: Connection, component_id: int) -> ContentLocation | None: ...
    def iter_content(self, location: ContentLocation, start: int = 0, end: int | None = None) -> Iterator[bytes]: ...
    def read(self, connection: Connection, component_id: int) -> bytes | None: ...
    def delete(self, connection: Connection, component_id: int) -> bool: ...


def inspect_upload(upload: UploadFile, settings) -> UploadedContent:
    """Measure and hash a spooled upload without retaining the file in memory."""
    digest = hashlib.sha256()
    total = 0
    count = 0
    maximum = settings["MAX_UPLOAD_SIZE_BYTES"]
    upload.file.seek(0)
    while content := upload.file.read(settings["CONTENT_SEGMENT_SIZE_BYTES"]):
        total += len(content)
        if total > maximum:
            upload.file.seek(0)
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"file exceeds the configured {maximum}-byte upload limit",
            )
        digest.update(content)
        count += 1
    upload.file.seek(0)
    return UploadedContent(total, digest.hexdigest(), count)


def _segment_digest(content: bytes, settings) -> tuple[str | None, str | None]:
    if not settings["CONTENT_SEGMENT_CHECKSUMS_ENABLED"]:
        return None, None
    return "sha256", hashlib.sha256(content).hexdigest()


def _stream_segments(
    connection: Connection, source: BinaryIO, insert_sql: str, owner_id: int, settings,
) -> UploadedContent:
    digest = hashlib.sha256()
    total = 0
    segment_no = 0
    maximum = settings["MAX_UPLOAD_SIZE_BYTES"]
    while content := source.read(settings["CONTENT_SEGMENT_SIZE_BYTES"]):
        total += len(content)
        if total > maximum:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"file exceeds the configured {maximum}-byte upload limit",
            )
        digest.update(content)
        algorithm, segment_checksum = _segment_digest(content, settings)
        connection.execute(
            insert_sql,
            (owner_id, segment_no, len(content), algorithm, segment_checksum, content),
        )
        segment_no += 1
    return UploadedContent(total, digest.hexdigest(), segment_no)


class PostgreSQLContentStorage:
    def store_upload(
        self, connection: Connection, component_id: int, upload: UploadFile, *, settings=None,
    ) -> UploadedContent:
        settings = settings if settings is not None else settings_cache.for_connection(connection)
        old = connection.execute(
            "SELECT active_content_set_id FROM digital_components WHERE id = %s FOR UPDATE",
            (component_id,),
        ).fetchone()
        if old is None:
            raise HTTPException(status_code=404, detail="digital component not found")
        content_set = connection.execute(
            """INSERT INTO digital_component_content_sets (digital_component_id, status)
               VALUES (%s, 'staged') RETURNING id""", (component_id,),
        ).fetchone()
        session = connection.execute(
            """INSERT INTO content_upload_sessions
                   (digital_component_id, content_set_id, status, expires_at)
               VALUES (%s, %s, 'uploading', CURRENT_TIMESTAMP + (LEAST(%s::numeric, EXTRACT(EPOCH FROM
                   (TIMESTAMPTZ '9999-12-31 00:00:00+00' - CURRENT_TIMESTAMP))) * interval '1 second'))
               RETURNING id""",
            (component_id, content_set["id"],
             settings["CONTENT_UPLOAD_SESSION_TTL_SECONDS"]),
        ).fetchone()
        uploaded = _stream_segments(
            connection, upload.file,
            """INSERT INTO digital_component_blobs
                   (content_set_id, segment_no, segment_size,
                    segment_checksum_algo, segment_checksum_value, content)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            content_set["id"], settings,
        )
        connection.execute(
            """UPDATE content_upload_sessions SET status = 'finalizing',
                   next_segment_no = %s, bytes_received = %s,
                   date_updated = CURRENT_TIMESTAMP WHERE id = %s""",
            (uploaded.segment_count, uploaded.size_in_bytes, session["id"]),
        )
        if old["active_content_set_id"] is not None:
            connection.execute(
                "UPDATE digital_component_content_sets SET status = 'superseded' WHERE id = %s",
                (old["active_content_set_id"],),
            )
        connection.execute(
            """UPDATE digital_component_content_sets SET status = 'active',
                   size_in_bytes = %s, segment_count = %s, checksum_algo = 'sha256',
                   checksum_value = %s, date_completed = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (uploaded.size_in_bytes, uploaded.segment_count,
             uploaded.checksum_value, content_set["id"]),
        )
        connection.execute(
            """UPDATE digital_components SET active_content_set_id = %s,
                   upload_completed_at = CURRENT_TIMESTAMP WHERE id = %s""",
            (content_set["id"], component_id),
        )
        connection.execute(
            """UPDATE content_upload_sessions SET status = 'completed',
                   date_updated = CURRENT_TIMESTAMP WHERE id = %s""", (session["id"],),
        )
        if old["active_content_set_id"] is not None:
            connection.execute(
                "DELETE FROM digital_component_content_sets WHERE id = %s",
                (old["active_content_set_id"],),
            )
        return uploaded

    def store_draft_upload(
        self, connection: Connection, draft_component_id: int, upload: UploadFile, *, settings=None,
    ) -> UploadedContent:
        settings = settings if settings is not None else settings_cache.for_connection(connection)
        session = connection.execute(
            """INSERT INTO content_upload_sessions (draft_component_id, status, expires_at)
               VALUES (%s, 'uploading', CURRENT_TIMESTAMP + (LEAST(%s::numeric, EXTRACT(EPOCH FROM
                   (TIMESTAMPTZ '9999-12-31 00:00:00+00' - CURRENT_TIMESTAMP))) * interval '1 second'))
               RETURNING id""",
            (draft_component_id,
             settings["CONTENT_UPLOAD_SESSION_TTL_SECONDS"]),
        ).fetchone()
        uploaded = _stream_segments(
            connection, upload.file,
            """INSERT INTO record_draft_component_blobs
                   (record_draft_component_id, segment_no, segment_size,
                    segment_checksum_algo, segment_checksum_value, content)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            draft_component_id, settings,
        )
        connection.execute(
            """UPDATE record_draft_components SET size_in_bytes = %s,
                   checksum_value = %s, content_status = 'available',
                   segment_count = %s, upload_completed_at = CURRENT_TIMESTAMP
               WHERE id = %s""",
            (uploaded.size_in_bytes, uploaded.checksum_value,
             uploaded.segment_count, draft_component_id),
        )
        connection.execute(
            """UPDATE content_upload_sessions SET status = 'completed',
                   next_segment_no = %s, bytes_received = %s,
                   date_updated = CURRENT_TIMESTAMP WHERE id = %s""",
            (uploaded.segment_count, uploaded.size_in_bytes, session["id"]),
        )
        return uploaded

    def promote_draft(
        self, connection: Connection, draft_component_id: int, component_id: int,
    ) -> None:
        staged = connection.execute(
            """SELECT size_in_bytes, segment_count, checksum_algo, checksum_value
               FROM record_draft_components
               WHERE id = %s AND content_status = 'available'""",
            (draft_component_id,),
        ).fetchone()
        if staged is None:
            raise HTTPException(status_code=409, detail="draft component upload is not complete")
        content_set = connection.execute(
            """INSERT INTO digital_component_content_sets
                   (digital_component_id, status, size_in_bytes, segment_count,
                    checksum_algo, checksum_value, date_completed)
               VALUES (%s, 'active', %s, %s, %s, %s, CURRENT_TIMESTAMP)
               RETURNING id""",
            (component_id, staged["size_in_bytes"], staged["segment_count"],
             staged["checksum_algo"], staged["checksum_value"]),
        ).fetchone()
        connection.execute(
            """INSERT INTO digital_component_blobs
                   (content_set_id, segment_no, segment_size,
                    segment_checksum_algo, segment_checksum_value, content, date_stored)
               SELECT %s, segment_no, segment_size, segment_checksum_algo,
                      segment_checksum_value, content, date_stored
               FROM record_draft_component_blobs
               WHERE record_draft_component_id = %s ORDER BY segment_no""",
            (content_set["id"], draft_component_id),
        )
        connection.execute(
            """UPDATE digital_components SET active_content_set_id = %s,
                   upload_completed_at = CURRENT_TIMESTAMP WHERE id = %s""",
            (content_set["id"], component_id),
        )

    def location(self, connection: Connection, component_id: int) -> ContentLocation | None:
        row = connection.execute(
            """SELECT content_set.id AS content_set_id, content_set.size_in_bytes,
                      content_set.segment_count
               FROM digital_components component
               JOIN digital_component_content_sets content_set
                 ON content_set.id = component.active_content_set_id
               WHERE component.id = %s AND component.content_status = 'available'
                 AND content_set.status = 'active'""", (component_id,),
        ).fetchone()
        return None if row is None else ContentLocation(**row)

    def iter_content(
        self, location: ContentLocation, start: int = 0, end: int | None = None,
    ) -> Iterator[bytes]:
        stop = location.size_in_bytes if end is None else min(end, location.size_in_bytes)
        if start >= stop:
            return
        offset = 0
        with pool.connection() as connection:
            with connection.cursor(name=f"content_stream_{location.content_set_id}") as cursor:
                cursor.execute(
                    """SELECT segment_size, content FROM digital_component_blobs
                       WHERE content_set_id = %s ORDER BY segment_no""",
                    (location.content_set_id,),
                )
                for row in cursor:
                    segment_start = offset
                    segment_end = offset + row["segment_size"]
                    offset = segment_end
                    if segment_end <= start:
                        continue
                    if segment_start >= stop:
                        break
                    content = bytes(row["content"])
                    local_start = max(0, start - segment_start)
                    local_end = min(len(content), stop - segment_start)
                    if local_start < local_end:
                        yield content[local_start:local_end]

    def read(self, connection: Connection, component_id: int) -> bytes | None:
        location = self.location(connection, component_id)
        return None if location is None else b"".join(self.iter_content(location))

    def delete(self, connection: Connection, component_id: int) -> bool:
        row = connection.execute(
            """UPDATE digital_components SET active_content_set_id = NULL
               WHERE id = %s AND active_content_set_id IS NOT NULL RETURNING id""",
            (component_id,),
        ).fetchone()
        connection.execute(
            "DELETE FROM digital_component_content_sets WHERE digital_component_id = %s",
            (component_id,),
        )
        return row is not None


def configured_storage() -> ContentStorage:
    backend = os.getenv("CONTENT_STORAGE_BACKEND", "postgresql").strip().lower()
    if backend != "postgresql":
        raise RuntimeError(f"unsupported CONTENT_STORAGE_BACKEND: {backend}")
    return PostgreSQLContentStorage()


@dataclass(frozen=True)
class GovernedUpload:
    """Server-owned staging reference; never accepted from an HTTP client."""
    draft_id: int
    component_id: int
    file_name: str
    mime_type: str
    size_in_bytes: int
    checksum_value: str


@contextmanager
def stage_governed_upload(upload: UploadFile, settings, *, connection_factory=None):
    """Stage bounded segments before taking workflow/destination locks.

    An ownerless, unplaced internal draft is invisible to personal draft APIs.
    Each segment commits separately. Final record/component/document promotion
    uses the caller's one domain transaction. Abandonment uses existing draft
    and upload-session expiry cleanup; normal exit always removes the staging.
    No filesystem storage, new setting or content bytes in audit metadata.
    """
    factory = connection_factory or pool.connection
    inspected = inspect_upload(upload, settings)
    name = (upload.filename or 'unnamed').replace('\\', '/').rsplit('/', 1)[-1] or 'unnamed'
    mime = upload.content_type or 'application/octet-stream'
    draft_id = None
    try:
        with factory() as c:
            with c.transaction():
                draft_id = c.execute("INSERT INTO record_drafts(owner_user_id,medium) VALUES(NULL,'digital') RETURNING id").fetchone()['id']
                component_id = c.execute('''INSERT INTO record_draft_components
                 (draft_id,component_order,file_name,mime_type,size_in_bytes,checksum_algo,checksum_value)
                 VALUES(%s,1,%s,%s,%s,'sha256',%s) RETURNING id''',
                 (draft_id,name,mime,inspected.size_in_bytes,inspected.checksum_value)).fetchone()['id']
                session_id = c.execute('''INSERT INTO content_upload_sessions(draft_component_id,status,expires_at)
                 VALUES(%s,'uploading',CURRENT_TIMESTAMP + (LEAST(%s::numeric,EXTRACT(EPOCH FROM
                   (TIMESTAMPTZ '9999-12-31 00:00:00+00' - CURRENT_TIMESTAMP))) * interval '1 second')) RETURNING id''',
                 (component_id,settings['CONTENT_UPLOAD_SESSION_TTL_SECONDS'])).fetchone()['id']
            digest = hashlib.sha256(); count = 0; size = 0
            while chunk := upload.file.read(settings['CONTENT_SEGMENT_SIZE_BYTES']):
                size += len(chunk)
                if size > settings['MAX_UPLOAD_SIZE_BYTES']:
                    raise HTTPException(413, detail='file exceeds the configured upload limit')
                digest.update(chunk)
                algorithm, checksum = _segment_digest(chunk, settings)
                with c.transaction():
                    c.execute('''INSERT INTO record_draft_component_blobs
                     (record_draft_component_id,segment_no,segment_size,segment_checksum_algo,segment_checksum_value,content)
                     VALUES(%s,%s,%s,%s,%s,%s)''',(component_id,count,len(chunk),algorithm,checksum,chunk))
                    count += 1
                    c.execute('''UPDATE content_upload_sessions SET next_segment_no=%s,bytes_received=%s,
                     date_updated=CURRENT_TIMESTAMP WHERE id=%s''',(count,size,session_id))
            if size != inspected.size_in_bytes or digest.hexdigest() != inspected.checksum_value:
                raise HTTPException(409, detail='upload changed while staging')
            with c.transaction():
                c.execute('''UPDATE record_draft_components SET content_status='available',segment_count=%s,
                 upload_completed_at=CURRENT_TIMESTAMP WHERE id=%s''',(count,component_id))
                c.execute("UPDATE content_upload_sessions SET status='completed',date_updated=CURRENT_TIMESTAMP WHERE id=%s",(session_id,))
        yield GovernedUpload(draft_id,component_id,name,mime,size,inspected.checksum_value)
    finally:
        upload.file.seek(0)
        if draft_id is not None:
            with factory() as c:
                c.execute('DELETE FROM record_drafts WHERE id=%s AND owner_user_id IS NULL',(draft_id,))
