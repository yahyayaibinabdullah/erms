# WebUI architecture and migration specification

**Status:** Phases 1–6 complete for the approved local scope; Phases 7 and 8 await authorization
**Date:** 10 November 2026

## 1 Purpose and scope

Split the large NiceGUI `app.py` into smaller feature modules so developers and
agents can work independently. Preserve the current single-page application
and its navigation exactly.

**No functionality or UX change is allowed.** Screens, layout, styling,
wording, translations, controls, permissions, workflows, validation, and API
contracts must remain unchanged. Existing loading, empty, and error states must
also be preserved. This work does not redesign the UI, database, or REST API.

Existing approved feature specifications remain authoritative. A discovered
defect or any other proposed behavior change requires separate approval.

New public URLs are outside this refactor. If considered later, they must be
limited to records and aggregations and require a separate specification and
approval. This document does not authorize or schedule that enhancement.

## 2 Target architecture

| Part | Responsibility |
| --- | --- |
| Small application entry point | Configure startup and assemble the existing single-page application. |
| Shared application shell | Keep the existing header, drawer, breadcrumbs, and notification controls. |
| Session context | Supply the authenticated API client, identity, locale, and session cleanup. |
| Navigation module | Coordinate existing screen selection, breadcrumbs, in-app Back, and unsaved-change checks. |
| Feature modules | Own each feature's pages, interactions, state, and tests. |
| Shared components | Reuse existing tables, selectors, dialogs, and other common controls. |

Group modules by feature, such as records, aggregations, classifications,
administration, messaging, holds, and disposition. Keep existing workspaces
together where their workflow spans several entities.

Pass dependencies explicitly. Features must not import the application entry
point, edit another feature's internal state, or depend on one large shared
state dictionary. Keep view state local; preserve existing session persistence
and identity, language, and browser isolation. Each view must stop its own
background reads when abandoned and ignore late responses. Accepted server
operations must continue as they do today.

Keep the existing NiceGUI page entry point and persistent shell. Feature modules
render inside that shell; they do not require separate URL routes. Do not bundle
a framework upgrade into this refactor.

## 3 Navigation contract

- Preserve every existing screen and dialog and how users reach them. Do not
  introduce entity routes or change dialogs into pages.
- Preserve `/`, existing search links including `/?q=...`, and existing URL
  updates. Do not introduce URL changes for screen selection.
- Preserve current opening, refresh, authentication, authorization, and
  missing-resource and error behavior.
- Preserve current browser-history behavior. Do not add history entries for
  in-app navigation or otherwise change browser Back/Forward behavior.
- Preserve existing page-state restoration. Fetch current authorized entity
  data; do not use navigation history as a data cache.
- Keep existing breadcrumbs and in-app Back behavior exactly, including
  destinations, limits, persistence, discarded forward branches, and fallback
  rules. Keep the displayed page and breadcrumb synchronized without duplicate
  visits.
- Preserve existing unsaved-change protection. Cancelled in-app navigation must
  leave the current view, draft, and URL intact. Do not introduce new prompts or
  extend existing guards to new situations.
- Preserve existing sign-out, identity-change, and session cleanup behavior.
  Keep authorization checks and private session data isolation intact.

Browser Back/Forward integration and exit prevention are outside this refactor.
Do not disable browser controls, add boundary guards, or intercept browser Back
to keep users inside the application. Browser controls may still return to a
previous website; this specification does not promise to prevent that. Any
future browser-history integration requires separate approval.

## 4 Incremental migration

