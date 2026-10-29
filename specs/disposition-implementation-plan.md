# Administration Configuration and Disposition Implementation Plan

**Status:** Approved implementation plan
**Approved:** 12 October 2026
**Revision:** 1.4
**Amendment approved:** 21 October 2026
**Date:** 12 October 2026

## 1. Purpose and scope

Implement the shared Administration Settings foundation, common disposition
rules, and destruction process in the order below. Each phase delivers a bounded
part of the system with its own verification. Destruction must not be made
available for operational use until its complete workflow and recovery paths
have passed the final release gate.

This plan follows these specifications:

- [Administration Settings](administration-settings.md), revision 1.1;
- [Application Configuration](application-configuration.md), revision 1.1;
- [Disposition](disposition.md), revision 1.9; and
- [Destruction Process](destruction-process.md), revision 1.2.

The destruction specification is named `destruction-process.md` in this
repository. All four specifications and this implementation plan are approved
as of 12 October 2026. Approval records the agreed implementation contract;
it does not claim that any phase has been implemented or verified.

The plan includes the broader application-configuration migration as distinct
phases because it shares the same settings foundation. The four configuration
decisions are now approved: a 30-second general cache, all database-managed
settings editable, preservation of existing non-default values during migration,
and atomic saves of related settings. The broader migration scope is included
in the approved specification and plan.

Permanent transfer, selective transfer, and retention as local archives receive
their specified common statuses, job types, and integrity rules. Their
action-specific workflows require their own specifications; this plan does not
invent them. No generic workflow engine, digital signatures, or new privilege
model is included.

## 2. How to execute the phases

The numbered order is the recommended implementation order. Dependencies stated
for each phase identify what must already be verified. A phase can take several
development sessions; it is not a promise to fit a complete subsystem into one
agent turn. If a phase grows too large, split its implementation into smaller
changes while preserving its completion gate.

For every phase, maintain a requirement ledger linking the applicable source
section or requirement ID to implementation locations, named tests, and actual
verification results. Include requirements in prose that have no ID. A checked
box or a test name without a passing result is not completion evidence.

Every phase follows these rules:

- Inspect existing implementation first and reuse working subsystems. In
  particular, verify existing organizational-role fields, access control,
  notifications, storage, retention rules, and event history before adding them.
- Add schema changes to the self-contained canonical schema and an independent
  upgrade migration. Verify both paths. Keep seeds separate and preserve
  existing data and grants unless an approved requirement changes them.
- Run database tests only on newly created, uniquely named disposable databases.
  Initialize each from the canonical schema or the required migration path;
  drop it after success or failure and report cleanup failures. Never test
  against `demo`, `demo3`, or another persistent database.
- Test protected commands through supported entry points and attempted bypasses,
  including direct SQL where required. Exercise concurrency, stale versions,
  rollback, retries, and authorization failures at the phase that introduces
  the operation.
- For each UI phase, verify real save-and-reload behavior and server results,
  not merely rendered controls or mocked success responses. Verify English LTR
  and Arabic RTL, the established Wathiq table design, bounded selectors, true
  server pagination, accessibility, and deliberate loading/error/empty states.
- Follow the WebUI performance contract and translation-artifact rules. Preserve
  curated Arabic wording and provenance; verify key coverage, ordering,
  placeholders, terminology, stale keys, and artifact hashes.
- Reconcile environment templates whenever configuration ownership changes.
  Preserve private values; use the authoritative API template and its sync/check
  utility. Document restart requirements and operator actions.
- Record remaining work honestly. Do not expose an unfinished irreversible
  action or describe a partially implemented workflow as complete.

## 3. Ordered phases

### Phase 1 Establish the implementation baseline

**Priority:** Foundation. **Dependencies:** None.

**Scope:** Build the requirement ledger for all four specifications, including
their referenced security, relationships, retention, storage, messaging,
internationalization, and UI contracts. Inventory existing code, schema,
migrations, tests, and deployment settings. Record what is already implemented
and what requires extension. Identify exact integration points and document
technical transaction boundaries without changing product rules.

Apply the approved Application Configuration section 12 decisions: 30-second
general cache, every database-managed setting editable, preservation of existing
non-default values, and grouped atomic saves. Include tests for each decision.
These four decisions and the applicable scope are approved; they are no longer
outstanding approval gates.

**Verification and completion:** Every source requirement has a phase owner and
planned verification. Existing claims of implementation have evidence. Any
remaining product decision identifies precisely which later phase it blocks.

**Completion record — 14 October 2026:** Complete. The
[Phase 1 baseline](../docs/disposition-phase-1.md) and
[requirement ledger](../docs/disposition-requirement-ledger.json) record all
100 acceptance IDs, 171 numbered prose sections, referenced contracts,
93 setting-inventory rows, the four approved configuration decisions,
integration/transaction boundaries, and planned verification owners.
103 disposable-database API regressions, 31 database-free WebUI checks,
and 27 traceability/local-environment tests passed. Database creation and
cleanup succeeded; source coverage, compilation, environment-template sync,
shell syntax and whitespace checks passed. Runtime requirements remain planned.
Decision D-01 applies to historical audit-payload minimization before Phase 21
retained-record finalization and does not block Phase 2. No runtime/schema,
environment-template, translation-artifact or deployment changes were made.
Measured active time: **1.29 hours**; see Section 6.

### Phase 2 Build the shared settings registry and protected administration API

**Priority:** Foundation. **Dependencies:** Phase 1.

**Scope:** Implement the single typed settings registry, database persistence,
defaults, validation, versions, authorized reads and updates, required change
reasons, and atomic audit history. Grant `app.settings.manage` through System
Administrator using the established privilege mechanism. Define an explicit
registry `category` for each setting and supply it with translated labels
through the API; do not infer it from keys or duplicate it in the settings table.
Implement protected
SMTP-secret storage, masked/write-only responses, and server-only resolution.
Use the user-approved API deployment key `APPLICATION_SETTINGS_ENCRYPTION_KEY`
from local `.env`, with production shell environment precedence. SMTP passwords
remain encrypted database settings; missing key configuration blocks only
credential replacement/resolution.
Register the approved Disposition and Email settings, including the six-month
reminder default, without inventing missing destinations or credentials.

Persist provenance distinguishing untouched defaults from intentionally configured
values, including values equal to defaults. Provide per-database migration
completion tracking that supports additional migrated keys in later releases.
Verify provenance, atomic completion updates, and concurrent configuration edits.

Implement the approved general-cache policy and direct committed reads at job
creation, artifact saving, and email sending. Each operation captures one
consistent set of settings; failures cannot substitute stale settings at those
boundaries. Do not migrate unrelated legacy consumers in this phase.

**Verification and completion:** Fresh-schema and upgrade parity; preserved
existing settings; invalid values and inconsistent reference rejection;
unauthorized access; optimistic conflicts and rollback; cache isolation and
refresh failure; fresh operation reads; no secret in responses, logs, history,
or ordinary caches; startup with optional settings unset.

