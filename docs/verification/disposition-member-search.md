# Disposition aggregation search wording — 29 October 2026

The job/task Aggregations tab reused the Jobs list's **Search job number**
label. The approved correction changes only this field to **Search aggregations**
and adds a persistent NiceGUI input hint:

> Search by aggregation number or title, owning organization unit name, or
> classification code or title. Press Enter to search.

The hint follows the existing five-field OR predicate in
`backend/services/api/disposition/queries.py::members`. The current job ID
continues to scope every search. No API behavior, pagination, authorization,
requests, caches, saved filters or other search labels changed.

`frontend/webui/disposition/screens.py::job_screen` uses two new contextual
keys, `disposition.ui.search_aggregations` and
`disposition.ui.search_aggregations_hint`. The existing row now uses NiceGUI's
`items-start` alignment because the input hint adds bottom height; observed
bottom alignment put the Membership control below the search box. No CSS
override or table change was needed.

## Verification

- Existing disposition screen/task tests: **258 passed** in 7.61 seconds.
- Catalogue references/stale keys, lexicographic order, exact English/Arabic
  active-key coverage, blanks, placeholder contracts, markup, provenance,
  approved Arabic glossary and current artifact hash checks passed.
- The two new Arabic entries pass the generation validator. Its whole-artifact
  mode also flags pre-existing curated wording (including an outdated Vital
  record spelling expectation and the established `Re:` prefix); retained
  entries were preserved rather than regenerated to satisfy that older tool.
- Live browser inspection of the actual workspace renderer with a synthetic
  API fixture confirmed visible English and Arabic labels/hints and aligned
  controls. The fixture used no database. Screenshots:
  [English](disposition-member-search/english.png),
  [Arabic](disposition-member-search/arabic.png).

The catalogue now has **3,923 active keys**. All 3,921 prior Arabic artifact
entries and deprecated history remain exactly unchanged. No administrator
export was promoted. Both new generated Arabic drafts require human review.

The managed demo stack was restarted with the final change. Missing-only
seeding added two unpublished generated drafts; a read-only comparison
confirmed all **3,974 prior demo Arabic translation rows** were unchanged.
API and WebUI health checks passed. No database-backed test suite ran and no
user aggregation, proposal or job was modified. The temporary preview process
and agent-created browser tabs were closed after verification.
