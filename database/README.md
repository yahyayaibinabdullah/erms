# ERMS database setup

## New database

Initialize a new empty database from the canonical schema alone:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/schema.sql
```

`database/schema.sql` is complete and self-contained. It does not execute or
depend on migrations or seeds. All SQL files contain portable PostgreSQL SQL;
client meta-commands such as `\\i`, `\\ir`, `\\set`, and `\\copy` are prohibited.

## Existing database

Migration `048_hierarchical_oversight_acls.sql` adds the approved organizational
role designations and contextual ACL principals. It changes defaults only for
future resource creation; it preserves every existing ACL grant. See
[implementation and verification](../docs/hierarchical-oversight-acls-implementation.md).

Migrations upgrade an existing database containing data. Inspect
`schema_migrations` and apply only missing files from `database/migrations/` in
filename order:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/001_fix_vital_descendant_scope.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/002_govern_review_dates.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/003_location_sources_and_governed_history.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/004_normalize_user_management_lifecycle.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/005_add_legal_holds_foundation.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/006_correct_legal_hold_authorization.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/007_add_global_hold_membership_management.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/008_rename_hold_membership_to_held_items.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/009_preserve_relationship_truth_for_search.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/010_add_full_text_search_phase1.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/011_add_full_text_search_phase2.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/012_add_full_text_search_phase3.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/013_add_full_text_search_rollout_controls.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/014_rename_system_role_to_platform_role.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/015_restore_system_role_terminology.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/016_add_retention_schedule_foundation.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/017_add_search_subsystem_foundation.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/018_add_advanced_search_phase1.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/019_add_internationalization_foundation.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/020_add_ui_message_catalogue.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/021_add_multilingual_entity_metadata.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/022_harden_internationalized_search.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/023_add_multilingual_profile_metadata.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/024_grant_profile_metadata_to_system_administrator.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/025_allow_text_indexer_role_translations.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/026_allow_text_indexer_profile_translations.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/027_simplify_translation_publication.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/028_disallow_non_source_copy_publication.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/029_organization_tree_ordering.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/030_rename_saved_search_admin_privilege.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/031_allow_governed_security_changes_on_closed_resources.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/032_remove_redundant_record_draft_status.sql
```

Migration 004 makes lifecycle timestamps authoritative. Organization units and
roles are inactive exactly when `date_deactivated` is populated. Users use
`date_deactivated` for deactivation and the separate `date_suspended` timestamp
for temporary suspension. Their `status` columns become generated, read-only
projections so existing API and search contracts remain stable without storing
contradictory mutable state. Suspended legacy users receive migration-time
`date_suspended` values and corresponding immutable migration-provenance events.

Migration 005 installs legal-hold persistence, effective-state calculations,
non-bypassable preservation rules, contributor delegation, immutable history,
and the `holds.administer` privilege.

Migration 006 completes the approved authorization separation (information-
governance visibility without Hold administration), stable Hold integrity
failures, component-reordering protection, event metadata, and governed-search
Hold fields for databases previously upgraded with migration 005.

Migration 007 added the separately auditable `holds.membership.manage_all`
privilege, grants it to the built-in Information Governance Manager and Officer
profiles, and extended assignment-management authority to Hold administrators
and global managers while retaining owner/contributor authority.

Migration 008 renames the original legal-hold membership terminology to the
canonical **held items** terminology. It updates the global privilege to
`holds.held_items.manage_all` and refreshes the database authorization function
without changing existing hold assignments.

Migration 009 makes governed search predicates operate on true aggregation
relationships. Inaccessible parent/container identifiers remain redacted at
the API response boundary and are distinguished from absent relationships by
explicit relationship-state fields.

Migration 010 installs the PostgreSQL 18 full-text-search foundation: weighted
record and aggregation metadata documents, protected service-indexer
authorization, opaque API-key persistence, and authorization-filtered metadata
relations. It fails atomically unless the server is PostgreSQL 18 or newer and
provides the built-in `pg_catalog.simple`, `pg_catalog.english`, and
`pg_catalog.arabic` text-search configurations.

Migration files are not initialization scripts and must never be run against a
new database already created from the latest `schema.sql`.

Migration 013 adds the transaction-local automatic-indexing scheduling gate
used by the staged full-text rollout. It keeps search-document freshness
truthful while scheduling is disabled; bounded reconciliation creates the jobs
after scheduling and workers are enabled.

