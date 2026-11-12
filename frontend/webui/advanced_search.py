"""Advanced query builder, saved queries, sharing and unsaved-change coordination."""
from __future__ import annotations
from .advanced_search_model import ADVANCED_SEARCH_COMPONENT_FIELDS
from .advanced_search_model import ADVANCED_SEARCH_CONTROLLED_VALUES
from .advanced_search_model import ADVANCED_SEARCH_FIELDS
from .advanced_search_model import ADVANCED_SEARCH_RETENTION_FIELDS
from typing import Any
from .api_client import ApiError
from .advanced_search_model import advanced_search_depth
from .advanced_search_model import advanced_search_empty_value
from .advanced_search_model import advanced_search_field_options
from .advanced_search_model import advanced_search_has_component_field
from .advanced_search_model import advanced_search_has_positive_full_text
from .advanced_search_model import advanced_search_leaf_count
from .advanced_search_model import advanced_search_node_from_expression
from .advanced_search_model import advanced_search_operators
import asyncio
from .advanced_search_model import compile_advanced_search_node
from .component_presentation import component_is_previewable
import copy
from frontend.webui.disposition.messages import text as disposition_text
import json
from .i18n_catalogue import render_message
from .i18n_catalogue import render_message_plain
from .relationship_select_styles import style_relationship_chip_select
from nicegui import ui

