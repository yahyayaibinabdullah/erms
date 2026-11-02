#!/usr/bin/env python3
"""Local-only MailDev 3 lifecycle helper (Python standard library + OpenSSL)."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import smtplib
import socket
import ssl
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / '.runtime' / 'maildev'
STATE = RUNTIME / 'state.json'
CERT = RUNTIME / 'localhost.pem'
KEY = RUNTIME / 'localhost.key'


def log(message):
    with (RUNTIME / 'lifecycle.log').open('a') as stream:
        stream.write(time.strftime('%Y-%m-%dT%H:%M:%S%z ') + message + '\n')


def identity(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'command='],
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def running(state):
    return bool(state and identity(state['pid']) == state['identity'])


def report(state):
    print(f"Mailbox: http://127.0.0.1:{state['web_port']}/")
    print(f"MCP:     http://127.0.0.1:{state['web_port']}/mcp")
    print(f"SMTP:    localhost:{state['smtp_port']} (implicit_tls; authentication disabled)")
    print(f"Trust:   {CERT}")
    print(f"Logs:    {RUNTIME}/maildev.log and lifecycle.log")


def health(state):
    context = ssl.create_default_context(cafile=str(CERT))
    with smtplib.SMTP_SSL('localhost', state['smtp_port'], timeout=2, context=context) as smtp:
        if smtp.noop()[0] != 250:
            raise RuntimeError('SMTP NOOP failed')
    # Bypass system HTTP proxies for these loopback-only probes.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = f"http://127.0.0.1:{state['web_port']}"
    with opener.open(urllib.request.Request(base + '/', headers={'Accept': 'text/html'}), timeout=2) as response:
        if response.status != 200:
            raise RuntimeError('Mailbox health check failed')
    request = urllib.request.Request(base + '/mcp', data=json.dumps({
        'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
        'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                   'clientInfo': {'name': 'erms-local-maildev', 'version': '1.0'}},
    }).encode(), headers={'Content-Type': 'application/json',
                         'Accept': 'application/json, text/event-stream'})
    with opener.open(request, timeout=2) as response:
        body = response.read().decode()
        if 'serverInfo' not in body or 'protocolVersion' not in body:
            raise RuntimeError('MCP initialization failed')


def certificates():
    if CERT.exists() != KEY.exists():
        raise RuntimeError(f'Incomplete certificate/key pair in {RUNTIME}; restore the missing file or remove both while stopped.')
    if not CERT.exists():
        openssl = shutil.which('openssl')
        if not openssl:
            raise RuntimeError('Install OpenSSL and put it on PATH.')
        # Temporary names ensure a failed generation never installs a partial pair.
        cert_tmp, key_tmp = RUNTIME / 'localhost.new.pem', RUNTIME / 'localhost.new.key'
        try:
            with (RUNTIME / 'maildev.log').open('a') as output:
                subprocess.run([openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                                '-days', '365', '-keyout', str(key_tmp), '-out', str(cert_tmp),
                                '-subj', '/CN=localhost', '-addext',
                                'subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1'],
                               check=True, stdout=output, stderr=output)
            key_tmp.chmod(0o600)
            key_tmp.replace(KEY)
            cert_tmp.replace(CERT)
            log('Generated local self-signed SMTP certificate (365 days).')
        finally:
            key_tmp.unlink(missing_ok=True)
            cert_tmp.unlink(missing_ok=True)
    KEY.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERT, KEY)
    check = subprocess.run(['openssl', 'x509', '-in', str(CERT), '-checkend', '0', '-noout'],
                           capture_output=True, check=False)
    if check.returncode:
        raise RuntimeError('Local SMTP certificate expired. While stopped, remove localhost.pem and localhost.key, then run up again and restart trusting clients.')


def stop(state, owner=None):
    if owner is not None and (not state or state.get('owner') != owner):
        print('MailDev was not started by this caller; leaving it unchanged.')
        return
    if not running(state):
        print('MailDev is stopped (no owned live process).')
        return
    pid = state['pid']
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        if not running(state):
            log(f'Stopped PID {pid}.')
            print('MailDev stopped.')
            return
        time.sleep(0.1)
    raise RuntimeError('MailDev did not stop within 10 seconds; inspect logs/process before retrying.')


def start(args, previous):
    if running(previous):
        health(previous)
        print(f"MailDev is already running (PID {previous['pid']}). Use restart to change options.")
        report(previous)
        return
    settings = {key: getattr(args, key) or (previous or {}).get(key) or default for key, default in
                [('smtp_port', 1025), ('web_port', 1080), ('node', 'node'), ('maildev', 'maildev')]}
    node = shutil.which(settings['node'])
    executable = shutil.which(settings['maildev'])
    if not node or not executable:
        raise RuntimeError('Install MailDev 3 (npm install -g maildev@3) and Node.js; use --node/--maildev for explicit executables.')
    command = [node, str(Path(executable).resolve())]
    env = {key: value for key, value in os.environ.items() if not key.startswith('MAILDEV_')}
    probe = subprocess.run(command + ['--help'], env=env, capture_output=True, text=True, timeout=15)
    if probe.returncode or '--mcp' not in probe.stdout or '--incoming-secure' not in probe.stdout:
        with (RUNTIME / 'maildev.log').open('a') as output:
            output.write(probe.stdout + probe.stderr)
        raise RuntimeError('MailDev could not start with this Node runtime, or lacks TLS/MCP flags. See maildev.log; select a compatible Node with --node PATH.')
    if settings['smtp_port'] == settings['web_port']:
        raise RuntimeError('SMTP and web ports must be different.')
    for port in [settings['smtp_port'], settings['web_port']]:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(('127.0.0.1', port))
            except OSError as error:
                raise RuntimeError(f'Port {port} is unavailable; stop its owner yourself or select another port. No existing process was stopped.') from error
    certificates()
    config = RUNTIME / 'config.json'
    config.write_text(json.dumps({
        'smtp': settings['smtp_port'], 'web': settings['web_port'],
        'ip': '127.0.0.1', 'webIp': '127.0.0.1', 'mcp': True,
        'incomingSecure': True, 'incomingCert': str(CERT), 'incomingKey': str(KEY),
        'mailDirectory': str(RUNTIME / 'mail'), 'maxEmails': 1000,
    }, indent=2) + '\n')
    with (RUNTIME / 'maildev.log').open('a') as output:
        process = subprocess.Popen(command + ['--config', str(config)], cwd=RUNTIME,
                                   env=env, stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    state = dict(settings, pid=process.pid, identity=identity(process.pid), owner=args.owner)
    if not state['identity']:
        process.wait(timeout=5)
        raise RuntimeError('MailDev exited during launch. See maildev.log.')
    STATE.write_text(json.dumps(state, indent=2) + '\n')
    try:
        for _ in range(50):
            if process.poll() is not None:
                raise RuntimeError('MailDev exited during startup. See maildev.log.')
            try:
                health(state)
                break
            except (OSError, RuntimeError, smtplib.SMTPException) as error:
                last_error = str(error)
                time.sleep(0.2)
        else:
            raise RuntimeError(f'MailDev did not become healthy: {last_error}. See maildev.log.')
    except BaseException:
        if running(state):
            process.terminate()
            process.wait(timeout=10)
        raise
    log(f'Started PID {process.pid}, SMTP {settings["smtp_port"]}, web/MCP {settings["web_port"]}.')
    print(f'MailDev started (PID {process.pid}).')
    report(state)


def port(value):
    number = int(value)
    if not 1024 <= number <= 65535:
        raise argparse.ArgumentTypeError('Use an unprivileged port between 1024 and 65535.')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['up', 'down', 'status', 'restart'])
    parser.add_argument('--smtp-port', type=port, help='Default: 1025; retained across restarts.')
    parser.add_argument('--web-port', type=port, help='Mailbox and MCP port; default: 1080.')
    parser.add_argument('--node', help='Node executable; default: node on PATH.')
    parser.add_argument('--maildev', help='MailDev executable; default: maildev on PATH.')
    parser.add_argument('--owner', help='Lifecycle owner token: up records it only for a new process; down stops only a matching owner.')
    args = parser.parse_args()
    os.umask(0o077)
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    RUNTIME.chmod(0o700)
    with (RUNTIME / 'control.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(STATE.read_text()) if STATE.exists() else None
        if args.mode == 'status':
            if not running(state):
                print('MailDev is stopped (no owned live process).')
                return 1
            health(state)
            print(f"MailDev is healthy (PID {state['pid']}).")
            report(state)
        elif args.mode == 'down':
            stop(state, args.owner)
        else:
            if args.mode == 'restart':
                stop(state, args.owner)
            start(args, state)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, smtplib.SMTPException) as error:
        if RUNTIME.exists():
            log(f'ERROR: {error}')
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
