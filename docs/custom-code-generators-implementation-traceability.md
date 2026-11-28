# Custom Code Generators Implementation Traceability

**Authority:** [Approved specification revision 0.6](../specs/custom-code-generators.md).

**Updated:** 28 November 2026.

**Status:** Phases 0–6 and the approved revision 0.6 applicability extension are complete. The two outdated checks recorded in the original applicability run are now repaired, with 166 affected-suite tests passing and application behavior unchanged. Functional, browser, upgrade, permission,
translation and final measurement/close-out evidence is recorded.
Slow search/selector timings are reported for separate optimization under the
user's direction, without claiming a strict latency pass.
Unrelated search optimizations were removed at the user's direction. Current
search changes implement attached-field natural ordering only; performance
optimization is reserved for a separate session. See the phase 6 scope correction.

## Phase status

| Phase | Status | Evidence and remaining work |
| --- | --- | --- |
| 0 Contract mapping and baseline | Complete | [Integration and transaction design](custom-code-generators-integration.md); [verification report](verification/custom-code-generators-phase0.md): 189 functional checks passed; both search correctness baselines completed, with 12 pre-existing latency failures retained and all five disposable databases dropped. |
| 1 Schema and allocation | Complete | [Phase 1 report](verification/custom-code-generators-phase1.md): renderer/schema parity, database constraints/audit, allocation/adjustment/configuration races, populated upgrade preservation/rollback/locking/space, and 96 existing creation/type regressions passed. All disposable databases dropped. |
| 2 Administration APIs | Complete | [Phase 2 report](verification/custom-code-generators-phase2.md): thirteen privileged operations, exact names/serials, versions/reasons/audit, isolated previews, scoped adjustments and measured paginated definitions/selectors/counters. Nine Arabic drafts added without changing curated items. The checkpoint's glossary failure is retained historically; final translation checks pass in phase 6. |
| 3 Creation and safe retries | Complete | [Phase 3 report](verification/custom-code-generators-phase3.md): all creation adapters, exact recommendations, preserved files, safe replay, simultaneous/manual races, scoped hints, stale contexts, no backfill, closed-placement correction and populated upgrade. Integrated run: 170 passed, one catalogue-order assumption failed; all affected cases passed after correcting it. Dialog/client regressions passed. All disposable databases dropped. |
| 4 Natural ordering | Complete | [Phase 4 report](verification/custom-code-generators-phase4.md): 59 post-removal correctness tests; 801 complete generator responses with correct results. All 630 code-search responses met three seconds; 129 selector overruns are recorded for separate work under the user's direction. |
| 5 WebUI | Complete | [Phase 5 report](verification/custom-code-generators-phase5.md): named listing, settings, five-value simulator, historical names and counter controls; keyboard/validation and English/Arabic narrow/desktop checks; numberless upload, exact conflict preservation and explicit corrected-document recovery. Final catalogue and WebUI checks pass in phase 6. |
| 6 Integrated verification | Complete | [Phase 6 report](verification/custom-code-generators-phase6.md): creation/concurrency, API/database/WebUI, schema/upgrade, policy and translation checks pass. Final measurements cover 3,198 correct API responses; 190 child-list/selector timings are reported for separate optimization. [Operator guidance](custom-code-generators-operations.md) is complete. Full remote CI/deployment were not performed. |

## Requirement coverage

The implementation column identifies owning phases. Reports for phases 1–6
provide executed evidence. Slow search samples remain failures and are reported
for separate work under the user's 27 November close-out instruction; they are
not treated as missing generator implementation or as latency passes.

