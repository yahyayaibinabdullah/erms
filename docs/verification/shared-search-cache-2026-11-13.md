# Shared search cache verification — 13 November 2026

Global Search, Advanced Search, saved-search execution, and aggregation/record
collection filters use one replaceable `search_results_cache` row per login
session and connected NiceGUI tab. The stored user, list ID and query fingerprint
must also match. A replaced or expired list is rebuilt from the requesting
screen's submitted criteria; draft input is not submitted by Next.

## Implementation and upgrade

- Migration 111 renames the existing table, constraints and expiry index in
  place. Tests verify preserved entries, UNLOGGED storage and login deletion
  cascade. The canonical schema and baseline use the new name.
- The cache contains ordered IDs/scores, not permission decisions or translated
  display rows. Every page checks current access and criteria. Explicit searches
  and mutation refreshes rebuild membership; newly matching records do not enter
  an existing list until it is rebuilt.
- Matching, scoring, sorting and page selection remain in PostgreSQL. The first
  page and saved list use the same ranked result. Record capabilities and match
  evidence are fetched as a batch for the displayed page.
- Collection filters use the administrator cap (default 1,000, maximum 5,000).
  Selectors and hierarchy branches do not replace the slot.
  SQL selects at most cap + 1 authorized, ordered hits to detect truncation;
  only the first cap entries are saved. Page size is a separate limit. This
  bounds saved output, not how many candidates PostgreSQL may examine or score.
- Existing `GLOBAL_SEARCH_CACHE_*` setting keys and values are retained for
  compatibility; labels describe the shared cache. No environment variables
  were added or renamed. Five existing English messages and their generated
  Arabic drafts were updated; curated translations were preserved. Drafts still
  require administrator review.

Migration 111 was tested on disposable databases before deployment. It was
subsequently **applied to demo at 19:27 Asia/Dubai on 13 November 2026**, following
explicit user authorization; see the deployment verification below.
Deploy it with the updated API and independent cleanup worker stopped, then
restart those services and WebUI together. See the
[upgrade instructions](../application-settings-upgrade.md).

## Correctness and browser evidence

The focused API runs cover exact cached/uncached items and scores, multiple text
leaves, same-component conditions, inherited holds/locations/retention, terminal
disposition, cap enforcement, permission revocation, separate logins/tabs,
cross-screen replacement, expiry, sort/criteria/endpoint fingerprint changes,
saved-search runtime IDs and migration/cleanup behavior.

Recorded API runs passed 68 focused cases initially, then 33 cache/terminal
cases including freshness, and finally 26 cache/index cases after the SQL
corrections. These overlap and are not presented as a count of unique tests.
Two additional cached/uncached saved-search audience tests passed after their
retained profile fixtures received distinct codes and names. They verify that
revoking the audience rejects an existing cached execution; changing the saved
definition's version also replaces its cache identity.
After the Linux JIT finding, another **28 API tests passed**, covering search
setting restoration, SQL/Python error paths, Global page batching and all shared
cache regressions. Every disposable API test database was dropped, including
failed fixture attempts.
The final cache suite has 22 cases: 21 passed together, and the remaining case
passed after its fixture was corrected to remove a privilege dependency before
removing file access. That regression checks the legacy Advanced score without
file evidence and Global Search's protected score. The final ranking changes
also passed the 26-case cache/index run. These runs overlap with the counts above.

The UI/interaction run passed **116 tests**, including paging with unsubmitted
edits, stale-response abandonment, shared framework tab IDs, cache-token reuse
and mutation refresh. Translation/provenance checks also passed.

The real Chrome `global-search` run passed all **9 checks** in English and
Arabic/RTL, with no browser errors. It verified reload identity, duplicated tabs
with copied session storage, expiry recovery, and the full sequence:
Global Search → Advanced Search → aggregation filter → Advanced Search Next.
The last step rebuilt Advanced Search's list and displayed the correct second
page despite edited but unsubmitted controls. Both final screenshots were
visually inspected. Evidence:
`.runtime/webui-integration/shared-tabs-global-01/`.

The first additional collection-paging attempt lost its Chrome renderer
connection during the initial Settings check, before search assertions. Its
owned services and database were cleaned up; this is retained as a failed
attempt, not counted as a pass.

The retry passed all **9 collection-paging checks** with no browser errors.
Both languages reached records/aggregations 101–103 of 103, preserved unsubmitted
primary text while paging and returning from details, and applied a new compact
filter correctly. Unrelated role-assignment and dashboard paging checks also
passed. Representative English record and Arabic aggregation screenshots were
visually inspected against the existing compact result pattern. Evidence:
`.runtime/webui-integration/shared-tabs-collections-02/`.

