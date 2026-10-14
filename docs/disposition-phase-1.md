# Disposition Phase 1 implementation baseline

Phase 1 establishes the requirement, integration, and verification baseline for
the approved Administration Settings, Application Configuration, Disposition,
and Destruction Process specifications, including the 13 October 2026 Records
Manager Only and Save amendment. Settings and workflow runtime implementation
starts in the later phases assigned below.

Baseline revision: `fd90a426ef3dd318fcafe89f147748163ec33831`.
Inspection and verification date: 14 October 2026.
Measured session: 2026-10-14 04:24:21 to 2026-10-14 05:41:29 UTC (1.29 active hours).

## Requirement ledger and completion evidence

The maintained [requirement ledger](disposition-requirement-ledger.json) contains:

- all 100 acceptance IDs: ACFG-01–17, DISP-01–42, and DEST-01–41;
- every numbered source section's own prose, tables, fields, and invariants,
  including parent introductions: 171 section entries;
- scoped supporting security, ownership, relationships, holds, retention,
  storage, resource lifecycle, media/location, messaging, authentication,
  indexing, internationalization, performance, and design contracts;
- all 51 database-managed settings and 42 deployment inventory rows from
  Application Configuration sections 4–5;
- the four approved configuration decisions, their owners and named tests;
- inspected symbols, existing test selectors, actual verification runs,
  integration locations, missing implementation, and later decision gates.

`ACFG-S7`, for example, covers every clause of Application Configuration section
7, including requirements not repeated in an acceptance ID. Its source locator
and hash identify the exact contract. Parent sections stop at their first child
heading; their introductory prose is not discarded. Revision histories describe
historical decisions and are not additional current product requirements. The
approved non-numbered local environment reconciliation is separately included.

`phase_plans` gives the implementation locations and acceptance cases for each
owner. An entry links those plans through `planned_locations` and named
`planned_checks`. These names identify planned verification scenarios; they are
not existing tests or passing results. Later work must attach concrete test
selectors, implementation locations, run results and required browser/render
evidence in `implementation` and `verification`. Supporting-contract entries
require compatible reuse of their applicable rules, not new unrelated features.

Every product entry remains **planned**. `baseline_refs` proves only the stated
reuse finding; it does not satisfy an unimplemented disposition requirement.
This describes the Phase 1 snapshot; the maintained ledger now includes
[Phase 2 foundation evidence](disposition-phase-2.md) without completing its
later UI, consumer-cutover or workflow clauses.
The checker rejects incomplete source/setting coverage, source drift, missing
owners or test plans, altered approved decisions, read-only business settings,
and product completion without passing evidence for every applicable phase.

Run these database-free checks from the repository root:

```sh
python3 tools/check_disposition_baseline.py
backend/services/api/.venv/bin/python -m pytest -q tools/tests/test_disposition_baseline.py tools/tests/test_reconcile_local_env.py
python3 tools/sync_api_env_template.py --check
```

The checker validates the ledger; it never regenerates source contracts or
converts planned scenarios into passing results. Reconcile ledger entries
deliberately after an approved specification change.

## Existing implementation and required extensions

