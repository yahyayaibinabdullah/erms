"""Read-only number suggestions; database uniqueness remains authoritative."""
import re
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection, sql

from .operation_policy import operation_policy
from .database import get_connection
from . import typed_metadata
from .code_generation import CodeGenerationError, counter_key, next_serial, render
from .code_generation_creation import generation_context
from .code_generation_store import available_serial, lock_creation_bindings, read_counter
from .creation_roles import select_creator_role
from .resource_authorization import require_clearance_for_level, require_global, require_resource_operation

router = APIRouter(prefix='/api/v1/number-suggestions', tags=['number suggestions'])


@router.get('/{resource}')
@operation_policy("relationship_scoped")
def suggest_number(resource: str, number: str | None = Query(None, min_length=1),
                   connection: Connection = Depends(get_connection, scope='function'), root: bool = False,
                   parent_aggregation_id: int | None = None, classification_id: int | None = None,
                   type_id: int | None = None, creator_acl_role_id: int | None = None, security_level_id: int | None = None):
    if resource not in {'records', 'aggregations'}:
        raise HTTPException(404, detail='unknown resource')
    privileges = ['record.create'] if resource == 'records' else ['aggregation.create_root', 'aggregation.create_child']
    allowed = connection.execute(
        'SELECT EXISTS(SELECT 1 FROM unnest(%s::text[]) p WHERE user_has_global_privilege(current_user_id(),p)) AS allowed',
        (privileges,),
    ).fetchone()['allowed']
    if not allowed:
        raise HTTPException(403, detail={'code': 'insufficient_privilege'})
    configured=custom_suggestion(connection,resource,parent_aggregation_id,classification_id,type_id,
                                 creator_acl_role_id,security_level_id)
    if configured is not None:
        return configured
    if number is not None and len(number)>200:
        raise HTTPException(422,detail=[{"loc":["query","number"],"type":"string_too_long",
            "msg":"String should have at most 200 characters"}])
    if number is None:
        if parent_aggregation_id is not None:
            parent = connection.execute(
                'SELECT aggregation_number FROM aggregations WHERE id=%s AND current_user_can_view_aggregation(id)',
                (parent_aggregation_id,),
            ).fetchone()
            if parent is None:
                raise HTTPException(404, detail={'code': 'resource_not_found'})
            root = False
            number = parent['aggregation_number'] + ('.0' if resource == 'records' else '/0')
        elif resource == 'aggregations' and classification_id is not None:
            classification = connection.execute(
                "SELECT code FROM classifications WHERE id=%s AND is_terminal", (classification_id,),
            ).fetchone()
            if classification is None:
                raise HTTPException(422, detail={'code': 'terminal_classification_required'})
            year = connection.execute("SELECT extract(year FROM CURRENT_TIMESTAMP)::int AS year").fetchone()['year']
            root = True
            number = f"{classification['code']}/0/{year}"
        else:
            raise HTTPException(422, detail={'code': 'number_context_required'})
    numbers = next_numbers(connection, resource, number, root=root)
    return ({'suggested_number':numbers[0],'generation_intent':{'source':'legacy'}}
            if numbers else {'suggested_number':None})


