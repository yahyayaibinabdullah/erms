"""Retained organization table presentation, filters and action bindings."""
from __future__ import annotations
from nicegui import ui
from .i18n_catalogue import render_message


LIFECYCLE_ACTION_BUTTONS = (
    '<q-btn v-if="props.row.status === \'inactive\'" flat round dense '
    'icon="toggle_on" color="positive" aria-label="Activate" '
    '@click="$parent.$emit(\'lifecycle\', props.row)">'
    '<q-tooltip>Activate</q-tooltip></q-btn>'
    '<q-btn v-else flat round dense icon="toggle_off" color="negative" '
    'aria-label="Deactivate" @click="$parent.$emit(\'lifecycle\', props.row)">'
    '<q-tooltip>Deactivate</q-tooltip></q-btn>'
)


USER_SUSPENSION_ACTION_BUTTONS = (
    '<q-btn v-if="props.row.status !== \'suspended\'" flat round dense '
    'icon="pause_circle" color="warning" '
    ':disable="props.row.status !== \'active\'" '
    ':aria-label="props.row.status === \'active\' ? \'Suspend\' : \'Suspend unavailable while inactive\'" '
    '@click="$parent.$emit(\'suspend_user\', props.row)">'
    '<q-tooltip>{{ props.row.status === \'active\' ? \'Suspend\' : '
    "'Activate the user before suspending' }}</q-tooltip></q-btn>"
    '<q-btn v-else flat round dense icon="play_circle" color="positive" '
    'aria-label="Unsuspend" @click="$parent.$emit(\'unsuspend_user\', props.row)">'
    '<q-tooltip>Unsuspend</q-tooltip></q-btn>'
)


def organization_table_filters(spec, get_lifecycle_filter, get_account_type_filter, reset_lifecycle_filter):
    administration_filter = account_type_filter = lifecycle_filter = None
    if spec.key in {"org-units", "roles", "users"}:
        status_options = {
            "all": render_message("webui.render_table.text.all_statuses_06d8caa8"),
            "active": render_message("webui.render_table.text.active_3a692d6a"),
            "inactive": render_message("webui.render_table.text.inactive_ffa76f23"),
        }
        if spec.key == "users":
            status_options["suspended"] = "Suspended"
        filter_labels = {
            "org-units": "Search code, name, or parent unit",
            "roles": "Search code, name, or organization unit",
            "users": "Search name or email",
        }
        selected_lifecycle_filter = get_lifecycle_filter()
        if selected_lifecycle_filter not in status_options:
            selected_lifecycle_filter = "all"
            reset_lifecycle_filter()
        with ui.row().classes(
            "w-full items-center gap-3 px-5 pt-2 pb-1 mb-2"
        ):
            administration_filter = ui.input(
                filter_labels[spec.key],
                placeholder=render_message("webui.render_table.input.type_to_filter_this_table_c56c09a2"),
            ).props("outlined dense clearable debounce=250").classes("w-96 max-w-full")
            ui.space()
            if spec.key == "users":
                account_type_filter = ui.select(
                    {"all": render_message("webui.render_table.select.all_account_types_4efb11a2"), "person": render_message("webui.render_table.select.person_71413829"), "service": render_message("webui.render_table.select.service_e1263edf")},
                    value=get_account_type_filter(),
                    label=render_message("webui.render_table.select.account_type_1e818a83"),
                ).props("outlined dense options-dense").classes("w-48")
            lifecycle_filter = ui.select(
                status_options,
                value=selected_lifecycle_filter,
                label=render_message("webui.render_table.select.status_bba3b0bf"),
            ).props("outlined dense options-dense").classes("w-48")
    return administration_filter, account_type_filter, lifecycle_filter


def organization_user_slots(spec, table):
    if spec.key == "users":
        table.add_slot("body-cell-_avatar", '''
            <q-td :props="props" style="width: 56px">
              <q-avatar size="38px" :style="{ backgroundColor: props.row._avatar.color, color: props.row._avatar.text_color }">
                {{ props.row._avatar.initials }}
              </q-avatar>
            </q-td>
        ''')
        table.add_slot("body-cell-account_type", '''
            <q-td :props="props">
              <span>{{ props.value === 'person' ? 'Person' : 'Service' }}</span>
            </q-td>
        ''')


def organization_leading_actions(spec, buttons):
    if spec.key == "org-units":
        buttons = '<q-btn flat round dense icon="open_in_new" color="primary" @click="$parent.$emit(\'open_org_unit\', props.row)"><q-tooltip>Open organization unit</q-tooltip></q-btn>' + buttons
    if spec.key == "roles":
        buttons = '<q-btn flat round dense icon="open_in_new" color="primary" @click="$parent.$emit(\'open_role\', props.row)"><q-tooltip>Open role</q-tooltip></q-btn>' + buttons
    return buttons


def organization_membership_action(spec, buttons):
    if spec.key in {"users", "roles"}:
        buttons += '<q-btn flat round dense icon="group" color="secondary" @click="$parent.$emit(\'memberships\', props.row)"><q-tooltip>Role assignments</q-tooltip></q-btn>'
    return buttons


def organization_user_actions(spec, buttons):
    if spec.key == "users":
        buttons = '<q-btn flat round dense icon="open_in_new" color="primary" @click="$parent.$emit(\'open_user\', props.row)"><q-tooltip>Open user</q-tooltip></q-btn>' + buttons
        buttons += '<q-btn flat round dense icon="password" color="orange" @click="$parent.$emit(\'temporary_password\', props.row)"><q-tooltip>Issue temporary password</q-tooltip></q-btn>'
    return buttons


def organization_lifecycle_actions(spec, buttons):
    if spec.key in {"org-units", "roles", "users"}:
        buttons += LIFECYCLE_ACTION_BUTTONS
    if spec.key == "users":
        buttons += USER_SUSPENSION_ACTION_BUTTONS
    return buttons


def bind_organization_table_destinations(spec, table, select_organization_unit_details, select_role_details):
    if spec.key == "org-units":
        table.on("open_org_unit", lambda event: select_organization_unit_details(event.args["id"]))
    if spec.key == "roles":
        table.on("open_role", lambda event: select_role_details(event.args["id"]))
