# Phase 22 — certificates and final task behavior

Status: complete (20 October 2026). Live Arabic verification passed in the
in-app browser after the approved DISP-35 clarification. Phase 23 has not
started. Canonical physical/digital release gates remain closed.

The evidence-retention investigation is recorded in
[the finding](disposition-evidence-retention-finding.md). No separate approved
expiry/deletion policy was found. On 20 October 2026 the specification owner
approved removing that undefined separate feature from Phase 22 while preserving
protected governed evidence and permanent provenance. Disposition revision 1.7
and implementation-plan revision 1.3 now record that clarification; no duration,
purge setting, privilege or deletion procedure was introduced.

## Implemented behavior and traceability

| Contract | Implementation | Verification |
| --- | --- | --- |
| DEST-14; destruction §§15.2, 16 | The last successful digital unit queues durable certificate work. The bounded worker renders the existing bilingual Word template, stages its PDF, then rechecks current authority and immutable outcome facts in a fresh consistent transaction. Certificate, governed record/component, job completion, Manager download task and history commit together. Unique indexes prevent duplicate certificates/tasks. | `test_disposition_completion.py`: automatic completion, mixed jobs, real PDF, storage/completion rollback, simultaneous workers and interrupted ownership. |
| Certificate-only recovery, §16 | Safe failure codes leave destruction committed and the job incomplete. A currently authorized Manager explicitly retries certificate work only; ordinary destruction is never repeated. A changed destination, role or task claim is checked again. Operational release remains required. | Failure/retry, missing destination, permission revocation during rendering, conflict, exact retry and atomicity tests. |
| Physical-only completion, §17.3 | Physical confirmation, saved physical certificate, complete-unit final metadata and job completion share one transaction. No digital run, digital certificate or download task is created. The exact committed confirmation remains acknowledgeable after its task/job close, with current Manager/evidence access and original command bindings; new or changed submissions remain rejected. | Physical-only completion/exact retry/conflict/new-command tests, existing physical/recovery regressions and database whole-unit constraints. |
| DISP-14, DISP-26 | Certificates use permanent destruction proof, actual executors and execution-time names, destruction number, approved request reference, scope/counts, physical reference and integrity hash. Certificate-generation time is separate from destruction completion time. | Real saved PDF and final-field assertions; existing actual-executor/proof regressions. |
| DEST-36; §16 | The Manager downloads the saved PDF; download closes only its task and records history. Existing Phase 18 email sends the exact saved certificate repeatedly, including after completion. Send history is available before and after download; neither gates completion. | Actual download endpoint, genuine completed-job repeat-email regression, English browser download and two SMTP-accepted attempts captured by local MailDev. |
| DISP-30 | Completed digital, mixed and physical-only jobs show the warning about external backups/copies and Wathiq's responsibility boundary. | English/Arabic native component tests and English live browser capture. Live Arabic passed in the in-app browser on 20 October 2026. |
| DEST-23; existing notifications contract | Durable work survives navigation. Existing optional notification administration/receipts deliver completion or certificate-failure outcomes only to currently authorized Managers. Certificate tasks use the existing task-assigned producer. | Configured-producer deduplication acceptance, English navigate-away/recovery check, EN/AR abandoned-response and lazy-history tests. |
| DEST-15; DISP-35 (approved clarified scope) | Certificate/evidence records remain outside destroyed units, use current evidence settings, and retain ordinary record access controls and immutable provenance. | Evidence-boundary regressions, destination and real certificate storage assertions. These tests cover the clarified preservation scope. Separate expiry/deletion acceptance is outside this phase. |

Migration `069_disposition_completion.sql` and the independent canonical schema
contain the same DDL. Existing successful digital runs awaiting a certificate
receive queued checkpoints using their actual saved requester/task/role.
Neither migration nor canonical schema enables operational destruction.

## Verification evidence

Evidence is under `docs/verification/disposition-phase-22/`. Test runs overlap;
their totals must not be added into a unique-test total.

- Certificate, workflow and physical acceptance: `backend-acceptance.log`.
- Affected evidence, physical, recovery, erasure and email regressions:
  `backend-regressions.log` (116 passed).