**Completion record — 14 October 2026:** Complete. The shared settings registry,
protected GET/PUT API, canonical schema and independent migration 050, safe audit,
provenance/completion, 30-second cache, fresh operation captures, and encrypted
SMTP secret representation are implemented. The approved deployment key uses
`APPLICATION_SETTINGS_ENCRYPTION_KEY` with shell-over-dotenv precedence. Evidence
and phase-scoped requirement coverage are recorded in
[Phase 2 verification](../docs/disposition-phase-2.md) and the maintained ledger:
80 fresh-schema, 82 upgrade, 105 compatibility, one fixture-guard, 22 settings
unit, 16 frontend regression and 27 traceability/local-environment checks passed.
Every disposable database was created and dropped. Templates and 118 new draft
translation keys are reconciled; 3,023 prior Arabic items are preserved.
Persistent databases were not migrated; operator instructions accompany 050.
Phase 3 UI and later consumer/workflow integrations remain assigned work.

### Phase 3 Deliver Administration Settings and configuration warnings

**Priority:** Foundation. **Dependencies:** Phase 2.

**Scope:** Build the reusable Settings page with Disposition and Email groups.
Implement two-character remote search and paginated Browse for schemes and
terminal classifications, selected-value retention, and consistent scheme and
destination validation. Show setting effects and protected credential controls.
Include visible translated explanations for every setting: purpose, plain-language
type, units, limits, default/unset meaning, dependencies, and effective timing.
Verify their presence and readability in both interface languages.
Add Governance Custody warnings for missing destination settings and missing
suitable open roots, with authorized navigation to Settings and warning clearance.

**Verification and completion:** Browser save/reload proves persisted values,
including role restrictions and secret handling. Test deep and large
classification trees without full downloads, stale selections, setting changes,
missing roots, warning clearance, LTR/RTL, and translation/performance checks.

**Completion (14 October 2026):** Phase 3 is complete. See
[Phase 3 verification](../docs/disposition-phase-3.md) and the maintained ledger:
all 51 settings have bilingual controls and visible explanations; grouped
reasoned/versioned saves, protected credentials, bounded scheme/terminal Browse
and search, current destination/root warnings and restricted navigation pass.
68 disposable-database API, 76 frontend and 27 traceability/environment checks
passed, together with live English/Arabic save/reload, deep/large-tree paging,
warning clearance, role restrictions, measured RTL and translation checks. All
seven test/preview databases are confirmed dropped. No persistent database or
private environment values were changed. New Arabic wording remains generated
drafts for explicit administrator review/publication. Phase 4 completion is recorded below.

### Phase 4 Migrate general application and WebUI settings

**Priority:** Configuration completion. **Dependencies:** Phases 1–3.

**Scope:** Migrate Application Configuration sections 5.1 and 5.4 consumers to
the registry: timezone and medium defaults, review warning window, dashboard,
selector, and administration-page limits. Make every database-managed setting
editable and save related settings atomically. Preserve existing non-default
values through reviewed migration before switching consumers, resolving invalid
values or conflicts explicitly. Remove corresponding environment fallbacks and duplicate WebUI
authority; preserve deployment-managed settings.

**Verification and completion:** Conflicting old environment values cannot
override database settings after cutover. Verify migrated non-default values,
existing database-value preservation, conflict handling, grouped rollback,
runtime changes, consumer behavior, existing user preferences, default
preservation, pagination, and reconciled templates.

Phase 4 also delivers the explicit preview/apply command and launcher readiness
check specified in Application Configuration section 9. The command operates
before affected services start, targets one explicit database, preserves the
private `.env`, and reports obsolete entries. Test preview without writes,
conflicts, invalid values, grouped rollback, per-database isolation, safe reruns,
and incomplete-migration startup blocking. Extend the same command for the
additional setting groups in phases 5 and 6; do not build separate importers.

**Completed 14 October 2026:** Nine general/interface consumers now use database
settings exclusively. Reviewed per-database preview/apply, explicit conflict
resolution, atomic provenance/audit/completion and startup readiness are delivered.
125 API, 227 WebUI and 29 traceability/environment/CLI tests pass; English/Arabic
live runtime freshness, preference precedence, pagination and repeated navigation
are verified. All disposable databases were dropped. Nine obsolete template
entries were removed; no private environment or persistent database was changed.
All 3,188 Arabic items were preserved. See `docs/disposition-phase-4.md` and the
phase-scoped ledger evidence. Total active time: **2.25 hours** (first interruption
boundary approximate; offline interval excluded). Phase 5 is next.

### Phase 5 Migrate content and authentication policy settings

**Priority:** Configuration completion. **Dependencies:** Phase 4.

**Scope:** Migrate sections 5.2 and 5.3 in two bounded implementation changes:
content upload, segmentation, cleanup and conversion policy; then authentication,
session and password policy. Update operational workers as well as request
handlers. Preserve the specified treatment of existing passwords and expired
sessions.

**Verification and completion:** Exercise upload boundaries, segmented content,
conversion limits, cleanup batches, active/expired sessions, lockout and password
changes. Verify runtime refresh, failure behavior, and removal of every migrated
environment read. Each change passes its own regression tests before the next.

**Completed 14 October 2026:** All seven content and eight authentication/session
settings now use the database registry at request and operational worker boundaries.
The existing migration extends to 24 keys and preserves earlier completion.
Content passed 37 regressions before authentication implementation; broad regression
passed 132 tests, followed by 28 boundary/authentication and 25 final readiness
checks. 84 WebUI and 44 traceability/cache/CLI/environment tests passed. All nine
disposable run/isolation databases are confirmed absent. No private environment,
persistent database, schema or translation item changed. Deployment requires a
new reviewed 24-key preview/apply before upgraded API/cleanup workers start.
See `docs/disposition-phase-5.md` and phase-scoped ledger evidence. Total measured
active time: **0.30 hours**. Phase 6 is next.

### Phase 6 Complete search configuration and deployment reconciliation

**Priority:** Configuration completion. **Dependencies:** Phase 5.

**Scope:** Migrate section 5.5 search, indexing, cleanup, history and rate-limit
settings and all API-owned workers. Migrate `AUDIT_TRAIL_SEARCH_RESULT_LIMIT`
to database management with default 1000, positive-integer validation, the
30-second cache, and no restart requirement. Preserve existing non-default
values and remove its environment lookup and template entries at cutover.
Remove the separate WebUI full-text flag.
Complete the production-setting inventory, installation/upgrade procedure, and
environment-template reconciliation. Preserve Audit Trail count/pagination
protections and the separately approved local environment reconciliation.

**Verification and completion:** API/WebUI agreement, scheduling and cleanup,
rate limits, worker refresh, no migrated environment fallback, and template
checks pass. Verify Audit Trail invalid-value rejection, non-default migration,
runtime cache refresh, consistent per-request count/pagination bounds and
API-provided `result_cap`, and absence of environment fallback. Verify registry
category coverage, translated UI grouping, and no key-prefix inference.
Every production setting has exactly one documented authority.