## Performance evidence

The mandatory runner uses 51,003 aggregations, 153,009 records, 153,009 components
and 306,018 chunks, a 1,000-result cap and 100-row pages. It performs post-load
VACUUM ANALYZE, without a search/oracle warm-up before the first measured broad
Global Search. These are API request times through TestClient, including
authentication and JSON serialization, excluding browser automation/rendering
and network transit. They are not cold-disk or concurrent-production guarantees.

The extension exercises actual Advanced Search, saved-search execution and
collection-filter endpoints for allowed and resource-denied callers. Every
stored ordered list and every page is checked against independent SQL or fixed
fixture expectations, including exact scores. Rare terms must use the existing
metadata GIN indexes. Broad inherited-value filters are included.

Retained failed approaches:

- `shared-tabs-01`: cancelled after a display-view candidate scan repeatedly
  resolved inherited holds across the entire corpus. The database was dropped.
- `shared-tabs-02`: the one-repeat diagnostic passed, maximum 2.6764 seconds.
- `shared-tabs-final`: the subsequent three-repeat run failed 9 requests;
  maximum 5.8768 seconds. All result/order checks completed, and cleanup succeeded.
  The new scoring path performed 153,009 chunk index lookups and spilled wide
  vectors. The correction scores vectors before downstream joins and chooses
  indexed or bulk retrieval from the actual eligible-file count. The unchanged
  Global path also ran slower in this attempt; the measurements alone do not
  isolate the reason for that variation.
- `shared-tabs-03`: Global Search's first broad response took 3.0151 seconds
  (a failure, not rounded down). The new text-candidate union then exposed a
  bad file-match join that had previously been short-circuited by metadata
  matches. Its non-executing plan was retained, the stalled request cancelled,
  and the database dropped. The matching boundary and redundant-match handling
  were corrected before the next run.
- `shared-tabs-04`: all correctness checks completed, but 16 responses exceeded
  three seconds, maximum 6.3591 seconds. Broad-content scoring now used a bulk
  scan (zero executions of the per-file index branch) and wrote 8,161 temporary
  blocks rather than 53,775. The native host was concurrently running substantial
  Microsoft Defender and system activity, and unchanged Global plans also slowed
  markedly. This is evidence of contention, not proof that it explains every
  delay. The failed timings are retained; no security services were disabled.
  Cleanup succeeded. The same gate was then run against disk-backed disposable
  Linux PostgreSQL for an explicit environment comparison.
- `shared-tabs-linux-01`: broad API responses took 16.18–16.61 seconds. Plans
  identified 5.51 seconds of JIT compilation for records plus 4.50 seconds for
  aggregations. The run was stopped after collecting this evidence; its database
  and container were removed. The scoped JIT correction and restoration tests
  were added before repeating the same gate. No Docker volumes were created.
- `shared-tabs-linux-02`: JIT disappeared from the plans; the complete run still
  failed 15 responses, maximum 9.4305 seconds, with all correctness assertions
  passing. Advanced Search's repeated full-candidate joins were then removed
  for standalone/grouped text searches, and field sorting was changed to score
  only the already-authorized retained rows. The database and container were
  removed. The native host's background activity also varied during this run.
- `shared-tabs-linux-03`: Docker returned before its allocated port was reported.
  No test database was created. The container was removed and the wrapper gained
  an explicit port-readiness wait. This was a startup failure, not a timing sample.

See the [optimization lessons](../postgresql-search-optimization-lessons.md) for
the query-plan evidence and score-preservation constraints.

### Final repeated run

`shared-tabs-linux-04` passed **876 measured requests across 74 case/identity
combinations**, each repeated three times. All correctness assertions passed;
there were no responses above three seconds. The slowest response was **2.3503
seconds**. Global Search contributed 192 requests, allowed Advanced/saved/filter
searches 612, and resource-denied Advanced/saved/filter searches 72. The three
result files all contain empty failure lists. Source hashes still matched the
tested implementation when this report was completed.

The database was PostgreSQL 18.6 on Debian arm64, running in Docker Desktop's
8-CPU Linux VM; the Python API test client ran on macOS. `work_mem` was 4 MB.
Checksums, fsync and full-page writes remained enabled, and PGDATA/WAL/query spill
used Linux disk storage. JIT was available and enabled by default, with only
interactive search execution disabling it and restoring the connection setting.

