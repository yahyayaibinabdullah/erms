# Global Search page batching and session-lock verification — 13 November 2026

The follow-up to the [12 November timing investigation](search-performance-2026-11-12.md)
keeps matching, permissions, ranking, result caps and cache ownership unchanged.
All changes remain local and uncommitted.

## Changes

- `search_page.py` fetches the returned page's metadata attribution, filename
  matches, content snippets, visible parent labels and two display capabilities
  in one SQL statement. File evidence retains the original limits, order,
  snippet selection, leaf attribution and capped-count indicators.
- Cached-page checks share the canonical authorization sets. They project the
  displayed fields instead of expanding every column of the search views.
  Explicit retained-destruction expressions preserve their specialized checks.
- The WebUI uses `list_components` and `has_previewable_component` from the
  search response. It makes no per-record capabilities calls. Those flags and
  snippets are recalculated per page; only ranked IDs/scores are cached.
- Authentication's entire synchronous transaction runs in a worker thread,
  including connection acquisition, policy/settings reads, commit and release.
  The login-session row uses `FOR NO KEY UPDATE`, compatible with a cache
  INSERT's foreign-key `KEY SHARE` lock. Concurrent session updates/deletes
  remain serialized. Code comments describe the former database/event-loop
  wait cycle and why both changes are necessary.
- A repeated request for the already displayed page is ignored, including when
  an immediately completed request would otherwise allow a duplicate click.
- Candidate matching reuses metadata hits and adds only file matches outside
  that set. A one-time guard skips redundant file matching when every record
  already matches metadata. All permitted file scoring is preserved.

## Demo WebUI timing

Five fresh submissions and five Next actions per phrase, ten rows per page,
using the signed-in Chrome session against the managed local demo stack.
`demo` returned 296 results (199 records, 97 aggregations). The broad phrase was
`demo OR test OR record OR file OR وثيقة OR ملف OR a OR the`, capped at 1,000.

Browser timing starts at the native click and ends after ten replacement rows
appear and two animation frames provide a paint opportunity. Automation command
time is recorded separately. These are medians, **not maximum guarantees**.

| Actual browser time | Before | After | After range |
| --- | ---: | ---: | ---: |
| `demo`, first page | 301.0 ms | 177.5 ms | 159.8–406.3 ms |
| `demo`, Next | 143.7 ms | 108.1 ms | 76.6–156.5 ms |
| Broad, first page | 607.5 ms | 439.5 ms | 421.6–462.1 ms |
| Broad, Next | 266.9 ms | 176.1 ms | 142.1–208.8 ms |

The first `demo` sample after reload was 406.3 ms and is retained in the report.
Its initial ranking took 238.1 ms, compared with a five-sample median of 44.1 ms.
No first sample or slow sample was discarded. This is not a controlled cold-disk
comparison; local plan/buffer state differs between runs.

| Median measurement | `demo` first | `demo` Next | Broad first | Broad Next |
| --- | ---: | ---: | ---: | ---: |
| Automation command duration | 305.0 ms | 302.0 ms | 518.0 ms | 294.0 ms |
| Paired automation time beyond browser time | 121.5 ms | 201.9 ms | 71.7 ms | 119.9 ms |
| Search HTTP round trip from WebUI | 96.2 ms | 44.6 ms | 339.5 ms | 114.1 ms |
| Ranking | 44.1 ms | none | 129.3 ms | none |
| Cache save/read | 1.5 ms | 1.4 ms | 5.3 ms | 2.0 ms |
| Current page match/access checks | reused from ranking | 13.0 ms | reused from ranking | 19.6 ms |
| Batched page evidence and display flags | 32.8 ms | 13.4 ms | 188.6 ms | 73.4 ms |
| Additional record capabilities requests | 0 | 0 | 0 | 0 |
| SQL statements in the search request | 12 | 10 | 12 | 11 |

