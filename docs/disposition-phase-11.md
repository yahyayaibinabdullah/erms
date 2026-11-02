# Disposition Phase 11 implementation and verification

Phase 11 implements current artifact destinations, governed document storage,
authorized preview, and append-only corrections. Initial uploads remain private
service operations for their action-specific workflow; there is no unrestricted
HTTP upload that can manufacture an external approval or physical confirmation.
Controlled Word templates and document generation remain Phase 12 work.

## Requirement traceability

| Approved contract | Implementation and verification |
| --- | --- |
| Destruction §§17.2, 18.12; ACFG-14/15; ADMIN §§3/5 | `disposition/artifacts.py`, `disposition_private.artifact_destination`, existing Governance Custody warnings. Resolve current grouped settings, terminal classification and latest open root by opening date then larger ID. The destination is rechecked under settings/classification/root locks at save. Closed roots, children and another classification cannot substitute. Missing destinations block saving; warnings clear on a fresh read. Root ordering, missing/recreated roots, grouped-settings and closure races pass. |
| Changed destinations and earlier records | Capture scheme/classification/root on each document. Compare against earlier artifacts in the applicable evidence/report category; warn even when an older differing destination exists behind a more recent matching one. Show only authorized destination details. An advisory fingerprint detects a destination that changes after preview; the user refreshes and sees the new warning before saving. Previously stored records are never relocated. |
| Shared disposition §17.7; DISP-41; destruction DEST-14/15/16/33 | Private `register`/`save` services create a governed record, component, verified PostgreSQL content set, immutable document link and history in one domain transaction. Reports use the report classification; the generated digital certificate uses evidence classification. Original registration and correction receipts bind bytes/checksum, filename, MIME type, destination preview, actor/role, version, reason and applicable provenance. Byte changes under the same retry ID are rejected. Separate action commands can share the caller's outer transaction, so an outcome failure also rolls back its artifact. Final-action generation/completion remains with its later phases. |
| Destruction §6.4.1; DEST-32 | Purpose-built correction API checks the exact assigned Officer or authorized Manager role and current job/record/component permissions. A correction inserts a new version/record/component; the earlier available document is immutable, and decisions/job fields remain unchanged. No workflow-stage-specific correction restriction is added. A later external-approval-stage fixture proves Manager correction by another person; an unassigned Officer role, expired role, non-management recipient and generated-document correction are rejected. |
| Preview, history and redaction | Bounded document pages return only authorized records/components, with current/earlier version state and preview/download capabilities. Current or historical task recipients can preview without acquiring management authority. Existing component preview/download handlers enforce the ordinary permissions. The job history includes document events through `authorized_event_history`; correction events are redacted if either the current or preceding record becomes inaccessible. Three shared readable event labels also apply to existing stored operation codes. |
| Evidence outside destruction units | Deferred SQL checks reject admitting or moving a job's evidence inside that job's active/completed disposition unit. Ordinary content replacement, deletion and segment/set mutation cannot erase linked available evidence. Original bytes, record links, provenance, history and original confirmation facts are never overwritten by correction. Later action-specific confirmation tables retain their own phase ownership. |
| Segmented PostgreSQL storage §§4–9/11/12/15 | `stage_governed_upload` reuses ownerless, unplaced internal drafts, which personal draft access rules conceal. It hashes/measures the spooled input and commits bounded segments before workflow/destination locks. Existing `promote_draft` copies verified segments in the domain transaction without joining the file in memory. Configured upload size, segment size/checksums and session lifetime apply. Normal exit/failure deletes staging; interrupted processes use existing session/draft expiry cleanup. Content bytes never enter audit metadata. |

`backend/services/api/tests/test_disposition_artifacts.py` contains 21 focused
acceptance cases. The ledger records scoped Phase 11 evidence against every
owning source section and ID, while retaining later phase ownership for actual
review decisions, external outcomes, physical confirmation and final destruction.

## UI and live verification

The document panel reuses the existing Wathiq `PageTable`, native NiceGUI Upload,
Select, Textarea, Dialog and layout controls, and the existing governed component
viewer. No CSS fallback, new privilege, runtime cache, environment setting or
startup asset was introduced. Four useful document columns sort on the server;
25-row pages and independent destination reads are bounded and concurrent.
Guarded callbacks discard abandoned/obsolete responses. A retry retains the
exact command ID, reason and file; inputs cannot change while saving. Closing
the dialog during a request retains the spool until the request finishes.

