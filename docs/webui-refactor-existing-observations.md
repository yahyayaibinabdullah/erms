# WebUI refactoring — existing defects and observations

This register collects all defects and abnormalities recorded during the WebUI
refactor, in recommended investigation/fix order. Phase 8 final acceptance is
recorded separately in the [verification report](webui-refactor-phase8-verification.md). Entries below distinguish established
original defects from observations whose cause or original status is unproven.
No open entry is authorized for a product fix as part of this refactor.

Priority means recommended order for investigation/fixing, not an agreed delivery
schedule: **P1** blocks an existing workflow; **P2** impairs use or warrants
reliability/accessibility investigation; **P3** is a lower-impact warning or test issue.

## Reproduced original product defects

The previously listed generic-table callback defect has now been repaired under
separate authorization; see the corrected section below. The legacy presentation
and pagination limitations remain listed separately.

## Existing UX limitations and unresolved observations

| Priority | Observation and certainty | Evidence | Recommended next action |
| --- | --- | --- | --- |
| P2 | The restored legacy scheme table has client pagination over its bounded server page, without equivalent server-page controls. The dedicated workspace remains the complete menu destination. This old-view completeness limitation is preserved by the callback repair. | [Scheme refresh report](classification-scheme-refresh-fix-verification.md); `collection_table.py` and `collection_controls.py`. | Review legacy paging or explicitly approve how old navigation should reach the current workspace; do not silently redirect saved navigation. |
| P3 | The restored legacy scheme table uses the default “Dashboard” heading and retains English action tooltips/date formatting in Arabic. These existing display quirks are unchanged. | [Scheme refresh report and captures](classification-scheme-refresh-fix-verification.md). | Review old-view labels and date localization separately. |
| P2 | The email-dialog keyboard boundary does not always wrap focus; Arabic Chrome/Edge differ and some runs put focus on the page body. Preserved baseline behavior, not an accessibility certification. | [Phase 2](webui-refactor-phase2-verification.md), keyboard results. | Review accessible focus containment and restoration across supported browsers. |
| P2 | Some accessible labels remain English in Arabic, including breadcrumb overflow and favourite controls. | [Phase 1](webui-refactor-phase1-baseline.md), original English/Arabic inspection. | Audit translated accessible names and screen-reader behavior separately; preserve current wording during this refactor. |
| P3 | An audit-event Settings link selects the correct category but does not automatically focus the target field. This is recorded baseline behavior, not a new regression. | [Phase 2](webui-refactor-phase2-verification.md), caller coverage. | Review whether a separate UX change should add target-field focus; preserve existing behavior until approved. |
| P2 | Initial Phase 5 Edge custody-loading timeout did not recur in twelve subsequent checks. Cause and whether it was an original defect are unproven; the user explicitly accepted this recorded exception. | [Phase 5](webui-refactor-phase5-verification.md). | Retain diagnostics and investigate on recurrence; do not label it fixed. |
| P2 | One 6O aggregation-child save succeeded but two parent-refresh reads were cancelled. The exact trigger was not captured; original focused and subsequent full suites passed. Phase 7's full assembled suite and two independent focused reruns also passed without recurrence. Original-defect status is unproven. | [6O](webui-refactor-phase6o-verification.md); cancellation diagnostics retained. [Phase 7](webui-refactor-phase7-verification.md) records the passing full suite and two independent focused reruns. | Retain cancellation-ownership diagnostics and investigate on recurrence; do not label it fixed. |
| P2 | An initial Edge record baseline showed an English subtitle in Arabic. Original/extracted reruns matched in Arabic. | [6N](webui-refactor-phase6n-verification.md). | Check localization readiness on repetition; preserve language/identity isolation. |
| P3 | One extracted Chrome record run performed an extra old-label security search and selected-ID resolution; unchanged rerun request counts matched the original. | [6N](webui-refactor-phase6n-verification.md). | Monitor selector echo/debounce readiness and redundant reads. |
| P3 | Native resizing can emit `ResizeObserver loop completed with undelivered notifications.` Drawer restoration also depends on transition timing; stable original/extracted geometry matched. | [Phase 5](webui-refactor-phase5-verification.md). | Investigate resize events separately; retain stable geometry and direction checks. |
| P3 | One Chrome translation session disconnected before its first check; later runs passed. Cause/application attribution is unproven. | [6J](webui-refactor-phase6j-verification.md). | Retain raw diagnostics and investigate only with a repeatable trigger or new evidence. |
| P2 | A Phase 7 repeated-navigation benchmark on the original UI in Edge stopped while opening a record: the effective-holds read raised `ApiError` before appearing in the API request log, leaving the details incomplete. The transport cause and production relevance are unproven. | [Phase 7 investigation](webui-refactor-phase7-verification.md); failed original run retained. | Capture the underlying transport exception and verify recovery; do not attribute this original-run observation to extraction or silently fix it. |
| P2 | One Phase 7 Edge timing run lost its WebDriver session when the browser closed the renderer connection. The last API calls succeeded; application attribution and the cause remain unproven. | [Phase 7 investigation](webui-refactor-phase7-verification.md); failed run and subsequent driver diagnostics retained. | Investigate on recurrence with driver diagnostics; do not label the disconnect fixed or infer its cause from a passing rerun. |
| P3 | Phase 7 retained smaller repeatable timing increases and isolated larger spikes despite passing the approved consistency threshold. API timing variation explains part of some samples, not every remaining difference. | [Phase 7 timing review](verification/webui-refactor-phase7/performance-review.json). | Monitor with the same controlled protocol; investigate repeatable increases and block the agreed material regressions. Do not describe the result as identical latency. |
| P3 | Native Edge diagnostics include macOS display-link and updater permission warnings. | [Phase 7](webui-refactor-phase7-verification.md), retained driver logs. | Investigate separately if they correlate with reproducible test instability; no system-setting changes are authorized by the refactor. |

