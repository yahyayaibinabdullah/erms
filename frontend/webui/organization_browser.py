"""Existing organization browser view with explicit per-client dependencies."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from typing import Callable
from nicegui import app
from .entity_selectors import apply_relationship_selection
import asyncio
from .capabilities import can_open_organization_detail
from .entity_editor_controls import entity_metadata_label
from .i18n_catalogue import render_message
from nicegui import ui


def build_organization_browser(
    *, add_button, add_record_button, aggregation_mode_bar, api, current_page, enter_organization_browser, error_message, format_timestamp, get_principal, guidance, localized_account_type, localized_lifecycle_value, page_client, register_navigation, render_user_avatar, search_bar, select_organization_unit_details, select_role_details, select_user_details, show_authenticated_view, subtitle, table_container, title, tree_expander_icon,
):
    async def show_organization_structure(
        *, selection_mode: str | None = None, target_control: Any = None,
        on_selection: Callable[..., Any] | None = None,
        saved_audience: str | None = None,
    ) -> None:
        """Shared lazy organization browser for the page and selectors."""
        selection_entity_label = {
            "role": render_message("entity_metadata.field.role"),
            "org_unit": render_message("entity_metadata.field.organization_unit"),
            "user": render_message("entity_metadata.field.user"),
            "all": render_message("messaging.field.recipient"),
        }.get(selection_mode, "")
        is_selector = selection_mode is not None
        if not is_selector:
            register_navigation("organization-browser", "Browse organization structure")
        if is_selector:
            dialog = ui.dialog()
            host = dialog
            saved_state: dict[str, Any] = {
                "expanded": [], "selected": None, "query": "", "validity": "all",
                "entity_type": selection_mode or "all", "status": "all", "scroll_top": 0,
            }
        else:
            show_authenticated_view()
            enter_organization_browser()
            title.text = render_message("webui.show_organization_structure.text.browse_organization_structure_ad6087b2")
            subtitle.text = render_message("webui.show_organization_structure.text.explore_organization_units_roles_and_assig_3f272b2f")
            search_bar.set_visibility(False); aggregation_mode_bar.set_visibility(False)
            add_button.set_visibility(False); add_record_button.set_visibility(False)
            guidance.text = ""; table_container.clear()
            host = table_container
            saved_state = dict(app.storage.user.get("organization_browser_state") or {})
            saved_state.setdefault("expanded", []); saved_state.setdefault("selected", None)
            saved_state.setdefault("query", ""); saved_state.setdefault("validity", "all")
            saved_state.setdefault("entity_type", "all"); saved_state.setdefault("status", "all")
            saved_state.setdefault("scroll_top", 0)

        expanded = set(saved_state["expanded"])
        browser: dict[str, Any] = {
            "roots": [], "root_more": False, "children": {}, "pages": {},
            "selected": saved_state["selected"],
            "scroll_top": saved_state.get("scroll_top", 0),
            "pending": {}, "revision": 0, "search_revision": 0,
            "refreshing": False,
        }
        tree_host: Any = None
        summary_host: Any = None
        search_results_host: Any = None
        selection_confirm_button: Any = None

        def browser_active() -> bool:
            return (
                not card_context.is_deleted
                and (is_selector or current_page() == "organization-browser")
            )

        def persist() -> None:
            if is_selector or not browser_active():
                return
            app.storage.user["organization_browser_state"] = {
                "expanded": sorted(expanded), "selected": browser["selected"],
                "query": query_input.value or "", "validity": validity_filter.value,
                "entity_type": entity_type_filter.value, "status": status_filter.value,
                "scroll_top": browser.get("scroll_top", 0),
                "root_count": len(browser["roots"]),
                "branch_counts": {key: len(rows) for key, rows in browser["children"].items()},
                "filters_visible": advanced_filters.visible,
            }

        def selection_label(node: dict[str, Any]) -> str:
            if node["type"] in {"role", "org_unit"} and node.get("code"):
                return f"{node['code']} · {node.get('name') or node['id']}"
            return str(node.get("name") or node.get("email") or node["id"])

        def organization_node_dom_id(node: dict[str, Any]) -> str:
            assignment = f"-{node['assignment_id']}" if node.get("assignment_id") else ""
            return f"organization-browser-node-{node['type']}-{node['id']}{assignment}"

        async def select_node(node: dict[str, Any]) -> None:
            browser["selected"] = {
                "type": node["type"], "id": node["id"],
                "selectable": node_selectable(node),
                "label": selection_label(node),
                **({"assignment_id": node.get("assignment_id"), "role_id": node.get("role_id")} if node["type"] == "user" else {}),
            }
            persist()
            if not is_selector:
                return
            await page_client.run_javascript(
                "document.querySelectorAll('#organization-browser-tree .organization-browser-selected')"
                ".forEach(item => item.classList.remove('organization-browser-selected', 'bg-blue-50')); "
                f"document.getElementById('{organization_node_dom_id(node)}')"
                "?.classList.add('organization-browser-selected', 'bg-blue-50');"
            )
            if is_selector:
                await render_summary(node)
            if is_selector and selection_confirm_button is not None:
                if node_selectable(node):
                    selection_confirm_button.enable()
                else:
                    selection_confirm_button.disable()

        async def activate_node(node: dict[str, Any]) -> None:
            if not browser_active():
                return
            await select_node(node)
            if not is_selector and browser_active():
                await open_selected(node)

        async def load_node_children(
            node: dict[str, Any], *, append: bool = False,
        ) -> list[dict[str, Any]]:
            key = f"{node['type']}:{node['id']}"
            if key in browser["children"] and not append:
                return browser["children"][key]
            if key in browser["pending"]:
                return await asyncio.shield(browser["pending"][key])
            task = asyncio.create_task(read_node_children(node, append=append))
            browser["pending"][key] = task
            try:
                return await task
            finally:
                if browser["pending"].get(key) is task:
                    browser["pending"].pop(key, None)

        async def read_node_children(
            node: dict[str, Any], *, append: bool = False,
        ) -> list[dict[str, Any]]:
            key = f"{node['type']}:{node['id']}"
            revision = browser["revision"]
            current = browser["children"].get(key, []) if append else []
            page = browser["pages"].setdefault(
                key, {"unit_offset": 0, "role_offset": 0, "user_offset": 0, "more": False},
            )
            if not append:
                page.update(unit_offset=0, role_offset=0, user_offset=0, more=False)
            if node["type"] == "org_unit":
                result = await api.organization_children(
                    node["id"], include_roles=selection_mode != "org_unit", limit=25,
                    unit_offset=page["unit_offset"], role_offset=page["role_offset"],
                    audience=saved_audience,
                )
                children = [{**item, "type": "org_unit"} for item in result["org_units"]]
                if selection_mode != "org_unit":
                    children += [{**item, "type": "role"} for item in result["roles"]]
                page["unit_offset"] += len(result["org_units"])
                page["role_offset"] += len(result["roles"])
                page["more"] = bool(result.get("more_org_units") or result.get("more_roles"))
            else:
                page_rows = [] if selection_mode == "role" else await api.organization_role_users(
                    node["id"], validity=validity_filter.value,
                    limit=26, offset=page["user_offset"],
                )
                children = [{**item, "type": "user"} for item in page_rows[:25]]
                page["user_offset"] += len(children)
                page["more"] = len(page_rows) > 25
            if not browser_active() or revision != browser["revision"]:
                return []
            browser["children"][key] = [*current, *children]
            return browser["children"][key]

        async def toggle_node(node: dict[str, Any]) -> None:
            key = f"{node['type']}:{node['id']}"
            if key in expanded:
                expanded.remove(key)
            else:
                expanded.add(key)
                if key not in browser["children"]:
                    try:
                        await load_node_children(node)
                    except ApiError as error:
                        expanded.discard(key)
                        if browser_active() and error.status_code != 401:
                            ui.notify(error_message(error), color="negative", close_button=True)
            if browser_active():
                persist(); render_tree()

        def node_selectable(node: dict[str, Any]) -> bool:
            if not is_selector or (selection_mode != "all" and node["type"] != selection_mode):
                return not is_selector
            status = node.get("effective_status", node.get("status"))
            return status == "active" and (saved_audience is None or node.get("audience_selectable") is True)

        def render_nodes(nodes: list[dict[str, Any]], depth: int = 0) -> None:
            for node in nodes:
                key = f"{node['type']}:{node['id']}"
                can_expand = node["type"] == "org_unit" or (
                    node["type"] == "role" and selection_mode not in {"org_unit", "role"}
                )
                selected = (
                    browser["selected"]
                    and browser["selected"].get("type") == node["type"]
                    and browser["selected"].get("id") == node["id"]
                    and (
                        node["type"] != "user"
                        or browser["selected"].get("assignment_id") == node.get("assignment_id")
                    )
                )
                tree_row = ui.row().props(
                    f"id={organization_node_dom_id(node)}"
                ).classes(
                    "organization-browser-node-row w-full rounded-lg py-1 px-2 hover:bg-blue-50 "
                    + ("organization-browser-selected bg-blue-50" if selected else "")
                ).style(f"padding-inline-start:{depth * 20 + 4}px")
                with tree_row:
                    with ui.element("div").classes("organization-browser-expander w-8 h-8 shrink-0 flex items-center justify-center"):
                        if can_expand:
                            disclosure = ui.button(
                                icon=tree_expander_icon(key in expanded),
                                on_click=lambda _, item=node: toggle_node(item),
                            ).props("flat round dense size=sm color=blue-grey").classes(
                                "organization-browser-disclosure"
                            ).props(
                                f'aria-expanded={str(key in expanded).lower()}'
                            ).tooltip(selection_label(node))
                            disclosure.props["aria-label"] = selection_label(node)
                    ui.icon(
                        {"org_unit": "corporate_fare", "role": "badge", "user": "person"}[node["type"]],
                        color="primary", size="20px",
                    ).classes("organization-browser-icon w-6 shrink-0")
                    privileges = set(
                        (get_principal() or {}).get("global_privileges", [])
                    )
                    clickable = (
                        node_selectable(node) if is_selector
                        else can_open_organization_detail(node["type"], privileges)
                    )
                    if clickable:
                        node_content = ui.button(
                            on_click=lambda _, item=node: activate_node(item),
                        ).props("flat dense no-caps align=left").classes(
                            "organization-browser-content min-w-0 w-full text-start py-1"
                        )
                        node_content.props["aria-label"] = selection_label(node)
                        node_content.tooltip(node.get("name") or selection_label(node))
                        if is_selector:
                            tree_row.on(
                                "dblclick", lambda _, item=node: confirm_node_selection(item),
                            )
                    else:
                        node_content = ui.column().classes(
                            "organization-browser-content min-w-0 gap-0 py-1"
                        )
                    with node_content, ui.column().classes("w-full min-w-0 gap-0 items-start"):
                        inactive = node.get("effective_status", node.get("status")) == "inactive"
                        ui.label(node.get("name") or str(node["id"])).props("dir=auto").classes(
                            "text-sm font-semibold max-w-full truncate "
                            + ("text-slate-400" if inactive else "text-slate-800")
                        )
                        if node.get("code"):
                            ui.label(node["code"]).props("dir=auto").classes("text-xs text-slate-400 max-w-full truncate")
                    status_value = node.get("effective_status", node.get("status"))
                    if node["type"] == "user":
                        ui.badge(
                            localized_lifecycle_value(node.get("status") or "active"),
                            color={"active": "positive", "suspended": "warning"}.get(node.get("status"), "grey-7"),
                        ).props("outline").classes("organization-browser-badge")
                    elif status_value and status_value != "active":
                        ui.badge(
                            localized_lifecycle_value(status_value), color="grey-7",
                        ).props("outline").classes("organization-browser-badge")
                    if is_selector and not node_selectable(node):
                        node_content.tooltip(
                            render_message("webui.render_nodes.tooltip.this_item_is_visible_for_context_but_canno_b093611d")
                            if selection_mode == "all" or node["type"] == selection_mode else render_message("webui.render_nodes.tooltip.use_this_item_to_navigate_the_hierarchy_869873c9")
                        )
                if key in expanded:
                    render_nodes(browser["children"].get(key, []), depth + 1)
                    if browser["pages"].get(key, {}).get("more"):
                        async def load_more(item: dict[str, Any] = node) -> None:
                            await load_node_children(item, append=True)
                            render_tree()
                            persist()
                        ui.button(
                            render_message("webui.render_collection.button.load_more_755f4879"),
                            icon="more_horiz", on_click=load_more,
                        ).props("flat dense no-caps").style(
                            f"margin-inline-start:{(depth + 1) * 20 + 36}px"
                        )

        def render_tree() -> None:
            if not browser_active():
                return
            tree_host.clear()
            with tree_host:
                if not browser["roots"]:
                    ui.label(render_message("webui.render_tree.label.no_organization_units_found_f6a84d3c")).classes("p-4 text-slate-400")
                render_nodes(browser["roots"])
                if browser.get("root_more"):
                    async def load_more_roots() -> None:
                        if browser.get("root_loading"):
                            return
                        browser["root_loading"] = True
                        revision = browser["revision"]
                        try:
                            page_rows = await api.organization_roots(
                                limit=26, offset=len(browser["roots"]), audience=saved_audience,
                            )
                        finally:
                            browser["root_loading"] = False
                        if not browser_active() or revision != browser["revision"]:
                            return
                        browser["roots"].extend(
                            {**item, "type": "org_unit"} for item in page_rows[:25]
                        )
                        browser["root_more"] = len(page_rows) > 25
                        render_tree()
                        persist()
                    ui.button(
                        render_message("webui.render_collection.button.load_more_755f4879"),
                        icon="more_horiz", on_click=load_more_roots,
                    ).props("flat dense no-caps").classes("self-center")

        async def reveal_result(result: dict[str, Any]) -> None:
            """Load and expand the exact ancestor path returned by search."""
            nodes = browser["roots"]
            parent_node: dict[str, Any] | None = None
            target: dict[str, Any] | None = None
            for unit_id in result.get("org_unit_path") or []:
                target = next((item for item in nodes if item["id"] == unit_id), None)
                while target is None and parent_node is not None and browser["pages"].get(
                    f"org_unit:{parent_node['id']}", {},
                ).get("more"):
                    nodes = await load_node_children(parent_node, append=True)
                    target = next((item for item in nodes if item["id"] == unit_id), None)
                while target is None and parent_node is None and browser.get("root_more"):
                    page_rows = await api.organization_roots(
                        limit=26, offset=len(browser["roots"]), audience=saved_audience,
                    )
                    browser["roots"].extend(
                        {**item, "type": "org_unit"} for item in page_rows[:25]
                    )
                    browser["root_more"] = len(page_rows) > 25
                    nodes = browser["roots"]
                    target = next((item for item in nodes if item["id"] == unit_id), None)
                if target is None:
                    return
                key = f"org_unit:{unit_id}"
                expanded.add(key)
                nodes = await load_node_children(target)
                parent_node = target
            if result["type"] == "role":
                target = next((item for item in nodes if item["type"] == "role" and item["id"] == result["id"]), None)
                while target is None and parent_node is not None and browser["pages"].get(
                    f"org_unit:{parent_node['id']}", {},
                ).get("more"):
                    nodes = await load_node_children(parent_node, append=True)
                    target = next((item for item in nodes if item["type"] == "role" and item["id"] == result["id"]), None)
                target = target or result
            elif result["type"] == "user":
                role = next((item for item in nodes if item["type"] == "role" and item["id"] == result.get("role_id")), None)
                while role is None and parent_node is not None and browser["pages"].get(
                    f"org_unit:{parent_node['id']}", {},
                ).get("more"):
                    nodes = await load_node_children(parent_node, append=True)
                    role = next((item for item in nodes if item["type"] == "role" and item["id"] == result.get("role_id")), None)
                if role is not None:
                    expanded.add(f"role:{role['id']}")
                    users = await load_node_children(role)
                    target = next((item for item in users if item.get("assignment_id") == result.get("assignment_id")), None)
                    while target is None and browser["pages"].get(f"role:{role['id']}", {}).get("more"):
                        users = await load_node_children(role, append=True)
                        target = next((item for item in users if item.get("assignment_id") == result.get("assignment_id")), None)
                    target = target or result
                else:
                    target = result
            if target is None:
                target = result
            render_tree()
            await activate_node({**target, "type": result["type"]})
            if not is_selector:
                return
            await ui.run_javascript(
                "document.querySelector('#organization-browser-tree .bg-blue-50')?.scrollIntoView({block:'center'})"
            )

        async def open_selected(node: dict[str, Any]) -> None:
            persist()
            if not is_selector and not can_open_organization_detail(
                node["type"], set((get_principal() or {}).get("global_privileges", [])),
            ):
                return
            if is_selector and not node_selectable(node):
                ui.notify(render_message("webui.open_selected.notify.select_an_active_item_of_the_requested_typ_2d331b9a"), color="warning")
                return
            if is_selector and on_selection is not None:
                if await on_selection(node):
                    dialog.close()
                return
            if node["type"] == "user":
                if is_selector:
                    target_control.set_value(node["id"]); dialog.close()
                else:
                    await select_user_details(node["id"])
            elif is_selector:
                target_control.set_value(node["id"]); dialog.close()
            else:
                if node["type"] == "org_unit":
                    await select_organization_unit_details(node["id"])
                else:
                    await select_role_details(node["id"])

        async def confirm_browser_selection() -> None:
            selected = browser.get("selected")
            if (
                not selected
                or (selection_mode != "all" and selected.get("type") != selection_mode)
                or not selected.get("selectable")
            ):
                ui.notify(
                    render_message("webui.confirm_browser_selection.notify.select_an_active_replace_first_9ad73ee2", replace=selection_entity_label),
                    color="warning",
                )
                return
            if on_selection is not None:
                if await on_selection(selected):
                    dialog.close()
                return
            apply_relationship_selection(
                target_control, selected["id"], selected["label"],
            )
            await asyncio.sleep(0)
            dialog.close()

        async def confirm_node_selection(node: dict[str, Any]) -> None:
            await select_node(node)
            await confirm_browser_selection()

        async def render_summary(node: dict[str, Any]) -> None:
            if not is_selector:
                return
            summary_host.clear()
            if node["type"] in {"org_unit", "role"}:
                item = await api.organization_summary(
                    "org-units" if node["type"] == "org_unit" else "roles", node["id"],
                )
            else:
                item = node
            with summary_host:
                with ui.column().classes("w-full gap-3 p-5"):
                    with ui.row().classes("w-full items-start gap-3 no-wrap"):
                        if node["type"] == "user":
                            render_user_avatar(item, size="38px")
                        else:
                            ui.avatar(
                                icon="corporate_fare" if node["type"] == "org_unit" else "badge",
                                color="blue-1", text_color="primary", size="56px",
                            )
                        with ui.column().classes("gap-0 grow min-w-0"):
                            ui.label(item.get("name") or render_message("webui.render_summary.label.selected_item_7ed0cfcc")).classes("text-xl font-semibold")
                            if item.get("code"): ui.label(item["code"]).classes("text-primary")
                            if item.get("email"): ui.label(item["email"]).classes("text-slate-500")
                    if item.get("description"):
                        ui.label(item["description"]).classes("text-sm text-slate-600 bg-slate-50 rounded p-3 w-full")
                    for field_key, label, value in (
                        ("status", entity_metadata_label("Status") if node["type"] == "user" else render_message("webui.render_governance_cards.text.effective_status_c7a1dfe1"), item.get("effective_status", item.get("status"))),
                        ("account_type", entity_metadata_label("Account type"), item.get("account_type")),
                        ("org_unit", entity_metadata_label("Organization unit"), item.get("org_unit_name")),
                        ("selected_role", render_message("entity_metadata.field.role"), " — ".join(filter(None, (item.get("role_code"), item.get("role_name")))) or None),
                        ("supervisor_role", entity_metadata_label("Supervising role"), item.get("supervisor_role_name")),
                        ("direct_status", entity_metadata_label("Status"), item.get("status") if node["type"] != "user" else None),
                        ("inactive_source", entity_metadata_label("Status"), (item.get("inactive_source") or {}).get("name") if isinstance(item.get("inactive_source"), dict) else None),
                        ("child_units", render_message("webui.show_organization_structure.select.organization_units_66c328dc"), item.get("child_org_unit_count")),
                        ("roles", render_message("webui.show_organization_structure.select.roles_2c70f24a"), item.get("role_count")),
                        ("supervised_roles", render_message("webui.show_organization_structure.select.roles_2c70f24a"), item.get("subordinate_role_count")),
                        ("assigned_users", render_message("webui.show_organization_structure.select.users_03e2325e"), item.get("assigned_user_count")),
                        ("current_assignments", render_message("governance_custody.stat.current_assignments"), item.get("current_assignment_count")),
                        ("future_assignments", render_message("webui.show_organization_structure.select.future_875190f7"), item.get("future_assignment_count")),
                        ("expired_assignments", render_message("webui.show_organization_structure.select.expired_66c2cb88"), item.get("expired_assignment_count")),
                        ("assignment_validity", render_message("webui.show_organization_structure.select.assignment_validity_b7656407"), item.get("assignment_validity")),
                        ("valid_from", render_message("governance_custody.field.valid_from"), format_timestamp(item.get("valid_from")) if item.get("valid_from") else None),
                        ("valid_until", render_message("governance_custody.field.valid_until"), format_timestamp(item.get("valid_until")) if item.get("valid_until") else None),
                    ):
                        if value is not None:
                            guidance_text = None
                            if field_key == "status" and node["type"] != "user":
                                guidance_text = render_message("webui.render_summary.text.includes_inactivity_inherited_from_organiz_1ed32480")
                            elif field_key == "direct_status":
                                guidance_text = render_message("webui.render_summary.text.set_directly_on_this_item_without_consider_076d5cd7")
                            display_value = value
                            if field_key in {"status", "direct_status", "assignment_validity"}:
                                display_value = localized_lifecycle_value(value)
                            elif field_key == "account_type":
                                display_value = localized_account_type(value)
                            with ui.column().classes("w-full gap-0 border-b border-slate-100 py-1.5"):
                                with ui.element("div").classes("organization-browser-summary-field w-full"):
                                    ui.label(label).classes("organization-browser-summary-label text-xs uppercase tracking-wide text-slate-400")
                                    ui.label(str(display_value)).classes("organization-browser-summary-value text-sm font-medium")
                                if guidance_text:
                                    ui.label(guidance_text).classes("w-full text-[10px] leading-3 text-slate-400")
                    privileges = set(
                        (get_principal() or {}).get("global_privileges", [])
                    )
                    if not is_selector and can_open_organization_detail(node["type"], privileges):
                        action_label = render_message({
                            "org_unit": "webui.render_governance_cards.tooltip.open_organization_unit_831f72f6",
                            "role": "webui.render_governance_cards.tooltip.open_role_5c0462a7",
                            "user": "webui.render_governance_cards.tooltip.open_user_0dd1ba6f",
                        }[node["type"]])
                        ui.button(
                            action_label, icon="open_in_new",
                            on_click=lambda: open_selected(node),
                        ).props("unelevated no-caps").classes("self-end")

        async def run_search() -> None:
            browser["search_revision"] += 1
            revision = browser["search_revision"]
            search_results_host.clear()
            query = (query_input.value or "").strip()
            persist()
            if not query:
                return
            type_filter = selection_mode or entity_type_filter.value
            results = await api.search_organization(
                query, entity_type=type_filter, status=status_filter.value, audience=saved_audience,
            )
            if not browser_active() or revision != browser["search_revision"]:
                return
            with search_results_host:
                if not results:
                    ui.label(render_message("webui.run_search.label.no_matching_organization_units_roles_or_us_29cce504")).classes("px-2 py-3 text-slate-400")
                for result in results:
                    with ui.card().classes("w-full shadow-none border border-slate-200 p-0"):
                        result_clickable = is_selector or can_open_organization_detail(
                            result["type"], set((get_principal() or {}).get("global_privileges", [])),
                        )
                        result_row = ui.button(
                            on_click=lambda _, item=result: reveal_result(item),
                        ).props("flat no-caps align=left").classes(
                            "w-full text-start"
                        )
                        result_row.props["aria-label"] = selection_label(result)
                        if not result_clickable:
                            result_row.disable()
                        if is_selector:
                            async def confirm_search_result(item: dict[str, Any] = result) -> None:
                                await reveal_result(item)
                                await confirm_browser_selection()
                            result_row.on(
                                "dblclick", lambda _, action=confirm_search_result: action()
                            )
                        with result_row, ui.row(wrap=False).classes("w-full items-start gap-3"):
                            ui.avatar(
                                icon={"org_unit": "corporate_fare", "role": "badge", "user": "person"}[result["type"]],
                                color="blue-1", text_color="primary", size="36px",
                            ).classes("shrink-0")
                            with ui.column().classes("grow min-w-0 gap-0 items-start text-start"):
                                ui.label(result.get("name") or result.get("code")).classes("font-medium text-start")
                                if result.get("code"):
                                    ui.label(result["code"]).classes("text-xs text-primary text-start")
                                if result.get("email"):
                                    ui.label(result["email"]).classes("text-xs text-slate-500 text-start")
                                if result.get("role_name"):
                                    ui.label(render_message("webui.run_search.label.via_role_get_role_name_5576a5f2", get=result.get('role_code'), role_name=result['role_name'])).classes("text-xs text-slate-500 text-start")

        if is_selector:
            with dialog:
                card_context = ui.card().classes(
                    "w-[1100px] max-w-[calc(100vw-32px)] max-h-[calc(100vh-32px)]"
                )
        else:
            with table_container:
                card_context = ui.column().classes("organization-browser-workspace w-full p-4 gap-3")
        with card_context:
            if is_selector:
                ui.label(render_message("webui.show_organization_structure.label.browse_replace_s_06870755", replace=selection_entity_label)).classes("text-xl font-semibold")
            with ui.row().classes("w-full items-end gap-2"):
                query_input = ui.input(render_message("webui.show_organization_structure.input.search_organization_structure_b22c915b"), value=saved_state.get("query", "")).props("outlined dense clearable").classes("grow")
                validity_filter = ui.select(
                    {"all": render_message("webui.show_organization_structure.select.all_assignments_1a3e1480"), "current": render_message("webui.show_organization_structure.select.current_8d79efc1"), "future": render_message("webui.show_organization_structure.select.future_875190f7"), "expired": render_message("webui.show_organization_structure.select.expired_66c2cb88")},
                    value=saved_state.get("validity", "all"), label=render_message("webui.show_organization_structure.select.assignment_validity_b7656407"),
                ).props("outlined dense options-dense").classes("w-48")
                if selection_mode in {"org_unit", "role"}:
                    validity_filter.set_visibility(False)
                ui.button(render_message("webui.show_organization_structure.button.search_577b8b0f"), icon="search", on_click=run_search).props("flat dense no-caps")
                query_input.on("keydown.enter", run_search)
                filters_button = ui.button(render_message("webui.show_organization_structure.button.filters_c7ccc610"), icon="filter_list").props("flat dense no-caps")
                async def refresh_browser() -> None:
                    if browser["refreshing"]:
                        return
                    browser["refreshing"] = True
                    try:
                        await refresh_tree()
                    finally:
                        browser["refreshing"] = False

                async def refresh_tree() -> None:
                    persist()
                    if not is_selector:
                        saved_state.update(app.storage.user["organization_browser_state"])
                    browser["revision"] += 1
                    browser["pending"].clear()
                    try:
                        roots = await api.organization_roots(limit=26, audience=saved_audience)
                    except ApiError as error:
                        # The shared 401 handler has already cleared protected UI
                        # and opened the sign-in dialog. Do not continue rendering
                        # this page or surface a redundant event-handler traceback.
                        if error.status_code == 401:
                            return
                        if browser_active():
                            ui.notify(error_message(error), color="negative", close_button=True)
                        return
                    if not browser_active():
                        return
                    browser["children"].clear()
                    browser["pages"].clear()
                    browser["roots"] = [{**item, "type": "org_unit"} for item in roots[:25]]
                    browser["root_more"] = len(roots) > 25
                    await restore_root_pages()
                    await restore_expanded(browser["roots"])
                    render_tree()
                    if is_selector and browser.get("selected"):
                        selected = browser["selected"]
                        try:
                            if selected["type"] == "user" and selected.get("role_id"):
                                candidates = await api.organization_role_users(selected["role_id"], validity="all")
                                refreshed = next((item for item in candidates if item.get("assignment_id") == selected.get("assignment_id")), None)
                                if refreshed: await render_summary({**refreshed, "type": "user"})
                            elif selected["type"] != "user":
                                refreshed = await api.organization_summary("org-units" if selected["type"] == "org_unit" else "roles", selected["id"])
                                await render_summary({**refreshed, "type": selected["type"]})
                        except ApiError:
                            browser["selected"] = None; persist()
                    if browser_active():
                        await run_search()
                        ui.notify(render_message("webui.refresh_browser.notify.organization_structure_refreshed_c53f2b77"), color="positive")
                ui.button(render_message("webui.show_organization_structure.button.refresh_7f802034"), icon="refresh", on_click=refresh_browser).props("flat dense no-caps")
            with ui.row().classes("w-full items-end gap-2 rounded bg-slate-50 p-2") as advanced_filters:
                entity_type_filter = ui.select(
                    {"all": render_message("webui.show_organization_structure.select.all_entity_types_aca0740b"), "org_unit": render_message("webui.show_organization_structure.select.organization_units_66c328dc"), "role": render_message("webui.show_organization_structure.select.roles_2c70f24a"), "user": render_message("webui.show_organization_structure.select.users_03e2325e")},
                    value=selection_mode or saved_state.get("entity_type", "all"), label=render_message("webui.show_organization_structure.select.entity_type_9e2af3fa"),
                ).props("outlined dense options-dense").classes("w-52")
                if is_selector:
                    entity_type_filter.disable()
                status_filter = ui.select(
                    {"all": render_message("webui.show_organization_structure.select.all_statuses_c7b69ce2"), "active": render_message("webui.show_organization_structure.select.active_9e0362ed"), "inactive": render_message("webui.show_organization_structure.select.inactive_926e3f6c"), "suspended": render_message("webui.show_organization_structure.select.suspended_e5b9d9f5")},
                    value=saved_state.get("status", "all"), label=render_message("webui.show_organization_structure.select.status_5399f6fd"),
                ).props("outlined dense options-dense").classes("w-48")
                ui.button(render_message("webui.show_organization_structure.button.clear_269fa70e"), icon="filter_alt_off", on_click=lambda: (
                    entity_type_filter.set_value(selection_mode or "all"),
                    status_filter.set_value("all"), validity_filter.set_value("all"),
                )).props("flat dense no-caps")
            advanced_filters.set_visibility(saved_state.get("filters_visible", False))
            filters_button.on("click", lambda: advanced_filters.set_visibility(not advanced_filters.visible))
            search_results_host = ui.column().classes("w-full gap-0")
            layout_direction = "flex-col"
            browser_height = "h-[520px]" if is_selector else "h-[720px]"
            page_layout_class = "" if is_selector else "organization-browser-page-layout"
            with ui.row().classes(f"w-full {browser_height} gap-0 border border-slate-200 rounded-lg overflow-hidden {layout_direction} {page_layout_class}"):
                tree_classes = (
                    "w-full h-[340px] overflow-auto border-b"
                    if is_selector else "organization-browser-page-tree w-full min-w-0 h-full overflow-auto"
                )
                tree_host = ui.column().classes(f"{tree_classes} p-2 gap-0 border-slate-200").props("id=organization-browser-tree")
                if is_selector:
                    summary_host = ui.column().classes("w-full h-[180px] overflow-auto min-w-0")
            if is_selector:
                with ui.row().classes("w-full justify-end"):
                    ui.button(render_message("webui.show_organization_structure.button.cancel_6938b29c"), on_click=dialog.close).props("flat no-caps")
                    selection_confirm_button = ui.button(
                        render_message("webui.show_organization_structure.button.select_replace_cf383c4d", replace=selection_entity_label), icon="check",
                        on_click=confirm_browser_selection,
                    ).props("unelevated no-caps color=primary")
                    selection_confirm_button.disable()
        try:
            roots = await api.organization_roots(limit=26, audience=saved_audience)
        except ApiError as error:
            # Session expiry and development reloads can race with a navigation
            # click. The API client has already presented sign-in for a 401.
            if error.status_code == 401:
                return
            if browser_active():
                with tree_host:
                    ui.label(error_message(error)).classes("text-negative p-3")
                    ui.button(
                        render_message("classification_browser.retry"), icon="refresh",
                        on_click=lambda: show_organization_structure(
                            selection_mode=selection_mode, target_control=target_control,
                            on_selection=on_selection, saved_audience=saved_audience,
                        ),
                    ).props("flat no-caps")
                if is_selector:
                    dialog.open()
            return
        if not browser_active():
            return
        browser["roots"] = [{**item, "type": "org_unit"} for item in roots[:25]]
        browser["root_more"] = len(roots) > 25
        def remember_scroll(event: Any) -> None:
            try:
                browser["scroll_top"] = float(event.args)
                persist()
            except (TypeError, ValueError):
                pass
        tree_host.on("scroll", remember_scroll, js_handler="event => emit(event.target.scrollTop)", throttle=0.25)
        async def change_validity() -> None:
            for key in [key for key in browser["children"] if key.startswith("role:")]:
                browser["children"].pop(key, None)
            persist()
            await restore_expanded(browser["roots"])
            render_tree()
        validity_filter.on_value_change(change_validity)
        async def restore_expanded(nodes: list[dict[str, Any]]) -> None:
            async def restore_branch(node: dict[str, Any]) -> None:
                key = f"{node['type']}:{node['id']}"
                if key in expanded and node["type"] != "user" and browser_active():
                    children = await load_node_children(node)
                    wanted = (saved_state.get("branch_counts") or {}).get(key, 0)
                    while (browser_active() and len(children) < wanted
                           and browser["pages"].get(key, {}).get("more")):
                        children = await load_node_children(node, append=True)
                    await restore_expanded(children)
            await asyncio.gather(*(restore_branch(node) for node in nodes))
        async def restore_root_pages() -> None:
            while (browser_active() and browser["root_more"]
                   and len(browser["roots"]) < saved_state.get("root_count", 0)):
                page_rows = await api.organization_roots(
                    limit=26, offset=len(browser["roots"]), audience=saved_audience,
                )
                if not browser_active():
                    return
                browser["roots"].extend({**item, "type": "org_unit"} for item in page_rows[:25])
                browser["root_more"] = len(page_rows) > 25

        await restore_root_pages()
        await restore_expanded(browser["roots"])
        if not browser_active():
            return
        if not is_selector and browser["selected"]:
            selected = browser["selected"]
            loaded_nodes = [*browser["roots"], *(
                node for children in browser["children"].values() for node in children
            )]
            if not any(organization_node_dom_id(node) == organization_node_dom_id(selected)
                       for node in loaded_nodes):
                browser["selected"] = None
                persist()
        render_tree()
        if saved_state.get("scroll_top"):
            await ui.run_javascript(
                f"const tree=document.getElementById('organization-browser-tree'); if(tree) tree.scrollTop={float(saved_state['scroll_top'])}"
            )
        if not is_selector:
            if saved_state.get("query"):
                await run_search()
            return
        if browser["selected"]:
            selected = browser["selected"]
            try:
                if selected["type"] == "user":
                    node = None
                    if selected.get("role_id"):
                        candidates = await api.organization_role_users(
                            selected["role_id"], validity="all",
                        )
                        node = next((item for item in candidates if item.get("assignment_id") == selected.get("assignment_id")), None)
                    if node is None:
                        node = await api.get("users", selected["id"])
                    node["type"] = "user"
                else:
                    node = await api.organization_summary(
                        "org-units" if selected["type"] == "org_unit" else "roles", selected["id"],
                    ); node["type"] = selected["type"]
                await render_summary(node)
            except ApiError:
                browser["selected"] = None; persist()
        else:
            with summary_host:
                summary_guidance = (
                    {
                        "org_unit": render_message("webui.show_organization_structure.text.select_an_organization_unit_to_view_its_su_9aeb165f"),
                        "role": render_message("webui.show_organization_structure.text.select_a_role_to_view_its_summary_3925160a"),
                        "user": render_message("webui.show_organization_structure.text.select_a_user_to_view_their_summary_6593ceaf"),
                    }[selection_mode]
                    if is_selector and selection_mode != "all"
                    else render_message("webui.show_organization_structure.text.select_an_organization_unit_role_or_user_t_4b5308e8")
                )
                ui.label(summary_guidance).classes("p-8 text-slate-400")
        if is_selector:
            dialog.open()


    return show_organization_structure
