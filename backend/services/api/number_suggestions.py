"""Read-only number suggestions; database uniqueness remains authoritative."""
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import Connection, sql

from .operation_policy import operation_policy
from .database import get_connection

router = APIRouter(prefix='/api/v1/number-suggestions', tags=['number suggestions'])


@router.get('/{resource}')
@operation_policy("relationship_scoped")
def suggest_number(resource: str, number: str | None = Query(None, min_length=1, max_length=200),
                   connection: Connection = Depends(get_connection, scope='function'), root: bool = False,
                   parent_aggregation_id: int | None = None, classification_id: int | None = None):
    if resource not in {'records', 'aggregations'}:
        raise HTTPException(404, detail='unknown resource')
    privileges = ['record.create'] if resource == 'records' else ['aggregation.create_root', 'aggregation.create_child']
    allowed = connection.execute(
        'SELECT EXISTS(SELECT 1 FROM unnest(%s::text[]) p WHERE user_has_global_privilege(current_user_id(),p)) AS allowed',
        (privileges,),
    ).fetchone()['allowed']
    if not allowed:
        raise HTTPException(403, detail={'code': 'insufficient_privilege'})
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
    pattern = (r'(.+/)([0-9]+)(/[0-9]{4})' if root and resource == 'aggregations'
               else r'(.+\.)([0-9]+)' if resource == 'records' else r'(.+/)([0-9]+)')
    match = re.fullmatch(pattern, number)
    if not match:
        return {'suggested_number': None}
    prefix, suffix = match.groups()[:2]
    ending = match.group(3) if root and resource == "aggregations" else ""
    column = sql.Identifier('record_number' if resource == 'records' else 'aggregation_number')
    # Candidate gaps avoid generating an unbounded series. Read globally so a
    # hidden resource cannot cause a suggestion that is already occupied.
    query = sql.SQL('''WITH existing AS (
        SELECT substring({column} FROM %s FOR length({column})-%s)::numeric AS n FROM {table}
        WHERE left({column},%s)=%s AND right({column},%s)=%s
          AND substring({column} FROM %s FOR greatest(0,length({column})-%s)) ~ '^[0-9]+$'
    ), candidates AS (SELECT %s::numeric + 1 AS n UNION SELECT n+1 FROM existing)
    SELECT min(n) AS n FROM candidates
    WHERE n>%s::numeric AND NOT EXISTS(SELECT 1 FROM existing WHERE existing.n=candidates.n)''').format(
        column=column, table=sql.Identifier(resource))
    value = connection.execute(query, (len(prefix)+1,len(prefix)+len(ending),len(prefix),prefix,len(ending),ending,len(prefix)+1,len(prefix)+len(ending),suffix,suffix)).fetchone()['n']
    suggested = prefix + str(int(value)).zfill(len(suffix)) + ending
    return {'suggested_number': suggested if len(suggested) <= 200 else None}
