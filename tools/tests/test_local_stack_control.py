"""Exercise lifecycle transitions with a fake stack and a loopback HTTP server."""
import importlib.util
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_control():
    spec = importlib.util.spec_from_file_location('control', ROOT / 'tools/local_stack_control.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('parent_exits', [False, True])
def test_stubborn_reloader_tree_is_removed_but_untracked_service_survives(tmp_path, parent_exits):
    module = load_control()
    tree = tmp_path / 'tree.py'
    tree.write_text('''
import json, os, signal, socket, subprocess, sys, time
from pathlib import Path
kind, directory, parent_exits = sys.argv[1:]
path = Path(directory)
if kind == 'leaf':
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0)); listener.listen()
    child = None
    port = listener.getsockname()[1]
else:
    child = subprocess.Popen([sys.executable, __file__, 'child' if kind == 'root' else 'leaf', directory, parent_exits])
    port = None
if kind != 'root' or parent_exits == 'False':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
(path / (kind + '.json')).write_text(json.dumps({'pid': os.getpid(), 'port': port}))
while child is None or child.poll() is None:
    time.sleep(.05)
''')
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
    root = subprocess.Popen([sys.executable, str(tree), 'root', str(tmp_path), str(parent_exits)])
    captured = []
    try:
        deadline = time.monotonic() + 8
        while not (tmp_path / 'leaf.json').exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert (tmp_path / 'leaf.json').exists()
        records = [json.loads((tmp_path / (kind + '.json')).read_text()) for kind in ('root', 'child', 'leaf')]
        captured = module.owned_tree([{'pid': root.pid, 'identity': module.identity(root.pid)}])
        assert {p['pid'] for p in captured} == {r['pid'] for r in records}
        remembered = []
        module.terminate_owned(captured[:1], grace=.3, remember=remembered.extend)
        root.wait(timeout=5)
        assert not module.owned_tree(captured)
        assert any(p['pid'] == records[-1]['pid'] for p in remembered)
        assert unrelated.poll() is None  # Same process group; never group-kill.
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', records[-1]['port']))
    finally:
        module.signal_owned(reversed(captured), signal.SIGKILL)
        if root.poll() is None:
            root.kill()
        root.wait(timeout=5)
        unrelated.terminate(); unrelated.wait(timeout=5)


def test_forced_shutdown_rechecks_reused_pid(monkeypatch):
    module = load_control()
    original = {'pid': 123, 'identity': 'original'}
    snapshots = iter([[original], [original], []])
    monkeypatch.setattr(module, 'owned_tree', lambda _: next(snapshots))
    owners = iter(['original', 'replacement'])
    monkeypatch.setattr(module, 'identity', lambda _: next(owners))
    kill = Mock(); monkeypatch.setattr(module.os, 'kill', kill)
    module.terminate_owned([original], grace=0)
    kill.assert_called_once_with(123, signal.SIGTERM)


def test_start_refuses_surviving_recorded_children(monkeypatch):
    module = load_control()
    monkeypatch.setattr(module, 'read_state', lambda: {'pid': 1, 'identity': 'dead', 'shutdown_processes': [{'pid': 123, 'identity': 'child'}]})
    monkeypatch.setattr(module, 'running', lambda _: False)
    monkeypatch.setattr(module, 'owned_tree', lambda _: [{'pid': 123}])
    spawn = Mock(); monkeypatch.setattr(module.subprocess, 'Popen', spawn)
    with pytest.raises(RuntimeError, match='processes remain'):
        module.start()
    spawn.assert_not_called()


def test_restart_never_starts_after_failed_shutdown(tmp_path, monkeypatch):
    module = load_control()
    monkeypatch.setattr(module, 'RUNTIME', tmp_path)
    monkeypatch.setattr(module, 'read_state', lambda: None)
    monkeypatch.setattr(module, 'stop', Mock(side_effect=RuntimeError('owned processes remain')))
    start = Mock(); monkeypatch.setattr(module, 'start', start)
    monkeypatch.setattr(sys, 'argv', ['control', 'restart'])
    with pytest.raises(RuntimeError, match='owned processes remain'):
        module.main()
    start.assert_not_called()


@pytest.mark.parametrize('mode', ['down', 'restart'])
@pytest.mark.parametrize('launcher_dead', [False, True])
def test_commands_clean_survivors_before_restart(tmp_path, monkeypatch, capsys, mode, launcher_dead):
    module = load_control()
    launcher_file = tmp_path / 'launcher.py'
    worker_file = tmp_path / 'worker.pid'
    launcher_file.write_text('''
import os, signal, subprocess, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(120)'])
Path(sys.argv[1]).write_text(str(child.pid))
while child.poll() is None: time.sleep(.05)
''')
    launcher = subprocess.Popen([sys.executable, str(launcher_file), str(worker_file)])
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
    owned = []
    try:
        deadline = time.monotonic() + 5
        while not worker_file.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert worker_file.exists()
        child = int(worker_file.read_text())
        owned = [{'pid': child, 'identity': module.identity(child)}]
        state = {'pid': launcher.pid, 'identity': module.identity(launcher.pid),
                 'phase': 'ready', 'processes': {'api': owned[0]}}
        if launcher_dead:
            launcher.kill(); launcher.wait(timeout=5)
        monkeypatch.setattr(module, 'RUNTIME', tmp_path)
        monkeypatch.setattr(module, 'STATE', tmp_path / 'state.json')
        module.save(state)
        if launcher_dead:
            monkeypatch.setattr(sys, 'argv', ['control', 'status'])
            assert module.main() == 1
            assert 'owned processes remain' in capsys.readouterr().out
        original_stop = module.stop
        monkeypatch.setattr(module, 'stop', lambda s: original_stop(s, launcher_grace=.2, process_grace=.2))
        def replacement():
            assert not module.running(state)
            assert not module.owned_tree(owned)
        start = Mock(side_effect=replacement); monkeypatch.setattr(module, 'start', start)
        monkeypatch.setattr(sys, 'argv', ['control', mode])
        assert module.main() == 0
        assert start.call_count == int(mode == 'restart')
        assert module.read_state()['phase'] == 'stopped'
        assert not module.owned_tree(owned)
        assert unrelated.poll() is None
        launcher.wait(timeout=5)
    finally:
        module.signal_owned(owned, signal.SIGKILL)
        if launcher.poll() is None:
            launcher.kill()
        launcher.wait(timeout=5)
        unrelated.terminate(); unrelated.wait(timeout=5)


def test_foreground_registration_preserves_previous_survivor_records(tmp_path, monkeypatch):
    module = load_control()
    monkeypatch.setattr(module, 'RUNTIME', tmp_path)
    old = {'pid': 123, 'identity': 'previous launcher'}
    monkeypatch.setattr(module, 'read_state', lambda: old)
    monkeypatch.setattr(module, 'identity', lambda _: 'new launcher')
    monkeypatch.setattr(module, 'running', lambda _: False)
    monkeypatch.setattr(module, 'owned_tree', lambda _: [{'pid': 456, 'identity': 'surviving child'}])
    save = Mock(); monkeypatch.setattr(module, 'save', save)
    monkeypatch.setattr(sys, 'argv', ['control', '_register', str(os.getpid())])
    with pytest.raises(RuntimeError, match='earlier stack still owns live processes'):
        module.main()
    save.assert_not_called()


def test_reused_pid_is_not_signalled(monkeypatch):
    spec = importlib.util.spec_from_file_location('control', ROOT / 'tools/local_stack_control.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'identity', lambda pid: 'different process')
    kill = Mock()
    monkeypatch.setattr(module.os, 'kill', kill)
    module.stop({'pid': 123, 'identity': 'old process'})
    kill.assert_not_called()


def test_startup_reports_port_conflict_without_waiting_for_timeout(tmp_path):
    tools = tmp_path / 'tools'
    tools.mkdir()
    control = tools / 'local_stack_control.py'
    control.write_text((ROOT / 'tools/local_stack_control.py').read_text())
    (tmp_path / 'run-local-stack.sh').write_text(
        '#!/bin/bash\necho "[2026-10-20T12:34:56.123+04:00] Local stack preflight: API port 8000 is occupied" >&2\nexit 1\n')
    result = subprocess.run([sys.executable, str(control), 'up'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert 'API port 8000 is occupied' in result.stderr


def test_background_modes_and_logs(tmp_path):
    tools = tmp_path / 'tools'
    tools.mkdir()
    control = tools / 'local_stack_control.py'
    control.write_text((ROOT / 'tools/local_stack_control.py').read_text())
    maildev = tmp_path / 'run-maildev.py'
    maildev.write_text('#!/bin/sh\nexit 0\n')
    maildev.chmod(0o700)
    maildev_runtime = tmp_path / '.runtime/maildev'
    maildev_runtime.mkdir(parents=True)
    (maildev_runtime / 'state.json').write_text(json.dumps({'web_port': 11080}))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    fake = tmp_path / 'fake.py'
    fake.write_text('''
import http.server, signal, subprocess, sys
from pathlib import Path
root=Path(__file__).parent
subprocess.run([sys.executable,str(root/'tools/local_stack_control.py'),'_register',sys.argv[1]],check=True)
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
http.server.HTTPServer.allow_reuse_address=True
server=http.server.HTTPServer(('127.0.0.1',int(sys.argv[2])),Handler)
url='http://127.0.0.1:'+sys.argv[2]
subprocess.run([sys.executable,str(root/'tools/local_stack_control.py'),'_ready',sys.argv[1],
                '--api-url',url,'--ui-url',url,'--process','http='+str(__import__('os').getpid())],check=True)
print('fake stack is ready',flush=True)
server.serve_forever()
''')
    shell = tmp_path / 'run-local-stack.sh'
    shell.write_text(f'''#!/bin/bash
worker=''
cleanup() {{
    trap - EXIT INT TERM
    kill "$worker" 2>/dev/null || true
    wait "$worker" 2>/dev/null || true
    "{sys.executable}" "{control}" _stopped "$$"
    exit 0
}}
trap cleanup EXIT INT TERM
"{sys.executable}" "{fake}" "$$" {port} &
worker=$!
while true; do sleep 0.1; done
''')
    def run(mode, expected=0):
        result = subprocess.run([sys.executable, str(control), mode], capture_output=True,
                                text=True, timeout=30)
        assert result.returncode == expected, (result.stdout, result.stderr)
        return result
    statefile = tmp_path / '.runtime/local-stack/state.json'
    try:
        run('status', 1)
        started = run('up')
        assert 'MailDev inbox: http://127.0.0.1:11080/' in started.stdout
        assert 'MailDev MCP:   http://127.0.0.1:11080/mcp' in started.stdout
        first = json.loads(statefile.read_text())
        run('status')
        reused = run('up')
        assert 'http://127.0.0.1:11080/mcp' in reused.stdout
        assert json.loads(statefile.read_text())['pid'] == first['pid']
        restarted = run('restart')
        assert 'MailDev inbox: http://127.0.0.1:11080/' in restarted.stdout
        assert 'MailDev MCP:   http://127.0.0.1:11080/mcp' in restarted.stdout
        second = json.loads(statefile.read_text())
        assert second['pid'] != first['pid']
        with pytest.raises(ProcessLookupError):
            os.kill(first['processes']['http']['pid'], 0)
        run('down')
        run('down')
        run('status', 1)
        with pytest.raises(ProcessLookupError):
            os.kill(second['processes']['http']['pid'], 0)
        runtime = tmp_path / '.runtime/local-stack'
        with (runtime / 'control.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            status = subprocess.run([sys.executable, str(control), 'status'],
                                    capture_output=True, timeout=2)
            assert status.returncode == 1
        assert 'fake stack is ready' in (runtime / 'stack.log').read_text()
        assert 'Stopped launcher' in (runtime / 'lifecycle.log').read_text()
        assert runtime.stat().st_mode & 0o777 == 0o700
    finally:
        subprocess.run([sys.executable, str(control), 'down'], capture_output=True, timeout=50)
