"""Existing aggregation behavior with explicit view dependencies."""
from __future__ import annotations
from typing import Any, Callable
from .api_client import ApiError
from .entities import ENTITIES
import asyncio
from .capabilities import can_add_from_collection
from .i18n_catalogue import render_message
from nicegui import ui

def build_aggregation_browser(
    *, add_button, add_record_button, aggregation_browse_mode, aggregation_search_mode, aggregation_state, api, bind_remote_scheme_select, current_direction, error_message, get_resource, guidance, open_aggregation, page_client, personal, principal, render_table, search_bar, show_record_details, table_container, tree_expander_icon,
):
    def set_aggregation_mode_controls(mode: str) -> None:
        for button, active in (
            (aggregation_search_mode, mode == "search"),
            (aggregation_browse_mode, mode == "browse"),
        ):
            button.props(remove="flat unelevated")
            button.props("unelevated" if active else "flat")


    async def select_aggregation_browser() -> None:
        aggregation_state["aggregation_mode"] = "browse"
        aggregation_state["aggregation_detail"] = None
        set_aggregation_mode_controls("browse")
        search_bar.set_visibility(False)
        guidance.text = render_message("webui.select_aggregation_browser.text.browse_published_classification_schemes_go_45d4b5c6")
        privileges = set(
            (principal() or {}).get("global_privileges", [])
        )
        add_button.set_visibility(can_add_from_collection("aggregations", privileges))
        add_button.text = render_message("webui.select_aggregation_browser.text.add_828a436b")
        add_button.update()
        add_record_button.set_visibility(False)
        table_container.clear()

        browse: dict[str, Any] = aggregation_state.setdefault("aggregation_browse", {
            "schemes": [], "scheme_id": None, "collections": {},
            "expanded": set(), "selected": None,
            "revision": 0,
        })

        def collection_key(kind: str, owner_id: int, collection: str) -> str:
            return f"{kind}:{owner_id}:{collection}"

        def collection_state(key: str, path: str) -> dict[str, Any]:
            return browse["collections"].setdefault(key, {
                "path": path, "items": [], "next_cursor": None, "total": 0,
                "loaded": False, "loading": False, "error": None, "query": "",
                "request_version": 0,
            })

        # Data belongs to this authenticated page invocation. Keep expansion,
        # filters and page lengths for return, but re-read rows after navigation.
        invocation = object()
        browse["invocation"] = invocation
        browse["opening"] = False

        def browser_active() -> bool:
            return (
                browse.get("invocation") is invocation
                and get_resource() == "aggregations"
                and aggregation_state.get("aggregation_mode") == "browse"
                and tree_panel is not None and not tree_panel.is_deleted
            )

        tree_panel: Any = None
        scheme_select: Any = None

        async def render_tree_preserving_scroll(*, anchor_id: str | None = None) -> None:
            anchor_expression = (
                f"document.getElementById('{anchor_id}')?.getBoundingClientRect().top ?? null"
                if anchor_id else "null"
            )
            if not browser_active():
                return
            scroll_position = await page_client.run_javascript(
                "({ page: window.scrollY || 0, "
                "tree: document.getElementById('aggregation-browser-tree')?.scrollTop || 0, "
                f"anchor: {anchor_expression} }})"
            )
            if not browser_active():
                return
            render_tree()
            anchor_top = (scroll_position or {}).get("anchor")
            anchor_top_javascript = "null" if anchor_top is None else str(float(anchor_top))
            anchor_restore = (
                f"const anchor = document.getElementById('{anchor_id}'); "
                f"if (anchor && {anchor_top_javascript} !== null) "
                f"tree.scrollTop += anchor.getBoundingClientRect().top - {float(anchor_top or 0)}; "
                if anchor_id else ""
            )
            await page_client.run_javascript(
                "requestAnimationFrame(() => requestAnimationFrame(() => { "
                "const tree = document.getElementById('aggregation-browser-tree'); "
                f"if (tree) tree.scrollTop = {float((scroll_position or {}).get('tree', 0))}; "
                f"if (tree) {{ {anchor_restore} }} "
                f"window.scrollTo(0, {float((scroll_position or {}).get('page', 0))}); "
                "}));"
            )

        async def select_browse_item(item: dict[str, Any]) -> None:
            if not browser_active() or browse.get("opening"):
                return
            browse["opening"] = True
            try:
                browse["scroll"] = await page_client.run_javascript(
                    "({page: window.scrollY || 0, tree: "
                    "document.getElementById('aggregation-browser-tree')?.scrollTop || 0})"
                )
                if not browser_active():
                    return
                browse["selected"] = (item["type"], item["id"])
                if item["type"] == "aggregation":
                    await open_aggregation(item)
                else:
                    await show_record_details(item)
            finally:
                browse["opening"] = False

        async def load_collection(
            key: str, *, append: bool = False, render: bool = True,
        ) -> None:
            current = browse["collections"].get(key)
            if not browser_active() or current is None or current["loading"]:
                return
            append_anchor_id = (
                browse_item_dom_id(current["items"][-1])
                if append and current["items"] else None
            )
            browse["revision"] += 1
            current["request_version"] += 1
            request_version = current["request_version"]
            current["loading"] = True
            current["error"] = None
            if render:
                await render_tree_preserving_scroll()
            try:
                result = await api.browse_page(
                    current["path"],
                    cursor=current["next_cursor"] if append else None,
                    query=current["query"],
                )
                if (
                    not browser_active()
                    or current["request_version"] != request_version
                    or browse["collections"].get(key) is not current
                ):
                    return
                existing = {entry["id"] for entry in current["items"]} if append else set()
                additions = [entry for entry in result["items"] if entry["id"] not in existing]
                current["items"] = [*current["items"], *additions] if append else additions
                current["next_cursor"] = result.get("next_cursor")
                current["total"] = int(result["total"])
                current["loaded"] = True
            except ApiError as error:
                if browser_active() and current["request_version"] == request_version:
                    current["error"] = error_message(error)
            finally:
                if browser_active() and current["request_version"] == request_version:
                    current["loading"] = False
                    if render:
                        await render_tree_preserving_scroll(anchor_id=append_anchor_id)

        def browse_item_dom_id(item: dict[str, Any]) -> str:
            if "is_terminal" in item:
                kind = "classification"
            elif "aggregation_number" in item:
                kind = "aggregation"
            else:
                kind = "record"
            return f"aggregation-browser-{kind}-{int(item['id'])}"

        async def filter_collection(key: str, value: str) -> None:
            current = browse["collections"][key]
            current["request_version"] += 1
            current.update(
                items=[], next_cursor=None, total=0, loaded=False,
                loading=False, error=None, query=value.strip(),
            )
            await load_collection(key)

        def render_collection_controls(key: str, noun: str) -> None:
            current = browse["collections"][key]
            if current["total"] <= 50 and not current["query"]:
                return
            with ui.row().classes("w-full items-center gap-1 py-1"):
                filter_input = ui.input(
                    render_message("webui.render_collection_controls.input.filter_noun_a1a1bf93", noun=noun), value=current["query"],
                ).props("outlined dense clearable").classes("grow")
                ui.button(
                    icon="search", on_click=lambda: filter_collection(key, filter_input.value or ""),
                ).props("flat round dense color=primary").tooltip(render_message("webui.render_collection_controls.tooltip.filter_these_noun_ee29d2dc", noun=noun))
                filter_input.on(
                    "keydown.enter", lambda: filter_collection(key, filter_input.value or "")
                )

        def render_continuation(key: str, noun: str, depth: int) -> None:
            current = browse["collections"][key]
            if not current.get("next_cursor"):
                return
            remaining = max(0, current["total"] - len(current["items"]))
            amount = min(50, remaining)
            with ui.button(
                on_click=lambda: load_collection(key, append=True), icon="more_horiz",
            ).props("flat dense no-caps color=primary").classes("w-full justify-start").style(
                f"padding-inline-start: {depth * 20 + 36}px"
            ):
                ui.label(
                    render_message("webui.render_continuation.label.load_amount_more_noun_item_count_of_total_4c5b6463", amount=amount, noun=noun, item_count=len(current['items']), total=current['total'])
                ).classes("text-xs")

        def render_collection_status(key: str, empty_text: str, depth: int) -> bool:
            current = browse["collections"][key]
            if current["loading"] and not current["items"]:
                with ui.row().classes("items-center gap-2 py-2 text-slate-400").style(
                    f"padding-inline-start: {depth * 20 + 36}px"
                ):
                    ui.spinner("dots", size="20px")
                    ui.label(render_message("webui.render_collection_status.label.loading_9be967d2")).classes("text-xs")
                return True
            if current["error"]:
                with ui.row().classes("items-center gap-2 py-2 text-negative").style(
                    f"padding-inline-start: {depth * 20 + 36}px"
                ):
                    ui.label(current["error"]).classes("text-xs")
                    ui.button(render_message("webui.render_collection_status.button.retry_a8d0f7d9"), on_click=lambda: load_collection(key)).props(
                        "flat dense no-caps color=negative"
                    )
                return True
            if current["loaded"] and not current["items"]:
                ui.label(empty_text).classes("text-xs text-slate-400 py-2").style(
                    f"padding-inline-start: {depth * 20 + 36}px"
                )
                return True
            return False

        async def toggle_classification(item: dict[str, Any]) -> None:
            node = ("classification", item["id"])
            if node in browse["expanded"]:
                browse["expanded"].remove(node)
                await render_tree_preserving_scroll()
                return
            browse["expanded"].add(node)
            collection = "aggregations" if item["is_terminal"] else "classifications"
            path = (
                f"classifications/{item['id']}/aggregations"
                if item["is_terminal"] else f"classifications/{item['id']}/children"
            )
            key = collection_key("classification", item["id"], collection)
            current = collection_state(key, path)
            if not current["loaded"]:
                await load_collection(key)
            else:
                await render_tree_preserving_scroll()

        async def toggle_aggregation(item: dict[str, Any]) -> None:
            node = ("aggregation", item["id"])
            if node in browse["expanded"]:
                browse["expanded"].remove(node)
                await render_tree_preserving_scroll()
                return
            browse["expanded"].add(node)
            child_key = collection_key("aggregation", item["id"], "aggregations")
            record_key = collection_key("aggregation", item["id"], "records")
            child_state = collection_state(
                child_key, f"aggregations/{item['id']}/children",
            )
            record_state = collection_state(
                record_key, f"aggregations/{item['id']}/records",
            )
            await render_tree_preserving_scroll()
            await asyncio.gather(*(
                load_collection(key, render=False)
                for key, value in ((child_key, child_state), (record_key, record_state))
                if not value["loaded"]
            ))
            await render_tree_preserving_scroll()

        def render_classification(item: dict[str, Any], depth: int) -> None:
            node = ("classification", item["id"])
            expanded = node in browse["expanded"]
            with ui.row().props(f"id={browse_item_dom_id(item)}").classes(
                "aggregation-browser-tree-row w-full items-center no-wrap rounded-lg py-1 pe-2 hover:bg-blue-50"
            ).style(f"padding-inline-start: {depth * 20 + 4}px"):
                disclosure = ui.button(
                    icon=tree_expander_icon(expanded),
                    on_click=lambda: toggle_classification(item),
                ).props("flat round dense size=sm color=blue-grey")
                disclosure.props["aria-label"] = item["title"]
                disclosure.props["aria-expanded"] = str(expanded).lower()
                ui.icon("label" if item["is_terminal"] else "schema", color="primary").classes("w-6")
                with ui.button(on_click=lambda: toggle_classification(item)).props(
                    f"flat no-caps align={'right' if current_direction['value'] == 'rtl' else 'left'}"
                ).classes("aggregation-browser-node-link grow min-w-0"):
                    with ui.column().classes("min-w-0 gap-0 text-start"):
                        ui.label(item["title"]).classes("text-sm font-semibold whitespace-normal break-words")
                        ui.label(item["code"]).classes("text-xs text-slate-400")
                ui.badge(render_message("webui.render_classification.badge.terminal_c550b780") if item["is_terminal"] else render_message("webui.render_classification.badge.branch_dd50f161"), color="primary").props("outline")
            if not expanded:
                return
            collection = "aggregations" if item["is_terminal"] else "classifications"
            key = collection_key("classification", item["id"], collection)
            current = browse["collections"].get(key)
            if current is None or render_collection_status(
                key,
                "No governed aggregations" if item["is_terminal"] else "No child classifications",
                depth + 1,
            ):
                return
            render_collection_controls(key, "aggregations" if item["is_terminal"] else "classifications")
            for child in current["items"]:
                if item["is_terminal"]:
                    render_aggregation(child, depth + 1)
                else:
                    render_classification(child, depth + 1)
            render_continuation(
                key, "aggregations" if item["is_terminal"] else "classifications", depth + 1,
            )

        def render_aggregation(item: dict[str, Any], depth: int) -> None:
            item["type"] = "aggregation"
            node = ("aggregation", item["id"])
            expanded = node in browse["expanded"]
            selected = browse["selected"] == node
            with ui.row().props(f"id={browse_item_dom_id(item)}").classes(
                "aggregation-browser-tree-row w-full items-center no-wrap rounded-lg py-1 pe-2 hover:bg-blue-50 "
                + ("bg-blue-50" if selected else "")
            ).style(f"padding-inline-start: {depth * 20 + 4}px"):
                has_content = item["child_aggregation_count"] or item["record_count"]
                with ui.element("div").classes("w-8 shrink-0"):
                    if has_content:
                        disclosure = ui.button(
                            icon=tree_expander_icon(expanded),
                            on_click=lambda: toggle_aggregation(item),
                        ).props("flat round dense size=sm color=blue-grey")
                        disclosure.props["aria-label"] = item["title"]
                        disclosure.props["aria-expanded"] = str(expanded).lower()
                ui.icon("folder", color="primary").classes("w-6")
                with ui.button(on_click=lambda: select_browse_item(item)).props(
                    f"flat no-caps align={'right' if current_direction['value'] == 'rtl' else 'left'}"
                ).classes("aggregation-browser-node-link grow min-w-0"):
                    with ui.column().classes("min-w-0 gap-0 text-start"):
                        ui.label(item["title"]).classes("text-sm font-semibold whitespace-normal break-words")
                        ui.label(item["aggregation_number"]).classes("text-xs text-slate-400")
                ui.label(render_message(
                    "webui.render_aggregation.label.heading_count_6ad646b7",
                    heading=render_message("navigation.item.records"), count=item["record_count"],
                )).classes("text-xs text-slate-400 shrink-0")
                ui.badge(
                    render_message("webui.render_aggregation.badge.closed_d0d85ac9")
                    if item.get("date_closed") else render_message("webui.open_aggregation.badge.open_88407b0f"),
                    color="amber-8" if item.get("date_closed") else "positive",
                ).props("outline")
            if not expanded:
                return
            for collection, heading, noun, empty in (
                ("aggregations", render_message("webui.open_aggregation.label.child_aggregations_cd3bce3a"), "child aggregations", "No child aggregations"),
                ("records", render_message("navigation.item.records"), "records", "No records in this aggregation"),
            ):
                count = item["child_aggregation_count"] if collection == "aggregations" else item["record_count"]
                if not count:
                    continue
                key = collection_key("aggregation", item["id"], collection)
                ui.label(render_message("webui.render_aggregation.label.heading_count_6ad646b7", heading=heading, count=count)).classes(
                    "text-[10px] font-semibold tracking-wider text-slate-400 py-1"
                ).style(f"padding-inline-start: {(depth + 1) * 20 + 36}px")
                if render_collection_status(key, empty, depth + 1):
                    continue
                render_collection_controls(key, noun)
                current = browse["collections"][key]
                for child in current["items"]:
                    if collection == "aggregations":
                        render_aggregation(child, depth + 1)
                    else:
                        render_record(child, depth + 1)
                render_continuation(key, noun, depth + 1)

        def render_record(item: dict[str, Any], depth: int) -> None:
            item["type"] = "record"
            selected = browse["selected"] == ("record", item["id"])
            with ui.row().props(f"id={browse_item_dom_id(item)}").classes(
                "aggregation-browser-tree-row w-full items-center no-wrap rounded-lg py-2 pe-2 hover:bg-blue-50 cursor-pointer "
                + ("bg-blue-50" if selected else "")
            ).style(f"padding-inline-start: {depth * 20 + 40}px"):
                ui.icon("description", color="primary", size="18px").classes("w-6")
                with ui.button(on_click=lambda: select_browse_item(item)).props(
                    f"flat no-caps align={'right' if current_direction['value'] == 'rtl' else 'left'}"
                ).classes("aggregation-browser-node-link grow min-w-0"):
                    with ui.column().classes("min-w-0 gap-0 text-start"):
                        ui.label(item["title"]).classes("text-sm font-semibold whitespace-normal break-words")
                        ui.label(item["record_number"]).classes("text-xs text-slate-400")
                if item["digital_component_count"]:
                    ui.badge(str(item["digital_component_count"]), color="blue-grey").props("outline")

        def render_tree() -> None:
            tree_panel.clear()
            with tree_panel:
                scheme_id = browse["scheme_id"]
                if scheme_id is None:
                    ui.label(render_message("webui.render_tree.label.choose_a_classification_scheme_to_begin_br_b8ecd124")).classes(
                        "text-sm text-slate-400 py-10 self-center"
                    )
                    return
                key = collection_key("scheme", scheme_id, "classifications")
                if key not in browse["collections"]:
                    return
                if render_collection_status(key, "This scheme has no root classifications", 0):
                    return
                current = browse["collections"][key]
                render_collection_controls(key, "classifications")
                for item in current["items"]:
                    render_classification(item, 0)
                render_continuation(key, "classifications", 0)

        async def select_browse_scheme(scheme_id: int | None) -> None:
            if scheme_id is None:
                return
            browse["revision"] += 1
            browse.update(
                scheme_id=int(scheme_id), collections={}, expanded=set(),
                selected=None,
            )
            key = collection_key("scheme", int(scheme_id), "classifications")
            collection_state(key, f"classification-schemes/{scheme_id}/roots")
            await load_collection(key)

        async def reload_visible_collections() -> None:
            async def reload_collection(key: str, current: dict[str, Any]) -> None:
                count = len(current["items"])
                current["loading"] = False
                current["request_version"] += 1
                await load_collection(key, render=False)
                while (
                    browser_active() and not current["error"]
                    and current["next_cursor"] and len(current["items"]) < count
                ):
                    await load_collection(key, append=True, render=False)
            await asyncio.gather(*(
                reload_collection(key, current)
                for key, current in list(browse["collections"].items())
                if current["loaded"] or current["loading"] or current["error"]
            ))
            if not browser_active():
                return
            render_tree()
            scroll = browse.get("scroll") or {}
            await page_client.run_javascript(
                "requestAnimationFrame(() => { const tree = "
                "document.getElementById('aggregation-browser-tree'); "
                f"if (tree) tree.scrollTop = {float(scroll.get('tree', 0))}; "
                f"window.scrollTo(0, {float(scroll.get('page', 0))}); }})"
            )

        with table_container:
            with ui.grid(columns="minmax(0, 1fr) auto").classes("w-full items-end gap-3 px-5 pt-5"):
                scheme_select = ui.select(
                    {}, label=render_message("webui.select_aggregation_browser.select.classification_scheme_bcbbfb3c"),
                ).props("outlined dense options-dense use-input input-debounce=0").classes("grow")
                bind_remote_scheme_select(scheme_select)
                ui.button(
                    icon="refresh",
                    on_click=lambda: select_browse_scheme(browse["scheme_id"]),
                ).props("flat round color=primary").tooltip(render_message("webui.select_aggregation_browser.tooltip.refresh_the_hierarchy_3ccde65c"))
            with ui.column().classes("w-full h-[720px] min-h-0 gap-0 p-5 pt-3"):
                with ui.card().classes(
                    "w-full h-full min-h-0 overflow-hidden shadow-none border border-slate-200 p-0"
                ):
                    with ui.grid(columns="auto minmax(0, 1fr)").classes("w-full items-center px-4 py-3 border-b border-slate-200"):
                        ui.icon("account_tree", color="primary")
                        ui.label(render_message("webui.select_aggregation_browser.label.classification_aggregation_and_record_tree_06d28fb7")).classes("font-semibold")
                    tree_panel = ui.column().props("id=aggregation-browser-tree").classes(
                        "w-full grow min-h-0 gap-0 overflow-y-auto p-2"
                    )
            with ui.expansion(
                render_message("aggregation_browser.heading.recent_activity"), icon="history",
            ).classes("w-full border-t border-slate-200"):
                with ui.row().classes("w-full p-4 gap-5 items-start"):
                    for heading, operation in (
                        (render_message("aggregation_browser.heading.recently_created"), "CREATE"),
                        (render_message("aggregation_browser.heading.recently_updated"), "UPDATE"),
                    ):
                        rows = [
                            item for item in personal.recent_activity.get("aggregations", [])
                            if item["_operation"] == operation
                        ]
                        with ui.column().classes("grow min-w-[280px] gap-2"):
                            ui.label(heading).classes("text-sm font-semibold text-slate-600")
                            if not rows:
                                ui.label(render_message("webui.select_aggregation_browser.label.nothing_here_yet_b8809aaa")).classes("text-xs text-slate-400")
                            for recent in rows:
                                with ui.row().classes(
                                    "w-full items-center gap-2 rounded-lg border border-slate-200 "
                                    "px-3 py-2 cursor-pointer hover:bg-blue-50"
                                ).on("click", lambda _, entry=recent: open_aggregation(entry)):
                                    ui.icon("folder", color="primary", size="18px")
                                    with ui.column().classes("grow min-w-0 gap-0"):
                                        ui.label(recent["title"]).classes("text-sm font-semibold truncate")
                                        ui.label(recent["aggregation_number"]).classes("text-xs text-slate-400")

        try:
            schemes = await api.browse_schemes()
            if not browser_active():
                return
            browse["schemes"] = schemes
            scheme_select.options = {
                item["id"]: (
                    f"{item['code']} — {item['title']}"
                    + (render_message("common.status.inactive_suffix") if item.get("date_deactivated") else "")
                ) for item in browse["schemes"]
            }
            scheme_select.update()
            if browse["schemes"]:
                available_ids = {item["id"] for item in browse["schemes"]}
                target_scheme_id = (
                    browse["scheme_id"]
                    if browse["scheme_id"] in available_ids
                    else browse["schemes"][0]["id"]
                )
                scheme_select.value = target_scheme_id
                scheme_select.update()
                root_key = collection_key("scheme", target_scheme_id, "classifications")
                if root_key in browse["collections"] and browse["collections"][root_key]["loaded"]:
                    with tree_panel:
                        ui.spinner("dots", size="20px")
                    await reload_visible_collections()
                else:
                    await select_browse_scheme(target_scheme_id)
            else:
                render_tree()
        except ApiError as error:
            if not browser_active():
                return
            with tree_panel:
                ui.label(error_message(error)).classes("text-negative p-4")
        scheme_select.on_value_change(lambda event: select_browse_scheme(event.value))


    async def select_aggregation_search() -> None:
        aggregation_state["aggregation_mode"] = "search"
        set_aggregation_mode_controls("search")
        search_bar.set_visibility(True)
        guidance.text = render_message("webui.select_aggregation_search.text.large_collections_are_search_first_to_avoi_cd3ab332")
        render_table(ENTITIES["aggregations"])


    return set_aggregation_mode_controls, select_aggregation_browser, select_aggregation_search
