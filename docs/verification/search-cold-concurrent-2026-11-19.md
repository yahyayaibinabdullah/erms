# Cold-cache full-text ranking under concurrency, 19 November 2026

Setting `effective_io_concurrency = 0` for ranking raised aggregate cold-batch throughput by 78% with two readers and 23% with four. It finished first in four of six paired batches at each load. With four readers, 15 of 24 responses still exceeded the three-second requirement at zero, compared with 17 of 24 at 16. No deployment change was made.

## Response times and throughput

Each row aggregates six cold-start batches. Times are complete first-page HTTP responses for a new search. Throughput is completed searches divided by the sum of the six batch durations, from first request sent to last response received. Login, cache resets and correctness checks are outside that interval. The p95 uses nearest rank and is descriptive at these sample sizes.

| Simultaneous users | Ranking I/O concurrency | Requests | Min (s) | Median (s) | p95 (s) | Max (s) | Above 3 s | Searches/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 0 | 12 | 1.744 | 2.391 | 2.927 | 2.927 | 0 | 0.791 |
| 2 | 16 | 12 | 1.579 | 3.462 | 7.620 | 7.620 | 6 | 0.445 |
| 4 | 0 | 24 | 2.096 | 3.075 | 3.481 | 3.590 | 15 | 1.241 |
| 4 | 16 | 24 | 2.470 | 3.242 | 5.395 | 5.460 | 17 | 1.010 |

## Same data and same query mix

This benchmark used one freshly created ARM64 Debian PostgreSQL 18.4 database in Docker Desktop on the Mac, with eight logical CPUs and 7.65 GiB allocated to Linux. It contained 51,003 aggregations, 153,009 records and 180,630 MAIN/LZ4 chunks. The driver verified actual compression and the corpus fingerprints. The three file-content searches were `universal -restricted`, `universal -"boundaryalpha boundarybeta"`, and `"document evidence"`. The paired settings used the same users and same search assignments, with the order counterbalanced. Each query appeared equally often at each setting and concurrency level.

Each reader signed in with a separate account and held the benchmark reader role. Each request used a fresh search tab, the existing ranking, a 1,000-hit cap and a 100-hit first page. The first-page IDs and scores, full cached ranking, cache ownership, totals and truncation passed the independent oracle for every response. The expected results also matched the previous Linux experiment. PostgreSQL used three I/O workers, a cluster default of 16, 128 MB shared buffers, and 4 MB work memory. The two benchmark API processes used the same transaction-local setting and restoration code for both 0 and 16. The application and cluster defaults were preserved.

## Cold state and concurrency evidence

Before each batch the driver checkpointed the private cluster, evicted PostgreSQL shared buffers, and advised the Linux kernel to discard pages for files belonging to the disposable database. It then checked the PostgreSQL buffer cache and the Linux page residency of the records, aggregations, component and search tables, their indexes and TOAST files. All 24 batches began with zero resident corpus pages in both layers. Searches could share pages loaded by another reader during a batch. The Linux VM’s underlying macOS and device caches were outside the reset. These are cold-start batch throughput figures for an already-running service. A sustained warm workload or different production storage can behave differently.

The PostgreSQL activity sampler observed all requested rankings executing together in every batch. Maximum HTTP start spread was 3.8 ms. Linux cgroup block reads were approximately 1.07 GiB per batch. Device-read deltas for the whole Mac varied from 2 MiB to 1,150 MiB. Most batches recorded under 30 MiB at the host, so these data cannot establish the same advantage on physically cold production storage. Both the database drop and container removal were verified.

The [portable capture](search-cold-concurrent-2026-11-19.json.gz) contains all 72 response times, all batch timings, cache checks, I/O counters, overlap and correctness evidence. The [raw run](../../.runtime/search-performance/cold-concurrent-01/) retains the independent oracle and generated ranking SQL.

## Reproduction

Use the API virtual environment and the existing ARM64 image recorded in the capture. Run from the repository root with a new output path.

```sh
backend/services/api/.venv/bin/python tools/run_linux_search_performance.py \
  --image sha256:a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636 \
  --workload cold-ranking --io-workers 3 --repeats 6 --settle-seconds 60 \
  --output .runtime/search-performance/cold-concurrent-repeat
```
