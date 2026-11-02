# Disposition Phase 8 implementation and verification

Phase 8 implements the bounded scheduled eligibility service and current common
blocker facts. PostgreSQL supplies the effective rule, UTC due instant and
comparison clock. Eligibility does not clear protections or execute disposition.
Job admission, recalculation hooks and operational job commands remain in Phase 9;
the listing/workspace remains in Phase 10; final execution remains closed.

## Requirement evidence

| Contract | Implementation | Passing verification |
| --- | --- | --- |
| DISP-03/04/05; §§3.4/7; retention precedence | `disposition_private.eligibility` reuses `aggregation_effective_retention_rule`, preserving local/nearest-classification provenance and the full rule-definition/version snapshot. UTC calendar arithmetic adds the sum of both periods and compares strictly later. | Four action mappings; exact one-microsecond before/equal/after boundary; leap years and summed periods in four database session zones; local override and inherited classification provenance; open roots; UTC worker audit instants. |
| DISP-06; §§7/16/17.1 | `disposition/eligibility.py` scans at most the requested batch, advances a server cursor, commits each root independently, retries transient serialization/deadlock failures and reports individual SQLSTATE failures. Root state and current policy are checked under locks. | Two workers change a root once; same-key retry returns its committed result; changed intent and human/GUC-only bypass rejected; interruption rolls back; invalid date/descendant failure leaves that whole unit unchanged while later roots succeed; policy/closure/reparent races. |
| DISP-08/09/10/18; §§9/9.1/9.3 | Current all-descendant vital, security-policy and effective direct/inherited hold facts; generic reasons survive resource redaction. Reads never change pending status, membership, evidence or approvals and never resume an action. | Root/descendant/record holds, half-open hold time boundaries, vital/security blockers, hidden record identity/name redaction, appearance/resolution while status 6 and membership history remain unchanged. |
| DISP-19; §9.2 | `lock_current_blockers` and `locked_summary` supply locked facts for later protected action commands. Hold policy, ordered resource rows, relevant security policies, relationships and membership use coordinated transaction locks. | Concurrent vital, hold, security flag, relationship and membership changes wait while the check is held; fresh facts reflect the committed protection/scope change after release. No irreversible command is introduced or tested as complete. |
| DISP-36; DEST-17; relationship §§5/7 | Both endpoint directions, every existing aggregation/record relationship type, descendant endpoints, and current active-job scope are checked. Same-unit and same-job links do not block; all outside-job links block only the final action. | All types in both directions; different jobs versus same job; internal links; removal refresh at both units; hidden endpoints retain a generic blocker without IDs or type details. |
| Referenced security, hold, medium, audit and performance contracts | Existing authorization/hold visibility predicates and relationship protections reused. Private SQL, no new privilege, typed human/automation receipts, exact version handling, bounded projections and an existing shared event-label map. | Current human governance role/root access; full-width resource versions; preserve-state hold still blocks ordinary edits; existing resource/relationship/hold/localization regressions; bounded 25-name hold preview with continuation indication. |

The shared SQL definitions are in standalone migration
`database/migrations/054_disposition_eligibility.sql` and an independent complete
copy in `database/schema.sql`. Migration 053 stays unchanged. Its parity checker
now isolates its historical section before 054; a separate Phase 8 checker
verifies the complete latest schema against the pre-054 upgrade path.

## Eligibility and retry boundary

The worker does not accept a caller-selected status or mutation clock. It
rechecks a closed governing root still at status 1, reads the database rule and
clock, and changes every descendant aggregation and record in one transaction.
Four retention actions map to 2, 3, 4 and 5; `selective_preservation` is preserved
as the existing policy value. Open roots are not candidates. The database
calculation uses UTC before calendar arithmetic, so a user's or connection's
working timezone cannot change the eligibility instant. Worker connections use
UTC, including captured JSON timestamps.

The automated receipt has no fabricated human or role. The private schema keeps
its no-PUBLIC-access boundary, and an automated receipt is valid only for
`eligibility_evaluate`. Human commands retain their prior attribution and
privilege checks. Only the eligibility entry point constructs this automated
context; resource guards restrict it to that root and disposition-only changes.
Receipts, full-unit state and immutable rule/date events commit together.
Repeated runs find the new status and make no new event or receipt. An exact
command-key retry returns the saved result. Failures roll back that root and
report its ID/SQLSTATE to the internal operator result, without raw errors or
credentials; remaining selected roots continue.

The internal full-unit function now accepts a `bigint` expected resource version,
matching the existing resource column rather than narrowing it to an integer.
A test verifies a version above three billion.

The preserve-state legal-hold guard has one narrow exception: an authorized
status-1-to-eligible update changing only disposition status/version. The
specification explicitly requires eligibility even under a hold. Every ordinary
metadata/content protection remains in the original function body. Admission
and final execution must still reject current blockers in their owning phases.

## Locking and current facts

Eligibility takes the existing disposition transaction advisory lock (7357,1),
short SHARE locks on retention-rule/classification policy tables, the existing
hold-policy shared lock, then ordered root/descendant/record row locks. Policy
locks cover direct SQL edits, including local-rule insertion and classification
hierarchy edits. This freezes the calculation inputs without downloading policy
or resource collections. Each root commits before the next root's transaction.

