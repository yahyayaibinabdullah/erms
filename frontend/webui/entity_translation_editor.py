"""Reusable localized entity-value editor inside the existing entity dialog.

The feature selects eligible fields and supplies any shared change-reason control.
The editor keeps dialog-local drafts and guards asynchronous language loads.
"""
from __future__ import annotations
from typing import Any, Callable
from nicegui import ui, background_tasks
from .api_client import ApiError
from .entity_creation import EntityCreation
from .entity_translation_drafts import EntityTranslationDrafts, TranslationUpdate
from .i18n_catalogue import render_message


async def entity_translation_editor(
    api: Any, *, resource: str, row: dict, fields: tuple[str, ...],
    languages: list[dict], dialog: Any, uses_external_reason: bool,
    get_external_reason: Callable, error_message: Callable, show_api_error: Callable,
    definition_translations: dict | None = None,
    creation: EntityCreation | None = None,
    edits: EntityTranslationDrafts | None = None,
) -> Callable:
    local_translations = creation.translations if creation is not None else definition_translations
    if local_translations is None and edits is None:
        edits = EntityTranslationDrafts(fields)
    language_options = {
        item["language_tag"]: f'{item["native_name"]} · {item["english_name"]}'
        for item in languages
        if item.get("is_enabled", True)
    }
    translation_state: dict[str, Any] = {
        "loaded_language": None,
        "load_generation": 0,
        "baseline": {field: "" for field in fields},
    }
    with ui.expansion(render_message("entity_translation_editor.expansion.title"), icon="translate").props(
        "dense header-class='text-sm font-medium'"
    ).classes("w-full rounded-lg border border-slate-200 bg-slate-50"):
        ui.label(
            render_message("webui.open_editor.label.optional_add_localized_names_and_descripti_611fdfb3")
        ).classes("text-xs leading-5 text-slate-600")
        language_control = ui.select(
            language_options, label=render_message("webui.open_editor.select.language_a1337600")
        ).props("outlined dense options-dense").classes("w-full")
        translation_field_labels = {
            "name": render_message("entity_translation_editor.input.name"),
            "title": render_message("entity_translation_editor.input.title"),
            "description": render_message("entity_translation_editor.input.description"),
        }
        translation_controls = {
            field: (
                ui.textarea(translation_field_labels[field]).props("outlined dense autogrow")
                if field == "description"
                else ui.input(translation_field_labels[field]).props("outlined dense")
            ).classes("w-full")
            for field in fields
        }
        for control in translation_controls.values():
            control.disable()
        translation_reason = (
            None if uses_external_reason or local_translations is not None else ui.input(
                render_message("webui.open_editor.input.reason_for_translation_change_82d24ea1")
            ).props("outlined dense").classes("w-full")
        )
        translation_status = ui.label(
            render_message("webui.open_editor.label.choose_a_language_then_load_its_current_va_7921b5e3")
        ).props('role="status" aria-live="polite"').classes(
            "text-xs text-slate-500"
        )
        # Capture these while the editor's client-localized UI
        # context is active. The API await below may resume in a
        # background task where NiceGUI no longer exposes that
        # client as the current rendering context.
        translation_loading_status = render_message("common.status.loading")
        translation_loaded_status = render_message(
            "entity_translation_editor.status.loaded"
        )

        def stage_definition_translation():
            tag = translation_state["loaded_language"]
            if not tag:
                return
            values = {field: (control.value or "").strip() for field, control in translation_controls.items()}
            if edits is not None:
                edits.values[tag] = values
                if not uses_external_reason:
                    edits.reasons[tag] = (translation_reason.value or "").strip()
            elif local_translations is not None:
                if any(values.values()):
                    local_translations[tag] = {field: value for field, value in values.items() if value}
                else:
                    local_translations.pop(tag, None)

        async def load_entity_translation(*, refresh: bool = False) -> None:
            if edits is not None and edits.writing:
                return
            stage_definition_translation()
            language = language_control.value
            if not language:
                ui.notify(render_message("webui.load_entity_translation.notify.choose_a_language_049998ee"), color="warning")
                return
            translation_state["load_generation"] += 1
            load_generation = translation_state["load_generation"]
            translation_state["loaded_language"] = None
            translation_state["baseline"] = {
                field: "" for field in translation_controls
            }
            translation_status.set_text(translation_loading_status)
            for control in translation_controls.values():
                # Keep the previous value disabled while loading. An intermediate
                # empty input update can arrive after the new language's value
                # through NiceGUI's input loopback and blank a successful load.
                control.disable()
                control.update()
            try:
                if edits is not None and language in edits.values and not refresh:
                    current = None
                elif local_translations is None:
                    current = await api.entity_translation(resource, row["id"], language)
                else:
                    current = {"fields": local_translations.get(language, {})}
                if (
                    load_generation != translation_state["load_generation"]
                    or language_control.value != language
                    or not dialog.value
                    or edits is not None and edits.writing
                ):
                    return
                if edits is not None:
                    if current is not None:
                        edits.loaded(language, current, row)
                    current = {"fields": edits.values[language]}
                    if not uses_external_reason:
                        translation_reason.value = edits.reasons.get(language, "")
                translation_state["loaded_language"] = language
                for field, control in translation_controls.items():
                    control.value = current["fields"].get(field) or ""
                    control.enable()
                    control.update()
                translation_state["baseline"] = {
                    field: (control.value or "").strip()
                    for field, control in translation_controls.items()
                }
                translation_status.set_text(translation_loaded_status)
            except ApiError as error:
                if (load_generation != translation_state["load_generation"]
                    or language_control.value != language or not dialog.value):
                    return
                # Language changes run in a background task. Restore
                # this editor's client context for localized errors.
                # Failed loads keep fields disabled and cannot save
                # a translation against an unknown baseline/version.
                with translation_status.client:
                    translation_status.set_text(error_message(error))
                    show_api_error(error)

        def pending_entity_translation() -> list[TranslationUpdate] | None:
            language = language_control.value
            stage_definition_translation()
            if local_translations is not None:
                if creation is not None and language and translation_state["loaded_language"] != language:
                    raise ValueError(render_message(
                        "webui.save_entity_translation.notify.load_the_selected_language_before_saving_dc2d8ba1"
                    ))
                return None
            if not edits.dirty_languages():
                if any((control.value or "").strip() for control in translation_controls.values()) and not translation_state["loaded_language"]:
                    raise ValueError(render_message(
                        "webui.save_entity_translation.notify.load_the_selected_language_before_saving_dc2d8ba1"
                    ))
                return None
            if language and translation_state["loaded_language"] != language:
                raise ValueError(render_message(
                    "webui.save_entity_translation.notify.load_the_selected_language_before_saving_dc2d8ba1"
                ))
            shared_reason = (get_external_reason().value or "").strip() if uses_external_reason else None
            updates = edits.updates(shared_reason)
            for tag, values, reason in updates:
                if not reason or not any(values.values()):
                    if language != tag:
                        language_control.value = tag
                    raise ValueError(render_message(
                        "webui.save_entity_translation.notify.enter_a_reason_for_the_translation_change_23f6bb0d"
                        if not reason else "entity_translation_editor.status.enter_one"
                    ))
            return updates

        async def remove_entity_translation() -> None:
            language = language_control.value
            if not language or translation_state["loaded_language"] != language:
                ui.notify(render_message("webui.save_entity_translation.notify.load_the_selected_language_before_saving_dc2d8ba1"), color="warning")
                return
            if local_translations is not None:
                local_translations.pop(language, None)
                for control in translation_controls.values():
                    control.value = ""
                    control.update()
                translation_state["baseline"] = {field: "" for field in fields}
                return
            reason_control = (
                get_external_reason()
                if uses_external_reason else translation_reason
            )
            reason = (reason_control.value or "").strip()
            if not reason:
                ui.notify(render_message("webui.save_entity_translation.notify.enter_a_reason_for_the_translation_change_23f6bb0d"), color="warning")
                return
            if edits.writing:
                return
            edits.writing = True
            stage_definition_translation()
            enabled = [control for control in [language_control, *translation_controls.values(), translation_reason, *translation_buttons]
                       if control is not None and control.enabled]
            for control in enabled:
                control.disable()
            try:
                removed_translation = await api.update_entity_translation(
                    resource, row["id"], language,
                    {field: None for field in fields},
                    row["version"], reason,
                )
                edits.accepted(language, {}, removed_translation, row)
                edits.reasons[language] = ""
                translation_state["baseline"] = {field: "" for field in fields}
                for control in translation_controls.values():
                    control.value = ""
                    control.update()
                reason_control.value = ""
                reason_control.update()
                translation_status.set_text(render_message("webui.remove_entity_translation.notify.translation_removed_09e85c43"))
                ui.notify(render_message("webui.remove_entity_translation.notify.translation_removed_09e85c43"), color="positive")
            except ApiError as error:
                show_api_error(error)
            finally:
                edits.writing = False
                for control in enabled:
                    control.enable()

        translation_buttons = []
        with ui.row().classes("w-full justify-end gap-1"):
            translation_buttons.append(ui.button(icon="refresh", on_click=lambda: load_entity_translation(refresh=True)).props(
                "flat round dense"
            ).tooltip(render_message("webui.open_editor.tooltip.load_translation_d75ce604")))
            translation_buttons.append(ui.button(icon="delete_outline", on_click=remove_entity_translation).props(
                "flat round dense color=negative"
            ).tooltip(render_message("webui.open_editor.tooltip.remove_translation_01e5d951")))

        language_control.on_value_change(
            lambda: background_tasks.create(load_entity_translation())
        )
        if language_control.value:
            await load_entity_translation()

    return pending_entity_translation
