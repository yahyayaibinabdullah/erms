"""Frontend-neutral Phase 1 messaging endpoints; no system-sender impersonation."""

from datetime import datetime
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Header
from ..operation_policy import operation_policy
from ..authentication import Principal, principal_from_request
from ..entity_localization import preferred_language_for_user, localized_projection
from ..authorization_policy import require_global_privilege
from . import reading
from .config import LIMITS
from .models import RecipientValidation, Send, Amendment, Draft, DraftSend
from . import drafts
from .service import RESOURCE_QUERIES, expand, level, require_exchange, send
from .transactions import run

router = APIRouter(prefix="/api/v1/messages", tags=["messages"])
require_exchange_privilege = require_global_privilege(
    "messaging.user_messages.exchange"
)
PageSize = Query(25, ge=1, le=50)
Priority = Literal["normal", "high", "very_high"]


@router.get("/capabilities", dependencies=[Depends(require_exchange_privilege)])
def capabilities(principal: Principal = Depends(principal_from_request)):
    def operation(c):
        require_exchange(c, principal.user_id)
        levels = c.execute(
            "SELECT id,code,name,translations,level_number FROM security_levels WHERE level_number<=messaging_user_clearance(%s) ORDER BY level_number",
            (principal.user_id,),
        ).fetchall()
        language = preferred_language_for_user(c, principal.user_id)
        for row in levels:
            row['name'] = localized_projection(row, language, 'name')['name']
            row.pop('translations', None)
        return {
            "limits": LIMITS,
            "security_levels": levels,
            "default_security_level_id": levels[0]["id"] if levels else None,
        }

    return run(principal.user_id, operation)


@router.post("/recipients/validate", dependencies=[Depends(require_exchange_privilege)])
def validate(
    payload: RecipientValidation, principal: Principal = Depends(principal_from_request)
):
    def operation(c):
        require_exchange(c, principal.user_id)
        selected = level(c, principal.user_id, payload.security_level_id)
        _, addresses = expand(
            c, principal.user_id, payload.selectors, selected["level_number"]
        )
        return {"expanded_recipient_count": len(addresses), "is_preview": True}

    return run(principal.user_id, operation)


@router.get("/recipients/{kind}", dependencies=[Depends(require_exchange_privilege)])
def recipients(
    kind: Literal["user", "role", "org_unit"],
    purpose: Literal["compose", "filter"] = "compose",
    q: str = Query("", max_length=120),
    target_id: int | None = Query(None, gt=0),
    security_level_id: int | None = Query(None, gt=0),
    after: int = Query(0, ge=0),
    limit: int = PageSize,
    principal: Principal = Depends(principal_from_request),
):
    def operation(c):
        require_exchange(c, principal.user_id)
        selected = level(c, principal.user_id, security_level_id) if purpose == "compose" else None
        table = {"user": "users", "role": "roles", "org_unit": "org_units"}[kind]
        live = {
            "user": "t.status='active' AND t.account_type='person'" + (" AND t.id<>%s" if purpose == "compose" else ""),
            "role": "role_effectively_active(t.id)",
            "org_unit": "org_unit_effectively_active(t.id)",
        }[kind]
        # Directory identity fields include email for person recipients.
        # Messaging further excludes inactive entities and self, and never lists
        # concrete members of role/unit selectors to a recipient.
        params = [principal.user_id] if kind == "user" and purpose == "compose" else []
        rows = c.execute(
            f"""SELECT t.id,t.name,t.description,t.translations,
            {"t.email" if kind == "user" else "NULL::text"} AS email
            FROM {table} t WHERE {live} AND t.id>%s
            AND (%s::bigint IS NULL OR t.id=%s)
            AND (t.name ILIKE %s OR t.description ILIKE %s
                 OR {"t.external_id" if kind == "user" else "t.code"} ILIKE %s
                 OR {"t.email" if kind == "user" else "NULL::text"} ILIKE %s
                 OR EXISTS (SELECT 1 FROM jsonb_each(COALESCE(t.translations, '{{}}'::jsonb)) tr
                    JOIN supported_languages lang ON lang.language_tag=tr.key AND lang.is_enabled
                    WHERE tr.value->>'name' ILIKE %s OR tr.value->>'description' ILIKE %s))
            ORDER BY t.id LIMIT %s""",
            (*params, after, target_id, target_id, *(["%" + q + "%"] * 6), limit + 1),
        ).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        if purpose == "filter":
            language = preferred_language_for_user(c, principal.user_id)
            for row in rows:
                row["name"] = localized_projection(row, language, "name")["name"]
                row.pop("translations", None)
                row.pop("description", None)
            return {"items": rows, "has_more": more,
                    "next_cursor": rows[-1]["id"] if more else None}
        ids = [r["id"] for r in rows]
        if kind == "user":
            membership = "u.id=t.id"
        else:
            target = "r.id" if kind == "role" else "r.org_unit_id"
            membership = f"""EXISTS(SELECT 1 FROM roles r JOIN user_role_assignments a ON a.role_id=r.id
                WHERE a.user_id=u.id AND {target}=t.id AND role_effectively_active(r.id)
                AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP))"""
        # Two EXISTS predicates distinguish clearance from exchange failure;
        # no unbounded member collection is returned to Python or the client.
        eligible = c.execute(
            f"""SELECT t.id,
            EXISTS(SELECT 1 FROM users u WHERE {membership} AND u.id<>%s AND messaging_user_eligible(u.id,%s)) AS eligible,
            EXISTS(SELECT 1 FROM users u WHERE {membership} AND u.id<>%s AND messaging_user_clearance(u.id)>=%s) AS cleared
            FROM {table} t WHERE t.id=ANY(%s::bigint[])""",
            (
                principal.user_id,
                selected["level_number"],
                principal.user_id,
                selected["level_number"],
                ids,
            ),
        ).fetchall()
        checks = {r["id"]: r for r in eligible}
        language = preferred_language_for_user(c, principal.user_id)
        for row in rows:
            row["name"] = localized_projection(row, language, "name")["name"]
            row.pop("translations", None)
            row.pop("description", None)
            check = checks[row["id"]]
            row.update(
                eligible=check["eligible"],
                reason_code=(
                    None
                    if check["eligible"]
                    else (
                        "message_recipient_exchange_required"
                        if check["cleared"]
                        else "message_recipient_clearance_required"
                    )
                ),
            )
        return {
            "items": rows,
            "has_more": more,
            "next_cursor": rows[-1]["id"] if more else None,
        }

    return run(principal.user_id, operation)


