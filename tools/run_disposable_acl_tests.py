"""Run authorization regressions only against a fresh, disposable database."""
import os
from pathlib import Path
import subprocess
import sys
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    targets = sys.argv[1:]
    baseline_ref = None
    migration_path = None
    if targets and targets[0].startswith("--baseline-ref="):
        baseline_ref = targets.pop(0).split("=", 1)[1]
        if not targets or not targets[0].startswith("--migration="):
            raise ValueError("A baseline schema requires an explicit upgrade migration")
        migration_path = ROOT / targets.pop(0).split("=", 1)[1]
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
            connection.execute(schema_source, prepare=False)
            if migration_path:
                connection.commit()
                connection.execute(migration_path.read_text(), prepare=False)
            connection.commit()
            # Existing messaging tests require the separately maintained seeds.
            for seed in ("messaging.sql", "hold-notification-producers.sql", "relationship-types.sql"):
                connection.execute((ROOT / "database/seeds" / seed).read_text(), prepare=False)
        environment = {key: str(value) for key, value in configuration.items() if value is not None}
        environment["DATABASE_URL"] = test_url
        environment["AUTH_COOKIE_SECURE"] = "false"
        environment["TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS"] = "365"
        # API regressions also exercise shared WebUI policy/catalogue modules.
        frontend_packages = ROOT / "frontend/webui/.venv/lib/python3.11/site-packages"
        environment["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(frontend_packages), environment.get("PYTHONPATH", "")])
        targets = targets or ["backend/services/api/tests"]
        if targets[0].startswith("--shard="):
            index, total = map(int, targets.pop(0).split("=", 1)[1].split("/"))
            if not 1 <= index <= total:
                raise ValueError("Shard must be between 1 and the total shard count")
            files = sorted((ROOT / "backend/services/api/tests").glob("test_*.py"))
            targets = [str(path.relative_to(ROOT)) for path in files[index - 1::total]] + targets
        return subprocess.run([sys.executable, "-m", "pytest", "-q", *targets], cwd=ROOT, env=environment).returncode
    finally:
        if created:
            with psycopg.connect(admin_url, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))
            print(f"Dropped disposable database {database_name}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
