# Custom Code Generators: Integrated Verification

**Authority:** Approved specification revision 0.5. **Date:** 27 November 2026.
**Status:** Complete for the local implementation, with search timing failures
recorded for separate optimization under the user's direction. No strict
latency pass or deployment approval is claimed.

All changes remain local and uncommitted. No persistent database upgrade,
deployment, branch operation or publication has been performed.

## Final close-out

All phases 0–6 and CG-01–15 implementation/correctness coverage are complete.
The [final performance report](custom-code-generators-final-performance.md)
records final measurements on the application code after unrelated search
changes were removed:

- 1,754 ordinary-search API responses passed correctness. Global Search,
  structured filters, saved search and cached paging met three seconds;
  61 chronological child-list responses exceeded it, maximum 4.0604 s.
- The complete generator matrix passed correctness for 801 responses. All
  630 code-search responses met three seconds, maximum 1.113958 s; 129 of
  171 selector responses exceeded it, maximum 11.686756 s.
- All 643 larger-text/type-specific Text API responses passed correctness and
  latency, maximum 2.784820 s. Scoring-loop and complete-membership checks passed.

All **3,198 final API responses** have correct results. The two direct SQL
edit/commit observations in the harness are preserved separately, not counted
as HTTP responses. The original partial generator run and its missing-fixture-
permission assertion remain preserved; a corrected fixture smoke test passed,
then the full affected matrix completed. No application rule was changed.

Under the user's explicit close-out direction and plan revision 0.16, the
**190 timing failures** are reported for separate dedicated optimization.
They remain failures and do not keep custom generator implementation open.
Every disposable database/container from these runs was removed.

The classification-tree scope clarification in the final report distinguishes
the actual 50-item-per-branch UI from the benchmark's 100-item browse requests
and concentrated 1,100-child fixture. Those are stress timings, not measured
normal classification-tree latency. The separate chronological child-list
case exercises the aggregation details screen. The representative profile was
not measured during generator close-out. A [subsequent tree verification](classification-tree-representative-2026-11-27.md)
now records 114 correct 50-item API requests with 100 child aggregations per
tested parent; 84 exceeded three seconds. Those failures are reported for
separate work, with no application changes or optimization.

The final source comparison against commit `997a49a2051d` passed. Application,
schema and translation sources were unchanged during final measurement; only
the two benchmark-tool corrections were made. Global ranking, search routes,
shared authorization and existing execution guards match the commit; remaining
search changes implement the required natural ordering. All 87 changed Python
files compile and `git diff --check` passes. Evidence:
`final-source-and-baseline-checks.json` under the phase 6 runtime directory.

Final policy generation, configuration ownership (131 settings), API template
consistency (37 entries), current catalogue references, all 35 Arabic glossary
mappings/1,006 contextual uses, original translation provenance, draft quality
and artifact hashes passed. Active coverage is 4,337 keys, with 141 new Arabic
drafts needing normal human review. The executed broader API/database, WebUI,
canonical/archive and populated-upgrade results below remain valid; these
overlapping suites are not added together as a unique-test total.

Operator guidance is complete. Applying migration 126 to an existing
installation, coordinated API/client upgrade, Arabic review/publication and
the user's commit/deployment decision remain operator actions. Full remote CI
was not run and no changes were published to trigger it.

## Scope correction: unrelated search changes removed

On 27 November, the user confirmed that comparable searches ran below or just
above three seconds on previous days, attributed the slower runs to host
contention, and directed removal of unrelated search optimization. Search
optimization will be separate work in a separate session. This boundary is
recorded in AGENTS.md and implementation-plan revision 0.15.
For future test runs, any search timing over three seconds must be recorded
and reported for separate dedicated optimization, without starting unrelated
search changes during feature work. A reported failure remains a failure.

Removed from the current implementation:

- Generic-search candidate-join and no-full-text top-N rewrites.
- Browse display enrichment and child/record count rewrites, including new
  root-candidate prefilters.
- Additional JIT guards on ordinary search and browse, plus their experimental
  tests. Existing guards and their original tests remain unchanged.

The compact authorization experiment had already been removed. Global Search
ranking/candidate SQL is unchanged from the branch baseline. Remaining search
changes implement the approved attached-field natural ordering, matching
cursors, deterministic ties and cache invalidation. The generator creation,
administration and audit implementation is retained.

The benchmark harness now captures plans for the restored browse statements
and no longer imports removed helpers or changes their JIT setting for EXPLAIN.
An ignored copy of the removed experiments is retained under
`.runtime/custom-code-generators/phase6/scope-cleanup/` for evidence only.
Later sections preserve historical results, including failures; they do not
describe adopted optimizations or establish a final latency pass. No further
search tuning is being pursued as part of this feature.

