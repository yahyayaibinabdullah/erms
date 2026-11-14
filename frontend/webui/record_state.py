"""Per-client record detail identity and existing return context.

One owner per client; existing defaults, refresh/invalidation and identity cleanup
are preserved. This extraction introduces no new cache.
"""
from typing import Any


def new_record_state() -> dict[str, Any]:
    return {}