def build_advanced_search(
    *, add_button, add_record_button, advanced_search_state, aggregation_mode_bar, aggregation_state, api, bind_remote_relationship_select, bind_remote_saved_audience_select, browse_advanced_aggregation, browse_advanced_classification, collection_state, discard_navigation_guard, enter_advanced_search, error_message, format_timestamp, get_principal, get_resource, guidance, localized_editor_entity, open_aggregation, register_navigation, render_compact_resource_result, restore_compact_result_anchor, search_bar, select_record_details, set_navigation_guard, show_authenticated_view, show_organization_structure, style_status_chip_select, subtitle, table_container, title,
):
    async def select_advanced_search() -> None:
        search_session_revision = advanced_search_state.get("advanced_search_session_revision", 0)
        search_principal = get_principal()

        def search_session_is_current() -> bool:
            return (
                search_principal is not None
                and get_principal() is search_principal
                and advanced_search_state.get("advanced_search_session_revision", 0) == search_session_revision
            )

        def search_view_is_current() -> bool:
            return (
                search_session_is_current()
                and get_resource() == "advanced-search"
                and not results_host.is_deleted
            )

        privileges = set((get_principal() or {}).get("global_privileges", []))
        targets = {
            key: label for key, label, privilege in (
                ("records", render_message("advanced_search.resource.records"), "record.view"),
                ("aggregations", render_message("advanced_search.resource.aggregations"), "aggregation.view"),
            ) if privilege in privileges
        }
        if not targets:
            ui.notify(render_message("webui.select_advanced_search.notify.you_do_not_have_permission_to_use_advanced_019c4e37"), color="negative")
            return
        relation_sources = {
            field_name: (endpoint, label_fields)
            for field_name, endpoint, label_fields in (
            ("aggregation_id", "aggregations", ("aggregation_number", "title")),
            ("parent_aggregation_id", "aggregations", ("aggregation_number", "title")),
            ("classification_id", "classifications", ("code", "title")),
            ("security_level_id", "security-levels", ("code", "name")),
            ("owning_org_unit_id", "org-units", ("code", "name")),
            )
        }
        register_navigation("advanced-search", render_message("navigation.item.advanced_search"))
        show_authenticated_view()
        enter_advanced_search(); collection_state.update(rows=[], searched=False); aggregation_state.update(aggregation_detail=None)
        title.text = render_message("webui.select_advanced_search.text.advanced_search_509592d0")
        subtitle.text = render_message("webui.select_advanced_search.text.build_nested_searches_across_record_or_agg_b4682fe2")
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        table_container.clear()

        default_workspace: dict[str, Any] = {
            "resource": next(iter(targets)),
            "root": {"type": "group", "operator": "and", "children": [
                {"type": "condition", "kind": "structured", "field": "title", "operator": "contains_ci", "value": ""},
            ]},
            "sort_field": "id", "sort_direction": "asc", "limit": 25,
            "max_results": 1000, "offset": 0, "total": 0, "searched": False,
            "busy": False, "error": None, "saved": None, "baseline": None,
            "audience_mode": "private", "role_ids": [], "org_unit_ids": [],
            "search_name": "", "search_category": None, "search_description": "",
            "category_suggestions": [],
            "last_result": None,
            "expanded_results": [],
        }
        restored_workspace = advanced_search_state.get("advanced_search_workspace")
        workspace: dict[str, Any] = copy.deepcopy(restored_workspace) if isinstance(restored_workspace, dict) else default_workspace
        if workspace.get("resource") not in targets:
            workspace = default_workspace
        for key, value in default_workspace.items():
            workspace.setdefault(key, copy.deepcopy(value))
        workspace["busy"] = False
        # Browser history and saved client state can outlive the option sets
        # used by these selectors. NiceGUI rejects an initial value which is
        # not present in the selector's options, so normalize restored values
        # before constructing the controls.
        if workspace.get("sort_direction") not in {"asc", "desc"}:
            workspace["sort_direction"] = "asc"
        if workspace.get("limit") not in {25, 50, 100}:
            workspace["limit"] = 25

        with table_container:
            with ui.column().classes("advanced-search-page w-full gap-4 p-4"):
                with ui.column().classes("hidden"):
                    search_name = ui.input(value=workspace["search_name"])
                    search_category = ui.input(value=str(workspace.get("search_category") or ""))
                    search_description = ui.textarea(value=workspace["search_description"])
                workspace_layout = ui.element("div").classes("advanced-search-workspace-layout")
                workspace_layout.__enter__()
                with ui.card().classes("advanced-search-criteria-panel w-full p-4 shadow-none border border-slate-200"):
                    with ui.row().classes("advanced-search-target-row w-full items-end gap-4 flex-wrap"):
                        target = ui.select(targets, value=workspace["resource"], label=render_message("webui.select_advanced_search.select.search_for_410f853e")).props(
                            'outlined dense options-dense aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.search_target_27bbcc33"))
                        ).classes("w-56")
                        max_results = ui.number(render_message("advanced_search.field.maximum_results"), value=workspace["max_results"], min=1, max=5000, step=1).props(
                            'outlined dense aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.maximum_results_4993c5ac"))
                        ).classes("w-48")
                        ui.label(render_message("webui.select_advanced_search.label.system_maximum_5_000_77d23fb5")).classes("text-xs text-slate-500 pb-2")
                    ui.label(render_message("webui.select_advanced_search.label.criteria_ef9a8718")).classes("text-lg font-semibold mt-3")
                    ui.label(render_message("webui.select_advanced_search.label.nest_all_any_and_not_groups_up_to_50_condi_a3faa193")).classes("text-sm text-slate-500")
                    component_scope_help = ui.label(
                        render_message("webui.select_advanced_search.label.file_details_narrow_the_record_results_in_a8ddca60")
                    ).classes("text-sm text-blue-800 bg-blue-50 border border-blue-200 rounded-lg px-3 py-2")
                    validation_summary = ui.column().classes("w-full rounded-lg border border-red-200 bg-red-50 p-3 gap-1").props(
                        'role=alert tabindex=-1 aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.search_validation_summary_9c5c4e57"))
                    )
                    builder_host = ui.column().classes("w-full gap-3")
                    with ui.row().classes("advanced-search-sort-row w-full items-end gap-3 flex-wrap mt-2"):
                        sort_field = ui.select({}, label=render_message("webui.select_advanced_search.select.sort_by_ead29b06")).props("outlined dense options-dense").classes("w-60")
                        sort_direction = ui.select({"asc": render_message("webui.select_advanced_search.select.ascending_7ac56d5e"), "desc": render_message("webui.select_advanced_search.select.descending_b4342bd5")}, value=workspace["sort_direction"], label=render_message("webui.select_advanced_search.select.direction_c0ccf4a5")).props("outlined dense options-dense").classes("w-40")
                        page_size = ui.select({25: render_message("webui.select_advanced_search.select.page_size_25_3ce9d53c"), 50: render_message("webui.select_advanced_search.select.page_size_50_34f8a03e"), 100: render_message("webui.select_advanced_search.select.page_size_100_ac5cc8df")}, value=workspace["limit"], label=render_message("webui.select_advanced_search.select.page_size_cafb2ebd")).props("outlined dense options-dense").classes("w-40")
                    with ui.row().classes("advanced-search-submit-row w-full items-center gap-2 mt-2"):
                        search_advanced = ui.button(render_message("webui.select_advanced_search.button.search_97989f23"), icon="search").props("unelevated no-caps")
                        reset_advanced = ui.button(render_message("webui.select_advanced_search.button.reset_507afbb7"), icon="restart_alt").props("flat no-caps")
                        status_label = ui.label().classes("text-sm text-slate-500 ml-auto")
                with ui.card().classes("advanced-search-saved-panel w-full p-4 gap-3 shadow-none border border-slate-200"):
                    ui.label(render_message("webui.select_advanced_search.label.saved_search_6ccb135c")).classes("text-base font-semibold")
                    ui.label(render_message("webui.select_advanced_search.label.keep_or_reopen_useful_queries_5db11485")).classes("text-xs text-slate-500")
                    unsaved_context = ui.label(render_message("webui.select_advanced_search.label.this_query_has_not_been_saved_9eaee420")).classes(
                        "w-full rounded-lg bg-slate-50 p-3 text-xs text-slate-600"
                    )
                    saved_context = ui.column().classes("w-full gap-1 rounded-lg border border-blue-200 bg-blue-50 p-3")
                    saved_context.set_visibility(False)
                    with ui.column().classes("advanced-search-saved-actions w-full gap-2"):
                        save_button = ui.button(render_message("webui.select_advanced_search.button.save_search_f4158320"), icon="save").props("outline no-caps")
                        edit_details_button = ui.button(
                            render_message("webui.open_aggregation.button.edit_metadata_3ee4d255"),
                            icon="edit",
                        ).props("outline no-caps")
                        edit_details_button.tooltip(
                            render_message("webui.open_aggregation.button.edit_metadata_3ee4d255")
                        )
                        save_as_button = ui.button(render_message("webui.select_advanced_search.button.save_as_b7ca59d6"), icon="content_copy").props("outline no-caps")
                        open_button = ui.button(render_message("webui.select_advanced_search.button.open_saved_search_8bef667f"), icon="folder_open").props("outline no-caps")
                        new_button = ui.button(render_message("webui.select_advanced_search.button.new_search_635c50cb"), icon="add").props("flat no-caps")
                        delete_button = ui.button(render_message("webui.select_advanced_search.button.delete_f507983a"), icon="delete", color="negative").props("flat no-caps")
                workspace_layout.__exit__(None, None, None)
                freshness_host = ui.column().classes("w-full")
                results_host = ui.column().classes("w-full gap-3").props("aria-live=polite")
                with ui.row().classes("w-full items-center justify-center gap-2") as pagination:
                    first_page = ui.button(icon="first_page").props('flat round aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.first_page_8dfd5626")))
                    previous_page = ui.button(icon="chevron_left").props('flat round aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.previous_page_5a18f6b0")))
                    range_label = ui.label().classes("text-sm text-slate-600 min-w-36 text-center")
                    next_page = ui.button(icon="chevron_right").props('flat round aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.next_page_d75b42e2")))
                    last_page = ui.button(icon="last_page").props('flat round aria-label=' + repr(render_message("webui.select_advanced_search.accessible_name.last_page_d53f2dec")))
                pagination.set_visibility(False)

        def new_condition() -> dict[str, Any]:
            return {"type": "condition", "kind": "structured", "field": "title", "operator": "contains_ci", "value": ""}

        def persist_workspace() -> None:
            # A callback from a discarded identity must never restore its cache.
            if search_session_is_current():
                previous = advanced_search_state.get("advanced_search_workspace")
                if isinstance(previous, dict) and any(
                    previous.get(key) != workspace.get(key)
                    for key in ("root", "resource", "sort_field", "sort_direction", "max_results")
                ):
                    workspace["offset"] = 0
                advanced_search_state["advanced_search_workspace"] = copy.deepcopy(workspace)

        def set_advanced_result_expansion(identifier: int, expanded: bool) -> None:
            key = int(identifier)
            expanded_results = set(int(value) for value in workspace.get("expanded_results", []))
            (expanded_results.add if expanded else expanded_results.discard)(key)
            workspace["expanded_results"] = sorted(expanded_results)
            persist_workspace()

        def current_definition() -> dict[str, Any]:
            expression = compile_advanced_search_node(workspace["root"], workspace["resource"])
            request: dict[str, Any] = {
                "where": expression,
                "sort": [{"field": workspace["sort_field"], "direction": workspace["sort_direction"]}],
                "limit": int(workspace["limit"]), "offset": 0,
            }
            if advanced_search_has_positive_full_text(workspace["root"]):
                request["include"] = ["full_text_matches"]
            return {
                "schema_version": 1,
                "resource_type": "record" if workspace["resource"] == "records" else "aggregation",
                "max_results": max(1, min(5000, int(max_results.value or 1000))),
                "request": request,
            }

        def current_saved_payload() -> dict[str, Any]:
            return {
                "name": str(workspace.get("search_name") or "").strip(),
                "category": str(workspace.get("search_category") or "").strip() or None,
                "description": str(workspace.get("search_description") or "").strip() or None,
                "definition": current_definition(),
                "audience_mode": workspace["audience_mode"],
                "role_ids": sorted(int(value) for value in workspace["role_ids"]),
                "org_unit_ids": sorted(int(value) for value in workspace["org_unit_ids"]),
            }

        def current_saved_signature() -> str:
            try:
                value = current_saved_payload()
                # Page size is execution state, not an edit to saved criteria.
                value["definition"]["request"].pop("limit", None)
            except (TypeError, ValueError):
                value = {
                    "name": workspace.get("search_name"), "category": workspace.get("search_category"),
                    "description": workspace.get("search_description"), "root": workspace["root"],
                    "resource": workspace["resource"], "sort": workspace["sort_field"],
                    "direction": workspace["sort_direction"],
                    "maximum": max_results.value, "audience_mode": workspace["audience_mode"],
                    "role_ids": workspace["role_ids"], "org_unit_ids": workspace["org_unit_ids"],
                }
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

        def is_dirty() -> bool:
            baseline = workspace.get("baseline")
            if baseline is None:
                return False
            # Workspaces persisted before page-size exclusion carry the old
            # signature. Normalize that baseline without discarding real edits.
            value = json.loads(baseline)
            if "definition" in value:
                value["definition"]["request"].pop("limit", None)
            else:
                value.pop("limit", None)
            baseline = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            return current_saved_signature() != baseline

        async def confirm_discard_changes(action: str) -> bool:
            if not is_dirty():
                return True
            with ui.dialog() as dialog, ui.card().classes("w-[500px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.confirm_discard_changes.label.discard_unsaved_changes_8aacea70")).classes("text-lg font-semibold")
                ui.label(render_message("webui.confirm_discard_changes.label.your_changes_will_be_lost_if_you_action_b802686d", action=action)).classes("text-sm text-slate-600")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.confirm_discard_changes.button.keep_editing_965cc0ca"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
                    ui.button(render_message("webui.confirm_discard_changes.button.discard_changes_81df7dc9"), color="negative", on_click=lambda: dialog.submit(True)).props("unelevated no-caps")
            return bool(await dialog)

        set_navigation_guard(confirm_discard_changes)

        def render_saved_context() -> None:
            saved_context.clear()
            saved = workspace.get("saved")
            saved_context.set_visibility(saved is not None)
            unsaved_context.set_visibility(saved is None)
            if saved is None:
                return
            owner = saved.get("owner") or {}
            with saved_context:
                with ui.row().classes("w-full items-start gap-3"):
                    ui.icon("bookmark", color="primary")
                    with ui.column().classes("gap-0 grow min-w-0"):
                        ui.label(saved["name"]).classes("font-semibold")
                        ui.label(render_message("webui.render_saved_context.label.category_value_d60c970c", value=saved.get('category') or 'Uncategorized')).classes("text-xs text-slate-600")
                        ui.label(
                            render_message("webui.render_saved_context.label.owned_by_value_updated_format_timestamp_824cfbd4", value=(owner.get('localized') or {}).get('name') or owner.get('name') or 'Unknown owner', format_timestamp=format_timestamp(saved.get('date_updated')))
                        ).classes("text-xs text-slate-600")
                    ui.badge(render_message("webui.render_saved_context.badge.mine_74055dac") if saved.get("owner_user_id") == (get_principal() or {}).get("user", {}).get("id") else render_message("webui.render_saved_context.badge.shared_d6938797")).props("outline")

        def refresh_saved_actions() -> None:
            saved = workspace.get("saved")
            capabilities = (saved or {}).get("capabilities") or {}
            has_save = "search.saved_search.save" in privileges
            editable = saved is None or capabilities.get("update") is True
            can_execute = saved is None or capabilities.get("execute") is True
            _, validation_error = validate_builder()
            structurally_valid = validation_error is None
            for control in (search_name, search_category, search_description, target, max_results, sort_field, sort_direction, page_size, reset_advanced):
                control.set_enabled(editable)
            if editable:
                builder_host.props(remove="inert aria-disabled")
                builder_host.classes(remove="pointer-events-none opacity-70")
            else:
                builder_host.props(add="inert aria-disabled=true")
                builder_host.classes(add="pointer-events-none opacity-70")
            search_advanced.set_enabled(can_execute and structurally_valid)
            # Navigation restoration can refresh controls outside their page slot.
            # Resolve the catalogue through the button's owning client.
            with save_button:
                save_button.text = render_message("webui.refresh_saved_actions.text.update_saved_search_31788e51") if saved is not None else render_message("webui.refresh_saved_actions.text.save_search_76b8ff5b")
            save_button.update()
            save_button.set_visibility((saved is None and has_save) or capabilities.get("update") is True)
            edit_details_button.set_visibility(
                saved is not None and capabilities.get("update") is True
            )
            save_as_button.set_visibility(has_save and saved is not None)
            save_button.set_enabled(structurally_valid)
            edit_details_button.set_enabled(structurally_valid)
            save_as_button.set_enabled(structurally_valid)
            delete_button.set_visibility(capabilities.get("delete") is True)
            render_saved_context()

        def load_saved_into_workspace(saved: dict[str, Any]) -> None:
            definition = saved["definition"]
            request = definition["request"]
            workspace["loading"] = True
            workspace["saved"] = saved
            workspace["resource"] = "records" if definition["resource_type"] == "record" else "aggregations"
            workspace["root"] = advanced_search_node_from_expression(request.get("where") or {
                "field": "title", "operator": "contains_ci", "value": "",
            })
            # Canonical API expressions may be a single condition; the visual
            # builder requires an outer group. A one-child AND preserves meaning.
            if workspace["root"].get("type") == "condition":
                workspace["root"] = {"type": "group", "operator": "and", "children": [workspace["root"]]}
            visible_sort = next((item for item in request.get("sort", []) if item["field"] != "id"), None)
            workspace["sort_field"] = (visible_sort or {"field": "id"})["field"]
            workspace["sort_direction"] = (visible_sort or {"direction": "asc"})["direction"]
            workspace["limit"] = int(request.get("limit", 25))
            workspace["max_results"] = int(definition.get("max_results", 1000))
            # A newly loaded definition has no execution results. Do not let
            # navigation restore cards belonging to the previous target/query.
            workspace.update(
                offset=0, total=0, searched=False, last_result=None,
                expanded_results=[], record_component_details={}, record_capabilities={},
            )
            workspace.pop("return_anchor", None)
            status_label.text = ""
            workspace["audience_mode"] = saved.get("audience_mode", "private")
            workspace["role_ids"] = list(saved.get("role_ids") or [])
            workspace["org_unit_ids"] = list(saved.get("org_unit_ids") or [])
            workspace["search_name"] = saved["name"]
            workspace["search_category"] = saved.get("category")
            workspace["search_description"] = saved.get("description") or ""
            if saved.get("category"):
                workspace["category_suggestions"] = sorted({
                    *workspace.get("category_suggestions", []), saved["category"],
                }, key=str.casefold)
            search_name.value = saved["name"]
            search_category.value = saved.get("category")
            search_description.value = saved.get("description")
            target.value = workspace["resource"]
            max_results.value = workspace["max_results"]
            page_size.value = workspace["limit"]
            sort_direction.value = workspace["sort_direction"]
            results_host.clear(); freshness_host.clear(); pagination.set_visibility(False)
            render_builder()
            workspace["loading"] = False
            workspace["baseline"] = current_saved_signature()
            refresh_saved_actions()
            persist_workspace()

        async def show_stale_saved_search(saved_search_id: int) -> None:
            with ui.dialog() as dialog, ui.card().classes("w-[500px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.show_stale_saved_search.label.this_saved_search_changed_29b608c2")).classes("text-lg font-semibold")
                ui.label(render_message("webui.show_stale_saved_search.label.another_update_was_saved_after_you_opened_626bc7b5")).classes("text-sm text-slate-600")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.show_stale_saved_search.button.cancel_40dedb50"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
                    ui.button(render_message("webui.show_stale_saved_search.button.reload_latest_600ddd0f"), on_click=lambda: dialog.submit(True)).props("unelevated no-caps")
            if await dialog:
                load_saved_into_workspace(await api.saved_search(saved_search_id))

        async def save_search(
            *, save_as: bool = False, edit_details: bool = False,
        ) -> None:
            _, validation_error = validate_builder()
            if validation_error:
                show_validation(validation_error); validation_summary.run_method("focus"); return
            saved = workspace.get("saved")
            capabilities = (saved or {}).get("capabilities") or {}
            creating = save_as or saved is None
            if not creating and not edit_details:
                payload = current_saved_payload()
                payload.update(
                    audience_mode=workspace["audience_mode"],
                    role_ids=list(workspace["role_ids"]),
                    org_unit_ids=list(workspace["org_unit_ids"]),
                )
                try:
                    save_button.disable()
                    updated = await api.update_saved_search(
                        int(saved["id"]), int(saved["version"]), payload,
                    )
                    load_saved_into_workspace(updated)
                    ui.notify(
                        render_message("webui.persist_saved_search.notify.saved_search_updated_7bd649da"),
                        color="positive",
                    )
                except ApiError as error:
                    save_button.enable()
                    if error.status_code == 409:
                        await show_stale_saved_search(int(saved["id"]))
                    else:
                        ui.notify(error_message(error), color="negative", close_button=True)
                return
            can_manage_audience = creating or capabilities.get("manage_audience") is True
            selected_role_ids = [int(value) for value in ([] if save_as else workspace["role_ids"])]
            selected_unit_ids = [int(value) for value in ([] if save_as else workspace["org_unit_ids"])]
            with ui.dialog() as dialog, ui.card().classes("w-[680px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.save_search.label.save_as_a_new_search_201a62ae") if save_as else (render_message("webui.save_search.label.save_search_9f72f967") if creating else render_message("webui.save_search.label.update_saved_search_09fb6c1c"))).classes("text-lg font-semibold")
                current_name = str(workspace.get("search_name") or "")
                name_control = ui.input(render_message("webui.save_search.input.name_76ae569a"), value=(f"{current_name} copy" if save_as and current_name else current_name)).props("outlined maxlength=120").classes("w-full")
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    category_control = ui.input(
                        render_message("webui.save_search.input.category_a403b84d"), value=str(workspace.get("search_category") or ""),
                        autocomplete=list(workspace.get("category_suggestions") or []),
                    ).props("outlined clearable maxlength=80").classes("grow min-w-56")
                    ui.label(render_message("webui.save_search.label.int_maximum_results_ae8080bb", int=format(int(max_results.value or 1000), ','))).classes("text-sm text-slate-500 self-center")
                description_control = ui.textarea(render_message("webui.save_search.textarea.description_491f6450"), value=workspace.get("search_description") or "").props("outlined maxlength=500 autogrow").classes("w-full")
                audience_mode = ui.radio({"private": render_message("webui.save_search.radio.only_me_739a9de4"), "shared": render_message("webui.save_search.radio.roles_or_organizational_units_01b067ca")}, value="private" if save_as else workspace["audience_mode"]).props("inline")
                audience_host = ui.column().classes("w-full gap-3")
                async def browse_audience(control: Any, kind: str) -> None:
                    async def choose(node: dict[str, Any]) -> bool:
                        try:
                            page = await api.saved_search_audience_options(kind, ids=[node["id"]], limit=1, offset=0)
                        except ApiError as error:
                            ui.notify(error_message(error), color="negative", close_button=True)
                            return False
                        if not page["items"]:
                            ui.notify(render_message("webui.saved_audience.ineligible"), color="warning")
                            return False
                        item = page["items"][0]
                        name = (item.get("localized") or {}).get("name") or item["name"]
                        options = {**dict(control.options), item["id"]: f"{name} ({item['code']})"}
                        control.set_options(options, value=list(dict.fromkeys([*(control.value or []), item["id"]])))
                        return True
                    await show_organization_structure(
                        selection_mode="role" if kind == "roles" else "org_unit", on_selection=choose,
                        saved_audience=kind,
                    )

                with audience_host:
                    role_control = ui.select({}, value=[], label=render_message("webui.save_search.select.roles_c2c266e1"), multiple=True, with_input=True).props("outlined use-chips options-dense clearable input-debounce=0").classes("w-full")
                    ui.label(render_message("webui.saved_audience.roles_help")).classes("text-xs text-slate-500")
                    with ui.row():
                        more_roles = ui.button(render_message("webui.render_collection.button.load_more_755f4879"), icon="more_horiz").props("flat dense no-caps")
                        ui.button(render_message("webui.saved_audience.browse_roles"), icon="account_tree", on_click=lambda: browse_audience(role_control, "roles")).props("flat dense no-caps")
                    unit_control = ui.select({}, value=[], label=render_message("webui.save_search.select.organizational_units_9c039bd2"), multiple=True, with_input=True).props("outlined use-chips options-dense clearable input-debounce=0").classes("w-full")
                    ui.label(render_message("webui.saved_audience.units_help")).classes("text-xs text-slate-500")
                    with ui.row():
                        more_units = ui.button(render_message("webui.render_collection.button.load_more_755f4879"), icon="more_horiz").props("flat dense no-caps")
                        ui.button(render_message("webui.saved_audience.browse_units"), icon="account_tree", on_click=lambda: browse_audience(unit_control, "org-units")).props("flat dense no-caps")
                    _, load_selected_roles = bind_remote_saved_audience_select(role_control, "roles", more_roles)
                    _, load_selected_units = bind_remote_saved_audience_select(unit_control, "org-units", more_units)
                    ui.label(render_message("webui.save_search.label.recipients_can_run_this_query_but_results_c13f331f")).classes("text-xs text-slate-500")
                error_label = ui.label().classes("text-sm text-negative")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.save_search.button.cancel_6ad2d1bd"), on_click=dialog.close).props("flat no-caps")
                    submit = ui.button(render_message("webui.save_search.button.save_53b01f94"), icon="save").props("unelevated no-caps")
                def audience_visibility() -> None:
                    audience_host.set_visibility(can_manage_audience and audience_mode.value == "shared")
                audience_mode.on_value_change(audience_visibility); audience_visibility()
                if not can_manage_audience:
                    audience_mode.disable()

                async def persist_saved_search() -> None:
                    name = str(name_control.value or "").strip()
                    if not name:
                        error_label.text = render_message("webui.persist_saved_search.text.name_is_required_90a7eeee"); return
                    mode = audience_mode.value
                    roles = list(role_control.value or []) if mode == "shared" else []
                    units = list(unit_control.value or []) if mode == "shared" else []
                    if mode == "shared" and not (roles or units):
                        error_label.text = render_message("webui.persist_saved_search.text.choose_at_least_one_role_or_organizational_2c3b3c87"); return
                    workspace["search_name"] = name
                    workspace["search_category"] = str(category_control.value or "").strip() or None
                    workspace["search_description"] = str(description_control.value or "").strip() or None
                    payload = current_saved_payload()
                    payload.update(audience_mode=mode, role_ids=roles, org_unit_ids=units)
                    try:
                        submit.disable()
                        if creating:
                            updated = await api.create_saved_search(payload)
                        else:
                            updated = await api.update_saved_search(
                                int(saved["id"]), int(saved["version"]), payload,
                            )
                        workspace["audience_mode"] = mode
                        workspace["role_ids"] = roles
                        workspace["org_unit_ids"] = units
                        dialog.close(); load_saved_into_workspace(updated)
                        ui.notify(render_message("webui.persist_saved_search.notify.saved_search_created_f6c7b94e") if creating else render_message("webui.persist_saved_search.notify.saved_search_updated_7bd649da"), color="positive")
                    except ApiError as error:
                        submit.enable()
                        if error.status_code == 409 and saved is not None:
                            dialog.close(); await show_stale_saved_search(int(saved["id"]))
                        else:
                            error_label.text = error_message(error)
                submit.on("click", persist_saved_search)
                await asyncio.gather(
                    load_selected_roles(selected_role_ids),
                    load_selected_units(selected_unit_ids),
                )
            dialog.open()

        async def open_saved_search_dialog() -> None:
            # This dialog is execution-oriented: All is strictly the union of
            # Mine and Shared with me. System-wide inventory belongs to the
            # dedicated Saved Search Administration screen.
            administrator = False
            with ui.dialog() as dialog, ui.card().classes("w-[900px] max-w-full max-h-[90vh] p-5 gap-4"):
                ui.label(render_message("webui.open_saved_search_dialog.label.open_saved_search_306aeadf")).classes("text-lg font-semibold")
                filters: dict[str, Any] = {"offset": 0, "limit": 25}
                with ui.row().classes("w-full gap-3 items-end flex-wrap"):
                    query_control = ui.input(render_message("webui.open_saved_search_dialog.input.search_saved_searches_3352fa10")).props("outlined dense clearable").classes("grow min-w-64")
                    filter_button = ui.button(render_message("webui.open_saved_search_dialog.button.filters_d413e321"), icon="tune").props("outline dense no-caps aria-expanded=false")
                with ui.tabs(value="all").props("dense no-caps align=left") as scope_control:
                    ui.tab("all", label=render_message("webui.open_saved_search_dialog.tab.all_d9a1fa9c"))
                    ui.tab("owned", label=render_message("webui.open_saved_search_dialog.tab.mine_74806472"))
                    ui.tab("shared_with_me", label=render_message("webui.open_saved_search_dialog.tab.shared_with_me_1300d28d"))
                advanced_filters = ui.column().classes("w-full gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3")
                advanced_filters.set_visibility(False)
                with advanced_filters:
                    with ui.row().classes("w-full gap-3 items-end flex-wrap"):
                        resource_control = ui.select({None: render_message("webui.open_saved_search_dialog.select.all_targets_fe147069"), "record": render_message("webui.open_saved_search_dialog.select.records_41634859"), "aggregation": render_message("webui.open_saved_search_dialog.select.aggregations_58e793f3")}, value=None, label=render_message("webui.open_saved_search_dialog.select.target_0edd3d27")).props("outlined dense options-dense clearable").classes("w-48")
                        category_filter = ui.input(render_message("webui.open_saved_search_dialog.input.category_d8c18ca4")).props("outlined dense clearable").classes("w-48")
                        apply_filters = ui.button(render_message("webui.open_saved_search_dialog.button.apply_filters_63a71659"), icon="filter_alt").props("outline dense no-caps")
                    if administrator:
                        ui.label(render_message("webui.open_saved_search_dialog.label.administrative_filters_ea190231")).classes("text-sm font-semibold text-slate-600")
                        with ui.row().classes("w-full gap-3 items-end flex-wrap"):
                            owner_filter = ui.number(render_message("webui.open_saved_search_dialog.number.owner_user_id_05651181"), min=1).props("outlined dense").classes("w-40")
                            with ui.column().classes("gap-1"):
                                role_filter = ui.select({}, label=render_message("webui.open_saved_search_dialog.select.role_audience_47211c66"), with_input=True).props("outlined dense clearable options-dense input-debounce=0").classes("w-52")
                                more_role_filters = ui.button(render_message("webui.render_collection.button.load_more_755f4879"), icon="more_horiz").props("flat dense no-caps")
                            with ui.column().classes("gap-1"):
                                unit_filter = ui.select({}, label=render_message("webui.open_saved_search_dialog.select.unit_audience_29a50f10"), with_input=True).props("outlined dense clearable options-dense input-debounce=0").classes("w-52")
                                more_unit_filters = ui.button(render_message("webui.render_collection.button.load_more_755f4879"), icon="more_horiz").props("flat dense no-caps")
                            bind_remote_saved_audience_select(role_filter, "roles", more_role_filters)
                            bind_remote_saved_audience_select(unit_filter, "org-units", more_unit_filters)
                            minimum_filter = ui.number(render_message("webui.open_saved_search_dialog.number.minimum_result_cap_32191a13"), min=1, max=5000).props("outlined dense").classes("w-44")
                            maximum_filter = ui.number(render_message("webui.open_saved_search_dialog.number.maximum_result_cap_87c75dd6"), min=1, max=5000).props("outlined dense").classes("w-44")
                            updated_from = ui.input(render_message("webui.open_saved_search_dialog.input.updated_from_6262aba2")).props("outlined dense type=datetime-local").classes("w-48")
                            updated_before = ui.input(render_message("webui.open_saved_search_dialog.input.updated_before_77f4bd93")).props("outlined dense type=datetime-local").classes("w-48")
                list_host = ui.column().classes("w-full gap-3 overflow-y-auto")
                with ui.row().classes("w-full items-center justify-center gap-2"):
                    previous = ui.button(render_message("webui.open_saved_search_dialog.button.previous_f6a88eee"), icon="chevron_left").props("flat no-caps")
                    page_label = ui.label().classes("text-sm text-slate-500")
                    following = ui.button(render_message("webui.open_saved_search_dialog.button.next_ba38d6aa"), icon="chevron_right").props("flat no-caps")

                async def select_saved_search(selected: dict[str, Any]) -> None:
                    if not await confirm_discard_changes("open another saved search"):
                        return
                    dialog.close()
                    load_saved_into_workspace(selected)

                saved_page_request = {"revision": 0}
                dialog.on("hide", lambda: saved_page_request.update(revision=saved_page_request["revision"] + 1))

                async def load_saved_page() -> None:
                    saved_page_request["revision"] += 1
                    revision = saved_page_request["revision"]
                    params: dict[str, Any] = {"limit": 25, "offset": filters["offset"]}
                    administrative_all = administrator and scope_control.value == "all"
                    if not administrative_all:
                        params["scope"] = scope_control.value
                    if query_control.value: params["q"] = str(query_control.value).strip()
                    if resource_control.value: params["resource_type"] = resource_control.value
                    if category_filter.value: params["category"] = str(category_filter.value).strip()
                    if administrative_all:
                        for key, control in (("owner_user_id", owner_filter), ("role_id", role_filter), ("org_unit_id", unit_filter), ("max_results_min", minimum_filter), ("max_results_max", maximum_filter), ("updated_from", updated_from), ("updated_before", updated_before)):
                            if control.value not in (None, ""): params[key] = control.value
                    try:
                        page = await (api.saved_search_administration(**params) if administrative_all else api.saved_searches(**params))
                        # Resolve only this page's audience IDs, in bounded parallel batches.
                        audience_names: dict[str, dict[int, str]] = {"roles": {}, "org-units": {}}
                        lookups = []
                        for kind, field in (("roles", "role_ids"), ("org-units", "org_unit_ids")):
                            ids = sorted({int(value) for item in page["items"] for value in item.get(field) or []})
                            lookups.extend((kind, ids[start:start + 50]) for start in range(0, len(ids), 50))
                        resolved_pages = await asyncio.gather(*(
                            api.saved_search_audience_options(kind, ids=ids, limit=50, offset=0)
                            for kind, ids in lookups
                        ))
                        for (kind, _), resolved_page in zip(lookups, resolved_pages):
                            for target in resolved_page["items"]:
                                name = (target.get("localized") or {}).get("name") or target["name"]
                                audience_names[kind][int(target["id"])] = f"{target['code']} — {name}"
                    except ApiError as error:
                        if revision != saved_page_request["revision"] or not search_view_is_current():
                            return
                        list_host.clear()
                        with list_host: ui.label(error_message(error)).classes("text-negative")
                        return
                    if revision != saved_page_request["revision"] or not search_view_is_current():
                        return
                    list_host.clear()
                    categories = {item.get("category") for item in page["items"] if item.get("category")}
                    workspace["category_suggestions"] = sorted({
                        *workspace.get("category_suggestions", []), *categories,
                    }, key=str.casefold)
                    with list_host:
                        if not page["items"]:
                            ui.label(render_message("webui.load_saved_page.label.no_saved_searches_match_these_filters_83501f8d")).classes("text-sm text-slate-500 py-8 self-center")
                        for item in page["items"]:
                            owner = item.get("owner") or {}
                            mine = item.get("owner_user_id") == (get_principal() or {}).get("user", {}).get("id")
                            audience_label = render_message("webui.save_search.radio.only_me_739a9de4") if item.get("audience_mode") == "private" else render_message(
                                "webui.saved_search_metadata.audience",
                                roles=len(item.get("role_ids") or []), units=len(item.get("org_unit_ids") or []),
                            )
                            with ui.card().classes("w-full shadow-none border border-slate-200 p-4"):
                                with ui.grid(columns="auto minmax(0, 1fr) auto").classes("w-full items-start gap-3"):
                                    ui.icon("description" if item["resource_type"] == "record" else "folder", color="primary")
                                    with ui.column().classes("gap-1 min-w-0 break-words"):
                                        ui.label(item["name"]).classes("font-semibold")
                                        ui.label(item.get("description") or render_message("webui.load_saved_page.label.no_description_e23ca0ad")).classes("text-sm text-slate-600")
                                        ui.label(
                                            render_message("webui.load_saved_page.label.title_value_updated_format_timestamp_value_b78393c6", title=localized_editor_entity("records" if item["resource_type"] == "record" else "aggregations", item["resource_type"]), value=item.get('category') or render_message("webui.saved_search_metadata.uncategorized"), format_timestamp=format_timestamp(item['date_updated']), value_2=render_message("webui.saved_search_metadata.owned") if mine else render_message("webui.saved_search_metadata.shared_by", owner=str((owner.get('localized') or {}).get('name') or owner.get('name') or item['owner_user_id'])))
                                        ).classes("text-xs text-slate-500")
                                        ui.label(
                                            render_message("webui.load_saved_page.label.maximum_max_results_results_audience_label_1664749d", max_results=format(item['definition']['max_results'], ','), audience_label=audience_label)
                                        ).classes("text-xs text-slate-500")
                                        for kind, field, label_key in (
                                            ("roles", "role_ids", "webui.save_search.select.roles_c2c266e1"),
                                            ("org-units", "org_unit_ids", "webui.save_search.select.organizational_units_9c039bd2"),
                                        ):
                                            names = [audience_names[kind][int(value)] for value in item.get(field) or []
                                                     if int(value) in audience_names[kind]]
                                            if names:
                                                ui.label(render_message(label_key) + ": " + "; ".join(names)).classes("text-xs text-slate-500")
                                    ui.badge(render_message("webui.load_saved_page.badge.mine_47cb9b71") if mine else render_message("webui.load_saved_page.badge.shared_0a95a474"), color="blue-grey").props("outline")
                                ui.button(
                                    render_message("webui.load_saved_page.button.open_2606a7e0"), icon="folder_open",
                                    on_click=lambda _, selected=item: select_saved_search(selected),
                                ).props("flat dense no-caps")
                    start = page["offset"] + 1 if page["items"] else 0
                    page_label.text = render_message("webui.load_saved_page.text.start_value_of_total_eed8d817", start=start, value=page['offset'] + len(page['items']), total=page['total'])
                    previous.set_enabled(page["offset"] > 0)
                    following.set_enabled(page["offset"] + page["limit"] < page["total"])
                async def apply_page_filters() -> None:
                    filters["offset"] = 0; await load_saved_page()
                def toggle_filters() -> None:
                    visible = not advanced_filters.visible
                    advanced_filters.set_visibility(visible)
                    filter_button.props(f"aria-expanded={'true' if visible else 'false'}")
                async def change_page(delta: int) -> None:
                    filters["offset"] = max(0, filters["offset"] + delta); await load_saved_page()
                filter_button.on("click", toggle_filters)
                apply_filters.on("click", apply_page_filters)
                query_control.on("keydown.enter", apply_page_filters)
                if scope_control is not None:
                    scope_control.on_value_change(apply_page_filters)
                previous.on("click", lambda: change_page(-25)); following.on("click", lambda: change_page(25))
                await load_saved_page()
            dialog.open()

        async def delete_saved_search() -> None:
            saved = workspace.get("saved")
            if not saved: return
            with ui.dialog() as dialog, ui.card().classes("w-[520px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.delete_saved_search.label.delete_name_3f400e6a", name=saved['name'])).classes("text-lg font-semibold")
                ui.label(render_message("webui.delete_saved_search.label.this_permanently_deletes_the_saved_query_d_a0cf4b5a")).classes("text-sm text-slate-600")
                reason = ui.textarea(render_message("webui.delete_saved_search.textarea.reason_for_deletion_5aca706a")).props("outlined maxlength=500 autogrow").classes("w-full")
                error_label = ui.label().classes("text-sm text-negative")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.delete_saved_search.button.cancel_9711f5b2"), on_click=dialog.close).props("flat no-caps")
                    confirm = ui.button(render_message("webui.delete_saved_search.button.delete_saved_search_226c4222"), color="negative", icon="delete").props("unelevated no-caps")
                async def remove() -> None:
                    if not str(reason.value or "").strip(): error_label.text = render_message("webui.remove.text.a_reason_is_required_0adbb4d3"); return
                    try:
                        await api.delete_saved_search(int(saved["id"]), int(saved["version"]), str(reason.value).strip())
                        dialog.close(); reset_search(clear_metadata=True)
                        ui.notify(render_message("webui.remove.notify.saved_search_deleted_9cf582fa"), color="positive")
                    except ApiError as error:
                        if error.status_code == 409:
                            dialog.close(); await show_stale_saved_search(int(saved["id"]))
                        else: error_label.text = error_message(error)
                confirm.on("click", remove)
            dialog.open()

        def validate_builder() -> tuple[dict[str, Any] | None, str | None]:
            try:
                if advanced_search_leaf_count(workspace["root"]) > 50:
                    raise ValueError("A search can contain at most 50 conditions.")
                if advanced_search_depth(workspace["root"]) > 5:
                    raise ValueError("A search can be nested at most five levels.")
                return compile_advanced_search_node(workspace["root"], workspace["resource"]), None
            except ValueError as error:
                return None, str(error)

        def show_validation(message: str | None) -> None:
            validation_summary.clear()
            validation_summary.set_visibility(bool(message))
            if message:
                with validation_summary:
                    ui.label(render_message("webui.show_validation.label.check_the_search_criteria_225bbe77")).classes("font-semibold text-red-800")
                    ui.label(message).classes("text-sm text-red-700")

        def update_search_enabled() -> None:
            _, error = validate_builder()
            if error:
                search_advanced.disable()
            else:
                search_advanced.enable()
            show_validation(None)
            refresh_saved_actions()
            persist_workspace()

        def replace_node(parent: list[dict[str, Any]], index: int, value: dict[str, Any]) -> None:
            parent[index] = value
            render_builder()

        def remove_node(parent: list[dict[str, Any]], index: int) -> None:
            parent.pop(index)
            render_builder()

        def duplicate_node(parent: list[dict[str, Any]], index: int, node: dict[str, Any]) -> None:
            if advanced_search_leaf_count(workspace["root"]) + advanced_search_leaf_count(node) > 50:
                ui.notify(render_message("webui.duplicate_node.notify.a_search_can_contain_at_most_50_conditions_ea7ba8dc"), color="warning")
                return
            parent.insert(index + 1, json.loads(json.dumps(node)))
            render_builder()

        def negate_node(parent: list[dict[str, Any]], index: int, node: dict[str, Any]) -> None:
            parent[index] = {"type": "group", "operator": "not", "children": [node]}
            if advanced_search_depth(workspace["root"]) > 5:
                parent[index] = node
                ui.notify(render_message("webui.negate_node.notify.groups_can_be_nested_at_most_five_levels_d998427b"), color="warning")
                return
            render_builder()


        async def browse_advanced_relationship(field_name: str, target_control: Any) -> None:
            if field_name == "classification_id":
                await browse_advanced_classification(target_control)
            elif field_name == "owning_org_unit_id":
                await show_organization_structure(selection_mode="org_unit", target_control=target_control)
            elif field_name in {"aggregation_id", "parent_aggregation_id"}:
                await browse_advanced_aggregation(target_control)

        def render_condition(node: dict[str, Any], parent: list[dict[str, Any]], index: int) -> None:
            with ui.card().classes("advanced-search-condition w-full p-2 shadow-none border border-slate-200"):
                with ui.row().classes("advanced-search-condition-row w-full items-end gap-2 flex-wrap"):
                    kind = ui.select({"structured": render_message("webui.render_condition.select.metadata_65eb8656"), "full_text": render_message("webui.render_condition.select.full_text_3ef4f841")}, value=node.get("kind", "structured"), label=render_message("webui.render_condition.select.condition_type_5394683e")).props("outlined dense options-dense").classes("w-36")
                    if node.get("kind") == "full_text":
                        query_control = ui.input(render_message("webui.render_condition.input.search_words_or_phrase_f4d8da06"), value=node.get("query", "")).props("outlined dense clearable inputmode=search").classes("advanced-search-auto-value grow min-w-64")
                        query_control.on_value_change(lambda event: (
                            node.__setitem__("query", event.value or ""),
                            update_search_enabled(), refresh_sort_options(), persist_workspace(),
                        ))
                        if workspace["resource"] == "records":
                            sources = ui.select({"metadata": render_message("webui.render_condition.select.record_metadata_505c5130"), "components": render_message("webui.render_condition.select.file_names_and_content_b85754e5")}, value=node.get("sources") or ["metadata", "components"], label=render_message("webui.render_condition.select.sources_2eec501d"), multiple=True).props("outlined dense options-dense use-chips").classes("min-w-64")
                            sources.on_value_change(lambda event: (
                                node.__setitem__("sources", event.value or []),
                                update_search_enabled(), refresh_sort_options(), persist_workspace(),
                            ))
                    else:
                        fields = advanced_search_field_options(workspace["resource"],can_manage_disposition=bool((get_principal() or {}).get("can_manage_disposition")))
                        if node.get("field")=="disposition_status" and "disposition_status" not in fields:
                            ui.label(disposition_text("restricted")).props("role=status")
                            return
                        field_name = node.get("field") if node.get("field") in fields else "title"
                        node["field"] = field_name
                        field_control = ui.select(fields, value=field_name, label=render_message("webui.render_condition.select.field_02092225")).props("outlined dense options-dense").classes("min-w-44 grow")
                        _, field_kind, nullable = ADVANCED_SEARCH_FIELDS[workspace["resource"]][field_name]
                        operators = advanced_search_operators(field_kind, nullable)
                        operator_name = node.get("operator") if node.get("operator") in operators else next(iter(operators))
                        node["operator"] = operator_name
                        operator_control = ui.select(operators, value=operator_name, label=render_message("webui.render_condition.select.operator_e4a90ad3")).props("outlined dense options-dense").classes("min-w-44")
                        if operator_name not in {"is_null", "is_not_null"}:
                            if field_kind == "boolean":
                                value_control = ui.select({True: render_message("webui.render_condition.select.yes_917fd8af"), False: render_message("webui.render_condition.select.no_b3020c97")}, value=node.get("value"), label=render_message("webui.render_condition.select.value_3acb61a0")).props("outlined dense options-dense clearable").classes("w-32")
                            elif operator_name == "between":
                                values = node.get("value") if isinstance(node.get("value"), list) else ["", ""]
                                if field_name in ADVANCED_SEARCH_RETENTION_FIELDS:
                                    first = ui.number(render_message("webui.render_condition.input.from_8e3ed147"), value=values[0] if values else None, min=0, step=1).props("outlined dense clearable dir=ltr").classes("advanced-search-technical-value min-w-40")
                                    second = ui.number(render_message("webui.render_condition.input.to_5f691965"), value=values[1] if len(values) > 1 else None, min=0, step=1).props("outlined dense clearable dir=ltr").classes("advanced-search-technical-value min-w-40")
                                else:
                                    first = ui.input(render_message("webui.render_condition.input.from_8e3ed147"), value=values[0] if values else "").props("outlined dense clearable").classes("min-w-40")
                                    second = ui.input(render_message("webui.render_condition.input.to_5f691965"), value=values[1] if len(values) > 1 else "").props("outlined dense clearable").classes("min-w-40")
                                if field_kind == "datetime":
                                    first.props(add="type=datetime-local dir=ltr").classes(add="advanced-search-technical-value")
                                    second.props(add="type=datetime-local dir=ltr").classes(add="advanced-search-technical-value")
                                first.on_value_change(lambda event: (node.__setitem__("value", [event.value, (node.get("value") or ["", ""])[1]]), update_search_enabled()))
                                second.on_value_change(lambda event: (node.__setitem__("value", [(node.get("value") or ["", ""])[0], event.value]), update_search_enabled()))
                                value_control = None
                            elif operator_name in {"in", "not_in"} and field_kind == "choice":
                                controlled_options = {
                                    value: render_message(message_key)
                                    for value, message_key in ADVANCED_SEARCH_CONTROLLED_VALUES[field_name].items()
                                }
                                selected_values = node.get("value") if isinstance(node.get("value"), list) else []
                                value_control = ui.select(
                                    controlled_options, value=[value for value in selected_values if value in controlled_options],
                                    label=render_message("webui.render_condition.select.value_3acb61a0"), multiple=True,
                                ).props("outlined dense options-dense clearable use-chips").classes("grow min-w-56")
                                value_control.on_value_change(lambda event: (node.__setitem__("value", event.value or []), update_search_enabled()))
                            elif operator_name in {"in", "not_in"}:
                                rendered = ", ".join(str(item) for item in node.get("value", [])) if isinstance(node.get("value"), list) else ""
                                value_control = ui.input(render_message("webui.render_condition.input.values_comma_separated_c3e84e2f"), value=rendered).props("outlined dense clearable").classes("advanced-search-auto-value grow min-w-56")
                                value_control.on_value_change(lambda event: (node.__setitem__("value", [part.strip() for part in str(event.value or "").split(",") if part.strip()][:100]), update_search_enabled()))
                            elif field_name in relation_sources:
                                endpoint, label_fields = relation_sources[field_name]
                                selected_value = node.get("value")
                                selected_label = str(node.get("_value_label") or "…")
                                value_control = ui.select(
                                    ({int(selected_value): selected_label} if selected_value is not None else {}),
                                    value=selected_value,
                                    label=render_message("webui.render_condition.select.value_3acb61a0"),
                                ).props("outlined dense clearable").classes("grow min-w-56")
                                style_relationship_chip_select(value_control, field_name)
                                bind_remote_relationship_select(
                                    value_control,
                                    resource=endpoint,
                                    search_fields=tuple(label_fields),
                                    label_fields=tuple(label_fields),
                                    on_options_resolved=lambda options, condition=node: (
                                        condition.__setitem__(
                                            "_value_label", options[int(condition["value"])]
                                        )
                                        if condition.get("value") is not None
                                        and int(condition["value"]) in options
                                        else None
                                    ),
                                )
                                value_control.on_value_change(
                                    lambda event, condition=node, control=value_control: (
                                        condition.__setitem__(
                                            "_value_label",
                                            dict(control.options or {}).get(event.value, ""),
                                        )
                                        if event.value is not None
                                        else condition.pop("_value_label", None)
                                    )
                                )
                                if field_name in {
                                    "aggregation_id", "parent_aggregation_id",
                                    "classification_id", "owning_org_unit_id",
                                }:
                                    ui.button(
                                        render_message("webui.render_condition.button.browse_3bc4c331"), icon="account_tree",
                                        on_click=lambda _, relationship_field=field_name, control=value_control:
                                            browse_advanced_relationship(relationship_field, control),
                                    ).props("flat dense no-caps color=primary")
                            elif field_name in ADVANCED_SEARCH_CONTROLLED_VALUES:
                                controlled_options = {
                                    value: render_message(message_key)
                                    for value, message_key in ADVANCED_SEARCH_CONTROLLED_VALUES[field_name].items()
                                }
                                selected_value = node.get("value")
                                if selected_value not in controlled_options:
                                    selected_value = None
                                    node["value"] = None
                                value_control = ui.select(
                                    controlled_options, value=selected_value, label=render_message("webui.render_condition.select.value_3acb61a0"),
                                ).props("outlined dense options-dense clearable").classes("grow min-w-56")
                                if field_name == "component.content_status":
                                    style_status_chip_select(value_control)
                            elif field_kind == "integer":
                                number_options = {"min": 0, "step": 1} if field_name in ADVANCED_SEARCH_RETENTION_FIELDS else {}
                                value_control = ui.number(render_message("advanced_search.field.value"), value=node.get("value"), **number_options).props("outlined dense clearable dir=ltr").classes("advanced-search-technical-value min-w-40")
                            else:
                                value_control = ui.input(render_message("webui.render_condition.input.value_8dc59edc"), value=node.get("value", "")).props("outlined dense clearable").classes("advanced-search-auto-value grow min-w-56")
                                if field_kind == "datetime":
                                    value_control.props(add="type=datetime-local dir=ltr").classes(add="advanced-search-technical-value")
                            if value_control is not None and operator_name not in {"in", "not_in"}:
                                value_control.on_value_change(lambda event: (node.__setitem__("value", event.value), update_search_enabled()))
                        field_control.on_value_change(lambda event: (
                            node.update(
                                field=event.value, operator="eq",
                                value=advanced_search_empty_value(
                                    event.value, "eq",
                                    ADVANCED_SEARCH_FIELDS[workspace["resource"]][event.value][1],
                                ),
                            ),
                            render_builder(),
                        ))
                        operator_control.on_value_change(lambda event: (
                            node.update(
                                operator=event.value,
                                value=advanced_search_empty_value(field_name, event.value, field_kind),
                            ),
                            render_builder(),
                        ))
                    kind.on_value_change(lambda event: (node.clear(), node.update(new_condition() if event.value == "structured" else {"type": "condition", "kind": "full_text", "query": "", "sources": ["metadata", "components"] if workspace["resource"] == "records" else ["metadata"]}), render_builder()))
                    with ui.row().classes("advanced-search-condition-actions items-center gap-0 self-end"):
                        ui.button(icon="block", on_click=lambda: negate_node(parent, index, node)).props('flat round dense aria-label=' + repr(render_message("webui.render_condition.accessible_name.negate_condition_0ee5684b"))).tooltip(render_message("webui.render_condition.tooltip.negate_9cd858a3"))
                        ui.button(icon="content_copy", on_click=lambda: duplicate_node(parent, index, node)).props('flat round dense aria-label=' + repr(render_message("webui.render_condition.accessible_name.duplicate_condition_2282d530"))).tooltip(render_message("webui.render_condition.tooltip.duplicate_93f8b940"))
                        ui.button(icon="delete", color="negative", on_click=lambda: remove_node(parent, index)).props('flat round dense aria-label=' + repr(render_message("webui.render_condition.accessible_name.remove_condition_6b0c8a12"))).tooltip(render_message("webui.render_condition.tooltip.remove_47af9389"))

        def render_group(node: dict[str, Any], parent: list[dict[str, Any]] | None = None, index: int = 0, depth: int = 1) -> None:
            labels = {"and": render_message("webui.render_group.text.all_c40a1b2b"), "or": render_message("webui.render_group.text.any_54504cd1"), "not": render_message("webui.render_group.text.not_2b98a4ad")}
            with ui.card().classes("advanced-search-group w-full p-2 shadow-none border-l-4 border-blue-300 bg-slate-50").props(
                'role=group aria-label=' + repr(render_message(
                    "advanced_search.group.accessible_name",
                    operator=labels.get(node.get("operator", "and"), render_message("advanced_search.group.boolean")),
                    depth=depth,
                ))
            ):
                with ui.row().classes("advanced-search-group-toolbar w-full items-center gap-2"):
                    group_operator = ui.select(labels, value=node.get("operator", "and"), label=render_message("webui.render_group.select.match_c4607f29")).props("outlined dense options-dense").classes("w-32")
                    ui.label(render_message("webui.render_group.label.level_depth_40cb374d", depth=depth)).classes("text-xs text-slate-500")
                    ui.space()
                    add_condition = ui.button(render_message("webui.render_group.button.condition_d5d2516f"), icon="add").props("flat dense no-caps")
                    add_group = ui.button(render_message("webui.render_group.button.group_3a670cc7"), icon="account_tree").props("flat dense no-caps")
                    if parent is not None:
                        ui.button(icon="block", on_click=lambda: negate_node(parent, index, node)).props('flat round dense aria-label=' + repr(render_message("webui.render_group.accessible_name.negate_group_bed5f9ae"))).tooltip(render_message("webui.render_group.tooltip.negate_12f5d3d7"))
                        ui.button(icon="content_copy", on_click=lambda: duplicate_node(parent, index, node)).props('flat round dense aria-label=' + repr(render_message("webui.render_group.accessible_name.duplicate_group_6c8dc686"))).tooltip(render_message("webui.render_group.tooltip.duplicate_fdc06841"))
                        ui.button(icon="delete", color="negative", on_click=lambda: remove_node(parent, index)).props('flat round dense aria-label=' + repr(render_message("webui.render_group.accessible_name.remove_group_2edf8a7e"))).tooltip(render_message("webui.render_group.tooltip.remove_58552cd7"))
                children_host = ui.column().classes("w-full gap-1 pl-2")
                children = node.setdefault("children", [])
                with children_host:
                    for child_index, child in enumerate(list(children)):
                        if child.get("type") == "group":
                            render_group(child, children, child_index, depth + 1)
                        else:
                            render_condition(child, children, child_index)
                if node.get("operator") == "not" and children:
                    add_condition.disable()
                    add_group.disable()

                def change_group_operator(event: Any) -> None:
                    previous_operator = node.get("operator", "and")
                    previous_children = list(children)
                    if event.value == "not" and len(children) > 1:
                        node["children"] = [{"type": "group", "operator": "and", "children": list(children)}]
                    node["operator"] = event.value
                    if advanced_search_depth(workspace["root"]) > 5:
                        node["operator"] = previous_operator
                        node["children"] = previous_children
                        ui.notify(render_message("webui.change_group_operator.notify.groups_can_be_nested_at_most_five_expressi_cb065045"), color="warning")
                    render_builder()

                group_operator.on_value_change(change_group_operator)
                add_condition.on("click", lambda: (children.append(new_condition()), render_builder()) if advanced_search_leaf_count(workspace["root"]) < 50 else ui.notify(render_message("webui.render_group.notify.a_search_can_contain_at_most_50_conditions_17aaa789"), color="warning"))
                add_group.on("click", lambda: (children.append({"type": "group", "operator": "and", "children": [new_condition()]}), render_builder()) if depth < 4 and advanced_search_leaf_count(workspace["root"]) < 50 else ui.notify(render_message("webui.render_group.notify.groups_can_be_nested_at_most_five_expressi_15cd18ec"), color="warning"))

        def render_builder() -> None:
            component_scope_help.set_visibility(
                workspace["resource"] == "records"
                and advanced_search_has_component_field(workspace["root"])
            )
            builder_host.clear()
            with builder_host:
                render_group(workspace["root"])
            update_search_enabled()
            refresh_sort_options()
            persist_workspace()

        def refresh_sort_options() -> None:
            options = {
                name: render_message(details[0])
                for name, details in ADVANCED_SEARCH_FIELDS[workspace["resource"]].items()
                if name not in ADVANCED_SEARCH_COMPONENT_FIELDS and name not in ADVANCED_SEARCH_RETENTION_FIELDS and (name!="disposition_status" or (get_principal() or {}).get("can_manage_disposition"))
            }
            options["id"] = render_message("advanced_search.sort.identifier")
            try:
                expression = compile_advanced_search_node(workspace["root"], workspace["resource"])
                if advanced_search_has_positive_full_text(workspace["root"]):
                    options = {"_relevance": render_message("webui.refresh_sort_options.text.relevance_5632eeed"), **options}
            except ValueError:
                pass
            sort_field.options = options
            if workspace["sort_field"] not in options:
                workspace["sort_field"] = "_relevance" if "_relevance" in options else "id"
            sort_field.value = workspace["sort_field"]
            sort_field.update()

        async def execute_search() -> None:
            if not search_view_is_current():
                return
            expression, error = validate_builder()
            if error:
                show_validation(error)
                validation_summary.run_method("focus")
                return
            workspace.update(busy=True, error=None)
            search_advanced.disable()
            status_label.text = render_message("webui.execute_search.text.searching_ec84eae6")
            results_host.clear()
            with results_host:
                ui.spinner(size="lg").classes("self-center")
            try:
                maximum = max(1, min(5000, int(max_results.value or 1000)))
                workspace["max_results"] = maximum
                remaining = maximum - workspace["offset"]
                if remaining <= 0:
                    workspace["offset"] = 0
                    remaining = maximum
                payload = {
                    "where": expression,
                    "sort": [{"field": workspace["sort_field"], "direction": workspace["sort_direction"]}],
                    "limit": min(workspace["limit"], remaining), "offset": workspace["offset"],
                }
                if advanced_search_has_positive_full_text(workspace["root"]):
                    payload["include"] = ["full_text_matches"]
                saved = workspace.get("saved")
                if saved is not None and not is_dirty():
                    result = await api.execute_saved_search(
                        int(saved["id"]), {"limit": payload["limit"], "offset": payload["offset"]},
                    )
                else:
                    result = await api.search_request(workspace["resource"], payload)
                if not search_view_is_current():
                    return
                workspace["record_component_details"] = {}
                workspace["record_capabilities"] = {}
                if workspace["resource"] == "records":
                    async def load_matching_component_details(
                        record_item: dict[str, Any],
                    ) -> tuple[int, dict[str, Any], list[dict[str, Any]]]:
                        try:
                            record_id = int(record_item["id"])
                            capabilities, components = await asyncio.gather(
                                api.resource_capabilities("records", record_id),
                                api.component_page(record_id, limit=25),
                            )
                            return record_id, capabilities, components["items"]
                        except ApiError:
                            return int(record_item["id"]), {}, []
                    component_contexts = await asyncio.gather(*(
                        load_matching_component_details(record_item) for record_item in result.get("items", [])
                    ))
                    if not search_view_is_current():
                        return
                    workspace["record_component_details"] = {
                        record_id: components for record_id, _, components in component_contexts
                    }
                    workspace["record_capabilities"] = {
                        record_id: capabilities for record_id, capabilities, _ in component_contexts
                    }
                workspace["total"] = min(int(result["total"]), maximum)
                workspace["searched"] = True
                render_results(result)
            except ApiError as api_error:
                if not search_view_is_current():
                    return
                results_host.clear()
                with results_host, ui.card().classes("w-full border border-red-200 bg-red-50 p-4 shadow-none"):
                    ui.label(render_message_plain("webui.execute_search.label.the_search_could_not_be_completed_f959e209")).classes("font-semibold text-red-800")
                    ui.label(error_message(api_error)).classes("text-sm text-red-700")
                status_label.text = render_message("webui.execute_search.text.search_failed_e44b669e")
            finally:
                workspace["busy"] = False
                if search_view_is_current():
                    search_advanced.enable()
                    persist_workspace()

        def render_results(result: dict[str, Any]) -> None:
            if not search_view_is_current():
                return
            workspace["last_result"] = copy.deepcopy(result)
            results_host.clear()
            freshness_host.clear()
            freshness = result.get("index_freshness") or {}
            if freshness.get("has_pending_content"):
                with freshness_host, ui.card().classes("w-full p-3 shadow-none border border-amber-200 bg-amber-50"):
                    with ui.row().classes("w-full items-center gap-2"):
                        ui.icon("hourglass_top").classes("text-amber-700")
                        ui.label(render_message("webui.render_results.label.some_authorized_file_content_is_still_bein_598843e0")).classes("text-sm text-amber-900")
            items = result.get("items", [])
            start = workspace["offset"] + 1 if items else 0
            end = workspace["offset"] + len(items)
            total = workspace["total"]
            status_label.text = render_message("webui.render_results.text.total_authorized_result_value_da53e146", total=format(total, ','), value='s' if total != 1 else '')
            range_label.text = render_message("webui.render_results.text.start_end_of_total_a1dbcf9a", start=format(start, ','), end=format(end, ','), total=format(total, ','))
            pagination.set_visibility(total > 0)
            first_page.set_enabled(workspace["offset"] > 0)
            previous_page.set_enabled(workspace["offset"] > 0)
            next_page.set_enabled(end < total)
            last_page.set_enabled(end < total)
            if not items:
                with results_host, ui.card().classes("w-full p-8 items-center shadow-none border border-slate-200"):
                    ui.icon("search_off", size="42px").classes("text-slate-400")
                    ui.label(render_message("webui.render_results.label.no_authorized_results_matched_this_search_897e7e5e")).classes("font-semibold")
                    ui.label(render_message("webui.render_results.label.change_a_condition_or_broaden_the_criteria_da24d5dc")).classes("text-sm text-slate-500")
                return
            with results_host:
                with ui.column().classes("compact-result-list w-full gap-0"):
                    uses_full_text = advanced_search_has_positive_full_text(workspace["root"])
                    for item in items:
                        search_meta = item.get("_search") or {}
                        authorized_component_details = {
                            int(component["id"]): component
                            for component in workspace.get("record_component_details", {}).get(int(item["id"]), [])
                        }
                        matching_components = [
                            {**authorized_component_details.get(int(component["id"]), {}), **component}
                            for component in search_meta.get("matching_components", [])
                            if component.get("id") is not None
                        ]
                        record_capabilities = workspace.get("record_capabilities", {}).get(
                            int(item["id"]), {}
                        )
                        if workspace["resource"] == "records":
                            displayed_components = (
                                matching_components if uses_full_text
                                else list(authorized_component_details.values())
                            )
                            render_compact_resource_result(
                                "records", item,
                                on_open=lambda selected: open_advanced_record(int(selected["id"]),selected.get("disposition_status")),
                                components=displayed_components,
                                metadata_matched=bool(search_meta.get("metadata_matched")),
                                content_matched=bool(matching_components),
                                show_medium=True,
                                can_preview=bool(
                                    record_capabilities.get("view_component")
                                    and any(component_is_previewable(component) for component in authorized_component_details.values())
                                ),
                                can_expand_components=bool(
                                    record_capabilities.get("list_components") and displayed_components
                                ),
                                components_are_matches=uses_full_text,
                                initially_expanded=int(item["id"]) in set(
                                    int(value) for value in workspace.get("expanded_results", [])
                                ),
                                on_expansion_changed=lambda expanded, identifier=int(item["id"]):
                                    set_advanced_result_expansion(identifier, expanded),
                            )
                        else:
                            render_compact_resource_result(
                                "aggregations", item,
                                on_open=lambda selected: open_advanced_aggregation(int(selected["id"]),selected.get("disposition_status")),
                                metadata_matched=bool(search_meta.get("metadata_matched")),
                                show_medium=True,
                            )
            restore_compact_result_anchor(workspace.pop("return_anchor", None))

        async def open_destroyed_search_result(kind: str, identifier: int):
            from frontend.webui.disposition.destruction import retained_detail
            try:proof=await api.disposition_page(f"retained/{kind}/{identifier}")
            except ApiError as error:
                if search_view_is_current():ui.notify(error_message(error),type='negative')
                return
            if search_view_is_current():await retained_detail(api=api,proof=proof,active=search_view_is_current,on_error=error_message,format_timestamp=format_timestamp)

        async def open_advanced_record(identifier: int, disposition_status: int | None = None) -> None:
            if disposition_status==10:
                await open_destroyed_search_result('record',identifier)
                return
            workspace["return_anchor"] = f"compact-result-records-{int(identifier)}"
            persist_workspace()
            discard_navigation_guard()
            await select_record_details(identifier)

        async def open_advanced_aggregation(identifier: int, disposition_status: int | None = None) -> None:
            if disposition_status==10:
                await open_destroyed_search_result('aggregation',identifier)
                return
            workspace["return_anchor"] = f"compact-result-aggregations-{int(identifier)}"
            persist_workspace()
            discard_navigation_guard()
            await open_aggregation(await api.get("aggregations", identifier))

        async def confirm_target_reset() -> bool:
            with ui.dialog() as dialog, ui.card().classes("w-[480px] max-w-full p-5 gap-4"):
                ui.label(render_message("webui.confirm_target_reset.label.change_search_target_bc42440d")).classes("text-lg font-semibold")
                ui.label(render_message("webui.confirm_target_reset.label.changing_the_target_resets_all_criteria_be_f52ba27b")).classes("text-sm text-slate-600")
                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.confirm_target_reset.button.cancel_6f1ce483"), on_click=lambda: dialog.submit(False)).props("flat no-caps")
                    ui.button(render_message("webui.confirm_target_reset.button.change_target_31a62b29"), on_click=lambda: dialog.submit(True)).props("unelevated no-caps")
            return bool(await dialog)

        async def change_target(event: Any) -> None:
            if workspace.get("loading") or not search_view_is_current():
                return
            requested = event.value
            # NiceGUI may deliver programmatic value-change events after loading
            # has finished. Ignore superseded events and already-applied values.
            if requested != target.value or requested == workspace["resource"]:
                return
            was_dirty = is_dirty()
            if was_dirty or workspace.get("saved") is not None:
                confirmed = await confirm_target_reset()
                if not confirmed:
                    target.value = workspace["resource"]
                    target.update()
                    return
            # A target change starts a new search; the loaded saved search is
            # left intact and must no longer supply metadata or update actions.
            workspace["resource"] = requested
            reset_search(clear_metadata=True)

        def reset_search(*, clear_metadata: bool = False) -> None:
            workspace.update(root={"type": "group", "operator": "and", "children": [new_condition()]}, sort_field="id", sort_direction="asc", limit=25, max_results=1000, offset=0, total=0, searched=False, last_result=None)
            workspace.update(expanded_results=[], record_component_details={}, record_capabilities={})
            workspace.pop("return_anchor", None)
            if clear_metadata:
                workspace.update(
                    saved=None, audience_mode="private", role_ids=[], org_unit_ids=[],
                    search_name="", search_category=None, search_description="",
                )
                search_name.value = ""; search_category.value = None; search_description.value = ""
            max_results.value = 1000
            page_size.value = 25
            sort_direction.value = "asc"
            results_host.clear()
            freshness_host.clear()
            pagination.set_visibility(False)
            status_label.text = ""
            render_builder()
            refresh_sort_options()
            workspace["baseline"] = current_saved_signature()
            refresh_saved_actions()
            persist_workspace()

        async def start_new_search() -> None:
            if await confirm_discard_changes("start a new search"):
                reset_search(clear_metadata=True)

        async def move_page(offset: int) -> None:
            workspace["offset"] = max(0, min(offset, max(0, workspace["total"] - 1)))
            workspace["offset"] = (workspace["offset"] // workspace["limit"]) * workspace["limit"]
            await execute_search()

        target.on_value_change(change_target)
        max_results.on_value_change(lambda event: (
            workspace.__setitem__("max_results", max(1, min(5000, int(event.value or 1000)))),
            persist_workspace(),
        ))
        sort_field.on_value_change(lambda event: (workspace.__setitem__("sort_field", event.value), persist_workspace()))
        sort_direction.on_value_change(lambda event: (workspace.__setitem__("sort_direction", event.value), persist_workspace()))
        page_size.on_value_change(lambda event: (workspace.update(limit=int(event.value), offset=0), persist_workspace()))
        search_advanced.on("click", execute_search)
        reset_advanced.on("click", reset_search)
        new_button.on("click", start_new_search)
        open_button.on("click", open_saved_search_dialog)
        save_button.on("click", lambda: save_search(save_as=False))
        edit_details_button.on(
            "click", lambda: save_search(save_as=False, edit_details=True),
        )
        save_as_button.on("click", lambda: save_search(save_as=True))
        delete_button.on("click", delete_saved_search)
        first_page.on("click", lambda: move_page(0))
        previous_page.on("click", lambda: move_page(workspace["offset"] - workspace["limit"]))
        next_page.on("click", lambda: move_page(workspace["offset"] + workspace["limit"]))
        last_page.on("click", lambda: move_page(max(0, workspace["total"] - 1)))
        administered_search_id = advanced_search_state.pop("admin_saved_search_id", None)
        if administered_search_id is not None:
            try:
                load_saved_into_workspace(await api.saved_search(int(administered_search_id)))
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)
                render_builder()
        else:
            render_builder()
        if workspace.get("baseline") is None:
            workspace["baseline"] = current_saved_signature()
        refresh_saved_actions()
        if workspace.get("searched") and isinstance(workspace.get("last_result"), dict):
            render_results(workspace["last_result"])
        persist_workspace()


    return select_advanced_search
