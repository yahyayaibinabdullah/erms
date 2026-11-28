# Custom Code Generators — Phase 4 Verification

**Status:** Complete, with measured selector latency failures reported for
separate work under the user's direction. **Updated:** 27 November 2026.

**Authority:** [Approved specification revision 0.5](../../specs/custom-code-generators.md), CG-08.

**Current scope, corrected 27 November:** The user identified host contention
behind the variable timings and directed removal of unrelated search changes.
The candidate-join, bounded-ordinal, browse display/count and added JIT-guard
experiments described below have been removed. Their measurements remain
historical evidence, not a description of the current implementation. Only
generator-related natural ordering, cursor and cache semantics remain changed.
Search optimization is deferred to a separate session. The phase 6 report
records verification after this removal; no final latency pass is claimed.

## Final verification and completion

The post-removal correctness suite passed **59 tests**. The final complete
generator matrix passed correctness for **801 responses** on 51,003 aggregations
and 153,009 records: 630 primary/type-specific code-search responses and 171
selector responses. All code-search responses met three seconds, maximum
1.113958 s. There were 129 selector overruns, maximum 11.686756 s.

All criteria, timings, exact expected results, plans, fixture corrections and
successful disposable-database/container cleanup are retained in the
[final performance report](custom-code-generators-final-performance.md).
The earlier partial run is preserved too. The only correction was to the test
fixture's missing Add record grant; no application/search behavior was changed.

Under the user's explicit 27 November instruction and plan revision 0.16,
these measured failures are reported for separate optimization and do not keep
the custom-generator phase open. Natural ordering is implemented and verified;
this completion decision does not claim the strict latency gate passed.

## Implementation and functional evidence

One stored Text value is ordered with deterministic ICU `erms_code_natural`
when a generator remains attached to the field, including disabled definitions.
SQL selects and orders each page. Typed sorts retain secondary keys and null
placement; hierarchy cursors use the same collation for comparisons and ordering.
The existing ranked-list fingerprint includes attached sort fields, rebuilding
the session/tab slot after an ordering change. Renaming, pausing and pattern
changes preserve it. Other fields keep their existing order and matching.

`code_ordering.py`, `search.py`, `type_search.py`, `search_cache.py`, `crud.py`,
`browse.py`, `search_page.py` and disposition report presentation implement these
paths. No duplicate code column, additional cache or code-width index is added.
Manual 20,000-character Text values remain writable and sortable.

The initial focused run exposed three fixture problems (transaction-local actor
reset, uncommitted type visibility and a second actor reset); corrected affected
cases passed. Typed/long-Text checks passed (2), report ordering passed (1), and
the existing browse/cache/type-search/policy run passed (59). Logs are in
`.runtime/custom-code-generators/phase0-20261126/phase4-*.log`; each disposable
database was dropped. No persistent database was migrated.

The ICU diagnostic records provider `i`, deterministic collation version
`153.128` and its actual boundary. Numeric runs of up to 254 significant digits
have numeric ordering; longer runs remain valid and follow ICU's ordering.
The user approved documenting this limit without a digit cap on 27 November.
Leading zeroes do not count; adjacent numeric placeholders form one run.
The spec is revision 0.5. The test also accepts a
300-digit serial with optional padding to 350 characters, within a 400-character
complete-code limit.

## Historical experiments and measurements

All remaining sections record earlier attempts, including changes since removed.

### Full standard run 6 and permission projection

The next measured fix removed a redundant candidate-set join from ordinary
generic search: the canonical authorized set already contains only candidate
IDs. The controlled retained-resource path keeps its distinct candidate and
authorization joins. Sixty-three search/cache/access regressions passed before
the complete run.

`code-generators-phase4-standard-20261127-run6` passed all correctness checks.
All 630 generator-search responses passed (maximum **1.276915 seconds**), as
did 135 reader navigation responses (maximum **1.329754 seconds**) and all 15
denied navigation responses. Broad initial combined search reached 2.6574
seconds, and generic record field-sort reached 0.7723 seconds. Two existing
25-row Global Search UI requests remained over the limit: **3.1529** and
**3.8532 seconds**. These failures were not waived. Database
`erms_search_perf_d7eb87efdd014f339f8a51e46132cf98` was dropped.

The separate isolated Global Search UI profile passed all twelve complete
responses, but its actual combined 25-row plan still took 2,323.467 ms. Its
materialized authorized-record set held 153,009 rows of estimated width 29,
including owning-unit, parent and disposition columns unused by search.
Ranking dominated response time; selected-page details took roughly 56–74 ms.

An experimental compact projection of those same authorization CTEs preserved
access decisions and passed equivalence regressions. A later alternating
comparison over one disposable corpus showed no consistent complete-response
benefit despite narrower rows. The experiment was removed; canonical
authorization code remains unchanged. No extra index, memory allowance,
planner setting or vector-storage change was introduced. See phase 6 for the
comparison and final standard/larger-text gates.

