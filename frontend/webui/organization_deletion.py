"""Existing organization deletion view with explicit per-client dependencies."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from typing import Callable
import inspect
from .i18n_catalogue import render_message
from nicegui import ui


def build_organization_deletion(
    *, api, deletion_blocked_report, deletion_identity, error_message, show_api_error,
):
    async def confirm_identity_deletion(
        resource: str, item: dict[str, Any], *, label: str, on_deleted: Callable[[], Any],
    ) -> None:
        """Explain the server's deletion analysis and require a reason."""
        try:
            report = await api.deletion_preflight(resource, item["id"])
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return
        dialog = ui.dialog().props("persistent")
        with dialog, ui.card().classes("w-[620px] max-w-full gap-4 p-5"):
            ui.label(render_message("webui.confirm_identity_deletion.label.permanently_delete_label_421a1183", label=label)).classes("text-xl font-semibold")
            ui.label(deletion_identity(item)).classes("font-medium")
            if report["blockers"]:
                ui.label(render_message("webui.confirm_identity_deletion.label.deletion_is_currently_blocked_f60d1f75")).classes("text-negative font-semibold")
                for blocker in report["blockers"]:
                    with ui.row().classes("items-start gap-2"):
                        ui.icon("block", color="negative").classes("mt-0.5")
                        with ui.column().classes("gap-0 grow"):
                            ui.label(blocker["message"]).classes("text-sm")
                            details = blocker.get("details") or {}
                            if details:
                                ui.label(" · ".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in details.items())).classes("text-xs text-slate-500")
                ui.label(render_message("webui.confirm_identity_deletion.label.resolve_every_blocker_and_run_the_prefligh_4fcfa2c6")).classes("text-xs text-slate-500")
                ui.button(render_message("webui.confirm_identity_deletion.button.close_ef4c48d5"), on_click=dialog.close).props("flat no-caps").classes("self-end")
            else:
                cascades = {key: value for key, value in report.get("cascades", {}).items() if value}
                ui.label(render_message("webui.confirm_identity_deletion.label.the_live_entity_cannot_be_restored_immutab_9045451d")).classes("text-sm text-slate-600")
                if cascades:
                    ui.label(render_message("webui.confirm_identity_deletion.label.data_removed_automatically_590a2b44")).classes("text-sm font-semibold")
                    ui.label(" · ".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in cascades.items())).classes("text-sm text-slate-600")
                reason = ui.textarea(render_message("webui.confirm_identity_deletion.textarea.reason_for_permanent_deletion_4d209619")).props("outlined autogrow counter maxlength=2000").classes("w-full")

                async def remove() -> None:
                    change_reason = (reason.value or "").strip()
                    if not change_reason:
                        ui.notify(render_message("webui.remove.notify.a_deletion_reason_is_required_21f0a705"), color="warning")
                        return
                    try:
                        await api.delete(resource, item["id"], report["entity_version"], reason=change_reason)
                    except ApiError as error:
                        dialog.close()
                        if deletion_blocked_report(error) is not None:
                            await confirm_identity_deletion(
                                resource, item, label=label, on_deleted=on_deleted,
                            )
                        else:
                            show_api_error(error)
                        return
                    dialog.close()
                    ui.notify(render_message("webui.remove.notify.title_permanently_deleted_d3785d76", title=label.title()), color="positive")
                    result = on_deleted()
                    if inspect.isawaitable(result):
                        await result

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.confirm_identity_deletion.button.cancel_a7ad1d30"), on_click=dialog.close).props("flat no-caps")
                    ui.button(render_message("webui.confirm_identity_deletion.button.delete_permanently_3b2f8fa1"), icon="delete_forever", color="negative", on_click=remove).props("unelevated no-caps")
        dialog.open()


    return confirm_identity_deletion


def deletion_identity(item: dict[str, Any]) -> str:
    """Identify a deletion target by its display name and stable identifier."""
    name = str(item.get("name") or "").strip()
    stable_identifier = str(item.get("email") or item.get("code") or "").strip()
    if name and stable_identifier and stable_identifier != name:
        return f"{name} — {stable_identifier}"
    return name or stable_identifier or f"Item #{item['id']}"


def deletion_blocked_report(error: ApiError) -> dict[str, Any] | None:
    """Extract the server's authoritative deletion report from a race conflict."""
    if (
        error.status_code == 409
        and isinstance(error.detail, dict)
        and error.detail.get("code") == "deletion_blocked"
    ):
        return error.detail
    return None

