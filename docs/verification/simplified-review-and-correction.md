# Simplified review additions and correction comments — 29 October 2026

Approved contract: Disposition revision 1.15 section 10.2 and Destruction Process
revision 1.8 sections 5.2, 6.6 and 10; DEST-05 and DEST-06. The current user request
approves the Simplified-only addition exception and asks to fix correction
comments first.

## Correction comments

The reason was already stored correctly in the review decision. The correction
task rendered only the Officer's own draft and the submission comments; the
existing return notice appeared only in Job details.

`proposals.work` now includes the preceding authorized round in `return_context`
only for the current correction task. It reuses `progress.page(limit=1)`, honors
history redaction and the requested interface language, and excludes resource
snapshots. No extra browser request or shared cache is introduced. `ReviewForm`
and Job details share the same return-notice renderer: stage, round, author,
timestamp and full original comments, kept separate from editable Officer text.
External rejection/invalidation retains its existing meaning. No history or
authored comments are rewritten.

## Simplified additions

The SQL gate `can_add_review_members` requires an active destruction job with
saved route Simplified, current Records Manager review, the caller's current
claim and a currently eligible Manager role. The membership-stage guard permits
only `membership_add` through that exception. All existing common admission
checks remain in `assert_admission`; immediate review-stage removal is forbidden.

The job projection separately provides `membership_addable` and its task-specific
`membership_add_role_id`. The task's Aggregations tab and Job details offer
**Add aggregations**. The existing eligibility command uses that role rather
than an unrelated global governance role. The existing unsaved-work warning
protects pending edits. Returning reloads current job and membership versions.

An addition does not advance the stage or round. Final approval uses fresh
versions/tokens and the complete current set. The immutable submission snapshot
is retained; Simplified approval accepts only an extension containing every
original snapshot entry exactly unchanged. Missing/changed original entries
still fail. Final decision and execution snapshots contain the updated set.
No Standard or Records Manager Only routing, post-approval permissions, proposal
execution or protection requirements are relaxed.

## Requirement mapping

| Requirement | Implementation | Verification |
| --- | --- | --- |
| DEST-06 / section 6.6: show recorded return to Officer | `proposals.work`, review-work route, shared `process.return_notice`, `ReviewForm.load` | Correction notice API tests, repeated Standard/Simplified rounds, bilingual rendering/redaction tests and live correction screenshots |
| DEST-05 / section 10: only working Simplified Manager adds | Migration 094, `require_membership_stage`, `can_add_review_members`, job/chooser projections | Saved-route, role, unclaimed/other-claim, HTTP, no-removal and admission-protection tests |
| DEST-06: approve full updated set without rewriting submission | `approve_proposals` original-entry comparison, existing preview fingerprints and decision/execution snapshots | Complete approval including a new member's proposal, stale preview, changed-original rejection, saved-work and immutable-round tests |
| DISP-27: bounded and retry-safe addition | Existing add command/eligibility UI, projected task role | Exact retry, concurrent additions, UI role attribution and bounded reads |
| Canonical and populated upgrade agreement | Canonical schema, baseline and migration 094 | Function parity, idempotence and populated pinned-schema upgrade preserving tasks, proposals, notes, membership and rounds |

## Evidence

Final affected verification is complete. The broad run and focused reruns below
cover every selected API case, including the corrected workspace fixtures.

- Focused correction API checks: **6 passed**, including existing progress tests.
- Focused Simplified addition API checks: **10 passed**.
- Populated upgrade from pinned pre-change commit
  `d01b02e031c43a9c0307ac629e48469a05ee6703`: **1 passed**. Required reference seed
  and baseline were applied separately; migration 094 was applied twice after
  reproducing the old rejection. Saved review data remained identical.
- Frontend/schema checks: **317 passed**. These cover both languages, task-only
  additions, unsaved-work protection, exact task-role attribution, correction
  notice/redaction, existing screens/tasks/history and migration parity.
- Wider affected API run: **270 passed** before an existing queue fixture failed
  because it supplied one eligible reviewer while expecting an unclaimed task.
  The established sole-reviewer policy auto-claims that task. The fixture now
  supplies two eligible reviewers; the remaining workspace/correction rerun is
  completed with **16 passed** (all 13 workspace cases and 3 correction cases).
  Other explicit-claim fixtures in that file were aligned with the same existing
  policy. No routing behavior was changed to satisfy the tests.
- The final correction-only rerun also passed **6 checks**, including ensuring
  an old completed correction task does not receive a later return notice.
- Live isolated API/WebUI: correction notice in English/Arabic; correction
  resubmission; Manager review Add action; successful addition; retained Manager
  review stage and two Pending destruction members on return; repeated Arabic
  navigation shows fresh membership. Existing Wathiq/NiceGUI presentation is
  retained without custom layout CSS.

Screenshots:
[English correction](simplified-review-and-correction/correction-ltr.png),
[Arabic correction](simplified-review-and-correction/correction-rtl.png),
[English addition action](simplified-review-and-correction/additions-ltr.png),
[Arabic addition action](simplified-review-and-correction/additions-rtl.png),
[updated membership](simplified-review-and-correction/added-membership-ltr.png).

All database tests and live fixtures use uniquely named disposable databases,
never demo. Failed fixture-only expectations (empty string versus null, normal
task version after saving, and governed reason setup) were corrected before the
final focused runs. The first populated-upgrade fixture lacked separately seeded
reference data; its database was dropped and the corrected pinned upgrade passed.

## Catalogue and deployment

One key, `disposition.ui.add_aggregations`, adds **Add aggregations** / **إضافة
ملفات**. Both catalogues have **3,924 active keys**. All 3,923 prior Arabic entries
and deprecated history were preserved exactly. Existing return-notice keys are
reused; authored comments are not translated. No administrator export was
promoted. The new generated Arabic value requires human review.

Catalogue reference/stale-key, exact ordered coverage, blank, placeholder,
markup, approved Arabic glossary, provenance and artifact-hash checks passed.
The older whole-artifact generation validator has pre-existing curated-wording
exceptions documented in earlier verification; the new entry passes it.
Configuration authority (122 settings), API template consistency (36 API
settings) and whitespace checks pass;
no settings or environment variables changed.

Migration 094 was applied to demo. All existing jobs, memberships, tasks,
rounds, decisions, notes and proposals were unchanged by migration. The managed stack restart succeeded. Read-only checks confirmed all three
changed SQL functions match canonical definitions and the four named demo
aggregations, all jobs, memberships, tasks, proposals, rounds, decisions and
review comments remained unchanged. All **3,976 pre-existing Arabic translation
rows** were preserved exactly; only the new key's untouched English source-copy
draft was filled with its generated Arabic value. It remains unreviewed and
unpublished. API/WebUI health checks returned HTTP 200.

All **13 owned disposable databases** are absent, the temporary preview
connection file is removed and no agent-created browser tabs remain. See
[cleanup evidence](simplified-review-and-correction/cleanup.json). The preview
API/WebUI and browser tab were closed. Its in-process fixture shutdown stalled;
its exact owned process was verified and stopped, then its uniquely named
disposable database was explicitly dropped and its absence verified. The
temporary connection file was removed.

Historical phase snapshots in the legacy project ledger remain historical.
This amendment has the explicit current mapping above; it does not claim a new
whole-project phase acceptance run.
