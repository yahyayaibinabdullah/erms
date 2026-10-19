"""Derived action state and atomic completion/amendment rules."""

from datetime import datetime, time, timedelta
from hashlib import sha256
from html import escape
import json
import unicodedata
from uuid import uuid4
from zoneinfo import ZoneInfo
from .envelopes import insert_envelope
from .config import LIMITS
from .content import invalid
from .service import level, require_exchange, result, fan_out
from ..config import default_working_timezone


def effective(c, envelope):
    latest = c.execute(
        "SELECT * FROM message_action_amendments WHERE original_envelope_id=%s ORDER BY sequence DESC LIMIT 1",
        (envelope["id"],),
    ).fetchone()
    return {
        "action_required": (
            latest["new_action_required"] if latest else envelope["action_required"]
        ),
        "due_date": latest["new_due_date"] if latest else envelope["action_due_date"],
        "due_timezone": (
            latest["new_due_timezone"] if latest else envelope["action_due_timezone"]
        ),
        "due_at": latest["new_due_at"] if latest else envelope["action_due_at"],
        "sequence": latest["sequence"] if latest else 0,
    }


def validate_completion(c, user, payload, source, addresses):
    if not source or source["sender_kind"] != "user" or not source["action_required"] or source.get("source_recipient_type") != "to":
        invalid("message_completion_unavailable")
    if not effective(c, source)["action_required"]:
        invalid("message_action_withdrawn", 409)
    if c.execute(
        "SELECT 1 FROM message_action_completions WHERE original_delivery_id=%s",
        (payload.related_delivery_id,),
    ).fetchone():
        invalid("message_action_already_completed", 409)
    if addresses.get(source["sender_user_id"], {}).get("recipient_type") != "to":
        invalid("message_completion_sender_to_required")


def status(original_required, state, completed_at, now, completion_due_at=None):
    if not original_required:
        return None
    if completed_at:
        boundary = state["due_at"] if state["action_required"] else completion_due_at
        return "completed_late" if boundary and completed_at > boundary else "completed"
    if not state["action_required"]:
        return "withdrawn"
    return "late" if state["due_at"] and now > state["due_at"] else "outstanding"


