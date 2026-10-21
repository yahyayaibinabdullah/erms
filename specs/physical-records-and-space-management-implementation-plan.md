# Physical Records and Space Management — Phased Implementation Plan

**Status:** Approved implementation plan — implementation pending
**Approved:** 21 October 2026
**Prepared:** 21 October 2026  
**Project:** ERMS / Wathiq  
**Revision:** 1.0 — Specification and plan approved

## 1. Authority and approach

Implement the approved requirements in the
[Physical Records and Space Management specification](physical-records-and-space-management.md).
The user approved the complete specification and this plan on 21 October 2026.
The product specification, its recorded approvals, and subsequent explicit user
instructions remain authoritative. The documented implementation approach and
additional scan actions are included in that approval. Explicitly optional
fields/capabilities, including optional camera support, remain optional. Physical
box replacement, label reprint, and the additional approved scan actions are
included in their owning phases below. Approval does not claim that any phase
has been implemented or verified.

Use nine phases. Each phase has a bounded responsibility, stable inputs from
its predecessors, and one consolidated completion gate. The first phase builds
a working foundation rather than creating a separate planning-only phase.
Phases 2–8 deliver coherent capabilities through their database, API, and UI
surfaces. Phase 9 is the integrated release rehearsal and handoff, not a place
to postpone the implementation or routine testing of earlier requirements.

The default execution order is 1 through 9. JSON transfer technically depends
on Phases 2–3 and the finalized Site notification settings in Phase 7; keeping
it in Phase 8 avoids changing the interchange format as settings are added.
Nothing in this plan starts implementation, deploys unfinished workflows, or
requires a new recurring task, role, privilege, or approval process.

## 2. Architecture established once and extended

Phase 1 records the complete logical model and command boundaries before their
implementation is distributed among phases. This is technical design work under
the existing approvals, not another product decision questionnaire.

| Shared boundary | Established | Reused or extended |
| --- | --- | --- |
| Site/space structure, configuration, scope, publication policy | 1 | Administration 2; assignments 3–4; scans 5; loans 6–7; transfer 8 |
| Effective locations, physical-unit counting, box membership and capacity rules | Contracts 1; executable implementation 3 | Bulk operations 4; scans/inventory 5; loan fulfilment 7 |
| Governed assignment commands, lock ordering, history and retry identity | Interfaces 1; commands 3 | Whole-group execution 4; scanning adapter 5; custody transitions 7 |
| Full-address representations and bounded remote selectors | Representations 1; space browsing 2; location/box selection 3 | All later screens |
| Scan session framing, entity resolution, badge verification, staged items | 5 | Inventory/movement 5; request-related scanning 7 where required |
| Request header, item lines and permitted lifecycle transitions | Contracts 1; request implementation 6 | Dispatch, returns and reminders 7 |
| Existing notification producer/configuration machinery | Integration contract 1; request events 6 | Timed reminders, escalation and receipt/extension effects 7 |
| Versioned Site definition interchange | Export boundary designed 1; implementation 8 | Release migration/round-trip rehearsal 9 |

Avoid separate implementations of assignment validation in individual screens,
bulk handlers, scanner handlers, or loan handlers. They call the same controlled
commands and enforce the same database invariants. Likewise, a box's current
and assigned contents come from aggregation references, not competing lists.
Do not create a generic workflow engine or duplicate the existing authorization,
notifications, settings, translation, and event-history subsystems.

## 3. Phase execution and verification discipline

Each phase can span several development sessions. Within a phase, use a small
number of implementation checkpoints, normally domain/schema/API followed by
UI/integration. These checkpoints are not additional phases or reasons to repeat
a full verification gate. Record the next task and verified state when context
is exhausted, then resume from that record.

For every phase:

- Keep a requirement ledger mapping each source requirement, including prose
  additions, to its owning phase, implementation paths, meaningful tests, and
  actual results. Requirements spanning phases remain partially complete until
  all their evidence exists. All phases below start **not started**.
- Put SQL changes in the self-contained `database/schema.sql` and an independent
  upgrade migration in the same change. Allocate migration numbers from the
  actual repository state during execution. Seeds remain separate, use source
  `seeding`, and do not silently change existing grants or private configuration.