**Completed 14 October 2026:** All ten search/indexing settings now use database
policy, including one Audit Trail cap captured per request. UI visibility follows
API responses; the separate WebUI flag is removed. Reviewed migration extends to
34 keys, preserving earlier completion. Canonical schema and migration 051 supply
saved scheduling policy for direct database writes. The 117-setting production
inventory, service templates, append-only bootstrap and upgrade guide agree.
36 search/indexing, 63 integration, 14 Audit Trail, 223 frontend and 46 supporting
checks passed; bilingual runtime availability/cap/grouping and request counts were
verified live. All six disposable databases are confirmed absent. No private
environment or maintained translation item changed. See `docs/disposition-phase-6.md`
and phase-scoped ledger evidence. Total active time: **0.47 hours**. Phase 7 is next.

### Phase 7 Implement common disposition persistence and protected transitions

**Priority:** Disposition foundation. **Dependencies:** Phase 1; this approved
common work does not depend on completing the legacy migration in phases 4–6.

**Scope:** Implement resource outcome fields and the shared jobs, membership
episodes, tasks, review rounds, decisions, and document-link structures from
Disposition section 17. Enforce statuses 1–13, job types/lifecycle, controlled
stages, versions, terminal fields, and authorized transition operations. Pending
statuses require matching active membership. Propagate root changes to every
descendant in the same transaction. Establish immutable history and command
retry handling; later phases supply action-specific commands.

**Verification and completion:** Schema/upgrade parity, full-unit rollback,
invalid transitions, ordinary-CRUD and direct-SQL bypass attempts, concurrent
membership changes, terminal-field consistency, and historical-row preservation.

**Completed 15 October 2026:** Canonical schema and independent migration 053
implement the common resource outcomes, jobs, membership episodes, tasks, rounds,
decisions and governed-document links. Private actor/access/version/claim/state
operations, complete-unit deferred checks, immutable history and command receipts
protect the shared foundation. All 75 foundation cases passed on both fresh and
upgrade paths; 91 affected resource/authorization regressions and 39 supporting
checks passed. Catalogue parity and prior-data/grant/history preservation passed;
all 34 disposable databases are independently confirmed absent. No persistent
database, environment/template or translation artifact changed. Operational
eligibility, action-specific job/review commands and final execution remain in
their later phases. See [Phase 7 evidence](../docs/disposition-phase-7.md).
Total active time: **0.54 hours**. Phase 8 is next.

### Phase 8 Implement eligibility calculation and current blockers

**Priority:** Disposition foundation. **Dependencies:** Phase 7.

**Scope:** Implement effective-rule resolution, database timestamp calculation,
strict due-time comparison, and the bounded repeatable eligibility service.
Open roots stay at status 1. Evaluate vital status, disposition-blocking
security, and effective holds throughout the unit. Evaluate relationships
separately: they permit admission and acceleration but outside-job links prevent
final disposition. Include record endpoints, both directions, and all link types.

**Verification and completion:** Exact due boundary, leap/calendar behavior,
timezone display independence, local overrides, open roots, inherited holds,
hidden descendants, same-job links, concurrent changes, and repeated worker runs.

**Completed 2026-10-15.** Bounded database-clock eligibility and current
all-descendant protection/relationship facts are implemented. The 57-case suite
passed on both fresh and independent-upgrade paths; all 75 Phase 7 cases,
53 affected regressions, 39 tool checks and three shared-label/export checks
passed. Fresh/upgrade schema parity and existing-data preservation passed.
All 20 disposable databases, including failed runs, were independently confirmed
absent. Migration 054 is ready; no persistent database or service was changed.
Two new Arabic audit-label drafts preserve all prior curated entries and require
normal deployment seeding/review/publication. Evidence and operator steps:
[Phase 8 verification](../docs/disposition-phase-8.md) and the requirement ledger.
Total active time: **0.57 hours**. Phase 9 is next.

### Approved amendment: closure is required for all eligibility

**Approved:** 21 October 2026. **Requirements:** DISP-03 and DISP-13, Disposition Sections 2, 3, 6, 7 and 11.

Retention starts at closure; time spent open never counts. Every eligibility
path must keep open roots in status 1. Verify normal eligibility, recalculation
and reopening against this invariant and the strict due-date boundary.
Close an open root at database time in the same transaction as acceleration,
with existing closure authorization, unchanged prior closure dates, effective
subtree closure, and rollback of both changes on any failure. Move the action
to the effective retention-rule section and explain automatic closure in its
confirmation. Verify fresh-schema and migration paths, closure and permission
failures, blockers, retries and LTR/RTL presentation. The notification follow-up
below remains separately pending.

Implementation evidence (21 October 2026): canonical schema and migration
`072_acceleration_closes_root.sql`; 128 fresh-schema membership/eligibility
checks, 71 prior-schema-plus-migration checks, and an additional forced-failure
rollback check passed in disposable databases. Live preview confirmed closure
and eligibility together, reopening resets status 1, and the action's retention
card location in [English](../docs/verification/acceleration-closure/english.png)
and [RTL](../docs/verification/acceleration-closure/rtl.png). RTL uses English
fallback for unpublished disposition translations; revised Arabic confirmation
remains a generated draft requiring human review and publication. Catalogue
coverage/order, terminology and artifact-hash checks passed. Migration 072 has
not been applied to the persistent demo database.

### Approved correction: eligible-but-blocked acceleration

**Approved:** 22 October 2026. Implements Disposition §7/§9/§11 and DISP-13.
Normal and accelerated eligibility are independent of vital status, blocking
security levels and effective holds. Keep admission/execution checks, existing
closure permission and state-preserving hold rules. Normal holds allow closure;
closed preserve-state-held roots allow status-only acceleration. Do not remove
protections or add units to jobs automatically. Verify all four outcomes,
root/descendant/record protections, normal/preserve-state holds, open/closed
roots, unchanged holds/content/closure, retries, failed closure rollback and
continued rejection at admission. Implementation and verification are recorded
in [the protection correction report](../docs/verification/acceleration-protections.md).
Historical Phase 9 evidence below predates and is superseded by this correction
where it describes protections as acceleration blockers.
Verification (22 October 2026): 194 fresh-schema, 57 migration-path, 13 final-
execution protection and 25 WebUI checks passed. English/LTR and Arabic/RTL
confirmation verified in a disposable preview. Prerequisite 072 and migration
077 applied to demo without changing resource rows; Arabic source draft awaits
administrator review/publication.

### Approved follow-up: exceptional-acceleration notifications

**Approved:** 21 October 2026. **Status:** Implementation and verification pending.
**Requirement:** DISP-43, Disposition Section 11.1, and Destruction Process Section 3.

The existing acceleration action, reason capture and authorization are
implemented. Admission and execution blocker checks remain mandatory; blockers
do not prevent the eligibility change. Extend successful acceleration to trigger immediate
notifications through the existing subsystem to all active Information
Governance role holders and the accelerated root's owning Unit Manager.
Cover all four outcomes, authoritative owning-unit manager resolution,
effective role assignments, per-person deduplication across both audiences,
rollback, retries, confidentiality and live delivery. Keep the periodic
destruction-eligibility reminder independent. Historical phase completion
records below predate this amendment and do not certify this new requirement.

