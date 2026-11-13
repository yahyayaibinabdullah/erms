"""Real PostgreSQL session locks, through one shared API event loop."""
import os
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg

from backend.services.api.authentication import hash_secret


def test_authentication_can_finish_while_search_holds_session_reference(client):
    # This is the KEY SHARE lock taken by the cache's login-session FK. Hold it
    # until authentication has completed, rather than releasing it on a timer.
    with ThreadPoolExecutor(max_workers=1) as workers:
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            connection.execute(
                "SELECT id FROM login_sessions WHERE session_token_hash=%s FOR KEY SHARE",
                (hash_secret(client.cookies["erms_session"]),),
            )
            response = workers.submit(client.get, "/api/v1/auth/me").result(timeout=3)
            assert response.status_code == 200, response.text


def test_session_lock_wait_does_not_block_event_loop_and_revocation_wins(client):
    with ThreadPoolExecutor(max_workers=2) as workers:
        with psycopg.connect(os.environ["DATABASE_URL"]) as blocker:
            session_id = blocker.execute(
                "SELECT id FROM login_sessions WHERE session_token_hash=%s FOR UPDATE",
                (hash_secret(client.cookies["erms_session"]),),
            ).fetchone()[0]
            waiting = workers.submit(client.get, "/api/v1/auth/me")
            with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as observer:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    if observer.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE %s=ANY(pg_blocking_pids(pid)))",
                        (blocker.info.backend_pid,),
                    ).fetchone()[0]:
                        break
                    time.sleep(0.01)
                else:
                    raise AssertionError("Authentication never reached the held session lock")
            # A different session's work must proceed on the same TestClient
            # event loop while the first request is demonstrably lock-blocked.
            healthy = workers.submit(client.get, "/health", headers={"Authorization": "Bearer invalid"})
            assert healthy.result(timeout=3).status_code == 200
            assert not waiting.done()
            blocker.execute("UPDATE login_sessions SET revoked_at=clock_timestamp() WHERE id=%s", (session_id,))
        assert waiting.result(timeout=3).status_code == 401
        assert client.get("/api/v1/auth/me").status_code == 401
