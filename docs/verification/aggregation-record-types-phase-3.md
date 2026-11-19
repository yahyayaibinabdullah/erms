# Aggregation and record types, Phase 3

Phase 3 passed on 19 November 2026. It covers structured criteria, sorting and saved-search disclosure for records and aggregations. Each final database-backed run confirmed the removal of its disposable database. The JSON grammar remains schema version 1. [Mixed-query example and operators](../search-grammar.md#type-specific-criteria-and-sort-keys)

| Final check | Result |
| --- | --- |
| Broad regression suite | 359 passed across 32 modules |
| Focused saved-search and authorization suite | 32 passed, overlapping the broad suite |
| Advanced Search browser checks | 17 passed in Chrome, covering English and Arabic |
| Standard large-dataset benchmark | 1,524 responses, maximum 2.9968 s |
| Type-specific large-dataset benchmark | 237 responses, maximum 1.8654 s |
| Authorization work in typed search plans | 12 of 12 built effective roles and accessible types once each |

[Regression results, module selection, browser checks and cleanup](types-p3-regressions.json.gz) · [Standard benchmark](types-p3-standard-02.json.gz) · [Typed benchmark](types-p3-structured-03.json.gz)

## Query evaluation

The compiler resolves all explicit type, field and choice references for a query together. It validates the kind and owning field before compiling native PostgreSQL comparisons. An unset test limits the candidate set to resources of the named type. An outer Boolean NOT complements that complete set, so other types can satisfy the negation. Criteria use sets of resource IDs. A typed sort joins the corresponding value relation, specifies NULLS LAST and preserves subsequent sort keys. A choice sort reads its display order. The cache fingerprint includes the owning definition’s version for each choice sort key. Other edits to that type can also rebuild the list. [Reference resolution](../../backend/services/api/type_search.py) · [Search compiler](../../backend/services/api/search.py) · [Cached search](../../backend/services/api/search_cache.py)

Saved-list disclosure resolves type references for the whole returned page. The ordinary GET, execution and page requests each check current access. Workspace restoration checks the saved definition before constructing the controls, and Open checks it again when the user acts on an earlier list. An administrator inspecting a restricted definition still receives a disabled execute capability. An administrative rename or audience edit can preserve the existing server-side definition. Changing its conditions or sort requires See on the proposed references. See alone is sufficient for the explicit reference check. Results also require each resource’s existing gates. [Saved searches](../../backend/services/api/saved_searches.py)

## Regression and benchmark record

The initial saved-search and cache regression run passed 31 tests. An early test fixture attempted to save two definitions with the same owner and name. Its correction exposed a second fixture error, inserting a delegated privilege without naming the target columns. Both original errors and their disposable-database cleanup remain in the run logs. The mixed Boolean, native-value, missing-last, stable-choice and multiple-page assertions passed for both resource kinds. [Typed search regressions](../../backend/services/api/tests/test_type_search.py)

The first typed large-data run exercised 51,003 aggregations and 153,009 records, with 182 types per kind, sparsely populated integers, 150 ordered choices, and 160 saved definitions per kind. All 141 requests met the three-second limit. The maximum was 0.705 s for a descending choice sort over records. The workload checked exact IDs, totals or expected denials, paged past 100 entries in the catalogues and saved lists, captured eight actual ranking plans and dropped the database. [Workload and independent oracles](../../tools/structured_type_search_performance.py)

Full-text scoring, chunk matching, evidence generation and indexing are outside these changes. The standard benchmark exercises existing full-text calls through the shared search entry points. Phase 2’s larger-text evidence covers the scoring pipeline on 180,630 chunks. [Larger-text benchmark](aggregation-record-types-phase-2.md#larger-text-comparison)

The first standard run retained the correct rankings but recorded five above-threshold first pages for broad Global Search (4.0027, 3.2832, 3.0485, 3.2479 and 3.3955 s). The failing requests used page sizes 10 and 25 and contained no type reference. Both broad-branch plan trees matched Phase 2, including join and index choices. The separately captured record-branch plan took 1.804 s against 1.717 s in Phase 2 and wrote the same 11,400 temporary blocks. Host samples showed Defender above 100% CPU in 226 of 402 snapshots, compared with 180 of 434 in the Phase 2 run. These are whole-run observations. They cannot identify the cause of an individual slow request. [First standard run](types-p3-standard-01.json.gz)

The final standard run passed all **1,524** timings. The slowest request, a reader’s broad content search, took **2.9968 s**, against the 3 s limit. Phase 2’s overall maximum was 2.547 s. The broad Global Search first pages that varied between runs are shown below. All 296 comparable ranking and expectation files were byte-identical to the Phase 0 reference. The disposable database was dropped. The local PostgreSQL 18.4 build lacks LLVM JIT, so these runs provide no production JIT compilation timings. [Final standard run](types-p3-standard-02.json.gz)

| Broad Global Search first page | Phase 2 accepted run (s) | Phase 3 first run (s) | Phase 3 final run (s) |
| --- | --- | --- | --- |
| 10 results | 2.090, 2.055, 2.205 | 4.003, 3.283, 2.905 | 2.192, 2.754, 2.068 |
| 25 results | 2.004, 2.009, 2.153 | 3.049, 3.248, 3.396 | 2.022, 1.987, 1.950 |

The expanded workload populated all **182 types per resource kind**, including 180 distributed across the former untyped population. Half of that population remained untyped. It tested an 80-type membership condition and every broad and selective criterion through the capped tab cache, the capped endpoint without a tab, and uncapped resource search. All **237 requests** met three seconds, including forbidden requests and selectors. The maximum was **1.550 s**, for an uncapped record choice sort. Twelve actual plans and the expected counts and returned IDs are retained. The database was dropped. [Expanded workload evidence](types-p3-structured-02.json.gz) · [Initial workload evidence](types-p3-structured-01.json.gz)

The final typed run repeated the expanded workload on a fresh database. All **237 requests** met their timing and correctness expectations. The slowest was an uncapped mixed-condition record search at **1.8654 s**. Each of the twelve captured execution plans built the effective-role and accessible-type sets once, across cached and uncached queries for both resource kinds. Cleanup succeeded. [Final typed run, expected and returned IDs, timings and plans](types-p3-structured-03.json.gz)

The focused contract run passed 32 tests, including restricted administrator inspection, metadata-only updates, rejected edits to restricted criteria, visibility after a grant or revocation, and exact JSON decimal literals in ad hoc and saved queries. During development, a mixed keyword/typed test initially left the disposable fixture’s full-text feature disabled. The permission inventory also still expected only one conditional global privilege route. The fixture now enables the feature and the inventory checks both the permissions catalogue and the new inspection condition. The earlier failures remain in the evidence. [Regression runs and database cleanup](types-p3-regressions.json.gz)

## Saved-search UI and translations

Headless Chrome passed all **17** Advanced Search checks on its disposable stack. Both English and Arabic showed the saved summary and a disabled Open action, explained why it was unavailable, and withheld the type name. The journey also restored existing searches, checked discard and administration actions, and paged submitted criteria while controls contained an unapplied change. The runner confirmed database cleanup. [English screenshot](types-p3-restricted-saved-en.png) · [Arabic screenshot](types-p3-restricted-saved-ar.png) · [Browser checks and database cleanup](types-p3-regressions.json.gz)

The two new message keys cover a forbidden type and an unavailable definition reference. The local demo catalogue sync stored two Arabic drafts, protected 4,130 existing translations and reported zero failures or missing drafts. Catalogue checks confirmed matching English and Arabic key coverage and all 35 approved Arabic terminology mappings. The new wording awaits administrator review.

## Reproduction

Run timing jobs consecutively with the API virtual environment active. Both commands create and drop a uniquely named disposable database. Inspect `typed-search.json` for the individual requests, independent expected counts, returned IDs and actual plans. All twelve captured typed plans built the effective-role and accessible-type sets once each.

```sh
python tools/check_search_performance.py --typed-search-only --settle-seconds 30 --repeats 3 --output .runtime/search-performance/local-p3-structured
python tools/check_search_performance.py --resource-types --settle-seconds 30 --repeats 3 --output .runtime/search-performance/local-p3-standard
```

Run the focused API cases through the disposable test runner. The retained regression evidence lists the modules for the broader run. The browser runner creates a second disposable database and starts its own API and WebUI.

```sh
python tools/run_disposable_acl_tests.py backend/services/api/tests/test_type_search.py backend/services/api/tests/test_saved_searches.py backend/services/api/tests/test_policy_inventory.py frontend/webui/tests/test_saved_search_localization.py
python tools/run_webui_integration.py --fixed-fixture --browser chrome --browser-scope advanced-search --output .runtime/search-performance/local-p3-browser
```
