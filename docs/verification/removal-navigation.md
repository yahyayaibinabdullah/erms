# Membership removal navigation — 5 November 2026

Contract: Disposition §18.1. Individual and bulk removal must retain the
Aggregations view in both job and task workspaces.

The removal callbacks previously reopened the default job/task entry point,
discarding the selected tab. `job_screen.reload_members` now captures the current
member-table view and uses the workspace refresh callback. The existing
`PageTable` handles an emptied last page. Bulk conflict refresh follows the same
path. Mutation endpoints, authorization and workflow transitions are unchanged.

`frontend/webui/tests/test_disposition_removal_navigation.py` covers 12 cases:
English/Arabic, job/task workspaces, individual removal, bulk removal and bulk
conflict refresh. It verifies selected tab, job/task identity, search, filter,
sort, page size, current page and bounded server requests. Bulk removal empties
the last page and verifies the preceding page is shown. Individual removal is
tested with the actual response shape, which has no job-version field.

**121 checks passed** across removal navigation, bulk actions, selection,
shared footer, pending proposals and existing screens. No database-backed tests
were needed for this frontend callback fix; no persistent job was mutated.

Live browser checks mounted the actual job screen and Wathiq table components
with in-memory sample data. In both languages, individual removal changed the
active count from 35 to 34, removed the selected row and retained Aggregations.
The existing table styling and RTL presentation were preserved.

- [English after removal](removal-navigation/english-after.jpg)
- [Arabic after removal](removal-navigation/arabic-after.jpg)

No UI text, catalogue, schema, environment setting or API contract changed.

Catalogue references, configuration authority, API environment-template
consistency, Python compilation and `git diff --check` passed. The broad
disposition-baseline checker still reports unrelated pre-existing source-range,
unowned-requirement and historical schema-anchor drift; this change reconciles
the modified Disposition source and §18.1 only and does not claim release-wide
traceability acceptance.
