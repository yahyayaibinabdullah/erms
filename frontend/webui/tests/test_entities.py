from io import BytesIO
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend.webui.app import (
    AGGREGATION_SUMMARY_LAYOUT_CLASSES,
    CHILD_AGGREGATION_CLASSIFICATION_HELP,
    CLASSIFICATION_WORKSPACE_SEARCH_FIELDS,
    CLASSIFICATION_SELECTOR_SEARCH_FIELDS,
    RECORD_UPLOAD_WAIT_MESSAGE,
    RECORD_DETAIL_HEADER_CLASSES,
    RECORD_DETAIL_TITLE_CLASSES,
    RELATIONSHIP_DISPLAY_FIELDS,
    LIFECYCLE_ACTION_BUTTONS,
    LAST_CUSTODIAN_MESSAGE,
    LAST_CUSTODIAN_TITLE,
    NAVIGATION_TRAIL_LIMIT,
    NAVIGATION_VISIBLE_LIMIT,
    USER_SUSPENSION_ACTION_BUTTONS,
    STOP_PROPAGATION_CLICK_HANDLER,
    apply_relationship_selection,
    buffer_upload_batch,
    component_uploader,
    component_file_icon,
    component_is_previewable,
    decorate_relationship_rows,
    deletion_blocked_report,
    deletion_identity,
    direct_classification_label,
    display_value,
    error_message,
    show_api_error,
    field_input,
    format_file_size,
    form_payload,
    format_timestamp,
    filter_membership_rows,
    index,
    medium_label,
    user_avatar,
    relationship_options,
    record_draft_component_context,
    render_component_cards,
    requires_document_conversion,
    role_change_requires_reason,
    append_navigation_entry,
    visible_navigation_indices,
)
from frontend.webui.api_client import ApiError
from frontend.webui.app import native_preview_kind
from frontend.webui.entities import ENTITIES
from frontend.webui.config import (
    classification_recent_selection_limit,
    database_display_name,
    dashboard_favourite_item_limit,
    dashboard_recent_days,
    dashboard_recent_item_limit,
    user_details_session_limit,
)
from frontend.webui.app import favourite_preview, personal_dialog_list_height
from frontend.webui.tests.localization_assertions import with_english_messages

APP_SOURCE = with_english_messages(inspect.getsource(index))
WORKSPACE_SOURCE = (Path(__file__).parents[1] / "classification_workspace.py").read_text()
TIMELINE_SOURCE = (Path(__file__).parents[1] / "retention_timeline.py").read_text()


def test_direct_classification_label_uses_only_leaf_classification():
    path = [
        {"code": "1000", "title": "Corporate functions"},
        {"code": "1100", "title": "Leadership affairs"},
        {"code": "1111", "title": "Meeting agendas"},
    ]

    assert direct_classification_label(path) == "1111 — Meeting agendas"
    assert direct_classification_label([]) == "—"


def test_record_draft_component_context_requires_and_normalizes_visible_form_values():
    assert record_draft_component_context("17", "digital") == {
        "aggregation_id": 17,
        "medium": "digital",
    }
    with pytest.raises(ValueError, match="Select the parent aggregation"):
        record_draft_component_context(None, "digital")
    with pytest.raises(ValueError, match="record medium"):
        record_draft_component_context(17, None)


def test_native_preview_kind_uses_safe_browser_renderers():
    assert native_preview_kind("image/png") == "image"
    assert native_preview_kind("audio/mpeg") == "audio"
    assert native_preview_kind("video/mp4") == "video"
    assert native_preview_kind("image/svg+xml") is None
    assert native_preview_kind("application/pdf") is None


def test_phase1_previewability_requires_available_supported_content():
    assert component_is_previewable({
        "content_status": "available", "mime_type": "application/pdf", "file_name": "a.pdf",
    })
    assert component_is_previewable({
        "content_status": "available", "mime_type": "text/plain", "file_name": "a.txt",
    })
    assert component_is_previewable({
        "content_status": "available", "mime_type": "image/png", "file_name": "a.png",
    })
    assert not component_is_previewable({
        "content_status": "pending", "mime_type": "application/pdf", "file_name": "a.pdf",
    })
    assert not component_is_previewable({
        "content_status": "available", "mime_type": "application/zip", "file_name": "a.zip",
    })


def test_phase1_preview_controls_and_entry_points_are_present():
    source = APP_SOURCE
    assert "async def preview_record_components(" in source
    assert "Preview digital components" in source
    assert 'capabilities.get("download_component")' in source
    assert 'capabilities.get("print_component")' in source
    assert "Print document" in source
    assert "window.__ermsPrintWindow = w" in source
    assert 'record.get("medium") != "physical"' in source
    assert 'component_order' in source
    assert "viewer_client = context.client" in source
    viewer_source = source.split("async def preview_record_components(", 1)[1].split(
        "async def show_components(", 1
    )[0]
    assert "ui.run_javascript(" not in viewer_source
    assert "viewer_client.run_javascript(" in viewer_source


def test_component_surfaces_use_bounded_server_pages_and_cross_page_moves():
    source = APP_SOURCE
    assert "api.components(" not in source
    assert 'component_page = {"limit": 25, "offset": 0, "total": 0}' in source
    assert 'api.component_page(' in source
    assert 'await api.move_component(record["id"], component["id"], direction)' in source
    assert 'first_position = int(component_page["total"]) + 1' in source
    assert 'component_total = await api.component_count(record["id"])' in source
    assert 'preview_page = {"limit": 50, "offset": 0, "total": 0}' in source


def test_pdf_preview_is_isolated_from_the_arabic_ui_direction():
    assert 'ui.element("canvas").props(f"id={canvas_id} dir=ltr")' in APP_SOURCE
    viewer_source = (
        Path(__file__).parents[1] / "static" / "pdfjs" / "erms-viewer.mjs"
    ).read_text(encoding="utf-8")
    assert "canvas.dir = 'ltr';" in viewer_source
    assert "context.direction = 'ltr';" in viewer_source
    assert "page.render({canvasContext: context" in viewer_source


def test_pdf_print_does_not_wait_for_animation_frames_in_the_background_viewer():
    viewer_source = (
        Path(__file__).parents[1] / "static" / "pdfjs" / "erms-viewer.mjs"
    ).read_text(encoding="utf-8")
    print_source = viewer_source.split("async function printDocument(", 1)[1].split(
        "window.ermsPdfViewer =", 1
    )[0]
    # PDF.js defaults to display intent, which schedules rendering using the
    # opener's requestAnimationFrame. A focused print tab can suspend it.
    assert "viewport, intent: 'print'" in print_source


@pytest.mark.parametrize("extension", ("md", "msg", "eml", "html", "txt", "xml"))
def test_additional_document_formats_show_conversion_progress(extension):
    assert requires_document_conversion({
        "file_name": f"example.{extension}",
        "mime_type": "application/octet-stream",
    })


class Control:
    def __init__(self, value):
        self.value = value


def test_first_class_navigation_excludes_digital_components():
    assert tuple(ENTITIES) == (
        "aggregations", "records", "classification-schemes", "classifications",
        "org-units", "users", "roles", "security-levels", "profiles", "privileges",
        "permissions",
    )
    assert ENTITIES["aggregations"].search_first
    assert ENTITIES["records"].search_first
    assert ENTITIES["org-units"].fields[0].lookup_resource == "org-units"
    assert ENTITIES["roles"].fields[0].lookup_resource == "org-units"
    assert ENTITIES["roles"].fields[1].lookup_resource == "roles"


def test_identity_administration_lists_use_one_column_governance_cards():
    assert '{"security-levels", "profiles", "users", "roles", "org-units"}' in APP_SOURCE
    assert '"users": "Filter users"' in APP_SOURCE
    assert '"roles": "Filter roles"' in APP_SOURCE
    assert '"org-units": "Filter organization units"' in APP_SOURCE
    assert '"users": (' in APP_SOURCE
    assert '"roles": (' in APP_SOURCE
    assert '"org-units": (' in APP_SOURCE
    assert 'select_user_details(item["id"])' in APP_SOURCE
    assert 'select_role_details(item["id"])' in APP_SOURCE
    assert 'select_organization_unit_details(item["id"])' in APP_SOURCE
    assert 'show_memberships(item, for_user=user_view)' in APP_SOURCE
    assert 'else await api.search_request(' in APP_SOURCE
    assert 'include_system=True if spec.key == "roles" else None' in APP_SOURCE
    assert '"limit": int(page["limit"]), "offset": int(page["offset"])' in APP_SOURCE


def test_identity_card_headers_use_direction_aware_native_grid():
    header = APP_SOURCE.split('def render_governance_cards', 1)[1].split('facts_by_resource =', 1)[0]
    assert 'ui.grid(columns="auto minmax(0, 1fr) auto")' in header
    assert 'governance-card-header w-full items-start gap-3' in header
    assert 'with ui.row().classes("w-full items-start no-wrap gap-3")' not in header
    assert header.index('governance-card-icon') < header.index('card_value(row, "name")')


def test_governance_cards_display_and_sort_localized_entity_metadata():
    assert 'def card_value(row: dict[str, Any], field: str) -> Any:' in APP_SOURCE
    assert '(row.get("localized") or {}).get(field) or row.get(field)' in APP_SOURCE
    assert 'ui.label(card_value(row, "name") or "Unnamed")' in APP_SOURCE
    assert 'ui.label(card_value(row, "description") or "No description provided")' in APP_SOURCE
    assert 'sort=card_sort.value' in APP_SOURCE
    assert '(spec.key == "users" and fact_index == 2)' in APP_SOURCE
    assert '(spec.key == "profiles" and fact_index == 3)' in APP_SOURCE
    assert '(spec.key == "org-units" and fact_index in {2, 3})' in APP_SOURCE
    assert 'fact_value.props(\'dir="ltr"\').classes("text-left")' in APP_SOURCE


def test_dashboard_overview_uses_compact_holdings_first_layout():
    assert 'ui.label("Overview").classes("text-lg font-semibold")' in APP_SOURCE
    assert '"dashboard-overview-primary w-full"' in APP_SOURCE
    assert 'ui.label("Visible to you")' in APP_SOURCE
    assert '"dashboard-overview-admin"' in APP_SOURCE
    assert 'html[dir="rtl"] .dashboard-overview-heading' in APP_SOURCE
    assert 'html[dir="rtl"] .dashboard-overview-card-heading' in APP_SOURCE
    assert 'direction: rtl; flex-direction: row !important;' in APP_SOURCE
    assert '"dashboard-overview-card-heading w-full items-center no-wrap gap-3"' in APP_SOURCE


def test_classification_tree_uses_logical_indentation_and_direction_aware_expanders():
    assert 'padding-inline-start:' in WORKSPACE_SOURCE
    assert '"chevron_left" if direction() == "rtl" else "chevron_right"' in WORKSPACE_SOURCE
    assert 'aria-expanded=' in WORKSPACE_SOURCE
    assert 'flex-row-reverse' not in WORKSPACE_SOURCE


def test_classification_icons_point_toward_rtl_labels():
    assert 'html[dir="rtl"] .classification-directional-icon .q-icon' in APP_SOURCE
    assert 'transform: scaleX(-1)' in APP_SOURCE
    assert 'if icon in {"label", "schema", "account_tree"}:' in WORKSPACE_SOURCE
    assert 'button.classes("classification-directional-icon")' in WORKSPACE_SOURCE
    assert 'classes("classification-directional-icon")' in WORKSPACE_SOURCE


def test_aggregation_browser_tree_keeps_expanders_at_rtl_inline_start():
    assert 'html[dir="rtl"] #aggregation-browser-tree .aggregation-browser-tree-row' in APP_SOURCE
    assert "direction: rtl;" in APP_SOURCE
    assert "flex-direction: row !important;" in APP_SOURCE
    assert APP_SOURCE.count('"aggregation-browser-tree-row w-full items-center no-wrap') == 3
    assert 'py-1 pe-2 hover:bg-blue-50' in APP_SOURCE
    assert 'py-2 pe-2 hover:bg-blue-50 cursor-pointer' in APP_SOURCE


def test_classification_workspace_has_exclusive_tree_and_detail_pages():
    assert 'browser_host.set_visibility(False)' in WORKSPACE_SOURCE
    assert 'detail_host.set_visibility(False)' in WORKSPACE_SOURCE
    assert 'register_page("classification-scheme-details", fresh)' in WORKSPACE_SOURCE
    assert 'register_page("classification-details", selected)' in WORKSPACE_SOURCE
    assert 'classification-scheme-master-detail' not in WORKSPACE_SOURCE
    assert 'open_in_new' not in WORKSPACE_SOURCE