- Run database-backed tests only through a harness that creates a uniquely
  named disposable database, initializes the required schema/migration path,
  points the full process and fixtures to it, and drops it in all outcomes.
  The existing `tools/run_disposable_acl_tests.py` is a candidate to reuse after
  checking its suitability. Report creation/cleanup failures. Never use a
  persistent ERMS database for tests or browser verification.
- Add tests with each meaningful invariant or command. At the phase gate run
  the phase's relevant tests together, plus a focused regression slice of the
  shared components it changed. Run concurrency tests where the competing writes
  are first introduced. Do not rerun unrelated suites or earlier full gates
  unless changed code, a failure, or an unresolved risk justifies it.
- For schema-changing phases verify both latest empty-schema initialization and
  upgrade from the preceding phase baseline. The final release rehearsal checks
  the complete upgrade chain from the pre-feature baseline once.
- For UI phases compare new tables to an existing Wathiq table in a live browser;
  exercise real save/reload, English/LTR and Arabic/RTL, bounded pagination and
  selectors, failure states, navigation abandonment, and freshness after mutation.
  Reuse supported NiceGUI behavior before considering scoped CSS fallbacks.
- Read and follow the required internationalization sections before changing UI
  text. Merge missing keys without overwriting curated Arabic wording/provenance;
  keep all maintained artifacts in the English key order and run required
  coverage, placeholder, blank, terminology, stale-key, provenance, and hash checks.
- Site settings are operational data, not new environment variables. If a real
  service-runtime setting is introduced, reconcile only its consumer templates,
  regenerate the API template from its authority, run the template check, and
  document upgrade/restart action. Preserve private environment values.

Evidence should be compact: commands and outcomes, database creation/cleanup,
relevant browser results, unresolved failures, and a resume checkpoint. Avoid
large command transcripts or duplicating the source specification in each report.
A phase is complete only when its own deliverables and gate pass; passing tests
alone do not complete a still-unimplemented requirement.

## 4. Ordered implementation phases

### Phase 1 — Domain foundation, authorization and audit infrastructure

**Depends on:** Existing repository implementation.  
**Primary requirements:** SPM-01/02/03/11/12; contracts supporting SPM-04–18.

**Build:**

- Inspect existing location functions/routes/representations, security gates,
  event history, deletion/disposition integrations, notification producers,
  settings, selectors, and test harnesses. Record actual reuse points, not
  assumptions from older drafts. Reconcile the new source with the earlier
  location/medium document without modifying unrelated product behavior.
- Record one compact technical contract for identifiers, Site/space hierarchy,
  ordered physical adjacency, settings, Draft/Published and deactivation rules,
  box identity/membership, explicit/inherited location states, custody linkage,
  request transitions, reference matching, and transactional command inputs.
  Account for the whole feature so later phases add behavior without replacing
  foundational tables or APIs. Do not implement all future workflows here.
- Add the Site/space/settings and role-to-Site scope foundation, ordered-type
  constraints, versions, publication/deactivation fields, and paginated query
  representations. Initialize new Sites as Draft; enforce the foundation's
  applicable structural and authorization rules from its first write path.
- Add the approved privilege/permission catalogue and `SPACE_MANAGER` Profile.
  Implement creation/import bootstrap and Site permission administration under
  `spaces.administer`, including prevention of administrative lockout. Preserve
  `roles.is_information_governance` and existing clearance/access rules.
- Extend shared audit identity snapshots/event display support and command
  correlation/idempotency infrastructure. Every foundation mutation is audited
  immediately; do not postpone auditing until Phase 9. Establish the stable
  history/locking interfaces subsequent command implementations will reuse.

**Boundary:** No box placement, new aggregation location cutover, scanner session,
or loan workflow yet. Existing location behavior remains supported.

**Gate:** New schema and upgrade initialize correctly; structural/direct-write
checks work; global/Site/resource gates remain distinct; Site creator access,
delegation and last-administrator checks pass; history failure rolls back writes;
existing authorization/location regression slice passes.

### Phase 2 — Site administration, hierarchy wizard and publication

**Depends on:** 1.  
**Primary requirements:** SPM-02/03/11/12/14/15/17; relevant SPM-13 UI rules.

**Build:**

