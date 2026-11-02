from typing import Any

from fastapi import HTTPException
from psycopg import Connection, sql


READ_VISIBILITY = {
    "aggregations": sql.SQL("current_user_can_view_aggregation(id)"),
    "records": sql.SQL("current_user_can_view_record(id)"),
    "digital_components": sql.SQL(
        "EXISTS (SELECT 1 FROM records visible_record "
        "WHERE visible_record.id=record_id AND current_user_can_list_record_components(visible_record.id))"
    ),
}


def redact_hidden_relationships(
    connection: Connection, table: str, rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Remove protected relationship identifiers with one bounded set query.

    Filtering must already have used the real database relationship.  The
    companion state field preserves the semantic difference between no
    relationship and an existing relationship whose identifier is redacted.
    Never use a magic/sentinel identifier for that distinction.
    """
    relation = {"aggregations": "parent_aggregation_id", "records": "aggregation_id"}.get(table)
    aggregation_context: dict[int, dict[str, Any]] = {}
    if table in {"aggregations", "records"} and rows:
        owner_ids = sorted({row["owning_org_unit_id"] for row in rows if row.get("owning_org_unit_id")})
        owners = {
            row["id"]: row for row in connection.execute(
                "SELECT id,code,name FROM org_units WHERE id=ANY(%s)", (owner_ids,)
            ).fetchall()
        } if owner_ids else {}
        for row in rows:
            owner = owners.get(row.get("owning_org_unit_id"), {})
            row["owning_org_unit_code"] = owner.get("code")
            row["owning_org_unit_name"] = owner.get("name")
        aggregation_ids = {
            row["id"] if table == "aggregations" else row.get("aggregation_id")
            for row in rows
            if (row["id"] if table == "aggregations" else row.get("aggregation_id")) is not None
        }
        if relation is not None:
            aggregation_ids.update(row[relation] for row in rows if row.get(relation) is not None)
        aggregation_context = {
            row["id"]: row for row in connection.execute(
                """SELECT id,
                          current_user_can_view_aggregation(id) AS visible,
                          aggregation_effective_assigned_location(id) AS effective_assigned_location,
                          aggregation_effective_current_location(id) AS effective_current_location
                          ,CASE WHEN current_user_can_view_aggregation(aggregation_effective_assigned_location_source_id(id)) THEN aggregation_effective_assigned_location_source_id(id) END AS effective_assigned_location_source_aggregation_id
                          ,CASE WHEN current_user_can_view_aggregation(aggregation_effective_current_location_source_id(id)) THEN aggregation_effective_current_location_source_id(id) END AS effective_current_location_source_aggregation_id
                     FROM aggregations WHERE id=ANY(%s)""",
                (sorted(aggregation_ids),),
            ).fetchall()
        } if aggregation_ids else {}
        for row in rows:
            aggregation_id = row["id"] if table == "aggregations" else row.get("aggregation_id")
            locations = aggregation_context.get(aggregation_id, {})
            row["effective_assigned_location"] = locations.get("effective_assigned_location")
            row["effective_current_location"] = locations.get("effective_current_location")
            row["effective_assigned_location_source_aggregation_id"] = locations.get("effective_assigned_location_source_aggregation_id")
            row["effective_current_location_source_aggregation_id"] = locations.get("effective_current_location_source_aggregation_id")
        if table == "aggregations":
            vital_ids = [row["id"] for row in rows]
            descendants = {
                row["id"]: row["has_vital_descendants"] for row in connection.execute(
                    "SELECT id,aggregation_has_vital_descendants(id) AS has_vital_descendants FROM aggregations WHERE id=ANY(%s)",
                    (vital_ids,),
                ).fetchall()
            }
            for row in rows:
                row["has_vital_descendants"] = descendants.get(row["id"], False)
    if relation is None:
        return rows
    parent_ids = sorted({row[relation] for row in rows if row.get(relation) is not None})
    state_field = "parent_aggregation_state" if table == "aggregations" else "aggregation_state"
    if not parent_ids:
        for row in rows:
            # Aggregations may truly be roots. Records always have a container,
            # so a missing record relationship is necessarily already redacted.
            row[state_field] = "none" if table == "aggregations" else "redacted"
        return rows
    visible = {
        entity_id for entity_id in parent_ids
        if aggregation_context.get(entity_id, {}).get("visible", bool(aggregation_context.get(entity_id)))
    }
    for row in rows:
        relationship_id = row.get(relation)
        if relationship_id is None:
            row[state_field] = "none" if table == "aggregations" else "redacted"
        elif relationship_id not in visible:
            row[relation] = None
            row[state_field] = "redacted"
        else:
            row[state_field] = "visible"
    return rows


def get_or_404(connection: Connection, table: str, entity_id: int) -> dict[str, Any]:
    source = "authorized_event_history" if table == "event_history" else table
    query = sql.SQL("SELECT * FROM {} WHERE id = %s").format(sql.Identifier(source))
    if table in READ_VISIBILITY:
        query += sql.SQL(" AND ") + READ_VISIBILITY[table]
    row = connection.execute(query, (entity_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{table.rstrip('s')} not found")
    return redact_hidden_relationships(connection, table, [row])[0]


def list_rows(
    connection: Connection,
    table: str,
    *,
    limit: int,
    offset: int,
    filters: dict[str, Any] | None = None,
    order_by: tuple[str, ...] = ("id",),
    descending: bool = False,
) -> list[dict[str, Any]]:
    filters = {key: value for key, value in (filters or {}).items() if value is not None}
    source = "authorized_event_history" if table == "event_history" else table
    query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(source))
    parameters: list[Any] = []

    clauses = [
        sql.SQL("{} = %s").format(sql.Identifier(column)) for column in filters
    ]
    parameters.extend(filters.values())
    if table in READ_VISIBILITY:
        clauses.append(READ_VISIBILITY[table])
    if clauses:
        query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)

    direction = sql.SQL(" DESC") if descending else sql.SQL(" ASC")
    query += sql.SQL(" ORDER BY ") + sql.SQL(", ").join(
        sql.Identifier(column) + direction for column in order_by
    )
    query += sql.SQL(" LIMIT %s OFFSET %s")
    parameters.extend((limit, offset))
    rows = list(connection.execute(query, parameters).fetchall())
    return redact_hidden_relationships(connection, table, rows)


def create_row(connection: Connection, table: str, values: dict[str, Any]) -> dict[str, Any]:
    columns = list(values)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING *").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    row = connection.execute(query, [values[column] for column in columns]).fetchone()
    return redact_hidden_relationships(connection, table, [row])[0]


def update_row(
    connection: Connection,
    table: str,
    entity_id: int,
    values: dict[str, Any],
    expected_version: int,
) -> dict[str, Any]:
    if not values:
        row = get_or_404(connection, table, entity_id)
        if row["version"] != expected_version:
            raise HTTPException(status_code=412, detail="entity has changed")
        return row

    assignments = [
        sql.SQL("{} = %s").format(sql.Identifier(column)) for column in values
    ]
    query = sql.SQL(
        "UPDATE {} SET {} WHERE id = %s AND version = %s RETURNING *"
    ).format(
        sql.Identifier(table),
        sql.SQL(", ").join(assignments),
    )
    row = connection.execute(
        query, [*values.values(), entity_id, expected_version]
    ).fetchone()
    if row is None:
        current = get_or_404(connection, table, entity_id)
        raise HTTPException(
            status_code=412,
            detail={
                "message": "entity has changed",
                "current_version": current["version"],
            },
        )
    if table == "aggregations" and values.keys() & {"date_closed", "classification_id", "parent_aggregation_id"}:
        # An AFTER-statement disposition hook can update this row again. Return
        # its current status/version, not UPDATE RETURNING's earlier row image.
        row = connection.execute("SELECT * FROM aggregations WHERE id=%s", (entity_id,)).fetchone()
    return redact_hidden_relationships(connection, table, [row])[0]


def delete_row(
    connection: Connection,
    table: str,
    entity_id: int,
    expected_version: int,
) -> None:
    query = sql.SQL(
        "DELETE FROM {} WHERE id = %s AND version = %s RETURNING id"
    ).format(
        sql.Identifier(table)
    )
    if connection.execute(query, (entity_id, expected_version)).fetchone() is None:
        current = get_or_404(connection, table, entity_id)
        raise HTTPException(
            status_code=412,
            detail={
                "message": "entity has changed",
                "current_version": current["version"],
            },
        )
