# Phase 7 — Application-wide verification

**Status: complete for the approved local Chrome/Edge scope, 11 November 2026.**
Phase 8 has not started and requires the user's authorization. Firefox, Safari
and CI remain deferred. Work stays local and uncommitted on the user's branch.

## Scope and acceptance

Phase 7 checks the assembled modular application against the original inventory
and existing feature evidence. It does not change application behavior, fix
product defects, introduce routes or alter browser history. The separately
approved aggregation visibility fix remains part of the pre-extraction baseline.

The user approved a performance blocking threshold of **20% and 100 ms** on
11 November 2026. Both thresholds must be met consistently across independent
paired runs for the same workflow. Every repeatable slowdown is investigated,
including smaller differences. This supplements the functional, visual, request
count, cancellation, freshness and identity/language isolation gates.

## Completed checks

- Full WebUI suites: **1,628 unit and 420 interaction tests passed**, with no
  failures, errors or skips. These run in separate processes with network access
  blocked before collection.
- Full assembled application against a fresh real API/database: **74 passed**.
  Two further independent aggregation save/refresh reruns passed. The earlier
  6O cancellation did not recur; its cause remains unknown, and no fix is claimed.
- Runner/evidence-stream safety: **30 passed**. Timing-gate decision tests: **16 passed**, covering
  both limits, independent repeats, slow tails and rejected incomplete evidence.
- Configuration ownership, API templates, catalogue references and Arabic
  terminology checks passed. No runtime, environment or catalogue file changed.
- Chrome and Edge full journeys: **42 groups per browser passed**. Live SMTP
  delivery was not repeated; its prior MailDev evidence remains in Phase 2/3/5.
- Keyboard journeys: **12 groups, 58 focus observations and 54 screenshots per
  browser**. All recorded semantic focus properties and geometry match the pilot
  baseline; generated element IDs and animation opacity are excluded. Existing
  focus limitations remain documented.

The final Chrome and Edge destination traversals each passed **120 visits**:
30 destinations, forward and reverse, in English and Arabic. Component workflows
also passed. Across nine native scopes, the final functional runs passed **190
check groups** and retained **436 screenshots**; these groups include repeated
sign-ins and are not 190 distinct features. The known pagination errors and the
component/dashboard deleted-slot notification errors remain explicitly recorded.

**Performance acceptance passed.** Neither browser has a workflow whose median
or p90 consistently crosses both approved limits in the two independent pairs.
The final eight runs retain **1,888 samples**, including 144 excluded warmups;
all **80 paired API request-shape/count comparisons match**. Fifteen
workflow/language combinations had smaller repeatable increases across 18
metrics. Each was reviewed against raw samples and API durations; passing the
gate does not mean those differences are zero.

The largest repeated warm p90 increases were Edge Arabic parent aggregation
(93.8 ms and 25.6 ms) and Chrome Arabic record details (31.2 ms and 76.2 ms).
Chrome Arabic search had a 244.2 ms p90 increase in one pair but only 6.1 ms in
the other; its two slow cycles also had slower API calls. Cold Chrome page load
increased 213.5 ms in one pair and 6.9 ms in the other. These isolated larger
increases do not satisfy the agreed consistency rule. API variation contributes
to some slow samples, but the full cause of every residual difference is not
established. The detailed review retains all increases and limitations.

The initial comparison crossed both
limits for Chrome sign-in, English record-search p90, Arabic record-detail p90,
and Edge Arabic Dashboard/parent-aggregation p90. Those results are retained.
Profiling then found both original and refactored event loops waiting in
test-only log-file opening calls. The driver's repeated log reads also stalled:
a separate probe measured maxima of 217–441 ms, versus less than 0.02 ms with a
persistent reader. These measurements include substantial harness overhead and
cannot reliably establish application latency.

The test harness now retains append handles, flushes complete rows and reads
only newly appended events, including safely retaining incomplete lines. All
46 harness checks pass. The entire original/current timing protocol was repeated
with that correction and the same threshold; those complete runs are the final
acceptance series. No application code was changed. The independent cleanup
audit confirms all **64 uniquely named disposable databases** were removed,
including failed and interrupted attempts. No owned test processes remain.

## Inventory and visual evidence

The reconciliation covers all 16 original workflow families, 147 named host
functions, 121 dialog construction sites, 66 navigation sites, 829 shared-state
references and 54 original runtime modules. Every family is linked to executed
passing cases and its feature-extraction report. Source-owner mappings supplement
behavior tests; they do not prove every dynamically constructed dialog variant
or every combination of data and permissions.

Of 54 full-journey screenshots comparable with the pilot archive, **46 match
exactly below the animated 72px header**. Four differ only in the saved-search
update timestamp. Four Arabic email-dialog images differ only in a background
sender field: the historical English MailDev test populated its value before
switching to Arabic; the current run leaves MailDev alone. That changes the
background field's floating-label state. The dialogs and remaining pixels match.
Full images are retained; representative complete pairs and the differing text
region were inspected. Baselines were not replaced.

The individual original/extracted comparisons in the
[Phase 6 reports](webui-refactor-phase6-verification.md) remain the feature-level
visual and workflow evidence. Phase 7 adds application-wide execution and
cross-feature traversal; it does not erase previously recorded defects.

## Performance method

Compare original UI commit `8106e1e` (Phase 2 complete, before extraction) with
current modular UI `123ad8b`. A read-only Git archive supplies the complete
original frontend package in the ignored test directory; the active checkout
and Git history remain untouched. Both variants use the same current API,
canonical schema, fixtures, dependencies and installed browser. API/schema
runtime files did not change between those revisions.