| Area | Inspected reuse and passing evidence | Required extension and owner |
| --- | --- | --- |
| Organizational responsibility | `org_units.managing_role_id` and `file_administrator_role_id`, same-unit/non-system/non-service validation, active File Administrator assignment, designation audit, nearest configured contextual ACL resolution. `test_hierarchical_oversight_acls.py` passes. Canonical SQL and migration `048_hierarchical_oversight_acls.sql` already contain the fields. | Reuse the columns; do not add them again. Implement task routing, no-role skip versus unusable-role block, source-unit attribution, assignment effectiveness and claiming in Phase 13. Contextual ACL matching is not a workflow router. |
| Authorization | `authorization_policy.authorize`, `load_policy_context`, `require_global_privilege`, `resource_authorization.py`, database privilege/view predicates. Governance privilege/clearance/ACL-bypass regressions pass. | Settings authority in Phase 2; common disposition authorization in Phase 7 and operation-specific phases. Enforce task-only File Administrator/Unit Manager rights in Phases 13–16 without granting full job management. Assignment never grants content access. |
| Retention | `aggregation_effective_retention_rule` resolves root-local override before inherited classification rule with source/provenance. Classification APIs and hierarchy/local-override tests pass. | Database UTC due timestamp and strict boundary in Phase 8. Rule, classification, reopening and hierarchy hooks with whole-unit/job recalculation in Phase 9. Do not store a second job-local retention rule or rename `selective_preservation`. |
| Legal holds | `effective_holds_for_aggregation`, `effective_holds_for_record`, `resource_has_effective_hold`, preservation triggers and `lock_hold_policy_shared/exclusive`. Existing hold lifecycle, visibility and management API tests pass. | Integrate current all-descendant admission/final checks and explicit hold-versus-disposition races in Phases 8–9, 15, 19 and 21. Existing ordinary-deletion protection is insufficient proof of final-action safety. |
| Relationships | `resource_relationships.py`, `guard_resource_relationship`, separate aggregation/record tables, both-endpoint access, both directions, sorted endpoint locks, bounded selectors, audit. Full relationship API regressions pass. Migration 049 and the separate relationship-type seed exist. | Job-aware blockers/summary in Phases 8–10 and 16; exact-link proposals/execution in 14–15; final rechecks and historical-link recovery in 19–21. The module explicitly defers disposition integration. |
| Medium, vital status and locations | Governed commands in `main.py`, vital deletion triggers, media and inherited-location representations. Vital direct-SQL/concurrency tests pass; no independent stored record location exists. | Inspect every descendant's medium and protection, rather than relying on root medium. Generate physical scope/location/count reports in Phase 19, preserving existing location semantics. |
| Storage and governed record creation | `PostgreSQLContentStorage`, content sets/segments and `commit_record_draft`. Byte-range/segment reconstruction, closed subtree and atomic draft promotion tests pass. | Phase 11 joins governed record/component creation to job evidence/outcomes. Phase 21 removes every controlled original and derivative, including indexing staging/results and temporary copies. Ordinary DELETE is not destruction. Inspect streaming/finalization boundaries before reuse: current `store_upload` streams segments on its caller's transaction; the short-finalization contract cannot be assumed from segmented storage alone. |
| Audit and versions | `audit_context.py`, `expected_version`, `record_entity_history`, `append_domain_event`, immutable history guards. Correlated history, read-only audit and optimistic-conflict regressions pass. | Add settings/job identities and safe domain events at their owning phases. Use dedicated secret-safe events rather than generic secret-row snapshots. Resolve the historical-snapshot minimization question before Phase 21 finalization (below). |
| Notifications | `SystemNotificationDefinition`, registry initialization, `emit_system_notification`, `message_request_receipts`. Typed producer, atomic business rollback and duplicate-event notification tests pass. | Register disposition producers using the existing subsystem in Phases 13, 18 and 22. Calendar reminders require their own durable per-person/interval checkpoint. External SMTP document delivery belongs to Phase 18 and does not replace notifications. |
| UI infrastructure | `RemoteSelect`, `resource_relationships.py`, `api_client.py`, paged browse and `erms-page-table`. Selected unit/source checks for role fields, relationships and bounded collections pass. | Settings and custody warnings in Phase 3, eligibility/jobs in 10, tasks/workspace in 16, recovery in 20 and final tasks in 22. Each UI phase must verify live saves, server pagination, standard table appearance, navigation freshness and both directions. |
| Calculated date display | `retention_timeline.disposition_dates` and its 11 tests pass for the existing local-calendar display. | This helper converts closure to the user's timezone before calendar arithmetic. It cannot implement DISP-03. Phase 8 calculates the authoritative database timestamp; Phase 10 uses it for display without timezone-dependent eligibility. |
| Application configuration | `config.py` and WebUI `config.py` remain environment-backed; API authentication, main and dashboard contain import-time policy constants. `database.py` reads indexing scheduling during request context setup. | No shared settings table/registry/cache/API/UI, settings privilege, migration provenance or readiness command exists. Phase 2 supplies the shared foundation; Phases 4–6 cut over consumers and workers. |

The reuse findings above are limited to the inspected symbols and selected
passing tests. They do not claim full reacceptance of every supporting subsystem
or its historical migrations. New schema and upgrade parity must be verified
by each phase that changes persistence.

## Configuration ownership and cutover inventory

