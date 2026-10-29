from __future__ import annotations

from datetime import datetime
from collections import Counter, defaultdict
from hashlib import sha256
import gzip
import json
import logging
from pathlib import Path
import re
from threading import RLock
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .audit_context import decode_change_reason
from .authentication import Principal, principal_from_request
from .authorization_policy import require_global_privilege
from .config import default_working_timezone
from .application_configuration import ui_configuration
from .database import get_connection, pool


router = APIRouter(prefix="/api/v1", tags=["internationalization"])
require_localization_admin = require_global_privilege("localization.administer")
PLACEHOLDER_PATTERN = re.compile(r"(?<!\{)\{([a-z][a-z0-9_]*)\}(?!\})")
DISALLOWED_MARKUP = re.compile(r"<[^>]+>")
_catalogue_cache: dict[tuple[str, int], tuple[str, bytes, bytes]] = {}
_catalogue_cache_lock = RLock()
_metrics_lock = RLock()
_metrics: Counter[str] = Counter()
_language_metrics: defaultdict[str, Counter[str]] = defaultdict(Counter)
logger = logging.getLogger(__name__)


def _record_metric(name: str, language_tag: str | None = None, amount: int = 1) -> None:
    with _metrics_lock:
        _metrics[name] += amount
        if language_tag:
            _language_metrics[language_tag][name] += amount


def localization_metrics() -> dict[str, Any]:
    with _metrics_lock:
        return {
            **dict(_metrics),
            "by_language": {tag: dict(values) for tag, values in _language_metrics.items()},
        }


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LanguageRead(StrictModel):
    language_tag: str
    english_name: str
    native_name: str
    direction: str
    catalogue_revision: int
    formatting_config: dict[str, Any]


class PreferenceUpdate(StrictModel):
    language_tag: str = Field(min_length=2, max_length=64)
    working_timezone: str = Field(min_length=1, max_length=255)


class PreferenceRead(PreferenceUpdate):
    direction: str
    persisted: bool
    version: int
    date_updated: datetime | None = None


class BootstrapRead(StrictModel):
    effective_language: str
    direction: str
    working_timezone: str
    fallback_language: str
    supported_languages: list[LanguageRead]
    catalogue_revision: int
    catalogue_url: str
    application_configuration: dict[str, Any]
    uses_default_working_timezone: bool


class LanguageCreate(StrictModel):
    language_tag: str = Field(min_length=2, max_length=64)
    english_name: str = Field(min_length=1, max_length=200)
    native_name: str = Field(min_length=1, max_length=200)
    direction: str
    is_enabled: bool = True
    is_default: bool = False
    formatting_config: dict[str, Any] = Field(default_factory=dict)


class LanguageUpdate(StrictModel):
    english_name: str = Field(min_length=1, max_length=200)
    native_name: str = Field(min_length=1, max_length=200)
    direction: str
    is_enabled: bool
    is_default: bool
    formatting_config: dict[str, Any]


class TranslationUpdate(StrictModel):
    translated_text: str
    origin: str = "manual"
    reviewed: bool = False
    generation_metadata: dict[str, Any] | None = None


class BulkTranslationItem(StrictModel):
    message_key: str = Field(min_length=1, max_length=500)
    version: int = Field(ge=1)


class BulkTranslationPublication(StrictModel):
    items: list[BulkTranslationItem] = Field(min_length=1, max_length=5_000)


class GeneratedTranslationCandidate(StrictModel):
    message_key: str = Field(min_length=1, max_length=500)
    translated_text: str = Field(min_length=1, max_length=20_000)
    quality_flags: list[str] = Field(default_factory=list, max_length=20)


class GenerationBatch(StrictModel):
    generator: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)
    model_version: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=200)
    specification_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalogue_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    terminology_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    batch_id: str = Field(min_length=1, max_length=200)
    generated_at: AwareDatetime
    items: list[GeneratedTranslationCandidate] = Field(min_length=1, max_length=5_000)


class TranslationArtifactImport(StrictModel):
    artifact: dict[str, Any]


ARABIC_TERMINOLOGY = {
    "Record": "وثيقة",
    "Records": "وثائق",
    "Aggregation": "ملف",
    "Aggregations": "ملفات",
    "Parent aggregation": "الملف الحاوي",
    "Containing aggregation": "الملف الحاوي",
    "Scheme": "نظام التصنيف",
    "Schemes": "نظم التصنيف",
    "Classification": "تصنيف",
    "Classifications": "تصنيفات",
    "Digital component": "المكوّن الرقمي",
    "Digital components": "المكوّنات الرقمية",
    "Sharjah Archives": "دار الوثائق في إمارة الشارقة",
    "Audit Trail": "مسار التتبع",
    "Current period": "الفترة الجارية",
    "Intermediate period": "الفترة الوسيطة",
    "Destruction": "الإتلاف",
    "Disposition Job": "عملية تصرف",
    "Disposition Jobs": "عمليات التصرف",
    "Destruction Job": "عملية إتلاف",
    "Task": "مهمة",
    "Tasks": "مهام",
    "My Tasks": "مهامي",
    "Role": "الدور",
    "Legal Hold": "تعليق القنوني",
    "Mixed (record medium)": "هجين",
    "Physical (record medium)": "مادي",
    "Records Unit (organizational unit)": "وحدة الوثائق",
    "Retention Rule": "قاعدة الحفظ",
    "Security Level": "درجة السرية",
    "Selective Preservation": "الإنتقاء",
    "Permanent Preservation": "حفظ الدائم",
    "Vital record": "الوثائق الهيوية",
    "Close (aggregation lifecycle action)": "إغلاق",
    "Checksum": "مجموع التحقق",
    "Inherit": "يستمد",
    "System Administrator": "مسؤول النظام",
    "Delete": "حذف",
    "Filter": "التصفية",
    "Dashboard": "لوحة المعلومات",
    "Title": "العنوان",
}


def _error(status_code: int, code: str, message_key: str, **parameters: object) -> HTTPException:
    return HTTPException(status_code=status_code, detail={
        "code": code,
        "message_key": message_key,
        "parameters": parameters,
    })


def _stale_version(expected: int, actual: int, current: dict | None = None) -> HTTPException:
    detail: dict[str, Any] = {
        "code": "stale_version",
        "message_key": "common.error.stale_version",
        "parameters": {},
        "expected_version": expected,
        "actual_version": actual,
    }
    if current is not None:
        detail["current"] = jsonable_encoder(current)
    return HTTPException(status_code=409, detail=detail)


def _required_reason(change_reason: str | None) -> str:
    reason = decode_change_reason(change_reason).strip()
    if not reason:
        raise _error(400, "change_reason_required", "localization.validation.change_reason.required")
    if len(reason) > 2000:
        raise _error(400, "change_reason_too_long", "localization.validation.change_reason.too_long")
    return reason


def _canonical_language_tag(value: str) -> str:
    pieces = value.strip().split("-")
    if not pieces or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value.strip()):
        raise _error(422, "invalid_language_tag", "localization.validation.language_tag.invalid", language=value)
    canonical = [pieces[0].lower()]
    for piece in pieces[1:]:
        canonical.append(piece.upper() if len(piece) == 2 and piece.isalpha() else piece.title() if len(piece) == 4 and piece.isalpha() else piece.lower())
    return "-".join(canonical)


def _template_parameters(text: str) -> set[str]:
    stripped = PLACEHOLDER_PATTERN.sub("", text).replace("{{", "").replace("}}", "")
    if "{" in stripped or "}" in stripped:
        raise ValueError("invalid brace or placeholder syntax")
    return set(PLACEHOLDER_PATTERN.findall(text))


def _validate_translation(definition: dict, text: str) -> tuple[str, list[str], list[str]]:
    normalized = text.strip()
    if not normalized:
        _record_metric("invalid_translation_syntax")
        raise _error(422, "blank_translation", "localization.validation.translation.blank")
    try:
        actual = _template_parameters(normalized)
    except ValueError as exception:
        _record_metric("invalid_translation_syntax")
        raise _error(422, "invalid_template", "localization.validation.template.invalid") from exception
    expected = set(definition["parameter_schema"])
    missing, unexpected = sorted(expected - actual), sorted(actual - expected)
    if missing or unexpected:
        _record_metric("invalid_translation_syntax")
        raise _error(422, "placeholder_mismatch", "localization.validation.placeholders.mismatch", missing=missing, unexpected=unexpected)
    if not definition["is_html"] and DISALLOWED_MARKUP.search(normalized):
        _record_metric("invalid_translation_syntax")
        raise _error(422, "markup_not_allowed", "localization.validation.markup.not_allowed")
    return normalized, missing, unexpected


def _set_reason(connection: Connection, reason: str, user_id: int | None = None) -> None:
    connection.execute(
        "SELECT set_config('app.change_reason',%s,true),set_config('app.user_id',%s,true)",
        (reason, str(user_id) if user_id is not None else ""),
    )


