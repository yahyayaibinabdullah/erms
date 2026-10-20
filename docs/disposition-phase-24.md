# Phase 24 — controlled rollout preparation and handoff

Status: complete (20 October 2026). Persistent deployment and operational
physical/digital destruction have not been authorized or enabled.

## Deliverables

[The installation/upgrade guide](disposition-rollout.md) gives the ordered 050–070 upgrade
path, fresh canonical installation, bootstrap, separate feature/language seeds,
reviewed settings migration for each database, explicit conflict/stale-plan
handling, safe reruns, verification and eventual obsolete-key removal. [Operations section 14](operations.md#14-disposition-and-destruction-operations) is the
primary reference for initial role/profile and existing content access prerequisites, governed evidence
and report roots, database-backed SMTP with the deployment encryption key,
templates/Changa/native dependencies, all three worker processes, runtime versus
restart settings, safe unconfigured states, certificate-only recovery and
rollback limits after irreversible destruction.

`tools/rehearse_disposition_rollout.py` creates its own fresh and two populated
upgrade databases and drops all of them, including on failure. It uses the
actual bootstrap/settings/language-seed/worker CLIs and API lifespan. It never
starts the persistent local stack or takes a caller-supplied target database.
The existing PostgreSQL connection is used only to create dedicated disposable
databases; no persistent application data is read or changed.

## Verification

Evidence is in `docs/verification/disposition-phase-24/`.

- Final fresh installation plus two populated 050–070 upgrades passed. The
  fresh database exercised the actual administrator bootstrap without logging
  its temporary password. All targets passed actual API lifespan/health and
  eligibility, communications and destruction/completion worker one-shot runs.
- Both upgraded databases independently previewed/applied/checked the legacy
  settings file, verified values, and safely reran their completed plans. A plan
  from database A was rejected on B. Source file bytes were unchanged and a
  private canary/deployment value was excluded from plan output. Unconfigured
  fresh defaults were ready without an import. Feature seeds and guarded Arabic
  draft seeding passed; neither human publication nor a persistent edit occurred.
- Fresh/upgrade catalogues match; all old rows/fields/grants/events survive DDL.
  Both SQL operational execution gates stayed false.
- Thirteen disposable API checks passed for missing-destination warnings and
  action blocking, stale/conflicting migration plans, audit rollback, reruns,
  certificate generation/recovery, authorization and retained evidence.
- Four actual Word-to-PDF conversion checks passed with embedded Changa across
  all template types. This uses the existing host runtime and native packages;
  it is a fresh-database rehearsal, not a claim of testing every server OS image.
- Missing SMTP/recipient settings block queueing without a send attempt. The
  check uses disposable fixtures and sends no external email.
- Existing Phase 23 integrated, UI, indexer, bilingual/browser and populated
  upgrade acceptance remains linked. No UI behavior, translation artifact,
  environment variable or template changed in Phase 24.

The completed ledger records passing evidence for every applicable phase through
24. Six earlier pending RTL/policy records are retained separately as resolved
historical findings, pointing to their actual later passing browser evidence or
the user's explicit evidence-preservation clarification. They are not relabelled
as tests that passed at the earlier time.

## Boundary

This phase delivers instructions and disposable rehearsals. A maintainer must
commit/share the verified changes before colleagues can pull them. No commit,
push, persistent migration, role assignment, translation publication, production
email or operational release is performed here. Backup/restore and deployment
selection remain operator actions requiring deployment authorization. Reverting
code/settings cannot restore physical or digitally erased material.

Independent cleanup confirmed all nine Phase 24 databases absent. Source/template
checks and the full 369-entry acceptance gate through Phase 24 passed.
