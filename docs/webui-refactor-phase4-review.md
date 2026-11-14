# WebUI refactor: Phase 4 approach review

**Date:** 10 November 2026  
**Reviewed revision:** `541aad12e66b666f79b7009be13e90ecf369fb01`  
**Status:** Review complete; user authorized Phase 5 on 10 November 2026.

## Recommendation

**Proceed with smaller steps inside Phase 5.** Keep the eight-phase plan and
the controller-and-renderer pattern demonstrated by Settings. Do not expand
this small pilot into a general routing framework or a shared object containing
every feature's state. No functionality, UI, UX, URL or browser-history change
is authorized. Execution is recorded in the [Phase 5 progress report](webui-refactor-phase5-verification.md).

## What the pilot establishes

| Area | Finding | Decision |
| --- | --- | --- |
| Feature ownership | Settings owns authorization, category, view identity and its four entry paths. Each client has its own controller. | Keep this pattern where it fits existing features; do not require every feature to use the same class shape. |
| Dependencies | Ten explicit dependencies replace access to the large host closure. The feature neither imports `app.py` nor receives its shared state dictionaries. | Keep dependencies narrow. Group them only when a concrete shared responsibility emerges. |
| Shared responsibilities | Shell entry, snapshot persistence, navigation guards and read cancellation still belong to the host. | Extract those responsibilities separately; do not copy them into each feature. |
| Behavior | The renderer is unchanged. Local functional, visual, focus and request-count evidence passes. | Accept the pilot within the agreed Chrome/Edge scope. |
| Maintainability and effort | The controller is 96 lines; `app.py` shrank by only nine lines. Most shared coupling remains. | The benefit is clearer ownership and direct tests. Do not estimate the rest of the migration by lines moved or promise that later moves will be equally easy. |

The controller's view token rejects late callbacks; it does not itself cancel
network reads. Existing navigation and the API client still cancel reads, while
the renderer checks view validity. Preserve that division and the existing
treatment of accepted writes. Likewise, keep category assignment before shell
entry and audit-dialog closure before the existing navigation guard: their order
is part of current behavior.

## Evidence and limits

The [Phase 3 report](webui-refactor-phase3-verification.md) records 1,497 unit and
209 interaction tests passing twice, 40 assembled real-API tests, and 44 full
workflow checks per browser. Each browser also passed 12 keyboard groups with
58 focus observations matching Phase 2. Of 58 full-workflow screenshots, 54
match exactly below the animated header; four differ only in real timestamps.
Settings request counts match. All nine disposable databases were removed.

For this review, the saved reports and screenshot hashes were checked again.
All runtime files recorded by the browser runs still match the current files.
Older reports contain the earlier navigation test helper; the final Edge full
run and Chrome navigation recheck match the corrected helper. That timing fix
waits for restoration to finish; it changes no application behavior.

No new regression was identified in the reviewed pilot. This does not establish
whole-application regression freedom. The 30-destination assembled smoke test
checks entry, heading and request completion, not every workflow. Some existing
tests still extract functions from `app.py`. The fixed viewport, deferred
Firefox/Safari/CI checks, and non-controlled latency measurements remain limits.
The animated header needs its own visual evidence before shell code moves;
excluding it from the Settings pixel comparison does not verify that region.

## Proposed Phase 5 sequence

Each step must pass before the next begins. Add missing behavior checks against
the current implementation first, then move the code without changing behavior.

| Step | Small extraction | Evidence required before accepting it |
| --- | --- | --- |
| 5A Navigation data helpers | Move the existing entry identity, duplicate handling, trail limit and visible-index helpers. Keep persistence and dispatch in their current owner. | Preserve existing assertions for consecutive duplicates, distinct job/task IDs, limits and overflow. Test the extracted functions directly. |
| 5B Shell presentation | Move one shell section at a time, preserving element construction order, classes, callbacks and existing component instances. Supply explicit handles and callbacks. | Add English/Arabic header, drawer and breadcrumb baselines, including narrow viewport, collapse/overflow, restricted visibility, dialogs and focus. Check every destination still opens. |
| 5C Navigation coordination | Move trail storage, registration, restoration and guard coordination in separate changes. Leave feature loaders behind explicit callbacks until their own migration. | Add assembled checks for restoration finishing before the next visit, missing/forbidden targets and fallback, trail truncation, in-app Back and cancelled guards. Preserve stored state, search URLs, request cancellation and browser exit behavior. |
| 5D Session lifecycle | Move identity access and cleanup gradually, keeping API-client ownership, localization, caches and live-message connections intact. | Extend assembled/browser coverage for simultaneous independent clients, late old-identity responses, disconnect/reconnect, expiry/sign-out, required password changes and recovery. Verify existing read cancellation and accepted-write behavior. |

These are checks of existing behavior, not proposals for new workflows or
privileges. Existing unit and interaction coverage is retained; replace
location-dependent tests with direct module tests only while preserving their
assertions. If a baseline check exposes an existing defect, record it and seek
separate approval for a correction rather than changing the expected UX.

For every step, run the relevant direct tests and the full WebUI suites. Changes
to rendered UI, navigation or session behavior also require the affected real-API
and Chrome/Edge journeys, English/Arabic appearance and focus checks, request
bounds, freshness and abandoned-work checks. Repeat the full local acceptance
set before declaring Phase 5 complete. Use fresh disposable databases for every
database-backed run. Firefox, Safari and CI remain deferred as instructed.

## How to keep the work manageable

Keep one owner for the shared interfaces. Independent feature work should wait
until those interfaces are stable. During development, use focused tests for
feedback; run acceptance checks against a frozen change. Wait for observable
completion in browser tests, retain failed attempts, and never replace visual
baselines simply to make a comparison pass. Measure latency under comparable
local load before accepting performance-sensitive shared changes.

Maintain a requirement → implementation → test record for each step. Any
unexplained functional, visual, focus, permission or performance difference
blocks that step. Leave rollback and Git operations to the user; this review
does not authorize branches, commits, pushes or history changes.

This phase changes documentation only. No application code, test expectations,
database, browser settings or environment configuration was changed, and no
test services were started. The review relies on the verified Phase 3 evidence;
it does not claim a new test run. The user subsequently authorized Phase 5;
its sequential acceptance gates remain in force.
