"""Bounded, idempotent cleanup for abandoned segmented-content storage."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .application_settings import cache as settings_cache, load_snapshot
from .database import database_url
from .application_settings_migration import readiness, MigrationInvalid


LOCK_KEY = 2_027_091_701


@dataclass
class CleanupResult:
    expired_sessions: int = 0
    removed_sessions: int = 0
    removed_drafts: int = 0
    removed_content_sets: int = 0
    reclaimed_bytes: int = 0


def cleanup_content(connection: Connection, *, batch_size: int = 100, dry_run: bool = False) -> CleanupResult:
    result = CleanupResult()
    connection.execute(
        """SELECT set_config('app.actor_type', 'automated_process', true),
                  set_config('app.actor_name', 'Content cleanup worker', true),
                  set_config('app.event_source', 'scheduled_job', true)"""
    )
    locked = connection.execute("SELECT pg_try_advisory_xact_lock(%s) AS locked", (LOCK_KEY,)).fetchone()
    if not locked["locked"]:
        return result

    sessions = connection.execute(
        """SELECT id, draft_component_id, content_set_id, status,
                  COALESCE(bytes_received, 0) AS bytes_received
           FROM content_upload_sessions
           WHERE (status IN ('uploading', 'interrupted', 'finalizing') AND expires_at <= CURRENT_TIMESTAMP)
              OR status IN ('failed', 'cancelled', 'expired')
           ORDER BY id
           FOR UPDATE SKIP LOCKED LIMIT %s""",
        (batch_size,),
    ).fetchall()
    for session in sessions:
        result.reclaimed_bytes += session["bytes_received"]
        if session["status"] in {"uploading", "interrupted", "finalizing"}:
            result.expired_sessions += 1
        if dry_run:
            continue
        connection.execute(
            "UPDATE content_upload_sessions SET status = 'expired', date_updated = CURRENT_TIMESTAMP WHERE id = %s",
            (session["id"],),
        )
        if session["draft_component_id"] is not None:
            connection.execute(
                "DELETE FROM record_draft_component_blobs WHERE record_draft_component_id = %s",
                (session["draft_component_id"],),
            )
            connection.execute(
                """UPDATE record_draft_components SET content_status = 'expired', segment_count = NULL
                   WHERE id = %s AND content_status <> 'available'""",
                (session["draft_component_id"],),
            )
        if session["content_set_id"] is not None:
            deleted = connection.execute(
                """DELETE FROM digital_component_content_sets content_set
                   WHERE content_set.id = %s
                     AND NOT EXISTS (
                         SELECT 1 FROM digital_components component
                         WHERE component.active_content_set_id = content_set.id
                     ) RETURNING id""",
                (session["content_set_id"],),
            ).fetchone()
            result.removed_content_sets += int(deleted is not None)
        connection.execute("DELETE FROM content_upload_sessions WHERE id = %s", (session["id"],))
        result.removed_sessions += 1

    if not dry_run:
        completed = connection.execute(
            """DELETE FROM content_upload_sessions
               WHERE id IN (
                   SELECT id FROM content_upload_sessions
                   WHERE status = 'completed' AND expires_at <= CURRENT_TIMESTAMP
                   ORDER BY id LIMIT %s
               ) RETURNING id""",
            (batch_size,),
        ).fetchall()
        result.removed_sessions += len(completed)

    expired_drafts = connection.execute(
        """SELECT id,
                  COALESCE((SELECT sum(blob.segment_size)
                    FROM record_draft_components component
                    JOIN record_draft_component_blobs blob
                      ON blob.record_draft_component_id = component.id
                   WHERE component.draft_id = draft.id), 0) AS stored_bytes
           FROM record_drafts draft
           WHERE expires_at <= CURRENT_TIMESTAMP
           ORDER BY id FOR UPDATE SKIP LOCKED LIMIT %s""",
        (batch_size,),
    ).fetchall()
    for draft in expired_drafts:
        result.reclaimed_bytes += draft["stored_bytes"]
        result.removed_drafts += 1
        if not dry_run:
            connection.execute("DELETE FROM record_drafts WHERE id = %s", (draft["id"],))

    superseded = connection.execute(
        """SELECT content_set.id,
                  COALESCE(sum(blob.segment_size), 0) AS stored_bytes
           FROM digital_component_content_sets content_set
           LEFT JOIN digital_component_blobs blob ON blob.content_set_id = content_set.id
           WHERE content_set.status IN ('superseded', 'failed')
             AND NOT EXISTS (
                 SELECT 1 FROM digital_components component
                 WHERE component.active_content_set_id = content_set.id
             )
           GROUP BY content_set.id ORDER BY content_set.id
           LIMIT %s""",
        (batch_size,),
    ).fetchall()
    for content_set in superseded:
        result.reclaimed_bytes += content_set["stored_bytes"]
        result.removed_content_sets += 1
        if not dry_run:
            connection.execute(
                "DELETE FROM digital_component_content_sets WHERE id = %s", (content_set["id"],)
            )
    if not dry_run and any((
        result.expired_sessions, result.removed_sessions, result.removed_drafts,
        result.removed_content_sets,
    )):
        connection.execute(
            "SELECT append_domain_event('content_storage', 0, 'CONTENT_CLEANUP', %s)",
            (Jsonb(result.__dict__),),
        )
    return result


def _run_pass(*, batch_size: int, dry_run: bool, watch: bool = False,
              interval_seconds: int | None = None):
    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        settings = settings_cache.for_connection(connection) if watch else load_snapshot(connection)
        if not readiness(connection, snapshot=settings)['ready']:
            raise MigrationInvalid('application_settings_migration_incomplete; run the reviewed preview/apply command')
        result = cleanup_content(connection, batch_size=batch_size, dry_run=dry_run)
        interval = interval_seconds if interval_seconds is not None else settings["CONTENT_CLEANUP_INTERVAL_SECONDS"]
        if dry_run:
            connection.rollback()
        return result, interval


def run_once(*, batch_size: int, dry_run: bool) -> CleanupResult:
    return _run_pass(batch_size=batch_size, dry_run=dry_run)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean expired ERMS content uploads and drafts")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--watch", action="store_true", help="run continuously as the dedicated cleanup worker")
    parser.add_argument(
        "--interval-seconds", type=int,
        default=None, help="Explicit per-invocation override; default is database CONTENT_CLEANUP_INTERVAL_SECONDS",
    )
    arguments = parser.parse_args()
    if arguments.batch_size < 1:
        parser.error("--batch-size must be positive")
    if arguments.interval_seconds is not None and arguments.interval_seconds < 1:
        parser.error("--interval-seconds must be positive")
    while True:
        result, interval = _run_pass(batch_size=arguments.batch_size, dry_run=arguments.dry_run,
                                     watch=arguments.watch, interval_seconds=arguments.interval_seconds)
        print(
            f"expired_sessions={result.expired_sessions} removed_sessions={result.removed_sessions} "
            f"removed_drafts={result.removed_drafts} removed_content_sets={result.removed_content_sets} "
            f"reclaimed_bytes={result.reclaimed_bytes} dry_run={arguments.dry_run}",
            flush=True,
        )
        if not arguments.watch:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
