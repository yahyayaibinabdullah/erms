"""Private advanced and saved-query workspace, session revision and administration selection.

One owner per client; existing defaults, refresh/invalidation and identity cleanup
are preserved. This extraction introduces no new cache.
"""
from typing import Any


def new_advanced_search_state() -> dict[str, Any]:
    return {}
