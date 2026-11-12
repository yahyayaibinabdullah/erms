"""Resource/default ACL editing and contextual-principal paging, scoped to each dialog."""
from __future__ import annotations

from typing import Any, Callable
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message, render_message_plain
import asyncio
import inspect
from dataclasses import dataclass
from .acl_editor import acl_grants_payload, dependents_of, permission_closure
from .authorization_ui import acl_source_label, aggregation_reference_label, operation_label, ordered_permission_catalogue

@dataclass(frozen=True)
class AccessControlDialogs:
    show_acl_editor: Callable
    show_contextual_acl_roles: Callable


def build_access_control_dialogs(
    api, *, principal: Callable, direction: Callable, open_aggregation: Callable,
    show_organization_structure: Callable, bind_remote_relationship_select: Callable, error_message: Callable,
):
    async def show_contextual_acl_roles(resource, entity_id, principal_type) -> None:
        dialog = ui.dialog()
        with dialog, ui.card().classes("w-[560px] max-w-full gap-3"):
            ui.label(
                render_message("authorization.oversight.managers")
                if principal_type == "owning_and_higher_level_unit_managers"
                else render_message("authorization.oversight.file_administrator")
            ).classes("text-lg font-semibold")
            host = ui.column().classes("w-full gap-2")
            state = {"offset": 0, "revision": 0}

            async def load_page(offset=0):
                state["revision"] += 1
                revision = state["revision"]
                try:
                    result = await api.request("GET", f"/api/v1/{resource}/{entity_id}/acl-contextual-principals", params={
                        "principal_type": principal_type, "limit": 25, "offset": offset,
                    })
                except ApiError as error:
                    if dialog.value and revision == state["revision"]:
                        ui.notify(error_message(error), color="negative", close_button=True)
                    return
                if not dialog.value or revision != state["revision"]:
                    return
                state["offset"] = offset
                host.clear()
                with host:
                    if not result["items"]:
                        ui.label(render_message("authorization.oversight.no_matches"))
                    for item in result["items"]:
                        ui.label(f'{item["org_unit_code"]} — {item["org_unit_name"]}').classes("text-sm font-medium")
                        if item["role_id"] is not None:
                            ui.label(f'{item["role_code"]} — {item["role_name"]}').classes("text-sm")
                            if not item["active"]:
                                ui.label(render_message("authorization.oversight.inactive")).classes("text-xs text-amber-900")
                        else:
                            ui.label(render_message("authorization.oversight.no_designation")).classes("text-xs text-slate-500")
                    with ui.row():
                        previous = ui.button(render_message("authorization.oversight.previous"), on_click=lambda: load_page(max(0, state["offset"]-25))).props("flat no-caps")
                        previous.set_enabled(offset>0)
                        following = ui.button(render_message("authorization.oversight.next"), on_click=lambda: load_page(state["offset"]+25)).props("flat no-caps")
                        following.set_enabled(result["has_more"])
            ui.button(render_message("authorization.oversight.close"), on_click=dialog.close).props("flat no-caps")
        dialog.open()
        await load_page()


    async def show_acl_editor(
        resource: str, entity_id: int, *, scope: str = "resource",
        on_saved: Callable[[], Any] | None = None,
    ) -> None:
        """Edit a complete ACL atomically; inherited and dormant sets stay visually distinct."""
        resource_type = "record" if resource == "records" or scope == "record" else "aggregation"
        try:
            catalogue = await api.permissions_catalogue(resource_type)
            if scope == "resource":
                acl = await api.resource_acl(resource, entity_id)
                displayed = acl["override_acl"]
                version = acl["resource_acl_version"]
            else:
                child_type = "record" if scope == "record" else "aggregation"
                acl = await api.child_acl(entity_id, child_type)
                displayed = acl.get("custom_acl", acl.get("effective_acl", []))
                version = acl["version"]
            selected_role_ids = sorted({
                int(item["role_id"]) for item in displayed
                if item.get("principal_type") == "role" and item.get("role_id") is not None
            })
            roles = await asyncio.gather(*(
                api.get("roles", identifier) for identifier in selected_role_ids
            ))
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return

        source_aggregation: dict[str, Any] | None = None
        edited_aggregation: dict[str, Any] | None = None
        owner_resource: dict[str, Any] | None = None
        try:
            if scope != "resource" or resource_type == "aggregation":
                edited_aggregation = await api.get("aggregations", entity_id)
                owner_resource = edited_aggregation
            else:
                owner_resource = await api.get("records", entity_id)
        except ApiError:
            edited_aggregation = None
            owner_resource = None
        owner_name = (
            owner_resource.get("owning_org_unit_name")
            if owner_resource else "this resource's organizational unit"
        )
        if owner_resource and owner_resource.get("owning_org_unit_id") is not None:
            try:
                owner_unit = await api.get("org-units", int(owner_resource["owning_org_unit_id"]))
                owner_name = (
                    (owner_unit.get("localized") or {}).get("name")
                    or owner_unit.get("name") or owner_name
                )
            except ApiError:
                pass  # Retain the resource's owner name if the unit cannot be read.
        source_aggregation_id = acl.get("source_resource_id") or acl.get("effective_acl_source_id")
        if source_aggregation_id:
            try:
                source_aggregation = await api.get("aggregations", int(source_aggregation_id))
            except (ApiError, TypeError, ValueError):
                source_aggregation = None

        options = {
            item["code"]: operation_label(item["code"])
            for item in ordered_permission_catalogue(catalogue, resource_type)
        }
        role_options = {item["id"]: f"{item['code']} — {item['name']}" for item in roles}
        principals: list[dict[str, Any]] = [dict(item) for item in displayed]
        dialog_title = (
            render_message("webui.show_acl_editor.text.default_child_aggregation_acl_bdf05df3")
            if scope == "aggregation"
            else render_message("webui.show_acl_editor.text.default_child_record_acl_316d787d")
            if scope == "record"
            else render_message("webui.show_acl_editor.text.access_control_list_d8401318")
        )
        dialog = ui.dialog()
        with dialog, ui.card().classes("max-h-[92vh] p-0 gap-0").style(
            "width: min(1050px, 90vw); max-width: none"
        ):
            with ui.row().classes("w-full items-center px-5 py-4 border-b border-slate-200"):
                ui.icon("policy", color="primary")
                ui.label(dialog_title).classes("text-xl font-semibold grow")
                ui.button(icon="close", on_click=dialog.close).props("flat round dense")
            with ui.element("div").classes(
                "w-full h-[680px] max-h-[calc(92vh-142px)] overflow-y-auto overflow-x-hidden px-5 py-4"
            ):
                if scope == "resource" and acl.get("inherit_acl_from_parent") is not None:
                    with ui.row().classes("w-full items-start gap-3 rounded-lg border border-blue-100 bg-blue-50 p-3"):
                        ui.icon("account_tree", color="primary")
                        with ui.column().classes("gap-0 grow"):
                            ui.label(render_message("webui.show_acl_editor.label.effective_source_acl_source_label_de94ce9b", acl_source_label=acl_source_label(acl))).classes("font-semibold text-slate-800")
                            if source_aggregation is not None:
                                ui.label(aggregation_reference_label(source_aggregation)).classes("text-sm text-slate-700")
                            ui.label(
                                render_message("webui.show_acl_editor.label.a_root_aggregation_has_no_parent_acl_so_th_5e629db4")
                                if edited_aggregation is not None and edited_aggregation.get("parent_aggregation_id") is None else
                                render_message("webui.show_acl_editor.label.inherited_access_is_evaluated_live_a_local_d5ec9a6a")
                            ).classes("text-xs text-slate-600")

                        if source_aggregation is not None:
                            async def open_editor_acl_source() -> None:
                                dialog.close()
                                await open_aggregation(source_aggregation)

                            ui.button(render_message("webui.show_acl_editor.button.open_81b1e6e8"), icon="open_in_new", on_click=open_editor_acl_source).props(
                                "flat dense no-caps"
                            )
                    inherit = ui.switch(render_message("authorization.acl.inherit_from_parent"), value=acl["inherit_acl_from_parent"])
                    if edited_aggregation is not None and edited_aggregation.get("parent_aggregation_id") is None:
                        inherit.set_enabled(False)
                        inherit.tooltip(render_message("webui.show_acl_editor.tooltip.a_root_aggregation_has_no_parent_acl_to_in_8d57d004"))
                        ui.label(
                            render_message("webui.show_acl_editor.label.this_is_a_root_aggregation_so_its_acl_must_bc32d08b")
                        ).classes("text-xs text-slate-500 ml-2")
                    if acl.get("override_acl_is_dormant"):
                        ui.label(render_message("webui.show_acl_editor.label.the_local_override_shown_below_is_dormant_980a9af4")).classes("text-xs text-slate-500")
                else:
                    inherit = None
                if scope == "aggregation":
                    mode = ui.select(
                        {"mirror_resource_acl": render_message("webui.show_acl_editor.select.mirror_this_aggregation_s_effective_resour_7d0607b1"), "custom": render_message("webui.show_acl_editor.select.use_custom_default_acl_497bc7b9")},
                        value=acl["mode"], label=render_message("webui.show_acl_editor.select.default_child_aggregation_acl_mode_751a7cee"),
                    ).classes("w-full mt-3")
                    ui.label(render_message("webui.show_acl_editor.label.mirror_is_a_live_reference_the_custom_defa_1151569c")).classes("text-xs text-slate-500")
                else:
                    mode = None
                state_banner = ui.column().classes("w-full mt-3")
                editor = ui.column().classes("w-full gap-3 mt-4")
                editor_controls: list[Any] = []
                permission_controls: dict[int, dict[str, Any]] = {}
                matrix_control: dict[str, Any] = {}

                def reset_matrix_scroll() -> None:
                    matrix_control["area"].scroll_to(
                        percent=1 if direction() == "rtl" else 0,
                        axis="horizontal",
                    )

                # Measure after the dialog is shown, not while its width is zero.
                dialog.on("show", reset_matrix_scroll)

                def is_dormant() -> bool:
                    if inherit is not None:
                        return bool(inherit.value)
                    if mode is not None:
                        return mode.value == "mirror_resource_acl"
                    return False

                def activate_local_acl() -> None:
                    if inherit is not None:
                        inherit.value = False
                        inherit.update()
                    elif mode is not None:
                        mode.value = "custom"
                        mode.update()
                    render_acl_state()
                    render_principals()

                def render_acl_state() -> None:
                    state_banner.clear()
                    with state_banner:
                        if is_dormant():
                            with ui.card().classes("w-full shadow-none border border-amber-200 bg-amber-50 p-3"):
                                with ui.row().classes("w-full items-start gap-3"):
                                    ui.icon("visibility_off", color="amber-9")
                                    with ui.column().classes("gap-0 grow"):
                                        ui.label(
                                            render_message("webui.render_acl_state.label.dormant_local_acl_not_currently_used_412e5d6f")
                                            if inherit is not None else
                                            render_message("webui.render_acl_state.label.dormant_custom_default_acl_not_currently_u_e9730cb4")
                                        ).classes("font-semibold text-amber-950")
                                        ui.label(
                                            render_message("webui.render_acl_state.label.effective_access_comes_from_the_parent_whi_c5f7c617")
                                            if inherit is not None else
                                            render_message("webui.render_acl_state.label.child_aggregations_currently_mirror_this_a_12962422")
                                        ).classes("text-xs text-amber-900")
                                    ui.button(
                                        render_message("webui.render_acl_state.button.use_local_acl_43acc939") if inherit is not None else render_message("webui.render_acl_state.button.use_custom_default_acl_01cde39d"),
                                        icon="edit", on_click=activate_local_acl,
                                    ).props("outline no-caps color=amber-10")
                        else:
                            with ui.row().classes("w-full items-center gap-2 rounded-lg border border-green-200 bg-green-50 p-3"):
                                ui.icon("check_circle", color="positive")
                                ui.label(
                                    render_message("webui.render_acl_state.label.this_local_acl_is_active_and_changes_here_4f1b1dd3")
                                    if scope == "resource" else
                                    render_message("webui.render_acl_state.label.this_custom_default_acl_is_active_and_chan_91f39756")
                                ).classes("text-sm font-medium text-green-900")

                def render_principals() -> None:
                    editor.clear()
                    editor_controls.clear()
                    permission_controls.clear()
                    with editor:
                        with ui.row().classes("w-full items-center gap-2"):
                            ui.label(
                                render_message(
                                    "webui.render_principals.label.assigned_principal_count",
                                    count=len(principals),
                                )
                            ).classes("text-sm text-slate-500 grow")
                            add_role_button = ui.button(render_message("webui.render_principals.button.add_role_504bd3b3"), icon="person_add", on_click=add_role).props("outline no-caps")
                            editor_controls.append(add_role_button)
                            if not any(item["principal_type"] == "everyone" for item in principals):
                                add_everyone_button = ui.button(
                                    render_message("webui.render_principals.button.add_everyone_c070438a"), icon="groups",
                                    on_click=lambda: (
                                        principals.insert(0, {"principal_type": "everyone", "role_id": None, "permission_codes": []}),
                                        render_principals(),
                                    ),
                                ).props("outline no-caps")
                                editor_controls.append(add_everyone_button)
                            if not any(
                                item["principal_type"] == "org_unit_members"
                                for item in principals
                            ):
                                add_org_members_button = ui.button(
                                    render_message("webui.render_principals.button.add_all_org_unit_members_47c111a3"), icon="corporate_fare",
                                    on_click=lambda: (
                                        principals.insert(0, {
                                            "principal_type": "org_unit_members",
                                            "role_id": None,
                                            "permission_codes": [],
                                        }),
                                        render_principals(),
                                    ),
                                ).props("outline no-caps")
                                editor_controls.append(add_org_members_button)

                            for contextual_type in ("owning_and_higher_level_unit_managers", "effective_file_administrator"):
                                if not any(item["principal_type"] == contextual_type for item in principals):
                                    button = ui.button(
                                        render_message("authorization.oversight.add_managers")
                                        if contextual_type == "owning_and_higher_level_unit_managers"
                                        else render_message("authorization.oversight.add_file_administrator"),
                                        icon="corporate_fare",
                                        on_click=lambda _, kind=contextual_type: (
                                            principals.append({"principal_type": kind, "role_id": None, "permission_codes": []}),
                                            render_principals(),
                                        ),
                                    ).props("outline no-caps")
                                    editor_controls.append(button)

                        with ui.row().classes("w-full items-center gap-2 text-slate-500"):
                            ui.icon("groups", size="17px")
                            ui.label(
                                render_message("webui.render_principals.label.everyone_represents_all_authenticated_user_1d9d9a84")
                            ).classes("text-xs")
                        with ui.row().classes("w-full items-center gap-2 text-slate-500"):
                            ui.icon("corporate_fare", size="17px")
                            ui.label(
                                render_message("webui.render_principals.label.all_org_unit_members_means_everyone_curren_05b026f1", owner_name=owner_name)
                            ).classes("text-xs")

                        ui.label(
                            render_message("webui.render_principals.label.select_permissions_by_principal_required_p_9d029dd3")
                        ).classes("text-xs text-slate-500 mb-2")
                        # Use NiceGUI's scroll area, as in the dashboard lists,
                        # so horizontal scrolling remains discoverable on systems
                        # that hide native scrollbars.
                        matrix = ui.scroll_area().classes(
                            "w-full rounded-xl border border-slate-200 bg-white"
                        ).props("visible dir=ltr").style("height: 300px")
                        matrix_control["area"] = matrix
                        matrix_width = 310 + (len(options) * 132)
                        with matrix:
                            # The scroll widget uses the framework's LTR scroll
                            # coordinates; document RTL alone does not switch its
                            # drag calculations. Keep that viewport LTR and give
                            # the content its actual direction via public props.
                            with ui.column().classes("gap-0").props(
                                f'dir={direction()}'
                            ).style(f"min-width: {matrix_width}px"):
                                # ui.row has no direction argument. Its inherited
                                # RTL direction already mirrors the cells; bypass
                                # the global .row reversal to avoid mirroring twice.
                                with ui.row().classes(
                                    "w-full gap-0 no-wrap border-b border-slate-200 bg-slate-50"
                                ).style("position: sticky; top: 0; z-index: 30; flex-direction: row"):
                                    with ui.element("div").classes(
                                        "w-[310px] shrink-0 self-stretch px-3 py-3 bg-slate-50 border-r border-slate-200"
                                    ).style("position: sticky; inset-inline-start: 0; z-index: 35"):
                                        ui.label(render_message("webui.render_principals.label.principal_6f352deb")).classes("text-xs font-semibold uppercase tracking-wide text-slate-500")
                                    for code, name in options.items():
                                        with ui.element("div").classes(
                                            "w-[132px] shrink-0 self-stretch px-2 py-3 border-r border-slate-200 text-center"
                                        ):
                                            ui.label(name).classes(
                                                "text-xs font-semibold leading-tight text-slate-600"
                                            ).tooltip(name)

                                if not principals:
                                    ui.label(
                                        render_message("webui.render_principals.label.no_principals_are_present_add_a_role_every_a101b46b")
                                    ).classes("m-5 text-sm text-slate-500")

                                for index, acl_principal in enumerate(principals):
                                    selected = set(acl_principal.get("permission_codes", []))
                                    row_controls: dict[str, Any] = {}
                                    permission_controls[id(acl_principal)] = row_controls
                                    with ui.row().classes(
                                        "w-full gap-0 no-wrap border-b border-slate-100 last:border-b-0 hover:bg-blue-50/30"
                                    ).style("flex-direction: row"):
                                        with ui.element("div").classes(
                                            "w-[310px] shrink-0 min-h-[62px] bg-white border-r border-slate-200 px-2 py-1"
                                        ).style("position: sticky; inset-inline-start: 0; z-index: 20"):
                                            with ui.row().classes("w-full no-wrap items-center gap-2"):
                                                ui.icon(
                                                    {
                                                        "everyone": "groups",
                                                        "org_unit_members": "corporate_fare",
                                                    }.get(acl_principal["principal_type"], "badge"),
                                                    color="primary", size="20px",
                                                )
                                                if acl_principal["principal_type"] == "everyone":
                                                    with ui.column().classes("gap-0 grow min-w-0"):
                                                        ui.label(render_message("webui.render_principals.label.everyone_8d69f084")).classes("font-semibold")
                                                        ui.label(render_message("webui.render_principals.label.all_authenticated_users_fb3e7d95")).classes("text-xs text-slate-500")
                                                elif acl_principal["principal_type"] == "org_unit_members":
                                                    with ui.column().classes("gap-0 grow min-w-0"):
                                                        ui.label(render_message("webui.render_principals.label.all_org_unit_members_53d5b79a")).classes("font-semibold")
                                                        ui.label(
                                                            render_message("webui.render_principals.label.everyone_currently_working_in_owner_name_271a9a37", owner_name=owner_name)
                                                        ).classes("text-xs text-slate-500")
                                                elif acl_principal["principal_type"] in {"owning_and_higher_level_unit_managers", "effective_file_administrator"}:
                                                    with ui.column().classes("gap-0 grow min-w-0"):
                                                        ui.label(
                                                            render_message("authorization.oversight.managers")
                                                            if acl_principal["principal_type"] == "owning_and_higher_level_unit_managers"
                                                            else render_message("authorization.oversight.file_administrator")
                                                        ).classes("font-semibold")
                                                        ui.label(render_message("authorization.oversight.dynamic", owner_name=owner_name)).classes("text-xs text-slate-500")
                                                        if "organization.browse" in (principal() or {}).get("global_privileges", []):
                                                            ui.button(
                                                                render_message("authorization.oversight.show_roles"),
                                                                on_click=lambda _, kind=acl_principal["principal_type"]: show_contextual_acl_roles(resource, entity_id, kind),
                                                            ).props("flat dense no-caps")
                                                else:
                                                    role_picker = ui.select(
                                                        role_options, value=acl_principal.get("role_id"),
                                                    ).props(
                                                        "dense outlined options-dense use-input input-debounce=0"
                                                    ).classes("grow min-w-0")
                                                    bind_remote_relationship_select(
                                                        role_picker,
                                                        resource="roles",
                                                        search_fields=("code", "name"),
                                                        label_fields=("code", "name"),
                                                    )
                                                    role_picker.on_value_change(
                                                        lambda event, item=acl_principal: item.update(role_id=event.value)
                                                    )
                                                    editor_controls.append(role_picker)
                                                    browse_role_button = ui.button(
                                                        icon="account_tree",
                                                        on_click=lambda _, control=role_picker: show_organization_structure(
                                                            selection_mode="role", target_control=control,
                                                        ),
                                                    ).props(
                                                        'flat round dense aria-label=' + repr(render_message("webui.render_principals.accessible_name.browse_roles_dac5f03b"))
                                                    ).tooltip(render_message("webui.render_principals.tooltip.browse_organization_structure_for_a_role_ce297699"))
                                                    editor_controls.append(browse_role_button)
                                                remove_button = ui.button(
                                                    icon="delete_outline", color="negative",
                                                    on_click=lambda _, i=index: (principals.pop(i), render_principals()),
                                                ).props("flat round dense").tooltip(render_message("webui.render_principals.tooltip.remove_principal_8dc60c3b"))
                                                editor_controls.append(remove_button)

                                        for code in options:
                                            with ui.element("div").classes(
                                                "w-[132px] shrink-0 min-h-[62px] border-r border-slate-100 flex items-center justify-center"
                                            ):
                                                checkbox = ui.checkbox(value=code in selected).props("dense")
                                                checkbox.tooltip(options[code])
                                                row_controls[code] = checkbox
                                                editor_controls.append(checkbox)

                                                def update_permission(
                                                    event: Any, item=acl_principal, permission=code,
                                                ) -> None:
                                                    current = set(item.get("permission_codes", []))
                                                    if bool(event.value):
                                                        updated = permission_closure(current | {permission})
                                                        added = updated - current - {permission}
                                                        if added:
                                                            ui.notify(
                                                                render_message("webui.update_permission.notify.required_prerequisite_permissions_were_add_7b363cdf"),
                                                                color="info",
                                                            )
                                                    else:
                                                        removed_dependents = dependents_of(permission, current)
                                                        updated = current - {permission} - removed_dependents
                                                        if removed_dependents:
                                                            ui.notify(
                                                                render_message("webui.update_permission.notify.dependent_permissions_were_also_removed_9b480b90"),
                                                                color="info",
                                                            )
                                                    item["permission_codes"] = sorted(updated)
                                                    for permission_code, control in permission_controls.get(id(item), {}).items():
                                                        expected = permission_code in updated
                                                        if bool(control.value) != expected:
                                                            control.value = expected
                                                            control.update()

                                                checkbox.on_value_change(update_permission)

                        if dialog.value:
                            reset_matrix_scroll()

                def add_role() -> None:
                    if any(
                        item["principal_type"] == "role" and item.get("role_id") is None
                        for item in principals
                    ):
                        ui.notify(render_message("webui.add_role.notify.select_the_blank_role_before_adding_anothe_ccce15f6"), color="warning")
                        return
                    principals.append({"principal_type": "role", "role_id": None, "permission_codes": []})
                    render_principals()

                def apply_editor_state() -> None:
                    dormant = is_dormant()
                    editor.classes(replace="w-full gap-3 mt-4 " + ("opacity-55" if dormant else ""))
                    for control in editor_controls:
                        control.set_enabled(not dormant)

                original_render_principals = render_principals
                def render_principals() -> None:
                    original_render_principals()
                    apply_editor_state()

                if inherit is not None:
                    inherit.on_value_change(lambda _: (render_acl_state(), render_principals()))
                if mode is not None:
                    mode.on_value_change(lambda _: (render_acl_state(), render_principals()))
                render_acl_state()
                render_principals()
                reason = ui.input(render_message("webui.show_acl_editor.input.reason_for_access_change_27d12eef")).classes("w-full mt-4")

            async def save_acl() -> None:
                if any(
                    item["principal_type"] == "role" and item.get("role_id") is None
                    for item in principals
                ):
                    ui.notify(render_message("webui.save_acl.notify.select_a_role_for_every_role_row_before_sa_ac946d6d"), color="warning")
                    return
                if not reason.value or not str(reason.value).strip():
                    ui.notify(render_message("webui.save_acl.notify.a_reason_is_required_29a5d403"), color="warning"); return
                payload: dict[str, Any] = {
                    "version": version,
                    "grants": acl_grants_payload(principals),
                    "reason": str(reason.value).strip(),
                }
                if inherit is not None: payload["inherit_acl_from_parent"] = inherit.value
                if mode is not None: payload["mode"] = mode.value
                async def apply_change() -> None:
                    try:
                        if scope == "resource": await api.replace_resource_acl(resource, entity_id, payload)
                        else: await api.replace_child_acl(entity_id, "record" if scope == "record" else "aggregation", payload)
                        dialog.close(); ui.notify(render_message("webui.apply_change.notify.access_control_list_updated_2f758b3c"), color="positive")
                        if on_saved:
                            result = on_saved()
                            if inspect.isawaitable(result): await result
                    except ApiError as error:
                        ui.notify(error_message(error), color="negative", close_button=True)
                try:
                    if scope == "resource":
                        await apply_change(); return
                    impact = await api.preview_child_acl(
                        entity_id, "record" if scope == "record" else "aggregation", payload,
                    )
                    confirmation = ui.dialog()
                    with confirmation, ui.card().classes("w-[520px] max-w-full"):
                        ui.label(render_message("webui.save_acl.label.apply_inherited_access_change_96b5990f")).classes("text-lg font-semibold")
                        ui.label(
                            render_message("webui.save_acl.label.this_changes_added_grants_grants_added_and_91334da7", added_grants=impact['added_grants'], removed_grants=impact['removed_grants'], get=impact.get('affected_aggregation_count', 0), get_2=impact.get('affected_record_count', 0), potentially_affected_user_count=impact['potentially_affected_user_count'])
                        ).classes("text-sm text-slate-600")
                        with ui.row().classes("w-full justify-end gap-2"):
                            ui.button(render_message("webui.save_acl.button.cancel_5d123d5d"), on_click=confirmation.close).props("flat no-caps")
                            async def confirm_apply() -> None:
                                confirmation.close(); await apply_change()
                            ui.button(render_message("webui.save_acl.button.apply_change_16aede93"), icon="check", on_click=confirm_apply).props("unelevated no-caps")
                    confirmation.open()
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)
            with ui.row().classes("w-full justify-end gap-2 px-5 py-4 border-t border-slate-200"):
                ui.button(render_message("webui.show_acl_editor.button.cancel_256f9c91"), on_click=dialog.close).props("flat no-caps")
                ui.button(render_message("webui.show_acl_editor.button.save_acl_a2306fa4"), icon="save", on_click=save_acl).props("unelevated no-caps")
        dialog.open()


    return AccessControlDialogs(show_acl_editor=show_acl_editor, show_contextual_acl_roles=show_contextual_acl_roles)
