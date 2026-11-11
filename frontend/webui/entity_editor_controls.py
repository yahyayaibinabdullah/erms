"""Shared field rendering and value conversion; feature workflows remain in their owners."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from nicegui import ui
from .entities import EntitySpec, FieldSpec
from .relationship_select import relationship_select
from .i18n_catalogue import render_message
from .locale_services import current_locale_context, utc_instant_to_working, working_datetime_to_utc, working_zone

ENTITY_METADATA_LABEL_KEYS = {
    "Managing role": "entity_metadata.field.managing_role",
    "File Administrator role": "entity_metadata.field.file_administrator_role",
    "Account type": "entity_metadata.field.account_type",
    "Aggregation": "entity_metadata.field.aggregation",
    "Aggregation number": "entity_metadata.field.aggregation_number",
    "Assigned location": "entity_metadata.field.assigned_location",
    "Authority": "entity_metadata.field.authority",
    "Built-in": "entity_metadata.field.built_in",
    "Category": "entity_metadata.field.category",
    "Classification": "entity_metadata.field.classification",
    "Classification scheme": "entity_metadata.field.classification_scheme",
    "Classification type": "entity_metadata.field.classification_type",
    "Code": "entity_metadata.field.code",
    "Current location": "entity_metadata.field.current_location",
    "Current retention (years)": "entity_metadata.field.current_retention_years",
    "Date closed": "entity_metadata.field.date_closed",
    "Date of next review": "entity_metadata.field.date_of_next_review",
    "Date opened": "entity_metadata.field.date_opened",
    "Date originated": "entity_metadata.field.date_originated",
    "Date published": "entity_metadata.field.date_published",
    "Deactivated": "entity_metadata.field.deactivated",
    "Description": "entity_metadata.field.description",
    "Edition": "entity_metadata.field.edition",
    "Email": "entity_metadata.field.email",
    "External ID": "entity_metadata.field.external_id",
    "Final disposition": "entity_metadata.field.final_disposition",
    "Information-governance role": "entity_metadata.field.information_governance_role",
    "Inherited location": "entity_metadata.field.inherited_location",
    "Intermediate retention (years)": "entity_metadata.field.intermediate_retention_years",
    "Keywords": "entity_metadata.field.keywords",
    "Level": "entity_metadata.field.level",
    "Level number": "entity_metadata.field.level_number",
    "Location": "entity_metadata.field.location",
    "Medium": "entity_metadata.field.medium",
    "Name": "entity_metadata.field.name",
    "Number": "entity_metadata.field.number",
    "Organization unit": "entity_metadata.field.organization_unit",
    "Parent": "entity_metadata.field.parent",
    "Parent aggregation": "entity_metadata.field.parent_aggregation",
    "Parent classification": "entity_metadata.field.parent_classification",
    "Parent organization unit": "entity_metadata.field.parent_organization_unit",
    "Prevents disposition": "entity_metadata.field.prevents_disposition",
    "Profile": "entity_metadata.field.profile",
    "Published": "entity_metadata.field.published",
    "Record number": "entity_metadata.field.record_number",
    "Reserved": "entity_metadata.field.reserved",
    "Resource type": "entity_metadata.field.resource_type",
    "Retention and disposal instructions": "entity_metadata.field.retention_disposal_instructions",
    "Review": "entity_metadata.field.review",
    "Scheme": "entity_metadata.field.scheme",
    "Scope note": "entity_metadata.field.scope_note",
    "Security clearance": "entity_metadata.field.security_clearance",
    "Security level": "entity_metadata.field.security_level",
    "Status": "entity_metadata.field.status",
    "Supervising role": "entity_metadata.field.supervising_role",
    "Title": "entity_metadata.field.title",
    "Type": "entity_metadata.field.type",
    "Vital": "entity_metadata.field.vital",
    "Vital aggregation": "entity_metadata.field.vital_aggregation",
    "Vital record": "entity_metadata.field.vital_record",
}


def entity_metadata_label(label: str) -> str:
    return render_message(ENTITY_METADATA_LABEL_KEYS[label])


def medium_options() -> dict[str, str]:
    return {
        "digital": render_message("webui.field_input.select.digital_a8c0d87b"),
        "physical": render_message("webui.field_input.select.physical_c583106a"),
        "mixed": render_message("webui.field_input.select.mixed_3c647345"),
    }


def field_input(field: FieldSpec, value: Any = None, options: dict[int, str] | None = None):
    localized_label = entity_metadata_label(field.label)
    display_label = render_message("webui.field_input.text.label_29445dc3", label=localized_label) if field.required else localized_label
    if field.kind == "account_type":
        return ui.select(
            {"person": render_message("webui.field_input.select.person_d4b133be"), "service": render_message("webui.field_input.select.service_9bbc2101")},
            label=display_label, value=value or "person",
        ).props("outlined").classes("w-full")
    if field.kind == "classification_type":
        return ui.select(
            {False: render_message("webui.field_input.select.branch_may_contain_children_10410e17"), True: render_message("webui.field_input.select.terminal_assignable_to_root_aggregations_b091e9dc")},
            label=display_label, value=False if value is None else value,
        ).props("outlined").classes("w-full")
    if field.kind == "disposition":
        return ui.select({
            "destruction": render_message("webui.field_input.select.destruction_2711246f"),
            "transfer_to_external_archive": render_message("webui.field_input.select.permanent_preservation_external_archive_53d3f9f7"),
            "selective_preservation": render_message("webui.field_input.select.selective_preservation_04d0086f"),
            "retain_as_local_archives": render_message("webui.field_input.select.retain_as_local_archives_8d22b8ed"),
        }, label=display_label, value=value, clearable=True).props("outlined").classes("w-full")
    if field.kind == "medium":
        control = ui.select(medium_options(), label=display_label, value=value).props("outlined options-dense").classes("w-full")
        control.tooltip(render_message("webui.field_input.tooltip.how_the_resource_is_held_digital_files_phy_317d9b8b"))
        return control
    if field.kind == "textarea":
        return ui.textarea(display_label, value=value or "").props("outlined autogrow").classes("w-full")
    if field.kind == "int":
        return ui.number(display_label, value=value, format="%.0f").props("outlined").classes("w-full")
    if field.kind == "bool":
        return ui.checkbox(display_label, value=bool(value))
    if field.kind in {"lookup", "classification"}:
        return relationship_select(
            display_label, options or {}, value=value, required=field.required
        )
    if field.kind == "datetime":
        rendered = ""
        if value:
            _, timezone_name = current_locale_context()
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            rendered = utc_instant_to_working(parsed, timezone_name).strftime("%Y-%m-%dT%H:%M")
        props = "outlined type=datetime-local"
        if field.name == "date_of_next_review":
            _, timezone_name = current_locale_context()
            props += f" min={datetime.now(timezone.utc).astimezone(working_zone(timezone_name)).strftime('%Y-%m-%dT%H:%M')}"
        return ui.input(display_label, value=rendered).props(props).classes("w-full")
    return ui.input(display_label, value=value or "").props("outlined").classes("w-full")


def form_payload(spec: EntitySpec, controls: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in spec.fields:
        if field.name not in controls:
            continue
        value = controls[field.name].value
        if field.kind in {"int", "lookup", "classification"} and value not in (None, ""):
            value = int(value)
        if field.kind == "datetime" and value:
            _, timezone_name = current_locale_context()
            value = working_datetime_to_utc(
                datetime.fromisoformat(value), timezone_name,
            ).isoformat().replace("+00:00", "Z")
        if isinstance(value, str):
            value = value.strip()
        if field.required and value in (None, ""):
            raise ValueError(render_message("entity_metadata.validation.required", field=entity_metadata_label(field.label)))
        if creating and value in (None, "") and not field.required:
            continue
        payload[field.name] = None if value == "" else value
    return payload