Migration 014 renames the protected non-organizational role discriminator to
`is_platform_role`, avoiding ambiguity with the ordinary System Administrator
role while preserving all role data and constraints.

Migration 015 restores the discriminator name to `is_system` for consistency
with built-in profiles. In both cases “system” means implementation-owned; it
does not identify or grant the System Administrator role.

Migration 018 installs Advanced Search Phase 1 persistence: saved-search
definitions, role and organizational-unit audiences, owner/concurrency/history
controls, the saved-search privilege family, and the approved built-in profile
grants.

Migration 019 installs the approved internationalization Phase 1 foundation:
the extensible language registry, per-user language and working-timezone
preferences, audited optimistic concurrency, the reserved
`localization.administer` privilege, and the original six entity metadata privileges.

Migration 020 installs the Phase 2 contextual UI-message catalogue, draft and
published translation state, review provenance, row-scoped optimistic
concurrency, validation constraints, and immutable catalogue history. Checked-in
English definitions and non-English source-copy queues are synchronized by the
API startup process after the migration is applied.

Migration 021 adds validated JSONB translation maps to the six approved
multilingual administrative entities. It also adds optional canonical
description fields to users and security levels while preserving all existing
canonical name/title columns and relationships.

Migration 022 installs trigram indexes used as bounded prefilters for
translated metadata search. Search still verifies the exact field and enabled
language after the indexed prefilter, preventing JSON keys or disabled-language
values from becoming results.

Migration 023 adds authorization Profiles as the seventh multilingual domain
entity. It adds the validated and indexed `profiles.translations` map, the
person-only `profile.modify_metadata` privilege, and that privilege's protected
`ALL_PRIVS` membership. Migration 024 grants the same privilege to `SYS_ADMIN`
by default. Existing profile codes, canonical names, privilege
membership, role assignments, and built-in protections remain unchanged.

## Targeted data corrections

Corrective scripts are optional, idempotent repairs for a database exhibiting
the specific documented data gap. They are not migrations and do not add a
`schema_migrations` entry. To backfill missing baseline Security Level history
without duplicating existing `CREATE` events:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/corrections/backfill_security_level_create_history.sql
```

## Seed data

Schema creation, schema migration, and seeding are separate workflows. Apply
optional utilities or SQL from `database/seeds/` only after the database is on
the latest canonical schema. Seeds do not record migration versions and their
event-history source is `seeding`.

The larger XML example file plan is imported transactionally with:

```bash
backend/services/api/.venv/bin/python database/seeds/import_mutamathilah.py \
  --database-url "$DATABASE_URL"
```

## Bootstrap administrator

The schema contains no shared default password. After initializing a genuinely
empty database, provision the one-time bootstrap administrator with:

```bash
backend/services/api/.venv/bin/python -m backend.services.api.manage_auth \
  bootstrap \
  --name "Bootstrap Administrator" \
  --email bootstrap@erms.local
```

The command emits a unique 24-hour temporary password, requires it to be
changed on first login, and refuses to run after users exist. See
[`../docs/authentication.md`](../docs/authentication.md).

## Tests

```bash
database/tests/run.sh
```

The runner creates uniquely named disposable PostgreSQL databases inside a
temporary PostgreSQL container. It tests the canonical schema and the lifecycle
upgrade path separately, runs the API/database suite and backup/restore check,
then explicitly drops auxiliary databases and removes the container on success,
failure, or interruption. It never targets a persistent ERMS database.

Migration 046 (`046_audit_actor_redaction.sql`) updates the authorized history
view to mask actor ID, name and email when the resource event is redacted. This
also prevents actor filters and result counts from matching hidden identities.
Raw immutable history rows are retained. The same view definition is included
directly in `schema.sql` for new installations.

Migration 047 (`047_audit_actor_search_indexes.sql`) adds name/email trigram
indexes and a fixed-size snapshot identity index, and adds deterministic ID
ordering to actor/time indexes. The canonical schema contains the same DDL.
Audit Trail searches are bounded by `AUDIT_TRAIL_SEARCH_RESULT_LIMIT` in `.env`
(default 1000, positive integer). Counts inspect at most that limit plus one
matching authorized event; a truncated search asks the user to refine filters.
Actor suggestions query only current users and return at most 25 matches after
two characters. Unselected text on Apply searches historical snapshots, including
deleted accounts. Apply API configuration
changes by restarting the API process.
