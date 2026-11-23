"""Immutable administration versions and non-executable localized templates."""

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from html import escape, unescape
import re
import json
from string import Formatter
from typing import Literal
from uuid import UUID, uuid4
from babel.dates import format_date, format_datetime
from babel.numbers import format_decimal
from pydantic import Field, ValidationError
from psycopg.types.json import Jsonb
from . import notification_registry as contracts
from .content import body, subject, invalid
from .models import Input, Selector
from .config import LIMITS
from ..entity_localization import localized_labels
from ..audit_context import correlation_id_context, event_source_context

ADMIN = "messaging.notifications.administer"


class Template(Input):
    language_tag: str = Field(min_length=2, max_length=35)
    subject_template: str = Field(min_length=1, max_length=255)
    body_template_rich_text: str = Field(min_length=1, max_length=65536)
    review_status: Literal["draft", "reviewed", "published"] = "draft"


class Expected(Input):
    expected_version: int = Field(ge=0)
    expected_active_configuration_version_id: UUID | None = None


class NotificationSelector(Selector):
    """Producer audiences retain the ordinary-principal API contract."""
    selector_kind: Literal["user", "role", "org_unit"]
    target_id: int = Field(gt=0)


class Configuration(Expected):
    enabled: bool = True
    priority: Literal["normal", "high", "very_high"] = "normal"
    audience_mode: str = Field(min_length=1, max_length=120)
    selectors: list[NotificationSelector] = Field(
        default_factory=list, max_length=LIMITS["MAX_SELECTORS_PER_SEND"]
    )
    resource_presentation: dict = Field(default_factory=dict)
    operational_owner: str = Field(min_length=1, max_length=200)
    templates: list[Template] = Field(min_length=1, max_length=200)


def require_admin(c, user):
    if not c.execute(
        "SELECT 1 FROM users WHERE id=%s AND status='active' AND account_type='person' AND user_has_global_privilege(id,%s)",
        (user, ADMIN),
    ).fetchone():
        invalid("insufficient_privilege", 403)


def audit(c, user, operation, code, version_id, reason, **metadata):
    c.execute(
        """INSERT INTO event_history(entity_type,entity_id,operation,actor_user_id,actor_type,source,reason,correlation_id,metadata,changed_fields)
        VALUES ('system_notification',0,%s,%s,'user',%s,%s,%s,%s,%s)""",
        (
            operation,
            user,
            event_source_context.get(),
            reason,
            correlation_id_context.get() or uuid4(),
            Jsonb(
                {
                    "producer_code": code,
                    "configuration_version_id": str(version_id),
                    **metadata,
                }
            ),
            list(metadata.get("changed_fields", [])),
        ),
    )


def fields(value, allowed):
    counts = Counter()
    try:
        for _, name, spec, conversion in Formatter().parse(value):
            if name is not None:
                if name not in allowed or spec or conversion:
                    raise ValueError()
                counts[name] += 1
    except ValueError:
        invalid("notification_template_invalid")
    return counts


def enabled_languages(c):
    return c.execute(
        "SELECT language_tag,direction,is_default,formatting_config FROM supported_languages WHERE is_enabled ORDER BY language_tag"
    ).fetchall()


def verify_contract(c, code):
    definition = contracts.registry.get(code)
    row = c.execute(
        "SELECT * FROM system_notification_producers WHERE producer_code=%s FOR UPDATE",
        (code,),
    ).fetchone()
    if (
        not row
        or row["contract_definition"] != definition.contract()
        or any(
            row[key] != getattr(definition, key)
            for key in (
                "feature_code",
                "event_type",
                "contract_version",
                "required_for_business_commit",
            )
        )
    ):
        invalid("notification_contract_mismatch", 409)
    return definition, row


def state(c, code):
    row = c.execute(
        "SELECT p.*,coalesce((SELECT max(version) FROM system_notification_configuration_versions v WHERE v.producer_code=p.producer_code),0) AS latest_version FROM system_notification_producers p WHERE producer_code=%s",
        (code,),
    ).fetchone()
    if not row:
        invalid("notification_producer_unregistered", 404)
    return row


def check_expected(c, code, payload):
    current = state(c, code)
    if (
        current["latest_version"] != payload.expected_version
        or current["active_configuration_version_id"]
        != payload.expected_active_configuration_version_id
    ):
        invalid("notification_configuration_conflict", 409)
    return current


