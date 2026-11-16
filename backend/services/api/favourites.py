from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from psycopg import Connection

from .operation_policy import operation_policy
from .authentication import Principal, principal_from_request
from .database import get_connection
from .schemas import FavouritesPageRead
from .application_configuration import ui_configuration
from .creator_attribution import add_creator_names
from .dashboard_visibility import visibility_ctes


router = APIRouter(prefix="/api/v1/favourites", tags=["favourites"])

FAVOURITE_PAGE = f"""
WITH RECURSIVE aggregation_favourites AS MATERIALIZED (
    SELECT aggregation.id, aggregation.parent_aggregation_id, favourite.date_created
      FROM user_favourite_aggregations favourite
      JOIN aggregations aggregation ON aggregation.id=favourite.aggregation_id
     WHERE favourite.user_id=%s AND (%s::text IS NULL OR %s='aggregation')
), record_favourites AS MATERIALIZED (
    SELECT record.id, record.aggregation_id, favourite.date_created
      FROM user_favourite_records favourite
      JOIN records record ON record.id=favourite.record_id
     WHERE favourite.user_id=%s AND (%s::text IS NULL OR %s='record')
), page_aggregation_ids AS (
    SELECT id FROM aggregation_favourites
    UNION SELECT parent_aggregation_id FROM aggregation_favourites WHERE parent_aggregation_id IS NOT NULL
    UNION SELECT aggregation_id FROM record_favourites
), page_record_ids AS (
    SELECT id FROM record_favourites
), {visibility_ctes(page_access=True)}, visible AS MATERIALIZED (
    SELECT 'aggregation'::text kind, aggregation.id, aggregation.aggregation_number,
           NULL::text record_number, aggregation.title, parent.id parent_aggregation_id,
           NULL::bigint aggregation_id, NULL::text aggregation_title,
           favourite.date_created date_favourited
      FROM aggregation_favourites favourite
      JOIN authorized_aggregations allowed ON allowed.id=favourite.id
      JOIN aggregations aggregation ON aggregation.id=allowed.id
 LEFT JOIN authorized_aggregations parent ON parent.id=favourite.parent_aggregation_id
    UNION ALL
    SELECT 'record', record.id, parent.aggregation_number, record.record_number, record.title, NULL,
           parent.id, parent.title, favourite.date_created
      FROM record_favourites favourite
      JOIN authorized_records allowed ON allowed.id=favourite.id
      JOIN records record ON record.id=allowed.id
 LEFT JOIN authorized_aggregations visible_parent ON visible_parent.id=favourite.aggregation_id
 LEFT JOIN aggregations parent ON parent.id=visible_parent.id
), page AS (
    SELECT * FROM visible ORDER BY date_favourited DESC,kind,id DESC LIMIT %s OFFSET %s
)
SELECT totals.total,page.* FROM (SELECT count(*) AS total FROM visible) totals
LEFT JOIN page ON true ORDER BY page.date_favourited DESC,page.kind,page.id DESC
"""


