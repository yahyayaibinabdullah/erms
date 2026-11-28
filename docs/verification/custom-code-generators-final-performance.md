# Custom Code Generators: Final Performance Measurements

**Date:** 27 November 2026. **Authority:** Approved specification 0.5 and
implementation plan 0.16.

**Status:** Complete. All final correctness checks passed. Search/selector
timing failures are recorded for separate work under the user's direction.

The user directed that search responses over three seconds be recorded and
reported for future dedicated optimization, without tuning search during this
feature. The three-second threshold is unchanged. Completion of implementation
does not mean every timing passed. No search optimization was made during this
final measurement round.

## Environment and measurement scope

### Classification-tree scope clarification

The actual classification browsing tree fetches **50 items per expanded
branch**, using `APIClient.browse_page`'s default limit. The relationship browse
dialog explicitly requests the same 50-item limit. Further batches are loaded
through the returned cursor; expanding a branch does not fetch its entire
collection. These are bounded API responses.

The recorded browse benchmarks requested **100 items per page**, with 1,100
children under one aggregation and 49,903 root aggregations under one
classification. That is a concentrated stress fixture, not a measured profile
of the user's expected classification-tree usage. The 11.686756-second sample
returned the eleventh 100-item page of 1,100 filtered root aggregations; it did
not return all roots in one request. The unfiltered-root cases also fetched
only the first 100 items.

The separate ten-item chronological child-list test uses the aggregation
details screen's `/aggregations/search` path. Its 61 slow requests must not be
presented as classification-tree timings.

For representative classification-tree measurements, the user identified
50-item batches and approximately 100 immediate child aggregations per parent
as the relevant profile, with roots distributed across classifications. That
profile was **not measured in the generator close-out round**. Existing stress timings remain
valid for their stated dataset and requests; they do not establish normal tree
interaction latency. No runtime limit of 100 children is introduced.

The API separately calculates matching totals and selects each ordered page,
so a 50-item response does not imply PostgreSQL touches only 50 rows. Actual
latency for the representative profile requires its own measurement. This
clarification adds no search optimization or application change.

The user further clarified that a classification with about 50,000 root
aggregations is a valid stress case and that **each bounded 50/100-item page
still has a three-second limit**. The exception concerns returning the entire
50,000-item collection at once. Consequently, the paged overruns below remain
page-response limit failures; stress classification does not excuse them.
They are retained for separate optimization without changing this implementation.

A subsequent [representative tree measurement](classification-tree-representative-2026-11-27.md)
has now tested 50-item batches and 100 child aggregations per tested parent.
All 114 API requests returned correct results; 84 missed the three-second page
limit (median 4.284 s, p95 7.229 s, maximum 10.142 s). No application/search
optimization was made. This is a separate profile, not a controlled speed
comparison with the concentrated dataset below; the earlier totals remain intact.

### Recorded stress environment

Measurements use PostgreSQL 18.4 on Linux from the existing local image
`sha256:a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636`.
The runner creates a new disposable database/container for each workload.
Checksums, fsync and full-page writes remain enabled; storage is on the
container's writable disk layer. File-text vector storage policy retains MAIN/LZ4.
There are no server-wide planner or memory changes. LLVM/JIT availability,
execution plans, settings, source hashes and host observations are retained.

Each criterion is repeated three times, after 60 seconds of post-load idle
time without search warm-up. The result cap remains 1,000 where applicable;
uncapped lists are traversed beyond it. Correctness checks compare expected
counts, complete ordered IDs/scores, page boundaries and denied access.
These are complete API response measurements on a shared host, not a
production throughput or concurrency guarantee. Workloads run sequentially,
without another test suite or browser workload from this task.

## Ordinary searches on the final application code

The standard fixture contains **51,003 aggregations, 153,009 records and
306,018 file-text chunks**, with mixed typed/untyped resources.
All **1,754 ordinary-search API responses** passed correctness checks.

| Flow | Responses | Over 3 seconds | Maximum |
| --- | ---: | ---: | ---: |
| Global Search, including 25/100-row UI pages | 210 | 0 | 2.7616 s |
| Structured filters, Advanced Search, saved execution and tab-cache paging | 684 | 0 | 2.4564 s |
| Contained-record lists | 273 | 0 | 0.4291 s |
| Chronological child-aggregation lists | 339 | 61 | 4.0604 s |
| Type-specific Text matching/ranking/revocation | 188 | 0 | 0.696092 s |
| Aggregation record activity | 18 | 0 | 0.117412 s |
| Audit search/list paging | 42 | 0 | 0.095168 s |

