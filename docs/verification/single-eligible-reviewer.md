# Single eligible reviewer assignment

New File Administrator, Unit Manager and Records Manager review tasks
conditionally assign responsibility immediately. Distinct currently eligible
people are counted across the stage's applicable queues; at most one task is
claimed. Multiple candidates retain manual claiming. Zero eligible candidates
remain subject to the existing routing rejection.

The canonical schema and migration 083 install a narrow BEFORE INSERT trigger
ordered after the existing disposition authorization guard. It only defaults
new, open internal-review tasks during authorized review routing. The role
queue remains the destination and the sole person becomes claimant, preserving
existing current-eligibility checks, release/reassignment, immutable history,
notification recipient resolution and worker reconciliation. It neither grants
access nor changes preparation, external-approval or execution-task routing.

The candidate gates match task_eligible's role-queue branch: active human,
effective role and assignment, stage-specific designation/profile/privilege,
active job and current access/clearance for every aggregation and record in its
active units. Candidates are limited to two distinct users because only zero,
one or multiple matters. Role and ACL changes are checked again at work time.
Loss of eligibility immediately blocks work; the existing reconciliation worker
reopens the queue for manual claiming, preserving saved work. Release never
causes immediate automatic reassignment.

Migration 083 adds behavior for newly routed tasks only. It does not claim
existing tasks or rewrite their history. The occupied-database upgrade test
verifies this preservation. No environment settings or new translation keys.
The previously added localized submission toast names the actual claimant when
one exists, otherwise the shared queue(s).

## Verification (26 October 2026)

- 16 focused API/database tests passed: sole/multiple distinct reviewers,
  current role/assignment/access/clearance gates, loss of eligibility,
  reconciliation, multiple manager roles, and occupied-database preservation.
- Workflow and task-notification regressions passed (42 tests); review and
  approval regressions passed on the final rerun (72 tests). Manual-claim
  scenarios explicitly provide multiple eligible candidates.
- 154 WebUI task/screen tests passed, including localized submission feedback,
  successful return to My Tasks, and retention of the page after failure.
- Database-backed tests used fresh disposable databases initialized from the
  canonical schema; all were dropped after their runs.
- Migration 083 applied to `demo`; both existing task rows compared equal
  before and after, and the new trigger was enabled.
- API environment-template check and `git diff --check` passed. No new UI
  keys were introduced by automatic assignment. The submission-feedback Arabic
  drafts remain unpublished for administrator review.
