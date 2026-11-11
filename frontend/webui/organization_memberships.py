"""Existing organization memberships view with explicit per-client dependencies."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from .entity_editor_controls import entity_metadata_label
from .relationship_select import relationship_select
from .i18n_catalogue import render_message
from nicegui import ui


def build_organization_memberships(
    *, add_timestamp_slots, api, bind_remote_relationship_select, error_message, filter_membership_rows, localized_lifecycle_value, show_api_error, show_organization_structure, user_avatar,
):
    async def show_memberships(entity: dict[str, Any], *, for_user: bool) -> None:
        dialog = ui.dialog()
        entity_kind = "user" if for_user else "role"
        counterpart_resource = "roles" if for_user else "users"
        counterpart_label = "role" if for_user else "user"
        localized_counterpart_label = render_message(
            "entity_metadata.field.role" if for_user else "entity_metadata.field.user"
        )
        assignment_allowed = (
            entity.get("effective_status", entity.get("status", "active")) == "active"
        )
        assignments_area: Any = None
        selection_holder: dict[str, Any] = {}
        assigned_ids: set[int] = set()
        assignment_page = {"offset": 0, "limit": 25, "total": 0}

        async def load_held_itemships() -> None:
            try:
                result = await (
                    api.user_roles(
                        entity["id"], limit=assignment_page["limit"],
                        offset=assignment_page["offset"],
                    ) if for_user else api.role_users(
                        entity["id"], limit=assignment_page["limit"],
                        offset=assignment_page["offset"],
                    )
                )
                assignments = result["items"]
                assignment_page["total"] = int(result["total"])
                if not assignments and assignment_page["offset"] and assignment_page["total"]:
                    assignment_page["offset"] = max(
                        0, assignment_page["offset"] - assignment_page["limit"],
                    )
                    await load_held_itemships()
                    return
                assigned_ids.clear()
                assigned_ids.update({
                    item["role_id" if for_user else "user_id"] for item in assignments
                })
                selection_holder["control"].value = None
                selection_holder["control"].update()
                assignments_area.clear()
                with assignments_area:
                    if not assignments:
                        ui.label(render_message("webui.load_held_itemships.label.no_counterpart_label_s_assigned_09a70b6e", counterpart_label=localized_counterpart_label)).classes("text-slate-500 py-4")
                    else:
                        rows = []
                        for assignment in assignments:
                            counterpart_id = assignment["role_id" if for_user else "user_id"]
                            counterpart = assignment.get("counterpart") or {}
                            inactive_reason = ""
                            effective_status = counterpart.get("status", render_message("webui.load_held_itemships.text.inactive_06345426"))
                            if for_user:
                                if counterpart.get("status") != "active":
                                    effective_status = render_message("webui.load_held_itemships.text.inactive_06345426")
                                    inactive_reason = "This role is directly inactive."
                                else:
                                    effective_status = render_message("webui.load_held_itemships.text.active_537ddc31")
                                    inactive_reason = "This role is effective."
                            elif effective_status == "active":
                                inactive_reason = "This user is active."
                            elif effective_status == "suspended":
                                inactive_reason = "This user is suspended."
                            else:
                                inactive_reason = "This user is inactive."
                            rows.append({
                                **assignment,
                                "counterpart": (
                                    f"{counterpart.get('code', '')} — {counterpart.get('name', counterpart_id)}"
                                    if for_user else counterpart.get("name", counterpart_id)
                                ),
                                "counterpart_name": counterpart.get("name", str(counterpart_id)),
                                "counterpart_email": counterpart.get("email") or "",
                                "counterpart_avatar": user_avatar(counterpart) if not for_user else None,
                                "counterpart_search": " ".join(
                                    str(value) for value in (
                                        counterpart.get("code"), counterpart.get("name"),
                                        counterpart.get("email"),
                                    ) if value
                                ),
                                "counterpart_status": effective_status,
                                "counterpart_status_label": localized_lifecycle_value(effective_status),
                                "counterpart_status_reason": inactive_reason,
                            })
                        filter_panel: Any = None

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
                                icon="filter_alt_off",
                                on_click=lambda: (
                                    membership_status.set_value("all"),
                                    membership_valid_from.set_value(None),
                                    membership_valid_until.set_value(None),
                                ),
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
                            rows=rows,
                            row_key="id",
                            pagination={"rowsPerPage": 10, "sortBy": "counterpart", "descending": False},
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

                        def apply_membership_filters() -> None:
                            membership_table.rows = filter_membership_rows(
                                rows,
                                query=membership_search.value or "",
                                status=membership_status.value or "all",
                                valid_from=membership_valid_from.value or None,
                                valid_until=membership_valid_until.value or None,
                            )
                            membership_table.update()

                        for control in (
                            membership_search, membership_status,
                            membership_valid_from, membership_valid_until,
                        ):
                            control.on_value_change(apply_membership_filters)
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

                        async def remove_assignment(event) -> None:
                            assignment = event.args
                            try:
                                await api.delete_assignment(assignment["id"], assignment["version"])
                                ui.notify(render_message("webui.remove_assignment.notify.assignment_removed_d3a39d0c"), color="positive")
                                await load_held_itemships()
                            except ApiError as error:
                                show_api_error(error)

                        membership_table.on("remove", remove_assignment)
                        with ui.row().classes("w-full items-center gap-2"):
                            start = assignment_page["offset"] + 1 if assignments else 0
                            end = assignment_page["offset"] + len(assignments)
                            ui.label(render_message("webui.load_held_itemships.label.start_end_total_caa5dacc", start=start, end=end, total=assignment_page['total'])).classes(
                                "text-xs text-slate-500 grow"
                            )
                            previous_assignments = ui.button(icon="chevron_left").props("flat round dense")
                            next_assignments = ui.button(icon="chevron_right").props("flat round dense")
                            previous_assignments.set_enabled(assignment_page["offset"] > 0)
                            next_assignments.set_enabled(end < assignment_page["total"])

                            async def move_assignment_page(direction: int) -> None:
                                assignment_page["offset"] = max(
                                    0,
                                    assignment_page["offset"]
                                    + direction * assignment_page["limit"],
                                )
                                await load_held_itemships()

                            previous_assignments.on("click", lambda: move_assignment_page(-1))
                            next_assignments.on("click", lambda: move_assignment_page(1))
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)

        async def assign() -> None:
            counterpart_id = selection_holder["control"].value
            if counterpart_id is None:
                ui.notify(render_message("webui.assign.notify.select_a_counterpart_label_ba181b86", counterpart_label=localized_counterpart_label), color="warning")
                return
            payload = {
                "user_id": entity["id"] if for_user else int(counterpart_id),
                "role_id": int(counterpart_id) if for_user else entity["id"],
            }
            try:
                await api.create("user-role-assignments", payload)
                ui.notify(render_message("webui.assign.notify.capitalize_assigned_dd48342e", capitalize=localized_counterpart_label), color="positive")
                await load_held_itemships()
            except ApiError as error:
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
            assignments_area = ui.column().classes("w-full min-h-0 overflow-hidden")
            with ui.row().classes("w-full items-end gap-2"):
                selection_holder["control"] = relationship_select(
                    render_message(
                        "webui.show_memberships.select.counterpart",
                        counterpart=localized_counterpart_label,
                    ), {}
                ).classes("grow")
                bind_remote_relationship_select(
                    selection_holder["control"],
                    resource=counterpart_resource,
                    search_fields=("code", "name") if for_user else ("name", "email"),
                    label_fields=("code", "name") if for_user else ("name", "email"),
                    item_filter=lambda item: (
                        item.get("status") == "active"
                        and int(item["id"]) not in assigned_ids
                    ),
                )
                ui.button(
                    render_message("webui.show_memberships.button.browse_aed12689"), icon="account_tree",
                    on_click=lambda: show_organization_structure(
                        selection_mode="role" if for_user else "user",
                        target_control=selection_holder["control"],
                    ),
                ).props('outline no-caps color=primary aria-label=' + repr(render_message("webui.show_memberships.accessible_name.browse_organization_structure_0d480876"))).tooltip(
                    render_message("webui.show_memberships.tooltip.browse_and_select_a_counterpart_label_908694f6", counterpart_label=localized_counterpart_label)
                )
                assign_button = ui.button(render_message("webui.show_memberships.button.assign_e003b2ce"), on_click=assign, icon="person_add").props("unelevated")
                if not assignment_allowed:
                    selection_holder["control"].disable()
                    assign_button.disable()
            with ui.row().classes("w-full justify-end"):
                ui.button(render_message("webui.show_memberships.button.close_4c7a508f"), on_click=dialog.close).props("flat")
        dialog.open()
        await load_held_itemships()


    return show_memberships


def filter_membership_rows(
    rows: list[dict[str, Any]], *, query: str = "", status: str = "all",
    valid_from: str | None = None, valid_until: str | None = None,
) -> list[dict[str, Any]]:
    """Filter assignments by counterpart identity, status, and overlapping validity."""
    needle = query.strip().casefold()

    def date_part(value: Any) -> str | None:
        return str(value)[:10] if value else None

    def included(row: dict[str, Any]) -> bool:
        if needle and needle not in row.get("counterpart_search", "").casefold():
            return False
        if status != "all" and row.get("counterpart_status") != status:
            return False
        row_start = date_part(row.get("valid_from"))
        row_end = date_part(row.get("valid_until"))
        if valid_from and row_end and row_end < valid_from:
            return False
        if valid_until and row_start and row_start > valid_until:
            return False
        return True

    return [row for row in rows if included(row)]

