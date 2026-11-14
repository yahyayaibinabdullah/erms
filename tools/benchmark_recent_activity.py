"""Benchmark recent activity on a fresh disposable copy of the dashboard fixture."""
import argparse
import ast
from datetime import datetime, timedelta, timezone
from itertools import groupby
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import psycopg
from dotenv import dotenv_values
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.benchmark_dashboard import PASSWORD, seed
from tools.initialize_database import initialize

ACTIVITY = "/api/v1/auth/me/recent-activity"


def previous_statement(ref):
    source = subprocess.check_output(
        ["git", "show", f"{ref}:backend/services/api/authentication.py"], cwd=ROOT, text=True,
    )
    route = next(node for node in ast.parse(source).body
                 if isinstance(node, ast.FunctionDef) and node.name == "my_recent_activity")
    return next(node.value for node in ast.walk(route)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and "WITH governed_resource_events AS" in node.value)


def measure_queries(url, baseline, since, output):
    from backend.services.api.recent_activity import ACTIVITY_STATEMENTS
    with psycopg.connect(url, row_factory=dict_row) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        reader = connection.execute("SELECT id FROM users WHERE email='reader@test.invalid'").fetchone()["id"]
        connection.execute("SELECT set_config('app.user_id',%s,true)", (str(reader),))
        connection.execute("SET LOCAL statement_timeout='120s'")
        queries = {
            "baseline": (baseline, (reader,since,since)*3+(50,)),
            **{kind: (ACTIVITY_STATEMENTS[kind], (reader,since,reader,since,50))
               for kind in ("aggregation","record")},
        }
        results = {}
        for kind, (statement, params) in queries.items():
            samples = []
            for _ in range(3):
                started = time.perf_counter()
                rows = connection.execute(statement, params).fetchall()
                samples.append(round((time.perf_counter()-started)*1000, 3))
            results[kind] = {"sql_ms": samples, "rows": len(rows)}
            print(kind, results[kind], flush=True)
            if kind == "baseline":
                expected = rows
                continue
            fields = ("entity_type","entity_id","operation","occurred_at")
            actual = [{field: row[field] for field in fields} for row in rows]
            reference = [
                row for row in expected if row["entity_type"] == kind
            ]
            # The old query leaves the order unspecified when type, resource
            # and timestamp are all equal across different operations.
            def comparable(entries):
                return [(key, sorted(group, key=lambda row: row["operation"]))
                        for key, group in groupby(entries, lambda row: (
                            row["occurred_at"], row["entity_type"], row["entity_id"]))]

            if comparable(actual) != comparable(reference):
                (output / f"{kind}-mismatch.json").write_text(
                    json.dumps({"expected":reference,"actual":actual}, default=str, indent=2)+"\n",
                )
                raise AssertionError(f"{kind} membership or defined order changed")
            plan = connection.execute(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, params,
            ).fetchone()["QUERY PLAN"]
            (output / f"{kind}-plan.json").write_text(json.dumps(plan, indent=2)+"\n")
        results["events"] = connection.execute(
            "SELECT count(*) AS total, count(*) FILTER (WHERE actor_user_id=%s AND occurred_at>=%s)"
            " AS reader_recent FROM event_history", (reader,since),
        ).fetchone()
        results["aggregations"], results["records"] = connection.execute(
            "SELECT (SELECT count(*) FROM aggregations) AS aggregations,"
            " (SELECT count(*) FROM records) AS records",
        ).fetchone().values()
        results["postgres"] = connection.info.server_version
        results["jit_available"] = connection.execute("SELECT pg_jit_available() AS available").fetchone()["available"]
        return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--webui-launcher", type=Path, help="Optional local WebUI script on port 18083")
    args = parser.parse_args()
    baseline = previous_statement(args.baseline_ref)
    # Refuse to time or sign into a service that the benchmark did not start.
    for port in (18030, 18083) if args.webui_launcher else (18030,):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    args.output.mkdir(parents=True, exist_ok=False)
    configuration = {key: str(value) for key, value in {**dotenv_values(ROOT / ".env"), **os.environ}.items()
                     if value is not None}
    name = "erms_messaging_test_acl_" + uuid4().hex
    admin_url = make_conninfo(configuration["DATABASE_URL"], dbname="postgres")
    url = make_conninfo(configuration["DATABASE_URL"], dbname=name)
    configuration.update(DATABASE_URL=url, AUTH_COOKIE_SECURE="false", PYTHONPATH=str(ROOT),
                         WEBUI_API_URL="http://127.0.0.1:18030", WEBUI_PORT="18083", WEBUI_HOST="127.0.0.1",
                         WEBUI_RELOAD="false", NICEGUI_REDIS_URL="", WEBUI_STORAGE_SECRET=uuid4().hex,
                         NICEGUI_STORAGE_PATH=str((args.output / "browser-storage").resolve()))
    created = False
    processes = []
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        created = True
        print("Created disposable database", name, flush=True)
        with psycopg.connect(url) as connection:
            initialize(connection)
            for filename in ("messaging.sql","hold-notification-producers.sql","relationship-types.sql"):
                connection.execute((ROOT / "database/seeds" / filename).read_text(), prepare=False)
        seed(configuration, 18_400)
        # Exercise all three aggregation groups. Existing fixture events cover
        # record changes and component views, but have no aggregation edits.
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute("""
                INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_type,source,before_state,after_state,occurred_at)
                SELECT 'aggregation',aggregation.id,op.operation,actor.id,'user','seeding',
                       CASE WHEN op.operation='UPDATE' THEN '{}'::jsonb END,'{}'::jsonb,
                       CURRENT_TIMESTAMP - aggregation.id * interval '1 second'
                  FROM aggregations aggregation CROSS JOIN users actor
                 CROSS JOIN (VALUES ('CREATE'),('UPDATE')) op(operation)
                 WHERE actor.email='reader@test.invalid'
            """)
            connection.execute("VACUUM ANALYZE event_history")
        print("Fixture ready", flush=True)
        since = datetime.now(timezone.utc)-timedelta(days=30)
        report = measure_queries(url, baseline, since, args.output)
        (args.output / "timings.json").write_text(json.dumps(report,indent=2)+"\n")
        with (args.output/"api.log").open("w") as log:
            processes.append(subprocess.Popen(
                [sys.executable,"-m","uvicorn","backend.services.api.main:app","--host","127.0.0.1","--port","18030"],
                cwd=ROOT,env=configuration,stdout=log,stderr=subprocess.STDOUT,
            ))
        with httpx.Client(base_url=configuration["WEBUI_API_URL"], timeout=30) as client:
            for _ in range(100):
                if processes[0].poll() is not None:
                    raise RuntimeError("Benchmark API exited")
                try:
                    if client.get("/health",timeout=1).is_success:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.2)
            else:
                raise RuntimeError("Benchmark API did not become ready")
            client.post("/api/v1/auth/login",json={"email":"reader@test.invalid","password":PASSWORD}).raise_for_status()
            for kind in ("aggregation","record"):
                samples = []
                for _ in range(7):
                    started = time.perf_counter()
                    response = client.get(ACTIVITY,params={"entity_type":kind,"limit":50})
                    samples.append(round((time.perf_counter()-started)*1000,3))
                    response.raise_for_status()
                    rows = response.json()
                    assert len(rows) == 150 and all(row["entity_type"] == kind for row in rows)
                report[kind].update(http_ms=samples, response_bytes=len(response.content))
                print(kind, report[kind], flush=True)
        (args.output / "timings.json").write_text(json.dumps(report,indent=2)+"\n")
        if args.webui_launcher:
            with (args.output/"webui.log").open("w") as log:
                processes.append(subprocess.Popen(
                    [str(ROOT/"frontend/webui/.venv/bin/python"),str(args.webui_launcher.resolve())],
                    cwd=ROOT,env=configuration,stdout=log,stderr=subprocess.STDOUT,
                ))
            print("WebUI benchmark at http://127.0.0.1:18083/", flush=True)
            while not (args.output/"stop").exists() and all(process.poll() is None for process in processes):
                time.sleep(.2)
            if not (args.output/"stop").exists():
                raise RuntimeError("A benchmark service exited before browser verification")
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if created:
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            print("Dropped disposable database", name, flush=True)


if __name__ == "__main__":
    def stop(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        main()
    except KeyboardInterrupt:
        pass
