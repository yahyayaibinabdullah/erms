"""Existing account preferences behavior with explicit session dependencies."""
from __future__ import annotations
from zoneinfo import available_timezones
from nicegui import ui, app
from .api_client import ApiError
from .i18n_catalogue import render_message


def build_account_preferences(
    *, api, get_localization, error_message, show_api_error,
):
    async def show_preferences() -> None:
        try:
            preference = await api.preferences()
            bootstrap = get_localization() or await api.localization_bootstrap()
        except ApiError as error:
            show_api_error(error); return
        languages = {
            item["language_tag"]: f"{item['native_name']} ({item['language_tag']})"
            for item in bootstrap["supported_languages"]
        }
        dialog = ui.dialog().props("persistent")
        with dialog, ui.card().classes("erms-preferences-dialog w-[620px] max-w-full gap-3"):
            ui.label(render_message("preferences.heading.personal")).classes("text-xl font-semibold")
            ui.label(render_message("preferences.guidance.personal")).classes("text-sm text-slate-500")
            language = ui.select(
                languages, value=preference["language_tag"],
                label=render_message("preferences.field.language"),
            ).props("outlined dense options-dense").classes("erms-preference-select w-full")
            working_timezone = ui.select(
                sorted(available_timezones()), value=preference["working_timezone"],
                label=render_message("preferences.field.working_timezone"),
            ).props("outlined dense options-dense use-input input-debounce=0").classes(
                "erms-preference-select w-full"
            )
            ui.label(render_message("preferences.guidance.working_timezone")).classes("text-xs text-slate-500")
            inline_error = ui.label().classes("text-sm text-negative")
            async def save_preferences() -> None:
                try:
                    await api.update_preferences(
                        language.value, working_timezone.value, preference["version"],
                    )
                    app.storage.user.pop("localization_context", None)
                    app.storage.user.pop("localization_messages", None)
                    app.storage.user.pop("localization_fallback_keys", None)
                    app.storage.user.pop("localization_catalogue_etag", None)
                    dialog.close()
                    await ui.run_javascript("window.location.reload(); true", timeout=5)
                except ApiError as error:
                    inline_error.text = error_message(error)
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(
                    icon="close", on_click=dialog.close,
                ).props(
                    f"flat round aria-label={render_message('preferences.action.cancel')!r}"
                ).tooltip(
                    render_message("common.action.cancel")
                )
                ui.button(
                    icon="save", on_click=save_preferences,
                ).props(
                    f"unelevated round aria-label={render_message('preferences.action.save')!r}"
                ).tooltip(
                    render_message("common.action.save")
                )
        dialog.open()


    return show_preferences
