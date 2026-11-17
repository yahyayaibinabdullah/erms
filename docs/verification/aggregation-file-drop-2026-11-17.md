# Aggregation file drop — 17 November 2026

Contract: [approved specification](../../specs/aggregation-file-drop.md).
Changes remain local and uncommitted on the existing branch.

**Implemented approved amendment:** AFD-2/AFD-3 now require an editable title
confirmation dialog for multi-file **Create one record with all files**,
prefilled from the first browser-supplied filename including its extension,
with a scrollable, numbered file list that determines digital component order.
Reordering updates the suggested title from the first file while preserving a
custom title.
With multiple eligible roles, the same dialog also contains **Create for**.
The browser supplies no selection-click history, so confirmation lets the
user correct a suggestion that differs from their intended filename.
The specification, implementation and acceptance checks have been updated.
See the follow-ups below, especially file ordering, for current verification. Earlier
combined-record automatic-save results describe the preceding behavior and
are superseded by these confirmation checks.

## Traceability

| Requirement | Implementation | Verification |
| --- | --- | --- |
| AFD-1: page overlay, Physical denial, existing creation policy | `aggregation_file_drop.py/js`; protected `POST /api/v1/aggregations/{id}/records/file-drop` | API Physical/anonymous/scoped-denial cases; NiceGUI disabled/abandoned cases; browser Physical overlay in both languages |
| AFD-2: single / separate / combined, confirmed title and component order, numbers, no links | Shared numbering/storage; reorderable file list keyed by original file index; editable title and files in confirmed order in one multipart request | API title/duplicate-file content/order/rollback assertions; UI reorder/confirm/edit/cancel checks; live three-target browser flow |
| AFD-3: owning-unit role, title/role dialog as applicable, no governance exception | Existing `_select_creator_role`, shared creator context; eligible-role selection and combined-title confirmation | API owning/unrelated/governance and creation-without-component-read cases; sole/multiple eligible-role confirmation tests |
| AFD-4: atomic records and bytes, single count toast | One API transaction for complete multipart batch | Inject second-file failure in both modes; assert no records, components, content sets or blobs; browser one-toast assertions |
| AFD-5: direct-child personal activity and preview/View all | Existing batched `recent_activity` SQL with early aggregation scope; shared activity card renderer | Scope before cap, record-visibility revocation, creator attribution, zero per-record API calls; navigation abandonment; drop and normal Add record freshness; browser LTR/RTL placement |
| AFD-6: Originated (records) / Opened (child aggregations) ascending, ID ascending; page/submitted/draft filter preservation | Both page loaders submit historical date and ID sorts; invalidate only submitted search result ID after mutation | Legacy dates differing from system creation, ID ties across pages; reverse-number browser fixture; contained-record and child-aggregation large-fixture gates |
| AFD-7: Last page only on aggregation lists | Native NiceGUI buttons on both local pagers | Browser keyboard activation, disabled last-page state, submitted-filter paging |

## Focused verification

- 22 API tests passed in a fresh disposable PostgreSQL database, including existing numbering/activity regressions. Database cleanup confirmed in `.runtime/aggregation-file-drop/api-tests.log`.
- 69 API-client/NiceGUI tests passed, including 10 new interaction tests. Evidence: `.runtime/aggregation-file-drop/focused-webui.log`.
- Chrome browser acceptance passed all 5 checks in English/Arabic: actual multipart drops, both multi-file targets, right/left panel placement, Physical overlay, last-page keyboard controls, submitted/draft filters, normal Add record freshness, and 49 → 50 → 52 records expanding the list to page 3 while retaining page 2. Screenshots and request logs were inspected in `.runtime/webui-integration/a4985b0e9dd44050bbe0ee760b3c1153/`; `lifecycle.json` confirms service/database cleanup.
- All 5 relevant existing component authorization tests passed (draft creation, post-commit changes, atomic replacement, metadata-only visibility and preview permissions); 1 unrelated governance-correction case was deselected. Evidence: `.runtime/aggregation-file-drop/existing-content-tests.log`; disposable database cleanup confirmed.