| Requirement | Implementation work | Verification and current evidence |
| --- | --- | --- |
| CG-01 Text targets | Phases 1/2/5: server target catalogue, stable field references and database eligibility guards. | Phases 1/2 passed non-Text/system-field rejection and attached-field edit/deletion guards, including populated upgrades. Phase 5 live typed/Text-only selectors and validation passed. |
| CG-02 Names and configuration | Phases 1/2/5: required nonblank names, setting validation, overlapping enabled binding checks and rename stability. | Phases 1/2 passed blank-name, all/named-type overlap, enable/retarget race, required-placeholder and rename/counter tests. Phase 5 named creation, edit reasons, rename and historical names passed. |
| CG-03 Pattern and context | Phases 1/2/3/5: one renderer, all tokens/escapes, existing owner/Create for and one working-timezone instant. | Renderer and API checks passed tokens/escapes, missing context, authorized owner/Create for, working-timezone boundaries and ASCII digits. Phase 5 keyboard insertion, fictional contexts and actual owner/Create for values passed. |
| CG-04 Counter scopes and resets | Phases 1/2/3/5: stable scope IDs and Never/Yearly/Monthly buckets. | Engine/store/API checks passed start 10/increment 10, four scopes, full calendar buckets, boundaries and retained configuration state. Phase 5 annual, monthly, split-scope and combined owning-unit simulations passed without allocation. |
| CG-05 Padding and length | Phases 1/2/3/5: optional minimum padding and Unicode complete-code/field limits. | Engine/store/creation tests passed absent/zero/positive padding, growing serials, Unicode lengths, target limits and atomic length failure. Phase 5 live field-capacity failure cleared stale preview rows; final UI regressions passed. |
| CG-06 Future creation | Phases 3/5: authorized final creation after static defaults; retain manual values, numberless drafts and ordinary edits. | Phase 3 API/dialog checks passed for numberless drafts, defaults, explicit blanks, manual values, later type assignment and edits without generation. Phase 5 observed numberless draft upload and exact chosen-number recovery with matching downloaded document bytes. |
| CG-07 Atomic allocation and reuse | Phases 1/3/6: transactional allocation, occupied new-candidate skipping, no chosen-number substitution, retained counters. | Phases 1/3 passed manual/automatic collision races, hidden/imported occupancy, rollback, deletion/manual reuse and retained scope/reset state. Phase 6 concentrated/mixed complete-request checks passed after correcting the parent-lock deadlock. |
| CG-08 Natural ordering | Phases 4/6: attached-field `erms_code_natural` SQL ordering, matching cursors and cache invalidation. | Mixed-code/tie/null/paging/cache/report and long-Text checks passed, including 59 post-removal regressions. The complete generator matrix returned 801 correct responses; all 630 code-search responses met three seconds. The [final performance report](verification/custom-code-generators-final-performance.md) preserves selector overruns and all other findings for separate work. No strict combined latency pass is claimed. |
| CG-09 Administration | Phases 2/5: named bounded listing, settings management privilege and fresh committed reads. | Phase 2 allowed/denied/scoped API and bounded catalogue/list/counter checks passed. No new access or configuration cache. Phase 5 listing, selectors, freshness, version/error states and real API settings controls passed. |
| CG-10 Suggestions and delivery | Phases 3/5: preserve legacy controls, automatic provenance, exact chosen number, every direct/draft/drop path. | Phase 3 passed legacy/configured suggestions, exact chosen conflicts, copied-document bytes, type/Create for context, stale month/configuration/counter/parent values, late/edit-revert/save/close responses, direct and draft-opening drops. Phase 5 observed numberless draft upload and exact chosen-number recovery with matching downloaded document bytes. |
| CG-11 Five-value simulations | Phases 2/5: unsaved configuration and isolated fictional counters using the real renderer. | Engine/API checks passed five complete values, same/split scopes, month/year transitions, combined resets and zero real writes. Phase 5 live checks verified the five-value sequence, annual transition, monthly owning-unit combined simulation, Arabic rendering and unchanged empty real-counter list. Phase 5 final keyboard, typed-target, validation, English/Arabic and narrow/desktop checks passed. |
| CG-12 Configuration audit | Phases 1/2/5: database-boundary immutable events, historical names, optional create reason, required edit/rename reason. | Database/API checks passed direct-write enforcement, stale edits, historical names, optional creation reasons, required edit reasons and audit-failure rollback. Phase 5 real history retained original and renamed names; localized shared audit regressions passed. |
| CG-13 Shared storage | Phases 1/3/4/6: three shared tables, unique normalized counter/request keys, target lookups and short ordered locks. | Fresh/populated upgrade, first-use/independent-counter races, ordered locks and measured lookup/occupancy plans passed in phases 1–3. Phase 6 complete-request load and full archive/canonical schema/data/grant/sequence comparison passed. |
| CG-14 Forward adjustments | Phases 1/2/5: versioned advance for one scope/period with reason and old/new next values. | Store/API checks passed backward/stale rejection, untouched other counters, concurrent allocation and audit rollback. Phase 5 real counter advance, required reason and backward rejection passed. |
| CG-15 Safe retries | Phases 1/3/5/6: caller/operation/submission identity and atomic completed-result retention. | Phase 3 passed lost-response and four simultaneous retries, changed completed inputs, current access, failed batches/receipts, deleted/destroyed outcomes, review-date replay and frozen original dialog inputs. Phase 5 real conflict/document recovery and phase 6 broader creation/retry checks passed. |

## Evidence

The following source/test references locate the implementation behind the
executed phase reports. Test names alone are not proof of execution; the reports
retain the actual results, failed attempts and disposable-database cleanup.

