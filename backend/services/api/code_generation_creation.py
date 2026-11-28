"""One transactional generator batch for authorized final resource creation.

Adapters resolve existing resource/type/role rules first. Collect every item
before apply(), so a separate-record drop locks all counters in one stable
order rather than acquiring later counters while holding earlier ones.
"""

from dataclasses import dataclass, field
from typing import Callable

from psycopg import Connection
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from .code_generation import CodeGenerationError, GenerationContext, counter_key, is_blank_text, next_serial, render
from .code_generation_store import (
    PRIMARY_TEXT_FIELDS, CounterState, LockedGenerator, allocate_locked, available_serial,
    lock_counters, lock_creation_bindings, read_counter,
)


def generation_context(
    c: Connection, *, parent_id: int | None, classification_id: int | None,
    owner_org_unit_id: int, role_id: int,
) -> GenerationContext:
    """One server snapshot/instant, existing owning unit and selected Create for."""
    row=c.execute("""WITH RECURSIVE lineage AS (
        SELECT id,parent_aggregation_id,classification_id FROM aggregations WHERE id=%s
        UNION ALL SELECT ancestor.id,ancestor.parent_aggregation_id,ancestor.classification_id
        FROM aggregations ancestor JOIN lineage child ON ancestor.id=child.parent_aggregation_id
        ), root AS (SELECT classification_id FROM lineage WHERE parent_aggregation_id IS NULL)
        SELECT statement_timestamp() AS instant,settings.value#>>'{}' AS working_timezone,
        parent.id AS parent_aggregation_id,parent.aggregation_number AS parent_aggregation_number,
        classification.id AS classification_id,classification.code AS classification_code,
        scheme.code AS classification_scheme_code,owner.id AS org_unit_id,owner.code AS org_unit_code,role.code AS role_code
        FROM application_settings settings
        LEFT JOIN aggregations parent ON parent.id=%s
        LEFT JOIN root ON true
        LEFT JOIN classifications classification ON classification.id=CASE WHEN parent.id IS NULL THEN %s ELSE root.classification_id END
        LEFT JOIN classification_schemes scheme ON scheme.id=classification.classification_scheme_id
        LEFT JOIN org_units owner ON owner.id=coalesce(parent.owning_org_unit_id,%s)
        LEFT JOIN roles role ON role.id=%s
        WHERE settings.key='DEFAULT_WORKING_TIMEZONE'""",(parent_id,parent_id,classification_id,owner_org_unit_id,role_id)).fetchone()
    return GenerationContext(**row)


def validate_intent(kind: str, intent: dict) -> dict:
    if not isinstance(intent,dict) or any(key not in PRIMARY_TEXT_FIELDS[kind] for key in intent):
        raise CodeGenerationError("code_generator_invalid",field="generation_intent")
    for value in intent.values():
        if not isinstance(value,dict) or value.get("source") not in {"generator","legacy"}:
            raise CodeGenerationError("code_generator_invalid",field="generation_intent")
        source=value["source"]
        if (set(value)!={"source","generator_id"} if source=="generator" else set(value)!={"source"}):
            raise CodeGenerationError("code_generator_invalid",field="generation_intent")
        if source=="generator" and (type(value["generator_id"]) is not int or value["generator_id"]<=0):
            raise CodeGenerationError("code_generator_invalid",field="generation_intent")
    return intent


def normalize_create_text(kind: str, values: dict, intent: dict, *, draft: bool=False) -> dict:
    """Preserve the create models' manual trimming and exact automatic literals."""
    validate_intent(kind,intent)
    for key in PRIMARY_TEXT_FIELDS[kind]:
        value=values.get(key)
        if key!="description" and isinstance(value,str) and intent.get(key,{}).get("source")!="generator":
            values[key]=value.strip()
        if draft and key in {"record_number","title"} and key in values and is_blank_text(values[key]):
            values[key]=None
            intent.pop(key,None)
    return values


@dataclass
class CreationItem:
    values: dict
    raw: str
    intent: dict
    generated: dict[str,str] = field(default_factory=dict)


@dataclass(frozen=True)
class RequestedValue:
    item: int
    definition: LockedGenerator
    chosen_code: str | None


