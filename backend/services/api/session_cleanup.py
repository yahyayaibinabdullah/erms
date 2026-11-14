"""Standalone worker for login history and expired search lists, on separate schedules."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .application_settings import CACHE_SECONDS, cache as settings_cache, load_snapshot
from .database import database_url
from .application_settings_migration import readiness, MigrationInvalid


LOCK_KEY = 2_026_091_801
SEARCH_CACHE_LOCK_KEY = 2_026_091_802
# Database-scoped session lock, distinct from the per-job transaction locks.
# Multiple API hosts/local launchers may run this standalone command. Only the
# holder runs either job; other watch processes remain inexpensive standbys.
LEADER_LOCK_KEY = 2_026_091_803
LEADER_RETRY_SECONDS = 5


def _worker_connection():
    return psycopg.connect(
        database_url(), row_factory=dict_row, connect_timeout=5,
        application_name="erms-session-cleanup",
    )


def _try_leadership(connection: Connection) -> bool:
    """Acquire once, then retain ownership across commits and idle waits.

    A transaction lock alone only excludes simultaneous passes: a second worker
    could acquire it immediately after our commit and run another batch. A
    session lock instead elects one process for this database for its lifetime.
    Call this only while a standby: session advisory locks are reentrant and
    repeated acquisition by the leader would stack lock counts.

    Crucially, ALL job SQL must use THIS connection. A separate lock connection
    could fail while another connection continued deleting, allowing the old
    and new leaders to work concurrently. Here a lost connection ends both
    leadership and the ability to perform work; errors escape for supervisor
    restart. Never reconnect transparently while retaining a leader flag.
    Use PostgreSQL directly (or session pooling), not transaction pooling.
    """
    locked = connection.execute(
        "SELECT pg_try_advisory_lock(%s) AS locked", (LEADER_LOCK_KEY,),
    ).fetchone()["locked"]
    connection.commit()  # No idle transaction while holding/waiting for ownership.
    return locked


@dataclass
class SessionCleanupResult:
    selected: int = 0
    expired_events: int = 0
    revocation_events_backfilled: int = 0
    removed: int = 0


@dataclass
class SearchCacheCleanupResult:
    selected: int = 0
    removed: int = 0
    lock_skipped: bool = False


@dataclass
class CleanupSchedule:
    # Monotonic completion times: a slow pass must not trigger a catch-up storm.
    # None makes both jobs run immediately when the supervised process starts.
    sessions_finished: float | None = None
    search_finished: float | None = None


def cleanup_search_cache(
    connection: Connection, *, batch_size: int | None = None, dry_run: bool = False,
) -> SearchCacheCleanupResult:
    """Remove at most batch_size expired *lists*, never inspect their JSON hits.

    Request-time expiry/permission checks remain authoritative. Physical cleanup
    is storage maintenance, so a missed pass never extends a list's validity.
    Its own transaction advisory lock prevents overlapping cache passes without
    sharing the login-history job's slower schedule or locks. SKIP LOCKED avoids
    waiting for a search currently replacing/extending a tab's cache row.
    """
    if batch_size is None:
        batch_size = settings_cache.for_connection(connection)["GLOBAL_SEARCH_CACHE_CLEANUP_BATCH_SIZE"]
    locked = connection.execute(
        "SELECT pg_try_advisory_xact_lock(%s) AS locked", (SEARCH_CACHE_LOCK_KEY,),
    ).fetchone()["locked"]
    if not locked:
        return SearchCacheCleanupResult(lock_skipped=True)
    # A statement-stable cutoff permits an expiry-index range scan. Do not use
    # a volatile clock_timestamp() predicate that must be evaluated per row.
    expired = """
        SELECT session_id, tab_id FROM search_results_cache
        WHERE expires_at <= statement_timestamp()
        ORDER BY expires_at, session_id, tab_id LIMIT %s FOR UPDATE SKIP LOCKED
    """
    if dry_run:
        count = connection.execute(
            f"SELECT count(*) AS n FROM ({expired}) expired", (batch_size,),
        ).fetchone()["n"]
        return SearchCacheCleanupResult(selected=count)
    count = connection.execute(f"""
        DELETE FROM search_results_cache saved USING ({expired}) expired
        WHERE saved.session_id = expired.session_id AND saved.tab_id = expired.tab_id
    """, (batch_size,)).rowcount
    return SearchCacheCleanupResult(selected=count, removed=count)


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
    with _worker_connection() as connection:
        if not _try_leadership(connection):
            return SessionCleanupResult(), LEADER_RETRY_SECONDS
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


def _run_due_passes(
    schedule: CleanupSchedule, *, retention_days: int | None = None,
    batch_size: int | None = None, interval_seconds: int | None = None,
    dry_run: bool = False, watch: bool = True, stop: Event | None = None,
    connection: Connection | None = None,
) -> tuple[SessionCleanupResult | None, SearchCacheCleanupResult | None, float]:
    """One process, two deadlines, a separate committed transaction per job.

    Previously cache deletion inherited the hourly, 500-row login-history pass.
    Merely changing its batch limit would still leave expired caches for an hour;
    speeding up that shared loop would unnecessarily repeat login-history work.
    Track each completion independently and poll settings at most 30 seconds
    apart, even when both configured intervals are long. Settings edits therefore
    take effect without restarting the worker or waiting out the old interval.
    """
    session_result = search_result = None
    # Production supplies the connection holding the leadership lock. The
    # optional connection keeps this single-pass helper usable in DB tests.
    with (nullcontext(connection) if connection is not None else _worker_connection()) as connection:
        connection.execute("SELECT 1")  # Detect a lost leader session even when no job is due.
        settings = settings_cache.for_connection(connection) if watch else load_snapshot(connection)
        if not readiness(connection, snapshot=settings)['ready']:
            raise MigrationInvalid('application_settings_migration_incomplete; run the reviewed preview/apply command')
        session_interval = settings['AUTH_SESSION_CLEANUP_INTERVAL_SECONDS'] if interval_seconds is None else interval_seconds
        search_interval = settings['GLOBAL_SEARCH_CACHE_CLEANUP_INTERVAL_SECONDS']
        # Commit the short cache batch before doing any audited login cleanup;
        # slow session event writes must not retain cache row/advisory locks.
        if schedule.search_finished is None or time.monotonic() - schedule.search_finished >= search_interval:
            search_result = cleanup_search_cache(
                connection, batch_size=settings['GLOBAL_SEARCH_CACHE_CLEANUP_BATCH_SIZE'], dry_run=dry_run,
            )
            connection.rollback() if dry_run else connection.commit()
            schedule.search_finished = time.monotonic()
        if (stop is None or not stop.is_set()) and (
            schedule.sessions_finished is None or time.monotonic() - schedule.sessions_finished >= session_interval
        ):
            session_result = cleanup_sessions(
                connection,
                retention_days=settings['AUTH_SESSION_RETENTION_DAYS'] if retention_days is None else retention_days,
                batch_size=settings['AUTH_SESSION_CLEANUP_BATCH_SIZE'] if batch_size is None else batch_size,
                dry_run=dry_run,
            )
            connection.rollback() if dry_run else connection.commit()
            schedule.sessions_finished = time.monotonic()
        connection.rollback() if dry_run else connection.commit()
    now = time.monotonic()
    delays = [CACHE_SECONDS]
    for finished, interval in ((schedule.sessions_finished, session_interval), (schedule.search_finished, search_interval)):
        delays.append(0 if finished is None else max(0, interval - (now - finished)))
    return session_result, search_result, min(delays)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean up expired search lists and audit/remove retained ERMS login sessions"
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
    stop = Event()
    # systemd and the local launcher send SIGTERM. Wake immediately from an idle
    # wait; let an in-flight bounded transaction finish, then exit cleanly. If a
    # supervisor must forcibly stop a stuck process, PostgreSQL rolls back that
    # transaction. No worker is spawned inside a FastAPI request/worker process.
    previous = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with _worker_connection() as connection:
            leader = False
            standby_reported = False
            schedule = CleanupSchedule()
            while not stop.is_set():
                if not leader:
                    leader = _try_leadership(connection)
                    if not leader:
                        if not standby_reported:
                            print("role=standby reason=leader_present", flush=True)
                            standby_reported = True
                        if not arguments.watch:
                            return  # One-shot/dry-run never bypasses a running leader.
                        stop.wait(LEADER_RETRY_SECONDS)
                        continue
                    settings_cache.invalidate()
                    print(f"role=leader backend_pid={connection.info.backend_pid}", flush=True)
                if stop.is_set():
                    break
                result, search_result, delay = _run_due_passes(
                    schedule, retention_days=arguments.retention_days,
                    batch_size=arguments.batch_size, dry_run=arguments.dry_run,
                    watch=arguments.watch, interval_seconds=arguments.interval_seconds,
                    stop=stop, connection=connection,
                )
                if search_result is not None:
                    print(f"job=search_cache selected={search_result.selected} removed={search_result.removed} "
                          f"lock_skipped={search_result.lock_skipped} dry_run={arguments.dry_run}", flush=True)
                if result is not None:
                    print(f"job=login_sessions selected={result.selected} expired_events={result.expired_events} "
                          f"revocation_events_backfilled={result.revocation_events_backfilled} "
                          f"removed={result.removed} dry_run={arguments.dry_run}", flush=True)
                if not arguments.watch:
                    return
                stop.wait(delay)
        # Closing the connection releases leadership, including on SIGTERM.
        # PostgreSQL releases it after detecting a crashed/disconnected owner;
        # standby takeover is bounded by that detection plus its retry delay.
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    main()
