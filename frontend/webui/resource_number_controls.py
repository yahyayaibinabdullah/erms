"""Number suggestions and conflict feedback shared by resource editors."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message

@dataclass(frozen=True)
class NumberControls:
    add_number_suggestion: Callable
    show_number_conflict: Callable

def build_number_controls(api: Any, *, show_api_error: Callable[[ApiError], None]):
    def add_number_suggestion(control: Any, resource: str, controls: dict[str, Any]) -> None:
        def selected_context() -> dict[str, Any]:
            parent_field = "aggregation_id" if resource == "records" else "parent_aggregation_id"
            parent = controls.get(parent_field)
            parent_id = parent.value if parent is not None else None
            if parent_id is not None:
                return {"parent_aggregation_id": parent_id}
            classification = controls.get("classification_id")
            if resource == "aggregations" and classification is not None and classification.value is not None:
                return {"classification_id": classification.value}
            return {}

        async def suggest() -> None:
            context = selected_context()
            if not context:
                ui.notify(render_message("webui.number_conflict.select_context"), color="warning")
                return
            button.disable()
            original = control.value
            try:
                result = await api.request("GET", f"/api/v1/number-suggestions/{resource}", params=context)
                if selected_context() == context and control.value == original and result.get("suggested_number"):
                    control.set_value(result["suggested_number"])
            except ApiError as error:
                show_api_error(error)
            finally:
                button.enable()

        with control.add_slot("append"):
            button = ui.button(render_message("webui.number_conflict.suggest"), icon="auto_fix_high", on_click=suggest).props("flat dense no-caps")


    async def show_number_conflict(error: ApiError, resource: str, control: Any, *, root: bool = False) -> bool:
        if not isinstance(error.detail, dict) or error.detail.get("code") != "duplicate_resource_number":
            return False
        attempted = str(control.value or "")
        suggestion = None
        try:
            result = await api.request("GET", f"/api/v1/number-suggestions/{resource}", params={"number": attempted, "root": root})
            suggestion = result.get("suggested_number")
        except ApiError:
            pass  # The duplicate message remains useful if suggestion lookup fails.
        with ui.dialog() as conflict_dialog, ui.card().classes("w-[520px] max-w-full"):
            ui.label(render_message("webui.number_conflict.duplicate", number=attempted)).classes("text-lg font-semibold")
            if suggestion:
                ui.label(render_message("webui.number_conflict.suggestion", number=suggestion))
                ui.label(render_message("webui.number_conflict.not_reserved")).classes("text-sm text-slate-500")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.number_conflict.close"), on_click=conflict_dialog.close).props("flat")
                if suggestion:
                    def use_suggestion() -> None:
                        control.set_value(suggestion)
                        conflict_dialog.close()
                    ui.button(render_message("webui.number_conflict.use"), on_click=use_suggestion).props("unelevated")
        conflict_dialog.open()
        return True

    return NumberControls(add_number_suggestion, show_number_conflict)

