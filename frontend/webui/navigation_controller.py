"""Per-page navigation trail and coordination, without routes or feature loaders.

The host supplies existing presentation, persistence, guard and dispatch callbacks.
No application state dictionary or API client is shared with this controller.
"""
import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from .api_client import ApiError
from .i18n_catalogue import render_message
from .navigation_data import NAVIGATION_TRAIL_LIMIT, append_navigation_entry


class NavigationController:
    def __init__(
        self, *, stored: Any,
        write_trail: Callable[[list[dict[str, Any]]], None],
        prepare: Callable[[str], None], snapshot: Callable[[], dict[str, Any]],
        label_key: Callable[[str], str | None],
        get_guard: Callable[[], Callable[[str], Awaitable[bool]] | None],
        clear_guard: Callable[[], Any], cancel_reads: Callable[[], None],
        restore: Callable[[dict[str, Any]], Awaitable[None]],
        dashboard: Callable[[], Awaitable[None]], render: Callable[[], None],
        notify: Callable[..., None], on_error: Callable[[ApiError], str],
    ) -> None:
        self.trail = [
            item for item in (stored if isinstance(stored, list) else [])
            if isinstance(item, dict) and isinstance(item.get("page"), str)
        ][-NAVIGATION_TRAIL_LIMIT:]
        self.restoring = False
        self._write_trail = write_trail
        self._prepare = prepare
        self._snapshot = snapshot
        self._label_key = label_key
        self._get_guard = get_guard
        self._clear_guard = clear_guard
        self._cancel_reads = cancel_reads
        self._restore = restore
        self._dashboard = dashboard
        self._render = render
        self._notify = notify
        self._on_error = on_error

    def persist(self) -> None:
        self._write_trail(self.trail)

    async def _allow_leave(self) -> bool:
        discard_guard = self._get_guard()
        if discard_guard is not None and not await discard_guard("leave this page"):
            return False
        self._clear_guard()
        return True

    async def navigate_to_breadcrumb(self, index: int) -> None:
        trail = self.trail
        if index < 0 or index >= len(trail):
            return
        if not await self._allow_leave():
            return
        entry = dict(trail[index])
        self.trail = trail[:index + 1]
        self.persist()
        self.restoring = True
        try:
            await self._restore(entry)
        except ApiError as error:
            if error.status_code in {403, 404}:
                self.trail = self.trail[:-1]
                self.persist()
                self._notify(
                    render_message("webui.navigate_to_breadcrumb.notify.that_page_is_no_longer_available_returning_9e1c0830"),
                    color="warning",
                )
                if self.trail:
                    await self._restore(self.trail[-1])
                else:
                    await self._dashboard()
            else:
                self._notify(self._on_error(error), color="negative", close_button=True)
        finally:
            self.restoring = False
            self._render()

    def register_navigation(
        self, page: str, label: str, *, entity_id: int | None = None,
        accessible_label: str | None = None, dynamic_label: bool = False,
    ) -> None:
        self._prepare(page)
        if self.restoring:
            return
        trail = self.trail
        if trail:
            trail[-1]["state"] = self._snapshot()
        entry = {
            "page": page,
            "label": label,
            "label_key": None if dynamic_label else self._label_key(page),
            "dynamic_label": dynamic_label,
            "entity_id": entity_id,
            "accessible_label": accessible_label or label,
            "state": {},
        }
        self.trail = append_navigation_entry(trail, entry)
        self.persist()
        self._render()

    async def breadcrumb_back(self, fallback: Any) -> None:
        if len(self.trail) > 1:
            await self.navigate_to_breadcrumb(len(self.trail) - 2)
            return
        result = fallback()
        if asyncio.iscoroutine(result):
            await result

    async def guarded_page_navigation(self, callback: Callable[[], Any]) -> None:
        if not await self._allow_leave():
            return
        self._cancel_reads()
        result = callback()
        if inspect.isawaitable(result):
            await result
