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
