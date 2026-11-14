"""Run the DB-free WebUI suites in separate, network-isolated processes."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    local_python = ROOT / 'frontend/webui/.venv/bin/python'
    parser.add_argument('--python', default=str(local_python if local_python.exists() else sys.executable))
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    output = (args.output or ROOT / '.runtime/webui-tests' / uuid4().hex).resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, DATABASE_URL='', MESSAGING_LISTENER_DATABASE_URL='',
                       WEBUI_API_URL='http://127.0.0.1:1', PYTHON_DOTENV_DISABLED='1',
                       NICEGUI_STORAGE_PATH=str(output / 'storage'), NICEGUI_REDIS_URL='',
                       WEBUI_STORAGE_SECRET='disposable-webui-tests-only')
    # Caller options must not override suite selection or silently deselect tests.
    environment.pop('PYTEST_ADDOPTS', None)
    results = []
    print(f'WebUI test evidence: {output}', flush=True)
    try:
        for repetition in range(1, args.repeat + 1):
            for suite, target in [('unit', 'frontend/webui/tests'),
                                  ('interaction', 'frontend/webui/interaction/tests')]:
                name = f'{repetition}-{suite}'
                xml = output / f'{name}.xml'
                command = [args.python, '-m', 'pytest', target, '-q',
                           '-p', 'tools.webui_no_network', '-o', 'asyncio_mode=auto',
                           f'--junitxml={xml}']
                # NiceGUI creates the storage directory itself, but not its
                # parents. Each isolated suite needs its own existing parent.
                (output / name).mkdir()
                with (output / f'{name}.log').open('w') as log:
                    status = subprocess.run(command, cwd=ROOT,
                                            env=dict(environment, NICEGUI_STORAGE_PATH=str(output / name / 'storage')),
                                            stdout=log, stderr=subprocess.STDOUT, timeout=600).returncode
                result = {'run': repetition, 'suite': suite, 'exit_code': status}
                if xml.exists():
                    cases = list(ET.parse(xml).getroot().iter('testcase'))
                    result.update(tests=len(cases), failures=sum(c.find('failure') is not None for c in cases),
                                  errors=sum(c.find('error') is not None for c in cases),
                                  skipped=sum(c.find('skipped') is not None for c in cases))
                results.append(result)
                print(json.dumps(result), flush=True)
    finally:
        (output / 'summary.json').write_text(json.dumps({
            'finished_at': datetime.now(timezone.utc).isoformat(), 'runs': results,
            'requested_repetitions': args.repeat, 'network_access': 'blocked before collection',
            'complete': len(results) == args.repeat * 2,
        }, indent=2) + '\n')
    return int(any(r['exit_code'] or not r.get('tests') or r.get('failures') or
                   r.get('errors') or r.get('skipped') for r in results))


if __name__ == '__main__':
    raise SystemExit(main())
