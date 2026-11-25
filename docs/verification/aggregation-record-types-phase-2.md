# Aggregation and record types, Phase 2

**Identifier note.** The recorded evidence predates migration renumbering. The
access migration is now 120; see the
[identifier mapping](../../database/README.md#type-migration-identifiers-after-pdf-integration).

Phase 2 passed on 19 November 2026. It covers type administration, typed resource writes, access enforcement and audit history. The approved historical disclosure rule applies to records and aggregations. [History specification](../../specs/aggregation-and-record-types.md#historical-values-after-reassignment--approved-19-november-2026) · [Auditor example](../event-history.md#when-a-record-or-aggregation-changes-type)

| Final check | Result |
| --- | --- |
| Broad regression suite | 314 passed |
| Focused API and lifecycle suite | 81 passed |
| Regressions on the upgraded schema | 31 passed |
| Canonical SQL and schema verifier tests | 53 passed |
| Standard search benchmark | 1,524 responses, maximum 2.547 s |
| Larger-text benchmark | 428 responses, maximum 2.873 s |
| Restricted visibility and governance workload | 116 requests, maximum 0.883 s |
| Populated upgrade | All resource and saved-search hashes preserved. Fresh and upgraded schemas matched. |

The regression suites overlap. Every database-backed run above used a disposable database and confirmed its removal. The final broad rerun passed the privilege and search-cache cases that had failed earlier. [Regression results, module selection and cleanup](types-p2-regressions.json.gz)

## Resource history after reassignment

The write transaction preserves the former and new type IDs, type names, resource security levels and type-specific field values. Both the ordinary row-change event and the type-metadata event pass through the authorized audit projection. The stored names let an auditor identify the transition after a catalogue rename. The viewer’s effective permissions at read time determine which values appear. Revocation takes effect on the next request, including direct event reads.

The API regression exercises both resource kinds. A viewer with history access and See on Correspondence can identify the previous Investigation type. The former values are withheld. Granting See on Investigation reveals those values and revoking See withholds them again. An auditor needs the usual resource access and history rights to read the event. [Phase 2 regressions](../../backend/services/api/tests/test_resource_type_access.py) · [Database upgrade](../../database/migrations/120_resource_type_access.sql)

## Verification evidence

The first passing combined run covered 18 type-access and field-foundation tests on the canonical schema. The runner confirmed database cleanup. All 44 canonical SQL checks passed. Subsequent runs cover additional assertions and the populated upgrade. [Initial combined regression log](../../.runtime/search-performance/types-p2-typed-04.log) · [Canonical SQL checks](../../.runtime/search-performance/types-p2-canonical.log)

The first restricted-visibility run finished its request and authorization checks. Its client teardown raised a pool-closed error after a second application lifespan closed the shared connection pool. The runner dropped its database. The second client now owns only its HTTP transport. The first larger-text run passed its ranking and response-time checks, then failed its source-hash check because two files changed during measurement. These runs are retained as diagnostics. [Visibility run](../../.runtime/search-performance/types-p2-visibility-01/) · [Larger-text run](../../.runtime/search-performance/types-p2-rich-01/)

The expanded canonical-schema type-access and ACL suite passed **24 tests**. It exercised an actual single-choice selection, renaming the former type, both historical snapshots, an auditor’s direct event lookup and audit search, grant and revocation, governance, and denial after history access was withdrawn. It also checked independent Use grants for source and destination, an expired role and component-list versus upload access. The disposable database was dropped. The final static canonical-schema and verifier suite passed **53 tests**. [Authorization regressions](../../.runtime/search-performance/types-p2-typed-05.log) · [SQL checks](../../.runtime/search-performance/types-p2-canonical-02.log)

## Standard large-data comparison

The standard fixture contains 51,003 aggregations, 153,009 records and 306,018 searchable chunks. Two thirds of each resource kind were assigned types. The equivalent-access reader had See on both types. The denied identity retained its original ACL restrictions. All 74 expectation files and 222 returned ranking files matched the Phase 0 application-override run byte for byte.

The first standard run was stopped after a contained-page request authorized the whole resource table. The fallback now uses a directly conjoined parent or ID equality to bound the candidate set for that request. The second run finished all **1,524 responses**. One exceeded three seconds. The failing request was the first 10-item broad Global Search page, at **3.3129 s**, against **2.4237 s** in the corresponding Phase 0 sample and **2.5314 s** in Phase 1. Its Phase 2 repetitions took **2.3051 s** and **2.2046 s**. A separately captured broad record-branch plan took 2.343 s against 1.739 s in Phase 0. The recorded ranking plan and the endpoint timing are different observations. The runner dropped both disposable databases. [Second run, ranked IDs, plans and individual measurements](types-p2-standard-02.json.gz)

The final standard run passed all **1,524 responses**, with a maximum of **2.5466 s** on the descending filtered record list. The 10-item broad Global Search request from the earlier failure took **2.0896, 2.0547 and 2.2046 s**. All 296 ranking and expectation files matched Phase 0 again, and the disposable database was dropped. The earlier 3.3129 s observation remains in the second-run report. [Final standard timings and actual plans](types-p2-standard-03.json.gz)

The first broad regression run recorded 297 passes and 15 failures. One test still expected 64 base privileges after the two approved additions. Fourteen tests compared cached and uncached item shapes while the two query modules were at different revisions. Both paths now return the type ID alongside the selected page. The focused reruns passed all 16 privilege and inventory checks and all 56 typed-access, cached-search, component-filter and session concurrency checks. The reports retain the original failures. [Initial broad run](../../.runtime/search-performance/types-p2-regressions-01.log) · [Privilege and inventory rerun](../../.runtime/search-performance/types-p2-privilege-02.log) · [Search and authorization rerun](../../.runtime/search-performance/types-p2-read-02.log)

## Populated upgrade

A fresh installation and an upgrade through migrations 118 and 119 produced identical schema dumps. Every pre-existing resource and both saved searches retained their column hashes. The existing privilege grants were preserved. Each information-governance profile and ALL_PRIVS gained exactly the two type-administration privileges. Migration 119 took 0.018 s on this fixture. Both disposable databases were dropped. [Upgrade evidence](types-p2-upgrade-01.json.gz)

## Restricted visibility and governance

The extended workload compares a partly restricted reader and an information-governance user against independent sets of known fixture IDs. The first extended run reached a 4.960 s aggregation-browse response and a destination-selector count that was cancelled at 73.394 s. The planner estimated 26.4 million rows in the recursive open-aggregation set on a database with 51,003 aggregations. Its plan also nested the grant-to-source match over a severely underestimated ACL set. The selector now exposes unique open IDs to the planner and matches the add-record grant using the resolved source and owning unit. The hierarchy browser bounds authorization to the requested branch, the ancestors needed for labels and the immediate descendants needed for counts. [Preserved estimated plan](../../.runtime/search-performance/types-p2-destinations-estimated.json) · [Partial request samples](../../.runtime/search-performance/types-p2-visibility-02/type-visibility.json)

The corrected run passed all **116 requests**, including the four policy-change and reassignment writes. The slowest read took **0.883 s**. The restricted reader’s record destination selector stayed at or below **0.649 s**, and the aggregation hierarchy browse stayed at or below **0.301 s**. The slowest measured policy change took **0.044 s** and the slowest reassignment **0.043 s**. The runner checked both identities against fixture IDs, re-read a cached page after revocation, captured actual plans for seven API flows after timing, and dropped the database. [Individual samples and actual plans](types-p2-visibility-03.json.gz)

The migrated-schema regression suite passed **31 tests** covering typed operations, audit disclosure, foundation constraints and ACL behavior. [Migrated suite and cleanup](../../.runtime/search-performance/types-p2-migrated-01.log)

In the 15 captured SQL statements, the plans show zero or one execution of each effective-role and accessible-type set per statement. One unused branch did not execute either set. The counts, page queries and enrichment statements retain their separate authorization checks; the number of candidate resources does not determine the number of type lookups.

The final API run passed **81 tests** on the fresh canonical schema, including lifecycle, destruction, retained metadata, permanent deletion, ownership correction and ACL checks. It verified both resource kinds through two successive reassignments: once the resource is under C, a viewer with See on A and C can read A’s values in the older A → B event. If See on A is then revoked, the viewer still sees both historical names and both sides are marked as withheld. The runner dropped the database. [API suite and cleanup](../../.runtime/search-performance/types-p2-final-api.log)

## Larger-text comparison

All **428 complete API responses** met the three-second threshold on the unchanged application sources. The maximum was **2.8728 s**, compared with **2.4035 s** in Phase 0. Both maxima occurred on the first broad combined search. On this fixture of 180,630 chunks, all 19 comparison files, including the returned rankings and uncapped membership, matched Phase 0 exactly. The actual broad combined plan built the effective-role set, accessible-type set and scored-chunk set once each. The database was dropped. PostgreSQL 18.4 on this host had no LLVM JIT available. The bundle contains the timings, plans, source hashes and wait-event/host I/O samples. [Larger-text evidence](types-p2-rich-02.json.gz)

## Reproducing the measurements

Run these commands with the API virtual environment active. Each runner creates and drops its own disposable database. Run the measurements sequentially so the jobs do not compete for the same PostgreSQL host.

```sh
python tools/run_disposable_acl_tests.py backend/services/api/tests/test_resource_type_access.py backend/services/api/tests/test_resource_type_foundation.py
python tools/check_search_performance.py --resource-types --type-visibility-only --settle-seconds 30 --repeats 3 --output .runtime/search-performance/local-type-visibility
python tools/check_search_performance.py --resource-types --settle-seconds 30 --repeats 3 --output .runtime/search-performance/local-type-standard
python tools/check_large_text_search_performance.py --resource-types --settle-seconds 60 --repeats 3 --sample-waits-and-io --output .runtime/search-performance/local-type-large-text
python tools/check_resource_type_upgrade.py --output .runtime/search-performance/local-type-upgrade
```