def expand_system(c, selectors):
    if not selectors or not any(item.recipient_type == "to" for item in selectors):
        invalid("message_to_required")
    baseline = c.execute(
        "SELECT id,level_number FROM security_levels ORDER BY level_number LIMIT 1"
    ).fetchone()
    snapshots, addresses, seen = [], {}, set()
    positions = {"to": 0, "cc": 0}
    for selected in selectors:
        key = (selected.recipient_type, selected.selector_kind, selected.target_id)
        if key in seen:
            invalid("message_selector_duplicate")
        seen.add(key)
        kind = selected.selector_kind
        if kind == "everyone":
            invalid("message_selector_ineligible")
        table = {"user": "users", "role": "roles", "org_unit": "org_units"}[kind]
        live = {
            "user": "status='active' AND account_type='person'",
            "role": "role_effectively_active(id)",
            "org_unit": "org_unit_effectively_active(id)",
        }[kind]
        item = c.execute(
            f"SELECT id,name FROM {table} WHERE id=%s AND {live}", (selected.target_id,)
        ).fetchone()
        if not item:
            invalid("message_selector_ineligible")
        if kind == "user":
            condition = "u.id=%s"
        else:
            target = "r.id" if kind == "role" else "r.org_unit_id"
            condition = f"EXISTS(SELECT 1 FROM user_role_assignments a JOIN roles r ON r.id=a.role_id WHERE a.user_id=u.id AND {target}=%s AND role_effectively_active(r.id) AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP))"
        rows = c.execute(
            f"SELECT u.id,u.name FROM users u WHERE {condition} AND u.status='active' AND u.account_type='person' AND messaging_user_clearance(u.id)>=%s ORDER BY u.id LIMIT %s",
            (
                selected.target_id,
                baseline["level_number"],
                LIMITS["MAX_RECIPIENTS_PER_SEND"] + 1,
            ),
        ).fetchall()
        if not rows:
            invalid("message_selector_ineligible")
        snapshots.append(
            {
                "selector": selected,
                "display_name": item["name"],
                "enumeration": positions[selected.recipient_type],
            }
        )
        positions[selected.recipient_type] += 1
        for recipient in rows:
            if recipient["id"] not in addresses or selected.recipient_type == "to":
                addresses[recipient["id"]] = {
                    **recipient,
                    "recipient_type": selected.recipient_type,
                }
        if len(addresses) > LIMITS["MAX_RECIPIENTS_PER_SEND"]:
            invalid("message_recipient_limit")
    return snapshots, addresses


def validate_configuration(c, definition, payload, *, resolve_audience=True):
    if definition.required_for_business_commit and not payload.enabled:
        invalid("notification_required_cannot_disable")
    if not payload.operational_owner.strip():
        invalid("notification_owner_required")
    if payload.audience_mode not in definition.contract()["audience_modes"]:
        invalid("notification_audience_invalid")
    if any(s.selector_kind == "everyone" for s in payload.selectors):
        invalid("message_selector_ineligible")
    if payload.audience_mode == "static":
        if not payload.selectors:
            invalid("notification_audience_invalid")
        if resolve_audience:
            expand_system(c, payload.selectors)
    elif payload.selectors:
        invalid("notification_audience_invalid")
    if definition.resource_configuration:
        try:
            value = definition.resource_configuration.model_validate(
                payload.resource_presentation
            )
            if set(payload.resource_presentation) - set(type(value).model_fields):
                raise ValueError()
        except (ValidationError, ValueError):
            invalid("notification_resource_configuration_invalid")
    elif payload.resource_presentation:
        invalid("notification_resource_configuration_invalid")
    templates = {item.language_tag: item for item in payload.templates}
    required = {item["language_tag"] for item in enabled_languages(c)} | {"en"}
    default = next(
        item["language_tag"] for item in enabled_languages(c) if item["is_default"]
    )
    if len(templates) != len(payload.templates) or not required.issubset(templates):
        invalid("notification_language_coverage_required")
    registered = {
        row["language_tag"]
        for row in c.execute("SELECT language_tag FROM supported_languages")
    }
    if not set(templates).issubset(registered):
        invalid("notification_language_coverage_required")
    for item in templates.values():
        item.subject_template = subject(item.subject_template)
        item.body_template_rich_text = body(item.body_template_rich_text, [])
        if not unescape(re.sub(r"<[^>]*>", "", item.body_template_rich_text)).strip():
            invalid("notification_template_blank")
    canonical = templates["en"]
    parity = (
        fields(canonical.subject_template, definition.placeholders),
        fields(canonical.body_template_rich_text, definition.placeholders),
    )
    for item in templates.values():
        if (
            fields(item.subject_template, definition.placeholders),
            fields(item.body_template_rich_text, definition.placeholders),
        ) != parity:
            invalid("notification_placeholder_parity")
    return templates, default


