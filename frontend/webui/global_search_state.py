"""Per-client global search queries, results, diagnostics and restoration state.

The current query owns its initial totals and the cursor pages visited in each
tab. These results are reused for tab changes, backward paging and breadcrumb
restoration. A new submission or session reset discards them. Language reload
creates a fresh owner. Failed reads do not replace a tab's existing pages.
"""
from typing import Any


def new_global_search_state(q: str = "") -> dict[str, Any]:
    return {
        'global_search_query': q.strip(), 'global_search_streams': {},
        'global_search_totals': None, 'global_search_filter': 'all',
        'global_search_page': 1, 'global_search_page_size': 10,
        'global_search_return_anchor': None, 'global_search_expanded_results': set(),
        'global_search_loading': False, 'global_search_error': None,
        'global_search_retry_page': 1, 'global_search_pending': False,
        'search_diagnostics_enabled': False, 'search_diagnostics_sent': None,
        'search_diagnostics_accepted': None, 'search_diagnostics_error': None,
    }