The ledger records the exact specified type, initial default, validation,
ownership, consumers and relevant tracked templates for each setting. It reads
tracked source/templates, not private `.env` values. Disposition and Email rows
use their approved descriptive names because their stable registry keys have
not yet been chosen; Phase 2 chooses technical keys without adding settings.

| Approved group | Count | Consumer cutover |
| --- | ---: | --- |
| General application behavior, section 5.1 | 3 | Phase 4: API main/localization/dashboard and WebUI effective defaults |
| Content/viewing policy, section 5.2 | 7 | Phase 5: content storage, document conversion and cleanup |
| Authentication/session policy, section 5.3 | 8 | Phase 5: authentication request evaluation and session cleanup |
| Dashboard/selector/admin limits, section 5.4 | 6 | Phase 4: dashboard API, WebUI config/consumers and bounded selectors |
| API search/indexing policy, section 5.5 | 10 | Phase 6: search, middleware/health, DB scheduling context, maintenance and credential-history consumers |
| Disposition, section 5.6 | 7 | Phase 2 registry, Phase 3 controls, later operation-specific consumers |
| Email, section 5.7 | 10 | Phase 2 protected registry, Phase 3 controls, Phase 18 send service |

For every legacy key, the cutover change must switch consumers and remove the
environment fallback together. Before that switch, preview/apply the reviewed
legacy values for one explicit database. Do not remove private-file assignments
or infer that migration of one database migrates another. Preserve deliberate
configured values equal to defaults using provenance, not value comparison.

Current API `FULL_TEXT_SEARCH_ENABLED` and
`CONTENT_INDEXING_SCHEDULING_ENABLED` fallback reads use `true` in several
places, while the approved registry defaults and tracked rollout templates are
`false`. `DEFAULT_WORKING_TIMEZONE` currently requires an environment value;
the approved database default is `Asia/Dubai`. These differences must be
explicit in the reviewed cutover and operator guidance. Do not silently copy a
code fallback or change an existing configured value. The obsolete WebUI
full-text flag is removed and reconciled against the API flag, not migrated to
a second key.

Retain deployment connectivity, process capacity, cookie/storage infrastructure,
orchestration controls and every separate text-indexer process setting. Keep
API-owned indexing policy distinct from indexer deployment policy even when
their names start with `TEXT_INDEXER_`.

Approved messaging limits/infrastructure remain governed by the Messaging
specification (including section 11.5 and its real-time architecture), rather
than being silently removed by the general template migration. Phase 6 must
reconcile that supporting contract in its production inventory. Storage section
6 mentions `CONTENT_DOWNLOAD_DB_BATCH_SIZE`, but no current consumer/template
was found; do not invent a new variable during this baseline.

Template consumers reviewed: `.env.example`, `.env.example.api`,
`.env.example.text_indexer`, `backend/services/api/deploy/api.env.example`,
`frontend/webui/deploy/webui.env.example`, and
`backend/services/text_indexer/deploy/text-indexer.env.example`. The API deploy
template remains authoritative and its generated copy passes sync validation.
No template/default/environment ownership changed in Phase 1.

## Approved configuration decisions applied to the implementation plan

| Decision | Implementation boundary | Named planned verification |
| --- | --- | --- |
| General cache is 30 seconds | Phase 2 complete non-secret snapshot per logical DB/API process, clock from successful load completion, one reload lock, local update invalidation; fresh create/save/send reads bypass it. | `test_cache_hit_expiry_and_load_completion_clock`, `test_concurrent_reload_is_single_load`, `test_updating_process_invalidates_and_other_instance_converges`, `test_refresh_failure_retains_only_valid_snapshot`, `test_fresh_operations_reject_stale_fallback` |
| Every DB-managed setting is editable | Registry and authorized translated controls, including protected write-only secret replacement. No deployment settings exposed. Phases 2–6. | `test_every_registered_database_key_is_editable`, `test_authorized_ui_grouped_save_and_reload_every_setting`, `test_secret_is_write_only_replaceable` |
| Preserve existing non-default values | Reviewed per-database migration, untouched-default provenance, configured-default conflict protection, rechecked versions and per-migration completion. Phases 2, 4–6 and 24. | `test_upgrade_inserts_missing_rows_without_overwrite`, `test_preview_preserves_legacy_nondefault_without_writes`, `test_configured_default_is_not_untouched_default`, `test_invalid_conflicting_values_and_preview_race`, `test_completed_rerun_and_later_key_migration_are_isolated` |
| Save related settings atomically | One reason, validation of the complete resulting dependency set and every expected version; values/audit/provenance/completion share the applicable transaction. Category does not force unrelated updates. Phases 2–6. | `test_destinations_validate_as_one_set`, `test_smtp_set_validates_without_secret_disclosure`, `test_group_version_conflict_rolls_back_values_and_audit`, `test_migration_completion_commits_with_group` |

