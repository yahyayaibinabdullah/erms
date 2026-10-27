# Records Manager request delivery

Approved requirement: destruction-process §11.1/11.4 and DEST-35. After proposal
approval, the Records Manager checks the execution report and generated request
in Evidence and documents rather than being returned immediately to My Tasks.
The Manager can send the current request without claiming the Officer’s task;
the assigned Records Officer can also send/resend it if delivery is uncertain.
This does not transfer responsibility for recording the external decision.

Implementation: canonical SQL and migration 087 extend `can_email` for current
Records Manager roles while retaining person/role, content, clearance, document
view/download, current approved round/request and open external-task checks.
The API controls and SMTP worker both use this same predicate. Each deliberate
click creates an attributed attempt; exact retries reuse the original attempt.
No approval, migration or page navigation automatically sends mail. Digital
certificate permissions and other workflow routing are unchanged.

The UI reuses the standard document table, preview/download, Send by email and
lazy history controls. Approval success and committed generation failures route
to this view; pending generation retains existing recovery controls. Other
stage completions retain their My Tasks return. New guidance has an English
catalogue definition and generated Arabic draft, preserving all other wording
and provenance. No cache or environment setting was added.

Verification: disposable communications/external workflow suite covers three
routes, Manager/Officer sends, repeat attempts, exact retry, revoked roles,
worker reauthorization, document versions, SMTP failures/unknown outcomes and
external-stage transitions. NiceGUI tests exercise English/Arabic approval
success and committed pending generation with document-results navigation.

26 October verification evidence: 59 communications/external API cases passed
using disposable database `erms_messaging_test_acl_adfd12517a4a44168cf73eb5269ed584`,
which was dropped cleanly. All 250 task/screen UI cases passed in English/Arabic.
Catalogue references, Arabic terminology and API environment-template checks
passed. Live isolated NiceGUI previews used the production job/document/email
components in English and Arabic, confirming the selected documents tab,
collapsed job summary, standard table, download actions and Send by email.
No actual authority mail was sent during verification. Migration 087 was
applied to demo without creating any email attempts; Arabic missing-only seed
preserved 3,912 translations and added one unpublished draft.

27 October email-history placement correction: task pages have no visible
History tab, so the former Email attempts expansion there was unreachable.
The shared email controls now mount that expansion directly under Send by email
in Evidence and documents on both task and job pages, including read-only
workspaces. Expansion loads 25 rows from the existing authorized endpoint;
reopening, Refresh, returning to the documents tab with history expanded, and
an acknowledged send refresh the retained table. Hidden or abandoned views do
not fetch/render history. No new cache, authorization or email retry is added.
The duplicate request title/filename block is suppressed when it has no action
or status to communicate; generation failure and renewed-review recovery remain.

Verification: 241 existing/new frontend email, external, completion and task
cases passed, followed by the focused recovery-control regression. An isolated
NiceGUI browser preview used production job/task/document/email components with
mock data in English and Arabic. It confirmed placement below Send by email,
standard light-blue paginated table styling and localized status/error labels.
No actual email was sent. Catalogue references remain complete; this correction
adds/changes/removes zero translation keys and does not replace language
artifacts or promote an administrator export.


27 October request-email correspondence: `disposition.email.request_body`
uses the configured authority/organization names, approving round's Manager
and that acting role's organization unit. Entity names use translated values
with canonical fallback. Arabic-first bilingual emits Arabic then English;
User's preferred language resolves the initiating sender, never the worker.
The Arabic letter closes with «وتفضلوا بقبول فائق الاحترام والتقدير،».
The immutable per-attempt configuration captures body text before enqueue;
exact retries preserve it even if settings, names or preferences later change.
Previously queued attempts without body text build it using their initiating
user identity. The saved PDF attachment and transport authorization are
unchanged. Certificate emails have an empty body rather than incorrect request
wording. No schema, environment or WebUI translation-key change is needed.

Communications verification: the existing 28 cases passed in disposable database
`erms_messaging_test_acl_44cd4a6743994577b15dddbbda26eaa7`; the three new
language/signature cases initially exposed a test-fixture rename that correctly
invalidated the approved request. After retaining canonical approved names and
adding only Arabic translations, all three passed in
`erms_messaging_test_acl_bce22fc81b974fb8b81f75db5cf04842`. Both databases were
dropped cleanly. Tests used a synthetic transport; no email was sent to MailDev
or an external authority. Python compilation and whitespace checks passed.


27 October follow-up: suppress the request-controls block after an external
approval/rejection has been received when no recovery action/error remains.
The previous visibility guard treated a received decision as a reason to show
an otherwise empty request heading plus a success-notification sentence.
Received decisions remain in the decision history and letters in the document
list. The success toast remains at the time of saving; generation/renew-review
controls and unresolved approval warnings remain available. English/Arabic
regressions cover both decisions with current and invalidated approvals.
No translation key or wording changes.
All 24 external-request UI cases passed, including English and Arabic.
Whitespace checks passed; no database-backed tests or email sends were needed.

27 October certificate completion guidance: Current task now renders automatic
completion progress while the stage is still Digital destruction. Header text
uses `digital_completion_processing` or `digital_completion_failed` according
to completion-work state. The redundant destruction-progress paragraph was
removed. The existing authorized Retry certificate generation and storage
control is now reachable in this stage; queued/running work polls for completion
and exposes no destruction action. API permissions and retry semantics remain
unchanged. Specs §16 records the distinction and the retry location.

235 frontend task/completion/destruction cases passed, including both languages
and queued/running/failed completion states. Two focused API cases passed in
`erms_messaging_test_acl_f52ae2f5ca704056ae3ce710a3c889a7`, then the database was
dropped: a certificate failure offers certificate retry and excludes destruction,
certificate recovery saves only one certificate without another destruction run,
and a partially failed destruction retry skips previously successful units.
Isolated production-component previews confirmed English and Arabic failure and
Arabic processing messages and the certificate-only button. No actual destruction,
certificate retry or email was triggered against demo during verification.
Two new catalogue keys have generated Arabic drafts; all existing wording and
provenance remain unchanged. Catalogue references and approved terminology pass.
