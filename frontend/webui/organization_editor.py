"""Existing organization rules and presentation, shared with connected features."""
from __future__ import annotations
from typing import Any
from nicegui import ui
from .i18n_catalogue import render_message


def inactive_org_unit_source(
    org_unit: dict[str, Any] | None,
    org_units_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    current = org_unit
    seen: set[int] = set()
    while current and current.get("id") not in seen:
        seen.add(current["id"])
        if current.get("status") == "inactive":
            return current
        current = org_units_by_id.get(current.get("parent_org_unit_id"))
    return None


def role_change_requires_reason(
    current: dict[str, Any], proposed: dict[str, Any],
    security_levels: list[dict[str, Any]],
) -> bool:
    """Return whether a role edit is sensitive enough to require an audit reason."""
    if any(
        proposed.get(name) != current.get(name)
        for name in ("profile_id", "is_information_governance")
        if name in proposed
    ):
        return True
    if "security_level_id" not in proposed:
        return False
    level_numbers = {item["id"]: item["level_number"] for item in security_levels}
    old_number = level_numbers.get(current.get("security_level_id"))
    new_number = level_numbers.get(proposed.get("security_level_id"))
    return (
        old_number is not None
        and new_number is not None
        and new_number < old_number
    )



def configure_designation_field(spec, field, row, controls, dialog, api, bind_remote_relationship_select):
    if spec.key == "org-units" and field.name in {"managing_role_id", "file_administrator_role_id"}:
        async def designated_roles(query, unit_id=row["id"]):
            if len(query.strip()) < 2:
                return {"items": []}
            return await api.search_request("roles", {
                "where": {"and": [
                    {"field": "org_unit_id", "operator": "eq", "value": unit_id},
                    {"or": [{"field": name, "operator": "contains_ci", "value": query.strip()} for name in ("code", "name")]},
                ]},
                "sort": [{"field": "code", "direction": "asc"}], "limit": 25,
            })
        bind_remote_relationship_select(
            controls[field.name], "roles", ("code", "name"), ("code", "name"),
            page_loader=designated_roles, active=lambda: dialog.value,
        )


def configure_role_profile_field(spec, field, controls, lookup_rows_by_field):
    if spec.key == "roles" and field.name == "profile_id":
        profiles_by_id = {
            item["id"]: item
            for item in lookup_rows_by_field.get(field.name, [])
        }
        with ui.row().classes(
            "w-full items-start gap-2 rounded-lg border border-amber-200 "
            "bg-amber-50 px-3 py-2 -mt-2"
        ) as all_privileges_warning:
            ui.icon("warning_amber", color="amber-9", size="20px").classes(
                "mt-0.5 shrink-0"
            )
            ui.label(
                render_message("webui.open_editor.label.this_profile_grants_every_currently_define_e746104e")
            ).classes("text-xs leading-5 text-amber-10")

        def update_all_privileges_warning() -> None:
            all_privileges_warning.set_visibility(
                bool(profiles_by_id.get(
                    controls["profile_id"].value, {}
                ).get("grants_all_privileges"))
                or str(controls["profile_id"].options.get(
                    controls["profile_id"].value, "",
                )).startswith("ALL_PRIVS")
            )

        controls["profile_id"].on_value_change(
            lambda _: update_all_privileges_warning()
        )
        update_all_privileges_warning()


def configure_organization_browser_field(translation_only, field, controls, show_organization_structure):
    if (
        not translation_only
        and field.lookup_resource in {"org-units", "roles", "users"}
    ):
        selector_mode = {
            "org-units": "org_unit", "roles": "role", "users": "user",
        }[field.lookup_resource]
        ui.button(
            render_message("webui.open_editor.button.browse_organization_structure_8fdef32d"), icon="account_tree",
            on_click=lambda _, control=controls[field.name], mode=selector_mode: show_organization_structure(
                selection_mode=mode, target_control=control,
            ),
        ).props("flat dense no-caps color=primary").classes("self-start -mt-2")


def configure_role_governance_field(spec, field):
    if spec.key == "roles" and field.name == "is_information_governance":
        ui.label(
            render_message("webui.open_editor.label.information_governance_roles_may_bypass_re_697d91ef")
        ).classes("text-xs leading-5 text-slate-500 -mt-2")


def organization_reason_input(spec, *, creating, translation_only):
    security_change_reason = None
    if not creating and spec.key == "roles" and not translation_only:
        security_change_reason = ui.textarea(
            render_message("webui.open_editor.textarea.reason_for_sensitive_authorization_changes_1726b6f0"),
            placeholder=render_message("webui.open_editor.textarea.required_for_profile_governance_status_or_ee1c9562"),
        ).props("outlined autogrow").classes("w-full")
    return security_change_reason


def organization_change_reason(spec, row, payload, lookup_rows_by_field, security_change_reason, change_reason):
    if spec.key == "roles" and role_change_requires_reason(
        row, payload,
        lookup_rows_by_field.get("security_level_id", []),
    ):
        change_reason = (security_change_reason.value or "").strip()
        if not change_reason:
            raise ValueError(
                "A reason is required when changing a role's profile, "
                "governance status, or lowering its security clearance"
            )
    return change_reason


def protected_organization_role(resource, row):
    return resource == "roles" and row.get("is_system")


async def read_organization_editor_row(api, row):
    # Tree and summary projections can omit existing designations.
    return await api.get("org-units", row["id"])