- Deliver Site creation/editing with code, name, address, telephone, bounded
  contact-user selection, settings, scope administration, and paginated hierarchy
  browsing. Implement space create/update/delete and readable full addresses.
- Implement the empty-Site-only wizard: selected ordered levels, counts per
  actual included parent, generated codes/names, bounded preview, confirmation,
  creation and audit. Serialize competing wizard/manual creation; retries do
  not build twice. Empty/unassigned/unreserved pruning preserves history.
- Implement explicit Site publication with required validation and actor/time.
  Draft Sites and their descendants remain unavailable to operational users.
  Implement ancestor deactivation propagation and clearly separate it from
  publication; do not encode a blanket return ban in shared eligibility checks.
- Implement administrator control of physical storage order and the structural
  change preview/validation required by the approved hierarchy rules. Placement
  dependency checks use the common interfaces that Phase 3 fills with actual
  holdings; they do not rely on downloading a complete hierarchy.

**Boundary:** Deliver a complete setup workflow, not empty menu entries for later
operations. Existing holdings are not yet mapped into the new structure.

**Gate:** Wizard arithmetic and skipped levels are correct; existing, inactive,
or concurrently created descendants prevent wizard reuse; invalid publication
stays Draft; publication and administration are audited; parent/child ordering
and eligible deletion work; bounded browser UI, permission editing, real reload,
LTR/RTL and required translation/performance checks pass.

### Phase 3 — Boxes, governed locations and individual assignment

**Depends on:** 1–2.  
**Primary requirements:** SPM-01/03/04/06/11/12; location migration in SPM-13.

**Build:**

- Implement box registration, instance-wide `BX` numbering, immutable scan
  identities, current/assigned box references, current/assigned spaces, and box
  lifecycle data. No new box-specific privileges or separate physical-item flag.
- Implement the complete individual assignment/packing/unpacking/reassignment
  commands and shared validations. Derive separate tracking from medium and
  explicit locations; preserve independent inheritance, Missing reasons,
  outside/unknown representations, record effective locations, and full paths.
  Include custody-compatible data contracts now; loan transitions are Phase 7.
- Implement one capacity/reservation model for slots, boxes, loose storage and
  combined storage. Honor optional boxes, retained homes, source/destination
  scope, security, publication, and deactivation's existing-home return exception.
  Box and aggregation reference consistency is authoritative in the database.
- Extend aggregation forms/details, space holdings and box detail views with
  bounded remote location/box selectors and current/assigned/full/available
  distinctions. Integrate existing lifecycle mutations with new references and
  dependency checks under their governing specifications.
- Implement legacy-code inventory/mapping and the upgrade path into reference
  locations. Preserve source values/provenance and explicit versus inherited
  meaning; surface unmapped values without guessing or silently clearing them.
  Maintain a single documented source of truth at cutover. Update API/schema,
  effective views, search, history and existing governed commands together so
  later phases do not replace the location model again. Migration dry runs use
  disposable databases; actual operator data reconciliation is not a test run.

**Boundary:** Complete manual individual placement and reusable commands. Physical
box replacement involving multiple members and whole-group actions are Phase 4.
Do not expose an ordinary metadata setter that bypasses governed commands.

**Gate:** Fresh/upgrade location parity and legacy mapping preservation; inherited
versus explicit counts; optional boxes; current versus assigned memberships;
Missing and deactivation rules; security/capacity contention; canonical SQL and
API bypass attempts; selector retention/full paths; aggregate/global history;
existing closure/security/location regressions and targeted live UI checks.

### Phase 4 — Whole-group assignment, relocation and contiguous recommendations

**Depends on:** 2–3.  
**Primary requirements:** SPM-03/05/12/18; box replacement part of SPM-06.

**Build:**

- Extend the Phase 3 command service to accept selected groups with reviewed
  terminal-space mappings and current/home/permanent modes. Preserve the same
  individual invariants rather than implementing a second validation engine.
- Implement whole-group locking/serialization, versions, capacity and reservation
  checks, idempotency and correlated history. One confirmation commits every
  affected assignment/membership/reservation/event or none. Reject oversized
  selections before mutation; no separately committed internal batches.
