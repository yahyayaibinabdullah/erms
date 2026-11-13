"""Per-tab Global Search state and server page tokens."""
from typing import Any
from uuid import uuid4


def new_global_search_state(q: str = "", *, tab_id: str | None = None) -> dict[str, Any]:
    return {
        'global_search_query': q.strip(), 'global_search_tab_id': tab_id or str(uuid4()),
        'global_search_id': None, 'global_search_page_tokens': {}, 'global_search_items': [],
        'global_search_totals': None, 'global_search_filter': 'all', 'global_search_truncated': False,
        'global_search_page': 1, 'global_search_page_size': 10, 'global_search_result_cap': None,
        'global_search_return_anchor': None, 'global_search_expanded_results': set(),
        'global_search_loading': False, 'global_search_error': None,
        'global_search_retry_page': 1, 'global_search_pending': False,
        'search_diagnostics_enabled': False, 'search_diagnostics_sent': None,
        'search_diagnostics_accepted': None, 'search_diagnostics_error': None,
    }