def render(c, definition, templates, context, languages):
    values = contracts.validate_context(definition, context)
    boolean_labels = (
        {
            value: localized_labels(c, "messaging.value." + str(value).lower())
            for value in (True, False)
        }
        if any(type(value) is bool for value in values.values())
        else {}
    )
    variants = []
    for language in languages:
        tag = language["language_tag"]
        template = templates[tag]
        locale = language["formatting_config"].get("locale", tag).replace("-", "_")
        strings = {}
        for key, value in values.items():
            if isinstance(value, datetime):
                text = format_datetime(value, locale=locale)
            elif isinstance(value, date):
                text = format_date(value, locale=locale)
            elif isinstance(value, (int, Decimal)) and not isinstance(value, bool):
                text = format_decimal(value, locale=locale)
            elif isinstance(value, bool):
                text = boolean_labels[value][tag]
            else:
                text = value
            strings[key] = text
        variants.append(
            {
                "language_tag": tag,
                "direction": language["direction"],
                "subject": subject(template.subject_template.format_map(strings)),
                "body_rich_text": body(
                    template.body_template_rich_text.format_map(
                        {key: escape(value) for key, value in strings.items()}
                    ),
                    [],
                ),
            }
        )
    return variants


def load_version(c, code, identity):
    row = c.execute(
        "SELECT * FROM system_notification_configuration_versions WHERE producer_code=%s AND id=%s",
        (code, identity),
    ).fetchone()
    if not row:
        invalid("notification_configuration_unavailable", 404)
    row["templates"] = c.execute(
        "SELECT * FROM system_notification_configuration_translations WHERE configuration_version_id=%s ORDER BY language_tag",
        (identity,),
    ).fetchall()
    row["selectors"] = c.execute(
        "SELECT recipient_type,selector_kind,coalesce(user_id,role_id,org_unit_id) AS target_id,display_name FROM system_notification_configuration_audiences WHERE configuration_version_id=%s ORDER BY recipient_type DESC,ordinal",
        (identity,),
    ).fetchall()
    return row


def configuration_from_row(row):
    return Configuration(
        expected_version=row["version"],
        enabled=row["enabled"],
        priority=row["priority"],
        audience_mode=row["audience_mode"],
        resource_presentation=row["resource_presentation"],
        operational_owner=row["operational_owner"],
        templates=[
            Template(**{k: r[k] for k in Template.model_fields})
            for r in row["templates"]
        ],
        selectors=[
            NotificationSelector(**{k: r[k] for k in NotificationSelector.model_fields})
            for r in row["selectors"]
        ],
    )


def coverage(c, row, language=None):
    templates = {t["language_tag"]: t for t in row["templates"]}
    tags = (
        {language}
        if language
        else {l["language_tag"] for l in enabled_languages(c)} | {"en"}
    )
    return all(
        tag in templates
        and templates[tag]["review_status"] == "published"
        and templates[tag]["reviewed_by_user_id"]
        and templates[tag]["reviewed_at"]
        for tag in tags
    )


def language_ready(c, tag):
    for row in c.execute(
        "SELECT producer_code,active_configuration_version_id FROM system_notification_producers WHERE active_configuration_version_id IS NOT NULL"
    ):
        if not coverage(
            c,
            load_version(
                c, row["producer_code"], row["active_configuration_version_id"]
            ),
            tag,
        ):
            from ..localization import _error

            raise _error(
                409,
                "notification_language_coverage_required",
                "localization.validation.notification_coverage",
                language=tag,
                producer=row["producer_code"],
            )


