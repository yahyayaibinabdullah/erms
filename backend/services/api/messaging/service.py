"""Canonical send/fan-out service. The caller owns commit and rollback."""

from datetime import datetime, time, timedelta
from hashlib import sha256
import json
from uuid import uuid4
from zoneinfo import ZoneInfo
from psycopg import Connection, sql
from .config import LIMITS
from .content import body, invalid, subject
from .models import Send, Selector
from ..config import default_working_timezone

from .envelopes import insert_envelope

EXCHANGE = "messaging.user_messages.exchange"


def require_exchange(c: Connection, user: int):
    row = c.execute(
        "SELECT name FROM users WHERE id=%s AND status='active' AND account_type='person' AND user_has_global_privilege(id,%s)",
        (user, EXCHANGE),
    ).fetchone()
    if not row:
        invalid("insufficient_privilege", 403)
    return row["name"]


def level(c: Connection, user: int, requested: int | None):
    row = c.execute(
        "SELECT id,level_number FROM security_levels WHERE (%s::bigint IS NULL OR id=%s) ORDER BY level_number LIMIT 1",
        (requested, requested),
    ).fetchone()
    if (
        not row
        or not c.execute(
            "SELECT messaging_user_clearance(%s)>=%s AS allowed",
            (user, row["level_number"]),
        ).fetchone()["allowed"]
    ):
        invalid("insufficient_clearance", 403)
    return row


def selector_users(c: Connection, user: int, selected: Selector, required: int):
    kind = selected.selector_kind
    if kind == "everyone":
        rows = c.execute(
            "SELECT u.id,u.name FROM users u WHERE u.id<>%s AND messaging_user_eligible(u.id,%s) ORDER BY u.id LIMIT %s",
            (user, required, LIMITS["MAX_RECIPIENTS_PER_SEND"] + 1),
        ).fetchall()
        if not rows:
            invalid("message_selector_ineligible")
        return {"name": "Everyone"}, rows
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
        condition = f"""EXISTS(SELECT 1 FROM user_role_assignments a JOIN roles r ON r.id=a.role_id
          WHERE a.user_id=u.id AND {target}=%s AND role_effectively_active(r.id)
          AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP))"""
    rows = c.execute(
        f"""SELECT u.id,u.name FROM users u WHERE {condition} AND u.id<>%s
        AND messaging_user_eligible(u.id,%s) ORDER BY u.id LIMIT %s""",
        (selected.target_id, user, required, LIMITS["MAX_RECIPIENTS_PER_SEND"] + 1),
    ).fetchall()
    if not rows:
        cleared = c.execute(
            f"""SELECT EXISTS(SELECT 1 FROM users u WHERE {condition} AND u.id<>%s
            AND messaging_user_clearance(u.id)>=%s) AS allowed""",
            (selected.target_id, user, required),
        ).fetchone()["allowed"]
        invalid(
            "message_recipient_exchange_required"
            if cleared
            else "message_recipient_clearance_required"
        )
    return item, rows


def validate_everyone(selectors):
    everyone = [s for s in selectors if s.selector_kind == "everyone"]
    if not everyone:
        return
    if len(everyone) != 1:
        invalid("message_selector_ineligible")
    selected = everyone[0]
    if selected.recipient_type == "to" and len(selectors) != 1:
        invalid("message_selector_ineligible")
    if selected.recipient_type == "cc" and any(s is not selected and s.recipient_type == "cc" for s in selectors):
        invalid("message_selector_ineligible")


def expand(c: Connection, user: int, selectors: list[Selector], required: int):
    validate_everyone(selectors)
    if not any(x.recipient_type == "to" for x in selectors):
        invalid("message_to_required")
    snapshots = []
    addresses = {}
    seen = set()
    positions = {"to": 0, "cc": 0}
    for selected in selectors:
        key = (selected.recipient_type, selected.selector_kind, selected.target_id)
        if key in seen:
            invalid("message_selector_duplicate")
        seen.add(key)
        item, rows = selector_users(c, user, selected, required)
        snapshots.append(
            dict(
                enumeration=positions[selected.recipient_type],
                display_name=item["name"],
                selector=selected,
            )
        )
        positions[selected.recipient_type] += 1
        for recipient in rows:
            previous = addresses.get(recipient["id"])
            if previous is None or selected.recipient_type == "to":
                addresses[recipient["id"]] = {
                    **recipient,
                    "recipient_type": selected.recipient_type,
                }
        if len(addresses) > LIMITS["MAX_RECIPIENTS_PER_SEND"]:
            invalid("message_recipient_limit")
    return snapshots, addresses


