# PostgreSQL search optimization lessons

This records the Wathiq Global Search investigation of 12 November 2026 on
PostgreSQL 18.4. Read it before optimizing a search or filter. The
[performance contract](search-performance.md) defines the requirements; the
[verification report](verification/search-performance-2026-11-12.md) records
the final measurements and their limits.

Several problems compounded each other: repeated permission work, repeated
language scans and parsing, misleading row estimates, and large intermediate
rows. A separate first-scan cost came from PostgreSQL updating freshly loaded
rows' visibility information and writing recovery logs. There was no single
missing index or universal planner setting that explained everything.

These are measured examples and diagnostic methods, not instructions to copy
every CTE, index, scan threshold or `OFFSET 0` into another query. Recheck the
actual endpoint, data distribution, permissions and PostgreSQL version.

## Causes and approaches that worked

### 1. Avoid repeated permission computation across the candidate set

Putting permission functions inside SQL did not make repeated execution cheap.
The same roles, privileges, clearance and ACL rules could still be recalculated
for each record, file, chunk and projection.

The useful change was to calculate shared permission sets and join candidates
to them. Record and component grants were grouped by ACL source. Access still
precedes the result cap, and component evidence still requires component-view
permission even when the record also matches metadata.

Use canonical permission functions as a correctness reference. Compare allowed
and denied decisions, inherited grants, contextual roles, clearance and retained
resources. An optimization that grants more access is a defect, regardless of
its timing. The shared implementation is in
[`dashboard_visibility.py`](../backend/services/api/dashboard_visibility.py).

### 2. Language support was not inherently the expensive part

Two implementation choices multiplied the work:

- Separate common-language branches could each scan the entire chunk table for
  a broad term. Combining fixed-configuration predicates with `OR` allowed one
  broad scan while retaining indexed paths for selective terms.
- A row-dependent `websearch_to_tsquery(configuration, phrase)` reparsed the
  same phrase for many documents/chunks. Parsed queries are now shared for
  scoring, with each row still using its correct text configuration.

Keep the actual phrase and a fixed configuration visible in candidate predicates.
An intermediate attempt to reuse an opaque parsed value there hid useful term
selectivity. Reuse parsed values for scoring without obscuring matching estimates.
Do not switch everything to the `simple` configuration to save work: that changes
matching and ranking. English, Arabic and uncommon installed configurations have
correctness coverage.

### 3. Verify index use, and distinguish selective from broad searches

The existing metadata/chunk GIN indexes were useful when the SQL exposed an
indexable predicate. Their existence alone did not prove that the query used
them. Filename matching also needed its own expression GIN index; fallback
configuration branches needed small partial indexes to avoid unnecessary scans.
Migration 109 contains those additions.

A term matching almost every file can be cheaper to process with a bulk scan
than repeated indexed lookups. The final chunk-scoring query chooses retrieval
from the actual permitted component count: indexed ID-array access for small
sets, bulk retrieval for larger sets. Only one path executes. The current
cutover is the greater of 1,000 components and 5% of the component table estimate.
That is a measured implementation choice, **not a result cap or a universal
tuning constant**. Statistics must remain current, and another workload may
need a different choice.

GIN narrows matches; it does not eliminate subsequent permission, scoring and
ordering work. PostgreSQL's [text-search index documentation](https://www.postgresql.org/docs/18/textsearch-indexes.html)
explains the information GIN stores and when row rechecks are required.

### 4. Bad estimates were often consequences of the query shape

One executed aggregation plan estimated about **4.23 billion** recursive-source
rows where **51,003** existed. A later join estimated about **1.40 billion** rows
and used **2,048 hash batches**. Other plans went in the opposite direction:
they underestimated eligible files and performed **153,009 separate chunk index
scans**.

The corrective changes included:

- Expressing the hierarchy's existing one-per-aggregation source rule explicitly.
- Removing a redundant target filter followed by another join to the same ACL
  targets; the combination compounded selectivity estimates.
- Using compact Boolean ACL-source fields and shared membership checks.
- Keeping correlated content-identity comparisons from being treated as
  unrelated, highly selective join conditions.
- Passing parsed scoring queries as scalar values rather than a cross join
  that produced a misleading intermediate estimate.
