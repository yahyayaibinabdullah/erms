"""Authorization explanations and bounded subject selection; server decisions remain authoritative."""
from __future__ import annotations

from typing import Any, Callable
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message, render_message_plain
import asyncio
from nicegui import background_tasks
from .i18n_catalogue import strip_diagnostic_metadata
from .entity_selectors import relationship_search_query
from .authorization_ui import (OPERATIONS, operation_label, acl_source_label, aggregation_reference_label, decision_code_label, gate_detail, gate_label, security_level_label)
from .security_administration import localized_privilege_name


def build_access_explanation(
    api, *, principal: Callable, open_aggregation: Callable, localized_editor_entity: Callable, error_message: Callable,
):
    async def show_access_explanation(resource_type: str, entity_id: int) -> None:
        """Explain every authorization gate without treating the UI as an enforcement boundary."""
        privileges = set((principal() or {}).get("global_privileges", []))
        can_examine_others = "authorization.explain" in privileges
        operations = {code: operation_label(code) for code in OPERATIONS[resource_type]}
        dialog = ui.dialog()
        result_host: Any = None
        explanation_request = {"sequence": 0}
        with dialog, ui.card().classes("w-[820px] max-w-[95vw] max-h-[90vh] p-0 gap-0"):
            with ui.row().classes("w-full items-center border-b border-slate-200 px-5 py-4"):
                ui.icon("fact_check", color="primary")
                with ui.column().classes("gap-0 grow"):
                    ui.label(render_message("webui.show_access_explanation.label.access_explanation_054e47dd")).classes("text-xl font-semibold")
                    ui.label(render_message("webui.show_access_explanation.label.shows_which_policy_gates_and_roles_contrib_b13484e9")).classes("text-xs text-slate-500")
                ui.button(icon="close", on_click=dialog.close).props('flat round dense aria-label=' + repr(render_message("webui.show_access_explanation.accessible_name.close_access_explanation_347ccd8f")))
            with ui.row().classes("w-full items-end gap-3 px-5 pt-4"):
                operation = ui.select(operations, value=OPERATIONS[resource_type][0], label=render_message("webui.show_access_explanation.select.operation_709c7c46")).props("outlined").classes("grow")
                user = None
                if can_examine_others:
                    with ui.column().classes("grow gap-1"):
                        user = ui.select(
                            {}, label=render_message("webui.show_access_explanation.select.explain_for_another_user_optional_c0131ea6"),
                            clearable=True, with_input=True,
                        ).props("outlined input-debounce=0").classes("w-full")
                        more_users = ui.button(render_message("webui.render_collection.button.load_more_755f4879"), icon="more_horiz").props("flat dense no-caps")
                        more_users.set_visibility(False)
                    picker = {"revision": 0, "query": "", "offset": 0, "task": None}

                    async def load_users(query: str = "", *, append: bool = False) -> None:
                        picker["revision"] += 1
                        revision = picker["revision"]
                        offset = picker["offset"] if append else 0
                        try:
                            rows = await api.explainable_users(query=query, limit=26, offset=offset)
                        except ApiError as error:
                            ui.notify(error_message(error), color="negative", close_button=True)
                            return
                        if revision != picker["revision"] or not dialog.value:
                            return
                        retained = dict(user.options) if append else {
                            key: label for key, label in user.options.items() if key == user.value
                        }
                        user.set_options({**retained, **{
                            item["id"]: f"{item['name']} — {item.get('email') or '—'}" for item in rows[:25]
                        }})
                        picker.update(query=query, offset=offset + len(rows[:25]))
                        more_users.set_visibility(len(rows) > 25)

                    def search_users(event: Any) -> None:
                        query = relationship_search_query(user, event.args)
                        if query is None:
                            return
                        picker["revision"] += 1
                        more_users.set_visibility(False)
                        if picker["task"] is not None:
                            picker["task"].cancel()
                        async def delayed() -> None:
                            await asyncio.sleep(0.2)
                            await load_users(strip_diagnostic_metadata(query).strip())
                        picker["task"] = background_tasks.create(delayed())
                    user.on("input-value", search_users)
                    user.on("popup-show", lambda: load_users() if not user.options else None)
                    more_users.on("click", lambda: load_users(picker["query"], append=True))
                run = ui.button(render_message("webui.show_access_explanation.button.explain_46823543"), icon="play_arrow").props("unelevated no-caps")
            result_host = ui.scroll_area().classes("w-full h-[520px] px-5 py-4")

            async def load_explanation() -> None:
                explanation_request["sequence"] += 1
                request_sequence = explanation_request["sequence"]
                selected_operation = operation.value
                try:
                    result = await api.explain_access({
                        "resource_type": resource_type, "resource_id": entity_id,
                        "operation": selected_operation,
                        **({"user_id": user.value} if user is not None and user.value else {}),
                    })
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True); return
                if (
                    request_sequence != explanation_request["sequence"]
                    or selected_operation != operation.value
                ):
                    return
                source_aggregation: dict[str, Any] | None = None
                source_aggregation_id = result.get("acl", {}).get("source_resource_id")
                if source_aggregation_id:
                    try:
                        source_aggregation = await api.get("aggregations", int(source_aggregation_id))
                    except (ApiError, TypeError, ValueError):
                        # A source ancestor can legitimately be hidden by the same
                        # authorization policy this dialog is explaining.
                        source_aggregation = None
                async def localize_explanation_entity(resource: str, identifier: int) -> dict[str, Any]:
                    try:
                        return await api.get(resource, identifier)
                    except ApiError:
                        return {}

                roles = {item["role_id"]: dict(item) for item in result["subject"]["effective_roles"]}
                references = [("roles", role_id) for role_id in roles]
                level_fields = [name for name in ("effective_security_level", "required_security_level")
                                if (result.get(name) or {}).get("id") is not None]
                references.extend(("security-levels", result[name]["id"]) for name in level_fields)
                localized_rows = await asyncio.gather(*(
                    localize_explanation_entity(kind, identifier) for kind, identifier in references
                ))
                for role_id, localized in zip(roles, localized_rows):
                    roles[role_id]["role_name"] = (
                        (localized.get("localized") or {}).get("name")
                        or localized.get("name") or roles[role_id].get("role_name")
                    )
                for name, localized in zip(level_fields, localized_rows[len(roles):]):
                    if localized:
                        result[name] = localized
                if request_sequence != explanation_request["sequence"] or selected_operation != operation.value:
                    return
                result_host.clear()
                with result_host:
                    with ui.row().classes(
                        "w-full items-center gap-3 rounded-xl border p-4 " +
                        ("border-green-200 bg-green-50" if result["allowed"] else "border-red-200 bg-red-50")
                    ):
                        ui.icon("check_circle" if result["allowed"] else "cancel", color="positive" if result["allowed"] else "negative", size="28px")
                        with ui.column().classes("gap-0 grow"):
                            ui.label(render_message("webui.load_explanation.label.allowed_4d6e5631") if result["allowed"] else render_message("webui.load_explanation.label.denied_c4e96002")).classes("text-lg font-semibold")
                            ui.label(decision_code_label(result["decision_code"])).classes("text-sm text-slate-600")
                    ui.label(render_message("webui.load_explanation.label.decision_gates_1847ec0e")).classes("text-base font-semibold mt-4")
                    for gate in result["gates"]:
                        with ui.row().classes("w-full items-start gap-3 py-2 border-b border-slate-100"):
                            ui.icon("check_circle" if gate["passed"] else "cancel", color="positive" if gate["passed"] else "negative")
                            with ui.column().classes("gap-0 grow"):
                                ui.label(gate_label(gate["gate"])).classes("font-medium")
                                ui.label(gate_detail(gate)).classes("text-xs text-slate-500")
                    constraint_labels = {
                        "deletion": render_message("authorization.explanation.constraint.deletion"),
                        "metadata_change": render_message("authorization.explanation.constraint.metadata_change"),
                        "movement": render_message("authorization.explanation.constraint.movement"),
                        "addition": render_message("authorization.explanation.constraint.addition"),
                        "removal": render_message("authorization.explanation.constraint.removal"),
                        "replacement": render_message("authorization.explanation.constraint.replacement"),
                        "reordering": render_message("authorization.explanation.constraint.reordering"),
                        "change": render_message("authorization.explanation.constraint.change"),
                        "direct": render_message("authorization.explanation.constraint.direct"),
                        "inherited": render_message("authorization.explanation.constraint.inherited"),
                        "both": render_message("authorization.explanation.constraint.both"),
                        "unknown": render_message("authorization.explanation.constraint.unknown"),
                    }
                    constraints = result.get("resource_state_constraints", [])
                    if constraints:
                        ui.label(render_message("webui.load_explanation.label.resource_state_restrictions_2f05b5a7")).classes("text-base font-semibold mt-4")
                        for constraint in constraints:
                            effect = constraint_labels.get(constraint.get("effect"), constraint_labels["change"])
                            with ui.column().classes("w-full gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3"):
                                with ui.row().classes("items-center gap-2"):
                                    ui.icon("gavel", color="warning")
                                    ui.label(
                                        render_message("webui.load_explanation.label.an_effective_legal_hold_prevents_this_reso_bc46e497", resource_type=localized_editor_entity("aggregations" if resource_type == "aggregation" else "records", resource_type), effect=effect)
                                    ).classes("font-medium text-amber-900")
                                ui.label(
                                    render_message("webui.load_explanation.label.coverage_get_get_2_effective_hold_s_7dc8ce69", get=constraint_labels.get(constraint.get('source'), constraint_labels['unknown']), get_2=constraint.get('effective_hold_count', 0))
                                ).classes("text-xs text-amber-800")
                                for hold in constraint.get("holds", []):
                                    preservation = render_message("authorization.explanation.preservation") if hold.get("preserve_resource_state") else ""
                                    ui.label(
                                        render_message("webui.load_explanation.label.get_get_2_get_3_preservation_8736fc35", get=hold.get('code', ''), get_2=hold.get('name', ''), get_3=constraint_labels.get(hold.get('source'), constraint_labels['unknown']), preservation=preservation)
                                    ).classes("text-sm text-amber-900")
                    ui.label(render_message("webui.load_explanation.label.contributing_context_eeadfa0a")).classes("text-base font-semibold mt-4")
                    with ui.grid(columns=2).classes("w-full gap-3"):
                        with ui.column().classes("gap-0 rounded-lg border border-slate-200 p-3"):
                            ui.label(render_message("webui.load_explanation.label.effective_clearance_db68dd23")).classes(
                                "text-xs font-semibold uppercase tracking-wide text-slate-500"
                            )
                            ui.label(
                                security_level_label(result.get("effective_security_level"))
                            ).classes("text-sm font-medium text-slate-800")
                        with ui.column().classes("gap-0 rounded-lg border border-slate-200 p-3"):
                            ui.label(render_message("webui.load_explanation.label.required_clearance_32337131")).classes(
                                "text-xs font-semibold uppercase tracking-wide text-slate-500"
                            )
                            ui.label(
                                security_level_label(result.get("required_security_level"))
                            ).classes("text-sm font-medium text-slate-800")
                    with ui.column().classes("w-full gap-1 rounded-lg border border-slate-200 bg-slate-50 p-3"):
                        ui.label(render_message("webui.load_explanation.label.acl_source_6a8f565e")).classes("text-xs font-semibold uppercase tracking-wide text-slate-500")
                        ui.label(
                            acl_source_label(result.get("acl", {}))
                        ).classes("text-sm font-medium text-slate-800")
                        if source_aggregation is not None:
                            with ui.row().classes("w-full items-center gap-2"):
                                ui.icon("folder", color="primary", size="18px")
                                ui.label(
                                    aggregation_reference_label(source_aggregation)
                                ).classes("text-sm text-slate-700 grow")

                                async def open_acl_source() -> None:
                                    dialog.close()
                                    await open_aggregation(source_aggregation)

                                ui.button(render_message("webui.load_explanation.button.open_6153e24c"), icon="open_in_new", on_click=open_acl_source).props(
                                    "flat dense no-caps"
                                )
                        elif source_aggregation_id:
                            ui.label(
                                render_message("webui.load_explanation.label.aggregation_reference_source_aggregation_i_f8ac63d4", source_aggregation_id=source_aggregation_id)
                            ).classes("text-xs text-slate-500")
                    contributors = result["contributors"]

                    def contributor_heading(title: str, code: str, icon: str) -> None:
                        with ui.row().classes("w-full items-start gap-3"):
                            ui.icon(icon, color="primary", size="20px").classes("mt-1")
                            with ui.column().classes("gap-0 grow min-w-0"):
                                ui.label(title).classes("text-sm font-semibold text-slate-800")
                                ui.label(code).classes("text-xs font-mono text-slate-400")

                    def contributor_role(role_id: int, *, clearance: bool = False) -> None:
                        role = roles.get(role_id, {})
                        with ui.row().classes("w-full items-center gap-2 pl-8"):
                            ui.icon("badge", color="blue-grey-5", size="16px")
                            ui.label(
                                render_message("webui.contributor_role.label.get_get_2_303a1c41", get=role.get('role_code', 'Role'), get_2=role.get('role_name', role_id))
                            ).classes("text-sm text-slate-700")
                            if clearance:
                                ui.label(
                                    render_message("webui.contributor_role.label.get_level_get_2_fa6ba9ac", get=role.get('security_level_code', '—'), get_2=role.get('clearance', '—'))
                                ).classes("text-xs text-slate-400")

                    privilege_role_ids = contributors.get("privilege_role_ids", [])
                    if privilege_role_ids:
                        with ui.column().classes("w-full gap-1 rounded-lg border border-slate-200 p-3"):
                            required_privilege = result["required_privilege"]
                            contributor_heading(
                                render_message('authorization.explanation.privilege', name=localized_privilege_name({"code": required_privilege})),
                                required_privilege, "key",
                            )
                            for role_id in privilege_role_ids:
                                contributor_role(role_id)

                    clearance_role_ids = contributors.get("clearance_role_ids", [])
                    if clearance_role_ids:
                        with ui.column().classes("w-full gap-1 rounded-lg border border-slate-200 p-3"):
                            contributor_heading(
                                render_message('authorization.explanation.clearance', level=result.get('required_clearance', '—')),
                                render_message('authorization.explanation.maximum_clearance'), "verified_user",
                            )
                            for role_id in clearance_role_ids:
                                contributor_role(role_id, clearance=True)

                    everyone_permissions = contributors.get("everyone_permissions", [])
                    org_unit_member_permissions = contributors.get(
                        "org_unit_member_permissions", []
                    )
                    org_unit_member_roles = contributors.get(
                        "org_unit_member_role_ids_by_permission", {}
                    )
                    acl_roles = contributors.get("acl_role_ids_by_permission", {})
                    for permission in dict.fromkeys([
                        *everyone_permissions,
                        *org_unit_member_permissions,
                        *acl_roles.keys(),
                    ]):
                        role_ids = acl_roles.get(permission, [])
                        if (
                            permission not in everyone_permissions
                            and permission not in org_unit_member_permissions
                            and not role_ids
                        ):
                            continue
                        with ui.column().classes("w-full gap-1 rounded-lg border border-slate-200 p-3"):
                            contributor_heading(
                                render_message('authorization.explanation.permission', name=operation_label(permission)),
                                permission, "policy",
                            )
                            if permission in everyone_permissions:
                                with ui.row().classes("w-full items-center gap-2 pl-8"):
                                    ui.icon("groups", color="blue-grey-5", size="16px")
                                    ui.label(render_message("webui.load_explanation.label.everyone_all_authenticated_users_f5ef1381")).classes("text-sm text-slate-700")
                            if permission in org_unit_member_permissions:
                                with ui.column().classes("w-full gap-1 pl-8"):
                                    with ui.row().classes("w-full items-center gap-2"):
                                        ui.icon("corporate_fare", color="blue-grey-5", size="16px")
                                        ui.label(
                                            render_message("webui.load_explanation.label.all_org_unit_members_matched_through_the_r_485b0ebf")
                                        ).classes("text-sm text-slate-700")
                                    for role_id in org_unit_member_roles.get(permission, []):
                                        contributor_role(role_id)
                            for role_id in role_ids:
                                for match in result.get("acl", {}).get("contextual_matches", []):
                                    if match["role_id"] == role_id and match["permission_code"] == permission:
                                        ui.label(
                                            render_message("authorization.oversight.managers")
                                            if match["principal_type"] == "owning_and_higher_level_unit_managers"
                                            else render_message("authorization.oversight.file_administrator")
                                        ).classes("text-sm font-medium")
                                        ui.label(render_message("authorization.oversight.match_unit", unit_id=match["org_unit_id"])).classes("text-xs text-slate-500")
                                contributor_role(role_id)

                    bypass_role_ids = contributors.get("governance_bypass_role_ids", [])
                    if bypass_role_ids:
                        with ui.column().classes("w-full gap-1 rounded-lg border border-amber-200 bg-amber-50 p-3"):
                            contributor_heading(
                                render_message('authorization.explanation.bypass'),
                                render_message('authorization.explanation.bypass_detail'),
                                "admin_panel_settings",
                            )
                            for role_id in bypass_role_ids:
                                contributor_role(role_id)
                    if result["acl"].get("dormant_override_grants"):
                        ui.label(render_message("webui.load_explanation.label.a_dormant_local_acl_override_is_retained_b_4df0897f")).classes("text-xs text-amber-800 bg-amber-50 rounded p-2 mt-2")
            run.on("click", load_explanation)
            operation.on_value_change(lambda _: load_explanation())
            if user is not None:
                user.on_value_change(lambda _: load_explanation())
        dialog.open()
        await load_explanation()


    return show_access_explanation
