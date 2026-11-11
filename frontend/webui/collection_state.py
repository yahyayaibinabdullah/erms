"""Shared per-client bounded collection results, filters, paging and result anchors.

One owner per client; existing defaults, refresh/invalidation and identity cleanup
are preserved. This extraction introduces no new cache.
"""
from typing import Any


def new_collection_state() -> dict[str, Any]:
    return {'rows': [], 'searched': False, 'lifecycle_filter': 'all', 'entity_result_states': {}, 'collection_pages': {}}