def _validated_timezone(value: str) -> str:
    candidate = value.strip()
    try:
        zone = ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as exception:
        _record_metric("preference_validation_failures")
        _record_metric("timezone_resolution_failures")
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_working_timezone",
            "preferences.validation.working_timezone.invalid",
            timezone=candidate,
        ) from exception
    if zone.key != candidate:
        _record_metric("preference_validation_failures")
        _record_metric("timezone_resolution_failures")
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_working_timezone",
            "preferences.validation.working_timezone.invalid",
            timezone=candidate,
        )
    return candidate


def _languages(connection: Connection) -> list[dict]:
    return list(connection.execute(
        """SELECT language_tag,english_name,native_name,direction,catalogue_revision,formatting_config
             FROM supported_languages WHERE is_enabled ORDER BY is_default DESC,english_name,id"""
    ).fetchall())


def synchronize_message_definitions() -> None:
    path = Path(__file__).resolve().parents[3] / "frontend" / "webui" / "i18n" / "messages.en.json"
    definitions = json.loads(path.read_text(encoding="utf-8"))
    with pool.connection() as connection:
        connection.execute(
            """SELECT set_config('app.actor_type','automated_process',true),
                      set_config('app.event_source','seeding',true),
                      set_config('app.change_reason','Synchronize checked-in English UI message definitions',true),
                      set_config('app.event_metadata','{"source":"messages.en.json"}',true)"""
        )
        existing_count = connection.execute("SELECT count(*) AS value FROM ui_message_definitions").fetchone()["value"]
        catalogue_changed = False
        manifest_keys: list[str] = []
        for item in definitions:
            manifest_keys.append(item["message_key"])
            prior = connection.execute(
                "SELECT default_text,parameter_schema FROM ui_message_definitions WHERE message_key=%s",
                (item["message_key"],),
            ).fetchone()
            connection.execute(
                """INSERT INTO ui_message_definitions(
                       message_key,context_group,default_text,semantic_meaning,common_locations,
                       translator_guidance,grammatical_role,parameter_schema,rendered_example,is_html
                   ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(message_key) DO UPDATE SET
                       context_group=EXCLUDED.context_group,default_text=EXCLUDED.default_text,
                       semantic_meaning=EXCLUDED.semantic_meaning,common_locations=EXCLUDED.common_locations,
                       translator_guidance=EXCLUDED.translator_guidance,grammatical_role=EXCLUDED.grammatical_role,
                       parameter_schema=EXCLUDED.parameter_schema,rendered_example=EXCLUDED.rendered_example,
                       is_html=EXCLUDED.is_html,is_deprecated=false
                   WHERE (ui_message_definitions.context_group,ui_message_definitions.default_text,
                          ui_message_definitions.semantic_meaning,ui_message_definitions.common_locations,
                          ui_message_definitions.translator_guidance,ui_message_definitions.grammatical_role,
                          ui_message_definitions.parameter_schema,ui_message_definitions.rendered_example,
                          ui_message_definitions.is_html,ui_message_definitions.is_deprecated)
                     IS DISTINCT FROM
                         (EXCLUDED.context_group,EXCLUDED.default_text,EXCLUDED.semantic_meaning,EXCLUDED.common_locations,
                          EXCLUDED.translator_guidance,EXCLUDED.grammatical_role,EXCLUDED.parameter_schema,
                          EXCLUDED.rendered_example,EXCLUDED.is_html,false)""",
                (
                    item["message_key"], item["context_group"], item["default_text"], item["semantic_meaning"],
                    Jsonb(item["common_locations"]), item["translator_guidance"], item["grammatical_role"],
                    Jsonb(item["parameter_schema"]), item["rendered_example"], bool(item.get("is_html", False)),
                ),
            )
            source_changed = prior is not None and (
                prior["default_text"] != item["default_text"] or prior["parameter_schema"] != item["parameter_schema"]
            )
            catalogue_changed = catalogue_changed or (existing_count > 0 and (prior is None or source_changed))
            if source_changed:
                connection.execute(
                    """UPDATE ui_message_translations SET
                           translated_text=CASE WHEN origin='source_copy' THEN %s ELSE translated_text END,
                           needs_review=true,status='draft'
                         WHERE message_key=%s""",
                    (item["default_text"], item["message_key"]),
                )
            connection.execute(
                """INSERT INTO ui_message_translations(message_key,language_tag,translated_text,status,origin)
                   SELECT %s,language.language_tag,%s,'draft','source_copy'
                     FROM supported_languages language
                    WHERE lower(language.language_tag)<>'en'
                   ON CONFLICT(message_key,language_tag) DO NOTHING""",
                (item["message_key"], item["default_text"]),
            )
        deprecated = connection.execute(
            """UPDATE ui_message_definitions SET is_deprecated=true
                 WHERE NOT is_deprecated AND NOT (message_key=ANY(%s)) RETURNING message_key""",
            (manifest_keys,),
        ).fetchall()
        catalogue_changed = catalogue_changed or bool(deprecated)
        if catalogue_changed:
            connection.execute("UPDATE supported_languages SET catalogue_revision=catalogue_revision+1")
            clear_catalogue_cache()