| Phase | Work | Completion evidence |
| --- | --- | --- |
| 1 Inventory and baseline | Map every screen, dialog, workflow, shared state, and dependency. Record supported browsers, existing defects, and English/Arabic appearance and performance. | Complete inventory and documented baseline. |
| 2 Strengthen tests | Establish the repeatable runner and missing behavior, browser, integration, and visual checks against today's application. | Repeatable results, basic coverage of every main destination, and detailed pilot coverage. No application-code extraction begins before this gate passes. |
| 3 Extract the pilot | Complete the separation of Application Settings, including its callers, while retaining current navigation. Separate only the dependencies needed for this pilot. | Functional and visual parity, including cross-feature links; no broad infrastructure rewrite. |
| 4 Review the approach | Assess coupling, regressions, test gaps, and effort revealed by the pilot. | Explicit review decision to proceed, adjust, or stop. Any change in approved scope requires user approval. |
| 5 Extract shared infrastructure | Gradually separate session handling, shell, and existing navigation interfaces. Keep the application working after each small change. | Authentication, isolation, navigation, and all existing screens remain correct. |
| 6 Extract remaining features | Migrate one feature at a time, in small batches ordered by the dependencies and risks found in the inventory and pilot. Cover all inventoried features, including connected workflows. | Add missing coverage before each move. Each feature passes before the next batch begins; migrated and remaining screens work together. |
| 7 Verify the modular application | Exercise complete journeys across all features with the same navigation and UI. | Application-wide parity and requirement-to-implementation-to-test evidence for every inventory item. |
| 8 Cleanup and final acceptance | Remove obsolete code and temporary adapters. Update developer guidance and rerun regression checks after cleanup. | No missing requirements, unresolved regressions, or dependencies on the old implementation. |

Keep each migration small and independently revertible, including its callers
and tests. Avoid concurrent edits to shared shell, authentication, and navigation
code. Use one owner for shared interfaces and separate feature owners once the
pilot establishes stable boundaries. Do not combine extraction with redesign,
unrelated cleanup, or bug fixes, and do not duplicate business logic during
transition. Each phase must pass its checks before the next proceeds.

## 5 Regression checks and acceptance

**The existing WebUI tests are a useful foundation, but are not sufficient on
their own.** Some tests inspect or extract functions from `app.py`. NiceGUI
interaction tests exercise controls with a simulated user and fake API; they
cannot by themselves prove browser appearance, browser history, or real API
integration. The root pytest configuration also selects API tests by default,
so WebUI suites must be run explicitly.

Before extracting application code:

- For the remaining Phase 2 work, verify Chrome and Edge. On 10 November 2026
  the user explicitly deferred Firefox and Safari testing to reduce the time
  required. Keep their partial results and outstanding checks visible; this
  deferral does not establish that those browsers pass or remove their support.
  Record actual browser versions and operating systems for each run. An
  embedded browser or an engine substitute is supplemental evidence only.
- Provide one documented command that runs unit and NiceGUI interaction suites
  in separate processes. Report failures, skips, and unstable tests explicitly.
  On 10 November 2026 the user deferred CI testing until much later and made
  local-machine verification the current priority. Keep the prepared CI workflow,
  but CI execution is not a gate for the current local Phase 2 acceptance.
  Automatic checks on proposed changes remain future work.
- Add tests of observable behavior through the assembled application. Cover
  every main destination and the pilot's complete workflows, including
  authentication, navigation, state restoration, editing, permissions, and
  abandoned background requests. Keep useful existing tests until equivalent
  behavior coverage replaces them.
- Keep fake-API tests for controlled errors and delayed responses. Add selected
  real-browser, real-API workflows, checking browser errors and failed requests
  as well as visible results. Use isolated test processes and disposable
  databases only.
- Capture repeatable English/Arabic screenshots with fixed data and viewport
  sizes, plus request counts and navigation timings. Review image differences;
  never automatically accept replacement baselines. Avoid timing checks that
  fail solely because of ordinary test-machine variation.
- Record existing defects separately; do not silently fix them or treat them
  as new regressions. Baseline tests must demonstrate current behavior before
  the corresponding application code moves.

For each migrated feature:

1. Run relevant unit and NiceGUI interaction tests separately. Replace tests
   tied to old file locations with direct module or behavior tests while
   retaining their assertions. Do not remove coverage just to make tests pass.
