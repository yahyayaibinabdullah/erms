# PostgreSQL search optimization lessons

This records the Wathiq Global Search investigation of 12 November 2026 on
PostgreSQL 18.4. Read it before optimizing a search or filter. The
[performance contract](search-performance.md) defines the requirements; the
[verification report](verification/search-performance-2026-11-12.md) records
that investigation's measurements and their limits. The
[consolidated benchmark history and acceptance decision](search-performance-benchmarks.md)
includes subsequent experiments through 14 November and the user's acceptance
of the compressed-storage baseline with its documented latency exception.

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

Materialize shared work when reuse matters. A syntactically single-use CTE can
still be executed many times by a nested-loop join: inspect actual loops before
deciding that its scores can safely stream. The SQL uses targeted `OFFSET 0` boundaries to
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

## 13 November: richer vectors and repeated scoring

The original repetitive-text fixture did not reveal every expensive plan. The
richer corpus has 151,470 one-chunk files, 1,386 ten-chunk files and 153
hundred-chunk files (153,009 records and 51,003 aggregations). Each chunk contains
hundreds of distinct lexemes. Extracted-text sizes are about 4 KB, 160 KB and
1.6 MB per file respectively; these are not original binary document sizes.

A selective AND query estimated one eligible file although 1,200 matched.
PostgreSQL inlined the chunk-score batch beneath a nested loop and executed
that entire batch 1,200 times: 1,440,000 `ts_rank_cd` calculations instead of
1,200. Existing GIN candidate retrieval did not prevent this later mistake.
`OFFSET 0` stopped some projection movement but did not guarantee one execution.

The correction materializes the narrow `(component ID, numeric score)` batch
and the completed per-record maximum. Text and vectors stay out of those
stored intermediate rows. Global and Advanced Search retain their existing
score formulas and eligibility rules. A corrected selective plan recorded
1,200 scored rows with one execution, rather than 1,200 executions. Verify the
producer's `Actual Loops`, not just how many times a CTE scan reads its result.

The combined metadata/file variant exposed the same issue in a separate
metadata-score batch. Its plan executed 1,200 metadata scores 1,200 times.
Materializing those numeric scores reduced the exact captured ranking SQL from
2.222 to 0.167 seconds in the paired diagnostic, with identical returned rows
and scores. These are SQL timings, not complete HTTP response timings. Protect
both score sources; testing only file-only searches misses this join shape.

Page evidence had another avoidable cost. SQL produced a headline for every
one of the top 12 matching chunks, then Python retained only the first snippet
per file. The revised SQL keeps the same top-12 window and tie-breaks, marks its
cap before deduplication, and generates a headline only for the retained first
chunk per file. Differential tests compare filenames, snippets, ordering,
component IDs and cap flags against the previous implementation, including
files with 100 chunks. This removes repeated presentation work without
changing matching or relevance.

The approved product behavior remains chunk-local: terms in an AND must match
one vector; NOT excludes a matching chunk rather than the complete file; a
phrase cannot span two adjacent chunks. The rejected mixed single/multi-chunk
matcher changed these semantics and introduced more plan branches. It is not
part of this fix. The specification and grammar guide state these limitations,
and the richer gate asserts the existing behavior explicitly.

Do not equate the scoring fix with a complete performance pass. Larger vectors
also expose TOAST retrieval, decompression and headline costs that the original
fixture hid. Disposable-only storage experiments compare `MAIN`, LZ4 and a
larger TOAST target; a faster isolated scan does not establish a faster API
request. Capture the API's complete SQL, including its outer ranking/page
projection. Explaining only an inner branch can produce a different plan.
Retain response timings separately from later instrumented EXPLAIN timings.

Host contention is another separate measurement. Record CPU, memory and
database read waits alongside every run; do not attribute all elapsed time to
the planner or to antivirus activity. No antivirus setting is disabled for the
gate. Failed attempts remain evidence, and reducing host pressure does not
justify deleting their samples or claiming a production latency guarantee.