Activity uses one bounded API response for preview and View all. The batched SQL resolves roles/privileges and creator names as shared sets; opening an entry is the only record-detail request. The mounted snapshot is scoped to page identity, principal and locale, refreshes on mount/creation, rejects abandoned replies and shows retry on failure. No cross-page cache was introduced.

## Performance

The required `tools/check_search_performance.py` gate now includes broad, selective, empty and denied aggregation activity cases. The unchanged fixture contains 51,003 aggregations, 153,009 records, 153,009 components and 306,018 search chunks; each case is repeated three times. Exact IDs/counts, timings, SQL execution plans, JIT/environment settings and cleanup are retained in:

`.runtime/search-performance/62f247fdc9e54481a593ca6149cad765/`

All new activity cases passed correctness and the 3-second limit. The broad authorized case returned its exact expected 50 records in 58.6–70.4 ms; selective responses were 47.7–48.7 ms. Denied/empty responses were at most 21.8 ms. Plan inspection confirms shared effective-role/privilege CTEs, not a per-record detail/authorization loop. PostgreSQL 18.4 on macOS reports JIT unavailable; the gate preserves the search-scoped JIT setting and logs restoration/environment details. This local build cannot measure production LLVM compilation overhead.

The first full gate run was **not green**: one existing Global Search first-page response was 3.8049 seconds. All correctness assertions passed; no search SQL/storage/planner changes were made to mask the failure. The failed sample is retained. Database deletion succeeded (`cleanup.json`).

A second full run, after the other database/browser test jobs finished, **passed** the unchanged 3-second gate and all correctness checks, with no failures. Evidence: `.runtime/search-performance/10102782d0774538ad637e636d941924/` and `.runtime/aggregation-file-drop/search-performance-final.log`. The initial failed sample above remains retained. In this final run the broad activity responses took 58.3–90.3 ms and selective responses 46.1–46.8 ms. Its disposable database was also deleted successfully.

## Broader test limitations

The complete DB-free WebUI unit runner timed out at its existing 600-second limit, after reporting failures; its interaction phase did not run. Evidence: `.runtime/webui-tests/481cbef6f3db4210a329da9b1e2aba67/` and `.runtime/aggregation-file-drop/full-webui.log`. It is not reported as passing.

The existing personal-preview suite has 12 failures because it invokes the asynchronous favourites callback without awaiting it. These exact failures were reproduced by loading `personal_resource_views.py` from unchanged `HEAD`, with 2 other cases passing. Evidence: `.runtime/aggregation-file-drop/baseline-personal.log`. The feature's separate preview/View all test passes. An existing activity-client expectation was updated to include its already-present nullable `created_by` projection.

## Translation and delivery

Added 13 English/Arabic keys under `aggregation_file_drop.*`; both catalogues are sorted with identical active-key coverage. All existing Arabic entries, including wording and per-item provenance, were verified unchanged against HEAD. No administrator export was promoted. New Arabic values are generated drafts requiring human review. Coverage, placeholders, blanks, markup, approved terminology, stale references and artifact hashes passed validation. The older generic draft generator has pre-existing conflicts with curated terminology; it was not used to rewrite the artifact.

The explicitly authorized local `demo` translation utility ran with `--missing-only`: 13 new drafts stored, 4,115 existing values protected, zero corrections, failures or missing generations. New drafts remain unpublished. This was translation synchronization, not a test against the persistent database.

The API policy inventory was regenerated. No schema migration or environment-template changes are required. Restart API and WebUI processes to load the new route/components.


## Follow-up: refresh after the child-record Preview action

The existing rendition endpoint correctly wrote `CONTENT_VIEWED`; the aggregation page had no callback to refresh its mounted activity snapshot. The listing's Preview icon and the expanded component's Preview icon now pass a success callback through the shared viewer to `activity.load`. Saved image/audio/video previews notify after successful content retrieval and display construction; PDF/converted-document previews notify after the viewer opens. Failed, abandoned and private draft previews do not refresh saved activity.

