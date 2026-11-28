"""Governed, uncached administration of custom code generators."""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
import psycopg
from psycopg import Connection, sql
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from .authorization_policy import require_global_privilege
from .code_generation import (
    CodeGenerationError, CounterKey, GenerationContext, GeneratorConfig, is_blank_text,
    next_serial, preview_sequence, serial_text,
)
from .code_generation_store import PRIMARY_TEXT_FIELDS, advance_counter, read_counter, read_definition
from .concurrency import expected_version
from .config import default_working_timezone
from .continuity_lock import acquire_continuity_shared_lock
from .database import get_connection


Kind = Literal["record", "aggregation"]
Scope = Literal["generator", "parent_aggregation", "classification", "org_unit"]
Reset = Literal["never", "yearly", "monthly"]
Database = Annotated[Connection, Depends(get_connection, scope="function")]
Version = Annotated[int, Depends(expected_version)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]
Identity = Annotated[int, Field(gt=0, le=2**63-1, strict=True)]

router = APIRouter(prefix="/api/v1/code-generators", tags=["code generation"],
                   dependencies=[Depends(require_global_privilege("app.settings.manage"))])

messages = {
    "code_generator_invalid": "code_generation.error.invalid",
    "code_generator_invalid_target": "code_generation.error.invalid_target",
    "code_generator_overlap": "code_generation.error.overlap",
    "code_generator_not_found": "code_generation.error.not_found",
    "code_generator_missing_context": "code_generation.error.missing_context",
    "code_generator_length_exceeded": "code_generation.error.length_exceeded",
    "code_generator_reason_required": "code_generation.error.reason_required",
    "code_generator_backward_adjustment": "code_generation.error.backward_adjustment",
    "code_generator_stale_version": "common.error.stale_version",
    "code_generator_in_use": "code_generation.error.in_use",
    "code_generator_access_denied": "common.error.forbidden",
    "code_generator_required_value": "code_generation.error.required_value",
    "code_generator_recommendation_conflict": "code_generation.error.recommendation_conflict",
    "creation_submission_key_required": "code_generation.error.submission_key_required",
    "creation_submission_key_invalid": "code_generation.error.submission_key_invalid",
    "creation_submission_conflict": "code_generation.error.submission_conflict",
    "creation_submission_unavailable": "code_generation.error.submission_unavailable",
}


def generator_error(error: CodeGenerationError) -> HTTPException:
    status = {"code_generator_overlap":409, "code_generator_not_found":404,
              "code_generator_stale_version":412, "code_generator_in_use":409,
              "code_generator_recommendation_conflict":409,"creation_submission_key_required":428,
              "creation_submission_conflict":409,"creation_submission_unavailable":410,
              "code_generator_access_denied":403}.get(error.code,422)
    detail = {"code":error.code,"message_key":messages.get(error.code,"code_generation.error.invalid"),"parameters":{}}
    if error.field is not None:
        detail["field"] = error.field
    if error.parameters:
        detail["validation"] = dict(error.parameters)
    return HTTPException(status,detail=detail)


@contextmanager
def checked(c):
    try:
        with c.transaction():
            yield
    except CodeGenerationError as error:
        raise generator_error(error) from None
    except psycopg.Error as error:
        constraint = error.diag.constraint_name or ""
        primary = error.diag.message_primary or ""
        if constraint in {"code_generators_primary_overlap","code_generators_enabled_primary","code_generators_enabled_field"}:
            code = "code_generator_overlap"
        elif constraint == "code_generator_counters_generator_id_fkey":
            code = "code_generator_in_use"
        elif primary in messages:
            code = primary
        elif isinstance(error,(psycopg.IntegrityError,psycopg.DataError)):
            code = "code_generator_invalid_target" if error.sqlstate=="23503" else "code_generator_invalid"
        else:
            raise
        raise generator_error(CodeGenerationError(code)) from None


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr
    kind: Kind
    primary_field: StrictStr | None = None
    type_id: Identity | None = None
    applies_to: Literal["all", "untyped", "type"] | None = None
    field_id: Identity | None = None
    pattern: StrictStr
    start: StrictStr | StrictInt = "1"
    increment: StrictStr | StrictInt = "1"
    scope: Scope = "generator"
    reset_frequency: Reset = "never"
    padding_width: Annotated[int,Field(ge=0,le=2_147_483_647,strict=True)] | None = None
    max_code_length: Annotated[int,Field(gt=0,le=2_147_483_647,strict=True)]
    enabled: StrictBool = True


