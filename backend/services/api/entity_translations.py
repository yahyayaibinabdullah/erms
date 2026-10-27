from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from psycopg import Connection, sql
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict

from .audit_context import decode_change_reason
from .authentication import Principal, principal_from_request
from .authorization_policy import require_global_privilege
from .concurrency import expected_version
from .database import get_connection


router = APIRouter(prefix="/api/v1/entity-translations", tags=["entity translations"])
LANGUAGE_TAG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*")


class TranslationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    title: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class EntityConfiguration:
    table: str
    primary_field: Literal["name", "title"]
    privilege: str

    @property
    def allowed_fields(self) -> frozenset[str]:
        return frozenset((self.primary_field, "description"))


ENTITY_CONFIGURATIONS = {
    "classification-schemes": EntityConfiguration(
        "classification_schemes", "title", "classification_scheme.modify_metadata"
    ),
    "classifications": EntityConfiguration(
        "classifications", "title", "classification.modify_metadata"
    ),
    "users": EntityConfiguration("users", "name", "identity.users.administer"),
    "roles": EntityConfiguration("roles", "name", "role.modify_metadata"),
    "org-units": EntityConfiguration("org_units", "name", "org_unit.modify_metadata"),
    "security-levels": EntityConfiguration(
        "security_levels", "name", "security_level.modify_metadata"
    ),
    "profiles": EntityConfiguration("profiles", "name", "profile.modify_metadata"),
}


def _error(status_code: int, code: str, message_key: str, **parameters: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail={
        "code": code,
        "message_key": message_key,
        "parameters": parameters,
    })


def _configuration(entity_type: str) -> EntityConfiguration:
    configuration = ENTITY_CONFIGURATIONS.get(entity_type)
    if configuration is None:
        raise _error(404, "unsupported_entity_type", "entity_translation.error.entity_type.unsupported")
    return configuration


def _language(connection: Connection, language_tag: str) -> str:
    candidate = language_tag.strip()
    if not LANGUAGE_TAG.fullmatch(candidate):
        raise _error(422, "invalid_language_tag", "localization.validation.language_tag.invalid", language=candidate)
    row = connection.execute(
        "SELECT language_tag FROM supported_languages WHERE lower(language_tag)=lower(%s) AND is_enabled",
        (candidate,),
    ).fetchone()
    if row is None:
        raise _error(422, "unsupported_language", "entity_translation.error.language.unsupported", language=candidate)
    return row["language_tag"]


def _row(connection: Connection, configuration: EntityConfiguration, entity_id: int, *, lock: bool = False) -> dict:
    query = sql.SQL("SELECT * FROM {} WHERE id=%s{}").format(
        sql.Identifier(configuration.table),
        sql.SQL(" FOR UPDATE") if lock else sql.SQL(""),
    )
    row = connection.execute(query, (entity_id,)).fetchone()
    if row is None:
        raise _error(404, "entity_not_found", "entity_translation.error.entity.not_found")
    return dict(row)


def _translation_read(row: dict, configuration: EntityConfiguration, language_tag: str) -> dict[str, Any]:
    translations = row.get("translations") or {}
    values = translations.get(language_tag) or {}
    return {
        "entity_id": row["id"],
        "language_tag": language_tag,
        "fields": {field: values.get(field) for field in configuration.allowed_fields},
        "canonical": {field: row.get(field) for field in configuration.allowed_fields},
        "version": row["version"],
        "date_updated": row.get("date_updated"),
    }


def _get_entity_translation(
    entity_type: str,
    entity_id: int,
    language_tag: str,
    connection: Connection,
):
    configuration = _configuration(entity_type)
    language = _language(connection, language_tag)
    return _translation_read(_row(connection, configuration, entity_id), configuration, language)


def _patch_entity_translation(
    entity_type: str,
    entity_id: int,
    language_tag: str,
    payload: TranslationPatch,
    version: int,
    change_reason: str | None,
    principal: Principal,
    connection: Connection,
):
    configuration = _configuration(entity_type)
    reason = decode_change_reason(change_reason).strip()
    if not reason:
        raise _error(422, "change_reason_required", "entity_translation.validation.change_reason.required")
    language = _language(connection, language_tag)
    supplied = set(payload.model_fields_set)
    invalid = supplied - configuration.allowed_fields
    if invalid:
        raise _error(
            422, "invalid_translation_field", "entity_translation.validation.field.invalid",
            fields=sorted(invalid),
        )
    if not supplied:
        raise _error(422, "empty_patch", "entity_translation.validation.patch.empty")

    row = _row(connection, configuration, entity_id, lock=True)
    if row["version"] != version:
        raise HTTPException(status_code=409, detail={
            "code": "stale_version",
            "message_key": "common.error.stale_version",
            "parameters": {},
            "expected_version": version,
            "actual_version": row["version"],
            "current": _translation_read(row, configuration, language),
        })

    translations = dict(row.get("translations") or {})
    localized = dict(translations.get(language) or {})
    for field in supplied:
        value = getattr(payload, field)
        if value is None:
            localized.pop(field, None)
            continue
        normalized = value.strip()
        if not normalized:
            raise _error(
                422, "blank_translation", "entity_translation.validation.translation.blank", field=field
            )
        localized[field] = normalized
    if localized:
        translations[language] = localized
    else:
        translations.pop(language, None)

    connection.execute(
        "SELECT set_config('app.change_reason',%s,true),set_config('app.user_id',%s,true)",
        (reason, str(principal.user_id)),
    )
    query = sql.SQL("UPDATE {} SET translations=%s WHERE id=%s AND version=%s RETURNING *").format(
        sql.Identifier(configuration.table)
    )
    updated = connection.execute(
        query, (Jsonb(translations) if translations else None, entity_id, version)
    ).fetchone()
    if updated is None:
        current = _row(connection, configuration, entity_id)
        raise HTTPException(status_code=409, detail={
            "code": "stale_version", "message_key": "common.error.stale_version", "parameters": {},
            "expected_version": version, "actual_version": current["version"],
        })
    return _translation_read(dict(updated), configuration, language)


def _register_entity_routes(entity_type: str, configuration: EntityConfiguration) -> None:
    privilege_dependency = require_global_privilege(configuration.privilege)

    def read_translation(
        entity_id: int,
        language_tag: str,
        connection: Connection = Depends(get_connection, scope="function"),
    ):
        return _get_entity_translation(entity_type, entity_id, language_tag, connection)

    def write_translation(
        entity_id: int,
        language_tag: str,
        payload: TranslationPatch,
        version: int = Depends(expected_version),
        change_reason: str | None = Header(None, alias="X-Change-Reason"),
        principal: Principal = Depends(principal_from_request),
        connection: Connection = Depends(get_connection, scope="function"),
    ):
        return _patch_entity_translation(
            entity_type, entity_id, language_tag, payload, version,
            change_reason, principal, connection,
        )

    read_translation.__name__ = f"get_{entity_type.replace('-', '_')}_translation"
    write_translation.__name__ = f"patch_{entity_type.replace('-', '_')}_translation"
    path = f"/{entity_type}/{{entity_id}}/{{language_tag}}"
    router.add_api_route(
        path, read_translation, methods=["GET"], dependencies=[Depends(privilege_dependency)]
    )
    router.add_api_route(
        path, write_translation, methods=["PATCH"], dependencies=[Depends(privilege_dependency)]
    )


for _entity_type, _configuration_item in ENTITY_CONFIGURATIONS.items():
    _register_entity_routes(_entity_type, _configuration_item)
