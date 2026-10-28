#!/usr/bin/env python3
"""Create, initialize, compare, test, and always drop two disposable databases."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MARKER = (
    "-- Notifications and messaging: complete storage model (specification section 7)."
)


from tools.historical_schema import historical_schema
from tools.initialize_database import initialize


def main():
    load_dotenv(ROOT / ".env", override=False)
    admin_info = conninfo_to_dict(os.environ["DATABASE_URL"])
    admin_info["dbname"] = "postgres"
    names = []
    processes = []
    preview = any(
        flag in sys.argv
        for flag in ("--preview", "--preview-multi", "--preview-notifications")
    )
    result = 1
    try:
        canonical = historical_schema()
        baseline, kernel = canonical.split(MARKER, 1)
        migration = (
            ROOT / "database/migrations/033_add_messaging_kernel.sql"
        ).read_text()
        for suffix in ("fresh", "upgrade"):
            name = "erms_messaging_test_" + uuid4().hex[:16] + "_" + suffix
            with psycopg.connect(**admin_info, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
                )
            names.append(name)
            print("Created disposable database " + name, flush=True)
            with psycopg.connect(**dict(admin_info, dbname=name)) as connection:
                if suffix == "fresh":initialize(connection)
                else:connection.execute(baseline)
                if suffix == "upgrade":
                    # Upgrade a populated predecessor, not another empty schema.
                    connection.execute(
                        "INSERT INTO users(name) VALUES ('Upgrade preservation fixture')"
                    )
                    connection.commit()
                    connection.execute(migration)
                    connection.execute(
                        (
                            ROOT
                            / "database/migrations/034_messaging_human_workflows.sql"
                        ).read_text()
                    )
                    connection.execute(
                        (
                            ROOT / "database/migrations/035_messaging_live_signals.sql"
                        ).read_text()
                    )
                    connection.execute(
                        (
                            ROOT
                            / "database/migrations/036_notification_administration_guards.sql"
                        ).read_text()
                    )
                    connection.execute(
                        (ROOT / "database/migrations/037_messaging_retention.sql").read_text()
                    )
                    connection.execute((ROOT / "database/migrations/038_legal_hold_notifications.sql").read_text())
                    connection.execute((ROOT / "database/migrations/039_localized_notification_producer_names.sql").read_text())
                    connection.execute((ROOT / "database/migrations/040_message_record_aggregation_links.sql").read_text())
                    connection.execute((ROOT / "database/migrations/041_to_recipient_action_completion.sql").read_text())
                    connection.execute((ROOT / "database/migrations/042_messaging_everyone.sql").read_text())
                    connection.execute((ROOT / "database/migrations/043_legal_hold_notification_governors.sql").read_text())
                    connection.execute((ROOT / "database/migrations/044_hold_assignment_recipient_only.sql").read_text())
                    connection.execute("INSERT INTO messaging_gateway_health VALUES ('00000000-0000-0000-0000-000000000045',CURRENT_TIMESTAMP,false,1,0,NULL,0,0)")
                    connection.execute((ROOT / "database/migrations/045_messaging_gateway_health_lifecycle.sql").read_text())
                    assert connection.execute("SELECT host_addresses IS NULL AND api_port IS NULL FROM messaging_gateway_health WHERE instance_id='00000000-0000-0000-0000-000000000045'").fetchone()[0]
                    assert (
                        connection.execute(
                            "SELECT count(*) FROM users WHERE name='Upgrade preservation fixture'"
                        ).fetchone()[0]
                        == 1
                    )
                connection.commit()
                connection.execute((ROOT / "database/seeds/messaging.sql").read_text())
                connection.execute((ROOT / "database/seeds/hold-notification-producers.sql").read_text())
        dumps = []
        for name in names:
            env = dict(os.environ, PGDATABASE=name)
            # Connection credentials stay in the process environment, not argv/output.
            for key, value in admin_info.items():
                if key in ("host", "port", "user", "password"):
                    env["PG" + key.upper()] = str(value)
            output = subprocess.check_output(
                ["pg_dump", "--schema-only", "--no-owner", "--no-privileges"],
                env=env,
                text=True,
            )
            dumps.append(re.sub(r"^\\(?:un)?restrict .*\n", "", output, flags=re.M))
        assert dumps[0] == dumps[1], "Fresh/upgrade structures differ"
        print("Fresh/upgrade schema parity and data preservation passed", flush=True)
        if "--schema-only" in sys.argv:
            result = 0
        else:
            env = dict(
                os.environ,
                DATABASE_URL=make_conninfo(**dict(admin_info, dbname=names[0])),
                MESSAGING_LISTENER_DATABASE_URL=make_conninfo(
                    **dict(admin_info, dbname=names[0])
                ),
                PYTHONPATH=str(ROOT),
            )
            paths = [
                arg
                for arg in sys.argv[1:]
                if arg
                not in {"--preview", "--preview-multi", "--preview-notifications"}
            ] or ["backend/services/api/tests/test_messaging.py"]
            result = subprocess.call(
                [sys.executable, "-m", "pytest", "-q", *paths], cwd=ROOT, env=env
            )
            if result == 0 and preview:
                subprocess.run(
                    [sys.executable, "-m", "tools.messaging_preview"],
                    cwd=ROOT,
                    env=env,
                    check=True,
                )
                if "--preview-notifications" in sys.argv:
                    subprocess.run(
                        [sys.executable, "-m", "tools.notification_preview"],
                        cwd=ROOT,
                        env=env,
                        check=True,
                    )
                for instance in range(2 if "--preview-multi" in sys.argv else 1):
                    api_port, ui_port = str(18001 + instance), str(18081 + instance)
                    preview_env = dict(
                        env,
                        API_HOST="127.0.0.1",
                        API_PORT=api_port,
                        WEBUI_API_URL="http://127.0.0.1:" + api_port,
                        WEBUI_PORT=ui_port,
                        WEBUI_HOST="127.0.0.1",
                        WEBUI_RELOAD="false",
                        NICEGUI_STORAGE_PATH=tempfile.mkdtemp(
                            prefix="erms-messaging-ui-"
                        ),
                        WEBUI_STORAGE_SECRET=uuid4().hex,
                    )
                    for command in (
                        [
                            sys.executable,
                            "-m",
                            "uvicorn",
                            (
                                "tools.notification_preview:app"
                                if "--preview-notifications" in sys.argv
                                else "backend.services.api.main:app"
                            ),
                            "--host",
                            "127.0.0.1",
                            "--port",
                            api_port,
                        ],
                        [
                            str(ROOT / "frontend/webui/.venv/bin/python"),
                            "-m",
                            "frontend.webui.app",
                        ],
                    ):
                        processes.append(
                            subprocess.Popen(command, cwd=ROOT, env=preview_env)
                        )
                print(
                    "Disposable preview http://127.0.0.1:18081 — Ctrl-C cleans up",
                    flush=True,
                )
                try:
                    while all(process.poll() is None for process in processes):
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for name in reversed(names):
            try:
                with psycopg.connect(**admin_info, autocommit=True) as admin:
                    admin.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(name)
                        )
                    )
                print("Dropped disposable database " + name, flush=True)
            except Exception as error:
                print(
                    "FAILED to drop disposable database " + name + ": " + str(error),
                    file=sys.stderr,
                )
                result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
