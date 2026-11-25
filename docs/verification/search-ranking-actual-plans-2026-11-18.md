# Full-text search latency on PostgreSQL 18.4, 18 November 2026

## What changed between fast and slow requests

PostgreSQL executed the same 255-node ranking plan for each of the nine reader requests below. Within each query, a recursive comparison of the plan trees found differences only in buffer counters and I/O times. Every node had identical row estimates, actual rows and loop counts across rounds. The backend PID was the same for all nine. The largest measured difference was the first sequential scan of `digital_component_search_chunks`, which tests the file chunks against the full-text expression.

| File-content query | Complete HTTP seconds, rounds 1 / 2 / 3 | First chunk scan, shared-read milliseconds | Chunks matching on each execution |
| --- | --- | --- | ---: |
| `universal -restricted` | 1.997 / **6.525** / **6.523** | 322 / **2,553** / **2,551** | 83,435 |
| `universal -"boundaryalpha boundarybeta"` | 2.929 / **7.235** / 2.726 | 344 / **2,553** / 326 | 180,430 |
| `"document evidence"` | 2.584 / 2.578 / **7.236** | 328 / 330 / **2,605** | 180,630 |

The word-exclusion scan visited 104,895 shared blocks in every round. It read 95,397 of them into PostgreSQL buffers in the fast round and 94,647 in the first slow round. The slow round thus read slightly fewer blocks and spent an extra 2.23 seconds doing it. The scoring scan still ran once. Its measured shared-read time was 2–6 ms across the nine requests. Temporary block counts, disk-sort sizes and hash batches were constant by query.

The four slow rankings had 101 `AioIoCompletion` observations in 253 active backend samples and zero observed lock waits. Across the four intervals, the host recorded 1.4–16.5 MiB of device reads per interval. PostgreSQL counts a shared read when it brings a block into its buffers, including a read satisfied by the operating system's cache. Host counters include every process. The measurements locate about 2.2–2.3 seconds of added read time in the first scan. They leave part of the roughly 4.5-second elapsed gap unattributed. Per-node wall-clock timing was disabled to limit instrumentation overhead.

## Database configuration experiment

