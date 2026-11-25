# Aggregation and record types, Phase 1

**Identifier note.** Measurements below retain their original migration numbers
and hashes. The type foundation is now migration 119 after PDF integration;
see the [identifier mapping](../../database/README.md#type-migration-identifiers-after-pdf-integration).

**Status.** Phase 1 complete on 19 November 2026. Both installation paths passed the foundation tests and the standard large-data gate passed on the new schema.

## Storage and validation

Migration 118 introduces the aggregation and record type catalogues. Each resource has one nullable foreign key to its own catalogue. The two catalogues share field, translation, choice, grant and validation rules. Fields and choices have stable IDs and administrator-defined order, with ID as the tie-breaker. Resource text and its literal default each have one language-independent value. A role-grant row gives See access. Its Use flag grants that role Use as well. Access decisions and public write routes belong to Phase 2. [Canonical schema](../../database/schema.sql) · [Current foundation migration (119)](../../database/migrations/119_resource_types.sql)

The seven field types use PostgreSQL native scalar storage. Exact decimals pass directly to `numeric`. Datetimes require an explicit UTC offset or Z on input and are stored as `timestamptz`. A single choice stores its field's choice ID. The translation columns use the existing supported-language validator and the existing entity projection for locale fallback. These columns belong to definitions. [Translation projection](../../backend/services/api/entity_localization.py)

The side-effect-free SQL function `resolve_resource_type_values(kind, resource_id, destination_type_id, submitted)` validates the proposed metadata and returns one typed row per populated field. Callers pass the destination type, a JSON object keyed by field ID, and a null resource ID for creation. For an existing resource, the function reads its current type to distinguish assignment from an ordinary update. On assignment, omitted fields receive their current defaults. On an ordinary update, omitted fields retain their saved values. An explicit null clears an optional value. Every metadata save checks all required fields, including new ones. Calling the resolver before changing the resource's type preserves that distinction. Phase 2's authorized write transaction must lock the resource and applicable definitions, validate against the old assignment, confirm destructive changes, and persist the assignment, values and history atomically.

Foreign keys enforce resource kind, assignment, field ownership, scalar type and choice membership. A default's choice must belong to its field. A populated field cannot change data type or be deleted. The stored text capacity follows the field's maximum through a cascading foreign key. Changing the limit updates the capacity on that field's populated rows in the same transaction. A reduction below a stored value rolls back. Changes to requiredness and defaults preserve historical values. Renames, translations and changes to order preserve field and choice IDs. [Foundation regressions](../../backend/services/api/tests/test_resource_type_foundation.py)

## Populated upgrade

On native PostgreSQL 18.4, the reference installation used the version of the schema and seeds from commit `2a5bbb805ba445c3da24e6b399a873e1d2ad3230`. The runner loaded the standard search corpus plus two existing saved queries, then applied the complete migration as shipped. In a second database it installed the latest canonical schema and seeds. Both full schema dumps had SHA-256 `d61f42106c0de9140e51641698d780e2f074585075816228fc9d3831382d40d7` after removal of pg_dump client boilerplate.

| Populated resource | Rows | New assigned types | Heap change | Resource index growth |
| --- | ---: | ---: | ---: | ---: |
| Aggregations | 51,003 | 0 | 0 bytes | 1,630,208 bytes |
| Records | 153,009 | 0 | 0 bytes | 4,857,856 bytes |

Hashes of every pre-existing column of every resource and both saved searches matched before and after. Both resource heap file identifiers were preserved and there were zero field-value rows. The migration, including index builds and commit, took 0.353 s. From a separate session the observer saw granted `ACCESS EXCLUSIVE` locks on both resource tables. Concurrent resource reads and writes can therefore wait until commit. This measurement was taken without competing client transactions. Allow for existing transactions, storage speed, index space and WAL when scheduling a populated deployment. Both disposable databases were dropped. [Migration measurements and row hashes](aggregation-record-types-phase-1-upgrade.json.gz) · [Reproducible upgrade check](../../tools/check_resource_type_upgrade.py)

A second populated migration timed each statement within the original transaction. The unique indexes on `(id, type_id)` took 0.049 s for aggregations and 0.084 s for records. The partial assignment indexes took 0.055 s and 0.041 s, respectively. The complete migration took 0.352 s. Row hashes and full-schema parity checks passed again, and both databases were dropped. [Index timings and lock samples](aggregation-record-types-phase-1-index-builds.json.gz)

## Verification

The fresh installation passed **237 tests** across the foundation and the 230 Phase 0 regression cases. The seven foundation tests also passed on a database upgraded with migration 118. Coverage includes exact native round trips, Unicode limits, zero and false, defaults on assignment and reassignment, explicit clearing, newly required fields, invalid and cross-kind references, a concurrent length reduction, choice integrity, Arabic and French regional fallback, canonical fallback, and rejected public create/update attempts for both resource kinds. All **44 canonical-schema tests** passed. The database runners confirmed their disposable database drops. [Fresh regression log](../../.runtime/search-performance/types-p1-regressions-01.log) · [Migrated regression log](../../.runtime/search-performance/types-p1-migrated-regressions-01.log) · [Canonical checks](../../.runtime/search-performance/types-p1-canonical.log)

An initial API boundary test received HTTP 428 because it omitted the existing update precondition. Supplying the resource version let the test reach request validation and verify HTTP 422 for the type attributes. [Initial regression output](../../.runtime/search-performance/types-p1-foundation-01.log)

The untyped corpus used 51,003 aggregations, 153,009 records and the original standard fixture. Both phases ran three measured repetitions after a 30-second settling period. All **1,524** Phase 1 responses met three seconds. All 74 expected-result files and 222 received Global Search ranking files matched the Phase 0 application-override run byte for byte. The runner also checked the independent oracles, paging, denied access and existing index paths. It dropped its disposable database. [Phase 1 samples](types-p1-standard-01.json.gz) · [Phase 0 samples](adopt-ranking-standard-01.json.gz) · [Plans, exact rankings, host measurements and cleanup](../../.runtime/search-performance/types-p1-standard-01/)

| Standard workload | Phase 0, seconds | Phase 1, seconds |
| --- | --- | --- |
| Broad combined first page, 204,012 matches | 2.1587 / 1.9114 / 1.9455 | 2.4095 / 2.0447 / 2.0614 |
| Broad metadata first page | 0.7782 / 0.6954 / 0.6762 | 0.7202 / 0.9436 / 0.8205 |
| Broad file-content first page | 1.4629 / 1.4130 / 1.3906 | 1.5995 / 1.5268 / 1.5887 |
| Broad Global Search, 25-item first page | 2.0063 / 1.9397 / 2.0573 | 2.5403 / **2.9999** / 2.3207 |
| Maximum across all workloads | 2.4237 | **2.9999** |

The worst recorded response was within 0.0001 s of the limit. Median one-minute host load across samples was 13.28 during Phase 1 and 3.49 during Phase 0. The broad combined record branch used the same chunk index, through a bitmap scan in Phase 1. The aggregation branch used the new resource ID/type index at one node, and its captured execution took 0.331 s against 0.327 s before. These are whole-response comparisons on a shared host. They establish the measured increase and threshold result, with limited ability to isolate the schema's contribution. PostgreSQL reported JIT unavailable on this build. This phase changed neither full-text scoring, evidence nor vector storage, so the plan calls for the standard gate only. The larger-text reference remains the 428-response Phase 0 run.
