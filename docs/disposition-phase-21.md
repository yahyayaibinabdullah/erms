# Phase 21 — Durable digital destruction and retained records

Phase 21 implements the three ordered changes: durable execution/manifests,
actual storage and derivative removal, then status 10 and protected retained
records. Digital and physical operational release functions remain false in the
canonical schema. Phase 22 owns certificates, final task/job completion and its
release checks. No persistent database was migrated and no commit was created.

## Requirement → implementation → verification

| Approved contract | Implementation | Evidence |
| --- | --- | --- |
| Destruction §15.1; DEST-11 | Native unchecked Manager confirmation and disabled execution button; protected command UUID/version boundary; current human authority, current task claim, preparer, stage, approval/letter/number, complete membership, physical confirmation and fresh blockers. UTC-normalized immutable execution facts. | Confirmation/retry/authority/task-release tests; real concurrent hold commit, current vital/security/relationship checks; live confirmation and queued state. |
| Destruction §18.8–10; DEST-12/26 | Migration 066 stores request/run/unit progress and proof-only manifests. One active run per job; bounded claims, session mutex, durable claim before execution, explicit retry after interruption; succeeded units never repeat. | Exact UUID retry; two live connections; real worker process exits before commit and after durable claim; mixed multi-unit failure/retry and unchanged earlier proof. |
| Disposition §9.2, §14.1/14.2 | Migration 067 and the dedicated worker remove all PostgreSQL content sets/segments, components, OCR/search documents/chunks, queued/staged indexing results, jobs and attempts in the unit transaction. Authorized downloads precede the record deletion lock. Source, converter and extractor working copies register before reading bytes and acknowledge only after real deletion; inherited locks protect surviving converter children. | Real PostgreSQL versions/OCR deletion; real file and child-process cleanup; native PDF response lifetime; partial-storage rollback; indexing/content regressions. Separate governed evidence bytes survive. |
| Disposition §13/14.2/14.3; DEST-13 | Migration 068 stores stable IDs, minimal hierarchy, destruction-time classification/owner/access/rule snapshots, actual human executor/name/time, number and separate physical/digital proof. Entire root and descendants reach 10 together only after erasure. Physical-only units in mixed jobs retain the original physical confirmer/time. | Full-unit finalization and minimal metadata assertions; mixed retry and Phase 20 recovery regressions; actual Phase 20 physical-outcome backfill upgrade. |
| Disposition §14.2, §15/16 | Ordinary views/search/hierarchy exclude 10. Immutable retained rows prevent restore, reopen, move, reclassification, new parenting and reuse. Disposition or audit privilege also requires current existing resource authority. Historical raw metadata and shared workflow snapshots lose prohibited descriptors/storage pointers for the destroyed unit; unfinished units retain their source facts. | Ordinary 404/search exclusion; privileged/read-only route checks; administrator without current resource access denied; immutable event/proof guards; snapshot minimization and retained history tests. |
| Destruction §15.2 | Durable progress is read fresh through the existing workspace and My tasks. Polling stops on abandonment/terminal state; optional outcome producer uses the existing notification registry/immutable source-event deduplication. Counts do not claim final job completion. | EN/AR component tests, notification delivery/deduplication, live navigation and completed-unit progress. |
| WebUI/i18n/performance contracts | Existing Wathiq PageTable styling, sortable bounded retained/manifest pages, native controls, no new cache or bulk catalogue download. | Live LTR/RTL comparison with membership/task tables; EN/AR forms; exact Arabic preservation/coverage/hash/placeholder/new-key glossary checks. |

## Verification

Evidence is in `docs/verification/disposition-phase-21/`. Overlapping runs are
not added into a unique-test total.

- Integrated execution, recovery, indexing and notification acceptance: **54 passed**.
- Ordinary content/authorization/conversion regressions: **11 passed**.
- Text-indexer unit regressions: **28 passed**.
- English/Arabic UI, member tables, tasks, recovery, physical controls and audit labels: **76 passed**.
- Simultaneous hold/vital/security/relationship commits during the worker wait: **4 passed**.
- Final retained-history/native-preview/shared-unit proof checks: **3 passed**.
- Fresh canonical versus populated 066–068 upgrade: complete function/view/catalogue parity and every prior row preserved.
- Actual Phase 20 final physical outcome backfill and rejection of undrained legacy indexers: **passed**. Original executor/time/event/number and separate bytes remain intact.

All tests use newly created disposable PostgreSQL databases. Cleanup evidence
records independent absence checks, owned preview shutdown and browser cleanup.
Acceptance fixtures temporarily enable execution only in their owned synthetic
databases. No test suite touches `demo` or another persistent ERMS database.

Both catalogues contain **3,712** aligned active keys. All **3,665** previous
Arabic items retain their exact text/provenance; **47** new contextual keys have
Arabic drafts marked `needs_human_review`. No administrator export was replaced
or translation published. Placeholder, blank, markup, ordering, stale-key,
provenance and artifact hash checks pass. New-key glossary checks pass; existing
curated terminology is preserved. Live Arabic uses the approved English fallback
for unpublished keys; EN/AR component tests exercise the new Arabic wording.

## Deployment

1. Keep operational execution disabled. Drain and stop old text indexers and
   active API preview/conversion processes before the upgrade. Verify all their
   owned legacy temporary content is removed; legacy workers have no durable
   copy receipts. Migration 067 rejects leased jobs or active worker registrations.
   Finish/release leases and allow registrations to expire before retrying; never
   clear live leases to bypass this prerequisite.
2. Apply **066**, **067**, **068**, in order, after 065 and all predecessors. A new
   empty database uses `database/schema.sql` alone. Migration 068 minimizes
   existing proven physical-only final outcomes; anomalous final rows with
   digital content or missing actual executor evidence stop for operator review.
3. Deploy/restart API, WebUI and the updated text indexer together. The indexer
   must use its new working-copy registration/cleanup protocol. Retain service
   scratch roots until cleanup acknowledgments succeed. Across multiple service
   hosts, outstanding receipts deliberately block erasure until each owning host
   recovers and acknowledges actual cleanup. A DB receipt must never be manually
   deleted to pretend that a working copy was erased.
4. Install `backend/services/api/deploy/erms-disposition-destruction.service` for
   the dedicated worker when the later release gate is ready. Its bounded CLI is
   `python -m backend.services.api.disposition.destruction_worker --watch
   --batch-size 1 --interval-seconds 5`. It rechecks 068 and does no work while
   the canonical release function is false.
5. Reconcile the optional destruction outcome producer through the existing
   `database/seeds/disposition-notification-producers.sql`, then configure,
   review and activate its language templates/audience in Notification
   Administration. No notification template or producer is activated implicitly.
   Seed/review/publish the new translation drafts through the existing workflow.

No environment variables or templates changed. All 36 API settings pass template
reconciliation. No encryption key, SMTP setting, local `.env`, MailDev mailbox,
or persistent application setting was modified.

Successful digital destruction leaves the job active and its completion task
unfinished. Phase 22 must save the single digital certificate before final job
completion, implement certificate-only retry/download behavior and show the
external-backups/copies warning.

Live sizing investigation: the standard NiceGUI dialog/card width classes were
overridden by QDialog’s computed 560px maximum, clipping the last table action.
The installed NiceGUI dialog has no width argument; full-width would discard
the bounded proof-dialog size. The three proof cards reuse Wathiq’s existing
card `.style()` width/max-width pattern (1024px, viewport minus 32px). This is
a narrowly scoped fallback, with measured LTR/RTL verification.
