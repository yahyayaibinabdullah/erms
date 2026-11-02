"""Phase 23: populated pre-configuration upgrade and complete schema parity.

Creates and drops both databases itself. It never opens a persistent ERMS DB.
"""
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.check_disposition_completion_upgrade import full_catalogue, snapshot
from tools.check_disposition_foundation_upgrade import baseline_data


from tools.historical_schema import historical_schema


def main():
    configuration = {**dotenv_values(ROOT / '.env'), **os.environ}
    base = configuration['DATABASE_URL']
    admin = make_conninfo(base, dbname='postgres')
    schema = historical_schema()
    old = schema.split('-- Shared configuration foundation.', 1)[0]
    migrations = sorted((ROOT / 'database/migrations').glob('*.sql'))
    migrations = [p for p in migrations if 50 <= int(p.name.split('_', 1)[0]) <= 71]
    assert len(migrations) == 22
    names = []
    try:
        for kind in ('fresh', 'populated_upgrade'):
            name = 'erms_disposition23_test_' + kind + '_' + uuid4().hex
            with psycopg.connect(admin, autocommit=True) as c:
                c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            names.append(name)
            print('Created disposable database ' + name, flush=True)
            with psycopg.connect(make_conninfo(base, dbname=name)) as c:
                c.execute(schema if kind == 'fresh' else old, prepare=False)
                c.commit()
                if kind == 'fresh':
                    canonical = full_catalogue(c)
                    continue
                baseline_data(c)
                c.commit()
                before = snapshot(c)
                for migration in migrations:
                    c.execute(migration.read_text(), prepare=False)
                    c.commit()
                after = snapshot(c)
                # Added columns/grants/history are expected. Every pre-existing
                # row, field and immutable event must retain its exact value.
                for table, rows in before.items():
                    upgraded = [r[0] for r in after[table]]
                    for (prior,) in rows:
                        assert any(all(row.get(k) == v for k, v in prior.items()) for row in upgraded), table
                actual = full_catalogue(c)
                differing = [key for key in canonical if canonical[key] != actual[key]]
                assert not differing, 'Canonical/050–071 catalogue differences: ' + repr(differing)
                assert c.execute('SELECT installation_kind FROM application_settings_state').fetchone()[0] == 'upgrade'
                assert c.execute("SELECT to_regprocedure('disposition_private.physical_execution_released()'),to_regprocedure('disposition_private.digital_execution_released()')").fetchone() == (None, None)
                print('Passed: populated 050–071 upgrade; complete schema/function/view/privilege parity; all original data, settings, grants and events preserved; temporary gates absent; workflow guards preserved.', flush=True)
    finally:
        failures = []
        for name in reversed(names):
            try:
                with psycopg.connect(admin, autocommit=True) as c:
                    c.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database ' + name, flush=True)
            except Exception as error:
                failures.append((name, type(error).__name__))
        if failures:
            raise RuntimeError('Disposable cleanup failed: ' + json.dumps(failures))


if __name__ == '__main__':
    main()
