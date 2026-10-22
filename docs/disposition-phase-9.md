# Disposition Phase 9 implementation and verification

> Historical phase evidence. The acceleration protection rule described here
> is superseded by the approved 22 October 2026 correction: protected units may
> become eligible while admission and execution remain blocked. Normal holds
> permit closure; preserve-state closure restrictions remain. See the
> [current behavior and verification](verification/acceleration-protections.md).

Phase 9 provides protected common job commands and atomic integration of
reopening, effective retention changes and hierarchy changes. The application
services and explicit command API reuse the private transaction/receipt kernel.
No general CRUD endpoint exposes workflow tables. Phase 10 owns the eligibility
listing and common screens; later phases own action-specific review/evidence,
irreversible termination recovery and final execution.

## Contract and implementation

| Approved contract | Implementation and verification |
| --- | --- |
| §§3.5/3.6/10/17.3; DISP-11/12/26/34/37 | Create an active job for each of four action types. An empty job may be unassigned; admission requires a currently authorized specific person and existing view access. Assignment/reassignment never grants ACLs, organizational access or clearance. Destruction creation/assignment requires the existing Records Officer profile. Tests cover assignment effectiveness, service accounts, clearance and privilege loss, empty/nonempty assignment, lifecycle and exact retries. |
| §§5.3/5.4/10.2/17.4; DISP-25/27/28/38 | A bounded selection of 1–100 roots uses an independent savepoint per item, with an exact saved mixed-result receipt. Each success joins one membership episode, whole-unit pending status and immutable history. Stale, hidden, child, wrong-type, blocked and conflicting items stay unchanged. Removal preserves every episode; re-addition creates a new one. Tests include competing jobs, descendant failure and current authorization on retries. |
| Destruction §§5.1/5.2 | Check current root ownership against the job-owning organizational subtree. Ownership remains on the resources. Owning-unit changes require an active empty job never submitted for review. Membership edits are limited to preparation/correction; reviewer-stage edits are rejected. Tests cover mixed inside/outside ownership, empty-again jobs, review history and restrictions. |
| §11; DISP-13/36 | Acceleration derives the action from the effective rule, needs a reason, uses current locked vital/security/hold facts and records rule/dates/actor. Open roots may accelerate; they must close before admission. Outside-job relationships allow acceleration/admission and still block final action. All four actions, open/future-due units and root/descendant protections are tested. |
| §§6.1/12/12.1; DISP-24/29/32 | Database hooks capture previous rule/date/status, compare current effective policy and recalculate the complete unit in the same transaction as the authorized policy/reopening/hierarchy edit. Matching due members stay pending; not-due/incompatible members stay in their job with a protected removal-required reason. Reopened members stay at status 1 until explicit removal, including reclosure. Progress is blocked while removal is required. Tests cover local/inherited precedence, unchanged inheritance, changed hierarchy, rule removal, API freshness, authorization and rollback. |
| §§9/10.3; DISP-18/19/21 | Protections arising after admission retain membership/pending status. An authorized explicit removal or pre-irreversible termination may restore eligibility while preserving every protection. Termination requires confirmation/reason, cancels open tasks and retains membership history. Tests cover holds, vital/security flags, interruption-safe rollback and later admission to a new job. Partial/final irreversible outcomes remain closed for their owning phases. |
| §§16/17.8/17.9; DISP-17/42 | Current actor, role, access, version and command-scope checks; immutable receipts/history; canonical/055 equivalence; preservation of existing active memberships and original data. Events use the existing shared English/Arabic audit-label map, including historical operations. |

Implementation locations:

- `database/migrations/055_disposition_membership.sql` and its independent complete
  canonical copy in `database/schema.sql`.
- `backend/services/api/disposition/membership.py` and `disposition/routes.py`.
- Existing aggregation/classification/ACL-move routes coordinate locks before
  taking resource locks. `crud.update_row` fetches the final aggregation image
  after a hook can change its status/version.
- Shared `frontend/webui/event_labels.py` and the two maintained language artifacts.

## Commands and current checks

