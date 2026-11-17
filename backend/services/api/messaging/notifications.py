"""Internal system notification service. Callers own the business transaction."""

from dataclasses import dataclass
from hashlib import sha256
import json
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
from psycopg.types.json import Jsonb
from pydantic import ValidationError
from psycopg.pq import TransactionStatus
from . import notification_registry as contracts
from .notification_configuration import (
    verify_contract,
    load_version,
    configuration_from_row,
    validate_configuration,
    localized_labels,
    enabled_languages,
    render,
    coverage,
    expand_system,
    require_admin,
    audit,
)
from .envelopes import insert_envelope
from .models import Selector, ResourceLink
from .content import invalid, body, subject
from .config import LIMITS
from .service import fan_out, result, resource


@dataclass(frozen=True)
class NotificationResult:
    status: str
    envelope_id: UUID | None = None
    delivery_ids: tuple[UUID, ...] = ()


def _result(c, identity, status="created"):
    return NotificationResult(
        status, identity, tuple(row["id"] for row in result(c, identity)["deliveries"])
    )


def _fingerprint(value):
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _prior(c, code, event_type, event_id, fingerprint):
    lock = int.from_bytes(
        sha256(f"notification:{code}:{event_type}:{event_id}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    c.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
    row = c.execute(
        "SELECT * FROM message_request_receipts WHERE producer_code=%s AND source_event_type=%s AND source_event_id=%s",
        (code, event_type, event_id),
    ).fetchone()
    if row:
        if row["request_fingerprint"] != fingerprint:
            invalid("message_request_conflict", 409)
        if row["result_purged_at"]:
            return NotificationResult("message_result_purged")
        return _result(c, row["result_envelope_id"], "existing")


def _transaction(c):
    if c.info.transaction_status != TransactionStatus.INTRANS:
        raise RuntimeError("System notifications require an already-open transaction")
    if c.execute("SHOW transaction_isolation").fetchone()[
        "transaction_isolation"
    ] not in ("repeatable read", "serializable"):
        raise RuntimeError(
            "System notifications require the caller's consistent-snapshot transaction"
        )


from .operations import measure_system


@measure_system
def emit_system_notification(
    *, transaction, producer_code, source_event_id, context, triggered_by_user_id=None
):
    c = transaction
    _transaction(c)
    definition = contracts.registry.get(producer_code)
    if (
        not isinstance(source_event_id, str)
        or not source_event_id.strip()
        or len(source_event_id) > 255
    ):
        invalid("notification_event_id_invalid")
    receipt_context = context
    if definition.display_only_placeholders:
        contracts.validate_context(definition, context)
        # Display values can be added without changing the identity of a retry.
        receipt_context = {
            key: value for key, value in context.items()
            if key not in definition.display_only_placeholders
        }
    fingerprint = _fingerprint({"context": receipt_context, "actor": triggered_by_user_id})
    prior = _prior(
        c, producer_code, definition.event_type, source_event_id, fingerprint
    )
    if prior:
        return prior
    definition, producer = verify_contract(c, producer_code)
    if not producer["active_configuration_version_id"]:
        invalid("notification_configuration_required", 409)
    row = load_version(c, producer_code, producer["active_configuration_version_id"])
    contracts.validate_context(definition, context)
    if not row["enabled"] and not definition.required_for_business_commit:
        return NotificationResult("disabled")
    payload = configuration_from_row(row)
    templates, _ = validate_configuration(c, definition, payload)
    if not coverage(c, row):
        invalid("notification_language_coverage_required", 409)
    if payload.audience_mode == "static":
        selected = payload.selectors
    else:
        selected = definition.audience_resolvers[payload.audience_mode](
            c, contracts.validate_context(definition, context)
        )
        if (
            not isinstance(selected, (tuple, list))
            or len(selected) > LIMITS["MAX_SELECTORS_PER_SEND"]
        ):
            invalid("notification_audience_invalid")
        try:
            selected = [Selector.model_validate(value) for value in selected]
        except ValidationError:
            invalid("notification_audience_invalid")
    return _write(
        c,
        definition,
        row,
        templates,
        selected,
        context,
        definition.event_type,
        source_event_id,
        fingerprint,
        triggered_by_user_id,
    )


def emit_system_notification_test(
    *,
    transaction,
    producer_code,
    configuration_version_id,
    test_run_id,
    context,
    recipient_user_ids,
    initiated_by_user_id,
):
    c = transaction
    _transaction(c)
    require_admin(c, initiated_by_user_id)
    if not isinstance(test_run_id, UUID):
        invalid("notification_test_id_invalid")
    if (
        not recipient_user_ids
        or len(recipient_user_ids) > LIMITS["TEST_MAX_RECIPIENTS"]
        or any(type(value) is not int or value < 1 for value in recipient_user_ids)
        or len(set(recipient_user_ids)) != len(recipient_user_ids)
    ):
        invalid("notification_test_recipients_invalid")
    fingerprint = _fingerprint(
        {
            "configuration": configuration_version_id,
            "context": context,
            "recipients": recipient_user_ids,
            "actor": initiated_by_user_id,
        }
    )
    prior = _prior(c, producer_code, "test", str(test_run_id), fingerprint)
    if prior:
        return prior
    # Serialize concurrent attempts by one administrator before checking the rate.
    c.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (initiated_by_user_id,))
    count = c.execute(
        "SELECT count(*) AS n FROM event_history WHERE actor_user_id=%s AND operation='NOTIFICATION_TEST_SENT' AND occurred_at>clock_timestamp()-interval '1 hour'",
        (initiated_by_user_id,),
    ).fetchone()["n"]
    if count >= LIMITS["TEST_SENDS_PER_HOUR"]:
        invalid("notification_test_rate_limit", 429)
    definition, _ = verify_contract(c, producer_code)
    row = load_version(c, producer_code, configuration_version_id)
    payload = configuration_from_row(row)
    templates, _ = validate_configuration(
        c, definition, payload, resolve_audience=False
    )
    # A valid pending version may be tested before publication. Production
    # audiences are never resolved or used to select test recipients.
    selected = [
        Selector(selector_kind="user", target_id=uid) for uid in recipient_user_ids
    ]
    outcome = _write(
        c,
        definition,
        row,
        templates,
        selected,
        context,
        "test",
        str(test_run_id),
        fingerprint,
        initiated_by_user_id,
        test_run_id=test_run_id,
    )
    audit(
        c,
        initiated_by_user_id,
        "NOTIFICATION_TEST_SENT",
        producer_code,
        configuration_version_id,
        "Controlled notification test",
        test_run_id=str(test_run_id),
        recipient_count=len(recipient_user_ids),
        result=outcome.status,
        is_test=True,
    )
    return outcome


def _write(
    c,
    definition,
    row,
    templates,
    selected,
    context,
    event_type,
    event_id,
    fingerprint,
    actor,
    test_run_id=None,
):
    baseline = c.execute(
        "SELECT id,level_number FROM security_levels ORDER BY level_number LIMIT 1"
    ).fetchone()
    selectors, addresses = expand_system(c, selected)
    languages = enabled_languages(c)
    variants = render(c, definition, templates, context, languages)
    links = []
    if definition.resource_builder:
        config = definition.resource_configuration.model_validate(
            row["resource_presentation"]
        )
        built = definition.resource_builder(
            c, contracts.validate_context(definition, context), config
        )
        if (
            not isinstance(built, (tuple, list))
            or len(built) > LIMITS["MAX_RESOURCE_LINKS"]
        ):
            invalid("notification_resources_invalid")
        for item in built:
            try:
                link = ResourceLink.model_validate(item)
            except ValidationError:
                invalid("notification_resources_invalid")
            if link.resource_kind not in definition.resource_link_kinds:
                invalid("notification_resources_invalid")
            # With no triggering actor, retain the caller transaction's
            # authenticated backend principal. Ordinary resource policy still
            # applies; producer registration grants no additional authority.
            if actor is not None:
                c.execute("SELECT set_config('app.user_id',%s,true)", (str(actor),))
            target = resource(
                c, link.resource_kind, link.target_id, baseline["level_number"]
            )
            links.append((link, target))
        if len({str(link.link_token) for link, _ in links}) != len(links):
            invalid("notification_resources_invalid")
    prefixes = localized_labels(c, "messaging.test.label") if test_run_id else {}
    for variant in variants:
        if test_run_id:
            prefix = prefixes.get(variant["language_tag"])
            if not prefix:
                invalid("message_notice_catalogue_unavailable", 503)
            # The immutable is_test field remains authoritative in every UI.
            variant["subject"] = subject(prefix + " — " + variant["subject"])
        variant["body_rich_text"] = body(
            variant["body_rich_text"]
            + "".join(
                f'<p><span data-wathiq-link="{link.link_token}"></span></p>'
                for link, _ in links
            ),
            [str(link.link_token) for link, _ in links],
        )
    default = next(
        language["language_tag"] for language in languages if language["is_default"]
    )
    fallback = next(
        variant for variant in variants if variant["language_tag"] == default
    )
    identity = uuid4()
    request_id = uuid5(
        NAMESPACE_URL,
        f"wathiq:notification:{definition.producer_code}:{event_type}:{event_id}",
    )
    insert_envelope(
        c,
        {
            "id": identity,
            "sender_name": "system",
            "sender_kind": "system",
            "message_kind": "system_notification",
            "system_producer_code": definition.producer_code,
            "system_configuration_version_id": row["id"],
            "source_event_type": event_type,
            "source_event_id": event_id,
            "triggered_by_user_id": actor,
            "is_test": bool(test_run_id),
            "test_run_id": test_run_id,
            "test_initiated_by_user_id": actor if test_run_id else None,
            "subject": fallback["subject"],
            "body_rich_text": fallback["body_rich_text"],
            "priority": row["priority"],
            "security_level_id": baseline["id"],
            "action_required": False,
            "read_receipt_requested": False,
            "request_id": request_id,
        },
        retention_days=(
            LIMITS["TEST_RETENTION_DAYS"] if test_run_id else LIMITS["RETENTION_DAYS"]
        ),
    )
    for variant in variants:
        c.execute(
            "INSERT INTO message_envelope_localizations(envelope_id,language_tag,subject,body_rich_text,direction) VALUES (%s,%s,%s,%s,%s)",
            (
                identity,
                variant["language_tag"],
                variant["subject"],
                variant["body_rich_text"],
                variant["direction"],
            ),
        )
    for snapshot in selectors:
        selector = snapshot["selector"]
        c.execute(
            f"INSERT INTO message_recipient_selectors(envelope_id,recipient_type,selector_kind,{selector.selector_kind}_id,display_name,ordinal) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                identity,
                selector.recipient_type,
                selector.selector_kind,
                selector.target_id,
                snapshot["display_name"],
                snapshot["enumeration"],
            ),
        )
    for ordinal, (link, target) in enumerate(links):
        c.execute(
            f"INSERT INTO message_resource_links(envelope_id,link_token,ordinal,resource_kind,target_id_snapshot,{link.resource_kind}_id,security_level_id_at_send) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                identity,
                link.link_token,
                ordinal,
                link.resource_kind,
                link.target_id,
                link.target_id,
                target["security_level_id"],
            ),
        )
    fan_out(c, identity, addresses)
    c.execute(
        "INSERT INTO message_request_receipts(operation_kind,producer_code,request_id,request_fingerprint,source_event_type,source_event_id,result_envelope_id) VALUES ('send',%s,%s,%s,%s,%s,%s)",
        (
            definition.producer_code,
            request_id,
            fingerprint,
            event_type,
            event_id,
            identity,
        ),
    )
    return _result(c, identity)
