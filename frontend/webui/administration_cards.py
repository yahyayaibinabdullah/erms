"""Shared administration-card presentation and its existing feature callbacks.

Collection paging remains per client; this renderer receives only its page map
and result reader, never the application-state dictionary.
"""
from __future__ import annotations
from typing import Any
from .collection_controls import bind_collection_paging
from .security_administration import localized_profile_value
from .i18n_catalogue import render_message
from nicegui import ui


def build_administration_cards(
    *, format_timestamp, load_rows, localized_account_type, localized_lifecycle_value, open_editor, pages, reset_lifecycle_filter, get_rows, select_organization_unit_details, select_role_details, select_user_details, show_entity_history, show_memberships, show_profile_privilege_editor,
):
    def render_administration_cards(spec):
        card_page = pages.setdefault(spec.key, {
            "offset": 0, "limit": 25, "total": len(get_rows()),
            "query": "", "status": "all", "account_type": "all",
            "sort": "level_number" if spec.key == "security-levels" else "name",
        })
        with ui.row().classes("w-full items-end gap-3 px-5 pt-3 flex-wrap"):
            card_filter = ui.input(
                {
                    "security-levels": render_message("webui.render_table.input.filter_security_levels_f290cff4"),
                    "profiles": render_message("webui.render_table.input.filter_profiles_2f4a2c88"),
                    "users": render_message("webui.render_table.input.filter_users_87c1f82f"),
                    "roles": render_message("webui.render_table.input.filter_roles_89b2d475"),
                    "org-units": render_message("webui.render_table.input.filter_organization_units_472aad07"),
                }[spec.key],
                placeholder={
                    "users": render_message("webui.render_table.input.name_email_or_external_identifier_52dac4f4"),
                    "roles": render_message("webui.render_table.input.code_name_organization_unit_or_profile_1ba283b1"),
                    "org-units": render_message("webui.render_table.input.code_name_parent_unit_or_description_0e985d50"),
                }.get(spec.key, render_message("webui.render_table.input.code_name_or_description_8b7e9b8d")),
                value=card_page.get("query", ""),
            ).props("outlined dense clearable debounce=350").classes("grow min-w-[260px]")
            card_status = None
            card_account_type = None
            if spec.key in {"users", "roles", "org-units"}:
                status_options = {"all": render_message("webui.render_table.text.all_statuses_06d8caa8"), "active": render_message("webui.render_table.text.active_3a692d6a"), "inactive": render_message("webui.render_table.text.inactive_ffa76f23")}
                if spec.key == "users":
                    status_options["suspended"] = render_message("webui.show_organization_structure.select.suspended_e5b9d9f5")
                selected_status = card_page.get("status", "all")
                if selected_status not in status_options:
                    selected_status = "all"
                    reset_lifecycle_filter()
                card_status = ui.select(
                    status_options, value=selected_status, label=render_message("webui.render_table.select.status_bba3b0bf"),
                ).props("outlined dense options-dense").classes("w-44")
            if spec.key == "users":
                card_account_type = ui.select(
                    {"all": render_message("webui.render_table.select.all_account_types_4efb11a2"), "person": render_message("webui.render_table.select.person_71413829"), "service": render_message("webui.render_table.select.service_e1263edf")},
                    value=card_page.get("account_type", "all"), label=render_message("webui.render_table.select.account_type_1e818a83"),
                ).props("outlined dense options-dense").classes("w-48")
            sort_options = {
                "security-levels": {"level_number": render_message("webui.render_table.text.level_167db239"), "code": render_message("webui.render_table.text.code_85512fe5"), "name": render_message("webui.render_table.text.name_12ca0838")},
                "profiles": {"name": render_message("webui.render_table.text.name_12ca0838"), "code": render_message("webui.render_table.text.code_85512fe5"), "is_system": render_message("webui.render_table.text.type_4f2149b1")},
                "users": {"name": render_message("webui.render_table.text.name_12ca0838"), "email": render_message("webui.render_table.text.email_28a52077"), "date_created": render_message("webui.render_table.text.created_a2dd6a8e")},
                "roles": {"name": render_message("webui.render_table.text.name_12ca0838"), "code": render_message("webui.render_table.text.code_85512fe5"), "status": render_message("webui.render_table.text.status_9c5fc70c")},
                "org-units": {"name": render_message("webui.render_table.text.name_12ca0838"), "code": render_message("webui.render_table.text.code_85512fe5"), "status": render_message("webui.render_table.text.status_9c5fc70c")},
            }[spec.key]
            card_sort = ui.select(
                sort_options,
                value=card_page.get("sort", "level_number" if spec.key == "security-levels" else "name"),
                label=render_message("webui.render_table.select.sort_by_dc4ba2eb"),
            ).props("outlined dense options-dense").classes("w-44")
            card_page_size = ui.select(
                {10: "10", 25: "25", 50: "50"}, value=int(card_page.get("limit", 25)),
                label=render_message("webui.render_table.select.per_page_204d3934"),
            ).props("outlined dense options-dense").classes("w-28")
        with ui.row().classes("w-full items-center px-5"):
            card_summary = ui.label().classes("text-sm text-slate-500")
            ui.space()
            ui.button(render_message("webui.render_table.button.refresh_d245cda4"), icon="refresh", on_click=lambda: reload_governance_cards()).props("flat dense no-caps")
        card_host = ui.element("div").classes("governance-card-list w-full px-5")
        with ui.row().classes("w-full items-center px-5 pb-5 gap-2"):
            card_range = ui.label().classes("text-sm text-slate-500")
            ui.space()
            card_first = ui.button(render_message("webui.render_table.button.first_6e0613a1"), icon="first_page").props("flat dense no-caps")
            card_previous = ui.button(render_message("webui.render_table.button.previous_ff5ac91d"), icon="chevron_left").props("flat dense no-caps")
            card_next = ui.button(render_message("webui.render_table.button.next_7c669a6d"), icon="chevron_right").props("flat dense no-caps")
            card_last = ui.button(render_message("webui.render_table.button.last_cb5252cb"), icon="last_page").props("flat dense no-caps")

        def render_governance_cards(*, reset: bool = False) -> None:
            rows = list(get_rows())
            def card_value(row: dict[str, Any], field: str) -> Any:
                if spec.key == "profiles" and field in {"name", "description"}:
                    return localized_profile_value(row, field)
                if field in {"name", "description"} and spec.key in {
                    "security-levels", "users", "roles", "org-units",
                }:
                    return (row.get("localized") or {}).get(field) or row.get(field)
                return row.get(field)

            page_rows = rows
            card_host.clear()
            with card_host:
                if not page_rows:
                    ui.label(render_message("webui.render_governance_cards.label.no_matching_items_38db9ba1")).classes("w-full text-center text-slate-400 py-12")
                for row in page_rows:
                    with ui.card().classes("governance-list-card shadow-none"):
                        # Grid follows document direction directly; the
                        # global RTL flex-row reversal must not move
                        # the leading identity icon to the trailing edge.
                        with ui.grid(columns="auto minmax(0, 1fr) auto").classes("governance-card-header w-full items-start gap-3"):
                            with ui.element("div").classes("governance-card-icon mt-1"):
                                ui.icon(
                                    {
                                        "security-levels": "shield",
                                        "profiles": "admin_panel_settings",
                                        "users": "person" if row.get("account_type") == "person" else "smart_toy",
                                        "roles": "badge",
                                        "org-units": "corporate_fare",
                                    }[spec.key],
                                    size="22px",
                                )
                            with ui.column().classes("gap-0 min-w-0 grow"):
                                ui.label(card_value(row, "name") or render_message("webui.render_governance_cards.label.unnamed_7a826fff")).classes("font-semibold text-base leading-tight")
                                identity = row.get("code") or row.get("email") or row.get("external_id") or "—"
                                ui.label(identity).classes("text-xs font-medium text-primary break-all")
                                if spec.key in {"profiles", "roles", "org-units"}:
                                    ui.label(card_value(row, "description") or render_message("webui.render_governance_cards.label.no_description_provided_6c1f71ae")).classes("text-xs text-slate-500 mt-1 leading-5")
                            if spec.key == "profiles":
                                ui.badge(render_message("webui.render_governance_cards.badge.built_in_0f593ef6") if row.get("is_system") else render_message("webui.render_governance_cards.badge.custom_50f80791"), color="blue-grey").props("outline")
                            elif spec.key == "roles" and row.get("is_system"):
                                ui.badge(render_message("webui.render_governance_cards.badge.built_in_0f593ef6"), color="blue-grey").props("outline")
                            elif spec.key in {"users", "roles", "org-units"}:
                                status_value = row.get("effective_status", row.get("status", "active"))
                                localized_status = localized_lifecycle_value(status_value)
                                ui.badge(
                                    localized_status,
                                    color="positive" if status_value == "active" else "warning" if status_value == "suspended" else "blue-grey",
                                ).props("outline")
                        with ui.element("div").classes("governance-list-facts w-full"):
                            facts_by_resource = {
                                "security-levels": (
                                    (render_message("webui.render_governance_cards.text.level_9166a0c6"), str(row.get("level_number", "—"))),
                                    (render_message("webui.render_governance_cards.text.roles_assigned_this_level_cdc0781e"), str(row.get("roles_assigned_count", 0))),
                                    (render_message("webui.render_governance_cards.text.assigned_content_6b3ceaf7"), render_message("webui.render_governance_cards.text.get_aggregations_get_2_records_5bb78a16", get=row.get('aggregation_count', 0), get_2=row.get('record_count', 0))),
                                    (render_message("webui.render_governance_cards.text.prevents_disposition_02424d41"), render_message("webui.render_governance_cards.text.yes_1e245559") if row.get("prevents_disposition") else render_message("webui.render_governance_cards.text.no_10013db4")),
                                ),
                                "profiles": (
                                    (render_message("webui.render_governance_cards.text.privileges_228b97c0"), render_message("webui.render_governance_cards.text.get_privileges_bd0fe2c3", get=row.get('privilege_count', 0))),
                                    (render_message("webui.render_governance_cards.text.assigned_roles_5abc87ce"), render_message("webui.render_governance_cards.text.get_roles_144c9447", get=row.get('role_count', 0))),
                                    (render_message("webui.render_governance_cards.text.profile_type_84511002"), render_message("webui.render_governance_cards.text.built_in_2cc42a11") if row.get("is_system") else render_message("webui.render_governance_cards.text.custom_9bafe4e0")),
                                    (render_message("webui.render_governance_cards.text.last_updated_fdb63867"), format_timestamp(row.get("date_updated"))),
                                ),
                                "users": (
                                    (render_message("webui.render_governance_cards.text.account_type_f4a822a4"), localized_account_type(row.get("account_type"))),
                                    (render_message("webui.render_governance_cards.text.external_identifier_e529aee4"), row.get("external_id") or "—"),
                                    (render_message("webui.render_governance_cards.text.created_f7945475"), format_timestamp(row.get("date_created"))),
                                    (render_message("webui.render_governance_cards.text.account_state_2d75af66"), localized_lifecycle_value(row.get("status"))),
                                ),
                                "roles": (
                                    (render_message("webui.render_governance_cards.text.organization_unit_ba48dcf7"), " — ".join(filter(None, ((row.get("org_unit_display") or {}).get("code"), (row.get("org_unit_display") or {}).get("name")))) or "—"),
                                    (render_message("webui.render_governance_cards.text.profile_160b9a86"), " — ".join(filter(None, ((row.get("profile_display") or {}).get("code"), (row.get("profile_display") or {}).get("name")))) or "—"),
                                    (render_message("webui.render_governance_cards.text.security_clearance_6ed9f255"), " — ".join(filter(None, ((row.get("security_level_display") or {}).get("code"), (row.get("security_level_display") or {}).get("name")))) or "—"),
                                    (render_message("webui.render_governance_cards.text.role_type_2eb796a4"), render_message("webui.render_governance_cards.text.built_in_2cc42a11") if row.get("is_system") else render_message("webui.render_governance_cards.text.custom_9bafe4e0")),
                                ),
                                "org-units": (
                                    (render_message("webui.render_governance_cards.text.parent_unit_b7e8e83c"), " — ".join(filter(None, ((row.get("parent_org_unit_display") or {}).get("code"), (row.get("parent_org_unit_display") or {}).get("name")))) or render_message("webui.render_governance_cards.text.top_level_unit_2e4edd39")),
                                    (render_message("webui.render_governance_cards.text.effective_status_c7a1dfe1"), localized_lifecycle_value(row.get("effective_status"))),
                                    (render_message("webui.render_governance_cards.text.created_f7945475"), format_timestamp(row.get("date_created"))),
                                    (render_message("webui.render_governance_cards.text.deactivated_8c6071da"), format_timestamp(row.get("date_deactivated")) if row.get("date_deactivated") else "—"),
                                ),
                            }
                            facts = facts_by_resource[spec.key]
                            for fact_index, (label, value) in enumerate(facts):
                                with ui.column().classes("gap-0 min-w-0"):
                                    ui.label(label).classes("detail-field-label")
                                    if spec.key == "security-levels" and fact_index == 3 and row.get("prevents_disposition"):
                                        ui.badge(render_message("webui.render_governance_cards.badge.yes_c316a2c3"), color="warning").props(
                                            "rounded text-color=white"
                                        ).classes("font-semibold")
                                    elif (
                                        spec.key == "org-units"
                                        and fact_index == 0
                                        and row.get("parent_org_unit_id")
                                    ):
                                        ui.label(value).classes(
                                            "text-sm font-medium text-primary cursor-pointer "
                                            "truncate w-full"
                                        ).on(
                                            "click",
                                            lambda _, parent_id=row["parent_org_unit_id"]:
                                                select_organization_unit_details(parent_id),
                                        ).tooltip(render_message("webui.render_governance_cards.tooltip.open_value_f1e5a469", value=value))
                                    else:
                                        fact_value = ui.label(value).classes(
                                            "text-sm font-medium truncate w-full"
                                        ).tooltip(value)
                                        if (
                                            (spec.key == "users" and fact_index == 2)
                                            or (spec.key == "profiles" and fact_index == 3)
                                            or (spec.key == "org-units" and fact_index in {2, 3})
                                        ):
                                            fact_value.props('dir="ltr"').classes("text-left")
                        with ui.row().classes("w-full justify-end gap-1"):
                            if spec.key == "users":
                                ui.button(icon="open_in_new", on_click=lambda _, item=row: select_user_details(item["id"])).props("outline dense color=primary").tooltip(render_message("webui.render_governance_cards.tooltip.open_user_0dd1ba6f"))
                            elif spec.key == "roles":
                                ui.button(icon="open_in_new", on_click=lambda _, item=row: select_role_details(item["id"])).props("outline dense color=primary").tooltip(render_message("webui.render_governance_cards.tooltip.open_role_5c0462a7"))
                            elif spec.key == "org-units":
                                ui.button(icon="open_in_new", on_click=lambda _, item=row: select_organization_unit_details(item["id"])).props("outline dense color=primary").tooltip(render_message("webui.render_governance_cards.tooltip.open_organization_unit_831f72f6"))
                            ui.button(icon="edit", on_click=lambda _, item=row: open_editor(item)).props("outline dense color=primary").tooltip(render_message("webui.render_governance_cards.tooltip.edit_e758b62a"))
                            if spec.key == "profiles":
                                ui.button(icon="key", on_click=lambda _, item=row: show_profile_privilege_editor(item)).props("outline dense color=primary").tooltip(render_message("webui.render_governance_cards.tooltip.manage_privileges_aafa40bb"))
                            if spec.key in {"users", "roles"} and not (
                                spec.key == "roles" and row.get("is_system")
                            ):
                                ui.button(
                                    icon="group",
                                    on_click=lambda _, item=row, user_view=spec.key == "users": show_memberships(item, for_user=user_view),
                                ).props("outline dense color=primary").tooltip(render_message("webui.render_governance_cards.tooltip.role_assignments_130ac369"))
                            ui.button(icon="history", on_click=lambda _, item=row: show_entity_history(spec.key, item)).props("outline dense color=blue-grey").tooltip(render_message("webui.render_governance_cards.tooltip.event_history_b5a81195"))
            start = card_page["offset"] + 1 if page_rows else 0
            end = card_page["offset"] + len(page_rows)
            resource_count_label = {
                "security-levels": render_message("navigation.item.security_levels"),
                "profiles": render_message("navigation.item.profiles"),
                "users": render_message("navigation.item.users"),
                "roles": render_message("navigation.item.roles"),
                "org-units": render_message("navigation.item.org_units"),
            }[spec.key]
            card_summary.text = render_message("webui.render_governance_cards.text.row_count_lower_b95cb021", row_count=card_page["total"], lower=resource_count_label)
            card_range.text = render_message("webui.render_governance_cards.text.showing_start_end_of_row_count_2542d0d0", start=start, end=end, row_count=card_page["total"])
            at_start = card_page["offset"] == 0
            at_end = end >= card_page["total"]
            card_first.set_enabled(not at_start); card_previous.set_enabled(not at_start)
            card_next.set_enabled(not at_end); card_last.set_enabled(not at_end)

        reload_governance_cards = bind_collection_paging(
            card_page=card_page, card_filter=card_filter, card_status=card_status,
            card_account_type=card_account_type, card_sort=card_sort,
            card_page_size=card_page_size, card_host=card_host,
            card_first=card_first, card_previous=card_previous,
            card_next=card_next, card_last=card_last,
            load_rows=load_rows, render_governance_cards=render_governance_cards,
        )
        render_governance_cards()
        return render_governance_cards

    return render_administration_cards