The 61 child-list overruns range from **3.0004 to 4.0604 seconds**. Their
criteria are parent IDs 1/51003, ascending `date_opened` then ID, ten rows per
page, and complete traversal across three repeats. Reader traversal includes
1,100 children; the denied caller returns none. These timings are follow-up
work, not an instruction to change the query here.

The broad combined Global Search criterion `common OR universal` returned the
expected capped ranked list from 204,012 matching resources, maximum 2.7582 s.
Broad file-content search `universal` matched 153,009 records, maximum 1.5920 s.
No broad-search regression is inferred from unrelated historical runs under
different host conditions.

Artifacts:
`.runtime/search-performance/code-generators-final-clean-standard-20261127/`.
The machine-readable summary is
`.runtime/custom-code-generators/phase6/final-clean-standard-summary.json`.
Database `erms_search_perf_db2a37e770e3435788010b62804957f9` was dropped and
container `erms-search-perf-linux-c80640ff8e6649fbaa36ccbb445593fe` was removed.

## Preserved fixture failure and corrected generator measurement

After the ordinary matrix completed, the initial generator matrix stopped at
`root_creation_prefix`: its oracle expected 368 selectable aggregations, while
the API correctly returned zero. The synthetic reader had View grants but
lacked `aggregation.add_record`. This was a benchmark-fixture error, not a
generator or search behavior defect.

Only the generator fixture was corrected: the synthetic reader receives the
required Add record grant; the denied caller is unchanged. Existing global
privileges, owning-role eligibility, open/digital conditions and typed Use
restrictions remain enforced. The independent oracle still expects only the
eligible untyped roots. No application authorization rule was changed.

The corrected harness smoke test passed in a new disposable database:
**one test passed in 27.85 seconds**, including allowed/denied selectors.
Database `erms_messaging_test_acl_320a78c7cdf34ca88ca5d9a335015e5a` was dropped.
Evidence: `final-harness-fixture-smoke.log` under the phase 6 runtime directory.

The original partial generator results remain preserved: 558 sorting responses
matched their expected output, maximum 1.206108 s; 136 selector responses were
recorded before the fixture assertion. Of those selectors, 103 exceeded three
seconds, maximum 6.932121 s, including the request that exposed the oracle
error. These partial results are not claimed as a complete generator run.

The generator-only runner reuses the full standard-sized fixture and all
generator criteria. It completes the affected matrix without repeating the
already-completed ordinary searches. Its final results are recorded below.

## Complete generator matrix

All **801 responses passed correctness checks**, including exact numeric
ordering, secondary keys/nulls, saved lists, complete paging and denied access.
All eight definitions remain disabled but attached, and the real counter table
remains empty: this measures sorting, not number allocation.

| Flow | Responses | Over 3 seconds | Maximum |
| --- | ---: | ---: | ---: |
| Primary/type-specific code sorting, filters and saved search | 630 | 0 | 1.113958 s |
| Relationship and creation-destination selectors | 171 | 129 | 11.686756 s |

Selector overruns are retained for separate optimization:

| Selector criterion | Over 3 seconds | Range |
| --- | ---: | ---: |
| Records in an aggregation | 33 | 4.066646–4.496096 s |
| Immediate child aggregations | 33 | 3.650562–4.446991 s |
| Root aggregation prefix `PERF-15` | 36 | 3.749386–11.686756 s |
| Broad root aggregation page | 6 | 3.764948–7.191787 s |
| Record-creation roots, prefix plus owner/digital/type Use rules | 15 | 4.177260–5.889658 s |
| Broad record-creation root page with those rules | 6 | 4.083203–6.082614 s |

These samples include the reader and denied caller. A timing failure never
changes an expected count, authorization rule or page order. The benchmark
exited nonzero because of the 129 timing failures, after all correctness checks
completed. It is not a strict latency pass, and no query was changed in response.

