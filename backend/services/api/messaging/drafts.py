"""Private, versioned compose documents; send and removal share one transaction."""

from datetime import datetime, time, timedelta
from uuid import uuid4
import unicodedata
from psycopg import sql
from pydantic import ValidationError
from .config import LIMITS
from .content import body, invalid
from .models import Send
from .service import level, require_exchange, send
from ..config import default_working_timezone


def get(c, user, identity, lock=False, deleted=False):
    require_exchange(c, user)
    row = c.execute(
        "SELECT * FROM message_drafts WHERE id=%s AND owner_user_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (identity, user),
    ).fetchone()
    if not row:
        invalid("message_draft_not_found", 404)
    level(c, user, row["security_level_id"])
    now = c.execute("SELECT CURRENT_TIMESTAMP AS now").fetchone()["now"]
    expired = row["expires_at"] <= now
    removed = row["deleted_at"] is not None or expired
    deadline = row["purge_after"] or row["expires_at"] + timedelta(
        days=row["expiry_restoration_days"]
    )
    if removed and (not deleted or deadline <= now):
        invalid("message_draft_not_found", 404)
    row["selectors"] = [
        {
            "selector_kind": r["selector_kind"],
            "recipient_type": r["recipient_type"],
            "target_id": None if r["selector_kind"] == "everyone" else r[r["selector_kind"] + "_id"],
        }
        for r in c.execute(
            "SELECT * FROM message_draft_recipient_selectors WHERE draft_id=%s ORDER BY recipient_type DESC,ordinal",
            (identity,),
        ).fetchall()
    ]
    row["resource_links"] = [
        {
            "link_token": r["link_token"],
            "resource_kind": r["resource_kind"],
            "target_id": r["target_id_snapshot"],
        }
        for r in c.execute(
            "SELECT * FROM message_draft_resource_links WHERE draft_id=%s ORDER BY ordinal",
            (identity,),
        ).fetchall()
    ]
    row["is_deleted"] = removed
    row["restorable_until"] = deadline if removed else None
    return row


def listing(c, user, limit, after=None, deleted=False, recipient_kind=None, recipient_id=None):
    require_exchange(c, user)
    condition = (
        "(deleted_at IS NOT NULL OR expires_at<=CURRENT_TIMESTAMP) AND COALESCE(purge_after,expires_at+make_interval(days=>expiry_restoration_days))>CURRENT_TIMESTAMP"
        if deleted
        else "deleted_at IS NULL AND expires_at>CURRENT_TIMESTAMP"
    )
    args = [user]
    if (recipient_kind is None) != (recipient_id is None):
        invalid("message_recipient_filter_invalid")
    if recipient_kind:
        column = {"user": "user_id", "role": "role_id", "org_unit": "org_unit_id"}[recipient_kind]
        condition += f" AND messaging_user_clearance(%s)>=(SELECT level_number FROM security_levels WHERE id=message_drafts.security_level_id) AND EXISTS(SELECT 1 FROM message_draft_recipient_selectors s WHERE s.draft_id=message_drafts.id AND s.{column}=%s)"
        args.extend((user, recipient_id))
    if after:
        from .reading import cursor_decode

        condition += " AND (date_updated,id)<(%s,%s)"
        args.extend(cursor_decode(after))
    rows = c.execute(
        "SELECT id,subject,date_updated,expires_at,version,deleted_at,purge_after, messaging_user_clearance(%s)>=(SELECT level_number FROM security_levels WHERE id=message_drafts.security_level_id) AS readable, (subject='' OR body_rich_text='' OR NOT EXISTS(SELECT 1 FROM message_draft_recipient_selectors s WHERE s.draft_id=message_drafts.id AND s.recipient_type='to')) AS needs_attention, expires_at<=CURRENT_TIMESTAMP+make_interval(days=>%s) AS expiry_warning FROM message_drafts WHERE owner_user_id=%s AND "
        + condition
        + " ORDER BY date_updated DESC,id DESC LIMIT %s",
        (user, LIMITS["DRAFT_WARNING_DAYS"], *args, limit + 1),
    ).fetchall()
    for row in rows:
        if not row.pop("readable"):
            row["subject"] = None
            row["needs_attention"] = True
            row["availability"] = "restricted"
    more = len(rows) > limit
    rows = rows[:limit]
    from .reading import cursor_encode

    cursor = (
        cursor_encode({"sent_at": rows[-1]["date_updated"], "id": rows[-1]["id"]}, "id")
        if more
        else None
    )
    return {"items": rows, "has_more": more, "next_cursor": cursor}