- Implement contiguous-empty-space recommendations using configured storage
  order and real demand. Exclude assigned/reserved/ineligible gaps; honor box
  grouping, no-slot capacities, permissions and publication. Previewing does not
  reserve space. Confirmation cannot silently choose another mapping.
- Deliver the bulk selection/mapping/confirmation UI and completion/conflict
  results. Include cross-site moves and inherited effects without overwriting
  absent items' actual state.
- Implement physical box replacement through the same group transaction:
  transfer actual and assigned members appropriately, preserve loan-compatible
  references, replace a box in its slot without double occupancy, retire the old
  identity, and preserve linked history. Label printing comes in Phase 5.

**Gate:** Two independent connections competing for the same last capacity cannot
both succeed; stale/current versus home/settings/scope conflicts roll back the
whole group and its successful-change history; mixed box/content selection is
deduplicated; no-contiguous-fit and unknown-capacity results are honest; retries
return one result; replacement and cross-site invariants pass; UI previews and
post-mutation freshness are verified in both directions.

### Phase 5 — Labels, scanner workbench, inventory and scanned movement

**Depends on:** 2–4.  
**Primary requirements:** SPM-06/07/08; shared scan interaction in section 7.4.

**Build:**

- Implement QR/Code 128 label generation/printing, entity resolution, stable
  identifier lifecycle and reprinting. Use the existing user identity surface to
  support the specified worker-badge resolution; do not introduce badge-based
  login or a new grant model. Physical replacement keeps Phase 4's new-box rule.
- Build one reusable scan workbench: explicit operation/step, focused HID/manual
  input, complete-scan framing, Enter suffix handling, staged items, duplicates,
  box-content deduplication, feedback, own-badge match, review and confirmation.
  It must not interpret a scan suffix or a badge scan as final confirmation.
- Add scanned movement as an adapter over Phase 4's commands, including explicit
  multi-destination mapping, whole-group atomicity and safe retries. Scanning
  contributes identifiers; it cannot bypass destination or access checks.
- Implement inventory sessions, direct/subtree manifests, observed scans,
  incomplete/limited inventories, concurrent-change handling, discrepancy review
  and recorded completion. Corrections call the governed location/Missing
  commands; a box scan never certifies unseen contents.
- Connect box replacement and label reprint to the workbench where required.
  Keep request-related scan actions for Phase 7; the shared session/step contract
  already supports them without a new scanner implementation. Camera input is
  optional as specified and is not a mandatory release gate.

**Gate:** Real keyboard-wedge or equivalent HID/manual input path works; Enter
only completes one scan; correct/wrong/retired/duplicate codes and badge mismatch
are handled; inventory has no implicit location mutation; scanned movement
reuses the same race/rollback behavior; session recovery, authorization, history,
LTR/RTL focus and live UI results pass. Record physical scanner testing honestly;
simulated HID input does not by itself prove a particular device was tested.

### Phase 6 — Request submission, conflict review and approval

**Depends on:** 1–4; 5 supplies item identification for later fulfilment.  
**Primary requirements:** Submission/review/approval part of SPM-09; SPM-11/12;
request-event integration part of SPM-10.

**Build:**

- Implement request headers/item lines and the complete lifecycle representation
and guarded transition contract needed by Phase 7. Expose submission, review,
conflict resolution, referral, approval/rejection and pre-dispatch cancellation
now; do not expose unimplemented dispatch/return transitions.
- Deliver requester and staff work queues, view-filtered bounded item selection,
requested windows/duration/Taken to and recipient information, reasons, explicit
item-level decisions, human conflict reconciliation, concurrent allocation
protection, and required reapproval after approved changes.
- Enforce physical/mixed scope, parent versus accompanying unit conflicts,
request/view/access gates, Site scope, and the approved role-based governance
self-approval exception. Reuse shared authorization; preserve the role flag.
- Integrate notification producers and recipient resolution for the request
operations implemented here through existing notification configuration and
transaction machinery. Store responsible participation/handling information
needed later, rather than bolting notification ownership onto Phase 7.
- Record lifecycle/decision history. Prepare approved dispatch inputs without
claiming physical dispatch or starting the four-day clock prematurely.

