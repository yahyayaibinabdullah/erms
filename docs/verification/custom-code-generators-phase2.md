# Custom Code Generators — Phase 2 Verification

**Date:** 26 November 2026. **Authority:** approved specification revision 0.4.

**Status:** Administration API checkpoint complete. Creation integration and
the Settings interface are later phases; this is not feature release approval.

`backend/services/api/code_generator_routes.py` provides thirteen operations
under `/api/v1/code-generators`: paged definitions, eligible primary fields,
paged type/field selectors, create/read/edit/delete, binding removal, five-value
preview, counter lookup, paged saved counters and forward adjustment. Every
operation derives its policy from `app.settings.manage`; the generated API
inventory records that dependency. No new privilege, setting or configuration
cache was added.

Serials cross JSON as exact decimal strings. Names are required; creation
reasons remain optional. Edits and adjustments require a reason and expected
version. An unused counter reads as version zero without creating storage.
Preview uses unsaved settings, fictional codes, the application working timezone
and isolated counters. It neither saves configuration nor allocates numbers.
Existing authorized audit APIs remain the history boundary.

## Verification and corrections

All logs below are under `.runtime/custom-code-generators/phase0-20261126/`.

| Run | Result and evidence |
| --- | --- |
| `phase2-admin-api.log` | 38 passed: initial administration cases, the existing policy suite and Arabic artifact/hash/placeholder checks. Database `erms_messaging_test_acl_cf776fa08ed648e4882d9ad977451e55` was dropped. |
| `phase2-admin-complete.log` | Expanded run: 25 passed, four failures retained. One counter-list query used an ambiguous column; two assertions assumed a forbidden-resource status instead of the existing hidden-resource 404 and a catalogue fixture failed to clear its preceding test's type. Database `erms_messaging_test_acl_8c640be339ab4762b751c263aa00f380` was dropped. |
| `phase2-admin-corrections.log` | All four affected cases passed after the query/fixture/assertion corrections. Database `erms_messaging_test_acl_79d0545bec564f20a050cdce6effef53` was dropped. |

Coverage includes optional creation reasons, required names and edit reasons,
precise large serials, stale and simultaneous edits, overlapping enabled
bindings, disabled alternatives, binding removal, protected counter retention,
permitted unused-definition deletion, all five preview scenarios, missing
fictional context, length overflow, zero preview writes, scope/full-month
adjustments and audit-failure rollback through the API.

Every operation rejects a signed-in nonadministrator. A settings administrator
with no business-resource or type-edit privileges can select eligible definition
information and configure a Text field; the same caller remains unable to read
the record or edit its type. Integer fields remain ineligible. Primary target
discovery is also covered in the subsequent passing padding/target check noted
in the phase 1 supplement.

## Pagination and actual plans

Tests reached every one of 127 definitions, 125 types, 125 Text fields and 125
saved counter scopes through server pages. Filters, descending definition
ordering, retained selected options and empty/beyond-end pages were checked.
No complete catalogue download implements pagination.

Actual request SQL, parameters, plans and complete HTTP timings are retained
under `.runtime/custom-code-generators/administration-metrics/`, keyed by the
disposable database name:

| Collection | Total / page | Complete HTTP | SQL `EXPLAIN ANALYZE` |
| --- | --- | --- | --- |
| Definitions | 127 / 50 | 26.1 ms | 3.12 ms |
| Types | 125 / 50 | 24.7 ms | 0.19 ms |
| Text fields | 125 / 50 | 40.3 ms | 0.28 ms |
| Counters | 125 / 50 | 7.0 ms | 0.45 ms |

Plans show the page limit before response projection. The field selector uses
its existing field index; the other small catalogues use ordinary set scans and
sorts. No planner override or speculative index was introduced. These small
administration fixtures do not replace later resource/search-scale gates.

## Translation preservation

Added nine `code_generation.error.*` English definitions and nine Arabic
generated drafts, bringing exact active coverage to 4,205 keys. The Arabic
values remain unpublished and require human review. All 4,196 existing items,
their wording and their provenance were preserved unchanged. No administrator
export was promoted and no persistent database translation was changed.

`phase2-catalogue-references.log` passes source-reference, stale-key, ordering
and maintained-artifact coverage checks. The Arabic artifact/hash/placeholder
test passes. Separate validation of the nine new Arabic entries passes
nonblank, placeholder, Latin-text and terminology checks.

The full glossary checker reports an existing failure for
`settings.field.search_result_limit.description`: its curated Arabic wording
omits the English source's aggregation/record filters. Both source and
translation are unchanged from HEAD. The failure is retained in
`phase2-arabic-terminology.log` and independently confirmed in
`phase2-existing-terminology-failure.json`; preservation evidence is in
`phase2-translation-preservation.json`. It is not reported as a passing glossary
gate, and the curated translation was not silently replaced.

## Remaining acceptance

Generation in actual creation/suggestion paths, preserved draft provenance,
safe retries and erasure, natural ordering/cursors/cache invalidation, production
NiceGUI/LTR/RTL behavior and complete release-scale verification remain
unimplemented or unverified. Phase 0's twelve search latency failures remain
recorded failures. This checkpoint does not waive any later acceptance gate.
