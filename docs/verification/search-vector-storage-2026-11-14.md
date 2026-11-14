# Compressed and uncompressed search vectors — 14 November 2026

## Finding

Retain the current MAIN/LZ4 chunk-vector policy. Disabling compression with
EXTERNAL storage did not improve the larger-text workload overall: every broad
content-search case had a slower median first page, and 10 responses exceeded
three seconds instead of one. Uncompressed storage also required more space.
The current policy still had one slow response; neither larger-text run passed
the strict requirement that **every** response finish within three seconds.

The user subsequently accepted the current compressed baseline as good enough
for now, given the small remaining overruns on a shared development machine.
The [consolidated benchmark history and decision](../search-performance-benchmarks.md)
records the rationale and scope. The numerical failures below remain unchanged;
the three-second test threshold still applies to future work.

This was a disposable-only experiment. Application SQL, permissions, scoring,
sorting, caps and the canonical schema were unchanged. No migration or storage
change was applied to demo. Benchmark tooling now supports an explicit storage
variant and records actual compression, storage sizes and binary-vector hashes.

## Conditions and scope

- Native Mac PostgreSQL 18.4 (Postgres.app), macOS 15.6.1, eight logical CPUs.
- Each run created a new database from the canonical schema and dropped it in
  `finally`. Four databases were created and removed, with no Docker use.
- Same deterministic fixtures, application/benchmark source hashes, cap of
  1,000, page size of 100, and three submissions per criterion.
- Same `VACUUM ANALYZE` preparation, physical-vector verification, and 60-second
  idle interval before requests. Binary-vector hashing reads the vectors before
  that interval in both variants: these are maintained-data measurements, not
  cold-disk measurements. No search warm-up was discarded.
- Default 4 MB `work_mem` and 128 MB `shared_buffers`; checksums, fsync and
  full-page writes retained. Search-scoped JIT behavior was unchanged. This
  Postgres.app build has no LLVM JIT support.
- Sequential run order: original/current, original/uncompressed,
  larger-text/uncompressed, larger-text/current. Nothing ran concurrently with
  another benchmark. Host CPU/load/memory observations were retained; security
  software and host settings were not reconfigured. A temporary `caffeinate -i`
  assertion prevented idle system sleep only while the owned coordinator ran.
- Original gate: FastAPI TestClient timings, including authentication, SQL,
  cache handling and serialization. Diagnostic files were buffered until timed
  work ended; its oracle and EXPLAIN calculations still ran between requests.
- Larger-text gate: real loopback HTTP, with oracle/EXPLAIN and diagnostic writes
  deferred until all requests ended. Neither benchmark includes WebUI rendering
  or browser automation. Both variants used the same protocol within each gate.