def configuration(c, body: Configuration, *, allow_unbound=False):
    values = body.model_dump()
    primary,field,kind,type_id = body.primary_field,body.field_id,body.kind,body.type_id
    if 'applies_to' in body.model_fields_set and body.applies_to is None:
        raise CodeGenerationError("code_generator_invalid_target",field="applies_to")
    values['applies_to'] = body.applies_to or ('type' if type_id is not None else 'all')
    if (values['applies_to']=='type') != (type_id is not None):
        raise CodeGenerationError("code_generator_invalid_target",field="applies_to")
    unbound = primary is None and field is None and type_id is None and not body.enabled
    if unbound and values['applies_to']!='all':
        raise CodeGenerationError("code_generator_invalid_target",field="applies_to")
    if not (allow_unbound and unbound):
        if ((primary is None)==(field is None) or primary is not None and primary not in PRIMARY_TEXT_FIELDS[kind]
            or field is not None and type_id is None):
            raise CodeGenerationError("code_generator_invalid_target")
    if type_id is not None and c.execute("SELECT id FROM resource_types WHERE kind=%s AND id=%s",(kind,type_id)).fetchone() is None:
        raise CodeGenerationError("code_generator_invalid_target",field="type_id")
    capacity = 200 if primary in {"assigned_location","current_location"} else None
    if field is not None:
        row = c.execute("SELECT max_length FROM resource_type_fields WHERE kind=%s AND type_id=%s AND id=%s AND data_type='text'",
                        (kind,type_id,field)).fetchone()
        if row is None:
            raise CodeGenerationError("code_generator_invalid_target",field="field_id")
        capacity = row["max_length"]
    config = GeneratorConfig.from_mapping(values,globally_unique_number=primary in {"record_number","aggregation_number"},field_max_length=capacity)
    values.update(start=config.start,increment=config.increment,padding_width=config.padding_width)
    return config,values


def require_reason(c):
    reason = c.execute("SELECT current_setting('app.change_reason',true) AS reason").fetchone()["reason"]
    if is_blank_text(reason):
        raise CodeGenerationError("code_generator_reason_required")


def definition_result(c, identity):
    row = c.execute("SELECT code_generator_snapshot(g) AS value FROM code_generators g WHERE id=%s",(identity,)).fetchone()
    if row is None:
        raise CodeGenerationError("code_generator_not_found")
    return row["value"]


def pattern_warnings(c, values, identity=None):
    """Conservative advisory for independent series with the same first code.

    This is not an overlap rule or a promise that other patterns cannot collide.
    Actual allocation still checks the existing primary-number unique constraint.
    """
    if not values.get('enabled', True) or values.get('primary_field') not in {'record_number','aggregation_number'}:
        return []
    duplicate = c.execute("""SELECT EXISTS (
        SELECT FROM code_generators WHERE id IS DISTINCT FROM %s AND enabled
          AND kind=%s AND primary_field=%s AND pattern=%s
          AND start=%s::numeric AND coalesce(padding_width,0)=%s
    ) AS duplicate""", (identity, values['kind'], values['primary_field'], values['pattern'],
                          values['start'], values.get('padding_width') or 0)).fetchone()['duplicate']
    return ['independent_number_pattern'] if duplicate else []


@router.get("")
def definitions(c: Database, q: str="", kind: Kind | None=None, enabled: bool | None=None,
                limit: PageSize=25, offset: Offset=0, descending: bool=False):
    direction = sql.SQL("DESC" if descending else "ASC")
    rows = c.execute(sql.SQL("""WITH matching AS MATERIALIZED (
        SELECT g FROM code_generators g WHERE (%s='' OR strpos(lower(name),lower(%s))>0)
          AND (%s::text IS NULL OR kind=%s) AND (%s::boolean IS NULL OR enabled=%s)
        ), total AS (SELECT count(*) AS total FROM matching), page AS (
        SELECT g FROM matching ORDER BY (g).name COLLATE "C" {direction},(g).id {direction} LIMIT %s OFFSET %s)
        SELECT total.total,code_generator_snapshot(page.g) AS item FROM total LEFT JOIN page ON true
        ORDER BY (page.g).name COLLATE "C" {direction},(page.g).id {direction}""").format(direction=direction),
        (q,q,kind,kind,enabled,enabled,limit,offset)).fetchall()
    return {"items":[row["item"] for row in rows if row["item"] is not None and row["item"]["id"] is not None],"total":rows[0]["total"]}


@router.get("/targets/primary")
def primary_targets(kind: Kind):
    return {"items":[{"key":key,"data_type":"text","max_length":200 if key in {"assigned_location","current_location"} else None}
                     for key in PRIMARY_TEXT_FIELDS[kind]]}