### Phase 9 Implement job membership and changing eligibility

**Priority:** Disposition foundation. **Dependencies:** Phase 8.

**Scope:** Implement creation, assignment/reassignment, per-item multi-add,
removal, and termination before irreversible work. Enforce one active job,
matching action, specific authorized assignee before first membership, and
rejection of redacted roots. Preserve every membership episode and terminated
job membership history. Add acceleration with reasons and blockers. Integrate
reopening, local/effective retention changes, and hierarchy changes with status
recalculation and explicit-removal requirements. Matching due members retain
pending status; incompatible members block progress.

**Verification and completion:** Mixed-success additions, simultaneous jobs,
repeated add/remove, assignment without access, open/reclosed roots, matching
and mismatching rule changes, unchanged inherited rules, required removal, and
all-or-nothing propagation. Terminal units cannot be readmitted.

**Completed 2026-10-15.** Protected job creation, specific assignment,
per-item membership, owning-unit rules, acceleration, pre-irreversible
termination and atomic reopening/rule/hierarchy recalculation are implemented.
Matching members retain pending status; incompatible/reopened members require
explicit removal and block progress. On each fresh/upgrade path, 201 full-suite
cases and three final CHECK cases passed; 83 affected API regressions, 39 tool
checks and five bilingual label/export checks passed. Final schema/055 catalogue
parity and existing active-membership/data preservation passed. All 26 disposable
databases were independently confirmed absent. Ten new Arabic audit-label drafts
preserve every prior item/provenance and require normal review/publication.
Migration 055 and deployment guidance are ready; no persistent database,
private environment or deployed service was changed. Evidence:
[Phase 9 verification](../docs/disposition-phase-9.md) and the requirement ledger.
Total active time: **0.58 hours**. Phase 10 is next.

### Phase 10 Deliver eligibility and common job screens

**Completed 2026-10-15.** Server-paged eligibility, owner grouping, protected
blocker explanations, common job management/history and descendant status
presentation are implemented. Real create/assign/add/remove/acceleration,
mutation feedback/freshness, authorization/redaction and desktop/mobile
LTR/RTL and keyboard checks passed. Final focused frontend checks: 110 passed;
final read/filter cases: 10 plus 1 passed; catalogue/publication checks: 19
passed; traceability checks: 24 passed. All 19 disposable databases were
independently confirmed absent. All 3,204 existing Arabic items were preserved;
133 new drafts retain human-review flags and require explicit review/publication.
No persistent database or deployed service was changed. Evidence:
[Phase 10 verification](../docs/disposition-phase-10.md) and the requirement ledger.
Total active time: **1.83 hours**. Phase 11 is next.

**Priority:** Disposition usability. **Dependencies:** Phase 9.

**Scope:** Build the eligibility listing, required filters/grouping/sorting,
blocked-unit explanations and protected redacted descendants. Add job creation,
assignment, membership management, history, and status display in descendant
metadata/search/browse. Show aggregate addition feedback and on-demand per-item
failure details (29 October 2026 amendment). Apply destruction-stage
restrictions when its stages are introduced; common controls must not bypass them.

**Verification and completion:** Real persistence, permission intersections,
large paginated lists, inaccessible root selection rejection, blocker rendering,
descendant status accuracy, repeat navigation, and LTR/RTL checks.

### Phase 11 Implement artifact destinations and governed evidence storage

**Status:** Complete (15 October 2026). Governed artifact storage, current-settings
destinations, versioned corrective uploads and authorized preview/history are
implemented and verified. Migration 056 is ready; no persistent database upgrade
was run. The 37 new Arabic entries remain flagged drafts for human review and
publication. Evidence: [Phase 11 verification](../docs/disposition-phase-11.md).
Total active time: **0.99 hours**; elapsed time: **1.36 hours**,
including the separately recorded blocked browser-tool wait. Phase 12 is next.

**Priority:** Workflow foundation. **Dependencies:** Phases 2, 3, and 7.

**Scope:** Implement current-settings destination resolution: latest open root
by `date_opened`, with larger ID breaking ties. Save uploads and generated
artifacts as governed records/components with job links, checksums, provenance,
and the specified transaction boundaries. Evidence and reports use separate
configured destinations; digital certificates use the evidence destination.
Block relevant tasks when no destination exists. Warn before saving to a changed
destination while preserving earlier records. Keep job evidence outside the
units scheduled for destruction.

Implement authorized preview and correction of uploaded evidence by the assigned
Records Officer or authorized Records Manager, preserving every version and
original confirmation. Generated documents cannot be replaced through upload
correction.

**Verification and completion:** Root ordering and ties, closed/child/wrong
classification exclusion, concurrent closure/settings changes, missing-root
warnings, rollback, retry deduplication, evidence-version authorization, and
original-record preservation.

### Phase 12 Implement controlled Word templates and PDF generation

**Status:** Complete (15 October 2026). See `docs/disposition-phase-12.md` and
the requirement ledger for scoped verification. Measured elapsed/active effort: 1.31 hours.
Migration 057 is ready but not applied to persistent databases; 24 new Arabic
drafts require review/publication. Phase 13 is next.

**Priority:** Workflow foundation. **Dependencies:** Phase 11.

**Scope:** Create the specified default Word templates under
`templates/disposition/destruction/` for the request, digital certificate,
proposal execution report, and physical preparation report. Implement template
download, validation, revision upload, retained versions, and artifact provenance.
Generate PDF from the selected valid template revision. Follow the specified
mandatory fields, Arabic-first bilingual layout, RTL/LTR handling and Changa
font requirements; no signature blocks. Do not create templates during planning.

**Verification and completion:** Valid/invalid Word files, required fields and
repeating groups, role authorization, revision history, deterministic artifact
linkage and retry behavior. Render representative short and multipage PDFs;
inspect Arabic shaping, English direction, fonts, pagination, and overflow.

### Phase 13 Implement destruction routing and shared task operations

**Priority:** Review workflow. **Dependencies:** Phases 2, 7, and 9.

**Scope:** Capture Standard/Simplified route at job creation. Implement allowed
owning-unit scope, descendant-unit membership, and owning-unit editability only
while active, empty, and never submitted. Resolve File Administrator from the
nearest configured unit; no configured role skips the stage, while an unusable
configured role blocks it. Resolve the job unit's manager and required governance
profiles. Implement direct assignments, role queues, atomic claims, release,
reassignment, eligibility loss, round routing, and task history.

**Verification and completion:** Both routes, nearest ancestor, no-role skip,
configured-unusable block, no implied resource access, concurrent claims, role
loss, first-submission locking, correction routing, and same-person Officer/
Manager participation when independently authorized.

### Phase 14 Implement proposals and review decisions

**Priority:** Review workflow. **Dependencies:** Phase 13.

**Scope:** Implement every specified proposal type, payload validation,
multi-hold selections, relationship identity, and root retention overrides.
All four participants can revise/withdraw active proposals during their own
authorized open task; preserve original proposer and every change. Individual
governance reasons are optional; proposed-removal reasons and the Officer's
overall submission reason follow their separate mandatory rules. Implement
optional attributed Review notes, own-note editing, rounds and decisions.
Officer membership removal is immediate only in preparation/correction;
relationship removal remains a proposal.

