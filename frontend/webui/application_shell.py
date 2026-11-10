"""Construction of the existing per-client shell; feature state stays outside."""
from dataclasses import dataclass
from typing import Any, Callable

from nicegui import ui

from .disposition.messages import text as disposition_text
from .config import database_display_name
from .i18n_catalogue import render_message


@dataclass(frozen=True)
class HeaderControls:
    brand_mark: Any
    brand_name: Any
    brand_row: Any
    change_password_menu: Any
    current_user_avatar: Any
    current_user_avatar_initials: Any
    current_user_email: Any
    current_user_last_login: Any
    current_user_name: Any
    current_user_roles: Any
    diagnostics_section: Any
    diagnostics_separator: Any
    global_search_input: Any
    global_search_submit: Any
    global_search_wrap: Any
    header_network: Any
    inspector_bridge: Any
    inspector_switch: Any
    message_unread_button: Any
    preferences_menu: Any
    shell_header: Any
    sign_out_menu: Any
    user_menu: Any


def build_header(*, q: str, select_messages: Callable, avatar_background: str, avatar_text: str) -> HeaderControls:
    with ui.header().classes("erms-header items-center gap-3") as shell_header:
        header_network = ui.element("canvas").classes(
            "wathiq-network-canvas wathiq-header-network"
        ).props("aria-hidden=true")
        header_network.set_visibility(False)
        with ui.row().classes("erms-brand items-center no-wrap").props('aria-label=' + repr(render_message("webui.index.accessible_name.wathiq_faa0862c"))) as brand_row:
            brand_mark = ui.image("/static/brand/wathiq-mark.svg?v=2").classes("erms-brand-mark").props(
                "fit=contain alt='" + render_message("webui.index.accessible_name.wathiq_faa0862c") + "'"
            )
            brand_name = ui.label(render_message("webui.index.label.wathiq_d1dfb800")).classes("erms-brand-name")
        with ui.row().classes("erms-global-search-wrap no-wrap") as global_search_wrap:
            global_search_input = ui.input(
                placeholder=render_message("webui.index.input.search_records_files_and_aggregations_8808d362"),
            ).props(
                'outlined dense clearable aria-label=' + repr(render_message("webui.index.accessible_name.search_records_files_and_aggregations_f4df7ac8"))
            ).classes("erms-global-search")
            global_search_input.value = q.strip()
            global_search_submit = ui.button(icon="search").props(
                'flat round color=blue-grey-8 aria-label=' + repr(render_message("webui.index.accessible_name.submit_global_search_d3d1329e"))
            ).tooltip(render_message("webui.index.tooltip.search_93d9b9f9"))
        global_search_wrap.set_visibility(False)
        ui.space()
        message_unread_button = ui.button(icon="inbox", on_click=lambda: select_messages("inbox")).props("flat no-caps")
        message_unread_button.set_visibility(False)
        user_menu_button = ui.button(icon="account_circle").props(
            "flat round color=blue-grey-9 data-inspector-ignore=true"
        )
        with user_menu_button, ui.menu() as user_menu:
            with ui.column().classes("erms-profile-menu w-72 p-3 gap-2"):
                with ui.row().classes("erms-profile-identity-row w-full items-center gap-3 no-wrap"):
                    with ui.avatar(size="44px").style(
                        f"background:{avatar_background} !important;"
                        f"color:{avatar_text} !important"
                    ) as current_user_avatar:
                        current_user_avatar_initials = ui.label("?").classes("font-medium")
                    with ui.column().classes("erms-profile-identity-copy gap-0 min-w-0"):
                        current_user_name = ui.label(render_message("webui.index.label.not_signed_in_589ae00f")).classes(
                            "font-semibold line-clamp-1"
                        )
                        current_user_email = ui.label().classes(
                            "erms-profile-email text-xs text-slate-500 line-clamp-1"
                        )
                ui.separator()
                ui.label(render_message("webui.index.label.previous_sign_in_2c39a842")).classes("component-meta-label")
                current_user_last_login = ui.label(render_message("webui.index.label.first_sign_in_63bba234")).classes("text-sm text-slate-600")
                ui.separator()
                ui.label(render_message("webui.index.label.assigned_roles_891e6566")).classes("component-meta-label")
                current_user_roles = ui.column().classes("w-full gap-1")
                ui.separator()
                with ui.column().classes("erms-profile-actions w-full").style(
                    "gap:0 !important;margin:0 !important;padding:0 !important"
                ):
                    preferences_menu = ui.button(
                        render_message("preferences.action.open"), icon="language",
                    ).props("flat dense no-caps align=left").classes(
                        "erms-profile-action w-full"
                    )
                    change_password_menu = ui.button(render_message("webui.index.button.change_password_04ba3d0b"), icon="key").props(
                        "flat dense no-caps align=left"
                    ).classes("erms-profile-action w-full")
                    diagnostics_separator = ui.separator()
                    with ui.column().classes(
                        "erms-profile-diagnostics w-full gap-1"
                    ).props("data-inspector-ignore=true") as diagnostics_section:
                        ui.label(
                            render_message("translation_inspector.menu.diagnostics")
                        ).classes("component-meta-label")
                        inspector_switch = ui.switch(
                            render_message("translation_inspector.menu.toggle"), value=False,
                        ).props("dense color=primary")
                    sign_out_menu = ui.button(render_message("webui.index.button.sign_out_a4610dd4"), icon="logout", color="negative").props(
                        "flat dense no-caps align=left"
                    ).classes("erms-profile-action w-full")
                    diagnostics_separator.set_visibility(False)
                    diagnostics_section.set_visibility(False)

        inspector_bridge = ui.element("div").props(
            "id=translation-inspector-bridge aria-hidden=true"
        ).classes("hidden")

    return HeaderControls(
        brand_mark=brand_mark,
        brand_name=brand_name,
        brand_row=brand_row,
        change_password_menu=change_password_menu,
        current_user_avatar=current_user_avatar,
        current_user_avatar_initials=current_user_avatar_initials,
        current_user_email=current_user_email,
        current_user_last_login=current_user_last_login,
        current_user_name=current_user_name,
        current_user_roles=current_user_roles,
        diagnostics_section=diagnostics_section,
        diagnostics_separator=diagnostics_separator,
        global_search_input=global_search_input,
        global_search_submit=global_search_submit,
        global_search_wrap=global_search_wrap,
        header_network=header_network,
        inspector_bridge=inspector_bridge,
        inspector_switch=inspector_switch,
        message_unread_button=message_unread_button,
        preferences_menu=preferences_menu,
        shell_header=shell_header,
        sign_out_menu=sign_out_menu,
        user_menu=user_menu,
    )


