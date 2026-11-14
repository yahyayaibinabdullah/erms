# Search performance benchmarks and acceptance — 14 November 2026

## Decision

The user accepted the current search performance as **good enough for now** on
14 November 2026 and requested an end to this optimization round. Retain the
current compressed MAIN/LZ4 policy for file-text vectors. The uncompressed
experiment is not adopted. Permissions, matching, scores, ranking, result caps
and chunk-local matching semantics remain unchanged.

This is an explicit acceptance of the measured baseline with occasional latency
exceptions on a shared MacBook, **not a claim that every three-second test
passed**. The latest compressed larger-text run had one response at 3.4069
seconds; the uncompressed run had ten above three seconds, maximum 3.2691.
Both passed every correctness check. The user accepted the small overruns in
the context of a machine also running unrelated applications and jobs.

The three-second test threshold stays unchanged. Existing failures remain in
the reports and machine-readable evidence. Further optimization of this
baseline is deferred by this decision; future changes still require the
documented correctness and performance tests and honest reporting of failures.
This acceptance does not establish a production concurrency or cold-disk SLA.

## Latest comparison: compressed versus uncompressed

Four fresh disposable databases were tested sequentially on native Mac
PostgreSQL, with identical application SQL and fixture contents. Each criterion
was submitted three times, with a 1,000-result cap and 100-row pages. Every page
was checked. These are complete API response times, not just SQL execution.

| Fixture | Storage policy | Responses | Maximum first page | Maximum cached page | Responses over 3 s |
| --- | --- | ---: | ---: | ---: | ---: |
| Original | Current | 876 | 2.4953 s | 0.3469 s | 0 |
| Original | Uncompressed | 876 | 2.3169 s | 0.2855 s | 0 |
| Larger text | Current, compressed | 428 | 3.4069 s | 0.4749 s | 1 |
| Larger text | Uncompressed | 428 | 3.2691 s | 0.4131 s | 10 |

All **2,608 responses passed correctness checks**. Every cached page and denied
request met the latency target. Both original-fixture runs passed the strict
gate; both larger-text runs failed it numerically. The comparison completing
successfully does not convert those two latency failures into gate passes.

In the retained current-storage runs, 876/876 original-fixture responses and
427/428 larger-text responses were within three seconds. Counts include cached
pages and denied requests; they are not a first-page failure probability.

The compressed run's sole overrun was the file-only negative phrase
`universal -"boundaryalpha boundarybeta"`. Its first-page times were 2.376,
3.407 and 2.381 seconds. The slow sample spent 3.151 seconds ranking, 0.0035
seconds saving the list and 0.231 seconds retrieving page details. Saving the
cache was not the main cost.

### First-page results by broad criterion

Medians below describe three submissions per criterion. The maximums and
failures above remain part of the decision; medians do not replace them.

| Global Search criterion | Current compressed | Uncompressed |
| --- | ---: | ---: |
| `common OR universal`, metadata and file text | 2.256 s | 2.744 s |
| `universal`, file text only | 2.075 s | 2.903 s |
| `universal evidence`, file text only, AND | 2.246 s | 3.080 s |
| `universal -restricted`, file text only | 1.875 s | 2.276 s |
| `"document evidence"`, file text only | 2.670 s | 3.035 s |
| `universal -"boundaryalpha boundarybeta"`, file text only | 2.381 s | 3.148 s |
| `common`, metadata only | 0.766 s | 0.756 s |

The uncompressed overruns were combined search (one), broad word (one), broad
AND (three), broad phrase (two) and negative phrase (three). All six broad
content-search cases had slower first-page medians without compression.

### Storage cost

For the larger fixture, all 180,630 file-text vectors were actually LZ4-compressed
under the current policy and uncompressed under the experimental EXTERNAL
policy. Ordered binary fingerprints confirmed identical vectors and text
configurations. Metadata vectors were uncompressed in both variants.

| Larger-fixture chunk table | Current compressed | Uncompressed |
| --- | ---: | ---: |
| Table including TOAST, excluding main-table indexes | 1,053,081,600 bytes | 1,269,039,104 bytes |
| Total including all indexes | 1,169,776,640 bytes | 1,359,724,544 bytes |

