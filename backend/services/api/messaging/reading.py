"""Durable, owner-scoped reads. Resource checks are batched by target kind."""

import base64
import binascii
from datetime import datetime
from uuid import UUID
from .content import invalid
from .config import LIMITS
from ..entity_localization import preferred_language_for_user, localized_projection
from .service import RESOURCE_QUERIES, require_exchange

ACTIVE_INBOX = "d.deleted_at IS NULL AND (e.expires_at>CURRENT_TIMESTAMP OR d.purge_after>CURRENT_TIMESTAMP)"
ACTIVE_OUTBOX = "e.sender_deleted_at IS NULL AND (e.expires_at>CURRENT_TIMESTAMP OR e.sender_purge_after>CURRENT_TIMESTAMP)"
VISIBLE = "(e.sender_kind='system' OR user_has_global_privilege(%s,'messaging.user_messages.exchange'))"
PROJECTION = """e.*,l.level_number,l.name AS security_level_name,d.id AS delivery_id,d.mailbox_sequence,d.read_at,d.recipient_type,
 d.language_tag_at_send, messaging_user_clearance(%s)>=l.level_number AS readable"""
JOIN = "message_deliveries d JOIN message_envelopes e ON e.id=d.envelope_id JOIN security_levels l ON l.id=e.security_level_id"


def person(c, user):
    if not c.execute(
        "SELECT 1 FROM users WHERE id=%s AND status='active' AND account_type='person'",
        (user,),
    ).fetchone():
        invalid("insufficient_privilege", 403)


def cursor_encode(row, identity):
    return base64.urlsafe_b64encode(
        f"{row['sent_at'].isoformat()}|{row[identity]}".encode()
    ).decode()


def cursor_decode(value):
    try:
        timestamp, identity = base64.urlsafe_b64decode(value).decode().split("|")
        timestamp = datetime.fromisoformat(timestamp)
        if timestamp.tzinfo is None:
            raise ValueError()
        return timestamp, UUID(identity)
    except (ValueError, UnicodeError, binascii.Error):
        invalid("message_cursor_invalid")


def links_for(c, rows):
    ids = [r["id"] for r in rows if r["readable"]]
    links = (
        c.execute(
            "SELECT * FROM message_resource_links WHERE envelope_id=ANY(%s::uuid[]) ORDER BY envelope_id,ordinal",
            (ids,),
        ).fetchall()
        if ids
        else []
    )
    levels = {r["id"]: r["level_number"] for r in rows}
    targets = {}
    for kind, (source, label, security, permission) in RESOURCE_QUERIES.items():
        selected = [
            x[kind + "_id"]
            for x in links
            if x["resource_kind"] == kind and x[kind + "_id"] is not None
        ]
        if selected:
            targets[kind] = {
                r["id"]: r
                for r in c.execute(
                    f"""SELECT t.id,{label} AS title,t.{kind}_number AS number,l.level_number
                FROM {source} JOIN security_levels l ON l.id={security}
                WHERE t.id=ANY(%s::bigint[]) AND {permission}""",
                    (selected,),
                ).fetchall()
            }
    result = {}
    for link in links:
        kind = link["resource_kind"]
        target = targets.get(kind, {}).get(link[kind + "_id"])
        item = {
            "link_token": link["link_token"],
            "available": bool(
                target and target["level_number"] <= levels[link["envelope_id"]]
            ),
        }
        if item["available"]:
            item.update(
                resource_kind=kind, target_id=target["id"], title=target["title"], number=target["number"]
            )
        else:
            item["reason_code"] = "message_resource_unavailable"
        result.setdefault(link["envelope_id"], []).append(item)
    return result


