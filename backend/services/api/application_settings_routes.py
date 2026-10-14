"""Explicit authenticated settings models; no generic CRUD or secret reads."""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt
import psycopg
from psycopg import Connection

from .application_settings import _rows, _snapshot, apply_changes, cache, connection_key
from .application_settings_registry import CATEGORIES, MESSAGE_KEYS, REGISTRY, SettingsInvalid
from .authorization_policy import require_global_privilege
from .audit_context import decode_change_reason
from .database import get_connection
from .entity_localization import preferred_language


class SettingChange(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    key: str
    expected_version: StrictInt = Field(ge=1)
    value: Any = None
    secret_value: SecretStr | None = Field(default=None, repr=False)
    clear_secret: bool = False


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    changes: list[SettingChange] = Field(min_length=1, max_length=51)


class SettingRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    category: str
    category_label: str
    kind: str
    default: Any
    value: Any
    effective_value: Any
    label_key: str
    label: str
    description_key: str
    description: str
    validation: dict[str, Any]
    editable: bool
    sensitive: bool
    secret_is_set: bool | None
    provenance: str
    version: int
    date_updated: datetime
    updated_by_user_id: int | None


class SettingsRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SettingRead]
    propagation_seconds: int = 30


router = APIRouter(prefix="/api/v1/application-settings", tags=["application settings"],
                   dependencies=[Depends(require_global_privilege("app.settings.manage"))])


messages = {
    "application_settings_unavailable": "settings.error.unavailable",
    "application_settings_invalid_update": "settings.error.invalid_update",
    "application_setting_value_invalid": "settings.error.invalid_value",
    "application_settings_reason_required": "settings.error.reason_required",
    "application_settings_group_required": "settings.error.group_required",
    "application_settings_group_inconsistent": "settings.error.group_inconsistent",
    "application_settings_secret_unavailable": "settings.error.secret_unavailable",
    "application_settings_stale_version": "common.error.stale_version",
}


def settings_error(code, status=422):
    return HTTPException(status, detail={"code": code, "message_key": messages.get(code, "settings.error.unavailable"), "parameters": {}})


def _labels(c, language):
    # Bounded registry-only translated metadata, not a second authoritative cache.
    # Never expose unreviewed drafts. Exact language, base language, then English.
    languages = [language, language.split("-")[0]]
    rows = c.execute(
        """SELECT d.message_key,d.default_text,
                  COALESCE(exact.published_text,base.published_text,d.default_text) AS text
             FROM ui_message_definitions d
             LEFT JOIN ui_message_translations exact ON exact.message_key=d.message_key
              AND exact.language_tag=%s AND exact.published_text IS NOT NULL
             LEFT JOIN ui_message_translations base ON base.message_key=d.message_key
              AND base.language_tag=%s AND base.published_text IS NOT NULL
            WHERE d.message_key=ANY(%s) AND NOT d.is_deprecated""",
        (languages[0], languages[1], sorted(MESSAGE_KEYS)),
    ).fetchall()
    return {row["message_key"]: row["text"] for row in rows}


def read_settings(c, request):
    rows = _rows(c)
    snapshot = _snapshot(rows)
    labels = _labels(c, preferred_language(c, request))
    items = []
    for row in rows:
        definition = REGISTRY[row["key"]]
        category_key = f"settings.category.{definition.category}"
        items.append(SettingRead(
            key=definition.key, category=definition.category,
            category_label=labels.get(category_key, CATEGORIES[definition.category]),
            kind=definition.kind, default=definition.default,
            value=None if definition.secret else row["value"],
            effective_value=None if definition.secret else snapshot[definition.key],
            label_key=definition.label_key, label=labels.get(definition.label_key, definition.label),
            description_key=definition.description_key, description=labels.get(definition.description_key, definition.purpose),
            validation={"minimum": definition.minimum, "maximum": definition.maximum,
                        "choices": definition.choices, "nullable": definition.nullable, "group": definition.group},
            editable=definition.editable, sensitive=definition.secret,
            secret_is_set=row["secret_is_set"] if definition.secret else None,
            provenance=row["provenance"], version=row["version"],
            date_updated=row["date_updated"], updated_by_user_id=row["updated_by_user_id"],
        ))
    return SettingsRead(items=items)


@router.get("", response_model=SettingsRead)
def list_settings(request: Request, c: Connection = Depends(get_connection, scope="function")):
    try:
        return read_settings(c, request)
    except SettingsInvalid:
        raise settings_error("application_settings_unavailable", 503) from None


@router.put("", response_model=SettingsRead)
def update_settings(payload: SettingsUpdate, request: Request,
                    c: Connection = Depends(get_connection, scope="function")):
    reason = decode_change_reason(request.headers.get("X-Change-Reason", "")).strip()
    if not reason:
        raise settings_error("application_settings_reason_required")
    # The deployment encryption key is server-only. The password stays in DB
    # ciphertext; neither is returned in a SettingsRead model.
    from .application_settings_secret import encrypt
    try:
        with c.transaction():
            apply_changes(c, payload.changes, reason, encrypt_secret=encrypt)
        c.commit()  # Deferred constraints/audit complete before invalidation or success.
    except SettingsInvalid as error:
        raise settings_error(str(error), 503 if str(error) == "application_settings_secret_unavailable" else 422) from None
    except psycopg.Error as error:
        code = error.diag.message_primary
        safe_code = code if code in messages else "application_settings_invalid_update"
        raise settings_error(safe_code, 409 if error.sqlstate == "40001" else 403 if error.sqlstate == "42501" else 422) from None
    cache.invalidate(connection_key(c))
    return read_settings(c, request)
