# Aggregation and Record Types — Phased Implementation Plan

**Status:** Approved. Phases 0–3 passed their applicable regression and performance gates on 19 November 2026. Phase 4 awaits authorization. [Phase 3 report](../docs/verification/aggregation-record-types-phase-3.md)

**Prepared:** 18 November 2026

**Authority:** The user approved the updated
[type specification](aggregation-and-record-types.md), including the
[query approach](resource-type-authorization-design.md), on 18 November 2026.
This plan sequences that approved scope; it introduces no new product features
or permissions. Section 10 links the evidence for each completed phase.

## 1. Delivery rules

Execute phases 0–6 in order. Each phase ends with its own regression and
performance evidence; later integration testing does not substitute for those
gates. Fix failures in the owning phase before proceeding. A phase is complete
only when its requirements have implementation and verification evidence.
Incomplete phases are development checkpoints, not independently deployable
releases of partially enforced type access.

Keep changes on the current branch, local and uncommitted. Do not create a
branch/worktree, commit, push, or deploy through this plan. Preserve existing
work. Use disposable databases for all database-backed tests: create a unique
database for each run, initialize it from the canonical schema or the migration
fixture under test, point the complete process at it, and drop it in cleanup
even on failure. Record creation/cleanup errors.

Maintain [the traceability ledger](../docs/aggregation-and-record-types-implementation-traceability.md)
throughout. Link code, tests, browser evidence, benchmark reports, and remaining
limitations. Product-level gaps or departures require explicit approval before
dependent implementation; ordinary technical choices within the approved
contract do not require repeated permission requests.

## 2. Common performance gate

Follow [the search performance contract](../docs/search-performance.md), its
[optimization lessons](../docs/postgresql-search-optimization-lessons.md), and
[accepted benchmark history](../docs/search-performance-benchmarks.md).

| Requirement | Evidence required at each applicable phase gate |
| --- | --- |
| Large dataset | More than 50,000 aggregations and 150,000 records; retain the existing deterministic corpus, extending it with typed/untyped data and role grants as features become available |
| Query workload | Broad matches covering most/all resources, selective matches, empty matches, denied access, governance access, mixed types, and every newly changed query/list flow |
| Limits and repetitions | Existing 1,000-result cap and benchmark page sizes; at least three measured repetitions, including first submissions and subsequent pages; do not discard slow samples |
| Latency | Every measured API response must meet the existing three-second threshold; report individual samples, maxima, and before/after differences, not only averages or medians |
| Correctness | Exact authorized membership/counts, complete capped ranking, stable IDs/order/scores, deterministic ties, and current permissions on every page |
| SQL behavior | Actual execution plans and statement counts demonstrating shared type-access sets and no new per-resource queries or independently repeated type authorization across branches |
| Environment | Source revision plus local diff/hash, runner/fixture versions, dataset distribution, host/PostgreSQL configuration, JIT availability/time, storage policy, and maintenance conditions |
| Cleanup | Disposable database identity, successful cleanup, and retained failure reports |

For existing queries, compare phase results with both phase 0 and the preceding
applicable phase on comparable resource corpora and environments. New typed
queries have no pre-feature implementation baseline: verify their independent
expected results and absolute threshold, then retain them as subsequent
baselines. Separate intentional permission/result changes from regressions;
equivalent-access identities must preserve existing results and scores.

Keep broad queries without explicit type criteria in every authorization/search
gate: all resources still pass type visibility. Also exercise many types and
roles, unequal type populations, mostly allowed and mostly denied data, no type
grants, and governance bypass. Record exact fixture sizes/distributions before
each run. Do not use only small, selective, or uniformly distributed examples.

Use the existing runners, extending their fixtures/cases rather than treating
unrelated passing endpoints as coverage:

```sh
backend/services/api/.venv/bin/python tools/check_search_performance.py --output .runtime/search-performance/types-PHASE-RUN --repeats 3
backend/services/api/.venv/bin/python tools/check_large_text_search_performance.py --output .runtime/search-performance/types-PHASE-RUN-large-text --repeats 3
```