def present(c, user, rows, *, detail=False):
    from .actions import decorate

    action_details = decorate(c, user, rows, detail)
    links = links_for(c, rows)
    ids = [r["id"] for r in rows if r["readable"]]
    headers = {}
    task_links = {}
    # One bounded projection query for the complete visible mailbox page.
    metadata = c.execute(
        """SELECT e.id,e.sender_user_id,u.translations AS sender_translations,
            CASE WHEN e.system_producer_code='disposition.task_assigned' AND NOT e.is_test THEN
              (SELECT jsonb_build_object('task_id',t.id,'job_id',t.job_id) FROM event_history src
               JOIN disposition_tasks t ON t.id=src.entity_id AND src.entity_type='disposition_task'
               WHERE src.id::text=e.source_event_id AND disposition_private.task_eligible(%s,t.id) LIMIT 1)
            END AS disposition_task,
            l.id AS level_id,l.code,l.name,l.translations,l.level_number,
            COALESCE((SELECT p.language_tag FROM user_preferences p
                JOIN supported_languages sl USING(language_tag)
                WHERE p.user_id=%s AND sl.is_enabled),
                (SELECT language_tag FROM supported_languages WHERE is_enabled
                 ORDER BY is_default DESC,id LIMIT 1),'en') AS language,
            COALESCE((SELECT jsonb_agg(jsonb_build_object(
                'recipient_type',s.recipient_type,'selector_kind',s.selector_kind,
                'display_name',s.display_name,'ordinal',s.ordinal,
                'translations',COALESCE(su.translations,sr.translations,so.translations,'{}'::jsonb))
                ORDER BY s.recipient_type DESC,s.ordinal)
                FROM message_recipient_selectors s
                LEFT JOIN users su ON su.id=s.user_id
                LEFT JOIN roles sr ON sr.id=s.role_id
                LEFT JOIN org_units so ON so.id=s.org_unit_id
                WHERE s.envelope_id=e.id),'[]'::jsonb) AS selectors
            FROM message_envelopes e
            JOIN security_levels l ON l.id=e.security_level_id
            LEFT JOIN users u ON u.id=e.sender_user_id
            WHERE e.id=ANY(%s::uuid[])""", (user, user, ids)
    ).fetchall() if ids else []
    language = metadata[0]['language'] if metadata else 'en'
    levels = {r['level_id']: r for r in metadata}
    senders = {r['sender_user_id']: r['sender_translations'] for r in metadata}
    from .notification_configuration import localized_labels
    everyone_labels = localized_labels(c, "messaging.field.everyone") if any(h["selector_kind"] == "everyone" for r in metadata for h in r["selectors"]) else {}
    for row in metadata:
        task_links[row['id']]=row.get('disposition_task')
        for header in row['selectors']:
            translations = header.pop("translations")
            header['display_name'] = everyone_labels.get(language, "Everyone") if header["selector_kind"] == "everyone" else localized_projection(
                {'name': header['display_name'], 'translations': translations},
                language, 'name')['name']
        headers[row['id']] = row['selectors']
    system_ids = [
        r["id"]
        for r in rows
        if r["readable"]
        and r["message_kind"] in ("system_notification", "action_amendment_notice")
    ]
    variants = {}
    toast_variants = {}
    if system_ids:
        localized = c.execute(
            "SELECT envelope_id,subject,body_rich_text,language_tag,direction FROM message_envelope_localizations WHERE envelope_id=ANY(%s::uuid[]) AND language_tag=ANY(%s::text[])",
            (
                system_ids,
                list(
                    {language}
                    | {
                        r["language_tag_at_send"]
                        for r in rows
                        if r.get("language_tag_at_send")
                    }
                ),
            ),
        ).fetchall()
        variants = {
            v["envelope_id"]: v for v in localized if v["language_tag"] == language
        }
        toast_variants = {(v["envelope_id"], v["language_tag"]): v for v in localized}
    captured = {r["selected_envelope_id"] for r in c.execute(
        "SELECT DISTINCT x.selected_envelope_id FROM message_record_captures x JOIN records r ON r.id=x.record_id WHERE x.captured_by_user_id=%s AND x.selected_envelope_id=ANY(%s::uuid[])", (user,ids)
    )} if ids else set()
    restricted = sum(not row["readable"] for row in rows)
    if restricted:
        from .operations import observe
        observe("restricted_count", restricted, connection=c)
    output = []
    for r in rows:
        item = {k: r[k] for k in ("sent_at",)}
        if "delivery_id" in r:
            item.update(
                id=r["delivery_id"],
                mailbox_sequence=r["mailbox_sequence"],
                is_read=r["read_at"] is not None,
            )
        else:
            item["id"] = r["id"]
        if not r["readable"]:
            item.update(availability="restricted", reason_code="message_restricted")
            output.append(item)
            continue
        item.update(
            {
                k: r[k]
                for k in (
                    "sender_name",
                    "sender_user_id",
                    "sender_kind",
                    "message_kind",
                    "subject",
                    "priority",
                    "security_level_id",
                    "action_required",
                    "action_due_date",
                    "action_due_timezone",
                    "action_due_at",
                    "read_receipt_requested",
                    "sent_at",
                    "expires_at",
                    "is_test",
                )
            }
        )
        security = levels.get(r['security_level_id'], {})
        item['sender_name'] = localized_projection(
            {'name': r['sender_name'], 'translations': senders.get(r['sender_user_id'])}, language, 'name')['name']
        item['recipient_names'] = [h['display_name'] for h in headers.get(r['id'], [])]
        item['security_level_code'] = security.get('code', '')
        item['security_level_number'] = security.get('level_number', r.get('level_number'))
        item.update(
            security_level_name=localized_projection(security, language, "name")["name"] or r.get("security_level_name", str(r["security_level_id"])),
            can_delete=r["message_kind"] != "user_message" or r["expires_at"] <= r["now"] or r["id"] in captured,
            expiry_warning=(r["expires_at"] - r["now"]).total_seconds()
            <= LIMITS["RETENTION_WARNING_DAYS"] * 86400,
            envelope_id=r["id"],
            availability="available",
            has_unavailable_resources=any(
                not x["available"] for x in links.get(r["id"], [])
            ),
        )
        if r["id"] in variants:
            item["subject"] = variants[r["id"]]["subject"]
            item["language_tag"] = variants[r["id"]]["language_tag"]
            item["direction"] = variants[r["id"]]["direction"]
        if r["id"] in system_ids and "delivery_id" in r:
            toast = toast_variants.get((r["id"], r.get("language_tag_at_send")))
            item["toast_subject"] = toast["subject"] if toast else r["subject"]
            item["toast_language_tag"] = r.get("language_tag_at_send")
        if "recipient_type" in r:
            item["recipient_type"] = r["recipient_type"]
        if r["action_required"] and "delivery_id" in r and r.get("recipient_type") == "to":
            item["action_status"] = (
                "late"
                if r["action_due_at"] and r["action_due_at"] <= r["now"]
                else "outstanding"
            )
        else:
            item["action_status"] = None
        if detail and task_links.get(r['id']):item['disposition_task']=task_links[r['id']]
        if detail:
            if r["sender_user_id"] == user:
                item["recipient_count"] = c.execute(
                    "SELECT count(*) AS n FROM message_addressees WHERE envelope_id=%s",
                    (r["id"],),
                ).fetchone()["n"]
            item.update(
                body_rich_text=variants.get(r["id"], r)["body_rich_text"],
                selectors=headers.get(r["id"], []),
                resource_links=links.get(r["id"], []),
            )
        item.update(action_details.get(r["id"], {}))
        output.append(item)
    return output


