"""No real database: prove cleanup paths before relying on the owning runner."""
import json
import sys

import pytest
from psycopg.conninfo import conninfo_to_dict

from tools import run_webui_integration as runner


@pytest.mark.parametrize('failure', ['seed', 'initialization', 'drop', 'preview_interrupt', 'fixed_preview_interrupt',
                                   'browser_fail', 'browser_timeout', 'browser_interrupt'])
def test_owned_database_cleanup_and_failures_are_reported(tmp_path, monkeypatch, failure):
    output = tmp_path / 'run'
    monkeypatch.setattr(sys, 'argv', ['runner', '--output', str(output)])
    preview = failure.endswith('preview_interrupt')
    browser = failure.startswith('browser_')
    if preview:
        sys.argv.append('--preview')
    if failure == 'fixed_preview_interrupt':
        sys.argv.append('--fixed-fixture')
    if browser:
        sys.argv.extend(['--browser', 'chrome'])
    monkeypatch.setattr(runner, 'dotenv_values', lambda _: {})
    monkeypatch.setenv('DATABASE_URL', 'postgresql://fixture@127.0.0.1/must_not_be_used')
    monkeypatch.setattr(runner.signal, 'signal', lambda *args: None)
    monkeypatch.setattr(runner.platform, 'platform', lambda: 'Test OS')
    monkeypatch.setattr(runner, 'free_port', lambda: 12346)
    monkeypatch.setattr(runner.subprocess, 'check_output', lambda *args, **kwargs: str(tmp_path))
    databases = []
    commands = []

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, command, *args, **kwargs):
            text = str(command)
            commands.append(text)
            if failure == 'drop' and 'DROP DATABASE' in text:
                raise RuntimeError('simulated cleanup failure')
            return self
        def fetchone(self): return None

    def connect(url, **kwargs):
        name = conninfo_to_dict(url)['dbname']
        assert name == 'postgres' or name.startswith('erms_webui_test_')
        databases.append(name)
        return Connection()

    class Listener:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, address): assert address == ('127.0.0.1', 0)
        def getsockname(self): return ('127.0.0.1', 12345)
        def fileno(self): return 123

    class FailedSeed:
        def wait(self, **kwargs): return 0 if preview or browser else 1
        def poll(self): return self.wait()

    class Service:
        stopped = False
        def poll(self): return 0 if self.stopped else None
        def terminate(self): self.stopped = True
        def wait(self, **kwargs): return 0

    class Browser(Service):
        def wait(self, **kwargs):
            if self.stopped:
                return 0
            if failure == 'browser_timeout':
                raise runner.subprocess.TimeoutExpired('browser', 900)
            if failure == 'browser_interrupt':
                raise KeyboardInterrupt
            return 1

    owned_services = []

    def start(command, **kwargs):
        if any('seed(dict(os.environ))' in part or 'seed(browser=True)' in part for part in command) or not (preview or browser):
            return FailedSeed()
        service = Browser() if 'tools/check_webui_browser.py' in command else Service()
        owned_services.append(service)
        return service

    def interrupt(_):
        raise KeyboardInterrupt

    def initialize(connection):
        if failure == 'initialization':
            raise RuntimeError('simulated schema failure')

    monkeypatch.setattr(runner.psycopg, 'connect', connect)
    monkeypatch.setattr(runner.socket, 'socket', Listener)
    monkeypatch.setattr(runner, 'initialize', initialize)
    monkeypatch.setattr(runner.subprocess, 'Popen', start)
    monkeypatch.setattr(runner, 'wait_ready', lambda *args: None)
    monkeypatch.setattr(runner.time, 'sleep', interrupt)
    if preview:
        assert runner.main() == 0
    elif failure == 'browser_fail':
        assert runner.main() == 1
    elif failure == 'browser_interrupt':
        assert runner.main() == 130
    elif failure == 'browser_timeout':
        with pytest.raises(runner.subprocess.TimeoutExpired):
            runner.main()
    else:
        with pytest.raises(RuntimeError):
            runner.main()
    assert any('CREATE DATABASE' in command for command in commands)
    assert any('DROP DATABASE' in command for command in commands)
    assert len(set(name for name in databases if name != 'postgres')) == 1
    evidence = json.loads((output / 'lifecycle.json').read_text())
    assert evidence['database_dropped'] is (failure != 'drop')
    assert evidence['ready'] is (preview or browser)
    assert all(service.stopped for service in owned_services)
    if failure == 'fixed_preview_interrupt':
        assert evidence['fixture'] == 'fixed-v1'


@pytest.mark.parametrize('entry_point', ['seed', 'prepare_browser_languages_and_settings'])
def test_fixture_rejects_a_persistent_database_before_connecting(monkeypatch, entry_point):
    from tools import seed_webui_regression as fixture
    monkeypatch.setenv('DATABASE_URL', 'postgresql://fixture@127.0.0.1/persistent_database')
    def forbidden(*args, **kwargs):
        pytest.fail('A rejected fixture must not attempt a connection')
    monkeypatch.setattr(fixture.psycopg, 'connect', forbidden)
    with pytest.raises(RuntimeError, match='disposable WebUI runner'):
        getattr(fixture, entry_point)()
