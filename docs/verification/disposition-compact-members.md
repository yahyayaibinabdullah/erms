# Compact disposition aggregation listing — 29 October 2026

Approved scope: disposition revision 1.17, “Compact aggregation membership
listing”, requested by the user for the job/task Aggregations table.

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Reduce repetitive retention text in rows without losing the defining source or rule values | `screens.py` shows Classification · code or Local override; the native read-only dialog shows the full source, current/intermediate years and disposition action from the already authorized row | Bilingual parent-classification, local-rule, unknown/redacted-rule and disclosure assertions in `test_disposition_tasks.py`; live English/Arabic dialogs |
| Remove redundant membership/date columns from the normal view while retaining historical episodes | Default filter follows job lifecycle: Active, Completed history or Terminated history; Membership appears only for Any, Removed at only for Any/Removed | Six bilingual lifecycle-default cases, filter changes, retained pagination/navigation tests; live Any/Removed/Active transitions and deliberate empty state |
| Open proposals from nonzero counts | Native link-style button reuses the aggregation-scoped proposal dialog and existing bounded API | Root ID/round/page assertions; live count 2 opens both proposals; zero/restricted counts remain plain/unavailable |
| Keep the existing Wathiq presentation and performance contract | Existing PageTable styling, sorting/pagination, read-only rule disclosure without another request, existing lazy proposal request and liveness guards | Repeated tab navigation; English/Arabic screenshots; focused task/history suite: **257 passed** |

The old retention cell measured about 86 pixels wide and drove a 224-pixel
fixture row. With the compact cell and normal membership columns, the Arabic
fixture row measured **119 pixels** at the same 1,280-pixel viewport. The new
Membership selector uses a supported explicit width to avoid its former cramped
label. No global CSS or Quasar layout override is introduced.

The existing proposal dialog's intended width class was constrained by the
native 560-pixel dialog card limit. It now uses Wathiq's established NiceGUI
card `.style()` pattern: 1,050 pixels, bounded by the viewport with side margins.
Its full metadata table retains native horizontal scrolling when required.
Proposal fields, attribution, permissions, pagination and mutation behavior are
unchanged.

## Evidence

- [English aggregation table](disposition-compact-members/table-ltr.png)
- [Arabic aggregation table](disposition-compact-members/table-rtl.png)
- [English full rule](disposition-compact-members/rule-ltr.png)
- [Arabic full rule](disposition-compact-members/rule-rtl.png)
- [English proposals](disposition-compact-members/proposals-ltr.png)
- [Arabic proposals](disposition-compact-members/proposals-rtl.png)

## Translation artifacts and deployment

Added only `disposition.ui.retention_rule` to the English and canonical Arabic
catalogues. Both have **3,935 active keys**, in identical lexicographic order.
All **3,934 pre-existing Arabic entries**, including wording and provenance,
remain exactly unchanged. The added Arabic wording is a generated draft needing
human review. No administrator export was promoted or replaced.

Reference/stale-key, ordered coverage, blank/placeholder/markup, artifact hash,
new-entry provenance and approved terminology checks passed. The explicit
`--missing-only` seed utility applies the new draft to demo without publishing
it. See [translation preservation](disposition-compact-members/demo-translations.json).

No API, schema, privilege, workflow, environment-template or business-data change
is needed. All automated tests use in-memory UI fixtures. Browser verification
uses a newly created disposable PostgreSQL database; no test suite runs against
demo. The disposable database was dropped and preview ports 18000/18080/18081
are closed. The managed stack was restarted to apply the change to demo; API and
WebUI health both returned HTTP 200. See [final verification data](disposition-compact-members/verification.json).