A protected current-blocker check takes the same disposition lock, the hold-policy
shared lock, ordered resource row locks and relevant security-level SHARE locks.
Membership commands already use that disposition lock. Relationship API mutations
now take it before endpoint locks, and before-statement database triggers cover
direct SQL writes to both relationship tables. Thus a newly introduced link or
membership-scope change cannot be missed by an action holding the check.
Database deadlocks/serialization aborts remain safe rollbacks; the eligibility
worker retries them at most three times and reports exhaustion. Later final-action
services must retain the locks through their specified final validation/commit
boundary and follow their own irreversible-work/recovery contract.

Read-only previews deliberately take no long-lived business locks. They query
current committed facts on each call and use existing resource/hold visibility
predicates. Resource and relationship pages fetch `LIMIT + 1` with server-side
pagination; concealed IDs are not put in cursors. Each resource exposes at most
25 visible hold names plus a continuation indication. The private hold preview
is capped at 26 IDs; its nonempty flag remains a complete blocker fact, not an
exhaustive authority to remove holds. Hidden resources expose only their kind
and generic vital/security/hold reasons. No cache is introduced.

Reopening or rule changes after a completed eligibility transaction still need
the Phase 9 recalculation hooks for already eligible/pending units. Phase 8 proves
that concurrent changes cannot produce a wrong status-1 transition; it does not
claim completion of those later lifecycle integrations, action commands or UI.
The existing WebUI calendar-only retention helper is not an eligibility source;
Phase 10 will display the server-calculated due instant.
Blocker-detection/resolution events at action attempts remain with their consumer
phases; existing protective/link changes retain their original immutable audit.

## Verification and cleanup

- Final canonical Phase 8 suite: **57 passed**, 49.64s, database
  `erms_messaging_test_acl_9332c21dd56640e1b3cf970c6835c4b3`.
- The same suite after independent 054 upgrade: **57 passed**, 49.72s, database
  `erms_messaging_test_acl_600048c0fefa41fd9d2617f33c8f7234`.
- Combined Phase 8 plus Phase 7 compatibility: **128 passed**, 116.52s,
  database `erms_messaging_test_acl_8d78fb8cd9b04f05b753879da4c56e7b`
  (53 earlier Phase 8 cases plus all 75 Phase 7 cases).
- Affected relationships, legal holds, medium/governance and complete localization
  catalogue regressions: **53 passed**, 48.38s, database
  `erms_messaging_test_acl_aa0016653cb64a83b608bffa49c0c037`.
- Fresh/upgrade catalogue and existing-data preservation passed in
  `erms_disposition8_test_fresh_9cdea438004547b2a500b47accd0897b` and
  `erms_disposition8_test_upgrade_809ef65c36464f6d833d759d5c9f4a35`.
  Columns/defaults, constraints, functions/ACLs, indexes, views, hold protection
  and relationship coordination triggers agree. Existing resources, jobs,
  human command receipts, users/roles, settings, grants and history are unchanged.
- **39** database-free traceability/cache checks and **3** shared audit-label/export
  checks passed. All 36 API environment settings remain synchronized. Catalogue
  reference/stale-key, terminology, ordering, coverage, placeholders/nonblank,
  provenance/hash, Python compilation and whitespace checks pass.
- API pytest runs report the two existing Starlette/AnyIO deprecation warnings.
  Initial type/audit-name and disposable-fixture issues were fixed before final
  acceptance; failed runs also dropped their databases. A final independent
  read-only PostgreSQL catalogue query confirmed all 20 Phase 8 disposable
  databases absent; the requirement ledger records this cleanup confirmation.

## Localization and operator handoff

`DISPOSITION_ELIGIBILITY_EVALUATED` and `DISPOSITION_STATUS_CHANGED` use the
existing shared readable audit-label mapping in English and Arabic, including
historical events. The two new contextual keys are
`audit.event.disposition_eligibility_evaluated` and
`audit.event.disposition_status_changed`. English and maintained Arabic now have
**3,194** identically ordered active keys. Every one of the prior **3,192** Arabic
entries and its complete provenance is unchanged. Only two missing generated
drafts were added, with separate model/batch/spec/catalogue/terminology metadata;
no administrator export was promoted. These two drafts need normal review and
publication after explicit seeding on a selected deployment database. No
persistent translation was seeded or published. No screen/layout/navigation,
per-user state, catalogue parsing path or runtime cache changed.

Apply missing 053, then 054 once before deploying the updated API/worker. A new
empty database still uses `database/schema.sql` alone, then separate seeds. No
new environment variable or template setting is introduced; shell environment
continues to override `.env` through the existing API environment loader.
Reload the API/WebUI when deploying the new message definitions and static
audit-label mappings; explicitly seed, review and publish the two new Arabic
drafts through the normal translation workflow. No service was restarted here.
The API-owned worker reuses `DATABASE_URL` and the existing deployment environment.
A one-shot bounded pass is:

```sh
backend/services/api/.venv/bin/python -m backend.services.api.disposition.eligibility --batch-size 100
```

For scheduling, the supplied
`backend/services/api/deploy/erms-disposition-eligibility.service` follows the
existing API worker service pattern and runs `--watch --batch-size 100
--interval-seconds 60`. The cursor advances across not-yet-due/failed roots and
wraps to revisit earlier roots; each pass is bounded and safe to restart.
These are process arguments, not additional application settings. Install/enable
it through the normal deployment procedure when introducing this service.
The schema migration neither starts the worker nor evaluates existing roots.
No persistent database, including `demo`, was migrated or tested, and no service
was installed or started on this machine.

Phase 9 implements operational job membership and changing eligibility.

Measured active session: 2026-10-15 04:30:35 UTC to 2026-10-15 05:04:59 UTC, **0.57 hours**.
Final completion evidence bookkeeping follows the captured end boundary.
