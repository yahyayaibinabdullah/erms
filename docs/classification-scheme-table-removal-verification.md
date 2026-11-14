# Removal of the obsolete classification-scheme table

**Status: removed and locally verified on 12 November 2026.**

## Authorized change

The user explicitly requested removal of the old page name and the associated
classification-scheme table code. The obsolete destination is removed, with no
compatibility alias or redirect. Work remains local and uncommitted on the
user's existing branch.

The string `classification-schemes` remains an active **data-resource identifier**
for API requests, editor fields, relationship lookups and menu identity. These
uses do not select the removed table. The normal menu still opens the current
`classification-workspace`; scheme and classification detail destinations remain
`classification-scheme-details` and `classification-details`.

## Removed and retained

Removed:

- The old page's breadcrumb label and heading-icon registration.
- Its table-column definition, localized-row branch, action markup/bindings,
  publish/lifecycle helpers, refresh callback and collection-sort special case.
- The `legacy-schemes` browser scope, fixture route and legacy-table tests.
- Four contextual messages referenced only by the removed helpers, from both
  English and the canonical Arabic artifact.

Entity definitions still supply the current editor. `COLLECTION_ENTITIES`
contains only definitions with collection columns; restoration, loading,
navigation and rendering use this boundary. The old scheme resource cannot
accidentally become a generic table merely because its editor definition exists.

The current classification controller/workspace, API endpoints, editor fields,
selectors, transfer functionality and navigation handlers remain in place.
Other collection pages are unchanged. Shared generic-table code remains for its
other consumers; this is not a whole-table-framework removal.

An explicitly supplied obsolete page entry now follows existing unsupported
navigation handling (404). It does not open the old table or redirect to the
workspace. No actual user storage or persistent navigation was examined or
modified; the earlier browser fixture deliberately synthesized such entries.

## Translation maintenance

Source-reference discovery confirms that all four retired keys have no remaining
production caller. The remaining English definitions and Arabic entries are
unchanged as complete values, including wording, review/import provenance and
metadata. Arabic `catalogue_sha256` is updated to the new English artifact hash;
other artifact metadata is preserved. Retired definitions/translations are kept
in verification evidence, not the active catalogue.

The existing API catalogue synchronization deprecates missing definitions rather
than deleting database translation/history rows. No persistent database was
changed and no new translation draft is needed. No administrator export was
promoted; no retained translation needs new review. Restart API/WebUI when
loading the updated code and catalogue; no database migration is introduced.

## Verification

- **233 unit tests and 34 interaction tests passed** (267 total).
- The retired page is rejected without loading data or changing the active
  navigation. Current workspace/scheme/classification detail restoration passes.
- All other collection resources remain eligible. Collection background
  localization, compact results, filters, save refresh and request bounds pass.
- Classification editor/controller, selectors, workspace, navigation coordination,
  entity definitions and feature-boundary checks pass.
- Catalogue completeness/stale-key checks, terminology, ordered English/Arabic
  coverage, placeholders, nonblank wording, provenance and artifact hash pass.
  Configuration authority and API template consistency also pass.

| Browser | English and Arabic | Passing groups | Screenshots |
| --- | --- | ---: | ---: |
| Chrome 157.0.8103.51 | Pass | 11 | 24 |
| Edge 157.0.4341.46 | Pass | 11 | 24 |

Both native runs passed on their first attempt, with no browser errors,
unsuccessful recorded API requests or server tracebacks. The current workspace
captures were inspected in both languages and browsers. All recorded application
and harness source hashes match the verified files.

Both uniquely named disposable PostgreSQL databases were initialized through the
canonical runner and dropped. An independent PostgreSQL catalogue query confirms
cleanup, with no owned test processes or native drivers left running. No persistent
database was used. Branch and HEAD match the initial checkpoint; no branch,
worktree, staging, commit, history or remote operation was performed.

Python syntax and `git diff --check` also pass. Verification is focused and local;
no full-suite, comparative timing benchmark, Firefox/Safari or remote CI run is
claimed. No cache or request path was added to the current workspace.

The browser journey exercises the existing workspace in English and Arabic:
bounded hierarchy paging, retained expansion, inherited retention, detail reload,
editor keyboard focus, event history, transfer entry, empty filters, publication,
deactivation/reactivation, fresh detail and return to the tree. Each language now
has its own synthetic scheme so publication is exercised in both languages.

Historical cleanup/repair reports and their immutable evidence remain as records
of earlier states. Their old source snapshots are not imported or run by current
application code or test suites.

## Evidence

- [Acceptance](verification/classification-scheme-table-removal/acceptance.json),
  [source removal audit](verification/classification-scheme-table-removal/removal-audit.json)
  and [application diff from the starting checkpoint](verification/classification-scheme-table-removal/application-change.diff)
- [Unit results](verification/classification-scheme-table-removal/unit/tests.xml)
  and [interaction results](verification/classification-scheme-table-removal/interaction-final/tests.xml)
- [Chrome results](verification/classification-scheme-table-removal/chrome/browser-results.json)
  and [Edge results](verification/classification-scheme-table-removal/edge/browser-results.json)
- [Translation preservation](verification/classification-scheme-table-removal/translation-validation.json)
  and [retired messages](verification/classification-scheme-table-removal/retired-messages.json)
- [Validation](verification/classification-scheme-table-removal/validation.json),
  [database cleanup](verification/classification-scheme-table-removal/database-cleanup.json),
  [process cleanup](verification/classification-scheme-table-removal/process-cleanup.json)
  and [file hashes](verification/classification-scheme-table-removal/manifest.sha256)
