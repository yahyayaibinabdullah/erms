# Disposition Phase 7 implementation and verification

Phase 7 implements the common persistence and transaction foundation from
Disposition sections 4–6 and 17. It does not expose operational job creation,
eligibility, review or destruction endpoints. Those phases must supply their
own current policy, blocker, routing, evidence and approval checks before using
the private primitives. Final execution and status-13 creation stay closed in
the unit-transition entry point until their owning phases implement them.

## Contract and implementation

| Approved requirement | Implementation | Verification |
| --- | --- | --- |
| DISP-01/02/17/25; §§4–6,17.2 | Numeric statuses 1–13 and stable Python catalogue; read-only outcome fields on aggregations/records; full-unit transition primitive, private command context, root/membership/job deferred consistency checks; read/search projections expose stored state. | Defaults and ordinary PATCH rejection; forged-GUC and direct-SQL attempts; invalid/partial/wrong-type membership rollback; injected descendant failure; descendant metadata/search projection. |
| DISP-37; §§17.1/17.3 | Four controlled types, three lifecycle states, controlled destruction stages/edges, immutable identity, current assignment, review round, server timestamps and versions; final execution remains blocked. | Four matching job types, stage-skip rejection, assignment-before-membership and nonempty assignment checks; stale versions; termination/reactivation; completed/final-field negative tests. |
| DISP-38; §17.4 | A row per membership episode, partial unique active-root index, immutable historical episodes, complete-unit changes and job version updates in the same command transaction. | Remove/re-add produces distinct episodes; concurrent admission has one winner; termination retains membership history and allows a later active job. |
| DISP-39; §17.5 | Shared user/role task destinations, claim/release/reassignment/completion attribution and versions; atomic private claim function rechecks current actor, queue eligibility and job-resource access. | Both/neither destination rejection; concurrent same-person and two-person claims; release/reassignment/completion history; completed task immutability; authority loss and resource-access checks. |
| DISP-40; §17.6 | Ordered rounds and immutable membership/resource-version snapshots, attributed immutable decisions with task and acting role, completion/invalidation fields. | Ordered, forged and immutable snapshots; current round linkage; attributed decisions and immutable decisions. Action-specific submission, routing, invalidation and repeated-review commands remain with Phases 13–15. |
| DISP-41; §17.7 | Governed record/component references, controlled document types/states, creator/checksum/template/version fields; component/checksum pairing, current record access and immutable available links. | Generating→failed→retry→available link lifecycle; immutable available link; governed component pairing. Atomic byte upload/generation and destination selection remain in Phase 11 and later artifact phases. |
| DISP-33; §13/17.2/17.3 | Externally supplied, exact free-format numbers, 20-character limit, unique per applicable job, shared outcome fields and event reference. | Unicode/special characters, length and uniqueness; incomplete/premature terminal fields rejected; no number generator. |
| DISP-42; §17.8/17.9 | New standalone migration 053; identical standalone canonical DDL; private command receipts bind actor/role/operation/payload/reason and preserve committed results. Existing event history remains append-only and follows resource redaction. | Fresh/upgrade acceptance; database catalogue parity and pre-existing resource/settings/grant/history preservation; unfinished command rejection, simultaneous duplicate retries, changed intent and lost-authority retries, redacted history. |

`database/migrations/053_disposition_foundation.sql` and the independent copy in
`database/schema.sql` own SQL. `backend/services/api/disposition/model.py` owns
stable Python codes; `commands.py` supplies the server-internal transaction,
version-lock, claim and full-unit primitives. The existing resource create and
update schemas continue to reject outcome fields; read schemas include them.
No general table CRUD or configurable workflow engine is added.

## Transaction and authorization boundary

A command uses the existing authenticated database actor context and a currently
effective information-governance role supplying `disposition.jobs.manage`.
The new approved privilege is granted to the two information-governance
profiles and the existing controlled `ALL_PRIVS` compatibility profile. An
actual acting role must still be marked for information governance; `SYS_ADMIN`
receives no grant. People, current assignments, active roles, access and claimed
task ownership are checked independently of job assignment.

A database-backed command context is scoped to transaction ID, backend PID and
an unfinished receipt. A caller-controlled authorization GUC cannot open it.
The private schema, tables and functions have no PUBLIC grants. They are
server-internal objects under the existing trusted database-owner connection
model; a database owner/superuser capable of altering triggers remains trusted,
as for existing ERMS database protection. Do not expose the private context as
an HTTP/import/general SQL endpoint or grant arbitrary clients access to it.

