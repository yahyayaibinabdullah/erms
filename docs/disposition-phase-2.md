# Disposition Phase 2 implementation and verification

The later user-approved readable Settings audit snapshots and migration 052 are
documented in [reference audit verification](application-settings-reference-audit.md).
Original completion evidence and hours below remain unchanged.

Phase 2 supplies the shared application-settings foundation: a closed registry
of 51 database settings, protected administration API, canonical/upgrade SQL,
safe audit, provenance/completion, non-secret cache, and fresh operation-capture
helpers. The user approved environment storage for the encryption key on
14 October 2026; SMTP passwords remain encrypted database settings. The approval
is reconciled in Application Configuration revision 1.2 and the maintained
[requirement ledger](disposition-requirement-ledger.json).

Measured session: 2026-10-14 05:52:04 to 2026-10-14 07:21:03 UTC
(1.48 active hours; no excluded idle interval was recorded). Final
completion bookkeeping follows this captured end boundary.

## Implementation and requirement evidence

| Phase 2 contract | Implementation | Passing verification |
| --- | --- | --- |
| ACFG sections 5.1–5.7 and 7; ACFG-01/04; ADMIN sections 2–4; DEST-40 settings foundation | `application_settings_registry.py`: 51 immutable definitions, seven explicit categories, exact defaults/types/limits, editable business keys, metadata keys, complete destination/SMTP groups. Canonical SQL and independent migration 050 repeat identical settings DDL. No category column or prefix-based category inference. | `test_exact_registry_defaults_and_protected_public_metadata`, invalid-setting cases, `test_registry_is_complete_explicit_editable_and_defaults_are_valid`, `test_canonical_and_upgrade_settings_ddl_are_identical_except_installation_kind` |
| ACFG section 8; ACFG-07/09/12; security supporting contracts; DISP section 15 audit compatibility | `application_settings_routes.py`: explicit GET/PUT models, current `app.settings.manage` authorization, nonblank reason, all expected versions, bounded metadata reads. SQL locks rows in stable order, validates groups and records safe immutable domain events in the same transaction. Canonical/migration grants use SYS_ADMIN and existing ALL_PRIVS compatibility. No generic settings CRUD route. | Authority/unknown/deployment-key/validation-response negatives; `test_configured_default_provenance_versions_atomic_audit_and_conflict`; destination/SMTP group rejection; `test_audit_failure_rolls_back_group_and_migration_completion`; concurrent administrator test; policy/privilege regressions |
| ACFG sections 5.7 and 7; ACFG-13; ADMIN section 4; DEST sections 3 and 11.4 secret foundation | `application_settings_secret.py`: authenticated Fernet encryption bound to database ID and SMTP_PASSWORD; deployment key never enters DB/API. Password JSON remains null, encrypted bytes are server-only, public models expose only set-state, audit excludes plaintext and ciphertext, ordinary snapshots exclude both. Missing/wrong key fails credential replacement/resolution safely. | `test_encrypted_password_is_write_only_and_send_capture_is_fresh`, missing-key grouped rollback, authenticated tamper/wrong-key/cross-database tests, shell-over-dotenv and append-only private-file tests |
| ACFG sections 6 and 6.1; ACFG-05/06/14 foundation | `application_settings.py`: complete validated immutable non-secret snapshot; 30-second TTL from load completion; process lock and database isolation; post-commit local invalidation; safe last-valid refresh fallback. Job/artifact/email helpers use one current committed query through a separate transaction, bypassing cache and older repeatable-read transactions. Captured settings are immutable; no stale fallback at those boundaries. | Controlled-clock TTL/convergence, reload single flight, database isolation, safe refresh failure, fresh operation and actual repeatable-read tests; password/recipient changes affect only subsequent captures |
| ACFG sections 9, 9.2 and 10.1; ACFG-03/16/17 foundation | SQL provenance distinguishes untouched defaults from explicit configured defaults. Migration completion is per database, migration and key, guarded and atomic with values/audit. Completed reruns skip finished keys; additional keys can migrate; conflicts preserve configured values. Startup reads/validates canonical rows and never seeds/imports settings. | Fresh and pre-settings-baseline upgrade suites; idempotent 050 rerun preserves configured values; configured-default conflict and completion rollback; migration-versus-admin race; missing canonical row rejects startup; startup succeeds with optional settings and encryption key unset |
| ACFG section 4.3 amendment; ACFG-10 deployment subset; approved local reconciliation | `APPLICATION_SETTINGS_ENCRYPTION_KEY` is API-only deployment configuration, optional until credential replacement/resolution, shell environment wins, API restart required. Authoritative API template and generated root API copy agree; root local template documents optional initialization. Existing private values are preserved. | Environment precedence, local initialization/permissions/idempotence; `sync_api_env_template.py --check`; private-file reconciliation regressions |
| ACFG-11 metadata subset; ADMIN section 2; i18n sections 7.5/7.8/21.1 | Added 118 contextual English/Arabic keys: 109 registry labels/descriptions/categories, seven safe errors, two privilege texts. English sorted; Arabic exact same order. All 3,023 previous Arabic items preserve text and provenance. New items have per-item generation/model/prompt/time/batch/source hashes and remain generated drafts. Published preferred-language metadata uses English fallback for drafts. | Preferred-language/publication fallback API test; all 3,141 active keys match, placeholders/nonblank text/terminology/provenance/hashes pass; new drafts pass generation validation; translation import/export/seed/publication regression suite passes |

