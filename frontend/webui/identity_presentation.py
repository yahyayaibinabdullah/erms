"""Existing organization rules and presentation, shared with connected features."""
from __future__ import annotations
from typing import Any
from nicegui import ui


USER_AVATAR_BACKGROUND = "#e3f2fd"


USER_AVATAR_TEXT = "#15527a"


def user_avatar(user: dict[str, Any]) -> dict[str, str]:
    """Return best-effort initials with the standard Wathiq user-avatar palette."""
    parts = [part for part in str(user.get("name") or "").split() if part]
    if len(parts) >= 2:
        initials = f"{parts[0][0]}{parts[-1][0]}"
    elif parts:
        initials = parts[0][:2]
    else:
        initials = "?"
    return {
        "initials": initials.upper(),
        "color": USER_AVATAR_BACKGROUND,
        "text_color": USER_AVATAR_TEXT,
    }


def render_user_avatar(user: dict[str, Any], *, size: str = "38px") -> Any:
    """Render the same deterministic avatar used by the Users listing."""
    avatar = user_avatar(user)
    with ui.avatar(size=size).style(
        f"background:{avatar['color']} !important;color:{avatar['text_color']} !important"
    ) as control:
        ui.label(avatar["initials"]).classes("font-medium")
    return control

