"""Existing organization memberships view with explicit per-client dependencies."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from .entity_editor_controls import entity_metadata_label
from .relationship_select import relationship_select
from .i18n_catalogue import render_message
from nicegui import ui


def build_organization_memberships(
    *, add_timestamp_slots, api, bind_remote_relationship_select, error_message, localized_lifecycle_value, show_api_error, show_organization_structure, user_avatar,
):
    async def show_memberships(entity: dict[str, Any], *, for_user: bool) -> None:
        dialog = ui.dialog()
        counterpart_resource = "roles" if for_user else "users"
        counterpart_label = "role" if for_user else "user"
        localized_counterpart_label = render_message(
            "entity_metadata.field.role" if for_user else "entity_metadata.field.user"
        )
        assignment_allowed = (
            entity.get("effective_status", entity.get("status", "active")) == "active"
        )
        assigned_ids: set[int] = set()
        unfiltered_assignments: dict[int, int] = {}
        assignment_page = {
            "offset": 0, "limit": 25, "total": 0, "sort": "counterpart", "descending": False,
            "criteria": {}, "revision": 0, "loading": False,
        }
        clearing_filters = False
        reader = api.user_roles if for_user else api.role_users
        counterpart_id_field = "role_id" if for_user else "user_id"

        def table_pagination() -> dict[str, Any]:
            return {
                "page": 1 + assignment_page["offset"] // assignment_page["limit"],
                "rowsPerPage": assignment_page["limit"],
                "rowsNumber": assignment_page["total"],
                "sortBy": assignment_page["sort"],
                "descending": assignment_page["descending"],
            }

        def read_filters() -> dict[str, Any]:
            status_key = "role_status" if for_user else "user_status"
            return {key: value for key, value in (
                ("membership_q", (membership_search.value or "").strip()),
                (status_key, membership_status.value if membership_status.value != "all" else None),
                ("valid_from", membership_valid_from.value),
                ("valid_until", membership_valid_until.value),
            ) if value}

        def membership_filters_changed():
            if not clearing_filters:
                return load_assignments(offset=0, criteria=read_filters())

        async def clear_membership_filters() -> None:
            nonlocal clearing_filters
            clearing_filters = True
            try:
                membership_status.set_value("all")
                membership_valid_from.set_value(None)
                membership_valid_until.set_value(None)
            finally:
                clearing_filters = False
            await load_assignments(offset=0, criteria=read_filters())

        def render_rows(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
            rows = []
            for assignment in assignments:
                counterpart_id = assignment[counterpart_id_field]
                counterpart = assignment.get("counterpart") or {}
                status = counterpart.get("status", "inactive")
                if for_user:
                    status_label = (
                        render_message("webui.load_held_itemships.text.active_537ddc31")
                        if status == "active" else render_message("webui.load_held_itemships.text.inactive_06345426")
                    )
                else:
                    status_label = localized_lifecycle_value(status)
                rows.append({
                    **assignment,
                    "counterpart": (
                        f"{counterpart.get('code', '')} — {counterpart.get('name', counterpart_id)}"
                        if for_user else counterpart.get("name", counterpart_id)
                    ),
                    "counterpart_name": counterpart.get("name", str(counterpart_id)),
                    "counterpart_email": counterpart.get("email") or "",
                    "counterpart_avatar": user_avatar(counterpart) if not for_user else None,
                    "counterpart_status": status,
                    "counterpart_status_label": status_label,
                })
            return rows

        async def load_assignments(
            *, offset: int | None = None, criteria: dict[str, Any] | None = None,
            sort: str | None = None, descending: bool | None = None,
        ) -> None:
            if not dialog.value or dialog.is_deleted:
                return
            offset = assignment_page["offset"] if offset is None else offset
            criteria = assignment_page["criteria"] if criteria is None else criteria
            sort = assignment_page["sort"] if sort is None else sort
            descending = assignment_page["descending"] if descending is None else descending
            limit = assignment_page["limit"]
            assignment_page["revision"] += 1
            revision = assignment_page["revision"]
            assignment_page["loading"] = True

            def current() -> bool:
                return revision == assignment_page["revision"] and dialog.value and not dialog.is_deleted

            try:
                params = dict(limit=limit, sort=sort, descending=descending, **criteria)
                result = await reader(entity["id"], offset=offset, **params)
                if current() and not result["items"] and offset:
                    offset = max(0, (int(result["total"]) - 1) // limit * limit)
                    result = await reader(entity["id"], offset=offset, **params)
            except ApiError as error:
                if current():
                    ui.notify(error_message(error), color="negative", close_button=True)
                return
            finally:
                if current():
                    assignment_page["loading"] = False

            if not current():
                return
            assignments = result["items"]
            total = int(result["total"])
            assignment_page.update(offset=offset, total=total, criteria=criteria, sort=sort, descending=descending)
            assigned_ids.clear()
            assigned_ids.update(item[counterpart_id_field] for item in assignments)
            if not criteria:
                unfiltered_assignments.clear()
                unfiltered_assignments.update((item["id"], item[counterpart_id_field]) for item in assignments)
            membership_table.rows = render_rows(assignments)
            membership_table.pagination = table_pagination()
            membership_table.update()
            show_filters = bool(total or criteria)
            membership_results.set_visibility(show_filters)
            empty_label.set_visibility(not total)
            empty_label.text = (
                render_message("webui.render_governance_cards.label.no_matching_items_38db9ba1") if criteria else
                render_message("webui.load_held_itemships.label.no_counterpart_label_s_assigned_09a70b6e", counterpart_label=localized_counterpart_label)
            )
            membership_table.set_visibility(bool(total))
            pager.set_visibility(show_filters)
            page_label.text = render_message(
                "webui.load_held_itemships.label.start_end_total_caa5dacc",
                start=offset + 1 if assignments else 0, end=offset + len(assignments), total=total,
            )
            previous_assignments.set_enabled(offset > 0)
            next_assignments.set_enabled(offset + len(assignments) < total)

        async def move_assignment_page(direction: int) -> None:
            offset = assignment_page["offset"] + direction * assignment_page["limit"]
            if not assignment_page["loading"] and 0 <= offset < assignment_page["total"]:
                await load_assignments(offset=offset)

        async def sort_assignments(event) -> None:
            pagination = event.args["pagination"]
            sort = pagination.get("sortBy") or "counterpart"
            descending = bool(pagination.get("descending"))
            if (sort, descending) != (assignment_page["sort"], assignment_page["descending"]):
                await load_assignments(offset=0, criteria=read_filters(), sort=sort, descending=descending)

        async def remove_assignment(event) -> None:
            assignment = event.args
            try:
                await api.delete_assignment(assignment["id"], assignment["version"])
                if dialog.value and not dialog.is_deleted:
                    unfiltered_assignments.pop(assignment["id"], None)
                    ui.notify(render_message("webui.remove_assignment.notify.assignment_removed_d3a39d0c"), color="positive")
                    await load_assignments(criteria=read_filters())
            except ApiError as error:
                if dialog.value and not dialog.is_deleted:
                    show_api_error(error)

        async def assign() -> None:
            counterpart_id = counterpart_picker.value
            if counterpart_id is None:
                ui.notify(render_message("webui.assign.notify.select_a_counterpart_label_ba181b86", counterpart_label=localized_counterpart_label), color="warning")
                return
            payload = {
                "user_id": entity["id"] if for_user else int(counterpart_id),
                "role_id": int(counterpart_id) if for_user else entity["id"],
            }
            try:
                await api.create("user-role-assignments", payload)
                if dialog.value and not dialog.is_deleted:
                    ui.notify(render_message("webui.assign.notify.capitalize_assigned_dd48342e", capitalize=localized_counterpart_label), color="positive")
                    counterpart_picker.value = None
                    await load_assignments(criteria=read_filters())
            except ApiError as error:
                if dialog.value and not dialog.is_deleted:
                    ui.notify(error_message(error), color="negative", close_button=True)

        with dialog, ui.card().classes(
            "membership-dialog flex flex-col"
        ):
            heading = entity.get("name") or entity.get("code") or entity["id"]
            ui.label(render_message("webui.show_memberships.label.capitalize_assignments_heading_ecd9d308", capitalize=localized_counterpart_label, heading=heading)).classes("text-xl font-semibold")
            if not assignment_allowed:
                with ui.row().classes("w-full items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg"):
                    ui.icon("block", color="amber-8")
                    ui.label(
                    render_message("webui.show_memberships.label.new_assignments_are_unavailable_while_this_9dc434ca")
                    ).classes("text-sm text-amber-900")
            empty_label = ui.label().classes("text-slate-500 py-4")
            empty_label.set_visibility(False)
            with ui.column().classes("w-full min-h-0 overflow-hidden") as membership_results:
                def toggle_filter_panel() -> None:
                    filter_panel.set_visibility(not filter_panel.visible)

                with ui.row().classes("w-full items-center gap-2"):
                    membership_search = ui.input(
                        render_message(
                            "webui.show_memberships.input.search_counterpart_name_or_code"
                            if for_user else
                            "webui.show_memberships.input.search_counterpart_name_or_email",
                            counterpart=localized_counterpart_label,
                        ),
                    ).props("outlined dense clearable debounce=250").classes(
                        "grow max-w-[430px] min-w-[220px]"
                    )
                    ui.button(
                        render_message("webui.load_held_itemships.button.filters_d7704feb"), icon="filter_list", on_click=toggle_filter_panel,
                    ).props("flat dense no-caps color=primary").tooltip(
                        render_message("webui.load_held_itemships.tooltip.filter_by_status_or_assignment_validity_b46438f9")
                    )
                filter_panel = ui.row().classes(
                    "w-full items-end gap-2 flex-nowrap overflow-x-auto rounded-lg "
                    "bg-slate-50 border border-slate-200 p-3"
                )
                with filter_panel:
                    status_options = {
                        "all": render_message("webui.load_held_itemships.text.all_statuses_6b30cb23"), "active": render_message("webui.load_held_itemships.text.active_9406c1d5"),
                        "inactive": render_message("webui.load_held_itemships.text.inactive_fff50323"),
                    }
                    if not for_user:
                        status_options["suspended"] = localized_lifecycle_value("suspended")
                    membership_status = ui.select(
                        status_options,
                        value="all", label=render_message("webui.load_held_itemships.select.status_f583ecf6"),
                    ).props("outlined dense options-dense").classes("w-40 shrink-0")
                    membership_valid_from = ui.input(
                        render_message("webui.load_held_itemships.input.valid_during_or_after_426a5d0b"),
                    ).props("outlined dense type=date clearable").classes("w-40 shrink-0")
                    membership_valid_until = ui.input(
                        render_message("webui.load_held_itemships.input.valid_during_or_before_d4e95a3d"),
                    ).props("outlined dense type=date clearable").classes("w-40 shrink-0")
                    ui.button(
                        icon="filter_alt_off", on_click=clear_membership_filters,
                    ).props('flat round dense color=grey-7 aria-label=' + repr(render_message("webui.load_held_itemships.accessible_name.clear_filters_2f8c06a6"))).tooltip(
                        render_message("webui.load_held_itemships.tooltip.clear_filters_6414665b")
                    )
                filter_panel.set_visibility(False)
                membership_table = ui.table(
                    columns=[
                        {"name": "counterpart", "label": localized_counterpart_label, "field": "counterpart", "align": "left", "sortable": True},
                        {"name": "counterpart_status", "label": entity_metadata_label("Status"), "field": "counterpart_status", "align": "left", "sortable": True},
                        {"name": "valid_from", "label": render_message("webui.show_memberships.table.valid_from"), "field": "valid_from", "align": "left", "sortable": True},
                        {"name": "valid_until", "label": render_message("webui.show_memberships.table.valid_until"), "field": "valid_until", "align": "left", "sortable": True},
                        {"name": "actions", "label": "", "field": "actions", "align": "right"},
                    ],
                    rows=[],
                    row_key="id",
                    pagination=table_pagination(),
                ).props("flat bordered dense hide-bottom").classes("w-full membership-table")

                if not for_user:
                    membership_table.add_slot(
                        "body-cell-counterpart",
                        '''
                        <q-td :props="props">
                          <div class="column">
                            <div class="row items-center no-wrap q-gutter-sm">
                              <q-avatar size="36px" :style="{ backgroundColor: props.row.counterpart_avatar.color, color: props.row.counterpart_avatar.text_color }">
                                {{ props.row.counterpart_avatar.initials }}
                              </q-avatar>
                              <div class="column">
                                <span>{{ props.row.counterpart_name }}</span>
                                <span v-if="props.row.counterpart_email" class="text-caption text-grey-7">{{ props.row.counterpart_email }}</span>
                              </div>
                            </div>
                          </div>
                        </q-td>
                        ''',
                    )

                add_timestamp_slots(membership_table, ["valid_from", "valid_until"])
                membership_table.add_slot(
                    "body-cell-counterpart_status",
                    '''
                    <q-td :props="props">
                      <q-badge
                        :color="props.value === 'active' ? 'positive' : (props.value === 'suspended' ? 'warning' : 'grey-7')"
                        :label="props.row.counterpart_status_label"
                      />
                    </q-td>
                    ''',
                )
                membership_table.add_slot(
                    "body-cell-actions",
                    '<q-td :props="props"><q-btn flat round dense icon="person_remove" color="negative" @click="$parent.$emit(\'remove\', props.row)"><q-tooltip>Remove assignment</q-tooltip></q-btn></q-td>',
                )

                for control in (membership_search, membership_status, membership_valid_from, membership_valid_until):
                    control.on_value_change(membership_filters_changed)
                membership_table.on("remove", remove_assignment)
                membership_table.on("request", sort_assignments)
                with ui.row().classes("w-full items-center gap-2") as pager:
                    page_label = ui.label().classes("text-xs text-slate-500 grow")
                    previous_assignments = ui.button(icon="chevron_left", on_click=lambda: move_assignment_page(-1)).props("flat round dense")
                    next_assignments = ui.button(icon="chevron_right", on_click=lambda: move_assignment_page(1)).props("flat round dense")
            membership_results.set_visibility(False)
            with ui.row().classes("w-full items-end gap-2"):
                counterpart_picker = relationship_select(
                    render_message(
                        "webui.show_memberships.select.counterpart",
                        counterpart=localized_counterpart_label,
                    ), {}
                ).classes("grow")
                bind_remote_relationship_select(
                    counterpart_picker,
                    resource=counterpart_resource,
                    search_fields=("code", "name") if for_user else ("name", "email"),
                    label_fields=("code", "name") if for_user else ("name", "email"),
                    item_filter=lambda item: (
                        item.get("status") == "active"
                        and int(item["id"]) not in assigned_ids
                        and int(item["id"]) not in unfiltered_assignments.values()
                    ),
                )
                ui.button(
                    render_message("webui.show_memberships.button.browse_aed12689"), icon="account_tree",
                    on_click=lambda: show_organization_structure(
                        selection_mode="role" if for_user else "user",
                        target_control=counterpart_picker,
                    ),
                ).props('outline no-caps color=primary aria-label=' + repr(render_message("webui.show_memberships.accessible_name.browse_organization_structure_0d480876"))).tooltip(
                    render_message("webui.show_memberships.tooltip.browse_and_select_a_counterpart_label_908694f6", counterpart_label=localized_counterpart_label)
                )
                assign_button = ui.button(render_message("webui.show_memberships.button.assign_e003b2ce"), on_click=assign, icon="person_add").props("unelevated")
                if not assignment_allowed:
                    counterpart_picker.disable()
                    assign_button.disable()
            with ui.row().classes("w-full justify-end"):
                ui.button(render_message("webui.show_memberships.button.close_4c7a508f"), on_click=dialog.close).props("flat")
        dialog.open()
        await load_assignments()


    return show_memberships

