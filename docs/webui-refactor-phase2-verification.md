# WebUI refactor: Phase 2 verification

**Date:** 10 November 2026  
**Status:** Phase 2 complete for the approved local scope. Chrome and Edge each passed 44 workflow checks and 12 supplemental keyboard/focus check groups in English and Arabic. Firefox, Safari and CI remain deferred by the user.
**Contract:** [Approved specification](../specs/webui-modular-routing-refactor.md)

The existing application has not been split or given new URLs. This phase repairs
the regression tests, adds checks through the assembled application, and makes
test database ownership and cleanup repeatable. The only production change is
the separately approved one-line aggregation reload fix described below.

The local Phase 2 gate is complete under the user's revised scope: Chrome and
Edge, with Firefox, Safari and CI deferred. No Phase 3 extraction has started.
The completed checks establish today's baseline; they do not guarantee that
every possible application path is defect-free.

## 1 What changed

- One runner executes the unit and NiceGUI interaction suites in separate
  processes and storage folders. It disables dotenv loading, clears database
  URLs, and blocks Python socket and native PostgreSQL connection entry points
  before collection. Missing results, empty runs, failures and skips fail the run.
- A separate runner creates a uniquely named disposable database, initializes
  the canonical schema and separate seeds, owns its API/UI/seed/test processes,
  and removes them and the database on completion or interruption. It reserves
  both real-server listeners to prevent tests reaching an unrelated service
  through a released-port race. Cleanup failure remains an error and is recorded.
- The prepared CI workflow runs both isolated suites twice, runner safety checks, and assembled
  checks against an ephemeral PostgreSQL service. This workflow has been added
  but has not yet run on GitHub; local results are the evidence below. The user
  requires all changes to remain local and uncommitted, so CI execution is deferred.
- Forty assembled checks exercise the real NiceGUI root and real REST API.
  They record request outcomes and timings. Browser JavaScript is explicitly
  simulated; these checks do not claim to prove browser layout or history.
- Test dependency versions match the installed frontend baseline. No runtime
  dependency was upgraded. No environment template, private `.env`, translation
  key, wording or translation artifact was changed.