def custom_suggestion(c,resource,parent_id,classification_id,type_id,creator_role_id,security_level_id):
    kind=resource[:-1]
    number_field="record_number" if kind=="record" else "aggregation_number"
    attached=c.execute("""SELECT id FROM code_generators WHERE enabled AND kind=%s AND primary_field=%s
        AND type_population @> coalesce(%s::bigint,0)""",(kind,number_field,type_id)).fetchone()
    if attached is None:
        if type_id is not None:
            level=security_level_id or c.execute("SELECT lowest_security_level_id() AS id").fetchone()["id"]
            typed_metadata.authorize_creation(c,kind,type_id,level)
        return None
    if kind=="record" and parent_id is None:
        raise CodeGenerationError("code_generator_missing_context",field="parent_aggregation_id")
    privilege="record.create" if kind=="record" else "aggregation.create_child" if parent_id is not None else "aggregation.create_root"
    require_global(c,privilege)
    parent=None
    if parent_id is not None:
        parent=require_resource_operation(c,"aggregation",parent_id,privilege,
            "aggregation.add_record" if kind=="record" else "aggregation.add_child",lock=False)
    selected_role=select_creator_role(c,creator_role_id,parent_id)
    level=security_level_id or (parent["security_level_id"] if kind=="aggregation" and parent else
        c.execute("SELECT lowest_security_level_id() AS id").fetchone()["id"])
    require_clearance_for_level(c,level)
    typed_metadata.authorize_creation(c,kind,type_id,level)
    definition=next((g for g in lock_creation_bindings(c,kind,type_id) if g.primary_field==number_field),None)
    if definition is None:
        return None
    context=generation_context(c,parent_id=parent_id,classification_id=classification_id,
        owner_org_unit_id=selected_role["org_unit_id"],role_id=selected_role["role_id"])
    key=counter_key(definition.config,context)
    state=read_counter(c,definition.id,key)
    serial=available_serial(c,definition,context,next_serial(definition.config,state.last_serial,state.forward_next))
    return {"suggested_number":render(definition.config,context,serial),
        "generation_intent":{"source":"generator","generator_id":definition.id},
        "context":{**asdict(key),"generator_version":definition.version,"working_timezone":context.working_timezone}}


def next_numbers(connection: Connection, resource: str, number: str, *, root: bool = False,
                 count: int = 1) -> list[str]:
    pattern = (r'(.+/)([0-9]+)(/[0-9]{4})' if root and resource == 'aggregations'
               else r'(.+\.)([0-9]+)' if resource == 'records' else r'(.+/)([0-9]+)')
    match = re.fullmatch(pattern, number)
    if not match:
        return []
    prefix, suffix = match.groups()[:2]
    ending = match.group(3) if root and resource == "aggregations" else ""
    column = sql.Identifier('record_number' if resource == 'records' else 'aggregation_number')
    # Check global occupancy, including hidden records. Generate numbers only
    # from the first gaps needed to fill the requested batch.
    query = sql.SQL('''WITH existing AS (
        SELECT substring({column} FROM %(begin)s FOR length({column})-%(affixes)s)::numeric AS n
        FROM {table}
        WHERE left({column},%(prefix_size)s)=%(prefix)s AND right({column},%(ending_size)s)=%(ending)s
          AND substring({column} FROM %(begin)s FOR greatest(0,length({column})-%(affixes)s)) ~ '^[0-9]+$'
    ), occupied AS (
        SELECT DISTINCT n FROM existing WHERE n>%(start)s::numeric
        UNION ALL SELECT %(start)s::numeric
    ), spans AS (
        SELECT n,lead(n) OVER (ORDER BY n) AS next_n FROM occupied
    ), gaps AS (
        SELECT n,LEAST(next_n-n-1,%(count)s)::int AS width
        FROM spans WHERE next_n IS NULL OR next_n>n+1
    ), available AS (
        SELECT n,width,sum(width) OVER (ORDER BY n)-width AS preceding FROM gaps
    )
    SELECT n+step AS n FROM available
    CROSS JOIN LATERAL generate_series(1,LEAST(width,%(count)s-preceding)::int) AS step
    WHERE preceding<%(count)s ORDER BY n''').format(
        column=column, table=sql.Identifier(resource))
    values = connection.execute(query, {
        "begin": len(prefix) + 1, "affixes": len(prefix) + len(ending),
        "prefix_size": len(prefix), "prefix": prefix, "ending_size": len(ending),
        "ending": ending, "start": suffix, "count": count,
    }).fetchall()
    numbers = [prefix + str(int(row["n"])).zfill(len(suffix)) + ending for row in values]
    return [number for number in numbers if len(number) <= 200]
