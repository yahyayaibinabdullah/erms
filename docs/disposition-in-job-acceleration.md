# Restoring a reopened aggregation within its disposition job

Approved 29 October 2026; Disposition revision 1.14, sections 5.2, 6.1 and 11,
and Destruction Process revision 1.7. This amendment supersedes the mandatory
removal step for the compatible reopened-member case.

Reopening preserves membership, resets the complete unit to status 1 and blocks
job progress. An authorized IGU can then use **Accelerate disposition
eligibility** on the aggregation. If its current retention action matches the
existing active job and its organizational scope remains compatible, the command:

1. Closes the aggregation if open using the current database date/time, through
   existing closure checks. It does not reuse the date cleared by reopening.
   If already reclosed, preserve its current closure date, including a valid
   historical closure date for a migrated physical file.
2. Restores it and every descendant aggregation and record to the job's pending
   status: destruction 6, permanent transfer 7, selective transfer 8 or local
   archives 9.
3. Clears that membership's reopening flag/reason without changing its identity,
   job, original addition time or actor.
4. Records acceleration with its reason, current rule/due-date facts, job and
   membership identity, and sends the existing acceleration notifications.

All changes commit together. The command retains existing authorization,
resource/job access, optimistic-version, closure, preserve-state hold and
irreversible-work safeguards. An incompatible action, missing policy or other
failure leaves closure, statuses, membership, history and notifications
unchanged. Other reopened members continue to block the job.

Holds, vital status, security and relationship facts are retained and their
existing action-specific checks still apply. Recovery does not advance the
workflow or resume destruction. If the job is still in preparation with saved proposals only, recovery keeps
those proposals and the current stage without creating a new review round.
For jobs with completed review/approval, retain the existing approved-facts
comparison. Reopening alone does not discard approval. A migrated physical
file may legitimately keep or regain its original historical closure date.
If all approved contents and other facts are restored, the prior approval can
remain valid. If approved facts changed, the existing correction/return and
complete-review flow obtains renewed approval. Current blocker/execution
checks remain independent of approval validity. Preserve work, decisions,
documents and permanent history.

Ordinary reclosure and scheduled eligibility evaluation do not clear the flag.
Explicit removal remains available, especially when the retention action no
longer matches the job. This amendment does not allow arbitrary pending/final
state transitions or recovery of unrelated removal reasons.

## Implementation and deployment

Apply `database/migrations/093_restore_reopened_job_members.sql` to an existing
installation after migration 092, then restart the API/WebUI. The upgrade
replaces private functions only, is repeatable, and does not automatically
close aggregations, restore members, change jobs or rewrite historical events.
New empty databases use the standalone canonical `database/schema.sql` with
separate reference seeds and `database/baseline.sql`.

The existing acceleration endpoint, payload, `If-Match`, reason and response
shape are retained. For recovered members the returned status is the matching
pending status. The protected transaction-scoped recalculation context permits
only the exact unit's status and membership-flag restoration; it is removed
before completion. Existing advisory/hold-policy/unit row locks coordinate
reopening, policy edits, recovery, job changes and retries.

The membership update increments the job version, so open stale workflow forms
must refresh. No cache, additional page request, permission, workflow stage or
user setting is introduced. English and Arabic describe recovery as an
alternative to removal. Three new catalogue messages replace the retired
removal-only notice, whose complete translation provenance is retained in
`deprecated_items`. Seed missing Arabic drafts with the explicit
`004_seed_generated_arabic_ui_translations.py --missing-only` utility and review
before publication.

## Requirement traceability

| Requirement | Implementation | Verification |
| --- | --- | --- |
| DISP-13 / DISP-24: atomic closure and compatible in-job restoration | SQL `accelerate`, `allowed_transition`, `guard_resource`, `guard_workflow` | `test_disposition_in_job_acceleration.py`: all four actions, closed/open roots, original episode, retries, rollback, concurrent commands |
| DISP-25 / DISP-38 / DISP-42: protected pending state and membership identity | Exact-unit context, current job/action/scope checks, `assert_unit` | Direct SQL/command bypass denial, unchanged historical episode, migration parity/idempotence |
| DISP-18 / DISP-19: retain blockers and existing execution gates | Existing hold/protection/closure guards | Normal/preserve-state holds, vital/security facts preserved; other members still block |
| DISP-40 / DEST-06: approval follows actual approved facts | Existing `request_approval_current`, review snapshots and correction flow | Exact historical-date restoration preserves approval; changed title requires renewed approval; preparation proposals/stage preserved |
| DISP-43: one notification per committed acceleration | Existing event and receipt notification path | Retry/rollback and existing acceleration-notification regressions |
| Clear bilingual guidance | Existing bounded confirmation dialog and membership notice | English/Arabic component tests, catalogue checks and live browser evidence |

See the [verification report](verification/in-job-acceleration.md).