**Verification and completion:** Each proposal type, no premature resource
mutation, successor reviewers, claim checks, closed/executed edit rejection,
history, note ownership, required reasons, removal marks, rejected rounds and
complete saved-route resubmission.

### Phase 15 Implement Records Manager approval and proposal execution

**Priority:** Review correctness. **Dependencies:** Phases 11, 12, and 14.

**Scope:** Approve the exact reviewed membership and complete active proposal
set under current authorization and versions. Execute underlying operations as
the approving Records Manager with `actor_type = 'user'`; retain proposer and
revision history. Use the overall submission reason when an execution needs a
reason and the proposal has none. Compute direct and cascading membership
removals to a stable result, with correct statuses. Reject unresolved conflicts
and roll back the entire operation on failure. Return an empty job to the
Officer. Produce the governed proposal execution report for the successful round.

**Verification and completion:** Every underlying privilege, including retention
administration and relationship authorization; stale endpoints; combined
proposals; cascading removals; empty jobs; approval snapshots; atomic rollback;
execution attribution; and report retry without re-executing proposals.

### Phase 16 Deliver the task inbox and review workspace

**Priority:** Review usability. **Dependencies:** Phases 13–15.

**Scope:** Deliver paginated My tasks, direct/queue/claimant display, correct
task forms, workflow timeline, job membership, attributed proposals, reasons,
Review notes, evidence preview, and history. Start the process diagram with
Start, then active job creation and Officer preparation; end with Completed and
End. Show skipped stages and the saved route. Expose only the actions authorized
for the current task, including task-only File Administrator/Unit Manager work.

**Verification and completion:** Role-by-role live-browser review and correction
cycles on both routes; evidence visibility; unauthorized actions; saved proposal
changes; concurrent/stale forms; paginated large jobs; LTR/RTL and performance.

### Phase 17 Implement external requests and authority decisions

**Priority:** External approval. **Dependencies:** Phases 12, 15, and 16.

**Scope:** Generate the request PDF from post-proposal membership, grouped by
terminal classification and effective rule, with counts, explicit local-rule
sources, required job details, and configured authority name. Record approval
with its letter and unique never-reused destruction number, accepting the
specified characters up to 20 characters. Record rejection with mandatory notes
and letter; return to Officer correction and repeat the saved internal route.
Retain separate requests/decisions and never replay already executed proposals.

**Verification and completion:** Group counts and local overrides, removed-unit
exclusion, large requests, number boundaries and uniqueness after termination,
atomic governed evidence creation, repeated rejection cycles, new forms, and
approval invalidation rules.

### Phase 18 Implement external document email and eligibility reminders

**Priority:** Communication. **Dependencies:** Phases 2, 8, 13, and 17.

**Scope:** Implement shared external PDF sending with current recipient/SMTP
settings, exact artifact version, repeat explicit sends, request deduplication,
durable per-attempt status and audit. Officer sends requests; Manager sends the
digital certificate once available, including after completion. Distinguish SMTP
acceptance, failure, and unknown outcomes without claiming inbox delivery.

Implement configurable calendar-month eligibility reminders to active effective
Officer and Manager profiles supplying `disposition.jobs.manage`, deduplicated
per person/interval using durable checkpoints. All system notifications use the
existing messaging subsystem. Reminder text omits protected metadata and links
to the authorized eligibility listing.

**Verification and completion:** Isolated mail test transport; TLS/settings
validation, secret-safe errors, retry/resend distinction, configuration changes,
navigation persistence, authorization, no workflow advancement by sending,
calendar boundaries, duplicate workers, and reminder deduplication after message
purge. Certificate end-to-end sending is completed in phase 22.

### Phase 19 Implement physical preparation and confirmation

**Priority:** Irreversible-action preparation. **Dependencies:** Phases 11, 12,
and 17.

**Scope:** Route using the complete hierarchy's media. Generate and store the
physical preparation PDF, grouped by terminal classification, with assigned
and current locations, prescribed descendant counts, non-overlapping totals,
and missing/inherited-location treatment. Support report versions. Recheck
blockers before physical work is authorized. Confirm offline destruction only
with the checkbox, unique certificate reference, upload, actor/time, and immutable
physical scope; commit confirmation and governed evidence together.

**Verification and completion:** Physical descendants under digital parents,
mixed units, location rules and counts, report destination, concurrent blockers,
missing evidence, duplicate confirmation/reference, rollback and correction
without rewriting confirmation. Operational destruction remains unavailable
until recovery and completion phases pass.

### Phase 20 Implement termination and partial disposition recovery

**Priority:** Required before operational destruction. **Dependencies:** Phase 19.

**Scope:** Extend termination to irreversible outcomes. Preserve fully disposed
units at status 10, set partially disposed units and descendants to status 13,
preserve remaining digital material, and retain terminated membership/history.
After physical destruction, blockers or required corrections follow termination
and recovery rather than ordinary review/removal. Implement explicit IGU
resolution to selected eligibility status 2–5 with a required reason; bulk
resolution applies one status/reason to all applicable status-13 units atomically.
Allow subsequent admission to a matching new job under ordinary checks.

**Verification and completion:** Mixed completed/partial/unexecuted membership,
preserved content, authorization, all-or-nothing bulk rollback, terminal-unit
exclusion, historical facts, new-job admission, and recovery UI in both languages.

### Phase 21 Implement durable digital destruction and retained disposition records

**Priority:** Irreversible execution. **Dependencies:** Phases 19 and 20.

**Scope:** Implement explicit Manager confirmation, final fresh checks, bounded
worker claims, durable runs/unit progress/manifests, and idempotent resume. Remove
content and all prohibited renditions, OCR, indexes, previews, temporary and cached
copies controlled by Wathiq. Retain only the permanent disposition metadata
approved in Disposition section 14.2, protected and read-only; exclude destroyed
resources from ordinary views and prevent reuse or reopening. Record complete
executor, number, job, and separate physical/digital outcome information.

Treat this phase as three sequential changes: execution/manifest persistence;
storage and derivative deletion; then status finalization and read restrictions.
Do not enable execution until all three pass. Technical failures may resume only
under the specified valid approved scope; blockers and required corrections after
physical destruction use phase 20.

**Verification and completion:** Worker crashes at irreversible boundaries,
duplicate requests/workers, completed-unit retry exclusion, concurrent holds/
security/vital/relationships, partial storage failure, protected errors, manifest
minimization, no retained prohibited content, immutable outcomes, and restricted
disposition/audit access. Do not rely solely on mocked file deletion.

### Phase 22 Complete certificates and final task behavior

**Status:** Complete (20 October 2026). See `docs/disposition-phase-22.md` for
automated, English and Arabic live verification evidence. Operational release
remains subject to Phase 23.

**Scope clarification approved:** 20 October 2026. Separate evidence-file expiry
and deletion are outside this phase; protected governed evidence and permanent
provenance/history remain required.

