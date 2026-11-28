# Custom Code Generators — Phase 1 Verification

**Date:** 26 November 2026. **Authority:** approved specification revision 0.4.

The shared schema, renderer, counter allocator, configuration audit guards and
creation-request identity primitives are implemented. Application creation and
administration routes do not use them yet. All phase 1 checks passed and their
disposable databases were dropped. Phase 1 is complete; the feature is not yet
available in the application.

## Implementation

- `database/schema.sql` and upgrade `126_custom_code_generators.sql` define the
  same three shared tables, native binding constraints and database guards.
  Fresh initialization is self-contained. The upgrade enables no generator.
- `code_generation.py` parses and renders the approved tokens, exact serials,
  Unicode character lengths, minimum padding, stable scopes and full calendar
  buckets. Its five-value simulations have no database or clock side effects.
- `code_generation_store.py` coordinates current bindings, ordered per-counter
  allocation, occupied primary-number skipping, exact accepted suggestions,
  read-only counter peeks and versioned forward adjustments. Caller/operation/
  submission keys and precise input fingerprints support durable completion.
- Database triggers audit configuration and explicit next-number changes in
  the existing immutable history. Creation reasons are optional; edits and
  adjustments require a reason. Ordinary serial allocations produce no
  configuration-change event. Audit failure rolls back the associated change.
- Draft reads expose the new empty-by-default provenance object. Saving a draft
  still permits a missing record number and allocates nothing.

## Executed checks

Logs are retained under `.runtime/custom-code-generators/phase0-20261126/`;
the directory name preserves continuity with the baseline evidence.

| Check | Result | Log |
| --- | --- | --- |
| Renderer/simulation and canonical schema tests | 117 passed: 72 engine cases and 45 canonical-schema cases. | `phase1-pure-parity-final.log` |
| Current database guards | 39 passed; populated upgrade deliberately skipped by this fresh-schema run. | `phase1-database-current-guard.log` |
| Allocation, read-only peeks, exact suggestions, adjustment versions, reverse multi-counter lock order, concurrent replay | 11 passed. | `phase1-store-advance-metrics.log` |
| Simultaneous enable/retarget, configuration versus allocation, multi-field rollback | 4 passed. | `phase1-remaining-races.log` |
| Two first adjustments of one unused counter | 1 passed; exactly one winner and one adjustment audit event. | `phase1-adjustment-race.log` |
| Populated upgrade, forced rollback, preservation and DDL-lock observation | 1 passed. | `phase1-upgrade-locking-space.log` |
| Existing creation, numbering, type foundation and scoped type access | 96 passed in 247.51 seconds. | `phase1-existing-creation-types-regression.log` |

Every database-backed run created a unique disposable database and dropped it.
The final runs recorded successful cleanup for:

- `erms_messaging_test_acl_e6ac6c9667cd437481c2194f98db9df5`
- `erms_messaging_test_acl_07ccd6b0b0994709841dac255ae82b06`
- `erms_messaging_test_acl_2080cc2865a440aa80d44922749027a6`
- `erms_messaging_test_acl_9ae9ebb6fd984f7d9ddd50292ea05582`
- `erms_messaging_test_acl_ec5b5d19b55a461bae771e395ed64f3f`
- `erms_messaging_test_acl_27d607acecce421e9347f6e8acdfd0d5`

Earlier smoke, populated-upgrade and allocation runs and their cleanup remain
in `phase1-schema-smoke.log`, `phase1-database-rerun.log`,
`phase1-populated-upgrade.log` and `phase1-store.log`. The initial failing
fixture-isolation run is retained in `phase1-database.log`; it led to explicit
disposable-only reset handling for the protected new tables.

## Reproduced field-edit race

`phase1-field-race-before-fix.log` preserves a failing regression: an earlier
Repeatable Read snapshot saw a generator maximum of 20, another transaction
committed a maximum of 50, and the first transaction could reduce its field to
30. An advisory lock did not refresh that snapshot.

The database now rejects field-length reductions in frozen snapshot modes with
retryable SQLSTATE `40001`; the normal API uses Read Committed. Compatible
increases and label edits retain their existing transaction modes. Passing
coverage checks Read Committed, Repeatable Read and Serializable, as well as
the existing concurrent typed-value length test. See the integration design
for lock ordering and the operational retry requirement.

## Measurements and limits

Actual occupancy plans and allocation timings are in
`.runtime/custom-code-generators/allocation-metrics/` with the disposable
database name. With 1,500 occupied codes, the first available serial was 15010
for both padding widths 0 and 4. Allocation took 7.59 ms and 7.28 ms;
`EXPLAIN ANALYZE` measured 5.30 ms and 4.96 ms. The actual plans scan the
1,500 matching rows once and find the next gap as a set. They do not issue one
query for each occupied serial. No planner setting or index was added to make
these small-fixture measurements pass.

Four workers committed eight creations against one counter in 421 ms, with
individual connection/transaction times of 121–287 ms. The independent-counter
test completed one creation while another counter remained locked. These are
transaction-primitive checks, not complete API throughput or release-scale
performance claims. The later phases retain representative hot-counter,
many-generator and full request/performance gates.

The populated fixture contained one record and one numberless draft. Its
upgrade took 92.5 ms including a deliberately induced relation-lock wait.
Database size increased by 573,440 bytes, including extension objects; the new
empty tables and indexes occupied 90,112 bytes together. The observed wait
confirms that the draft-table alteration requires an exclusive DDL window.
Larger installations still need deployment scheduling and representative
upgrade measurements; this tiny fixture is not a production maintenance-time
estimate. Evidence is in `.runtime/custom-code-generators/upgrade-metrics/`.

The phase 0 standard/larger-text search failures remain recorded as failures.
These foundation measurements neither waive those gates nor demonstrate
natural-ordering performance. Administration APIs, creation integration,
natural sorting, WebUI/Arabic and integrated release verification remain later
phases.

## Supplement during phase 2

An additional width-eight case exposed an occupancy-parser error: it compared
the padded digit count with the numeric bound's significant digit count. The
parser now removes leading zeroes before that bound check and numeric parsing,
then still compares the complete stored code with the exact configured padding.
No second stored representation is introduced.

The reproducer is retained in `phase1-wide-padding-before-fix.log`. The first
rerun exposed a second mistake in the test data: its deliberately different
zero representation was identical to the newly tested width-eight format.
That failing run is retained in `phase1-wide-padding-fixed.log`; its other
three checks passed, including eligible primary-target discovery through the
API. Corrected data and the actual allocator now pass all four checks in
`phase1-wide-padding-final.log`: widths 0, 4 and 8 with 1,500 occupied codes,
plus an all-zero padded starting serial. All three disposable databases were
dropped, including `erms_messaging_test_acl_1230842fd8cc4949a4f61e71fa3be848`
for the final passing run.

The final actual plans and timings are retained with that database name.
Allocation took 8.25, 6.96 and 16.91 ms for widths 0, 4 and 8;
`EXPLAIN ANALYZE` measured 5.89, 5.88 and 6.56 ms. These replace the earlier
small-fixture timings when assessing the corrected query, while preserving the
original evidence.
