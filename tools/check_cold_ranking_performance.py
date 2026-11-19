"""Paired cold-start HTTP ranking waves. Run via run_linux_search_performance.py."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
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
from tools.initialize_database import initialize
from tools.search_benchmark_support import sample_waits_and_io
from tools.search_large_text_fixture import CASES, PASSWORD, fixture, oracle, payload
from tools.search_storage_experiment import inspect

TARGETS = [
    next(c for c in CASES if c[0] == name)
    for name in ("broad_not", "negative_phrase", "broad_phrase")
]
TABLES = [
    "aggregations",
    "records",
    "digital_components",
    "digital_component_content_sets",
    "aggregation_search_documents",
    "record_search_documents",
    "digital_component_search_documents",
    "digital_component_search_chunks",
]


def save(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def cache_files(container, oid, nodes, mode):
    result = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "--user",
            "postgres",
            container,
            "perl",
            "-",
            mode,
            str(oid),
            *map(str, nodes),
        ],
        input=(ROOT / "tools/cold_ranking_cache.pl").read_text(),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def reset_cache(c, container, oid, nodes):
    c.execute("CHECKPOINT")
    for _ in range(5):
        c.execute("SELECT * FROM pg_buffercache_evict_all()").fetchone()
        guest = cache_files(container, oid, nodes, "evict")
        shared = c.execute(
            """SELECT count(*) n FROM pg_buffercache WHERE reldatabase=%s
                            AND relfilenode=ANY(%s::oid[])""",
            (oid, nodes),
        ).fetchone()["n"]
        if guest["resident"] == 0 and shared == 0:
            return {"guest": guest, "postgres_corpus_buffers": shared}
        time.sleep(0.25)
    raise RuntimeError(f"Cache reset incomplete: shared={shared}, Linux pages={guest}")


@contextmanager
def api(url, output, setting):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    output.mkdir()
    with (output / "api.log").open("w") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "tools/search_benchmark_app.py"),
                "--port",
                str(port),
                "--output",
                str(output),
                "--ranking-io-concurrency",
                str(setting),
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "DATABASE_URL": url,
                "AUTH_COOKIE_SECURE": "false",
                "PYTHONPATH": str(ROOT),
            },
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        endpoint = f"http://127.0.0.1:{port}"
        try:
            with httpx.Client(base_url=endpoint, timeout=3) as hc:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline and server.poll() is None:
                    try:
                        if hc.get("/health").status_code == 200:
                            break
                    except httpx.RequestError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError(f"API setup failed: {output}/api.log")
            yield endpoint
        finally:
            server.terminate()
            try:
                server.wait(20)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def execute_wave(pool, clients, cases, reader_ids, expected, c):
    barrier = threading.Barrier(len(cases))

    def submit(slot, case):
        request = payload(case)
        barrier.wait(timeout=15)
        wall = time.time()
        start = time.perf_counter()
        response = clients[slot].post("/api/v1/full-text-search", json=request)
        end = time.perf_counter()
        response.raise_for_status()
        return slot, case[0], wall, start, end, response.json()

    futures = [pool.submit(submit, i, case) for i, case in enumerate(cases)]
    responses = [f.result() for f in futures]
    data = []
    for slot, name, wall, start, end, body in responses:
        cached = c.execute(
            "SELECT user_id, hits FROM search_results_cache WHERE search_id=%s",
            (body["search_id"],),
        ).fetchone()
        wanted = expected[name]
        page = [
            {"type": item["type"], "id": item[item["type"]]["id"], "score": item["score"]}
            for item in body["items"]
        ]
        assert page == wanted["hits"][:100] and cached["hits"] == wanted["hits"]
        assert cached["user_id"] == reader_ids[slot]
        assert sum(body["totals"].values()) == min(1000, wanted["count"])
        assert body["truncated"] == (wanted["count"] > 1000)
        data.append(dict(reader=slot + 1, case=name, start_time=wall, seconds=end - start))
    return data, max(r[4] for r in responses) - min(r[3] for r in responses)


def cgroup_reads(c):
    raw = c.execute("SELECT pg_read_file('/sys/fs/cgroup/io.stat',0,65536) AS data").fetchone()[
        "data"
    ]
    return sum(int(n) for n in re.findall(r"\brbytes=(\d+)", raw))


def experiment(args, url, dbname):
    output = args.output
    with psycopg.connect(url, row_factory=dict_row) as c:
        initialize(c)
        sets = fixture(c)
        storage = inspect(c, "current")
        expected = {case[0]: oracle(c, case, sets) for case in TARGETS}
        save(output / "expected.json", expected)
        c.execute("CREATE EXTENSION pg_buffercache")
        c.execute("SELECT set_config('app.event_source','seeding',true)")
        ids = []
        for n in range(4):
            uid = c.execute(
                "INSERT INTO users(name,email) VALUES(%s,%s) RETURNING id",
                (f"Concurrent reader {n+1}", f"cold{n+1}@performance.invalid"),
            ).fetchone()["id"]
            c.execute(
                """INSERT INTO user_credentials(user_id,password_hash,must_change_password)
                SELECT %s, password_hash, false FROM user_credentials JOIN users ON users.id=user_id
                WHERE email='reader@performance.invalid'""",
                (uid,),
            )
            c.execute(
                """INSERT INTO user_role_assignments(user_id,role_id)
                SELECT %s,id FROM roles WHERE code='PERF'""",
                (uid,),
            )
            ids.append(uid)
        nodes = [
            r["node"]
            for r in c.execute(
                """WITH base AS (
               SELECT oid,reltoastrelid FROM pg_class WHERE oid=ANY(%s::regclass[])),
               heaps AS (SELECT oid FROM base UNION SELECT reltoastrelid FROM base WHERE reltoastrelid<>0),
               all_rels AS (SELECT oid FROM heaps UNION SELECT indexrelid FROM pg_index WHERE indrelid IN (SELECT oid FROM heaps))
               SELECT pg_relation_filenode(oid) node FROM all_rels ORDER BY node""",
                (TABLES,),
            )
        ]
        oid = c.execute("SELECT oid FROM pg_database WHERE datname=current_database()").fetchone()[
            "oid"
        ]
        env = c.execute("""SELECT version() AS postgres, current_setting('io_workers') workers,
              current_setting('io_method') io_method,current_setting('effective_io_concurrency') cluster_io,
              current_setting('shared_buffers') shared_buffers,current_setting('work_mem') work_mem,
              current_setting('data_checksums') checksums,current_setting('fsync') fsync,
              (SELECT count(*) FROM aggregations) aggregations,(SELECT count(*) FROM records) records,
              (SELECT count(*) FROM digital_component_search_chunks) chunks""").fetchone()
        assert (env["aggregations"], env["records"], env["chunks"]) == (51003, 153009, 180630)
        assert storage["tables"]["digital_component_search_chunks"]["compression_counts"] == [
            {"compression": "lz4", "rows": 180630}
        ]
        c.commit()
        c.autocommit = True
        pre = cache_files(args.container, oid, nodes, "inspect")
        assert pre["resident"] > 0
        save(
            output / "environment.json",
            dict(
                server=env,
                storage=storage,
                warm_residency=pre,
                corpus_tables=TABLES,
                database=dbname,
                pairs=args.repeats,
                settle_seconds=args.settle_seconds,
            ),
        )
        print("Fixture and oracle verified; starting paired cold waves", flush=True)
        with ExitStack() as stack:
            clients = {}
            for setting in (0, 16):
                url_api = stack.enter_context(api(url, output / f"api-{setting}", setting))
                clients[setting] = []
                for n in range(4):
                    hc = stack.enter_context(httpx.Client(base_url=url_api, timeout=120))
                    login = hc.post(
                        "/api/v1/auth/login",
                        json={"email": f"cold{n+1}@performance.invalid", "password": PASSWORD},
                    )
                    login.raise_for_status()
                    hc.headers["X-CSRF-Token"] = hc.cookies["erms_csrf"]
                    clients[setting].append(hc)
            time.sleep(args.settle_seconds)
            pool = stack.enter_context(ThreadPoolExecutor(max_workers=4))
            stack.enter_context(sample_waits_and_io(output, url))
            waves = []
            for pair in range(args.repeats):
                for level in ((2, 4) if pair % 2 == 0 else (4, 2)):
                    cases = [TARGETS[(pair + i) % 3] for i in range(level)]
                    order = (16, 0) if (pair + (level == 4)) % 2 == 0 else (0, 16)
                    for setting in order:
                        cold = reset_cache(c, args.container, oid, nodes)
                        before = cgroup_reads(c)
                        rows, elapsed = execute_wave(
                            pool, clients[setting], cases, ids, expected, c
                        )
                        waves.append(
                            dict(
                                pair=pair + 1,
                                readers=level,
                                setting=setting,
                                cache=cold,
                                seconds=elapsed,
                                samples=rows,
                                linux_read_bytes=cgroup_reads(c) - before,
                            )
                        )
                        save(output / "waves.json", waves)
                        print(
                            f"Pair {pair+1}: {level} users, setting {setting}, {elapsed:.3f}s,"
                            f" {level/elapsed:.3f} searches/s",
                            flush=True,
                        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=6)
    parser.add_argument("--settle-seconds", type=int, default=60)
    args = parser.parse_args()
    if not re.fullmatch(r"erms-search-perf-linux-[0-9a-f]{32}", args.container) or args.repeats < 1:
        parser.error("requires a private benchmark container and positive repetitions")
    args.output.mkdir(parents=True)
    admin = os.environ["DATABASE_URL"]
    os.environ.update(
        {
            k: v
            for k, v in dotenv_values(ROOT / ".env").items()
            if v is not None and k not in os.environ
        }
    )
    # Bind destructive cache actions to the cluster the Docker wrapper actually owns.
    identity = subprocess.check_output(
        [
            "docker",
            "exec",
            "--user",
            "postgres",
            args.container,
            "psql",
            "-XAt",
            "-d",
            "postgres",
            "-c",
            "SELECT system_identifier FROM pg_control_system()",
        ],
        text=True,
    ).strip()
    name = "erms_large_text_" + uuid4().hex

    def interrupted(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    with psycopg.connect(admin, autocommit=True) as root:
        system_id = root.execute("SELECT system_identifier FROM pg_control_system()").fetchone()[0]
        if str(system_id) != identity:
            raise ValueError("The database connection must point to the owned benchmark container")
        root.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            experiment(args, make_conninfo(admin, dbname=name), name)
        finally:
            root.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            save(args.output / "cleanup.json", {"database": name, "dropped": True})


if __name__ == "__main__":
    main()