- Choosing small-set or bulk chunk retrieval using the actual permitted set
  when ordinary statistics could not describe caller-specific ACL selectivity.

These observations do not establish a PostgreSQL planner bug. The planner was
making cost decisions from estimates that did not capture the relationships in
our SQL. Fix the representation and validate the resulting plan before changing
server-wide planner settings. Also distinguish an executed problem from an
unused branch: some alarming estimates in record plans had `Actual Loops = 0`.

Global ranking executes with `prepare=False` so the driver does not switch this
term-sensitive statement to a generic prepared plan. This is a targeted choice,
not a ban on prepared statements. PostgreSQL distinguishes
[generic and parameter-specific plans](https://www.postgresql.org/docs/18/sql-prepare.html);
measure both when plan reuse is relevant to a future investigation.

### 5. Reduce the width and lifetime of intermediate rows

Some joins carried full search vectors when later steps only needed IDs, access
flags and scores. Hash batching spilled those vectors. One recorded record plan
wrote **50,524 temporary blocks**—about 414 MB with 8 KiB blocks. This is cumulative
temporary traffic, not a measurement of one file's peak size.

The effective changes were to keep permission/candidate rows compact, reduce
vectors to scores before downstream joins, preserve match flags with record IDs,
and fetch display details only for the selected page.

Materialize shared work when reuse matters. Stream single-use intermediate
scores where possible. The final SQL uses targeted `OFFSET 0` boundaries to
prevent projection/filter movement that previously recreated bad estimates or
wide joins, without writing every intermediate result to a tuplestore. These
boundaries need plan evidence; they are not general optimization decorations.
PostgreSQL documents the tradeoff between
[CTE materialization and folding](https://www.postgresql.org/docs/18/queries-with.html#QUERIES-WITH-CTE-MATERIALIZATION).

## Approaches that failed or were insufficient

| Attempt | What happened | Lesson |
| --- | --- | --- |
| Separate scan branch for each common language | Broad queries repeatedly scanned the same chunk table. | Preserve each language's semantics while sharing the broad scan. |
| Share an opaque parsed query in the matching predicate | It hid term selectivity needed for a good candidate plan. | Candidate matching and row-dependent scoring have different planning needs. |
| Materialize progressively more intermediate results | Some reuse improved, but extra storage and wide rows still caused spills. | Materialize deliberately; it is not automatically faster. |
| Narrow a chunk join / replace it with a membership query | Temporary writes fell, but a new plan chose thousands of individual index lookups and ran slower. | Less spill is not sufficient evidence of an overall improvement. |
| Remove redundant match joins and carry match flags | Useful work was removed, but changed estimates again triggered 153,009 chunk lookups. | This change was retained only alongside a reliable bulk retrieval path. |
| Use indexed chunk retrieval for every set size | It was not a reliable broad-query solution. Early first-run observations also included bulk-load maintenance costs. | Compare access methods under the same preparation; do not attribute a mixed first-run cost entirely to the index path. |
| Score only chunks that satisfy the full query | It would change existing exclusion-query ranking. | Preserve the score formula, not just the matching IDs. |
| Run broad queries only after other cases | Earlier searches and oracle calculations hid a first-scan problem. | Time the broadest query first and retain every sample. |
| Rely on the saved search list or the 1,000-hit cap | Later pages became cheaper, but the initial search still had to authorize and rank all eligible candidates. | Caching and output limits do not replace initial-query optimization. |

The ranking counterexample is concrete: with the `simple` configuration, the
vector for `cat dog` fails the query `cat -dog`, but `ts_rank_cd` returns `0.1`.
A record that matches through metadata still receives that permitted component
contribution under Wathiq's existing formula. The regression in
[`test_search_candidate_indexes.py`](../backend/services/api/tests/test_search_candidate_indexes.py)
protects this behavior.

The 13 November follow-up found another distinction: a record that already
matches metadata does not need file text to establish that it is a candidate.
The broad combined plan spent about 475 ms constructing candidates, including
a redundant chunk-match scan and deduplication when every record already
matched metadata. Candidate construction now retains metadata IDs once and
adds file-only IDs from outside that set. A one-time existence check can skip
the file-match branch when no other records exist. Existing GIN predicates
remain visible when file matching is needed. This does **not** skip file
scoring: metadata hits still receive all their permitted active-chunk scores,
including the exclusion-query counterexample above. Page attribution also
still reports matching file evidence for metadata hits.

The following snapshots show why whole-query retesting mattered. They are
iterations with multiple changes and different cache/maintenance states, not
isolated experiments from which to calculate each edit's percentage benefit.
Raw local evidence is under `.runtime/search-performance/runN/`.

| Run | Broad combined first-page seconds | Outcome |
| --- | --- | --- |
| 8 | 3.2324 | Failed. |
| 9 | 4.1890, 3.8960, 4.0567 | Failed despite lower temporary-write traffic; the plan used 153,009 chunk index scans. |
| 10 | 3.0278, 2.5382, 2.5320 | Failed; a fast average cannot excuse one failing response. |
| 11 | 3.5447, 3.5242, 3.5749 | Failed after a further simplification changed the chosen chunk plan. |
| 12 | 8.6123, 2.3981, 2.3945 | Failed when the broad query ran first against the unvacuumed bulk load. |
| 13 | 2.8381, 2.3726, 2.3427 | Passed after documented post-load maintenance; all 192 measured responses passed. |

Increasing `work_mem` globally, disabling planner algorithms globally, disabling
durability features, moving ranking into Python, or cutting off candidates
before ranking were **not adopted fixes**. Do not describe untested alternatives
as measured failures. Any future memory/planner tuning needs its own evidence,
including the effect of concurrent searches.

## Two different kinds of disk writes

| Kind | Evidence in this investigation | Correct response |
| --- | --- | --- |
| Temporary query spill | Large vectors passed through joins/sorts; temporary blocks and hash batches grew. | Reduce intermediate width, duplication and storage; inspect the complete new plan. |
| Recovery-log writes after bulk loading | A first scan produced 46,505 full-page WAL images totaling 344,428,849 bytes while updating fresh rows' visibility hints. | Complete normal post-load maintenance and keep autovacuum healthy; report the unmaintained case separately. |

The latter is not the saved search cache and not a temporary join spill. With
checksums enabled, PostgreSQL
[WAL-logs hint-bit updates](https://www.postgresql.org/docs/18/runtime-config-wal.html#GUC-WAL-LOG-HINTS).
In the diagnostic, the chunk scan took 4.379 seconds and the record statement
6.440 seconds. The complete first API request in the unmaintained run took
8.6123 seconds, followed by approximately 2.40 seconds on repeats.

Fixture setup now finishes with `VACUUM ANALYZE`, as the existing dashboard
benchmark does. It changes the state being measured and must be disclosed.
It also touches data pages; this is **not a cold-disk benchmark**. There is no
search/oracle warm-up before the first measured broad query and no discarded
first response. Checksums and WAL remain enabled. Never vacuum in the search
request path or conceal this preparation when reporting a pass.

Warm buffers, cached database plans, a saved application result list and
post-load maintenance are different effects. An elapsed-time improvement alone
does not tell us which one occurred. The maintained-data pass does not prove a
three-second bound immediately after any unvacuumed bulk import.

## Method for the next optimization

1. Define the exact behavior to preserve: caller permissions, text configurations,
   scoring formula, tie-breaks, filters, cap and page behavior. Identify the
   endpoint actually being changed.
2. Create a unique disposable database using the canonical schema. Record data
   sizes, distribution, preparation, indexes, statistics, PostgreSQL version and
   settings. Keep fixture setup separate from measured requests.
3. Time the real API request before running any diagnostic query or oracle that
   could warm its data. Separate first submissions from saved-list pages. The
   API's page token is a position in a saved list, **not an open database cursor**.
4. Capture the actual SQL and parameters under the same caller and scope. Use
   `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` and, for write-heavy first scans,
   add `WAL` and controlled I/O timing. `ANALYZE` executes the query: capture the
   first-execution plan on a separate fresh fixture when that is the question.
5. Find the earliest important estimate/actual divergence. Inspect executed
   rows, loop counts, row width, hash batches, temporary blocks, shared reads,
   dirtied pages and WAL separately. Per-loop times must be multiplied by loops;
   parent-node totals include child work, so do not sum them indiscriminately.
   See PostgreSQL's [plan-reading guide](https://www.postgresql.org/docs/18/using-explain.html).
6. State a testable cause, make a narrow change and inspect the resulting plan.
   Recheck selective, broad, empty, denied and multilingual cases. Reducing one
   counter is insufficient if another part of the query regresses.
7. Check exact IDs, scores, ordering, deduplication, caps and every page against
   an independent oracle. Compare batch authorization with canonical decisions.
   Do not omit a failing sample, loosen the timer or change results to pass.
8. Capture final source hashes, all samples, plans and cleanup. Preserve failed
   approaches and explain confounding changes instead of presenting a misleading
   sequence of isolated speedups. Drop the disposable database on every exit.

The [repeatable runner](../tools/check_search_performance.py) covers Global
Search. Extend coverage to another endpoint when changing its search/filter
flow; this result is not proof that every Wathiq endpoint is fast.

## Boundaries of the result

The initial 12 November gate used 51,003 aggregations, 153,009 records, 306,018 chunks,
a 1,000-result cap and 100-row pages. All 192 responses passed after the
documented maintenance; the maximum was 2.8381 seconds. This is API timing
through TestClient, excluding browser rendering and network transit.

The [13 November follow-up](verification/search-page-batching-2026-11-13.md)
retains the later 3.1668-second failure, the redundant-candidate-match correction,
and the final 192-response pass with a maximum of 2.7375 seconds. Apply the same
maintenance and measurement limits to that result.

One SQL statement for ranking is not one SQL statement for the entire API
request. At the end of the initial optimization, returned-page attribution and
parent-label lookups still included per-result queries in `_attribution` and
`_global_search_item`. The 13 November follow-up batches Global Search page
enrichment in `search_page.py`; it also returns the two display capabilities
directly, removing the WebUI's per-record capability calls. Cached-page access
checks reuse statement-local permission sets and project only displayed fields.
Explicit retained-destruction expressions keep their specialized access path.
The old `_attribution` implementation remains in other search flows and serves
as a differential reference. This does not claim to have batched every endpoint.

The [subsequent browser timing investigation](verification/search-performance-2026-11-12.md#browser-versus-application-latency-follow-up--12-november-2026)
separated the cached-list read (2–3 ms) from page checks, snippets and capability
requests. Cached pagination still needs profiling: bounded per-page queries can
dominate after ranking becomes fast. The general record-capabilities endpoint
performed roughly 30 SQL statements per displayed record; the full search API
alone did not account for that subsequent WebUI work. The fix removes those
calls; it does not cache authorization decisions or the snippets.

Measure browser actions from the native click through the new results and a
paint opportunity, separately from automation command duration. Diagnostic
logging must not perform disk I/O on the request/event-loop path: the initial
timing logger itself introduced nearly one-second stalls. Retain contaminated
runs with their cause, replace the interfering probe, and repeat all samples.
Inspect thread stacks and database waits when HTTP latency exceeds SQL time;
the same investigation exposed synchronous authentication/session-lock waiting
during simultaneous reconnects, independently of full-text matching.

The session failure was a database/application wait cycle. A cache INSERT held
a foreign-key `KEY SHARE` lock on `login_sessions`; a concurrent authentication
request tried `FOR UPDATE` synchronously on the API event loop. That blocked the
loop needed to finish the first request and commit its cache write. PostgreSQL
could not detect the Python-side dependency as a database deadlock. Moving the
complete authentication transaction to a worker keeps request cleanup running.
Using `FOR NO KEY UPDATE` additionally avoids the unnecessary conflict with the
foreign-key reference while preserving conflicts with session updates/deletes.
Both changes matter: even the narrower lock can wait behind revocation work.
Tests hold real locks, verify other requests progress, and confirm that a
request waiting behind revocation is rejected. Never remove session locking or
weaken expiry checks merely to improve timing.

An existing component-filter assertion also required one particular index name.
The unchanged SQL could validly choose `digital_components_dashboard_storage_idx`,
which has the same leading `record_id` key and includes `size_in_bytes` for an
index-only scan. The regression now checks the used index's leading key and
the record correlation, rather than forbidding an equivalent covering path.
This does not relax the separate full-text GIN assertions or latency threshold.

Revalidate with production-like hierarchy depth, ACL diversity, text size,
selectivity, concurrent users and storage conditions before making a production
latency guarantee. The current scan cutoff and query boundaries are starting
points for measurement, not substitutes for it.
