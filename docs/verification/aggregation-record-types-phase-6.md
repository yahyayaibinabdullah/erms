# Aggregation and record types · Phase 6

**Passed locally on 21 November 2026.** The approved implementation plan is complete. Across the five large-dataset runs, all 2,957 measured requests finished within three seconds. The slowest took 2.611 seconds. Two additional timed text-edit commits also passed. All disposable test databases were dropped. The persistent `demo` database was untouched.

## Fresh installation and populated upgrade

The populated rehearsal starts at the published PDF migration, using revision `50b2aaa0`, with 51,003 aggregations, 153,009 records and two existing saved searches. A second database starts from the current canonical schema, required reference data and fresh-install baseline. The runner applies migrations 119, 120 and 121 in order to the older database. It compares normalized schema dumps, complete receipt names, existing resource and saved-search row hashes, legacy audit history and published translation provenance. It checks resource heap files, indexes, default privilege grants and all 204,012 search vectors. [Rehearsal](../../tools/check_resource_type_upgrade.py)

Migration 119 leaves existing resources untyped. The rehearsal then deliberately populates 5,001 records and 5,001 aggregations with stored text before applying 121. This tests the upgrade of sites that already have type data. The backfill updates their searchable metadata in place and preserves each document’s configuration. It leaves component content and untyped documents intact. A separate test rejects the final receipt after the backfill, verifies rollback of both the search vectors and new function, removes the injected failure and successfully reapplies the actual file. [Recovery test](../../backend/services/api/tests/test_type_text_upgrade.py)

