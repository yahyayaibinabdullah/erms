"""Existing text-indexers UI with explicit shell and destination callbacks.

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


def build_text_indexers(
    *, register_navigation, show_authenticated_view, search_bar, aggregation_mode_bar, add_button, add_record_button, guidance, title, subtitle, table_container, api, error_message, show_api_error, format_timestamp, localized_lifecycle_value, direction, enter, select_text_indexer_details, select_record_details, show_components,
):
    async def select_text_indexers() -> None:
        register_navigation("text-indexers", "Text Indexers")
        show_authenticated_view()
        enter()
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        guidance.text = ""
        title.text = render_message("webui.select_text_indexers.text.text_indexers_1f668c0c")
        subtitle.text = render_message("webui.select_text_indexers.text.non_interactive_indexing_identities_and_ap_ac33df30")
        table_container.clear()
        try:
            indexers, health, diagnostics = await asyncio.gather(
                api.text_indexers(), api.text_indexers_health(),
                api.text_indexer_diagnostics(limit=10, offset=0),
            )
        except ApiError as error:
            with table_container, ui.column().classes("w-full p-5"):
                ui.label(error_message(error)).classes("text-negative")
                ui.button(render_message("webui.select_text_indexers.button.try_again_f7ef4536"), icon="refresh", on_click=select_text_indexers).props(
                    "outline no-caps"
                )
            return

        def add_text_indexer_dialog() -> None:
            dialog = ui.dialog().props("persistent")
            with dialog, ui.card().classes("w-[580px] max-w-full gap-3"):
                ui.label(render_message("webui.add_text_indexer_dialog.label.add_text_indexer_4b375416")).classes("text-xl font-semibold")
                ui.label(
                    render_message("webui.add_text_indexer_dialog.label.creates_a_non_interactive_identity_assigns_a634b67e")
                ).classes("text-sm text-slate-500")
                name = ui.input(render_message("webui.add_text_indexer_dialog.input.deployment_or_pool_name_7539da84")).props("outlined").classes("w-full")
                external_id = ui.input(render_message("webui.add_text_indexer_dialog.input.immutable_external_id_0e9e9051")).props("outlined").classes("w-full")
                credential_name = ui.input(render_message("webui.add_text_indexer_dialog.input.initial_credential_name_33daef5e")).props("outlined").classes("w-full")
                expiry = ui.input(
                    render_message("webui.add_text_indexer_dialog.input.credential_expiry_iso_8601_e10ffe03"),
                    value=(datetime.now(timezone.utc) + timedelta(days=90)).replace(
                        microsecond=0
                    ).isoformat(),
                ).props("outlined").classes("w-full")
                ui.input(
                    render_message("webui.add_text_indexer_dialog.input.assigned_role_ae268a10"), value="Text Indexer Service (protected, sole role)",
                ).props("outlined readonly").classes("w-full")

                async def submit() -> None:
                    payload = {
                        "name": (name.value or "").strip(),
                        "external_id": (external_id.value or "").strip(),
                        "credential_name": (credential_name.value or "").strip(),
                        "expires_at": (expiry.value or "").strip(),
                    }
                    try:
                        created = await api.create_text_indexer(payload)
                    except ApiError as error:
                        show_api_error(error)
                        return
                    dialog.close()
                    account = created["text_indexer"]
                    reveal_text_indexer_key(
                        created["credential"],
                        lambda: select_text_indexer_details(account["id"]),
                    )

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.add_text_indexer_dialog.button.cancel_45f5d861"), on_click=dialog.close).props("flat no-caps")
                    ui.button(render_message("webui.add_text_indexer_dialog.button.create_and_generate_key_a5f16e9e"), icon="add", on_click=submit).props(
                        "unelevated no-caps"
                    )
            dialog.open()

        def queue_backfill_dialog() -> None:
            dialog = ui.dialog().props("persistent")
            with dialog, ui.card().classes("w-[520px] max-w-full gap-3"):
                ui.label(render_message("webui.queue_backfill_dialog.label.queue_backfill_batch_c4ea11b0")).classes("text-xl font-semibold")
                ui.label(
                    render_message("webui.queue_backfill_dialog.label.queues_low_priority_indexing_jobs_for_exis_f6ecc87b")
                ).classes("text-sm text-slate-500")
                batch_size = ui.number(
                    render_message("webui.queue_backfill_dialog.number.maximum_components_453f254a"), value=500, min=1, max=500, step=1,
                ).props("outlined").classes("w-full")
                ui.label(
                    render_message("webui.queue_backfill_dialog.label.this_returns_after_queuing_text_indexers_p_265b5d9b")
                ).classes("text-xs text-slate-500")

                async def submit_backfill() -> None:
                    try:
                        requested = int(batch_size.value or 0)
                        result = await api.queue_text_indexers_backfill(requested)
                    except (TypeError, ValueError):
                        ui.notify(render_message("webui.submit_backfill.notify.enter_a_whole_number_from_1_to_500_4a71656e"), color="warning")
                        return
                    except ApiError as error:
                        show_api_error(error)
                        return
                    dialog.close()
                    ui.notify(
                        render_message("webui.submit_backfill.notify.examined_drifted_components_queued_queued_d2ec2f63", drifted=result['drifted'], queued=result['queued']),
                        color="positive",
                    )
                    await select_text_indexers()

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.queue_backfill_dialog.button.cancel_3c7e55da"), on_click=dialog.close).props("flat no-caps")
                    ui.button(
                        render_message("webui.queue_backfill_dialog.button.queue_batch_59aa1eb9"), icon="playlist_add", on_click=submit_backfill,
                    ).props("unelevated no-caps")
            dialog.open()

        def retry_failed_dialog() -> None:
            dialog = ui.dialog().props("persistent")
            with dialog, ui.card().classes("w-[540px] max-w-full gap-3"):
                ui.label(render_message("webui.retry_failed_dialog.label.retry_failed_documents_f97ef116")).classes("text-xl font-semibold")
                ui.label(
                    render_message("webui.retry_failed_dialog.label.queue_a_bounded_retry_only_after_correctin_056e1e4e")
                ).classes("text-sm text-slate-500")
                batch_size = ui.number(
                    render_message("webui.retry_failed_dialog.number.maximum_failed_documents_b3470eff"), value=100, min=1, max=500, step=1,
                ).props("outlined").classes("w-full")
                ui.label(
                    render_message("webui.retry_failed_dialog.label.retained_failed_job_history_is_preserved_d_96255725")
                ).classes("text-xs text-slate-500")

                async def submit_retry() -> None:
                    try:
                        requested = int(batch_size.value or 0)
                        result = await api.retry_failed_text_indexer_documents(requested)
                    except (TypeError, ValueError):
                        ui.notify(render_message("webui.submit_retry.notify.enter_a_whole_number_from_1_to_500_2b2ac3cd"), color="warning")
                        return
                    except ApiError as error:
                        show_api_error(error)
                        return
                    dialog.close()
                    ui.notify(
                        render_message("webui.submit_retry.notify.examined_examined_failed_documents_queued_ed66c8d2", examined=result['examined'], queued=result['queued']),
                        color="positive",
                    )
                    await select_text_indexers()

                with ui.row().classes("w-full justify-end gap-2"):
                    ui.button(render_message("webui.retry_failed_dialog.button.cancel_be73a154"), on_click=dialog.close).props("flat no-caps")
                    ui.button(
                        render_message("webui.retry_failed_dialog.button.queue_retries_f4fd3f7f"), icon="replay", on_click=submit_retry,
                    ).props("unelevated no-caps")
            dialog.open()

        async def open_diagnostic_component(record_id: int, component_id: int) -> None:
            try:
                record = await api.get("records", record_id)
                await show_components(record, focused_component_id=component_id)
            except ApiError as error:
                show_api_error(error)

        with table_container, ui.column().classes("w-full p-5 gap-4"):
            metrics = health["metrics"]
            queue = metrics.get("queue", {})
            workers = metrics.get("workers", {})
            recovery = metrics.get("recovery", {})

            def backlog_age(value: Any) -> str:
                if value is None:
                    return render_message_plain("webui.backlog_age.empty")
                seconds = max(0, int(value))
                if seconds < 60:
                    return render_message_plain("webui.backlog_age.seconds", count=seconds)
                if seconds < 3600:
                    return render_message_plain("webui.backlog_age.minutes", count=seconds // 60)
                if seconds < 86400:
                    return render_message_plain("webui.backlog_age.hours", count=seconds // 3600)
                return render_message_plain("webui.backlog_age.days", count=seconds // 86400)

            with ui.card().classes("detail-surface shadow-none p-5 w-full gap-4"):
                with ui.row().classes("w-full items-start gap-3"):
                    with ui.element("div").classes("governance-card-icon"):
                        ui.icon(
                            "health_and_safety" if health["ready_for_search"] else "warning",
                            size="22px",
                        )
                    with ui.column().classes("gap-0 grow min-w-0"):
                        ui.label(render_message("webui.select_text_indexers.label.health_58ba42bd")).classes("text-lg font-semibold")
                        ui.label(
                            render_message("webui.select_text_indexers.label.worker_heartbeats_indexing_queue_and_searc_2306bce9")
                        ).classes("text-sm text-slate-500")
                    ui.badge(
                        render_message("webui.select_text_indexers.badge.ready_for_search_6e324bdc") if health["ready_for_search"] else render_message("webui.select_text_indexers.badge.attention_required_018ec3f4"),
                        color="positive" if health["ready_for_search"] else "warning",
                    ).props("outline")
                    ui.button(
                        render_message("webui.select_text_indexers.button.refresh_489c8018"), icon="refresh", on_click=select_text_indexers,
                    ).props("outline dense no-caps")
                    ui.button(
                        render_message("webui.select_text_indexers.button.queue_backfill_batch_55344f95"), icon="playlist_add",
                        on_click=queue_backfill_dialog,
                    ).props("unelevated dense no-caps")
                    ui.button(
                        render_message("webui.select_text_indexers.button.retry_failed_d128e4bd"), icon="replay", on_click=retry_failed_dialog,
                    ).props("outline dense no-caps").set_enabled(
                        int(health.get("failed_documents", 0)) > 0
                    )
                ui.label(
                    render_message("webui.select_text_indexers.label.api_liveness_is_reported_separately_by_hea_4471aea2")
                ).classes("text-xs text-slate-500")
                with ui.element("div").classes(
                    "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 w-full"
                ):
                    text_indexer_metrics = (
                        (
                            render_message("webui.select_text_indexers.text.active_workers_92ac21cf"), workers.get("active", 0),
                            render_message("webui.select_text_indexers.text.get_stale_registrations_a829ce04", get=workers.get('stale', 0)),
                            "memory", int(workers.get("active", 0)) == 0,
                        ),
                        (
                            render_message("webui.select_text_indexers.text.waiting_418a4e06"), queue.get("queued", 0),
                            render_message("webui.select_text_indexers.text.oldest_backlog_age_660985ec", backlog_age=backlog_age(metrics.get('oldest_queued_seconds'))),
                            "schedule", int(queue.get("queued", 0)) > 0,
                        ),
                        (
                            render_message("webui.select_text_indexers.text.processing_c1ea7da0"), queue.get("leased", 0),
                            render_message("webui.select_text_indexers.text.jobs_with_active_worker_leases_62e4e14b"),
                            "sync", False,
                        ),
                        (
                            render_message("webui.select_text_indexers.text.failed_documents_a52a6b9e"), health.get("failed_documents", 0),
                            render_message("webui.select_text_indexers.text.get_historical_failed_jobs_get_2_unsupport_d0b683dc", get=health.get('historical_failed_jobs', 0), get_2=queue.get('unsupported', 0)),
                            "error_outline", int(health.get("failed_documents", 0)) > 0,
                        ),
                        (
                            render_message("webui.select_text_indexers.text.drifted_documents_d9b3b97f"), health.get("drifted_documents", 0),
                            render_message("webui.select_text_indexers.text.missing_or_obsolete_derived_index_10be6549"),
                            "difference", int(health.get("drifted_documents", 0)) > 0,
                        ),
                        (
                            render_message("webui.select_text_indexers.text.stale_documents_47eeb60a"), health.get("stale_documents", 0),
                            render_message("webui.select_text_indexers.text.published_index_is_no_longer_current_2f26941b"),
                            "update_disabled", int(health.get("stale_documents", 0)) > 0,
                        ),
                        (
                            render_message("webui.select_text_indexers.text.expired_leases_66660c86"), recovery.get("expired_leases", 0),
                            render_message("webui.select_text_indexers.text.get_lease_loss_attempts_b4b9dd3e", get=recovery.get('lease_lost_attempts', 0)),
                            "restart_alt", int(recovery.get("expired_leases", 0)) > 0,
                        ),
                        (
                            render_message("webui.select_text_indexers.text.blocking_jobs_9ff16656"), health.get("blocking_jobs", 0),
                            render_message("webui.select_text_indexers.text.observed_format_timestamp_2519c007", format_timestamp=format_timestamp(health.get('observed_at'))),
                            "hourglass_top", int(health.get("blocking_jobs", 0)) > 0,
                        ),
                    )
                    for label, value, note, icon_name, attention in text_indexer_metrics:
                        with ui.card().classes(
                            "shadow-none border border-slate-200 p-3 gap-1"
                            + (" bg-amber-50" if attention else "")
                        ):
                            with ui.row().classes("w-full items-center gap-2"):
                                ui.icon(
                                    icon_name,
                                    color="warning" if attention else "primary",
                                )
                                ui.label(str(value)).classes("text-2xl font-semibold tabular-nums")
                            ui.label(label).classes("text-sm font-semibold")
                            ui.label(note).classes("text-xs text-slate-500")

            diagnostics_host = ui.element("div").classes("w-full")
            diagnostics_page = {"offset": 0}
            diagnostics_page_size = 10

            def render_failure_diagnostics() -> None:
                diagnostics_host.clear()
                failure_page = diagnostics.get("failures", {})
                failure_items = failure_page.get("items", [])
                total_failures = int(failure_page.get("total", 0))
                groups = diagnostics.get("failure_groups", [])
                unsupported_formats = diagnostics.get("unsupported_formats", [])
                with diagnostics_host, ui.card().classes(
                    "detail-surface shadow-none p-5 w-full gap-4"
                ):
                    with ui.row().classes("w-full items-start gap-3"):
                        with ui.element("div").classes("governance-card-icon"):
                            ui.icon("troubleshoot", size="22px")
                        with ui.column().classes("gap-0 grow min-w-0"):
                            ui.label(render_message("webui.render_failure_diagnostics.label.failure_diagnostics_e8ffa8d8")).classes("text-lg font-semibold")
                            ui.label(
                                render_message("webui.render_failure_diagnostics.label.current_indexing_failures_and_unsupported_ef4bb325")
                            ).classes("text-sm text-slate-500")
                        ui.button(
                            render_message("webui.render_failure_diagnostics.button.refresh_diagnostics_83e70efa"), icon="refresh",
                            on_click=lambda: load_failure_diagnostics(
                                diagnostics_page["offset"]
                            ),
                        ).props("outline dense no-caps")

                    ui.label(render_message("webui.render_failure_diagnostics.label.current_failures_by_cause_and_format_6545d527")).classes(
                        "text-sm font-semibold"
                    )
                    if groups:
                        with ui.element("div").classes(
                            "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2 w-full"
                        ):
                            for group in groups:
                                with ui.card().classes(
                                    "shadow-none border border-slate-200 p-3 gap-1"
                                ):
                                    with ui.row().classes("w-full items-center gap-2"):
                                        ui.badge(str(group["count"]), color="negative").props(
                                            "outline"
                                        )
                                        ui.label(
                                            str(group.get("error_code") or "unknown")
                                        ).classes("text-sm font-semibold break-all")
                                    ui.label(group.get("mime_type") or render_message("webui.render_failure_diagnostics.label.unknown_2bc639ca")).classes(
                                        "text-xs font-mono text-slate-600 break-all"
                                    )
                                    ui.label(
                                        render_message(
                                            "webui.render_failure_diagnostics.label.latest_failure",
                                            timestamp=format_timestamp(group.get("newest_failure_at")),
                                        )
                                    ).classes("text-xs text-slate-500")
                    else:
                        ui.label(render_message("webui.render_failure_diagnostics.label.no_documents_are_currently_failed_93bbc776")).classes(
                            "text-sm text-slate-500"
                        )

                    if failure_items:
                        ui.separator()
                        with ui.element("div").classes("governance-card-list w-full"):
                            for failure in failure_items:
                                with ui.card().classes(
                                    "shadow-none border border-slate-200 p-4 w-full gap-2"
                                ):
                                    with ui.row().classes("w-full items-start gap-3"):
                                        ui.icon("error_outline", color="negative")
                                        with ui.column().classes("gap-0 grow min-w-0"):
                                            ui.label(
                                                failure.get("component_name")
                                                or render_message("webui.render_failure_diagnostics.label.digital_component_digital_component_id_fc07174c", digital_component_id=failure['digital_component_id'])
                                            ).classes("text-sm font-semibold break-words")
                                            ui.label(
                                                render_message("webui.render_failure_diagnostics.label.value_value_2_434ec21b", value=failure.get('error_code') or 'unknown', value_2=failure.get('mime_type') or 'unknown')
                                            ).classes("text-xs font-mono text-slate-600 break-all")
                                        ui.label(
                                            format_timestamp(failure.get("last_attempt_at"))
                                        ).classes("text-xs text-slate-500")
                                    if failure.get("last_error_summary"):
                                        ui.label(failure["last_error_summary"]).classes(
                                            "text-sm text-slate-700 break-words"
                                        )
                                    with ui.row().classes(
                                        "w-full items-center gap-2 flex-wrap"
                                    ):
                                        if failure.get("worker_id"):
                                            ui.badge(
                                                render_message("webui.render_failure_diagnostics.badge.worker_worker_id_ff69e3e4", worker_id=failure['worker_id'])
                                            ).props("outline color=blue-grey")
                                        if failure.get("attempt_no"):
                                            ui.badge(
                                                render_message("webui.render_failure_diagnostics.badge.attempt_attempt_no_cdf09d73", attempt_no=failure['attempt_no'])
                                            ).props("outline color=blue-grey")
                                        if failure.get("can_open"):
                                            ui.button(
                                                failure.get("record_number")
                                                or render_message("webui.render_failure_diagnostics.button.record_record_id_96bc8024", record_id=failure['record_id']),
                                                icon="description",
                                                on_click=lambda _, record_id=failure["record_id"]:
                                                    select_record_details(record_id),
                                            ).props("flat dense no-caps color=primary").tooltip(
                                                failure.get("record_title") or render_message("webui.render_failure_diagnostics.tooltip.open_record_833909f2")
                                            )
                                            ui.button(
                                                render_message("webui.render_failure_diagnostics.button.component_digital_component_id_831b121d", digital_component_id=failure['digital_component_id']),
                                                icon="attachment",
                                                on_click=lambda _, record_id=failure["record_id"],
                                                                    component_id=failure["digital_component_id"]:
                                                    open_diagnostic_component(
                                                        record_id, component_id
                                                    ),
                                            ).props("flat dense no-caps color=primary")
                                        else:
                                            ui.label(
                                                render_message("webui.render_failure_diagnostics.label.record_component_links_require_record_and_894030f7")
                                            ).classes("text-xs text-slate-500")

                        start = diagnostics_page["offset"] + 1
                        end = min(diagnostics_page["offset"] + len(failure_items), total_failures)
                        with ui.row().classes("w-full justify-end items-center gap-2"):
                            ui.label(
                                render_message("webui.render_failure_diagnostics.label.showing_start_end_of_total_failures_curren_0789126a", start=start, end=end, total_failures=total_failures)
                            ).classes("text-sm text-slate-500")
                            ui.button(
                                render_message("webui.render_failure_diagnostics.button.previous_a37406c2"), icon="chevron_left",
                                on_click=lambda: load_failure_diagnostics(
                                    max(0, diagnostics_page["offset"] - diagnostics_page_size)
                                ),
                            ).props("flat dense no-caps").set_enabled(
                                diagnostics_page["offset"] > 0
                            )
                            ui.button(
                                render_message("webui.render_failure_diagnostics.button.next_856cdffc"), icon="chevron_right",
                                on_click=lambda: load_failure_diagnostics(
                                    diagnostics_page["offset"] + diagnostics_page_size
                                ),
                            ).props("flat dense no-caps").set_enabled(
                                diagnostics_page["offset"] + diagnostics_page_size
                                < total_failures
                            )

                    ui.separator()
                    ui.label(render_message("webui.render_failure_diagnostics.label.unsupported_formats_currently_encountered_efac58f6")).classes(
                        "text-sm font-semibold"
                    )
                    ui.label(
                        render_message("webui.render_failure_diagnostics.label.these_documents_were_safely_classified_as_a5f6518b")
                    ).classes("text-xs text-slate-500")
                    if unsupported_formats:
                        with ui.element("div").classes(
                            "grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2 w-full"
                        ):
                            for item in unsupported_formats:
                                with ui.row().classes(
                                    "items-center gap-2 border border-slate-200 rounded-lg p-3"
                                ):
                                    ui.badge(str(item["count"]), color="orange").props("outline")
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(item.get("mime_type") or render_message("webui.render_failure_diagnostics.label.unknown_2bc639ca")).classes(
                                            "text-xs font-mono break-all"
                                        )
                                        ui.label(
                                            render_message(
                                                "webui.render_failure_diagnostics.label.latest_unsupported",
                                                timestamp=format_timestamp(item.get("most_recent_at")),
                                            )
                                        ).classes("text-xs text-slate-500")
                    else:
                        ui.label(render_message("webui.render_failure_diagnostics.label.no_unsupported_formats_are_currently_recor_1390594a")).classes(
                            "text-sm text-slate-500"
                        )

            async def load_failure_diagnostics(offset: int = 0) -> None:
                nonlocal diagnostics
                try:
                    diagnostics = await api.text_indexer_diagnostics(
                        limit=diagnostics_page_size, offset=offset,
                    )
                except ApiError as error:
                    show_api_error(error)
                    return
                diagnostics_page["offset"] = offset
                render_failure_diagnostics()

            render_failure_diagnostics()

            with ui.row().classes("w-full items-center gap-3"):
                query = ui.input(render_message("webui.select_text_indexers.input.filter_by_name_or_external_id_3d14f34f")).props(
                    "outlined dense clearable"
                ).classes("grow")
                ui.button(
                    render_message("webui.select_text_indexers.button.add_text_indexer_fd6584b1"), icon="add", on_click=add_text_indexer_dialog,
                ).props("unelevated no-caps")
            results = ui.element("div").classes("governance-card-list w-full")
            page = {"offset": 0}
            page_size = 10
            with ui.row().classes("w-full justify-end items-center gap-2"):
                page_label = ui.label().classes("text-sm text-slate-500")
                previous = ui.button(render_message("webui.select_text_indexers.button.previous_0509bae7"), icon="chevron_right" if direction() == "rtl" else "chevron_left").props("flat dense no-caps")
                next_button = ui.button(render_message("webui.select_text_indexers.button.next_0e31089e"), icon="chevron_left" if direction() == "rtl" else "chevron_right").props("flat dense no-caps")

            def filtered() -> list[dict[str, Any]]:
                needle = str(query.value or "").strip().lower()
                if not needle:
                    return indexers
                return [
                    item for item in indexers
                    if needle in item["name"].lower()
                    or needle in item["external_id"].lower()
                ]

            def render() -> None:
                rows = filtered()
                if page["offset"] >= len(rows) and page["offset"]:
                    page["offset"] = max(0, ((len(rows) - 1) // page_size) * page_size)
                shown = rows[page["offset"]:page["offset"] + page_size]
                results.clear()
                with results:
                    if not shown:
                        with ui.card().classes("governance-empty-state shadow-none"):
                            ui.icon("manage_search", size="34px").classes("text-slate-300")
                            ui.label(
                                render_message("webui.render.label.no_matching_text_indexers_064a7cfd") if indexers else render_message("webui.render.label.no_text_indexers_2719a0c9")
                            ).classes("font-semibold")
                            ui.label(
                                render_message("webui.render.label.create_a_deployment_or_pool_identity_when_289c263c")
                            ).classes("text-sm text-slate-500")
                    for item in shown:
                        with ui.card().classes(
                            "governance-list-card shadow-none cursor-pointer"
                        ).on(
                            "click", lambda _, indexer_id=item["id"]:
                                select_text_indexer_details(indexer_id),
                        ):
                            with ui.row().classes("w-full items-start gap-3 no-wrap"):
                                with ui.element("div").classes("governance-card-icon"):
                                    ui.icon("manage_search", size="20px")
                                with ui.column().classes("gap-0 grow min-w-0"):
                                    ui.label(item["name"]).classes("font-semibold")
                                    ui.label(item["external_id"]).classes(
                                        "text-xs text-slate-500 font-mono break-all"
                                    )
                                ui.badge(
                                    localized_lifecycle_value(item["status"]),
                                    color={"active": "positive", "suspended": "warning"}.get(
                                        item["status"], "grey-7"
                                    ),
                                ).props("outline")
                            with ui.element("div").classes("governance-list-facts"):
                                for label, value in (
                                    (render_message("webui.text_indexer_card.active_credentials"), str(item["active_credential_count"])),
                                    (render_message("webui.text_indexer_card.credential_history"), str(item["credential_count"])),
                                    (render_message("webui.text_indexer_card.last_used"), format_timestamp(item["last_used_at"]) if item.get("last_used_at") else render_message("webui.text_indexer_card.never")),
                                ):
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(label).classes("detail-field-label")
                                        ui.label(value).classes("text-sm")
                start = page["offset"] + 1 if rows else 0
                end = min(page["offset"] + page_size, len(rows))
                page_label.text = render_message("webui.render.text.start_end_of_row_count_b847f230", start=start, end=end, row_count=len(rows))
                previous.set_enabled(page["offset"] > 0)
                next_button.set_enabled(page["offset"] + page_size < len(rows))

            def move(delta: int) -> None:
                page["offset"] = max(0, page["offset"] + delta * page_size)
                render()

            query.on_value_change(lambda: (page.update(offset=0), render()))
            previous.on("click", lambda: move(-1))
            next_button.on("click", lambda: move(1))
            render()


    return select_text_indexers
