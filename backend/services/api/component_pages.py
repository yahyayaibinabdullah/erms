"""Bounded component metadata for the saved-record viewer."""

from fastapi import HTTPException
from psycopg import Connection, sql

from backend.services.component_formats import CONVERTIBLE_EXTENSIONS, NATIVE_IMAGE_MIME_TYPES


# Match Path.suffix on the basename, including its requirement for a stem.
PREVIEWABLE = sql.SQL("""
    content_status = 'available' AND (
        lower(mime_type) = ANY({mime_types})
        OR starts_with(lower(mime_type), 'audio/')
        OR starts_with(lower(mime_type), 'video/')
        OR lower(substring(file_name FROM '[^/]+([.][^./]+)$')) = ANY({extensions})
    )
""").format(
    mime_types=sql.Literal(sorted(NATIVE_IMAGE_MIME_TYPES | {"application/pdf"})),
    extensions=sql.Literal(sorted(CONVERTIBLE_EXTENSIONS)),
)


def component_summary(connection: Connection, record_id: int, *, can_view: bool) -> dict:
    return connection.execute(
        sql.SQL("""
            SELECT count(*) AS component_count,
                   coalesce(bool_or(CASE WHEN %s THEN {} ELSE false END), false)
                       AS has_previewable_component
            FROM digital_components WHERE record_id = %s
        """).format(PREVIEWABLE),
        (can_view, record_id),
    ).fetchone()


def previewable_component_page(
    connection: Connection, record_id: int, *, limit: int, offset: int,
    selected_component_id: int | None,
) -> dict:
    allowed = connection.execute(
        """SELECT current_user_can_list_record_components(%s) AS can_list,
                  current_user_can_record_component_operation(
                      %s, 'record.component.view', 'record.component.view') AS can_view""",
        (record_id, record_id),
    ).fetchone()
    if not allowed["can_list"]:
        raise HTTPException(status_code=404, detail="record not found")
    if not allowed["can_view"]:
        raise HTTPException(status_code=403, detail={"code": "insufficient_resource_permission"})

    eligible = sql.SQL("FROM digital_components WHERE record_id = %s AND ({})").format(PREVIEWABLE)
    if selected_component_id is not None:
        selected = connection.execute(
            sql.SQL("SELECT component_order ") + eligible + sql.SQL(" AND id = %s"),
            (record_id, selected_component_id),
        ).fetchone()
        if selected is None:
            raise HTTPException(status_code=404, detail="previewable digital component not found")
        rank = connection.execute(
            sql.SQL("SELECT count(*) AS value ") + eligible
            + sql.SQL(" AND (component_order, id) < (%s, %s)"),
            (record_id, selected["component_order"], selected_component_id),
        ).fetchone()["value"]
        offset = rank // limit * limit

    total = connection.execute(
        sql.SQL("SELECT count(*) AS value ") + eligible, (record_id,),
    ).fetchone()["value"]
    offset = min(offset, max(0, total - 1) // limit * limit)
    items = connection.execute(
        sql.SQL("SELECT * ") + eligible + sql.SQL(" ORDER BY component_order, id LIMIT %s OFFSET %s"),
        (record_id, limit, offset),
    ).fetchall()
    return {"items": items, "total": total, "limit": limit, "offset": offset, "returned": len(items)}
