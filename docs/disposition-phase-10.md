# Disposition Phase 10 implementation and verification

Phase 10 adds the eligibility list and common job workspace. Phase 9's protected
commands remain the only mutation path. Evidence destinations, review workflows,
final execution and irreversible recovery remain with their later phases.

## Requirement traceability

| Approved scope | Implementation and evidence |
| --- | --- |
| Disposition §8; DISP-07/27/28 | `disposition/queries.py` and explicit read routes return server pages of roots in statuses 2–5. Default ordering is database-calculated due instant, then aggregation ID. Owner, due bounds, status/action, vital, security and hold filters and ascending/descending sorts execute on the server. Owner grouping uses only the requested server page. `test_disposition_queries.py` verifies ordering, every filter category, paging, grouping and protected projections. |
| §8 row content | Number/title, stored status and action, calculated due instant, database-derived days overdue, owner, effective rule source, protection indicators/counts, admission explanation and active membership are displayed. Open accelerated roots show that closure is required; unknown due dates are explicit. Hidden roots have page-local redacted envelopes, no resource identifiers/version/metadata and no usable selection. |
| §§8/9.1/9.3; DISP-25/28 | Bounded blocker pages include a separate copy of every hidden blocking resource. Hidden copies expose only generic blocker categories; no identity, title, security details or hold identity/name. Visible hold metadata still undergoes its own authorization. Job members show current protection/final-relationship blockers and explicit removal-required notices. API and browser checks cover redaction and unchanged membership/status. |
| §§3.3/3.4/4; DISP-01/02/37 | New navigation uses the existing privilege plus effective IG-role intersection, computed with the existing authentication policy. Read services independently enforce current person/IG/manage authorization. Existing role/profile rules govern create-type and assignee choices. Relationship selectors require two characters, return at most 25 options, retain selected values and hydrate a selected ID narrowly. |
| Common jobs; DISP-25/37/38; Destruction §4 | Create all four job types, including empty unassigned jobs; assign/reassign, choose owner, add selected roots and remove current members with versions, acting role and mandatory post-creation reason. Creation itself needs no reason; numbers are allocated by the system under disposition §10.1.0. Destruction membership controls obey server preparation/correction restrictions; owner changes are offered only for eligible empty, never-submitted jobs. Each addition has its own persistent result. Partial or wholly rejected additions never receive a total-success toast. Membership episodes and authorized event history use independent bounded pages. Live create/assign/add/remove tests verify persistence and automatic refresh. |
| §§6/6.1; DISP-17/42 | Metadata, inspectors and shared search/browse results display each resource's own stored status. Browse projections explicitly carry status and active job ID; search permits stored-status filtering. Reopened members show status 1 and a mandatory-removal notice. The open-root acceleration dialog displays the effective target status and whole-unit scope, takes a reason and calls the existing protected command. |
| Internationalization/performance/design references | Native NiceGUI controls and the existing Wathiq `PageTable`, true server pagination, guarded async responses, native cell wrapping, working-timezone filters, explicit DST overlap choice, shared event labels and contextual catalogues. Automated and live checks below exercise these contracts. |

The requirement ledger records scoped Phase 10 evidence for all 37 owners. Only
DISP-S8 has Phase 10 as its sole owner. Multi-phase source sections retain their
later action/review/execution obligations; this phase does not complete them by
implication.

## Current facts, audit and authorization

The job member reader calculates current protection and outside-job relationship
facts. It records first-detected pending blockers, including time-activated
holds, and subsequent changed/resolved facts as immutable domain events. A
per-root observation lock and fingerprint prevent duplicate detection evidence.
The fingerprint is never used to authorize or resume an action: every display
and protected command reads current facts. Detection changes no membership,
resource status, approval, evidence, protection or task. Existing whole-job audit
redaction protects events containing hidden descendant references.

Causative resource/protection events remain intact. Action-specific proposal,
execution and final-action auditing retains its later phase ownership. No
irreversible action button, evidence upload or review-stage bypass was added.

## UI, timezone and performance verification