@router.get("", response_model=FavouritesPageRead, response_model_exclude_unset=True)
@operation_policy("authenticated_only")
def list_favourites(
    kind: Literal["aggregation", "record"] | None = None,
    limit: int | None = Query(None, ge=1, le=100),
    offset: int = Query(0, ge=0),
    preview: Literal["aggregation", "record", "combined"] | None = None,
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    configuration = ui_configuration(connection)
    if limit is not None:
        rows = connection.execute(FAVOURITE_PAGE, (
            principal.user_id, kind, kind, principal.user_id, kind, kind, limit, offset,
        )).fetchall()
        total = rows[0]["total"]
        items = {"aggregations": [], "records": []}
        page = [(row.pop("kind"), row) for row in rows if row["id"] is not None]
        add_creator_names(connection, page)
        for item_kind, item in page:
            item.pop("total")
            if item_kind == "record":
                item.pop("parent_aggregation_id")
            else:
                item.pop("record_number")
                item.pop("aggregation_id")
                item.pop("aggregation_title")
            items[item_kind + "s"].append(item)
        return {**items, "total": total, "application_configuration": configuration}
    aggregations = connection.execute(
        """
        SELECT aggregation.id, aggregation.aggregation_number,
               aggregation.title,
               CASE WHEN aggregation.parent_aggregation_id IS NULL
                          OR current_user_can_view_aggregation(aggregation.parent_aggregation_id)
                    THEN aggregation.parent_aggregation_id END AS parent_aggregation_id,
               favourite.date_created AS date_favourited
        FROM user_favourite_aggregations favourite
        JOIN aggregations aggregation ON aggregation.id = favourite.aggregation_id
        WHERE favourite.user_id = %s
          AND current_user_can_view_aggregation(aggregation.id)
        ORDER BY favourite.date_created DESC, aggregation.id DESC
        """,
        (principal.user_id,),
    ).fetchall()
    records = connection.execute(
        """
        SELECT record.id, record.record_number, record.title,
               CASE WHEN current_user_can_view_aggregation(record.aggregation_id)
                    THEN record.aggregation_id END AS aggregation_id,
               CASE WHEN current_user_can_view_aggregation(record.aggregation_id)
                    THEN aggregation.aggregation_number END AS aggregation_number,
               CASE WHEN current_user_can_view_aggregation(record.aggregation_id)
                    THEN aggregation.title END AS aggregation_title,
               favourite.date_created AS date_favourited
        FROM user_favourite_records favourite
        JOIN records record ON record.id = favourite.record_id
        JOIN aggregations aggregation ON aggregation.id = record.aggregation_id
        WHERE favourite.user_id = %s
          AND current_user_can_view_record(record.id)
        ORDER BY favourite.date_created DESC, record.id DESC
        """,
        (principal.user_id,),
    ).fetchall()
    if preview:
        add_creator_names(connection, favourite_preview(aggregations, records, configuration["DASHBOARD_FAVOURITE_ITEM_LIMIT"], preview))
    return {"aggregations": aggregations, "records": records, "application_configuration": configuration}


def favourite_preview(aggregations, records, limit: int, preview: str = "combined"):
    if preview == "aggregation":
        return [("aggregation", row) for row in aggregations[:limit]]
    if preview == "record":
        return [("record", row) for row in records[:limit]]
    mixed = [("aggregation", row) for row in aggregations[:limit]] + [("record", row) for row in records[:limit]]
    return sorted(mixed, key=lambda item: item[1]["date_favourited"], reverse=True)[:limit]


def _add_favourite(
    connection: Connection, principal: Principal, *, table: str,
    target_table: str, target_column: str, target_id: int,
) -> None:
    visibility = (
        "current_user_can_view_aggregation(id)" if target_table == "aggregations"
        else "current_user_can_view_record(id)"
    )
    exists = connection.execute(
        f"SELECT 1 FROM {target_table} WHERE id = %s AND {visibility}", (target_id,)
    ).fetchone()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"{target_table[:-1]} not found")
    connection.execute(
        f"""
        INSERT INTO {table} (user_id, {target_column})
        VALUES (%s, %s)
        ON CONFLICT (user_id, {target_column}) DO NOTHING
        """,
        (principal.user_id, target_id),
    )


def _remove_favourite(
    connection: Connection, principal: Principal, *, table: str,
    target_column: str, target_id: int,
) -> None:
    connection.execute(
        f"DELETE FROM {table} WHERE user_id = %s AND {target_column} = %s",
        (principal.user_id, target_id),
    )


@router.put("/aggregations/{aggregation_id}", status_code=status.HTTP_204_NO_CONTENT)
@operation_policy("authenticated_only")
def favourite_aggregation(
    aggregation_id: int,
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _add_favourite(
        connection, principal, table="user_favourite_aggregations",
        target_table="aggregations", target_column="aggregation_id",
        target_id=aggregation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/aggregations/{aggregation_id}", status_code=status.HTTP_204_NO_CONTENT)
@operation_policy("authenticated_only")
def unfavourite_aggregation(
    aggregation_id: int,
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _remove_favourite(
        connection, principal, table="user_favourite_aggregations",
        target_column="aggregation_id", target_id=aggregation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
@operation_policy("authenticated_only")
def favourite_record(
    record_id: int,
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _add_favourite(
        connection, principal, table="user_favourite_records",
        target_table="records", target_column="record_id", target_id=record_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
@operation_policy("authenticated_only")
def unfavourite_record(
    record_id: int,
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _remove_favourite(
        connection, principal, table="user_favourite_records",
        target_column="record_id", target_id=record_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
