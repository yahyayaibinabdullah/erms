# Phase 13 — Destruction routing and shared tasks

Phase 13 implements saved destruction routes, reviewer resolution, shared task
operations and internal round-routing primitives. Proposal editing, submission
forms and actual review decisions remain Phase 14; combined approval/execution
remains Phase 15; the My tasks screen and task-form navigation remain Phase 16.
No destruction execution is exposed.

## Requirement and implementation map

| Approved contract | Implementation and verification |
| --- | --- |
| Destruction §§2.1–2.4, 5.4–5.5; Configuration §6.1 | Migration 058 captures the current database setting on job insertion and prevents later route changes. Standard, Simplified and Records Manager Only are supported. Current person accounts, effective role assignments, required Officer/Manager profiles and management privilege are checked independently. `test_capture_route_direct_preparation_and_saved_route_round`, `test_manager_only_no_officer_or_review_queues_and_immutable_route`, and `test_same_person_officer_and_manager_actions_require_independent_current_roles`. |
| Destruction §§5.1–5.2; common §§10.1.1–10.2 | Existing subtree admission preserves each unit's ownership and protections. Membership mutation now requires the assigned preparer in an allowed preparation/correction stage. Owning-unit changes remain limited to active, empty, never-submitted jobs, including the Manager-only combined-action boundary. Assignment changes cancel old direct tasks and create the current preparer's task. Existing membership and ownership regressions, `test_correction_resolves_saved_route_again_and_owner_locked_after_empty`, and `test_manager_only_combined_round_boundary_locks_owner_and_external_correction`. |
| Destruction §§7.1, 8, 17.1, 18.2 | Nearest configured File Administrator and its source unit are retained. Absence skips only that step; inactive, unassigned or inaccessible configured roles block without ancestor fallback. Unit Manager uses exactly the owning unit's `managing_role_id`. Manager queues require current `INFO_GOV_MGR` roles supplying the management privilege. `test_nearest_configured_ancestor_and_source_unit_no_role_grant`, `test_explicit_unusable_file_admin_blocks_without_fallback`, `test_unit_manager_requires_own_units_usable_designated_role_before_entering_stage`, and the route tests. |
| Common §17.5; Destruction §§6.3, 17.5 | `workflow.py`, protected SQL and purpose-built task APIs implement claim, release, reassignment, management recovery and current eligibility. File Administrator/Unit Manager task authority does not require or grant `disposition.jobs.manage`. Access checks cover every aggregation and record in each active disposition unit. Role queues retain their destination when a claimant is reassigned or loses eligibility. A replacement configured queue can be selected by an authorized management role. No new privilege, ACL grant or workflow engine. Concurrent-claim, task-only authority, eligibility-loss and retargeting tests. |
| Common §17.6; Destruction §§5.4–5.5, 9, 12.1 | Private routing primitives start ordered rounds with immutable membership/version snapshots, resolve the saved route again on resubmission, record skipped routing and source units, and create direct Officer/Manager correction tasks. The private Manager-only round boundary is available for the later atomic combined approval. No generic stage-setting, review-decision or task-completion HTTP endpoint bypasses Phase 14/15 validation. |
| Common §16; Destruction §§6.3, 7.1 | Existing immutable events retain before/after task states, old/new claimants, actor, acting role, reason, time and routing source. Job history now includes task/round/decision events. Seven shared audit labels also format existing historical operation codes without rewriting events. |
| Destruction §6.1; Messaging MSG-018/019/021 | `disposition/notifications.py` registers an optional task-assignment producer with typed task ID, bounded current eligible recipients, durable source-event identity and existing messaging receipts. Enabled notification failure rolls back the business command. Disabled/unconfigured delivery is dormant. Exact command retries do not duplicate notifications. Task-link presentation belongs to Phase 16. No separate notification store is introduced. |
| WebUI performance §§6–10 | Task API uses server limits/offsets and current authorization, with no result cache. Existing assignment type-ahead/hydration now sends the job ID so changing the organization-wide route does not change existing jobs' assignee eligibility. Existing native controls, rendering and abandonment guards are retained. LTR/RTL component tests pass. An index-only task lookup and non-overlapping pages were verified over 201 jobs and 1,001 task-history rows. |

