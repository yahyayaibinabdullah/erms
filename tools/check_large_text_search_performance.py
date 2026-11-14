"""Large-text SQL correctness/latency gate; owns and drops one disposable DB.

Uses the same corpus as the single-/multi-chunk comparison, retaining current
matching. Timers include real HTTP, auth, permissions, ranking, cache and page
evidence. Oracle calculation and EXPLAIN are outside the request timers.
"""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import random
import signal
import socket
import subprocess
import sys
import time
import traceback
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.initialize_database import initialize
from tools.search_large_text_fixture import (
    AGGREGATIONS, RECORDS, PASSWORD, CASES, fixture, distribution, oracle, payload, expected_ids,
)


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + '\n')


from tools.search_benchmark_support import HostMonitor


def exercise(output, url, repeats, settle_seconds):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = None
    samples, failures, expected, observations = [], [], {}, []
    env = {**os.environ, 'DATABASE_URL': url, 'AUTH_COOKIE_SECURE': 'false', 'PYTHONPATH': str(ROOT)}
    try:
        with (output / 'api.log').open('w') as log:
            server = subprocess.Popen([sys.executable, str(ROOT / 'tools/search_benchmark_app.py'),
                                       '--port', str(port), '--output', str(output)],
                                      cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=120) as client, \
                psycopg.connect(url, row_factory=dict_row, autocommit=True) as c:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError('API startup failed; see api.log')
                try:
                    if client.get('/health').status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                time.sleep(.25)
            else:
                raise RuntimeError('API startup timeout')

            def login(identity):
                client.cookies.clear()
                client.headers.pop('X-CSRF-Token', None)
                response = client.post('/api/v1/auth/login', json={
                    'email': identity + '@performance.invalid', 'password': PASSWORD})
                assert response.status_code == 200, response.text
                client.headers['X-CSRF-Token'] = client.cookies['erms_csrf']

            time.sleep(settle_seconds)
            # Authenticate after the deliberate idle interval. Host suspension
            # can extend it beyond the application's real login idle timeout;
            # do not weaken that timeout or time a rejected expired session.
            login('reader')
            sets = json.loads((output / 'fixture-sets.json').read_text())
            # The first broad request precedes all search/oracle/plan work.
            # Each round submits a fresh list and then follows every page.
            for repeat in range(repeats):
                cases = list(CASES)
                if repeat:
                    random.Random(91000 + repeat).shuffle(cases)
                for case in cases:
                    request, page = payload(case), 0
                    observed = {'case': case[0], 'repeat': repeat, 'hits': []}
                    observations.append(observed)
                    while True:
                        page += 1
                        assert page <= 10, (case[0], 'Pagination exceeded the 1,000-result cap')
                        start, wall_start = time.perf_counter(), time.time()
                        response = client.post('/api/v1/full-text-search', json=request)
                        elapsed = time.perf_counter() - start
                        row = {'identity': 'reader', 'case': case[0], 'repeat': repeat,
                               'page': page, 'seconds': elapsed, 'start_time': wall_start}
                        samples.append(row)
                        if elapsed > 3:
                            failures.append(row)
                        assert response.status_code == 200, response.text[:2000]
                        body = response.json()
                        actual = [{'type': i['type'], 'id': i[i['type']]['id'], 'score': i['score']} for i in body['items']]
                        observed['hits'].extend(actual)
                        if page == 1:
                            search_id = body['search_id']
                            cached = c.execute('SELECT hits FROM search_results_cache WHERE search_id=%s', (search_id,)).fetchone()['hits']
                            observed.update(cache=cached, total=sum(body['totals'].values()),
                                            truncated=body['truncated'])
                        else:
                            assert body['search_id'] == search_id, 'Unexpected cache rebuild'
                        if not body['next_cursor']:
                            break
                        request = {**request, 'cursor': body['next_cursor'], 'include_totals': False}
                    print(f'Round {repeat+1} {case[0]}: first {samples[-page]["seconds"]:.3f}s, '
                          f'max page {max(r["seconds"] for r in samples[-page:]):.3f}s', flush=True)

            login('denied')
            for case in CASES:
                start = time.perf_counter()
                response = client.post('/api/v1/full-text-search', json=payload(case))
                elapsed = time.perf_counter() - start
                row = {'identity': 'denied', 'case': case[0], 'repeat': 0, 'page': 1, 'seconds': elapsed}
                samples.append(row)
                if elapsed > 3:
                    failures.append(row)
                assert response.status_code == 200 and not response.json()['items'], (case[0], response.text[:1000])
            # Validation SQL and artifact writes start only after ALL HTTP
            # timers. They must not warm later searches or start host file
            # scanners between a first page and Next.
            for case in CASES:
                expected[case[0]] = oracle(c, case, sets)
                dump(output / (case[0] + '-expected.json'), expected[case[0]])
            for observed in observations:
                exp = expected[observed['case']]
                assert observed['hits'] == exp['hits'], (observed['case'], 'Page ranking differs')
                assert observed['cache'] == exp['hits'], (observed['case'], 'Full cache differs')
                assert observed['total'] == min(1000, exp['count'])
                assert observed['truncated'] == (exp['count'] > 1000)

        # The server buffers diagnostics in memory during requests. Normal
        # shutdown flushes them after all timers, avoiding measurement-induced
        # filesystem/antivirus activity on the request path.
        server.terminate()
        server.wait(15)
        assert server.returncode in (0, -signal.SIGTERM), 'Benchmark API shutdown failed'
        assert (output / 'stages.json').exists(), 'Benchmark API did not flush its diagnostics'
        server = None
        # Preserve real generated plans after timing, including loop counts.
        from backend.services.api import search
        from backend.services.api.search_execution import search_sql_execution
        captured = [json.loads(path.read_text()) for path in output.glob('ranking-query-*.json')]
        with psycopg.connect(url, row_factory=dict_row) as c:
            # Diagnostic I/O accounting starts only after all response timers.
            c.execute('SET LOCAL track_io_timing=on')
            user = c.execute("SELECT id FROM users WHERE email='reader@performance.invalid'").fetchone()['id']
            c.execute("SELECT set_config('app.user_id',%s,true)", (str(user),))
            membership_checks = []
            for case in CASES:
                packet, = [item for item in captured if item['query'] == case[1] and item['sources'] == case[2]]
                statement, arguments = packet['sql'], packet['parameters']
                with search_sql_execution(c):
                    plan = c.execute('EXPLAIN (ANALYZE,BUFFERS,VERBOSE,FORMAT JSON) ' + statement,
                                     arguments, prepare=False).fetchone()['QUERY PLAN']
                dump(output / (case[0] + '-plan.json'), plan)
                def nodes(node):
                    yield node
                    for child in node.get('Plans', []):
                        yield from nodes(child)
                scoring = [node for node in nodes(plan[0]['Plan'])
                           if node.get('Subplan Name') == 'CTE scored_component_chunks']
                for node in nodes(plan[0]['Plan']):
                    if node.get('Subplan Name') in ('CTE metadata_scores', 'CTE component_scores'):
                        assert node['Actual Loops'] <= 1, (case[0], node['Subplan Name'], 'Score batch rescanned')
                if case[2] != 'metadata':
                    assert len(scoring) == 1, (case[0], 'Missing score reuse boundary')
                    assert scoring[0]['Actual Loops'] <= 1, (case[0], 'Scoring batch rescanned')
                    found, arguments = search._indexed_text_ids(
                        'digital_component_search_chunks', 'digital_component_id', case[1],
                        ('pg_catalog.simple', 'pg_catalog.english', 'pg_catalog.arabic'))
                    statement = sql.SQL('''WITH search_query AS MATERIALIZED (
                        SELECT %s::text phrase,websearch_to_tsquery('english',%s) english,
                            websearch_to_tsquery('arabic',%s) arabic
                    ), other_search_queries AS MATERIALIZED (
                        SELECT config.oid::regconfig config,
                            websearch_to_tsquery(config.oid::regconfig,phrase) parsed
                        FROM pg_catalog.pg_ts_config config CROSS JOIN search_query
                        WHERE config.oid NOT IN ('simple'::regconfig,'english'::regconfig,'arabic'::regconfig)
                    ) SELECT DISTINCT id FROM ({}) found ORDER BY id''').format(found)
                    with search_sql_execution(c):
                        actual = [row['id'] for row in c.execute(statement, [case[1]]*3 + arguments)]
                    ids = expected_ids(case[0], sets)
                    if ids is None:
                        ids = list(range(1, RECORDS + 1))
                    assert actual == ids, (case[0], 'Uncapped membership differs')
                    membership_checks.append({'case': case[0], 'count': len(ids), 'equal': True,
                        'ids_sha256': hashlib.sha256(json.dumps(actual).encode()).hexdigest()})
                    dump(output / 'uncapped-membership.json', membership_checks)
        assert not failures, f'{len(failures)} responses exceeded 3 seconds; see {output}/results.json'
    finally:
        dump(output / 'results.json', {'samples': samples, 'failures': failures})
        dump(output / 'observed-rankings.json', observations)
        (output / 'samples.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in samples))
        if server is not None:
            server.terminate()
            try:
                server.wait(15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--settle-seconds', type=int, default=0)
    parser.add_argument('--probe-concurrency', action='store_true',
                        help='After the HTTP gate, compare two concurrent ranking queries at 4/12 MB')
    parser.add_argument('--vector-storage', choices=('current', 'uncompressed'), default='current',
                        help='Disposable-only storage comparison; application schema is unchanged')
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 1 or not 0 <= args.settle_seconds <= 300:
        parser.error('output must be new, repeats positive and settle-seconds in 0..300')
    output = args.output.resolve()
    output.mkdir(parents=True)
    config = {k: str(v) for k, v in {**dotenv_values(ROOT / '.env'), **os.environ}.items() if v is not None}
    admin = make_conninfo(config['DATABASE_URL'], dbname='postgres')
    name = 'erms_large_text_' + uuid4().hex
    url = make_conninfo(admin, dbname=name)
    created = False
    monitor = HostMonitor(output)
    monitor.thread.start()
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        created = True
        os.environ.update(config)
        os.environ['DATABASE_URL'] = url
        os.environ['AUTH_COOKIE_SECURE'] = 'false'
        with psycopg.connect(url, row_factory=dict_row) as c:
            initialize(c)
            from tools.search_storage_experiment import configure, inspect
            configure(c, args.vector_storage)
            sets = fixture(c)
            dump(output / 'fixture-sets.json', sets)
            environment = {'database': name, 'postgres': c.execute('SELECT version() v').fetchone()['v'],
                           'platform': platform.platform(), 'cpu_count': os.cpu_count(),
                           'aggregations': AGGREGATIONS, 'records': RECORDS, 'distribution': distribution(c),
                           'cap': 1000, 'page_size': 100, 'repeats': args.repeats,
                           'settle_seconds': args.settle_seconds,
                           'concurrency_probe': args.probe_concurrency,
                           'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (
                               ROOT / 'backend/services/api/search.py', ROOT / 'backend/services/api/search_page.py',
                               ROOT / 'backend/services/api/search_cache.py', ROOT / 'tools/search_benchmark_app.py',
                               ROOT / 'backend/services/api/search_execution.py',
                               ROOT / 'backend/services/api/search_projections.py',
                               ROOT / 'backend/services/api/dashboard_visibility.py',
                               ROOT / 'backend/services/api/authentication.py', ROOT / 'backend/services/api/main.py',
                               ROOT / 'database/baseline.sql', ROOT / 'database/migrations/112_search_vector_storage.sql',
                               ROOT / 'database/seeds/000_required_reference_data.sql', ROOT / 'tools/initialize_database.py',
                               ROOT / 'tools/search_memory_probe.py',
                               ROOT / 'tools/search_storage_experiment.py', ROOT / 'tools/search_benchmark_support.py',
                               ROOT / 'database/schema.sql', Path(__file__), ROOT / 'tools/search_large_text_fixture.py',
                               ROOT / 'tools/check_search_performance.py')}}
            for setting in ('jit', 'work_mem', 'shared_buffers', 'fsync', 'data_checksums', 'full_page_writes'):
                environment[setting] = c.execute('SHOW ' + setting).fetchone()[setting]
            from backend.services.api.search_execution import search_sql_execution
            with search_sql_execution(c):
                environment['search_execution'] = c.execute("SELECT current_setting('jit') AS jit,current_setting('work_mem') AS work_mem").fetchone()
            environment['jit_available'] = c.execute('SELECT pg_jit_available() v').fetchone()['v']
            environment['vector_storage'] = c.execute('''SELECT attstorage,attcompression
                FROM pg_attribute WHERE attrelid='digital_component_search_chunks'::regclass
                AND attname='search_vector' ''').fetchone()
            environment['chunk_table_bytes'] = c.execute("SELECT pg_table_size('digital_component_search_chunks') v").fetchone()['v']
            environment['chunk_table_options'] = c.execute("SELECT reloptions FROM pg_class WHERE oid='digital_component_search_chunks'::regclass").fetchone()['reloptions']
            environment['vector_compression_counts'] = c.execute('''SELECT
                pg_column_compression(search_vector) compression,count(*) chunks
                FROM digital_component_search_chunks GROUP BY 1 ORDER BY 1 NULLS FIRST''').fetchall()
            if args.vector_storage == 'current':
                assert environment['vector_storage'] == {'attstorage': 'm', 'attcompression': 'l'}
                assert environment['vector_compression_counts'] == [{'compression': 'lz4', 'chunks': 180630}]
            else:
                assert environment['vector_compression_counts'] == [{'compression': None, 'chunks': 180630}]
            environment['storage_experiment'] = inspect(c, args.vector_storage)
            environment['actual_counts'] = c.execute('''SELECT
                (SELECT count(*) FROM aggregations) aggregations,
                (SELECT count(*) FROM records) records,
                (SELECT count(*) FROM digital_component_search_chunks) chunks''').fetchone()
            assert environment['actual_counts'] == {'aggregations': AGGREGATIONS, 'records': RECORDS, 'chunks': 180630}
            dump(output / 'environment.json', environment)
        print('Large-text fixture ready: ' + name, flush=True)
        exercise(output, url, args.repeats, args.settle_seconds)
        if args.probe_concurrency:
            from tools.search_memory_probe import probe
            probe(output, url)
        changed = [name for name, digest in environment['source_sha256'].items()
                   if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
        assert not changed, f'Benchmark sources changed during the run: {changed}'
    except BaseException as error:
        dump(output / 'failure.json', {'type': type(error).__name__,
                                      'message': str(error), 'traceback': traceback.format_exc()})
        raise
    finally:
        try:
            if created:
                with psycopg.connect(admin, autocommit=True) as c:
                    c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                dump(output / 'cleanup.json', {'database': name, 'dropped': True})
                print('Dropped ' + name, flush=True)
        finally:
            monitor.close()


if __name__ == '__main__':
    main()
