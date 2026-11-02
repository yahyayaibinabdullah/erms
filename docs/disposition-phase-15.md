# Phase 15 — Records Manager approval and proposal execution

Phase 15 adds the protected approval operation, atomic proposal effects and a
retryable governed execution report. It preserves the existing review forms and
Save behavior. Phase 16 owns the inbox and review workspace; Phase 17 owns
Request for Destruction generation, subsequent routing and authority decisions.

## Requirement-to-implementation-to-test traceability

| Approved requirement | Implementation and verification |
| --- | --- |
| Destruction §§5.3, 10–10.1, 18.13; DEST-19 | `approval.py` and migration 060 validate the complete active proposal set, exact reviewed membership, current task/claim, Manager role, access and optimistic versions. Approval-preview checksums bind the entire set rather than a client-selected subset. Timestamp values are canonicalized across database session timezones. Tests cover stale members, edited proposals, unavailable links and hidden endpoints, current assignment loss, wrong roles, missing claims and concurrent approval. |
| Destruction §10.1; Common §§9, 12, 15 | Preflight validates every underlying vital/security, hold, relationship and retention authority before resource changes. Security upgrades respect current clearance and planned parent/child hierarchy. Relationships retain exact identity and normalize symmetric links when detecting conflicts. Each operation executes as the approving authenticated person, with `actor_type='user'`, actual acting role and a link to the proposal/approval. Individual reasons take precedence; otherwise execution uses the round's mandatory overall reason. All seven executable governance types, every privilege, hold-management authority, conflicts, and late-failure rollback are tested. Removal marks prevent approval. |
| Destruction §10.1; DEST-20; Common §9.1 | Direct protection/retention removals affect complete governing units. Repeated relationship evaluation removes newly outside-linked units until membership stabilizes. Effects attribute cascades to their causal proposals. Existing independent blockers and baseline outside links do not authorize automatic removal. Ordinary status 6 returns to 2; recalculated status 1 or another eligible action is retained. Tests cover descendants, existing-link chains, new links combined with protection, direct outside links, matching/non-matching retention and preservation of unrelated blockers. |
| Destruction §§5.5, 6.6.1 | Manager Only performs one combined action, requiring its own nonblank overall reason and independent Manager authority. No Officer role, review queue or intervening submission is introduced. Empty jobs retain preparation/correction with a fresh direct task; earlier execution is not replayed in another round. A nonempty approved job has no open preparation task and cannot continue editing membership. The existing job projection reflects that task gate. Removal marks require correction in
Manager Only and rejection in a separate Manager review task. Manager Only reports use the actual Manager duty label. |
| Common §§16–17.8; Destruction §§18.3–18.5 | Immutable round execution data records reviewed and post-execution membership, effective rules, original proposals/proposers, actual executor, roles, reason source and outcomes. `disposition_proposal_effects` records resource changes, blocked units, direct/cascading removals and recalculation. Ordinary commands cannot mark proposals executed or erase effects/approval. Effects have an uncached, server-paginated authorized projection. Proposal/history redaction covers cascading effect roots. |
| Destruction §10.1; DEST-34 | `approval.generate_report` renders the frozen execution using the existing controlled Word/PDF pipeline and stores it as a governed record in the current Generated reports destination. It retains original proposers, execution attribution, reason source, removed units and proposal-history references. The report source must match its immutable approval; a per-round unique index prevents duplicate current reports while preserving legacy artifacts. Retry never executes resource operations again, including after job termination. Actual HTTP failure/retry, PDF bytes/checksum, provenance and one-record behavior are verified. |

## Transaction and phase boundaries

The SQL approval function locks the job, round, current memberships, full-unit
resources, proposal rows, selected holds and relationship endpoints. It freezes
policy/catalogue changes while validating the plan. All resource changes,
complete-unit status changes, membership closures, approval, effects and audit
records commit together. A failure leaves the pre-approval state unchanged.
Active hold selections close when a proposal is executed; immutable proposal
and round snapshots retain every selected hold and its metadata, and the real
hold assignments remain applied. Identical idempotent desired changes produce
truthful outcomes without falsely recording another resource mutation.

The private transaction context is scoped to the actual command/person/role and
is removed before commit; it is not a new workflow engine or a public bypass.

Report rendering and staging run after the approval commit, on a fresh
transaction using the existing content-storage visibility model. A renderer,
destination or storage failure returns an explicitly pending report and retains
the approved execution. Retrying uses the frozen approval data and a unique
round identity. A per-round database mutex serializes report creation across
API instances without holding workflow locks during rendering. The document
records its actual generation time separately from the frozen execution time.
Pending report events are audited. If that failure audit cannot
be saved, the API explicitly returns 503 with `approval_committed=true`; it does
not silently hide the audit failure or claim approval rolled back.

An empty Standard/Simplified job returns to its assigned Officer's correction
task. Manager Only retains its preparation/correction stage and creates a fresh
direct task. A successful nonempty approval completes the Manager task and
retains the current stage until Phase 17 generates the request from
`approval_execution.post_membership`, `post_rules` and the approved job facts.
No external request or waiting-stage transition is fabricated in this phase.
The `approved_job_version` and immutable snapshots support that later check.

## Verification and preservation

Evidence is under `docs/verification/disposition-phase-15/`. The broad scoped
regression passed **324 tests**. The final approval module passed **46 tests**;
report timestamp/deduplication/HTTP recovery passed a further two targeted
checks, and the final record-target report projection passed its all-type check. Additional final checks cover the stricter task
gate, report provenance, pending-report audit failure, terminated-job recovery,
Manager Only duty labels and effect projections. Final upgraded behavior passed
**48 tests**. The frontend/audit-label and traceability checks passed **28**.
These runs overlap; their counts are not a sum of unique cases.

An older recalculation test changed only a workflow-stage column, without
creating the corresponding correction task. Its fixture is reconciled with the
real review round and rejection so it tests the approved own-open-task rule.
The full compatibility run passed 32 other cases; the corrected fixture passed
its focused rerun. No
production permission or task gate is weakened to accommodate that fixture.

The independent upgrade probe compares canonical and upgraded columns,
constraints, indexes, private functions, resource/content triggers, the shared
audit view and the execution-audit trigger. It verifies every pre-existing
public/private table row is unchanged. Database-backed tests use newly named
disposable databases, and cleanup is independently checked.

Both pages of generated Standard and Manager Only execution PDFs were rendered and visually inspected using the PDF skill. Bilingual
headings, actual proposer/executor, reason source, unit removal and history
references are legible without clipping. No WebUI table or layout was added;
shared audit labels are checked in English and Arabic. Phase 16 retains full
live-browser workspace acceptance.

## Deployment and translations

- Apply `060_disposition_approval.sql` after 059 (and pending 058/059 where
  applicable). New databases use `database/schema.sql` alone. No persistent
  database, including `demo`, was migrated or used for tests.
- Restart API and WebUI on deployment. There are no new environment settings
  or service-template changes.
- Three contextual audit keys were added for approval/application, execution
  and pending report generation. English and Arabic now each contain **3,414**
  active keys. All **3,411** previous Arabic items retain exact wording,
  provenance and flags; no administrator export was promoted.
- The three new Arabic translations are generated drafts marked
  `needs_human_review`. Exact-key coverage/order, placeholders, nonblank values,
  new-entry terminology/quality, provenance and hashes pass validation.
  Explicit deployment seeding and normal human review/publication remain
  operator actions. Persistent translations were not changed.
- Keep report retries separate from approval execution. Phase 17 must consume
  the successful round's post-execution membership/rules and frozen job facts,
  exclude removed units, and require renewed review if approved facts change.
