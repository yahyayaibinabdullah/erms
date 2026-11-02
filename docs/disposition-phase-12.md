# Disposition Phase 12 implementation and verification

Phase 12 implements four controlled Word templates, organization-wide retained
revisions, job workspace download/upload/history controls and private PDF
generation from a complete action-owned snapshot. Approval, execution,
physical-task routing and finalization triggers remain with their later phases.
There is no public operation that can manufacture an arbitrary approval,
certificate or destruction outcome.

## Implementation and traceability

| Approved requirement | Implementation and evidence |
| --- | --- |
| Destruction §17.4 / DEST-39 | Four editable DOCX defaults and placeholder README in `templates/disposition/destruction/`. Arabic-first titles, RTL Arabic paragraphs/tables, LTR English/data, Changa throughout, no signatures/seals. Deterministic builds and an immutable version/checksum manifest. |
| Required request fields, §§11.2–11.3 | `template_contract.py` declares every scalar and grouped field. `document_snapshots.py` captures actual job/membership facts, groups by terminal classification/effective retention values, distinguishes local overrides and differing values, counts complete units, and retains the exact source snapshot/checksum. Approval services provide their real review summaries/round and approved form version. |
| Execution/certificate/preparation fields, §§10.1, 14.1, 16 | Required template contracts cover original proposers, executing Manager/role, reason/source, execution results/removals/history; approved external number/request reference, completion/scope/counts/physical confirmation/integrity; and every physical/mixed aggregation below any medium parent, inherited locations, descendant counts and non-overlapping group/report totals. Later action services supply their authentic execution/completion facts. No external number is invented. |
| Validation | `template_engine.py` checks actual OOXML, package expansion, complete scalar/repeating-row structure, split Word runs, bilingual content, Changa and explicit/inherited paragraph/table direction. Rejects unsafe external references, active objects/macros, tracked changes and unsupported field instructions. Replacements preserve surrounding Word formatting; empty repeats disappear and no application placeholders remain. |
| Revision authorization/history | `documents.py`, the purpose-built API and migration 057 require a current effective Officer/Manager role with existing job access. An administrator profile alone and File Administrator/Unit Manager acting roles cannot revise. Every upload retains exact bytes/checksum/name/type/version, user/acting role/user actor type/time/source job. SQL prevents overwrite/deletion and protects inserts. Global command serialization plus expected revision prevents lost uploads; accepted uploads immediately apply across jobs. |
| PDF generation/provenance, DISP-41 / DEST-16 | The private generator selects a valid current revision, fills a server-owned snapshot, renders that Word layout, and checks every PDF font for embedded Changa. Reuses the existing LibreOffice executable, timeout/rendition settings and Phase 11 governed segmented storage. Save retains exact revision/checksum/filename, full snapshot/checksum, render metadata and retry key. Conversion/staging precede workflow locks. Caller-owned transactions preserve action/artifact rollback. Committed retries return the earlier PDF even after revision changes; a later generation uses the new revision and preserves earlier bytes. |
| Browser/UI contracts | Native NiceGUI dialogs/upload/select/textarea/buttons and standard Wathiq PageTable. Four finite current-template rows; growing revision history uses server sorting/pagination, metadata-only listing, guarded abandoned responses, no authorization/history cache. Save requires a reason, has warning/success toasts and reloads job/template/history data. The immutable default-asset cache is process-scoped by four fixed types, invalidated on deployment/restart, caches no failures or identity/locale data, and never includes uploads. |

## Verification

- **36 focused template acceptance cases**: the final 34-case suite plus two
  concurrency cases; the expanded generation-after-revision case also passes.
  Four real Word-to-PDF conversions cover all types. Checks include malformed
  files, missing fields/repeats, split runs, style inheritance, font substitution,
  Officer/Manager/reviewer authorization, SQL immutability, HTTP download/upload,
  exact retry, concurrency, preserved earlier PDFs and outer rollback.
- **21 existing governed-artifact cases** passed with the template implementation;
  **18 complete localization catalogue cases** passed. These were separate
  disposable runs, not an assertion that the entire API suite was run.
- **77 focused frontend/client cases** passed after final UI changes, including
  native upload/retry/feedback, abandoned responses and standard history controls.
- Canonical schema versus **057 upgrade parity** passed in two disposable
  databases, preserving all previous evidence bytes, links, provenance, job
  resources, receipts, settings and immutable audit rows. Defaults are packaged
  files; no migration executes a seed. The prior 056 probe is bounded to its
  own schema section so later DDL does not invalidate that earlier comparison.
- Representative PDF review inspected **nine pages**: request 2, certificate 1,
  execution report 3, preparation report 3. Every page was rendered to PNG and
  inspected; Changa embedding was independently checked with Poppler. Long
  mixed-script titles/checksums wrap, bilingual headers repeat, and rows and
  headings remain together without clipping or unresolved placeholders.
- Live Chrome checks covered English and Arabic roles/direction, template
  controls, server pagination, exact retained DOCX download, a real native
  revision upload, warning/success toasts, and the governed two-page PDF viewer.
  The observed 560px dialog cap was fixed with native `full-width`; standard
  checksum word wrapping contains all columns. See `browser.json` for the
  exact scope and final callback/mobile limitations.

Early iterations caught a role-expiry fixture date constraint, the preview's
closed test-client pool, substituted fonts and page-break/dialog-width issues.
They were corrected; failed runs also dropped their disposable databases. No
persistent database was used for testing or preview.

## Deployment and translation handoff

Apply `database/migrations/057_disposition_templates.sql` after 056 before
restarting the API/WebUI. Install the updated API requirements (`pypdf` is now
explicit), package all four DOCX files, their README/manifest, and the merged
licensed `messaging/pdf_assets/disposition/Changa.ttf`. Existing
`LIBREOFFICE_BINARY` configuration/discovery is reused. Fontconfig uses a private
child configuration/cache; native font backends may require installing the
packaged Changa face for the API account. Font substitution fails generation.
No new environment variable or template change is needed; environment-template
reconciliation passes. No migration was applied to demo or another persistent
ERMS database, and no commit was created.

English and canonical Arabic gain **24 keys** (23 template UI messages and one
readable audit-event label), reaching **3,398 active keys** in identical lexical
order. All **3,374 starting Arabic items preserve exact wording/provenance**.
New Arabic entries remain generated flagged drafts for human review and explicit
publication. No administrator export was promoted and no existing review flag
was cleared. Coverage, placeholders, blanks, terminology, stale keys, provenance
and artifact hash checks pass. The terminology checker now recognizes the named
Changa font and DOCX format; this does not publish or waive review of drafts.

Verification logs and rendering, browser, localization and cleanup records are
under `docs/verification/disposition-phase-12/`. Phase 13 is next.
