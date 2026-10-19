# Phase 18 — external document email and eligibility reminders

Saved request PDFs can now be sent through a durable server-owned queue, with
current recipient/SMTP settings captured per attempt. A deliberate later send
creates another attempt; the same submission returns its original attempt.
The browser displays the recipient before sending and retains failed/uncertain
submissions. Sending never advances the destruction workflow.

## Requirement-to-implementation-to-test traceability

| Approved requirements | Implementation and verification |
| --- | --- |
| Destruction §11.4; DEST-35; ACFG §§5.6–5.7, 6.1; ACFG-14/15 | `email.enqueue`, protected migration 063, purpose-built POST and worker bind job/document/round/person/role/request identity, exact immutable content-set/checksum, recipient, sender, message ID and captured transport settings. Credentials stay encrypted in private pending payloads and are erased on outcome. Config changes preserve old attempts; recipient changes require refresh. Retry and deliberate resend tests verify one versus multiple attempts, matching attachment bytes, current settings and unchanged job snapshots. |
| Destruction §16; DEST-36, 40 | The shared sender accepts saved digital certificates for an actual currently authorized Manager, including after completion. A synthetic completed-job/certificate fixture verifies authorization, repeated sends, exact bytes and unchanged job facts. The genuine final-action → certificate generation → completed-job end-to-end workflow remains Phase 22, as the Phase 18 plan explicitly requires. |
| Destruction §11.4; DEST-16 | Durable `sending`, `smtp_accepted`, `failed`, `unknown` outcomes, server timestamps and actual initiating actor/role are retained in job audit/history. SMTP acceptance is explicitly distinguished from inbox arrival/read confirmation. Verification covers verified STARTTLS/implicit TLS, auth failures, DATA refusal versus disconnect, lost-worker recovery, overlapping workers, safe status codes and no raw credential-bearing errors. Network I/O holds no database transaction or business lock. An uncertain send is never automatically replayed. |
| Destruction §3, §18.11; DEST-01/27; MSG-018/019/021 | `reminders.run_batch` uses the existing optional notification producer, templates, audience resolution and receipts. Bounded committed-state batches choose active people with effective Officer/Manager profiles supplying `disposition.jobs.manage`; dual-profile people receive one reminder. Durable calendar anchors/checkpoints survive message purge, restarts and duplicate workers. Interval changes reanchor future schedules; no historical notifications are replayed. Tests cover month-end/leap boundaries, changed interval, disabled/no-work cases, real message purge, duplicate workers and privacy. Notification details link to the authorized, server-paginated eligibility listing without resource metadata. |
| Authorization, UI, performance and translation contracts | Assigned Officer or Manager Only task authority, current request/approved facts, exact artifact visibility/download permission and current Manager certificate authority are checked before queueing and again before transport. Native controls and shared Wathiq `PageTable` provide lazy bounded sortable history, safe errors/toasts, explicit refresh and read-only history after task closure. No data cache is introduced. Bilingual component tests cover uncertain retry identity, deliberate resend, abandonment and lazy history. Existing task and messaging projections remain server-authorized. |

## Verification and local MailDev

Evidence is in `docs/verification/disposition-phase-18/`; overlapping runs must
not be added as unique test totals.

- Canonical API/external/workspace/task-notification/shared messaging regression:
  **91 passed**.
- Pending HEAD → 062 → 063 upgrade acceptance: **43 passed**.
- Final retry/role-control/worker-attribution/workspace acceptance:
  **37 passed**; final communications/EHLO regression: **25 passed**.
- Frontend/forms/history/navigation/bounded collection/messaging/translation
  grammar/traceability checks: **118 passed**.
- Full canonical versus upgraded catalogue parity and every pre-existing
  public/private row preservation passed. Both probe databases were dropped.
- EN/AR coverage, source references, ordering, placeholders, blanks, new-draft
  terminology/provenance/timestamps/hash and exact preservation of previous
  Arabic entries passed. API environment templates still agree.

The user supplied MailDev at `localhost:1025` and its MCP endpoint at
`http://localhost:1080/mcp`. That SMTP listener advertises no STARTTLS. The
optional **test-only** `tools/maildev_tls_preview.py` bridge binds loopback,
creates a temporary localhost certificate, and forwards to MailDev. Only the
disposable preview worker trusts that exact certificate; certificate/hostname
verification remains enabled. No system trust store or production transport
configuration is weakened. The bridge and certificate disappear with preview
cleanup. MailDev tests use unique synthetic sender addresses and `.invalid`
recipients; existing messages are not edited or removed.

This real transport check caught a missing EHLO in the unauthenticated
implicit-TLS path. The failed attempt correctly retained its failed status.
The sender now performs EHLO on both TLS paths; a regression assertion prevents
this omission. All three final MailDev captures matched the saved RFC Message-IDs and exact
PDF checksums: two deliberate Manager Only sends and one Officer send from
the RTL workspace. Navigation retained prior attempts. Capture and LTR/RTL
history evidence is recorded in `maildev-verification.json` and screenshots.

## Deployment

Apply **063_disposition_communications.sql** after **062** and any pending
predecessors; new empty databases use `database/schema.sql` alone. Run the
separate idempotent `database/seeds/disposition-notification-producers.sql`
seed to register the optional reminder contract. Configure and activate its
English/Arabic notification templates and dynamic current-governance-person
audience through existing Notification Administration. The producer remains
dormant until configured/enabled. The first worker pass persists the future
calendar anchor; interval-setting revisions establish a new future schedule.

Restart API and WebUI. Deploy/enable
`backend/services/api/deploy/erms-disposition-communications.service`, or run:

```sh
python -m backend.services.api.disposition.communications --watch --batch-size 100 --interval-seconds 30
```

The worker uses the existing API environment and database SMTP settings,
including the existing encryption key. All instances for one database must
retain the same deployment key. No environment variable/template change was
introduced. Configure the real recipient, sender, verified TLS mode and SMTP
credentials in Application Configuration before sending.

The English manifest and canonical Arabic artifact add **22** contextual keys
(**3,619** active keys per language). All **3,597** previous Arabic entries,
including wording and provenance, are unchanged. New entries are generated
drafts flagged `needs_human_review`; explicit seeding/review/publication remain
operator actions. No administrator export was promoted and no new drafts were
published. No persistent ERMS database, including `demo`, was tested or migrated.
All 16 owned disposable databases are independently confirmed absent; the
API/WebUI/TLS bridge ports and owned browser tabs are closed. The three test
captures remain in the user’s MailDev. Changes remain uncommitted.
Phase 19 owns physical preparation/confirmation;
no destruction action is introduced here.