This calls the existing batched activity endpoint once per successful preview, without reloading the child-record list or looking up individual activity records. No API/query/authorization or translation changes were needed.

Focused verification: 19 interaction tests (including 9 new preview cases), 23 existing staged/saved viewer tests, and 4 API recent-activity tests passed. The API runner created and deleted a fresh disposable database. Logs are in `.runtime/aggregation-file-drop/preview-*.log`. The preview cases cover both action icons, native/PDF rendering, failed/abandoned responses, draft isolation and View all's reuse of the refreshed data.

Live Chrome acceptance passed in English and Arabic for both the child-record listing Preview icon and the expanded component Preview icon. Each successful preview produced exactly one scoped activity request, displayed **Viewed**, preserved the submitted and draft filters, and made no record-detail or records-search request. The preceding file-drop/paging checks also passed. Evidence: `.runtime/webui-integration/933a089668b84ab8b80ba88042557b38/`; all 7 checks passed and the disposable stack/database were cleaned up.


## Follow-up: a single eligible Create for choice

At the user's request, AFD-3 now counts eligible choices in the aggregation's owning unit, rather than all effective roles. File drops automatically use the sole eligible choice even when the user has roles in other units. Several eligible choices still require the role-only dialog; no eligible choice still denies creation. The existing server-side owning-unit and authorization checks are unchanged.

All 13 file-drop/activity interaction tests passed. Three new cases reproduce multiple effective roles with only one eligible role (deliberately not the first returned role), covering a single file and both multi-file options. They verify no dialog, exactly one upload, submission of the eligible role ID and successful refresh. Existing multiple-choice and denied-creation tests also passed. Evidence: `.runtime/aggregation-file-drop/one-eligible-role.log`. No database, API, layout or translation changes were required.

## Follow-up: confirm or edit the combined-record title

Multi-file **Create one record with all files** now always opens a confirmation
dialog. Its editable Title starts with the first filename supplied by the
browser, including its extension. Native file-manager selection-click history
is unavailable, so this suggestion cannot promise the user's first-clicked
file. The user can confirm it or supply a different title before creation.
One eligible owning-unit role is assigned automatically; several eligible
roles add Create for to the same dialog. Single-file and separate-record
automatic creation retain their existing rules.

The browser sends filenames alongside the drop mode/count, without
uploading files before confirmation. The UI rejects blank titles and guards
unconfirmed uploads and duplicate submission. Cancel, Escape and dismissal
clear the pending drop; completed dialogs are removed. The API client passes
the confirmed title in the existing multipart request. The combined-record
API requires that title and validates it with the same `NonBlankString` type
as ordinary record creation, including trimming surrounding whitespace.
Original filenames, component order and content are preserved, with the
existing atomic transaction and authorization checks intact.

Title-confirmation verification (before the filename-dropdown addition):

- **30 interaction tests passed**, including unchanged/edited/blank titles,
  sole/multiple eligible roles, cancellation/dismissal, abandoned pages,
  premature uploads, duplicate activation and preview/activity regressions.
  Evidence: `.runtime/aggregation-file-drop/title-ui.log`.
- **61 API-client tests passed**, including parsed multipart assertions for
  title submission, original filenames, order and content.
  Evidence: `.runtime/aggregation-file-drop/title-client.log`.
- **18 file-drop API tests and 2 catalogue tests passed**. These cover
  title validation before any creation, unchanged/edited titles, component
  content/order, atomic rollback, unauthenticated/scoped denial and the
  owning-unit requirement with and without Information Governance bypass.
  The runner created and dropped a new disposable PostgreSQL database.
  Evidence: `.runtime/aggregation-file-drop/title-api.log`.
- **All 7 Chrome browser checks passed** in English/LTR and Arabic/RTL.
  Combined drops used a non-alphabetical browser payload order and confirmed
  unchanged and edited titles. Cancel and Escape produced no file-drop API
  request and subsequent drops worked. Blank-title submission was disabled.
  Current page/submitted/draft filters and Last page behavior were preserved.
  The dialog screenshots were visually inspected in both languages.
  Existing preview checks still verify one batched activity refresh and no
  per-record detail lookups. Evidence and confirmed disposable-stack/database
  cleanup: `.runtime/webui-integration/f8e01a370d86488398fc7b6a33a285e6/`.

