# Search and filtering performance contract

This contract applies to every Wathiq search, filter, count, selector and
paginated list. It supplements the authorization and pagination specifications.
The [consolidated benchmark history and acceptance decision](search-performance-benchmarks.md)
records the user's 14 November acceptance of the current MAIN/LZ4 baseline as
good enough for now. One of 428 larger-text responses took 3.4069 seconds; that
sample remains a numerical gate failure. Further tuning of this baseline is
explicitly deferred, while future changes retain the three-second threshold,
correctness checks and reporting requirements below.

The [12 November verification report](verification/search-performance-2026-11-12.md)
records the measured results, preparation and limits of the current gate.
The [13 November follow-up](verification/search-page-batching-2026-11-13.md)
records page batching, session-lock checks and the latest gate/browser timings,
including the failed intermediate run and its correction.
The [14 November native storage comparison](verification/search-vector-storage-2026-11-14.md)
records the latest API gates: the original fixture passed, while the larger-text
fixture still had one response above three seconds with current storage and ten
with uncompressed storage. It adds no new WebUI timing claim.
The [PostgreSQL optimization lessons](postgresql-search-optimization-lessons.md)
explain the causes, successful changes, failed approaches and diagnostic method.
Read them before changing search/filter SQL; retain this contract's correctness
and measurement requirements when applying a lesson to another endpoint.

Matching, authorization, relevance scoring, ordering, counting and page
selection belong in PostgreSQL. API code validates the request and serializes
the authorized page. Never fetch a candidate collection to authorize, filter
or rank it in Python or the WebUI.

Use indexable predicates to find candidates. Resolve effective roles,
privileges, clearance, contextual grants and inherited ACL sources as shared
sets in each SQL branch and join candidates to those sets. Reuse batch visibility
logic and compare its decisions with canonical permission functions. Do not repeat those
functions for every file, chunk, metadata projection and count. Reuse parsed
queries for scoring rather than parsing per document or chunk. Enrich only the
returned page and avoid one database or HTTP request per result.

Global Search batches page attribution, snippets, parent labels and display
capabilities in `search_page.py`. Its cached-page checks reuse the same canonical
authorization sets. The general capabilities endpoint is not on the search
render path. Session authentication uses a worker thread and a lock compatible
with search-cache foreign-key references; measure concurrent request progress
as well as isolated SQL speed. `test_global_search_page_batch.py` compares page
evidence/scores with the prior implementation, `test_dashboard_set_visibility.py`
compares list/view decisions with canonical functions, and
`test_search_session_concurrency.py` exercises actual session locks and revocation.

Retain term selectivity when compiling SQL: the GIN predicate must see the
actual phrase and fixed configuration. A generic prepared plan or an opaque
scalar subquery can hide that selectivity and choose a poor join strategy.
Global ranking uses a custom plan for each submitted phrase and materializes
parsed queries for row-dependent scoring. Keep authorization working sets
limited to IDs and the fields needed for access decisions; load display data
only after selecting the page.

Common language predicates share one scan branch: selective terms can use GIN
bitmap paths, while broad terms can use one sequential scan. Keep content
identity comparisons from producing false join-cardinality estimates. Group
component and record grants once per ACL source. Pass component IDs through
authorization joins and reduce chunk vectors to scores before grouping them.
Express the single-parent hierarchy's one-source-per-aggregation rule in the
resolved permission set. Attach parsed scoring queries as scalar values so
they cannot distort the candidate joins' cardinality estimates.

For chunk scoring, use the actual permitted component count to choose retrieval:
up to the greater of 1,000 components or 5% of the component table estimate uses
one indexed ID-array lookup; larger sets use a bulk scan joined to permitted IDs.
Only the chosen path executes. This internal scan threshold does not cap results
or skip candidates. Keep PostgreSQL statistics current. Retain shared numeric
chunk scores, metadata scores and completed per-record score aggregates once per statement.
An apparently single-use CTE can still be rescanned by a nested-loop join when
row estimates are wrong. Verify actual scoring-node loop counts for selective
AND/phrase queries as well as broad queries. Keep full vectors/text out of
these materialized results and downstream joins.

`search_execution.py` disables JIT only during interactive search SQL and
restores the caller's prior setting. `work_mem` remains unchanged: 8/12/16 MB
experiments reduced spills without establishing a reliable complete-request
benefit. Tests protect lower/higher memory settings, nesting, separate
connections, Python errors, SQL rollback and transaction completion.

