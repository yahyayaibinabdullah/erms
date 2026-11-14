# Search score reuse and realistic text sizes — 13 November 2026

Status at this report's close: implementation and correctness checks were
present; both final native three-second performance gates failed. This report
does not supersede the earlier small-vector gate with a claimed large-vector pass.
The user subsequently accepted the current compressed baseline as good enough
for now on 14 November. See the
[consolidated benchmark history and acceptance decision](../search-performance-benchmarks.md).
This closes the tuning round with an explicit latency exception, without
changing any measured failure recorded here.

The [14 November storage comparison](search-vector-storage-2026-11-14.md) reran
both gates on the native Mac with identical application SQL. The original gate
passed; the current-storage larger-text gate still had one response over three
seconds. Uncompressed storage had ten such failures and was not adopted. Earlier
failed samples in this report remain part of the evidence.

## Behavior preserved

Matching remains chunk-local, as approved in Full-Text Search §10.1.1. AND terms
must match one chunk, NOT excludes a matching chunk rather than the whole file,
and a phrase cannot span adjacent chunks. No mixed single/multi-chunk matcher
or boundary vector was added. Authorization, source eligibility, score formulas,
tie-breaks, result caps and cache ownership remain unchanged.

`search.py` and `search_cache.py` retain numeric chunk scores, per-record maxima
and metadata scores once per statement. The selective fixture had 1,200 matches
despite an estimate of one. Inlining let a nested loop compute the entire batch
for each candidate. The fix keeps vectors out of materialized results and stops
that repeated calculation. `OFFSET 0` alone did not prevent rescans.

`search_page.py` also retains the exact first-12 matching-chunk window and cap
flag before selecting the first chunk per file for headline generation. It no
longer creates multiple snippets that the existing response processing discards.

## Repeatable workload

The canonical-schema disposable fixture contains 51,003 aggregations, 153,009
records/files and 180,630 text chunks. There are 151,470 single-chunk files
(about 4,000 extracted characters), 1,386 ten-chunk files (about 160,000
characters) and 153 hundred-chunk files (about 1.6 million characters). These
are extracted-text lengths, not original document sizes. All three common text
configurations are represented. Every file has one configuration.

The richer gate times real HTTP responses, including authentication, SQL,
result-cache writes/reads and page evidence. It uses a 1,000-result cap and
100-row pages, checks all pages and exact scores against independent SQL, and
checks complete uncapped file-text membership. A denied caller must receive
no results. Every measured response, including first submissions, must meet
three seconds; failed samples remain in the evidence.

| Criteria | Expected uncapped records | Expected aggregations |
| --- | ---: | ---: |
| Combined `common OR universal` | 153,009 | 51,003 |
| Metadata `common` | 153,009 | 51,003 |
| File `universal` | 153,009 | 0 |
| File `needleunique` or `needleunique OR absentunique` | 1,200 | 0 |
| File `universal evidence` | 153,009 | 0 |
| `needleunique witnessunique`, files only or combined sources | 1,200 | 0 |
| File `universal -restricted` | 76,505 | 0 |
| File `"document evidence"` | 153,009 | 0 |
| File `"needleunique witnessunique"` | 1,200 | 0 |
| File `absentalpha absentbeta` | 0 | 0 |
| File `crossalpha crossbeta` | 200 | 0 |
| File `notalpha -notbeta` | 1,000 | 0 |
| File `"boundaryalpha boundarybeta"` | 200 | 0 |
| File `"crossalpha crossbeta"` | 200 | 0 |
| File `universal -"boundaryalpha boundarybeta"` | 152,809 | 0 |

## Evidence and limits

Raw runs are retained in `.runtime/search-scoring/`. Each run owns a newly
created database and drops it on exit. Initial Linux runs used PostgreSQL 18.6
in Docker, created no volumes, and removed their owned containers. All later
verification uses native PostgreSQL 18.4 on the eight-CPU, 24 GiB Mac, as requested.
Checksums, fsync and full-page writes remain on. The fixture finishes with
`VACUUM ANALYZE`; this is maintained-data testing, not cold-disk testing.

The paired exact-query diagnostic `full-query-probe-01` recorded:

