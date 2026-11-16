"""Human mailboxes. Every page is bounded, fetched fresh, and scoped to one view.

No message cache is retained. Revision guards suppress abandoned results; app
navigation cancels pending API reads. Mutations refresh the current mailbox.
Recipient/resource controls use the app's shared remote relationship selector.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import re
from uuid import uuid4
from typing import Any

from nicegui import ui
from .api_client import ApiError
from .identity_presentation import render_user_avatar
from .resource_picker import resource_picker
from .i18n_catalogue import render_message, render_message_plain

MAILBOX_PAGE_SIZE = 25
PANE_HEADING_CLASSES = "mailbox-pane-title font-semibold"
RECIPIENT_PAGE_SIZE = 3


def mailbox_badge(label, tone="neutral"):
    return ui.badge(label, color=None).classes(f"mailbox-badge mailbox-badge--{tone}")


def action_tone(status):
    if status in ("late", "completed_late"):
        return "warning"
    if status == "completed":
        return "done"
    if status == "withdrawn":
        return "neutral"
    return "info"


MESSAGING_MESSAGE_KEYS = {
    "notice.action_amended": "messaging.notice.action_amended",
    "navigation.messages": "messaging.navigation.messages",
    "navigation.inbox": "messaging.navigation.inbox",
    "navigation.outbox": "messaging.navigation.outbox",
    "navigation.drafts": "messaging.navigation.drafts",
    "action.browse_recipients": "messaging.action.browse_recipients",
    "help.recipient_search": "messaging.help.recipient_search",
    "action.filters": "messaging.action.filters",
    "action.apply_filters": "messaging.action.apply_filters",
    "action.clear_filters": "messaging.action.clear_filters",
    "action.open_draft": "messaging.action.open_draft",
    "action.view_sent": "messaging.action.view_sent",
    "action.more": "messaging.action.more",
    "section.action_history": "messaging.section.action_history",
    "section.reading_pane": "messaging.section.reading_pane",
    "section.sent_messages": "messaging.section.sent_messages",
    "section.saved_drafts": "messaging.section.saved_drafts",
    "section.new_draft": "messaging.section.new_draft",
    "section.edit_draft": "messaging.section.edit_draft",
    "section.deleted_draft": "messaging.section.deleted_draft",
    "list.newest_first": "messaging.list.newest_first",
    "list.last_updated": "messaging.list.last_updated",
    "kind.system_notice": "messaging.kind.system_notice",
    "state.select_message": "messaging.state.select_message",
    "state.select_draft": "messaging.state.select_draft",
    "action.compose": "messaging.action.compose",
    "action.send": "messaging.action.send",
    "action.save_draft": "messaging.action.save_draft",
    "action.reply": "messaging.action.reply",
    "action.forward": "messaging.action.forward",
    "action.follow_up": "messaging.action.follow_up",
    "action.amend": "messaging.action.amend",
    "action.open_original": "messaging.action.open_original",
    "action.open_amended": "messaging.action.open_amended",
    "action.refresh": "messaging.action.refresh",
    "action.next": "messaging.action.next",
    "action.previous": "messaging.action.previous",
    "action.open": "messaging.action.open",
    "action.cancel": "messaging.action.cancel",
    "action.discard": "messaging.action.discard",
    "action.restore": "messaging.action.restore",
    "action.add": "messaging.action.add",
    "action.remove": "messaging.action.remove",
    "action.recently_deleted": "messaging.action.recently_deleted",
    "field.subject": "messaging.field.subject",
    "field.body": "messaging.field.body",
    "field.priority": "messaging.field.priority",
    "field.security": "messaging.field.security",
    "field.action_required": "messaging.field.action_required",
    "field.due_date": "messaging.field.due_date",
    "field.receipts": "messaging.field.receipts",
    "field.to": "messaging.field.to",
    "field.cc": "messaging.field.cc",
    "field.user": "messaging.field.user",
    "field.role": "messaging.field.role",
    "field.org_unit": "messaging.field.org_unit",
    "field.recipient": "messaging.field.recipient",
    "field.everyone": "messaging.field.everyone",
    "field.kind": "messaging.field.kind",
    "field.resource_kind": "messaging.field.resource_kind",
    "field.resource": "messaging.field.resource",
    "field.aggregation": "messaging.field.aggregation",
    "field.record": "messaging.field.record",
    "field.reason": "messaging.field.reason",
    "field.amendment_kind": "messaging.field.amendment_kind",
    "field.complete": "messaging.field.complete",
    "field.sent_at": "messaging.field.sent_at",
    "field.sender": "messaging.field.sender",
    "field.read": "messaging.field.read",
    "field.unread": "messaging.field.unread",
    "field.search": "messaging.field.search",
    "field.search_body": "messaging.field.search_body",
    "field.search_linked_content": "messaging.field.search_linked_content",
    "field.all": "messaging.field.all",
    "priority.normal": "messaging.priority.normal",
    "priority.high": "messaging.priority.high",
    "priority.very_high": "messaging.priority.very_high",
    "state.outstanding": "messaging.state.outstanding",
    "state.late": "messaging.state.late",
    "state.completed": "messaging.state.completed",
    "state.completed_late": "messaging.state.completed_late",
    "state.withdrawn": "messaging.state.withdrawn",
    "state.restricted": "messaging.state.restricted",
    "state.empty": "messaging.state.empty",
    "state.active": "messaging.state.active",
    "state.loading": "messaging.state.loading",
    "state.sent": "messaging.state.sent",
    "state.saved": "messaging.state.saved",
    "state.action_completed": "messaging.state.action_completed",
    "state.unavailable": "messaging.state.unavailable",
    "state.expiring": "messaging.state.expiring",
    "amendment.due_date_added": "messaging.amendment.due_date_added",
    "amendment.due_date_changed": "messaging.amendment.due_date_changed",
    "amendment.due_date_removed": "messaging.amendment.due_date_removed",
    "amendment.action_withdrawn": "messaging.amendment.action_withdrawn",
    "section.amendments": "messaging.section.amendments",
    "section.links": "messaging.section.links",
    "section.original": "messaging.section.original",
    "section.effective": "messaging.section.effective",
    "help.linked": "messaging.help.linked",
    "help.completion": "messaging.help.completion",
    "help.due": "messaging.help.due",
    "help.amend": "messaging.help.amend",
    "error.failed": "messaging.error.failed",
    "error.conflict": "messaging.error.conflict",
    "error.validation": "messaging.error.validation",
    "error.denied": "messaging.error.denied",
    "field.expiry": "messaging.field.expiry",
    "field.sent_from": "messaging.field.sent_from",
    "field.sent_before": "messaging.field.sent_before",
    "field.information": "messaging.field.information",
    "field.affected_recipients": "messaging.field.affected_recipients",
    "field.expanded_recipients": "messaging.field.expanded_recipients",
    "state.ready_validate": "messaging.state.ready_validate",
    "state.needs_attention": "messaging.state.needs_attention",
    "help.limits": "messaging.help.limits",
    "reason.message_recipient_exchange_required": "messaging.reason.message_recipient_exchange_required",
    "reason.message_recipient_clearance_required": "messaging.reason.message_recipient_clearance_required",
    "reason.message_resource_level_too_high": "messaging.reason.message_resource_level_too_high",
    "reason.message_resource_unavailable": "messaging.reason.message_resource_unavailable",
}


def text(key):
    return render_message(MESSAGING_MESSAGE_KEYS[key])


def plain_text(key):
    return render_message_plain(MESSAGING_MESSAGE_KEYS[key])


def choices(prefix, values):
    return {value: plain_text(prefix + value) for value in values}


def body_without_resources(value):
    marker = r'<span\s+data-wathiq-link="[^"]+">.*?</span>'
    value = re.sub(r'<p>\s*' + marker + r'\s*</p>', '', value or '', flags=re.S)
    return re.sub(marker, '', value, flags=re.S)


def body_with_resource_markers(value, resources):
    return body_without_resources(value) + ''.join(
        '<span data-wathiq-link="' + str(item['link_token']) + '"></span>' for item in resources)


async def messaging_workspace(
    *,
    api,
    container,
    mailbox,
    can_exchange,
    relationship_select,
    bind_relationship,
    open_resource,
    format_timestamp,
    active,
    format_date=str,
    on_read=None,
    capture_record=None,
    browse_recipients=None,
    inspect_resource=None,
    open_disposition_task=None,
    open_disposition_job=None,
    open_disposition_eligibility=None,
    mailbox_position=None,
    initial_item=None,
    navigate_mailbox=None,
    compose_host=None,
    linked_content_enabled=True,
    page_size=MAILBOX_PAGE_SIZE,
):
    position_state = mailbox_position if mailbox_position is not None else {}
    view = {
        "revision": 0,
        "compose_revision": 0,
        "detail_revision": 0,
        "cursor": None,
        "previous": [],
        "next": None,
        "criteria": {},
        "loading": False,
        "deleted": False,
        **position_state,
    }
    if position_state.get("page_size", MAILBOX_PAGE_SIZE) != page_size:
        view.update(cursor=None, previous=[])
    if initial_item is not None:
        # Save and send link to active objects. Keep the destination criteria
        # and reuse its cursor when it was last viewed as an active mailbox.
        if view["deleted"]:
            view.update(deleted=False, cursor=None, previous=[])
    restored_criteria = dict(view["criteria"])
    if not linked_content_enabled and "linked_q" in restored_criteria:
        restored_criteria.pop("linked_q")
        view.update(criteria=restored_criteria, cursor=None, previous=[])
    filter_labels_by_key = {}

    read_indicators = {}
    message_rows = {}
    selected_message = None
    base = "/api/v1/messages"

    def current(revision):
        return active() and revision == view["revision"]

    def warn(error):
        if not active():
            return
        with container:
            if isinstance(error.detail, dict) and error.detail.get("message_key"):
                message = render_message(error.detail["message_key"], **error.detail.get("parameters", {}))
            else:
                key = {
                    403: "error.denied", 404: "error.denied",
                    409: "error.conflict", 422: "error.validation",
                }.get(error.status_code, "error.failed")
                message = text(key)
            ui.notify(message, color="negative", close_button=True)

    async def request(method, path, **kwargs):
        return await api.request(method, base + path, **kwargs)

    def state_label(value):
        return text("state." + value) if value else "—"

    def action_summary(required, due, zone=None):
        return (text("field.action_required") if required else "—") + (
            " · " + str(due) + (" · " + zone if zone else "") if due else ""
        )

    def caption(key, value):
        control = filters[key]
        options = getattr(control, "options", None)
        if key in ("sent_from", "sent_before"):
            value = value[:10]
        if isinstance(options, dict):
            value = options.get(value, plain_text("state.unavailable"))
        return value

    def update_clear_filters():
        clear_filters_button.set_enabled(
            bool(view["criteria"]) or any(control.value not in (None, "") for control in filters.values())
        )

    def render_applied_filters():
        update_clear_filters()
        applied.clear()
        if view["deleted"] and mailbox != "drafts":
            applied.set_visibility(False)
            return
        with applied:
            criteria = view["criteria"]
            for key in filters:
                if key == "recipient":
                    if "recipient_id" not in criteria:
                        continue
                    value = criteria["recipient_id"] * 3 + filter_kinds.index(criteria["recipient_kind"])
                elif key in criteria:
                    value = criteria[key]
                else:
                    continue
                ui.label(
                    plain_text(filter_labels_by_key[key]) + " · " + caption(key, value)
                ).classes("px-2 py-1 rounded-md bg-blue-50 text-blue-900 text-xs break-all")
        applied.set_visibility(bool(view["criteria"]))

    def saved_option(key):
        value = restored_criteria.get(key)
        return ({value: plain_text("state.unavailable")} if value is not None else {}, value)

    def expiry(item):
        if item.get("expires_at"):
            ui.label(
                text("field.expiry") + ": " + format_timestamp(item["expires_at"])
            ).classes("text-xs text-slate-500")

    def letter_disclosure(label):
        section = ui.expansion(label).props(
            'dense hide-expand-icon header-class="px-0 mailbox-disclosure-title"'
        ).classes(
            "mailbox-letter-disclosure w-full border-t border-slate-200"
        )
        with section.add_slot("header"), ui.column().classes("w-full gap-1 py-2") as header:
            with ui.row().classes("items-center gap-0"):
                ui.icon("arrow_right", size="xs").bind_name_from(
                    section, "value", lambda opened: "arrow_drop_down" if opened else "arrow_right",
                ).props("aria-hidden=true").classes("mailbox-disclosure-marker")
                ui.label(label).classes("text-sm font-semibold")
        return section, header

    def render_recipients(message, current):
        def recipient_pager(label, icon, forward):
            button = ui.button(icon=icon, on_click=lambda: page_recipients(forward)).props(
                "outline dense " + "aria-label=" + json.dumps(label, ensure_ascii=False)
            ).classes("mailbox-page-button").tooltip(label)
            button.disable()
            return button

        summary = message["recipient_summary"]
        section, header = letter_disclosure(render_message("messaging.outbox.recipients"))
        section.classes("mailbox-receipts")
        with header:
            with ui.row().classes("mailbox-receipt-counts items-center gap-x-3 gap-y-1 text-xs font-semibold text-slate-600"):
                ui.label(render_message("messaging.outbox.delivered_count", count=summary["delivered"]))
                if "read" in summary:
                    ui.label(render_message("messaging.outbox.read_count", count=summary["read"]))
                if "action_total" in summary:
                    ui.label(render_message(
                        "messaging.outbox.completed_count", completed=summary["completed"], total=summary["action_total"],
                    ))
        with section, ui.column().classes("w-full gap-0"):
            notice = ui.label().props("role=status").classes("text-sm empty:hidden py-1")
            rows_host = ui.element("ul").classes("w-full list-none m-0 p-0")
            with ui.row().classes("w-full items-center justify-between gap-2 pt-2") as pager:
                range_label = ui.label().classes("text-xs text-slate-600").props("role=status")
                with ui.row().classes("items-center gap-2"):
                    previous = recipient_pager(
                        render_message_plain("messaging.outbox.previous_recipients"), "chevron_left", False,
                    )
                    following = recipient_pager(
                        render_message_plain("messaging.outbox.next_recipients"), "chevron_right", True,
                    )
                pager.set_visibility(summary["delivered"] > RECIPIENT_PAGE_SIZE)
            cursor = 0
            history = []
            next_cursor = None
            loaded = loading = False

            async def open_completion_reply(delivery_id):
                if current():
                    await open_linked(delivery_id, "inbox", None, completion_reply=True)

            async def load_recipients(after, previous_cursors):
                nonlocal cursor, history, next_cursor, loaded, loading
                if loading or not current():
                    return
                loading = True
                previous.disable()
                following.disable()
                notice.text = text("state.loading")
                try:
                    page = await request(
                        "GET", f'/outbox/{message["envelope_id"]}/recipients',
                        params={"limit": RECIPIENT_PAGE_SIZE, "after": after},
                    )
                    if not current():
                        return
                    items = page["items"]
                    cursor, history = after, previous_cursors
                    next_cursor = page["next_cursor"]
                    loaded = True
                    notice.text = "" if items else text("state.empty")
                    rows_host.clear()
                    with rows_host:
                        for row in items:
                            with ui.element("li").classes("border-t border-slate-200 py-2"), ui.column().classes("w-full gap-1"):
                                ui.label(row["recipient_name"]).classes("mailbox-recipient-name font-semibold break-words")
                                with ui.row().classes("mailbox-recipient-details items-center gap-2 text-xs text-slate-600"):
                                    mailbox_badge(text("field." + row["recipient_type"]))
                                    ui.label(render_message(
                                        "messaging.outbox.receipt_delivered_at", time=format_timestamp(row["delivered_at"]),
                                    )).classes("mailbox-recipient-delivery")
                                    if "read_at" in row:
                                        ui.label(render_message(
                                            "messaging.outbox.receipt_read_at", time=format_timestamp(row["read_at"]),
                                        ) if row["read_at"] else text("field.unread"))
                                    if action_status := row.get("action_status"):
                                        tone = "done" if action_status == "completed_late" else action_tone(action_status)
                                        mailbox_badge(state_label(action_status), tone)
                                if delivery_id := row.get("completion_reply_delivery_id"):
                                    ui.button(
                                        render_message("messaging.outbox.open_completion_reply"), icon="reply",
                                        on_click=lambda _, identity=delivery_id: open_completion_reply(identity),
                                    ).props("flat dense no-caps").classes("mailbox-text-link")
                    if items:
                        first = len(history) * RECIPIENT_PAGE_SIZE + 1
                        range_label.text = render_message(
                            "messaging.outbox.recipient_range", first=first, last=first + len(items) - 1,
                            total=summary["delivered"],
                        )
                except ApiError as error:
                    if current():
                        notice.text = text("error.failed")
                        warn(error)
                finally:
                    loading = False
                    if current():
                        previous.set_enabled(bool(history))
                        following.set_enabled(next_cursor is not None)

            async def page_recipients(forward):
                if forward and next_cursor is not None:
                    await load_recipients(next_cursor, [*history, cursor])
                elif not forward and history:
                    await load_recipients(history[-1], history[:-1])

            async def open_recipients():
                if not loaded:
                    await load_recipients(0, [])

            section.on("show", open_recipients)

    if compose_host is not None and can_exchange:
        with compose_host:
            ui.button(text("action.compose"), icon="edit", on_click=lambda: compose()).props("unelevated no-caps")

    with container:
        with ui.column().classes("messaging-workspace w-full gap-3 p-3").props(f"data-mailbox={mailbox}"):
            with ui.row().classes("w-full items-center justify-between gap-2"):
                with ui.row().classes("items-center gap-2 grow min-w-0"):
                    if can_exchange and compose_host is None:
                        ui.button(text("action.compose"), icon="edit", on_click=lambda: compose()).props("unelevated no-caps")
                    active_tools = ui.row().classes("items-center gap-2 grow min-w-0")
                with ui.row().classes("items-center gap-2"):
                    deleted = ui.switch(
                        text("action.recently_deleted")
                        if mailbox == "drafts"
                        else render_message("messaging.retention.recently_deleted"),
                        value=view["deleted"],
                    ).mark("mailbox-recently-deleted")
                    deleted.on_value_change(lambda event: change_deleted_view(event.value))
            with active_tools:
                subject_host = ui.row().classes("items-center gap-2 min-w-0")
                filters_toggle = ui.button(text("action.filters"), icon="tune", on_click=lambda: toggle_filters()).props(
                    'outline no-caps aria-expanded="false" aria-controls="mailbox-filters"'
                ).mark("mailbox-toggle-filters")
                clear_filters_button = ui.button(
                    text("action.clear_filters"), icon="filter_alt_off", on_click=lambda: clear_filters()
                ).props("flat no-caps").classes("mailbox-clear-filters").mark("mailbox-clear-filters")
                clear_filters_button.disable()
            filters_host = ui.column().classes("w-full gap-2 border border-slate-200 rounded-lg p-3").props('id="mailbox-filters"')
            filters_host.set_visibility(False)
            filters = {}
            with subject_host:
                filters["q"] = ui.input(
                    text("field.search"), value=restored_criteria.get("q", "")
                ).props("outlined dense clearable maxlength=255").classes("min-w-0").on(
                    "keydown.enter", lambda: apply_filters(subject_only=True)
                )
                ui.button(text("field.search"), icon="search", on_click=lambda: apply_filters(subject_only=True)).props(
                    "flat no-caps"
                ).mark("mailbox-search-subject")
                filter_labels_by_key["q"] = "field.search"
            with filters_host, ui.grid(columns="repeat(auto-fit, minmax(min(100%, 16rem), 1fr))").classes("w-full gap-3"):
                fields = {"body_q": "field.search_body"}
                if linked_content_enabled:
                    fields["linked_q"] = "field.search_linked_content"
                for key, label in fields.items():
                    filters[key] = ui.input(text(label), value=restored_criteria.get(key, "")).props(
                        "outlined dense clearable maxlength=255"
                    ).on("keydown.enter", lambda: apply_filters())
                    filter_labels_by_key[key] = label
            with filters_host, ui.row().classes("w-full items-start gap-3"):
                if mailbox == "inbox" and can_exchange:
                    with ui.column().classes("w-full max-w-xs gap-1"):
                        options, value = saved_option("sender_user_id")
                        sender = relationship_select(
                            text("field.sender"), options, value=value, remote=True,
                        ).props("dense")
                        sender.classes("w-full").mark("mailbox-sender")
                        async def sender_page(query):
                            if len(query.strip()) < 2:
                                return {"items": []}
                            return await request("GET", "/recipients/user", params={"q": query.strip(), "limit": 25, "purpose": "filter"})
                        async def selected_sender(identity):
                            page = await request("GET", "/recipients/user", params={"target_id": identity, "limit": 1, "purpose": "filter"})
                            return next(iter(page["items"]), {"id": identity, "name": plain_text("state.unavailable")})
                        bind_relationship(
                            sender, "users", ("name",), ("name",), page_loader=sender_page,
                            selected_loader=selected_sender, active=active,
                            on_options_resolved=lambda _: render_applied_filters(),
                        )
                        filters["sender_user_id"] = sender
                        filter_labels_by_key["sender_user_id"] = "field.sender"
                        if browse_recipients:
                            async def browse_sender():
                                async def choose(node):
                                    if not active() or node["type"] != "user":
                                        return False
                                    row = await selected_sender(node["id"])
                                    if not active():
                                        return False
                                    sender.options = {row["id"]: row["name"]}
                                    sender.value = row["id"]
                                    sender.update()
                                    return True
                                await browse_recipients(selection_mode="user", on_selection=choose)
                            ui.button(text("action.browse_recipients"), icon="account_tree", on_click=browse_sender).props("flat no-caps").mark("mailbox-browse-sender")
                if mailbox != "drafts":
                    priority = (
                        ui.select(
                            {
                                "": text("field.all"),
                                **choices("priority.", ("normal", "high", "very_high")),
                            },
                            value=restored_criteria.get("priority", ""),
                            label=text("field.priority"),
                        )
                        .props("outlined dense")
                        .classes("min-w-40")
                    )
                    filters["priority"] = priority
                    filter_labels_by_key["priority"] = "field.priority"
                if mailbox == "inbox":
                    read = ui.select(
                        {
                            "": text("field.all"),
                            "true": text("field.read"),
                            "false": text("field.unread"),
                        },
                        value=restored_criteria.get("is_read", ""),
                        label=text("field.read"),
                    ).props("outlined dense").classes("min-w-24")
                    filters["is_read"] = read
                    filter_labels_by_key["is_read"] = "field.read"
                if mailbox in ("inbox", "outbox"):
                    for key in ("sent_from", "sent_before"):
                        filter_labels_by_key[key] = "field." + key
                        filters[key] = ui.input(
                            text("field." + key), value=restored_criteria.get(key, "")[:10]
                        ).props("outlined dense type=date")
                if mailbox == "outbox":
                    filters["action_required"] = ui.select(
                        {
                            "": text("field.all"),
                            "true": text("field.action_required"),
                            "false": text("field.information"),
                        },
                        value=restored_criteria.get("action_required", ""),
                        label=text("field.action_required"),
                    ).props("outlined dense")
                    filters["action_state"] = ui.select(
                        {
                            "": text("field.all"),
                            **choices("state.", ("outstanding", "late")),
                        },
                        value=restored_criteria.get("action_state", ""),
                        label=text("section.effective"),
                    ).props("outlined dense")
                    options, value = saved_option("security_level_id")
                    security = relationship_select(text("field.security"), options, value=value).props("dense")
                    security.classes("max-w-xs")
                    bind_relationship(
                        security, "security-levels", ("name",), ("name",), active=active,
                        on_options_resolved=lambda _: render_applied_filters(),
                    )
                    filters["security_level_id"] = security
                    filter_labels_by_key.update(
                        action_required="field.action_required", action_state="section.effective",
                        security_level_id="field.security",
                    )
                if mailbox in ("inbox", "outbox", "drafts") and can_exchange:
                    filter_kinds = ("user", "role", "org_unit")
                    filter_labels = [plain_text("field." + kind) for kind in filter_kinds]
                    with ui.column().classes("w-full max-w-xs gap-1") as recipient_group:
                        value = (
                            restored_criteria["recipient_id"] * 3 + filter_kinds.index(restored_criteria["recipient_kind"])
                            if "recipient_id" in restored_criteria else None
                        )
                        options = {value: plain_text("state.unavailable")} if value is not None else {}
                        recipient = relationship_select(
                            text("field.recipient"), options, value=value, remote=True,
                        ).props("dense")
                        filters["recipient"] = recipient
                        filter_labels_by_key["recipient"] = "field.recipient"
                        recipient.classes("w-full").mark("mailbox-recipient")

                    def filter_option(row, index):
                        return dict(row, id=row["id"] * 3 + index,
                                    name=filter_labels[index] + " · " + row["name"])

                    async def filter_recipients(query):
                        if len(query.strip()) < 2:
                            return {"items": []}
                        pages = await asyncio.gather(*(request("GET", "/recipients/" + kind,
                            params={"q": query.strip(), "limit": 25, "purpose": "filter"}) for kind in filter_kinds))
                        return {"items": [filter_option(row, index)
                            for index, page in enumerate(pages) for row in page["items"]]}

                    async def selected_filter_recipient(identity):
                        target, index = divmod(int(identity), 3)
                        page = await request("GET", "/recipients/" + filter_kinds[index],
                            params={"target_id": target, "limit": 1, "purpose": "filter"})
                        row = next(iter(page["items"]), {"id": target, "name": plain_text("state.unavailable")})
                        return filter_option(row, index)

                    bind_relationship(recipient, "users", ("name",), ("name",),
                        page_loader=filter_recipients, selected_loader=selected_filter_recipient,
                        active=active, on_options_resolved=lambda _: render_applied_filters())
                    if browse_recipients:
                        async def browse_filter():
                            async def choose(node):
                                if not active():
                                    return False
                                index = filter_kinds.index(node["type"])
                                identity = node["id"] * 3 + index
                                row = await selected_filter_recipient(identity)
                                if not active():
                                    return False
                                recipient.options = {identity: row["name"]}
                                recipient.value = identity
                                recipient.update()
                                return True
                            await browse_recipients(selection_mode="all", on_selection=choose)
                        with recipient_group:
                            ui.button(text("action.browse_recipients"), icon="account_tree",
                                      on_click=browse_filter).props("flat no-caps").mark("mailbox-browse-recipient")
            with filters_host, ui.row().classes("w-full justify-end"):
                ui.button(
                    text("action.apply_filters"), icon="filter_alt", on_click=lambda: apply_filters()
                ).props("unelevated no-caps").mark("mailbox-apply-filters")
            applied = ui.row().classes("w-full items-center gap-2")
            with ui.page_sticky(position="bottom-right", x_offset=16, y_offset=16).classes("z-50") as feedback:
                feedback_content = ui.row().classes(
                    "mailbox-send-feedback max-w-full items-center gap-2 rounded-lg border border-slate-200 bg-white p-2 shadow-md"
                ).style("max-width: calc(100vw - 32px)")
            feedback.set_visibility(False)
            with ui.grid().classes("mailbox-columns w-full min-w-0 grid-cols-1 gap-3 items-start"):
                with ui.column().classes("mailbox-list w-full min-w-0 gap-0 rounded-xl border border-slate-200 overflow-hidden bg-white"):
                    with ui.row().classes(
                        "w-full items-center justify-between gap-2 bg-blue-50 border-b border-blue-100 px-3 py-2"
                    ):
                        title_key = {"inbox": "navigation.messages", "outbox": "section.sent_messages",
                                     "drafts": "section.saved_drafts"}[mailbox]
                        ui.label(text(title_key)).classes(PANE_HEADING_CLASSES)
                        with ui.row().classes("items-center gap-2"):
                            sort_label = ui.label(text(
                                "list.last_updated" if mailbox == "drafts" else "list.newest_first"
                            )).classes("text-xs text-slate-600")
                            refresh_label = plain_text("action.refresh")
                            ui.button(icon="refresh", on_click=lambda: refresh_list()).props(
                                "flat dense round aria-label=" + json.dumps(refresh_label, ensure_ascii=False)
                            ).tooltip(refresh_label).mark("mailbox-refresh")
                    progress = ui.label().props("role=status").classes(
                        "w-full px-3 py-2 text-sm text-slate-600 empty:hidden"
                    )
                    content = ui.column().classes("w-full min-w-0 gap-0")
                    with ui.row().classes(
                        "mailbox-pagination w-full items-center justify-between gap-2 border-t border-slate-200 px-3 py-2"
                    ):
                        page_range = ui.label().classes("text-xs text-slate-600").props("role=status dir=ltr")
                        with ui.row().classes("items-center gap-2"):
                            def pager_button(key, icon, forward):
                                label = plain_text(key)
                                return ui.button(icon=icon, on_click=lambda: page(forward)).props(
                                    "outline dense " + "aria-label=" + json.dumps(label, ensure_ascii=False)
                                ).classes("mailbox-page-button").tooltip(label)
                            previous = pager_button("action.previous", "chevron_left", False).mark("mailbox-previous")
                            next_button = pager_button("action.next", "chevron_right", True).mark("mailbox-next")
                            previous.disable()
                            next_button.disable()
                with ui.column().classes("w-full min-w-0 gap-3"):
                    detail_status = ui.label().props("role=status").classes("text-sm empty:hidden")
                    with ui.card().classes(
                        "w-full min-h-48 items-center justify-center gap-2 border border-slate-200 shadow-none text-slate-600"
                    ) as placeholder:
                        ui.icon("drafts" if mailbox == "drafts" else "mail_outline", size="sm", color="primary")
                        ui.label(text("state.select_draft" if mailbox == "drafts" else "state.select_message")).classes("font-semibold text-center")
                    detail = ui.column().classes("w-full min-w-0 gap-3")
                    detail.set_visibility(False)

    def toggle_filters(expanded=None):
        visible = (mailbox == "drafts" or not view["deleted"]) and (
            not filters_host.visible if expanded is None else expanded
        )
        filters_host.set_visibility(visible)
        filters_toggle.props(f'aria-expanded="{str(visible).lower()}"')

    def clear_detail():
        view["detail_revision"] += 1
        select_row(None)
        detail.clear()
        detail.set_visibility(False)
        detail_status.text = ""
        placeholder.set_visibility(True)

    async def change_deleted_view(value):
        view["deleted"] = value
        clear_detail()
        toggle_filters(False)
        active_tools.set_visibility(not value or mailbox == "drafts")
        render_applied_filters()
        await load(reset=True)

    def select_row(identity):
        nonlocal selected_message
        selected_message = str(identity) if identity is not None else None
        for row_id, row in message_rows.items():
            if row_id == selected_message:
                row.props("aria-current=true")
            else:
                row.props(remove="aria-current")

    async def clear_filters():
        reload_list = bool(view["criteria"]) or view["loading"]
        for key, control in filters.items():
            control.value = "" if key in (
                "q", "body_q", "linked_q", "priority", "is_read", "sent_from", "sent_before", "action_required", "action_state"
            ) else None
        if reload_list:
            await load(reset=True, criteria={})

    def show_success(key, folder=None, identity=None):
        if not (navigate_mailbox and folder and identity):
            feedback.set_visibility(False)
            ui.notify(text(key), color="positive")
            return

        def dismiss_feedback():
            feedback.set_visibility(False)

        async def open_destination():
            dismiss_feedback()
            await navigate_mailbox(folder, identity)

        feedback_content.clear()
        with feedback_content:
            ui.label(text(key)).classes("text-positive").props("role=status")
            ui.button(
                text("action.open_draft" if folder == "drafts" else "action.view_sent"),
                icon="open_in_new",
                on_click=open_destination,
            ).props("flat dense no-caps")
            close_label = render_message_plain("messaging.live.close")
            ui.button(icon="close", on_click=dismiss_feedback).props(
                "flat dense round aria-label=" + json.dumps(close_label, ensure_ascii=False)
            ).tooltip(close_label)
        feedback.set_visibility(True)

    async def page(forward):
        if view["loading"] or (forward and not view["next"]) or (not forward and not view["previous"]):
            return
        if forward:
            await load(position=(view["next"], [*view["previous"], view["cursor"]]))
        else:
            await load(position=(view["previous"][-1], view["previous"][:-1]))

    async def refresh_list():
        if active() and not view["loading"]:
            await load()

    async def apply_filters(*, subject_only=False):
        if subject_only:
            criteria = dict(view["criteria"])
            if subject := (filters["q"].value or "").strip():
                criteria["q"] = subject
            else:
                criteria.pop("q", None)
            await load(reset=True, criteria=criteria)
            return
        criteria = {
            key: control.value for key, control in filters.items()
            if key != "recipient" and control.value not in (None, "")
        }
        for key in ("q", "body_q", "linked_q"):
            if key in criteria:
                if value := criteria[key].strip():
                    criteria[key] = value
                else:
                    criteria.pop(key)
        for key in ("sent_from", "sent_before"):
            if key in criteria:
                criteria[key] += "T00:00:00Z"
        if mailbox in ("inbox", "outbox", "drafts") and can_exchange and recipient.value:
            target, index = divmod(int(recipient.value), 3)
            criteria.update(recipient_kind=filter_kinds[index], recipient_id=target)
        await load(reset=True, criteria=criteria)

    async def load(reset=False, *, position=None, criteria=None):
        view["revision"] += 1
        revision = view["revision"]
        view["loading"] = True
        cursor, history = (None, []) if reset else position or (view["cursor"], view["previous"])
        submitting = criteria is not None
        criteria = view["criteria"] if criteria is None else criteria
        progress.text = text("state.loading")
        params = {"limit": page_size}
        if cursor:
            params["cursor"] = cursor
        if mailbox == "drafts":
            params["deleted"] = view["deleted"]
        if mailbox == "drafts" or not view["deleted"]:
            params.update(criteria)
        try:
            result = await request(
                "GET",
                (
                    "/recently-deleted/"
                    if view["deleted"] and mailbox != "drafts"
                    else "/"
                )
                + mailbox,
                params=params,
            )
        except asyncio.CancelledError:
            return
        except ApiError as error:
            if current(revision):
                progress.text = text("error.failed")
                warn(error)
            return
        finally:
            if view["revision"] == revision:
                view["loading"] = False
        if not current(revision):
            return
        view.update(cursor=cursor, previous=history, criteria=criteria)
        position_state.update(cursor=cursor, previous=history, criteria=criteria, deleted=view["deleted"], page_size=page_size)
        if submitting:
            render_applied_filters()
        progress.text = ""
        content.clear()
        read_indicators.clear()
        message_rows.clear()
        items = result["items"]
        sort_label.set_visibility(bool(items))
        with content:
            if not items:
                ui.label(text("state.empty")).classes("p-5 text-slate-500")
            for item in items:
                identity = str(item["id"])
                restricted = item.get("availability") == "restricted"
                with ui.row().classes(
                    "mailbox-message-row w-full items-start no-wrap gap-2 py-2.5 px-3"
                ) as message_row:
                    if not restricted or mailbox != "drafts":
                        message_rows[identity] = message_row
                        if identity == selected_message:
                            message_row.props("aria-current=true")
                        message_row.props("tabindex=0 role=button").classes("cursor-pointer")
                        message_row.mark("message-row-" + identity)
                        message_row.on("click", lambda _, row=item: open_item(row))
                        message_row.on("keydown.enter", lambda _, row=item: open_item(row))
                        message_row.on("keydown.space.prevent", lambda _, row=item: open_item(row))
                    ui.element("span").classes("mailbox-row-dot").props("aria-hidden=true")
                    with ui.column().classes("grow min-w-0 gap-1"):
                        with ui.row().classes("w-full min-w-0 gap-2 items-center"):
                            ui.label(
                                text("state.restricted") if restricted else item.get("subject") or text("action.compose")
                            ).classes("mailbox-row-subject break-words min-w-0")
                            if not restricted and "is_read" in item:
                                unread = not item["is_read"]
                                message_row.props(f"data-unread={str(unread).lower()}")
                                read_indicators[identity] = ui.label(
                                    text("field.unread" if unread else "field.read")
                                ).classes("sr-only")
                        with ui.row().classes("w-full items-baseline justify-between gap-x-2 gap-y-1 text-xs text-slate-600"):
                            names = "" if restricted else (
                                "; ".join(item.get("recipient_names", [])) if mailbox == "outbox" else item.get("sender_name", "")
                            )
                            if names:
                                ui.label(names).classes("grow min-w-0 truncate").tooltip(names)
                            ui.label(format_timestamp(item.get("sent_at") or item.get("date_updated"))).classes("shrink-0")
                        if restricted:
                            ui.label(text("error.denied")).classes("text-xs text-slate-600")
                            continue
                        with ui.row().classes("w-full min-w-0 gap-x-2 gap-y-1 items-center text-xs empty:hidden"):
                            if item.get("recipient_type") == "cc":
                                mailbox_badge(text("field.cc"))
                            if item.get("priority") not in (None, "normal"):
                                mailbox_badge(text("priority." + item["priority"]), "warning")
                            if mailbox in ("inbox", "outbox") and (security_name := item.get("security_level_name")):
                                security_code = item.get("security_level_code")
                                security_level = f"{security_code} · {security_name}" if security_code else security_name
                                mailbox_badge(security_level).classes("mailbox-security-level")
                            if item.get("recipient_type") != "cc":
                                action = item.get("effective_action", {})
                                if action_status := item.get("action_status"):
                                    mailbox_badge(state_label(action_status), action_tone(action_status))
                                elif action.get("action_required"):
                                    mailbox_badge(text("field.action_required"), "info")
                                if due := action.get("due_date"):
                                    ui.label(text("field.due_date") + ": " + due).classes("text-slate-600")
                            if item.get("has_unavailable_resources"):
                                ui.icon("link_off").tooltip(
                                    text("state.unavailable")
                                )
                            if item.get("amendment_sequence"):
                                mailbox_badge(text("notice.action_amended"), "info")
                            if item.get("is_test"):
                                mailbox_badge(render_message("messaging.test.label"), "warning")
                            if item.get("expiry_warning"):
                                mailbox_badge(text("state.expiring"), "warning")
                            if mailbox == "drafts":
                                needs_attention = item.get("needs_attention")
                                mailbox_badge(
                                    text("state.needs_attention" if needs_attention else "state.ready_validate"),
                                    "warning" if needs_attention else "neutral",
                                )
        if items:
            first = len(history) * page_size + 1
            last = first + len(items) - 1
            page_range.text = render_message("messaging.list.page_range", first=first, last=last)
        else:
            page_range.text = ""
        view["next"] = result.get("next_cursor")
        previous.set_enabled(bool(view["previous"]))
        next_button.set_enabled(bool(result.get("has_more")))

    async def open_item(item, *, focus=False):
        if mailbox == "drafts":
            view["detail_revision"] += 1
            opening_revision = view["detail_revision"]
            detail_status.text = text("state.loading")
            try:
                draft = await request(
                    "GET", "/drafts/" + item["id"], params={"deleted": view["deleted"]}
                )
            except ApiError as error:
                if active() and opening_revision == view["detail_revision"]:
                    detail_status.text = text("error.failed")
                    warn(error)
                return
            if active() and opening_revision == view["detail_revision"]:
                select_row(item["id"])
                await compose(draft=draft, focus=focus)
        else:
            await show_message(item["id"], mailbox, focus=focus)

    async def open_linked(identity, source, root, overlay=None, *, completion_reply=False, mark_read=True):
        if overlay is None:
            dialog = ui.dialog().props("persistent")
            overlay = dict(revision=0, closed=False, owner_revision=view["detail_revision"], history=[])
            def close_linked():
                overlay["closed"] = True
                overlay["revision"] += 1
                dialog.close()
            async def back_linked():
                if len(overlay["history"]) > 1:
                    overlay["history"].pop()
                    previous_identity, previous_source, previous_root, previous_mark_read = overlay["history"][-1]
                    overlay["back"].set_visibility(len(overlay["history"]) > 1)
                    await show_message(
                        previous_identity, previous_source, root=previous_root, overlay=overlay,
                        mark_read=previous_mark_read,
                    )
            with dialog, ui.card().classes("gap-3").style("width: 672px; max-width: calc(100vw - 32px)"):
                with ui.row().classes("w-full items-center justify-between gap-2"):
                    ui.label(
                        text("state.action_completed") if completion_reply else render_message("messaging.linked.title")
                    ).classes("text-xl font-semibold")
                    ui.button(render_message("messaging.live.close"), icon="close", on_click=close_linked).props("flat no-caps").mark("linked-message-close")
                overlay["back"] = ui.button(text("action.previous"), icon="arrow_back", on_click=back_linked).props("flat no-caps").mark("linked-message-back")
                overlay["status"] = ui.label().props("role=status")
                overlay["host"] = ui.column().classes("w-full min-w-0 gap-3")
            dialog.open()
        overlay["history"].append((identity, source, root, mark_read))
        overlay["back"].set_visibility(len(overlay["history"]) > 1)
        await show_message(identity, source, root=root, overlay=overlay, mark_read=mark_read)

    async def show_message(identity, source, *, root=None, overlay=None, mark_read=True, focus=False):
        if root and overlay is None:
            await open_linked(identity, source, root)
            return
        detail_state = overlay if overlay is not None else view
        revision_key = "revision" if overlay is not None else "detail_revision"
        detail_state[revision_key] += 1
        revision = detail_state[revision_key]
        def detail_current(revision):
            return active() and revision == detail_state[revision_key] and (overlay is None or
                (not overlay["closed"] and overlay["owner_revision"] == view["detail_revision"]))

        host = overlay["host"] if overlay is not None else detail
        status = overlay["status"] if overlay is not None else detail_status
        status.text = text("state.loading")
        try:
            if root:
                message = await request("GET", f"/linked/{root}/{identity}")
            elif overlay is None and view["deleted"]:
                message = await request("GET", f"/recently-deleted/{source}/{identity}")
            elif source == "inbox" and mark_read:
                message = await request("POST", f"/inbox/{identity}/read")
                if on_read is not None:
                    await on_read()
            else:
                message = await request("GET", f"/{source}/{identity}")
        except asyncio.CancelledError:
            return
        except ApiError as error:
            if detail_current(revision):
                status.text = text("error.failed")
                warn(error)
            return
        if not detail_current(revision):
            return
        status.text = ""
        if overlay is None:
            select_row(identity)
            placeholder.set_visibility(False)
            if (
                source == "inbox" and mark_read and not view["deleted"]
                and message["availability"] == "available" and str(identity) in read_indicators
            ):
                read_indicators[str(identity)].set_text(text("field.read"))
                message_rows[str(identity)].props("data-unread=false")
        host.clear()
        host.set_visibility(True)
        if message["availability"] != "available":
            with host, ui.card().classes("w-full border border-slate-200 shadow-none"):
                ui.label(text("state.restricted")).classes("font-semibold")
                ui.label(text("error.denied")).classes("text-sm")
            return
        eligible = (
            overlay is None
            and not root
            and not view["deleted"]
            and can_exchange
            and not message["is_test"]
            and message["message_kind"] != "action_amendment_notice"
            and datetime.fromisoformat(message["expires_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc)
        )
        can_capture = capture_record and message["message_kind"] == "user_message"
        can_delete = overlay is None and not view["deleted"] and message.get("can_delete")
        can_restore = overlay is None and view["deleted"]

        async def change_mailbox():
            if not detail_current(revision):
                return
            restoring = view["deleted"]
            retention_button.disable()
            try:
                await request(
                    "POST" if restoring else "DELETE",
                    f"/{source}/{identity}" + ("/restore" if restoring else ""),
                )
            except ApiError as error:
                if detail_current(revision):
                    warn(error)
                return
            finally:
                if detail_current(revision):
                    retention_button.enable()
            if detail_current(revision):
                clear_detail()
                if on_read is not None:
                    await asyncio.gather(load(reset=True), on_read())
                else:
                    await load(reset=True)

        async def capture_current():
            if not detail_current(revision) or not capture_button.enabled:
                return
            capture_button.disable()
            capture_button.props("loading")
            menu.close()
            try:
                await capture_record(message["envelope_id"], root)
            finally:
                if detail_current(revision):
                    capture_button.props(remove="loading")
                    capture_button.enable()

        outbox_letter = source == "outbox"
        with host:
            with ui.card().classes(add="mailbox-outbox" if outbox_letter else "").classes(
                "mailbox-letter w-full shadow-none border border-slate-200 rounded-xl p-0 gap-0"
            ):
                with ui.row().classes(
                    "mailbox-reader-toolbar w-full items-center justify-between gap-2 rounded-t-xl bg-blue-50 border-b border-blue-100 px-3 py-2"
                ):
                    ui.label(text("section.reading_pane")).classes(PANE_HEADING_CLASSES)
                    with ui.row().classes("items-center gap-2"):
                            if eligible and source == "inbox":
                                ui.button(
                                    text("action.reply"), icon="o_reply",
                                    on_click=lambda: compose(source=message, relationship="reply"),
                                ).props("unelevated dense no-caps").classes("mailbox-reply mailbox-directional px-2")
                            if eligible:
                                ui.button(
                                    text("action.forward"), icon="o_turn_right",
                                    on_click=lambda: compose(source=message, relationship="forward", outbox_source=source == "outbox"),
                                ).props("outline dense no-caps").classes("px-2 mailbox-neutral-outline mailbox-directional")
                            if eligible and source == "outbox":
                                ui.button(
                                    text("action.follow_up"), icon="o_send",
                                    on_click=lambda: compose(source=message, relationship="follow_up", outbox_source=True),
                                ).props("unelevated dense no-caps").classes("mailbox-reply px-2")
                            if can_restore:
                                retention_button = ui.button(
                                    render_message("messaging.retention.restore"), icon="restore", on_click=change_mailbox
                                ).props("outline dense no-caps").classes("px-2")
                            if can_capture or can_delete:
                                more = plain_text("action.more")
                                with ui.button(icon="more_horiz").props(
                                    "outline dense " + 'aria-label=' + json.dumps(more, ensure_ascii=False)
                                ).classes("mailbox-neutral-outline").tooltip(more).mark("mailbox-more-actions"), ui.menu() as menu:
                                    with ui.column().classes("gap-1 p-1"):
                                        if can_capture:
                                            capture_button = ui.button(
                                                render_message("messaging.capture.save"), icon="archive", on_click=capture_current,
                                            ).props("flat no-caps")
                                        if can_delete:
                                            retention_button = ui.button(
                                                render_message("messaging.retention.delete"), icon="delete",
                                                color="negative", on_click=change_mailbox,
                                            ).props("flat no-caps")
                with ui.column().classes("w-full min-w-0 gap-3 px-4 py-4"):
                    with ui.row().classes("w-full items-center gap-1.5"):
                        if message.get("is_test"):
                            mailbox_badge(render_message("messaging.test.label"), "warning")
                        if message["message_kind"] == "system_notification":
                            mailbox_badge(text("kind.system_notice"), "info")
                        if message["message_kind"] == "action_amendment_notice" or message.get("amendments"):
                            mailbox_badge(text("notice.action_amended"), "info")
                        priority = message["priority"]
                        priority_label = render_message(
                            "messaging.outbox.priority", priority=plain_text("priority." + priority),
                        )
                        mailbox_badge(priority_label, "neutral" if priority == "normal" else "warning")
                        if message.get("is_completion_reply"):
                            mailbox_badge(text("state.action_completed"), "done")
                        if message.get("expiry_warning"):
                            mailbox_badge(text("state.expiring"), "warning")
                    heading = ui.label(message["subject"]).classes(
                        "w-full text-2xl font-bold break-words"
                    ).props("role=heading aria-level=2 tabindex=-1").mark("mailbox-message-heading")
                    if focus:
                        # NiceGUI Label has no native focus method.
                        ui.run_javascript(f'document.getElementById("c{heading.id}")?.focus()')
                    with ui.row().classes("mailbox-byline items-center gap-2 no-wrap"):
                        render_user_avatar({"name": message["sender_name"]}, size="34px").props("aria-hidden=true")
                        with ui.column().classes("min-w-0 gap-0"):
                            ui.label(message["sender_name"]).classes("text-sm font-semibold break-words")
                            ui.label(format_timestamp(message["sent_at"])).classes("text-xs text-slate-600")
                    security = ' · '.join(str(value) for value in (
                        message.get('security_level_code'),
                        message.get('security_level_name', message['security_level_id']),
                        render_message('webui.render_table.text.level_167db239') + ' ' + str(message['security_level_number'])
                        if message.get('security_level_number') is not None else None,
                    ) if value is not None and value != '')
                    with ui.grid(columns="auto minmax(0, 1fr)").classes(
                        "mailbox-headers w-full items-baseline gap-x-4 gap-y-1 text-sm py-1"
                    ):
                        label_style = "mailbox-header-label text-xs font-semibold text-slate-600"
                        value_style = "mailbox-header-value min-w-0 break-words text-slate-900"
                        for kind in ("to", "cc"):
                            names = "; ".join(
                                x["display_name"] for x in message["selectors"] if x["recipient_type"] == kind
                            )
                            if names:
                                ui.label(text("field." + kind)).classes(label_style)
                                ui.label(names).classes(value_style)
                        ui.label(render_message("messaging.outbox.security")).classes(label_style)
                        ui.label(security).classes(value_style)
                    has_action_details = message["action_required"] or message.get("amendment_notice")
                    is_to_recipient = message.get("recipient_type") == "to"
                    show_action_banner = is_to_recipient or (outbox_letter and not root)
                    if has_action_details and show_action_banner:
                        state = message["effective_action"]
                        action_status = (
                            message.get("action_status") if is_to_recipient
                            else message.get("recipient_summary", {}).get("action_status")
                        )
                        action_label = "field.action_required" if state["action_required"] else "amendment.action_withdrawn"
                        if message["message_kind"] == "action_amendment_notice" and state["action_required"]:
                            action_label = "notice.action_amended"
                        with ui.row().classes("mailbox-action-summary w-full items-center justify-between gap-2 rounded-lg p-3"):
                            with ui.row().classes("grow items-center no-wrap gap-2"):
                                ui.icon("o_event", size="xs").props("aria-hidden=true")
                                with ui.column().classes("min-w-0 gap-1"):
                                    with ui.row().classes("items-baseline gap-1"):
                                        ui.label(text(action_label)).classes("font-semibold")
                                        if action_status and action_status != "withdrawn":
                                            ui.label("· " + state_label(action_status)).classes("text-sm")
                                    if state["action_required"]:
                                        ui.label(render_message(
                                            "messaging.outbox.due", date=format_date(state["due_date"]),
                                        ) if state["due_date"] else render_message("messaging.outbox.no_due_date")).classes("text-sm")
                            if eligible and outbox_letter and state["action_required"]:
                                ui.button(text("action.amend"), color=None, on_click=lambda: amendment_form(message)).props(
                                    "flat dense no-caps"
                                ).classes("font-semibold")
                    elif is_to_recipient and message.get("action_status"):
                        mailbox_badge(state_label(message["action_status"]), action_tone(message["action_status"]))
                    render_body(message, lambda: detail_current(revision))
                    parent = message.get("linked_envelope_id")
                    if parent:
                        with ui.row().classes("w-full border-t border-slate-200 pt-2"):
                            ui.button(
                                text("action.open_amended" if message["message_kind"] == "action_amendment_notice" else "action.open_original"),
                                icon="link",
                                on_click=lambda: open_linked(parent, source, root or message["envelope_id"], overlay),
                            ).props("flat dense no-caps").classes("mailbox-text-link").mark(
                                "earlier-link-" + str(message["envelope_id"])
                            )
                    if root:
                        ui.label(text("help.linked")).classes("text-sm text-slate-500")
                    if outbox_letter and overlay is None and not view["deleted"] and "recipient_summary" in message:
                        render_recipients(message, lambda: detail_current(revision))
                    if has_action_details:
                        section, _ = letter_disclosure(text("section.action_history"))
                        with section:
                            original_action = action_summary(
                                message["action_required"], message["action_due_date"], message["action_due_timezone"],
                            )
                            ui.label(text("section.original") + ": " + original_action).classes("text-sm")
                            state = message["effective_action"]
                            current_action = action_summary(state["action_required"], state["due_date"], state["due_timezone"])
                            if current_action != original_action:
                                if not state["action_required"]:
                                    current_action = text("amendment.action_withdrawn")
                                ui.label(text("section.effective") + ": " + current_action).classes("text-sm")
                            history_host = ui.column().classes("w-full")
                            with history_host:
                                for amendment in message.get("amendments", []) + (
                                    [message["amendment_notice"]]
                                    if message.get("amendment_notice")
                                    else []
                                ):
                                    render_amendment(amendment)
                            history_cursor = {"next": message.get("amendments_next_cursor")}

                            async def more_history():
                                try:
                                    result = await request(
                                        "GET",
                                        f'/{message["envelope_id"]}/amendments',
                                        params={
                                            "after": history_cursor["next"],
                                            "limit": 25,
                                            **({"root_id": root} if root else {}),
                                        },
                                    )
                                except ApiError as error:
                                    warn(error)
                                    return
                                if detail_current(revision):
                                    with history_host:
                                        for row in result["items"]:
                                            render_amendment(row)
                                    history_cursor["next"] = result["next_cursor"]
                                    history_more.set_visibility(result["has_more"])

                            history_more = ui.button(
                                text("action.next"), on_click=more_history
                            ).props("flat no-caps")
                            history_more.set_visibility(bool(history_cursor["next"]))
                    if message.get("expires_at") or can_restore:
                        with ui.row().classes("w-full items-center gap-2 border-t border-slate-200 pt-3"):
                            expiry(message)
                            if can_restore:
                                ui.label(render_message(
                                    "messaging.retention.deadline", deadline=format_timestamp(message["restorable_until"]),
                                )).classes("text-xs text-slate-600")

    def render_body(message, link_active):
        if message.get('disposition_job') and open_disposition_job:
            from .disposition.messages import text as disposition_text
            ui.button(disposition_text('job_details'),icon='open_in_new',on_click=lambda:open_disposition_job(message['disposition_job'])).props('outline no-caps')
        if message.get("disposition_eligibility") and open_disposition_eligibility:
            from .disposition.messages import text as disposition_text
            ui.button(disposition_text("eligibility"),icon="event_available",on_click=open_disposition_eligibility).props("outline no-caps")
        if message.get('disposition_task') and open_disposition_task:
            from .disposition.messages import text as disposition_text
            ui.button(disposition_text('open'),icon='task_alt',on_click=lambda:open_disposition_task(message['disposition_task']['job_id'],message['disposition_task']['task_id'])).props('outline no-caps')
        with ui.column().classes('mailbox-letter-body w-full gap-2 break-words').props('dir=' + message.get('direction', 'auto')):
            body = body_without_resources(message['body_rich_text'])
            if body.strip():
                ui.html(body)
        links = message.get('resource_links', [])
        if links:
            with ui.column().classes("w-full min-w-0 gap-1 border-t border-slate-200 pt-2"):
                ui.label(render_message("messaging.reader.linked_resources")).classes("text-sm font-semibold")
                with ui.column().classes("w-full min-w-0 gap-0 max-h-52 overflow-y-auto"):
                    for link in links:
                        with ui.grid(columns="auto minmax(0, 1fr)").classes("w-full items-center gap-2 py-1"):
                            if link.get('available'):
                                async def open_link(link=link):
                                    if not link_active():
                                        return
                                    try:
                                        await open_resource(link['resource_kind'], link['target_id'], link_active)
                                    except ApiError as error:
                                        if link_active():
                                            warn(error)
                                ui.icon("folder" if link["resource_kind"] == "aggregation" else "description", color="primary")
                                ui.button(link["title"], on_click=open_link).props("flat dense no-caps align=left").classes(
                                    "mailbox-text-link min-w-0 text-start whitespace-normal justify-start"
                                )
                            else:
                                ui.icon("link_off", color="grey")
                                ui.label(text("state.unavailable")).classes("text-slate-500")

    def render_amendment(row):
        with ui.column().classes("w-full gap-1 border-b border-slate-100 py-2"):
            ui.label(
                text("amendment." + row["amendment_kind"])
                + " · "
                + format_timestamp(row["created_at"])
            ).classes("font-medium")
            ui.label(
                action_summary(
                    row["previous_action_required"],
                    row["previous_due_date"],
                    row["previous_due_timezone"],
                )
                + " → "
                + action_summary(
                    row["new_action_required"],
                    row["new_due_date"],
                    row["new_due_timezone"],
                )
            )
            ui.label(row["reason"]).classes("whitespace-pre-wrap")

    async def amendment_form(message):
        state = message["effective_action"]
        kinds = (
            ["due_date_changed", "due_date_removed"]
            if state["due_date"]
            else ["due_date_added"]
        ) + ["action_withdrawn"]
        dialog = ui.dialog().props("persistent")
        request_id = str(uuid4())
        with dialog, ui.card().classes("w-[640px] max-w-full gap-3"):
            ui.label(text("action.amend")).classes("text-xl font-semibold")
            ui.label(
                text("section.original")
                + ": "
                + action_summary(
                    message["action_required"],
                    message["action_due_date"],
                    message["action_due_timezone"],
                )
            )
            ui.label(
                text("section.effective")
                + ": "
                + action_summary(
                    state["action_required"], state["due_date"], state["due_timezone"]
                )
            )
            ui.label(
                text("field.affected_recipients")
                + ": "
                + str(message.get("recipient_count", ""))
            )
            ui.label(text("help.amend")).classes("text-sm text-slate-600")
            kind = (
                ui.select(
                    choices("amendment.", kinds),
                    value=kinds[0],
                    label=text("field.amendment_kind"),
                )
                .props("outlined")
                .classes("w-full")
            )
            date = (
                ui.input(text("field.due_date"))
                .props("outlined type=date")
                .classes("w-full")
            )
            reason = (
                ui.textarea(text("field.reason"))
                .props("outlined maxlength=2000")
                .classes("w-full")
            )
            preview = ui.label()

            def update_preview():
                dated = kind.value in ("due_date_added", "due_date_changed")
                date.set_visibility(dated)
                preview.text = (
                    text("section.effective")
                    + ": "
                    + action_summary(
                        kind.value != "action_withdrawn", date.value if dated else None
                    )
                )

            kind.on_value_change(update_preview)
            date.on_value_change(update_preview)
            update_preview()

            async def commit():
                submit.disable()
                try:
                    await request(
                        "POST",
                        f'/outbox/{message["envelope_id"]}/amendments',
                        json={
                            "request_id": request_id,
                            "amendment_kind": kind.value,
                            "reason": reason.value,
                            "due_date": (
                                date.value
                                if kind.value in ("due_date_added", "due_date_changed")
                                else None
                            ),
                        },
                    )
                except ApiError as error:
                    warn(error)
                    return
                finally:
                    submit.enable()
                dialog.close()
                if active():
                    await asyncio.gather(load(), show_message(message["envelope_id"], "outbox"))

            with ui.row():
                submit = ui.button(text("action.amend"), on_click=commit).props(
                    "no-caps"
                )
                ui.button(text("action.cancel"), on_click=dialog.close).props(
                    "flat no-caps"
                )
        dialog.open()

    async def compose(
        *, draft=None, source=None, relationship=None, outbox_source=False, focus=False
    ):
        if not can_exchange or not active():
            return
        inline = mailbox == "drafts"
        ownership_key = "detail_revision" if inline else "compose_revision"
        view[ownership_key] += 1
        compose_revision = view[ownership_key]

        def owns_form():
            return active() and compose_revision == view[ownership_key]
        try:
            capabilities = await request("GET", "/capabilities")
        except ApiError as error:
            warn(error)
            return
        if not owns_form():
            return
        dialog = None if inline else ui.dialog().props("persistent")
        if inline:
            detail.clear()
            detail_status.text = ""
            placeholder.set_visibility(False)
            detail.set_visibility(True)
        saved = dict(draft or {})
        if draft is None and source and relationship == "reply":
            saved["subject"] = render_message_plain("messaging.reply.subject_prefix") + " " + source["subject"]
        selectors = list(saved.get("selectors", []))
        resources = list(saved.get("resource_links", []))
        if source and relationship == "reply" and source.get("sender_kind") == "user":
            selectors = [{"recipient_type": "to", "selector_kind": "user",
                          "target_id": source["sender_user_id"]}]
        relationship_fields = {
            k: saved.get(k)
            for k in ("relationship_kind", "related_delivery_id", "related_envelope_id")
        }
        if source:
            relationship_fields.update(
                relationship_kind=relationship,
                related_envelope_id=source["envelope_id"] if outbox_source else None,
                related_delivery_id=None if outbox_source else source["id"],
            )
        source_delivery_id = relationship_fields["related_delivery_id"]
        source_envelope_id = relationship_fields["related_envelope_id"]
        if saved.get("relationship_kind") == "reply" and source_delivery_id and not source:
            try:
                source = await request("GET", "/inbox/" + source_delivery_id)
            except ApiError:
                source = None  # Saving remains possible; send revalidates the source.
        if not owns_form():
            return
        form = {
            "revision": 0,
            "valid": False,
            "busy": False,
            "closed": False,
            "request_id": str(uuid4()),
            "signature": None,
        }
        form_active = lambda: owns_form() and not form["closed"]

        def close():
            form["closed"] = True
            if inline:
                if compose_revision == view["detail_revision"]:
                    clear_detail()
            else:
                dialog.close()

        reason_labels = {
            key: plain_text("reason." + key)
            for key in (
                "message_recipient_exchange_required",
                "message_recipient_clearance_required",
                "message_resource_level_too_high",
                "message_resource_unavailable",
            )
        }

        def ineligible(row):
            if row.get("eligible", True):
                return None
            return reason_labels[
                row.get("reason_code") or "message_resource_unavailable"
            ]

        def draft_field(control):
            if inline:
                control.props("dense stack-label label-slot").classes("mailbox-draft-field")
                with control.add_slot("label"):
                    ui.label(control.label).classes("font-semibold text-slate-600")
            return control

        async def preview_draft_source():
            if form_active():
                await open_linked(
                    source_delivery_id or source_envelope_id,
                    "inbox" if source_delivery_id else "outbox", None, mark_read=False,
                )

        with (detail if inline else dialog), ui.card().classes(
            "mailbox-draft-editor w-full shadow-none border border-slate-200 rounded-xl p-0 gap-0"
            if inline else "mailbox-compose-dialog gap-3"
        ) as editor_card:
            if inline:
                with ui.row().classes(
                    "mailbox-draft-heading w-full items-center justify-between gap-2 rounded-t-xl bg-blue-50 border-b border-blue-100 px-4 py-2"
                ):
                    if saved.get("is_deleted"):
                        title_key = "section.deleted_draft"
                    else:
                        title_key = "section.edit_draft" if saved.get("id") else "section.new_draft"
                    draft_heading = ui.label(text(title_key)).classes(PANE_HEADING_CLASSES).props("role=heading aria-level=2")
                    if saved.get("restorable_until") and saved.get("is_deleted"):
                        mailbox_badge(render_message(
                            "messaging.retention.deadline", deadline=format_timestamp(saved["restorable_until"]),
                        ))
                editor_fields = ui.column().classes("w-full min-w-0 gap-3 p-4")
            else:
                # Quasar caps minimized dialogs at 560px. Keep normal modal behavior
                # and cap this wider card at the available width inside the dialog.
                editor_card.style("width: 840px; max-width: 100%")
                ui.label(text("action.compose")).classes("text-xl font-semibold")
                editor_fields = editor_card
        with editor_fields:
            if relationship_fields["relationship_kind"]:
                if inline and (source_delivery_id or source_envelope_id):
                    source_title = (source or {}).get("subject") or text("action.open_original")
                    with ui.row().classes("w-full items-center gap-2 rounded-md bg-slate-50 px-2 py-1"):
                        source_link = ui.button(source_title, icon="link", on_click=preview_draft_source).props(
                            "flat dense no-caps align=left"
                        ).classes("mailbox-text-link mailbox-draft-source max-w-full whitespace-normal")
                        source_link.props(
                            "aria-label=" + json.dumps(plain_text("action.open_original"), ensure_ascii=False)
                        ).tooltip(text("action.open_original"))
                else:
                    ui.label(text("help.linked")).classes("text-sm text-slate-600")
            subject = draft_field(
                ui.input(text("field.subject"), value=saved.get("subject", ""))
                .props("outlined maxlength=255")
                .classes("w-full")
            )
            if focus and not saved.get("is_deleted"):
                subject.run_method("focus")
            recipient_kinds = ("user", "role", "org_unit")
            recipient_controls = {}
            recipient_loaders = []
            browse_buttons = []
            syncing_recipients = False

            def recipient_key(row):
                if row["selector_kind"] == "everyone":
                    return -1
                return int(row["target_id"]) * 3 + recipient_kinds.index(row["selector_kind"])

            async def recipient_row(identity):
                if int(identity) == -1:
                    return {"id": -1, "name": plain_text("field.everyone"), "eligible": True}
                target, index = divmod(int(identity), 3)
                page = await request("GET", "/recipients/" + recipient_kinds[index], params={
                    "target_id": target, "limit": 1, "security_level_id": security.value,
                })
                row = next(iter(page["items"]), {"name": plain_text("state.unavailable"),
                    "eligible": False, "reason_code": "message_recipient_exchange_required"})
                return {**row, "id": identity,
                        "name": recipient_labels[index] + " · " + row["name"]}

            def recipient_locked(address_type):
                return any(row["selector_kind"] == "everyone" and (row["recipient_type"] == "to" or address_type == "cc") for row in selectors)

            async def recipient_page(query, address_type):
                if recipient_locked(address_type):
                    return {"items": []}
                if len(query.strip()) < 2:
                    return {"items": []}
                pages = await asyncio.gather(*(request("GET", "/recipients/" + kind, params={
                    "q": query.strip(), "limit": 25, "security_level_id": security.value,
                }) for kind in recipient_kinds))
                return {"items": [dict(row, id=row["id"] * 3 + index,
                    name=recipient_labels[index] + " · " + row["name"])
                    for index, page in enumerate(pages) for row in page["items"]]}

            recipient_labels = [plain_text("field." + kind) for kind in recipient_kinds]

            async def recipients_changed(recipient_type):
                if syncing_recipients or not form_active():
                    return
                control = recipient_controls[recipient_type]
                candidates = [{"recipient_type": recipient_type,
                    "selector_kind": "everyone" if int(identity) == -1 else recipient_kinds[int(identity) % 3],
                    "target_id": None if int(identity) == -1 else int(identity) // 3} for identity in control.value or []]
                others = [row for row in selectors if row["recipient_type"] != recipient_type]
                if any(row["selector_kind"] == "everyone" and row["recipient_type"] == "to" for row in others):
                    await validate()
                    return
                if any(row["selector_kind"] == "everyone" for row in candidates):
                    candidates = [row for row in candidates if row["selector_kind"] == "everyone"]
                if len(others) + len(candidates) <= limits["MAX_SELECTORS_PER_SEND"]:
                    selectors[:] = others + candidates
                await completion_changed()

            async def choose_everyone(address_type):
                if not form_active() or saved.get("is_deleted") or recipient_locked(address_type):
                    return
                selectors[:] = ([row for row in selectors if row["recipient_type"] == "to" and row["selector_kind"] != "everyone"] if address_type == "cc" else [])
                selectors.append({"recipient_type": address_type, "selector_kind": "everyone", "target_id": None})
                await validate()

            async def browse(recipient_type):
                async def choose(node):
                    if not form_active() or saved.get("is_deleted") or any(row["selector_kind"] == "everyone" and (row["recipient_type"] == "to" or recipient_type == "cc") for row in selectors):
                        return False
                    candidate = {"recipient_type": recipient_type,
                        "selector_kind": node["type"], "target_id": node["id"]}
                    row = await recipient_row(recipient_key(candidate))
                    if not form_active():
                        return False
                    if not row.get("eligible"):
                        ui.notify(ineligible(row), color="warning")
                        return False
                    if candidate not in selectors:
                        if len(selectors) >= limits["MAX_SELECTORS_PER_SEND"]:
                            return False
                        selectors.append(candidate)
                    await validate()
                    return True
                await browse_recipients(selection_mode="all", on_selection=choose)

            with ui.grid(columns="repeat(auto-fit, minmax(min(100%, 14rem), 1fr))").classes("w-full gap-3"):
                for address_type in ("to", "cc"):
                    with ui.column().classes("w-full min-w-0 gap-1"):
                        control = draft_field(relationship_select(text("field." + address_type), {},
                            multiple=True, value=[], remote=True).props(
                                "outlined use-chips input-debounce=0 behavior=menu options-dense"
                            ).classes("mailbox-compose-address w-full"))
                        control.mark("message-recipients-" + address_type)
                        recipient_controls[address_type] = control
                        recipient_loaders.append(bind_relationship(
                            control, "users", ("name",), ("name",),
                            page_loader=lambda query, address_type=address_type: recipient_page(query, address_type), selected_loader=recipient_row,
                            option_reason=ineligible, active=form_active,
                        ))
                        control.on_value_change(lambda _, address_type=address_type: None if syncing_recipients else recipients_changed(address_type))
                        with ui.row().classes("w-full items-center gap-1"):
                            browse_buttons.append(ui.button(
                                plain_text("field.everyone"), icon="groups",
                                on_click=lambda _, address_type=address_type: choose_everyone(address_type),
                            ).props("flat dense no-caps").mark("message-everyone-" + address_type))
                            if browse_recipients:
                                browse_buttons.append(ui.button(
                                    text("action.browse_recipients"), icon="account_tree",
                                    on_click=lambda _, address_type=address_type: browse(address_type),
                                ).props("flat dense no-caps"))
            ui.label(text("help.recipient_search")).classes("text-sm text-slate-500")
            selected_host = ui.column().classes("w-full gap-1")
            with ui.grid(columns="repeat(auto-fit, minmax(min(100%, 14rem), 1fr))").classes("w-full gap-3"):
                levels = {row["id"]: row["name"] for row in capabilities["security_levels"]}
                security = draft_field(relationship_select(
                    render_message("messaging.outbox.security") if inline else text("field.security"),
                    levels,
                    value=saved.get("security_level_id")
                    or (source or {}).get("security_level_id")
                    or capabilities["default_security_level_id"],
                    required=True,
                ))
                bind_relationship(
                    security,
                    "security-levels",
                    ("name",),
                    ("name",),
                    filters={"assignable": True},
                    item_filter=lambda row: row["id"] in levels,
                    active=form_active,
                )
                priority_control = draft_field(ui.select(
                    choices("priority.", ("normal", "high", "very_high")),
                    value=saved.get("priority", "normal"),
                    label=text("field.priority"),
                ).props("outlined"))
            with ui.row().classes("w-full items-center gap-3") as action_controls:
                action = ui.checkbox(
                    text("field.action_required"),
                    value=saved.get("action_required", False),
                )
            with (editor_fields if inline else action_controls):
                due = draft_field(ui.input(
                    text("field.due_date"), value=saved.get("action_due_date") or ""
                ).props("outlined type=date"))
            with action_controls:
                receipts_control = ui.checkbox(
                    text("field.receipts"),
                    value=saved.get("read_receipt_requested", False),
                )
            due_help = ui.label(text("help.due")).classes("text-sm text-slate-500")
            can_complete = bool(
                source
                and relationship_fields["relationship_kind"] == "reply"
                and source.get("sender_kind") == "user"
                and source.get("recipient_type") == "to"
                and source.get("action_status") in ("outstanding", "late")
            )
            completion = ui.checkbox(
                text("field.complete"), value=can_complete and saved.get("complete_action", False)
            )
            completion.set_visibility(can_complete)
            if (
                source
                and relationship_fields["relationship_kind"] == "reply"
                and source.get("action_status")
            ):
                ui.label(state_label(source["action_status"]))
            completion_help = ui.label(text("help.completion")).classes(
                "text-sm text-slate-500"
            )
            completion_help.set_visibility(can_complete)
            ui.label(text("field.body")).classes("font-medium")
            # The message sanitizer accepts paragraphs and strips the editor's default div wrappers.
            editor = ui.editor(
                value=body_without_resources(saved.get("body_rich_text", "")), placeholder=text("field.body")
            ).props("height=12rem paragraph-tag=p").classes("w-full shrink-0")
            editor._props["toolbar"] = [
                ["bold", "italic", "underline"],
                ["unordered", "ordered"],
                ["link", "undo", "redo"],
            ]
            async def add_resources():
                def remaining():
                    return capabilities["limits"]["MAX_RESOURCE_LINKS"] - len(resources)

                def eligible(row):
                    levels = {item["id"]: item.get("level_number", 0)
                              for item in capabilities["security_levels"]}
                    resource_level = levels.get(row.get("security_level_id"))
                    message_level = levels.get(security.value)
                    if resource_level is None or message_level is None or resource_level > message_level:
                        return plain_text("reason.message_resource_level_too_high")
                    return None

                async def attach(selected, picker_active):
                    if not form_active() or not picker_active():
                        return False
                    selected_level = security.value
                    pages = await asyncio.gather(*(request("GET", "/resources/" + item["resource_kind"],
                        params={"target_id": item["target_id"], "limit": 1,
                                "security_level_id": selected_level}) for item in selected))
                    if not form_active() or not picker_active():
                        return False
                    if selected_level != security.value:
                        ui.notify(plain_text("error.conflict"), color="warning")
                        return False
                    if len(selected) > remaining():
                        ui.notify(render_message_plain("resource_picker.limit"), color="warning")
                        return False
                    rows = [next(iter(page["items"]), {"eligible": False,
                            "reason_code": "message_resource_unavailable"}) for page in pages]
                    invalid_row = next((row for row in rows if not row.get("eligible")), None)
                    if invalid_row:
                        ui.notify(ineligible(invalid_row), color="warning")
                        return False
                    # Commit the complete validated selection without an intervening
                    # await. Closing the picker or abandoning compose adds nothing.
                    links = [{"link_token": str(uuid4()), "resource_kind": item["resource_kind"],
                              "target_id": item["target_id"]} for item in selected]
                    resources.extend(links)
                    await validate()
                    return True

                await resource_picker(search=api.full_text_search, eligible=eligible,
                    on_confirm=attach, remaining=remaining, active=form_active, on_error=warn,
                    on_inspect=inspect_resource)

            add_link_button = ui.button(render_message("resource_picker.title"),
                icon="add_link", on_click=add_resources).props(
                    "flat dense no-caps" if inline else "outline no-caps"
                ).classes(add="mailbox-text-link" if inline else "")
            ui.separator()
            resource_count = ui.label().classes("font-medium")
            with ui.scroll_area().props("visible").classes("w-full shrink-0").mark("compose-resources") as resource_scroll:
                resource_host = ui.column().classes("w-full gap-1")
            resource_count.set_visibility(bool(resources))
            resource_scroll.set_visibility(bool(resources))
            resource_scroll.style(f"height: {min(len(resources) * 56, 168)}px")
            validation = ui.label().props("role=status").classes("text-sm")
            limits = capabilities["limits"]
            ui.label(
                text("help.limits")
                + ": "
                + " / ".join(
                    str(limits[k])
                    for k in (
                        "MAX_SELECTORS_PER_SEND",
                        "MAX_RECIPIENTS_PER_SEND",
                        "MAX_RESOURCE_LINKS",
                    )
                )
            ).classes("text-xs text-slate-500")

            def fields():
                return dict(
                    subject=subject.value,
                    body_rich_text=body_with_resource_markers(editor.value, resources),
                    priority=priority_control.value,
                    security_level_id=security.value,
                    action_required=action.value,
                    action_due_date=due.value or None if action.value else None,
                    read_receipt_requested=receipts_control.value,
                    complete_action=completion.value,
                    selectors=selectors,
                    resource_links=resources,
                    **relationship_fields,
                )

            async def validate():
                nonlocal syncing_recipients
                form["revision"] += 1
                check = form["revision"]
                form["valid"] = False
                send_button.disable()
                buttons_per_field = 2 if browse_recipients else 1
                for index, button in enumerate(browse_buttons):
                    address_type = "to" if index < buttons_per_field else "cc"
                    locked = recipient_locked(address_type)
                    button.set_enabled(not locked and not saved.get("is_deleted") and len(selectors) < limits["MAX_SELECTORS_PER_SEND"])
                add_link_button.set_enabled(
                    not saved.get("is_deleted")
                    and len(resources) < limits["MAX_RESOURCE_LINKS"]
                )

                async def resolve(group, row):
                    if group == "recipients" and row["selector_kind"] == "everyone":
                        return {"name": plain_text("field.everyone"), "eligible": True}
                    key = (
                        row["selector_kind"]
                        if group == "recipients"
                        else row["resource_kind"]
                    )
                    page = await request(
                        "GET",
                        f"/{group}/{key}",
                        params={
                            "target_id": row["target_id"],
                            "security_level_id": security.value,
                            "limit": 1,
                        },
                    )
                    return next(
                        iter(page["items"]),
                        {
                            "eligible": False,
                            "reason_code": (
                                "message_resource_unavailable"
                                if group == "resources"
                                else "message_recipient_exchange_required"
                            ),
                        },
                    )

                try:
                    rows = await asyncio.gather(
                        *(resolve("recipients", row) for row in selectors),
                        *(resolve("resources", row) for row in resources),
                    )
                    valid = (
                        bool(selectors)
                        and any(row["recipient_type"] == "to" for row in selectors)
                        and all(row.get("eligible") for row in rows)
                    )
                    if source:
                        numbers = {
                            row["id"]: row["level_number"]
                            for row in capabilities["security_levels"]
                        }
                        valid = valid and numbers.get(
                            security.value, -1
                        ) >= numbers.get(source["security_level_id"], float("inf"))
                    count = None
                    if valid:
                        preview = await request(
                            "POST",
                            "/recipients/validate",
                            json={
                                "selectors": selectors,
                                "security_level_id": security.value,
                            },
                        )
                        count = preview["expanded_recipient_count"]
                except asyncio.CancelledError:
                    return
                except ApiError as error:
                    if form_active() and check == form["revision"]:
                        validation.text = text("error.validation")
                    return
                if not form_active() or check != form["revision"]:
                    return
                syncing_recipients = True
                try:
                    for address_type, control in recipient_controls.items():
                        options = {recipient_key(item):
                            (plain_text("field.everyone") if item["selector_kind"] == "everyone" else recipient_labels[recipient_kinds.index(item["selector_kind"])] + " · " + (row.get("name") or plain_text("state.unavailable")))
                            for item, row in zip(selectors, rows) if item["recipient_type"] == address_type}
                        control.options = options if recipient_locked(address_type) else {**control.options, **options}
                        control._props["use-input"] = not recipient_locked(address_type)
                        control.value = list(options)
                        control.update()
                finally:
                    syncing_recipients = False
                selected_host.clear()
                resource_count.text = render_message("resource_picker.selected") + ": " + str(len(resources))
                resource_count.set_visibility(bool(resources))
                resource_scroll.set_visibility(bool(resources))
                resource_scroll.style(f"height: {min(len(resources) * 56, 168)}px")
                resource_host.clear()
                for group, selected, host, resolved in (
                    ("recipients", selectors, selected_host, rows[: len(selectors)]),
                    ("resources", resources, resource_host, rows[len(selectors) :]),
                ):
                    with host:
                        for item, row in zip(list(selected), resolved):
                            if group == "recipients" and row.get("eligible"):
                                continue
                            with ui.grid(columns='auto minmax(0, 1fr) auto').classes('w-full items-center gap-3 border-b border-slate-100 py-2'):
                                ui.icon(('folder' if item.get('resource_kind') == 'aggregation' else 'description') if group == 'resources' else 'person', color='primary')
                                label = (
                                    row.get("name")
                                    or row.get("title")
                                    or text("state.unavailable")
                                )
                                with ui.column().classes('min-w-0 gap-1'):
                                    ui.label(
                                        (
                                            text("field." + item["recipient_type"]) + ": "
                                            if group == "recipients"
                                            else ""
                                        )
                                        + label
                                    ).classes('min-w-0 break-words')
                                    if not row.get("eligible"):
                                        ui.label(ineligible(row)).classes("text-red-700")

                                async def remove(
                                    _, item=item, selected=selected, group=group
                                ):
                                    selected.remove(item)
                                    if group == "resources":
                                        editor.value = re.sub(
                                            r'<span data-wathiq-link="'
                                            + re.escape(item["link_token"])
                                            + r'">.*?</span>',
                                            "",
                                            editor.value,
                                            flags=re.S,
                                        )
                                    await validate()

                                button = ui.button(icon="close", on_click=remove).props("flat round dense")
                                button.props['aria-label'] = plain_text('action.remove')
                                button.tooltip(text('action.remove'))
                                if saved.get("is_deleted") or (
                                    completion.value
                                    and source
                                    and group == "recipients"
                                    and item
                                    == {
                                        "recipient_type": "to",
                                        "selector_kind": "user",
                                        "target_id": source["sender_user_id"],
                                    }
                                ):
                                    button.disable()
                validation.text = (
                    (text("field.expanded_recipients") + ": " + str(count))
                    if valid
                    else text("error.validation")
                )
                form["valid"] = valid
                send_button.set_enabled(valid and not form["busy"] and not saved.get("is_deleted"))

            async def open_saved_draft():
                if form_active() and not form["busy"] and saved.get("id"):
                    close()
                    await navigate_mailbox("drafts", saved["id"])

            def set_busy(value):
                form["busy"] = value
                save_button.set_enabled(not value and not saved.get("is_deleted"))
                send_button.set_enabled(not value and form["valid"] and not saved.get("is_deleted"))
                cancel_button.set_enabled(not value)
                if discard_button is not None:
                    discard_button.set_enabled(not value)
                if open_draft_button is not None:
                    open_draft_button.set_enabled(not value)

            async def save():
                if not form_active() or form["busy"] or saved.get("is_deleted"):
                    return
                set_busy(True)
                try:
                    data = fields()
                    if saved.get("id"):
                        result = await request(
                            "PUT",
                            "/drafts/" + saved["id"],
                            headers={"If-Match": str(saved["version"])},
                            json=data,
                        )
                    else:
                        result = await request("POST", "/drafts", json=data)
                    saved.update(result)
                    if form_active():
                        if inline:
                            draft_heading.text = text("section.edit_draft")
                            select_row(saved["id"])
                            discard_button.set_visibility(True)
                            show_success("state.saved")
                            await load()
                        else:
                            ui.notify(text("state.saved"), color="positive")
                            if open_draft_button is not None:
                                draft_feedback.set_visibility(True)
                except ApiError as error:
                    if form_active():
                        warn(error)
                finally:
                    if form_active():
                        set_busy(False)

            async def send_message():
                if not form_active() or form["busy"] or saved.get("is_deleted") or not form["valid"]:
                    return
                set_busy(True)
                sent = None
                try:
                    data = fields()
                    # Preserve a key for exact retries, mint a new one only after
                    # the user changes the submitted compose document.
                    signature = json.dumps(data, sort_keys=True)
                    if form["signature"] is not None and signature != form["signature"]:
                        form["request_id"] = str(uuid4())
                    form["signature"] = signature
                    if saved.get("id"):
                        # Explicit save is version checked; after a successful
                        # send the same draft/version request is safely retryable.
                        if form.get("submitted_signature") != signature:
                            updated = await request(
                                "PUT",
                                "/drafts/" + saved["id"],
                                headers={"If-Match": str(saved["version"])},
                                json=data,
                            )
                            saved.update(updated)
                            form["submitted_signature"] = signature
                        sent = await request(
                            "POST",
                            "/drafts/" + saved["id"] + "/send",
                            json={
                                "request_id": form["request_id"],
                                "version": saved["version"],
                                "complete_action": data["complete_action"],
                            },
                        )
                    else:
                        sent = await request(
                            "POST",
                            "/send",
                            json={**data, "request_id": form["request_id"]},
                        )
                except ApiError as error:
                    if form_active():
                        warn(error)
                    return
                finally:
                    if form_active():
                        set_busy(False)
                if not active():
                    return
                owns_editor = form_active()
                if inline and saved.get("id"):
                    # The send committed even if another draft now owns the editor.
                    row = message_rows.pop(str(saved["id"]), None)
                    if row is not None:
                        row.delete()
                if owns_editor:
                    close()
                show_success("state.sent", "outbox", sent.get("envelope_id") if sent else None)
                if (
                    owns_editor and mailbox == "inbox" and source and data["complete_action"]
                    and selected_message == str(source["id"])
                ):
                    await asyncio.gather(load(reset=True), show_message(source["id"], "inbox", mark_read=False))
                else:
                    await load(reset=True)

            async def discard_or_restore():
                if not form_active() or form["busy"]:
                    return
                set_busy(True)
                try:
                    restoring = saved.get("is_deleted")
                    await request(
                        "POST" if restoring else "DELETE",
                        "/drafts/" + saved["id"] + ("/restore" if restoring else ""),
                        headers={"If-Match": str(saved["version"])},
                    )
                except ApiError as error:
                    if form_active():
                        warn(error)
                    return
                finally:
                    if form_active():
                        set_busy(False)
                if form_active():
                    close()
                if active():
                    await load(reset=True)

            open_draft_button = None
            if navigate_mailbox and not inline:
                with ui.row().classes("w-full items-center gap-2").mark("mailbox-draft-saved") as draft_feedback:
                    open_draft_button = ui.button(
                        text("action.open_draft"), icon="open_in_new", on_click=open_saved_draft
                    ).props("flat no-caps")
                draft_feedback.set_visibility(False)

            discard_button = None
            with editor_card, ui.row().classes(
                "mailbox-draft-footer w-full items-center justify-between gap-2 border-t border-slate-200 px-4 py-2"
                if inline else "w-full items-center justify-between gap-2 border-t border-slate-200 pt-2"
            ):
                with ui.row().classes("items-center gap-2"):
                    cancel_button = ui.button(text("action.cancel"), on_click=close).props("flat no-caps")
                    if not saved.get("is_deleted") and (saved.get("id") or inline):
                        discard_button = ui.button(
                            text("action.discard"), icon="delete", color="negative", on_click=discard_or_restore,
                        ).props("flat no-caps")
                        discard_button.set_visibility(bool(saved.get("id")))
                with ui.row().classes("items-center gap-2"):
                    save_button = ui.button(
                        text("action.save_draft"), icon="save", on_click=save
                    ).props("outline no-caps").classes(add="mailbox-neutral-outline" if inline else "")
                    send_button = ui.button(
                        text("action.send"), icon="send", on_click=send_message
                    ).props("no-caps").mark("messaging-send")
                    send_button.disable()
                    if saved.get("is_deleted"):
                        save_button.set_visibility(False)
                        send_button.set_visibility(False)
                        discard_button = ui.button(
                            text("action.restore"), icon="restore", on_click=discard_or_restore,
                        ).props("unelevated no-caps")
            if saved.get("is_deleted"):
                save_button.disable()
                for control in (
                    security,
                    subject,
                    *recipient_controls.values(),
                    *browse_buttons,
                    priority_control,
                    action,
                    due,
                    receipts_control,
                    completion,
                    editor,
                    add_link_button,
                ):
                    control.disable()

            async def security_changed():
                await validate()
                await asyncio.gather(*(loader() for loader in recipient_loaders))

            async def completion_changed():
                if completion.value and source and not any(row["selector_kind"] == "everyone" and row["recipient_type"] == "to" for row in selectors):
                    entry = {
                        "recipient_type": "to",
                        "selector_kind": "user",
                        "target_id": source["sender_user_id"],
                    }
                    if entry not in selectors:
                        selectors.append(entry)
                await validate()

            def action_changed():
                due.set_visibility(action.value)
                due_help.set_visibility(action.value)
                if not action.value:
                    due.value = ""

            security.on_value_change(security_changed)
            completion.on_value_change(completion_changed)
            action.on_value_change(action_changed)
            action_changed()
        if dialog is not None:
            dialog.open()
        await completion_changed()

    for control in filters.values():
        control.on_value_change(lambda _: update_clear_filters())
    active_tools.set_visibility(not view["deleted"] or mailbox == "drafts")
    render_applied_filters()
    if initial_item is None:
        await load()
    else:
        await asyncio.gather(load(), open_item({"id": str(initial_item)}, focus=True))

    async def refresh_live():
        if active() and content.visible:
            await load()

    async def refresh_capture():
        if active() and selected_message:
            await asyncio.gather(show_message(selected_message, mailbox, mark_read=False), refresh_live())

    return {
        "refresh": refresh_live,
        "capture_committed": refresh_capture,

    }