`PHASE-RUN` denotes a new, unique output directory for each invocation; never
overwrite prior results. These are existing command options, not commands to
run while preparing this plan. Extend the standard runner to cover type
administration/list/selector flows where relevant. Run the larger-text runner
whenever scoring or evidence changes, and at the explicit phases below.

Measure complete API response times, preserving each runner's documented
transport and timing boundary. Record browser timings separately. Exclude
fixture/oracle/EXPLAIN work from timed requests as prescribed by the runners.
Do not weaken authorization, cap candidates before ranking, change global
planner settings, or reopen the accepted storage-tuning experiment to pass.

The 14 November compressed-storage exception remains limited to its documented
baseline; retain its failed samples and do not relabel them as passes. It does
not exempt new type workloads or new regressions. Accepted repeated read stages
may remain, but their response-time thresholds are unchanged. If a new gate
fails, fix the phase and retain both failed and corrected reports.

## 3. Phase 0 — contract reconciliation, inventory, and baseline

**Deliverables**

- Inventory resource reads/mutations, database permission paths, batch query
  consumers, cache revalidation, components, explanations, custody, saved-search
  serialization, and UI conventions. Map each to the approved requirements.
- Record current accepted repeated read stages and baseline SQL statement
  counts. Identify precisely where type sets will join existing queries.
- Document storage/API/JSON contracts and upgrade/backfill strategy before
  dependent phases. Preserve existing untyped resources and old saved queries.
- Incorporate the approved resolutions below into those technical contracts.

**Contract points resolved by approval — 18 November 2026**

1. Introduce `aggregations.administer` and `records.administer` with the scope
   in type-specification section 7.1. Grant both by default to `INFO_GOV_MGR`,
   `INFO_GOV_OFFICER`, and `ALL_PRIVS`; delegate to other profiles explicitly.
   Include fresh seeds and populated upgrades without changing unrelated
   grants. No broader substitute privilege or separate field/choice privilege.
2. Type-field missing values sort last in both directions. Single choices sort
   by administrator-defined order; other scalars use native existing ordering.
   Retain subsequent keys/ID tie-breaking and invalidate affected ranked caches
   on choice reordering. Type-specification section 9.1.1 is authoritative.
   Record the technical JSON encoding and backward compatibility without
   reopening these approved semantics.

The future classification-default/subtree, optional-field hiding, and permitted
parent aggregation-type topics in section 10.1 are excluded from these phases.
Custom-entry/conditional companion-field behavior is also not an approved
feature; existing ordinary choices and independent text fields remain supported.

**Regression gate:** Run the current relevant authorization, search/cache,
saved-search, custody, translation/editor, and policy-inventory tests in
disposable databases. Record pre-existing failures separately; do not conceal
them as type-feature regressions or waive new failures.

**Large-dataset gate:** Run both existing performance runners before feature
changes. Capture complete timing/result/plan evidence, including the broadest
queries and all measured pages. Keep the original fixture workload available
for comparisons after typed fixtures are added.

**Exit:** Traceability and integration inventory exist; contract points affecting
the next phase reflect the approved resolutions; baseline artifacts and database
cleanup are recorded. Any newly discovered product gap blocks only dependent work.

## 4. Phase 1 — schema, field model, and validation foundation

**Requirements:** ART-01–08, ART-11; foundation for ART-10, ART-14, ART-17.

**Deliverables**

- Add separate type catalogues, stable type/field/choice identities, translated
  definition text, ordered fields/choices, See/Use role grants, optional
  resource assignments, and scalar value storage according to the phase-0
  contract. Do not introduce translated resource text values.
- Implement shared validation for all seven data types, exact decimals,
  `timestamptz`, required/optional values, Unicode limits, literal defaults,
  choice membership, and safe definition changes. Enforce Use-implies-See.
