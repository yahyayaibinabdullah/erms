# Classification Tree: Last Commit Versus Current Changes

**Date:** 27 November 2026. **Status:** Comparison and correctness checks complete.
The three-second response requirement failed in both versions. No application
or optimization changes were made for this comparison.

## Finding

These measurements **do not establish that the custom code generator caused a
slowdown**. The current median was 1.64% higher; its average, p95 and maximum
were also higher, and all those samples are retained. These results do not
prove zero overhead.

Results varied substantially within each version and changes for individual
pages went in both directions. Baseline pass medians ranged from 3.741 to
5.931 seconds. The host was busy and its load changed during the comparison.
The slowest current page lists **child classifications**; its exact count/page
SQL and parameters match the last commit and do not use the new number sorting.
The evidence supports pre-existing slow pages and considerable run-to-run
variation; it cannot confidently separate a small feature cost from that variation.

## Comparable API timings

Baseline is commit `997a49a2051d8f7d3301b558167f4288d98d1241`. Current is the preserved working
checkout, including all existing uncommitted custom-generator changes.

| Measure | Last commit | Current |
| --- | ---: | ---: |
| Timed API requests | 152 | 152 |
| Correct IDs, totals, ordering, paging and access | 152/152 | 152/152 |
| Average | 4.264 s | 4.618 s |
| Median | 4.889 s | 4.970 s |
| p95 | 9.035 s | 10.980 s |
| Maximum | 15.722 s | 21.231 s |
| Requests over three seconds | 110 | 112 |

Every request is a bounded interactive page. These are target failures, even
when results are empty. A successful recorder exit means measurement,
correctness and cleanup completed; it does not mean latency passed.

p95 uses nearest rank. There are only four repetitions for each caller/case/page,
so this is an observed comparison on a shared host, not a production latency
guarantee or a statistically conclusive finding about small regressions.

## Fixture and controls

This repeats the [previous representative classification-tree profile](classification-tree-representative-2026-11-27.md):

- 51,003 aggregations, 153,009 records and 153,009 digital components; no file-text
  chunks, which these tree requests do not read.
- 50,000 root aggregations across 500 populated terminal classifications,
  100 per classification, plus an empty terminal classification and five groups.
- 1,003 child aggregations: ten parents have 100 children each and one has three.
  Tested parents 1 and 101 each have 100 children and 100 records.
- 50-item pages. All continuation pages are followed. Initial child and record
  pages are requested concurrently when expanding an aggregation, as in the UI;
  subsequent pages are independent requests.
- Both an authorized reader and a signed-in caller without resource ACL grants.
  Hidden roots stay hidden, classification counts expose no unauthorized roots,
  and denied parent requests return 404.
- Exact independent expected IDs/order, totals, bounded page sizes, cursor
  termination and no missing or duplicated IDs are checked. Both versions
  return the same complete memberships. Their expected order differs where
  current number sorting intentionally changes the old alphabetic order.

This is the same distributed representative fixture; the separate stress shape
of 50,000 roots under one classification is not measured here. Such a branch's
bounded pages still have the three-second requirement.

The last commit was exported with `git archive`; no checkout, branch or worktree
operation was used. The archive commit ID and every regular extracted file were
verified. Separate API processes load each version's own application modules;
retained module-origin checks reject mixing source copies. Both use the same
installed dependencies and Python 3.11.9.

One database was initialized from the last commit's canonical schema (125) and
separate seeds, then reshaped with the common tree fixture and VACUUM ANALYZE.
Two databases were cloned from it, preserving identical core rows and initial
statistics. Only the current clone received migration 126 and the two disabled
but attached number-generator definitions from the previous benchmark.
Those bindings exercise `erms_code_natural` sorting even while generation is
disabled; the counter table remains empty. Only the new generator table was
analyzed separately; core-table statistics were not resampled for either copy.
SHA-256 fingerprints of 17 resource, permission and creation-history datasets
match exactly after the run.

Both versions use the same disposable Linux PostgreSQL 18.4 image
`sha256:a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636`.
LLVM/query compilation is available and remains enabled. Checksums, fsync and
full-page writes remain on; memory, planner and storage settings are unchanged.
There was a 60-second idle period after preparation, without a search warm-up.
No other test or browser workload from this task ran concurrently. Existing
host processes were observed, not stopped.

These are TestClient API response timings including authentication, SQL and
serialization. Browser rendering and HTTP network transit are excluded, just
as in the prior benchmark.

## Run order and host conditions

The sequence is baseline/current/current/baseline, repeated twice. Each version
has four passes and balanced early/late positions. Each pass makes 38 timed
requests. This reduces order bias but does not eliminate changing host load.
Host load and executable-only process snapshots were sampled every ten seconds.
The host reports eight CPUs; load average also includes other runnable/waiting
work and is not a direct measurement of database CPU utilization.