def synchronize_generated_arabic_drafts(*, missing_only: bool = False) -> dict[str, int]:
    """Seed source copies; optionally preserve even explicitly superseded text."""
    path = Path(__file__).resolve().parents[3] / "frontend/webui/i18n/messages.ar.generated.json"
    if not path.exists():
        return {
            "stored": 0,
            "corrected": 0,
            "protected": 0,
            "failed": 0,
            "awaiting_generation": 0,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    superseded = payload.get("superseded_translations", {})
    common_metadata = {
        key: payload[key] for key in (
            "generator", "model", "model_version", "prompt_version",
            "specification_sha256", "catalogue_sha256", "terminology_sha256",
            "batch_id", "generated_at",
        )
    }
    counts = {
        "stored": 0,
        "corrected": 0,
        "protected": 0,
        "failed": 0,
        "awaiting_generation": 0,
    }
    with pool.connection() as connection:
        connection.execute(
            """SELECT set_config('app.actor_type','automated_process',true),
                      set_config('app.event_source','seeding',true),
                      set_config('app.change_reason','Seed approved Phase 6 Arabic generated drafts',true),
                      set_config('app.event_metadata',%s,true)""",
            (json.dumps({"source": path.name, "batch_id": payload["batch_id"]}),),
        )
        definitions = {
            row["message_key"]: row
            for row in connection.execute(
                "SELECT * FROM ui_message_definitions WHERE NOT is_deprecated"
            ).fetchall()
        }
        candidates = []
        for item in payload["items"]:
            definition = definitions.get(item["message_key"])
            if definition is None:
                counts["failed"] += 1
                continue
            try:
                normalized, _, _ = _validate_translation(definition, item["translated_text"])
            except HTTPException:
                counts["failed"] += 1
                continue
            export_provenance = item.get("provenance") if isinstance(item.get("provenance"), dict) else None
            seed_origin = "imported" if export_provenance else "generated"
            # A canonical admin export may later gain newly generated entries.
            # Preserve imported provenance while recording the generating batch
            # of each new entry, rather than attributing it to the old export.
            item_metadata = dict(common_metadata)
            generation_metadata = item.get("generation_metadata")
            if not export_provenance and isinstance(generation_metadata, dict):
                item_metadata.update({
                    key: generation_metadata[key]
                    for key in common_metadata if key in generation_metadata
                })
            candidates.append((
                item["message_key"], normalized,
                seed_origin,
                Jsonb({
                    **item_metadata,
                    "quality_flags": item.get("quality_flags", []),
                    **({"export_provenance": export_provenance} if export_provenance else {}),
                }),
                list(superseded.get(item["message_key"], [])),
            ))
        connection.execute(
            """CREATE TEMP TABLE generated_arabic_seed(
                   message_key text PRIMARY KEY,
                   translated_text text NOT NULL,
                   origin text NOT NULL,
                   generation_metadata jsonb NOT NULL,
                   superseded_texts text[] NOT NULL
               ) ON COMMIT DROP"""
        )
        with connection.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO generated_arabic_seed(
                       message_key,translated_text,origin,generation_metadata,superseded_texts
                   ) VALUES(%s,%s,%s,%s,%s)""",
                candidates,
            )
        stored = connection.execute(
            """UPDATE ui_message_translations translation SET
                   translated_text=seed.translated_text,
                   status='draft',origin=seed.origin,
                   generation_metadata=seed.generation_metadata,
                   needs_review=false,
                   reviewed_by_user_id=NULL,date_reviewed=NULL,
                   published_text=NULL,published_by_user_id=NULL,date_published=NULL
                 FROM generated_arabic_seed seed
                WHERE translation.message_key=seed.message_key
                  AND translation.language_tag='ar'
                  AND translation.origin='source_copy'
                  AND translation.reviewed_by_user_id IS NULL
                  AND translation.published_text IS NULL
            RETURNING translation.message_key"""
        ).fetchall()
        counts["stored"] = len(stored)
        corrected = connection.execute(
            """UPDATE ui_message_translations translation SET
                   translated_text=seed.translated_text,
                   status='draft',origin=seed.origin,
                   generation_metadata=seed.generation_metadata,
                   needs_review=false,
                   reviewed_by_user_id=NULL,date_reviewed=NULL,
                   published_text=NULL,published_by_user_id=NULL,date_published=NULL
                 FROM generated_arabic_seed seed
                WHERE translation.message_key=seed.message_key
                  AND translation.language_tag='ar'
                  AND translation.translated_text=ANY(seed.superseded_texts)
                  AND translation.translated_text IS DISTINCT FROM seed.translated_text
                  AND NOT %s
                  AND NOT (
                      translation.origin='source_copy'
                      AND translation.reviewed_by_user_id IS NULL
                      AND translation.published_text IS NULL
                  )
            RETURNING translation.message_key""",
            (missing_only,),
        ).fetchall()
        counts["corrected"] = len(corrected)
        counts["protected"] = len(candidates) - counts["stored"] - counts["corrected"]
        counts["awaiting_generation"] = connection.execute(
            """SELECT count(*) AS value
                 FROM ui_message_definitions definition
                 LEFT JOIN ui_message_translations translation
                   ON translation.message_key=definition.message_key
                  AND translation.language_tag='ar'
                WHERE NOT definition.is_deprecated
                  AND (translation.message_key IS NULL OR translation.origin='source_copy')"""
        ).fetchone()["value"]
    logger.info("localization_arabic_generation_seeded", extra=counts)
    return counts


def clear_catalogue_cache(language_tag: str | None = None) -> None:
    with _catalogue_cache_lock:
        for key in list(_catalogue_cache):
            if language_tag is None or key[0].lower() == language_tag.lower():
                _catalogue_cache.pop(key, None)
    _record_metric("cache_invalidations", language_tag)
    logger.info("localization_cache_invalidated", extra={"language_tag": language_tag or "all"})


def _preference(connection: Connection, user_id: int) -> dict | None:
    return connection.execute(
        """SELECT p.language_tag,p.working_timezone,p.version,p.date_updated,l.direction,l.is_enabled
             FROM user_preferences p JOIN supported_languages l USING(language_tag)
            WHERE p.user_id=%s""",
        (user_id,),
    ).fetchone()


def _effective_preference(connection: Connection, user_id: int, *, include_context=False) -> dict:
    stored = _preference(connection, user_id)
    if stored and stored["is_enabled"]:
        stored.pop("is_enabled", None)
        return {**stored, "persisted": True, **({"uses_default_working_timezone":False} if include_context else {})}
    language = connection.execute(
        "SELECT language_tag,direction FROM supported_languages WHERE is_default AND is_enabled"
    ).fetchone()
    if language is None:
        raise RuntimeError("an enabled default language is required")
    return {
        "language_tag": language["language_tag"],
        "working_timezone": default_working_timezone(connection),
        **({"uses_default_working_timezone":True} if include_context else {}),
        "direction": language["direction"],
        "persisted": stored is not None,
        "version": stored["version"] if stored else 0,
        "date_updated": stored["date_updated"] if stored else None,
    }


def _expected_preference_version(if_match: str | None) -> int:
    if if_match is None:
        raise _error(428, "precondition_required", "common.error.precondition_required")
    value = if_match.strip()
    if value.startswith("W/"):
        value = value[2:].strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    try:
        version = int(value)
    except ValueError as exception:
        raise _error(400, "invalid_version", "common.error.invalid_version") from exception
    if version < 0:
        raise _error(400, "invalid_version", "common.error.invalid_version")
    return version


@router.get("/preferences", response_model=PreferenceRead)
def get_preferences(
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    return _effective_preference(connection, principal.user_id)


@router.put("/preferences", response_model=PreferenceRead)
def update_preferences(
    payload: PreferenceUpdate,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    expected = _expected_preference_version(if_match)
    timezone_name = _validated_timezone(payload.working_timezone)
    language_tag = payload.language_tag.strip().lower()
    enabled = connection.execute(
        "SELECT language_tag FROM supported_languages WHERE lower(language_tag)=lower(%s) AND is_enabled",
        (language_tag,),
    ).fetchone()
    if enabled is None:
        raise _error(422, "unsupported_language", "preferences.validation.language.unsupported", language=language_tag)
    language_tag = enabled["language_tag"]

    current = connection.execute(
        "SELECT version FROM user_preferences WHERE user_id=%s FOR UPDATE",
        (principal.user_id,),
    ).fetchone()
    actual = current["version"] if current else 0
    if actual != expected:
        raise _stale_version(expected, actual)
    if current:
        connection.execute(
            "UPDATE user_preferences SET language_tag=%s,working_timezone=%s WHERE user_id=%s",
            (language_tag, timezone_name, principal.user_id),
        )
    else:
        connection.execute(
            "INSERT INTO user_preferences(user_id,language_tag,working_timezone) VALUES (%s,%s,%s)",
            (principal.user_id, language_tag, timezone_name),
        )
    preference = _preference(connection, principal.user_id)
    preference.pop("is_enabled", None)
    return {**preference, "persisted": True}


@router.get("/i18n/bootstrap", response_model=BootstrapRead)
def bootstrap(
    response: Response,
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    languages = _languages(connection)
    preference = _effective_preference(connection, principal.user_id, include_context=True)
    fallback = connection.execute(
        "SELECT language_tag FROM supported_languages WHERE is_default AND is_enabled"
    ).fetchone()
    if fallback is None:
        raise RuntimeError("an enabled default language is required")
    effective_language = next(
        item for item in languages
        if item["language_tag"].lower() == preference["language_tag"].lower()
    )
    revision = effective_language["catalogue_revision"]
    response.headers["Cache-Control"] = "private, max-age=60"
    response.headers["Vary"] = "Authorization, Cookie"
    return {
        "effective_language": preference["language_tag"],
        "direction": preference["direction"],
        "working_timezone": preference["working_timezone"],
        "fallback_language": fallback["language_tag"],
        "supported_languages": languages,
        "catalogue_revision": revision,
        "catalogue_url": f"/api/v1/i18n/catalogues/{preference['language_tag']}",
        "application_configuration": ui_configuration(connection),
        "uses_default_working_timezone": preference["uses_default_working_timezone"],
    }


def _compiled_catalogue(
    connection: Connection, language_tag: str, revision: int,
) -> tuple[str, bytes, bytes]:
    cache_key = (language_tag, revision)
    with _catalogue_cache_lock:
        cached = _catalogue_cache.get(cache_key)
    if cached:
        _record_metric("cache_hits", language_tag)
        return cached
    _record_metric("cache_misses", language_tag)
    started = perf_counter()
    base_tag = language_tag.split("-", 1)[0] if "-" in language_tag else None
    rows = connection.execute(
        """SELECT definition.message_key,definition.default_text,
                  exact.published_text AS exact_text,base.published_text AS base_text
             FROM ui_message_definitions definition
             LEFT JOIN ui_message_translations exact
               ON exact.message_key=definition.message_key AND lower(exact.language_tag)=lower(%s)
              AND exact.published_text IS NOT NULL AND NOT exact.needs_review
             LEFT JOIN ui_message_translations base
               ON base.message_key=definition.message_key AND lower(base.language_tag)=lower(%s)
              AND base.published_text IS NOT NULL AND NOT base.needs_review
            WHERE NOT definition.is_deprecated ORDER BY definition.message_key""",
        (language_tag, base_tag or language_tag),
    ).fetchall()
    payload = {
        "language_tag": language_tag,
        "revision": revision,
        "messages": {row["message_key"]: row["exact_text"] or row["base_text"] or row["default_text"] for row in rows},
        "fallback_keys": [
            row["message_key"] for row in rows
            if not row["exact_text"] and not row["base_text"]
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    result = (
        '"' + sha256(encoded).hexdigest() + '"',
        encoded,
        gzip.compress(encoded, compresslevel=5, mtime=0),
    )
    fallback_count = sum(
        1 for row in rows if not row["exact_text"] and not row["base_text"]
    )
    _record_metric("fallback_messages", language_tag, fallback_count)
    compile_microseconds = max(1, round((perf_counter() - started) * 1_000_000))
    _record_metric("catalogue_compile_microseconds", language_tag, compile_microseconds)
    logger.info(
        "localization_catalogue_compiled",
        extra={
            "language_tag": language_tag,
            "revision": revision,
            "message_count": len(rows),
            "fallback_count": fallback_count,
            "compile_microseconds": compile_microseconds,
        },
    )
    with _catalogue_cache_lock:
        _catalogue_cache[cache_key] = result
    return result


def localization_readiness(connection: Connection) -> dict[str, Any]:
    timezone_name = default_working_timezone(connection)
    language = connection.execute(
        "SELECT language_tag,catalogue_revision FROM supported_languages WHERE is_default AND is_enabled"
    ).fetchone()
    if language is None:
        raise RuntimeError("an enabled default language is required")
    etag, _, _ = _compiled_catalogue(
        connection, language["language_tag"], language["catalogue_revision"],
    )
    return {
        "ready": True,
        "default_language": language["language_tag"],
        "default_working_timezone": timezone_name,
        "default_catalogue_etag": etag,
        "metrics": localization_metrics(),
    }


@router.get("/i18n/catalogues/{language_tag}", response_model=None)
def catalogue(
    language_tag: str,
    request: Request,
    principal: Principal = Depends(principal_from_request),
    connection: Connection = Depends(get_connection, scope="function"),
):
    del principal
    language = connection.execute(
        "SELECT language_tag,catalogue_revision FROM supported_languages WHERE lower(language_tag)=lower(%s) AND is_enabled",
        (language_tag,),
    ).fetchone()
    if language is None:
        raise _error(404, "unsupported_language", "preferences.validation.language.unsupported", language=language_tag)
    etag, encoded, compressed = _compiled_catalogue(
        connection, language["language_tag"], language["catalogue_revision"],
    )
    accepts_gzip = "gzip" in request.headers.get("Accept-Encoding", "").lower()
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=300, stale-while-revalidate=60",
        "Vary": "Authorization, Cookie, Accept-Encoding",
    }
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers=headers)
    if accepts_gzip:
        headers["Content-Encoding"] = "gzip"
    return Response(
        content=compressed if accepts_gzip else encoded,
        media_type="application/json",
        headers=headers,
    )


def _language_result(row: dict) -> dict:
    return dict(row)


@router.get("/admin/i18n/languages")
def admin_languages(
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection, scope="function"),
):
    return list(connection.execute("SELECT * FROM supported_languages ORDER BY is_default DESC,english_name,id").fetchall())


@router.post("/admin/i18n/languages", status_code=201)
def create_language(
    payload: LanguageCreate,
    change_reason: str | None = Header(default=None, alias="X-Change-Reason"),
    principal: Principal = Depends(principal_from_request),
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection, scope="function"),
):
    reason = _required_reason(change_reason)
    _set_reason(connection, reason, principal.user_id)
    tag = _canonical_language_tag(payload.language_tag)
    if payload.direction not in {"ltr", "rtl"}:
        raise _error(422, "invalid_direction", "localization.validation.direction.invalid")
    if payload.is_default and not payload.is_enabled:
        raise _error(422, "default_language_disabled", "localization.validation.default_language.disabled")
    if payload.is_enabled:
        from .messaging.notification_configuration import language_ready
        language_ready(connection, tag)
    if payload.is_default:
        connection.execute("UPDATE supported_languages SET is_default=false WHERE is_default")
    try:
        row = connection.execute(
            """INSERT INTO supported_languages(language_tag,english_name,native_name,direction,is_enabled,is_default,formatting_config)
               VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (tag,payload.english_name.strip(),payload.native_name.strip(),payload.direction,payload.is_enabled,payload.is_default,Jsonb(payload.formatting_config)),
        ).fetchone()
    except Exception as exception:
        if getattr(exception, "sqlstate", None) == "23505":
            raise _error(409, "language_exists", "localization.validation.language.exists", language=tag) from exception
        raise
    connection.execute(
        """INSERT INTO ui_message_translations(message_key,language_tag,translated_text,status,origin,updated_by_user_id)
           SELECT message_key,%s,default_text,'draft','source_copy',%s FROM ui_message_definitions
           ON CONFLICT DO NOTHING""",
        (tag,principal.user_id),
    )
    return _language_result(row)


