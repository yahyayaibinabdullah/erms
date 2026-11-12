"""Per-client audit workspace and the shared entity-history dialogs.

The host supplies navigation destinations and shell entry; this module owns
filters, request revisions, immutable event presentation and dialog lifetimes.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from nicegui import ui

from .api_client import ErmsApiClient, ApiError
from .audit_actor_select import bind_audit_actor_select, actor_condition
from .audit_labels import audit_entity_type_label
from .capabilities import can_navigate
from .disposition.messages import text as disposition_text
from .event_labels import event_label
from .i18n_catalogue import render_message, render_message_plain
from .remote_select import RemoteSelect


def event_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def event_reference_value(event: dict[str, Any], side: str, field: str, value: Any) -> str:
    """Prefer the immutable readable identity captured with a new audit event."""
    references = (
        (event.get("metadata") or {})
        .get("reference_snapshots", {})
        .get(side, {})
    )
    snapshot = references.get(field) or {}
    if not snapshot:
        return event_value(value)
    primary = snapshot.get("code") or snapshot.get("name") or snapshot.get("title")
    secondary = snapshot.get("title") or snapshot.get("name") or snapshot.get("email")
    if secondary == primary:
        secondary = None
    identity = " — ".join(str(part) for part in (primary, secondary) if part)
    return identity or event_value(value)


def event_entity_identity(event: dict[str, Any]) -> tuple[str, str]:
    entity_type = event["entity_type"]
    if entity_type in ('disposition_job', 'disposition_task'):
        from .audit_labels import disposition_event_identity
        return disposition_event_identity(event)
    snapshot = event.get("after_state") or event.get("before_state") or {}
    if event.get("operation") == "EXPORT" and entity_type == "classification_scheme":
        snapshot = (event.get("metadata") or {}).get("scheme") or snapshot
    current = event.get("_current_entity") or event.get("_historical_entity") or {}

    if entity_type == "user_role_assignment":
        parties = (event.get("metadata") or {}).get("assignment_parties") or {}
        assigned_user = parties.get("user") or {}
        assigned_role = parties.get("role") or {}
        user_identity = assigned_user.get("name") or "Unknown user"
        if assigned_user.get("email"):
            user_identity += f" ({assigned_user['email']})"
        role_identity = " — ".join(
            str(part) for part in (assigned_role.get("code"), assigned_role.get("name"))
            if part
        ) or "Unknown role"
        return "Role assignment", f"{user_identity} → {role_identity}"

    value = lambda field: snapshot.get(field) or current.get(field)
    identities = {
        "aggregation": (value("aggregation_number"), value("title")),
        "record": (value("record_number"), value("title")),
        "digital_component": (value("file_name"), None),
        "org_unit": (value("code"), value("name")),
        "user": (value("name"), value("email")),
        "role": (value("code"), value("name")),
        "classification_scheme": (value("code"), value("title")),
        "classification": (value("code"), value("title")),
    }
    primary, secondary = identities.get(entity_type, (None, None))
    identity = " — ".join(str(value) for value in (primary, secondary) if value)
    entity_title = audit_entity_type_label(entity_type) if entity_type == "application_setting" else entity_type.replace('_', ' ').title()
    heading = render_message("webui.event_entity_identity.text.title_entity_id_3be1e8f8", title=entity_title, entity_id=event['entity_id'])
    return heading, identity


def hydrate_historical_audit_identities(events_list: list[dict[str, Any]]) -> None:
    """Reuse immutable snapshots within the result set without extra API calls."""
    identities: dict[tuple[str, int], dict[str, Any]] = {}
    for event in reversed(events_list):
        snapshot = event.get("after_state") or event.get("before_state")
        if snapshot:
            identities[(event["entity_type"], event["entity_id"])] = snapshot
    for event in events_list:
        event["_historical_entity"] = identities.get((event["entity_type"], event["entity_id"]))


def event_actor_identity(event: dict[str, Any]) -> tuple[str, str | None]:
    if event.get("actor_name"):
        return event["actor_name"], event.get("actor_email") or "No email address"
    actor_type = event.get("actor_type") or "unknown"
    if event.get("actor_user_id"):
        return "User identity was not captured", None
    labels = {
        "anonymous": render_message("webui.event_actor_identity.text.anonymous_actor_7be4bc7f"),
        "automated_process": render_message("webui.event_actor_identity.text.automated_process_0d4c2aac"),
        "user": render_message("webui.event_actor_identity.text.application_user_f9f45948"),
    }
    return labels.get(actor_type, actor_type.replace("_", " ").title()), None


@dataclass(frozen=True)
class AuditWorkspace:
    select_audit_trail: Callable[..., Awaitable[None]]
    show_entity_history: Callable[[str, dict[str, Any]], Awaitable[None]]
    render_event_timeline: Callable[[list[dict[str, Any]], Any], None]
    show_event_detail: Callable[[dict[str, Any]], None]
    navigate_to_event_entity: Callable[[dict[str, Any]], Awaitable[None]]
    can_open_event_entity: Callable[[dict[str, Any]], bool]


def build_audit_workspace(
    *, api: ErmsApiClient, table_container: Any,
    principal: Callable[[], dict[str, Any] | None],
    selected: Callable[[], bool], enter: Callable[[], None],
    error_message: Callable[[ApiError], str], format_timestamp: Callable[[Any], str],
    set_connection_status: Callable[[bool], None],
    can_open_settings: Callable[[], bool],
    open_settings: Callable[[dict[str, Any]], Awaitable[None]],
    open_destination: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> AuditWorkspace:
    """Build once for each root-page client; no state is shared between clients."""
    revision = 0

    def can_open_event_entity(event: dict[str, Any]) -> bool:
        if event.get("entity_type") == "application_setting":
            return can_open_settings()
        return event.get("entity_type") in {"aggregation", "record", "digital_component", "org_unit", "user", "role"}

    async def navigate_to_event_entity(event: dict[str, Any]) -> None:
        if event.get("entity_type") == "application_setting":
            await open_settings(event)
            return
        entity = event.get("_current_entity")
        if not entity:
            resources = {
                "aggregation": "aggregations", "record": "records",
                "digital_component": "digital-components", "org_unit": "org-units",
                "user": "users", "role": "roles",
                "classification_scheme": "classification-schemes",
                "classification": "classifications",
            }
            resource = resources.get(event["entity_type"])
            if not resource:
                ui.notify(render_message("webui.navigate_to_event_entity.notify.this_event_type_does_not_have_a_standalone_d2f6c8ef"), color="warning")
                return
            try:
                entity = await api.get(resource, event["entity_id"])
                event["_current_entity"] = entity
            except ApiError as error:
                if error.status_code == 404:
                    if event['entity_type'] in ('aggregation','record','digital_component'):
                        try:proof=await api.disposition_page(f"retained/{event['entity_type']}/{event['entity_id']}",audit=True)
                        except ApiError:proof=None
                        if proof:
                            from .disposition.destruction import retained_detail
                            await retained_detail(api=api,proof=proof,active=lambda:True,on_error=error_message,format_timestamp=format_timestamp)
                            return
                    ui.notify(render_message("webui.navigate_to_event_entity.notify.this_entity_no_longer_exists_its_historica_a20fef91"), color="warning")
                else:
                    ui.notify(error_message(error), color="negative", close_button=True)
                return
        origin_dialog = event.get("_origin_dialog")
        if origin_dialog:
            origin_dialog.close()
            await asyncio.sleep(0.15)
        await open_destination(event["entity_type"], entity)

    def show_event_detail(event: dict[str, Any]) -> None:
        disposition_event = event.get('display_presentation') == 'disposition'
        entity_heading, entity_identity = event_entity_identity(event)
        dialog = ui.dialog()
        before = event.get("before_state") or {}
        after = event.get("after_state") or {}
        changed = event.get("changed_fields") or sorted(set(before) | set(after))
        actor_name, actor_email = event_actor_identity(event)

        async def open_entity() -> None:
            dialog.close()
            await asyncio.sleep(0.05)
            await navigate_to_event_entity(event)

        with dialog, ui.card().classes("p-0 max-h-[calc(100vh-32px)]").style("width: 960px; max-width: calc(100vw - 32px)"):
            with ui.row().classes("w-full items-center px-5 pt-5"):
                ui.avatar(icon="history", color="blue-1", text_color="primary")
                with ui.column().classes("gap-0 grow"):
                    operation_heading = ui.label(event_label(event["operation"], event=event)).classes("text-xl font-semibold")
                    if not disposition_event:
                        operation_heading.tooltip(event["operation"])
                    ui.label(entity_heading).classes("text-sm text-slate-500")
                    if entity_identity:
                        ui.label(entity_identity).classes("text-sm font-medium text-slate-700 line-clamp-1")
                if can_open_event_entity(event):
                    ui.button(
                        render_message("webui.show_event_detail.button.open_entity_ef774537"), icon="open_in_new",
                        on_click=open_entity,
                    ).props("flat no-caps color=primary")
                ui.button(icon="close", on_click=dialog.close).props("flat round")
            with ui.column().classes("w-full px-5 pb-4 gap-4 overflow-y-auto"):
                with ui.row().classes("w-full gap-5 text-sm"):
                    with ui.column().classes("gap-0"):
                        ui.label(render_message("webui.show_event_detail.label.occurred_608bfcc8")).classes("component-meta-label")
                        ui.label(format_timestamp(event.get("occurred_at"))).classes("text-sm text-slate-700")
                    with ui.column().classes("gap-0 min-w-[220px]"):
                        ui.label(render_message("webui.show_event_detail.label.actor_43121a3e")).classes("component-meta-label")
                        ui.label(actor_name).classes("text-sm font-medium text-slate-700")
                        if actor_email:
                            ui.label(actor_email).classes("text-xs text-slate-500")
                    with ui.column().classes("gap-0"):
                        ui.label(render_message("webui.show_event_detail.label.source_c6457d34")).classes("component-meta-label")
                        ui.label(event.get("source") or "—").classes("text-sm text-slate-700")
                if event.get("reason") and event["operation"] not in ("DISPOSITION_BLOCKERS_DETECTED", "DISPOSITION_BLOCKERS_RESOLVED"):
                    with ui.card().classes("w-full bg-blue-50 shadow-none border border-blue-100"):
                        ui.label(render_message("webui.show_event_detail.label.change_reason_93b265ba")).classes("component-meta-label")
                        ui.label(event["reason"]).classes("text-sm")
                if disposition_event:
                    from .disposition.history import readable_event_fields
                    readable_event_fields(event, format_timestamp)
                elif changed:
                    ui.label(render_message("webui.show_event_detail.label.field_changes_252aeebc")).classes("font-semibold")
                    change_rows = [
                        {
                            "field": field.replace("_", " ").title(),
                            "before": event_reference_value(event, "before", field, before.get(field)),
                            "after": event_reference_value(event, "after", field, after.get(field)),
                        }
                        for field in changed
                    ]
                    change_table = ui.table(
                        columns=[
                            {"name": "field", "label": "Field", "field": "field", "align": "left"},
                            {"name": "before", "label": "Before", "field": "before", "align": "left"},
                            {"name": "after", "label": "After", "field": "after", "align": "left"},
                        ], rows=change_rows, row_key="field",
                    ).props("flat bordered wrap-cells hide-pagination").classes("w-full shrink-0")
                    for key in ("before", "after"):
                        change_table.add_slot(f"body-cell-{key}", f'<q-td :props="props"><div class="audit-value">{{{{ props.row.{key} }}}}</div></q-td>')
                if can_navigate("audit-trail", (principal() or {}).get("global_privileges", [])):
                    with ui.expansion(disposition_text('history_technical'), icon='code', value=False).classes('w-full'):
                        with ui.grid(columns=2).classes("w-full gap-3"):
                            for label, value in (
                                ("Request ID", event.get("request_id")),
                                ("Correlation ID", event.get("correlation_id")),
                                ("Transaction", event.get("transaction_id")),
                                ("Event ID", event.get("id")),
                            ):
                                with ui.column().classes("gap-0 min-w-0"):
                                    ui.label(label).classes("component-meta-label")
                                    ui.label(event_value(value)).classes("text-xs text-slate-600 break-all")
                        if disposition_event or event.get("metadata"):
                            ui.label(render_message("webui.show_event_detail.label.metadata_426a77f1")).classes("font-semibold")
                            ui.code(json.dumps(event if disposition_event else event["metadata"], ensure_ascii=False, indent=2, sort_keys=True, default=str)).classes("w-full text-xs")
        dialog.open()

    def render_event_timeline(events_list: list[dict[str, Any]], container: Any) -> None:
        container.clear()
        with container:
            if not events_list:
                with ui.column().classes("w-full items-center py-10 text-slate-400 gap-2"):
                    ui.icon("history_toggle_off").classes("text-4xl")
                    ui.label(render_message("webui.render_event_timeline.label.no_matching_events_bd2c227e"))
                return
            previous_correlation = None
            for event in events_list:
                actor_name, actor_email = event_actor_identity(event)
                correlation = event.get("correlation_id")
                if correlation and correlation != previous_correlation:
                    ui.label(render_message("webui.render_event_timeline.label.correlation_group_value_5807bee2", value=str(correlation)[:8])).classes(
                        "text-xs text-slate-400 font-medium mt-2"
                    ).tooltip(render_message("webui.render_event_timeline.tooltip.events_sharing_this_correlation_id_belong_6351adea"))
                previous_correlation = correlation
                operation = event_label(event["operation"], event=event)
                entity_heading, entity_identity = event_entity_identity(event)
                with ui.card().classes("audit-event w-full px-4 py-3"):
                    with ui.row().classes("w-full items-center no-wrap gap-3"):
                        ui.avatar(icon={"CREATE": "add", "UPDATE": "edit", "DELETE": "delete"}.get(event["operation"], "bolt"), color="blue-1", text_color="primary", size="36px")
                        with ui.column().classes("gap-0 grow min-w-0"):
                            operation_heading = ui.label(operation).classes("font-semibold")
                            if event.get('display_presentation') != 'disposition':
                                operation_heading.tooltip(event["operation"])
                            ui.label(entity_heading).classes("text-xs text-slate-500")
                            if entity_identity:
                                ui.label(entity_identity).classes("text-sm font-medium text-slate-700 line-clamp-1")
                            if event.get("changed_fields"):
                                ui.label(", ".join(field.replace("_", " ") for field in event["changed_fields"])).classes("text-xs text-slate-400 line-clamp-1")
                        with ui.column().classes("items-end gap-0"):
                            ui.label(format_timestamp(event["occurred_at"])).classes("text-xs font-medium text-slate-600")
                            ui.label(actor_name).classes("text-xs font-medium text-slate-600")
                            if actor_email:
                                ui.label(actor_email).classes("text-xs text-slate-400")
                            ui.label(event.get("source", render_message("webui.render_event_timeline.label.unknown_509e35f5"))).classes("text-xs text-slate-400")
                        if can_open_event_entity(event):
                            ui.button(
                                icon="open_in_new",
                                on_click=lambda _, item=event: navigate_to_event_entity(item),
                            ).props("flat round dense color=primary").props(
                                f"aria-label={render_message_plain('webui.render_event_timeline.tooltip.open_current_entity_208e2a65')!r}"
                            ).tooltip(render_message("webui.render_event_timeline.tooltip.open_current_entity_208e2a65"))
                        ui.button(
                            icon="chevron_right",
                            on_click=lambda _, item=event: show_event_detail(item),
                        ).props("flat round dense color=blue-grey").tooltip(render_message("webui.render_event_timeline.tooltip.view_audit_details_74f728b6"))

    async def show_entity_history(resource: str, entity: dict[str, Any]) -> None:
        page_size = 25
        try:
            history = await api.history(resource, entity["id"], limit=page_size + 1, offset=0)
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return
        name = entity.get("title") or entity.get("name") or entity.get("file_name") or render_message("webui.show_entity_history.text.id_56b4dfc9", id=entity['id'])
        dialog = ui.dialog()
        offset = 0
        has_next = False
        loading = False
        with dialog, ui.card().classes("p-0 max-h-[calc(100vh-32px)]").style("width: 820px; max-width: calc(100vw - 32px)"):
            with ui.row().classes("w-full items-center px-5 py-4 border-b"):
                ui.avatar(icon="manage_history", color="blue-1", text_color="primary")
                with ui.column().classes("gap-0 grow min-w-0"):
                    ui.label(render_message("webui.show_entity_history.label.event_history_670b1156")).classes("text-xl font-semibold")
                    ui.label(name).classes("text-sm text-slate-500 line-clamp-1")
                event_range = ui.badge(color="primary").classes("entity-history-range").props("outline dir=ltr")
                ui.button(icon="close", on_click=dialog.close).props("flat round")
            with ui.row().classes("entity-history-pager w-full justify-end px-5 gap-2") as pager:
                previous = ui.button(render_message("relationships.ui.previous")).classes("entity-history-previous").props("flat dense no-caps")
                following = ui.button(render_message("relationships.ui.next")).classes("entity-history-next").props("flat dense no-caps")
            timeline = ui.column().classes("w-full gap-2 px-5 pb-5 overflow-y-auto")

        def update_controls() -> None:
            pager.set_visibility(offset > 0 or has_next)
            previous.set_enabled(not loading and offset > 0)
            following.set_enabled(not loading and has_next)

        def render_page(rows: list[dict[str, Any]]) -> None:
            nonlocal has_next
            has_next = len(rows) > page_size
            events = [{**event, "_current_entity": entity, "_origin_dialog": dialog}
                      for event in rows[:page_size]]
            event_range.text = (
                f"{offset + 1}–{offset + len(events)}" if events and (offset or has_next)
                else str(len(events))
            )
            render_event_timeline(events, timeline)
            update_controls()

        async def move_page(delta: int) -> None:
            nonlocal offset, loading
            target = offset + delta * page_size
            if loading or not dialog.value or target < 0 or (delta > 0 and not has_next):
                return
            loading = True
            update_controls()
            try:
                rows = await api.history(resource, entity["id"], limit=page_size + 1, offset=target)
                if dialog.value and not dialog.is_deleted:
                    offset = target
                    render_page(rows)
            except ApiError as error:
                if dialog.value and not dialog.is_deleted:
                    ui.notify(error_message(error), color="negative", close_button=True)
            finally:
                loading = False
                if dialog.value and not dialog.is_deleted:
                    update_controls()

        previous.on_click(lambda: move_page(-1))
        following.on_click(lambda: move_page(1))
        render_page(history)
        dialog.open()

    async def select_audit_trail(*, initial_entity_type: str | None = None) -> None:
        nonlocal revision
        revision += 1
        audit_page_revision = revision

        def audit_page_is_current() -> bool:
            return (selected() and revision == audit_page_revision)

        enter()
        with table_container:
            with ui.column().classes("w-full p-5 gap-4"):
                with ui.card().classes("w-full shadow-none border border-slate-200 p-4"):
                    ui.label(render_message("webui.select_audit_trail.label.filter_events_5327c240")).classes("font-semibold")
                    with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3"):
                        type_filter = ui.select(
                            {initial_entity_type: audit_entity_type_label(initial_entity_type)}
                            if initial_entity_type else {},
                            value=initial_entity_type,
                            label=render_message("webui.select_audit_trail.select.entity_type_3b68096e"), clearable=True,
                        ).props("outlined dense use-input options-dense").classes("w-full")
                        operation_filter = ui.select(
                            [],
                            label=render_message("webui.select_audit_trail.select.operation_c3539ad5"), clearable=True,
                        ).props("outlined dense use-input options-dense").classes("w-full")
                        source_filter = ui.select(
                            [], label=render_message("webui.select_audit_trail.select.source_47e0b469"), clearable=True,
                        ).props("outlined dense use-input options-dense").classes("w-full")
                        actor_filter = ui.select(
                            [], label=render_message("webui.select_audit_trail.select.actor_type_1e26e211"), clearable=True,
                        ).props("outlined dense use-input options-dense").classes("w-full")
                        with ui.column().classes("w-full sm:col-span-2 gap-1"):
                            actor_identity_filter = RemoteSelect(
                                {}, label=render_message("audit.filter.actor_identity"),
                                with_input=True, clearable=True,
                            ).props("outlined dense options-dense input-debounce=0").classes("w-full remote-relationship-select")
                            actor_identity_filter.props["placeholder"] = render_message("audit.filter.actor_identity_hint")
                            actor_suggestion_status = ui.label(
                                render_message("audit.filter.actor_suggestions_hint")
                            ).classes("text-xs text-slate-500")
                        from_filter = ui.input(render_message("webui.select_audit_trail.input.from_0cee5608")).props("outlined dense type=datetime-local").classes("w-full")
                        until_filter = ui.input(render_message("webui.select_audit_trail.input.until_dafbbcb5")).props("outlined dense type=datetime-local").classes("w-full")
                        entity_id_filter = ui.number(render_message("webui.select_audit_trail.number.entity_id_39367eca"), min=1, format="%.0f").props("outlined dense clearable").classes("w-full")
                        correlation_filter = ui.input(render_message("webui.select_audit_trail.input.correlation_id_e6872415")).props("outlined dense clearable").classes("w-full")
                    with ui.row().classes("w-full justify-end"):
                        reset_button = ui.button(render_message("audit.filter.clear"), icon="filter_alt_off").props("flat no-caps")
                        refresh_button = ui.button(render_message("webui.select_audit_trail.button.apply_filters_bf49489c"), icon="filter_alt").props("unelevated no-caps")
                with ui.row().classes("w-full items-center gap-2"):
                    result_summary = ui.label().classes("text-sm text-slate-500 grow")
                    previous_button = ui.button(render_message("webui.select_audit_trail.button.previous_928715e5"), icon="chevron_left").props("flat dense no-caps")
                    next_button = ui.button(render_message("webui.select_audit_trail.button.next_4982f418"), icon="chevron_right").props("flat dense no-caps")
                    previous_button.disable()
                    next_button.disable()
                result_cap_notice = ui.label().classes("text-sm text-amber-700")
                result_cap_notice.set_visibility(False)
                results_container = ui.column().classes("w-full gap-2")

        page = {"offset": 0, "size": 50, "total": 0, "where": None, "loading": False}

        actor_search, selected_actor, reset_actor = bind_audit_actor_select(
            actor_identity_filter, actor_suggestion_status, api=api,
            active=audit_page_is_current,
            scope=lambda: {"entity_type": type_filter.value, "actor_type": actor_filter.value},
            on_error=lambda error: ui.notify(error_message(error), color="negative", close_button=True),
        )

        try:
            filter_options = await api.event_history_filter_options()
            if not audit_page_is_current():
                return
            type_filter.options = {
                value: audit_entity_type_label(value)
                for value in filter_options["entity_types"]
            }
            # Keep the shortcut's scope even before any matching event exists.
            if initial_entity_type:
                type_filter.options.setdefault(
                    initial_entity_type, audit_entity_type_label(initial_entity_type)
                )
            operation_filter.options = {code: event_label(code) for code in filter_options["operations"]}
            source_filter.options = filter_options["sources"]
            actor_filter.options = filter_options["actor_types"]
            for control in (
                type_filter, operation_filter, source_filter, actor_filter,
            ):
                control.update()
        except ApiError as error:
            if audit_page_is_current() and error.status_code != 401:
                ui.notify(
                    render_message("webui.select_audit_trail.notify.could_not_load_audit_operation_filters_err_1e52391b", error_message=error_message(error)),
                    color="warning",
                    close_button=True,
                )

        def read_audit_filters() -> dict[str, Any] | None:
            conditions: list[dict[str, Any]] = []
            for field, operator, value in (
                ("entity_type", "eq", type_filter.value),
                ("operation", "eq", operation_filter.value),
                ("source", "eq", source_filter.value),
                ("actor_type", "eq", actor_filter.value),
                ("entity_id", "eq", int(entity_id_filter.value) if entity_id_filter.value else None),
                ("correlation_id", "eq", (correlation_filter.value or "").strip()),
                ("occurred_at", "gte", from_filter.value),
                ("occurred_at", "lte", until_filter.value),
            ):
                if value not in (None, ""):
                    conditions.append({"field": field, "operator": operator, "value": value})
            actor = selected_actor()
            actor_identity = actor_search["query"]
            if actor:
                conditions.append(actor_condition(actor))
            elif actor_identity:
                conditions.append({"or": [
                    {"field": field, "operator": "contains_ci", "value": actor_identity}
                    for field in ("actor_name", "actor_email")
                ]})
            if not conditions:
                return None
            return conditions[0] if len(conditions) == 1 else {"and": conditions}

        async def load_audit_events(offset: int, where: dict[str, Any] | None) -> None:
            if not audit_page_is_current() or results_container.is_deleted or page["loading"]:
                return
            page["loading"] = True
            refresh_button.props("loading disable")
            payload: dict[str, Any] = {
                "sort": [{"field": "occurred_at", "direction": "desc"}, {"field": "id", "direction": "desc"}],
                "limit": page["size"], "offset": offset,
            }
            if where is not None:
                payload["where"] = where
            try:
                response = await api.search_request("event-history", payload)
                if not audit_page_is_current() or results_container.is_deleted:
                    return
                events_list = response["items"]
                hydrate_historical_audit_identities(events_list)
                page.update(offset=offset, where=where, total=response["total"])
                result_cap_notice.set_visibility(bool(response.get("truncated")))
                if response.get("truncated"):
                    result_cap_notice.text = render_message("audit.filter.results_capped", limit=response["result_cap"])
                first = page["offset"] + 1 if events_list else 0
                last = page["offset"] + len(events_list)
                result_summary.text = render_message("webui.load_audit_events.text.showing_first_last_of_total_matching_event_a86705af", first=first, last=last, total=page['total'])
                if page["offset"] > 0:
                    previous_button.enable()
                else:
                    previous_button.disable()
                if last < page["total"]:
                    next_button.enable()
                else:
                    next_button.disable()
                render_event_timeline(events_list, results_container)
                set_connection_status(True)
            except ApiError as error:
                if audit_page_is_current() and not results_container.is_deleted:
                    ui.notify(error_message(error), color="negative", close_button=True)
            finally:
                page["loading"] = False
                if audit_page_is_current() and not results_container.is_deleted:
                    refresh_button.props(remove="loading disable")

        async def apply_filters() -> None:
            await load_audit_events(0, read_audit_filters())

        async def previous_page() -> None:
            if page["offset"] > 0:
                await load_audit_events(max(0, page["offset"] - page["size"]), page["where"])

        async def next_page() -> None:
            if page["offset"] + page["size"] < page["total"]:
                await load_audit_events(page["offset"] + page["size"], page["where"])

        async def reset_filters() -> None:
            if page["loading"]:
                return
            for control in (operation_filter, source_filter, actor_filter,
                            from_filter, until_filter,
                            entity_id_filter, correlation_filter):
                control.value = None
            reset_actor()
            type_filter.value = initial_entity_type
            await apply_filters()

        reset_button.on("click", reset_filters)
        refresh_button.on("click", apply_filters)
        previous_button.on("click", previous_page)
        next_button.on("click", next_page)
        await apply_filters()

    return AuditWorkspace(
        select_audit_trail=select_audit_trail, show_entity_history=show_entity_history,
        render_event_timeline=render_event_timeline, show_event_detail=show_event_detail,
        navigate_to_event_entity=navigate_to_event_entity, can_open_event_entity=can_open_event_entity,
    )
