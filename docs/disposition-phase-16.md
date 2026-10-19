# Phase 16 — task inbox and review workspace

The task inbox and common destruction workspace now support the assigned
Records Officer, task-only File Administrator and Unit Manager, and Records
Manager. The API derives actions from the current task, role, claim, job stage
and access. Standard, Simplified and Records Manager Only retain their saved
routes. External request generation and authority decisions remain Phase 17.

## Requirement-to-implementation-to-test traceability

| Approved scope | Implementation and verification |
| --- | --- |
| Destruction §§6.1–6.3; DEST-02, 21–23 | `workflow.tasks`, `workspace.read`, `tasks.py` and guarded app navigation provide real server pages, direct/queue/claimant names, received date/age, priority, governing-root count, state and action indicators. Filters and meaningful sorts run on the server. Current queue eligibility, claim, release and reasoned reassignment use existing protected commands. Workspace/API regressions cover task-only reviewers, other claimants, stale authority, selected hydration and exact role/person handover scope. Live FA/UM work has no Disposition Jobs/Eligibility navigation or membership/assignment/evidence replacement controls. |
| Destruction §§6.4–6.4.1; DISP §17.5 | `screens.py`, `queries.py` and existing governed artifact controls show current round, destruction number, claimant and action-required state; member owner/classification, effective rule/source, override, medium, blockers and proposal/removal labels. Membership filtering/sorting/pagination and redaction remain server-owned. Evidence retains record/component authorization and version history. Live checks page the 58-root Standard job in 25-row requests and render evidence/report PDFs. Task-only FA can preview evidence and cannot correct it. Existing artifact tests verify correction authority, history and no broadened evidence access. |
| Destruction §§5.3, 6.5, 6.6.1; DEST-03–06, 18–20, 24, 28–29, 34, 41 | `review.py`, `proposals.py` and bounded workspace selectors provide all eight proposal editors, readable current/proposed values, original author/role/stage/round/time and distinct last editor/time. Identity is fixed on revision; selected links outside the first page hydrate by exact resource-scoped ID. Draft dialogs do not write. Explicit atomic Save retains partial overall reason, own versioned notes and proposal revisions without executing or advancing. Typed editor tests cover every proposal type in both catalogues. Live Officer → FA revision preserves original authorship; a retention proposal saves without applying its values. |
| Destruction §§6.6–6.6.1, 7–10; DEST-40 | Task-specific forms expose current actions only, save visible edits before decisions, enforce required reasons and preserve failed drafts. Busy/dirty guards protect navigation and mutation. Approval failure after commit reports a pending report truthfully and never reruns resource effects. Live Standard: submit → FA revise/save/complete → UM reasoned removal mark/reject → Officer remove/resubmit → FA/UM complete → Manager approve. Live Simplified: submit → Manager reject → Officer correct/resubmit → Manager approve. Manager Only performs combined approval with its own reason, without intermediate tasks. All three create available execution reports; immutable outcomes are recorded in `live-workflow-outcomes.json`. |
| Destruction §6.7 | Native NiceGUI Mermaid is lazy and shows Start → active creation → assigned preparation, saved route/skipped stages, rejection/correction branches, future approved process stages, Completed → End and current-stage emphasis. Its actual SVG was inspected in the browser; no diagram asset loads before expansion. |
| Common §§15, 17; Destruction §§6.4–6.6 | Proposal/note revision history, prior rounds/decisions and authorized job events are paginated. History disclosures construct on demand and refresh on reopening. Notifications open the actual currently authorized task through existing envelope/source-event metadata. No new message store, ACL grant, role or privilege is introduced. |
| Performance/design/i18n contracts | Standard Wathiq `PageTable`, native grids/controls, current-page guards, concurrent independent reads, bounded two-character selectors and selected-ID hydration. No new data cache. Repeated navigation, abandoned workspace load, mutation freshness, actual LTR/RTL layouts and stale forms are checked. The stale browser form shows a conflict toast and retains unsaved notes. Arabic-direction live pages use the existing published catalogue and English fallback for new unreviewed keys; bilingual component checks exercise the new draft wording. |

## Claim/save database fix

Live FA Save exposed a database defect that single-transaction tests concealed:
`guard_workflow` replaced the original `claimed_at` during a later Save. The
protected draft-save trigger correctly rejected the changed claim. Migration
**061_disposition_review_save.sql** preserves the original timestamp except
when claiming or reassigning. New tests commit a claim, save/revise on another
connection, and verify the original claimant/time and proposal attribution for
all three review stages. The same standalone SQL is in `database/schema.sql`.

Canonical/upgrade parity compares the complete database catalogue and every
pre-existing public/private row. The probe passed and removed both databases.
A related messaging compatibility failure used the old zero-argument timezone
resolver; three messaging callers now pass their existing database connection.
Messaging regression passed.

## Verification evidence

Evidence and screenshots are in `docs/verification/disposition-phase-16/`.
Overlapping runs are not a sum of unique tests.

- Final HEAD → migrations 058–061 API run: **161 passed**.
- Final canonical workspace/workflow/header run: **47 passed**.
- Final frontend/forms/artifacts/templates/history/navigation/messaging run:
  **82 passed**, including all eight proposal editors in English and Arabic.
- Final messaging and catalogue checks: **19 passed**.
- Committed-claim cross-transaction workspace run: **11 passed**.
- Upgrade catalogue/data parity passed; all 24 traceability-tool tests passed.
- Catalogue reference completeness, environment-template synchronization,
  requirement baseline and whitespace checks passed.
- Browser: Standard and Simplified correction cycles, Manager Only combined
  action, saved authorship/revision, membership paging, concurrent forms,
  evidence/report rendering, limited actions, navigation freshness/abandonment,
  diagram and LTR/RTL table geometry. Chrome used the requested Yahya Gmail
  profile. The in-app browser was unavailable in this session.

The first final API command referenced a nonexistent messaging test filename;
it collected no tests and cleaned up its database. The corrected invocation
passed. Editor tests initially found a retention-summary scope error; it was
fixed and both the complete rerun and live Save passed. These diagnostic failures
are not represented as passing acceptance.

## Deployment and translation handoff

Apply **061** after **060** and any pending predecessors, then restart API and
WebUI. New empty databases use `database/schema.sql` alone. No persistent
ERMS database, including `demo`, was migrated or used for tests. No environment
variable or template change was introduced; all 36 API template settings agree.

EN/AR each have **3,560** aligned active keys. The **146** new Arabic entries are
generated drafts marked `needs_human_review`; all **3,414** previous Arabic
items retain exact wording, flags and provenance. Ordering, coverage,
placeholders, blanks, new-entry terminology/quality, generation timestamps,
provenance and catalogue hash pass. No administrator export was promoted and
no persistent translation or new-draft publication was performed. Explicit
seeding, human review and publication remain operator actions. Automatic
approval review rejected an attempted new-draft publication in the disposable
preview; that rejected operation did not run and was not retried.

All owned previews/test databases are removed at handoff; independent database
absence is recorded in `cleanup.json`. Changes remain uncommitted. Phase 17
is next; no external request or subsequent destruction action was fabricated.
