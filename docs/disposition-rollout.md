# Disposition controlled rollout and colleague handoff

This is the Phase 24 preparation runbook. It does **not** authorize applying
changes to demo, staging or production, or performing destruction.
Select the database and obtain deployment authorization before the write steps.
The implementation through Phase 23 has been verified; see
[acceptance](disposition-phase-23.md) and [Phase 24 rehearsal](disposition-phase-24.md).

## 1. Release and prerequisite checks

The maintainer must first commit and share the complete verified implementation.
A colleague cannot obtain an uncommitted working tree with `git pull`. This
runbook neither commits changes nor chooses a deployment branch for the operator.
From a clean checkout of the agreed branch:

```sh
git status --short
git pull --ff-only
python3 tools/sync_api_env_template.py --check
python3 tools/check_configuration_authority.py
python3 tools/check_disposition_acceptance.py
```

Stop on local modifications, divergent branches or failed checks; reconcile them
with the maintainer without resetting local work. Do not combine code from
incompatible phase versions. Back up the selected database and its encryption
key together using the established restore-tested backup procedure. Record its
migration receipts and the deployed revision. Drain API writes, indexers, cleanup
jobs, disposition workers and other database writers before the upgrade; a
running API alone is not the full writer inventory. Before migration 067, old
text-indexer work must be drained/restarted as required by that migration; do not
bypass its undrained-worker rejection.

Use the supported PostgreSQL/runtime/native dependencies from
[deployment.md](deployment.md) and [database/README.md](../database/README.md).
Install the checked-in service requirements in their own virtual environments:

```sh
backend/services/api/.venv/bin/python -m pip install -r backend/services/api/requirements.txt
frontend/webui/.venv/bin/python -m pip install -r frontend/webui/requirements.txt
```

When the optional text indexer is deployed, also follow its existing service
requirements and credentials procedure. Keep its deployment settings in its own
service environment. Do not copy API secrets to the WebUI or indexer template.

Package all four versioned DOCX files, `defaults.json` and the placeholder README
under `templates/disposition/destruction/`, and the licensed embedded Changa face
at `backend/services/api/messaging/pdf_assets/disposition/Changa.ttf`.
LibreOffice must be discoverable by the API account or selected through existing
`LIBREOFFICE_BINARY`; include Fontconfig and the platform font backend. Follow
[template dependencies](disposition-phase-12.md) and the existing PDF native
Pango/validation dependencies in deployment.md. Do not substitute a font or
rebuild templates during deployment. Uploaded organization-wide template
revisions live in the database and must survive code upgrades. Retained PDFs
are downloaded/emailed as their original bytes, never regenerated on access.

## 2. Select and upgrade each existing database

Run from the repository root. Export `DATABASE_URL` securely for **one selected
database**; keep the value out of shared logs and shell history. Verify the
selection before proceeding:

```sh
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -c 'SELECT current_database();'
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -c 'SELECT version FROM schema_migrations ORDER BY version;'
```

This upgrade path requires the database already current through
`049_resource_relationships`. Older databases first need the preceding approved
migration path from database/README.md. An existing database must never be
initialized with `schema.sql`. Apply missing files from the ordered list below,
checking the filename stem against `schema_migrations.version` first. Do not
blindly replay all DDL: several migrations are intentionally non-repeatable.

| Order | Migration |
| --- | --- |
| 050 | `database/migrations/050_application_settings.sql` |
| 051 | `database/migrations/051_database_indexing_policy.sql` |
| 052 | `database/migrations/052_application_settings_reference_audit.sql` |
| 053 | `database/migrations/053_disposition_foundation.sql` |
| 054 | `database/migrations/054_disposition_eligibility.sql` |
| 055 | `database/migrations/055_disposition_membership.sql` |
| 056 | `database/migrations/056_disposition_artifacts.sql` |
| 057 | `database/migrations/057_disposition_templates.sql` |
| 058 | `database/migrations/058_disposition_routing.sql` |
| 059 | `database/migrations/059_disposition_review.sql` |
| 060 | `database/migrations/060_disposition_approval.sql` |
| 061 | `database/migrations/061_disposition_review_save.sql` |
| 062 | `database/migrations/062_disposition_external_approval.sql` |
| 063 | `database/migrations/063_disposition_communications.sql` |
| 064 | `database/migrations/064_disposition_physical.sql` |
| 065 | `database/migrations/065_disposition_recovery.sql` |
| 066 | `database/migrations/066_disposition_destruction_runs.sql` |
| 067 | `database/migrations/067_disposition_content_erasure.sql` |
| 068 | `database/migrations/068_disposition_retained_records.sql` |
| 069 | `database/migrations/069_disposition_completion.sql` |
| 070 | `database/migrations/070_disposition_decision_minimization.sql` |
| 071 | `database/migrations/071_remove_destruction_release_gates.sql` |

For each missing file, the exact invocation is:

```sh
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f database/migrations/050_application_settings.sql
```

Replace that filename with the next missing file from the table. Stop at the
first error, preserve the error privately, inspect receipts and transaction
outcome, and repair the cause before resuming. Do not stamp receipts manually.
070 corrects decision snapshot minimization; it must accompany 069 completion.
071 removes the temporary physical/digital release gates; apply it before using
the matching API/WebUI code. No separate database enablement is required.
The populated 050–071 rehearsal verifies schema parity and preservation of
existing rows, fields, grants and history, rather than assuming a fresh install
proves an upgrade.

