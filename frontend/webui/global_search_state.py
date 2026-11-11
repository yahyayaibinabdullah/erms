"""Per-client global search queries, results, diagnostics and restoration state.

One owner per client; existing defaults, refresh/invalidation and identity cleanup
are preserved. Results are reused only by this client for breadcrumb restoration;
explicit searches and cursor pages retain their existing API requests. Sign-in,
sign-out and expiry clear private results and diagnostics and invalidate pending
responses. Language reload creates a fresh owner. No new cache is introduced.
"""
from typing import Any


def new_global_search_state(q: str = "") -> dict[str, Any]:
    return {'global_search_query': q.strip(), 'global_search_items': [], 'global_search_cursor': None, 'global_search_filter': 'all', 'global_search_page': 1, 'global_search_page_size': 10, 'global_search_return_anchor': None, 'global_search_expanded_results': set(), 'search_diagnostics_enabled': False, 'search_diagnostics_sent': None, 'search_diagnostics_accepted': None, 'search_diagnostics_error': None}