The database-free Phase 1 negative controls verify that these approved decisions
and their test plans cannot silently disappear or change. Runtime verification
is owned by the phases above; Phase 1 does not claim an implemented cache,
editable Settings page or settings transaction.

The future cache's key is the logical database identity within its API process.
It contains shared non-secret business values only, not users, resource
authorization or translated labels. User/language-specific rendering occurs
after authorization; there is no second authoritative WebUI cache. Ordinary
refresh failure may retain only a previously fully validated snapshot; startup
and fresh operation-boundary reads cannot substitute stale/environment values.

## Technical integration and transaction boundaries

These are implementation boundaries for the approved operations. Concrete
route models, SQL functions and locking details are verified at their owning
phase; no additional product states or API contract is established here.

| Operation | Required transaction and integration boundary |
| --- | --- |
| Settings load and startup | In Phase 2 load via an existing connection or raw pool connection without recursively invoking `get_connection`. When general consumers cut over, open the deployment-configured pool before validating DB settings. Preserve the existing locale-definition and notification startup hooks. Capture one immutable snapshot per request/worker pass; remove import-time business constants in Phases 4–6. |
| Settings update | Authenticate and check `app.settings.manage`; validate the complete proposed related set; lock/check submitted row versions in deterministic key order; change values/provenance and safe per-setting events in one transaction. Invalidate the updating process's cache only after successful commit. Failed validation/version/audit work leaves the group unchanged. |
| Explicit legacy migration | Preview has no writes. Apply rechecks versions, preserves configured values, and commits the applicable group, source=`migration` history and target-database completion together. Defaults use source=`seeding`. The launcher checks readiness, never imports values. |
| Job creation | Directly read committed review route and capture it once with job creation, actual human actor/history and the route-appropriate initial task. Route remains immutable. Use current role/access policy, not job assignment as authorization. |
| Membership and recalculation | One protected transaction per selected root joins admission, membership episode, complete descendant status propagation and history. Different selection results may commit independently. Reopen/rule/classification/hierarchy hooks join their resource changes to whole-unit recalculation and required-removal/job blocking. |
| Claim/review/Save | Lock task/job/round/current versions and recheck eligible user/role/access/claim ownership. Persist attributed saved proposals, own notes, removal recommendations and partial overall reason/history together. Save keeps the task and stage unchanged. Submit/approve validates the exact current saved work and required overall reason. |
| Proposal approval | Use the approving Records Manager's user/acting-role audit context on the same connection for every underlying operation. Lock job/round/members/targets/holds/endpoints in coordinated order; validate the complete set; compute cascading removals to a stable result. Proposal/resource/status/membership/approval/effect/history changes commit together. Generate the per-round report after commit with durable retry/deduplication; do not replay resource changes. |
| Artifact save and external/physical evidence | Capture current committed scheme/destinations as a consistent set. Resolve and recheck the latest open root (`date_opened DESC, id DESC`) and resource access/versions within governed record finalization. Outcome, job document link, governed record/component and required history succeed together. Stage large bytes outside long-held business locks; reuse verified draft promotion at finalization. Missing destinations block the applicable task. Earlier destinations and evidence versions remain intact. |
| Document email | Capture recipient/SMTP/secret and exact existing artifact version once, server-side. Persist a deduplicated attempt before external network work, then persist its outcome/history. PostgreSQL and SMTP cannot be one atomic commit; interruption around SMTP acceptance requires truthful unknown-outcome handling. A deliberate resend has a new attempt identity and never advances workflow. |
| Reminder/task notification | Invoke `emit_system_notification(transaction=...)` on the caller's business transaction with an allowlisted producer. Reminder checkpoint and durable message creation share the applicable transaction and unique per-person/interval identity; purging a message cannot permit duplicates. |
| Final action and protection changes | Existing hold shared/exclusive policy locks, ordered relationship endpoint locks, closure ancestry locks and continuity locks are integration inputs, not a proven unified disposition lock protocol. Phases 7–9/19/21 must make every participating vital/security/hold/relationship/hierarchy/membership path use a consistent documented ordering and recheck changed predicates. Race/deadlock/rollback tests are mandatory. |
| Digital work and completion | Durable claims/runs/manifests identify bounded work. External deletion can cross PostgreSQL commit boundaries, so persist irreversible progress and resume only unfinished work under current approved scope. Never equate row status with deletion. Digital certificate storage is independently retryable after deletion; job completion requires its evidence. Physical-only completion uses physical evidence and skips digital runs/certificate/tasks. |

