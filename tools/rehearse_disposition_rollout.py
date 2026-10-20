"""Phase 24 rehearsal: only databases created by this invocation are touched.

Uses the actual settings CLI and workers; never starts the persistent local stack.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.check_disposition_foundation_upgrade import baseline_data
from tools.check_disposition_completion_upgrade import snapshot, full_catalogue


def main():
    config = {**dotenv_values(ROOT / '.env'), **os.environ}
    base = config['DATABASE_URL']
    admin = make_conninfo(base, dbname='postgres')
    schema = (ROOT / 'database/schema.sql').read_text()
    migrations = sorted(p for p in (ROOT / 'database/migrations').glob('*.sql')
                        if 50 <= int(p.name.split('_', 1)[0]) <= 70)
    assert len(migrations) == 21
    names = []
    reports = []
    try:
        with TemporaryDirectory(prefix='erms-disposition24-') as directory:
            directory = Path(directory)
            source = directory / 'legacy.env'
            source.write_text('DEFAULT_WORKING_TIMEZONE=UTC\nREVIEW_WARNING_WINDOW_DAYS=7\nDATABASE_URL=private-canary-never-import\n')
            original = source.read_bytes()
            empty = directory / 'empty.env'; empty.write_text('')
            plans = []
            for kind in ('fresh', 'upgrade_a', 'upgrade_b'):
                name = 'erms_disposition24_test_' + kind + '_' + uuid4().hex[:20]
                with psycopg.connect(admin, autocommit=True) as c:
                    c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                names.append(name)
                print('Created disposable database ' + name, flush=True)
                url = make_conninfo(base, dbname=name)
                env = {**os.environ, 'DATABASE_URL': url, 'AUTH_COOKIE_SECURE': 'false', 'PYTHONPATH': str(ROOT)}

                def run(args, expected=0):
                    result = subprocess.run([sys.executable, *args], cwd=ROOT, env=env,
                                            capture_output=True, text=True, timeout=120)
                    # Never echo a connection string or raw driver exception.
                    assert result.returncode == expected, (kind, args[0], result.returncode, 'unexpected command result')
                    assert 'private-canary-never-import' not in result.stdout
                    return result

                with psycopg.connect(url) as c:
                    c.execute(schema if kind == 'fresh' else schema.split('-- Shared configuration foundation.', 1)[0], prepare=False)
                    c.commit()
                    if kind == 'fresh':
                        # Exercise the documented empty-install bootstrap; its
                        # one-time credential is captured and never logged.
                        run(['-m', 'backend.services.api.manage_auth', 'bootstrap',
                             '--name', 'Disposable bootstrap', '--email', 'bootstrap@rehearsal.invalid'])
                    baseline_data(c); c.commit()
                    before = snapshot(c)
                    if kind != 'fresh':
                        for migration in migrations:
                            c.execute(migration.read_text(), prepare=False); c.commit()
                    after = snapshot(c)
                    for table, rows in before.items():
                        assert all(any(all(row.get(k) == value for k, value in old.items()) for (row,) in after[table]) for (old,) in rows), table
                    actual = full_catalogue(c)
                    # Structural parity alone cannot catch missing receipts:
                    # operators use these to skip already committed DDL.
                    installed = {row[0] for row in c.execute('SELECT version FROM schema_migrations')}
                    assert {migration.stem for migration in migrations} <= installed, 'Missing migration receipts'
                    if kind == 'fresh': canonical = actual
                    else: assert actual == canonical, 'Fresh/upgrade catalogue mismatch'
                    assert c.execute('SELECT disposition_private.physical_execution_released(),disposition_private.digital_execution_released()').fetchone() == (False, False)
                    actor = c.execute("SELECT id FROM users WHERE email='upgrade@example.invalid'").fetchone()[0]
                    for seed in ('messaging.sql', 'hold-notification-producers.sql', 'relationship-types.sql', 'disposition-notification-producers.sql'):
                        c.execute((ROOT / 'database/seeds' / seed).read_text(), prepare=False)
                    c.commit()
                cli = ['tools/migrate_application_settings.py', '--database-url', url]
                if kind == 'fresh':
                    run([*cli, '--source-env', str(empty), '--check'])
                else:
                    run([*cli, '--source-env', str(source), '--check'], expected=1)
                    if plans:
                        wrong = run([*cli, '--source-env', str(source), '--apply', '--plan', str(plans[0]), '--actor-user-id', str(actor), '--reason', 'Disposable wrong-target rehearsal'], expected=1)
                        assert 'preview_target_changed' in wrong.stderr
                    plan = directory / (kind + '.json')
                    run([*cli, '--source-env', str(source), '--preview', '--plan', str(plan)])
                    reviewed = json.loads(plan.read_text()); assert not reviewed['issues']
                    apply = [*cli, '--source-env', str(source), '--apply', '--plan', str(plan), '--actor-user-id', str(actor), '--reason', 'Reviewed disposable rollout rehearsal']
                    run(apply); run(apply)
                    run([*cli, '--source-env', str(source), '--check'])
                    plans.append(plan)
                    with psycopg.connect(url) as c:
                        assert c.execute("SELECT value FROM application_settings WHERE key='REVIEW_WARNING_WINDOW_DAYS'").fetchone()[0] == 7
                        assert c.execute("SELECT value FROM application_settings WHERE key='DEFAULT_WORKING_TIMEZONE'").fetchone()[0] == 'UTC'
                run(['database/seeds/004_seed_generated_arabic_ui_translations.py', '--database-url', url])
                for module in ('eligibility', 'communications', 'destruction_worker'):
                    result = run(['-m', 'backend.services.api.disposition.' + module, '--batch-size', '1'])
                    assert '"error"' not in result.stdout
                # Actual API lifespan and health on the selected disposable target.
                run(['-c', 'from fastapi.testclient import TestClient; from backend.services.api.main import app;\nwith TestClient(app) as client:\n r=client.get("/health"); assert r.status_code==200, r.status_code'])
                assert source.read_bytes() == original
                reports.append({'installation': kind, 'database': name, 'result': 'passed', 'data_grants_events_preserved': True, 'api_lifespan_health': 'passed', 'three_worker_one_shots': 'passed', 'execution_gates': False})
                print('Passed ' + kind + ': schema/data/grant preservation, settings readiness, actual CLI, workers and API startup', flush=True)
    finally:
        failures = []
        for name in reversed(names):
            try:
                with psycopg.connect(admin, autocommit=True) as c:
                    c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database ' + name, flush=True)
            except Exception as error:
                failures.append({'database': name, 'error_type': type(error).__name__})
        if failures: raise RuntimeError('Disposable cleanup failed: ' + json.dumps(failures))
    print(json.dumps({'result': 'passed', 'rehearsals': reports, 'source_file_preserved': True, 'cross_database_plan_rejected': True, 'settings_apply_rerun': 'passed', 'persistent_database_modified': False, 'cleanup': 'passed'}, indent=2))


if __name__ == '__main__':
    main()