**Priority:** Destruction completion. **Dependencies:** Phases 18 and 21.

**Scope:** Generate and save exactly one digital certificate as evidence before
completion when digital destruction applies. Support certificate-only retry
without repeating deletion. Create the Manager download task and allow repeat
certificate email using phase 18. Physical-only jobs skip digital runs,
certificates, and their tasks and complete with physical evidence. Show the
external-backups/copies warning. Persist progress across navigation and notify
completion, failure, or required action through existing notifications.

**Verification and completion:** Fully digital, physical-only, and mixed jobs;
certificate storage failure after successful deletion; missing destinations;
retry deduplication; complete final fields; download not gating completion;
post-completion send history; completion warnings; and evidence surviving unit
destruction. Verify supporting evidence and its permanent provenance/history
survive the original unit's destruction. A separate evidence-file expiry or
deletion workflow is outside this phase.

### Phase 23 Run complete workflow and upgrade acceptance

**Status:** Complete (20 October 2026). See `docs/disposition-phase-23.md`.

**Priority:** Release gate. **Dependencies:** All applicable preceding phases.

**Scope:** Execute the complete requirement ledger against the integrated
system. Verify fresh installation and representative populated upgrade paths on
disposable databases. Run Standard with direct/inherited/no File Administrator,
Simplified, repeated internal/external rejection, proposal revisions, both email
actions, destination changes, physical-only/digital/mixed outcomes, termination,
status-13 resolution, and a new job after recovery.

**Verification and completion:** Every approved requirement has passing evidence.
Include multiple concurrent users/workers, privilege loss, hidden descendants,
large/deep hierarchies, stale pages, server restart, storage/mail/database failures,
and settings changes between tasks. Complete live LTR/RTL, accessibility,
translation, pagination and performance verification. Resolve failures at their
owning phase; do not waive them as integration follow-ups.

### Phase 24 Prepare the controlled rollout and implementation handoff

**Status:** Complete (20 October 2026). See `docs/disposition-phase-24.md` and
`docs/disposition-rollout.md`. Preparation only; persistent deployment and
operational destruction require separate authorization.

**Priority:** Delivery. **Dependencies:** Phase 23.

**Scope:** Prepare the ordered migration/installation instructions, settings
setup, role/profile prerequisites, evidence/report roots, SMTP setup, templates
and font dependencies, worker startup, and operator recovery procedures. Explain
which settings require no restart and which remaining deployment settings do.
Document upgrade treatment of existing values and preservation of data/grants.
Provide exact colleague instructions to pull code, upgrade the schema, preview
and apply local settings migration for each database, verify values, and start
the stack. Explain conflict resolution, safe reruns, and when obsolete `.env`
entries can be removed after all intended databases have migrated. Rehearse
both a multi-database upgrade and a fresh installation on disposable databases.
Provide the completed requirement ledger and verification results.

**Verification and completion:** Rehearse installation and upgrade on disposable
environments, including an initially unconfigured deployment. Confirm warnings
and safe task blocking. Distinguish reversible deployment changes from content
already destroyed, which cannot be restored by code rollback. Applying changes
to persistent databases or enabling operational destruction requires the user's
deployment authorization; producing this plan does not provide it.

## Approved operational simplification — 20 October 2026

The user approved removing the temporary physical/digital implementation release
gates. After all migrations through 071, destruction is available subject to the
existing permissions and workflow checks. No per-database function rewrite or
separate enablement setting is required. Existing release-acceptance evidence
is retained; historical statements about temporary disabled execution describe
the earlier rollout only. See `docs/disposition-release-gate-removal.md`.

## 4. Requirement coverage index

The approved Records Manager Only and Save amendment extends these phases:

- Phases 2–3: register and explain all three route choices, retaining Standard
  as default and immutable route capture for existing jobs.
- Phase 13: implement direct Manager preparation/correction assignments,
  route-specific duties and stages, and the combined-action owning-unit lock.
- Phases 14–16: implement persistent Save for Officer, File Administrator,
  Unit Manager, and Manager tasks, including partial overall reasons, version
  conflicts and history. Implement Manager-only combined approval without a
  separate submission/approval task, retaining proposal execution safeguards.
- Phases 17–18: route external correspondence and rejection correction to the
  assigned Manager for Manager-only jobs, with the same evidence and email rules.
- Phase 23: run all three routes, including multi-day save/resume by each
  participant, no workflow advance on Save, combined approval, empty membership,
  external rejection, and unchanged authorization and destruction safeguards.

All references elsewhere in this plan to both routes now include the third
route wherever applicable. Phase timing continues under Section 6; this
specification amendment is not implementation time.

The following assigns every existing requirement ID to its principal phases.
It supplements, rather than replaces, the detailed requirement ledger and source
prose. Requirements spanning several phases are complete only when all their
applicable verification passes.

| Source requirements | Principal phases |
| --- | --- |
| ACFG-01, ACFG-02, ACFG-08, ACFG-10 | 1, 4–6, 24 |
| ACFG-03, ACFG-04, ACFG-05, ACFG-06, ACFG-07, ACFG-09, ACFG-12, ACFG-13 | 2, 4–6 |
| ACFG-11 | 3, 23 |
| ACFG-14, ACFG-15 | 2, 3, 11, 13, 18, 22 |
| ACFG-16, ACFG-17 | 2, 4–6, 23, 24 |
| Administration Settings sections 2–4 | 2, 3, 11, 13, 18 |
| Administration Settings sections 5–7 | 2, 3, 11, 23, 24 |
| DISP-01, DISP-02, DISP-17, DISP-25, DISP-37, DISP-38, DISP-42 | 7, 9, 10, 23 |
| DISP-03, DISP-04, DISP-05, DISP-06, DISP-08, DISP-09, DISP-10 | 8, 9 |
| DISP-07, DISP-27, DISP-28 | 9, 10 |
| DISP-11, DISP-12, DISP-13, DISP-21, DISP-24, DISP-26, DISP-29, DISP-32, DISP-34 | 9, 13, 20, 22 |
| DISP-14, DISP-15, DISP-16, DISP-20, DISP-30, DISP-35 | 19–22 |
| DISP-18, DISP-19, DISP-36 | 8, 9, 14, 15, 19–21 |
| DISP-22, DISP-23 | 20 |
| DISP-31 | 2, 9, 13–16, 20–22 |
| DISP-33 | 7, 17, 21 |
| DISP-39, DISP-40 | 7, 13–16 |
| DISP-41 | 7, 11, 12, 15, 17, 19, 22 |
| DEST-01, DEST-27 | 18 |
| DEST-02, DEST-28, DEST-31 | 13, 16 |
| DEST-03, DEST-04, DEST-05, DEST-18, DEST-24, DEST-29 | 14, 16 |
| DEST-06, DEST-19, DEST-20, DEST-34 | 15, 16 |
| DEST-07, DEST-08, DEST-30 | 17 |
| DEST-09, DEST-10, DEST-37 | 19 |
| DEST-11, DEST-12, DEST-26 | 21 |
| DEST-13 | 20, 21 |
| DEST-14, DEST-15 | 11, 21, 22 |
| DEST-16 | 7, 11–22, 23 |
| DEST-17 | 8, 14, 15, 19, 21 |
| DEST-21, DEST-22, DEST-23 | 13, 16, 22 |
| DEST-25 | 17, 19 |
| DEST-32, DEST-33, DEST-38 | 3, 11, 17, 19, 22 |
| DEST-35, DEST-36 | 18, 22 |
| DEST-39 | 12, 17, 22 |
| DEST-40 | 2, 3, 13–18, 23 |
| DEST-41 | 14–16, 23 |