Post-removal correctness verification passed **59 tests in 206.82 seconds**:
attached primary/typed ordering, natural cursors, cache replacement and current
permissions, existing browse behavior and original execution-setting restoration
tests. Disposable database
`erms_messaging_test_acl_cef394e0d380498389a2e56686e65014` was dropped.
Evidence: `scope-cleanup/regressions.log`. These were correctness checks, not
a new performance benchmark.

`scope-cleanup/scope-checks.json` verifies that only natural-ordering definitions
differ in the six search/browse modules. Search/browse route functions,
`search_execution.py`, the shared authorization generator and original
execution-setting tests match the branch baseline. Updated benchmark helpers
compile, references to removed helpers are absent, and `git diff --check` passes.

## Concurrent creation and safe retries

The complete-request load case uses eight creations sharing a counter,
occupied manual numbers, three completed retries, and eight independently
configured series alongside a rename, counter adjustment, manual creation and
search. It records request times and aggregate cursor-execution counts without
logging SQL parameters or credentials.

The first run exposed a real deadlock. Creation took a shared parent-row lock
and later requested the exclusive lock already required by the existing
authorization and medium guards. Two concurrent requests could wait on each
other while upgrading that lock, before counter allocation. Creation and
draft-parent paths now acquire the existing final parent lock mode first.
Permissions and business rules are unchanged. Retained diagnostics identify
SQLSTATE `40P01` on `aggregations`, rather than attributing it to the counters.

The corrected load case passed in **6.11 seconds**. Eight concentrated requests
completed in 0.566277 seconds; the slowest request took 0.5619 seconds. Twelve
mixed requests completed in 0.613155 seconds; the slowest took 0.6090 seconds.
Completed retries preserved their original resource and did not advance a
counter. The occupied 90/100 example allocated 110 in 0.0683 seconds. These are
small local API measurements, including the native shared-parent serialization,
not a production throughput guarantee. Transaction-level independent-counter
and ordered multi-counter tests are recorded in phase 1.

Evidence is under `.runtime/custom-code-generators/phase6/`:
`compact-permissions-regression.log` (85 passing checks and the original load
failure), `concentrated-diagnostic.log` (deadlock reproduction), and
`concentrated-parent-lock-fixed.log` (passing reproducer). Request measurements
are retained under `.runtime/custom-code-generators/request-metrics/`.
All corresponding disposable databases were dropped.

## Broader creation and authorization regressions

The first broader run reported 28 failures, 66 passes and 47 setup errors.
The first affected setup returned 401 after a preceding test left its Bearer
header on the session-scoped test client. A fresh login cookie was being
overridden by that old test identity. Test isolation now clears Authorization
as well as cookies and the CSRF header before and after each database fixture.
This corrects the test harness; it does not weaken application authentication.
The failed log is preserved as `creation-and-parent-lock-regression.log`.

The identical broader suite then passed **141 tests in 469.76 seconds**:
allocation/store, direct creation, erasure, single/separate/combined file drops,
legacy numbering, parent/medium guards and type access. Evidence:
`creation-parent-lock-and-auth-isolation.log`. Disposable database
`erms_messaging_test_acl_8ede6b48985746f4ad20012ae077c513` was dropped.

## Historical search investigation: experiments removed

Full standard run 6 passed every correctness check and all 630 generator-search
samples (maximum 1.276915 seconds); all 135 reader navigation samples passed
(maximum 1.329754 seconds), as did 15 denied-navigation samples. Two existing
Global Search UI requests still failed the strict limit: 3.1529 and 3.8532
seconds. They remain failures. Its database was dropped.

An isolated before-fix profile measured complete Global Search UI requests and
then captured the actual combined ranking plan. All twelve isolated responses
passed, but the 25-row plan still took 2,323.467 ms. The materialized authorized
record set held 153,009 rows at width 29, including columns unused by search.
Ranking dominated the request; page-detail retrieval took only about 56–74 ms.

An experiment requested a compact result from the canonical batch authorization
CTEs: resource identity and the flags the caller actually needs. All access
predicates, shared role/clearance/ACL sets and default dashboard projections are
preserved. Equivalence tests compared compact and normal projections with the
canonical resource-access functions across identities and access rules. This
changed neither candidate membership nor matching, scores, evidence, caps or
ordering. No planner, memory, index or vector-storage change was made.

The profile and complete plans are in
`.runtime/search-performance/code-generators-phase6-global-ui-profile-before/`;
the disposable database was dropped. Final standard and larger-text results
must be recorded below before release acceptance.

