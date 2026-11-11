# WebUI refactoring — existing defects and observations

This is a working register for the final WebUI-refactoring handoff. It will be
rechecked after Phases 7 and 8. The user requested a prioritized final list of all
pre-existing defects and abnormalities. Entries below distinguish established
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

## Existing UX limitations and unresolved observations

| Priority | Observation and certainty | Evidence | Recommended next action |
| --- | --- | --- | --- |
| P2 | The email-dialog keyboard boundary does not always wrap focus; Arabic Chrome/Edge differ and some runs put focus on the page body. Preserved baseline behavior, not an accessibility certification. | [Phase 2](webui-refactor-phase2-verification.md), keyboard results. | Review accessible focus containment and restoration across supported browsers. |
| P2 | Initial Phase 5 Edge custody-loading timeout did not recur in twelve subsequent checks. Cause and whether it was an original defect are unproven; the user explicitly accepted this recorded exception. | [Phase 5](webui-refactor-phase5-verification.md). | Retain diagnostics and investigate on recurrence; do not label it fixed. |
| P2 | One 6O aggregation-child save succeeded but two parent-refresh reads were cancelled. The exact trigger was not captured; original focused and subsequent full suites passed. Original-defect status is unproven. | [6O](webui-refactor-phase6o-verification.md); cancellation diagnostics retained. | Revisit in Phase 7 and capture cancellation ownership if it recurs. |
| P2 | An initial Edge record baseline showed an English subtitle in Arabic. Original/extracted reruns matched in Arabic. | [6N](webui-refactor-phase6n-verification.md). | Check localization readiness on repetition; preserve language/identity isolation. |
| P3 | One extracted Chrome record run performed an extra old-label security search and selected-ID resolution; unchanged rerun request counts matched the original. | [6N](webui-refactor-phase6n-verification.md). | Monitor selector echo/debounce readiness and redundant reads. |
| P3 | Native resizing can emit `ResizeObserver loop completed with undelivered notifications.` Drawer restoration also depends on transition timing; stable original/extracted geometry matched. | [Phase 5](webui-refactor-phase5-verification.md). | Investigate resize events separately; retain stable geometry and direction checks. |
| P3 | One Chrome translation session disconnected before its first check; later runs passed. Cause/application attribution is unproven. | [6J](webui-refactor-phase6j-verification.md). | Retain raw diagnostics and investigate only with a repeatable trigger or new evidence. |

## Test abnormalities addressed or still being recorded

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