def test_classification_detail_rows_use_single_logical_rtl_order():
    rtl_rules = APP_SOURCE.split('html[dir="rtl"] .classification-detail-title-status,', 1)[1].split('}', 1)[0]
    for class_name in (
        "classification-detail-title-status",
        "classification-detail-actions", "classification-detail-warning",
        "classification-tree-toolbar", "classification-selected-identity",
    ):
        if class_name != "classification-detail-title-status":
            assert f'.{class_name}' in rtl_rules
        assert class_name in APP_SOURCE
    assert 'direction: rtl; flex-direction: row !important;' in rtl_rules
    assert '("classification-schemes", "Classification schemes", "account_tree"' in APP_SOURCE
    assert 'ui.label("System overview")' not in APP_SOURCE


def test_dashboard_uses_compact_favourites_and_recent_record_streams():
    assert APP_SOURCE.count("await api.dashboard_summary(") == 1
    assert "recent_limit=50, recent_since=recent_since" in APP_SOURCE
    assert '"dashboard-personal-columns mt-2"' in APP_SOURCE
    assert 'ui.label("Favourites")' in APP_SOURCE
    assert 'ui.label("Recent records activity")' in APP_SOURCE
    assert 'item["operation"] in {"CREATE", "UPDATE", "CONTENT_VIEWED"}' in APP_SOURCE
    assert '"CONTENT_VIEWED": ("Viewed", "visibility", "dashboard-activity-viewed")' in APP_SOURCE
    assert 'ui.label("Your favourites")' not in APP_SOURCE
    assert 'personal_sections_area = ui.element("div").classes("w-full")' in APP_SOURCE
    assert APP_SOURCE.index(
        'personal_sections_area = ui.element("div").classes("w-full")'
    ) < APP_SOURCE.index('ui.label("Holdings by organizational unit")')
    assert "with personal_sections_area:" in APP_SOURCE


def test_records_and_aggregations_landing_use_dashboard_personal_panel_treatment():
    raw_source = inspect.getsource(index)
    source = with_english_messages(raw_source)
    assert 'def render_resource_personal_sections(' in source
    personal = raw_source[
        raw_source.index('def render_resource_personal_sections('):
        raw_source.index('async def show_profile_privilege_editor')
    ]
    assert 'localized_singular = ' in personal
    assert 'localized_plural = ' in personal
    retained_context = 'with personal_host, ui.element("div").classes("dashboard-personal-columns w-full px-5 pt-5 pb-5"):'
    assert personal.index(retained_context) < personal.index('localized_singular = ')
    assert personal.index(retained_context) < personal.index('localized_plural = ')
    assert 'singular=localized_singular' in personal
    assert 'resource=localized_plural' in personal
    assert 'ui.label(f"Favourite {localized_plural}").classes("font-semibold text-slate-800")' in source
    assert 'ui.label(f"Recent {localized_singular} activity").classes("font-semibold text-slate-800")' in source
    assert '"dashboard-personal-columns w-full px-5 pt-5 pb-5"' in source
    assert source.count('"dashboard-personal-item"') >= 4
    assert 'f"dashboard-activity-badge {activity_class}"' in source
    assert 'activity = await api.recent_resource_activity(spec.key, limit=50, since=since)' in source
    assert 'decorated = await decorate_for_spec(spec, activity)' in source
    assert 'api.recent_resource_activity(spec.key, limit=50, since=since)' in source
    assert '"CONTENT_VIEWED": ("Viewed", "visibility", "dashboard-activity-viewed")' in source
    assert 'state["recent_activity"]' in source
    assert 'spec.key in {"aggregations", "records"}' in source
    assert 'render_resource_personal_sections(spec)' in source
    assert 'ui.label("Your recent records activity")' not in APP_SOURCE


def test_personal_view_all_dialogs_use_dedicated_scroll_container():
    assert ".dashboard-personal-dialog-list" in APP_SOURCE
    assert APP_SOURCE.count("dashboard-personal-dialog-list") >= 6
    assert APP_SOURCE.count("ui.scroll_area()") >= 6
    assert APP_SOURCE.count('.props("visible")') >= 5
    assert APP_SOURCE.count("height:min(65vh,") >= 5
    assert "dashboard-personal-panel w-full max-h-[65vh] overflow-y-auto" not in APP_SOURCE


def test_personal_dialog_list_height_is_compact_and_capped():
    assert personal_dialog_list_height(0) == 120
    assert personal_dialog_list_height(3) == 174
    assert personal_dialog_list_height(100) == 520


def test_classification_workspace_uses_available_height_without_fixed_panels():
    assert 'h-[870px]' not in WORKSPACE_SOURCE
    assert 'h-[420px]' not in WORKSPACE_SOURCE
    assert 'browser_host = ui.column().classes("classification-workspace w-full gap-3 p-3")' in WORKSPACE_SOURCE


def test_classification_workspace_uses_server_order_and_branch_pagination():
    load_children = WORKSPACE_SOURCE.split("async def load_children", 1)[1].split("async def load_classification_path", 1)[0]
    assert 'limit=PAGE_SIZE + 1, offset=len(existing)' in load_children
    assert '"roots_only": True' in load_children
    assert '"parent_classification_id": parent_id' in load_children
    # The list endpoint orders the entire sibling set before applying pagination.
    api_source = (Path(__file__).parents[3] / "backend/services/api/classification_management.py").read_text()
    assert 'ORDER BY c.code COLLATE "C" ASC, c.id ASC LIMIT %s OFFSET %s' in api_source


def test_dashboard_overview_shows_medium_breakdowns_and_admin_hold_total():
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in APP_SOURCE
    assert 'medium_counts = summary["overview_medium_counts"]' in APP_SOURCE
    assert '("physical", "inventory_2")' in APP_SOURCE
    assert '("digital", "cloud")' in APP_SOURCE
    assert '("mixed", "join_inner")' in APP_SOURCE
    assert 'if "holds.administer" in privileges:' in APP_SOURCE
    assert '("holds", "Holds", "gavel", select_holds)' in APP_SOURCE
    assert 'aggregation_status_counts = summary["overview_aggregation_status_counts"]' in APP_SOURCE
    assert 'attention_counts = summary["overview_resource_attention_counts"]' in APP_SOURCE
    assert 'component_metrics = summary["overview_digital_component_metrics"]' in APP_SOURCE
    assert '("open", "text-green-700")' in APP_SOURCE
    assert '("closed", "text-slate-500")' in APP_SOURCE
    assert 'f"dashboard-overview-signal {status_color}"' in APP_SOURCE
    assert '(("vital", "emergency"), ("held", "gavel"))' in APP_SOURCE
    assert 'ui.label("|").classes("dashboard-overview-separator")' in APP_SOURCE
    assert '"dashboard-overview-signals"' not in APP_SOURCE
    assert '"dashboard.metric.components",count=component_metrics["component_count"]' in inspect.getsource(index)
    assert 'ui.icon("storage", size="13px")' in APP_SOURCE
    assert 'format_file_size(component_metrics["storage_size_in_bytes"])' in APP_SOURCE


def test_dashboard_adds_attention_chart_without_removing_overview_counts():
    assert '"dashboard-attention-chart"' in APP_SOURCE
    assert ".dashboard-attention-chart {" in APP_SOURCE
    assert "width: 50%; margin-inline: auto;" in APP_SOURCE
    assert "padding: 12px 32px 28px 54px" in APP_SOURCE
    assert 'ui.label("Attention signals")' in APP_SOURCE
    assert '"Visible vital and effectively held resources."' in APP_SOURCE
    assert 'attention_counts["aggregations"]["vital"]' in APP_SOURCE
    assert 'attention_counts["aggregations"]["held"]' in APP_SOURCE
    assert 'attention_counts["records"]["vital"]' in APP_SOURCE
    assert 'attention_counts["records"]["held"]' in APP_SOURCE
    assert APP_SOURCE.index(
        'with ui.element("div").classes("dashboard-overview-admin")'
    ) < APP_SOURCE.index(
        'with ui.element("section").classes("dashboard-attention-chart")'
    )
    assert '("vital", "emergency")' in APP_SOURCE
    assert '("held", "gavel")' in APP_SOURCE


def test_dashboard_adds_holdings_chart_without_removing_unit_rows():
    assert '"dashboard-holdings-chart"' in APP_SOURCE
    assert ".dashboard-holdings-chart {" in APP_SOURCE
    assert ".dashboard-storage-chart { width: 100%; }" in APP_SOURCE
    assert 'ui.label("Records by medium")' in APP_SOURCE
    assert '"Compare record volume and medium mix across your units."' in APP_SOURCE
    assert 'owner_count[f"{medium}_record_count"]' in APP_SOURCE
    assert '"dashboard-holdings-list"' in APP_SOURCE
    assert APP_SOURCE.index(
        'with ui.element("section").classes("dashboard-holdings-chart")'
    ) < APP_SOURCE.index(
        'with ui.element("div").classes("dashboard-holdings-list")'
    )
    assert 'ui.icon("storage", size="14px")' in APP_SOURCE


def test_dashboard_adds_review_urgency_chart_without_removing_reminder_lists():
    assert '"dashboard-review-layout"' in APP_SOURCE
    assert '"dashboard-review-summary"' in APP_SOURCE
    assert 'ui.label("Review urgency")' in APP_SOURCE
    assert 'overdue_total = int(summary["overdue_review_count"])' in APP_SOURCE
    assert 'upcoming_total = int(summary["upcoming_review_count"])' in APP_SOURCE
    assert '"dashboard-review-columns"' in APP_SOURCE
    assert '"View all", icon="arrow_forward"' in APP_SOURCE


def test_dashboard_ends_with_top_five_digital_storage_chart_and_other_summary():
    assert 'ui.label("Digital storage by organizational unit")' in APP_SOURCE
    assert '"dashboard-storage-chart"' in APP_SOURCE
    assert 'top_storage_units = ranked_storage_units[:5]' in APP_SOURCE
    assert 'other_storage_units = ranked_storage_units[5:]' in APP_SOURCE
    assert '"dashboard.storage.other_units",count=len(other_storage_units)' in inspect.getsource(index)
    assert 'ui.label("Combined remainder")' in APP_SOURCE
    assert 'int(item["storage_size_in_bytes"])' in APP_SOURCE
    assert APP_SOURCE.index(
        'with ui.element("div").classes("dashboard-personal-columns mt-2")'
    ) < APP_SOURCE.index(
        'with ui.element("section").classes("dashboard-storage-chart")'
    )


def test_form_payload_converts_ids_and_omits_empty_create_fields():
    spec = ENTITIES["records"]
    controls = {
        "aggregation_id": Control(12.0),
        "record_number": Control(" REC-12 "),
        "title": Control("Annual report"),
        "description": Control(""),
        "date_originated": Control(""),
        "date_of_next_review": Control(""),
        "security_level_id": Control(1.0),
        "medium": Control("mixed"),
    }
    assert form_payload(spec, controls, creating=True) == {
        "aggregation_id": 12,
        "record_number": "REC-12",
        "title": "Annual report",
        "security_level_id": 1,
        "medium": "mixed",
    }


def test_form_payload_rejects_required_blank_value():
    spec = ENTITIES["users"]
    controls = {"name": Control("  "), "email": Control(""), "external_id": Control("")}
    with pytest.raises(ValueError) as error:
        form_payload(spec, controls, creating=True)
    assert str(error.value).replace("\u2068", "").replace("\u2069", "") == "Name is required"


def test_relationship_options_prioritize_name_over_internal_id():
    options = relationship_options(
        [{"id": 42, "code": "RM", "name": "Records Management"}],
        ("code", "name"),
    )
    assert options == {42: "RM · Records Management"}


def test_security_level_relationship_options_use_localized_name_and_level():
    options = relationship_options(
        [{
            "id": 42, "code": "G", "name": "General", "level_number": 1,
            "localized": {"name": "عام"},
        }],
        ("code", "name"),
        include_level_number=True,
        level_label="المستوى",
    )
    assert options == {42: "G · عام · المستوى 1"}