Stage medians are independent and must not be added as if from one sample.
Before batching, the corresponding search SQL counts were 37, 29, 51 and 34,
plus respectively 90, 0, approximately 300 and 60 statements in subsequent
capabilities requests. A prior batching measurement also observed one additional
settings-refresh statement. Every measured Next used `_read_global_search`; none ran
`_rank_global_search`. The remaining broad-page enrichment time is SQL work,
not a repeated full search or a capabilities HTTP request.

Raw local evidence: `.runtime/search-latency-batch-final/paired-measurements.json`,
`webui.jsonl`, `api.jsonl`, source hashes/backups and `cleanup.json`. Diagnostic
disk writes use a background queue, never the API/WebUI event loop. Probes were
removed and both edited application files restored to their post-fix hashes;
the final browser check confirmed no probe script remained.

English/LTR repeated paging and Arabic/RTL first/Next/Previous navigation were
verified for both phrases. English and the original Asia/Dubai timezone were
restored, and the user tab was left on the dashboard. No translation keys or
wording changed in this follow-up.

## Disposable correctness and performance gate

Command:

```sh
backend/services/api/.venv/bin/python tools/check_search_performance.py --output .runtime/search-performance/page-batch-candidates-20261113
```

The runner created and removed
`erms_search_perf_ca3685f7e7284872aa1b961d1d349e1e`. Canonical schema and reference
seeds; 51,003 aggregations, 153,009 records/components and 306,018 chunks;
1,000-result cap; 100-row pages. Standard post-load `VACUUM ANALYZE`, no search
or oracle warm-up, broad combined case first, three repetitions and both
authorized and denied identities. The [gate contract](../search-performance.md)
describes all thirteen criteria and the independent oracle.

All **192 responses passed**, including exact counts, ranked IDs/scores, every
page, capped totals and denied access. Broad combined first-page times were
**2.7375, 2.1978 and 2.2948 seconds**. The maximum later-page time was
**0.4848 seconds**. Selective-index plan assertions passed. All individual
samples, expected/received lists, plans, environment and cleanup evidence are
retained in the output directory.

The broad combined record plan confirms zero executions of the redundant
chunk-matching scan while the chunk-scoring scan still processed all 306,018
chunks. The warm record-plan execution fell from about 2.20 to 1.87 seconds.
These plan timings include instrumentation and are separate from API timings.

An intermediate batching run passed at 2.9960 seconds, but the next full rerun
failed at **3.1668 seconds** for the initial broad response. It was not discarded
or excused by its faster repeats. Its plan exposed roughly 475 ms of candidate
construction, including redundant file matching for metadata hits. The final
change described above removed that work and passed the full gate. Retained
evidence is under `page-batch-20261113`, `page-batch-final-20261113` (the failing
run) and `page-batch-candidates-20261113` (the final pass); all three databases
were dropped. The runner now also records per-request stage times without
extra queries or synchronous logging.

The final margin below the gate is about 263 ms. This is a local regression result, not a
three-second guarantee on arbitrary hardware or under concurrent production
load. The maintenance preparation is not a cold-disk or unvacuumed-import SLA.

Focused regressions cover the original search/authentication cases, exact
batched-versus-legacy evidence and scores, canonical list/view permission
decisions, content freshness, and real concurrent session locks. The lock tests
hold a session reference while authentication completes, then separately block
authentication behind a session update, verify other requests can progress on
the same event loop, revoke the session, and assert the waiting request is
rejected. WebUI tests cover response-supplied display flags, duplicate paging,
expired-list recovery and abandonment after navigation/logout/newer searches.

The component-filter regression accepts any used, valid index whose leading
key is `record_id`, and still verifies record correlation. The unchanged default
compiler SQL chose the existing covering index including `size_in_bytes`; an
assertion requiring only `digital_components_record_id_idx` was unnecessarily
specific. The latency and selective full-text GIN requirements remain unchanged.
