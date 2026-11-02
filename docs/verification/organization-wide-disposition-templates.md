# Organization-wide disposition template management

Approved change: move shared template administration out of Job details into
Disposition → Document templates. Contract: destruction-process.md §§6.4,17.4.

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Management without a job; unchanged Officer/Manager authorization | Global template routes; principal template capability; standalone screen | API shared endpoint, no-job catalogue, denied acting-role and UI navigation tests |
| Immutable shared revisions, stale-write protection and retry | Existing revision command, nullable source job; migration 081 | Shared upload/retry/history/old-download test; existing concurrent revision tests |
| Preserve existing job-associated revisions and audit history | Migration changes guards and nullability only; no row rewrite | HEAD schema plus migration 081 disposable run; legacy revision still downloadable and associated with original job |
| Job documents identify/download exact saved revision | Document page joins saved reference, authorized exact-reference download | Generated artifact regression and English/Arabic browser fixture |
| No template-management tab in job/task details | Removed templates section and lazy loader | Job/task distinct-focus test |
| English/Arabic, bounded history and safe abandoned reads | Existing PageTable and active guards; localized role/uploader names | UI template regressions; Arabic API localization test; in-app browser LTR/RTL inspection |

Browser verification used real NiceGUI components with deterministic fixture data,
not persistent database writes. Template history and document tables were compared
with Wathiq's existing light-blue-header PageTable styling. Both language views
show the shared-scope explanation, revision history and exact document revision.

The English catalogue adds `disposition.ui.template_revision`; the Arabic artifact
adds its review draft. Existing translations/provenance remain unchanged. No
administrator export was replaced or promoted, and no translations were published.

Deployment: apply migration 081 after 080 to existing databases and restart API
and WebUI. This implementation does not apply migrations to demo.

Verification results (23 October 2026): 104 focused WebUI tests passed; 55 API
and document regressions passed on the latest canonical schema (six unrelated
renderer/font stress cases deselected); six focused migration/API checks passed
on HEAD schema upgraded with 081. All disposable databases were dropped.
Catalogue reference checks, active-key order/coverage/hash, new Arabic draft
validation and preservation of all pre-existing Arabic entries passed. Python
compilation, API environment-template synchronization and diff whitespace passed.