def test_relationship_columns_replace_foreign_keys_with_business_labels():
    units = [
        {"id": 1, "code": "HQ", "name": "Headquarters", "parent_org_unit_id": None},
        {"id": 2, "code": "RM", "name": "Records", "parent_org_unit_id": 1},
    ]
    decorated_units = decorate_relationship_rows("org-units", units)
    assert decorated_units[1]["parent_org_unit_display"] == {
        "name": "Headquarters", "code": "HQ"
    }

    roles = [{"id": 8, "org_unit_id": 2, "code": "DIR", "name": "Director"}]
    decorated_roles = decorate_relationship_rows("roles", roles, units)
    assert decorated_roles[0]["org_unit_display"] == {
        "name": "Records", "code": "RM"
    }


def test_timestamp_formatter_is_human_readable():
    formatted = format_timestamp("2026-09-15T08:05:00+00:00")
    assert "2026" in formatted
    assert "T08:05:00" not in formatted
    assert format_timestamp(None) == "—"


def test_plain_metadata_containing_uppercase_t_is_not_treated_as_a_timestamp():
    code = "CORPORATE-RECORDS-MANAGEMENT-SCHEME-2026"
    description = "This description must remain complete."
    assert display_value(code) == code
    assert display_value(description) == description
    assert display_value(None) == "—"


def test_medium_label_uses_accessible_business_terms():
    assert medium_label("digital") == "Digital"
    assert medium_label("physical") == "Physical"
    assert medium_label("mixed") == "Mixed"
    assert medium_label(None) == "—"


def test_dashboard_recent_configuration(monkeypatch):
    monkeypatch.setenv("DASHBOARD_RECENT_ITEM_LIMIT", "7")
    monkeypatch.setenv("DASHBOARD_RECENT_DAYS", "14")
    assert dashboard_recent_item_limit() == 7
    assert dashboard_recent_days() == 14


def test_database_display_name_uses_language_override_and_default_fallback(monkeypatch):
    monkeypatch.setenv("DATABASE_DISPLAY_NAME", "Production Database")
    monkeypatch.setenv("DATABASE_DISPLAY_NAME_AR", "قاعدة بيانات الإنتاج")
    monkeypatch.setenv("DATABASE_DISPLAY_NAME_FR", "Base de données de production")
    assert database_display_name("en") == "Production Database"
    assert database_display_name("ar-AE") == "قاعدة بيانات الإنتاج"
    assert database_display_name("fr-FR") == "Base de données de production"
    monkeypatch.setenv("DATABASE_DISPLAY_NAME_AR", "  ")
    assert database_display_name("ar") == "Production Database"


def test_database_display_name_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_DISPLAY_NAME", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_DISPLAY_NAME is required"):
        database_display_name("en")


def test_dashboard_favourite_configuration_and_preview(monkeypatch):
    monkeypatch.setenv("DASHBOARD_FAVOURITE_ITEM_LIMIT", "2")
    assert dashboard_favourite_item_limit() == 2
    items = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert favourite_preview(items, 2) == (items[:2], True)
    assert favourite_preview(items[:2], 2) == (items[:2], False)


def test_dashboard_favourite_configuration_defaults_to_five(monkeypatch):
    monkeypatch.delenv("DASHBOARD_FAVOURITE_ITEM_LIMIT", raising=False)
    assert dashboard_favourite_item_limit() == 5


def test_user_details_session_limit_defaults_to_five_and_is_configurable(monkeypatch):
    monkeypatch.delenv("USER_DETAILS_SESSION_LIMIT", raising=False)
    assert user_details_session_limit() == 5
    monkeypatch.setenv("USER_DETAILS_SESSION_LIMIT", "8")
    assert user_details_session_limit() == 8


def test_membership_filters_identity_status_and_overlapping_validity():
    rows = [
        {
            "id": 1, "counterpart_search": "Alya Al-Salman alya@example.test",
            "counterpart_status": "active", "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": None,
        },
        {
            "id": 2, "counterpart_search": "Sami Jari sami@example.test",
            "counterpart_status": "suspended", "valid_from": "2025-01-01T00:00:00Z",
            "valid_until": "2025-12-31T23:59:59Z",
        },
    ]
    assert [row["id"] for row in filter_membership_rows(rows, query="alya")] == [1]
    assert [row["id"] for row in filter_membership_rows(rows, query="SAMI@EXAMPLE")] == [2]
    assert [row["id"] for row in filter_membership_rows(rows, status="suspended")] == [2]
    assert [row["id"] for row in filter_membership_rows(
        rows, valid_from="2026-06-01", valid_until="2026-06-30",
    )] == [1]


def test_user_avatar_is_stable_and_uses_best_effort_initials():
    user = {"id": 42, "name": "Sami Mali Jibtou Jari", "email": "sami@example.test"}
    first = user_avatar(user)
    assert first["initials"] == "SJ"
    assert first["color"] == "#e3f2fd"
    assert first["text_color"] == "#15527a"
    assert first == user_avatar(user)
    assert user_avatar({"id": 43, "name": "Admin"})["initials"] == "AD"
    assert user_avatar({"id": 44, "name": ""})["initials"] == "?"


def test_classification_recent_selection_configuration(monkeypatch):
    monkeypatch.setenv("CLASSIFICATION_RECENT_SELECTION_LIMIT", "6")
    assert classification_recent_selection_limit() == 6


def test_classification_workspace_search_includes_keywords():
    assert CLASSIFICATION_WORKSPACE_SEARCH_FIELDS == (
        "code", "title", "description", "keywords",
    )
    assert CLASSIFICATION_SELECTOR_SEARCH_FIELDS == (
        "code", "title", "description", "keywords",
    )
    assert ENTITIES["classifications"].search_fields == (
        "code", "title", "description", "keywords",
    )


def test_contextual_form_help_explains_disabled_controls():
    assert "inherit classification governance" in CHILD_AGGREGATION_CLASSIFICATION_HELP
    assert "cannot have a classification assigned directly" in CHILD_AGGREGATION_CLASSIFICATION_HELP
    assert RECORD_UPLOAD_WAIT_MESSAGE == "Please wait until all files have finished uploading."


def test_aggregation_summary_has_command_centre_layout():
    assert "flex-1" in AGGREGATION_SUMMARY_LAYOUT_CLASSES
    assert "aggregation-command-summary" in AGGREGATION_SUMMARY_LAYOUT_CLASSES
    assert "min-w-[520px]" in AGGREGATION_SUMMARY_LAYOUT_CLASSES


def test_resource_detail_headers_mirror_identity_and_actions_in_rtl():
    assert "items-center" in RECORD_DETAIL_HEADER_CLASSES
    assert "no-wrap" in RECORD_DETAIL_HEADER_CLASSES
    assert "flex-wrap" not in RECORD_DETAIL_HEADER_CLASSES
    assert "grow" in RECORD_DETAIL_TITLE_CLASSES
    assert "min-w-0" in RECORD_DETAIL_TITLE_CLASSES
    source = with_english_messages(inspect.getsource(index))
    assert 'ui.label(record["record_number"]).classes("text-xs text-primary font-semibold")' in source
    assert 'ui.label(record["title"]).classes("text-lg font-semibold break-words")' in source
    assert '"record-detail-identity-header w-full' in source
    assert '"record-detail-header-actions items-center gap-2"' in source
    assert '"aggregation-detail-identity-header w-full items-center gap-3"' in source
    assert '"aggregation-detail-header-actions items-center gap-2"' in source
    assert source.count('" icon-right=arrow_forward" if current_direction["value"] == "rtl"') >= 2
    assert 'ui.icon("description", color="primary", size="18px").classes("w-6")' in source


def test_child_aggregation_section_heading_stays_at_rtl_reading_start():
    source = with_english_messages(inspect.getsource(index))
    assert '"aggregation-child-section-heading w-full items-center px-5 pt-1"' in source
    rtl_rule = source.split(
        'html[dir="rtl"] .aggregation-child-section-heading {', 1
    )[1].split("}", 1)[0]
    assert "flex-direction: row;" in rtl_rule


def test_record_details_uses_the_approved_right_hand_control_column():
    source = with_english_messages(inspect.getsource(index))
    assert '"record-command-layout w-full"' in source
    assert '"record-command-controls"' in source
    assert '"detail-surface record-command-overview' in source
    assert 'ui.label("Hold controls").classes("aggregation-panel-heading w-full")' in source
    assert 'ui.label("Record actions").classes("aggregation-panel-heading w-full")' in source
    assert 'ui.label("Metadata and review").classes("record-action-group-label")' in source
    assert 'ui.label("Security, access and audit").classes("record-action-group-label")' in source
    assert 'ui.label("Lifecycle").classes("record-action-group-label")' in source
    assert '"Remove direct holds"' in source


def test_record_detail_long_values_are_aligned_and_bounded():
    source = with_english_messages(inspect.getsource(index))
    component_source = inspect.getsource(render_component_cards)
    assert ".detail-linked-entity .q-btn__content" in source
    assert "justify-content: flex-start; text-align: start; white-space: normal" in source
    assert '"detail-linked-entity self-start -m-2 p-2"' in source
    assert "overflow-wrap: anywhere" in source
    assert "width: 100%; min-width: 0; min-height: 2.5em" in source
    assert "-webkit-line-clamp: 2" in source
    assert ").tooltip(component_name)" in component_source
    assert '"component-card-actions w-full items-center justify-end' in component_source
    assert '"component-mime-type text-xs text-slate-500"' in component_source
    assert ").tooltip(mime_type)" in component_source


def test_identity_details_use_grouped_command_panels():
    source = with_english_messages(inspect.getsource(index))
    assert source.count('"identity-command-layout w-full"') == 3
    assert 'ui.label("Organization unit actions")' in source
    assert 'ui.label("Role actions")' in source
    assert 'ui.label("User actions")' in source
    assert 'ui.label("Manage and assignments")' in source
    assert 'ui.label("Account and assignments")' in source
    assert 'ui.label("Status and access")' in source
    assert '"detail-surface identity-command-metadata' in source
    assert '"detail-surface identity-command-actions' in source
    assert ".identity-command-metadata { grid-column: 1; grid-row: 1;" in source
    assert ".identity-command-actions { grid-column: 2; grid-row: 1;" in source
    assert 'assignment_results = ui.element("div").classes(' in source
    assert 'assignment_page_size = 5' in source
    assert 'def render_assignment_cards()' in source
    assert 'page_rows = rows[offset:offset + assignment_page_size]' in source
    assert 'assignment_previous = ui.button(' in source
    assert 'assignment_next = ui.button(' in source
    assert '"governance-list-facts user-role-assignment-facts"' in source
    assert '"governance-list-card user-role-assignment-card shadow-none"' in source
    assert 'lambda _, role_id=row["role_id"]: select_role_details(role_id)' in source
    assert 'def confirm_remove_role_assignment(row: dict[str, Any])' in source
    assert 'await api.delete_assignment(row["id"], row["version"])' in source
    assert '"click.stop",' in source
    assert 'session_results = ui.element("div").classes("login-session-card-grid w-full")' in source
    assert source.count('localized_lifecycle_value(value)') >= 3
    assert '"identity-detail-facts w-full gap-4"' in source


def test_user_details_localize_controlled_values_and_assignment_facts():
    source = inspect.getsource(index)
    assert '(person.get("localized") or {}).get("name") or person["name"]' in source
    assert 'roles = [item.get("counterpart") or {} for item in assignments]' in source
    assert 'title=localized_account_type(person["account_type"])' in source
    assert 'ui.badge(localized_account_type(person["account_type"])' in source
    assert 'localized_lifecycle_value(person["status"])' in source
    assert 'localized_lifecycle_value(row["role_status"])' in source
    assert 'localized_lifecycle_value(row["validity"])' in source
    assert 'render_message("governance_custody.field.valid_from")' in source
    assert 'render_message("governance_custody.field.valid_until")' in source
    assert 'render_message("common.value.no_expiry")' in source
    assert 'str(row["role_status"]).title()' not in source
    assert 'str(row["validity"]).title()' not in source


def test_saved_search_audiences_and_memberships_use_bounded_enriched_pages():
    source = inspect.getsource(index)
    assert 'def bind_remote_saved_audience_select(' in source
    assert 'if len(term) < 2:' in source
    assert 'api.saved_search_audience_options(\n                    audience_kind, query=term, limit=25, offset=offset,' in source
    assert 'await api.saved_search_audience_options()' not in source
    assert 'api.user_roles(\n                        entity["id"], limit=assignment_page["limit"]' in source
    assert 'counterpart = assignment.get("counterpart") or {}' in source
    assert 'counterpart_rows = await asyncio.gather' not in source


