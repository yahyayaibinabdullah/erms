"""Existing aggregation behavior with explicit view dependencies."""
from __future__ import annotations
from typing import Any, Callable
from .api_client import ApiError
from .entity_selectors import apply_relationship_selection
import asyncio
from .i18n_catalogue import render_message
from nicegui import ui

def build_aggregation_selector(
    *, api, bind_remote_scheme_select, error_message, tree_expander_icon,
):
    async def browse_advanced_aggregation(target_control: Any, *, record_creation=False, digital_only=False, resource_kind="aggregation", exclude_id=None, on_select=None, active=lambda: True) -> None:
        dialog = ui.dialog()
        content: Any = None
        scheme_control: Any = None
        def current():
            return active() and dialog.value and not dialog._deleted
        browser = {"collections": {}, "expanded": set(), "scheme_id": None}

        async def load_collection(path: str, *, append: bool = False) -> None:
            requested_scheme = browser['scheme_id']
            collection = browser["collections"].setdefault(path, {"items": [], "next_cursor": None})
            page = await api.browse_page(
                path, cursor=collection["next_cursor"] if append else None, limit=50,
                **({"record_creation": True, "digital_only": digital_only} if record_creation and (path.endswith("/aggregations") or path.startswith("aggregations/")) else {}),
            )
            if not current() or browser['scheme_id'] != requested_scheme:
                return
            collection["items"] = [*collection["items"], *page["items"]] if append else list(page["items"])
            collection["next_cursor"] = page.get("next_cursor")

        async def toggle_node(kind: str, item: dict[str, Any]) -> None:
            if not current():
                return
            node = (kind, int(item["id"]))
            if node in browser["expanded"]:
                browser["expanded"].remove(node)
                render_tree()
                return
            browser["expanded"].add(node)
            if kind == "classification":
                path = (
                    f"classifications/{item['id']}/aggregations"
                    if item["is_terminal"] else f"classifications/{item['id']}/children"
                )
            else:
                path = f"aggregations/{item['id']}/children"
            paths = [path]
            if kind == "aggregation" and resource_kind == "record":
                paths.append(f"aggregations/{item['id']}/records")
            await asyncio.gather(*(load_collection(candidate) for candidate in paths if candidate not in browser["collections"]))
            if current():
                render_tree()

        async def select_aggregation(item: dict[str, Any]) -> None:
            if not current():
                return
            if on_select:
                try:
                    await on_select(item, current)
                except ApiError as error:
                    if current():
                        ui.notify(error_message(error), color="negative")
                    return
            else:
                apply_relationship_selection(target_control, item["id"], f"{item['aggregation_number']} · {item['title']}")
            if current():
                dialog.close()

        def render_collection(path: str, kind: str, depth: int) -> None:
            collection = browser["collections"].get(path, {"items": [], "next_cursor": None})
            for item in collection["items"]:
                node_kind = kind
                node = (node_kind, int(item["id"]))
                expanded = node in browser["expanded"]
                with ui.column().classes("advanced-relationship-tree-node gap-0"):
                    with ui.row().classes(
                        "advanced-relationship-tree-row w-full rounded-lg py-1 pe-2 hover:bg-blue-50"
                    ):
                        expander = ui.button(
                            icon=tree_expander_icon(expanded),
                            on_click=lambda _, selected=item, selected_kind=node_kind: toggle_node(selected_kind, selected),
                        ).props("flat round dense size=sm color=blue-grey").classes(
                            "advanced-relationship-tree-expander"
                        )
                        if node_kind == "record":
                            expander.set_visibility(False)
                        ui.icon(
                            "description" if node_kind == "record" else "schema" if node_kind == "classification" and not item.get("is_terminal")
                            else "label" if node_kind == "classification" else "folder",
                            color="primary",
                        ).classes("advanced-relationship-tree-icon")
                        with ui.column().classes(
                            "advanced-relationship-tree-content min-w-0 gap-0"
                        ):
                            ui.label(item["title"]).classes("text-sm font-semibold")
                            ui.label(item.get("code") or item.get(node_kind + "_number")).classes(
                                "text-xs text-slate-500"
                            )
                        if node_kind == resource_kind and item['id'] != exclude_id:
                            ui.button(
                                render_message("webui.render_collection.button.select_c2c58965"), icon="check",
                                on_click=lambda _, selected=item: select_aggregation(selected),
                            ).props("flat dense no-caps").classes(
                                "advanced-relationship-tree-action"
                            )
                    if expanded:
                        child_path = (
                            f"classifications/{item['id']}/aggregations"
                            if node_kind == "classification" and item["is_terminal"] else
                            f"classifications/{item['id']}/children"
                            if node_kind == "classification" else
                            f"aggregations/{item['id']}/children"
                        )
                        with ui.column().classes(
                            "advanced-relationship-tree-children w-auto gap-0"
                        ):
                            render_collection(
                                child_path,
                                "aggregation" if node_kind == "aggregation" or item.get("is_terminal") else "classification",
                                depth + 1,
                            )
                            if node_kind == "aggregation" and resource_kind == "record":
                                render_collection(f"aggregations/{item['id']}/records", "record", depth + 1)
            if collection.get("next_cursor"):
                async def load_more(collection_path: str = path) -> None:
                    await load_collection(collection_path, append=True)
                    render_tree()
                ui.button(
                    render_message("webui.render_collection.button.load_more_755f4879"),
                    icon="more_horiz", on_click=load_more,
                ).props("flat dense no-caps").classes("self-start ms-8")

        def render_tree() -> None:
            if not current():
                return
            content.clear()
            with content:
                scheme_id = browser.get("scheme_id")
                if scheme_id is None:
                    ui.label(render_message("webui.render_tree.label.choose_a_classification_scheme_20386596")).classes("text-sm text-slate-500 py-6 self-center")
                    return
                render_collection(f"classification-schemes/{scheme_id}/roots", "classification", 0)

        async def select_scheme(scheme_id: int | None) -> None:
            if scheme_id is None:
                return
            browser.update(scheme_id=int(scheme_id), collections={}, expanded=set())
            await load_collection(f"classification-schemes/{scheme_id}/roots")
            render_tree()

        with dialog, ui.card().classes("w-[760px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-32px)]"):
            with ui.row().classes("w-full items-center"):
                ui.label(render_message("webui.browse_advanced_aggregation.label.browse_classification_and_aggregation_hier_26704b25")).classes("text-xl font-semibold")
                ui.space(); ui.button(icon="close", on_click=dialog.close).props("flat round")
            scheme_control = ui.select({}, label=render_message("webui.browse_advanced_aggregation.select.classification_scheme_84f93d50")).props("outlined dense options-dense use-input input-debounce=0").classes("w-full")
            bind_remote_scheme_select(scheme_control)
            content = ui.column().classes("w-full gap-2 overflow-y-auto max-h-[calc(100vh-150px)]")
        dialog.open()
        try:
            schemes = await api.browse_schemes()
            if not current():
                return
            scheme_control.options = {item["id"]: f"{item['code']} — {item['title']}" for item in schemes}
            scheme_control.update()
            if schemes:
                scheme_control.value = schemes[0]["id"]
                scheme_control.update()
                await select_scheme(schemes[0]["id"])
            else:
                render_tree()
        except ApiError as error:
            dialog.close(); ui.notify(error_message(error), color="negative", close_button=True)
        scheme_control.on_value_change(lambda event: select_scheme(event.value))


    return browse_advanced_aggregation
