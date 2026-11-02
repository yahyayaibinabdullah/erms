# Phase 14 — proposals and review decisions

Phase 14 implements the protected review backend. Save persists work without
executing proposals, changing membership, completing tasks, or advancing the
workflow. Phase 15 owns Records Manager approval and execution; Phase 16 owns
the task inbox, forms, proposal panel and browser acceptance.

## Requirement, implementation and verification

| Approved requirement | Implementation and acceptance evidence |
| --- | --- |
| Destruction §§5.3, 18.3–18.4 | Migration 059 and `disposition/proposals.py` support removal marks, vital status, higher blocking security, multiple existing holds, directed aggregation relationship creation, exact aggregation/record relationship removal, and complete root retention overrides with classification-derived rule snapshots. `test_all_types_save_atomically_without_resource_membership_or_stage_changes` and the invalid-payload cases verify scope, exact fields, history and no premature effects. |
| Destruction §§5.3, 6.5, 17.5 | Actual task ownership, current role/access, queue claim and optimistic versions gate creating, revising and withdrawing any active proposal. Original proposer remains immutable; last editor is separate. Successor Officer, all participant roles, task-only reviewers, hidden endpoints, closed/executed/failed outcomes and direct-write bypass cases are tested in `test_disposition_review_edges.py`. |
| Destruction §§6.6–6.6.1; DEST-41 | Save atomically persists changes, removal marks, the current participant's notes and the preparer's partial overall reason. Own notes are versioned and cannot overwrite another author's notes. Fresh connections and actual HTTP restore saved work. Stale notes roll back proposal edits; concurrent saves have one winner. Individual governance reasons are optional, removal-mark reasons and submission reasons are nonblank. |
| Destruction §§7.2–10; Common §17.6 | Submission snapshots the complete in-scope active proposal set, membership/versions and overall reason. File Administrator forwarding and Unit Manager approval route the whole job. Removal marks block Unit Manager approval and Officer resubmission. Rejection preserves decisions/notes and returns correction; reopened members can still be rejected. Resubmission follows the saved route and carries every remaining active proposal into a new round without replacing its proposer or deleting earlier rows. |
| Common §§15–16, 17.8; security/holds/relationships/retention contracts | No new privilege or content ACL grant. Proposal access checks include both relationship endpoints and every hold. Missing links/holds and inactive types prevent forwarding rather than disappearing. Underlying execution authorization remains a separate Phase 15 gate. Shared audit redaction now receives workflow metadata snapshots as well as dedicated before/after columns. Hidden endpoint metadata and round snapshots are redacted. |
| Destruction §§6.5–6.6, 18.3 | Uncached server-paginated proposal, notes, rounds, decisions and combined job-history projections support the later workspace. Two-character bounded candidate search and selected-ID hydration return at most 25 current authorized matches. Real pagination and selected-hold hydration are tested. |

Proposal and note mutations retain every saved version in immutable event
history, including actor, acting role, stage, round, time and before/after data.
Withdrawal of a proposal whose external endpoint has become hidden is permitted
under the participant's current job/task authority; it returns only the proposal
identifier/version/state and does not reveal the hidden payload. This allows an
invalid proposal to be withdrawn while its protected history stays redacted.

Each resubmission creates a new row for every still-active in-scope proposal,
linked through `carried_from_proposal_id`, with its original proposer and prior
last-editor attribution preserved. Removed units and prior-round rows remain
historical. Current reviewers cannot edit earlier-round or closed outcome rows.

## Verification

Passing logs and localization/cleanup evidence are in
`docs/verification/disposition-phase-14/`. Database checks use uniquely named
fresh disposable databases; the independent upgrade probe compares the complete
059 schema, private functions, constraints, triggers, indexes and shared audit
view with a canonical fresh database, and checks every pre-existing table row.
The upgraded behavior run applies HEAD's schema, then 058 and 059 explicitly.

The broad regression ran 347 cases: 346 passed and one Phase 10 assertion
expected 403 for a workspace read that has used a non-disclosing 404 since the
governed evidence/task workspace was introduced. That assertion was reconciled
with the existing access contract and the complete query module rerun (15 passing compatibility checks, including
closed outcomes and seed-catalogue restoration). An enabled-notification HTTP
submission and its exact retry also passed. Final
closed/executed/failed fixture cases were checked separately. The upgraded
behavior run passed 31 cases; the frontend/traceability run passed 28.

The final progress gate treats a missing private decision payload as a normal
progress check; only an explicit rejection may bypass progress to return a
changed job for correction.

The final affected workflow/review run passed **73 tests** after that hardening.

The Phase 7 decision fixtures now use an authorized Unit Manager approval to
exercise immutable decisions and stale snapshots. They no longer simulate a
successful Records Manager approval, which must remain blocked until Phase 15
can execute the complete proposal set atomically.

Only audit-label mappings and their catalogues changed in the WebUI for this
phase; there are no new forms, tables, layout or navigation changes. English and
Arabic labels are checked through the shared renderer. Full review-workspace
LTR/RTL and live browser verification remain Phase 16 acceptance gates.

## Deployment and translations

- Apply `059_disposition_review.sql` **after 058** on an existing database;
  new databases use `database/schema.sql` alone. This work does not apply
  migrations to `demo` or any other persistent database.
- Restart API and WebUI when deploying. There are no new environment settings
  or service-template changes.
- Six contextual audit keys were added. English and Arabic each contain
  **3,411** active keys. All **3,405** previous Arabic items retain their exact
  wording, provenance and flags; no administrator export was promoted.
- New Arabic entries are generated drafts flagged `needs_human_review`.
  Coverage, order, nonblank text, placeholders, new-entry terminology/quality,
  provenance and artifact hashes are verified. Existing curated translations
  are preserved. Explicit seeding and normal human review/publication remain
  operator actions; persistent translation data was not changed.
- Phase 15 must replace the explicit Manager-approval execution gate only when
  the complete authorized execution plan and its atomic rollback are available.
  It must use the overall submission reason where an underlying operation
  requires a reason and the individual proposal has none.
