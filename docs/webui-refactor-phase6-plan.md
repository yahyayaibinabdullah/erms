# WebUI refactor: approved Phase 6 sequence

**Status:** All approved sub-phases **6A–6U are complete for the local scope**.
The [overall verification report](webui-refactor-phase6-verification.md) links
all 21 individual reports and their acceptance results. The latest authorization
through 6N–6U has been fulfilled. Work remains local and uncommitted.
**Stop before Phases 7 and 8 until the user instructs continuation.**

## Purpose and evidence

Finish separating the remaining features from `frontend/webui/app.py`, preserving
all existing functionality and UX. Each feature owns its screens, dialogs,
interactions, state and tests. Reuse existing feature modules instead of replacing
them. A feature may use several small files; it does not need one large file.

This order is based on the [Phase 1 feature/dependency map and risks](webui-refactor-phase1-baseline.md),
the [captured closure inventory](verification/webui-refactor-phase1/source-inventory.md),
the [pilot review](webui-refactor-phase4-review.md), and the
[Phase 5 results](webui-refactor-phase5-verification.md). The remaining functions,
captured dependencies, entity definitions and restoration dispatch in the current
working copy were also inspected. This is a static planning review, not a new test
run or a claim that all feature workflows already have sufficient coverage.

The main findings are:

- Relationship administration already has a separate renderer and a small host
  wrapper, making it a suitable first move.
- Audit history is called by many editors and detail screens. Give it an owner early.
- `open_editor`, `render_table`, `load_rows` and `select_entity` mix shared mechanics
  with feature-specific behavior. They cannot simply move into one replacement
  application module or receive the whole shared state dictionary.
- Classification depends on editing and history. Organization roles depend on
  profiles and security levels. Records depend on aggregation selection and digital
  components. These dependencies determine the middle of the sequence.
- Records and aggregations call each other. Messaging calls records, organization,
  audit and disposition; disposition uses resource selection and preview. Explicit
  callbacks are needed to preserve these cycles without circular imports.
- Search and dashboard share personal-resource displays and identity-scoped state.
  Their extraction must include those state owners, not just their entry functions.
- Live messaging owns a separate API client and connection lifecycle. Its host
  integration moves last, after its destination features are established.

## Approved order

Module names below describe proposed ownership; existing modules remain in use.
All paths are under `frontend/webui`. Risk describes regression exposure, not an
estimate of implementation time. Each row is a separate acceptance step.