Uncompressed storage used **20.5% more table space**, or **16.2% more including
indexes**. It also moved more data into overflow storage. This compares complete
storage policies, including physical placement; it does not isolate the CPU
cost of decompression.

The original fixture's small vectors were already physically uncompressed in
both variants, with identical table sizes. Its slightly faster uncompressed
run therefore does not demonstrate a benefit from removing compression.

### Why this is acceptable for now

- Correctness held across all four runs: exact counts, IDs, scores, order,
  saved rankings, page boundaries and permission expectations. Storage variants
  also agreed on every binary vector and configuration.
- The retained policy passed all 876 responses in the original fixture. Its
  larger-text run had one modest overrun out of 428, rather than sustained
  multi-second overruns across broad searches.
- The broad cases deliberately match most or all 153,009 records. PostgreSQL
  must consider eligible candidates before keeping the best 1,000. The cap
  limits saved results, not all matching and ranking work.
- Cached pages remained fast: the latest compressed larger-text maximum was
  0.4749 seconds, including current permission checks and page details.
- Uncompressed storage did not deliver a consistent speed advantage. It had
  more overruns, slower broad-content medians and a larger storage footprint.
- These measurements came from a shared development laptop. Variation is
  expected under competing work, and the user explicitly accepted these small
  remaining overruns rather than requiring further tuning on this machine.

The last point is a reason for the acceptance decision, not proof that every
slow sample was caused by another process. Backups were suggested but not
verified. Neither backups nor Microsoft Defender were isolated as the cause.

## Dataset and measurement boundaries

Both fixtures contain **51,003 aggregations and 153,009 records/files**. The
original has 306,018 small text chunks. The larger-text fixture has:

| Files | Chunks per file | Approximate extracted text per file |
| ---: | ---: | ---: |
| 151,470 | 1 | 4,000 characters |
| 1,386 | 10 | 160,000 characters |
| 153 | 100 | 1.6 million characters |

These are synthetic ASCII texts: the outliers contain about 160 KB and 1.6 MB
of extracted UTF-8 text. They are not measurements of original PDF/Word files.
The larger fixture totals 180,630 chunks and is mostly single-chunk files.

