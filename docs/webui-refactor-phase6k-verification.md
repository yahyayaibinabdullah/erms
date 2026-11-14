# Phase 6K — legal holds

**Status: complete for the approved local scope.** Changes remain local and uncommitted.
Chrome and Edge are the approved browser scope; Firefox, Safari and CI are deferred.

## Ownership

| Module | Existing responsibility moved |
| --- | --- |
| `holds.py` | Hold list, filters, paging and history/detail/editor destinations |
| `hold_details.py` | Detail view, contributors, held-resource filtering/selection, candidate picker, bulk operations and deletion |
| `hold_editor.py` | Create/edit form, versioned contributor follow-up and required-reason dialog |
| `hold_resources.py` | Add a resource to a hold; effective direct/inherited/restricted hold dialogs and returns |
| `holds_people.py` | Existing selector presentation, bounded typeahead, selected values, exclusions and stale-response/cancellation handling |
| `hold_navigation.py` | Existing privilege/visible-hold navigation visibility rule |

The host supplies two narrow page-entry callbacks and existing destination
callbacks. Feature filters, paging and selection retain their original per-view or
per-dialog lifetime. No host state dictionary is passed into the modules. History
and cyclic destinations are deferred until invoked, preserving assembly order.
The root re-exports the existing public person-selector styling helper.

Source reconstruction matches all nine moved functions/helpers; the other 91
host functions are identical. No UI strings, routes, browser-history behavior,
API contracts, database schema, caches or translation artifacts were changed.

## Requirement → verification

| Existing behavior | Evidence |
| --- | --- |
| Required reasons; synchronous/asynchronous actions; API-error retention | Original/after interaction tests |
| Create/edit validation, owner exclusion, UTC payloads, version/reason and contributor update | Original/after editor interaction tests and real-API edit journey |
| Manageable-hold selection, 25-row paging bound, required reason, attachment errors and refresh | Original/after attachment interaction tests |
| Direct, inherited and restricted effective holds; assigning-aggregation link; versioned direct removal | Original/after effective-hold interaction tests |
| People minimum query length, 25-person bound, selected values, exclusions and obsolete-response rejection | Two new behavior tests plus retained source contracts |
| Navigation privilege shortcuts, one-row fallback lookup and failure visibility | Five original/after navigation behavior cases |
| Contributors, bulk attachment/removal, effective hold, non-empty deletion restriction and empty deletion | Original/after connected real-API workflow |
| English/Arabic appearance, list paging/empty results, keyboard focus, dialogs/cancellation and navigation/history | Original/after Chrome and Edge journeys |
| Other callers and application behavior | Full unit, interaction and assembled regression gates |

## Findings and corrections

- Fixture correction: restricted effective-hold responses still contain a source;
  the synthetic interaction row now follows that existing response shape.
- The hold filter-people endpoint returns identities already used by holds. The
  lifecycle fixture obtains a contributor through bounded `active_people` search.
- Nested reason dialogs open asynchronously; the real-API test explicitly waits
  for the reason dialog's confirmation control instead of selecting the old editor.
- The first assembled run caught an extraction wiring error: the history callback
  was supplied before its owner was assembled. Both holds connections now use
  deferred callbacks. The original function bodies remain unchanged. Browser
  services started with the initial wiring failed readiness and are retained as
  failed attempts; final acceptance uses fresh runs of the corrected assembly.
- Source-location assertions were redirected to the owning modules, including the
  candidate scroll area formerly counted with personal-resource scroll areas.
  Existing assertions and behaviors were retained.

## Final verification

- **1,618 unit tests, 326 interaction tests and 60 assembled tests passed** against
  the corrected, unchanged extraction.
- Before extraction: 14 dialog/selector interaction tests, five navigation behavior
  tests and the connected real-API hold lifecycle passed. The 14 interaction tests
  also passed immediately after extraction.
- Chrome and Edge each passed nine groups and captured 20 English/Arabic scenes,
  before and after extraction. Keyboard focus and request counters match exactly,
  excluding only existing periodic unread/catch-up polling. Hold list requests
  retain their 25-row bound; navigation visibility retains its one-row bound.
- Below the animated header, 39 of 40 paired scenes are pixel-identical. Eight
  antialiasing pixels at the rounded corners of a background search field differ
  by at most 2/255 in one Chrome scene. Raw images were inspected; no masking or
  UI style changes were used.
- All 4,071 English/Arabic catalogue keys and both artifacts remain unchanged.
  Catalogue references, approved Arabic terminology, configuration ownership,
  API template consistency and 24 runner-safety tests passed.
- **All 11 uniquely named disposable databases were removed**, confirmed by the
  runners and an independent PostgreSQL catalogue audit.

[Acceptance totals and archived evidence](verification/webui-refactor-phase6k/acceptance.json)
include source reconstruction, final test results, browser images/comparisons and
cleanup. Failed development attempts remain in the local runtime evidence and are
explained above. No product behavior was changed to accommodate the tests.
Git history and the user's branch remain unchanged.