For future memory experiments, the optional `--probe-concurrency` diagnostic
runs after the HTTP gate. It compares two simultaneous complete ranking
statements at 4/12 MB, verifies identical results, and records elapsed SQL time
and per-backend RSS. RSS includes shared pages and must not be summed as private
allocation. This capacity diagnostic is separate from the single-client HTTP
acceptance samples; it never changes the application's memory policy.

An index's existence does not prove that a query uses it. Inspect
`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for selective and broad queries.
Sequential scans can be appropriate when most rows match. Investigate repeated
scans, excessive loops, repeated parsing, spill and unnecessary enrichment.
Never force index scans globally or add indexes without plan evidence.

The result cap bounds the saved list, not all candidate work. Authorization
must precede the cap and all eligible candidates must participate in ranking.
Never cut candidates before ranking, omit evidence, change permissions or
weaken correctness assertions to meet a timer.

Preserve the specified score formula even when an optimization looks obvious.
For example, `ts_rank_cd` can be positive for a chunk that fails a negated query.
A metadata hit still receives that component contribution under the existing
formula, if component access is allowed. Scoring only chunks found by the GIN
match would change its rank. The focused search regression suite covers this.

### Global Search ranking I/O

On a new `POST /api/v1/full-text-search` submission, `_rank_global_search` executes the combined ranking SELECT with `effective_io_concurrency = 0`. This applies once per submitted list, including a fresh submission that rebuilds an expired list. It covers all work inside that statement, including candidate matching, permissions, scoring, top results, deterministic ordering and the first-page projection. Record-only, aggregation-only and combined submissions use the same scope.

For reads governed by this setting, PostgreSQL 18 interprets zero as disabling asynchronous I/O requests. A read can still be satisfied from cache. Parallel reads can help on high-latency or high-IOPS storage, which is one reason to keep this measured exception narrow. [PostgreSQL I/O settings](https://www.postgresql.org/docs/18/runtime-config-resource.html#GUC-EFFECTIVE-IO-CONCURRENCY)

The override starts **after** branch preparation and ends immediately after the statement's rows are fetched. Cache insertion, later page enrichment, snippets, current visibility checks and cached paging use the caller's setting. Advanced Search, list filters and unrelated operations retain their existing execution policy. Reading a saved list of hits does not perform the initial ranking again.

The [ranking context manager](../backend/services/api/search_execution.py) reads the current value from the executing connection, including a caller's transaction-local value. It applies zero with transaction-local `set_config` and restores that exact value before returning control, including on a Python exception. If PostgreSQL aborts the transaction, rollback restores the setting and the original SQL error propagates. A connection already at zero needs no setting change. Other sessions keep their own values throughout. This policy ships in the API code. Normal API rollout activates it without database configuration, migrations, an environment variable or a server restart.

**Reason for the exception.** On PostgreSQL 18.4, the same plans, actual row counts and loop counts produced repeatable slow file-content rankings. On the Mac, one sequential chunk scan spent 0.322 s reading in a fast execution and 2.553 s in a slow one, despite reading slightly fewer blocks. The Linux Docker test reproduced the same four slow query/round combinations. Moving from three to four I/O workers on the Mac did not remove them. With a ranking-only zero setting, all 428 serial Mac responses met three seconds. The measurements implicate the asynchronous read path in this workload. They do not establish a single PostgreSQL defect or identify the cause of every millisecond. [Actual ranking plans](verification/search-ranking-actual-plans-2026-11-18.md)

In the paired Linux cold-cache test with two readers, zero improved throughput from 0.445 to 0.791 searches/s and reduced the worst response from 7.620 to 2.927 s. With four readers, throughput rose from 1.010 to 1.241 searches/s, but 15 of 24 responses at zero still exceeded three seconds. The database and Linux guest caches started cold; host and storage caches could still serve reads. These findings support the narrow ranking exception. They do not grant a new latency waiver or justify setting the whole cluster to zero. [Cold-cache measurements](verification/search-cold-concurrent-2026-11-19.md)

The production-path verification passed 230 regressions, all 1,524 standard responses and all 428 larger-text responses. [Verification report](verification/aggregation-record-types-phase-0.md#verification-of-the-application-ranking-override-19-november)

**Reverification.** Run both large-data gates on the ordinary application path with no ranking override argument. Compare whole responses and the complete rankings against the independent oracle. For an A/B experiment, `--ranking-io-concurrency 16` in the disposable larger-text runner selects the asynchronous control. Both arms use the same setting and restoration implementation. Retest on a new PostgreSQL version or materially different storage and concurrency before extending or removing the exception. [PostgreSQL I/O setting](https://www.postgresql.org/docs/18/runtime-config-resource.html#GUC-EFFECTIVE-IO-CONCURRENCY)

## Required repeatable gate

Audit Trail page projection is included in the ordinary gate. A focused run
uses `--audit-only --repeats 3` with a fresh `--output` directory. It keeps the
large resource, ACL and event fixture while omitting file-text chunks. Checks
cover unfiltered, record-scoped and empty searches, offsets 0/50/950, capped
counts, exact event ordering, protected values and permission-projection work
bounded to the returned page. See the
[Audit Trail loading verification](verification/audit-trail-loading-2026-11-26.md)
for the cause, rejected join plan, Demo read-only comparison and regressions.

Mailbox text filters use the same document fixture with 2,400 messages per
folder and caller. The mailbox run measures subject, body, and linked-content
filters, including combined criteria, denied resource access, and cursor pages
past 1,000 items. It records exact expected counts and row IDs, complete
request timings, and executed SQL plans.

```sh
backend/services/api/.venv/bin/python tools/check_search_performance.py \
  --mailbox-only --output .runtime/search-performance/mailbox-filters-new --repeats 3 --settle-seconds 30
