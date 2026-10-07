# Hierarchical oversight ACL implementation and verification

This implements revision 1.5 of the Organizational Ownership and Default ACLs
specification and the Hierarchical Oversight Default ACLs extension. It does
not implement disposition or destruction workflows.

## Implementation

- `database/schema.sql` includes nullable `org_units.managing_role_id` and
  `org_units.file_administrator_role_id`, same-unit designation checks,
  protected role references, contextual principal constraints in all four ACL
  tables, and current-data authorization functions.
- Migration `048_hierarchical_oversight_acls.sql` upgrades an existing database.
  It does not insert, delete, or update existing ACL grants. New databases use
  the canonical schema alone; do not run this migration on a new database.
- New creator-role defaults omit ACL management. New contextual grants have
  NULL role IDs and the exact permission sets in the approved specifications.
  Effective inherited ACLs still take precedence over dormant local defaults.
- API and WebUI organization-unit editors expose the two role designations.
  The existing organization-administration privilege, optimistic concurrency,
  and immutable history govern updates. Role selection searches the current
  unit with bounded requests and retains selected values.
- ACL editors support adding and removing the two principals, require the
  existing change reason and version checks, and explain their current owner.
  Current-role details are server-paged and require organization browsing as
  well as resource ACL-management authorization. Closed or superseded dialog
  responses are ignored.
- Access explanations identify matched principal, real role and unit alongside
  the existing privilege, clearance and resource-state checks. Ownership move
  previews warn that contextual matching users can change.

No authorization cache was added. Every authoritative decision resolves the
current resource owner, hierarchy, designations, active roles and assignments
from PostgreSQL. Independent authorization gates are unchanged.

## Requirement-to-test map

The named tests below are in
`backend/services/api/tests/test_hierarchical_oversight_acls.py` unless noted.
Existing resource ACL, ownership, mutation authorization and governance suites
continue to verify the surrounding behavior.

| Requirement | Implementation and verification |
|---|---|
| HACL-01–03 | Prospective SQL initializer and all four ACL scopes; `test_exact_prospective_defaults_and_null_role_ids`, `test_dormant_defaults_do_not_override_live_parent_policy`; revised phase-6 exact-set tests |
| HACL-04 | Designation validation, role protection, ordinary versioned organization-unit updates; `test_designations_same_unit_governed_versioned_and_audited`, `test_designated_role_integrity_and_protected_delete`, `test_designated_role_delete_preflight_requires_configuration_removal` |
| HACL-05 | Current owning-unit and ancestor manager resolution; `test_manager_matches_owning_unit_and_ancestors_with_current_assignments` |
| HACL-06 | Nearest configured File Administrator, no fallback past unusable configuration; `test_file_administrator_nearest_configured_role_without_inactive_fallback` |
| HACL-07 | Existing independent gates; `test_contextual_grants_do_not_bypass_other_gates`, existing phase-7 and phase-9 authorization regressions |
| HACL-08 | No new authorization cache; current-data SQL evaluation; assignment, inactivity, reparenting, configuration clearing and ownership tests above |
| HACL-09 | Existing ACL replacement, versions and history; `test_api_removal_version_history_and_no_automatic_recreation` |
| HACL-10 | Move preview and current target ownership; `test_ownership_move_previews_and_resolves_contextual_access_without_copying_roles`, existing ownership move tests |
| HACL-11 | API schemas, constraint checks, bounded disclosure, ACL editor and explanation; `test_explanations_identify_contextual_role_and_bounded_disclosure`, `test_database_rejects_duplicate_or_anchored_contextual_grants`; four WebUI oversight tests and live LTR/RTL checks |
| HACL-12 | Prospective-only migration; `test_upgrade_preserves_every_existing_acl_grant_and_changes_only_future_defaults` compares all four ACL tables exactly in an additional disposable populated predecessor database |

## Verification procedure

Verified on 7 October 2026: 55 focused ACL, defaults, migration and policy tests;
45 surrounding global and mutation authorization tests; and all 423 frontend
tests passed. The final complete API suite passed all 740 tests in three
independent disposable database shards (339, 257 and 144 tests). All databases,
including the separate browser-verification database, were cleaned up.
The frontend tests also verify catalogue ordering, hashes,
placeholder coverage and preservation of the existing Arabic translation rows.
Live browser checks passed in English LTR and Arabic RTL.

Run API regressions with:

```sh
backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py backend/services/api/tests -q
```

For the three independent runs used in final verification, replace the test
directory argument with `--shard=1/3`, `--shard=2/3`, or `--shard=3/3`. Together
these runs cover every API test file, with a separate database per run.

The runner creates a uniquely named disposable database, initializes it from
the canonical schema, applies the separately maintained messaging test seeds,
runs pytest, and drops the database even on failure. No persistent database is
used. The migration preservation test separately creates and cleans up its
own disposable database.

Frontend regressions run with:

```sh
frontend/webui/.venv/bin/python -m pytest frontend/webui/tests -q
```

Live browser checks use a separate disposable database and temporary login
storage: existing styled ACL matrix, prospective permission differences,
current-role dialogs, repeat opening, and LTR/RTL direction and layout.

## Translation and deployment notes

Sixteen English keys and matching Arabic drafts were added. Both catalogues
have the same sorted key order. Existing Arabic wording and provenance are
preserved; catalogue hashes and contextual placeholders are verified by tests.
The new Arabic drafts still require the normal human review/publication
workflow before deployment. Publication in a disposable browser fixture is
not production approval.

No persistent database migration or ACL backfill was performed. Deploying this
change requires applying migration 048 to the intended existing database and
configuring the designated roles through normal authorized administration.
Existing grants, including existing creator ACL-management grants, remain
unchanged.