- Update self-contained `database/schema.sql` and a populated-database upgrade
  migration; retain existing resources as untyped and preserve saved searches.
  Keep seeds separate and SQL portable. Do not expose typed assignment through
  application endpoints before phase 2 enforces it.

**Regression gate:** Fresh-schema/upgrade parity; populated-upgrade preservation;
invalid/wrong-kind/orphan references; false/zero/null/blank distinctions;
Unicode limits; default precedence and clearing; no backfill/reapplication;
required-field changes; choice rename/reorder/deletion/default safeguards;
translation fallback and stable IDs. Test constraints through both validation
and direct database integrity cases where appropriate.

**Large-dataset gate:** Run the standard search gate on the new schema with
existing resources still untyped. Measure upgrade/backfill/index-build duration
and locking/space behavior on a disposable populated large fixture separately
from query latency. Preserve baseline results and query thresholds. The larger-
text gate is required here only if this phase changes FTS storage/scoring/evidence.

**Exit:** Canonical schema and populated upgrades agree; validation is verified;
no existing-query regression; typed data remains unavailable through unsecured
application paths.

## 5. Phase 2 — type administration, resource APIs, and authorization

**Requirements:** ART-09–11, ART-14–18, ART-23; API portions of ART-01–08.

**Deliverables**

- Implement definition/choice/translation/default/role-grant administration
  under the two approved new privileges, including their default profile grants
  and explicit delegation, with bounded list/select APIs.
