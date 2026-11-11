"""Per-client live transport, identity and notification ownership; no new cache."""


def new_message_live_state():
    return {"adapter": None, "api": None, "token": None, "notifications": []}
