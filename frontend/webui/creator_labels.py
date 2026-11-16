"""Optional creator attribution shared by resource listings."""

from nicegui import ui

from .i18n_catalogue import render_message


def creator_text(item):
    name = item.get("created_by")
    return render_message("resource_details.created_by", name=name) if name else ""


def render_creator_name(item) -> None:
    if text := creator_text(item):
        ui.label(text).classes("resource-created-by min-w-0 text-xs text-slate-600 whitespace-normal break-words").props("dir=auto")