RESOURCE_QUERIES = {
    "aggregation": (
        "aggregations t",
        "t.title",
        "t.security_level_id",
        "current_user_can_view_aggregation(t.id)",
    ),
    "record": (
        "records t",
        "t.title",
        "t.security_level_id",
        "current_user_can_view_record(t.id)",
    ),

}


def resource(c: Connection, kind: str, target: int, required: int):
    source, label, security, permission = RESOURCE_QUERIES[kind]
    row = c.execute(
        f"""SELECT t.id,{label} AS title,{security} AS security_level_id,l.level_number
        FROM {source} JOIN security_levels l ON l.id={security}
        WHERE t.id=%s AND {permission}""",
        (target,),
    ).fetchone()
    if not row:
        invalid("message_resource_unavailable")
    if row["level_number"] > required:
        invalid("message_resource_level_too_high")
    return row


def result(c: Connection, envelope):
    deliveries = c.execute(
        "SELECT id,recipient_user_id,recipient_type,mailbox_sequence FROM message_deliveries WHERE envelope_id=%s ORDER BY recipient_user_id",
        (envelope,),
    ).fetchall()
    return {
        "envelope_id": envelope,
        "deliveries": deliveries,
        "expanded_recipient_count": len(deliveries),
    }


def send(c: Connection, user: int, payload: Send, *, request_fingerprint=None):
    """Must be called in a consistent-snapshot transaction, including authorization."""
    if c.execute("SHOW transaction_isolation").fetchone()[
        "transaction_isolation"
    ] not in ("repeatable read", "serializable"):
        raise RuntimeError("Messaging send requires a consistent transaction snapshot")
    sender_name = require_exchange(c, user)
    clean_subject = subject(payload.subject)
    clean_body = body(
        payload.body_rich_text,
        [str(link.link_token) for link in payload.resource_links],
    )
    canonical = payload.model_dump(mode="json")
    for key in (
        "relationship_kind",
        "related_delivery_id",
        "related_envelope_id",
        "complete_action",
    ):
        if not canonical[key]:
            canonical.pop(key)
    canonical["subject"] = clean_subject
    canonical["body_rich_text"] = clean_body
    fingerprint = sha256(
        json.dumps(
            canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    fingerprint = request_fingerprint or fingerprint
    # Collisions can only cause extra serialization, not sharing of identities.
    lock = int.from_bytes(
        sha256(f"{user}:{payload.request_id}".encode()).digest()[:8], "big", signed=True
    )
    c.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
    prior = c.execute(
        "SELECT * FROM message_request_receipts WHERE operation_kind='send' AND principal_user_id=%s AND request_id=%s",
        (user, payload.request_id),
    ).fetchone()
    if prior:
        if prior["request_fingerprint"] != fingerprint:
            invalid("message_request_conflict", 409)
        if prior["result_purged_at"]:
            invalid("message_result_purged", 410)
        # Retrying must not bypass current message clearance.
        saved = c.execute(
            "SELECT security_level_id FROM message_envelopes WHERE id=%s",
            (prior["result_envelope_id"],),
        ).fetchone()
        level(c, user, saved["security_level_id"])
        return result(c, prior["result_envelope_id"])
    from .relationships import validate_source

    source = validate_source(c, user, payload)
    selected_level = level(c, user, payload.security_level_id)
    if source and selected_level["level_number"] < source["level_number"]:
        invalid("message_relationship_security_floor")
    selectors, addresses = expand(
        c, user, payload.selectors, selected_level["level_number"]
    )
    ordered_links = sorted(
        payload.resource_links, key=lambda x: clean_body.index(str(x.link_token))
    )
    links = [
        resource(c, x.resource_kind, x.target_id, selected_level["level_number"])
        for x in ordered_links
    ]
    due_at = due_zone = None
    if payload.action_due_date:
        if not payload.action_required:
            invalid("message_due_requires_action")
        pref = c.execute(
            "SELECT working_timezone FROM user_preferences WHERE user_id=%s", (user,)
        ).fetchone()
        due_zone = pref["working_timezone"] if pref else default_working_timezone(c)
        now = c.execute("SELECT CURRENT_TIMESTAMP AS instant").fetchone()["instant"]
        zone = ZoneInfo(due_zone)
        if payload.action_due_date < now.astimezone(zone).date():
            invalid("message_due_date_past")
        try:
            due_at = datetime.combine(
                payload.action_due_date + timedelta(days=1), time(), zone
            )
        except OverflowError:
            invalid("message_due_date_out_of_range")
    if payload.complete_action:
        from .actions import validate_completion

        validate_completion(c, user, payload, source, addresses)
    envelope = uuid4()
    insert_envelope(
        c,
        {
            "id": envelope,
            "sender_user_id": user,
            "sender_name": sender_name,
            "sender_kind": "user",
            "message_kind": "user_message",
            "subject": clean_subject,
            "priority": payload.priority,
            "body_rich_text": clean_body,
            "security_level_id": selected_level["id"],
            "action_required": payload.action_required,
            "action_due_date": payload.action_due_date,
            "action_due_timezone": due_zone,
            "action_due_at": due_at,
            "read_receipt_requested": payload.read_receipt_requested,
            "request_id": payload.request_id,
            "relationship_kind": payload.relationship_kind,
            "related_delivery_id": payload.related_delivery_id,
            "related_envelope_id": payload.related_envelope_id,
        },
        retention_days=LIMITS["RETENTION_DAYS"],
    )
    for snapshot in selectors:
        selected = snapshot["selector"]
        c.execute(
            sql.SQL(
                """INSERT INTO message_recipient_selectors(envelope_id,recipient_type,selector_kind,user_id,role_id,org_unit_id,display_name,ordinal)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"""
            ),
            (
                envelope,
                selected.recipient_type,
                selected.selector_kind,
                *(selected.target_id if selected.selector_kind == kind else None for kind in ("user", "role", "org_unit")),
                snapshot["display_name"],
                snapshot["enumeration"],
            ),
        )
    for ordinal, (link, target) in enumerate(zip(ordered_links, links)):
        c.execute(
            sql.SQL(
                """INSERT INTO message_resource_links(envelope_id,link_token,ordinal,resource_kind,target_id_snapshot,{},security_level_id_at_send)
            VALUES (%s,%s,%s,%s,%s,%s,%s)"""
            ).format(sql.Identifier(link.resource_kind + "_id")),
            (
                envelope,
                link.link_token,
                ordinal,
                link.resource_kind,
                link.target_id,
                link.target_id,
                target["security_level_id"],
            ),
        )
    fan_out(c, envelope, addresses)
    if payload.complete_action:
        c.execute(
            "INSERT INTO message_action_completions(original_delivery_id,reply_envelope_id,completed_by_user_id) VALUES (%s,%s,%s)",
            (payload.related_delivery_id, envelope, user),
        )
    c.execute(
        """INSERT INTO message_request_receipts(operation_kind,principal_user_id,request_id,request_fingerprint,result_envelope_id)
       VALUES ('send',%s,%s,%s,%s)""",
        (user, payload.request_id, fingerprint, envelope),
    )
    return result(c, envelope)


def fan_out(c, envelope, addresses):
    languages = {
        r["user_id"]: r["language_tag"]
        for r in c.execute(
            """SELECT u.id AS user_id,
       COALESCE(l.language_tag,(SELECT language_tag FROM supported_languages WHERE is_enabled ORDER BY is_default DESC,id LIMIT 1),'en') AS language_tag
       FROM users u LEFT JOIN user_preferences p ON p.user_id=u.id
       LEFT JOIN supported_languages l ON l.language_tag=p.language_tag AND l.is_enabled
       WHERE u.id=ANY(%s::bigint[])""",
            (list(addresses),),
        ).fetchall()
    }
    positions = {"to": 0, "cc": 0}
    # Ascending IDs order both INSERT conflict waits and row-update locks.
    for uid, address in sorted(addresses.items()):
        kind = address["recipient_type"]
        c.execute(
            "INSERT INTO message_addressees(envelope_id,user_id,recipient_name,recipient_type,ordinal) VALUES (%s,%s,%s,%s,%s)",
            (envelope, uid, address["name"], kind, positions[kind]),
        )
        positions[kind] += 1
        c.execute(
            "INSERT INTO message_mailboxes(user_id,last_sequence) VALUES (%s,0) ON CONFLICT DO NOTHING",
            (uid,),
        )
        sequence = c.execute(
            "UPDATE message_mailboxes SET last_sequence=last_sequence+1 WHERE user_id=%s RETURNING last_sequence",
            (uid,),
        ).fetchone()["last_sequence"]
        c.execute(
            """INSERT INTO message_deliveries(id,envelope_id,recipient_user_id,recipient_type,mailbox_sequence,language_tag_at_send)
            VALUES (%s,%s,%s,%s,%s,%s)""",
            (uuid4(), envelope, uid, kind, sequence, languages[uid]),
        )
