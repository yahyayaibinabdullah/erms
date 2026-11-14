# Phase 6M — aggregations

**Status: complete for the approved local scope.** Changes remain local and uncommitted.
Chrome and Edge are the approved browser scope; Firefox, Safari and CI are deferred.

## Ownership

| Module | Existing responsibility moved |
| --- | --- |
| `aggregation_state.py` | Per-client hierarchy, mode, child paging, selected detail and return anchors |
| `aggregation_browser.py` | Browse/search mode, classification hierarchy, branch loading and restoration |
| `aggregation_details.py` | Detail presentation, children/records, location, vital/review, closure, relationships, holds and actions |
| `aggregation_actions.py` | Reopening, governed movement and ownership correction |
| `aggregation_selector.py` | Shared bounded classification/aggregation picker |
| `aggregation_toolbar.py` | Contextual aggregation/record creation actions |
| `aggregation_editor.py` | Nine existing aggregation-specific editor hooks: creation context, roles, inheritance, classification/parent constraints and payload validation |
| `aggregation_presentation.py`, `relationship_select_styles.py` | Existing labels, closure lookup, constants and shared relationship-chip presentation |

Seven aggregation-only state keys now have their own per-client dictionary.
Defaults, refresh policy, expansion/page restoration, authentication cleanup and
return paths are unchanged. Shared page identity, principal and relationship
request token use narrow callbacks. Cyclic record/editor/history destinations
remain deferred callbacks. No whole application state or app import enters a feature.

Source reconstruction confirms all 13 moved functions, all nine editor blocks,
and the other 117 host/top-level functions retain their behavior. Only `app.py`
changed among pre-existing runtime files. Catalogue and inspector bytes are unchanged.

## Requirement → verification

| Existing behavior | Evidence |
| --- | --- |
| Reopen reason, versioned update, success and API failure | Original/extracted interaction cases |
| Ownership options, current-owner exclusion, preview, reason, validation and failed writes | Original/extracted interaction cases |
| Governed move selector compatibility | Original/extracted interaction cases, including the recorded original failure below |
| Branch paging, expansion/return state and ignored abandoned responses | Four original/extracted browser interaction cases; Chrome/Edge hierarchy journeys |
| Child creation, inherited parent/classification/medium and metadata | Original/extracted real-API lifecycle |
| Location, vital status, review date, close and reopen freshness | Original/extracted real-API lifecycle |
| Independent child/record paging, contained-record return and empty filter | Chrome/Edge English/Arabic journeys |
| Metadata Tab focus and action-dialog Escape behavior | Chrome/Edge English/Arabic journeys |
| Access, holds, component links, shared editor and other destinations | Full unit, interaction and assembled regression gates |

## Original behavior preserved

The governed move dialog references undefined `compatible_aggregations`, raising
`NameError` before it opens for both aggregations and records. The same defect
exists in committed HEAD and pre-Phase-6 snapshots. Tests record that baseline;
this extraction does not repair it or claim successful movement coverage.

A contained-record filter with no results renders the existing “does not contain
any records” branch and removes its filter control. Reloading restores the
unfiltered detail page. Original and extracted browser journeys check this exact
behavior. Both findings require separate approval for a product fix.

Browser-test development corrected drawer/button scoping, required-field labels,
debounce readiness, duplicate pager ARIA labels, the seeded classification path
and the actual hierarchy page size. Source-location tests now inspect the new
owners, retaining their original assertions.

## Verification

- 1,624 unit, 345 interaction and 62 assembled real-API tests passed.
- The original implementation passed 12 focused aggregation interaction/browser
  cases and one real-API lifecycle. The extracted implementation also passed 22
  focused interaction cases and the same real-API lifecycle.
- Chrome and Edge each passed seven groups before and after extraction, with
  22 English/Arabic scenes per journey. **All 44 paired scenes are pixel-identical
  below the existing animated 72px header.** Focus, paging controls, navigation
  behavior and request counts match. Only existing message catch-up/unread polling
  is excluded from request counters.
- The first passing visual journeys navigated while recent-item hydration was
  still running, producing different counts of cancelled background reads. The
  final driver waits for the existing personal-panel loading indicators to finish.
  Both final before/after pairs use that same check and have identical request
  counters. No application behavior or test assertion was weakened to obtain parity.
- All 4,071 English/Arabic keys and catalogue artifact bytes are unchanged.
- **All 19 Phase 6M disposable databases were removed**, including failed
  test-development attempts, independently verified against PostgreSQL's catalogue.
- Catalogue references, approved Arabic terminology, configuration ownership,
  API template consistency and 24 runner-safety tests passed.

No functionality, UI, UX, text, translation, API, schema, public URL or browser-history
change is introduced. Branch `refactor-API-python-file` and HEAD `40bf384` remain
unchanged; no commits or pushes were made.

[Acceptance totals and archived evidence](verification/webui-refactor-phase6m/acceptance.json)
contain the source reconstruction, tests, browser comparisons and cleanup audit.

## Stop boundary

At the user's latest instruction, work stops after 6M pending explicit approval.
No 6N runtime extraction was performed. Record/capture test drafts prepared before
that instruction are parked outside the active suite in the ignored runtime
directory. Their three disposable test databases were also removed and independently
verified; the separate cleanup audit is included with this report's evidence.
