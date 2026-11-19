# Aggregation and Record Types — Implementation Traceability

**Status:** Approved plan. Phase 0 passed 230 regression cases and both large-data gates. Phase 1 passed its schema, upgrade, field-validation and standard performance gates. Phase 2 passed its regression, populated-upgrade and large-dataset gates. Phase 3 passed its structured-search, sorting, saved-search and performance gates. [Phase 3 evidence](verification/aggregation-record-types-phase-3.md) · [Phase 2 evidence](verification/aggregation-record-types-phase-2.md) · [Phase 1 evidence](verification/aggregation-record-types-phase-1.md)

**Prepared:** 18 November 2026

Authority: [approved specification](../specs/aggregation-and-record-types.md)
and [phased implementation plan](../specs/aggregation-and-record-types-implementation-plan.md).
Phase numbers below refer to that plan. The evidence column describes the complete requirement across its owning phases. Each phase records the portion exercised before the next phase begins.

| Requirement | Owning phases | Required evidence | Status |
| --- | --- | --- | --- |
| ART-01 — catalogues, optional compatible type, stable IDs, uniqueness | 1, 2 | Schema/upgrade constraints, API membership/uniqueness tests, preserved untyped data | Schema, populated upgrade and scoped administration/assignment APIs verified. |
| ART-02 — seven data types and validation | 1, 2, 5 | Storage/API boundary and round-trip tests, exact decimal/datetime values, UI controls | Native storage and API literal validation verified, including exact decimal and datetime values. UI checks belong to Phase 5. |
| ART-03 — translated definitions and choices | 1, 3, 5 | Language fallback, stable-ID search after renaming, supported-language editor, LTR/RTL evidence | Definition storage and fallback were verified in Phase 1. Search uses stable field and choice IDs after a rename or translation. The supported-language editor belongs to Phase 5. |
| ART-04 — single untranslated text values/defaults | 1, 4, 5 | Cross-language value equality, search/index values, no language-specific content storage | Storage and resource APIs retain one literal per field. Index and UI checks belong to Phases 4 and 5. |
| ART-05 — Unicode text length and control threshold | 1, 2, 5 | Limit/reduction tests and single-line/multiline UI behavior | Unicode limits and concurrent length reduction verified. Control selection belongs to Phase 5. |
| ART-06 — required/optional and later updates | 1, 2, 5 | Null/blank/zero/false and required-field-change tests; unrelated operations remain valid | Required-field changes and resource metadata save validation verified. Form checks belong to Phase 5. |
| ART-07 — static defaults | 1, 2, 5 | Initialization/override/clear tests, no backfill or ordinary-update reapplication | Assignment defaults, explicit clearing and preservation verified. Form checks belong to Phase 5. |
| ART-08 — single-choice integrity | 1, 2, 3, 5 | Membership/default/deletion tests, stable queries after label/order changes, choice editor | Choice membership, references, stored selection and read disclosure were verified in Phases 1–2. Phase 3 tests membership by ID and sorting by configured order. The choice editor belongs to Phase 5. |
| ART-09 — administration and operation authority | 0, 2, 5 | Two new privileges and default grants to both governance profiles and ALL_PRIVS, explicit delegation, fresh/upgrade preservation, route inventory, allowed/denied/out-of-scope API tests | API tests cover kind-specific delegation and denied administration. Fresh and populated-upgrade checks cover the six default role/privilege pairs. UI administration belongs to Phase 5. |
| ART-10 — reassignment/removal and history | 1, 2, 4, 5 | Source/destination checks, atomic clears/defaults, event history, confirmation and stale-index tests | Source and destination grants, confirmation, clearing and historical disclosure verified for both resource kinds. Index and UI checks remain. [History evidence](verification/aggregation-record-types-phase-2.md#resource-history-after-reassignment) |
| ART-11 — safe definition changes | 1, 2, 3 | Populated deletion/type-change safeguards, valid defaults, removed-definition query errors | Stored-value and default safeguards passed. Removing a referenced field leaves the stored definition intact and produces a validation error on Open or Execute. |
| ART-12 — existing forms/details conventions | 5 | Live comparison of both resource dialogs, preserved tabs, primary-before-type section, LTR/RTL controls | Planned |
| ART-13 — structured and full-text behavior | 3, 4 | Operators/type scope/untyped/unset, text-only indexing, counts/paging/freshness, large-data oracles | Phase 3 tests structured operators, mixed types and primary fields, negation, missing values and paging. Indexing text values belongs to Phase 4. |
| ART-14 — See/Use and gate order | 1, 2, 5 | Use-implies-See, empty grants, untyped resources, role union/expiry/ancestry, explanation order | API, database, explanation and list checks cover See, Use, effective-role union and expiry. UI checks remain. |
| ART-15 — governance bypass boundaries | 2, 5 | See/Use and ACL bypass, own clearance, missing privilege, lifecycle/administration/custody denials | API and batch checks cover governance bypass, own clearance, separate privileges, and custody. UI checks remain. |
| ART-16 — operation coverage | 2 | Create/update/delete, type source/destination, components, bulk and direct API negative tests | Typed writes, source/destination changes, component upload, file drop and draft placement exercised through resource APIs. [Regression evidence](verification/aggregation-record-types-phase-2.md) |
| ART-17 — custody, audit and freshness | 2, 3, 4 | Transaction/concurrency tests, policy/reassignment history, cached-page revocation and index freshness | Custody, concurrent permission changes and historical snapshots passed Phase 2. Phase 3 rechecks type references on paging and rebuilds after a choice reorder. Text index freshness belongs to Phase 4. |
| ART-18 — equivalent policy and no leakage | 2, 3, 4 | Independent expected decisions plus Python/SQL/batch equivalence, hidden lists/counts/relations/components/explanations | Phase 2 verified instance visibility and related data. Phase 3 verifies nested forbidden criteria and sorts, denied definitions, and independent administrative inspection. Keyword-index checks belong to Phase 4. |
| ART-19 — mixed types and sorting | 0, 3, 5 | Approved missing-last ordering in both directions, native values, language-independent choice order, choice-reorder cache invalidation, JSON contract, stable IDs and pagination | Phase 3 tests all seven data types, missing-last order in both directions, ID ties, multi-type Boolean queries, stable choice IDs, translated choice labels, reorder invalidation and page continuity. Builder controls belong to Phase 5. |
| ART-20 — consistent UI and translations | 5 | Existing table/dialog/builder conventions, bounded scoped selectors, translation/choice editing, catalogue checks | Planned |
| ART-21 — measured regression/performance impact | 0–6 | Phase baselines and applicable large-data gates, individual complete-response samples, exact outcomes/plans/JIT/cleanup | [Phase 0 measurements](verification/aggregation-record-types-phase-0.md), [Phase 1 standard and upgrade gates](verification/aggregation-record-types-phase-1.md), [Phase 2 regression and performance evidence](verification/aggregation-record-types-phase-2.md), and [Phase 3 structured and saved-search evidence](verification/aggregation-record-types-phase-3.md). |
| ART-22 — restricted shared saved searches | 3, 5 | Summary-only responses, no forbidden definition on list/read/restore, Open/Execute denial, See-only access, revocation/restoration | Phase 3 verifies summaries, Open/Execute, independent inspection, revocation and restored access. Chrome verified disabled Open and its explanation in English and Arabic. Typed condition and sort controls belong to Phase 5. |
| ART-23 — query authorization sets | 2, 3, 4, 5 | Actual plans/statement counts, no new per-resource type queries or repeated type work across branches, current-access paging | Phase 2 verified shared access sets and current-access paging. Phase 3 captures cached and uncached typed plans and checks IDs and totals against an independent oracle. [Typed search evidence](verification/aggregation-record-types-phase-3.md) |

Phase 6 reconciles every row against the final integrated code and upgraded
schema. It does not defer earlier rows' verification until the end.

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