| Pass | Version | Median | p95 | Maximum | Over 3 s | Host one-minute load range |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | baseline | 3.741 s | 6.241 s | 9.113 s | 26/38 | 5.97–8.15 |
| 2 | current | 4.501 s | 13.545 s | 21.231 s | 28/38 | 5.89–9.22 |
| 3 | current | 4.691 s | 7.607 s | 10.989 s | 28/38 | 7.02–9.18 |
| 4 | baseline | 5.002 s | 9.267 s | 11.897 s | 28/38 | 7.74–11.40 |
| 5 | baseline | 5.226 s | 8.689 s | 11.977 s | 28/38 | 7.68–9.99 |
| 6 | current | 5.093 s | 7.836 s | 11.790 s | 28/38 | 7.72–9.98 |
| 7 | current | 6.223 s | 13.306 s | 14.139 s | 28/38 | 8.61–13.44 |
| 8 | baseline | 5.931 s | 11.531 s | 15.722 s | 28/38 | 12.73–15.05 |

## Every caller, case and page

Each row below has four requests per version. “Denied” is a signed-in caller
without access to these resources. First and next pages are kept separate.
The complete p95/max/failure counts per row are in `scorecard.json`; every
individual response, request parameters and above-target sample are in the CSVs.

| Caller | Case | Page | Last-commit median | Current median | Change |
| --- | --- | --- | ---: | ---: | ---: |
| Denied | Child aggregations, parent 1 | first | 0.018 s | 0.016 s | -11.8% |
| Denied | Child aggregations, parent 101 | first | 0.015 s | 0.011 s | -25.9% |
| Denied | Child classifications | first | 3.833 s | 4.201 s | +9.6% |
| Denied | Child classifications | next | 3.582 s | 4.492 s | +25.4% |
| Denied | Top-level classifications | first | 3.983 s | 3.866 s | -2.9% |
| Denied | Empty child-aggregation branch | first | 0.014 s | 0.015 s | +6.1% |
| Denied | Empty classification | first | 5.321 s | 5.223 s | -1.8% |
| Denied | Empty record branch | first | 0.014 s | 0.014 s | +1.6% |
| Denied | Root filter, no matches | first | 4.432 s | 4.659 s | +5.1% |
| Denied | Filtered records | first | 0.013 s | 0.011 s | -13.6% |
| Denied | Filtered roots | first | 5.160 s | 4.818 s | -6.6% |
| Denied | Roots, second classification | first | 4.992 s | 5.163 s | +3.4% |
| Denied | Records, parent 1 | first | 0.018 s | 0.017 s | -5.6% |
| Denied | Records, parent 101 | first | 0.016 s | 0.013 s | -19.9% |
| Denied | Roots, first classification | first | 5.253 s | 5.011 s | -4.6% |
| Denied | Three child aggregations | first | 0.019 s | 0.021 s | +8.4% |
| Reader | Child aggregations, parent 1 | first | 6.680 s | 6.236 s | -6.6% |
| Reader | Child aggregations, parent 1 | next | 4.975 s | 4.543 s | -8.7% |
| Reader | Child aggregations, parent 101 | first | 6.077 s | 5.566 s | -8.4% |
| Reader | Child aggregations, parent 101 | next | 4.990 s | 5.141 s | +3.0% |
| Reader | Child classifications | first | 11.937 s | 12.548 s | +5.1% |
| Reader | Child classifications | next | 8.978 s | 8.404 s | -6.4% |
| Reader | Top-level classifications | first | 5.300 s | 4.707 s | -11.2% |
| Reader | Empty child-aggregation branch | first | 0.025 s | 0.029 s | +14.9% |
| Reader | Empty classification | first | 5.321 s | 5.301 s | -0.4% |
| Reader | Empty record branch | first | 5.216 s | 4.696 s | -10.0% |
| Reader | Root filter, no matches | first | 4.614 s | 4.418 s | -4.2% |
| Reader | Filtered records | first | 6.152 s | 5.431 s | -11.7% |
| Reader | Filtered roots | first | 5.406 s | 5.645 s | +4.4% |
| Reader | Roots, second classification | first | 6.054 s | 5.966 s | -1.5% |
| Reader | Roots, second classification | next | 5.462 s | 6.290 s | +15.2% |
| Reader | Records, parent 1 | first | 7.632 s | 6.957 s | -8.8% |
| Reader | Records, parent 1 | next | 5.718 s | 5.720 s | +0.0% |
| Reader | Records, parent 101 | first | 6.957 s | 6.461 s | -7.1% |
| Reader | Records, parent 101 | next | 5.314 s | 5.867 s | +10.4% |
| Reader | Roots, first classification | first | 6.765 s | 5.930 s | -12.3% |
| Reader | Roots, first classification | next | 5.693 s | 6.271 s | +10.1% |
| Reader | Three child aggregations | first | 0.521 s | 0.570 s | +9.4% |

Large percentages on millisecond access-denied responses should be interpreted
with their absolute times. The raw matched-pair CSV compares each page in the
adjacent baseline/current passes (1/2, 3/4, 5/6 and 7/8); it retains every pair,
including outliers, without treating different pages as identical work.

