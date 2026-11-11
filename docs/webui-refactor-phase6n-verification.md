# Phase 6N — records, capture and shared collections

**Status: complete for the approved local scope.** Changes remain local and
uncommitted on `refactor-API-python-file`, HEAD `839b770`. Chrome and Edge are
covered; Firefox, Safari and CI remain deferred.

## Ownership

| Module | Existing responsibility moved |
| --- | --- |
| `record_details.py`, `record_state.py` | Record details, actions, parent return, relationships and per-client detail identity |
| `record_capture.py` | Draft metadata, physical/digital capture, staging, preparation, validation, commit and abandonment |
| `record_editor.py`, `record_presentation.py` | Record medium rules, draft context and presentation constants |
| `entity_editor.py` | Shared form/save orchestration, retaining the existing classification, organization, security and aggregation hooks |
| `resource_row_hydration.py`, `resource_row_presentation.py` | Bounded row enrichment and existing relationship display helpers |
| `resource_collection_results.py` | Compact record/aggregation results, filtering, paging, expansion and return anchors |
| `collection_table.py`, `collection_navigation.py`, `collection_state.py` | Shared collection dispatch, loading, navigation and per-client bounded result state |

Record detail state and shared collection state have separate owners. Authentication,
page identity and destination calls use explicit callbacks; cyclic destinations
remain deferred until invoked. Initial defaults and all existing cleanup paths
are preserved. No feature imports `app.py` or receives its complete state.

Source reconstruction covers 12 moved functions, the record-medium editor block,
and the other 105 host/top-level functions. State defaults and per-client creation
also match. Only `app.py` changed among pre-existing runtime files. No new cache,
request strategy, URL, browser-history behavior, wording or translation was added.

## Requirement → verification

| Existing behavior | Passing evidence |
| --- | --- |
| Physical/digital parent and medium rules, required fields and creation | Two original/extracted real-API record lifecycle cases |
| Digital staging, component persistence and saved metadata freshness | Real-API lifecycle, plus native Chrome/Edge upload and preview |
| Pending capture preparation, editable metadata, disabled commit, failed preparation and abandonment | Ten original capture interaction cases; full extracted interaction gate |
| Bounded destination search and fixed digital capture medium | Capture control interaction cases |
| Metadata edit focus, cancellation and containing-aggregation return | English/Arabic Chrome/Edge journeys |
| Draft validation without a write, upload, preview and actual draft deletion | English/Arabic Chrome/Edge journeys |
| Shared editors, permissions, failed writes, paging, stale-response rejection, localization and session cleanup | Full unit/interaction and assembled gates; existing assertions retained and pointed at their new owners |
| Existing governed-move defect and component behavior | Unchanged action/component owners and their existing regression tests |

## Verification

- **1,624 unit, 345 interaction and 64 assembled tests passed.**
- Original capture baseline: 10 interaction cases and two real-API lifecycles.
- Each browser passed five groups and 14 English/Arabic scenes before and after.
  Focus and request counters match. Only existing message catch-up/unread polling
  is excluded from counters.
- Edge's 14 final paired scenes are pixel-identical. Chrome has 13 identical
  scenes and one with eight border-rasterization pixels differing by at most
  3/255 per channel. Geometry, wording, controls and focus are unchanged.
  The existing animated 72px header is excluded; fullscreen previews are compared
  in full. No CSS or page content was hidden or masked.
- The first Edge baseline displayed an English record subtitle in Arabic. The
  repeated original and extracted journeys both display Arabic and match exactly.
  The first Chrome extracted run made one old selected-label security lookup and
  one selected-ID resolution; the unchanged-source rerun matches original request
  counts. The selector and display-label echo handling are unchanged. These
  initial observations remain recorded; no product fix was introduced.
- Initial test failures came from old source locations and test fixtures supplying
  the former state owner. They were corrected without removing assertions. The
  new real-API test also waits for the current detail's component controls before
  opening its editor; that readiness correction passed against the original.
- All 4,071 catalogue keys and catalogue/inspector artifact bytes are unchanged.
  Catalogue, Arabic terminology, configuration and API-template checks pass,
  together with 24 runner-safety tests.
- **All 15 unique disposable PostgreSQL databases were removed**, including failed
  development attempts, confirmed independently against PostgreSQL's catalogue.

The two aggregation defects remain outside this refactor's authorization. Their
reminder is recorded for the final whole-WebUI refactoring handoff. The existing
undefined `card_host` in unreachable legacy table fallbacks is also preserved;
removal of obsolete adapters remains Phase 8.

[Acceptance totals and evidence](verification/webui-refactor-phase6n/acceptance.json)
include reconstruction, tests, browser comparisons and database cleanup. No branch,
commit, push, persistent database or existing stack was changed by this work.
