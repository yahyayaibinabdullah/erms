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
from .resource_picker import resource_picker
from .i18n_catalogue import render_message, render_message_plain

MESSAGING_MESSAGE_KEYS = {
    "notice.action_amended": "messaging.notice.action_amended",
    "navigation.messages": "messaging.navigation.messages",
    "navigation.inbox": "messaging.navigation.inbox",
    "navigation.outbox": "messaging.navigation.outbox",
    "navigation.drafts": "messaging.navigation.drafts",
    "action.browse_recipients": "messaging.action.browse_recipients",
    "help.recipient_search": "messaging.help.recipient_search",
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
    "section.recipients": "messaging.section.recipients",
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
    on_read=None,
    capture_record=None,
    browse_recipients=None,
    inspect_resource=None,
    open_disposition_task=None,
):
    view = {
        "revision": 0,
        "detail_revision": 0,
        "cursor": None,
        "previous": [],
        "next": None,
        "deleted": False,
        "mode": "list",
    }
    read_badges = {}
    message_rows = {}
    selected_message = None
    base = "/api/v1/messages"

    def current(revision):
        return active() and revision == view["revision"]

    def warn(error):
        if (
            active()
            and isinstance(error.detail, dict)
            and error.detail.get("message_key")
        ):
            ui.notify(
                render_message(
                    error.detail["message_key"], **error.detail.get("parameters", {})
                ),
                color="negative",
                close_button=True,
            )
            return
        if active():
            key = (
                "error.conflict"
                if error.status_code == 409
                else (
                    "error.denied"
                    if error.status_code in (403, 404)
                    else (
                        "error.validation"
                        if error.status_code == 422
                        else "error.failed"
                    )
                )
            )
            ui.notify(text(key), color="negative", close_button=True)

    async def request(method, path, **kwargs):
        return await api.request(method, base + path, **kwargs)

    def state_label(value):
        return text("state." + value) if value else "—"

    def action_summary(required, due, zone=None):
        return (text("field.action_required") if required else "—") + (
            " · " + str(due) + (" · " + zone if zone else "") if due else ""
        )

    def expiry(item):
        if item.get("expires_at"):
            ui.label(
                text("field.expiry") + ": " + format_timestamp(item["expires_at"])
            ).classes("text-xs text-slate-500")
            if item.get("expiry_warning"):
                ui.badge(text("state.expiring"), color="orange")

    with container:
        with ui.column().classes("messaging-workspace w-full gap-3 p-3"):
            with ui.row().classes("w-full items-center gap-2"):
                if can_exchange:
                    ui.button(
                        text("action.compose"), icon="edit", on_click=lambda: compose()
                    ).props("no-caps")
                ui.button(
                    text("action.refresh"),
                    icon="refresh",
                    on_click=lambda: load(reset=True),
                ).props("flat no-caps")
                if mailbox in ("drafts", "inbox", "outbox"):
                    deleted = ui.switch(
                        text("action.recently_deleted")
                        if mailbox == "drafts"
                        else render_message("messaging.retention.recently_deleted")
                    )

                    async def deleted_changed(e):
                        view["deleted"] = e.value
                        view["detail_revision"] += 1
                        detail.set_visibility(False)
                        await load(reset=True)

                    deleted.on_value_change(deleted_changed)
            filters_host = ui.row().classes("w-full items-start gap-2")
            with filters_host:
                filters = {}
                if mailbox == "inbox" and can_exchange:
                    with ui.column().classes("w-full max-w-xs gap-1"):
                        sender = relationship_select(text("field.sender"), {}, remote=True)
                        sender.classes("w-full").mark("mailbox-sender")
                        async def sender_page(query):
                            if len(query.strip()) < 2:
                                return {"items": []}
                            return await request("GET", "/recipients/user", params={"q": query.strip(), "limit": 25, "purpose": "filter"})
                        async def selected_sender(identity):
                            page = await request("GET", "/recipients/user", params={"target_id": identity, "limit": 1, "purpose": "filter"})
                            return next(iter(page["items"]), {"id": identity, "name": plain_text("state.unavailable")})
                        bind_relationship(sender, "users", ("name",), ("name",), page_loader=sender_page, selected_loader=selected_sender, active=active)
                        filters["sender_user_id"] = sender
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
                            value="",
                            label=text("field.priority"),
                        )
                        .props("outlined dense")
                        .classes("min-w-40")
                    )
                    filters["priority"] = priority
                if mailbox == "inbox":
                    read = ui.select(
                        {
                            "": text("field.all"),
                            "true": text("field.read"),
                            "false": text("field.unread"),
                        },
                        value="",
                        label=text("field.read"),
                    ).props("outlined dense")
                    filters["is_read"] = read
                if mailbox in ("inbox", "outbox"):
                    filters["sent_from"] = ui.input(text("field.sent_from")).props(
                        "outlined dense type=date"
                    )
                    filters["sent_before"] = ui.input(text("field.sent_before")).props(
                        "outlined dense type=date"
                    )
                if mailbox == "outbox":
                    filters["q"] = ui.input(text("field.search")).props(
                        "outlined dense"
                    )
                    filters["action_required"] = ui.select(
                        {
                            "": text("field.all"),
                            "true": text("field.action_required"),
                            "false": text("field.information"),
                        },
                        value="",
                        label=text("field.action_required"),
                    ).props("outlined dense")
                    filters["action_state"] = ui.select(
                        {
                            "": text("field.all"),
                            **choices("state.", ("outstanding", "late")),
                        },
                        value="",
                        label=text("section.effective"),
                    ).props("outlined dense")
                    security = relationship_select(text("field.security"), {})
                    security.classes("max-w-xs")
                    bind_relationship(
                        security, "security-levels", ("name",), ("name",), active=active
                    )
                    filters["security_level_id"] = security
                if mailbox in ("inbox", "outbox", "drafts") and can_exchange:
                    filter_kinds = ("user", "role", "org_unit")
                    filter_labels = [plain_text("field." + kind) for kind in filter_kinds]
                    with ui.column().classes("w-full max-w-xs gap-1") as recipient_group:
                        recipient = relationship_select(text("field.recipient"), {}, remote=True)
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
                        active=active)
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
                if mailbox != "drafts" or can_exchange:
                    ui.button(
                        text("field.search"),
                        icon="search",
                        on_click=lambda: load(reset=True),
                    ).props("flat no-caps")
            progress = ui.label(text("state.loading")).props("role=status")
            with ui.grid().classes("w-full grid-cols-1 lg:grid-cols-2 gap-4 items-start"):
                with ui.column().classes("w-full min-w-0 gap-3"):
                    content = ui.column().classes(
                        "w-full gap-0 rounded-xl border border-slate-200 overflow-hidden bg-white"
                    )
                    with ui.row().classes("w-full items-center gap-2") as pagination:
                        previous = ui.button(text("action.previous"), on_click=lambda: page(False)).props("outline no-caps")
                        next_button = ui.button(text("action.next"), on_click=lambda: page(True)).props("outline no-caps")
                detail = ui.column().classes("w-full min-w-0 gap-3")
                detail.set_visibility(False)

    async def page(forward):
        if forward:
            view["previous"].append(view["cursor"])
            view["cursor"] = view["next"]
        elif view["previous"]:
            view["cursor"] = view["previous"].pop()
        await load()

    async def load(reset=False):
        view["revision"] += 1
        revision = view["revision"]
        view["mode"] = "list"
        if reset:
            view.update(cursor=None, previous=[])
        content.set_visibility(True)
        filters_host.set_visibility(not view["deleted"] or mailbox == "drafts")
        pagination.set_visibility(True)
        progress.text = text("state.loading")
        params = {"limit": 25}
        if view["cursor"]:
            params["cursor"] = view["cursor"]
        if mailbox == "drafts":
            params["deleted"] = view["deleted"]
        elif not view["deleted"]:
            params.update(
                {
                    key: control.value
                    for key, control in filters.items()
                    if control.value not in (None, "")
                }
            )
            for key in ("sent_from", "sent_before"):
                if key in params:
                    params[key] += "T00:00:00Z"
        if (mailbox == "drafts" or not view["deleted"]) and can_exchange and recipient.value:
            target, index = divmod(int(recipient.value), 3)
            params.update(recipient_kind=filter_kinds[index], recipient_id=target)
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
        if not current(revision):
            return
        progress.text = ""
        content.clear()
        read_badges.clear()
        message_rows.clear()
        with content:
            with ui.column(align_items="start").classes(
                "w-full bg-blue-50 border-b border-blue-100 px-4 py-3"
            ):
                ui.label(text("navigation." + mailbox)).classes(
                    "font-semibold text-blue-900"
                )
            if not result["items"]:
                ui.label(text("state.empty")).classes("p-5 text-slate-500")
            for item in result["items"]:
                with ui.row().classes(
                    "w-full items-start justify-between gap-3 p-4 border-b border-slate-100 hover:bg-blue-50/30"
                ) as message_row:
                    if item.get("availability") != "restricted" or mailbox != "drafts":
                        message_rows[str(item["id"])] = message_row
                        if str(item["id"]) == selected_message:
                            message_row.classes("bg-blue-50")
                        message_row.props("tabindex=0 role=button").classes("cursor-pointer")
                        message_row.mark("message-row-" + str(item["id"]))
                        message_row.on("click", lambda _, row=item: open_item(row))
                        message_row.on("keydown.enter", lambda _, row=item: open_item(row))
                        message_row.on("keydown.space", lambda _, row=item: open_item(row))
                    with ui.column().classes("grow min-w-0 gap-1"):
                        if item.get("availability") == "restricted":
                            ui.label(text("state.restricted")).classes("font-semibold")
                            ui.label(text("error.denied")).classes(
                                "text-sm text-slate-500"
                            )
                        else:
                            ui.label(
                                item.get("subject") or text("action.compose")
                            ).classes("font-semibold break-words")
                            if item.get("is_test"):
                                ui.label(
                                    render_message("messaging.test.label")
                                ).classes("font-bold text-amber-900")
                            with ui.row().classes("w-full min-w-0 gap-2 items-center"):
                                names = '; '.join(item.get('recipient_names', [])) if mailbox == 'outbox' else item.get('sender_name', '')
                                if names:
                                    ui.label(names).classes('text-sm truncate w-full min-w-0').tooltip(names)
                                if "is_read" in item:
                                    read_badges[str(item["id"])] = ui.badge(
                                        text(
                                            "field.read"
                                            if item["is_read"]
                                            else "field.unread"
                                        ),
                                        color="grey" if item["is_read"] else "blue",
                                    )
                                if item.get("recipient_type"):
                                    ui.badge(
                                        text("field." + item["recipient_type"]),
                                        color="blue-grey",
                                    )
                                if item.get("priority"):
                                    ui.badge(
                                        text("priority." + item["priority"]),
                                        color=(
                                            "orange"
                                            if item["priority"] != "normal"
                                            else "grey"
                                        ),
                                    )
                                if item.get("action_status"):
                                    ui.badge(
                                        state_label(item["action_status"]),
                                        color=(
                                            "orange"
                                            if "late" in item["action_status"]
                                            else "blue"
                                        ),
                                    )
                                if item.get("recipient_type") != "cc" and not item.get("action_status") and item.get(
                                    "effective_action", {}
                                ).get("action_required"):
                                    ui.badge(
                                        text("field.action_required"), color="blue"
                                    )
                                due = item.get("effective_action", {}).get("due_date")
                                if due:
                                    ui.label(
                                        text("field.due_date") + ": " + due
                                    ).classes("text-sm")
                                if item.get("has_unavailable_resources"):
                                    ui.icon("link_off").tooltip(
                                        text("state.unavailable")
                                    )
                                if item.get("amendment_sequence"):
                                    ui.badge(
                                        text("notice.action_amended"), color="blue-grey"
                                    )
                            expiry(item)
                            if mailbox == "drafts":
                                ui.label(
                                    text(
                                        "state.needs_attention"
                                        if item.get("needs_attention")
                                        else "state.ready_validate"
                                    )
                                ).classes("text-sm text-slate-500")
                        ui.label(
                            format_timestamp(
                                item.get("sent_at") or item.get("date_updated")
                            )
                        ).classes("text-xs text-slate-500")
        view["next"] = result.get("next_cursor")
        previous.set_enabled(bool(view["previous"]))
        next_button.set_enabled(bool(result.get("has_more")))

    async def open_item(item):
        nonlocal selected_message
        if mailbox == "drafts":
            view["detail_revision"] += 1
            opening_revision = view["detail_revision"]
            try:
                draft = await request(
                    "GET", "/drafts/" + item["id"], params={"deleted": view["deleted"]}
                )
            except ApiError as error:
                warn(error)
                return
            if active() and opening_revision == view["detail_revision"]:
                selected_message = str(item["id"])
                for row_id, row in message_rows.items():
                    row.classes(add="bg-blue-50" if row_id == selected_message else "", remove="bg-blue-50" if row_id != selected_message else "")
                await compose(draft=draft)
        else:
            await show_message(item["id"], mailbox)

    async def open_linked(identity, source, root, overlay=None):
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
                    previous_identity, previous_source, previous_root = overlay["history"][-1]
                    overlay["back"].set_visibility(len(overlay["history"]) > 1)
                    await show_message(previous_identity, previous_source, root=previous_root, overlay=overlay)
            with dialog, ui.card().classes("gap-3").style("width: 672px; max-width: calc(100vw - 32px)"):
                with ui.row().classes("w-full items-center justify-between gap-2"):
                    ui.label(render_message("messaging.linked.title")).classes("text-xl font-semibold")
                    ui.button(render_message("messaging.live.close"), icon="close", on_click=close_linked).props("flat no-caps").mark("linked-message-close")
                overlay["back"] = ui.button(text("action.previous"), icon="arrow_back", on_click=back_linked).props("flat no-caps").mark("linked-message-back")
                overlay["status"] = ui.label().props("role=status")
                overlay["host"] = ui.column().classes("w-full min-w-0 gap-3")
            dialog.open()
        overlay["history"].append((identity, source, root))
        overlay["back"].set_visibility(len(overlay["history"]) > 1)
        await show_message(identity, source, root=root, overlay=overlay)

    async def show_message(identity, source, *, root=None, overlay=None):
        nonlocal selected_message
        if root and overlay is None:
            await open_linked(identity, source, root)
            return
        state = overlay if overlay is not None else view
        revision_key = "revision" if overlay is not None else "detail_revision"
        state[revision_key] += 1
        revision = state[revision_key]
        def detail_current(revision):
            return active() and revision == state[revision_key] and (overlay is None or
                (not overlay["closed"] and overlay["owner_revision"] == view["detail_revision"]))

        host = overlay["host"] if overlay is not None else detail
        status = overlay["status"] if overlay is not None else progress
        status.text = text("state.loading")
        try:
            if root:
                message = await request("GET", f"/linked/{root}/{identity}")
            elif view["deleted"]:
                message = await request("GET", f"/recently-deleted/{source}/{identity}")
            elif source == "inbox":
                message = await request("POST", f"/inbox/{identity}/read")
                if on_read is not None:
                    await on_read()
            else:
                message = await request("GET", f"/outbox/{identity}")
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
            selected_message = str(identity)
            for row_id, row in message_rows.items():
                row.classes(add="bg-blue-50" if row_id == selected_message else "", remove="bg-blue-50" if row_id != selected_message else "")
            if source == "inbox" and not root and not view["deleted"] and str(identity) in read_badges:
                read_badges[str(identity)].set_text(text("field.read"))
                read_badges[str(identity)].props("color=grey")
        host.clear()
        host.set_visibility(True)
        if message["availability"] != "available":
            with host:
                ui.label(text("state.restricted"))
            return
        with host:
            with ui.card().classes("w-full shadow-none border border-slate-200 gap-3"):
                ui.label(message["subject"]).classes(
                    "text-xl font-semibold break-words"
                )
                if message.get("is_test"):
                    ui.label(render_message("messaging.test.label")).classes(
                        "font-bold text-amber-900"
                    )
                ui.label(
                    message["sender_name"]
                    + " · "
                    + format_timestamp(message["sent_at"])
                ).classes("text-sm text-slate-600")
                with ui.row().classes("items-center gap-2"):
                    ui.badge(text("priority." + message["priority"]))
                    ui.label(
                        text("field.security")
                        + ": "
                        + ' · '.join(str(value) for value in (
                            message.get('security_level_code'),
                            message.get('security_level_name', message['security_level_id']),
                            render_message('webui.render_table.text.level_167db239') + ' ' + str(message['security_level_number'])
                            if message.get('security_level_number') is not None else None,
                        ) if value is not None and value != '')
                    )
                    if message.get("action_status"):
                        ui.badge(state_label(message["action_status"]))
                    if message.get("is_completion_reply"):
                        ui.badge(text("state.action_completed"), color="green")
                for kind in ("to", "cc"):
                    ui.label(
                        text("field." + kind)
                        + ": "
                        + "; ".join(
                            x["display_name"]
                            for x in message["selectors"]
                            if x["recipient_type"] == kind
                        )
                    ).classes("text-sm")
                expiry(message)
                render_body(message)

                async def change_mailbox():
                    try:
                        await request(
                            "POST" if view["deleted"] else "DELETE",
                            f"/{source}/{identity}"
                            + ("/restore" if view["deleted"] else ""),
                        )
                    except ApiError as error:
                        warn(error)
                        return
                    if active():
                        if on_read is not None:
                            await on_read()
                        view["detail_revision"] += 1
                        detail.set_visibility(False)
                        await load(reset=True)

                with ui.row().classes("detail-action-row gap-2"):
                    if capture_record and message["message_kind"] == "user_message":

                        async def capture_current():
                            capture_button.disable()
                            capture_button.props("loading")
                            try:
                                await capture_record(message["envelope_id"], root)
                            finally:
                                if detail_current(revision):
                                    capture_button.props(remove="loading")
                                    capture_button.enable()

                        capture_button = ui.button(
                            render_message("messaging.capture.save"),
                            icon="archive",
                            on_click=capture_current,
                        ).props("outline no-caps")
                    if not root and (view["deleted"] or message.get("can_delete")):
                        ui.button(
                            render_message(
                                "messaging.retention.restore"
                                if view["deleted"]
                                else "messaging.retention.delete"
                            ),
                            icon="restore" if view["deleted"] else "delete",
                            on_click=change_mailbox,
                        ).props("flat no-caps")
                        if view["deleted"]:
                            ui.label(
                                render_message(
                                    "messaging.retention.deadline",
                                    deadline=format_timestamp(
                                        message["restorable_until"]
                                    ),
                                )
                            )
                parent = message.get("linked_envelope_id")
                if parent:
                    ui.button(
                        text(
                            "action.open_amended"
                            if message["message_kind"] == "action_amendment_notice"
                            else "action.open_original"
                        ),
                        icon="link",
                        on_click=lambda: open_linked(
                            parent, source, root or message["envelope_id"], overlay
                        ),
                    ).props("outline no-caps").mark("earlier-link-" + str(message["envelope_id"]))
                if root:
                    ui.label(text("help.linked")).classes("text-sm text-slate-500")
                eligible = (
                    not root
                    and not view["deleted"]
                    and can_exchange
                    and not message["is_test"]
                    and message["message_kind"] != "action_amendment_notice"
                    and datetime.fromisoformat(
                        message["expires_at"].replace("Z", "+00:00")
                    )
                    > datetime.now(timezone.utc)
                )
                if eligible:
                    with ui.row().classes("gap-2"):
                        if source == "inbox":
                            ui.button(
                                text("action.reply"),
                                icon="reply",
                                on_click=lambda: compose(
                                    source=message, relationship="reply"
                                ),
                            ).props("no-caps")
                        ui.button(
                            text("action.forward"),
                            icon="forward",
                            on_click=lambda: compose(
                                source=message,
                                relationship="forward",
                                outbox_source=source == "outbox",
                            ),
                        ).props("outline no-caps")
                        if source == "outbox":
                            ui.button(
                                text("action.follow_up"),
                                icon="reply_all",
                                on_click=lambda: compose(
                                    source=message,
                                    relationship="follow_up",
                                    outbox_source=True,
                                ),
                            ).props("outline no-caps")
            if message["action_required"] or message.get("amendment_notice"):
                with ui.card().classes("w-full shadow-none border border-blue-100"):
                    ui.label(
                        text("section.original")
                        + ": "
                        + action_summary(
                            message["action_required"],
                            message["action_due_date"],
                            message["action_due_timezone"],
                        )
                    ).classes("text-sm")
                    state = message["effective_action"]
                    ui.label(
                        text("section.effective")
                        + ": "
                        + action_summary(
                            state["action_required"],
                            state["due_date"],
                            state["due_timezone"],
                        )
                    ).classes("font-medium")
                    if eligible and source == "outbox" and state["action_required"]:
                        ui.button(
                            text("action.amend"),
                            icon="edit_calendar",
                            on_click=lambda: amendment_form(message),
                        ).props("no-caps")
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
            if source == "outbox" and not root:
                with ui.card().classes("w-full shadow-none border border-slate-200"):
                    ui.label(text("section.recipients")).classes("font-semibold")
                    receipts_host = ui.column().classes("w-full")
                    receipt_cursor = {"after": 0}

                    async def receipts():
                        try:
                            result = await request(
                                "GET",
                                f'/outbox/{message["envelope_id"]}/recipients',
                                params={"limit": 25, "after": receipt_cursor["after"]},
                            )
                        except ApiError as error:
                            warn(error)
                            return
                        if not detail_current(revision):
                            return
                        receipts_host.clear()
                        with receipts_host:
                            for row in result["items"]:
                                with ui.row().classes(
                                    "w-full items-center gap-3 border-b border-slate-100 py-2"
                                ):
                                    ui.label(row["recipient_name"])
                                    ui.badge(text("field." + row["recipient_type"]))
                                    if row.get("action_status"):
                                        ui.label(state_label(row["action_status"]))
                                    if "read_at" in row:
                                        ui.label(
                                            format_timestamp(row["read_at"])
                                            if row["read_at"]
                                            else text("field.unread")
                                        )
                                    if row.get("completion_reply_delivery_id"):
                                        ui.button(
                                            text("state.action_completed"),
                                            on_click=lambda _, r=row: show_message(
                                                r["completion_reply_delivery_id"],
                                                "inbox",
                                            ),
                                        ).props("flat no-caps")
                        receipt_cursor["after"] = result.get("next_cursor")
                        receipt_next.set_visibility(result["has_more"])

                    receipt_next = ui.button(
                        text("action.next"), on_click=receipts
                    ).props("flat no-caps")
                    await receipts()

    def render_body(message):
        if message.get('disposition_task') and open_disposition_task:
            from .disposition.messages import text as disposition_text
            ui.button(disposition_text('open'),icon='task_alt',on_click=lambda:open_disposition_task(message['disposition_task']['job_id'],message['disposition_task']['task_id'])).props('outline no-caps')
        with ui.column().classes('w-full gap-2 break-words').props('dir=' + message.get('direction', 'auto')):
            body = body_without_resources(message['body_rich_text'])
            if body.strip():
                ui.html(body)
        links = message.get('resource_links', [])
        if links:
            with ui.card().classes('w-full border border-blue-100 shadow-none gap-2'):
                ui.label(render_message('messaging.field.resources')).classes('font-semibold')
                with ui.scroll_area().props('visible').classes('w-full').style(f'height: {min(len(links) * 52, 208)}px'):
                    with ui.column().classes('w-full gap-0'):
                        for link in links:
                            if link.get('available'):
                                async def open_link(link=link):
                                    try:
                                        if inspect_resource:
                                            await inspect_resource(link['resource_kind'], link['target_id'], active)
                                        else:
                                            await open_resource(link['resource_kind'], link['target_id'])
                                    except ApiError as error:
                                        warn(error)
                                with ui.grid(columns='auto minmax(0, 1fr)').classes('w-full items-start gap-3 border-b border-blue-50 py-2'):
                                    ui.icon('folder' if link['resource_kind'] == 'aggregation' else 'description', color='primary').classes('shrink-0 mt-1')
                                    ui.button(link['title'], on_click=open_link).props('flat no-caps align=left').classes('grow min-w-0 text-start whitespace-normal justify-start')
                            else:
                                with ui.grid(columns='auto minmax(0, 1fr)').classes('w-full items-start gap-3 border-b border-blue-50 py-2'):
                                    ui.icon('link_off', color='grey')
                                    ui.label(text('state.unavailable')).classes('text-slate-500')

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
                    await show_message(message["envelope_id"], "outbox")

            with ui.row():
                submit = ui.button(text("action.amend"), on_click=commit).props(
                    "no-caps"
                )
                ui.button(text("action.cancel"), on_click=dialog.close).props(
                    "flat no-caps"
                )
        dialog.open()

    async def compose(
        *, draft=None, source=None, relationship=None, outbox_source=False
    ):
        if not can_exchange or not active():
            return
        inline = mailbox == "drafts"
        if inline:
            view["detail_revision"] += 1
        compose_revision = view["detail_revision"]
        revision = view["revision"]
        try:
            capabilities = await request("GET", "/capabilities")
        except ApiError as error:
            warn(error)
            return
        if not active() or (inline and compose_revision != view["detail_revision"]) or (not inline and not current(revision)):
            return
        dialog = None if inline else ui.dialog().props("persistent")
        if inline:
            detail.clear()
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
        if saved.get("relationship_kind") == "reply" and not source:
            try:
                source = await request("GET", "/inbox/" + saved["related_delivery_id"])
            except ApiError:
                source = None  # Saving remains possible; send revalidates the source.
        if inline and compose_revision != view["detail_revision"]:
            return
        form = {
            "revision": 0,
            "valid": False,
            "closed": False,
            "request_id": str(uuid4()),
            "signature": None,
        }
        form_active = lambda: active() and not form["closed"] and (not inline or compose_revision == view["detail_revision"])

        def close():
            form["closed"] = True
            if inline:
                if compose_revision == view["detail_revision"]:
                    view["detail_revision"] += 1
                    detail.clear()
                    detail.set_visibility(False)
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

        with (detail if inline else dialog), ui.card().classes("w-full shadow-none border border-slate-200 gap-3" if inline else "w-[960px] max-w-full gap-3"):
            ui.label(text("action.compose")).classes("text-xl font-semibold")
            if relationship_fields["relationship_kind"]:
                ui.label(text("help.linked")).classes("text-sm text-slate-600")
            levels = {row["id"]: row["name"] for row in capabilities["security_levels"]}
            security = relationship_select(
                text("field.security"),
                levels,
                value=saved.get("security_level_id")
                or (source or {}).get("security_level_id")
                or capabilities["default_security_level_id"],
                required=True,
            )
            bind_relationship(
                security,
                "security-levels",
                ("name",),
                ("name",),
                filters={"assignable": True},
                item_filter=lambda row: row["id"] in levels,
                active=form_active,
            )
            subject = (
                ui.input(text("field.subject"), value=saved.get("subject", ""))
                .props("outlined maxlength=255")
                .classes("w-full")
            )
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

            for address_type in ("to", "cc"):
                control = relationship_select(text("field." + address_type), {},
                    multiple=True, value=[], remote=True).props(
                        "outlined use-chips input-debounce=0 behavior=menu options-dense"
                    ).classes("w-full")
                control.mark("message-recipients-" + address_type)
                recipient_controls[address_type] = control
                recipient_loaders.append(bind_relationship(
                    control, "users", ("name",), ("name",),
                    page_loader=lambda query, address_type=address_type: recipient_page(query, address_type), selected_loader=recipient_row,
                    option_reason=ineligible, active=form_active,
                ))
                control.on_value_change(lambda _, address_type=address_type: None if syncing_recipients else recipients_changed(address_type))
                browse_buttons.append(ui.button(plain_text("field.everyone"), icon="groups",
                    on_click=lambda _, address_type=address_type: choose_everyone(address_type)).props("flat no-caps").mark("message-everyone-" + address_type))
                if browse_recipients:
                    browse_buttons.append(ui.button(
                        text("action.browse_recipients"), icon="account_tree",
                        on_click=lambda _, address_type=address_type: browse(address_type),
                    ).props("flat no-caps"))
            ui.label(text("help.recipient_search")).classes("text-sm text-slate-500")
            selected_host = ui.column().classes("w-full gap-1")
            with ui.row().classes("w-full items-center gap-3"):
                priority_control = ui.select(
                    choices("priority.", ("normal", "high", "very_high")),
                    value=saved.get("priority", "normal"),
                    label=text("field.priority"),
                ).props("outlined")
                action = ui.checkbox(
                    text("field.action_required"),
                    value=saved.get("action_required", False),
                )
                due = ui.input(
                    text("field.due_date"), value=saved.get("action_due_date") or ""
                ).props("outlined type=date")
                receipts_control = ui.checkbox(
                    text("field.receipts"),
                    value=saved.get("read_receipt_requested", False),
                )
            due_help = ui.label(text("help.due")).classes("text-sm text-slate-500")
            completion = ui.checkbox(text("field.complete"), value=False)
            can_complete = bool(
                source
                and relationship_fields["relationship_kind"] == "reply"
                and source.get("sender_kind") == "user"
                and source.get("recipient_type") == "to"
                and source.get("action_status") in ("outstanding", "late")
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
            editor = ui.editor(
                value=body_without_resources(saved.get("body_rich_text", "")), placeholder=text("field.body")
            ).props("height=12rem").classes("w-full shrink-0")
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
                icon="add_link", on_click=add_resources).props("outline no-caps")
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
                send_button.set_enabled(valid and not saved.get("is_deleted"))

            async def save():
                save_button.disable()
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
                    ui.notify(text("state.saved"), color="positive")
                    if mailbox == "drafts" and active():
                        await load()
                except ApiError as error:
                    warn(error)
                finally:
                    save_button.enable()

            async def send_message():
                send_button.disable()
                try:
                    data = fields()
                    # Preserve a key for exact retries, mint a new one only after
                    # the user changes the submitted compose document.
                    signature = json.dumps(
                        {**data, "complete_action": completion.value}, sort_keys=True
                    )
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
                        await request(
                            "POST",
                            "/drafts/" + saved["id"] + "/send",
                            json={
                                "request_id": form["request_id"],
                                "version": saved["version"],
                                "complete_action": completion.value,
                            },
                        )
                    else:
                        await request(
                            "POST",
                            "/send",
                            json={
                                **data,
                                "request_id": form["request_id"],
                                "complete_action": completion.value,
                            },
                        )
                except ApiError as error:
                    warn(error)
                    return
                finally:
                    send_button.set_enabled(form["valid"])
                if active() and mailbox == "drafts" and saved.get("id"):
                    # Send has committed: this draft no longer exists. Remove its
                    # row immediately, even if refreshing the mailbox is slow or fails.
                    row = message_rows.pop(str(saved["id"]), None)
                    if row is not None:
                        row.delete()
                close()
                ui.notify(text("state.sent"), color="positive")
                if active():
                    await load(reset=True)

            async def discard_or_restore():
                try:
                    restoring = saved.get("is_deleted")
                    await request(
                        "POST" if restoring else "DELETE",
                        "/drafts/" + saved["id"] + ("/restore" if restoring else ""),
                        headers={"If-Match": str(saved["version"])},
                    )
                except ApiError as error:
                    warn(error)
                    return
                close()
                if active():
                    await load(reset=True)

            with ui.row().classes("w-full items-center gap-2"):
                send_button = ui.button(
                    text("action.send"), icon="send", on_click=send_message
                ).props("no-caps").mark("messaging-send")
                send_button.disable()
                save_button = ui.button(
                    text("action.save_draft"), icon="save", on_click=save
                ).props("outline no-caps")
                if saved.get("id"):
                    ui.button(
                        text(
                            "action.restore"
                            if saved.get("is_deleted")
                            else "action.discard"
                        ),
                        on_click=discard_or_restore,
                    ).props("flat no-caps")
                ui.button(text("action.cancel"), on_click=close).props("flat no-caps")
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
        await validate()

    await load()

    async def refresh_live():
        if active() and content.visible:
            await load()

    return {
        "refresh": refresh_live,
        "open": lambda identity: show_message(identity, "inbox"),
    }