@router.get("/resources/{kind}")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def resources(
    kind: Literal["aggregation", "record"],
    q: str = Query("", max_length=120),
    target_id: int | None = Query(None, gt=0),
    security_level_id: int | None = Query(None, gt=0),
    after: int = Query(0, ge=0),
    limit: int = PageSize,
    principal: Principal = Depends(principal_from_request),
):
    def operation(c):
        require_exchange(c, principal.user_id)
        selected = level(c, principal.user_id, security_level_id)
        source, label, security, permission = RESOURCE_QUERIES[kind]
        rows = c.execute(
            f"""SELECT t.id,{label} AS title,{security} AS security_level_id,l.level_number
            FROM {source} JOIN security_levels l ON l.id={security}
            WHERE {permission} AND t.id>%s AND (%s::bigint IS NULL OR t.id=%s)
            AND {label} ILIKE %s ORDER BY t.id LIMIT %s""",
            (after, target_id, target_id, "%" + q + "%", limit + 1),
        ).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        for row in rows:
            row["eligible"] = row.pop("level_number") <= selected["level_number"]
            row["reason_code"] = (
                None if row["eligible"] else "message_resource_level_too_high"
            )
        return {
            "items": rows,
            "has_more": more,
            "next_cursor": rows[-1]["id"] if more else None,
        }

    return run(principal.user_id, operation)


@router.post("/send", dependencies=[Depends(require_exchange_privilege)])
def send_message(payload: Send, principal: Principal = Depends(principal_from_request)):
    return run(principal.user_id, lambda c: send(c, principal.user_id, payload))


@router.get("/inbox")
@operation_policy("relationship_scoped")
def inbox(
    limit: int = PageSize,
    cursor: str | None = Query(None, max_length=200),
    is_read: bool | None = None,
    priority: Priority | None = None,
    sent_from: datetime | None = None,
    sent_before: datetime | None = None,
    sender_user_id: int | None = Query(None, gt=0),
    recipient_kind: Literal["user", "role", "org_unit"] | None = None,
    recipient_id: int | None = Query(None, gt=0),
    principal: Principal = Depends(principal_from_request),
):
    return run(
        principal.user_id,
        lambda c: reading.inbox(
            c,
            principal.user_id,
            limit,
            cursor=cursor,
            is_read=is_read,
            priority=priority,
            sent_from=sent_from,
            sent_before=sent_before,
            sender_user_id=sender_user_id,
            recipient_kind=recipient_kind,
            recipient_id=recipient_id,
        ),
    )


