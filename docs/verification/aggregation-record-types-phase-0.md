# Aggregation and record types — Phase 0 baseline

Baseline revision `2a5bbb805ba445c3da24e6b399a873e1d2ad3230` on 18 November 2026. The working diff at test start comprised type specifications and planning documents. The benchmark environment files identify executable inputs by SHA-256. All measurements in this report concern the existing application before resource types.

**Final outcome, 19 November.** Phase 0 passed 230 regressions, all 1,524 standard responses and all 428 larger-text responses. [Verification of the application override](#verification-of-the-application-ranking-override-19-november)

**Initial outcome, 18 November.** Baseline collection is complete. Of 223 selected regression cases, 220 passed on the initial runs. All 1,524 standard benchmark responses met three seconds. Four of 428 larger-text responses missed the threshold. Both benchmarks passed their result-correctness checks. Phase 1 had not started at this point.

**After the approved fixes**, all 224 regression cases passed. The standard benchmark again passed all 1,524 responses (2.3474 s maximum). Five of 428 responses exceeded three seconds on the larger-text repeat. See the [follow-up and wait/I/O evidence](#follow-up-after-the-approved-fixes).

The [subsequent disposable-cluster repeat](#disposable-cluster-repeat) reproduced four first-page overruns, with a maximum of 7.169 s.

## Integration inventory

| Boundary | Integration and controlling requirements |
| --- | --- |
| Definition and value storage | Keep separate aggregation/record catalogues. Store stable IDs, ordered definitions, default-language names and localized definition labels. Use nullable type references on resources and enforce belonging to the correct catalogue. Store one value per resource/field, with field/type membership and native scalar validation. ART-01–08, 11 |
| Schema installation and upgrade | Add DDL to the self-contained canonical schema and a forward migration following the current migration series. Start existing resources untyped. Existing queries and resource metadata require no value backfill. Install the two approved privilege codes and three default profile grants through the appropriate fresh-install and upgrade paths, preserving unrelated grants. Upgrade tests compare populated and fresh installations. ART-01, 09, 11 |
| API contracts and write transaction | Optional type assignment on create/update. On update distinguish omitted type (retain), explicit null (remove), and destination ID (assign/change). Key field values by stable IDs and distinguish omitted keys from explicit clears. On first assignment apply validated literal defaults only to omitted values. Check Use for old/new types and existing operation rights. Save reassignment, removal of old values and history atomically. Apply existing concurrency and custody locks. ART-06–11, 14–17 |
| Single-resource access and explanations | Map route policies and adapters in `main.py`, `resource_authorization.py`, `authorization_policy.py` and `governance_authorization.py` to the See/Use table in spec §7.3. Cover components, creation/commit, moves, copy/import where supported, ACL/security changes and deletion. Check SQL access and retained-resource functions separately. Attribute type-only governance bypass even when ACL access passes. ART-09, 14–18 |
| Visibility in SQL | Extend effective roles and authority in `dashboard_visibility.visibility_ctes` with kind-scoped type grants. Join to record/aggregation candidate rows before counting, ordering and caps. Shared consumers include search, page checks, dashboard, favourites, recent activity and messaging filters. Include scalar-predicate collection paths in `crud.list_rows`, authorized search views, parent/relationship disclosure and exports. Compare with canonical single-resource decisions. ART-13, 18, 21, 23 |
| Caching and accepted extra queries | Preserve session/tab scope in `search_cache.py`; recompute current visibility for subsequent pages. Retain separate `search_page.page_details` enrichment, record/aggregation batches in cached Global Search, non-tab fallback count/result and per-item attribution, and relationship/freshness checks. Invalidate affected ranked lists on choice reorder. ART-17–19, 23 |
| Query and indexing contract | Extend existing `SearchExpression.field` and `SearchSort.field` strings with a controlled stable-ID namespace. Reserve e.g. `type.17.field.42` for field 42 of type 17 in the request's resource kind and `type_id` for assignment criteria. Compare choice IDs, retain the existing Boolean grammar, validate type ownership and See access for every reference including sort. Sort missing last, choices by defined order, then existing tie-breakers. Only populated text values enter the resource's own metadata text index. ART-04, 08, 13, 19 |
| Saved definitions | `saved_searches._serialize` currently copies the full row and the builder loads its definition. Batch-check all explicit condition/sort references before normal list/read/restore disclosure and again for execute/paging. Restricted summaries omit the whole definition. Preserve administrative inspection as specified. ART-17–19, 22 |
| WebUI | Reuse existing entity translation editor, paged catalogue/role selectors, group/condition builder and resource detail dialogs. Add type metadata below primary metadata in the first tab. Choice IDs are predefined. An optional Other text field is independent. ART-03–08, 12, 20, 22 |

In the [shared visibility SQL](../../backend/services/api/dashboard_visibility.py), derive allowed type IDs by resource kind once from `effective_roles` and the definition grants. Carry the assigned type ID through `live_aggregations` and `live_records`. Apply the See predicate in `authorized_aggregations` and `authorized_records`, where each row already has its required clearance and the caller's governance clearance. An untyped resource passes the type gate. A typed resource passes with a matching grant or a qualifying governance role's own clearance. All consumers then count, sort and page the authorized rows. Keep ACL source resolution independent so a hidden parent can still supply an inherited ACL without disclosing the parent. The [authorization design](../../specs/resource-type-authorization-design.md) identifies the single-resource, retention and explanation paths that require the same decisions.

Illustrative Phase 0 query encoding for Phase 3 compiler/validator tests (IDs are examples):

```json
{
  "where": {"and": [
    {"field": "title", "operator": "contains_ci", "value": "inspection"},
    {"or": [
      {"field": "type.17.field.42", "operator": "gte", "value": 100},
      {"field": "type.19.field.8", "operator": "eq", "value": 3}
    ]}
  ]},
  "sort": [{"field": "type.17.field.42", "direction": "desc"}]
}
```

The second branch compares a single-choice field to choice ID 3. Existing primary-field expressions and saved definitions keep their encoding. An example resource update is `{"type_id":17,"type_values":{"42":125}}`. The API must validate every ID against resource kind, type and field. These are technical integration sketches for later implementation.

## Comparison method

Use the native PostgreSQL runners sequentially with current vector storage, 30 seconds of post-maintenance idle time and three repetitions. Compare future equivalent-access requests on the same fixture and transport. Use independent expected results for newly introduced criteria. Preserve failed samples individually. Each runner owns its disposable database.

The commands below reproduce the timing workload. Supply fresh output directory names for each comparison.

```sh
backend/services/api/.venv/bin/python tools/check_search_performance.py --output .runtime/search-performance/types-p0-standard-01 --settle-seconds 30 --repeats 3
backend/services/api/.venv/bin/python tools/check_large_text_search_performance.py --output .runtime/search-performance/types-p0-large-01 --settle-seconds 30 --repeats 3
```

The earlier [instrumented Global Search page report](search-page-batching-2026-11-13.md) gives a reference statement-count baseline for its two specific ten-row UI queries: 12 statements on first pages, 10 and 11 on Next, and zero additional per-record capability calls. Those counts are historical and workload-specific. The standard runner records stage timings and plans; distinguish those from SQL statement counts.

## Standard query baseline

The standard runner exited successfully. The fixture contained 51,003 aggregations, 153,009 records, 153,009 files and 306,018 chunks. All independent result checks passed. The 1,000-result cap applied to capped searches. The fixture also tested uncapped browsing.

| Measured workload | Responses | Maximum complete API time |
| --- | ---: | ---: |
| Global Search | 192 | 2.6413 s |
| Tab search, saved execution and collection filters | 684 | 2.1850 s |
| Contained records and filters | 273 | 0.5856 s |
| Child aggregations | 339 | 0.3276 s |
| Global Search at UI page sizes | 18 | 2.2258 s |
| Recent activity | 18 | 0.0621 s |
| Total | 1,524 | 2.6413 s |

All 1,524 responses met the three-second limit. The broad combined search matched 204,012 authorized items before the cap. Its three first submissions took 2.6413, 2.2948 and 2.0359 seconds. The same query for the denied identity returned zero results in all repetitions. The runner checked the saved ranked hits and page sequence against independently calculated expectations. Timings include the TestClient API pipeline and serialization.

Native PostgreSQL 18.4 ran on macOS arm64 with checksums enabled as recorded in the environment artifact. PostgreSQL reported JIT unavailable. These measurements do not establish timings for an LLVM-enabled server. The standard runner dropped its owned database. The [raw standard artifacts](../../.runtime/search-performance/types-p0-standard-01/) include environment and source fingerprints, per-request samples, independent expected rankings, plans and cleanup.

## Larger-text baseline

The loopback HTTP runner measured 428 responses across 17 queries on 51,003 aggregations, 153,009 records and 180,630 LZ4-compressed chunks. The corpus included 151,470 single-chunk files, 1,386 ten-chunk files and 153 hundred-chunk files. All ranked page sequences, complete cached rankings, scores, capped totals, truncation flags and denied results matched expectations. All 16 file-content cases also passed independent uncapped membership checks. The runner captured 17 execution plans and verified that the score-producing batches ran at most once per plan.

**Latency gate failed.** Four reader submissions exceeded three seconds. The table shows every first submission for the affected queries. The parenthesized times measure the ranking stage within each failed response.

| File-content query | Authorized matches before cap | Round 1 | Round 2 | Round 3 |
| --- | ---: | ---: | ---: | ---: |
| `universal -restricted` | 76,505 | 1.9176 s | **6.2434 s** (6.0384 s ranking) | **6.1387 s** (5.9247 s ranking) |
| `universal -"boundaryalpha boundarybeta"` | 152,809 | 2.8949 s | **6.8641 s** (6.6335 s ranking) | 2.8746 s |
| `"document evidence"` | 153,009 | 2.5280 s | 2.6893 s | **7.0107 s** (6.7368 s ranking) |

The other 424 responses met the limit. Broad combined metadata and content submissions took 2.3216, 2.3666 and 2.4949 seconds. The slowest cached page took 0.4536 seconds and the slowest denied response took 1.2260 seconds. PostgreSQL reported JIT unavailable. The runner exited with its latency assertion after checking correctness and recording plans, then dropped its database. These observations establish pre-feature latency and carry no new exception to the three-second threshold. The [larger-text artifacts](../../.runtime/search-performance/types-p0-large-01/) retain every sample, stage, expected and observed ranking, uncapped membership digest, plan and cleanup record.

## Existing regression tests

Across 20 selected test modules, **220 of 223 distinct cases passed**, three failed and none were skipped. Counts below exclude reruns and the diagnostic probe. Each database-backed process used [the disposable test runner](../../tools/run_disposable_acl_tests.py) and the canonical schema.

| Coverage | Passed / run | Evidence |
| --- | ---: | --- |
| Policy evaluator, profile administration and custody, governance and explanations, security monitoring, batch visibility, search/cache and concurrency, saved searches, component metadata, translation/editor, policy inventory, Advanced Search builder | 182 / 185 | [JUnit cases](../../.runtime/search-performance/types-p0-regressions-01.xml) |
| Read and mutation authorization, component authorization, resource detail APIs and pooled search-setting restoration | 38 / 38 | [JUnit cases](../../.runtime/search-performance/types-p0-read-write-01.xml) |

- The [Global Search page comparison](../../backend/services/api/tests/test_global_search_page_batch.py) observed different item payloads between the first submission and a cached request for page one. The focused rerun passed. A subsequent controlled API reproduction using the timestamp from the original failure isolated the difference to fractional-second formatting. The first page returned `07:06:01.78968+00:00` and the cached page returned `07:06:01.789680+00:00`. All other item fields were equal.
- Two [Advanced Search builder tests](../../frontend/webui/tests/test_advanced_search_builder.py) failed again on the focused rerun. They assert exact source strings for component preview and compact-row layout. The [current renderer](../../frontend/webui/compact_resource_view.py) passes additional preview options and uses NiceGUI row arguments for wrapping and alignment. These failures establish source mismatches. Browser behavior was outside this baseline run.

The [three-case confirmation](../../.runtime/search-performance/types-p0-confirm-01.xml) preserves the rerun outcomes separately from the original failures. A second run of the [complete six-case Global Search page-batch module](../../.runtime/search-performance/types-p0-page-batch-01.xml) also passed all six cases.

## SQL statement counts

A diagnostic using two accessible records, no components and one result per page counted calls to `psycopg.Cursor.execute` during each complete authenticated API request. Setup and instrumentation were outside the measured requests. Retain this small fixture for like-for-like comparisons when the type gate is added. The counts include authentication and page work, so they measure more than just the visibility SQL.

| Request | First submission | Next page |
| --- | ---: | ---: |
| Record list filter on title | 15 | 15 |
| Global Search over record metadata | 15 | 14 |

The non-tab record search requesting full-text attribution took 14 statements for one result and 15 for two. This captures one of the accepted repeated stages on this fixture. The [probe](../../.runtime/search-performance/test_types_p0_sql_counts.py) and [observed counts](../../.runtime/search-performance/test_types_p0_sql_counts.json) preserve the payloads and measurement boundary. The diagnostic passed and its disposable database was dropped.

## Database cleanup

All seven runners confirmed a successful drop. No database cleanup is pending.

| Run | Disposable database |
| --- | --- |
| Standard benchmark | `erms_search_perf_9988f53263654b79b25a212f124c1ef1` |
| Larger-text benchmark | `erms_large_text_aa66e6c04ba249b9a51f87be9a24a7d0` |
| Main regression selection | `erms_messaging_test_acl_d9249737d9124b65912e05ed00354d25` |
| Additional read/write regressions | `erms_messaging_test_acl_3c572833193e41268c61f52245f08e74` |
| Statement-count diagnostic | `erms_messaging_test_acl_b0f16022b7254bb6a3a12716b6709a6c` |
| Three-case confirmation | `erms_messaging_test_acl_63dd1b34b0714094aea9c56ab52c7280` |
| Page-batch module confirmation | `erms_messaging_test_acl_dc8aa7f4826845fd9065648570e671da` |

## Follow-up after the approved fixes

Global Search now passes the first-page timestamp from PostgreSQL JSON through the same API datetime encoder used for a cached page. The change applies to record `date_originated` and aggregation `date_opened`. The ranking SQL and cache reauthorization are unchanged. The new regression uses a fixed timestamp with a trailing fractional-second zero and compares both complete result items.

All 223 original regression cases and the new timestamp case passed in a fresh database. The [JUnit report](../../.runtime/search-performance/types-p0-fix-regressions.xml) lists every case. The separate [preview and related UI tests](../../.runtime/search-performance/types-p0-fix-preview.xml) passed all 12 cases, including clicks on two distinct matched files and the absence of component-preview controls when preview is denied.

Chrome verified the computed alignment, wrapping and direction on actual result rows. All 15 [Advanced Search checks](../../.runtime/search-performance/types-p0-ui-advanced-search/browser-results.json) passed. Search rows had centered alignment and no wrapping in English and Arabic. [Focused contained-record checks](../../.runtime/search-performance/types-p0-contained-layout-confirm/browser-results.json) confirmed centered alignment and wrapping in both directions. The first focused diagnostic stopped at screenshot capture because it passed the target positionally. The confirmation used the helper's keyword argument.

The first full aggregation browser run also exposed a fixture selection error. Its [request trace](../../.runtime/search-performance/types-p0-ui-aggregations/requests.jsonl) showed holds assigned to record 3 while the test opened record 1. The check now opens the held record by its stable ID. All 21 [full aggregation browser checks](../../.runtime/search-performance/types-p0-ui-aggregations-confirm/browser-results.json) passed on the confirmation run.

### Larger-text control using the November 14 protocol

The current MAIN/LZ4 run used native PostgreSQL 18.4, the same 180,630 compressed chunks, three repetitions, a 1,000-hit cap, pages of 100 and real loopback HTTP. The runner verified the vectors, allowed 60 seconds of settling, retained the first request and ran EXPLAIN after timing. This run added a read-only observer and host disk counters. The user reported disabling Microsoft Defender real-time protection for this control. All 17 generated ranking SQL statements and parameter sets, expected rankings and uncapped membership digests matched the November 14 and original Phase 0 artifacts byte for byte. The runner verified the observed page sequences, scores, totals, permissions, truncation and score-batch reuse.

| Complete file-content first page | Nov 14 accepted (seconds, rounds 1 / 2 / 3) | Original Phase 0 | After fixes |
| --- | --- | --- | --- |
| `universal -restricted` | 1.589 / 2.227 / 1.875 | 1.918 / **6.243** / **6.139** | 1.937 / **6.649** / **6.502** |
| `universal -"boundaryalpha boundarybeta"` | 2.376 / **3.407** / 2.381 | 2.895 / **6.864** / 2.875 | 2.623 / **7.317** / 2.633 |
| `"document evidence"` | 2.673 / 2.670 / 2.484 | 2.528 / 2.689 / **7.011** | **3.131** / 2.527 / **7.444** |

The strict limit failed on five of 428 responses, compared with four in the original Phase 0 run and one on November 14. All five were reader submissions. All 360 cached pages (maximum 0.4651 s) and all 17 denied requests (maximum 1.1395 s) met the limit.

**Wait events and host I/O.** The observer took 2,320 snapshots at a median interval of 106 ms. The table covers the ranking stage of every slow request. Wait counts are point-in-time samples. Host bytes are differences in cumulative disk counters at the samples nearest the beginning and end of ranking and include other processes.

| Query and round | Ranking time | Async I/O completion samples / active ranking samples | Host read / written (MiB) |
| --- | ---: | ---: | ---: |
| Quoted phrase, round 1 | 2.870 s | 4 / 27 | 51.7 / 34.8 |
| Word exclusion, round 2 | 6.437 s | 33 / 61 | 12.0 / 18.6 |
| Phrase exclusion, round 2 | 7.072 s | 19 / 67 | 6.1 / 34.9 |
| Word exclusion, round 3 | 6.278 s | 20 / 59 | 6.3 / 18.1 |
| Quoted phrase, round 3 | 7.205 s | 28 / 67 | 33.2 / 56.3 |

The same four long ranking intervals recurred. Across those intervals, 100 of 254 active ranking samples showed `AioIoCompletion`. Four more showed a temporary-file write and 150 had no reported wait. No sampled ranking backend reported a lock wait. During all four spikes, the host sampler still observed Microsoft's `epsext` system extension using CPU, with per-request peaks of 89.4–91.1% of one core. The sampled `wdavdaemon_unprivileged` process showed 0% in those windows. The run establishes an asynchronous I/O wait contribution and recurring host activity. It cannot assign the waits to any specific host process or quantify sampling overhead. The wider investigation can compare the same corpus on an isolated PostgreSQL host.

The [raw larger-text control](../../.runtime/search-performance/types-p0-control-large-01/) retains all response samples, plans and cleanup. The [per-ranking summary](../../.runtime/search-performance/types-p0-control-large-01/ranking-wait-summary.json) joins stage timestamps to the [raw wait and disk samples](../../.runtime/search-performance/types-p0-control-large-01/waits-and-host-io.jsonl). The [accepted run](search-vector-storage-2026-11-14.md) remains the November 14 reference.

The [portable capture (gzip-compressed JSON)](aggregation-record-types-phase-0-control.json.gz) preserves all 428 HTTP timings, all 2,320 wait/I/O snapshots, ranking-stage correlations, environment settings and cleanup alongside this report.

### Standard query control

The standard benchmark ran sequentially after the larger-text control using the original Phase 0 settings (30 seconds settling, three repetitions). All correctness checks and all 1,524 responses passed. The slowest complete response was a Global Search request at a UI page size, 2.3474 s. The three broad combined first submissions took 2.2788, 1.9783 and 2.0772 s for 204,012 matches before the cap. See the [standard control samples, plans and cleanup](../../.runtime/search-performance/types-p0-control-standard-01/).

All eight follow-up disposable databases were dropped, including both early browser exits. The [regression runner log](../../.runtime/search-performance/types-p0-fix-regressions.log), benchmark cleanup files and each browser run's `lifecycle.json` preserve the individual confirmations.

### Disposable-cluster repeat

On November 18 the runner created a fresh database on the configured native PostgreSQL 18.4 cluster. The machine and its storage were shared. The run preserved the November 14 query sequence, including intervening searches and paging, MAIN/LZ4 storage, 60 seconds of settling and three rounds over loopback HTTP. The original Phase 0 run used 30 seconds of settling. The two instrumented runs used identical application and benchmark source hashes.

| File-content query | Nov 14 accepted | Original Phase 0 | Previous instrumented control | Fresh database |
| --- | --- | --- | --- | --- |
| `universal -restricted` | 1.589 / 2.227 / 1.875 | 1.918 / **6.243** / **6.139** | 1.937 / **6.649** / **6.502** | 1.936 / **6.501** / **6.517** |
| `universal -"boundaryalpha boundarybeta"` | 2.376 / **3.407** / 2.381 | 2.895 / **6.864** / 2.875 | 2.623 / **7.317** / 2.633 | 2.628 / **7.169** / 2.647 |
| `"document evidence"` | 2.673 / 2.670 / 2.484 | 2.528 / 2.689 / **7.011** | **3.131** / 2.527 / **7.444** | 2.533 / 2.510 / **7.123** |

Times are complete first-page response seconds in round order. Bold samples exceeded three seconds. Four of 428 responses failed the latency gate. The same four query/round combinations exceeded six seconds in all three Phase 0 runs. All 360 cached pages (maximum 0.325 s) and 17 denied requests (maximum 1.170 s) passed. Correctness checks passed for every query. The 17 ranking statements and parameters, expected results and uncapped membership digests matched all three comparison runs byte for byte.

| Slow first page | Ranking seconds | Async I/O completion / active ranking samples | Host read / written during ranking (MiB) |
| --- | ---: | ---: | ---: |
| Word exclusion, round 2 | 6.291 | 27 / 59 | 1.7 / 9.2 |
| Phrase exclusion, round 2 | 6.932 | 25 / 65 | 3.2 / 69.0 |
| Word exclusion, round 3 | 6.317 | 27 / 60 | 1.7 / 14.5 |
| Quoted phrase, round 3 | 6.888 | 24 / 65 | 6.4 / 27.8 |

The observer collected 2,269 snapshots at a median interval of 106 ms. During the four slow rankings, PostgreSQL reported `AioIoCompletion` in 103 of 249 active samples, compared with 100 of 254 in the same four rankings of the previous control. Three samples showed temporary-file I/O, and 143 showed no reported wait. No lock wait was observed in those rankings. Disk counter differences include every host process. The observations establish recurring I/O waits during ranking and leave their underlying cause unresolved.

The [portable capture](aggregation-record-types-phase-0-cluster-repeat.json.gz) contains all HTTP timings, wait events, host disk counters and ranking-stage correlations. The [raw run directory](../../.runtime/search-performance/types-p0-cluster-repeat-01/) retains execution plans and correctness evidence. The runner [confirmed the drop](../../.runtime/search-performance/types-p0-cluster-repeat-01/cleanup.json) of `erms_large_text_4048ae5077d04cc8a1943cf93d61a3b3`. Phase 1 had not started at this point.

The [actual fast and slow ranking plans and configuration experiment](search-ranking-actual-plans-2026-11-18.md) follow up on the four recurring reader spikes above.

## Verification of the application ranking override, 19 November

The API now sets `effective_io_concurrency = 0` around the single initial Global Search ranking statement. It restores the incoming connection value before cache insertion. The benchmark ran the ordinary application path on native PostgreSQL 18.4 with no experimental override argument. Both gates used three repetitions, the existing 1,000-result cap and independent result oracles. [Scope and rationale](../search-performance.md#global-search-ranking-io)

The larger-text run used the November 14 sequence and 60-second settling period. All 428 responses passed, with a maximum of 2.404 s. The 17 expectation files and the uncapped membership file were byte-identical to the previous disposable-cluster repeat. Times below are complete reader first-page HTTP responses in seconds. [Portable results](adopt-ranking-rich-01.json.gz) · [Raw plans, waits, host I/O and cleanup](../../.runtime/search-performance/adopt-ranking-rich-01/)

| File-content search | Previous repeat, rounds 1 / 2 / 3 | With the application override |
| --- | --- | --- |
| `universal -restricted` | 1.936 / 6.501 / 6.517 | 1.646 / 1.369 / 1.413 |
| `universal -"boundaryalpha boundarybeta"` | 2.628 / 7.169 / 2.647 | 2.146 / 2.126 / 2.238 |
| `"document evidence"` | 2.533 / 2.510 / 7.123 | 2.070 / 1.943 / 2.029 |

The separate four-reader cold-cache experiment still recorded 15 of 24 responses above three seconds at zero. That workload measures simultaneous cold starts. The serial release gates and their three-second threshold remain as specified. [Cold-cache measurements](search-cold-concurrent-2026-11-19.md)

On the standard corpus of 51,003 aggregations and 153,009 records, all 1,524 responses met three seconds. The maximum was 2.4237 s, compared with 2.3474 s in the previous control. The broad combined query matched 204,012 resources and took 2.1587, 1.9114 and 1.9455 s on the three first pages. Every expectation file matched the previous control byte for byte. Both runners verified their database drops. [Standard samples](adopt-ranking-standard-01.json.gz) · [Raw timings, execution plans and cleanup](../../.runtime/search-performance/adopt-ranking-standard-01/)

The selected suite passed 230 cases, including six new checks for ranking scope, isolation, success, failure, rollback and pool reuse. The original 224 tests also passed. [Regression output and database lifecycle](../../.runtime/search-performance/adopt-ranking-regressions.log)
