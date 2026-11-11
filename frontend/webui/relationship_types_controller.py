"""Relationship-type administration entry and per-client view lifetime.

Rendering remains in resource_relationships.py. The host supplies only the
existing shell entry, identity, destination and language readers.
"""
from collections.abc import Callable
from typing import Any

from nicegui.element import Element

from .api_client import ApiError, ErmsApiClient
from .capabilities import can_navigate
from .resource_relationships import relationship_administration


class RelationshipTypesController:
    def __init__(
        self, *, api: ErmsApiClient, container: Element,
        principal: Callable[[], dict[str, Any] | None],
        selected: Callable[[], bool], enter: Callable[[], None],
        supported_languages: Callable[[], list[dict[str, Any]]],
        on_error: Callable[[ApiError], str],
    ) -> None:
        self.api = api
        self.container = container
        self._principal = principal
        self._selected = selected
        self._enter = enter
        self._supported_languages = supported_languages
        self._on_error = on_error
        self._token: object | None = None

    async def open(self) -> None:
        principal = self._principal()
        if not principal or not can_navigate(
            'relationship-types', principal.get('global_privileges', []),
        ):
            return
        token = object()
        self._token = token
        self._enter()
        await relationship_administration(
            api=self.api, container=self.container,
            supported_languages=self._supported_languages(),
            active=lambda: self._principal() is principal and self._selected() and self._token is token,
            on_error=self._on_error,
        )