Full run 7 completed the legacy correctness matrix but retained **20 latency
failures**, maximum **5.7577 seconds**. It was deliberately interrupted during
the later generator-only matrix to inspect those failures; it is not a complete
gate or a pass. Its buffered plans/results were flushed and database
`erms_search_perf_1efc306661474a24abfc2dd6102363ce` was dropped. The actual
plans preserved the same large-set scoring path and loop counts, with narrower
authorized rows (29 to 11 bytes estimated for combined search). Most measured
nodes took substantially longer, including candidate scans unaffected by the
projection change. The host observations include active backup and endpoint
security processes. This is context, not proof of causation or a latency waiver.
A controlled alternating comparison followed; final gates remain necessary.

### Controlled projection comparison: rejected experiment

The same disposable corpus alternated compact/control requests in balanced
order over three repeats, for combined search and file-content-only search,
including the first 25 rows and the next cached page. All **24 complete API
responses** passed three seconds and matched independent expected IDs, scores
and page boundaries. Maximum response time was **2.512617 seconds**.

| First-page case | Control median | Compact median |
| --- | ---: | ---: |
| Combined metadata/content | 2.057799 s | 2.093892 s |
| Content only | 1.566607 s | 1.573599 s |

The compact representation showed no consistent benefit. It was removed from
search, the shared authorization generator and its experimental test branch.
The existing canonical authorization code is unchanged. Actual diagnostic
plans after timed requests are retained too, including slower content plans;
they are not substituted for complete API measurements or treated as proof
that host activity caused a failure. Artifacts:
`.runtime/search-performance/code-generators-phase6-projection-comparison/`.
Database `erms_search_perf_2d7532de00bb49b4ab2d80569e21cbf9` was dropped.

### Linux uncached paging: removed JIT experiment

The first local Linux attempt could list `postgres:18.4` but Docker could not
inspect the tag. Inspecting its exact existing image ID succeeded; no image
was downloaded. The complete run then reached uncached child paging with LLVM
available. That path called `search_rows` without the existing interactive
search guard. The run was interrupted for diagnosis, flushed its partial
evidence, dropped its database and removed its container. It is not a completed
gate or a pass.

The isolated Linux profile alternated the same real child-page API request with
and without the existing scoped guard. Every response returned the same ten
IDs and exact total of 1,100. The incoming and final connection setting remained
`jit=on` in both cases.

| Repeat | Original complete request | With scoped guard |
| --- | ---: | ---: |
| 1 | 3.320632 s | 0.104175 s |
| 2 | 2.891416 s | 0.104170 s |
| 3 | 2.862586 s | 0.105809 s |

Actual count and page plans compiled 455 and 495 functions respectively.
Their JIT compilation consumed about 1.3–1.6 seconds **each**. Guarded plans
contained no JIT section. This is measured compilation cost, not an inference
from the Mac's faster timings. The Mac build has no LLVM and could not expose
it.

The experiment temporarily gave `search_rows` the existing `@interactive_search` wrapper, covering
uncached searches as well as its already-guarded cached/browse branches.
The wrapper restores the caller's setting, including validation failures and
nested calls; SQL aborts retain the existing rollback behavior. No server-wide
setting, permission, matching/ranking rule, memory allowance or storage policy
changes. The new regression observes JIT off during actual uncached statements
and preserves both incoming on/off settings after success or invalid sorting.

That additional wrapper and its experimental regression were removed in the
scope correction above. These results describe the experiment only.

Profile artifacts and statements:
`.runtime/search-performance/code-generators-phase6-linux-plain-search-profile/`.
Its disposable database and container were both removed.

`final-uncached-jit-regression.log`: **38 passed in 104.70 seconds**, covering
the new uncached statements/restoration cases, existing execution-setting
guards, natural ordering and canonical access equivalence. Database
`erms_messaging_test_acl_789f661406e34af3af36268ac30ce8ee` was dropped.
`final-seed-tool.log`: the complete API-only fake workflow passed, including
300 distinct creation keys persisted to its run manifest before sending and
no repeated creation on completed resume. That test contacted no database.

### Full Linux run 3: removed root-selector experiment

The complete post-JIT-fix run passed all correctness checks but **failed 32
response timings**. Nine were broad Global/record searches (maximum 4.6712 s);
23 were root selectors (22 filtered pages and one broad page, maximum
5.455772 s). All **630 generator-search responses** passed, maximum
**1.970837 s**. All 15 denied-navigation responses passed. The uncached child
traversal returned every expected ID across **333 responses**, maximum
**0.3962 s**, confirming the JIT correction over complete paging.

Actual root-selector plans still performed too much collection-wide work:
the count statement took 1,409 ms and the page statement 2,284 ms, while the
already-bounded detail statement took only 13.952 ms. Child/record count joins
caused authorization of the full record collection before selecting a page;
classification, owner and text criteria also arrived after the broad
materialized authorization set.

