"""Per-client aggregation view state, retaining the original lifetime and defaults.

Hierarchy rows are refreshed on entry; expansion, filters, page lengths and
return anchors retain their existing session behavior. This introduces no cache.
The host shares only this feature's state with aggregation views.
"""
from typing import Any


def new_aggregation_state() -> dict[str, Any]:
    return {"aggregation_detail": None, "aggregation_mode": "search"}
