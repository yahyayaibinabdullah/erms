"""Administration and scoped definition selectors for the two metadata catalogues."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from .authorization_admin import qualified_custodian_count
from .authorization_policy import require_global_privilege
from .concurrency import expected_version
from .continuity_lock import acquire_continuity_lock
from .database import get_connection
from .entity_localization import preferred_language, localized_projection
from .metadata_json import JsonSource
from .operation_policy import operation_policy
from .schemas import NonBlankString
from .resource_authorization import require_global


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: NonBlankString
    translations: dict[str, dict[str, str]] | None = None


class TypeDefinition(Definition):
    description: str | None = None


class ChoiceDefinition(Definition):
    display_order: int


class FieldDefinition(ChoiceDefinition):
    data_type: Literal[
        "text", "integer", "decimal", "boolean", "date", "datetime", "single_choice"
    ]
    max_length: int | None = Field(default=None, gt=0)
    required: bool = False
    # Decimal strings keep full precision through JSON transports.
    default: str | int | bool | float | None = None


class TypeGrants(BaseModel):
    model_config = ConfigDict(extra="forbid")
    see_role_ids: set[int]
    use_role_ids: set[int]


Database = Annotated[Connection, Depends(get_connection, scope="function")]
Version = Annotated[int, Depends(expected_version)]
PageSize = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def check_custodian(c, level_id):
    if level_id is not None and not qualified_custodian_count(c, level_id):
        raise HTTPException(
            409, detail={"code": "resource_without_effective_custodian"}
        )


def lock_administration(c, kind):
    acquire_continuity_lock(c)
    require_global(c, kind + "s.administer")


def type_locked(c, kind, type_id, version):
    lock_administration(c, kind)
    row = c.execute(
        "SELECT * FROM resource_types WHERE kind=%s AND id=%s FOR UPDATE",
        (kind, type_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, detail="Type not found")
    if row["version"] != version:
        raise HTTPException(412, detail="Type definition has changed")


def touch(c, kind, type_id):
    # One version protects the type, its fields, choices and grants as a unit.
    return c.execute(
        "UPDATE resource_types SET name=name WHERE kind=%s AND id=%s RETURNING version",
        (kind, type_id),
    ).fetchone()["version"]


def translated(row, language):
    return {**row, "localized": localized_projection(row, language, "name")}


def field_row(c, kind, type_id, field_id):
    row = c.execute(
        """SELECT id,name,translations,display_order,required,max_length,data_type,
                              resource_field_json(default_value) AS "default"
                       FROM resource_type_fields WHERE kind=%s AND type_id=%s AND id=%s""",
        (kind, type_id, field_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, detail="Field not found")
    return row


def catalogue(kind):
    table = "records" if kind == "record" else "aggregations"
    prefix = f"/api/v1/{kind}-types"
    admin = APIRouter(
        prefix=prefix,
        dependencies=[Depends(require_global_privilege(table + ".administer"))],
    )
    options = APIRouter(prefix=prefix)

    selector_policy = operation_policy(
        "resource_scoped",
        conditional_resource_authorization={
            "type": "effective See or Use grant or governance"
        },
    )

    def options_for(c, access, q, limit, offset, type_id=None):
        return c.execute(
            """WITH effective AS MATERIALIZED (
                SELECT r.id,r.is_information_governance FROM roles r JOIN user_role_assignments a ON a.role_id=r.id
                WHERE a.user_id=current_user_id() AND a.valid_from<=CURRENT_TIMESTAMP
                  AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP) AND role_effectively_active(r.id))
            SELECT t.* FROM resource_types t WHERE kind=%s AND (%s::bigint IS NULL OR t.id=%s)
              AND (EXISTS (SELECT FROM effective WHERE is_information_governance)
                   OR t.id IN (SELECT g.type_id FROM resource_type_role_grants g JOIN effective r ON r.id=g.role_id
                               WHERE g.kind=t.kind AND (NOT %s OR g.can_use)))
              AND (position(lower(%s) IN lower(t.name))>0 OR EXISTS (
                  SELECT FROM jsonb_each(t.translations) l WHERE position(lower(%s) IN lower(l.value->>'name'))>0))
            ORDER BY t.name,t.id LIMIT %s OFFSET %s""",
            (kind, type_id, type_id, access == "use", q, q, limit, offset),
        ).fetchall()

    @options.get("/options")
    @selector_policy
    def select_types(
        request: Request,
        c: Database,
        access: Literal["see", "use"] = "see",
        q: str = "",
        limit: PageSize = 25,
        offset: Offset = 0,
    ):
        language = preferred_language(c, request)
        return [
            translated(row, language)
            for row in options_for(c, access, q, limit, offset)
        ]

    def visible_type(c, type_id, access):
        rows = options_for(c, access, "", 1, 0, type_id)
        if not rows:
            raise HTTPException(404, detail="Type not found")
        return rows[0]

    @options.get("/options/{type_id}")
    @selector_policy
    def selected_type(
        type_id: int,
        request: Request,
        c: Database,
        access: Literal["see", "use"] = "see",
    ):
        return translated(
            visible_type(c, type_id, access), preferred_language(c, request)
        )

    @options.get("/options/{type_id}/fields")
    @selector_policy
    def selected_fields(
        type_id: int,
        request: Request,
        c: Database,
        access: Literal["see", "use"] = "see",
        limit: PageSize = 25,
        offset: Offset = 0,
    ):
        visible_type(c, type_id, access)
        language = preferred_language(c, request)
        return [translated(row, language) for row in fields(type_id, c, limit, offset)]

    @options.get("/options/{type_id}/fields/{field_id}/choices")
    @selector_policy
    def selected_choices(
        type_id: int,
        field_id: int,
        request: Request,
        c: Database,
        access: Literal["see", "use"] = "see",
        limit: PageSize = 25,
        offset: Offset = 0,
    ):
        visible_type(c, type_id, access)
        language = preferred_language(c, request)
        return [
            translated(row, language)
            for row in choices(type_id, field_id, c, limit, offset)
        ]

    @admin.get("")
    def list_types(
        request: Request,
        c: Database,
        q: str = "",
        limit: PageSize = 25,
        offset: Offset = 0,
    ):
        rows = c.execute(
            """SELECT * FROM resource_types WHERE kind=%s AND
            (position(lower(%s) IN lower(name))>0 OR EXISTS (SELECT FROM jsonb_each(translations) l
                WHERE position(lower(%s) IN lower(l.value->>'name'))>0))
            ORDER BY name,id LIMIT %s OFFSET %s""",
            (kind, q, q, limit, offset),
        ).fetchall()
        language = preferred_language(c, request)
        return [translated(row, language) for row in rows]

    @admin.post("", status_code=201)
    def create_type(body: TypeDefinition, c: Database):
        lock_administration(c, kind)
        return c.execute(
            """INSERT INTO resource_types(kind,name,description,translations) VALUES (%s,%s,%s,%s) RETURNING *""",
            (
                kind,
                body.name,
                body.description,
                Jsonb(body.translations) if body.translations else None,
            ),
        ).fetchone()

    @admin.get("/{type_id}")
    def read_type(type_id: int, c: Database):
        row = c.execute(
            "SELECT * FROM resource_types WHERE kind=%s AND id=%s", (kind, type_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, detail="Type not found")
        return row

    @admin.put("/{type_id}")
    def update_type(type_id: int, body: TypeDefinition, version: Version, c: Database):
        type_locked(c, kind, type_id, version)
        return c.execute(
            """UPDATE resource_types SET name=%s,description=%s,translations=%s
                            WHERE kind=%s AND id=%s RETURNING *""",
            (
                body.name,
                body.description,
                Jsonb(body.translations) if body.translations else None,
                kind,
                type_id,
            ),
        ).fetchone()

    @admin.delete("/{type_id}", status_code=204)
    def delete_type(type_id: int, version: Version, c: Database):
        type_locked(c, kind, type_id, version)
        c.execute("DELETE FROM resource_types WHERE kind=%s AND id=%s", (kind, type_id))

    @admin.get("/{type_id}/fields")
    def fields(type_id: int, c: Database, limit: PageSize = 25, offset: Offset = 0):
        read_type(type_id, c)
        return c.execute(
            """SELECT id,name,translations,display_order,required,max_length,data_type,
                            resource_field_json(default_value) AS "default" FROM resource_type_fields
                            WHERE kind=%s AND type_id=%s ORDER BY display_order,id LIMIT %s OFFSET %s""",
            (kind, type_id, limit, offset),
        ).fetchall()

    @admin.post("/{type_id}/fields", status_code=201)
    def create_field(
        type_id: int,
        body: FieldDefinition,
        raw: JsonSource,
        version: Version,
        c: Database,
    ):
        type_locked(c, kind, type_id, version)
        field_id = c.execute(
            """INSERT INTO resource_type_fields(kind,type_id,name,translations,display_order,required,
            max_length,data_type,default_value) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,resource_field_decode(%s,(%s::jsonb)->'default')) RETURNING id""",
            (
                kind,
                type_id,
                body.name,
                Jsonb(body.translations) if body.translations else None,
                body.display_order,
                body.required,
                body.max_length,
                body.data_type,
                body.data_type,
                raw,
            ),
        ).fetchone()["id"]
        return {
            **field_row(c, kind, type_id, field_id),
            "type_version": touch(c, kind, type_id),
        }

    @admin.put("/{type_id}/fields/{field_id}")
    def update_field(
        type_id: int,
        field_id: int,
        body: FieldDefinition,
        raw: JsonSource,
        version: Version,
        c: Database,
    ):
        type_locked(c, kind, type_id, version)
        field_row(c, kind, type_id, field_id)
        c.execute(
            """UPDATE resource_type_fields SET name=%s,translations=%s,display_order=%s,required=%s,
                     max_length=%s,data_type=%s,default_value=resource_field_decode(%s,(%s::jsonb)->'default') WHERE id=%s""",
            (
                body.name,
                Jsonb(body.translations) if body.translations else None,
                body.display_order,
                body.required,
                body.max_length,
                body.data_type,
                body.data_type,
                raw,
                field_id,
            ),
        )
        return {
            **field_row(c, kind, type_id, field_id),
            "type_version": touch(c, kind, type_id),
        }

    @admin.delete("/{type_id}/fields/{field_id}", status_code=204)
    def delete_field(type_id: int, field_id: int, version: Version, c: Database):
        type_locked(c, kind, type_id, version)
        field_row(c, kind, type_id, field_id)
        c.execute("DELETE FROM resource_type_fields WHERE id=%s", (field_id,))
        touch(c, kind, type_id)

    @admin.get("/{type_id}/fields/{field_id}/choices")
    def choices(
        type_id: int,
        field_id: int,
        c: Database,
        limit: PageSize = 25,
        offset: Offset = 0,
    ):
        field_row(c, kind, type_id, field_id)
        return c.execute(
            """SELECT id,name,translations,display_order FROM resource_field_choices
                            WHERE field_id=%s ORDER BY display_order,id LIMIT %s OFFSET %s""",
            (field_id, limit, offset),
        ).fetchall()

    @admin.post("/{type_id}/fields/{field_id}/choices", status_code=201)
    def create_choice(
        type_id: int,
        field_id: int,
        body: ChoiceDefinition,
        version: Version,
        c: Database,
    ):
        type_locked(c, kind, type_id, version)
        field_row(c, kind, type_id, field_id)
        row = c.execute(
            """INSERT INTO resource_field_choices(field_id,name,translations,display_order)
            VALUES (%s,%s,%s,%s) RETURNING id,name,translations,display_order""",
            (
                field_id,
                body.name,
                Jsonb(body.translations) if body.translations else None,
                body.display_order,
            ),
        ).fetchone()
        return {**row, "type_version": touch(c, kind, type_id)}

    @admin.put("/{type_id}/fields/{field_id}/choices/{choice_id}")
    def update_choice(
        type_id: int,
        field_id: int,
        choice_id: int,
        body: ChoiceDefinition,
        version: Version,
        c: Database,
    ):
        type_locked(c, kind, type_id, version)
        field_row(c, kind, type_id, field_id)
        row = c.execute(
            """UPDATE resource_field_choices SET name=%s,translations=%s,display_order=%s
            WHERE field_id=%s AND id=%s RETURNING id,name,translations,display_order""",
            (
                body.name,
                Jsonb(body.translations) if body.translations else None,
                body.display_order,
                field_id,
                choice_id,
            ),
        ).fetchone()
        if row is None:
            raise HTTPException(404, detail="Choice not found")
        return {**row, "type_version": touch(c, kind, type_id)}

    @admin.delete("/{type_id}/fields/{field_id}/choices/{choice_id}", status_code=204)
    def delete_choice(
        type_id: int, field_id: int, choice_id: int, version: Version, c: Database
    ):
        type_locked(c, kind, type_id, version)
        field_row(c, kind, type_id, field_id)
        if not c.execute(
            "DELETE FROM resource_field_choices WHERE field_id=%s AND id=%s",
            (field_id, choice_id),
        ).rowcount:
            raise HTTPException(404, detail="Choice not found")
        touch(c, kind, type_id)

    @admin.get("/{type_id}/role-grants")
    def grants(type_id: int, c: Database, limit: PageSize = 25, offset: Offset = 0):
        read_type(type_id, c)
        return c.execute(
            """SELECT role_id,can_use FROM resource_type_role_grants WHERE kind=%s AND type_id=%s
                            ORDER BY role_id LIMIT %s OFFSET %s""",
            (kind, type_id, limit, offset),
        ).fetchall()

    @admin.put("/{type_id}/role-grants")
    def replace_grants(type_id: int, body: TypeGrants, version: Version, c: Database):
        type_locked(c, kind, type_id, version)
        if not body.use_role_ids <= body.see_role_ids:
            raise HTTPException(422, detail="Use requires See for the same role")
        level = c.execute(
            f"""SELECT l.id FROM security_levels l WHERE EXISTS
                        (SELECT FROM {table} r WHERE r.security_level_id=l.id AND r.type_id=%s)
                        ORDER BY l.level_number DESC LIMIT 1""",
            (type_id,),
        ).fetchone()
        if level:
            check_custodian(c, level["id"])
        c.execute(
            """DELETE FROM resource_type_role_grants WHERE kind=%s AND type_id=%s
                     AND NOT (role_id=ANY(%s::bigint[]))""",
            (kind, type_id, list(body.see_role_ids)),
        )
        c.execute(
            """INSERT INTO resource_type_role_grants(kind,type_id,role_id,can_use)
            SELECT %s,%s,id,id=ANY(%s::bigint[]) FROM unnest(%s::bigint[]) id
            ON CONFLICT (kind,type_id,role_id) DO UPDATE SET can_use=excluded.can_use
            WHERE resource_type_role_grants.can_use IS DISTINCT FROM excluded.can_use""",
            (kind, type_id, list(body.use_role_ids), sorted(body.see_role_ids)),
        )
        return {"version": touch(c, kind, type_id)}

    return options, admin


router = APIRouter()
for resource_kind in ("aggregation", "record"):
    for routes in catalogue(resource_kind):
        router.include_router(routes)
