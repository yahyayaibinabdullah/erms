# Application Settings reference audit correction

User-approved requirement (14 October 2026): when a reference setting changes,
persist its readable code and name in the event metadata alongside its ID.
This extends the ACFG section 8 / ACFG-07 durable old/new-value evidence for
the disposition scheme and both destination classifications.

| Requirement | Implementation | Passing evidence |
| --- | --- | --- |
| Uploaded evidence and generated reports changes record readable old/new identities | `audit_application_setting()` in `database/schema.sql` and migration `052_application_settings_reference_audit.sql` reuse `event_reference_identity` | `test_destination_audit_snapshots_survive_rename_clear_and_deletion`, both destination keys on fresh and upgraded schemas |
| Scheme changes also have readable identity evidence | Same trigger resolves scheme identities through the existing helper | `test_scheme_audit_has_immutable_code_and_title_snapshots` |
| Snapshots survive later entity changes and null clearing | Metadata contains `old_reference` / `new_reference`, each `{id, code, title}` or null, in the setting update transaction; numeric `old_value` / `new_value` retained | Both tests verify original snapshots after renames; destination tests verify clearing and subsequent deletion |
| Upgrade preserves configured values and immutable history, and can be rerun | Migration 052 replaces only the trigger function and registers its version; migration 050 stays unchanged; canonical schema includes the latest definition directly | Upgrade cases run 052 twice and compare existing history/setting rows; schema/cache DDL parity test verifies the latest function matches 052 |
| Secret values remain excluded and audit failures remain atomic | Existing SMTP secret branch and transaction behavior retained | Existing encrypted-password audit-redaction, audit-failure rollback, grouped-update/concurrency and authorization regressions |

`title` is the classification/scheme's canonical name, matching the repository's
existing audit identity snapshots. No live lookup is needed when reading an
event. Existing events are not backfilled: current names cannot establish their
historical names. No frontend rendering, catalogue, environment variable or
privilege change is required.

The complete Settings API/database suite passes **31 tests** (two existing
dependency deprecation warnings). Schema/cache checks pass **15 tests**. API
environment synchronization and whitespace checks pass. Initial new fixture
failures were corrected by supplying the required terminal retention rule and
using an unpublished scheme for the deletion case; product constraints were
preserved.

Three uniquely named disposable databases were created from the canonical
schema and separate seeds, then dropped; final read-only PostgreSQL catalogue
inspection confirmed all are absent:

- `erms_messaging_test_acl_51b6da6fab3740ac836de94d881f88ca`
- `erms_messaging_test_acl_7629d9b435364a0e99f6d13080ca1baf`
- `erms_messaging_test_acl_02fabdcbf4fe4eabac55cbba9dac2c6d`

Migration 052 was applied and verified on **demo**, under the user's existing
pending-migration authorization. All Settings rows, audit row count/max ID and
the latest 200 event metadata rows were identical before and after deployment.
The former function definition and deployment report are private files under
`/private/tmp/erms-settings-audit-upgrade-e79rp0vp/` (directory 0700, files 0600).
No test suite targeted demo. The trigger change takes effect immediately for
subsequent events and requires no application restart.