## Large-data run 1

`tools/check_search_performance.py --code-generators-only --repeats 3`
completed correctness on PostgreSQL 18.4 with 51,003 aggregations, 153,009
records and 306,018 chunks. Eight disabled but attached generators cover
primary number/title/description and typed Text fields. There are 68,004 mixed
typed codes, repeated values, multiple digit runs, optional zeroes and missing
values. Real allocations remain zero. Independent SQL oracles are evaluated
after the first measured request; plans are captured after measurements.

All 630 search samples passed the three-second limit; the maximum was
1.329145 seconds. Complete capped IDs, counts, scores, saved execution and
all returned pages agree. Navigation produced 102 reader and 12 denied samples.
All correctness checks passed, but all three broad root selector samples failed:
3.032079, 3.032728 and 3.016199 seconds. These are failures, not rounded passes.

Plans identify a separate 483 ms count and a 2,610 ms page query. The page's
hold-detail lateral join ran for 49,903 authorized candidates before selecting
100 rows. The fix under verification calculates those display details only for
the authorized selected page, preserving complete authorization/count/order.
The page operation uses the existing scoped JIT setting and restores it.
No server-wide planner or memory setting changes.

Artifacts, environment/source hashes, exact expected/received IDs, timings,
plans and cleanup:
`.runtime/search-performance/code-generators-phase4-natural-20261127-run1/`.
Database `erms_search_perf_2f30c24c20b244198444832222042490` was dropped;
`cleanup.json` confirms cleanup. LLVM/JIT is unavailable in the local build;
production Linux verification must retain the scoped JIT protection.

The harness smoke checks passed before the large run. Earlier smoke failures
were oracle bugs (parent-label matching and omitted score evidence), corrected
without changing product matching or scores. The new record keyset selector
coverage and the page-enrichment fix still require verification. Full affected
and unaffected performance acceptance remains open. The phase 0 standard and
larger-text failures remain recorded and are not waived by these results.

## Selector regression verification

`phase4-browse-page-enrichment.log`: **40 passed** in 64.70 seconds, covering
the code-order suite, existing hierarchy browser and search-execution tests.
Inherited hold counts/state-blocking flags agree on pages and summaries.
Successful and rejected cursor requests restore both incoming JIT settings.
Database `erms_messaging_test_acl_a9bc747c02c24f02bf85a91fe9ba8e62` was dropped.

The full standard gate includes existing resource/type-Text cases, all new code
cases and added record-selector traversal.

Run 2 stopped before the generator matrix: a grouped cached page rebuilt its
expired list. The host monitor contains only 174 samples over 4,073 seconds,
including four gaps of 780–1,063 seconds. These host execution pauses exceed
the normal cache inactivity lifetime; they are not evidence of a broken cache
fingerprint. The isolated grouped/ungrouped paging reproduction passed in a
fresh database (1 test, 8.52 seconds), then dropped it. Run 2's database
`erms_search_perf_6680adb49d07462cb13010b74c227eb2` was also dropped. Its
partial results and host observations remain available. Run 3 uses macOS
`caffeinate -i` only for the benchmark process, without changing application
expiry, a persistent power setting or the acceptance limit. Full acceptance
is still pending.

## Separately approved Arabic correction

On 27 November the user explicitly approved replacing only
`settings.field.search_result_limit.description` with
«الحد الأقصى لعدد النتائج في جميع صفحات البحث الشامل والبحث المتقدم وعوامل تصفية الملفات أو الوثائق.»
This supplies the filters omitted by the prior curated translation. The prior
text and its complete provenance remain in the corrected item's provenance.
The pre-existing guarded seed-replacement list is preserved unchanged.
Before/after evidence is in
`approved-search-limit-arabic-correction.json` beside the phase logs. The new
provenance records user review, without claiming a database publication or a new
administrator export. All other existing curated wording remains unchanged.
The maintained context-aware glossary check passes all 993 uses of 35 mappings.
Catalogue references and 4,215 active-key coverage agree; all 19 new generated
drafts pass their stricter generation-time validation. Applying that draft-only
literal checker to the entire pre-existing curated artifact flagged context and
diacritic variants, an existing glossary spelling mismatch and the email `Re:`
marker; those curated values were preserved. The maintained context-aware
checker, rather than a rewrite of those entries, supplies full glossary evidence.

## Full standard run 3 and remaining selector work

`code-generators-phase4-standard-20261127-run3` completed every correctness
case and dropped database
`erms_search_perf_e8b606138c774c00a9a688d6ea17134d`. It retained 824 host
observations and completed the cache traversals that the suspended run could
not complete. The strict gate **failed eight samples**:

