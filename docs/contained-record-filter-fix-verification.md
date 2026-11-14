# Contained-record filter — empty-result recovery

**Status: fixed and locally verified on 11 November 2026.** The user separately authorized this repair
after the WebUI refactor. Earlier local changes are preserved on
`refactor-API-python-file`; no branch, commit, history or remote changes are made.

## Cause and correction

The aggregation detail view used `if not records` to choose its empty-aggregation
presentation. A filtered search with no matches therefore skipped the filter
input and its results container. The existing “No records match this filter”
message could not be reached.

The correction uses the empty-aggregation presentation only when there are no
returned records **and no active query**. With an active query, the existing
filter input, count and empty-result message remain available. Users can edit or
clear the input and press Enter, as in the existing filtering workflow. The
record pager remains hidden when there are no matches.

Genuinely empty, unfiltered aggregations retain their existing presentation.
The search payload, 10-record page limit, child-aggregation paging, return state,
URLs, layout and move/action behavior are unchanged. No API, schema or cache
changes are needed, and the fix adds no requests.

## Requirement → verification

| Requirement | Native Chrome/Edge checks, in English and Arabic |
| --- | --- |
| Keep the filter usable after zero matches | Submit a missing query from record page 2; retain its text and enabled input; show the existing no-match message |
| Recover by changing the query | Change to `REC-11`; show exactly the matching record on the first filtered page |
| Preserve return navigation | Open that record and return to its aggregation; retain the matching filter |
| Recover by clearing the query | Submit a second missing query, clear the input and press Enter; restore the first 10 records without reloading |
| Keep both pagers independent | Child page 3 remains selected through filtering; record page 2 works again after clearing |
| Preserve the truly empty state | Open an empty child aggregation; retain the original empty message without a filter |
| Preserve nearby behavior | Existing metadata keyboard focus, action-dialog cancellation, hierarchy continuation, return and reload checks |

The maintained `aggregations` browser scope replaces its former assertion that
the defect must remain with these recovery checks. The original Phase 6M report
remains historical evidence of the pre-refactor defect.

## Results and evidence

- **163 related unit tests passed** for entity contracts, relationship search and
  feature boundaries.
- **Four aggregation interaction tests passed**, including hierarchy paging,
  expansion/return behavior and abandonment. Total: **167 focused tests**.
- Configuration authority, API template consistency, catalogue references,
  approved Arabic terminology and the existing pure artifact validator passed.
- The pre-fix Chrome run reproduced the failure: the filtered-empty message was
  missing after the zero-result query. Its unsuccessful result is retained as
  regression evidence, not counted as passing acceptance.
- **Chrome 157.0.8103.40 and Edge 157.0.4341.42 passed** all seven groups each,
  covering English/LTR and Arabic/RTL. Each run retains 26 screenshots, including
  empty, recovered and cleared filter states. Visual review confirmed the
  retained controls and translated empty-result message in both browsers/languages.
- Both runs passed the recovery and independent-paging checks, filtered-record
  return, genuinely empty aggregation presentation, metadata keyboard focus,
  action-dialog cancellation and hierarchy navigation. Neither run reported
  browser errors or unsuccessful API requests.
- All **three disposable databases** were dropped, including the pre-fix run.
  An independent PostgreSQL catalogue query confirmed none remain. No owned
  test processes or native drivers remain.

Evidence: [acceptance record](verification/contained-record-filter-fix/acceptance.json),
[Chrome results](verification/contained-record-filter-fix/chrome/browser-results.json),
[Edge results](verification/contained-record-filter-fix/edge/browser-results.json),
and [cleanup audit](verification/contained-record-filter-fix/database-cleanup.json).
Raw logs, source hashes, screenshots and the failing pre-fix result are retained
alongside them. Final native source hashes match the current application/harness.
The sole application change in this follow-up is the condition in
`frontend/webui/aggregation_details.py`. Branch and HEAD remain unchanged, and
nothing was staged, committed or pushed.

This is focused local verification, not a new full-suite, CI or timing-benchmark
certification. The reusable native check is the existing `aggregations` scope of
`tools/run_webui_integration.py`, invoked with `--browser chrome` or `--browser edge`
through the API virtual environment. Recorded runs use existing cached native
drivers through the retained wrappers; no drivers or browser settings are changed.

Both existing language artifacts are reused. No keys, wording, placeholder
contracts, ordering or provenance are changed; no administrator export or
persistent database translation is modified, and no new draft review is required.
