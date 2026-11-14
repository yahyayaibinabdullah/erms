"""Shared entity form orchestration delegating feature rules to their owners."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from typing import Callable
from .entities import ENTITIES
from .aggregation_editor import aggregation_initial_medium
from .aggregation_editor import aggregation_initial_security_level
from .capabilities import can_edit_entity_translation
from .aggregation_editor import configure_aggregation_classification
from .aggregation_editor import configure_aggregation_parent_rules
from .organization_editor import configure_designation_field
from .organization_editor import configure_organization_browser_field
from .security_administration import configure_profile_field
from .record_editor import configure_record_medium
from .organization_editor import configure_role_governance_field
from .organization_editor import configure_role_profile_field
from .classification_editor import configure_scheme_field
from .entity_translation_editor import entity_translation_editor
from .entity_editor_controls import field_input
from .entity_editor_controls import form_payload
from .aggregation_editor import load_aggregation_creation_context
from .classification_editor import load_direct_retention
from .aggregation_editor import lock_aggregation_close_field
from .organization_editor import organization_change_reason
from .organization_editor import organization_reason_input
from .aggregation_editor import prepare_aggregation_payload
from .security_administration import prepare_profile_update
from .classification_editor import prepare_retention_payload
from .security_administration import profile_reason_input
from .security_administration import profile_translation_only
from .organization_editor import protected_organization_role
from .organization_editor import read_organization_editor_row
from .entity_selectors import relationship_options
from .aggregation_editor import render_aggregation_close_help
from .aggregation_editor import render_aggregation_creation_controls
from .i18n_catalogue import render_message
from .classification_editor import retention_editor_source
from .i18n_catalogue import strip_diagnostic_metadata
from nicegui import ui
from .security_administration import profile_change_reason as validated_profile_change_reason

def build_entity_editor(
    *, CLASSIFICATION_SELECTOR_SEARCH_FIELDS, accept_application_configuration, add_number_suggestion, api, bind_remote_relationship_select, bind_resource_security_select, browse_classification_tree, clear_medium_error, current_resource, error_message, highlight_medium_error, load_recent, load_rows, localization, localized_editor_entity, open_record_draft_editor, principal, render_table, search_input, set_searched, show_api_error, show_number_conflict, show_organization_structure, validation_error_message,
):
    async def open_editor(
        row: dict[str, Any] | None = None, on_saved=None,
        initial_values: dict[str, Any] | None = None,
        locked_fields: set[str] | None = None,
        resource_key: str | None = None,
    ) -> None:
        resolved_resource = resource_key or {
            "aggregation-details": "aggregations",
            "record-details": "records",
            "org-unit-details": "org-units",
            "role-details": "roles",
            "user-details": "users",
            "text-indexer-details": "text-indexers",
        }.get(current_resource(), current_resource())
        spec = ENTITIES[resolved_resource]
        creating = row is None
        if row is not None and spec.key == "org-units":
            # Tree nodes and summary cards are display projections, not edit
            # records. Read all persisted fields before initializing controls;
            # an omitted designation must never turn into an implicit clear.
            try:
                row = await read_organization_editor_row(api, row)
            except ApiError as error:
                show_api_error(error)
                return
        translation_only = bool(
            row and (
                protected_organization_role(spec.key, row)
                or profile_translation_only(spec.key, row)
            )
        )
        translation_edit_allowed = can_edit_entity_translation(
            spec.key, (principal() or {}).get("global_privileges", [])
        )
        if translation_only and not translation_edit_allowed:
            ui.notify(
                render_message("webui.open_editor.notify.your_effective_roles_do_not_allow_editing_ae0f56e0", singular=spec.singular),
                color="warning", close_button=True,
            )
            return
        effective_locked_fields = set(locked_fields or set())
        if row and spec.key in {"aggregations", "records"}:
            try:
                editor_capabilities = await api.resource_capabilities(
                    spec.key, row["id"]
                )
            except ApiError as error:
                show_api_error(error)
                return
            if not editor_capabilities.get("modify_metadata"):
                ui.notify(
                    render_message("webui.open_editor.notify.your_effective_roles_do_not_allow_editing_ae0f56e0", singular=spec.singular),
                    color="warning", close_button=True,
                )
                return
            if not editor_capabilities.get("change_security_level"):
                effective_locked_fields.add("security_level_id")
        if row and spec.key in {"aggregations", "records"} and row.get("_effectively_closed"):
            ui.notify(
                render_message("webui.open_editor.notify.closed_singular_metadata_cannot_be_changed_9b448126", singular=spec.singular),
                color="warning",
            )
            return
        if row and spec.key == "aggregations" and row.get("date_closed") is None:
            lock_aggregation_close_field(editor_capabilities, effective_locked_fields)
        if creating and spec.key == "records":
            await open_record_draft_editor()
            return
        lookup_options: dict[str, dict[int, str]] = {}
        lookup_rows_by_field: dict[str, list[dict[str, Any]]] = {}
        creation_roles: list[dict[str, Any]] = []
        retention_rule: dict[str, Any] | None = None
        try:
            if creating and spec.key == "aggregations":
                creation_roles, creation_configuration = await load_aggregation_creation_context(api, initial_values, accept_application_configuration)
            if row and spec.key == "classifications":
                retention_rule = await load_direct_retention(api, row)
            for field in spec.fields:
                if not field.lookup_resource:
                    continue
                selected_id = (
                    (initial_values or {}).get(field.name)
                    if creating else row.get(field.name) if row else None
                )
                lookup_rows: list[dict[str, Any]] = []
                if selected_id is not None:
                    lookup_rows.append(
                        await api.get(field.lookup_resource, int(selected_id))
                    )
                if field.lookup_resource == "security-levels":
                    first_levels = await api.list("security-levels", limit=25)
                    known_ids = {item["id"] for item in lookup_rows}
                    lookup_rows.extend(
                        item for item in first_levels if item["id"] not in known_ids
                    )
                elif field.lookup_resource == "profiles" and creating:
                    compatibility_page = await api.administration_reference_page(
                        "profiles", query="ALL_PRIVS", limit=25,
                    )
                    known_ids = {item["id"] for item in lookup_rows}
                    lookup_rows.extend(
                        item for item in compatibility_page.get("items", [])
                        if item.get("code") == "ALL_PRIVS"
                        if item["id"] not in known_ids
                    )
                lookup_rows_by_field[field.name] = lookup_rows
                if field.kind == "classification":
                    lookup_options[field.name] = {
                        item["id"]: " · ".join(filter(None, (
                            (item.get("localized") or {}).get(field_name) or item.get(field_name)
                            for field_name in CLASSIFICATION_SELECTOR_SEARCH_FIELDS
                        ))) for item in lookup_rows
                    }
                else:
                    lookup_options[field.name] = relationship_options(
                        lookup_rows, field.lookup_label_fields
                    )
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return


        dialog = ui.dialog()
        controls: dict[str, Any] = {}
        with dialog, ui.card().classes("w-[620px] max-w-full"):
            editor_action = render_message(
                "webui.open_editor.action.add" if creating else "webui.open_editor.action.edit"
            )
            editor_entity = localized_editor_entity(spec.key, spec.singular)
            ui.label(render_message(
                "webui.open_editor.label.value_singular_18d4bf4f",
                value=editor_action,
                singular=editor_entity,
            )).classes("text-xl font-semibold")
            ui.label(render_message("webui.open_editor.label.required_fields_73ed8b5b")).classes("text-xs text-slate-500 -mt-2")
            with ui.column().classes("w-full gap-3"):
                if translation_only:
                    ui.label(
                        render_message("webui.select_role_details.label.built_in_roles_are_provisioned_by_the_plat_fefe2800")
                    ).classes(
                        "w-full rounded-lg border border-blue-200 bg-blue-50 "
                        "px-3 py-2 text-xs leading-5 text-blue-900"
                    )
                if not creating and spec.key in {"aggregations", "records"}:
                    owner_label = " — ".join(filter(None, (
                        row.get("owning_org_unit_code"),
                        row.get("owning_org_unit_name"),
                    ))) or "Unavailable"
                    ui.input(
                        render_message("webui.open_editor.input.owning_organizational_unit_75aab41f"), value=owner_label,
                    ).props("outlined readonly").classes("w-full")
                    ui.label(
                        render_message("webui.open_editor.label.ownership_is_determined_by_placement_move_9bd5bbc5")
                    ).classes("text-xs leading-5 text-slate-500 -mt-2")
                if creating and spec.key == "aggregations":
                    aggregation_creation_role_status = render_aggregation_creation_controls(spec, initial_values, lookup_options, controls, effective_locked_fields, creation_roles, bind_remote_relationship_select)
                for field in spec.fields:
                    if creating and spec.key == "org-units" and field.name in {"managing_role_id", "file_administrator_role_id"}:
                        continue
                    if not creating and spec.key in {"aggregations", "records"} and field.name in {
                        "date_of_next_review", "is_vital", "assigned_location", "current_location",
                        "security_level_id",
                    }:
                        continue
                    if creating and spec.key == "aggregations" and field.name == "parent_aggregation_id":
                        continue
                    source = retention_editor_source(field, row, retention_rule)
                    initial_value = (
                        (initial_values or {}).get(field.name)
                        if creating else source.get(field.name) if source else None
                    )
                    if creating and field.name == "security_level_id" and initial_value is None:
                        available_levels = lookup_rows_by_field.get(field.name, [])
                        if spec.key == "aggregations" and (initial_values or {}).get("parent_aggregation_id"):
                            initial_value = aggregation_initial_security_level(initial_values, lookup_rows_by_field)
                        if initial_value is None and available_levels:
                            initial_value = min(
                                available_levels, key=lambda item: (item["level_number"], item["id"])
                            )["id"]
                    if creating and spec.key == "aggregations" and field.name == "medium":
                        initial_value = aggregation_initial_medium(controls, lookup_rows_by_field, creation_configuration)
                    if creating and field.name == "profile_id" and initial_value is None:
                        available_profiles = lookup_rows_by_field.get(field.name, [])
                        compatibility = next(
                            (item for item in available_profiles if item.get("code") == "ALL_PRIVS"),
                            None,
                        )
                        initial_value = compatibility["id"] if compatibility else None
                    controls[field.name] = field_input(
                        field,
                        initial_value,
                        lookup_options.get(field.name),
                    )
                    if field.name == "medium":
                        controls[field.name].on_value_change(
                            lambda _, control=controls[field.name]: clear_medium_error(control)
                        )
                    if creating and field.name in {"aggregation_number", "record_number"}:
                        add_number_suggestion(controls[field.name], spec.key, controls)
                    if field.name == "security_level_id" and spec.key in {"aggregations", "records"}:
                        if field.name not in effective_locked_fields:
                            bind_resource_security_select(
                                controls[field.name],
                                parent_control=controls.get("parent_aggregation_id" if spec.key == "aggregations" else "aggregation_id"),
                                aggregation_id=row["id"] if row and spec.key == "aggregations" else None,
                            )
                        else:
                            with ui.column().classes("w-full min-w-0 gap-1") as field_group:
                                controls[field.name].move(field_group)
                                ui.label(render_message("security_level.selection.constraints")).classes("w-full text-xs text-slate-500 leading-relaxed")
                    elif field.lookup_resource and not (spec.key == "org-units" and field.name in {"managing_role_id", "file_administrator_role_id"}):
                        bind_remote_relationship_select(
                            controls[field.name], field.lookup_resource,
                            CLASSIFICATION_SELECTOR_SEARCH_FIELDS
                            if field.kind == "classification"
                            else field.lookup_label_fields or ("name",),
                            field.lookup_label_fields or ("name",),
                            eligible_classifications=field.kind == "classification",
                            exclude_id=(
                                row["id"]
                                if row and field.lookup_resource == spec.key else None
                            ),
                        )
                    configure_designation_field(spec, field, row, controls, dialog, api, bind_remote_relationship_select)
                    configure_role_profile_field(spec, field, controls, lookup_rows_by_field)
                    configure_organization_browser_field(translation_only, field, controls, show_organization_structure)
                    if field.name in effective_locked_fields:
                        controls[field.name].disable()
                        if spec.key == "aggregations" and field.name == "date_closed":
                            render_aggregation_close_help()
                    if spec.key == "profiles":
                        configure_profile_field(field, controls[field.name], creating=creating)
                    if translation_only:
                        controls[field.name].disable()
                    configure_role_governance_field(spec, field)
                    if spec.key == "classification-schemes":
                        configure_scheme_field(field, controls[field.name], creating=creating)
                    if spec.key == "aggregations" and field.name == "classification_id":
                        configure_aggregation_classification(field, controls, creating, initial_values, row, browse_classification_tree)

                multilingual_fields = {
                    "classification-schemes": ("title", "description"),
                    "classifications": ("title", "description"),
                    "users": ("name", "description"),
                    "roles": ("name", "description"),
                    "org-units": ("name", "description"),
                    "security-levels": ("name", "description"),
                    "profiles": ("name", "description"),
                }
                prepare_entity_translation_update: Callable[
                    [], tuple[str, dict[str, str], str] | None
                ] | None = None
                profile_change_reason = None
                if not creating and spec.key in multilingual_fields and translation_edit_allowed:
                    prepare_entity_translation_update = await entity_translation_editor(
                        api, resource=spec.key, row=row, fields=multilingual_fields[spec.key],
                        languages=(localization() or {}).get("supported_languages", []),
                        dialog=dialog, uses_external_reason=spec.key == "profiles",
                        get_external_reason=lambda: profile_change_reason,
                        error_message=error_message, show_api_error=show_api_error,
                    )

            if spec.key == "aggregations" and "security_level_id" in controls:
                configure_aggregation_parent_rules(controls, lookup_rows_by_field, creating, row, creation_configuration, aggregation_creation_role_status, api, error_message)

            if spec.key == "records" and "medium" in controls:
                configure_record_medium(controls, lookup_rows_by_field)

            resource_change_reason = None
            if not creating and spec.key in {"aggregations", "records"}:
                resource_change_reason = ui.textarea(
                    render_message("webui.open_editor.textarea.reason_for_change_172dcfd9"),
                    placeholder=render_message("webui.open_editor.textarea.required_when_changing_the_medium_6aa98d2d"),
                ).props("outlined autogrow").classes("w-full")
                ui.label(
                    render_message("webui.open_editor.label.a_reason_is_required_when_changing_the_med_8019dd27")
                ).classes("text-xs text-slate-500 -mt-2")
            security_change_reason = None
            security_change_reason = organization_reason_input(spec, creating=creating, translation_only=translation_only)
            if not creating and spec.key == "profiles":
                profile_change_reason = profile_reason_input()

            async def save() -> None:
                try:
                    translation_update = (
                        prepare_entity_translation_update()
                        if prepare_entity_translation_update is not None
                        else None
                    )
                    if translation_only:
                        if translation_update is None:
                            raise ValueError(
                                render_message("entity_translation_editor.status.enter_one")
                            )
                        language, values, reason = translation_update
                        saved_translation = await api.update_entity_translation(
                            spec.key, row["id"], language, values,
                            row["version"], reason,
                        )
                        row["version"] = saved_translation["version"]
                        # Older rows and protected built-in entities can expose
                        # a JSON NULL here.  ``setdefault`` preserves an
                        # existing None value, so normalize the local cache
                        # before recording the successfully persisted change.
                        if not isinstance(row.get("translations"), dict):
                            row["translations"] = {}
                        row["translations"][language] = dict(values)
                        saved = dict(row)
                        dialog.close()
                        ui.notify(
                            render_message(
                                "webui.save.notify.capitalize_saved_c660b8b4",
                                capitalize=strip_diagnostic_metadata(editor_entity).capitalize(),
                            ),
                            color="positive",
                        )
                        if on_saved is not None:
                            await on_saved(saved)
                        elif not spec.search_first and current_resource() == spec.key:
                            await load_rows(repeat_search=True)
                        return
                    payload = form_payload(spec, controls, creating=creating)
                    if spec.key == 'aggregations':
                        prepare_aggregation_payload(creating, controls, payload)
                    rule_payload = None
                    if spec.key == "classifications":
                        rule_payload = prepare_retention_payload(payload, creating=creating)
                    if creating:
                        saved = await api.create(spec.key, payload)
                    else:
                        if spec.key == "profiles":
                            prepare_profile_update(payload)
                        change_reason = None
                        if (
                            resource_change_reason is not None
                            and spec.key in {"aggregations", "records"}
                            and payload.get("medium") != row.get("medium")
                        ):
                            change_reason = (resource_change_reason.value or "").strip()
                            if not change_reason:
                                raise ValueError("A reason is required when changing the record medium")
                        change_reason = organization_change_reason(spec, row, payload, lookup_rows_by_field, security_change_reason, change_reason)
                        if profile_change_reason is not None:
                            change_reason = validated_profile_change_reason(profile_change_reason)
                        saved = await api.update(
                            spec.key, row["id"], row["version"], payload,
                            change_reason=change_reason,
                        )
                        row.update(saved)
                        if spec.key == "classifications" and rule_payload is not None:
                            await api.put_classification_retention_rule(
                                row["id"], rule_payload,
                                retention_rule.get("version") if retention_rule else None,
                            )
                        if translation_update is not None:
                            language, values, reason = translation_update
                            saved_translation = await api.update_entity_translation(
                                spec.key, row["id"], language, values,
                                saved["version"], reason,
                            )
                            saved["version"] = saved_translation["version"]
                            row["version"] = saved_translation["version"]
                    dialog.close()
                    ui.notify(render_message("webui.save.notify.capitalize_saved_c660b8b4", capitalize=strip_diagnostic_metadata(editor_entity).capitalize()), color="positive")
                    if on_saved is not None:
                        if spec.search_first:
                            await load_recent(spec)
                        await on_saved(saved)
                        return
                    if spec.search_first:
                        await load_recent(spec)
                        query = (search_input.value or "").strip()
                        if query:
                            await load_rows(repeat_search=True)
                        else:
                            set_searched(False)
                            render_table(spec)
                    elif current_resource() == spec.key:
                        # Reload the bounded page using its localized sort and
                        # filters, rather than appending and reordering by ID.
                        await load_rows(repeat_search=True)
                except ValueError as error:
                    ui.notify(validation_error_message(error), color="warning")
                except ApiError as error:
                    if creating and spec.key in {"aggregations", "records"}:
                        number_field = "aggregation_number" if spec.key == "aggregations" else "record_number"
                        if await show_number_conflict(error, spec.key, controls[number_field], root=spec.key == "aggregations" and controls["parent_aggregation_id"].value is None):
                            return
                    highlight_medium_error(error, controls.get("medium"))
                    show_api_error(error)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.open_editor.button.cancel_c07bff03"), on_click=dialog.close).props("flat")
                ui.button(render_message("webui.open_editor.button.save_46081ed6"), on_click=save, icon="save").props("unelevated")
        dialog.open()


    return open_editor
