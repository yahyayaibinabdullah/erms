"""Page-scoped recent child records, using the existing batched activity projection."""
from datetime import datetime, timedelta, timezone

from nicegui import ui

from .api_client import ApiError
from .config import dashboard_recent_days, dashboard_recent_item_limit
from .i18n_catalogue import render_message
from .personal_resource_views import render_recent_activity_item


class AggregationRecentActivity:
    def __init__(self, *, api, aggregation_id, active, configuration,
                 format_timestamp, show_record_details, error_message):
        self.api, self.aggregation_id, self.active = api, aggregation_id, active
        self.configuration, self.format_timestamp = configuration, format_timestamp
        self.show_record_details, self.error_message = show_record_details, error_message
        # Snapshot belongs only to this mounted page/principal/language. Refresh
        # on mount, creation and successful preview; stale or abandoned replies are discarded.
        self.items = []
        self.serial = 0
        self.host = ui.card().classes("dashboard-personal-panel w-full min-w-0")
        with self.host:
            with ui.row().classes("dashboard-personal-header w-full items-center gap-2", remove="row"):
                ui.icon("history", color="primary", size="19px")
                ui.label(render_message("aggregation_file_drop.recent_activity")).classes("font-semibold text-slate-800")
                ui.space()
                self.view_all = ui.button(
                    render_message("webui.render_resource_personal_sections.button.view_all_a52a6926"),
                    on_click=self.show_all,
                ).props("flat dense no-caps color=primary")
                self.view_all.disable()
            self.body = ui.column().classes("w-full gap-0")
            with self.body:
                ui.spinner("dots", size="20px")

    async def open_record(self, item):
        if not self.active():
            return
        try:
            record = await self.api.get("records", item["id"])
            if self.active():
                await self.show_record_details(record)
        except ApiError as error:
            if self.active():
                ui.notify(self.error_message(error), color="negative", close_button=True)

    def render_items(self, items):
        if not items:
            ui.label(render_message("aggregation_file_drop.no_activity")).classes("text-sm text-slate-500 p-4")
        for item in items:
            render_recent_activity_item(item, icon="description", number_field="record_number",
                                        open_resource=self.open_record, format_timestamp=self.format_timestamp)

    def show_all(self):
        if not self.active():
            return
        dialog = ui.dialog()
        with dialog, ui.card().classes("dashboard-personal-dialog w-[820px] max-w-full max-h-[85vh]"):
            with ui.row().classes("w-full items-center", remove="row"):
                ui.label(render_message("aggregation_file_drop.recent_activity")).classes("text-xl font-semibold")
                ui.space()
                ui.button(icon="close", on_click=dialog.close).props("flat round")
            with ui.scroll_area().classes("w-full").style("height:65vh"):
                self.render_items(self.items)
        dialog.open()

    async def load(self):
        if not self.active():
            return
        self.serial += 1
        serial = self.serial
        try:
            items = await self.api.recent_resource_activity(
                "records", aggregation_id=self.aggregation_id, limit=50,
                since=datetime.now(timezone.utc) - timedelta(days=dashboard_recent_days(self.configuration)),
            )
        except ApiError:
            if self.active() and serial == self.serial:
                self.items = []
                self.view_all.disable()
                self.body.clear()
                with self.body:
                    ui.label(render_message("resource_details.list_unavailable"))
                    ui.button(render_message("resource_details.retry"), on_click=self.load).props("flat no-caps")
            return
        if not self.active() or serial != self.serial:
            return
        self.items = items
        self.body.clear()
        self.view_all.enable()
        with self.body:
            self.render_items(items[:dashboard_recent_item_limit(self.configuration)])
