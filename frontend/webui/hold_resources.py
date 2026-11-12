"""Existing legal-hold behavior with explicit feature dependencies."""
from __future__ import annotations
import asyncio
from typing import Any
from nicegui import background_tasks, ui
from .api_client import ApiError
from .i18n_catalogue import render_message


def build_hold_resources(
    *, api, select_hold_details, open_aggregation, hold_reason_dialog, error_message,
):
    async def add_resource_to_hold_dialog(resource_type: str, resource_id: int, refresh_page: Any) -> None:
        dialog = ui.dialog()
        paging = {"offset": 0, "limit": 25, "total": 0, "query": None, "revision": 0, "loading": False}
        known_holds: dict[int, str] = {}
        with dialog, ui.card().classes("w-[520px] max-w-full"):
            ui.label(render_message("webui.add_resource_to_hold_dialog.label.add_to_hold_057d6b79")).classes("text-xl font-semibold")
            hold_query = ui.input(
                render_message("webui.select_holds.input.search_code_or_name_79d187ac")
            ).props("outlined dense clearable debounce=300").classes("w-full")
            selected = ui.select({}, label=render_message("webui.add_resource_to_hold_dialog.select.hold_77a90801"), with_input=True).props("outlined use-input options-dense").classes("w-full")
            with ui.row().classes("w-full items-center gap-2"):
                hold_status = ui.label().classes("text-xs text-slate-500 grow")
                previous_hold_page = ui.button(icon="chevron_left").props("flat round dense")
                next_hold_page = ui.button(icon="chevron_right").props("flat round dense")
            reason = ui.textarea(render_message("webui.add_resource_to_hold_dialog.textarea.reason_cd1ea4c6")).props("outlined autogrow maxlength=2000").classes("w-full")

            async def load_hold_page(offset: int, query: str | None) -> None:
                if dialog.is_deleted or not dialog.value:
                    return
                paging["revision"] += 1
                revision = paging["revision"]
                paging["loading"] = True
                def request_is_current() -> bool:
                    return revision == paging["revision"] and not dialog.is_deleted and dialog.value
                try:
                    result = await api.holds_page(q=query, limit=paging["limit"], offset=offset)
                except ApiError as error:
                    if request_is_current():
                        ui.notify(error_message(error), color="negative", close_button=True)
                    return
                finally:
                    if revision == paging["revision"]:
                        paging["loading"] = False
                if not request_is_current():
                    return
                manageable = [
                    item for item in result["items"]
                    if item.get("capabilities", {}).get("manage_held_items")
                ]
                paging.update(offset=offset, query=query, total=int(result["total"]))
                for item in manageable:
                    known_holds[int(item["id"])] = f"{item['code']} — {item['name']}"
                selected.options = dict(known_holds)
                selected.update()
                start = paging["offset"] + 1 if result["items"] else 0
                end = paging["offset"] + len(result["items"])
                hold_status.text = render_message("webui.load_hold_page.text.start_end_total_42ef8de2", start=start, end=end, total=paging['total'])
                previous_hold_page.set_enabled(paging["offset"] > 0)
                next_hold_page.set_enabled(end < paging["total"])

            async def move_hold_page(direction: int) -> None:
                offset = paging["offset"] + direction * paging["limit"]
                if not paging["loading"] and 0 <= offset < paging["total"]:
                    await load_hold_page(offset, paging["query"])

            async def submit_hold_filter() -> None:
                await load_hold_page(0, (hold_query.value or "").strip() or None)

            hold_query.on("keydown.enter", submit_hold_filter)
            previous_hold_page.on("click", lambda: move_hold_page(-1))
            next_hold_page.on("click", lambda: move_hold_page(1))
            async def submit() -> None:
                if selected.value is None or not (reason.value or "").strip(): ui.notify(render_message("webui.submit.notify.hold_and_reason_are_required_bd688fb2"), color="warning"); return
                try:
                    await api.add_resource_to_hold(resource_type, resource_id, int(selected.value), reason.value.strip())
                    dialog.close(); ui.notify(render_message("webui.submit.notify.resource_added_to_hold_363e538f"), color="positive")
                    result = refresh_page()
                    if asyncio.iscoroutine(result): await result
                except ApiError as error: ui.notify(error_message(error), color="negative", close_button=True)
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.add_resource_to_hold_dialog.button.cancel_b8201f0b"), on_click=dialog.close).props("flat no-caps")
                ui.button(render_message("webui.add_resource_to_hold_dialog.button.add_25497227"), icon="add_link", on_click=submit).props("unelevated no-caps")
        dialog.open()
        background_tasks.create(load_hold_page(0, None))


    def show_effective_holds_dialog(
        effective_holds: list[dict[str, Any]], resource_type: str | None = None,
        resource_id: int | None = None, refresh_page: Any = None,
    ) -> None:
        dialog=ui.dialog()
        with dialog,ui.card().classes("w-[720px] max-w-[94vw] max-h-[85vh]"):
            with ui.row().classes("w-full items-center gap-3"):
                ui.avatar(icon="gavel",color="amber-2",text_color="amber-9",size="44px")
                with ui.column().classes("gap-0 grow"):
                    ui.label(render_message("webui.show_effective_holds_dialog.label.effective_legal_holds_d0741f24")).classes("text-xl font-semibold")
                    ui.label(render_message("webui.show_effective_holds_dialog.label.these_holds_currently_restrict_deletion_di_b25c7cfe")).classes("text-sm text-slate-600")
            ui.separator()
            with ui.column().classes("w-full gap-3 overflow-y-auto"):
                for item in effective_holds:
                    with ui.card().classes("w-full shadow-none border border-amber-200 bg-amber-50 p-4"):
                        if item.get("code"):
                            with ui.row().classes("w-full items-center gap-2"):
                                ui.badge(item["code"],color="amber").props("outline")
                                ui.label(item["name"]).classes("font-semibold text-slate-900")
                            ui.label(render_message("webui.show_effective_holds_dialog.label.protection_source_title_902b3795", title=item['source'].title())).classes("text-sm text-slate-600")
                            if item.get("preserve_resource_state"):
                                ui.label(render_message("webui.show_effective_holds_dialog.label.also_preserves_metadata_and_governed_state_36554881")).classes("text-sm text-amber-900")
                            with ui.row().classes("w-full justify-end gap-2"):
                                async def open_this_hold(selected_id: int = item["hold_id"]) -> None:
                                    dialog.close(); await select_hold_details(selected_id)
                                ui.button(render_message("webui.show_effective_holds_dialog.button.open_hold_c0eed5f4"), icon="open_in_new", on_click=open_this_hold).props("flat no-caps")
                                if item.get("is_inherited") and item.get("nearest_assigned_aggregation_id"):
                                    async def open_source(source_id: int = item["nearest_assigned_aggregation_id"]) -> None:
                                        dialog.close(); await open_aggregation(await api.get("aggregations", source_id))
                                    ui.button(render_message("webui.show_effective_holds_dialog.button.open_assigning_aggregation_e0b07cd2"), icon="account_tree", on_click=open_source).props("flat no-caps")
                                if (resource_type and resource_id is not None and item.get("is_direct")
                                        and item.get("can_manage_held_items") and item.get("direct_assignment_version") is not None):
                                    async def remove_this(selected: dict[str, Any] = item) -> None:
                                        async def remove(reason: str) -> None:
                                            await api.remove_hold_held_item(selected["hold_id"],resource_type,resource_id,selected["direct_assignment_version"],reason)
                                            dialog.close(); ui.notify(render_message("webui.remove.notify.direct_hold_assignment_removed_bd41d0bd"),color="positive")
                                            if refresh_page:
                                                result=refresh_page()
                                                if asyncio.iscoroutine(result): await result
                                        await hold_reason_dialog("Reason for removing this direct assignment","Remove",remove)
                                    ui.button(render_message("webui.show_effective_holds_dialog.button.remove_from_this_hold_bf33546c"),icon="link_off",color="negative",on_click=remove_this).props("flat no-caps")
                        else:
                            ui.label(render_message("webui.show_effective_holds_dialog.label.effective_hold_details_restricted_6e99756d")).classes("font-semibold text-amber-900")
                            ui.label(render_message("webui.show_effective_holds_dialog.label.protection_source_title_902b3795", title=item['source'].title())).classes("text-sm text-slate-600")
            ui.button(render_message("webui.show_effective_holds_dialog.button.close_7cfb3209"),on_click=dialog.close).props("flat no-caps").classes("self-end")
        dialog.open()


    return add_resource_to_hold_dialog, show_effective_holds_dialog
