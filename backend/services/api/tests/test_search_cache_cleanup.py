"""Independent cache maintenance; run only through the disposable DB runner."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
import psycopg

from backend.services.api import session_cleanup as worker
from backend.services.api.application_settings import cache
from backend.services.api.tests.test_application_settings import save, items
from backend.services.api.tests.test_application_settings_phase4 import db
from backend.services.api.tests.test_application_settings_phase5_authentication import make_session

INTERVAL = 'GLOBAL_SEARCH_CACHE_CLEANUP_INTERVAL_SECONDS'
BATCH = 'GLOBAL_SEARCH_CACHE_CLEANUP_BATCH_SIZE'


def test_leadership_survives_job_commits_and_rollback_then_releases(client):
    seed_lists()
    with worker._worker_connection() as leader, worker._worker_connection() as standby:
        assert worker._try_leadership(leader)
        assert not worker._try_leadership(standby)
        worker._run_due_passes(worker.CleanupSchedule(), connection=leader, dry_run=True)
        assert count_lists() == 5
        assert not worker._try_leadership(standby)
        worker._run_due_passes(worker.CleanupSchedule(), connection=leader)
        assert count_lists() == 1
        assert not worker._try_leadership(standby)
        # Manual/legacy login-only command must not bypass the active leader.
        assert worker.run_once().selected == 0
        leader.close()
        assert worker._try_leadership(standby)


def test_lost_leader_connection_cannot_continue_deleting(client):
    seed_lists()
    leader = worker._worker_connection()
    try:
        assert worker._try_leadership(leader)
        with db() as c:
            c.execute('SELECT pg_terminate_backend(%s)', (leader.info.backend_pid,))
        with pytest.raises(psycopg.OperationalError):
            worker._run_due_passes(worker.CleanupSchedule(), connection=leader)
        assert count_lists() == 5
        with worker._worker_connection() as replacement:
            assert worker._try_leadership(replacement)
            worker._run_due_passes(worker.CleanupSchedule(), connection=replacement)
        assert count_lists() == 1
    finally:
        leader.close()


def seed_lists(expired=4, active=1):
    session_id = make_session()[1]
    with db() as c:
        c.execute("""
            INSERT INTO global_search_results
                (session_id,tab_id,user_id,requires_tab_id,search_id,fingerprint,hits,truncated,started_at,expires_at)
            SELECT %s,md5(n::text)::uuid,1,true,md5(n::text)::uuid,'cleanup-fixture','[]',false,
                now()-interval '1 hour',now()+CASE WHEN n<=%s THEN -interval '1 minute' ELSE interval '1 hour' END
            FROM generate_series(1,%s) n
        """, (session_id, expired, expired + active))
    return session_id


def count_lists():
    with db() as c:
        return c.execute('SELECT count(*) AS n FROM global_search_results').fetchone()['n']


def test_defaults_delete_5000_lists_not_hits_preserve_active_and_dry_run(client):
    assert items(client)[INTERVAL]['value'] == 60
    assert items(client)[BATCH]['value'] == 5000
    seed_lists(expired=5002)
    with db() as c:
        dry = worker.cleanup_search_cache(c, dry_run=True)
        assert (dry.selected, dry.removed) == (5000, 0)
    assert count_lists() == 5003
    with db() as c:
        first = worker.cleanup_search_cache(c)
    assert first.removed == 5000 and count_lists() == 3
    with db() as c:
        assert worker.cleanup_search_cache(c).removed == 2
        assert worker.cleanup_search_cache(c).removed == 0
    assert count_lists() == 1


def test_cache_lock_and_busy_tab_do_not_block_other_work(client):
    session_id = seed_lists()
    with db() as held:
        held.execute('SELECT pg_advisory_xact_lock(%s)', (worker.SEARCH_CACHE_LOCK_KEY,))
        with db() as c:
            c.execute("SET LOCAL statement_timeout='1s'")
            assert worker.cleanup_search_cache(c).lock_skipped
        assert count_lists() == 5
    with db() as held:
        held.execute('SELECT pg_advisory_xact_lock(%s)', (worker.LOCK_KEY,))
        held.execute("SELECT 1 FROM global_search_results WHERE session_id=%s AND tab_id=md5('1')::uuid FOR UPDATE", (session_id,))
        with db() as c:
            c.execute("SET LOCAL statement_timeout='1s'")
            assert worker.cleanup_search_cache(c).removed == 3
    with db() as c:
        assert worker.cleanup_search_cache(c).removed == 1
    assert count_lists() == 1


def test_independent_deadlines_live_settings_and_cli_overrides(client, monkeypatch):
    seed_lists(expired=6)
    assert save(client, {INTERVAL: 60, BATCH: 1}).status_code == 200
    clock = [100.0]
    monkeypatch.setattr(worker.time, 'monotonic', lambda: clock[0])
    schedule = worker.CleanupSchedule()
    session, search, delay = worker._run_due_passes(schedule, batch_size=7, interval_seconds=3600)
    assert session is not None and search.removed == 1 and delay == 30
    clock[0] += 30
    assert worker._run_due_passes(schedule) == (None, None, 30)
    # Changing the interval must shorten the current wait, not wait an hour for
    # login cleanup; the login CLI override must not become the cache limit.
    assert save(client, {INTERVAL: 10, BATCH: 2}).status_code == 200
    session, search, delay = worker._run_due_passes(schedule, batch_size=7, interval_seconds=3600)
    assert session is None and search.removed == 2 and delay == 10
    assert schedule.sessions_finished == 100
    clock[0] += 10
    session, search, _ = worker._run_due_passes(schedule)
    assert session is None and search.removed == 2
    # Retuning the login interval does not reset the search deadline either.
    assert save(client, {'AUTH_SESSION_CLEANUP_INTERVAL_SECONDS': 40}).status_code == 200
    session, search, _ = worker._run_due_passes(schedule)
    assert session is not None and search is None
    assert count_lists() == 2


@pytest.mark.parametrize('key', [INTERVAL, BATCH])
def test_settings_are_positive_integers_and_database_owned(client, monkeypatch, key):
    monkeypatch.setenv(key, 'invalid-obsolete-environment')
    for invalid in (0, -1, True, 1.5, '60'):
        assert save(client, {key: invalid}).status_code == 422
    assert save(client, {key: 7}).status_code == 200
    with db() as c:
        assert c.execute('SELECT application_setting_value_valid(%s,%s::jsonb,NULL) AS valid', (key, '0')).fetchone()['valid'] is False
        assert cache.for_connection(c)[key] == 7


def test_cache_batch_commits_separately_from_failing_login_audit(client, monkeypatch):
    seed_lists()
    def fail(*args, **kwargs):
        raise RuntimeError('login_audit_fixture_failure')
    monkeypatch.setattr(worker, 'cleanup_sessions', fail)
    with pytest.raises(RuntimeError, match='login_audit_fixture_failure'):
        worker._run_due_passes(worker.CleanupSchedule())
    assert count_lists() == 1


def test_watch_process_starts_cleans_and_stops_promptly_on_sigterm(client, tmp_path):
    seed_lists()
    output = tmp_path / 'worker.log'
    with output.open('w') as log:
        process = subprocess.Popen(
            [sys.executable, '-u', '-m', 'backend.services.api.session_cleanup', '--watch'],
            stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy(),
        )
        try:
            deadline = time.monotonic() + 15
            while 'job=login_sessions' not in output.read_text():
                assert process.poll() is None, output.read_text()
                assert time.monotonic() < deadline, output.read_text()
                time.sleep(0.05)
            assert 'job=search_cache selected=4 removed=4' in output.read_text()
            assert count_lists() == 1
            started = time.monotonic()
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=3) == 0
            assert time.monotonic() - started < 3
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize('configured', [False, True])
def test_migration_110_defaults_or_preserves_values_and_matches_canonical_validator(client, configured):
    if configured:
        assert save(client, {INTERVAL: 13, BATCH: 27}).status_code == 200
    root = Path(__file__).resolve().parents[4]
    with db() as c:
        before = c.execute("SELECT pg_get_functiondef('application_setting_value_valid(text,jsonb,bytea)'::regprocedure) AS ddl").fetchone()['ddl']
        if not configured:
            # Recreate the pre-110 absence in this disposable fixture only.
            c.execute('ALTER TABLE application_settings DISABLE TRIGGER USER')
            c.execute('DELETE FROM application_settings WHERE key=ANY(%s)', ([INTERVAL, BATCH],))
            c.execute('ALTER TABLE application_settings ENABLE TRIGGER USER')
        c.execute("DELETE FROM schema_migrations WHERE version='110_search_cache_cleanup_settings'")
        c.commit()
        c.execute((root / 'database/migrations/110_search_cache_cleanup_settings.sql').read_text(), prepare=False)
        after = c.execute("SELECT pg_get_functiondef('application_setting_value_valid(text,jsonb,bytea)'::regprocedure) AS ddl").fetchone()['ddl']
        assert before == after
    cache.invalidate()
    assert items(client)[INTERVAL]['value'] == (13 if configured else 60)
    assert items(client)[BATCH]['value'] == (27 if configured else 5000)