| Change | Before SQL seconds | After SQL seconds | Result |
| --- | ---: | ---: | --- |
| Retain metadata-score batch in selective combined search | 2.222 | 0.167 | Identical rows/scores; repeated scoring removed |
| Force index paths for broad word | 3.894 | 3.965 | Insufficient; not adopted |
| Force index paths for broad phrase | 4.208 | 5.200 | Slower; not adopted |

Those are SQL diagnostics, not API timing results. Later instrumented EXPLAIN
can differ from an earlier API request. Complete captured API statements are
used for plan checks; an inner ranking branch alone can choose a different plan.

The original-storage `iteration-04-original-storage` retained 143 API samples:
four first-page failures (3.506–3.745 seconds), with every cached page and denied
request passing. This run preceded the metadata-score correction and the added
17th combined selective case. It is not a final pass.

Storage experiments (`MAIN`, LZ4 and a larger TOAST target) used only
disposable databases. MAIN/LZ4 is now represented by the canonical schema and
the prepared migration 112; its final API gate remains required. Host CPU,
memory and database read waits are recorded. Defender remains enabled. Memory
pressure and background CPU activity varied, so adjacent runs are not evidence
of an isolated percentage improvement from one storage setting.

The initial disposable regression suite passed 76 tests. After the metadata-score
and storage changes, the native follow-up passed **77 tests** in 321.44 seconds,
including chunk-local matching, exact page evidence, permissions, cache
ownership/rebuilding, JIT restoration and the populated migration. The database
`erms_messaging_test_acl_25ec81bdc14b4da898d2a0eaf74a6aea` was dropped. Two existing
TestClient deprecation warnings remain; there were no test failures.
Migration 112 is prepared locally; no migration or storage experiment has been
applied to demo for this work.

## Native Mac follow-up

At the user's direction, further tests run directly on the Mac's PostgreSQL
18.4 cluster (Postgres.app), not Docker. Each still creates and drops its own
database. `iteration-07-native` used the existing canonical storage and all
score-reuse fixes. All result/ranking, membership and score-batch loop checks
passed; 9 of 154 HTTP responses exceeded three seconds. Broad first pages took
3.500 seconds combined, 4.569 seconds for a file word, 7.940 seconds for file
AND, 6.226 seconds for exclusion, 7.226 seconds for a phrase and 5.937 seconds
for a negative phrase. The selective combined AND took 0.525 seconds. All
cached pages passed. This is a failed latency gate, not a Docker-only issue.

The benchmark now buffers diagnostics during requests and calculates its oracle
only after all HTTP samples. No benchmark artifact is written during those
timers. The native run recorded no swap-outs, but concurrent memory compression
and Defender CPU activity were present. No security or host-memory settings were
changed, and the user is not asked to free further memory.

`native-cpu-probe-01` sampled only its owned disposable PostgreSQL backend using
macOS `sample`. In five-second samples of the broad word/AND queries, roughly
half of the sampled stacks were in `detoast_attr`: retrieving out-of-line vectors
and decompressing them. This is sampling evidence, not an exact percentage of
complete API latency. The plain SQL samples took 4.112 and 5.776 seconds. Those
diagnostics and the next storage comparison preserve the complete SQL and exact
returned rows. The native database was dropped after profiling.

### Retained attempts

All attempts below have cleanup records confirming their disposable database
was dropped. Attempts 01–06 used Linux/Docker; 07 onward use native Postgres.app.
These are successive experiments under variable host load, not isolated
percentage comparisons. No failing sample was removed.

| Attempt | HTTP samples | Above 3 seconds | Maximum seconds | Relevant condition |
| --- | ---: | ---: | ---: | --- |
| 01 | 143 | 14 | 10.442 | Initial numeric-score reuse; original storage |
| 02 | 143 | 11 | 9.697 | MAIN storage experiment |
| 03 | 143 | 11 | 9.648 | MAIN/LZ4 requested, but mixed actual compression |
| 04 | 143 | 4 | 3.745 | Original storage, fewer headlines; before metadata reuse fix |
| 05 | 154 | 11 | 20.045 | MAIN/larger TOAST target; plan capture failed separately |
| 06 | 154 | 8 | 6.071 | Metadata reuse fixed; mixed actual compression |
| 07 | 154 | 9 | 7.940 | Native Mac, original storage |
| 08 | 428 | 14 | 6.816 | Native MAIN/LZ4 requested, mixed actual compression |
| 09 | 428 | 1 | 3.483 | Native MAIN, all 180,630 vectors actually LZ4 |
| 10 | 428 | 2 | 3.393 | As 09, plus three language-specific GIN indexes |
| 11 | 428 | 12 | 7.622 | As 10, with disposable-process `work_mem=8MB`; not adopted |
| 12 | 428 | 1 | 3.105 | Canonical MAIN/LZ4, original indexes, 4 MB query memory, 300-second settling interval |
| 13 | 0 valid searches | — | — | Session expired after a prolonged scheduling/suspension gap; HTTP 401 before ranking |
| 14 | 428 | 2 | 3.325 | Search-only 12 MB trial, login after settling, idle sleep prevented; trial removed |
| 15 | 428 | 4 | 3.797 | Retained MAIN/LZ4 code, original indexes and 4 MB memory; all correctness checks passed |