The subsequent experiment applied those submitted root criteria to candidate IDs
before canonical authorization, with no limit/cursor before access checks.
It selected the same ordered page, then calculated visible child and record
counts through one canonical batch over only those selected parents' contents.
Summary behavior, access decisions, query matching, total-count and cursor
semantics remain unchanged. The new regression covers natural one-row pages,
exact visible counts, hidden children/records, denied root access and owner/text
filters. Performance coverage now includes record-creation destinations with
Use restrictions, digital-only and owning-unit filters, plus actual count-detail
statements. This experiment and its helper-specific tests were removed in the
scope correction above; the original browse projections and counts are restored.

`bounded-root-counts-regression.log`: **63 passed in 309.67 seconds**, covering
root/child lists, exact visible content counts, selected-page hydration, hidden
and denied resources, type Use permissions, natural cursors and JIT restoration.
Database `erms_messaging_test_acl_ffafcef1348a44ce9836e994c171f989` was dropped.

Run 3 artifacts are under
`.runtime/search-performance/code-generators-phase6-linux-standard-final-run3/`.
Database `erms_search_perf_08d2535e40184f58a07408256f29b731` and its container
were removed. Its 32 failures remain failures; no threshold was changed.

## Canonical schema and translation checks

`final-api-database-catalogue.log`: **150 passed, one intentionally skipped**
in 407.95 seconds. The skip requires the separate populated-upgrade runner;
that case passed there. Database
`erms_messaging_test_acl_e4452c20048c4775aba7bb7d8f846307` was dropped.
`final-index-and-parity-regression.log`: **12 passed in 44.18 seconds**;
database `erms_messaging_test_acl_898d1a9e708e41bb809b5c615255ce8b` was dropped.

The final renderer/schema/configuration suite passed **143 tests in 23.49
seconds**. The WebUI suite passed **146 tests in 14.75 seconds**. Catalogue
references, exact sorted active-key coverage, all 35 approved Arabic terminology
mappings (1,006 contextual uses), placeholders, nonblank translations, generated
draft flags, original provenance and artifact hashes passed. The 141 new Arabic
drafts require review. Of 4,196 original entries, 4,195 remain identical; the
single explicitly approved correction retains its complete previous wording
and provenance. Guarded seed-replacement rules remain unchanged.

Policy inventory regeneration, configuration ownership (131 settings) and all
37 API environment-template entries passed. No environment setting was added.
Evidence is in `final-*` logs and `translation-preservation.json` under the
phase 6 runtime directory.

The populated upgrade passed again in **9.07 seconds**, including a forced
rollback, preservation of an existing record and numberless draft, and an
observed draft-table DDL wait. Database
`erms_messaging_test_acl_cca754f4f8d44865a57067d31dfb2c01` was dropped.

The full archive-based comparison caught the new draft column being placed
earlier in fresh installations than migration 126's appended column. Canonical
column order now matches the upgrade, with a static regression. It also
identified two equivalent representations of the existing uncommon-config
index predicate: casting individual regconfig constants to oid versus casting
their array. The index is unchanged. The verifier now asks PostgreSQL to fold
immutable constants using EXPLAIN VERBOSE without executing the scan, retaining
the complete resulting predicate. A regression requires equal output for the
two forms and unequal output for changed configurations or operators. Functions,
grants, visible column order, constraints, data and sequence states remain
strict comparisons. Initial and corrected evidence and every cleanup are
retained in the canonical-parity logs.

The final comparison passed for **144 tables, six views, 378 functions and 354
triggers**, including all 908 archived rows and 70 sequence states. Both
disposable databases were dropped. Exact table fingerprints, locale, normalized
schema hash and cleanup are in `canonical-parity-final.json`. The final static
canonical/verifier checks passed 54 tests. All 87 then-changed Python files
compiled; the Linux runner was subsequently extended to forward the existing
typed-field/generator gate options, with no new application configuration.

The authorized local demo catalogue received **141 missing Arabic drafts**
through the explicit seed utility with `--missing-only`: zero corrections,
failures or awaiting-generation rows. All 4,302 existing non-source-copy rows
remained byte-for-byte identical, including unpublished and retired history.
New drafts remain unpublished. Evidence: `demo-arabic-missing-only.json`.
The first invocation lacked the repository import path and failed before
connecting; retrying with `PYTHONPATH=.` completed the authorized upkeep. No
persistent schema upgrade or generator configuration was performed.

## Operator handoff

[Operating Custom Code Generators](../custom-code-generators-operations.md)
documents migration prerequisites and locking, first configuration, existing
series, optimistic conflicts and document correction, creation-request keys,
disablement/recovery, natural sorting and ICU maintenance. The API and clients
must be upgraded together. Existing resources are not backfilled, and no
generator is enabled by the upgrade.

Arabic additions remain generated drafts for human review and publication.
Local macOS PostgreSQL lacks LLVM JIT; the original scoped setting/restoration
tests remain covered. The final local Linux measurements above had LLVM/JIT
available. Full remote CI and production deployment were not performed.
