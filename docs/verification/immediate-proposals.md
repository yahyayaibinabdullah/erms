# Immediate proposal persistence and optional explanations

Approved 3 November 2026. Implements destruction-process.md revision 1.17,
§6.6–6.6.1 and DEST-03/18/24/29/41; common disposition specification and
workflow guide agree with this contract.

- Add/Update and confirmed Withdraw persist through the existing versioned
  review-work command. Multiple selected relationships remain one atomic command
  with separate proposals. Save sends an empty proposal-change array and saves
  comments only; confirmed proposal operations never save unsaved comments.
- Removed the local proposal queue/overlay and draft Add/Update wording. Refresh
  current server-paged proposals/memberships while retaining navigation and
  comments. Open proposal disclosures refresh too; abandoned views do not repaint.
- Every proposal reason, including removal-from-job, is optional. Routine Submit,
  Complete review and Approve accept empty comments on all routes. Rejection/
  return for correction still rejects blank comments. Labels/helpers explicitly
  explain the distinction in English and Arabic.
- Each persisted proposal action retains its event, identity, role and versions.
  Proposal persistence has no operational resource effect or stage transition.
  Full current access and execution authorization remain required on final
  approval. Missing user explanations use an approval-derived technical audit
  description at execution, without fabricating user-authored submission comments.
- Migration 096 and canonical schema agree; root scope constraints remain, and
  rejected decisions still require nonblank reasons. Existing saved rows/history
  are preserved. No new privilege, workflow state, endpoint or environment setting.

Verification:

- 304 focused WebUI tests passed, including actual English/Arabic ReviewForm,
  proposal editors, saved counts, multi-link atomic payloads, failed-write input
  retention, exact retry identity, busy guards, unsaved comments, restored tabs,
  required correction comments and abandoned views.
- 107 API review/edge/approval tests passed in disposable database
  `erms_messaging_test_acl_20b754e1626e45e4bd67865417c6f952`, then dropped.
- Seven additional focused audit-fallback/occupied-upgrade checks passed in
  `erms_messaging_test_acl_8c46bf999d5641fb8f34c6b4389a93fd`, then dropped.
  The occupied-upgrade check preserves job/task/membership/proposal/note/event
  rows and repeats the migration safely.
- Upgrade from the prior HEAD schema plus 095, repeated 096, verified the four
  changed function bodies against canonical SQL and retained scope/rejection
  constraints in `erms_proposal_upgrade_a7ce488cbabc4ac6ba1419a1b6d7faf5`; dropped.
  Final migration/function text parity was checked again locally after the
  execution-audit fallback correction. All earlier disposable runs were dropped.
- Live browser verification used actual ReviewForm/PageTable components and
  Wathiq table CSS with an in-memory API harness, without mutating a real job.
  Confirmed immediate Add with no reason, updated standard proposal rows, retained
  unsaved comments, and blocked empty correction comments in LTR/RTL. Saved
  [English](immediate-proposals/english.png),
  [Arabic editor](immediate-proposals/arabic-editor.png), and
  [Arabic saved table](immediate-proposals/arabic-saved.png) screenshots.
  Preview server and tab were closed.
- Catalogue reference/stale-key, lexical ordering, exact 3,990-key English/Arabic
  coverage, nonblank values, placeholder parity, terminology and artifact hashes
  passed. Nine new contextual keys were added; all earlier canonical Arabic text
  and provenance were preserved. Existing legacy keys remain for deployment
  compatibility. No administrator export was promoted.
- Applied 096 to authorized local `demo` after the focused tests; saved function/
  constraint definitions under gitignored `.runtime/immediate-proposals/` first.
  Jobs, tasks, memberships, proposals, comments and command receipts were unchanged.
  The official `--missing-only` seed stored nine unpublished Arabic drafts,
  protected 3,981 existing translations, and reported zero replacements/failures.
  Arabic drafts require human review/publication. No test suite ran against demo.
