"""Shared collection presentation and existing table/card action dispatch."""
from __future__ import annotations
from typing import Any
from .organization_table import bind_organization_table_destinations
from .organization_collection_actions import build_change_suspension
from .organization_collection_actions import build_confirm_lifecycle
from .organization_collection_actions import build_issue_password
from .entity_editor_controls import entity_metadata_label
from .organization_table import organization_leading_actions
from .organization_table import organization_lifecycle_actions
from .organization_table import organization_membership_action
from .organization_table import organization_table_filters
from .organization_table import organization_user_actions
from .organization_table import organization_user_slots
from .classification_editor import render_classification_search_prompt
from .entities import COLLECTION_ENTITIES
from .i18n_catalogue import render_message
from nicegui import ui

def build_collection_table(
    *, RELATIONSHIP_DISPLAY_FIELDS, add_timestamp_slots, api, collection_state, current_session_revoked, decorate_for_spec, error_message, favourite_state, format_timestamp, guidance, load_recent, load_rows, open_editor, reload_favourites, render_administration_cards, render_entity_compact_results, render_recent_section, render_resource_personal_sections, required_principal, select_organization_unit_details, select_role_details, select_user_details, show_api_error, show_components, show_entity_history, show_memberships, show_profile_privilege_editor, show_record_details, subtitle, table_container, toggle_favourite,
):
    def render_table(spec: EntitySpec) -> None:
        if spec.key not in COLLECTION_ENTITIES:
            raise ValueError("Entity has no collection page")
        # Background personal-section refreshes do not inherit a NiceGUI slot.
        # Resolve translations in the owning page before updating its labels.
        with table_container:
            if spec.key in {"aggregations", "records"}:
                guidance.text = "" if collection_state["searched"] else render_message(
                    "webui.select_entity.text.large_collections_are_search_first_to_avoi_717a0f77"
                )
                subtitle.text = "" if collection_state["searched"] else render_message(
                    "webui.select_entity.text.search_required_before_loading_results_88549c49"
                )
        table_container.clear()
        with table_container:
            if spec.key in {"aggregations", "records"} and spec.search_first and not collection_state["searched"]:
                render_resource_personal_sections(spec)
                return
            if spec.search_first and not collection_state["searched"]:
                if spec.key == "classifications":
                    render_classification_search_prompt()
                    return
                render_recent_section(spec)
                return
            if spec.key in {"aggregations", "records"}:
                render_entity_compact_results(spec)
                render_resource_personal_sections(spec)
                return
            if spec.key == "aggregations":
                ui.separator().classes("erms-results-divider")
                with ui.row().classes("w-full items-center px-5 pt-2 gap-2"):
                    ui.icon("search", color="primary")
                    ui.label(render_message("webui.render_table.label.search_results_1bc0cdb3")).classes("text-lg font-semibold")
                    ui.badge(str(len(collection_state["rows"])), color="blue-grey").props("outline")
            lifecycle_filter = None
            account_type_filter = None
            administration_filter = None
            visible_rows = collection_state["rows"]
            result_filter = None
            if spec.key in {"security-levels", "profiles", "users", "roles", "org-units"}:
                render_governance_cards = render_administration_cards(spec)
                return
            if spec.key in {"aggregations", "records"}:
                with ui.row().classes("w-full items-center px-5 pt-2 gap-3"):
                    result_filter = ui.input(
                        render_message("webui.render_table.input.filter_displayed_results_126f56ec"),
                        placeholder=render_message("webui.render_table.input.type_to_filter_across_the_table_6a3e2810"),
                    ).props("outlined dense clearable debounce=250").classes("w-96 max-w-full")
                    ui.space()
                    ui.label(render_message("webui.render_table.label.visible_row_count_results_07a8f243", visible_row_count=len(visible_rows))).classes("text-sm text-slate-500")
            administration_filter, account_type_filter, lifecycle_filter = organization_table_filters(
                spec, lambda: collection_state.get("lifecycle_filter", "all"),
                lambda: collection_state.get("account_type_filter", "all"),
                lambda: collection_state.update(lifecycle_filter='all'),
            )
            sortable_relationships = {"parent_org_unit_display", "org_unit_display", "profile_display"}
            localized_metadata_fields = (
                {"name", "description"}
                if spec.key in {"org-units", "roles", "users", "security-levels"}
                else {"title", "description"}
                if spec.key == "classifications"
                else set()
            )
            for row in visible_rows:
                localized = row.get("localized") or {}
                for metadata_field in localized_metadata_fields:
                    row[f"_localized_{metadata_field}"] = (
                        localized.get(metadata_field) or row.get(metadata_field)
                    )
                for relationship_key in sortable_relationships:
                    relationship = row.get(relationship_key) or {}
                    row[f"_{relationship_key}_sort"] = " ".join(
                        str(relationship.get(part) or "") for part in ("name", "code")
                    ).strip().casefold()
            columns = [
                {
                    "name": key,
                    "label": entity_metadata_label(label),
                    "field": (
                        f"_{key}_sort" if key in sortable_relationships
                        else f"_localized_{key}" if key in localized_metadata_fields
                        else key
                    ),
                    "align": "left",
                    "sortable": (
                        key != "_avatar"
                        and (not key.endswith("_display") or key in sortable_relationships)
                    ),
                }
                for key, label in spec.columns
            ]
            columns.append({"name": "actions", "label": "", "field": "actions", "align": "right"})
            if spec.key == "profiles":
                profile_widths = {
                    "code": "width: 150px",
                    "name": "width: 230px",
                    "description": "width: auto",
                    "is_system": "width: 110px",
                    "actions": "width: 150px",
                }
                for column in columns:
                    column["style"] = profile_widths.get(column["name"], "")
                    column["headerStyle"] = profile_widths.get(column["name"], "")
            if spec.key in {"aggregations", "records"}:
                for row in visible_rows:
                    row["_is_favourite"] = favourite_state(spec.key, row["id"])
            table = ui.table(
                columns=columns,
                rows=visible_rows,
                row_key="id",
                pagination={"rowsPerPage": 25},
            ).props(
                'flat bordered separator=horizontal :rows-per-page-options="[10,25,50,100]"'
            ).classes(
                "erms-page-table erms-profiles-table"
                if spec.key == "profiles" else "erms-page-table"
            )
            if result_filter is not None:
                table.bind_filter_from(result_filter, "value")
            if administration_filter is not None:
                def searchable_text(value: Any) -> str:
                    if isinstance(value, dict):
                        return " ".join(searchable_text(item) for item in value.values())
                    if isinstance(value, (list, tuple)):
                        return " ".join(searchable_text(item) for item in value)
                    return "" if value is None else str(value)

                def apply_administration_filters() -> None:
                    collection_state["lifecycle_filter"] = lifecycle_filter.value
                    if account_type_filter is not None:
                        collection_state["account_type_filter"] = account_type_filter.value
                    query = (administration_filter.value or "").strip().casefold()
                    selected_status = lifecycle_filter.value
                    selected_account_type = (
                        account_type_filter.value if account_type_filter is not None else "all"
                    )
                    table.rows = [
                        row for row in collection_state["rows"]
                        if (
                            selected_status == "all"
                            or row.get("effective_status", row.get("status")) == selected_status
                        )
                        and (
                            selected_account_type == "all"
                            or row.get("account_type") == selected_account_type
                        )
                        and (
                            not query
                            or query in " ".join(
                                searchable_text(
                                    (row.get("localized") or {}).get(key) or row.get(key)
                                ).casefold()
                                for key, _ in spec.columns
                                if key != "_avatar"
                            )
                        )
                    ]
                    table.update()

                administration_filter.on_value_change(apply_administration_filters)
                lifecycle_filter.on_value_change(apply_administration_filters)
                if account_type_filter is not None:
                    account_type_filter.on_value_change(apply_administration_filters)
                apply_administration_filters()
            add_timestamp_slots(
                table, [key for key, _ in spec.columns if key.startswith("date_")]
            )
            organization_user_slots(spec, table)
            if spec.key == "profiles":
                table.add_slot("body-cell-name", '''
                    <q-td :props="props">
                      <div class="ellipsis">{{ props.value }}</div>
                      <q-tooltip>{{ props.value }}</q-tooltip>
                    </q-td>
                ''')
                table.add_slot("body-cell-description", '''
                    <q-td :props="props" class="profile-description-cell">
                      {{ props.value || '—' }}
                      <q-tooltip>{{ props.value || 'No description' }}</q-tooltip>
                    </q-td>
                ''')
                table.add_slot("body-cell-is_system", '''
                    <q-td :props="props">
                      <q-badge
                        :color="props.value ? 'blue-grey-7' : 'grey-5'"
                        :label="props.value ? 'Built-in' : 'Custom'"
                        outline
                      >
                        <q-tooltip>
                          {{ props.value
                            ? 'Supplied by Wathiq. It cannot be deleted and its code cannot be renamed.'
                            : 'Created by your organization.' }}
                        </q-tooltip>
                      </q-badge>
                    </q-td>
                ''')
            for key, _ in spec.columns:
                if not key.endswith("_display"):
                    continue
                if key == "type_display":
                    table.add_slot("body-cell-type_display", """
                        <q-td :props="props">
                          <div class="row items-center no-wrap q-gutter-sm">
                            <q-avatar size="30px" color="blue-1" text-color="primary" :icon="props.row.is_terminal ? 'label' : 'schema'" />
                            <span class="text-weight-medium">{{ props.row.is_terminal ? 'Terminal' : 'Branch' }}</span>
                          </div>
                        </q-td>
                    """)
                    continue
                if key not in RELATIONSHIP_DISPLAY_FIELDS:
                    continue
                relationship_icon = {
                    "parent_org_unit_display": "corporate_fare",
                    "org_unit_display": "corporate_fare",
                    "aggregation_display": "folder",
                    "scheme_display": "account_tree",
                    "profile_display": "admin_panel_settings",
                }.get(key, "link")
                relationship_template = """
                    <q-td :props="props">
                      <div v-if="props.row.__FIELD__" class="row items-center no-wrap q-gutter-sm">
                        <q-avatar size="30px" color="blue-1" text-color="primary" icon="__ICON__" />
                        <div class="column">
                          <span class="text-weight-medium relationship-cell-name">{{ props.row.__FIELD__.name }}</span>
                          <q-badge v-if="props.row.__FIELD__.code" outline color="primary" :label="props.row.__FIELD__.code" class="self-start" />
                        </div>
                      </div>
                      <span v-else class="text-grey-5">—</span>
                    </q-td>
                """.replace("__ICON__", relationship_icon).replace("__FIELD__", key)
                if key == "profile_display":
                    relationship_template = relationship_template.replace(
                        '<q-badge v-if="props.row.__FIELD__.code" outline color="primary" :label="props.row.__FIELD__.code" class="self-start" />'.replace("__FIELD__", key),
                        '<q-badge v-if="props.row.profile_display.code" outline :color="props.row.profile_display.code === \'ALL_PRIVS\' ? \'warning\' : \'primary\'" :label="props.row.profile_display.code === \'ALL_PRIVS\' ? \'Compatibility profile\' : props.row.profile_display.code" class="self-start"><q-tooltip v-if="props.row.profile_display.code === \'ALL_PRIVS\'">Review and replace with a purpose-specific profile</q-tooltip></q-badge>',
                    )
                table.add_slot(f"body-cell-{key}", relationship_template)
            if any(key == "effective_status" for key, _ in spec.columns):
                table.add_slot("body-cell-effective_status", '''
                    <q-td :props="props">
                      <q-badge
                        :color="props.value === 'active' ? 'positive' : (props.value === 'suspended' ? 'warning' : 'grey-7')"
                        :label="props.value"
                      ><q-tooltip>{{ props.row._inactive_reason }}</q-tooltip></q-badge>
                    </q-td>
                ''')
            if any(key == "status" for key, _ in spec.columns):
                table.add_slot("body-cell-status", '''
                    <q-td :props="props">
                      <q-badge
                        :color="props.value === 'active' ? 'positive' : (props.value === 'suspended' ? 'warning' : 'grey-7')"
                        :label="props.value"
                      />
                    </q-td>
                ''')
            if spec.key in {"records", "aggregations"}:
                buttons = '<q-btn flat round dense :icon="props.row._is_favourite ? \'favorite\' : \'favorite_border\'" :color="props.row._is_favourite ? \'red\' : \'primary\'" :aria-label="props.row._is_favourite ? \'Remove from favourites\' : \'Add to favourites\'" @click.stop="$parent.$emit(\'toggle_favourite\', props.row)"><q-tooltip>{{ props.row._is_favourite ? \'Remove from favourites\' : \'Add to favourites\' }}</q-tooltip></q-btn>'
            elif spec.key in {"privileges", "permissions"}:
                buttons = ''
            else:
                buttons = '<q-btn flat round dense icon="edit" color="primary" @click="$parent.$emit(\'edit\', props.row)"><q-tooltip>Edit</q-tooltip></q-btn>'
            buttons = organization_leading_actions(spec, buttons)
            if spec.key not in {"privileges", "permissions"}:
                buttons += '<q-btn flat round dense icon="history" color="blue-grey" @click="$parent.$emit(\'history\', props.row)"><q-tooltip>Event history</q-tooltip></q-btn>'
            if spec.key == "records":
                buttons = '<q-btn flat round dense icon="open_in_new" color="primary" @click="$parent.$emit(\'open_record\', props.row)"><q-tooltip>Open record</q-tooltip></q-btn>' + buttons
                buttons += '<q-btn flat round dense icon="attach_file" color="secondary" @click="$parent.$emit(\'components\', props.row)"><q-tooltip>Digital components</q-tooltip></q-btn>'
            buttons = organization_membership_action(spec, buttons)
            if spec.key == "profiles":
                buttons += '<q-btn flat round dense icon="key" color="secondary" @click="$parent.$emit(\'profile_privileges\', props.row)"><q-tooltip>Manage privileges</q-tooltip></q-btn>'
            buttons = organization_user_actions(spec, buttons)
            buttons = organization_lifecycle_actions(spec, buttons)
            table.add_slot("body-cell-actions", f'<q-td :props="props">{buttons}</q-td>')
            table.on("edit", lambda event: open_editor(event.args))
            table.on("history", lambda event, resource=spec.key: show_entity_history(resource, event.args))
            if spec.key == "profiles":
                table.on("profile_privileges", lambda event: show_profile_privilege_editor(event.args))
            bind_organization_table_destinations(spec, table, select_organization_unit_details, select_role_details)
            if spec.key in {"aggregations", "records"}:
                async def toggle_table_favourite(event) -> None:
                    row = event.args
                    selected = await toggle_favourite(spec.key, row["id"])
                    for table_row in table.rows:
                        if table_row["id"] == row["id"]:
                            table_row["_is_favourite"] = selected
                            break
                    table.update()
                    if spec.key in {"aggregations", "records"}:
                        await reload_favourites()
                        render_table(spec)
                table.on("toggle_favourite", toggle_table_favourite)
            if spec.key == "records":
                table.on("open_record", lambda event: show_record_details(event.args))
                table.on("components", lambda event: show_components(event.args))
            if spec.key in {"users", "roles"}:
                table.on(
                    "memberships",
                    lambda event, user_view=spec.key == "users": show_memberships(
                        event.args, for_user=user_view
                    ),
                )
            if spec.key == "users":
                table.on("open_user", lambda event: select_user_details(event.args["id"]))
                issue_password = build_issue_password(
                    api=api,
                    error_message=error_message,
                    format_timestamp=format_timestamp,
                )
                table.on("temporary_password", issue_password)
                change_suspension = build_change_suspension(
                    api=api,
                    current_session_revoked=current_session_revoked,
                    decorate_for_spec=decorate_for_spec,
                    get_principal=lambda: required_principal(),
                    get_rows=lambda: collection_state["rows"],
                    render_table=render_table,
                    set_rows=lambda rows: collection_state.update(rows=rows),
                    show_api_error=show_api_error,
                    spec=spec,
                )

                table.on("suspend_user", lambda event: change_suspension(event, suspended=True))
                table.on("unsuspend_user", lambda event: change_suspension(event, suspended=False))
            if spec.key in {"org-units", "roles", "users"}:
                confirm_lifecycle = build_confirm_lifecycle(
                    api=api,
                    current_session_revoked=current_session_revoked,
                    decorate_for_spec=decorate_for_spec,
                    get_principal=lambda: required_principal(),
                    get_rows=lambda: collection_state["rows"],
                    render_table=render_table,
                    set_rows=lambda rows: collection_state.update(rows=rows),
                    show_api_error=show_api_error,
                    spec=spec,
                )
                table.on("lifecycle", confirm_lifecycle)


    return render_table