| Requirements | Main implementation | Verification sources |
| --- | --- | --- |
| CG-01–02 Text targets, names and bindings | `code_generation_store.py`, `code_generator_routes.py`, canonical schema/migrations 126–127, `code_generator_administration.py` | `test_code_generator_database.py`, `test_code_generator_applicability.py`, `test_code_generator_routes.py`, administration interaction tests |
| CG-03–05 tokens, context, scope/reset, padding and length | `code_generation.py`, `code_generation_creation.py`, `creation_roles.py`, `code_generation_store.py` | `tools/tests/test_code_generation_engine.py`, `test_code_generation_creation.py`, store/database/routes tests |
| CG-06–07 creation and atomic allocation | `code_generation_creation.py`, `code_generation_store.py`, `main.py`, `typed_metadata.py` | `test_code_generation_creation.py`, `test_code_generation_store.py`, `test_code_generator_direct_creation.py`, request metrics tests |
| CG-08 natural ordering | `code_ordering.py`, `search.py`, `search_cache.py`, `type_search.py`, `browse.py`, `search_page.py`, `crud.py`, disposition report presentation | `test_code_generator_ordering.py`, existing browse/tab-cache/execution tests, `code_generation_ordering_performance.py` |
| CG-09 administration | `code_generator_routes.py`, `code_generator_administration.py` | routes tests, administration interaction tests, measured listing/type/field/counter pagination |
| CG-10 suggestions and creation paths | `number_suggestions.py`, `code_generation_access.py`, `main.py`, WebUI creation/capture/drop controls | `test_number_suggestions.py`, `test_code_generator_direct_creation.py`, `test_code_generator_file_drop.py`, creation-dialog retry tests, live copied-document conflict/recovery |
| CG-11 preview and simulation | `code_generation.py`, preview route, `code_generator_administration.py` | engine/routes tests, administration interaction tests and English/Arabic browser evidence |
| CG-12 configuration audit | canonical schema/migrations 126–127, generator routes, `code_generator_audit.py` | database/routes audit and rollback tests, `test_code_generator_audit.py`, live historical-name checks |
| CG-13 shared storage | canonical schema/migrations 126–127, `code_generation_store.py`, `creation_requests.py` | canonical/populated-upgrade comparison, database/store races, allocation/request metrics and measured plans |
| CG-14 forward adjustments | `code_generation_store.py`, adjustment route and counter dialog | store/routes tests, live reason/version/backward-rejection checks |
| CG-15 safe retries | `creation_requests.py`, `main.py`, `creation_submission.py` | concurrent replay/store/direct-creation/file-drop tests, `test_creation_submission.py`, creation-dialog retry tests |

API sources/tests are under `backend/services/api/` and its `tests/` directory;
WebUI sources and tests are under `frontend/webui/`. These paths identify code,
not additional deliverables or new requirements.

Baseline artifacts are under
`.runtime/custom-code-generators/phase0-20261126/`. Source hashes distinguish
the existing production implementation from subsequent feature changes.
Database creation and successful cleanup must be recorded for every run.

See the [phase 0 verification report](verification/custom-code-generators-phase0.md)
for the historical baselines, commands, cleanup and gates pending at that time.

The [phase 1 verification report](verification/custom-code-generators-phase1.md)
records the implemented foundation, passing focused checks, measured plans and
lock/space behavior and preserved failures. These foundation checks are combined
with the later API/UI and integration evidence in the requirement table above.

The [phase 2 verification report](verification/custom-code-generators-phase2.md)
records administration API coverage, corrected failures, query plans, cleanup
and translation preservation. UI and actual creation were later verified in
phases 3 and 5.

The [phase 3 verification report](verification/custom-code-generators-phase3.md)
records creation, provenance, retries, retained files, concurrency, native
closure protection, occupied upgrades and corrected test failures. Subsequent
settings UI, natural ordering, browser and translation evidence is recorded in
the phase 4–6 reports.

Historical phase checkpoints do not replace the later feature evidence. Use
the current status table and integrated phase 6 report for the close-out decision.

## Revision 0.6 extension

CG-02 adds All items / Untyped items only / One selected type, disjoint untyped
and named-type populations, compatible migration 127, immutable audit display
and the replacement UI selector. CG-06/10/11 require matching creation, draft,
file-drop, recommendation and hint behavior. Core changes are in the canonical
schema/migration, code_generator_routes, code_generation_store/access,
number_suggestions and code_generator_administration/audit.

Dedicated evidence is recorded in the [applicability verification report](verification/custom-code-generator-applicability-2026-11-27.md): all three populations, native simultaneous-save exclusion, every creation adapter, matching hints/recommendations, no regeneration on later type assignment, English/Arabic selector interactions, immutable applicability audit display and the populated 126-to-127 rollback/preservation check.

The expanded regression run also found and corrected the message-capture savepoint integration defect. The complete capture/direct-creation follow-up passed 59 tests, including actual validated PDF provenance, generated untyped-only numbering, capture-history failure rollback, unchanged staged files and safe retry/replay. Broader draft/applicability/type/file-drop follow-up passed 56 tests. Exact case coverage accounts for all 2,300 original API cases plus the additional PDF case, all six separately executed historical upgrades, 2,567 WebUI tests and the other maintained suites. The original 5,450-case audit retained two pre-existing unrelated failures; both outdated checks subsequently passed their affected-suite reruns. All 39 explicitly observed disposable databases were verified absent; source/policy/configuration/translation checks pass. Full-suite close-out is complete. The original failed attempts and earlier latency overruns remain preserved; the affected checks now pass without rewriting that original run.

The [28 November check repair report](verification/outdated-checks-2026-11-28.md)
records the six relocated source references, unchanged fingerprints and historical
audit upgrade test, 166 passing affected-suite tests and disposal of both test
databases. The original full-run evidence remains unchanged.
