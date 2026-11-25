# Localized classification title display

Classification workspace labels previously selected the canonical `title` even
when the API supplied an effective `localized.title`. An Arabic interface could
therefore display English scheme and classification names despite existing
entity translations. The reverse also applied: Arabic canonical titles could
remain Arabic in an English interface despite available English translations.

## Behavior and scope

`classification_labels.classification_title` selects a nonblank API-localized
title, falling back to the canonical title for missing, empty or legacy
projections. Language resolution remains on the API. Rendering does not modify
entity dictionaries, canonical editor values, codes, ordering or permissions.

The helper covers workspace tree/search nodes, full-title tooltips, accessible
names, headings, ancestor links, parent metadata, retention provenance,
lifecycle confirmations and the export-dialog scheme reference. Classification
pickers, aggregation browsers/selectors and aggregation classification metadata
use the same effective title. Stored aggregation/record titles and immutable
history snapshots retain their existing treatment.

The three existing classification browse routes now supply the same localized
projection as classification detail/list/path responses. Classification branch
projection occurs only after server paging. Internal translation maps are removed
from the bounded node response; canonical titles remain present. Filters, cursor
identity, code order and authorization policies are unchanged. No migration is
required.

Persisted classification breadcrumbs are revalidated on authenticated reload,
including language changes. Each distinct prior reference is fetched once within
the existing 20-entry trail, using the API client's concurrency limit. The current
destination uses its normal detail read. Fresh detail responses also update prior
visits to that entity. ID-only loading placeholders do not replace labels.
Unavailable references are removed; transient failures retain only stable identity
rather than an old-language title. No new entity or label cache is introduced.

## Verification

On the restored `localizedDisplayFix` worktree, 75 frontend unit/navigation and
NiceGUI interaction tests passed. These cover effective-title selection,
canonical fallback and editor preservation, language/client isolation,
breadcrumb refresh, pickers, paging and abandoned responses. All 18 Python fix
files compile; whitespace, API environment-template consistency and
configuration-authority checks pass.

A fresh disposable PostgreSQL 18 preview passed API health, synthetic login,
UI HTTP readiness and Arabic → English → Arabic localized browse checks while
preserving canonical titles. The human confirmed the preview works. Its database
was dropped and absence independently verified after testing; owned services
were stopped and temporary runtime/tooling removed.

Earlier validation on the prior base included classification API authorization
and pagination tests, browser checks and the large-data search performance gate.
Those are historical results, not a rerun on this base. Remote CI and a new full
API/performance suite remain outstanding. No regression was detected in current
focused checks or reported in human testing.

Missing or blank entity translations deliberately fall back to canonical titles.
When a persisted breadcrumb cannot be refreshed because of a transient failure,
it displays stable identity rather than retaining a previous-language title.
No migration or specification rewrite is required.

## Scheme selector search and ordering follow-up

`GET /api/v1/browse/classification-schemes` also searches title translations
for enabled languages, regardless of the current UI language, as required by
internationalization specification section 12. Canonical titles and codes
remain searchable. Translation descriptions, JSON property names and disabled
languages do not produce title matches. Publication eligibility and route
authorization are unchanged.

Section 11.5 ordering is performed in PostgreSQL before `LIMIT` and `OFFSET`,
using the same effective title as the response projection. Installed ICU
collations are selected in effective-language, parent-language and `und` order;
installations without one use explicit `pg_catalog."C"` Unicode ordering.
Code in `C` ordering and ID break title ties. Canonical fields remain intact.
No new index, migration, setting or cache is introduced.

`backend/services/api/tests/test_localized_classification_titles.py` traces
these contracts to API regressions for translated type-ahead, ordering across
pages, regional/canonical fallback, stable duplicate-title ordering,
enabled-language changes and publication filtering. The display regressions
also exercise the three localized browse routes. The companion NiceGUI tests
cover both directions, editor values and both classification pickers.

The changed selector has its own workload in the existing disposable gate:

```sh
backend/services/api/.venv/bin/python tools/check_search_performance.py \
  --classification-schemes-only --repeats 3 \
  --output .runtime/search-performance/classification-schemes-new
```

It retains the standard 51,003-aggregation/153,009-record document fixture and
adds 5,003 published, 23 draft and 17 future-published schemes. It checks
English/Arabic title ordering, canonical and translated matching, broad,
selective, empty, disabled-language and description-only criteria, complete
catalogue traversal and offsets beyond 1,000. Both signed-in fixture identities
can browse scheme metadata, including the identity denied document access;
anonymous requests remain denied. Every measured response has a three-second
ceiling. Expected rows, returned IDs, timings, execution plans, JIT availability
and database cleanup are retained under the chosen output directory. This is
the selector workload; it does not rerun unrelated full-text ranking cases.

Verification on 25 November 2026: merge commit `3616015b` passed 308 focused
post-merge unit, interaction and API checks before the follow-up changes.
The follow-up then passed all eight API regressions in the title test module.
The selector gate passed all 447 measured responses; the maximum was 0.067806
seconds on native PostgreSQL 18.4. Captured plans used one catalogue scan,
shared enabled-language selection and bounded result sorting; the selective
Arabic case expanded translations for seven candidates. This local build has
no JIT support, so no compilation time was observed. Every owned disposable
database was dropped and absence independently verified. Raw evidence is in
gitignored `.runtime/pr72-followup/`, including plans and source hashes.
