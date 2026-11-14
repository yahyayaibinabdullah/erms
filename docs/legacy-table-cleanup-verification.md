# Legacy table caller audit and cleanup

**Superseded:** the user later authorized [removal of the obsolete scheme table](classification-scheme-table-removal-verification.md).
This report and its evidence describe the earlier implementation.

**Status: completed and locally verified on 12 November 2026.**

Follow-up: the separately authorized
[classification-scheme refresh repair](classification-scheme-refresh-fix-verification.md)
now fixes the preserved callback. This report records the earlier cleanup scope.

## Scope and decision

The user authorized auditing callers and removing only confirmed unused legacy
code, preserving functionality and UX. Changes stay local and uncommitted on
the existing `refactor-API-python-file` branch.

Only the obsolete aggregation Open/Reopen table buttons, their event callbacks
and two unused factory dependencies are removed. The active aggregation detail
screen and its reopen callback are unchanged. No table layout, text catalogue,
API, permission, cache, URL or browser-history behavior changes.

The generic table is **not** deleted. In particular, the classification-scheme
fallback cannot be certified unused: persisted navigation accepts an entity page
name and dispatches it through `select_entity`. Its broken refresh remains
documented, rather than silently deleting potentially reachable actions. This
qualifies the earlier statement that both defective fallbacks were unreachable.

## Caller audit

| Entry/caller | Existing dispatch | Decision |
| --- | --- | --- |
| Drawer and dashboard Aggregations entries | `select_entity` → `render_table`; unsearched collections render personal sections, searched collections render compact results; both return before the generic table | Old aggregation-specific table action blocks are unreachable |
| Aggregation search mode, loader refresh, editor save and record capture | `collection_navigation`, `collection_controls`, `aggregation_browser`, `entity_editor`, `record_capture` use the same renderer | Early return applies to every aggregation caller, including repeated/empty search refresh |
| Aggregation favourites, recent items and dashboard review | `personal_resource_views` and `dashboard` open detail or use that same renderer | Preserve personal sections and active detail callbacks |
| Global search, advanced/saved search and compact result links | `global_search`, `advanced_search`, `resource_collection_results` call the active detail callback | Do not use the deleted generic-table actions |
| Aggregation restored navigation and linked/audit destinations | Host restoration selects the entity or opens its detail; browse restoration stays with its tree | Preserve the current tree/detail/compact dispatch |
| Active aggregation reopening | `aggregation_details.reopen_current` → `aggregation_actions.show_reopen_aggregation` → reload recent items and reopen detail | Unchanged; native mutation/refresh/reload checks added |
| Classification drawer, dashboard shortcuts and audit links | Dedicated `select_classification_workspace`/controller | Preserve dedicated workspace and its publish/lifecycle refresh |
| Classification create/edit | Workspace supplies explicit resource and `on_saved` callback; shared entity editor remains in use | Preserve classification editor helpers |
| Classification restored current workspace/detail entries | Dedicated controller via `classification-workspace`, `classification-scheme-details`, `classification-details` | Preserve these routes through internal navigation |
| Persisted legacy `classification-schemes` entry | `NavigationController` reads stored page strings; host `page in ENTITIES` → `select_entity(page)` → generic table | Do not remove scheme actions or the defective refresh under an unused-code-only authorization |
| Records, administration cards and other generic-table consumers | Existing dispatch and shared helpers | Unchanged; no wholesale generic-table or helper-module deletion |

The aggregation proof does not depend on lack of observed clicks: the earlier
return in `render_table` dominates both deleted blocks, and `EntitySpec` is frozen.
All production assembly occurs in `app.py`; its two removed dependencies were
used only by the deleted block. Other consumers of the active aggregation
actions remain wired. A regression executes the real navigation-restoration
callback and confirms the persisted scheme entry still selects the collection.

## Verification

- **74 unit tests and 33 interaction tests passed** (107 after cleanup).
  Coverage includes collection loading/filtering/save refresh, navigation
  restoration, feature boundaries, classification controller/editor/workspace,
  aggregation actions and page-local translation context.
- Eight new collection-dispatch cases also pass against the captured pre-cleanup
  factory executed in memory. Both versions keep compact results and personal
  sections on initial/repeated rendering, for Aggregations and Records, searched
  and unsearched, in English and Arabic. Working-tree files were not replaced.
