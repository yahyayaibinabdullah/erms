"""Login-session administration; paging and confirmations belong to each open view.

The host supplies shell entry and the existing current-session cleanup sequence.
This owner has no application-state dictionary, persistent cache or route.
"""
from __future__ import annotations
from typing import Any, Callable
from nicegui import ui
from .api_client import ApiError
from .i18n_catalogue import render_message


def build_login_sessions(
    api, *, table_container, enter: Callable, principal: Callable,
    current_session_revoked: Callable, render_user_avatar: Callable,
    format_timestamp: Callable, localized_lifecycle_value: Callable, error_message: Callable,
):
    async def select_login_sessions(user_id: int | None = None) -> None:
        enter(user_id)
        with table_container:
            outer = ui.column().classes("w-full p-5 gap-4")

        page_state = {"offset": 0, "total": 0, "active": 0, "loading": False}
        with outer:
            with ui.card().classes("w-full shadow-none border border-slate-200 p-4 gap-3"):
                ui.label(render_message("webui.select_login_sessions.label.filter_sessions_aa1ab045")).classes("font-semibold")
                with ui.element("div").classes("hold-held-item-filter-primary w-full"):
                    session_filter = ui.input(
                        render_message("webui.select_login_sessions.input.user_or_client_e41c0521"), placeholder=render_message("webui.select_login_sessions.input.name_email_ip_address_or_browser_d1aeccf0"),
                    ).props("outlined dense clearable").classes("w-full col-span-2")
                    status_filter = ui.select(
                        {"all": render_message("webui.select_login_sessions.select.all_statuses_34d5de11"), "active": render_message("webui.select_login_sessions.select.active_36219838"), "expired": render_message("webui.select_login_sessions.select.expired_4f6360cb"), "revoked": render_message("webui.select_login_sessions.select.revoked_c6e031f9")},
                        value="all", label=render_message("webui.select_login_sessions.select.status_de37c9ef"),
                    ).props("outlined dense options-dense").classes("w-full")
                    sort_filter = ui.select(
                        {"date_created": render_message("webui.select_login_sessions.select.signed_in_54f907f7"), "last_seen_at": render_message("webui.select_login_sessions.select.last_activity_cd341923"), "expires_at": render_message("webui.select_login_sessions.select.expiry_252f7b7d"), "status": render_message("webui.select_login_sessions.select.status_de37c9ef"), "client_ip": render_message("webui.select_login_sessions.select.ip_address_ebf48f5f")},
                        value="date_created", label=render_message("webui.select_login_sessions.select.sort_by_bc12d82d"),
                    ).props("outlined dense options-dense").classes("w-full")
                    timestamp_field = ui.select(
                        {"date_created": render_message("webui.select_login_sessions.select.signed_in_54f907f7"), "last_seen_at": render_message("webui.select_login_sessions.select.last_activity_cd341923")},
                        label=render_message("webui.select_login_sessions.select.date_field_3d55a2d9"), value="date_created",
                    ).props("outlined dense options-dense").classes("w-full")
                    from_filter = ui.input(render_message("webui.select_login_sessions.input.from_d21e44c1")).props("outlined dense clearable type=datetime-local").classes("w-full")
                    until_filter = ui.input(render_message("webui.select_login_sessions.input.to_fe61918d")).props("outlined dense clearable type=datetime-local").classes("w-full")
                    direction_filter = ui.select(
                        {True: render_message("webui.select_login_sessions.select.newest_descending_f99e885f"), False: render_message("webui.select_login_sessions.select.oldest_ascending_a4172995")},
                        value=True, label=render_message("webui.select_login_sessions.select.direction_784704c5"),
                    ).props("outlined dense options-dense").classes("w-full")
                filter_actions = ui.row().classes("w-full justify-end gap-2")
            with ui.row().classes("w-full items-center"):
                result_summary = ui.label().classes("text-sm text-slate-500")
                ui.space()
                refresh_button = ui.button(render_message("webui.select_login_sessions.button.refresh_85d6e787"), icon="refresh").props("flat no-caps")
            results = ui.element("div").classes("login-session-card-grid w-full")
            empty_state = ui.label(render_message("webui.select_login_sessions.label.no_login_sessions_match_these_filters_2c8578fd")).classes(
                "w-full text-center text-slate-400 py-12"
            )
            with ui.row().classes("w-full items-center gap-3"):
                page_range = ui.label().classes("text-sm text-slate-500")
                ui.space()
                rows_per_page = ui.select({20: "20", 50: "50", 100: "100"}, value=20, label=render_message("webui.select_login_sessions.select.per_page_a942866a")).props("outlined dense options-dense").classes("w-28")
                first_page = ui.button(render_message("webui.select_login_sessions.button.first_3e9443bf"), icon="first_page").props("flat dense no-caps")
                previous_page = ui.button(render_message("webui.select_login_sessions.button.previous_6631329f"), icon="chevron_left").props("flat dense no-caps")
                next_page = ui.button(render_message("webui.select_login_sessions.button.next_b09718d5"), icon="chevron_right").props("flat dense no-caps")
                last_page = ui.button(render_message("webui.select_login_sessions.button.last_5cfe5c95"), icon="last_page").props("flat dense no-caps")

        def client_summary(user_agent: str | None) -> tuple[str, str]:
            value = user_agent or render_message("webui.client_summary.text.unknown_client_a90618da")
            browser = next((name for token, name in (("Edg/", "Microsoft Edge"), ("Chrome/", "Google Chrome"), ("Firefox/", "Mozilla Firefox"), ("Safari/", "Safari")) if token in value), "Browser")
            platform = next((name for token, name in (("Macintosh", "macOS"), ("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iOS"), ("Linux", "Linux")) if token in value), "Unknown platform")
            return browser, platform

        async def confirm_revoke(row: dict[str, Any], *, all_for_user: bool = False) -> None:
            confirmation = ui.dialog()
            with confirmation, ui.card().classes("w-[460px] max-w-full"):
                ui.label(render_message("webui.confirm_revoke.label.force_sign_out_fdc134c3")).classes("text-xl font-semibold")
                scope = "all active sessions for" if all_for_user else "this session for"
                ui.label(render_message("webui.confirm_revoke.label.this_will_immediately_revoke_scope_user_na_d568e325", scope=scope, user_name=row['user_name'])).classes("text-sm text-slate-600")

                async def proceed() -> None:
                    confirmation.close()
                    try:
                        if all_for_user:
                            await api.revoke_user_sessions(row["user_id"])
                        else:
                            await api.revoke_session(row["id"])
                        if row.get("is_current"):
                            current_session_revoked()
                        else:
                            ui.notify(render_message("webui.proceed.notify.session_revoked_69e45d5b"), color="positive")
                            await load_sessions()
                    except ApiError as error:
                        ui.notify(error_message(error), color="negative")

                with ui.row().classes("w-full justify-end"):
                    ui.button(render_message("webui.confirm_revoke.button.cancel_9fc0545b"), on_click=confirmation.close).props("flat")
                    ui.button(render_message("webui.confirm_revoke.button.force_sign_out_e02eacd0"), icon="logout", color="negative", on_click=proceed).props("unelevated no-caps")
            confirmation.open()

        def render_session_card(row: dict[str, Any], *, can_revoke_all: bool) -> None:
            browser, platform = client_summary(row.get("user_agent"))
            with ui.card().classes("login-session-card shadow-none"):
                with ui.row().classes("w-full items-start no-wrap gap-3"):
                    render_user_avatar({"id": row.get("user_id"), "name": row.get("user_name"), "email": row.get("user_email")}, size="40px")
                    with ui.column().classes("gap-0 min-w-0 grow"):
                        ui.label(row.get("user_name") or render_message("webui.render_session_card.label.unknown_user_acc76adf")).classes("font-semibold leading-tight")
                        ui.label(row.get("user_email") or render_message("webui.render_session_card.label.no_email_address_ab665b8b")).classes("text-xs text-slate-500 truncate w-full").tooltip(row.get("user_email") or render_message("webui.render_session_card.tooltip.no_email_address_be875868"))
                        if row.get("is_current"):
                            ui.badge(render_message("webui.render_session_card.badge.current_session_01ba47c6"), color="primary").props("outline").classes("mt-1")
                    ui.badge(
                        localized_lifecycle_value(row.get("status")),
                        color={
                            "active": "positive", "revoked": "negative",
                            "expired": "grey-7",
                        }.get(row.get("status"), "grey-7"),
                    ).props("outline")
                with ui.grid(columns=3).classes("w-full gap-x-4 gap-y-3"):
                    session_facts = (
                        (render_message("webui.render_session_card.text.signed_in_74099f59"), format_timestamp(row.get("date_created"))),
                        (render_message("webui.render_session_card.text.last_activity_d18059ae"), format_timestamp(row.get("last_seen_at"))),
                        (render_message("webui.render_session_card.text.expires_af4d4f10"), format_timestamp(row.get("expires_at"))),
                        (render_message("webui.render_session_card.text.ip_address_c3b3a584"), row.get("client_ip") or "—"),
                        (render_message("webui.render_session_card.text.platform_015c8cc7"), platform), (render_message("webui.render_session_card.text.browser_126852df"), browser),
                    )
                    for label, value in session_facts:
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(label).classes("detail-field-label")
                            ui.label(value).classes("text-xs truncate w-full").tooltip(value)
                with ui.row().classes("w-full items-center no-wrap border-t border-slate-100 pt-2 gap-2"):
                    ui.icon("devices", color="primary", size="18px")
                    ui.label(row.get("user_agent") or render_message("webui.render_session_card.label.unknown_client_c63ac50c")).classes("text-xs text-slate-500 truncate grow").tooltip(row.get("user_agent") or render_message("webui.render_session_card.tooltip.unknown_client_b07bbf57"))
                    if row.get("status") == "active":
                        ui.button(icon="logout", on_click=lambda _, item=row: confirm_revoke(item)).props("outline dense color=negative").classes("login-session-action-button").tooltip(render_message("webui.render_session_card.tooltip.force_sign_out_this_session_3882517f"))
                        if can_revoke_all:
                            ui.button(icon="person_off", on_click=lambda _, item=row: confirm_revoke(item, all_for_user=True)).props("outline dense color=negative").classes("login-session-action-button").tooltip(render_message("webui.render_session_card.tooltip.force_sign_out_all_sessions_for_this_user_27a3671e"))

        async def load_sessions(*, reset: bool = False) -> None:
            if page_state["loading"]:
                return
            if reset:
                page_state["offset"] = 0
            page_state["loading"] = True
            results.clear()
            empty_state.set_visibility(False)
            with results:
                for _ in range(4):
                    ui.skeleton(type="rect").classes("h-48 rounded-xl")
            try:
                page = await api.login_sessions_page(
                    user_id, limit=int(rows_per_page.value), offset=page_state["offset"],
                    query=(session_filter.value or "").strip(),
                    session_status=status_filter.value or "all",
                    sort_by=sort_filter.value or "date_created",
                    descending=bool(direction_filter.value),
                    date_field=timestamp_field.value or "date_created",
                    from_timestamp=from_filter.value or None,
                    until_timestamp=until_filter.value or None,
                )
            except ApiError as error:
                ui.notify(error_message(error), color="negative")
                return
            finally:
                page_state["loading"] = False
            rows = page.get("items", [])
            page_state.update(total=int(page.get("total", 0)), active=int(page.get("active", 0)))
            if page_state["offset"] >= page_state["total"] and page_state["offset"]:
                page_state["offset"] = max(0, ((page_state["total"] - 1) // int(rows_per_page.value)) * int(rows_per_page.value))
                await load_sessions()
                return
            results.clear()
            can_revoke_all = "identity.sessions.administer" in set(principal().get("global_privileges", []))
            with results:
                for row in rows:
                    render_session_card(row, can_revoke_all=can_revoke_all)
            empty_state.set_visibility(not rows)
            start = page_state["offset"] + 1 if rows else 0
            end = page_state["offset"] + len(rows)
            result_summary.text = render_message("webui.load_sessions.text.total_sessions_active_active_bf830d8b", total=page_state['total'], active=page_state['active'])
            page_range.text = render_message("webui.load_sessions.text.showing_start_end_of_total_sessions_5362e794", start=start, end=end, total=page_state['total'])
            at_start = page_state["offset"] == 0
            at_end = end >= page_state["total"]
            first_page.set_enabled(not at_start); previous_page.set_enabled(not at_start)
            next_page.set_enabled(not at_end); last_page.set_enabled(not at_end)

        async def clear_session_filters() -> None:
            session_filter.value = ""; status_filter.value = "all"; sort_filter.value = "date_created"
            timestamp_field.value = "date_created"; from_filter.value = ""; until_filter.value = ""; direction_filter.value = True
            for control in (session_filter, status_filter, sort_filter, timestamp_field, from_filter, until_filter, direction_filter):
                control.update()
            await load_sessions(reset=True)

        with filter_actions:
            ui.button(render_message("webui.select_login_sessions.button.clear_7925d8e0"), icon="filter_alt_off", on_click=clear_session_filters).props("flat dense no-caps")
            ui.button(render_message("webui.select_login_sessions.button.apply_filters_fc2322aa"), icon="filter_alt", on_click=lambda: load_sessions(reset=True)).props("unelevated dense no-caps")
        refresh_button.on("click", load_sessions)
        session_filter.on("keydown.enter", lambda: load_sessions(reset=True))
        rows_per_page.on_value_change(lambda: load_sessions(reset=True))

        async def go_to_offset(offset: int) -> None:
            page_state["offset"] = max(0, offset)
            await load_sessions()

        first_page.on("click", lambda: go_to_offset(0))
        previous_page.on("click", lambda: go_to_offset(page_state["offset"] - int(rows_per_page.value)))
        next_page.on("click", lambda: go_to_offset(page_state["offset"] + int(rows_per_page.value)))
        last_page.on("click", lambda: go_to_offset(((page_state["total"] - 1) // int(rows_per_page.value)) * int(rows_per_page.value)))
        await load_sessions()


    return select_login_sessions