def test_saved_search_audience_controls_accept_typed_remote_queries():
    import ast

    tree = ast.parse(inspect.getsource(index))
    save_search = next(node for node in ast.walk(tree)
                       if isinstance(node, ast.AsyncFunctionDef) and node.name == "save_search")
    controls = [node for node in ast.walk(save_search)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "select"
                and any(keyword.arg == "multiple" and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True for keyword in node.keywords)]
    assert len(controls) == 2
    for control in controls:
        assert any(keyword.arg == "with_input" and isinstance(keyword.value, ast.Constant)
                   and keyword.value.value is True for keyword in control.keywords)


def test_org_unit_details_show_dedicated_holdings_summary_and_card_style_labels():
    source = with_english_messages(inspect.getsource(index))
    assert 'holdings_metrics = unit["holdings_metrics"]' in source
    assert 'ui.label("Holdings summary")' in source
    assert '"Visible holdings owned by this organization unit"' in source
    assert '"org-unit-holdings-grid"' in source
    assert "holdings_metrics['open_aggregation_count']" in source
    assert "holdings_metrics[f'{medium}_aggregation_count']" in source
    assert 'ui.label("|").classes(' in source
    assert "holdings_metrics[f'{medium}_record_count']" in source
    assert "holdings_metrics['vital_record_count']" in source
    assert "holdings_metrics['storage_size_in_bytes']" in source
    assert 'ui.label(label).classes("detail-field-label")' in source


def test_org_unit_parent_values_navigate_to_parent_details():
    source = with_english_messages(inspect.getsource(index))
    assert 'spec.key == "org-units"' in source
    assert 'and fact_index == 0' in source
    assert 'parent_id=row["parent_org_unit_id"]' in source
    assert 'select_organization_unit_details(parent_id)' in source
    assert 'value_kind == "parent" and (unit.get("parent") or {}).get("id")' in source
    assert 'unit["parent"]["id"]' in source
    assert '.tooltip("Open parent organization unit")' in source


def test_org_unit_details_show_clickable_vertical_lineage_before_holdings():
    source = with_english_messages(inspect.getsource(index))
    lineage_index = source.index('ui.label("Organizational lineage")')
    holdings_index = source.index('ui.label("Holdings summary")')
    assert lineage_index < holdings_index
    assert 'lineage = [*(unit.get("ancestors") or []), {' in source
    assert '"org-unit-lineage-row"' in source
    assert '"org-unit-lineage-node" + (" current" if is_current else "")' in source
    assert 'ancestor_id=lineage_unit["id"]' in source
    assert 'select_organization_unit_details(ancestor_id)' in source
    assert 'if not is_current:' in source
    assert 'ui.label(lineage_unit["code"]).classes(' in source
    assert 'ui.element("div").classes("org-unit-lineage-copy")' in source
    assert 'html[dir="rtl"] .org-unit-lineage-copy' in APP_SOURCE
    assert 'direction: rtl; flex-direction: row !important;' in APP_SOURCE
    assert 'ui.label("Current unit").classes(' not in source


def test_role_and_user_metadata_field_names_use_card_style_labels():
    source = with_english_messages(inspect.getsource(index))
    assert source.count('ui.label(label).classes("detail-field-label")') >= 2
    for label in ("Email address", "Account type", "Status", "External ID", "Created", "User ID"):
        assert f'ui.label("{label}").classes("detail-field-label")' in source


def test_role_details_relationship_values_navigate_to_details_pages():
    source = with_english_messages(inspect.getsource(index))
    assert 'role.get("org_unit_code"), role.get("org_unit_name")' in source
    assert 'role.get("supervisor_role_code"), role.get("supervisor_role_name")' in source
    assert 'select_organization_unit_details(' in source
    assert 'role["org_unit_id"]' in source
    assert 'select_role_details(role["supervisor_role_id"])' in source
    assert '.tooltip("Open organization unit")' in source
    assert '.tooltip("Open supervising role")' in source


def test_role_details_group_profile_privileges_with_names_and_codes():
    source = with_english_messages(inspect.getsource(index))
    assert 'profile_privileges = role.get("profile_privileges") or []' in source
    assert 'privileges_by_category: dict[str, list[dict[str, Any]]]' in source
    assert 'ui.label("Privileges inherited from profile")' in source
    assert '"role-privilege-groups w-full p-3"' in source
    assert 'ui.label(localized_privilege_name(privilege))' in source
    assert 'ui.label(privilege["code"])' in source
    assert 'localized_privilege_description(privilege)' in source
    assert 'localized_privilege_category(category)' in source


def test_user_details_use_fixed_blue_avatar_and_one_column_session_cards():
    source = with_english_messages(inspect.getsource(index))
    assert 'render_user_avatar(person, size="64px")' in source
    assert 'session_results = ui.element("div").classes("login-session-card-grid w-full")' in source
    assert 'def render_user_session_card(row: dict[str, Any])' in source
    assert 'ui.label(f"{browser} on {platform}")' in source
    assert ').props("outline")' in source


def test_governance_catalogues_use_one_column_cards():
    source = with_english_messages(inspect.getsource(index))
    assert 'if spec.key in {"security-levels", "profiles", "users", "roles", "org-units"}:' in source
    assert '"governance-card-list w-full px-5"' in source
    assert '"governance-list-card shadow-none"' in source
    assert 'width: 100%; min-width: 0;' in source
    assert '"security-levels": "shield"' in source
    assert '"profiles": "admin_panel_settings"' in source
    assert 'with ui.element("div").classes("governance-card-icon mt-1")' in source
    assert "border: 1px solid #add4ec" in source
    assert '("Roles assigned this level", str(row.get("roles_assigned_count", 0)))' in source
    assert "Clearance requirement" not in source
    assert 'spec.key == "security-levels" and fact_index == 3' in source
    assert 'ui.badge("Yes", color="warning")' in source
    assert '("Privileges", f"{row.get(\'privilege_count\', 0)} privileges")' in source
    assert 'with ui.element("div").classes("governance-card-list w-full")' in source
    assert '.tooltip("Hold history")' in source


def test_hold_held_items_use_one_column_cards():
    source = with_english_messages(inspect.getsource(index))
    assert 'ui.label("No held items match these filters.")' in source
    assert 'update_held_item_selection(row: dict[str, Any], selected: bool)' in source
    assert '.tooltip("Remove from this hold")' in source
    assert 'update_candidate_selection(row: dict[str, Any], selected: bool)' in source
    assert 'picker["selected"][row["selection_key"]] = dict(row)' in source
    assert 'session_results = ui.element("div").classes("login-session-card-grid w-full")' in source
    assert 'user_agent = row.get("user_agent") or "Unknown client"' in source
    assert '.tooltip(user_agent)' in source


def test_scalar_display_columns_are_not_rendered_as_relationship_links():
    assert RELATIONSHIP_DISPLAY_FIELDS == {
        "aggregation_display",
        "org_unit_display",
        "parent_org_unit_display",
        "profile_display",
        "scheme_display",
    }
    scalar_fields = {
        "medium_display", "vital_display", "review_display", "location_display",
    }
    assert scalar_fields.isdisjoint(RELATIONSHIP_DISPLAY_FIELDS)
    assert "if key not in RELATIONSHIP_DISPLAY_FIELDS:" in APP_SOURCE


def test_record_and_aggregation_scalar_columns_remain_plain_text():
    for resource in ("records", "aggregations"):
        displayed_fields = {
            key for key, _ in ENTITIES[resource].columns if key.endswith("_display")
        }
        assert {
            "medium_display", "vital_display", "review_display", "location_display",
        } <= displayed_fields
        assert (
            displayed_fields - {"aggregation_display"}
        ).isdisjoint(RELATIONSHIP_DISPLAY_FIELDS)


def test_governed_collection_rows_open_details_instead_of_direct_editors():
    collection_actions = APP_SOURCE[
        APP_SOURCE.index('if spec.key in {"records", "aggregations"}:'):
        APP_SOURCE.index('elif spec.key in {"privileges", "permissions"}:')
    ]
    assert "$parent.$emit(\\'edit\\', props.row)" not in collection_actions
    assert 'icon="open_in_new"' in APP_SOURCE
    assert "$parent.$emit(\\'open_record\\', props.row)" in APP_SOURCE
    assert 'table.on("open_record", lambda event: show_record_details(event.args))' in APP_SOURCE


def test_governed_metadata_editor_fails_closed_without_modify_capability():
    editor = APP_SOURCE[
        APP_SOURCE.index("async def open_editor("):
        APP_SOURCE.index("async def show_memberships(")
    ]
    capability_check = editor.index(
        'editor_capabilities = await api.resource_capabilities('
    )
    denial_check = editor.index(
        'if not editor_capabilities.get("modify_metadata"):'
    )
    dialog_open = editor.index("dialog.open()")
    assert capability_check < denial_check < dialog_open
    assert "Your effective roles do not allow editing this" in editor


def test_entity_translation_editor_loads_selected_language_automatically():
    editor = APP_SOURCE[
        APP_SOURCE.index("async def open_editor("):
        APP_SOURCE.index("async def show_memberships(")
    ]
    assert 'language_control.on_value_change(' in editor
    assert 'background_tasks.create(load_entity_translation())' in editor
    assert 'if language_control.value:' in editor
    assert 'await load_entity_translation()' in editor
    assert 'icon="refresh"' in editor
    assert 'icon="download"' not in editor
    assert '''multilingual_fields = {
                    "classification-schemes": ("title", "description"),
                    "classifications": ("title", "description"),
                    "users": ("name", "description"),
                    "roles": ("name", "description"),
                    "org-units": ("name", "description"),
                    "security-levels": ("name", "description"),
                    "profiles": ("name", "description"),
                }''' in editor
    multilingual_configuration = editor[
        editor.index("multilingual_fields = {"):
        editor.index("if not creating and spec.key in multilingual_fields:")
    ]
    assert '"aggregations":' not in multilingual_configuration
    assert '"records":' not in multilingual_configuration


def test_entity_translations_are_saved_by_the_main_entity_action_for_all_seven_entities():
    editor = APP_SOURCE[
        APP_SOURCE.index("async def open_editor("):
        APP_SOURCE.index("async def show_memberships(")
    ]
    for entity in (
        "classification-schemes", "classifications", "users", "roles",
        "org-units", "security-levels", "profiles",
    ):
        assert f'"{entity}":' in editor
    assert "def pending_entity_translation()" in editor
    assert "prepare_entity_translation_update()" in editor
    assert "saved_translation = await api.update_entity_translation(" in editor
    assert 'saved["version"], reason' in editor
    assert 'icon="save", on_click=save_entity_translation' not in editor


def test_profile_uses_one_reason_for_canonical_and_translation_changes():
    editor = APP_SOURCE[
        APP_SOURCE.index("async def open_editor("):
        APP_SOURCE.index("async def show_memberships(")
    ]
    assert 'None if spec.key == "profiles" else ui.input(' in editor
    assert 'profile_change_reason\n                                if spec.key == "profiles" else translation_reason' in editor
    assert 'if not creating and spec.key == "profiles":' in editor
    assert 'if not creating and spec.key == "profiles" and not translation_only:' not in editor


def test_builtin_role_editor_is_translation_only():
    editor = APP_SOURCE[
        APP_SOURCE.index("async def open_editor("):
        APP_SOURCE.index("async def show_memberships(")
    ]
    assert 'translation_only = bool(' in editor
    assert '(spec.key == "roles" and row.get("is_system"))' in editor
    assert 'spec.key == "profiles"' in editor
    assert 'row.get("code") == "TEXT_INDEXER_SERVICE"' in editor
    assert 'if translation_only:\n                        controls[field.name].disable()' in editor
    translation_only_save = editor[
        editor.index("if translation_only:", editor.index("async def save()")):
        editor.index("payload = form_payload", editor.index("async def save()"))
    ]
    assert "api.update_entity_translation(" in translation_only_save
    assert "api.update(" not in translation_only_save
    assert 'if not isinstance(row.get("translations"), dict):' in translation_only_save
    assert 'row["translations"] = {}' in translation_only_save
    assert 'row["translations"][language] = dict(values)' in translation_only_save


def test_detail_pages_use_light_blue_metadata_and_retention_visual_system():
    source = with_english_messages(inspect.getsource(index))
    assert 'primary="#268bd2"' in source
    assert ".detail-field-label" in source
    assert ".retention-card" in source
    assert "render_retention_stages(" in source
    assert 'count=rule["current_period_years"]' in TIMELINE_SOURCE
    assert 'disposition_label(rule["final_disposition"])' in TIMELINE_SOURCE
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr))' in source
    assert 'ui.label(str(len(children))).classes("text-2xl font-bold text-primary")' not in source
    assert '"retention-card aggregation-retention-compact shadow-none p-4 gap-3"' in source