- The saved-scheme navigation regression executes the real restoration callback
  and confirms the generic entity destination remains accepted.

| Native browser | Feature journey, both English/LTR and Arabic/RTL | Passing groups | Screenshots |
| --- | --- | ---: | ---: |
| Chrome 157.0.8103.51 | Aggregations | 9 | 30 |
| Edge 157.0.4341.46 | Aggregations | 9 | 30 |
| Chrome 157.0.8103.51 | Classification workspace | 11 | 24 |
| Edge 157.0.4341.46 | Classification workspace | 11 | 24 |

All four runs passed on their first browser attempt, with no browser errors,
unsuccessful recorded API requests or server tracebacks. The 187 recorded
application/harness source hashes per run match the final files.

Aggregation checks exercise search, independent child/record pagination,
zero-result filter recovery, linked-record return, editor keyboard focus,
action dialogs, real close/reopen mutations, refreshed detail, persisted closure
state/version, reload and hierarchy-return restoration in both languages.

Classification checks exercise bounded hierarchy paging, retained expansion,
inherited retention, editor keyboard focus, event-history and transfer entry,
empty scheme filtering, real publication in English, published state in Arabic,
and real deactivate/reactivate mutations with detail refresh/reload in both
languages. The unused synthetic scheme is shared between language passes;
publication is not repeated in Arabic. These checks use the dedicated workspace,
not the preserved defective generic-table callback.

Post-reopen aggregation and post-reactivation scheme captures were visually
inspected in both languages and browsers. No appearance or interaction change
was observed. No active renderer, request flow or cache changed; this is focused
local verification, not a full-suite run or a comparative timing benchmark.
Firefox, Safari and remote CI remain outside the requested scope.

Catalogue reference/stale-key checks, ordered English/Arabic coverage,
nonblank wording, placeholders, provenance, approved terminology and unchanged
artifact hashes pass. Configuration authority, API template consistency, Python
syntax and `git diff --check` pass. No translation keys or wording changed, no
administrator export was promoted, and no translation review is newly required.

All four uniquely named disposable PostgreSQL databases were initialized by the
canonical runner and dropped. An independent PostgreSQL catalogue query confirms
their removal; no owned test processes or native drivers remain. No persistent
database was used. Branch and HEAD match the initial checkpoint. No staging,
commits, pushes, branch/worktree changes or history operations were performed.

During test development, the new absence assertion incorrectly used NiceGUI's
`user.find`, which raises when the requested table is absent. It now checks the
actual client elements; all eight cases pass before and after cleanup. A first
unit command named a nonexistent test file and ran no tests; the corrected
selection passes all 74. Both development attempts are retained separately.

## Evidence and remaining defect

- [Acceptance and source verification](verification/legacy-table-cleanup/acceptance.json)
- [Caller audit](verification/legacy-table-cleanup/caller-audit.json) and
  [application diff](verification/legacy-table-cleanup/application-change.diff)
- [Unit results](verification/legacy-table-cleanup/unit-final/tests.xml),
  [interaction results](verification/legacy-table-cleanup/interaction-final/tests.xml)
  and [pre-cleanup dispatch results](verification/legacy-table-cleanup/before-dispatch/tests.xml)
- [Chrome aggregations](verification/legacy-table-cleanup/chrome-aggregations/browser-results.json),
  [Edge aggregations](verification/legacy-table-cleanup/edge-aggregations/browser-results.json),
  [Chrome classification](verification/legacy-table-cleanup/chrome-classification/browser-results.json)
  and [Edge classification](verification/legacy-table-cleanup/edge-classification/browser-results.json)
- [Validation](verification/legacy-table-cleanup/validation.json),
  [database cleanup](verification/legacy-table-cleanup/database-cleanup.json),
  [process cleanup](verification/legacy-table-cleanup/process-cleanup.json)
  and [evidence hashes](verification/legacy-table-cleanup/manifest.sha256)

The remaining **P3 classification-scheme generic refresh defect is not fixed**.
Deleting it requires an explicit decision about old persisted entity navigation,
or it can be repaired separately while preserving that path. The
[defect register](webui-refactor-existing-observations.md) now records this precise
scope instead of describing both callbacks as unreachable.