## Concurrent expansion observations

These time waiting for both first batches, using requests already included in
the 304 total. They are not additional API requests. There are eight observations
per caller/version, 32 total.

| Caller | Last-commit median / maximum | Current median / maximum |
| --- | ---: | ---: |
| Reader | 6.996 / 10.272 s | 6.462 / 14.140 s |
| Denied | 0.019 / 0.027 s | 0.016 / 0.020 s |

## SQL evidence and interpretation

Exact SQL, parameters and EXPLAIN ANALYZE/BUFFERS/SETTINGS plans were collected
only after **all** timed passes. Diagnostic replays and their SQL execution
times are not included in the 304 timed requests, and their later sequential
execution is not used as a controlled API timing comparison.

For both callers, top-level and child-classification count/page SQL and
parameters are byte-for-byte identical in baseline and current captures. The
slowest page in each version is the reader's first child-classification page:
15.722 seconds baseline, 21.231 seconds current. These query captures use the
original ordering, with no generator-binding lookup or `erms_code_natural`.
Consequently the new number collation does not explain those particular SQL
outliers.

For generated-number fields, captures show the intended generator-binding
lookup and natural-order expression. The 18 captured binding lookups took
0.023–0.205 milliseconds of server execution in diagnostic replays. These
figures cover this two-generator fixture and do not measure total request
latency or prove that number sorting has no cost at other data volumes.

The old queries already spend seconds in execution and query compilation.
For example, the baseline diagnostic top-level classification queries report
1.669 and 2.487 seconds of compilation, before considering their other work.
This records existing behavior; no SQL, indexes, query-compiler settings,
permissions or application processing were changed to address it.

The median comparison is close, but the current average and tail are worse.
Individual pages improve and regress, and baseline itself varies considerably.
Host contention is a plausible contributor, consistent with the retained load
observations; this experiment does not isolate it as the only cause or rule out
a small generator-related regression. The result applies to these classification
APIs and fixture, rather than establishing performance for other searches or
creation workflows. All target overruns are retained for separately authorized
performance work.

## Preservation and cleanup

The workspace preservation check covers all 11,014 pre-existing tracked and
nonignored untracked files, including current implementation, specifications,
plan and prior evidence. Their SHA-256 values match the before-run snapshot.
HEAD, Git index bytes and all pre-existing Git status entries are unchanged.
The only new nonignored file from this comparison is this report. Runtime
harnesses, baseline export and detailed evidence remain under gitignored
`.runtime/`. No application file, configuration, translation or search source
was edited, and no commit or publication was performed.

The full run dropped all three uniquely named disposable databases:

- `erms_tree_compare_seed_52328b1cbc7f463598698b77809f6625`
- `erms_tree_compare_baseline_52328b1cbc7f463598698b77809f6625`
- `erms_tree_compare_current_52328b1cbc7f463598698b77809f6625`

Container `erms-search-perf-linux-d403357b51bc4c0aa54e5abb78c8107a` was removed without leaving a volume.
The preliminary small-fixture setup check also passed both versions, source
origin and fixture parity checks, dropped its three databases, and removed its
container. Neither run used a persistent ERMS database.

## Evidence and reproduction

Artifact root: `.runtime/classification-tree/commit-comparison-20261127/`.

- `preparation.json`, `last-commit.tar`, `last-commit/`: exact exported commit,
  common test-driver adaptations and source provenance. The driver accounts
  for the legacy schema's absent generator table and legacy ordering; it does
  not change either application's implementation.
- `workspace-before.json`, `git-before.json`, `workspace-preservation.json`:
  complete file/Git preservation checks.
- `full/tree-fixture.json`, `full/environment.json`,
  `full/comparison.json`: common fixture, unchanged PostgreSQL settings,
  17 dataset fingerprints and successful database cleanup.
- `full/pass-*/tree-results.json`, `tree-expected-ids.json`, `origins.json`:
  every HTTP sample, exact independent ordering and isolated application imports.
- `full/scorecard.json`, `all-http-samples.csv`, `above-three-seconds.csv`,
  `matched-http-pairs.csv`: complete summary, all 304 request timings,
  all 222 above-target samples, and the 152 paired comparisons.
- `full/plans-baseline/`, `full/plans-current/`: exact SQL/parameters and plans;
  current `generator-fixture.json` confirms the two definitions and zero counters.
- `full/host-samples.jsonl`, `full-linux.json`: host observations and confirmed
  Linux container cleanup. `smoke/` and `smoke-linux.json` retain the setup check.

`comparison.py`, `analyze.py`, `write_report.py` and `verify_workspace.py` retain
this run's orchestration and analysis. The launch command was:

```sh
backend/services/api/.venv/bin/python .runtime/classification-tree/commit-comparison-20261127/comparison.py
```

The runner rejects existing measurement directories. A repeat requires a fresh
artifact directory at the same depth and a new before-run source snapshot;
retained evidence must not be overwritten. All changes remain local for the
user to review and commit.