For each browser, run **original → current → current → original**, sequentially,
after functional tests finish. Each process owns a fresh browser session and a
new disposable database. Pair runs 1/2 and 4/3 so the execution order is reversed.

Measure cold browser load and sign-in separately. For warmed workflows, exclude
one warmup cycle, then retain 12 samples per language per process: Settings,
Dashboard, Records, Classification, Inbox, Custody, record search, record details
and the parent aggregation. Time native activation through the visible result,
completed non-stream API reads, absent loading indicators and two animation
frames. Finding controls, typing, screenshots and fixture setup are outside the
measured interval. Raw timings and request metadata are retained.

Compare per-pair medians and p90 timings. A consistent breach of both approved
limits in either metric blocks acceptance; a faster overall average cannot hide
an individual slow workflow. Cold load/sign-in has one sample per independent
process and therefore weaker evidence than warmed navigation. This is a local,
synthetic-fixture comparison, not a production capacity test, server-process boot
benchmark or certification of unmeasured workflows.

Timing includes the browser test driver's command overhead and 20 ms readiness
polling. The same method applies to both variants. Read-only diagnostic stack
sampling and supplementary DOM/heap observations were collected separately;
profiled and verbose-logging runs are not used for timing acceptance. Heap
observations are GC-dependent and do not certify the absence of memory leaks.

## Failed attempts and preserved findings

All failed and interrupted attempts remain identifiable in the evidence. During
test development, the new traversal needed the existing disposition role fixture
to reach Document Templates and explicit accounting for the already documented
pagination icon errors. Older breadcrumb checks needed to wait for the actual
Dashboard before reacquiring its Settings breadcrumb. A temporary indentation
error in the new benchmark dispatch was corrected; affected launches were rerun.
These are test-harness corrections, not product changes.

One original-UI Edge benchmark stopped on an effective-holds read before that
request reached the API log. A subsequent current-UI Edge benchmark lost its
WebDriver session when the renderer connection closed. Their causes remain
unproven; successful reruns do not establish a fix. Edge's browser version stayed
at `157.0.4341.42`, although automatic driver selection changed. The final Edge
series therefore uses the same existing `157.0.4341.42` driver binary throughout.
Early driver diagnostics accidentally enabled verbose command logging; those
runs are excluded from timing acceptance. Final driver logging is warning-only.
The first pinning wrapper also failed at setup, before launching a browser, and
was corrected. Every attempt retains its lifecycle and outcome.

Native Edge logs also contain macOS display-link and updater permission warnings.
They are retained as environment observations, without attributing them to the
application or changing system settings. Large verbose diagnostic driver logs
stay in ignored local runtime storage; the archive records their paths, sizes
and SHA-256 hashes instead of copying hundreds of megabytes of command dumps.

An execution interruption killed two disposable test runs before their cleanup
completed. Their service/driver processes were independently confirmed absent;
the two owned test databases were then dropped and recovery was recorded. New
runs use new database names. The final cleanup audit includes failed,
interrupted and successful runs.

The [working defect register](webui-refactor-existing-observations.md) retains
original product defects and unresolved observations separately. The final
prioritized defect/abnormality list is due after the whole refactor, including
Phase 8. No product fixes or Git mutations are authorized by this verification.

## Reproducing the checks

The owned runner is `tools/run_webui_integration.py`. Its `--browser-scope`
options include `application` for the 30-destination traversal and `performance`
for the timing journey. Use a new output directory for each run; the runner
creates and drops its own uniquely named database. The same runner supplies
the existing functional scopes listed above. Do not point tests at a persistent
database or reuse a completed run's output directory.

For the comparison, retain the exact original-package overlay, pinned-driver
wrapper, ordered-run manifests and source hashes with the evidence. The original
package must be placed on the import path before importing frontend diagnostics
or application code. Run the two variants sequentially in the recorded ABBA
order, with no other test suites running. `tools/compare_webui_performance.py`
validates the completed manifest and returns failure for a blocking regression;
its output also identifies smaller repeatable increases requiring review.

## Evidence and handoff

- [Acceptance summary](verification/webui-refactor-phase7/acceptance.json),
  [inventory-to-test traceability](verification/webui-refactor-phase7/inventory-traceability.json).
- [Visual comparison](verification/webui-refactor-phase7/historical-visual-comparison.json),
  [keyboard comparison](verification/webui-refactor-phase7/keyboard-comparison.json).
- [Final timing comparison](verification/webui-refactor-phase7/performance-clean-comparison.json),
  [review of every repeatable increase](verification/webui-refactor-phase7/performance-review.json),
  [request comparison](verification/webui-refactor-phase7/performance-clean-request-comparison.json),
  [accepted run manifest](verification/webui-refactor-phase7/performance-accepted-runs.json).
- [Initial instrumentation diagnosis](verification/webui-refactor-phase7/instrumentation-stall-diagnosis.json),
  [large diagnostic log retention](verification/webui-refactor-phase7/large-diagnostic-log-retention.json).
- [Database cleanup](verification/webui-refactor-phase7/database-cleanup.json),
  [process cleanup](verification/webui-refactor-phase7/process-cleanup.json),
  [runtime preservation](verification/webui-refactor-phase7/runtime-preservation.json).

The archive includes selected passing runs and identifiable failed attempts.
Original baselines were preserved. All 165 recorded application runtime files
retain their pre-Phase-7 hashes. No UI text, translation artifact, API, schema or
environment setting changed. Python parsing and `git diff --check` passed.
The branch remains `refactor-API-python-file`, with HEAD `123ad8b`; changes are
local and uncommitted. Phase 8 requires separate authorization. Firefox, Safari,
CI and production-scale performance remain outside this completed local scope.
