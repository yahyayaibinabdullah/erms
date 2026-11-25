# Aggregation and record types, Phase 4

## Rerun after merging main on 21 November 2026

The rerun used merge revision `a16df902` and the local type implementation. Each database-backed runner created and dropped its own disposable databases. The search benchmarks ran consecutively after the regressions and upgrade rehearsal finished. The standard run used a 30-second settle and three rounds. The larger-text run used a 60-second settle, three rounds and wait-event and host I/O sampling. Both used PostgreSQL 18.4 without LLVM JIT.

| Complete HTTP responses | Count | Slowest on 19 November | Slowest after merge |
| --- | ---: | ---: | ---: |
| Standard, existing searches | 1,524 | 2.5671 s | 2.5297 s |
| Standard, type-text searches | 188 | 0.6074 s | 0.5629 s |
| Larger text, existing searches | 428 | 2.5107 s | 2.3829 s |
| Larger text, type-text searches | 215 | 0.6602 s | 0.5993 s |

All 2,355 responses met the three-second threshold. The 296 standard and 19 larger-text ranking and expectation files matched their pre-feature baselines byte for byte. [Standard measurements and plans](postmerge-p4-standard.json.gz) · [Larger-text measurements and plans](postmerge-p4-rich.json.gz) · [Wait events and host I/O](postmerge-p4-rich-waits-and-io.jsonl.gz)

The five focused search regressions passed. The populated upgrade test passed with `--baseline-ref=a16df902` and `--migration=database/migrations/121_type_text_search.sql`. The large rehearsal initialized the published PDF schema, applied migrations 119–121 and compared it with a fresh installation. Migration 121 and commit took 0.9272 s for 5,001 text-bearing records and 5,001 text-bearing aggregations. All 204,012 vectors matched the expected values, and the schema dumps matched. [Upgrade measurements](postmerge-p4-upgrade.json.gz)

The first 41-module run passed 486 cases and failed one on import. An `await` in the aggregation details action menu prevented the WebUI from loading. Moving the renderer below the primary metadata in the first tab fixed the import. All 40 Advanced Search builder tests then passed. A clean rerun on a new database passed all 487 tests in 19 minutes 33 seconds. [Regression logs and module list](postmerge-p4-regressions.json.gz)

The record draft editor already contained the checkpoint indentation correction and compiled successfully.

## Original verification