Forcing index paths was also insufficient. In an isolated diagnostic,
`enable_seqscan=off` changed the broad-word matching branch to a GIN bitmap scan,
but the complete SQL took 3.965 seconds versus 3.894 seconds with normal planner
choices. Its mixed-configuration filter still evaluated the vector predicate
after the bitmap lookup, so it still read/decompressed the large vectors. The
forced-index phrase query was slower too (5.200 versus 4.208 seconds). The
experiment restored the setting and was never adopted in application code.
An index name in a plan is not evidence that expensive text work disappeared.

### Verify physical vectors, not just a column's declared policy

Native Mac sampling found substantial time retrieving out-of-line vectors and
decompressing PGLZ values. `tsvector` is a TOAST-capable type: TOAST compression
can apply to its physical value both inline and out of line. It is not a
separate full-text encoding, and it does not discard terms or positions.

`MAIN` with LZ4 reduced those costs in the richer fixture while preserving all
logical values. MAIN prefers an inline compressed vector but still permits
overflow when needed. The selected physical policy is in migration 112 and the
fresh schema; it does not change database-wide defaults. The API gate, not an
isolated decompression microbenchmark, remains the release criterion.

Two traps needed explicit regressions:

- A destination's LZ4 setting does not necessarily recompress a copied datum.
  The original synthetic template insertion retained 99,847 PGLZ values even
  though `attcompression` said LZ4. Check `pg_column_compression` on actual
  rows. The fixture now makes a fresh identical vector before insertion.
- A same-type `ALTER COLUMN TYPE ... USING ...` rewrites the table but resets
  its column storage policy. Applying MAIN/LZ4 in preceding statements produced
  another PGLZ table. Migration 112 specifies the type expression and final
  storage/compression policy in one ALTER operation. Its populated-upgrade test
  compares binary vector values, matching, scores, data and physical policy.