def target_page(c, source, parameters, q, selected, limit, offset, descending=False):
    direction = sql.SQL("DESC" if descending else "ASC")
    rows = c.execute(sql.SQL("""WITH matching AS MATERIALIZED (
        SELECT * FROM ({source}) options WHERE %s='' OR strpos(lower(name),lower(%s))>0 OR id=%s
        ), total AS (SELECT count(*) AS total FROM matching), page AS (
        SELECT * FROM matching ORDER BY (id=%s) DESC NULLS LAST,name COLLATE "C" {direction},id {direction} LIMIT %s OFFSET %s)
        SELECT total.total,to_jsonb(page) AS item FROM total LEFT JOIN page ON true
        ORDER BY (page.id=%s) DESC NULLS LAST,page.name COLLATE "C" {direction},page.id {direction}""").format(
            source=sql.SQL(source),direction=direction),
        (*parameters,q,q,selected,selected,limit,offset,selected)).fetchall()
    return {"items":[row["item"] for row in rows if row["item"] is not None and row["item"]["id"] is not None],"total":rows[0]["total"]}


@router.get("/targets/types")
def type_targets(c: Database, kind: Kind, q: str="", selected: int | None=None, limit: PageSize=25, offset: Offset=0, descending: bool=False):
    return target_page(c,"SELECT id,name,translations FROM resource_types WHERE kind=%s",(kind,),q,selected,limit,offset,descending)


@router.get("/targets/fields")
def field_targets(c: Database, kind: Kind, type_id: int, q: str="", selected: int | None=None, limit: PageSize=25, offset: Offset=0, descending: bool=False):
    return target_page(c,"""SELECT id,name,translations,display_order,max_length FROM resource_type_fields
                      WHERE kind=%s AND type_id=%s AND data_type='text'""",(kind,type_id),q,selected,limit,offset,descending)


class SampleContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_aggregation_number: StrictStr | None = None
    classification_code: StrictStr | None = None
    classification_scheme_code: StrictStr | None = None
    org_unit_code: StrictStr | None = None
    role_code: StrictStr | None = None

    def context(self, day, identity, working_timezone):
        return GenerationContext(instant=datetime(day.year,day.month,day.day,tzinfo=timezone.utc),working_timezone=working_timezone,
            parent_aggregation_id=identity,classification_id=identity,org_unit_id=identity,**self.model_dump())


class Simulation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration: Configuration
    scenario: Literal["same_scope","year_transition","month_transition","different_scopes","combined"] = "same_scope"
    sample_date: date
    context_a: SampleContext
    context_b: SampleContext
    generator_id: Identity | None = None


@router.post("/preview")
def preview(body: Simulation, c: Database):
    with checked(c):
        config,values = configuration(c,body.configuration)
        working_timezone = default_working_timezone(c)
        items = preview_sequence(config,body.context_a.context(body.sample_date,1,working_timezone),body.context_b.context(body.sample_date,2,working_timezone),
                                 body.scenario,sample_date=body.sample_date)
        return {"items":[asdict(item) for item in items],
                "warnings":[*config.warnings,*pattern_warnings(c,values,body.generator_id)],
                "working_timezone":working_timezone}


@router.post("",status_code=201)
def create(body: Configuration, c: Database):
    with checked(c):
        acquire_continuity_shared_lock(c)
        _,values = configuration(c,body)
        row = c.execute(sql.SQL("INSERT INTO code_generators ({}) VALUES ({}) RETURNING id").format(
            sql.SQL(",").join(map(sql.Identifier,values)),sql.SQL(",").join(sql.Placeholder() for _ in values)),list(values.values())).fetchone()
        result = definition_result(c,row["id"])
        result['warnings'] = pattern_warnings(c,values,row['id'])
        return result


@router.get("/{generator_id}")
def read(generator_id: int, c: Database):
    with checked(c):
        result = definition_result(c,generator_id)
        result['warnings'] = pattern_warnings(c,result,generator_id)
        return result


@router.put("/{generator_id}")
def update(generator_id: int, body: Configuration, version: Version, c: Database):
    with checked(c):
        acquire_continuity_shared_lock(c)
        require_reason(c)
        definition_result(c,generator_id)
        _,values = configuration(c,body,allow_unbound=True)
        row = c.execute(sql.SQL("UPDATE code_generators SET {} WHERE id=%s AND version=%s RETURNING id").format(
            sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(key)) for key in values)),
            (*values.values(),generator_id,version)).fetchone()
        if row is None:
            raise CodeGenerationError("code_generator_stale_version")
        result = definition_result(c,generator_id)
        result['warnings'] = pattern_warnings(c,values,generator_id)
        return result


