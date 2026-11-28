"""Transactional generator primitives; callers own authorization and commit.

All methods use the supplied connection. They never commit, open a second
connection or wait for uploads. Creation adapters must resolve their existing
resource/type/role rules before acquiring these locks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID

from psycopg import Connection, sql
from psycopg.types.json import Jsonb

from .code_generation import (
    CodeGenerationError, CounterKey, GenerationContext, GeneratorConfig,
    RESETS, SCOPES, code_affixes, counter_key, next_serial, render, whole_number,
)


PRIMARY_TEXT_FIELDS = {
    "record": ("record_number", "title", "description"),
    "aggregation": ("aggregation_number", "title", "description", "assigned_location", "current_location"),
}


@dataclass(frozen=True)
class LockedGenerator:
    id: int
    kind: str
    primary_field: str | None
    field_id: int | None
    type_id: int | None
    version: int
    config: GeneratorConfig


def read_definition(connection: Connection, generator_id: int, *, for_adjustment: bool = False) -> LockedGenerator:
    """Read one definition; adjustments freeze it before locking a counter.

    Creation must use lock_creation_bindings instead. Taking a definition row
    lock after a binding guard would invert the configuration-writer order.
    """
    statement = """SELECT g.*,f.max_length AS field_max_length FROM code_generators g
                   LEFT JOIN resource_type_fields f ON f.id=g.field_id WHERE g.id=%s"""
    if for_adjustment:
        statement += " FOR SHARE OF g"
    row = connection.execute(statement, (generator_id,)).fetchone()
    if row is None:
        raise CodeGenerationError("code_generator_not_found")
    return LockedGenerator(
        row["id"], row["kind"], row["primary_field"], row["field_id"], row["type_id"], row["version"],
        GeneratorConfig.from_mapping(
            row, globally_unique_number=row["primary_field"] in {"record_number", "aggregation_number"},
            field_max_length=row["field_max_length"] if row["field_id"] is not None else
                200 if row["primary_field"] in {"assigned_location", "current_location"} else None,
        ),
    )


def lock_creation_bindings(connection: Connection, kind: str, type_id: int | None) -> list[LockedGenerator]:
    if kind not in PRIMARY_TEXT_FIELDS:
        raise CodeGenerationError("code_generator_invalid", field="kind")
    fields = connection.execute(
        """SELECT id,data_type,max_length FROM resource_type_fields
           WHERE kind=%s AND type_id=%s ORDER BY id FOR SHARE""", (kind, type_id),
    ).fetchall()
    targets = [{"kind": kind, "primary_field": name, "field_id": None}
               for name in PRIMARY_TEXT_FIELDS[kind]]
    targets.extend({"kind": kind, "primary_field": None, "field_id": field["id"]}
                   for field in fields if field["data_type"] == "text")
    keys = connection.execute(
        """SELECT DISTINCT code_generator_binding_key(kind,primary_field,field_id) AS key
           FROM jsonb_to_recordset(%s::jsonb) AS target(kind text,primary_field text,field_id bigint)
           ORDER BY key""", (Jsonb(targets),),
    ).fetchall()
    # Pipeline in a stable order; do not rely on evaluation order of a SELECT
    # target-list function relative to its ORDER BY.
    with connection.cursor() as cursor:
        cursor.executemany("SELECT pg_advisory_xact_lock_shared(%s)", [(row["key"],) for row in keys])
    definitions = connection.execute(
        """SELECT * FROM code_generators WHERE kind=%s AND enabled
           AND type_population @> coalesce(%s::bigint,0) ORDER BY id""", (kind, type_id),
    ).fetchall()
    lengths = {field["id"]: field["max_length"] for field in fields}
    return [LockedGenerator(
        row["id"], row["kind"], row["primary_field"], row["field_id"], row["type_id"], row["version"],
        GeneratorConfig.from_mapping(
            row, globally_unique_number=row["primary_field"] in {"record_number", "aggregation_number"},
            field_max_length=lengths.get(row["field_id"]) if row["field_id"] is not None else
                200 if row["primary_field"] in {"assigned_location", "current_location"} else None,
        ),
    ) for row in definitions]


@dataclass(frozen=True)
class CounterState:
    key: CounterKey
    last_serial: Decimal | None
    forward_next: Decimal | None
    version: int


def read_counter(
    connection: Connection, generator_id: int, key: CounterKey, *, for_update: bool = False,
) -> CounterState:
    """Read-only peeks return version zero for an unused normalized bucket."""
    if (key.scope_kind not in SCOPES or key.reset_frequency not in RESETS
        or isinstance(key.scope_id, bool) or not isinstance(key.scope_id, int)
        or (key.scope_id != 0 if key.scope_kind == "generator" else key.scope_id <= 0)
        or not isinstance(key.period_bucket, date) or isinstance(key.period_bucket, datetime)
        or (key.reset_frequency == "never" and key.period_bucket != date(1, 1, 1))
        or (key.reset_frequency == "yearly" and (key.period_bucket.month, key.period_bucket.day) != (1, 1))
        or (key.reset_frequency == "monthly" and key.period_bucket.day != 1)):
        raise CodeGenerationError("code_generator_invalid", field="counter")
    statement = """SELECT last_serial,forward_next,version FROM code_generator_counters
                   WHERE generator_id=%s AND scope_kind=%s AND scope_id=%s AND reset_frequency=%s AND period_bucket=%s"""
    if for_update:
        statement += " FOR UPDATE"
    row = connection.execute(statement, (generator_id, key.scope_kind, key.scope_id, key.reset_frequency, key.period_bucket)).fetchone()
    return CounterState(key, row["last_serial"], row["forward_next"], row["version"]) if row else CounterState(key, None, None, 0)


def advance_counter(
    connection: Connection, generator_id: int, key: CounterKey, next_number: Any, *, expected_version: int,
) -> CounterState:
    """Advance one selected bucket; the database enforces authority and reason."""
    definition = read_definition(connection, generator_id, for_adjustment=True)
    state = read_counter(connection, generator_id, key, for_update=True)
    if expected_version != state.version:
        raise CodeGenerationError("code_generator_stale_version")
    value = whole_number(next_number, "next_number")
    if value <= next_serial(definition.config, state.last_serial, state.forward_next):
        raise CodeGenerationError("code_generator_backward_adjustment")
    parameters = (generator_id, key.scope_kind, key.scope_id, key.reset_frequency, key.period_bucket)
    if state.version == 0:
        row = connection.execute(
            """INSERT INTO code_generator_counters(generator_id,scope_kind,scope_id,reset_frequency,period_bucket,forward_next)
               VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING version""", (*parameters, value),
        ).fetchone()
    else:
        row = connection.execute(
            """UPDATE code_generator_counters SET forward_next=%s
               WHERE generator_id=%s AND scope_kind=%s AND scope_id=%s AND reset_frequency=%s AND period_bucket=%s
                 AND version=%s RETURNING version""", (value, *parameters, expected_version),
        ).fetchone()
    if row is None:
        raise CodeGenerationError("code_generator_stale_version")
    return CounterState(key, state.last_serial, value, row["version"])


def lock_counters(
    connection: Connection, desired: list[tuple[LockedGenerator, CounterKey]],
) -> dict[tuple[int, CounterKey], CounterState]:
    keys = sorted({(g.id, key.scope_kind, key.scope_id, key.reset_frequency, key.period_bucket)
                   for g, key in desired})
    if not keys:
        return {}
    with connection.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO code_generator_counters(generator_id,scope_kind,scope_id,reset_frequency,period_bucket)
               VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", keys,
        )
    requested = [{"generator_id": gid, "scope_kind": scope, "scope_id": identity,
                  "reset_frequency": reset, "period_bucket": bucket.isoformat()}
                 for gid, scope, identity, reset, bucket in keys]
    rows = connection.execute(
        """SELECT counter.* FROM code_generator_counters counter
           JOIN jsonb_to_recordset(%s::jsonb) AS requested(generator_id bigint,scope_kind text,scope_id bigint,
                reset_frequency text,period_bucket date)
           USING(generator_id,scope_kind,scope_id,reset_frequency,period_bucket)
           ORDER BY generator_id,scope_kind,scope_id,reset_frequency,period_bucket FOR UPDATE OF counter""",
        (Jsonb(requested),),
    ).fetchall()
    result = {}
    for row in rows:
        key = CounterKey(row["scope_kind"], row["scope_id"], row["reset_frequency"], row["period_bucket"])
        result[row["generator_id"], key] = CounterState(key, row["last_serial"], row["forward_next"], row["version"])
    return result


def available_serial(
    connection: Connection, definition: LockedGenerator, context: GenerationContext, candidate: Decimal,
) -> Decimal:
    """Find the first unoccupied forward candidate; never mutate a counter."""
    column = definition.primary_field
    if column not in {"record_number", "aggregation_number"}:
        return candidate
    table = "records" if definition.kind == "record" else "aggregations"
    code = render(definition.config, context, candidate)
    if not connection.execute(sql.SQL("SELECT EXISTS(SELECT FROM {} WHERE {}=%s) AS occupied").format(
        sql.Identifier(table), sql.Identifier(column)), (code,),
    ).fetchone()["occupied"]:
        return candidate
    prefix, suffix = code_affixes(definition.config, context)
    statement = sql.SQL("""WITH candidates AS MATERIALIZED (
        SELECT {column} AS code,substring({column} FROM %(begin)s
             FOR greatest(0,char_length({column})-%(affixes)s)) AS digits
        FROM {table} WHERE left({column},%(prefix_size)s)=%(prefix)s
           AND right({column},%(suffix_size)s)=%(suffix)s
           AND char_length({column})>%(affixes)s
    ), bound AS (
        SELECT %(start)s::numeric+%(step)s::numeric*(count(*)+1) AS upper FROM candidates
    ), parsed AS (
        SELECT code,CASE WHEN digits COLLATE "C" ~ '^[0-9]+$'
             AND char_length(ltrim(digits,'0'))<=char_length(trunc(upper)::text)
             THEN coalesce(nullif(ltrim(digits,'0'),''),'0')::numeric END AS n
        FROM candidates CROSS JOIN bound
    ), occupied AS (
        SELECT DISTINCT n FROM parsed CROSS JOIN bound
        WHERE n>=%(start)s::numeric AND n<=upper AND mod(n-%(start)s::numeric,%(step)s::numeric)=0
          AND code=%(prefix)s || lpad(trunc(n)::text,greatest(%(width)s,char_length(trunc(n)::text)),'0') || %(suffix)s
        UNION SELECT %(start)s::numeric-%(step)s::numeric
    ), spans AS (
        SELECT n,lead(n) OVER(ORDER BY n) AS following FROM occupied
    ) SELECT min(n+%(step)s::numeric) AS available FROM spans
      WHERE following IS NULL OR following>n+%(step)s::numeric""").format(
        column=sql.Identifier(column), table=sql.Identifier(table))
    return connection.execute(statement, {
        "begin": len(prefix) + 1, "affixes": len(prefix) + len(suffix),
        "prefix_size": len(prefix), "suffix_size": len(suffix), "prefix": prefix, "suffix": suffix,
        "start": candidate, "step": definition.config.increment, "width": definition.config.padding_width,
    }).fetchone()["available"]


def allocate_locked(
    connection: Connection, definition: LockedGenerator, context: GenerationContext, state: CounterState,
    *, chosen_code: str | None = None,
) -> tuple[str, CounterState]:
    """The caller holds all needed counters; commit only with the resource.

    Occupancy can change after the check. The final resource uniqueness check
    remains authoritative; its adapter handles only that specific violation.
    """
    if state.key != counter_key(definition.config, context):
        raise CodeGenerationError("code_generator_recommendation_conflict")
    candidate = next_serial(definition.config, state.last_serial, state.forward_next)
    candidate = available_serial(connection, definition, context, candidate)
    value = render(definition.config, context, candidate)
    if chosen_code is not None and value != chosen_code:
        raise CodeGenerationError("code_generator_recommendation_conflict")
    key = state.key
    updated = connection.execute(
        """UPDATE code_generator_counters SET last_serial=%s,forward_next=NULL
           WHERE generator_id=%s AND scope_kind=%s AND scope_id=%s AND reset_frequency=%s
             AND period_bucket=%s AND version=%s RETURNING version""",
        (candidate, definition.id, key.scope_kind, key.scope_id, key.reset_frequency, key.period_bucket, state.version),
    ).fetchone()
    if updated is None:
        raise CodeGenerationError("code_generator_recommendation_conflict")
    return value, CounterState(key, candidate, None, updated["version"])


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, UUID)):
        return format(value, "f") if isinstance(value, Decimal) else str(value)
    raise TypeError(f"Unsupported completion value: {type(value).__name__}")


def submission_fingerprint(connection: Connection, operation: str, body: str, *, route: dict, files: list | None = None) -> str:
    canonical = connection.execute(
        """SELECT jsonb_build_object('operation',%s::text,'route',%s::jsonb,
                  'body',%s::jsonb,'files',%s::jsonb)::text AS value""",
        (operation, Jsonb(route), body, Jsonb(files or [])),
    ).fetchone()["value"]
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CreationSubmission:
    caller_user_id: int
    operation: str
    key: UUID
    fingerprint: str
    completed_result: dict | None

    @classmethod
    def lock(cls, connection: Connection, operation: str, key: UUID, fingerprint: str) -> CreationSubmission:
        caller = connection.execute("SELECT current_user_id() AS id").fetchone()["id"]
        if caller is None:
            raise CodeGenerationError("insufficient_privilege")
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1260002))",
                           (f"{caller}/{operation}/{key}",))
        earlier = connection.execute(
            """SELECT fingerprint,result FROM resource_creation_requests
               WHERE caller_user_id=%s AND operation=%s AND submission_key=%s""", (caller, operation, key),
        ).fetchone()
        if earlier is not None and earlier["fingerprint"] != fingerprint:
            raise CodeGenerationError("creation_submission_conflict")
        # The adapter must reauthorize the earlier result before exposing it.
        return cls(caller, operation, key, fingerprint, earlier["result"] if earlier else None)

    def complete(self, connection: Connection, result: dict) -> None:
        if self.completed_result is not None:
            raise CodeGenerationError("creation_submission_conflict")
        connection.execute(
            """INSERT INTO resource_creation_requests(caller_user_id,operation,submission_key,fingerprint,result)
               VALUES(%s,%s,%s,%s,%s)""",
            (self.caller_user_id, self.operation, self.key, self.fingerprint,
             Jsonb(result, dumps=lambda value: json.dumps(value, default=_json_value))),
        )
