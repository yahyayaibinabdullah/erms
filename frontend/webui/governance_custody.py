"""Governance custody report, isolated refresh ownership, status and destination links."""
from __future__ import annotations
from .api_client import ApiError
from .capabilities import can_navigate
from .application_settings import disposition_warning_panel
from .security_administration import localized_profile_value
from .i18n_catalogue import render_message
from .identity_presentation import render_user_avatar
from nicegui import ui
from .identity_presentation import user_avatar

def build_governance_custody(
    *, add_button, add_record_button, aggregation_mode_bar, api, can_open_settings, clear_collection, enter_governance_custody, error_message, format_timestamp, get_principal, get_resource, guidance, open_settings, register_navigation, search_bar, select_entity, select_role_details, select_user_details, show_authenticated_view, subtitle, table_container, title,
):
    custody_state = {}
    async def select_governance_custody() -> None:
        principal = get_principal()
        if not principal or not can_navigate("governance-custody", principal.get("global_privileges", [])):
            return
        prior_report_visible = get_resource() == "governance-custody"
        token = object()
        register_navigation(
            "governance-custody",
            render_message("webui.select_governance_custody.text.governance_custody_d1711a12"),
        )
        show_authenticated_view()
        enter_governance_custody(); custody_state['custody_page_token'] = token; clear_collection()
        title.text = render_message("webui.select_governance_custody.text.governance_custody_d1711a12")
        subtitle.text = render_message("webui.select_governance_custody.text.checks_that_someone_can_always_manage_and_63c11d0d")
        search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False); add_record_button.set_visibility(False)
        guidance.text = ""
        if not prior_report_visible:
            table_container.clear()
            with table_container:
                ui.label(render_message("settings.custody.loading")).classes("p-5 text-sm text-slate-500").props("role=status")
        try:
            report = await api.governance_custody()
        except ApiError as error:
            if custody_state.get("custody_page_token") is token and get_resource() == "governance-custody":
                ui.notify(error_message(error), color="negative", close_button=True)
            return
        if get_principal() is not principal or get_resource() != "governance-custody" or custody_state.get("custody_page_token") is not token:
            return
        table_container.clear()
        highest_level = report.get("highest_security_level")
        warning = next(iter(report.get("warnings", [])), None)
        custodian_count = report["highest_clearance_custodian_count"]
        qualifying_roles = [
            item for item in report["governance_roles"]
            if item["qualifies_for_universal_custody"]
        ]
        qualifying_assignments = [
            item for item in report["assignments"]
            if item["effective_for_universal_custody"]
        ]
        assignments_needing_attention = [
            item for item in report["assignments"]
            if not item["effective_for_universal_custody"]
        ]
        qualifying_roles_by_id = {item["id"]: item for item in qualifying_roles}
        with table_container, ui.column().classes("w-full p-5 gap-4"):
            with ui.row().classes("w-full justify-end"):
                ui.button(render_message("settings.action.refresh"), icon="refresh", on_click=select_governance_custody).props("flat dense no-caps")
            disposition_warning_panel(
                report.get("disposition_configuration_warnings", []),
                can_manage=can_open_settings(),
                open_settings=open_settings,
            )
            with ui.element("div").classes("governance-overview-grid"):
                with ui.card().classes("governance-purpose-card shadow-none"):
                    with ui.row().classes("w-full items-start gap-3 no-wrap"):
                        with ui.element("div").classes("governance-purpose-icon"):
                            ui.icon("policy", size="21px")
                        with ui.column().classes("gap-1 grow min-w-0"):
                            ui.label(render_message("webui.select_governance_custody.label.what_this_page_checks_99ff34f2")).classes("text-base font-semibold")
                            ui.label(
                                render_message("webui.select_governance_custody.label.at_least_one_active_person_must_be_able_to_4bd6d924")
                            ).classes("text-sm text-slate-600 leading-relaxed")
                            with ui.element("div").classes("governance-requirements-grid"):
                                for requirement in (
                                    render_message("governance_custody.requirement.governance_role_enabled"),
                                    render_message("governance_custody.requirement.highest_clearance_held"),
                                    render_message("governance_custody.requirement.required_profile_privileges"),
                                    render_message("governance_custody.requirement.current_role_assignment"),
                                ):
                                    with ui.row().classes("items-center gap-2 no-wrap"):
                                        ui.icon("check", color="positive", size="16px")
                                        ui.label(requirement).classes("text-xs text-slate-600")
                            ui.label(
                                render_message("webui.select_governance_custody.label.the_system_blocks_relevant_changes_that_wo_35b5b23b")
                            ).classes("text-xs text-slate-500 mt-1")
                critical = bool(warning and warning["severity"] == "critical")
                status_classes = (
                    "governance-status-card governance-status-critical"
                    if critical else
                    "governance-status-card governance-status-warning"
                    if warning else
                    "governance-status-card governance-status-healthy"
                )
                with ui.card().classes(f"{status_classes} shadow-none"):
                    with ui.row().classes("w-full items-start gap-3 no-wrap"):
                        with ui.element("div").classes("governance-status-icon"):
                            ui.icon("priority_high" if warning else "check", size="18px")
                        with ui.column().classes("gap-1 grow min-w-0"):
                            ui.label(
                                render_message("webui.select_governance_custody.label.custody_gap_detected_574f1e6b") if critical else
                                render_message("webui.select_governance_custody.label.custody_resilience_needs_attention_c7e23c3c") if warning else
                                render_message("webui.select_governance_custody.label.custody_coverage_is_healthy_a188b010")
                            ).classes("text-base font-semibold")
                            ui.label(
                                render_message("webui.select_governance_custody.label.no_person_currently_meets_every_requiremen_0a14d273")
                                if critical else
                                render_message("webui.select_governance_custody.label.only_one_person_currently_qualifies_add_a_8331e15a")
                                if warning else
                                render_message(
                                    "webui.select_governance_custody.label.custodian_count_active_value_currently_qua_5dd0d9d6",
                                    custodian_count=custodian_count,
                                    qualifying_role_count=len(qualifying_roles),
                                    qualifying_assignment_count=len(qualifying_assignments),
                                )
                            ).classes("text-sm leading-relaxed")
            with ui.row().classes("governance-metrics-row"):
                for value, label, icon in (
                    (custodian_count, render_message("governance_custody.metric.universal_custodians"), "person"),
                    (len(qualifying_roles), render_message("governance_custody.metric.qualifying_roles"), "badge"),
                    (len(qualifying_assignments), render_message("governance_custody.metric.qualifying_assignments"), "group"),
                ):
                    with ui.card().classes("governance-metric-card shadow-none"):
                        with ui.element("div").classes("governance-metric-icon"):
                            ui.icon(icon, size="18px")
                        with ui.column().classes("gap-0"):
                            ui.label(str(value)).classes("text-2xl font-semibold leading-none")
                            ui.label(label).classes("text-xs text-slate-500 mt-1")
            with ui.row().classes("w-full items-end gap-3 mt-1"):
                with ui.column().classes("gap-0 grow"):
                    ui.label(render_message("webui.select_governance_custody.label.universal_custodians_custodian_count_7eae7060", custodian_count=custodian_count)).classes(
                        "text-base font-semibold"
                    )
                    ui.label(
                        render_message("webui.select_governance_custody.label.active_people_whose_current_assignments_pr_46442dde")
                    ).classes("text-xs text-slate-500")
                if highest_level:
                    ui.badge(
                        render_message("webui.select_governance_custody.badge.required_clearance_code_name_level_level_n_def0467f", code=highest_level['code'], name=highest_level['name'], level_number=highest_level['level_number'])
                    ).props("outline color=primary")
            if qualifying_assignments:
                custodian_rows = [
                    {
                        **item,
                        "person": item["user_name"],
                        "email": item.get("user_email") or "—",
                        "avatar": user_avatar({
                            "id": item["user_id"],
                            "name": item["user_name"],
                            "email": item.get("user_email"),
                        }),
                        "role": f"{item['role_code']} — {item['role_name']}",
                        "clearance": (
                            f"{qualifying_roles_by_id[item['role_id']]['security_level_code']} — "
                            f"{qualifying_roles_by_id[item['role_id']]['security_level_name']}"
                        ),
                        "valid_from_display": format_timestamp(item["valid_from"]),
                        "valid_until_display": (
                            format_timestamp(item["valid_until"])
                            if item.get("valid_until")
                            else render_message("common.value.no_expiry")
                        ),
                    }
                    for item in qualifying_assignments
                ]
                custodian_page = {"offset": 0}
                custodian_host = ui.element("div").classes("governance-card-list w-full")
                with ui.row().classes("w-full items-center justify-end gap-2"):
                    custodian_page_label = ui.label().classes("text-sm text-slate-500")
                    custodian_previous = ui.button(
                        render_message("webui.select_governance_custody.button.previous_edabaddc"), icon="chevron_left",
                    ).props("flat dense no-caps")
                    custodian_next = ui.button(
                        render_message("webui.select_governance_custody.button.next_1b4b15c1"), icon="chevron_right",
                    ).props("flat dense no-caps")

                def render_custodian_cards() -> None:
                    offset = custodian_page["offset"]
                    page_rows = custodian_rows[offset:offset + 5]
                    custodian_host.clear()
                    with custodian_host:
                        for row in page_rows:
                            with ui.card().classes(
                                "governance-list-card governance-custody-assignment-card shadow-none"
                            ):
                                with ui.row().classes("w-full items-center no-wrap gap-3"):
                                    render_user_avatar({
                                        "id": row["user_id"], "name": row["person"],
                                        "email": row["email"],
                                    }, size="36px")
                                    with ui.column().classes("gap-0 min-w-0 grow"):
                                        ui.label(row["person"]).classes("font-semibold")
                                        ui.label(row["email"]).classes(
                                            "text-xs text-slate-500 truncate w-full"
                                        ).tooltip(row["email"])
                                    ui.badge(render_message("webui.render_custodian_cards.badge.universal_custodian_d25d5028"), color="positive").props(
                                        "outline"
                                    )
                                    ui.button(
                                        icon="person",
                                        on_click=lambda _, item=row: select_user_details(
                                            item["user_id"]
                                        ),
                                    ).props("flat round dense").tooltip(render_message("webui.render_custodian_cards.tooltip.open_user_9f50a343"))
                                    ui.button(
                                        icon="badge",
                                        on_click=lambda _, item=row: select_role_details(
                                            item["role_id"]
                                        ),
                                    ).props("flat round dense").tooltip(render_message("webui.render_custodian_cards.tooltip.open_role_b3a2bb9f"))
                                with ui.element("div").classes("governance-list-facts"):
                                    for label, value in (
                                        (render_message("governance_custody.field.qualifying_role"), row["role"]),
                                        (render_message("governance_custody.field.clearance"), row["clearance"]),
                                        (render_message("governance_custody.field.valid_from"), row["valid_from_display"]),
                                        (render_message("governance_custody.field.valid_until"), row["valid_until_display"]),
                                    ):
                                        with ui.column().classes("gap-0 min-w-0"):
                                            ui.label(label).classes("detail-field-label")
                                            ui.label(value).classes("text-sm truncate w-full").tooltip(value)
                    start = offset + 1
                    end = min(offset + 5, len(custodian_rows))
                    custodian_page_label.text = render_message("webui.render_custodian_cards.text.start_end_of_custodian_row_count_dae30e10", start=start, end=end, custodian_row_count=len(custodian_rows))
                    custodian_page_label.update()
                    (custodian_previous.enable if offset > 0 else custodian_previous.disable)()
                    (custodian_next.enable if offset + 5 < len(custodian_rows) else custodian_next.disable)()

                def previous_custodians() -> None:
                    custodian_page["offset"] = max(0, custodian_page["offset"] - 5)
                    render_custodian_cards()

                def next_custodians() -> None:
                    custodian_page["offset"] += 5
                    render_custodian_cards()

                custodian_previous.on("click", previous_custodians)
                custodian_next.on("click", next_custodians)
                render_custodian_cards()
            else:
                ui.label(
                    render_message("webui.select_governance_custody.label.no_active_person_currently_meets_every_uni_a3dca3a6")
                ).classes("governance-empty-inline")
            with ui.row().classes("w-full items-center gap-3"):
                with ui.column().classes("gap-0 grow"):
                    ui.label(render_message("webui.select_governance_custody.label.information_governance_roles_911de052")).classes("text-base font-semibold")
                    ui.label(
                        render_message("webui.select_governance_custody.label.qualifying_roles_provide_custody_other_lis_4d8ef8ea")
                    ).classes("text-xs text-slate-500")
            if not report["governance_roles"]:
                with ui.card().classes("governance-empty-state shadow-none"):
                    ui.icon("verified_user", color="blue-grey-4", size="28px")
                    ui.label(render_message("webui.select_governance_custody.label.no_information_governance_roles_are_config_e5d78ffe")).classes(
                        "text-sm font-semibold text-slate-700"
                    )
                    ui.label(
                        render_message("webui.select_governance_custody.label.designate_the_appropriate_records_manageme_af9e90ae")
                    ).classes("text-xs text-slate-500 text-center")
                    with ui.row().classes("gap-2 mt-1"):
                        ui.button(
                            render_message("webui.select_governance_custody.button.configure_a_role_29c8cb79"), icon="badge",
                            on_click=lambda: select_entity("roles"),
                        ).props("outline dense no-caps")
                        ui.button(
                            render_message("webui.select_governance_custody.button.review_profiles_72e9cc1a"), icon="admin_panel_settings",
                            on_click=lambda: select_entity("profiles"),
                        ).props("flat dense no-caps")
            else:
                for role in report["governance_roles"]:
                    with ui.card().classes("w-full shadow-none border border-slate-200 p-4 gap-2"):
                        with ui.row().classes("w-full items-center gap-3 no-wrap"):
                            ui.icon("verified_user", color="primary")
                            with ui.column().classes("gap-0 grow min-w-0"):
                                ui.label(render_message("webui.select_governance_custody.label.code_name_740f84d3", code=role['code'], name=role['name'])).classes("font-semibold")
                                ui.label(
                                    render_message(
                                        "webui.select_governance_custody.label.profile_profile_code_profile_name_8fd7d019",
                                        profile_code=role["profile_code"],
                                        profile_name=localized_profile_value(
                                            {"code": role["profile_code"], "name": role["profile_name"]},
                                            "name",
                                        ),
                                    )
                                ).classes("text-xs text-slate-500")
                            ui.badge(
                                render_message("webui.select_governance_custody.badge.qualifies_for_universal_custody_a79e1a94")
                                if role["qualifies_for_universal_custody"] else
                                render_message("webui.select_governance_custody.badge.does_not_qualify_1f027fee"),
                                color="positive" if role["qualifies_for_universal_custody"] else "warning",
                            ).props("outline")
                            ui.button(
                                icon="badge",
                                on_click=lambda _, identifier=role["id"]: select_role_details(identifier),
                            ).props("flat round dense").tooltip(render_message("webui.select_governance_custody.tooltip.open_role_5da0e9a7"))
                        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                            ui.badge(
                                render_message("webui.select_governance_custody.badge.security_level_code_security_level_name_le_7ee97b4b", security_level_code=role['security_level_code'], security_level_name=role['security_level_name'], level_number=role['level_number']),
                                color="positive" if role["is_highest_clearance"] else "blue-grey",
                            ).props("outline")
                            ui.badge(
                                render_message("webui.select_governance_custody.badge.role_and_organization_active_c40efefa") if role["effective"] else render_message("webui.select_governance_custody.badge.role_or_organization_inactive_b4bb3f56"),
                                color="positive" if role["effective"] else "negative",
                            ).props("outline")
                            ui.badge(
                                render_message("webui.select_governance_custody.badge.all_custody_privileges_present_1be04201")
                                if role["has_required_custody_privileges"] else
                                render_message("webui.select_governance_custody.badge.missing_custody_privilege_code_count_custo_93921b59", missing_custody_privilege_code_count=len(role['missing_custody_privilege_codes'])),
                                color="positive" if role["has_required_custody_privileges"] else "negative",
                            ).props("outline")
                            for count, label, explanation in (
                                (
                                    role["current_assignee_count"],
                                    render_message("governance_custody.stat.current_assignments"),
                                    render_message("governance_custody.help.current_assignments"),
                                ),
                                (
                                    role["effective_assignee_count"],
                                    render_message("governance_custody.stat.active_people_in_active_role"),
                                    render_message("governance_custody.help.active_people_in_active_role"),
                                ),
                                (
                                    role["universal_custodian_count"],
                                    render_message("governance_custody.metric.universal_custodians"),
                                    render_message("governance_custody.help.universal_custodians"),
                                ),
                            ):
                                ui.label(render_message("webui.select_governance_custody.label.label_count_73f7a855", label=label, count=count)).classes(
                                    "text-xs text-slate-500 cursor-help"
                                ).tooltip(explanation)
                        if role["missing_custody_privilege_codes"]:
                            missing = ", ".join(role["missing_custody_privilege_codes"])
                            ui.label(render_message("webui.select_governance_custody.label.missing_privileges_missing_ab329cec", missing=missing)).classes(
                                "text-xs font-mono text-red-700 break-all"
                            )

            if assignments_needing_attention:
                with ui.row().classes("w-full items-center gap-3 mt-1"):
                    with ui.column().classes("gap-0 grow"):
                        ui.label(render_message("webui.select_governance_custody.label.assignments_needing_attention_c83257ed")).classes("text-base font-semibold")
                        ui.label(
                            render_message("webui.select_governance_custody.label.only_assignments_that_do_not_currently_pro_3dcf32ef")
                        ).classes("text-xs text-slate-500")
                    if highest_level:
                        ui.label(
                            render_message("webui.select_governance_custody.label.highest_configured_level_code_name_level_l_8df33123", code=highest_level['code'], name=highest_level['name'], level_number=highest_level['level_number'])
                        ).classes("text-xs text-slate-500")
                reason_labels = {
                    "service_account": render_message("governance_custody.reason.service_account"),
                    "user_inactive": render_message("governance_custody.reason.user_inactive"),
                    "user_suspended": render_message("governance_custody.reason.user_suspended"),
                    "assignment_not_current": render_message("governance_custody.reason.assignment_not_current"),
                    "role_or_organization_inactive": render_message("governance_custody.reason.role_or_organization_inactive"),
                    "role_not_universal_custody_qualified": render_message("governance_custody.reason.role_not_universal_custody_qualified"),
                }
                assignment_rows = []
                for item in assignments_needing_attention:
                    assignment_rows.append({
                        **item,
                        "person": item["user_name"],
                        "email": item.get("user_email") or "—",
                        "role": f"{item['role_code']} — {item['role_name']}",
                        "custody_status": "; ".join(
                            reason_labels[reason]
                            if reason in reason_labels
                            else reason.replace("_", " ").title()
                            for reason in item["ineffective_reasons"]
                        ),
                    })
                attention_page = {"offset": 0}
                attention_host = ui.element("div").classes("governance-card-list w-full")
                with ui.row().classes("w-full items-center justify-end gap-2"):
                    attention_page_label = ui.label().classes("text-sm text-slate-500")
                    attention_previous = ui.button(
                        render_message("webui.select_governance_custody.button.previous_edabaddc"), icon="chevron_left",
                    ).props("flat dense no-caps")
                    attention_next = ui.button(
                        render_message("webui.select_governance_custody.button.next_1b4b15c1"), icon="chevron_right",
                    ).props("flat dense no-caps")

                def render_attention_cards() -> None:
                    offset = attention_page["offset"]
                    page_rows = assignment_rows[offset:offset + 5]
                    attention_host.clear()
                    with attention_host:
                        for row in page_rows:
                            with ui.card().classes(
                                "governance-list-card governance-custody-assignment-card shadow-none"
                            ):
                                with ui.row().classes("w-full items-center no-wrap gap-3"):
                                    render_user_avatar({
                                        "id": row["user_id"], "name": row["person"],
                                        "email": row["email"],
                                    }, size="36px")
                                    with ui.column().classes("gap-0 min-w-0 grow"):
                                        ui.label(row["person"]).classes("font-semibold")
                                        ui.label(row["email"]).classes(
                                            "text-xs text-slate-500 truncate w-full"
                                        ).tooltip(row["email"])
                                    ui.button(
                                        icon="person",
                                        on_click=lambda _, item=row: select_user_details(
                                            item["user_id"]
                                        ),
                                    ).props("flat round dense").tooltip(render_message("webui.render_attention_cards.tooltip.open_user_350f3508"))
                                with ui.element("div").classes(
                                    "governance-list-facts user-role-assignment-facts"
                                ):
                                    for label, value in (
                                        (render_message("entity_metadata.field.role"), row["role"]),
                                        (render_message("governance_custody.field.custody_status"), row["custody_status"]),
                                    ):
                                        with ui.column().classes("gap-0 min-w-0"):
                                            ui.label(label).classes("detail-field-label")
                                            ui.label(value).classes(
                                                "text-sm whitespace-normal"
                                            )
                    start = offset + 1
                    end = min(offset + 5, len(assignment_rows))
                    attention_page_label.text = render_message("webui.render_attention_cards.text.start_end_of_assignment_row_count_f9667dd2", start=start, end=end, assignment_row_count=len(assignment_rows))
                    attention_page_label.update()
                    (attention_previous.enable if offset > 0 else attention_previous.disable)()
                    (attention_next.enable if offset + 5 < len(assignment_rows) else attention_next.disable)()

                def previous_attention_assignments() -> None:
                    attention_page["offset"] = max(0, attention_page["offset"] - 5)
                    render_attention_cards()

                def next_attention_assignments() -> None:
                    attention_page["offset"] += 5
                    render_attention_cards()

                attention_previous.on("click", previous_attention_assignments)
                attention_next.on("click", next_attention_assignments)
                render_attention_cards()


    return select_governance_custody