def test_application_shell_is_flat_and_uses_one_background():
    source = with_english_messages(inspect.getsource(index))
    assert "with ui.header().classes" in source
    assert "ui.header(elevated=True)" not in source
    assert "background: var(--erms-bg); color: var(--erms-ink);" in source
    assert ".erms-content .q-card { box-shadow: none !important; }" in source
    assert 'ui.image("/static/brand/wathiq-mark.svg?v=2")' in source
    assert 'ui.label("wathiq").classes("erms-brand-name")' in source
    assert 'ui.label("ERMS")' not in source
    assert 'href="/static/fonts/righteous/righteous.css?v=1"' in source
    assert "family=Righteous" not in source
    assert "font-family: Righteous, Inter" in source
    assert 'href="/static/fonts/changa/changa.css?v=1"' in source
    assert "family=Changa" not in source
    assert 'font-family: Changa, Tahoma, Arial, "Segoe UI", sans-serif' in source
    assert 'html[dir="rtl"] .erms-brand {' in source
    assert 'direction: rtl; flex-direction: row !important;' in source
    assert 'html[dir="rtl"] .erms-brand-name,' in source
    assert 'html[dir="rtl"] .erms-page-title-row {' in source
    assert '"erms-page-title-row items-center no-wrap gap-2"' in source
    assert "Noto Sans Arabic" not in source
    assert "letter-spacing: .035em" in source
    assert ".erms-page-table" in source
    assert ".erms-page-table .q-table thead tr { background: #eef7fd; }" in source
    assert ".erms-page-table .q-table tbody td" in source
    assert '"erms-page-table' in source
    assert ".login-sessions-table .q-table th" in source
    assert "white-space: nowrap" in source
    assert 'results = ui.element("div").classes("login-session-card-grid w-full")' in source
    assert "grid-template-columns: minmax(0, 1fr); gap: 10px;" in source
    assert '.tooltip("Force sign-out this session")' in source
    assert '.tooltip("Force sign-out all sessions for this user")' in source
    assert 'icon="logout", on_click=' in source
    assert 'icon="person_off", on_click=' in source
    assert '{20: "20", 50: "50", 100: "100"}' in source
    assert 'page_range.text = f"Showing {start}–{end} of {page_state[\'total\']} sessions"' in source
    assert 'await api.login_sessions_page(' in source
    assert ".login-session-action-button" in source
    assert "<q-btn-dropdown" not in source
    assert 'ui.row().classes("w-full items-center no-wrap gap-4", remove="row")' in source
    assert 'ui.row().classes("items-center no-wrap gap-2 flex-none")' in source
    assert 'ui.label("Search results").classes("text-lg font-semibold")' in source
    assert '"Filter displayed results"' in source
    assert 'table.bind_filter_from(result_filter, "value")' in source
    assert 'sortable_relationships = {"parent_org_unit_display", "org_unit_display", "profile_display"}' in source
    assert 'not key.endswith("_display") or key in sortable_relationships' in source


def test_aggregation_records_use_compact_authorized_expandable_rows():
    source = with_english_messages(inspect.getsource(index))
    assert 'load_record_result_context(' in source
    assert 'record["_components"] = components if record_capabilities.get("list_components") else []' in source
    assert 'record["_can_preview"] = bool(' in source
    assert 'record_capabilities.get("view_component")' in source
    assert 'render_compact_resource_result(' in source
    assert 'components=record.get("_components", [])' in source
    assert 'can_expand_components=bool(record.get("_can_expand_components"))' in source
    assert '"Search code, name, or parent unit"' in source
    assert '"Search code, name, or organization unit"' in source
    assert '"Search name or email"' in source
    assert '"All account types"' in source
    assert '"w-full items-center gap-3 px-5 pt-2 pb-1 mb-2"' in source
    assert ':rows-per-page-options="[10,25,50,100]"' in source
    assert '"Filter records"' in source
    assert 'record_page_result = await api.search_request("records", {' in source
    assert '"limit": 10, "offset": (record_page_number - 1) * 10' in source
    assert 'contained_record_page = ui.pagination(' in source
    assert 'state["aggregation_child_return"] = {' in source
    assert '"expanded_records": sorted(expanded_child_records)' in source
    assert 'restore_compact_result_anchor(child_return.get("anchor"))' in source


def test_brand_assets_are_exposed_through_the_frontend_static_route():
    module_source = inspect.getsource(inspect.getmodule(index))
    assert 'app.add_static_files("/static/brand"' in module_source
    assert 'app.add_static_files("/static/fonts"' in module_source
    assert 'title="wathiq"' in module_source
    assert 'favicon=Path(__file__).with_name("static") / "brand" / "wathiq-mark.svg"' in module_source


def test_changa_is_bundled_for_local_browser_delivery():
    font_dir = Path(__file__).parents[1] / "static" / "fonts" / "changa"
    stylesheet = (font_dir / "changa.css").read_text(encoding="utf-8")

    assert "fonts.googleapis.com" not in stylesheet
    assert "fonts.gstatic.com" not in stylesheet
    assert 'font-weight: 400 700;' in stylesheet
    for filename in (
        "changa-arabic.woff2",
        "changa-latin-ext.woff2",
        "changa-latin.woff2",
    ):
        assert f'url("./{filename}")' in stylesheet
        assert (font_dir / filename).read_bytes().startswith(b"wOF2")
    assert "SIL OPEN FONT LICENSE Version 1.1" in (
        font_dir / "OFL.txt"
    ).read_text(encoding="utf-8")


def test_righteous_is_bundled_for_local_brand_delivery():
    font_dir = Path(__file__).parents[1] / "static" / "fonts" / "righteous"
    stylesheet = (font_dir / "righteous.css").read_text(encoding="utf-8")

    assert "fonts.googleapis.com" not in stylesheet
    assert "fonts.gstatic.com" not in stylesheet
    assert 'font-family: "Righteous";' in stylesheet
    assert "font-weight: 400;" in stylesheet
    for filename in (
        "righteous-latin-ext.woff2",
        "righteous-latin.woff2",
    ):
        assert f'url("./{filename}")' in stylesheet
        assert (font_dir / filename).read_bytes().startswith(b"wOF2")
    assert "SIL OPEN FONT LICENSE Version 1.1" in (
        font_dir / "OFL.txt"
    ).read_text(encoding="utf-8")


def test_record_detail_aggregation_navigation_uses_click_handler_not_route_link():
    source = with_english_messages(inspect.getsource(index))
    assert "on_click=open_containing_aggregation" in source
    assert 'ui.label(value.get("name") or "—").classes(' in source
    assert 'ui.label(value["code"]).classes(' in source
    assert '"detail-linked-entity-title"' in source
    assert '"detail-linked-entity-identifier"' in source


def test_aggregation_detail_classification_is_split_and_navigable():
    source = with_english_messages(inspect.getsource(index))
    assert "async def open_parent_classification()" in source
    assert 'initial_scheme_id=classification["classification_scheme_id"]' in source
    assert 'initial_classification_id=classification["id"]' in source
    assert 'on_click=open_parent_classification' in source
    assert 'ui.label(value.get("title") or "—").classes(' in source
    assert 'ui.label(value["code"]).classes(' in source
    assert '"Parent classification"' in source


def test_child_aggregation_shows_clickable_parent_instead_of_inherited_classification():
    source = with_english_messages(inspect.getsource(index))
    assert "async def open_parent_aggregation()" in source
    assert 'governing_relationship = (' in source
    assert '"parent_aggregation", "Parent aggregation"' in source
    assert 'parent_aggregation or "Parent aggregation restricted"' in source
    assert 'elif field_key == "parent_aggregation" and isinstance(value, dict):' in source
    assert "on_click=open_parent_aggregation" in source
    assert 'ui.label(value.get("title") or "—").classes(' in source
    assert 'ui.label(value["aggregation_number"]).classes(' in source


def test_aggregation_detail_relationship_context_does_not_use_removed_global_cache():
    source = with_english_messages(inspect.getsource(index))
    assert "aggregation_context_by_id = {" in source
    assert 'aggregation_context_by_id.get(current.get("parent_aggregation_id"))' in source
    assert "aggregation_context_by_id.get(source_id)" in source
    assert "aggregation_context_by_id.get(governing_root_id)" in source


def test_detail_page_editors_resolve_api_entity_resources_explicitly():
    source = with_english_messages(inspect.getsource(index))
    assert 'record, on_saved=refresh_record_view, resource_key="records"' in source
    assert 'current, on_saved=open_aggregation,\n                                        resource_key="aggregations"' in source
    assert '"aggregation-details": "aggregations"' in source
    assert '"record-details": "records"' in source


def test_navigation_trail_collapses_only_consecutive_duplicates_and_is_bounded():
    trail = []
    for index in range(NAVIGATION_TRAIL_LIMIT + 3):
        trail = append_navigation_entry(trail, {
            "page": "record-details", "entity_id": index, "label": f"Record {index}",
        })
    assert len(trail) == NAVIGATION_TRAIL_LIMIT
    assert trail[0]["entity_id"] == 3
    unchanged_length = append_navigation_entry(trail, {
        "page": "record-details", "entity_id": trail[-1]["entity_id"],
        "label": "Updated label",
    })
    assert len(unchanged_length) == NAVIGATION_TRAIL_LIMIT
    assert unchanged_length[-1]["label"] == "Updated label"


def test_navigation_visible_entries_retain_first_and_recent_pages():
    visible, hidden = visible_navigation_indices(9)
    assert len(visible) == NAVIGATION_VISIBLE_LIMIT
    assert visible == [0, 5, 6, 7, 8]
    assert hidden == [1, 2, 3, 4]


def test_navigation_drawer_does_not_load_or_render_entity_counts():
    source = with_english_messages(inspect.getsource(index))
    assert "navigation_badges" not in source
    assert "refresh_navigation_counts" not in source
    assert "active_count" not in source
    assert "page_state.update(total=int(page.get(\"total\", 0)), active=int(page.get(\"active\", 0)))" in source


def test_navigation_drawer_collapses_to_clickable_icon_rail():
    source = with_english_messages(inspect.getsource(index))
    assert '"width=300 mini-width=64 show-if-above"' in source
    assert '"width=300 mini-width=64 show-if-above bordered"' not in source
    assert '"Browse", "lan", navigation_key="organization-browser"' in source
    assert "erms-nav-link" in source
    assert "white-space: nowrap" in source
    assert ".erms-nav-link:hover" in source
    assert ".erms-nav-heading" in source
    assert ".erms-nav-link--active" in source
    assert "background: #ffffff; color: #172033;" in source
    assert "--erms-bg: #ffffff" in source
    assert "color: #1f2937 !important" in source
    assert 'font-family: "Material Symbols Outlined" !important' in source
    assert 'font-variation-settings: "FILL" 0' in source
    assert '"wght" 300' in source
    assert "background: #fff4d7 !important; color: #174b72 !important;" in source
    assert "def set_active_drawer_link(page: str)" in source
    assert 'button.props(add="aria-current=page")' in source


def test_rtl_navigation_mirrors_icon_label_alignment_and_active_edge():
    source = inspect.getsource(index)
    assert 'html[dir="rtl"] .erms-nav-link .q-btn__content {' in source
    assert "direction: rtl; flex-direction: row; justify-content: flex-start;" in source
    assert 'html[dir="rtl"] .erms-nav-link .q-btn__content .block {' in source
    assert "flex: 1 1 auto; text-align: right;" in source
    assert 'html[dir="rtl"] .erms-nav-heading { text-align: right; }' in source
    assert "left: auto !important; right: -8px;" in source
    assert 'html[dir="rtl"] .erms-drawer--collapsed .erms-nav-link--active::before {' in source


def test_breadcrumbs_resolve_static_labels_in_the_active_language():
    source = inspect.getsource(index)
    assert "def localized_breadcrumb_label(entry: dict[str, Any])" in source
    assert '"dashboard": "navigation.item.dashboard"' in source
    assert '"full-text-search": "webui.run_global_search.text.search_results_ecc13a7a"' in source
    assert '"users": "navigation.item.users"' in source
    assert '"roles": "navigation.item.roles"' in source
    assert '"org-units": "navigation.item.org_units"' in source
    assert '"translations": "navigation.item.translations"' in source
    assert "message_key = breadcrumb_message_keys.get(page)" in source
    assert '"label_key": None if dynamic_label else breadcrumb_message_keys.get(page)' in source
    assert "label = localized_breadcrumb_label(entry)" in source
    assert "label if label != entry.get(\"label\")" in source
    assert "erms-breadcrumb-row" in source
    assert 'html[dir="rtl"] .erms-breadcrumb-row {' in source


