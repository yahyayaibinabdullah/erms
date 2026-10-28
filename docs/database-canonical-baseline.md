# Canonical database baseline

`database/schema.sql` defines the complete **current structure** of a new
PostgreSQL 18 database. Each function has one final definition. Tables contain
their current columns and checks; the later constraint, default, ownership and
ACL statements attach final objects in dependency order. They do not replay
older versions, transform existing application rows or invoke migrations.
The file has one transaction and refuses PostgreSQL installations without the
required built-in Arabic text-search configuration.

## Fresh installation

Create the empty database with explicit locale settings first. **ICU `ar` with
UTF-8** is recommended for Arabic-primary, Arabic/English Wathiq deployments.
The [collation guide](database-collation.md) contains the creation/inspection
commands, measured libc differences, `ar` versus `und` rationale and conversion
checks. Provider selection is outside the canonical DDL. Existing databases and
local volumes retain their locale until an operator deliberately rebuilds them.

Run these independent files in order:

1. `database/schema.sql`: current object definitions only.
2. `database/seeds/000_required_reference_data.sql`: required built-in settings,
   languages, security levels, permissions, profiles, dependencies and protected
   service-role defaults. These are the final values, not a sequence of changes.
3. `database/baseline.sql`: registers the installation’s version. It executes no
   historical migrations. It records one explicit list of upgrade versions
   already included in this fresh schema.

`tools/initialize_database.py` performs these steps using the API Python
runtime and refuses an existing application schema. Docker local initialization
and the standalone bootstrap helper use the same order. Optional feature,
classification, demonstration and load seeds remain separate. Required-reference
seeding refuses an existing populated catalogue and must never be used to
reconcile or overwrite a colleague's database.

Fresh seed events use source `seeding`. The previous schema created a mixture
of seed, database and migration audit rows while replaying its construction
history. Fresh installations now audit the final reference-data inserts with
seed provenance; that old construction history is not copied. Actual existing
audit history is not changed. Fresh database UUIDs and initialization timestamps
are independently generated, as before.

Existing databases and historical migration files are unaffected. Upgrade them
with the migrations newer than their installed baseline; never replay older
files just because a fresh baseline did not list every historical marker.
Never load the three fresh-install files over an existing database.

## Maintaining the canonical files

For a structural change, edit the existing final definition in `schema.sql`
and add an independent migration for existing databases. Do not append an older
object followed by `CREATE OR REPLACE`, `DROP`, repeated column changes or data
repairs. Change the required reference seed only when fresh-install defaults
change. Keep the included-version list in `baseline.sql` current. Schema creation
must never invoke either a seed or a migration.

The seed is not a dump of a development tenancy: it contains no users,
organization hierarchy, records, aggregations, credentials or environment values.
Its sole role row is the existing protected platform text-indexer role.

## Verification

`tools/tests/test_canonical_schema.py` rejects top-level data repairs,
replacement definitions and multiple transaction blocks. SQL function bodies
remain opaque to that check: normal application DML inside a function is allowed.

The current parity gate uses an independent full backup of a migration-built
database. It does not use another fresh schema as the reference:

```bash
backend/services/api/.venv/bin/python tools/verify_canonical_schema.py \
  --reference-archive /private/path/migration-built-database.dump \
  --pg-dump /path/to/postgresql-18/bin/pg_dump \
  --report /tmp/canonical-schema-migration-parity.json
```

The verifier owns two uniquely named disposable databases. It restores the full
reference archive into one, builds the current schema in the other and restores
the same archive's data into it, then drops both on success or failure. It reads
the archive's explicit encoding, locale provider and locale options before
creating either database. It never inherits an unintended provider from
`template0`. Restore diagnostics containing private data stay under gitignored
`.runtime/canonical-schema-verification/` with restricted file permissions.

The schema comparison preserves object names, visible column ordering, function
bodies, grants, constraints and indexes. PostgreSQL reparses CHECK and
trigger-WHEN expressions through temporary views to normalize its own flattening
of associative Boolean expressions; it does not discard parentheses blindly.
Exact typed row fingerprints include every application table, audit history,
timestamps, settings, database identity and operational tables. All sequence
states must also match. Both databases use the same backup snapshot, so ongoing
heartbeats and credential-use updates in a running source cannot create false
data discrepancies. It verifies that restore-time trigger disabling was undone.

Internal dropped-column slots, object OIDs, physical storage layout and query
statistics are not logical schema definitions. A clean schema does not recreate
obsolete columns to reproduce that history. The fresh reference seed is tested
separately through fresh-install API regressions; archive restores already
contain reference rows and must not run the seed over them.

On 28 October 2026 the final definitions were aligned with the approved
migration-built database: 29 CHECK names, visible column order in `org_units`,
`roles` and `users`, and 17 function bodies. The source contract is protected by
tests comparing those bodies and names with their independent migration files.
See [the discrepancy correction report](verification/canonical-schema-discrepancies.md).

The initial 27 October consolidation gate compared with the previous canonical
Git schema. That established preservation of the old file, but did not detect
its pre-existing drift from the migration path. Its report remains historical
evidence, not the current parity gate. An explicit `--reference-ref` mode is
available for historical comparisons and requires explicit `--locale-provider`
and `--locale` values; it is not a substitute for the migration-built archive.

Historical upgrade tests read their predecessor fixture through
`tools/historical_schema.py`; they must not slice migration fragments from the
current canonical file. Shallow CI checkouts need the pinned commit available.
The normal disposable API runner installs all three current files before its
feature fixtures. Regression shards have separate databases and never share
mutable test data or use a persistent development database.

## Earlier development re-baseline

The 21 September 2026 development re-baseline and its gitignored backups predate
this consolidation. This cleanup does not restore, rename or upgrade any
persistent database. After a deliberately authorized data-only restore, the
existing `database/seeds/002_reconcile_governed_resource_catalogue.sql` remains
the explicit catalogue-reconciliation path; the fresh reference seed is not a
replacement for that workflow.
