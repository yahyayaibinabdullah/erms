# Phase 6Q — Global and full-text search

**Status: complete for the approved local scope.** Changes remain local and
uncommitted on `refactor-API-python-file`, HEAD `839b770`. Chrome/Edge are covered;
Firefox, Safari and CI remain deferred.

`global_search.py` owns queries, safe snippets, diagnostics, result paging,
component context, expansion state, destination callbacks and cleanup.
`global_search_state.py` creates an independent owner for each client. Existing
navigation and account cleanup use that owner; advanced-search cleanup remains
an explicit callback for 6R. No new cache or request policy was introduced.

Source reconstruction confirms all 14 moved functions, the other 89 host
functions and all initial state values are preserved. Pre-existing feature files
and catalogue bytes are unchanged.

## Requirement → verification

| Existing behavior | Passing evidence |
| --- | --- |
| Bounded 25-result requests, cached ten-row pages and cursor continuation | Original/extracted interaction tests and 29-result Chrome/Edge fixture |
| Record/aggregation filters, expansions and return anchors | Interaction tests; actual record destination and breadcrumb restoration |
| Authorized component details and denied-detail fallback | Original/extracted interaction tests, bounded component request assertions |
| No stale results after navigation, sign-out or a newer search | Original/extracted interaction cases and existing session-isolation tests |
| Privileged, explicit diagnostics; private state cleared at identity boundaries | Interaction/session tests and independent-client state test |
| Safe snippet markers; loading, empty and failure states | Original/extracted interaction checks |
| Existing query URL, reload, keyboard focus and browser history | English/Arabic Chrome/Edge journeys |
| Shared navigation and other screens | Full unit, interaction and assembled gates |

## Results and observations

- **1,625 unit, 379 interaction and 69 assembled tests passed.**
- Nine new interaction cases passed before and after extraction. The 22 existing
  focused unit cases and new real-API search journey passed against the original.
- Both browsers passed five groups and 18 scenes before and after extraction.
  **All 36 paired scenes match exactly below the animated 72px header.** Focus,
  URL/history behavior and request counters match; only existing message
  catch-up/unread polling is excluded from request counters.
- The test driver now respects existing behavior: the query clear control precedes
  Search in keyboard order; a cached partial page can grow when the next cursor
  is fetched; the existing query URL takes precedence on language reload.
- Test preparation corrected synthetic record fields, enabled full-text search
  only in the disposable assembled fixture (then restored it), and corrected
  multi-row/diagnostic-aware locators and native input replacement. No application
  fix or relaxed assertion was required.
- Navigation test fixtures now supply the extracted search-state owner. Their
  existing diagnostics-cleanup and navigation-order assertions are unchanged.
- Catalogue, Arabic terminology, configuration ownership, API templates and all
  24 runner-safety checks pass. No text, key, translation or provenance changed.
- **All 18 disposable databases were removed**, including test-development runs,
  independently verified against PostgreSQL's catalogue.

[Acceptance and archived evidence](verification/webui-refactor-phase6q/acceptance.json)
record these checks. No functionality, UI, UX, API, schema, new URL or history
behavior changed. No branch, commit or push was created. Phase 6R follows under
the existing approval.