def test_translation_administration_supports_governed_artifact_round_trips():
    source = inspect.getsource(index)
    assert 'icon="download"' in source
    assert 'icon="upload_file"' in source
    assert "async def export_artifact_dialog()" in source
    assert "async def import_artifact_dialog()" in source
    assert "preview_localization_export" in source
    assert "export_localization_artifact" in source
    assert "preview_localization_import" in source
    assert "import_localization_artifact" in source
    assert 'ui.download(content, result["filename"], "application/json")' in source
    assert "localization.artifact.import.guidance" in source
    assert "def focus_export_problem(message_key: str)" in source
    assert 'for message_key in preview["missing_keys"]' in source
    assert 'for problem in preview["invalid_keys"]' in source
    assert 'entry["message_key"] == message_key' in source
    assert "after_persist=export_artifact_dialog" in source
    assert "def open_bulk_review_from_export()" in source
    assert 'target_language = administration_language["value"]' in source
    assert "await bulk_review_publish_dialog(language_tag=target_language)" in source
    assert "background_tasks.create(\n                        bulk_review_publish_dialog" not in source
    assert "export_language = ui.select(" not in source
    assert "language_select = ui.select(" not in source
    assert "preview_localization_export(\n                            target_language" in source
    assert "export_localization_artifact(\n                            target_language" in source
    assert "artifact_language = str(artifact.get(\"language_tag\")" in source
    assert "preview_localization_import(artifact_language, artifact)" in source
    assert 'state["translation_language"] = selected["language_tag"]' in source
    assert "await select_translation_administration()" in source


def test_translation_administration_preserves_expanded_context_and_scroll_after_edit():
    source = inspect.getsource(index)
    assert 'expanded_contexts = set(state.get("translation_expanded_contexts") or [])' in source
    assert 'def set_translation_context_expanded(context_group: str, expanded: bool)' in source
    assert 'state["translation_expanded_contexts"] = sorted(expanded_contexts)' in source
    assert 'value=filters_active or group in expanded_contexts' in source
    assert 'on_value_change=lambda event, context=group: set_translation_context_expanded(' in source
    assert 'async def load_messages(reset: bool=False, restore_scroll: float | None = None)' in source
    assert 'await load_messages(restore_scroll=scroll_top)' in source
    assert "window.scrollTo({{top:" in source


def test_translation_administration_reveals_filtered_matches_and_ignores_stale_requests():
    source = inspect.getsource(index)
    translation_source = source[
        source.index("async def select_translation_administration("):
        source.index("async def guarded_page_navigation(")
    ]
    advanced_condition_source = source[
        source.index("def render_condition("):
        source.index("def render_group(")
    ]
    assert 'message_load = {"sequence": 0}' in source
    assert 'request_sequence = message_load["sequence"]' in source
    assert 'if request_sequence != message_load["sequence"]:' in source
    assert 'filters_active = bool(' in source
    assert 'value=filters_active or group in expanded_contexts' in source
    assert 'translation-filter-row w-full items-end gap-2 flex-wrap' in translation_source
    assert 'translation-filter-row' not in advanced_condition_source
    assert 'html[dir="rtl"] .translation-filter-row {' in source
    assert 'direction: rtl !important;' in source


def test_navigation_links_scroll_independently_when_the_drawer_is_taller_than_the_viewport():
    source = with_english_messages(inspect.getsource(index))
    assert 'drawer_factory = ui.right_drawer if initial_direction == "rtl" else ui.left_drawer' in source
    assert 'drawer.props(remove="side")' not in source
    assert 'ui.scroll_area().classes("erms-nav-scroll w-full h-full")' in source
    assert 'ui.column().classes("w-full gap-0 no-wrap")' in source
    assert ".erms-nav-scroll .q-scrollarea__content" in source
    assert ".erms-nav-scroll .q-scrollarea__container" in source


def test_empty_navigation_sections_are_hidden_with_their_links():
    source = with_english_messages(inspect.getsource(index))
    assert "drawer_sections: list[tuple[Any, tuple[str, ...]]]" in source
    assert "bool(visible_links.intersection(section_keys))" in source
    assert "refresh_drawer_visibility(privileges)" in source
    assert "not drawer_collapsed" in source


def test_governance_custody_page_explains_qualification_and_empty_configuration():
    source = with_english_messages(inspect.getsource(index))
    assert "Checks that someone can always manage and recover access to protected records" in source
    assert "At least one active person must be able to manage information" in source
    assert "Governance role enabled" in source
    assert "Highest clearance held" in source
    assert "Required profile privileges" in source
    assert "Current role assignment" in source
    assert "No information-governance roles are configured" in source
    assert "governance-overview-grid" in source
    assert "governance-metrics-row" in source
    assert "governance-empty-state" in source
    assert "Universal custodians (" in source
    assert "governance-custody-assignment-card" in source
    assert 'custodian_host = ui.element("div").classes("governance-card-list w-full")' in source
    assert 'attention_host = ui.element("div").classes("governance-card-list w-full")' in source
    assert 'def render_custodian_cards()' in source
    assert 'def render_attention_cards()' in source
    assert 'render_user_avatar({' in source
    assert '.tooltip("Open user")' in source
    assert '.tooltip("Open role")' in source
    assert '"Open roles", icon="open_in_new"' not in source
    assert 'icon="person",\n                                        on_click=lambda _, item=row: select_user_details(' in source
    assert 'icon="badge",\n                                on_click=lambda _, identifier=role["id"]: select_role_details(identifier)' in source
    assert "valid_from_display" in source
    assert "valid_until_display" in source
    assert "qualifies_for_universal_custody" in source
    assert "effective_for_universal_custody" in source
    assert "Assignments needing attention" in source
    assert "All governance-role assignments" not in source
    assert '"Current assignments"' in source
    assert "Assignments whose validity dates include the present time." in source
    assert "account, role, and organization hierarchy are active" in source
    assert "highest security clearance" in source
    assert 'page_rows = custodian_rows[offset:offset + 5]' in source
    assert 'page_rows = assignment_rows[offset:offset + 5]' in source
    assert "def set_page_title_icon(page: str)" in source
    assert 'page_title_icon = ui.icon("dashboard")' in source
    assert "page_title_icon = ui.icon()" not in source
    assert 'ui.label("Previous sign-in")' in source


def test_login_session_statuses_and_security_operations_use_compact_cards():
    source = with_english_messages(inspect.getsource(index))
    assert 'localized_lifecycle_value(row.get("status"))' in source
    assert '"expired": "grey-7",' in source
    assert ').props("outline")' in source
    assert 'security_event_host = ui.element("div").classes(' in source
    assert 'def render_security_event_cards()' in source
    assert 'page_rows = event_rows[offset:offset + 10]' in source
    assert 'ui.label("No recent security events in this period.")' in source
    assert 'f"Technical code: {row[\'decision_code\']}"' in source
    assert '"Open role", icon="open_in_new"' not in source
    assert 'async def open_security_event_target(row: dict[str, Any])' in source
    assert '"name": row.get("actor_name")' in source
    assert 'render_user_avatar({' in source
    assert 'select_user_details(user_id)' in source
    assert 'target_supported = (' in source
    assert 'open_security_event_target(item)' in source
    assert 'current_user_last_login = ui.label("First sign-in")' in source
    assert 'current_user_avatar_initials = ui.label("?")' in source
    assert 'user_menu.on("show", refresh_user_profile)' in source
    assert 'my_sessions_menu' not in source
    assert '"dashboard": "dashboard"' in source
    assert '"aggregations": "folder"' in source
    assert '"records": "description"' in source
    assert '"classification-workspace": "account_tree"' in source
    assert '"org-units": "corporate_fare"' in source
    assert '"roles": "badge"' in source
    assert '"users": "group"' in source
    assert '"organization-browser": "lan"' in source
    assert '"audit-trail": "manage_history"' in source
    assert '"login-sessions": "devices"' in source
    assert '"w-full px-5 pb-5 pt-0 gap-4"' in source
    assert "background: #f4f6f8; color: var(--erms-ink);" in source
    assert "min-height: 54px; padding: 0 18px;" in source
    assert ".erms-brand-mark { width: 28px; height: 33px;" in source
    assert 'with ui.footer().classes("erms-footer items-center")' in source
    assert 'f"Database: {database_display_name(initial_language)}"' in source
    assert ".erms-footer-credit" in source
    assert ".erms-footer-database" in source
    assert 'replace="text-positive text-lg"' in source
    assert "#popup { display: none !important; }" in source
    assert 'ui.label("wathiq").classes("wathiq-login-word")' in source
    assert 'login_submit = ui.button(\n                        "Continue to wathiq"' in source
    assert 'drawer.hide()' in source
    assert 'drawer.show()' in source
    assert "Sign in to ERMS" not in source
    assert 'page_title_icon.set_visibility(False)' in source
    assert ".erms-dashboard-card .erms-shared-control" in source
    assert 'content_card.classes(add="erms-dashboard-card")' in source
    assert 'content_card.classes(remove="erms-dashboard-card")' in source
    assert 'drawer.props(add="mini")' in source
    assert 'drawer.props(remove="mini")' in source
    assert 'drawer.classes(add="erms-drawer--collapsed p-0")' in source
    assert 'icon="chevron_right" if initial_direction == "rtl" else "chevron_left"' in source
    assert 'icon=chevron_right' in source
    assert 'icon="menu"' not in source
    assert "erms-drawer-toggle" in source
    assert "erms-profile-action" in source
    assert "erms-profile-menu" in source
    assert "erms-profile-identity-row" in source
    assert "erms-profile-role-row" in source
    assert "erms-profile-role-copy" in source
    assert 'html[dir="rtl"] .erms-profile-action .q-btn__content' in source
    assert 'html[dir="rtl"] .erms-profile-diagnostics .q-toggle' in source
    assert "direction: rtl; flex-direction: row; justify-content: flex-start;" in source
    assert "erms-preferences-dialog" in source
    assert "erms-preference-select" in source
    assert 'html[dir="rtl"] .erms-preferences-dialog .erms-preference-select .q-field__native' in source
    assert "text-align: right !important;" in source
    assert 'html[dir="rtl"] .compact-result-row' in source
    assert 'html[dir="rtl"] .compact-result-title' in source
    assert 'html[dir="rtl"] .compact-result-actions' in source
    assert "direction: rtl; flex-direction: row !important;" in source
    assert 'ui.button("Change password", icon="key")' in source
    assert 'with ui.column().classes("erms-profile-actions w-full")' in source
    assert "min-height: 38px !important; height: 38px !important;" in source
    assert "gap: 0 !important" in source
    assert 'button.text = ""' in source
    assert 'button.classes(add="justify-center px-0"' in source
    assert "ui.tooltip(label)" in source


def test_forced_password_change_precedes_authenticated_data_loading():
    source = with_english_messages(inspect.getsource(index))
    login_flow = source[
        source.index("async def submit_login()"):
        source.index('login_submit.on("click", submit_login)')
    ]
    assert "await reload_favourites()" not in login_flow
    forced_change_gate = login_flow.index('if principal["must_change_password"]:')
    assert forced_change_gate < login_flow.index(
        "await prepare_authenticated_workspace(principal)"
    )
    assert forced_change_gate < login_flow.index("await select_dashboard()")
    assert "await load_localization_context()" not in login_flow
    assert "await refresh_hold_navigation()" not in login_flow

    restored_flow = source[
        source.index("async def initialize_authenticated_ui()"):
        source.index("ui.timer(0.05, initialize_authenticated_ui")
    ]
    restored_gate = restored_flow.index('if principal["must_change_password"]:')
    assert restored_gate < restored_flow.index(
        "await prepare_authenticated_workspace(principal)"
    )

    workspace_setup = source[
        source.index("async def prepare_authenticated_workspace("):
        source.index("async def load_login_animation()")
    ]
    assert "await load_localization_context()" in workspace_setup
    assert "await refresh_hold_navigation()" in workspace_setup

    password_flow = source[
        source.index("async def show_change_password()"):
        source.index("async def sign_out()")
    ]
    password_changed = password_flow.index(
        'await api.change_password(current.value or "", new.value or "")'
    )
    principal_refreshed = password_flow.index("principal = await api.me()")
    workspace_prepared = password_flow.index(
        "await prepare_authenticated_workspace(principal)"
    )
    dashboard_selected = password_flow.index("await select_dashboard()")
    assert password_changed < principal_refreshed < workspace_prepared < dashboard_selected
    assert "Your temporary password must be replaced before you can continue." in source
    assert '"Set new password" if forced_change else "Change password"' in source
    assert '"Back to sign in", icon="arrow_back"' in source
    assert "dialog.close()\n                await sign_out()" in source


