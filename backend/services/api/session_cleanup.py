"""Bounded cleanup for expired and retained revoked login sessions."""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .application_settings import cache as settings_cache, load_snapshot
from .database import database_url
from .application_settings_migration import readiness, MigrationInvalid


LOCK_KEY = 2_026_091_801


@dataclass
class SessionCleanupResult:
    selected: int = 0
    expired_events: int = 0
    revocation_events_backfilled: int = 0
    removed: int = 0


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _snapshot(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": session["id"],
        "client_ip": str(session["client_ip"]) if session.get("client_ip") else None,
        "user_agent": (
            session["user_agent"][:1000] if session.get("user_agent") else None
        ),
        "session_created_at": _timestamp(session.get("date_created")),
        "last_seen_at": _timestamp(session.get("last_seen_at")),
        "expires_at": _timestamp(session.get("expires_at")),
        "absolute_expires_at": _timestamp(session.get("absolute_expires_at")),
        "revoked_at": _timestamp(session.get("revoked_at")),
    }


def _has_revocation_event(connection: Connection, session_id: int) -> bool:
    return connection.execute(
        """
        SELECT EXISTS (
            SELECT 1
              FROM event_history
             WHERE operation = 'SESSION_REVOKED'
               AND (
                    metadata @> jsonb_build_object('session_id', %s)
                    OR metadata -> 'sessions' @> jsonb_build_array(
                        jsonb_build_object('session_id', %s)
                    )
               )
        ) AS found
        """,
        (session_id, session_id),
    ).fetchone()["found"]


def cleanup_sessions(
    connection: Connection,
    *,
    retention_days: int | None = None,
    batch_size: int | None = None,
    dry_run: bool = False,
) -> SessionCleanupResult:
    if retention_days is None or batch_size is None:
        settings = settings_cache.for_connection(connection)
        retention_days = settings["AUTH_SESSION_RETENTION_DAYS"] if retention_days is None else retention_days
        batch_size = settings["AUTH_SESSION_CLEANUP_BATCH_SIZE"] if batch_size is None else batch_size
    now = datetime.now(timezone.utc)
    cutoff = datetime.min.replace(tzinfo=timezone.utc) if retention_days >= now.toordinal() else now - timedelta(days=retention_days)
    result = SessionCleanupResult()
    connection.execute(
        """SELECT set_config('app.actor_type', 'automated_process', true),
                  set_config('app.actor_name', 'Login session cleanup worker', true),
                  set_config('app.event_source', 'scheduled_job', true),
                  set_config('app.change_reason', 'Expired login-session retention period', true)"""
    )
    locked = connection.execute(
        "SELECT pg_try_advisory_xact_lock(%s) AS locked", (LOCK_KEY,)
    ).fetchone()
    if not locked["locked"]:
        return result

    sessions = connection.execute(
        """
        SELECT id, user_id, client_ip, user_agent, date_created, last_seen_at,
               expires_at, absolute_expires_at, revoked_at
          FROM login_sessions
         WHERE (revoked_at IS NOT NULL
                AND revoked_at <= %s)
            OR (revoked_at IS NULL
                AND LEAST(expires_at, absolute_expires_at)
                    <= %s)
         ORDER BY COALESCE(revoked_at, LEAST(expires_at, absolute_expires_at)), id
         FOR UPDATE SKIP LOCKED
         LIMIT %s
        """,
        (cutoff, cutoff, batch_size),
    ).fetchall()
    result.selected = len(sessions)
    if dry_run:
        return result

    for session in sessions:
        metadata = _snapshot(session)
        if session["revoked_at"] is None:
            metadata.update({
                "termination_reason": "expired",
                "retention_days": retention_days,
            })
            connection.execute(
                "SELECT append_domain_event('user', %s, 'SESSION_EXPIRED', %s)",
                (session["user_id"], Jsonb(metadata)),
            )
            result.expired_events += 1
        elif not _has_revocation_event(connection, session["id"]):
            metadata.update({
                "revocation_scope": "individual",
                "revocation_reason": "legacy_revocation_audit_backfill",
                "sessions_revoked": 1,
                "retention_days": retention_days,
            })
            connection.execute(
                "SELECT append_domain_event('user', %s, 'SESSION_REVOKED', %s)",
                (session["user_id"], Jsonb(metadata)),
            )
            result.revocation_events_backfilled += 1
        connection.execute("DELETE FROM login_sessions WHERE id = %s", (session["id"],))
        result.removed += 1
    return result


def _run_pass(*, retention_days: int | None = None, batch_size: int | None = None,
              dry_run: bool = False, watch: bool = False, interval_seconds: int | None = None):
    with psycopg.connect(database_url(), row_factory=dict_row) as connection:
        settings = settings_cache.for_connection(connection) if watch else load_snapshot(connection)
        if not readiness(connection, snapshot=settings)['ready']:
            raise MigrationInvalid('application_settings_migration_incomplete; run the reviewed preview/apply command')
        result = cleanup_sessions(connection,
            retention_days=settings['AUTH_SESSION_RETENTION_DAYS'] if retention_days is None else retention_days,
            batch_size=settings['AUTH_SESSION_CLEANUP_BATCH_SIZE'] if batch_size is None else batch_size,
            dry_run=dry_run)
        interval = settings['AUTH_SESSION_CLEANUP_INTERVAL_SECONDS'] if interval_seconds is None else interval_seconds
        if dry_run:
            connection.rollback()
        return result, interval


def run_once(*, retention_days: int | None = None, batch_size: int | None = None,
             dry_run: bool = False) -> SessionCleanupResult:
    return _run_pass(retention_days=retention_days,batch_size=batch_size,dry_run=dry_run)[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit and remove expired or retained revoked ERMS login sessions"
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None, help="Explicit override; default is database AUTH_SESSION_RETENTION_DAYS",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None, help="Explicit override; default is database AUTH_SESSION_CLEANUP_BATCH_SIZE",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=None, help="Explicit override; default is database AUTH_SESSION_CLEANUP_INTERVAL_SECONDS",
    )
    arguments = parser.parse_args()
    if arguments.retention_days is not None and arguments.retention_days < 0:
        parser.error("--retention-days cannot be negative")
    if arguments.batch_size is not None and arguments.batch_size < 1:
        parser.error("--batch-size must be positive")

    if arguments.interval_seconds is not None and arguments.interval_seconds < 1:
        parser.error("--interval-seconds must be positive")
    while True:
        result, interval = _run_pass(
            retention_days=arguments.retention_days,
            batch_size=arguments.batch_size,
            dry_run=arguments.dry_run, watch=arguments.watch, interval_seconds=arguments.interval_seconds,
        )
        print(
            f"selected={result.selected} expired_events={result.expired_events} "
            f"revocation_events_backfilled={result.revocation_events_backfilled} "
            f"removed={result.removed} dry_run={arguments.dry_run}",
            flush=True,
        )
        if not arguments.watch:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