This amendment reuses existing translated Title, Create for, Cancel and Create
record labels: no keys or translation artifacts were added, changed or removed,
and no administrator export was promoted. Catalogue coverage, ordering,
placeholders, nonblank values, provenance, hash and terminology checks passed;
the source-reference/stale-key check also passed
(`.runtime/aggregation-file-drop/title-catalogue.log`). No new translation
review is required for this amendment. The API policy registry was regenerated.
No activity/search query, schema or environment changes were needed. The
broader-suite limitations above remain recorded; this follow-up ran focused
checks rather than the complete application test suite.

## Follow-up: choose a dropped filename as the title

The same combined-record confirmation dialog now includes **Use filename as
title**, listing all dropped filenames with extensions in browser order.
The first is selected initially. Selecting another filename fills the editable
Title; selecting the first again restores that suggestion. A custom edit clears
the dropdown selection without overwriting the text. Neither selecting a
filename nor editing the title creates records before confirmation or changes
digital component filenames, contents or order. The role-selection rules and
existing batched Recent Activity path are unchanged.

The specification and acceptance checks include this interaction. All **32
focused interaction tests passed**, including filename selection, restoring
the first choice, subsequent custom editing, and confirmation with one or
multiple eligible roles. Evidence: `.runtime/aggregation-file-drop/filename-ui.log`.
The API and client implementation are unchanged from the successful
title-confirmation checks above.

Added one contextual English/Arabic key, `aggregation_file_drop.title_filename`.
All 4,128 pre-existing Arabic entries and provenance were preserved. No keys
were removed and no administrator export was promoted. The Arabic text is a
generated draft requiring human review. Source-reference/stale-key validation
and both catalogue artifact/terminology tests passed; the latter used a new
disposable database with confirmed cleanup. Logs:
`.runtime/aggregation-file-drop/filename-catalogue.log` and
`.runtime/aggregation-file-drop/filename-catalogue-api.log`.
The authorized local `demo` missing-only seed stored one unpublished draft,
protected 4,128 existing values, and reported zero corrections, failures or
missing generations (`.runtime/aggregation-file-drop/filename-arabic-seed.log`).

All **7 Chrome acceptance checks passed** with the filename dropdown in
English/LTR and Arabic/RTL. Both runs checked browser-order options, selected
another filename, exercised Cancel and Escape, and confirmed a selected or
subsequently edited title. Dialog screenshots were visually inspected in both
languages. Paging/filter preservation, batched activity and both Preview
actions still passed. Screenshots, request evidence and confirmed disposable
stack/database cleanup are retained in
`.runtime/webui-integration/bee36784ff494d91969180bea7646f2e/`.

## Follow-up: reorder files before creating the combined record

The filename dropdown is replaced by a numbered file list in a native NiceGUI
scroll area. It uses the existing component **Move earlier** / **Move later**
buttons, with keyboard access and disabled boundary controls. The viewport
reserves five complete rows plus native content padding and borders; shorter
lists use their actual row count. Rows retain their element identity when
moved. No custom drag library or CSS override is required.

The first filename, including its extension, remains the suggested title.
Reordering updates that suggestion while Title matches the previous first
filename and preserves custom text otherwise. The pending order uses original
file indices, not filenames, so identically named files remain distinct.
On confirmation the existing single multipart API request receives files in
the displayed order, and the API assigns component orders 1..N. Existing
creation authorization, atomicity, role selection and batched Recent Activity
remain unchanged. The specification and acceptance checks now cover this order.

**33 focused UI tests passed** (`.runtime/aggregation-file-drop/order-ui.log`),
including first-file suggestions, custom-title preservation, sole/multiple
roles, cancellation, six-file reordering, boundary buttons and duplicate
filenames with distinct bytes. **19 file-drop API tests and 2 catalogue tests
passed** (`.runtime/aggregation-file-drop/order-api.log`), including persistence
of duplicate filenames in confirmed order with their original contents. The
API runner's new disposable database was created and dropped successfully.

