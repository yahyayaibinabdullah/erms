# Dashboard favourite removal — notification context

**Status: fixed and locally verified on 12 November 2026.**
The user separately authorized this repair after the WebUI refactor. All changes
remain local and uncommitted on `refactor-API-python-file`; earlier work is preserved.

## Cause and correction

Removal succeeds and redraws the favourites panel and, when open, the complete
list dialog. This deletes the clicked row. The subsequent success notification
tries to obtain its client through the deleted row's NiceGUI slot and raises
`RuntimeError: The parent element this slot belongs to has been deleted.`

The existing success notification now runs inside the surviving favourites
container. Its text, colour and timing after removal remain unchanged. The fix
does not alter deletion, error handling, list rendering, cache updates, navigation,
layout or permissions. It adds no request or cache. The only application file
changed by this follow-up is `frontend/webui/dashboard.py`.

## Requirement → verification

| Requirement | Verification |
| --- | --- |
| Notify after the clicked row is gone | Real dashboard factory and real NiceGUI notifier, releasing the removed row before notification |
| Cover records and aggregations, English and Arabic | Parameterized interaction cases and native browser journeys |
| Support dashboard and View all removal | Both entry points, remaining-item and last-item cases |
| Preserve visible counts and existing dialog lifecycle | Native badge, row-count and empty-state assertions; reopen View all after its existing close-on-redraw behavior |
| Preserve personal state and cached summary | Exact favourite-ID and cached-list assertions; held-refresh navigation checks |
| Preserve error and abandonment behavior | Rejected request leaves favourites intact with negative feedback; abandoned view receives no stale feedback or cache mutation |
| Avoid duplicate writes or extra loading | One DELETE per tested click; existing single-flight warm-refresh checks |

## Verification

- **36 interaction tests passed**: 32 new removal cases and four existing dashboard
  identity/cache cases. The new cases invoke the actual feature factory.
- **28 related unit tests passed** for session isolation and feature boundaries.
  Total: **64 focused tests**, with network/database access blocked.
- Before the fix, the corrected regression reproduced the deleted-slot exception
  in all 16 successful-removal cases; the 16 rejection/abandonment cases passed.
- **Chrome 157.0.8103.40 and Edge 157.0.4341.46 passed**, each with nine check
  groups and 16 screenshots, covering English/LTR and Arabic/RTL. Across both
  final runs, 20 UI removals succeeded (plus four explicit API removals used to
  exercise warm-refresh freshness). Each tested removal shows the existing
  translated success notification; counts, empty states and reopened lists agree.
- Keyboard navigation, connected record details, single-flight background refresh
  and warm cached state pass. Captures were visually reviewed in both browsers
  and directions. No browser errors, unsuccessful API requests or server
  tracebacks occurred in either final run.
- All 186 recorded source hashes per final run match the current application and
  harness. Screenshot and regression-test source hashes are retained.
- Catalogue coverage, approved Arabic terminology, ordered active-key coverage,
  placeholders, nonblank wording and provenance checks pass. Catalogue hashes
  are unchanged. Configuration authority and API template checks pass, changed
  Python modules compile, and `git diff --check` passes.
- All **six uniquely named disposable PostgreSQL databases** were initialized by
  the canonical runner and dropped, including the four unsuccessful native
  test-development attempts. An independent catalogue query confirms cleanup;
  no owned test processes or native drivers remain. No persistent database was
  used for these tests.

This is focused local verification, not a full-suite, CI or timing benchmark.
The maintained native journey uses the `dashboard` scope of
`tools/run_webui_integration.py`. It also retains keyboard navigation, connected
record details and non-destructive warm-refresh coverage.

No user-visible text or translation key changes. Both catalogues, including Arabic
wording and provenance, remain unchanged. No translation export or persistent
database translations are modified; no new translation review is required.

## Test-development notes

The first fixture attempt omitted unused feature dependencies; the second invoked
NiceGUI's button event wrapper without its event argument. Those fixture issues
were corrected before establishing the failing-before result. Both attempts are
retained separately from acceptance. No application changes were needed for them.

The first native runs verified the existing record-removal notification, then the
new locator expected `TEST-REC` in a favourite row. Inspection showed the existing
row says `Record · TEST-AGG`: its renderer prefers `aggregation_number` even for
records that also have a record number. The same expression is present in HEAD
before this repair. The locator now uses the unique synthetic title. Both failed
attempts and screenshots are retained; application rendering was not altered.
This separate display defect is recorded for later approval, not counted as fixed.

The next native attempt confirmed successful notifications for dashboard and
View all removal, but the test incorrectly expected View all to remain open.
Its dialog is created inside the panel's event slot, so redrawing that panel also
deletes the dialog. The interaction fixture initially opened it under the page
root and missed this lifetime relationship. The corrected fixture uses the real
opening button's parent slot and asserts the existing dialog deletion; all 36
interaction tests still pass. Running the corrected tests against the captured
pre-fix factory in memory again produces the same 16 deleted-slot failures and
16 rejection/abandonment passes. No working-tree application source was replaced.
The native journey now reopens View all for the next removal and verifies the
remaining list and final empty state. Dialog persistence is a separate UX review.

## Retained evidence

- [Acceptance record](verification/dashboard-favourite-fix/acceptance.json)
- [Chrome results](verification/dashboard-favourite-fix/chrome/browser-results.json)
  and [Edge results](verification/dashboard-favourite-fix/edge/browser-results.json)
- [Focused comparison](verification/dashboard-favourite-fix/focused-comparison.json),
  [interaction tests](verification/dashboard-favourite-fix/interaction/tests.xml)
  and [unit tests](verification/dashboard-favourite-fix/unit/tests.xml)
- [Corrected pre-fix failures](verification/dashboard-favourite-fix/before-event-context/tests.xml)
- [Validation](verification/dashboard-favourite-fix/validation.json),
  [database cleanup](verification/dashboard-favourite-fix/database-cleanup.json)
  and [process cleanup](verification/dashboard-favourite-fix/process-cleanup.json)
- [Separate record-number observation](verification/dashboard-favourite-fix/record-number-observation.json),
  [dialog lifecycle attempt](verification/dashboard-favourite-fix/chrome-dialog-attempt/browser-results.json)
  and [file hashes](verification/dashboard-favourite-fix/manifest.sha256)

The notification defect is corrected. The record-number label and View all
close-on-redraw observations remain separate entries in the
[defect register](webui-refactor-existing-observations.md).
No branch, worktree, staging, commit, history, remote or system-setting changes
were made. Everything remains local and uncommitted on the user's branch.
