"""Existing bounded classification pickers for editors and Advanced Search.

Each invocation owns its dialog/page data. The scheme type-ahead keeps its
revision/task per control. No cross-page cache or new request is introduced.
"""
import asyncio
from typing import Any
from nicegui import ui
from .api_client import ApiError
from .entity_selectors import apply_relationship_selection, relationship_options
from .i18n_catalogue import render_message


def build_scheme_selector(api):
    def bind_remote_scheme_select(control: Any) -> None:
        """Attach bounded published-scheme type-ahead behavior."""
        request_state: dict[str, Any] = {"revision": 0, "task": None}

        async def load(query: str = "") -> None:
            request_state["revision"] += 1
            revision = request_state["revision"]
            try:
                rows = await api.browse_schemes(query, limit=25)
            except (ApiError, asyncio.CancelledError):
                return
            if revision != request_state["revision"]:
                return
            selected = control.value
            options = {
                item["id"]: f"{item['code']} — {item['title']}" for item in rows
            }
            if selected is not None and selected not in options:
                options[selected] = dict(control.options).get(selected, str(selected))
            control.options = options
            control.update()

        def schedule(event: Any) -> None:
            previous = request_state.get("task")
            if previous is not None and not previous.done():
                previous.cancel()

            async def delayed() -> None:
                await asyncio.sleep(0.2)
                await load(str(event.args or ""))

            request_state["task"] = asyncio.create_task(delayed())

        control.on("input-value", schedule)

    return bind_remote_scheme_select


