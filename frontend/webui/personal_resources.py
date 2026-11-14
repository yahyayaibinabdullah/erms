"""Per-client favourites and recent activity owned by the authenticated page."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable
from nicegui import ui
from .api_client import ApiError
from .entities import EntitySpec
from .i18n_catalogue import render_message

STOP_PROPAGATION_CLICK_HANDLER = "(event) => { event.stopPropagation(); emit(); }"

@dataclass
class PersonalResourceState:
    favourites: dict = field(default_factory=lambda: {"aggregations": [], "records": []})
    favourite_ids: dict = field(default_factory=lambda: {"aggregations": set(), "records": set()})
    recent_activity: dict = field(default_factory=dict)
    recent_scope: tuple | None = None
    navigation_revision: int = 0
    personal_refresh: asyncio.Task | None = None
    personal_sections_loading: dict = field(default_factory=dict)
    personal_section_hosts: dict = field(default_factory=dict)

    def leave_view(self) -> None:
        """Release the old panel refresh before a new view starts its reads."""
        self.navigation_revision += 1
        if self.personal_refresh is not None:
            self.personal_refresh.cancel()
            self.personal_refresh = None
        self.personal_sections_loading.clear()
        self.personal_section_hosts.clear()

    def sync_recent_scope(self, scope: tuple | None) -> None:
        if self.recent_scope != scope:
            self.recent_activity.clear()
            self.recent_scope = scope

@dataclass(frozen=True)
class PersonalResources:
    reload_favourites: Callable
    favourite_state: Callable
    toggle_favourite: Callable
    favourite_button: Callable
    load_recent: Callable

def build_personal_resources(api: Any, personal: PersonalResourceState, *,
    get_principal: Callable, get_resource: Callable[[], str],
    accept_application_configuration: Callable, get_recent_scope: Callable,
    error_message: Callable[[ApiError], str]):
    async def reload_favourites() -> dict[str, list[dict[str, Any]]]:
        principal = get_principal()
        resource = get_resource()
        revision = personal.navigation_revision
        favourites = await api.favourites()
        if (get_principal() is not principal or get_resource() != resource
                or personal.navigation_revision != revision):
            return favourites
        accept_application_configuration(favourites["application_configuration"])
        personal.favourites = {key:favourites[key] for key in ("aggregations","records")}
        personal.favourite_ids = {
            resource: {int(item["id"]) for item in favourites[resource]}
            for resource in ("aggregations", "records")
        }
        return favourites


    def favourite_state(resource: str, entity_id: int) -> bool:
        return int(entity_id) in personal.favourite_ids[resource]


    def apply_favourite_button(button: Any, tooltip: Any, selected: bool) -> None:
        label = render_message("webui.apply_favourite_button.text.remove_from_favourites_596874e5") if selected else render_message("webui.apply_favourite_button.text.add_to_favourites_46913fe5")
        button.props(remove="icon color aria-label")
        button.props(
            f"icon={('favorite' if selected else 'favorite_border')} color={('red' if selected else 'primary')} aria-label={label!r}"
        )
        tooltip.text = label
        button.update()
        tooltip.update()


    async def toggle_favourite(
        resource: str, entity_id: int, *, button: Any | None = None,
        tooltip: Any | None = None, on_changed: Any | None = None,
    ) -> bool:
        was_selected = favourite_state(resource, entity_id)
        now_selected = not was_selected
        if button is not None:
            button.disable()
            if tooltip is not None:
                apply_favourite_button(button, tooltip, now_selected)
        ids = personal.favourite_ids[resource]
        (ids.add if now_selected else ids.discard)(int(entity_id))
        try:
            if now_selected:
                await api.favourite(resource, entity_id)
            else:
                await api.unfavourite(resource, entity_id)
            ui.notify(
                render_message("webui.toggle_favourite.notify.added_to_favourites_c5febdef") if now_selected else render_message("webui.toggle_favourite.notify.removed_from_favourites_4077349e"),
                color="positive",
            )
            if on_changed is not None:
                result = on_changed(now_selected)
                if asyncio.iscoroutine(result):
                    await result
            return now_selected
        except ApiError as error:
            (ids.add if was_selected else ids.discard)(int(entity_id))
            if button is not None and tooltip is not None:
                apply_favourite_button(button, tooltip, was_selected)
            ui.notify(error_message(error), color="negative", close_button=True)
            return was_selected
        finally:
            if button is not None:
                button.enable()


    def favourite_button(resource: str, entity_id: int, *, on_changed: Any | None = None) -> Any:
        selected = favourite_state(resource, entity_id)
        button = ui.button(
            icon="favorite" if selected else "favorite_border",
        ).props(
            f"flat round dense color={('red' if selected else 'primary')} aria-label={('Remove from favourites' if selected else 'Add to favourites')!r}"
        )
        with button:
            tooltip = ui.tooltip(
                render_message("webui.favourite_button.tooltip.remove_from_favourites_bf36943b") if selected else render_message("webui.favourite_button.tooltip.add_to_favourites_524a224e")
            )
        button.on(
            "click",
            lambda: toggle_favourite(
                resource, entity_id, button=button, tooltip=tooltip,
                on_changed=on_changed,
            ),
            js_handler=STOP_PROPAGATION_CLICK_HANDLER,
        )
        return button


    async def load_recent(spec: EntitySpec) -> None:
        if spec.key not in {"aggregations", "records"}:
            return
        scope = get_recent_scope()
        personal.sync_recent_scope(scope)
        if scope is None:
            return
        revision = personal.navigation_revision
        activity = await api.recent_resource_activity(spec.key, limit=50)
        if (get_recent_scope() == personal.recent_scope == scope
                and personal.navigation_revision == revision):
            personal.recent_activity[spec.key] = activity

    return PersonalResources(reload_favourites, favourite_state, toggle_favourite, favourite_button, load_recent)