At the time of the rehearsal, the fresh-install baseline checked type storage, authorization and search objects before recording their version names. The subsequent [atomic installation change](../database-canonical-baseline.md#fresh-installation) restricts the receipt writer to the transaction that created and seeded the database. The former guard could accept a schema at the PDF migration if its receipt table was empty. The rehearsal checks that attempted baseline against the older schema and verifies the legitimate fresh-install path. [Baseline guard](../../database/baseline.sql)

In the final rehearsal, migrations 119, 120 and 121 committed in 0.938 s, 0.013 s and 0.956 s respectively, with no competing application writers. The first migration acquired `ACCESS EXCLUSIVE` locks on both resource tables. Their heap files and sizes stayed unchanged. Their indexes grew by 6.19 MiB combined. That figure covers only those two tables’ indexes and excludes WAL, temporary files and the text backfill. All 54 inspected indexes were ready and valid. All 175,239 original audit rows retained their content. The fresh and upgraded schema dumps had the same SHA-256 digest. [Migration receipts, storage, lock samples and hashes](p6-upgrade-01.json.gz)

## Cross-phase regression coverage

The integrated collection includes the type APIs, direct and set-based authorization, custody continuity, lifecycle and destruction, component access, history redaction, field validation and translation, saved-search disclosure, cached-page reauthorization and generated policy inventory. The two-kind API journey creates definitions, assigns all seven field types, queries by stable field and choice IDs, shares a saved search with an ordinary recipient and revokes See. In the same signed-in session the recipient loses access to the resource, saved definition, ad hoc query and cached execution. The shared summary remains available and governance retains resource access. Restoring the grant restores the expected row. [API journey](../../backend/services/api/tests/test_type_search.py) · [Detailed traceability](../aggregation-and-record-types-implementation-traceability.md)

The integrated suite passed 489 cases in 22 min 35 s, with two dependency deprecation warnings. The two additional end-to-end sharing cases and the rollback/retry case also passed. Each database-backed suite confirmed its database drop. The first runner invocation used an interpreter without PostgreSQL support and exited before creating a database. The successful run used the API environment. [Case-level results, source hashes, browser attempts and cleanup](types-p6-regressions.json.gz)

The DB-free UI suites passed 1,650 unit tests and 670 interaction tests. Chrome passed all 12 assembled checks in English and Arabic, including multilingual editing, typed creation, details, mixed queries and sorting. Initial Chrome attempts captured a disabled selection button and stale table elements during rendering. The checks now wait for selection to be enabled, the destination table to appear, and the current row button before clicking. The browser stack and its disposable database were cleaned up after each attempt.

## Large-dataset response times

The standard corpus contains 51,003 aggregations and 153,009 records. The larger-text fixture includes 180,630 component chunks. The table compares the slowest complete API response in each run. Each individual response must finish within three seconds. Phase 0 figures use the accepted ranking-scoped I/O setting. Type-specific workloads were added in later phases. [Phase 0 comparison](aggregation-record-types-phase-0.md) · [Phase 4 comparison](aggregation-record-types-phase-4.md) · [Phase 5 comparison](aggregation-record-types-phase-5.md)

| Workload | Phase 0 maximum | Previous maximum | Phase 6 samples | Phase 6 maximum |
| --- | ---: | ---: | ---: | ---: |
| Standard search and lists | 2.424 s | 2.657 s (Phase 5) | 1,524 | 2.611 s |
| Standard corpus, type-specific text | — | 0.563 s (Phase 4) | 188 | 0.597 s |
| Larger-text search | 2.404 s | 2.383 s (Phase 4) | 428 | 2.546 s |
| Larger corpus, type-specific text | — | 0.599 s (Phase 4) | 215 | 0.654 s |
| Structured type criteria, sorting, saved execution and paging | — | 1.471 s (Phase 5) | 237 | 1.382 s |
| Bounded selectors and administration pages | — | 0.022 s (Phase 5) | 144 | 0.022 s |
| Restricted visibility, governance and permission changes | — | 0.883 s (Phase 2) | 116 | 0.887 s |

All 296 comparable standard result files and all 19 larger-text files matched the accepted Phase 0 output byte for byte. Standard and larger-text edits committed in 0.014 s and 0.026 s respectively. The standard maximum fell by 0.047 s from Phase 5. The larger-text maximum rose by 0.163 s from Phase 4 and retained 0.454 s of headroom. Differences describe these runs on this host. [Standard results and plans](p6-standard-01.json.gz) · [Larger-text results and plans](p6-rich-01.json.gz) · [Wait events and host I/O](p6-rich-01-waits-and-io.jsonl.gz)

The restricted-visibility workload includes four measured policy and reassignment writes. Its maximum changed by 0.004 s from Phase 2. The structured-search maximum fell by 0.089 s from Phase 5. [Structured search and administration samples](p6-structured-01.json.gz) · [Visibility samples and plans](p6-visibility-01.json.gz) · [Phase 2 comparison](aggregation-record-types-phase-2.md)

### Broad searches after upgrading a populated database

These are the reader’s three first-page response times in seconds. Each submission used a new search tab, a 100-row page and a 1,000-result cap. The two fixtures contain the same legacy searchable content and different synthetic type values.

| Query and sources | Authorized matches before cap | Fresh schema | Upgraded schema |
| --- | ---: | --- | --- |
| `common OR universal`, metadata and components | 204,012 | 2.611 / 2.034 / 2.072 | 2.462 / 2.027 / 1.933 |
| `common`, metadata | 204,012 | 0.751 / 0.738 / 0.733 | 0.754 / 0.711 / 0.701 |
| `universal`, component content | 153,009 | 1.504 / 1.610 / 1.531 | 1.536 / 1.555 / 1.523 |

All 99 upgraded-schema submissions and page requests passed. The denied caller received zero results in each case. The 24 comparable expected and received ranking files matched the Phase 0 baseline. Both legacy saved searches also opened with their original conditions and sort. All six executions returned IDs 1–25 in order, with a capped total of 1,000 and the truncation indicator set. The maximum was 0.488 s for aggregations and 0.841 s for records. [Upgraded query samples, rankings, saved results and plans](p6-upgrade-01.json.gz)

## Requirement reconciliation

| Requirements | Implementation | Verification |
| --- | --- | --- |
| ART-01, ART-02, ART-05, ART-06, ART-07, ART-08, ART-11 · compatible catalogues, seven native types, constraints, defaults and safe edits | [Definition schema](../../database/migrations/119_resource_types.sql), [definition API](../../backend/services/api/resource_types.py), [value writes](../../backend/services/api/typed_metadata.py) | [Foundation tests](../../backend/services/api/tests/test_resource_type_foundation.py), [form boundary and paging tests](../../frontend/webui/interaction/tests/test_type_metadata_controls.py) |
| ART-03, ART-04, ART-12, ART-20 · translated definitions, literal resource text and existing UI conventions | [Administration](../../frontend/webui/type_administration.py), [shared translation editor](../../frontend/webui/entity_translation_editor.py), [resource controls](../../frontend/webui/type_controls.py) | [Assembled browser](../../tools/webui_browser_resource_types.py), [bounded and localized API reads](../../backend/services/api/tests/test_resource_type_ui.py) |
| ART-09, ART-10, ART-14, ART-15, ART-16, ART-17, ART-18 · delegation, operation gates, governance, custody, history and freshness | [Authorization and audit SQL](../../database/migrations/120_resource_type_access.sql), [policy evaluator](../../backend/services/api/authorization_policy.py), [resource writes](../../backend/services/api/typed_metadata.py) | [Access, concurrent change, audit and custody tests](../../backend/services/api/tests/test_resource_type_access.py), [policy inventory](../../backend/services/api/tests/test_policy_inventory.py), [visible and restricted populations](../../tools/resource_type_visibility_performance.py) |
| ART-13, ART-19, ART-22 · mixed queries, sort order, saved disclosure and text indexing | [Typed query compiler](../../backend/services/api/type_search.py), [saved execution](../../backend/services/api/saved_searches.py), [metadata index maintenance](../../database/migrations/121_type_text_search.sql) | [Search and sharing tests](../../backend/services/api/tests/test_type_search.py), [text searches and freshness](../../backend/services/api/tests/test_type_text_search.py), [upgrade rollback and retry](../../backend/services/api/tests/test_type_text_upgrade.py) |
| ART-21, ART-23 · measured performance and set-based authorization | [Shared visibility SQL](../../backend/services/api/dashboard_visibility.py), [search execution scope](../../backend/services/api/search_execution.py) | The final fresh and upgraded measurements preserve independently checked IDs, scores, paging, plans and per-request timings. |

## Reproduction

Use a distinct output directory for each run. The database-backed runners create, initialize and drop their own databases. Run the timed benchmarks consecutively on a quiet host. The standard, structured and visibility runners use a 30-second post-maintenance settle. The larger-text runner uses the accepted 60-second protocol. The upgraded broad-query check uses the same standard reader, denied caller, queries, cap, paging and independent rank oracle as the fresh-schema standard benchmark.

```sh
backend/services/api/.venv/bin/python tools/check_search_performance.py --type-text --repeats 3 --settle-seconds 30 --output .runtime/search-performance/p6-standard-01
backend/services/api/.venv/bin/python tools/check_large_text_search_performance.py --type-text --sample-waits-and-io --repeats 3 --settle-seconds 60 --output .runtime/search-performance/p6-rich-01
backend/services/api/.venv/bin/python tools/check_search_performance.py --type-ui --repeats 3 --settle-seconds 30 --output .runtime/search-performance/p6-structured-01
backend/services/api/.venv/bin/python tools/check_search_performance.py --type-visibility-only --repeats 3 --settle-seconds 30 --output .runtime/search-performance/p6-visibility-01
backend/services/api/.venv/bin/python tools/check_resource_type_upgrade.py --broad-search --settle-seconds 30 --output .runtime/search-performance/p6-upgrade-01
```

## Handoff

Use the existing-database procedure for a site at migration 118 and the canonical initializer for an empty installation. The operator guidance covers migration order, locking, disk and WAL capacity, post-upgrade checks and recovery after an interrupted commit. The 55 new Arabic drafts await administrator review and publication. The configuration authority and service templates remain consistent. All verification is local. Production-host latency, a PostgreSQL build with LLVM JIT, and remote CI require separate verification. [Database operator guidance](../../database/README.md#resource-type-upgrade-and-recovery)
