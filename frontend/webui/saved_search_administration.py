"""Saved-query administration, filters, paging and reasoned deletion."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from .i18n_catalogue import render_message
from nicegui import ui

def build_saved_search_administration(
    *, add_button, add_record_button, advanced_search_state, aggregation_mode_bar, aggregation_state, api, collection_state, enter_saved_administration, error_message, format_timestamp, get_principal, get_resource, guidance, register_navigation, search_bar, select_advanced_search, show_authenticated_view, subtitle, table_container, title,
):
    async def select_saved_search_administration() -> None:
        privileges = set((get_principal() or {}).get("global_privileges", []))
        if "search.saved_search.administer" not in privileges:
            ui.notify(error_message(ApiError(403, "insufficient_privilege")), color="negative")
            return
        page_key = "saved-search-administration"
        page_label = render_message("privilege.search.saved_search.administrator.name")
        register_navigation(page_key, page_label)
        show_authenticated_view()
        enter_saved_administration(page_key); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
        title.text = page_label
        subtitle.text = render_message("privilege.search.saved_search.administrator.description")
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        table_container.clear()
        page = {"offset": 0, "limit": 25, "total": 0, "revision": 0}

        with table_container, ui.column().classes("w-full gap-4 p-4"):
            with ui.card().classes("w-full shadow-none border border-slate-200 p-4 gap-3"):
                with ui.row().classes("w-full gap-3 items-end flex-wrap"):
                    name_filter = ui.input(
                        render_message("webui.open_saved_search_dialog.input.search_saved_searches_3352fa10")
                    ).props("outlined dense clearable").classes("grow min-w-64")
                    owner_filter = ui.input(
                        render_message("saved_search.administration.filter.owner")
                    ).props("outlined dense clearable").classes("grow min-w-56")
                    created_from = ui.input(
                        render_message("saved_search.administration.filter.created_from")
                    ).props("outlined dense type=datetime-local clearable").classes("w-52")
                    created_before = ui.input(
                        render_message("saved_search.administration.filter.created_before")
                    ).props("outlined dense type=datetime-local clearable").classes("w-52")
                    apply_filters = ui.button(
                        render_message("webui.open_saved_search_dialog.button.apply_filters_63a71659"),
                        icon="filter_alt",
                    ).props("outline dense no-caps")
            list_host = ui.column().classes("w-full gap-3")
            with ui.row().classes("w-full items-center justify-center gap-2"):
                previous = ui.button(
                    render_message("webui.open_saved_search_dialog.button.previous_f6a88eee"), icon="chevron_left",
                ).props("flat no-caps")
                range_label = ui.label().classes("text-sm text-slate-500")
                following = ui.button(
                    render_message("webui.open_saved_search_dialog.button.next_ba38d6aa"), icon="chevron_right",
                ).props("flat no-caps")

        async def edit_saved_search(item: dict[str, Any]) -> None:
            advanced_search_state["admin_saved_search_id"] = int(item["id"])
            await select_advanced_search()

        async def delete_administered_search(item: dict[str, Any]) -> None:
            with ui.dialog() as dialog, ui.card().classes("w-[520px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.delete_saved_search.label.delete_name_3f400e6a", name=item["name"])).classes("text-lg font-semibold")
                ui.label(render_message("webui.delete_saved_search.label.this_permanently_deletes_the_saved_query_d_a0cf4b5a")).classes("text-sm text-slate-600")
                reason = ui.textarea(render_message("webui.delete_saved_search.textarea.reason_for_deletion_5aca706a")).props("outlined maxlength=500 autogrow").classes("w-full")
                error_label = ui.label().classes("text-sm text-negative")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.delete_saved_search.button.cancel_9711f5b2"), on_click=dialog.close).props("flat no-caps")
                    confirm = ui.button(render_message("webui.delete_saved_search.button.delete_saved_search_226c4222"), color="negative", icon="delete").props("unelevated no-caps")
                async def remove() -> None:
                    if not str(reason.value or "").strip():
                        error_label.text = render_message("webui.remove.text.a_reason_is_required_0adbb4d3")
                        return
                    try:
                        await api.delete_saved_search(int(item["id"]), int(item["version"]), str(reason.value).strip())
                    except ApiError as error:
                        error_label.text = error_message(error)
                        return
                    dialog.close()
                    await load_page()
                confirm.on("click", remove)
            dialog.open()

        async def load_page() -> None:
            page["revision"] += 1
            revision = page["revision"]
            params: dict[str, Any] = {"limit": page["limit"], "offset": page["offset"]}
            if str(name_filter.value or "").strip(): params["q"] = str(name_filter.value).strip()
            if str(owner_filter.value or "").strip(): params["owner_q"] = str(owner_filter.value).strip()
            if created_from.value: params["created_from"] = created_from.value
            if created_before.value: params["created_before"] = created_before.value
            try:
                result = await api.saved_search_administration(**params)
            except ApiError as error:
                if revision != page["revision"] or get_resource() != page_key: return
                list_host.clear()
                with list_host: ui.label(error_message(error)).classes("text-negative")
                return
            if revision != page["revision"] or get_resource() != page_key: return
            page["total"] = int(result["total"])
            list_host.clear()
            with list_host:
                if not result["items"]:
                    ui.label(render_message("webui.load_saved_page.label.no_saved_searches_match_these_filters_83501f8d")).classes("w-full text-center text-slate-500 py-8")
                for item in result["items"]:
                    owner = item.get("owner") or {}
                    with ui.card().classes("w-full shadow-none border border-slate-200 p-4"):
                        with ui.row().classes("w-full items-start gap-3 no-wrap"):
                            ui.icon("description" if item["resource_type"] == "record" else "folder", color="primary")
                            with ui.column().classes("gap-1 grow min-w-0"):
                                ui.label(item["name"]).classes("font-semibold")
                                ui.label(item.get("description") or render_message("webui.load_saved_page.label.no_description_e23ca0ad")).classes("text-sm text-slate-600")
                                ui.label((owner.get("localized") or {}).get("name") or owner.get("name") or owner.get("email") or "—").classes("text-xs text-slate-500")
                                ui.label(format_timestamp(item.get("date_created"))).classes("text-xs text-slate-500")
                            ui.button(icon="edit", on_click=lambda _, selected=item: edit_saved_search(selected)).props("flat round color=primary")
                            if (item.get("capabilities") or {}).get("delete") is True:
                                ui.button(icon="delete", color="negative", on_click=lambda _, selected=item: delete_administered_search(selected)).props("flat round")
            start = page["offset"] + 1 if result["items"] else 0
            range_label.text = render_message("webui.load_saved_page.text.start_value_of_total_eed8d817", start=start, value=page["offset"] + len(result["items"]), total=page["total"])
            previous.set_enabled(page["offset"] > 0)
            following.set_enabled(page["offset"] + page["limit"] < page["total"])

        async def apply_page_filters() -> None:
            page["offset"] = 0
            await load_page()
        async def move_page(delta: int) -> None:
            page["offset"] = max(0, page["offset"] + delta)
            await load_page()
        apply_filters.on("click", apply_page_filters)
        name_filter.on("keydown.enter", apply_page_filters)
        owner_filter.on("keydown.enter", apply_page_filters)
        previous.on("click", lambda: move_page(-page["limit"]))
        following.on("click", lambda: move_page(page["limit"]))
        await load_page()


    return select_saved_search_administration