The fixture originally copied already-compressed template vectors. PostgreSQL
can retain that physical representation despite the destination column's
compression setting. Attempt 08 had 99,847 PGLZ values and 80,783 LZ4 values.
The fixture now concatenates an empty vector when inserting each value, creating
a fresh, logically identical datum to which the destination policy applies.
Attempt 09 verifies `pg_column_compression(search_vector)` for every row, rather
than assuming `pg_attribute.attcompression` describes existing data.

Attempt 10 still used a lossy bitmap for the broad AND query: 38,794 exact heap
pages and 66,101 lossy pages at the default 4 MB `work_mem`. Lossy pages require
vector rechecks even when the plan reports zero rows removed by rechecking.
The following experiment uses 8 MB only in its disposable test processes;
neither the cluster defaults nor demo were changed. Checkpointer CPU did not
increase during the slow negative-phrase samples in attempt 09, so no claim is
made that a checkpoint caused those delays.

Attempt 11 eliminated bitmap lossiness and reduced temporary blocks from 8,205
to 2,523 in the broad AND plan, but did not pass the HTTP gate. All first-round
requests passed (maximum 2.732 seconds); later rounds slowed down. Defender CPU
observations averaged approximately 98%, 152% and 176% across the three timed
rounds (100% denotes one core). There were no swap-outs and almost no new memory
compression during those rounds. These observations do not isolate Defender as
the cause or support attributing the slowdown to memory pressure.

`native-memory-plan-01` compared the identical complete captured SQL at 4, 8,
12 and 16 MB in another disposable database. All returned rows and scores were
identical. At 12 MB the observed narrow intermediate spills disappeared; 16 MB
was not consistently faster. This diagnostic had sequential order and variable
host load, so it does not establish isolated speedup percentages. Extra partial
GIN indexes and an 8 MB allowance were not adopted. The database was dropped.

### Populated migration verification

The migration regression reconstructs pre-upgrade PGLZ/EXTENDED storage and
checks binary vector contents, positions, weights, stripped lexemes, matching,
scores, row data and index definitions after the physical rewrite. It includes
a compressed vector larger than one heap page, preserving overflow support.

The first test fixture did not actually compress its random vocabulary and was
corrected. The next test caught a real migration defect: a separate same-type
ALTER reset the preceding compression policy and rewrote PGLZ again. The final
single ALTER specifies its type expression and MAIN/LZ4 together. The focused
test passed in `storage-upgrade-test-03.log`; the 77-test regression pass
also checks the retained large value and index definitions. All three focused
test databases were dropped. No logical reindexing or text re-extraction occurs.

### Canonical native timing protocol

The follow-up uses the actual canonical schema and application code, with no
experimental indexes or memory override:

```sh
backend/services/api/.venv/bin/python tools/check_large_text_search_performance.py \
  --output .runtime/search-scoring/iteration-12-native-canonical \
  --repeats 3 --settle-seconds 300
```

The five-minute idle interval follows fixture maintenance and API login, before
any search or oracle SQL. It is an explicit measurement condition intended to
reduce bulk-load/background interference, not a discarded warm-up. Host
observations now include the busiest executable names in addition to PostgreSQL,
Python and Defender, so unrelated competing services are not hidden by a narrow
process whitelist. Nothing disables or reconfigures host security.

Attempt 12 verified all results and score-batch loop checks, but one negative
phrase response took 3.105 seconds: ranking 2.869 seconds, saving the list
0.003 seconds, and page details 0.212 seconds. Its other two first pages took
2.440 and 2.327 seconds; all cached pages passed (maximum 0.514 seconds).

