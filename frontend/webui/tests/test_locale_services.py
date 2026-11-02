from datetime import date, datetime, timedelta, timezone
import inspect
import json
from pathlib import Path

import pytest

from frontend.webui.i18n_catalogue import (
    _encoded_diagnostic_key, load_english_manifest, render_english,
)
from frontend.webui.locale_services import (
    date_value, format_instant, format_local_date, LocalizedTimezoneError,
    utc_instant_to_working,
    working_datetime_to_utc,
)
from frontend.webui.scripts.check_i18n_catalogue import validate_repository_catalogue
from frontend.webui.scripts.extract_english_messages import extract
from frontend.webui.app import (
    index, review_datetime_input_minimum, review_datetime_input_value,
    review_datetime_payload,
)
from frontend.webui.locale_services import clear_locale_context, set_locale_context


def test_manifest_has_context_and_exact_placeholder_schemas():
    catalogue = load_english_manifest()
    assert catalogue["preferences.validation.language.unsupported"]["context_group"] == "preferences"
    assert catalogue["preferences.validation.language.unsupported"]["parameter_schema"] == {"language": "identifier"}
    validate_repository_catalogue()


def test_english_manifest_is_cached_after_its_first_validated_load():
    load_english_manifest.cache_clear()
    first = load_english_manifest()
    second = load_english_manifest()
    assert first is second
    assert load_english_manifest.cache_info().misses == 1
    assert load_english_manifest.cache_info().hits == 1


def test_translation_inspector_key_encoding_is_cached():
    _encoded_diagnostic_key.cache_clear()
    first = _encoded_diagnostic_key("navigation.item.dashboard")
    second = _encoded_diagnostic_key("navigation.item.dashboard")
    assert first == second
    assert _encoded_diagnostic_key.cache_info().misses == 1
    assert _encoded_diagnostic_key.cache_info().hits == 1


def test_translation_inspector_skips_dom_scans_while_disabled():
    script = (
        Path(__file__).parents[1] / "static" / "translation-inspector.js"
    ).read_text()
    assert "new MutationObserver" in script
    assert "observer.disconnect()" in script
    assert "observer.observe(document.documentElement" in script
    assert "if(state.enabled)" in script
    assert "scan(document);" in script
    initialize = script[script.index("initialize(labels)"):script.index("setAuthorized(v)")]
    assert "scan(document)" not in initialize


def test_navigation_and_translation_administration_have_arabic_catalogue_entries():
    root = Path(__file__).parents[3]
    artifact = json.loads(
        (root / "frontend/webui/i18n/messages.ar.generated.json").read_text()
    )
    arabic = {item["message_key"]: item["translated_text"] for item in artifact["items"]}
    assert arabic["navigation.item.dashboard"] == "لوحة المعلومات"
    assert arabic["navigation.item.translations"] == "الترجمات"
    assert arabic["localization.filter.status.all"] == "جميع الحالات"
    assert arabic["localization.administration.result_count"].startswith("{count}")


def test_privilege_catalogue_has_contextual_english_and_arabic_copy():
    root = Path(__file__).parents[3]
    english = load_english_manifest()
    artifact = json.loads(
        (root / "frontend/webui/i18n/messages.ar.generated.json").read_text()
    )
    arabic = {item["message_key"]: item["translated_text"] for item in artifact["items"]}
    assert english["privilege.authorization.administer.name"]["default_text"] == "Authorization Administer"
    assert english["privilege.authorization.administer.description"]["context_group"] == "privilege.authorization.administer"
    assert arabic["privilege.authorization.administer.name"] == "إدارة التفويض"
    assert arabic["privilege.authorization.administer.description"].startswith("تتيح هذه الصلاحية")
    assert arabic["privilege.category.administration"] == "إدارة النظام"


def test_literal_audit_follows_data_driven_presentation_structures(tmp_path):
    source = tmp_path / "page.py"
    source.write_text(
        '''\nfrom nicegui import ui\nresource = "users"\nui.input({"users": "Filter users"}[resource], placeholder={"users": "Name or email"}.get(resource, "Search"))\nsort_options = {"name": "Name", "created": "Created"}\nui.select(sort_options)\nuser_facts = (("Account state", "Active"), ("External identifier", "—"))\nfor label, value in user_facts:\n    ui.label(label)\nui.number("Entity ID")\n''',
        encoding="utf-8",
    )
    candidates = extract(tmp_path)
    visible = " ".join(str(item["source_text"]) for item in candidates)
    for expected in (
        "Filter users", "Name or email", "Search", "Name", "Created",
        "Account state", "Active", "External identifier", "Entity ID",
    ):
        assert expected in visible