- Native English/Arabic forms, task tables, completion, email and audit labels:
  `frontend-acceptance.log` (82 passed).
- Populated upgrade versus canonical schema: complete catalogue parity and
  preservation of every prior public/private row (`upgrade-parity.log`).
- The real template renderer produced a bilingual PDF with embedded Changa.
  Both PDF and rendered-page evidence are retained as synthetic test artifacts.
- English browser checks verified current recovery actions, retained unit
  counts, navigation-independent recovery, completion before download, the
  external-copy warning, download history, repeat send and persistent outcomes.
  Standard task and membership tables retained Wathiq's light-blue presentation.
- MailDev MCP search/get verified two synthetic captures, their recipient,
  subject and PDF attachment name. Its attachment-download tool returned
  `Attachment not found` despite listing the attachment; independent MailDev
  attachment-byte comparison was unavailable. Exact saved attachment bytes are
  verified by the API transport tests. Existing MailDev messages were untouched.
- The earlier Chrome connection failure was resolved for verification by using
  the Codex in-app browser on 20 October 2026. Arabic certificate-only retry,
  navigate-away completion, completed memberships, warning, actual PDF download,
  task closure, repeat send and persisted history passed. The final fix exposing
  send history before download was verified live. The downloaded PDF exactly
  matches the saved certificate (49,111 bytes; hash in `live-arabic-state.json`).
- RTL task, membership, evidence and email tables were inspected against the
  earlier LTR captures: standard light-blue headers, wrapping, borders and
  contained horizontal scrolling agree. `lang=ar`, `dir=rtl` and computed RTL
  direction were verified, with no page-level horizontal overflow. No browser
  console errors or warnings were observed.
- Existing Arabic draft wording was made renderable only in the new disposable
  database using the existing publication endpoint. The checked-in artifact hash
  is unchanged; this is a layout/interaction check, not human translation
  approval. This run used synthetic isolated SMTP, with no external sends or
  added MailDev messages. Earlier real SMTP/MailDev evidence remains applicable.
- The new database was dropped and independently confirmed absent, both owned
  ports closed and the temporary preview directory removed. The application tab
  was closed and the viewport reset. An initial connection-error tab could not
  be closed under browser URL policy; it remains unmarked for automatic cleanup.

Both catalogues contain 3,737 aligned active keys. All 3,712 previous Arabic
items preserve their exact text and provenance. Twenty-five new contextual UI
and audit keys have generated Arabic drafts requiring human review. No
administrator export was replaced and no translations were published to a
persistent database. Exact
coverage, source references, ordering, placeholders, nonblank text, new-key
terminology/provenance and catalogue hashes were checked.

## Deployment and boundary

1. Apply migration 069 after 068 to an existing database; initialize a new empty
   database from `database/schema.sql` alone. No persistent database was tested
   or migrated during this work.
2. Deploy/restart API, WebUI and the dedicated destruction worker. Its existing
   bounded CLI now performs certificate work after digital units and requires
   migration 069. It does no work while the canonical release gate is closed.
3. Reconcile the optional `disposition.completion_outcome` producer through the
   existing notification seed, then review/configure/activate its templates and
   audience in Notification Administration. Activation is never implicit.
4. Review/import/publish the 25 new Arabic drafts through the established
   Translation Administration workflow.
5. Phase 22 verification is complete. Full workflow/release acceptance remains
   Phase 23; the operational destruction gates remain closed.

No environment variables or templates changed; all 36 API settings pass template
reconciliation. Private environment values and SMTP/encryption configuration
were preserved. Disposable databases and owned servers were cleaned up; the
cleanup report records independent absence checks. Two own synthetic MailDev
captures are intentionally retained. No commit, staging or push was performed.

The Phase 22 start boundary was not retained across context compaction, so
active hours are incomplete and are not reported as measured.

Live Arabic completion evidence is recorded in `browser-checks.json` and the
`live-arabic-*.json` files. No implementation or translation artifact changes
were needed for this final browser verification.
