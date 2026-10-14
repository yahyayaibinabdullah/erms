from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg import Connection

from .authentication import Principal, principal_from_request
from .database import get_connection
from .schemas import FavouritesPageRead
from .application_configuration import ui_configuration


router = APIRouter(prefix="/api/v1/favourites", tags=["favourites"])


@router.get("", response_model=FavouritesPageRead)
def list_favourites(
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
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
    return {"aggregations": aggregations, "records": records, "application_configuration": ui_configuration(connection)}


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