SMTP credentials currently have no reusable reversible protected-secret store.
Authentication and service credentials are hashes, which cannot supply an
outbound password. Phase 2 must select an at-rest secret representation/key
lifecycle within the approved contract and prove secret-safe storage, reads,
errors and history. If that design requires an extra deployment setting or
another product-level departure from the approved inventory, obtain explicit
approval before adding it and reconcile every relevant environment template.

## Specification reconciliation and later decision gates

The approved amendment governs three routes. Administration Settings section
6's older “only Standard and Simplified” bullet and section 7's old “draft/open”
configuration wording are superseded by its section 3, Application Configuration
sections 5.6/12, Destruction sections 5.4–5.5 and the approved plan amendment.
They are recorded in the ledger; the approved specs were not rewritten.

The template section's historical statement that implementation is not yet
authorized does not block the approved plan's Phase 12. This Phase 1 request
does not start template work. The authoritative due-date requirements govern
eligibility even though the existing UI helper uses local calendar arithmetic.

One later product decision needs explicit resolution before **Phase 21 retained
record finalization**: existing immutable audit events contain full resource
before/after JSON through `record_entity_history`, including descriptions and
other free text. Disposition section 14.2 prohibits retention of unnecessary
free text, personal information and content extracts, including in event
messages, while the common resource/audit contract prohibits rewriting or
deleting historical events. A restricted UI projection alone does not remove
prohibited stored values. Define the approved treatment of historical snapshots
that contain prohibited values before implementing finalization: do not silently
introduce an audit-mutation exception or retain all prior payloads. This does
not block Phase 2 or the common disposition foundation.

Permanent transfer, selective transfer and local-archives action-specific final
workflows remain deferred pending their own approved specifications. Their
shared statuses/job structures are in scope; inventing final workflows or
enabling final actions is not.

## Verification and handoff

- **103 selected API/database regressions passed** in 75.60 seconds, with two
  existing Starlette/httpx/anyio deprecation warnings. Exact suite/node targets
  and results are recorded in the ledger's `verification_runs`.
- Disposable database
  `erms_messaging_test_acl_1e7696fc430e474581c673900fed7d41` was created,
  initialized from the self-contained canonical schema and separate required
  seeds, used by the full test process/fixtures, and dropped successfully by
  the repository runner. The first sandboxed attempt could not connect and
  created no database; the approved rerun succeeded. No persistent ERMS
  database was tested or changed.
- **31 WebUI unit/source checks passed** in 1.42 seconds for the calculated
  date helper, role fields, relationships and bounded collections. They are
  database-free and do not establish new-page live-browser acceptance.
- **27 traceability/local-environment tests passed** in 0.95 seconds: 24
  coverage/completion negative controls and three existing safe-reconciliation
  tests. The final run is recorded in the ledger.
- Source/setting coverage and approved decision checks pass. API environment
  template sync/check passes. Python compilation, shell syntax and whitespace
  checks pass at handoff.

No application runtime, schema, migration, seed, environment template or
user-visible UI text changed. English and Arabic catalogue artifacts are
unchanged; no administrator export was promoted and no new translation review
is needed. Browser/PDF verification is assigned to the UI/document phases.
No deployment/operator action is required for this baseline.

Phase 1's gate is met: source requirements have phase owners and planned
verification, reuse claims have bounded evidence, integration/transaction
boundaries and gaps are documented, and the remaining decision identifies its
later blocking phase. The implementation plan records this phase's measured
UTC session and completion. **Phase 2** is the next recommended phase: shared
settings registry, protected administration API, audit, provenance, cache and
fresh operation reads.
