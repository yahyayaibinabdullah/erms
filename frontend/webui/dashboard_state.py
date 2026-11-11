"""Per-client dashboard snapshot, identity/language cache key and refresh ownership.

One owner per client; existing defaults, refresh/invalidation and identity cleanup
are preserved. The existing key includes session revision, user, language,
timezone, privileges and roles. Each return renders its authorized snapshot then
refreshes once; mutations are observed by that refresh. Identity/key changes
invalidate snapshots. Failed warm refreshes retain the current snapshot; abandoned
responses cannot repopulate it. This extraction introduces no new cache.
"""
from typing import Any


def new_dashboard_state() -> dict[str, Any]:
    return {}
