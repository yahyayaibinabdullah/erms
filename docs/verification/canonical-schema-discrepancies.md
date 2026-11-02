# Canonical schema alignment with the migration path

Verified on 28 October 2026 using PostgreSQL 18.4.

## Corrected definitions

The canonical file previously agreed with its earlier Git version, but that
version already differed from the approved upgrade path. These differences were
observed when comparing the migration-built `demo` database with a fresh restore.
The final definitions in `database/schema.sql` now match that upgrade path:

- 29 CHECK constraint names from migrations 019 and 020.
- Visible column order for `org_units`, `roles` and `users`, following migration
  004's lifecycle changes.
- 17 function bodies, each checked against its last definition in the approved
  migrations. Fourteen differed only in formatting/case; the remaining three
  used different aliases or optional `AS` syntax.

These edits are in-place final definitions. They do not add migration replays,
change business rules or rewrite audit history. Historical migration files,
reference defaults and baseline version markers are unchanged. Existing
migration-built databases already have the expected definitions; no new feature
upgrade is introduced. No persistent database, including `demo` and `demo4`, was
altered by this correction.

Object IDs, old dropped-column slots, storage sizes and query statistics remain
expected internal differences when a database is recreated. They are not
reproduced through obsolete DDL in the canonical file.

## Independent schema and data verification

Two uniquely named disposable databases were created with the backup's explicit
`libc` / `en_US.UTF-8` settings. One received the full saved migration-built
archive; the other received the corrected canonical schema and the archive's
data. No seed was applied over restored reference data.

The comparison passed for:

- 128 tables, 6 views, 333 functions and 312 triggers, including exact names,
  visible column order, function source, grants, constraints and indexes.
- All 192,150 rows, including audit history, settings, credentials, timestamps
  and operational tables. Row fingerprints retain SQL NULLs and JSON text.
- All 66 sequence states.
- Matching database locale settings and re-enabled triggers after data restore.

Only PostgreSQL's own associative Boolean deparsing and client dump boilerplate
were normalized in the schema comparison. Function bodies, CHECK names and
visible column ordering were not ignored. No runtime-table or timestamp
exclusions were used in the archive data comparison.

Both comparison databases were dropped. Machine-readable evidence is in
[canonical-schema-migration-parity.json](canonical-schema-migration-parity.json).
The verifier and reproduction command are documented in
[the canonical baseline guide](../database-canonical-baseline.md).

## Regression checks

All **57** focused canonical-schema, migration-source alignment,
locale-preservation and application-settings checks passed. All **58**
fresh-install API regressions passed, exercising localization, translated entity
metadata and legal holds in another uniquely named disposable database, which
was then dropped. Exact results are recorded alongside the parity
report in [canonical-schema-correction-checks.json](canonical-schema-correction-checks.json).

The earlier broad API run's pre-existing workflow-fixture failures remain
documented in [the initial consolidation report](canonical-schema-consolidation.md).
This correction does not claim a new full-suite pass.

## Locale and runtime-data scope

The locale-provider mismatch in `demo4` was caused by its database-creation
command inheriting ICU from the server template. A database's default provider
is selected before `schema.sql` runs. The verifier now preserves the archive's
provider and locale explicitly. This correction does not choose a new production
collation policy or rebuild either persistent database.

Differences in live gateway health, service-account `last_used_at`, and indexer
`last_contact_at` / `active_until` arose from source application activity after
the backup. They were not caused by different table definitions. The archive
comparison includes those tables and proves that the same snapshot restores
identically under the corrected schema.