def test_renderer_escapes_and_isolates_named_parameters():
    rendered = render_english(
        "preferences.validation.language.unsupported", language="<ar>",
    )
    assert "<ar>" not in rendered
    assert "\u2068&lt;ar&gt;\u2069" in rendered
    with pytest.raises(ValueError):
        render_english("preferences.validation.language.unsupported", unexpected="ar")


def test_renderer_allows_message_key_as_a_template_placeholder():
    rendered = render_english(
        "webui.bulk_review_publish_dialog.label.message_key_code_19cb32db",
        message_key="navigation.item.dashboard",
        code="placeholder_mismatch",
    )
    assert "navigation.item.dashboard" in rendered
    assert "placeholder_mismatch" in rendered


def test_timezone_services_preserve_instants_and_calendar_dates():
    value = datetime(2026, 1, 1, 8, tzinfo=timezone.utc)
    assert utc_instant_to_working(value, "Asia/Dubai").hour == 12
    assert working_datetime_to_utc(datetime(2026, 1, 1, 12), "Asia/Dubai") == value
    assert date_value(date(2026, 1, 1)) == "2026-01-01"


def test_review_datetime_dialog_round_trips_through_the_working_timezone():
    set_locale_context("en", "Asia/Dubai")
    try:
        assert review_datetime_input_value("2026-10-01T06:00:00Z") == "2026-10-01T10:00"
        assert review_datetime_payload("2026-10-01T10:00") == "2026-10-01T06:00:00Z"
        assert review_datetime_payload("") is None
        assert len(review_datetime_input_minimum()) == 16
    finally:
        clear_locale_context("test")


def test_timezone_services_reject_gap_and_ambiguous_wall_times():
    with pytest.raises(LocalizedTimezoneError) as gap:
        working_datetime_to_utc(datetime(2026, 3, 29, 1, 30), "Europe/London")
    assert gap.value.message_key == "timezone.validation.wall_time.nonexistent"
    with pytest.raises(LocalizedTimezoneError) as overlap:
        working_datetime_to_utc(datetime(2026, 10, 25, 1, 30), "Europe/London")
    assert overlap.value.message_key == "timezone.validation.wall_time.ambiguous"
    earlier = working_datetime_to_utc(
        datetime(2026, 10, 25, 1, 30), "Europe/London", "earlier",
    )
    later = working_datetime_to_utc(
        datetime(2026, 10, 25, 1, 30), "Europe/London", "later",
    )
    assert later - earlier == timedelta(hours=1)


def test_explicit_timezone_formatting_covers_offsets_locale_and_calendar_dates():
    instant = datetime(2026, 2, 28, 20, 30, tzinfo=timezone.utc)
    assert format_instant(instant, "Asia/Kathmandu", "en") == "1 Mar 2026, 02:15 AM"
    assert format_instant(instant, "America/St_Johns", "en") == "28 Feb 2026, 05:00 PM"
    assert format_instant(instant, "Asia/Dubai", "ar") == "1 مارس 2026, 12:30 ص"
    assert format_local_date(date(2024, 2, 29), "en") == "29 Feb 2024"
    assert format_local_date(date(2024, 2, 29), "ar") == "29 فبراير 2024"
    assert format_local_date("2022-02-03T05:00:00+00:00", "en") == "3 Feb 2022"
    assert format_local_date("2022-02-03T05:00:00Z", "ar") == "3 فبراير 2022"


def test_authenticated_catalogue_uses_revision_scoped_session_cache():
    source = inspect.getsource(index)
    assert 'previous.get("effective_language") == bootstrap["effective_language"]' in source
    assert 'previous.get("catalogue_revision") == bootstrap["catalogue_revision"]' in source
    assert 'messages = session_messages' in source
    assert 'etag=session_catalogue_etag if same_language and has_cached_catalogue else None' in source
    assert 'catalogue.get("not_modified")' in source
    assert 'app.storage.user["localization_catalogue_etag"] = catalogue_etag' in source