## Phase 8 verification observations

- **P2 timing follow-up, attribution unproven:** Phase 8's first Edge pair had a
  361.2 ms / 244.8% Arabic-dashboard p90 increase and a 212.2 ms / 24.1% cold-load
  increase. The reverse pair showed only 26.4 ms / 18.7% and 24.4 ms / 2.8%, so
  neither met the approved repeated blocking gate. The large dashboard cycles had
  short API calls; exact frontend/transport/browser attribution remains unproven.
  All 22 repeatably slower metrics were reviewed, and 80 request comparisons match.
  Monitor on recurrence; do not label these observations fixed or established
  pre-existing product defects. See the [timing review](verification/webui-refactor-phase8/performance-review.json).

- **P3 test interaction:** the first Edge translation journey passed English
  Inspector, then WebDriver's click on the language selector's internal input was
  intercepted by a text span before Arabic testing. Original and unchanged current
  diagnostic repeats passed all 11 groups in both languages. No application or
  tracked harness code was changed. The exact timing/overlay cause remains
  unproven; investigate on recurrence using the retained hit-test diagnostics.
- **Rendering environment:** older captures reserved native scrollbar space;
  resumed captures use overlay scrollbars. Fresh original/current runs reproduce the same layout, and all 58 focus
  observations per browser match. Historical comparisons and raw captures remain
  retained. No application CSS or system setting was changed.

## Deferred verification, not proven product defects

- **P2 verification follow-up:** complete Firefox and Safari checks when authorized.
  Firefox's last Phase 2 attempt completed 43 checks before the old favicon
  classification failed; an earlier browser error did not recur. Safari completed
  13 checks before a dialog-opening timeout. Neither is a passing final acceptance
  run or proof of an application defect. See the [Phase 2 partial results](webui-refactor-phase2-verification.md).
- **P3 verification follow-up:** execute the prepared CI checks when authorized.
  Local acceptance does not claim remote CI or production-scale performance.

## Test abnormalities and verification limitations

- Phase 8 found that some tests imported extracted helpers indirectly through
  `app.py` or compiled feature functions with the old root's globals. Tests now
  use the actual feature owners/factories, retaining behavior assertions. A new
  preview test's event callback argument was corrected during development.
  Interrupted and failed development attempts remain separate from acceptance.
- Phase 7 timing instrumentation repeatedly opened log files on the measured
  event loops and reread whole logs while polling. Stack samples and a direct
  I/O probe showed substantial test-only stalls. Persistent append handles and
  incremental readers replace that instrumentation; safety tests cover flushing,
  incomplete lines and cleanup. Initial timing results remain recorded and the
  complete comparison passed after repeating it with corrected instrumentation.
  No application code was changed.
- Phase 7 Edge diagnostics initially enabled verbose WebDriver command logging,
  adding substantial I/O. Those runs are excluded from performance acceptance.
  The final comparison pins one existing driver binary and warning-only logging.
  Browser version stayed unchanged; a different automatic driver selection was
  observed, but it is not established as the cause of the earlier disconnect.
  A first pinning wrapper failed during setup and was corrected before testing.
- Phase 1 T1–T5 identified stale structural/permission assertions, UI-context
  isolation and asynchronous locator/readiness problems. [Phase 2](webui-refactor-phase2-verification.md)
  records their test corrections and passing replacement evidence.
- Later harness corrections (selectors, translated labels, active-page identity,
  debounce/disclosure readiness, synthetic schema fields and fixed dates) are
  documented in each phase report. They are test defects, not established product defects.
- Phase 1 B2: the disposition preview omitted mandatory reviewer designations.
  Phase 6T repairs the disposable fixture while retaining all canonical gates.
- Phase 6T: older integrated backend journeys assumed certificate generation and
  downloading implicitly completed the job. Tests now follow the approved explicit
  final-task completion contract and separately request optional certificate email.
