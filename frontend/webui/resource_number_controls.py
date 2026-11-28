"""Explicit number suggestions, their provenance and stale-response protection."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from nicegui import ui

from .api_client import ApiError
from .i18n_catalogue import render_message


@dataclass
class NumberState:
    revision: int = 0
    origin: dict | None = None
    setting: bool = False
    busy: bool = False
    context: Callable | None = None
    active: Callable | None = None
    button: Any = None


def number_state(control) -> NumberState:
    state = getattr(control, "_creation_number_state", None)
    if state is None:
        state = NumberState()
        control._creation_number_state = state

        def edited(_):
            if not state.setting:
                state.revision += 1
                state.origin = None

        control.on_value_change(edited)
        # A client edit also counts when pasting the same text over a suggestion.
        control.on("update:model-value", edited)
    return state


def set_automatic_number(control, value, origin):
    state = number_state(control)
    state.revision += 1
    state.setting = True
    try:
        control.set_value(value)
    finally:
        state.setting = False
    state.origin = deepcopy(origin)


def generation_intent(controls):
    return {name: deepcopy(state.origin) for name, control in controls.items()
            if (state := getattr(control, "_creation_number_state", None)) is not None
            and state.origin is not None}


def numbers_busy(controls, busy):
    for control in controls.values():
        state = getattr(control, "_creation_number_state", None)
        if state is not None:
            state.busy = busy
            if busy:
                state.revision += 1
            if state.button is not None and not state.button.is_deleted:
                state.button.set_enabled(not busy)


@dataclass(frozen=True)
class NumberControls:
    add_number_suggestion: Callable
    show_number_conflict: Callable


def build_number_controls(api: Any, *, show_api_error: Callable[[ApiError], None]):
    def add_number_suggestion(control: Any, resource: str, controls: dict[str, Any],
                              *, creation_context=None, active=None) -> None:
        state = number_state(control)

        def selected_context() -> dict[str, Any]:
            parent_field = "aggregation_id" if resource == "records" else "parent_aggregation_id"
            parent = controls.get(parent_field)
            parent_id = parent.value if parent is not None else None
            result = {}
            if parent_id is not None:
                result["parent_aggregation_id"] = parent_id
            else:
                classification = controls.get("classification_id")
                if resource == "aggregations" and classification is not None and classification.value is not None:
                    result["classification_id"] = classification.value
            if creation_context is not None:
                result.update({key: value for key, value in creation_context().items() if value is not None})
            return result

        state.context = selected_context
        state.active = active

        def current():
            return not control.is_deleted and (state.active is None or state.active())

        async def suggest() -> None:
            if state.busy or not current():
                return
            context = selected_context()
            if not any(key in context for key in ("parent_aggregation_id", "classification_id")):
                ui.notify(render_message("webui.number_conflict.select_context"), color="warning")
                return
            revision = state.revision
            button.disable()
            try:
                result = await api.request("GET", f"/api/v1/number-suggestions/{resource}", params=context)
                if (current() and not state.busy and state.revision == revision
                        and selected_context() == context and result.get("suggested_number")):
                    set_automatic_number(control, result["suggested_number"],
                                         result.get("generation_intent") or {"source": "legacy"})
            except ApiError as error:
                if current() and state.revision == revision:
                    show_api_error(error)
            finally:
                if current() and not state.busy:
                    button.enable()

        with control.add_slot("append"):
            button = ui.button(render_message("webui.number_conflict.suggest"), icon="auto_fix_high", on_click=suggest).props("flat dense no-caps")
        state.button = button

    async def show_number_conflict(error: ApiError, resource: str, control: Any, *, root: bool = False) -> bool:
        if not isinstance(error.detail, dict) or error.detail.get("code") not in {
            "duplicate_resource_number", "code_generator_recommendation_conflict",
        }:
            return False
        state = number_state(control)
        revision = state.revision
        context = state.context() if state.context is not None else {}

        def current():
            return (not control.is_deleted and state.revision == revision
                    and (state.active is None or state.active())
                    and (state.context is None or state.context() == context))

        attempted = str(control.value or "")
        result = {}
        try:
            result = await api.request("GET", f"/api/v1/number-suggestions/{resource}",
                                       params={"number": attempted, "root": root, **context})
        except ApiError:
            pass
        if not current():
            return True
        suggestion = result.get("suggested_number")
        with ui.dialog() as conflict_dialog, ui.card().classes("w-[520px] max-w-full"):
            message = (render_message("code_generation.error.recommendation_conflict")
                       if error.detail.get("code") == "code_generator_recommendation_conflict"
                       else render_message("webui.number_conflict.duplicate", number=attempted))
            ui.label(message).classes("text-lg font-semibold")
            if suggestion:
                ui.label(render_message("webui.number_conflict.suggestion", number=suggestion))
                ui.label(render_message("webui.number_conflict.not_reserved")).classes("text-sm text-slate-500")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.number_conflict.close"), on_click=conflict_dialog.close).props("flat")
                if suggestion:
                    def use_suggestion() -> None:
                        if current() and not state.busy:
                            set_automatic_number(control, suggestion,
                                                 result.get("generation_intent") or {"source": "legacy"})
                        conflict_dialog.close()
                    ui.button(render_message("webui.number_conflict.use"), on_click=use_suggestion).props("unelevated")
        conflict_dialog.open()
        return True

    return NumberControls(add_number_suggestion, show_number_conflict)
