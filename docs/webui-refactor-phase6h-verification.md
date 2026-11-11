# WebUI refactor: Phase 6H — Text-indexer administration

**Status:** Complete for the approved local scope.

## Ownership and preserved behavior

The existing list, health/diagnostics view and operational dialogs belong to
`text_indexers.py`. Account status and credential history belong to
`text_indexer_details.py`; the one-time key dialog belongs to
`text_indexer_credentials.py`. The root supplies shell elements, navigation,
existing error/format helpers and explicit record/component destinations.

List filtering and its existing client paging stay local to each opened view.
Diagnostics retain server pages of 10; credential history retains server pages
of 5 and its existing empty-page fallback. No cache or route is introduced.
The legacy generic service-account branch remains with User Details; authorized
indexer accounts retain the existing redirect to their dedicated feature.

No API, schema, layout, text, translation, URL or history behavior changes.
The source proof reconstructs all three original functions after replacing only
shell-entry and direction callbacks, and compares every other direct host
function. No feature imports the root or receives its shared state dictionary.

## Requirement-to-verification map

| Requirement / callers | Owner and evidence |
| --- | --- |
| List, filtering, empty state, health and operational controls | `text_indexers.py`; original/extracted interaction tests, real-API backfill and disabled empty-retry checks; EN/AR Chrome/Edge journeys |
| Diagnostic paging, denied links, record/component destinations and failures | `text_indexers.py`; bounded request assertions and both permitted/denied destination tests |
| Account suspension/reactivation and credential action restrictions | `text_indexer_details.py`; interaction and real-API lifecycle checks |
| Credential generation, rotation, revocation, cancellation and error retention | `text_indexer_details.py`; six success/error interaction cases and real-API lifecycle |
| One-time secret handling, copy/download and close follow-up | `text_indexer_credentials.py`; original function reconstruction, synthetic-only reveal tests; real secrets never included in browser evidence |
| History paging, filter reset, errors and freshness after writes | `text_indexer_details.py`; exact limit/offset assertions, retained source contracts and real-API rereads |
| Organization/user, role and navigation callers | Explicit destination callbacks; full assembled drawer coverage and unchanged source proof |
| Language, direction, focus, appearance and navigation | Original/extracted Chrome/Edge EN/AR comparisons; no history/URL change |

## Findings

The baseline tests initially used ambiguous labels shared by page and dialog
buttons. They now scope those controls to their owners. Retry remains disabled
when health reports no failed documents; mock fixtures explicitly provide a
failure when testing the enabled workflow. Browser cancellation checks exclude
only the fixture's initial account-creation request, not user actions.

The existing Boolean `icon-right` pagination error is counted separately in
credential details. Health observation timestamps are live data and their raw
screenshot regions are recorded for comparison. No application fix is included.

## Verification results

| Check | Result |
| --- | --- |
| New original behavior tests | 21 interaction and 2 real-API tests passed |
| Extracted focused tests | 28 passed |
| Full final unit / interaction / assembled suites | 1,603 / 285 / 57 passed |
| Chrome and Edge, original and extracted | All 7 groups and 12 scenes per journey passed in English/Arabic |
| Browser comparison | Equal focus and request counts; every pixel outside the animated header and live observation timestamp regions matches |
| Source comparison | All three moved functions reconstruct exactly; 112 other direct host functions unchanged |
| Translations and configuration | All 4,071 keys and artifact bytes preserved; reference/terminology/configuration/template checks pass |
| Runner safety | 24 passed |
| Disposable databases | All 12 unique databases removed; independent PostgreSQL catalogue audit passed |

The first assembled run caught two organization callbacks being bound before
the extracted functions existed. Deferred callbacks fixed the wiring; the full
57-test run above uses the final source. An original Edge test changed language
before its return to the indexer list had completed. The test now waits for the
list's unique filter control; the settled original/extracted pair matches.

The new browser dispatcher initially omitted its completion flag. All seven
checks passed, but the runner consequently returned 1. Raw reports and exit
codes are preserved. The one-line reporting correction has a dedicated runner
contract test, included in the 24 passing checks; no application change was
needed. Acceptance verifies all expected checks, scenes and source hashes,
rather than rewriting those raw reports.

Firefox, Safari and CI remain deferred. Evidence is in
`docs/verification/webui-refactor-phase6h/`; original snapshots and intermediate
failures remain in `.runtime/webui-refactor-phase6h/`. No credential values are
included in browser evidence. No translation or operator action is required.
All changes remain local and uncommitted on the user's branch.
