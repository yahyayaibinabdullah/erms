# Canonical database baseline

`database/schema.sql` is the sole schema baseline for Wathiq. It creates a
complete current database. Later schema additions may record their included
version markers in `schema_migrations`; those markers do not execute migrations.
Seed scripts remain separate under `database/seeds`.

On 21 September 2026, the sole local development database was re-baselined by
creating a separate database from the canonical schema and restoring a
data-only PostgreSQL 18 dump with triggers temporarily disabled. Every table's
row count matched the source; event history, binary-content size, ownership,
medium and physical-component invariants were verified before the databases
were renamed. The previous database remains available as
`erms_precanonical_20260921` for rollback.

Because a data-only restore replaces catalogue rows that `schema.sql` initially
bootstraps, run `database/seeds/002_reconcile_governed_resource_catalogue.sql`
after such a restore. The script idempotently restores governed privilege and
permission rows, dependencies and built-in governance-profile memberships.

The git-ignored `database/local-backups` directory contains the full and
data-only pre-baseline dumps and their reported SHA-256 checksums. These files
must not be committed or distributed as they may contain sensitive data.

Historical migrations were removed because no other deployed database needs an
upgrade path. Future schema changes must update `schema.sql` and introduce a new
migration sequence beginning from this baseline. Database-backed tests create a
unique disposable database from `schema.sql`; they never run against the local
development database.
