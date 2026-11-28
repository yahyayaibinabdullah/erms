# Classification Tree: Representative Performance Verification

**Date:** 27 November 2026. **Status:** Measurement complete. Correctness passed;
the three-second page-response requirement **failed for 84 of 114 API requests**.
No optimization or application changes were made.

## Policy and scope

The user requested 50-item classification-tree batches and about 100 immediate
**child aggregations per parent aggregation**. These are fixture choices, not
application limits. A classification with 50,000 roots is a valid stress case;
each bounded 50/100-item page still must meet three seconds. Unpaged bulk
retrieval of the full collection needs a separate budget.

The run follows the real tree APIs for classification nodes, root aggregations,
child aggregations, records, filters, empty/short branches and Load-more paging.
Expanding an aggregation requests the first child and record batches
concurrently, matching the UI. This measures API response time through TestClient
against the real application and Linux PostgreSQL, including authentication,
SQL and serialization. Browser rendering and HTTP network transit are excluded.

## Fixture and execution

- 51,003 aggregations and 153,009 records; one digital component per record.
  File-text chunks are omitted because tree requests do not read them.
- 50,000 roots spread over 500 terminal classifications, 100 per classification,
  plus an empty terminal classification. Five classification groups contain
  the populated terminal classifications.
- 1,003 child aggregations across eleven parents: ten have 100 children, one
  has three. Tested parents 1 and 101 each have 100 children and 100 records.
- Two disabled but attached number generators exercise natural number ordering.
  The counter table remains empty.
- Every request specifies 50 items. All continuation pages are followed;
  response sizes, exact IDs/order, totals and cursor termination are checked.
- Three repetitions per case, with an authorized reader and a signed-in caller
  with global privileges but no resource ACL grants. Denied parent requests
  return 404; root lists are empty and classification badges expose no hidden
  roots. No expected ID is skipped or duplicated.
- PostgreSQL 18.4 on Linux with LLVM/JIT available and original JIT preserved.
  Checksums, fsync and full-page writes are enabled. No index, planner, memory,
  storage-policy or application-SQL changes were made.
- Canonical initialization, separate seeds, VACUUM ANALYZE and 60 seconds idle
  without search warm-up. No other test/browser workload from this task ran
  concurrently. Host observations and source hashes are retained.

## Overall result

| Measure | Result |
| --- | ---: |
| API requests | 114 |
| Correct IDs, totals, order, pagination and permissions | 114/114 |
| Requests over the three-second page limit | 84 |
| Median API response | 4.284 s |
| p95 API response | 7.229 s |
| Maximum API response | 10.142 s |

These are page-limit failures, including empty-result cases. The recorder's zero
exit status means capture/correctness/cleanup completed, not that latency passed.
No optimization was attempted in response.

The slowest request was the authorized reader's first 50-item page of **child
classifications** in a 100-classification group, first repetition:
`GET /api/v1/browse/classifications/1/children?limit=50`.
It returned classification nodes, not child aggregations or the entire repository.

p95 uses nearest rank. Per-case sample counts are small (three or six), so these
results do not establish a production tail-latency guarantee.

## Authorized reader

| Case | Requests | Over 3 s | Median | p95 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| Top-level classification nodes (6 nodes) | 3 | 3 | 3.685 s | 4.217 s | 4.217 s |
| Child classifications (100 nodes) | 6 | 6 | 9.641 s | 10.142 s | 10.142 s |
| Root aggregations, first classification (100 roots) | 6 | 6 | 4.586 s | 4.725 s | 4.725 s |
| Root aggregations, second classification (100 roots) | 6 | 6 | 4.428 s | 4.620 s | 4.620 s |
| Filtered roots (12 matches) | 3 | 3 | 4.291 s | 4.625 s | 4.625 s |
| Root filter with no matches | 3 | 3 | 3.313 s | 3.363 s | 3.363 s |
| Empty terminal classification | 3 | 3 | 4.036 s | 4.171 s | 4.171 s |
| Short child-aggregation branch (3 children) | 3 | 0 | 0.460 s | 0.506 s | 0.506 s |
| Empty child-aggregation branch | 3 | 0 | 0.339 s | 0.349 s | 0.349 s |
| Empty record branch | 3 | 3 | 3.935 s | 3.956 s | 3.956 s |
| Filtered records (12 matches) | 3 | 3 | 4.325 s | 4.651 s | 4.651 s |
| Child aggregations, parent 1 (100 children) | 6 | 6 | 4.218 s | 6.553 s | 6.553 s |
| Records, parent 1 (100 records) | 6 | 6 | 5.197 s | 7.229 s | 7.229 s |
| Child aggregations, parent 101 (100 children) | 6 | 6 | 5.775 s | 6.356 s | 6.356 s |
| Records, parent 101 (100 records) | 6 | 6 | 6.398 s | 7.245 s | 7.245 s |

## Caller without resource access

