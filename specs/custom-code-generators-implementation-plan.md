# Custom Code Generators Implementation Plan

**Status:** Phases 0–6 and the approved specification revision 0.6
applicability extension are complete. The full maintained test suites were
rerun; generator regressions were corrected and verified. The two outdated
verification checks found in that run were subsequently repaired without
changing application behavior; all 166 affected-suite tests passed. See the
[check repair report](../docs/verification/outdated-checks-2026-11-28.md).
Earlier slow-search evidence is retained for separately authorized optimization.
All changes remain local and uncommitted; no deployment/publication is authorized.

**Prepared:** 26 November 2026

**Revision:** 0.19

**Updated:** 28 November 2026

**Authority:** [Custom Code Generators](custom-code-generators.md), approved
specification revision 0.6, requirements CG-01–15. The specification was initially
approved on 26 November 2026; its ICU clarification and applicability extension
were approved on 27 November 2026. This plan records implementation and verification.

**UI reference:** The clickable Custom Code Generator dialog reviewed in this
chat. Section 3 records its implementation mapping so the plan remains usable
without the chat. The mockup illustrates the interface; the specification
controls behavior. Its sample settings and fictional data are not installation
defaults, and its local save/history behavior is not a production implementation.

**Progress:** [Requirement traceability](../docs/custom-code-generators-implementation-traceability.md)
and [integration design](../docs/custom-code-generators-integration.md).

## 1 Delivery rules

Implement core dependencies in phase order. Each phase has deliverables,
verification and an exit condition. Once its API and creation dependencies are
verified, independent administration UI implementation may proceed while the
phase 4 measurements are still being collected. This changes delivery sequencing only;
no requirement or acceptance threshold is waived. Intermediate phases are
development checkpoints, not releases of a partially enforced feature. Record
implementation and test evidence before marking a requirement or phase complete.

For each substantive update to this plan or the specification, advance the
affected document's revision and update its date and revision history in the
same change. Reconcile this plan's authority reference when the specification
revision changes.

Keep all changes on the user's existing branch, local and uncommitted. This
plan does not authorize branches, worktrees, commits, pushes or deployment.
Preserve existing changes and follow the repository's AGENTS.md instructions.

Change search code only where custom code generation requires it, principally
attached-field natural ordering and its cursor/cache semantics. Do not use
variable benchmark timings to expand this work into search optimization.
The user identified host contention as the cause of the slower runs and
directed that unrelated optimization be handled in a separate session.
Keep the timing evidence without claiming a final performance pass.
Record and report any search response over three seconds for future dedicated
optimization work; do not respond to it by optimizing search during this feature.

Database-backed checks must use a new, uniquely named disposable database for
each run, initialized from the canonical schema or the upgrade path under test.
Point the entire process and its fixtures at that database. Drop it after the
run, including failures, and report creation or cleanup failures. Never run a
suite against the persistent development database.

Maintain `docs/custom-code-generators-implementation-traceability.md` from
phase 0 onward. For every CG requirement, record its owning phase, code paths,
tests, results and remaining work. Keep phase reports under
`docs/verification/`; put large runtime artifacts in gitignored `.runtime/`
directories. Do not substitute planned tests for executed verification.

Use the existing `app.settings.manage` privilege for generator administration.
Declare access policies where routes are defined and test allowed, denied and
signed-in callers without access to the relevant resource or type. Administration
does not grant resource access. Preserve existing type See/Use, role, clearance,
ACL, ownership and lifecycle rules.