The next implementation tested a search-only 12 MB floor, restoring the prior
connection setting and preserving higher configured values. All 14 execution
setting tests passed, including nested calls, separate connections, Python
errors, SQL rollback and commit. It does not raise the server's 4 MB default.

Attempt 13 was invalidated before ranking by an expired login. The host monitor
recorded a 940.7-second observation gap and other prolonged gaps; no valid search
timing was produced. Its database was dropped. The harness now authenticates
after the deliberate idle interval, preserving application session timeouts.

Attempt 14 used the same five-minute interval with that correction and the
search-scoped memory floor, plus `--probe-concurrency`. A temporary macOS
`caffeinate -i -w <benchmark-pid>` assertion prevents idle sleep only for the
owned run; it ends when that process exits. The concurrent diagnostic executes
only after HTTP/oracle/plan checks and reports raw SQL time and per-backend RSS
separately from the HTTP gate.

Attempt 14 passed exact-result/score/membership checks but failed two HTTP samples:
broad exclusion 3.094 seconds and negative phrase 3.325 seconds. The concurrent
probe did not run because the HTTP gate had failed. The larger memory allowance
was removed: reducing spills had not established a reliable complete-request
benefit, so the retained application respects the caller's existing `work_mem`.
The expanded 14 execution-isolation tests passed again with that retained policy
in 27.51 seconds; their database was dropped.

Attempt 15 and the original native gate run sequentially under a temporary
`caffeinate -i` wrapper. Both use three repeats and a documented 300-second
post-load idle interval. Login occurs after that interval in the richer gate.
These runs use the retained code, original GIN indexes and original 4 MB memory
setting. Attempt 15 passed exact results, ranking, uncapped membership and score
producer loop checks, but four first pages failed the latency requirement:
negative phrase 3.797 and 3.628 seconds, broad NOT 3.112 seconds, and broad AND
3.095 seconds. All cached pages passed (maximum 0.604 seconds). Ranking took
3.351 seconds of the slowest response, cache insertion 0.003 seconds and page
details 0.420 seconds. Its disposable database was dropped. This repeats the
failure with the retained code; it is not appropriate to keep rerunning until
one favorable run hides these failures.

`standard-native-01` completed all 876 API samples and exact result/cache/page
checks. Ten first-page samples failed the latency requirement, with a maximum
of 8.906 seconds. Earlier broad Global, Advanced and saved-search maxima were
2.304, 2.118 and 2.168 seconds respectively; later grouped Advanced Search,
field sorting, file-only search and record filters slowed substantially. All
cached pages and denied requests passed. The disposable database was dropped.

This original harness still interleaves oracle queries, EXPLAIN execution and
artifact writes between timed requests; it does not use the richer harness's
fully buffered protocol. Configuration-template checks were also run during
this attempt. A host snapshot during the slowdown showed concurrent Spotlight,
Defender and system-policy activity, with load averages above seven. No thermal
warning was reported. These conditions prevent treating the run as an isolated
measure of any one code change. They do not erase its failures or establish
which background process caused the slowdown.

### Parallel-query diagnostic (not adopted)

`native-parallel-probe-01` created another canonical native database with the
same richer fixture. It compared the complete captured ranking statement, the
same ranking without first-page detail projection, and that latter statement
with the identity helper's existing expression written inline. The comparison
ran forwards and backwards for broad word, AND and negative-phrase criteria.
Every variant returned identical ranked IDs and scores. None selected a Gather
node, even though the cluster allowed two workers per Gather and eight parallel
workers overall. Removing page projection/identity indirection did not enable
parallelism or establish a consistent improvement, so no application query or
function parallel-safety annotation was changed on this hypothesis.

The first complete negative-phrase SQL took 10.439 seconds elapsed and 5.63
seconds of leader CPU. Subsequent complete statements took 3.587–5.078 seconds,
with 3.28–4.14 seconds of leader CPU. Thus later delays were not predominantly
time spent waiting off-CPU. These are raw SQL diagnostics, not HTTP samples.
Separate subsequent EXPLAIN executions recorded shared-read time ranging from
about 7 to 602 ms and temporary-write time around 79–104 ms in the sampled
plans; those I/O times must not be attributed to the preceding plain execution.
The diagnostic database was dropped. This investigation did not meet or replace
the three-second response requirement.