def build_classification_pickers(api, *, direction, tree_expander_icon, error_message):
    async def browse_classification_tree(target_control: Any) -> None:
        browser = ui.dialog()
        content: Any = None

        async def show_schemes(
            *, offset: int = 0,
            accumulated: list[dict[str, Any]] | None = None,
        ) -> None:
            try:
                page_schemes = await api.list(
                    "classification-schemes", eligible=True,
                    limit=26, offset=offset,
                )
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                return
            has_more = len(page_schemes) > 25
            schemes = [*(accumulated or []), *page_schemes[:25]]
            content.clear()
            with content:
                ui.label(render_message("webui.show_schemes.label.published_classification_schemes_60973ae8")).classes("text-lg font-semibold")
                ui.label(render_message("webui.show_schemes.label.choose_a_scheme_to_browse_its_classificati_16640d3e")).classes("text-sm text-slate-500")
                if not schemes:
                    ui.label(render_message("webui.show_schemes.label.no_active_published_classification_schemes_5c51e82c")).classes("py-8 text-slate-400")
                for scheme in schemes:
                    with ui.card().classes("w-full shadow-none border border-slate-200 cursor-pointer").on(
                        "click", lambda _, selected=scheme: show_level(selected, None, [])
                    ):
                        with ui.row().classes("w-full items-start gap-3 no-wrap"):
                            ui.avatar(
                                icon="account_tree", color="blue-1", text_color="primary"
                            ).classes("shrink-0")
                            with ui.column().classes("gap-0 grow min-w-0"):
                                ui.label(scheme["title"]).classes(
                                    "w-full font-semibold whitespace-normal break-words"
                                )
                                ui.label(scheme["code"]).classes(
                                    "w-full text-xs text-primary truncate"
                                )
                                if scheme.get("description"):
                                    ui.label(scheme["description"]).classes(
                                        "w-full text-xs text-slate-500 line-clamp-2"
                                    )
                            ui.icon(tree_expander_icon(False)).classes(
                                "text-slate-400 shrink-0 self-center"
                            )
                if has_more:
                    ui.button(
                        render_message("webui.render_collection.button.load_more_755f4879"),
                        icon="more_horiz",
                        on_click=lambda: show_schemes(
                            offset=offset + 25, accumulated=schemes,
                        ),
                    ).props("flat dense no-caps").classes("self-center")

        async def show_level(
            scheme: dict[str, Any], parent: dict[str, Any] | None,
            path: list[dict[str, Any]], *, offset: int = 0,
            accumulated: list[dict[str, Any]] | None = None,
        ) -> None:
            try:
                page_rows = await api.list(
                    "classifications",
                    classification_scheme_id=scheme["id"],
                    limit=26, offset=offset,
                    **({"roots_only": True} if parent is None else {"parent_classification_id": parent["id"]}),
                )
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                return
            has_more = len(page_rows) > 25
            rows = [*(accumulated or []), *page_rows[:25]]
            rows.sort(key=lambda item: (
                str(item.get("code") or "").casefold(), int(item.get("id") or 0),
            ))
            content.clear()
            with content:
                with ui.row().classes("w-full items-center gap-1"):
                    ui.button(icon="arrow_forward" if direction() == "rtl" else "arrow_back", on_click=show_schemes if not path else lambda: show_level(scheme, path[-1] if path else None, path[:-1])).props("flat round dense").tooltip(render_message("webui.show_level.tooltip.back_f6d07119"))
                    ui.label(scheme["title"]).classes("font-semibold")
                    for ancestor in path:
                        ui.icon(tree_expander_icon(False), size="16px").classes("text-slate-400")
                        ui.label(ancestor["code"]).classes("text-xs text-slate-500")
                    if parent:
                        ui.icon(tree_expander_icon(False), size="16px").classes("text-slate-400")
                        ui.label(parent["code"]).classes("text-xs font-semibold text-primary")
                if not rows:
                    ui.label(render_message("webui.show_level.label.this_branch_has_no_child_classifications_y_83ec7e08")).classes("py-8 text-slate-400")
                for classification in rows:
                    async def choose(item=classification) -> None:
                        if item["is_terminal"]:
                            apply_relationship_selection(
                                target_control, item["id"],
                                relationship_options([item], ("code", "title"))[item["id"]],
                            )
                            browser.close()
                        else:
                            await show_level(
                                scheme, item,
                                [*path, parent] if parent else path,
                            )
                    with ui.card().classes("w-full shadow-none border border-slate-200 cursor-pointer").on("click", choose):
                        with ui.row().classes("w-full items-center gap-3"):
                            ui.avatar(
                                icon="label" if classification["is_terminal"] else "schema",
                                color="blue-1", text_color="primary",
                            )
                            with ui.column().classes("gap-0 grow"):
                                with ui.row().classes("items-center gap-2"):
                                    ui.label(classification["title"]).classes("font-semibold")
                                    ui.badge(
                                        render_message("webui.show_level.badge.terminal_06982bf6") if classification["is_terminal"] else render_message("webui.show_level.badge.branch_f3904c54"),
                                        color="primary",
                                    ).props("outline")
                                ui.label(classification["code"]).classes("text-xs text-primary")
                                if classification.get("description"):
                                    ui.label(classification["description"]).classes("text-xs text-slate-500 line-clamp-2")
                            ui.icon("check_circle" if classification["is_terminal"] else tree_expander_icon(False), color="primary")
                if has_more:
                    ui.button(
                        render_message("webui.render_collection.button.load_more_755f4879"),
                        icon="more_horiz",
                        on_click=lambda: show_level(
                            scheme, parent, path,
                            offset=offset + 25, accumulated=rows,
                        ),
                    ).props("flat dense no-caps").classes("self-center")

        with browser, ui.card().classes("w-[760px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-32px)]"):
            with ui.row().classes("w-full items-center"):
                ui.label(render_message("webui.browse_classification_tree.label.browse_classifications_9c9abe6c")).classes("text-xl font-semibold")
                ui.space()
                ui.button(icon="close", on_click=browser.close).props("flat round")
            content = ui.column().classes("w-full gap-2 overflow-y-auto max-h-[calc(100vh-150px)]")
        browser.open()
        await show_schemes()

    async def browse_advanced_classification(target_control: Any) -> None:
        dialog = ui.dialog()
        content: Any = None

        async def show_schemes(
            *, offset: int = 0,
            accumulated: list[dict[str, Any]] | None = None,
        ) -> None:
            page_schemes = await api.list(
                "classification-schemes", eligible=True,
                limit=26, offset=offset,
            )
            has_more = len(page_schemes) > 25
            schemes = [*(accumulated or []), *page_schemes[:25]]
            content.clear()
            with content:
                ui.label(render_message("webui.show_schemes.label.choose_a_published_scheme_20d93417")).classes("text-sm text-slate-500")
                for scheme in schemes:
                    with ui.card().classes("w-full shadow-none border border-slate-200 cursor-pointer p-3").on(
                        "click", lambda _, item=scheme: show_level(item, None, [])
                    ):
                        ui.label(scheme["title"]).classes("font-semibold")
                        ui.badge(scheme["code"], color="primary").props("outline")
                if has_more:
                    ui.button(
                        render_message("webui.render_collection.button.load_more_755f4879"),
                        icon="more_horiz",
                        on_click=lambda: show_schemes(
                            offset=offset + 25, accumulated=schemes,
                        ),
                    ).props("flat dense no-caps").classes("self-center")

        async def show_level(
            scheme: dict[str, Any], parent_item: dict[str, Any] | None,
            path: list[dict[str, Any]], *, offset: int = 0,
            accumulated: list[dict[str, Any]] | None = None,
        ) -> None:
            page_rows = await api.list(
                "classifications", classification_scheme_id=scheme["id"],
                limit=26, offset=offset,
                **({"roots_only": True} if parent_item is None else {"parent_classification_id": parent_item["id"]}),
            )
            has_more = len(page_rows) > 25
            rows = [*(accumulated or []), *page_rows[:25]]
            rows.sort(key=lambda item: (
                str(item.get("code") or "").casefold(), int(item.get("id") or 0),
            ))
            content.clear()
            with content:
                with ui.row().classes("w-full items-center gap-2"):
                    ui.button(
                        icon="arrow_forward" if direction() == "rtl" else "arrow_back",
                        on_click=show_schemes if parent_item is None else lambda: show_level(
                            scheme, path[-1] if path else None, path[:-1],
                        ),
                    ).props('flat round dense aria-label=' + repr(render_message("webui.show_level.accessible_name.back_1d2eb652")))
                    ui.label(scheme["title"]).classes("font-semibold")
                    if parent_item:
                        ui.badge(parent_item["code"], color="primary").props("outline")
                if not rows:
                    ui.label(render_message("webui.show_level.label.this_branch_has_no_child_classifications_91eaaa60")).classes("py-6 text-slate-500")
                for item in rows:
                    async def choose(selected=item) -> None:
                        if selected["is_terminal"]:
                            apply_relationship_selection(
                                target_control, selected["id"],
                                f"{selected['code']} · {selected['title']}",
                            )
                            dialog.close()
                        else:
                            await show_level(
                                scheme, selected,
                                [*path, parent_item] if parent_item else path,
                            )
                    with ui.card().classes("w-full shadow-none border border-slate-200 cursor-pointer p-3").on("click", choose):
                        with ui.row().classes("w-full items-center gap-3"):
                            ui.avatar(icon="label" if item["is_terminal"] else "schema", color="blue-1", text_color="primary")
                            with ui.column().classes("grow min-w-0 gap-0"):
                                ui.label(item["title"]).classes("font-semibold")
                                ui.badge(item["code"], color="primary").props("outline")
                            ui.icon("check_circle" if item["is_terminal"] else tree_expander_icon(False), color="primary")
                if has_more:
                    ui.button(
                        render_message("webui.render_collection.button.load_more_755f4879"),
                        icon="more_horiz",
                        on_click=lambda: show_level(
                            scheme, parent_item, path,
                            offset=offset + 25, accumulated=rows,
                        ),
                    ).props("flat dense no-caps").classes("self-center")

        with dialog, ui.card().classes("w-[760px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-32px)]"):
            with ui.row().classes("w-full items-center"):
                ui.label(render_message("webui.browse_advanced_classification.label.browse_classifications_66b655c2")).classes("text-xl font-semibold")
                ui.space(); ui.button(icon="close", on_click=dialog.close).props("flat round")
            content = ui.column().classes("w-full gap-2 overflow-y-auto max-h-[calc(100vh-150px)]")
        dialog.open()
        try:
            await show_schemes()
        except ApiError as error:
            dialog.close(); ui.notify(error_message(error), color="negative", close_button=True)

    return browse_classification_tree, browse_advanced_classification
