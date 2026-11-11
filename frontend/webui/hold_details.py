"""Existing legal-hold behavior with explicit feature dependencies."""
from __future__ import annotations
from typing import Any
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message
from .identity_presentation import render_user_avatar, user_avatar
from .holds_people import style_person_select


def build_hold_details(
    *, api, register_navigation, show_authenticated_view, enter_hold_details, search_bar, aggregation_mode_bar, add_button, add_record_button, title, subtitle, guidance, table_container, bind_remote_people_select, select_holds, hold_reason_dialog, open_aggregation, select_user_details, select_record_details, open_hold_editor, show_entity_history, error_message, format_timestamp,
):
    async def select_hold_details(hold_id: int) -> None:
        try:
            hold = await api.hold(hold_id)
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True); return
        register_navigation("hold-details", hold["name"], entity_id=hold_id, accessible_label=f"{hold['name']} — {hold['code']}")
        show_authenticated_view(); enter_hold_details()
        search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False); add_button.set_visibility(False); add_record_button.set_visibility(False)
        localized_hold_states = {
            "scheduled": render_message("webui.select_holds.select.scheduled_860621ba"),
            "active": render_message("webui.select_holds.select.active_f5bdb37b"),
            "expired": render_message("webui.select_holds.select.expired_99643a2d"),
        }
        localized_hold_state = localized_hold_states.get(
            hold["state"], str(hold["state"] or "—")
        )
        title.text=hold["name"]; subtitle.text=render_message("webui.select_hold_details.text.code_title_fbb1087b", code=hold['code'], title=localized_hold_state); guidance.text=""; table_container.clear()

        async def manage_contributors() -> None:
            known_people = {
                int(person["id"]): f"{(person.get('localized') or {}).get('name') or person['name']} — {person.get('email') or render_message('webui.select_user_details.label.no_email_address_1d665180')}"
                for person in hold["contributors"]
                if int(person["id"]) != int(hold["owner_user_id"])
            }
            dialog = ui.dialog()
            with dialog, ui.card().classes("w-[620px] max-w-full"):
                ui.label(render_message("webui.manage_contributors.label.manage_contributors_39fd431b")).classes("text-xl font-semibold")
                selected = ui.select(known_people, value=[item["id"] for item in hold["contributors"]], multiple=True, label=render_message("webui.manage_contributors.select.active_contributors_be1212fb")).props("outlined use-chips use-input").classes("w-full")
                style_person_select(selected, multiple=True)
                load_contributor_options = bind_remote_people_select(
                    selected,
                    excluded_ids=lambda: {int(hold["owner_user_id"])},
                )
                reason = ui.textarea(render_message("webui.manage_contributors.textarea.reason_17ba4d8f")).props("outlined autogrow maxlength=2000").classes("w-full")
                async def submit() -> None:
                    if not (reason.value or "").strip(): ui.notify(render_message("webui.submit.notify.a_reason_is_required_2d25211d"), color="warning"); return
                    try:
                        saved = await api.replace_hold_contributors(hold_id, hold["version"], [int(value) for value in (selected.value or [])], reason.value.strip())
                        dialog.close(); ui.notify(render_message("webui.submit.notify.contributors_updated_0d631f65"), color="positive"); await select_hold_details(saved["id"])
                    except ApiError as error: ui.notify(error_message(error), color="negative", close_button=True)
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.manage_contributors.button.cancel_551081d0"), on_click=dialog.close).props("flat no-caps")
                    ui.button(render_message("webui.manage_contributors.button.save_contributors_9b6b56e2"), icon="group", on_click=submit).props("unelevated no-caps")

            dialog.open()

        async def delete_current_hold() -> None:
            async def remove(reason: str) -> None:
                await api.delete_hold(hold_id, hold["version"], reason); ui.notify(render_message("webui.remove.notify.hold_deleted_b2ed1745"), color="positive"); await select_holds()
            await hold_reason_dialog("Reason for deleting this empty hold", "Delete hold", remove)

        async def show_hold_history() -> None:
            await show_entity_history("holds", hold)
        with table_container, ui.column().classes("w-full p-4 gap-3"):
            with ui.element("div").classes("hold-command-layout w-full"):
                with ui.card().classes("detail-surface hold-command-overview shadow-none p-4 gap-3"):
                    with ui.row().classes("w-full items-start no-wrap gap-3"):
                        ui.avatar(icon="gavel",color="blue-1",text_color="primary",size="46px")
                        with ui.column().classes("gap-0 grow min-w-0"):
                            with ui.row().classes("items-center gap-2"):
                                ui.label(hold["name"]).classes("text-xl font-semibold text-slate-900")
                                ui.badge(localized_hold_state, color="positive" if hold["state"]=="active" else "blue-grey").props("outline")
                            ui.label(hold["code"]).classes("text-xs font-medium tracking-wide text-slate-500")
                            ui.label(hold.get("description") or render_message("webui.select_hold_details.label.no_description_provided_d1db5944")).classes("text-sm text-slate-600 mt-2 leading-5")
                    with ui.element("div").classes("hold-summary-facts w-full"):
                        for label,value in (
                            (render_message("webui.select_holds.select.valid_from_ebec3edf"),format_timestamp(hold["valid_from"])),
                            (render_message("webui.select_holds.select.valid_until_5ebd52b4"),format_timestamp(hold["valid_to"]) if hold.get("valid_to") else render_message("common.value.no_expiry")),
                            (render_message("webui.select_holds.select.protection_517995ff"),(render_message("webui.select_holds.select.enhanced_state_preservation_39552bdf") if hold["preserve_resource_state"] else render_message("webui.select_holds.select.core_protection_6f52e26e"))),
                        ):
                            with ui.column().classes("gap-0 min-w-0"):
                                ui.label(label).classes("detail-field-label")
                                ui.label(value).classes("text-sm font-medium w-full").tooltip(value)
                    with ui.column().classes("hold-people-block w-full gap-1"):
                        ui.label(render_message("webui.select_hold_details.label.owner_7d141da3")).classes("detail-field-label")
                        with ui.button(on_click=lambda: select_user_details(hold["owner"]["id"])).props("flat dense no-caps color=blue-grey-9").classes("hold-person-button self-start -ml-2"):
                            render_user_avatar(hold["owner"], size="26px").style("margin-inline-end:7px !important")
                            ui.label((hold["owner"].get("localized") or {}).get("name") or hold["owner"]["name"]).classes("text-sm")
                        ui.label(render_message("webui.select_hold_details.label.contributors_008a0e27")).classes("detail-field-label mt-1")
                        with ui.row().classes("hold-people-row w-full items-center gap-2 -ml-2"):
                            if hold["contributors"]:
                                for contributor in hold["contributors"]:
                                    with ui.button(on_click=lambda _, user_id=contributor["id"]: select_user_details(user_id)).props("flat dense no-caps color=blue-grey-9").classes("hold-person-button gap-1"):
                                        render_user_avatar(contributor, size="25px").style("margin-inline-end:5px !important")
                                        ui.label((contributor.get("localized") or {}).get("name") or contributor["name"]).classes("text-sm")
                            else:
                                ui.label(render_message("webui.select_hold_details.label.no_contributors_assigned_401fb846")).classes("text-xs text-slate-500")
                with ui.card().classes("detail-surface hold-command-actions shadow-none p-4 gap-3"):
                    ui.label(render_message("webui.select_hold_details.label.hold_actions_cc65f86c")).classes("aggregation-panel-heading w-full")
                    ui.label(render_message("webui.select_hold_details.label.manage_104ec502")).classes("aggregation-action-group-label")
                    with ui.element("div").classes("hold-action-row w-full"):
                        if hold["capabilities"].get("update"):
                            ui.button(render_message("webui.select_hold_details.button.edit_hold_d034b7c2"),icon="edit",on_click=lambda:open_hold_editor(hold)).props("outline dense no-caps")
                        if hold["capabilities"].get("manage_contributors"):
                            ui.button(render_message("webui.select_hold_details.button.manage_contributors_866ef148"),icon="group",on_click=manage_contributors).props("outline dense no-caps")
                    ui.label(render_message("webui.select_hold_details.label.audit_and_lifecycle_cb58ed69")).classes("aggregation-action-group-label")
                    with ui.element("div").classes("hold-action-row w-full"):
                        ui.button(render_message("webui.select_hold_details.button.view_history_f7d1e6af"),icon="history",on_click=show_hold_history).props("outline dense no-caps")
                        delete_button = ui.button(render_message("webui.select_hold_details.button.delete_hold_61877bfd"),icon="delete",color="negative",on_click=delete_current_hold).props("outline dense no-caps")
                    if hold["capabilities"].get("delete"):
                        delete_button.tooltip(render_message("webui.select_hold_details.tooltip.delete_empty_hold_37fe4ab5"))
                    else:
                        delete_button.disable()
                        delete_button.tooltip(render_message("webui.select_hold_details.tooltip.remove_all_held_items_before_deleting_this_292c752f") if hold["capability_reasons"].get("delete") == "hold_not_empty" else render_message("webui.select_hold_details.tooltip.you_are_not_authorized_to_delete_this_hold_6fd753f2"))
            assigned_by_options={None:render_message("webui.select_hold_details.text.any_assigning_user_2e01c2df"),hold["owner"]["id"]:(hold["owner"].get("localized") or {}).get("name") or hold["owner"]["name"]}
            assigned_by_options.update({item["id"]:(item.get("localized") or {}).get("name") or item["name"] for item in hold["contributors"]})
            with ui.card().classes("detail-surface w-full shadow-none p-4 gap-3"):
                ui.label(render_message("webui.select_hold_details.label.filter_held_items_480cc40c")).classes("font-semibold")
                with ui.grid(columns=4).classes("w-full gap-3"):
                    held_item_query=ui.input(render_message("webui.select_hold_details.input.search_held_items_1ff2e989")).props("outlined dense clearable").classes("w-full")
                    held_item_type=ui.select({None:render_message("webui.select_hold_details.select.all_types_e15731ed"),"aggregation":render_message("webui.select_hold_details.select.aggregations_a2b082b0"),"record":render_message("webui.select_hold_details.select.records_443323d2")},value=None,label=render_message("webui.select_hold_details.select.type_228c6d86")).props("outlined dense").classes("w-full")
                    held_item_sort=ui.select({"assigned_at":render_message("webui.select_hold_details.select.assigned_79862205"),"number":render_message("webui.select_hold_details.select.number_996300ef"),"title":render_message("webui.select_hold_details.select.title_4c1867a5"),"type":render_message("webui.select_hold_details.select.type_228c6d86"),"assigned_by":render_message("webui.select_hold_details.select.assigned_by_5b6fa5fb"),"security_level":render_message("webui.select_hold_details.select.security_level_68d98e9c")},value="assigned_at",label=render_message("webui.select_hold_details.select.sort_by_714d10c2")).props("outlined dense").classes("w-full")
                    held_item_assigned_by=ui.select(assigned_by_options,value=None,label=render_message("webui.select_hold_details.select.assigned_by_5b6fa5fb")).props("outlined dense clearable").classes("w-full")
                with ui.grid(columns=2).classes("w-full gap-3"):
                    held_item_assigned_from=ui.input(render_message("webui.select_hold_details.input.assignment_date_from_4569e572")).props("outlined dense clearable type=datetime-local").classes("w-full")
                    held_item_assigned_before=ui.input(render_message("webui.select_hold_details.input.assignment_date_before_45df0de5")).props("outlined dense clearable type=datetime-local").classes("w-full")
                with ui.row().classes("detail-action-row w-full items-center justify-start gap-2"):
                    held_item_refresh=ui.button(render_message("webui.select_hold_details.button.refresh_251d4756"),icon="refresh").props("flat dense no-caps")
                    if hold["capabilities"].get("manage_held_items"):
                        add_held_item=ui.button(render_message("webui.select_hold_details.button.add_held_items_4cfdf56b"),icon="add").props("unelevated dense no-caps")
                        remove_selected_held_items=ui.button(render_message("webui.select_hold_details.button.remove_selected_16cdfb8a"),icon="link_off",color="negative").props("outline dense no-caps")
            with ui.row().classes("w-full items-end justify-between pt-2"):
                with ui.column().classes("gap-0"):
                    ui.label(render_message("webui.select_hold_details.label.held_items_244f35b3")).classes("text-lg font-semibold text-slate-900")
                    ui.label(render_message("webui.select_hold_details.label.records_and_aggregations_directly_assigned_bbbbae27")).classes("text-sm text-slate-500")
            held_item_host=ui.column().classes("w-full")
            held_item_paging={"offset":0,"total":0,"limit":25}
            held_item_selection:dict[str,dict[str,Any]]={}
            with ui.row().classes("w-full items-center justify-between"):
                held_item_page_status=ui.label().classes("text-sm text-slate-600")
                with ui.row().classes("gap-1"):
                    held_item_first=ui.button(render_message("webui.select_hold_details.button.first_38cdd984"),icon="first_page").props("flat no-caps")
                    held_item_previous=ui.button(render_message("webui.select_hold_details.button.previous_363a9cec"),icon="chevron_left").props("flat no-caps")
                    held_item_next=ui.button(render_message("webui.select_hold_details.button.next_1aa535cd"),icon="chevron_right").props("flat no-caps")
                    held_item_last=ui.button(render_message("webui.select_hold_details.button.last_6614b469"),icon="last_page").props("flat no-caps")

            async def load_held_items(*,reset:bool=False) -> None:
                if reset: held_item_paging["offset"]=0
                result=await api.hold_held_items_page(hold_id,q=(held_item_query.value or "").strip() or None,resource_type=held_item_type.value,
                    assigned_by_user_id=held_item_assigned_by.value,assigned_from=held_item_assigned_from.value or None,assigned_before=held_item_assigned_before.value or None,
                    sort=held_item_sort.value,descending=held_item_sort.value=="assigned_at",limit=held_item_paging["limit"],offset=held_item_paging["offset"])
                rows=result["items"]; held_item_paging["total"]=result["total"]
                held_item_host.clear()
                with held_item_host:
                    for row in rows:
                        row["selection_key"]=f"{row['resource_type']}:{row['resource_id']}"
                        row["security_level_display"] = f"{row['security_level_code']} — {row['security_level_name']}"
                        row["assigned_at_display"] = format_timestamp(row["assigned_at"])
                        row["assigned_by_avatar"] = user_avatar({
                            "id": row.get("assigned_by_user_id"),
                            "name": row.get("assigned_by_name") or render_message("webui.load_held_items.value.system"),
                        })
                    async def open_held_item(row: dict[str, Any]) -> None:
                        if row["resource_type"]=="aggregation": await open_aggregation(await api.get("aggregations",row["resource_id"]))
                        else: await select_record_details(row["resource_id"])
                    async def remove_held_item(row: dict[str, Any]) -> None:
                        async def remove(reason: str) -> None:
                            await api.remove_hold_held_item(hold_id,row["resource_type"],row["resource_id"],row["version"],reason); ui.notify(render_message("webui.remove.notify.held_item_removed_180da70b"),color="positive"); await select_hold_details(hold_id)
                        await hold_reason_dialog("Reason for removing this direct assignment","Remove",remove)
                    def update_held_item_selection(row: dict[str, Any], selected: bool) -> None:
                        if selected:
                            held_item_selection[row["selection_key"]] = dict(row)
                        else:
                            held_item_selection.pop(row["selection_key"], None)
                    if not rows:
                        ui.label(render_message("webui.load_held_items.label.no_held_items_match_these_filters_c28c6f92")).classes("w-full text-center text-slate-400 py-12")
                    with ui.element("div").classes("governance-card-list w-full"):
                        for row in rows:
                            with ui.card().classes("governance-list-card shadow-none"):
                                with ui.row().classes("w-full items-start no-wrap gap-3"):
                                    if hold["capabilities"].get("manage_held_items"):
                                        selected = ui.checkbox(value=row["selection_key"] in held_item_selection).props("dense")
                                        selected.on_value_change(lambda event, item=row: update_held_item_selection(item, bool(event.value)))
                                    with ui.element("div").classes("governance-card-icon mt-1"):
                                        ui.icon("folder" if row["resource_type"] == "aggregation" else "description", size="22px")
                                    with ui.column().classes("gap-0 min-w-0 grow"):
                                        ui.label(row.get("title") or render_message("webui.load_held_items.label.untitled_9d476a3c")).classes("font-semibold text-base leading-tight")
                                        ui.label(row.get("number") or "—").classes("text-xs font-medium text-primary")
                                        ui.label(row.get("description") or render_message("webui.load_held_items.label.no_description_provided_db263706")).classes("text-xs text-slate-500 mt-1 leading-5")
                                    ui.badge(render_message("webui.load_held_items.badge.aggregation_4d7e0b4c") if row["resource_type"] == "aggregation" else render_message("webui.load_held_items.badge.record_58fed782"), color="blue-grey").props("outline")
                                with ui.element("div").classes("governance-list-facts w-full"):
                                    for field, label, value in (
                                        ("security_level", render_message("webui.load_held_items.field.security_level"), row["security_level_display"]),
                                        ("assigned", render_message("webui.load_held_items.field.assigned"), row["assigned_at_display"]),
                                        ("assigned_by", render_message("webui.load_held_items.field.assigned_by"), row.get("assigned_by_name") or render_message("webui.load_held_items.value.system")),
                                        ("direct_assignment", render_message("webui.load_held_items.field.direct_assignment"), render_message("webui.load_held_items.value.yes")),
                                    ):
                                        with ui.column().classes("gap-0 min-w-0"):
                                            ui.label(label).classes("detail-field-label")
                                            if field == "assigned_by" and row.get("assigned_by_user_id"):
                                                with ui.button(on_click=lambda _, user_id=row["assigned_by_user_id"]: select_user_details(user_id)).props("flat dense no-caps color=blue-grey-9").classes("self-start -ml-2"):
                                                    render_user_avatar({"id":row["assigned_by_user_id"],"name":value}, size="26px").style("margin-inline-end:7px !important")
                                                    ui.label(value).classes("text-sm")
                                            else:
                                                ui.label(value).classes("text-sm font-medium truncate w-full").tooltip(value)
                                with ui.row().classes("w-full justify-end gap-1"):
                                    ui.button(icon="open_in_new", on_click=lambda _, item=row: open_held_item(item)).props("outline dense color=primary").tooltip(render_message("webui.load_held_items.tooltip.open_resource_527a2063"))
                                    if hold["capabilities"].get("manage_held_items"):
                                        ui.button(icon="link_off", on_click=lambda _, item=row: remove_held_item(item)).props("outline dense color=negative").tooltip(render_message("webui.load_held_items.tooltip.remove_from_this_hold_c9ad1e53"))
                start=held_item_paging["offset"]+1 if held_item_paging["total"] else 0; end=min(held_item_paging["offset"]+len(rows),held_item_paging["total"])
                held_item_page_status.text=render_message("webui.load_held_items.text.showing_start_end_of_total_held_items_b7918b7e", start=start, end=end, total=held_item_paging['total'])
                held_item_first.set_enabled(held_item_paging["offset"]>0); held_item_previous.set_enabled(held_item_paging["offset"]>0)
                held_item_next.set_enabled(held_item_paging["offset"]+held_item_paging["limit"]<held_item_paging["total"]); held_item_last.set_enabled(held_item_paging["offset"]+held_item_paging["limit"]<held_item_paging["total"])
            async def move_held_item_page(delta:int)->None:
                held_item_paging["offset"]=max(0,held_item_paging["offset"]+delta*held_item_paging["limit"]); await load_held_items()
            async def held_item_page_edge(last:bool)->None:
                held_item_paging["offset"]=(max(0,(held_item_paging["total"]-1)//held_item_paging["limit"])*held_item_paging["limit"] if last else 0); await load_held_items()
            async def show_add_held_item() -> None:
                page_size = 50
                picker = {"offset": 0, "total": 0, "selected": {}}
                dialog=ui.dialog()
                with dialog,ui.card().style(
                    "width:1280px;max-width:calc(100vw - 48px)"
                ).classes("max-h-[94vh]"):
                    with ui.row().classes("w-full items-center justify-between no-wrap"):
                        ui.label(render_message("webui.show_add_held_item.label.add_resources_to_hold_59f543cf")).classes("text-xl font-semibold")
                        ui.button(icon="close", on_click=dialog.close).props(
                            'flat round dense aria-label=' + repr(render_message("webui.show_add_held_item.button.cancel_93656897"))
                        ).tooltip(render_message("webui.show_add_held_item.button.cancel_93656897"))
                    ui.label(render_message("webui.show_add_held_item.label.search_the_resources_you_can_view_select_a_a096d995")).classes("text-sm text-slate-600")
                    with ui.row().classes("w-full items-end gap-3"):
                        candidate_query=ui.input(render_message("webui.show_add_held_item.input.search_number_title_or_description_f135a521"),placeholder=render_message("webui.show_add_held_item.input.for_example_case_2026_or_contract_83e77270")).props("outlined clearable debounce=350").classes("grow")
                        candidate_type=ui.select({None:render_message("webui.show_add_held_item.select.aggregations_and_records_0c33d8e9"),"aggregation":render_message("webui.show_add_held_item.select.aggregations_only_e3ca93ce"),"record":render_message("webui.show_add_held_item.select.records_only_f985a7d3")},value="aggregation",label=render_message("webui.show_add_held_item.select.resource_type_186980bb")).props("outlined").classes("w-56")
                    selection_summary=ui.label(render_message("webui.show_add_held_item.label.no_resources_selected_c1ee3075")).classes("text-sm font-medium text-primary")
                    # Contain the paginated cards: an ordinary flex column shrinks
                    # while its visible overflow paints behind the reason/footer.
                    with ui.scroll_area().classes("w-full h-64 max-h-[30vh] shrink-0"):
                        candidate_host=ui.column().classes("w-full")
                    with ui.row().classes("w-full items-center justify-between"):
                        page_status=ui.label().classes("text-sm text-slate-600")
                        with ui.row().classes("gap-1"):
                            first_page=ui.button(render_message("webui.show_add_held_item.button.first_ec1eaa60"),icon="first_page").props("flat no-caps")
                            previous_page=ui.button(render_message("webui.show_add_held_item.button.previous_e18f5c26"),icon="chevron_left").props("flat no-caps")
                            next_page=ui.button(render_message("webui.show_add_held_item.button.next_3c10a2c8"),icon="chevron_right").props("flat no-caps")
                            last_page=ui.button(render_message("webui.show_add_held_item.button.last_341e2a6f"),icon="last_page").props("flat no-caps")
                    reason=ui.textarea(render_message("webui.show_add_held_item.textarea.reason_for_adding_these_resources_3d6f886e")).props("outlined autogrow maxlength=2000").classes("w-full")

                    def update_selection_summary() -> None:
                        count=len(picker["selected"])
                        selection_summary.text = render_message(
                            "webui.update_selection_summary.text.selected_resource_count",
                            count=count,
                        )

                    async def load_candidates(*, reset: bool=False) -> None:
                        if reset: picker["offset"]=0
                        try:
                            result=await api.hold_held_item_candidates(
                                hold_id,q=(candidate_query.value or "").strip() or None,
                                resource_type=candidate_type.value,limit=page_size,offset=picker["offset"],
                            )
                        except ApiError as error:
                            ui.notify(error_message(error),color="negative",close_button=True); return
                        rows=result["items"]
                        for row in rows: row["selection_key"]=f"{row['resource_type']}:{row['resource_id']}"
                        picker["total"]=result["total"]
                        candidate_host.clear()
                        with candidate_host:
                            if not rows:
                                ui.label(render_message("webui.load_candidates.label.no_matching_resources_are_available_to_add_bc0471cf")).classes("text-slate-500 p-8 self-center")
                            else:
                                def update_candidate_selection(row: dict[str, Any], selected: bool) -> None:
                                    if selected:
                                        picker["selected"][row["selection_key"]] = dict(row)
                                    else:
                                        picker["selected"].pop(row["selection_key"], None)
                                    update_selection_summary()
                                with ui.element("div").classes("governance-card-list w-full"):
                                    for row in rows:
                                        with ui.card().classes("governance-list-card shadow-none"):
                                            with ui.row().classes("w-full items-start no-wrap gap-3"):
                                                selected = ui.checkbox(value=row["selection_key"] in picker["selected"]).props("dense")
                                                selected.on_value_change(lambda event, item=row: update_candidate_selection(item, bool(event.value)))
                                                with ui.element("div").classes("governance-card-icon mt-1"):
                                                    ui.icon("folder" if row["resource_type"] == "aggregation" else "description", size="22px")
                                                with ui.column().classes("gap-0 min-w-0 grow"):
                                                    ui.label(row.get("title") or render_message("webui.load_candidates.label.untitled_9322bbb9")).classes("font-semibold leading-tight")
                                                    ui.label(row.get("number") or "—").classes("text-xs font-medium text-primary")
                                                    ui.label(row.get("description") or render_message("webui.load_candidates.label.no_description_provided_bf7f8283")).classes("text-xs text-slate-500 mt-1 leading-5")
                                                ui.badge(render_message("webui.load_candidates.badge.aggregation_de7a9bf8") if row["resource_type"] == "aggregation" else render_message("webui.load_candidates.badge.record_4970f2fc"), color="blue-grey").props("outline")
                        start=picker["offset"]+1 if result["total"] else 0
                        end=min(picker["offset"]+len(rows),result["total"])
                        page_status.text=render_message("webui.load_candidates.text.showing_start_end_of_total_matching_resour_e74f20c5", start=start, end=end, total=result['total'])
                        first_page.set_enabled(picker["offset"]>0)
                        previous_page.set_enabled(picker["offset"]>0)
                        next_page.set_enabled(picker["offset"]+page_size<result["total"])
                        last_page.set_enabled(picker["offset"]+page_size<result["total"])

                    async def move_page(direction: int) -> None:
                        picker["offset"]=max(0,picker["offset"]+direction*page_size)
                        await load_candidates()

                    async def move_to_edge(last: bool) -> None:
                        picker["offset"]=(max(0,(picker["total"]-1)//page_size)*page_size if last else 0)
                        await load_candidates()

                    async def submit() -> None:
                        if not picker["selected"]: ui.notify(render_message("webui.submit.notify.select_at_least_one_resource_69cf4456"),color="warning"); return
                        if not(reason.value or "").strip(): ui.notify(render_message("webui.submit.notify.a_reason_is_required_2d25211d"),color="warning"); return
                        held_items=[{"resource_type":row["resource_type"],"resource_id":row["resource_id"]} for row in picker["selected"].values()]
                        try:
                            result=await api.add_hold_held_items_bulk(hold_id,held_items,reason.value.strip())
                            dialog.close(); ui.notify(render_message("webui.submit.notify.added_resources_added_to_the_hold_860b4c3c", added=result['added']),color="positive"); await select_hold_details(hold_id)
                        except ApiError as error: ui.notify(error_message(error),color="negative",close_button=True)
                    candidate_query.on_value_change(lambda:load_candidates(reset=True))
                    candidate_type.on_value_change(lambda:load_candidates(reset=True))
                    first_page.on("click",lambda:move_to_edge(False)); previous_page.on("click",lambda:move_page(-1))
                    next_page.on("click",lambda:move_page(1)); last_page.on("click",lambda:move_to_edge(True))
                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button(render_message("webui.show_add_held_item.button.cancel_93656897"),on_click=dialog.close).props("flat no-caps")
                        ui.button(render_message("webui.show_add_held_item.button.add_held_items_be6b0111"),icon="playlist_add",on_click=submit).props("unelevated no-caps")
                    await load_candidates()
                dialog.open()
            held_item_refresh.on("click",load_held_items); held_item_query.on_value_change(lambda:load_held_items(reset=True)); held_item_type.on_value_change(lambda:load_held_items(reset=True)); held_item_sort.on_value_change(lambda:load_held_items(reset=True))
            held_item_assigned_by.on_value_change(lambda:load_held_items(reset=True)); held_item_assigned_from.on_value_change(lambda:load_held_items(reset=True)); held_item_assigned_before.on_value_change(lambda:load_held_items(reset=True))
            held_item_first.on("click",lambda:held_item_page_edge(False)); held_item_previous.on("click",lambda:move_held_item_page(-1)); held_item_next.on("click",lambda:move_held_item_page(1)); held_item_last.on("click",lambda:held_item_page_edge(True))
            if hold["capabilities"].get("manage_held_items"): add_held_item.on("click",show_add_held_item)
            if hold["capabilities"].get("manage_held_items"):
                async def remove_selected() -> None:
                    selected=list(held_item_selection.values())
                    if not selected: ui.notify(render_message("webui.remove_selected.notify.select_one_or_more_held_items_c34cd7be"),color="warning"); return
                    async def remove(reason:str)->None:
                        await api.remove_hold_held_items_bulk(hold_id,[{"resource_type":row["resource_type"],"resource_id":row["resource_id"],"version":row["version"]} for row in selected],reason)
                        held_item_selection.clear(); ui.notify(render_message("webui.remove.notify.selected_count_held_items_removed_from_nam_4794d2e9", selected_count=len(selected), name=hold['name']),color="positive"); await select_hold_details(hold_id)
                    await hold_reason_dialog(f"Remove {len(selected)} selected held items from {hold['name']}?","Remove held items",remove)
                remove_selected_held_items.on("click",remove_selected)
            await load_held_items()


    return select_hold_details
