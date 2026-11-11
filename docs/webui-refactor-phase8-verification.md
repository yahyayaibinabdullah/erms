# Phase 8 — Cleanup and final verification

**Status: complete for the approved local Chrome/Edge scope.** The user authorized Phase 8 with no functionality or UX
changes, local uncommitted work, and a final prioritized defect list. Chrome and
Edge are the approved local browser scope; Firefox, Safari and CI remain deferred.

## Cleanup and preserved behavior

The starting branch was `refactor-API-python-file`, HEAD
`9fdf51279e1db78597118c2df05b3467c8b7190e`, with a clean working tree. No branch,
commit, history, remote or worktree operation is part of this phase.

Only two application runtime files change:

- `app.py`: remove 153 unused imports left after extraction, a duplicated
  classification search-field constant, an unused audit entity-type mapping,
  an unused favourites renderer alias, and the uncalled `favourite_preview`
  helper. Remove blank extraction gaps without touching multiline CSS/JS.
- `session_context.py`: replace the temporary one-key identity dictionary with
  the page's `principal` and an explicit setter. Update every root read/write
  and injected identity callback. The API client, principal object identity,
  initialization and cleanup order remain unchanged.

An AST comparison applies only those enumerated transformations to the starting
root and verifies it matches the result. CSS/head-HTML values and root message
keys match exactly. The other 150 files in the runtime/catalogue hash inventory
are unchanged. No new cache, endpoint, setting, route or browser-history entry
is introduced. Existing product defects are preserved.

Active shell entry, navigation snapshot/restore and cross-feature callbacks
remain. Deferred lambdas connect controllers constructed later in the page;
removing them would break initialization. Reusable presentation functions in
feature modules are retained. Removing an unused root binding does not remove
its feature module's API or translations.

## Tests and developer guidance

Tests now import extracted helpers from their owners rather than incidental
`app.py` reexports. AST-isolated fixtures resolve feature globals from the actual
owner; hold dialog/selector tests now call the real factories. Existing behavior
assertions remain. The unused favourites helper's two synthetic slicing
assertions are replaced by 12 rendered tests: records/aggregations, English/Arabic,
and empty/exact-limit/over-limit lists, including opening the complete list.
Two architecture guards reject runtime feature imports of `app.py` and passing
the whole shell state to another component.

The developer guide now records final ownership, page-scoped state, callback
construction, testing and current deferrals. It no longer describes extracted
feature logic or the identity adapter as pending migration work.

Development attempts are retained separately from acceptance. The first
interaction check exposed old test dependencies on removed root imports and
was interrupted to inspect them. Later focused runs identified the remaining
hold fixture dependencies and a missing event argument in the new preview test.
Those were test-fixture corrections; no application behavior was changed to make
them pass. No failed or interrupted attempt counts as acceptance evidence.

An execution interruption stopped the first Chrome session journey before its
database cleanup. Its owned service/driver processes were confirmed absent;
only its recorded disposable database was then dropped and recovery recorded.
The session journey restarts in a new database. The already completed full
Chrome/Edge journeys are retained; the interrupted attempt is not a passing run.

## Acceptance gates

- Full unit suite: **1,630 passed**.
- Full NiceGUI interaction suite: **432 passed**.
- Full assembled application/real API: **74 passed**; disposable database removed.
- Configuration ownership, API template synchronization, catalogue references
  and approved Arabic terminology: **passed**.
- Chrome and Edge full journeys: **42 groups each passed**.
- Chrome and Edge session journeys: **6 groups each passed**. The accepted Chrome
  result is `session-chrome-resumed`; the interrupted first attempt is retained.
- Native Chrome/Edge: **182 groups passed across 12 selected runs**, with
  **384 screenshots**. This includes 120 destination visits and 58 keyboard-focus
  observations per browser, collections, session isolation/reconnect and dedicated
  Translation Inspector checks in English and Arabic.
- Translation Inspector: toggle, inspect, open the matching administration entry
  and disable **passed in both browsers and both languages**. The 29 earlier
  Inspector-related unit cases still apply to unchanged Python/JavaScript owners.
- Visual and focus reconciliation: **passed**, with every differing image reviewed.
- Performance: **passed** the approved repeated **20% AND 100 ms** gate.
  Eight sequential original/current/current/original runs retained **1,888 samples**,
  including **144 excluded warmups**. All **80 request comparisons match**.
- Cleanup: **all 32 uniquely named disposable databases removed**, independently
  confirmed through the PostgreSQL catalogue; no owned test service/driver remains.
- Final source/traceability audit, branch/HEAD validation and whitespace check:
  **passed**. All changes remain local and uncommitted.

Performance uses the Phase 7 protocol and the approved **20% AND 100 ms** gate
across independent original/current comparisons, with smaller repeatable
increases reviewed too. Fixed existing browser drivers and corrected event-log
instrumentation are used. Timed runs execute separately from functional tests.
The synthetic local benchmark is not a production-capacity certification.

The original inventory is reconciled with current owner locations and freshly
executed tests for all 16 workflow families, 147 named host functions, 121 dialog
construction sites, 66 navigation sites and 829 shared-state references. A stale
Settings category-persistence callback name in the earlier evidence mapping was
updated to its actual current name. Source mappings supplement behavior checks;
they do not prove every possible data/permission combination.

The root is now 3,951 lines versus 21,741 before extraction; 1,646 current lines
are the unchanged inline stylesheet. All feature owners established in 6A–6U
remain in place. Dormant generic-table fallbacks stay in their feature module:
they are not a dependency on the old root implementation, and removing their
public renderer behavior or catalogue references requires a separate caller
and compatibility review. Their known undefined-reference abnormality is in the
prioritized register, rather than silently repaired during cleanup.

