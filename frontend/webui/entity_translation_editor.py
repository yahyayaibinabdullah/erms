"""Reusable localized entity-value editor inside the existing entity dialog.

The feature selects eligible fields and supplies any shared change-reason control.
The editor owns only its loaded language, baseline and asynchronous load generation.
"""
from __future__ import annotations
from typing import Any, Callable
from nicegui import ui, background_tasks
from .api_client import ApiError
from .i18n_catalogue import render_message


async def entity_translation_editor(
    api: Any, *, resource: str, row: dict, fields: tuple[str, ...],
    languages: list[dict], dialog: Any, uses_external_reason: bool,
    get_external_reason: Callable, error_message: Callable, show_api_error: Callable,
) -> Callable:
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
            None if uses_external_reason else ui.input(
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

        async def load_entity_translation() -> None:
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
                control.value = ""
                control.disable()
                control.update()
            try:
                current = await api.entity_translation(resource, row["id"], language)
                if (
                    load_generation != translation_state["load_generation"]
                    or language_control.value != language
                ):
                    return
                translation_state["loaded_language"] = language
                row["version"] = current["version"]
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

        def pending_entity_translation() -> tuple[
            str, dict[str, str], str
        ] | None:
            language = language_control.value
            entered_values = {
                field: (control.value or "").strip()
                for field, control in translation_controls.items()
            }
            if entered_values == translation_state["baseline"]:
                return None
            if not language or translation_state["loaded_language"] != language:
                raise ValueError(
                    render_message("webui.save_entity_translation.notify.load_the_selected_language_before_saving_dc2d8ba1")
                )
            reason_control = (
                get_external_reason()
                if uses_external_reason else translation_reason
            )
            reason = (reason_control.value or "").strip()
            if not reason:
                raise ValueError(
                    render_message("webui.save_entity_translation.notify.enter_a_reason_for_the_translation_change_23f6bb0d")
                )
            values = {
                field: value for field, value in entered_values.items() if value
            }
            if not values:
                raise ValueError(
                    render_message("entity_translation_editor.status.enter_one")
                )
            return language, values, reason

    

        async def remove_entity_translation() -> None:
            language = language_control.value
            if not language or translation_state["loaded_language"] != language:
                ui.notify(render_message("webui.save_entity_translation.notify.load_the_selected_language_before_saving_dc2d8ba1"), color="warning")
                return
            reason_control = (
                get_external_reason()
                if uses_external_reason else translation_reason
            )
            reason = (reason_control.value or "").strip()
            if not reason:
                ui.notify(render_message("webui.save_entity_translation.notify.enter_a_reason_for_the_translation_change_23f6bb0d"), color="warning")
                return
            try:
                removed_translation = await api.update_entity_translation(
                    resource, row["id"], language,
                    {field: None for field in fields},
                    row["version"], reason,
                )
                row["version"] = removed_translation["version"]
                for control in translation_controls.values():
                    control.value = ""
                    control.update()
                reason_control.value = ""
                reason_control.update()
                translation_status.set_text(render_message("webui.remove_entity_translation.notify.translation_removed_09e85c43"))
                ui.notify(render_message("webui.remove_entity_translation.notify.translation_removed_09e85c43"), color="positive")
            except ApiError as error:
                show_api_error(error)

        with ui.row().classes("w-full justify-end gap-1"):
            ui.button(icon="refresh", on_click=load_entity_translation).props(
                "flat round dense"
            ).tooltip(render_message("webui.open_editor.tooltip.load_translation_d75ce604"))
            ui.button(icon="delete_outline", on_click=remove_entity_translation).props(
                "flat round dense color=negative"
            ).tooltip(render_message("webui.open_editor.tooltip.remove_translation_01e5d951"))

        language_control.on_value_change(
            lambda: background_tasks.create(load_entity_translation())
        )
        if language_control.value:
            await load_entity_translation()

    return pending_entity_translation
