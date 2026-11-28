"""CG-01/02/07/12/13/14/15 database-boundary foundations."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import json
import os
from pathlib import Path
from threading import Barrier, Event
import time
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest

from backend.services.api.code_generation import parse_pattern


ROOT = Path(__file__).resolve().parents[4]


def actor(connection, *, reason="", user=1):
    connection.execute(
        """SELECT set_config('app.user_id',%s,true),set_config('app.actor_type','user',true),
                  set_config('app.event_source','api',true),set_config('app.change_reason',%s,true)""",
        (str(user), reason),
    )


@pytest.fixture
def c():
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        actor(connection)
        try:
            yield connection
        finally:
            connection.rollback()


def generator(c, **changes):
    values = {
        "name": "Record codes", "kind": "record", "primary_field": "record_number",
        "pattern": "{SERIAL}", "start": 10, "increment": 10,
        "max_code_length": 64, **changes,
    }
    values.setdefault('applies_to','type' if values.get('type_id') is not None else 'all')
    return c.execute(sql.SQL("INSERT INTO code_generators ({}) VALUES ({}) RETURNING *").format(
        sql.SQL(",").join(map(sql.Identifier, values)),
        sql.SQL(",").join(sql.Placeholder() for _ in values),
    ), list(values.values())).fetchone()


def resource_type(c, name="Contract"):
    return c.execute("INSERT INTO resource_types(kind,name) VALUES('record',%s) RETURNING id", (f"{name}-{uuid4().hex}",)).fetchone()["id"]


def initialize_counter(c, generator_id):
    return c.execute(
        """INSERT INTO code_generator_counters(generator_id,scope_kind,scope_id,reset_frequency,period_bucket)
           VALUES(%s,'generator',0,'never','0001-01-01') RETURNING *""", (generator_id,),
    ).fetchone()


def test_creation_reason_optional_and_rename_is_audited_without_restarting(c):
    definition = generator(c)
    initialize_counter(c, definition["id"])
    c.execute("UPDATE code_generator_counters SET last_serial=10 WHERE generator_id=%s", (definition["id"],))
    created = c.execute("SELECT * FROM event_history WHERE entity_type='code_generator' AND entity_id=%s", (definition["id"],)).fetchone()
    assert created["reason"] is None
    assert created["after_state"]["name"] == "Record codes"
    assert created["after_state"]["start"] == "10"
    for reason in ("", " \t\n", "\u00a0\u2000"):
        actor(c, reason=reason)
        with pytest.raises(psycopg.errors.CheckViolation), c.transaction():
            c.execute("UPDATE code_generators SET name='Renamed' WHERE id=%s", (definition["id"],))
    actor(c, reason="Clarify the generator name")
    renamed = c.execute("UPDATE code_generators SET name='Finance record codes' WHERE id=%s RETURNING *", (definition["id"],)).fetchone()
    assert renamed["id"] == definition["id"] and renamed["version"] == 2
    assert c.execute("SELECT last_serial FROM code_generator_counters WHERE generator_id=%s", (definition["id"],)).fetchone()["last_serial"] == 10
    events = c.execute("SELECT * FROM event_history WHERE entity_type='code_generator' AND entity_id=%s ORDER BY id", (definition["id"],)).fetchall()
    assert len(events) == 2
    assert events[0]["after_state"]["name"] == "Record codes"
    assert events[1]["before_state"]["name"] == "Record codes"
    assert events[1]["after_state"]["name"] == "Finance record codes"
    assert events[1]["reason"] == "Clarify the generator name"


def test_optional_creation_reason_and_denied_direct_configuration(c):
    actor(c, reason="Explain the initial setup")
    row = generator(c)
    assert c.execute("SELECT reason FROM event_history WHERE entity_type='code_generator' AND entity_id=%s", (row["id"],)).fetchone()["reason"] == "Explain the initial setup"
    c.execute("SELECT set_config('app.user_id','',true)")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), c.transaction():
        generator(c, primary_field="title")


@pytest.mark.parametrize("changes", [
    {"name": "\u00a0 \t"}, {"primary_field": "medium"}, {"primary_field": "date_created"},
    {"primary_field": "destruction_number"}, {"start": -1}, {"start": "NaN"},
    {"increment": 0}, {"increment": "Infinity"}, {"padding_width": -1},
    {"pattern": "{{SERIAL}}"}, {"pattern": "{SERIAL}/{SERIAL}"},
    {"pattern": "{UNKNOWN}/{SERIAL}"}, {"reset_frequency": "monthly", "pattern": "{YYYY}/{SERIAL}"},
    {"scope": "org_unit"}, {"scope": "parent_aggregation"},
    {"scope": "classification", "pattern": "{CLASSIFICATION_CODE}/{SERIAL}"},
    {"max_code_length": 1}, {"primary_field": "assigned_location", "kind": "aggregation", "max_code_length": 201},
])
def test_database_rejects_invalid_definitions(c, changes):
    with pytest.raises(psycopg.IntegrityError), c.transaction():
        generator(c, **changes)


@pytest.mark.parametrize("left,right,rejected", [
    (None, None, True), (None, "Contract", True), ("Contract", None, True),
    ("Contract", "Contract", True), ("Contract", "Employee file", False),
])
def test_primary_overlap_examples_and_disabled_enabling(c, left, right, rejected):
    types = {name: resource_type(c, name) for name in {left, right} - {None}}
    generator(c, type_id=types.get(left))
    if rejected:
        with pytest.raises((psycopg.errors.UniqueViolation, psycopg.errors.ExclusionViolation)), c.transaction():
            generator(c, type_id=types.get(right))
        disabled = generator(c, type_id=types.get(right), enabled=False)
        actor(c, reason="Enable another generator")
        with pytest.raises((psycopg.errors.UniqueViolation, psycopg.errors.ExclusionViolation)), c.transaction():
            c.execute("UPDATE code_generators SET enabled=true WHERE id=%s", (disabled["id"],))
    else:
        generator(c, type_id=types[right])
    # Another field/kind is independent of this population overlap.
    generator(c, primary_field="title")
    generator(c, kind="aggregation", primary_field="aggregation_number")


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ"])
def test_simultaneous_first_bindings_cannot_create_all_type_overlap(c, isolation):
    type_id = resource_type(c)
    c.commit()
    ready = Barrier(2)

    def save(selected):
        try:
            with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as worker:
                worker.execute(sql.SQL("SET TRANSACTION ISOLATION LEVEL ") + sql.SQL(isolation))
                actor(worker)
                assert worker.execute("SELECT count(*) AS n FROM code_generators").fetchone()["n"] == 0
                ready.wait(timeout=10)
                generator(worker, type_id=selected)
            return "saved"
        except (psycopg.errors.UniqueViolation, psycopg.errors.ExclusionViolation, psycopg.errors.SerializationFailure):
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save, value) for value in (None, type_id)]
        assert sorted(f.result(timeout=20) for f in futures) == ["rejected", "saved"]
    assert c.execute("SELECT count(*) AS n FROM code_generators WHERE enabled").fetchone()["n"] == 1


@pytest.mark.parametrize("operation", ["enable", "retarget"])
def test_simultaneous_existing_definition_changes_cannot_overlap(c, operation):
    type_id = resource_type(c)
    first = generator(c,primary_field="title" if operation=="retarget" else "record_number",enabled=operation=="retarget")
    second = generator(c,primary_field="description" if operation=="retarget" else "record_number",type_id=type_id,enabled=operation=="retarget")
    c.commit()
    ready = Barrier(2)

    def change(identity):
        try:
            with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as worker:
                actor(worker,reason="Change the applicable field")
                worker.execute("SET LOCAL lock_timeout='8s'")
                ready.wait(timeout=5)
                worker.execute("UPDATE code_generators SET primary_field='record_number',enabled=true WHERE id=%s",(identity,))
            return "saved"
        except (psycopg.errors.UniqueViolation,psycopg.errors.ExclusionViolation):
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(change,row["id"]) for row in (first,second)]
        assert sorted(f.result(timeout=15) for f in futures) == ["rejected","saved"]
    assert c.execute("SELECT count(*) AS n FROM code_generators WHERE enabled AND primary_field='record_number'").fetchone()["n"] == 1


def test_text_binding_length_guards_unbinding_and_historical_names(c):
    type_id = resource_type(c)
    field_id = c.execute("""INSERT INTO resource_type_fields(kind,type_id,name,display_order,data_type,max_length)
                            VALUES('record',%s,'Employee code',1,'text',20) RETURNING id""", (type_id,)).fetchone()["id"]
    definition = generator(c, primary_field=None, type_id=type_id, field_id=field_id, max_code_length=20)
    initialize_counter(c, definition["id"])
    c.execute("UPDATE code_generator_counters SET last_serial=10 WHERE generator_id=%s", (definition["id"],))
    actor(c, reason="Change the field definition")
    for statement in (
        "UPDATE resource_type_fields SET max_length=10 WHERE id=%s",
        "UPDATE resource_type_fields SET data_type='integer',max_length=NULL WHERE id=%s",
        "DELETE FROM resource_type_fields WHERE id=%s",
    ):
        with pytest.raises(psycopg.IntegrityError), c.transaction():
            c.execute(statement, (field_id,))
    with pytest.raises(psycopg.IntegrityError), c.transaction():
        c.execute("UPDATE code_generators SET max_code_length=21 WHERE id=%s", (definition["id"],))
    c.execute("UPDATE code_generators SET field_id=NULL,type_id=NULL,enabled=false,applies_to='all' WHERE id=%s", (definition["id"],))
    c.execute("DELETE FROM resource_type_fields WHERE id=%s", (field_id,))
    assert c.execute("SELECT last_serial FROM code_generator_counters WHERE generator_id=%s", (definition["id"],)).fetchone()["last_serial"] == 10
    event = c.execute("SELECT after_state FROM event_history WHERE entity_type='code_generator' AND entity_id=%s AND operation='CREATE'", (definition["id"],)).fetchone()
    assert event["after_state"]["target_snapshot"]["field_name"] == "Employee code"
    with pytest.raises(psycopg.IntegrityError), c.transaction():
        c.execute("UPDATE code_generators SET enabled=true WHERE id=%s", (definition["id"],))


def test_sql_parser_matches_shared_renderer_parts(c):
    for pattern in ("{SERIAL}", "{{literal}}/{YYYY}/{SERIAL}", "{{{SERIAL}}}", "عقد-{ROLE_CODE}-{SERIAL}"):
        rows = c.execute("SELECT * FROM code_generator_parts(%s)", (pattern,)).fetchall()
        assert [(r["literal"], r["placeholder"]) for r in rows] == [(p.text, p.token) for p in parse_pattern(pattern)]
    for pattern in ("{SERIAL", "{UNKNOWN}", "{{SERIAL}}", "{SERIAL}-{SERIAL}"):
        with pytest.raises(psycopg.errors.CheckViolation), c.transaction():
            c.execute("SELECT * FROM code_generator_parts(%s)", (pattern,)).fetchall()


@pytest.mark.parametrize("isolation,error", [
    ("READ COMMITTED",psycopg.errors.CheckViolation),
    ("REPEATABLE READ",psycopg.errors.SerializationFailure),
    ("SERIALIZABLE",psycopg.errors.SerializationFailure),
])
def test_snapshot_field_edit_cannot_miss_committed_generator_maximum(c,isolation,error):
    type_id = resource_type(c)
    field_id = c.execute("""INSERT INTO resource_type_fields(kind,type_id,name,display_order,data_type,max_length)
                            VALUES('record',%s,'Race proof',1,'text',100) RETURNING id""", (type_id,)).fetchone()["id"]
    definition = generator(c,primary_field=None,type_id=type_id,field_id=field_id,max_code_length=20)
    c.commit()
    with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as earlier:
        earlier.execute(sql.SQL("SET TRANSACTION ISOLATION LEVEL ") + sql.SQL(isolation))
        actor(earlier,reason="Tighten the field length")
        assert earlier.execute("SELECT max_code_length FROM code_generators WHERE id=%s",(definition["id"],)).fetchone()["max_code_length"] == 20
        actor(c,reason="Increase the generator output limit")
        c.execute("UPDATE code_generators SET max_code_length=50 WHERE id=%s",(definition["id"],))
        c.commit()
        with pytest.raises(error):
            earlier.execute("UPDATE resource_type_fields SET max_length=30 WHERE id=%s",(field_id,))
        earlier.rollback()
    bounds = c.execute("""SELECT g.max_code_length,f.max_length FROM code_generators g
                          JOIN resource_type_fields f ON f.id=g.field_id WHERE g.id=%s""",(definition["id"],)).fetchone()
    assert bounds["max_code_length"] <= bounds["max_length"]


@pytest.mark.parametrize("isolation", ["READ COMMITTED","REPEATABLE READ","SERIALIZABLE"])
def test_compatible_field_increase_and_label_edit_keep_existing_transaction_modes(c,isolation):
    type_id = resource_type(c)
    field_id = c.execute("""INSERT INTO resource_type_fields(kind,type_id,name,display_order,data_type,max_length)
                            VALUES('record',%s,'Compatible changes',1,'text',50) RETURNING id""",(type_id,)).fetchone()["id"]
    definition = generator(c,primary_field=None,type_id=type_id,field_id=field_id,max_code_length=20)
    c.commit()
    with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as earlier:
        earlier.execute(sql.SQL("SET TRANSACTION ISOLATION LEVEL ") + sql.SQL(isolation))
        actor(earlier,reason="Increase field capacity")
        earlier.execute("SELECT max_code_length FROM code_generators WHERE id=%s",(definition["id"],)).fetchone()
        actor(c,reason="Increase the code limit")
        c.execute("UPDATE code_generators SET max_code_length=40 WHERE id=%s",(definition["id"],))
        c.commit()
        earlier.execute("UPDATE resource_type_fields SET max_length=100 WHERE id=%s",(field_id,))
        earlier.execute("UPDATE resource_type_fields SET name='Renamed',data_type='text',max_length=100 WHERE id=%s",(field_id,))
    assert c.execute("SELECT max_length,name FROM resource_type_fields WHERE id=%s",(field_id,)).fetchone() == {"max_length":100,"name":"Renamed"}


def test_counter_rollback_forward_adjustment_and_no_erasure(c):
    definition = generator(c)
    initialize_counter(c, definition["id"])
    for serial in (10, 20):
        c.execute("UPDATE code_generator_counters SET last_serial=%s WHERE generator_id=%s", (serial, definition["id"]))
    with pytest.raises(RuntimeError), c.transaction():
        c.execute("UPDATE code_generator_counters SET last_serial=30 WHERE generator_id=%s", (definition["id"],))
        raise RuntimeError("Roll back the entire attempted allocation")
    assert c.execute("SELECT last_serial FROM code_generator_counters WHERE generator_id=%s", (definition["id"],)).fetchone()["last_serial"] == 20
    for statement in ("UPDATE code_generator_counters SET last_serial=10", "DELETE FROM code_generator_counters", "TRUNCATE code_generator_counters"):
        with pytest.raises(psycopg.Error), c.transaction():
            c.execute(statement)
    with pytest.raises(psycopg.errors.CheckViolation), c.transaction():
        c.execute("UPDATE code_generator_counters SET forward_next=501 WHERE generator_id=%s", (definition["id"],))
    actor(c, reason="Continue the imported series")
    c.execute("UPDATE code_generator_counters SET forward_next=501 WHERE generator_id=%s", (definition["id"],))
    # An occupied explicitly selected candidate can be skipped by the increment.
    c.execute("UPDATE code_generator_counters SET last_serial=511,forward_next=NULL WHERE generator_id=%s", (definition["id"],))
    events = c.execute("SELECT operation,metadata FROM event_history WHERE entity_type='code_generator' AND entity_id=%s ORDER BY id", (definition["id"],)).fetchall()
    assert [e["operation"] for e in events] == ["CREATE", "NEXT_NUMBER_CHANGED"]
    assert events[1]["metadata"]["before"]["next_number"] == "30"
    assert events[1]["metadata"]["after"]["next_number"] == "501"


def test_scope_and_period_keys_remain_independent(c):
    definition = generator(c, scope="org_unit", pattern="{ORG_UNIT_CODE}/{YYYY}/{MM}/{SERIAL}", reset_frequency="monthly")
    for owner, month in ((1, date(2026,1,1)), (2, date(2026,1,1)), (1, date(2027,1,1))):
        c.execute("""INSERT INTO code_generator_counters(generator_id,scope_kind,scope_id,reset_frequency,period_bucket,last_serial)
                     VALUES(%s,'org_unit',%s,'monthly',%s,10)""", (definition["id"],owner,month))
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters WHERE generator_id=%s", (definition["id"],)).fetchone()["n"] == 3
    actor(c, reason="Change future scope settings")
    c.execute("UPDATE code_generators SET scope='generator',reset_frequency='never',enabled=false WHERE id=%s", (definition["id"],))
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters WHERE generator_id=%s", (definition["id"],)).fetchone()["n"] == 3


def test_audit_failure_rolls_back_definition_and_adjustment(c):
    definition = generator(c)
    initialize_counter(c, definition["id"])
    c.execute("""CREATE FUNCTION pg_temp.reject_code_generator_audit() RETURNS trigger LANGUAGE plpgsql AS $$
                 BEGIN RAISE EXCEPTION 'audit failure fixture'; END $$""")
    c.execute("""CREATE TRIGGER reject_code_generator_audit BEFORE INSERT ON event_history
                 FOR EACH ROW WHEN (NEW.entity_type='code_generator') EXECUTE FUNCTION pg_temp.reject_code_generator_audit()""")
    actor(c, reason="Audited edit")
    for statement in (
        "UPDATE code_generators SET name='Must roll back' WHERE id=%s",
        "UPDATE code_generator_counters SET forward_next=501 WHERE generator_id=%s",
    ):
        with pytest.raises(psycopg.errors.RaiseException, match="audit failure fixture"), c.transaction():
            c.execute(statement, (definition["id"],))
    assert c.execute("SELECT name,version FROM code_generators WHERE id=%s", (definition["id"],)).fetchone() == {"name":"Record codes","version":1}
    assert c.execute("SELECT forward_next,version FROM code_generator_counters WHERE generator_id=%s", (definition["id"],)).fetchone() == {"forward_next":None,"version":1}
    c.execute("DROP TRIGGER reject_code_generator_audit ON event_history")


def test_completed_request_identity_survives_resource_deletion(c, client, record):
    key = uuid4()
    result = {"kind":"record","resource_ids":[record["id"]],"response":record}
    # Store only JSON-native wire values, including the response's ISO dates.
    c.execute("""INSERT INTO resource_creation_requests(caller_user_id,operation,submission_key,fingerprint,result)
                 VALUES(1,'record.create',%s,%s,%s)""", (key,"a"*64,Jsonb(result)))
    c.commit()
    removed = client.delete(f"/api/v1/records/{record['id']}", headers={"If-Match":str(record["version"])})
    assert removed.status_code == 204, removed.text
    assert c.execute("SELECT result FROM resource_creation_requests WHERE submission_key=%s", (key,)).fetchone()["result"] == result
    with pytest.raises(psycopg.errors.UniqueViolation), c.transaction():
        c.execute("""INSERT INTO resource_creation_requests(caller_user_id,operation,submission_key,fingerprint,result)
                     VALUES(1,'record.create',%s,%s,'{}')""", (key,"b"*64))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), c.transaction():
        c.execute("DELETE FROM resource_creation_requests WHERE submission_key=%s", (key,))


@pytest.mark.skipif(not os.environ.get("ERMS_TEST_DEFERRED_MIGRATIONS"), reason="requires populated upgrade runner")
def test_populated_generator_upgrade_is_atomic_and_preserves_records_and_drafts(client):
    migration = Path(os.environ["ERMS_TEST_DEFERRED_MIGRATIONS"])
    assert migration.name == "126_custom_code_generators.sql"
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection:
        # Populate the old schema directly. The upgraded creation API correctly
        # requires its new schema, so it cannot be used to seed a pre-upgrade DB.
        actor(connection)
        connection.execute("SELECT set_config('app.creator_acl_role_id','1',true)")
        parent=connection.execute("""INSERT INTO aggregations(aggregation_number,title,classification_id,medium,owning_org_unit_id)
            SELECT 'UPGRADE-ROOT','Upgrade parent',1,'digital',org_unit_id FROM roles WHERE id=1 RETURNING id""").fetchone()["id"]
        record=connection.execute("""INSERT INTO records(aggregation_id,record_number,title,medium)
            VALUES(%s,'UPGRADE-RECORD','Existing upgrade record','digital') RETURNING *""",(parent,)).fetchone()
        draft=connection.execute("""INSERT INTO record_drafts(owner_user_id,aggregation_id,title,medium)
            VALUES(1,%s,'Unfinished upgrade proof','digital') RETURNING *""",(parent,)).fetchone()
        old_function=connection.execute("SELECT pg_get_functiondef('disposition_private.minimize_unit_history(bigint,bigint)'::regprocedure) AS body").fetchone()["body"]
        connection.execute("""CREATE FUNCTION pg_temp.reject_generator_upgrade_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
                            BEGIN RAISE EXCEPTION 'receipt failure fixture'; END $$""")
        connection.execute("""CREATE TRIGGER reject_generator_upgrade_receipt BEFORE INSERT ON schema_migrations
                             FOR EACH ROW WHEN (NEW.version='126_custom_code_generators') EXECUTE FUNCTION pg_temp.reject_generator_upgrade_receipt()""")
        connection.commit()
        with pytest.raises(psycopg.errors.RaiseException, match="receipt failure fixture"):
            connection.execute(migration.read_text(), prepare=False)
        connection.rollback()
        assert connection.execute("SELECT to_regclass('public.code_generators') AS table").fetchone()["table"] is None
        assert not connection.execute("SELECT 1 FROM schema_migrations WHERE version='126_custom_code_generators'").fetchone()
        assert connection.execute("SELECT pg_get_functiondef('disposition_private.minimize_unit_history(bigint,bigint)'::regprocedure) AS body").fetchone()["body"]==old_function
        connection.execute("DROP TRIGGER reject_generator_upgrade_receipt ON schema_migrations")
        connection.commit()
        before = connection.execute("SELECT pg_database_size(current_database()) AS bytes").fetchone()["bytes"]
        connection.commit()
        ready = Event()
        identity = []

        def upgrade():
            started = time.perf_counter()
            with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as worker:
                identity.append(worker.info.backend_pid)
                ready.set()
                worker.execute(migration.read_text(),prepare=False)
            return time.perf_counter()-started

        with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as blocker:
            blocker.execute("SELECT id FROM record_drafts WHERE id=%s FOR SHARE",(draft["id"],)).fetchone()
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(upgrade)
                assert ready.wait(timeout=5)
                deadline = time.monotonic()+8
                while time.monotonic()<deadline:
                    waiting = connection.execute("""SELECT wait_event_type,wait_event,pg_blocking_pids(pid) AS blockers
                        FROM pg_stat_activity WHERE pid=%s""",(identity[0],)).fetchone()
                    if waiting and blocker.info.backend_pid in waiting["blockers"]:
                        break
                    connection.commit()
                    time.sleep(.01)
                else:
                    blocker.commit()
                    pytest.fail("Upgrade never demonstrated the draft-table DDL lock")
                blocker.commit()
                elapsed = pending.result(timeout=15)
        assert connection.execute("SELECT count(*) AS n FROM code_generators").fetchone()["n"] == 0
        assert connection.execute("SELECT generation_intent FROM record_drafts WHERE id=%s", (draft["id"],)).fetchone()["generation_intent"] == {}
        assert connection.execute("SELECT * FROM records WHERE id=%s",(record["id"],)).fetchone()==record
        assert connection.execute("SELECT * FROM record_drafts WHERE id=%s",(draft["id"],)).fetchone()=={**draft,"generation_intent":{}}
        after = connection.execute("SELECT pg_database_size(current_database()) AS bytes").fetchone()["bytes"]
        sizes = connection.execute("""SELECT name,pg_total_relation_size(name::regclass) AS bytes
            FROM unnest(ARRAY['code_generators','code_generator_counters','resource_creation_requests','record_drafts']) name""").fetchall()
        evidence = ROOT / ".runtime/custom-code-generators/upgrade-metrics"
        evidence.mkdir(parents=True,exist_ok=True)
        (evidence / f"{connection.info.dbname}.json").write_text(json.dumps({"database_bytes_before":before,
            "database_bytes_after":after,"relation_sizes":sizes,"migration_seconds_including_deliberate_lock_wait":elapsed,
            "observed_ddl_wait":waiting,"records":1,"drafts":1},indent=2)+"\n")
    assert client.get(f"/api/v1/records/{record['id']}").json()["record_number"]==record["record_number"]
    preserved = client.get(f"/api/v1/record-drafts/{draft['id']}").json()
    assert preserved["title"] == draft["title"] and preserved["record_number"] is None
