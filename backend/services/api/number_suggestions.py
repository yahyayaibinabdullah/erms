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
    numbers = next_numbers(connection, resource, number, root=root)
    return {'suggested_number': numbers[0] if numbers else None}


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