The eligibility worker also reconciles a bounded page of claimed tasks, using
an independent cursor across watch iterations. Work authorization fails
immediately after eligibility loss; the next worker pass returns the claim to
its queue without changing proposals or round snapshots. The worker now checks
migration 058 before starting. An authorized manager can release/reassign a task
without waiting for that pass, subject to existing resource access.

Multiple eligible Manager roles receive their own role-queue destinations.
Claims across those destinations are serialized so only one person handles a
job's current review stage. The later decision service cancels the other open
stage tasks atomically through the shared routing primitive.

## Database upgrade and notification integration

`database/migrations/058_disposition_routing.sql` is independent portable
PostgreSQL SQL. The same SQL is appended to the standalone canonical schema.
Earlier assigned jobs retain Standard routing; missing direct preparation tasks
are backfilled with migration-attributed events. Existing events are never
rewritten. Existing task rows, governed evidence bytes/links, templates, settings,
receipts and job fields are preserved by the independent upgrade probe.

The messaging snapshot guard previously equated tuple `xmin` with the top-level
transaction ID. A command savepoint gives inserted rows a child transaction ID,
so enabled notifications were rejected. The guard now accepts only a visible
in-progress insertion, with wrap-aware full transaction IDs. Committed message
snapshots remain sealed. This follows PostgreSQL's documented distinction
between [top-level IDs, subtransactions and commit status](https://www.postgresql.org/docs/current/functions-info.html#FUNCTIONS-PG-SNAPSHOT).
Tests cover nested command savepoints, enabled delivery, rollback, exact retries,
HTTP transaction isolation, and attempted insertion after commit.

## Verification

The final canonical regression run passed **338 tests**, the upgraded-schema run
passed **29**, and the frontend/traceability run passed **47**. Additional
checks passed for enabled HTTP notifications (7), task-only reviewers (2),
owning-unit Manager failures before stage entry (6), and representative task
pagination/index use (1), common job projections (4), and authentication (15).
These targeted runs overlap the main regression cases;
the counts are per run, not a sum of distinct tests.

Passing run logs are under `docs/verification/disposition-phase-13/`. They cover
canonical-schema regressions, HEAD plus 058 behavior, independent schema parity
and historical preservation, notification HTTP integration, representative task
paging/index plans, native UI component regressions and localization validation.
All database checks used uniquely named disposable databases. Cleanup evidence
lists every database created during successful and diagnostic runs.

A temporary disposable preview started and was shut down cleanly. The computer
use bridge returned `Native pipe startup failed`, with no available browser
surfaces, so a live browser inspection was unavailable. The only existing-screen
change passes a saved job ID to the unchanged assignment selector; no layout,
table, loading-state or navigation change was introduced. English/LTR and
Arabic/RTL selector/search/hydration and audit-label behavior were verified in
component tests; actual save/read/task commands were verified through HTTP.
The full task workspace remains with its Phase 16 browser acceptance gate.

## Translation and operator handoff

- English and Arabic contain **3,405** active keys. Seven audit labels were added;
  no existing key or wording was changed or removed. All **3,398** prior Arabic
  items, including administrator wording/provenance/flags, were preserved exactly.
- New Arabic values are generated drafts flagged `needs_human_review`.
  No administrator export was promoted and no persistent translations were
  published. Coverage, ordering, placeholders, terminology, stale keys and hashes
  pass validation.
- Apply **058 after 057** to an existing database. This task did not migrate
  `demo` or any other persistent database.
- Seed `database/seeds/disposition-notification-producers.sql` separately when
  deploying the feature. The seed preserves existing configurations. Configure
  and activate the producer through existing Notification Administration after
  reviewing language templates. No automatic activation or publication occurs.
- Restart API, WebUI and the eligibility worker after deployment. There are no
  new environment variables or template changes; the API template check passes.
- Phase 14 should invoke the private routing functions only inside a complete
  validated submission/decision command and a consistent transaction. Phase 15
  invokes the Manager-only round boundary within its atomic combined approval;
  an empty result does not start a round or generate a request.
