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

| Priority | Finding and user impact | Evidence | Recommended next action |
| --- | --- | --- | --- |
| P1 | Governed Move for aggregations and records references undefined `compatible_aggregations`; the dialog raises `NameError` before opening. | [6M](webui-refactor-phase6m-verification.md) confirms committed and pre-refactor copies. | Repair the destination lookup separately; verify permissions, bounded selectors and both move lifecycles. |
| P2 | A contained-record filter returning zero results removes its own filter control. Reload restores the unfiltered aggregation. | Original/extracted browser journeys in [6M](webui-refactor-phase6m-verification.md). | Preserve the filter and an empty-result state; test clearing/changing the query in both languages. |
| P2 | Removing a digital component succeeds, then its success notification uses a deleted UI slot. The error prevents the automatic refresh; reopening shows the saved result. | Original/extracted Chrome and Edge in [6L](webui-refactor-phase6l-verification.md). | Notify from a surviving UI context and verify refresh, cancellation and duplicate-click behavior. |
| P2 | Reopening a synthetic saved search containing a bare condition raises `ValueError: Invalid value: contains_ci`. Normal UI-created queries have an outer Boolean group. | Original/extracted check in [6R](webui-refactor-phase6r-verification.md). | Confirm supported saved-definition shapes; make the builder handle every supported shape without changing query semantics. |
| P2 | Dashboard favourite removal succeeds, but its confirmation notification raises a deleted-slot error after removing the row. | Both languages and both browsers, original/extracted, in [6S](webui-refactor-phase6s-verification.md). | Use a surviving notification context; retain successful removal and cache freshness. Review alongside component deletion. |
| P2 | Administration pagination passes Boolean `icon-right` to an icon renderer expecting a string, producing `TypeError: u.match is not a function`. | [6C](webui-refactor-phase6c-verification.md), with affected later consumers recorded in 6E–6G. | Correct the prop type and verify all affected pagers, icons and keyboard actions. |
| P3 | Legacy generic-table refresh callbacks reference undefined `card_host` (and a card-render callback outside its valid path). No failure was observed in the verified navigation flows; the 6N report records these as unreachable fallbacks. | [6N](webui-refactor-phase6n-verification.md); `collection_table.py` retains the feature renderer unchanged in Phase 8. | Audit supported callers before removing the dormant branches or repairing them. This is not an observed active-screen regression. |

## Existing UX limitations and unresolved observations

| Priority | Observation and certainty | Evidence | Recommended next action |
| --- | --- | --- | --- |
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

## Separately approved and corrected product defect

Phase 1 B1: aggregation reload/restoration left the containing details panel
hidden. The user explicitly approved its separate one-line visibility correction.
[Phase 2](webui-refactor-phase2-verification.md) records failing-before/passing-after
evidence. It belongs in the final history, not the open-fix backlog.

Phase 6T also corrected a queued-review test fixture missing the required unit
manager designation. Its 21-test artifact suite passes; application rules were
unchanged. See the [6T report](webui-refactor-phase6t-verification.md).
