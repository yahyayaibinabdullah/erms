"""Existing account localization behavior with explicit session dependencies."""
from __future__ import annotations
from nicegui import ui, app
from .i18n_catalogue import set_active_messages
from .locale_services import set_locale_context
from .rtl import normalize_direction, document_direction_script


def build_account_localization(
    *, api, initial_language, initial_direction, set_direction, drawer_toggle_button, get_localization, set_localization, set_configuration,
):
    async def apply_document_direction(language: str, direction: str) -> None:
        normalized = normalize_direction(direction)
        set_direction(normalized)
        ui.query("html").props(remove="lang dir").props(
            add=f"lang={language} dir={normalized}"
        )
        drawer_toggle_button.icon = (
            "chevron_right" if normalized == "rtl" else "chevron_left"
        )
        await ui.run_javascript(
            document_direction_script(language, normalized), timeout=5,
        )


    async def load_localization_context() -> bool:
        bootstrap = await api.localization_bootstrap()
        previous = app.storage.user.get("localization_context") or {}
        session_messages = app.storage.user.get("localization_messages") or {}
        session_fallback_keys = app.storage.user.get("localization_fallback_keys") or []
        session_catalogue_etag = app.storage.user.get("localization_catalogue_etag")
        cache_is_current = (
            isinstance(session_messages, dict)
            and bool(session_messages)
            and previous.get("effective_language") == bootstrap["effective_language"]
            and previous.get("catalogue_revision") == bootstrap["catalogue_revision"]
        )
        if cache_is_current:
            messages = session_messages
            fallback_keys = session_fallback_keys
            catalogue_etag = session_catalogue_etag
        else:
            same_language = (
                previous.get("effective_language") == bootstrap["effective_language"]
            )
            has_cached_catalogue = isinstance(session_messages, dict) and bool(session_messages)
            catalogue = await api.localization_catalogue(
                bootstrap["effective_language"],
                etag=session_catalogue_etag if same_language and has_cached_catalogue else None,
            )
            if catalogue.get("not_modified") and isinstance(session_messages, dict) and session_messages:
                messages = session_messages
                fallback_keys = session_fallback_keys
            else:
                messages = catalogue["messages"]
                fallback_keys = catalogue.get("fallback_keys", [])
            catalogue_etag = catalogue.get("etag") or session_catalogue_etag
        set_active_messages(messages, fallback_keys)
        # Persist remembered locale metadata only. Business settings remain a
        # transient page response, never another browser settings cache.
        set_localization({key:value for key,value in bootstrap.items() if key != "application_configuration"})
        set_configuration(bootstrap["application_configuration"])
        set_locale_context(
            bootstrap["effective_language"], bootstrap["working_timezone"],
        )
        app.storage.user["localization_context"] = get_localization()
        app.storage.user["localization_messages"] = messages
        app.storage.user["localization_fallback_keys"] = fallback_keys
        app.storage.user["localization_catalogue_etag"] = catalogue_etag
        await apply_document_direction(
            bootstrap["effective_language"], bootstrap["direction"],
        )
        needs_rebuild = (
            previous.get("effective_language", initial_language) != bootstrap["effective_language"]
            or previous.get("direction", initial_direction) != bootstrap["direction"]
        )
        if needs_rebuild:
            await ui.run_javascript("window.location.reload(); true", timeout=5)
        return needs_rebuild


    return apply_document_direction, load_localization_context
