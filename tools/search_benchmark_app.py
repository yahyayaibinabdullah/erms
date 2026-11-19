"""API factory used only by the disposable benchmark's explicit CLI command."""
from functools import partial, wraps
from contextlib import asynccontextmanager
import argparse
import hashlib
import json
from pathlib import Path
import time


def create_app(output=None, *, capture_plans=False, ranking_io_concurrency=None):
    from backend.services.api import search
    from backend.services.api.search_execution import global_ranking_io
    from backend.services.api.main import app
    if ranking_io_concurrency is not None:
        # Only this standalone benchmark process overrides the production value.
        search.global_ranking_io = partial(global_ranking_io, concurrency=ranking_io_concurrency)
    recorded, stages = {}, []
    actual_plans = []

    def flush():
        # File writes (and host filesystem scanners) must not add latency to
        # the timed request. The harness shuts down this synthetic-only API
        # after all HTTP samples, then reads its buffered diagnostics.
        if output is not None:
            for digest, packet in recorded.items():
                (output / f'ranking-query-{digest}.json').write_text(json.dumps(packet, indent=2) + '\n')
            (output / 'stages.json').write_text(json.dumps(stages, indent=2) + '\n')
            if capture_plans:
                (output / 'actual-ranking-plans.json').write_text(json.dumps(actual_plans) + '\n')

    lifecycle = app.router.lifespan_context

    @asynccontextmanager
    async def benchmark_lifespan(application):
        try:
            async with lifecycle(application) as state:
                yield state
        finally:
            # Uvicorn may re-raise SIGTERM after graceful shutdown, bypassing
            # atexit handlers. Flush inside its completed lifespan instead.
            flush()

    app.router.lifespan_context = benchmark_lifespan

    class ProbeConnection:
        """Capture the actual full ranking statement, including page projection.

        EXPLAINing just an inner branch can choose a different plan from the
        API's complete statement. Capture only the ranking SELECT in this
        synthetic-only CLI; never intercept authentication or log credentials.
        """
        def __init__(self, connection, packets):
            self.connection, self.packets = connection, packets

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def execute(self, statement, parameters=None, **kwargs):
            rendered = statement if isinstance(statement, str) else statement.as_string(self.connection)
            if 'WITH ranked AS MATERIALIZED' in rendered:
                self.packets.append({'sql': rendered, 'parameters': parameters})
                execute = self.execute_with_plan if capture_plans else self.connection.execute
                return execute(statement, parameters, **kwargs)
            return self.connection.execute(statement, parameters, **kwargs)

        def execute_with_plan(self, statement, parameters, **kwargs):
            # Receive auto_explain's report from this execution via libpq. Do
            # not instrument login, other API routes, page details or oracles.
            c = self.connection
            c.execute("LOAD 'auto_explain'")
            c.execute("""SET LOCAL auto_explain.log_level = notice;
                         SET LOCAL client_min_messages = notice;
                         SET LOCAL auto_explain.log_format = json;
                         SET LOCAL auto_explain.log_analyze = on;
                         SET LOCAL auto_explain.log_buffers = on;
                         SET LOCAL auto_explain.log_timing = off;
                         SET LOCAL auto_explain.log_parameter_max_length = 0;
                         SET LOCAL track_io_timing = on""")
            reports = []
            def notice(diagnostic):
                msg = diagnostic.message_primary or ''
                if 'plan:\n' in msg:
                    reports.append(msg)
            c.add_notice_handler(notice)
            try:
                c.execute("SET LOCAL auto_explain.log_min_duration = 0")
                started = time.time()
                result = c.execute(statement, parameters, **kwargs)
                finished = time.time()
                c.execute("SET LOCAL auto_explain.log_min_duration = -1")
            finally:
                c.remove_notice_handler(notice)
            message, = reports
            header, body = message.split('plan:\n', 1)
            actual_plans.append({'started_at': started, 'finished_at': finished,
                                 'pid': c.info.backend_pid, 'duration': header.strip(),
                                 'explain': json.loads(body)})
            return result

    def timed(name):
        original = getattr(search, name)
        @wraps(original)
        def operation(*args, **kwargs):
            start = time.perf_counter()
            packets = []
            branches = args[1] if name == '_rank_global_search' else None
            if branches is not None and output is not None:
                args = (ProbeConnection(args[0], packets), *args[1:])
            try:
                return original(*args, **kwargs)
            finally:
                for packet in packets:
                    leaf = branches['record'][1].full_text
                    # The API canonicalizes omitted sources to both sources.
                    # Distinguish that from an explicitly file-only request.
                    packet.update(query=leaf.query, sources=leaf.sources[0]
                                  if leaf.sources and len(leaf.sources) == 1 else None)
                    digest = hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()
                    recorded.setdefault(digest, packet)
                stages.append({
                    'operation': name, 'seconds': time.perf_counter() - start,
                    'finished_at': time.time()})
        return operation

    for name in ('_rank_global_search', '_save_global_search', '_read_global_search',
                 '_global_search_page', 'page_details'):
        setattr(search, name, timed(name))
    return app


if __name__ == '__main__':
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--capture-ranking-plans', action='store_true')
    parser.add_argument('--ranking-io-concurrency', type=int, choices=range(0, 1001), metavar='N')
    args = parser.parse_args()
    uvicorn.run(create_app(args.output, capture_plans=args.capture_ranking_plans,
                           ranking_io_concurrency=args.ranking_io_concurrency),
                host='127.0.0.1', port=args.port, access_log=False)
