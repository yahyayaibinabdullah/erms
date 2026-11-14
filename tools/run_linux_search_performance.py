"""Run the search gate on disposable Linux PostgreSQL; leave no container/volume."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
from uuid import uuid4

import psycopg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='An existing local PostgreSQL 18 image/tag or digest; never pulled')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--settle-seconds', type=int, default=0)
    parser.add_argument('--workload', choices=('standard', 'large-text'), default='standard')
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 1 or not 0 <= args.settle_seconds <= 300:
        parser.error('output must be new, repeats positive, and settle-seconds between 0 and 300')
    root = Path(__file__).resolve().parents[1]
    name = 'erms-search-perf-linux-' + uuid4().hex
    password = secrets.token_urlsafe(24)
    created, child = False, None
    evidence = {'container': name, 'image': args.image, 'container_removed': False}
    report = args.output.with_name(args.output.name + '-linux.json')
    report.parent.mkdir(parents=True, exist_ok=True)

    def docker(*arguments, check=True):
        return subprocess.run(['docker', *arguments], check=check, text=True, capture_output=True, timeout=60)

    def interrupted(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        image = json.loads(docker('image', 'inspect', args.image).stdout)[0]
        evidence['image_id'] = image['Id']
        # The image declares a VOLUME at /var/lib/postgresql. Mask that UNUSED
        # path to prevent Docker creating an anonymous volume. Actual PGDATA,
        # including WAL and query spill, lives on the Linux container's writable
        # disk layer at /tmp/search-gate-pgdata, NOT on tmpfs. Do not disable
        # checksums, WAL or fsync to improve this benchmark.
        # Pass the temporary password in the child environment, not arguments
        # or evidence logs. It has no relationship to any persistent database.
        environment = {**os.environ, 'POSTGRES_PASSWORD': password}
        # A failed `docker run` may still have created its uniquely named
        # container, so inspect/remove it in finally even if startup fails.
        created = True
        subprocess.run(['docker', 'run', '--detach', '--pull=never', '--name', name,
                        '--publish', '127.0.0.1::5432',
                        '--tmpfs', '/var/lib/postgresql:rw,size=1m',
                        '--env', 'PGDATA=/tmp/search-gate-pgdata',
                        '--env', 'POSTGRES_INITDB_ARGS=--data-checksums',
                        '--env', 'POSTGRES_PASSWORD', image['Id']],
                       env=environment, check=True, capture_output=True, text=True, timeout=60)
        # Docker Desktop can return from run before the ephemeral host binding
        # appears in inspect. Wait for the binding as part of startup readiness.
        deadline = time.monotonic() + 60
        while True:
            container = json.loads(docker('inspect', name).stdout)[0]
            assert not any(m['Type'] == 'volume' for m in container['Mounts']), 'Unexpected Docker volume'
            bindings = container['NetworkSettings']['Ports'].get('5432/tcp') or []
            if bindings:
                port = bindings[0]['HostPort']
                break
            if not container['State']['Running'] or time.monotonic() >= deadline:
                raise RuntimeError('Disposable PostgreSQL port did not become ready: ' + docker('logs', name).stderr)
            time.sleep(0.25)
        url = f'postgresql://postgres:{password}@127.0.0.1:{port}/postgres'
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(url, connect_timeout=2) as connection:
                    evidence['postgres'] = connection.execute('SELECT version()').fetchone()[0]
                    for setting in ('data_directory', 'data_checksums', 'fsync', 'full_page_writes'):
                        evidence[setting] = connection.execute('SHOW ' + setting).fetchone()[0]
                    assert all(evidence[k] == 'on' for k in ('data_checksums', 'fsync', 'full_page_writes'))
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Disposable Linux PostgreSQL did not become ready') from None
                time.sleep(0.25)
        print('Disposable Linux PostgreSQL ready: ' + name, flush=True)
        gate = 'check_large_text_search_performance.py' if args.workload == 'large-text' else 'check_search_performance.py'
        evidence['workload'] = args.workload
        child = subprocess.Popen([sys.executable, str(root / 'tools' / gate),
                                  '--repeats', str(args.repeats), '--output', str(args.output),
                                  '--settle-seconds', str(args.settle_seconds)],
                                 cwd=root, env={**os.environ, 'DATABASE_URL': url})
        evidence['test_exit_code'] = child.wait()
        return evidence['test_exit_code']
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)
        try:
            if created:
                inspected = docker('inspect', name, check=False)
                if inspected.returncode == 0:
                    docker('rm', '--force', '--volumes', name)
                elif 'No such' not in inspected.stderr:
                    raise RuntimeError('Could not verify disposable-container cleanup: ' + inspected.stderr)
                evidence['container_removed'] = True
                print('Removed disposable Linux container: ' + name, flush=True)
        finally:
            report.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    sys.exit(main())
