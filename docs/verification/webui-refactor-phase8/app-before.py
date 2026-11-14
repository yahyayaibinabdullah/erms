from __future__ import annotations
from .message_live_state import new_message_live_state
from .messaging_controller import build_messaging_controller
from .message_stream import build_message_stream
from .messaging_state import new_messaging_state
from .disposition.controller import build_disposition_controller
from .disposition_state import new_disposition_state
from .dashboard import build_dashboard
from .dashboard_state import new_dashboard_state
from .saved_search_audiences import build_saved_search_audiences
from .saved_search_administration import build_saved_search_administration
from .advanced_search import build_advanced_search
from .advanced_search_state import new_advanced_search_state
from .advanced_search_model import (
    ADVANCED_SEARCH_FIELDS,
    ADVANCED_SEARCH_COMPONENT_FIELDS,
    ADVANCED_SEARCH_RETENTION_FIELDS,
    ADVANCED_SEARCH_RELATIONSHIP_FIELDS,
    ADVANCED_SEARCH_CONTROLLED_VALUES,
    advanced_search_field_options,
    advanced_search_empty_value,
    advanced_search_operators,
    advanced_search_leaf_count,
    advanced_search_depth,
    advanced_search_has_positive_full_text,
    advanced_search_has_component_field,
    compile_advanced_search_node,
    advanced_search_node_from_expression,
)
from .global_search import build_global_search
from .global_search_state import new_global_search_state
from .governance_custody import build_governance_custody
from .security_operations import build_security_operations
from .record_details import build_record_details
from .record_capture import build_record_capture
from .entity_editor import build_entity_editor
from .resource_row_hydration import build_resource_row_hydration
from .resource_collection_results import build_resource_collection_results
from .collection_table import build_collection_table
from .collection_navigation import build_collection_navigation
from .resource_row_presentation import relationship_cell, decorate_relationship_rows
from .record_presentation import RECORD_DETAIL_HEADER_CLASSES, RECORD_DETAIL_TITLE_CLASSES, RECORD_UPLOAD_WAIT_MESSAGE
from .record_editor import record_draft_component_context
from .record_editor import configure_record_medium
from .collection_state import new_collection_state
from .record_state import new_record_state
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
RELATIONSHIP_DISPLAY_FIELDS = frozenset({
    "aggregation_display",
    "org_unit_display",
    "parent_org_unit_display",
    "profile_display",
    "scheme_display",
})
STOP_PROPAGATION_CLICK_HANDLER = "(event) => { event.stopPropagation(); emit(); }"



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
    message_live = new_message_live_state()
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
    record_state = new_record_state()
    collection_state = new_collection_state()
    global_search_state = new_global_search_state(q)
    advanced_search_state = new_advanced_search_state()
    dashboard_state = new_dashboard_state()
    disposition_state = new_disposition_state()
    messaging_state = new_messaging_state()
    state: dict[str, Any] = {'resource': 'dashboard'}
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



    bind_remote_saved_audience_select = build_saved_search_audiences(
        api=api,
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
    )

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
        entity_result_state = collection_state.get("entity_result_states", {}).get(state.get("resource"), {})
        return {
            "searched": bool(collection_state.get("searched")),
            "search_text": str(search_input.value or ""),
            "lifecycle_filter": collection_state.get("lifecycle_filter", "all"),
            "aggregation_mode": aggregation_state.get("aggregation_mode", "search"),
            "settings_category": application_settings_controller.category,
            "disposition_view": dict(disposition_state.get("disposition_view") or {}),
            "global_search_query": global_search_state.get("global_search_query", ""),
            "global_search_page": global_search_state.get("global_search_page", 1),
            "global_search_filter": global_search_state.get("global_search_filter", "all"),
            "global_search_return_anchor": global_search_state.get("global_search_return_anchor"),
            "global_search_expanded_results": sorted(global_search_state.get("global_search_expanded_results", set())),
            "entity_result_state": {
                **entity_result_state,
                "expanded_results": sorted(entity_result_state.get("expanded_results", set())),
            } if entity_result_state else {},
        }

    global_search_payload, render_safe_snippet, copy_diagnostic_json, render_search_diagnostics, render_global_search_results, change_global_search_page, remember_global_result, set_global_result_expansion, open_global_record_from_result, open_global_aggregation_from_result, open_global_record, open_global_aggregation, run_global_search, clear_global_search_session = build_global_search(
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_mode_bar=aggregation_mode_bar,
        api=api,
        clear_advanced_workspace=lambda: advanced_search_state.pop("advanced_search_workspace", None),
        clear_collection_results=lambda: collection_state.update(entity_result_states={}),
        discard_navigation_guard=lambda: state.pop("discard_navigation_guard", None),
        enter_global_search=lambda: state.update(resource="full-text-search"),
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        get_principal=lambda: auth_state.get("principal"),
        get_resource=lambda: state["resource"],
        global_search_input=global_search_input,
        global_search_state=global_search_state,
        invalidate_advanced_session=lambda: advanced_search_state.__setitem__("advanced_search_session_revision", advanced_search_state.get("advanced_search_session_revision", 0) + 1),
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        register_navigation=lambda *args, **kwargs: register_navigation(*args, **kwargs),
        render_compact_resource_result=lambda *args, **kwargs: render_compact_resource_result(*args, **kwargs),
        restore_compact_result_anchor=lambda *args, **kwargs: restore_compact_result_anchor(*args, **kwargs),
        search_bar=search_bar,
        select_record_details=lambda *args, **kwargs: select_record_details(*args, **kwargs),
        show_authenticated_view=lambda *args, **kwargs: show_authenticated_view(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )













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
            global_search_state["search_diagnostics_sent"] = None
            global_search_state["search_diagnostics_accepted"] = None
            global_search_state["search_diagnostics_error"] = None
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
            query = str(saved.get("global_search_query") or global_search_state.get("global_search_query") or "")
            if query:
                if global_search_state.get("global_search_items") and global_search_state.get("global_search_query") == query:
                    global_search_state["global_search_page"] = int(saved.get("global_search_page") or 1)
                    global_search_state["global_search_filter"] = saved.get("global_search_filter") or "all"
                    global_search_state["global_search_return_anchor"] = saved.get("global_search_return_anchor")
                    global_search_state["global_search_expanded_results"] = set(
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
                collection_state.setdefault("entity_result_states", {})[page] = restored_result_state
            if page == "aggregations":
                aggregation_state["aggregation_mode"] = saved.get("aggregation_mode", "search")
            await select_entity(page)
            # Browse restores its own expanded branches, selection and scroll.
            # A search made before switching modes must not replace that tree.
            if page == "aggregations" and aggregation_state.get("aggregation_mode") == "browse":
                return
            search_input.value = saved.get("search_text", "")
            collection_state["lifecycle_filter"] = saved.get("lifecycle_filter", "all")
            if saved.get("searched") and search_input.value and ENTITIES[page].search_first:
                await load_rows()
            elif collection_state["lifecycle_filter"] != "all" and page in {"org-units", "roles", "users"}:
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
        state.update(resource='dashboard'); collection_state.update(rows=[], searched=False); aggregation_state.update(aggregation_detail=None)
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



    dashboard_session_key, clear_dashboard_session, select_dashboard = build_dashboard(
        STOP_PROPAGATION_CLICK_HANDLER=STOP_PROPAGATION_CLICK_HANDLER,
        accept_application_configuration=lambda *args, **kwargs: accept_application_configuration(*args, **kwargs),
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_mode_bar=aggregation_mode_bar,
        aggregation_state=aggregation_state,
        api=api,
        collection_state=collection_state,
        dashboard_state=dashboard_state,
        decorate_for_spec=lambda *args, **kwargs: decorate_for_spec(*args, **kwargs),
        enter_dashboard=lambda: state.update(resource="dashboard"),
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        format_file_size=lambda *args, **kwargs: format_file_size(*args, **kwargs),
        format_timestamp=lambda *args, **kwargs: format_timestamp(*args, **kwargs),
        get_configuration=lambda: state["application_configuration"],
        get_localization=lambda: state.get("localization"),
        get_principal=lambda: auth_state.get("principal"),
        get_resource=lambda: state.get("resource"),
        guidance=guidance,
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        page_client=page_client,
        personal=personal,
        personal_dialog_list_height=lambda *args, **kwargs: personal_dialog_list_height(*args, **kwargs),
        register_navigation=lambda *args, **kwargs: register_navigation(*args, **kwargs),
        render_table=lambda *args, **kwargs: render_table(*args, **kwargs),
        require_principal=lambda: auth_state["principal"],
        review_display=lambda *args, **kwargs: review_display(*args, **kwargs),
        search_bar=search_bar,
        select_classification_workspace=lambda *args, **kwargs: select_classification_workspace(*args, **kwargs),
        select_entity=lambda *args, **kwargs: select_entity(*args, **kwargs),
        select_holds=lambda *args, **kwargs: select_holds(*args, **kwargs),
        select_organization_unit_details=lambda *args, **kwargs: select_organization_unit_details(*args, **kwargs),
        set_connection_status=lambda *args, **kwargs: set_connection_status(*args, **kwargs),
        show_authenticated_view=lambda *args, **kwargs: show_authenticated_view(*args, **kwargs),
        show_record_details=lambda *args, **kwargs: show_record_details(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )


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




    show_record_details, select_record_details = build_record_details(
        add_button=add_button,
        add_record_button=add_record_button,
        add_resource_to_hold_dialog=lambda *args, **kwargs: add_resource_to_hold_dialog(*args, **kwargs),
        aggregation_mode_bar=aggregation_mode_bar,
        api=api,
        bind_remote_relationship_select=lambda *args, **kwargs: bind_remote_relationship_select(*args, **kwargs),
        breadcrumb_back=lambda *args, **kwargs: breadcrumb_back(*args, **kwargs),
        browse_advanced_aggregation=lambda *args, **kwargs: browse_advanced_aggregation(*args, **kwargs),
        clear_collection=lambda: collection_state.update(rows=[], searched=True),
        current_direction=current_direction,
        decorate_for_spec=lambda *args, **kwargs: decorate_for_spec(*args, **kwargs),
        enter_record_details=lambda: state.update(resource="record-details"),
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        favourite_button=lambda *args, **kwargs: favourite_button(*args, **kwargs),
        format_timestamp=lambda *args, **kwargs: format_timestamp(*args, **kwargs),
        get_aggregation_detail=lambda: aggregation_state.get("aggregation_detail"),
        get_relationship_page_token=lambda: state.get("relationship_page_token"),
        get_resource=lambda: state.get("resource"),
        guidance=guidance,
        hold_reason_dialog=lambda *args, **kwargs: hold_reason_dialog(*args, **kwargs),
        load_recent=lambda *args, **kwargs: load_recent(*args, **kwargs),
        medium_label=lambda *args, **kwargs: medium_label(*args, **kwargs),
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        open_editor=lambda *args, **kwargs: open_editor(*args, **kwargs),
        open_related_resource=lambda *args, **kwargs: open_related_resource(*args, **kwargs),
        preview_record_components=lambda *args, **kwargs: preview_record_components(*args, **kwargs),
        principal=lambda: auth_state.get("principal"),
        record_state=record_state,
        register_navigation=lambda *args, **kwargs: register_navigation(*args, **kwargs),
        review_datetime_input_minimum=lambda *args, **kwargs: review_datetime_input_minimum(*args, **kwargs),
        review_datetime_input_value=lambda *args, **kwargs: review_datetime_input_value(*args, **kwargs),
        review_datetime_payload=lambda *args, **kwargs: review_datetime_payload(*args, **kwargs),
        review_display=lambda *args, **kwargs: review_display(*args, **kwargs),
        search_bar=search_bar,
        select_entity=lambda *args, **kwargs: select_entity(*args, **kwargs),
        set_relationship_page_token=lambda token: state.__setitem__("relationship_page_token", token),
        show_access_explanation=lambda *args, **kwargs: show_access_explanation(*args, **kwargs),
        show_acl_editor=lambda *args, **kwargs: show_acl_editor(*args, **kwargs),
        show_authenticated_view=lambda *args, **kwargs: show_authenticated_view(*args, **kwargs),
        show_components=lambda *args, **kwargs: show_components(*args, **kwargs),
        show_effective_holds_dialog=lambda *args, **kwargs: show_effective_holds_dialog(*args, **kwargs),
        show_entity_history=lambda *args, **kwargs: show_entity_history(*args, **kwargs),
        show_governed_move=lambda *args, **kwargs: show_governed_move(*args, **kwargs),
        show_security_level_change=lambda *args, **kwargs: show_security_level_change(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )


    decorate_for_spec, decorate_record_search_components = build_resource_row_hydration(
        api=api,
        get_row_hydrators=lambda: row_hydrators,
        medium_label=lambda *args, **kwargs: medium_label(*args, **kwargs),
        review_display=lambda *args, **kwargs: review_display(*args, **kwargs),
    )


    browse_advanced_aggregation = build_aggregation_selector(
        api=api,
        bind_remote_scheme_select=lambda *args, **kwargs: bind_remote_scheme_select(*args, **kwargs),
        error_message=error_message,
        tree_expander_icon=lambda *args, **kwargs: tree_expander_icon(*args, **kwargs),
    )

    open_record_draft_editor = build_record_capture(
        add_number_suggestion=lambda *args, **kwargs: add_number_suggestion(*args, **kwargs),
        api=api,
        bind_remote_relationship_select=lambda *args, **kwargs: bind_remote_relationship_select(*args, **kwargs),
        bind_resource_security_select=lambda *args, **kwargs: bind_resource_security_select(*args, **kwargs),
        browse_advanced_aggregation=lambda *args, **kwargs: browse_advanced_aggregation(*args, **kwargs),
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        load_recent=lambda *args, **kwargs: load_recent(*args, **kwargs),
        preview_record_components=lambda *args, **kwargs: preview_record_components(*args, **kwargs),
        render_component_cards=render_component_cards,
        render_table=lambda *args, **kwargs: render_table(*args, **kwargs),
        set_searched=lambda value: collection_state.__setitem__("searched", value),
        show_number_conflict=lambda *args, **kwargs: show_number_conflict(*args, **kwargs),
        validation_error_message=lambda *args, **kwargs: validation_error_message(*args, **kwargs),
    )

    open_editor = build_entity_editor(
        CLASSIFICATION_SELECTOR_SEARCH_FIELDS=CLASSIFICATION_SELECTOR_SEARCH_FIELDS,
        accept_application_configuration=lambda *args, **kwargs: accept_application_configuration(*args, **kwargs),
        add_number_suggestion=lambda *args, **kwargs: add_number_suggestion(*args, **kwargs),
        api=api,
        bind_remote_relationship_select=lambda *args, **kwargs: bind_remote_relationship_select(*args, **kwargs),
        bind_resource_security_select=lambda *args, **kwargs: bind_resource_security_select(*args, **kwargs),
        browse_classification_tree=lambda *args, **kwargs: browse_classification_tree(*args, **kwargs),
        clear_medium_error=lambda *args, **kwargs: clear_medium_error(*args, **kwargs),
        current_resource=lambda: state["resource"],
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        highlight_medium_error=lambda *args, **kwargs: highlight_medium_error(*args, **kwargs),
        load_recent=lambda *args, **kwargs: load_recent(*args, **kwargs),
        load_rows=lambda *args, **kwargs: load_rows(*args, **kwargs),
        localization=lambda: state.get("localization"),
        localized_editor_entity=lambda *args, **kwargs: localized_editor_entity(*args, **kwargs),
        open_record_draft_editor=lambda *args, **kwargs: open_record_draft_editor(*args, **kwargs),
        principal=lambda: auth_state.get("principal"),
        render_table=lambda *args, **kwargs: render_table(*args, **kwargs),
        search_input=search_input,
        set_searched=lambda value: collection_state.__setitem__("searched", value),
        show_api_error=lambda *args, **kwargs: show_api_error(*args, **kwargs),
        show_number_conflict=lambda *args, **kwargs: show_number_conflict(*args, **kwargs),
        show_organization_structure=lambda *args, **kwargs: show_organization_structure(*args, **kwargs),
        validation_error_message=lambda *args, **kwargs: validation_error_message(*args, **kwargs),
    )



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
        get_record_detail_id=lambda: record_state.get("record_detail_id"),
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






    render_entity_compact_results = build_resource_collection_results(
        collection_state=collection_state,
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        render_compact_resource_result=lambda *args, **kwargs: render_compact_resource_result(*args, **kwargs),
        restore_compact_result_anchor=lambda *args, **kwargs: restore_compact_result_anchor(*args, **kwargs),
        show_record_details=lambda *args, **kwargs: show_record_details(*args, **kwargs),
    )

    render_table = build_collection_table(
        RELATIONSHIP_DISPLAY_FIELDS=RELATIONSHIP_DISPLAY_FIELDS,
        add_timestamp_slots=lambda *args, **kwargs: add_timestamp_slots(*args, **kwargs),
        api=api,
        collection_state=collection_state,
        current_session_revoked=lambda *args, **kwargs: current_session_revoked(*args, **kwargs),
        decorate_for_spec=lambda *args, **kwargs: decorate_for_spec(*args, **kwargs),
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        favourite_state=lambda *args, **kwargs: favourite_state(*args, **kwargs),
        format_timestamp=lambda *args, **kwargs: format_timestamp(*args, **kwargs),
        guidance=guidance,
        load_recent=lambda *args, **kwargs: load_recent(*args, **kwargs),
        load_rows=lambda *args, **kwargs: load_rows(*args, **kwargs),
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        open_editor=lambda *args, **kwargs: open_editor(*args, **kwargs),
        reload_favourites=lambda *args, **kwargs: reload_favourites(*args, **kwargs),
        render_administration_cards=lambda *args, **kwargs: render_administration_cards(*args, **kwargs),
        render_entity_compact_results=lambda *args, **kwargs: render_entity_compact_results(*args, **kwargs),
        render_recent_section=lambda *args, **kwargs: render_recent_section(*args, **kwargs),
        render_resource_personal_sections=lambda *args, **kwargs: render_resource_personal_sections(*args, **kwargs),
        required_principal=lambda: auth_state["principal"],
        select_organization_unit_details=lambda *args, **kwargs: select_organization_unit_details(*args, **kwargs),
        select_role_details=lambda *args, **kwargs: select_role_details(*args, **kwargs),
        select_user_details=lambda *args, **kwargs: select_user_details(*args, **kwargs),
        show_api_error=lambda *args, **kwargs: show_api_error(*args, **kwargs),
        show_components=lambda *args, **kwargs: show_components(*args, **kwargs),
        show_entity_history=lambda *args, **kwargs: show_entity_history(*args, **kwargs),
        show_memberships=lambda *args, **kwargs: show_memberships(*args, **kwargs),
        show_profile_privilege_editor=lambda *args, **kwargs: show_profile_privilege_editor(*args, **kwargs),
        show_record_details=lambda *args, **kwargs: show_record_details(*args, **kwargs),
        show_reopen_aggregation=lambda *args, **kwargs: show_reopen_aggregation(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        toggle_favourite=lambda *args, **kwargs: toggle_favourite(*args, **kwargs),
    )

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
        state.update(resource='login-sessions'); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
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


    def enter_audit_trail() -> None:
        register_navigation("audit-trail", "Audit trail")
        show_authenticated_view()
        state.update(resource='audit-trail'); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
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
        state.update(resource='org-unit-details'); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)


    def enter_organization_roles() -> None:
        state.update(resource='role-details'); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)





    def enter_organization_users() -> None:
        state.update(resource='user-details'); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)


    def enter_organization_browser() -> None:
        state.update(resource='organization-browser'); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)


    select_governance_custody = build_governance_custody(
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_mode_bar=aggregation_mode_bar,
        api=api,
        can_open_settings=lambda: application_settings_controller.can_open(),
        clear_collection=lambda: collection_state.update(rows=[], searched=True),
        enter_governance_custody=lambda: state.update(resource="governance-custody"),
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        format_timestamp=lambda *args, **kwargs: format_timestamp(*args, **kwargs),
        get_principal=lambda: auth_state.get("principal"),
        get_resource=lambda: state.get("resource"),
        guidance=guidance,
        open_settings=lambda: application_settings_controller.open_from_custody(),
        register_navigation=lambda *args, **kwargs: register_navigation(*args, **kwargs),
        search_bar=search_bar,
        select_entity=lambda *args, **kwargs: select_entity(*args, **kwargs),
        select_role_details=lambda *args, **kwargs: select_role_details(*args, **kwargs),
        select_user_details=lambda *args, **kwargs: select_user_details(*args, **kwargs),
        show_authenticated_view=lambda *args, **kwargs: show_authenticated_view(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )

    select_security_operations = build_security_operations(
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_mode_bar=aggregation_mode_bar,
        api=api,
        enter_security_operations=lambda: (state.update(resource="security-operations"), collection_state.update(rows=[], searched=True)),
        format_timestamp=lambda *args, **kwargs: format_timestamp(*args, **kwargs),
        get_resource=lambda: state.get("resource"),
        guidance=guidance,
        localized_lifecycle_value=lambda *args, **kwargs: localized_lifecycle_value(*args, **kwargs),
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        page_client=page_client,
        principal=lambda: auth_state.get("principal"),
        register_navigation=lambda *args, **kwargs: register_navigation(*args, **kwargs),
        search_bar=search_bar,
        select_classification_workspace=lambda *args, **kwargs: select_classification_workspace(*args, **kwargs),
        select_organization_unit_details=lambda *args, **kwargs: select_organization_unit_details(*args, **kwargs),
        select_record_details=lambda *args, **kwargs: select_record_details(*args, **kwargs),
        select_role_details=lambda *args, **kwargs: select_role_details(*args, **kwargs),
        select_user_details=lambda *args, **kwargs: select_user_details(*args, **kwargs),
        show_api_error=lambda *args, **kwargs: show_api_error(*args, **kwargs),
        show_authenticated_view=lambda *args, **kwargs: show_authenticated_view(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )

    select_saved_search_administration = build_saved_search_administration(
        add_button=add_button,
        add_record_button=add_record_button,
        advanced_search_state=advanced_search_state,
        aggregation_mode_bar=aggregation_mode_bar,
        aggregation_state=aggregation_state,
        api=api,
        collection_state=collection_state,
        enter_saved_administration=lambda page: state.update(resource=page),
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        format_timestamp=lambda *args, **kwargs: format_timestamp(*args, **kwargs),
        get_principal=lambda: auth_state.get("principal"),
        get_resource=lambda: state.get("resource"),
        guidance=guidance,
        register_navigation=lambda *args, **kwargs: register_navigation(*args, **kwargs),
        search_bar=search_bar,
        select_advanced_search=lambda *args, **kwargs: select_advanced_search(*args, **kwargs),
        show_authenticated_view=lambda *args, **kwargs: show_authenticated_view(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )

    select_advanced_search = build_advanced_search(
        add_button=add_button,
        add_record_button=add_record_button,
        advanced_search_state=advanced_search_state,
        aggregation_mode_bar=aggregation_mode_bar,
        aggregation_state=aggregation_state,
        api=api,
        bind_remote_relationship_select=lambda *args, **kwargs: bind_remote_relationship_select(*args, **kwargs),
        bind_remote_saved_audience_select=lambda *args, **kwargs: bind_remote_saved_audience_select(*args, **kwargs),
        browse_advanced_aggregation=lambda *args, **kwargs: browse_advanced_aggregation(*args, **kwargs),
        browse_advanced_classification=lambda *args, **kwargs: browse_advanced_classification(*args, **kwargs),
        collection_state=collection_state,
        discard_navigation_guard=lambda: state.pop("discard_navigation_guard", None),
        enter_advanced_search=lambda: state.update(resource="advanced-search"),
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        format_timestamp=lambda *args, **kwargs: format_timestamp(*args, **kwargs),
        get_principal=lambda: auth_state.get("principal"),
        get_resource=lambda: state.get("resource"),
        guidance=guidance,
        localized_editor_entity=lambda *args, **kwargs: localized_editor_entity(*args, **kwargs),
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        register_navigation=lambda *args, **kwargs: register_navigation(*args, **kwargs),
        render_compact_resource_result=lambda *args, **kwargs: render_compact_resource_result(*args, **kwargs),
        restore_compact_result_anchor=lambda *args, **kwargs: restore_compact_result_anchor(*args, **kwargs),
        search_bar=search_bar,
        select_record_details=lambda *args, **kwargs: select_record_details(*args, **kwargs),
        set_navigation_guard=lambda guard: state.__setitem__("discard_navigation_guard", guard),
        show_authenticated_view=lambda *args, **kwargs: show_authenticated_view(*args, **kwargs),
        show_organization_structure=lambda *args, **kwargs: show_organization_structure(*args, **kwargs),
        style_status_chip_select=lambda *args, **kwargs: style_status_chip_select(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )

    async def open_related_resource(kind: str, identity: int) -> None:
        if kind == "record":
            await select_record_details(identity)
        else:
            await open_aggregation(await api.get("aggregations", identity))

    def enter_application_settings() -> None:
        """Adapt the Settings feature to the existing shared shell."""
        state.update(resource='application-settings'); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
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

    select_disposition = build_disposition_controller(
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_mode_bar=aggregation_mode_bar,
        aggregation_state=aggregation_state,
        api=api,
        bind_remote_relationship_select=lambda *args, **kwargs: bind_remote_relationship_select(*args, **kwargs),
        browse_advanced_aggregation=lambda *args, **kwargs: browse_advanced_aggregation(*args, **kwargs),
        collection_state=collection_state,
        current_navigation_snapshot=lambda *args, **kwargs: current_navigation_snapshot(*args, **kwargs),
        disposition_state=disposition_state,
        enter_disposition=lambda page: state.update(resource=page),
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        format_timestamp=lambda *args, **kwargs: format_timestamp(*args, **kwargs),
        get_principal=lambda: auth_state.get("principal"),
        get_resource=lambda: state.get("resource"),
        guarded_page_navigation=lambda *args, **kwargs: guarded_page_navigation(*args, **kwargs),
        guidance=guidance,
        navigation_controller=navigation_controller,
        open_related_resource=lambda *args, **kwargs: open_related_resource(*args, **kwargs),
        persist_navigation_trail=lambda *args, **kwargs: persist_navigation_trail(*args, **kwargs),
        preview_record_components=lambda *args, **kwargs: preview_record_components(*args, **kwargs),
        register_navigation=lambda *args, **kwargs: register_navigation(*args, **kwargs),
        search_bar=search_bar,
        set_discard_guard=lambda guard: state.__setitem__("discard_navigation_guard", guard),
        show_authenticated_view=lambda *args, **kwargs: show_authenticated_view(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )

    def enter_relationship_types() -> None:
        """Adapt relationship-type administration to the existing shared shell."""
        state.update(resource='relationship-types'); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
        register_navigation("relationship-types", localized_navigation["relationship-types"])
        show_authenticated_view()
        title.text = localized_navigation["relationship-types"]
        subtitle.text = ""
        guidance.text = ""
        for control in (search_bar, aggregation_mode_bar, add_button, add_record_button):
            control.set_visibility(False)
        table_container.clear()

    select_messages = build_messaging_controller(
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_mode_bar=aggregation_mode_bar,
        aggregation_state=aggregation_state,
        api=api,
        bind_remote_relationship_select=lambda *args, **kwargs: bind_remote_relationship_select(*args, **kwargs),
        collection_state=collection_state,
        enter_messages=lambda key: state.update(resource=key),
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        format_timestamp=lambda *args, **kwargs: format_timestamp(*args, **kwargs),
        get_principal=lambda: auth_state.get("principal"),
        get_resource=lambda: state.get("resource"),
        guarded_page_navigation=lambda *args, **kwargs: guarded_page_navigation(*args, **kwargs),
        guidance=guidance,
        localized_navigation=localized_navigation,
        medium_label=lambda *args, **kwargs: medium_label(*args, **kwargs),
        messaging_state=messaging_state,
        open_aggregation=lambda *args, **kwargs: open_aggregation(*args, **kwargs),
        open_record_draft_editor=lambda *args, **kwargs: open_record_draft_editor(*args, **kwargs),
        preview_record_components=lambda *args, **kwargs: preview_record_components(*args, **kwargs),
        refresh_message_unread=lambda *args, **kwargs: refresh_message_unread(*args, **kwargs),
        register_navigation=lambda *args, **kwargs: register_navigation(*args, **kwargs),
        search_bar=search_bar,
        select_audit_trail=lambda *args, **kwargs: select_audit_trail(*args, **kwargs),
        select_disposition=lambda *args, **kwargs: select_disposition(*args, **kwargs),
        show_authenticated_view=lambda *args, **kwargs: show_authenticated_view(*args, **kwargs),
        show_organization_structure=lambda *args, **kwargs: show_organization_structure(*args, **kwargs),
        show_record_details=lambda *args, **kwargs: show_record_details(*args, **kwargs),
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )

    select_entity = build_collection_navigation(
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_mode_bar=aggregation_mode_bar,
        aggregation_state=aggregation_state,
        collection_state=collection_state,
        error_message=lambda *args, **kwargs: error_message(*args, **kwargs),
        get_resource=lambda: state.get("resource"),
        guidance=guidance,
        load_recent=lambda *args, **kwargs: load_recent(*args, **kwargs),
        load_rows=lambda *args, **kwargs: load_rows(*args, **kwargs),
        personal=personal,
        principal=lambda: auth_state.get("principal"),
        register_navigation=lambda *args, **kwargs: register_navigation(*args, **kwargs),
        reload_favourites=lambda *args, **kwargs: reload_favourites(*args, **kwargs),
        render_resource_personal_sections=lambda *args, **kwargs: render_resource_personal_sections(*args, **kwargs),
        render_table=lambda *args, **kwargs: render_table(*args, **kwargs),
        search_bar=search_bar,
        search_input=search_input,
        select_aggregation_browser=lambda *args, **kwargs: select_aggregation_browser(*args, **kwargs),
        set_connection_status=lambda *args, **kwargs: set_connection_status(*args, **kwargs),
        set_resource=lambda key: state.update(resource=key),
        show_authenticated_view=lambda *args, **kwargs: show_authenticated_view(*args, **kwargs),
        subtitle=subtitle,
        title=title,
    )

    async def select_classification_workspace(
        initial_scheme_id: int | None = None,
        initial_classification_id: int | None = None,
    ) -> None:
        await classification_controller.open(initial_scheme_id, initial_classification_id)

    def begin_classification_workspace() -> None:
        show_authenticated_view()
        state.update(resource='classification-workspace'); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)

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
        state.update(resource='holds'); collection_state.update(rows=[], searched=True)

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
        state.update(resource='hold-details'); collection_state.update(rows=[], searched=True)

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
        state.update(resource='translations'); collection_state.update(rows=[], searched=True)

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
        collection_state["rows"] = rows
        collection_state["searched"] = searched

    load_rows = build_collection_loader(
        api, get_resource=lambda: state["resource"], get_query=lambda: search_input.value,
        pages=collection_state["collection_pages"], accept_results=accept_collection_results,
        clear_result_state=lambda resource: collection_state.setdefault("entity_result_states", {}).pop(resource, None),
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
        pages=collection_state["collection_pages"],
        reset_lifecycle_filter=lambda: collection_state.update(lifecycle_filter='all'),
        get_rows=lambda: collection_state["rows"],
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
        state.update(resource='text-indexers'); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)

    def enter_text_indexer_details() -> None:
        state.update(resource='text-indexer-details'); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)

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

    open_live_delivery, show_message_notification, stop_message_stream, refresh_message_unread, start_message_stream = build_message_stream(
        api=api,
        get_principal=lambda: auth_state.get("principal"),
        get_resource=lambda: state.get("resource"),
        handle_unauthorized=lambda *args, **kwargs: handle_unauthorized(*args, **kwargs),
        message_live=message_live,
        message_unread_button=message_unread_button,
        messaging_state=messaging_state,
        page_client=page_client,
        select_messages=lambda *args, **kwargs: select_messages(*args, **kwargs),
    )

    ui.on("messaging_open", open_live_delivery)





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
