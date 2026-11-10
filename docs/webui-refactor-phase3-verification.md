# WebUI refactor: Phase 3 pilot verification

**Date:** 10 November 2026  
**Status:** Complete for the approved local Chrome/Edge scope.  
**Base:** `8106e1ebd425e28b38b565fd34499abfac266fbc` on `refactor-API-python-file`.

## Change

Application Settings now has a feature-owned controller alongside its existing
renderer. It owns authorization, the selected category, view identity and the
four entry paths. It receives explicit dependencies rather than the shared
application state dictionary. Each NiceGUI client gets its own instance.

The renderer, controls, wording, styling, API contracts, URLs and navigation
remain unchanged. The shared shell still belongs to `app.py`; two small adapters
prepare that shell and persist the existing navigation snapshot. This pilot
does not extract authentication, navigation infrastructure or other features.

## Requirement-to-code-to-test traceability

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Permission checks before entry | `ApplicationSettingsController.can_open/open` | New denied-entry tests; existing restricted-user assembled/browser cases |
| Drawer and existing unsaved-change guard | `open_from_drawer` → existing guard | Cancelled-entry unit cases; real drawer and saved-search browser journeys |
| Reload and breadcrumb category restoration | `restore/category`, existing shell snapshot key | Assembled category/reload tests; browser breadcrumb and reload journeys |
| Audit setting link, including origin dialog | `open_from_event` | Real-controller audit interaction tests, including cancellation/denial; assembled and browser audit links |
| Custody warning opens Disposition | `open_from_custody` | Caller unit check; assembled and browser custody journey |
| Replaced views and changed identities cannot update current state | Controller-local token and principal identity checks; unchanged renderer guard | New abandoned-view, pending-render and independent-client tests; browser held read and sign-out/expiry cases |
| Current data, bounded requests and unchanged settings workflows | Existing `application_settings.py` renderer and injected API/relationship binding | Existing interaction suite and full browser workflow checks |
| Appearance and keyboard behavior | Unchanged renderer and shell controls | Phase 2/3 screenshot and semantic focus comparisons |
| Translation keys, wording and provenance | No catalogue or artifact edits | Reference checker and exact artifact/hash/coverage checks |

Thirteen controller tests cover the new boundary directly. The existing audit
interaction test now uses the real controller instead of a stub for the removed
host callback; its permission, guard, historical-label and no-extra-read
assertions remain. No existing test was removed or marked skipped.

## Validation

Completed checks:

| Check | Result |
| --- | --- |
| Isolated unit suite, twice | 1,497 passed each run |
| Interaction suite, twice | 209 passed each run |
| Assembled application with real API | 40 passed |
| Chrome and Edge full workflows | 44 passed in each browser |
| Chrome and Edge keyboard/focus | 12 groups and 58 observations per browser; no semantic differences from Phase 2 |
| Chrome navigation after harness timing correction | 18 passed |
| Catalogue references and configuration authority | Passed; no configuration changes |

[Isolated reports](verification/webui-refactor-phase3/isolated/summary.json),
[assembled report](verification/webui-refactor-phase3/assembled/assembled.xml),
[Chrome workflows](verification/webui-refactor-phase3/browsers/chrome/browser-results.json),
[Edge workflows](verification/webui-refactor-phase3/browsers/edge/browser-results.json),
[focus comparison](verification/webui-refactor-phase3/focus-comparison.json), and
[Chrome navigation](verification/webui-refactor-phase3/navigation/chrome/browser-results.json).

The first Edge run passed all 44 functional checks, but its screenshot trail
missed a Dashboard visit. The test clicked while root-page restoration was
still active. The harness now waits for the restoration-complete breadcrumb
before navigating. An intermediate wait incorrectly assumed search results
would return; the existing empty-query fallback is Dashboard. That assumption
failed in Chrome and Edge and was replaced with the breadcrumb wait. These
attempts are retained under
[initial runs](verification/webui-refactor-phase3/initial-runs/); their failures
are not counted as passes. The corrected Edge full run passed all 44 checks and matches the baseline trail.

The shared navigation functions are unchanged, confirmed by an
[AST comparison](verification/webui-refactor-phase3/navigation-source-check.json).
Only the Settings host integration and new controller changed among top-level
WebUI runtime modules; the renderer is byte-identical to the base
([source comparison](verification/webui-refactor-phase3/runtime-source-check.json)).
Existing keyboard quirks recorded in Phase 2 remain unchanged. Screenshots of
English reason-field focus, Arabic email-dialog return, the unsaved-change
dialog and Arabic General Settings were also visually reviewed.
Chrome and Edge are the approved local browser scope, in English/LTR and
Arabic/RTL. Firefox, Safari and CI remain deferred at the user's instruction.
All database-backed runs use fresh disposable databases on the local cluster.

The English and Arabic artifacts are byte-identical to the base. All 4,071 keys
retain the same wording and provenance; no keys were added, changed or removed,
and no administrator export was promoted. Coverage, ordering, blanks and
placeholders pass; repository references are complete and current.
[Translation evidence](verification/webui-refactor-phase3/translation-check.json).

## Visual, request and cleanup evidence

All 29 full-workflow screenshots per browser were compared with Phase 2 at
1440 × 1000. Below the existing animated-header exclusion, 54 of 58 images are
pixel-identical. The other four differ only in the saved-search update
timestamp; all pixels outside that timestamp and header match. Original images
are retained. [Visual comparison](verification/webui-refactor-phase3/visual-comparison.json).

Settings request counts match Phase 2 exactly in both browsers: 48 successful
reads, 14 successful updates, two deliberate update conflicts, two controlled
read failures, and two successful plus two controlled-failure test sends.
Repeated visits still make one Settings read each. The expected-error and
browser-console checks pass; each browser delivered both English and Arabic
test messages to local MailDev with TLS certificate validation enabled.
[Request comparison](verification/webui-refactor-phase3/request-comparison.json)
and [browser summary](verification/webui-refactor-phase3/browser-summary.json).

All nine disposable databases, including those used by the unsuccessful harness
attempts, were dropped. A separate read-only PostgreSQL catalogue check confirmed
none remain. Test servers and browser drivers exited. The owned MailDev instance
was stopped and its stopped status confirmed; unrelated services and Safari
were left alone. [Cleanup evidence](verification/webui-refactor-phase3/database-cleanup.json).

## Limits and next review

This is evidence for the Settings pilot, not a guarantee that every application
path is regression-free. Browser checks retain the Phase 2 viewport and fixed
synthetic fixture. The full original screenshots are retained; the animated
header is excluded from automated pixel comparisons using the existing
72-pixel boundary. No CSS or rendered content was changed for comparison.

Per-check elapsed times remain in the browser reports. They include automation
waits and machine load; initial Chrome checks ran alongside other suites and
are not a controlled performance benchmark. Request counts, freshness and
abandoned-read assertions provide the performance regression checks here.
No cache, additional data request or new background task was introduced.

Phase 4 should review these narrow dependencies before extracting the shared
shell or navigation: the existing API client, identity/direction accessors,
relationship binding, navigation guard, shell entry and snapshot persistence.
The pilot leaves those shared responsibilities in their existing owner.

## Handoff

No environment variables, deployment settings, dependencies or translation
artifacts changed; no operator configuration is required.

All changes remain local and uncommitted on the user's branch. No branches,
commits, pushes, resets or pull requests were created. Phase 4's explicit review
decision is still required before expanding the extraction to shared
infrastructure or other features.
