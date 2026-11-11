from __future__ import annotations
from frontend.webui.disposition.tasks import tasks_screen
from frontend.webui.disposition.screens import eligibility_screen, jobs_screen, job_screen, accelerate_dialog
from frontend.webui.disposition.messages import text as disposition_text, status_label as disposition_status_label

from frontend.webui.event_labels import event_label

import asyncio
import base64
import copy
import inspect
import json
from datetime import datetime, timedelta, timezone
from html import escape as html_escape
from pathlib import Path
from typing import Any, Callable
from zoneinfo import available_timezones

from nicegui import app, background_tasks, context, events, ui

from .aggregation_editor import (
    lock_aggregation_close_field,
    load_aggregation_creation_context,
    render_aggregation_creation_controls,
    aggregation_initial_security_level,
    aggregation_initial_medium,
    render_aggregation_close_help,
    configure_aggregation_classification,
    configure_aggregation_parent_rules,
    prepare_aggregation_payload,
)
from .aggregation_presentation import CHILD_AGGREGATION_CLASSIFICATION_HELP, AGGREGATION_SUMMARY_LAYOUT_CLASSES, direct_classification_label, effective_closure
from .relationship_select_styles import style_relationship_chip_select
from .aggregation_state import new_aggregation_state
from .aggregation_actions import build_aggregation_actions
from .aggregation_selector import build_aggregation_selector
from .aggregation_details import build_aggregation_details
from .aggregation_browser import build_aggregation_browser
from .aggregation_toolbar import build_aggregation_toolbar
from .component_presentation import localized_component_status, localized_indexing_status, component_file_icon, native_preview_kind, requires_document_conversion, component_is_previewable, component_uploader
from .upload_buffers import buffer_upload_batch
from .component_cards import build_component_cards
from .component_presentation import CONVERTIBLE_PREVIEW_EXTENSIONS
from .component_preview import build_component_preview
from .components import build_components
from .api_client import ApiError, ErmsApiClient
from .relationship_select import relationship_select
from .application_shell import build_header, build_footer, build_drawer, build_content
from .navigation_data import (
    NAVIGATION_TRAIL_LIMIT, NAVIGATION_VISIBLE_LIMIT,
    append_navigation_entry, navigation_entry_identity, visible_navigation_indices,
)
from .navigation_drawer import navigation_menu
from .navigation_controller import NavigationController
from .session_context import SessionContext
from .audit_workspace import build_audit_workspace
from .login_sessions import build_login_sessions
from .holds_people import build_people_select
from .hold_editor import build_hold_editor
from .hold_resources import build_hold_resources
from .holds import build_holds
from .hold_details import build_hold_details
from .hold_navigation import build_hold_navigation
from .holds_people import style_person_select
from .translation_administration import build_translation_administration
from .translation_inspector import build_translation_inspector
from .account_localization import build_account_localization
from .account_preferences import build_account_preferences
from .account_profile import build_account_profile
from .account_password import build_account_password
from .account_bootstrap import build_account_bootstrap
from .account_sign_in import build_sign_in, build_login_error_message
from .text_indexers import build_text_indexers
from .text_indexer_details import build_text_indexer_details
from .organization_table import (
    organization_table_filters, organization_user_slots, organization_leading_actions, organization_membership_action, organization_user_actions, organization_lifecycle_actions, bind_organization_table_destinations, LIFECYCLE_ACTION_BUTTONS, USER_SUSPENSION_ACTION_BUTTONS,
)
from .organization_collection_actions import build_issue_password, build_change_suspension, build_confirm_lifecycle
from .organization_editor import (
    configure_designation_field, configure_role_profile_field, configure_organization_browser_field, configure_role_governance_field, organization_reason_input, organization_change_reason, protected_organization_role, read_organization_editor_row,
)
from .organization_collections import decorate_organization_rows
from .identity_presentation import user_avatar, render_user_avatar, USER_AVATAR_BACKGROUND, USER_AVATAR_TEXT
from .organization_memberships import filter_membership_rows
from .organization_editor import inactive_org_unit_source, role_change_requires_reason
from .organization_deletion import deletion_identity, deletion_blocked_report
from .administration_cards import build_administration_cards
from .organization_memberships import build_organization_memberships
from .organization_deletion import build_organization_deletion
from .organization_units import build_organization_units
from .organization_roles import build_organization_roles
from .organization_users import build_organization_users
from .organization_browser import build_organization_browser
from .security_level_controls import build_security_selector, build_security_level_change
from .access_control_dialogs import build_access_control_dialogs
from .access_explanation_dialog import build_access_explanation
from .security_administration import (
    build_profile_privilege_editor, localized_profile_value, localized_privilege_name,
    localized_privilege_description, localized_privilege_category, localized_privilege_matches_search,
    profile_translation_only, configure_profile_field, profile_reason_input,
    prepare_profile_update, profile_change_reason as validated_profile_change_reason,
)
from .entity_selectors import (relationship_options, relationship_search_query, apply_relationship_selection, build_relationship_selector)
from .entity_translation_editor import entity_translation_editor
from .entity_editor_controls import ENTITY_METADATA_LABEL_KEYS, entity_metadata_label, medium_options, field_input, form_payload
from .resource_number_controls import build_number_controls
from .collection_hydration import build_row_hydrators
from .collection_controls import build_collection_loader, bind_collection_paging
from .personal_resources import PersonalResourceState, build_personal_resources
from .personal_resource_views import build_personal_resource_views
from .compact_resource_view import build_compact_resource_view
from .classification_controller import ClassificationController
from .classification_selectors import build_scheme_selector, build_classification_pickers
from .classification_editor import (
    load_direct_retention, retention_editor_source, configure_scheme_field,
    prepare_retention_payload, decorate_classifications,
    render_classification_search_prompt, scheme_action_buttons, bind_scheme_actions,
)
from .application_settings import disposition_warning_panel
from .application_settings_controller import ApplicationSettingsController
from .messaging_workspace import messaging_workspace
from .resource_inspector import resource_inspector
from .messaging_live import LiveMailbox, stream_events, mailbox_cursor_key
from .notification_administration import notification_administration
from .resource_relationships import relationship_panel
from .relationship_types_controller import RelationshipTypesController
from .messaging_monitor import messaging_monitor
from .retention_timeline import render_disposition_date, render_retention_stages
from .capabilities import (
    capability_allowed,
    can_add_from_collection,
    can_edit_entity_translation,
    can_navigate,
    can_navigate_disposition,
    can_open_organization_detail,
)
from .authorization_ui import (
    gate_label, OPERATIONS, acl_source_label, aggregation_reference_label,
    authorization_code_label, decision_code_label, operation_label, gate_detail, ordered_permission_catalogue,
    privilege_help_text, privilege_matches_search, security_level_label,
)
from .config import (
    api_url,
    dashboard_favourite_item_limit,
    dashboard_recent_days,
    dashboard_recent_item_limit,
    database_display_name,
    default_root_aggregation_medium,
    full_text_search_enabled,
    classification_recent_selection_limit,
    host,
    port,
    reload_enabled,
    storage_secret,
    user_details_session_limit,
)
from .entities import ENTITIES, EntitySpec, FieldSpec
from .i18n_catalogue import (
    clear_active_messages, disable_diagnostic_metadata, enable_diagnostic_metadata, render_message,
    render_message_plain, set_active_messages, strip_diagnostic_metadata,
)
from .locale_services import (
    clear_locale_context, current_locale_context, format_instant, format_local_date,
    LocalizedTimezoneError,
    set_locale_context, utc_instant_to_working, working_datetime_to_utc, working_zone,
)
from .rtl import document_direction_script, normalize_direction


app.add_static_files("/static/pdfjs", Path(__file__).with_name("static") / "pdfjs")
app.add_static_files("/static/brand", Path(__file__).with_name("static") / "brand")
app.add_static_files("/static/login", Path(__file__).with_name("static") / "login")
app.add_static_files("/static/fonts", Path(__file__).with_name("static") / "fonts")
app.add_static_files("/static/inspector", Path(__file__).with_name("static"))

CLASSIFICATION_WORKSPACE_SEARCH_FIELDS = ("code", "title", "description", "keywords")
CLASSIFICATION_SELECTOR_SEARCH_FIELDS = ("code", "title", "description", "keywords")
RECORD_UPLOAD_WAIT_MESSAGE = render_message("webui.module.text.please_wait_until_all_files_have_finished_65b4bf18")
RECORD_DETAIL_HEADER_CLASSES = "w-full items-center gap-3 no-wrap"
RECORD_DETAIL_TITLE_CLASSES = "gap-0 grow min-w-0"
RELATIONSHIP_DISPLAY_FIELDS = frozenset({
    "aggregation_display",
    "org_unit_display",
    "parent_org_unit_display",
    "profile_display",
    "scheme_display",
})
STOP_PROPAGATION_CLICK_HANDLER = "(event) => { event.stopPropagation(); emit(); }"

ADVANCED_SEARCH_FIELDS: dict[str, dict[str, tuple[str, str, bool]]] = {
    "records": {
        "record_number": ("advanced_search.field.record_number", "text", False),
        "disposition_status": ("disposition.ui.status", "integer", False),
        "title": ("advanced_search.field.title", "text", False),
        "description": ("advanced_search.field.description", "text", True),
        "aggregation_id": ("advanced_search.field.aggregation", "integer", True),
        "date_created": ("advanced_search.field.date_created", "datetime", False),
        "date_originated": ("advanced_search.field.date_originated", "datetime", False),
        "medium": ("advanced_search.field.medium", "text", False),
        "is_vital": ("advanced_search.field.vital_record", "boolean", False),
        "date_of_next_review": ("advanced_search.field.next_review", "datetime", True),
        "effective_assigned_location": ("advanced_search.field.assigned_location", "text", True),
        "effective_current_location": ("advanced_search.field.current_location", "text", True),
        "security_level_id": ("advanced_search.field.security_level", "integer", False),
        "owning_org_unit_id": ("advanced_search.field.owning_org_unit", "integer", False),
        "on_effective_hold": ("advanced_search.field.on_hold", "boolean", False),
        "component.file_name": ("advanced_search.field.file_name", "text", False),
        "component.mime_type": ("advanced_search.field.mime_type", "text", False),
        "component.size_in_bytes": ("advanced_search.field.size_in_bytes", "integer", False),
        "component.date_created": ("advanced_search.field.date_created", "datetime", False),
        "component.date_originated": ("advanced_search.field.date_originated", "datetime", False),
        "component.checksum_algorithm": ("advanced_search.field.checksum_algorithm", "text", False),
        "component.checksum_value": ("advanced_search.field.checksum_value", "text", False),
        "component.content_status": ("advanced_search.field.content_status", "text", False),
    },
    "aggregations": {
        "aggregation_number": ("advanced_search.field.aggregation_number", "text", False),
        "effective_retention.current_period_years": ("advanced_search.field.effective_current_period_years", "integer", False),
        "effective_retention.intermediate_period_years": ("advanced_search.field.effective_intermediate_period_years", "integer", False),
        "effective_retention.final_disposition": ("advanced_search.field.effective_disposition_action", "choice", False),
        "disposition_status": ("disposition.ui.status", "integer", False),
        "title": ("advanced_search.field.title", "text", False),
        "description": ("advanced_search.field.description", "text", True),
        "parent_aggregation_id": ("advanced_search.field.parent_aggregation", "integer", True),
        "classification_id": ("advanced_search.field.classification", "integer", True),
        "date_created": ("advanced_search.field.date_created", "datetime", False),
        "date_opened": ("advanced_search.field.date_opened", "datetime", False),
        "date_closed": ("advanced_search.field.date_closed", "datetime", True),
        "medium": ("advanced_search.field.medium", "text", False),
        "is_vital": ("advanced_search.field.vital_aggregation", "boolean", False),
        "date_of_next_review": ("advanced_search.field.next_review", "datetime", True),
        "effective_assigned_location": ("advanced_search.field.assigned_location", "text", True),
        "effective_current_location": ("advanced_search.field.current_location", "text", True),
        "security_level_id": ("advanced_search.field.security_level", "integer", False),
        "owning_org_unit_id": ("advanced_search.field.owning_org_unit", "integer", False),
        "on_effective_hold": ("advanced_search.field.on_hold", "boolean", False),
    },
}

ADVANCED_SEARCH_COMPONENT_FIELDS = frozenset(
    field for field in ADVANCED_SEARCH_FIELDS["records"] if field.startswith("component.")
)
ADVANCED_SEARCH_RETENTION_FIELDS = frozenset(
    field for field in ADVANCED_SEARCH_FIELDS["aggregations"] if field.startswith("effective_retention.")
)
ADVANCED_SEARCH_RELATIONSHIP_FIELDS = frozenset({
    "aggregation_id", "parent_aggregation_id", "classification_id",
    "security_level_id", "owning_org_unit_id",
})
ADVANCED_SEARCH_CONTROLLED_VALUES: dict[str, dict[Any, str]] = {
    "effective_retention.final_disposition": {
        "destruction": "disposition.ui.destruction",
        "transfer_to_external_archive": "disposition.ui.permanent_transfer",
        "selective_preservation": "disposition.ui.selective_transfer",
        "retain_as_local_archives": "disposition.ui.local_archives",
    },
    "disposition_status": {1: "disposition.ui.status_1",2: "disposition.ui.status_2",3: "disposition.ui.status_3",4: "disposition.ui.status_4",5: "disposition.ui.status_5",6: "disposition.ui.status_6",7: "disposition.ui.status_7",8: "disposition.ui.status_8",9: "disposition.ui.status_9",10: "disposition.ui.status_10",11: "disposition.ui.status_11",12: "disposition.ui.status_12",13: "disposition.ui.status_13"},
    "medium": {"digital": "advanced_search.value.digital", "physical": "advanced_search.value.physical", "mixed": "advanced_search.value.mixed"},
    "component.content_status": {
        "pending": "advanced_search.value.pending", "uploading": "advanced_search.value.uploading", "available": "advanced_search.value.available",
        "failed": "advanced_search.value.failed", "quarantined": "advanced_search.value.quarantined", "deleted": "advanced_search.value.deleted",
    },
}

# Entity metadata labels live in schema descriptors because they are also used
# by validation and API-shaping code.  Resolve them at the presentation edge so
# every table, editor and selector receives the active locale consistently.




def localized_lifecycle_value(value: Any) -> str:
    return {
        "active": render_message("webui.render_table.text.active_3a692d6a"),
        "inactive": render_message("webui.render_table.text.inactive_ffa76f23"),
        "suspended": render_message("webui.show_organization_structure.select.suspended_e5b9d9f5"),
        "current": render_message("webui.show_organization_structure.select.current_8d79efc1"),
        "future": render_message("webui.show_organization_structure.select.future_875190f7"),
        "expired": render_message("webui.select_login_sessions.select.expired_4f6360cb"),
        "revoked": render_message("webui.select_login_sessions.select.revoked_c6e031f9"),
    }.get(str(value or "").lower(), str(value or "—"))










def localized_account_type(value: Any) -> str:
    return {
        "person": render_message("webui.render_table.select.person_71413829"),
        "service": render_message("webui.render_table.select.service_e1263edf"),
    }.get(str(value or "").lower(), str(value or "—"))


EDITOR_ENTITY_LABEL_KEYS = {
    "aggregations": "dashboard.resource.aggregation",
    "records": "dashboard.resource.record",
    "classification-schemes": "entity_metadata.field.classification_scheme",
    "classifications": "entity_metadata.field.classification",
    "org-units": "entity_metadata.field.organization_unit",
    "users": "entity_metadata.field.user",
    "roles": "entity_metadata.field.role",
    "security-levels": "entity_metadata.field.security_level",
    "profiles": "entity_metadata.field.profile",
}


def localized_editor_entity(resource_key: str, fallback: str) -> str:
    key = EDITOR_ENTITY_LABEL_KEYS.get(resource_key)
    return render_message(key) if key else fallback


def localized_disposition_value(value: Any) -> str:
    return {
        "destruction": render_message("webui.field_input.select.destruction_2711246f"),
        "transfer_to_external_archive": render_message("webui.field_input.select.permanent_preservation_external_archive_53d3f9f7"),
        "selective_preservation": render_message("webui.field_input.select.selective_preservation_04d0086f"),
        "retain_as_local_archives": render_message("webui.field_input.select.retain_as_local_archives_8d22b8ed"),
    }.get(str(value or ""), str(value or "—"))




def advanced_search_field_options(resource: str, *, can_manage_disposition: bool = False) -> dict[str, str]:
    """Return visibly grouped labels while retaining canonical field values."""
    return {
        field: (
            render_message("advanced_search.field.digital_component_qualified", field=render_message(details[0]))
            if field in ADVANCED_SEARCH_COMPONENT_FIELDS
            else render_message(
                "advanced_search.field.resource_qualified",
                resource=render_message(
                    "advanced_search.resource.record" if resource == "records"
                    else "advanced_search.resource.aggregation"
                ),
                field=render_message(details[0]),
            )
        )
        for field, details in ADVANCED_SEARCH_FIELDS[resource].items()
        if field != "disposition_status" or can_manage_disposition
    }


def advanced_search_empty_value(field: str, operator: str, kind: str) -> Any:
    if operator in {"between", "in", "not_in"}:
        return []
    if field in ADVANCED_SEARCH_RELATIONSHIP_FIELDS or kind in {"integer", "boolean", "choice"}:
        return None
    return ""


def advanced_search_operators(kind: str, nullable: bool) -> dict[str, str]:
    common = {"eq": render_message("advanced_search.operator.is"), "ne": render_message("advanced_search.operator.is_not")}
    if kind == "choice":
        common |= {"in": render_message("advanced_search.operator.is_one_of"), "not_in": render_message("advanced_search.operator.is_not_one_of")}
    if kind == "text":
        common |= {"contains_ci": render_message("advanced_search.operator.contains"), "starts_with_ci": render_message("advanced_search.operator.starts_with"), "ends_with_ci": render_message("advanced_search.operator.ends_with"), "in": render_message("advanced_search.operator.is_one_of"), "not_in": render_message("advanced_search.operator.is_not_one_of")}
    elif kind in {"integer", "datetime"}:
        common |= {"lt": render_message("advanced_search.operator.less_than"), "lte": render_message("advanced_search.operator.at_most"), "gt": render_message("advanced_search.operator.greater_than"), "gte": render_message("advanced_search.operator.at_least"), "between": render_message("advanced_search.operator.between"), "in": render_message("advanced_search.operator.is_one_of"), "not_in": render_message("advanced_search.operator.is_not_one_of")}
    if nullable:
        common |= {"is_null": render_message("advanced_search.operator.is_empty"), "is_not_null": render_message("advanced_search.operator.is_not_empty")}
    return common


def advanced_search_leaf_count(node: dict[str, Any]) -> int:
    if node.get("type") == "condition":
        return 1
    return sum(advanced_search_leaf_count(child) for child in node.get("children", []))


def advanced_search_depth(node: dict[str, Any]) -> int:
    if node.get("type") == "condition":
        return 1
    children = node.get("children", [])
    return 1 + (max((advanced_search_depth(child) for child in children), default=0))


def advanced_search_has_positive_full_text(node: dict[str, Any], positive: bool = True) -> bool:
    if node.get("type") == "condition":
        return positive and node.get("kind") == "full_text"
    polarity = not positive if node.get("operator") == "not" else positive
    return any(advanced_search_has_positive_full_text(child, polarity) for child in node.get("children", []))


def advanced_search_has_component_field(node: dict[str, Any]) -> bool:
    if node.get("type") == "condition":
        return node.get("kind") == "structured" and node.get("field") in ADVANCED_SEARCH_COMPONENT_FIELDS
    return any(advanced_search_has_component_field(child) for child in node.get("children", []))


def compile_advanced_search_node(node: dict[str, Any], resource: str) -> dict[str, Any]:
    if node.get("type") == "condition":
        if node.get("kind") == "full_text":
            query = str(node.get("query") or "").strip()
            if not query:
                raise ValueError(render_message("advanced_search.validation.full_text_required"))
            sources = node.get("sources") or (["metadata", "components"] if resource == "records" else ["metadata"])
            return {"full_text": {"query": query, "sources": sources}}
        field = node.get("field")
        if field not in ADVANCED_SEARCH_FIELDS[resource]:
            raise ValueError(render_message("advanced_search.validation.field_required"))
        _, kind, nullable = ADVANCED_SEARCH_FIELDS[resource][field]
        operator = node.get("operator")
        if operator not in advanced_search_operators(kind, nullable):
            raise ValueError(render_message("advanced_search.validation.operator_required"))
        result: dict[str, Any] = {"field": field, "operator": operator}
        if operator not in {"is_null", "is_not_null"}:
            value = node.get("value")
            if operator in {"between", "in", "not_in"}:
                if not isinstance(value, list) or not value or any(item in (None, "") for item in value):
                    raise ValueError(render_message("advanced_search.validation.value_required"))
            elif value in (None, ""):
                raise ValueError(render_message("advanced_search.validation.value_required"))
            if field in ADVANCED_SEARCH_RETENTION_FIELDS:
                values = value if operator in {"between", "in", "not_in"} else [value]
                if field == "effective_retention.final_disposition":
                    if any(item not in ADVANCED_SEARCH_CONTROLLED_VALUES[field] for item in values):
                        raise ValueError(render_message("advanced_search.validation.retention_action"))
                else:
                    normalized = []
                    try:
                        for item in values:
                            number = int(item)
                            if isinstance(item, bool) or number < 0 or (not isinstance(item, str) and number != item):
                                raise ValueError
                            normalized.append(number)
                    except (ValueError, TypeError, OverflowError):
                        raise ValueError(render_message("advanced_search.validation.retention_years")) from None
                    value = normalized if operator in {"between", "in", "not_in"} else normalized[0]
                if operator == "between" and len(values) != 2:
                    raise ValueError(render_message("advanced_search.validation.value_required"))
            result["value"] = value
        return result
    children = node.get("children", [])
    if not children:
        raise ValueError(render_message("advanced_search.validation.group_empty"))
    operator = node.get("operator", "and")
    if operator == "not":
        if len(children) != 1:
            raise ValueError(render_message("advanced_search.validation.not_single_child"))
        return {"not": compile_advanced_search_node(children[0], resource)}
    if operator not in {"and", "or"}:
        raise ValueError(render_message("advanced_search.validation.group_operator_required"))
    return {operator: [compile_advanced_search_node(child, resource) for child in children]}


def advanced_search_node_from_expression(expression: dict[str, Any]) -> dict[str, Any]:
    """Convert canonical API grammar into the visual builder's editable tree."""
    if "full_text" in expression:
        full_text = expression["full_text"]
        return {
            "type": "condition", "kind": "full_text",
            "query": full_text.get("query", ""),
            "sources": list(full_text.get("sources") or []),
        }
    if "field" in expression:
        node = {
            "type": "condition", "kind": "structured",
            "field": expression["field"], "operator": expression["operator"],
        }
        if "value" in expression:
            node["value"] = expression["value"]
        return node
    if "not" in expression:
        return {
            "type": "group", "operator": "not",
            "children": [advanced_search_node_from_expression(expression["not"])],
        }
    operator = "and" if "and" in expression else "or"
    return {
        "type": "group", "operator": operator,
        "children": [advanced_search_node_from_expression(child) for child in expression[operator]],
    }

LAST_CUSTODIAN_TITLE = render_message("webui.module.text.this_change_can_t_be_made_yet_54b54067")
LAST_CUSTODIAN_MESSAGE = (
    render_message("webui.module.text.this_change_would_remove_the_only_active_p_71a19f0b")
)




def favourite_preview(items: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Return a bounded Dashboard preview and whether more entries exist."""
    return items[:limit], len(items) > limit


def personal_dialog_list_height(item_count: int) -> int:
    """Return a compact list height that caps long dialogs for scrolling."""
    return min(520, max(120, item_count * 58))








def display_value(value: Any) -> str:
    if value is None:
        return "—"
    return str(value)




def medium_label(value: Any) -> str:
    return {
        "digital": render_message("advanced_search.value.digital"),
        "physical": render_message("advanced_search.value.physical"),
        "mixed": render_message("advanced_search.value.mixed"),
    }.get(str(value or "").lower(), "—")




def review_state(value: Any) -> str | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
    return "Overdue" if parsed <= now else "Upcoming"


def review_display(value: Any) -> str:
    state = review_state(value)
    if not state:
        return "—"
    localized_state = render_message(
        "dashboard.review.overdue"
        if state == "Overdue" else "dashboard.review.upcoming"
    )
    return f"{localized_state} · {format_timestamp(value)}"






def record_draft_component_context(
    aggregation_id: Any, medium: Any,
) -> dict[str, Any]:
    """Return the persisted draft context required before staging content."""
    if aggregation_id in (None, "") or medium in (None, ""):
        raise ValueError(
            "Select the parent aggregation and record medium before adding digital files."
        )
    return {"aggregation_id": int(aggregation_id), "medium": str(medium)}


def format_timestamp(value: Any) -> str:
    if not value:
        return "—"
    try:
        try:
            language, timezone_name = current_locale_context()
        except RuntimeError:
            return str(value)  # No timezone authority before API localization.
        return format_instant(value, timezone_name, language)
    except (ValueError, TypeError):
        return str(value)


def format_date(value: Any) -> str:
    if not value:
        return "—"
    try:
        try:
            language, _ = current_locale_context()
        except RuntimeError:
            language = "en"
        return format_local_date(value, language)
    except (ValueError, TypeError):
        return str(value)


def format_file_size(value: Any) -> str:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return "—"
    units = ("B", "KB", "MB", "GB", "TB")
    amount = float(size)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{int(amount)} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{size} B"


def review_datetime_input_value(value: Any) -> str:
    """Render a stored UTC instant for a browser ``datetime-local`` control."""
    if not value:
        return ""
    _, timezone_name = current_locale_context()
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return utc_instant_to_working(parsed, timezone_name).strftime("%Y-%m-%dT%H:%M")


def review_datetime_input_minimum() -> str:
    _, timezone_name = current_locale_context()
    return datetime.now(timezone.utc).astimezone(
        working_zone(timezone_name)
    ).strftime("%Y-%m-%dT%H:%M")


def review_datetime_payload(value: str | None) -> str | None:
    """Convert working-timezone ``datetime-local`` input into a UTC instant."""
    if not value:
        return None
    _, timezone_name = current_locale_context()
    return working_datetime_to_utc(
        datetime.fromisoformat(value), timezone_name,
    ).isoformat().replace("+00:00", "Z")


def validation_error_message(error: ValueError) -> str:
    if isinstance(error, LocalizedTimezoneError):
        return render_message(error.message_key, **error.parameters)
    return str(error)


















render_component_cards = build_component_cards(format_timestamp=format_timestamp, format_file_size=format_file_size)




def add_timestamp_slots(table: Any, column_names: list[str]) -> None:
    for key in column_names:
        table.add_slot(f"body-cell-{key}", """
            <q-td :props="props">
              <div v-if="props.value" class="row items-center no-wrap q-gutter-sm timestamp-cell">
                <q-icon name="schedule" color="blue-grey-4" size="18px" />
                <div class="column no-wrap">
                  <span class="timestamp-date">{{ new Date(props.value).toLocaleDateString(undefined, {day: 'numeric', month: 'short', year: 'numeric'}) }}</span>
                  <span class="timestamp-time">{{ new Date(props.value).toLocaleTimeString(undefined, {hour: 'numeric', minute: '2-digit'}) }}</span>
                </div>
                <q-tooltip>{{ props.value }}</q-tooltip>
              </div>
              <span v-else class="text-grey-5">—</span>
            </q-td>
        """)




def error_message(error: ApiError) -> str:
    if error.status_code == 404 and error.message == "saved search not found":
        return render_message_plain("saved_search.error.unavailable")
    if error.status_code == 412:
        return render_message_plain("common.error.stale_version")
    if error.status_code == 428:
        return render_message_plain("common.error.precondition_required")
    if error.message == "X-Change-Reason is required when lowering a security level":
        return render_message_plain("security_level.error.lower_reason_required")
    if error.message == "X-Change-Reason is required when changing a security level":
        return render_message_plain("security_level.error.change_reason_required")
    if "saved_searches_owner_name_ci_unique" in error.message:
        return render_message_plain("saved_search.error.name_exists")
    if isinstance(error.detail, dict):
        if error.detail.get("code") == "privilege_dependency_violation":
            return "\n".join(
                render_message_plain("authorization.profile.error.missing_prerequisite",
                                     privilege=item["privilege_code"], required=item["required_code"])
                for item in error.detail.get("missing", [])
            )
        if error.detail.get("message_key"):
            return render_message_plain(
                error.detail["message_key"], **(error.detail.get("parameters") or {}),
            )
        messages = {
            "aggregation_medium_contents_conflict": "resource_medium.error.contents_conflict",
            "aggregation_medium_mismatch": "resource_medium.error.parent_conflict",
            "record_medium_not_allowed_by_parent": "resource_medium.error.record_parent_conflict",
            "medium_change_reason_required": "resource_medium.error.reason_required",
            "physical_record_has_digital_components": "resource_medium.error.components_present",
            "insufficient_privilege": "authorization.error.insufficient_privilege",
            "insufficient_resource_permission": "authorization.error.insufficient_resource_permission",
            "insufficient_clearance": "authorization.error.insufficient_clearance",
        }
        if error.detail.get("code") in messages:
            return render_message_plain(messages[error.detail["code"]])
    status_messages = {
        400: "common.error.bad_request",
        401: "common.error.authentication_required",
        403: "common.error.forbidden",
        404: "common.error.not_found",
        409: "common.error.conflict",
        413: "common.error.payload_too_large",
        422: "common.error.validation_failed",
        429: "common.error.too_many_requests",
        503: "common.error.service_unavailable",
    }
    return render_message_plain(status_messages.get(error.status_code, "shared.errors.unexpected"))


login_error_message = build_login_error_message(error_message)


def clear_medium_error(control) -> None:
    # NiceGUI validation requires its error prop to remain present.
    control.error = None


def highlight_medium_error(error: ApiError, control) -> None:
    if control is not None and isinstance(error.detail, dict) and error.detail.get("code") in {
        "aggregation_medium_contents_conflict", "aggregation_medium_mismatch",
        "record_medium_not_allowed_by_parent", "physical_record_has_digital_components",
    }:
        control.props['error'] = True
        control.props['error-message'] = error_message(error)
        control.update()


def show_api_error(error: ApiError) -> None:
    """Present continuity blocks persistently; keep ordinary API errors as notices."""
    detail_code = (
        error.detail.get("code") if isinstance(error.detail, dict) else error.detail
    )
    if detail_code != "last_governance_custodian":
        ui.notify(error_message(error), color="negative", close_button=True)
        return

    dialog = ui.dialog().props("persistent")
    with dialog, ui.card().classes("w-[560px] max-w-full p-5 gap-4"):
        with ui.row().classes("w-full items-start gap-3 no-wrap"):
            ui.icon("shield", color="negative", size="32px").classes("shrink-0")
            with ui.column().classes("gap-2"):
                ui.label(LAST_CUSTODIAN_TITLE).classes("text-xl font-semibold")
                ui.label(LAST_CUSTODIAN_MESSAGE).classes(
                    "text-sm leading-6 text-slate-700"
                )
        with ui.row().classes("w-full justify-end"):
            ui.button(render_message("webui.show_api_error.button.i_understand_03cb796b"), on_click=dialog.close).props(
                "unelevated no-caps autofocus color=primary"
            )
    dialog.open()














def relationship_cell(item: dict[str, Any] | None, *, number_field: str | None = None) -> dict[str, Any] | None:
    if item is None:
        return None
    localized = item.get("localized") or {}
    code = item.get("code") or (item.get(number_field) if number_field else None)
    return {
        "name": (
            localized.get("name") or localized.get("title")
            or item.get("name") or item.get("title")
            or f"Item {item['id']}"
        ),
        "code": code,
    }


def decorate_relationship_rows(
    resource: str,
    rows: list[dict[str, Any]],
    related_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    related_by_id = {item["id"]: item for item in (related_rows or rows)}
    decorated = []
    for row in rows:
        item = dict(row)
        if resource == "org-units":
            item["parent_org_unit_display"] = relationship_cell(
                related_by_id.get(row.get("parent_org_unit_id"))
            )
        elif resource == "roles":
            item["org_unit_display"] = relationship_cell(
                related_by_id.get(row.get("org_unit_id"))
            )
        elif resource == "records":
            item["aggregation_display"] = relationship_cell(
                related_by_id.get(row.get("aggregation_id")),
                number_field="aggregation_number",
            )
        decorated.append(item)
    return decorated






def style_status_chip_select(control: Any) -> None:
    """Render controlled component statuses as compact labelled chips."""
    control.props("options-dense").classes("component-status-chip-select")
    control.add_slot("option", """
        <q-item v-bind="props.itemProps">
          <q-item-section>
            <q-chip outline color="primary" icon="task_alt" :label="props.opt.label" />
          </q-item-section>
        </q-item>
    """)
    control.add_slot("selected-item", """
        <q-chip outline color="primary" icon="task_alt" removable
          @remove="props.removeAtIndex(props.index)" :label="props.opt.label" />
    """)






@ui.page("/")
def index(q: str = "") -> None:
    # A client per page prevents one browser's token leaking into another and
    # keeps it available when dashboard calls run in child asyncio tasks.
    api = ErmsApiClient(api_url())
    page_client = context.client
    page_client.on_disconnect(api.close)
    page_client.on_disconnect(lambda: clear_active_messages(page_client.id))
    page_client.on_disconnect(lambda: clear_locale_context(page_client.id))
    session = SessionContext(
        api=api, storage=lambda: app.storage.user,
        locale=lambda: state.get("localization") or {},
        reset_private_views=lambda: reset_private_views(),
        reset_navigation=lambda: reset_navigation_session(),
        clear_identity=lambda: clear_signed_in_identity(),
        close_menu=lambda: user_menu.close(), open_login=lambda: login_dialog.open(),
        set_connection_status=lambda connected: set_connection_status(connected),
    )
    auth_state = session.identity
    message_live = {"adapter": None, "api": None, "token": None, "notifications": []}
    cached_localization = app.storage.user.get("localization_context") or {}
    cached_messages = app.storage.user.get("localization_messages") or {}
    cached_fallback_keys = app.storage.user.get("localization_fallback_keys") or []
    if isinstance(cached_messages, dict):
        set_active_messages(cached_messages, cached_fallback_keys)
    initial_language = str(cached_localization.get("effective_language") or "en")
    initial_direction = normalize_direction(cached_localization.get("direction"))
    current_direction = {"value": initial_direction}

    def tree_expander_icon(expanded: bool) -> str:
        """Return a disclosure icon pointing into the hierarchy's reading direction."""
        if expanded:
            return "expand_more"
        return "chevron_left" if current_direction["value"] == "rtl" else "chevron_right"

    if cached_localization.get("working_timezone"):
        set_locale_context(initial_language, str(cached_localization["working_timezone"]))
    ui.query("html").props(f"lang={initial_language} dir={initial_direction}")


    personal = PersonalResourceState()
    aggregation_state = new_aggregation_state()
    state: dict[str, Any] = {
        "resource": "dashboard", "rows": [], "searched": False,
        "lifecycle_filter": "all",
        "global_search_query": q.strip(), "global_search_items": [],
        "global_search_cursor": None, "global_search_filter": "all",
        "global_search_page": 1, "global_search_page_size": 10,
        "global_search_return_anchor": None,
        "global_search_expanded_results": set(),
        "entity_result_states": {},
        "search_diagnostics_enabled": False, "search_diagnostics_sent": None,
        "search_diagnostics_accepted": None, "search_diagnostics_error": None,
        "collection_pages": {},
    }
    navigation_controller = NavigationController(
        stored=app.storage.user.get("navigation_trail"),
        write_trail=lambda trail: app.storage.user.__setitem__("navigation_trail", trail),
        prepare=lambda page: prepare_navigation(page),
        snapshot=lambda: current_navigation_snapshot(),
        label_key=lambda page: breadcrumb_message_keys.get(page),
        get_guard=lambda: state.get("discard_navigation_guard"),
        clear_guard=lambda: state.pop("discard_navigation_guard", None),
        cancel_reads=api.cancel_pending_reads,
        restore=lambda entry: restore_navigation_entry(entry),
        dashboard=lambda: select_dashboard(),
        render=lambda: render_navigation_breadcrumbs(),
        notify=ui.notify, on_error=error_message,
    )



    def bind_remote_saved_audience_select(
        control: Any, audience_kind: str, more_button: Any,
    ) -> tuple[Callable[..., Any], Callable[..., Any]]:
        """Attach a bounded typeahead to a saved-search role or unit selector."""
        request_state: dict[str, Any] = {"revision": 0, "task": None, "query": "", "offset": 0}

        def selected_values() -> list[int]:
            if control.multiple:
                return list(control.value or [])
            return [control.value] if control.value is not None else []

        def option_label(item: dict[str, Any]) -> str:
            name = (item.get("localized") or {}).get("name") or item.get("name") or item["id"]
            return f"{name} ({item['code']})" if item.get("code") else str(name)

        async def load_options(query: str = "", *, append: bool = False) -> None:
            request_state["revision"] += 1
            revision = request_state["revision"]
            selected = set(selected_values())
            retained = {key: value for key, value in dict(control.options).items() if key in selected}
            term = strip_diagnostic_metadata(query).strip()
            offset = request_state["offset"] if append else 0
            if not append:
                more_button.set_visibility(False)
            if len(term) < 2:
                control.options = retained
                control.update()
                return
            try:
                page = await api.saved_search_audience_options(
                    audience_kind, query=term, limit=25, offset=offset,
                )
            except asyncio.CancelledError:
                return
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                return
            if revision != request_state["revision"]:
                return
            retained = dict(control.options) if append else {key: value for key, value in dict(control.options).items() if key in set(selected_values())}
            request_state.update(query=term, offset=offset + len(page.get("items", [])))
            more_button.set_visibility(request_state["offset"] < page["total"])
            control.options = {
                **retained,
                **{int(item["id"]): option_label(item) for item in page.get("items", [])},
            }
            control.update()

        async def load_selected(ids: list[int]) -> None:
            if not ids:
                return
            try:
                pages = await asyncio.gather(*(
                    api.saved_search_audience_options(
                        audience_kind, ids=ids[index:index + 50],
                        limit=min(50, len(ids[index:index + 50])), offset=0,
                    )
                    for index in range(0, len(ids), 50)
                ))
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                return
            items = [item for page in pages for item in page.get("items", [])]
            control.options = {
                **dict(control.options),
                **{int(item["id"]): option_label(item) for item in items},
            }
            resolved = [value for value in ids if value in control.options]
            control.value = resolved if control.multiple else (resolved[0] if resolved else None)
            control.update()

        def schedule(event: Any) -> None:
            request_state["revision"] += 1
            more_button.set_visibility(False)
            previous = request_state.get("task")
            if previous is not None and not previous.done():
                previous.cancel()
            async def delayed() -> None:
                await asyncio.sleep(0.2)
                await load_options(str(event.args or ""))
            request_state["task"] = asyncio.create_task(delayed())

        more_button.set_visibility(False)
        more_button.on("click", lambda: load_options(request_state["query"], append=True))
        control.on("input-value", schedule)
        if control.multiple:
            # NiceGUI exposes no separate input-text setter. Clear the QSelect
            # search buffer through its public method, leaving selected IDs intact.
            control.on_value_change(lambda: control.run_method("updateInputValue", ""))
        return load_options, load_selected

    bind_remote_people_select = build_people_select(
        api=api,
        error_message=error_message,
    )

    bind_remote_scheme_select = build_scheme_selector(api)

    ui.colors(
        primary="#268bd2", secondary="#0f749f", accent="#72b8e8",
        positive="#2f9e44", warning="#e9a23b", negative="#dc5050",
    )

    ui.add_head_html(
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="/static/fonts/righteous/righteous.css?v=1" rel="stylesheet">'
        '<link href="/static/fonts/changa/changa.css?v=1" rel="stylesheet">'
        '<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:'
        'opsz,wght,FILL,GRAD@20,300,0,0&display=swap" rel="stylesheet">'
    )
    ui.add_css("""
        :root {
            --erms-ink: #172033; --erms-muted: #687386; --erms-blue: #268bd2;
            --erms-blue-deep: #176da8; --erms-blue-soft: #eaf5fc;
            --erms-bg: #ffffff; --erms-surface: #fff; --erms-border: #e1e6eb;
        }
        body {
            background: var(--erms-bg); color: var(--erms-ink);
            font-family: Changa, ui-sans-serif, -apple-system, BlinkMacSystemFont,
                         "Segoe UI", sans-serif;
            letter-spacing: -.008em;
        }
        html[dir="rtl"] body {
            font-family: Changa, Tahoma, Arial, "Segoe UI", sans-serif;
            letter-spacing: 0; direction: rtl !important;
            text-align: start;
        }
        html[dir="rtl"] .q-layout,
        html[dir="rtl"] .q-page-container,
        html[dir="rtl"] .q-dialog,
        html[dir="rtl"] .q-menu,
        html[dir="rtl"] .q-notifications,
        html[dir="rtl"] [role="listbox"] { direction: rtl; }
        html[dir="rtl"] .q-field__native,
        html[dir="rtl"] .q-field__input,
        html[dir="rtl"] .q-item__label,
        html[dir="rtl"] .q-menu .q-item,
        html[dir="rtl"] textarea,
        html[dir="rtl"] input { text-align: right; }
        html[dir="rtl"] input[type="email"],
        html[dir="rtl"] input[type="url"],
        html[dir="rtl"] input[type="number"],
        html[dir="rtl"] .font-mono,
        html[dir="rtl"] code,
        html[dir="rtl"] pre,
        html[dir="rtl"] [data-bidi="ltr"] {
            direction: ltr; unicode-bidi: isolate; text-align: left;
        }
        html[dir="rtl"] .row { flex-direction: row-reverse; }
        /* Remote selects already inherit RTL. Reversing their internal rows
           again places the recipient chips on the left. */
        html[dir="rtl"] .remote-relationship-select .row { flex-direction: row; }
        /* These native components already inherit RTL. The legacy global row
           reversal flips them twice; Quasar floating labels remain left-anchored.
           Native direction/card/row props do not reset those internal styles. */
        html[dir="rtl"] :is(.wathiq-login-card, .messaging-workspace, .application-settings-page, .application-settings-browser) .row {
            flex-direction: row;
        }
        html[dir="rtl"] :is(.wathiq-login-card, .messaging-workspace, .application-settings-page) .q-field__label {
            left: auto; right: 0; transform-origin: right top; text-align: right;
        }
        html[dir="rtl"] :is(.wathiq-login-card, .messaging-workspace, .application-settings-page) .q-field__append {
            padding-left: 0; padding-right: 12px;
        }
        html[dir="rtl"] :is(.wathiq-login-card, .messaging-workspace, .application-settings-page) .q-field__prepend {
            padding-right: 0; padding-left: 12px;
        }
        /* The native login glyph has no directional variant. Keep the same
           symbol and mirror only this button in RTL. */
        html[dir="rtl"] .wathiq-login-submit .q-icon { transform: scaleX(-1); }
        /* QSelect's default removable chips use physical negative margins.
           Native Select props cannot set the internal remove-icon spacing;
           inspection showed overlap in inherited RTL. Keep a logical gap. */
        .remote-relationship-select .q-chip__icon--remove {
            margin: 0;
        }
        .remote-relationship-select.q-select--multiple .q-chip__content {
            margin-inline-end: 6px;
        }


        /* Transfer dialogs inherit the supported document direction. NiceGUI's
           select/row APIs have no per-control RTL layout switch. Live inspection
           showed the legacy .row reversal reversing that RTL direction twice;
           scope the correction to these dialogs, including Quasar field rows. */
        html[dir="rtl"] .classification-transfer-dialog .row { flex-direction: row; }
        html[dir="rtl"] .classification-transfer-dialog .q-field__label {
            left: auto; right: 0; transform-origin: right top;
        }
        /* The document direction already places the first heading item at the
           reading start.  The legacy global .row reversal would reverse it a
           second time and put the child-aggregation heading on the left. */
        html[dir="rtl"] .aggregation-child-section-heading {
            flex-direction: row;
        }
        html[dir="rtl"] .q-btn__content { flex-direction: row-reverse; }
        /* Detail action groups must wrap from the reading start. NiceGUI Row
           offers wrap/align_items, not direction; grids cannot preserve these
           variable-width, wrapping groups. Live RTL inspection confirmed that
           the legacy .row rule double-reverses the inherited direction. Scope
           this correction to action panels, including their button contents;
           identity-header Back/Favourite/Preview groups remain independent. */
        html[dir="rtl"] :is(.record-command-controls, .identity-command-actions,
            .aggregation-actions-panel, .aggregation-hold-controls) .nicegui-row,
        html[dir="rtl"] .detail-action-row,
        html[dir="rtl"] :is(.record-command-controls, .identity-command-actions,
            .aggregation-actions-panel, .aggregation-hold-controls,
            .hold-command-actions, .detail-action-row) .q-btn__content {
            flex-direction: row;
        }
        /* Quasar's on-left/on-right icon spacing is physical in this build.
           Preserve its 6px separation at the logical end/start after mirroring. */
        html[dir="rtl"] :is(.record-command-controls, .identity-command-actions,
            .aggregation-actions-panel, .aggregation-hold-controls,
            .hold-command-actions, .detail-action-row) .q-btn__content > .q-icon.on-left {
            margin-right: 0; margin-left: 6px;
        }
        html[dir="rtl"] :is(.record-command-controls, .identity-command-actions,
            .aggregation-actions-panel, .aggregation-hold-controls,
            .hold-command-actions, .detail-action-row) .q-btn__content > .q-icon.on-right {
            margin-left: 0; margin-right: 6px;
        }
        html[dir="rtl"] .erms-nav-link { justify-content: flex-start; text-align: right; }
        html[dir="rtl"] .erms-nav-link .q-btn__content {
            direction: rtl; flex-direction: row;
            text-align: right;
        }
        html[dir="rtl"] .erms-nav-link .q-btn__content .block {
            flex: 1 1 auto; text-align: right;
        }
        html[dir="rtl"] .erms-nav-heading { text-align: right; }
        html[dir="rtl"] .erms-breadcrumb-row {
            direction: rtl; flex-direction: row;
        }
        html[dir="rtl"] .erms-nav-link--active::before {
            left: auto !important; right: -8px;
        }
        html[dir="rtl"] .erms-drawer--collapsed .erms-nav-link--active::before {
            right: 0;
        }
        html[dir="rtl"] .erms-drawer-toggle .q-icon,
        html[dir="rtl"] button[aria-label="Previous page"] .q-icon,
        html[dir="rtl"] button[aria-label="Next page"] .q-icon,
        html[dir="rtl"] .q-breadcrumbs__separator .q-icon { transform: scaleX(-1); }
        html[dir="rtl"] .q-notification__message,
        html[dir="rtl"] .q-tooltip { text-align: right; direction: rtl; }
        html[dir="rtl"] .detail-status-notice {
            direction: rtl;
            flex-direction: row !important;
            text-align: right;
        }
        html[dir="rtl"] .detail-status-notice-copy {
            align-items: flex-start;
            text-align: right;
        }
        html[dir="rtl"] .hold-people-row {
            direction: rtl;
            flex-direction: row !important;
            justify-content: flex-start;
        }
        html[dir="rtl"] .hold-person-button .q-btn__content {
            direction: rtl;
            flex-direction: row !important;
        }
        .organization-browser-node-row {
            display: grid !important;
            grid-template-columns: 2rem 1.5rem minmax(0, 1fr) auto;
            grid-template-areas: "expander icon content badge";
            align-items: center;
            column-gap: .25rem;
        }
        .organization-browser-expander { grid-area: expander; }
        .organization-browser-icon { grid-area: icon; }
        .organization-browser-content { grid-area: content; }
        .organization-browser-badge { grid-area: badge; }
        html[dir="rtl"] .organization-browser-node-row {
            direction: rtl;
            grid-template-columns: 2rem 1.5rem minmax(0, 1fr) auto;
            grid-template-areas: "expander icon content badge";
        }
        html[dir="rtl"] .organization-browser-content {
            direction: rtl; text-align: right; align-items: flex-start;
        }
        .organization-browser-summary-field {
            display: grid !important;
            grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
            align-items: center;
            column-gap: .75rem;
        }
        .organization-browser-summary-label { text-align: left; }
        .organization-browser-summary-value { text-align: right; }
        html[dir="rtl"] .organization-browser-summary-field { direction: rtl; }
        html[dir="rtl"] .organization-browser-summary-label { text-align: right; }
        html[dir="rtl"] .organization-browser-summary-value {
            direction: rtl; text-align: left;
        }
        /* As in the classification workspace, NiceGUI Row has no direction
           option. The global RTL row-reverse rule double-reverses these rows;
           keep logical RTL order only within the full-page browser. */
        html[dir="rtl"] .organization-browser-workspace .nicegui-row,
        html[dir="rtl"] .organization-browser-workspace .q-btn__content {
            flex-direction: row !important;
        }
        .translation-card-heading { order: 1; }
        .translation-card-actions { order: 2; }
        html[dir="rtl"] .translation-card-heading { order: 2; }
        html[dir="rtl"] .translation-card-actions { order: 1; }
        html[dir="rtl"] .translation-filter-row {
            direction: rtl !important;
            flex-direction: row !important;
            justify-content: flex-start;
        }
        .classification-tree-row {
            display: grid !important;
            grid-template-columns: 2rem 1.5rem minmax(0, 1fr) auto;
            grid-template-areas: "expander icon content badge";
            align-items: center;
            column-gap: 0.25rem;
        }
        .classification-tree-expander { grid-area: expander; }
        .classification-tree-icon { grid-area: icon; }
        .classification-tree-content { grid-area: content; }
        .classification-tree-badge { grid-area: badge; }
        html[dir="rtl"] .classification-tree-row {
            /* CSS Grid already maps its first column to the inline start
               (the right edge in RTL). Reversing the named areas here would
               mirror the row twice and strand the expander on the left. */
            grid-template-columns: 2rem 1.5rem minmax(0, 1fr) auto;
            grid-template-areas: "expander icon content badge";
        }
        html[dir="rtl"] .classification-tree-content { direction: rtl; text-align: right; }
        html[dir="rtl"] #aggregation-browser-tree .aggregation-browser-tree-row {
            direction: rtl;
            flex-direction: row !important;
            text-align: right;
        }
        .advanced-relationship-tree-node {
            position: relative;
            width: 100%;
        }
        .advanced-relationship-tree-row {
            display: grid !important;
            grid-template-columns: 2rem 1.5rem minmax(0, 1fr) auto;
            grid-template-areas: "expander icon content action";
            align-items: center;
            column-gap: .35rem;
        }
        .advanced-relationship-tree-expander { grid-area: expander; }
        .advanced-relationship-tree-icon { grid-area: icon; }
        .advanced-relationship-tree-content {
            grid-area: content;
            align-items: flex-start;
            text-align: start;
        }
        .advanced-relationship-tree-action { grid-area: action; }
        .advanced-relationship-tree-children {
            margin-inline-start: 1rem;
            padding-inline-start: 1rem;
            border-inline-start: 1px solid #cbd5e1;
        }
        html[dir="rtl"] .advanced-relationship-tree-row {
            direction: rtl;
            grid-template-columns: 2rem 1.5rem minmax(0, 1fr) auto;
            grid-template-areas: "expander icon content action";
        }
        html[dir="rtl"] .advanced-relationship-tree-content {
            direction: rtl;
            align-items: flex-start;
            text-align: right;
        }
        .classification-scheme-selector-panel { border-inline-end: 1px solid #e2e8f0; }
        html[dir="rtl"] .classification-scheme-master-detail {
            direction: rtl; flex-direction: row !important;
        }
        html[dir="rtl"] .classification-scheme-filter-sort {
            direction: rtl; flex-direction: row !important;
        }
        .classification-scheme-selector-heading {
            display: grid !important;
            grid-template-columns: minmax(0, 1fr) auto;
            grid-template-areas: "heading action";
            align-items: center;
        }
        .classification-scheme-selector-heading-label { grid-area: heading; }
        .classification-scheme-selector-heading-action { grid-area: action; }
        html[dir="rtl"] .classification-scheme-selector-heading {
            direction: ltr;
            grid-template-areas: "action heading";
        }
        html[dir="rtl"] .classification-scheme-selector-heading-label {
            direction: rtl; text-align: right;
        }
        .classification-scheme-list-card-row {
            display: grid !important;
            grid-template-columns: 2rem minmax(0, 1fr) auto;
            grid-template-areas: "icon content status";
            align-items: start;
        }
        .classification-scheme-list-card-icon { grid-area: icon; }
        .classification-scheme-list-card-content { grid-area: content; }
        .classification-scheme-list-card-status { grid-area: status; }
        html[dir="rtl"] .classification-scheme-list-card-row {
            direction: ltr;
            grid-template-columns: auto minmax(0, 1fr) 2rem;
            grid-template-areas: "status content icon";
        }
        html[dir="rtl"] .classification-scheme-list-card-content,
        html[dir="rtl"] .classification-scheme-list-card-status {
            direction: rtl; text-align: right; align-items: flex-start;
        }
        .classification-scheme-detail-identity {
            display: grid !important;
            grid-template-columns: 3rem minmax(0, 1fr);
            grid-template-areas: "icon content";
            align-items: start;
        }
        .classification-scheme-detail-identity-icon { grid-area: icon; }
        .classification-scheme-detail-identity-content { grid-area: content; }
        html[dir="rtl"] .classification-scheme-detail-identity {
            direction: ltr;
            grid-template-columns: minmax(0, 1fr) 3rem;
            grid-template-areas: "content icon";
        }
        html[dir="rtl"] .classification-scheme-detail-identity-content {
            direction: rtl; text-align: right;
        }
        /* NiceGUI Row exposes wrapping/alignment, not direction. The global
           RTL .row reversal double-mirrors these naturally RTL containers.
           Keep this fallback scoped to the classification workspace. */
        html[dir="rtl"] .classification-workspace .row,
        html[dir="rtl"] .classification-workspace .q-btn__content {
            flex-direction: row !important;
        }
        /* Material hierarchy glyphs are fixed-direction; mirror toward RTL text. */
        html[dir="rtl"] .classification-directional-icon .q-icon {
            transform: scaleX(-1);
        }
        html[dir="rtl"] .classification-detail-title-status,
        html[dir="rtl"] .classification-detail-actions,
        html[dir="rtl"] .classification-detail-warning,
        html[dir="rtl"] .classification-tree-toolbar,
        html[dir="rtl"] .classification-selected-identity {
            direction: rtl; flex-direction: row !important;
        }
        /* Connection state is presented in the application footer. Keep
           NiceGUI's reconnect machinery, but suppress its duplicate popup. */
        #popup { display: none !important; }
        .erms-header {
            position: fixed; overflow: hidden;
            background: #f4f6f8; color: var(--erms-ink);
            border-bottom: 1px solid var(--erms-border); box-shadow: none !important;
            min-height: 54px; padding: 0 18px;
        }
        .erms-header > .erms-global-search-wrap {
            position: absolute; z-index: 2; left: 50%; transform: translateX(-50%);
            display: flex; align-items: center; gap: 6px; min-width: 0;
        }
        .erms-global-search { width: min(48vw, 680px); min-width: 260px; }
        .erms-global-search .q-field__control { background: white; border-radius: 9px; }
        .global-search-card { border: 1px solid var(--erms-border); border-radius: 10px;
            box-shadow: none; padding: 0; overflow: hidden; }
        .global-search-card-header { background: #f7fbfe; border-bottom: 1px solid var(--erms-border); }
        .global-search-component { border-top: 1px solid #e7edf2; padding: 8px 12px; }
        .compact-result-list { border: 1px solid var(--erms-border); border-radius: 12px; overflow: hidden; }
        .compact-result-item { width: 100%; border-bottom: 1px solid var(--erms-border); background: white; }
        .compact-result-item:last-child { border-bottom: 0; }
        .compact-result-row {
            direction: ltr;
            display: grid !important;
            grid-template-columns: minmax(0, 1fr) auto;
            grid-template-areas: "identity actions";
            align-items: center;
            min-height: 68px; padding: 8px 12px; gap: 10px;
        }
        .compact-result-identity {
            direction: ltr;
            grid-area: identity;
            display: grid !important;
            grid-template-columns: 30px minmax(0, max-content);
            grid-template-areas: "type title";
            justify-content: start;
            align-items: center;
            gap: 10px;
            min-width: 0;
        }
        .compact-result-type {
            grid-area: type;
            width: 30px; height: 34px; flex: 0 0 30px; display: flex; align-items: center;
            justify-content: center; border-radius: 7px; color: var(--erms-blue); background: #eaf5fc;
        }
        .compact-result-title { grid-area: title; min-width: 0; line-height: 1.3; }
        .compact-result-date {
            color: #718096; font-size: .75rem;
            flex: 0 0 92px; width: 92px;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
        .compact-result-indicators { gap: 0; }
        .compact-result-indicator { width: 28px; height: 28px; min-width: 28px !important; padding: 0 !important; }
        .compact-result-actions { grid-area: actions; flex-wrap: nowrap; gap: 0; }
        .compact-result-actions .q-btn { width: 34px; height: 34px; min-width: 34px !important; padding: 0 !important; }
        .compact-result-component-badge {
            min-width: 18px; height: 18px; padding: 0 5px; margin-inline-start: -5px; margin-inline-end: 4px;
            display: inline-flex; align-items: center; justify-content: center;
            color: #9a6700 !important; border-color: #e0ad2f !important; background: #fffdf5 !important;
            font-size: .67rem; font-weight: 700; line-height: 1;
        }
        .compact-result-components {
            padding-block: 0 7px; padding-inline: 52px 12px; background: #f7fbfe;
        }
        .compact-result-component {
            min-height: 52px; padding: 6px 8px; border-inline-start: 2px solid #a9d6ee;
            border-top: 1px solid #e7edf2;
        }
        .compact-result-component:first-child { border-top: 0; }
        .compact-result-snippet { min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
        .compact-result-snippet > .q-row { flex-wrap: nowrap !important; overflow: hidden; white-space: nowrap; }
        .compact-result-snippet .q-label { white-space: pre !important; flex: 0 0 auto; }
        html[dir="rtl"] .compact-result-row {
            direction: ltr;
            grid-template-columns: auto minmax(0, 1fr);
            grid-template-areas: "actions identity";
        }
        html[dir="rtl"] .compact-result-identity {
            direction: ltr;
            grid-template-columns: minmax(0, max-content) 30px;
            grid-template-areas: "title type";
            justify-content: end;
        }
        html[dir="rtl"] .compact-result-title {
            direction: rtl; text-align: right;
            display: grid !important;
            grid-template-columns: minmax(0, max-content);
            justify-content: start;
            justify-items: start;
            align-items: flex-end !important;
        }
        html[dir="rtl"] .compact-result-primary,
        html[dir="rtl"] .compact-result-meta,
        html[dir="rtl"] .compact-result-indicators,
        html[dir="rtl"] .compact-result-actions,
        html[dir="rtl"] .compact-result-component {
            direction: rtl; flex-direction: row !important;
        }
        html[dir="rtl"] .compact-result-primary,
        html[dir="rtl"] .compact-result-meta {
            width: auto !important;
            max-width: 100%;
            justify-self: start !important;
            align-self: end !important;
            justify-content: flex-start !important;
            text-align: right;
        }
        html[dir="rtl"] .compact-result-indicators { order: -1; }
        html[dir="rtl"] .compact-result-date { order: 0; text-align: right; }
        html[dir="rtl"] .compact-result-actions {
            direction: rtl;
            flex-direction: row !important;
        }
        html[dir="rtl"] .compact-result-title .q-label { text-align: right; }
        .global-search-highlight { background: #fff0a8; color: #573f00; border-radius: 3px;
            padding: 0 2px; font-weight: 600; }
        .global-search-json { max-height: 280px; overflow: auto; white-space: pre-wrap;
            overflow-wrap: anywhere; background: #f5f7f9; border: 1px solid #dce3e8;
            border-radius: 7px; padding: 12px; font-size: 12px; min-width: 0; max-width: 100%; }
        .global-search-json .nicegui-markdown,
        .global-search-json .codehilite,
        .global-search-json pre { min-width: 0 !important; max-width: 100% !important;
            white-space: pre-wrap !important; overflow-wrap: anywhere !important;
            word-break: break-word !important; }
        @media (max-width: 760px) {
            .erms-header { flex-wrap: wrap; height: auto; }
            .erms-header > .erms-global-search-wrap {
                position: relative; left: auto; transform: none; order: 3;
                width: 100%;
            }
            .erms-global-search { width: auto; min-width: 0; flex: 1; }
            .global-search-result-action { width: 100%; }
        }
        .wathiq-header-network {
            position: absolute; z-index: 0; inset: 0; width: 100%; height: 100%;
            pointer-events: none; background: transparent;
        }
        .erms-header > :not(.wathiq-header-network):not(.erms-global-search-wrap) {
            position: relative; z-index: 1;
        }
        .erms-footer {
            min-height: 34px; padding: 0 18px;
            background: #f4f6f8; color: #687386;
            border-top: 1px solid var(--erms-border); box-shadow: none !important;
        }
        .erms-footer-credit { font-size: .72rem; letter-spacing: .01em; }
        .erms-footer-database { font-size: .72rem; letter-spacing: .01em; }
        .erms-dashboard-card .erms-shared-control { display: none !important; }
        .erms-shared-control:empty { display: none !important; }
        .erms-brand { gap: 8px; min-width: 0; }
        .erms-brand-mark { width: 28px; height: 33px; flex: 0 0 auto; }
        .erms-brand-name {
            color: #152033; font-family: Righteous, Inter, ui-sans-serif, sans-serif;
            font-size: 1.24rem; font-weight: 400; letter-spacing: .035em; line-height: 1;
        }
        html[dir="rtl"] .erms-brand {
            direction: rtl; flex-direction: row !important;
        }
        html[dir="rtl"] .erms-brand-name,
        html[lang|="ar"] .wathiq-login-word {
            font-family: Changa, Tahoma, Arial, "Segoe UI", sans-serif;
            font-weight: 600; letter-spacing: 0;
        }
        .erms-drawer {
            background: #ffffff; color: #172033;
            border-inline-end: 1px solid var(--erms-border) !important;
            overflow: visible !important;
        }
        .erms-drawer .q-drawer__content { overflow-x: visible !important; }
        .erms-nav-scroll {
            height: 100%; width: 100%;
        }
        .erms-nav-scroll .q-scrollarea__content {
            width: 100%; box-sizing: border-box;
            padding: 0 8px 24px;
        }
        .erms-nav-scroll .q-scrollarea__container {
            overscroll-behavior: contain;
        }
        .erms-drawer-toggle {
            position: absolute !important; inset-inline-end: -13px; top: 18px; z-index: 20;
            width: 27px; height: 34px; min-width: 27px; min-height: 34px;
            padding: 0; border: 1px solid var(--erms-border);
            border-radius: 9px; background: #ffffff !important; color: #52657a !important;
        }
        .erms-drawer-toggle:hover {
            background: var(--erms-blue-soft) !important; color: var(--erms-blue-deep) !important;
        }
        .erms-drawer-toggle .q-icon,
        .erms-profile-action .q-icon {
            font-family: "Material Symbols Outlined" !important;
            font-weight: 300 !important;
            font-variation-settings: "FILL" 0, "wght" 300, "GRAD" 0, "opsz" 20;
        }
        .erms-drawer-toggle .q-icon { font-size: 19px; }
        .erms-profile-action .q-icon { font-size: 21px; }
        .erms-profile-action .q-btn__content { gap: 12px; }
        .erms-profile-action {
            min-height: 38px !important; height: 38px !important;
            margin: 0 !important; padding: 2px 10px !important;
        }
        .erms-profile-actions {
            display: flex !important; flex-direction: column; gap: 0 !important;
            margin: 0 !important; padding: 0 !important;
        }
        .erms-profile-diagnostics { padding: 2px 8px 0; }
        .erms-profile-diagnostics .q-toggle { width: 100%; }
        .erms-profile-menu { direction: inherit; text-align: start; }
        .erms-profile-identity-copy,
        .erms-profile-role-copy { flex: 1 1 auto; min-width: 0; text-align: start; }
        .erms-profile-menu .component-meta-label { width: 100%; text-align: start; }
        html[dir="rtl"] .erms-profile-menu { direction: rtl; text-align: right; }
        html[dir="rtl"] .erms-profile-identity-row,
        html[dir="rtl"] .erms-profile-role-row {
            direction: rtl; flex-direction: row; text-align: right;
        }
        html[dir="rtl"] .erms-profile-identity-copy,
        html[dir="rtl"] .erms-profile-role-copy,
        html[dir="rtl"] .erms-profile-menu .component-meta-label,
        html[dir="rtl"] .erms-profile-menu .q-label { text-align: right; }
        html[dir="rtl"] .erms-profile-email {
            direction: ltr; unicode-bidi: isolate; text-align: right;
        }
        html[dir="rtl"] .erms-profile-action .q-btn__content {
            direction: rtl; flex-direction: row; justify-content: flex-start;
            width: 100%; text-align: right;
        }
        html[dir="rtl"] .erms-profile-action .q-btn__content .block {
            flex: 1 1 auto; text-align: right;
        }
        html[dir="rtl"] .erms-profile-diagnostics .q-toggle {
            direction: rtl; flex-direction: row; justify-content: flex-start;
            text-align: right;
        }
        html[dir="rtl"] .erms-profile-diagnostics .q-toggle__label {
            flex: 1 1 auto; text-align: right;
        }
        .erms-preferences-dialog .erms-preference-select .q-field__native,
        .erms-preferences-dialog .erms-preference-select .q-field__input {
            width: 100%; text-align: start;
        }
        .erms-preferences-dialog .erms-preference-select .q-field__native > span {
            display: block; width: 100%; text-align: start;
        }
        html[dir="rtl"] .erms-preferences-dialog .erms-preference-select .q-field__native,
        html[dir="rtl"] .erms-preferences-dialog .erms-preference-select .q-field__input,
        html[dir="rtl"] .erms-preferences-dialog .erms-preference-select .q-field__native > span {
            direction: rtl; text-align: right !important;
        }
        .wathiq-i18n-inspected {
            outline: 2px solid rgba(38, 139, 210, .72) !important;
            outline-offset: 2px !important;
            border-radius: 3px;
        }
        .wathiq-translation-inspector {
            position: fixed; z-index: 10050; inset-block-end: 48px;
            inset-inline-end: 18px; width: min(390px, calc(100vw - 32px));
            max-height: min(360px, calc(100vh - 96px)); overflow: auto;
            padding: 12px; border: 1px solid #b8d9ed; border-radius: 10px;
            background: rgba(255, 255, 255, .98); color: var(--erms-ink);
            box-shadow: 0 8px 24px rgba(23, 32, 51, .16);
            direction: inherit; text-align: start;
        }
        .wathiq-translation-inspector[hidden] { display: none !important; }
        .wathiq-i18n-panel-header {
            display: flex; align-items: center; gap: 8px; cursor: grab;
            touch-action: none; user-select: none;
        }
        .wathiq-i18n-panel-header.is-dragging { cursor: grabbing; }
        .wathiq-i18n-panel-title { font-size: .82rem; font-weight: 700; flex: 1; }
        .wathiq-i18n-panel-actions { display: flex; gap: 2px; }
        .wathiq-i18n-panel-actions button {
            width: 30px; height: 30px; border: 0; border-radius: 50%;
            background: transparent; color: var(--erms-blue-deep); cursor: pointer;
            font-family: "Material Symbols Outlined"; font-size: 19px;
        }
        .wathiq-i18n-panel-actions button:hover,
        .wathiq-i18n-panel-actions button:focus-visible { background: var(--erms-blue-soft); }
        .wathiq-translation-inspector code {
            display: block; margin-block: 8px; padding: 5px 7px;
            border-radius: 5px; background: #f4f6f8; color: #334155;
            font-size: .72rem; overflow-wrap: anywhere; unicode-bidi: isolate;
        }
        .wathiq-translation-inspector dl { display: flex; gap: 14px; margin: 0 0 8px; }
        .wathiq-translation-inspector dl > div { display: flex; gap: 5px; }
        .wathiq-translation-inspector dt { color: var(--erms-muted); font-size: .7rem; }
        .wathiq-translation-inspector dd { margin: 0; font-size: .7rem; font-weight: 600; }
        .wathiq-i18n-rendered { font-size: .84rem; line-height: 1.5; overflow-wrap: anywhere; }
        .wathiq-i18n-panel-guidance { margin-block-start: 7px; color: var(--erms-muted); font-size: .7rem; line-height: 1.4; }
        .wathiq-login-card {
            position: relative; z-index: 2;
            width: min(680px, calc(100vw - 32px)); max-width: none !important;
            padding: 0 !important; gap: 0 !important; overflow: hidden;
            border: 1px solid var(--erms-border); border-radius: 18px;
        }
        .wathiq-login-network {
            position: fixed; z-index: 1; inset: 0; width: 100vw; height: 100vh;
            pointer-events: none;
            background:
                linear-gradient(135deg, rgba(245, 249, 251, .50), rgba(219, 237, 247, .22)),
                #eaf2f6;
        }
        .wathiq-login-brand-panel {
            width: 270px; min-height: 430px; padding: 34px;
            background: linear-gradient(145deg, #eaf5fc, #f7fbfe);
            border-inline-end: 1px solid #d9eaf4;
        }
        .wathiq-login-mark { width: 35px; height: 42px; }
        .wathiq-login-word {
            color: #152033; font-family: Righteous, Inter, ui-sans-serif, sans-serif;
            font-size: 1.45rem; letter-spacing: .035em;
        }
        .wathiq-login-form { width: 410px; min-height: 430px; padding: 38px; }
        .wathiq-login-error { min-height: 20px; }
        @media (max-width: 640px) {
            .wathiq-login-brand-panel { display: none !important; }
            .wathiq-login-form { width: 100%; min-height: auto; padding: 30px 24px; }
        }
        .erms-nav-heading {
            color: var(--erms-blue-deep); font-size: .67rem; font-weight: 700;
            letter-spacing: .12em; text-transform: uppercase;
        }
        .erms-nav-link { position: relative; border-radius: 8px; color: #1f2937 !important; }
        .erms-nav-link .q-btn__content {
            width: 100%; gap: 12px; flex-wrap: nowrap; justify-content: flex-start;
        }
        .erms-nav-link .q-icon {
            font-family: "Material Symbols Outlined" !important;
            font-size: 21px; font-weight: 300 !important;
            font-variation-settings: "FILL" 0, "wght" 300, "GRAD" 0, "opsz" 20;
        }
        .erms-nav-link .q-btn__content .block {
            min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .erms-nav-link:hover { background: var(--erms-blue-soft) !important; color: var(--erms-blue-deep); }
        .erms-nav-link--active {
            background: #fff4d7 !important; color: #174b72 !important;
        }
        .erms-nav-link--active::before {
            content: ""; position: absolute; inset-inline-start: -8px; top: 50%; transform: translateY(-50%);
            width: 4px; height: 24px; border-radius: 0 4px 4px 0; background: var(--erms-blue);
        }
        .erms-drawer--collapsed .erms-nav-link .q-btn__content {
            justify-content: center;
        }
        .erms-drawer--collapsed .erms-nav-link--active::before { inset-inline-start: 0; }
        .erms-page-title-icon {
            color: var(--erms-blue-deep);
            font-family: "Material Symbols Outlined" !important;
            font-size: 27px; font-weight: 300 !important;
            font-variation-settings: "FILL" 0, "wght" 300, "GRAD" 0, "opsz" 24;
        }
        html[dir="rtl"] .erms-page-title-row {
            direction: rtl; flex-direction: row !important;
        }
        .erms-content { max-width: 1540px; margin: 0 auto; }
        .erms-card {
            background: var(--erms-surface); border: 1px solid var(--erms-border);
            border-radius: 14px; box-shadow: none;
        }
        .governance-overview-grid {
            display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(280px, .75fr);
            width: 100%; gap: 14px; align-items: start;
        }
        .governance-purpose-card,
        .governance-status-card {
            width: 100%; min-height: 0; padding: 18px 20px;
            border: 1px solid var(--erms-border); border-radius: 14px;
        }
        .governance-purpose-card { background: #ffffff; }
        .governance-purpose-icon,
        .governance-metric-icon {
            display: flex; align-items: center; justify-content: center;
            flex: 0 0 auto; color: var(--erms-blue); background: var(--erms-blue-soft);
            border-radius: 10px;
        }
        .governance-purpose-icon { width: 38px; height: 38px; }
        .governance-requirements-grid {
            display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
            width: 100%; gap: 7px 18px; margin-top: 8px;
        }
        .governance-status-card { color: #3f4b5d; }
        .governance-status-critical { background: #fff4f2; border-color: #f1c7c1; color: #8f312d; }
        .governance-status-warning { background: #fff9e9; border-color: #efd99b; color: #765718; }
        .governance-status-healthy { background: #f0faf4; border-color: #bce1c9; color: #23633a; }
        .governance-status-icon {
            display: flex; align-items: center; justify-content: center;
            width: 32px; height: 32px; flex: 0 0 32px; border-radius: 999px;
            color: currentColor; background: rgba(255, 255, 255, .7);
        }
        .governance-metrics-row { width: 100%; gap: 10px; flex-wrap: wrap; }
        .governance-metric-card {
            width: 205px; min-height: 72px; padding: 12px 14px;
            display: flex !important; flex-direction: row !important;
            align-items: center; gap: 12px; border: 1px solid var(--erms-border);
            background: #ffffff; border-radius: 12px;
        }
        .governance-metric-icon { width: 32px; height: 32px; }
        .governance-empty-state {
            width: 100%; min-height: 126px; padding: 18px;
            align-items: center; justify-content: center; gap: 6px;
            border: 1px dashed #ccd8e4; background: #fbfcfd; border-radius: 12px;
        }
        .governance-empty-inline {
            width: 100%; padding: 18px; text-align: center; color: #718096;
            border: 1px dashed #ccd8e4; background: #fbfcfd; border-radius: 12px;
            font-size: .8rem;
        }
        .governance-table .q-table thead tr { background: #eef7fd; }
        .governance-table .q-table th { color: #35546f; text-align: left; }
        .governance-table .q-table td { text-align: left; }
        .governance-table .q-table th:last-child,
        .governance-table .q-table td:last-child { text-align: right; white-space: nowrap; }
        .hold-selection-table .q-table th:first-child,
        .hold-selection-table .q-table td:first-child {
            width: 52px !important;
            min-width: 52px !important;
            max-width: 52px !important;
            padding-inline-start: 10px !important;
            padding-inline-end: 10px !important;
            text-align: center !important;
        }
        .hold-candidate-selection-table .q-table th:first-child,
        .hold-candidate-selection-table .q-table td:first-child {
            width: 32px !important;
            min-width: 32px !important;
            max-width: 32px !important;
            padding-inline-start: 0 !important;
            padding-inline-end: 0 !important;
        }
        .security-operations-table .q-table th:last-child,
        .security-operations-table .q-table td:last-child { text-align: left; white-space: normal; }
        .login-sessions-table .q-table th {
            vertical-align: middle;
            white-space: nowrap;
        }
        .login-sessions-table .q-table th > * {
            flex-wrap: nowrap;
        }
        .login-sessions-table .q-table__sort-icon {
            flex: 0 0 auto;
        }
        .login-sessions-table .q-table { table-layout: fixed; width: 100%; }
        .login-sessions-table .q-table th,
        .login-sessions-table .q-table td { overflow: hidden; }
        .login-session-client-value {
            display: block; min-width: 0; max-width: 100%;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .login-session-user-value { min-width: 0; max-width: 100%; }
        .login-session-user-name { white-space: normal; overflow-wrap: anywhere; line-height: 1.3; }
        .login-session-user-email {
            display: block; min-width: 0; max-width: 100%;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .login-session-action-button {
            width: 36px; height: 34px; min-width: 36px !important; padding: 0 !important;
        }
        .login-session-action-button .q-icon { font-size: 20px !important; }
        .login-session-card-grid {
            display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px;
        }
        .login-session-card {
            width: 100%; min-width: 0; padding: 14px; gap: 13px;
            border: 1px solid var(--erms-border); background: var(--erms-surface);
        }
        .governance-card-list { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; }
        .governance-list-card {
            width: 100%; min-width: 0; padding: 14px; gap: 12px;
            border: 1px solid var(--erms-border); background: var(--erms-surface);
        }
        .governance-card-icon {
            width: 38px; height: 38px; flex: 0 0 38px;
            display: flex; align-items: center; justify-content: center;
            border: 1px solid #add4ec; border-radius: 9px;
            color: var(--erms-blue); background: transparent;
        }
        .governance-list-facts {
            display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
            width: 100%; min-width: 0;
            gap: 10px 18px; padding-top: 10px; border-top: 1px solid #e7ebef;
        }
        .hold-list-card--effective { border-inline-start: 4px solid #fbbf24; }
        .hold-list-facts { grid-template-columns: repeat(5, minmax(0, 1fr)); }
        .user-role-assignment-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .user-role-assignment-card {
            padding: 9px 11px; gap: 8px; cursor: pointer; transition: all .16s ease;
        }
        .user-role-assignment-card:hover { border-color: #93b4e8; background: #f8fcff; }
        .user-role-assignment-card .governance-card-icon {
            width: 32px; height: 32px; flex-basis: 32px;
        }
        .user-role-assignment-card .user-role-assignment-facts {
            gap: 6px 16px; padding-top: 7px;
        }
        .governance-custody-assignment-card { padding: 11px 13px; gap: 9px; }
        .governance-custody-assignment-card .governance-list-facts {
            gap: 7px 16px; padding-top: 8px;
        }
        .security-event-facts { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .role-privilege-groups {
            display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px;
        }
        .role-privilege-group {
            min-width: 0; overflow: hidden; border: 1px solid var(--erms-border);
            border-radius: 9px; background: var(--erms-surface);
        }
        .role-privilege-group-header {
            display: grid; grid-template-columns: auto minmax(0, 1fr) auto;
            align-items: center; min-height: 42px; padding: 9px 11px; background: #eef7fd;
            border-bottom: 1px solid #dceaf3;
        }
        .role-privilege-group-title { min-width: 0; text-align: start; }
        .role-privilege-group-count { justify-self: end; }
        .role-privilege-list {
            display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0 14px; padding: 4px 11px 8px;
        }
        .role-privilege-item {
            display: grid; grid-template-columns: auto minmax(0, 1fr);
            align-items: start; min-width: 0; padding: 7px 2px;
            border-bottom: 1px solid #edf1f4;
        }
        .role-privilege-copy { min-width: 0; text-align: start; }
        html[dir="rtl"] .role-privilege-group-header,
        html[dir="rtl"] .role-privilege-item { direction: rtl; }
        html[dir="rtl"] .role-privilege-group-title,
        html[dir="rtl"] .role-privilege-copy { text-align: right; }
        html[dir="rtl"] .role-privilege-group-count { justify-self: left; }
        @media (max-width: 820px) {
            .role-privilege-groups { grid-template-columns: minmax(0, 1fr); }
        }
        @media (max-width: 800px) {
            .governance-list-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        .erms-profiles-table .q-table { table-layout: fixed; width: 100%; }
        .erms-profiles-table .q-table th,
        .erms-profiles-table .q-table td { overflow: hidden; }
        .erms-profiles-table .profile-description-cell {
            white-space: normal; overflow-wrap: anywhere; line-height: 1.35;
        }
        @media (max-width: 900px) {
            .governance-overview-grid { grid-template-columns: 1fr; }
            .governance-purpose-card, .governance-status-card { min-height: auto; }
        }
        @media (max-width: 560px) {
            .governance-requirements-grid { grid-template-columns: 1fr; }
            .governance-metric-card { width: 100%; }
        }
        .q-card { border-radius: 14px; }
        .erms-content .q-card { box-shadow: none !important; }
        .q-btn { border-radius: 9px; }
        .q-field--outlined .q-field__control { border-radius: 10px; }
        .q-table__container { border-radius: 12px; overflow: hidden; }
        .erms-page-table {
            width: calc(100% - 40px) !important;
            margin: 8px 20px 20px;
        }
        .erms-page-table .q-table thead tr { background: #eef7fd; }
        .erms-page-table .q-table th {
            color: #35546f; font-size: .74rem; font-weight: 700;
            letter-spacing: .045em;
        }
        .erms-page-table .q-table tbody td { color: #334155; font-size: .875rem; }
        .erms-page-table .q-table tbody tr:hover { background: #f7fbfe; }
        .aggregation-records-table .q-table { table-layout: fixed; width: 100%; }
        .aggregation-records-table .q-table th,
        .aggregation-records-table .q-table td { overflow: hidden; }
        .aggregation-record-cell-value {
            display: block; min-width: 0; overflow: hidden;
            text-overflow: ellipsis; white-space: nowrap;
        }
        .erms-results-divider { width: calc(100% - 40px) !important; margin: 8px 20px 0; }
        .q-table thead tr { background: #f7f8f8; }
        .q-table th { color: #657184; font-size: .72rem; font-weight: 700; letter-spacing: .035em; }
        .detail-surface {
            background: var(--erms-surface); border: 1px solid var(--erms-border);
            border-radius: 14px;
        }
        .detail-field {
            min-width: 0; padding: 10px 0; border-bottom: 1px solid #eef0f2;
        }
        .detail-field-label {
            color: #8791a1; font-size: .67rem; font-weight: 700;
            letter-spacing: .065em; text-transform: uppercase;
        }
        .detail-field-value { color: #263244; font-size: .9rem; font-weight: 600; line-height: 1.4; }
        .retention-card {
            background: linear-gradient(135deg, #f5fbff 0%, #eaf5fc 100%);
            border: 1px solid #d5eaf8; border-radius: 14px;
        }
        .retention-line { position: relative; width: 22px; align-self: stretch; flex: 0 0 22px; }
        .retention-line::before {
            content: ""; position: absolute; top: 14px; bottom: -22px; inset-inline-start: 10px;
            width: 2px; background: #a9d6f3;
        }
        .retention-stage:last-child .retention-line::before { display: none; }
        .retention-dot {
            position: relative; z-index: 1; width: 11px; height: 11px; margin: 8px 0 0 5px;
            border-radius: 999px; background: var(--erms-blue); box-shadow: 0 0 0 4px #eaf5fc;
        }
        .retention-stage-label { color: #607086; font-size: .75rem; line-height: 1.2; }
        .retention-stage-value { color: #172033; font-size: 1.15rem; font-weight: 750; line-height: 1.25; }
        .aggregation-command-layout {
            display: grid !important; grid-template-columns: minmax(0, 1.55fr) minmax(330px, .8fr);
            align-items: start !important; gap: 12px !important;
        }
        .aggregation-command-summary { grid-column: 1; grid-row: 1; min-width: 0 !important; }
        .aggregation-command-side { display: contents; }
        .aggregation-command-controls {
            grid-column: 2; grid-row: 1; min-width: 0; width: 100%; gap: 12px;
        }
        .aggregation-hold-controls, .aggregation-actions-panel { min-width: 0; width: 100%; }
        .aggregation-actions-panel .q-btn { justify-content: flex-start; }
        .aggregation-action-group-label {
            color: #64748b; font-size: .68rem; font-weight: 750;
            letter-spacing: .07em; text-transform: uppercase;
        }
        .aggregation-retention-compact {
            grid-column: 1 / -1; grid-row: 2; min-width: 0; width: 100%; margin-top: 4px;
        }
        .aggregation-panel-heading {
            margin: -16px -16px 0; padding: 11px 13px; border-bottom: 1px solid #e5ebf1;
            color: #172033; font-size: .8rem; font-weight: 750;
        }
        .aggregation-command-summary > .aggregation-panel-heading { margin: -20px -20px 0; }
        .aggregation-overview-actions { justify-content: flex-start !important; gap: 6px; }
        .aggregation-overview-actions .q-btn {
            border: 1px solid #cbd9e5; border-radius: 8px; background: #fff;
            color: #25445d; padding: 0 9px;
        }
        .aggregation-overview-actions .q-btn.text-negative {
            border-color: #e9a8ad; background: #fff7f7; color: #bd3341 !important;
        }
        .aggregation-child-preview-grid {
            display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px;
            max-height: 146px; overflow-y: auto; padding-inline-end: 3px;
        }
        .aggregation-child-preview {
            min-width: 0; min-height: 64px; border: 1px solid #e2e8f0;
            border-radius: 10px; background: #fff; padding: 8px;
        }
        .aggregation-child-preview:hover { border-color: #93b4e8; background: #f8fcff; }
        .aggregation-retention-stages { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 18px; }
        .aggregation-retention-stage {
            position: relative; min-width: 0; padding: 8px 10px;
            padding-inline-start: 30px;
            border-radius: 9px; background: rgba(255,255,255,.68);
        }
        .aggregation-retention-stage::before {
            content: ""; position: absolute; inset-inline-start: 11px; top: 13px; width: 9px; height: 9px;
            border-radius: 999px; background: var(--erms-blue); box-shadow: 0 0 0 4px #dff1fc;
        }
        .aggregation-retention-stage:not(:last-child)::after {
            content: "→"; position: absolute; inset-inline-end: -15px; top: 12px;
            color: #6f98b4; font-weight: 800;
        }
        html[dir="rtl"] .aggregation-retention-stage:not(:last-child)::after {
            content: "←";
        }
        html[dir="rtl"] .aggregation-retention-stage,
        html[dir="rtl"] .aggregation-retention-chip { text-align: right; }
        .aggregation-retention-footer {
            display: flex; align-items: center; gap: 8px; min-width: 0;
            padding-top: 9px; border-top: 1px solid #d5eaf8;
        }
        .aggregation-retention-chip {
            min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis;
            white-space: nowrap; border-radius: 8px; background: rgba(255,255,255,.62);
            padding: 7px 9px; color: #536b7f; font-size: .75rem;
        }
        .record-command-layout {
            display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(330px, .72fr);
            align-items: start; gap: 12px;
        }
        .record-command-overview { grid-column: 1; grid-row: 1; min-width: 0; }
        .record-command-controls { grid-column: 2; grid-row: 1; min-width: 0; width: 100%; gap: 12px; }
        .record-command-controls .q-btn { justify-content: flex-start; }
        .record-action-group-label {
            color: #64748b; font-size: .68rem; font-weight: 750;
            letter-spacing: .07em; text-transform: uppercase;
        }
        .identity-command-layout {
            display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(330px, .72fr);
            align-items: start; gap: 12px;
        }
        .identity-command-metadata { grid-column: 1; grid-row: 1; min-width: 0; }
        .identity-command-actions { grid-column: 2; grid-row: 1; min-width: 0; width: 100%; }
        .identity-command-actions .q-btn { justify-content: flex-start; }
        .identity-detail-fact { min-width: 0; text-align: start; align-items: flex-start; }
        html[dir="rtl"] .identity-detail-facts { direction: rtl; }
        html[dir="rtl"] .identity-detail-fact {
            direction: rtl; text-align: right; align-items: flex-start;
        }
        html[dir="rtl"] .identity-detail-fact > * { width: 100%; text-align: right; }
        .hold-command-layout {
            display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(300px, .65fr);
            align-items: start; gap: 12px;
        }
        .hold-command-overview { grid-column: 1; grid-row: 1; min-width: 0; }
        .hold-command-actions { grid-column: 2; grid-row: 1; min-width: 0; width: 100%; }
        .hold-action-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
        .hold-action-row .q-btn { width: auto; }
        .hold-summary-facts {
            display: grid; grid-template-columns: minmax(150px, .8fr) minmax(150px, .8fr) minmax(240px, 1.4fr);
            gap: 16px; padding-top: 12px; border-top: 1px solid #e2e8f0;
        }
        .hold-people-block { padding-top: 2px; }
        .hold-held-item-filter-primary {
            display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px;
        }
        .hold-held-item-filter-secondary {
            display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px;
        }
        @media (max-width: 980px) {
            .aggregation-command-layout { display: flex !important; flex-direction: column; }
            .aggregation-command-side { display: contents; }
            .aggregation-command-summary, .aggregation-command-controls,
            .aggregation-retention-compact,
            .aggregation-hold-controls { min-width: 100%; }
            .aggregation-child-preview-grid { grid-template-columns: repeat(2, minmax(0,1fr)); }
            .record-command-layout { display: flex; flex-direction: column; }
            .record-command-overview, .record-command-controls { min-width: 100%; width: 100%; }
            .identity-command-layout { display: flex; flex-direction: column; }
            .identity-command-metadata, .identity-command-actions { min-width: 100%; width: 100%; }
            .hold-command-layout { display: flex; flex-direction: column; }
            .hold-command-overview, .hold-command-actions { min-width: 100%; width: 100%; }
            .hold-summary-facts { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .hold-held-item-filter-primary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 600px) {
            .hold-summary-facts { grid-template-columns: minmax(0, 1fr); }
            .hold-held-item-filter-primary,
            .hold-held-item-filter-secondary { grid-template-columns: minmax(0, 1fr); }
        }
        .relationship-select .q-field__control { min-height: 58px; border-radius: 10px; }
        .relationship-option { min-width: 360px; }
        .relationship-option:hover { background: #f3f7ff; }
        .relationship-select .q-field__native { font-weight: 600; color: #16324f; }
        .person-select .q-field__control { min-height: 62px; border-radius: 10px; }
        .person-select .q-field__native { min-width: 0; gap: 5px; }
        .person-select-option:hover { background: #f3f8fc; }
        .person-select-value { min-width: 0; max-width: calc(100% - 8px); padding: 3px 0; }
        .person-select-value .min-width-0 { min-width: 0; }
        .person-select-initials {
            display: inline-flex; align-items: center; justify-content: center; flex: 0 0 32px;
            width: 32px; height: 32px; border-radius: 999px; background: #e3f2fd;
            color: var(--q-primary); font-size: .75rem; font-weight: 700;
        }
        .person-select-chip { max-width: 240px; background: #f7fbfe !important; }
        .person-select-chip .q-chip__content { min-width: 0; flex-wrap: nowrap; }
        .relationship-chip-select .q-field__native { min-width: 0; }
        .relationship-value-chip { max-width: 100%; background: #f7fbfe !important; }
        .relationship-value-chip .q-chip__content { min-width: 0; flex-wrap: nowrap; gap: 6px; }
        .relationship-option-card {
            min-width: 340px; border: 1px solid #e2e8f0; border-radius: 10px;
            background: #fff; transition: border-color .15s ease, background .15s ease;
        }
        .relationship-option-card:hover { border-color: #93b4e8; background: #f8fcff; }
        .relationship-cell-name { color: #172033; }
        .recent-card { min-height: 62px; border: 1px solid #e2e8f0; border-radius: 10px; transition: all .16s ease; }
        .recent-card:hover { border-color: #93b4e8; background: #f8fcff; }
        .breadcrumb-link { color: #52657a; }
        .timestamp-date { font-size: .84rem; font-weight: 600; color: #334155; line-height: 1.15; }
        .timestamp-time { font-size: .72rem; color: #94a3b8; line-height: 1.2; }
        .component-grid { display: grid; grid-template-columns: 1fr; gap: 12px; padding-inline-end: 8px; }
        .component-list { container-type: inline-size; overflow: visible; padding: 2px 0; }
        @container (min-width: 760px) { .component-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
        .component-card { border: 1px solid #e2e8f0; border-radius: 12px; box-shadow: none; overflow: hidden; }
        .component-card:hover { border-color: #a8bdd8; background: #fafdff; }
        .component-filename {
            display: -webkit-box; width: 100%; min-width: 0; min-height: 2.5em;
            overflow: hidden; overflow-wrap: anywhere; line-height: 1.25;
            -webkit-box-orient: vertical; -webkit-line-clamp: 2;
        }
        .component-mime-type {
            display: block; width: 100%; min-width: 0; overflow: hidden;
            text-overflow: ellipsis; white-space: nowrap;
        }
        .component-card-actions {
            min-height: 34px; margin-top: -5px; padding-inline-start: 56px;
        }
        .detail-linked-entity { width: 100%; text-align: start; }
        .detail-linked-entity .q-btn__content {
            width: 100%; justify-content: flex-start; text-align: start; white-space: normal;
        }
        .detail-linked-entity-content {
            width: 100%; min-width: 0; align-items: flex-start; gap: 1px;
            text-align: start;
        }
        .detail-linked-entity-title {
            width: 100%; color: var(--q-primary); font-size: .9rem;
            font-weight: 600; line-height: 1.4; overflow-wrap: anywhere;
        }
        .detail-linked-entity-identifier {
            width: 100%; color: #8791a1; font-size: .72rem;
            font-weight: 500; line-height: 1.3;
        }
        .component-meta-label { color: #94a3b8; font-size: .68rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; }
        .component-meta-value { color: #475569; font-size: .8rem; line-height: 1.3; }
        .component-switcher-bar {
            min-height: 56px; padding: 7px 16px; background: #fff;
            border-bottom: 1px solid #dfe7ef;
        }
        .component-switcher-summary {
            flex: 0 0 auto; color: #64748b; font-size: .76rem;
            font-weight: 600; white-space: nowrap;
        }
        .component-switcher-divider {
            width: 1px; height: 30px; background: #d7e0e9; flex: 0 0 1px;
        }
        .component-switcher-file {
            min-width: 0; flex: 1 1 auto; overflow: hidden;
        }
        .component-switcher-filename {
            min-width: 0; max-width: 440px; overflow: hidden; text-overflow: ellipsis;
            color: #1e293b; font-size: .82rem; font-weight: 600; white-space: nowrap;
        }
        .component-switcher-position {
            flex: 0 0 auto; color: #8291a3; font-size: .72rem; white-space: nowrap;
        }
        .component-switcher-scroll {
            flex: 0 1 auto; max-width: 48vw; min-width: 0; overflow-x: auto;
            scrollbar-width: thin; padding: 2px 3px;
        }
        .component-switcher-button {
            flex: 0 0 30px; width: 30px !important; height: 30px !important;
            min-width: 30px !important; min-height: 30px !important; padding: 0 !important;
            border: 0 !important; border-radius: 999px !important;
            background: #eef2f6 !important; color: #475569 !important;
            box-shadow: none !important; font-size: .74rem; font-weight: 600;
            letter-spacing: 0; text-transform: none;
        }
        .component-switcher-button:hover {
            background: #dfeaf4 !important; color: #1e6091 !important;
        }
        .component-switcher-button--active {
            background: #2f86c9 !important; color: #fff !important;
            box-shadow: 0 1px 3px rgba(30, 96, 145, .24) !important;
        }
        .component-switcher-button .q-btn__content {
            width: 100%; min-width: 0; flex-wrap: nowrap; justify-content: center;
            overflow: hidden;
        }
        .component-viewer-toolbar { min-height: 52px; }
        @media (max-width: 700px) {
            .component-switcher-button { width: 30px; }
            .component-switcher-bar { padding-inline: 10px; gap: 8px !important; }
            .component-switcher-summary { display: none; }
            .component-switcher-divider { display: none; }
            .component-switcher-filename { max-width: 42vw; }
            .component-switcher-position { display: none; }
            .component-switcher-scroll { max-width: 44vw; }
        }
        .record-uploader { border: 2px dashed #a9bfd9; border-radius: 12px; box-shadow: none; background: #fbfdff; }
        .record-uploader:hover { border-color: #5b8ec9; background: #f7fbff; }
        .record-uploader .q-uploader__header { background: transparent; color: inherit; }
        .record-uploader .q-uploader__list { min-height: 58px; padding: 0; }
        .record-uploader .upload-header {
            direction: ltr;
            flex-direction: row !important;
        }
        .record-uploader .upload-header > .column {
            align-items: center;
            text-align: center;
        }
        .upload-empty { display: flex; align-items: center; justify-content: center; min-height: 58px; color: #94a3b8; font-size: .78rem; }
        .upload-queue { max-height: 144px; overflow-y: auto; background: #f8fafc; }
        .membership-dialog {
            width: min(680px, calc(100vw - 32px)) !important;
            max-width: none !important;
            max-height: min(700px, calc(100vh - 32px));
            overflow: hidden;
        }
        .membership-table { height: min(330px, calc(100vh - 370px)); min-height: 250px; }
        .membership-table .q-table__middle { overflow-y: auto; }
        .membership-table thead tr th { position: sticky; top: 0; z-index: 1; background: white; }
        .audit-event { border-inline-start: 3px solid #bfdbfe; box-shadow: none; }
        .audit-event:hover { border-inline-start-color: #3b82f6; background: #f8fbff; }
        .audit-value { max-width: 360px; overflow-wrap: anywhere; white-space: pre-wrap; }
        .q-tooltip {
            max-width: min(360px, calc(100vw - 32px)) !important;
            white-space: normal !important;
            overflow-wrap: anywhere;
            line-height: 1.35;
            text-align: left;
        }
        .dashboard-overview-primary {
            display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px;
        }
        .dashboard-overview-primary-card {
            width: 100%; min-width: 0; padding: 10px 12px; gap: 10px;
            border: 1px solid #dce5eb; box-shadow: none; transition: all .16s ease;
        }
        .dashboard-overview-primary-card:hover,
        .dashboard-overview-admin-item:hover { border-color: #93b4e8; background: #f8fcff; }
        html[dir="rtl"] .dashboard-overview-heading,
        html[dir="rtl"] .dashboard-overview-card-heading {
            direction: rtl; flex-direction: row !important;
        }
        html[dir="rtl"] .dashboard-overview-card-heading .column { text-align: right; }
        .dashboard-overview-mediums {
            display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px;
            padding-top: 7px; margin-top: 7px; border-top: 1px solid #edf2f5;
        }
        .dashboard-overview-medium {
            display: inline-flex; align-items: center; gap: 4px; min-width: 0;
            color: #64748b; font-size: .7rem; white-space: nowrap;
        }
        .dashboard-overview-separator {
            color: #cbd5e1; font-size: .8rem; line-height: 1; user-select: none;
        }
        .dashboard-overview-signal {
            display: inline-flex; align-items: center; gap: 4px; white-space: nowrap;
            color: #475569; font-size: .72rem;
        }
        .dashboard-overview-icon {
            width: 34px; height: 34px; flex: 0 0 34px; display: flex;
            align-items: center; justify-content: center; border: 1px solid #add4ec;
            border-radius: 8px; color: var(--erms-blue); background: transparent;
        }
        .dashboard-overview-admin {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            width: 100%; overflow: hidden; border: 1px solid #dce5eb;
            border-radius: 10px; background: white;
        }
        .dashboard-overview-admin-item {
            min-width: 0; min-height: 46px; padding: 9px 10px; display: flex;
            align-items: center; gap: 7px; border-inline-end: 1px solid #e2e8ed;
            transition: all .16s ease; cursor: pointer;
        }
        .dashboard-overview-admin-item:last-child { border-inline-end: 0; }
        @media (max-width: 800px) {
            .dashboard-overview-admin { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .dashboard-overview-admin-item { border-bottom: 1px solid #e2e8ed; }
        }
        @media (max-width: 520px) {
            .dashboard-overview-primary { grid-template-columns: minmax(0, 1fr); }
        }
        .dashboard-attention-chart {
            width: 50%; margin-inline: auto; padding: 13px 14px 12px;
            border: 1px solid #dce5eb;
            border-radius: 10px; background: white;
        }
        .dashboard-chart-legend {
            display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px;
            color: #64748b; font-size: .7rem;
        }
        .dashboard-chart-legend-item {
            display: inline-flex; align-items: center; gap: 5px; white-space: nowrap;
        }
        .dashboard-chart-swatch {
            width: 9px; height: 9px; flex: 0 0 9px; border-radius: 2px;
        }
        .dashboard-attention-plot {
            display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
            align-items: end; gap: 36px; min-height: 156px; margin-top: 12px;
            padding: 12px 32px 28px 54px; border-inline-start: 1px solid #cbd5e1;
            border-bottom: 1px solid #cbd5e1;
            background: repeating-linear-gradient(
                to top, transparent 0, transparent 38px, #edf2f5 39px
            );
        }
        .dashboard-attention-group {
            display: flex; align-items: end; justify-content: center; gap: 10px;
            height: 126px; position: relative;
        }
        .dashboard-attention-bar {
            position: relative; width: min(44px, 38%);
            border-radius: 4px 4px 0 0;
        }
        .dashboard-attention-bar-value {
            position: absolute; left: 50%; top: -20px; transform: translateX(-50%);
            color: #334155; font-size: .72rem; font-weight: 600;
            font-variant-numeric: tabular-nums;
        }
        .dashboard-attention-group-label {
            position: absolute; left: 0; right: 0; bottom: -24px; text-align: center;
            color: #64748b; font-size: .72rem;
        }
        .dashboard-attention-axis-label {
            position: absolute; left: -47px; top: 50%; transform: rotate(-90deg);
            color: #94a3b8; font-size: .64rem; white-space: nowrap;
        }
        .dashboard-holdings-list {
            width: 100%; overflow: hidden; border: 1px solid #dce5eb;
            border-radius: 10px; background: white;
        }
        .dashboard-holdings-chart {
            width: 50%; margin-inline: auto; padding: 13px 14px 12px;
            border: 1px solid #dce5eb;
            border-radius: 10px; background: white;
        }
        .dashboard-holdings-chart-rows { display: grid; gap: 10px; margin-top: 13px; }
        .dashboard-holdings-chart-row {
            display: grid; grid-template-columns: minmax(110px, 180px) minmax(100px, 1fr) 46px;
            align-items: center; gap: 10px; min-width: 0;
        }
        .dashboard-holdings-chart-name {
            min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
            color: #475569; font-size: .75rem; font-weight: 600;
        }
        .dashboard-holdings-chart-track {
            display: flex; height: 18px; overflow: hidden; border-radius: 4px;
            background: #edf2f5;
        }
        .dashboard-holdings-chart-segment { height: 100%; min-width: 0; }
        .dashboard-holdings-chart-total {
            text-align: right; color: #334155; font-size: .75rem; font-weight: 600;
            font-variant-numeric: tabular-nums;
        }
        .dashboard-storage-chart {
            width: 50%; margin-inline: auto; padding: 13px 14px 12px;
            border: 1px solid #dce5eb; border-radius: 10px; background: white;
        }
        .dashboard-storage-chart-rows { display: grid; gap: 10px; margin-top: 13px; }
        .dashboard-storage-chart-row {
            display: grid; grid-template-columns: minmax(105px, 145px) minmax(80px, 1fr) 78px;
            align-items: center; gap: 9px; min-width: 0;
        }
        .dashboard-storage-chart-name {
            min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
            color: #475569; font-size: .75rem; font-weight: 600;
        }
        .dashboard-storage-chart-track {
            height: 15px; overflow: hidden; border-radius: 4px; background: #edf2f5;
        }
        .dashboard-storage-chart-bar { height: 100%; background: #4d82c4; }
        .dashboard-storage-chart-value {
            text-align: right; color: #334155; font-size: .72rem; font-weight: 600;
            font-variant-numeric: tabular-nums;
        }
        .dashboard-storage-chart-share {
            color: #94a3b8; font-size: .62rem; font-weight: 500;
        }
        .dashboard-storage-other {
            margin-top: 3px; padding-top: 10px; border-top: 1px solid #e2e8ed;
        }
        .dashboard-storage-other-summary { color: #94a3b8; font-size: .68rem; }
        .dashboard-holdings-row {
            display: grid;
            grid-template-columns: minmax(220px, 1fr) 190px 250px 165px;
            align-items: center; gap: 12px; min-width: 0; padding: 10px 12px;
            border-bottom: 1px solid #e2e8ed; cursor: pointer; transition: all .16s ease;
        }
        .dashboard-holdings-row:last-child { border-bottom: 0; }
        .dashboard-holdings-row:hover { background: #f8fcff; }
        .dashboard-holdings-identity {
            display: flex; align-items: center; gap: 10px; min-width: 0;
        }
        .dashboard-holdings-metric {
            display: flex; align-items: flex-start; justify-content: flex-start;
            gap: 7px; min-width: 0; color: #64748b;
        }
        .dashboard-holdings-metric-detail {
            color: #94a3b8; font-size: .68rem; line-height: 1.35; white-space: nowrap;
        }
        .dashboard-holdings-mediums {
            display: flex; flex-wrap: wrap; align-items: center; gap: 3px 8px;
        }
        .dashboard-holdings-medium {
            color: #94a3b8; font-size: .64rem; line-height: 1.3;
        }
        .dashboard-holdings-peer-stat {
            display: inline-flex; align-items: center; gap: 5px; color: #64748b;
            min-height: 18px; font-size: .75rem; font-weight: 500;
            line-height: 18px; white-space: nowrap;
        }
        .dashboard-holdings-peer-stat .q-icon {
            display: inline-flex; align-items: center; justify-content: center;
            width: 14px; height: 14px; min-width: 14px; line-height: 14px;
            font-size: 14px !important; flex: 0 0 14px;
        }
        .org-unit-holdings-grid {
            display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
            width: 100%;
        }
        .org-unit-holdings-group {
            min-width: 0; padding: 13px 16px;
            border-inline-end: 1px solid #e2e8ed;
        }
        .org-unit-holdings-group:last-child { border-inline-end: 0; }
        .org-unit-lineage-list { width: 100%; padding: 8px 16px 10px; }
        .org-unit-lineage-row {
            position: relative; display: grid;
            grid-template-columns: 28px minmax(0, 1fr);
            align-items: center; gap: 9px; min-height: 38px;
        }
        .org-unit-lineage-row:not(:last-child)::after {
            content: ""; position: absolute; z-index: 0;
            inset-inline-start: 13px; top: 27px; bottom: -11px; width: 1px;
            background: #c8deec;
        }
        .org-unit-lineage-node {
            position: relative; z-index: 1; width: 28px; height: 28px;
            display: flex; align-items: center; justify-content: center;
            border-radius: 999px; color: var(--erms-blue); background: #eaf6fd;
        }
        .org-unit-lineage-node.current { color: white; background: var(--erms-blue); }
        .org-unit-lineage-copy {
            display: flex; align-items: center; gap: 8px; min-width: 0;
            justify-content: flex-start;
        }
        html[dir="rtl"] .org-unit-lineage-copy {
            direction: rtl; flex-direction: row !important;
        }
        .org-unit-lineage-link { cursor: pointer; color: var(--erms-blue); }
        .org-unit-lineage-link:hover { text-decoration: underline; }
        .org-unit-lineage-code {
            color: #8791a1; font-size: .68rem; font-weight: 600;
            letter-spacing: .025em;
        }
        @media (max-width: 760px) {
            .org-unit-holdings-grid { grid-template-columns: minmax(0, 1fr); }
            .org-unit-holdings-group {
                border-inline-end: 0; border-bottom: 1px solid #e2e8ed;
            }
            .org-unit-holdings-group:last-child { border-bottom: 0; }
        }
        @media (max-width: 1050px) {
            .dashboard-holdings-row {
                grid-template-columns: minmax(220px, 1fr) repeat(3, minmax(145px, auto));
                overflow-x: auto;
            }
        }
        @media (max-width: 520px) {
            .dashboard-holdings-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .dashboard-holdings-identity { grid-column: 1 / -1; }
            .dashboard-holdings-metric { justify-content: flex-start; }
            .dashboard-holdings-chart-row {
                grid-template-columns: minmax(72px, 90px) minmax(80px, 1fr) 38px;
                gap: 7px;
            }
            .dashboard-attention-plot { gap: 14px; padding-inline-end: 12px; padding-inline-start: 42px; }
            .dashboard-attention-axis-label { left: -42px; }
            .dashboard-storage-chart-row {
                grid-template-columns: minmax(72px, 90px) minmax(70px, 1fr) 65px;
                gap: 6px;
            }
        }
        .dashboard-review-layout {
            display: grid; grid-template-columns: minmax(190px, .55fr) minmax(0, 2fr);
            align-items: stretch; gap: 10px; width: 100%;
        }
        .dashboard-review-summary {
            width: 100%; min-width: 0; padding: 13px; gap: 10px;
            border: 1px solid #dce5eb; box-shadow: none;
        }
        .dashboard-review-donut {
            position: relative; width: 126px; height: 126px; margin: 4px auto;
            border-radius: 999px;
        }
        .dashboard-review-donut::after {
            content: ""; position: absolute; inset: 21px; border-radius: 999px;
            background: white;
        }
        .dashboard-review-donut-center {
            position: absolute; inset: 0; z-index: 1; display: flex;
            flex-direction: column; align-items: center; justify-content: center;
        }
        .dashboard-review-donut-total {
            color: #334155; font-size: 1.35rem; font-weight: 700;
            font-variant-numeric: tabular-nums;
        }
        .dashboard-review-donut-caption { color: #94a3b8; font-size: .65rem; }
        .dashboard-review-summary-row {
            display: grid; grid-template-columns: 9px minmax(0, 1fr) auto;
            align-items: center; gap: 7px; color: #64748b; font-size: .72rem;
        }
        .dashboard-review-summary-value {
            color: #334155; font-size: .85rem; font-weight: 600;
            font-variant-numeric: tabular-nums;
        }
        .dashboard-review-columns {
            display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px; width: 100%;
        }
        .dashboard-review-group {
            width: 100%; min-width: 0; padding: 0; gap: 0; overflow: hidden;
            border: 1px solid #dce5eb; box-shadow: none;
        }
        .dashboard-review-header {
            min-height: 46px; padding: 9px 11px; border-bottom: 1px solid #e2e8ed;
        }
        .dashboard-review-item {
            display: grid; grid-template-columns: 32px minmax(0, 1fr) auto;
            align-items: center; gap: 9px; width: 100%; min-width: 0;
            padding: 9px 11px; border-bottom: 1px solid #e8edf1;
            cursor: pointer; transition: all .16s ease;
        }
        .dashboard-review-item:last-child { border-bottom: 0; }
        .dashboard-review-item:hover { background: #f8fcff; }
        .dashboard-review-date { white-space: nowrap; font-variant-numeric: tabular-nums; }
        @media (max-width: 760px) {
            .dashboard-attention-chart,
            .dashboard-holdings-chart,
            .dashboard-storage-chart { width: 100%; }
            .dashboard-review-layout { grid-template-columns: minmax(0, 1fr); }
            .dashboard-review-summary {
                display: grid; grid-template-columns: minmax(0, 1fr) auto;
                align-items: center;
            }
            .dashboard-review-summary > :first-child { grid-column: 1 / -1; }
            .dashboard-review-columns { grid-template-columns: minmax(0, 1fr); }
        }
        @media (max-width: 460px) {
            .dashboard-review-date { display: none; }
        }
        .dashboard-personal-columns {
            display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px; width: 100%;
        }
        .dashboard-personal-panel {
            width: 100%; min-width: 0; padding: 0; gap: 0; overflow: hidden;
            border: 1px solid #dce5eb; box-shadow: none;
        }
        .dashboard-personal-dialog {
            display: flex; flex-direction: column; overflow: hidden;
        }
        .dashboard-personal-dialog-list {
            width: 100%; min-height: 0;
        }
        .dashboard-personal-header {
            min-height: 44px; padding: 9px 11px; border-bottom: 1px solid #e2e8ed;
        }
        .dashboard-personal-item {
            display: grid; grid-template-columns: 32px minmax(0, 1fr) auto;
            align-items: center; gap: 9px; width: 100%; min-width: 0;
            padding: 9px 11px; border-bottom: 1px solid #e8edf1;
            cursor: pointer; transition: all .16s ease;
        }
        .dashboard-personal-item:last-child { border-bottom: 0; }
        .dashboard-personal-item:hover { background: #f8fcff; }
        .dashboard-activity-badge {
            display: inline-flex; align-items: center; gap: 4px; white-space: nowrap;
            border: 1px solid currentColor; border-radius: 5px; padding: 2px 5px;
            font-size: .7rem; font-weight: 600;
        }
        .dashboard-activity-created { color: #28864a; }
        .dashboard-activity-updated { color: #a46000; }
        .dashboard-activity-viewed { color: #287eae; }
        @media (max-width: 760px) {
            .dashboard-personal-columns { grid-template-columns: minmax(0, 1fr); }
        }
        @media (max-width: 440px) {
            .dashboard-activity-badge { display: none; }
        }
        [dir="rtl"] .advanced-search-page { direction: rtl; text-align: right; }
        [dir="rtl"] .advanced-search-target-row,
        [dir="rtl"] .advanced-search-sort-row,
        [dir="rtl"] .advanced-search-submit-row,
        [dir="rtl"] .advanced-search-group-toolbar,
        [dir="rtl"] .advanced-search-condition-row {
            direction: ltr;
            flex-direction: row-reverse !important;
        }
        [dir="rtl"] .advanced-search-target-row > *,
        [dir="rtl"] .advanced-search-sort-row > *,
        [dir="rtl"] .advanced-search-submit-row > *,
        [dir="rtl"] .advanced-search-group-toolbar > *,
        [dir="rtl"] .advanced-search-condition-row > * {
            direction: rtl;
            text-align: right;
        }
        [dir="rtl"] .advanced-search-group {
            border-left-width: 1px !important;
            border-right-width: 4px !important;
            border-right-color: rgb(147 197 253) !important;
        }
        [dir="rtl"] .advanced-search-condition-actions {
            direction: ltr;
            flex-direction: row-reverse !important;
            margin-inline-start: 0 !important;
            margin-right: auto !important;
        }
        [dir="rtl"] .advanced-search-technical-value,
        [dir="rtl"] .advanced-search-technical-value input {
            direction: ltr !important;
            text-align: left !important;
        }
        [dir="rtl"] .advanced-search-auto-value input { text-align: start !important; }
        [dir="rtl"] .advanced-search-group .pl-2 {
            padding-inline-start: 0 !important;
            padding-inline-end: .5rem !important;
        }
        [dir="rtl"] .advanced-search-page .ml-auto {
            margin-inline-start: 0 !important;
            margin-inline-end: auto !important;
        }
        .advanced-search-workspace-layout {
            display: grid; grid-template-columns: minmax(0, 1fr) 260px;
            align-items: start; gap: 16px; width: 100%; min-width: 0;
        }
        .advanced-search-criteria-panel { min-width: 0; }
        .advanced-search-group > .q-card__section,
        .advanced-search-condition > .q-card__section { padding: 0; }
        .advanced-search-condition-actions { flex-wrap: nowrap; margin-inline-start: auto; }
        .advanced-search-result-actions { flex-wrap: nowrap; align-self: center; }
        .advanced-search-saved-panel {
            position: sticky; top: 76px; min-width: 0;
        }
        .advanced-search-saved-panel .q-btn { width: 100%; justify-content: flex-start; }
        .advanced-search-saved-panel .q-btn__content { justify-content: flex-start; }
        @media (max-width: 900px) {
            .advanced-search-workspace-layout { grid-template-columns: minmax(0, 1fr); }
            .advanced-search-saved-panel { position: static; }
            .advanced-search-saved-actions { flex-direction: row !important; flex-wrap: wrap; }
            .advanced-search-saved-panel .q-btn { width: auto; }
        }
    """)

    header_controls = build_header(
        q=q, select_messages=lambda folder: select_messages(folder),
        avatar_background=USER_AVATAR_BACKGROUND, avatar_text=USER_AVATAR_TEXT,
    )
    brand_mark = header_controls.brand_mark
    brand_name = header_controls.brand_name
    brand_row = header_controls.brand_row
    change_password_menu = header_controls.change_password_menu
    current_user_avatar = header_controls.current_user_avatar
    current_user_avatar_initials = header_controls.current_user_avatar_initials
    current_user_email = header_controls.current_user_email
    current_user_last_login = header_controls.current_user_last_login
    current_user_name = header_controls.current_user_name
    current_user_roles = header_controls.current_user_roles
    diagnostics_section = header_controls.diagnostics_section
    diagnostics_separator = header_controls.diagnostics_separator
    global_search_input = header_controls.global_search_input
    global_search_submit = header_controls.global_search_submit
    global_search_wrap = header_controls.global_search_wrap
    header_network = header_controls.header_network
    inspector_bridge = header_controls.inspector_bridge
    inspector_switch = header_controls.inspector_switch
    message_unread_button = header_controls.message_unread_button
    preferences_menu = header_controls.preferences_menu
    shell_header = header_controls.shell_header
    sign_out_menu = header_controls.sign_out_menu
    user_menu = header_controls.user_menu

    footer_controls = build_footer(initial_language)
    connection_icon = footer_controls.connection_icon
    connection_tooltip = footer_controls.connection_tooltip

    def set_connection_status(connected: bool) -> None:
        connection_icon.name = "cloud_done" if connected else "cloud_off"
        connection_icon.classes(
            replace="text-positive text-lg" if connected else "text-negative text-lg"
        )
        connection_tooltip.text = render_message("webui.set_connection_status.text.connected_cb4b6d71") if connected else render_message("webui.set_connection_status.text.disconnected_299593e5")
        connection_icon.update()
        connection_tooltip.update()

    drawer_controls = build_drawer(initial_direction)
    application_settings_navigation = drawer_controls.application_settings_navigation
    audit_navigation = drawer_controls.audit_navigation
    custody_navigation = drawer_controls.custody_navigation
    dashboard_navigation = drawer_controls.dashboard_navigation
    drawer = drawer_controls.drawer
    drawer_headings = drawer_controls.drawer_headings
    drawer_links = drawer_controls.drawer_links
    drawer_sections = drawer_controls.drawer_sections
    drawer_toggle_button = drawer_controls.drawer_toggle_button
    drawer_toggle_tooltip = drawer_controls.drawer_toggle_tooltip
    holds_navigation = drawer_controls.holds_navigation
    localized_navigation = drawer_controls.localized_navigation
    navigation = drawer_controls.navigation
    organization_browser_navigation = drawer_controls.organization_browser_navigation
    saved_search_administration_navigation = drawer_controls.saved_search_administration_navigation
    security_operations_navigation = drawer_controls.security_operations_navigation
    sessions_navigation = drawer_controls.sessions_navigation
    text_indexers_navigation = drawer_controls.text_indexers_navigation

    def set_active_drawer_link(page: str) -> None:
        navigation_key = {
            "aggregation-details": "aggregations",
            "record-details": "records",
            "classification-workspace": "classification-schemes",
            "classification-scheme-details": "classification-schemes",
            "classification-details": "classification-schemes",
            "org-unit-details": "org-units",
            "role-details": "roles",
            "user-details": "users",
            "disposition-job": "disposition-jobs",
            "disposition-task": "disposition-tasks",
        }.get(page, page)
        for button, _, key in drawer_links:
            if key == navigation_key:
                button.classes(add="erms-nav-link--active")
                button.props(add="aria-current=page")
            else:
                button.classes(remove="erms-nav-link--active")
                button.props(remove="aria-current")
            button.update()

    with shell_header:
        mobile_navigation = navigation_menu(
            drawer,
            expand_label=render_message("webui.toggle_navigation_drawer.text.expand_navigation_65731dae"),
            collapse_label=render_message("webui.toggle_navigation_drawer.text.collapse_navigation_1f139a52"),
        )
        mobile_navigation.move(target_index=1)

    drawer_collapsed = False

    def refresh_drawer_headings() -> None:
        visible_links = {key for button, _, key in drawer_links if button.visible}
        for heading, section_keys in drawer_sections:
            heading.set_visibility(
                not drawer_collapsed and bool(visible_links.intersection(section_keys))
            )

    def refresh_drawer_visibility(privileges: set[str] | None = None) -> None:
        granted = privileges
        if granted is None:
            granted = set(
                (auth_state.get("principal") or {}).get("global_privileges", [])
            )
        link_visibility = {
            key: can_navigate(key, granted)
            and can_navigate_disposition(key, auth_state.get("principal"))
            for _, _, key in drawer_links
        }
        for button, _, key in drawer_links:
            # Holds visibility is resolved separately from assigned hold access.
            if key != "holds":
                button.set_visibility(link_visibility[key])
        refresh_drawer_headings()

    def toggle_navigation_drawer() -> None:
        nonlocal drawer_collapsed
        drawer_collapsed = not drawer_collapsed
        if drawer_collapsed:
            drawer.props(add="mini")
            drawer.classes(add="erms-drawer--collapsed p-0")
            drawer_toggle_button.props(
                remove="aria-label icon",
                add='aria-label=' + json.dumps(render_message("webui.toggle_navigation_drawer.text.expand_navigation_65731dae"), ensure_ascii=False)
                    + ' icon=' + ('chevron_left' if initial_direction == 'rtl' else 'chevron_right'),
            )
            drawer_toggle_tooltip.text = render_message("webui.toggle_navigation_drawer.text.expand_navigation_65731dae")
            for heading in drawer_headings:
                heading.set_visibility(False)
            for button, _, _ in drawer_links:
                button.text = ""
                button.classes(add="justify-center px-0", remove="justify-start px-4")
                button.update()
        else:
            drawer.props(remove="mini")
            drawer.classes(remove="erms-drawer--collapsed p-0")
            drawer_toggle_button.props(
                remove="aria-label icon",
                add='aria-label=' + json.dumps(render_message("webui.toggle_navigation_drawer.text.collapse_navigation_1f139a52"), ensure_ascii=False)
                    + ' icon=' + ('chevron_right' if initial_direction == 'rtl' else 'chevron_left'),
            )
            drawer_toggle_tooltip.text = render_message("webui.toggle_navigation_drawer.text.collapse_navigation_1f139a52")
            for button, label, _ in drawer_links:
                button.text = label
                button.classes(add="justify-start px-4", remove="justify-center px-0")
                button.update()
            refresh_drawer_visibility()
        drawer.update()
        drawer_toggle_button.update()

    drawer_toggle_button.on("click", toggle_navigation_drawer)

    content_controls = build_content()
    add_button = content_controls.add_button
    add_record_button = content_controls.add_record_button
    aggregation_browse_mode = content_controls.aggregation_browse_mode
    aggregation_mode_bar = content_controls.aggregation_mode_bar
    aggregation_search_mode = content_controls.aggregation_search_mode
    breadcrumb_host = content_controls.breadcrumb_host
    content_card = content_controls.content_card
    guidance = content_controls.guidance
    page_title_icon = content_controls.page_title_icon
    search_bar = content_controls.search_bar
    search_button = content_controls.search_button
    search_input = content_controls.search_input
    subtitle = content_controls.subtitle
    table_container = content_controls.table_container
    title = content_controls.title

    def set_page_title_icon(page: str) -> None:
        icon_name = {
            "dashboard": "dashboard",
            "aggregations": "folder",
            "records": "description",
            "advanced-search": "manage_search",
            "classification-schemes": "account_tree",
            "classification-workspace": "account_tree",
            "classification-scheme-details": "account_tree",
            "classification-details": "schema",
            "org-units": "corporate_fare",
            "roles": "badge",
            "users": "group",
            "text-indexers": "manage_search",
            "text-indexer-details": "manage_search",
            "organization-browser": "lan",
            "audit-trail": "manage_history",
            "login-sessions": "devices",
            "governance-custody": "shield_person",
            "application-settings": "settings",
            "security-operations": "monitor_heart",
        }.get(page)
        if icon_name:
            page_title_icon.name = icon_name
            page_title_icon.set_visibility(True)
            page_title_icon.update()
        else:
            page_title_icon.set_visibility(False)

    def current_navigation_snapshot() -> dict[str, Any]:
        entity_result_state = state.get("entity_result_states", {}).get(state.get("resource"), {})
        return {
            "searched": bool(state.get("searched")),
            "search_text": str(search_input.value or ""),
            "lifecycle_filter": state.get("lifecycle_filter", "all"),
            "aggregation_mode": aggregation_state.get("aggregation_mode", "search"),
            "settings_category": application_settings_controller.category,
            "disposition_view": dict(state.get("disposition_view") or {}),
            "global_search_query": state.get("global_search_query", ""),
            "global_search_page": state.get("global_search_page", 1),
            "global_search_filter": state.get("global_search_filter", "all"),
            "global_search_return_anchor": state.get("global_search_return_anchor"),
            "global_search_expanded_results": sorted(state.get("global_search_expanded_results", set())),
            "entity_result_state": {
                **entity_result_state,
                "expanded_results": sorted(entity_result_state.get("expanded_results", set())),
            } if entity_result_state else {},
        }

    def global_search_payload(query: str, *, cursor: str | None = None) -> dict[str, Any]:
        full_text = {"full_text": {"query": query}}
        payload: dict[str, Any] = {
            "record_where": full_text,
            "aggregation_where": full_text,
            "result_types": ["records", "aggregations"],
            "limit": 25,
        }
        if cursor:
            payload["cursor"] = cursor
        if state["search_diagnostics_enabled"]:
            payload["debug"] = True
        return payload

    def render_safe_snippet(value: str | None, *, compact: bool = False) -> None:
        """Render server markers as elements so snippet text can never become HTML."""
        text = value or "No preview available"
        if compact:
            text = " ".join(text.split())
        layout = (
            "items-baseline gap-0 text-xs text-slate-600 no-wrap overflow-hidden whitespace-nowrap"
            if compact else "items-baseline gap-0 text-sm text-slate-600 flex-wrap"
        )
        with ui.row().classes(layout):
            highlighted = False
            for segment in text.replace("⟧", "⟧\x00").replace("⟦", "\x00⟦").split("\x00"):
                if not segment:
                    continue
                if segment.startswith("⟦"):
                    highlighted = True
                    segment = segment[1:]
                closes = segment.endswith("⟧")
                if closes:
                    segment = segment[:-1]
                if segment:
                    label = ui.label(segment).classes("whitespace-pre" if compact else "whitespace-pre-wrap")
                    if highlighted:
                        label.classes(add="global-search-highlight")
                if closes:
                    highlighted = False

    async def copy_diagnostic_json(value: dict[str, Any]) -> None:
        encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        await ui.run_javascript(
            f"navigator.clipboard.writeText({json.dumps(encoded)}).then(() => true)",
            timeout=5,
        )
        ui.notify(render_message("webui.copy_diagnostic_json.notify.json_copied_2dbf473d"), color="positive")

    def render_search_diagnostics() -> None:
        if not state["search_diagnostics_enabled"]:
            return
        with ui.expansion(render_message("webui.render_search_diagnostics.expansion.search_diagnostics_517d7729"), icon="bug_report").props(
            "dense header-class='text-slate-700'"
        ).classes("w-full border border-slate-200 rounded-lg"):
            sent = state.get("search_diagnostics_sent")
            accepted = state.get("search_diagnostics_accepted")
            with ui.column().classes("w-full p-3 gap-3"):
                with ui.row().classes("w-full items-center flex-wrap min-w-0"):
                    ui.label(render_message("webui.render_search_diagnostics.label.sent_to_api_68a1d285")).classes("font-semibold")
                    ui.label(render_message("webui.render_search_diagnostics.label.post_api_v1_full_text_search_8191066f")).classes("text-xs text-slate-500")
                    ui.space()
                    if sent is not None:
                        ui.button(render_message("webui.render_search_diagnostics.button.copy_json_19011ed1"), icon="content_copy", on_click=lambda: copy_diagnostic_json(sent)).props("flat dense no-caps")
                ui.code(json.dumps(sent, ensure_ascii=False, indent=2, sort_keys=True) if sent else render_message("webui.render_search_diagnostics.code.no_diagnostic_request_has_been_sent_5b401e20")).classes("global-search-json w-full")
                with ui.row().classes("w-full items-center flex-wrap min-w-0"):
                    ui.label(render_message("webui.render_search_diagnostics.label.accepted_by_api_6f8fcf1f")).classes("font-semibold")
                    if accepted:
                        ui.label(
                            render_message("webui.render_search_diagnostics.label.request_id_value_fingerprint_value_2_f8dbcf29", value=accepted.get('request_id') or 'unavailable', value_2=accepted.get('query_fingerprint') or 'unavailable')
                        ).classes("text-xs text-slate-500 break-all min-w-0")
                    ui.space()
                    if accepted:
                        ui.button(render_message("webui.render_search_diagnostics.button.copy_json_19011ed1"), icon="content_copy", on_click=lambda: copy_diagnostic_json(accepted)).props("flat dense no-caps")
                if accepted:
                    ui.code(json.dumps(accepted, ensure_ascii=False, indent=2, sort_keys=True)).classes("global-search-json w-full")
                else:
                    ui.label(render_message("webui.render_search_diagnostics.label.unavailable_the_api_did_not_accept_or_retu_8a4916f9")).classes("text-sm text-slate-500 italic")

    def render_global_search_results() -> None:
        table_container.clear()
        query = state["global_search_query"]
        items = state["global_search_items"]
        selected = state["global_search_filter"]
        visible = [item for item in items if selected == "all" or item["type"] == selected]
        page_size = int(state.get("global_search_page_size", 10))
        page_count = max(1, (len(visible) + page_size - 1) // page_size)
        state["global_search_page"] = min(max(1, int(state.get("global_search_page", 1))), page_count)
        page_number = state["global_search_page"]
        page_start = (page_number - 1) * page_size
        page_items = visible[page_start:page_start + page_size]
        record_count = sum(item["type"] == "record" for item in items)
        aggregation_count = sum(item["type"] == "aggregation" for item in items)
        with table_container, ui.column().classes("w-full p-5 gap-4"):
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                ui.label(render_message("webui.render_global_search_results.label.results_for_query_53df3850", query=query)).classes("text-sm text-slate-600 grow")
                if "search.query.debug" in set((auth_state.get("principal") or {}).get("global_privileges", [])):
                    def toggle_diagnostics(event) -> None:
                        state["search_diagnostics_enabled"] = bool(event.value)
                        state["search_diagnostics_sent"] = None
                        state["search_diagnostics_accepted"] = None
                        ui.notify(render_message("webui.toggle_diagnostics.notify.diagnostics_will_apply_to_the_next_explici_286f12ab"), color="primary")
                        render_global_search_results()
                    secondary_actions = ui.button(icon="more_vert").props(
                        'flat round aria-label=' + repr(render_message("webui.render_global_search_results.accessible_name.search_result_actions_10f81af1"))
                    ).tooltip(render_message("webui.render_global_search_results.tooltip.search_result_actions_2fe233c8"))
                    with secondary_actions, ui.menu():
                        diagnostics_toggle = ui.switch(
                            "Search diagnostics", value=state["search_diagnostics_enabled"],
                        ).props("dense color=primary").classes("px-3 py-2")
                        diagnostics_toggle.on_value_change(toggle_diagnostics)
            with ui.row().classes("items-center gap-1"):
                for key, label in (
                    ("all", render_message("global_search.filter.all", count=len(items))),
                    ("record", render_message("global_search.filter.records", count=record_count)),
                    ("aggregation", render_message("global_search.filter.aggregations", count=aggregation_count)),
                ):
                    button = ui.button(label, on_click=lambda _, value=key: (
                        state.__setitem__("global_search_filter", value),
                        state.__setitem__("global_search_page", 1),
                        render_global_search_results(),
                    )).props("dense no-caps")
                    button.props("unelevated color=primary" if selected == key else "flat color=blue-grey")
            if state.get("global_search_loading"):
                with ui.row().classes("w-full justify-center items-center py-12 gap-3").props('role=status aria-label=' + repr(render_message("webui.render_global_search_results.accessible_name.loading_search_results_eff54ce6"))):
                    ui.spinner("dots", size="32px", color="primary")
                    ui.label(render_message("webui.render_global_search_results.label.searching_records_files_and_aggregations_5756053f")).classes("text-slate-500")
                return
            render_search_diagnostics()
            if state.get("global_search_error"):
                with ui.card().classes("w-full shadow-none border border-red-200 bg-red-50 p-5"):
                    ui.icon("error_outline", color="negative", size="30px")
                    ui.label(render_message_plain("webui.render_global_search_results.label.search_could_not_be_completed_14ef74f3")).classes("font-semibold")
                    ui.label(state["global_search_error"]).classes("text-sm text-slate-600")
                    ui.button(render_message("webui.render_global_search_results.button.try_again_75a7aeea"), icon="refresh", on_click=lambda: run_global_search(query)).props("outline no-caps color=negative")
                return
            if state.get("global_search_pending"):
                with ui.row().classes("w-full items-center gap-2 rounded-lg bg-blue-50 border border-blue-200 p-3").props("role=status"):
                    ui.icon("info", color="primary")
                    ui.label(render_message("webui.render_global_search_results.label.recently_added_content_may_still_be_indexi_b45b7d39")).classes("text-sm text-slate-700")
            if not visible:
                with ui.column().classes("w-full items-center py-12 gap-2").props("role=status"):
                    ui.icon("search_off", size="42px").classes("text-slate-300")
                    ui.label(render_message("webui.render_global_search_results.label.no_results_found_ab1c85dc")).classes("text-lg font-semibold")
                    ui.label(render_message("webui.render_global_search_results.label.try_different_words_or_check_the_spelling_7fc06c50")).classes("text-sm text-slate-500")
            if page_items:
                with ui.column().classes("compact-result-list w-full gap-0"):
                    for item in page_items:
                        if item["type"] == "record":
                            record = item["record"]
                            authorized_component_details = {
                                int(component["id"]): component
                                for component in item.get("authorized_component_details", [])
                            }
                            matching_components = [
                                {**authorized_component_details.get(int(component["id"]), {}), **component}
                                for component in item.get("matching_components", [])
                                if component.get("id") is not None
                            ]
                            record_capabilities = item.get("record_capabilities") or {}
                            render_compact_resource_result(
                                "records", record,
                                on_open=open_global_record_from_result,
                                components=matching_components,
                                metadata_matched=bool(item.get("matched_record_metadata")),
                                content_matched=bool(matching_components),
                                can_preview=bool(
                                    record_capabilities.get("view_component")
                                    and any(component_is_previewable(component) for component in authorized_component_details.values())
                                ),
                                can_expand_components=bool(
                                    record_capabilities.get("list_components") and matching_components
                                ),
                                components_are_matches=True,
                                initially_expanded=(
                                    f"records:{int(record['id'])}" in state["global_search_expanded_results"]
                                ),
                                on_expansion_changed=lambda expanded, identifier=int(record["id"]):
                                    set_global_result_expansion("records", identifier, expanded),
                            )
                        else:
                            aggregation = item["aggregation"]
                            render_compact_resource_result(
                                "aggregations", aggregation,
                                on_open=open_global_aggregation_from_result,
                                metadata_matched=True,
                            )
            if visible:
                with ui.row().classes("w-full items-center justify-center gap-2 pt-1"):
                    first_button = ui.button(icon="first_page", on_click=lambda: change_global_search_page(1)).props(
                        'flat round aria-label=' + repr(render_message("webui.render_global_search_results.accessible_name.first_page_69926c59"))
                    ).tooltip(render_message("webui.render_global_search_results.tooltip.first_page_45ffdb30"))
                    previous_button = ui.button(icon="chevron_left", on_click=lambda: change_global_search_page(page_number - 1)).props(
                        'flat round aria-label=' + repr(render_message("webui.render_global_search_results.accessible_name.previous_page_571d7f79"))
                    ).tooltip(render_message("webui.render_global_search_results.tooltip.previous_page_6b7e38b3"))
                    ui.label(render_message("webui.render_global_search_results.label.page_page_number_9319ded9", page_number=page_number)).classes("text-sm text-slate-600 min-w-20 text-center")
                    next_button = ui.button(icon="chevron_right", on_click=lambda: change_global_search_page(page_number + 1)).props(
                        'flat round aria-label=' + repr(render_message("webui.render_global_search_results.accessible_name.next_page_c45c7218"))
                    ).tooltip(render_message("webui.render_global_search_results.tooltip.next_page_62ca3105"))
                    first_button.set_enabled(page_number > 1)
                    previous_button.set_enabled(page_number > 1)
                    next_button.set_enabled(page_number < page_count or bool(state.get("global_search_cursor")))
            restore_compact_result_anchor(state.pop("global_search_return_anchor", None))

    async def change_global_search_page(target_page: int) -> None:
        target_page = max(1, int(target_page))
        page_size = int(state.get("global_search_page_size", 10))
        while True:
            selected = state.get("global_search_filter", "all")
            visible_count = sum(
                selected == "all" or item["type"] == selected
                for item in state.get("global_search_items", [])
            )
            if (target_page - 1) * page_size < visible_count or not state.get("global_search_cursor"):
                break
            previous_cursor = state.get("global_search_cursor")
            await run_global_search(state["global_search_query"], load_more=True)
            if state.get("global_search_cursor") == previous_cursor:
                break
        selected = state.get("global_search_filter", "all")
        visible_count = sum(
            selected == "all" or item["type"] == selected
            for item in state.get("global_search_items", [])
        )
        page_count = max(1, (visible_count + page_size - 1) // page_size)
        state["global_search_page"] = min(target_page, page_count)
        render_global_search_results()

    def remember_global_result(item: dict[str, Any], resource: str) -> None:
        state["global_search_return_anchor"] = f"compact-result-{resource}-{int(item['id'])}"

    def set_global_result_expansion(resource: str, identifier: int, expanded: bool) -> None:
        key = f"{resource}:{int(identifier)}"
        expanded_results = state["global_search_expanded_results"]
        (expanded_results.add if expanded else expanded_results.discard)(key)

    async def open_global_record_from_result(record: dict[str, Any]) -> None:
        remember_global_result(record, "records")
        await open_global_record(int(record["id"]))

    async def open_global_aggregation_from_result(aggregation: dict[str, Any]) -> None:
        remember_global_result(aggregation, "aggregations")
        await open_global_aggregation(aggregation)

    async def open_global_record(record_id: int) -> None:
        state.pop("discard_navigation_guard", None)
        await select_record_details(record_id)

    async def open_global_aggregation(aggregation: dict[str, Any]) -> None:
        state.pop("discard_navigation_guard", None)
        await open_aggregation(aggregation)

    async def run_global_search(query: str, *, load_more: bool = False) -> None:
        if not auth_state.get("principal"):
            return
        revision = state.get("global_search_revision", 0) + 1
        state["global_search_revision"] = revision

        def is_current() -> bool:
            return (state.get("global_search_revision") == revision
                    and bool(auth_state.get("principal"))
                    and state["resource"] == "full-text-search")

        query = query.strip()
        if not query:
            ui.notify(render_message("webui.run_global_search.notify.enter_words_to_search_for_317e3f34"), color="warning")
            return
        if not load_more:
            state.pop("discard_navigation_guard", None)
            register_navigation("full-text-search", "Search results")
            state.update(resource="full-text-search", global_search_query=query,
                         global_search_items=[], global_search_cursor=None,
                         global_search_filter="all", global_search_page=1,
                         global_search_return_anchor=None, search_diagnostics_sent=None,
                         global_search_expanded_results=set(),
                         search_diagnostics_accepted=None, search_diagnostics_error=None)
            global_search_input.value = query
            global_search_input.update()
            await ui.run_javascript(
                f"history.replaceState(null, '', '/?q=' + encodeURIComponent({json.dumps(query)})); true",
                timeout=5,
            )
        if not is_current():
            return
        payload = global_search_payload(query, cursor=state.get("global_search_cursor") if load_more else None)
        if state["search_diagnostics_enabled"]:
            state["search_diagnostics_sent"] = payload
        state["global_search_loading"] = True
        state["global_search_error"] = None
        title.text = render_message("webui.run_global_search.text.search_results_ecc13a7a")
        subtitle.text = render_message("webui.run_global_search.text.records_files_and_aggregations_b4bdbe1c")
        show_authenticated_view()
        search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False); add_record_button.set_visibility(False)
        render_global_search_results()
        try:
            result = await api.full_text_search(payload)
            if not is_current():
                return
            result_items = list(result.get("items", []))
            record_items = [item for item in result_items if item.get("type") == "record"]
            async def load_global_matching_component_details(
                result_item: dict[str, Any],
            ) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
                record_id = int(result_item["record"]["id"])
                try:
                    capabilities, components = await asyncio.gather(
                        api.resource_capabilities("records", record_id),
                        api.component_page(record_id, limit=25),
                    )
                    return record_id, capabilities, components["items"]
                except ApiError:
                    return record_id, {}, []
            component_contexts = await asyncio.gather(*(
                load_global_matching_component_details(result_item) for result_item in record_items
            )) if record_items else []
            if not is_current():
                return
            component_details = {
                record_id: components for record_id, _, components in component_contexts
            }
            component_capabilities = {
                record_id: capabilities for record_id, capabilities, _ in component_contexts
            }
            for result_item in record_items:
                record_id = int(result_item["record"]["id"])
                result_item["authorized_component_details"] = component_details.get(record_id, [])
                result_item["record_capabilities"] = component_capabilities.get(record_id, {})
            state["global_search_items"].extend(result_items)
            state["global_search_cursor"] = result.get("next_cursor")
            state["global_search_pending"] = bool(result.get("index_freshness", {}).get("has_pending_content"))
            state["search_diagnostics_accepted"] = result.get("_debug")
        except ApiError as error:
            if is_current():
                state["global_search_error"] = error_message(error)
        finally:
            if is_current():
                state["global_search_loading"] = False
                render_global_search_results()

    def reset_navigation_session() -> None:
        navigation_controller.trail = []
        app.storage.user.pop("navigation_trail", None)

    persist_navigation_trail = navigation_controller.persist
    navigate_to_breadcrumb = navigation_controller.navigate_to_breadcrumb
    register_navigation = navigation_controller.register_navigation
    breadcrumb_back = navigation_controller.breadcrumb_back

    breadcrumb_message_keys = {
        "disposition-eligibility": "disposition.ui.eligibility",
        "disposition-jobs": "disposition.ui.jobs",
        "disposition-templates": "disposition.ui.templates",
        "disposition-tasks": "disposition.ui.my_tasks",
        "messages-inbox": "messaging.navigation.inbox",
        "messages-outbox": "messaging.navigation.outbox",
        "messages-drafts": "messaging.navigation.drafts",
        "messages-notifications": "messaging.admin.title",
        "relationship-types": "relationships.ui.catalogue",
        "messages-monitor": "messaging.monitor.title",
        "dashboard": "navigation.item.dashboard",
        "advanced-search": "navigation.item.advanced_search",
        "full-text-search": "webui.run_global_search.text.search_results_ecc13a7a",
        "aggregations": "navigation.item.aggregations",
        "records": "navigation.item.records",
        "classification-schemes": "navigation.item.classification_schemes",
        "classification-workspace": "navigation.item.classification_schemes",
        "organization-browser": "navigation.item.organization_browser",
        "org-units": "navigation.item.org_units",
        "roles": "navigation.item.roles",
        "users": "navigation.item.users",
        "text-indexers": "navigation.item.text_indexers",
        "audit-trail": "navigation.item.audit_trail",
        "login-sessions": "navigation.item.login_sessions",
        "security-operations": "navigation.item.security_operations",
        "security-levels": "navigation.item.security_levels",
        "profiles": "navigation.item.profiles",
        "translations": "navigation.item.translations",
        "governance-custody": "navigation.item.governance_custody",
        "application-settings": "navigation.item.application_settings",
        "holds": "navigation.item.holds",
    }

    def localized_breadcrumb_label(entry: dict[str, Any]) -> str:
        page = str(entry.get("page") or "")
        stored_label = entry.get("label")
        message_key = entry.get("label_key")
        if not message_key and not entry.get("dynamic_label"):
            # Migrate trails saved before language-neutral label keys were
            # persisted. The page identity, not its old rendered text,
            # determines a static breadcrumb's label in the active language.
            message_key = breadcrumb_message_keys.get(page)
        if message_key:
            return render_message(str(message_key))
        return stored_label or page.replace("-", " ").title()

    def render_navigation_breadcrumbs() -> None:
        breadcrumb_host.clear()
        trail = navigation_controller.trail
        breadcrumb_host.set_visibility(bool(auth_state.get("principal") and trail))
        if not trail or not auth_state.get("principal"):
            return
        visible, hidden = visible_navigation_indices(len(trail))
        with breadcrumb_host, ui.row().classes(
            "erms-breadcrumb-row w-full items-center no-wrap gap-1 text-xs text-slate-500 overflow-hidden"
        ):
            previous_index = None
            for index in visible:
                if previous_index is not None and index > previous_index + 1:
                    with ui.button(icon="more_horiz").props(
                        f"flat round dense size=sm aria-label='{len(hidden)} hidden navigation entries'"
                    ):
                        with ui.menu():
                            for hidden_index in hidden:
                                item = trail[hidden_index]
                                ui.menu_item(
                                    localized_breadcrumb_label(item),
                                    on_click=lambda _, target=hidden_index: navigate_to_breadcrumb(target),
                                )
                if previous_index is not None:
                    ui.icon("chevron_right", size="15px").props("aria-hidden=true").classes("shrink-0 text-slate-300")
                entry = trail[index]
                label = localized_breadcrumb_label(entry)
                accessible_label = (
                    label if label != entry.get("label")
                    else entry.get("accessible_label") or label
                )
                if index == len(trail) - 1:
                    ui.label(label).props("aria-current=page").classes(
                        "font-semibold text-slate-700 truncate max-w-64"
                    ).tooltip(accessible_label)
                else:
                    ui.button(
                        label, on_click=lambda _, target=index: navigate_to_breadcrumb(target),
                    ).props("flat dense no-caps color=blue-grey").classes(
                        "min-w-0 max-w-52 truncate px-1"
                    ).tooltip(accessible_label)
                previous_index = index

    def prepare_navigation(page: str) -> None:
        # A newly committed page transition owns subsequent reads. Any older
        # transition may no longer update the visible page and is cancelled.
        api.cancel_pending_reads()
        if page != "full-text-search":
            state["search_diagnostics_sent"] = None
            state["search_diagnostics_accepted"] = None
            state["search_diagnostics_error"] = None
        if page == "dashboard":
            content_card.classes(add="erms-dashboard-card")
        else:
            content_card.classes(remove="erms-dashboard-card")
        set_active_drawer_link(page)
        set_page_title_icon(page)

    async def restore_navigation_entry(entry: dict[str, Any]) -> None:
        page = entry["page"]
        saved = entry.get("state") or {}
        entity_id = entry.get("entity_id")
        if page == "dashboard":
            await select_dashboard()
        elif page == "full-text-search":
            query = str(saved.get("global_search_query") or state.get("global_search_query") or "")
            if query:
                if state.get("global_search_items") and state.get("global_search_query") == query:
                    state["global_search_page"] = int(saved.get("global_search_page") or 1)
                    state["global_search_filter"] = saved.get("global_search_filter") or "all"
                    state["global_search_return_anchor"] = saved.get("global_search_return_anchor")
                    state["global_search_expanded_results"] = set(
                        saved.get("global_search_expanded_results") or []
                    )
                    register_navigation("full-text-search", "Search results")
                    state["resource"] = "full-text-search"
                    title.text = render_message("webui.restore_navigation_entry.text.search_results_92198f98")
                    subtitle.text = render_message("webui.restore_navigation_entry.text.records_files_and_aggregations_3e6f144c")
                    show_authenticated_view()
                    search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
                    add_button.set_visibility(False); add_record_button.set_visibility(False)
                    render_global_search_results()
                else:
                    await run_global_search(query)
            else:
                await select_dashboard()
        elif page in ("disposition-tasks", "disposition-eligibility", "disposition-jobs", "disposition-templates", "disposition-job", "disposition-task"):
            disposition_saved=saved.get("disposition_view") or {}
            await select_disposition(page, disposition_saved.get("job_id") if page=="disposition-task" else entity_id if page=="disposition-job" else None, disposition_saved,task_id=entity_id if page=="disposition-task" else None)
        elif page == "relationship-types":
            await select_relationship_types()
        elif page.startswith("messages-"):
            await select_messages(page.removeprefix("messages-"))
        elif page == "advanced-search":
            await select_advanced_search()
        elif page in ENTITIES:
            if saved.get("entity_result_state"):
                restored_result_state = dict(saved["entity_result_state"])
                restored_result_state["expanded_results"] = set(
                    restored_result_state.get("expanded_results") or []
                )
                state.setdefault("entity_result_states", {})[page] = restored_result_state
            if page == "aggregations":
                aggregation_state["aggregation_mode"] = saved.get("aggregation_mode", "search")
            await select_entity(page)
            # Browse restores its own expanded branches, selection and scroll.
            # A search made before switching modes must not replace that tree.
            if page == "aggregations" and aggregation_state.get("aggregation_mode") == "browse":
                return
            search_input.value = saved.get("search_text", "")
            state["lifecycle_filter"] = saved.get("lifecycle_filter", "all")
            if saved.get("searched") and search_input.value and ENTITIES[page].search_first:
                await load_rows()
            elif state["lifecycle_filter"] != "all" and page in {"org-units", "roles", "users"}:
                render_table(ENTITIES[page])
        elif page == "classification-workspace":
            await select_classification_workspace()
        elif page == "classification-scheme-details" and entity_id is not None:
            await select_classification_workspace(initial_scheme_id=entity_id)
        elif page == "classification-details" and entity_id is not None:
            await select_classification_workspace(initial_classification_id=entity_id)
        elif page == "organization-browser":
            await show_organization_structure()
        elif page == "audit-trail":
            await select_audit_trail()
        elif page == "login-sessions":
            await select_login_sessions()
        elif page == "governance-custody":
            await select_governance_custody()
        elif page == "application-settings":
            await application_settings_controller.restore(saved)
        elif page == "holds":
            await select_holds()
        elif page == "hold-details" and entity_id is not None:
            await select_hold_details(entity_id)
        elif page == "security-operations":
            await select_security_operations()
        elif page == "saved-search-administration":
            await select_saved_search_administration()
        elif page == "text-indexers":
            await select_text_indexers()
        elif page == "translations":
            await select_translation_administration()
        elif page == "text-indexer-details" and entity_id is not None:
            await select_text_indexer_details(entity_id)
        elif page == "aggregation-details" and entity_id is not None:
            await open_aggregation(await api.get("aggregations", entity_id))
        elif page == "record-details" and entity_id is not None:
            await select_record_details(entity_id)
        elif page == "org-unit-details" and entity_id is not None:
            await select_organization_unit_details(entity_id)
        elif page == "role-details" and entity_id is not None:
            await select_role_details(entity_id)
        elif page == "user-details" and entity_id is not None:
            await select_user_details(entity_id)
        else:
            raise ApiError(404, "Navigation target is no longer available")

    def clear_authenticated_view() -> None:
        """Remove protected data as soon as there is no authenticated principal."""
        state.update(resource='dashboard', rows=[], searched=False); aggregation_state.update(aggregation_detail=None)
        aggregation_state.pop("aggregation_browse", None)
        personal.favourites = {"aggregations": [], "records": []}
        personal.favourite_ids = {"aggregations": set(), "records": set()}
        title.text = ""
        subtitle.text = ""
        page_title_icon.set_visibility(False)
        guidance.text = ""
        table_container.clear()
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        content_card.set_visibility(False)
        breadcrumb_host.set_visibility(False)

    def clear_global_search_session() -> None:
        """Discard private query state and invalidate outstanding search responses."""
        state.pop("advanced_search_workspace", None)
        state.pop("discard_navigation_guard", None)
        state["advanced_search_session_revision"] = state.get("advanced_search_session_revision", 0) + 1
        state.update(
            global_search_revision=state.get("global_search_revision", 0) + 1,
            global_search_query="", global_search_items=[], global_search_cursor=None,
            global_search_filter="all", global_search_page=1,
            global_search_return_anchor=None, global_search_expanded_results=set(),
            global_search_loading=False, global_search_error=None, global_search_pending=False,
            search_diagnostics_enabled=False, search_diagnostics_sent=None,
            search_diagnostics_accepted=None, search_diagnostics_error=None,
            entity_result_states={},
        )
        global_search_input.value = ""
        global_search_input.update()


    def dashboard_session_key() -> tuple[Any, ...] | None:
        principal = auth_state.get("principal")
        if principal is None:
            return None
        localization = state.get("localization") or {}
        return (
            state.get("dashboard_session_revision", 0),
            principal["user"]["id"],
            localization.get("effective_language", "en"),
            localization.get("working_timezone", "UTC"),
            tuple(sorted(principal.get("global_privileges", []))),
            tuple(sorted(role["id"] for role in principal.get("roles", []))),
        )

    def clear_dashboard_session() -> None:
        """Discard private snapshots and invalidate all old dashboard callbacks."""
        state.pop("dashboard_summary_cache", None)
        state.pop("dashboard_summary_cache_key", None)
        state.pop("dashboard_view_token", None)
        state["dashboard_session_revision"] = state.get("dashboard_session_revision", 0) + 1

    def clear_signed_in_identity() -> None:
        """Remove account identity and overlays before presenting sign-in again."""
        stop_message_stream()
        message_unread_button.set_visibility(False)
        clear_global_search_session()
        clear_dashboard_session()
        classification_controller.reset()
        api.cancel_pending_reads()
        drawer.hide()
        mobile_navigation.set_visibility(False)
        user_menu.close()
        diagnostics_separator.set_visibility(False)
        diagnostics_section.set_visibility(False)
        inspector_switch.value = False
        inspector_switch.update()
        background_tasks.create(clear_translation_inspector_session())
        disable_diagnostic_metadata(page_client.id)
        auth_state["principal"] = None
        state["application_configuration"] = {}
        global_search_wrap.set_visibility(False)
        current_user_name.text = render_message("webui.clear_signed_in_identity.text.not_signed_in_a1c07c9a")
        current_user_email.text = ""
        current_user_avatar_initials.text = "?"
        current_user_avatar.style(
            replace=(
                f"background:{USER_AVATAR_BACKGROUND} !important;"
                f"color:{USER_AVATAR_TEXT} !important"
            )
        )
        current_user_last_login.text = render_message("webui.clear_signed_in_identity.text.first_sign_in_823bfe67")
        current_user_roles.clear()
        header_network.set_visibility(False)
        reset_navigation_session()
        clear_authenticated_view()

    def show_authenticated_view() -> None:
        content_card.set_visibility(True)

    def accept_application_configuration(configuration):
        """Page response values only; no independent expiry or environment fallback."""
        state["application_configuration"] = configuration
        global_search_wrap.set_visibility(full_text_search_enabled(configuration))
        localization = state.get("localization") or {}
        if localization.get("uses_default_working_timezone") is True:
            timezone_name = configuration["DEFAULT_WORKING_TIMEZONE"]
            localization["working_timezone"] = timezone_name
            with table_container:
                set_locale_context(localization["effective_language"], timezone_name)
            app.storage.user["localization_context"] = localization







    def restore_compact_result_anchor(anchor_id: str | None) -> None:
        if not anchor_id:
            return
        async def restore() -> None:
            await page_client.run_javascript(
                "requestAnimationFrame(() => requestAnimationFrame(() => {"
                f"const result = document.getElementById({json.dumps(anchor_id)});"
                "if (result) result.scrollIntoView({block:'center'});"
                "}));"
            )
        background_tasks.create(restore())

    entity_types = {
        "aggregations": "aggregation", "records": "record",
        "digital-components": "digital_component", "org-units": "org_unit",
        "users": "user", "roles": "role",
        "classification-schemes": "classification_scheme",
        "classifications": "classification",
    }

    async def open_audit_entity(entity_type: str, entity: dict[str, Any]) -> None:
        if entity_type == "aggregation":
            await open_aggregation(entity)
        elif entity_type == "record":
            await show_record_details(entity)
        elif entity_type == "digital_component":
            try:
                record = await api.get("records", entity["record_id"])
                with table_container:
                    await show_components(record)
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
        elif entity_type == "classification_scheme":
            await select_classification_workspace(initial_scheme_id=entity["id"])
        elif entity_type == "classification":
            await select_classification_workspace(
                initial_scheme_id=entity["classification_scheme_id"],
                initial_classification_id=entity["id"],
            )
        elif entity_type in {"org_unit", "user", "role"}:
            resource = {
                "org_unit": "org-units", "user": "users", "role": "roles",
            }[entity_type]
            await select_entity(resource)
            with table_container:
                await open_editor(entity)

    preview_record_components = build_component_preview(
        api=api,
        error_message=error_message,
    )

    show_components = build_components(
        api=api,
        error_message=error_message,
        show_entity_history=lambda *args, **kwargs: show_entity_history(*args, **kwargs),
        preview_record_components=preview_record_components,
        render_component_cards=render_component_cards,
    )






    show_reopen_aggregation, show_governed_move, show_ownership_correction = build_aggregation_actions(
        api=api,
        bind_remote_relationship_select=lambda *args, **kwargs: bind_remote_relationship_select(*args, **kwargs),
        error_message=error_message,
    )




    async def show_record_details(record: dict[str, Any]) -> None:
        """Navigate to the dedicated details page for a record."""
        await select_record_details(record["id"])

    async def select_record_details(record_id: int) -> None:
        relationship_token = object()
        relationship_principal = auth_state.get("principal")
        state["relationship_page_token"] = relationship_token
        register_navigation("record-details", f"Record #{record_id}", entity_id=record_id)
        previous_resource = state.get("resource")
        if previous_resource != "record-details":
            state["record_detail_return_resource"] = previous_resource
            state["record_detail_return_aggregation"] = aggregation_state.get("aggregation_detail")
        show_authenticated_view()
        state.update(resource="record-details", record_detail_id=record_id, rows=[], searched=True)
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        table_container.clear()

        try:
            fetched = await api.get("records", record_id)
            record = (await decorate_for_spec(ENTITIES["records"], [fetched]))[0]
            security_level, owning_org_unit, capabilities, effective_holds = await asyncio.gather(
                api.get("security-levels", record["security_level_id"]),
                api.get("org-units", record["owning_org_unit_id"]),
                api.resource_capabilities("records", record_id),
                api.effective_holds("record", record_id),
            )
            record_components = (
                (await api.component_page(record_id, limit=25))["items"]
                if capabilities.get("list_components") else []
            )
            location_source_ids = {
                record.get("effective_assigned_location_source_aggregation_id"),
                record.get("effective_current_location_source_aggregation_id"),
            } - {None}
            location_sources = {
                source_id: await api.get("aggregations", source_id)
                for source_id in location_source_ids
            }
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return

        title.text = record["title"]
        subtitle.text = render_message("webui.select_record_details.text.record_record_number_6c5c5dcc", record_number=record['record_number'])
        register_navigation(
            "record-details", record["title"], entity_id=record_id,
            accessible_label=f"{record['title']} — {record['record_number']}",
        )

        async def refresh_record_view(saved: dict[str, Any] | None = None) -> None:
            await select_record_details((saved or record)["id"])

        async def reindex_record_components() -> None:
            try:
                result=await api.reindex_record(record["id"])
                ui.notify(
                    render_message("webui.reindex_record_components.notify.reindex_batch_queued_queued_new_already_in_952147c5", queued=result['queued'], already_in_progress=result['already_in_progress'], unsupported_or_no_content=result['unsupported_or_no_content']),
                    color="info",close_button=True,
                )
            except ApiError as error:
                ui.notify(error_message(error),color="negative",close_button=True)

        async def leave_record_page() -> None:
            await breadcrumb_back(lambda: select_entity("records"))

        async def open_containing_aggregation() -> None:
            try:
                await open_aggregation(await api.get("aggregations", record["aggregation_id"]))
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)

        async def confirm_delete_record() -> None:
            confirmation = ui.dialog()
            try:
                component_total = await api.component_count(record["id"])
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                return
            with confirmation, ui.card().classes("w-[500px] max-w-full"):
                ui.label(render_message("webui.confirm_delete_record.label.delete_record_44486e61")).classes("text-xl font-semibold")
                ui.label(
                    render_message("webui.confirm_delete_record.label.record_number_title_will_be_permanently_de_fd38dfa9", record_number=record['record_number'], title=record['title'])
                ).classes("text-sm text-slate-700")
                if component_total:
                    ui.label(
                        render_message("webui.confirm_delete_record.label.its_component_count_digital_component_valu_7b85da08", component_count=component_total, value='s' if component_total != 1 else '')
                    ).classes("text-sm font-medium text-negative")
                ui.label(render_message("webui.confirm_delete_record.label.the_immutable_event_history_will_be_retain_daa89bf7")).classes("text-xs text-slate-500")

                async def delete_record() -> None:
                    try:
                        await api.delete("records", record["id"], record["version"])
                        confirmation.close()
                        ui.notify(render_message("webui.delete_record.notify.record_deleted_87ce6f8a"), color="positive")
                        await load_recent(ENTITIES["records"])
                        await leave_record_page()
                    except ApiError as error:
                        ui.notify(error_message(error), color="negative", close_button=True)

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.confirm_delete_record.button.cancel_8987a97b"), on_click=confirmation.close).props("flat no-caps")
                    ui.button(
                        render_message("webui.confirm_delete_record.button.delete_record_2a62e6e1"), icon="delete_forever", color="negative",
                        on_click=delete_record,
                    ).props("unelevated no-caps")
            confirmation.open()

        async def remove_record_from_all_holds() -> None:
            async def remove(reason: str) -> None:
                await api.remove_all_direct_holds("record", record_id, reason)
                ui.notify(render_message("webui.remove.notify.record_removed_from_all_directly_assigned_3c5f5d03"), color="positive")
                await select_record_details(record_id)

            await hold_reason_dialog(
                render_message("webui.hold_reason_dialog.remove_all_confirmation"),
                render_message("webui.open_aggregation.button.remove_direct_holds_d5ecb7ae"),
                remove,
            )

        with table_container, ui.column().classes("w-full p-5 gap-5"):
            with ui.element("div").classes("record-command-layout w-full"):
                with ui.column().classes("record-command-controls"):
                    with ui.card().classes("detail-surface w-full shadow-none p-4 gap-3"):
                        ui.label(render_message("webui.select_record_details.label.hold_controls_c055620a")).classes("aggregation-panel-heading w-full")
                        with ui.row().classes("w-full gap-2 flex-wrap"):
                            if effective_holds:
                                ui.button(
                                    render_message("webui.select_record_details.button.view_holds_73f90e5b"), icon="visibility",
                                    on_click=lambda: show_effective_holds_dialog(
                                        effective_holds, "record", record_id,
                                        lambda: select_record_details(record_id),
                                    ),
                                ).props("outline dense no-caps color=primary")
                            if capabilities.get("add_to_hold"):
                                ui.button(
                                    render_message("webui.select_record_details.button.add_to_hold_e811b460"), icon="add_link",
                                    on_click=lambda: add_resource_to_hold_dialog(
                                        "record", record_id, lambda: select_record_details(record_id),
                                    ),
                                ).props("outline dense no-caps color=primary")
                            if capabilities.get("remove_all_direct_hold_assignments"):
                                ui.button(
                                    render_message("webui.select_record_details.button.remove_direct_holds_4c99e462"), icon="link_off",
                                    on_click=remove_record_from_all_holds,
                                ).props("outline dense no-caps color=negative")
                            if not effective_holds and not capabilities.get("add_to_hold"):
                                ui.label(render_message("webui.select_record_details.label.no_hold_actions_are_available_41ed8e8a")).classes("text-xs text-slate-500")
                    with ui.card().classes("detail-surface w-full shadow-none p-4 gap-3"):
                        ui.label(render_message("webui.select_record_details.label.record_actions_ae672368")).classes("aggregation-panel-heading w-full")
                        ui.label(render_message("webui.select_record_details.label.metadata_and_review_185a8164")).classes("record-action-group-label")
                        record_metadata_actions = ui.row().classes("w-full gap-2 flex-wrap")
                        ui.label(render_message("webui.select_record_details.label.security_access_and_audit_355a3bbe")).classes("record-action-group-label")
                        record_security_actions = ui.row().classes("w-full gap-2 flex-wrap")
                        ui.label(render_message("webui.select_record_details.label.lifecycle_0a37135c")).classes("record-action-group-label")
                        record_lifecycle_actions = ui.row().classes("w-full gap-2 flex-wrap")
                        if not record.get("_effectively_closed") and capabilities.get("move"):
                            with ui.expansion(
                                render_message("webui.select_record_details.expansion.advanced_73101adb"), caption=render_message("record_details.guidance.specialist_actions"),
                                icon="tune", value=False,
                            ).classes("w-full border-t border-slate-100"):
                                record_advanced_actions = ui.row().classes(
                                    "w-full justify-start gap-2 pb-2"
                                )
                        else:
                            record_advanced_actions = None
                record_command_overview = ui.card().classes(
                    "detail-surface record-command-overview w-full shadow-none p-0 gap-0 overflow-hidden"
                )
                record_command_overview.__enter__()
                with ui.row().classes("w-full items-center px-5 py-3 border-b border-slate-100"):
                    ui.icon("description", color="primary", size="21px")
                    ui.label(render_message("webui.select_record_details.label.record_details_4a7ba94d")).classes("font-semibold")
                record_preview_available = (
                    record.get("medium") != "physical"
                    and capabilities.get("view_component")
                    and any(component_is_previewable(item) for item in record_components)
                )
                with ui.grid(columns="auto minmax(0, 1fr) auto").classes(
                    f"record-detail-identity-header w-full {RECORD_DETAIL_HEADER_CLASSES} gap-3 px-5 py-5"
                ):
                    ui.avatar(icon="description", color="blue-1", text_color="primary", size="52px")
                    with ui.column().classes(RECORD_DETAIL_TITLE_CLASSES):
                        ui.label(record["record_number"]).classes("text-xs text-primary font-semibold")
                        ui.label(record["title"]).classes("text-lg font-semibold break-words")
                    with ui.grid(
                        columns=f"repeat({3 if record_preview_available else 2}, max-content)"
                    ).classes("record-detail-header-actions items-center gap-2"):
                        favourite_button("records", record["id"])
                        if record_preview_available:
                            ui.button(
                                icon="visibility",
                                on_click=lambda: preview_record_components(record),
                            ).props(
                                'flat round dense color=primary aria-label=' + repr(render_message("webui.select_record_details.accessible_name.preview_digital_components_d68f8cab"))
                            ).tooltip(render_message("webui.select_record_details.tooltip.preview_digital_components_b4905386"))
                        ui.button(
                            render_message("webui.select_record_details.button.back_f6cea7ff"),
                            icon=None if current_direction["value"] == "rtl" else "arrow_back",
                            on_click=leave_record_page,
                        ).props(
                            "flat no-caps color=blue-grey-8"
                            + (" icon-right=arrow_forward" if current_direction["value"] == "rtl" else "")
                        )
                    if capabilities.get("change_security_level"):
                        with record_security_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.security_level_2f483a84"), icon="security",
                                on_click=lambda: show_security_level_change(
                                    "record", record, refresh_record_view,
                                ),
                            ).props("outline dense no-caps").tooltip(render_message("webui.select_record_details.tooltip.change_the_record_security_level_8289e1f4"))
                    if not record.get("_effectively_closed") and capabilities.get("modify_metadata"):
                        with record_metadata_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.edit_metadata_d7742b94"), icon="edit",
                                on_click=lambda: open_editor(
                                    record, on_saved=refresh_record_view, resource_key="records",
                                ),
                            ).props("outline dense no-caps color=primary")
                    if not record.get("_effectively_closed") and capabilities.get("delete"):
                        with record_lifecycle_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.delete_962597c5"), icon="delete_outline", color="negative",
                                on_click=confirm_delete_record,
                            ).props("outline dense no-caps")
                    with record_security_actions:
                        ui.button(
                            render_message("webui.select_record_details.button.event_history_89d2205e"), icon="history",
                            on_click=lambda: show_entity_history("records", record),
                        ).props("outline dense no-caps")
                        ui.button(
                            render_message("webui.select_record_details.button.why_this_access_a28abcce"), icon="fact_check",
                            on_click=lambda: show_access_explanation("record", record["id"]),
                        ).props("outline dense no-caps").tooltip(render_message("webui.select_record_details.tooltip.explain_the_authorization_decision_gate_by_cc6d9083"))
                        if capabilities.get("reindex_components"):
                            ui.button(
                                render_message("webui.select_record_details.button.reindex_components_c8b4317c"),icon="manage_search",
                                on_click=reindex_record_components,
                            ).props("outline dense no-caps").tooltip(
                                render_message("webui.select_record_details.tooltip.queue_a_background_reindex_for_every_eligi_b41c4630")
                            )
                    if capabilities.get("manage_acl"):
                        with record_security_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.access_489ef75d"), icon="policy",
                                on_click=lambda: show_acl_editor(
                                    "records", record["id"], on_saved=lambda: refresh_record_view(),
                                ),
                            ).props("outline dense no-caps")
                    if capabilities.get("change_vital_status"):
                        async def change_vital() -> None:
                            dialog = ui.dialog()
                            with dialog, ui.card().classes("w-[520px] max-w-full"):
                                ui.label(render_message("webui.change_vital.label.change_vital_status_4cad0b01")).classes("text-xl font-semibold")
                                value = ui.checkbox(render_message("webui.change_vital.checkbox.vital_record_1d96a258"), value=bool(record.get("is_vital")))
                                reason = ui.textarea(render_message("webui.change_vital.textarea.reason_6aae1911")).props("outlined autogrow").classes("w-full")
                                async def submit() -> None:
                                    if not (reason.value or "").strip():
                                        ui.notify(render_message("webui.submit.notify.enter_a_reason_f7e81e79"), color="warning"); return
                                    try:
                                        saved = await api.change_vital_status("records", record["id"], record["version"], bool(value.value), reason.value.strip())
                                        dialog.close(); await refresh_record_view(saved)
                                    except ApiError as error: ui.notify(error_message(error), color="negative", close_button=True)
                                ui.button(render_message("webui.change_vital.button.save_9787450d"), on_click=submit).props("unelevated")
                            dialog.open()
                        with record_metadata_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.vital_status_e3b08bfe"), icon="emergency", on_click=change_vital,
                            ).props("outline dense no-caps").tooltip(
                                render_message("webui.select_record_details.tooltip.change_whether_this_record_is_protected_as_f1c5619f")
                            )
                    if capabilities.get("change_review_date"):
                        async def change_record_review_date() -> None:
                            dialog = ui.dialog()
                            with dialog, ui.card().classes("w-[520px] max-w-full"):
                                ui.label(render_message("webui.change_record_review_date.label.schedule_next_review_ea5d874d")).classes("text-xl font-semibold")
                                ui.label(render_message("webui.change_record_review_date.label.set_a_future_date_or_clear_it_when_no_revi_45f20a16")).classes("text-sm text-slate-500")
                                review_date = ui.input(render_message("webui.change_record_review_date.input.date_of_next_review_2e08f279"), value=review_datetime_input_value(record.get("date_of_next_review"))).props(f"outlined clearable type=datetime-local min={review_datetime_input_minimum()}").classes("w-full")
                                reason = ui.textarea(render_message("webui.change_record_review_date.textarea.reason_f2cf789a")).props("outlined autogrow").classes("w-full")
                                async def submit() -> None:
                                    if not (reason.value or "").strip(): ui.notify(render_message("webui.submit.notify.enter_a_reason_f7e81e79"), color="warning"); return
                                    value = review_datetime_payload(review_date.value)
                                    try:
                                        saved = await api.change_review_date("records", record["id"], record["version"], value, reason.value.strip())
                                        dialog.close(); await refresh_record_view(saved)
                                    except (ApiError, ValueError) as error: ui.notify(error_message(error) if isinstance(error, ApiError) else render_message("webui.submit.notify.choose_a_valid_future_date_d0f7285f"), color="negative", close_button=True)
                                ui.button(render_message("webui.change_record_review_date.button.save_67ef4f4f"), on_click=submit).props("unelevated")
                            dialog.open()
                        with record_metadata_actions:
                            ui.button(
                                render_message("webui.select_record_details.button.next_review_4e7a14e8"), icon="event", on_click=change_record_review_date,
                            ).props("outline dense no-caps").tooltip(
                                render_message("webui.select_record_details.tooltip.schedule_or_clear_this_record_s_next_gover_b9fd992b")
                            )
                if record_advanced_actions is not None:
                    with record_advanced_actions:
                        ui.button(
                            render_message("webui.select_record_details.button.move_d812404c"), icon="drive_file_move",
                            on_click=lambda: show_governed_move(
                                "records", record, refresh_record_view,
                            ),
                        ).props("outline dense no-caps")
                ui.separator()
                with ui.column().classes("w-full px-5 py-4 gap-4"):
                    if record.get("_effectively_closed"):
                        with ui.row().classes("detail-status-notice w-full items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg"):
                            ui.icon("lock", color="amber-8")
                            ui.label(render_message("webui.select_record_details.label.this_record_is_read_only_because_its_aggre_39233ef1")).classes("text-sm text-amber-900")
                    if record.get("is_vital"):
                        with ui.row().classes(
                            "detail-status-notice w-full items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg"
                        ):
                            ui.icon("emergency", color="red-8")
                            with ui.column().classes("detail-status-notice-copy gap-0"):
                                ui.label(render_message("webui.select_record_details.label.vital_record_26408a5c")).classes("text-sm font-semibold text-red-900")
                                ui.label(
                                    render_message("webui.select_record_details.label.this_record_is_protected_from_deletion_whi_70e8fed6")
                                ).classes("text-xs text-red-800")
                    if effective_holds:
                        with ui.row().classes(
                            "detail-status-notice w-fit max-w-full items-center gap-2 flex-wrap rounded-xl "
                            "border border-amber-200 bg-amber-50 px-3 py-2"
                        ):
                            ui.icon("gavel", color="warning").classes("shrink-0")
                            hold_count = len(effective_holds)
                            ui.label(
                                render_message("webui.select_record_details.label.protected_by_hold_count_effective_value_fdfb1fe2", hold_count=hold_count)
                            ).classes("text-sm font-semibold text-amber-900")
                            ui.button(
                                render_message("webui.select_record_details.button.view_holds_73f90e5b"), icon="visibility",
                                on_click=lambda: show_effective_holds_dialog(
                                    effective_holds, "record", record_id,
                                    lambda: select_record_details(record_id),
                                ),
                            ).props("flat dense no-caps color=warning")
                    with ui.grid(columns=2).classes("w-full gap-x-8 gap-y-0"):
                        record_metadata = [
                            (
                                "security_level", render_message("entity_metadata.field.security_level"),
                                f"{security_level['code']} — {(security_level.get('localized') or {}).get('name') or security_level['name']}",
                            ),
                            (
                                "owning_org_unit",
                                render_message("advanced_search.field.owning_org_unit"),
                                f"{owning_org_unit['code']} — {(owning_org_unit.get('localized') or {}).get('name') or owning_org_unit['name']}",
                            ),
                            ("medium", render_message("entity_metadata.field.medium"), medium_label(record.get("medium"))),
                            (
                                "vital_status",
                                render_message("webui.select_record_details.button.vital_status_e3b08bfe"),
                                render_message("translation_inspector.value.yes")
                                if record.get("is_vital") else
                                render_message("translation_inspector.value.no"),
                            ),
                            ("originated", render_message("entity_metadata.field.date_originated"), format_timestamp(record.get("date_originated"))),
                            ("created", render_message("advanced_search.field.date_created"), format_timestamp(record.get("date_created"))),
                        ]
                        if record.get("medium") != "digital":
                            record_metadata.extend([
                                (
                                    "inherited_assigned_location",
                                    f'{render_message("entity_metadata.field.assigned_location")} · {render_message("entity_metadata.field.inherited_location")}',
                                    record.get("effective_assigned_location") or render_message("webui.render_detail_content.text.unknown_d3c1ce73"),
                                ),
                                (
                                    "inherited_current_location",
                                    f'{render_message("entity_metadata.field.current_location")} · {render_message("entity_metadata.field.inherited_location")}',
                                    record.get("effective_current_location") or render_message("webui.render_detail_content.text.unknown_d3c1ce73"),
                                ),
                            ])
                        record_metadata.extend([
                            ("disposition_status", disposition_text("status"), disposition_status_label(record.get("disposition_status", 1))),
                            ("review", render_message("entity_metadata.field.review"), review_display(record.get("date_of_next_review"))),
                            # The state disambiguates a protected existing
                            # container from an absent relationship; records
                            # structurally always have a container.
                            (
                                "containing_aggregation",
                                render_message("advanced_search.field.parent_aggregation"),
                                render_message("webui.open_aggregation.label.parent_aggregation_restricted_684099c8")
                                if record.get("aggregation_state") == "redacted"
                                else record.get("aggregation_display"),
                            ),
                        ])
                        for field_key, label, value in record_metadata:
                            with ui.column().classes("detail-field gap-1"):
                                ui.label(label).classes("detail-field-label")
                                if field_key == "containing_aggregation" and isinstance(value, dict):
                                    with ui.button(on_click=open_containing_aggregation).props(
                                        "flat dense no-caps color=primary"
                                    ).classes("detail-linked-entity self-start -m-2 p-2"):
                                        with ui.column().classes("detail-linked-entity-content"):
                                            ui.label(value.get("name") or "—").classes(
                                                "detail-linked-entity-title"
                                            )
                                            if value.get("code"):
                                                ui.label(value["code"]).classes(
                                                    "detail-linked-entity-identifier"
                                                )
                                elif field_key == "vital_status":
                                    ui.badge(
                                        str(value),
                                        color="red-8" if record.get("is_vital") else "blue-grey-7",
                                    ).props("outline")
                                else:
                                    ui.label(str(value or "—")).classes("detail-field-value")
                                    if field_key.startswith("inherited_"):
                                        source_key = "effective_assigned_location_source_aggregation_id" if field_key == "inherited_assigned_location" else "effective_current_location_source_aggregation_id"
                                        source = location_sources.get(record.get(source_key))
                                        if source:
                                            ui.label(render_message("webui.select_record_details.label.inherited_from_aggregation_number_title_ab7fbcfd", aggregation_number=source['aggregation_number'], title=source['title'])).classes("text-xs text-slate-500")
                        with ui.column().classes("detail-field col-span-full gap-1"):
                            ui.label(
                                render_message("webui.select_record_details.label.description_918dd932")
                            ).classes("detail-field-label")
                            ui.label(record.get("description") or "—").props("dir=auto").classes(
                                "detail-field-value whitespace-pre-wrap break-words leading-6"
                            )

                record_command_overview.__exit__(None, None, None)
            await relationship_panel(
                api=api, kind="record", identity=record_id,
                source_label=" · ".join(filter(None, (record.get("record_number"), record.get("title")))),
                can_link="relationships.link" in (auth_state.get("principal") or {}).get("global_privileges", []),
                active=lambda: auth_state.get("principal") is relationship_principal and state.get("resource") == "record-details" and state.get("relationship_page_token") is relationship_token,
                open_target=open_related_resource, bind_remote=bind_remote_relationship_select, on_error=error_message,
                browse_resource=browse_advanced_aggregation,
            )
            with ui.card().classes("detail-surface w-full shadow-none p-5 gap-4"):
                with ui.row().classes("w-full items-center gap-3"):
                    ui.icon("attach_file", color="primary", size="28px")
                    with ui.column().classes("gap-0 grow"):
                        ui.label(render_message("webui.select_record_details.label.digital_components_c5a1a49d")).classes("text-xl font-semibold")
                        ui.label(render_message("webui.select_record_details.label.files_belonging_to_this_record_can_be_mana_7c78350c")).classes("text-sm text-slate-500")
                components_host = ui.column().classes("w-full gap-3")
                await show_components(record, container=components_host)

    async def decorate_for_spec(
        spec: EntitySpec,
        rows: list[dict[str, Any]],
        *,
        aggregation_rows: list[dict[str, Any]] | None = None,
        related_rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        rows_by_id = row_hydrators.rows_by_id
        closure_flags = row_hydrators.closure_flags
        org_unit_context = row_hydrators.org_unit_context



        if spec.key == "classifications":
            return await decorate_classifications(rows, rows_by_id=rows_by_id, relationship_cell=relationship_cell)
        if spec.key == "aggregations":
            closed_by_id = await closure_flags(rows, "id")
            return [
                {
                    **item,
                    "medium_display": medium_label(item.get("medium")),
                    "vital_display": "Vital" if item.get("is_vital") else "Contains vital resources" if item.get("has_vital_descendants") else "Not vital",
                    "review_display": review_display(item.get("date_of_next_review")),
                    "location_display": item.get("effective_current_location") or item.get("effective_assigned_location") or "Unknown",
                    "_effectively_closed": closed_by_id.get(int(item["id"]), False),
                    "_directly_closed": bool(item.get("date_closed")),
                }
                for item in rows
            ]
        if spec.key in {"org-units", "roles", "users"}:
            return await decorate_organization_rows(
                spec, rows, org_unit_context=org_unit_context, rows_by_id=rows_by_id,
                decorate_relationship_rows=decorate_relationship_rows, relationship_cell=relationship_cell,
            )
        if spec.key == "records":
            aggregations_by_id = await rows_by_id(
                "aggregations", {item.get("aggregation_id") for item in rows},
            )
            closed_by_id = await closure_flags(rows, "aggregation_id")
            decorated = decorate_relationship_rows(
                spec.key, rows, list(aggregations_by_id.values()),
            )
            return [
                {
                    **item,
                    "medium_display": medium_label(item.get("medium")),
                    "vital_display": "Vital" if item.get("is_vital") else "Not vital",
                    "review_display": review_display(item.get("date_of_next_review")),
                    "location_display": item.get("effective_current_location") or item.get("effective_assigned_location") or "Unknown",
                    "_effectively_closed": closed_by_id.get(
                        int(item["aggregation_id"]), False,
                    ),
                }
                for item in decorated
            ]
        return rows


    browse_advanced_aggregation = build_aggregation_selector(
        api=api,
        bind_remote_scheme_select=lambda *args, **kwargs: bind_remote_scheme_select(*args, **kwargs),
        error_message=error_message,
        tree_expander_icon=lambda *args, **kwargs: tree_expander_icon(*args, **kwargs),
    )

    async def open_record_draft_editor(
        target_aggregation_id: int | None = None, on_committed=None, existing_capture_draft=None, capture_active=None,
        capture_loader=None, capture_dialog=None,
    ) -> None:
        spec = ENTITIES["records"]
        try:
            draft = existing_capture_draft or await api.create_record_draft()
            security_levels, creation_roles = await asyncio.gather(
                api.list("security-levels", limit=25),
                api.creation_role_options(target_aggregation_id),
            )
            target_aggregation = (
                await api.get("aggregations", target_aggregation_id)
                if target_aggregation_id is not None else None
            )
            aggregations_by_id = (
                {target_aggregation["id"]: target_aggregation}
                if target_aggregation is not None else {}
            )
        except ApiError as error:
            if capture_dialog is not None:capture_dialog.close()
            if capture_active is not None and not capture_active():return
            ui.notify(error_message(error), color="negative", close_button=True)
            return

        if capture_active is not None and not capture_active():
            if capture_dialog is not None:capture_dialog.close()
            return

        dialog = capture_dialog or ui.dialog().props("persistent")
        dialog.clear()
        capture_preparation = {"closed": False, "ready": capture_loader is None}
        controls: dict[str, Any] = {}
        current_rows: list[dict[str, Any]] = []
        component_area: Any = None
        upload_lock = asyncio.Lock()
        upload_state = {"pending": 0}
        action_controls: dict[str, Any] = {}
        uploader_control: dict[str, Any] = {}

        async def refresh_draft_components() -> bool:
            try:
                rows = await api.draft_components(draft["id"])
                if capture_active is not None and not capture_active():return
                current_rows.clear()
                current_rows.extend(rows)
                component_area.clear()
                component_list.set_visibility(bool(rows))
                with component_area:
                    if rows:
                        render_component_cards(
                            rows, move_draft_component, remove_draft_component,
                            on_view=lambda component: preview_record_components(
                                None, component["id"], draft_id=draft["id"], staged_components=list(current_rows),
                                source_active=lambda: dialog.value and not dialog._deleted and (capture_active is None or capture_active()),
                            ),
                            readonly=existing_capture_draft is not None, staged_preview=True,
                        )
                return True
            except ApiError as error:
                if capture_active is not None and not capture_active():return
                with component_area:
                    ui.notify(error_message(error), color="negative")
                return False

        async def move_draft_component(component: dict[str, Any], direction: int) -> None:
            index = next((i for i, item in enumerate(current_rows) if item["id"] == component["id"]), -1)
            target = index + direction
            if index < 0 or target < 0 or target >= len(current_rows):
                return
            reordered = list(current_rows)
            reordered[index], reordered[target] = reordered[target], reordered[index]
            try:
                await api.reorder_draft_components(draft["id"], [
                    {"id": item["id"], "component_order": position}
                    for position, item in enumerate(reordered, 1)
                ])
                await refresh_draft_components()
            except ApiError as error:
                ui.notify(error_message(error), color="negative")

        async def remove_draft_component(component: dict[str, Any]) -> None:
            try:
                await api.delete_draft_component(draft["id"], component["id"])
                ui.notify(render_message("webui.remove_draft_component.notify.staged_file_removed_5c3ae99e"), color="positive")
                await refresh_draft_components()
            except ApiError as error:
                ui.notify(error_message(error), color="negative")

        def upload_to_draft(event: events.MultiUploadEventArguments) -> None:
            try:
                buffered_files = buffer_upload_batch(event)
                # Form controls are client-side state. Persist the relationship
                # and medium before the component endpoint validates the draft.
                component_context = record_draft_component_context(
                    target_aggregation_id
                    if target_aggregation_id is not None
                    else controls["aggregation_id"].value,
                    controls["medium"].value,
                )
            except OSError as error:
                ui.notify(render_message("webui.upload_to_draft.notify.could_not_read_an_uploaded_file_error_17327476", error=error), color="negative", close_button=True)
                return
            except ValueError as error:
                ui.notify(validation_error_message(error), color="warning", close_button=True)
                return
            upload_state["pending"] += 1
            action_controls["commit"].disable()
            action_controls["upload_wait"].set_visibility(True)

            async def stage_buffered_files() -> None:
                try:
                    async with upload_lock:
                        await api.update_record_draft(draft["id"], component_context)
                        await refresh_draft_components()
                        first_position = len(current_rows) + 1
                        for offset, (content, name, mime_type) in enumerate(buffered_files):
                            await api.upload_draft_component(
                                draft["id"], first_position + offset, name, content, mime_type,
                            )
                            await refresh_draft_components()
                    with component_area:
                        ui.notify(
                            render_message("webui.stage_buffered_files.notify.buffered_file_count_file_value_staged_for_45b0562d", buffered_file_count=len(buffered_files), value='s' if len(buffered_files) != 1 else ''),
                            color="positive",
                        )
                    uploader_control["uploader"].reset()
                except ApiError as error:
                    with component_area:
                        ui.notify(error_message(error), color="negative", close_button=True)
                finally:
                    upload_state["pending"] -= 1
                    if upload_state["pending"] == 0:
                        action_controls["commit"].enable()
                        action_controls["upload_wait"].set_visibility(False)

            background_tasks.create(
                stage_buffered_files(), name=f"stage components for draft {draft['id']}"
            )

        async def discard() -> None:
            capture_preparation["closed"] = True
            if draft.get("id") is None:
                dialog.close()
                return
            try:
                await api.discard_record_draft(draft["id"])
            except ApiError as error:
                if error.status_code != 404:
                    ui.notify(error_message(error), color="negative")
                    return
            dialog.close()

        async def commit() -> None:
            if not capture_preparation["ready"] or capture_preparation["closed"]:
                return
            if existing_capture_draft is not None:
                action_controls["commit"].disable()
                action_controls["commit"].props("loading")
            try:
                payload = form_payload(spec, controls, creating=True)
                if target_aggregation_id is not None:
                    # The aggregation-details route owns this relationship.
                    # Bind it from route context instead of trusting a
                    # read-only presentation control to submit its value.
                    payload["aggregation_id"] = int(target_aggregation_id)
                creator_role_id = controls["creator_acl_role_id"].value
                if creator_role_id is None:
                    raise ValueError("Select who this record is being created for")
                await api.update_record_draft(draft["id"], payload)
                committed_record = await api.commit_record_draft(
                    draft["id"], int(creator_role_id), capture=existing_capture_draft is not None,
                )
                if capture_active is not None and not capture_active():return
                dialog.close()
                ui.notify(render_message("webui.commit.notify.record_and_digital_components_created_c1c2938b"), color="positive")
                if existing_capture_draft is None:
                    await load_recent(spec)
                if capture_active is not None and not capture_active():return
                if on_committed is not None:
                    await on_committed(committed_record)
                    return
                state["searched"] = False
                render_table(spec)
            except ValueError as error:
                ui.notify(validation_error_message(error), color="warning")
            except ApiError as error:
                if capture_active is not None and not capture_active():return
                if await show_number_conflict(error, "records", controls["record_number"]):
                    return
                ui.notify(error_message(error), color="negative", close_button=True)

            finally:
                if existing_capture_draft is not None and (capture_active is None or capture_active()):
                    action_controls["commit"].props(remove="loading")
                    action_controls["commit"].enable()

        with dialog, ui.card().classes("max-h-[calc(100vh-32px)] p-0").style("width: 1050px; max-width: calc(100vw - 32px)"):
            with ui.row().classes("w-full items-center no-wrap px-6 pt-5"):
                ui.avatar(icon="note_add", color="blue-1", text_color="primary")
                with ui.column().classes("gap-0 grow"):
                    ui.label(render_message("webui.open_record_draft_editor.label.create_record_080740e1")).classes("text-xl font-semibold")
                    ui.label(render_message("webui.open_record_draft_editor.label.assemble_the_metadata_and_files_then_creat_ba4447db")).classes("text-sm text-slate-500")
                ui.badge(render_message("webui.open_record_draft_editor.badge.draft_59a3031a"), color="primary").props("outline")
            with ui.element("div").classes("w-full overflow-y-auto px-6 pb-2 max-h-[calc(100vh-190px)]"):
                ui.label(render_message("webui.open_record_draft_editor.label.record_details_e88ae30c")).classes("text-base font-semibold mt-4 mb-2")
                ui.label(render_message("webui.open_record_draft_editor.label.required_fields_40cea53e")).classes("text-xs text-slate-500 -mt-1 mb-2")
                with ui.grid(columns=2).classes("w-full gap-3"):
                    aggregation_field = next(
                        field for field in spec.fields if field.name == "aggregation_id"
                    )
                    controls["aggregation_id"] = field_input(
                        aggregation_field,
                        value=target_aggregation_id,
                        options=relationship_options(
                            list(aggregations_by_id.values()),
                            aggregation_field.lookup_label_fields,
                        ),
                    )
                    controls["aggregation_id"].classes("col-span-2").props("clearable")
                    style_relationship_chip_select(
                        controls["aggregation_id"], "aggregation_id",
                    )
                    if target_aggregation_id is None:
                        async def destinations(query):
                            if len(query.strip()) < 2:
                                return {"items": []}
                            return await api.search_request("aggregations", {
                                "where": {"or": [{"field": field, "operator": "contains_ci", "value": query.strip()}
                                    for field in ("aggregation_number", "title", "description")]},
                                "sort": [{"field": "aggregation_number", "direction": "asc"}], "limit": 25,
                            }, record_creation=True, digital_only=existing_capture_draft is not None)
                        bind_remote_relationship_select(
                            controls["aggregation_id"], "aggregations",
                            ("aggregation_number", "title"),
                            aggregation_field.lookup_label_fields,
                            page_loader=destinations,
                            active=lambda: dialog.value and (capture_active is None or capture_active()),
                        )
                        ui.button(
                            render_message("webui.show_memberships.button.browse_aed12689"),
                            icon="account_tree",
                            on_click=lambda: browse_advanced_aggregation(controls["aggregation_id"], record_creation=True, digital_only=existing_capture_draft is not None),
                        ).props("flat dense no-caps").classes("col-span-2 justify-self-start")
                    if target_aggregation_id is not None:
                        # Read-only keeps the selected parent visible in the
                        # form. Saving is independently guarded by binding the
                        # route's target_aggregation_id into the payload.
                        controls["aggregation_id"].props("readonly")
                        ui.label(
                            render_message("webui.open_record_draft_editor.label.the_parent_aggregation_is_fixed_because_th_767330a4")
                        ).classes("text-xs leading-5 text-slate-500 col-span-2 -mt-2")

                    role_options = {
                        item["role_id"]: item["label"] for item in creation_roles
                    } if target_aggregation_id is not None else {}
                    controls["creator_acl_role_id"] = ui.select(
                        role_options,
                        value=(
                            creation_roles[0]["role_id"]
                            if target_aggregation_id is not None and len(creation_roles) == 1
                            else None
                        ),
                        label=render_message("webui.open_record_draft_editor.select.create_for_857b2d59"),
                    ).props("outlined options-dense").classes("w-full col-span-2")
                    # A sole eligible role is fixed by policy but must remain
                    # visibly populated; readonly avoids the empty rendering
                    # observed with a disabled NiceGUI select.
                    if len(creation_roles) == 1:
                        controls["creator_acl_role_id"].props("readonly")
                    elif not creation_roles:
                        controls["creator_acl_role_id"].disable()
                    ui.label(
                        render_message("webui.open_record_draft_editor.label.select_the_role_that_will_receive_creator_410b59fa")
                    ).classes("text-xs leading-5 text-slate-500 col-span-2 -mt-2")
                    creation_role_status = ui.label(
                        render_message("webui.open_record_draft_editor.label.select_a_parent_aggregation_before_choosin_e92b6402")
                        if target_aggregation_id is None
                        else (
                            render_message("webui.open_record_draft_editor.label.create_for_was_set_automatically_because_y_974126aa")
                            if len(creation_roles) == 1
                            else (
                                render_message("webui.open_record_draft_editor.label.you_do_not_have_an_effective_role_in_the_p_124c1ce3")
                                if not creation_roles
                                else render_message("webui.open_record_draft_editor.label.choose_one_of_your_roles_in_the_parent_agg_e5eca9a8")
                            )
                        )
                    ).props('role="status" aria-live="polite"').classes(
                        "text-xs leading-5 text-amber-800 col-span-2 -mt-2"
                    )
                    for field in spec.fields:
                        if field.name == "aggregation_id":
                            continue
                        lookup_rows = (
                            list(aggregations_by_id.values()) if field.lookup_resource == "aggregations"
                            else security_levels if field.lookup_resource == "security-levels"
                            else []
                        )
                        options = relationship_options(lookup_rows, field.lookup_label_fields) if field.lookup_resource else None
                        initial_value = None
                        if field.name == "security_level_id" and security_levels:
                            initial_value = min(
                                security_levels, key=lambda item: (item["level_number"], item["id"])
                            )["id"]
                        if field.name == "medium":
                            parent = aggregations_by_id.get(controls["aggregation_id"].value)
                            initial_value = parent.get("medium", "mixed") if parent else "mixed"
                        if existing_capture_draft is not None and field.name in draft:
                            initial_value = draft[field.name]
                        controls[field.name] = field_input(field, value=initial_value, options=options)
                        if field.name == "record_number":
                            add_number_suggestion(controls[field.name], "records", controls)
                        if field.name == "security_level_id":
                            bind_resource_security_select(
                                controls[field.name], parent_control=controls["aggregation_id"],
                            )
                        if field.kind == "textarea":
                            controls[field.name].classes("col-span-2")
                    def constrain_record_medium() -> None:
                        parent = aggregations_by_id.get(controls["aggregation_id"].value)
                        medium_control = controls["medium"]
                        if existing_capture_draft is not None:
                            medium_control.set_options({"digital": medium_options()["digital"]}, value="digital")
                            medium_control.disable()
                            return
                        if not parent:
                            medium_control.set_options({"digital": medium_options()["digital"]} if existing_capture_draft is not None else {},
                                                       value="digital" if existing_capture_draft is not None else None)
                            medium_control.disable()
                            return
                        parent_medium = parent.get("medium", "mixed")
                        if parent_medium == "mixed":
                            medium_control.set_options(
                                medium_options(),
                                value=medium_control.value or "mixed",
                            )
                            medium_control.enable()
                        else:
                            medium_control.set_options(
                                {parent_medium: medium_options()[parent_medium]}, value=parent_medium,
                            )
                            medium_control.disable()
                        medium_control.update()
                    async def refresh_record_creation_roles() -> None:
                        aggregation_id = controls["aggregation_id"].value
                        role_control = controls["creator_acl_role_id"]
                        previous_role_id = role_control.value
                        if aggregation_id is None:
                            role_control.set_options({}, value=None)
                            role_control.disable()
                            creation_role_status.set_text(
                                render_message('webui.open_record_draft_editor.label.select_a_parent_aggregation_before_choosin_e92b6402'))
                            return
                        try:
                            rows = await api.creation_role_options(int(aggregation_id))
                            if controls["aggregation_id"].value != aggregation_id or (capture_active is not None and not capture_active()):
                                return
                        except ApiError as error:
                            ui.notify(error_message(error), color="negative", close_button=True)
                            return
                        eligible_role_ids = {item["role_id"] for item in rows}
                        previous_role_was_cleared = (
                            previous_role_id is not None
                            and previous_role_id not in eligible_role_ids
                        )
                        selected_role_id = (
                            previous_role_id if previous_role_id in eligible_role_ids
                            else rows[0]["role_id"] if len(rows) == 1
                            else None
                        )
                        role_control.set_options(
                            {item["role_id"]: item["label"] for item in rows},
                            value=selected_role_id,
                        )
                        role_control.props(remove="readonly")
                        if len(rows) == 1:
                            role_control.enable()
                            role_control.props("readonly")
                        elif rows:
                            role_control.enable()
                        else:
                            role_control.disable()
                        if not rows:
                            creation_role_status.set_text(
                                render_message("webui.open_record_draft_editor.label.you_do_not_have_an_effective_role_in_the_p_124c1ce3")
                            )
                        elif previous_role_was_cleared:
                            creation_role_status.set_text(
                                render_message("messaging.capture.creator_role_cleared")
                            )
                        elif len(rows) == 1:
                            creation_role_status.set_text(
                                render_message('webui.open_record_draft_editor.label.create_for_was_set_automatically_because_y_974126aa'))
                        else:
                            creation_role_status.set_text(
                                render_message('webui.open_record_draft_editor.label.choose_one_of_your_roles_in_the_parent_agg_e5eca9a8'))

                    async def apply_selected_aggregation() -> None:
                        aggregation_id = controls["aggregation_id"].value
                        if (
                            aggregation_id is not None
                            and int(aggregation_id) not in aggregations_by_id
                        ):
                            try:
                                aggregations_by_id[int(aggregation_id)] = await api.get(
                                    "aggregations", int(aggregation_id),
                                )
                            except ApiError as error:
                                ui.notify(error_message(error), color="negative", close_button=True)
                                return
                        if controls["aggregation_id"].value != aggregation_id or (capture_active is not None and not capture_active()):
                            return
                        with dialog:
                            constrain_record_medium()
                            await refresh_record_creation_roles()

                    controls["aggregation_id"].on_value_change(
                        lambda: background_tasks.create(apply_selected_aggregation())
                    )
                    constrain_record_medium()
                with ui.column().classes("w-full gap-0 mt-5 mb-2"):
                    ui.label(render_message("webui.open_record_draft_editor.label.digital_components_21c9474b")).classes("w-full text-start text-base font-semibold")
                    ui.label(render_message("webui.open_record_draft_editor.label.files_remain_staged_until_you_create_the_r_ec0dd8d9")).classes("w-full text-start text-xs text-slate-500")
                with ui.column().classes("w-full") as draft_upload_area:
                    uploader_control["uploader"] = component_uploader(upload_to_draft)
                with ui.row().classes(
                    "w-full items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3"
                ) as physical_draft_notice:
                    ui.icon("inventory_2", color="primary")
                    with ui.column().classes("gap-0 grow"):
                        ui.label(render_message("webui.open_record_draft_editor.label.this_is_a_physical_record_399cc6c8")).classes("font-semibold text-blue-900")
                        ui.label(render_message("webui.open_record_draft_editor.label.digital_files_cannot_be_added_a2f23cff")).classes("text-sm text-blue-800")

                def update_draft_component_controls() -> None:
                    selected_medium = controls["medium"].value
                    draft_upload_area.set_visibility(existing_capture_draft is None and selected_medium in {"digital", "mixed"})
                    physical_draft_notice.set_visibility(selected_medium == "physical")

                controls["medium"].on_value_change(
                    lambda _: update_draft_component_controls()
                )
                controls["aggregation_id"].on_value_change(
                    lambda _: update_draft_component_controls()
                )
                update_draft_component_controls()
                with ui.element("div").classes("component-list w-full mt-3") as component_list:
                    component_area = ui.element("div").classes("component-grid w-full")
                component_list.set_visibility(capture_loader is not None)
                if capture_loader is not None:
                    with component_area:
                        for component in draft.get("components", []):
                            with ui.card().classes("w-full gap-1").props("flat bordered"):
                                with ui.grid(columns="auto minmax(0, 1fr)").classes("w-full items-center gap-2"):
                                    ui.spinner(size="sm")
                                    ui.label(component["title"]).classes("font-semibold grow break-words")
                                ui.label(component["file_name"]).classes("text-xs text-slate-500 break-all")
                                ui.label(render_message("messaging.capture.preparing")).classes("text-sm text-slate-500")
            ui.separator()
            with ui.row().classes("w-full justify-end gap-2 px-6 py-4"):
                with ui.row().classes(
                    "items-center gap-1 text-sm text-slate-500 mr-2"
                ) as upload_wait:
                    ui.icon("hourglass_top", size="18px")
                    ui.label(RECORD_UPLOAD_WAIT_MESSAGE)
                upload_wait.set_visibility(False)
                action_controls["upload_wait"] = upload_wait
                ui.button(render_message("webui.open_record_draft_editor.button.cancel_draft_84ea17b5"), on_click=discard).props("flat color=grey-7").mark("capture-cancel" if capture_loader is not None else "record-draft-cancel")
                action_controls["commit"] = ui.button(render_message("webui.open_record_draft_editor.button.create_record_dd0193d6"), icon="check", on_click=commit).props("unelevated")
                if capture_loader is not None:
                    action_controls["commit"].disable()
                    action_controls["commit"].mark("capture-create")
        dialog.open()
        if capture_loader is not None:
            try:
                prepared = await capture_loader()
            except ApiError as error:
                if not capture_preparation["closed"] and (capture_active is None or capture_active()):
                    action_controls["upload_wait"].set_visibility(False)
                    component_area.clear()
                    with component_area:
                        ui.label(error_message(error)).classes("text-negative").mark("capture-preparation-error")
                else:
                    dialog.close()
                return
            if capture_preparation["closed"] or (capture_active is not None and not capture_active()):
                await api.discard_record_draft(prepared["id"])
                dialog.close()
                return
            # Keep metadata the user has edited while conversion was running.
            # The server rechecks the chain and its security floor at commit.
            draft = prepared
            components_loaded = await refresh_draft_components()
            if capture_preparation["closed"] or (capture_active is not None and not capture_active()):
                if not capture_preparation["closed"]:
                    await api.discard_record_draft(prepared["id"])
                dialog.close()
                return
            if not components_loaded:
                return
            capture_preparation["ready"] = True
            action_controls["upload_wait"].set_visibility(False)
            action_controls["commit"].enable()
            return
        await refresh_draft_components()

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
        }.get(state["resource"], state["resource"])
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
            spec.key, (auth_state.get("principal") or {}).get("global_privileges", [])
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
                        languages=(state.get("localization") or {}).get("supported_languages", []),
                        dialog=dialog, uses_external_reason=spec.key == "profiles",
                        get_external_reason=lambda: profile_change_reason,
                        error_message=error_message, show_api_error=show_api_error,
                    )

            if spec.key == "aggregations" and "security_level_id" in controls:
                configure_aggregation_parent_rules(controls, lookup_rows_by_field, creating, row, creation_configuration, aggregation_creation_role_status, api, error_message)

            if spec.key == "records" and "medium" in controls:
                aggregation_rows = lookup_rows_by_field.get("aggregation_id", [])

                def constrain_edited_record_medium() -> None:
                    parent = next(
                        (item for item in aggregation_rows
                         if item["id"] == controls["aggregation_id"].value),
                        None,
                    )
                    medium_control = controls["medium"]
                    if not parent:
                        return
                    parent_medium = parent.get("medium", "mixed")
                    if parent_medium == "mixed":
                        medium_control.set_options(
                            medium_options(), value=medium_control.value or "mixed",
                        )
                        medium_control.enable()
                    else:
                        medium_control.set_options(
                            {parent_medium: medium_options()[parent_medium]}, value=parent_medium,
                        )
                        medium_control.disable()
                    medium_control.update()

                controls["aggregation_id"].on_value_change(
                    lambda _: constrain_edited_record_medium()
                )
                constrain_edited_record_medium()

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
                        elif not spec.search_first and state["resource"] == spec.key:
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
                            state["searched"] = False
                            render_table(spec)
                    elif state["resource"] == spec.key:
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



    open_aggregation = build_aggregation_details(
        add_button=add_button,
        add_record_button=add_record_button,
        add_resource_to_hold_dialog=lambda *args, **kwargs: add_resource_to_hold_dialog(*args, **kwargs),
        aggregation_mode_bar=aggregation_mode_bar,
        aggregation_state=aggregation_state,
        api=api,
        bind_remote_relationship_select=lambda *args, **kwargs: bind_remote_relationship_select(*args, **kwargs),
        breadcrumb_back=lambda *args, **kwargs: breadcrumb_back(*args, **kwargs),
        browse_advanced_aggregation=lambda *args, **kwargs: browse_advanced_aggregation(*args, **kwargs),
        current_direction=current_direction,
        enter_details=lambda: state.__setitem__("resource", "aggregation-details"),
        error_message=error_message,
        favourite_button=lambda *args, **kwargs: favourite_button(*args, **kwargs),
        format_timestamp=format_timestamp,
        get_record_detail_id=lambda: state.get("record_detail_id"),
        get_relationship_page_token=lambda: state.get("relationship_page_token"),
        get_resource=lambda: state.get("resource"),
        guidance=guidance,
        hold_reason_dialog=lambda *args, **kwargs: hold_reason_dialog(*args, **kwargs),
        load_recent=lambda *args, **kwargs: load_recent(*args, **kwargs),
        localized_disposition_value=localized_disposition_value,
        medium_label=medium_label,
        open_editor=lambda *args, **kwargs: open_editor(*args, **kwargs),
        open_related_resource=lambda *args, **kwargs: open_related_resource(*args, **kwargs),
        principal=lambda: auth_state.get("principal"),
        register_navigation=lambda *args, **kwargs: register_navigation(*args, **kwargs),
        render_compact_resource_result=lambda *args, **kwargs: render_compact_resource_result(*args, **kwargs),
        restore_compact_result_anchor=lambda *args, **kwargs: restore_compact_result_anchor(*args, **kwargs),
        review_datetime_input_minimum=review_datetime_input_minimum,
        review_datetime_input_value=review_datetime_input_value,
        review_datetime_payload=review_datetime_payload,
        review_display=review_display,
        search_bar=search_bar,
        select_classification_workspace=lambda *args, **kwargs: select_classification_workspace(*args, **kwargs),
        select_entity=lambda *args, **kwargs: select_entity(*args, **kwargs),
        set_relationship_page_token=lambda token: state.__setitem__("relationship_page_token", token),
        show_access_explanation=lambda *args, **kwargs: show_access_explanation(*args, **kwargs),
        show_acl_editor=lambda *args, **kwargs: show_acl_editor(*args, **kwargs),
        show_authenticated_view=lambda *args, **kwargs: show_authenticated_view(*args, **kwargs),
        show_effective_holds_dialog=lambda *args, **kwargs: show_effective_holds_dialog(*args, **kwargs),
        show_entity_history=lambda *args, **kwargs: show_entity_history(*args, **kwargs),
        show_governed_move=lambda *args, **kwargs: show_governed_move(*args, **kwargs),
        show_ownership_correction=lambda *args, **kwargs: show_ownership_correction(*args, **kwargs),
        show_record_details=lambda *args, **kwargs: show_record_details(*args, **kwargs),
        show_reopen_aggregation=lambda *args, **kwargs: show_reopen_aggregation(*args, **kwargs),
        show_security_level_change=lambda *args, **kwargs: show_security_level_change(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )





    async def decorate_record_search_components(
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        async def context(record: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            try:
                capabilities = await api.resource_capabilities("records", int(record["id"]))
                components = (
                    (await api.component_page(int(record["id"]), limit=25))["items"]
                    if capabilities.get("list_components") else []
                )
                return capabilities, components
            except ApiError:
                return {}, []

        contexts = await asyncio.gather(*(context(record) for record in rows))
        return [
            {
                **record,
                "_record_capabilities": capabilities,
                "_components": components,
            }
            for record, (capabilities, components) in zip(rows, contexts)
        ]

    def render_entity_compact_results(spec: EntitySpec) -> None:
        resource = spec.key
        result_state = state.setdefault("entity_result_states", {}).setdefault(resource, {
            "filter": "", "sort": "number", "page": 1, "page_size": 10,
            "expanded_results": set(), "return_anchor": None,
        })
        result_state["expanded_results"] = set(result_state.get("expanded_results") or [])
        number_field = "aggregation_number" if resource == "aggregations" else "record_number"

        ui.separator().classes("erms-results-divider")
        with ui.row().classes("w-full items-center px-5 pt-2 gap-2"):
            ui.icon("search", color="primary")
            ui.label(render_message("webui.render_entity_compact_results.label.search_results_66d40806")).classes("text-lg font-semibold")
            ui.badge(str(len(state["rows"])), color="blue-grey").props("outline")

        controls = ui.row().classes("w-full items-end gap-3 px-5 pt-2 flex-wrap")
        with controls:
            filter_control = ui.input(
                render_message("webui.render_entity_compact_results.input.filter_results_bb36c793"), value=result_state.get("filter", ""),
            ).props("outlined dense clearable debounce=200").classes("grow min-w-[250px]")
            sort_control = ui.select(
                {"number": render_message("webui.render_entity_compact_results.select.number_13b108c8"), "title": render_message("webui.render_entity_compact_results.select.title_c402fbea"), "date": render_message("webui.render_entity_compact_results.select.date_originated_66ee2579") if resource == "records" else render_message("webui.render_entity_compact_results.select.date_opened_8e338da3"), "medium": render_message("webui.render_entity_compact_results.select.medium_d8693777")},
                value=result_state.get("sort", "number"), label=render_message("webui.render_entity_compact_results.select.sort_by_26eae3a9"),
            ).props("outlined dense options-dense").classes("w-44")
            page_size_control = ui.select(
                {10: "10", 25: "25", 50: "50", 100: "100"},
                value=int(result_state.get("page_size", 10)), label=render_message("webui.render_entity_compact_results.select.per_page_d6d26cbd"),
            ).props("outlined dense options-dense").classes("w-28")
        summary = ui.label().classes("text-sm text-slate-500 px-5")
        host = ui.column().classes("compact-result-list w-[calc(100%-2.5rem)] mx-5 gap-0")
        pager = ui.row().classes("w-full items-center justify-center gap-2 px-5 pb-5")
        with pager:
            first = ui.button(icon="first_page").props('flat round aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.first_page_99404add"))).tooltip(render_message("webui.render_entity_compact_results.tooltip.first_page_36860f7f"))
            previous = ui.button(icon="chevron_left").props('flat round aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.previous_page_2ba84275"))).tooltip(render_message("webui.render_entity_compact_results.tooltip.previous_page_e175a9ce"))
            page_label = ui.label().classes("text-sm text-slate-600 min-w-20 text-center")
            next_button = ui.button(icon="chevron_right").props('flat round aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.next_page_66adc3fc"))).tooltip(render_message("webui.render_entity_compact_results.tooltip.next_page_e62c6c59"))
            last = ui.button(icon="last_page").props('flat round aria-label=' + repr(render_message("webui.render_entity_compact_results.accessible_name.last_page_9a6fde18"))).tooltip(render_message("webui.render_entity_compact_results.tooltip.last_page_00e9ef30"))

        async def open_result(item: dict[str, Any]) -> None:
            result_state["return_anchor"] = f"compact-result-{resource}-{int(item['id'])}"
            if resource == "aggregations":
                await open_aggregation(item)
            else:
                await show_record_details(item)

        def render_results() -> None:
            query = str(filter_control.value or "").strip().casefold()
            result_state.update(filter=str(filter_control.value or ""), sort=sort_control.value,
                                page_size=int(page_size_control.value or 10))
            rows = list(state["rows"])
            if query:
                rows = [row for row in rows if query in " ".join(str(value or "") for value in (
                    row.get(number_field), row.get("title"), row.get("medium"),
                    (row.get("aggregation_display") or {}).get("code"),
                    (row.get("aggregation_display") or {}).get("name"),
                )).casefold()]
            sort_field = {"number": number_field, "title": "title", "date": "date_originated" if resource == "records" else "date_opened", "medium": "medium"}[sort_control.value]
            rows.sort(key=lambda row: str(row.get(sort_field) or "").casefold())
            page_size = int(page_size_control.value or 10)
            page_count = max(1, (len(rows) + page_size - 1) // page_size)
            result_state["page"] = min(max(1, int(result_state.get("page", 1))), page_count)
            page_number = result_state["page"]
            start = (page_number - 1) * page_size
            page_rows = rows[start:start + page_size]
            summary.text = render_message("webui.render_results.text.showing_value_value_2_of_row_count_results_3d5b1825", value=start + 1 if page_rows else 0, value_2=start + len(page_rows), row_count=len(rows))
            page_label.text = render_message("webui.render_results.text.page_page_number_of_page_count_1680e7c0", page_number=page_number, page_count=page_count)
            first.set_enabled(page_number > 1); previous.set_enabled(page_number > 1)
            next_button.set_enabled(page_number < page_count); last.set_enabled(page_number < page_count)
            host.clear()
            with host:
                if not page_rows:
                    ui.label(render_message("webui.render_results.label.no_matching_results_e67e2811")).classes("w-full text-center text-slate-500 py-8")
                for item in page_rows:
                    capabilities = item.get("_record_capabilities") or {}
                    components = item.get("_components") or []
                    render_compact_resource_result(
                        resource, item, on_open=open_result,
                        components=components, show_medium=True,
                        can_preview=bool(resource == "records" and capabilities.get("view_component") and any(component_is_previewable(component) for component in components)),
                        can_expand_components=bool(resource == "records" and capabilities.get("list_components") and components),
                        initially_expanded=f"{resource}:{int(item['id'])}" in result_state["expanded_results"],
                        on_expansion_changed=lambda expanded, identifier=int(item["id"]): (
                            result_state["expanded_results"].add(f"{resource}:{identifier}") if expanded
                            else result_state["expanded_results"].discard(f"{resource}:{identifier}")
                        ),
                    )
            restore_compact_result_anchor(result_state.pop("return_anchor", None))

        def set_page(page_number: int) -> None:
            result_state["page"] = page_number
            render_results()

        filter_control.on_value_change(lambda _: (result_state.__setitem__("page", 1), render_results()))
        sort_control.on_value_change(lambda _: (result_state.__setitem__("page", 1), render_results()))
        page_size_control.on_value_change(lambda _: (result_state.__setitem__("page", 1), render_results()))
        first.on("click", lambda: set_page(1)); previous.on("click", lambda: set_page(result_state["page"] - 1))
        next_button.on("click", lambda: set_page(result_state["page"] + 1)); last.on("click", lambda: set_page(10**9))
        render_results()

    def render_table(spec: EntitySpec) -> None:
        # Background personal-section refreshes do not inherit a NiceGUI slot.
        # Resolve translations in the owning page before updating its labels.
        with table_container:
            if spec.key in {"aggregations", "records"}:
                guidance.text = "" if state["searched"] else render_message(
                    "webui.select_entity.text.large_collections_are_search_first_to_avoi_717a0f77"
                )
                subtitle.text = "" if state["searched"] else render_message(
                    "webui.select_entity.text.search_required_before_loading_results_88549c49"
                )
        table_container.clear()
        with table_container:
            if spec.key in {"aggregations", "records"} and spec.search_first and not state["searched"]:
                render_resource_personal_sections(spec)
                return
            if spec.search_first and not state["searched"]:
                if spec.key == "classifications":
                    render_classification_search_prompt()
                    return
                render_recent_section(spec)
                return
            if spec.key in {"aggregations", "records"}:
                render_entity_compact_results(spec)
                render_resource_personal_sections(spec)
                return
            if spec.key == "aggregations":
                ui.separator().classes("erms-results-divider")
                with ui.row().classes("w-full items-center px-5 pt-2 gap-2"):
                    ui.icon("search", color="primary")
                    ui.label(render_message("webui.render_table.label.search_results_1bc0cdb3")).classes("text-lg font-semibold")
                    ui.badge(str(len(state["rows"])), color="blue-grey").props("outline")
            lifecycle_filter = None
            account_type_filter = None
            administration_filter = None
            visible_rows = state["rows"]
            result_filter = None
            if spec.key in {"security-levels", "profiles", "users", "roles", "org-units"}:
                render_governance_cards = render_administration_cards(spec)
                return
            if spec.key in {"aggregations", "records"}:
                with ui.row().classes("w-full items-center px-5 pt-2 gap-3"):
                    result_filter = ui.input(
                        render_message("webui.render_table.input.filter_displayed_results_126f56ec"),
                        placeholder=render_message("webui.render_table.input.type_to_filter_across_the_table_6a3e2810"),
                    ).props("outlined dense clearable debounce=250").classes("w-96 max-w-full")
                    ui.space()
                    ui.label(render_message("webui.render_table.label.visible_row_count_results_07a8f243", visible_row_count=len(visible_rows))).classes("text-sm text-slate-500")
            administration_filter, account_type_filter, lifecycle_filter = organization_table_filters(
                spec, lambda: state.get("lifecycle_filter", "all"),
                lambda: state.get("account_type_filter", "all"),
                lambda: state.update(lifecycle_filter="all"),
            )
            sortable_relationships = {"parent_org_unit_display", "org_unit_display", "profile_display"}
            localized_metadata_fields = (
                {"name", "description"}
                if spec.key in {"org-units", "roles", "users", "security-levels"}
                else {"title", "description"}
                if spec.key in {"classification-schemes", "classifications"}
                else set()
            )
            for row in visible_rows:
                localized = row.get("localized") or {}
                for metadata_field in localized_metadata_fields:
                    row[f"_localized_{metadata_field}"] = (
                        localized.get(metadata_field) or row.get(metadata_field)
                    )
                for relationship_key in sortable_relationships:
                    relationship = row.get(relationship_key) or {}
                    row[f"_{relationship_key}_sort"] = " ".join(
                        str(relationship.get(part) or "") for part in ("name", "code")
                    ).strip().casefold()
            columns = [
                {
                    "name": key,
                    "label": entity_metadata_label(label),
                    "field": (
                        f"_{key}_sort" if key in sortable_relationships
                        else f"_localized_{key}" if key in localized_metadata_fields
                        else key
                    ),
                    "align": "left",
                    "sortable": (
                        key != "_avatar"
                        and (not key.endswith("_display") or key in sortable_relationships)
                    ),
                }
                for key, label in spec.columns
            ]
            columns.append({"name": "actions", "label": "", "field": "actions", "align": "right"})
            if spec.key == "profiles":
                profile_widths = {
                    "code": "width: 150px",
                    "name": "width: 230px",
                    "description": "width: auto",
                    "is_system": "width: 110px",
                    "actions": "width: 150px",
                }
                for column in columns:
                    column["style"] = profile_widths.get(column["name"], "")
                    column["headerStyle"] = profile_widths.get(column["name"], "")
            if spec.key in {"aggregations", "records"}:
                for row in visible_rows:
                    row["_is_favourite"] = favourite_state(spec.key, row["id"])
            table = ui.table(
                columns=columns,
                rows=visible_rows,
                row_key="id",
                pagination={"rowsPerPage": 25},
            ).props(
                'flat bordered separator=horizontal :rows-per-page-options="[10,25,50,100]"'
            ).classes(
                "erms-page-table erms-profiles-table"
                if spec.key == "profiles" else "erms-page-table"
            )
            if result_filter is not None:
                table.bind_filter_from(result_filter, "value")
            if administration_filter is not None:
                def searchable_text(value: Any) -> str:
                    if isinstance(value, dict):
                        return " ".join(searchable_text(item) for item in value.values())
                    if isinstance(value, (list, tuple)):
                        return " ".join(searchable_text(item) for item in value)
                    return "" if value is None else str(value)

                def apply_administration_filters() -> None:
                    state["lifecycle_filter"] = lifecycle_filter.value
                    if account_type_filter is not None:
                        state["account_type_filter"] = account_type_filter.value
                    query = (administration_filter.value or "").strip().casefold()
                    selected_status = lifecycle_filter.value
                    selected_account_type = (
                        account_type_filter.value if account_type_filter is not None else "all"
                    )
                    table.rows = [
                        row for row in state["rows"]
                        if (
                            selected_status == "all"
                            or row.get("effective_status", row.get("status")) == selected_status
                        )
                        and (
                            selected_account_type == "all"
                            or row.get("account_type") == selected_account_type
                        )
                        and (
                            not query
                            or query in " ".join(
                                searchable_text(
                                    (row.get("localized") or {}).get(key) or row.get(key)
                                ).casefold()
                                for key, _ in spec.columns
                                if key != "_avatar"
                            )
                        )
                    ]
                    table.update()

                administration_filter.on_value_change(apply_administration_filters)
                lifecycle_filter.on_value_change(apply_administration_filters)
                if account_type_filter is not None:
                    account_type_filter.on_value_change(apply_administration_filters)
                apply_administration_filters()
            add_timestamp_slots(
                table, [key for key, _ in spec.columns if key.startswith("date_")]
            )
            organization_user_slots(spec, table)
            if spec.key == "profiles":
                table.add_slot("body-cell-name", '''
                    <q-td :props="props">
                      <div class="ellipsis">{{ props.value }}</div>
                      <q-tooltip>{{ props.value }}</q-tooltip>
                    </q-td>
                ''')
                table.add_slot("body-cell-description", '''
                    <q-td :props="props" class="profile-description-cell">
                      {{ props.value || '—' }}
                      <q-tooltip>{{ props.value || 'No description' }}</q-tooltip>
                    </q-td>
                ''')
                table.add_slot("body-cell-is_system", '''
                    <q-td :props="props">
                      <q-badge
                        :color="props.value ? 'blue-grey-7' : 'grey-5'"
                        :label="props.value ? 'Built-in' : 'Custom'"
                        outline
                      >
                        <q-tooltip>
                          {{ props.value
                            ? 'Supplied by Wathiq. It cannot be deleted and its code cannot be renamed.'
                            : 'Created by your organization.' }}
                        </q-tooltip>
                      </q-badge>
                    </q-td>
                ''')
            for key, _ in spec.columns:
                if not key.endswith("_display"):
                    continue
                if key == "type_display":
                    table.add_slot("body-cell-type_display", """
                        <q-td :props="props">
                          <div class="row items-center no-wrap q-gutter-sm">
                            <q-avatar size="30px" color="blue-1" text-color="primary" :icon="props.row.is_terminal ? 'label' : 'schema'" />
                            <span class="text-weight-medium">{{ props.row.is_terminal ? 'Terminal' : 'Branch' }}</span>
                          </div>
                        </q-td>
                    """)
                    continue
                if key not in RELATIONSHIP_DISPLAY_FIELDS:
                    continue
                relationship_icon = {
                    "parent_org_unit_display": "corporate_fare",
                    "org_unit_display": "corporate_fare",
                    "aggregation_display": "folder",
                    "scheme_display": "account_tree",
                    "profile_display": "admin_panel_settings",
                }.get(key, "link")
                relationship_template = """
                    <q-td :props="props">
                      <div v-if="props.row.__FIELD__" class="row items-center no-wrap q-gutter-sm">
                        <q-avatar size="30px" color="blue-1" text-color="primary" icon="__ICON__" />
                        <div class="column">
                          <span class="text-weight-medium relationship-cell-name">{{ props.row.__FIELD__.name }}</span>
                          <q-badge v-if="props.row.__FIELD__.code" outline color="primary" :label="props.row.__FIELD__.code" class="self-start" />
                        </div>
                      </div>
                      <span v-else class="text-grey-5">—</span>
                    </q-td>
                """.replace("__ICON__", relationship_icon).replace("__FIELD__", key)
                if key == "profile_display":
                    relationship_template = relationship_template.replace(
                        '<q-badge v-if="props.row.__FIELD__.code" outline color="primary" :label="props.row.__FIELD__.code" class="self-start" />'.replace("__FIELD__", key),
                        '<q-badge v-if="props.row.profile_display.code" outline :color="props.row.profile_display.code === \'ALL_PRIVS\' ? \'warning\' : \'primary\'" :label="props.row.profile_display.code === \'ALL_PRIVS\' ? \'Compatibility profile\' : props.row.profile_display.code" class="self-start"><q-tooltip v-if="props.row.profile_display.code === \'ALL_PRIVS\'">Review and replace with a purpose-specific profile</q-tooltip></q-badge>',
                    )
                table.add_slot(f"body-cell-{key}", relationship_template)
            if any(key == "effective_status" for key, _ in spec.columns):
                table.add_slot("body-cell-effective_status", '''
                    <q-td :props="props">
                      <q-badge
                        :color="props.value === 'active' ? 'positive' : (props.value === 'suspended' ? 'warning' : 'grey-7')"
                        :label="props.value"
                      ><q-tooltip>{{ props.row._inactive_reason }}</q-tooltip></q-badge>
                    </q-td>
                ''')
            if any(key == "status" for key, _ in spec.columns):
                table.add_slot("body-cell-status", '''
                    <q-td :props="props">
                      <q-badge
                        :color="props.value === 'active' ? 'positive' : (props.value === 'suspended' ? 'warning' : 'grey-7')"
                        :label="props.value"
                      />
                    </q-td>
                ''')
            if spec.key in {"records", "aggregations"}:
                buttons = '<q-btn flat round dense :icon="props.row._is_favourite ? \'favorite\' : \'favorite_border\'" :color="props.row._is_favourite ? \'red\' : \'primary\'" :aria-label="props.row._is_favourite ? \'Remove from favourites\' : \'Add to favourites\'" @click.stop="$parent.$emit(\'toggle_favourite\', props.row)"><q-tooltip>{{ props.row._is_favourite ? \'Remove from favourites\' : \'Add to favourites\' }}</q-tooltip></q-btn>'
            elif spec.key in {"privileges", "permissions"}:
                buttons = ''
            else:
                buttons = '<q-btn flat round dense icon="edit" color="primary" @click="$parent.$emit(\'edit\', props.row)"><q-tooltip>Edit</q-tooltip></q-btn>'
            buttons = organization_leading_actions(spec, buttons)
            if spec.key not in {"privileges", "permissions"}:
                buttons += '<q-btn flat round dense icon="history" color="blue-grey" @click="$parent.$emit(\'history\', props.row)"><q-tooltip>Event history</q-tooltip></q-btn>'
            if spec.key == "records":
                buttons = '<q-btn flat round dense icon="open_in_new" color="primary" @click="$parent.$emit(\'open_record\', props.row)"><q-tooltip>Open record</q-tooltip></q-btn>' + buttons
                buttons += '<q-btn flat round dense icon="attach_file" color="secondary" @click="$parent.$emit(\'components\', props.row)"><q-tooltip>Digital components</q-tooltip></q-btn>'
            if spec.key == "aggregations":
                buttons = '<q-btn flat round dense icon="folder_open" color="secondary" @click="$parent.$emit(\'open_aggregation\', props.row)"><q-tooltip>Open aggregation</q-tooltip></q-btn>' + buttons
                buttons += '<q-btn v-if="props.row._directly_closed" flat round dense icon="lock_open" color="primary" @click="$parent.$emit(\'reopen\', props.row)"><q-tooltip>Reopen aggregation</q-tooltip></q-btn>'
            buttons = organization_membership_action(spec, buttons)
            if spec.key == "profiles":
                buttons += '<q-btn flat round dense icon="key" color="secondary" @click="$parent.$emit(\'profile_privileges\', props.row)"><q-tooltip>Manage privileges</q-tooltip></q-btn>'
            buttons = organization_user_actions(spec, buttons)
            buttons = organization_lifecycle_actions(spec, buttons)
            if spec.key == "classification-schemes":
                buttons = scheme_action_buttons(buttons)
            table.add_slot("body-cell-actions", f'<q-td :props="props">{buttons}</q-td>')
            table.on("edit", lambda event: open_editor(event.args))
            table.on("history", lambda event, resource=spec.key: show_entity_history(resource, event.args))
            if spec.key == "profiles":
                table.on("profile_privileges", lambda event: show_profile_privilege_editor(event.args))
            bind_organization_table_destinations(spec, table, select_organization_unit_details, select_role_details)
            if spec.key in {"aggregations", "records"}:
                async def toggle_table_favourite(event) -> None:
                    row = event.args
                    selected = await toggle_favourite(spec.key, row["id"])
                    for table_row in table.rows:
                        if table_row["id"] == row["id"]:
                            table_row["_is_favourite"] = selected
                            break
                    table.update()
                    if spec.key in {"aggregations", "records"}:
                        await reload_favourites()
                        render_table(spec)
                table.on("toggle_favourite", toggle_table_favourite)
            if spec.key == "records":
                table.on("open_record", lambda event: show_record_details(event.args))
                table.on("components", lambda event: show_components(event.args))
            if spec.key == "aggregations":
                table.on("open_aggregation", lambda event: open_aggregation(event.args))
                async def reopen_from_table(event) -> None:
                    row = event.args
                    async def reopened(_: dict[str, Any]) -> None:
                        await load_recent(spec)
                        if state["searched"]:
                            await load_rows(
                        repeat_search=True, on_loaded=render_governance_cards,
                        is_current=lambda: not card_host.is_deleted,
                    )
                        else:
                            render_table(spec)

                    await show_reopen_aggregation(row, reopened)
                table.on("reopen", reopen_from_table)
            if spec.key == "classification-schemes":
                bind_scheme_actions(
                    table, api=api, error_message=error_message,
                    refresh=lambda: load_rows(
                        repeat_search=True, on_loaded=render_governance_cards,
                        is_current=lambda: not card_host.is_deleted,
                    ),
                )
            if spec.key in {"users", "roles"}:
                table.on(
                    "memberships",
                    lambda event, user_view=spec.key == "users": show_memberships(
                        event.args, for_user=user_view
                    ),
                )
            if spec.key == "users":
                table.on("open_user", lambda event: select_user_details(event.args["id"]))
                issue_password = build_issue_password(
                    api=api,
                    error_message=error_message,
                    format_timestamp=format_timestamp,
                )
                table.on("temporary_password", issue_password)
                change_suspension = build_change_suspension(
                    api=api,
                    current_session_revoked=current_session_revoked,
                    decorate_for_spec=decorate_for_spec,
                    get_principal=lambda: auth_state["principal"],
                    get_rows=lambda: state["rows"],
                    render_table=render_table,
                    set_rows=lambda rows: state.update(rows=rows),
                    show_api_error=show_api_error,
                    spec=spec,
                )

                table.on("suspend_user", lambda event: change_suspension(event, suspended=True))
                table.on("unsuspend_user", lambda event: change_suspension(event, suspended=False))
            if spec.key in {"org-units", "roles", "users"}:
                confirm_lifecycle = build_confirm_lifecycle(
                    api=api,
                    current_session_revoked=current_session_revoked,
                    decorate_for_spec=decorate_for_spec,
                    get_principal=lambda: auth_state["principal"],
                    get_rows=lambda: state["rows"],
                    render_table=render_table,
                    set_rows=lambda rows: state.update(rows=rows),
                    show_api_error=show_api_error,
                    spec=spec,
                )
                table.on("lifecycle", confirm_lifecycle)

    (clear_translation_inspector_session, synchronize_translation_inspector,
     toggle_translation_inspector, open_inspected_translation) = build_translation_inspector(
        page_client=page_client, principal=lambda: auth_state.get("principal"),
        brand_row=brand_row, brand_mark=brand_mark, brand_name=brand_name,
        diagnostics_separator=diagnostics_separator, diagnostics_section=diagnostics_section,
        inspector_switch=inspector_switch, user_menu=user_menu,
        guarded_page_navigation=lambda callback: guarded_page_navigation(callback),
        select_translation_administration=lambda **kwargs: select_translation_administration(**kwargs),
    )




    inspector_switch.on_value_change(toggle_translation_inspector)


    refresh_hold_navigation = build_hold_navigation(
        api=api,
        principal=lambda: auth_state.get("principal"),
        holds_navigation=holds_navigation,
        refresh_drawer_headings=refresh_drawer_headings,
    )


    sign_out = session.sign_out

    def enter_login_sessions(user_id: int | None) -> None:
        if user_id is None:
            register_navigation("login-sessions", "Login sessions")
        show_authenticated_view()
        state.update(resource='login-sessions', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
        title.text = render_message("webui.select_login_sessions.text.login_sessions_06291138")
        subtitle.text = (
            render_message("webui.select_login_sessions.text.review_and_revoke_sessions_for_the_selecte_eab5be28")
            if user_id is not None else render_message("webui.select_login_sessions.text.review_and_revoke_authenticated_sessions_32f7dec7")
        )
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        guidance.text = ""
        table_container.clear()

    def current_session_revoked() -> None:
        app.storage.user.pop("session_token", None)
        api.set_session_token(None)
        clear_signed_in_identity()
        login_dialog.open()

    async def select_dashboard() -> None:
        dashboard_principal = auth_state.get("principal")
        dashboard_key = dashboard_session_key()
        if dashboard_key is None:
            return
        dashboard_view_token = object()
        state["dashboard_view_token"] = dashboard_view_token
        if state.get("dashboard_summary_cache_key") != dashboard_key:
            state.pop("dashboard_summary_cache", None)
            state.pop("dashboard_summary_cache_key", None)
        register_navigation("dashboard", render_message("navigation.item.dashboard"))
        show_authenticated_view()
        state.update(resource='dashboard', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
        title.text = render_message("navigation.item.dashboard")
        subtitle.text = render_message("dashboard.subtitle")
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        guidance.text = ""
        table_container.clear()
        with table_container:
            dashboard_content = ui.column().classes("w-full px-5 pb-5 pt-0 gap-4")
        dashboard_load_state = {"running": False}
        dashboard_refresh_controls: dict[str, Any] = {"button": None}

        def dashboard_session_is_current() -> bool:
            return (
                auth_state.get("principal") is dashboard_principal
                and dashboard_session_key() == dashboard_key
                and state.get("dashboard_view_token") is dashboard_view_token
                and not getattr(page_client, "_deleted", False)
                and page_client.has_socket_connection
            )

        def dashboard_view_is_current() -> bool:
            return (
                dashboard_session_is_current()
                and state.get("resource") == "dashboard"
                and not dashboard_content.is_deleted
            )

        def dashboard_medium_label(medium: str, count: int) -> str:
            if medium == "physical":
                return render_message("dashboard.medium.physical", count=count)
            if medium == "digital":
                return render_message("dashboard.medium.digital", count=count)
            return render_message("dashboard.medium.mixed", count=count)

        def dashboard_attention_label(metric: str, count: int) -> str:
            if metric == "vital":
                return render_message("dashboard.metric.vital", count=count)
            return render_message("dashboard.metric.held", count=count)

        def dashboard_aggregation_status_label(status: str, count: int) -> str:
            if status == "open":
                return render_message("dashboard.metric.open", count=count)
            return render_message("dashboard.metric.closed", count=count)

        def dashboard_resource_type(resource: str) -> str:
            if resource == "aggregations":
                return render_message("dashboard.resource.aggregation")
            return render_message("dashboard.resource.record")

        async def open_dashboard_resource(resource: str, item: dict[str, Any]) -> None:
            if not dashboard_session_is_current():
                return
            try:
                entity = await api.get(resource, item["id"])
                if not dashboard_session_is_current():
                    return
                if resource == "aggregations":
                    await open_aggregation(entity)
                else:
                    await show_record_details(entity)
            except ApiError as error:
                if not dashboard_session_is_current():
                    return
                ui.notify(error_message(error), color="negative", close_button=True)

        async def show_unclassified_roots() -> None:
            await select_entity("aggregations")
            try:
                # The API evaluates this against the true stored parent before
                # response redaction; a concealed parent is not a root.
                result = await api.search_request("aggregations", {
                    "where": {"and": [
                        {"field": "parent_aggregation_id", "operator": "is_null"},
                        {"field": "classification_id", "operator": "is_null"},
                    ]},
                    "sort": [{"field": "date_created", "direction": "desc"}],
                    "limit": 100,
                })
                state["rows"] = await decorate_for_spec(
                    ENTITIES["aggregations"], result["items"],
                )
                state["searched"] = True
                subtitle.text = render_message("webui.show_unclassified_roots.text.root_aggregations_missing_a_governing_clas_b4fc46cb")
                guidance.text = (
                    render_message("webui.show_unclassified_roots.text.showing_row_count_of_total_unclassified_ro_823f8b47", row_count=len(state['rows']), total=result['total'])
                )
                render_table(ENTITIES["aggregations"])
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)

        async def show_all_reviews(review_kind: str) -> None:
            if not dashboard_view_is_current():
                return
            register_navigation(
                "dashboard", f"{review_kind.title()} reviews", dynamic_label=True,
            )
            title.text = render_message("webui.show_all_reviews.text.title_reviews_bd68819e", title=review_kind.title())
            subtitle.text = render_message("webui.show_all_reviews.text.governance_review_reminders_for_holdings_o_05bb2c0c")
            table_container.clear()
            page = {"offset": 0, "limit": 25, "loading": False}
            with table_container, ui.column().classes("w-full p-5 gap-3"):
                with ui.row().classes("w-full items-center"):
                    ui.button(render_message("webui.show_all_reviews.button.back_to_dashboard_7f5aab05"), icon="arrow_back", on_click=select_dashboard).props("flat no-caps")
                    ui.space()
                    page_badge = ui.badge(color="negative" if review_kind == "overdue" else "warning").props("outline")
                results_host = ui.column().classes("w-full gap-3")
                with ui.row().classes("w-full items-center justify-end gap-1"):
                    previous_page = ui.button(icon="chevron_left").props("flat round dense")
                    page_label = ui.label().classes("text-sm text-slate-500 min-w-24 text-center")
                    next_page = ui.button(icon="chevron_right").props("flat round dense")

            async def load_review_page() -> None:
                if not dashboard_session_is_current() or results_host.is_deleted or page["loading"]:
                    return
                page["loading"] = True
                previous_page.props(add="disable")
                next_page.props(add="disable")
                results_host.clear()
                with results_host, ui.row().classes("w-full justify-center py-8"):
                    ui.spinner("dots", size="28px")
                try:
                    fetched = await api.dashboard_reviews(
                        review_kind, limit=page["limit"], offset=page["offset"],
                    )
                    if not dashboard_session_is_current() or results_host.is_deleted:
                        return
                    has_more = len(fetched) > page["limit"]
                    items = fetched[:page["limit"]]
                    results_host.clear()
                    with results_host:
                        if not items:
                            ui.label(render_message("webui.show_all_reviews.label.no_matching_review_reminders_d8ec16f5")).classes("text-slate-500")
                        for item in items:
                            resource = "aggregations" if item["entity_type"] == "aggregation" else "records"
                            number = item.get("aggregation_number") or item.get("record_number")
                            with ui.card().classes(
                                "recent-card cursor-pointer w-full shadow-none border border-slate-200 p-3"
                            ).on(
                                "click", lambda _, row=item, kind=resource: open_dashboard_resource(
                                    kind, {"id": row["entity_id"]},
                                ),
                            ):
                                with ui.row().classes("w-full items-center gap-3"):
                                    ui.icon("folder" if resource == "aggregations" else "description", color="primary")
                                    with ui.column().classes("gap-0 grow min-w-0"):
                                        ui.label(item["title"]).classes("font-semibold")
                                        ui.label(render_message("webui.show_all_reviews.label.number_review_display_82a23fd9", number=number, review_display=review_display(item['date_of_next_review']))).classes("text-xs text-slate-500")
                    page_number = page["offset"] // page["limit"] + 1
                    page_badge.text = str(len(items))
                    page_label.text = render_message(
                        "webui.render_global_search_results.label.page_page_number_9319ded9",
                        page_number=page_number,
                    )
                    previous_page.set_enabled(page["offset"] > 0)
                    next_page.set_enabled(has_more)
                except asyncio.CancelledError:
                    return
                except ApiError as error:
                    if not dashboard_session_is_current() or results_host.is_deleted:
                        return
                    results_host.clear()
                    with results_host:
                        ui.label(error_message(error)).classes("text-negative")
                finally:
                    page["loading"] = False

            async def move_review_page(direction: int) -> None:
                page["offset"] = max(0, page["offset"] + direction * page["limit"])
                await load_review_page()

            previous_page.on("click", lambda: move_review_page(-1))
            next_page.on("click", lambda: move_review_page(1))
            await load_review_page()

        async def load_dashboard(
            *, summary_override: dict[str, Any] | None = None,
            refresh_only: bool = False,
        ) -> None:
            if not dashboard_view_is_current() or dashboard_load_state["running"]:
                return
            dashboard_load_state["running"] = True
            refresh_button = dashboard_refresh_controls.get("button")
            if refresh_only and refresh_button is not None:
                refresh_button.props(add="loading disable")
            elif summary_override is None:
                dashboard_content.clear()
                with dashboard_content:
                    with ui.row().classes("dashboard-overview-heading w-full items-center"):
                        ui.label(render_message("webui.load_dashboard.label.overview_c59db7d5")).classes("text-lg font-semibold")
                        ui.space()
                        ui.button(
                            render_message("webui.load_dashboard.button.refresh_938d7997"),
                            icon="refresh",
                        ).props("flat dense no-caps color=primary disable")
                    with ui.row().classes("w-full items-center justify-center py-12 gap-2"):
                        ui.spinner("dots", size="32px")
                        ui.label(render_message("webui.load_dashboard.label.loading_dashboard_30b6a7ab")).classes("text-slate-500")

            try:
                privileges = set(auth_state["principal"].get("global_privileges", []))
                can_classify = "classifications.administer" in privileges
                can_organize = "organization.administer" in privileges
                can_administer_users = "identity.users.administer" in privileges

                if summary_override is None:
                    summary = await api.dashboard_summary(recent_limit=50)
                    # Check ownership before any cache write or UI/config update.
                    if not dashboard_view_is_current():
                        return
                    state["dashboard_summary_cache"] = summary
                    state["dashboard_summary_cache_key"] = dashboard_key
                else:
                    summary = summary_override
                if not dashboard_view_is_current():
                    return
                accept_application_configuration(summary["application_configuration"])
                recent_limit = dashboard_recent_item_limit(summary["application_configuration"])
                recent_days = dashboard_recent_days(summary["application_configuration"])
                counts = summary["overview_counts"]
                medium_counts = summary["overview_medium_counts"]
                attention_counts = summary["overview_resource_attention_counts"]
                aggregation_status_counts = summary["overview_aggregation_status_counts"]
                component_metrics = summary["overview_digital_component_metrics"]
                metrics = summary["classification_metrics"]
                published_scheme_count = int(metrics["published_scheme_count"])
                draft_scheme_count = int(metrics["draft_scheme_count"])
                inactive_scheme_count = int(metrics["inactive_scheme_count"])
                branch_count = int(metrics["branch_count"])
                terminal_count = int(metrics["terminal_count"])
                assignable_terminal_count = int(metrics["assignable_terminal_count"])
                draft_terminal_count = int(metrics["draft_terminal_count"])
                inactive_classification_count = int(metrics["inactive_classification_count"])
                unclassified_root_count = int(summary["unclassified_root_count"])
                ownership_counts = summary["ownership_counts"]
                favourites = summary["favourites"]
                personal.favourites = favourites
                personal.favourite_ids = {
                    resource: {int(item["id"]) for item in favourites[resource]}
                    for resource in ("aggregations", "records")
                }
                activity = summary["recent_activity"]
                def recent_record_entries(
                    source_activity: list[dict[str, Any]], *, limit: int | None = None,
                ) -> list[dict[str, Any]]:
                    entries = [
                        {
                            "id": item["entity_id"],
                            "title": item["title"],
                            "record_number": item.get("record_number"),
                            "_activity_at": item["occurred_at"],
                            "_operation": item["operation"],
                        }
                        for item in source_activity
                        if item["entity_type"] == "record"
                        and item["operation"] in {"CREATE", "UPDATE", "CONTENT_VIEWED"}
                    ]
                    return entries if limit is None else entries[:limit]

                all_recent_records = recent_record_entries(activity)
                recent_records = all_recent_records[:recent_limit]
                favourite_limit = dashboard_favourite_item_limit(state["application_configuration"])
            except ApiError as error:
                if not dashboard_view_is_current():
                    return
                if error.status_code == 401:
                    set_connection_status(True)
                    return
                if refresh_only:
                    # A failed refresh must not destroy this identity's last
                    # authorized snapshot or the working Refresh control.
                    with dashboard_content:
                        ui.notify(error_message(error), color="negative", close_button=True)
                else:
                    dashboard_content.clear()
                    with dashboard_content:
                        ui.label(error_message(error)).classes("text-negative p-5")
                set_connection_status(False)
                return
            finally:
                dashboard_load_state["running"] = False
                if (
                    dashboard_view_is_current()
                    and refresh_button is not None
                    and not getattr(refresh_button, "_deleted", False)
                ):
                    refresh_button.props(remove="loading disable")

            if not dashboard_view_is_current():
                return
            dashboard_content.clear()
            with dashboard_content:
                with ui.row().classes("w-full items-center"):
                    ui.label(render_message("webui.load_dashboard.label.overview_c59db7d5")).classes("text-lg font-semibold")
                    ui.space()
                    dashboard_refresh_controls["button"] = ui.button(
                        render_message("webui.load_dashboard.button.refresh_938d7997"),
                        icon="refresh",
                        on_click=lambda: load_dashboard(refresh_only=True),
                    ).props("flat dense no-caps color=primary")
                with ui.element("div").classes("dashboard-overview-primary w-full"):
                    for resource, label, icon, handler in (
                        ("aggregations", render_message("navigation.item.aggregations"), "folder", lambda: select_entity("aggregations")),
                        ("records", render_message("navigation.item.records"), "description", lambda: select_entity("records")),
                    ):
                        with ui.card().classes(
                            "dashboard-overview-primary-card cursor-pointer"
                        ).on("click", lambda _, action=handler: action()):
                            with ui.row().classes("dashboard-overview-card-heading w-full items-center no-wrap gap-3"):
                                with ui.element("div").classes("dashboard-overview-icon"):
                                    ui.icon(icon, size="20px")
                                with ui.column().classes("gap-0 min-w-0"):
                                    ui.label(label).classes("text-sm font-semibold text-slate-700")
                                    ui.label(render_message("webui.load_dashboard.label.visible_to_you_16b9d228")).classes("text-[11px] text-slate-500")
                                ui.space()
                                ui.label(str(counts[resource])).classes(
                                    "text-xl font-bold text-slate-800 tabular-nums"
                                )
                            with ui.element("div").classes("dashboard-overview-mediums"):
                                for medium, medium_icon in (
                                    ("physical", "inventory_2"),
                                    ("digital", "cloud"),
                                    ("mixed", "join_inner"),
                                ):
                                    with ui.element("span").classes("dashboard-overview-medium"):
                                        ui.icon(medium_icon, size="13px").classes("text-primary")
                                        ui.label(
                                            dashboard_medium_label(medium,medium_counts[resource][medium])
                                        ).classes("tabular-nums")
                                ui.label("|").classes("dashboard-overview-separator").props(
                                    "aria-hidden=true"
                                )
                                for metric, metric_icon in (("vital", "emergency"), ("held", "gavel")):
                                    with ui.element("span").classes("dashboard-overview-signal"):
                                        ui.icon(metric_icon, size="13px").classes(
                                            "text-red-600" if metric == "vital" else "text-amber-600"
                                        )
                                        ui.label(
                                            dashboard_attention_label(metric,attention_counts[resource][metric])
                                        ).classes("font-semibold tabular-nums")
                                if resource == "aggregations":
                                    for status, status_color in (
                                        ("open", "text-green-700"),
                                        ("closed", "text-slate-500"),
                                    ):
                                        with ui.element("span").classes(
                                            f"dashboard-overview-signal {status_color}"
                                        ):
                                            ui.label(
                                                dashboard_aggregation_status_label(status,aggregation_status_counts[status])
                                            ).classes("font-semibold tabular-nums")
                                else:
                                    with ui.element("span").classes("dashboard-overview-signal"):
                                        ui.icon("attachment", size="13px").classes("text-primary")
                                        ui.label(
                                            render_message("dashboard.metric.components",count=component_metrics["component_count"])
                                        ).classes("font-semibold tabular-nums")
                                    with ui.element("span").classes("dashboard-overview-signal"):
                                        ui.icon("storage", size="13px").classes("text-primary")
                                        ui.label(
                                            format_file_size(component_metrics["storage_size_in_bytes"])
                                        ).classes("font-semibold tabular-nums")

                administration_items = []
                if can_classify:
                    administration_items.extend((
                        ("classification-schemes", render_message("navigation.item.classification_schemes"), "account_tree", select_classification_workspace),
                        ("classifications", render_message("dashboard.admin.classifications"), "schema", select_classification_workspace),
                    ))
                if "holds.administer" in privileges:
                    administration_items.append(
                        ("holds", render_message("navigation.item.holds"), "gavel", select_holds),
                    )
                if can_organize:
                    administration_items.extend((
                        ("org-units", render_message("navigation.item.org_units"), "corporate_fare", lambda: select_entity("org-units")),
                        ("roles", render_message("navigation.item.roles"), "badge", lambda: select_entity("roles")),
                    ))
                if can_administer_users:
                    administration_items.append(
                        ("users", render_message("navigation.item.users"), "group", lambda: select_entity("users")),
                    )
                if administration_items:
                    with ui.element("div").classes("dashboard-overview-admin"):
                        for resource, label, icon, handler in administration_items:
                            with ui.element("div").classes(
                                "dashboard-overview-admin-item"
                            ).on("click", lambda _, action=handler: action()):
                                ui.icon(icon, size="17px").classes("text-primary shrink-0")
                                ui.label(label).classes(
                                    "text-xs font-medium text-slate-600 truncate min-w-0"
                                ).tooltip({
                                    "classification-schemes": render_message("navigation.item.classification_schemes"),
                                    "org-units": render_message("navigation.item.org_units"),
                                }.get(resource, label))
                                ui.space()
                                ui.label(str(counts[resource])).classes(
                                    "text-sm font-bold text-slate-800 tabular-nums"
                                )

                attention_maximum = max(
                    1,
                    attention_counts["aggregations"]["vital"],
                    attention_counts["aggregations"]["held"],
                    attention_counts["records"]["vital"],
                    attention_counts["records"]["held"],
                )
                with ui.element("section").classes("dashboard-attention-chart").props(
                    'aria-label=' + repr(render_message("webui.load_dashboard.accessible_name.attention_signals_for_visible_aggregations_c8c49e94"))
                ):
                    with ui.row().classes("classification-detail-identity w-full items-start gap-3"):
                        with ui.column().classes("gap-0"):
                            ui.label(render_message("webui.load_dashboard.label.attention_signals_71bf1d51")).classes(
                                "text-sm font-semibold text-slate-700"
                            )
                            ui.label(
                                render_message("webui.load_dashboard.label.visible_vital_and_effectively_held_resourc_b027ff42")
                            ).classes("text-xs text-slate-500")
                        ui.space()
                        with ui.element("div").classes("dashboard-chart-legend"):
                            for label, color in ((render_message("dashboard.legend.vital"), "#d85a6d"), (render_message("dashboard.legend.on_hold"), "#d99b32")):
                                with ui.element("span").classes("dashboard-chart-legend-item"):
                                    ui.element("i").classes("dashboard-chart-swatch").style(
                                        f"background: {color}"
                                    )
                                    ui.label(label)
                    with ui.element("div").classes("dashboard-attention-plot"):
                        ui.label(render_message("webui.load_dashboard.label.number_of_items_3b9e348e")).classes("dashboard-attention-axis-label")
                        for resource, label in (
                            ("aggregations", render_message("navigation.item.aggregations")),
                            ("records", render_message("navigation.item.records")),
                        ):
                            with ui.element("div").classes("dashboard-attention-group"):
                                for metric, color in (("vital", "#d85a6d"), ("held", "#d99b32")):
                                    value = int(attention_counts[resource][metric])
                                    height = round((value / attention_maximum) * 112)
                                    with ui.element("div").classes(
                                        "dashboard-attention-bar"
                                    ).style(f"height: {height}px; background: {color}").props(
                                        f"aria-label='{label} {metric}: {value}'"
                                    ):
                                        ui.label(str(value)).classes(
                                            "dashboard-attention-bar-value"
                                        )
                                ui.label(label).classes("dashboard-attention-group-label")

                personal_sections_area = ui.element("div").classes("w-full")

                with ui.row().classes("w-full items-center mt-2"):
                    ui.label(render_message("webui.load_dashboard.label.holdings_by_organizational_unit_342445f5")).classes("text-lg font-semibold")
                    ui.space()
                    unit_count = len(ownership_counts)
                    ui.label(render_message("dashboard.count.units",count=unit_count)).classes(
                        "text-xs text-slate-500"
                    )
                ui.label(
                    render_message("webui.load_dashboard.label.only_units_where_you_have_an_effective_rol_68aa4c10")
                ).classes("text-sm leading-5 text-slate-500 -mt-1")
                if ownership_counts:
                    holdings_maximum = max(
                        1, *(int(item["record_count"]) for item in ownership_counts)
                    )
                    with ui.element("section").classes("dashboard-holdings-chart").props(
                        'aria-label=' + repr(render_message("webui.load_dashboard.accessible_name.records_by_organizational_unit_and_medium_a855d0ad"))
                    ):
                        with ui.row().classes("w-full items-start gap-3"):
                            with ui.column().classes("gap-0"):
                                ui.label(render_message("webui.load_dashboard.label.records_by_medium_92e62b20")).classes(
                                    "text-sm font-semibold text-slate-700"
                                )
                                ui.label(
                                    render_message("webui.load_dashboard.label.compare_record_volume_and_medium_mix_acros_3295a6ca")
                                ).classes("text-xs text-slate-500")
                            ui.space()
                            with ui.element("div").classes("dashboard-chart-legend"):
                                for label, color in (
                                    (render_message("dashboard.legend.physical"), "#356fb1"),
                                    (render_message("dashboard.legend.digital"), "#39a19f"),
                                    (render_message("dashboard.legend.mixed"), "#9cbfe5"),
                                ):
                                    with ui.element("span").classes(
                                        "dashboard-chart-legend-item"
                                    ):
                                        ui.element("i").classes(
                                            "dashboard-chart-swatch"
                                        ).style(f"background: {color}")
                                        ui.label(label)
                        with ui.element("div").classes("dashboard-holdings-chart-rows"):
                            for owner_count in ownership_counts:
                                record_count = int(owner_count["record_count"])
                                overall_width = (record_count / holdings_maximum) * 100
                                with ui.element("div").classes(
                                    "dashboard-holdings-chart-row"
                                ):
                                    ui.label(owner_count["org_unit_name"]).classes(
                                        "dashboard-holdings-chart-name"
                                    ).tooltip(owner_count["org_unit_name"])
                                    with ui.element("div").classes(
                                        "dashboard-holdings-chart-track"
                                    ).style(f"width: {overall_width:.2f}%"):
                                        for medium, color in (
                                            ("physical", "#356fb1"),
                                            ("digital", "#39a19f"),
                                            ("mixed", "#9cbfe5"),
                                        ):
                                            medium_count = int(
                                                owner_count[f"{medium}_record_count"]
                                            )
                                            medium_width = (
                                                (medium_count / record_count) * 100
                                                if record_count else 0
                                            )
                                            ui.element("span").classes(
                                                "dashboard-holdings-chart-segment"
                                            ).style(
                                                f"width: {medium_width:.2f}%; background: {color}"
                                            ).props(
                                                f"aria-label='{medium.title()} {medium_count}'"
                                            )
                                    ui.label(str(record_count)).classes(
                                        "dashboard-holdings-chart-total"
                                    )
                    with ui.element("div").classes("dashboard-holdings-list"):
                        for owner_count in ownership_counts:
                            row = ui.element("div").classes("dashboard-holdings-row").props(
                                "role=button tabindex=0"
                            )
                            row.on(
                                "click",
                                lambda _, item=owner_count: select_organization_unit_details(
                                    item["org_unit_id"]
                                ),
                            )
                            row.on(
                                "keydown.enter",
                                lambda _, item=owner_count: select_organization_unit_details(
                                    item["org_unit_id"]
                                ),
                            )
                            with row:
                                with ui.element("div").classes("dashboard-holdings-identity"):
                                    with ui.element("div").classes("dashboard-overview-icon"):
                                        ui.icon("corporate_fare", size="20px")
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(owner_count["org_unit_name"]).classes(
                                            "text-sm font-semibold text-slate-700 truncate w-full"
                                        ).tooltip(owner_count["org_unit_name"])
                                        ui.label(owner_count["org_unit_code"]).classes(
                                            "text-xs font-semibold text-primary"
                                        )
                                with ui.element("div").classes("dashboard-holdings-metric"):
                                    ui.icon("folder", size="17px").classes("text-primary shrink-0")
                                    with ui.column().classes("gap-0"):
                                        ui.label(
                                            render_message("dashboard.metric.aggregations",count=owner_count["aggregation_count"])
                                        ).classes("text-xs font-medium tabular-nums")
                                        ui.label(
                                            render_message("dashboard.metric.aggregation_status",open=owner_count["open_aggregation_count"],closed=owner_count["closed_aggregation_count"])
                                        ).classes("dashboard-holdings-metric-detail tabular-nums")
                                with ui.element("div").classes("dashboard-holdings-metric"):
                                    ui.icon("description", size="17px").classes("text-primary shrink-0")
                                    with ui.column().classes("gap-0"):
                                        ui.label(
                                            render_message("dashboard.metric.records",count=owner_count["record_count"])
                                        ).classes("text-xs font-medium tabular-nums")
                                        with ui.element("div").classes("dashboard-holdings-mediums"):
                                            for medium_index, medium in enumerate((
                                                "physical", "digital", "mixed",
                                            )):
                                                if medium_index:
                                                    ui.label("·").classes(
                                                        "dashboard-holdings-medium"
                                                    ).props("aria-hidden=true")
                                                with ui.element("span").classes(
                                                    "dashboard-overview-medium dashboard-holdings-medium"
                                                ):
                                                    ui.label(
                                                        dashboard_medium_label(medium,owner_count[f"{medium}_record_count"])
                                                    ).classes("tabular-nums")
                                with ui.element("div").classes("dashboard-holdings-metric"):
                                    with ui.column().classes("gap-1"):
                                        with ui.element("span").classes(
                                            "dashboard-holdings-peer-stat tabular-nums"
                                        ):
                                            ui.icon("emergency", size="14px").classes("text-red-600")
                                            ui.label(
                                                render_message("dashboard.metric.vital_records",count=owner_count["vital_record_count"])
                                            )
                                        with ui.element("span").classes(
                                            "dashboard-holdings-peer-stat tabular-nums"
                                        ):
                                            ui.icon("storage", size="14px").classes("text-primary")
                                            ui.label(
                                                render_message("dashboard.metric.storage",size=format_file_size(owner_count["storage_size_in_bytes"]))
                                            )
                else:
                    ui.label(
                        render_message("webui.load_dashboard.label.no_organizational_unit_holdings_are_availa_d64b09bd")
                    ).classes("text-sm text-slate-500")

                overdue_reviews = summary.get("overdue_reviews", [])
                upcoming_reviews = summary.get("upcoming_reviews", [])
                ui.label(render_message("webui.load_dashboard.label.review_reminders_8c1908c3")).classes("text-lg font-semibold mt-2")
                ui.label(
                    render_message("dashboard.review.window_guidance",days=summary.get("review_warning_window_days",30))
                ).classes("text-sm text-slate-500 -mt-1")
                overdue_total = int(summary["overdue_review_count"])
                upcoming_total = int(summary["upcoming_review_count"])
                review_total = overdue_total + upcoming_total
                overdue_percent = (overdue_total / review_total * 100) if review_total else 0
                donut_background = (
                    "conic-gradient(#d64b5f 0 "
                    f"{overdue_percent:.2f}%, #d99b32 {overdue_percent:.2f}% 100%)"
                    if review_total else "#e2e8f0"
                )
                with ui.element("div").classes("dashboard-review-layout"):
                    with ui.card().classes("dashboard-review-summary").props(
                        'aria-label=' + repr(render_message("webui.load_dashboard.accessible_name.review_urgency_summary_2750f795"))
                    ):
                        ui.label(render_message("webui.load_dashboard.label.review_urgency_561cf02e")).classes(
                            "text-sm font-semibold text-slate-700"
                        )
                        with ui.element("div").classes("dashboard-review-donut").style(
                            f"background: {donut_background}"
                        ):
                            with ui.element("div").classes("dashboard-review-donut-center"):
                                ui.label(str(review_total)).classes(
                                    "dashboard-review-donut-total"
                                )
                                ui.label(render_message("webui.load_dashboard.label.need_review_323554bd")).classes(
                                    "dashboard-review-donut-caption"
                                )
                        with ui.column().classes("w-full gap-2"):
                            for label, value, color in (
                                (render_message("dashboard.review.overdue"), overdue_total, "#d64b5f"),
                                (
                                    render_message("dashboard.review.next_days",days=summary.get("review_warning_window_days",30)),
                                    upcoming_total,
                                    "#d99b32",
                                ),
                            ):
                                with ui.element("div").classes(
                                    "dashboard-review-summary-row"
                                ):
                                    ui.element("i").classes("dashboard-chart-swatch").style(
                                        f"background: {color}"
                                    )
                                    ui.label(label)
                                    ui.label(str(value)).classes(
                                        "dashboard-review-summary-value"
                                    )
                    with ui.element("div").classes("dashboard-review-columns"):
                        for heading, items, color, empty in (
                            ("overdue", overdue_reviews, "negative", render_message("dashboard.review.none_overdue")),
                            ("upcoming", upcoming_reviews, "warning", render_message("dashboard.review.none_upcoming")),
                        ):
                            with ui.card().classes("dashboard-review-group"):
                                with ui.row().classes("dashboard-review-header w-full items-center gap-2"):
                                    ui.icon(
                                        "error_outline" if heading == "overdue" else "event",
                                        color=color,
                                        size="19px",
                                    )
                                    ui.label(render_message("dashboard.review.overdue") if heading == "overdue" else render_message("dashboard.review.upcoming")).classes("font-semibold")
                                    total = summary["overdue_review_count" if heading == "overdue" else "upcoming_review_count"]
                                    ui.badge(str(total), color=color).props("outline")
                                    ui.space()
                                    ui.button(
                                        render_message("webui.load_dashboard.button.view_all_260c05da"), icon="arrow_forward",
                                        on_click=lambda _, kind=heading.lower(): show_all_reviews(kind),
                                    ).props("flat dense no-caps color=primary")
                                if not items:
                                    ui.label(empty).classes("text-sm text-slate-400 px-3 py-4")
                                for item in items:
                                    resource = "aggregations" if item["entity_type"] == "aggregation" else "records"
                                    number = item.get("aggregation_number") or item.get("record_number")
                                    review_item = ui.element("div").classes(
                                        "dashboard-review-item"
                                    ).props("role=button tabindex=0")
                                    review_item.on(
                                        "click",
                                        lambda _, row=item, kind=resource: open_dashboard_resource(
                                            kind, {"id": row["entity_id"]}
                                        ),
                                    )
                                    review_item.on(
                                        "keydown.enter",
                                        lambda _, row=item, kind=resource: open_dashboard_resource(
                                            kind, {"id": row["entity_id"]}
                                        ),
                                    )
                                    with review_item:
                                        with ui.element("div").classes("dashboard-overview-icon"):
                                            ui.icon(
                                                "folder" if resource == "aggregations" else "description",
                                                size="18px",
                                            )
                                        with ui.column().classes("gap-0 grow min-w-0"):
                                            ui.label(item["title"]).classes(
                                                "text-sm font-semibold text-slate-700 truncate w-full"
                                            ).tooltip(item["title"])
                                            ui.label(
                                                render_message("dashboard.resource.identity",type=dashboard_resource_type(resource),number=number)
                                            ).classes("text-xs text-slate-500 truncate w-full")
                                        ui.label(
                                            format_timestamp(item["date_of_next_review"])
                                        ).classes(
                                            f"dashboard-review-date text-xs font-medium text-{color}"
                                        )
                                if total > len(items):
                                    ui.label(render_message("dashboard.result.showing",shown=len(items),total=total)).classes(
                                        "text-xs text-slate-500 self-end px-3 py-2"
                                    )

                if unclassified_root_count or inactive_classification_count:
                    ui.label(render_message("webui.load_dashboard.label.governance_attention_de7138ce")).classes("text-lg font-semibold mt-2")
                    with ui.row().classes("w-full gap-3 flex-wrap"):
                        if unclassified_root_count:
                            with ui.card().classes(
                                "grow min-w-[280px] cursor-pointer shadow-none border "
                                "border-red-200 bg-red-50 p-4"
                            ).on("click", show_unclassified_roots):
                                with ui.row().classes("items-center gap-3 no-wrap"):
                                    ui.avatar(icon="folder_off", color="red-1", text_color="negative")
                                    with ui.column().classes("gap-0"):
                                        ui.label(str(unclassified_root_count)).classes("text-xl font-bold text-negative")
                                        ui.label(render_message("webui.load_dashboard.label.unclassified_root_aggregations_efcbac0c")).classes("font-semibold")
                                        ui.label(render_message("webui.load_dashboard.label.root_aggregations_require_a_governing_clas_20cf1244")).classes("text-xs text-slate-500")
                        if inactive_classification_count:
                            with ui.card().classes(
                                "grow min-w-[280px] cursor-pointer shadow-none border "
                                "border-amber-200 bg-amber-50 p-4"
                            ).on("click", select_classification_workspace):
                                with ui.row().classes("items-center gap-3 no-wrap"):
                                    ui.avatar(icon="label_off", color="amber-1", text_color="amber-9")
                                    with ui.column().classes("gap-0"):
                                        ui.label(str(inactive_classification_count)).classes("text-xl font-bold text-amber-900")
                                        ui.label(render_message("webui.load_dashboard.label.inactive_classifications_4ca99653")).classes("font-semibold")
                                        ui.label(render_message("webui.load_dashboard.label.unavailable_for_new_aggregation_assignment_9e25cb2c")).classes("text-xs text-slate-500")

                favourites_area: Any = None

                def combined_favourites() -> list[dict[str, Any]]:
                    combined = [
                        {**item, "_resource": resource}
                        for resource in ("aggregations", "records")
                        for item in favourites[resource]
                    ]
                    return sorted(
                        combined,
                        key=lambda item: str(item.get("date_favourited") or ""),
                        reverse=True,
                    )

                def render_favourite_entry(
                    resource: str, item: dict[str, Any], *, after_remove: Any,
                ) -> None:
                    icon = "folder" if resource == "aggregations" else "description"
                    favourite_row = ui.element("div").classes(
                        "dashboard-personal-item"
                    ).props("role=button tabindex=0").on(
                        "click",
                        lambda _, selected=item, kind=resource: open_dashboard_resource(kind, selected),
                    ).on(
                        "keydown.enter",
                        lambda _, selected=item, kind=resource: open_dashboard_resource(kind, selected),
                    )
                    with favourite_row:
                        with ui.element("div").classes("dashboard-overview-icon"):
                            ui.icon(icon, size="18px")
                        with ui.column().classes("gap-0 grow min-w-0"):
                            ui.label(item["title"]).classes(
                                "text-sm font-semibold text-slate-700 truncate w-full"
                            ).tooltip(item["title"])
                            number = item.get("aggregation_number") or item.get("record_number")
                            resource_label = dashboard_resource_type(resource)
                            ui.label(render_message("dashboard.resource.identity",type=resource_label,number=number)).classes(
                                "text-xs text-slate-500 truncate w-full"
                            )
                        remove_button = ui.button(
                            icon="favorite", color="red",
                        ).props('flat round dense aria-label=' + repr(render_message("webui.render_favourite_entry.accessible_name.remove_from_favourites_40670952")))
                        remove_button.tooltip(render_message("webui.render_favourite_entry.tooltip.remove_from_favourites_dc2403f2"))
                        remove_button.on(
                            "click",
                            lambda _, selected=item, kind=resource: after_remove(kind, selected),
                            js_handler=STOP_PROPAGATION_CLICK_HANDLER,
                        )

                async def remove_dashboard_favourite(
                    resource: str, item: dict[str, Any], *, dialog_refresh: Any | None = None,
                ) -> None:
                    if not dashboard_view_is_current():
                        return
                    try:
                        await api.unfavourite(resource, item["id"])
                        if not dashboard_view_is_current():
                            return
                        favourites[resource] = [
                            entry for entry in favourites[resource]
                            if entry["id"] != item["id"]
                        ]
                        personal.favourites = favourites
                        personal.favourite_ids[resource].discard(int(item["id"]))
                        render_favourites_dashboard()
                        if dialog_refresh is not None:
                            dialog_refresh()
                        ui.notify(render_message("webui.remove_dashboard_favourite.notify.removed_from_favourites_6953809b"), color="positive")
                    except ApiError as error:
                        if not dashboard_view_is_current():
                            return
                        ui.notify(error_message(error), color="negative", close_button=True)

                def show_all_favourites() -> None:
                    if not dashboard_view_is_current():
                        return
                    dialog = ui.dialog()
                    with dialog, ui.card().classes(
                        "dashboard-personal-dialog w-[760px] max-w-full max-h-[85vh]"
                    ):
                        with ui.row().classes("w-full items-center"):
                            ui.label(render_message("webui.show_all_favourites.label.favourites_f9033752")).classes("text-xl font-semibold")
                            ui.space()
                            ui.button(icon="close", on_click=dialog.close).props("flat round")
                        complete_list = (
                            ui.scroll_area()
                            .classes("dashboard-personal-dialog-list")
                            .props("visible")
                            .style(
                                f"height:min(65vh,{personal_dialog_list_height(len(combined_favourites()))}px)"
                            )
                        )

                    def render_complete_list() -> None:
                        complete_list.clear()
                        with complete_list:
                            all_favourites = combined_favourites()
                            if not all_favourites:
                                ui.label(render_message("webui.render_complete_list.label.no_favourites_8952ca8c")).classes("text-sm text-slate-400 p-4")
                            for item in all_favourites:
                                render_favourite_entry(
                                    item["_resource"], item,
                                    after_remove=lambda kind, selected: remove_dashboard_favourite(
                                        kind, selected, dialog_refresh=render_complete_list,
                                    ),
                                )

                    render_complete_list()
                    dialog.open()

                def render_favourites_dashboard() -> None:
                    favourites_area.clear()
                    with favourites_area:
                        with ui.card().classes("dashboard-personal-panel"):
                            with ui.row().classes(
                                "dashboard-personal-header w-full items-center gap-2"
                            ):
                                ui.icon("favorite_border", color="primary", size="19px")
                                ui.label(render_message("webui.render_favourites_dashboard.label.favourites_a1c0758b")).classes("font-semibold text-slate-800")
                                total_favourites = sum(len(favourites[key]) for key in ("aggregations", "records"))
                                ui.badge(str(total_favourites), color="blue-grey").props("outline")
                                ui.space()
                                ui.button(
                                    render_message("webui.render_favourites_dashboard.button.view_all_e1f7fcfb"), on_click=show_all_favourites,
                                ).props("flat dense no-caps color=primary")
                            all_favourites = combined_favourites()
                            if not all_favourites:
                                ui.label(
                                    render_message("webui.render_favourites_dashboard.label.you_haven_t_added_any_favourites_yet_selec_9fcb89ef")
                                ).classes("text-sm text-slate-500 p-4")
                            for item in all_favourites[:favourite_limit]:
                                render_favourite_entry(
                                    item["_resource"], item, after_remove=remove_dashboard_favourite,
                                )

                def render_recent_record_entry(item: dict[str, Any]) -> None:
                    operation = item["_operation"]
                    activity_label, activity_icon, activity_class = {
                        "CREATE": (render_message("dashboard.activity.created"), "add", "dashboard-activity-created"),
                        "UPDATE": (render_message("dashboard.activity.updated"), "edit", "dashboard-activity-updated"),
                        "CONTENT_VIEWED": (render_message("dashboard.activity.viewed"), "visibility", "dashboard-activity-viewed"),
                    }[operation]
                    activity_row = ui.element("div").classes(
                        "dashboard-personal-item"
                    ).props("role=button tabindex=0").on(
                        "click", lambda _, entry=item: open_dashboard_resource("records", entry),
                    ).on(
                        "keydown.enter", lambda _, entry=item: open_dashboard_resource("records", entry),
                    )
                    with activity_row:
                        with ui.element("div").classes("dashboard-overview-icon"):
                            ui.icon("description", size="18px")
                        with ui.column().classes("gap-0 grow min-w-0"):
                            ui.label(item["title"]).classes(
                                "text-sm font-semibold text-slate-700 truncate w-full"
                            ).tooltip(item["title"])
                            ui.label(
                                render_message("webui.render_recent_record_entry.label.value_format_timestamp_a3b124e0", value=item.get('record_number') or '—', format_timestamp=format_timestamp(item['_activity_at']))
                            ).classes("text-xs text-slate-500 truncate w-full")
                        with ui.element("div").classes(
                            f"dashboard-activity-badge {activity_class}"
                        ):
                            ui.icon(activity_icon, size="13px")
                            ui.label(activity_label)

                def show_all_recent_records() -> None:
                    if not dashboard_view_is_current():
                        return
                    dialog = ui.dialog()
                    with dialog, ui.card().classes(
                        "dashboard-personal-dialog w-[820px] max-w-full max-h-[85vh]"
                    ):
                        with ui.row().classes("w-full items-center"):
                            ui.label(render_message("webui.show_all_recent_records.label.recent_records_activity_3b1a4c9d")).classes("text-xl font-semibold")
                            ui.space()
                            ui.button(icon="close", on_click=dialog.close).props("flat round")
                        with (
                            ui.scroll_area()
                            .classes("dashboard-personal-dialog-list")
                            .props("visible")
                            .style(
                                f"height:min(65vh,{personal_dialog_list_height(len(all_recent_records))}px)"
                            )
                        ):
                            if not all_recent_records:
                                ui.label(render_message("webui.show_all_recent_records.label.no_recent_records_activity_0ecddb69")).classes("text-sm text-slate-400 p-4")
                            for item in all_recent_records:
                                render_recent_record_entry(item)
                    dialog.open()

                with personal_sections_area:
                    with ui.element("div").classes("dashboard-personal-columns mt-2"):
                        favourites_area = ui.element("div").classes("w-full")
                        render_favourites_dashboard()
                        with ui.card().classes("dashboard-personal-panel"):
                            with ui.row().classes(
                                "dashboard-personal-header w-full items-center gap-2"
                            ):
                                ui.icon("history", color="primary", size="19px")
                                ui.label(render_message("webui.load_dashboard.label.recent_records_activity_5200d38a")).classes("font-semibold text-slate-800")
                                ui.space()
                                ui.button(
                                    render_message("webui.load_dashboard.button.view_all_260c05da"), on_click=show_all_recent_records,
                                ).props("flat dense no-caps color=primary")
                            if not recent_records:
                                ui.label(
                                    render_message("dashboard.recent.empty",days=recent_days)
                                ).classes("text-sm text-slate-500 p-4")
                            for item in recent_records:
                                render_recent_record_entry(item)

                ui.label(render_message("webui.load_dashboard.label.digital_storage_by_organizational_unit_e4533a05")).classes(
                    "text-lg font-semibold mt-2"
                )
                ui.label(
                    render_message("webui.load_dashboard.label.largest_authorized_storage_totals_among_un_e603dcd3")
                ).classes("text-sm text-slate-500 -mt-1")
                ranked_storage_units = sorted(
                    ownership_counts,
                    key=lambda item: (
                        -int(item["storage_size_in_bytes"]),
                        str(item["org_unit_name"]),
                        int(item["org_unit_id"]),
                    ),
                )
                top_storage_units = ranked_storage_units[:5]
                other_storage_units = ranked_storage_units[5:]
                total_storage_bytes = sum(
                    int(item["storage_size_in_bytes"]) for item in ranked_storage_units
                )
                maximum_unit_storage = max(
                    (int(item["storage_size_in_bytes"]) for item in top_storage_units),
                    default=1,
                ) or 1
                with ui.element("section").classes("dashboard-storage-chart").props(
                    'aria-label=' + repr(render_message("webui.load_dashboard.accessible_name.top_five_organizational_units_by_authorize_cfc7c0c5"))
                ):
                    with ui.row().classes("w-full items-start gap-3"):
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(render_message("webui.load_dashboard.label.top_organizational_units_22b57918")).classes(
                                "text-sm font-semibold text-slate-700"
                            )
                            ui.label(
                                render_message("dashboard.storage.units_shown",shown=len(top_storage_units),total=len(ranked_storage_units))
                            ).classes("text-xs text-slate-500")
                        ui.space()
                        with ui.column().classes("items-end gap-0 shrink-0"):
                            ui.label(format_file_size(total_storage_bytes)).classes(
                                "text-lg font-bold text-slate-800 tabular-nums"
                            )
                            ui.label(render_message("webui.load_dashboard.label.authorized_storage_dc78b6fc")).classes(
                                "text-[10px] text-slate-500"
                            )
                    if not ranked_storage_units:
                        ui.label(
                            render_message("webui.load_dashboard.label.no_organizational_unit_storage_is_availabl_a6019705")
                        ).classes("text-sm text-slate-500 py-4")
                    else:
                        with ui.element("div").classes("dashboard-storage-chart-rows"):
                            for owner_count in top_storage_units:
                                storage_bytes = int(owner_count["storage_size_in_bytes"])
                                bar_width = (storage_bytes / maximum_unit_storage) * 100
                                share = (
                                    (storage_bytes / total_storage_bytes) * 100
                                    if total_storage_bytes else 0
                                )
                                with ui.element("div").classes(
                                    "dashboard-storage-chart-row"
                                ):
                                    ui.label(owner_count["org_unit_name"]).classes(
                                        "dashboard-storage-chart-name"
                                    ).tooltip(owner_count["org_unit_name"])
                                    with ui.element("div").classes(
                                        "dashboard-storage-chart-track"
                                    ):
                                        ui.element("div").classes(
                                            "dashboard-storage-chart-bar"
                                        ).style(f"width: {bar_width:.2f}%")
                                    with ui.column().classes("items-end gap-0"):
                                        ui.label(format_file_size(storage_bytes)).classes(
                                            "dashboard-storage-chart-value"
                                        )
                                        ui.label(render_message("webui.load_dashboard.label.share_06671928", share=format(share, '.1f'))).classes(
                                            "dashboard-storage-chart-share"
                                        )
                            if other_storage_units:
                                other_storage_bytes = sum(
                                    int(item["storage_size_in_bytes"])
                                    for item in other_storage_units
                                )
                                other_share = (
                                    (other_storage_bytes / total_storage_bytes) * 100
                                    if total_storage_bytes else 0
                                )
                                with ui.element("div").classes(
                                    "dashboard-storage-chart-row dashboard-storage-other"
                                ):
                                    ui.label(
                                        render_message("dashboard.storage.other_units",count=len(other_storage_units))
                                    ).classes("dashboard-storage-chart-name")
                                    ui.label(render_message("webui.load_dashboard.label.combined_remainder_df5fa70b")).classes(
                                        "dashboard-storage-other-summary"
                                    )
                                    with ui.column().classes("items-end gap-0"):
                                        ui.label(format_file_size(other_storage_bytes)).classes(
                                            "dashboard-storage-chart-value"
                                        )
                                        ui.label(render_message("webui.load_dashboard.label.other_share_36b8a00f", other_share=format(other_share, '.1f'))).classes(
                                            "dashboard-storage-chart-share"
                                        )
                set_connection_status(True)

        cached_summary = state.get("dashboard_summary_cache")
        if (
            state.get("dashboard_summary_cache_key") == dashboard_key
            and isinstance(cached_summary, dict) and cached_summary
        ):
            await load_dashboard(summary_override=cached_summary)
            background_tasks.create(load_dashboard(refresh_only=True))
        else:
            await load_dashboard()

    def enter_audit_trail() -> None:
        register_navigation("audit-trail", "Audit trail")
        show_authenticated_view()
        state.update(resource='audit-trail', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
        title.text = render_message("webui.select_audit_trail.text.audit_trail_2f72156b")
        subtitle.text = render_message("webui.select_audit_trail.text.immutable_history_of_changes_across_the_sy_788bd954")
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        guidance.text = ""
        table_container.clear()


    set_aggregation_mode_controls, select_aggregation_browser, select_aggregation_search = build_aggregation_browser(
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_browse_mode=aggregation_browse_mode,
        aggregation_search_mode=aggregation_search_mode,
        aggregation_state=aggregation_state,
        api=api,
        bind_remote_scheme_select=lambda *args, **kwargs: bind_remote_scheme_select(*args, **kwargs),
        current_direction=current_direction,
        error_message=error_message,
        get_resource=lambda: state.get("resource"),
        guidance=guidance,
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        page_client=page_client,
        personal=personal,
        principal=lambda: auth_state.get("principal"),
        render_table=lambda *args, **kwargs: render_table(*args, **kwargs),
        search_bar=search_bar,
        show_record_details=lambda *args, **kwargs: show_record_details(*args, **kwargs),
        table_container=table_container,
        tree_expander_icon=lambda *args, **kwargs: tree_expander_icon(*args, **kwargs),
    )





    def enter_organization_units() -> None:
        state.update(resource='org-unit-details', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)


    def enter_organization_roles() -> None:
        state.update(resource='role-details', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)





    def enter_organization_users() -> None:
        state.update(resource='user-details', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)


    def enter_organization_browser() -> None:
        state.update(resource='organization-browser', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)


    async def select_governance_custody() -> None:
        principal = auth_state.get("principal")
        if not principal or not can_navigate("governance-custody", principal.get("global_privileges", [])):
            return
        prior_report_visible = state.get("resource") == "governance-custody"
        token = object()
        register_navigation(
            "governance-custody",
            render_message("webui.select_governance_custody.text.governance_custody_d1711a12"),
        )
        show_authenticated_view()
        state.update(resource="governance-custody", custody_page_token=token, rows=[], searched=True)
        title.text = render_message("webui.select_governance_custody.text.governance_custody_d1711a12")
        subtitle.text = render_message("webui.select_governance_custody.text.checks_that_someone_can_always_manage_and_63c11d0d")
        search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False); add_record_button.set_visibility(False)
        guidance.text = ""
        if not prior_report_visible:
            table_container.clear()
            with table_container:
                ui.label(render_message("settings.custody.loading")).classes("p-5 text-sm text-slate-500").props("role=status")
        try:
            report = await api.governance_custody()
        except ApiError as error:
            if state.get("custody_page_token") is token and state.get("resource") == "governance-custody":
                ui.notify(error_message(error), color="negative", close_button=True)
            return
        if auth_state.get("principal") is not principal or state.get("resource") != "governance-custody" or state.get("custody_page_token") is not token:
            return
        table_container.clear()
        highest_level = report.get("highest_security_level")
        warning = next(iter(report.get("warnings", [])), None)
        custodian_count = report["highest_clearance_custodian_count"]
        qualifying_roles = [
            item for item in report["governance_roles"]
            if item["qualifies_for_universal_custody"]
        ]
        qualifying_assignments = [
            item for item in report["assignments"]
            if item["effective_for_universal_custody"]
        ]
        assignments_needing_attention = [
            item for item in report["assignments"]
            if not item["effective_for_universal_custody"]
        ]
        qualifying_roles_by_id = {item["id"]: item for item in qualifying_roles}
        with table_container, ui.column().classes("w-full p-5 gap-4"):
            with ui.row().classes("w-full justify-end"):
                ui.button(render_message("settings.action.refresh"), icon="refresh", on_click=select_governance_custody).props("flat dense no-caps")
            disposition_warning_panel(
                report.get("disposition_configuration_warnings", []),
                can_manage=application_settings_controller.can_open(),
                open_settings=application_settings_controller.open_from_custody,
            )
            with ui.element("div").classes("governance-overview-grid"):
                with ui.card().classes("governance-purpose-card shadow-none"):
                    with ui.row().classes("w-full items-start gap-3 no-wrap"):
                        with ui.element("div").classes("governance-purpose-icon"):
                            ui.icon("policy", size="21px")
                        with ui.column().classes("gap-1 grow min-w-0"):
                            ui.label(render_message("webui.select_governance_custody.label.what_this_page_checks_99ff34f2")).classes("text-base font-semibold")
                            ui.label(
                                render_message("webui.select_governance_custody.label.at_least_one_active_person_must_be_able_to_4bd6d924")
                            ).classes("text-sm text-slate-600 leading-relaxed")
                            with ui.element("div").classes("governance-requirements-grid"):
                                for requirement in (
                                    render_message("governance_custody.requirement.governance_role_enabled"),
                                    render_message("governance_custody.requirement.highest_clearance_held"),
                                    render_message("governance_custody.requirement.required_profile_privileges"),
                                    render_message("governance_custody.requirement.current_role_assignment"),
                                ):
                                    with ui.row().classes("items-center gap-2 no-wrap"):
                                        ui.icon("check", color="positive", size="16px")
                                        ui.label(requirement).classes("text-xs text-slate-600")
                            ui.label(
                                render_message("webui.select_governance_custody.label.the_system_blocks_relevant_changes_that_wo_35b5b23b")
                            ).classes("text-xs text-slate-500 mt-1")
                critical = bool(warning and warning["severity"] == "critical")
                status_classes = (
                    "governance-status-card governance-status-critical"
                    if critical else
                    "governance-status-card governance-status-warning"
                    if warning else
                    "governance-status-card governance-status-healthy"
                )
                with ui.card().classes(f"{status_classes} shadow-none"):
                    with ui.row().classes("w-full items-start gap-3 no-wrap"):
                        with ui.element("div").classes("governance-status-icon"):
                            ui.icon("priority_high" if warning else "check", size="18px")
                        with ui.column().classes("gap-1 grow min-w-0"):
                            ui.label(
                                render_message("webui.select_governance_custody.label.custody_gap_detected_574f1e6b") if critical else
                                render_message("webui.select_governance_custody.label.custody_resilience_needs_attention_c7e23c3c") if warning else
                                render_message("webui.select_governance_custody.label.custody_coverage_is_healthy_a188b010")
                            ).classes("text-base font-semibold")
                            ui.label(
                                render_message("webui.select_governance_custody.label.no_person_currently_meets_every_requiremen_0a14d273")
                                if critical else
                                render_message("webui.select_governance_custody.label.only_one_person_currently_qualifies_add_a_8331e15a")
                                if warning else
                                render_message(
                                    "webui.select_governance_custody.label.custodian_count_active_value_currently_qua_5dd0d9d6",
                                    custodian_count=custodian_count,
                                    qualifying_role_count=len(qualifying_roles),
                                    qualifying_assignment_count=len(qualifying_assignments),
                                )
                            ).classes("text-sm leading-relaxed")
            with ui.row().classes("governance-metrics-row"):
                for value, label, icon in (
                    (custodian_count, render_message("governance_custody.metric.universal_custodians"), "person"),
                    (len(qualifying_roles), render_message("governance_custody.metric.qualifying_roles"), "badge"),
                    (len(qualifying_assignments), render_message("governance_custody.metric.qualifying_assignments"), "group"),
                ):
                    with ui.card().classes("governance-metric-card shadow-none"):
                        with ui.element("div").classes("governance-metric-icon"):
                            ui.icon(icon, size="18px")
                        with ui.column().classes("gap-0"):
                            ui.label(str(value)).classes("text-2xl font-semibold leading-none")
                            ui.label(label).classes("text-xs text-slate-500 mt-1")
            with ui.row().classes("w-full items-end gap-3 mt-1"):
                with ui.column().classes("gap-0 grow"):
                    ui.label(render_message("webui.select_governance_custody.label.universal_custodians_custodian_count_7eae7060", custodian_count=custodian_count)).classes(
                        "text-base font-semibold"
                    )
                    ui.label(
                        render_message("webui.select_governance_custody.label.active_people_whose_current_assignments_pr_46442dde")
                    ).classes("text-xs text-slate-500")
                if highest_level:
                    ui.badge(
                        render_message("webui.select_governance_custody.badge.required_clearance_code_name_level_level_n_def0467f", code=highest_level['code'], name=highest_level['name'], level_number=highest_level['level_number'])
                    ).props("outline color=primary")
            if qualifying_assignments:
                custodian_rows = [
                    {
                        **item,
                        "person": item["user_name"],
                        "email": item.get("user_email") or "—",
                        "avatar": user_avatar({
                            "id": item["user_id"],
                            "name": item["user_name"],
                            "email": item.get("user_email"),
                        }),
                        "role": f"{item['role_code']} — {item['role_name']}",
                        "clearance": (
                            f"{qualifying_roles_by_id[item['role_id']]['security_level_code']} — "
                            f"{qualifying_roles_by_id[item['role_id']]['security_level_name']}"
                        ),
                        "valid_from_display": format_timestamp(item["valid_from"]),
                        "valid_until_display": (
                            format_timestamp(item["valid_until"])
                            if item.get("valid_until")
                            else render_message("common.value.no_expiry")
                        ),
                    }
                    for item in qualifying_assignments
                ]
                custodian_page = {"offset": 0}
                custodian_host = ui.element("div").classes("governance-card-list w-full")
                with ui.row().classes("w-full items-center justify-end gap-2"):
                    custodian_page_label = ui.label().classes("text-sm text-slate-500")
                    custodian_previous = ui.button(
                        render_message("webui.select_governance_custody.button.previous_edabaddc"), icon="chevron_left",
                    ).props("flat dense no-caps")
                    custodian_next = ui.button(
                        render_message("webui.select_governance_custody.button.next_1b4b15c1"), icon="chevron_right",
                    ).props("flat dense no-caps")

                def render_custodian_cards() -> None:
                    offset = custodian_page["offset"]
                    page_rows = custodian_rows[offset:offset + 5]
                    custodian_host.clear()
                    with custodian_host:
                        for row in page_rows:
                            with ui.card().classes(
                                "governance-list-card governance-custody-assignment-card shadow-none"
                            ):
                                with ui.row().classes("w-full items-center no-wrap gap-3"):
                                    render_user_avatar({
                                        "id": row["user_id"], "name": row["person"],
                                        "email": row["email"],
                                    }, size="36px")
                                    with ui.column().classes("gap-0 min-w-0 grow"):
                                        ui.label(row["person"]).classes("font-semibold")
                                        ui.label(row["email"]).classes(
                                            "text-xs text-slate-500 truncate w-full"
                                        ).tooltip(row["email"])
                                    ui.badge(render_message("webui.render_custodian_cards.badge.universal_custodian_d25d5028"), color="positive").props(
                                        "outline"
                                    )
                                    ui.button(
                                        icon="person",
                                        on_click=lambda _, item=row: select_user_details(
                                            item["user_id"]
                                        ),
                                    ).props("flat round dense").tooltip(render_message("webui.render_custodian_cards.tooltip.open_user_9f50a343"))
                                    ui.button(
                                        icon="badge",
                                        on_click=lambda _, item=row: select_role_details(
                                            item["role_id"]
                                        ),
                                    ).props("flat round dense").tooltip(render_message("webui.render_custodian_cards.tooltip.open_role_b3a2bb9f"))
                                with ui.element("div").classes("governance-list-facts"):
                                    for label, value in (
                                        (render_message("governance_custody.field.qualifying_role"), row["role"]),
                                        (render_message("governance_custody.field.clearance"), row["clearance"]),
                                        (render_message("governance_custody.field.valid_from"), row["valid_from_display"]),
                                        (render_message("governance_custody.field.valid_until"), row["valid_until_display"]),
                                    ):
                                        with ui.column().classes("gap-0 min-w-0"):
                                            ui.label(label).classes("detail-field-label")
                                            ui.label(value).classes("text-sm truncate w-full").tooltip(value)
                    start = offset + 1
                    end = min(offset + 5, len(custodian_rows))
                    custodian_page_label.text = render_message("webui.render_custodian_cards.text.start_end_of_custodian_row_count_dae30e10", start=start, end=end, custodian_row_count=len(custodian_rows))
                    custodian_page_label.update()
                    (custodian_previous.enable if offset > 0 else custodian_previous.disable)()
                    (custodian_next.enable if offset + 5 < len(custodian_rows) else custodian_next.disable)()

                def previous_custodians() -> None:
                    custodian_page["offset"] = max(0, custodian_page["offset"] - 5)
                    render_custodian_cards()

                def next_custodians() -> None:
                    custodian_page["offset"] += 5
                    render_custodian_cards()

                custodian_previous.on("click", previous_custodians)
                custodian_next.on("click", next_custodians)
                render_custodian_cards()
            else:
                ui.label(
                    render_message("webui.select_governance_custody.label.no_active_person_currently_meets_every_uni_a3dca3a6")
                ).classes("governance-empty-inline")
            with ui.row().classes("w-full items-center gap-3"):
                with ui.column().classes("gap-0 grow"):
                    ui.label(render_message("webui.select_governance_custody.label.information_governance_roles_911de052")).classes("text-base font-semibold")
                    ui.label(
                        render_message("webui.select_governance_custody.label.qualifying_roles_provide_custody_other_lis_4d8ef8ea")
                    ).classes("text-xs text-slate-500")
            if not report["governance_roles"]:
                with ui.card().classes("governance-empty-state shadow-none"):
                    ui.icon("verified_user", color="blue-grey-4", size="28px")
                    ui.label(render_message("webui.select_governance_custody.label.no_information_governance_roles_are_config_e5d78ffe")).classes(
                        "text-sm font-semibold text-slate-700"
                    )
                    ui.label(
                        render_message("webui.select_governance_custody.label.designate_the_appropriate_records_manageme_af9e90ae")
                    ).classes("text-xs text-slate-500 text-center")
                    with ui.row().classes("gap-2 mt-1"):
                        ui.button(
                            render_message("webui.select_governance_custody.button.configure_a_role_29c8cb79"), icon="badge",
                            on_click=lambda: select_entity("roles"),
                        ).props("outline dense no-caps")
                        ui.button(
                            render_message("webui.select_governance_custody.button.review_profiles_72e9cc1a"), icon="admin_panel_settings",
                            on_click=lambda: select_entity("profiles"),
                        ).props("flat dense no-caps")
            else:
                for role in report["governance_roles"]:
                    with ui.card().classes("w-full shadow-none border border-slate-200 p-4 gap-2"):
                        with ui.row().classes("w-full items-center gap-3 no-wrap"):
                            ui.icon("verified_user", color="primary")
                            with ui.column().classes("gap-0 grow min-w-0"):
                                ui.label(render_message("webui.select_governance_custody.label.code_name_740f84d3", code=role['code'], name=role['name'])).classes("font-semibold")
                                ui.label(
                                    render_message(
                                        "webui.select_governance_custody.label.profile_profile_code_profile_name_8fd7d019",
                                        profile_code=role["profile_code"],
                                        profile_name=localized_profile_value(
                                            {"code": role["profile_code"], "name": role["profile_name"]},
                                            "name",
                                        ),
                                    )
                                ).classes("text-xs text-slate-500")
                            ui.badge(
                                render_message("webui.select_governance_custody.badge.qualifies_for_universal_custody_a79e1a94")
                                if role["qualifies_for_universal_custody"] else
                                render_message("webui.select_governance_custody.badge.does_not_qualify_1f027fee"),
                                color="positive" if role["qualifies_for_universal_custody"] else "warning",
                            ).props("outline")
                            ui.button(
                                icon="badge",
                                on_click=lambda _, identifier=role["id"]: select_role_details(identifier),
                            ).props("flat round dense").tooltip(render_message("webui.select_governance_custody.tooltip.open_role_5da0e9a7"))
                        with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                            ui.badge(
                                render_message("webui.select_governance_custody.badge.security_level_code_security_level_name_le_7ee97b4b", security_level_code=role['security_level_code'], security_level_name=role['security_level_name'], level_number=role['level_number']),
                                color="positive" if role["is_highest_clearance"] else "blue-grey",
                            ).props("outline")
                            ui.badge(
                                render_message("webui.select_governance_custody.badge.role_and_organization_active_c40efefa") if role["effective"] else render_message("webui.select_governance_custody.badge.role_or_organization_inactive_b4bb3f56"),
                                color="positive" if role["effective"] else "negative",
                            ).props("outline")
                            ui.badge(
                                render_message("webui.select_governance_custody.badge.all_custody_privileges_present_1be04201")
                                if role["has_required_custody_privileges"] else
                                render_message("webui.select_governance_custody.badge.missing_custody_privilege_code_count_custo_93921b59", missing_custody_privilege_code_count=len(role['missing_custody_privilege_codes'])),
                                color="positive" if role["has_required_custody_privileges"] else "negative",
                            ).props("outline")
                            for count, label, explanation in (
                                (
                                    role["current_assignee_count"],
                                    render_message("governance_custody.stat.current_assignments"),
                                    render_message("governance_custody.help.current_assignments"),
                                ),
                                (
                                    role["effective_assignee_count"],
                                    render_message("governance_custody.stat.active_people_in_active_role"),
                                    render_message("governance_custody.help.active_people_in_active_role"),
                                ),
                                (
                                    role["universal_custodian_count"],
                                    render_message("governance_custody.metric.universal_custodians"),
                                    render_message("governance_custody.help.universal_custodians"),
                                ),
                            ):
                                ui.label(render_message("webui.select_governance_custody.label.label_count_73f7a855", label=label, count=count)).classes(
                                    "text-xs text-slate-500 cursor-help"
                                ).tooltip(explanation)
                        if role["missing_custody_privilege_codes"]:
                            missing = ", ".join(role["missing_custody_privilege_codes"])
                            ui.label(render_message("webui.select_governance_custody.label.missing_privileges_missing_ab329cec", missing=missing)).classes(
                                "text-xs font-mono text-red-700 break-all"
                            )

            if assignments_needing_attention:
                with ui.row().classes("w-full items-center gap-3 mt-1"):
                    with ui.column().classes("gap-0 grow"):
                        ui.label(render_message("webui.select_governance_custody.label.assignments_needing_attention_c83257ed")).classes("text-base font-semibold")
                        ui.label(
                            render_message("webui.select_governance_custody.label.only_assignments_that_do_not_currently_pro_3dcf32ef")
                        ).classes("text-xs text-slate-500")
                    if highest_level:
                        ui.label(
                            render_message("webui.select_governance_custody.label.highest_configured_level_code_name_level_l_8df33123", code=highest_level['code'], name=highest_level['name'], level_number=highest_level['level_number'])
                        ).classes("text-xs text-slate-500")
                reason_labels = {
                    "service_account": render_message("governance_custody.reason.service_account"),
                    "user_inactive": render_message("governance_custody.reason.user_inactive"),
                    "user_suspended": render_message("governance_custody.reason.user_suspended"),
                    "assignment_not_current": render_message("governance_custody.reason.assignment_not_current"),
                    "role_or_organization_inactive": render_message("governance_custody.reason.role_or_organization_inactive"),
                    "role_not_universal_custody_qualified": render_message("governance_custody.reason.role_not_universal_custody_qualified"),
                }
                assignment_rows = []
                for item in assignments_needing_attention:
                    assignment_rows.append({
                        **item,
                        "person": item["user_name"],
                        "email": item.get("user_email") or "—",
                        "role": f"{item['role_code']} — {item['role_name']}",
                        "custody_status": "; ".join(
                            reason_labels[reason]
                            if reason in reason_labels
                            else reason.replace("_", " ").title()
                            for reason in item["ineffective_reasons"]
                        ),
                    })
                attention_page = {"offset": 0}
                attention_host = ui.element("div").classes("governance-card-list w-full")
                with ui.row().classes("w-full items-center justify-end gap-2"):
                    attention_page_label = ui.label().classes("text-sm text-slate-500")
                    attention_previous = ui.button(
                        render_message("webui.select_governance_custody.button.previous_edabaddc"), icon="chevron_left",
                    ).props("flat dense no-caps")
                    attention_next = ui.button(
                        render_message("webui.select_governance_custody.button.next_1b4b15c1"), icon="chevron_right",
                    ).props("flat dense no-caps")

                def render_attention_cards() -> None:
                    offset = attention_page["offset"]
                    page_rows = assignment_rows[offset:offset + 5]
                    attention_host.clear()
                    with attention_host:
                        for row in page_rows:
                            with ui.card().classes(
                                "governance-list-card governance-custody-assignment-card shadow-none"
                            ):
                                with ui.row().classes("w-full items-center no-wrap gap-3"):
                                    render_user_avatar({
                                        "id": row["user_id"], "name": row["person"],
                                        "email": row["email"],
                                    }, size="36px")
                                    with ui.column().classes("gap-0 min-w-0 grow"):
                                        ui.label(row["person"]).classes("font-semibold")
                                        ui.label(row["email"]).classes(
                                            "text-xs text-slate-500 truncate w-full"
                                        ).tooltip(row["email"])
                                    ui.button(
                                        icon="person",
                                        on_click=lambda _, item=row: select_user_details(
                                            item["user_id"]
                                        ),
                                    ).props("flat round dense").tooltip(render_message("webui.render_attention_cards.tooltip.open_user_350f3508"))
                                with ui.element("div").classes(
                                    "governance-list-facts user-role-assignment-facts"
                                ):
                                    for label, value in (
                                        (render_message("entity_metadata.field.role"), row["role"]),
                                        (render_message("governance_custody.field.custody_status"), row["custody_status"]),
                                    ):
                                        with ui.column().classes("gap-0 min-w-0"):
                                            ui.label(label).classes("detail-field-label")
                                            ui.label(value).classes(
                                                "text-sm whitespace-normal"
                                            )
                    start = offset + 1
                    end = min(offset + 5, len(assignment_rows))
                    attention_page_label.text = render_message("webui.render_attention_cards.text.start_end_of_assignment_row_count_f9667dd2", start=start, end=end, assignment_row_count=len(assignment_rows))
                    attention_page_label.update()
                    (attention_previous.enable if offset > 0 else attention_previous.disable)()
                    (attention_next.enable if offset + 5 < len(assignment_rows) else attention_next.disable)()

                def previous_attention_assignments() -> None:
                    attention_page["offset"] = max(0, attention_page["offset"] - 5)
                    render_attention_cards()

                def next_attention_assignments() -> None:
                    attention_page["offset"] += 5
                    render_attention_cards()

                attention_previous.on("click", previous_attention_assignments)
                attention_next.on("click", next_attention_assignments)
                render_attention_cards()

    async def select_security_operations() -> None:
        register_navigation("security-operations", "Security operations")
        show_authenticated_view()
        state.update(resource="security-operations", rows=[], searched=True)
        title.text = render_message("webui.select_security_operations.text.security_operations_f2690c64"); subtitle.text = render_message("webui.select_security_operations.text.sanitized_security_signals_and_access_cont_960ec487")
        search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False); add_record_button.set_visibility(False); guidance.text = ""
        table_container.clear()
        privileges = set((auth_state.get("principal") or {}).get("global_privileges", []))
        with table_container, ui.column().classes("w-full p-5 gap-5"):
            with ui.row().classes("w-full items-center gap-3"):
                ui.icon("monitor_heart", color="primary", size="30px")
                with ui.column().classes("gap-0 grow"):
                    window_title = ui.label(render_message("webui.select_security_operations.label.last_24_hours_fa33cd89")).classes("text-xl font-semibold")
                    ui.label(render_message("webui.select_security_operations.label.aggregated_signals_contain_no_protected_re_f7ff6ccb")).classes("text-sm text-slate-500")
                period = ui.select(
                    {"24h": render_message("webui.select_security_operations.select.last_24_hours_bb3b461d"), "week": render_message("webui.select_security_operations.select.last_week_b01c00d9"), "month": render_message("webui.select_security_operations.select.last_month_c2116839"), "custom": render_message("webui.select_security_operations.select.custom_4d95447c")},
                    value="24h", label=render_message("webui.select_security_operations.select.period_ed31c1a0"),
                ).props("outlined dense options-dense").classes("w-44")
                refresh = ui.button(render_message("webui.select_security_operations.button.refresh_aa2c487e"), icon="refresh").props("outline no-caps")
            custom_range = ui.row().classes("w-full items-end gap-3")
            with custom_range:
                range_start = ui.input(render_message("webui.select_security_operations.input.from_a135a152")).props("outlined dense type=date").classes("w-52")
                range_end = ui.input(render_message("webui.select_security_operations.input.through_b5ed408a")).props("outlined dense type=date").classes("w-52")
                apply_range = ui.button(render_message("webui.select_security_operations.button.apply_range_53faab3c"), icon="date_range").props("unelevated no-caps")
            custom_range.set_visibility(False)
            content = ui.column().classes("w-full gap-5")

        def custom_iso(value: str | None, *, end: bool) -> str | None:
            if not value:
                return None
            parsed = datetime.fromisoformat(value).astimezone()
            if end:
                parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
            else:
                parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
            return parsed.isoformat()

        async def load_security_operations() -> None:
            with page_client:
                await render_security_operations()

        async def render_security_operations() -> None:
            # Resolve explanations in the current session language, never at import time.
            security_event_help = {
                "AUTHORIZATION_DENIED": render_message("webui.module.text.an_operation_was_refused_because_one_or_mo_8a8c328d"),
                "AUTHENTICATION_FAILED": render_message("webui.module.text.a_sign_in_attempt_failed_repeated_failures_9063b5ad"),
                "ACCOUNT_LOCKED": render_message("webui.module.text.an_account_was_locked_after_reaching_the_c_9b0a2ea9"),
                "INFORMATION_GOVERNANCE_BYPASS_USED": render_message("webui.module.text.a_qualifying_governance_role_bypassed_the_b9e69c3c"),
                "ACCESS_EXPLANATION_VIEWED": render_message("webui.module.text.an_authorized_examiner_inspected_why_anoth_ff54a75d"),
                "SECURITY_LEVEL_CHANGED": render_message("webui.module.text.a_resource_security_level_changed_45527425"),
                "SECURITY_LEVEL_UPGRADED": render_message("webui.module.text.a_resource_was_raised_to_a_more_restrictiv_267fec56"),
                "SECURITY_LEVEL_DOWNGRADED": render_message("webui.module.text.a_resource_was_lowered_to_a_less_restricti_33c49609"),
                "ACL_REPLACED": render_message("webui.module.text.a_resource_s_local_access_control_list_was_9401ad98"),
                "DEFAULT_CHILD_AGGREGATION_ACL_REPLACED": render_message("webui.module.text.the_default_acl_inherited_by_child_aggrega_f12c6a28"),
                "DEFAULT_CHILD_RECORD_ACL_REPLACED": render_message("webui.module.text.the_default_acl_inherited_by_child_records_b8435ae9"),
                "PROFILE_PRIVILEGES_REPLACED": render_message("webui.module.text.the_complete_privilege_set_attached_to_a_p_8355d82e"),
                "PROFILE_ASSIGNED": render_message("webui.module.text.a_role_was_assigned_a_different_authorizat_a7a05cad"),
                "GOVERNANCE_ROLE_CHANGED": render_message("webui.module.text.a_role_s_information_governance_designatio_118a4087"),
            }

            authorization_denial_help = (
                render_message("webui.module.text.these_are_operations_refused_by_the_author_9f71f790")
            )
            mode = period.value or "24h"
            hours = {"24h": 24, "week": 24 * 7, "month": 24 * 30}.get(mode, 24)
            if mode == "custom" and (not range_start.value or not range_end.value):
                ui.notify(render_message("webui.load_security_operations.notify.select_both_dates_for_the_custom_range_c8117eee"), color="warning")
                return
            summary = await api.security_summary(
                hours=hours,
                start_at=custom_iso(range_start.value, end=False) if mode == "custom" else None,
                end_at=custom_iso(range_end.value, end=True) if mode == "custom" else None,
            )
            reconciliation = None
            if "authorization.administer" in privileges:
                reconciliation = await api.security_reconciliation()
            if state.get("resource") != "security-operations" or period.value != mode:
                return
            window_title.text = {
                "24h": render_message("webui.load_security_operations.text.last_24_hours_42c47f2c"), "week": render_message("webui.load_security_operations.text.last_week_0f602f5d"), "month": render_message("webui.load_security_operations.text.last_month_1df4669b"),
                "custom": render_message("webui.load_security_operations.text.value_through_value_2_8da1ebd6", value=range_start.value, value_2=range_end.value),
            }[mode]
            content.clear()
            with content:
                full_privilege_roles = summary.get("full_privilege_roles", [])
                if full_privilege_roles:
                    with ui.card().classes(
                        "w-full shadow-none border border-amber-300 bg-amber-50 p-4 gap-3"
                    ):
                        with ui.row().classes("w-full items-start gap-3"):
                            ui.icon("warning_amber", color="amber-9", size="26px").classes(
                                "mt-0.5 shrink-0"
                            )
                            with ui.column().classes("gap-1 grow"):
                                ui.label(
                                    render_message("webui.load_security_operations.label.roles_have_profiles_containing_every_syste_c0e25901")
                                ).classes("font-semibold text-amber-10")
                                ui.label(
                                    render_message("webui.load_security_operations.label.each_role_below_is_assigned_a_profile_that_b60ce009")
                                ).classes("text-sm leading-6 text-amber-10")
                        with ui.column().classes("w-full gap-1 pl-9"):
                            for affected_role in full_privilege_roles:
                                with ui.row().classes("w-full items-center gap-2"):
                                    ui.icon("badge", size="18px").classes("text-amber-9")
                                    ui.label(
                                        render_message("webui.load_security_operations.label.code_name_10bd8f14", code=affected_role['code'], name=affected_role['name'])
                                    ).classes("grow text-sm font-medium")
                                    ui.badge(
                                        render_message("webui.load_security_operations.badge.profile_code_profile_name_119cb2e7", profile_code=affected_role['profile_code'], profile_name=affected_role['profile_name']),
                                        color=(
                                            "warning" if affected_role["is_builtin_bootstrap_profile"]
                                            else "amber-8"
                                        ),
                                    ).props("outline")
                                    ui.badge(
                                        localized_lifecycle_value(affected_role["status"]),
                                        color="warning",
                                    ).props("outline")
                                    if "organization.administer" in privileges:
                                        ui.button(
                                            icon="badge",
                                            on_click=lambda _, role_id=affected_role["id"]: select_role_details(role_id),
                                        ).props("flat round dense color=primary").tooltip(
                                            render_message("webui.load_security_operations.tooltip.open_role_92d6ce18")
                                        )

                with ui.grid(columns=2).classes("w-full gap-4"):
                    security_icon = "security"
                    denial_icon = "gpp_bad"
                    security_operation_facts = (
                        (summary["total_security_events"], render_message("webui.load_security_operations.text.security_events_a38a6da1"), security_icon, render_message("webui.load_security_operations.text.recognized_authentication_authorization_cl_b866a4b5")),
                        (summary["total_denials"], render_message("webui.load_security_operations.text.authorization_denials_09e48996"), denial_icon, authorization_denial_help),
                    )
                    for value, label, icon, help_text in security_operation_facts:
                        with ui.card().classes("shadow-none border border-slate-200 p-4 gap-1"):
                            with ui.row().classes("items-center gap-3"):
                                ui.icon(icon, color="primary")
                                ui.label(str(value)).classes("text-3xl font-semibold")
                            ui.label(label).classes("font-medium")
                            ui.label(help_text).classes("text-sm text-slate-500")

                ui.label(render_message("webui.load_security_operations.label.event_signals_4567e82a")).classes("text-lg font-semibold")
                ui.label(render_message("webui.load_security_operations.label.counts_by_security_operation_with_the_most_b43974c6")).classes("text-sm text-slate-500 -mt-4")
                if not summary["event_counts"]:
                    ui.label(render_message("webui.load_security_operations.label.no_security_events_in_this_period_c672277b")).classes("text-sm text-slate-400")
                for item in summary["event_counts"]:
                    with ui.grid(columns="minmax(220px, 1fr) minmax(320px, 2fr) 80px 170px").classes("w-full items-center gap-3 border-b border-slate-100 py-3"):
                        ui.label(event_label(item["operation"])).classes("font-medium").tooltip(item["operation"])
                        ui.label(security_event_help.get(item["operation"], render_message("webui.load_security_operations.label.security_relevant_activity_recorded_in_the_993f1e3d"))).classes("text-sm text-slate-500")
                        with ui.row().classes("w-full justify-center"):
                            ui.badge(str(item["count"]), color="primary").props("outline")
                        ui.label(format_timestamp(item["last_seen_at"])).classes("text-xs text-slate-500 text-right")

                ui.label(render_message("webui.load_security_operations.label.recent_security_events_1b6b711e")).classes("text-lg font-semibold mt-2")
                ui.label(
                    render_message("webui.load_security_operations.label.the_most_recent_security_related_events_in_649bc0ac")
                ).classes("text-sm text-slate-500 -mt-4")
                event_rows = [{
                    **item,
                    "actor": item.get("actor_name") or item.get("actor_email") or item.get("actor_type"),
                    "when": format_timestamp(item["occurred_at"]),
                    "signal": event_label(item["operation"]),
                    "decision": decision_code_label(item.get("decision_code")),
                } for item in summary.get("recent_events", [])]
                security_event_page = {"offset": 0}
                security_event_host = ui.element("div").classes(
                    "governance-card-list w-full"
                )
                with ui.row().classes("w-full items-center justify-end gap-2"):
                    security_event_page_label = ui.label().classes(
                        "text-sm text-slate-500"
                    )
                    security_event_previous = ui.button(
                        render_message("webui.load_security_operations.button.previous_49e3a635"), icon="chevron_left",
                    ).props("flat dense no-caps")
                    security_event_next = ui.button(
                        render_message("webui.load_security_operations.button.next_1b5d6dc7"), icon="chevron_right",
                    ).props("flat dense no-caps")

                async def open_security_event_target(row: dict[str, Any]) -> None:
                    entity_type = row.get("entity_type")
                    entity_id = row.get("entity_id")
                    try:
                        if entity_type == "aggregation":
                            await open_aggregation(await api.get("aggregations", entity_id))
                        elif entity_type == "record":
                            await select_record_details(entity_id)
                        elif entity_type == "org_unit":
                            await select_organization_unit_details(entity_id)
                        elif entity_type == "role":
                            await select_role_details(entity_id)
                        elif entity_type == "user":
                            await select_user_details(entity_id)
                        elif entity_type == "classification_scheme":
                            await select_classification_workspace(
                                initial_scheme_id=entity_id,
                            )
                        elif entity_type == "classification":
                            classification = await api.get("classifications", entity_id)
                            await select_classification_workspace(
                                initial_scheme_id=classification["classification_scheme_id"],
                                initial_classification_id=entity_id,
                            )
                    except ApiError as error:
                        if error.status_code == 404:
                            ui.notify(
                                render_message("webui.open_security_event_target.notify.this_target_no_longer_exists_2815aee4"), color="warning",
                            )
                        else:
                            show_api_error(error)

                def render_security_event_cards() -> None:
                    offset = security_event_page["offset"]
                    page_rows = event_rows[offset:offset + 10]
                    security_event_host.clear()
                    with security_event_host:
                        if not page_rows:
                            ui.label(render_message("webui.render_security_event_cards.label.no_recent_security_events_in_this_period_6d8fd436")).classes(
                                "w-full text-center text-slate-400 py-8"
                            )
                        for row in page_rows:
                            with ui.card().classes(
                                "governance-list-card governance-custody-assignment-card shadow-none"
                            ):
                                with ui.row().classes("w-full items-center no-wrap gap-3"):
                                    with ui.element("div").classes("governance-card-icon"):
                                        ui.icon("security", size="18px")
                                    ui.label(row["signal"]).classes(
                                        "font-semibold grow min-w-0"
                                    ).tooltip(row["operation"])
                                    ui.label(row["when"]).classes(
                                        "text-xs text-slate-500 whitespace-nowrap"
                                    )
                                with ui.element("div").classes(
                                    "governance-list-facts security-event-facts"
                                ):
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(render_message("webui.render_security_event_cards.label.account_actor_0d591ef2")).classes(
                                            "detail-field-label"
                                        )
                                        if row.get("actor_user_id"):
                                            actor_control = ui.row().classes(
                                                "items-center no-wrap gap-2 min-w-0 "
                                                "cursor-pointer text-primary"
                                            ).on(
                                                "click",
                                                lambda _, user_id=row["actor_user_id"]:
                                                    select_user_details(user_id),
                                            )
                                            actor_control.tooltip(render_message("webui.render_security_event_cards.tooltip.open_user_13542730"))
                                            with actor_control:
                                                render_user_avatar({
                                                    "id": row["actor_user_id"],
                                                    "name": row.get("actor_name"),
                                                    "email": row.get("actor_email"),
                                                }, size="26px")
                                                ui.label(row.get("actor") or "—").classes(
                                                    "text-sm truncate min-w-0"
                                                )
                                        else:
                                            with ui.row().classes(
                                                "items-center no-wrap gap-2 min-w-0"
                                            ):
                                                ui.icon("smart_toy", size="18px").classes(
                                                    "text-slate-400"
                                                )
                                                ui.label(row.get("actor") or "—").classes(
                                                    "text-sm truncate min-w-0"
                                                )
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(render_message("webui.render_security_event_cards.label.target_f4f7d136")).classes("detail-field-label")
                                        target_value = row.get("entity_label") or "—"
                                        target_supported = (
                                            not row.get("redacted")
                                            and row.get("entity_type") in {
                                                "aggregation", "record", "org_unit", "role",
                                                "user", "classification", "classification_scheme",
                                            }
                                        )
                                        target_label = ui.label(target_value).classes(
                                            "text-sm truncate w-full "
                                            + ("cursor-pointer text-primary" if target_supported else "")
                                        ).tooltip(target_value)
                                        if target_supported:
                                            target_label.on(
                                                "click",
                                                lambda _, item=row: open_security_event_target(item),
                                            )
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(render_message("webui.render_security_event_cards.label.decision_447868a3")).classes("detail-field-label")
                                        decision_value = row.get("decision") or "—"
                                        decision_label = ui.label(decision_value).classes(
                                            "text-sm truncate w-full"
                                        )
                                        if row.get("decision_code"):
                                            decision_label.tooltip(
                                                render_message("webui.render_security_event_cards.tooltip.technical_code_decision_code_f5bc7779", decision_code=row['decision_code'])
                                            )
                    start = offset + 1 if event_rows else 0
                    end = min(offset + 10, len(event_rows))
                    security_event_page_label.text = (
                        render_message("webui.render_security_event_cards.text.start_end_of_event_row_count_7e8f78d3", start=start, end=end, event_row_count=len(event_rows))
                    )
                    security_event_page_label.update()
                    (
                        security_event_previous.enable
                        if offset > 0 else security_event_previous.disable
                    )()
                    (
                        security_event_next.enable
                        if offset + 10 < len(event_rows)
                        else security_event_next.disable
                    )()

                def previous_security_events() -> None:
                    security_event_page["offset"] = max(
                        0, security_event_page["offset"] - 10,
                    )
                    render_security_event_cards()

                def next_security_events() -> None:
                    security_event_page["offset"] += 10
                    render_security_event_cards()

                security_event_previous.on("click", previous_security_events)
                security_event_next.on("click", next_security_events)
                render_security_event_cards()

                ui.label(render_message("webui.load_security_operations.label.denial_monitoring_9ac48ee1")).classes("text-lg font-semibold mt-2")
                ui.label(authorization_denial_help).classes("text-sm text-slate-500 -mt-4")
                if not summary["denial_groups"]:
                    ui.label(render_message("webui.load_security_operations.label.no_authorization_denials_occurred_in_this_3d7c10a2")).classes("text-sm text-positive")
                for item in summary["denial_groups"]:
                    with ui.card().classes("w-full shadow-none border border-slate-200 p-4 gap-1"):
                        with ui.row().classes("w-full items-center gap-3"):
                            ui.label(item["decision_code"].replace("_", " ").title()).classes("font-medium")
                            ui.label(item["required_privilege"]).classes("grow text-sm text-slate-500")
                            ui.badge(str(item["count"]), color="negative").props("outline")
                        ui.label(render_message("webui.load_security_operations.label.review_the_recent_events_above_or_open_the_dfa372aa")).classes("text-sm text-slate-500")

                if reconciliation is not None:
                    ui.separator()
                    ui.label(render_message("webui.load_security_operations.label.administrative_access_and_security_level_c_6d5dbfc3")).classes("text-lg font-semibold")
                    ui.label(
                        render_message("webui.load_security_operations.label.checks_that_at_least_one_active_person_can_a8d39836")
                    ).classes("text-sm text-slate-500 -mt-4")
                    hierarchy_count = reconciliation["hierarchy_violation_count"]
                    with ui.row().classes("w-full items-center gap-3 rounded-lg border p-3 " + ("border-red-200 bg-red-50" if hierarchy_count else "border-green-200 bg-green-50")):
                        ui.icon("warning" if hierarchy_count else "check_circle", color="negative" if hierarchy_count else "positive")
                        ui.label(render_message("webui.load_security_operations.label.hierarchy_count_security_hierarchy_violati_59d66fc7", hierarchy_count=hierarchy_count, value='s' if hierarchy_count != 1 else '')).classes("font-semibold grow")
                        ui.label(render_message("webui.load_security_operations.label.requires_investigation_45d92599") if hierarchy_count else render_message("webui.load_security_operations.label.no_invalid_parent_child_levels_found_9931a46f")).classes("text-sm text-slate-600")
                    for finding in reconciliation["findings"]:
                        if "governance_custodian" in finding["code"] or finding["code"] == "security_hierarchy_violation":
                            continue
                        with ui.row().classes("w-full items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3"):
                            ui.icon("warning", color="negative" if finding["severity"] == "critical" else "amber-8")
                            ui.label(finding["code"].replace("_", " ").title()).classes("font-semibold grow")
                            ui.badge(finding["severity"], color="negative" if finding["severity"] == "critical" else "warning")

        def change_period() -> None:
            custom_range.set_visibility(period.value == "custom")
            if period.value != "custom":
                background_tasks.create(load_security_operations())

        period.on_value_change(change_period)
        refresh.on("click", load_security_operations)
        apply_range.on("click", load_security_operations)
        await load_security_operations()

    async def select_saved_search_administration() -> None:
        privileges = set((auth_state.get("principal") or {}).get("global_privileges", []))
        if "search.saved_search.administer" not in privileges:
            ui.notify(error_message(ApiError(403, "insufficient_privilege")), color="negative")
            return
        page_key = "saved-search-administration"
        page_label = render_message("privilege.search.saved_search.administrator.name")
        register_navigation(page_key, page_label)
        show_authenticated_view()
        state.update(resource=page_key, rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
        title.text = page_label
        subtitle.text = render_message("privilege.search.saved_search.administrator.description")
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        table_container.clear()
        page = {"offset": 0, "limit": 25, "total": 0, "revision": 0}

        with table_container, ui.column().classes("w-full gap-4 p-4"):
            with ui.card().classes("w-full shadow-none border border-slate-200 p-4 gap-3"):
                with ui.row().classes("w-full gap-3 items-end flex-wrap"):
                    name_filter = ui.input(
                        render_message("webui.open_saved_search_dialog.input.search_saved_searches_3352fa10")
                    ).props("outlined dense clearable").classes("grow min-w-64")
                    owner_filter = ui.input(
                        render_message("saved_search.administration.filter.owner")
                    ).props("outlined dense clearable").classes("grow min-w-56")
                    created_from = ui.input(
                        render_message("saved_search.administration.filter.created_from")
                    ).props("outlined dense type=datetime-local clearable").classes("w-52")
                    created_before = ui.input(
                        render_message("saved_search.administration.filter.created_before")
                    ).props("outlined dense type=datetime-local clearable").classes("w-52")
                    apply_filters = ui.button(
                        render_message("webui.open_saved_search_dialog.button.apply_filters_63a71659"),
                        icon="filter_alt",
                    ).props("outline dense no-caps")
            list_host = ui.column().classes("w-full gap-3")
            with ui.row().classes("w-full items-center justify-center gap-2"):
                previous = ui.button(
                    render_message("webui.open_saved_search_dialog.button.previous_f6a88eee"), icon="chevron_left",
                ).props("flat no-caps")
                range_label = ui.label().classes("text-sm text-slate-500")
                following = ui.button(
                    render_message("webui.open_saved_search_dialog.button.next_ba38d6aa"), icon="chevron_right",
                ).props("flat no-caps")

        async def edit_saved_search(item: dict[str, Any]) -> None:
            state["admin_saved_search_id"] = int(item["id"])
            await select_advanced_search()

        async def delete_administered_search(item: dict[str, Any]) -> None:
            with ui.dialog() as dialog, ui.card().classes("w-[520px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.delete_saved_search.label.delete_name_3f400e6a", name=item["name"])).classes("text-lg font-semibold")
                ui.label(render_message("webui.delete_saved_search.label.this_permanently_deletes_the_saved_query_d_a0cf4b5a")).classes("text-sm text-slate-600")
                reason = ui.textarea(render_message("webui.delete_saved_search.textarea.reason_for_deletion_5aca706a")).props("outlined maxlength=500 autogrow").classes("w-full")
                error_label = ui.label().classes("text-sm text-negative")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.delete_saved_search.button.cancel_9711f5b2"), on_click=dialog.close).props("flat no-caps")
                    confirm = ui.button(render_message("webui.delete_saved_search.button.delete_saved_search_226c4222"), color="negative", icon="delete").props("unelevated no-caps")
                async def remove() -> None:
                    if not str(reason.value or "").strip():
                        error_label.text = render_message("webui.remove.text.a_reason_is_required_0adbb4d3")
                        return
                    try:
                        await api.delete_saved_search(int(item["id"]), int(item["version"]), str(reason.value).strip())
                    except ApiError as error:
                        error_label.text = error_message(error)
                        return
                    dialog.close()
                    await load_page()
                confirm.on("click", remove)
            dialog.open()

        async def load_page() -> None:
            page["revision"] += 1
            revision = page["revision"]
            params: dict[str, Any] = {"limit": page["limit"], "offset": page["offset"]}
            if str(name_filter.value or "").strip(): params["q"] = str(name_filter.value).strip()
            if str(owner_filter.value or "").strip(): params["owner_q"] = str(owner_filter.value).strip()
            if created_from.value: params["created_from"] = created_from.value
            if created_before.value: params["created_before"] = created_before.value
            try:
                result = await api.saved_search_administration(**params)
            except ApiError as error:
                if revision != page["revision"] or state.get("resource") != page_key: return
                list_host.clear()
                with list_host: ui.label(error_message(error)).classes("text-negative")
                return
            if revision != page["revision"] or state.get("resource") != page_key: return
            page["total"] = int(result["total"])
            list_host.clear()
            with list_host:
                if not result["items"]:
                    ui.label(render_message("webui.load_saved_page.label.no_saved_searches_match_these_filters_83501f8d")).classes("w-full text-center text-slate-500 py-8")
                for item in result["items"]:
                    owner = item.get("owner") or {}
                    with ui.card().classes("w-full shadow-none border border-slate-200 p-4"):
                        with ui.row().classes("w-full items-start gap-3 no-wrap"):
                            ui.icon("description" if item["resource_type"] == "record" else "folder", color="primary")
                            with ui.column().classes("gap-1 grow min-w-0"):
                                ui.label(item["name"]).classes("font-semibold")
                                ui.label(item.get("description") or render_message("webui.load_saved_page.label.no_description_e23ca0ad")).classes("text-sm text-slate-600")
                                ui.label((owner.get("localized") or {}).get("name") or owner.get("name") or owner.get("email") or "—").classes("text-xs text-slate-500")
                                ui.label(format_timestamp(item.get("date_created"))).classes("text-xs text-slate-500")
                            ui.button(icon="edit", on_click=lambda _, selected=item: edit_saved_search(selected)).props("flat round color=primary")
                            if (item.get("capabilities") or {}).get("delete") is True:
                                ui.button(icon="delete", color="negative", on_click=lambda _, selected=item: delete_administered_search(selected)).props("flat round")
            start = page["offset"] + 1 if result["items"] else 0
            range_label.text = render_message("webui.load_saved_page.text.start_value_of_total_eed8d817", start=start, value=page["offset"] + len(result["items"]), total=page["total"])
            previous.set_enabled(page["offset"] > 0)
            following.set_enabled(page["offset"] + page["limit"] < page["total"])

        async def apply_page_filters() -> None:
            page["offset"] = 0
            await load_page()
        async def move_page(delta: int) -> None:
            page["offset"] = max(0, page["offset"] + delta)
            await load_page()
        apply_filters.on("click", apply_page_filters)
        name_filter.on("keydown.enter", apply_page_filters)
        owner_filter.on("keydown.enter", apply_page_filters)
        previous.on("click", lambda: move_page(-page["limit"]))
        following.on("click", lambda: move_page(page["limit"]))
        await load_page()

    async def select_advanced_search() -> None:
        search_session_revision = state.get("advanced_search_session_revision", 0)
        search_principal = auth_state.get("principal")

        def search_session_is_current() -> bool:
            return (
                search_principal is not None
                and auth_state.get("principal") is search_principal
                and state.get("advanced_search_session_revision", 0) == search_session_revision
            )

        def search_view_is_current() -> bool:
            return (
                search_session_is_current()
                and state.get("resource") == "advanced-search"
                and not results_host.is_deleted
            )

        privileges = set((auth_state.get("principal") or {}).get("global_privileges", []))
        targets = {
            key: label for key, label, privilege in (
                ("records", render_message("advanced_search.resource.records"), "record.view"),
                ("aggregations", render_message("advanced_search.resource.aggregations"), "aggregation.view"),
            ) if privilege in privileges
        }
        if not targets:
            ui.notify(render_message("webui.select_advanced_search.notify.you_do_not_have_permission_to_use_advanced_019c4e37"), color="negative")
            return
        relation_sources = {
            field_name: (endpoint, label_fields)
            for field_name, endpoint, label_fields in (
            ("aggregation_id", "aggregations", ("aggregation_number", "title")),
            ("parent_aggregation_id", "aggregations", ("aggregation_number", "title")),
            ("classification_id", "classifications", ("code", "title")),
            ("security_level_id", "security-levels", ("code", "name")),
            ("owning_org_unit_id", "org-units", ("code", "name")),
            )
        }
        register_navigation("advanced-search", render_message("navigation.item.advanced_search"))
        show_authenticated_view()
        state.update(resource='advanced-search', rows=[], searched=False); aggregation_state.update(aggregation_detail=None)
        title.text = render_message("webui.select_advanced_search.text.advanced_search_509592d0")
        subtitle.text = render_message("webui.select_advanced_search.text.build_nested_searches_across_record_or_agg_b4682fe2")
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        table_container.clear()

        default_workspace: dict[str, Any] = {
            "resource": next(iter(targets)),
            "root": {"type": "group", "operator": "and", "children": [
                {"type": "condition", "kind": "structured", "field": "title", "operator": "contains_ci", "value": ""},
            ]},
            "sort_field": "id", "sort_direction": "asc", "limit": 25,
            "max_results": 1000, "offset": 0, "total": 0, "searched": False,
            "busy": False, "error": None, "saved": None, "baseline": None,
            "audience_mode": "private", "role_ids": [], "org_unit_ids": [],
            "search_name": "", "search_category": None, "search_description": "",
            "category_suggestions": [],
            "last_result": None,
            "expanded_results": [],
        }
        restored_workspace = state.get("advanced_search_workspace")
        workspace: dict[str, Any] = copy.deepcopy(restored_workspace) if isinstance(restored_workspace, dict) else default_workspace
        if workspace.get("resource") not in targets:
            workspace = default_workspace
        for key, value in default_workspace.items():
            workspace.setdefault(key, copy.deepcopy(value))
        workspace["busy"] = False
        # Browser history and saved client state can outlive the option sets
        # used by these selectors. NiceGUI rejects an initial value which is
        # not present in the selector's options, so normalize restored values
        # before constructing the controls.
        if workspace.get("sort_direction") not in {"asc", "desc"}:
            workspace["sort_direction"] = "asc"
        if workspace.get("limit") not in {25, 50, 100}:
            workspace["limit"] = 25

        with table_container:
            with ui.column().classes("advanced-search-page w-full gap-4 p-4"):
                with ui.column().classes("hidden"):
                    search_name = ui.input(value=workspace["search_name"])
                    search_category = ui.input(value=str(workspace.get("search_category") or ""))
                    search_description = ui.textarea(value=workspace["search_description"])
                workspace_layout = ui.element("div").classes("advanced-search-workspace-layout")
                workspace_layout.__enter__()
                with ui.card().classes("advanced-search-criteria-panel w-full p-4 shadow-none border border-slate-200"):
                    with ui.row().classes("advanced-search-target-row w-full items-end gap-4 flex-wrap"):
                        target = ui.select(targets, value=workspace["resource"], label=render_message("webui.select_advanced_search.select.search_for_410f853e")).props(
                            'outlined dense options-dense aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.search_target_27bbcc33"))
                        ).classes("w-56")
                        max_results = ui.number(render_message("advanced_search.field.maximum_results"), value=workspace["max_results"], min=1, max=5000, step=1).props(
                            'outlined dense aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.maximum_results_4993c5ac"))
                        ).classes("w-48")
                        ui.label(render_message("webui.select_advanced_search.label.system_maximum_5_000_77d23fb5")).classes("text-xs text-slate-500 pb-2")
                    ui.label(render_message("webui.select_advanced_search.label.criteria_ef9a8718")).classes("text-lg font-semibold mt-3")
                    ui.label(render_message("webui.select_advanced_search.label.nest_all_any_and_not_groups_up_to_50_condi_a3faa193")).classes("text-sm text-slate-500")
                    component_scope_help = ui.label(
                        render_message("webui.select_advanced_search.label.file_details_narrow_the_record_results_in_a8ddca60")
                    ).classes("text-sm text-blue-800 bg-blue-50 border border-blue-200 rounded-lg px-3 py-2")
                    validation_summary = ui.column().classes("w-full rounded-lg border border-red-200 bg-red-50 p-3 gap-1").props(
                        'role=alert tabindex=-1 aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.search_validation_summary_9c5c4e57"))
                    )
                    builder_host = ui.column().classes("w-full gap-3")
                    with ui.row().classes("advanced-search-sort-row w-full items-end gap-3 flex-wrap mt-2"):
                        sort_field = ui.select({}, label=render_message("webui.select_advanced_search.select.sort_by_ead29b06")).props("outlined dense options-dense").classes("w-60")
                        sort_direction = ui.select({"asc": render_message("webui.select_advanced_search.select.ascending_7ac56d5e"), "desc": render_message("webui.select_advanced_search.select.descending_b4342bd5")}, value=workspace["sort_direction"], label=render_message("webui.select_advanced_search.select.direction_c0ccf4a5")).props("outlined dense options-dense").classes("w-40")
                        page_size = ui.select({25: render_message("webui.select_advanced_search.select.page_size_25_3ce9d53c"), 50: render_message("webui.select_advanced_search.select.page_size_50_34f8a03e"), 100: render_message("webui.select_advanced_search.select.page_size_100_ac5cc8df")}, value=workspace["limit"], label=render_message("webui.select_advanced_search.select.page_size_cafb2ebd")).props("outlined dense options-dense").classes("w-40")
                    with ui.row().classes("advanced-search-submit-row w-full items-center gap-2 mt-2"):
                        search_advanced = ui.button(render_message("webui.select_advanced_search.button.search_97989f23"), icon="search").props("unelevated no-caps")
                        reset_advanced = ui.button(render_message("webui.select_advanced_search.button.reset_507afbb7"), icon="restart_alt").props("flat no-caps")
                        status_label = ui.label().classes("text-sm text-slate-500 ml-auto")
                with ui.card().classes("advanced-search-saved-panel w-full p-4 gap-3 shadow-none border border-slate-200"):
                    ui.label(render_message("webui.select_advanced_search.label.saved_search_6ccb135c")).classes("text-base font-semibold")
                    ui.label(render_message("webui.select_advanced_search.label.keep_or_reopen_useful_queries_5db11485")).classes("text-xs text-slate-500")
                    unsaved_context = ui.label(render_message("webui.select_advanced_search.label.this_query_has_not_been_saved_9eaee420")).classes(
                        "w-full rounded-lg bg-slate-50 p-3 text-xs text-slate-600"
                    )
                    saved_context = ui.column().classes("w-full gap-1 rounded-lg border border-blue-200 bg-blue-50 p-3")
                    saved_context.set_visibility(False)
                    with ui.column().classes("advanced-search-saved-actions w-full gap-2"):
                        save_button = ui.button(render_message("webui.select_advanced_search.button.save_search_f4158320"), icon="save").props("outline no-caps")
                        edit_details_button = ui.button(
                            render_message("webui.open_aggregation.button.edit_metadata_3ee4d255"),
                            icon="edit",
                        ).props("outline no-caps")
                        edit_details_button.tooltip(
                            render_message("webui.open_aggregation.button.edit_metadata_3ee4d255")
                        )
                        save_as_button = ui.button(render_message("webui.select_advanced_search.button.save_as_b7ca59d6"), icon="content_copy").props("outline no-caps")
                        open_button = ui.button(render_message("webui.select_advanced_search.button.open_saved_search_8bef667f"), icon="folder_open").props("outline no-caps")
                        new_button = ui.button(render_message("webui.select_advanced_search.button.new_search_635c50cb"), icon="add").props("flat no-caps")
                        delete_button = ui.button(render_message("webui.select_advanced_search.button.delete_f507983a"), icon="delete", color="negative").props("flat no-caps")
                workspace_layout.__exit__(None, None, None)
                freshness_host = ui.column().classes("w-full")
                results_host = ui.column().classes("w-full gap-3").props("aria-live=polite")
                with ui.row().classes("w-full items-center justify-center gap-2") as pagination:
                    first_page = ui.button(icon="first_page").props('flat round aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.first_page_8dfd5626")))
                    previous_page = ui.button(icon="chevron_left").props('flat round aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.previous_page_5a18f6b0")))
                    range_label = ui.label().classes("text-sm text-slate-600 min-w-36 text-center")
                    next_page = ui.button(icon="chevron_right").props('flat round aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.next_page_d75b42e2")))
                    last_page = ui.button(icon="last_page").props('flat round aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.last_page_d53f2dec")))
                pagination.set_visibility(False)

        def new_condition() -> dict[str, Any]:
            return {"type": "condition", "kind": "structured", "field": "title", "operator": "contains_ci", "value": ""}

        def persist_workspace() -> None:
            # A callback from a discarded identity must never restore its cache.
            if search_session_is_current():
                previous = state.get("advanced_search_workspace")
                if isinstance(previous, dict) and any(
                    previous.get(key) != workspace.get(key)
                    for key in ("root", "resource", "sort_field", "sort_direction", "max_results")
                ):
                    workspace["offset"] = 0
                state["advanced_search_workspace"] = copy.deepcopy(workspace)

        def set_advanced_result_expansion(identifier: int, expanded: bool) -> None:
            key = int(identifier)
            expanded_results = set(int(value) for value in workspace.get("expanded_results", []))
            (expanded_results.add if expanded else expanded_results.discard)(key)
            workspace["expanded_results"] = sorted(expanded_results)
            persist_workspace()

        def current_definition() -> dict[str, Any]:
            expression = compile_advanced_search_node(workspace["root"], workspace["resource"])
            request: dict[str, Any] = {
                "where": expression,
                "sort": [{"field": workspace["sort_field"], "direction": workspace["sort_direction"]}],
                "limit": int(workspace["limit"]), "offset": 0,
            }
            if advanced_search_has_positive_full_text(workspace["root"]):
                request["include"] = ["full_text_matches"]
            return {
                "schema_version": 1,
                "resource_type": "record" if workspace["resource"] == "records" else "aggregation",
                "max_results": max(1, min(5000, int(max_results.value or 1000))),
                "request": request,
            }

        def current_saved_payload() -> dict[str, Any]:
            return {
                "name": str(workspace.get("search_name") or "").strip(),
                "category": str(workspace.get("search_category") or "").strip() or None,
                "description": str(workspace.get("search_description") or "").strip() or None,
                "definition": current_definition(),
                "audience_mode": workspace["audience_mode"],
                "role_ids": sorted(int(value) for value in workspace["role_ids"]),
                "org_unit_ids": sorted(int(value) for value in workspace["org_unit_ids"]),
            }

        def current_saved_signature() -> str:
            try:
                value = current_saved_payload()
                # Page size is execution state, not an edit to saved criteria.
                value["definition"]["request"].pop("limit", None)
            except (TypeError, ValueError):
                value = {
                    "name": workspace.get("search_name"), "category": workspace.get("search_category"),
                    "description": workspace.get("search_description"), "root": workspace["root"],
                    "resource": workspace["resource"], "sort": workspace["sort_field"],
                    "direction": workspace["sort_direction"],
                    "maximum": max_results.value, "audience_mode": workspace["audience_mode"],
                    "role_ids": workspace["role_ids"], "org_unit_ids": workspace["org_unit_ids"],
                }
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

        def is_dirty() -> bool:
            baseline = workspace.get("baseline")
            if baseline is None:
                return False
            # Workspaces persisted before page-size exclusion carry the old
            # signature. Normalize that baseline without discarding real edits.
            value = json.loads(baseline)
            if "definition" in value:
                value["definition"]["request"].pop("limit", None)
            else:
                value.pop("limit", None)
            baseline = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            return current_saved_signature() != baseline

        async def confirm_discard_changes(action: str) -> bool:
            if not is_dirty():
                return True
            with ui.dialog() as dialog, ui.card().classes("w-[500px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.confirm_discard_changes.label.discard_unsaved_changes_8aacea70")).classes("text-lg font-semibold")
                ui.label(render_message("webui.confirm_discard_changes.label.your_changes_will_be_lost_if_you_action_b802686d", action=action)).classes("text-sm text-slate-600")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.confirm_discard_changes.button.keep_editing_965cc0ca"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
                    ui.button(render_message("webui.confirm_discard_changes.button.discard_changes_81df7dc9"), color="negative", on_click=lambda: dialog.submit(True)).props("unelevated no-caps")
            return bool(await dialog)

        state["discard_navigation_guard"] = confirm_discard_changes

        def render_saved_context() -> None:
            saved_context.clear()
            saved = workspace.get("saved")
            saved_context.set_visibility(saved is not None)
            unsaved_context.set_visibility(saved is None)
            if saved is None:
                return
            owner = saved.get("owner") or {}
            with saved_context:
                with ui.row().classes("w-full items-start gap-3"):
                    ui.icon("bookmark", color="primary")
                    with ui.column().classes("gap-0 grow min-w-0"):
                        ui.label(saved["name"]).classes("font-semibold")
                        ui.label(render_message("webui.render_saved_context.label.category_value_d60c970c", value=saved.get('category') or 'Uncategorized')).classes("text-xs text-slate-600")
                        ui.label(
                            render_message("webui.render_saved_context.label.owned_by_value_updated_format_timestamp_824cfbd4", value=(owner.get('localized') or {}).get('name') or owner.get('name') or 'Unknown owner', format_timestamp=format_timestamp(saved.get('date_updated')))
                        ).classes("text-xs text-slate-600")
                    ui.badge(render_message("webui.render_saved_context.badge.mine_74055dac") if saved.get("owner_user_id") == (auth_state.get("principal") or {}).get("user", {}).get("id") else render_message("webui.render_saved_context.badge.shared_d6938797")).props("outline")

        def refresh_saved_actions() -> None:
            saved = workspace.get("saved")
            capabilities = (saved or {}).get("capabilities") or {}
            has_save = "search.saved_search.save" in privileges
            editable = saved is None or capabilities.get("update") is True
            can_execute = saved is None or capabilities.get("execute") is True
            _, validation_error = validate_builder()
            structurally_valid = validation_error is None
            for control in (search_name, search_category, search_description, target, max_results, sort_field, sort_direction, page_size, reset_advanced):
                control.set_enabled(editable)
            if editable:
                builder_host.props(remove="inert aria-disabled")
                builder_host.classes(remove="pointer-events-none opacity-70")
            else:
                builder_host.props(add="inert aria-disabled=true")
                builder_host.classes(add="pointer-events-none opacity-70")
            search_advanced.set_enabled(can_execute and structurally_valid)
            # Navigation restoration can refresh controls outside their page slot.
            # Resolve the catalogue through the button's owning client.
            with save_button:
                save_button.text = render_message("webui.refresh_saved_actions.text.update_saved_search_31788e51") if saved is not None else render_message("webui.refresh_saved_actions.text.save_search_76b8ff5b")
            save_button.update()
            save_button.set_visibility((saved is None and has_save) or capabilities.get("update") is True)
            edit_details_button.set_visibility(
                saved is not None and capabilities.get("update") is True
            )
            save_as_button.set_visibility(has_save and saved is not None)
            save_button.set_enabled(structurally_valid)
            edit_details_button.set_enabled(structurally_valid)
            save_as_button.set_enabled(structurally_valid)
            delete_button.set_visibility(capabilities.get("delete") is True)
            render_saved_context()

        def load_saved_into_workspace(saved: dict[str, Any]) -> None:
            definition = saved["definition"]
            request = definition["request"]
            workspace["loading"] = True
            workspace["saved"] = saved
            workspace["resource"] = "records" if definition["resource_type"] == "record" else "aggregations"
            workspace["root"] = advanced_search_node_from_expression(request.get("where") or {
                "field": "title", "operator": "contains_ci", "value": "",
            })
            visible_sort = next((item for item in request.get("sort", []) if item["field"] != "id"), None)
            workspace["sort_field"] = (visible_sort or {"field": "id"})["field"]
            workspace["sort_direction"] = (visible_sort or {"direction": "asc"})["direction"]
            workspace["limit"] = int(request.get("limit", 25))
            workspace["max_results"] = int(definition.get("max_results", 1000))
            # A newly loaded definition has no execution results. Do not let
            # navigation restore cards belonging to the previous target/query.
            workspace.update(
                offset=0, total=0, searched=False, last_result=None,
                expanded_results=[], record_component_details={}, record_capabilities={},
            )
            workspace.pop("return_anchor", None)
            status_label.text = ""
            workspace["audience_mode"] = saved.get("audience_mode", "private")
            workspace["role_ids"] = list(saved.get("role_ids") or [])
            workspace["org_unit_ids"] = list(saved.get("org_unit_ids") or [])
            workspace["search_name"] = saved["name"]
            workspace["search_category"] = saved.get("category")
            workspace["search_description"] = saved.get("description") or ""
            if saved.get("category"):
                workspace["category_suggestions"] = sorted({
                    *workspace.get("category_suggestions", []), saved["category"],
                }, key=str.casefold)
            search_name.value = saved["name"]
            search_category.value = saved.get("category")
            search_description.value = saved.get("description")
            target.value = workspace["resource"]
            max_results.value = workspace["max_results"]
            page_size.value = workspace["limit"]
            sort_direction.value = workspace["sort_direction"]
            results_host.clear(); freshness_host.clear(); pagination.set_visibility(False)
            render_builder()
            workspace["loading"] = False
            workspace["baseline"] = current_saved_signature()
            refresh_saved_actions()
            persist_workspace()

        async def show_stale_saved_search(saved_search_id: int) -> None:
            with ui.dialog() as dialog, ui.card().classes("w-[500px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.show_stale_saved_search.label.this_saved_search_changed_29b608c2")).classes("text-lg font-semibold")
                ui.label(render_message("webui.show_stale_saved_search.label.another_update_was_saved_after_you_opened_626bc7b5")).classes("text-sm text-slate-600")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.show_stale_saved_search.button.cancel_40dedb50"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
                    ui.button(render_message("webui.show_stale_saved_search.button.reload_latest_600ddd0f"), on_click=lambda: dialog.submit(True)).props("unelevated no-caps")
            if await dialog:
                load_saved_into_workspace(await api.saved_search(saved_search_id))

        async def save_search(
            *, save_as: bool = False, edit_details: bool = False,
        ) -> None:
            _, validation_error = validate_builder()
            if validation_error:
                show_validation(validation_error); validation_summary.run_method("focus"); return
            saved = workspace.get("saved")
            capabilities = (saved or {}).get("capabilities") or {}
            creating = save_as or saved is None
            if not creating and not edit_details:
                payload = current_saved_payload()
                payload.update(
                    audience_mode=workspace["audience_mode"],
                    role_ids=list(workspace["role_ids"]),
                    org_unit_ids=list(workspace["org_unit_ids"]),
                )
                try:
                    save_button.disable()
                    updated = await api.update_saved_search(
                        int(saved["id"]), int(saved["version"]), payload,
                    )
                    load_saved_into_workspace(updated)
                    ui.notify(
                        render_message("webui.persist_saved_search.notify.saved_search_updated_7bd649da"),
                        color="positive",
                    )
                except ApiError as error:
                    save_button.enable()
                    if error.status_code == 409:
                        await show_stale_saved_search(int(saved["id"]))
                    else:
                        ui.notify(error_message(error), color="negative", close_button=True)
                return
            can_manage_audience = creating or capabilities.get("manage_audience") is True
            selected_role_ids = [int(value) for value in ([] if save_as else workspace["role_ids"])]
            selected_unit_ids = [int(value) for value in ([] if save_as else workspace["org_unit_ids"])]
            with ui.dialog() as dialog, ui.card().classes("w-[680px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.save_search.label.save_as_a_new_search_201a62ae") if save_as else (render_message("webui.save_search.label.save_search_9f72f967") if creating else render_message("webui.save_search.label.update_saved_search_09fb6c1c"))).classes("text-lg font-semibold")
                current_name = str(workspace.get("search_name") or "")
                name_control = ui.input(render_message("webui.save_search.input.name_76ae569a"), value=(f"{current_name} copy" if save_as and current_name else current_name)).props("outlined maxlength=120").classes("w-full")
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    category_control = ui.input(
                        render_message("webui.save_search.input.category_a403b84d"), value=str(workspace.get("search_category") or ""),
                        autocomplete=list(workspace.get("category_suggestions") or []),
                    ).props("outlined clearable maxlength=80").classes("grow min-w-56")
                    ui.label(render_message("webui.save_search.label.int_maximum_results_ae8080bb", int=format(int(max_results.value or 1000), ','))).classes("text-sm text-slate-500 self-center")
                description_control = ui.textarea(render_message("webui.save_search.textarea.description_491f6450"), value=workspace.get("search_description") or "").props("outlined maxlength=500 autogrow").classes("w-full")
                audience_mode = ui.radio({"private": render_message("webui.save_search.radio.only_me_739a9de4"), "shared": render_message("webui.save_search.radio.roles_or_organizational_units_01b067ca")}, value="private" if save_as else workspace["audience_mode"]).props("inline")
                audience_host = ui.column().classes("w-full gap-3")
                async def browse_audience(control: Any, kind: str) -> None:
                    async def choose(node: dict[str, Any]) -> bool:
                        try:
                            page = await api.saved_search_audience_options(kind, ids=[node["id"]], limit=1, offset=0)
                        except ApiError as error:
                            ui.notify(error_message(error), color="negative", close_button=True)
                            return False
                        if not page["items"]:
                            ui.notify(render_message("webui.saved_audience.ineligible"), color="warning")
                            return False
                        item = page["items"][0]
                        name = (item.get("localized") or {}).get("name") or item["name"]
                        options = {**dict(control.options), item["id"]: f"{name} ({item['code']})"}
                        control.set_options(options, value=list(dict.fromkeys([*(control.value or []), item["id"]])))
                        return True
                    await show_organization_structure(
                        selection_mode="role" if kind == "roles" else "org_unit", on_selection=choose,
                        saved_audience=kind,
                    )

                with audience_host:
                    role_control = ui.select({}, value=[], label=render_message("webui.save_search.select.roles_c2c266e1"), multiple=True, with_input=True).props("outlined use-chips options-dense clearable input-debounce=0").classes("w-full")
                    ui.label(render_message("webui.saved_audience.roles_help")).classes("text-xs text-slate-500")
                    with ui.row():
                        more_roles = ui.button(render_message("webui.render_collection.button.load_more_755f4879"), icon="more_horiz").props("flat dense no-caps")
                        ui.button(render_message("webui.saved_audience.browse_roles"), icon="account_tree", on_click=lambda: browse_audience(role_control, "roles")).props("flat dense no-caps")
                    unit_control = ui.select({}, value=[], label=render_message("webui.save_search.select.organizational_units_9c039bd2"), multiple=True, with_input=True).props("outlined use-chips options-dense clearable input-debounce=0").classes("w-full")
                    ui.label(render_message("webui.saved_audience.units_help")).classes("text-xs text-slate-500")
                    with ui.row():
                        more_units = ui.button(render_message("webui.render_collection.button.load_more_755f4879"), icon="more_horiz").props("flat dense no-caps")
                        ui.button(render_message("webui.saved_audience.browse_units"), icon="account_tree", on_click=lambda: browse_audience(unit_control, "org-units")).props("flat dense no-caps")
                    _, load_selected_roles = bind_remote_saved_audience_select(role_control, "roles", more_roles)
                    _, load_selected_units = bind_remote_saved_audience_select(unit_control, "org-units", more_units)
                    ui.label(render_message("webui.save_search.label.recipients_can_run_this_query_but_results_c13f331f")).classes("text-xs text-slate-500")
                error_label = ui.label().classes("text-sm text-negative")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.save_search.button.cancel_6ad2d1bd"), on_click=dialog.close).props("flat no-caps")
                    submit = ui.button(render_message("webui.save_search.button.save_53b01f94"), icon="save").props("unelevated no-caps")
                def audience_visibility() -> None:
                    audience_host.set_visibility(can_manage_audience and audience_mode.value == "shared")
                audience_mode.on_value_change(audience_visibility); audience_visibility()
                if not can_manage_audience:
                    audience_mode.disable()

                async def persist_saved_search() -> None:
                    name = str(name_control.value or "").strip()
                    if not name:
                        error_label.text = render_message("webui.persist_saved_search.text.name_is_required_90a7eeee"); return
                    mode = audience_mode.value
                    roles = list(role_control.value or []) if mode == "shared" else []
                    units = list(unit_control.value or []) if mode == "shared" else []
                    if mode == "shared" and not (roles or units):
                        error_label.text = render_message("webui.persist_saved_search.text.choose_at_least_one_role_or_organizational_2c3b3c87"); return
                    workspace["search_name"] = name
                    workspace["search_category"] = str(category_control.value or "").strip() or None
                    workspace["search_description"] = str(description_control.value or "").strip() or None
                    payload = current_saved_payload()
                    payload.update(audience_mode=mode, role_ids=roles, org_unit_ids=units)
                    try:
                        submit.disable()
                        if creating:
                            updated = await api.create_saved_search(payload)
                        else:
                            updated = await api.update_saved_search(
                                int(saved["id"]), int(saved["version"]), payload,
                            )
                        workspace["audience_mode"] = mode
                        workspace["role_ids"] = roles
                        workspace["org_unit_ids"] = units
                        dialog.close(); load_saved_into_workspace(updated)
                        ui.notify(render_message("webui.persist_saved_search.notify.saved_search_created_f6c7b94e") if creating else render_message("webui.persist_saved_search.notify.saved_search_updated_7bd649da"), color="positive")
                    except ApiError as error:
                        submit.enable()
                        if error.status_code == 409 and saved is not None:
                            dialog.close(); await show_stale_saved_search(int(saved["id"]))
                        else:
                            error_label.text = error_message(error)
                submit.on("click", persist_saved_search)
                await asyncio.gather(
                    load_selected_roles(selected_role_ids),
                    load_selected_units(selected_unit_ids),
                )
            dialog.open()

        async def open_saved_search_dialog() -> None:
            # This dialog is execution-oriented: All is strictly the union of
            # Mine and Shared with me. System-wide inventory belongs to the
            # dedicated Saved Search Administration screen.
            administrator = False
            with ui.dialog() as dialog, ui.card().classes("w-[900px] max-w-full max-h-[90vh] p-5 gap-4"):
                ui.label(render_message("webui.open_saved_search_dialog.label.open_saved_search_306aeadf")).classes("text-lg font-semibold")
                filters: dict[str, Any] = {"offset": 0, "limit": 25}
                with ui.row().classes("w-full gap-3 items-end flex-wrap"):
                    query_control = ui.input(render_message("webui.open_saved_search_dialog.input.search_saved_searches_3352fa10")).props("outlined dense clearable").classes("grow min-w-64")
                    filter_button = ui.button(render_message("webui.open_saved_search_dialog.button.filters_d413e321"), icon="tune").props("outline dense no-caps aria-expanded=false")
                with ui.tabs(value="all").props("dense no-caps align=left") as scope_control:
                    ui.tab("all", label=render_message("webui.open_saved_search_dialog.tab.all_d9a1fa9c"))
                    ui.tab("owned", label=render_message("webui.open_saved_search_dialog.tab.mine_74806472"))
                    ui.tab("shared_with_me", label=render_message("webui.open_saved_search_dialog.tab.shared_with_me_1300d28d"))
                advanced_filters = ui.column().classes("w-full gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3")
                advanced_filters.set_visibility(False)
                with advanced_filters:
                    with ui.row().classes("w-full gap-3 items-end flex-wrap"):
                        resource_control = ui.select({None: render_message("webui.open_saved_search_dialog.select.all_targets_fe147069"), "record": render_message("webui.open_saved_search_dialog.select.records_41634859"), "aggregation": render_message("webui.open_saved_search_dialog.select.aggregations_58e793f3")}, value=None, label=render_message("webui.open_saved_search_dialog.select.target_0edd3d27")).props("outlined dense options-dense clearable").classes("w-48")
                        category_filter = ui.input(render_message("webui.open_saved_search_dialog.input.category_d8c18ca4")).props("outlined dense clearable").classes("w-48")
                        apply_filters = ui.button(render_message("webui.open_saved_search_dialog.button.apply_filters_63a71659"), icon="filter_alt").props("outline dense no-caps")
                    if administrator:
                        ui.label(render_message("webui.open_saved_search_dialog.label.administrative_filters_ea190231")).classes("text-sm font-semibold text-slate-600")
                        with ui.row().classes("w-full gap-3 items-end flex-wrap"):
                            owner_filter = ui.number(render_message("webui.open_saved_search_dialog.number.owner_user_id_05651181"), min=1).props("outlined dense").classes("w-40")
                            with ui.column().classes("gap-1"):
                                role_filter = ui.select({}, label=render_message("webui.open_saved_search_dialog.select.role_audience_47211c66"), with_input=True).props("outlined dense clearable options-dense input-debounce=0").classes("w-52")
                                more_role_filters = ui.button(render_message("webui.render_collection.button.load_more_755f4879"), icon="more_horiz").props("flat dense no-caps")
                            with ui.column().classes("gap-1"):
                                unit_filter = ui.select({}, label=render_message("webui.open_saved_search_dialog.select.unit_audience_29a50f10"), with_input=True).props("outlined dense clearable options-dense input-debounce=0").classes("w-52")
                                more_unit_filters = ui.button(render_message("webui.render_collection.button.load_more_755f4879"), icon="more_horiz").props("flat dense no-caps")
                            bind_remote_saved_audience_select(role_filter, "roles", more_role_filters)
                            bind_remote_saved_audience_select(unit_filter, "org-units", more_unit_filters)
                            minimum_filter = ui.number(render_message("webui.open_saved_search_dialog.number.minimum_result_cap_32191a13"), min=1, max=5000).props("outlined dense").classes("w-44")
                            maximum_filter = ui.number(render_message("webui.open_saved_search_dialog.number.maximum_result_cap_87c75dd6"), min=1, max=5000).props("outlined dense").classes("w-44")
                            updated_from = ui.input(render_message("webui.open_saved_search_dialog.input.updated_from_6262aba2")).props("outlined dense type=datetime-local").classes("w-48")
                            updated_before = ui.input(render_message("webui.open_saved_search_dialog.input.updated_before_77f4bd93")).props("outlined dense type=datetime-local").classes("w-48")
                list_host = ui.column().classes("w-full gap-3 overflow-y-auto")
                with ui.row().classes("w-full items-center justify-center gap-2"):
                    previous = ui.button(render_message("webui.open_saved_search_dialog.button.previous_f6a88eee"), icon="chevron_left").props("flat no-caps")
                    page_label = ui.label().classes("text-sm text-slate-500")
                    following = ui.button(render_message("webui.open_saved_search_dialog.button.next_ba38d6aa"), icon="chevron_right").props("flat no-caps")

                async def select_saved_search(selected: dict[str, Any]) -> None:
                    if not await confirm_discard_changes("open another saved search"):
                        return
                    dialog.close()
                    load_saved_into_workspace(selected)

                saved_page_request = {"revision": 0}
                dialog.on("hide", lambda: saved_page_request.update(revision=saved_page_request["revision"] + 1))

                async def load_saved_page() -> None:
                    saved_page_request["revision"] += 1
                    revision = saved_page_request["revision"]
                    params: dict[str, Any] = {"limit": 25, "offset": filters["offset"]}
                    administrative_all = administrator and scope_control.value == "all"
                    if not administrative_all:
                        params["scope"] = scope_control.value
                    if query_control.value: params["q"] = str(query_control.value).strip()
                    if resource_control.value: params["resource_type"] = resource_control.value
                    if category_filter.value: params["category"] = str(category_filter.value).strip()
                    if administrative_all:
                        for key, control in (("owner_user_id", owner_filter), ("role_id", role_filter), ("org_unit_id", unit_filter), ("max_results_min", minimum_filter), ("max_results_max", maximum_filter), ("updated_from", updated_from), ("updated_before", updated_before)):
                            if control.value not in (None, ""): params[key] = control.value
                    try:
                        page = await (api.saved_search_administration(**params) if administrative_all else api.saved_searches(**params))
                        # Resolve only this page's audience IDs, in bounded parallel batches.
                        audience_names: dict[str, dict[int, str]] = {"roles": {}, "org-units": {}}
                        lookups = []
                        for kind, field in (("roles", "role_ids"), ("org-units", "org_unit_ids")):
                            ids = sorted({int(value) for item in page["items"] for value in item.get(field) or []})
                            lookups.extend((kind, ids[start:start + 50]) for start in range(0, len(ids), 50))
                        resolved_pages = await asyncio.gather(*(
                            api.saved_search_audience_options(kind, ids=ids, limit=50, offset=0)
                            for kind, ids in lookups
                        ))
                        for (kind, _), resolved_page in zip(lookups, resolved_pages):
                            for target in resolved_page["items"]:
                                name = (target.get("localized") or {}).get("name") or target["name"]
                                audience_names[kind][int(target["id"])] = f"{target['code']} — {name}"
                    except ApiError as error:
                        if revision != saved_page_request["revision"] or not search_view_is_current():
                            return
                        list_host.clear()
                        with list_host: ui.label(error_message(error)).classes("text-negative")
                        return
                    if revision != saved_page_request["revision"] or not search_view_is_current():
                        return
                    list_host.clear()
                    categories = {item.get("category") for item in page["items"] if item.get("category")}
                    workspace["category_suggestions"] = sorted({
                        *workspace.get("category_suggestions", []), *categories,
                    }, key=str.casefold)
                    with list_host:
                        if not page["items"]:
                            ui.label(render_message("webui.load_saved_page.label.no_saved_searches_match_these_filters_83501f8d")).classes("text-sm text-slate-500 py-8 self-center")
                        for item in page["items"]:
                            owner = item.get("owner") or {}
                            mine = item.get("owner_user_id") == (auth_state.get("principal") or {}).get("user", {}).get("id")
                            audience_label = render_message("webui.save_search.radio.only_me_739a9de4") if item.get("audience_mode") == "private" else render_message(
                                "webui.saved_search_metadata.audience",
                                roles=len(item.get("role_ids") or []), units=len(item.get("org_unit_ids") or []),
                            )
                            with ui.card().classes("w-full shadow-none border border-slate-200 p-4"):
                                with ui.grid(columns="auto minmax(0, 1fr) auto").classes("w-full items-start gap-3"):
                                    ui.icon("description" if item["resource_type"] == "record" else "folder", color="primary")
                                    with ui.column().classes("gap-1 min-w-0 break-words"):
                                        ui.label(item["name"]).classes("font-semibold")
                                        ui.label(item.get("description") or render_message("webui.load_saved_page.label.no_description_e23ca0ad")).classes("text-sm text-slate-600")
                                        ui.label(
                                            render_message("webui.load_saved_page.label.title_value_updated_format_timestamp_value_b78393c6", title=localized_editor_entity("records" if item["resource_type"] == "record" else "aggregations", item["resource_type"]), value=item.get('category') or render_message("webui.saved_search_metadata.uncategorized"), format_timestamp=format_timestamp(item['date_updated']), value_2=render_message("webui.saved_search_metadata.owned") if mine else render_message("webui.saved_search_metadata.shared_by", owner=str((owner.get('localized') or {}).get('name') or owner.get('name') or item['owner_user_id'])))
                                        ).classes("text-xs text-slate-500")
                                        ui.label(
                                            render_message("webui.load_saved_page.label.maximum_max_results_results_audience_label_1664749d", max_results=format(item['definition']['max_results'], ','), audience_label=audience_label)
                                        ).classes("text-xs text-slate-500")
                                        for kind, field, label_key in (
                                            ("roles", "role_ids", "webui.save_search.select.roles_c2c266e1"),
                                            ("org-units", "org_unit_ids", "webui.save_search.select.organizational_units_9c039bd2"),
                                        ):
                                            names = [audience_names[kind][int(value)] for value in item.get(field) or []
                                                     if int(value) in audience_names[kind]]
                                            if names:
                                                ui.label(render_message(label_key) + ": " + "; ".join(names)).classes("text-xs text-slate-500")
                                    ui.badge(render_message("webui.load_saved_page.badge.mine_47cb9b71") if mine else render_message("webui.load_saved_page.badge.shared_0a95a474"), color="blue-grey").props("outline")
                                ui.button(
                                    render_message("webui.load_saved_page.button.open_2606a7e0"), icon="folder_open",
                                    on_click=lambda _, selected=item: select_saved_search(selected),
                                ).props("flat dense no-caps")
                    start = page["offset"] + 1 if page["items"] else 0
                    page_label.text = render_message("webui.load_saved_page.text.start_value_of_total_eed8d817", start=start, value=page['offset'] + len(page['items']), total=page['total'])
                    previous.set_enabled(page["offset"] > 0)
                    following.set_enabled(page["offset"] + page["limit"] < page["total"])
                async def apply_page_filters() -> None:
                    filters["offset"] = 0; await load_saved_page()
                def toggle_filters() -> None:
                    visible = not advanced_filters.visible
                    advanced_filters.set_visibility(visible)
                    filter_button.props(f"aria-expanded={'true' if visible else 'false'}")
                async def change_page(delta: int) -> None:
                    filters["offset"] = max(0, filters["offset"] + delta); await load_saved_page()
                filter_button.on("click", toggle_filters)
                apply_filters.on("click", apply_page_filters)
                query_control.on("keydown.enter", apply_page_filters)
                if scope_control is not None:
                    scope_control.on_value_change(apply_page_filters)
                previous.on("click", lambda: change_page(-25)); following.on("click", lambda: change_page(25))
                await load_saved_page()
            dialog.open()

        async def delete_saved_search() -> None:
            saved = workspace.get("saved")
            if not saved: return
            with ui.dialog() as dialog, ui.card().classes("w-[520px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.delete_saved_search.label.delete_name_3f400e6a", name=saved['name'])).classes("text-lg font-semibold")
                ui.label(render_message("webui.delete_saved_search.label.this_permanently_deletes_the_saved_query_d_a0cf4b5a")).classes("text-sm text-slate-600")
                reason = ui.textarea(render_message("webui.delete_saved_search.textarea.reason_for_deletion_5aca706a")).props("outlined maxlength=500 autogrow").classes("w-full")
                error_label = ui.label().classes("text-sm text-negative")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.delete_saved_search.button.cancel_9711f5b2"), on_click=dialog.close).props("flat no-caps")
                    confirm = ui.button(render_message("webui.delete_saved_search.button.delete_saved_search_226c4222"), color="negative", icon="delete").props("unelevated no-caps")
                async def remove() -> None:
                    if not str(reason.value or "").strip(): error_label.text = render_message("webui.remove.text.a_reason_is_required_0adbb4d3"); return
                    try:
                        await api.delete_saved_search(int(saved["id"]), int(saved["version"]), str(reason.value).strip())
                        dialog.close(); reset_search(clear_metadata=True)
                        ui.notify(render_message("webui.remove.notify.saved_search_deleted_9cf582fa"), color="positive")
                    except ApiError as error:
                        if error.status_code == 409:
                            dialog.close(); await show_stale_saved_search(int(saved["id"]))
                        else: error_label.text = error_message(error)
                confirm.on("click", remove)
            dialog.open()

        def validate_builder() -> tuple[dict[str, Any] | None, str | None]:
            try:
                if advanced_search_leaf_count(workspace["root"]) > 50:
                    raise ValueError("A search can contain at most 50 conditions.")
                if advanced_search_depth(workspace["root"]) > 5:
                    raise ValueError("A search can be nested at most five levels.")
                return compile_advanced_search_node(workspace["root"], workspace["resource"]), None
            except ValueError as error:
                return None, str(error)

        def show_validation(message: str | None) -> None:
            validation_summary.clear()
            validation_summary.set_visibility(bool(message))
            if message:
                with validation_summary:
                    ui.label(render_message("webui.show_validation.label.check_the_search_criteria_225bbe77")).classes("font-semibold text-red-800")
                    ui.label(message).classes("text-sm text-red-700")

        def update_search_enabled() -> None:
            _, error = validate_builder()
            if error:
                search_advanced.disable()
            else:
                search_advanced.enable()
            show_validation(None)
            refresh_saved_actions()
            persist_workspace()

        def replace_node(parent: list[dict[str, Any]], index: int, value: dict[str, Any]) -> None:
            parent[index] = value
            render_builder()

        def remove_node(parent: list[dict[str, Any]], index: int) -> None:
            parent.pop(index)
            render_builder()

        def duplicate_node(parent: list[dict[str, Any]], index: int, node: dict[str, Any]) -> None:
            if advanced_search_leaf_count(workspace["root"]) + advanced_search_leaf_count(node) > 50:
                ui.notify(render_message("webui.duplicate_node.notify.a_search_can_contain_at_most_50_conditions_ea7ba8dc"), color="warning")
                return
            parent.insert(index + 1, json.loads(json.dumps(node)))
            render_builder()

        def negate_node(parent: list[dict[str, Any]], index: int, node: dict[str, Any]) -> None:
            parent[index] = {"type": "group", "operator": "not", "children": [node]}
            if advanced_search_depth(workspace["root"]) > 5:
                parent[index] = node
                ui.notify(render_message("webui.negate_node.notify.groups_can_be_nested_at_most_five_levels_d998427b"), color="warning")
                return
            render_builder()


        async def browse_advanced_relationship(field_name: str, target_control: Any) -> None:
            if field_name == "classification_id":
                await browse_advanced_classification(target_control)
            elif field_name == "owning_org_unit_id":
                await show_organization_structure(selection_mode="org_unit", target_control=target_control)
            elif field_name in {"aggregation_id", "parent_aggregation_id"}:
                await browse_advanced_aggregation(target_control)

        def render_condition(node: dict[str, Any], parent: list[dict[str, Any]], index: int) -> None:
            with ui.card().classes("advanced-search-condition w-full p-2 shadow-none border border-slate-200"):
                with ui.row().classes("advanced-search-condition-row w-full items-end gap-2 flex-wrap"):
                    kind = ui.select({"structured": render_message("webui.render_condition.select.metadata_65eb8656"), "full_text": render_message("webui.render_condition.select.full_text_3ef4f841")}, value=node.get("kind", "structured"), label=render_message("webui.render_condition.select.condition_type_5394683e")).props("outlined dense options-dense").classes("w-36")
                    if node.get("kind") == "full_text":
                        query_control = ui.input(render_message("webui.render_condition.input.search_words_or_phrase_f4d8da06"), value=node.get("query", "")).props("outlined dense clearable inputmode=search").classes("advanced-search-auto-value grow min-w-64")
                        query_control.on_value_change(lambda event: (
                            node.__setitem__("query", event.value or ""),
                            update_search_enabled(), refresh_sort_options(), persist_workspace(),
                        ))
                        if workspace["resource"] == "records":
                            sources = ui.select({"metadata": render_message("webui.render_condition.select.record_metadata_505c5130"), "components": render_message("webui.render_condition.select.file_names_and_content_b85754e5")}, value=node.get("sources") or ["metadata", "components"], label=render_message("webui.render_condition.select.sources_2eec501d"), multiple=True).props("outlined dense options-dense use-chips").classes("min-w-64")
                            sources.on_value_change(lambda event: (
                                node.__setitem__("sources", event.value or []),
                                update_search_enabled(), refresh_sort_options(), persist_workspace(),
                            ))
                    else:
                        fields = advanced_search_field_options(workspace["resource"],can_manage_disposition=bool((auth_state.get("principal") or {}).get("can_manage_disposition")))
                        if node.get("field")=="disposition_status" and "disposition_status" not in fields:
                            ui.label(disposition_text("restricted")).props("role=status")
                            return
                        field_name = node.get("field") if node.get("field") in fields else "title"
                        node["field"] = field_name
                        field_control = ui.select(fields, value=field_name, label=render_message("webui.render_condition.select.field_02092225")).props("outlined dense options-dense").classes("min-w-44 grow")
                        _, field_kind, nullable = ADVANCED_SEARCH_FIELDS[workspace["resource"]][field_name]
                        operators = advanced_search_operators(field_kind, nullable)
                        operator_name = node.get("operator") if node.get("operator") in operators else next(iter(operators))
                        node["operator"] = operator_name
                        operator_control = ui.select(operators, value=operator_name, label=render_message("webui.render_condition.select.operator_e4a90ad3")).props("outlined dense options-dense").classes("min-w-44")
                        if operator_name not in {"is_null", "is_not_null"}:
                            if field_kind == "boolean":
                                value_control = ui.select({True: render_message("webui.render_condition.select.yes_917fd8af"), False: render_message("webui.render_condition.select.no_b3020c97")}, value=node.get("value"), label=render_message("webui.render_condition.select.value_3acb61a0")).props("outlined dense options-dense clearable").classes("w-32")
                            elif operator_name == "between":
                                values = node.get("value") if isinstance(node.get("value"), list) else ["", ""]
                                if field_name in ADVANCED_SEARCH_RETENTION_FIELDS:
                                    first = ui.number(render_message("webui.render_condition.input.from_8e3ed147"), value=values[0] if values else None, min=0, step=1).props("outlined dense clearable dir=ltr").classes("advanced-search-technical-value min-w-40")
                                    second = ui.number(render_message("webui.render_condition.input.to_5f691965"), value=values[1] if len(values) > 1 else None, min=0, step=1).props("outlined dense clearable dir=ltr").classes("advanced-search-technical-value min-w-40")
                                else:
                                    first = ui.input(render_message("webui.render_condition.input.from_8e3ed147"), value=values[0] if values else "").props("outlined dense clearable").classes("min-w-40")
                                    second = ui.input(render_message("webui.render_condition.input.to_5f691965"), value=values[1] if len(values) > 1 else "").props("outlined dense clearable").classes("min-w-40")
                                if field_kind == "datetime":
                                    first.props(add="type=datetime-local dir=ltr").classes(add="advanced-search-technical-value")
                                    second.props(add="type=datetime-local dir=ltr").classes(add="advanced-search-technical-value")
                                first.on_value_change(lambda event: (node.__setitem__("value", [event.value, (node.get("value") or ["", ""])[1]]), update_search_enabled()))
                                second.on_value_change(lambda event: (node.__setitem__("value", [(node.get("value") or ["", ""])[0], event.value]), update_search_enabled()))
                                value_control = None
                            elif operator_name in {"in", "not_in"} and field_kind == "choice":
                                controlled_options = {
                                    value: render_message(message_key)
                                    for value, message_key in ADVANCED_SEARCH_CONTROLLED_VALUES[field_name].items()
                                }
                                selected_values = node.get("value") if isinstance(node.get("value"), list) else []
                                value_control = ui.select(
                                    controlled_options, value=[value for value in selected_values if value in controlled_options],
                                    label=render_message("webui.render_condition.select.value_3acb61a0"), multiple=True,
                                ).props("outlined dense options-dense clearable use-chips").classes("grow min-w-56")
                                value_control.on_value_change(lambda event: (node.__setitem__("value", event.value or []), update_search_enabled()))
                            elif operator_name in {"in", "not_in"}:
                                rendered = ", ".join(str(item) for item in node.get("value", [])) if isinstance(node.get("value"), list) else ""
                                value_control = ui.input(render_message("webui.render_condition.input.values_comma_separated_c3e84e2f"), value=rendered).props("outlined dense clearable").classes("advanced-search-auto-value grow min-w-56")
                                value_control.on_value_change(lambda event: (node.__setitem__("value", [part.strip() for part in str(event.value or "").split(",") if part.strip()][:100]), update_search_enabled()))
                            elif field_name in relation_sources:
                                endpoint, label_fields = relation_sources[field_name]
                                selected_value = node.get("value")
                                selected_label = str(node.get("_value_label") or "…")
                                value_control = ui.select(
                                    ({int(selected_value): selected_label} if selected_value is not None else {}),
                                    value=selected_value,
                                    label=render_message("webui.render_condition.select.value_3acb61a0"),
                                ).props("outlined dense clearable").classes("grow min-w-56")
                                style_relationship_chip_select(value_control, field_name)
                                bind_remote_relationship_select(
                                    value_control,
                                    resource=endpoint,
                                    search_fields=tuple(label_fields),
                                    label_fields=tuple(label_fields),
                                    on_options_resolved=lambda options, condition=node: (
                                        condition.__setitem__(
                                            "_value_label", options[int(condition["value"])]
                                        )
                                        if condition.get("value") is not None
                                        and int(condition["value"]) in options
                                        else None
                                    ),
                                )
                                value_control.on_value_change(
                                    lambda event, condition=node, control=value_control: (
                                        condition.__setitem__(
                                            "_value_label",
                                            dict(control.options or {}).get(event.value, ""),
                                        )
                                        if event.value is not None
                                        else condition.pop("_value_label", None)
                                    )
                                )
                                if field_name in {
                                    "aggregation_id", "parent_aggregation_id",
                                    "classification_id", "owning_org_unit_id",
                                }:
                                    ui.button(
                                        render_message("webui.render_condition.button.browse_3bc4c331"), icon="account_tree",
                                        on_click=lambda _, relationship_field=field_name, control=value_control:
                                            browse_advanced_relationship(relationship_field, control),
                                    ).props("flat dense no-caps color=primary")
                            elif field_name in ADVANCED_SEARCH_CONTROLLED_VALUES:
                                controlled_options = {
                                    value: render_message(message_key)
                                    for value, message_key in ADVANCED_SEARCH_CONTROLLED_VALUES[field_name].items()
                                }
                                selected_value = node.get("value")
                                if selected_value not in controlled_options:
                                    selected_value = None
                                    node["value"] = None
                                value_control = ui.select(
                                    controlled_options, value=selected_value, label=render_message("webui.render_condition.select.value_3acb61a0"),
                                ).props("outlined dense options-dense clearable").classes("grow min-w-56")
                                if field_name == "component.content_status":
                                    style_status_chip_select(value_control)
                            elif field_kind == "integer":
                                number_options = {"min": 0, "step": 1} if field_name in ADVANCED_SEARCH_RETENTION_FIELDS else {}
                                value_control = ui.number(render_message("advanced_search.field.value"), value=node.get("value"), **number_options).props("outlined dense clearable dir=ltr").classes("advanced-search-technical-value min-w-40")
                            else:
                                value_control = ui.input(render_message("webui.render_condition.input.value_8dc59edc"), value=node.get("value", "")).props("outlined dense clearable").classes("advanced-search-auto-value grow min-w-56")
                                if field_kind == "datetime":
                                    value_control.props(add="type=datetime-local dir=ltr").classes(add="advanced-search-technical-value")
                            if value_control is not None and operator_name not in {"in", "not_in"}:
                                value_control.on_value_change(lambda event: (node.__setitem__("value", event.value), update_search_enabled()))
                        field_control.on_value_change(lambda event: (
                            node.update(
                                field=event.value, operator="eq",
                                value=advanced_search_empty_value(
                                    event.value, "eq",
                                    ADVANCED_SEARCH_FIELDS[workspace["resource"]][event.value][1],
                                ),
                            ),
                            render_builder(),
                        ))
                        operator_control.on_value_change(lambda event: (
                            node.update(
                                operator=event.value,
                                value=advanced_search_empty_value(field_name, event.value, field_kind),
                            ),
                            render_builder(),
                        ))
                    kind.on_value_change(lambda event: (node.clear(), node.update(new_condition() if event.value == "structured" else {"type": "condition", "kind": "full_text", "query": "", "sources": ["metadata", "components"] if workspace["resource"] == "records" else ["metadata"]}), render_builder()))
                    with ui.row().classes("advanced-search-condition-actions items-center gap-0 self-end"):
                        ui.button(icon="block", on_click=lambda: negate_node(parent, index, node)).props('flat round dense aria-label=' + repr(render_message("webui.render_condition.accessible_name.negate_condition_0ee5684b"))).tooltip(render_message("webui.render_condition.tooltip.negate_9cd858a3"))
                        ui.button(icon="content_copy", on_click=lambda: duplicate_node(parent, index, node)).props('flat round dense aria-label=' + repr(render_message("webui.render_condition.accessible_name.duplicate_condition_2282d530"))).tooltip(render_message("webui.render_condition.tooltip.duplicate_93f8b940"))
                        ui.button(icon="delete", color="negative", on_click=lambda: remove_node(parent, index)).props('flat round dense aria-label=' + repr(render_message("webui.render_condition.accessible_name.remove_condition_6b0c8a12"))).tooltip(render_message("webui.render_condition.tooltip.remove_47af9389"))

        def render_group(node: dict[str, Any], parent: list[dict[str, Any]] | None = None, index: int = 0, depth: int = 1) -> None:
            labels = {"and": render_message("webui.render_group.text.all_c40a1b2b"), "or": render_message("webui.render_group.text.any_54504cd1"), "not": render_message("webui.render_group.text.not_2b98a4ad")}
            with ui.card().classes("advanced-search-group w-full p-2 shadow-none border-l-4 border-blue-300 bg-slate-50").props(
                'role=group aria-label=' + repr(render_message(
                    "advanced_search.group.accessible_name",
                    operator=labels.get(node.get("operator", "and"), render_message("advanced_search.group.boolean")),
                    depth=depth,
                ))
            ):
                with ui.row().classes("advanced-search-group-toolbar w-full items-center gap-2"):
                    group_operator = ui.select(labels, value=node.get("operator", "and"), label=render_message("webui.render_group.select.match_c4607f29")).props("outlined dense options-dense").classes("w-32")
                    ui.label(render_message("webui.render_group.label.level_depth_40cb374d", depth=depth)).classes("text-xs text-slate-500")
                    ui.space()
                    add_condition = ui.button(render_message("webui.render_group.button.condition_d5d2516f"), icon="add").props("flat dense no-caps")
                    add_group = ui.button(render_message("webui.render_group.button.group_3a670cc7"), icon="account_tree").props("flat dense no-caps")
                    if parent is not None:
                        ui.button(icon="block", on_click=lambda: negate_node(parent, index, node)).props('flat round dense aria-label=' + repr(render_message("webui.render_group.accessible_name.negate_group_bed5f9ae"))).tooltip(render_message("webui.render_group.tooltip.negate_12f5d3d7"))
                        ui.button(icon="content_copy", on_click=lambda: duplicate_node(parent, index, node)).props('flat round dense aria-label=' + repr(render_message("webui.render_group.accessible_name.duplicate_group_6c8dc686"))).tooltip(render_message("webui.render_group.tooltip.duplicate_fdc06841"))
                        ui.button(icon="delete", color="negative", on_click=lambda: remove_node(parent, index)).props('flat round dense aria-label=' + repr(render_message("webui.render_group.accessible_name.remove_group_2edf8a7e"))).tooltip(render_message("webui.render_group.tooltip.remove_58552cd7"))
                children_host = ui.column().classes("w-full gap-1 pl-2")
                children = node.setdefault("children", [])
                with children_host:
                    for child_index, child in enumerate(list(children)):
                        if child.get("type") == "group":
                            render_group(child, children, child_index, depth + 1)
                        else:
                            render_condition(child, children, child_index)
                if node.get("operator") == "not" and children:
                    add_condition.disable()
                    add_group.disable()

                def change_group_operator(event: Any) -> None:
                    previous_operator = node.get("operator", "and")
                    previous_children = list(children)
                    if event.value == "not" and len(children) > 1:
                        node["children"] = [{"type": "group", "operator": "and", "children": list(children)}]
                    node["operator"] = event.value
                    if advanced_search_depth(workspace["root"]) > 5:
                        node["operator"] = previous_operator
                        node["children"] = previous_children
                        ui.notify(render_message("webui.change_group_operator.notify.groups_can_be_nested_at_most_five_expressi_cb065045"), color="warning")
                    render_builder()

                group_operator.on_value_change(change_group_operator)
                add_condition.on("click", lambda: (children.append(new_condition()), render_builder()) if advanced_search_leaf_count(workspace["root"]) < 50 else ui.notify(render_message("webui.render_group.notify.a_search_can_contain_at_most_50_conditions_17aaa789"), color="warning"))
                add_group.on("click", lambda: (children.append({"type": "group", "operator": "and", "children": [new_condition()]}), render_builder()) if depth < 4 and advanced_search_leaf_count(workspace["root"]) < 50 else ui.notify(render_message("webui.render_group.notify.groups_can_be_nested_at_most_five_expressi_15cd18ec"), color="warning"))

        def render_builder() -> None:
            component_scope_help.set_visibility(
                workspace["resource"] == "records"
                and advanced_search_has_component_field(workspace["root"])
            )
            builder_host.clear()
            with builder_host:
                render_group(workspace["root"])
            update_search_enabled()
            refresh_sort_options()
            persist_workspace()

        def refresh_sort_options() -> None:
            options = {
                name: render_message(details[0])
                for name, details in ADVANCED_SEARCH_FIELDS[workspace["resource"]].items()
                if name not in ADVANCED_SEARCH_COMPONENT_FIELDS and name not in ADVANCED_SEARCH_RETENTION_FIELDS and (name!="disposition_status" or (auth_state.get("principal") or {}).get("can_manage_disposition"))
            }
            options["id"] = render_message("advanced_search.sort.identifier")
            try:
                expression = compile_advanced_search_node(workspace["root"], workspace["resource"])
                if advanced_search_has_positive_full_text(workspace["root"]):
                    options = {"_relevance": render_message("webui.refresh_sort_options.text.relevance_5632eeed"), **options}
            except ValueError:
                pass
            sort_field.options = options
            if workspace["sort_field"] not in options:
                workspace["sort_field"] = "_relevance" if "_relevance" in options else "id"
            sort_field.value = workspace["sort_field"]
            sort_field.update()

        async def execute_search() -> None:
            if not search_view_is_current():
                return
            expression, error = validate_builder()
            if error:
                show_validation(error)
                validation_summary.run_method("focus")
                return
            workspace.update(busy=True, error=None)
            search_advanced.disable()
            status_label.text = render_message("webui.execute_search.text.searching_ec84eae6")
            results_host.clear()
            with results_host:
                ui.spinner(size="lg").classes("self-center")
            try:
                maximum = max(1, min(5000, int(max_results.value or 1000)))
                workspace["max_results"] = maximum
                remaining = maximum - workspace["offset"]
                if remaining <= 0:
                    workspace["offset"] = 0
                    remaining = maximum
                payload = {
                    "where": expression,
                    "sort": [{"field": workspace["sort_field"], "direction": workspace["sort_direction"]}],
                    "limit": min(workspace["limit"], remaining), "offset": workspace["offset"],
                }
                if advanced_search_has_positive_full_text(workspace["root"]):
                    payload["include"] = ["full_text_matches"]
                saved = workspace.get("saved")
                if saved is not None and not is_dirty():
                    result = await api.execute_saved_search(
                        int(saved["id"]), {"limit": payload["limit"], "offset": payload["offset"]},
                    )
                else:
                    result = await api.search_request(workspace["resource"], payload)
                if not search_view_is_current():
                    return
                workspace["record_component_details"] = {}
                workspace["record_capabilities"] = {}
                if workspace["resource"] == "records":
                    async def load_matching_component_details(
                        record_item: dict[str, Any],
                    ) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
                        try:
                            record_id = int(record_item["id"])
                            capabilities, components = await asyncio.gather(
                                api.resource_capabilities("records", record_id),
                                api.component_page(record_id, limit=25),
                            )
                            return record_id, capabilities, components["items"]
                        except ApiError:
                            return int(record_item["id"]), {}, []
                    component_contexts = await asyncio.gather(*(
                        load_matching_component_details(record_item) for record_item in result.get("items", [])
                    ))
                    if not search_view_is_current():
                        return
                    workspace["record_component_details"] = {
                        record_id: components for record_id, _, components in component_contexts
                    }
                    workspace["record_capabilities"] = {
                        record_id: capabilities for record_id, capabilities, _ in component_contexts
                    }
                workspace["total"] = min(int(result["total"]), maximum)
                workspace["searched"] = True
                render_results(result)
            except ApiError as api_error:
                if not search_view_is_current():
                    return
                results_host.clear()
                with results_host, ui.card().classes("w-full border border-red-200 bg-red-50 p-4 shadow-none"):
                    ui.label(render_message_plain("webui.execute_search.label.the_search_could_not_be_completed_f959e209")).classes("font-semibold text-red-800")
                    ui.label(error_message(api_error)).classes("text-sm text-red-700")
                status_label.text = render_message("webui.execute_search.text.search_failed_e44b669e")
            finally:
                workspace["busy"] = False
                if search_view_is_current():
                    search_advanced.enable()
                    persist_workspace()

        def render_results(result: dict[str, Any]) -> None:
            if not search_view_is_current():
                return
            workspace["last_result"] = copy.deepcopy(result)
            results_host.clear()
            freshness_host.clear()
            freshness = result.get("index_freshness") or {}
            if freshness.get("has_pending_content"):
                with freshness_host, ui.card().classes("w-full p-3 shadow-none border border-amber-200 bg-amber-50"):
                    with ui.row().classes("w-full items-center gap-2"):
                        ui.icon("hourglass_top").classes("text-amber-700")
                        ui.label(render_message("webui.render_results.label.some_authorized_file_content_is_still_bein_598843e0")).classes("text-sm text-amber-900")
            items = result.get("items", [])
            start = workspace["offset"] + 1 if items else 0
            end = workspace["offset"] + len(items)
            total = workspace["total"]
            status_label.text = render_message("webui.render_results.text.total_authorized_result_value_da53e146", total=format(total, ','), value='s' if total != 1 else '')
            range_label.text = render_message("webui.render_results.text.start_end_of_total_a1dbcf9a", start=format(start, ','), end=format(end, ','), total=format(total, ','))
            pagination.set_visibility(total > 0)
            first_page.set_enabled(workspace["offset"] > 0)
            previous_page.set_enabled(workspace["offset"] > 0)
            next_page.set_enabled(end < total)
            last_page.set_enabled(end < total)
            if not items:
                with results_host, ui.card().classes("w-full p-8 items-center shadow-none border border-slate-200"):
                    ui.icon("search_off", size="42px").classes("text-slate-400")
                    ui.label(render_message("webui.render_results.label.no_authorized_results_matched_this_search_897e7e5e")).classes("font-semibold")
                    ui.label(render_message("webui.render_results.label.change_a_condition_or_broaden_the_criteria_da24d5dc")).classes("text-sm text-slate-500")
                return
            with results_host:
                with ui.column().classes("compact-result-list w-full gap-0"):
                    uses_full_text = advanced_search_has_positive_full_text(workspace["root"])
                    for item in items:
                        search_meta = item.get("_search") or {}
                        authorized_component_details = {
                            int(component["id"]): component
                            for component in workspace.get("record_component_details", {}).get(int(item["id"]), [])
                        }
                        matching_components = [
                            {**authorized_component_details.get(int(component["id"]), {}), **component}
                            for component in search_meta.get("matching_components", [])
                            if component.get("id") is not None
                        ]
                        record_capabilities = workspace.get("record_capabilities", {}).get(
                            int(item["id"]), {}
                        )
                        if workspace["resource"] == "records":
                            displayed_components = (
                                matching_components if uses_full_text
                                else list(authorized_component_details.values())
                            )
                            render_compact_resource_result(
                                "records", item,
                                on_open=lambda selected: open_advanced_record(int(selected["id"]),selected.get("disposition_status")),
                                components=displayed_components,
                                metadata_matched=bool(search_meta.get("metadata_matched")),
                                content_matched=bool(matching_components),
                                show_medium=True,
                                can_preview=bool(
                                    record_capabilities.get("view_component")
                                    and any(component_is_previewable(component) for component in authorized_component_details.values())
                                ),
                                can_expand_components=bool(
                                    record_capabilities.get("list_components") and displayed_components
                                ),
                                components_are_matches=uses_full_text,
                                initially_expanded=int(item["id"]) in set(
                                    int(value) for value in workspace.get("expanded_results", [])
                                ),
                                on_expansion_changed=lambda expanded, identifier=int(item["id"]):
                                    set_advanced_result_expansion(identifier, expanded),
                            )
                        else:
                            render_compact_resource_result(
                                "aggregations", item,
                                on_open=lambda selected: open_advanced_aggregation(int(selected["id"]),selected.get("disposition_status")),
                                metadata_matched=bool(search_meta.get("metadata_matched")),
                                show_medium=True,
                            )
            restore_compact_result_anchor(workspace.pop("return_anchor", None))

        async def open_destroyed_search_result(kind: str, identifier: int):
            from frontend.webui.disposition.destruction import retained_detail
            try:proof=await api.disposition_page(f"retained/{kind}/{identifier}")
            except ApiError as error:
                if search_view_is_current():ui.notify(error_message(error),type='negative')
                return
            if search_view_is_current():await retained_detail(api=api,proof=proof,active=search_view_is_current,on_error=error_message,format_timestamp=format_timestamp)

        async def open_advanced_record(identifier: int, disposition_status: int | None = None) -> None:
            if disposition_status==10:
                await open_destroyed_search_result('record',identifier)
                return
            workspace["return_anchor"] = f"compact-result-records-{int(identifier)}"
            persist_workspace()
            state.pop("discard_navigation_guard", None)
            await select_record_details(identifier)

        async def open_advanced_aggregation(identifier: int, disposition_status: int | None = None) -> None:
            if disposition_status==10:
                await open_destroyed_search_result('aggregation',identifier)
                return
            workspace["return_anchor"] = f"compact-result-aggregations-{int(identifier)}"
            persist_workspace()
            state.pop("discard_navigation_guard", None)
            await open_aggregation(await api.get("aggregations", identifier))

        async def confirm_target_reset() -> bool:
            with ui.dialog() as dialog, ui.card().classes("w-[480px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.confirm_target_reset.label.change_search_target_bc42440d")).classes("text-lg font-semibold")
                ui.label(render_message("webui.confirm_target_reset.label.changing_the_target_resets_all_criteria_be_f52ba27b")).classes("text-sm text-slate-600")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.confirm_target_reset.button.cancel_6f1ce483"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
                    ui.button(render_message("webui.confirm_target_reset.button.change_target_31a62b29"), on_click=lambda: dialog.submit(True)).props("unelevated no-caps")
            return bool(await dialog)

        async def change_target(event: Any) -> None:
            if workspace.get("loading") or not search_view_is_current():
                return
            requested = event.value
            # NiceGUI may deliver programmatic value-change events after loading
            # has finished. Ignore superseded events and already-applied values.
            if requested != target.value or requested == workspace["resource"]:
                return
            was_dirty = is_dirty()
            if was_dirty or workspace.get("saved") is not None:
                confirmed = await confirm_target_reset()
                if not confirmed:
                    target.value = workspace["resource"]
                    target.update()
                    return
            # A target change starts a new search; the loaded saved search is
            # left intact and must no longer supply metadata or update actions.
            workspace["resource"] = requested
            reset_search(clear_metadata=True)

        def reset_search(*, clear_metadata: bool = False) -> None:
            workspace.update(root={"type": "group", "operator": "and", "children": [new_condition()]}, sort_field="id", sort_direction="asc", limit=25, max_results=1000, offset=0, total=0, searched=False, last_result=None)
            workspace.update(expanded_results=[], record_component_details={}, record_capabilities={})
            workspace.pop("return_anchor", None)
            if clear_metadata:
                workspace.update(
                    saved=None, audience_mode="private", role_ids=[], org_unit_ids=[],
                    search_name="", search_category=None, search_description="",
                )
                search_name.value = ""; search_category.value = None; search_description.value = ""
            max_results.value = 1000
            page_size.value = 25
            sort_direction.value = "asc"
            results_host.clear()
            freshness_host.clear()
            pagination.set_visibility(False)
            status_label.text = ""
            render_builder()
            refresh_sort_options()
            workspace["baseline"] = current_saved_signature()
            refresh_saved_actions()
            persist_workspace()

        async def start_new_search() -> None:
            if await confirm_discard_changes("start a new search"):
                reset_search(clear_metadata=True)

        async def move_page(offset: int) -> None:
            workspace["offset"] = max(0, min(offset, max(0, workspace["total"] - 1)))
            workspace["offset"] = (workspace["offset"] // workspace["limit"]) * workspace["limit"]
            await execute_search()

        target.on_value_change(change_target)
        max_results.on_value_change(lambda event: (
            workspace.__setitem__("max_results", max(1, min(5000, int(event.value or 1000)))),
            persist_workspace(),
        ))
        sort_field.on_value_change(lambda event: (workspace.__setitem__("sort_field", event.value), persist_workspace()))
        sort_direction.on_value_change(lambda event: (workspace.__setitem__("sort_direction", event.value), persist_workspace()))
        page_size.on_value_change(lambda event: (workspace.update(limit=int(event.value), offset=0), persist_workspace()))
        search_advanced.on("click", execute_search)
        reset_advanced.on("click", reset_search)
        new_button.on("click", start_new_search)
        open_button.on("click", open_saved_search_dialog)
        save_button.on("click", lambda: save_search(save_as=False))
        edit_details_button.on(
            "click", lambda: save_search(save_as=False, edit_details=True),
        )
        save_as_button.on("click", lambda: save_search(save_as=True))
        delete_button.on("click", delete_saved_search)
        first_page.on("click", lambda: move_page(0))
        previous_page.on("click", lambda: move_page(workspace["offset"] - workspace["limit"]))
        next_page.on("click", lambda: move_page(workspace["offset"] + workspace["limit"]))
        last_page.on("click", lambda: move_page(max(0, workspace["total"] - 1)))
        administered_search_id = state.pop("admin_saved_search_id", None)
        if administered_search_id is not None:
            try:
                load_saved_into_workspace(await api.saved_search(int(administered_search_id)))
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                render_builder()
        else:
            render_builder()
        if workspace.get("baseline") is None:
            workspace["baseline"] = current_saved_signature()
        refresh_saved_actions()
        if workspace.get("searched") and isinstance(workspace.get("last_result"), dict):
            render_results(workspace["last_result"])
        persist_workspace()

    async def open_related_resource(kind: str, identity: int) -> None:
        if kind == "record":
            await select_record_details(identity)
        else:
            await open_aggregation(await api.get("aggregations", identity))

    def enter_application_settings() -> None:
        """Adapt the Settings feature to the existing shared shell."""
        state.update(resource='application-settings', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
        register_navigation("application-settings", render_message("navigation.item.application_settings"))
        show_authenticated_view()
        title.text = render_message("navigation.item.application_settings")
        subtitle.text = render_message("settings.page.subtitle")
        guidance.text = ""
        for control in (search_bar, aggregation_mode_bar, add_button, add_record_button):
            control.set_visibility(False)
        table_container.clear()

    def persist_application_settings_category() -> None:
        if navigation_controller.trail and navigation_controller.trail[-1]["page"] == "application-settings":
            navigation_controller.trail[-1]["state"] = current_navigation_snapshot()
            persist_navigation_trail()

    async def select_disposition(page="disposition-eligibility", identity=None, saved=None, target_job=None, task_id=None):
        principal=auth_state.get("principal")
        if not principal or not can_navigate_disposition(page, principal):
            return
        task_id=task_id or (saved or {}).get("task_id")
        if task_id and page=="disposition-job":page="disposition-task"
        token=object()
        label=disposition_text("templates" if page=="disposition-templates" else "current_task" if task_id else "workspace_details" if page=="disposition-job" else "my_tasks" if page=="disposition-tasks" else "eligibility" if page=="disposition-eligibility" else "jobs")
        register_navigation(page,label,entity_id=task_id if page=="disposition-task" else identity)
        state.update(resource=page, disposition_page_token=token, rows=[], searched=True, disposition_view={**dict(saved or {}), **({'task_id': task_id, 'job_id': identity} if task_id else {})}); aggregation_state.update(aggregation_detail=None)
        show_authenticated_view();title.text=label;subtitle.text="";guidance.text=""
        for control in (search_bar,aggregation_mode_bar,add_button,add_record_button):control.set_visibility(False)
        table_container.clear()
        def active():
            return auth_state.get("principal") is principal and state.get("resource")==page and state.get("disposition_page_token") is token
        def remember(value):
            if active():
                state["disposition_view"]=value
                if navigation_controller.trail and navigation_controller.trail[-1]["page"]==page:
                    navigation_controller.trail[-1]["state"]=current_navigation_snapshot();persist_navigation_trail()
        async def open_tasks():await select_disposition("disposition-tasks")
        async def open_approval_results(identity):await select_disposition("disposition-job",identity,saved={"section":"documents","approval_results":True})
        async def open_job(identity):await select_disposition("disposition-job",identity)
        async def open_task(job_id,identity):await select_disposition("disposition-job",job_id,task_id=identity)
        async def refresh_workspace(view):
            await select_disposition(page,identity,saved=view,task_id=task_id)
        def register_dirty(dirty):
            async def guard(action):
                if dirty():
                    ui.notify(disposition_text("unsaved_warning"),type="warning");return False
                return True
            state["discard_navigation_guard"]=guard
        async def open_eligibility(job_id):await select_disposition("disposition-eligibility",target_job=job_id)
        async def open_resource(kind,identity):await guarded_page_navigation(lambda:open_related_resource(kind,identity))
        common=dict(api=api,container=table_container,active=active,on_error=error_message,
                    bind_remote=bind_remote_relationship_select,open_job=open_job)
        try:
            if page in ("disposition-job","disposition-task"):
                await job_screen(**common,identity=identity,open_eligibility=open_eligibility,
                                 open_resource=open_resource,format_timestamp=format_timestamp,event_label=event_label,preview=preview_record_components,task_id=task_id,register_dirty=register_dirty,browse_resource=browse_advanced_aggregation,open_task=open_task,open_tasks=open_tasks,open_approval_results=open_approval_results,saved=saved,remember=remember,refresh_workspace=refresh_workspace)
            elif page=="disposition-templates":
                from .disposition.templates import templates_screen
                await templates_screen(api=api,container=table_container,active=active,on_error=error_message,format_timestamp=format_timestamp)
            elif page=="disposition-tasks":
                filter_preference_key=f"disposition_task_filters:{principal['user']['id']}"
                def remember_task_filters(expanded):
                    if active():
                        app.storage.user[filter_preference_key]=bool(expanded)
                await tasks_screen(**common,open_task=open_task,format_timestamp=format_timestamp,saved=saved,remember=remember,
                                   filters_expanded=app.storage.user.get(filter_preference_key,False),
                                   remember_filters=remember_task_filters)
            elif page=="disposition-eligibility":
                filter_preference_key=f"disposition_eligibility_filters:{principal['user']['id']}"
                def remember_eligibility_filters(expanded):
                    if active():
                        app.storage.user[filter_preference_key]=bool(expanded)
                await eligibility_screen(**common,open_resource=open_resource,format_timestamp=format_timestamp,
                                         saved=saved,remember=remember,target_job=target_job,
                                         filters_expanded=app.storage.user.get(filter_preference_key,False),
                                         remember_filters=remember_eligibility_filters)
            else:
                filter_preference_key=f"disposition_job_filters:{principal['user']['id']}"
                def remember_job_filters(expanded):
                    if active():
                        app.storage.user[filter_preference_key]=bool(expanded)
                await jobs_screen(**common,saved=saved,remember=remember,
                                  filters_expanded=app.storage.user.get(filter_preference_key,False),
                                  remember_filters=remember_job_filters)
        except asyncio.CancelledError:
            return
        except ApiError as error:
            if active():
                with table_container:ui.label(error_message(error)).classes("text-negative").props("role=alert")

    def enter_relationship_types() -> None:
        """Adapt relationship-type administration to the existing shared shell."""
        state.update(resource='relationship-types', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
        register_navigation("relationship-types", localized_navigation["relationship-types"])
        show_authenticated_view()
        title.text = localized_navigation["relationship-types"]
        subtitle.text = ""
        guidance.text = ""
        for control in (search_bar, aggregation_mode_bar, add_button, add_record_button):
            control.set_visibility(False)
        table_container.clear()

    async def select_messages(mailbox: str = "inbox") -> None:
        principal = auth_state.get("principal")
        if principal is None:
            return
        key = "messages-" + mailbox
        if not can_navigate(key, principal.get("global_privileges", [])):
            return
        show_authenticated_view()
        state.update(resource=key, rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
        token = object()
        state["messaging_workspace_token"] = token
        register_navigation(key, localized_navigation[key])
        title.text = localized_navigation[key]
        subtitle.text = ""
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        table_container.clear()

        async def open_message_resource(kind, identity):
            if kind == "aggregation":
                await open_aggregation(await api.get("aggregations", identity))
            elif kind == "record":
                await show_record_details(await api.get("records", identity))
            else:
                component = await api.get("digital-components", identity)
                await show_record_details(await api.get("records", component["record_id"]))

        async def inspect_message_resource(kind, identity, picker_active):
            await resource_inspector(api=api, kind=kind, identity=identity,
                active=picker_active, preview=preview_record_components,
                field_label=entity_metadata_label, format_timestamp=format_timestamp,
                medium_label=medium_label, on_error=lambda error: ui.notify(
                    error_message(error), color="negative", close_button=True))

        async def capture_message(envelope_id, root_id):
            capture_dialog = ui.dialog().props("persistent")
            opening = {"closed": False}
            def capture_active():
                return (not opening["closed"] and auth_state.get("principal") is principal
                        and state.get("messaging_workspace_token") is token)
            def cancel_opening():
                opening["closed"] = True
                capture_dialog.close()
            with capture_dialog, ui.card().classes("w-full gap-4").style("width: 1050px; max-width: calc(100vw - 32px)"):
                ui.label(render_message("webui.open_record_draft_editor.label.create_record_080740e1")).classes("text-xl font-semibold")
                with ui.row().classes("w-full items-center"):
                    ui.spinner(size="sm")
                    ui.label(render_message("messaging.capture.preparing")).classes("grow")
                ui.skeleton().classes("w-full h-24")
                with ui.row().classes("w-full justify-end"):
                    ui.button(render_message("webui.open_record_draft_editor.button.cancel_draft_84ea17b5"), on_click=cancel_opening).props("flat")
                    ui.button(render_message("webui.open_record_draft_editor.button.create_record_dd0193d6"), icon="check").disable()
            capture_dialog.open()
            params = {"root_id":root_id} if root_id else {}
            try:
                draft = await api.request("GET", f"/api/v1/messages/{envelope_id}/capture-preview", params=params)
            except ApiError as error:
                capture_dialog.close()
                if capture_active():
                    ui.notify(error_message(error),color="negative",close_button=True)
                return
            if not capture_active():
                capture_dialog.close()
                return
            async def prepare_pdfs():
                return await api.request("POST", f"/api/v1/messages/{envelope_id}/capture", params=params,timeout=660)
            await open_record_draft_editor(existing_capture_draft=draft,
                on_committed=lambda _:select_messages(mailbox),capture_active=capture_active,
                capture_loader=prepare_pdfs,capture_dialog=capture_dialog)

        if mailbox == "monitor":
            await messaging_monitor(api=api,container=table_container,
                active=lambda:auth_state.get("principal") is principal and state.get("messaging_workspace_token") is token and state.get("resource")==key,
                format_timestamp=format_timestamp,
                open_audit=lambda:guarded_page_navigation(
                    lambda:select_audit_trail(initial_entity_type="system_notification")))
            return
        if mailbox == "notifications":
            await notification_administration(
                api=api, container=table_container,
                relationship_select=relationship_select,
                bind_relationship=bind_remote_relationship_select,
                format_timestamp=format_timestamp,
                active=lambda: auth_state.get("principal") is principal
                and state.get("messaging_workspace_token") is token and state.get("resource") == key,
            )
            return
        state["messaging_workspace"] = await messaging_workspace(
            api=api, container=table_container, mailbox=mailbox,
            can_exchange="messaging.user_messages.exchange" in principal.get("global_privileges", []),
            relationship_select=relationship_select,
            bind_relationship=bind_remote_relationship_select,
            open_resource=open_message_resource, format_timestamp=format_timestamp,
            open_disposition_eligibility=lambda:guarded_page_navigation(lambda:select_disposition("disposition-eligibility")),
            open_disposition_job=lambda job_id:guarded_page_navigation(lambda:select_disposition("disposition-job",job_id)),
            open_disposition_task=lambda job_id,task_id:guarded_page_navigation(lambda:select_disposition("disposition-job",job_id,task_id=task_id)),
            inspect_resource=inspect_message_resource,
            on_read=refresh_message_unread,
            browse_recipients=show_organization_structure if "organization.browse" in principal.get("global_privileges", []) else None,
            capture_record=capture_message if "record.create" in principal.get("global_privileges",[]) else None,
            active=lambda: auth_state.get("principal") is principal
            and state.get("messaging_workspace_token") is token and state.get("resource") == key,
        )

    async def select_entity(key: str) -> None:
        entity_navigation_keys = {
            "aggregations": "navigation.item.aggregations",
            "records": "navigation.item.records",
            "org-units": "navigation.item.org_units",
            "roles": "navigation.item.roles",
            "users": "navigation.item.users",
            "text-indexers": "navigation.item.text_indexers",
            "audit-trail": "navigation.item.audit_trail",
            "login-sessions": "navigation.item.login_sessions",
            "security-operations": "navigation.item.security_operations",
            "security-levels": "navigation.item.security_levels",
            "profiles": "navigation.item.profiles",
            "governance-custody": "navigation.item.governance_custody",
            "holds": "navigation.item.holds",
        }
        entity_label = render_message(entity_navigation_keys.get(key, "navigation.item.dashboard"))
        register_navigation(key, entity_label)
        show_authenticated_view()
        state.update(resource=key, rows=[], searched=False, lifecycle_filter='all'); aggregation_state.update(aggregation_detail=None)
        spec = ENTITIES[key]
        title.text = entity_label
        subtitle.text = render_message("webui.select_entity.text.search_required_before_loading_results_88549c49") if spec.search_first else render_message("webui.select_entity.text.manage_current_system_entries_fcec8116")
        aggregation_mode_bar.set_visibility(key == "aggregations")
        search_bar.set_visibility(
            spec.search_first
            and not (key == "aggregations" and aggregation_state.get("aggregation_mode") == "browse")
        )
        guidance.text = render_message("webui.select_entity.text.large_collections_are_search_first_to_avoi_717a0f77") if spec.search_first else ""
        privileges = set(
            (auth_state.get("principal") or {}).get("global_privileges", [])
        )
        add_button.set_visibility(can_add_from_collection(key, privileges))
        add_button.text = render_message("webui.select_entity.text.add_6623ee14")
        add_button.update()
        add_record_button.set_visibility(False)
        search_input.value = ""
        try:
            if key in {"aggregations", "records"} and not (
                key == "aggregations" and aggregation_state.get("aggregation_mode") == "browse"
            ):
                personal.personal_sections_loading[key] = True
                render_table(spec)
                await load_rows()

                async def refresh_personal_sections(
                    resource_key: str = key, resource_spec: EntitySpec = spec,
                ) -> None:
                    try:
                        await asyncio.gather(reload_favourites(), load_recent(resource_spec))
                    except asyncio.CancelledError:
                        return
                    except ApiError as error:
                        if state.get("resource") == resource_key:
                            set_connection_status(error.status_code != 503)
                            ui.notify(error_message(error), color="negative", close_button=True)
                    finally:
                        personal.personal_sections_loading[resource_key] = False
                    if state.get("resource") == resource_key and not (
                        resource_key == "aggregations" and aggregation_state.get("aggregation_mode") == "browse"
                    ):
                        personal_host = personal.personal_section_hosts.get(resource_key)
                        if personal_host is not None and not getattr(personal_host, "_deleted", False):
                            render_resource_personal_sections(
                                resource_spec, container=personal_host,
                            )
                        else:
                            render_table(resource_spec)

                background_tasks.create(refresh_personal_sections())
                return
            startup_requests = []
            if key in {"aggregations", "records"}:
                startup_requests.append(reload_favourites())
            if spec.search_first:
                startup_requests.append(load_recent(spec))
            if startup_requests:
                await asyncio.gather(*startup_requests)
            if key == "aggregations" and aggregation_state.get("aggregation_mode") == "browse":
                await select_aggregation_browser()
                return
            render_table(spec)
            await load_rows()
        except ApiError as error:
            set_connection_status(error.status_code != 503)
            ui.notify(error_message(error), color="negative", close_button=True)

    async def select_classification_workspace(
        initial_scheme_id: int | None = None,
        initial_classification_id: int | None = None,
    ) -> None:
        await classification_controller.open(initial_scheme_id, initial_classification_id)

    def begin_classification_workspace() -> None:
        show_authenticated_view()
        state.update(resource='classification-workspace', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)

    def clear_classification_shell() -> None:
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        table_container.clear()

    def register_classification_page(page, label, item, subtitle_text) -> None:
        register_navigation(page, label, entity_id=item["id"] if item else None, dynamic_label=bool(item))
        state["resource"] = page
        title.text = label
        subtitle.text = subtitle_text

    hold_reason_dialog, open_hold_editor = build_hold_editor(
        api=api,
        bind_remote_people_select=bind_remote_people_select,
        select_hold_details=lambda *args, **kwargs: select_hold_details(*args, **kwargs),
        error_message=error_message,
    )


    add_resource_to_hold_dialog, show_effective_holds_dialog = build_hold_resources(
        api=api,
        select_hold_details=lambda *args, **kwargs: select_hold_details(*args, **kwargs),
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        hold_reason_dialog=hold_reason_dialog,
        error_message=error_message,
    )


    def enter_holds() -> None:
        state.update(resource="holds", rows=[], searched=True)

    select_holds = build_holds(
        api=api,
        principal=lambda: auth_state.get("principal"),
        register_navigation=register_navigation,
        show_authenticated_view=show_authenticated_view,
        enter_holds=enter_holds,
        search_bar=search_bar,
        aggregation_mode_bar=aggregation_mode_bar,
        add_button=add_button,
        add_record_button=add_record_button,
        title=title,
        subtitle=subtitle,
        guidance=guidance,
        table_container=table_container,
        select_hold_details=lambda *args, **kwargs: select_hold_details(*args, **kwargs),
        open_hold_editor=open_hold_editor,
        show_entity_history=lambda *args, **kwargs: show_entity_history(*args, **kwargs),
        error_message=error_message,
        format_timestamp=format_timestamp,
    )

    def enter_hold_details() -> None:
        state.update(resource="hold-details", rows=[], searched=True)

    select_hold_details = build_hold_details(
        api=api,
        register_navigation=register_navigation,
        show_authenticated_view=show_authenticated_view,
        enter_hold_details=enter_hold_details,
        search_bar=search_bar,
        aggregation_mode_bar=aggregation_mode_bar,
        add_button=add_button,
        add_record_button=add_record_button,
        title=title,
        subtitle=subtitle,
        guidance=guidance,
        table_container=table_container,
        bind_remote_people_select=bind_remote_people_select,
        select_holds=lambda *args, **kwargs: select_holds(*args, **kwargs),
        hold_reason_dialog=hold_reason_dialog,
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        select_user_details=lambda *args, **kwargs: select_user_details(*args, **kwargs),
        select_record_details=lambda *args, **kwargs: select_record_details(*args, **kwargs),
        open_hold_editor=open_hold_editor,
        show_entity_history=lambda *args, **kwargs: show_entity_history(*args, **kwargs),
        error_message=error_message,
        format_timestamp=format_timestamp,
    )

    def enter_translations() -> None:
        state.update(resource="translations", rows=[], searched=True)

    select_translation_administration = build_translation_administration(
        api=api,
        register_navigation=register_navigation,
        show_authenticated_view=show_authenticated_view,
        enter_translations=enter_translations,
        current_page=lambda: state.get("resource"),
        title=title,
        subtitle=subtitle,
        search_bar=search_bar,
        aggregation_mode_bar=aggregation_mode_bar,
        add_button=add_button,
        add_record_button=add_record_button,
        guidance=guidance,
        table_container=table_container,
        page_client=page_client,
        error_message=error_message,
        buffer_upload_batch=buffer_upload_batch,
    )

    guarded_page_navigation = navigation_controller.guarded_page_navigation

    def accept_collection_results(rows: list[dict[str, Any]], searched: bool) -> None:
        state["rows"] = rows
        state["searched"] = searched

    load_rows = build_collection_loader(
        api, get_resource=lambda: state["resource"], get_query=lambda: search_input.value,
        pages=state["collection_pages"], accept_results=accept_collection_results,
        clear_result_state=lambda resource: state.setdefault("entity_result_states", {}).pop(resource, None),
        decorate_for_spec=decorate_for_spec,
        decorate_record_search_components=decorate_record_search_components,
        page_client=page_client, set_connection_status=set_connection_status,
        render_table=render_table, error_message=error_message,
    )

    render_administration_cards = build_administration_cards(
        format_timestamp=format_timestamp,
        load_rows=lambda *args, **kwargs: load_rows(*args, **kwargs),
        localized_account_type=localized_account_type,
        localized_lifecycle_value=localized_lifecycle_value,
        open_editor=lambda *args, **kwargs: open_editor(*args, **kwargs),
        pages=state["collection_pages"],
        reset_lifecycle_filter=lambda: state.update(lifecycle_filter="all"),
        get_rows=lambda: state["rows"],
        select_organization_unit_details=lambda *args, **kwargs: select_organization_unit_details(*args, **kwargs),
        select_role_details=lambda *args, **kwargs: select_role_details(*args, **kwargs),
        select_user_details=lambda *args, **kwargs: select_user_details(*args, **kwargs),
        show_entity_history=lambda *args, **kwargs: show_entity_history(*args, **kwargs),
        show_memberships=lambda *args, **kwargs: show_memberships(*args, **kwargs),
        show_profile_privilege_editor=lambda *args, **kwargs: show_profile_privilege_editor(*args, **kwargs),
    )

    show_memberships = build_organization_memberships(
        add_timestamp_slots=add_timestamp_slots,
        api=api,
        bind_remote_relationship_select=lambda *args, **kwargs: bind_remote_relationship_select(*args, **kwargs),
        error_message=error_message,
        filter_membership_rows=filter_membership_rows,
        localized_lifecycle_value=localized_lifecycle_value,
        show_api_error=show_api_error,
        show_organization_structure=lambda *args, **kwargs: show_organization_structure(*args, **kwargs),
        user_avatar=user_avatar,
    )

    confirm_identity_deletion = build_organization_deletion(
        api=api,
        deletion_blocked_report=deletion_blocked_report,
        deletion_identity=deletion_identity,
        error_message=error_message,
        show_api_error=show_api_error,
    )

    select_organization_unit_details = build_organization_units(
        ADVANCED_SEARCH_CONTROLLED_VALUES=ADVANCED_SEARCH_CONTROLLED_VALUES,
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_mode_bar=aggregation_mode_bar,
        api=api,
        breadcrumb_back=breadcrumb_back,
        confirm_identity_deletion=lambda *args, **kwargs: confirm_identity_deletion(*args, **kwargs),
        direction=lambda: current_direction["value"],
        enter_organization_units=enter_organization_units,
        error_message=error_message,
        format_file_size=format_file_size,
        guidance=guidance,
        localized_lifecycle_value=localized_lifecycle_value,
        open_editor=open_editor,
        register_navigation=register_navigation,
        search_bar=search_bar,
        select_entity=select_entity,
        select_role_details=lambda *args, **kwargs: select_role_details(*args, **kwargs),
        show_api_error=show_api_error,
        show_authenticated_view=show_authenticated_view,
        show_entity_history=lambda *args, **kwargs: show_entity_history(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )

    select_role_details = build_organization_roles(
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_mode_bar=aggregation_mode_bar,
        api=api,
        breadcrumb_back=breadcrumb_back,
        confirm_identity_deletion=lambda *args, **kwargs: confirm_identity_deletion(*args, **kwargs),
        direction=lambda: current_direction["value"],
        enter_organization_roles=enter_organization_roles,
        error_message=error_message,
        get_principal=lambda: auth_state.get("principal"),
        guidance=guidance,
        localized_lifecycle_value=localized_lifecycle_value,
        open_editor=open_editor,
        register_navigation=register_navigation,
        search_bar=search_bar,
        select_entity=select_entity,
        select_organization_unit_details=lambda *args, **kwargs: select_organization_unit_details(*args, **kwargs),
        select_text_indexers=lambda: select_text_indexers(),
        show_api_error=show_api_error,
        show_authenticated_view=show_authenticated_view,
        show_entity_history=lambda *args, **kwargs: show_entity_history(*args, **kwargs),
        show_memberships=lambda *args, **kwargs: show_memberships(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )

    select_user_details = build_organization_users(
        accept_application_configuration=accept_application_configuration,
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_mode_bar=aggregation_mode_bar,
        api=api,
        breadcrumb_back=breadcrumb_back,
        confirm_identity_deletion=lambda *args, **kwargs: confirm_identity_deletion(*args, **kwargs),
        current_page=lambda: state.get("resource"),
        direction=lambda: current_direction["value"],
        enter_organization_users=enter_organization_users,
        error_message=error_message,
        format_timestamp=format_timestamp,
        get_principal=lambda: auth_state.get("principal"),
        guidance=guidance,
        localized_account_type=localized_account_type,
        localized_lifecycle_value=localized_lifecycle_value,
        open_editor=open_editor,
        register_navigation=register_navigation,
        render_user_avatar=render_user_avatar,
        search_bar=search_bar,
        select_entity=select_entity,
        select_role_details=lambda *args, **kwargs: select_role_details(*args, **kwargs),
        select_text_indexer_details=lambda identity: select_text_indexer_details(identity),
        show_api_error=show_api_error,
        show_authenticated_view=show_authenticated_view,
        show_entity_history=lambda *args, **kwargs: show_entity_history(*args, **kwargs),
        show_memberships=lambda *args, **kwargs: show_memberships(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )

    show_organization_structure = build_organization_browser(
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_mode_bar=aggregation_mode_bar,
        api=api,
        current_page=lambda: state.get("resource"),
        enter_organization_browser=enter_organization_browser,
        error_message=error_message,
        format_timestamp=format_timestamp,
        get_principal=lambda: auth_state.get("principal"),
        guidance=guidance,
        localized_account_type=localized_account_type,
        localized_lifecycle_value=localized_lifecycle_value,
        page_client=page_client,
        register_navigation=register_navigation,
        render_user_avatar=render_user_avatar,
        search_bar=search_bar,
        select_organization_unit_details=lambda *args, **kwargs: select_organization_unit_details(*args, **kwargs),
        select_role_details=lambda *args, **kwargs: select_role_details(*args, **kwargs),
        select_user_details=lambda *args, **kwargs: select_user_details(*args, **kwargs),
        show_authenticated_view=show_authenticated_view,
        subtitle=subtitle,
        table_container=table_container,
        title=title,
        tree_expander_icon=tree_expander_icon,
    )

    select_login_sessions = build_login_sessions(
        api, table_container=table_container, enter=enter_login_sessions,
        principal=lambda: auth_state["principal"], current_session_revoked=current_session_revoked,
        render_user_avatar=render_user_avatar, format_timestamp=format_timestamp,
        localized_lifecycle_value=localized_lifecycle_value, error_message=error_message,
    )

    def enter_text_indexers() -> None:
        state.update(resource='text-indexers', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)

    def enter_text_indexer_details() -> None:
        state.update(resource='text-indexer-details', rows=[], searched=True); aggregation_state.update(aggregation_detail=None)

    select_text_indexers = build_text_indexers(
        register_navigation=register_navigation,
        show_authenticated_view=show_authenticated_view,
        search_bar=search_bar,
        aggregation_mode_bar=aggregation_mode_bar,
        add_button=add_button,
        add_record_button=add_record_button,
        guidance=guidance,
        title=title,
        subtitle=subtitle,
        table_container=table_container,
        api=api,
        error_message=error_message,
        show_api_error=show_api_error,
        format_timestamp=format_timestamp,
        localized_lifecycle_value=localized_lifecycle_value,
        enter=enter_text_indexers,
        direction=lambda: current_direction["value"],
        select_text_indexer_details=lambda *args, **kwargs: select_text_indexer_details(*args, **kwargs),
        select_record_details=lambda *args, **kwargs: select_record_details(*args, **kwargs),
        show_components=lambda *args, **kwargs: show_components(*args, **kwargs),
    )

    select_text_indexer_details = build_text_indexer_details(
        register_navigation=register_navigation,
        show_authenticated_view=show_authenticated_view,
        search_bar=search_bar,
        aggregation_mode_bar=aggregation_mode_bar,
        add_button=add_button,
        add_record_button=add_record_button,
        guidance=guidance,
        title=title,
        subtitle=subtitle,
        table_container=table_container,
        api=api,
        error_message=error_message,
        show_api_error=show_api_error,
        format_timestamp=format_timestamp,
        localized_lifecycle_value=localized_lifecycle_value,
        enter=enter_text_indexer_details,
        direction=lambda: current_direction["value"],
        select_text_indexers=lambda *args, **kwargs: select_text_indexers(*args, **kwargs),
        breadcrumb_back=lambda *args, **kwargs: breadcrumb_back(*args, **kwargs),
    )

    apply_document_direction, load_localization_context = build_account_localization(
        api=api, initial_language=initial_language, initial_direction=initial_direction,
        set_direction=lambda value: current_direction.__setitem__("value", value),
        drawer_toggle_button=drawer_toggle_button,
        get_localization=lambda: state.get("localization"),
        set_localization=lambda value: state.__setitem__("localization", value),
        set_configuration=lambda value: state.__setitem__("application_configuration", value),
    )
    populate_user_menu, refresh_user_profile = build_account_profile(
        api=api, get_principal=lambda: auth_state.get("principal"),
        set_principal=lambda principal: auth_state.__setitem__("principal", principal),
        drawer=drawer, mobile_navigation=mobile_navigation, header_network=header_network,
        holds_navigation=holds_navigation, refresh_drawer_visibility=refresh_drawer_visibility,
        synchronize_translation_inspector=synchronize_translation_inspector,
        current_user_name=current_user_name, current_user_email=current_user_email,
        current_user_avatar_initials=current_user_avatar_initials, current_user_avatar=current_user_avatar,
        current_user_last_login=current_user_last_login, current_user_roles=current_user_roles,
        format_timestamp=format_timestamp,
    )
    show_change_password = build_account_password(
        api=api, get_principal=lambda: auth_state.get("principal"),
        prepare_authenticated_workspace=lambda principal: prepare_authenticated_workspace(principal),
        select_dashboard=lambda: select_dashboard(), sign_out=sign_out, error_message=error_message,
    )
    show_preferences = build_account_preferences(
        api=api, get_localization=lambda: state.get("localization"),
        error_message=error_message, show_api_error=show_api_error,
    )

    bind_remote_relationship_select = build_relationship_selector(api, error_message=error_message)
    bind_resource_security_select = build_security_selector(api, error_message=error_message)
    show_security_level_change = build_security_level_change(
        api, bind_remote_relationship_select=bind_remote_relationship_select,
        error_message=error_message,
    )
    access_control_dialogs = build_access_control_dialogs(
        api, principal=lambda: auth_state.get("principal"), direction=lambda: current_direction["value"],
        open_aggregation=open_aggregation, show_organization_structure=show_organization_structure,
        bind_remote_relationship_select=bind_remote_relationship_select, error_message=error_message,
    )
    show_acl_editor = access_control_dialogs.show_acl_editor
    show_access_explanation = build_access_explanation(
        api, principal=lambda: auth_state.get("principal"), open_aggregation=open_aggregation,
        localized_editor_entity=localized_editor_entity, error_message=error_message,
    )
    show_profile_privilege_editor = build_profile_privilege_editor(
        api, select_entity=select_entity, error_message=error_message, show_api_error=show_api_error,
    )
    row_hydrators = build_row_hydrators(api)
    number_controls = build_number_controls(api, show_api_error=show_api_error)
    add_number_suggestion = number_controls.add_number_suggestion
    show_number_conflict = number_controls.show_number_conflict
    personal_resources = build_personal_resources(
        api, personal, get_principal=lambda: auth_state.get("principal"),
        get_resource=lambda: state.get("resource"),
        accept_application_configuration=accept_application_configuration,
        decorate_for_spec=decorate_for_spec, error_message=error_message,
    )
    reload_favourites = personal_resources.reload_favourites
    favourite_state = personal_resources.favourite_state
    toggle_favourite = personal_resources.toggle_favourite
    favourite_button = personal_resources.favourite_button
    load_recent = personal_resources.load_recent
    personal_views = build_personal_resource_views(
        api, personal, get_configuration=lambda: state["application_configuration"],
        render_table=render_table, open_aggregation=open_aggregation,
        show_record_details=show_record_details, load_recent=load_recent,
        toggle_favourite=toggle_favourite, error_message=error_message,
        format_timestamp=format_timestamp, personal_dialog_list_height=personal_dialog_list_height,
    )
    render_recent_section = personal_views.render_recent_section
    render_entity_favourites_section = personal_views.render_entity_favourites_section
    render_resource_personal_sections = personal_views.render_resource_personal_sections
    render_compact_resource_result = build_compact_resource_view(
        tree_expander_icon=tree_expander_icon, favourite_button=favourite_button,
        render_safe_snippet=render_safe_snippet, preview_record_components=preview_record_components,
        format_date=format_date, medium_label=medium_label, component_is_previewable=component_is_previewable,
    )

    browse_classification_tree, browse_advanced_classification = build_classification_pickers(
        api, direction=lambda: current_direction["value"],
        tree_expander_icon=tree_expander_icon, error_message=error_message,
    )
    relationship_types_controller = RelationshipTypesController(
        api=api, container=table_container,
        principal=lambda: auth_state.get("principal"),
        selected=lambda: state.get("resource") == "relationship-types",
        enter=enter_relationship_types,
        supported_languages=lambda: (state.get("localization") or {}).get("supported_languages", []),
        on_error=error_message,
    )
    select_relationship_types = relationship_types_controller.open

    application_settings_controller = ApplicationSettingsController(
        api=api, container=table_container,
        principal=lambda: auth_state.get("principal"),
        selected=lambda: state.get("resource") == "application-settings",
        enter=enter_application_settings,
        persist_category=persist_application_settings_category,
        guard=guarded_page_navigation, bind_relationship=bind_remote_relationship_select,
        direction=lambda: current_direction["value"], on_error=error_message,
    )

    audit_workspace = build_audit_workspace(
        api=api, table_container=table_container,
        principal=lambda: auth_state.get("principal"),
        selected=lambda: state.get("resource") == "audit-trail",
        enter=enter_audit_trail, error_message=error_message,
        format_timestamp=format_timestamp, set_connection_status=set_connection_status,
        can_open_settings=application_settings_controller.can_open,
        open_settings=application_settings_controller.open_from_event,
        open_destination=open_audit_entity,
    )
    select_audit_trail = audit_workspace.select_audit_trail
    show_entity_history = audit_workspace.show_entity_history

    classification_controller = ClassificationController(
        api=api, container=table_container, principal=lambda: auth_state.get("principal"),
        selected=lambda: state.get("resource") in {
            "classification-workspace", "classification-scheme-details", "classification-details",
        },
        begin=begin_classification_workspace, clear=clear_classification_shell,
        register=register_classification_page, open_editor=open_editor,
        show_entity_history=show_entity_history, format_timestamp=format_timestamp,
        display_value=display_value, error_message=error_message,
        entity_metadata_label=entity_metadata_label,
        localized_disposition_value=localized_disposition_value,
        direction=lambda: current_direction["value"],
    )


    inspector_bridge.on("click", open_inspected_translation)

    for key, button in navigation.items():
        if key.startswith("messages-"):
            button.on("click", lambda _, mailbox=key.removeprefix("messages-"): guarded_page_navigation(lambda: select_messages(mailbox)))
        elif key == "classification-schemes":
            button.on("click", lambda: guarded_page_navigation(select_classification_workspace))
        elif key == "advanced-search":
            button.on("click", lambda: guarded_page_navigation(select_advanced_search))
        elif key in ("disposition-tasks", "disposition-eligibility", "disposition-jobs", "disposition-templates"):
            button.on("click", lambda _, page=key: guarded_page_navigation(lambda: select_disposition(page)))
        elif key == "relationship-types":
            button.on("click", lambda: guarded_page_navigation(select_relationship_types))
        elif key == "translations":
            button.on("click", lambda: guarded_page_navigation(select_translation_administration))
        else:
            button.on("click", lambda _, entity_key=key: guarded_page_navigation(lambda: select_entity(entity_key)))
    aggregation_search_mode.on("click", lambda: guarded_page_navigation(select_aggregation_search))
    aggregation_browse_mode.on("click", lambda: guarded_page_navigation(select_aggregation_browser))
    dashboard_navigation.on("click", lambda: guarded_page_navigation(select_dashboard))
    organization_browser_navigation.on("click", lambda: guarded_page_navigation(show_organization_structure))
    audit_navigation.on("click", lambda: guarded_page_navigation(select_audit_trail))
    sessions_navigation.on("click", lambda: guarded_page_navigation(select_login_sessions))
    security_operations_navigation.on("click", lambda: guarded_page_navigation(select_security_operations))
    saved_search_administration_navigation.on(
        "click", lambda: guarded_page_navigation(select_saved_search_administration)
    )
    text_indexers_navigation.on("click", lambda: guarded_page_navigation(select_text_indexers))
    application_settings_navigation.on("click", application_settings_controller.open_from_drawer)
    custody_navigation.on("click", lambda: guarded_page_navigation(select_governance_custody))
    holds_navigation.on("click", lambda: guarded_page_navigation(select_holds))
    change_password_menu.on("click", show_change_password)
    preferences_menu.on("click", show_preferences)
    sign_out_menu.on("click", sign_out)


    user_menu.on("show", refresh_user_profile)
    add_for_current_context, add_record_for_current_aggregation = build_aggregation_toolbar(
        aggregation_state=aggregation_state,
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        open_editor=lambda *args, **kwargs: open_editor(*args, **kwargs),
        open_record_draft_editor=lambda *args, **kwargs: open_record_draft_editor(*args, **kwargs),
    )


    add_button.on("click", add_for_current_context)
    add_record_button.on("click", add_record_for_current_aggregation)
    search_button.on("click", lambda: load_rows())
    search_input.on("keydown.enter", lambda: load_rows())
    async def clear_collection_search() -> None:
        if state.get("resource") not in {"aggregations", "records"}:
            return
        search_input.value = ""
        await load_rows()
        search_input.run_method("focus")

    search_input.on("clear", clear_collection_search)
    global_search_submit.on("click", lambda: run_global_search(global_search_input.value or ""))
    global_search_input.on("keydown.enter", lambda: run_global_search(global_search_input.value or ""))
    login_dialog = build_sign_in(
        session=session, initial_direction=initial_direction, initial_language=initial_language,
        set_principal=lambda principal: auth_state.__setitem__("principal", principal),
        drawer=drawer, table_container=table_container,
        show_change_password=lambda: show_change_password(),
        prepare_authenticated_workspace=lambda principal: prepare_authenticated_workspace(principal),
        select_dashboard=lambda: select_dashboard(), login_error_message=login_error_message,
    )

    async def reset_private_views() -> None:
        clear_global_search_session()
        clear_dashboard_session()
        await clear_translation_inspector_session()

    handle_unauthorized = session.handle_unauthorized

    api.set_unauthorized_handler(handle_unauthorized)

    async def load_authenticated_client_assets() -> None:
        """Load non-critical tools without delaying the authenticated workspace."""
        try:
            await ui.run_javascript(
                "import('/static/pdfjs/erms-viewer.mjs').then(() => true)", timeout=15,
            )
        except Exception:
            # The PDF viewer reports its own load failure when invoked.
            pass

    async def open_live_delivery(event):
        if auth_state.get("principal") is None:
            return
        identity = event.args
        if identity is not None:
            try:
                from uuid import UUID
                identity = str(UUID(identity))
            except (ValueError, TypeError):
                return
        await select_messages("inbox")
        workspace = state.get("messaging_workspace")
        if identity and workspace:
            await workspace["open"](identity)

    ui.on("messaging_open", open_live_delivery)

    def show_message_notification(label, identity):
        # ui.notify's raw transport cannot serialize Python action callbacks.
        # The standard notification element supports dynamic Quasar actions;
        # ui.on / emitEvent is NiceGUI's supported browser-event bridge.
        notification = ui.notification(label, actions=[{
            "label": render_message("messaging.action.open"),
            ":handler": "() => emitEvent('messaging_open', " + json.dumps(identity) + ")",
        }], timeout=8, close_button=render_message("messaging.live.close"), html=False)
        notifications = message_live["notifications"]
        notifications[:] = [item for item in notifications if not item._deleted]
        notifications.append(notification)
        if len(notifications) > 32:
            notifications.pop(0).dismiss()

    def stop_message_stream() -> None:
        if message_live["adapter"]:
            message_live["adapter"].stop()
        if message_live["api"]:
            message_live["api"].cancel_pending_reads()
            background_tasks.create(message_live["api"].close())
        message_live.update(adapter=None, api=None, token=None)
        for notification in message_live["notifications"]:
            if not notification._deleted:
                notification.dismiss()
        message_live["notifications"].clear()

    async def refresh_message_unread() -> None:
        principal = auth_state.get("principal")
        if principal is None:
            return
        result = await api.request("GET", "/api/v1/messages/unread-count")
        if auth_state.get("principal") is principal:
            message_unread_button.text = render_message("messaging.live.unread", count=result["unread_count"])
            message_unread_button.set_visibility(True)

    async def start_message_stream() -> None:
        principal = auth_state.get("principal")
        token = app.storage.user.get("session_token")
        if not principal or not token or principal.get("must_change_password"):
            return
        stop_message_stream()
        import hashlib
        cursor_key = mailbox_cursor_key(api_url(), principal["user"]["id"])
        legacy_cursor_key = "wathiq-message-cursor:" + str(principal["user"]["id"]) + ":" + hashlib.sha256(token.encode()).hexdigest()[:24]
        message_live["token"] = token
        is_active = lambda: auth_state.get("principal") is principal and message_live["token"] == token and page_client.has_socket_connection

        async def load_cursor():
            return await page_client.run_javascript("localStorage.getItem(" + json.dumps(cursor_key) + ") ?? sessionStorage.getItem(" + json.dumps(legacy_cursor_key) + ")", timeout=5)

        async def save_cursor(value):
            if is_active():
                # Browser execution is synchronous: another tab cannot regress
                # this account's persisted checkpoint with an older page.
                script = "(() => { const key = " + json.dumps(cursor_key) + "; const incoming = BigInt(" + json.dumps(str(value)) + "); const stored = localStorage.getItem(key); const previous = stored && /^[0-9]+$/.test(stored) ? BigInt(stored) : 0n; localStorage.setItem(key, String(incoming > previous ? incoming : previous)); return true; })()"
                await page_client.run_javascript(script, timeout=5)

        async def present_message(kind, value):
            if not is_active():
                return
            with page_client:
                if kind == "unread":
                    message_unread_button.text = render_message("messaging.live.unread", count=value)
                    message_unread_button.set_visibility(True)
                elif kind == "summary":
                    label = render_message("messaging.live.test_summary", **value) if isinstance(value, dict) else (render_message("messaging.live.summary_one") if value == 1 else render_message("messaging.live.summary", count=value))
                    show_message_notification(label, None)
                elif kind == "message":
                    # Content was freshly authorized by catch-up. Restricted
                    # deliveries receive only a generic non-disclosing toast.
                    label = render_message("messaging.live.new_message")
                    if value.get("is_test"):
                        label = render_message("messaging.test.label") + " · " + label
                    if value.get("availability") == "available":
                        label += ": " + value.get("toast_subject", value["subject"])
                    show_message_notification(label, value["id"])
                elif kind == "refresh" and state.get("resource") == "messages-inbox":
                    workspace = state.get("messaging_workspace")
                    if workspace:
                        await workspace["refresh"]()

        # Navigation cancels ordinary page reads; the stream owns a separate
        # identity-scoped client so those cancellations cannot kill reconciliation.
        live_api = ErmsApiClient(api_url())
        live_api.set_session_token(token)
        live_api.set_unauthorized_handler(handle_unauthorized)
        message_live["api"] = live_api
        adapter = LiveMailbox(api=live_api, events=lambda transport: stream_events(api_url(), token, transport), load_cursor=load_cursor, save_cursor=save_cursor, present=present_message, active=is_active)
        message_live["adapter"] = adapter
        adapter.start()

    page_client.on_disconnect(stop_message_stream)
    page_client.on_connect(start_message_stream)




    prepare_authenticated_workspace, initialize_authenticated_ui = build_account_bootstrap(
        api=api, page_client=page_client, initial_language=initial_language,
        initial_direction=initial_direction, apply_document_direction=apply_document_direction,
        load_localization_context=load_localization_context,
        accept_application_configuration=accept_application_configuration,
        get_configuration=lambda: state["application_configuration"],
        populate_user_menu=lambda principal: populate_user_menu(principal),
        load_authenticated_client_assets=load_authenticated_client_assets,
        start_message_stream=start_message_stream, refresh_hold_navigation=refresh_hold_navigation,
        set_principal=lambda principal: auth_state.__setitem__("principal", principal),
        drawer=drawer, table_container=table_container, show_change_password=show_change_password,
        q=q, navigation_controller=navigation_controller, run_global_search=run_global_search,
        restore_navigation_entry=restore_navigation_entry,
        render_navigation_breadcrumbs=render_navigation_breadcrumbs, select_dashboard=select_dashboard,
        clear_signed_in_identity=clear_signed_in_identity, set_connection_status=set_connection_status,
        login_dialog=login_dialog,
    )

    ui.timer(0.05, initialize_authenticated_ui, once=True)


def run() -> None:
    ui.run(
        title="wathiq",
        host=host(),
        port=port(),
        reload=reload_enabled(),
        storage_secret=storage_secret(),
        favicon=Path(__file__).with_name("static") / "brand" / "wathiq-mark.svg",
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
