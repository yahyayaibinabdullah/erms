# Aggregation and Record Types — Implementation Traceability

**Status:** Approved plan. Phase 0 passed 230 regression cases and both large-data gates. Phase 1 passed its schema, upgrade, field-validation and standard performance gates. Phase 2 passed its regression, populated-upgrade and large-dataset gates. Phase 3 passed its structured-search, sorting, saved-search and performance gates. Phase 4 passed the keyword-index, upgrade and large-dataset gates, including the post-merge repeat. Phase 5 passed the API, UI, translation and large-dataset gates. Phase 6 passed the integrated regression, upgrade and final performance gates. [Phase 6 evidence](verification/aggregation-record-types-phase-6.md) [Phase 5 evidence](verification/aggregation-record-types-phase-5.md) [Phase 4 evidence](verification/aggregation-record-types-phase-4.md) · [Phase 3 evidence](verification/aggregation-record-types-phase-3.md) · [Phase 2 evidence](verification/aggregation-record-types-phase-2.md) · [Phase 1 evidence](verification/aggregation-record-types-phase-1.md)

**Prepared:** 18 November 2026

Authority: [approved specification](../specs/aggregation-and-record-types.md)
and [phased implementation plan](../specs/aggregation-and-record-types-implementation-plan.md).
Phase numbers below refer to that plan. The evidence column describes the complete requirement across its owning phases. Each phase records the portion exercised before the next phase begins.

