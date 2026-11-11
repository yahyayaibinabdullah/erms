"""Classification navigation and per-client preferences, beside the existing workspace.

Preferences contain only the existing filter, expansion and paging choices. API
snapshots remain inside classification_workspace; reset detaches old preferences
and invalidates the view token on identity cleanup. Shell state stays in the host.
"""
from collections.abc import Callable
from typing import Any

from .classification_workspace import classification_workspace
from .i18n_catalogue import render_message


class ClassificationController:
    def __init__(
        self, *, api, container, principal: Callable, selected: Callable,
        begin: Callable, clear: Callable, register: Callable,
        open_editor: Callable, show_entity_history: Callable,
        format_timestamp: Callable, display_value: Callable, error_message: Callable,
        entity_metadata_label: Callable, localized_disposition_value: Callable,
        direction: Callable,
    ) -> None:
        self.api = api
        self.container = container
        self._principal = principal
        self._selected = selected
        self._begin = begin
        self._clear = clear
        self._register = register
        self._open_editor = open_editor
        self._show_entity_history = show_entity_history
        self._format_timestamp = format_timestamp
        self._display_value = display_value
        self._error_message = error_message
        self._entity_metadata_label = entity_metadata_label
        self._localized_disposition_value = localized_disposition_value
        self._direction = direction
        self._preferences: dict[str, Any] = {}
        self._token: object | None = None

    def reset(self) -> None:
        self._preferences = {}
        self._token = None

    async def open(
        self, initial_scheme_id: int | None = None,
        initial_classification_id: int | None = None,
    ) -> None:
        # Preserve the existing unresolved-principal guard and entry ordering.
        principal = self._principal()
        if principal is None:
            return
        self._begin()
        token = object()
        self._token = token
        self._clear()

        def register_classification_page(page: str, item: dict[str, Any] | None) -> None:
            label = (
                f"{item['code']} — {item['title']}"
                if item and item.get("title") else
                render_message("navigation.item.classification_schemes")
            )
            self._register(
                page, label, item,
                "" if item else render_message("webui.select_classification_workspace.text.build_and_govern_classification_hierarchie_1766e961"),
            )

        await classification_workspace(
            api=self.api, container=self.container, open_editor=self._open_editor,
            show_entity_history=self._show_entity_history, format_timestamp=self._format_timestamp,
            display_value=self._display_value, error_message=self._error_message,
            entity_metadata_label=self._entity_metadata_label,
            localized_disposition_value=self._localized_disposition_value,
            register_page=register_classification_page,
            active=lambda: self._token is token and self._selected(),
            can_transfer="classifications.administer" in principal.get("global_privileges", []),
            preferences=self._preferences, direction=self._direction,
            initial_scheme_id=initial_scheme_id,
            initial_classification_id=initial_classification_id,
        )