The existing Relationship Types table was inspected before adding the screens:
header background `rgb(238, 247, 253)`, one-pixel borders and `7px 16px` header
padding. New tables reuse its component and styling. Browser inspection found
NiceGUI's explicit one-column grid setting overrode responsive classes; omitting
that setting uses standard responsive grid classes. No CSS fallback was needed.
Native `wrap-cells` removes the observed `q-table--no-wrap` cause of clipped
columns. Direction and alignment are tested in both LTR and RTL.

Independent role-context and collection reads run concurrently. Member history
follows the member read because first-detection events must commit before
history is loaded. No new cache was introduced. Existing API-client in-flight
coalescing remains identity scoped; page tokens, revisions, captured client
contexts and cancellation prevent late responses from updating another page.
Restoring a nondefault page size does not fire another initial page request.

Browser checks used only newly created disposable databases and isolated UI
storage/cookies on ports 18030 and 18083. The fixture has 131 eligible roots,
two owners, 28 jobs and separately protected descendants. Verified operations:

- two-character owner/assignee searches and bounded job selection;
- create an empty unassigned destruction job, assign an authorized Officer,
  add a selected root, then explicitly remove it;
- missing reason: persistent warning, warning toast and focus on the reason;
  successful mutation: positive toast and refreshed stored state;
- admitted root disappears from eligibility; removal preserves its episode and
  displays its recalculated eligible status and separate audit events;
- owner grouping remains server paginated; breadcrumb restoration keeps grouping
  and page-two offset 25, with one matching page request;
- restricted Officer sees two separate hidden blocking records with generic
  vital reasons and no names, IDs or Open/selection actions; hidden counts are
  not exposed;
- Arabic locale uses RTL document/body direction, right-aligned table headers,
  mirrored navigation/paging, Arabic working-timezone timestamps and the normal
  English fallback for the new unpublished drafts.

Due instants remain UTC database values. Date/time filter input is interpreted
in the user's IANA working timezone and submitted with an explicit offset. The
API rejects offset-free filter instants. Tests cover Dubai conversion, London's
nonexistent clock time and both occurrences of its repeated clock time.

## Translation artifacts and deployment

`messages.en.json` and `messages.ar.generated.json` gain 133 contextual keys:
131 disposition controls/status/feedback keys and two audit labels. Both have
3,337 active keys in identical lexical order. All 3,204 starting Arabic items,
including their wording and provenance, are preserved exactly. New entries have
per-item generation metadata and retain `needs_human_review` flags and draft
status. No administrator export was promoted.

Coverage, ordering, nonblank, placeholders, terminology, stale references,
provenance preservation and artifact hashes pass. New Arabic wording still
requires human review and the existing explicit seed/review/publication workflow.
An automated approval review rejected clearing those flags; no flags were
cleared. Preview publication deliberately excluded flagged entries. A regression
confirms they remain unpublishable. The generic export/import test now uses four
controlled existing definitions rather than assuming every developing product
translation has already been reviewed. It restores its disposable catalogue.

Deploy/reload the API and WebUI together. The database must already have Phases
7–9 migrations 053–055; Phase 10 introduces no schema migration or environment
setting. There are no private `.env` edits or environment-template changes.
No persistent database, translation publication or deployed service was changed.

## Automated verification and cleanup

Final frontend/locale/client/table checks: **110 passed**. Final API reads and
filter matrix: **10 plus 1 passed**; catalogue/publication checks: **19 passed**;
traceability tests: **24 passed**. The combined earlier API regression run had
199 passes and one publication-fixture assumption failure; the corrected
controlled-catalogue round trip and full catalogue module subsequently passed.
No runtime publication guard was weakened. An extra final DST-control check
also passed. All 19 created databases, including failed runs, were independently
confirmed absent.

See `phase_10_completion` and the named verification runs in
`docs/disposition-requirement-ledger.json` for exact tests, results, database
names, cleanup confirmation and measured timing. Failed fixture runs are
recorded and their databases were dropped. Browser measurements are recorded in `docs/verification/disposition-phase-10/browser.json`.
Independent database cleanup and final timing are recorded in the ledger.

Measured active time: **1.83 hours**, from 06:16:18 UTC through 08:06:07 UTC on 15 October 2026. No user-wait interval was excluded.