def test_network_animation_loads_for_login_and_restored_sessions():
    source = with_english_messages(inspect.getsource(index))
    animation_loader = source[
        source.index("async def load_login_animation()"):
        source.index("async def initialize_authenticated_ui()")
    ]
    assert "page_client.run_javascript(" in animation_loader
    assert "ui.run_javascript(" not in animation_loader

    initialization = source[
        source.index("async def initialize_authenticated_ui()"):
        source.index("ui.timer(0.05, initialize_authenticated_ui")
    ]
    assert initialization.index(
        "background_tasks.create(load_login_animation())"
    ) < initialization.index('token = app.storage.user.get("session_token")')


def test_structured_api_errors_prefer_the_accessible_message():
    error = ApiError(422, {
        "code": "aggregation_dates_out_of_order",
        "message": "The aggregation's closing date cannot be earlier than its opening date.",
        "technical_detail": 'new row violates check constraint "aggregations_dates_in_order"',
    })
    assert error_message(error) == (
        "Review the highlighted information and correct any errors."
    )
    assert error_message(ApiError(
        422, "X-Change-Reason is required when lowering a security level",
    )) == "Please explain why the security level is being lowered, then try again."


def test_last_custodian_block_uses_a_persistent_explanatory_dialog():
    source = with_english_messages(inspect.getsource(show_api_error))
    assert 'detail_code != "last_governance_custodian"' in source
    assert 'ui.dialog().props("persistent")' in source
    assert 'ui.button("I understand"' in source
    assert LAST_CUSTODIAN_TITLE == "This change can’t be made yet"
    assert "only active person" in LAST_CUSTODIAN_MESSAGE
    assert "No changes were saved" in LAST_CUSTODIAN_MESSAGE
    assert "Assign another active person" in LAST_CUSTODIAN_MESSAGE


def test_lowering_role_clearance_requires_the_audit_reason():
    levels = [
        {"id": 1, "level_number": 10},
        {"id": 2, "level_number": 20},
    ]
    current = {"security_level_id": 2, "profile_id": 4,
               "is_information_governance": True}
    assert role_change_requires_reason(
        current, {"security_level_id": 1}, levels,
    )
    assert not role_change_requires_reason(
        current, {"security_level_id": 2}, levels,
    )
    assert role_change_requires_reason(
        current, {"profile_id": 5}, levels,
    )


def test_permanent_deletion_uses_stable_identity_and_preserves_blocker_reports():
    assert deletion_identity({
        "id": 7, "name": "Alex Example", "email": "alex@example.test",
    }) == "Alex Example — alex@example.test"
    assert deletion_identity({
        "id": 8, "name": "Records Team", "code": "RECORDS",
    }) == "Records Team — RECORDS"
    report = {"code": "deletion_blocked", "blockers": [{"code": "self_deletion"}]}
    assert deletion_blocked_report(ApiError(409, report)) == report
    assert deletion_blocked_report(ApiError(409, "another conflict")) is None


def test_identity_detail_actions_are_explicitly_permanent():
    source = with_english_messages(inspect.getsource(index))
    assert source.count('"Permanently delete", icon="delete_forever"') >= 3
    assert "if deletion_blocked_report(error) is not None:" in source
    assert "await confirm_identity_deletion(" in source


def test_aggregation_browser_load_more_preserves_the_previous_last_child_anchor():
    source = with_english_messages(inspect.getsource(index))
    assert 'browse_item_dom_id(current["items"][-1])' in source
    assert "render_tree_preserving_scroll(anchor_id=append_anchor_id)" in source
    assert "anchor.getBoundingClientRect().top" in source
    assert '.props(f"id={browse_item_dom_id(item)}")' in source


def test_organization_browser_selectors_have_persistent_confirmation_action():
    source = with_english_messages(inspect.getsource(index))
    assert '"Clear selection"' not in source
    assert 'f"Select {selection_entity_label}"' in source
    assert "selection_confirm_button.disable()" in source
    assert "selection_confirm_button.enable()" in source
    assert "apply_relationship_selection(" in source
    assert '"dblclick", lambda _, item=node: confirm_node_selection(item)' in source
    assert '"dblclick", lambda _, action=confirm_search_result: action()' in source
    assert "await confirm_browser_selection()" in source
    assert "organization-browser-selected" in source
    assert "organization_node_dom_id(node)" in source
    assert "persist(); render_tree(); await render_summary(node)" not in source


def test_organization_browser_does_not_shadow_the_page_guidance_control():
    source = with_english_messages(inspect.getsource(index))
    assert "summary_guidance = (" in source
    assert "ui.label(summary_guidance)" in source
    assert "                guidance = (\n" not in source


def test_organization_browser_hides_detail_links_without_destination_privilege():
    source = with_english_messages(inspect.getsource(index))
    assert 'can_open_organization_detail(node["type"], privileges)' in source
    assert '(auth_state.get("principal") or {}).get("global_privileges", [])' in source


def test_organization_browser_localizes_statuses_summary_and_rtl_disclosures():
    source = inspect.getsource(index)
    assert "organization-browser-node-row" in source
    assert "organization-browser-expander" in source
    assert "organization-browser-disclosure" in source
    assert 'localized_lifecycle_value(node.get("status") or "active")' in source
    assert '"current": render_message("webui.show_organization_structure.select.current_8d79efc1")' in source
    assert 'display_value = localized_lifecycle_value(value)' in source
    assert 'display_value = localized_account_type(value)' in source
    assert 'entity_metadata_label("Status")' in source
    assert 'render_message("webui.show_organization_structure.select.organization_units_66c328dc")' in source
    assert 'render_message("webui.show_organization_structure.select.roles_2c70f24a")' in source
    assert '"org_unit": "webui.render_governance_cards.tooltip.open_organization_unit_831f72f6"' in source
    assert 'ui.badge(status_value.title()' not in source
    assert "organization-browser-summary-field" in source
    assert "organization-browser-summary-label" in source
    assert "organization-browser-summary-value" in source


def test_organization_browser_has_one_full_width_tree_and_explicit_directional_icons():
    source = inspect.getsource(index)
    assert "organization-browser-page-tree w-full min-w-0 h-full overflow-auto" in source
    assert "organization-browser-page-tree w-1/2" not in source
    assert "icon=tree_expander_icon(key in expanded)" in source
    assert 'html[dir="rtl"] .organization-browser-disclosure' not in source
    assert 'html[dir="rtl"] .organization-browser-page-tree' not in source


def test_browsed_relationship_selection_adds_option_and_value_atomically():
    class FakeControl:
        def __init__(self):
            self.options = {1: "Existing user"}
            self.value = None

        def set_options(self, options, *, value):
            self.options = options
            self.value = value

    control = FakeControl()
    apply_relationship_selection(control, 42, "Selected user")
    assert control.options == {1: "Existing user", 42: "Selected user"}
    assert control.value == 42


def test_favourite_click_handler_stops_propagation_inside_function():
    assert STOP_PROPAGATION_CLICK_HANDLER.startswith("(event) =>")
    assert "event.stopPropagation(); emit();" in STOP_PROPAGATION_CLICK_HANDLER


def test_lifecycle_actions_keep_activate_button_for_inactive_rows():
    assert 'v-if="props.row.status === \'inactive\'"' in LIFECYCLE_ACTION_BUTTONS
    assert 'icon="toggle_on"' in LIFECYCLE_ACTION_BUTTONS
    assert 'aria-label="Activate"' in LIFECYCLE_ACTION_BUTTONS
    assert "v-else" in LIFECYCLE_ACTION_BUTTONS
    assert 'aria-label="Deactivate"' in LIFECYCLE_ACTION_BUTTONS


def test_suspend_action_remains_visible_but_disabled_for_inactive_users():
    assert 'v-if="props.row.status !== \'suspended\'"' in USER_SUSPENSION_ACTION_BUTTONS
    assert ':disable="props.row.status !== \'active\'"' in USER_SUSPENSION_ACTION_BUTTONS
    assert "Activate the user before suspending" in USER_SUSPENSION_ACTION_BUTTONS
    assert 'icon="play_circle"' in USER_SUSPENSION_ACTION_BUTTONS


def test_dashboard_recent_configuration_rejects_non_positive_values(monkeypatch):
    monkeypatch.setenv("DASHBOARD_RECENT_ITEM_LIMIT", "0")
    with pytest.raises(RuntimeError, match="must be at least 1"):
        dashboard_recent_item_limit()

    monkeypatch.setenv("DASHBOARD_FAVOURITE_ITEM_LIMIT", "0")
    with pytest.raises(RuntimeError, match="must be at least 1"):
        dashboard_favourite_item_limit()


def test_organizational_ownership_is_presented_on_details_and_dashboard():
    source = with_english_messages(inspect.getsource(index))
    raw_source = inspect.getsource(index)
    assert '"Owning organizational unit"' in source
    assert "await api.dashboard_summary(" in source
    assert 'dashboard_load_state = {"running": False}' in source
    assert 'if dashboard_load_state["running"]:' in source
    assert 'ui.label("Holdings by organizational unit")' in source
    assert "Only units where you have an effective role; counts respect your access." in source
    assert '"dashboard-holdings-list"' in source
    assert '"dashboard-holdings-row"' in source
    assert 'select_organization_unit_details(' in source
    assert '"role=button tabindex=0"' in source
    assert '"keydown.enter"' in source
    assert 'dashboard-holdings-open' not in source
    assert 'owner_count["aggregation_count"]' in raw_source
    assert 'owner_count["record_count"]' in raw_source
    assert 'owner_count["open_aggregation_count"]' in raw_source
    assert 'owner_count["closed_aggregation_count"]' in raw_source
    assert 'owner_count["vital_record_count"]' in raw_source
    assert 'owner_count["storage_size_in_bytes"]' in raw_source
    assert '"dashboard-holdings-mediums"' in source
    assert '"dashboard-overview-medium dashboard-holdings-medium"' in source
    assert 'for medium_index, medium in enumerate((' in source
    assert 'ui.label("·").classes(' in source
    assert 'owner_count[f"{medium}_record_count"]' in source
    assert '"dashboard-holdings-peer-stat tabular-nums"' in source
    assert 'ui.icon("storage", size="14px")' in source
    assert ".dashboard-holdings-peer-stat .q-icon" in APP_SOURCE


def test_metadata_editor_shows_read_only_owning_org_unit_context():
    source = with_english_messages(inspect.getsource(index))
    assert '"Owning organizational unit", value=owner_label' in source
    assert '.props("outlined readonly")' in source
    assert "Move the resource through the governed move action to change it." in source


def test_record_creation_explains_and_enforces_parent_owner_role_context():
    source = with_english_messages(inspect.getsource(index))
    parent_position = source.index('controls["aggregation_id"] = field_input(')
    create_for_position = source.index('label="Create for *"', parent_position)
    assert parent_position < create_for_position
    assert "Select the role that will receive creator access. The record belongs to the" in source
    assert "parent aggregation's organizational unit." in source
    assert 'role="status" aria-live="polite"' in source
    assert "previous Create for selection was cleared" in source
    assert "you cannot create a record there" in source
    assert "previous_role_id in eligible_role_ids" in source
    assert 'payload["aggregation_id"] = int(target_aggregation_id)' in source
    assert 'controls["aggregation_id"].props("readonly")' in source
    assert "The parent aggregation is fixed because this record is being" in source
    assert 'controls["aggregation_id"].disable()' not in source[parent_position:create_for_position]
    assert "if len(creation_roles) == 1:" in source[parent_position:]
    assert 'controls["creator_acl_role_id"].props("readonly")' in source
    assert "if len(rows) == 1:" in source[create_for_position:]
    upload_handler_position = source.index("def upload_to_draft(")
    context_sync_position = source.index(
        'await api.update_record_draft(draft["id"], component_context)',
        upload_handler_position,
    )
    component_upload_position = source.index(
        "await api.upload_draft_component(", upload_handler_position,
    )
    assert context_sync_position < component_upload_position