**Gate:** Requesters cannot discover/request inaccessible items; concurrent
conflicting approvals cannot both allocate the item; referral blocks dispatch;
self-approval gates and reapproval work; partial item decisions are explicit;
request events are durable and deduplicated; request UI, permissions, LTR/RTL and
real save/reload pass. Lifecycle representation tests cover forbidden transitions;
actual dispatch/return behavior remains incomplete until Phase 7.

### Phase 7 — Dispatch, custody, return, deadlines and reminders

**Depends on:** 3–6.  
**Primary requirements:** Remaining SPM-09/10; custody/location, deactivation,
reservation, box and scan integration in SPM-03/04/06/08/11/12.

**Build:**

- Implement pick/dispatch/handover, in-transit/on-loan and return transitions,
actual custody, Taken to, physical receipt and confirmed reshelving through the
existing location/group commands. Expose manual and required scanner actions;
the approved pick-list, delivery/return and reshelving verification actions
use that same workbench.
- Handle explicit item subsets, failed delivery, partial returns, extension,
recall and reapproval without losing outstanding obligations. Preserve home
claims and assigned box membership while an individually loaned item is away.
Existing homes in deactivated branches remain valid return destinations.
- Establish default deadlines four days after actual dispatch per line, honor
explicit approved deadlines, and snapshot applicable settings so later Site
changes do not rewrite established obligations. Do not implement a second
request lifecycle or a separate scanner session system.
- Add durable scheduling and retry-safe notification producers for reminders,
due/overdue and seven-day escalation. Extensions replace obsolete schedules;
physical receipt stops borrower reminders while reshelving remains outstanding.
Notification content/recipients obey live access and deduplication requirements.
- Finish the previously identified custody-dependent guards for existing
aggregation, box, role/user and disposition operations under their approved
contracts. Verify lost-access handling and protected evidence; do not invent a
new override, automatic loss closure or irreversible disposition rule.

**Gate:** One complete loan and return works through manual and scanner inputs;
partial dispatch uses its actual dates; overdue/extension/recall/failed delivery
and partial return preserve correct state; box and space current/home references
stay consistent; deactivated-home return succeeds while new assignments fail;
restart/retry/timezone/access-change notification tests pass; notification/audit
failures meet transactional requirements; real staff/requester UI paths pass.

### Phase 8 — Site JSON export/import

**Depends on:** 1–3 and 7; use Phase 4 transaction infrastructure where applicable.  
**Primary requirements:** SPM-16; settings, publication, authorization and audit
parts of SPM-02/03/11/12/15/17.

**Build:**

- Implement the versioned Site-definition JSON schema and round-trip codec using
the now-complete settings catalogue. Include structure/storage order and exclude
boxes, aggregations, placements, reservations, accounts, grants and source history.
- Add independent include/blank choices for security references and Contact User,
with no hidden identifying metadata when blanked and no source mutation.
Resolve included references against destination data; assign unambiguous matches
or offer replacement/cancel. Resolve deliberate blanks before completion under
the required-field rules. Do not create accounts/security levels or reuse IDs.
- Deliver complete preview, conflict/reference mapping, whole-Site validation,
atomic creation and retry-safe import. Reuse normal Site creation/bootstrap,
structure/settings validation and per-space history, not a bypassing import path.
Implement the approved transfer approach without adding synchronization or
merge functionality.
- Start every imported Site/sub-space as Draft regardless of source publication,
with independent deactivation flags. Keep printed identifiers separate from new
destination scan identities and require destination publication before use.

**Gate:** Export/import into a separate disposable destination preserves the
specified definition and no holdings/grants; all four include/blank combinations
work; missing/ambiguous references allow replacement/cancel; invalid/cancelled
imports leave nothing; code conflicts and retry behavior are correct; imported
Draft status blocks operational use; round-trip/upgrade and real UI checks pass.

### Phase 9 — Integrated release rehearsal and operator handoff

**Depends on:** 1–8, each with its own completed evidence.  
**Primary requirements:** SPM-13 and final cross-phase acceptance for SPM-01–18.

**Complete:**

