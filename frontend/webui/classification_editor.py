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