The comparison run set `effective_io_concurrency` to `0` only around the ranking SELECT, restored the previous value before page enrichment and ran the original 428 requests with live plan logging off. At zero, PostgreSQL disables asynchronous I/O requests governed by this setting. The workload used a pre-read fixture on a shared Mac. The closest comparison is the earlier fresh-database run with identical request order, observer and plan logging off. [PostgreSQL I/O configuration](https://www.postgresql.org/docs/18/runtime-config-resource.html#GUC-EFFECTIVE-IO-CONCURRENCY)

| Complete first page, seconds | November 14 accepted | Original Phase 0 | November 18 fresh database, 16 | November 18 ranking only, 0 |
| --- | --- | --- | --- | --- |
| `universal -restricted` | 1.589 / 2.227 / 1.875 | 1.918 / 6.243 / 6.139 | 1.936 / 6.501 / 6.517 | **1.767 / 1.366 / 1.352** |
| `universal -"boundaryalpha boundarybeta"` | 2.376 / 3.407 / 2.381 | 2.895 / 6.864 / 2.875 | 2.628 / 7.169 / 2.647 | **2.113 / 2.116 / 2.083** |
| `"document evidence"` | 2.673 / 2.670 / 2.484 | 2.528 / 2.689 / 7.011 | 2.533 / 2.510 / 7.123 | **2.037 / 1.997 / 1.983** |

All 428 responses in the configuration run passed the three-second gate. The slowest reader submission took 2.116 s, the slowest of 360 cached pages took 0.353 s and the slowest of 17 denied submissions took 0.639 s. The four formerly slow ranking windows had zero `AioIoCompletion` observations in 56 active samples. Their host read deltas ranged from 0.0 to 3.9 MiB. The earlier fresh-database run failed four of 428 responses with a maximum of 7.169 s. The November 14 run failed one of 428 with a maximum of 3.407 s.

**Recommendation.** Use a ranking-scoped `effective_io_concurrency = 0` as the candidate setting for this Mac's full-text workload. The database default can continue to serve the other queries. Before deploying the override, compare 16 and 0 on the target database host with concurrent readers and both warm and cold data. Check all individual response limits, ranked results, denied access and throughput, and verify restoration on pooled connections. This run measured serial HTTP latency on one shared host. The strongest explanation is overhead on the worker-based asynchronous read path when many pages can be served from the operating system cache. The data do not identify how much time was spent scheduling workers or which host processes contributed.

Keep `work_mem` at 4 MB for this change. Spill volumes were identical within each query, and an earlier 12 MB search-only trial still failed two samples. The measurements give no reason to change cluster-wide I/O workers, planner costs or shared buffers as part of this fix. [Earlier memory trials](../postgresql-search-optimization-lessons.md)

## Request order

After the three usual reader rounds, the runner rotated three predecessors before resubmitting the same negative-phrase search. It followed all pages between submissions. The cells give the target's complete first-page seconds. Each predecessor occupied each position once.

| Immediately preceding search | Rotation 1 | Rotation 2 | Rotation 3 |
| --- | ---: | ---: | ---: |
| Selective phrase (`"crossalpha crossbeta"`) | 2.736 | 7.153 | 7.207 |
| Broad word (`universal`) | 7.460 | 7.055 | 7.224 |
| Same negative phrase | 7.248 | 7.203 | 7.183 |

An immediate repeat stayed slow in all three rotations. The selective predecessor produced both a fast and two slow targets. Previous requests can affect database and operating-system cache state, but the preceding query alone cannot predict this outcome.

## Measurement and reproduction

Both runs used the native macOS PostgreSQL 18.4 cluster, separate disposable databases, MAIN/LZ4, 51,003 aggregations, 153,009 records, 180,630 chunks, 60 seconds of settling, the November 14 query order, a cap of 1,000 and pages of 100. Wait and host I/O sampling ran in both. `work_mem` was 4 MB, `shared_buffers` was 128 MB, `io_method` was `worker`, and `io_workers` was 3. The application disabled JIT for search. PostgreSQL settings outside the disposable benchmark sessions were preserved.

The first run captured the PostgreSQL plan from the actual ranking SELECT on each HTTP submission using session-local `auto_explain`, with buffers, actual rows, loops and I/O times. The benchmark buffered the plans in memory during measurement. It recorded 86 plans and 584 responses. Four of the 51 standard reader submissions exceeded three seconds. Fourteen of the 156 additional probe responses and one subsequently executed denied request also exceeded the limit. The probe ran before the denied checks, which changes their cache history. All 360 standard cached pages passed. [PostgreSQL auto_explain](https://www.postgresql.org/docs/18/auto-explain.html)

Run from the repository root with the API environment and a new output directory for each command.

```sh
backend/services/api/.venv/bin/python tools/check_large_text_search_performance.py \
  --output .runtime/search-performance/plan-capture-repeat \
  --repeats 3 --settle-seconds 60 --vector-storage current \
  --sample-waits-and-io --capture-ranking-plans --predecessor-probe

backend/services/api/.venv/bin/python tools/check_large_text_search_performance.py \
  --output .runtime/search-performance/ranking-io-zero-repeat \
  --repeats 3 --settle-seconds 60 --vector-storage current \
  --sample-waits-and-io --ranking-io-concurrency 0
```


## Evidence and cleanup

Both disposable databases were dropped. Both runs passed the benchmark's correctness checks, including returned IDs and scores, authorization, totals and pagination. All 17 captured ranking SQL/parameter packets, expected results and the uncapped membership file matched the earlier fresh-database run byte for byte. The zero-setting trial had live plan capture off. Its ordinary post-run verification plans used the session default.

The portable JSON includes the 86 actual plan trees, summaries keyed by identity, case and round, complete timings, wait and host I/O samples, fixture settings, correctness digests and cleanup confirmations. Within `capture_at_16`, entry *i* in `actual-summary` describes entry *i* in `actual_ranking_plans`. For example, select reader `broad_not` in rounds 1 and 2 for the fast and slow word-exclusion pair. [Download the plan and telemetry capture](search-ranking-actual-plans-2026-11-18.json.gz)