## 5. Completion record for each phase

At handoff, record the phase's status, implemented requirement IDs and prose
sections, code/schema/UI locations, test names and results, disposable-database
creation and cleanup results, and any required browser/render evidence. Record
migrations, template/catalogue changes, deployment actions, and remaining gaps.

A phase is complete only when its implementation and verification are complete.
The release is complete only when all approved in-scope requirements have that
evidence. An unresolved product decision remains a decision for the user; it
must not become an undocumented implementation assumption.

## 6. Actual implementation time

Record actual hours for every phase to support future estimates. Begin timing
when implementation work on that phase starts, not when this plan was written.
Maintain the session log below as work proceeds and update the phase totals at
each handoff. A phase's completion record includes its total measured hours.

Use timestamped work sessions, with start and end recorded in UTC. Active elapsed
time includes inspection, implementation, required tests and their execution,
debugging, browser/PDF verification, and implementation documentation. Pause
timing for user-response waits, unrelated work, or external outages that prevent
progress. Record such waiting separately. Split sessions when switching phases;
do not charge the same elapsed interval to more than one phase. Concurrent tool
operations count once as elapsed time, not as summed tool durations.

Calculate hours from recorded timestamps, retaining minutes and reporting totals
to two decimal places. If timing was interrupted or a boundary was not captured,
mark that entry estimated or incomplete; never present reconstructed time as
measured. Do not invent retrospective timings. Calendar duration from first
start to final completion is separate from active hours and may span many days.

Record verification and corrections within the phase that performs them. Later
cross-phase acceptance belongs to Phase 23; a separately reopened implementation
phase receives its own additional correction session. Record the reason and
avoid double-counting. Preserve both the original completion total and later
rework so future benchmarks show the full cost.

### Session log

Append one row per work session. Use the notes to record scope, interruptions,
test runs, significant reuse, or rework that affects comparisons with future work.

| Phase | Start UTC | End UTC | Active hours | Excluded waiting hours | Measurement quality | Work and notes |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-14 04:24:21 | 2026-10-14 05:41:29 | 1.29 | 0.00 | Measured | Source/setting ledger, code/schema/test inventory, approved decisions, integration and transaction boundaries, 103 disposable-DB + 31 UI + 27 traceability/local-env checks passed; disposable DB created/dropped; D-01 recorded for Phase 21 only. Final handoff bookkeeping follows the captured end boundary. |
| 2 | 2026-10-14 05:52:04 | 2026-10-14 07:21:03 | 1.48 | 0.00 | Measured | Shared settings registry/API/schema/cache/audit/provenance, approved env encryption key and encrypted SMTP password, current capture helpers, templates/upgrade guidance, preserved curated translations, fresh/upgrade/compatibility and unit checks passed; all disposable DBs dropped. Final completion bookkeeping follows the captured end boundary. |
| 3 | 2026-10-14 07:32:00 | 2026-10-14 09:13:34 | 1.69 | 0.00 | Measured | All 51 Settings controls/explanations, protected saves, bounded selectors, current custody warnings; 68 disposable-DB + 76 frontend + 27 traceability/env checks and live bilingual persistence/RTL/role/performance checks passed; all seven disposable DBs confirmed dropped; 3141 Arabic items preserved and 47 new drafts require review. Final completion bookkeeping follows the captured end boundary. |
| 4 | 2026-10-14 09:16:16 | 2026-10-14 11:24:00 | 2.13 | 0.00 | Start measured; end approximate | Implementation and regression tests; English checks. User requested immediate stop before losing connectivity; interruption boundary reconstructed from saved resume note. Preview stopped and disposable database dropped. |
| 4 | 2026-10-14 12:06:39 | 2026-10-14 12:13:42 | 0.12 | 0.71 | Measured; excluded interval approximate | Resumed after user authorization. Arabic saves/runtime limits/preference precedence/RTL/repeated navigation, 29 final tool checks, artifact preservation/template/policy checks, ledger and handoff. Offline interval 11:24–12:06:39 excluded. Final bookkeeping follows this captured end boundary. |
| 5 | 2026-10-14 12:15:58 | 2026-10-14 12:33:52 | 0.30 | 0.00 | Measured | Content first, then authentication; runtime upload/conversion/session/password/cleanup policy, extended reviewed migration/worker readiness; 132 broad + 28 boundary/auth + 25 final readiness, 84 UI and 44 tool checks passed. All nine disposable databases confirmed dropped. Fifteen business template entries removed; no private env/schema/translation changes. Final completion bookkeeping follows captured end boundary. |
| 6 | 2026-10-14 13:22:58 | 2026-10-14 13:51:03 | 0.47 | 0.00 | Measured | Search/indexing/Audit cap cutover,34-key migration,canonical/051,API-owned header,117-setting inventory and safe bootstrap.36 search+63 integration+14 Audit+223 UI+46 supporting checks and live bilingual freshness/grouping passed; all six disposable databases absent. Final bookkeeping follows captured end boundary. |
| 3 (control correction) | 2026-10-14 15:31:21 | 2026-10-14 15:47:07 | 0.26 | 0.00 | Measured | User-requested IANA dropdown, exact integer steppers/minimum one, scheme-first layout and dependent selector guidance. 17 Settings + 18 relationship/bounded tests and English/Arabic browser save/search/Browse/reload/responsive checks passed; both disposable previews confirmed dropped; catalogues unchanged. Details: docs/application-settings-controls.md. Final documentation bookkeeping follows captured end boundary. |
| 3 (native stepper/toast correction) | 2026-10-14 16:03:51 | 2026-10-14 16:13:36 | 0.16 | 0.00 | Measured | User-reported stepper overflow reproduced (64px buttons in a 40px field); replaced composed arrows with standard NiceGUI numeric Input and native stepping. Added translated positive save toast. 19 Settings tests and English/Arabic browser integer precision, toast, reload and narrow RTL checks passed. Both disposable previews confirmed absent; translation artifacts unchanged. Final documentation bookkeeping follows captured end boundary. |
| 3 (required-reason warning) | 2026-10-14 16:22:44 | 2026-10-14 16:27:12 | 0.07 | 0.00 | Measured | Added translated warning toast when Save has an empty/whitespace-only reason, retained inline error/draft and cleared an earlier success status. 23 Settings tests and live English/Arabic checks pass; no Settings PUT sent. Disposable preview confirmed dropped; catalogues unchanged. Final documentation bookkeeping follows captured end boundary. |
| 2 (readable reference audit) | 2026-10-14 16:35:10 | 2026-10-14 16:42:21 | 0.12 | 0.00 | Measured | User-approved scheme/classification code/title snapshots for old/new Settings values. Canonical schema and standalone migration 052; 31 disposable-DB regressions and 15 schema/cache checks passed. All three test databases confirmed dropped. Tested trigger migration applied to demo with settings/history preservation verified and private rollback definition saved; no restart required. Final documentation bookkeeping follows captured end boundary. |
| 3 (audit labels/navigation) | 2026-10-14 17:03:58 | 2026-10-14 17:22:28 | 0.31 | 0.00 | Measured | Shared readable labels for all three Settings operation codes, including historical events; authorized/guarded current-entity links open the API-selected Settings category with one read. 32 interaction + one export regression pass, live English/Arabic details and links verified, disposable preview confirmed dropped. Four contextual labels merged while preserving all prior Arabic entries; four demo labels published with all pre-existing translation rows preserved. Final documentation bookkeeping follows captured end boundary. |

