# Phase 20 — Termination and partial disposition recovery

Phase 20 implements termination after irreversible physical outcomes and explicit
individual or atomic bulk recovery of status 13. Operational physical/digital
execution and final job completion retain their closed release boundaries and
their later phase owners. No persistent database was migrated, no translation
was published, and no commit was created.

## Requirement → implementation → verification

| Approved contract | Implementation | Evidence |
| --- | --- | --- |
| Disposition §10.3; DISP-21/22 | Existing IGU `disposition.jobs.manage` authority, confirmation, reason and current job version govern termination at every active stage. Whole units with confirmed physical work and unfinished digital material become 13; untouched units return to matching eligibility. Proven physical-only outcomes become 10 using the actual confirming Manager, original confirmation time, external number and permanent outcome event. Already final units retain their exact fields. | Mixed four-unit termination, existing-final preservation, complete descendant status and final-field assertions in `test_disposition_recovery.py`; previous pre-execution/membership regressions. |
| Disposition §10.3/14.3; destruction §14.2; DEST-13 | Immutable physical scope survives termination, correction and later admission. Post-physical reopen, rule/structural corrections, ordinary membership removal and workflow rewinds cannot undo physical work. Holds remain in force; termination and eligible-status recovery change bookkeeping and preserve all content. Resumable technical and certificate-only failures do not automatically terminate a job. | Post-physical correction rejection, current-hold termination/recovery followed by blocked readmission, immutable confirmation and byte-for-byte blob preservation; direct component/blob deletion, reopening and command-bypass rejection. |
| Disposition §10.4.1; DISP-22 | Individual resolution requires an explicit eligible status 2–5, a nonblank reason, a current root version and current IGU/full-unit access. Root and every descendant change together. Original terminated membership stays unchanged; matching new jobs use ordinary admission checks. | Four selected-status/new-job cases, wrong-job-type rejection, current hold and hidden-scope cases, single-unit form and live RTL recovery. |
| Disposition §10.4.2; DISP-23 | A lazy bounded-response preview supplies affected root count and a scope/version token. Bulk resolution requires explicit status, count confirmation and one shared reason, and changes every current status-13 unit in that terminated job. Current/latest terminated membership prevents an older job from resolving a later partial outcome. One command owns all resource changes and events. | Late failure in the second unit rolls back every unit and event; stale count/token, missing confirmation/reason, final/eligible exclusion, concurrent winners and exact retries; live count 3 → individual recovery → count 2. |
| Disposition §10.4/16; DEST-16 | Permanent job/root events retain actual actor/time/reason, old/new statuses, terminated job, shared command UUID, original physical evidence and preserved component/content-set IDs. They contain no content bytes. Root recovery-event projection checks the complete unit and governed evidence, preserving ordinary redacted event envelopes. | Linked-event assertions, absence of content in audit metadata and root-visible/child-hidden audit redaction; readable English/Arabic operation labels and retained history. |
| Disposition §14 and ordinary admission | Termination snapshots the exact existing relationship IDs. Retained former-job links to a status-10 unit do not block a later unit; links to live units and newly created links retain normal blocking rules. Existing physical confirmation scope excludes already destroyed material from later physical routing and preparation reports, without rewriting its medium/history. | Retained versus new/live links, new matching job routing directly to digital work, frozen confirmation and report/count regressions. |
| WebUI design, performance and translation contracts | Native NiceGUI dialogs/selects/checkboxes, existing Wathiq server-paginated member/history tables, no implicit status selection, warning/error/success toasts, retained retry inputs and abandonment guards. Recovery projection shares the existing workspace response; preview is requested only when bulk recovery is opened. No new cache. | English/Arabic component checks, Gmail-profile Chrome LTR/RTL checks, repeated navigation, fresh scope after mutation, server sorting, standard light-blue table headers and no page/main/dialog horizontal overflow. |

The no-irreversible-work behavior for a previously reopened/recalculated member
is preserved: its current recalculated state is retained when termination clears
its active membership. Recovery does not bypass vital, security, hold, due-date
or matching-job-type checks on subsequent admission.

## Verification

Final logs, screenshots and structured checks are in
`docs/verification/disposition-phase-20/`. Overlapping runs are not added as unique
test totals. The acceptance tests temporarily enable confirmation only inside
owned disposable fixture databases; the canonical release function remains false.

- Canonical Phase 20 acceptance: **21 passed**.
- Final upgraded foundation/recovery/membership/workspace regression: **139 passed**.
- Focused ordinary-write, historical-final-outcome and status-13 safeguards:
  **15 passed**.
- English/Arabic forms, tasks and audit labels: **50 passed**.
- Fresh/065-upgraded catalogue parity, changed hold guard/private privileges and
  every field of every pre-existing public/private row: **passed**.
- Preserved all **3,641** previous Arabic items exactly; added **24** contextual
  keys, resulting in **3,665** aligned active keys. Placeholder, blank,
  terminology, ordering, stale-key, provenance and catalogue-hash checks passed.
  New Arabic drafts require human review/publication. Live Arabic therefore uses
  the approved English fallback for unpublished keys; component tests exercise
  the Arabic draft wording too. No administrator export was replaced.

The older number-constraint test fixture now supplies the private external scope
introduced in Phase 17. Production external-approval/evidence guards were not
weakened. Historical final-outcome fixtures continue to exercise their existing
consistency guards independently of Phase 20 recovery scope.

`cleanup.json` records independent absence checks for every database created by
these runs, preview port shutdown and owned browser-tab cleanup.

## Deployment

Apply `database/migrations/065_disposition_recovery.sql` after 064 and every pending
predecessor. New empty databases use `database/schema.sql` alone. Restart API and
WebUI. Seed the new catalogue definitions/drafts through the existing translation
workflow, then review/publish approved translations. No environment variables or
templates changed; all 36 API settings still pass template reconciliation.

Phase 21 owns durable digital execution, content/derivative removal and retained
disposition records. Phase 22 owns final job completion and release verification.
Keep the operational release boundary closed until those requirements pass.
