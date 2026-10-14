# Disposition Phase 5 implementation and verification

Phase 5 cuts over the seven content/document-viewing settings and eight
authentication/session settings in Application Configuration sections 5.2–5.3.
It extends the existing reviewed migration to 24 keys (nine Phase 4 plus these
15), retaining the same migration identity and per-database/per-key completion.
Search/indexing policy remains Phase 6 work.

## Requirement evidence

| Approved contract | Implementation | Passing verification |
| --- | --- | --- |
| ACFG 5.2/10.3; storage supporting sections | `content_storage.py` receives one validated policy snapshot for inspection and storage, including drafts/replacement and messaging capture. Upload limit, segment size/checksums and session lifetime are database-only. Original whole-file checksums and stored segment representation remain intact. | `test_content_snapshot_boundaries_checksums_ttl_and_runtime_change`; segmented/range and real 200 MiB upload/reconstruction regressions; draft promotion, replacement, download, content authorization and cleanup tests. |
| ACFG 5.2/10.3 | `document_conversion.py` takes explicit settings for both preparation and conversion. API source-size guard uses the same snapshot. LibreOffice path remains deployment-owned. | Conversion format/intermediary regressions, preparation timeout, runtime timeout and exact rendition-size boundary/rejection; unsupported originals remain downloadable. |
| ACFG 5.3/10.3; authentication supporting sections | Login/lockout/password changes use the shared cache. Session evaluation applies current idle/absolute durations from last activity/creation, persists shortened expiry, and never revives a previously expired/revoked session. Row locking prevents competing evaluations from undoing expiry. Unchanged session timestamps do not cause writes; the existing one-minute activity-write cadence is retained. | `test_active_session_uses_new_idle_absolute_policy_and_expired_never_revives`, both shortened-lifetime cases, runtime lockout/password test, existing lifecycle/CSRF/audit/authorization/session tests. |
| ACFG 5.3 password treatment | Existing hashes remain usable after a minimum-length increase. New/changed passwords are validated against current policy. API temporary passwords and offline bootstrap/recovery generation satisfy the database minimum. The low-level hasher accepts already validated passwords or explicit seed fixtures. | `test_lockout_and_new_password_policy_refresh_preserves_existing_hash`, `test_temporary_password_api_and_recovery_use_database_minimum`, existing bootstrap/recovery and temporary-credential regressions. |
| ACFG 10.4; authentication/storage cleanup contracts | One-shot workers load one fresh validated snapshot. Watch passes use the same 30-second cache and re-evaluate defaults before each pass. Explicit flags override only that invocation. Standalone workers reject an unreviewed upgrade. Advisory locks, bounded batches, dry-run rollback and terminal audit are retained. | Content worker interval/override/load-failure test; session retention/batch/interval/override/load-failure test; standalone worker readiness before/after governed completion; existing cleanup audit/batch regressions. |
| ACFG 9–9.3; ACFG-03/16/17 | Same offline preview/apply command, explicit target/source/actor/reason, conflict/version safeguards and atomic values/audit/completion. Boolean parsing is added for the content checksum key. Completed general/content keys are preserved when later groups are added. | Content/auth migration-extension tests plus all 11 Phase 4 migration/readiness/runtime regressions using the expanded inventory. |
| ACFG 4.3/10.7; ACFG-02/10 | All 15 environment readers and root/API template assignments removed; authoritative API template regenerated. Storage backend, cookie security and LibreOffice path retain deployment ownership. Private `.env` unchanged. | Source-reader/template reconciliation, 46-setting API template check, syntax/policy/traceability checks. WebUI/text-indexer templates have no Phase 5 consumers and remain unchanged. |

Valid very large duration/retention settings do not overflow Python/PostgreSQL
arithmetic. Future expiries saturate to a representable distant date, with enough
room for timezone conversion; retention saturates at the earliest representable
cutoff. No registry upper bound is added. Login idle expiry is capped by absolute
expiry even when the configured idle duration is longer.

## Runs and lifecycle

The content change passed its own **37-test** regression run before authentication
implementation started. It included real large-file storage, conversion, draft,
content authorization, migration and runtime checks. Database
`erms_messaging_test_acl_fd5b3ce0a29648a6abf69f90cefae79b` was created and dropped.