This run explicitly used **60 seconds of idle time after VACUUM ANALYZE**. No
search or oracle ran during that interval, and the first broad request remained
a measured sample. Earlier failing runs are retained above. Both SQL changes
and different host activity separate these runs; this is not a controlled
measurement attributing the entire improvement to any one fix. The pause is
benchmark preparation, not an application delay, and does not prove latency
under concurrent load or immediately after import.
Defender CPU/I/O was not sampled continuously alongside the passing requests.
Its influence therefore cannot be ruled out or quantified from this run.
Docker still shares the host's resources; running PostgreSQL in Linux did not
establish isolation from host contention. The idle interval is not evidence that
scanning had stopped. A causal timing comparison needs identical SQL before and
after each change under comparable load, with concurrent host/process telemetry;
no security protection was disabled for these measurements.

The broad text criterion was exactly `common OR universal`, with metadata and
file text enabled. `common` occurs in every aggregation/record's metadata and
`universal` in every file's text: Global Search has **204,012 permitted matches**,
of which the first 1,000 are retained. Metadata-only `common` and file-only
`universal` were also tested. These are synthetic criteria, not a demo search.

| Request, allowed caller | First page, three runs (seconds) | Next, three runs (seconds) |
| --- | --- | --- |
| Global, broad combined | 2.3503 / 2.1823 / 2.0661 | 0.1632 / 0.1373 / 0.1501 |
| Global, broad file text | 1.4797 / 1.2805 / 1.2511 | 0.1443 / 0.1441 / 0.1413 |
| Advanced records, broad combined | 1.5323 / 1.4145 / 1.4543 | 0.1670 / 0.1859 / 0.1764 |
| Saved records, broad combined | 1.4248 / 1.6477 / 1.4178 | 0.1770 / 0.1603 / 0.1668 |
| Advanced aggregations, broad combined | 0.3144 / 0.3141 / 0.5967 | 0.1040 / 0.1263 / 0.1050 |
| Record collection, descending filter | 1.2558 / 1.0478 / 1.1626 | 0.1602 / 0.1744 / 0.1778 |
| Aggregation collection, descending filter | 0.3573 / 0.3175 / 0.3306 | 0.0886 / 0.0678 / 0.0747 |

Across every case, the slowest second page was 0.2709 seconds; the slowest later
page was 0.5254 seconds. Valid paging retained its list ID throughout. Each
1,000-hit case checked all ten 100-row pages, not just First and Next.

Reproduce with an already available local PostgreSQL image (the wrapper never
pulls one), using a new output directory:

```sh
backend/services/api/.venv/bin/python tools/run_linux_search_performance.py \
  --image sha256:5a5a84b19854a9ffaa54082c166ff4ec27473a361e496e5ea167f298f2da9722 \
  --repeats 3 --settle-seconds 60 \
  --output .runtime/search-performance/shared-tabs-linux-repeat
```

The [portable evidence summary](shared-search-cache-2026-11-13.json) preserves
environment/source hashes, all 876 timings, case results, browser checks and
cleanup evidence. Raw ordered expected/received IDs and scores, execution plans,
and stage timings remain in `.runtime/search-performance/shared-tabs-linux-04/`.
The database `erms_search_perf_b27c288c7dca4606a6b975d901e921e3` was dropped; the
wrapper exited zero and removed container
`erms-search-perf-linux-108cd98bd2a8409d9ba640b969dad915`. No Docker volumes were
created. A final container inventory found no remaining benchmark containers.
Both successful browser runs also record their disposable databases as dropped.

Final catalogue, configuration ownership (126 settings), API-template consistency
(36 settings), API policy generation and whitespace checks passed. No new demo
WebUI timing is claimed by this verification.

## Demo deployment verification

On 13 November 2026 at 19:27 Asia/Dubai, demo's history contained every migration
001–110 and only 111 was pending. The owned local stack was stopped, migration
111 was applied transactionally, and the same stack was started with the updated
API, WebUI and independent cleanup worker. Startup reported ready at 19:28.

Operational checks confirmed all 111 repository migration markers with no pending
files, the same cache table OID before/after rename, UNLOGGED persistence, both
renamed indexes, and the login-session foreign key with ON DELETE CASCADE. There
were zero cache entries before and immediately after the migration. No test suite
was run against demo. The local deployment record is
`.runtime/local-stack/migration-111-demo-2026-11-13.json`; this deployment does not
change or extend the earlier benchmark measurements.