The explicit API prefix is `/api/v1/disposition`. Commands cover job creation,
assignment, owning-unit change, bounded membership addition, individual removal,
acceleration and termination. Every request binds its UUID, authenticated person,
acting role, exact payload and reason. Existing `If-Match` applies to mutations;
addition also carries each selected root's version. Removal carries membership
and root versions. Termination requires an explicit boolean confirmation.

The authenticated session supplies identity; the payload cannot substitute an
actor. Database checks enforce the currently effective IG role supplying
`disposition.jobs.manage`. Resource access is checked independently and is
rechecked when returning a committed retry result. Destruction uses the existing
`INFO_GOV_OFFICER` designation for current creation/assignment; other route/task
variants belong to their action-specific phases.

Each multi-add item either saves membership, all descendant statuses and events,
or rolls back that item's savepoint. Other valid selections remain successful.
The outer request commits its exact mixed result once; retries do not duplicate
successes or history. Errors expose stable reason codes without raw SQL, hidden
resource names, security details or hold names. No collection download or cache
is introduced.

## Recalculation and hierarchy

Protected `removal_required` and `removal_required_reason` fields record the
specified reopening/rule-change exceptions to matching pending membership.
Clients cannot set them. Historical membership episodes remain immutable.
Rule changes preserve the root-local override priority, full current rule
snapshot, UTC calendar calculation and strict database due boundary.

A private transaction/backend/root context exists only from the policy trigger's
capture through its completed recalculation. It grants only the exact derived
status on that current unit and cannot alter ordinary metadata, content or final
fields. A fabricated GUC grants nothing. Failed or interrupted statements roll
back the context, policy, unit, flags and events together. The context is deleted
before a successful statement completes; it is not a cache.

Policy administration keeps its existing `classifications.administer` authority.
It does not require an extra disposition privilege or visibility of every
resource inheriting the policy. Recalculation events retain the actual policy
administrator. Reopening/reclassification retains existing resource-operation
permissions, reason and closure/hold restrictions.

Effective-rule comparison excludes incidental hierarchy depth and row timestamps.
An unchanged inherited/local rule preserves acceleration, status and membership.
Containment changes also align moved descendants with their current governing
unit. Detaching a subtree compares its old governing policy with its new root
policy. New descendants of an open accelerated unit inherit that unit's stored
status. Closed-content and final-resource protections still apply. Historical
membership identities remain unchanged when a former root later moves; integrity
checks validate its current governing unit rather than treating an old episode
as current membership.

Pre-055 policies with unrepresentable due dates remain reportable worker failures.
An authorized repair captures their original rule/provenance and explicit
calculation failure, then recalculates immediately. A new unrepresentable result
rejects and rolls back the policy edit.

## Locking and protections

Commands reuse advisory transaction lock `(7357,1)`. Policy/closure/hierarchy
entry points take that lock, then the hold-policy shared lock before resource
locks. Admission/acceleration reuse the current blocker lock protocol and ordered
unit rows/security-policy locks. Relationships are checked separately and are
not admission blockers. Existing relationship writers use the same coordination
lock. Each selected root is checked again under these locks.

Live protection checks evaluate the database clock after lock waits. This catches
a hold whose start time arrives while admission is waiting, without changing
half-open hold interval semantics. Preserve-state hold exceptions remain narrowly
limited to authorized status-only eligibility/recalculation and restoration of
eligibility on removal/termination. They never release a hold, weaken a security
policy, change vital status or permit ordinary protected metadata/content edits.

Recalculation does not advance an active job, discard work, remove membership,
or resume final action. Required removal blocks progress. Normal protective
blocker detection/resolution UI and action-attempt auditing remain with their
consuming screen/action phases, as recorded in the requirement ledger.

## Verification

- Final full canonical run: **201 passed**, 201.28s, database
  `erms_messaging_test_acl_4189ff0a59e44d5f813b7748263a5c29`.