The first browser run detected four complete rows because NiceGUI's native
scroll-content padding was omitted from the initial height calculation.
The screenshot and NiceGUI component styles identified the cause; the height
now includes `--nicegui-default-padding` and the border. Failed evidence and
confirmed database cleanup are retained in
`.runtime/webui-integration/0d226f43eab041ca9493c3b199fd6151/`.

Retired `aggregation_file_drop.title_filename` from the active catalogues and
added `aggregation_file_drop.component_order` and
`aggregation_file_drop.reorder_hint` with Arabic drafts. All other 4,128 Arabic
entries and provenance were preserved; no administrator export was promoted.
Catalogue and source-reference/stale-key checks passed. Missing-only seeding
in the authorized local `demo` database stored two unpublished drafts,
protected 4,128 values and reported zero corrections/failures/missing
generations. Definition synchronization deprecates the retired dropdown key
while retaining its translations and history. New drafts require human review.
Logs: `.runtime/aggregation-file-drop/order-catalogue.log` and
`.runtime/aggregation-file-drop/order-arabic-seed.log`.

RTL inspection followed design-language section 19.1. An isolated UI-only
probe in the in-app browser measured the native row as `direction: rtl` but
`flex-direction: row-reverse`, caused by the existing global `.row` rule.
Removing that class through NiceGUI's supported layout API restores native
RTL flow. The scroll viewport uses LTR coordinates with an explicitly
localized inner column, matching the existing ACL-matrix approach; filenames
retain automatic bidi direction and align with the language's start edge.
There is no new global CSS override. A suspected clipped-button screenshot
was not reproduced by full-app bounds measurements, retained in
`.runtime/webui-integration/29ccaa8bf6844ba8892f85da5c4073d6/`; those measurements
did confirm the incorrect row reversal. The final browser checks now assert
both button bounds and actual mirrored ordinal/action placement rather than
direction attributes alone. The synthetic probe was stopped and its tab
closed after inspection; it used no database or user files.

Final verification after the native layout correction: **33 UI tests passed**
again (`.runtime/aggregation-file-drop/order-ui-final.log`), and **all 7 Chrome
acceptance checks passed** in English/LTR and Arabic/RTL. The browser verified
five complete visible rows with six files, scrolling to and moving the last
file, keyboard reordering, title updates and custom-title preservation,
button bounds and mirrored placement, and actual persisted component order
1..N. Cancellation, submitted/draft filters, Last page, batched activity and
both Preview actions also passed. Both dialog screenshots were visually
inspected. Evidence, geometry and confirmed disposable-stack/database cleanup:
`.runtime/webui-integration/5b040783672d40b0926724d671a445d9/`.


## Superseded creation-order follow-up

This intermediate change was superseded by the historical-date amendment below.
The user initially replaced item-number sorting with `date_created ASC, id ASC` for
both aggregation-page lists. Text comparison had placed `.10` before `.2`.
The two loaders now submit that explicit server-side sort; the displayed
Originated date does not control ordering. Submitted filters, draft edits,
current page, Last page and the batched Recent Activity query are preserved.
The specification and AFD-6 acceptance checks supersede the earlier number-order
contract and evidence above.

Focused verification: **33 UI tests passed** (`chronology-ui.log`) and **21
API tests passed** (`chronology-api-verified.log`), under
`.runtime/aggregation-file-drop/`. The added API cases cover both lists,
non-chronological numbers `.1/.10/.2/.11`, a timestamp that takes precedence
over ID, and tied timestamps across filtered and unfiltered page boundaries.
The first API attempt (`chronology-api.log`) caught a test-fixture medium
mismatch, corrected before the passing run; both disposable databases were
removed. No application creation policy changed.

The large fixture now includes 1,100 direct child aggregations and varied
creation dates with large equal-timestamp groups. The performance gate checks every
page against independent SQL ordering, both authorized and denied users,
and empty children. The contained-record gate uses the new sort for ordinary,
broad, selective and empty filters, preserving the existing cap contract.

