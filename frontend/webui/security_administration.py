"""Security profile presentation, editing rules and privilege editor; no application-global state."""
from __future__ import annotations

from typing import Any, Callable
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message, render_message_plain
import asyncio
from .profile_privileges import closure as privilege_closure, dependents as privilege_dependents
from .authorization_ui import privilege_matches_search


def localized_privilege_name(privilege: dict[str, Any]) -> str:
    translation_code = {
        "search.saved_search.administer": "search.saved_search.administrator",
    }.get(privilege["code"], privilege["code"])
    message_key = f"privilege.{translation_code}.name"
    return render_message(message_key)


def localized_privilege_description(privilege: dict[str, Any]) -> str:
    translation_code = {
        "search.saved_search.administer": "search.saved_search.administrator",
    }.get(privilege["code"], privilege["code"])
    message_key = f"privilege.{translation_code}.description"
    return render_message(message_key)


def localized_privilege_category(category: str) -> str:
    message_key = f"privilege.category.{category}"
    return render_message(message_key)


def localized_privilege_matches_search(privilege: dict[str, Any], query: str) -> bool:
    localized = {
        **privilege,
        "name": localized_privilege_name(privilege),
        "description": localized_privilege_description(privilege),
    }
    return privilege_matches_search(localized, query)


def localized_profile_value(row: dict[str, Any], field: str) -> Any:
    localized = row.get("localized") or {}
    if localized.get(field):
        return localized[field]
    code = str(row.get("code") or "")
    if field == "name":
        values = {
            "ALL_PRIVS": render_message("profile.built_in.all_privileges.name"),
            "END_USER": render_message("profile.built_in.end_user.name"),
            "INFO_GOV_MGR": render_message("profile.built_in.information_governance_manager.name"),
            "INFO_GOV_OFFICER": render_message("profile.built_in.information_governance_officer.name"),
            "SYS_ADMIN": render_message("profile.built_in.system_administrator.name"),
            "TEXT_INDEXER_SERVICE": render_message("profile.built_in.text_indexer_service.name"),
            "UNIT_MGR": render_message("profile.built_in.unit_manager.name"),
            "VIEW_ONLY": render_message("profile.built_in.view_only.name"),
        }
        if code in values:
            return values[code]
    elif field == "description":
        values = {
            "ALL_PRIVS": render_message("profile.built_in.all_privileges.description"),
            "INFO_GOV_MGR": render_message("profile.built_in.information_governance.description"),
            "INFO_GOV_OFFICER": render_message("profile.built_in.information_governance.description"),
            "SYS_ADMIN": render_message("profile.built_in.system_administrator.description"),
            "TEXT_INDEXER_SERVICE": render_message("profile.built_in.text_indexer_service.description"),
        }
        if code in values:
            return values[code]
    return row.get(field)


