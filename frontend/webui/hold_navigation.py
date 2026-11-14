"""Existing legal-hold behavior with explicit feature dependencies."""
from __future__ import annotations
from .api_client import ApiError


def build_hold_navigation(
    *, api, principal, holds_navigation, refresh_drawer_headings,
):
    async def refresh_hold_navigation() -> None:
        privileges=set((principal() or {}).get("global_privileges",[]))
        if {"holds.administer", "holds.held_items.manage_all"} & privileges:
            holds_navigation.set_visibility(True)
            refresh_drawer_headings()
            return
        try:
            page=await api.holds_page(limit=1)
            holds_navigation.set_visibility(bool(page["total"]))
        except ApiError:
            holds_navigation.set_visibility(False)
        finally:
            refresh_drawer_headings()


    return refresh_hold_navigation