@router.put("/admin/i18n/languages/{language_tag}")
def update_language(
    language_tag: str,
    payload: LanguageUpdate,
    if_match: str | None = Header(default=None, alias="If-Match"),
    change_reason: str | None = Header(default=None, alias="X-Change-Reason"),
    principal: Principal = Depends(principal_from_request),
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection, scope="function"),
):
    reason = _required_reason(change_reason)
    expected = _expected_preference_version(if_match)
    if expected == 0:
        raise _error(400, "invalid_version", "common.error.invalid_version")
    if payload.direction not in {"ltr", "rtl"} or (payload.is_default and not payload.is_enabled):
        raise _error(422, "invalid_language_configuration", "localization.validation.language.configuration_invalid")
    _set_reason(connection, reason, principal.user_id)
    current = connection.execute(
        "SELECT * FROM supported_languages WHERE lower(language_tag)=lower(%s) FOR UPDATE", (language_tag,),
    ).fetchone()
    if current is None:
        raise _error(404, "language_not_found", "localization.validation.language.not_found", language=language_tag)
    if current["is_default"] and not payload.is_default:
        raise _error(422, "default_language_required", "localization.validation.language.configuration_invalid")
    if current["version"] != expected:
        raise _stale_version(expected, current["version"], dict(current))
    if payload.is_enabled:
        from .messaging.notification_configuration import language_ready
        language_ready(connection, current["language_tag"])
    if payload.is_default:
        connection.execute("UPDATE supported_languages SET is_default=false WHERE is_default AND id<>%s", (current["id"],))
    row = connection.execute(
        """UPDATE supported_languages SET english_name=%s,native_name=%s,direction=%s,is_enabled=%s,is_default=%s,formatting_config=%s
             WHERE id=%s RETURNING *""",
        (payload.english_name.strip(),payload.native_name.strip(),payload.direction,payload.is_enabled,payload.is_default,Jsonb(payload.formatting_config),current["id"]),
    ).fetchone()
    clear_catalogue_cache(row["language_tag"])
    return _language_result(row)


@router.get("/admin/i18n/messages")
def admin_messages(
    language_tag: str,
    key: str = "",
    source_text: str = "",
    translated_text: str = "",
    semantic_meaning: str = "",
    status_filter: str = Query(default="all", alias="status"),
    origin: str = "all",
    context: str = "",
    review_state: str = "all",
    needs_attention: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection, scope="function"),
):
    if status_filter not in {"all","draft","published"}:
        raise _error(422,"invalid_status_filter","localization.validation.status.invalid")
    if origin not in {"all","source_copy","manual","generated","imported"}:
        raise _error(422,"invalid_origin_filter","localization.validation.origin.invalid")
    if review_state not in {"all","reviewed","needs_review","unreviewed"}:
        raise _error(422,"invalid_review_filter","localization.validation.review_state.invalid")
    language = connection.execute(
        "SELECT language_tag FROM supported_languages WHERE lower(language_tag)=lower(%s)", (language_tag,),
    ).fetchone()
    if language is None:
        raise _error(404,"language_not_found","localization.validation.language.not_found",language=language_tag)
    is_source_language = language["language_tag"].lower() == "en"
    baseline_sql = "(translation.message_key IS NULL OR translation.origin='source_copy')"
    translated_text_sql = (
        f"CASE WHEN {baseline_sql} THEN definition.default_text ELSE translation.translated_text END"
        if is_source_language else "translation.translated_text"
    )
    published_text_sql = (
        f"CASE WHEN {baseline_sql} THEN definition.default_text ELSE translation.published_text END"
        if is_source_language else "translation.published_text"
    )
    status_sql = (
        f"CASE WHEN {baseline_sql} THEN 'published' ELSE translation.status END"
        if is_source_language else "translation.status"
    )
    origin_sql = (
        f"CASE WHEN {baseline_sql} THEN 'source_copy' ELSE translation.origin END"
        if is_source_language else "translation.origin"
    )
    predicates = ["NOT definition.is_deprecated"]
    params: list[Any] = [language["language_tag"]]
    for column, value in (("definition.message_key",key),("definition.default_text",source_text),(translated_text_sql,translated_text),("definition.semantic_meaning",semantic_meaning),("definition.context_group",context)):
        if value.strip():
            predicates.append(f"COALESCE({column},'') ILIKE %s")
            params.append(f"%{value.strip()}%")
    if status_filter != "all": predicates.append(f"{status_sql}=%s"); params.append(status_filter)
    if origin != "all": predicates.append(f"{origin_sql}=%s"); params.append(origin)
    if review_state == "reviewed": predicates.append("translation.date_reviewed IS NOT NULL")
    elif review_state == "needs_review": predicates.append("translation.needs_review")
    elif review_state == "unreviewed": predicates.append("translation.date_reviewed IS NULL")
    attention_sql = (
        "(COALESCE(translation.needs_review,false) OR "
        "COALESCE(translation.origin='generated' AND translation.date_reviewed IS NULL,false))"
        if is_source_language else
        "(translation.message_key IS NULL OR translation.origin='source_copy' OR translation.needs_review OR (translation.origin='generated' AND translation.date_reviewed IS NULL))"
    )
    if needs_attention is not None: predicates.append(attention_sql if needs_attention else f"NOT {attention_sql}")
    where = " AND ".join(predicates)
    total = connection.execute(
        f"""SELECT count(*) AS value FROM ui_message_definitions definition
             LEFT JOIN ui_message_translations translation ON translation.message_key=definition.message_key AND translation.language_tag=%s
             WHERE {where}""", params,
    ).fetchone()["value"]
    group_total = connection.execute(
        f"""SELECT count(DISTINCT definition.context_group) AS value
              FROM ui_message_definitions definition
              LEFT JOIN ui_message_translations translation ON translation.message_key=definition.message_key AND translation.language_tag=%s
             WHERE {where}""", params,
    ).fetchone()["value"]
    group_rows = connection.execute(
        f"""SELECT definition.context_group
              FROM ui_message_definitions definition
              LEFT JOIN ui_message_translations translation ON translation.message_key=definition.message_key AND translation.language_tag=%s
             WHERE {where}
             GROUP BY definition.context_group ORDER BY definition.context_group
             LIMIT %s OFFSET %s""", [*params,limit,offset],
    ).fetchall()
    selected_groups = [row["context_group"] for row in group_rows]
    rows = connection.execute(
        f"""SELECT definition.*,{translated_text_sql} AS translated_text,
                    {published_text_sql} AS published_text,{status_sql} AS status,
                    {origin_sql} AS origin,translation.generation_metadata,COALESCE(translation.needs_review,false) AS needs_review,
                    translation.reviewed_by_user_id,translation.date_reviewed,translation.date_published,
                    COALESCE(translation.version,0) AS translation_version,
                    CASE WHEN %s AND {baseline_sql} THEN 'valid'
                         WHEN translation.message_key IS NULL THEN 'missing'
                         WHEN translation.origin='source_copy' THEN 'needs_translation'
                         WHEN translation.origin='generated' AND translation.date_reviewed IS NULL THEN 'needs_review'
                         WHEN translation.needs_review THEN 'needs_review' ELSE 'valid' END AS validity
               FROM ui_message_definitions definition
               LEFT JOIN ui_message_translations translation ON translation.message_key=definition.message_key AND translation.language_tag=%s
              WHERE {where} AND definition.context_group=ANY(%s)
              ORDER BY definition.context_group,definition.message_key""",
        [is_source_language,*params,selected_groups],
    ).fetchall() if selected_groups else []
    summary_attention_sql = attention_sql
    summary_published_sql = (
        f"({baseline_sql} OR translation.status='published')"
        if is_source_language else "translation.status='published'"
    )
    summary_draft_sql = (
        f"(NOT {baseline_sql} AND translation.status='draft')"
        if is_source_language else "translation.status='draft'"
    )
    summaries = connection.execute(
        f"""SELECT definition.context_group,count(*) AS total,
                  count(*) FILTER(WHERE {summary_attention_sql}) AS needs_attention,
                  count(*) FILTER(WHERE {summary_published_sql}) AS published,
                  count(*) FILTER(WHERE {summary_draft_sql}) AS draft
             FROM ui_message_definitions definition LEFT JOIN ui_message_translations translation
               ON translation.message_key=definition.message_key AND translation.language_tag=%s
            WHERE NOT definition.is_deprecated GROUP BY definition.context_group ORDER BY definition.context_group""",
        (language["language_tag"],),
    ).fetchall()
    return {
        "items":list(rows), "total":total, "group_total":group_total,
        "limit":limit, "offset":offset, "context_groups":list(summaries),
    }


