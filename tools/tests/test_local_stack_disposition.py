"""Exercise the shell supervisor using fake services; never connect to a DB."""
import json
import os
from pathlib import Path
import signal
import re
import subprocess
import sys
import time

import pytest

MODULES = ['eligibility', 'communications', 'destruction_worker']
WORKERS = MODULES + ['content_cleanup', 'session_cleanup', 'text_indexing_maintenance']


def eventually(predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError('Local stack test timed out')


@pytest.fixture
def stack(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    source = Path(__file__).resolve().parents[2] / 'run-local-stack.sh'
    (project / source.name).write_text(source.read_text())
    (project / 'tools').mkdir()
    (project / 'tools/local_stack_log.py').write_text(
        (source.parent / 'tools/local_stack_log.py').read_text())
    (project / '.env').write_text('')
    maildev = project / 'run-maildev.py'
    maildev.write_text(f'#!{sys.executable}\n' + '''
import os, pathlib, sys
directory = pathlib.Path(os.environ['TEST_OUTPUT'])
owner_file = directory / 'maildev.owner'
owner = sys.argv[sys.argv.index('--owner') + 1]
if sys.argv[1] == 'up':
    if os.environ.get('TEST_MAILDEV_FAILURE') == '1': sys.exit(1)
    if not owner_file.exists(): owner_file.write_text(owner)
    (directory / 'maildev.started').touch()
elif sys.argv[1] == 'down' and owner_file.exists() and owner_file.read_text() == owner:
    (directory / 'maildev.stopped').touch()
''')
    maildev.chmod(0o700)
    binary = tmp_path / 'bin'
    binary.mkdir()
    for name, body in [('python3', f'if [ "$1" = -u ]; then shift; fi\ncase "$1" in */local_stack_log.py) exec "{sys.executable}" "$@";; esac\nexit 0'), ('curl', 'exit 0'),
                       ('psql', 'echo "${TEST_SCHEMA_READY:-t}"')]:
        file = binary / name
        file.write_text('#!/bin/sh\n' + body + '\n')
        file.chmod(0o700)
    python = project / 'backend/services/api/.venv/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text(f'#!{sys.executable}\n' + '''
import json, os, pathlib, sys, time
if '-m' not in sys.argv: sys.exit(0)
module = sys.argv[sys.argv.index('-m') + 1]
pathlib.Path(os.environ['TEST_OUTPUT'], module.rsplit('.', 1)[-1]+'.json').write_text(
    json.dumps({'pid': os.getpid(), 'args': sys.argv[1:],
                'database': os.environ.get('DATABASE_URL'),
                'trust': os.environ.get('SSL_CERT_FILE')}))
while True: time.sleep(1)
''')
    python.chmod(0o700)
    env = dict(os.environ, PATH=str(binary) + ':' + os.environ['PATH'],
               DATABASE_URL='postgresql://unused.invalid/disposable_fake',
               SSL_CERT_FILE='/fake/local-ca.pem', TEXT_INDEXER_ENABLED='false',
               CONTENT_INDEXING_MAINTENANCE_ENABLED='true', TEST_OUTPUT=str(tmp_path))
    # Skip only the lock wrapper in this isolated copied project. All launcher
    # startup, migration gating, worker supervision and cleanup run unchanged.
    def launch(ready='t', maildev_failure=False, maintenance=True):
        env['TEST_SCHEMA_READY'] = ready
        env['TEST_MAILDEV_FAILURE'] = '1' if maildev_failure else '0'
        env['CONTENT_INDEXING_MAINTENANCE_ENABLED'] = 'true' if maintenance else 'false'
        output = (tmp_path / 'output.log').open('w+')
        process = subprocess.Popen(['bash', '-c',
            'export ERMS_LOCAL_STACK_LOCK_PID=$$; exec bash "$1"',
            'test-stack', str(project / source.name)], env=env,
            stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        return process, output
    processes = []
    def start(ready='t', maildev_failure=False, maintenance=True):
        result = launch(ready, maildev_failure, maintenance)
        processes.append(result)
        return result
    yield start, tmp_path
    for process, output in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        output.close()


@pytest.mark.parametrize('failed_worker', [None, *WORKERS])
def test_workers_inherit_environment_and_stop_with_stack(stack, failed_worker):
    start, directory = stack
    process, output = start()
    eventually(lambda: all((directory / (name + '.json')).exists() for name in WORKERS))
    workers = [json.loads((directory / (name + '.json')).read_text()) for name in WORKERS]
    for worker in workers:
        assert worker['database'] == 'postgresql://unused.invalid/disposable_fake'
        assert worker['trust'] == '/fake/local-ca.pem'
        assert '--watch' in worker['args']
    if failed_worker:
        target = workers[WORKERS.index(failed_worker)]
        os.kill(target['pid'], signal.SIGTERM)
    else:
        process.send_signal(signal.SIGTERM)
    process.wait(timeout=10)
    assert (directory / 'maildev.started').exists()
    assert (directory / 'maildev.stopped').exists()
    if failed_worker:
        assert process.returncode == 1
        expected = {
            'content_cleanup': 'managed segmented-content cleanup worker stopped unexpectedly',
            'session_cleanup': 'managed login-session cleanup worker stopped unexpectedly',
            'text_indexing_maintenance': 'API-owned text-indexing maintenance worker stopped unexpectedly',
        }.get(failed_worker, 'managed disposition worker stopped unexpectedly')
        assert expected in (directory / 'output.log').read_text()
    for worker in workers:
        with pytest.raises(ProcessLookupError):
            os.kill(worker['pid'], 0)


def test_missing_migration_prevents_worker_start(stack):
    start, directory = stack
    process, output = start('f')
    assert process.wait(timeout=10) == 1
    assert 'migrations through 071' in (directory / 'output.log').read_text()
    assert not any((directory / (name + '.json')).exists() for name in WORKERS)
    assert not (directory / 'maildev.started').exists()


def test_reused_maildev_is_left_running(stack):
    start, directory = stack
    (directory / 'maildev.owner').write_text('separately-started')
    process, output = start()
    eventually(lambda: all((directory / (name + '.json')).exists() for name in WORKERS))
    process.send_signal(signal.SIGTERM)
    process.wait(timeout=10)
    assert (directory / 'maildev.started').exists()
    assert not (directory / 'maildev.stopped').exists()


def test_maildev_failure_prevents_worker_start(stack):
    start, directory = stack
    process, output = start(maildev_failure=True)
    assert process.wait(timeout=10) == 1
    assert not any((directory / (name + '.json')).exists() for name in WORKERS)


def test_background_worker_inventory_matches_packaged_services():
    root = Path(__file__).resolve().parents[2]
    modules = set()
    for unit in (root / 'backend/services/api/deploy').glob('*.service'):
        if unit.name == 'erms-api.service':
            continue
        match = re.search(r'ExecStart=.* -m ([\w.]+)', unit.read_text())
        assert match, unit
        modules.add(match[1].rsplit('.', 1)[-1])
    assert modules == set(WORKERS)


def test_explicit_maintenance_disable_preserves_other_workers(stack):
    start, directory = stack
    process, output = start(maintenance=False)
    expected = [name for name in WORKERS if name != 'text_indexing_maintenance']
    eventually(lambda: all((directory / (name + '.json')).exists() for name in expected))
    assert not (directory / 'text_indexing_maintenance.json').exists()
    process.send_signal(signal.SIGTERM)
    process.wait(timeout=10)
    assert (directory / 'maildev.stopped').exists()
    for name in expected:
        pid = json.loads((directory / (name + '.json')).read_text())['pid']
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
