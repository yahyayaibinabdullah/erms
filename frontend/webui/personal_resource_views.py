"""Existing favourites/recent layouts with explicit destination callbacks."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from nicegui import ui
from .api_client import ApiError
from .entities import EntitySpec
from .config import dashboard_favourite_item_limit
from .i18n_catalogue import render_message
from .personal_resources import PersonalResourceState, STOP_PROPAGATION_CLICK_HANDLER

@dataclass(frozen=True)
class PersonalResourceViews:
    render_entity_favourites_section: Callable
    render_resource_personal_sections: Callable

def build_personal_resource_views(api: Any, personal: PersonalResourceState, *,
    get_configuration: Callable, render_table: Callable, open_aggregation: Callable,
    show_record_details: Callable, toggle_favourite: Callable,
    error_message: Callable, format_timestamp: Callable, personal_dialog_list_height: Callable):
    def render_entity_favourites_section(spec: EntitySpec) -> None:
        preview_host = ui.column().classes("w-full px-5 pt-5")
        limit = dashboard_favourite_item_limit(get_configuration())
        resource = spec.key
        singular = "aggregation" if resource == "aggregations" else "record"
        localized_singular = render_message(
            "dashboard.resource.aggregation" if resource == "aggregations" else "dashboard.resource.record"
        )
        localized_plural = render_message(
            "navigation.item.aggregations" if resource == "aggregations" else "navigation.item.records"
        )
        heading = render_message("webui.render_entity_favourites_section.text.favourite_resource_e60851b2", resource=localized_plural)
        icon = "folder" if resource == "aggregations" else "description"

        async def open_favourite(item: dict[str, Any]) -> None:
            try:
                entity = await api.get(resource, item["id"])
                if resource == "aggregations":
                    await open_aggregation(entity)
                else:
                    await show_record_details(entity)
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)

        def render_entry(item: dict[str, Any], *, after_remove: Any) -> None:
            row = ui.element("div").classes("dashboard-personal-item").props(
                "role=button tabindex=0"
            ).on("click", lambda _, selected=item: open_favourite(selected)).on(
                "keydown.enter", lambda _, selected=item: open_favourite(selected)
            )
            with row:
                with ui.element("div").classes("dashboard-overview-icon"):
                    ui.icon(icon, size="18px")
                with ui.column().classes("gap-0 grow min-w-0"):
                    ui.label(item["title"]).classes(
                        "text-sm font-semibold text-slate-700 truncate w-full"
                    ).tooltip(item["title"])
                    number = item.get("aggregation_number") or item.get("record_number")
                    ui.label(render_message("webui.render_entry.label.title_value_32d79d0d", title=localized_singular, value=number or '—')).classes(
                        "text-xs text-slate-500 truncate w-full"
                    )
                remove_button = ui.button(icon="favorite", color="red").props(
                    'flat round dense aria-label=' + repr(render_message("webui.render_entry.accessible_name.remove_from_favourites_5fa138ab"))
                )
                remove_button.tooltip(render_message("webui.render_entry.tooltip.remove_from_favourites_84f9ea27"))
                remove_button.on(
                    "click", lambda _, selected=item: after_remove(selected),
                    js_handler=STOP_PROPAGATION_CLICK_HANDLER,
                )

        def show_all() -> None:
            dialog = ui.dialog()
            with dialog, ui.card().classes(
                "dashboard-personal-dialog w-[760px] max-w-full max-h-[85vh]"
            ):
                with ui.row().classes("w-full items-center"):
                    ui.label(heading).classes("text-xl font-semibold")
                    ui.space()
                    ui.button(icon="close", on_click=dialog.close).props("flat round")
                complete_host = (
                    ui.scroll_area()
                    .classes("dashboard-personal-dialog-list")
                    .props("visible")
                    .style(
                        f"height:min(65vh,{personal_dialog_list_height(len(personal.favourites[resource]))}px)"
                    )
                )

            def render_complete() -> None:
                complete_host.clear()
                with complete_host:
                    items = personal.favourites[resource]
                    if not items:
                        ui.label(render_message("webui.render_complete.label.no_favourite_resource_5a366cf8", resource=localized_plural)).classes("text-sm text-slate-400 py-4")
                    for item in items:
                        render_entry(
                            item,
                            after_remove=lambda selected: remove_favourite(
                                selected, refresh_dialog=render_complete,
                            ),
                        )

            render_complete()
            dialog.open()

        async def remove_favourite(
            item: dict[str, Any], *, refresh_dialog: Any | None = None,
        ) -> None:
            selected = await toggle_favourite(resource, item["id"])
            if selected:
                return
            personal.favourites[resource] = [
                row for row in personal.favourites[resource]
                if int(row["id"]) != int(item["id"])
            ]
            render_table(spec)
            if refresh_dialog is not None:
                refresh_dialog()

        def render_preview() -> None:
            preview_host.clear()
            items = personal.favourites[resource]
            with preview_host:
                with ui.card().classes("dashboard-personal-panel w-full"):
                    with ui.row().classes("dashboard-personal-header w-full items-center gap-2"):
                        ui.icon("favorite_border", color="primary", size="19px")
                        ui.label(heading).classes("font-semibold text-slate-800")
                        ui.badge(str(len(items)), color="blue-grey").props("outline")
                        ui.space()
                        if len(items) > limit:
                            ui.button(render_message("webui.render_preview.button.view_all_39d201d6"), on_click=show_all).props(
                                "flat dense no-caps color=primary"
                            )
                    if not items:
                        ui.label(render_message("webui.render_preview.label.no_favourite_resource_2e245f47", resource=localized_plural)).classes("text-sm text-slate-500 p-4")
                    else:
                        for item in items[:limit]:
                            render_entry(item, after_remove=remove_favourite)

        render_preview()


    def render_resource_personal_sections(
        spec: EntitySpec, *, container: Any | None = None,
    ) -> None:
        """Render resource favourites and activity using the Dashboard treatment."""
        limit = dashboard_favourite_item_limit(get_configuration())
        resource = spec.key
        icon = "folder" if resource == "aggregations" else "description"
        number_field = "aggregation_number" if resource == "aggregations" else "record_number"
        favourite_items = personal.favourites[resource]
        recent_items = sorted(
            personal.recent_activity,
            key=lambda item: str(item.get("_activity_at") or ""),
            reverse=True,
        )
        personal_loading = bool(
            personal.personal_sections_loading.get(resource)
        )

        async def open_resource(item: dict[str, Any]) -> None:
            try:
                entity = await api.get(resource, item["id"])
                if resource == "aggregations":
                    await open_aggregation(entity)
                else:
                    await show_record_details(entity)
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)

        def render_favourite_item(item: dict[str, Any]) -> None:
            row = ui.element("div").classes("dashboard-personal-item").props(
                "role=button tabindex=0"
            ).on(
                "click", lambda _, selected=item: open_resource(selected),
            ).on(
                "keydown.enter", lambda _, selected=item: open_resource(selected),
            )
            with row:
                with ui.element("div").classes("dashboard-overview-icon"):
                    ui.icon(icon, size="18px")
                with ui.column().classes("gap-0 grow min-w-0"):
                    ui.label(item["title"]).classes(
                        "text-sm font-semibold text-slate-700 truncate w-full"
                    ).tooltip(item["title"])
                    ui.label(
                        render_message("webui.render_favourite_item.label.title_value_e1a0d09d", title=localized_singular, value=item.get(number_field) or '—')
                    ).classes("text-xs text-slate-500 truncate w-full")
                remove_button = ui.button(icon="favorite", color="red").props(
                    'flat round dense aria-label=' + repr(render_message("webui.render_favourite_item.accessible_name.remove_from_favourites_89be972a"))
                )
                remove_button.tooltip(render_message("webui.render_favourite_item.tooltip.remove_from_favourites_96304e80"))
                remove_button.on(
                    "click", lambda _, selected=item: remove_favourite(selected),
                    js_handler=STOP_PROPAGATION_CLICK_HANDLER,
                )

        def render_recent_item(item: dict[str, Any]) -> None:
            operation = item["_operation"]
            activity_label, activity_icon, activity_class = {
                "CREATE": (render_message("dashboard.activity.created"), "add", "dashboard-activity-created"),
                "UPDATE": (render_message("dashboard.activity.updated"), "edit", "dashboard-activity-updated"),
                "CONTENT_VIEWED": (render_message("dashboard.activity.viewed"), "visibility", "dashboard-activity-viewed"),
            }[operation]
            row = ui.element("div").classes("dashboard-personal-item").props(
                "role=button tabindex=0"
            ).on(
                "click", lambda _, selected=item: open_resource(selected),
            ).on(
                "keydown.enter", lambda _, selected=item: open_resource(selected),
            )
            with row:
                with ui.element("div").classes("dashboard-overview-icon"):
                    ui.icon(icon, size="18px")
                with ui.column().classes("gap-0 grow min-w-0"):
                    ui.label(item["title"]).classes(
                        "text-sm font-semibold text-slate-700 truncate w-full"
                    ).tooltip(item["title"])
                    ui.label(
                        render_message("webui.render_recent_item.label.value_format_timestamp_2d04c976", value=item.get(number_field) or '—', format_timestamp=format_timestamp(item.get('_activity_at')))
                    ).classes("text-xs text-slate-500 truncate w-full")
                with ui.element("div").classes(
                    f"dashboard-activity-badge {activity_class}"
                ):
                    ui.icon(activity_icon, size="13px")
                    ui.label(activity_label)

        async def remove_favourite(item: dict[str, Any]) -> None:
            selected = await toggle_favourite(resource, item["id"])
            if selected:
                return
            personal.favourites[resource] = [
                row for row in personal.favourites[resource]
                if int(row["id"]) != int(item["id"])
            ]
            render_table(spec)

        def show_all_favourites() -> None:
            dialog = ui.dialog()
            with dialog, ui.card().classes(
                "dashboard-personal-dialog w-[760px] max-w-full max-h-[85vh]"
            ):
                with ui.row().classes("w-full items-center"):
                    ui.label(render_message("webui.show_all_favourites.label.favourite_resource_e9e7ec57", resource=localized_plural)).classes("text-xl font-semibold")
                    ui.space()
                    ui.button(icon="close", on_click=dialog.close).props("flat round")
                with (
                    ui.scroll_area()
                    .classes("dashboard-personal-dialog-list")
                    .props("visible")
                    .style(f"height:min(65vh,{personal_dialog_list_height(len(favourite_items))}px)")
                ):
                    if not favourite_items:
                        ui.label(render_message("webui.show_all_favourites.label.no_favourite_resource_6427b546", resource=localized_plural)).classes("text-sm text-slate-400 p-4")
                    for item in favourite_items:
                        render_favourite_item(item)
            dialog.open()

        def show_all_recent() -> None:
            dialog = ui.dialog()
            with dialog, ui.card().classes(
                "dashboard-personal-dialog w-[820px] max-w-full max-h-[85vh]"
            ):
                with ui.row().classes("w-full items-center"):
                    ui.label(render_message("webui.show_all_recent.label.recent_singular_activity_2b35eaf4", singular=localized_singular)).classes("text-xl font-semibold")
                    ui.space()
                    ui.button(icon="close", on_click=dialog.close).props("flat round")
                with (
                    ui.scroll_area()
                    .classes("dashboard-personal-dialog-list")
                    .props("visible")
                    .style(f"height:min(65vh,{personal_dialog_list_height(len(recent_items))}px)")
                ):
                    if not recent_items:
                        ui.label(render_message("webui.show_all_recent.label.no_recent_singular_activity_9108240b", singular=localized_singular)).classes("text-sm text-slate-400 p-4")
                    for item in recent_items:
                        render_recent_item(item)
            dialog.open()

        personal_host = container
        if personal_host is None:
            personal_host = ui.element("div").classes("w-full")
            personal.personal_section_hosts[resource] = personal_host
        personal_host.clear()
        with personal_host, ui.element("div").classes("dashboard-personal-columns w-full px-5 pt-5 pb-5"):
            # Deferred refreshes run in a background task. Resolve nested
            # localized values only after entering the retained UI container,
            # where NiceGUI has restored the owning client's locale context.
            localized_singular = render_message(
                "dashboard.resource.aggregation"
                if resource == "aggregations"
                else "dashboard.resource.record"
            )
            localized_plural = render_message(
                "navigation.item.aggregations"
                if resource == "aggregations"
                else "navigation.item.records"
            )
            with ui.card().classes("dashboard-personal-panel"):
                with ui.row().classes("dashboard-personal-header w-full items-center gap-2"):
                    ui.icon("favorite_border", color="primary", size="19px")
                    ui.label(render_message("webui.render_resource_personal_sections.label.favourite_resource_c0cb6542", resource=localized_plural)).classes("font-semibold text-slate-800")
                    ui.badge(str(len(favourite_items)), color="blue-grey").props("outline")
                    ui.space()
                    ui.button(render_message("webui.render_resource_personal_sections.button.view_all_a52a6926"), on_click=show_all_favourites).props(
                        "flat dense no-caps color=primary"
                    )
                if not favourite_items:
                    if personal_loading:
                        with ui.row().classes("w-full items-center gap-2 p-4 text-slate-500"):
                            ui.spinner("dots", size="20px")
                            ui.label(render_message("common.status.loading"))
                    else:
                        ui.label(render_message("webui.render_resource_personal_sections.label.no_favourite_resource_5a26f58b", resource=localized_plural)).classes("text-sm text-slate-500 p-4")
                for item in favourite_items[:limit]:
                    render_favourite_item(item)
            with ui.card().classes("dashboard-personal-panel"):
                with ui.row().classes("dashboard-personal-header w-full items-center gap-2"):
                    ui.icon("history", color="primary", size="19px")
                    ui.label(render_message("webui.render_resource_personal_sections.label.recent_singular_activity_4bf70ea7", singular=localized_singular)).classes("font-semibold text-slate-800")
                    ui.space()
                    ui.button(render_message("webui.render_resource_personal_sections.button.view_all_a52a6926"), on_click=show_all_recent).props(
                        "flat dense no-caps color=primary"
                    )
                if not recent_items:
                    if personal_loading:
                        with ui.row().classes("w-full items-center gap-2 p-4 text-slate-500"):
                            ui.spinner("dots", size="20px")
                            ui.label(render_message("common.status.loading"))
                    else:
                        ui.label(render_message("webui.render_resource_personal_sections.label.no_recent_singular_activity_750e055d", singular=localized_singular)).classes("text-sm text-slate-500 p-4")
                for item in recent_items[:limit]:
                    render_recent_item(item)

    return PersonalResourceViews(render_entity_favourites_section, render_resource_personal_sections)