- Existing broad combined Global Search: 3.0135 seconds (first page).
- Existing initial Global Search UI sizes: 3.2039 seconds (10 rows), and
  3.4607, 3.2283 and 3.6229 seconds (25 rows).
- Natural-code broad root selector: 3.910880, 3.830333 and 4.126587 seconds.

All 630 code-sorted search responses passed (maximum 1.846049 seconds).
Navigation has 135 reader and 15 denied samples, including the added record
keyset selector. Maximum reader times outside the failed broad roots are
0.184748 seconds (contained records), 2.002162 (record selector), 0.415061
(child selector) and 2.065900 (root prefix selector). Each complete 1,100-row
traversal agrees with its independent SQL oracle and preserves the tab cache.

The root page plan still took 3,038 ms: inherited-location and vital-descendant
functions were projected for 49,903 candidates before sorting. Moving only the
hold lateral join was insufficient. The next fix also bounds these display
functions to selected IDs, calculates each source once, and resolves visibility
of source labels through the canonical batch authorization CTEs. A regression
checks inherited values, vital descendants and hidden-source redaction. Actual
display-query plans are added to the affected benchmark. Verification remains
open; the five unrelated Global Search failures are not declared passes.

`phase4-bounded-display-details.log` passed 21 cases and failed the new hidden-
parent fixture: its default owning-unit grant still allowed the parent. After
explicitly removing that grant and asserting the parent's API response is 404,
the location/source-redaction and inherited-hold cases both passed (7.23 seconds,
`phase4-bounded-details-scoped-fixture.log`). Both disposable databases were
dropped. The actual source-visibility decision uses the shared canonical batch
authorization; no per-item authorization-function workaround is introduced.

The affected large-data gate is being repeated as
`code-generators-phase4-natural-20261127-run4`, including actual plans for the
bounded display statement. It will not waive the separate broad Global Search
failures from run 3.

## Affected run 4

All correctness checks completed and database
`erms_search_perf_c31ccc083dd84566a518502cf0d9eccf` was dropped. Every selector
response passed (135 reader and 15 denied responses, reader maximum
1.966158 seconds). This verifies the page-only display fix.

The gate still **failed six search samples**: record description first pages
3.726768/3.893392/3.642410 seconds, and typed ascending first pages
5.575238/4.126223/3.322150 seconds. The retained plans have the same nodes and
temporary-block counts as earlier runs, with slower authorization as well as
sorting. The host monitor records concurrent antivirus, browser and indexing
activity; this observation does not establish their causal contribution, and
no unrelated service or security setting was stopped or changed.

The description plan sorts 153,009 full Text sort keys into a 57 MB temporary
file before a window can assign the first 1,001 ordinals. The next measured
change extends the existing field-sort `score_candidates` reduction to searches
without full-text leaves: match and authorize all candidates, select the exact
top `cap + 1` using the same complete sort, then assign ordinals. Relevance
ranking is unchanged. Focused result/score/null/cursor/cache tests and another
affected performance gate remain required; no failed sample is waived.

## Bounded ordinals and affected run 5

The field-sort reduction now also covers searches without full-text leaves.
PostgreSQL still matches and authorizes all candidates, then selects the exact
first `cap + 1` using the complete requested ordering before assigning ordinals.
The relevance branch is unchanged. Result, score, null, cursor, type-search and
cache regressions passed: **44 tests in 144.29 seconds**
(`phase4-bounded-ordinal-regression.log`). Database
`erms_messaging_test_acl_2e3507f3bcc4492db257c13e62c55ed9` was dropped.

`code-generators-phase4-natural-20261127-run5` completed all correctness checks,
630 search responses and 150 selector responses. All selector responses passed;
the reader maximum was 2.438314 seconds. Four record-search first pages still
**failed** the three-second limit:

- Ascending, repeat 0: 3.051370 seconds.
- Descending, repeat 0: 3.005085 seconds.
- Prefix, repeat 1: 3.153891 seconds.
- Metadata, repeat 2: 3.683600 seconds.

The description plan now uses a 557 KB top-N sort instead of the 57 MB
temporary-file sort; its measured execution was 1,318.576 ms. The typed ascending
plan uses a 167 KB top-N sort and executed in 1,431.704 ms. These plan improvements
do not turn the failed complete API timings into passes. Database
`erms_search_perf_b7c3ca58b78d404cbc8453a61ed23a2b` was dropped.

At this historical checkpoint, phase 4 remained in progress and final standard
and larger-text measurements were pending. Plan revision 0.13 permitted
independent phase 5 UI work against verified APIs. The current completion rule
is plan revision 0.16, following the user's instruction to report slow timings
for separate optimization work rather than tune search during this feature.
