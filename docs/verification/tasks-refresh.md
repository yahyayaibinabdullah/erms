# My Tasks Refresh — 5 November 2026

Contract: Destruction §6.2 / DEST-21. Keep Refresh visible outside the collapsible
filters so users can retrieve newly assigned work without opening those filters.

`tasks_screen` moves the existing translated Refresh action into an always-visible
row below the filters and above the table. It uses the same native row layout
as Eligibility and Jobs: aligned left in English and right in Arabic. It reuses
`PageTable.load(reset=True)` and the existing
bounded tasks endpoint: one fresh request, preserving filter values, sorting,
page size and filter disclosure state while returning to the first page. Existing
rows remain visible during loading; existing error and abandoned-response guards
apply. No result cache, API change or database migration was introduced.

The real NiceGUI inbox tests cover English and Arabic, an updated assignment,
failed refresh and navigation away during an outstanding response. They verify
the button sits outside the collapsed filter expansion, no duplicate button,
one request per click, unchanged query/filter/sort/size parameters, first-page
reset, loading continuity, refreshed rows and stale-response rejection. The full
task UI test module passed **245 checks**.

Live browser verification used the production inbox component and Wathiq styles
over in-memory sample data. In both languages, Refresh was visible with filters
closed, and clicking it added the newly available task and changed the total from
one to two without opening the filters.
The placement refinement was verified using rendered dimensions: in English the
button starts at its action row's left edge; in Arabic it ends at the row's right
edge. In both languages its top is below the collapsed filter heading and its
bottom is above the table. The same 245 checks passed after the move.
The Apply filters expansion also uses the same `filter_alt` icon as Eligibility
and Jobs, preserving its translated label and collapsed/expanded behavior.

- [English](tasks-refresh/english.jpg)
- [Arabic](tasks-refresh/arabic.jpg)

The existing `disposition.ui.refresh` English/Arabic label and tooltip are reused;
no catalogue key, wording or curated translation changed. No database tests or
persistent task mutations were needed.

Catalogue reference checks, configuration-authority and API-template consistency,
Python compilation and `git diff --check` passed. The local stack was restarted
to load the change. The broad disposition-baseline checker has known unrelated
historical drift; this change reconciles the modified source and DEST-21 only.
