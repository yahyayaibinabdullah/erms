"""Security oversight periods, event signals, reconciliation and destination links."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from nicegui import background_tasks
from datetime import datetime
from .authorization_ui import decision_code_label
from frontend.webui.event_labels import event_label
from .i18n_catalogue import render_message
from .identity_presentation import render_user_avatar
from nicegui import ui

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
        privileges = set((principal() or {}).get("global_privileges", []))
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
            if mode == "custom" and (not range_start.value or not range_end.value):
                ui.notify(render_message("webui.load_security_operations.notify.select_both_dates_for_the_custom_range_c8117eee"), color="warning")
                return
            summary = await api.security_summary(
                hours=hours,
                start_at=custom_iso(range_start.value, end=False) if mode == "custom" else None,
                end_at=custom_iso(range_end.value, end=True) if mode == "custom" else None,
            )
            reconciliation = None
            if "authorization.administer" in privileges:
                reconciliation = await api.security_reconciliation()
            if get_resource() != "security-operations" or period.value != mode:
                return
            window_title.text = {
                "24h": render_message("webui.load_security_operations.text.last_24_hours_42c47f2c"), "week": render_message("webui.load_security_operations.text.last_week_0f602f5d"), "month": render_message("webui.load_security_operations.text.last_month_1df4669b"),
                "custom": render_message("webui.load_security_operations.text.value_through_value_2_8da1ebd6", value=range_start.value, value_2=range_end.value),
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
                event_rows = [{
                    **item,
                    "actor": item.get("actor_name") or item.get("actor_email") or item.get("actor_type"),
                    "when": format_timestamp(item["occurred_at"]),
                    "signal": event_label(item["operation"]),
                    "decision": decision_code_label(item.get("decision_code")),
                } for item in summary.get("recent_events", [])]
                security_event_page = {"offset": 0}
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

                def render_security_event_cards() -> None:
                    offset = security_event_page["offset"]
                    page_rows = event_rows[offset:offset + 10]
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
                    start = offset + 1 if event_rows else 0
                    end = min(offset + 10, len(event_rows))
                    security_event_page_label.text = (
                        render_message("webui.render_security_event_cards.text.start_end_of_event_row_count_7e8f78d3", start=start, end=end, event_row_count=len(event_rows))
                    )
                    security_event_page_label.update()
                    (
                        security_event_previous.enable
                        if offset > 0 else security_event_previous.disable
                    )()
                    (
                        security_event_next.enable
                        if offset + 10 < len(event_rows)
                        else security_event_next.disable
                    )()

                def previous_security_events() -> None:
                    security_event_page["offset"] = max(
                        0, security_event_page["offset"] - 10,
                    )
                    render_security_event_cards()

                def next_security_events() -> None:
                    security_event_page["offset"] += 10
                    render_security_event_cards()

                security_event_previous.on("click", previous_security_events)
                security_event_next.on("click", next_security_events)
                render_security_event_cards()

                ui.label(render_message("webui.load_security_operations.label.denial_monitoring_9ac48ee1")).classes("text-lg font-semibold mt-2")
                ui.label(authorization_denial_help).classes("text-sm text-slate-500 -mt-4")
                if not summary["denial_groups"]:
                    ui.label(render_message("webui.load_security_operations.label.no_authorization_denials_occurred_in_this_3d7c10a2")).classes("text-sm text-positive")
                for item in summary["denial_groups"]:
                    with ui.card().classes("w-full shadow-none border border-slate-200 p-4 gap-1"):
                        with ui.row().classes("w-full items-center gap-3"):
                            ui.label(item["decision_code"].replace("_", " ").title()).classes("font-medium")
                            ui.label(item["required_privilege"]).classes("grow text-sm text-slate-500")
                            ui.badge(str(item["count"]), color="negative").props("outline")
                        ui.label(render_message("webui.load_security_operations.label.review_the_recent_events_above_or_open_the_dfa372aa")).classes("text-sm text-slate-500")

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
