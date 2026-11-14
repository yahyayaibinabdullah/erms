"""Aggregation-specific controls and validation used by the shared entity editor."""
from __future__ import annotations
import asyncio
from typing import Any
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message
from .aggregation_presentation import CHILD_AGGREGATION_CLASSIFICATION_HELP
from .entity_editor_controls import field_input
from .config import default_root_aggregation_medium
from .entity_editor_controls import medium_options


def lock_aggregation_close_field(editor_capabilities, effective_locked_fields):
    if not editor_capabilities.get("close"):
        effective_locked_fields.add("date_closed")


async def load_aggregation_creation_context(api, initial_values, accept_application_configuration):
    creation_roles, creation_configuration = await asyncio.gather(
        api.creation_role_options((initial_values or {}).get("parent_aggregation_id")),
        api.application_configuration(),
    )
    accept_application_configuration(creation_configuration)
    return creation_roles, creation_configuration


def render_aggregation_creation_controls(spec, initial_values, lookup_options, controls, effective_locked_fields, creation_roles, bind_remote_relationship_select):
    parent_field = next(
        field for field in spec.fields if field.name == "parent_aggregation_id"
    )
    initial_parent_id = (initial_values or {}).get("parent_aggregation_id")
    controls["parent_aggregation_id"] = field_input(
        parent_field,
        initial_parent_id,
        lookup_options.get("parent_aggregation_id"),
    )
    bind_remote_relationship_select(
        controls["parent_aggregation_id"], "aggregations",
        ("aggregation_number", "title"),
        parent_field.lookup_label_fields,
    )
    ui.label(
        render_message("webui.open_editor.label.optional_leave_this_blank_to_create_a_root_62bd543d")
    ).classes("text-xs leading-5 text-slate-500 -mt-2")
    if "parent_aggregation_id" in effective_locked_fields:
        controls["parent_aggregation_id"].disable()
    role_options = {
        item["role_id"]: item["label"] for item in creation_roles
    }
    initial_role_id = (
        creation_roles[0]["role_id"] if len(creation_roles) == 1 else None
    )
    controls["creator_acl_role_id"] = ui.select(
        role_options, value=initial_role_id, label=render_message("webui.open_editor.select.create_for_ab95b7b7"),
    ).props("outlined options-dense").classes("w-full")
    if len(creation_roles) == 1:
        controls["creator_acl_role_id"].disable()
    ui.label(
        render_message("webui.open_editor.label.for_a_child_aggregation_the_parent_determi_cd47a50d")
    ).classes("text-xs leading-5 text-slate-500 -mt-2")
    aggregation_creation_role_status = ui.label(
        (
            (
                render_message("webui.open_editor.label.you_do_not_have_an_eligible_role_in_the_pa_4862616a")
                if initial_parent_id is not None
                else render_message("webui.open_editor.label.you_do_not_have_an_eligible_role_so_you_ca_7fcb954d")
            )
            if not creation_roles
            else render_message("webui.open_editor.label.choose_one_of_your_roles_in_the_parent_agg_3f0d544f")
            if initial_parent_id is not None and len(creation_roles) > 1
            else render_message("webui.open_editor.label.create_for_was_set_automatically_because_y_cf4e8502")
            if initial_parent_id is not None
            else render_message("webui.open_editor.label.no_parent_is_selected_so_this_will_be_a_ro_36c62919")
        )
    ).props('role="status" aria-live="polite"').classes(
        "text-xs leading-5 text-amber-800 -mt-2"
    )
    return aggregation_creation_role_status


def aggregation_initial_security_level(initial_values, lookup_rows_by_field):
    parent = next(
        (item for item in lookup_rows_by_field.get("parent_aggregation_id", [])
         if item["id"] == (initial_values or {}).get("parent_aggregation_id")),
        None,
    )
    initial_value = parent.get("security_level_id") if parent else None
    return initial_value


def aggregation_initial_medium(controls, lookup_rows_by_field, creation_configuration):
    parent_id = controls["parent_aggregation_id"].value
    parent = next((item for item in lookup_rows_by_field.get("parent_aggregation_id", []) if item["id"] == parent_id), None)
    initial_value = parent.get("medium", "mixed") if parent else default_root_aggregation_medium(creation_configuration)
    return initial_value