`current` means the current benchmark schema: MAIN/LZ4 for
`digital_component_search_chunks.search_vector`, with existing metadata-vector
policies. `uncompressed` sets STORAGE EXTERNAL on all three stored search-vector
columns **before** inserting the fixture. PostgreSQL's EXTERNAL strategy allows
overflow storage and disables compression; PLAIN would reject oversized values.
[PostgreSQL TOAST documentation](https://www.postgresql.org/docs/18/storage-toast.html).
This changes physical placement as well as compression, so it is a complete
storage-policy comparison, not an isolated decompression microbenchmark.

## Complete response results

| Dataset | Storage | Responses | Slowest first page | Slowest cached page | Responses above 3 s |
| --- | --- | ---: | ---: | ---: | ---: |
| Original | Current | 876 | 2.4953 s | 0.3469 s | 0 |
| Original | Uncompressed | 876 | 2.3169 s | 0.2855 s | 0 |
| Larger text | Current | 428 | 3.4069 s | 0.4749 s | 1 |
| Larger text | Uncompressed | 428 | 3.2691 s | 0.4131 s | 10 |

All **2,608 responses** passed correctness checks. Every cached page and denied
request passed the latency requirement. No failed response was discarded.

The original fixture's vectors were already uncompressed in the current policy:
`pg_column_compression(search_vector)` was NULL for all 51,003 aggregation
vectors, 153,009 record vectors and 306,018 chunk vectors. Both variants had
identical table sizes. Its small timing difference cannot be credited to removing
vector compression; it serves as a control for variation between runs.

### Larger-text first-page medians

These medians describe the typical result of three submissions. They do not
override the failures shown above.

| Global Search criteria | Current | Uncompressed |
| --- | ---: | ---: |
| `common OR universal`, metadata and files | 2.256 s | 2.744 s |
| `universal`, files only | 2.075 s | 2.903 s |
| `universal evidence`, files only | 2.246 s | 3.080 s |
| `universal -restricted`, files only | 1.875 s | 2.276 s |
| `"document evidence"`, files only | 2.670 s | 3.035 s |
| `universal -"boundaryalpha boundarybeta"`, files only | 2.381 s | 3.148 s |
| `common`, metadata only | 0.766 s | 0.756 s |

The current policy's only failure was the negative phrase: its three first-page
times were **2.376, 3.407 and 2.381 seconds**. In the slow response, ranking took
3.151 seconds, saving the result list 0.0035 seconds and page details 0.231
seconds. The uncompressed failures were combined search (one), broad word (one),
broad AND (three), broad phrase (two) and negative phrase (three).

The broad queries intentionally match most or all records. For example,
`universal` matches all 153,009 records in this fixture. PostgreSQL must rank the
eligible matches before keeping the best 1,000; it returns one page to the API.

## Storage and execution-plan evidence

All 180,630 larger-fixture chunk vectors used LZ4 under the current policy and
were actually uncompressed under EXTERNAL. The inherited `attcompression='l'`
attribute in the EXTERNAL arm is inactive: the measured compression of every
stored vector was NULL. Metadata vectors remained uncompressed in both arms.

| Larger-fixture chunk storage | Current | Uncompressed |
| --- | ---: | ---: |
| Main heap | 859,299,840 bytes | 189,685,760 bytes |
| Associated TOAST storage, including its index | 193,519,616 bytes | 1,079,279,616 bytes |
| Table including TOAST/FSM/VM, excluding main indexes | 1,053,081,600 bytes | 1,269,039,104 bytes |
| Main-table indexes | 116,695,040 bytes | 90,685,440 bytes |
| Total including all indexes | **1,169,776,640 bytes** | **1,359,724,544 bytes** |

Uncompressed storage used **20.5% more table space**, or **16.2% more including
all indexes**. Much more vector data moved into TOAST. The later broad-word
EXPLAIN recorded 2,232,042 total shared-buffer accesses (hits plus reads) with
EXTERNAL, versus 849,502 with MAIN/LZ4. Shared reads are PostgreSQL buffer misses,
not proof of physical disk reads; the OS can satisfy them from its cache.
Both plans wrote 8,205 temporary blocks. These are separate instrumented plans,
not timings of the earlier HTTP requests. They support the extra retrieval work
introduced by EXTERNAL; they do not isolate a percentage of latency attributable
solely to compression or to background processes.

## Correctness and reproducibility

Both fixtures contain 51,003 aggregations and 153,009 records. The larger corpus
has 151,470 single-chunk files, 1,386 ten-chunk files and 153 hundred-chunk files.
The outliers contain approximately 160,000 and 1.6 million extracted characters
per file respectively. These synthetic contents are ASCII, so those are also
approximately 160 KB and 1.6 MB of extracted UTF-8 text. No original PDF or Word
documents are generated. Matching remains chunk-local, including its documented
AND, NOT and phrase limitations.

The comparison verified every vector's binary representation and configuration
through stable, ordered SHA-256 fingerprints. It also compared all 296 original
expected/received result files, all 17 larger-text oracle files, and all 51
observed larger-text ranked lists across storage variants. Counts, exact scores,
sort order, cache contents, page order, denied access, uncapped membership and
score-producer loop checks passed. All recorded source hashes still matched the
files after the four runs. Application SQL and ranking were not changed to make
the uncompressed arm pass.

Use new output directories when repeating these commands:

```sh
backend/services/api/.venv/bin/python tools/check_search_performance.py --vector-storage current --repeats 3 --settle-seconds 60 --output .runtime/search-storage-new/01-standard-current
backend/services/api/.venv/bin/python tools/check_search_performance.py --vector-storage uncompressed --repeats 3 --settle-seconds 60 --output .runtime/search-storage-new/02-standard-uncompressed
backend/services/api/.venv/bin/python tools/check_large_text_search_performance.py --vector-storage uncompressed --repeats 3 --settle-seconds 60 --output .runtime/search-storage-new/03-large-uncompressed
backend/services/api/.venv/bin/python tools/check_large_text_search_performance.py --vector-storage current --repeats 3 --settle-seconds 60 --output .runtime/search-storage-new/04-large-current
```

Raw evidence is retained under `.runtime/search-storage-2026-11-14/`.
The [machine-readable report](search-vector-storage-2026-11-14.json) preserves
all response samples, failures, environment/source hashes, storage measurements,
cross-variant checks and database cleanup confirmations.

These runs do not erase the [earlier failures](search-score-reuse-2026-11-13.md).
The same original-fixture searches ran much faster here without application SQL
changes. Host load, cache state, the shorter documented idle interval and buffered
diagnostic writes differ from earlier conditions. Backups were suggested as a
possible source of interference but were not verified. No specific background
process has been established as the cause, and this comparison is not a guarantee
under arbitrary production load.
