"""Existing text-indexer-details UI with explicit shell and destination callbacks.

List filters, diagnostics, credential paging and dialogs remain local to each
opened view. No shared application-state dictionary, route or cache is added.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message, render_message_plain
from .text_indexer_credentials import reveal_text_indexer_key


def build_text_indexer_details(
    *, register_navigation, show_authenticated_view, search_bar, aggregation_mode_bar, add_button, add_record_button, guidance, title, subtitle, table_container, api, error_message, show_api_error, format_timestamp, localized_lifecycle_value, direction, enter, select_text_indexers, breadcrumb_back,
):
    async def select_text_indexer_details(user_id: int) -> None:
        register_navigation("text-indexer-details", f"Text indexer #{user_id}", entity_id=user_id)
        show_authenticated_view()
        enter()
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        table_container.clear()
        try:
            indexer, credential_page = await asyncio.gather(
                api.text_indexer(user_id),
                api.text_indexer_credentials(user_id, history="all", limit=5, offset=0),
            )
        except ApiError as error:
            ui.notify(error_message(error), color="negative", close_button=True)
            return
        title.text = indexer["name"]
        subtitle.text = render_message("webui.select_text_indexer_details.text.text_indexer_identity_and_credential_admin_49259f0e")
        register_navigation(
            "text-indexer-details", indexer["name"], entity_id=user_id,
            accessible_label=f"{indexer['name']} — {indexer['external_id']}",
        )

        async def change_status(action: str) -> None:
            try:
                await api.set_text_indexer_status(user_id, indexer["version"], action)
            except ApiError as error:
                show_api_error(error)
                return
            ui.notify(render_message("webui.change_status.notify.text_indexer_status_updated_d7cf4113"), color="positive")
            await select_text_indexer_details(user_id)

        def credential_dialog(existing: dict[str, Any] | None = None) -> None:
            dialog = ui.dialog().props("persistent")
            with dialog, ui.card().classes("w-[540px] max-w-full gap-3"):
                ui.label(render_message("webui.credential_dialog.label.rotate_api_key_dc0e85ed") if existing else render_message("webui.credential_dialog.label.generate_api_key_e9cdd1d3")).classes(
                    "text-xl font-semibold"
                )
                name = ui.input(
                    render_message("webui.credential_dialog.input.credential_name_b670464d"), value=(existing or {}).get("name", ""),
                ).props("outlined").classes("w-full")
                expiry = ui.input(
                    render_message("webui.credential_dialog.input.expiry_iso_8601_222d3b9f"),
                    value=(datetime.now(timezone.utc) + timedelta(days=90)).replace(
                        microsecond=0
                    ).isoformat(),
                ).props("outlined").classes("w-full")
                ui.input(render_message("webui.credential_dialog.input.allowed_route_d805736a"), value=render_message("webui.select_text_indexer_details.label.internal_text_indexing_api_only_ec49ffe0")).props(
                    "outlined readonly"
                ).classes("w-full")
                overlap = None
                if existing:
                    overlap = ui.input(
                        render_message("webui.credential_dialog.input.old_key_overlap_until_optional_maximum_7_d_eec9eb31")
                    ).props("outlined clearable").classes("w-full")

                async def submit() -> None:
                    payload = {
                        "name": (name.value or "").strip(),
                        "expires_at": (expiry.value or "").strip(),
                    }
                    if existing and overlap and overlap.value:
                        payload["overlap_until"] = overlap.value.strip()
                    try:
                        result = (
                            await api.rotate_text_indexer_credential(
                                user_id, existing["id"], payload,
                            ) if existing else
                            await api.create_text_indexer_credential(user_id, payload)
                        )
                    except ApiError as error:
                        show_api_error(error)
                        return
                    dialog.close()
                    reveal_text_indexer_key(
                        result, lambda: select_text_indexer_details(user_id),
                    )

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.credential_dialog.button.cancel_f4440fc5"), on_click=dialog.close).props("flat no-caps")
                    ui.button(
                        render_message("webui.credential_dialog.button.rotate_key_abe27125") if existing else render_message("webui.credential_dialog.button.generate_api_key_f5d573fe"),
                        icon="key", on_click=submit,
                    ).props("unelevated no-caps")
            dialog.open()

        def confirm_revoke(credential: dict[str, Any]) -> None:
            dialog = ui.dialog()
            with dialog, ui.card().classes("w-[520px] max-w-full gap-3"):
                ui.label(render_message("webui.confirm_revoke.label.revoke_api_key_6e1e1bba")).classes("text-xl font-semibold")
                ui.label(
                    render_message("webui.confirm_revoke.label.revoke_name_credential_identifier_25883f9b", name=credential['name'], credential_identifier=credential['credential_identifier'])
                ).classes("font-medium")
                ui.label(
                    render_message("webui.confirm_revoke.label.affected_indexers_fail_on_their_next_reque_4add025b")
                ).classes("text-sm text-slate-600")

                async def revoke() -> None:
                    try:
                        await api.revoke_text_indexer_credential(user_id, credential["id"])
                    except ApiError as error:
                        show_api_error(error)
                        return
                    dialog.close()
                    ui.notify(render_message("webui.revoke.notify.api_key_revoked_0fb47669"), color="positive")
                    await select_text_indexer_details(user_id)

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.confirm_revoke.button.cancel_9fc0545b"), on_click=dialog.close).props("flat no-caps")
                    ui.button(render_message("webui.confirm_revoke.button.revoke_f9d8c510"), icon="block", color="negative", on_click=revoke).props(
                        "unelevated no-caps"
                    )
            dialog.open()

        with table_container, ui.column().classes("w-full p-5 gap-4"):
            with ui.card().classes("detail-surface shadow-none p-5 w-full"):
                with ui.row().classes("w-full items-start gap-3"):
                    with ui.element("div").classes("governance-card-icon"):
                        ui.icon("manage_search", size="22px")
                    with ui.column().classes("gap-0 grow"):
                        ui.label(indexer["name"]).classes("text-xl font-semibold")
                        ui.label(indexer["external_id"]).classes(
                            "text-sm text-slate-500 font-mono"
                        )
                        with ui.row().classes("items-center gap-2 mt-1"):
                            ui.badge(render_message("webui.select_text_indexer_details.badge.service_account_8d16f547"), color="primary").props("outline")
                            ui.badge(render_message("webui.select_text_indexer_details.badge.non_interactive_b952cd7b"), color="blue-grey").props("outline")
                            ui.badge(render_message("webui.select_text_indexer_details.badge.text_indexer_service_b73b4bdf"), color="indigo").props("outline")
                    ui.badge(
                        localized_lifecycle_value(indexer["status"]),
                        color={"active": "positive", "suspended": "warning"}.get(
                            indexer["status"], "grey-7"
                        ),
                    )
                with ui.grid(columns=3).classes("w-full gap-4 mt-3"):
                    for label, value in (
                        (render_message("webui.text_indexer_details.external_id"), indexer["external_id"]),
                        (render_message("webui.text_indexer_details.created"), format_timestamp(indexer["date_created"])),
                        (render_message("webui.text_indexer_card.last_used"), format_timestamp(indexer["last_used_at"]) if indexer.get("last_used_at") else render_message("webui.text_indexer_card.never")),
                    ):
                        with ui.column().classes("gap-1 border-b border-slate-100 pb-1.5"):
                            ui.label(label).classes("detail-field-label")
                            ui.label(value).classes("font-medium break-all")
                with ui.row().classes("w-full justify-between gap-2 flex-wrap mt-2"):
                    ui.button(
                        render_message("webui.select_text_indexer_details.button.back_to_text_indexers_34b66935"), icon="arrow_forward" if direction() == "rtl" else "arrow_back",
                        on_click=lambda: breadcrumb_back(select_text_indexers),
                    ).props("flat no-caps")
                    with ui.row().classes("detail-action-row gap-2"):
                        if indexer["status"] == "active":
                            ui.button(
                                render_message("webui.select_text_indexer_details.button.suspend_7f5e5b10"), icon="pause_circle", on_click=lambda: change_status("suspend"),
                            ).props("outline no-caps color=warning")
                        elif indexer["status"] == "suspended":
                            ui.button(
                                render_message("webui.select_text_indexer_details.button.activate_b44c7d38"), icon="play_circle", on_click=lambda: change_status("unsuspend"),
                            ).props("outline no-caps color=positive")

            with ui.row().classes("w-full items-center"):
                with ui.column().classes("gap-0 grow"):
                    ui.label(render_message("webui.select_text_indexer_details.label.api_credentials_66a20b8e")).classes("text-lg font-semibold")
                    ui.label(render_message("webui.select_text_indexer_details.label.internal_text_indexing_api_only_ec49ffe0")).classes("text-sm text-slate-500")
                generate = ui.button(
                    render_message("webui.select_text_indexer_details.button.generate_api_key_35bdc780"), icon="add", on_click=credential_dialog,
                ).props("unelevated no-caps")
                if indexer["status"] != "active":
                    generate.disable()
                    generate.tooltip(render_message("webui.select_text_indexer_details.tooltip.activate_this_text_indexer_before_generati_e7f349b2"))
            credential_state = {"history": "all", "offset": 0, "page": credential_page}
            with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                credential_filter = ui.select(
                    {"all": render_message("webui.select_text_indexer_details.select.all_credentials_8052bb35"), "usable": render_message("webui.select_text_indexer_details.select.usable_77e6a90f"), "history": render_message("webui.select_text_indexer_details.select.revoked_or_expired_2c5b4c9f")},
                    value="all", label=render_message("webui.select_text_indexer_details.select.show_c803b7ac"),
                ).props("outlined dense options-dense").classes("w-52")
                ui.label(
                    render_message("webui.select_text_indexer_details.label.revoked_and_expired_credentials_are_retain_1b39ddda", retention_days=credential_page['retention_days'])
                ).classes("text-xs text-slate-500 grow")
            credential_results = ui.column().classes("w-full gap-3")
            with ui.row().classes("w-full items-center justify-between gap-2"):
                credential_summary = ui.label().classes("text-sm text-slate-500")
                with ui.row().classes("gap-2"):
                    credential_previous = ui.button(render_message("webui.select_text_indexer_details.button.previous_86972be8"), icon="chevron_right" if direction() == "rtl" else "chevron_left").props("outline dense no-caps")
                    credential_next = ui.button(render_message("webui.select_text_indexer_details.button.next_e284c9ef"), icon="chevron_left" if direction() == "rtl" else "chevron_right").props("outline dense no-caps icon-right")

            def render_credentials() -> None:
                page = credential_state["page"]
                items = page["items"]
                credential_results.clear()
                with credential_results:
                    if not items:
                        with ui.card().classes("governance-empty-state shadow-none"):
                            ui.icon("key_off", size="34px").classes("text-slate-300")
                            ui.label(render_message("webui.render_credentials.label.no_matching_api_credentials_b2735a7d")).classes("font-semibold")
                    for credential in items:
                        with ui.card().classes("governance-list-card shadow-none"):
                            with ui.row().classes("w-full items-start gap-3 no-wrap"):
                                with ui.element("div").classes("governance-card-icon"):
                                    ui.icon("key", size="20px")
                                with ui.column().classes("gap-0 grow min-w-0"):
                                    ui.label(credential["name"]).classes("font-semibold")
                                    ui.label(
                                        render_message("webui.render_credentials.label.id_wti_credential_identifier_internal_text_b0627629", credential_identifier=credential['credential_identifier'])
                                    ).classes("text-xs text-slate-500 break-all")
                                ui.badge(
                                    (render_message("webui.text_indexer_details.expiring") if credential["status"] == "expiring" else localized_lifecycle_value(credential["status"])),
                                    color={"active": "positive", "expiring": "warning", "expired": "grey-7", "revoked": "negative"}.get(
                                        credential["status"], "grey-7"
                                    ),
                                ).props("outline")
                            with ui.element("div").classes("governance-list-facts"):
                                for label, value in (
                                    (render_message("webui.text_indexer_details.created"), format_timestamp(credential["date_created"])),
                                    (render_message("webui.text_indexer_details.expires"), format_timestamp(credential["expires_at"])),
                                    (render_message("webui.text_indexer_card.last_used"), format_timestamp(credential["last_used_at"]) if credential.get("last_used_at") else render_message("webui.text_indexer_card.never")),
                                    (render_message("webui.text_indexer_details.created_by"), credential.get("created_by_name") or render_message("webui.text_indexer_details.system")),
                                    (render_message("webui.text_indexer_details.last_worker"), credential.get("last_worker_id") or "—"),
                                ):
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(label).classes("detail-field-label")
                                        ui.label(value).classes("text-sm break-all")
                            if credential["status"] == "active":
                                with ui.row().classes("detail-action-row w-full justify-start gap-2 border-t border-slate-100 pt-2"):
                                    rotate = ui.button(
                                        render_message("webui.render_credentials.button.rotate_1496c92c"), icon="sync",
                                        on_click=lambda _, item=credential: credential_dialog(item),
                                    ).props("outline dense no-caps")
                                    if indexer["status"] != "active":
                                        rotate.disable()
                                    ui.button(
                                        render_message("webui.render_credentials.button.revoke_4fc0db3b"), icon="block", color="negative",
                                        on_click=lambda _, item=credential: confirm_revoke(item),
                                    ).props("outline dense no-caps")
                start = page["offset"] + 1 if page["total"] else 0
                end = min(page["offset"] + len(items), page["total"])
                credential_summary.text = render_message("webui.render_credentials.text.showing_start_end_of_total_5803a7b9", start=start, end=end, total=page['total'])
                credential_previous.set_enabled(page["offset"] > 0)
                credential_next.set_enabled(page["offset"] + page["limit"] < page["total"])

            async def load_credentials(*, offset: int | None = None) -> None:
                requested_offset = credential_state["offset"] if offset is None else max(0, offset)
                try:
                    page = await api.text_indexer_credentials(
                        user_id, history=credential_state["history"], limit=5,
                        offset=requested_offset,
                    )
                except ApiError as error:
                    show_api_error(error)
                    return
                if requested_offset and not page["items"] and page["total"]:
                    await load_credentials(offset=max(0, requested_offset - 5))
                    return
                credential_state.update(offset=page["offset"], page=page)
                render_credentials()

            async def filter_credentials() -> None:
                credential_state.update(history=credential_filter.value, offset=0)
                await load_credentials(offset=0)

            credential_filter.on_value_change(filter_credentials)
            credential_previous.on("click", lambda: load_credentials(offset=credential_state["offset"] - 5))
            credential_next.on("click", lambda: load_credentials(offset=credential_state["offset"] + 5))
            render_credentials()


    return select_text_indexer_details
