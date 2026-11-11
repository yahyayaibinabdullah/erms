"""Classification-specific rules and adapters used by the shared entity controls."""
from typing import Any
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message


RETENTION_FIELDS = {
    "current_period_years", "intermediate_period_years", "final_disposition", "instructions",
}


async def load_direct_retention(api, row):
    try:
        return await api.classification_retention_rule(row["id"])
    except ApiError as error:
        if error.status_code != 404:
            raise
    return None


def retention_editor_source(field, row, retention_rule):
    return retention_rule if field.name in RETENTION_FIELDS else row


def configure_scheme_field(field, control, *, creating):
    if field.name == "date_published" and not creating:
        control.disable()
        ui.label(
            render_message("webui.open_editor.label.use_the_publish_or_unpublish_action_to_cha_004f776d")
        ).classes("text-xs text-slate-500 -mt-2")


def prepare_retention_payload(payload, *, creating):
    rule_payload = None
    rule_values = {
        key: payload.pop(key, None) for key in (
            "current_period_years", "intermediate_period_years",
            "final_disposition", "instructions",
        )
    }
    if any(value not in (None, "") for value in rule_values.values()):
        required = ("current_period_years", "intermediate_period_years", "final_disposition")
        if any(rule_values[key] in (None, "") for key in required):
            raise ValueError("A direct retention rule requires both periods and a final disposition")
        rule_payload = rule_values
        if creating:
            payload["retention_rule"] = rule_payload
    if not creating:
        payload.pop("classification_scheme_id", None)

    return rule_payload


async def decorate_classifications(rows, *, rows_by_id, relationship_cell):
    schemes_by_id = await rows_by_id(
        "classification-schemes",
        {item.get("classification_scheme_id") for item in rows},
    )
    return [{
        **item,
        "type_display": {
            "name": "Terminal" if item.get("is_terminal") else "Branch",
            "code": "Assignable" if item.get("is_terminal") else "Hierarchy",
        },
        "scheme_display": relationship_cell(
            schemes_by_id.get(item.get("classification_scheme_id"))
        ),
    } for item in rows]



def render_classification_search_prompt():
    with ui.column().classes("w-full items-center py-12 gap-2 text-slate-500"):
        ui.icon("manage_search", size="42px").classes("text-primary")
        ui.label(
            render_message("webui.render_table.label.search_classifications_by_code_title_descr_30044cab")
        ).classes("font-medium")
        ui.label(render_message("webui.render_table.label.partial_matching_is_automatic_wildcard_cha_6cff96d6")).classes("text-xs")



def scheme_action_buttons(buttons):
    buttons += '<q-btn v-if="!props.row.date_published" flat round dense icon="publish" color="primary" @click="$parent.$emit(\'publish_scheme\', props.row)"><q-tooltip>Publish now</q-tooltip></q-btn>'
    buttons += '<q-btn flat round dense :icon="props.row.date_deactivated ? \'toggle_on\' : \'toggle_off\'" :color="props.row.date_deactivated ? \'positive\' : \'negative\'" @click="$parent.$emit(\'scheme_lifecycle\', props.row)"><q-tooltip>{{ props.row.date_deactivated ? \'Reactivate\' : \'Deactivate\' }}</q-tooltip></q-btn>'

    return buttons


def bind_scheme_actions(table, *, api, refresh, error_message):
    async def publish_scheme(event) -> None:
        row = event.args
        try:
            await api.request(
                "POST", f"/api/v1/classification-schemes/{row['id']}/publish",
                headers={"If-Match": str(row["version"])},
            )
            ui.notify(render_message("webui.publish_scheme.notify.classification_scheme_published_cd141332"), color="positive")
            await refresh()
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
    async def change_scheme_lifecycle(event) -> None:
        row = event.args
        action = render_message("webui.change_scheme_lifecycle.text.reactivate_ef9784c4") if row.get("date_deactivated") else render_message("webui.change_scheme_lifecycle.text.deactivate_871a64d1")
        try:
            await api.request(
                "POST", f"/api/v1/classification-schemes/{row['id']}/{action}",
                headers={
                    "If-Match": str(row["version"]),
                    "X-Change-Reason": f"{action.title()} from classification administration",
                },
            )
            ui.notify(render_message("webui.change_scheme_lifecycle.notify.classification_scheme_action_d_18fb0eda", action=action), color="positive")
            await refresh()
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
    table.on("publish_scheme", publish_scheme)
    table.on("scheme_lifecycle", change_scheme_lifecycle)

