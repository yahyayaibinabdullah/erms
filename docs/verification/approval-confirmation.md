# Compact final approval confirmation

Destruction-process §10 and DEST-45 require a bounded confirmation with the
complete proposal count and counts by type, explicit **Approve and apply
changes**, the applicable next step and a prominent no-destruction statement.
There is no expandable list; Cancel returns the reviewer to their unchanged task.

The read-only manager-authorized approval-summary endpoint includes the current
active proposals on active memberships in the applicable round and overlays up
to 100 queued creates, revisions and withdrawals. It checks current task/job
versions and validates queued target access, payload and versions without saving
review work, executing proposals or creating command/audit rows. Only aggregate
counts, advisory next-step context and existing approval tokens are returned;
related-resource identities and proposal values are withheld.

Only relationship removals/no proposals retain membership, so their message
explains automatic execution-report/request generation and external task creation.
Vital/security effects that certainly remove every root use the empty-job
message and actual preparation/correction return stage. Other effects can depend
on retention, hold policy and cascading relationships, so the confirmation states
both conditional outcomes instead of promising an inaccurate request. This is
an advisory explanation, not a replacement for final authorization, current-fact,
conflict, version, whole-set or atomicity checks.

Cancel performs no save. On confirmation, pending work is saved normally; the
existing final token preview is refreshed only if Save changed versions. Clean
work reuses the confirmation preview. There is no summary/result cache, no
cross-user or cross-language state, and abandoned views cannot open/submit the
dialog. The client marks the preview POST as a cancellable read so reference
caches are not invalidated. No schema migration, privilege or environment setting
is added; deploy the API and WebUI together.

## Verification — 26 October 2026

- 54 API approval/confirmation cases passed against a newly created disposable
  database initialized from the canonical schema. Cleanup dropped that database.
  Coverage includes queued creates/revisions/withdrawals, read-only snapshots,
  current task authorization, stale versions, input bounds, certain empty outcomes
  compared with actual execution in Standard and Records Manager Only, and the
  existing approval conflict/access/privilege/atomicity regressions.
- 303 WebUI task/screen/client cases passed, including English/Arabic rendering,
  a 1201-proposal count summary, all three next-step messages, Cancel without Save,
  no expandable content, clean preview reuse, post-save token refresh and client
  reference-cache preservation.
- Live in-app browser checks used production components with isolated mock data:
  English request creation and Arabic empty-job messages, explicit action label,
  readable counts, bold no-destruction statement and normal RTL wrapping. Both
  dialogs were cancelled; the temporary tab/process were cleaned up. No real
  job was approved or review work saved during verification.
- Catalogue references, sorted active-key coverage, nonblank/placeholder and
  artifact-hash checks, approved terminology, compilation, environment-template
  agreement and diff checks passed.

Nine contextual keys were added to the English catalogue and canonical Arabic
artifact: approval_title, approval_summary, approval_type_count,
approval_no_proposals, approval_next_request, approval_next_empty,
approval_next_conditional, approval_no_destruction and approve_apply (all under
disposition.ui). Existing wording and provenance were preserved; no administrator
export was promoted. Demo's explicit missing-only seed stored nine unpublished
Arabic drafts and preserved 3903 existing non-source-copy translations. The new
drafts require administrator review.
