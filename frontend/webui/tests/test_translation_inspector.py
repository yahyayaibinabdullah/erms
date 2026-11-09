from pathlib import Path

from frontend.webui.i18n_catalogue import load_english_manifest


ROOT = Path(__file__).parents[3]
APP_SOURCE = (ROOT / "frontend/webui/app.py").read_text()
INSPECTOR_SOURCE = (
    ROOT / "frontend/webui/static/translation-inspector.js"
).read_text()


def test_translation_inspector_catalogue_contract_is_complete():
    catalogue = load_english_manifest()
    required = {
        "translation_inspector.menu.diagnostics",
        "translation_inspector.menu.toggle",
        "translation_inspector.panel.title",
        "translation_inspector.panel.guidance",
        "translation_inspector.panel.click_guidance",
        "translation_inspector.action.copy_key",
        "translation_inspector.action.open_administration",
        "translation_inspector.field.language",
        "translation_inspector.field.fallback",
        "translation_inspector.value.yes",
        "translation_inspector.value.no",
    }
    assert required <= catalogue.keys()


def test_inspector_is_privileged_session_only_and_cleared_with_identity():
    assert '"localization.administer" in privileges' in APP_SOURCE
    assert "diagnostics_section.set_visibility(authorized)" in APP_SOURCE
    assert "wathiqTranslationInspector?.clearSession()" in APP_SOURCE
    assert "sessionStorage.setItem(STORE,'true')" in INSPECTOR_SOURCE
    assert "disable_diagnostic_metadata(page_client.id)" in APP_SOURCE
    assert "enable_diagnostic_metadata(page_client.id)" in APP_SOURCE
    assert "enable_diagnostic_metadata(page_client.id)\n    page_client" not in APP_SOURCE
    assert "localStorage" not in INSPECTOR_SOURCE
    assert "background_tasks.create(clear_translation_inspector_session())" in APP_SOURCE
    assert "background_tasks.create(page_client.run_javascript" not in APP_SOURCE


def test_inspector_switch_loads_the_asset_before_applying_state():
    assert "async def ensure_translation_inspector_asset()" in APP_SOURCE
    assert "window.wathiqTranslationInspectorLoad = null" in APP_SOURCE
    assert "wathiq-translation-inspector-script" in APP_SOURCE
    assert "await ensure_translation_inspector_asset()" in APP_SOURCE
    assert "window.wathiqTranslationInspector.setEnabled(" in APP_SOURCE
    assert "window.wathiqTranslationInspector?.setEnabled(" not in APP_SOURCE


def test_inspector_uses_one_delegated_interaction_layer():
    assert ".dataset.i18nKey" in INSPECTOR_SOURCE
    assert "new MutationObserver" in INSPECTOR_SOURCE
    assert "['pointerover','over']" in INSPECTOR_SOURCE
    assert "['focusin','focus']" in INSPECTOR_SOURCE
    assert "['click','click']" in INSPECTOR_SOURCE
    click_handler = INSPECTOR_SOURCE.split("click:e=>", 1)[1].split(",key:e=>", 1)[0]
    assert "e.preventDefault()" in click_handler
    assert "e.stopPropagation()" in click_handler
    assert "stopImmediatePropagation" not in INSPECTOR_SOURCE
    assert "e.key==='Escape'" in INSPECTOR_SOURCE
    assert "#wathiq-translation-inspector" in INSPECTOR_SOURCE


def test_inspector_retains_metadata_after_sanitizing_its_own_dom_markers():
    assert "textData.get(n)?.entries" in INSPECTOR_SOURCE
    assert "previous.value!==p.value" in INSPECTOR_SOURCE
    assert "if(p.entries.length||!previous" in INSPECTOR_SOURCE


def test_inspector_panel_is_movable_and_kept_inside_the_viewport():
    assert "function makeMovable(p)" in INSPECTOR_SOURCE
    assert "setPointerCapture" in INSPECTOR_SOURCE
    assert "function place(p,left,top)" in INSPECTOR_SOURCE
    assert "sessionStorage.setItem(POSITION_STORE" in INSPECTOR_SOURCE
    assert "addEventListener('resize'" in INSPECTOR_SOURCE


def test_inspector_panel_supports_copy_and_filtered_administration_navigation():
    assert "navigator.clipboard.writeText(x.key)" in INSPECTOR_SOURCE
    assert "b.dataset.translationKey=x.key" in INSPECTOR_SOURCE
    assert 'inspector_bridge.on("click", open_inspected_translation)' in APP_SOURCE
    assert "select_translation_administration(initial_key=message_key)" in APP_SOURCE
    assert "value=initial_key or \"\"" in APP_SOURCE
    assert '"fallback_keys"' in (
        ROOT / "backend/services/api/localization.py"
    ).read_text()


def test_inspector_refreshes_persistent_brand_chrome_after_being_enabled():
    assert "def refresh_inspectable_chrome()" in APP_SOURCE
    assert 'brand_name.text = render_message("webui.index.label.wathiq_d1dfb800")' in APP_SOURCE
    assert "brand_row.props('aria-label=' + repr(accessible_name))" in APP_SOURCE
    assert "if enabled:\n            refresh_inspectable_chrome()" in APP_SOURCE


def test_inspector_does_not_assign_keys_to_user_authored_values():
    assert "_diagnostic_marker(effective_key, rendered)" in (
        ROOT / "frontend/webui/i18n_catalogue.py"
    ).read_text()
    assert "dataset.i18nKey" in INSPECTOR_SOURCE
    candidate = INSPECTOR_SOURCE.split("const candidate=", 1)[1].split("const handlers=", 1)[0]
    assert "textContent" not in candidate


def test_inspector_can_always_be_disabled_from_the_user_menu():
    assert "closest('[data-inspector-ignore]')" in INSPECTOR_SOURCE
    assert "data-inspector-ignore=true" in APP_SOURCE


def test_inspector_metadata_cannot_flash_visible_translation_keys():
    catalogue = (ROOT / "frontend/webui/i18n_catalogue.py").read_text()
    assert "VARIATION_SELECTOR_BASE = 0xFE00" in catalogue
    assert "_encoded_diagnostic_length(len(rendered))" in catalogue
    assert "V=0xFE00" in INSPECTOR_SOURCE
    assert "function parse(value)" in INSPECTOR_SOURCE
    assert "\\uE000([a-z][a-z0-9_.]*)" not in INSPECTOR_SOURCE


def test_translation_administration_pages_complete_context_groups():
    assert '"limit": 10, "total": 0, "key_total": 0' in APP_SOURCE
    assert 'page["total"]=group_total' in APP_SOURCE
    assert 'len(grouped)' in APP_SOURCE
    assert 'group_total and not data["items"] and page["offset"]' in APP_SOURCE
    assert 'state["translation_offset"] = 0' in APP_SOURCE


def test_copied_inspector_text_is_searchable_without_altering_visible_characters():
    from nicegui import ui
    from frontend.webui.i18n_catalogue import (
        _diagnostic_marker, disable_diagnostic_metadata, enable_diagnostic_metadata,
        strip_diagnostic_metadata,
    )
    with ui.column() as host:
        enable_diagnostic_metadata(host.client.id)
        try:
            for text in ('وسط الحفظ', 'Medium', 'نصّ عربي ❤️'):
                marked = _diagnostic_marker('entity_metadata.field.medium', text)
                assert marked != text
                assert strip_diagnostic_metadata(marked) == text
                assert strip_diagnostic_metadata(text) == text
                assert strip_diagnostic_metadata(marked + ' / ' + marked) == text + ' / ' + text
        finally:
            disable_diagnostic_metadata(host.client.id)