@dataclass(frozen=True)
class FooterControls:
    connection_icon: Any
    connection_tooltip: Any


def build_footer(initial_language: str) -> FooterControls:
    with ui.footer().classes("erms-footer items-center"):
        with ui.icon("cloud_done").classes("text-positive text-lg") as connection_icon:
            connection_tooltip = ui.tooltip(render_message("webui.index.tooltip.connected_f57ac5a8"))
        ui.label(render_message(
            "webui.index.label.database_display_name_31c6f7d2",
            database_name=database_display_name(initial_language),
        )).classes("erms-footer-database")
        ui.space()
        ui.label(render_message("webui.index.label.designed_and_built_by_sharjah_archives_742aec80")).classes("erms-footer-credit")

    return FooterControls(connection_icon, connection_tooltip)


@dataclass(frozen=True)
class DrawerControls:
    application_settings_navigation: Any
    audit_navigation: Any
    custody_navigation: Any
    dashboard_navigation: Any
    drawer: Any
    drawer_headings: Any
    drawer_links: Any
    drawer_sections: Any
    drawer_toggle_button: Any
    drawer_toggle_tooltip: Any
    holds_navigation: Any
    localized_navigation: Any
    navigation: Any
    organization_browser_navigation: Any
    saved_search_administration_navigation: Any
    security_operations_navigation: Any
    sessions_navigation: Any
    text_indexers_navigation: Any


