"""Observe host load and buffer diagnostic files outside timed search work."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import psutil
import psycopg
from psycopg.rows import dict_row


@contextmanager
def sample_waits_and_io(output, url):
    """Sample the owned database and host disk totals without logging SQL text."""
    stop = threading.Event()
    samples = []

    def collect():
        with psycopg.connect(url, autocommit=True, row_factory=dict_row) as observer:
            while not stop.is_set():
                active = observer.execute("""
                    SELECT pid, wait_event_type, wait_event,
                           ltrim(query, E' \t\n\r') LIKE 'WITH ranked AS MATERIALIZED%' AS ranking
                    FROM pg_stat_activity
                    WHERE datname = current_database() AND pid <> pg_backend_pid()
                      AND backend_type = 'client backend' AND state = 'active'
                    ORDER BY pid
                """).fetchall()
                disk = psutil.disk_io_counters()
                samples.append({"time": time.time(), "active": active,
                                "host_read_bytes": disk.read_bytes, "host_write_bytes": disk.write_bytes})
                stop.wait(0.1)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(collect)
        try:
            yield
        finally:
            stop.set()
            future.result()
            (output / "waits-and-host-io.jsonl").write_text(
                "".join(json.dumps(sample) + "\n" for sample in samples))


class HostMonitor:
    """Observe contention without stopping or reconfiguring host security."""
    def __init__(self, output):
        self.output, self.stop = output, threading.Event()
        self.samples = []
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop.is_set():
            result = subprocess.run(['ps', '-axo', 'pid=,pcpu=,rss=,time=,comm='],
                                    capture_output=True, text=True)
            lines = [line.strip() for line in result.stdout.splitlines() if len(line.split()) >= 5]
            busiest = sorted(lines, key=lambda line: float(line.split()[1]), reverse=True)[:20]
            # A whitelist alone misses competing services such as mediaanalysisd.
            # Record executable names, not command arguments or environment data.
            rows = list(dict.fromkeys(busiest + [line for line in lines if any(
                name in line.lower() for name in ('defender', 'wdav', 'docker', 'virtualmachine', 'postgres', 'python'))]))
            memory = None
            if sys.platform == 'darwin':
                memory = subprocess.run(['vm_stat'], capture_output=True, text=True).stdout
            elif Path('/proc/meminfo').exists():
                memory = Path('/proc/meminfo').read_text()
            self.samples.append({'time': time.time(), 'load': os.getloadavg(),
                                 'processes': rows, 'memory': memory, 'error': result.stderr})
            self.stop.wait(1)

    def close(self):
        self.stop.set()
        self.thread.join(5)
        # Buffer observations during the run. Creating/updating files each
        # second can itself trigger host security scans and distort timings.
        (self.output / 'host-processes.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in self.samples))



class BufferedOutput:
    """The original gate writes only via (output / name).write_text(...).

    Retain those artifacts until its complete timed phase has ended. The
    original oracle/EXPLAIN sequence remains unchanged and is documented; this
    prevents diagnostic file creation from triggering scans between requests.
    Flush in finally so correctness and latency failures retain their evidence.
    """
    def __init__(self, directory):
        self.directory, self.pending = directory, {}

    def __str__(self):
        return str(self.directory)

    def __truediv__(self, name):
        parent = self
        class Artifact:
            def write_text(self, content):
                parent.pending[name] = content
                return len(content)
        return Artifact()

    def flush(self):
        for name, content in self.pending.items():
            (self.directory / name).write_text(content)
        self.pending.clear()
