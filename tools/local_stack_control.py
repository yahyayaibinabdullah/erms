"""Manage the project-local stack; the shell launcher owns service cleanup."""
import argparse
import fcntl
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime/local-stack'
STATE = RUNTIME / 'state.json'


def identity(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'command='],
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def running(state):
    return bool(state and state.get('identity') and identity(state['pid']) == state['identity'])


def read_state():
    return json.loads(STATE.read_text()) if STATE.exists() else None


def save(state):
    temporary = RUNTIME / (uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(STATE)
    finally:
        temporary.unlink(missing_ok=True)


def log(message):
    with (RUNTIME / 'lifecycle.log').open('a') as output:
        output.write(time.strftime('%Y-%m-%dT%H:%M:%S%z ') + message + '\n')


def healthy(state):
    if not running(state) or state.get('phase') != 'ready':
        return False
    if not all(running(process) for process in state['processes'].values()):
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for url in [state['api_url'] + '/health', state['ui_url'] + '/']:
            with opener.open(url, timeout=2) as response:
                if response.status != 200:
                    return False
    except OSError:
        return False
    try:
        maildev = subprocess.run([str(ROOT / 'run-maildev.py'), 'status'],
                                 capture_output=True, timeout=10, check=False)
        if maildev.returncode:
            return False
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def report(state):
    print(f"Local stack: {state['phase']} (PID {state['pid']}).")
    if state.get('api_url'):
        print('API: ' + state['api_url'])
        print('Web UI: ' + state['ui_url'])
    for name, process in state.get('processes', {}).items():
        print(f"  {name}: {'running' if running(process) else 'stopped'} (PID {process['pid']})")
    print(f'Logs: {RUNTIME}/stack.log and lifecycle.log')
    try:
        maildev = json.loads((ROOT / '.runtime/maildev/state.json').read_text())
        port = maildev['web_port']
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid MailDev port')
        print(f'MailDev inbox: http://127.0.0.1:{port}/')
        print(f'MailDev MCP:   http://127.0.0.1:{port}/mcp')
    except (OSError, ValueError, KeyError, TypeError):
        print('MailDev endpoints unavailable; check ./run-maildev.py status')


def stop(state):
    if not running(state):
        print('Local stack is stopped (no owned live launcher).')
        return
    pid = state['pid']
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 45
    while running(state) and time.monotonic() < deadline:
        time.sleep(0.1)
    if running(state):
        raise RuntimeError('Local stack did not stop within 45 seconds; inspect stack.log. No unrelated process was killed.')
    log(f'Stopped launcher PID {pid}.')
    print('Local stack stopped; services that it reused are left running.')


def start():
    previous = read_state()
    if running(previous):
        report(previous)
        if not healthy(previous):
            raise RuntimeError('The existing stack is starting, stopping or unhealthy. Inspect logs or use restart.')
        print('Local stack is already healthy; reusing it.')
        return
    # The shell takes the existing process-lifetime stack lock. If a foreground
    # startup is racing this call, the losing launcher exits without ownership.
    log_path = RUNTIME / 'stack.log'
    offset = log_path.stat().st_size if log_path.exists() else 0
    with log_path.open('a') as output:
        process = subprocess.Popen(['bash', str(ROOT / 'run-local-stack.sh'), '__managed'],
                                   cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + 240
    next_update = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                with log_path.open() as output:
                    output.seek(offset)
                    lines = [re.sub(r'^\[\d{4}-\d{2}-\d{2}T[^\]]+\] ', '', line)
                             for line in output.read().splitlines()]
                reasons = [line for line in lines if line.startswith(('Local stack preflight:', 'Last API probe:', 'Last Web UI probe:'))]
                detail = (' ' + ' '.join(reasons)) if reasons else ''
                raise RuntimeError('Local stack exited during startup.' + detail + ' See .runtime/local-stack/stack.log.')
            state = read_state()
            if state and state['pid'] == process.pid and healthy(state):
                log(f'Started launcher PID {process.pid}.')
                report(state)
                return
            if time.monotonic() >= next_update:
                print('Waiting for local services; progress is in .runtime/local-stack/stack.log.', flush=True)
                next_update = time.monotonic() + 10
            time.sleep(0.2)
        raise RuntimeError('Local stack did not become ready within 240 seconds; inspect stack.log.')
    except BaseException:
        # Popen.poll prevents signalling a reused PID. The shell performs its
        # normal cleanup; never kill a process group containing reused services.
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                log(f'Launcher PID {process.pid} did not finish startup-failure cleanup.')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    for mode in ['up', 'down', 'status', 'restart']:
        sub.add_parser(mode)
    register = sub.add_parser('_register', help=argparse.SUPPRESS)
    register.add_argument('pid', type=int)
    ready = sub.add_parser('_ready', help=argparse.SUPPRESS)
    ready.add_argument('pid', type=int)
    ready.add_argument('--api-url', required=True)
    ready.add_argument('--ui-url', required=True)
    ready.add_argument('--process', action='append', default=[])
    stopped = sub.add_parser('_stopped', help=argparse.SUPPRESS)
    stopped.add_argument('pid', type=int)
    args = parser.parse_args()
    os.umask(0o077)
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUNTIME.chmod(0o700)
    # Shell hooks already hold the process-lifetime lock. Do not acquire the
    # control lock: `up` holds it while awaiting their readiness notification.
    if args.mode == '_register':
        owner = identity(args.pid)
        if not owner:
            raise RuntimeError('Cannot register missing launcher process.')
        save({'pid': args.pid, 'identity': owner, 'phase': 'starting', 'processes': {}})
        log(f'Registered launcher PID {args.pid}.')
        return 0
    if args.mode in {'_ready', '_stopped'}:
        state = read_state()
        if not state or state['pid'] != args.pid or not running(state):
            raise RuntimeError('Launcher ownership changed; refusing state update.')
        if args.mode == '_ready':
            processes = {}
            for item in args.process:
                name, pid = item.split('=', 1)
                if pid:
                    processes[name] = {'pid': int(pid), 'identity': identity(int(pid))}
            state.update(phase='ready', api_url=args.api_url.rstrip('/'),
                         ui_url=args.ui_url.rstrip('/'), processes=processes)
        else:
            state['phase'] = 'stopped'
        save(state)
        return 0
    if args.mode == 'status':
        # Atomic state replacement allows status during a long-running up or
        # restart; it must not wait behind the mutating command's control lock.
        state = read_state()
        if not running(state):
            print('Local stack is stopped (no owned live launcher).')
            print(f'Logs: {RUNTIME}/stack.log and lifecycle.log')
            return 1
        report(state)
        ok = healthy(state)
        print('Health: ' + ('ready' if ok else 'starting or unhealthy'))
        return 0 if ok else 1
    with (RUNTIME / 'control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_state()
        if args.mode in {'down', 'restart'}:
            stop(state)
        if args.mode in {'up', 'restart'}:
            start()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        if RUNTIME.exists():
            log(f'ERROR: {error}')
        print('Error: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
