"""Run authorization regressions only against a fresh, disposable database."""
import os
from pathlib import Path
import subprocess
import sys
import uuid
from tempfile import TemporaryDirectory
from zipfile import ZipFile


import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.initialize_database import initialize


def run_tests(targets, fixture_root=ROOT):
    baseline_ref = None
    migration_paths = []
    defer_migrations = False
    if targets and targets[0].startswith("--baseline-ref="):
        baseline_ref = targets.pop(0).split("=", 1)[1]
        if not targets or not targets[0].startswith("--migration="):
            raise ValueError("A baseline schema requires an explicit upgrade migration")
        while targets and targets[0].startswith("--migration="):
            migration_paths.append(ROOT / targets.pop(0).split("=", 1)[1])
    seed_reference_data = bool(targets and targets[0]=='--seed-required-reference-data')
    if seed_reference_data:targets.pop(0)
    if targets and targets[0]=='--defer-migrations-to-test':
        targets.pop(0);defer_migrations=True
    schema_source = (
        subprocess.check_output(["git", "show", f"{baseline_ref}:database/schema.sql"], cwd=ROOT, text=True)
        if baseline_ref else (ROOT / "database/schema.sql").read_text()
    )
    configuration = {**dotenv_values(ROOT / ".env"), **os.environ}
    base_url = configuration["DATABASE_URL"]
    # Existing real-process messaging probes enforce this disposable prefix.
    database_name = "erms_messaging_test_acl_" + uuid.uuid4().hex
    admin_url = make_conninfo(base_url, dbname="postgres")
    test_url = make_conninfo(base_url, dbname=database_name)
    created = False
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created = True
        print(f"Created disposable database {database_name}", flush=True)
        with psycopg.connect(test_url) as connection:
            if baseline_ref:
                connection.execute(schema_source, prepare=False)
                # Consolidated schemas keep initialization data separate. Opt in
                # when testing upgrades from such a schema, not older embedded seeds.
                if seed_reference_data:
                    connection.commit()
                    seed_path = 'database/seeds/000_required_reference_data.sql'
                    if fixture_root == ROOT:
                        seed = (ROOT / seed_path).read_text()
                    else:
                        seed = subprocess.check_output(['git', 'show', f'{baseline_ref}:{seed_path}'],
                                                       cwd=ROOT, text=True)
                    connection.execute(seed, prepare=False)
            else:
                initialize(connection)
            for migration_path in ([] if defer_migrations else migration_paths):
                connection.commit()
                connection.execute(migration_path.read_text(), prepare=False)
            connection.commit()
            # Existing messaging tests require the separately maintained seeds.
            for seed in ("messaging.sql", "hold-notification-producers.sql", "relationship-types.sql"):
                connection.execute((fixture_root / "database/seeds" / seed).read_text(), prepare=False)
        environment = {key: str(value) for key, value in configuration.items() if value is not None}
        environment["DATABASE_URL"] = test_url
        environment["AUTH_COOKIE_SECURE"] = "false"
        if defer_migrations:environment["ERMS_TEST_DEFERRED_MIGRATIONS"] = os.pathsep.join(str(p) for p in migration_paths)
        # API regressions also exercise shared WebUI policy/catalogue modules.
        frontend_packages = ROOT / "frontend/webui/.venv/lib/python3.11/site-packages"
        environment["PYTHONPATH"] = os.pathsep.join([str(fixture_root), str(frontend_packages), environment.get("PYTHONPATH", "")])
        targets = targets or ["backend/services/api/tests"]
        if targets[0].startswith("--shard="):
            index, total = map(int, targets.pop(0).split("=", 1)[1].split("/"))
            if not 1 <= index <= total:
                raise ValueError("Shard must be between 1 and the total shard count")
            files = sorted((ROOT / "backend/services/api/tests").glob("test_*.py"))
            targets = [str(path.relative_to(ROOT)) for path in files[index - 1::total]] + targets
        return subprocess.run([sys.executable, "-m", "pytest", "-q", *targets], cwd=fixture_root, env=environment).returncode
    finally:
        if created:
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))
            print(f"Dropped disposable database {database_name}", flush=True)


# These populated upgrades exercise application workflows on both sides of a
# historical schema change. Each release's own setup code speaks that schema.
OCCUPIED_UPGRADES = {
    "066": ("82bb4ed7a2066ed51df56715bbcf872e3864d699", ("066", "067", "068"),
            "test_disposition_destruction_upgrade.py::test_upgrade_retains_actual_physical_outcome_and_drains_legacy_workers"),
    "082": ("12e2b05a5387abbb4624b7f3db55802181691447", ("082",),
            "test_disposition_review_comments_upgrade.py::test_upgrade_preserves_old_notes_submission_decisions_and_events"),
    "094": ("9ab500ff763ac00f34da761fe986c84229c78492", ("094",),
            "test_disposition_simplified_additions.py::test_populated_upgrade_preserves_review_work_then_allows_addition"),
}


def main():
    targets = sys.argv[1:]
    if not targets or not targets[0].startswith('--occupied-workflow='):
        return run_tests(targets)
    number = targets.pop(0).split('=', 1)[1]
    release, versions, test = OCCUPIED_UPGRADES[number]
    selector = 'backend/services/api/tests/' + test
    filename = selector.split('::')[0]
    baseline = release + '^'
    options = ['--baseline-ref=' + baseline]
    for version in versions:
        migration, = (ROOT / 'database/migrations').glob(version + '_*.sql')
        options.append('--migration=' + str(migration.relative_to(ROOT)))
    if number == '094':
        options.append('--seed-required-reference-data')
    with TemporaryDirectory(prefix='erms-occupied-fixtures-') as temporary:
        fixture_root = Path(temporary)
        archive = fixture_root / 'fixtures.zip'
        subprocess.run(['git', 'archive', '--format=zip', '-o', str(archive), release,
                        'backend', 'frontend/webui', 'frontend/__init__.py', 'tools',
                        'templates', 'database/seeds', 'pyproject.toml'], cwd=ROOT, check=True)
        with ZipFile(archive) as files:
            files.extractall(fixture_root)
        # The assertions and SQL under test always come from the working tree.
        (fixture_root / filename).write_bytes((ROOT / filename).read_bytes())
        return run_tests([*options, '--defer-migrations-to-test', selector, *targets], fixture_root)


if __name__ == "__main__":
    sys.exit(main())
