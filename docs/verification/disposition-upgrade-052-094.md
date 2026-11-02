# Upgrade from pre-merge 052 through 094 — 2 November 2026

**Result:** all 42 migration files apply successfully. The upgraded schema and
demo have matching object counts and reviewed rules/definitions, but they are
**not exactly identical**. No reconciliation was silently applied to either
schema to make the comparison pass.

## Source and execution

- Loaded the original `database/schema.sql` from commit
  `4885a15767d797fea61762eec83b37b00f8cd5f1`, the first parent of merge PR #61.
  Its greatest recorded migration was verified as 052 before any upgrade.
- Created the unique disposable database
  `erms_upgrade_052_094_d4a9168bc164419995330ca5a2dc38d0` on the same PostgreSQL
  18.4 server as demo, using matching UTF-8/libc/en_US.UTF-8 database locale
  settings so intentional locale differences did not affect the comparison.
- Applied each current-checkout SQL file from 053 through 094, strictly in
  numeric order, including the corrected 079. All 42 succeeded and all 42
  upgrade history markers were present afterward.
- Compared PostgreSQL schema-only dumps using the same pg_dump 18.4 binary,
  excluding object ownership and pg_dump's randomized client guard tokens.
  Demo was used only as a read-only schema reference, never as a test target.
- Dropped the disposable database successfully in the verification's cleanup.

## Findings

| Objects | Upgraded database | Demo |
| --- | ---: | ---: |
| Tables | 128 | 128 |
| Views | 6 | 6 |
| Non-extension functions | 335 | 335 |
| User-defined triggers | 312 | 312 |

The raw dump comparison has 640 diff lines. Inspection accounts for every
difference:

- **29 constraint names** differ across `supported_languages`,
  `ui_message_definitions`, `ui_message_translations` and `user_preferences`.
  Their actual check expressions match.
- **Three physical column orders** differ: `org_units`, `roles` and `users`.
  Their named columns, data types, defaults, generated expressions and nullability
  match. This is an observable schema difference for positional SQL and
  `SELECT *`; it is not erased from the comparison.
- **17 function bodies** have different textual representations. Fourteen match
  after preserving literals/operators and comparing tokens without insignificant
  whitespace, keyword case or optional final semicolons. Two location-source
  functions additionally use consistently renamed local CTE aliases and optional
  `AS`; the entity-history function also uses optional `AS` for its identical
  `key`/`differences` aliases. Those specific syntax differences were inspected
  explicitly rather than broadly discarding identifiers or alias syntax.
- All other schema statements match after insignificant whitespace/comment/case
  normalization. There are no remaining unexplained differences in this
  comparison, including indexes, views, triggers, grants and other constraints.

The comparison therefore demonstrates a successful 052→094 migration path,
but must not be reported as exact schema equality. Inherited naming/order/text
differences require a separately considered reconciliation if exact identity is
required; none of demo's objects were rebuilt or altered for this test.

## Evidence and scope

[The machine-readable report](disposition-upgrade-052-094.json) records the pinned
baseline hash, all 42 migration hashes, locale, object counts, exact dump hashes,
every differing constraint name/function/table column order, and cleanup result.
Private full schema dumps, the raw diff and execution/comparison scripts remain
under gitignored `.runtime/upgrade-052-094/`.

This is **schema upgrade verification**, using only reference data bundled with
the historical 052 schema. It does not assert that colleagues' tenant data is
identical to demo, or exercise SA retention-policy updates against populated
classification trees. It does not replace a populated-database rehearsal or
test administrator-customized profile conflicts. No database-backed test suite
was run against demo, and no migration or application setting was applied there.
