"""Shared, direction-aware three-stage retention presentation."""
from calendar import monthrange
from datetime import date, datetime
from typing import Any, Callable

from nicegui import ui

from .i18n_catalogue import render_message
from .locale_services import format_instant, format_local_date, utc_instant_to_working
from .disposition.messages import status_label


def disposition_dates(
    rule: dict[str, Any], governing_root: dict[str, Any] | None, timezone_name: str,
) -> tuple[date, date] | None:
    """Return closure and calculated disposition dates for the root disposition unit."""
    if not governing_root or not governing_root.get("date_closed"):
        return None
    periods = (rule.get("current_period_years"), rule.get("intermediate_period_years"))
    if any(type(period) is not int or period < 0 for period in periods):
        return None
    try:
        instant = governing_root["date_closed"]
        if isinstance(instant, str):
            instant = datetime.fromisoformat(instant.replace("Z", "+00:00"))
        closed = utc_instant_to_working(instant, timezone_name).date()
        year = closed.year + sum(periods)
        due = closed.replace(year=year, day=min(closed.day, monthrange(year, closed.month)[1]))
    except (ValueError, TypeError, OverflowError):
        return None
    return closed, due


def render_disposition_date(
    rule: dict[str, Any], governing_root: dict[str, Any] | None,
    language: str, timezone_name: str,
) -> None:
    acceleration = rule.get("acceleration")
    if acceleration:
        with ui.row().classes("detail-action-row w-full items-start gap-3 rounded-lg bg-blue-50 p-4"):
            ui.icon("event_available", color="primary").classes("text-2xl")
            with ui.column().classes("min-w-0 gap-1"):
                ui.label(render_message("webui.open_aggregation.retention.accelerated_on", date=format_instant(
                    acceleration["occurred_at"], timezone_name, language,
                ))).classes("text-base font-semibold text-slate-900")
                if governing_root and governing_root.get("disposition_status"):
                    ui.label(status_label(governing_root["disposition_status"])).classes("text-sm font-semibold text-slate-800")
                if acceleration.get("actor_name"):
                    with ui.row().classes("detail-action-row items-baseline gap-1"):
                        ui.label(render_message("webui.open_aggregation.retention.accelerated_by"))
                        ui.label(acceleration["actor_name"])
                if acceleration.get("reason"):
                    ui.label(render_message("webui.open_aggregation.retention.acceleration_reason")).classes("text-sm font-semibold")
                    ui.label(acceleration["reason"]).classes("w-full whitespace-pre-wrap break-words")
                ui.label(render_message("webui.open_aggregation.retention.acceleration_effect")).classes("text-sm text-slate-600")
    dates = disposition_dates(rule, governing_root, timezone_name)
    if dates is None:
        return
    closed, due = dates
    with ui.row().classes("detail-action-row w-full items-start gap-3 rounded-lg bg-blue-50 p-4"):
        ui.icon("event", color="primary").classes("text-2xl")
        with ui.column().classes("min-w-0 gap-1"):
            ui.label(render_message(
                "webui.open_aggregation.retention.normal_disposition_date" if acceleration
                else "webui.open_aggregation.retention.calculated_disposition_date"
            )).classes("text-sm font-semibold text-slate-800")
            ui.label(format_local_date(due, language)).classes("text-xl font-semibold text-slate-900")
            with ui.row().classes("detail-action-row items-baseline gap-1 text-xs text-slate-500"):
                ui.label(render_message("entity_metadata.field.date_closed"))
                ui.label(format_local_date(closed, language))


def render_retention_stages(rule: dict[str, Any], disposition_label: Callable) -> None:
    # Reuse the aggregation page's established stage layout and RTL rules.
    stages = (
        (render_message("entity_metadata.field.current_retention_years"),
         render_message("common.duration.years", count=rule["current_period_years"]),
         render_message("webui.open_aggregation.retention.business_unit")),
        (render_message("entity_metadata.field.intermediate_retention_years"),
         render_message("common.duration.years", count=rule["intermediate_period_years"]),
         render_message("webui.open_aggregation.retention.records_storage")),
        (render_message("entity_metadata.field.final_disposition"),
         disposition_label(rule["final_disposition"]),
         render_message("entity_metadata.field.final_disposition")),
    )
    with ui.element("div").classes("aggregation-retention-stages w-full"):
        for label, value, help_text in stages:
            with ui.column().classes("aggregation-retention-stage gap-0"):
                ui.label(render_message(
                    "webui.open_aggregation.label.stage_label_stage_value_026d5c3a",
                    stage_label=label, stage_value=value,
                )).classes("w-full text-sm font-semibold text-slate-800")
                ui.label(help_text).classes("w-full text-xs text-slate-500")
