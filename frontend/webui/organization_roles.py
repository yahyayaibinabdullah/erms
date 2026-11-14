"""Existing organization roles view with explicit per-client dependencies."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from .entity_editor_controls import entity_metadata_label
from .security_administration import localized_privilege_category
from .security_administration import localized_privilege_description
from .security_administration import localized_privilege_name
from .i18n_catalogue import render_message
from nicegui import ui


def build_organization_roles(
    *, add_button, add_record_button, aggregation_mode_bar, api, breadcrumb_back, confirm_identity_deletion, direction, enter_organization_roles, error_message, get_principal, guidance, localized_lifecycle_value, open_editor, register_navigation, search_bar, select_entity, select_organization_unit_details, select_text_indexers, show_api_error, show_authenticated_view, show_entity_history, show_memberships, subtitle, table_container, title,
):
    async def select_role_details(role_id: int) -> None:
        register_navigation("role-details", f"Role #{role_id}", entity_id=role_id)
        show_authenticated_view()
        enter_organization_roles()
        search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False); add_record_button.set_visibility(False)
        guidance.text = ""; table_container.clear()
        try:
            role = await api.organization_summary("roles", role_id)
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True); return
        title.text = role["name"]; subtitle.text = render_message("webui.select_role_details.text.role_details_assignments_supervision_and_i_312b583b")
        register_navigation(
            "role-details", role["name"], entity_id=role_id,
            accessible_label=f"{role['name']} — {role['code']}",
        )

        async def refresh(_: Any = None) -> None:
            await select_role_details(role_id)

        async def change_status() -> None:
            try:
                await api.set_active("roles", role_id, role["version"], active=role["status"] == "inactive")
                await refresh()
            except ApiError as error:
                show_api_error(error)

        is_builtin = bool(role.get("is_system"))
        with table_container, ui.column().classes("w-full p-5 gap-4"):
            with ui.element("div").classes("identity-command-layout w-full"):
                with ui.card().classes(
                    "detail-surface identity-command-actions shadow-none p-4 gap-3"
                ):
                    ui.label(render_message("webui.select_role_details.label.role_actions_c60a91ae")).classes("aggregation-panel-heading w-full")
                    if is_builtin:
                        ui.badge(render_message("webui.select_role_details.badge.built_in_read_only_503b4528"), color="blue-grey").props("outline")
                        if role.get("code") == "text-indexer-service":
                            ui.label(
                                render_message("webui.select_role_details.label.this_is_a_platform_managed_service_role_fo_846ede9b")
                            ).classes("text-xs text-slate-500 leading-5")
                        else:
                            ui.label(
                                render_message("webui.select_role_details.label.built_in_roles_are_provisioned_by_the_plat_fefe2800")
                            ).classes("text-xs text-slate-500 leading-5")
                        ui.button(
                            render_message("webui.select_role_details.button.edit_a1e87f79"),
                            icon="translate",
                            on_click=lambda: open_editor(
                                role, on_saved=refresh, resource_key="roles"
                            ),
                        ).props("outline dense no-caps")
                        if (
                            role.get("code") == "text-indexer-service"
                            and "identity.text_indexers.administer" in set(
                                (get_principal() or {}).get("global_privileges", [])
                            )
                        ):
                            ui.button(
                                render_message("webui.select_role_details.button.open_text_indexers_e325fca4"), icon="manage_search",
                                on_click=select_text_indexers,
                            ).props("outline dense no-caps")
                    else:
                        ui.label(render_message("webui.select_role_details.label.manage_and_assignments_4a3e9ade")).classes("record-action-group-label")
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            ui.button(render_message("webui.select_role_details.button.edit_a1e87f79"), icon="edit", on_click=lambda: open_editor(role, on_saved=refresh, resource_key="roles")).props("outline dense no-caps")
                            ui.button(render_message("webui.select_role_details.button.user_assignments_5033da78"), icon="group", on_click=lambda: show_memberships(role, for_user=False)).props("outline dense no-caps")
                    ui.label(render_message("webui.select_role_details.label.audit_82b2637e")).classes("record-action-group-label")
                    with ui.row().classes("w-full gap-2 flex-wrap"):
                        ui.button(render_message("webui.select_role_details.button.history_bf61825c"), icon="history", on_click=lambda: show_entity_history("roles", role)).props("outline dense no-caps")
                    if not is_builtin:
                        ui.label(render_message("webui.select_role_details.label.lifecycle_1cff3de1")).classes("record-action-group-label")
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            ui.button(render_message("webui.select_role_details.button.activate_93e70c1e") if role["status"] == "inactive" else render_message("webui.select_role_details.button.deactivate_84105425"), icon="toggle_on" if role["status"] == "inactive" else "toggle_off", on_click=change_status).props("outline dense no-caps")
                            ui.button(
                                render_message("webui.select_role_details.button.permanently_delete_307494a2"), icon="delete_forever", color="negative",
                                on_click=lambda: confirm_identity_deletion(
                                    "roles", role, label="role", on_deleted=lambda: select_entity("roles"),
                                ),
                            ).props("outline dense no-caps")
                role_metadata_panel = ui.card().classes(
                    "detail-surface identity-command-metadata shadow-none p-5 gap-4"
                )
                role_metadata_panel.__enter__()
                with ui.grid(columns="auto minmax(0, 1fr) auto").classes("identity-detail-header w-full items-start gap-4"):
                    ui.avatar(icon="badge", color="blue-1", text_color="primary", size="58px")
                    with ui.column().classes("gap-1 min-w-0 break-words"):
                        ui.label(role["name"]).classes("text-xl font-semibold")
                        ui.label(role["code"]).classes("text-primary")
                        if is_builtin:
                            ui.badge(render_message("webui.select_role_details.badge.built_in_13c676c0"), color="blue-grey").props("outline")
                        if role.get("description"): ui.label(role["description"]).classes("text-slate-600")
                    ui.button(
                        render_message("webui.select_role_details.button.back_26071a1c"), icon=None if direction() == "rtl" else "arrow_back",
                        on_click=lambda: breadcrumb_back(lambda: select_entity("roles")),
                    ).props("flat no-caps" + (" icon-right=arrow_forward" if direction() == "rtl" else ""))
                with ui.grid(columns=3).classes("identity-detail-facts w-full gap-4"):
                    assignment_label = render_message("webui.show_organization_structure.select.all_assignments_1a3e1480")
                    for label, value, value_kind in (
                        (entity_metadata_label("Status"), role.get("status"), "status"),
                        (render_message("webui.render_governance_cards.text.effective_status_c7a1dfe1"), role.get("effective_status"), "status"),
                        (entity_metadata_label("Security clearance"), " — ".join(filter(None, (
                            role.get("security_level_code"), role.get("security_level_name"),
                        ))), None),
                        (entity_metadata_label("Profile"), " — ".join(filter(None, (
                            role.get("profile_code"),
                            role.get("profile_name"),
                        ))), "profile"),
                        (entity_metadata_label("Information-governance role"), render_message("webui.render_governance_cards.text.yes_1e245559") if role.get("is_information_governance") else render_message("webui.render_governance_cards.text.no_10013db4"), "governance"),
                        (entity_metadata_label("Organization unit"), " — ".join(filter(None, (
                            role.get("org_unit_code"), role.get("org_unit_name"),
                        ))), "organization"),
                        (entity_metadata_label("Supervising role"), " — ".join(filter(None, (
                            role.get("supervisor_role_code"), role.get("supervisor_role_name"),
                        ))) or None, "supervisor"),
                        (render_message("webui.render_governance_cards.text.roles_assigned_this_level_cdc0781e"), role.get("subordinate_role_count"), None),
                        (assignment_label, role.get("assigned_user_count"), None),
                        (render_message("governance_custody.stat.current_assignments"), role.get("current_assignment_count"), None),
                        (f"{localized_lifecycle_value('future')} · {assignment_label}", role.get("future_assignment_count"), None),
                        (f"{localized_lifecycle_value('expired')} · {assignment_label}", role.get("expired_assignment_count"), None),
                    ):
                        guidance_text = {
                            entity_metadata_label("Status"): render_message("webui.select_role_details.text.set_directly_on_this_role_without_consider_0646bc65"),
                            render_message("webui.render_governance_cards.text.effective_status_c7a1dfe1"): render_message("webui.select_role_details.text.also_includes_inactivity_inherited_from_it_c99dbc46"),
                            entity_metadata_label("Profile"): (
                                render_message("webui.select_role_details.text.all_privileges_is_a_migration_compatibilit_bca70ba7")
                                if role.get("profile_code") == "ALL_PRIVS" else
                                render_message("webui.select_role_details.text.the_role_receives_its_global_capabilities_173ecedf")
                            ),
                            entity_metadata_label("Information-governance role"): (
                                render_message("webui.select_role_details.text.this_role_may_bypass_resource_acls_only_gl_a6785150")
                            ),
                        }.get(label)
                        with ui.column().classes("identity-detail-fact gap-0 border-b border-slate-100 pb-1.5"):
                            ui.label(label).classes("detail-field-label")
                            if value_kind == "organization" and role.get("org_unit_id"):
                                ui.label(str(value)).classes(
                                    "font-medium text-primary cursor-pointer"
                                ).on(
                                    "click",
                                    lambda: select_organization_unit_details(
                                        role["org_unit_id"]
                                    ),
                                ).tooltip(render_message("webui.select_role_details.tooltip.open_organization_unit_de3a3909"))
                            elif value_kind == "supervisor" and role.get("supervisor_role_id"):
                                ui.label(str(value)).classes(
                                    "font-medium text-primary cursor-pointer"
                                ).on(
                                    "click",
                                    lambda: select_role_details(role["supervisor_role_id"]),
                                ).tooltip(render_message("webui.select_role_details.tooltip.open_supervising_role_10bd647e"))
                            else:
                                rendered_value = (
                                    localized_lifecycle_value(value)
                                    if value_kind == "status" and value is not None
                                    else str(value) if value is not None else "—"
                                )
                                ui.label(rendered_value).classes("font-medium")
                            if guidance_text:
                                ui.label(guidance_text).classes("w-full text-[10px] leading-3 text-slate-400")
                role_metadata_panel.__exit__(None, None, None)

            profile_privileges = role.get("profile_privileges") or []
            privileges_by_category: dict[str, list[dict[str, Any]]] = {}
            for privilege in profile_privileges:
                privileges_by_category.setdefault(
                    privilege.get("category") or "other", [],
                ).append(privilege)
            with ui.card().classes("detail-surface shadow-none w-full p-0 gap-0"):
                with ui.row().classes(
                    "w-full items-center gap-3 px-4 py-3 border-b border-slate-200"
                ):
                    with ui.column().classes("gap-0 grow min-w-0"):
                        ui.label(render_message("webui.select_role_details.label.privileges_inherited_from_profile_f70566f2")).classes(
                            "text-base font-semibold"
                        )
                        with ui.row().classes("items-center gap-1 text-xs text-slate-500"):
                            ui.label(render_message("webui.select_role_details.label.granted_by_313bfb40"))
                            ui.label(
                                " — ".join(filter(None, (
                                    role.get("profile_code"), role.get("profile_name"),
                                ))) or render_message("webui.select_role_details.label.unknown_profile_bcf958f1")
                            ).classes("font-semibold text-primary")
                    ui.badge(
                        render_message("webui.select_role_details.badge.profile_privilege_count_privileges_b8629558", profile_privilege_count=len(profile_privileges)), color="primary",
                    ).props("outline")
                if not profile_privileges:
                    ui.label(render_message("webui.select_role_details.label.this_profile_grants_no_privileges_180094b3")).classes(
                        "w-full text-center text-slate-400 py-8"
                    )
                else:
                    category_icons = {
                        "administration": "settings", "aggregation": "folder",
                        "record": "description", "component": "attachment",
                        "exceptional": "warning_amber", "hold": "gavel",
                    }
                    with ui.element("div").classes("role-privilege-groups w-full p-3"):
                        for category, privileges in privileges_by_category.items():
                            with ui.element("section").classes("role-privilege-group"):
                                with ui.element("header").classes(
                                    "role-privilege-group-header w-full gap-2"
                                ):
                                    ui.icon(
                                        category_icons.get(category, "verified_user"),
                                        size="18px",
                                    ).classes("text-primary")
                                    ui.label(
                                        localized_privilege_category(category)
                                    ).classes("role-privilege-group-title text-sm font-semibold")
                                    ui.label(str(len(privileges))).classes(
                                        "role-privilege-group-count text-xs text-slate-500 tabular-nums"
                                    )
                                with ui.element("div").classes("role-privilege-list"):
                                    for privilege in privileges:
                                        with ui.element("div").classes(
                                            "role-privilege-item gap-2"
                                        ):
                                            ui.icon(
                                                "check", color="positive", size="16px",
                                            ).classes("mt-0.5 shrink-0")
                                            with ui.column().classes("role-privilege-copy gap-0 min-w-0"):
                                                ui.label(localized_privilege_name(privilege)).classes(
                                                    "text-xs font-semibold leading-4"
                                                )
                                                ui.label(privilege["code"]).classes(
                                                    "text-[10px] font-mono text-slate-500 "
                                                    "break-all leading-4"
                                                ).tooltip(
                                                    localized_privilege_description(privilege)
                                                )


    return select_role_details