def save(c, user, payload, identity=None, version=None):
    require_exchange(c, user)
    selected = level(c, user, payload.security_level_id)
    clean_subject = unicodedata.normalize("NFC", payload.subject).strip()
    if len(clean_subject) > 255:
        invalid("message_subject_invalid")
    clean_body = body(
        payload.body_rich_text, [str(x.link_token) for x in payload.resource_links]
    )
    if payload.action_due_date and not payload.action_required:
        invalid("message_due_requires_action")
    pref = c.execute(
        "SELECT working_timezone FROM user_preferences WHERE user_id=%s", (user,)
    ).fetchone()
    fields = {
        **payload.model_dump(exclude={"selectors", "resource_links"}),
        "subject": clean_subject,
        "body_rich_text": clean_body,
        "security_level_id": selected["id"],
        "action_due_timezone": (
            (pref["working_timezone"] if pref else default_working_timezone(c))
            if payload.action_due_date
            else None
        ),
    }
    if identity:
        current = get(c, user, identity, True)
        if current["version"] != version:
            invalid("message_draft_version_conflict", 409)
        c.execute(
            sql.SQL(
                "UPDATE message_drafts SET {},version=version+1,date_updated=CURRENT_TIMESTAMP,expires_at=CURRENT_TIMESTAMP+make_interval(days=>%s) WHERE id=%s"
            ).format(
                sql.SQL(",").join(
                    sql.SQL("{}=%s").format(sql.Identifier(k)) for k in fields
                )
            ),
            (*fields.values(), LIMITS["DRAFT_ACTIVE_DAYS"], identity),
        )
        c.execute(
            "DELETE FROM message_draft_recipient_selectors WHERE draft_id=%s",
            (identity,),
        )
        c.execute(
            "DELETE FROM message_draft_resource_links WHERE draft_id=%s", (identity,)
        )
    else:
        identity = uuid4()
        c.execute(
            sql.SQL(
                "INSERT INTO message_drafts(id,owner_user_id,{},expires_at,expiry_restoration_days) VALUES (%s,%s,{},CURRENT_TIMESTAMP+make_interval(days=>%s),%s)"
            ).format(
                sql.SQL(",").join(map(sql.Identifier, fields)),
                sql.SQL(",").join(sql.Placeholder() for _ in fields),
            ),
            (identity, user, *fields.values(), LIMITS["DRAFT_ACTIVE_DAYS"], LIMITS["DRAFT_RECOVERY_DAYS"]),
        )
    from .service import validate_everyone
    validate_everyone(payload.selectors)
    positions = {"to": 0, "cc": 0}
    for selected in payload.selectors:
        table = {"user": "users", "role": "roles", "org_unit": "org_units"}.get(selected.selector_kind)
        row = {"name": "Everyone"} if table is None else c.execute(
            sql.SQL("SELECT name FROM {} WHERE id=%s").format(sql.Identifier(table)),
            (selected.target_id,),
        ).fetchone()
        if not row:
            invalid("message_selector_ineligible")
        c.execute(
            sql.SQL(
                "INSERT INTO message_draft_recipient_selectors(draft_id,recipient_type,selector_kind,user_id,role_id,org_unit_id,display_name,ordinal) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
            ),
            (
                identity,
                selected.recipient_type,
                selected.selector_kind,
                *(selected.target_id if selected.selector_kind == kind else None for kind in ("user", "role", "org_unit")),
                row["name"],
                positions[selected.recipient_type],
            ),
        )
        positions[selected.recipient_type] += 1
    from .service import RESOURCE_QUERIES

    for ordinal, link in enumerate(
        sorted(
            payload.resource_links, key=lambda x: clean_body.index(str(x.link_token))
        )
    ):
        source, _, security, permission = RESOURCE_QUERIES[link.resource_kind]
        target = c.execute(
            f"SELECT {security} AS security_level_id FROM {source} WHERE t.id=%s AND {permission}",
            (link.target_id,),
        ).fetchone()
        if not target:
            invalid("message_resource_unavailable")
        c.execute(
            sql.SQL(
                "INSERT INTO message_draft_resource_links(draft_id,link_token,ordinal,resource_kind,target_id_snapshot,{},security_level_id_at_send) VALUES (%s,%s,%s,%s,%s,%s,%s)"
            ).format(sql.Identifier(link.resource_kind + "_id")),
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
    return get(c, user, identity)


def discard(c, user, identity, version, restore=False):
    current = get(c, user, identity, True, deleted=restore)
    if current["version"] != version:
        invalid("message_draft_version_conflict", 409)
    if restore:
        if not current["is_deleted"]:
            invalid("message_draft_not_deleted", 409)
        c.execute(
            "UPDATE message_drafts SET deleted_at=NULL,purge_after=NULL,deletion_reason=NULL,version=version+1,date_updated=CURRENT_TIMESTAMP,expires_at=CURRENT_TIMESTAMP+make_interval(days=>%s) WHERE id=%s",
            (LIMITS["DRAFT_ACTIVE_DAYS"], identity),
        )
    else:
        c.execute(
            "UPDATE message_drafts SET deleted_at=CURRENT_TIMESTAMP,purge_after=CURRENT_TIMESTAMP+make_interval(days=>%s),deletion_reason='discarded',version=version+1,date_updated=CURRENT_TIMESTAMP WHERE id=%s",
            (LIMITS["DRAFT_RECOVERY_DAYS"], identity),
        )
    return get(c, user, identity, deleted=True)


def send_draft(c, user, identity, payload):
    # The draft may be gone after success. The submitted version and draft UUID
    # are included in the request digest so a retry can be recognized safely.
    require_exchange(c, user)
    import hashlib, json
    from .service import result

    digest = hashlib.sha256(
        json.dumps(
            {"draft_id": str(identity), **payload.model_dump(mode="json")},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    receipt = c.execute(
        "SELECT * FROM message_request_receipts WHERE operation_kind='send' AND principal_user_id=%s AND request_id=%s",
        (user, payload.request_id),
    ).fetchone()
    if receipt:
        if receipt["request_fingerprint"] != digest:
            invalid("message_request_conflict", 409)
        if receipt["result_purged_at"]:
            invalid("message_result_purged", 410)
        envelope = c.execute(
            "SELECT security_level_id FROM message_envelopes WHERE id=%s",
            (receipt["result_envelope_id"],),
        ).fetchone()
        level(c, user, envelope["security_level_id"])
        return result(c, receipt["result_envelope_id"])
    current = get(c, user, identity, True)
    if current["version"] != payload.version:
        invalid("message_draft_version_conflict", 409)
    fields = {
        k: current[k]
        for k in (
            "subject",
            "body_rich_text",
            "priority",
            "security_level_id",
            "action_required",
            "action_due_date",
            "read_receipt_requested",
            "relationship_kind",
            "related_delivery_id",
            "related_envelope_id",
            "selectors",
            "resource_links",
        )
    }
    try:
        message = Send(
            **fields,
            request_id=payload.request_id,
            complete_action=payload.complete_action,
        )
    except ValidationError:
        invalid("message_draft_incomplete")
    outcome = send(c, user, message, request_fingerprint=digest)
    c.execute(
        "DELETE FROM message_draft_recipient_selectors WHERE draft_id=%s", (identity,)
    )
    c.execute("DELETE FROM message_draft_resource_links WHERE draft_id=%s", (identity,))
    c.execute("DELETE FROM message_drafts WHERE id=%s", (identity,))
    return outcome
