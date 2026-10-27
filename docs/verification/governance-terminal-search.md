# Retained identification and disposition-status search

Approved contract: disposition §14.2, advanced-search disposition-status metadata
search and destruction-process DEST-49. Preserve numbers and titles in the
original read-only destroyed aggregation/record rows. Content, descriptions and
recoverable storage references remain erased. Permanent disposition proof is
separate and unchanged. Migration 089 applies prospectively; it does not
reconstruct previously erased identification or rewrite issued certificates.

The existing status field is available in Advanced Search to authorized
information-governance users. Controlled statuses include Destroyed (10),
Permanently transferred (11) and Retained as local archives (12). No new flag or
status is introduced. Destroyed rows require an explicit disposition-status
criterion, current governance authority, clearance and retained access. Search
views exclude all three terminal statuses from non-governance results/counts,
including forged or previously saved predicates. Unauthorized saved criteria
remain restricted rather than silently becoming title conditions. Indexing
freshness indications use the same terminal visibility boundary.

Opening a destroyed search result retrieves the existing authorized retained
detail endpoint. The read-only presentation shows identification, job,
classification, owning unit, security, retention and destruction facts with
localized labels. It provides no live editor or destroyed content action.
Ordinary live endpoints continue rejecting destroyed resources. No content/OCR
index is reconstructed. No cache, privilege, environment variable or UI message
key was added; existing English/Arabic labels are reused.

Verification on 27 October 2026:

- Canonical schema: 32 destruction and terminal-search tests passed, including
  actual erasure, preserved titles/numbers, ordinary endpoint denial, both
  resource types, terminal status authorization and failure/retry behavior.
- Upgrade from HEAD through migrations 087–089: final six terminal-search
  cases passed, including absence of inherited physical storage references on
  destroyed search rows. A prior upgrade run also passed.
- Existing full-text/global search and freshness suites: 13 tests passed.
- Advanced Search builder and destruction UI suites: 42 tests passed.
- Every database-backed run used a uniquely named disposable database and
  reported successful deletion. No suite used demo.
- Live NiceGUI preview checked governance status selection, absence of the
  field for non-governance users, and readable retained details in English and
  Arabic. Native grid layout mirrored correctly in RTL; no CSS fallback or new
  table was needed. The temporary preview process/tab were closed afterward.
- Catalogue references, Arabic terminology, Python compilation, environment
  template synchronization and whitespace checks passed. Existing translation
  provenance is preserved; this change introduces no translation drafts.

Migration 089 was applied to the authorized local demo database, followed by a
successful managed stack restart. Deployments must apply it before restarting
services; no operator environment setting is required.

The two-page DT-2026-1 digital destruction certificate preview was rendered
using demo presentation settings and visually checked. Its root listing uses
permanent proof for classification/count/location applicability and preserved
identification where available. Old erased titles, numbers and originated years
show Not specified. The preview is filesystem-only; it does not replace the
issued document, replay destruction, save a governed record or send email.