2. Test existing entry and search URLs, refresh, breadcrumbs and in-app Back, unsaved
   changes, session expiry, sign-out, restricted access, and cross-feature
   links. Verify that repeated in-app navigation preserves existing URL,
   browser-history, and browser exit behavior.
3. Exercise existing read and write workflows through a real browser and API,
   including validation failures and data refresh after changes. Use a new,
   uniquely named disposable database initialized from the canonical schema;
   always clean it up and report cleanup failures. Never test against a
   persistent ERMS database.
4. Compare before-and-after browser screenshots at the same sizes and data in
   English/LTR and Arabic/RTL. Check dialogs, tables, keyboard interaction,
   focus, and loading, empty, and error states. Explain any image differences;
   no unexplained appearance changes are acceptable.
5. Check repeated navigation, abandoned requests, identity/language isolation,
   and freshness after changes. Preserve request bounds, existing caching
   rules, and responsiveness against the baseline; resolve regressions before
   accepting the feature.
6. Preserve translation keys, wording, and provenance when moving code. Run
   the required catalogue coverage and validation checks.

Record each requirement, its new implementation location, and passing test or
browser evidence. A feature is complete only when all its requirements are
accounted for. Any unexpected difference in functionality, appearance, wording,
permissions, workflow, state, error
handling, or responsiveness blocks acceptance until resolved. Explaining a
difference does not authorize a UX change. Run the full WebUI suites and relevant
API integration tests before final acceptance. No test suite can guarantee zero defects; these
combined checks provide the evidence required to accept the refactor.

## 6 Governing references

- [Phase 1 inventory and baseline](../docs/webui-refactor-phase1-baseline.md)
- [Phase 2 local verification and deferred coverage](../docs/webui-refactor-phase2-verification.md)
- [Phase 3 pilot verification](../docs/webui-refactor-phase3-verification.md)
- [Phase 4 approach review and proposed Phase 5 sequence](../docs/webui-refactor-phase4-review.md)
- [WebUI performance contract](../docs/webui-performance.md)
- [WebUI design language](../docs/webui-design-language.md)
- [Persistent navigation breadcrumbs](persistent-navigation-breadcrumbs.md)
- [Internationalization and user preferences](internationalization-and-user-preferences.md)

Approval authorizes this architecture, test preparation, migration sequence,
and behavior-preserving code extraction only. It does not authorize new public
URLs, browser-history integration, exit prevention, or any functionality or UX
changes.

## 7 Separately approved defect correction

On 10 November 2026, the user explicitly approved a separate one-line fix for
Phase 1 finding B1: aggregation details load after refresh, but their containing
panel remains hidden. `open_aggregation` now calls the existing
`show_authenticated_view()` helper. This shows the existing panel; it does not
change its layout, data, URL, or navigation. A failing-before/passing-after
assembled regression test records the correction. This approval does not
authorize other product changes or application-code extraction before Phase 2
passes.

## 8 Local Phase 2 completion

On 10 November 2026, Phase 2 completed its approved local scope: repeated unit
and interaction suites, assembled real-API tests, and Chrome/Edge workflows,
visual review and keyboard/focus baselines in English and Arabic. Firefox,
Safari and CI remain deferred at the user's instruction. The verification
report records the evidence and existing behavior limitations.

## 9 Local Phase 3 completion

On 10 November 2026, Application Settings entry points and per-client view state
were extracted into `application_settings_controller.py`. The existing renderer,
single-page shell, routes and navigation behavior remain unchanged. The
[Phase 3 verification report](../docs/webui-refactor-phase3-verification.md)
records the implementation, repeated suites, real-API checks, Chrome/Edge
workflows, English/Arabic visual and focus comparisons, and database cleanup.
Firefox, Safari and CI remain deferred. At the Phase 3 handoff, its changes were
local and uncommitted on the user's existing branch, with Phase 4 review still
pending. The reviewed Phase 3 revision is recorded in the Phase 4 report below.

## 10 Phase 4 approach review