| 7 | 2026-10-15 03:28:46 | 2026-10-15 04:01:10 | 0.54 | 0.00 | Measured | Common schema/053 and private command/claim/unit foundation; 75 cases passed on each fresh/upgrade path, 91 affected regressions and 39 tools checks passed; exact database catalogue parity and prior resource/identity/settings/grant/history preservation. All 34 disposable databases confirmed absent. No persistent DB/environment/translation change; action-specific entry points/final execution stay closed. Final evidence bookkeeping follows captured end boundary. |

| 8 | 2026-10-15 04:30:35 | 2026-10-15 05:04:59 | 0.57 | 0.00 | Measured | Database UTC eligibility/054, bounded worker, current protections and both-direction relationships with scoped redaction/coordination locks; 57 cases passed on fresh and upgrade paths, all 75 Phase 7 cases plus 53 affected regressions, 39 tools and three labels/export checks passed. Latest catalogue parity and existing data preserved; all 20 disposable databases independently confirmed absent. Two Arabic drafts added preserving all 3192 prior entries; no persistent DB/environment/service changes. Final completion bookkeeping follows captured end boundary. |

| 9 | 2026-10-15 05:39:43 | 2026-10-15 06:14:25 | 0.58 | 0.00 | Measured | Protected common job/membership/assignment/owning-unit/acceleration/termination commands and atomic policy/reopening/hierarchy recalculation; 201 full-suite plus three final CHECK cases passed on each fresh/upgrade path, 83 API regressions, 39 tools and five labels/export checks passed. Exact final catalogue parity and prior active membership/data preserved; all 26 disposable databases independently absent. Ten Arabic drafts merged preserving all 3194 prior items; no persistent DB/environment/service change. Final evidence bookkeeping follows captured end boundary. |

| 22 | Not captured | 2026-10-19 20:59:12 | — | — | Incomplete timing | Certificate-only recovery, digital/mixed and physical-only completion, final download/email behavior, notification and upgrade tests; English browser and MailDev checks passed. Live Arabic connection unavailable; DISP-35 policy unresolved. No measured active-hours claim. See docs/disposition-phase-22.md. |

### Phase totals

A dash means no implementation time has been recorded, not zero hours worked.
Update status from actual progress; specification approval is not implementation.

| Phase | Status | First started | Completed | Active hours at completion | Later rework hours | Excluded waiting hours |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Complete | 2026-10-14 04:24:21 UTC | 2026-10-14 05:41:29 UTC | 1.29 | — | 0.00 |
| 2 | Complete | 2026-10-14 05:52:04 UTC | 2026-10-14 07:21:03 UTC | 1.48 | 0.12 | 0.00 |
| 3 | Complete | 2026-10-14 07:32:00 UTC | 2026-10-14 09:13:34 UTC | 1.69 | 0.80 | 0.00 |
| 4 | Complete | 2026-10-14 09:16:16 UTC | 2026-10-14 12:13:42 UTC | 2.25 (interruption boundary approximate) | — | 0.71 |
| 5 | Complete | 2026-10-14 12:15:58 UTC | 2026-10-14 12:33:52 UTC | 0.30 | — | 0.00 |
| 6 | Complete | 2026-10-14 13:22:58 UTC | 2026-10-14 13:51:03 UTC | 0.47 | — | 0.00 |
| 7 | Complete | 2026-10-15 03:28:46 UTC | 2026-10-15 04:01:10 UTC | 0.54 | — | 0.00 |
| 8 | Complete | 2026-10-15 04:30:35 UTC | 2026-10-15 05:04:59 UTC | 0.57 | — | 0.00 |
| 9 | Complete | 2026-10-15 05:39:43 UTC | 2026-10-15 06:14:25 UTC | 0.58 | — | 0.00 |
| 10 | Complete | 2026-10-15 06:16:18 | 2026-10-15 08:06:07 | 1.83 | — | 0.0 |
| 11 | Complete | 2026-10-15 08:10:36 | 2026-10-15 09:31:56 | 0.99 | — | 0.3625 |
| 12 | Complete | 2026-10-15 09:55:03 | 2026-10-15 11:13:53 | 1.31 | — | — |
| 13 | Complete | 2026-10-19 05:06:47 | 2026-10-19 05:43:40 | 0.61 | — | — |
| 14 | Complete | 2026-10-19 05:44:21 | 2026-10-19 06:19:31 | 0.59 | — | — |
| 15 | Complete | — | 2026-10-19T07:21:16.948547+00:00 | — | — | — |
| 16 | Complete | — | 2026-10-19T09:34:41.191119+00:00 | — | — | — |
| 17 | Complete | — | 2026-10-19T10:29:02.932984+00:00 | — | — | — |
| 18 | Complete | — | 2026-10-19T15:06:17.058127+00:00 | — | — | — |
| 19 | Complete | — | — | — | — | — |
| 20 | Complete | — | — | — | — | — |
| 21 | Complete | — | — | — | — | — |
| 22 | Complete | 2026-10-19 (time unrecorded) | 2026-10-20 | — (incomplete timing) | — | — |
| 23 | Complete | 2026-10-20 (initial time unrecorded) | 2026-10-20 | — (incomplete timing) | — | — |
| 24 | Complete | 2026-10-20 (initial time unrecorded) | 2026-10-20 | — (incomplete timing) | — | — |


### Approved follow-up: restore reopened members within their job

**Approved:** 29 October 2026. **Requirements:** DISP-13, DISP-24, DISP-25,
DISP-38, DISP-40, DISP-42 and DEST-06; Disposition Sections 5.2, 6.1 and 11.

Compatible acceleration closes a reopened member, restores its whole unit to
the existing active job's pending status and clears the reopening flag without
removal/re-addition. Retain scope, authorization, reason, version, hold/closure
and irreversible-work guards; preserve identity, history and protection facts.
Approval validity follows the existing approved-facts comparison: exact
restoration, including a legitimate historical closure date, may preserve
approval. Changed approved facts use existing renewal/correction routing.
Preparation-stage proposals and stage remain intact without a new round. Migration 093, the canonical schema and
API/UI regression cases are traced in
`docs/disposition-in-job-acceleration.md` and its verification report.