**Identifier note.** Measurements, hashes and commands below are historical
evidence from before PDF integration. Type-text migration 120 is now 121;
see the [identifier mapping](../../database/README.md#type-migration-identifiers-after-pdf-integration).
For a current complete upgrade rehearsal, use `tools/check_resource_type_upgrade.py`;
it includes published PDF migration 118 in its starting schema and applies
type migrations 119–121. The historical focused command below retains its old
path and source revision and is not a current invocation.

**Phase 4 passed on 19 November 2026.** The final regression suite passed 487 tests. Migration 120 backfilled 10,002 resources in 0.989 s on the disposable upgrade fixture. The final performance runs extended type-text coverage to direct Advanced Search and saved-search execution for both resource kinds. They followed complete capped lists and checked denied users, exact scores and current permissions.

| Final complete HTTP measurements | Standard dataset | Larger-text dataset |
| --- | ---: | ---: |
| Existing benchmark responses | 1,524 | 428 |
| Slowest existing response | 2.5671 s | 2.5107 s |
| Type-text responses | 188 | 215 |
| Slowest type-text response | 0.6074 s | 0.6602 s |
| Responses above 3 s | 0 | 0 |
| One committed field edit, measured separately | 0.0120 s | 0.0189 s |

All 296 standard and 19 larger-text ranking and expectation files matched their corresponding baseline files. Both final benchmarks confirmed database cleanup. The local build lacks LLVM JIT. [Final standard results](types-p4-standard-02.json.gz) · [Final larger-text results](types-p4-rich-02.json.gz) · [Final wait and I/O samples](types-p4-rich-02-waits-and-io.jsonl.gz)

Phase 4 covers keyword matching, ranking evidence and index freshness for populated type-specific text. The header, Advanced Search and saved queries share the existing metadata document for each aggregation or record.

## What changes when a resource is edited

The metadata vector keeps the number and title at weight A and the description at weight B. It appends populated text literals at weight B in stable field-ID order. Reordering a form or translating its labels preserves the indexed words and positions. Numeric values, dates, booleans, choices, labels and type definitions do not supply keyword text. A resource only contributes its own values. A record hit identifies metadata as the source. Aggregation snippets can show the matched text on authorized result pages. [Database definitions](../../database/migrations/121_type_text_search.sql) · [Result-page evidence](../../backend/services/api/search_page.py)

A field write collects the affected owner IDs once per statement, locks the owners in order, and rebuilds each changed document from current values in the same transaction. This also covers writes directly to a value partition. Owner deletion uses the existing document cascade. Searches continue to rank the stored vectors. Reading a page rechecks both its criteria and current visibility. [Freshness regressions](../../backend/services/api/tests/test_type_text_search.py)

The broad suite passed **487 tests across 41 modules** using a fresh database. It covered typed and legacy search APIs, saved queries, authorization, cached pages, disposition, component evidence, storage, schema and migration checks. The runner dropped the database. The five focused cases overlap the broad suite. [Selected modules and run outcomes](types-p4-regressions.json.gz)

## Existing installations

Migration 120 installs the triggers and refreshes only owners with populated text. It preserves the document's text configuration. It leaves the component content sets, chunk indexes and extraction queue alone. The populated upgrade test loads the Phase 3 schema and fields first, then applies the actual migration. [Deployment instructions](../../database/README.md#existing-database) · [Upgrade regression](../../backend/services/api/tests/test_type_text_upgrade.py)

## Benchmark scope

Both disposable fixtures contain 51,003 aggregations, 153,009 records and 5,001 resources with stored type text per kind. Of those, 21 per kind contain a 9,000-character repeated passage followed by a searchable English/Arabic phrase. The benchmark checks the broad type-only search (10,002 matches), a primary-and-type conjunction, a phrase at the end of the long field, and type-text OR component content. It compares every returned ID and score with a separate SQL ranking and verifies full match counts against the fixture. It also changes a text value, follows a cached cursor, searches for the new term, revokes the reader’s type grant and retries. [Fixture and measurement code](../../tools/type_text_search_performance.py)

Run the two commands consecutively with the API virtual environment active. Both create and drop their own local databases. The larger-text runner uses a 60-second idle interval and three rounds under the November 14 protocol. It records waits and host I/O. Both runners keep the response timings and actual plans.

```sh
python tools/check_search_performance.py --type-text --settle-seconds 30 --repeats 3 --output .runtime/search-performance/local-p4-standard
python tools/check_large_text_search_performance.py --type-text --settle-seconds 60 --repeats 3 --sample-waits-and-io --output .runtime/search-performance/local-p4-rich
```

The initial standard run passed all 1,524 existing timings. The slowest was 2.6387 s, compared with 2.9968 s in Phase 3. All 296 ranked-output and expectation files were byte-identical to Phase 0. The dedicated workload’s slowest HTTP response was 0.298 s. Its eight plans cover both resource kinds. The 5,001-row backfill including commit took 0.363 s for records and 0.618 s for aggregations. These times measure the backfill after a bulk load. They exclude migration lock acquisition and any wait for existing writers in a deployment. [Standard evidence](types-p4-standard-01.json.gz)

The initial larger-text run passed its 428 existing response timings, with a 2.4704 s maximum against 2.8728 s in Phase 2. All 19 comparable rankings, expectations and uncapped membership files matched the accepted pre-feature baseline byte for byte. All 180,630 chunk vectors used LZ4 with the existing MAIN storage policy. The actual rare combined-query plan scored its 1,200 matching chunks in one execution. The negative phrase plan also executed the chunk scoring set once. Both fixtures used PostgreSQL 18.4 without LLVM JIT. [Larger-text timings, plans and correctness](types-p4-rich-01.json.gz) · [Wait events and host I/O](types-p4-rich-waits-and-io.jsonl.gz)

| Initial type-text measurement | Standard corpus | Larger-text corpus |
| --- | ---: | ---: |
| Complete HTTP responses | 56 | 83 |
| Slowest HTTP response | 0.2976 s | 0.3558 s |
| Committed single-field edit, measured separately | 0.0134 s | 0.1242 s |
| Backfill and commit for 5,001 records | 0.363 s | 0.365 s |
| Backfill and commit for 5,001 aggregations | 0.618 s | 0.540 s |
| Broad text-only matches before the 1,000-hit cap | 10,002 | 10,002 |
| Mixed text-field or component matches before the cap | 94 | 1,224 |

All 16 type-text query plans built the effective-role and accessible-type sets once. Each run followed the broad search through its full capped list and checked every ID and score. On the edit test, record 4 stopped matching the original term and the next cached page returned record 7. A fresh search found record 4 by its replacement term. Revoking the type grant removed the matches on both the existing cursor and a new search. Both benchmark databases were dropped.

The focused API suite passed five cases. It verified English and Arabic matching, metadata evidence, absence of ancestor inheritance, excluded scalar values and choice labels, primary edits, type changes, clearing and removal. It also verified rollback and concurrent independent field writes for both resource kinds, and actual disposition destruction with retained proof. The first test attempt was blocked before database creation by local connection permissions. The next used an incorrect header-search test URL. The regression now uses the WebUI’s actual full-text endpoint. The separate populated Phase 3 upgrade regression passed for both kinds, including unchanged untyped document timestamps and unchanged primary-term scores. [Upgrade test](../../backend/services/api/tests/test_type_text_upgrade.py)

The historical upgrade rehearsal used the following commands. The runner installed the pre-type revision in one disposable database and the then-current canonical schema in another. After verifying migrations 118 and 119 it created 5,001 resources with a populated text field per kind in the older database, applied migration 120, compared every metadata document against its pre-upgrade vector plus the expected weighted text, and compared both schema dumps. The focused regression separately initialized the Phase 3 schema and tested removal after the upgrade.

```sh
python tools/check_resource_type_upgrade.py --output .runtime/search-performance/local-p4-upgrade
python tools/run_disposable_acl_tests.py --baseline-ref=f9de54c6 --migration=database/migrations/120_type_text_search.sql --seed-required-reference-data --defer-migrations-to-test backend/services/api/tests/test_type_text_upgrade.py
```

On the full rehearsal, migration 120 including commit took **0.9886 s** with no competing writers. All 204,012 metadata rows matched the independently calculated vector from their pre-upgrade bytes. The migration indexed 5,001 records and 5,001 aggregations, preserved the original configuration and version for every row, and preserved indexing timestamps wherever the vector stayed the same. The fresh and upgraded schema dumps had identical SHA-256 hashes. Both databases were dropped. The focused upgrade rerun additionally exercised an existing English stemming configuration on a record and the default simple configuration on an aggregation. [Full upgrade report and cleanup](types-p4-upgrade-large-01.json.gz)
