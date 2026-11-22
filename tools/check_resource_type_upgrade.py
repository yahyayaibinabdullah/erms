"""Measure resource type migrations on the populated search fixture and compare full schema dumps."""
import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.canonical_schema import statements
from tools.check_search_performance import AGGREGATIONS, RECORDS, exercise, seed
from tools.search_benchmark_support import BufferedOutput
from tools.initialize_database import initialize
from tools.verify_canonical_schema import dump_schema

# The combined upgrade starts after the published PDF migration, before types.
PRE_TYPE_REVISION = "50b2aaa07452029344c31e3cd0b2f19dfcd74118"
MIGRATION = ROOT / "database/migrations/119_resource_types.sql"


@contextmanager
def disposable(base_url, role, lifecycle):
    name = "erms_type_upgrade_" + role + "_" + uuid4().hex
    with psycopg.connect(make_conninfo(base_url, dbname="postgres"), autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        lifecycle[name] = "created"
        print("Created disposable database", name, flush=True)
        try:
            yield make_conninfo(base_url, dbname=name)
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            lifecycle[name] = "dropped"
            print("Dropped disposable database", name, flush=True)


def populate(connection):
    for source in ("database/schema.sql", "database/seeds/000_required_reference_data.sql", "database/baseline.sql"):
        if source == "database/baseline.sql":
            try:
                connection.execute((ROOT / source).read_text(), prepare=False)
            except psycopg.errors.RaiseException as error:
                assert "Baseline requires the fresh-install transaction" in str(error)
                connection.rollback()
            else:
                raise AssertionError("Current baseline accepted the older PDF schema")
        previous = subprocess.check_output(["git", "show", PRE_TYPE_REVISION + ":" + source], cwd=ROOT, text=True)
        connection.execute(previous, prepare=False)
        connection.commit()
    seed(connection)
    connection.execute("SELECT set_config('app.event_source','seeding',true), set_config('app.change_reason','Upgrade fixture',true)")
    connection.execute("""
        INSERT INTO saved_searches(owner_user_id, name, resource_type, definition)
        SELECT id, 'Existing ' || kind, kind,
               jsonb_build_object('schema_version',1,'resource_type',kind,
                     'request',jsonb_build_object('where',jsonb_build_object('field','title','operator','contains_ci','value','common'),
                     'sort',jsonb_build_array(jsonb_build_object('field','id','direction','asc')),'limit',25))
        FROM users CROSS JOIN unnest(ARRAY['record','aggregation']) kind WHERE email='reader@performance.invalid'
    """)
    connection.execute("""
        INSERT INTO ui_message_definitions(message_key,context_group,default_text,semantic_meaning,
            common_locations,translator_guidance,grammatical_role,rendered_example)
        VALUES('upgrade.fixture','upgrade','Archive','Archive a record','["fixture"]','Use a verb','verb','Archive')
    """)
    connection.execute("""
        INSERT INTO ui_message_translations(message_key,language_tag,translated_text,published_text,
            status,origin,published_by_user_id,date_published)
        SELECT 'upgrade.fixture','ar','أرشف','أرشف','published','manual',id,now()
        FROM users WHERE email='reader@performance.invalid'
    """)
    connection.execute("""UPDATE roles SET translations='{"ar":{"name":"قارئ"}}' WHERE code='PERF'""")
    connection.commit()


def snapshot(connection):
    snapshot = {}
    for table in ("aggregations", "records", "saved_searches"):
        # Compare every old column and row, including versions and timestamps.
        digest = hashlib.sha256()
        statement = sql.SQL("COPY (SELECT (to_jsonb(r) - 'type_id')::text FROM {} r ORDER BY id) TO STDOUT").format(sql.Identifier(table))
        with connection.cursor().copy(statement) as copy:
            for block in copy:
                digest.update(block)
        count = connection.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()["n"]
        snapshot[table] = {"rows": count, "sha256": digest.hexdigest()}
    return snapshot


def preserved_content(c, last_event):
    # New migration events may be appended. Compare the complete prior history,
    # including actor, reason, timestamps and JSON, in its original ID order.
    digest = hashlib.sha256()
    with c.cursor().copy(
        "COPY (SELECT to_jsonb(e)::text FROM event_history e WHERE id<=%s ORDER BY id) TO STDOUT",
        (last_event,),
    ) as stream:
        for chunk in stream:
            digest.update(chunk)
    return {
        "history_sha256": digest.hexdigest(),
        "history_rows": c.execute("SELECT count(*) AS n FROM event_history WHERE id<=%s",
                                  (last_event,)).fetchone()["n"],
        "role_translations": c.execute("SELECT translations FROM roles WHERE code='PERF'").fetchone()["translations"],
        "published_translation": c.execute("""
            SELECT to_jsonb(t) AS row FROM ui_message_translations t
            WHERE message_key='upgrade.fixture' AND language_tag='ar'
        """).fetchone()["row"],
    }


def profile_grants(connection):
    return {(row["profile"], row["privilege"]) for row in connection.execute("""
        SELECT p.code AS profile, privilege.code AS privilege FROM profile_privileges pp
          JOIN profiles p ON p.id=pp.profile_id JOIN privileges privilege ON privilege.id=pp.privilege_id
    """)}


def storage(connection):
    return connection.execute("""
        SELECT relname, pg_relation_filenode(oid) AS heap_file, pg_relation_size(oid) AS heap_bytes,
               pg_indexes_size(oid) AS index_bytes FROM pg_class
        WHERE oid IN ('public.records'::regclass,'public.aggregations'::regclass) ORDER BY relname
    """).fetchall()


def measure(connection, url, report):
    # Execute every migration statement in its original transaction. Measure resource
    # index builds separately and sample their locks from another session.
    # The per-mode duration is a sampled lower bound; total time includes commit.
    pid = connection.info.backend_pid
    ready, finished = threading.Event(), threading.Event()
    locks = []
    errors = []

    def monitor():
        try:
            with psycopg.connect(url, autocommit=True, row_factory=dict_row) as observer:
                ready.set()
                while not finished.is_set():
                    rows = observer.execute("""
                        SELECT relation::regclass::text AS relation, mode, granted FROM pg_locks
                        WHERE pid=%s AND relation IN ('records'::regclass,'aggregations'::regclass)
                        ORDER BY 1,2
                    """, (pid,)).fetchall()
                    locks.append({"time": time.perf_counter(), "locks": rows})
                    finished.wait(0.005)
        except BaseException as error:
            errors.append(error)
            ready.set()

    commands = statements(MIGRATION.read_text())
    report["resource_index_builds"] = []
    thread = threading.Thread(target=monitor)
    thread.start()
    try:
        ready.wait()
        start = time.perf_counter()
        for command in commands:
            started = time.perf_counter()
            connection.execute(command, prepare=False)
            if command.startswith(("ALTER TABLE public.aggregations ADD UNIQUE", "ALTER TABLE public.records ADD UNIQUE",
                                   "CREATE INDEX aggregation_type_assignments", "CREATE INDEX record_type_assignments")):
                report["resource_index_builds"].append({"statement": command, "seconds": time.perf_counter() - started})
        connection.commit()
        report["migration_seconds"] = time.perf_counter() - start
    finally:
        finished.set()
        thread.join()
    if errors:
        raise errors[0]
    for sample in locks:
        sample["time"] -= start
    report["lock_samples"] = locks


def measure_text_upgrade(c, report):
    """Apply the actual next migration to populated Phase 3 data."""
    for kind in ("record", "aggregation"):
        c.execute("SELECT set_config('app.event_source','seeding',true)")
        type_id = c.execute("INSERT INTO resource_types(kind,name) VALUES(%s,'Upgrade') RETURNING id",
                            (kind,)).fetchone()["id"]
        field_id = c.execute("""INSERT INTO resource_type_fields(kind,type_id,name,data_type,display_order,max_length)
                                VALUES(%s,%s,'Reference','text',1,50) RETURNING id""",
                             (kind, type_id)).fetchone()["id"]
        # Construct an already-populated Phase 3 fixture with its original index.
        c.execute("SET LOCAL session_replication_role='replica'")
        c.execute(f"UPDATE {kind}s SET type_id=%s WHERE id<=15001 AND id%%3=1", (type_id,))
        count = c.execute(f"""INSERT INTO resource_type_values(kind,resource_id,type_id,field_id,data_type,text_capacity,value)
                              SELECT %s,id,type_id,%s,'text',50,resource_field_decode('text','"migrationproof"')
                              FROM {kind}s WHERE type_id=%s""", (kind,field_id,type_id)).rowcount
        assert count == 5001
        c.execute(f"CREATE TEMP TABLE previous_{kind}_documents AS TABLE {kind}_search_documents")
        c.commit()

    migration = ROOT / "database/migrations/121_type_text_search.sql"
    started = time.perf_counter()
    c.execute(migration.read_text(), prepare=False)
    c.commit()
    report["text_upgrade"] = {"migration_sha256": hashlib.sha256(migration.read_bytes()).hexdigest(),
                              "migration_and_commit_seconds": time.perf_counter() - started, "documents": {}}

    for kind, total in (("record", RECORDS), ("aggregation", AGGREGATIONS)):
        # Independently calculate every expected vector from its pre-upgrade bytes.
        # Untouched owners must also preserve their original indexing timestamps.
        result = c.execute(f"""SELECT count(*) AS documents,
            count(*) FILTER (WHERE d.search_vector @@ plainto_tsquery(d.text_search_config,'migrationproof')) AS backfilled,
            bool_and(d.search_vector = CASE WHEN d.{kind}_id<=15001 AND d.{kind}_id%3=1
                     THEN old.search_vector || setweight(to_tsvector(old.text_search_config,'migrationproof'),'B')
                     ELSE old.search_vector END) AS exact_vectors,
            bool_and(d.text_search_config=old.text_search_config AND d.index_config_version=old.index_config_version
                     AND (d.search_vector<>old.search_vector OR d.indexed_at=old.indexed_at)) AS preserved
            FROM {kind}_search_documents d JOIN previous_{kind}_documents old USING({kind}_id)""").fetchone()
        assert result == {"documents": total, "backfilled": 5001, "exact_vectors": True, "preserved": True}
        report["text_upgrade"]["documents"][kind] = result


def verify_legacy_searches(client, connection, repeats):
    results = []
    for saved in connection.execute("""
        SELECT id,name,resource_type,definition FROM saved_searches
        WHERE name IN ('Existing record','Existing aggregation') ORDER BY name
    """).fetchall():
        url = f"/api/v1/saved-searches/{saved['id']}"
        opened = client.get(url)
        opened.raise_for_status()
        assert opened.json()["definition"]["request"] == saved["definition"]["request"]
        for round_no in range(repeats):
            started = time.perf_counter()
            response = client.post(url + "/execute", json={"tab_id": str(uuid4()), "limit": 25})
            elapsed = time.perf_counter() - started
            response.raise_for_status()
            page = response.json()
            ids = [item["id"] for item in page["items"]]
            assert ids == list(range(1, 26)) and page["total"] == 1000 and page["truncated"]
            results.append({"kind": saved["resource_type"], "round": round_no + 1, "seconds": elapsed,
                            "total": page["total"], "ids": ids})
    assert len(results) == repeats * 2
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--broad-search", action="store_true",
                        help="Repeat the standard broad search and paging cases on the upgraded fixture")
    parser.add_argument("--settle-seconds", type=int, default=30)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    config = {**dotenv_values(ROOT / ".env"), **os.environ}
    base = config["DATABASE_URL"]
    report = {"pre_type_revision": PRE_TYPE_REVISION, "lifecycle": {},
              "migration_sha256": hashlib.sha256(MIGRATION.read_bytes()).hexdigest()}
    try:
        with ExitStack() as stack:
            fresh_url, old_url = (stack.enter_context(disposable(base, kind, report["lifecycle"])) for kind in ("fresh", "populated"))
            os.environ.update({k: str(v) for k, v in config.items() if v is not None and k != "DATABASE_URL"})
            os.environ["AUTH_COOKIE_SECURE"] = "false"
            os.environ["DATABASE_URL"] = old_url  # Imported fixture helpers also use the disposable target.
            with psycopg.connect(fresh_url) as c:
                initialize(c)
            with psycopg.connect(old_url, row_factory=dict_row) as c:
                populate(c)
                print("Populated both resource kinds and legacy saved searches", flush=True)
                report["before"] = snapshot(c)
                assert [v["rows"] for v in report["before"].values()] == [AGGREGATIONS, RECORDS, 2]
                last_event = c.execute("SELECT max(id) AS last FROM event_history").fetchone()["last"]
                report["legacy_content"] = preserved_content(c, last_event)
                assert report["legacy_content"]["history_rows"] > 100000
                assert report["legacy_content"]["published_translation"]["status"] == "published"
                report["storage_before"] = storage(c)
                c.commit()
                previous_grants = profile_grants(c)
                measure(c, old_url, report)
                access_migration = ROOT / "database/migrations/120_resource_type_access.sql"
                start = time.perf_counter()
                c.execute(access_migration.read_text(), prepare=False)
                c.commit()
                report["access_migration_seconds"] = time.perf_counter() - start
                report["access_migration_sha256"] = hashlib.sha256(access_migration.read_bytes()).hexdigest()
                grants = profile_grants(c)
                expected = {(profile, privilege)
                            for profile in ("INFO_GOV_MGR", "INFO_GOV_OFFICER", "ALL_PRIVS")
                            for privilege in ("records.administer", "aggregations.administer")}
                assert grants - previous_grants == expected and previous_grants <= grants
                report["new_profile_grants"] = sorted(expected)
                assert len(report["resource_index_builds"]) == 4
                report["storage_after"] = storage(c)
                report["after"] = snapshot(c)
                assert report["after"] == report["before"], "Existing row changed"
                assert all(old["heap_file"] == new["heap_file"] and old["heap_bytes"] == new["heap_bytes"]
                           for old, new in zip(report["storage_before"], report["storage_after"])), "Resource heap rewritten"
                report["new_data"] = c.execute("""
                    SELECT (SELECT count(type_id) FROM records) AS typed_records,
                           (SELECT count(type_id) FROM aggregations) AS typed_aggregations,
                           (SELECT count(*) FROM resource_type_values) AS field_values
                """).fetchone()
                assert all(v == 0 for v in report["new_data"].values())
                assert c.execute("SELECT count(*) AS n FROM schema_migrations WHERE version='119_resource_types'").fetchone()["n"] == 1
                measure_text_upgrade(c, report)
                assert preserved_content(c, last_event) == report["legacy_content"]
                report["preserved_legacy_content"] = True
                report["fresh_baseline_rejected_on_old_schema"] = True
                versions = c.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
                with psycopg.connect(fresh_url, row_factory=dict_row) as fresh_connection:
                    assert versions == fresh_connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version").fetchall()
                report["migration_versions"] = [r["version"] for r in versions]
                index_health = c.execute("""
                    SELECT count(*) AS indexes, bool_and(i.indisvalid AND i.indisready) AS valid
                    FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid
                    WHERE t.relnamespace='public'::regnamespace AND t.relname IN
                    ('records','aggregations','resource_types','resource_type_fields','resource_field_choices',
                     'resource_type_role_grants','resource_type_values','record_type_values','aggregation_type_values',
                     'record_search_documents','aggregation_search_documents')
                """).fetchone()
                assert index_health["indexes"] > 0 and index_health["valid"]
                report["index_health"] = index_health
                if args.broad_search:
                    c.execute("SELECT set_config('app.event_source','seeding',true)")
                    c.execute("""INSERT INTO resource_type_role_grants(kind,type_id,role_id,can_use)
                        SELECT t.kind,t.id,r.id,false FROM resource_types t CROSS JOIN roles r
                        WHERE t.name='Upgrade' AND r.code='PERF'""")
                    c.commit()
                    c.autocommit = True
                    c.execute("VACUUM ANALYZE")
                    report["benchmark"] = c.execute("""SELECT version() AS postgres,
                        pg_jit_available() AS jit_available, current_setting('work_mem') AS work_mem,
                        current_setting('effective_io_concurrency') AS effective_io_concurrency""").fetchone()
                    report["benchmark"].update(repeats=3, settle_seconds=args.settle_seconds, threshold_seconds=3)
            pg_dump = shutil.which("pg_dump")
            if not pg_dump:
                raise RuntimeError("pg_dump matching the server is required")
            fresh, upgraded = (dump_schema(url, pg_dump) for url in (fresh_url, old_url))
            report["schema_sha256"] = {key: hashlib.sha256(value.encode()).hexdigest()
                                       for key, value in (("fresh", fresh), ("upgraded", upgraded))}
            if fresh != upgraded:
                import difflib
                (args.output / "schema.diff").write_text("".join(difflib.unified_diff(
                    fresh.splitlines(True), upgraded.splitlines(True), "fresh", "upgraded")))
                raise AssertionError("Schema mismatch; see schema.diff")
            print("Full schema dumps and every existing resource/saved-search row match", flush=True)
            if args.broad_search:
                time.sleep(args.settle_seconds)
                buffered = BufferedOutput(args.output)
                try:
                    def check_saved(client, connection, repeats):
                        samples = verify_legacy_searches(client, connection, repeats)
                        report["legacy_saved_requests"] = samples
                        assert all(row["seconds"] <= 3 for row in samples)

                    exercise(buffered, 3, upgraded_reader_check=check_saved)
                finally:
                    buffered.flush()
    finally:
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
