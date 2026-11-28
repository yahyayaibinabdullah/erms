# ERMS database setup

## New database

For Arabic-primary deployments supporting English, the recommended database
default is **UTF-8 with ICU locale `ar`**. Create the database explicitly before
loading the schema, for example from a maintenance database such as `postgres`:

```sql
CREATE DATABASE erms
    WITH TEMPLATE template0
         ENCODING 'UTF8'
         LOCALE_PROVIDER icu
         ICU_LOCALE 'ar';
```

Run database creation outside a transaction, using an appropriately authorized
deployment role and the intended database name. Verify `datlocprovider = i` and
`datlocale = ar`; an `en_US.UTF-8` OS label alone does not establish the active
provider. See [collation rationale, measured examples and restore guidance](../docs/database-collation.md).
Existing databases need an explicit rebuild to change their default locale;
`schema.sql` does not change it.

Run the fresh initializer with the intended database selected in `DATABASE_URL`:

```bash
backend/services/api/.venv/bin/python tools/initialize_database.py
```

The installer applies the canonical DDL, required reference data and included migration receipts in one transaction. Any error rolls the installation back. An existing ERMS schema, including one with an empty receipt table, is refused. Existing databases use the numbered upgrades. Investigate missing or mismatched receipts against the corresponding schema and data before making any repair.

For a deployment that uses `psql`, send the same initializer output to a single session:

```bash
set -o pipefail
python3 tools/initialize_database.py --print-sql | psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1
```

`database/schema.sql` remains independently executable DDL. `database/baseline.sql` records the versions included by a fresh installation and requires the initializer’s transaction-local marker. Required seed events use source `seeding`.

See [canonical maintenance and verification](../docs/database-canonical-baseline.md).
All SQL files contain portable PostgreSQL SQL;
client meta-commands such as `\\i`, `\\ir`, `\\set`, and `\\copy` are prohibited.

## Existing database

