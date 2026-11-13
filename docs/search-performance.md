# Search and filtering performance contract

This contract applies to every Wathiq search, filter, count, selector and
paginated list. It supplements the authorization and pagination specifications.
The [12 November verification report](verification/search-performance-2026-11-12.md)
records the measured results, preparation and limits of the current gate.
The [13 November follow-up](verification/search-page-batching-2026-11-13.md)
records page batching, session-lock checks and the latest gate/browser timings,
including the failed intermediate run and its correction.
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
or skip candidates. Keep PostgreSQL statistics current. Stream single-use
intermediate scores instead of writing them to temporary storage; retain the
SQL boundaries that stop full vectors from entering downstream joins.

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

## Required repeatable gate

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

Search SQL, authorization, index and result-processing changes require this
gate plus focused authorization regressions. Fix failures before reporting
search performance complete.
When another search/filter flow changes, add representative and worst-case
requests for its actual endpoint. Passing Global Search timings alone do not
establish the performance of Advanced Search, a list filter or another endpoint.