def build_drawer(initial_direction: str) -> DrawerControls:
    drawer_links: list[tuple[Any, str, str]] = []
    drawer_headings: list[Any] = []
    drawer_sections: list[tuple[Any, tuple[str, ...]]] = []

    def drawer_link(
        label: str, icon: str, *, navigation_key: str, extra_classes: str = "",
    ) -> Any:
        button = ui.button(label, icon=icon).props(
            f'flat align=left no-caps aria-label={label!r}'
        ).classes(f"erms-nav-link w-full justify-start px-4 {extra_classes}")
        with button:
            ui.tooltip(label)
        drawer_links.append((button, label, navigation_key))
        return button

    drawer_factory = ui.right_drawer if initial_direction == "rtl" else ui.left_drawer
    with drawer_factory(value=True).props(
        "width=300 mini-width=64 show-if-above"
    ).classes("erms-drawer") as drawer:
        drawer_toggle_button = ui.button(
            icon="chevron_right" if initial_direction == "rtl" else "chevron_left"
        ).props(
            'flat dense aria-label=' + repr(render_message("webui.index.accessible_name.collapse_navigation_b4de6b59"))
        ).classes("erms-drawer-toggle")
        with drawer_toggle_button:
            drawer_toggle_tooltip = ui.tooltip(render_message("webui.index.tooltip.collapse_navigation_abf7124d"))
        navigation: dict[str, Any] = {}
        localized_navigation = {
            "disposition_heading": disposition_text("section"),
            "disposition-eligibility": disposition_text("eligibility"),
            "disposition-jobs": disposition_text("jobs"),
            "disposition-templates": disposition_text("templates"),
            "disposition-tasks": disposition_text("my_tasks"),
            "records_heading": render_message("navigation.section.records"),
            "organization_heading": render_message("navigation.section.organization"),
            "messages_heading": render_message("messaging.navigation.messages"),
            "messages-inbox": render_message("messaging.navigation.inbox"),
            "messages-outbox": render_message("messaging.navigation.outbox"),
            "messages-drafts": render_message("messaging.navigation.drafts"),
            "messages-notifications": render_message("messaging.admin.title"),
            "relationship-types": render_message("relationships.ui.catalogue"),
            "messages-monitor": render_message("messaging.monitor.title"),
            "advanced-search": render_message("navigation.item.advanced_search"),
            "aggregations": render_message("navigation.item.aggregations"),
            "records": render_message("navigation.item.records"),
            "classification-schemes": render_message("navigation.item.classification_schemes"),
            "org-units": render_message("navigation.item.org_units"),
            "roles": render_message("navigation.item.roles"),
            "users": render_message("navigation.item.users"),
        }
        with ui.scroll_area().classes("erms-nav-scroll w-full h-full"):
            with ui.column().classes("w-full gap-0 no-wrap"):
                dashboard_navigation = drawer_link(
                    render_message("navigation.item.dashboard"), "dashboard", navigation_key="dashboard", extra_classes="mt-4",
                )
                for heading_key, entries in (
                    ("records_heading", (("advanced-search", "manage_search"), ("aggregations", "folder"), ("records", "description"), ("classification-schemes", "account_tree"), ("relationship-types", "link"))),
                    ("disposition_heading", (("disposition-tasks", "task_alt"), ("disposition-eligibility", "event_available"), ("disposition-jobs", "work_outline"), ("disposition-templates", "description"))),
                    ("messages_heading", (("messages-inbox", "inbox"), ("messages-outbox", "outbox"), ("messages-drafts", "drafts"), ("messages-monitor", "monitor_heart"), ("messages-notifications", "notifications"))),
                    ("organization_heading", (("org-units", "corporate_fare"), ("roles", "badge"), ("users", "group"))),
                ):
                    heading_control = ui.label(localized_navigation[heading_key]).classes(
                        "erms-nav-heading px-4 pt-5 pb-2"
                    )
                    drawer_headings.append(heading_control)
                    section_keys = tuple(key for key, _ in entries)
                    if heading_key == "organization_heading":
                        organization_browser_navigation = drawer_link(
                            render_message("navigation.item.organization_browser"), "lan", navigation_key="organization-browser",
                        )
                        section_keys = ("organization-browser", *section_keys)
                    drawer_sections.append((heading_control, section_keys))
                    for key, icon in entries:
                        navigation[key] = drawer_link(
                            localized_navigation[key],
                            icon, navigation_key=key,
                        )
                system_heading = ui.label(render_message("webui.index.label.system_administration_53cbe26c")).classes(
                    "erms-nav-heading px-4 pt-5 pb-2"
                )
                drawer_headings.append(system_heading)
                drawer_sections.append((system_heading, (
                    "audit-trail", "login-sessions", "security-operations", "saved-search-administration",
                    "security-levels", "profiles", "governance-custody", "holds",
                    "text-indexers", "translations", "application-settings",
                )))
                text_indexers_navigation = drawer_link(
                    render_message("navigation.item.text_indexers"), "manage_search", navigation_key="text-indexers",
                )
                application_settings_navigation = drawer_link(
                    render_message("navigation.item.application_settings"), "settings", navigation_key="application-settings",
                )
                audit_navigation = drawer_link(
                    render_message("navigation.item.audit_trail"), "manage_history", navigation_key="audit-trail",
                )
                sessions_navigation = drawer_link(
                    render_message("navigation.item.login_sessions"), "devices", navigation_key="login-sessions",
                )
                security_operations_navigation = drawer_link(
                    render_message("navigation.item.security_operations"), "monitor_heart", navigation_key="security-operations",
                )
                saved_search_administration_navigation = drawer_link(
                    render_message("privilege.search.saved_search.administrator.name"),
                    "manage_search", navigation_key="saved-search-administration",
                )
                navigation["security-levels"] = drawer_link(
                    render_message("navigation.item.security_levels"), "security", navigation_key="security-levels",
                )
                navigation["profiles"] = drawer_link(
                    render_message("navigation.item.profiles"), "admin_panel_settings", navigation_key="profiles",
                )
                navigation["translations"] = drawer_link(
                    render_message("navigation.item.translations"), "translate", navigation_key="translations",
                )
                custody_navigation = drawer_link(
                    render_message("navigation.item.governance_custody"), "shield_person", navigation_key="governance-custody",
                )
                holds_navigation = drawer_link(
                    render_message("navigation.item.holds"), "gavel", navigation_key="holds",
                )

    return DrawerControls(
        application_settings_navigation=application_settings_navigation,
        audit_navigation=audit_navigation,
        custody_navigation=custody_navigation,
        dashboard_navigation=dashboard_navigation,
        drawer=drawer,
        drawer_headings=drawer_headings,
        drawer_links=drawer_links,
        drawer_sections=drawer_sections,
        drawer_toggle_button=drawer_toggle_button,
        drawer_toggle_tooltip=drawer_toggle_tooltip,
        holds_navigation=holds_navigation,
        localized_navigation=localized_navigation,
        navigation=navigation,
        organization_browser_navigation=organization_browser_navigation,
        saved_search_administration_navigation=saved_search_administration_navigation,
        security_operations_navigation=security_operations_navigation,
        sessions_navigation=sessions_navigation,
        text_indexers_navigation=text_indexers_navigation,
    )


