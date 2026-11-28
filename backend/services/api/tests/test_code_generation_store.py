"""Exercise actual transactional primitives before wiring creation adapters."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Barrier, Event
import time
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest

from backend.services.api.code_generation import CodeGenerationError, GenerationContext, counter_key
from backend.services.api.code_generation_store import (
    CreationSubmission, advance_counter, allocate_locked, lock_counters, lock_creation_bindings,
    read_counter, read_definition, submission_fingerprint,
)
from .test_code_generator_database import actor, c, generator


def evidence(connection, name, values):
    directory = Path(__file__).resolve().parents[4] / ".runtime/custom-code-generators/allocation-metrics"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{connection.info.dbname}-{name}.json").write_text(json.dumps(values, indent=2, default=str) + "\n")


class QueryEvidence:
    """Capture the actual occupancy SQL, without production instrumentation."""
    def __init__(self, connection):
        self.connection = connection
        self.queries = []

    def execute(self, statement, parameters=None):
        query = statement.as_string(self.connection) if hasattr(statement, "as_string") else statement
        if query.startswith("WITH candidates AS MATERIALIZED"):
            self.queries.append((query, parameters))
        return self.connection.execute(statement, parameters)


def context(aggregation):
    return GenerationContext(
        instant=datetime(2026,11,26,tzinfo=timezone.utc), working_timezone="Asia/Dubai",
        parent_aggregation_id=aggregation["id"], parent_aggregation_number=aggregation["aggregation_number"],
        classification_id=1, classification_code="TEST-01", classification_scheme_code="TEST",
        org_unit_id=aggregation["owning_org_unit_id"], org_unit_code="test-root", role_code="system-administrator",
    )


def bindings(connection, aggregation, primary="record_number"):
    definition = next(g for g in lock_creation_bindings(connection,"record",None) if g.primary_field==primary)
    current = context(aggregation)
    key = counter_key(definition.config,current)
    state = lock_counters(connection,[(definition,key)])[definition.id,key]
    return definition,current,state


def insert_record(connection, aggregation, number, title="Transactional proof"):
    connection.execute("SELECT set_config('app.creator_acl_role_id','1',true)")
    return connection.execute(
        "INSERT INTO records(aggregation_id,record_number,title,medium) VALUES(%s,%s,%s,%s) RETURNING id",
        (aggregation["id"],number,title,aggregation["medium"]),
    ).fetchone()["id"]


def test_resource_failure_rolls_back_first_counter_and_success_allocates_start(c, aggregation):
    definition = generator(c, pattern="G{SERIAL}")
    c.commit()
    with pytest.raises(RuntimeError):
        with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as attempt:
            actor(attempt)
            locked,ctx,state = bindings(attempt,aggregation)
            value,_ = allocate_locked(attempt,locked,ctx,state)
            insert_record(attempt,aggregation,value)
            raise RuntimeError("Final creation failed")
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters WHERE generator_id=%s", (definition["id"],)).fetchone()["n"] == 0
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 0
    actor(c)
    locked,ctx,state = bindings(c,aggregation)
    value,state = allocate_locked(c,locked,ctx,state)
    assert value == "G10"
    insert_record(c,aggregation,value)
    assert state.last_serial == 10


@pytest.mark.parametrize("width", [0,4,8])
def test_many_occupied_codes_are_skipped_without_filling_old_gaps(c, aggregation, width):
    generator(c, pattern="A{SERIAL}/Z", padding_width=width)
    c.execute("SELECT set_config('app.creator_acl_role_id','1',true)")
    c.execute("""INSERT INTO records(aggregation_id,record_number,title,medium)
                 SELECT %s,'A'||lpad((n*10)::text,greatest(%s,char_length((n*10)::text)),'0')||'/Z',
                        'Imported numbered record',%s FROM generate_series(1,1500) n""",
              (aggregation["id"],width,aggregation["medium"]))
    locked,ctx,state = bindings(c,aggregation)
    captured = QueryEvidence(c)
    started = time.perf_counter()
    value,state = allocate_locked(captured,locked,ctx,state)
    elapsed = time.perf_counter() - started
    assert value == "A" + "15010".zfill(width) + "/Z"
    assert len(captured.queries) == 1
    query,parameters = captured.queries[0]
    plan = c.execute("EXPLAIN (ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) " + query,parameters).fetchone()["QUERY PLAN"]
    evidence(c,f"occupied-width-{width}", {"records":1500,"occupied_candidate":"A"+"10".zfill(width)+"/Z",
        "expected_available":value,"allocation_seconds":elapsed,"sql":query,"parameters":parameters,"plan":plan})
    insert_record(c,aggregation,value)
    # A deliberately different zero representation does not occupy our code.
    insert_record(c,aggregation,"A0"+"15020".zfill(width)+"/Z")
    old = "A" + "20".zfill(width) + "/Z"
    c.execute("DELETE FROM records WHERE record_number=%s",(old,))
    next_value,state = allocate_locked(c,locked,ctx,state)
    assert next_value == "A" + "15020".zfill(width) + "/Z"
    assert state.last_serial == 15020


def test_zero_serial_with_padding_is_occupied_and_skipped(c, aggregation):
    generator(c,pattern="Z{SERIAL}",start=0,padding_width=8)
    insert_record(c,aggregation,"Z00000000")
    locked,ctx,state=bindings(c,aggregation)
    value,state=allocate_locked(c,locked,ctx,state)
    assert value=="Z00000010" and state.last_serial==10


def test_chosen_number_is_exact_or_conflicts_without_advancing(c, aggregation):
    generator(c, pattern="G{SERIAL}")
    insert_record(c,aggregation,"G10")
    locked,ctx,state = bindings(c,aggregation)
    value,state = allocate_locked(c,locked,ctx,state,chosen_code="G20")
    assert value == "G20"
    insert_record(c,aggregation,value)
    insert_record(c,aggregation,"G30")
    with pytest.raises(CodeGenerationError,match="code_generator_recommendation_conflict"),c.transaction():
        allocate_locked(c,locked,ctx,state,chosen_code="G30")
    assert c.execute("SELECT last_serial FROM code_generator_counters WHERE generator_id=%s",(locked.id,)).fetchone()["last_serial"] == 20
    value,state = allocate_locked(c,locked,ctx,state)
    assert value == "G40"


def test_wrong_scope_context_cannot_use_a_locked_counter(c, aggregation):
    generator(c,scope="parent_aggregation",pattern="{PARENT_AGGREGATION_NUMBER}/{SERIAL}")
    locked,ctx,state = bindings(c,aggregation)
    with pytest.raises(CodeGenerationError),c.transaction():
        allocate_locked(c,locked,replace(ctx,parent_aggregation_id=ctx.parent_aggregation_id+1),state)
    assert c.execute("SELECT last_serial FROM code_generator_counters WHERE generator_id=%s",(locked.id,)).fetchone()["last_serial"] is None


def test_same_counter_first_use_is_atomic_across_workers(c, aggregation):
    definition = generator(c,pattern="C{SERIAL}")
    c.commit()

    def create(_):
        started = time.perf_counter()
        with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as worker:
            actor(worker)
            locked,ctx,state = bindings(worker,aggregation)
            value,_ = allocate_locked(worker,locked,ctx,state)
            insert_record(worker,aggregation,value)
        return value,time.perf_counter()-started

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as executor:
        measurements = list(executor.map(create,range(8)))
    elapsed = time.perf_counter()-started
    values = [value for value,_ in measurements]
    evidence(c,"same-counter",{"workers":4,"creations":8,"elapsed_seconds":elapsed,
        "committed_connection_seconds":measurements,"scope":"transaction primitives; not HTTP latency"})
    assert sorted(int(value[1:]) for value in values) == list(range(10,81,10))
    assert c.execute("SELECT last_serial FROM code_generator_counters WHERE generator_id=%s",(definition["id"],)).fetchone()["last_serial"] == 80
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 8


def test_reverse_input_order_locks_multiple_counters_consistently(c, aggregation):
    generator(c,pattern="N{SERIAL}")
    generator(c,primary_field="title",pattern="T{SERIAL}")
    c.commit()
    barrier = Barrier(2)

    def create(reverse):
        with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as worker:
            actor(worker)
            worker.execute("SET LOCAL lock_timeout='8s'")
            definitions = lock_creation_bindings(worker,"record",None)
            ctx = context(aggregation)
            desired = [(g,counter_key(g.config,ctx)) for g in definitions]
            barrier.wait(timeout=5)
            states = lock_counters(worker,desired[::-1] if reverse else desired)
            values = {g.primary_field:allocate_locked(worker,g,ctx,states[g.id,key])[0] for g,key in desired}
            insert_record(worker,aggregation,values["record_number"],values["title"])
        return values

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create,reverse) for reverse in (False,True)]
        values = [future.result(timeout=15) for future in futures]
    assert sorted((v["record_number"],v["title"]) for v in values) == [("N10","T10"),("N20","T20")]


def test_forward_adjustment_of_unused_bucket_is_versioned_and_other_buckets_unchanged(c, aggregation):
    row = generator(c,scope="parent_aggregation",pattern="{PARENT_AGGREGATION_NUMBER}/{SERIAL}")
    definition = read_definition(c,row["id"])
    key = counter_key(definition.config,context(aggregation))
    assert read_counter(c,definition.id,replace(key,scope_id=key.scope_id+1)).version == 0
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"] == 0
    other_key = replace(key,scope_id=key.scope_id+1)
    actor(c,reason="Continue the imported series")
    other = advance_counter(c,definition.id,other_key,"501",expected_version=0)
    assert other.forward_next == 501 and other.version == 1
    assert read_counter(c,definition.id,key).last_serial is None
    with pytest.raises(CodeGenerationError,match="code_generator_stale_version"),c.transaction():
        advance_counter(c,definition.id,other_key,"601",expected_version=0)
    with pytest.raises(CodeGenerationError,match="code_generator_backward_adjustment"),c.transaction():
        advance_counter(c,definition.id,other_key,"500",expected_version=1)
    updated = advance_counter(c,definition.id,other_key,"601",expected_version=1)
    assert updated.version == 2
    events = c.execute("SELECT metadata FROM event_history WHERE entity_type='code_generator' AND operation='NEXT_NUMBER_CHANGED' ORDER BY id").fetchall()
    assert len(events) == 2
    assert events[0]["metadata"]["before"]["next_number"] == "10"
    assert events[0]["metadata"]["after"]["next_number"] == "501"
    assert events[1]["metadata"]["after"]["next_number"] == "601"


def test_configuration_change_waits_for_allocation_and_next_creation_uses_new_increment(c, aggregation):
    row = generator(c,pattern="G{SERIAL}")
    c.commit()
    actor(c)
    definition,ctx,state = bindings(c,aggregation)
    ready = Event()
    identity = []

    def change():
        with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as worker:
            actor(worker,reason="Increase the increment for future creations")
            worker.execute("SET LOCAL lock_timeout='8s'")
            identity.append(worker.info.backend_pid)
            ready.set()
            worker.execute("UPDATE code_generators SET increment=100 WHERE id=%s",(row["id"],))

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(change)
        assert ready.wait(timeout=5)
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            blockers = c.execute("SELECT pg_blocking_pids(%s) AS ids",(identity[0],)).fetchone()["ids"]
            if c.info.backend_pid in blockers:
                break
            time.sleep(.01)
        else:
            pytest.fail("Configuration writer never waited on the creation binding guard")
        value,_ = allocate_locked(c,definition,ctx,state)
        assert value == "G10"
        insert_record(c,aggregation,value)
        c.commit()
        pending.result(timeout=10)
    actor(c)
    definition,ctx,state = bindings(c,aggregation)
    value,_ = allocate_locked(c,definition,ctx,state)
    assert value == "G110"


def test_multi_field_failure_rolls_back_all_counters_and_resource(c, aggregation):
    generator(c,pattern="N{SERIAL}")
    generator(c,primary_field="title",pattern="T{SERIAL}")
    with pytest.raises(RuntimeError),c.transaction():
        definitions = lock_creation_bindings(c,"record",None)
        ctx = context(aggregation)
        desired = [(g,counter_key(g.config,ctx)) for g in definitions]
        states = lock_counters(c,desired)
        values = {g.primary_field:allocate_locked(c,g,ctx,states[g.id,key])[0] for g,key in desired}
        insert_record(c,aggregation,values["record_number"],values["title"])
        raise RuntimeError("Final component persistence failed")
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 0
    assert c.execute("SELECT count(*) AS n FROM code_generator_counters").fetchone()["n"] == 0


def test_two_adjustments_of_the_same_unused_bucket_have_one_winner(c, aggregation):
    row = generator(c,pattern="G{SERIAL}")
    definition = read_definition(c,row["id"])
    key = counter_key(definition.config,context(aggregation))
    c.commit()
    barrier = Barrier(2)

    def adjust(value):
        with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as worker:
            actor(worker,reason="Continue the imported sequence")
            barrier.wait(timeout=5)
            try:
                result = advance_counter(worker,row["id"],key,value,expected_version=0)
                return result.forward_next
            except CodeGenerationError as error:
                assert error.code == "code_generator_stale_version"
                worker.rollback()
                return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(adjust,value) for value in (501,601)]
        values = [future.result(timeout=10) for future in futures]
    assert values.count(None) == 1
    assert read_counter(c,row["id"],key).forward_next in (501,601)
    assert c.execute("SELECT count(*) AS n FROM event_history WHERE operation='NEXT_NUMBER_CHANGED'").fetchone()["n"] == 1


def test_independent_counter_can_finish_while_another_is_locked(c, aggregation):
    first = generator(c,pattern="G{SERIAL}")
    second = generator(c,primary_field="title",pattern="T{SERIAL}")
    c.commit()

    def create_other():
        with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as worker:
            actor(worker)
            locked,ctx,state = bindings(worker,aggregation,primary="title")
            value,_ = allocate_locked(worker,locked,ctx,state)
            insert_record(worker,aggregation,"MANUAL-1",value)
            return value

    with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as blocker:
        actor(blocker)
        locked,ctx,state = bindings(blocker,aggregation)
        assert locked.id == first["id"]
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(create_other).result(timeout=10) == "T10"
    assert c.execute("SELECT last_serial FROM code_generator_counters WHERE generator_id=%s",(second["id"],)).fetchone()["last_serial"] == 10


def test_concurrent_submissions_replay_one_completed_result(c, aggregation):
    generator(c,pattern="R{SERIAL}")
    c.commit()
    key = uuid4()

    def create():
        with psycopg.connect(os.environ["DATABASE_URL"],row_factory=dict_row) as worker:
            actor(worker)
            fingerprint = submission_fingerprint(worker,"record.create",'{"title":"Retry proof"}',route={"aggregation_id":aggregation["id"]})
            submission = CreationSubmission.lock(worker,"record.create",key,fingerprint)
            if submission.completed_result is not None:
                return submission.completed_result
            locked,ctx,state = bindings(worker,aggregation)
            value,_ = allocate_locked(worker,locked,ctx,state)
            rid = insert_record(worker,aggregation,value,"Retry proof")
            result = {"kind":"record","resource_ids":[rid],"response":{"id":rid,"record_number":value}}
            submission.complete(worker,result)
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    assert results[0] == results[1]
    assert results[0]["response"]["record_number"] == "R10"
    assert c.execute("SELECT count(*) AS n FROM records").fetchone()["n"] == 1
    actor(c)
    different = submission_fingerprint(c,"record.create",'{"title":"Changed input"}',route={"aggregation_id":aggregation["id"]})
    with pytest.raises(CodeGenerationError,match="creation_submission_conflict"),c.transaction():
        CreationSubmission.lock(c,"record.create",key,different)


def test_fingerprints_preserve_exact_json_numbers_and_ignore_object_key_order(c):
    precise = '{"a":900719925474099312345,"b":0.1234567890123456789012345}'
    reordered = '{"b":0.1234567890123456789012345,"a":900719925474099312345}'
    rounded = '{"a":900719925474099312344,"b":0.1234567890123456789012345}'
    first = submission_fingerprint(c,"record.create",precise,route={})
    assert first == submission_fingerprint(c,"record.create",reordered,route={})
    assert first != submission_fingerprint(c,"record.create",rounded,route={})