Apply [migration 128](migrations/128_resource_field_codes.sql) after migrations
126 and 127 and before deploying the type field editor. Take a backup first.
The migration locks the type and field definitions, assigns codes in place,
records the changes in history and advances the version of each affected type.
Refresh any open field editors. To review the backfill, list `id, kind, type_id,
name, code` from `resource_type_fields` in field ID order. See the
[field code rules](../specs/aggregation-and-record-types.md#field-codes).

Apply [migration 125](migrations/125_type_administration_privilege_codes.sql)
with the updated API and WebUI in the same maintenance window. It renames
`aggregations.administer` to `aggregation_types.administer` and
`records.administer` to `record_types.administer` on their existing privilege
IDs and places both under Administration. Update integrations that check codes
directly. Existing profile grants still refer to the same IDs. The migration
carries translations to the new keys and retains the old keys for audit history.

[Migration 124](migrations/124_type_privilege_categories.sql) groups **Administer
aggregation types** under **Aggregation** and **Administer record types** under
**Record** in role details and the profile privilege editor.

For a database at version 122, back up the database and apply
[migration 123](migrations/123_resource_type_everyone.sql) before deploying the
updated Role access dialog. Each existing row keeps its named role and grants.
A null role ID represents an explicitly configured Everyone grant. The upgrade
creates none. The unique constraint permits at most one Everyone grant per type.

For a database at version 121, apply [migration 122](migrations/122_resource_field_positions.sql) before using the updated Fields administration dialog. The migration locks type and field definitions while it numbers fields consecutively within each type, in ascending former display order and then field ID. It updates the version of each affected type so already-open editors detect the change. Existing field IDs and resource values are preserved. Take a restorable backup and quiesce writers for the upgrade. Check the complete receipt and compare field IDs in display order before and after upgrading.

After version 120, apply [migration 121](migrations/121_type_text_search.sql) before deploying the updated API. It installs synchronous indexing for type-specific text and backfills existing records and aggregations that have stored text. The backfill keeps each document's PostgreSQL text configuration and updates its GIN entries in the same transaction. Resources without stored text require no rewrite. Component files and chunks require no re-extraction or reindex.

Schedule the migration during a write maintenance window. It acquires `SHARE ROW EXCLUSIVE` locks on records, aggregations and their type-value tables. Ordinary reads can continue. Resource and field-value writes wait until commit. Allow space for changed metadata rows, GIN entries and WAL. An error rolls back the backfill, trigger definitions and version marker together. Fresh installations get the final definitions from the canonical schema. [Phase 4 measurements](../docs/verification/aggregation-record-types-phase-4.md)

Migration [119](migrations/119_resource_types.sql) installs the aggregation and record type foundation. It leaves existing resources untyped and preserves saved searches. The nullable columns require no resource heap rewrite. The migration builds resource indexes and holds an `ACCESS EXCLUSIVE` lock on both resource tables until commit. Schedule a maintenance interval with capacity for the new indexes and WAL. The measured interval and resource-index growth are recorded in the [Phase 1 upgrade report](../docs/verification/aggregation-record-types-phase-1.md#populated-upgrade). Apply the remaining type migrations before starting the updated API or WebUI.

### Resource type upgrade and recovery

For a database at `118_converted_preview_renditions`, take a restorable pre-upgrade backup or record a verified point-in-time recovery target. Check the complete migration names and confirm disk capacity for the new indexes, temporary index builds, changed search documents and WAL, including retained WAL on replicas. Use the installation’s actual data volume to budget the maintenance window. Keep API writers and background workers quiescent through the upgrade.

Apply the files in order with a connection that stops on the first error. Each file commits its own DDL, data changes and receipt. Run this example only after confirming all three files are pending.

```sh
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  -f database/migrations/119_resource_types.sql \
  -f database/migrations/120_resource_type_access.sql \
  -f database/migrations/121_type_text_search.sql
```

Migration 119 builds two assignment indexes and two unique resource indexes. Its table locks can also block reads. Migration 120 installs the type authorization functions, audit and write triggers, and default profile grants. Migration 121 holds its write locks until the text backfill commits. After the upgrade, verify the three receipts, valid type indexes and enabled triggers. Check an existing untyped resource and saved search, then check a typed resource as an authorized and a restricted viewer. Refresh planner statistics on the affected tables after a substantial backfill. The release uses the existing service configuration and normal catalogue synchronization. Review and publish new Arabic drafts through Translation Administration.

If a file fails, keep the application quiescent and inspect the error and the complete receipts from a new connection. A committed earlier file remains applied. Resolve the cause and resume at the first pending file after verifying its objects. A disconnected client may have lost a commit acknowledgement, so check the receipt before retrying. If the installation must return to the previous release after a commit, restore the database to the verified recovery point and pair it with the previous application build before reopening writes. Account for any writes made after the recovery point. The fresh-install baseline and manual receipt edits cannot undo committed schema or data changes.

[Final rehearsal and observed space, locks and response times](../docs/verification/aggregation-record-types-phase-6.md)

### Type migration identifiers after PDF integration

The published `118_converted_preview_renditions` identifier is unchanged. Apply
the type migrations in order: `119_resource_types`, `120_resource_type_access`,
then `121_type_text_search`. Their SQL object definitions and data changes are
unchanged by renumbering; only filenames and migration receipt values changed.

| Former feature-branch identifier | Current identifier |
| --- | --- |
| `118_resource_types` | `119_resource_types` |
| `119_resource_type_access` | `120_resource_type_access` |
| `120_type_text_search` | `121_type_text_search` |

Check the complete `schema_migrations.version` strings before upgrading. A
database that already applied a former type identifier must not rerun that
migration's DDL. Reconcile only the affected receipt's `version` to the mapping
above in a reviewed maintenance transaction, preserving its `id` and
`applied_at`. Resolve any mixed old/new receipt history before proceeding.
Renaming repository files does not update existing databases automatically.

Retained verification reports and compressed artifacts record the original
identifiers, source revisions, hashes and measurements. Those historical
results have not been rewritten or rerun after renumbering. The current
upgrade runner starts from published `main` including the PDF migration and
uses the new type identifiers.

### Earlier storage migration

Migration `112_search_vector_storage.sql` changes the physical storage of file
search vectors to `MAIN` with LZ4 compression. PostgreSQL must be built with LZ4
support. `MAIN` prefers an inline compressed value but still supports overflow
for larger vectors; it does not truncate lexemes, positions or weights.

Changing a column's compression policy alone does not convert existing values.
Migration 112 rewrites the chunk table and its indexes using a logically
identical vector expression, without extracting or parsing document text again.
Plan a maintenance window: stop new searches and pause index publishing, allow
existing transactions to finish, and provision space for the replacement table,
indexes and generated WAL while the old files still exist. The rewrite takes
an `ACCESS EXCLUSIVE` lock. A failure rolls back the migration and its version
marker. Take the normal deployment backup before upgrading.

After applying this migration, run the following outside a transaction before
resuming traffic, to complete post-rewrite visibility/statistics maintenance:

```sql
VACUUM ANALYZE public.digital_component_search_chunks;
```

Verify the column policy and the actual values independently; small values may
legitimately remain uncompressed:

```sql
SELECT attstorage, attcompression FROM pg_attribute
WHERE attrelid='public.digital_component_search_chunks'::regclass
  AND attname='search_vector'; -- m, l
SELECT pg_column_compression(search_vector), count(*)
FROM public.digital_component_search_chunks GROUP BY 1;
```

No PostgreSQL-wide memory, planner, durability or compression default is changed.
The fresh schema contains the same column policy without replaying this rewrite.
See [the measured investigation](../docs/verification/search-score-reuse-2026-11-13.md).

Migration `080_fix_held_component_trigger.sql` fixes table-specific field access in
legal-hold protection without weakening holds. Apply it after migration 079,
then restart the API-owned content cleanup worker (or local stack) with the
updated cleanup code. Cleanup retains upload sessions for held records and
reclaims eligible expired sessions after the hold is released.


Migration `050_application_settings.sql` installs the typed application-settings
foundation and protected administration privilege without importing environment
values or overwriting configured settings. Apply it after migration 049 and
follow [the API/key upgrade guidance](../docs/application-settings-upgrade.md).

Migration `048_hierarchical_oversight_acls.sql` adds the approved organizational
role designations and contextual ACL principals. It changes defaults only for
future resource creation; it preserves every existing ACL grant. See
[implementation and verification](../docs/hierarchical-oversight-acls-implementation.md).

Migrations upgrade an existing database containing data. Inspect
`schema_migrations` and apply only missing files from `database/migrations/` in
filename order for upgrades newer than its recorded baseline. A fresh canonical
installation must not replay older files merely because their historical marker
is absent.

Migration **116** activates bilingual defaults for the five disposition
notification producers that have no saved configuration. It registers any
missing contracts and preserves saved drafts and all existing versions. It
requires English and Arabic to be registered and covers installations where
only those languages are enabled. Supply the user ID of the active
`messaging.notifications.administer` administrator approving the templates
to record their review and activation in the audit trail. For example, replace
`42` with that administrator's ID and run:

```bash
PGOPTIONS='-c app.user_id=42' psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/116_disposition_notification_defaults.sql \
  -f database/migrations/117_disposition_notification_job_numbers.sql
```

Migration **117** adds `{job_number}` to the four job-specific producers and
publishes it in the built-in English and Arabic templates. It preserves
custom versions and drafts. Installations that already applied 116 run only
117, with the same administrator attribution. Apply the migrations and deploy
the matching API and disposition workers together. A fresh installation can
configure the producers after the administrator has been provisioned.

Migration **115** adds **Messages per page** for Inbox, Outbox, and Drafts.
Apply it before restarting the API and WebUI. Existing installations start at
25 with an allowed range of 1–50.

Migration **114** saves the action completion checkbox with reply drafts.
Apply it before running the updated messaging API against an existing database.
Existing drafts start unchecked because earlier versions did not save the choice.

Migration **113** adds the application settings for child aggregation,
contained record, and search result page sizes. It adds defaults of 10, 25,
and 25 and preserves values already present. Apply it before restarting the
API and WebUI with code that reads those settings.

Migration **079** originally omitted its history insert. Use the corrected
`079_disposition_admission_reason.sql` from the current checkout when reconciling
an existing installation. It records its version and is safe to repeat. If
migration 084 or its reason-free claim behavior is already present, 079 verifies
the superseding function and reason constraint, records only the missing marker,
and preserves those newer definitions. Detected drift stops reconciliation for
inspection. On an older schema, 079 applies its original change; continue later
migrations in order. Fresh installations record 079 through `baseline.sql`.
Do not replay an older copy of 079 over a post-084 database: it can reinstate the
task-claim reason requirement. Pulling code or running the local stack does not
automatically apply these upgrade scripts. See
[079 reconciliation evidence](../docs/verification/migration-079-reconciliation.md).

Examples of explicitly applying missing upgrade files:

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

## Disposition/application-settings upgrades through 071

For an existing database current through 049, follow the ordered missing-only
050–071 procedure and separate seeds in [the controlled rollout runbook](../docs/disposition-rollout.md).
New empty databases still use `schema.sql` alone. The runbook includes explicit
settings preview/apply/check for each database; applying schema is not a legacy
settings import. Persistent deployment requires explicit authorization. Migration 071 removes
temporary release gates; existing workflow/permission checks still authorize
each destruction action. No destruction occurs merely by applying migrations.

Migration 111 renames the shared UNLOGGED result-list table from
`global_search_results` to `search_results_cache`, preserving rows, ownership,
constraints, expiry index and login-session cascade. Deploy API and independent
cleanup-worker code together after this migration. All four record/aggregation
search screens replace the same session/tab slot; schema initialization uses the
new name directly. See `docs/application-settings-upgrade.md`.
