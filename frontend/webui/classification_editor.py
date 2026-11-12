"""Classification-specific rules and adapters used by the shared entity controls."""
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