Live verification used isolated cookies/storage and only a newly created
disposable PostgreSQL database. The fixture contains 29 original document links,
an English Records Manager and an assigned Arabic Officer. Checks covered:

- real PDF preview in the established viewer;
- standard light-blue headers (`rgb(238, 247, 253)`), `7px 16px` padding,
  matched borders/actions and 982px contained desktop tables;
- page two returning rows 26–29, genuine limit/offset requests, server sorting,
  repeat navigation and fresh data after mutation;
- changed-destination warning with earlier record destinations retained;
- a real file-chooser upload, missing-reason persistent alert/toast and focus,
  successful positive toast and automatic workspace reload;
- current version 3 and preserved version 2/1, with correction controls only on
  the current uploaded version; generated reports have no correction action;
- readable, attributed correction history and current-entity record links;
- Arabic RTL document direction, right-aligned headers and native dialog fields,
  mirrored shell/actions, localized working-timezone timestamps; and
- a 390px English viewport whose document width remains 390px with table
  overflow contained within its standard component.

The initial automated upload used a different Chrome profile than the one whose
file permission the user enabled. Selecting the user's correct profile resolved
the issue; the real upload/save check subsequently passed. No browser permission
was changed by the implementation. New Arabic wording remains an unpublished
English fallback in the preview, rather than bypassing translation review.

## Verification results

- Final focused artifact acceptance: **21 cases passed** (19-case run plus two
  subsequent generated-destination/stale-HTTP cases). A final scoped staging
  check also passed after adding configured session expiry.
- Affected history reader and complete localization catalogue: **29 passed**.
- Focused frontend screens, native uploader/retry/feedback, API client, audit
  labels and locale services: **93 passed**.
- Existing foundation compatibility: 97 cases passed in the initial combined
  run; its three document fixtures were then updated for real content and new
  provenance and all three passed on the 056 upgrade path. The failed initial
  combined run is not reported as a full passing suite.
- Committed-schema → 056 upgrade acceptance: **17 passed** before the later
  scoped refinements; final independent catalogue parity/preservation probe
  passed for canonical and migration-created databases, preserving an existing
  evidence file, document/record/component links, receipts, jobs, settings and
  every earlier immutable event. It invents no historical uploader role.
- Baseline contract tests: **24 passed**. Catalogue discovery, lexical ordering,
  active-key coverage, nonblank/placeholder/terminology/provenance/hash checks,
  compilation, environment-template reconciliation and whitespace checks pass.

Early iterations caught SQL syntax, draft-medium, child-classification/rule and
fixture-role mistakes. Each failed run cleaned up its disposable database before
retry. Detailed run/database evidence is in the Phase 11 verification directory
and requirement ledger.

## Translation and deployment handoff

The English manifest and canonical Arabic artifact gain **37 keys**: 34
artifact/destination/correction UI keys and three audit-event labels. Both have
**3,374 active keys** in identical lexical order. All **3,337** starting Arabic
items retain their exact wording and provenance. New entries are generated
**drafts with human-review flags**. No administrator export was promoted and no
existing flags were cleared. Use the existing explicit seed, human review and
publication workflow; no persistent translation seed, review, publication or
migration command was run.

Apply `database/migrations/056_disposition_artifacts.sql` before deploying/reloading
the API and WebUI together on an existing database already at 055. A new empty
database still uses `database/schema.sql` alone, with seeds kept separate. The
upgrade reconstructs only recoverable legacy destination references and marks
that provenance explicitly. This turn did not migrate demo or another persistent
database. There are no environment-template changes or new deployment settings.

Phase 12 is next: controlled Word templates, their governed revisions, and PDF
generation. Phase 11 does not enable destruction execution.

All 21 disposable database names were independently confirmed absent after
cleanup. Owned preview servers, temporary cookies/logs and created browser tabs
were removed; the viewport was reset. See `cleanup.json`.

Measured active time: **0.99 hours**; elapsed time: **1.36 hours**.
The measured 1,305.0144-second stalled browser upload call is excluded from active
time; its profile mismatch was resolved and the real upload check passed.
