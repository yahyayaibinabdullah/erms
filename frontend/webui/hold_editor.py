"""Existing legal-hold behavior with explicit feature dependencies."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Any
from nicegui import background_tasks, ui
from .api_client import ApiError
from .i18n_catalogue import render_message, render_message_plain
from .holds_people import style_person_select


def build_hold_editor(
    *, api, bind_remote_people_select, select_hold_details, error_message,
):
    async def hold_reason_dialog(title_text: str, action_label: str, action: Any) -> None:
        dialog = ui.dialog()
        with dialog, ui.card().classes("w-[520px] max-w-full"):
            ui.label(title_text).classes("text-xl font-semibold")
            reason = ui.textarea(render_message("webui.hold_reason_dialog.textarea.reason_c483e491"), validation={render_message_plain("webui.submit.notify.a_reason_is_required_2d25211d"): lambda value: bool((value or "").strip())}).props("outlined autogrow maxlength=2000").classes("w-full")

            async def submit() -> None:
                if not (reason.value or "").strip():
                    ui.notify(render_message("webui.submit.notify.a_reason_is_required_2d25211d"), color="warning"); return
                try:
                    result = action(reason.value.strip())
                    if asyncio.iscoroutine(result): await result
                    dialog.close()
                except ApiError as error:
                    ui.notify(error_message(error), color="negative", close_button=True)

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.hold_reason_dialog.button.cancel_c97ff9b9"), on_click=dialog.close).props("flat no-caps")
                ui.button(action_label, icon="check", on_click=submit).props("unelevated no-caps")
        dialog.open()


    async def open_hold_editor(hold: dict[str, Any] | None = None) -> None:
        editing = hold is not None
        def person_label(person: dict[str, Any]) -> str:
            return (
                f"{(person.get('localized') or {}).get('name') or person['name']} — "
                f"{person.get('email') or render_message('webui.select_user_details.label.no_email_address_1d665180')}"
            )

        known_people = {
            int(person["id"]): person_label(person)
            for person in ([hold["owner"]] + list(hold.get("contributors", [])) if hold else [])
        }
        def local_datetime_value(value: str | None) -> str:
            if not value:
                return ""
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%Y-%m-%dT%H:%M")
        initial_valid_from = local_datetime_value((hold or {}).get("valid_from"))
        initial_valid_to = local_datetime_value((hold or {}).get("valid_to"))
        dialog = ui.dialog()
        with dialog, ui.card().classes("w-[760px] max-w-[95vw] max-h-[90vh] overflow-y-auto"):
            ui.label(render_message("webui.open_hold_editor.label.edit_hold_246b8e35") if editing else render_message("webui.open_hold_editor.label.create_hold_7f858468")).classes("text-xl font-semibold")
            with ui.grid(columns=2).classes("w-full gap-3"):
                code = ui.input(render_message("webui.open_hold_editor.input.code_e91b9355"), value=(hold or {}).get("code", "")).props("outlined maxlength=100").classes("w-full")
                name = ui.input(render_message("webui.open_hold_editor.input.name_fc2e95e9"), value=(hold or {}).get("name", "")).props("outlined maxlength=300").classes("w-full")
                valid_from = ui.input(render_message("webui.open_hold_editor.input.valid_from_5618bb9a"), value=initial_valid_from).props("outlined type=datetime-local").classes("w-full")
                valid_to = ui.input(render_message("webui.open_hold_editor.input.valid_to_exclusive_ac7e61ca"), value=initial_valid_to).props("outlined type=datetime-local").classes("w-full")
            owner = ui.select(
                dict(known_people), value=(hold or {}).get("owner_user_id"), label=render_message("webui.open_hold_editor.select.owner_2084c633"), with_input=True,
            ).props("outlined use-input").classes("w-full")
            style_person_select(owner)
            contributors = ui.select(
                {key: value for key, value in known_people.items() if key != owner.value},
                value=[item["id"] for item in (hold or {}).get("contributors", [])],
                multiple=True, label=render_message("webui.open_hold_editor.select.contributors_38f1f3e5"), with_input=True,
            ).props("outlined use-chips use-input").classes("w-full")
            style_person_select(contributors, multiple=True)
            load_owner_options = bind_remote_people_select(owner)
            load_contributor_options = bind_remote_people_select(
                contributors,
                excluded_ids=lambda: ({int(owner.value)} if owner.value is not None else set()),
            )
            description = ui.textarea(render_message("webui.open_hold_editor.textarea.description_930a66c1"), value=(hold or {}).get("description") or "").props("outlined autogrow maxlength=4000").classes("w-full")
            preserve = ui.checkbox(render_message("webui.open_hold_editor.checkbox.preserve_resource_metadata_and_state_8a5875d3"), value=(hold or {}).get("preserve_resource_state", False))
            ui.label(render_message("webui.open_hold_editor.label.valid_to_is_exclusive_dates_currently_use_b0942828")).classes("text-xs text-slate-500")

            def iso_value(value: str, *, required: bool) -> str | None:
                if not value:
                    if required: raise ValueError("Valid from is required")
                    return None
                # A datetime-local value has no offset. Until per-user timezone
                # preferences exist, interpret it in the application timezone.
                parsed = datetime.fromisoformat(value)
                local_timezone = datetime.now().astimezone().tzinfo
                return parsed.replace(tzinfo=local_timezone).astimezone(timezone.utc).isoformat()

            async def persist(reason: str | None = None) -> None:
                if not (code.value or "").strip() or not (name.value or "").strip() or owner.value is None:
                    ui.notify(render_message("webui.persist.notify.code_name_owner_and_valid_from_are_require_c60f7fcf"), color="warning"); return
                try:
                    owner_id = int(owner.value)
                    payload = {"code": code.value.strip(), "name": name.value.strip(), "description": (description.value or "").strip() or None,
                               "valid_from": iso_value(valid_from.value, required=True), "valid_to": iso_value(valid_to.value, required=False),
                               "owner_user_id": owner_id, "preserve_resource_state": bool(preserve.value)}
                    contributor_ids = [int(value) for value in (contributors.value or []) if int(value) != owner_id]
                    if not editing:
                        payload["contributor_user_ids"] = contributor_ids
                    saved = await (api.update_hold(hold["id"], hold["version"], payload, reason or "") if editing else api.create_hold(payload))
                    if editing and contributor_ids != [item["id"] for item in hold.get("contributors", [])]:
                        saved = await api.replace_hold_contributors(
                            hold["id"], saved["version"], contributor_ids, reason or "",
                        )
                    dialog.close(); ui.notify(render_message("webui.persist.notify.hold_updated_c8aae53f") if editing else render_message("webui.persist.notify.hold_created_7d49d8f4"), color="positive")
                    await select_hold_details(saved["id"])
                except (ApiError, ValueError) as error:
                    ui.notify(error_message(error) if isinstance(error, ApiError) else str(error), color="negative", close_button=True)

            async def save() -> None:
                if editing:
                    await hold_reason_dialog(
                        render_message("webui.hold_reason_dialog.update_title"),
                        render_message("webui.hold_reason_dialog.update_action"),
                        persist,
                    )
                else:
                    await persist()
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button(render_message("webui.open_hold_editor.button.cancel_9df95680"), on_click=dialog.close).props("flat no-caps")
                ui.button(render_message("webui.open_hold_editor.button.save_hold_c7de035c"), icon="save", on_click=save).props("unelevated no-caps")

            def filter_owner_from_contributors() -> None:
                contributors.options = {
                    key: value for key, value in dict(contributors.options).items()
                    if key != owner.value
                }
                contributors.value = [
                    value for value in (contributors.value or [])
                    if value != owner.value
                ]
                contributors.update()
                background_tasks.create(load_contributor_options())

            owner.on_value_change(filter_owner_from_contributors)
        dialog.open()


    return hold_reason_dialog, open_hold_editor