The original gate covers Global Search, Advanced Search, saved searches and
record/aggregation filters, including structured criteria and field sorting.
The richer gate covers 17 full-text cases: broad/selective terms, AND, OR, NOT,
phrases, no matches, denied access and the approved multi-chunk limitations.
The [score-reuse report](verification/search-score-reuse-2026-11-13.md#repeatable-workload)
lists the exact criteria and uncapped expectations. The combined broad query
matches 204,012 aggregations plus records; file-only `universal` matches all
153,009 records. An Advanced Search “All” group containing one text condition
does not make that condition narrower.

The latest comparison used PostgreSQL 18.4 on macOS 15.6.1, eight logical CPUs,
4 MB `work_mem` and 128 MB `shared_buffers`. Checksums, fsync and full-page writes
remained enabled. Each database received `VACUUM ANALYZE`, vector verification
and a 60-second idle interval before timing. Verification reads the vectors:
these are maintained-data measurements, not cold-cache or unvacuumed-import
measurements. No measured first search or slow sample was discarded.

Original-gate timings use FastAPI TestClient; oracle queries and EXPLAIN still
run between requests, while artifact writes are deferred. Richer-gate timings
use loopback HTTP; oracle queries, EXPLAIN and artifact writes all run afterward.
Neither includes browser rendering or automation overhead. The two storage
variants use the same protocol within each gate. Source hashes, host telemetry,
storage details and cleanup confirmations accompany the results.

All four latest databases were dropped. No test suite ran against demo and no
uncompressed-storage change was applied there. This documentation acceptance
does not apply migration 112 or restart the local stack.

## Earlier benchmark history

These were successive changes and diagnostics under varying conditions, not
one controlled before/after experiment. Preserve them when evaluating later
changes; a favorable run does not erase an unfavorable one.

### Initial SQL, paging and shared-cache work

| Stage | Measured outcome | Evidence and interpretation |
| --- | --- | --- |
| 12 November, maintained original fixture | 192 responses passed; maximum 2.8381 s; later pages at most 0.4149 s | [Initial report](verification/search-performance-2026-11-12.md); Global Search coverage |
| Same investigation, unmaintained bulk-load diagnostic | First API request 8.6123 s; repeats about 2.40 s | Separate plan recorded 344 MB of full-page WAL images from visibility updates; post-load maintenance matters |
| 13 November, page batching | Intermediate maximums 2.9960 s, then a failed 3.1668 s; final 192 responses passed, maximum 2.7375 s | [Batching report](verification/search-page-batching-2026-11-13.md); redundant file matching removed; later pages at most 0.4848 s |
| Shared-cache native trials | One-repeat diagnostic maximum 2.6764 s; later runs failed at maximums 5.8768 s and 6.3591 s; another attempt failed at 3.0151 s before cancellation | [Complete trial ledger](verification/shared-search-cache-2026-11-13.md#performance-evidence), including an earlier cancelled inherited-value scan |
| Shared-cache Linux diagnostic with JIT | Broad requests 16.18–16.61 s | Plans identified 5.51 s record JIT and 4.50 s aggregation JIT; search-scoped JIT disabling retained |
| Shared-cache Linux follow-up | 15 responses over 3 s; maximum 9.4305 s | Further repeated candidate joins and unnecessary scoring corrected; separate port-readiness failure produced no timing sample |
| Shared-cache Linux final | 876 responses passed; maximum 2.3503 s | Global, Advanced, saved execution and collection filters; slowest later page 0.5254 s |
| Later native original-fixture run | 876 responses; 10 over 3 s; maximum 8.906 s | [Native follow-up](verification/search-score-reuse-2026-11-13.md); interleaved diagnostics and concurrent host work limit attribution |

The latest original-fixture control then passed all 876 responses at a maximum
of 2.4953 seconds without changing application SQL. This supports investigating
runtime and measurement conditions when timings vary; it does not identify one
external process as the cause of the earlier 8–9 second responses.

### Richer-text optimization attempts

The [full dated report](verification/search-score-reuse-2026-11-13.md#retained-attempts)
preserves plans, conditions, correctness and cleanup. Attempts 01–06 used Linux
PostgreSQL in Docker; 07 onward used native Mac PostgreSQL. Samples increased
as coverage expanded. The invalid attempt is retained as such.

| Attempt | Responses | Over 3 s | Maximum | Condition |
| --- | ---: | ---: | ---: | --- |
| 01 | 143 | 14 | 10.442 s | Initial numeric-score reuse, original storage |
| 02 | 143 | 11 | 9.697 s | MAIN storage trial |
| 03 | 143 | 11 | 9.648 s | MAIN/LZ4 requested, mixed actual compression |
| 04 | 143 | 4 | 3.745 s | Fewer headlines, before metadata-score reuse |
| 05 | 154 | 11 | 20.045 s | Larger TOAST target; separate plan-capture failure |
| 06 | 154 | 8 | 6.071 s | Metadata-score reuse, mixed compression |
| 07 | 154 | 9 | 7.940 s | Native Mac, original storage |
| 08 | 428 | 14 | 6.816 s | Native MAIN/LZ4 requested, mixed compression |
| 09 | 428 | 1 | 3.483 s | All 180,630 vectors verified as LZ4 |
| 10 | 428 | 2 | 3.393 s | Additional language-specific GIN indexes, not adopted |
| 11 | 428 | 12 | 7.622 s | Additional indexes and 8 MB memory trial, not adopted |
| 12 | 428 | 1 | 3.105 s | Canonical MAIN/LZ4, original indexes, 4 MB memory, 300-second idle |
| 13 | 0 valid | — | — | Login expired after scheduling/suspension gap; no ranking sample |
| 14 | 428 | 2 | 3.325 s | Search-only 12 MB trial, removed |
| 15 | 428 | 4 | 3.797 s | Retained code and 4 MB memory, all correctness checks passed |

The latest four storage-comparison runs appear separately above. Their results
do not replace this history. In particular, attempt 15's cached pages all passed
but four first pages did not; the later improvement cannot be attributed solely
to a storage change because that policy was already retained.

## What worked and what was not retained

The [optimization lessons](postgresql-search-optimization-lessons.md) provide
the query-plan detail and constraints for future agents. The durable findings are:

- Reuse shared role/access calculations; putting a repeated permission function
  inside SQL alone does not make it efficient.
- Expose selective predicates to existing GIN indexes, reuse parsed queries and
  combine common-language scans. A broad sequential scan can be appropriate.
- Keep intermediate rows narrow and choose bulk chunk retrieval for broad
  candidate sets instead of 153,009 individual file lookups.
- Materialize numeric chunk, per-record and metadata scores once. A mistaken
  one-row estimate had caused an entire 1,200-chunk batch to be scored 1,200
  times: 1,440,000 calculations instead of 1,200.
- Batch page checks and display capabilities, generate only needed headlines,
  and keep login authentication from blocking request completion. Paging reuses
  the saved list while checking current permissions.
- Disable JIT only during interactive search and restore connection settings.
  Native Mac PostgreSQL without LLVM did not expose the Linux compilation cost.
- Verify actual compression. A changed column policy can leave old or copied
  compressed values untouched; the fixture and migration preserve vector values
  while creating the intended physical representation.
- Forced index scans, extra language-specific indexes, larger query-memory
  settings and parallel-query rewrites did not establish a reliable complete
  response improvement. They were not retained. EXTERNAL storage was also not
  adopted. The more complicated mixed single/multi-chunk matcher was rejected;
  the approved chunk-local matching limitations remain explicit.

## Browser timings are a separate measurement

The last paired demo WebUI measurements in this series were taken after page
batching on 13 November. They are not a fresh WebUI test of the 14 November
storage comparison. Five first-page and five Next actions were measured for
each phrase, with ten rows per page. These are median browser click-to-render
times, excluding automation command overhead:

| Query | First page | Next |
| --- | ---: | ---: |
| `demo` (296 results) | 177.5 ms | 108.1 ms |
| `demo OR test OR record OR file OR وثيقة OR ملف OR a OR the` (1,000 capped) | 439.5 ms | 176.1 ms |

Every measured Next read the cache; none rebuilt the full ranking. The
[paired report](verification/search-page-batching-2026-11-13.md#demo-webui-timing)
also preserves ranges, initial slower samples, HTTP/stage times and separate
automation durations. The earlier roughly one-second automation-command timings
must not be reported as application or database latency.

## Evidence, reproduction and future work

- [Latest storage report and reproduction commands](verification/search-vector-storage-2026-11-14.md)
  and [all 2,608 response samples plus checks](verification/search-vector-storage-2026-11-14.json).
- [Score-reuse history and diagnostics](verification/search-score-reuse-2026-11-13.md)
  and [machine-readable history](verification/search-score-reuse-2026-11-13.json).
- [Shared-cache evidence](verification/shared-search-cache-2026-11-13.md)
  and [machine-readable results](verification/shared-search-cache-2026-11-13.json).
- [Performance contract and fixture commands](search-performance.md), including
  disposable-database ownership, expected criteria, exact oracles and cleanup.

Detailed local artifacts for the latest comparison are in
`.runtime/search-storage-2026-11-14/`; the repository reports retain portable
measurements so the decision does not depend solely on that gitignored folder.
Historical machine-readable failure statuses describe their dated runs and
remain unchanged by this acceptance.

For a future capacity decision, measure on the intended deployment hardware
with representative concurrency, storage and data distribution. Revisit tuning
if broad first pages show sustained regressions, cached pages become slow, or
workload changes make this baseline unrepresentative. Keep correctness and the
three-second test threshold intact; do not rerun until a favorable sample hides
a failure. Any new acceptance exception requires its own explicit decision.