Artifacts:
`.runtime/search-performance/code-generators-final-clean-ordering-20261127/`.
The complete summary, criteria and every slow sample are in
`.runtime/custom-code-generators/phase6/final-clean-ordering-summary.json`.
Database `erms_search_perf_ce863882f2954834a79dcb4dcece26a5` was dropped and
container `erms-search-perf-linux-147f41d8df7d48d4b7f2051ad2765489` was removed.

## Larger-text regression

The final larger-text fixture has **51,003 aggregations, 153,009 records and
180,630 chunks**, including the existing 10/100-chunk outliers and larger
vectors. Actual compression checks found all 180,630 chunk vectors compressed
with LZ4. LLVM/JIT was available. Existing scoring-node loop and complete
uncapped-membership assertions passed, alongside exact ranked results,
page boundaries and denied access.

All **643 API responses** passed correctness and the three-second threshold:
428 larger-text responses, maximum **2.784820 s**, and 215 type-specific Text
responses, maximum **0.603489 s**. The benchmark exited successfully. Its
application-source hash checks passed too.

Artifacts:
`.runtime/search-performance/code-generators-final-clean-large-text-20261127/`.
Summary:
`.runtime/custom-code-generators/phase6/final-clean-large-text-summary.json`.
Database `erms_large_text_2464ff387fe844c480dfe4719e4445ae` was dropped and
container `erms-search-perf-linux-c5c35ceb31994479a76f823bbbec1a62` was removed.

## Close-out and separate performance work

The final measurement set comprises **3,198 API responses with correct
results**: 1,754 ordinary searches, 801 complete generator cases and 643
larger-text cases. The original partial generator attempt is preserved but is
not counted again in that total. The type-specific Text harness also records
one direct SQL edit/commit observation per workload. Both observations remain
in the summaries as `non_http_observations`; they are excluded from API totals.

There are **190 numerical timing failures** in the final set: 61 chronological
child-list responses and 129 relationship/creation-destination selector
responses. The maximum is **11.686756 s**. Ordinary Global Search, broad
structured/saved searches, generator sorting and the larger-text searches
met three seconds in these runs. The selector/child-list findings are reported
for a separate optimization session. No optimization was adopted here, and the
combined measurement set is not described as a strict latency pass.

The user's 27 November instruction permits feature completion with these
findings recorded. Plan revision 0.16 closes phases 4/6 on that basis, with
implementation/correctness, browser, upgrade and handoff evidence preserved.
This is not deployment or publication approval.

Final source checks compare against commit
`997a49a2051d8f7d3301b558167f4288d98d1241`. The only remaining search/list/report
changes implement natural ordering, stable cursors/ties and cache semantics.
Global Search ranking, search route functions, shared authorization and existing
execution-setting guards are unchanged. Application/schema/translation sources
stayed unchanged throughout final measurement; only the two benchmark tools
were corrected for the fixture grant and isolated-workload forwarding.
All 87 changed Python files compile and `git diff --check` passes. Evidence:
`.runtime/custom-code-generators/phase6/final-source-and-baseline-checks.json`.

The full remote CI pipeline was not run, and no repository change was published
to invoke it. Local Linux measurements and the other executed checks are
reported in the [integrated phase 6 report](custom-code-generators-phase6.md).

## Executed commands

The image ID above was supplied to each command below. Each output directory
was new. The first run's ordinary matrix completed before the preserved fixture
assertion; the second run completed the corrected generator matrix and exited
nonzero solely for recorded timing failures; the larger-text run exited zero.

```sh
backend/services/api/.venv/bin/python tools/run_linux_search_performance.py --image sha256:a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636 --workload standard --resource-types --type-text --code-generators --repeats 3 --settle-seconds 60 --output .runtime/search-performance/code-generators-final-clean-standard-20261127
backend/services/api/.venv/bin/python tools/run_linux_search_performance.py --image sha256:a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636 --workload standard --code-generators-only --repeats 3 --settle-seconds 60 --output .runtime/search-performance/code-generators-final-clean-ordering-20261127
backend/services/api/.venv/bin/python tools/run_linux_search_performance.py --image sha256:a02db8cac496f15b094798a38254f14d6e00741f709360e5e00bb6668ea31636 --workload large-text --resource-types --type-text --repeats 3 --settle-seconds 60 --output .runtime/search-performance/code-generators-final-clean-large-text-20261127
```
