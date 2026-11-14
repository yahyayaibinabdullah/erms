"""Safety and failure reporting for the DB-free WebUI test entry point."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools import run_webui_tests as runner


@pytest.mark.parametrize('outcome', ['pass', 'failure', 'skip', 'missing_xml', 'empty'])
def test_isolated_runner_reports_every_suite_and_rejects_incomplete_evidence(tmp_path, monkeypatch, outcome):
    output = tmp_path / 'evidence'
    monkeypatch.setattr(sys, 'argv', ['runner', '--repeat', '2', '--output', str(output)])
    monkeypatch.setenv('DATABASE_URL', 'must-not-be-inherited')
    monkeypatch.setenv('MESSAGING_LISTENER_DATABASE_URL', 'must-not-be-inherited')
    monkeypatch.setenv('PYTEST_ADDOPTS', '--ignore=frontend/webui/tests')
    calls = []

    def run(command, **kwargs):
        assert Path(kwargs['env']['NICEGUI_STORAGE_PATH']).parent.is_dir()
        calls.append((command, kwargs))
        xml = Path(next(a.removeprefix('--junitxml=') for a in command if a.startswith('--junitxml=')))
        if outcome != 'missing_xml':
            case = {'pass': '<testcase/>', 'failure': '<testcase><failure/></testcase>',
                    'skip': '<testcase><skipped/></testcase>', 'empty': ''}[outcome]
            xml.write_text(f'<testsuites><testsuite>{case}</testsuite></testsuites>')
        return subprocess.CompletedProcess(command, int(outcome == 'failure'))

    monkeypatch.setattr(runner.subprocess, 'run', run)
    assert runner.main() == int(outcome != 'pass')
    assert len(calls) == 4
    assert len({options['env']['NICEGUI_STORAGE_PATH'] for _, options in calls}) == 4
    for command, options in calls:
        env = options['env']
        assert env['DATABASE_URL'] == env['MESSAGING_LISTENER_DATABASE_URL'] == ''
        assert env['PYTHON_DOTENV_DISABLED'] == '1'
        assert env['WEBUI_API_URL'] == 'http://127.0.0.1:1'
        assert env['NICEGUI_REDIS_URL'] == ''
        assert 'PYTEST_ADDOPTS' not in env
        assert 'tools.webui_no_network' in command
        assert options['timeout'] == 600
    summary = json.loads((output / 'summary.json').read_text())
    assert summary['complete'] and len(summary['runs']) == 4


def test_runner_never_overwrites_previous_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['runner', '--output', str(tmp_path)])
    with pytest.raises(FileExistsError):
        runner.main()


def test_network_plugin_blocks_python_and_native_postgres_before_collection(tmp_path):
    # Separate process prevents this safety check from changing our test host.
    probe = tmp_path / 'test_probe.py'
    probe.write_text('''
import socket
import pytest
# These attempts happen during collection, before test fixtures can help.
with pytest.raises(RuntimeError, match="Network access is forbidden"):
    socket.socket().connect(("127.0.0.1", 1))
try:
    import psycopg
except ImportError:
    pass
else:
    for connect in (psycopg.connect, psycopg.Connection.connect, psycopg.AsyncConnection.connect):
        with pytest.raises(RuntimeError, match="Network access is forbidden"):
            connect("dbname=must_never_connect")
def test_collected_safely():
    assert True
''')
    result = subprocess.run([sys.executable, '-m', 'pytest', '-p', 'tools.webui_no_network',
                             str(probe), '-q', '-o', 'addopts='], cwd=runner.ROOT,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
