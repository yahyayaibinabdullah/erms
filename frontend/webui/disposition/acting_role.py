"""Internal attribution from a server-projected, operation-specific role set.

No role lookup/cache or UI control. The lowest qualifying role ID is stable across
projection order and locale. The API/SQL still recheck this single role's current
assignment, action/task eligibility and resource authorization on every request.
Never pass principal-wide roles or merge privileges to manufacture eligibility.
"""
from collections.abc import Mapping


def automatic_role(roles):
    identities = roles.keys() if isinstance(roles, Mapping) else (row['id'] for row in roles)
    return min((identity for identity in identities
                if isinstance(identity, int) and not isinstance(identity, bool) and identity > 0),
               default=None)