The broader content/authentication/settings/migration/API/content-authorization
run passed **132 tests**, with two existing dependency deprecation warnings,
in 120.53 seconds. Database
`erms_messaging_test_acl_9958df9fa69a4b5a8a6856df2e5acb39` and isolation database
`erms_messaging_test_acl_92d1bfc0298b4835b8e0725468f87630` were created and dropped.
A subsequent boundary/authentication run passed **28 tests** in 21.51 seconds;
its database `erms_messaging_test_acl_277220be9f7f4827981d1600a222e655` was dropped.
Final worker-readiness/Phase 4/Phase 5 run passed **25 tests** in 28.16 seconds.
Database `erms_messaging_test_acl_0b141ca653b34f6ab170fbcbdd1496a3` and isolation
database `erms_messaging_test_acl_b96d2a7d36aa46519abc182498468f2a` were dropped.

WebUI API client, sign-in feedback, authorization and session-isolation tests:
**84 passed** in 1.12 seconds. Cache, CLI safety and private-file reconciliation:
**20 passed** in 0.13 seconds. These runs do not use a database.

Two earlier runs found issues that were corrected: an existing credential-lock
Settings authorization gate required the fixture to simulate lock expiry
(62 passed/one failed), and the extreme-date fixture exposed timezone conversion
past year 9999 (12 passed/one failed). Their databases
`erms_messaging_test_acl_92e5dbc1d0e34cfba3eab5a04de88a61` and
`erms_messaging_test_acl_e83907d1144b4b4d9f50877f1d6acd41`, plus isolation database
`erms_messaging_test_acl_5db69b5db5fd4f6da8f4f7083ad59b02`, were dropped.
The existing authorization gate was preserved. Date saturation now retains
room for conversion to the deployment/user timezone.

Every database-backed test uses a unique disposable database initialized from
`database/schema.sql` alone and separate seeds. No persistent database was
initialized, tested, seeded, migrated or changed. No production email was sent.

## Cache, UI and deployment

The existing API cache is reused without adding another cache: scope is one
logical database/process, keys are registry setting keys, TTL is 30 seconds from
successful load completion, and local successful saves invalidate after commit.
Refresh failure can retain only a previous fully validated snapshot. Initial
request/worker load failure stops the operation; one-shot worker reads have no
stale fallback. Migration/readiness completion is read directly. No credentials,
user identity, language rendering or partial settings enter the cache. Explicit
snapshots keep upload/conversion decisions consistent throughout one operation.

Phase 5 adds no WebUI controls, text, translation keys or artifact changes. The
existing bilingual Settings editor supplies these already registered keys. Its
personal preference, page/configuration isolation and presentation remain as
verified in Phase 4; the WebUI regressions above cover login/session integration.
All 3,188 Arabic items and their provenance remain intact. Existing Phase 3
translation drafts still require explicit administrator review/publication.

Before deploying this code, stop affected services and review/apply a **new
24-key preview** using [application-settings-upgrade.md](application-settings-upgrade.md).
A completed Phase 4 migration does not complete the 15 new keys; it does protect
its existing values from later legacy edits. Upgrade API startup and standalone
cleanup workers fail closed until all active keys are completed. Fresh databases
without legacy entries use canonical defaults. Local launcher legacy-file review
rules still apply. Restart API/workers to load code; subsequent settings changes
use the shared cache without restart. Cleanup flags remain deliberate overrides.
No new environment variable, database schema migration or privilege is added.

Final traceability/cache/CLI/environment checks: **44 passed** in 1.25 seconds.
Catalogue references, 694 uses of 29 approved Arabic glossary mappings, complete
prior-item preservation, current operation-policy inventory, source syntax,
cleanup help and whitespace checks pass. Final read-only PostgreSQL catalogue
inspection confirms all nine Phase 5 run/isolation databases are absent.

Measured session: 14 October 2026, **12:15:58–12:33:52 UTC**, **0.30 active hours**,
with no excluded idle interval. Final completion bookkeeping follows this captured
end boundary.
