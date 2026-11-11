"""Global search, bounded results, diagnostics and per-client navigation callbacks."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
import asyncio
from .component_presentation import component_is_previewable
import json
from .i18n_catalogue import render_message
from .i18n_catalogue import render_message_plain
from nicegui import ui

def build_global_search(
    *, add_button, add_record_button, aggregation_mode_bar, api, clear_advanced_workspace, clear_collection_results, discard_navigation_guard, enter_global_search, error_message, get_principal, get_resource, global_search_input, global_search_state, invalidate_advanced_session, open_aggregation, register_navigation, render_compact_resource_result, restore_compact_result_anchor, search_bar, select_record_details, show_authenticated_view, subtitle, table_container, title,
):
    def global_search_payload(query: str, *, cursor: str | None = None) -> dict[str, Any]:
        full_text = {"full_text": {"query": query}}
        payload: dict[str, Any] = {
            "record_where": full_text,
            "aggregation_where": full_text,
            "result_types": ["records", "aggregations"],
            "limit": 25,
        }
        if cursor:
            payload["cursor"] = cursor
        if global_search_state["search_diagnostics_enabled"]:
            payload["debug"] = True
        return payload


    def render_safe_snippet(value: str | None, *, compact: bool = False) -> None:
        """Render server markers as elements so snippet text can never become HTML."""
        text = value or "No preview available"
        if compact:
            text = " ".join(text.split())
        layout = (
            "items-baseline gap-0 text-xs text-slate-600 no-wrap overflow-hidden whitespace-nowrap"
            if compact else "items-baseline gap-0 text-sm text-slate-600 flex-wrap"
        )
        with ui.row().classes(layout):
            highlighted = False
            for segment in text.replace("⟧", "⟧\x00").replace("⟦", "\x00⟦").split("\x00"):
                if not segment:
                    continue
                if segment.startswith("⟦"):
                    highlighted = True
                    segment = segment[1:]
                closes = segment.endswith("⟧")
                if closes:
                    segment = segment[:-1]
                if segment:
                    label = ui.label(segment).classes("whitespace-pre" if compact else "whitespace-pre-wrap")
                    if highlighted:
                        label.classes(add="global-search-highlight")
                if closes:
                    highlighted = False


    async def copy_diagnostic_json(value: dict[str, Any]) -> None:
        encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        await ui.run_javascript(
            f"navigator.clipboard.writeText({json.dumps(encoded)}).then(() => true)",
            timeout=5,
        )
        ui.notify(render_message("webui.copy_diagnostic_json.notify.json_copied_2dbf473d"), color="positive")


    def render_search_diagnostics() -> None:
        if not global_search_state["search_diagnostics_enabled"]:
            return
        with ui.expansion(render_message("webui.render_search_diagnostics.expansion.search_diagnostics_517d7729"), icon="bug_report").props(
            "dense header-class='text-slate-700'"
        ).classes("w-full border border-slate-200 rounded-lg"):
            sent = global_search_state.get("search_diagnostics_sent")
            accepted = global_search_state.get("search_diagnostics_accepted")
            with ui.column().classes("w-full p-3 gap-3"):
                with ui.row().classes("w-full items-center flex-wrap min-w-0"):
                    ui.label(render_message("webui.render_search_diagnostics.label.sent_to_api_68a1d285")).classes("font-semibold")
                    ui.label(render_message("webui.render_search_diagnostics.label.post_api_v1_full_text_search_8191066f")).classes("text-xs text-slate-500")
                    ui.space()
                    if sent is not None:
                        ui.button(render_message("webui.render_search_diagnostics.button.copy_json_19011ed1"), icon="content_copy", on_click=lambda: copy_diagnostic_json(sent)).props("flat dense no-caps")
                ui.code(json.dumps(sent, ensure_ascii=False, indent=2, sort_keys=True) if sent else render_message("webui.render_search_diagnostics.code.no_diagnostic_request_has_been_sent_5b401e20")).classes("global-search-json w-full")
                with ui.row().classes("w-full items-center flex-wrap min-w-0"):
                    ui.label(render_message("webui.render_search_diagnostics.label.accepted_by_api_6f8fcf1f")).classes("font-semibold")
                    if accepted:
                        ui.label(
                            render_message("webui.render_search_diagnostics.label.request_id_value_fingerprint_value_2_f8dbcf29", value=accepted.get('request_id') or 'unavailable', value_2=accepted.get('query_fingerprint') or 'unavailable')
                        ).classes("text-xs text-slate-500 break-all min-w-0")
                    ui.space()
                    if accepted:
                        ui.button(render_message("webui.render_search_diagnostics.button.copy_json_19011ed1"), icon="content_copy", on_click=lambda: copy_diagnostic_json(accepted)).props("flat dense no-caps")
                if accepted:
                    ui.code(json.dumps(accepted, ensure_ascii=False, indent=2, sort_keys=True)).classes("global-search-json w-full")
                else:
                    ui.label(render_message("webui.render_search_diagnostics.label.unavailable_the_api_did_not_accept_or_retu_8a4916f9")).classes("text-sm text-slate-500 italic")


    def render_global_search_results() -> None:
        table_container.clear()
        query = global_search_state["global_search_query"]
        items = global_search_state["global_search_items"]
        selected = global_search_state["global_search_filter"]
        visible = [item for item in items if selected == "all" or item["type"] == selected]
        page_size = int(global_search_state.get("global_search_page_size", 10))
        page_count = max(1, (len(visible) + page_size - 1) // page_size)
        global_search_state["global_search_page"] = min(max(1, int(global_search_state.get("global_search_page", 1))), page_count)
        page_number = global_search_state["global_search_page"]
        page_start = (page_number - 1) * page_size
        page_items = visible[page_start:page_start + page_size]
        record_count = sum(item["type"] == "record" for item in items)
        aggregation_count = sum(item["type"] == "aggregation" for item in items)
        with table_container, ui.column().classes("w-full p-5 gap-4"):
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                ui.label(render_message("webui.render_global_search_results.label.results_for_query_53df3850", query=query)).classes("text-sm text-slate-600 grow")
                if "search.query.debug" in set((get_principal() or {}).get("global_privileges", [])):
                    def toggle_diagnostics(event) -> None:
                        global_search_state["search_diagnostics_enabled"] = bool(event.value)
                        global_search_state["search_diagnostics_sent"] = None
                        global_search_state["search_diagnostics_accepted"] = None
                        ui.notify(render_message("webui.toggle_diagnostics.notify.diagnostics_will_apply_to_the_next_explici_286f12ab"), color="primary")
                        render_global_search_results()
                    secondary_actions = ui.button(icon="more_vert").props(
                        'flat round aria-label=' + repr(render_message("webui.render_global_search_results.accessible_name.search_result_actions_10f81af1"))
                    ).tooltip(render_message("webui.render_global_search_results.tooltip.search_result_actions_2fe233c8"))
                    with secondary_actions, ui.menu():
                        diagnostics_toggle = ui.switch(
                            "Search diagnostics", value=global_search_state["search_diagnostics_enabled"],
                        ).props("dense color=primary").classes("px-3 py-2")
                        diagnostics_toggle.on_value_change(toggle_diagnostics)
            with ui.row().classes("items-center gap-1"):
                for key, label in (
                    ("all", render_message("global_search.filter.all", count=len(items))),
                    ("record", render_message("global_search.filter.records", count=record_count)),
                    ("aggregation", render_message("global_search.filter.aggregations", count=aggregation_count)),
                ):
                    button = ui.button(label, on_click=lambda _, value=key: (
                        global_search_state.__setitem__("global_search_filter", value),
                        global_search_state.__setitem__("global_search_page", 1),
                        render_global_search_results(),
                    )).props("dense no-caps")
                    button.props("unelevated color=primary" if selected == key else "flat color=blue-grey")
            if global_search_state.get("global_search_loading"):
                with ui.row().classes("w-full justify-center items-center py-12 gap-3").props('role=status aria-label=' + repr(render_message("webui.render_global_search_results.accessible_name.loading_search_results_eff54ce6"))):
                    ui.spinner("dots", size="32px", color="primary")
                    ui.label(render_message("webui.render_global_search_results.label.searching_records_files_and_aggregations_5756053f")).classes("text-slate-500")
                return
            render_search_diagnostics()
            if global_search_state.get("global_search_error"):
                with ui.card().classes("w-full shadow-none border border-red-200 bg-red-50 p-5"):
                    ui.icon("error_outline", color="negative", size="30px")
                    ui.label(render_message_plain("webui.render_global_search_results.label.search_could_not_be_completed_14ef74f3")).classes("font-semibold")
                    ui.label(global_search_state["global_search_error"]).classes("text-sm text-slate-600")
                    ui.button(render_message("webui.render_global_search_results.button.try_again_75a7aeea"), icon="refresh", on_click=lambda: run_global_search(query)).props("outline no-caps color=negative")
                return
            if global_search_state.get("global_search_pending"):
                with ui.row().classes("w-full items-center gap-2 rounded-lg bg-blue-50 border border-blue-200 p-3").props("role=status"):
                    ui.icon("info", color="primary")
                    ui.label(render_message("webui.render_global_search_results.label.recently_added_content_may_still_be_indexi_b45b7d39")).classes("text-sm text-slate-700")
            if not visible:
                with ui.column().classes("w-full items-center py-12 gap-2").props("role=status"):
                    ui.icon("search_off", size="42px").classes("text-slate-300")
                    ui.label(render_message("webui.render_global_search_results.label.no_results_found_ab1c85dc")).classes("text-lg font-semibold")
                    ui.label(render_message("webui.render_global_search_results.label.try_different_words_or_check_the_spelling_7fc06c50")).classes("text-sm text-slate-500")
            if page_items:
                with ui.column().classes("compact-result-list w-full gap-0"):
                    for item in page_items:
                        if item["type"] == "record":
                            record = item["record"]
                            authorized_component_details = {
                                int(component["id"]): component
                                for component in item.get("authorized_component_details", [])
                            }
                            matching_components = [
                                {**authorized_component_details.get(int(component["id"]), {}), **component}
                                for component in item.get("matching_components", [])
                                if component.get("id") is not None
                            ]
                            record_capabilities = item.get("record_capabilities") or {}
                            render_compact_resource_result(
                                "records", record,
                                on_open=open_global_record_from_result,
                                components=matching_components,
                                metadata_matched=bool(item.get("matched_record_metadata")),
                                content_matched=bool(matching_components),
                                can_preview=bool(
                                    record_capabilities.get("view_component")
                                    and any(component_is_previewable(component) for component in authorized_component_details.values())
                                ),
                                can_expand_components=bool(
                                    record_capabilities.get("list_components") and matching_components
                                ),
                                components_are_matches=True,
                                initially_expanded=(
                                    f"records:{int(record['id'])}" in global_search_state["global_search_expanded_results"]
                                ),
                                on_expansion_changed=lambda expanded, identifier=int(record["id"]):
                                    set_global_result_expansion("records", identifier, expanded),
                            )
                        else:
                            aggregation = item["aggregation"]
                            render_compact_resource_result(
                                "aggregations", aggregation,
                                on_open=open_global_aggregation_from_result,
                                metadata_matched=True,
                            )
            if visible:
                with ui.row().classes("w-full items-center justify-center gap-2 pt-1"):
                    first_button = ui.button(icon="first_page", on_click=lambda: change_global_search_page(1)).props(
                        'flat round aria-label=' + repr(render_message("webui.render_global_search_results.accessible_name.first_page_69926c59"))
                    ).tooltip(render_message("webui.render_global_search_results.tooltip.first_page_45ffdb30"))
                    previous_button = ui.button(icon="chevron_left", on_click=lambda: change_global_search_page(page_number - 1)).props(
                        'flat round aria-label=' + repr(render_message("webui.render_global_search_results.accessible_name.previous_page_571d7f79"))
                    ).tooltip(render_message("webui.render_global_search_results.tooltip.previous_page_6b7e38b3"))
                    ui.label(render_message("webui.render_global_search_results.label.page_page_number_9319ded9", page_number=page_number)).classes("text-sm text-slate-600 min-w-20 text-center")
                    next_button = ui.button(icon="chevron_right", on_click=lambda: change_global_search_page(page_number + 1)).props(
                        'flat round aria-label=' + repr(render_message("webui.render_global_search_results.accessible_name.next_page_c45c7218"))
                    ).tooltip(render_message("webui.render_global_search_results.tooltip.next_page_62ca3105"))
                    first_button.set_enabled(page_number > 1)
                    previous_button.set_enabled(page_number > 1)
                    next_button.set_enabled(page_number < page_count or bool(global_search_state.get("global_search_cursor")))
            restore_compact_result_anchor(global_search_state.pop("global_search_return_anchor", None))


    async def change_global_search_page(target_page: int) -> None:
        target_page = max(1, int(target_page))
        page_size = int(global_search_state.get("global_search_page_size", 10))
        while True:
            selected = global_search_state.get("global_search_filter", "all")
            visible_count = sum(
                selected == "all" or item["type"] == selected
                for item in global_search_state.get("global_search_items", [])
            )
            if (target_page - 1) * page_size < visible_count or not global_search_state.get("global_search_cursor"):
                break
            previous_cursor = global_search_state.get("global_search_cursor")
            await run_global_search(global_search_state["global_search_query"], load_more=True)
            if global_search_state.get("global_search_cursor") == previous_cursor:
                break
        selected = global_search_state.get("global_search_filter", "all")
        visible_count = sum(
            selected == "all" or item["type"] == selected
            for item in global_search_state.get("global_search_items", [])
        )
        page_count = max(1, (visible_count + page_size - 1) // page_size)
        global_search_state["global_search_page"] = min(target_page, page_count)
        render_global_search_results()


    def remember_global_result(item: dict[str, Any], resource: str) -> None:
        global_search_state["global_search_return_anchor"] = f"compact-result-{resource}-{int(item['id'])}"


    def set_global_result_expansion(resource: str, identifier: int, expanded: bool) -> None:
        key = f"{resource}:{int(identifier)}"
        expanded_results = global_search_state["global_search_expanded_results"]
        (expanded_results.add if expanded else expanded_results.discard)(key)


    async def open_global_record_from_result(record: dict[str, Any]) -> None:
        remember_global_result(record, "records")
        await open_global_record(int(record["id"]))


    async def open_global_aggregation_from_result(aggregation: dict[str, Any]) -> None:
        remember_global_result(aggregation, "aggregations")
        await open_global_aggregation(aggregation)


    async def open_global_record(record_id: int) -> None:
        discard_navigation_guard()
        await select_record_details(record_id)


    async def open_global_aggregation(aggregation: dict[str, Any]) -> None:
        discard_navigation_guard()
        await open_aggregation(aggregation)


    async def run_global_search(query: str, *, load_more: bool = False) -> None:
        if not get_principal():
            return
        revision = global_search_state.get("global_search_revision", 0) + 1
        global_search_state["global_search_revision"] = revision

        def is_current() -> bool:
            return (global_search_state.get("global_search_revision") == revision
                    and bool(get_principal())
                    and get_resource() == "full-text-search")

        query = query.strip()
        if not query:
            ui.notify(render_message("webui.run_global_search.notify.enter_words_to_search_for_317e3f34"), color="warning")
            return
        if not load_more:
            discard_navigation_guard()
            register_navigation("full-text-search", "Search results")
            enter_global_search(); global_search_state.update(global_search_query=query, global_search_items=[], global_search_cursor=None, global_search_filter='all', global_search_page=1, global_search_return_anchor=None, search_diagnostics_sent=None, global_search_expanded_results=set(), search_diagnostics_accepted=None, search_diagnostics_error=None)
            global_search_input.value = query
            global_search_input.update()
            await ui.run_javascript(
                f"history.replaceState(null, '', '/?q=' + encodeURIComponent({json.dumps(query)})); true",
                timeout=5,
            )
        if not is_current():
            return
        payload = global_search_payload(query, cursor=global_search_state.get("global_search_cursor") if load_more else None)
        if global_search_state["search_diagnostics_enabled"]:
            global_search_state["search_diagnostics_sent"] = payload
        global_search_state["global_search_loading"] = True
        global_search_state["global_search_error"] = None
        title.text = render_message("webui.run_global_search.text.search_results_ecc13a7a")
        subtitle.text = render_message("webui.run_global_search.text.records_files_and_aggregations_b4bdbe1c")
        show_authenticated_view()
        search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False); add_record_button.set_visibility(False)
        render_global_search_results()
        try:
            result = await api.full_text_search(payload)
            if not is_current():
                return
            result_items = list(result.get("items", []))
            record_items = [item for item in result_items if item.get("type") == "record"]
            async def load_global_matching_component_details(
                result_item: dict[str, Any],
            ) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
                record_id = int(result_item["record"]["id"])
                try:
                    capabilities, components = await asyncio.gather(
                        api.resource_capabilities("records", record_id),
                        api.component_page(record_id, limit=25),
                    )
                    return record_id, capabilities, components["items"]
                except ApiError:
                    return record_id, {}, []
            component_contexts = await asyncio.gather(*(
                load_global_matching_component_details(result_item) for result_item in record_items
            )) if record_items else []
            if not is_current():
                return
            component_details = {
                record_id: components for record_id, _, components in component_contexts
            }
            component_capabilities = {
                record_id: capabilities for record_id, capabilities, _ in component_contexts
            }
            for result_item in record_items:
                record_id = int(result_item["record"]["id"])
                result_item["authorized_component_details"] = component_details.get(record_id, [])
                result_item["record_capabilities"] = component_capabilities.get(record_id, {})
            global_search_state["global_search_items"].extend(result_items)
            global_search_state["global_search_cursor"] = result.get("next_cursor")
            global_search_state["global_search_pending"] = bool(result.get("index_freshness", {}).get("has_pending_content"))
            global_search_state["search_diagnostics_accepted"] = result.get("_debug")
        except ApiError as error:
            if is_current():
                global_search_state["global_search_error"] = error_message(error)
        finally:
            if is_current():
                global_search_state["global_search_loading"] = False
                render_global_search_results()


    def clear_global_search_session() -> None:
        """Discard private query state and invalidate outstanding search responses."""
        clear_advanced_workspace()
        discard_navigation_guard()
        invalidate_advanced_session()
        global_search_state.update(global_search_revision=global_search_state.get('global_search_revision', 0) + 1, global_search_query='', global_search_items=[], global_search_cursor=None, global_search_filter='all', global_search_page=1, global_search_return_anchor=None, global_search_expanded_results=set(), global_search_loading=False, global_search_error=None, global_search_pending=False, search_diagnostics_enabled=False, search_diagnostics_sent=None, search_diagnostics_accepted=None, search_diagnostics_error=None); clear_collection_results()
        global_search_input.value = ""
        global_search_input.update()


    return global_search_payload, render_safe_snippet, copy_diagnostic_json, render_search_diagnostics, render_global_search_results, change_global_search_page, remember_global_result, set_global_result_expansion, open_global_record_from_result, open_global_aggregation_from_result, open_global_record, open_global_aggregation, run_global_search, clear_global_search_session