## Final handoff and scope

The [defect and observation register](webui-refactor-existing-observations.md)
is finalized for this handoff. It distinguishes original defects, existing
UX limitations, unresolved observations and corrected test issues. Product fixes
require separate approval. The separately approved Phase 2 aggregation-panel
visibility correction remains the sole approved product fix in this refactor.

## Checkpoint and resumption — 11 November 2026

The user requested a pause, then explicitly authorized resumption. The active
Chrome traversal was stopped through its owning runner and its disposable database
removed. At that checkpoint all seven test databases were independently confirmed
absent and no owned test process remained. On resumption the branch, HEAD and all
runtime hashes matched. Four completed native journeys were reused; remaining
journeys used new databases and output directories. Interrupted attempts are kept
separately and do not count as passing acceptance.

`specs/dashboard-records-and-creation.md` appeared as an unrelated untracked file.
This task did not create or modify it; it remains untouched.

## Visual and focus investigation

Older captures reserved a 15-pixel native scrollbar gutter; resumed captures use
an overlay scrollbar. Fresh runs of the complete original source snapshot reproduce
the current geometry. Both browsers' **58 focus observations match exactly** after
excluding only generated DOM IDs and focus-indicator animation opacity. All target,
semantic, geometry and other recorded style properties agree.

Across **384 paired screenshots**, **308 are pixel-identical** below the animated
72-pixel header. All **24 translation/Inspector captures match exactly**. The
remaining **76 captures were visually reviewed**: 32 contain run-specific timestamps
or synthetic audit identifiers, and 44 contain notification fade/slide timing,
overlay-scrollbar fading, focus-highlight shading or small antialiasing differences.
Arabic timestamp wrapping can also affect an audit row's height. These differences
are recorded per image. No application CSS, system setting, image mask or approved
baseline was altered to conceal differences. Historical comparisons, fresh original
runs and all raw images are retained separately.

## Edge translation test observation

The first Edge run passed English Inspector, then WebDriver's click on the
language selector's internal focus input was intercepted by a text span before
Arabic checks. The database was removed normally. Failure-only DOM hit-test and
screenshot diagnostics were added to the local wrapper. Original and unchanged
current repeats both passed all 11 groups in both languages; the diagnostic catch
did not fire. No application or tracked test-harness source was changed. The exact
timing/overlay cause remains unproven, and the failed attempt is retained rather
than counted as acceptance.

## Performance review

All 22 repeatably slower metrics across 17 browser/workflow/language groups were
reviewed against both independent pairs, request counts and slow-cycle API timings.
There is **no repeated blocking metric**. Latency is not identical, and the evidence
does not establish every cause of smaller increases or isolated spikes.

Two Edge results crossed both thresholds in only the first pair:

| Measurement | First pair increase | Reverse pair increase | Finding |
| --- | --- | --- | --- |
| Arabic dashboard p90 | 361.2 ms / 244.8% | 26.4 ms / 18.7% | Large first-pair cycles had 28–30 ms API calls, so API execution does not explain the full delay. Exact cause remains unproven. |
| Cold page to sign-in | 212.2 ms / 24.1% | 24.4 ms / 2.8% | One sample per independent process; exact loading/scheduling cause remains unproven. |

No slow sample was removed or replaced by a passing rerun. Request shapes/counts
are unchanged. Other repeated increases are smaller; the full review records API
variation where observed and leaves remaining attribution explicitly unproven.
These observations pass the agreed consistency gate and remain in the register
for follow-up. This synthetic local benchmark does not certify production scale.

## Retained evidence and completion

- [Acceptance totals](verification/webui-refactor-phase8/acceptance.json)
- [Source preservation audit](verification/webui-refactor-phase8/source-audit.json)
  and [inventory traceability](verification/webui-refactor-phase8/inventory-traceability.json)
- [Functional run manifest](verification/webui-refactor-phase8/functional-runs.json)
  and [supplementary original runs](verification/webui-refactor-phase8/original-visual-runs.json)
- [Visual review](verification/webui-refactor-phase8/visual-review.json) and
  [keyboard comparison](verification/webui-refactor-phase8/keyboard-comparison.json)
- [Performance comparison](verification/webui-refactor-phase8/performance-comparison.json),
  [all repeatable-increase reviews](verification/webui-refactor-phase8/performance-review.json)
  and [request comparison](verification/webui-refactor-phase8/performance-request-comparison.json)
- [Independent database audit](verification/webui-refactor-phase8/database-cleanup.json)
  and [process cleanup](verification/webui-refactor-phase8/process-cleanup.json)

The archive includes suite XML, logs, raw captures, timings and failed/interrupted
attempts. Accepted runs are selected explicitly; failed attempts are not counted.
The historical checkpoint remains as a record of the pause, not an outstanding task.

The approved WebUI refactor is complete through Phase 8. Earlier evidence is in the
[Phase 2 regression report](webui-refactor-phase2-verification.md),
[Phase 6 report and individual sub-phase reports](webui-refactor-phase6-verification.md)
and [Phase 7 integration/performance report](webui-refactor-phase7-verification.md).
The root now assembles feature modules while preserving the existing single-page
navigation. No public URLs, browser-history changes, API/schema changes, settings,
UI text or translation artifacts were introduced by Phase 8. All 4,071 English and
Arabic catalogue keys, wording and provenance remain unchanged; no new translation
review or deployment configuration is required.

Firefox, Safari, CI and production-scale performance remain deferred by the agreed
scope. Live SMTP was not repeated in Phase 8; earlier MailDev evidence is retained.
The persistent local stack, MailDev and Safari were left alone. Local acceptance
finds no new regression in the verified scope; it does not prove every possible
workflow/data/permission combination or certify absence of existing defects.