def save(c, user, code, payload, reason):
    require_admin(c, user)
    definition, _ = verify_contract(c, code)
    current = check_expected(c, code, payload)
    templates, _ = validate_configuration(c, definition, payload)
    if not reason or not reason.strip() or len(reason) > 2000:
        invalid("notification_reason_required")
    identity = uuid4()
    canonical = templates["en"]
    c.execute(
        """INSERT INTO system_notification_configuration_versions(id,producer_code,version,enabled,subject_template,body_template_rich_text,priority,audience_mode,resource_presentation,operational_owner,change_reason,created_by_user_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            identity,
            code,
            current["latest_version"] + 1,
            payload.enabled,
            canonical.subject_template,
            canonical.body_template_rich_text,
            payload.priority,
            payload.audience_mode,
            Jsonb(payload.resource_presentation),
            payload.operational_owner.strip(),
            reason.strip(),
            user,
        ),
    )
    for template in templates.values():
        reviewed = template.review_status != "draft"
        c.execute(
            """INSERT INTO system_notification_configuration_translations(configuration_version_id,language_tag,subject_template,body_template_rich_text,review_status,reviewed_by_user_id,reviewed_at) VALUES (%s,%s,%s,%s,%s,%s,CASE WHEN %s THEN CURRENT_TIMESTAMP ELSE NULL END)""",
            (
                identity,
                template.language_tag,
                template.subject_template,
                template.body_template_rich_text,
                template.review_status,
                user if reviewed else None,
                reviewed,
            ),
        )
    positions = {"to": 0, "cc": 0}
    for selector in payload.selectors:
        table = {"user": "users", "role": "roles", "org_unit": "org_units"}[
            selector.selector_kind
        ]
        name = c.execute(
            f"SELECT name FROM {table} WHERE id=%s", (selector.target_id,)
        ).fetchone()["name"]
        c.execute(
            f"INSERT INTO system_notification_configuration_audiences(configuration_version_id,recipient_type,selector_kind,{selector.selector_kind}_id,display_name,ordinal) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                identity,
                selector.recipient_type,
                selector.selector_kind,
                selector.target_id,
                name,
                positions[selector.recipient_type],
            ),
        )
        positions[selector.recipient_type] += 1
    audit(
        c,
        user,
        "NOTIFICATION_CONFIGURATION_SAVED",
        code,
        identity,
        reason,
        changed_fields=[
            "enabled",
            "priority",
            "audience",
            "templates",
            "resource_presentation",
            "operational_owner",
        ],
    )
    return load_version(c, code, identity)


def activate(c, user, code, identity, payload, reason):
    require_admin(c, user)
    definition, _ = verify_contract(c, code)
    check_expected(c, code, payload)
    row = load_version(c, code, identity)
    validate_configuration(c, definition, configuration_from_row(row))
    if not coverage(c, row):
        invalid("notification_language_coverage_required", 409)
    if not reason or not reason.strip() or len(reason) > 2000:
        invalid("notification_reason_required")
    c.execute(
        "UPDATE system_notification_producers SET active_configuration_version_id=%s WHERE producer_code=%s",
        (identity, code),
    )
    audit(
        c,
        user,
        "NOTIFICATION_CONFIGURATION_ACTIVATED",
        code,
        identity,
        reason,
        changed_fields=["active_configuration_version_id"],
    )
    return state(c, code)


def readiness(c):
    result = contracts.registry.reconcile(c)
    for code, definition in contracts.registry.definitions.items():
        producer = c.execute(
            "SELECT active_configuration_version_id FROM system_notification_producers WHERE producer_code=%s",
            (code,),
        ).fetchone()
        if not producer:
            continue
        identity = producer["active_configuration_version_id"]
        if not identity:
            if definition.required_for_business_commit:
                result["issues"].append(
                    {
                        "producer_code": code,
                        "code": "active_configuration_required",
                        "required": True,
                    }
                )
            continue
        try:
            row = load_version(c, code, identity)
            validate_configuration(c, definition, configuration_from_row(row))
            if not coverage(c, row):
                invalid("notification_language_coverage_required", 409)
        except Exception as error:
            from fastapi import HTTPException

            if not isinstance(error, HTTPException):
                raise
            result["issues"].append(
                {
                    "producer_code": code,
                    "code": "active_configuration_invalid",
                    "required": definition.required_for_business_commit
                    or row["enabled"],
                }
            )
    result["ready"] = not any(item["required"] for item in result["issues"])
    return result
