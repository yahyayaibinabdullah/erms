"""Existing organization units view with explicit per-client dependencies."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from .entity_editor_controls import entity_metadata_label
from .i18n_catalogue import render_message
from nicegui import ui


def build_organization_units(
    *, ADVANCED_SEARCH_CONTROLLED_VALUES, add_button, add_record_button, aggregation_mode_bar, api, breadcrumb_back, confirm_identity_deletion, direction, enter_organization_units, error_message, format_file_size, guidance, localized_lifecycle_value, open_editor, register_navigation, search_bar, select_entity, select_role_details, show_api_error, show_authenticated_view, show_entity_history, subtitle, table_container, title,
):
    async def select_organization_unit_details(org_unit_id: int) -> None:
        register_navigation("org-unit-details", f"Organization unit #{org_unit_id}", entity_id=org_unit_id)
        show_authenticated_view()
        enter_organization_units()
        search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False); add_record_button.set_visibility(False)
        guidance.text = ""; table_container.clear()
        try:
            unit = await api.organization_summary("org-units", org_unit_id)
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True); return
        title.text = unit["name"]; subtitle.text = render_message("webui.select_organization_unit_details.text.organization_unit_details_and_inherited_li_03c74d6b")
        register_navigation(
            "org-unit-details", unit["name"], entity_id=org_unit_id,
            accessible_label=f"{unit['name']} — {unit['code']}",
        )

        async def refresh(_: Any = None) -> None:
            await select_organization_unit_details(org_unit_id)

        async def change_status() -> None:
            try:
                await api.set_active(
                    "org-units", org_unit_id, unit["version"],
                    active=unit["status"] == "inactive",
                )
                await refresh()
            except ApiError as error:
                show_api_error(error)

        with table_container, ui.column().classes("w-full p-5 gap-4"):
            with ui.element("div").classes("identity-command-layout w-full"):
                with ui.card().classes(
                    "detail-surface identity-command-actions shadow-none p-4 gap-3"
                ):
                    ui.label(render_message("webui.select_organization_unit_details.label.organization_unit_actions_9cdc2b66")).classes("aggregation-panel-heading w-full")
                    ui.label(render_message("webui.select_organization_unit_details.label.manage_and_audit_224b4446")).classes("record-action-group-label")
                    with ui.row().classes("w-full gap-2 flex-wrap"):
                        ui.button(render_message("webui.select_organization_unit_details.button.edit_cfc8d565"), icon="edit", on_click=lambda: open_editor(unit, on_saved=refresh, resource_key="org-units")).props("outline dense no-caps")
                        ui.button(render_message("webui.select_organization_unit_details.button.history_1d5fdf03"), icon="history", on_click=lambda: show_entity_history("org-units", unit)).props("outline dense no-caps")
                    ui.label(render_message("webui.select_organization_unit_details.label.lifecycle_6664ab76")).classes("record-action-group-label")
                    with ui.row().classes("w-full gap-2 flex-wrap"):
                        ui.button(render_message("webui.select_organization_unit_details.button.activate_e8099903") if unit["status"] == "inactive" else render_message("webui.select_organization_unit_details.button.deactivate_5e1ac197"), icon="toggle_on" if unit["status"] == "inactive" else "toggle_off", on_click=change_status).props("outline dense no-caps")
                        ui.button(
                            render_message("webui.select_organization_unit_details.button.permanently_delete_257a572f"), icon="delete_forever", color="negative",
                            on_click=lambda: confirm_identity_deletion(
                                "org-units", unit, label="organization unit",
                                on_deleted=lambda: select_entity("org-units"),
                            ),
                        ).props("outline dense no-caps")
                organization_metadata_panel = ui.card().classes(
                    "detail-surface identity-command-metadata shadow-none p-5 gap-4"
                )
                organization_metadata_panel.__enter__()
                with ui.grid(columns="auto minmax(0, 1fr) auto").classes("identity-detail-header w-full items-start gap-4"):
                    ui.avatar(icon="corporate_fare", color="blue-1", text_color="primary", size="58px")
                    with ui.column().classes("gap-1 min-w-0 break-words"):
                        ui.label(unit["name"]).classes("text-xl font-semibold")
                        ui.label(unit["code"]).classes("text-primary")
                        if unit.get("description"): ui.label(unit["description"]).classes("text-slate-600")
                    ui.button(
                        render_message("webui.select_organization_unit_details.button.back_534197f5"), icon=None if direction() == "rtl" else "arrow_back",
                        on_click=lambda: breadcrumb_back(lambda: select_entity("org-units")),
                    ).props("flat no-caps" + (" icon-right=arrow_forward" if direction() == "rtl" else ""))
                with ui.grid(columns=3).classes("identity-detail-facts w-full gap-4"):
                    for label, value, value_kind in (
                        (entity_metadata_label("Status"), unit.get("status"), "status"),
                        (render_message("webui.render_governance_cards.text.effective_status_c7a1dfe1"), unit.get("effective_status"), "status"),
                        (render_message("webui.render_tree_level.text.inactive_via_parent_29212032"), (unit.get("inactive_source") or {}).get("name"), None),
                        (entity_metadata_label("Parent organization unit"), (unit.get("parent") or {}).get("name"), "parent"),
                        (entity_metadata_label("Managing role"), unit.get("managing_role"), "role"),
                        (entity_metadata_label("File Administrator role"), unit.get("file_administrator_role"), "role"),
                        (render_message("navigation.item.org_units"), unit.get("child_org_unit_count"), None),
                        (render_message("navigation.item.roles"), unit.get("role_count"), None),
                    ):
                        guidance_text = {
                            entity_metadata_label("Status"): render_message("webui.select_organization_unit_details.text.set_directly_on_this_organization_unit_wit_d76d3eda"),
                            render_message("webui.render_governance_cards.text.effective_status_c7a1dfe1"): render_message("webui.select_organization_unit_details.text.also_includes_inactivity_inherited_from_an_109127e4"),
                        }.get(label)
                        with ui.column().classes("identity-detail-fact gap-0 border-b border-slate-100 pb-1.5"):
                            ui.label(label).classes("detail-field-label")
                            display_value = (
                                localized_lifecycle_value(value)
                                if value is not None and value_kind == "status"
                                else str(value) if value is not None else "—"
                            )
                            if value_kind == "role" and value:
                                ui.label(f"{value['code']} · {value['name']}").classes(
                                    "font-medium text-primary cursor-pointer break-words"
                                ).on("click", lambda _, role_id=value["id"]: select_role_details(role_id))
                            elif value_kind == "parent" and (unit.get("parent") or {}).get("id"):
                                ui.label(display_value).classes(
                                    "font-medium text-primary cursor-pointer"
                                ).on(
                                    "click",
                                    lambda: select_organization_unit_details(
                                        unit["parent"]["id"]
                                    ),
                                ).tooltip(render_message("webui.select_organization_unit_details.tooltip.open_parent_organization_unit_25f29976"))
                            else:
                                ui.label(display_value).classes("font-medium")
                            if guidance_text:
                                ui.label(guidance_text).classes("w-full text-[10px] leading-3 text-slate-400")
                organization_metadata_panel.__exit__(None, None, None)
            with ui.card().classes(
                "detail-surface shadow-none p-0 gap-0 w-full overflow-hidden"
            ):
                with ui.row().classes(
                    "w-full items-center gap-2 px-4 py-3 border-b border-slate-200"
                ):
                    ui.icon("account_tree", size="19px").classes("text-primary")
                    with ui.column().classes("gap-0"):
                        ui.label(render_message("webui.select_organization_unit_details.label.organizational_lineage_26c71af1")).classes(
                            "font-semibold text-slate-800"
                        )
                        ui.label(
                            render_message("webui.select_organization_unit_details.label.from_the_highest_ancestor_to_the_current_o_6092bcab")
                        ).classes("text-xs text-slate-500")
                with ui.element("div").classes("org-unit-lineage-list"):
                    lineage = [*(unit.get("ancestors") or []), {
                        "id": unit["id"], "code": unit["code"],
                        "name": unit["name"], "is_current": True,
                    }]
                    for lineage_unit in lineage:
                        is_current = bool(lineage_unit.get("is_current"))
                        with ui.element("div").classes("org-unit-lineage-row"):
                            with ui.element("div").classes(
                                "org-unit-lineage-node" + (" current" if is_current else "")
                            ):
                                ui.icon(
                                    "location_on" if is_current else "corporate_fare",
                                    size="16px",
                                )
                            with ui.element("div").classes("org-unit-lineage-copy"):
                                lineage_name = ui.label(lineage_unit["name"]).classes(
                                    "text-sm font-semibold truncate"
                                )
                                if not is_current:
                                    lineage_name.classes("org-unit-lineage-link").on(
                                        "click",
                                        lambda _, ancestor_id=lineage_unit["id"]:
                                            select_organization_unit_details(ancestor_id),
                                    ).tooltip(
                                        render_message("webui.select_organization_unit_details.tooltip.open_name_fcf4fb5e", name=lineage_unit['name'])
                                    )
                                ui.label(lineage_unit["code"]).classes(
                                    "org-unit-lineage-code shrink-0"
                                )
            holdings_metrics = unit["holdings_metrics"]
            with ui.card().classes(
                "detail-surface shadow-none p-0 gap-0 w-full overflow-hidden"
            ):
                with ui.row().classes(
                    "w-full items-center gap-2 px-4 py-3 border-b border-slate-200"
                ):
                    ui.icon("inventory_2", size="19px").classes("text-primary")
                    with ui.column().classes("gap-0"):
                        ui.label(render_message("webui.select_organization_unit_details.label.holdings_summary_0736c95f")).classes("font-semibold text-slate-800")
                        ui.label(render_message("webui.select_organization_unit_details.label.visible_holdings_owned_by_this_organizatio_c8712879")).classes(
                            "text-xs text-slate-500"
                        )
                with ui.element("div").classes("org-unit-holdings-grid"):
                    with ui.element("div").classes("org-unit-holdings-group"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("folder", size="18px").classes("text-primary")
                            ui.label(
                                render_message("webui.select_organization_unit_details.label.aggregation_count_aggregations_5d7f7f5c", aggregation_count=holdings_metrics['aggregation_count'])
                            ).classes("text-sm font-semibold tabular-nums")
                        with ui.element("div").classes("dashboard-holdings-mediums mt-1"):
                            ui.label(
                                render_message("webui.select_organization_unit_details.label.open_aggregation_count_open_closed_aggrega_b1b24d8d", open_aggregation_count=holdings_metrics['open_aggregation_count'], closed_aggregation_count=holdings_metrics['closed_aggregation_count'])
                            ).classes("dashboard-holdings-medium tabular-nums")
                            ui.label("|").classes(
                                "dashboard-holdings-medium"
                            ).props("aria-hidden=true")
                            for medium_index, medium in enumerate((
                                "physical", "digital", "mixed",
                            )):
                                if medium_index:
                                    ui.label("·").classes(
                                        "dashboard-holdings-medium"
                                    ).props("aria-hidden=true")
                                ui.label(
                                    render_message(
                                        "webui.select_organization_unit_details.label.title_value_df57d819",
                                        title=render_message(ADVANCED_SEARCH_CONTROLLED_VALUES["medium"][medium]),
                                        value=holdings_metrics[f'{medium}_aggregation_count'],
                                    )
                                ).classes("dashboard-holdings-medium tabular-nums")
                    with ui.element("div").classes("org-unit-holdings-group"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("description", size="18px").classes("text-primary")
                            ui.label(
                                render_message("webui.select_organization_unit_details.label.record_count_records_36bb2d62", record_count=holdings_metrics['record_count'])
                            ).classes("text-sm font-semibold tabular-nums")
                        with ui.element("div").classes("dashboard-holdings-mediums mt-1"):
                            for medium_index, medium in enumerate((
                                "physical", "digital", "mixed",
                            )):
                                if medium_index:
                                    ui.label("·").classes(
                                        "dashboard-holdings-medium"
                                    ).props("aria-hidden=true")
                                ui.label(
                                    render_message(
                                        "webui.select_organization_unit_details.label.title_value_df57d819",
                                        title=render_message(ADVANCED_SEARCH_CONTROLLED_VALUES["medium"][medium]),
                                        value=holdings_metrics[f'{medium}_record_count'],
                                    )
                                ).classes("dashboard-holdings-medium tabular-nums")
                    with ui.element("div").classes("org-unit-holdings-group"):
                        with ui.column().classes("gap-1"):
                            with ui.element("span").classes(
                                "dashboard-holdings-peer-stat tabular-nums"
                            ):
                                ui.icon("emergency", size="14px").classes("text-red-600")
                                ui.label(
                                    render_message("webui.select_organization_unit_details.label.vital_record_count_vital_records_a2c63104", vital_record_count=holdings_metrics['vital_record_count'])
                                )
                            with ui.element("span").classes(
                                "dashboard-holdings-peer-stat tabular-nums"
                            ):
                                ui.icon("storage", size="14px").classes("text-primary")
                                ui.label(
                                    render_message("webui.select_organization_unit_details.label.format_file_size_storage_f4642599", format_file_size=format_file_size(holdings_metrics['storage_size_in_bytes']))
                                )


    return select_organization_unit_details
