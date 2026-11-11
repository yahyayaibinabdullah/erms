"""Privileged Translation Inspector UI and optional browser asset lifecycle."""
from __future__ import annotations
import json
from typing import Any
from nicegui import ui
from .i18n_catalogue import (render_message, render_message_plain,
    enable_diagnostic_metadata, disable_diagnostic_metadata)


def build_translation_inspector(
    *, page_client, principal, brand_row, brand_mark, brand_name, diagnostics_separator, diagnostics_section, inspector_switch, user_menu, guarded_page_navigation, select_translation_administration,
):
    async def clear_translation_inspector_session() -> None:
        """Clear browser diagnostics without pre-creating an awaitable response."""
        await page_client.run_javascript(
            "window.wathiqTranslationInspector?.clearSession(); "
            "history.replaceState(null, '', '/'); true", timeout=5,
        )


    async def ensure_translation_inspector_asset() -> None:
        """Load and initialize the inspector before any switch state is applied."""
        await page_client.run_javascript(
            "if (!window.wathiqTranslationInspectorLoad) window.wathiqTranslationInspectorLoad = new Promise((resolve, reject) => {"
            "if (window.wathiqTranslationInspector) { resolve(true); return; }"
            "const existing = document.getElementById('wathiq-translation-inspector-script');"
            "if (existing) existing.remove();"
            "const script = document.createElement('script');"
            "script.id = 'wathiq-translation-inspector-script';"
            "script.src = '/static/inspector/translation-inspector.js?v=10';"
            "script.onload = () => resolve(true);"
            "script.onerror = () => { script.remove(); reject(new Error('Translation inspector failed to load')); };"
            "document.head.appendChild(script);"
            "}).catch(error => { window.wathiqTranslationInspectorLoad = null; throw error; });"
            "window.wathiqTranslationInspectorLoad",
            timeout=15,
        )
        inspector_labels = {
            "title": render_message_plain("translation_inspector.panel.title"),
            "guidance": render_message_plain("translation_inspector.panel.guidance"),
            "clickGuidance": render_message_plain("translation_inspector.panel.click_guidance"),
            "copy": render_message_plain("translation_inspector.action.copy_key"),
            "open": render_message_plain("translation_inspector.action.open_administration"),
            "language": render_message_plain("translation_inspector.field.language"),
            "fallback": render_message_plain("translation_inspector.field.fallback"),
            "yes": render_message_plain("translation_inspector.value.yes"),
            "no": render_message_plain("translation_inspector.value.no"),
        }
        await page_client.run_javascript(
            "window.wathiqTranslationInspector.initialize("
            + json.dumps(inspector_labels, ensure_ascii=False)
            + "); true",
            timeout=5,
        )


    def refresh_inspectable_chrome() -> None:
        """Re-render persistent header text after Inspector metadata is enabled."""
        accessible_name = render_message("webui.index.accessible_name.wathiq_faa0862c")
        brand_row.props('aria-label=' + repr(accessible_name))
        brand_mark.props("fit=contain alt='" + accessible_name + "'")
        brand_name.text = render_message("webui.index.label.wathiq_d1dfb800")
        brand_name.update()


    async def synchronize_translation_inspector(privileges: set[str]) -> None:
        authorized = "localization.administer" in privileges
        if authorized:
            enable_diagnostic_metadata(page_client.id)
        else:
            disable_diagnostic_metadata(page_client.id)
        diagnostics_separator.set_visibility(authorized)
        diagnostics_section.set_visibility(authorized)
        if not authorized:
            inspector_switch.value = False
            inspector_switch.update()
            return
        try:
            await ensure_translation_inspector_asset()
            enabled = await page_client.run_javascript(
                "window.wathiqTranslationInspector.setAuthorized("
                + ("true" if authorized else "false")
                + "); window.wathiqTranslationInspector.restore()",
                timeout=5,
            )
        except Exception:
            enabled = False
        inspector_switch.value = bool(enabled) if authorized else False
        inspector_switch.update()
        if enabled:
            refresh_inspectable_chrome()


    async def toggle_translation_inspector(event: Any) -> None:
        authorized = "localization.administer" in set(
            (principal() or {}).get("global_privileges", [])
        )
        try:
            await ensure_translation_inspector_asset()
            enabled = await page_client.run_javascript(
                "window.wathiqTranslationInspector.setAuthorized("
                + ("true" if authorized else "false")
                + "); window.wathiqTranslationInspector.setEnabled("
                + ("true" if bool(event.value) else "false")
                + ")",
                timeout=5,
            )
        except Exception:
            enabled = False
            ui.notify(render_message("shared.errors.unexpected"), color="negative")
        if bool(inspector_switch.value) != bool(enabled):
            inspector_switch.value = bool(enabled)
            inspector_switch.update()
        if enabled:
            refresh_inspectable_chrome()


    async def open_inspected_translation(event: Any) -> None:
        privileges = set(
            (principal() or {}).get("global_privileges", [])
        )
        if "localization.administer" not in privileges:
            await synchronize_translation_inspector(privileges)
            return
        message_key = str(
            await page_client.run_javascript(
                "document.getElementById('translation-inspector-bridge')?.dataset.translationKey || ''",
                timeout=5,
            )
            or ""
        ).strip()
        if not message_key:
            return
        user_menu.close()
        await guarded_page_navigation(
            lambda: select_translation_administration(initial_key=message_key)
        )


    return clear_translation_inspector_session, synchronize_translation_inspector, toggle_translation_inspector, open_inspected_translation
