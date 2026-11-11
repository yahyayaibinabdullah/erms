"""Per-client disposition saved view and current page ownership token.

One owner per client; existing defaults, refresh/invalidation and identity cleanup
are preserved. This extraction introduces no new cache.
"""
from typing import Any


def new_disposition_state() -> dict[str, Any]:
    return {}
