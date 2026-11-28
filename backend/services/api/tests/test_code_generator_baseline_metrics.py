"""Record the legacy creation baseline in the runner's disposable database."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Lock
from time import monotonic, perf_counter, sleep

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


def test_legacy_creation_request_counts_and_parent_lock_wait(client, aggregation, monkeypatch):
    database = conninfo_to_dict(os.environ["DATABASE_URL"])["dbname"]
    assert database.startswith("erms_messaging_test_acl_")
    measurements = []
    lock = Lock()
    calls = []
    original = psycopg.Cursor.execute

    def counted(cursor, query, *args, **kwargs):
        with lock:
            calls.append(1)
        return original(cursor, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Cursor, "execute", counted)

    def measure(name, request, expected):
        with lock:
            calls.clear()
        started = perf_counter()
        response = request()
        elapsed = perf_counter() - started
        assert response.status_code == expected, response.text
        with lock:
            count = len(calls)
        assert count > 0
        measurements.append({
            "operation": name, "seconds": elapsed,
            "cursor_execute_calls_including_authentication": count,
            "status": response.status_code,
        })
        return response.json()

    measure("number_recommendation", lambda: client.get(
        "/api/v1/number-suggestions/records",
        params={"parent_aggregation_id": aggregation["id"]},
    ), 200)
    measure("manual_record_creation", lambda: client.post("/api/v1/records", json={
        "aggregation_id": aggregation["id"], "record_number": "BASELINE-1",
        "title": "Baseline record",
    }), 201)
    draft = measure("numberless_draft_save", lambda: client.post(
        "/api/v1/record-drafts", json={"aggregation_id": aggregation["id"]},
    ), 201)
    assert draft["record_number"] is None
    measure("direct_combined_file_drop", lambda: client.post(
        f"/api/v1/aggregations/{aggregation['id']}/records/file-drop",
        data={"separate_records": "false", "title": "Baseline combined record"},
        files=[("files", ("one.txt", b"one", "text/plain")),
               ("files", ("two.txt", b"two", "text/plain"))],
    ), 201)

    # Observe the actual blocker before releasing it, rather than assuming a
    # fixed sleep proves that resource creation waits for the parent row.
    monkeypatch.setattr(psycopg.Cursor, "execute", original)
    waits = []
    with psycopg.connect(os.environ["DATABASE_URL"]) as blocker, \
            psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row) as observer:
        blocker.execute("SELECT id FROM aggregations WHERE id=%s FOR UPDATE", (aggregation["id"],))
        blocker_pid = blocker.info.backend_pid
        with ThreadPoolExecutor(max_workers=1) as executor:
            started = perf_counter()
            future = executor.submit(client.post, "/api/v1/records", json={
                "aggregation_id": aggregation["id"], "record_number": "BASELINE-WAIT",
                "title": "Baseline parent lock wait",
            })
            try:
                deadline = monotonic() + 10
                while monotonic() < deadline and not future.done():
                    waits = observer.execute(
                        """SELECT wait_event_type,wait_event FROM pg_stat_activity
                           WHERE datname=current_database() AND %s=ANY(pg_blocking_pids(pid))""",
                        (blocker_pid,),
                    ).fetchall()
                    if waits:
                        break
                    sleep(0.02)
            finally:
                blocker.rollback()
            response = future.result(timeout=15)
            elapsed = perf_counter() - started
        assert waits, "No request was observed waiting for the held parent row"
        assert response.status_code == 201, response.text
    measurements.append({"operation": "parent_row_contention", "seconds": elapsed, "observed_waits": waits})

    output = Path(__file__).resolve().parents[4] / ".runtime/custom-code-generators/creation-metrics"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{database}.json").write_text(
        json.dumps({"database": database, "measurements": measurements}, indent=2) + "\n"
    )