- Independent upgrade from committed pre-054 baseline through separate 054/055:
  **201 passed**, 200.33s, database
  `erms_messaging_test_acl_1efc67b7296d4db9964d049e4c33b723`.
  Each full run includes 69 Phase 9 cases plus all 75 Phase 7 and 57 updated
  Phase 8 cases. The older tests now assert immediate policy recalculation;
  the worker-failure fixture explicitly models a pre-upgrade corrupt policy.
- The only subsequent change tightened the removal-reason CHECK against SQL
  NULL semantics. Its **three** isolated backstop cases passed on each final
  fresh/upgrade path (5.77s each), databases
  `erms_messaging_test_acl_0707c71742c34cbb9fd72cb85c7cd7cb` and
  `erms_messaging_test_acl_0755d2c32e2c4eb48d3b8e4dc30b27a3`.
  Current Phase 9 acceptance therefore has 72 cases, alongside 132 earlier
  disposition compatibility cases, verified on both schema paths.
- **83 affected API regressions passed**, 82.31s, database
  `erms_messaging_test_acl_00dc69e0690a4e159212578dc39dc903`: classification,
  ACLs, relationships, legal holds, media, mutation/governance authorization
  and the complete localization catalogue. Subsequent scoped refinements are
  covered by the final disposition suites above.
- Final fresh/055 catalogue equivalence and original-data preservation passed
  in `erms_disposition9_test_fresh_df24bb55c5c8485087e7f36d7f061ab9` and
  `erms_disposition9_test_upgrade_538fb2d5eed8431e89b272c0e36f2e21`.
  The checker compares actual definitions/ACLs/triggers and preserves a real
  pre-upgrade active membership and its job/receipts/history.
- **39** database-free source/traceability/cache checks and **five** shared
  bilingual label/export checks passed. Catalogue references/stale keys,
  694 approved terminology uses across 29 mappings, ordered coverage,
  placeholders/nonblank, full prior-entry/provenance preservation, artifact
  hashes, Python compilation, environment-template synchronization and
  whitespace checks pass.

All **26** disposable databases created in Phase 9, including failed runs,
were dropped and independently confirmed absent by a read-only PostgreSQL
catalogue query. No creation or cleanup failure remains. No test used `demo`
or another persistent database. API pytest runs report the two existing
Starlette/AnyIO deprecation warnings.

## Localization and deployment

Ten shared audit labels were added for job creation, assignment, owning-unit
change, membership addition/removal, termination, acceleration, recalculation,
reopening and required removal. English and Arabic have **3,204** active keys in
identical lexical order. Every prior **3,194** Arabic item, including curated
wording and complete provenance, is preserved. Only the ten new entries are
machine-generated drafts with contextual generation metadata. No administrator
export was promoted and no persistent translation was seeded or published.
The ten new drafts require ordinary review/publication after explicit seeding;
the two earlier Phase 8 drafts remain subject to that same workflow.

No screen, table, layout, navigation, catalogue-render path or runtime cache was
added or changed. Phase 10 will supply the common UI using these server commands.
Shared event labels were checked in English/Arabic; no layout fallback was used.

Apply missing migration 053, then 054, then 055 before deploying the updated API
and worker. A new empty database still uses `database/schema.sql` alone, followed
by separate seeds. The 055 upgrade preserves existing resources, active jobs and
memberships, receipts, settings, identities, grants and immutable history. It
adds default false/null removal flags and performs no eligibility sweep.

Deploy/reload the API and WebUI for new routes, final-row responses and static
message definitions/mappings. Explicitly seed and review/publish the new Arabic
drafts using the existing translation workflow. The Phase 8 worker uses the
updated database functions; no new worker or scheduling setting is introduced.
There are no environment-variable/template changes or private `.env` edits.
No persistent database migration, translation publication, service installation
or service restart was performed during implementation.

Phase 10 is next: eligibility and common job screens. Final execution remains
closed; later phases must add their action-specific gates and irreversible
recovery before enabling it.

Measured active session: 2026-10-15 05:39:43 UTC to 2026-10-15 06:14:25 UTC, **0.58 hours**.
Final completion evidence bookkeeping follows the captured end boundary.
