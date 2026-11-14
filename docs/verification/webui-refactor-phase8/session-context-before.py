"""Per-page API/identity context and existing authentication cleanup ordering.

Feature caches and shell controls stay with their owners behind explicit hooks.
The identity mapping is a temporary adapter for remaining host callbacks; new
features use the principal and locale accessors, not that mapping.
"""
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from .api_client import ApiError, ErmsApiClient


class SessionContext:
    def __init__(
        self, *, api: ErmsApiClient,
        storage: Callable[[], MutableMapping[str, Any]],
        locale: Callable[[], dict[str, Any]],
        reset_private_views: Callable[[], Awaitable[None]],
        reset_navigation: Callable[[], None], clear_identity: Callable[[], None],
        close_menu: Callable[[], None], open_login: Callable[[], None],
        set_connection_status: Callable[[bool], None],
    ) -> None:
        self.api = api
        self.identity: dict[str, Any] = {"principal": None}
        self._storage = storage
        self._locale = locale
        self._reset_private_views = reset_private_views
        self._reset_navigation = reset_navigation
        self._clear_identity = clear_identity
        self._close_menu = close_menu
        self._open_login = open_login
        self._set_connection_status = set_connection_status

    @property
    def principal(self) -> dict[str, Any] | None:
        return self.identity.get("principal")

    @property
    def locale(self) -> dict[str, Any]:
        """Current owner-provided locale; this context adds no locale cache."""
        return self._locale()

    async def sign_in(self, email: str, password: str, *, user_agent: str | None) -> dict[str, Any]:
        principal, token = await self.api.login(email, password, user_agent=user_agent)
        await self._reset_private_views()
        self._storage()["session_token"] = token
        self.api.set_session_token(token)
        self._reset_navigation()
        return principal

    async def sign_out(self) -> None:
        # Clear private presentation before waiting for a potentially slow logout.
        self._close_menu()
        self._clear_identity()
        try:
            await self.api.logout()
        except ApiError:
            pass
        self._storage().pop("session_token", None)
        self._storage().pop("organization_browser_state", None)
        self.api.set_session_token(None)
        self._open_login()

    def handle_unauthorized(self) -> None:
        self.api.set_session_token(None)
        try:
            self._storage().pop("session_token", None)
        except RuntimeError:
            # A background request may have no NiceGUI storage request context.
            pass
        self._clear_identity()
        self._set_connection_status(True)  # A 401 proves that the API is reachable.
        self._open_login()
