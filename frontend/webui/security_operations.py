"""Security oversight periods, event signals, reconciliation and destination links."""
from __future__ import annotations
import asyncio
from typing import Any
from .api_client import ApiError
from nicegui import background_tasks
from datetime import datetime
from .authorization_ui import decision_code_label
from frontend.webui.event_labels import event_label
from .i18n_catalogue import render_message
from .identity_presentation import render_user_avatar
from nicegui import ui

SECURITY_EVENT_PAGE_SIZE = 10
DENIAL_GROUP_PAGE_SIZE = 10

def build_security_operations(
    *, add_button, add_record_button, aggregation_mode_bar, api, enter_security_operations, format_timestamp, get_resource, guidance, localized_lifecycle_value, open_aggregation, page_client, principal, register_navigation, search_bar, select_classification_workspace, select_organization_unit_details, select_record_details, select_role_details, select_user_details, show_api_error, show_authenticated_view, subtitle, table_container, title,
):
    async def select_security_operations() -> None:
        register_navigation("security-operations", "Security operations")
        show_authenticated_view()
        enter_security_operations()
        title.text = render_message("webui.select_security_operations.text.security_operations_f2690c64"); subtitle.text = render_message("webui.select_security_operations.text.sanitized_security_signals_and_access_cont_960ec487")
        search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False); add_record_button.set_visibility(False); guidance.text = ""
        table_container.clear()
        current_principal = principal()
        privileges = set((current_principal or {}).get("global_privileges", []))
        load_revision = 0
        with table_container, ui.column().classes("w-full p-5 gap-5"):
            with ui.row().classes("w-full items-center gap-3"):
                ui.icon("monitor_heart", color="primary", size="30px")
                with ui.column().classes("gap-0 grow"):
                    window_title = ui.label(render_message("webui.select_security_operations.label.last_24_hours_fa33cd89")).classes("text-xl font-semibold")
                    ui.label(render_message("webui.select_security_operations.label.aggregated_signals_contain_no_protected_re_f7ff6ccb")).classes("text-sm text-slate-500")
                period = ui.select(
                    {"24h": render_message("webui.select_security_operations.select.last_24_hours_bb3b461d"), "week": render_message("webui.select_security_operations.select.last_week_b01c00d9"), "month": render_message("webui.select_security_operations.select.last_month_c2116839"), "custom": render_message("webui.select_security_operations.select.custom_4d95447c")},
                    value="24h", label=render_message("webui.select_security_operations.select.period_ed31c1a0"),
                ).props("outlined dense options-dense").classes("w-44")
                refresh = ui.button(render_message("webui.select_security_operations.button.refresh_aa2c487e"), icon="refresh").props("outline no-caps")
            custom_range = ui.row().classes("w-full items-end gap-3")
            with custom_range:
                range_start = ui.input(render_message("webui.select_security_operations.input.from_a135a152")).props("outlined dense type=date").classes("w-52")
                range_end = ui.input(render_message("webui.select_security_operations.input.through_b5ed408a")).props("outlined dense type=date").classes("w-52")
                apply_range = ui.button(render_message("webui.select_security_operations.button.apply_range_53faab3c"), icon="date_range").props("unelevated no-caps")
            custom_range.set_visibility(False)
            content = ui.column().classes("w-full gap-5")

        def view_is_current() -> bool:
            return (
                get_resource() == "security-operations"
                and not content.is_deleted
                and principal() is current_principal
            )

        def custom_iso(value: str | None, *, end: bool) -> str | None:
            if not value:
                return None
            parsed = datetime.fromisoformat(value).astimezone()
            if end:
                parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
            else:
                parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
            return parsed.isoformat()

        async def load_security_operations() -> None:
            with page_client:
                await render_security_operations()

        async def render_security_operations() -> None:
            nonlocal load_revision
            # Resolve explanations in the current session language, never at import time.
            security_event_help = {
                "AUTHORIZATION_DENIED": render_message("webui.module.text.an_operation_was_refused_because_one_or_mo_8a8c328d"),
                "AUTHENTICATION_FAILED": render_message("webui.module.text.a_sign_in_attempt_failed_repeated_failures_9063b5ad"),
                "ACCOUNT_LOCKED": render_message("webui.module.text.an_account_was_locked_after_reaching_the_c_9b0a2ea9"),
                "INFORMATION_GOVERNANCE_BYPASS_USED": render_message("webui.module.text.a_qualifying_governance_role_bypassed_the_b9e69c3c"),
                "ACCESS_EXPLANATION_VIEWED": render_message("webui.module.text.an_authorized_examiner_inspected_why_anoth_ff54a75d"),
                "SECURITY_LEVEL_CHANGED": render_message("webui.module.text.a_resource_security_level_changed_45527425"),
                "SECURITY_LEVEL_UPGRADED": render_message("webui.module.text.a_resource_was_raised_to_a_more_restrictiv_267fec56"),
                "SECURITY_LEVEL_DOWNGRADED": render_message("webui.module.text.a_resource_was_lowered_to_a_less_restricti_33c49609"),
                "ACL_REPLACED": render_message("webui.module.text.a_resource_s_local_access_control_list_was_9401ad98"),
                "DEFAULT_CHILD_AGGREGATION_ACL_REPLACED": render_message("webui.module.text.the_default_acl_inherited_by_child_aggrega_f12c6a28"),
                "DEFAULT_CHILD_RECORD_ACL_REPLACED": render_message("webui.module.text.the_default_acl_inherited_by_child_records_b8435ae9"),
                "PROFILE_PRIVILEGES_REPLACED": render_message("webui.module.text.the_complete_privilege_set_attached_to_a_p_8355d82e"),
                "PROFILE_ASSIGNED": render_message("webui.module.text.a_role_was_assigned_a_different_authorizat_a7a05cad"),
                "GOVERNANCE_ROLE_CHANGED": render_message("webui.module.text.a_role_s_information_governance_designatio_118a4087"),
            }

            authorization_denial_help = (
                render_message("webui.module.text.these_are_operations_refused_by_the_author_9f71f790")
            )
            mode = period.value or "24h"
            hours = {"24h": 24, "week": 24 * 7, "month": 24 * 30}.get(mode, 24)
            start_date = range_start.value if mode == "custom" else None
            end_date = range_end.value if mode == "custom" else None
            if mode == "custom" and (not start_date or not end_date):
                ui.notify(render_message("webui.load_security_operations.notify.select_both_dates_for_the_custom_range_c8117eee"), color="warning")
                return
            load_revision += 1
            revision = load_revision
            summary_request = api.security_summary(
                hours=hours,
                start_at=custom_iso(start_date, end=False),
                end_at=custom_iso(end_date, end=True),
                recent_event_limit=SECURITY_EVENT_PAGE_SIZE,
                denial_group_limit=DENIAL_GROUP_PAGE_SIZE + 1,
            )
            reconciliation = None
            if "authorization.administer" in privileges:
                summary, reconciliation = await asyncio.gather(
                    summary_request, api.security_reconciliation(),
                )
            else:
                summary = await summary_request
            if not view_is_current() or revision != load_revision or period.value != mode:
                return
            window_title.text = {
                "24h": render_message("webui.load_security_operations.text.last_24_hours_42c47f2c"), "week": render_message("webui.load_security_operations.text.last_week_0f602f5d"), "month": render_message("webui.load_security_operations.text.last_month_1df4669b"),
                "custom": render_message("webui.load_security_operations.text.value_through_value_2_8da1ebd6", value=start_date, value_2=end_date),
            }[mode]
            content.clear()
            with content:
                full_privilege_roles = summary.get("full_privilege_roles", [])
                if full_privilege_roles:
                    with ui.card().classes(
                        "w-full shadow-none border border-amber-300 bg-amber-50 p-4 gap-3"
                    ):
                        with ui.row().classes("w-full items-start gap-3"):
                            ui.icon("warning_amber", color="amber-9", size="26px").classes(
                                "mt-0.5 shrink-0"
                            )
                            with ui.column().classes("gap-1 grow"):
                                ui.label(
                                    render_message("webui.load_security_operations.label.roles_have_profiles_containing_every_syste_c0e25901")
                                ).classes("font-semibold text-amber-10")
                                ui.label(
                                    render_message("webui.load_security_operations.label.each_role_below_is_assigned_a_profile_that_b60ce009")
                                ).classes("text-sm leading-6 text-amber-10")
                        with ui.column().classes("w-full gap-1 pl-9"):
                            for affected_role in full_privilege_roles:
                                with ui.row().classes("w-full items-center gap-2"):
                                    ui.icon("badge", size="18px").classes("text-amber-9")
                                    ui.label(
                                        render_message("webui.load_security_operations.label.code_name_10bd8f14", code=affected_role['code'], name=affected_role['name'])
                                    ).classes("grow text-sm font-medium")
                                    ui.badge(
                                        render_message("webui.load_security_operations.badge.profile_code_profile_name_119cb2e7", profile_code=affected_role['profile_code'], profile_name=affected_role['profile_name']),
                                        color=(
                                            "warning" if affected_role["is_builtin_bootstrap_profile"]
                                            else "amber-8"
                                        ),
                                    ).props("outline")
                                    ui.badge(
                                        localized_lifecycle_value(affected_role["status"]),
                                        color="warning",
                                    ).props("outline")
                                    if "organization.administer" in privileges:
                                        ui.button(
                                            icon="badge",
                                            on_click=lambda _, role_id=affected_role["id"]: select_role_details(role_id),
                                        ).props("flat round dense color=primary").tooltip(
                                            render_message("webui.load_security_operations.tooltip.open_role_92d6ce18")
                                        )

                with ui.grid(columns=2).classes("w-full gap-4"):
                    security_icon = "security"
                    denial_icon = "gpp_bad"
                    security_operation_facts = (
                        (summary["total_security_events"], render_message("webui.load_security_operations.text.security_events_a38a6da1"), security_icon, render_message("webui.load_security_operations.text.recognized_authentication_authorization_cl_b866a4b5")),
                        (summary["total_denials"], render_message("webui.load_security_operations.text.authorization_denials_09e48996"), denial_icon, authorization_denial_help),
                    )
                    for value, label, icon, help_text in security_operation_facts:
                        with ui.card().classes("shadow-none border border-slate-200 p-4 gap-1"):
                            with ui.row().classes("items-center gap-3"):
                                ui.icon(icon, color="primary")
                                ui.label(str(value)).classes("text-3xl font-semibold")
                            ui.label(label).classes("font-medium")
                            ui.label(help_text).classes("text-sm text-slate-500")

                ui.label(render_message("webui.load_security_operations.label.event_signals_4567e82a")).classes("text-lg font-semibold")
                ui.label(render_message("webui.load_security_operations.label.counts_by_security_operation_with_the_most_b43974c6")).classes("text-sm text-slate-500 -mt-4")
                if not summary["event_counts"]:
                    ui.label(render_message("webui.load_security_operations.label.no_security_events_in_this_period_c672277b")).classes("text-sm text-slate-400")
                for item in summary["event_counts"]:
                    with ui.grid(columns="minmax(220px, 1fr) minmax(320px, 2fr) 80px 170px").classes("w-full items-center gap-3 border-b border-slate-100 py-3"):
                        ui.label(event_label(item["operation"])).classes("font-medium").tooltip(item["operation"])
                        ui.label(security_event_help.get(item["operation"], render_message("webui.load_security_operations.label.security_relevant_activity_recorded_in_the_993f1e3d"))).classes("text-sm text-slate-500")
                        with ui.row().classes("w-full justify-center"):
                            ui.badge(str(item["count"]), color="primary").props("outline")
                        ui.label(format_timestamp(item["last_seen_at"])).classes("text-xs text-slate-500 text-right")

                ui.label(render_message("webui.load_security_operations.label.recent_security_events_1b6b711e")).classes("text-lg font-semibold mt-2")
                ui.label(
                    render_message("webui.load_security_operations.label.the_most_recent_security_related_events_in_649bc0ac")
                ).classes("text-sm text-slate-500 -mt-4")
                # The history view redacts protected details while retaining the event
                # rows, so the summary already has the total for this same window.
                event_total = summary["total_security_events"]
                event_offset = 0
                event_page_loading = False
                security_event_host = ui.element("div").classes(
                    "governance-card-list w-full"
                )
                with ui.row().classes("w-full items-center justify-end gap-2"):
                    security_event_page_label = ui.label().classes(
                        "text-sm text-slate-500"
                    )
                    security_event_previous = ui.button(
                        render_message("webui.load_security_operations.button.previous_49e3a635"), icon="chevron_left",
                    ).props("flat dense no-caps")
                    security_event_next = ui.button(
                        render_message("webui.load_security_operations.button.next_1b5d6dc7"), icon="chevron_right",
                    ).props("flat dense no-caps")

                async def open_security_event_target(row: dict[str, Any]) -> None:
                    entity_type = row.get("entity_type")
                    entity_id = row.get("entity_id")
                    try:
                        if entity_type == "aggregation":
                            await open_aggregation(await api.get("aggregations", entity_id))
                        elif entity_type == "record":
                            await select_record_details(entity_id)
                        elif entity_type == "org_unit":
                            await select_organization_unit_details(entity_id)
                        elif entity_type == "role":
                            await select_role_details(entity_id)
                        elif entity_type == "user":
                            await select_user_details(entity_id)
                        elif entity_type == "classification_scheme":
                            await select_classification_workspace(
                                initial_scheme_id=entity_id,
                            )
                        elif entity_type == "classification":
                            classification = await api.get("classifications", entity_id)
                            await select_classification_workspace(
                                initial_scheme_id=classification["classification_scheme_id"],
                                initial_classification_id=entity_id,
                            )
                    except ApiError as error:
                        if error.status_code == 404:
                            ui.notify(
                                render_message("webui.open_security_event_target.notify.this_target_no_longer_exists_2815aee4"), color="warning",
                            )
                        else:
                            show_api_error(error)

                def render_security_event_cards(items: list[dict[str, Any]]) -> None:
                    page_rows = [{
                        **item,
                        "actor": item.get("actor_name") or item.get("actor_email") or item.get("actor_type"),
                        "when": format_timestamp(item["occurred_at"]),
                        "signal": event_label(item["operation"]),
                        "decision": decision_code_label(item.get("decision_code")),
                    } for item in items]
                    security_event_host.clear()
                    with security_event_host:
                        if not page_rows:
                            ui.label(render_message("webui.render_security_event_cards.label.no_recent_security_events_in_this_period_6d8fd436")).classes(
                                "w-full text-center text-slate-400 py-8"
                            )
                        for row in page_rows:
                            with ui.card().classes(
                                "governance-list-card governance-custody-assignment-card shadow-none"
                            ):
                                with ui.row().classes("w-full items-center no-wrap gap-3"):
                                    with ui.element("div").classes("governance-card-icon"):
                                        ui.icon("security", size="18px")
                                    ui.label(row["signal"]).classes(
                                        "font-semibold grow min-w-0"
                                    ).tooltip(row["operation"])
                                    ui.label(row["when"]).classes(
                                        "text-xs text-slate-500 whitespace-nowrap"
                                    )
                                with ui.element("div").classes(
                                    "governance-list-facts security-event-facts"
                                ):
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(render_message("webui.render_security_event_cards.label.account_actor_0d591ef2")).classes(
                                            "detail-field-label"
                                        )
                                        if row.get("actor_user_id"):
                                            actor_control = ui.row().classes(
                                                "items-center no-wrap gap-2 min-w-0 "
                                                "cursor-pointer text-primary"
                                            ).on(
                                                "click",
                                                lambda _, user_id=row["actor_user_id"]:
                                                    select_user_details(user_id),
                                            )
                                            actor_control.tooltip(render_message("webui.render_security_event_cards.tooltip.open_user_13542730"))
                                            with actor_control:
                                                render_user_avatar({
                                                    "id": row["actor_user_id"],
                                                    "name": row.get("actor_name"),
                                                    "email": row.get("actor_email"),
                                                }, size="26px")
                                                ui.label(row.get("actor") or "—").classes(
                                                    "text-sm truncate min-w-0"
                                                )
                                        else:
                                            with ui.row().classes(
                                                "items-center no-wrap gap-2 min-w-0"
                                            ):
                                                ui.icon("smart_toy", size="18px").classes(
                                                    "text-slate-400"
                                                )
                                                ui.label(row.get("actor") or "—").classes(
                                                    "text-sm truncate min-w-0"
                                                )
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(render_message("webui.render_security_event_cards.label.target_f4f7d136")).classes("detail-field-label")
                                        target_value = row.get("entity_label") or "—"
                                        target_supported = (
                                            not row.get("redacted")
                                            and row.get("entity_type") in {
                                                "aggregation", "record", "org_unit", "role",
                                                "user", "classification", "classification_scheme",
                                            }
                                        )
                                        target_label = ui.label(target_value).classes(
                                            "text-sm truncate w-full "
                                            + ("cursor-pointer text-primary" if target_supported else "")
                                        ).tooltip(target_value)
                                        if target_supported:
                                            target_label.on(
                                                "click",
                                                lambda _, item=row: open_security_event_target(item),
                                            )
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(render_message("webui.render_security_event_cards.label.decision_447868a3")).classes("detail-field-label")
                                        decision_value = row.get("decision") or "—"
                                        decision_label = ui.label(decision_value).classes(
                                            "text-sm truncate w-full"
                                        )
                                        if row.get("decision_code"):
                                            decision_label.tooltip(
                                                render_message("webui.render_security_event_cards.tooltip.technical_code_decision_code_f5bc7779", decision_code=row['decision_code'])
                                            )
                    start = event_offset + 1 if page_rows else 0
                    end = event_offset + len(page_rows)
                    security_event_page_label.text = (
                        render_message("webui.render_security_event_cards.text.start_end_of_event_row_count_7e8f78d3", start=start, end=end, event_row_count=event_total)
                    )
                    security_event_page_label.update()

                def update_security_event_controls() -> None:
                    security_event_previous.set_enabled(not event_page_loading and event_offset > 0)
                    security_event_next.set_enabled(
                        not event_page_loading and event_offset + SECURITY_EVENT_PAGE_SIZE < event_total,
                    )

                def event_page_is_current() -> bool:
                    return view_is_current() and not security_event_host.is_deleted

                async def load_security_event_page(offset: int) -> None:
                    nonlocal event_offset, event_page_loading
                    if event_page_loading or not event_page_is_current() or not 0 <= offset < event_total:
                        return
                    event_page_loading = True
                    update_security_event_controls()
                    try:
                        items = await api.security_events(
                            start_at=summary["window_start"], end_at=summary["window_end"],
                            limit=SECURITY_EVENT_PAGE_SIZE, offset=offset,
                        )
                        if event_page_is_current():
                            event_offset = offset
                            render_security_event_cards(items)
                    except ApiError as error:
                        if event_page_is_current():
                            show_api_error(error)
                    finally:
                        event_page_loading = False
                        if event_page_is_current():
                            update_security_event_controls()

                async def previous_security_events() -> None:
                    await load_security_event_page(event_offset - SECURITY_EVENT_PAGE_SIZE)

                async def next_security_events() -> None:
                    await load_security_event_page(event_offset + SECURITY_EVENT_PAGE_SIZE)

                security_event_previous.on("click", previous_security_events)
                security_event_next.on("click", next_security_events)
                render_security_event_cards(summary["recent_events"])
                update_security_event_controls()

                ui.label(render_message("webui.load_security_operations.label.denial_monitoring_9ac48ee1")).classes("text-lg font-semibold mt-2")
                ui.label(authorization_denial_help).classes("text-sm text-slate-500 -mt-4")
                denial_host = ui.column().classes("security-denial-groups w-full")
                with ui.row().classes("w-full items-center justify-end gap-2") as denial_pager:
                    denial_previous = ui.button(
                        render_message("relationships.ui.previous"),
                    ).classes("security-denial-previous").props("flat dense no-caps")
                    denial_next = ui.button(
                        render_message("relationships.ui.next"),
                    ).classes("security-denial-next").props("flat dense no-caps")
                denial_offset = 0
                denial_more = False
                denial_loading = False

                def update_denial_controls() -> None:
                    denial_pager.set_visibility(denial_offset > 0 or denial_more)
                    denial_previous.set_enabled(not denial_loading and denial_offset > 0)
                    denial_next.set_enabled(not denial_loading and denial_more)

                def render_denial_page(items: list[dict[str, Any]]) -> None:
                    nonlocal denial_more
                    denial_more = len(items) > DENIAL_GROUP_PAGE_SIZE
                    denial_host.clear()
                    with denial_host:
                        if not items:
                            ui.label(render_message("webui.load_security_operations.label.no_authorization_denials_occurred_in_this_3d7c10a2")).classes("text-sm text-positive")
                        for item in items[:DENIAL_GROUP_PAGE_SIZE]:
                            with ui.row().classes("security-denial-group w-full items-center gap-3 border-b border-slate-100 py-3"):
                                ui.label(item["decision_code"].replace("_", " ").title()).classes("font-medium")
                                ui.label(item["required_privilege"]).classes("grow text-sm text-slate-500")
                                ui.badge(str(item["count"]), color="negative").props("outline")
                            ui.label(render_message("webui.load_security_operations.label.review_the_recent_events_above_or_open_the_dfa372aa")).classes("text-sm text-slate-500")
                    update_denial_controls()

                def denial_page_is_current() -> bool:
                    return view_is_current() and not denial_host.is_deleted

                async def move_denial_page(delta: int) -> None:
                    nonlocal denial_offset, denial_loading
                    offset = denial_offset + delta * DENIAL_GROUP_PAGE_SIZE
                    if denial_loading or not denial_page_is_current() or offset < 0 or (delta > 0 and not denial_more):
                        return
                    denial_loading = True
                    update_denial_controls()
                    try:
                        items = await api.security_denial_groups(
                            start_at=summary["window_start"], end_at=summary["window_end"],
                            limit=DENIAL_GROUP_PAGE_SIZE + 1, offset=offset,
                        )
                        if denial_page_is_current():
                            denial_offset = offset
                            render_denial_page(items)
                    except ApiError as error:
                        if denial_page_is_current():
                            show_api_error(error)
                    finally:
                        denial_loading = False
                        if denial_page_is_current():
                            update_denial_controls()

                denial_previous.on_click(lambda: move_denial_page(-1))
                denial_next.on_click(lambda: move_denial_page(1))
                render_denial_page(summary["denial_groups"])

                if reconciliation is not None:
                    ui.separator()
                    ui.label(render_message("webui.load_security_operations.label.administrative_access_and_security_level_c_6d5dbfc3")).classes("text-lg font-semibold")
                    ui.label(
                        render_message("webui.load_security_operations.label.checks_that_at_least_one_active_person_can_a8d39836")
                    ).classes("text-sm text-slate-500 -mt-4")
                    hierarchy_count = reconciliation["hierarchy_violation_count"]
                    with ui.row().classes("w-full items-center gap-3 rounded-lg border p-3 " + ("border-red-200 bg-red-50" if hierarchy_count else "border-green-200 bg-green-50")):
                        ui.icon("warning" if hierarchy_count else "check_circle", color="negative" if hierarchy_count else "positive")
                        ui.label(render_message("webui.load_security_operations.label.hierarchy_count_security_hierarchy_violati_59d66fc7", hierarchy_count=hierarchy_count, value='s' if hierarchy_count != 1 else '')).classes("font-semibold grow")
                        ui.label(render_message("webui.load_security_operations.label.requires_investigation_45d92599") if hierarchy_count else render_message("webui.load_security_operations.label.no_invalid_parent_child_levels_found_9931a46f")).classes("text-sm text-slate-600")
                    for finding in reconciliation["findings"]:
                        if "governance_custodian" in finding["code"] or finding["code"] == "security_hierarchy_violation":
                            continue
                        with ui.row().classes("w-full items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3"):
                            ui.icon("warning", color="negative" if finding["severity"] == "critical" else "amber-8")
                            ui.label(finding["code"].replace("_", " ").title()).classes("font-semibold grow")
                            ui.badge(finding["severity"], color="negative" if finding["severity"] == "critical" else "warning")

        def change_period() -> None:
            custom_range.set_visibility(period.value == "custom")
            if period.value != "custom":
                background_tasks.create(load_security_operations())

        period.on_value_change(change_period)
        refresh.on("click", load_security_operations)
        apply_range.on("click", load_security_operations)
        await load_security_operations()


    return select_security_operations
