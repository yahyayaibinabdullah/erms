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
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]


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