def inbox(c, user, limit, cursor=None, after=None, is_read=None, priority=None, recipient_kind=None, recipient_id=None, sent_from=None, sent_before=None, sender_user_id=None):
    person(c, user)
    clauses = ["d.recipient_user_id=%s", ACTIVE_INBOX, VISIBLE]
    args = [user, user]
    if sender_user_id is not None:
        clauses.append("(messaging_user_clearance(%s)>=l.level_number AND e.sender_user_id=%s)")
        args.extend((user, sender_user_id))
    if after is not None:
        clauses.append("d.mailbox_sequence>%s")
        args.append(after)
    if cursor:
        clauses.append("(d.created_at,d.id)<(%s,%s)")
        args.extend(cursor_decode(cursor))
    if is_read is not None:
        clauses.append("(d.read_at IS NOT NULL)=%s")
        args.append(is_read)
    for value, operator in ((sent_from, ">="), (sent_before, "<")):
        if value is not None:
            clauses.append(f"e.sent_at{operator}%s")
            args.append(value)
    if priority:
        # Filtering on protected priority must not leak restricted content.
        clauses.append(
            "(messaging_user_clearance(%s)>=l.level_number AND e.priority=%s)"
        )
        args.extend((user, priority))
    if (recipient_kind is None) != (recipient_id is None):
        invalid("message_recipient_filter_invalid")
    if recipient_kind:
        column = {"user": "user_id", "role": "role_id", "org_unit": "org_unit_id"}[recipient_kind]
        clauses.append(f"(messaging_user_clearance(%s)>=l.level_number AND EXISTS(SELECT 1 FROM message_recipient_selectors s WHERE s.envelope_id=e.id AND s.{column}=%s))")
        args.extend((user, recipient_id))
    order = (
        "d.mailbox_sequence ASC" if after is not None else "d.created_at DESC,d.id DESC"
    )
    rows = c.execute(
        f"SELECT {PROJECTION},CURRENT_TIMESTAMP AS now FROM {JOIN} WHERE "
        + " AND ".join(clauses)
        + f" ORDER BY {order} LIMIT %s",
        (user, *args, limit + 1),
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    output = {"items": present(c, user, rows), "has_more": more}
    if after is not None:
        high = c.execute(
            "SELECT last_sequence FROM message_mailboxes WHERE user_id=%s", (user,)
        ).fetchone()
        output["next_cursor"] = (
            rows[-1]["mailbox_sequence"]
            if more
            else max(after, high["last_sequence"] if high else 0)
        )
    else:
        output["next_cursor"] = cursor_encode(rows[-1], "delivery_id") if more else None
    return output


def delivery(c, user, identity, mark_read=False):
    person(c, user)
    row = c.execute(
        f"SELECT {PROJECTION},CURRENT_TIMESTAMP AS now FROM {JOIN} WHERE d.recipient_user_id=%s AND d.id=%s AND {ACTIVE_INBOX} AND {VISIBLE}",
        (user, user, identity, user),
    ).fetchone()
    if not row:
        invalid("message_not_found", 404)
    if mark_read:
        if not row["readable"]:
            invalid("message_restricted", 403)
        row["read_at"] = c.execute(
            "UPDATE message_deliveries SET read_at=COALESCE(read_at,CURRENT_TIMESTAMP) WHERE id=%s RETURNING read_at",
            (identity,),
        ).fetchone()["read_at"]
    return present(c, user, [row], detail=True)[0]


def outbox(
    c,
    user,
    limit,
    cursor=None,
    identity=None,
    q="",
    priority=None,
    security_level_id=None,
    action_required=None,
    sent_from=None,
    sent_before=None,
    action_state=None,
    recipient_kind=None,
    recipient_id=None,
):
    require_exchange(c, user)
    clauses = ["e.sender_user_id=%s", "e.message_kind='user_message'", ACTIVE_OUTBOX]
    args = [user]
    if identity:
        clauses.append("e.id=%s")
        args.append(identity)
    if cursor:
        clauses.append("(e.sent_at,e.id)<(%s,%s)")
        args.extend(cursor_decode(cursor))
    for value, expression in (
        (priority, "e.priority"),
        (security_level_id, "e.security_level_id"),
        (action_required, "COALESCE(am.new_action_required,e.action_required)"),
    ):
        if value is not None:
            clauses.append(
                f"(messaging_user_clearance(%s)>=l.level_number AND {expression}=%s)"
            )
            args.extend((user, value))
    if q:
        clauses.append(
            "(messaging_user_clearance(%s)>=l.level_number AND e.subject ILIKE %s)"
        )
        args.extend((user, "%" + q + "%"))
    for value, operator in ((sent_from, ">="), (sent_before, "<")):
        if value:
            clauses.append(f"e.sent_at{operator}%s")
            args.append(value)
    if (recipient_kind is None) != (recipient_id is None):
        invalid("message_recipient_filter_invalid")
    if recipient_kind:
        column = {"user": "user_id", "role": "role_id", "org_unit": "org_unit_id"}[
            recipient_kind
        ]
        clauses.append(
            f"(messaging_user_clearance(%s)>=l.level_number AND EXISTS(SELECT 1 FROM message_recipient_selectors s WHERE s.envelope_id=e.id AND s.{column}=%s))"
        )
        args.extend((user, recipient_id))
    if action_state:
        clauses.append(
            "messaging_user_clearance(%s)>=l.level_number AND COALESCE(am.new_action_required,e.action_required)"
        )
        args.append(user)
        clauses.append(
            "EXISTS(SELECT 1 FROM message_deliveries delivery LEFT JOIN message_action_completions completion ON completion.original_delivery_id=delivery.id WHERE delivery.envelope_id=e.id AND delivery.recipient_type='to' AND completion.original_delivery_id IS NULL)"
        )
        clauses.append(
            "(CASE WHEN am.id IS NULL THEN e.action_due_at ELSE am.new_due_at END)<CURRENT_TIMESTAMP"
            if action_state == "late"
            else "(CASE WHEN am.id IS NULL THEN e.action_due_at ELSE am.new_due_at END IS NULL OR CASE WHEN am.id IS NULL THEN e.action_due_at ELSE am.new_due_at END>=CURRENT_TIMESTAMP)"
        )
    rows = c.execute(
        "SELECT e.*,l.level_number,l.name AS security_level_name,CURRENT_TIMESTAMP AS now,messaging_user_clearance(%s)>=l.level_number AS readable FROM message_envelopes e JOIN security_levels l ON l.id=e.security_level_id LEFT JOIN LATERAL (SELECT * FROM message_action_amendments WHERE original_envelope_id=e.id ORDER BY sequence DESC LIMIT 1) am ON true WHERE "
        + " AND ".join(clauses)
        + " ORDER BY e.sent_at DESC,e.id DESC LIMIT %s",
        (user, *args, limit + 1),
    ).fetchall()
    if identity:
        if not rows:
            invalid("message_not_found", 404)
        return present(c, user, rows, detail=True)[0]
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": present(c, user, rows),
        "has_more": more,
        "next_cursor": cursor_encode(rows[-1], "id") if more else None,
    }