User-visible text and Arabic drafts belong in the same change that introduces
the text, including in earlier phases when applicable. Follow
[internationalization sections 7.5 and 7.8](internationalization-and-user-preferences.md#75-translation-keys-during-active-webui-development),
preserve curated translations by message key, maintain canonical ordering and
run the governed artifact checks. Translation is not deferred to a final cleanup.

## 2 Scope and binding rules

Carry these decisions through every phase:

- Each generator has a required, nonblank administrator-defined name, shown in
  its dialog, listing and audit history. Use the stable ID for references;
  renaming preserves bindings, counters and stored codes and follows the
  existing configuration-edit reason and audit rules.
- Only editable primary Text metadata and type-specific Text fields qualify.
- Generate only for future creations and final draft commits. Existing items,
  ordinary edits and later type assignments are not backfilled.
- Drafts may be created, saved, reopened and updated without a record number.
  Draft saves do not allocate one; required-field checks apply to final creation.
- Preserve manual values and the existing static-default rules. Once a number
  is placed in the actual number field, final creation uses that exact number or
  stops with a conflict/review message. Never silently choose a different code.
- **Chosen approach, approved 26 November 2026:** optimistic conflict handling,
  as recorded with its advantages/disadvantages in CG-10. Suggestions remain
  unreserved. Do not implement reservation storage, expiry/release workflows or
  an administrator switch between these approaches in this version.
- Support generator-wide, parent, classification and owning-unit counters, with
  explicit Never, Yearly or Monthly reset. Required placeholders are validated;
  adding a placeholder alone never enables a scope or reset.
- Optional zero-padding width sets a minimum serial width, not a maximum.
  Longer serials remain valid if the complete output fits the maximum code
  length. Store one Text value and use `erms_code_natural` for the specified
  ordering of fields with attached generators.
- Skip occupied candidates only when obtaining a new automatic number for a
  blank field or a fresh recommendation. Never skip past or replace an already
  chosen number during final creation. Authorized manual creation or editing
  may reuse a number freed by deletion. Keep counter state; introduce no
  permanent historical-number reservation store.
- Generator configuration creation is audited without requiring a reason;
  preserve an optional reason. Configuration edits and explicit next-number
  adjustments require a nonblank reason.
- Type-specific field-value uniqueness, fiscal-year resets, check digits and
  shared counters across different fields remain deferred.

### Overlap rules

Two enabled generators overlap if both could fill the same field on the same
item. Compare the resource kind, stable target field key/ID and types covered.
The name, pattern, counter scope and reset choice do not decide which generator
applies. Counting separately by department does not restrict a generator to
one department.

For the same primary field on the same resource kind:

| First enabled generator | Second enabled generator | Result |
| --- | --- | --- |
| All items | All items | Reject: both apply to the same items. |
| All items | Untyped items only | Reject: All items includes untyped items. |
| All items | Contract | Reject: All items includes Contract. |
| Untyped items only | Untyped items only | Reject: both apply to untyped items. |
| Untyped items only | Contract | Allow: the covered items differ. |
| Contract | Contract | Reject: both apply to Contract items. |
| Contract | Employee file | Allow: the covered types differ. |

Primary metadata uses **Applies to** with All items (default), Untyped items
only, or One selected type. The latter requires the bounded type picker.
Replace the old checkbox and its all-types hint. Type-specific fields keep their
defining type and cannot use All items or Untyped items only. Show applicability
in listings and immutable audit rendering. All items is not an override/fallback.
Different resource kinds or target fields do not overlap. For a type-specific
Text field, use its stable field ID and defining type; matching display names
in different types do not make them the same field.

Disabled definitions may coexist, but enabling one or changing its target must
run the checks again. Different generators that cover different types can still
produce the same complete number; pattern warnings and CG-07's occupied-number
handling address that separate problem.

Enforce these rules in the database as well as the API. Serialize configuration
writes for the same logical resource-kind/primary-field target before checking
and saving, including when that target has no existing generator row. Use
transaction-scoped advisory locks or an equivalent database guard, with old/new
target locks acquired in a consistent order when a binding moves. Partial
unique indexes reject identical enabled bindings; a native exclusion constraint
rejects overlapping type populations, including All items versus untyped-only or a selected type,
even when a transaction has an older snapshot. Exercise direct database writes,
enabling, retargeting and simultaneous first saves. This configuration guard
must not become an exclusive lock on every counter allocation.
See [PostgreSQL advisory locks](https://www.postgresql.org/docs/18/explicit-locking.html#ADVISORY-LOCKS)
and [exclusion constraints](https://www.postgresql.org/docs/18/ddl-constraints.html#DDL-CONSTRAINTS-EXCLUSION).

### Revision 0.6 applicability extension

**Completed:** 28 November 2026. The verification report records the complete
2,300-case API sweep, corrected failures and follow-ups, one additional real-PDF
case, all six populated-upgrade contexts, 2,567 WebUI tests and the remaining
maintained suites. All 39 explicitly observed disposable databases were verified
absent. The two outdated verification checks from that run are now repaired,
as recorded in the follow-up report; CG requirement coverage is unchanged.

- Phase 1: add explicit `applies_to` (`all`, `untyped`, `type`) to the canonical
  schema and a populated upgrade from schema 126. Type ID is required only for
  `type`; type-specific fields require `type`. Represent untyped and selected
  types as disjoint populations in the native overlap constraint; preserve
  target-write serialization and enabled uniqueness. Keep old meanings,
  counters, configuration versions and history intact during backfill.
- Phase 2: accept/validate the three modes, list/read them, audit configuration
  changes and preserve reason/version/authorization checks. Legacy bodies
  without the new parameter infer `type` from a type ID, otherwise `all`.
  Retargeting or enabling must check the complete overlap matrix concurrently.
- Phase 3: apply the same matching predicate to locked creation bindings,
  recommendations and context-authorized generation hints. Cover records, root
  and child aggregations, final draft commits and direct file drops; ordinary
  updates/type reassignment remain outside generation.
- Phase 5: replace the checkbox with the three-option selector, retain the
  recent white, compact, scrollable dialog layout and 150px height increase,
  conditionally show the type picker, and keep type-specific fields bound to
  their defining type. Add English/Arabic labels and preserve retired-key
  history and all other curated translation wording/provenance.
- Phase 6: test all allowed/rejected shapes and overlaps through SQL/API,
  simultaneous saves, populated upgrades, audit snapshots (including older
  snapshots), every creation/recommendation/hint path and English/Arabic UI.
  Rerun the complete repository test suites with fresh disposable databases for
  database-backed checks. Record every result, cleanup and any above-target
  search samples; do not make unrelated search optimizations.

## 3 Mockup and current implementation mapping

| Mockup area | Production behavior |
| --- | --- |
| Generator name (added by the specification) | Required nonblank Name input in the dialog; show the name beside its target in the listing and preserve it in audit snapshots. This control is required even though the current mockup predates it. |
| Target field | Records/aggregations, primary/type-specific metadata, applicable type and Text field. Persist stable IDs/keys; use bounded selectors rather than downloading full catalogues. |
| Settings | Enabled state; editable pattern and placeholder insertion; scope; reset; start; increment; optional padding width; maximum complete-code length. Show clear validation and the current example/length. |
| Preview and simulator | One response containing five complete values with dates, scopes and reset markers. Support same-context, month/year boundaries, two scopes and combined scope/period scenarios using fictional data and isolated counters. |
| Sample values | Date, parent, classification/scheme, owning unit and Create for role examples. These are simulation inputs, not permission to read arbitrary live resources. |
| Occupied-number example | Demonstrate skipping for unique record/aggregation numbers without adding uniqueness to ordinary Text fields. |
| Create/edit actions | Clear create/edit mode; optional creation reason, required edit reason; validation, version conflicts, Cancel and saved-state refresh. |
| Change history | Existing immutable audit evidence, including stable generator ID, name at event time, actor, time, before/after values and applicable reason; show old/new names for renames and preserve earlier snapshots. Use the existing authorized history presentation. |
| Continuing an existing series | CG-14 remains required even though it is not drawn in the mockup. Provide a separate, reasoned next-number action using the existing dialog conventions. |

Rebuild the mockup with standard NiceGUI components and established Wathiq
patterns. Do not embed its HTML/JavaScript as the production implementation or
make its browser simulation an independent source of numbering rules. The
production preview and allocator must share the authoritative parsing,
formatting and sequence rules.

| Current area | Integration work to account for |
| --- | --- |
| `backend/services/api/main.py`, `schemas.py` | Direct root/child aggregation creation, direct record creation, draft creation/update/final commit, message capture and separate/combined file-drop creation. Draft storage already permits an omitted/null number; preserve that. The missing-number check is at final Create record, where a blank field may first be generated. |
| `backend/services/api/typed_metadata.py`, `resource_types.py` | Type validation/defaults, Text field identity and length constraints, required-value checks and protection against changing/deleting an attached field. |
| `backend/services/api/number_suggestions.py` | Dropping files to create records currently assigns numbers using `next_numbers`, the old built-in rules. Use the configured generator when one applies and retain the old behavior otherwise. |
| `frontend/webui/resource_number_controls.py`, `entity_editor.py`, `record_capture.py`, `api_client.py` | Keep recommendation controls. Preserve the exact chosen suggestion and whether it is automatic or manual. At final creation use it unchanged or report a conflict with the draft/files intact. Retain submission identity across retries and ignore outdated responses. |
| `frontend/webui/application_settings.py`, `application_settings_controller.py` | Enter through Administration → Settings, preserve view lifetime and unsaved-state behavior, and add the generator collection without duplicating scalar settings persistence. |
| `backend/services/api/search.py`, `browse.py`, type-value storage | Natural ordering, matching keyset cursor comparisons, saved searches, ranked caches, pagination and measured indexes. |
| `database/schema.sql`, migrations and existing history functions | Shared generator/counter/request tables, constraints, transactional allocation, audit enforcement and populated upgrades. |

## 4 Phase 0 Contract mapping and baseline

**Dependencies:** None. **Coverage:** All CG requirements and the mockup.

**Deliverables**

- Create the traceability ledger and inventory every supported creation,
  recommendation, type-field edit, code-sort and history path. Include message
  capture, draft placement correction and atomic file-drop batches.
- Record the technical request/response contracts: stable target identity,
  the exact chosen number and automatic/manual origin, submission-key transport
  for JSON/multipart/draft requests, exact integer encoding, error codes,
  versions and preview context. Document
  client compatibility and any client upgrade requirements. A new key on every
  retry is not retry protection.
- Define how the server validates an accepted recommendation without trusting a
  browser-supplied serial to advance a counter arbitrarily. Preserve the exact
  chosen code, or return a conflict/review result. Distinguish a confirmed failed
  attempt with corrected inputs from a retry whose outcome is still unknown.
- Map generation relative to authorization, owner/Create for resolution, static
  defaults, required-field checks, upload readiness and final commit. Record how
  a completed retry is found after successful commit has deleted its draft.
- Define the lock order and compare it with existing parent, resource, type,
  authorization and content locks. Record representative concurrency workloads
  and baseline statement counts, API timings and lock waits.
- Escalate any newly discovered product departure before dependent work;
  ordinary technical choices within the specification do not require repeated
  approval.

**Verification:** Run relevant existing numbering, creation/draft/file-drop,
type, settings/audit, policy-inventory and search regressions in disposable
databases. Capture the existing standard and larger-text performance baselines
under section 11. Record pre-existing failures separately.

**Exit:** Every requirement has an implementation owner and planned test;
the creation/locking/compatibility inventory and baseline evidence exist.
No implementation or performance pass is claimed from this plan alone.

## 5 Phase 1 Schema and allocation foundation

**Depends on:** Phase 0. **Requirements:** CG-01–07, CG-12–15 foundations.

**Deliverables**

- Add `code_generators`, `code_generator_counters` and
  `resource_creation_requests` to the self-contained canonical schema and a
  populated upgrade migration. Preserve existing resources and configuration;
  introduce no enabled business generator by default. Keep seeds separate.
- Store the required generator name on `code_generators`; reject missing,
  empty and whitespace-only names at the database and API boundaries. References
  and counter keys continue to use the stable ID, independently of the name.
- Enforce eligible targets, stable references, nonoverlapping enabled bindings,
  valid scope/reset/pattern combinations, numeric constraints and full-code
  length. Apply section 2's overlap rules at the database boundary, including
  All items versus untyped-only/a selected type and enabled type-field bindings by stable ID.
  Protect attached type fields against incompatible edits/deletion. Keep the
  generator maximum within the target field's maximum length, checking edits
  to either configuration or field constraints.
- Implement the shared pattern parser/renderer with exact whole-number
  arithmetic, escaped braces, every placeholder, one generation instant and
  the validated application working timezone. Preserve values beyond the
  browser's safe integer range without float conversion.
- Implement the unique counter identity from CG-13, atomic first allocation,
  forward-only advancement, retained state and explicit next-number adjustments.
  Skip occupied candidates for blank fields or fresh recommendations; for an
  accepted automatic recommendation, allocate that exact value or return a
  conflict/review result with all allocation changes rolled back. Manual entries
  do not advance counters. Recover only from the intended
  number uniqueness conflict, using valid database conflict/savepoint handling;
  do not retry unrelated integrity errors or leave the transaction aborted.
  Do not allocate through `nextval`.
- Add database-boundary audit enforcement, create/edit reason distinctions and
  optimistic versions. Include the stable ID and name at event time; record
  old/new names on rename and preserve earlier audit snapshots. Preserve history
  without creating an issued-code reservation table. Add the durable, unique
  submission identity needed by CG-15.

**Verification:** Fresh schema/upgrade parity and populated-data preservation;
direct constraint/audit checks; missing/empty/whitespace-only name rejection;
rename identity/counter/code preservation; complete placeholder and Unicode
length cases; start/increment, padding growth and Never/Yearly/Monthly buckets;
all four scopes;
concurrent first use and same/different counter allocation; rollback of all
fields/counters on any failure; simultaneous All items/untyped/selected-type first saves,
enable/retarget and field-edit races; exact chosen-number conflicts without
substitution; generator/target maximum-length edits; no counter loss after
deletion, disablement or configuration changes. Measure upgrade locking/space
and counter contention in disposable fixtures.

**Exit:** Storage, renderer, allocator and audit invariants are verified before
application creation paths consume them. No unrelated schema/search regression.

## 6 Phase 2 Administration APIs and simulation

**Depends on:** Phase 1. **Requirements:** CG-01–05, CG-09, CG-11–14.

**Deliverables**

- Provide bounded generator listing, target discovery and configuration
  create/read/edit/binding operations under `app.settings.manage`. Accept and
  return the required name and include it beside the target in listing results.
  Expose only definition information needed to configure generators; do not
  fetch business resource values or grant type-definition editing privileges
  implicitly.
- Implement optional creation reasons, required nonblank edit reasons, expected
  versions, current committed configuration reads and existing audit access.
  Apply the same edit rules to renaming; keep references and counters unchanged.
  Configuration and audit writes succeed or fail together.
- Provide an administrator-only preview using unsaved configuration and
  fictional context. Return five values per selected scenario with full-code
  validation, dates, scopes and reset explanations. Use isolated sample
  counters and no system-clock, configuration or live-counter writes.
- Provide the advance-only next-number action for one scope/period, with the
  current version, required reason and old/new next-number audit evidence.
- Declare route policies, regenerate the inventory and add localized errors
  without adding a new privilege, environment setting or configuration cache.

**Verification:** Allowed and denied API calls, insufficient administration
privileges, invalid/foreign targets and stale versions; creation with no reason
or an optional reason; required-name validation; listing/read name delivery;
renaming with an edit reason, unchanged bindings/counters/codes and retained
old/new audit names; blank/whitespace edit reasons; audit-write rollback;
exact five-value scenarios from the spec, including leap/month/year boundaries
and owning-unit scope; zero preview writes; forward adjustment races and refusal
to move backward. Inspect bounded listing/selector query plans and timings.

**Exit:** Configuration, preview and counter-management APIs are correct,
authorized and auditable. Actual allocation still occurs only on final creation.

## 7 Phase 3 Creation, recommendations and safe retries

**Depends on:** Phase 2. **Requirements:** CG-03–07, CG-10, CG-13–15.

**Deliverables**

- Integrate one generation path into root/child aggregation creation, direct
  record creation, final draft commits, message capture, placement-correction
  creation and separate/combined file-drop batches. Preserve existing route
  policies and digital-content transaction guarantees.
- Resolve the authorized parent, effective classification/scheme, inherited
  owner and existing Create for role before generation. Apply static-default
  and manual-entry rules, then fill eligible generated values before final
  required-field validation. Do not weaken requests with no applicable generator.
- Preserve numberless draft creation, saving, reopening and updates. Draft
  saves never call the allocator. For final creation, fill a blank number before
  the final required-field check when a generator applies. Adjust direct-create
  request validation where necessary. Keep edits and later type assignment out
  of automatic generation. Commit generated fields, indexes, components and
  counter changes atomically.
- Retain existing number recommendations and conflict suggestions, using the
  applicable generator or legacy fallback. Preserve the exact suggestion placed
  in the number field and its automatic origin; an edit becomes manual. Final
  creation uses that exact value or stops with a duplicate/stale-number result.
  Do not silently replace it after a collision or context/date/configuration/
  counter change. Keep the draft and files intact, and let the user explicitly
  choose a new number and correct any document containing the old one.
- For direct file-drop creation without a previously chosen number, generate
  one available number per record, skipping occupied candidates. A combined
  record gets one number and a separate-record batch gets one per record. Keep
  legacy numbering only when no generator applies. Drops that open drafts keep
  the review flow and exact-number conflict rules; do not turn them into direct
  creation. Suggestions and administration previews remain unreserved.
- Preserve one submission key across timeouts/retries. Find completed draft
  requests before requiring the now-deleted draft; recheck caller access before
  returning results. Different inputs with a completed key conflict. Failed
  transactions remain retryable; successful retries add no resources, codes,
  components or duplicate creation events.
- Keep counter transactions short and lock multiple counters consistently.
  Complete upload readiness/staging before holding allocation locks; never wait
  for network upload or user input while holding a counter. Preserve atomic
  batch behavior and existing content ownership/cleanup guarantees.

**Verification:** Exercise every creation adapter through the API, typed/untyped
and manual/generated combinations, multiple generated fields, defaults and
explicit blanks, role/owner changes, missing context, current type Use/See and
resource denials. Test many occupied values, concurrent manual/automatic
collisions, authorized manual reuse after deletion, retained counter progress,
mid-transaction failures, identical concurrent submissions, lost responses,
changed-input retries, deleted-result retries and rollback of a failed batch.
Exercise every creation-path and conflict-table case in CG-10: numberless draft
saves; exact accepted code on success; two users selecting the same number;
copied-document conflict with files preserved; explicit new-suggestion retry;
context/date/counter/configuration changes; late responses; direct versus
draft-opening drops; and a lost-response replay returning the original number.
Compare unconfigured creation and recommendation behavior with phase 0.

**Exit:** No supported creation path bypasses configuration, consumes a preview
serial or duplicates creation on a retry. Existing metadata-update behavior and
resource authorization remain intact.

## 8 Phase 4 Natural ordering and search performance

**Depends on:** Phase 3. **Requirement:** CG-08; CG-02 binding changes.

**Deliverables**

- Apply the existing deterministic `erms_code_natural` collation to primary
  and type-specific Text fields with attached generators, across generated,
  manual and legacy values. Other fields retain their current sorting. Store
  one Text value per field, with no second padded/unpadded copy or sort column.
  Update sort expressions and keyset cursor comparisons together. Preserve
  requested secondary keys, stable IDs and missing-value placement.
- Cover every affected collection, browse, selector, Advanced Search/saved
  execution and ranked-page path. Invalidate affected ranked lists when binding
  changes alter ordering, using the existing tab/session cache contract.
- Retain matching/relevance predicates, uniqueness constraints, trigram/FTS and
  prefix-search support. Add or change matching-collation indexes only after
  actual plan evidence; include type-field expressions and filter prefixes
  appropriate to each query. Account for write/storage costs and supported
  code lengths; an index must not make valid long-code writes fail.
- Extend the repeatable performance gate with the changed sorts, mixed
  padding/manual values, ties, broad/empty/selective/denied criteria and page
  boundaries. Preserve complete authorized results and submitted filters.

**Verification:** Numeric runs in multiple code segments, leading zeros,
deterministic ties, both directions and missing values; paging with edited but
unsubmitted controls; all matching list rows reachable; cache replacement and
permission changes between pages. Run section 11's standard gate and inspect
actual plans. Run the larger-text gate if scoring/evidence is affected; retain
regression coverage proving ordinary matching and relevance are unchanged.
Verify the approved ICU boundary: numeric ordering through 254 significant
digits, ignored leading zeroes and native ICU behavior for longer runs. Do not
turn that collation limit into a generator validation cap or another setting.

**Exit:** Affected sorts are correct and deterministic, and the final
implementation has measured performance evidence. Under the user's
27 November close-out instruction, retain and report every response over
three seconds for separate optimization work; those numerical failures do not
block this feature's completion and must not be described as passes.
A collation definition or index alone is not verification.

## 9 Phase 5 NiceGUI dialog and creation controls

**Depends on:** Verified phases 2–3 APIs/creation and implemented phase 4 ordering.
Phase 4 correctness and recorded performance evidence remain required for
feature close-out; slow timings follow the separate-work rule above.
**Requirements:** CG-01–12, CG-14–15 UI coverage.

**Deliverables**

- Implement the three mockup tabs and the section-3 controls through standard
  NiceGUI components and existing Wathiq settings/dialog/history patterns.
  Add the required Name field and display names beside targets in the listing;
  include names in history even though the current mockup predates that input.
  Provide clear empty, loading, invalid, stale-version and error states.
- Keep create/edit mode explicit. Creation needs no reason, edits require one,
  and both remain audited. Add the separate existing-series adjustment action;
  do not hide it because the mockup omitted it.
- Use bounded type/field/context selectors with retained selections and direct
  selected-ID retrieval. Generator collections use real server pagination;
  draft filters remain separate from submitted filters where Search/Apply exists.
- Use one preview request for all five values; abandon stale responses when
  settings/context changes or the dialog closes. Refresh valid previews after
  edits, and prevent old valid results appearing current after invalid input.
  Keep all numbering decisions on the server and all simulations non-consuming.
- Extend existing resource editors, capture dialogs and conflict controls to
  send the exact chosen number, complete context and automatic/manual origin,
  retaining the logical submission key across retries. Show conflicts without
  changing the field or dropping staged files. Applying a replacement number
  requires the user's explicit choice. Administration simulation refreshes must
  not be reused to silently refresh a chosen record number.
- Add English keys and Arabic drafts in the same change. Merge the canonical
  Arabic artifact by message key, preserve curated wording/provenance, remove
  retired active keys and align all maintained artifacts with sorted English.
  For authorized local demo catalogue upkeep, follow the explicit Arabic
  `--missing-only` seed workflow; never use that database for test suites.

**Verification:** Compare rendered controls/tables with existing Wathiq screens
in a live browser. Test English/LTR and Arabic/RTL, narrow layouts, keyboard
operation, placeholder insertion, all scope/reset simulations, exact integers,
full-code errors, required-name validation, listing names, renaming,
create/edit reason behavior and historical name snapshots. Exercise repeated
navigation, late preview/recommendation responses, Cancel, failed saves, mutation
freshness and request counts. Pass catalogue coverage, ordering, placeholder,
blank, terminology, stale-key, provenance and artifact-hash checks.

**Exit:** All specified UI behaviors work against the real API, including
creation adapters, with browser evidence and complete translation artifacts.
Mockup-only local state or a passing unit test does not close a UI requirement.

## 10 Phase 6 Integrated verification and handoff

**Depends on:** Phases 0–5. **Coverage:** CG-01–15 in full.

**Deliverables and verification**

- Run the focused and relevant broader API/database/WebUI suites against fresh
  disposable schemas and populated upgrade fixtures. Verify canonical/migration
  parity, current values, existing defaults, settings, permissions, histories,
  saved searches and unconfigured numbering behavior.
- Repeat the standard and larger-text measurements with final code. Retain all timings,
  exact results/ranks, plans, JIT details, source hashes and cleanup. Exercise
  realistic counter concentration, concurrent configurations/adjustments and
  safe retries alongside ordinary creation and search; report lock waits and
  complete request timings separately from search measurements. Record and
  report any search response over three seconds for separate optimization;
  do not change search implementation to make this feature's close-out pass.
- Check policy-inventory generation, curated translation preservation and
  catalogue artifacts. Close every traceability row with implementation and
  verification links; retain failures and remaining review items honestly.
- Write upgrade/operator guidance: existing resources are preserved; no generator
  is silently enabled; enter a required generator name, configure
  target/pattern/scope/reset/length, preview, and
  advance the appropriate counter when continuing an existing series. Explain
  optional creation versus required edit reasons, manual deletion reuse and
  forward-only automatic numbering. Explain that unreserved suggestions can
  conflict: final creation never silently changes a chosen number, and the user
  may need to correct documents before retrying with a replacement. Document
  any required API-client changes.
- Explain safe disablement/recovery without dropping or rewinding counter state.
  Report migration locking, storage/index maintenance and manual operator actions.
  No service deployment, persistent database upgrade or Git publication is part
  of this plan's execution authorization.

**Exit:** Every CG requirement has passing implementation/correctness evidence,
the applicable browser/upgrade checks pass, and final performance measurements
are recorded. Report failed search timings for separate optimization according
to the user's 27 November direction, without claiming a strict latency pass.
Report translation review needs and any CI verification not run locally. Leave
the implementation local and uncommitted for the user's testing and commit
decision. This closes implementation, not deployment or publication.

## 11 Performance and evidence rules

Follow [the search contract](../docs/search-performance.md),
[optimization lessons](../docs/postgresql-search-optimization-lessons.md),
[accepted benchmark history](../docs/search-performance-benchmarks.md),
[WebUI performance contract](../docs/webui-performance.md) and
[WebUI design language](../docs/webui-design-language.md).

Use the existing deterministic fixture exceeding 50,000 aggregations and
150,000 records, extended for generators and typed Text values. Preserve the
1,000-result search cap and measure every search response against the unchanged
three-second threshold. Retain each sample, including failures, over at least
three repetitions and subsequent pages. List pagination remains complete where
its contract has no total-result cap.

Measure actual plans, authorized counts, exact IDs/order/scores, query criteria,
statement counts, database/host settings, JIT availability and compilation time,
storage policy, source/fixture hashes and cleanup. Preserve search-scoped JIT
and pooled-connection restoration. Do not change server-wide planner settings,
weaken permissions or cut candidates before ranking to meet a timing target.
The accepted November compressed-storage exception remains limited to its
documented baseline and does not excuse new regressions.
The user's 27 November instruction governs this feature's close-out: timings
over three seconds are recorded and reported for future dedicated optimization,
without expanding feature work into search tuning. This changes the completion
decision, not the threshold, results or historical failure records.

Separately measure generator lookup, preview, counter allocation, occupied-value
skipping, request replay and adjustments under independent and concentrated
counter workloads. Include lock waits and maintenance effects. Indexes do not
remove contention on one serial counter, and a passing search benchmark does
not establish a generator-throughput guarantee.

Use unique output directories for every run. The following are implementation
gate commands, not commands executed while preparing this plan; extend their
cases so the generator flows themselves are measured:

```sh
backend/services/api/.venv/bin/python tools/check_search_performance.py --resource-types --type-text --code-generators --repeats 3 --output .runtime/search-performance/code-generators-PHASE-RUN
backend/services/api/.venv/bin/python tools/check_large_text_search_performance.py --resource-types --type-text --repeats 3 --output .runtime/search-performance/code-generators-PHASE-RUN-large-text
PYTHONPATH=. backend/services/api/.venv/bin/python tools/generate_policy_inventory.py
```

If an implementation change later touches environment templates, apply the
repository's complete template reconciliation and consistency checks in that
same change. No new environment variable is planned for this database-managed
feature.

## 12 Requirement coverage

| Requirement | Main implementation phases | Final evidence |
| --- | --- | --- |
| CG-01 Text-only targets | 1, 2, 5 | Rejected non-Text/system targets; eligible UI/API bindings |
| CG-02 Configuration and bindings | 1, 2, 5 | Required-name validation; renaming preserves IDs/bindings/counters/codes; overlap races and current settings |
| CG-03 Pattern/context | 1–3, 5 | Every token/escape, owner/Create for, missing context and timezone |
| CG-04 Counters and resets | 1–3, 5 | Exact sequences; four scopes; Never/Yearly/Monthly boundaries |
| CG-05 Formatting and full length | 1–3, 5 | Optional padding, growth, Unicode limits and atomic rejection |
| CG-06 Future creation/manual/default rules | 3, 5 | Numberless draft saves; final creation only; manual/default rules; no edit/backfill generation |
| CG-07 Atomic allocation and reuse | 1, 3, 6 | Rollback, collisions, retained progress and authorized manual reuse |
| CG-08 Natural ordering | 4, 6 | Correct SQL/cursors/cache behavior and measured performance |
| CG-09 Administration | 2, 5 | Required Name input and listing names; privilege enforcement, bounded settings UI and freshness |
| CG-10 Recommendations and delivery | 3, 5 | Exact chosen number or conflict, preserved draft/files, direct/draft file-drop paths and all documented scenarios |
| CG-11 Five-value simulations | 2, 5 | Exact scenarios, isolated counters and no preview writes |
| CG-12 Configuration audit | 1, 2, 5 | Optional create reason, required edit/rename reason, stable ID and historical name snapshots, immutable atomic history |
| CG-13 Shared database design | 1, 3, 4, 6 | Constraints, upgrades, independent progress, locks and indexes |
| CG-14 Forward adjustments | 1, 2, 5 | Reasoned versioned advance, unchanged other counters and audit |
| CG-15 Safe retries | 1, 3, 5, 6 | One result per logical request, authorized replay and atomic batches |

Phase 6 closes all rows, including required naming and rename/audit behavior.

## 13 Revision history

Earlier plan edits were unnumbered. Revision 0.2 is the first numbered plan
revision and is aligned with specification revision 0.2.

| Revision | Date | Changes |
| --- | --- | --- |
| Unnumbered | 26 November 2026 | Initial phased plan and subsequent discussion-driven clarifications. |
| 0.2 | 26 November 2026 | Consolidated phases 0–6, all CG-01–15 mappings, mockup/integration mapping, database-enforced overlap rules, numberless draft saves, separate direct/drop-to-draft behavior and the approved optimistic conflict approach. Added explicit revision maintenance. Generator naming remains a proposed addition. |
| 0.3 | 26 November 2026 | Reconciled the plan with approved specification revision 0.3 and checked all CG-01–15 phase/evidence mappings. Clarified padding versus complete-code length, new-candidate skipping versus exact chosen numbers, generator configuration reason rules, target length compatibility and sorting only for fields with attached generators. Kept naming outside approved scope and removed it as a phase dependency. No implementation phases have started. |
| 0.4 | 26 November 2026 | Aligned with approved specification revision 0.4: required generator names are included in schema/API validation, listing, dialog and audit work in phases 1, 2 and 5. Added rename stability and historical-name verification and removed the separate-proposal exclusion. Recorded the additional required Name control where the current mockup predates it. No implementation phases have started. |
| 0.5 | 26 November 2026 | Completed phase 0 under the user's implementation authorization: requirement traceability, integration/transaction/transport design, 189 passing functional checks and creation query-count/lock measurements. Both full search baselines completed correctness checks but failed latency gates on 12 existing requests; retained all evidence and dropped all five disposable databases. The approved specification remains revision 0.4; application implementation has not started. |
| 0.6 | 26 November 2026 | Started phase 1 with the shared exact-number pattern, context, formatting, counter-key and simulation engine and focused verification. Database schema/allocation and remaining feature work are still in progress; the approved specification remains revision 0.4. |
| 0.7 | 26 November 2026 | Added the shared schema, database audit/overlap guards, transactional allocation, forward adjustments and completed-request primitives. Documented the native exclusion constraint needed for overlapping populations under older snapshots. Focused checks pass; existing creation/type regressions remain in progress. |
| 0.8 | 26 November 2026 | Completed phase 1 with renderer/schema checks, database and allocation races, populated upgrade rollback/locking/space evidence, and 96 passing existing creation/type/numbering regressions. All disposable databases were dropped. Started phase 2 administration APIs; full feature acceptance remains pending. |
| 0.9 | 26 November 2026 | Completed administration APIs, access/version/audit/preview checks and measured server pagination. Added nine English errors and Arabic drafts while preserving curated entries; recorded an unchanged pre-existing glossary failure. Corrected and verified wide-padding occupancy detection. Started phase 3 creation integration; later feature gates remain required. |
| 0.10 | 26 November 2026 | Connected final creation, numberless drafts, exact recommendations, capture and direct file drops to transactional generation and completed-request replay. Recorded focused checks, populated-upgrade and permanent-destruction receipt cleanup evidence. Phase 3 remains open for dialog provenance, retry controls and remaining concurrency/access checks; phases 4–6 remain pending. |
| 0.11 | 27 November 2026 | Completed phase 3 creation/retry integration, scoped hints, dialog provenance, retained files, simultaneous/manual races, stale contexts, no-backfill checks and occupied upgrades. Repaired the existing closed-placement creation guard using the security specification's existing authority. Retained the 170-pass/one-fixture-failure integrated result and verified the corrected affected cases. Started phase 4 natural ordering; administration UI and release gates remain open. |
| 0.12 | 27 November 2026 | Aligned with approved specification revision 0.5 after the user accepted ICU's 254-significant-digit numeric-run limit. Added boundary and leading-zero verification while retaining the existing collation, optional padding and no extra digit cap. Phase 4 sorting/cache integration is in progress; performance and later-phase gates remain open. |
| 0.13 | 27 November 2026 | Recorded implemented natural ordering, page-only display enrichment and bounded ordinal sorting, with strict latency failures retained. Began independent settings UI work against verified APIs while phase 4 performance remains open; no product requirement, phase-completion claim or acceptance threshold changes. Added the generator matrix to the full standard gate command. The user-approved one-line Arabic correction passes contextual terminology/coverage checks. |
| 0.14 | 27 November 2026 | Completed administration, simulator, counter, history, translation and real-API browser verification, including exact conflict recovery with corrected document bytes. Integrated creation/load tests fixed a parent-row lock-upgrade deadlock; final API, canonical/archive, populated-upgrade and catalogue checks passed. Recorded failed performance run 7 and started a controlled projection comparison; phases 4/6 remain open. No specification requirement or latency threshold changed. |
| 0.15 | 27 November 2026 | Removed unrelated generic-search join/top-N rewrites, browse enrichment/count rewrites and added JIT guards at the user's direction. Retained required generator/natural-ordering integration, historical measurements and the existing search execution guards. Recorded the user's host-contention assessment and instruction to record/report search samples over three seconds for separate dedicated optimization, without tuning search during this feature. Phases 4/6 remain open; no final latency pass is claimed. |
| 0.16 | 27 November 2026 | Completed phases 4/6 and reconciled their exit criteria with the user's explicit direction to record/report slow searches for separate optimization. Final ordinary, complete generator and larger-text measurements passed correctness for 3,198 API responses; 190 child-list/selector timings exceeded three seconds and remain recorded failures. Corrected only the benchmark's missing synthetic Add record grant and isolated-workload forwarding. Source/baseline, policy, configuration and translation checks passed; requirement traceability and operator guidance are complete. No product requirement or search implementation changed during close-out. |
| 0.17 | 27 November 2026 | Aligned with approved specification revision 0.6 and reopened implementation/verification for the three-option applicability extension. Added untyped-only coexistence, explicit storage and compatible populated upgrade, shared creation/hint/suggestion matching, listing/audit/UI changes and full regression coverage. |
| 0.18 | 28 November 2026 | Completed the revision 0.6 applicability extension, migration 127, English/Arabic selector and all creation/hint/suggestion paths. Reran every maintained test suite; corrected fixtures and a message-capture transaction defect, then verified the affected complete files, broader draft paths and assembled UI. Exact case coverage records 5,450 distinct maintained cases, with two unrelated pre-existing failures retained and all generator requirements verified. All 39 explicitly observed disposable databases were absent at cleanup. No unrelated search source changed. |
| 0.19 | 28 November 2026 | Corrected the two previously retained verification failures at the user’s request: updated six shifted source line references while preserving every section hash and prior requirement evidence; corrected the historical audit-upgrade fixture and added explicit redaction/restoration checks. All 166 affected-suite tests passed; both disposable databases were dropped. No application, schema, migration or search behavior changed. Original full-run results remain retained. |