Run the separate, idempotent feature seeds after schema upgrade; these are not
migrations and use `seeding` event source:

```sh
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f database/seeds/messaging.sql
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f database/seeds/hold-notification-producers.sql
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f database/seeds/relationship-types.sql
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f database/seeds/disposition-notification-producers.sql
```

Preserve existing configured settings, role/profile assignments, evidence,
template revisions and immutable history. These commands do not reset them.

## 3. Preview, review, apply and verify local settings per database

Keep services stopped. `source-env` is the existing private legacy file; it is
read, never overwritten. Choose a **new**, private plan pathname for each target
and each revision. Substitute an existing active person ID who currently holds
`app.settings.manage`; a generic service account is not the migration actor.

```sh
backend/services/api/.venv/bin/python tools/migrate_application_settings.py \
  --preview --database-url "$DATABASE_URL" --source-env .env \
  --plan /tmp/erms-settings-db-a-review-1.json

backend/services/api/.venv/bin/python tools/migrate_application_settings.py \
  --apply --database-url "$DATABASE_URL" --source-env .env \
  --plan /tmp/erms-settings-db-a-review-1.json --actor-user-id 123 \
  --reason 'Reviewed configuration migration for the selected database'

backend/services/api/.venv/bin/python tools/migrate_application_settings.py \
  --check --database-url "$DATABASE_URL" --source-env .env
```

Preview's nonzero status and `issues` require resolution, not `--apply` anyway.
Invalid legacy values can be corrected in the source and previewed again, or
explicitly kept with `--keep-database KEY`. Configured-value conflicts require
`--keep-database KEY` or `--use-legacy KEY` on the **new preview**; the latter uses
the governed change path. Review every proposed value, provenance, issue and
obsolete key. A source meaning, target or unfinished row/version change makes a
plan stale; preview again. Plans are target-bound: never copy A's plan to B.
The preview contains non-secret configuration; still keep it private.

Repeat schema review, separate preview/apply/check and value verification after
selecting database B, C, etc. Even when the databases share a legacy file, each
has its own logical identity, configured values and migration completion.
Completed keys do not reimport later environment edits or overwrite subsequent
Settings changes. An already applied plan can be safely rerun against its own
completed target. This does not imply arbitrary schema migrations can be replayed.

The reviewed import covers 34 existing general/interface, content,
authentication and search keys. It does not import SMTP credentials or disposition
destinations. `WEBUI_FULL_TEXT_SEARCH_ENABLED` is obsolete, never imported; the
API-owned `FULL_TEXT_SEARCH_ENABLED` is authoritative. See the full key inventory,
conflict rules and startup semantics in [application-settings-upgrade.md](application-settings-upgrade.md).
Only after **all intended databases** report ready and their values are verified
may the operator manually remove reported obsolete business keys from the
legacy file. Keep deployment-owned variables, messaging settings and the API
encryption key. Never remove the file wholesale or let a startup script perform
an automatic business-settings import.

## 4. Fresh installation alternative

Use this path only on a newly created empty database, after deployment approval:

```sh
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -f database/schema.sql
backend/services/api/.venv/bin/python -m backend.services.api.manage_auth bootstrap \
  --name 'Initial administrator' --email 'administrator@example.invalid'
```

Replace the sample identity with the agreed administrator. The bootstrap command
displays a temporary password once: keep it private, deliver it through the
established secure process, and change it at first sign-in. Do not bootstrap an
already provisioned database. Run the separate seeds from section 2. A fresh
canonical database with no applicable legacy keys is ready without an import;
when the local legacy file includes those keys, use the explicit per-database
preview/apply/check procedure even for a fresh database.

For either path, seed the checked-in language drafts explicitly:

```sh
PYTHONPATH=. backend/services/api/.venv/bin/python \
  database/seeds/004_seed_generated_arabic_ui_translations.py --database-url "$DATABASE_URL"
```

This preserves protected database translations; it does not silently promote
an administrator export or authorize publication. Review seed results. If newer
administrator edits exist only in a database, deliberately export/promote them
before replacing the canonical artifact. Current English/Arabic have 3735 keys;
531 machine candidates remain subject to human review. Phase 23 corrected seven
unreviewed glossary values and preserved curated entries/provenance.

## 5. Operational setup, startup and recovery

After installation/migration, use the Operations documentation as the primary
reference for ongoing operation:

- [Initial disposition/destruction setup and configuration](operations.md#141-initial-setup-and-configuration): roles, classifications, open evidence/report roots, route/reminder settings, SMTP and encryption key.
- [Worker startup and verification](operations.md#142-worker-startup-and-verification): the three dedicated processes, service units, readiness checks and restart behavior.
- [Operator recovery and rollback](operations.md#143-recovery-and-rollback): blocked tasks, SMTP uncertainty, durable work, certificate-only retries and irreversible destruction.

After migration 071 there are no temporary execution gates. Destruction is
available subject to the existing permissions, approvals, workflow checks and
explicit confirmations; applying this upgrade does not perform destruction.
Persistent deployment still requires operator authorization.