@router.delete("/{generator_id}/binding")
def remove_binding(generator_id: int, version: Version, c: Database):
    with checked(c):
        acquire_continuity_shared_lock(c)
        require_reason(c)
        definition_result(c,generator_id)
        row = c.execute("""UPDATE code_generators SET enabled=false,primary_field=NULL,type_id=NULL,field_id=NULL,applies_to='all'
                         WHERE id=%s AND version=%s RETURNING id""",(generator_id,version)).fetchone()
        if row is None:
            raise CodeGenerationError("code_generator_stale_version")
        return definition_result(c,generator_id)


@router.delete("/{generator_id}",status_code=204)
def delete(generator_id: int, version: Version, c: Database):
    with checked(c):
        acquire_continuity_shared_lock(c)
        require_reason(c)
        definition_result(c,generator_id)
        if c.execute("DELETE FROM code_generators WHERE id=%s AND version=%s RETURNING id",(generator_id,version)).fetchone() is None:
            raise CodeGenerationError("code_generator_stale_version")


class CounterSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_kind: Scope = "generator"
    scope_id: Annotated[int,Field(ge=0,le=2**63-1,strict=True)] = 0
    reset_frequency: Reset = "never"
    period_bucket: date = date(1,1,1)

    def key(self):
        return CounterKey(self.scope_kind,self.scope_id,self.reset_frequency,self.period_bucket)


class CounterAdvance(CounterSelection):
    next_number: StrictStr | StrictInt


def counter_version(if_match: Annotated[str | None,Header(alias="If-Match")]=None):
    if if_match is not None:
        value = if_match.strip()
        if value.startswith("W/"):
            value = value[2:].strip()
        if len(value)>=2 and value[0]==value[-1]=='"':
            value = value[1:-1]
        if value=="0":
            return 0
    return expected_version(if_match)


def counter_result(definition, state):
    return {**asdict(state.key),"version":state.version,
        "last_serial":None if state.last_serial is None else serial_text(state.last_serial),
        "forward_next":None if state.forward_next is None else serial_text(state.forward_next),
        "next_number":serial_text(next_serial(definition.config,state.last_serial,state.forward_next))}


@router.get("/{generator_id}/counters")
def counters(generator_id: int, c: Database, scope_kind: Scope | None=None, scope_id: int | None=None,
             reset_frequency: Reset | None=None, limit: PageSize=25, offset: Offset=0):
    with checked(c):
        read_definition(c,generator_id)
        rows=c.execute("""WITH matching AS MATERIALIZED (
            SELECT counter.* FROM code_generator_counters counter WHERE generator_id=%s
              AND (%s::text IS NULL OR scope_kind=%s) AND (%s::bigint IS NULL OR scope_id=%s)
              AND (%s::text IS NULL OR reset_frequency=%s)
            ), total AS (SELECT count(*) AS total FROM matching), page AS (
            SELECT counter.scope_kind,counter.scope_id,counter.reset_frequency,counter.period_bucket,counter.version,
                   trunc(last_serial)::text AS last_serial,trunc(forward_next)::text AS forward_next,
                   trunc(coalesce(forward_next,last_serial+g.increment,g.start))::text AS next_number
            FROM matching counter JOIN code_generators g ON g.id=counter.generator_id
            ORDER BY counter.scope_kind,counter.scope_id,counter.reset_frequency,counter.period_bucket LIMIT %s OFFSET %s)
            SELECT total.total,to_jsonb(page) AS item FROM total LEFT JOIN page ON true
            ORDER BY page.scope_kind,page.scope_id,page.reset_frequency,page.period_bucket""",
            (generator_id,scope_kind,scope_kind,scope_id,scope_id,reset_frequency,reset_frequency,limit,offset)).fetchall()
        return {"items":[row["item"] for row in rows if row["item"] is not None and row["item"]["scope_kind"] is not None],
                "total":rows[0]["total"]}


@router.get("/{generator_id}/counter")
def counter(generator_id: int, c: Database, scope_kind: Scope="generator",
            scope_id: Annotated[int,Query(ge=0,le=2**63-1)]=0,
            reset_frequency: Reset="never",period_bucket: date=date(1,1,1)):
    with checked(c):
        definition = read_definition(c,generator_id)
        key = CounterKey(scope_kind,scope_id,reset_frequency,period_bucket)
        return counter_result(definition,read_counter(c,generator_id,key))


@router.post("/{generator_id}/counter/advance")
def advance(generator_id: int, body: CounterAdvance, c: Database, version: Annotated[int,Depends(counter_version)]):
    with checked(c):
        acquire_continuity_shared_lock(c)
        require_reason(c)
        state = advance_counter(c,generator_id,body.key(),body.next_number,expected_version=version)
        return counter_result(read_definition(c,generator_id),state)