def amend(c, user, envelope_id, payload):
    require_exchange(c, user)
    reason = unicodedata.normalize("NFC", payload.reason).strip()
    if not reason or len(reason) > 2000:
        invalid("message_amendment_reason_invalid")
    canonical = {
        **payload.model_dump(mode="json"),
        "reason": reason,
        "original_envelope_id": str(envelope_id),
    }
    digest = sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prior = c.execute(
        "SELECT * FROM message_request_receipts WHERE operation_kind='amendment' AND principal_user_id=%s AND request_id=%s",
        (user, payload.request_id),
    ).fetchone()
    if prior:
        if prior["request_fingerprint"] != digest:
            invalid("message_request_conflict", 409)
        if prior["result_purged_at"]:
            invalid("message_result_purged", 410)
        row = c.execute(
            "SELECT security_level_id FROM message_envelopes WHERE id=%s",
            (prior["result_envelope_id"],),
        ).fetchone()
        level(c, user, row["security_level_id"])
        return {
            **result(c, prior["result_envelope_id"]),
            "amendment_id": prior["result_amendment_id"],
        }
    original = c.execute(
        "SELECT * FROM message_envelopes WHERE id=%s AND sender_user_id=%s AND message_kind='user_message' AND NOT is_test AND sender_deleted_at IS NULL AND expires_at>CURRENT_TIMESTAMP FOR UPDATE",
        (envelope_id, user),
    ).fetchone()
    if not original:
        invalid("message_not_found", 404)
    level(c, user, original["security_level_id"])
    old = effective(c, original)
    if not old["action_required"]:
        invalid("message_action_withdrawn", 409)
    kind = payload.amendment_kind
    date = payload.due_date
    zone = boundary = None
    if kind in ("due_date_added", "due_date_changed"):
        if date is None or (kind == "due_date_added") != (old["due_date"] is None):
            invalid("message_amendment_transition_invalid")
        pref = c.execute(
            "SELECT working_timezone FROM user_preferences WHERE user_id=%s", (user,)
        ).fetchone()
        zone = pref["working_timezone"] if pref else default_working_timezone(c)
        try:
            boundary = datetime.combine(
                date + timedelta(days=1), time(), ZoneInfo(zone)
            )
        except OverflowError:
            invalid("message_due_date_out_of_range")
        now = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        if boundary <= now:
            invalid("message_amendment_due_must_be_future")
        if (date, zone, boundary) == (
            old["due_date"],
            old["due_timezone"],
            old["due_at"],
        ):
            invalid("message_amendment_no_change")
        completed = c.execute(
            "SELECT completed_at FROM message_action_completions a JOIN message_deliveries d ON d.id=a.original_delivery_id WHERE d.envelope_id=%s",
            (envelope_id,),
        ).fetchall()
        if any(
            (old["due_at"] is None or r["completed_at"] <= old["due_at"])
            and r["completed_at"] > boundary
            for r in completed
        ):
            invalid("message_amendment_unfair")
    elif date is not None or (kind == "due_date_removed" and old["due_date"] is None):
        invalid("message_amendment_transition_invalid")
    amendment, notice = uuid4(), uuid4()
    c.execute(
        """INSERT INTO message_action_amendments(id,original_envelope_id,sequence,amendment_kind,previous_action_required,previous_due_date,previous_due_timezone,previous_due_at,new_action_required,new_due_date,new_due_timezone,new_due_at,reason,created_by_user_id,request_id)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            amendment,
            envelope_id,
            old["sequence"] + 1,
            kind,
            True,
            old["due_date"],
            old["due_timezone"],
            old["due_at"],
            kind != "action_withdrawn",
            date,
            zone,
            boundary,
            reason,
            user,
            payload.request_id,
        ),
    )
    # Fixed wording comes from the governed UI catalogue, in every enabled language.
    variants = notice_variants(c, reason)
    default = next((r for r in variants if r["is_default"]), variants[0])
    insert_envelope(
        c,
        {
            "id": notice,
            "sender_user_id": user,
            "sender_name": original["sender_name"],
            "sender_kind": "user",
            "message_kind": "action_amendment_notice",
            "action_amendment_id": amendment,
            "subject": default["subject"],
            "priority": original["priority"],
            "body_rich_text": default["body"],
            "security_level_id": original["security_level_id"],
            "action_required": False,
            "read_receipt_requested": False,
            "expires_at": original["expires_at"],
            "request_id": payload.request_id,
        },
    )
    for v in variants:
        c.execute(
            "INSERT INTO message_envelope_localizations(envelope_id,language_tag,subject,body_rich_text,direction) VALUES (%s,%s,%s,%s,%s)",
            (notice, v["language_tag"], v["subject"], v["body"], v["direction"]),
        )
    c.execute(
        """INSERT INTO message_recipient_selectors(envelope_id,recipient_type,selector_kind,user_id,role_id,org_unit_id,display_name,ordinal)
        SELECT %s,recipient_type,selector_kind,user_id,role_id,org_unit_id,display_name,ordinal FROM message_recipient_selectors WHERE envelope_id=%s""",
        (notice, envelope_id),
    )
    addresses = {
        r["user_id"]: {
            "name": r["recipient_name"],
            "recipient_type": r["recipient_type"],
        }
        for r in c.execute(
            "SELECT * FROM message_addressees WHERE envelope_id=%s", (envelope_id,)
        ).fetchall()
    }
    fan_out(c, notice, addresses)
    c.execute(
        "INSERT INTO message_request_receipts(operation_kind,principal_user_id,request_id,request_fingerprint,result_envelope_id,result_amendment_id) VALUES ('amendment',%s,%s,%s,%s,%s)",
        (user, payload.request_id, digest, notice, amendment),
    )
    return {**result(c, notice), "amendment_id": amendment}


def notice_variants(c, reason):
    rows = c.execute(
        """SELECT l.language_tag,l.direction,l.is_default,
       COALESCE(t.published_text,b.published_text,d.default_text) AS subject FROM supported_languages l
       CROSS JOIN ui_message_definitions d LEFT JOIN ui_message_translations t ON t.message_key=d.message_key
       AND t.language_tag=l.language_tag AND t.published_text IS NOT NULL AND NOT t.needs_review
       LEFT JOIN ui_message_translations b ON b.message_key=d.message_key AND b.language_tag=split_part(l.language_tag,'-',1) AND b.published_text IS NOT NULL AND NOT b.needs_review
       WHERE l.is_enabled AND d.message_key='messaging.notice.action_amended' ORDER BY l.id"""
    ).fetchall()
    if not rows:
        invalid("message_notice_catalogue_unavailable", 503)
    return [
        {
            **r,
            "body": "<p>" + escape(r["subject"]) + "</p><p>" + escape(reason) + "</p>",
        }
        for r in rows
    ]


def decorate(c, user, rows, detail=False):
    """Bounded batch projection for message lists and owned delivery details."""
    ids = [r["id"] for r in rows if r["readable"]]
    if not ids:
        return {}
    latest = {
        r["original_envelope_id"]: r
        for r in c.execute(
            "SELECT DISTINCT ON (original_envelope_id) * FROM message_action_amendments WHERE original_envelope_id=ANY(%s::uuid[]) ORDER BY original_envelope_id,sequence DESC",
            (ids,),
        ).fetchall()
    }
    deliveries = [
        r["delivery_id"] for r in rows if r.get("delivery_id") and r["readable"]
    ]
    completions = (
        {
            r["original_delivery_id"]: r
            for r in c.execute(
                "SELECT * FROM message_action_completions WHERE original_delivery_id=ANY(%s::uuid[])",
                (deliveries,),
            ).fetchall()
        }
        if deliveries
        else {}
    )
    completion_replies = {
        r["reply_envelope_id"]
        for r in c.execute(
            "SELECT reply_envelope_id FROM message_action_completions WHERE reply_envelope_id=ANY(%s::uuid[])",
            (ids,),
        ).fetchall()
    }
    output = {}
    for r in rows:
        if not r["readable"]:
            continue
        a = latest.get(r["id"])
        state = {
            "action_required": a["new_action_required"] if a else r["action_required"],
            "due_date": a["new_due_date"] if a else r["action_due_date"],
            "due_timezone": a["new_due_timezone"] if a else r["action_due_timezone"],
            "due_at": a["new_due_at"] if a else r["action_due_at"],
        }
        completion = completions.get(r.get("delivery_id"))
        item = {
            "effective_action": state,
            "amendment_sequence": a["sequence"] if a else 0,
            "is_completion_reply": r["id"] in completion_replies,
            "relationship_kind": r["relationship_kind"],
            "related_delivery_id": r["related_delivery_id"],
            "related_envelope_id": r["related_envelope_id"],
        }
        if r.get("delivery_id"):
            item["action_status"] = status(
                r["action_required"] and r.get("recipient_type") == "to",
                state,
                completion["completed_at"] if completion else None,
                r["now"],
                a["previous_due_at"] if a else r["action_due_at"],
            )
            item["completion_reply_envelope_id"] = (
                completion["reply_envelope_id"] if completion else None
            )
        if detail:
            parent = c.execute(
                """SELECT COALESCE(%s::uuid,
                (SELECT envelope_id FROM message_deliveries WHERE id=%s),
                (SELECT original_envelope_id FROM message_action_amendments WHERE id=%s)) AS id""",
                (
                    r["related_envelope_id"],
                    r["related_delivery_id"],
                    r["action_amendment_id"],
                ),
            ).fetchone()
            item["linked_envelope_id"] = parent["id"]
            history = c.execute(
                "SELECT * FROM message_action_amendments WHERE original_envelope_id=%s ORDER BY sequence LIMIT 51",
                (r["id"],),
            ).fetchall()
            item["amendments"] = history[:50]
            item["amendments_next_cursor"] = (
                history[49]["sequence"] if len(history) > 50 else None
            )
            if r["message_kind"] == "action_amendment_notice":
                notice = c.execute(
                    "SELECT * FROM message_action_amendments WHERE id=%s",
                    (r["action_amendment_id"],),
                ).fetchone()
                item["amendment_notice"] = notice
        output[r["id"]] = item
    return output


def history(c, user, identity, limit, after, root=None):
    from .reading import outbox, delivery

    if root is not None:
        from .relationships import linked

        allowed = linked(c, user, root, identity)
    else:
        row = c.execute(
            "SELECT sender_user_id FROM message_envelopes WHERE id=%s", (identity,)
        ).fetchone()
        if row and row["sender_user_id"] == user:
            allowed = outbox(c, user, 1, identity=identity)
        else:
            d = c.execute(
                "SELECT id FROM message_deliveries WHERE envelope_id=%s AND recipient_user_id=%s",
                (identity, user),
            ).fetchone()
            if not d:
                invalid("message_not_found", 404)
            allowed = delivery(c, user, d["id"])
    if allowed["availability"] != "available":
        invalid("message_restricted", 403)
    rows = c.execute(
        "SELECT * FROM message_action_amendments WHERE original_envelope_id=%s AND sequence>%s ORDER BY sequence LIMIT %s",
        (identity, after, limit + 1),
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": rows,
        "has_more": more,
        "next_cursor": rows[-1]["sequence"] if more else None,
    }