- Run the complete feature upgrade chain from the recorded pre-feature schema
and the latest canonical-schema path in separate disposable databases. Rehearse
reviewed legacy location mapping, unresolved-value reporting and cutover checks;
prove equivalent final invariants without discarding originals or guessing codes.
- Run one integrated journey: build/publish a Site; create boxes/loose holdings;
recommend and atomically assign contiguous space; scan movement and inventory;
loan/extend/return an item; move/replace its box; deactivate and return to an
existing home; export/import the definition into another disposable instance
and publish it there. Verify resulting capacity, reservations, identity and
resource/global history together. Cover a losing concurrent assignment as part
of that journey rather than repeating every earlier contention test.
- Run the focused combined feature regression and selected shared-subsystem
regressions justified by the changes. Measure realistic pagination/hierarchy,
bulk preview, inherited effects and scanner responsiveness. Check no optional
scan/camera assets or duplicate requests burden authenticated startup.
- Reconcile the requirement ledger: no source requirement is missing, no
optional capability is misreported as mandatory, and no unresolved failure
is hidden.
Complete final translation/artifact and applicable environment-template checks;
document actual device coverage and remaining maintained-language review.
- Write deployment/upgrade and recovery guidance, manual legacy-mapping actions,
Profile/Site setup, operational settings, draft publication, scanner setup and
verification evidence. Recovery must preserve committed movement/history;
reverting application code is not permission to undo physical facts or erase
migration/audit data. Deployment and persistent data changes remain separate
from the disposable test rehearsal and require their applicable authorization.

**Gate:** All required capabilities have implementation and executed evidence;
upgrade/fresh paths and integrated journeys pass; failures are resolved or
explicitly prevent completion; operational documentation and handoff are usable.
No phase is marked complete merely because a context window or budget is ending.

## 5. Requirement ownership summary

The primary owner is responsible for completeness. Other listed phases own the
specific extensions above; they do not repeat a prior phase's full gate.

| Requirement | Primary phase(s) | Required later integration |
| --- | --- | --- |
| SPM-01 Scope and physical units | 1, 3 | 5–7 respect actual physical units and no independent record loans |
| SPM-02 Hierarchies and codes | 1–2 | 4 storage order; 8 portable definitions |
| SPM-03 Security, capacity, boxes and deactivation | 2–3 | 4 concurrency/replacement; 7 existing-home return |
| SPM-04 Locations, inheritance and Missing | 3 | 4 groups; 5 scanning; 7 custody/returns |
| SPM-05 Bulk assignments/moves | 4 | 5 scanner adapter; 7 fulfilment reuse |
| SPM-06 Labels, box identities and scanning | Box identity 3–4; label/workbench 5 | 7 request interactions |
| SPM-07 Inventory | 5 | 9 integrated reconciliation evidence |
| SPM-08 Scanned movement | 5 | 7 separation from loan/return actions |
| SPM-09 Requests and loans | 6–7 | 9 integrated acceptance |
| SPM-10 Notifications and deadlines | 6–7 | 8 settings portability; 9 restart/release integration |
| SPM-11 Authorization | 1–2 | Each command-owning phase enforces its specific gates |
| SPM-12 History and integrity | 1 | Every phase audits its introduced mutations; 9 correlated journey |
| SPM-13 Migration, UI/performance and delivery | 3, 9 | Every UI phase handles its own language/performance obligations |
| SPM-14 Site wizard | 2 | 8 imported sub-spaces prevent wizard reuse |
| SPM-15 Site contact/details | 2 | 8 contact transfer/mapping |
| SPM-16 JSON transfer | 8 | 9 separate-instance round trip |
| SPM-17 Publication | 1–2 | Every operation checks it; 8 imported Draft behavior |
| SPM-18 Contiguous recommendations | 4 | 5 manual/scanned mutation paths share concurrency rules |

## 6. Context and handoff record

At a session boundary record only: current phase/checkpoint, changed paths,
contract or migration decisions needed to resume, completed verification and
its disposable database cleanup result, remaining defects, and the next concrete
action. Keep the durable requirement ledger as the evidence source rather than
reconstructing status from chat history. Resume from the checkpoint; do not
restart baseline analysis or rerun previously passed gates without a reason.

The intended milestone boundaries are usable Site setup after Phase 2, correct
manual storage management after Phase 4, scanner/inventory workflows after
Phase 5, complete circulation after Phase 7, and portable Site definitions after
Phase 8. These are implementation milestones, not claims of production release
or permission to deploy an incomplete feature.
