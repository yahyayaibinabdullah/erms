# Phase 6L — digital components and preview

**Status: complete for the approved local scope.** Changes remain local and uncommitted.
Chrome and Edge are the approved browser scope; Firefox, Safari and CI are deferred.

## Ownership

| Module | Existing responsibility moved |
| --- | --- |
| `components.py` | Saved component list, permissions/closure, page state, upload serialization, ordering, removal, indexing status and callbacks |
| `component_preview.py` | Saved/staged viewer, selected component, 50-row paging, image/audio/video/PDF paths, print/download, request generations and cleanup |
| `component_presentation.py` | Existing status labels, file icons, supported formats and uploader slots |
| `component_cards.py` | Existing card presentation with explicit shared timestamp/size formatters |
| `upload_buffers.py` | Shared copying of temporary upload bytes before awaited operations |

The host supplies the API, error formatter, deferred history destination, preview
and card callbacks. Existing per-dialog/view state and upload locks keep their
original lifetimes. No application state dictionary, cache, or app import is
passed into a feature. Existing helper imports remain available from the root.
Draft context validation stays with capture (6N); search-result hydration stays
with its remaining search caller until that feature moves.

All 11 moved function bodies are identical; the other 130 top-level/host functions
are identical. The only changed existing runtime file is `app.py`. No wording,
translation, API, schema, URL, browser-history or product behavior changed.

## Requirement → verification

| Existing behavior | Evidence |
| --- | --- |
| Closed/physical/unauthorized upload rules and action capabilities | Four original/after interaction cases |
| Versioned optimistic removal, failure rollback, ordering and errors | Original/after interaction cases and real-API workflow |
| Current-total upload placement, per-file refresh, failure stops and retained cards | Original/after interaction cases; native browser upload |
| Shortened last-page recovery; 25-row component/50-row viewer bounds | Original/after interaction/viewer checks and retained source contracts |
| Staged formats, no saved-record permissions, selected item, paging, errors and abandoned responses | Original/after English/Arabic preview tests |
| Saved permissions, initial failures, binary print/download routes | Original/after English/Arabic preview tests |
| Connected upload, reorder, preview, download and removal | Original/after assembled real-API workflow |
| Real image/PDF rendering, zoom, focus, close, reopen and language direction | Original/after Chrome/Edge journeys |
| Record/draft, indexer, audit, disposition and search callers | Full unit, interaction and assembled regression gates |

## Baseline findings

A real-browser check reproduced an existing deletion-notification defect in both
browsers. Removing a component succeeds in the API and optimistically removes the
card. The subsequent success notification raises “The parent element this slot
belongs to has been deleted,” preventing the automatic refresh. Reopening the
record displays the saved result correctly. The frozen original and extracted
implementations exhibit exactly the same error once per language. This refactor
preserves it; a product fix needs separate approval. No other server traceback is
accepted by the evidence gate.

Test development also corrected an unsupported aggregation fixture field,
selector arguments/uniqueness, and a keyboard check that inadvertently reloaded
the selected component before pressing Tab. Browser screenshots now use ordinary
scrolling to show the actual component section. These are test changes only.
Original failed attempts remain in local runtime evidence; only passing evidence
and a sanitized summary of the known server error are archived.

## Final verification

- **1,624 unit tests, 337 interaction tests and 61 assembled tests passed**
  against the finished, unchanged extraction.
- Before extraction: 23 English/Arabic preview cases, 11 component interaction
  cases and one connected real-API workflow passed. All are included in the
  final passing suites; 168 focused unit/source checks also passed after extraction.
- Chrome and Edge each passed seven groups with 12 English/Arabic scenes before
  and after extraction. Focus, requests and the known deletion error match exactly.
  Only existing periodic unread/catch-up polling is excluded from request counters.
- **All 24 paired scenes are pixel-identical**: the full maximized viewer frame,
  and ordinary component scenes below the animated 72px header. No masking or
  styling changes were used. One initial Chrome empty-state screenshot scrolled
  before the actual empty result rendered; a specific readiness check corrected
  the test. Both final Chrome runs use it. Edge's already-identical pair retains
  its exact recorded driver version, archived with its evidence.
- All 4,071 English/Arabic catalogue keys and artifact bytes remain unchanged.
  Catalogue references, approved Arabic terminology, configuration ownership,
  API template consistency and 24 runner-safety tests passed.
- **All 16 uniquely named disposable databases were removed**, independently
  confirmed through PostgreSQL's database catalogue, including failed attempts.

[Acceptance totals and archived evidence](verification/webui-refactor-phase6l/acceptance.json)
include source proof, final tests, browser comparisons and cleanup. Branch
`refactor-API-python-file` and HEAD `40bf384` remain unchanged. No commits or
pushes were made.