def build_profile_privilege_editor(
    api, *, select_entity: Callable, error_message: Callable, show_api_error: Callable,
):
    async def show_profile_privilege_editor(profile: dict[str, Any]) -> None:
        try:
            all_privileges, selected, impact = await asyncio.gather(
                api.list("privileges"), api.profile_privileges(profile["id"]),
                api.profile_impact(profile["id"]),
            )
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return
        selected_ids = {item["id"] for item in selected}
        dialog = ui.dialog()
        controls: dict[int, Any] = {}
        privilege_entries: list[tuple[dict[str, Any], Any]] = []
        category_sections: dict[str, tuple[Any, list[tuple[dict[str, Any], Any]]]] = {}
        with dialog, ui.card().classes("w-[760px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-32px)]"):
            ui.label(render_message("webui.show_profile_privilege_editor.label.privileges_name_26affeed", name=profile['name'])).classes("text-xl font-semibold")
            ui.label(
                render_message("webui.show_profile_privilege_editor.label.changes_affect_role_count_role_s_and_user_61490a28", role_count=impact['role_count'], user_count=impact['user_count'])
            ).classes("text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2")
            privilege_search = ui.input(
                render_message("webui.show_profile_privilege_editor.input.find_privileges_1fa8656a"),
                placeholder=render_message("webui.show_profile_privilege_editor.input.search_by_code_name_or_description_a4008a4a"),
            ).props("outlined dense clearable debounce=200").classes("w-full")
            with ui.column().classes("w-full gap-2 overflow-y-auto max-h-[55vh]"):
                current_category = None
                for privilege in all_privileges:
                    if privilege["category"] != current_category:
                        current_category = privilege["category"]
                        category_label = ui.label(
                            localized_privilege_category(current_category)
                        ).classes(
                            "text-xs tracking-wider text-slate-500 font-semibold mt-2"
                        )
                        category_sections[current_category] = (category_label, [])
                    with ui.row().classes("w-full items-start") as privilege_entry:
                        with ui.column().classes("w-full gap-0"):
                            controls[privilege["id"]] = ui.checkbox(
                                render_message("webui.show_profile_privilege_editor.checkbox.name_code_988b7e60", name=localized_privilege_name(privilege), code=privilege['code']),
                                value=privilege["id"] in selected_ids,
                            )
                            ui.label(
                                localized_privilege_description(privilege)
                            ).classes(
                                "text-xs leading-5 text-slate-500 pl-10 -mt-1 pr-2"
                            )
                    entry = (privilege, privilege_entry)
                    privilege_entries.append(entry)
                    category_sections[current_category][1].append(entry)

            def filter_privileges() -> None:
                query = privilege_search.value or ""
                for privilege, entry_element in privilege_entries:
                    entry_element.set_visibility(localized_privilege_matches_search(privilege, query))
                for _, (category_label, entries) in category_sections.items():
                    category_label.set_visibility(
                        any(localized_privilege_matches_search(privilege, query) for privilege, _ in entries)
                    )

            privilege_search.on_value_change(lambda _: filter_privileges())
            with ui.row().classes(
                "w-full items-start gap-2 rounded-lg border border-amber-200 "
                "bg-amber-50 px-3 py-2"
            ) as unrestricted_profile_warning:
                ui.icon("warning_amber", color="amber-9", size="20px").classes(
                    "mt-0.5 shrink-0"
                )
                ui.label(
                    render_message("webui.show_profile_privilege_editor.label.this_profile_contains_every_defined_privil_2f49509c")
                ).classes("text-xs leading-5 text-amber-10")

            def update_unrestricted_profile_warning() -> None:
                unrestricted_profile_warning.set_visibility(
                    bool(controls) and all(control.value for control in controls.values())
                )

            dependencies = {item["id"]: set(item["required_privilege_ids"]) for item in all_privileges}
            selection = set(selected_ids)
            applying_selection = False

            def apply_selection(updated):
                nonlocal applying_selection
                applying_selection = True
                try:
                    selection.clear()
                    selection.update(updated)
                    for identifier, control in controls.items():
                        control.set_value(identifier in selection)
                finally:
                    applying_selection = False
                update_unrestricted_profile_warning()

            def selection_changed(identifier, checked):
                if applying_selection:
                    return
                if checked:
                    updated = privilege_closure(selection | {identifier}, dependencies)
                    added = updated - selection - {identifier}
                    apply_selection(updated)
                    if added:
                        names = ", ".join(item["code"] for item in all_privileges if item["id"] in added)
                        ui.notify(render_message("authorization.profile.prerequisites_added", privileges=names), color="info")
                    return
                affected = privilege_dependents(identifier, selection, dependencies)
                if not affected:
                    apply_selection(selection - {identifier})
                    return
                # Keep the valid selection until the user confirms removal.
                apply_selection(set(selection))
                with ui.dialog().props("persistent") as confirm, ui.card():
                    names = ", ".join(item["code"] for item in all_privileges if item["id"] in affected)
                    ui.label(render_message("authorization.profile.remove_dependents", privileges=names))
                    with ui.row():
                        ui.button(render_message("webui.show_profile_privilege_editor.button.cancel_d03380ff"), on_click=confirm.close).props("flat")
                        def remove_together():
                            apply_selection(selection - affected - {identifier})
                            confirm.close()
                        ui.button(render_message("authorization.profile.remove_together"), on_click=remove_together)
                confirm.open()

            for identifier, privilege_control in controls.items():
                privilege_control.on_value_change(
                    lambda event, identifier=identifier: selection_changed(identifier, event.value)
                )
            update_unrestricted_profile_warning()
            reason = ui.textarea(render_message("webui.show_profile_privilege_editor.textarea.reason_for_changing_this_profile_6813db02"), placeholder=render_message("webui.show_profile_privilege_editor.textarea.required_e75da8d4")).props(
                "outlined autogrow"
            ).classes("w-full")

            dependency_feedback = ui.column().classes("w-full gap-1")

            async def save_privileges() -> None:
                dependency_feedback.clear()
                for control in controls.values():
                    control.props(remove="error error-message")
                change_reason = (reason.value or "").strip()
                if not change_reason:
                    ui.notify(render_message("webui.save_privileges.notify.a_reason_is_required_ae7186e1"), color="warning")
                    return
                try:
                    await api.replace_profile_privileges(
                        profile["id"], profile["version"],
                        [identifier for identifier, control in controls.items() if control.value],
                        reason=change_reason,
                    )
                    dialog.close()
                    ui.notify(render_message("webui.save_privileges.notify.profile_privileges_saved_3a8e587a"), color="positive")
                    await select_entity("profiles")
                except ApiError as error:
                    if isinstance(error.detail, dict) and error.detail.get("code") == "privilege_dependency_violation":
                        missing = error.detail.get("missing", [])
                        required_codes = {item["required_code"] for item in missing}
                        privilege_search.set_value("")
                        filter_privileges()
                        for privilege, _ in privilege_entries:
                            if privilege["code"] in required_codes:
                                controls[privilege["id"]].props("error")
                        with dependency_feedback:
                            for item in missing:
                                ui.label(render_message(
                                    "authorization.profile.error.missing_prerequisite",
                                    privilege=item["privilege_code"], required=item["required_code"],
                                )).classes("text-negative").props('role="alert"')
                    show_api_error(error)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.show_profile_privilege_editor.button.cancel_d03380ff"), on_click=dialog.close).props("flat no-caps")
                ui.button(render_message("webui.show_profile_privilege_editor.button.save_privileges_9223c6cc"), icon="save", on_click=save_privileges).props("unelevated no-caps")
        dialog.open()


    return show_profile_privilege_editor


def profile_translation_only(resource: str, row: dict[str, Any] | None) -> bool:
    return bool(row and resource == "profiles" and row.get("code") == "TEXT_INDEXER_SERVICE")


def configure_profile_field(field, control, *, creating: bool) -> None:
    if field.name == "code" and not creating:
        control.disable()


def profile_reason_input():
    return ui.textarea(
        render_message("webui.open_editor.textarea.reason_for_changing_this_profile_5882ddfb"), placeholder=render_message("webui.open_editor.textarea.required_b956865c"),
    ).props("outlined autogrow").classes("w-full")


def prepare_profile_update(payload: dict[str, Any]) -> None:
    payload.pop("code", None)


def profile_change_reason(control) -> str:
    reason = (control.value or "").strip()
    if not reason:
        raise ValueError("A reason is required when changing a profile")
    return reason
