# Completing intermediate reviews with restricted related resources

## Requirement and rationale

Destruction-process §6.3 and DEST-42 distinguish completing a File Administrator
or Unit Manager stage from authorizing the application of proposals. Nad's case
in demo illustrates the distinction: she can read root 1141/DEMO/011/2026 and
owns its File Administrator task, while two relationship removals proposed by
the Records Officer involve other aggregations outside her clearance. Those
endpoints and protected proposal facts must remain redacted, without preventing
her intermediate review from progressing.

Previously, `decide_review_work` called `validate_active_proposals`, which
re-evaluated every proposal through `proposal_facts` as the intermediate reviewer.
Both related endpoints failed that access check, producing the misleading root
access error. Migration 086 replaces only `decide_review_work`, removing this
execution-like validation from intermediate completion. It leaves command scope,
task ownership/claim, current role and root access, versions, stage/decision,
marked-removal and next-stage routing guards in force. Decisions still preserve
attributed immutable snapshots; no proposal or resource is applied or rewritten.

Proposal creation/revision and Records Officer submission/resubmission retain
their validation. `approve_proposals` is unchanged: the approving Records Manager
must validate and authorize every active effect using current access, clearance,
resource facts and underlying privileges, then apply the full set atomically.
Restricted or invalid effects cannot be omitted. The ordinary review-decision
command still cannot perform final Records Manager approval.

## Implementation and verification

- Canonical `database/schema.sql` and migration
  `086_intermediate_review_completion.sql` contain the same replacement function.
- `test_intermediate_review_completion.py` covers both intermediate stages and
  restricted aggregation and record relationship endpoints, English/Arabic
  partial projections, rejected protected proposal revisions, successful stage
  completion with attributed snapshots, and unchanged resources/proposals.
- The same scenarios reach final approval: a manager who cannot access the
  endpoint is rejected with no effects/decision; an authorized manager can
  subsequently execute the unchanged proposal.
- Non-governance File Administrator and Unit Manager reviewers with explicit
  root/record view ACLs can also complete the stage without the Information
  Governance management privilege.
- Both intermediate stages retain rejection for loss of root access, removed assignment, missing claim and stale task version.
- An occupied upgrade regression restores the prior function, reproduces the
  denial, applies migration 086 without rewriting tasks/proposals/review history,
  and successfully retries the existing task.
- Existing review, final-approval and workflow suites cover all review routes,
  rejection/correction, marked removals, invalid/conflicting/stale proposals,
  missing execution privileges, concurrency, atomic rollback and idempotency.

This is a database-only change with no new UI text, translation keys, cache,
environment variables or schema entities. Existing English/Arabic redaction and
messages remain in use. No UI action is performed on a user's behalf.

## Results — 26 October 2026

The combined intermediate-completion, review, approval and workflow run passed
122 tests. The two additional non-governance ACL reviewer cases passed in a
separate run (124 passing cases overall). Each run used a newly created
disposable PostgreSQL database initialized from the canonical schema; all such
databases, including fixture-debugging runs, were dropped. Catalogue references,
approved Arabic terminology, API environment-template consistency, Python
compilation and `git diff --check` passed. No UI layout or text was changed.

Migration 086 was applied to the authorized local `demo` database. Before/after
row counts and content hashes agree for its two tasks, two proposals, one review
round and decision history. Nad's task remains claimed by her and has not been
completed on her behalf. No restart is needed; refresh and retry Complete review.