@router.get("/catch-up")
@operation_policy("relationship_scoped")
def catch_up(
    after: int = Query(0, ge=0, le=9223372036854775807),
    limit: int = PageSize,
    principal: Principal = Depends(principal_from_request),
):
    return run(
        principal.user_id,
        lambda c: reading.inbox(c, principal.user_id, limit, after=after),
    )


@router.get("/unread-count")
@operation_policy("relationship_scoped")
def unread(principal: Principal = Depends(principal_from_request)):
    def operation(c):
        reading.person(c, principal.user_id)
        return c.execute(
            f"""SELECT count(*) AS unread_count FROM {reading.JOIN}
            WHERE d.recipient_user_id=%s AND d.read_at IS NULL AND {reading.ACTIVE_INBOX} AND {reading.VISIBLE}""",
            (principal.user_id, principal.user_id),
        ).fetchone()

    return run(principal.user_id, operation)


@router.get("/inbox/{delivery_id}")
@operation_policy("relationship_scoped")
def get_delivery(
    delivery_id: UUID, principal: Principal = Depends(principal_from_request)
):
    return run(
        principal.user_id, lambda c: reading.delivery(c, principal.user_id, delivery_id)
    )


@router.post("/inbox/{delivery_id}/read")
@operation_policy("relationship_scoped")
def read_delivery(
    delivery_id: UUID, principal: Principal = Depends(principal_from_request)
):
    return run(
        principal.user_id,
        lambda c: reading.delivery(c, principal.user_id, delivery_id, True),
    )


@router.get("/outbox")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def outbox(
    limit: int = PageSize,
    cursor: str | None = Query(None, max_length=200),
    q: str = Query("", max_length=255),
    priority: Priority | None = None,
    security_level_id: int | None = Query(None, gt=0),
    action_required: bool | None = None,
    sent_from: datetime | None = None,
    sent_before: datetime | None = None,
    action_state: Literal["outstanding", "late"] | None = None,
    recipient_kind: Literal["user", "role", "org_unit"] | None = None,
    recipient_id: int | None = Query(None, gt=0),
    principal: Principal = Depends(principal_from_request),
):
    return run(
        principal.user_id,
        lambda c: reading.outbox(
            c,
            principal.user_id,
            limit,
            cursor,
            q=q,
            priority=priority,
            security_level_id=security_level_id,
            action_required=action_required,
            sent_from=sent_from,
            sent_before=sent_before,
            action_state=action_state,
            recipient_kind=recipient_kind,
            recipient_id=recipient_id,
        ),
    )


@router.get("/outbox/{envelope_id}")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def get_sent(envelope_id: UUID, principal: Principal = Depends(principal_from_request)):
    return run(
        principal.user_id,
        lambda c: reading.outbox(c, principal.user_id, 1, identity=envelope_id),
    )


@router.get("/outbox/{envelope_id}/recipients")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def get_receipts(
    envelope_id: UUID,
    limit: int = PageSize,
    after: int = Query(0, ge=0),
    principal: Principal = Depends(principal_from_request),
):
    return run(
        principal.user_id,
        lambda c: reading.receipts(c, principal.user_id, envelope_id, limit, after),
    )


@router.get("/linked/{root_id}/{target_id}")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def get_linked(
    root_id: UUID,
    target_id: UUID,
    principal: Principal = Depends(principal_from_request),
):
    from .relationships import linked

    return run(
        principal.user_id, lambda c: linked(c, principal.user_id, root_id, target_id)
    )


@router.post("/outbox/{envelope_id}/amendments")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def amend_action(
    envelope_id: UUID,
    payload: Amendment,
    principal: Principal = Depends(principal_from_request),
):
    from .actions import amend

    return run(
        principal.user_id, lambda c: amend(c, principal.user_id, envelope_id, payload)
    )


@router.get("/{envelope_id}/amendments")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def amendment_history(
    envelope_id: UUID,
    limit: int = PageSize,
    after: int = Query(0, ge=0),
    root_id: UUID | None = None,
    principal: Principal = Depends(principal_from_request),
):
    from .actions import history

    return run(
        principal.user_id,
        lambda c: history(c, principal.user_id, envelope_id, limit, after, root_id),
    )


