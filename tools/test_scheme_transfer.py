#!/usr/bin/env python3
"""Own two disposable databases for the full transfer acceptance process."""

import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from tools.initialize_database import initialize


def main():
    load_dotenv(ROOT / ".env", override=False)
    info = conninfo_to_dict(os.environ["DATABASE_URL"])
    info["dbname"] = "postgres"  # Administrative DDL only; never run tests here.
    names, processes, result = [], [], 1
    preview = "--preview" in sys.argv
    arguments = [arg for arg in sys.argv[1:] if arg != "--preview"]
    try:
        with psycopg.connect(**info, autocommit=True) as admin:
            for suffix in ("source", "destination"):
                name = "erms_transfer_test_" + uuid4().hex[:16] + "_" + suffix
                admin.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
                )
                names.append(name)
                print("Created disposable database " + name, flush=True)
                with psycopg.connect(**dict(info, dbname=name)) as connection:
                    initialize(connection)
        env = dict(
            os.environ,
            DATABASE_URL=make_conninfo(**dict(info, dbname=names[1])),
            TRANSFER_SOURCE_DATABASE_URL=make_conninfo(**dict(info, dbname=names[0])),
            TRANSFER_DISPOSABLE_RUN="1",
            PYTHONPATH=str(ROOT),
        )
        setup = "from backend.services.api.scheme_transfer.tests.conftest import client; setup=client.__wrapped__(); next(setup); setup.close()"
        subprocess.run(
            [sys.executable, "-c", setup],
            cwd=ROOT,
            env=dict(env, DATABASE_URL=env["TRANSFER_SOURCE_DATABASE_URL"]),
            check=True,
        )
        result = subprocess.call(
            [
                sys.executable,
                "-m",
                "pytest",
                "backend/services/api/scheme_transfer/tests",
                "-q",
                *arguments,
            ],
            cwd=ROOT,
            env=env,
        )
        if result == 0 and preview:
            preview_env = dict(
                env,
                WEBUI_API_URL="http://127.0.0.1:18000",
                WEBUI_PORT="18080",
                WEBUI_HOST="127.0.0.1",
                WEBUI_RELOAD="false",
                NICEGUI_STORAGE_PATH=tempfile.mkdtemp(prefix="erms-transfer-ui-"),
                WEBUI_STORAGE_SECRET=uuid4().hex,
            )
            processes.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "backend.services.api.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "18000",
                    ],
                    cwd=ROOT,
                    env=preview_env,
                )
            )
            processes.append(
                subprocess.Popen(
                    [
                        str(ROOT / "frontend/webui/.venv/bin/python"),
                        "-m",
                        "frontend.webui.app",
                    ],
                    cwd=ROOT,
                    env=preview_env,
                )
            )
            print(
                "Disposable preview: http://127.0.0.1:18080 — Ctrl-C cleans up",
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
                with psycopg.connect(**info, autocommit=True) as admin:
                    admin.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(name)
                        )
                    )
                print("Dropped disposable database " + name, flush=True)
            except Exception as error:
                print(
                    f"Cleanup failed for {name}: {type(error).__name__}",
                    file=sys.stderr,
                )
                result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