@dataclass(frozen=True)
class ContentControls:
    add_button: Any
    add_record_button: Any
    aggregation_browse_mode: Any
    aggregation_mode_bar: Any
    aggregation_search_mode: Any
    breadcrumb_host: Any
    content_card: Any
    guidance: Any
    page_title_icon: Any
    search_bar: Any
    search_button: Any
    search_input: Any
    subtitle: Any
    table_container: Any
    title: Any


def build_content() -> ContentControls:
    with ui.column().classes("erms-content w-full p-5 gap-4"):
        breadcrumb_host = ui.element("nav").props(
            'aria-label=' + repr(render_message("webui.index.accessible_name.navigation_history_21482f31"))
        ).classes("w-full min-h-7")
        # NiceGUI's native row follows document direction. Remove the redundant
        # Quasar row class to avoid the legacy global RTL row-reversal rule.
        with ui.row().classes("w-full items-center no-wrap gap-4", remove="row"):
            with ui.column().classes("gap-0 grow min-w-0"):
                with ui.row().classes("erms-page-title-row items-center no-wrap gap-2"):
                    page_title_icon = ui.icon("dashboard").classes("erms-page-title-icon")
                    title = ui.label().classes("text-2xl font-semibold")
                subtitle = ui.label().classes("text-sm text-slate-500")
            with ui.row().classes("items-center no-wrap gap-2 flex-none"):
                add_button = ui.button(render_message("webui.index.button.add_5cee7302"), icon="add", color="primary").props("unelevated rounded")
                add_record_button = ui.button(
                    render_message("webui.index.button.add_record_fc8125c4"), icon="note_add", color="secondary"
                ).props("unelevated rounded")

        with ui.card().classes("erms-card w-full p-0") as content_card:
            with ui.row().classes(
                "erms-shared-control w-full items-center px-4 pt-4 gap-2"
            ) as aggregation_mode_bar:
                ui.label(render_message("webui.index.label.view_1306dc09")).classes("text-xs font-semibold uppercase tracking-wide text-slate-400 mr-1")
                aggregation_search_mode = ui.button(render_message("webui.index.button.search_4d02b714"), icon="search").props(
                    "unelevated dense no-caps color=primary"
                )
                aggregation_browse_mode = ui.button(
                    render_message("webui.index.button.browse_classification_9c15150f"), icon="account_tree"
                ).props("flat dense no-caps color=primary")
            with ui.row().classes(
                "erms-shared-control w-full items-end p-4 gap-2"
            ) as search_bar:
                search_input = ui.input(render_message("webui.index.input.search_by_number_title_or_description_e21ed520")).props("outlined clearable").classes("grow")
                search_button = ui.button(render_message("webui.index.button.search_4d02b714"), icon="search").props("unelevated")
            guidance = ui.label().classes(
                "erms-shared-control px-4 pb-4 text-slate-500"
            )
            table_container = ui.column().classes("w-full gap-0")
    content_card.set_visibility(False)
    aggregation_mode_bar.set_visibility(False)
    add_button.set_visibility(False)
    add_record_button.set_visibility(False)
    page_title_icon.set_visibility(False)

    return ContentControls(
        add_button=add_button,
        add_record_button=add_record_button,
        aggregation_browse_mode=aggregation_browse_mode,
        aggregation_mode_bar=aggregation_mode_bar,
        aggregation_search_mode=aggregation_search_mode,
        breadcrumb_host=breadcrumb_host,
        content_card=content_card,
        guidance=guidance,
        page_title_icon=page_title_icon,
        search_bar=search_bar,
        search_button=search_button,
        search_input=search_input,
        subtitle=subtitle,
        table_container=table_container,
        title=title,
    )
