"""Optional concurrent SQL/memory diagnostic after the timed HTTP search gate.

Uses only the gate's owned disposable database and captured synthetic query.
RSS includes shared pages: report each backend, never sum it as private memory.
These SQL durations are separate from the single-client HTTP latency gate.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import subprocess
import threading
import time

import psycopg
from psycopg.rows import dict_row

from backend.services.api.search_execution import search_sql_execution


def probe(output, url):
    packets = [json.loads(p.read_text()) for p in output.glob('ranking-query-*.json')]
    packet, = [p for p in packets if p['query'] == 'universal -"boundaryalpha boundarybeta"'
               and p['sources'] == 'components']
    results, expected = [], None
    for memory in ('4MB', '12MB', '4MB', '12MB'):
        barrier = threading.Barrier(3)
        pids, peak_rss = [], {}

        def run():
            with psycopg.connect(url, row_factory=dict_row) as c:
                user = c.execute("SELECT id FROM users WHERE email='reader@performance.invalid'").fetchone()['id']
                c.execute("SELECT set_config('app.user_id',%s,true)", (str(user),))
                c.execute("SET LOCAL statement_timeout='30s'")
                pid = c.execute('SELECT pg_backend_pid() pid').fetchone()['pid']
                with search_sql_execution(c):
                    # Explicitly compare the old allowance with the proposed
                    # allowance, preserving the same JIT policy and SQL in both.
                    c.execute("SELECT set_config('work_mem',%s,true)", (memory,))
                    pids.append(pid)
                    barrier.wait(timeout=15)
                    started = time.perf_counter()
                    rows = c.execute(packet['sql'], packet['parameters'], prepare=False).fetchall()
                    elapsed = time.perf_counter() - started
                    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
                    return {'pid': pid, 'seconds': elapsed, 'rows': len(rows), 'rows_sha256': digest}

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run) for _ in range(2)]
            barrier.wait(timeout=20)
            while not all(future.done() for future in futures):
                observation = subprocess.run(['ps', '-p', ','.join(map(str, pids)), '-o', 'pid=,rss='],
                                             capture_output=True, text=True)
                for line in observation.stdout.splitlines():
                    pid, rss = map(int, line.split())
                    peak_rss[pid] = max(peak_rss.get(pid, 0), rss)
                time.sleep(.1)
            rows = [future.result() for future in futures]
        for row in rows:
            expected = expected or row['rows_sha256']
            assert row['rows_sha256'] == expected, 'Concurrent memory probe changed results'
            row['peak_backend_rss_kib'] = peak_rss.get(row['pid'])
        results.append({'work_mem': memory, 'concurrent_queries': 2, 'queries': rows})
    (output / 'concurrent-memory.json').write_text(json.dumps({
        'scope': 'Concurrent raw ranking SQL, after HTTP/oracle/plan work; not HTTP response timings',
        'memory_measure': 'Peak per-backend RSS includes shared pages and must not be summed as private memory',
        'results': results}, indent=2) + '\n')
