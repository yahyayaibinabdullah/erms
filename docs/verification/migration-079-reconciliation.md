# Migration 079 bookkeeping and replay safety — 2 November 2026

The original migration 079 changed the admission reason contract but omitted its
`schema_migrations` entry. Its existing effect in demo had subsequently been
extended by 084 to permit claiming a task without entering a reason. Blindly
replaying the old 079 would replace that newer function and receipt constraint.

## Correction

- The corrected 079 records its version atomically and skips an already
  recorded version. An older schema receives the original admission change.
- When 084 is recorded, or the function already expresses its reason-free claim
  contract, 079 verifies that superseding function and the validated constraint.
  It evaluates the constraint against synthetic scalar values (no business rows)
  to check blank reasons for job creation, membership addition and claiming,
  valid nonblank review reasons, and rejection of blank exceptional reasons.
  It then inserts only the missing history entry, preserving the exact current
  function and constraint. Detected drift raises an exception without recording
  success or replacing newer code.
- The fresh-install baseline now includes 079. `schema.sql` is unchanged and
  still does not execute migrations. No automatic migration application was
  added to the local launcher.

## Verification

The official disposable runner created
`erms_messaging_test_acl_32c7992c427042beaba955277280d10f`, initialized the current
canonical schema/reference data/baseline, and ran:

```bash
backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py \
  tools/tests/test_migration_079.py tools/tests/test_canonical_schema.py
```

All **50 checks passed**. Coverage includes an older reason contract followed by
079 then 084 then repeat 079; an updated database missing 079's marker; recognition
of newer behavior even if the 084 marker is absent; exact function/constraint and
other-history preservation; duplicate prevention; refusal of restrictive or
overly permissive constraint drift and function drift; and canonical baseline
separation. The disposable database was dropped successfully. These tests were
not run against demo or any persistent database.

## Authorized demo reconciliation

The corrected full SQL script was then applied to demo at
**2026-11-02 14:07:47 +04**. Its current post-084 branch inserted the missing
079 history entry only. Before/after checks confirmed the complete stored
function and constraint definitions were identical and every other migration
version/timestamp was preserved. Private operational snapshots remain in
gitignored `.runtime/migration-079-reconciliation/`.

Migration 073 was deliberately not applied as part of this authorization.
Its intended action is to promote the matching existing FILE_ADMIN profile to
`is_system=true`, preserving its assignments and privileges. Demo's existing
profile remains `is_system=false` because that promotion is still pending; 073
does not set it to false. At that checkpoint it was the sole remaining
unrecorded migration file.

### Subsequent authorized 073 promotion

The user subsequently authorized applying 073 to demo. Before doing so,
`tools/verify_file_administrator_profile.py` passed canonical provisioning,
dependencies, repeat application, promotion, conflict rollback and absent-profile
upgrade checks in `erms_test_file_admin_44a1db32ba724436ad8df109ed1e0df5`, then
dropped that disposable database. The exact 073 transaction body was applied
atomically to demo with before/after assertions before commit. Profile ID 9 now
has `is_system=true`; all 34 privilege assignments, role rows, user-role
assignments and profile translations were preserved. All 94 migration files
now have matching entries in demo's history. Operational snapshots are private
under `.runtime/migration-073-promotion/`. For new installations, the FILE_ADMIN
row with `is_system=true` comes from `000_required_reference_data.sql`;
`schema.sql` only defines the table and its default false for ordinary profiles.

## Colleagues

Syncing forks does not modify their databases. When an explicit upgrade or
reconciliation is needed, use the corrected 079 from this checkout and apply
remaining upgrades in order. The old 079 must not be replayed after 084. The
corrected file safely reconciles an intact newer schema, and fails for review
if its expected superseding contract cannot be verified. No application restart,
environment change, privilege change or new product behavior is introduced.