Commands and lifecycle guidance are in the
[WebUI README](../frontend/webui/README.md#refactor-regression-checks).

## 2 Original test failures

| Phase 1 finding | Correction to the test | Preserved assertion |
| --- | --- | --- |
| T1 translation editor source slice | Recognize the existing permission-aware guard | Language loading and editing permission checks |
| T2 aggregation layout source assertion | Include the existing `detail-action-row` class | Existing two-column layout structure |
| T3 capture controls fail in the full suite | Give each control test an owned NiceGUI client/slot and cleanup | Digital capture and ordinary-record medium behavior |
| T4 messaging tests cannot find Open | Use the existing message delivery-row marker | Restore route, refresh and busy capture behavior, including Arabic |
| T5 intermittent Send click | Target the existing send-button marker and assert a single enabled button | Separate To/Cc recipients and successful send |

The old text search for “Send” also matched “Sender”; that NiceGUI overload did
not apply its `kind` filter. The new locator removes that ambiguous click.
No test was skipped, marked expected-failure or weakened to remove its workflow
assertions. The original failures remain in the Phase 1 evidence.

## 3 Coverage and traceability

| Requirement / current implementation | Evidence | Limit |
| --- | --- | --- |
| Every main drawer destination; `app.py::index` and existing callbacks | 30 parameterized assembled cases use actual drawer controls, navigation state, screen headings and API outcomes | Smoke coverage, not every entity action or permission combination |
| Login and Settings drawer entry; `select_application_settings` | Assembled cases and Chrome/Edge real login/Settings journeys | Scoped keyboard/focus baseline completed below |
| Settings restoration and category persistence; `restore_navigation_entry` | Assembled and Chrome/Edge category, breadcrumb, root reload and Back/Forward cases | No new URLs or history behavior introduced |
| Audit-event Settings link; `render_event_timeline` | Assembled and Chrome/Edge actual audit-event → Settings/category checks | Observed category selection without automatic target-field focus; preserved as baseline |
| Custody warning → Disposition; `select_governance_custody` | Assembled warning-link case | Other custody workflows remain feature-specific work |
| Settings save, required reason and current data; `application_settings.py` | Assembled and Chrome/Edge validation/save/revisit/reload and real conflict in English/Arabic | Firefox/Safari completion deferred |
| Sign-out and identity isolation; `sign_out`, session cleanup | Assembled denial plus Chrome/Edge normal sign-out, expiry and administrator → viewer journeys | Concurrent conflict uses a separate API session, not a second browser window |
| Settings categories, selectors, secrets, errors and abandoned work | Existing interaction suites plus Chrome/Edge real controls, API requests and held-response checks | Deliberate errors/delays injected only by the test server |
| Aggregation restoration, Phase 1 B1; `open_aggregation` | Failing-before/passing-after assembled reload assertion of the containing panel's visibility | Separate approved defect correction, not an extraction |
| No unrelated production change | [Runtime source comparison](verification/webui-refactor-phase2/runtime-source-check.json) | 53 of 54 runtime modules unchanged; only the approved line differs in `app.py` |
| Test runner isolation and cleanup | Twenty-one safety/instrumentation tests, plus successful/failing disposable runs | CI execution still pending |

The detailed Settings interaction tests cover all registered settings in English
and Arabic, required/blank reasons, atomic destinations, stale versions, secret
replacement, remote search bounds, selected IDs, branch paging, stale selection,
refresh retention, abandoned responses, translated feedback, integer validation,
and test-email validation, outcomes and duplicate prevention. No outside email
was sent during this work.

## 4 Results and defect correction

The repaired unit and interaction suites passed twice before the production
correction: **1,484 unit + 209 interaction cases per repetition**, with no
failures, errors or skips. The final repeated run after the approved correction also passed:

| Final check | Run 1 | Run 2 | Failures / errors / skips |
| --- | ---: | ---: | --- |
| Unit/source tests | 1,484 | 1,484 | 0 / 0 / 0 |
| NiceGUI interaction tests | 209 | 209 | 0 / 0 / 0 |
| Assembled real-API tests | 40 | 40 | 0 / 0 / 0 |
| Runner safety/instrumentation tests | 21 | — | 0 / 0 / 0 |

[Final isolated-run summary](verification/webui-refactor-phase2/summary.json).
Configuration authority and API-template consistency checks also passed.

The assembled suite first passed 37 checks. Adding the B1 reload assertion
produced **37 passed, 1 failed**, proving the existing hidden-panel defect.
The user then explicitly approved showing the existing panel when an aggregation
opens. Adding `show_authenticated_view()` to `open_aggregation` produced
**38 passed**. Two further checks added real optimistic-conflict and identity
change coverage; the expanded run produced **40 passed**, without skips. A second full run also passed all 40
checks ([repeat results](verification/webui-refactor-phase2/assembled-repeat.xml)).

- [B1 failing-before evidence](verification/webui-refactor-phase2/aggregation-before-fix.xml)
- [B1 passing-after evidence](verification/webui-refactor-phase2/aggregation-after-fix.xml)
- [Expanded assembled results](verification/webui-refactor-phase2/assembled-first.xml)
- [Assembled request observations](verification/webui-refactor-phase2/assembled-first.requests.jsonl)
- [Runner safety results](verification/webui-refactor-phase2/runner-safety.xml)

Request observations include login and explicit test verification reads. They
are not browser-render timings or a blanket performance certification. The [request summary](verification/webui-refactor-phase2/request-summary.json)
records one Settings read for a normal entry and two for the two visits in the
breadcrumb-return case. No machine-speed pass threshold has been introduced. Phase 1's original screenshots
and request/timing evidence are preserved.

A live embedded-browser journey also passed: Records search → record detail →
parent aggregation → reload, followed by changing to Arabic and reloading again.
The aggregation overview remained visible in both languages, with no captured
warning/error logs. [English capture](verification/webui-refactor-phase2/aggregation-restored-en.jpg)
and [Arabic capture](verification/webui-refactor-phase2/aggregation-restored-ar.jpg)
record the result; these supplement the actual-product runs.

The B1 change uses the existing NiceGUI visibility helper. It does not add CSS,
alter data loading, or change navigation, layout or public URLs. Phase 1 B2, the
unrelated disposition-preview fixture failure, remains recorded and unfixed.

## 5 Actual browser verification

The remaining checks target **Chrome and Edge**, following the user's explicit
10 November 2026 instruction to defer Firefox and Safari. The four-browser
support intention is unchanged; deferred coverage is not a passing result.
Standard Selenium drivers use separate test sessions on macOS 15.6.1, with a
fresh disposable database for each run. Chrome and Edge run headless at a
1440 × 1000 CSS-pixel viewport, scale 1 and zoom 1. Installed product versions
are recorded in each result; no application runtime dependency was upgraded.

| Final product | Checks | Visual repeats below header | Evidence |
| --- | --- | --- | --- |
| Chrome 157.0.8103.40 | 44 passed, 0 failed | English/Arabic: 0 differing pixels | [Results](verification/webui-refactor-phase2/browsers/chrome/browser-results.json) |
| Edge 157.0.4341.42 | 44 passed, 0 failed | English/Arabic: 0 differing pixels | [Results](verification/webui-refactor-phase2/browsers/edge/browser-results.json) |

Each product has 29 full original screenshots, source hashes, API observations
and successful database cleanup records. The production hashes still match the current uncommitted application files.
The original full-run test-tool hashes are retained; the supplemental keyboard
runner has its own later source snapshot. Representative English and Arabic General,
table and dialog images were inspected. [Combined summary](verification/webui-refactor-phase2/browser-summary.json).

The automated journey covers both English/LTR and Arabic/RTL:

- All seven Settings categories, required reasons, one write per save, saved
  values after return/reload, and a real optimistic conflict caused by another
  authenticated API session. This is not a second browser-window test.
- Drawer, breadcrumb, restored navigation, custody warning and audit-event
  Settings entry; three repeated visits with one Settings read per visit.
- Controlled API errors and a held read released after leaving the page, proving
  that its late result does not replace the current view.
- Scheme-first selectors, paged schemes and child branches, bounded type-ahead,
  retained selected values, cancel/clear and atomic destination saves.
- Masked secret replacement and explicit clearing; email validation, busy-state
  duplicate prevention, Escape, and actual local MailDev acceptance with TLS
  certificate validation. All recipients are synthetic `test.invalid` addresses;
  MailDev has no outgoing relay.
- Existing search URLs, saved-search unsaved-change confirmation, record-to-parent
  aggregation navigation/reload, and an existing styled relationship-types table.
- Existing browser Back/Forward behavior, normal sign-out, expired sessions,
  restricted identity and absence of the previous administrator's draft.
- Browser console/unhandled errors and API failures. Expected failures are the
  exercised version conflicts, controlled errors and expired authentication.
  The preceding API health document's missing favicon is separately classified;
  it is not a WebUI asset failure.

### Completed keyboard/focus review

Each browser passed **12 supplemental check groups**, with **58 focus observations
and 54 original screenshots**, covering English and Arabic. Native keyboard
input was combined with visual review of field borders, button/tab highlights,
dialog states and navigation returns. The test code never injects focus or CSS.
[Review and findings](verification/webui-refactor-phase2/keyboard/review.json),
[Chrome results](verification/webui-refactor-phase2/keyboard/chrome/browser-results.json),
[Edge results](verification/webui-refactor-phase2/keyboard/edge/browser-results.json).

| Check | Existing behavior recorded |
| --- | --- |
| General form Tab / Shift-Tab | Number → reason → Save; reverse traversal returns through the same fields |
| Required-reason validation | Focus remains on Save, draft retained, no write |
| Successful save | Focus returns to the page body after the form renders again |
| Category arrows / Enter | Focused category becomes selected with a visible highlight |
| Email dialog | Recipient → Close → Send; validation stays on Send; Escape returns to Test Send, followed by Save on Tab |
| Dialog boundary | Some runs report page-body focus after Send before returning to recipient; Arabic Chrome returned directly to recipient, while Arabic Edge reported the body first. Repeated reverse Tab at the recipient boundary retained recipient focus |
| Classification browser | Close → first scheme, reverse Tab returns to Close; Escape restores Browse |
| Drawer / breadcrumb / custody / audit return | Drawer container or page body receives focus. Following Tab reaches Dashboard after breadcrumb return, and Refresh after the audit link. The audit link selects the category without automatically focusing its field |

Of 58 semantic focus observations, 56 matched between Chrome and Edge; the two
remaining observations are the documented Arabic email-dialog boundary steps.
These existing limitations and browser differences are preserved, not silently
fixed or described as universal focus trapping. This completes the pilot's
local keyboard baseline, not a whole-application accessibility certification.

The first supplemental attempt incorrectly asserted that Tab must wrap inside
the email dialog. Its failures are retained in the evidence; that invented
requirement was replaced with explicit observation of the current behavior.
Runner safety checks passed all 21 cases in the API environment. An initial
attempt in the frontend environment could not collect them because it lacks
`psycopg`; that setup failure is retained in the runtime evidence.

### Visual evidence

The fixed fixture uses dated synthetic records, UTC application display and
checked-in Arabic translations published only into the disposable database.
Browser timezone is recorded separately (Asia/Dubai). Screenshots record loaded
Changa fonts, identity, language, dimensions, scale, zoom and content hashes.
They include General, selectors, email dialogs, loading/error/empty states,
unsaved confirmation, tables, aggregation details and a restricted dashboard.

General is captured twice after reload in each language. Pixel comparisons
exclude only the animated header and its margin (top 72 CSS pixels); full
originals are retained. Audit timestamps in the unsaved-search screenshot are
explicitly recorded as dynamic content. Other captures are reviewable baselines,
not claims that every state has passed a repeated pixel comparison. No CSS,
layout, translation or navigation correction was introduced to obtain captures.

Earlier embedded-browser visual evidence remains in
[fixed-visuals](verification/webui-refactor-phase2/fixed-visuals/comparison.json).
Its initial English captures with transient scrollbars or a different drawer
position were rejected rather than accepted as goldens. The fixed fixture also
passed all 40 assembled checks before the actual-product runs.

### Deferred and unsuccessful runs

Earlier runs are retained under gitignored `.runtime/webui-refactor-phase2/`.
Harness corrections included ambiguous controls, stale page references, waiting
for completion, deterministic held responses, and classification of the API
health document's favicon request. Failed runs are not relabelled as passes.

Firefox 158.0.1 completed 43 checks in its latest attempt, then failed the old
favicon classification. Its corrected final run is **deferred**, not passed.
An earlier Firefox run recorded an unclassified browser error; later runs did
not reproduce it. Safari 18.6 completed 13 checks in its latest attempt before
a dialog-opening timeout. Native driver input and timing remained unreliable;
that incomplete journey is **deferred**, not an established application defect
or a passing acceptance run. Partial reports are retained for future work.

## 6 Phase 2 completion and deferred work

The approved local gate is complete: repaired repeated suites, assembled real-API
coverage, repeatable disposable runners, detailed Chrome/Edge pilot workflows,
visual baselines, request/abandonment checks and keyboard/focus observations.
The existing UI and navigation remain unchanged apart from the separately
approved B1 correction. No new production changes were needed for keyboard checks.

Firefox, Safari and CI execution remain explicitly deferred by the user. The
prepared CI workflow is retained, but it is not a local acceptance gate. No
claim of four-browser coverage or a successful CI run is made. All changes remain
local and uncommitted for the user's testing. Phase 3 has not started.

## 7 Cleanup and handoff

All **56 recorded disposable databases** were dropped, including failed attempts.
An independent PostgreSQL catalogue check found none remaining; see the
[cleanup evidence](verification/webui-refactor-phase2/database-cleanup.json).
All test runners and browser drivers have exited. The test-owned MailDev was
stopped and its previous saved SMTP/web ports (1025/1080) restored. Certificates
and captured mail remain in the gitignored runtime directory. Existing development
services and persistent databases were left alone. Safari's temporary “Allow remote automation” setting has not
been restored: computer-control attempts timed out, and the user then explicitly
instructed the agent to leave Safari alone. No further Safari changes are planned
in this batch.

All work remains local and uncommitted on `refactor-API-python-file`, based on
`3a4481d5de96df1b27f1c2e401316ab00b93567f`. No branch, commit, push or pull request
was created during this continuation. The Arabic artifact commit is the existing
base, not a new change introduced by this work.