- Extend creation/update APIs and existing mutation adapters for assignment,
  reassignment, removal, defaults, required fields, atomic value clearing,
  confirmation, version conflicts, and event history. For reassignment, preserve
  the event and both type names. Apply the viewer’s current See independently
  to the values stored on each side in every authorized history projection.
  [Approved scenario and rationale](aggregation-and-record-types.md#historical-values-after-reassignment--approved-19-november-2026)
- Insert the type gate after effective roles across resource reads and
  operations, database functions, batch SQL, components, and explanations.
  Preserve role union, untyped behavior, governance's See/Use bypass with its
  own clearance, remaining gates, and existing lifecycle exceptions.
- Extend the shared query sets and targeted older query paths. Preserve the
  accepted separate count/enrichment/paging stages. Include cached pages,
  lists/counts, relationships, favourites, exports, and retained-resource paths.
- Add type-policy/reassignment custody checks, appropriate transaction/lock
  coordination, audit attribution including type-only bypass, and permission
  freshness. Declare changed route policies and regenerate the inventory.

**Regression gate:** API allow/deny and out-of-scope signed-in callers; empty
grants; See without Use; multiple/expired/inactive roles; governance with and
without sufficient own clearance; privileges/ACL/state still denying access;
source and destination reassignment; component read/mutation separation;
bulk operations; no inherited types; no information leakage. Compare Python,
database, and batch decisions against independent expected outcomes. Test
concurrent policy/reassignment/role changes, revocation during paging, no stale
allow on writes, custody continuity, history, and old untyped clients.

**Large-dataset gate:** Standard runner plus typed visibility fixtures across
all changed read/list flows, including broad queries with no type predicate.
Run the larger-text runner because type visibility affects content eligibility
and evidence. Compare equivalent-access results/scores with phase 0; verify
expected restricted results independently. Inspect no per-resource type query
growth, no repeated type work across branches, and no new lock-wait regressions.
Measure type-policy/reassignment response impact on large affected populations;
do not extend the search-only latency limit to unrelated writes without a
separate requirement.

**Exit:** Every exposed typed operation is protected, consistent and auditable;
query gates and custody tests pass before adding typed search criteria or UI.

## 6. Phase 3 — structured type search, sorting, and saved searches

**Requirements:** ART-13, ART-19, ART-22–23; search portions of ART-03, ART-08,
ART-11, ART-17–18.

**Deliverables**

- Extend canonical query validation/compiler contracts for type/untyped and
  type-field conditions, mixed types within one resource kind, appropriate
  operators, choice IDs, and type-specific sorting using phase-0 decisions.
- Enforce field ownership, type-assigned/unset semantics, stable IDs, existing
  complexity limits, deterministic ties, and submitted-query paging.
- Collect all explicit type references, including nested OR/NOT and sorting,
  and authorize them as a set. Reject forbidden references without pruning.
- Implement approved saved-search disclosure and capabilities: retain shared
  summaries, withhold entire forbidden definitions on list/read/restore, block
  Open/Execute, permit See without Use, recheck current access, and preserve
  independent administrative inspection. Keep old saved definitions compatible.

**Regression gate:** Mixed primary/type Boolean queries; cross-type fields with
identical names; null/untyped/unset and negation; every operator/value boundary;
sorting across populated/unset/other-type resources in both directions; native
zero/false handling; no skip/duplicate paging; injection and invalid IDs;
choice/translation renames; choice-order changes and cache rebuilds; removed definitions.
Test ordinary recipients, owners after revocation, governors, administrators
without execution rights, all disclosure endpoints, nested forbidden references,
restored access, cache identity/version changes, and edited-but-unsubmitted UI
criteria at the API contract level.

**Large-dataset gate:** Standard runner extended with broad and selective typed
conditions/sorts, mixed OR/NOT, mostly-unset fields, many types, broad untyped
queries, denied criteria, generic searches with restricted results, and saved
execution/paging. Include bounded saved-list and selector queries with enough
definitions to verify server pagination. Compare counts/order with an independent
fixture oracle. Run the larger-text gate if this phase changes FTS scoring or
evidence paths; otherwise retain phase-2 evidence with that scope explanation.

**Exit:** Query JSON and saved-search responses satisfy the approved contract;
all applicable query thresholds pass before UI consumes them.

## 7. Phase 4 — text-field search and index freshness

**Requirements:** ART-13 and text-search portions of ART-04, ART-10, ART-17–18,
ART-21, ART-23.

**Deliverables:** Add populated type text values to each resource's own existing
metadata search source for basic/header and full-text search. Exclude numeric,
boolean, date/datetime, and choice labels from keyword indexing. Preserve
existing configurations, score semantics, component evidence, and chunk-local
limitations. Update metadata indexes synchronously after edits and type
changes/removal; define the populated-upgrade/reindex path without stale data.

**Regression gate:** Literal text in multiple scripts; no per-language stored
values; no parent inheritance; phrase/Boolean matching; correct attribution;
no numeric/choice-label keyword matches; stale terms disappear after clearing
or reassignment; new terms appear on the next search. Verify unaffected query
scores and authorized snippets, including retained-resource behavior.

**Large-dataset gate:** Both runners, extended with broad/selective type-text
matches, primary/type/content combinations, denied access, long text values,
and permission/metadata changes between pages. Measure the upgrade/reindex and
freshness cost separately. Retain actual plans, chunk-loop evidence, MAIN/LZ4
storage, and exact scores. Existing broad queries without type criteria remain
mandatory comparisons.

**Exit:** Matching, evidence, and freshness are correct and both applicable
performance workloads meet the established acceptance rules.

## 8. Phase 5 — administration and resource/search UI

**Requirements:** ART-03–08, ART-12, ART-20, ART-22; UI verification of ART-09–10,
ART-14–15, ART-19.

**Deliverables**

- Build aggregation/record type administration using existing Wathiq page,
  table, action, pagination and bounded selector conventions. Include fields,
  required flags, defaults, text lengths, choices/order/translations and See/Use
  grants, with clear governance and administration guidance.
- Reuse the entity translation editor for all supported languages. Maintain
  English keys and Arabic drafts in the same change; preserve curated wording,
  provenance and publication state under the i18n specification. Text values
  remain single literals.
- Add controls to existing creation/edit forms. Retain both existing details
  dialogs and tabs; place type metadata below primary metadata in the first tab.
- Extend the existing Advanced Search builder and sort controls with type-then-
  field selection, not a combined dropdown of all fields. Integrate saved-search
  unavailable summaries without loading forbidden definitions or redesigning
  the builder.

**Regression gate:** Unit/interaction and assembled browser tests for creation,
edit, details, defaults/validation, destructive clearing confirmation, translated
choices, Use-implies-See and policy conflicts. Inspect live English/LTR and
Arabic/RTL plus another configured language for the general translation
convention. Check keyboard/focus, narrow dialogs, empty/error/loading states,
remote selector pagination, repeated navigation, abandoned requests, identity/
language isolation, revocation after rendering, and edited-but-unsubmitted
search paging. Compare with existing screens and approved mockups. Run active-
key, Arabic coverage, placeholder, terminology, ordering, provenance, and hash
checks; generated Arabic remains unpublished for review.

**Large-dataset gate:** Run the standard runner plus the actual new UI's API
request shapes against the large typed fixture. Measure broad search and initial/
cached pages, definition/role/type selectors, and saved summaries; verify no
per-result capability calls or tenant-wide downloads. Collect browser network
counts and rendering timings separately in LTR/RTL. If supporting changes alter
FTS scoring/evidence, also run the larger-text gate; otherwise retain phase-4
evidence for those unchanged paths.

**Exit:** Existing UI conventions are preserved, all supported-language editing
works, server controls remain authoritative, and the UI's actual query flows
meet performance and freshness requirements.

## 9. Phase 6 — integrated upgrade rehearsal and handoff

**Requirements:** Reconcile ART-01–23 and cross-specification obligations.

**Deliverables:** Rehearse both a fresh install and populated upgrade in
disposable databases, including existing untyped resources, old saved searches,
translations/history, and indexes. Document migration locking/space/maintenance,
operator actions and recovery procedure. Keep schemas self-contained, seed
events correctly attributed, and any configuration changes reconciled across
all relevant templates. No deployment or persistent-data migration occurs.

**Regression gate:** Run the integrated authorization, resource lifecycle,
custody, search/cache/saved-search, translation, API inventory, and UI suites.
Exercise end-to-end administration → assignment → query → sharing → revocation
→ restored access, both resource kinds, all data types and governance cases.
Reconcile the ledger with actual code/tests; unresolved approved requirements
prevent completion.

**Large-dataset gate:** Run both complete, extended runners on the final code,
and exercise broad-query comparisons after populated-upgrade rehearsal as well
as fresh-schema setup. This verifies the final combined feature and upgrade
state, not a substitute for earlier gates. Preserve all failures, thresholds,
exact results, source hashes, plans, JIT data and cleanup. Compare with phase 0
and the latest owning phase; explain intentional result changes and measured
response-time impact.

**Exit:** All relevant phase gates pass, exceptions remain explicitly bounded,
and every requirement has evidence. Handoff states implementation status,
remaining administrator translation review, performance impact, migration
instructions and any CI checks not run. Changes remain local and uncommitted
for the user to test and decide what to commit or deploy.

## 10. Phase status

| Phase | Status | Evidence |
| --- | --- | --- |
| 0 — reconciliation/baseline | Baseline collected. The three original regression failures are resolved. Five first pages exceeded three seconds in the larger-text control. | [Original and follow-up results, query counts and cleanup](../docs/verification/aggregation-record-types-phase-0.md) |
| 1 — schema/validation | Passed | [Schema, validation and upgrade](../docs/verification/aggregation-record-types-phase-1.md) |
| 2 — APIs/authorization | Passed | [Authorization, regression and performance evidence](../docs/verification/aggregation-record-types-phase-2.md) |
| 3 — structured/saved search | Passed | [Phase 3 report](../docs/verification/aggregation-record-types-phase-3.md) |
| 4 — text search/freshness | Not started | None |
| 5 — UI | Not started | None |
| 6 — integration/upgrade | Not started | None |
