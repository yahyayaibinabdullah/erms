"""Fresh installation and incremental migration contract, using owned databases only."""
from contextlib import ExitStack
import os
import subprocess
import sys

from dotenv import dotenv_values
import psycopg
from psycopg.conninfo import conninfo_to_dict
import pytest

from tools import initialize_database as installer
from tools.check_resource_type_upgrade import disposable, PRE_TYPE_REVISION
from tools.verify_canonical_schema import dump_schema

ROOT = installer.ROOT
BASELINE = ROOT / 'database/baseline.sql'
CHECKS = ROOT / 'database/tests/migration_checks'


@pytest.fixture
def new_database():
    configuration = {**dotenv_values(ROOT / '.env'), **os.environ}
    with ExitStack() as owned:
        def create(label):
            return owned.enter_context(disposable(configuration['DATABASE_URL'], label, {}))
        yield create


def psql(url, source):
    settings = conninfo_to_dict(url)
    env = dict(os.environ)
    for key in ('host', 'port', 'user', 'password', 'sslmode'):
        if key in settings:
            env['PG' + key.upper()] = settings[key]
    return subprocess.run(['psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-d', settings['dbname']],
                          input=source, text=True, capture_output=True, env=env)


def receipts(connection):
    return [row[0] for row in connection.execute(
        'SELECT version FROM public.schema_migrations ORDER BY version')]


def test_rollback_and_retry_from_both_entry_points(new_database, monkeypatch, tmp_path):
    url = new_database('rollback')
    empty = dump_schema(url, 'pg_dump')
    failed_baseline = tmp_path / 'baseline.sql'
    insertion = 'INSERT INTO schema_migrations(version)'
    assert BASELINE.read_text().count(insertion) == 1
    fault = """DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM public.privileges) THEN RAISE EXCEPTION 'seed missing'; END IF;
        RAISE EXCEPTION 'injected receipt failure';
    END $$;
    """
    failed_baseline.write_text(BASELINE.read_text().replace(insertion, fault + insertion))
    with monkeypatch.context() as m:
        m.setattr(installer, 'INSTALL_FILES', (*installer.INSTALL_FILES[:-1], failed_baseline))
        with psycopg.connect(url) as c, pytest.raises(psycopg.errors.RaiseException, match='injected receipt failure'):
            installer.initialize(c)
    assert dump_schema(url, 'pg_dump') == empty

    emitted = subprocess.check_output([sys.executable, str(ROOT / 'tools/initialize_database.py'),
                                       '--print-sql'], text=True)
    failed = psql(url, emitted.replace(insertion, fault + insertion))
    assert failed.returncode and 'injected receipt failure' in failed.stderr
    assert dump_schema(url, 'pg_dump') == empty
    succeeded = psql(url, emitted)
    assert succeeded.returncode == 0, succeeded.stderr
    with psycopg.connect(url, autocommit=True) as c:
        original = receipts(c)
        assert original and c.execute("SELECT to_regclass('pg_temp.erms_fresh_install')").fetchone() == (None,)
        with pytest.raises(ValueError, match='already contains a schema'):
            installer.initialize(c)
        assert receipts(c) == original


@pytest.mark.parametrize('bad_body', [
    'BEGIN; SELECT 1; COMMIT; SELECT 2;',
    'BEGIN; SELECT 1; COMMIT; BEGIN; SELECT 2; COMMIT;',
])
def test_installer_rejects_extra_transaction_boundaries(tmp_path, monkeypatch, bad_body):
    path = tmp_path / 'invalid.sql'
    path.write_text(bad_body)
    monkeypatch.setattr(installer, 'INSTALL_FILES', (path,))
    with pytest.raises(ValueError, match='transaction'):
        installer.installation_body()


def test_current_schema_with_empty_history_cannot_be_baselined(new_database):
    url = new_database('schema_only')
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(installer.INSTALL_FILES[0].read_text(), prepare=False)
        c.execute(installer.INSTALL_FILES[1].read_text(), prepare=False)
        assert receipts(c) == []
        for source in (BASELINE.read_text(), 'BEGIN;\n' + installer.installation_body() + '\nCOMMIT;'):
            refused = psql(url, source)
            assert refused.returncode and ('Baseline requires' in refused.stderr or
                                           'already contains a schema' in refused.stderr)
            assert receipts(c) == []
        assert c.execute('SELECT EXISTS (SELECT FROM public.privileges)').fetchone() == (True,)


def test_partial_schema_without_ledger_is_preserved(new_database):
    url = new_database('partial')
    with psycopg.connect(url, autocommit=True) as c:
        c.execute('CREATE TABLE public.records(id int); INSERT INTO public.records VALUES(42)')
        with pytest.raises(ValueError, match='already contains a schema'):
            installer.initialize(c)
        assert c.execute('SELECT * FROM public.records').fetchall() == [(42,)]
        assert c.execute("SELECT to_regclass('public.schema_migrations')").fetchone() == (None,)


def test_upgrade_matches_fresh_and_standalone_baseline_cannot_stamp_existing_schema(new_database):
    fresh, old = new_database('fresh'), new_database('existing')
    with psycopg.connect(fresh, autocommit=True) as f, psycopg.connect(old, autocommit=True) as u:
        installer.initialize(f)
        # These seeded reference grants also have to exist on a fresh install.
        categories = CHECKS / '125_type_administration_privilege_codes.after.sql'
        assert f.execute(categories.read_text()).fetchall() == [(True,)]
        # The anchor freezes the intentional historical gaps. Derive all newer
        # expected receipts from migration filenames, independently of baseline.sql.
        for path in installer.INSTALL_FILES:
            historical = subprocess.check_output(
                ['git', 'show', PRE_TYPE_REVISION + ':' + path.relative_to(ROOT).as_posix()],
                cwd=ROOT, text=True)
            if path == BASELINE:
                assert receipts(u) == []
                result = psql(old, BASELINE.read_text())
                assert result.returncode and 'Baseline requires the fresh-install transaction' in result.stderr
                with pytest.raises(ValueError, match='already contains a schema'):
                    installer.initialize(u)
                assert receipts(u) == []
            u.execute(historical, prepare=False)
        expected = receipts(u)
        historical_files = subprocess.check_output(
            ['git', 'ls-tree', '--name-only', PRE_TYPE_REVISION + ':database/migrations'],
            cwd=ROOT, text=True).splitlines()
        paths = sorted((ROOT / 'database/migrations').glob('*.sql'))
        assert set(historical_files) <= {p.name for p in paths}, 'Released migrations changed names or were removed'
        before = dump_schema(old, 'pg_dump')
        for migration in paths:
            if migration.name in historical_files:
                continue
            given = CHECKS / (migration.stem + '.before.sql')
            if given.exists():
                u.execute(given.read_text(), prepare=False)
            u.execute(migration.read_text(), prepare=False)
            expected.append(migration.stem)
            assert receipts(u) == sorted(expected)
            after = dump_schema(old, 'pg_dump')
            check = CHECKS / (migration.stem + '.after.sql')
            if before == after:
                assert check.is_file(), f'{migration.name} needs a data assertion in {check.name}'
            if check.is_file():
                assert u.execute(check.read_text()).fetchall() == [(True,)], migration.name
            before = after
        assert receipts(f) == sorted(expected)
        assert dump_schema(fresh, 'pg_dump') == before
        original = receipts(u)
        rejected = psql(old, BASELINE.read_text())
        assert rejected.returncode and 'Baseline requires the fresh-install transaction' in rejected.stderr
        assert receipts(u) == original