| Step | Feature and proposed module boundary | Why here / principal checks |
| --- | --- | --- |
| 6A | **Relationship-type administration:** a controller beside `resource_relationships.py`; move `select_relationship_types` and its navigation/state integration. Resource relationship panels stay in their existing module and are verified with their record/aggregation callers later. | Smaller boundary with an existing renderer. Check administration writes, restrictions, languages and late responses. Moderate risk. |
| 6B | **Audit and entity history:** `audit_workspace.py`; move audit filters, event presentation/detail, entity-history dialogs and existing destination links. Retain `audit_actor_select.py` and label helpers. | Supplies history to later features. Check historical identities, filter/paging/export behavior and Settings/resource links with correct return state. Moderate risk. |
| 6C | **Shared entity controls:** small collection, editor, selector and resource-presentation modules; separate reusable parts of `open_editor`, `render_table`, `load_rows`, decoration, number conflicts and compact/personal sections. Give favourites/recent-data handling an explicit per-session owner. | Prerequisite for several features. Move one shared responsibility at a time and exercise every current consumer. Feature rules move with their feature below; do not create a generic replacement monolith. High risk. |
| 6D | **Classification:** a controller alongside `classification_workspace.py` and `classification_transfer.py`; move scheme/classification entry, editing rules, state and history integration. | Shared editor/history boundaries now exist. Check hierarchy paging, inherited retention, translations, import/export, selection and downstream links. High risk. |
| 6E | **Security configuration and access controls:** security administration and access-dialog modules; own security levels, profiles/privilege editing, ACL/defaults, access explanations and security-level changes. Reuse existing authorization helpers. | Supplies organization and resource workflows. Check allowed/denied actions, inherited/default ACLs, privilege dependencies and bounded principal selection. High risk. |
| 6F | **Login-session administration:** `login_sessions.py`; move the session list, filters and existing administrative actions. | User administration can call a stable session feature. Check current-session effects, restricted access, expiry and sign-out cleanup. Moderate risk. |
| 6G | **Organization workspace:** organization controller with separate unit, role, user and membership files; move tree/browser, lists, details, editors, memberships and deletion flows together as a connected workspace. | Uses profiles, security levels, history and session administration. Check branch paging, inherited status, ownership, membership changes, deletion restrictions and recipient browsing. High risk. |
| 6H | **Text-indexer administration:** `text_indexers.py`; move list/detail, key handling and existing operational controls. | Organization/user links are established. Preserve key visibility, permissions and record/component links; never expose secrets in evidence. Moderate risk. |
| 6I | **Account, sign-in and preferences:** account-view and preference modules; move remaining login/password UI, user-menu actions, language/timezone preferences and their localization coordination. | Session lifecycle already belongs to Phase 5. Preserve existing authentication/bootstrap order through explicit callbacks; check temporary-password recovery, language reload, direction and isolated session state. High risk. |
| 6J | **Translation administration and inspector:** translation administration/inspector modules; move the administration screen, inspect-and-open flow and optional asset lifecycle. | Builds on established locale/account interfaces. Check permissions, filtering, edit/import/export/publish behavior, inspector cleanup and wording/provenance preservation. High risk. |
| 6K | **Legal holds:** `holds.py` or a small holds package; move list/detail, editor, reasons, resource attach/remove and effective-hold dialogs, including navigation visibility refresh. | Supplies record/aggregation actions; organization and history are established. Check lifecycle, propagation, effective inheritance, notifications and resource returns. High risk. |
| 6L | **Digital components and preview:** component/preview modules; move `show_components`, `preview_record_components` and associated preview state. | Supplies record capture, indexer links, disposition review and message capture. Check staging, files, preview navigation, failures and cleanup. High risk. |
| 6M | **Aggregations:** aggregation controller/browser/detail/editor modules; move browse/search modes, hierarchy state and aggregation actions, including reopen, governed movement and ownership correction. | Classification, access controls, holds and shared resource displays are established. Check branch paging, restoration, location/vital/review rules, child creation and record links. High risk. |
| 6N | **Records and capture:** record list/detail/editor/capture modules; move record-specific editing, draft capture, resource movement rules and component/relationship integration. | Aggregation selection and component handling now have owners. Check physical/digital rules, capture/upload, validation, save failures, parent returns and post-write freshness. High risk. |
| 6O | **Security operations:** `security_operations.py`; move oversight/break-glass workspace and its actions/links. | Organization and resource destinations are established. Check permitted/denied operations, resource links, state restoration and audit effects. High risk. |
| 6P | **Governance custody:** `governance_custody.py`; move custody configuration/status, actions and existing Settings/organization links. | Uses organization, security and the established Settings controller. Check each existing state/action and return path; retain request/cancellation diagnostics for the Phase 5 loading observation. High risk. |
| 6Q | **Global/full-text search:** `global_search.py`; move query/results, diagnostics, paging, expansions, return anchors and session cleanup. | Resource destinations and shared result displays are established. Preserve existing search URLs, result restoration, request bounds and late-response handling. High risk. |
| 6R | **Advanced and saved search:** advanced-search and saved-search-administration modules; move query builder, saved-query state, sharing/audience controls and administration together. | Uses classification, organization and resource interfaces. Check effective-retention queries, sharing restrictions, paging, restoration and existing unsaved-change guards. High risk. |
| 6S | **Dashboard:** `dashboard.py`; move summary, favourites/recent presentation, review reminders, refresh and dashboard cache ownership. | Its linked destinations and shared personal-resource data have owners. Check warm navigation, mutation freshness, identity/language isolation and abandoned refresh without destructive loading. High risk. |
| 6T | **Disposition:** a controller in the existing `disposition/` package; move host integration, saved views, acting-role/resource selection, task/job navigation and guards. Keep existing eligibility, review, completion, template, artifact and recovery modules. | Resource selection/preview and access controls are established. Check connected proposal/job/task lifecycles, approvals, external/physical completion, artifacts and failure/recovery paths. High risk. |
| 6U | **Messaging and notifications:** a messaging controller beside existing workspace, monitor, notification and live modules; move mailbox state, capture/open callbacks, unread/toast controls and stream ownership. | Uses organization recipients, record capture, audit and disposition. Check compose/drafts/send/delete/restore, attachments, notification administration, monitor links, reconnect, identity changes and stream teardown. High risk. |

## Rules for the shared and cyclic dependencies

6C is a supporting extraction, not a new product feature or a second shell rewrite.
Before each small move, map every reader/writer of the affected state and add any
missing baseline checks. Move only reusable behavior whose inputs and callbacks
can be stated clearly. Record which remaining feature owns each temporary adapter.
Entity-specific form fields, validation, actions and refresh rules move in that
feature's row; common controls do not acquire authority over feature workflows.

Until both sides of a dependency have moved, the application assembly supplies an
explicit callback to the existing implementation. Examples include aggregation
→ record, organization → text indexer, audit → resource and account → dashboard.
When the destination moves, update and test that connection in the same step.
Never import `app.py` from a feature, pass its entire state dictionary, copy
business logic, or change the order of cancellation, restoration or cleanup.