def render_aggregation_close_help():
    ui.label(
        render_message("webui.open_editor.label.closing_an_aggregation_requires_the_aggreg_3d670823")
    ).classes("text-xs leading-5 text-slate-500 -mt-2")


def configure_aggregation_classification(field, controls, creating, initial_values, row, browse_classification_tree):
    parent_id = (initial_values or {}).get("parent_aggregation_id") if creating else row.get("parent_aggregation_id")
    if parent_id is not None:
        controls[field.name].value = None
        controls[field.name].disable()
        with ui.row().classes(
            "w-full items-start gap-1 text-xs text-slate-500 -mt-2"
        ):
            ui.icon("info", size="16px").classes("mt-px shrink-0")
            ui.label(CHILD_AGGREGATION_CLASSIFICATION_HELP).classes(
                "leading-5"
            )
    else:
        ui.button(
            render_message("webui.open_editor.button.browse_classification_tree_19ef047a"), icon="account_tree",
            on_click=lambda control=controls[field.name]: browse_classification_tree(control),
        ).props("outline dense no-caps color=primary").classes("self-start")


def configure_aggregation_parent_rules(controls, lookup_rows_by_field, creating, row, creation_configuration, aggregation_creation_role_status, api, error_message):
    parents = lookup_rows_by_field.get("parent_aggregation_id", [])
    def constrain_aggregation_medium() -> None:
        parent_id = controls["parent_aggregation_id"].value
        parent = next((item for item in parents if item["id"] == parent_id), None)
        medium_control = controls["medium"]
        if parent:
            medium = parent.get("medium", "mixed")
            medium_control.set_options({medium: medium_options()[medium]}, value=medium)
            medium_control.disable()
        else:
            medium_control.set_options(
                medium_options(),
                value=medium_control.value or (row["medium"] if row else default_root_aggregation_medium(creation_configuration)),
            )
            medium_control.enable()
        medium_control.update()
    if controls.get("parent_aggregation_id"):
        controls["parent_aggregation_id"].on_value_change(
            lambda _: constrain_aggregation_medium()
        )
        if creating:
            async def refresh_aggregation_creation_roles() -> None:
                control = controls["creator_acl_role_id"]
                previous_role_id = control.value
                parent_id = controls["parent_aggregation_id"].value
                try:
                    rows = await api.creation_role_options(
                        parent_id
                    )
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)
                    return
                options = {item["role_id"]: item["label"] for item in rows}
                eligible_role_ids = set(options)
                previous_role_was_cleared = (
                    previous_role_id is not None
                    and previous_role_id not in eligible_role_ids
                )
                selected_role_id = (
                    previous_role_id if previous_role_id in eligible_role_ids
                    else rows[0]["role_id"] if len(rows) == 1
                    else None
                )
                control.set_options(
                    options,
                    value=selected_role_id,
                )
                if len(rows) <= 1:
                    control.disable()
                else:
                    control.enable()
                if not rows:
                    aggregation_creation_role_status.set_text(
                        "You do not have an eligible role"
                        + (
                            " in the parent aggregation's organizational unit, so you "
                            "cannot add a child aggregation there."
                            if parent_id is not None
                            else ", so you cannot create a root aggregation."
                        )
                    )
                elif previous_role_was_cleared:
                    aggregation_creation_role_status.set_text(
                        "Your previous Create for selection was cleared because it does not "
                        "belong to the parent aggregation's organizational unit."
                    )
                elif parent_id is None:
                    aggregation_creation_role_status.set_text(
                        "No parent is selected, so this will be a root aggregation and the "
                        "selected role's organizational unit will become its owner."
                    )
                elif len(rows) == 1:
                    aggregation_creation_role_status.set_text(
                        "Create for was set automatically because you have one eligible role."
                    )
                else:
                    aggregation_creation_role_status.set_text(
                        "Choose one of your roles in the parent aggregation's organizational unit."
                    )

            controls["parent_aggregation_id"].on_value_change(
                lambda _: refresh_aggregation_creation_roles()
            )
    constrain_aggregation_medium()


def prepare_aggregation_payload(creating, controls, payload):
    if creating:
        creator_role_id = controls["creator_acl_role_id"].value
        if creator_role_id is None:
            raise ValueError("Select who this aggregation is being created for")
        payload["creator_acl_role_id"] = int(creator_role_id)
    if payload.get("parent_aggregation_id") is None and payload.get("classification_id") is None:
        raise ValueError("A root aggregation must have a terminal classification")