```

Use `--mailbox-page-size 50` to check the upper bound of **Messages per
page**. The mailbox workload includes unfiltered pages and applies the
chosen page size to the filtered requests and executed plans.

This run also checks Outbox recipient totals and bounded recipient paging for
one sent message with 2,000 deliveries. It records owner and denied requests
for the reading pane, first, last, and empty pages, along with executed query
plans and the expected delivery, read, and completion counts.

Full-text scoring and page-evidence changes must pass both the original gate
below and the richer-text gate:

```sh
backend/services/api/.venv/bin/python tools/check_large_text_search_performance.py \
  --output .runtime/search-performance/large-text-new --repeats 3 --settle-seconds 60
```

This uses the configured PostgreSQL cluster to create a new disposable database;
it does not test the configured persistent database. On the Mac, run against the
native PostgreSQL cluster when requested. The optional Linux wrapper below can
also run this gate with `--workload large-text`; do not conflate its timings with
native-cluster measurements.

For a timing investigation, add `--sample-waits-and-io` to the larger-text
command. A separate connection samples active client backends in the disposable
database approximately every 100 ms. Each sample records the wait event and
whether the backend is executing the ranking statement, alongside cumulative
host disk bytes read and written. The runner buffers the samples in memory and
writes `waits-and-host-io.jsonl` after measurement. Join sample times to
the request and stage timestamps. A null wait means PostgreSQL reported no
wait at that instant. Disk byte differences include all host processes.

The richer corpus in `tools/search_large_text_fixture.py` has 51,003 aggregations,
153,009 records/files and 180,630 chunks: 151,470 single-chunk files of about
4,000 extracted characters, 1,386 ten-chunk files of about 160,000 characters,
and 153 hundred-chunk files of about 1.6 million characters. Vocabulary and
probe placement are deterministic. These are extracted-text sizes, not original
PDF/DOCX sizes or a claim about customer document distributions. Simple, English
and Arabic configurations are represented. Each fixture file uses one configuration.
Setup inserts this corpus directly instead of first writing and discarding the
original small-vector chunks. It still completes the same `VACUUM ANALYZE`
maintenance before measurements; the final data and expectations are unchanged.
Template vectors are copied through an empty-vector concatenation to obtain
fresh datums; otherwise PostgreSQL may preserve the template's old compression
despite the destination policy. The gate verifies that all 180,630 large fixture
vectors actually use the canonical MAIN/LZ4 policy. This is a physical-storage
check; expected logical values, IDs and scores are independent of compression.

Both runners also accept `--vector-storage current|uncompressed` for an explicit
disposable-only comparison. The default `current` retains the canonical schema:
MAIN/LZ4 on chunk vectors and the existing metadata-vector policies. The
`uncompressed` arm sets EXTERNAL storage on the three stored search-vector
columns before seeding. EXTERNAL disables compression while preserving overflow
support; unlike PLAIN it can store vectors larger than a heap page. No persistent
database, application SQL or canonical storage setting is changed by this flag.
Keep the same fixtures, response limit, repeats, idle interval and application
source hashes in both arms. Compare all binary-vector fingerprints and exact
returned IDs/scores, and record actual compression plus heap/TOAST/index sizes.
EXTERNAL can change physical placement as well as compression, so report this
as a complete storage-policy comparison rather than isolated decompression cost.

`tools/check_large_text_search_performance.py` creates a new database from the
canonical schema and drops it in `finally`. The Linux wrapper uses disk-backed
PostgreSQL data/WAL with checksums/fsync enabled, creates no Docker volumes,
and removes its owned container even after failure. Never reuse an output
directory or hide failed attempts. The configured database supplies connection
details for the administrative database only; it is never tested or modified.

The 17 cases exercise broad/selective words, AND, OR, exclusions, quoted phrases,
empty results and the approved multi-chunk limitations. Selective AND is tested
with both file-only and combined metadata/file sources, because the additional
score join can change the plan. The gate uses real loopback
HTTP with a 1,000-result cap and 100-row pages. It verifies every page, the full
saved ranking, exact uncapped text membership, counts, ordering, scores, denied
access and cache reuse. PostgreSQL calculates the independent score oracle.
Every measured reader/denied search must take at most three seconds, including
the first request and all subsequent pages; warm-up samples are not discarded.
EXPLAIN runs after timing against the captured complete API ranking statement,
including its outer page projection, and asserts the scored-chunk batch executes
at most once. Source hashes, storage/compression details and read waits accompany
the plans. Host CPU/load/memory observations record possible contention without
changing antivirus settings. Timings, captured SQL and host observations are
buffered in memory; diagnostic files and independent oracle SQL are produced
only after all timed HTTP requests. This avoids measurement-related file scans
or oracle warming between requests. Oracle/EXPLAIN time and browser work are excluded.

Chunk-local matching is an explicit product choice, not a performance-test
shortcut. Tests retain the limits in
[Full-Text Search §10.1.1](../specs/full-text-search.md#1011-matching-scope-and-multi-chunk-limitations).
Do not add cross-chunk matching or alter ranking to meet the latency target.

Run from the repository root using the API environment:

```sh
backend/services/api/.venv/bin/python tools/check_search_performance.py
```

The runner creates a uniquely named disposable PostgreSQL database, initializes
the canonical schema and reference data, and seeds deterministic synthetic
content. It completes bulk loading with `VACUUM ANALYZE`, following the existing
dashboard benchmark's fixture setup. Checksums, WAL and other durability
settings stay unchanged. It never runs tests against the configured persistent database. Its
connection configuration is used only to create/drop the owned database through
the PostgreSQL administrative database.

The fixture contains 51,003 aggregations, 153,009 records, 153,009 components and
306,018 chunks across simple, English and Arabic configurations. The reader
uses explicit ACL grants; denied-access checks use a separate signed-in user.
The result cap is 1,000 and page size is 100. Criteria cover empty matches,
rare words, phrases, AND, OR, exclusion, Arabic, filenames, file content and
broad metadata/content/combined matches.

| Criterion | Exact authorized matches before the cap |
| --- | ---: |
| Absent word | 0 |
| Rare word | 50 |
| Phrase / AND | 160 each |
| OR | 450 |
| Exclusion | 80 |
| Arabic | 200 |
| Filename | 23 |
| File content | 73 |
| Full text plus an ID range | 474 |
| Broad metadata | 204,012 |
| Broad file content | 153,009 |
| Broad combined | 204,012 |

The denied identity has the same global privileges and clearance but no resource
grants; every criterion must return zero. Repeated terms create different score
tiers, with ties resolved by type and ID. Every record has two indexed chunks
so the oracle also checks that multiple chunk matches produce one record hit.

The independent oracle computes matching IDs and exact cover-density scores
from seeded evidence without production query builders. Fixed expected counts
guard against fixture/oracle drift. Every cached ID/score and every returned
page must equal the oracle, ordered by score descending, type ascending, ID
ascending. Counts, truncation, page boundaries and denied access are checked.

Every measured API response must finish within **3 seconds**, with three
submissions per criterion by default and all pages checked. One violation
fails the gate; averages or medians cannot hide it. Timings cover the real
FastAPI request pipeline, authentication, SQL, cache writes, attribution and
JSON serialization through TestClient. They exclude browser rendering and
network transit. Record the environment; this local regression gate is not a
guarantee for arbitrary hardware or concurrent production load. Do not weaken
the threshold to pass.

The broadest combined query runs first, before any search or oracle calculation
warms the corpus. Every first submission is timed before its oracle is computed.
These are measurements of a maintained database after bulk-load setup, not a
cold-disk or freshly unvacuumed import SLA. A diagnostic first scan before that
maintenance generated 344 MB of full-page WAL images for hint-bit updates on
new rows; its full API request took 8.61 seconds. PostgreSQL documents that
[checksums require WAL logging of these updates](https://www.postgresql.org/docs/18/runtime-config-wal.html#GUC-WAL-LOG-HINTS).
Retain this distinction in performance reports; do not describe maintained-data
measurements as proof of a three-second bound immediately after any bulk import.

Artifacts in `.runtime/search-performance/<run>/` retain dataset/environment
details, source hashes, expected and received ranked lists, all latency samples,
failures and execution plans. Cleanup runs on
success, failure and ordinary interruption and writes `cleanup.json`. Creation
or cleanup errors fail visibly. Never reuse or leave a benchmark database.

The original runner now buffers diagnostic artifact writes until its timed work
finishes and records host load/CPU/memory using the same monitor as the richer
runner. Its independent oracle and EXPLAIN calculations still occur between
timed requests; this protocol differs from the richer runner's fully deferred
oracle/plan checks. Use the same protocol in both storage arms. Avoid unrelated
checks or other benchmark processes while collecting response times.

Search SQL, authorization, index and result-processing changes require this
gate plus focused authorization regressions. Fix failures before reporting
search performance complete.
When another search/filter flow changes, add representative and worst-case
requests for its actual endpoint. Passing Global Search timings alone do not
establish the performance of Advanced Search, a list filter or another endpoint.

## Shared tab result lists (13 November 2026)

Global Search, Advanced Search (including saved searches), and aggregation/record
collection filters share one PostgreSQL UNLOGGED cache slot per login session and
NiceGUI `client.tab_id`, additionally checked against the signed-in user. Wait for
the framework connection before reading this ID. Reuse it across reloads and
verify duplicated-tab isolation; never invent a per-page UUID.

Each screen preserves its own submitted query and returned list ID. Reusing a
slot requires matching list ID and fingerprint (search type/endpoint, resource,
criteria, sorting, display filter, saved version, cap/idle setting versions).
A different screen's submission replaces the slot. Paging an older search
silently rebuilds it and serves its requested page. Do not use editable draft
controls for that rebuild. Mutation refreshes and explicit submissions rerun;
permission checks and current display details are never cached. Language-specific
rendering remains per request; these lists contain IDs/scores, not translated UI.

All four flows use the administrator cap (default 1,000, maximum 5,000). Selectors,
hierarchy branches and unrelated domains retain their separate contracts and
must not replace this slot. Existing cache idle/cleanup settings now govern all
four flows; no new environment variables are required. Migration 111 renames
`global_search_results` to `search_results_cache` in place, preserving entries,
UNLOGGED storage, indexes and the login-session cascade. Login expiry,
revocation/deletion, idle expiry, settings changes and UNLOGGED-table loss retain
the existing invalidation rules. See the Advanced Search specification for the
complete contract and API recovery behavior.

The shared-cache extension in `tools/search_cache_performance.py` runs through
actual Advanced Search, saved-search execution and ordinary collection-filter
routes. For each resource,
it compares the stored ordered IDs/scores and every returned page with independent
SQL/reference fixture expectations, for allowed and resource-denied callers.
Cases cover broad combined/file/metadata text, rare and empty text, ordinary
structured criteria, descending collection filters, inherited holds, null inherited
locations, and inherited aggregation retention. Each case repeats three times by
default with every response held to the same three-second ceiling. Execution plans
and separate `*-tab-cache-results.json` files accompany the Global Search evidence.
Every valid Next request must retain the same list ID; the gate fails if it
unexpectedly rebuilds the search. Record and aggregation filters have identical
cache-reuse rules.

For a Linux PostgreSQL comparison using an existing local PostgreSQL 18 image:

```sh
backend/services/api/.venv/bin/python tools/run_linux_search_performance.py \
  --image LOCAL_POSTGRES_IMAGE_ID --repeats 3 \
  --output .runtime/search-performance/linux-shared-tabs
```

The wrapper never pulls images. It starts a unique container and runs the same
gate against a new database, then drops the database and removes its container.
PGDATA, WAL and temporary query files use the container's Linux disk layer, not
RAM storage. A tiny unused tmpfs masks the image's declared volume path so Docker
does not create an anonymous volume. Checksums, fsync and full-page writes stay
enabled. A sibling `*-linux.json` records image identity and cleanup; the API
test client still runs on the host, so disclose this split environment and
Docker's allocated resources when reporting timings.

Both runners accept an optional `--settle-seconds N` (default 0, maximum 300)
to leave a declared idle interval after bulk-load maintenance. This can separate
import-triggered host background work from measured searches. No search or oracle
runs during the interval, the first request is still measured, and no failing
sample is discarded. Report the exact interval alongside results; a settled run
does not establish latency immediately after an import or under arbitrary host
contention. Previously failed runs remain evidence even if a later run passes.
