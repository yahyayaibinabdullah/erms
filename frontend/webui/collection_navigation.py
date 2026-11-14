"""Collection entry, bounded loading and existing background personal refresh."""
from __future__ import annotations
from .api_client import ApiError
from .entities import COLLECTION_ENTITIES
from .entities import EntitySpec
import asyncio
from nicegui import background_tasks
from .capabilities import can_add_from_collection
from .i18n_catalogue import render_message
from nicegui import ui

def build_collection_navigation(
    *, add_button, add_record_button, aggregation_mode_bar, aggregation_state, collection_state, error_message, get_resource, get_recent_scope, guidance, load_recent, load_rows, personal, principal, register_navigation, reload_favourites, render_resource_personal_sections, render_table, search_bar, search_input, select_aggregation_browser, set_connection_status, set_resource, show_authenticated_view, subtitle, title,
):
    def refresh_personal_sections(spec: EntitySpec) -> None:
        if personal.personal_refresh is not None:
            return
        key = spec.key
        scope = get_recent_scope()
        revision = personal.navigation_revision
        personal.sync_recent_scope(scope)
        personal.personal_sections_loading[key] = True

        def current() -> bool:
            return (personal.navigation_revision == revision and get_recent_scope() == scope
                    and get_resource() == key and not (
                        key == "aggregations" and aggregation_state.get("aggregation_mode") == "browse"
                    ))

        async def refresh() -> None:
            if not current():
                return
            try:
                # Each response can finish independently. A failed favourites
                # fetch must not leave a successful activity refresh invisible.
                results = await asyncio.gather(reload_favourites(), load_recent(spec), return_exceptions=True)
                if current():
                    for result in results:
                        if isinstance(result, ApiError):
                            set_connection_status(result.status_code != 503)
                            ui.notify(error_message(result), color="negative", close_button=True)
                        elif isinstance(result, Exception):
                            raise result
            except asyncio.CancelledError:
                return
            finally:
                if personal.personal_refresh is asyncio.current_task():
                    personal.personal_refresh = None
                    personal.personal_sections_loading.pop(key, None)
            if current():
                host = personal.personal_section_hosts.get(key)
                if host is not None and not host.is_deleted:
                    render_resource_personal_sections(spec, container=host)

        personal.personal_refresh = background_tasks.create(refresh())

    async def select_entity(key: str) -> None:
        spec = COLLECTION_ENTITIES[key]
        entity_navigation_keys = {
            "aggregations": "navigation.item.aggregations",
            "records": "navigation.item.records",
            "org-units": "navigation.item.org_units",
            "roles": "navigation.item.roles",
            "users": "navigation.item.users",
            "text-indexers": "navigation.item.text_indexers",
            "audit-trail": "navigation.item.audit_trail",
            "login-sessions": "navigation.item.login_sessions",
            "security-operations": "navigation.item.security_operations",
            "security-levels": "navigation.item.security_levels",
            "profiles": "navigation.item.profiles",
            "governance-custody": "navigation.item.governance_custody",
            "holds": "navigation.item.holds",
        }
        entity_label = render_message(entity_navigation_keys.get(key, "navigation.item.dashboard"))
        register_navigation(key, entity_label)
        show_authenticated_view()
        set_resource(key); collection_state.update(rows=[], searched=False, lifecycle_filter='all'); aggregation_state.update(aggregation_detail=None)
        title.text = entity_label
        subtitle.text = render_message("webui.select_entity.text.search_required_before_loading_results_88549c49") if spec.search_first else render_message("webui.select_entity.text.manage_current_system_entries_fcec8116")
        aggregation_mode_bar.set_visibility(key == "aggregations")
        search_bar.set_visibility(
            spec.search_first
            and not (key == "aggregations" and aggregation_state.get("aggregation_mode") == "browse")
        )
        guidance.text = render_message("webui.select_entity.text.large_collections_are_search_first_to_avoi_717a0f77") if spec.search_first else ""
        privileges = set(
            (principal() or {}).get("global_privileges", [])
        )
        add_button.set_visibility(can_add_from_collection(key, privileges))
        add_button.text = render_message("webui.select_entity.text.add_6623ee14")
        add_button.update()
        add_record_button.set_visibility(False)
        search_input.value = ""
        try:
            if key in {"aggregations", "records"} and not (
                key == "aggregations" and aggregation_state.get("aggregation_mode") == "browse"
            ):
                refresh_personal_sections(spec)
                render_table(spec)
                await load_rows(on_loaded=lambda: None)
                return
            revision = personal.navigation_revision
            personal.sync_recent_scope(get_recent_scope())
            startup_requests = []
            if key in {"aggregations", "records"}:
                startup_requests.append(reload_favourites())
            if spec.search_first:
                startup_requests.append(load_recent(spec))
            if startup_requests:
                await asyncio.gather(*startup_requests)
            if personal.navigation_revision != revision:
                return
            if key == "aggregations" and aggregation_state.get("aggregation_mode") == "browse":
                await select_aggregation_browser()
                return
            render_table(spec)
            await load_rows()
        except ApiError as error:
            set_connection_status(error.status_code != 503)
            ui.notify(error_message(error), color="negative", close_button=True)


    return select_entity, refresh_personal_sections