def _definition(connection: Connection, message_key: str) -> dict:
    row = connection.execute("SELECT * FROM ui_message_definitions WHERE message_key=%s AND NOT is_deprecated",(message_key,)).fetchone()
    if row is None: raise _error(404,"message_not_found","localization.validation.message.not_found",message_key=message_key)
    return row


def _file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _translation_export(
    connection: Connection, language_tag: str, *, include_reviewed_drafts: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a seed-compatible, validated export without mutating catalogue state."""
    language = connection.execute(
        "SELECT * FROM supported_languages WHERE lower(language_tag)=lower(%s)",
        (language_tag,),
    ).fetchone()
    if language is None:
        raise _error(404, "language_not_found", "localization.validation.language.not_found", language=language_tag)
    root = Path(__file__).resolve().parents[3]
    catalogue_path = root / "frontend/webui/i18n/messages.en.json"
    rows = list(connection.execute(
        """SELECT definition.*,translation.translated_text,translation.published_text,
                  translation.status,translation.origin,translation.generation_metadata,
                  translation.date_reviewed,translation.date_published
             FROM ui_message_definitions definition
            LEFT JOIN ui_message_translations translation
               ON translation.message_key=definition.message_key
              AND translation.language_tag=%s
            WHERE NOT definition.is_deprecated
            ORDER BY definition.message_key COLLATE "C"
        """,
        (language["language_tag"],),
    ).fetchall())
    checked_in_path = root / f"frontend/webui/i18n/messages.{language['language_tag'].lower()}.generated.json"
    checked_in: dict[str, str] = {}
    checked_in_payload: dict[str, Any] = {}
    if checked_in_path.exists():
        checked_in_payload = json.loads(checked_in_path.read_text(encoding="utf-8"))
        checked_in = {
            item["message_key"]: item["translated_text"]
            for item in checked_in_payload.get("items", [])
        }
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    invalid: list[dict[str, str]] = []
    draft_overrides = 0
    changed = 0
    for row in rows:
        use_reviewed_draft = bool(
            include_reviewed_drafts
            and row.get("date_reviewed") is not None
            and row.get("translated_text")
            and row.get("status") == "draft"
            and row.get("origin") != "source_copy"
        )
        text = row.get("translated_text") if use_reviewed_draft else row.get("published_text")
        # English definitions are the authored source catalogue, not
        # untranslated fallback drafts. They are directly exportable unless
        # an administrator has published an English override for the key.
        if not text and language["language_tag"].lower() == "en":
            text = row["default_text"]
        if not text:
            missing.append(row["message_key"])
            continue
        try:
            normalized, _, _ = _validate_translation(row, text)
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, dict) else {}
            invalid.append({
                "message_key": row["message_key"],
                "code": str(detail.get("code") or "invalid_translation"),
            })
            continue
        if use_reviewed_draft:
            draft_overrides += 1
        if checked_in.get(row["message_key"]) != normalized:
            changed += 1
        source_origin = str(row.get("origin") or "unknown")
        items.append({
            "message_key": row["message_key"],
            "translated_text": normalized,
            "quality_flags": [],
            "provenance": {
                "kind": "manual_admin_export" if source_origin == "manual" else "admin_catalogue_export",
                "source_origin": source_origin,
                "source_status": "reviewed_draft" if use_reviewed_draft else "published",
                "date_reviewed": row["date_reviewed"].isoformat() if row.get("date_reviewed") else None,
                "date_published": row["date_published"].isoformat() if row.get("date_published") else None,
            },
        })
    exported_at = datetime.now().astimezone().isoformat()
    specification_path = root / "specs/internationalization-and-user-preferences.md"
    terminology_bytes = json.dumps(
        ARABIC_TERMINOLOGY if language["language_tag"].lower() == "ar" else {},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    artifact = {
        "generator": "Wathiq Translation Administration",
        "model": "database-reviewed-translations",
        "model_version": "1",
        "prompt_version": "manual-admin-export-v1",
        "specification_sha256": _file_digest(specification_path),
        "catalogue_sha256": _file_digest(catalogue_path),
        "terminology_sha256": sha256(terminology_bytes).hexdigest(),
        "batch_id": f"admin-export-{language['language_tag'].lower()}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "generated_at": exported_at,
        "artifact_type": "wathiq_translation_administration_export",
        "language_tag": language["language_tag"],
        "language_metadata": {
            "english_name": language["english_name"],
            "native_name": language["native_name"],
            "direction": language["direction"],
            "formatting_config": language["formatting_config"],
        },
        "catalogue_revision": language["catalogue_revision"],
        "includes_reviewed_drafts": include_reviewed_drafts,
        # Preserve exact known replaced machine values. They are required by
        # guarded seeding and are independent of administrator wording.
        "superseded_translations": checked_in_payload.get(
            "superseded_translations", {}
        ),
        "items": items,
    }
    summary = {
        "language_tag": language["language_tag"],
        "active_keys": len(rows),
        "exportable_keys": len(items),
        "missing_keys": missing,
        "invalid_keys": invalid,
        "reviewed_draft_overrides": draft_overrides,
        "changed_from_checked_in": changed,
        "complete": len(items) == len(rows) and not missing and not invalid,
        "suggested_filename": f"messages.{language['language_tag'].lower()}.admin-export.json",
    }
    return artifact, summary


def _translation_import_plan(
    connection: Connection, language_tag: str, artifact: dict[str, Any], *, lock: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    language = connection.execute(
        "SELECT * FROM supported_languages WHERE lower(language_tag)=lower(%s)" + (" FOR UPDATE" if lock else ""),
        (language_tag,),
    ).fetchone()
    invalid: list[dict[str, str]] = []
    artifact_language = str(artifact.get("language_tag") or "").strip()
    if not artifact_language:
        artifact_language = language_tag
        invalid.append({"message_key": "", "code": "artifact_language_required"})
    if artifact_language.lower() != language_tag.lower():
        invalid.append({"message_key": "", "code": "artifact_language_mismatch"})
    creates_language = language is None
    if creates_language:
        metadata = artifact.get("language_metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            invalid.append({"message_key": "", "code": "artifact_language_metadata_required"})
        english_name = str(metadata.get("english_name") or "").strip()
        native_name = str(metadata.get("native_name") or "").strip()
        direction = str(metadata.get("direction") or "").lower()
        formatting_config = metadata.get("formatting_config")
        if not english_name or not native_name:
            invalid.append({"message_key": "", "code": "artifact_language_names_required"})
        if direction not in {"ltr", "rtl"}:
            invalid.append({"message_key": "", "code": "artifact_language_direction_invalid"})
        if not isinstance(formatting_config, dict):
            invalid.append({"message_key": "", "code": "artifact_language_formatting_invalid"})
            formatting_config = {}
        try:
            canonical_tag = _canonical_language_tag(artifact_language)
        except HTTPException:
            canonical_tag = artifact_language
            invalid.append({"message_key": "", "code": "artifact_language_tag_invalid"})
        language = {
            "language_tag": canonical_tag,
            "english_name": english_name,
            "native_name": native_name,
            "direction": direction,
            "is_enabled": True,
            "is_default": False,
            "catalogue_revision": 0,
            "formatting_config": formatting_config,
        }
    catalogue_path = (
        Path(__file__).resolve().parents[3] / "frontend/webui/i18n/messages.en.json"
    )
    catalogue_digest = _file_digest(catalogue_path)
    if artifact.get("catalogue_sha256") and artifact["catalogue_sha256"] != catalogue_digest:
        invalid.append({"message_key": "", "code": "catalogue_hash_mismatch"})
    raw_items = artifact.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        invalid.append({"message_key": "", "code": "artifact_items_required"})
        raw_items = []
    raw_keys = [
        str(item.get("message_key") or "") if isinstance(item, dict) else ""
        for item in raw_items
    ]
    if raw_keys != sorted(raw_keys):
        invalid.append({"message_key": "", "code": "artifact_key_order_mismatch"})
    definitions = {
        row["message_key"]: row for row in connection.execute(
            "SELECT * FROM ui_message_definitions WHERE NOT is_deprecated ORDER BY message_key"
        ).fetchall()
    }
    seen: set[str] = set()
    valid_items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            invalid.append({"message_key": "", "code": "invalid_artifact_item"})
            continue
        key = str(raw.get("message_key") or "")
        if not key or key in seen:
            invalid.append({"message_key": key, "code": "duplicate_or_blank_message_key"})
            continue
        seen.add(key)
        definition = definitions.get(key)
        if definition is None:
            invalid.append({"message_key": key, "code": "message_not_found"})
            continue
        try:
            normalized, _, _ = _validate_translation(definition, str(raw.get("translated_text") or ""))
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, dict) else {}
            invalid.append({"message_key": key, "code": str(detail.get("code") or "invalid_translation")})
            continue
        quality_flags = raw.get("quality_flags") or []
        if not isinstance(quality_flags, list) or any(not isinstance(flag, str) for flag in quality_flags):
            invalid.append({"message_key": key, "code": "invalid_quality_flags"})
            continue
        if quality_flags:
            invalid.append({"message_key": key, "code": "generation_quality_attention"})
            continue
        valid_items.append({
            "message_key": key,
            "translated_text": normalized,
            "quality_flags": quality_flags,
            "provenance": raw.get("provenance") if isinstance(raw.get("provenance"), dict) else {},
        })
    missing = sorted(set(definitions) - seen)
    keys = [item["message_key"] for item in valid_items]
    existing_rows = connection.execute(
        """SELECT * FROM ui_message_translations
            WHERE language_tag=%s AND message_key=ANY(%s)""" + (" FOR UPDATE" if lock else ""),
        (language["language_tag"], keys),
    ).fetchall() if keys else []
    existing = {row["message_key"]: row for row in existing_rows}
    importable: list[dict[str, Any]] = []
    protected: list[str] = []
    unchanged: list[str] = []
    for item in valid_items:
        current = existing.get(item["message_key"])
        if current and current["translated_text"] == item["translated_text"] and current["origin"] != "source_copy":
            unchanged.append(item["message_key"])
        elif current and (
            current["origin"] != "source_copy"
            or current["reviewed_by_user_id"] is not None
            or current["published_text"] is not None
        ):
            protected.append(item["message_key"])
        else:
            importable.append(item)
    summary = {
        "language_tag": language["language_tag"],
        "artifact_items": len(raw_items),
        "active_keys": len(definitions),
        "importable": len(importable),
        "protected": len(protected),
        "unchanged": len(unchanged),
        "missing_keys": missing,
        "invalid_keys": invalid,
        "protected_keys": protected,
        "complete": not missing and not invalid,
        "creates_language": creates_language,
    }
    return dict(language), importable, summary


@router.get("/admin/i18n/translations/{language_tag}/export-preview")
def preview_translation_export(
    language_tag: str,
    include_reviewed_drafts: bool = False,
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _, summary = _translation_export(
        connection, language_tag, include_reviewed_drafts=include_reviewed_drafts,
    )
    return summary


@router.get("/admin/i18n/translations/{language_tag}/export")
def export_translations(
    language_tag: str,
    include_reviewed_drafts: bool = False,
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection, scope="function"),
):
    artifact, summary = _translation_export(
        connection, language_tag, include_reviewed_drafts=include_reviewed_drafts,
    )
    if not summary["complete"]:
        raise _error(
            422, "translation_export_incomplete", "localization.validation.export.incomplete",
            missing=summary["missing_keys"], invalid=summary["invalid_keys"],
        )
    return {"filename": summary["suggested_filename"], "summary": summary, "artifact": artifact}


@router.post("/admin/i18n/translations/{language_tag}/import-preview")
def preview_translation_import(
    language_tag: str,
    payload: TranslationArtifactImport,
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection, scope="function"),
):
    _, _, summary = _translation_import_plan(connection, language_tag, payload.artifact)
    return summary


@router.post("/admin/i18n/translations/{language_tag}/import")
def import_translations(
    language_tag: str,
    payload: TranslationArtifactImport,
    change_reason: str | None = Header(default=None, alias="X-Change-Reason"),
    principal: Principal = Depends(principal_from_request),
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection, scope="function"),
):
    reason = _required_reason(change_reason)
    language, importable, summary = _translation_import_plan(
        connection, language_tag, payload.artifact, lock=True,
    )
    if not summary["complete"]:
        raise _error(
            422, "translation_import_invalid", "localization.validation.import.invalid",
            missing=summary["missing_keys"], invalid=summary["invalid_keys"],
        )
    _set_reason(connection, reason, principal.user_id)
    if summary["creates_language"]:
        connection.execute(
            """INSERT INTO supported_languages(
                   language_tag,english_name,native_name,direction,is_enabled,is_default,formatting_config
               ) VALUES(%s,%s,%s,%s,true,false,%s)""",
            (
                language["language_tag"], language["english_name"],
                language["native_name"], language["direction"],
                Jsonb(language["formatting_config"]),
            ),
        )
        connection.execute(
            """INSERT INTO ui_message_translations(
                   message_key,language_tag,translated_text,status,origin,updated_by_user_id
               )
               SELECT message_key,%s,default_text,'draft','source_copy',%s
                 FROM ui_message_definitions
                WHERE NOT is_deprecated
               ON CONFLICT DO NOTHING""",
            (language["language_tag"], principal.user_id),
        )
    common_metadata = {
        key: payload.artifact.get(key) for key in (
            "generator", "model", "model_version", "prompt_version", "specification_sha256",
            "catalogue_sha256", "terminology_sha256", "batch_id", "generated_at",
            "artifact_type", "language_tag", "catalogue_revision",
        ) if payload.artifact.get(key) is not None
    }
    for item in importable:
        metadata = {
            **common_metadata,
            "quality_flags": item["quality_flags"],
            "export_provenance": item["provenance"],
        }
        connection.execute(
            """INSERT INTO ui_message_translations(
                   message_key,language_tag,translated_text,status,origin,generation_metadata,
                   needs_review,updated_by_user_id
               ) VALUES(%s,%s,%s,'draft','imported',%s,false,%s)
               ON CONFLICT(message_key,language_tag) DO UPDATE SET
                   translated_text=EXCLUDED.translated_text,status='draft',origin='imported',
                   generation_metadata=EXCLUDED.generation_metadata,needs_review=false,
                   updated_by_user_id=EXCLUDED.updated_by_user_id,
                   reviewed_by_user_id=NULL,date_reviewed=NULL
               WHERE ui_message_translations.origin='source_copy'
                 AND ui_message_translations.reviewed_by_user_id IS NULL
                 AND ui_message_translations.published_text IS NULL""",
            (
                item["message_key"], language["language_tag"], item["translated_text"],
                Jsonb(metadata), principal.user_id,
            ),
        )
    return {**summary, "imported": len(importable), "created_language": summary["creates_language"]}


@router.get("/admin/i18n/generation-input/{language_tag}")
def generation_input(
    language_tag: str,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection, scope="function"),
):
    """Return only application-owned text and translation guidance."""
    language = connection.execute(
        "SELECT language_tag FROM supported_languages WHERE lower(language_tag)=lower(%s)",
        (language_tag,),
    ).fetchone()
    if language is None:
        raise _error(404, "language_not_found", "localization.validation.language.not_found", language=language_tag)
    rows = connection.execute(
        """SELECT definition.message_key,definition.context_group,definition.default_text,
                  definition.semantic_meaning,definition.common_locations,
                  definition.translator_guidance,definition.grammatical_role,
                  definition.parameter_schema,definition.rendered_example
             FROM ui_message_definitions definition
             LEFT JOIN ui_message_translations translation
               ON translation.message_key=definition.message_key
              AND translation.language_tag=%s
            WHERE NOT definition.is_deprecated
              AND (translation.message_key IS NULL OR translation.origin='source_copy')
            ORDER BY definition.context_group,definition.message_key
            LIMIT %s OFFSET %s""",
        (language["language_tag"], limit, offset),
    ).fetchall()
    total = connection.execute(
        """SELECT count(*) AS value
             FROM ui_message_definitions definition
             LEFT JOIN ui_message_translations translation
               ON translation.message_key=definition.message_key
              AND translation.language_tag=%s
            WHERE NOT definition.is_deprecated
              AND (translation.message_key IS NULL OR translation.origin='source_copy')""",
        (language["language_tag"],),
    ).fetchone()["value"]
    return {
        "language_tag": language["language_tag"],
        "items": list(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
        "approved_terminology": ARABIC_TERMINOLOGY if language["language_tag"].lower() == "ar" else {},
        "data_contract": "application_owned_source_context_and_placeholder_metadata_only",
    }


@router.post("/admin/i18n/generated-drafts/{language_tag}")
def store_generated_drafts(
    language_tag: str,
    payload: GenerationBatch,
    change_reason: str | None = Header(default=None, alias="X-Change-Reason"),
    principal: Principal = Depends(principal_from_request),
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection, scope="function"),
):
    reason = _required_reason(change_reason)
    language = connection.execute(
        "SELECT language_tag FROM supported_languages WHERE lower(language_tag)=lower(%s) FOR UPDATE",
        (language_tag,),
    ).fetchone()
    if language is None:
        raise _error(404, "language_not_found", "localization.validation.language.not_found", language=language_tag)
    keys = [item.message_key for item in payload.items]
    if len(keys) != len(set(keys)):
        raise _error(422, "duplicate_generation_key", "localization.validation.generation.duplicate_key")
    _set_reason(connection, reason, principal.user_id)
    metadata = {
        "generator": payload.generator,
        "model": payload.model,
        "model_version": payload.model_version,
        "prompt_version": payload.prompt_version,
        "specification_sha256": payload.specification_sha256,
        "catalogue_sha256": payload.catalogue_sha256,
        "terminology_sha256": payload.terminology_sha256,
        "batch_id": payload.batch_id,
        "generated_at": payload.generated_at.isoformat(),
    }
    stored: list[str] = []
    protected: list[dict[str, str]] = []
    failures: list[dict[str, Any]] = []
    for item in payload.items:
        definition = connection.execute(
            "SELECT * FROM ui_message_definitions WHERE message_key=%s AND NOT is_deprecated",
            (item.message_key,),
        ).fetchone()
        if definition is None:
            failures.append({"message_key": item.message_key, "code": "message_not_found"})
            continue
        current = connection.execute(
            """SELECT origin,status,reviewed_by_user_id,published_text
                 FROM ui_message_translations
                WHERE message_key=%s AND language_tag=%s FOR UPDATE""",
            (item.message_key, language["language_tag"]),
        ).fetchone()
        if current and (
            current["origin"] != "source_copy"
            or current["reviewed_by_user_id"] is not None
            or current["published_text"] is not None
        ):
            protected.append({"message_key": item.message_key, "origin": current["origin"]})
            continue
        try:
            normalized, _, _ = _validate_translation(definition, item.translated_text)
        except HTTPException as exception:
            detail = exception.detail if isinstance(exception.detail, dict) else {}
            failures.append({
                "message_key": item.message_key,
                "code": detail.get("code", "invalid_translation"),
                "parameters": detail.get("parameters", {}),
            })
            continue
        connection.execute(
            """INSERT INTO ui_message_translations(
                   message_key,language_tag,translated_text,status,origin,
                   generation_metadata,needs_review,updated_by_user_id
               ) VALUES(%s,%s,%s,'draft','generated',%s,false,%s)
               ON CONFLICT(message_key,language_tag) DO UPDATE SET
                   translated_text=EXCLUDED.translated_text,status='draft',origin='generated',
                   generation_metadata=EXCLUDED.generation_metadata,needs_review=false,
                   updated_by_user_id=EXCLUDED.updated_by_user_id,
                   reviewed_by_user_id=NULL,date_reviewed=NULL
               WHERE ui_message_translations.origin='source_copy'
                 AND ui_message_translations.reviewed_by_user_id IS NULL
                 AND ui_message_translations.published_text IS NULL""",
            (
                item.message_key, language["language_tag"], normalized,
                Jsonb({**metadata, "quality_flags": item.quality_flags}), principal.user_id,
            ),
        )
        stored.append(item.message_key)
    return {
        "language_tag": language["language_tag"],
        "submitted": len(payload.items),
        "stored": len(stored),
        "stored_keys": stored,
        "protected": protected,
        "failures": failures,
        "generation_metadata": metadata,
        "published": 0,
    }


@router.get("/admin/i18n/generation-report/{language_tag}")
def generation_report(
    language_tag: str,
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection, scope="function"),
):
    language = connection.execute(
        "SELECT language_tag FROM supported_languages WHERE lower(language_tag)=lower(%s)",
        (language_tag,),
    ).fetchone()
    if language is None:
        raise _error(404, "language_not_found", "localization.validation.language.not_found", language=language_tag)
    is_source_language = language["language_tag"].lower() == "en"
    published_condition = (
        "(translation.message_key IS NULL OR translation.origin='source_copy' OR translation.status='published')"
        if is_source_language else "translation.status='published'"
    )
    summary = connection.execute(
        f"""SELECT count(*) AS total,
                  count(*) FILTER(WHERE translation.status='draft' AND translation.origin<>'source_copy') AS drafts,
                  count(*) FILTER(WHERE translation.date_reviewed IS NOT NULL) AS reviewed,
                  count(*) FILTER(WHERE translation.status='draft' AND translation.origin<>'source_copy' AND translation.date_reviewed IS NULL) AS unreviewed,
                  count(*) FILTER(WHERE {published_condition}) AS published,
                  count(*) FILTER(WHERE NOT COALESCE(({published_condition}),false)) AS unpublished,
                  count(*) FILTER(WHERE translation.origin='generated') AS generated,
                  count(*) FILTER(WHERE translation.origin='generated' AND translation.date_reviewed IS NOT NULL) AS generated_reviewed,
                  count(*) FILTER(WHERE translation.origin='generated' AND translation.status='published') AS generated_published,
                  count(*) FILTER(WHERE translation.origin='generated' AND jsonb_array_length(COALESCE(translation.generation_metadata->'quality_flags','[]'::jsonb))>0) AS quality_attention,
                  count(*) FILTER(WHERE translation.origin='source_copy' OR translation.message_key IS NULL) AS awaiting_generation,
                  count(*) FILTER(WHERE translation.needs_review) AS needs_review
             FROM ui_message_definitions definition
             LEFT JOIN ui_message_translations translation
               ON translation.message_key=definition.message_key AND translation.language_tag=%s
            WHERE NOT definition.is_deprecated""",
        (language["language_tag"],),
    ).fetchone()
    contexts = connection.execute(
        """SELECT definition.context_group,count(*) AS total,
                  count(*) FILTER(WHERE translation.origin='generated') AS generated,
                  count(*) FILTER(WHERE translation.origin='generated' AND translation.date_reviewed IS NOT NULL) AS reviewed,
                  count(*) FILTER(WHERE translation.origin='source_copy' OR translation.message_key IS NULL) AS awaiting_generation
             FROM ui_message_definitions definition
             LEFT JOIN ui_message_translations translation
               ON translation.message_key=definition.message_key AND translation.language_tag=%s
            WHERE NOT definition.is_deprecated
            GROUP BY definition.context_group ORDER BY definition.context_group""",
        (language["language_tag"],),
    ).fetchall()
    return {"language_tag": language["language_tag"], **dict(summary), "context_groups": list(contexts)}


def _bulk_draft_rows(
    connection: Connection, language_tag: str, context_group: str,
    *, lock: bool = False,
) -> tuple[dict, list[dict], list[dict]]:
    language = connection.execute(
        "SELECT * FROM supported_languages WHERE lower(language_tag)=lower(%s)" + (" FOR UPDATE" if lock else ""),
        (language_tag,),
    ).fetchone()
    if language is None:
        raise _error(404,"language_not_found","localization.validation.language.not_found",language=language_tag)
    parameters: list[Any] = [language["language_tag"]]
    context_sql = ""
    if context_group.strip():
        context_sql = " AND definition.context_group=%s"
        parameters.append(context_group.strip())
    lock_sql = " FOR UPDATE OF translation" if lock else ""
    rows = connection.execute(
        f"""SELECT definition.message_key,definition.context_group,definition.parameter_schema,
                    definition.is_html,translation.translated_text,translation.version,
                    translation.origin,translation.status,translation.needs_review,
                    translation.generation_metadata
               FROM ui_message_definitions definition
               JOIN ui_message_translations translation
                 ON translation.message_key=definition.message_key
                AND translation.language_tag=%s
              WHERE NOT definition.is_deprecated
                AND translation.status='draft'
                {context_sql}
              ORDER BY definition.context_group,definition.message_key{lock_sql}""",
        parameters,
    ).fetchall()
    source_copies = (
        [row for row in rows if row["origin"] == "source_copy"]
        if language["language_tag"].lower() != "en" else []
    )
    excluded = {row["message_key"] for row in source_copies}
    eligible = [row for row in rows if row["message_key"] not in excluded]
    return dict(language), eligible, source_copies


def _bulk_validation_errors(rows: list[dict]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for row in rows:
        try:
            _validate_translation(row,row["translated_text"])
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail,dict) else {}
            errors.append({"message_key":row["message_key"],"code":str(detail.get("code") or "invalid_translation")})
            continue
        flags = (row.get("generation_metadata") or {}).get("quality_flags") or []
        # This endpoint performs the human review. The routine review marker
        # is acknowledged by publication; concrete or unknown defects still block.
        if any(flag != "needs_human_review" for flag in flags):
            errors.append({"message_key":row["message_key"],"code":"generation_quality_attention"})
    return errors


@router.get("/admin/i18n/translations/{language_tag}/bulk-publication-preview")
def preview_bulk_translation_publication(
    language_tag: str,
    context_group: str = "",
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection,scope="function"),
):
    language,rows,source_copies=_bulk_draft_rows(connection,language_tag,context_group)
    errors=_bulk_validation_errors(rows)
    return {
        "language_tag":language["language_tag"],"context_group":context_group.strip() or None,
        "count":len(rows),"items":[{"message_key":row["message_key"],"version":row["version"]} for row in rows],
        "source_copy_excluded":len(source_copies),
        "invalid":errors,
    }


@router.post("/admin/i18n/translations/{language_tag}/bulk-review-publish")
def bulk_review_publish_translations(
    language_tag: str,payload: BulkTranslationPublication,
    change_reason: str | None = Header(default=None,alias="X-Change-Reason"),
    principal: Principal = Depends(principal_from_request),
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection,scope="function"),
):
    reason=_required_reason(change_reason)
    requested={item.message_key:item.version for item in payload.items}
    if len(requested)!=len(payload.items):
        raise _error(422,"duplicate_message_key","localization.validation.bulk.duplicate")
    language,available,source_copies=_bulk_draft_rows(connection,language_tag,"",lock=True)
    rows=[row for row in available if row["message_key"] in requested]
    found={row["message_key"] for row in rows}
    excluded={row["message_key"] for row in source_copies if row["message_key"] in requested}
    missing=sorted(set(requested)-found-excluded)
    stale=sorted(row["message_key"] for row in rows if row["version"]!=requested[row["message_key"]])
    errors=[
        {"message_key":key,"code":"source_copy_not_publishable"}
        for key in sorted(excluded)
    ]+_bulk_validation_errors(rows)
    if missing or stale or errors:
        raise _error(409 if stale else 422,"bulk_publication_blocked","localization.validation.bulk.blocked",
                     missing=missing,stale=stale,invalid=errors)
    _set_reason(connection,reason,principal.user_id)
    now=datetime.now().astimezone()
    for row in rows:
        normalized,_,_=_validate_translation(row,row["translated_text"])
        connection.execute(
            """UPDATE ui_message_translations
                  SET translated_text=%s,published_text=%s,status='published',needs_review=false,
                      generation_metadata=CASE WHEN generation_metadata ? 'quality_flags'
                        THEN jsonb_set(generation_metadata,'{quality_flags}',
                          (generation_metadata->'quality_flags')-'needs_human_review')
                        ELSE generation_metadata END,
                      reviewed_by_user_id=%s,date_reviewed=%s,
                      published_by_user_id=%s,date_published=%s,updated_by_user_id=%s
                WHERE message_key=%s AND language_tag=%s""",
            (normalized,normalized,principal.user_id,now,principal.user_id,now,principal.user_id,
             row["message_key"],language["language_tag"]),
        )
    revision=connection.execute(
        "UPDATE supported_languages SET catalogue_revision=catalogue_revision+1 WHERE id=%s RETURNING catalogue_revision",
        (language["id"],),
    ).fetchone()["catalogue_revision"]
    clear_catalogue_cache(language["language_tag"])
    return {"language_tag":language["language_tag"],"published":len(rows),"catalogue_revision":revision}


@router.put("/admin/i18n/messages/{message_key}/translations/{language_tag}")
def update_translation(
    message_key: str, language_tag: str, payload: TranslationUpdate,
    if_match: str | None = Header(default=None,alias="If-Match"),
    change_reason: str | None = Header(default=None,alias="X-Change-Reason"),
    principal: Principal = Depends(principal_from_request),
    _: Any = Depends(require_localization_admin),
    connection: Connection = Depends(get_connection,scope="function"),
):
    expected=_expected_preference_version(if_match); reason=_required_reason(change_reason)
    definition=_definition(connection,message_key); normalized,_,_=_validate_translation(definition,payload.translated_text)
    if payload.origin not in {"manual","generated","imported"}:
        raise _error(422,"invalid_origin","localization.validation.origin.invalid")
    language=connection.execute("SELECT language_tag FROM supported_languages WHERE lower(language_tag)=lower(%s)",(language_tag,)).fetchone()
    if language is None: raise _error(404,"language_not_found","localization.validation.language.not_found",language=language_tag)
    _set_reason(connection,reason,principal.user_id)
    current=connection.execute("SELECT * FROM ui_message_translations WHERE message_key=%s AND language_tag=%s FOR UPDATE",(message_key,language["language_tag"])).fetchone()
    actual=current["version"] if current else 0
    if actual!=expected: raise _stale_version(expected,actual,dict(current) if current else None)
    review_user=principal.user_id if payload.reviewed else None; review_date=datetime.now().astimezone() if payload.reviewed else None
    if current:
        row=connection.execute("""UPDATE ui_message_translations SET translated_text=%s,status='draft',origin=%s,generation_metadata=%s,
             needs_review=false,updated_by_user_id=%s,reviewed_by_user_id=%s,date_reviewed=%s WHERE message_key=%s AND language_tag=%s RETURNING *""",
             (normalized,payload.origin,Jsonb(payload.generation_metadata) if payload.generation_metadata is not None else None,principal.user_id,review_user,review_date,message_key,language["language_tag"])).fetchone()
    else:
        row=connection.execute("""INSERT INTO ui_message_translations(message_key,language_tag,translated_text,status,origin,generation_metadata,updated_by_user_id,reviewed_by_user_id,date_reviewed)
             VALUES(%s,%s,%s,'draft',%s,%s,%s,%s,%s) RETURNING *""",
             (message_key,language["language_tag"],normalized,payload.origin,Jsonb(payload.generation_metadata) if payload.generation_metadata is not None else None,principal.user_id,review_user,review_date)).fetchone()
    return row


@router.post("/admin/i18n/messages/{message_key}/translations/{language_tag}/publish")
def publish_translation(
    message_key: str,language_tag: str,
    if_match: str | None=Header(default=None,alias="If-Match"),
    change_reason: str | None=Header(default=None,alias="X-Change-Reason"),
    principal: Principal=Depends(principal_from_request),
    _: Any=Depends(require_localization_admin),
    connection: Connection=Depends(get_connection,scope="function"),
):
    expected=_expected_preference_version(if_match);reason=_required_reason(change_reason);definition=_definition(connection,message_key)
    row=connection.execute("""SELECT translation.*,language.id AS language_id,language.catalogue_revision
      FROM ui_message_translations translation JOIN supported_languages language USING(language_tag)
      WHERE translation.message_key=%s AND lower(translation.language_tag)=lower(%s) FOR UPDATE OF translation,language""",(message_key,language_tag)).fetchone()
    if row is None: raise _error(422,"missing_translation","localization.validation.translation.missing")
    if row["version"]!=expected: raise _stale_version(expected,row["version"],dict(row))
    if row["language_tag"].lower()!="en" and row["origin"]=="source_copy":
        raise _error(422,"source_copy_not_publishable","localization.validation.source_copy.not_publishable")
    normalized,_,_=_validate_translation(definition,row["translated_text"])
    _set_reason(connection,reason,principal.user_id)
    published=connection.execute("""UPDATE ui_message_translations SET translated_text=%s,published_text=%s,status='published',needs_review=false,
      reviewed_by_user_id=%s,date_reviewed=CURRENT_TIMESTAMP,
      published_by_user_id=%s,date_published=CURRENT_TIMESTAMP WHERE message_key=%s AND language_tag=%s RETURNING *""",
      (normalized,normalized,principal.user_id,principal.user_id,message_key,row["language_tag"])).fetchone()
    language=connection.execute("UPDATE supported_languages SET catalogue_revision=catalogue_revision+1 WHERE id=%s RETURNING catalogue_revision",(row["language_id"],)).fetchone()
    clear_catalogue_cache(row["language_tag"])
    return {**published,"catalogue_revision":language["catalogue_revision"]}
