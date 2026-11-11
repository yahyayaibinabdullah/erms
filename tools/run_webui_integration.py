"""Own a fresh database and API/UI processes for assembled WebUI verification.

Use the API virtualenv. --preview keeps the disposable stack alive for browser
checks; Ctrl-C removes it. Otherwise run the assembled NiceGUI tests and clean up.
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from cryptography.fernet import Fernet
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.initialize_database import initialize


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def wait_ready(process, url):
    deadline = time.monotonic() + 90
    with httpx.Client(timeout=2, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Owned service exited before readiness; see its log')
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.2)
    raise RuntimeError(f'Test service did not become ready: {url}')


def interrupted(*_):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--fixed-fixture', action='store_true',
                        help='Use dated synthetic records, paged branches and published Arabic for browser baselines')
    parser.add_argument('--browser', choices=['chrome', 'edge', 'firefox', 'safari'])
    parser.add_argument('--browser-scope', choices=['full', 'navigation', 'keyboard', 'shell', 'session', 'relationships', 'audit', 'collections', 'classification', 'security', 'login-sessions', 'organization', 'text-indexers', 'account', 'translations', 'holds', 'components', 'aggregations', 'records', 'security-operations', 'governance-custody', 'global-search', 'advanced-search', 'dashboard', 'disposition', 'messaging', 'application', 'performance'], default='full',
                        help='Subset runs supplement, rather than replace, full browser acceptance')
    parser.add_argument('--maildev', action='store_true',
                        help='Verify local SMTP delivery through the repository-managed MailDev instance')
    parser.add_argument('--browser-python', default=str(ROOT / '.runtime/webui-browser-venv/bin/python'))
    parser.add_argument('--output', type=Path)
    local_python = ROOT / 'frontend/webui/.venv/bin/python'
    parser.add_argument('--webui-python', default=str(local_python if local_python.exists() else sys.executable))
    parser.add_argument('pytest_args', nargs='*')
    args = parser.parse_args()
    if args.browser and args.preview:
        parser.error('--browser owns a finite test run; do not combine with --preview')
    if args.browser:
        args.fixed_fixture = True
    output = (args.output or ROOT / '.runtime/webui-integration' / uuid4().hex).resolve()
    output.mkdir(parents=True, exist_ok=False)
    if args.browser:
        sources = list((ROOT / 'frontend/webui').glob('*.py')) + list((ROOT / 'frontend/webui/disposition').glob('*.py')) + [
            ROOT / 'frontend/webui/i18n/messages.en.json',
            ROOT / 'frontend/webui/i18n/messages.ar.generated.json',
            *[ROOT / 'tools' / filename for filename in (
                'run_webui_integration.py', 'check_webui_browser.py',
                'webui_browser_navigation.py', 'webui_browser_keyboard.py', 'webui_browser_shell.py', 'webui_browser_session.py', 'webui_browser_relationships.py', 'webui_browser_audit.py', 'webui_browser_collections.py', 'webui_browser_classification.py', 'webui_browser_security.py', 'webui_browser_login_sessions.py', 'webui_browser_organization.py', 'webui_browser_text_indexers.py', 'webui_browser_account.py', 'webui_browser_translations.py', 'webui_browser_holds.py', 'webui_browser_components.py', 'webui_browser_aggregations.py', 'webui_browser_records.py', 'webui_browser_security_operations.py', 'webui_browser_governance_custody.py', 'webui_browser_global_search.py', 'webui_browser_advanced_search.py', 'webui_browser_dashboard.py', 'webui_browser_disposition.py', 'webui_browser_messaging.py', 'webui_browser_application.py', 'webui_browser_performance.py', 'seed_webui_disposition.py', 'webui_browser_server.py',
                'seed_webui_regression.py', 'webui_test_events.py')],
        ]
        (output / 'source-environment.json').write_text(json.dumps({
            'started_utc': datetime.now(timezone.utc).isoformat(),
            'os': platform.platform(),
            'source_state': 'Local uncommitted working tree; hashes identify tested files',
            'sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in sorted(sources)},
        }, indent=2) + '\n')
    configuration = {**dotenv_values(ROOT / '.env'), **os.environ}
    name = 'erms_webui_test_' + uuid4().hex
    admin_url = make_conninfo(configuration['DATABASE_URL'], dbname='postgres')
    test_url = make_conninfo(configuration['DATABASE_URL'], dbname=name)
    created = False
    processes = []
    result = {'database': name, 'database_dropped': False, 'ready': False}
    signal.signal(signal.SIGTERM, interrupted)
    with ExitStack() as resources:
        storage = resources.enter_context(tempfile.TemporaryDirectory(prefix='erms-webui-test-'))
        # Reserve the API listener until uvicorn inherits it. A released-port
        # race must never direct test writes to an unrelated local service.
        api_socket = resources.enter_context(socket.socket())
        api_socket.bind(('127.0.0.1', 0))
        api_port = api_socket.getsockname()[1]
        api_url = f'http://127.0.0.1:{api_port}'
        ui_socket = None
        if args.preview or args.browser:
            ui_socket = resources.enter_context(socket.socket())
            ui_socket.bind(('127.0.0.1', 0))
            ui_port = ui_socket.getsockname()[1]
        else:
            ui_port = free_port()
        ui_url = f'http://127.0.0.1:{ui_port}'
        result.update(api_url=api_url, ui_url=ui_url)
        environment = {k: str(v) for k, v in configuration.items() if v is not None}
        environment.update(DATABASE_URL=test_url, MESSAGING_LISTENER_DATABASE_URL=test_url,
            AUTH_COOKIE_SECURE='false', APPLICATION_SETTINGS_ENCRYPTION_KEY=Fernet.generate_key().decode(),
            # The existing rich seed selects its records fixture by this label.
            DATABASE_DISPLAY_NAME='Phase 4 disposable preview', DATABASE_DISPLAY_NAME_AR='معاينة مؤقتة للاختبار',
            CONTENT_STORAGE_BACKEND='postgresql',
            WEBUI_API_URL=api_url, WEBUI_PORT=str(ui_port), WEBUI_HOST='127.0.0.1', WEBUI_RELOAD='false',
            NICEGUI_STORAGE_PATH=storage, NICEGUI_REDIS_URL='', WEBUI_STORAGE_SECRET=uuid4().hex,
            PYTHON_DOTENV_DISABLED='1', PYTHONPATH=str(ROOT))
        environment.pop('PYTEST_ADDOPTS', None)
        maildev_arguments = []
        if args.maildev:
            subprocess.run([sys.executable, str(ROOT / 'run-maildev.py'), 'status'], check=True)
            maildev = json.loads((ROOT / '.runtime/maildev/state.json').read_text())
            environment['SSL_CERT_FILE'] = str(ROOT / '.runtime/maildev/localhost.pem')
            maildev_arguments = ['--maildev-url', f'http://127.0.0.1:{maildev["web_port"]}',
                                 '--smtp-port', str(maildev['smtp_port'])]
        frontend_python = args.webui_python
        # The seed utility imports shared frontend modules in the API environment.
        packages = subprocess.check_output([str(frontend_python), '-c',
            'import sysconfig; print(sysconfig.get_paths()["purelib"])'], text=True).strip()
        environment['PYTHONPATH'] = os.pathsep.join([str(ROOT), packages])

        def start(label, command, *, pass_fds=()):
            log = resources.enter_context((output / f'{label}.log').open('w'))
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=log,
                                       stderr=subprocess.STDOUT, pass_fds=pass_fds)
            processes.append(process)
            return process

        try:
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created = True
            print(f'Created disposable database {name}', flush=True)
            with psycopg.connect(test_url) as connection:
                initialize(connection)
                for seed in ('messaging.sql', 'hold-notification-producers.sql', 'relationship-types.sql'):
                    connection.execute((ROOT / 'database/seeds' / seed).read_text(), prepare=False)
            seed_command = ('import os; from tools.preview_application_settings import seed; seed(dict(os.environ))'
                            if args.preview else 'from tools.seed_webui_regression import seed; seed()')
            if args.fixed_fixture:
                seed_command = 'from tools.seed_webui_regression import seed; seed(browser=True)'
                environment['DATABASE_DISPLAY_NAME'] = 'WebUI regression fixture'
            if args.browser_scope in {'disposition', 'application'}:
                seed_command += '; from tools.seed_webui_disposition import seed as seed_disposition; seed_disposition()'
            result['fixture'] = 'fixed-v1' if args.fixed_fixture else ('settings-preview' if args.preview else 'assembled-v1')
            seed = start('seed', [sys.executable, '-c', seed_command])
            if seed.wait(timeout=300):
                raise RuntimeError('Disposable fixture initialization failed; see seed.log')

            api_command = [sys.executable, '-m', 'uvicorn', 'backend.services.api.main:app',
                           '--fd', str(api_socket.fileno())]
            if args.browser:
                api_command = [sys.executable, '-m', 'tools.webui_browser_server',
                               '--fd', str(api_socket.fileno()), '--output', str(output)]
            api = start('api', api_command, pass_fds=(api_socket.fileno(),))
            wait_ready(api, api_url + '/health')
            services = [api]
            if args.preview or args.browser:
                webui = start('webui', [str(frontend_python), '-c',
                    "import os,runpy,functools; from nicegui import app,ui; from starlette.middleware.sessions import SessionMiddleware; "
                    f"ui.run=functools.partial(ui.run,fd={ui_socket.fileno()}); "
                    "app.add_middleware(SessionMiddleware, secret_key=os.environ['WEBUI_STORAGE_SECRET'], session_cookie='erms_refactor_disposable'); "
                    + ("from tools.webui_browser_server import BrowserDiagnostics, install_client_diagnostics; app.add_middleware(BrowserDiagnostics); "
                       f"install_client_diagnostics({str(output)!r}); " if args.browser else "") +
                    "runpy.run_module('frontend.webui.app',run_name='__main__')"],
                    pass_fds=(ui_socket.fileno(),))
                wait_ready(webui, ui_url + '/')
                services.append(webui)
            result['ready'] = True
            (output / 'lifecycle.json').write_text(json.dumps(result, indent=2) + '\n')
            print(f'Disposable services ready. Evidence: {output}; UI: {ui_url}', flush=True)
            if args.preview:
                while all(p.poll() is None for p in services):
                    time.sleep(.5)
                raise RuntimeError('Owned preview service exited unexpectedly')
            if args.browser:
                browser = start('browser', [args.browser_python, 'tools/check_webui_browser.py',
                    '--browser', args.browser, '--url', ui_url, '--api', api_url,
                    '--scope', args.browser_scope,
                    '--output', str(output), '--api-python', sys.executable, *maildev_arguments])
                result['test_exit_code'] = browser.wait(timeout=900)
                report = output / 'browser-results.json'
                evidence = json.loads(report.read_text()) if report.exists() else {}
                if not evidence.get('complete') or not evidence.get('checks'):
                    result['test_exit_code'] = result['test_exit_code'] or 1
                result['browser'] = args.browser
                return result['test_exit_code']
            with (output / 'assembled.log').open('w') as log:
                run = subprocess.Popen([str(frontend_python), '-m', 'pytest',
                    'frontend/webui/assembled/tests', '-q', '-o', 'asyncio_mode=auto',
                    f'--junitxml={output / "assembled.xml"}', *args.pytest_args],
                    cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
                processes.append(run)
                result['test_exit_code'] = run.wait(timeout=300)
                xml = output / 'assembled.xml'
                cases = list(ET.parse(xml).getroot().iter('testcase')) if xml.exists() else []
                result['tests'] = len(cases)
                result['skipped'] = sum(c.find('skipped') is not None for c in cases)
                if not cases or result['skipped']:
                    result['test_exit_code'] = result['test_exit_code'] or 1
                return result['test_exit_code']
        except KeyboardInterrupt:
            return 130 if not args.preview else 0
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
            for process in reversed(processes):
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            try:
                if created:
                    with psycopg.connect(admin_url, autocommit=True) as admin:
                        admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                        assert not admin.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone()
                    result['database_dropped'] = True
                    print(f'Dropped disposable database {name}', flush=True)
            finally:
                (output / 'lifecycle.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