def receipts(c, user, identity, limit, after):
    message = outbox(c, user, 1, identity=identity)
    if message["availability"] != "available":
        invalid("message_restricted", 403)
    fields = ",d.read_at" if message["read_receipt_requested"] else ""
    rows = c.execute(
        f"""SELECT d.id,d.recipient_user_id,d.recipient_type,a.recipient_name,u.translations,completion.completed_at,completion.reply_envelope_id,reply_delivery.id AS completion_reply_delivery_id{fields}
        FROM message_deliveries d JOIN message_addressees a ON a.envelope_id=d.envelope_id AND a.user_id=d.recipient_user_id
        LEFT JOIN users u ON u.id=d.recipient_user_id
        LEFT JOIN message_action_completions completion ON completion.original_delivery_id=d.id
        LEFT JOIN message_deliveries reply_delivery ON reply_delivery.envelope_id=completion.reply_envelope_id AND reply_delivery.recipient_user_id=%s
        WHERE d.envelope_id=%s AND d.recipient_user_id>%s ORDER BY d.recipient_user_id LIMIT %s""",
        (user, identity, after, limit + 1),
    ).fetchall()
    from .actions import status

    now = c.execute("SELECT CURRENT_TIMESTAMP AS now").fetchone()["now"]
    last = c.execute(
        "SELECT previous_due_at FROM message_action_amendments WHERE original_envelope_id=%s ORDER BY sequence DESC LIMIT 1",
        (identity,),
    ).fetchone()
    language = preferred_language_for_user(c, user)
    for row in rows:
        row["recipient_name"] = localized_projection({"name": row["recipient_name"], "translations": row.pop("translations")}, language, "name")["name"]
        row["action_status"] = status(
            message["action_required"] and row["recipient_type"] == "to",
            message["effective_action"],
            row["completed_at"],
            now,
            last["previous_due_at"] if last else message["action_due_at"],
        )
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": rows,
        "has_more": more,
        "next_cursor": rows[-1]["recipient_user_id"] if more else None,
    }
