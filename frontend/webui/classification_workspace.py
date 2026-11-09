from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable

from nicegui import ui

from .api_client import ApiError, ErmsApiClient
from .i18n_catalogue import render_message
from .retention_timeline import render_retention_stages

PAGE_SIZE = 25
CLASSIFICATION_WORKSPACE_SEARCH_FIELDS = ("code", "title", "description", "keywords")


async def classification_workspace(
    *, api: ErmsApiClient, container: Any, open_editor: Callable,
    show_entity_history: Callable, format_timestamp: Callable,
    display_value: Callable, error_message: Callable, entity_metadata_label: Callable,
    localized_disposition_value: Callable, register_page: Callable,
    active: Callable, preferences: dict[str, Any], direction: Callable,
    can_transfer: bool = False,
    initial_scheme_id: int | None = None,
    initial_classification_id: int | None = None,
) -> None:
    """One browser and mutually exclusive details; dependencies stay with the page.

    Data snapshots belong only to this instance/browser identity and language.
    Keys are (scheme ID, parent ID) for children and classification ID for paths.
    Return, refresh and every mutation invalidate snapshots. Only expansion,
    paging and filter preferences survive page recreation; failures never cache.
    Epoch checks prevent abandoned reads from rendering into a newer view.
    """
    workspace: dict[str, Any] = {
        "schemes": [], "scheme": None, "selected": None,
        "children": {}, "children_more": {}, "paths": {}, "counts": {},
        "expanded": set(preferences.get("expanded", [])),
        "expanded_schemes": set(preferences.get("expanded_schemes", [])),
        "scheme_sort": preferences.get("scheme_sort", "code"),
        "scheme_sort_direction": preferences.get("scheme_sort_direction", "asc"),
        "scheme_query": preferences.get("scheme_query", ""),
        "query": preferences.get("query", ""),
        "search_scheme": None,
        "search_results": [], "search_more": False, "search_total": 0,
        "schemes_more": False, "tree_revision": 0, "search_revision": 0, "view": "tree",
        "pending": set(),
    }
    with container:
        browser_host = ui.column().classes("classification-workspace w-full gap-3 p-3")
        with browser_host:
            ui.spinner(size="lg")
        detail_host = ui.column().classes("classification-workspace w-full gap-4")
    detail_host.set_visibility(False)

    def current(revision: int) -> bool:
        return active() and revision == workspace["tree_revision"]

    def remember() -> None:
        for key in ("scheme_sort", "scheme_sort_direction", "scheme_query", "query"):
            preferences[key] = workspace[key]
        preferences["search_scheme_id"] = (workspace["search_scheme"] or {}).get("id")
        preferences["expanded"] = sorted(workspace["expanded"])
        preferences["expanded_schemes"] = sorted(workspace["expanded_schemes"])

    def tree_expander_icon(expanded: bool) -> str:
        return "expand_more" if expanded else "chevron_left" if direction() == "rtl" else "chevron_right"

    def warn(error: ApiError) -> None:
        if active():
            ui.notify(error_message(error), color="negative", close_button=True)

    def scheme_lifecycle(scheme: dict[str, Any]) -> tuple[str, str]:
        if scheme.get("date_deactivated"):
            return render_message("webui.render_workspace_right.text.inactive_f9285c80"), "grey-7"
        published = scheme.get("date_published")
        if not published:
            return render_message("localization.filter.status.draft"), "blue-grey"
        try:
            publication = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            now = datetime.now(publication.tzinfo or timezone.utc)
            if publication > now:
                return render_message("webui.select_holds.select.scheduled_860621ba"), "orange"
        except (TypeError, ValueError):
            pass
        return render_message("entity_metadata.field.published"), "positive"

    def scheme_deletion_block_reason(scheme: dict[str, Any]) -> str | None:
        if scheme.get("date_first_used"):
            return render_message("classification_workspace.scheme.delete_blocked.used")
        if scheme.get("date_published"):
            return render_message("classification_workspace.scheme.delete_blocked.published")
        return None

    def metadata_value(
        label: str, value: Any, *, timestamp: bool = False,
    ) -> None:
        with ui.column().classes("gap-0 min-w-0 w-full"):
            ui.label(label.upper()).classes("component-meta-label")
            rendered = format_timestamp(value) if timestamp else display_value(value)
            ui.label(rendered).classes(
                "w-full text-sm text-slate-700 whitespace-pre-wrap break-words select-text"
            )

    def long_metadata_value(label: str, value: Any) -> None:
        with ui.column().classes("w-full gap-1 min-w-0"):
            ui.label(label.upper()).classes("component-meta-label")
            ui.label(display_value(value)).classes(
                "w-full min-h-[4.75rem] max-h-32 overflow-y-auto rounded-lg "
                "border border-slate-200 bg-slate-50 px-3 py-2 text-sm "
                "leading-6 text-slate-700 whitespace-pre-wrap break-words select-text"
            )


    async def load_children(
        scheme: dict[str, Any], parent_id: int | None, *, append: bool = False,
    ) -> list[dict[str, Any]]:
        revision = workspace["tree_revision"]
        key = (scheme["id"], parent_id)
        existing = workspace["children"].get(key, []) if append else []
        rows = await api.list(
            "classifications", classification_scheme_id=scheme["id"],
            limit=PAGE_SIZE + 1, offset=len(existing),
            **({"roots_only": True} if parent_id is None else {"parent_classification_id": parent_id}),
        )
        if current(revision):
            preferences.setdefault("branch_pages", {})[f"{scheme['id']}:{parent_id}"] = (len(existing) // PAGE_SIZE + 1)
            workspace["children"][key] = [*existing, *rows[:PAGE_SIZE]]
            workspace["children_more"][key] = len(rows) > PAGE_SIZE
        return rows[:PAGE_SIZE]

    async def load_classification_path(classification_id: int) -> list[dict[str, Any]]:
        if classification_id not in workspace["paths"]:
            revision = workspace["tree_revision"]
            path = await api.classification_path(classification_id)
            if not current(revision):
                raise asyncio.CancelledError
            workspace["paths"][classification_id] = path
        return workspace["paths"][classification_id]

    async def load_scheme_counts(schemes: list[dict[str, Any]]) -> None:
        revision = workspace["tree_revision"]
        rows = await api.request("GET", "/api/v1/classification-schemes/classification-counts")
        if not current(revision):
            return
        workspace["counts"] = {
            row["classification_scheme_id"]: (row["branch_count"], row["terminal_count"])
            for row in rows
        }

    async def load_schemes(*, append: bool = False) -> None:
        revision = workspace["tree_revision"]
        existing = workspace["schemes"] if append else []
        term = workspace["scheme_query"].strip()
        if term:
            # Filtering uses the existing search API, never just the loaded page.
            result = await api.search_request("classification-schemes", {
                "where": {"or": [
                    {"field": field, "operator": "contains_ci", "value": term}
                    for field in ("code", "title", "description")
                ]},
                "sort": [{"field": "code", "direction": "asc"}],
                "limit": PAGE_SIZE + 1, "offset": len(existing),
            })
            rows = result["items"]
        else:
            rows = await api.list(
                "classification-schemes", sort=workspace["scheme_sort"],
                direction=workspace["scheme_sort_direction"],
                limit=PAGE_SIZE + 1, offset=len(existing),
            )
        if current(revision):
            preferences["scheme_pages"] = len(existing) // PAGE_SIZE + 1
            workspace["schemes"] = [*existing, *rows[:PAGE_SIZE]]
            workspace["schemes_more"] = len(rows) > PAGE_SIZE

    async def run_search(*, append: bool = False) -> None:
        revision = workspace["tree_revision"]
        workspace["search_revision"] += 1
        search_revision = workspace["search_revision"]
        term = workspace["query"].strip()
        if not term or not workspace["search_scheme"]:
            workspace["search_results"] = []
            workspace["search_more"] = False
            return
        existing = workspace["search_results"] if append else []
        result = await api.search_request("classifications", {
            "where": {"and": [
                {"field": "classification_scheme_id", "operator": "eq", "value": workspace["search_scheme"]["id"]},
                {"or": [
                    {"field": field, "operator": "contains_ci", "value": term}
                    for field in CLASSIFICATION_WORKSPACE_SEARCH_FIELDS
                ]},
            ]},
            "sort": [{"field": "code", "direction": "asc"}],
            "limit": PAGE_SIZE + 1, "offset": len(existing),
        })
        if current(revision) and search_revision == workspace["search_revision"]:
            workspace["search_results"] = [*existing, *result["items"][:PAGE_SIZE]]
            workspace["search_more"] = len(result["items"]) > PAGE_SIZE
            workspace["search_total"] = result["total"]

    async def refresh_browser() -> None:
        workspace["tree_revision"] += 1
        revision = workspace["tree_revision"]
        workspace["children"].clear()
        workspace["children_more"].clear()
        workspace["paths"].clear()
        try:
            if workspace["search_scheme"] is None and preferences.get("search_scheme_id"):
                workspace["search_scheme"] = await api.get("classification-schemes", preferences["search_scheme_id"])
                if not current(revision):
                    return
            scheme_pages = preferences.get("scheme_pages", 1)
            branch_pages = dict(preferences.get("branch_pages", {}))
            await asyncio.gather(load_schemes(), run_search())
            for _ in range(1, scheme_pages):
                if not current(revision) or not workspace["schemes_more"]:
                    break
                await load_schemes(append=True)
            if not current(revision):
                return
            async def restore_branch(scheme: dict[str, Any], parent_id: int | None) -> None:
                await load_children(scheme, parent_id)
                key = (scheme["id"], parent_id)
                for _ in range(1, branch_pages.get(f"{scheme['id']}:{parent_id}", 1)):
                    if not current(revision) or not workspace["children_more"].get(key):
                        break
                    await load_children(scheme, parent_id, append=True)
                rows = workspace["children"].get(key, [])
                if not current(revision):
                    return
                await asyncio.gather(*(
                    restore_branch(scheme, row["id"]) for row in rows
                    if not row["is_terminal"] and row["id"] in workspace["expanded"]
                ))
            await asyncio.gather(*(
                restore_branch(scheme, None) for scheme in workspace["schemes"]
                if scheme["id"] in workspace["expanded_schemes"]
            ))
            if current(revision):
                render_browser()
        except ApiError as error:
            if current(revision):
                warn(error)
                if not workspace["schemes"]:
                    browser_host.clear()
                    with browser_host:
                        ui.label(error_message(error)).classes("text-negative")
                        ui.button(render_message("classification_browser.retry"), on_click=refresh_browser).props("outline no-caps")

    async def show_tree() -> None:
        register_page("classification-workspace", None)
        workspace["view"] = "tree"
        browser_host.set_visibility(True)
        detail_host.set_visibility(False)
        await refresh_browser()

    async def toggle_scheme(scheme: dict[str, Any]) -> None:
        revision = workspace["tree_revision"]
        key = (scheme["id"], None)
        if key in workspace["pending"]:
            return
        workspace["pending"].add(key)
        try:
            if scheme["id"] in workspace["expanded_schemes"]:
                workspace["expanded_schemes"].remove(scheme["id"])
            else:
                if (scheme["id"], None) not in workspace["children"]:
                    await load_children(scheme, None)
                if not current(revision):
                    return
                workspace["expanded_schemes"].add(scheme["id"])
            remember()
            render_browser()
        except ApiError as error:
            if current(revision):
                warn(error)
        finally:
            workspace["pending"].discard(key)

    async def toggle_branch(scheme: dict[str, Any], item: dict[str, Any]) -> None:
        revision = workspace["tree_revision"]
        key = (scheme["id"], item["id"])
        if key in workspace["pending"]:
            return
        workspace["pending"].add(key)
        try:
            if item["id"] in workspace["expanded"]:
                workspace["expanded"].remove(item["id"])
            else:
                if (scheme["id"], item["id"]) not in workspace["children"]:
                    await load_children(scheme, item["id"])
                if not current(revision):
                    return
                workspace["expanded"].add(item["id"])
            remember()
            render_browser()
        except ApiError as error:
            if current(revision):
                warn(error)
        finally:
            workspace["pending"].discard(key)

    async def more_children(scheme: dict[str, Any], parent_id: int | None) -> None:
        revision = workspace["tree_revision"]
        key = (scheme["id"], parent_id)
        if key in workspace["pending"]:
            return
        workspace["pending"].add(key)
        try:
            await load_children(scheme, parent_id, append=True)
            if current(revision):
                render_browser()
        except ApiError as error:
            if current(revision):
                warn(error)
        finally:
            workspace["pending"].discard(key)

    async def more_schemes() -> None:
        revision = workspace["tree_revision"]
        key = ("schemes", None)
        if key in workspace["pending"]:
            return
        workspace["pending"].add(key)
        try:
            await load_schemes(append=True)
            if current(revision):
                render_browser()
        except ApiError as error:
            if current(revision):
                warn(error)
        finally:
            workspace["pending"].discard(key)

    async def search_in_scheme(scheme: dict[str, Any]) -> None:
        workspace.update(search_scheme=scheme, query="", search_results=[], search_more=False)
        remember()
        await show_tree()

    def icon_action(icon: str, label: str, callback: Callable) -> Any:
        button = ui.button(icon=icon, on_click=callback).props("flat round dense color=primary")
        button.props["aria-label"] = label
        button.tooltip(label)
        return button

    def node_link(item: dict[str, Any], callback: Callable, *, inactive: bool = False, icon: str | None = None) -> None:
        button = ui.button(on_click=callback).props(
            "flat dense no-caps align=left color=" + ("grey-7" if inactive else "primary")
        ).classes("classification-node-button min-w-0 max-w-full text-start")
        if icon:
            button.classes("w-full")
        button.props["aria-label"] = f"{item['code']} — {item['title']}"
        button.tooltip(item["title"])
        if icon in {"label", "schema", "account_tree"}:
            button.classes("classification-directional-icon")
        # Explicit NiceGUI children avoid Quasar's physical on-left icon margin.
        # A logical flex gap works in both directions; only the title truncates.
        with button, ui.row(wrap=False).classes("w-full min-w-0 items-center gap-3"):
            if icon:
                ui.icon(icon, size="20px").classes("shrink-0")
            with ui.row(wrap=False).classes("grow min-w-0 items-center gap-1"):
                ui.label(item["code"]).props("dir=auto").classes("shrink-0 whitespace-nowrap")
                ui.label(f"— {item['title']}").props("dir=auto").classes("min-w-0 truncate")

    def render_tree_level(scheme: dict[str, Any], parent_id: int | None, depth: int = 1, ancestor_inactive: bool = False) -> None:
        key = (scheme["id"], parent_id)
        for item in workspace["children"].get(key, []):
            inactive = bool(scheme.get("date_deactivated") or ancestor_inactive or item.get("date_deactivated"))
            with ui.row().classes("w-full items-center no-wrap gap-2 py-1").style(f"padding-inline-start:{depth * 20}px"):
                with ui.row().classes("w-8 shrink-0 justify-center"):
                    if not item["is_terminal"]:
                        ui.button(icon=tree_expander_icon(item["id"] in workspace["expanded"]), on_click=lambda _, s=scheme, n=item: toggle_branch(s, n)).props(f"flat round dense aria-label={render_message('classification_browser.toggle_branch')!r} aria-expanded={str(item['id'] in workspace['expanded']).lower()}").tooltip(render_message("classification_browser.toggle_branch"))
                with ui.column().classes("grow min-w-0 gap-0"):
                    node_link(item, lambda _, n=item: focus_classification(n), inactive=inactive, icon="label" if item["is_terminal"] else "schema")
                if inactive:
                    text = render_message("webui.render_tree_level.text.inactive_via_scheme_f423139b") if scheme.get("date_deactivated") else render_message("webui.render_tree_level.text.inactive_83867934") if item.get("date_deactivated") else render_message("webui.render_tree_level.text.inactive_via_parent_29212032")
                else:
                    text = render_message("webui.render_tree_level.badge.terminal_522c0184") if item["is_terminal"] else render_message("webui.render_tree_level.badge.branch_e37cab95")
                ui.badge(text, color="grey-7" if inactive else "primary").props("outline")
                if not item["is_terminal"]:
                    icon_action("add", render_message("webui.render_workspace_right.tooltip.add_child_classification_beneath_title_b82facfa", title=item["title"]), lambda _, s=scheme, n=item: create_classification(n, scheme=s))
            if not item["is_terminal"] and item["id"] in workspace["expanded"]:
                render_tree_level(scheme, item["id"], depth + 1, inactive)
        if not workspace["children"].get(key):
            ui.label(render_message("webui.render_workspace_right.label.this_scheme_has_no_classifications_yet_e76fd30f" if parent_id is None else "webui.render_tree_level.label.no_child_classifications_81d396e2")).classes("text-sm text-slate-500").style(f"padding-inline-start:{depth * 20 + 40}px")
        if workspace["children_more"].get(key):
            ui.button(render_message("webui.render_collection.button.load_more_755f4879"), on_click=lambda: more_children(scheme, parent_id)).props("flat no-caps").style(f"margin-inline-start:{depth * 20}px")

    def render_browser() -> None:
        if not active() or workspace["view"] != "tree":
            return
        browser_host.clear()
        with browser_host:
            with ui.row().classes("w-full items-center gap-2"):
                ui.label(render_message("webui.render_workspace_right.label.classification_tree_69593539")).classes("text-lg font-semibold grow")
                if can_transfer:
                    from .classification_transfer import import_dialog
                    def open_import():
                        revision = workspace["tree_revision"]
                        import_dialog(api, lambda: current(revision) and workspace["view"] == "tree", refresh_browser, error_message)
                    ui.button(render_message("classification_transfer.import"), icon="upload", on_click=open_import).props("outline no-caps")
                ui.button(render_message("webui.select_classification_workspace.button.add_scheme_ff7a6bd6"), icon="add", on_click=create_scheme).props("unelevated no-caps")
                icon_action("refresh", render_message("webui.render_workspace_right.tooltip.refresh_tree_e83ccdf0"), refresh_browser)
            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                scheme_filter = ui.input(render_message("webui.select_classification_workspace.input.filter_schemes_a7f4591e"), value=workspace["scheme_query"]).props("outlined dense clearable").classes("grow")
                async def filter_schemes() -> None:
                    workspace["scheme_query"] = scheme_filter.value or ""
                    preferences["scheme_pages"] = 1
                    remember()
                    await refresh_browser()
                scheme_filter.on("keydown.enter", filter_schemes)
                ui.button(render_message("webui.render_workspace_right.button.search_be6d78e6"), icon="search", on_click=filter_schemes).props("outline no-caps")
                if not workspace["scheme_query"]:
                    scheme_sort = ui.select({
                        "code": render_message("webui.select_classification_workspace.select.code_d3581de2"),
                        "title": render_message("webui.select_classification_workspace.select.title_60b91cb4"),
                        "created": render_message("webui.select_classification_workspace.select.creation_order_1f954421"),
                        "published_status": render_message("webui.select_classification_workspace.select.status_5c0d1bcb"),
                    }, value=workspace["scheme_sort"], label=render_message("webui.select_classification_workspace.select.sort_by_67f4fa9f")).props("outlined dense options-dense").classes("w-44")
                    async def sort_changed() -> None:
                        workspace["scheme_sort"] = scheme_sort.value
                        preferences["scheme_pages"] = 1
                        remember()
                        await refresh_browser()
                    scheme_sort.on_value_change(sort_changed)
                    async def reverse_sort() -> None:
                        workspace["scheme_sort_direction"] = "desc" if workspace["scheme_sort_direction"] == "asc" else "asc"
                        preferences["scheme_pages"] = 1
                        remember()
                        await refresh_browser()
                    ui.button(icon="arrow_upward" if workspace["scheme_sort_direction"] == "asc" else "arrow_downward", on_click=reverse_sort).props("flat round dense").tooltip(render_message("webui.select_classification_workspace.tooltip.reverse_sort_direction_98ba265c"))
            if workspace["search_scheme"]:
                search_scheme = workspace["search_scheme"]
                with ui.card().classes("w-full shadow-none border border-blue-100 bg-blue-50 gap-2"):
                    node_link(search_scheme, lambda: select_scheme(search_scheme))
                    with ui.row().classes("w-full items-center gap-2"):
                        query_control = ui.input(render_message("webui.render_workspace_right.input.search_this_scheme_8fc08483"), value=workspace["query"]).props("outlined dense clearable").classes("grow")
                        async def search_now() -> None:
                            workspace["query"] = query_control.value or ""
                            remember()
                            try:
                                await run_search()
                                render_browser()
                            except ApiError as error:
                                warn(error)
                        async def clear_search() -> None:
                            workspace["search_revision"] += 1
                            workspace.update(search_scheme=None, query="", search_results=[], search_more=False)
                            remember()
                            render_browser()
                        query_control.on("keydown.enter", search_now)
                        ui.button(render_message("webui.render_workspace_right.button.search_be6d78e6"), on_click=search_now).props("unelevated no-caps")
                        ui.button(render_message("webui.render_workspace_right.button.clear_0d070407"), on_click=clear_search).props("flat no-caps")
                    if workspace["query"]:
                        ui.label(render_message("webui.render_workspace_right.label.search_result_count_matching_classificatio_1718c40f", search_result_count=workspace["search_total"])).classes("font-semibold")
                    for result in workspace["search_results"]:
                        node_link(result, lambda _, n=result: focus_classification(n, reveal=True))
                    if workspace["query"] and not workspace["search_results"]:
                        ui.label(render_message("webui.render_workspace_right.label.no_classifications_match_this_search_3e1025e9"))
                    if workspace["search_more"]:
                        async def more_search() -> None:
                            try:
                                await run_search(append=True)
                                render_browser()
                            except ApiError as error:
                                warn(error)
                        ui.button(render_message("webui.render_collection.button.load_more_755f4879"), on_click=more_search).props("flat no-caps")
            with ui.column().classes("w-full gap-1"):
                for scheme in workspace["schemes"]:
                    label, color = scheme_lifecycle(scheme)
                    with ui.row().classes("w-full items-center no-wrap gap-2 rounded-lg p-2 " + ("bg-slate-100" if scheme.get("date_deactivated") else "bg-blue-50")):
                        ui.button(icon=tree_expander_icon(scheme["id"] in workspace["expanded_schemes"]), on_click=lambda _, s=scheme: toggle_scheme(s)).props(f"flat round dense aria-label={render_message('classification_browser.toggle_scheme')!r} aria-expanded={str(scheme['id'] in workspace['expanded_schemes']).lower()}").tooltip(render_message("classification_browser.toggle_scheme"))
                        with ui.column().classes("grow min-w-0 gap-0"):
                            node_link(scheme, lambda _, s=scheme: select_scheme(s), inactive=bool(scheme.get("date_deactivated")), icon="account_tree")
                            description = (scheme.get("localized") or {}).get("description") or scheme.get("description")
                            if description:
                                ui.label(description).classes("w-full text-xs text-slate-500 truncate").tooltip(description)
                        ui.badge(label, color=color).props("outline")
                        icon_action("search", render_message("webui.render_workspace_right.input.search_this_scheme_8fc08483"), lambda _, s=scheme: search_in_scheme(s))
                        icon_action("add", render_message("webui.render_workspace_right.tooltip.add_root_classification_32ac07fe"), lambda _, s=scheme: create_classification(scheme=s))
                    if scheme["id"] in workspace["expanded_schemes"]:
                        render_tree_level(scheme, None)
                if not workspace["schemes"]:
                    ui.label(render_message("webui.render_scheme_list.label.no_matching_schemes_2a601365")).classes("text-slate-500 p-6")
                if workspace["schemes_more"]:
                    ui.button(render_message("webui.render_collection.button.load_more_755f4879"), on_click=more_schemes).props("flat no-caps")
    def render_rule_details(rule: dict[str, Any] | None) -> None:
        if rule is None:
            ui.label(render_message("webui.render_rule_details.label.no_retention_rule_is_defined_here_c2ad525c")).classes("text-sm text-slate-500")
            return
        render_retention_stages(rule, localized_disposition_value)
        long_metadata_value(entity_metadata_label("Retention and disposal instructions"), rule.get("instructions"))

    @contextmanager
    def detail_layout(scheme: dict, selected: dict | None, has_children: bool = False):
        # Reuse the aggregation detail grid, including its RTL and narrow layout.
        with ui.grid().classes("aggregation-command-layout w-full"):
            with ui.column().classes("aggregation-command-summary w-full gap-4"):
                yield
            with ui.column().classes("aggregation-command-controls"):
                detail_actions(scheme, selected, has_children)

    def detail_actions(scheme: dict[str, Any], selected: dict[str, Any] | None, has_children: bool = False) -> None:
        with ui.card().classes("detail-surface aggregation-actions-panel classification-actions-panel shadow-none p-4 gap-3"):
            ui.label(render_message("classification_details.actions.classification" if selected else "classification_details.actions.scheme")).classes("aggregation-panel-heading w-full")
            ui.label(render_message("classification_details.actions.metadata")).classes("aggregation-action-group-label")
            with ui.row().classes("aggregation-overview-actions w-full"):
                ui.button(render_message("webui.render_workspace_right.button.edit_a536c992") if selected else render_message("webui.render_workspace_right.button.edit_scheme_4406dbed"), icon="edit", on_click=edit_selected if selected else lambda: edit_scheme(scheme)).props("outline dense no-caps")
                if selected is None or not selected["is_terminal"]:
                    ui.button(render_message("classification_browser.add_child") if selected else render_message("classification_browser.add_root"), icon="add", on_click=lambda: create_classification(selected, scheme=scheme)).props("outline dense no-caps")
                if selected is None:
                    ui.button(render_message("webui.render_workspace_right.input.search_this_scheme_8fc08483"), icon="search", on_click=lambda: search_in_scheme(scheme)).props("outline dense no-caps")
            if selected is None and can_transfer:
                from .classification_transfer import export_control
                revision = workspace["tree_revision"]
                export_control(api, scheme, lambda: current(revision) and workspace["view"] == "scheme" and (workspace["scheme"] or {}).get("id") == scheme["id"], error_message)
            ui.label(render_message("classification_details.actions.lifecycle")).classes("aggregation-action-group-label")
            with ui.row().classes("aggregation-overview-actions w-full"):
                if selected is None:
                    if not scheme.get("date_published"):
                        ui.button(render_message("webui.render_workspace_right.button.publish_2e621852"), icon="publish", on_click=lambda: publish_workspace_scheme(scheme)).props("outline dense no-caps")
                    else:
                        unpublish = ui.button(render_message("webui.render_workspace_right.button.unpublish_57f099a0"), icon="unpublished", on_click=lambda: unpublish_workspace_scheme(scheme)).props("outline dense no-caps")
                        if scheme.get("date_first_used"):
                            unpublish.disable()
                            unpublish.tooltip(render_message("webui.render_workspace_right.tooltip.schemes_that_have_governed_aggregations_ca_423d00b9"))
                item = selected or scheme
                ui.button(render_message("webui.render_workspace_right.button.reactivate_b2117181") if item.get("date_deactivated") else render_message("webui.render_workspace_right.button.deactivate_ee74ba2e"), icon="toggle_on" if item.get("date_deactivated") else "toggle_off", color="positive" if item.get("date_deactivated") else "negative", on_click=lambda: change_classification_lifecycle(item) if selected else change_workspace_scheme_lifecycle(item)).props("outline dense no-caps")
                if selected:
                    reason = classification_deletion_reason(scheme, selected, has_children)
                    delete_label = render_message("webui.render_workspace_right.button.delete_f1ebfe66")
                else:
                    reason = scheme_deletion_block_reason(scheme)
                    branches, terminals = workspace["counts"].get(scheme["id"], (0, 0))
                    delete_label = render_message("webui.render_workspace_right.text.delete_scheme_and_classifications_189d4401") if branches + terminals else render_message("webui.render_workspace_right.text.delete_scheme_ee677085")
                delete_button = ui.button(delete_label, icon="delete_outline", color="negative", on_click=lambda: confirm_delete_classification(item) if selected else confirm_delete_workspace_scheme(item)).props("outline dense no-caps")
            if reason:
                delete_button.disable()
                delete_button.tooltip(reason)
                with ui.row().classes("w-full items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2"):
                    ui.icon("info", color="amber-8", size="18px")
                    ui.label(reason).classes("text-xs text-amber-900")
            ui.label(render_message("classification_details.actions.audit")).classes("aggregation-action-group-label")
            with ui.row().classes("aggregation-overview-actions w-full"):
                ui.button(render_message("webui.render_workspace_right.button.event_history_6802c7be"), icon="history", on_click=lambda: show_entity_history("classifications" if selected else "classification-schemes", selected or scheme)).props("outline dense no-caps")

    def classification_deletion_reason(scheme: dict, selected: dict, has_children: bool) -> str | None:
        if scheme.get("date_deactivated"):
            return render_message("webui.render_workspace_right.text.reactivate_the_scheme_before_deleting_clas_14788563")
        if scheme.get("date_published"):
            return render_message("webui.render_workspace_right.text.unpublish_the_scheme_before_deleting_class_98f71b2c")
        if selected.get("date_first_used"):
            return render_message("webui.render_workspace_right.text.this_classification_has_governed_an_aggreg_b5e94f69")
        if has_children:
            return render_message("webui.render_workspace_right.text.remove_child_classifications_first_414ee64a")
        return None

    def identity(scheme: dict, selected: dict | None = None) -> None:
        item = selected or scheme
        with ui.card().classes("detail-surface w-full shadow-none p-5 gap-3"):
            with ui.row().classes("w-full items-start gap-3"):
                ui.avatar(icon="label" if selected and selected["is_terminal"] else "schema" if selected else "account_tree", color="blue-1", text_color="primary", size="48px").classes("classification-directional-icon")
                with ui.column().classes("grow min-w-0 gap-1"):
                    ui.label(item["code"]).classes("text-sm text-primary font-semibold whitespace-normal break-all")
                    ui.label(item["title"]).classes("text-xl font-semibold whitespace-normal break-words")
                ui.button(render_message("classification_browser.back_to_tree"), icon="arrow_forward" if direction() == "rtl" else "arrow_back", on_click=show_tree).props("flat dense no-caps")
            if selected is None:
                label, color = scheme_lifecycle(scheme)
                ui.badge(label, color=color).props("outline")
            else:
                ui.badge(render_message("webui.render_workspace_right.badge.terminal_3424e6bd") if selected["is_terminal"] else render_message("webui.render_workspace_right.badge.branch_5a8c9ddf"), color="primary").props("outline")
                with ui.row().classes("w-full items-center gap-1 flex-wrap"):
                    node_link(scheme, lambda: select_scheme(scheme))
                    for ancestor in workspace["paths"][selected["id"]][:-1]:
                        ui.icon("chevron_left" if direction() == "rtl" else "chevron_right", size="16px")
                        node_link(ancestor, lambda _, node=ancestor: focus_classification(node))
            localized = item.get("localized") or {}
            long_metadata_value(entity_metadata_label("Description"), localized.get("description") or item.get("description"))

    def loading_details() -> None:
        workspace["view"] = "loading"
        browser_host.set_visibility(False)
        detail_host.set_visibility(True)
        detail_host.clear()
        with detail_host:
            ui.button(render_message("classification_browser.back_to_tree"), on_click=show_tree).props("flat no-caps")
            ui.spinner(size="lg")

    async def select_scheme(scheme: dict[str, Any]) -> None:
        register_page("classification-scheme-details", scheme)
        loading_details()
        workspace["tree_revision"] += 1
        revision = workspace["tree_revision"]
        try:
            fresh, _ = await asyncio.gather(api.get("classification-schemes", scheme["id"]), load_scheme_counts([scheme]))
            if not current(revision):
                return
            register_page("classification-scheme-details", fresh)
            workspace.update(scheme=fresh, selected=None, view="scheme")
            browser_host.set_visibility(False)
            detail_host.set_visibility(True)
            detail_host.clear()
            scheme = fresh
            with detail_host, detail_layout(scheme, None):
                identity(scheme)
                with ui.card().classes("detail-surface w-full shadow-none p-5 gap-4"):
                    ui.label(render_message("webui.render_workspace_right.label.scheme_information_b95e9ac6")).classes("text-lg font-semibold")
                    with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"):
                        metadata_value(entity_metadata_label("Code"), scheme.get("code"))
                        metadata_value(render_message("webui.open_aggregation.label.lifecycle_118239ec"), scheme_lifecycle(scheme)[0])
                        metadata_value(entity_metadata_label("Edition"), scheme.get("edition"))
                        metadata_value(entity_metadata_label("Authority"), scheme.get("authority"))
                        metadata_value(entity_metadata_label("Published"), scheme.get("date_published"), timestamp=True)
                        metadata_value(render_message("classification_workspace.metadata.first_used"), scheme.get("date_first_used"), timestamp=True)
                        metadata_value(entity_metadata_label("Deactivated"), scheme.get("date_deactivated"), timestamp=True)
                        metadata_value(render_message("dashboard.activity.created"), scheme.get("date_created"), timestamp=True)
                        metadata_value(render_message("webui.render_governance_cards.text.last_updated_fdb63867"), scheme.get("date_updated"), timestamp=True)
                    localized = scheme.get("localized") or {}
                    long_metadata_value(entity_metadata_label("Scope note"), localized.get("scope_note") or scheme.get("scope_note"))
                    branches, terminals = workspace["counts"].get(scheme["id"], (0, 0))
                    ui.label(render_message("webui.render_scheme_list.label.branches_value_terminals_value_2_c95fc338", branches=branches, terminals=terminals)).classes("text-sm text-slate-500")
        except ApiError as error:
            if current(revision):
                detail_error(error, lambda: select_scheme(scheme))

    def detail_error(error: ApiError, retry: Callable) -> None:
        if not active():
            return
        detail_host.set_visibility(True)
        browser_host.set_visibility(False)
        detail_host.clear()
        with detail_host:
            ui.label(error_message(error)).classes("text-negative")
            ui.button(render_message("classification_browser.retry"), on_click=retry).props("outline no-caps")
            ui.button(render_message("classification_browser.back_to_tree"), on_click=show_tree).props("flat no-caps")

    async def focus_classification(item: dict[str, Any], *, reveal: bool = False) -> None:
        register_page("classification-details", item)
        loading_details()
        workspace["tree_revision"] += 1
        revision = workspace["tree_revision"]
        workspace["paths"].pop(item["id"], None)
        try:
            selected = await api.get("classifications", item["id"])
            if not current(revision):
                return
            scheme, path, direct_result, effective_result, children = await asyncio.gather(
                api.get("classification-schemes", selected["classification_scheme_id"]),
                load_classification_path(selected["id"]),
                optional_rule(selected["id"], effective=False),
                optional_rule(selected["id"], effective=True),
                api.list("classifications", classification_scheme_id=selected["classification_scheme_id"], parent_classification_id=selected["id"], limit=1),
            )
            if not current(revision):
                return
            register_page("classification-details", selected)
            workspace.update(scheme=scheme, selected=selected, view="classification")
            if reveal:
                workspace["expanded_schemes"].add(scheme["id"])
                workspace["expanded"].update(node["id"] for node in path[:-1])
                remember()
            browser_host.set_visibility(False)
            detail_host.set_visibility(True)
            detail_host.clear()
            with detail_host, detail_layout(scheme, selected, bool(children)):
                identity(scheme, selected)
                inactive_ancestor = next((node for node in path[:-1] if node.get("date_deactivated")), None)
                if scheme.get("date_deactivated"):
                    effective_status = render_message("webui.render_workspace_right.text.inactive_via_scheme_84b8722d")
                    explanation = render_message("webui.render_workspace_right.text.the_scheme_code_title_is_deactivated_24061b49", code=scheme["code"], title=scheme["title"])
                elif selected.get("date_deactivated"):
                    effective_status = render_message("webui.render_workspace_right.text.inactive_f9285c80")
                    explanation = render_message("webui.render_workspace_right.text.this_classification_is_directly_deactivate_1511167f")
                elif inactive_ancestor:
                    effective_status = render_message("webui.render_workspace_right.text.inactive_via_ancestor_bf38d6fa")
                    explanation = render_message("webui.render_workspace_right.text.ancestor_code_title_is_deactivated_aae4022c", code=inactive_ancestor["code"], title=inactive_ancestor["title"])
                else:
                    effective_status = render_message("webui.render_workspace_right.text.active_78e7cbf5")
                    explanation = render_message("webui.render_workspace_right.text.this_classification_has_no_direct_or_inher_7ee3a26e")
                with ui.row().classes("w-full items-center gap-2"):
                    ui.badge(effective_status, color="grey-7" if scheme.get("date_deactivated") or selected.get("date_deactivated") or inactive_ancestor else "positive").props("outline")
                    ui.label(explanation).classes("text-xs text-slate-500")
                with ui.card().classes("retention-card w-full shadow-none p-5 gap-3"):
                    with ui.row().classes("w-full items-center gap-2"):
                        ui.icon("schedule", color="primary")
                        ui.label(render_message("webui.render_workspace_right.label.effective_retention_rule_e5300688")).classes("text-lg font-semibold")
                    if effective_result:
                        inherited = effective_result["defined_by_classification_id"] != selected["id"]
                        with ui.row().classes("w-full items-center gap-2"):
                            ui.badge(render_message("webui.render_workspace_right.badge.inherited_47a9f6bf") if inherited else render_message("webui.render_workspace_right.badge.direct_5942e4ad"), color="indigo").props("outline")
                            source = next((node for node in path if node["id"] == effective_result["defined_by_classification_id"]), None)
                            if inherited and source:
                                ui.label(render_message("webui.render_workspace_right.text.inherited_from_code_title_5a7d1fa5", code=source["code"], title=source["title"])).classes("text-sm text-slate-500")
                            else:
                                ui.label(render_message("webui.render_workspace_right.text.inherited_from_an_ancestor_classification_4b3d7b4b") if inherited else render_message("webui.render_workspace_right.text.defined_on_this_classification_c28d511d")).classes("text-sm text-slate-500")
                        render_rule_details(effective_result)
                        if inherited:
                            ui.separator()
                            ui.label(render_message("webui.render_workspace_right.label.direct_retention_rule_0840d945")).classes("font-semibold")
                            render_rule_details(direct_result)
                    else:
                        ui.label(render_message("webui.render_workspace_right.label.no_direct_or_inherited_rule_82cc8a91")).classes("text-sm text-slate-500")
                with ui.card().classes("detail-surface w-full shadow-none p-5 gap-4"):
                    ui.label(render_message("webui.render_workspace_right.label.classification_information_a1af0008")).classes("text-lg font-semibold")
                    with ui.grid().classes("w-full grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"):
                        metadata_value(entity_metadata_label("Code"), selected.get("code"))
                        metadata_value(entity_metadata_label("Authority"), selected.get("authority"))
                        metadata_value(entity_metadata_label("Keywords"), selected.get("keywords"))
                        parent = path[-2] if len(path) > 1 else None
                        metadata_value(entity_metadata_label("Parent classification"), f"{parent['code']} — {parent['title']}" if parent else None)
                        metadata_value(render_message("dashboard.activity.created"), selected.get("date_created"), timestamp=True)
                        metadata_value(render_message("webui.render_governance_cards.text.last_updated_fdb63867"), selected.get("date_updated"), timestamp=True)
                        metadata_value(render_message("classification_workspace.metadata.first_used"), selected.get("date_first_used"), timestamp=True)
                        metadata_value(entity_metadata_label("Deactivated"), selected.get("date_deactivated"), timestamp=True)
                    localized = selected.get("localized") or {}
                    long_metadata_value(entity_metadata_label("Scope note"), localized.get("scope_note") or selected.get("scope_note"))
        except ApiError as error:
            if current(revision):
                detail_error(error, lambda: focus_classification(item))

    async def optional_rule(classification_id: int, *, effective: bool) -> dict | None:
        try:
            return await api.classification_effective_rule(classification_id) if effective else await api.classification_retention_rule(classification_id)
        except ApiError as error:
            if error.status_code == 404:
                return None
            raise

    async def create_scheme() -> None:
        async def saved(item: dict[str, Any]) -> None:
            await reload_workspace(item["id"])
        await open_editor(on_saved=saved, resource_key="classification-schemes")

    async def create_classification(parent: dict[str, Any] | None = None, *, scheme: dict[str, Any] | None = None) -> None:
        scheme = scheme or workspace["scheme"]
        if scheme is None:
            return
        if parent and parent.get("is_terminal"):
            ui.notify(render_message("webui.create_classification.notify.terminal_classifications_cannot_contain_ch_93e2ea4c"), color="warning")
            return
        async def saved(item: dict[str, Any]) -> None:
            workspace["expanded_schemes"].add(scheme["id"])
            if parent:
                workspace["expanded"].add(parent["id"])
            remember()
            await reload_workspace(scheme["id"], item["id"])
        await open_editor(
            initial_values={"classification_scheme_id": scheme["id"], "parent_classification_id": parent["id"] if parent else None},
            locked_fields={"classification_scheme_id", "parent_classification_id"},
            on_saved=saved, resource_key="classifications",
        )

    async def edit_scheme(scheme: dict[str, Any]) -> None:
        async def saved(item: dict[str, Any]) -> None:
            await reload_workspace(item["id"])
        await open_editor(scheme, on_saved=saved, resource_key="classification-schemes")

    async def edit_selected() -> None:
        selected = workspace["selected"]
        if selected is None:
            return
        async def saved(item: dict[str, Any]) -> None:
            await reload_workspace(item["classification_scheme_id"], item["id"])
        await open_editor(selected, on_saved=saved, resource_key="classifications")

    async def reload_workspace(scheme_id: int | None = None, classification_id: int | None = None) -> None:
        workspace["children"].clear()
        workspace["children_more"].clear()
        workspace["paths"].clear()
        if classification_id is not None:
            await focus_classification({"id": classification_id})
        elif scheme_id is not None:
            await select_scheme({"id": scheme_id})
        else:
            await show_tree()
    async def change_classification_lifecycle(item: dict[str, Any]) -> None:
        deactivated = bool(item.get("date_deactivated"))
        action = render_message("webui.change_classification_lifecycle.text.reactivate_263766dd") if deactivated else render_message("webui.change_classification_lifecycle.text.deactivate_149beda7")
        dialog = ui.dialog()
        with dialog, ui.card().classes("w-[540px] max-w-full"):
            ui.label(render_message("webui.change_classification_lifecycle.label.title_classification_22f782a8", title=action.title())).classes("text-xl font-semibold")
            ui.label(render_message("webui.change_classification_lifecycle.label.code_title_58726667", code=item['code'], title=item['title'])).classes("font-semibold")
            ui.label(
                render_message(
                    "webui.change_classification_lifecycle.guidance.reactivate"
                    if deactivated else
                    "webui.change_classification_lifecycle.guidance.deactivate"
                )
            ).classes("text-sm text-slate-600")
            reason = ui.textarea(render_message("webui.change_classification_lifecycle.textarea.reason_for_action_8ac9320f", action=action)).props("outlined autogrow").classes("w-full")

            async def apply_change() -> None:
                if not (reason.value or "").strip():
                    ui.notify(render_message("webui.apply_change.notify.a_reason_for_action_is_required_11942f0f", action=action), color="warning")
                    return
                try:
                    updated = await api.request(
                        "POST", f"/api/v1/classifications/{item['id']}/{'reactivate' if deactivated else 'deactivate'}",
                        headers={
                            "If-Match": str(item["version"]),
                            "X-Change-Reason": reason.value.strip(),
                        },
                    )
                    dialog.close()
                    ui.notify(render_message("webui.apply_change.notify.classification_action_d_26155873", action=action), color="positive")
                    await reload_workspace(updated["classification_scheme_id"], updated["id"])
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.change_classification_lifecycle.button.cancel_0b3642a8"), on_click=dialog.close).props("flat no-caps")
                ui.button(action.title(), on_click=apply_change).props(
                    "unelevated no-caps color=" + ("positive" if deactivated else "negative")
                )
        dialog.open()

    async def confirm_delete_classification(item: dict[str, Any]) -> None:
        dialog = ui.dialog()
        with dialog, ui.card().classes("w-[540px] max-w-full"):
            ui.label(render_message("webui.confirm_delete_classification.label.delete_classification_permanently_71a3ad1f")).classes("text-xl font-semibold")
            ui.label(render_message("webui.confirm_delete_classification.label.code_title_339d0b48", code=item['code'], title=item['title'])).classes("font-semibold")
            ui.label(
                render_message("webui.confirm_delete_classification.label.its_directly_owned_retention_rule_and_rece_a6bb530e")
            ).classes("text-sm text-slate-600")
            reason = ui.textarea(render_message("webui.confirm_delete_classification.textarea.reason_for_deletion_b357bce9")).props("outlined autogrow").classes("w-full")

            async def remove() -> None:
                if not (reason.value or "").strip():
                    ui.notify(render_message("webui.remove.notify.a_reason_for_deletion_is_required_01159784"), color="warning")
                    return
                try:
                    await api.request(
                        "DELETE", f"/api/v1/classifications/{item['id']}",
                        headers={
                            "If-Match": str(item["version"]),
                            "X-Change-Reason": reason.value.strip(),
                        },
                    )
                    dialog.close()
                    ui.notify(render_message("webui.remove.notify.classification_deleted_ac0f9173"), color="positive")
                    await reload_workspace(item["classification_scheme_id"])
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.confirm_delete_classification.button.cancel_d099c16f"), on_click=dialog.close).props("flat no-caps")
                ui.button(render_message("webui.confirm_delete_classification.button.delete_permanently_16070e66"), icon="delete_forever", on_click=remove).props(
                    "unelevated no-caps color=negative"
                )
        dialog.open()


    async def publish_workspace_scheme(scheme: dict[str, Any]) -> None:
        try:
            await api.request(
                "POST", f"/api/v1/classification-schemes/{scheme['id']}/publish",
                headers={"If-Match": str(scheme["version"])},
            )
            ui.notify(render_message("webui.publish_workspace_scheme.notify.classification_scheme_published_c92a7a2a"), color="positive")
            await reload_workspace(scheme["id"])
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)

    async def unpublish_workspace_scheme(scheme: dict[str, Any]) -> None:
        dialog = ui.dialog()
        with dialog, ui.card().classes("w-[520px] max-w-full"):
            ui.label(render_message("webui.unpublish_workspace_scheme.label.unpublish_classification_scheme_6e0dafdd")).classes("text-xl font-semibold")
            ui.label(
                render_message("webui.unpublish_workspace_scheme.label.code_title_will_no_longer_be_available_for_c0a23502", code=scheme['code'], title=scheme['title'])
            ).classes("text-sm text-slate-700")
            reason = ui.textarea(render_message("webui.unpublish_workspace_scheme.textarea.reason_for_unpublishing_62fcf4eb")).props("outlined autogrow").classes("w-full")

            async def unpublish() -> None:
                if not (reason.value or "").strip():
                    ui.notify(render_message("webui.unpublish.notify.a_reason_for_unpublishing_is_required_34d3c039"), color="warning")
                    return
                try:
                    await api.request(
                        "POST", f"/api/v1/classification-schemes/{scheme['id']}/unpublish",
                        headers={
                            "If-Match": str(scheme["version"]),
                            "X-Change-Reason": reason.value.strip(),
                        },
                    )
                    dialog.close()
                    ui.notify(render_message("webui.unpublish.notify.classification_scheme_unpublished_896edfcd"), color="positive")
                    await reload_workspace(scheme["id"])
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.unpublish_workspace_scheme.button.cancel_511877c5"), on_click=dialog.close).props("flat no-caps")
                ui.button(render_message("webui.unpublish_workspace_scheme.button.unpublish_7902e66e"), icon="unpublished", on_click=unpublish).props(
                    "unelevated no-caps color=primary"
                )
        dialog.open()

    async def confirm_delete_workspace_scheme(scheme: dict[str, Any]) -> None:
        branches, terminals = workspace["counts"].get(scheme["id"], (0, 0))
        total = branches + terminals
        dialog = ui.dialog()
        with dialog, ui.card().classes("w-[560px] max-w-full"):
            ui.label(render_message("webui.confirm_delete_workspace_scheme.label.delete_classification_scheme_35b63adb")).classes("text-xl font-semibold")
            ui.label(render_message("webui.confirm_delete_workspace_scheme.label.code_title_7a072c4b", code=scheme['code'], title=scheme['title'])).classes(
                "font-semibold text-slate-800"
            )
            if total:
                ui.label(
                    render_message("webui.confirm_delete_workspace_scheme.label.this_permanently_deletes_total_classificat_0cfbf8a1", total=total, branches=branches, terminals=terminals)
                ).classes("text-sm text-slate-700")
            else:
                ui.label(render_message("webui.confirm_delete_workspace_scheme.label.this_permanently_deletes_the_empty_scheme_efe8bed5")).classes(
                    "text-sm text-slate-700"
                )
            ui.label(
                render_message("webui.confirm_delete_workspace_scheme.label.immutable_audit_events_are_retained_this_a_68367eee")
            ).classes("text-xs text-slate-500")
            reason = ui.textarea(render_message("webui.confirm_delete_workspace_scheme.textarea.reason_for_deletion_45441f2e")).props("outlined autogrow").classes("w-full")

            async def delete_scheme() -> None:
                if not (reason.value or "").strip():
                    ui.notify(render_message("webui.delete_scheme.notify.a_reason_for_deletion_is_required_4f6f8490"), color="warning")
                    return
                try:
                    await api.request(
                        "DELETE", f"/api/v1/classification-schemes/{scheme['id']}",
                        headers={
                            "If-Match": str(scheme["version"]),
                            "X-Change-Reason": reason.value.strip(),
                        },
                    )
                    dialog.close()
                    ui.notify(render_message("webui.delete_scheme.notify.classification_scheme_deleted_5e7bfd9f"), color="positive")
                    await reload_workspace()
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.confirm_delete_workspace_scheme.button.cancel_9d5de1b1"), on_click=dialog.close).props("flat no-caps")
                ui.button(
                    render_message("webui.confirm_delete_workspace_scheme.button.delete_permanently_fe15def9"), icon="delete_forever", color="negative",
                    on_click=delete_scheme,
                ).props("unelevated no-caps")
        dialog.open()

    async def change_workspace_scheme_lifecycle(scheme: dict[str, Any]) -> None:
        deactivated = bool(scheme.get("date_deactivated"))
        action = render_message("webui.change_workspace_scheme_lifecycle.text.reactivate_a849017f") if deactivated else render_message("webui.change_workspace_scheme_lifecycle.text.deactivate_e3f22c0d")
        dialog = ui.dialog()
        with dialog, ui.card().classes("w-[540px] max-w-full"):
            ui.label(action.title()).classes("text-xl font-semibold")
            ui.label(f"{scheme['code']} — {scheme['title']}").classes("font-semibold")
            reason = ui.textarea(render_message("webui.change_classification_lifecycle.textarea.reason_for_action_8ac9320f", action=action)).props("outlined autogrow").classes("w-full")

            async def apply_change() -> None:
                if not (reason.value or "").strip():
                    ui.notify(render_message("webui.apply_change.notify.a_reason_for_action_is_required_11942f0f", action=action), color="warning")
                    return
                try:
                    await api.request(
                        "POST", f"/api/v1/classification-schemes/{scheme['id']}/{'reactivate' if deactivated else 'deactivate'}",
                        headers={"If-Match": str(scheme["version"]), "X-Change-Reason": reason.value.strip()},
                    )
                    dialog.close()
                    ui.notify(render_message("webui.change_workspace_scheme_lifecycle.notify.classification_scheme_action_d_4d8e7f9b", action=action), color="positive")
                    await reload_workspace(scheme["id"])
                except ApiError as error:
                    warn(error)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.change_classification_lifecycle.button.cancel_0b3642a8"), on_click=dialog.close).props("flat no-caps")
                ui.button(action.title(), on_click=apply_change).props("unelevated no-caps color=" + ("positive" if deactivated else "negative"))
        dialog.open()


    await reload_workspace(initial_scheme_id, initial_classification_id)