class CreationBatch:
    def __init__(self, c: Connection, kind: str, type_id: int | None, context: Callable[[],GenerationContext]):
        self.c=c
        self.kind=kind
        self.definitions=lock_creation_bindings(c,kind,type_id)
        self._context=context
        self._resolved_context=None
        self.items: list[CreationItem]=[]
        self.requested: list[RequestedValue]=[]

    @property
    def context(self):
        if self._resolved_context is None:
            self._resolved_context=self._context()
        return self._resolved_context

    def add(self, values: dict, raw: str, *, intent: dict | None=None) -> CreationItem:
        """Static defaults are already merged; required-value validation follows apply."""
        intent=validate_intent(self.kind,{} if intent is None else intent)
        primary={g.primary_field:g for g in self.definitions if g.primary_field is not None}
        for key,origin in intent.items():
            if is_blank_text(values.get(key)):
                continue
            definition=primary.get(key)
            if ((origin["source"]=="generator" and (definition is None or definition.id!=origin["generator_id"]))
                or origin["source"]=="legacy" and definition is not None):
                raise CodeGenerationError("code_generator_recommendation_conflict")
        item=CreationItem(values,raw,intent)
        index=len(self.items)
        self.items.append(item)
        typed=[g.field_id for g in self.definitions if g.field_id is not None]
        blanks={}
        if typed:
            blanks={row["id"]:row["blank"] for row in self.c.execute("""SELECT id,
                value IS NULL OR value='null'::jsonb OR
                (jsonb_typeof(value)='string' AND NOT resource_type_has_text(value#>>'{}')) AS blank
                FROM unnest(%s::bigint[]) AS requested(id) LEFT JOIN LATERAL (
                    SELECT %s::jsonb->'field_values'->id::text AS value) input ON true""",(typed,raw)).fetchall()}
        for definition in self.definitions:
            key=definition.primary_field
            chosen=None
            if key is not None:
                value=values.get(key)
                automatic=intent.get(key,{}).get("source")=="generator"
                if not is_blank_text(value) and not automatic:
                    continue
                if automatic and not is_blank_text(value):
                    chosen=value
            elif not blanks.get(definition.field_id,True):
                continue
            self.requested.append(RequestedValue(index,definition,chosen))
        return item

    def _values(self, *, allocate: bool) -> list[dict[str,str]]:
        results=[{} for _ in self.items]
        if not self.requested:
            return results
        context=self.context
        desired=[(request.definition,counter_key(request.definition.config,context)) for request in self.requested]
        states=lock_counters(self.c,desired) if allocate else {
            (identity,key):read_counter(self.c,identity,key) for identity,key in
            sorted({(definition.id,key) for definition,key in desired},key=lambda pair:(pair[0],pair[1].scope_kind,pair[1].scope_id,pair[1].reset_frequency,pair[1].period_bucket))}
        for request,(definition,key) in zip(self.requested,desired,strict=True):
            state=states[definition.id,key]
            if allocate:
                code,updated=allocate_locked(self.c,definition,context,state,chosen_code=request.chosen_code)
            else:
                serial=available_serial(self.c,definition,context,next_serial(definition.config,state.last_serial,state.forward_next))
                code=render(definition.config,context,serial)
                if request.chosen_code is not None and code!=request.chosen_code:
                    raise CodeGenerationError("code_generator_recommendation_conflict")
                updated=CounterState(key,serial,None,state.version)
            states[definition.id,key]=updated
            results[request.item][definition.primary_field or str(definition.field_id)]=code
        return results

    def preview(self) -> list[dict[str,str]]:
        """Non-consuming live candidates for preparation, never a reservation."""
        return self._values(allocate=False)

    def apply(self, *, prepared_values: list[dict[str,str]] | None=None) -> None:
        results=self._values(allocate=True)
        if prepared_values is not None and any(
            any(values.get(key)!=value for key,value in expected.items())
            for values,expected in zip(results,prepared_values,strict=True)
        ):
            raise CodeGenerationError("code_generator_recommendation_conflict")
        for item,values in zip(self.items,results,strict=True):
            typed={}
            for key,value in values.items():
                if key in PRIMARY_TEXT_FIELDS[self.kind]:
                    item.values[key]=value
                else:
                    typed[key]=value
            if typed:
                item.raw=self.c.execute("""SELECT jsonb_set(%s::jsonb,'{field_values}',
                    coalesce(%s::jsonb->'field_values','{}'::jsonb)||%s::jsonb,true)::text AS raw""",
                    (item.raw,item.raw,Jsonb(typed))).fetchone()["raw"]
            item.generated=values

    def number_source(self, index: int) -> str | None:
        number="record_number" if self.kind=="record" else "aggregation_number"
        requested=next((entry for entry in self.requested if entry.item==index and entry.definition.primary_field==number),None)
        if requested is None:
            return None
        return "chosen" if requested.chosen_code is not None else "blank"

    def validate_primary(self) -> None:
        number="record_number" if self.kind=="record" else "aggregation_number"
        for item in self.items:
            for key in (number,"title"):
                if is_blank_text(item.values.get(key)):
                    raise CodeGenerationError("code_generator_required_value",field=key)
            for key in ("assigned_location","current_location"):
                value=item.values.get(key)
                if value is not None and (is_blank_text(value) or len(value)>200):
                    raise CodeGenerationError("code_generator_required_value",field=key)


def persist_batch(c: Connection, batch: CreationBatch, type_id: int | None, store, *, prepared_values=None):
    """Persist resources and all generated fields atomically, retrying only new numbers.

    store(index,item,prepared_metadata) may only perform transactional persistence;
    uploads and conversion must already be prepared before entering this loop.
    """
    constraint="records_record_number_key" if batch.kind=="record" else "aggregations_aggregation_number_key"
    while True:
        index=None
        try:
            with c.transaction():
                batch.apply(prepared_values=prepared_values)
                batch.validate_primary()
                prepared=[typed_creation(c,batch.kind,type_id,item.raw) for item in batch.items]
                results=[]
                for index,(item,metadata) in enumerate(zip(batch.items,prepared,strict=True)):
                    results.append(store(index,item,metadata))
                return results
        except UniqueViolation as error:
            if error.diag.constraint_name!=constraint or index is None:
                raise
            source=batch.number_source(index)
            if source=="chosen" or prepared_values is not None:
                raise CodeGenerationError("code_generator_recommendation_conflict") from None
            if source!="blank":
                raise
            # Recompute the entire batch after the savepoint rollback. This
            # preserves its order and rolls back every other generated field.


def typed_creation(c,kind,type_id,raw):
    from .typed_metadata import validate_creation
    return validate_creation(c,kind,type_id,raw)
