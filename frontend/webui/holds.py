"""Existing legal-hold behavior with explicit feature dependencies."""
from __future__ import annotations
from typing import Any
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message


def build_holds(
    *, api, principal, register_navigation, show_authenticated_view, enter_holds, search_bar, aggregation_mode_bar, add_button, add_record_button, title, subtitle, guidance, table_container, select_hold_details, open_hold_editor, show_entity_history, error_message, format_timestamp,
):
    async def select_holds() -> None:
        register_navigation("holds", "Holds")
        show_authenticated_view(); enter_holds()
        search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False); add_record_button.set_visibility(False)
        title.text = render_message("webui.select_holds.text.holds_06db50d5"); subtitle.text = render_message("webui.select_holds.text.legal_and_regulatory_preservation_instruct_046357c0"); guidance.text = ""
        table_container.clear()
        try:
            hold_people=await api.hold_people()
        except ApiError:
            hold_people=[]
        people_options={item["id"]:(item.get("localized") or {}).get("name") or item["name"] for item in hold_people}
        owner_options={None:render_message("webui.select_holds.text.all_owners_d14f22bf")}; owner_options.update(people_options)
        contributor_options={None:render_message("webui.select_holds.text.all_contributors_88e3d166")}; contributor_options.update(people_options)
        privileges = set((principal() or {}).get("global_privileges", []))
        with table_container, ui.column().classes("w-full p-5 gap-4"):
            paging = {"offset": 0, "total": 0, "limit": 25}
            with ui.row().classes("w-full items-center"):
                ui.label(render_message("webui.select_holds.label.filter_holds_9365e709")).classes("text-lg font-semibold text-slate-800")
                ui.space()
                if "holds.administer" in privileges:
                    ui.button(
                        render_message("webui.select_holds.button.create_hold_c7bae8dd"), icon="add", on_click=lambda: open_hold_editor(),
                    ).props("unelevated no-caps")
            with ui.row().classes("w-full items-end gap-3"):
                query = ui.input(render_message("webui.select_holds.input.search_code_or_name_79d187ac")).props("outlined dense clearable debounce=300").classes("grow")
                hold_state = ui.select({None:render_message("webui.select_holds.select.all_states_7fa05389"),"scheduled":render_message("webui.select_holds.select.scheduled_860621ba"),"active":render_message("webui.select_holds.select.active_f5bdb37b"),"expired":render_message("webui.select_holds.select.expired_99643a2d")}, value=None, label=render_message("webui.select_holds.select.state_f8c2bfbf")).props("outlined dense").classes("w-44")
                preservation = ui.select({None:render_message("webui.select_holds.select.all_protection_e6699e77"),"false":render_message("webui.select_holds.select.core_protection_6f52e26e"),"true":render_message("webui.select_holds.select.enhanced_state_preservation_39552bdf")},value=None,label=render_message("webui.select_holds.select.protection_517995ff")).props("outlined dense").classes("w-56")
                hold_sort = ui.select({"code":render_message("webui.select_holds.select.code_a654eddb"),"name":render_message("webui.select_holds.select.name_c9fd205f"),"state":render_message("webui.select_holds.select.state_f8c2bfbf"),"valid_from":render_message("webui.select_holds.select.valid_from_ebec3edf"),"valid_to":render_message("webui.select_holds.select.valid_until_5ebd52b4"),"owner":render_message("webui.select_holds.select.owner_26739337"),"created":render_message("webui.select_holds.select.created_04560f88"),"updated":render_message("webui.select_holds.select.updated_6ed0fc83")},value="code",label=render_message("webui.select_holds.select.sort_by_2bb66ed7")).props("outlined dense").classes("w-44")
                refresh = ui.button(render_message("webui.select_holds.button.refresh_debf3e22"), icon="refresh").props("flat dense no-caps")
            with ui.row().classes("w-full items-end gap-3"):
                owner_filter=ui.select(owner_options,value=None,label=render_message("webui.select_holds.select.owner_26739337")).props("outlined dense clearable").classes("w-56")
                contributor_filter=ui.select(contributor_options,value=None,label=render_message("webui.select_holds.select.contributor_f350f4ca")).props("outlined dense clearable").classes("w-56")
                valid_from_filter=ui.input(render_message("webui.select_holds.input.valid_from_on_after_29c20eb9")).props("outlined dense clearable type=datetime-local").classes("w-56")
                valid_to_filter=ui.input(render_message("webui.select_holds.input.valid_until_before_4a8c9188")).props("outlined dense clearable type=datetime-local").classes("w-56")
            host = ui.column().classes("w-full")
            with ui.row().classes("w-full items-center justify-between"):
                page_status = ui.label().classes("text-sm text-slate-600")
                with ui.row().classes("gap-1"):
                    first_page = ui.button(render_message("webui.select_holds.button.first_8a70bfa4"),icon="first_page").props("flat no-caps")
                    previous_page = ui.button(render_message("webui.select_holds.button.previous_1a2b68f0"),icon="chevron_left").props("flat no-caps")
                    next_page = ui.button(render_message("webui.select_holds.button.next_4ca23c51"),icon="chevron_right").props("flat no-caps")
                    last_page = ui.button(render_message("webui.select_holds.button.last_ddc4398f"),icon="last_page").props("flat no-caps")

            async def show_list_hold_history(hold: dict[str, Any]) -> None:
                await show_entity_history("holds", hold)

            async def load(*, reset: bool = False) -> None:
                if reset: paging["offset"] = 0
                try:
                    result = await api.holds_page(q=(query.value or "").strip() or None,state=hold_state.value,
                        preserve_resource_state=(None if preservation.value is None else preservation.value=="true"),
                        owner_user_id=owner_filter.value,contributor_user_id=contributor_filter.value,
                        valid_from_gte=valid_from_filter.value or None,valid_to_lt=valid_to_filter.value or None,
                        sort=hold_sort.value,limit=paging["limit"],offset=paging["offset"])
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True); return
                rows=result["items"]; paging["total"]=result["total"]
                host.clear()
                with host:
                    if not rows:
                        ui.label(render_message("webui.load.label.no_holds_are_available_47c12f52")).classes("text-slate-500 p-6")
                        return
                    with ui.element("div").classes("governance-card-list w-full"):
                        for hold in rows:
                            with ui.card().classes(
                                "governance-list-card shadow-none " +
                                ("hold-list-card--effective" if hold.get("is_effective") else "")
                            ):
                                with ui.row().classes("w-full items-start no-wrap gap-3"):
                                    ui.avatar(icon="gavel", color="amber-1" if hold.get("is_effective") else "blue-1", text_color="amber-9" if hold.get("is_effective") else "primary", size="42px")
                                    with ui.column().classes("gap-0 min-w-0 grow"):
                                        ui.label(hold["name"]).classes("font-semibold text-base leading-tight")
                                        ui.label(hold["code"]).classes("text-xs font-medium text-primary")
                                        ui.label(hold.get("description") or render_message("webui.load.label.no_description_provided_4b47ab9c")).classes("text-xs text-slate-500 mt-1 leading-5")
                                    hold_state_label = {
                                        "scheduled": render_message("webui.select_holds.select.scheduled_860621ba"),
                                        "active": render_message("webui.select_holds.select.active_f5bdb37b"),
                                        "expired": render_message("webui.select_holds.select.expired_99643a2d"),
                                    }.get(hold["state"], str(hold["state"] or "—"))
                                    ui.badge(hold_state_label, color={"active":"warning","scheduled":"primary","expired":"blue-grey"}.get(hold["state"], "blue-grey")).props("outline")
                                with ui.element("div").classes("governance-list-facts hold-list-facts w-full"):
                                    for label, value in (
                                        (render_message("webui.select_hold_details.label.owner_7d141da3"), (hold["owner"].get("localized") or {}).get("name") or hold["owner"]["name"]),
                                        (render_message("webui.select_hold_details.label.contributors_008a0e27"), str(len(hold.get("contributors") or []))),
                                        (render_message("webui.select_holds.select.valid_from_ebec3edf"), format_timestamp(hold.get("valid_from"))),
                                        (render_message("webui.select_holds.select.valid_until_5ebd52b4"), format_timestamp(hold.get("valid_to")) if hold.get("valid_to") else render_message("common.value.no_expiry")),
                                        (render_message("webui.select_hold_details.label.held_items_244f35b3"), str(hold.get("direct_held_item_count", 0))),
                                    ):
                                        with ui.column().classes("gap-0 min-w-0"):
                                            ui.label(label).classes("detail-field-label")
                                            ui.label(value).classes("text-sm font-medium truncate w-full").tooltip(value)
                                with ui.row().classes("w-full justify-end gap-1"):
                                    ui.button(icon="open_in_new", on_click=lambda _, item=hold: select_hold_details(item["id"])).props("outline dense color=primary").tooltip(render_message("webui.load.tooltip.open_hold_318634da"))
                                    if hold.get("capabilities", {}).get("update"):
                                        ui.button(icon="edit", on_click=lambda _, item=hold: open_hold_editor(item)).props("outline dense color=primary").tooltip(render_message("webui.load.tooltip.edit_hold_d1f52ab4"))
                                    ui.button(icon="history", on_click=lambda _, item=hold: show_list_hold_history(item)).props("outline dense color=blue-grey").tooltip(render_message("webui.load.tooltip.hold_history_fdbfa3e8"))
                start=paging["offset"]+1 if paging["total"] else 0; end=min(paging["offset"]+len(rows),paging["total"])
                page_status.text=render_message("webui.load.text.showing_start_end_of_total_holds_6b398c76", start=start, end=end, total=paging['total'])
                first_page.set_enabled(paging["offset"]>0); previous_page.set_enabled(paging["offset"]>0)
                next_page.set_enabled(paging["offset"]+paging["limit"]<paging["total"]); last_page.set_enabled(paging["offset"]+paging["limit"]<paging["total"])
            async def move_hold_page(delta: int) -> None:
                paging["offset"]=max(0,paging["offset"]+delta*paging["limit"]); await load()
            async def hold_page_edge(last: bool) -> None:
                paging["offset"]=(max(0,(paging["total"]-1)//paging["limit"])*paging["limit"] if last else 0); await load()
            refresh.on("click", load); query.on_value_change(lambda:load(reset=True)); hold_state.on_value_change(lambda:load(reset=True)); preservation.on_value_change(lambda:load(reset=True)); hold_sort.on_value_change(lambda:load(reset=True))
            owner_filter.on_value_change(lambda:load(reset=True)); contributor_filter.on_value_change(lambda:load(reset=True)); valid_from_filter.on_value_change(lambda:load(reset=True)); valid_to_filter.on_value_change(lambda:load(reset=True))
            first_page.on("click",lambda:hold_page_edge(False)); previous_page.on("click",lambda:move_hold_page(-1)); next_page.on("click",lambda:move_hold_page(1)); last_page.on("click",lambda:hold_page_edge(True))
            await load()


    return select_holds