Do not reparse extracted text just to change compression: current dictionaries
or normalization could change search values. Preserve the vector itself, and
document the rewrite's lock, temporary space, WAL and post-rewrite maintenance.
See PostgreSQL's [TOAST storage documentation](https://www.postgresql.org/docs/18/storage-toast.html)
and the [upgrade procedure](../database/README.md#existing-database).

### More indexes or memory did not establish a complete latency fix

Separate common-language GIN indexes could remove the redundant mixed-language
filter while keeping the existing single OR branch. Splitting the query into
three language scans remained slower because it revisited the heap three times.
The additional indexes alone did not pass the richer API gate, so they were not
added to the canonical schema.

With those experimental indexes, the broad AND bitmap had 66,101 lossy heap
pages at 4 MB `work_mem`; 8 MB eliminated lossiness. Zero rows removed by a
recheck does **not** mean PostgreSQL avoided rechecking vectors. At 12 MB the
tested complete ranking queries also stopped spilling their narrow intermediate
rows. Nevertheless full SQL/API latency remained variable, and 16 MB was not
consistently faster. The extra indexes and memory increases were not adopted.
Removing one expensive operation is useful evidence, not proof of overall speed.
Any future memory proposal must measure complete requests and concurrent-query
memory use: `work_mem` is an allowance per operation, not a whole-query limit.
The subsequent canonical 4 MB run still failed one response at 3.105 seconds;
a later search-scoped 12 MB experiment still failed two responses (maximum
3.325 seconds). It was removed, preserving the caller's memory policy. Removing
spills did not establish a reliable whole-request improvement. Restoration tests
cover lower/higher initial memory values, nesting, other connections, Python
errors, SQL rollback and transaction completion.

Removing first-page detail projection did not establish a parallel-query fix.
The native follow-up compared complete captured SQL with ranking-only variants,
including an inline form of the same identity expression. All ranked IDs and
scores agreed, but none of these plans selected Gather nodes and timings did
not improve consistently. Do not relabel permission functions `PARALLEL SAFE`
merely because a scan is slow: prove both semantic safety and an actual plan
benefit. This rejected diagnostic changed no application SQL or function labels.
See the [follow-up evidence](verification/search-score-reuse-2026-11-13.md#parallel-query-diagnostic-not-adopted).

### Uncompressed vectors were not a better storage policy

The 14 November native Mac comparison ran both gates with current storage and
with EXTERNAL (no vector compression), using fresh disposable databases and
identical application SQL. The original fixture's vectors were already
uncompressed in both arms, with identical table sizes; its timing variation is
not evidence of a compression benefit. Verify actual values before interpreting
a column-policy experiment.

For the larger corpus, all 180,630 chunk vectors were LZ4 in the current arm and
uncompressed in the EXTERNAL arm. Binary vector fingerprints and every result,
score, order and permission expectation agreed. EXTERNAL increased total chunk
storage, including indexes, by 16.2%, moved much more data into TOAST, and produced
slower median first pages for all six broad content-search cases. Ten responses
exceeded three seconds versus one with current storage. The current arm's lone
3.407-second response remains a failed latency sample; medians cannot excuse it.
The user subsequently accepted this baseline as good enough for now on the
shared MacBook. That explicit decision ends this tuning round without changing
the test threshold or claiming that host contention caused the failed sample.

Disabling compression is not equivalent to eliminating retrieval work. EXTERNAL
also changes physical placement and can add TOAST buffer accesses. Keep those
effects separate from LZ4 decoding cost and from host contention. The experiment
was not adopted in the application schema. See the
[complete comparison and measurement limits](verification/search-vector-storage-2026-11-14.md).

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

## 13 November: extending result caching to Advanced Search and filters

Do not select full-corpus candidate IDs through a display view without inspecting
its plan. `authorized_records_for_search` includes a lateral effective-hold
aggregate. In the first shared-cache prototype, even `SELECT resource.id` kept
that aggregate: the plan evaluated inherited hold ancestry once per candidate,
then repeated it while matching and ranking. On the 153,009-record fixture this
was unacceptable and the diagnostic run was cancelled and its database dropped.

Ordinary-field candidates and ordering now use base relations plus the canonical
batch permission sets. Display views hydrate only the selected page. Inherited hold and location criteria use shared sets in `search_projections.py`;
retention resolves each distinct root classification once and joins root overrides
before propagating values to descendants. Their meanings remain those of the
canonical SQL resolvers. The gate also covers broad not-held, null-location and
inherited-retention criteria; selecting a base column is not a substitute for an
inherited value.
Likewise, `page_permission_ctes()` is for a small displayed page, not the entire
corpus. The initial pass uses `visibility_ctes(candidate_resource=...)`; parent
label filters use a separate batch of candidate parent IDs. Small-fixture
correctness tests did not expose these costs; the mandatory large-data test did.

The next repeated run exposed a separate scoring problem in the new Advanced
Search path. Joining chunks to the parsed-language relation carried vectors
through an external sort, and underestimated eligible files led to 153,009
individual chunk index lookups. The broad-content plan wrote 53,775 temporary
blocks and took 5.09 seconds under EXPLAIN ANALYZE; measured API requests reached
5.88 seconds. A preceding single-repeat run had passed, so that pass was not
enough evidence of a reliable implementation.

The correction keeps parsed queries in scalar lookups, reduces vectors to
per-leaf scores before downstream joins, and selects indexed or bulk chunk
retrieval from the actual eligible-file count. It preserves Advanced Search's
existing eligibility and left-to-right float4 score addition, including its
historical difference from Global Search's active-content score protection.
Standalone positive full-text leaves also bound the permission pass with their
indexed text candidates. That shortcut is not applied to arbitrary NOT/OR
trees, where excluding nonmatching candidates could change Boolean semantics.
The repeated gate must verify exact scores as well as IDs and timings after
these changes; neither less disk traffic nor a faster single sample suffices.

Moving text candidates before permissions then exposed the same correlated
content-identity estimate in Advanced Search's *matching* branch. Previously a
metadata match could short-circuit that branch; a candidate union executes it.
The diagnostic request stalled, was cancelled, and its database was dropped.
Keep the active-content Boolean behind a measured projection boundary before
filtering it, as in Global Search; otherwise an estimated single file can choose
a nested loop across the broad set. Metadata hits need file scoring and page
attribution, but do not need the redundant file-only candidate scan.

The all-records coverage guard now compares exact metadata-match and record
counts instead of building an anti-join hash simply to prove no records remain.
This relies on a real invariant: one metadata document per record, a foreign key
to that record, and disjoint text-configuration branches. Never substitute
estimated table counts or copy this shortcut to duplicate-producing match sets.

### Check JIT on the actual PostgreSQL build

The disposable Linux comparison exposed a cost absent from the earlier local
plans: LLVM JIT compilation. One Global record plan compiled 649 functions for
5.51 seconds; its aggregation plan compiled 449 functions for 4.50 seconds.
The complete broad API responses took 16.18–16.61 seconds. Even an empty record
plan spent 469 ms compiling and only about 37 ms on the remaining execution.
High estimated costs from recursive ACL branches triggered this work regardless
of how many rows those branches eventually produced.

[PostgreSQL's JIT decision documentation](https://www.postgresql.org/docs/18/jit-decision.html)
explains that compilation is chosen from estimated cost at planning time and
can cost more than it saves for short queries. A build without LLVM performs
no JIT, so SQL parity alone does not establish performance parity across builds.
The native Postgres.app installation reported `jit=on`,
`pg_jit_available()=false`, and no `--with-llvm` build option; its missing JIT
timings were a build difference, not evidence that the SQL avoided compilation
on Linux.

`search_execution.py` now disables JIT only during interactive ranking/cached
page SQL and restores the prior connection setting afterward. SET LOCAL also
bounds it to the transaction; a failed SQL transaction is left for its owner's
rollback so restoration cannot hide the original exception. Regressions cover
initial settings on/off, successful execution, Python exceptions and SQL errors.
At that stage server defaults, join algorithms, work_mem, durability and
authorization remained unchanged; the later scoped-memory investigation is
recorded above. Explain probes use the same execution context as the real endpoint.
Record default JIT, JIT availability and compilation timing in future evidence.

### Reuse the compact ranking path and respect the requested sort

The generic Advanced Search plan still rejoined the full candidate/resource set
while matching, scoring and ordering. A standalone full-text leaf, including
one-child All/Any wrappers produced by the builder, now reuses the compact Global
candidate/ranking SQL. An explicit option preserves Advanced Search's historical
score eligibility; Global Search retains its stronger score protection. A
regression removes file-view access and checks identical Advanced scores without
file evidence, while Global retains its existing lower protected score.

When the user sorts by a field rather than relevance, scores cannot determine
which rows belong in the capped list. That path matches and authorizes first,
selects the requested deterministic order, then computes unchanged scores only
for the retained rows (and one extra truncation sentinel). Relevance sorting
still scores every authorized match before the cap. The gate includes grouped
text and text-plus-field criteria with explicit field sorting; do not benchmark
only a bare leaf if the WebUI submits a group.

### Preserve measurement conditions as well as passing numbers

The final three-repeat Linux run passed 876 API requests, maximum 2.3503 seconds,
with exact cached IDs/scores and all page orders verified. It explicitly waited
60 seconds after fixture maintenance, without issuing a search or oracle during
that interval. First broad Global pages took 2.0661–2.3503 seconds and Next took
0.1373–0.1632 seconds. SQL fixes and varying host load both separate this run
from earlier failures; do not attribute the whole reduction to one change or
discard the failures. These are maintained-data, single-client API timings, not
a guarantee under arbitrary contention. The
[verification report](verification/shared-search-cache-2026-11-13.md) records all
attempts, the exact synthetic broad criterion, reproducible command, environment,
source hashes and cleanup. A cap of 1,000 is an output limit after authorization
and ranking, not permission to stop examining candidates before the correct top
1,000 are known.
