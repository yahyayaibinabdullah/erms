"""Per-client mailbox workspace and current view ownership token.

One owner per client; existing defaults, refresh/invalidation and identity cleanup
are preserved. This extraction introduces no new cache.
"""
from typing import Any


def new_messaging_state() -> dict[str, Any]:
    return {}