The [Phase 4 review](../docs/webui-refactor-phase4-review.md) recommends retaining
the pilot's explicit feature boundaries and dividing Phase 5 into smaller
steps: navigation data helpers, shell presentation, navigation coordination,
then session lifecycle. Each step adds missing baseline checks before moving
code and must pass its acceptance checks before the next begins. This retains
the eight phases and the existing prohibition on functionality or UX changes.
The user authorized Phase 5 on 10 November 2026. Its smaller steps were completed
sequentially; see the [Phase 5 verification report](../docs/webui-refactor-phase5-verification.md).


## 11 Phase 5 completion

Phase 5A–5D shared infrastructure is complete locally and the final Chrome/Edge,
unit, interaction and assembled checks pass. The first Edge run encountered a
custody-loading timeout. After diagnostic logging was added, it did not recur in
the full Edge rerun or in 12 transitions each on the original and refactored code.
The cause remains unresolved; no fix or proven existing defect is claimed.

The user explicitly approved marking Phase 5 complete with this non-reproduced
loading problem recorded. This exception applies only to that observation; the
general regression gate and prohibition on functionality or UX changes remain
unchanged. Diagnostics are retained for any recurrence. See the verification
report for evidence. Phase 6 had not started at that handoff; Firefox, Safari and
CI remain deferred.

## 12 Approved Phase 6 sequence

The [Phase 6 plan](../docs/webui-refactor-phase6-plan.md) defines ordered steps
6A–6U based on the inventory, pilot and shared-infrastructure results. It assigns
each remaining feature, its supporting controls and connected workflows to an
owner, with baseline and acceptance checks before progressing. The plan is
approved by the user. The user authorized 6A, which is now complete; see the
[6A verification report](../docs/webui-refactor-phase6a-verification.md).
The original approval required a prompt before each subsequent sub-phase.
That requirement was superseded by the continuation authorization below.

The user subsequently authorized 6B (audit trail and entity history), now complete;
see the [6B verification report](../docs/webui-refactor-phase6b-verification.md).

The user subsequently authorized 6C (shared entity controls), now complete;
see the [6C verification report](../docs/webui-refactor-phase6c-verification.md).
The user subsequently authorized 6D (Classification), now complete; see the
[6D verification report](../docs/webui-refactor-phase6d-verification.md).
The user subsequently authorized 6E (Security configuration and access controls),
now complete; see the [6E verification report](../docs/webui-refactor-phase6e-verification.md).
The original approval stop before 6F was superseded below.

On 11 November 2026 the user authorized continuing through all remaining Phase 6
sub-phases (6F–6U), retaining per-row acceptance and reporting. Individual
approval stops were lifted by that instruction. The user's later instruction
initially required stopping after 6M. The latest instruction authorizes **6N
through 6U**, retaining all verification gates. No product changes or Git
mutations are authorized. At completion of the whole WebUI refactor, remind the
user of both pre-existing aggregation defects in the 6M report.

6F–6M are complete for the approved local scope; see the individual reports for
[login sessions](../docs/webui-refactor-phase6f-verification.md),
[organization](../docs/webui-refactor-phase6g-verification.md),
[text indexers](../docs/webui-refactor-phase6h-verification.md), and
[account/preferences](../docs/webui-refactor-phase6i-verification.md) and
[translations/Inspector](../docs/webui-refactor-phase6j-verification.md) and
[legal holds](../docs/webui-refactor-phase6k-verification.md) and
[digital components/preview](../docs/webui-refactor-phase6l-verification.md) and
[aggregations](../docs/webui-refactor-phase6m-verification.md).

All Phase 6 sub-phases, including 6N–6U, are complete for the approved local
scope. The [overall report](../docs/webui-refactor-phase6-verification.md) links
each individual gate. Phases 7 and 8 have not started. At the final WebUI handoff,
deliver the user-requested prioritized list of all recorded pre-existing defects
and abnormalities, using the [working register](../docs/webui-refactor-existing-observations.md).
This reporting requirement does not authorize product fixes.