def test_catalogue_revision_refresh_does_not_force_a_full_page_reload():
    source = inspect.getsource(index)
    rebuild = source[source.index("needs_rebuild = ("):source.index("return needs_rebuild")]
    assert "catalogue_revision" not in rebuild
    assert 'previous.get("effective_language", initial_language)' in rebuild
    assert 'previous.get("direction", initial_direction)' in rebuild


def test_dashboard_startup_defers_optional_assets_and_avoids_duplicate_favourites_call():
    source = inspect.getsource(index)
    workspace_setup = source[
        source.index("async def prepare_authenticated_workspace("):
        source.index("async def load_login_animation()")
    ]
    assert "background_tasks.create(load_authenticated_client_assets())" in workspace_setup
    initialization = source[
        source.index("async def initialize_authenticated_ui()"):
        source.index("ui.timer(0.05, initialize_authenticated_ui")
    ]
    assert "await reload_favourites()" not in initialization
    assert initialization.index('if principal["must_change_password"]:') < initialization.index(
        "await prepare_authenticated_workspace(principal)"
    )
    login_flow = source[
        source.index("async def submit_login()"):
        source.index('login_submit.on("click", submit_login)')
    ]
    assert "await reload_favourites()" not in login_flow
    assert login_flow.index('if principal["must_change_password"]:') < login_flow.index(
        "await prepare_authenticated_workspace(principal)"
    )


def test_dashboard_navigation_renders_cached_data_then_refreshes_in_background():
    source = inspect.getsource(index)
    dashboard = source[
        source.index("async def select_dashboard()"):
        source.index("async def select_audit_trail(")
    ]
    assert 'state["dashboard_summary_cache"] = summary' in dashboard
    assert "await load_dashboard(summary_override=cached_summary)" in dashboard
    assert "background_tasks.create(load_dashboard(refresh_only=True))" in dashboard
    assert "on_click=lambda: load_dashboard(refresh_only=True)" in dashboard


def test_entity_page_startup_parallelizes_requests_and_bounds_relationship_resolution():
    source = inspect.getsource(index)
    assert "await asyncio.gather(*startup_requests)" in source
    assert "activity = await api.recent_resource_activity(spec.key, limit=50)" in source
    assert "decorated = await decorate_for_spec(spec, activity)" in source
    assert "async def rows_by_id(" in source
    assert "async def org_unit_context(" in source


def test_navigation_and_translation_administration_route_visible_copy_through_catalogue():
    source = inspect.getsource(index)
    for key in (
        "navigation.section.records",
        "navigation.section.organization",
        "navigation.item.dashboard",
        "navigation.item.translations",
        "localization.administration.subtitle",
        "localization.filter.status.all",
        "localization.filter.origin.all",
        "localization.administration.result_count",
    ):
        assert f'render_message("{key}"' in source
    for key in (
        "localization.placeholder_guidance.title",
        "localization.placeholder_guidance.body",
        "localization.placeholder_guidance.example",
    ):
        assert f'render_message("{key}"' in source


def test_placeholder_guidance_uses_literal_example_and_prohibits_fragments():
    catalogue = load_english_manifest()
    body = catalogue["localization.placeholder_guidance.body"]
    example = catalogue["localization.placeholder_guidance.example"]
    assert body["parameter_schema"] == {}
    assert "{{count}}" in body["default_text"]
    assert "plural suffixes" in body["default_text"]
    assert "partial words" in body["default_text"]
    assert example["parameter_schema"] == {}
    assert "{{count}}" in example["default_text"]


def test_untranslated_text_audit_covers_dynamic_assignments_and_accessible_names(tmp_path):
    (tmp_path / "sample.py").write_text(
        '''
from nicegui import ui
count = 3
status = f"{count} sessions active"
label = ui.label(status)
label.text = f"Showing {count} results"
ui.button("Open").props("aria-label='Open details'")
ui.label(render_message("already.localized"))
''',
        encoding="utf-8",
    )
    candidates = extract(tmp_path)
    kinds = {candidate["candidate_kind"] for candidate in candidates}
    assert {"ui_call", "component_assignment", "component_props"} <= kinds
    assert any(candidate["dynamic"] for candidate in candidates)
    assert any(
        candidate["component"] == "accessible_name" for candidate in candidates
    )
    assert all("already.localized" not in candidate["source_expression"] for candidate in candidates)