Exact implementation locations, test selectors, phase-scoped results and source
hashes are attached to each applicable ledger entry. Multi-phase requirements
remain **in progress**: passing foundation evidence does not mark their later UI,
consumer, or workflow clauses complete. ACFG section 10.1, owned solely by Phase 2,
has implementation and passing schema/migration evidence.

## Verification runs and database lifecycle

The final fresh-schema suite passed 80 checks, and the final upgrade suite passed
82 checks. Both include settings API, policy inventory, global privileges, and
translation catalogue regressions. Upgrade initialization used canonical SQL
from `fd90a426ef3dd318fcafe89f147748163ec33831` followed by migration 050. The
extra upgrade checks exercise a migration/configuration race and fail-closed
startup; both also run against the latest fresh schema in the compatibility run.

- Fresh database: `erms_messaging_test_acl_8371e08cc67141b28d697fe24f6724a1`.
- Upgrade database: `erms_messaging_test_acl_2584078f44174c3ab520ed9b6ffa8013`.
- Both were created specifically for their run and dropped with `WITH (FORCE)`.
- Database-free settings/cache/encryption/DDL checks: 22 passed.
- Existing frontend authorization/translation/bounded-collection checks: 16 passed.
- Traceability and private-environment reconciliation checks: 27 passed.
- Existing records-management compatibility plus both new fresh-schema controls:
  105 passed in `erms_messaging_test_acl_289aa539b0b045daa57915919f741eea`.
- Persistent-target fixture guard: one passed in
  `erms_messaging_test_acl_4361af84928444ba8ad32a7212f48ae9`; a fake persistent
  target is rejected before API startup. Both databases were created and dropped.

The database runner explicitly overrides the encryption key to empty at startup;
credential tests use ephemeral fixture keys. No test runs against a persistent
ERMS database. Earlier failing development attempts also created and dropped
their disposable databases; final runs resolve those failures. Existing
Starlette/httpx and anyio deprecation warnings remain unchanged.

Catalogue checks preserve every existing item by `message_key`, validate only
new machine drafts with the draft generator, and check the complete artifact's
active-key order, placeholders, nonblank values, approved glossary and root hashes.
The legacy draft generator's older terminology/Latin heuristics are not applied
to administrator-curated wording; the maintained 29-entry approved glossary
checker verifies all 684 contextual uses. No curated wording is regenerated.
New drafts require explicit administrator review/publication through the existing
workflow; they are not published during startup or migration. No generic seed
utility is changed.

## Deployment and remaining phases

Follow [application settings upgrade guidance](application-settings-upgrade.md)
for migration 050, API dependency installation, the shared production environment
key, and API restart. A missing local key has been generated and appended without
printing it or changing existing private values. Persistent development and
production databases have not been migrated during implementation.

Phase 3 delivers the Settings page and configuration warnings, including live
LTR/RTL, table and navigation verification. Phases 4–6 supply the explicit reviewed
legacy migration command, readiness checks and consumer cutovers. Existing
environment-backed consumers/templates remain until their assigned cutover.
Later disposition phases connect the fresh captures to actual jobs/artifacts and
email attempts; Phase 18 implements verified SMTP transport. No disposition job,
destruction, transfer, notification producer, or document-send workflow is added
by this foundation. D-01 remains a Phase 21 policy gate only.

Policy inventory generation also reconciles already-approved relationship routes
and catalogue metadata that previously existed in SQL/committed route inventory
but were missing from generator/seed metadata. This introduces no new relationship
authority or profile grant.