| Case | Requests | Over 3 s | Median | p95 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| Top-level classification nodes (6 nodes) | 3 | 3 | 3.914 s | 4.134 s | 4.134 s |
| Child classifications (100 nodes) | 6 | 6 | 4.061 s | 4.827 s | 4.827 s |
| Root aggregations, first classification (100 roots) | 3 | 3 | 4.849 s | 5.086 s | 5.086 s |
| Root aggregations, second classification (100 roots) | 3 | 3 | 4.598 s | 4.646 s | 4.646 s |
| Filtered roots (12 matches) | 3 | 3 | 5.113 s | 5.254 s | 5.254 s |
| Root filter with no matches | 3 | 3 | 4.080 s | 4.140 s | 4.140 s |
| Empty terminal classification | 3 | 3 | 4.641 s | 5.450 s | 5.450 s |
| Short child-aggregation branch (3 children) | 3 | 0 | 0.020 s | 0.031 s | 0.031 s |
| Empty child-aggregation branch | 3 | 0 | 0.011 s | 0.020 s | 0.020 s |
| Empty record branch | 3 | 0 | 0.016 s | 0.022 s | 0.022 s |
| Filtered records (12 matches) | 3 | 0 | 0.010 s | 0.010 s | 0.010 s |
| Child aggregations, parent 1 (100 children) | 3 | 0 | 0.020 s | 0.021 s | 0.021 s |
| Records, parent 1 (100 records) | 3 | 0 | 0.015 s | 0.017 s | 0.017 s |
| Child aggregations, parent 101 (100 children) | 3 | 0 | 0.015 s | 0.016 s | 0.016 s |
| Records, parent 101 (100 records) | 3 | 0 | 0.011 s | 0.015 s | 0.015 s |

## First versus subsequent pages

Complete per-case/caller/first-versus-next statistics and all individual
timings, including every above-limit page, are in `tree-results.json`.
First child/record batches are concurrent; their Load-more calls are independent.

| Authorized-reader branch | First-page median | Next-page median |
| --- | ---: | ---: |
| Child classifications (100 nodes) | 9.911 s | 6.468 s |
| Root aggregations, first classification (100 roots) | 4.591 s | 4.388 s |
| Root aggregations, second classification (100 roots) | 4.365 s | 4.491 s |
| Child aggregations, parent 1 (100 children) | 4.464 s | 3.972 s |
| Records, parent 1 (100 records) | 5.098 s | 5.297 s |
| Child aggregations, parent 101 (100 children) | 6.314 s | 5.236 s |
| Records, parent 101 (100 records) | 6.989 s | 5.741 s |

## Concurrent expansion observations

Twelve additional **group timing observations** use requests already counted
in the 114 total. They must not be counted as twelve more requests. They time
the wait for both first batches, excluding browser rendering.

| Caller | Expansion pairs | Median | p95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| reader | 6 | 6.963 s | 7.247 s | 7.247 s |
| denied | 6 | 0.016 s | 0.022 s | 0.022 s |

## Evidence, checks and cleanup

Artifacts: `.runtime/search-performance/classification-tree-representative-20261127/`.

- `environment.json`, `tree-fixture.json`: dataset, distribution, settings/hashes.
- `tree-results.json`: samples, per-case/caller/page statistics, all above-limit
  pages and concurrent expansion observations.
- `tree-expected-ids.json`: exact independent membership/order.
- `tree-plan-*.json`: exact production count/page SQL captured after response
  timers, with execution plans and unchanged JIT.
- `host-processes.jsonl`, `cleanup.json` and adjacent `*-linux.json`: host
  observations and successful database/container cleanup.

Harness checks used fresh native disposable databases. The first attempt found
a missing helper import. The second passed the request assertions but exposed a
nested TestClient teardown error. Both attempts and their cleanup remain in
`.runtime/classification-tree/representative-20261127/`. The corrected smoke test
passed in **9.86 seconds**; database
`erms_messaging_test_acl_eb29f57e58b94703bb71359d45f93917` was dropped.

The full run dropped database
`erms_search_perf_814a411383b74e6fa947661d2876d133` and removed container
`erms-search-perf-linux-6f212888d7764104b65c99a9e28f0163`.
Both cleanup artifacts confirm success.

Source hashes cover 1,159 application/schema/test/artifact files. No existing
application, search, UI, schema or translation source changed. The only changed
file in that snapshot was the new harness smoke test, finalized before the full
run. Every benchmark source hash matches its recorded start-of-run value.
The new harness/runners/test compile. Configuration authority (131 settings)
and API environment-template consistency (37 entries) passed. No environment
variable was added. Full remote CI was not run.

Earlier concentrated stress results remain in the
[custom-generator report](custom-code-generators-final-performance.md).
These profiles differ and are not a controlled before/after optimization
comparison. Neither the stress overruns nor these representative failures
caused an application optimization change.

## Reproduction

Use a new output directory and the existing local image only:

```sh
backend/services/api/.venv/bin/python tools/run_linux_search_performance.py --image sha256:a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636 --workload classification-tree --repeats 3 --settle-seconds 60 --output .runtime/search-performance/classification-tree-representative-NEW-RUN
```

The user handles commits, publication, deployment and separately authorized
optimization. All current changes remain local and uncommitted.
