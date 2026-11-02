# Certificate email in Current Task — 2 November 2026

Approved requirement: destruction §16 / DEST-36, revision 1.15. The Records
Manager can deliberately send the saved digital certificate from **Current
Task** before completing the final task, while the same send action and full
history remain in **Evidence and documents**. Sending remains optional and
available after completion; completion does not send mail.

## Implementation and freshness

- `completion.controls` shows recipient, localized optional-send guidance,
  **Send by email** beside the existing certificate download action, and the
  latest attempt above the separate **Complete this task** action. The email
  document must match the saved certificate and have current server-projected
  send authority. The full history stays in documents.
- `email._sender` is mounted-form state keyed by exact document ID, scoped to
  that page's identity/job/language. Both copies share busy state, button
  disabling and the UUID for an uncertain submission. An acknowledged later
  click obtains a new UUID. No new result cache is added; leaving the page
  discards this state and suppresses late UI updates.
- The authorized email workspace projection includes the latest attempt's ID,
  status, requested/completed timestamps and actual recipient. No second
  initial browser request is introduced. The existing history endpoint accepts
  optional positive `document_id`; summary refreshes use server pagination
  with `limit=1`. Normal job/document visibility filters still apply.
- Tab entry and acknowledged sends refresh the summary. One timer per document
  polls visible pending attempts, guards overlapping reads, stops at terminal
  outcomes, and deactivates on abandonment/error. Hidden sections perform no
  summary requests. Tab-entry document/history/summary reads run concurrently.
  Open history tables retain their existing active-state guards and pagination.
- SMTP acceptance is labelled as such and never presented as confirmed inbox
  delivery. Current configured recipient and latest attempt recipient are
  displayed separately, so a later configuration change cannot misattribute
  an older attempt.

## Verification

**255 frontend checks passed** across email, completion and task modules,
including English/Arabic, both send locations, shared uncertain retry identity,
deliberate resends, cross-button busy guards, no eager summary read, visibility,
abandonment, current authority and explicit completion without sending or
downloading.

**33 API checks passed** across certificate email and communications modules.
They verify a saved certificate while the job remains active, Manager-only
authority, filtered and bounded document history, latest projection, exact
retry, synthetic SMTP acceptance, unchanged job/evidence and repeat sending
after explicit final completion. An older test was corrected to explicitly
complete the final task instead of expecting generation to complete the job.
Every database run used a new canonical disposable PostgreSQL database and
dropped it cleanly, including the initial run that exposed that stale assertion.
No real email was sent for verification.

Live in-app-browser verification rendered the actual NiceGUI components and
Wathiq CSS against an isolated synthetic API. Sending in Current Task moved
from Sending to Accepted by SMTP server; the documents tab showed the same
attempt and its existing standard light-blue history table. English and Arabic
directions were verified from rendered DOM styles. At a 390px card width,
actions wrap cleanly: English buttons measure approximately 311px/154px;
Arabic buttons 228px/199px. There was no horizontal overflow. The preview tab
and owned preview server are closed after verification.

- [English task controls](certificate-task-email/english.png)
- [Arabic task controls](certificate-task-email/arabic.png)
- [English narrow controls](certificate-task-email/english-narrow.png)
- [Arabic narrow controls](certificate-task-email/arabic-narrow.png)
- [Retained documents history](certificate-task-email/documents.png)

## Catalogue and local application

Three keys were added: `disposition.ui.certificate_email_hint`,
`disposition.ui.email_latest_attempt`, `disposition.ui.email_not_sent`.
English and the canonical maintained Arabic artifact contain 3,974 active keys
in identical lexicographic order. All previous item wording and provenance
were preserved; no administrator export was promoted. The three new Arabic
values are generated, unreviewed drafts. Exact coverage, blanks, named
placeholders, markup, new-draft Latin-token checks, catalogue hash, stale-key
references and approved terminology checks pass. Terminology verification
covers 928 contextual uses of the 35 approved mappings.

The managed local stack restarted successfully. Its official missing-only
startup seed stored three drafts, protected 3,971 existing translations and
reported zero failures, corrections or awaiting-generation entries. Drafts
remain unpublished for administrator review. No migration, privilege or
environment change is required. The traceability ledger updates §16/DEST-36
and retains the older unrelated baseline-check findings documented by the
preceding report-template change.
