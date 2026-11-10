"""Application Settings entry points and per-client view lifetime.

The existing shell supplies narrow callbacks; this feature never imports app.py
or receives the application's shared state/navigation dictionaries. Rendering
and form state remain in application_settings.py.
"""
from collections.abc import Awaitable, Callable
from typing import Any

from nicegui.element import Element

from .api_client import ErmsApiClient
from .application_settings import settings_page
from .capabilities import can_navigate


class ApplicationSettingsController:
    def __init__(
        self, *, api: ErmsApiClient, container: Element,
        principal: Callable[[], dict[str, Any] | None],
        selected: Callable[[], bool], enter: Callable[[], None],
        persist_category: Callable[[], None],
        guard: Callable[[Callable[[], Awaitable[None]]], Awaitable[None]],
        bind_relationship: Callable[..., Any], direction: Callable[[], str],
        on_error: Callable[[Any], str],
    ) -> None:
        self.api = api
        self.container = container
        self._principal = principal
        self._selected = selected
        self._enter = enter
        self._persist_category = persist_category
        self._guard = guard
        self._bind_relationship = bind_relationship
        self._direction = direction
        self._on_error = on_error
        self._category = "general"
        self._token: object | None = None

    @property
    def category(self) -> str:
        """The existing navigation snapshot value, never a cache of API data."""
        return self._category

    def can_open(self) -> bool:
        principal = self._principal()
        return bool(principal and can_navigate(
            "application-settings", principal.get("global_privileges", []),
        ))

    async def open(self, initial_category: str = "general", *, initial_setting_key: str | None = None) -> None:
        principal = self._principal()
        if not self.can_open():
            return
        token = object()
        self._token = token
        self._category = initial_category
        # Preserve the original ordering: select the resource/category before
        # registering the visit, then prepare the shared content container.
        self._enter()

        def active() -> bool:
            return (self._principal() is principal and self._selected()
                    and self._token is token)

        def remember_category(value: str) -> None:
            if not active():
                return
            self._category = value
            self._persist_category()

        await settings_page(
            api=self.api, container=self.container, bind_relationship=self._bind_relationship,
            active=active, on_error=self._on_error, direction=self._direction,
            initial_category=initial_category, initial_setting_key=initial_setting_key,
            on_category=remember_category,
        )

    async def restore(self, saved: dict[str, Any]) -> None:
        # Restoration is already guarded by the existing navigation host.
        await self.open(saved.get("settings_category", "general"))

    async def open_from_drawer(self) -> None:
        await self._guard(self.open)

    async def open_from_custody(self) -> None:
        await self._guard(lambda: self.open("disposition"))

    async def open_from_event(self, event: dict[str, Any]) -> None:
        if not self.can_open():
            return
        origin_dialog = event.get("_origin_dialog")
        if origin_dialog:
            origin_dialog.close()
        setting_key = (event.get("metadata") or {}).get("setting_key")
        await self._guard(lambda: self.open(initial_setting_key=setting_key))