Command entry takes one transaction advisory lock before job/root/record locks.
This deliberately serializes the new short disposition transactions, including
membership and duplicate retry races. It does not run network, file conversion
or irreversible actions under that lock. Later workers must use bounded passes
and the action-specific transaction boundaries in the implementation plan.
The callback, receipt, state, versions and attributable events commit together;
a failed savepoint leaves earlier successful commands in its outer transaction
intact. Reusing a key for another identity, role, operation, payload or reason
fails. A completed retry rechecks current authority and returns its saved result.
No cache is introduced.

Existing closure functions retain their full previous behavior, with one narrow
exception for private, authorized updates changing only disposition outcome
fields. Ordinary content, hierarchy, vital/security, location and reopening
rules continue through the original function bodies. Reopening/rule-change
membership exceptions and recalculation hooks are implemented in Phase 9;
they are not operationally reachable through new Phase 7 routes.

The existing Audit Trail view redacts a complete disposition event if its
membership/resource snapshot includes inaccessible resources; it does not leak
concealed descendant IDs. Existing events are never rewritten. Migration 053
appends only its applicable catalogue/grant events with source `migration`.
The API health regression's two pre-Phase-6 hardcoded `true` expectations were
corrected to the already approved database defaults (`false`); health code did
not change.

## Verification

- **75 Phase 7 cases passed on both paths:** 71 in the final complete run plus
  four targeted cancellation/provenance/stale-review cases. Fresh database
  `erms_messaging_test_acl_8dbd617fc5494896a2da180ee39586a6`: 71 passed in 62.53s;
  upgrade database `erms_messaging_test_acl_89114ea2f644439384d6cb5928fc446e`:
  71 passed in 62.79s. The four additional cases each passed in 4.41s in
  `erms_messaging_test_acl_cf2ca832edfb4e0eb67b1f15c861ea89` and
  `erms_messaging_test_acl_e65fadad57ea47658a1f22c91bb8537d`.
- **91 affected resource/closure/authorization/hold regressions passed** in the
  156-case combined run (the other 65 were earlier foundation cases), 126.04s,
  database `erms_messaging_test_acl_3b5424c70f7e48c3b826b57ae26e734c`. Later
  corrections affected only new task/round tables and were covered by final
  fresh/upgrade acceptance.
- **39 database-free traceability/cache checks passed**, 1.10s. The template
  checker confirms all 36 API settings; Python compilation and whitespace pass.
- **Fresh/upgrade database catalogue parity and preservation passed** in
  `erms_disposition_test_fresh_35f8ac7379244d98892efc227ae212b4` and
  `erms_disposition_test_upgrade_ba5964942a134920b3710e86289712e1`.
  Existing organizations, roles, users, assignments, resource metadata/versions,
  settings, grants and history were preserved. New migration events alone were
  appended, attributed to `migration`.
- API pytest runs report the two existing Starlette/AnyIO deprecation warnings.
  Every owned database was dropped, including failed runs. A final independent
  read-only PostgreSQL catalogue query confirms **all 34** Phase 7 databases
  are absent. No creation or cleanup failure remains.
- Terminal outcome tests import explicit historical fixtures in disposable
  databases while temporarily bypassing only the closed job-execution guard;
  resource/membership/deferred constraints remain enabled. They verify complete
  status-10/11/12 outcome consistency, bad-descendant rollback and read-only
  history. This does not verify or enable any real final action.
All tests use new, uniquely named disposable databases. Initial fixture errors
(ownership, generated account status, checksum column, and a test event without
an entity ID), SQL catalogue/category fixes, and the old health assertions were
corrected before final acceptance. Every failed run also dropped its databases.

No WebUI, layout, browser interaction, catalogue key, maintained Arabic artifact,
environment value or template is changed in this phase. There is no UI phase
or new cache requiring browser checks. Existing generated translations retain
their previous review/publication status.

## Deployment and next phase

For an existing database, take the normal deployment backup and apply
`database/migrations/053_disposition_foundation.sql` once after migrations
050–052, before restarting the updated API. Do not rerun this structural
migration on a database where its schema-version marker already exists. A new
empty database uses `database/schema.sql` alone, followed by separate seeds.
The migration initializes every existing aggregation and record at status 1,
without modifying prior metadata, versions or events. It adds the approved
disposition privilege/grants and preserves all pre-existing grants. No new
environment setting or credential is required.

No persistent database, including `demo`, was migrated or tested during this
phase. Applying the migration is a deployment operation still to perform.
Phase 8 adds database-timestamp eligibility calculation and current blockers.
Destruction remains unavailable for operational execution until its later
workflow, recovery and final release gates pass.

Measured session: 2026-10-15 03:28:46–04:01:10 UTC, **0.54 active hours**.
Final evidence/documentation bookkeeping follows that captured boundary.