- Phase 6T/6U: the footer retry test's fixed 20ms click wait could assert while
  NiceGUI's background action was still busy. Phase 6U reproduced this with a
  50ms fixture refresh in both languages. The helper now awaits the actual
  scheduled callback; all 20 footer tests and the final 1,628-unit suite pass.
  **Resolved P3 test issue**, not a product fix. See the
  [6U diagnosis and evidence](webui-refactor-phase6u-verification.md).
- Phase 6U development fixtures initially used an officer without messaging
  exchange permission and expected deletion of an uncaptured new message. Tests
  now supply an eligible disposable recipient and assert the existing retention
  protection. Native draft deletion/restoration and existing mailbox-restore
  cases retain that coverage; application rules are unchanged.

## Separately approved and corrected product defects

Classification-scheme refresh P3: the user separately approved repairing the
remaining legacy callback while preserving saved navigation. It now reloads the
bounded table using its actual lifetime, with no read/repaint after navigation.
The related invalid default sort and translated lifecycle API path are also
corrected. Chrome and Edge passed publication, deactivation and reactivation
through restored legacy navigation in English and Arabic; 115 focused tests
passed. Changes remain local and uncommitted; see the
[verification report](classification-scheme-refresh-fix-verification.md).

Administration pagination icon P2: the user separately approved repairing the
Boolean `icon-right` defect. Five invalid prop tokens were removed from the shared
administration, login-session and text-indexer credential pagers, preserving the
existing valid icons and paging behavior. All seven consumers passed Chrome and
Edge checks in English and Arabic; 101 focused tests passed. Maintained browser
journeys now reject the old error. Changes remain local and uncommitted; see the
[verification report](pagination-icon-fix-verification.md).

Favourite identity labels P2 and View all close-on-removal P3: the user separately
approved both fixes. Rows now use the correct resource-specific number; the dialog
is attached to the dashboard container and stays open through removal, including
its empty state. Chrome and Edge passed records and aggregations in English and
Arabic, with 64 focused tests passing. The changes remain local and uncommitted;
see the [verification report](dashboard-favourite-details-fix-verification.md).

Dashboard favourite-removal notification P2: the user separately approved this
repair. The success notification now uses the surviving favourites container
after the originating row is deleted. Chrome and Edge passed records and
aggregations in English and Arabic, through both dashboard and View all actions;
64 focused tests passed. Cached state, updated counts and empty states are verified.
The label and dialog-lifecycle issues were subsequently corrected in the approved
follow-up above. The notification fix
is local and uncommitted; see the
[verification report](dashboard-favourite-fix-verification.md).

Saved-search reopening P2: the user separately approved repairing standalone
condition loading. The shared loader supplies the builder's required outer AND
group without changing query meaning or modifying the stored definition on open.
Chrome and Edge passed records and aggregations in English and Arabic, including
execution, clean navigation, editing, saving and reopening; 100 focused tests
passed. The first Chrome attempt timed out at the Arabic picker; a diagnostic
rerun passed without application changes, and the unproven timeout is retained
separately. The fix remains local and uncommitted; see the
[verification report](saved-search-reopening-fix-verification.md).

Digital-component deletion P2: the user separately approved repairing the
deleted-slot notification and blocked refresh. Feedback and refresh now use the
surviving component container, including error feedback after rollback. Chrome
and Edge passed in English and Arabic, with eight successful deletions in total;
197 focused tests passed. Immediate deletion, wording and layout are preserved.
The fix remains local and uncommitted; see the
[verification report](component-deletion-fix-verification.md).

Contained-record filter P2: the user separately approved keeping the filter
available after a zero-result query. A one-line rendering condition now shows
the existing filtered-empty state, allowing users to change or clear the query
and press Enter without reloading. Chrome and Edge passed in English and Arabic,
including paging and record-return recovery; 167 focused tests also passed.
The genuinely empty aggregation display is preserved. The fix remains local and
uncommitted; see the [verification report](contained-record-filter-fix-verification.md).

Governed Move P1: the user approved repairing the undefined
`compatible_aggregations` reference after the refactor. Both dialogs now open and
use recoverable bounded destination search. Chrome and Edge passed aggregation and
record moves in English and Arabic, with 219 focused tests passing. The change is
local and uncommitted. See the [fix report](governed-move-fix-verification.md).

Governed Move P2/P3 follow-up: the user separately approved correcting the subtree
counts and Arabic titles. The UI now reads the existing API count fields and uses
the existing translated singular resource names. These two display defects are
corrected locally; see the [follow-up verification report](governed-move-details-fix-verification.md)
for test evidence and final browser status. Catalogue wording and provenance are unchanged.

Phase 1 B1: aggregation reload/restoration left the containing details panel
hidden. The user explicitly approved its separate one-line visibility correction.
[Phase 2](webui-refactor-phase2-verification.md) records failing-before/passing-after
evidence. It belongs in the final history, not the open-fix backlog.

Phase 6T also corrected a queued-review test fixture missing the required unit
manager designation. Its 21-test artifact suite passes; application rules were
unchanged. See the [6T report](webui-refactor-phase6t-verification.md).
