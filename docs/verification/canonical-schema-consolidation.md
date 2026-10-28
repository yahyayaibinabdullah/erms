# Canonical schema consolidation verification

This records the initial **27 October** comparison with the previous canonical
file. The **28 October** [migration-built discrepancy correction](canonical-schema-discrepancies.md)
is the current parity evidence. The initial comparison did not establish parity
with a database built through the historical migrations.

Verified on 27 October 2026 with PostgreSQL 18.4. The reference is the original
`database/schema.sql` at Git commit
`a476ff2dc6e96f29d8d1047ccbbc656fa5455657`.

## Result and scope

The consolidated schema contains each final definition once, in one transaction.
It does not replay migrations, insert reference data, repair existing rows or
record migration versions. Required reference data and fresh-install version
bookkeeping now have separate, explicitly executed files. Fresh installation
callers and their documentation use the same three-file sequence.

No existing database, including `demo`, was upgraded or changed. No historical
migration was edited. Product workflow and authorization behavior were preserved.
There were no environment-variable or translation-catalogue changes.

## Two-database comparison

`tools/verify_canonical_schema.py` created two uniquely named disposable databases:
one from the original schema and one from the consolidated schema, required seed
and baseline. The complete final object definitions matched, including function
bodies, grants, constraints, indexes and triggers:

| Object | Count |
| --- | ---: |
| Tables | 128 |
| Views | 6 |
| Functions | 333 |
| Triggers | 312 |

All required reference rows matched, including 55 settings, 65 privileges,
35 permissions and 39 included-version markers. Database UUIDs and initialization
timestamps were excluded from row equality. PostgreSQL's associative Boolean
expression deparsing was normalized by reparsing CHECK and trigger-WHEN
expressions through temporary views; function bodies were not normalized away.

Two expected initialization differences were checked explicitly:

- Fresh reference inserts generate 348 events with source `seeding`; the old
  construction history generated 186 events with mixed sources. Existing audit
  history is unaffected.
- Inserting the two languages with the final notification trigger installed
  initializes its serialization guard at revision 2. The original file installed
  that trigger after the language inserts and left the guard empty. No language,
  notification preference or authorization value differs.

Both comparison databases were dropped. The machine-readable results and source
hashes are in [canonical-schema-parity.json](canonical-schema-parity.json).
Reproduction instructions are in
[the canonical baseline guide](../database-canonical-baseline.md).

## Regression checks and limitations

The broad disposable API runs recorded **1,441 passed, 35 failed and 2 skipped**.
Two runs stopped at a 12-failure limit, so this is not a claim that the entire
API suite completed or passed.

One static policy test still looked for reference data inside `schema.sql`.
It was updated to check the separate required seed and passed on recheck.
The other 34 failing nodes were then run against the original schema:

- **33 also failed on the original schema.** Examples include fixtures expecting
  manual claiming despite automatic sole-reviewer assignment, or expecting job
  completion before the explicit final certificate-task acknowledgement.
- The remaining governance-custody check **passed alone on both schemas**. Its
  broad-run failure depends on test context/order; this cleanup does not change
  its highest-clearance policy or fixtures.

The test-by-test baseline outcomes are retained in
[canonical-schema-regressions.json](canonical-schema-regressions.json).
Those existing failures still need separate test maintenance/investigation;
authorization or approved workflow behavior was not weakened to satisfy them.

Additional checks passed:

- 24 canonical-schema and application-settings checks.
- Local-stack lifecycle/disposition launcher checks in the tool regression run.
- Three policy-inventory static checks after relocating the reference seed.
- Shell syntax, changed Python modules' compilation, API environment-template
  synchronization and `git diff --check`.

Additional regression runs used their own disposable databases. Each runner
reported successful cleanup, and the final PostgreSQL inventory found no
remaining databases with the test runner's `erms_messaging_test_acl_` prefix.
Detailed local test logs are gitignored under `.runtime/schema-consolidation/`.