@router.get("/drafts")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def list_drafts(
    limit: int = PageSize,
    cursor: str | None = Query(None, max_length=200),
    deleted: bool = False,
    recipient_kind: Literal["user", "role", "org_unit"] | None = None,
    recipient_id: int | None = Query(None, gt=0),
    principal: Principal = Depends(principal_from_request),
):
    return run(
        principal.user_id,
        lambda c: drafts.listing(c, principal.user_id, limit, cursor, deleted, recipient_kind=recipient_kind, recipient_id=recipient_id),
    )


@router.post("/drafts")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def create_draft(
    payload: Draft, principal: Principal = Depends(principal_from_request)
):
    return run(principal.user_id, lambda c: drafts.save(c, principal.user_id, payload))


@router.get("/drafts/{draft_id}")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def get_draft(
    draft_id: UUID,
    deleted: bool = False,
    principal: Principal = Depends(principal_from_request),
):
    return run(
        principal.user_id,
        lambda c: drafts.get(c, principal.user_id, draft_id, deleted=deleted),
    )


@router.put("/drafts/{draft_id}")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def update_draft(
    draft_id: UUID,
    payload: Draft,
    if_match: int = Header(gt=0),
    principal: Principal = Depends(principal_from_request),
):
    return run(
        principal.user_id,
        lambda c: drafts.save(c, principal.user_id, payload, draft_id, if_match),
    )


@router.delete("/drafts/{draft_id}")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def discard_draft(
    draft_id: UUID,
    if_match: int = Header(gt=0),
    principal: Principal = Depends(principal_from_request),
):
    return run(
        principal.user_id,
        lambda c: drafts.discard(c, principal.user_id, draft_id, if_match),
    )


@router.post("/drafts/{draft_id}/restore")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def restore_draft(
    draft_id: UUID,
    if_match: int = Header(gt=0),
    principal: Principal = Depends(principal_from_request),
):
    return run(
        principal.user_id,
        lambda c: drafts.discard(c, principal.user_id, draft_id, if_match, True),
    )


@router.post("/drafts/{draft_id}/send")
@operation_policy("relationship_scoped", "messaging.user_messages.exchange")
def send_saved_draft(
    draft_id: UUID,
    payload: DraftSend,
    principal: Principal = Depends(principal_from_request),
):
    return run(
        principal.user_id,
        lambda c: drafts.send_draft(c, principal.user_id, draft_id, payload),
    )


@router.get('/recently-deleted/{mailbox}')
@operation_policy("relationship_scoped")
def recently_deleted(mailbox: Literal['inbox','outbox'], limit: int = PageSize,
                     cursor: str | None = Query(None,max_length=200),
                     principal: Principal = Depends(principal_from_request)):
    from .retention import deleted_listing
    return run(principal.user_id,lambda c:deleted_listing(c,principal.user_id,mailbox,limit,cursor))


@router.delete('/{mailbox}/{identity}')
@operation_policy("relationship_scoped")
def delete_entry(mailbox: Literal['inbox','outbox'], identity: UUID,
                 principal: Principal = Depends(principal_from_request)):
    from .retention import mailbox_change
    return run(principal.user_id,lambda c:mailbox_change(c,principal.user_id,mailbox,identity))


@router.post('/{mailbox}/{identity}/restore')
@operation_policy("relationship_scoped")
def restore_entry(mailbox: Literal['inbox','outbox'], identity: UUID,
                  principal: Principal = Depends(principal_from_request)):
    from .retention import mailbox_change
    return run(principal.user_id,lambda c:mailbox_change(c,principal.user_id,mailbox,identity,True))


@router.get('/{envelope_id}/capture-preview')
@operation_policy("relationship_scoped", "record.create")
def preview_capture(envelope_id: UUID, root_id: UUID | None = None,
                    principal: Principal = Depends(principal_from_request)):
    from .capture import preview
    return run(principal.user_id,lambda c:preview(c,principal.user_id,envelope_id,root_id))


@router.post('/{envelope_id}/capture',status_code=201)
@operation_policy("relationship_scoped", "record.create")
def initialize_capture(envelope_id: UUID, root_id: UUID | None = None,
                       principal: Principal = Depends(principal_from_request)):
    from .capture import initialize
    return run(principal.user_id,lambda c:initialize(c,principal.user_id,envelope_id,root_id))


@router.get('/recently-deleted/{mailbox}/{identity}')
@operation_policy("relationship_scoped")
def deleted_message(mailbox: Literal['inbox','outbox'], identity:UUID,
                    principal:Principal=Depends(principal_from_request)):
    from .retention import deleted_detail
    return run(principal.user_id,lambda c:deleted_detail(c,principal.user_id,mailbox,identity))
