"""Existing Create for selection, shared by creation and number suggestions."""

from fastapi import HTTPException
from psycopg import Connection

from .entity_localization import localized_projection


def creation_role_options(
    connection: Connection, parent_aggregation_id: int | None = None,
    *, language_tag: str | None = None,
) -> list[dict]:
    parameters: list[int] = []
    owner_clause = ""
    if parent_aggregation_id is not None:
        parent = connection.execute(
            "SELECT owning_org_unit_id FROM aggregations WHERE id=%s",
            (parent_aggregation_id,),
        ).fetchone()
        if parent is None:
            raise HTTPException(status_code=409, detail="referenced aggregation does not exist")
        owner_clause = " AND role.org_unit_id=%s"
        parameters.append(parent["owning_org_unit_id"])
    rows = connection.execute(
        """SELECT DISTINCT role.id AS role_id,role.code AS role_code,
                  role.name AS role_name,unit.id AS org_unit_id,
                  unit.code AS org_unit_code,unit.name AS org_unit_name,
                  role.translations AS role_translations,
                  unit.translations AS org_unit_translations
             FROM user_role_assignments assignment
             JOIN roles role ON role.id=assignment.role_id
             JOIN org_units unit ON unit.id=role.org_unit_id
            WHERE assignment.user_id=current_user_id()
              AND CURRENT_TIMESTAMP>=assignment.valid_from
              AND (assignment.valid_until IS NULL OR CURRENT_TIMESTAMP<assignment.valid_until)
              AND role_effectively_active(role.id)""" + owner_clause +
        " ORDER BY org_unit_name,role_name,role_id",
        parameters,
    ).fetchall()
    for row in rows:
        for entity in ("role", "org_unit"):
            translations = row.pop(f"{entity}_translations")
            if language_tag is not None:
                row[f"{entity}_name"] = localized_projection(
                    {"name": row[f"{entity}_name"], "translations": translations},
                    language_tag, "name",
                )["name"]
        row["label"] = f"{row['org_unit_name']} — {row['role_name']}"
    return rows


def select_creator_role(
    connection: Connection, requested_role_id: int | None,
    parent_aggregation_id: int | None = None,
) -> dict:
    options = creation_role_options(connection, parent_aggregation_id)
    if not options:
        raise HTTPException(status_code=403, detail={
            "code": "creator_acl_role_not_eligible",
            "message": "You do not have a current role in the owning organizational unit.",
        })
    if requested_role_id is None:
        if len(options) != 1:
            raise HTTPException(status_code=422, detail={
                "code": "creator_acl_role_selection_required",
                "message": "Select the organizational role to create this resource for.",
            })
        return options[0]
    selected = next((row for row in options if row["role_id"] == requested_role_id), None)
    if selected is None:
        raise HTTPException(status_code=403, detail={
            "code": "creator_acl_role_not_eligible",
            "message": "The selected role is not currently eligible for this owner.",
        })
    return selected
