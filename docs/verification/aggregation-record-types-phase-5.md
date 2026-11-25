# Phase 5 verification · 21 November 2026

## Scope

The administration screens use the existing Wathiq paginated table and entity translation editor. Administrators can maintain types, fields, ordered choices, static defaults and role grants. Use includes See. Each resource editor uses the same typed controls, and the first details tab places type metadata below primary metadata. Advanced Search keeps its existing Boolean builder. A condition or sort selects the type before the field. Saved definitions retain stable field and choice IDs and secondary sort keys.

The checkpoint’s record draft fix was present in the merged working tree. The draft computes the assignment during commit. The post-merge Phase 4 import check uncovered a misplaced asynchronous call in the aggregation action menu. Moving it into the first metadata tab fixed the import and placed the section where specified. [Phase 4 rerun](aggregation-record-types-phase-4.md)

## Reproduction

Run the catalogue and terminology checkers and the database-free WebUI runner. The assembled browser starts its own stack and fixture. The benchmark commands each create, initialize and drop their own disposable database. Use distinct output directories for each run.

```sh
frontend/webui/.venv/bin/python tools/run_webui_tests.py --output .runtime/search-performance/p5-webui-final
backend/services/api/.venv/bin/python tools/run_webui_integration.py --browser chrome --browser-scope resource-types --output .runtime/search-performance/p5-browser-final
backend/services/api/.venv/bin/python tools/check_search_performance.py --resource-types --settle-seconds 30 --repeats 3 --output .runtime/search-performance/p5-standard-01
backend/services/api/.venv/bin/python tools/check_search_performance.py --type-ui --settle-seconds 30 --repeats 3 --output .runtime/search-performance/p5-type-ui-02
```

## Large fixture and comparison

Each large fixture contains 51,003 aggregations, 153,009 records, 153,009 components and 306,018 chunks. The runner vacuums and analyzes the fixture, waits 30 seconds and makes three rounds of complete API requests with a 1,000-hit cap. PostgreSQL 18.4 on this Mac has no LLVM JIT. Phase 5 uses the same ranking and evidence paths exercised by the post-merge Phase 4 larger-text run.

The standard gate passed all 1,524 samples. The slowest was 2.6573 s, compared with 2.5297 s after the merge in Phase 4. All 296 comparable expected-result and ranking files matched the reference byte for byte. The database was dropped. [Samples, plans and environment](p5-standard-01.json.gz)

The first typed run passed all 237 structured search checks. The new UI workload initially tried to reopen the FastAPI connection pool after the structured workload closed it. The runner now measures both workloads inside one application lifespan, using the same authenticated client. The first disposable database was dropped.

The repeat passed all 237 structured requests and all 144 requests made with the UI’s catalogue and selector parameters. The structured fixture included 182 types per kind, 145 fields in the General type, 150 configured choices for Priority, 160 saved searches per kind and 1,200 matching directory roles. Independent checks covered IDs, counts, sort order, denials, bounded pages and selection by ID. Twelve actual search plans are retained. Both benchmark databases were dropped. [Every typed sample, plan and fixture](p5-type-ui.json.gz)

| Workload | Responses | Maximum |
| --- | ---: | ---: |
| Structured searches, sorting, paging, saved searches and authorization | 237 | 1.4713 s |
| Type administration catalogue | 18 | 0.0215 s |
| See and Use selectors | 24 | 0.0143 s |
| Role directory | 18 | 0.0161 s |
| Field pages and selected-field reads | 42 | 0.0095 s |
| Choice pages and selected-choice reads | 42 | 0.0216 s |

The slowest structured request sorted all 153,009 records by configured choice order. The slowest new UI page read the last 25 of 150 choices. Its response took 0.0216 s. All 1,905 Phase 5 complete-response measurements passed the 3 s limit.

## Regression suites

The Phase 5 API coverage includes kind-specific administration, See-only selectors, forbidden selected IDs, choice lookup in a translated catalogue, role grant conflicts and custody. The catalogue test creates 130 definitions per resource kind and verifies the last page. The structured and text regression suites preserve the baseline search contracts. [API checks](../../backend/services/api/tests/test_resource_type_ui.py) · [Typed controls interaction tests](../../frontend/webui/interaction/tests/test_type_metadata_controls.py) · [Mixed query tests](../../frontend/webui/tests/test_type_metadata_ui.py)

The final disposable API run passed 69 cases across five modules in 275.84 s with two dependency deprecation warnings. The DB-free WebUI runs passed 1,650 unit tests in 50.21 s and 670 interaction tests in 217.81 s. Two asynchronous test fixtures initially waited indefinitely because their doubles omitted newly used dependencies. The corrected suites exercised the production callbacks, including stale-session isolation. The focused controls tests cover false, zero, Unicode, exact decimals, required defaults over multiple pages, deselection, cancellation and stale server responses.

## Assembled browser

Chrome exercised English/LTR and Arabic/RTL on a disposable local stack. The scenarios checked type administration for each resource kind, the paginated field and choice tables, choice creation/rename/deletion, Use implying See, a version conflict with unsaved edits retained, and repeated navigation. The test entered French names for both resource kinds through the same supported-language editor and checked that the Arabic names survived the save. Table header presentation was compared with the existing relationship-types screen. The choice dialogs were also exercised at narrow width with keyboard focus.

The existing aggregation and record details dialogs displayed the primary section first and the type-specific section below it. Chrome opened both editors, saved a changed text literal, then created a physical record from its parent, selected its type and verified the stored static default. In each language the saved mixed query restored the primary title criterion, the translated choice criterion and its descending type-field sort. Executing it returned the expected record. The final visual review aligned the operator control with the existing builder’s minimum width. The focused builder and controls rerun passed 47 cases.

All 12 assembled Chrome checks passed. Each catalogue opened with one catalogue request. Saved-query execution used one POST and returned the expected record in both languages. The following browser times include rendering.

| Language | Aggregation catalogue | Record catalogue | Execute saved query |
| --- | ---: | ---: | ---: |
| en | 0.276 s | 0.390 s | 0.253 s |
| ar | 0.293 s | 0.388 s | 0.230 s |

[English Advanced Search](types-p5-advanced-en.png) · [Arabic record details](types-p5-record-details-ar.png) · [Arabic choices at narrow width](types-p5-choices-narrow-ar.png) · [Regression and browser evidence](p5-ui-regressions.json.gz)

## Translation artifacts

The catalogue gained 55 English keys with matching Arabic drafts. The active-key and terminology checks passed, including 986 contextual uses of 35 glossary mappings. The explicit missing-only sync on local `demo` stored 55 drafts, protected 4,132 entries, and reported zero corrected, failed or awaiting generation. The catalogue contains 4,187 aligned keys. All pre-existing English and Arabic entries, including provenance, match the merged revision. The Arabic artifact references English catalogue SHA-256 `d71b0eea3485668cbc6171ac5ea41311d98f5a8587cc6aed236d1bd122e9e81a`. The drafts await translation review. This was a catalogue sync. Every database-backed test used a separate disposable database.
