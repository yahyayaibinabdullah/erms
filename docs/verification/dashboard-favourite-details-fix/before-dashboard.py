"""Dashboard overview, personal resources, review reminders and retained refresh."""
from __future__ import annotations
from typing import Any
from .api_client import ApiError
from .entities import ENTITIES
import asyncio
from nicegui import background_tasks
from .config import dashboard_favourite_item_limit
from .config import dashboard_recent_days
from .config import dashboard_recent_item_limit
from .i18n_catalogue import render_message
from nicegui import ui

def build_dashboard(
    *, STOP_PROPAGATION_CLICK_HANDLER, accept_application_configuration, add_button, add_record_button, aggregation_mode_bar, aggregation_state, api, collection_state, dashboard_state, decorate_for_spec, enter_dashboard, error_message, format_file_size, format_timestamp, get_configuration, get_localization, get_principal, get_resource, guidance, open_aggregation, page_client, personal, personal_dialog_list_height, register_navigation, render_table, require_principal, review_display, search_bar, select_classification_workspace, select_entity, select_holds, select_organization_unit_details, set_connection_status, show_authenticated_view, show_record_details, subtitle, table_container, title,
):
    def dashboard_session_key() -> tuple[Any, ...] | None:
        principal = get_principal()
        if principal is None:
            return None
        localization = get_localization() or {}
        return (
            dashboard_state.get("dashboard_session_revision", 0),
            principal["user"]["id"],
            localization.get("effective_language", "en"),
            localization.get("working_timezone", "UTC"),
            tuple(sorted(principal.get("global_privileges", []))),
            tuple(sorted(role["id"] for role in principal.get("roles", []))),
        )


    def clear_dashboard_session() -> None:
        """Discard private snapshots and invalidate all old dashboard callbacks."""
        dashboard_state.pop("dashboard_summary_cache", None)
        dashboard_state.pop("dashboard_summary_cache_key", None)
        dashboard_state.pop("dashboard_view_token", None)
        dashboard_state["dashboard_session_revision"] = dashboard_state.get("dashboard_session_revision", 0) + 1


    async def select_dashboard() -> None:
        dashboard_principal = get_principal()
        dashboard_key = dashboard_session_key()
        if dashboard_key is None:
            return
        dashboard_view_token = object()
        dashboard_state["dashboard_view_token"] = dashboard_view_token
        if dashboard_state.get("dashboard_summary_cache_key") != dashboard_key:
            dashboard_state.pop("dashboard_summary_cache", None)
            dashboard_state.pop("dashboard_summary_cache_key", None)
        register_navigation("dashboard", render_message("navigation.item.dashboard"))
        show_authenticated_view()
        enter_dashboard(); collection_state.update(rows=[], searched=True); aggregation_state.update(aggregation_detail=None)
        title.text = render_message("navigation.item.dashboard")
        subtitle.text = render_message("dashboard.subtitle")
        add_button.set_visibility(False)
        add_record_button.set_visibility(False)
        search_bar.set_visibility(False)
        aggregation_mode_bar.set_visibility(False)
        guidance.text = ""
        table_container.clear()
        with table_container:
            dashboard_content = ui.column().classes("w-full px-5 pb-5 pt-0 gap-4")
        dashboard_load_state = {"running": False}
        dashboard_refresh_controls: dict[str, Any] = {"button": None}

        def dashboard_session_is_current() -> bool:
            return (
                get_principal() is dashboard_principal
                and dashboard_session_key() == dashboard_key
                and dashboard_state.get("dashboard_view_token") is dashboard_view_token
                and not getattr(page_client, "_deleted", False)
                and page_client.has_socket_connection
            )

        def dashboard_view_is_current() -> bool:
            return (
                dashboard_session_is_current()
                and get_resource() == "dashboard"
                and not dashboard_content.is_deleted
            )

        def dashboard_medium_label(medium: str, count: int) -> str:
            if medium == "physical":
                return render_message("dashboard.medium.physical", count=count)
            if medium == "digital":
                return render_message("dashboard.medium.digital", count=count)
            return render_message("dashboard.medium.mixed", count=count)

        def dashboard_attention_label(metric: str, count: int) -> str:
            if metric == "vital":
                return render_message("dashboard.metric.vital", count=count)
            return render_message("dashboard.metric.held", count=count)

        def dashboard_aggregation_status_label(status: str, count: int) -> str:
            if status == "open":
                return render_message("dashboard.metric.open", count=count)
            return render_message("dashboard.metric.closed", count=count)

        def dashboard_resource_type(resource: str) -> str:
            if resource == "aggregations":
                return render_message("dashboard.resource.aggregation")
            return render_message("dashboard.resource.record")

        async def open_dashboard_resource(resource: str, item: dict[str, Any]) -> None:
            if not dashboard_session_is_current():
                return
            try:
                entity = await api.get(resource, item["id"])
                if not dashboard_session_is_current():
                    return
                if resource == "aggregations":
                    await open_aggregation(entity)
                else:
                    await show_record_details(entity)
            except ApiError as error:
                if not dashboard_session_is_current():
                    return
                ui.notify(error_message(error), color="negative", close_button=True)

        async def show_unclassified_roots() -> None:
            await select_entity("aggregations")
            try:
                # The API evaluates this against the true stored parent before
                # response redaction; a concealed parent is not a root.
                result = await api.search_request("aggregations", {
                    "where": {"and": [
                        {"field": "parent_aggregation_id", "operator": "is_null"},
                        {"field": "classification_id", "operator": "is_null"},
                    ]},
                    "sort": [{"field": "date_created", "direction": "desc"}],
                    "limit": 100,
                })
                collection_state["rows"] = await decorate_for_spec(
                    ENTITIES["aggregations"], result["items"],
                )
                collection_state["searched"] = True
                subtitle.text = render_message("webui.show_unclassified_roots.text.root_aggregations_missing_a_governing_clas_b4fc46cb")
                guidance.text = (
                    render_message("webui.show_unclassified_roots.text.showing_row_count_of_total_unclassified_ro_823f8b47", row_count=len(collection_state['rows']), total=result['total'])
                )
                render_table(ENTITIES["aggregations"])
            except ApiError as error:
                ui.notify(error_message(error), color="negative", close_button=True)

        async def show_all_reviews(review_kind: str) -> None:
            if not dashboard_view_is_current():
                return
            register_navigation(
                "dashboard", f"{review_kind.title()} reviews", dynamic_label=True,
            )
            title.text = render_message("webui.show_all_reviews.text.title_reviews_bd68819e", title=review_kind.title())
            subtitle.text = render_message("webui.show_all_reviews.text.governance_review_reminders_for_holdings_o_05bb2c0c")
            table_container.clear()
            page = {"offset": 0, "limit": 25, "loading": False}
            with table_container, ui.column().classes("w-full p-5 gap-3"):
                with ui.row().classes("w-full items-center"):
                    ui.button(render_message("webui.show_all_reviews.button.back_to_dashboard_7f5aab05"), icon="arrow_back", on_click=select_dashboard).props("flat no-caps")
                    ui.space()
                    page_badge = ui.badge(color="negative" if review_kind == "overdue" else "warning").props("outline")
                results_host = ui.column().classes("w-full gap-3")
                with ui.row().classes("w-full items-center justify-end gap-1"):
                    previous_page = ui.button(icon="chevron_left").props("flat round dense")
                    page_label = ui.label().classes("text-sm text-slate-500 min-w-24 text-center")
                    next_page = ui.button(icon="chevron_right").props("flat round dense")

            async def load_review_page() -> None:
                if not dashboard_session_is_current() or results_host.is_deleted or page["loading"]:
                    return
                page["loading"] = True
                previous_page.props(add="disable")
                next_page.props(add="disable")
                results_host.clear()
                with results_host, ui.row().classes("w-full justify-center py-8"):
                    ui.spinner("dots", size="28px")
                try:
                    fetched = await api.dashboard_reviews(
                        review_kind, limit=page["limit"], offset=page["offset"],
                    )
                    if not dashboard_session_is_current() or results_host.is_deleted:
                        return
                    has_more = len(fetched) > page["limit"]
                    items = fetched[:page["limit"]]
                    results_host.clear()
                    with results_host:
                        if not items:
                            ui.label(render_message("webui.show_all_reviews.label.no_matching_review_reminders_d8ec16f5")).classes("text-slate-500")
                        for item in items:
                            resource = "aggregations" if item["entity_type"] == "aggregation" else "records"
                            number = item.get("aggregation_number") or item.get("record_number")
                            with ui.card().classes(
                                "recent-card cursor-pointer w-full shadow-none border border-slate-200 p-3"
                            ).on(
                                "click", lambda _, row=item, kind=resource: open_dashboard_resource(
                                    kind, {"id": row["entity_id"]},
                                ),
                            ):
                                with ui.row().classes("w-full items-center gap-3"):
                                    ui.icon("folder" if resource == "aggregations" else "description", color="primary")
                                    with ui.column().classes("gap-0 grow min-w-0"):
                                        ui.label(item["title"]).classes("font-semibold")
                                        ui.label(render_message("webui.show_all_reviews.label.number_review_display_82a23fd9", number=number, review_display=review_display(item['date_of_next_review']))).classes("text-xs text-slate-500")
                    page_number = page["offset"] // page["limit"] + 1
                    page_badge.text = str(len(items))
                    page_label.text = render_message(
                        "webui.render_global_search_results.label.page_page_number_9319ded9",
                        page_number=page_number,
                    )
                    previous_page.set_enabled(page["offset"] > 0)
                    next_page.set_enabled(has_more)
                except asyncio.CancelledError:
                    return
                except ApiError as error:
                    if not dashboard_session_is_current() or results_host.is_deleted:
                        return
                    results_host.clear()
                    with results_host:
                        ui.label(error_message(error)).classes("text-negative")
                finally:
                    page["loading"] = False

            async def move_review_page(direction: int) -> None:
                page["offset"] = max(0, page["offset"] + direction * page["limit"])
                await load_review_page()

            previous_page.on("click", lambda: move_review_page(-1))
            next_page.on("click", lambda: move_review_page(1))
            await load_review_page()

        async def load_dashboard(
            *, summary_override: dict[str, Any] | None = None,
            refresh_only: bool = False,
        ) -> None:
            if not dashboard_view_is_current() or dashboard_load_state["running"]:
                return
            dashboard_load_state["running"] = True
            refresh_button = dashboard_refresh_controls.get("button")
            if refresh_only and refresh_button is not None:
                refresh_button.props(add="loading disable")
            elif summary_override is None:
                dashboard_content.clear()
                with dashboard_content:
                    with ui.row().classes("dashboard-overview-heading w-full items-center"):
                        ui.label(render_message("webui.load_dashboard.label.overview_c59db7d5")).classes("text-lg font-semibold")
                        ui.space()
                        ui.button(
                            render_message("webui.load_dashboard.button.refresh_938d7997"),
                            icon="refresh",
                        ).props("flat dense no-caps color=primary disable")
                    with ui.row().classes("w-full items-center justify-center py-12 gap-2"):
                        ui.spinner("dots", size="32px")
                        ui.label(render_message("webui.load_dashboard.label.loading_dashboard_30b6a7ab")).classes("text-slate-500")

            try:
                privileges = set(require_principal().get("global_privileges", []))
                can_classify = "classifications.administer" in privileges
                can_organize = "organization.administer" in privileges
                can_administer_users = "identity.users.administer" in privileges

                if summary_override is None:
                    summary = await api.dashboard_summary(recent_limit=50)
                    # Check ownership before any cache write or UI/config update.
                    if not dashboard_view_is_current():
                        return
                    dashboard_state["dashboard_summary_cache"] = summary
                    dashboard_state["dashboard_summary_cache_key"] = dashboard_key
                else:
                    summary = summary_override
                if not dashboard_view_is_current():
                    return
                accept_application_configuration(summary["application_configuration"])
                recent_limit = dashboard_recent_item_limit(summary["application_configuration"])
                recent_days = dashboard_recent_days(summary["application_configuration"])
                counts = summary["overview_counts"]
                medium_counts = summary["overview_medium_counts"]
                attention_counts = summary["overview_resource_attention_counts"]
                aggregation_status_counts = summary["overview_aggregation_status_counts"]
                component_metrics = summary["overview_digital_component_metrics"]
                metrics = summary["classification_metrics"]
                published_scheme_count = int(metrics["published_scheme_count"])
                draft_scheme_count = int(metrics["draft_scheme_count"])
                inactive_scheme_count = int(metrics["inactive_scheme_count"])
                branch_count = int(metrics["branch_count"])
                terminal_count = int(metrics["terminal_count"])
                assignable_terminal_count = int(metrics["assignable_terminal_count"])
                draft_terminal_count = int(metrics["draft_terminal_count"])
                inactive_classification_count = int(metrics["inactive_classification_count"])
                unclassified_root_count = int(summary["unclassified_root_count"])
                ownership_counts = summary["ownership_counts"]
                favourites = summary["favourites"]
                personal.favourites = favourites
                personal.favourite_ids = {
                    resource: {int(item["id"]) for item in favourites[resource]}
                    for resource in ("aggregations", "records")
                }
                activity = summary["recent_activity"]
                def recent_record_entries(
                    source_activity: list[dict[str, Any]], *, limit: int | None = None,
                ) -> list[dict[str, Any]]:
                    entries = [
                        {
                            "id": item["entity_id"],
                            "title": item["title"],
                            "record_number": item.get("record_number"),
                            "_activity_at": item["occurred_at"],
                            "_operation": item["operation"],
                        }
                        for item in source_activity
                        if item["entity_type"] == "record"
                        and item["operation"] in {"CREATE", "UPDATE", "CONTENT_VIEWED"}
                    ]
                    return entries if limit is None else entries[:limit]

                all_recent_records = recent_record_entries(activity)
                recent_records = all_recent_records[:recent_limit]
                favourite_limit = dashboard_favourite_item_limit(get_configuration())
            except ApiError as error:
                if not dashboard_view_is_current():
                    return
                if error.status_code == 401:
                    set_connection_status(True)
                    return
                if refresh_only:
                    # A failed refresh must not destroy this identity's last
                    # authorized snapshot or the working Refresh control.
                    with dashboard_content:
                        ui.notify(error_message(error), color="negative", close_button=True)
                else:
                    dashboard_content.clear()
                    with dashboard_content:
                        ui.label(error_message(error)).classes("text-negative p-5")
                set_connection_status(False)
                return
            finally:
                dashboard_load_state["running"] = False
                if (
                    dashboard_view_is_current()
                    and refresh_button is not None
                    and not getattr(refresh_button, "_deleted", False)
                ):
                    refresh_button.props(remove="loading disable")

            if not dashboard_view_is_current():
                return
            dashboard_content.clear()
            with dashboard_content:
                with ui.row().classes("w-full items-center"):
                    ui.label(render_message("webui.load_dashboard.label.overview_c59db7d5")).classes("text-lg font-semibold")
                    ui.space()
                    dashboard_refresh_controls["button"] = ui.button(
                        render_message("webui.load_dashboard.button.refresh_938d7997"),
                        icon="refresh",
                        on_click=lambda: load_dashboard(refresh_only=True),
                    ).props("flat dense no-caps color=primary")
                with ui.element("div").classes("dashboard-overview-primary w-full"):
                    for resource, label, icon, handler in (
                        ("aggregations", render_message("navigation.item.aggregations"), "folder", lambda: select_entity("aggregations")),
                        ("records", render_message("navigation.item.records"), "description", lambda: select_entity("records")),
                    ):
                        with ui.card().classes(
                            "dashboard-overview-primary-card cursor-pointer"
                        ).on("click", lambda _, action=handler: action()):
                            with ui.row().classes("dashboard-overview-card-heading w-full items-center no-wrap gap-3"):
                                with ui.element("div").classes("dashboard-overview-icon"):
                                    ui.icon(icon, size="20px")
                                with ui.column().classes("gap-0 min-w-0"):
                                    ui.label(label).classes("text-sm font-semibold text-slate-700")
                                    ui.label(render_message("webui.load_dashboard.label.visible_to_you_16b9d228")).classes("text-[11px] text-slate-500")
                                ui.space()
                                ui.label(str(counts[resource])).classes(
                                    "text-xl font-bold text-slate-800 tabular-nums"
                                )
                            with ui.element("div").classes("dashboard-overview-mediums"):
                                for medium, medium_icon in (
                                    ("physical", "inventory_2"),
                                    ("digital", "cloud"),
                                    ("mixed", "join_inner"),
                                ):
                                    with ui.element("span").classes("dashboard-overview-medium"):
                                        ui.icon(medium_icon, size="13px").classes("text-primary")
                                        ui.label(
                                            dashboard_medium_label(medium,medium_counts[resource][medium])
                                        ).classes("tabular-nums")
                                ui.label("|").classes("dashboard-overview-separator").props(
                                    "aria-hidden=true"
                                )
                                for metric, metric_icon in (("vital", "emergency"), ("held", "gavel")):
                                    with ui.element("span").classes("dashboard-overview-signal"):
                                        ui.icon(metric_icon, size="13px").classes(
                                            "text-red-600" if metric == "vital" else "text-amber-600"
                                        )
                                        ui.label(
                                            dashboard_attention_label(metric,attention_counts[resource][metric])
                                        ).classes("font-semibold tabular-nums")
                                if resource == "aggregations":
                                    for status, status_color in (
                                        ("open", "text-green-700"),
                                        ("closed", "text-slate-500"),
                                    ):
                                        with ui.element("span").classes(
                                            f"dashboard-overview-signal {status_color}"
                                        ):
                                            ui.label(
                                                dashboard_aggregation_status_label(status,aggregation_status_counts[status])
                                            ).classes("font-semibold tabular-nums")
                                else:
                                    with ui.element("span").classes("dashboard-overview-signal"):
                                        ui.icon("attachment", size="13px").classes("text-primary")
                                        ui.label(
                                            render_message("dashboard.metric.components",count=component_metrics["component_count"])
                                        ).classes("font-semibold tabular-nums")
                                    with ui.element("span").classes("dashboard-overview-signal"):
                                        ui.icon("storage", size="13px").classes("text-primary")
                                        ui.label(
                                            format_file_size(component_metrics["storage_size_in_bytes"])
                                        ).classes("font-semibold tabular-nums")

                administration_items = []
                if can_classify:
                    administration_items.extend((
                        ("classification-schemes", render_message("navigation.item.classification_schemes"), "account_tree", select_classification_workspace),
                        ("classifications", render_message("dashboard.admin.classifications"), "schema", select_classification_workspace),
                    ))
                if "holds.administer" in privileges:
                    administration_items.append(
                        ("holds", render_message("navigation.item.holds"), "gavel", select_holds),
                    )
                if can_organize:
                    administration_items.extend((
                        ("org-units", render_message("navigation.item.org_units"), "corporate_fare", lambda: select_entity("org-units")),
                        ("roles", render_message("navigation.item.roles"), "badge", lambda: select_entity("roles")),
                    ))
                if can_administer_users:
                    administration_items.append(
                        ("users", render_message("navigation.item.users"), "group", lambda: select_entity("users")),
                    )
                if administration_items:
                    with ui.element("div").classes("dashboard-overview-admin"):
                        for resource, label, icon, handler in administration_items:
                            with ui.element("div").classes(
                                "dashboard-overview-admin-item"
                            ).on("click", lambda _, action=handler: action()):
                                ui.icon(icon, size="17px").classes("text-primary shrink-0")
                                ui.label(label).classes(
                                    "text-xs font-medium text-slate-600 truncate min-w-0"
                                ).tooltip({
                                    "classification-schemes": render_message("navigation.item.classification_schemes"),
                                    "org-units": render_message("navigation.item.org_units"),
                                }.get(resource, label))
                                ui.space()
                                ui.label(str(counts[resource])).classes(
                                    "text-sm font-bold text-slate-800 tabular-nums"
                                )

                attention_maximum = max(
                    1,
                    attention_counts["aggregations"]["vital"],
                    attention_counts["aggregations"]["held"],
                    attention_counts["records"]["vital"],
                    attention_counts["records"]["held"],
                )
                with ui.element("section").classes("dashboard-attention-chart").props(
                    'aria-label=' + repr(render_message("webui.load_dashboard.accessible_name.attention_signals_for_visible_aggregations_c8c49e94"))
                ):
                    with ui.row().classes("classification-detail-identity w-full items-start gap-3"):
                        with ui.column().classes("gap-0"):
                            ui.label(render_message("webui.load_dashboard.label.attention_signals_71bf1d51")).classes(
                                "text-sm font-semibold text-slate-700"
                            )
                            ui.label(
                                render_message("webui.load_dashboard.label.visible_vital_and_effectively_held_resourc_b027ff42")
                            ).classes("text-xs text-slate-500")
                        ui.space()
                        with ui.element("div").classes("dashboard-chart-legend"):
                            for label, color in ((render_message("dashboard.legend.vital"), "#d85a6d"), (render_message("dashboard.legend.on_hold"), "#d99b32")):
                                with ui.element("span").classes("dashboard-chart-legend-item"):
                                    ui.element("i").classes("dashboard-chart-swatch").style(
                                        f"background: {color}"
                                    )
                                    ui.label(label)
                    with ui.element("div").classes("dashboard-attention-plot"):
                        ui.label(render_message("webui.load_dashboard.label.number_of_items_3b9e348e")).classes("dashboard-attention-axis-label")
                        for resource, label in (
                            ("aggregations", render_message("navigation.item.aggregations")),
                            ("records", render_message("navigation.item.records")),
                        ):
                            with ui.element("div").classes("dashboard-attention-group"):
                                for metric, color in (("vital", "#d85a6d"), ("held", "#d99b32")):
                                    value = int(attention_counts[resource][metric])
                                    height = round((value / attention_maximum) * 112)
                                    with ui.element("div").classes(
                                        "dashboard-attention-bar"
                                    ).style(f"height: {height}px; background: {color}").props(
                                        f"aria-label='{label} {metric}: {value}'"
                                    ):
                                        ui.label(str(value)).classes(
                                            "dashboard-attention-bar-value"
                                        )
                                ui.label(label).classes("dashboard-attention-group-label")

                personal_sections_area = ui.element("div").classes("w-full")

                with ui.row().classes("w-full items-center mt-2"):
                    ui.label(render_message("webui.load_dashboard.label.holdings_by_organizational_unit_342445f5")).classes("text-lg font-semibold")
                    ui.space()
                    unit_count = len(ownership_counts)
                    ui.label(render_message("dashboard.count.units",count=unit_count)).classes(
                        "text-xs text-slate-500"
                    )
                ui.label(
                    render_message("webui.load_dashboard.label.only_units_where_you_have_an_effective_rol_68aa4c10")
                ).classes("text-sm leading-5 text-slate-500 -mt-1")
                if ownership_counts:
                    holdings_maximum = max(
                        1, *(int(item["record_count"]) for item in ownership_counts)
                    )
                    with ui.element("section").classes("dashboard-holdings-chart").props(
                        'aria-label=' + repr(render_message("webui.load_dashboard.accessible_name.records_by_organizational_unit_and_medium_a855d0ad"))
                    ):
                        with ui.row().classes("w-full items-start gap-3"):
                            with ui.column().classes("gap-0"):
                                ui.label(render_message("webui.load_dashboard.label.records_by_medium_92e62b20")).classes(
                                    "text-sm font-semibold text-slate-700"
                                )
                                ui.label(
                                    render_message("webui.load_dashboard.label.compare_record_volume_and_medium_mix_acros_3295a6ca")
                                ).classes("text-xs text-slate-500")
                            ui.space()
                            with ui.element("div").classes("dashboard-chart-legend"):
                                for label, color in (
                                    (render_message("dashboard.legend.physical"), "#356fb1"),
                                    (render_message("dashboard.legend.digital"), "#39a19f"),
                                    (render_message("dashboard.legend.mixed"), "#9cbfe5"),
                                ):
                                    with ui.element("span").classes(
                                        "dashboard-chart-legend-item"
                                    ):
                                        ui.element("i").classes(
                                            "dashboard-chart-swatch"
                                        ).style(f"background: {color}")
                                        ui.label(label)
                        with ui.element("div").classes("dashboard-holdings-chart-rows"):
                            for owner_count in ownership_counts:
                                record_count = int(owner_count["record_count"])
                                overall_width = (record_count / holdings_maximum) * 100
                                with ui.element("div").classes(
                                    "dashboard-holdings-chart-row"
                                ):
                                    ui.label(owner_count["org_unit_name"]).classes(
                                        "dashboard-holdings-chart-name"
                                    ).tooltip(owner_count["org_unit_name"])
                                    with ui.element("div").classes(
                                        "dashboard-holdings-chart-track"
                                    ).style(f"width: {overall_width:.2f}%"):
                                        for medium, color in (
                                            ("physical", "#356fb1"),
                                            ("digital", "#39a19f"),
                                            ("mixed", "#9cbfe5"),
                                        ):
                                            medium_count = int(
                                                owner_count[f"{medium}_record_count"]
                                            )
                                            medium_width = (
                                                (medium_count / record_count) * 100
                                                if record_count else 0
                                            )
                                            ui.element("span").classes(
                                                "dashboard-holdings-chart-segment"
                                            ).style(
                                                f"width: {medium_width:.2f}%; background: {color}"
                                            ).props(
                                                f"aria-label='{medium.title()} {medium_count}'"
                                            )
                                    ui.label(str(record_count)).classes(
                                        "dashboard-holdings-chart-total"
                                    )
                    with ui.element("div").classes("dashboard-holdings-list"):
                        for owner_count in ownership_counts:
                            row = ui.element("div").classes("dashboard-holdings-row").props(
                                "role=button tabindex=0"
                            )
                            row.on(
                                "click",
                                lambda _, item=owner_count: select_organization_unit_details(
                                    item["org_unit_id"]
                                ),
                            )
                            row.on(
                                "keydown.enter",
                                lambda _, item=owner_count: select_organization_unit_details(
                                    item["org_unit_id"]
                                ),
                            )
                            with row:
                                with ui.element("div").classes("dashboard-holdings-identity"):
                                    with ui.element("div").classes("dashboard-overview-icon"):
                                        ui.icon("corporate_fare", size="20px")
                                    with ui.column().classes("gap-0 min-w-0"):
                                        ui.label(owner_count["org_unit_name"]).classes(
                                            "text-sm font-semibold text-slate-700 truncate w-full"
                                        ).tooltip(owner_count["org_unit_name"])
                                        ui.label(owner_count["org_unit_code"]).classes(
                                            "text-xs font-semibold text-primary"
                                        )
                                with ui.element("div").classes("dashboard-holdings-metric"):
                                    ui.icon("folder", size="17px").classes("text-primary shrink-0")
                                    with ui.column().classes("gap-0"):
                                        ui.label(
                                            render_message("dashboard.metric.aggregations",count=owner_count["aggregation_count"])
                                        ).classes("text-xs font-medium tabular-nums")
                                        ui.label(
                                            render_message("dashboard.metric.aggregation_status",open=owner_count["open_aggregation_count"],closed=owner_count["closed_aggregation_count"])
                                        ).classes("dashboard-holdings-metric-detail tabular-nums")
                                with ui.element("div").classes("dashboard-holdings-metric"):
                                    ui.icon("description", size="17px").classes("text-primary shrink-0")
                                    with ui.column().classes("gap-0"):
                                        ui.label(
                                            render_message("dashboard.metric.records",count=owner_count["record_count"])
                                        ).classes("text-xs font-medium tabular-nums")
                                        with ui.element("div").classes("dashboard-holdings-mediums"):
                                            for medium_index, medium in enumerate((
                                                "physical", "digital", "mixed",
                                            )):
                                                if medium_index:
                                                    ui.label("·").classes(
                                                        "dashboard-holdings-medium"
                                                    ).props("aria-hidden=true")
                                                with ui.element("span").classes(
                                                    "dashboard-overview-medium dashboard-holdings-medium"
                                                ):
                                                    ui.label(
                                                        dashboard_medium_label(medium,owner_count[f"{medium}_record_count"])
                                                    ).classes("tabular-nums")
                                with ui.element("div").classes("dashboard-holdings-metric"):
                                    with ui.column().classes("gap-1"):
                                        with ui.element("span").classes(
                                            "dashboard-holdings-peer-stat tabular-nums"
                                        ):
                                            ui.icon("emergency", size="14px").classes("text-red-600")
                                            ui.label(
                                                render_message("dashboard.metric.vital_records",count=owner_count["vital_record_count"])
                                            )
                                        with ui.element("span").classes(
                                            "dashboard-holdings-peer-stat tabular-nums"
                                        ):
                                            ui.icon("storage", size="14px").classes("text-primary")
                                            ui.label(
                                                render_message("dashboard.metric.storage",size=format_file_size(owner_count["storage_size_in_bytes"]))
                                            )
                else:
                    ui.label(
                        render_message("webui.load_dashboard.label.no_organizational_unit_holdings_are_availa_d64b09bd")
                    ).classes("text-sm text-slate-500")

                overdue_reviews = summary.get("overdue_reviews", [])
                upcoming_reviews = summary.get("upcoming_reviews", [])
                ui.label(render_message("webui.load_dashboard.label.review_reminders_8c1908c3")).classes("text-lg font-semibold mt-2")
                ui.label(
                    render_message("dashboard.review.window_guidance",days=summary.get("review_warning_window_days",30))
                ).classes("text-sm text-slate-500 -mt-1")
                overdue_total = int(summary["overdue_review_count"])
                upcoming_total = int(summary["upcoming_review_count"])
                review_total = overdue_total + upcoming_total
                overdue_percent = (overdue_total / review_total * 100) if review_total else 0
                donut_background = (
                    "conic-gradient(#d64b5f 0 "
                    f"{overdue_percent:.2f}%, #d99b32 {overdue_percent:.2f}% 100%)"
                    if review_total else "#e2e8f0"
                )
                with ui.element("div").classes("dashboard-review-layout"):
                    with ui.card().classes("dashboard-review-summary").props(
                        'aria-label=' + repr(render_message("webui.load_dashboard.accessible_name.review_urgency_summary_2750f795"))
                    ):
                        ui.label(render_message("webui.load_dashboard.label.review_urgency_561cf02e")).classes(
                            "text-sm font-semibold text-slate-700"
                        )
                        with ui.element("div").classes("dashboard-review-donut").style(
                            f"background: {donut_background}"
                        ):
                            with ui.element("div").classes("dashboard-review-donut-center"):
                                ui.label(str(review_total)).classes(
                                    "dashboard-review-donut-total"
                                )
                                ui.label(render_message("webui.load_dashboard.label.need_review_323554bd")).classes(
                                    "dashboard-review-donut-caption"
                                )
                        with ui.column().classes("w-full gap-2"):
                            for label, value, color in (
                                (render_message("dashboard.review.overdue"), overdue_total, "#d64b5f"),
                                (
                                    render_message("dashboard.review.next_days",days=summary.get("review_warning_window_days",30)),
                                    upcoming_total,
                                    "#d99b32",
                                ),
                            ):
                                with ui.element("div").classes(
                                    "dashboard-review-summary-row"
                                ):
                                    ui.element("i").classes("dashboard-chart-swatch").style(
                                        f"background: {color}"
                                    )
                                    ui.label(label)
                                    ui.label(str(value)).classes(
                                        "dashboard-review-summary-value"
                                    )
                    with ui.element("div").classes("dashboard-review-columns"):
                        for heading, items, color, empty in (
                            ("overdue", overdue_reviews, "negative", render_message("dashboard.review.none_overdue")),
                            ("upcoming", upcoming_reviews, "warning", render_message("dashboard.review.none_upcoming")),
                        ):
                            with ui.card().classes("dashboard-review-group"):
                                with ui.row().classes("dashboard-review-header w-full items-center gap-2"):
                                    ui.icon(
                                        "error_outline" if heading == "overdue" else "event",
                                        color=color,
                                        size="19px",
                                    )
                                    ui.label(render_message("dashboard.review.overdue") if heading == "overdue" else render_message("dashboard.review.upcoming")).classes("font-semibold")
                                    total = summary["overdue_review_count" if heading == "overdue" else "upcoming_review_count"]
                                    ui.badge(str(total), color=color).props("outline")
                                    ui.space()
                                    ui.button(
                                        render_message("webui.load_dashboard.button.view_all_260c05da"), icon="arrow_forward",
                                        on_click=lambda _, kind=heading.lower(): show_all_reviews(kind),
                                    ).props("flat dense no-caps color=primary")
                                if not items:
                                    ui.label(empty).classes("text-sm text-slate-400 px-3 py-4")
                                for item in items:
                                    resource = "aggregations" if item["entity_type"] == "aggregation" else "records"
                                    number = item.get("aggregation_number") or item.get("record_number")
                                    review_item = ui.element("div").classes(
                                        "dashboard-review-item"
                                    ).props("role=button tabindex=0")
                                    review_item.on(
                                        "click",
                                        lambda _, row=item, kind=resource: open_dashboard_resource(
                                            kind, {"id": row["entity_id"]}
                                        ),
                                    )
                                    review_item.on(
                                        "keydown.enter",
                                        lambda _, row=item, kind=resource: open_dashboard_resource(
                                            kind, {"id": row["entity_id"]}
                                        ),
                                    )
                                    with review_item:
                                        with ui.element("div").classes("dashboard-overview-icon"):
                                            ui.icon(
                                                "folder" if resource == "aggregations" else "description",
                                                size="18px",
                                            )
                                        with ui.column().classes("gap-0 grow min-w-0"):
                                            ui.label(item["title"]).classes(
                                                "text-sm font-semibold text-slate-700 truncate w-full"
                                            ).tooltip(item["title"])
                                            ui.label(
                                                render_message("dashboard.resource.identity",type=dashboard_resource_type(resource),number=number)
                                            ).classes("text-xs text-slate-500 truncate w-full")
                                        ui.label(
                                            format_timestamp(item["date_of_next_review"])
                                        ).classes(
                                            f"dashboard-review-date text-xs font-medium text-{color}"
                                        )
                                if total > len(items):
                                    ui.label(render_message("dashboard.result.showing",shown=len(items),total=total)).classes(
                                        "text-xs text-slate-500 self-end px-3 py-2"
                                    )

                if unclassified_root_count or inactive_classification_count:
                    ui.label(render_message("webui.load_dashboard.label.governance_attention_de7138ce")).classes("text-lg font-semibold mt-2")
                    with ui.row().classes("w-full gap-3 flex-wrap"):
                        if unclassified_root_count:
                            with ui.card().classes(
                                "grow min-w-[280px] cursor-pointer shadow-none border "
                                "border-red-200 bg-red-50 p-4"
                            ).on("click", show_unclassified_roots):
                                with ui.row().classes("items-center gap-3 no-wrap"):
                                    ui.avatar(icon="folder_off", color="red-1", text_color="negative")
                                    with ui.column().classes("gap-0"):
                                        ui.label(str(unclassified_root_count)).classes("text-xl font-bold text-negative")
                                        ui.label(render_message("webui.load_dashboard.label.unclassified_root_aggregations_efcbac0c")).classes("font-semibold")
                                        ui.label(render_message("webui.load_dashboard.label.root_aggregations_require_a_governing_clas_20cf1244")).classes("text-xs text-slate-500")
                        if inactive_classification_count:
                            with ui.card().classes(
                                "grow min-w-[280px] cursor-pointer shadow-none border "
                                "border-amber-200 bg-amber-50 p-4"
                            ).on("click", select_classification_workspace):
                                with ui.row().classes("items-center gap-3 no-wrap"):
                                    ui.avatar(icon="label_off", color="amber-1", text_color="amber-9")
                                    with ui.column().classes("gap-0"):
                                        ui.label(str(inactive_classification_count)).classes("text-xl font-bold text-amber-900")
                                        ui.label(render_message("webui.load_dashboard.label.inactive_classifications_4ca99653")).classes("font-semibold")
                                        ui.label(render_message("webui.load_dashboard.label.unavailable_for_new_aggregation_assignment_9e25cb2c")).classes("text-xs text-slate-500")

                favourites_area: Any = None

                def combined_favourites() -> list[dict[str, Any]]:
                    combined = [
                        {**item, "_resource": resource}
                        for resource in ("aggregations", "records")
                        for item in favourites[resource]
                    ]
                    return sorted(
                        combined,
                        key=lambda item: str(item.get("date_favourited") or ""),
                        reverse=True,
                    )

                def render_favourite_entry(
                    resource: str, item: dict[str, Any], *, after_remove: Any,
                ) -> None:
                    icon = "folder" if resource == "aggregations" else "description"
                    favourite_row = ui.element("div").classes(
                        "dashboard-personal-item"
                    ).props("role=button tabindex=0").on(
                        "click",
                        lambda _, selected=item, kind=resource: open_dashboard_resource(kind, selected),
                    ).on(
                        "keydown.enter",
                        lambda _, selected=item, kind=resource: open_dashboard_resource(kind, selected),
                    )
                    with favourite_row:
                        with ui.element("div").classes("dashboard-overview-icon"):
                            ui.icon(icon, size="18px")
                        with ui.column().classes("gap-0 grow min-w-0"):
                            ui.label(item["title"]).classes(
                                "text-sm font-semibold text-slate-700 truncate w-full"
                            ).tooltip(item["title"])
                            number = item.get("aggregation_number") or item.get("record_number")
                            resource_label = dashboard_resource_type(resource)
                            ui.label(render_message("dashboard.resource.identity",type=resource_label,number=number)).classes(
                                "text-xs text-slate-500 truncate w-full"
                            )
                        remove_button = ui.button(
                            icon="favorite", color="red",
                        ).props('flat round dense aria-label=' + repr(render_message("webui.render_favourite_entry.accessible_name.remove_from_favourites_40670952")))
                        remove_button.tooltip(render_message("webui.render_favourite_entry.tooltip.remove_from_favourites_dc2403f2"))
                        remove_button.on(
                            "click",
                            lambda _, selected=item, kind=resource: after_remove(kind, selected),
                            js_handler=STOP_PROPAGATION_CLICK_HANDLER,
                        )

                async def remove_dashboard_favourite(
                    resource: str, item: dict[str, Any], *, dialog_refresh: Any | None = None,
                ) -> None:
                    if not dashboard_view_is_current():
                        return
                    try:
                        await api.unfavourite(resource, item["id"])
                        if not dashboard_view_is_current():
                            return
                        favourites[resource] = [
                            entry for entry in favourites[resource]
                            if entry["id"] != item["id"]
                        ]
                        personal.favourites = favourites
                        personal.favourite_ids[resource].discard(int(item["id"]))
                        render_favourites_dashboard()
                        if dialog_refresh is not None:
                            dialog_refresh()
                        # Both lists may have removed the originating event's row.
                        with favourites_area:
                            ui.notify(render_message("webui.remove_dashboard_favourite.notify.removed_from_favourites_6953809b"), color="positive")
                    except ApiError as error:
                        if not dashboard_view_is_current():
                            return
                        ui.notify(error_message(error), color="negative", close_button=True)

                def show_all_favourites() -> None:
                    if not dashboard_view_is_current():
                        return
                    dialog = ui.dialog()
                    with dialog, ui.card().classes(
                        "dashboard-personal-dialog w-[760px] max-w-full max-h-[85vh]"
                    ):
                        with ui.row().classes("w-full items-center"):
                            ui.label(render_message("webui.show_all_favourites.label.favourites_f9033752")).classes("text-xl font-semibold")
                            ui.space()
                            ui.button(icon="close", on_click=dialog.close).props("flat round")
                        complete_list = (
                            ui.scroll_area()
                            .classes("dashboard-personal-dialog-list")
                            .props("visible")
                            .style(
                                f"height:min(65vh,{personal_dialog_list_height(len(combined_favourites()))}px)"
                            )
                        )

                    def render_complete_list() -> None:
                        complete_list.clear()
                        with complete_list:
                            all_favourites = combined_favourites()
                            if not all_favourites:
                                ui.label(render_message("webui.render_complete_list.label.no_favourites_8952ca8c")).classes("text-sm text-slate-400 p-4")
                            for item in all_favourites:
                                render_favourite_entry(
                                    item["_resource"], item,
                                    after_remove=lambda kind, selected: remove_dashboard_favourite(
                                        kind, selected, dialog_refresh=render_complete_list,
                                    ),
                                )

                    render_complete_list()
                    dialog.open()

                def render_favourites_dashboard() -> None:
                    favourites_area.clear()
                    with favourites_area:
                        with ui.card().classes("dashboard-personal-panel"):
                            with ui.row().classes(
                                "dashboard-personal-header w-full items-center gap-2"
                            ):
                                ui.icon("favorite_border", color="primary", size="19px")
                                ui.label(render_message("webui.render_favourites_dashboard.label.favourites_a1c0758b")).classes("font-semibold text-slate-800")
                                total_favourites = sum(len(favourites[key]) for key in ("aggregations", "records"))
                                ui.badge(str(total_favourites), color="blue-grey").props("outline")
                                ui.space()
                                ui.button(
                                    render_message("webui.render_favourites_dashboard.button.view_all_e1f7fcfb"), on_click=show_all_favourites,
                                ).props("flat dense no-caps color=primary")
                            all_favourites = combined_favourites()
                            if not all_favourites:
                                ui.label(
                                    render_message("webui.render_favourites_dashboard.label.you_haven_t_added_any_favourites_yet_selec_9fcb89ef")
                                ).classes("text-sm text-slate-500 p-4")
                            for item in all_favourites[:favourite_limit]:
                                render_favourite_entry(
                                    item["_resource"], item, after_remove=remove_dashboard_favourite,
                                )

                def render_recent_record_entry(item: dict[str, Any]) -> None:
                    operation = item["_operation"]
                    activity_label, activity_icon, activity_class = {
                        "CREATE": (render_message("dashboard.activity.created"), "add", "dashboard-activity-created"),
                        "UPDATE": (render_message("dashboard.activity.updated"), "edit", "dashboard-activity-updated"),
                        "CONTENT_VIEWED": (render_message("dashboard.activity.viewed"), "visibility", "dashboard-activity-viewed"),
                    }[operation]
                    activity_row = ui.element("div").classes(
                        "dashboard-personal-item"
                    ).props("role=button tabindex=0").on(
                        "click", lambda _, entry=item: open_dashboard_resource("records", entry),
                    ).on(
                        "keydown.enter", lambda _, entry=item: open_dashboard_resource("records", entry),
                    )
                    with activity_row:
                        with ui.element("div").classes("dashboard-overview-icon"):
                            ui.icon("description", size="18px")
                        with ui.column().classes("gap-0 grow min-w-0"):
                            ui.label(item["title"]).classes(
                                "text-sm font-semibold text-slate-700 truncate w-full"
                            ).tooltip(item["title"])
                            ui.label(
                                render_message("webui.render_recent_record_entry.label.value_format_timestamp_a3b124e0", value=item.get('record_number') or '—', format_timestamp=format_timestamp(item['_activity_at']))
                            ).classes("text-xs text-slate-500 truncate w-full")
                        with ui.element("div").classes(
                            f"dashboard-activity-badge {activity_class}"
                        ):
                            ui.icon(activity_icon, size="13px")
                            ui.label(activity_label)

                def show_all_recent_records() -> None:
                    if not dashboard_view_is_current():
                        return
                    dialog = ui.dialog()
                    with dialog, ui.card().classes(
                        "dashboard-personal-dialog w-[820px] max-w-full max-h-[85vh]"
                    ):
                        with ui.row().classes("w-full items-center"):
                            ui.label(render_message("webui.show_all_recent_records.label.recent_records_activity_3b1a4c9d")).classes("text-xl font-semibold")
                            ui.space()
                            ui.button(icon="close", on_click=dialog.close).props("flat round")
                        with (
                            ui.scroll_area()
                            .classes("dashboard-personal-dialog-list")
                            .props("visible")
                            .style(
                                f"height:min(65vh,{personal_dialog_list_height(len(all_recent_records))}px)"
                            )
                        ):
                            if not all_recent_records:
                                ui.label(render_message("webui.show_all_recent_records.label.no_recent_records_activity_0ecddb69")).classes("text-sm text-slate-400 p-4")
                            for item in all_recent_records:
                                render_recent_record_entry(item)
                    dialog.open()

                with personal_sections_area:
                    with ui.element("div").classes("dashboard-personal-columns mt-2"):
                        favourites_area = ui.element("div").classes("w-full")
                        render_favourites_dashboard()
                        with ui.card().classes("dashboard-personal-panel"):
                            with ui.row().classes(
                                "dashboard-personal-header w-full items-center gap-2"
                            ):
                                ui.icon("history", color="primary", size="19px")
                                ui.label(render_message("webui.load_dashboard.label.recent_records_activity_5200d38a")).classes("font-semibold text-slate-800")
                                ui.space()
                                ui.button(
                                    render_message("webui.load_dashboard.button.view_all_260c05da"), on_click=show_all_recent_records,
                                ).props("flat dense no-caps color=primary")
                            if not recent_records:
                                ui.label(
                                    render_message("dashboard.recent.empty",days=recent_days)
                                ).classes("text-sm text-slate-500 p-4")
                            for item in recent_records:
                                render_recent_record_entry(item)

                ui.label(render_message("webui.load_dashboard.label.digital_storage_by_organizational_unit_e4533a05")).classes(
                    "text-lg font-semibold mt-2"
                )
                ui.label(
                    render_message("webui.load_dashboard.label.largest_authorized_storage_totals_among_un_e603dcd3")
                ).classes("text-sm text-slate-500 -mt-1")
                ranked_storage_units = sorted(
                    ownership_counts,
                    key=lambda item: (
                        -int(item["storage_size_in_bytes"]),
                        str(item["org_unit_name"]),
                        int(item["org_unit_id"]),
                    ),
                )
                top_storage_units = ranked_storage_units[:5]
                other_storage_units = ranked_storage_units[5:]
                total_storage_bytes = sum(
                    int(item["storage_size_in_bytes"]) for item in ranked_storage_units
                )
                maximum_unit_storage = max(
                    (int(item["storage_size_in_bytes"]) for item in top_storage_units),
                    default=1,
                ) or 1
                with ui.element("section").classes("dashboard-storage-chart").props(
                    'aria-label=' + repr(render_message("webui.load_dashboard.accessible_name.top_five_organizational_units_by_authorize_cfc7c0c5"))
                ):
                    with ui.row().classes("w-full items-start gap-3"):
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(render_message("webui.load_dashboard.label.top_organizational_units_22b57918")).classes(
                                "text-sm font-semibold text-slate-700"
                            )
                            ui.label(
                                render_message("dashboard.storage.units_shown",shown=len(top_storage_units),total=len(ranked_storage_units))
                            ).classes("text-xs text-slate-500")
                        ui.space()
                        with ui.column().classes("items-end gap-0 shrink-0"):
                            ui.label(format_file_size(total_storage_bytes)).classes(
                                "text-lg font-bold text-slate-800 tabular-nums"
                            )
                            ui.label(render_message("webui.load_dashboard.label.authorized_storage_dc78b6fc")).classes(
                                "text-[10px] text-slate-500"
                            )
                    if not ranked_storage_units:
                        ui.label(
                            render_message("webui.load_dashboard.label.no_organizational_unit_storage_is_availabl_a6019705")
                        ).classes("text-sm text-slate-500 py-4")
                    else:
                        with ui.element("div").classes("dashboard-storage-chart-rows"):
                            for owner_count in top_storage_units:
                                storage_bytes = int(owner_count["storage_size_in_bytes"])
                                bar_width = (storage_bytes / maximum_unit_storage) * 100
                                share = (
                                    (storage_bytes / total_storage_bytes) * 100
                                    if total_storage_bytes else 0
                                )
                                with ui.element("div").classes(
                                    "dashboard-storage-chart-row"
                                ):
                                    ui.label(owner_count["org_unit_name"]).classes(
                                        "dashboard-storage-chart-name"
                                    ).tooltip(owner_count["org_unit_name"])
                                    with ui.element("div").classes(
                                        "dashboard-storage-chart-track"
                                    ):
                                        ui.element("div").classes(
                                            "dashboard-storage-chart-bar"
                                        ).style(f"width: {bar_width:.2f}%")
                                    with ui.column().classes("items-end gap-0"):
                                        ui.label(format_file_size(storage_bytes)).classes(
                                            "dashboard-storage-chart-value"
                                        )
                                        ui.label(render_message("webui.load_dashboard.label.share_06671928", share=format(share, '.1f'))).classes(
                                            "dashboard-storage-chart-share"
                                        )
                            if other_storage_units:
                                other_storage_bytes = sum(
                                    int(item["storage_size_in_bytes"])
                                    for item in other_storage_units
                                )
                                other_share = (
                                    (other_storage_bytes / total_storage_bytes) * 100
                                    if total_storage_bytes else 0
                                )
                                with ui.element("div").classes(
                                    "dashboard-storage-chart-row dashboard-storage-other"
                                ):
                                    ui.label(
                                        render_message("dashboard.storage.other_units",count=len(other_storage_units))
                                    ).classes("dashboard-storage-chart-name")
                                    ui.label(render_message("webui.load_dashboard.label.combined_remainder_df5fa70b")).classes(
                                        "dashboard-storage-other-summary"
                                    )
                                    with ui.column().classes("items-end gap-0"):
                                        ui.label(format_file_size(other_storage_bytes)).classes(
                                            "dashboard-storage-chart-value"
                                        )
                                        ui.label(render_message("webui.load_dashboard.label.other_share_36b8a00f", other_share=format(other_share, '.1f'))).classes(
                                            "dashboard-storage-chart-share"
                                        )
                set_connection_status(True)

        cached_summary = dashboard_state.get("dashboard_summary_cache")
        if (
            dashboard_state.get("dashboard_summary_cache_key") == dashboard_key
            and isinstance(cached_summary, dict) and cached_summary
        ):
            await load_dashboard(summary_override=cached_summary)
            background_tasks.create(load_dashboard(refresh_only=True))
        else:
            await load_dashboard()


    return dashboard_session_key, clear_dashboard_session, select_dashboard