def test_aggregation_creation_places_parent_before_role_and_explains_ownership():
    source = with_english_messages(inspect.getsource(index))
    aggregation_parent_position = source.index(
        'controls["parent_aggregation_id"] = field_input('
    )
    aggregation_create_for_position = source.index(
        'label="Create for *"', aggregation_parent_position
    )
    assert aggregation_parent_position < aggregation_create_for_position
    assert "Optional. Leave this blank to create a root aggregation" in source
    assert "select a parent" in source
    assert "For a child aggregation, the parent determines the owning organizational unit" in source
    assert "For a root" in source
    assert "aggregation, Create for determines both." in source
    assert "cannot add a child aggregation there" in source
    assert "previous Create for selection was cleared" in source


def test_required_fields_are_visually_marked_and_explained():
    source = with_english_messages(inspect.getsource(index))
    field_source = inspect.getsource(field_input)
    assert 'webui.field_input.text.label_29445dc3' in field_source
    assert 'localized_label = entity_metadata_label(field.label)' in field_source
    assert source.count('ui.label("* Required fields")') >= 2
    assert source.count('label="Create for *"') == 2


def test_governed_move_and_root_ownership_correction_are_exposed():
    source = with_english_messages(inspect.getsource(index))
    assert source.count('"Advanced", caption="Specialist') == 2
    assert source.count('icon="tune", value=False') == 2
    assert "show_aggregation_move" in source
    assert "show_ownership_correction_action" in source
    assert "show_acl_defaults" in source
    assert 'ui.label("Correct ownership")' in source
    assert '"Correct owner and creator ACL role"' in source
    assert 'api.correct_ownership(' in source
    assert 'api.acl_move_preview(' in source
    assert 'api.move_with_acl(' in source
    assert '"This move changes organizational ownership' in source


def test_acl_editor_presents_contextual_org_unit_members_principal():
    source = with_english_messages(inspect.getsource(index))
    assert '"Add all org unit members"' in source
    assert '"principal_type": "org_unit_members"' in source
    assert 'ui.label("All org unit members")' in source
    assert "Membership updates automatically when role assignments change." in source
    assert "Everyone currently working in" in source


def test_component_display_helpers_prioritize_readable_file_information():
    assert format_file_size(512) == "512 B"
    assert format_file_size(1_572_864) == "1.5 MB"
    assert format_file_size(None) == "—"
    assert component_file_icon("application/pdf") == "picture_as_pdf"
    assert component_file_icon("image/jpeg") == "image"
    assert component_file_icon("application/xml") == "description"
    assert component_file_icon("application/octet-stream") == "description"
    assert component_file_icon(None) == "description"


def test_component_uploader_batches_multiple_files_into_one_handler():
    uploader = component_uploader(lambda event: None)
    assert uploader._props["multiple"] is True
    assert uploader._props["batch"] is True
    assert uploader._upload_handlers == []
    assert len(uploader._multi_upload_handlers) == 1
    assert "list" in uploader.slots
    assert "file.__img" not in uploader.slots["list"].template
    assert "file.__sizeLabel" in uploader.slots["list"].template


def test_upload_batch_is_fully_buffered_before_api_awaits():
    sources = [BytesIO(b"first"), BytesIO(b"second"), BytesIO(b"third")]
    event = SimpleNamespace(
        contents=sources,
        names=["one.txt", "two.txt", "three.txt"],
        types=["text/plain", "text/plain", ""],
    )
    assert buffer_upload_batch(event) == [
        (b"first", "one.txt", "text/plain"),
        (b"second", "two.txt", "text/plain"),
        (b"third", "three.txt", "application/octet-stream"),
    ]
    assert all(source.tell() > 0 for source in sources)
def test_review_and_location_experience_has_accessible_text_labels():
    source = APP_SOURCE
    assert 'ui.label("Review reminders")' in source
    assert '"dashboard-review-columns"' in source
    assert '"dashboard-review-group"' in source
    assert '"dashboard-review-item"' in source
    assert '"dashboard.resource.identity",type=dashboard_resource_type(resource),number=number' in inspect.getsource(index)
    assert 'ui.label("Change location")' in source
    assert 'ui.input("Assigned location"' in source
    assert 'ui.input("Current location"' in source
    assert 'ui.textarea("Reason *")' in source
    assert 'f\'{"Assigned location"} · {"Inherited location"}\'' in source
    assert 'record.get("effective_assigned_location") or "Unknown"' in source
    assert 'f\'{"Current location"} · {"Inherited location"}\'' in source
    assert 'record.get("effective_current_location") or "Unknown"' in source
    assert 'if record.get("medium") != "digital":' in source
    assert 'if current.get("medium") != "digital":' in source
    assert 'aggregation_metadata.extend([' in source
    assert '"Record status"' not in source
    assert '"Closure state"' not in source
    assert '"View all", icon="arrow_forward"' in source
    assert '"review", "Review", review_display(record.get("date_of_next_review"))' in source
    assert '"Vital status"' in source
    assert '"medium", "Medium", medium_label(record.get("medium"))' in source
    assert '"medium", "Medium", medium_label(current.get("medium"))' in source
    assert 'color="red-8" if record.get("is_vital") else "blue-grey-7"' in source
    assert 'color="red-8" if current.get("is_vital") else "blue-grey-7"' in source
    assert 'ui.label("Vital record")' in source
    assert "This record is protected from deletion while its vital status applies." in source
    assert 'ui.badge("Vital", color="red-8")' not in source
    assert '"Change this aggregation\'s assigned or current physical location"' in source
    assert '"Change whether this aggregation is protected as vital"' in source
    assert '"Change whether this record is protected as vital"' in source
    assert '"Reason for change"' in source
    assert '"Reason for changing the medium"' not in source
    assert '"Reason for lowering the security level"' not in source


def test_record_and_aggregation_searches_use_shared_compact_results():
    source = APP_SOURCE
    assert "def render_entity_compact_results(spec: EntitySpec)" in source
    assert 'if spec.key in {"aggregations", "records"}:' in source
    assert "render_entity_compact_results(spec)" in source
    assert "show_medium=True" in source
    assert 'parent_aggregation=parent' not in source
    assert 'icon="folder", on_click=lambda _, parent=parent_aggregation' not in source
    assert 'await decorate_record_search_components(decorated_rows)' in source
    assert 'flex: 0 0 92px; width: 92px;' in source
    assert 'font-variant-numeric: tabular-nums;' in source


def test_entity_search_return_restores_page_row_and_expansion_state():
    source = APP_SOURCE
    assert '"entity_result_states": {}' in source
    assert '"entity_result_state": {' in source
    assert 'restored_result_state["expanded_results"] = set(' in source
    assert 'result_state["return_anchor"] = f"compact-result-{resource}-{int(item[\'id\'])}"' in source
    assert 'restore_compact_result_anchor(result_state.pop("return_anchor", None))' in source
    assert 'initially_expanded=f"{resource}:{int(item[\'id\'])}" in result_state["expanded_results"]' in source


def test_entity_page_favourites_reuse_dashboard_compact_item_treatment():
    source = with_english_messages(inspect.getsource(index))
    favourites_source = source[
        source.index("def render_entity_favourites_section"):
        source.index("def render_resource_personal_sections")
    ]
    assert 'classes("dashboard-personal-item")' in favourites_source
    assert 'classes("dashboard-personal-panel w-full")' in favourites_source
    assert "ui.grid(columns=2)" not in favourites_source
    assert '"recent-card cursor-pointer' not in favourites_source


def test_record_and_aggregation_searches_keep_favourites_and_recents_visible():
    source = with_english_messages(inspect.getsource(index))
    render_table_source = source[source.index("def render_table(spec: EntitySpec)"):]
    assert render_table_source.count("render_resource_personal_sections(spec)") >= 2
    assert "render_entity_compact_results(spec)\n                render_resource_personal_sections(spec)" in render_table_source


def test_classification_workspace_reuses_path_loaded_for_tree_reveal():
    assert WORKSPACE_SOURCE.count("api.classification_path(") == 1
    assert WORKSPACE_SOURCE.count("load_classification_path(") == 2
    assert 'workspace["paths"].clear()' in WORKSPACE_SOURCE
    assert 'workspace["paths"][selected["id"]][:-1]' in WORKSPACE_SOURCE
    assert 'if not current(revision):' in WORKSPACE_SOURCE


def test_resource_personal_sections_load_lazily_and_update_their_own_host():
    source = APP_SOURCE
    select_source = source[
        source.index("async def select_entity("):
        source.index("async def select_classification_workspace(")
    ]
    assert 'state["personal_sections_loading"][key] = True' in select_source
    assert "background_tasks.create(refresh_personal_sections())" in select_source
    assert 'state["personal_section_hosts"].get(resource_key)' in select_source
    assert "render_resource_personal_sections(\n                                resource_spec, container=personal_host," in select_source


def test_committed_navigation_cancels_abandoned_reads():
    register_source = APP_SOURCE[
        APP_SOURCE.index("def register_navigation("):
        APP_SOURCE.index("async def breadcrumb_back(")
    ]
    assert "api.cancel_pending_reads()" in register_source


def test_dashboard_complete_review_list_uses_server_side_pages():
    dashboard_source = APP_SOURCE[
        APP_SOURCE.index("async def select_dashboard("):
        APP_SOURCE.index("async def select_organization_unit_details(")
    ]
    assert 'page = {"offset": 0, "limit": 25, "loading": False}' in dashboard_source
    assert "limit=page[\"limit\"], offset=page[\"offset\"]" in dashboard_source
    assert 'has_more = len(fetched) > page["limit"]' in dashboard_source
    assert 'items = fetched[:page["limit"]]' in dashboard_source


def test_identity_lists_use_stable_name_first_ordering():
    load_source = APP_SOURCE[
        APP_SOURCE.index("async def load_rows("):
        APP_SOURCE.index("async def select_entity(")
    ]
    assert '"sort": "level_number" if spec.key == "security-levels" else "name"' in load_source
    assert '{"field": page["sort"], "direction": "asc"}' in load_source
    assert '[{"field": "id", "direction": "asc"}]' in load_source


def test_role_and_organization_unit_details_localize_fields_and_rtl_facts():
    organization_source = APP_SOURCE[
        APP_SOURCE.index("async def select_organization_unit_details("):
        APP_SOURCE.index("async def select_role_details(")
    ]
    role_source = APP_SOURCE[
        APP_SOURCE.index("async def select_role_details("):
        APP_SOURCE.index("async def select_user_details(")
    ]
    for source in (organization_source, role_source):
        assert 'classes("identity-detail-facts w-full gap-4")' in source
        assert 'classes("identity-detail-fact gap-0 border-b border-slate-100 pb-1.5")' in source
        assert 'ui.label("Direct status")' not in source
        assert 'if label in {"Direct status", "Effective status"}' not in source
    assert 'entity_metadata_label("Parent organization unit")' in organization_source
    assert 'entity_metadata_label("Security clearance")' in role_source
    assert 'entity_metadata_label("Information-governance role")' in role_source
    assert 'role.get("profile_name")' in role_source


def test_hold_people_selectors_use_independent_remote_typeahead_not_shared_search():
    holds_source = APP_SOURCE[
        APP_SOURCE.index("async def open_hold_editor("):
        APP_SOURCE.index("async def select_translation_administration(")
    ]
    assert 'api.list("users", limit=500)' not in holds_source
    assert holds_source.count("bind_remote_people_select(") >= 3
    assert "people_query = ui.input(" not in holds_source
    assert "people_previous = ui.button(" not in holds_source
    assert "people_next = ui.button(" not in holds_source
    assert 'excluded_ids=lambda: ({int(owner.value)} if owner.value is not None else set())' in holds_source
    assert 'excluded_ids=lambda: {int(hold["owner_user_id"])}' in holds_source
    assert 'contributors.value = [' in holds_source


def test_remote_people_typeahead_is_debounced_and_preserves_selected_people():
    helper_source = APP_SOURCE[
        APP_SOURCE.index("def bind_remote_people_select("):
        APP_SOURCE.index("def bind_remote_scheme_select(")
    ]
    assert "term = query.strip()" in helper_source
    assert "if len(term) < 2:" in helper_source
    assert 'await api.active_people(term, limit=25, offset=0)' in helper_source
    assert 'control.on("input-value", schedule_filter)' in helper_source
    assert 'control.on("popup-show"' not in helper_source
    assert 'await asyncio.sleep(0.2)' in helper_source
    assert 'selected_options = {' in helper_source