All **7 Chrome acceptance checks passed** in English/LTR and Arabic/RTL:
`.runtime/webui-integration/0849db057ea4417f9031bee75b8657a4/`.
The browser asserts oldest-first lists using reverse-number creation order,
Last page in both lists, page/filter preservation after creation, component
ordering/title confirmation, preview refresh and no per-record activity
lookups. `lifecycle.json` confirms disposable database cleanup and exit 0.


## Historical-date ordering amendment (current)

The approved order is **records: `date_originated ASC, id ASC`** and
**child aggregations: `date_opened ASC, id ASC`**. Both use full timestamps.
System creation records capture into Wathiq; migrated resources and physical
material captured in bulk may have much earlier historical dates. Native
creation represents the same event as origination/opening. Aggregations use
their existing Opened field, as explicitly confirmed by the user; no new
field, fallback rule or migration is introduced.

The current specification and AFD-6 acceptance checks cover historical versus
system dates, number-order discrepancies, and equal historical timestamps
with different system creation times. The UI keeps the current page and both
submitted/draft filters after drops, and Last page remains on these two lists
only. Recent Activity retains its existing activity chronology and batched
query, making new captures of old material discoverable.

The creation-date performance attempt in `chronology-performance.log` stopped
during setup because synthetic children incorrectly held a root classification;
its disposable database was removed and the fixture corrected to inherit the
classification. The following run (`chronology-performance-verified.log`) was
stopped when the user changed the required sort to historical dates; its
SIGTERM cleanup removed the disposable database. Neither is a passing gate
for the current behavior. Their evidence remains retained.

The current historical-date API run passed **21 tests**:
`.runtime/aggregation-file-drop/historical-api.log`; the disposable database
was removed. The initial historical-date browser run passed all English
checks, then an intercepted click in the existing Language settings dialog
prevented the Arabic run from starting. This is retained in
`.runtime/webui-integration/f1650e52bcf6442ea4ab60fd44001de0/`; its disposable
database was removed. The browser fixture now makes the second capture the
earliest historical item, so creation-time ordering cannot pass accidentally.

The final historical-date browser run passed **all 7 checks** in English/LTR
and Arabic/RTL, including both historical sorts, keyboard Last page,
preserved filter/page state, file/title order and batched preview activity.
Evidence: `.runtime/webui-integration/efd0f842f0e74158947d32d3b38f0dd7/`.
`lifecycle.json` confirms exit 0 and disposable database cleanup.

The final full search correctness/performance gate **passed with no failures**:
`.runtime/search-performance/cbeb9a22294d44b09719310bac965f9b/`, with console
log `.runtime/aggregation-file-drop/historical-performance.log`. Fixture:
51,003 aggregations, 153,009 records/components, and 306,018 chunks; three
repeats per case. The new branch contains 1,100 child aggregations and 1,100
records, with historical dates differing from capture dates and timestamp ties
crossing pages. Independent SQL oracles matched every returned ID in order.

| Changed flow (authorized reader) | Items | Complete API response range |
| --- | ---: | ---: |
| Records, ordinary browsing (all 44 pages) | 1,100 | 259.7–464.7 ms |
| Records, broad submitted filter (40 pages, existing cap) | 1,000 | 128.6–234.7 ms |
| Records, selective filter | 37 | 95.2–100.6 ms |
| Child aggregations (all 110 pages) | 1,100 | 178.7–307.6 ms |

Empty and denied cases also passed; denied callers received zero items.
All measured responses in the full gate stayed below three seconds. Exact
criteria, expected IDs, every response timing and analyzed plans are retained
in the evidence directory. The contained-record broad plan executed in
65.966 ms and child-aggregation plan in 41.919 ms. PostgreSQL JIT is unavailable
on this Mac; search-scoped `jit=off` and its restoration behavior were unchanged.
`cleanup.json` confirms the disposable database was dropped. No persistent
database was used for tests. `git diff --check` passed; changes remain local
and uncommitted. This sorting amendment introduces no UI text/catalogue keys.