Account bootstrap still invokes feature initialization/cleanup through callbacks.
Localization belongs to the existing locale services and the account/preferences
coordination; inspector behavior belongs to 6J. Live-message connection ownership
moves in 6U while session lifecycle remains in `SessionContext`. The root page
retains startup, static configuration, styles and assembly; final removal of
obsolete adapters remains Phase 8. No feature implementation is intentionally
deferred to that cleanup phase.

## Acceptance required for every row

1. Map existing requirements, entry points, state and dependencies to the proposed
   owner. Fill missing coverage and demonstrate the current behavior before moving it.
2. Extract in small changes. Preserve source-location test assertions when replacing
   them with direct module or behavior tests. Retain useful existing tests.
3. Run full WebUI unit and interaction suites at each row's acceptance gate, plus
   affected assembled/real-API and Chrome/Edge journeys. During development, use
   focused checks; run acceptance against the finished, unchanged source.
4. Compare English/Arabic appearance, keyboard/focus, navigation and saved state.
   Cover permissions, validation, loading/empty/error states, cancellation, accepted
   writes, data freshness and identity/language isolation. Check request bounds and
   responsiveness against the baseline. Verify migrated and remaining screens together.
5. Record requirement → module → passing evidence, including every caller and
   shared-control consumer affected by the step. Validate translation artifacts.
   Do not begin the next row while an unexplained regression remains.

Use a fresh disposable PostgreSQL database for every database-backed run and
report cleanup. Chrome and Edge remain the local scope; Firefox, Safari and CI
remain deferred. Synthetic email uses the established local MailDev arrangement.
No persistent application database is a test target.

The Phase 1 disposition-preview failure B2 was reproduced and its fixture repaired
in 6T to meet existing reviewer rules. Lifecycle coverage passes without weakening
application validation; the original failure remains recorded in its report.

The non-reproduced Phase 5 Edge timeout remains an accepted observation with an
unknown cause. Its acceptance is not permission to ignore future failures; retain
the diagnostic logging and investigate any recurrence.

## Approval boundary

The user initially required approval before each sub-phase. On 11 November 2026
the user authorized all remaining Phase 6 sub-phases and requested an individual
verification report for each, followed by an overall summary. The user's latest
instruction authorizes resuming at **6N and continuing through 6U**. This
supersedes the intervening stop after 6M. Every acceptance gate and product/Git
boundary still applies. The planning
review itself started no implementation or test sessions. Application Settings is
already extracted and is regression-tested as a caller/destination, not migrated again.
All inventoried feature families are assigned above, including dialogs and
background work that have no standalone navigation destination. `privileges` and
`permissions` registry entries do not authorize new standalone screens.

No functionality, UI, UX, wording, translation, API, public URL or browser-history
change is authorized. Any discovered product defect requires separate approval.
Keep work local and uncommitted on the user's existing branch. Phases 7 and 8
remain application-wide verification and cleanup/final acceptance respectively.

## Reminder at completion of the whole WebUI refactor

At the user's request, the final WebUI refactoring handoff (after Phases 7 and 8,
not merely Phase 6) must remind them about the two pre-existing defects recorded
in the [6M report](webui-refactor-phase6m-verification.md): governed movement fails
because `compatible_aggregations` is undefined, and an empty contained-record
filter removes its own filter control until reload. These remain outside the
refactor's product-change authorization.

Phase 7 must revisit the non-reproduced aggregation refresh cancellation recorded
in the [6O report](webui-refactor-phase6o-verification.md). Test-only cancellation
diagnostics are retained; no product fix or relaxed acceptance check was made.

The pre-existing bare-condition saved-query rendering observation in the
[6R report](webui-refactor-phase6r-verification.md) is also retained for Phase 7
review. Original and extracted behavior match; no product fix is authorized.

Phase 6S is complete: [dashboard verification](webui-refactor-phase6s-verification.md).
The original/extracted dashboard favourite-removal notification failure is
recorded there for Phase 7 review; the successful removal and existing error are
preserved. No product fix is included.

At the end of the complete WebUI refactoring, the user also requires a prioritized
list of every recorded pre-existing defect and abnormality. Consolidate findings
from all phase reports, distinguish reproducible defects from unexplained or
non-reproduced observations, link evidence, and recommend the next action for
each. Include the two aggregation defects already requested as a reminder.
This reporting requirement does not authorize product fixes during refactoring.

Phase 6T is complete: [disposition verification](webui-refactor-phase6t-verification.md).
The preview fixture B2 is repaired. Phase 6U reproduced the footer retry observation
as a test helper race and corrected its fixed wait, with delayed-response evidence.
No product change was made. [Phase 6U verification](webui-refactor-phase6u-verification.md)
is complete. The subsequently authorized Phase 7 also passed its approved local
functional and performance gates; see its
[verification report](webui-refactor-phase7-verification.md).
Phase 8 still requires authorization.