| Requirement | Owning phases | Required evidence | Status |
| --- | --- | --- | --- |
| ART-01 — catalogues, optional compatible type, stable IDs, uniqueness | 1, 2 | Schema/upgrade constraints, API membership/uniqueness tests, preserved untyped data | Schema, populated upgrade and scoped administration/assignment APIs verified. |
| ART-02 — seven data types and validation | 1, 2, 5 | Storage/API boundary and round-trip tests, exact decimal/datetime values, UI controls | Native storage and API literal validation verified, including exact decimal and datetime values. The shared WebUI scalar controls use the same typed-literal rules. |
| ART-03 — translated definitions and choices | 1, 3, 5 | Language fallback, stable-ID search after renaming, supported-language editor, LTR/RTL evidence | Definition storage and fallback were verified in Phase 1. Search uses stable field and choice IDs after a rename or translation. The administration screens reuse the supported-language entity editor. |
| ART-04 — single untranslated text values/defaults | 1, 4, 5 | Cross-language value equality, search/index values, no language-specific content storage | Storage and resource APIs retain one literal per field. Phase 4 verifies English and Arabic terms from that literal in the same metadata document. Both first-tab detail views display the same stored text across languages. |
| ART-05 — Unicode text length and control threshold | 1, 2, 5 | Limit/reduction tests and single-line/multiline UI behavior | Unicode limits and concurrent length reduction verified. The form switches to a text area above 255 characters. Unicode and multiline inputs are covered by the interaction suite. |
| ART-06 — required/optional and later updates | 1, 2, 5 | Null/blank/zero/false and required-field-change tests; unrelated operations remain valid | Required-field changes and resource metadata save validation verified. The shared form exercises required checks, false, zero, clearing and default preservation across field pages. |
| ART-07 — static defaults | 1, 2, 5 | Initialization/override/clear tests, no backfill or ordinary-update reapplication | Assignment defaults, explicit clearing and preservation verified. The shared form exercises required checks, false, zero, clearing and default preservation across field pages. |
| ART-08 — single-choice integrity | 1, 2, 3, 5 | Membership/default/deletion tests, stable queries after label/order changes, choice editor | Choice membership, references, stored selection and read disclosure were verified in Phases 1–2. Phase 3 tests membership by ID and sorting by configured order. The administration dialog maintains the ordered choices and their labels. Resource selectors submit stable IDs. |
| ART-09 — administration and operation authority | 0, 2, 5 | Two new privileges and default grants to both governance profiles and ALL_PRIVS, explicit delegation, fresh/upgrade preservation, route inventory, allowed/denied/out-of-scope API tests | API tests cover kind-specific delegation and denied administration. Fresh and populated-upgrade checks cover the six default role/privilege pairs. Each administration drawer entry follows its resource-kind privilege. The role-directory endpoint checks that same privilege. |
| ART-10 — reassignment/removal and history | 1, 2, 4, 5 | Source/destination checks, atomic clears/defaults, event history, confirmation and stale-index tests | Source and destination grants, confirmation, clearing and historical disclosure verified for both resource kinds. Phase 4 verifies removal of reassigned and cleared terms. NiceGUI checks cover confirmation, cancellation and stale requests after reassignment. [History evidence](verification/aggregation-record-types-phase-2.md#resource-history-after-reassignment) |
| ART-11 — safe definition changes | 1, 2, 3 | Populated deletion/type-change safeguards, valid defaults, removed-definition query errors | Stored-value and default safeguards passed. Removing a referenced field leaves the stored definition intact and produces a validation error on Open or Execute. |
| ART-12 — existing forms/details conventions | 5 | Live comparison of both resource dialogs, preserved tabs, primary-before-type section, LTR/RTL controls | First-tab integration in both details dialogs, shared typed resource controls and browser evidence. [Phase 5](verification/aggregation-record-types-phase-5.md) |
| ART-13 — structured and full-text behavior | 3, 4 | Operators/type scope/untyped/unset, text-only indexing, counts/paging/freshness, large-data oracles | Phase 3 tests structured operators, mixed types and primary fields, negation, missing values and paging. Phase 4 verifies own-resource keyword matches, exclusions, scores, paging and index freshness. [Full-text evidence](verification/aggregation-record-types-phase-4.md) |
| ART-14 — See/Use and gate order | 1, 2, 5 | Use-implies-See, empty grants, untyped resources, role union/expiry/ancestry, explanation order | API, database, explanation and list checks cover See, Use, effective-role union and expiry. The administration view explains the governance rule. The role-directory API and bounded resource selectors enforce the corresponding privileges. |
| ART-15 — governance bypass boundaries | 2, 5 | See/Use and ACL bypass, own clearance, missing privilege, lifecycle/administration/custody denials | API and batch checks cover governance bypass, own clearance, separate privileges, and custody. The administration view explains the governance rule. The role-directory API and bounded resource selectors enforce the corresponding privileges. |
| ART-16 — operation coverage | 2 | Create/update/delete, type source/destination, components, bulk and direct API negative tests | Typed writes, source/destination changes, component upload, file drop and draft placement exercised through resource APIs. [Regression evidence](verification/aggregation-record-types-phase-2.md) |
| ART-17 — custody, audit and freshness | 2, 3, 4 | Transaction/concurrency tests, policy/reassignment history, cached-page revocation and index freshness | Custody, concurrent permission changes and historical snapshots passed Phase 2. Phase 3 rechecks type references on paging and rebuilds after a choice reorder. Phase 4 verifies concurrent text edits, rollback, reassignment and searches after commit. |
| ART-18 — equivalent policy and no leakage | 2, 3, 4 | Independent expected decisions plus Python/SQL/batch equivalence, hidden lists/counts/relations/components/explanations | Phase 2 verified instance visibility and related data. Phase 3 verifies nested forbidden criteria and sorts, denied definitions, and independent administrative inspection. Phase 4 verifies denied text searches, cached-page revocation and erasure of typed words on destruction. |
| ART-19 — mixed types and sorting | 0, 3, 5 | Approved missing-last ordering in both directions, native values, language-independent choice order, choice-reorder cache invalidation, JSON contract, stable IDs and pagination | Phase 3 tests all seven data types, missing-last order in both directions, ID ties, multi-type Boolean queries, stable choice IDs, translated choice labels, reorder invalidation and page continuity. The existing condition and sort rows use type-scoped selectors. Mixed resource types and saved secondary keys round-trip through the builder model. |
| ART-20 — consistent UI and translations | 5 | Existing table/dialog/builder conventions, bounded scoped selectors, translation/choice editing, catalogue checks | Standard page tables, shared administration and translation editors, scoped paging and catalogue checks. [Phase 5](verification/aggregation-record-types-phase-5.md) |
| ART-21 — measured regression/performance impact | 0–6 | Phase baselines and applicable large-data gates, individual complete-response samples, exact outcomes/plans/JIT/cleanup | [Phase 0 measurements](verification/aggregation-record-types-phase-0.md), [Phase 1 standard and upgrade gates](verification/aggregation-record-types-phase-1.md), [Phase 2 regression and performance evidence](verification/aggregation-record-types-phase-2.md), [Phase 3 structured and saved-search evidence](verification/aggregation-record-types-phase-3.md), [Phase 4 full-text results](verification/aggregation-record-types-phase-4.md), [Phase 5 UI tests and measurements](verification/aggregation-record-types-phase-5.md) and [final fresh and upgraded measurements](verification/aggregation-record-types-phase-6.md). |
| ART-22 — restricted shared saved searches | 3, 5 | Summary-only responses, no forbidden definition on list/read/restore, Open/Execute denial, See-only access, revocation/restoration | Phase 3 verifies summaries, Open/Execute, independent inspection, revocation and restored access. Chrome verified disabled Open and its explanation in English and Arabic. The normal builder restores typed conditions and sort keys after the saved definition passes the access check. |
| ART-23 — query authorization sets | 2, 3, 4, 5, 6 | Actual plans/statement counts, no new per-resource type queries or repeated type work across branches, current-access paging | Phase 2 verified shared access sets and current-access paging. Phase 3 captures cached and uncached typed plans and checks IDs and totals against an independent oracle. [Typed search evidence](verification/aggregation-record-types-phase-3.md) · [Phase 4 full-text plans](verification/aggregation-record-types-phase-4.md) · [Final authorization, paging and upgrade evidence](verification/aggregation-record-types-phase-6.md) |

The [Phase 6 reconciliation](verification/aggregation-record-types-phase-6.md#requirement-reconciliation) maps ART-01 through ART-23 to the integrated implementation and verification evidence.

The privilege and sorting contract decisions are approved. Phase 2 covers the privileges. Phase 3 covers sorting. Type-specification section 10.1's classification,
optional-field hiding, and parent-type compatibility topics are deferred and
are not missing implementation obligations in this ledger. Custom-entry and
conditional companion-field behavior likewise remain outside approved scope.

## Cross-specification evidence

- Advanced Search AS-27 maps to ART-22; preserve existing AS criteria and cache
  scope, submitted filters, complexity limits, and old saved definitions.
- Security gate order, governance own-clearance, remaining gates, no leakage,
  continuity, and explanation/audit rules map to ART-09 and ART-14–18.
- Internationalization and WebUI performance obligations map to ART-03,
  ART-12 and ART-20, including protected translation provenance and Arabic drafts.
- Search performance acceptance maps to ART-21 and ART-23 for every changed
  query flow; attach both standard and larger-text results where applicable.

## Evidence record for each phase

Record: phase/status; resolved contract decisions; affected implementation
files; test commands and results; disposable database creation/cleanup;
fixture/source hashes; expected/actual results; response-time samples and
before/after comparison; execution plans and JIT details; browser evidence;
remaining requirements/approved exceptions; and next work. Keep failed attempts
and corrected reports. A blocked product decision must name the dependent
requirements rather than silently substituting behavior.

Phase 0 evidence is recorded in the [baseline report](verification/aggregation-record-types-phase-0.md). Phase 1 evidence is recorded in the [foundation and upgrade report](verification/aggregation-record-types-phase-1.md).

## Approved Phase 2 audit scenario

ART-10, ART-15, ART-17 and ART-18 cover history after reassignment. An authorized auditor may identify both types in the transition. Each side’s record or aggregation values require current See on that side. This preserves an intelligible chronology while protecting instance data, including which choice the user selected. Verify ordinary UPDATE snapshots and the type-metadata event through both entity history and the system audit view. Exercise See on B alone, subsequent grant and revocation on A, governance clearance and denied resource access. [Approved rule and example](../specs/aggregation-and-record-types.md#historical-values-after-reassignment--approved-19-november-2026)

### Creation and reassignment regressions

| Scenario | Verification |
|---|---|
| Collection Add, translated type shortcut and editable initial assignment | The focused Chromium `creation-buttons` scope checks both languages, both kinds, standalone corners, split-button placement, hover and the editors opened by each action. Shared form tests check the submitted payloads |
| Add, edit or remove roles, including Everyone | The focused Chromium `type-role-removal` scope checks multi-selection across pages, automatic read-only See, independent Use settings, deselection and re-selection, editing, and confirmed removal in both languages and both type catalogues |
| Aggregation drop with one eligible creator role | Drop interaction tests cover immediate creation without usable types, review with usable types, and cancellation before upload |
| Separate typed records | Multipart API tests cover distinct field maps for duplicate filenames, required-field rollback and revoked Use |
| Files dropped on Records | Chromium checks one untyped draft, staged files, the suggested title and cancellation in English and Arabic. The assembled Records test selects a destination, commits the draft and checks the saved components in order |
| Files dropped into an open draft on an aggregation | Chromium checks that the native uploader stages the component on that draft and that the drop does not submit a separate record-creation request |
| Existing record or aggregation changes from A to B | API tests cover authorization on both sides, confirmation, stale versions, snapshots, redaction and full-text freshness. The Chromium resource-types scope exercises cancel and confirm through each resource editor |

The 23 November 2026 large-data rerun used 51,003 aggregations, 153,009
records and 182 usable types of each kind. Across three rounds, the one-row
availability probes took 9.1–10.4 ms for aggregations and 7.0–7.9 ms for
records. The first and second 25-item menu pages took 10.9–14.2 ms and
7.9–8.5 ms respectively. All 240 type UI samples and all 237 structured
search samples met the existing three-second limit. The slowest structured
search took 2.7463 seconds. Reproduce with
`tools/check_search_performance.py --type-ui`.
