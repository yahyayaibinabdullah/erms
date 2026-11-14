# Favourite numbers and View all persistence

**Status: both fixes locally verified on 12 November 2026.**
The user explicitly approved these two follow-up fixes. Changes remain local
and uncommitted on `refactor-API-python-file`; all earlier work is preserved.

## Corrections

- Favourite rows now choose the number by resource type: records use
  `record_number`, aggregations use `aggregation_number`. The same renderer
  supplies both the dashboard preview and View all. The existing translated
  identity label remains unchanged.
- View all is now created under the dashboard content container, outside the
  favourites panel that is rebuilt after removal. The same dialog stays open,
  showing the remaining favourites or the existing empty state. Its Close button
  still works, and leaving the dashboard removes the dialog with its page.

Both changes use existing NiceGUI components and parent contexts. No CSS,
dimensions, API/schema, permissions, translations, navigation or browser-history
changes are introduced. The previous success-notification fix is preserved.
There are no new requests or caches. The sole application file changed by this
follow-up is `frontend/webui/dashboard.py`.

## Requirement → verification

| Requirement | Verification |
| --- | --- |
| Correct record identity even when a parent aggregation number is present | Distinct record/aggregation numbers in real factory fixtures; native exact translated identity assertions |
| Keep aggregation identity correct | Both resource types, dashboard preview and View all |
| Keep the same dialog open across removal | Native dialog element identity retained across two successive removals |
| Handle the final favourite | Existing empty-state label remains visible inside the open dialog |
| Keep explicit closing and page cleanup | Keyboard activation of native Close; real factory close and page-deletion assertions |
| Preserve notification, counts and caches | Real notifier, native translated feedback, badge/list totals, API persistence, held-refresh return navigation |
| Preserve rejection and abandoned requests | Negative feedback without losing favourites; no late feedback/cache write after navigating away |
| Preserve English and Arabic behavior | Both languages in focused and Chrome/Edge journeys |

## Verification

- **36 interaction tests passed**, including all 32 favourite cases and four
  existing dashboard identity/cache tests. The favourite cases use the actual
  feature factory and the opening button's native parent-slot context.
- **28 unit tests passed** for session isolation and feature boundaries:
  **64 focused tests** in total, with network/database access blocked.
- Before the changes, 20 cases failed: all 16 record cases detected the wrong
  number, and four aggregation-dialog success cases detected the deleted dialog.
  The other 12 cases passed. All 32 now pass.
- **Chrome 157.0.8103.40 and Edge 157.0.4341.46 passed**, each with nine check
  groups and 16 screenshots. Both English/LTR and Arabic/RTL verify exact resource
  labels in the dashboard and View all, retained dialog identity through two
  consecutive removals, the final empty state and keyboard activation of Close.
- Both final runs preserve notifications, count updates, API persistence, cached
  freshness, single-flight warm refresh and keyboard navigation. Together they
  perform 20 UI removals plus four API removals used as refresh fixtures. Neither
  run has unexpected browser errors, failed API requests or server tracebacks.
- English and Arabic captures were visually reviewed in both browsers. All 186
  recorded application/harness source hashes per run match current files;
  screenshots and regression-test source hashes are retained.
- Catalogue coverage, Arabic terminology, ordering, nonblank text, placeholders,
  provenance and unchanged artifact hashes pass. Configuration authority, API
  template consistency, Python syntax and `git diff --check` pass.
- All **four uniquely named disposable PostgreSQL databases** were initialized
  through the canonical runner and dropped, including the two interrupted runs.
  An independent PostgreSQL catalogue query confirms removal; no owned test
  processes or native drivers remain. No persistent database was used.

This is focused local verification, not a full-suite, CI or timing benchmark.
The reusable native check is the `dashboard` scope of
`tools/run_webui_integration.py`. It retains keyboard navigation, connected record
details, non-destructive warm refresh and one-delete-per-click assertions.

No catalogue keys, source wording, placeholders, ordering or Arabic provenance
change. No administrator export or persistent database translation is modified;
no new translation review is required.

## Development evidence

The initial number edit matched another occurrence of the same expression.
Focused tests caught it. That unrelated edit was restored, and the correction
was applied specifically inside `render_favourite_entry`. The two browser runs
started for that intermediate source were stopped through their owned runners;
both disposable databases were dropped. The unsuccessful interaction result and
interrupted native evidence are retained separately from final acceptance.

## Retained evidence

- [Acceptance and source identity](verification/dashboard-favourite-details-fix/acceptance.json)
- [Chrome results](verification/dashboard-favourite-details-fix/chrome/browser-results.json)
  and [Edge results](verification/dashboard-favourite-details-fix/edge/browser-results.json)
- [Focused before/after comparison](verification/dashboard-favourite-details-fix/focused-comparison.json),
  [interaction results](verification/dashboard-favourite-details-fix/interaction/tests.xml)
  and [unit results](verification/dashboard-favourite-details-fix/unit/tests.xml)
- [Application changes for this follow-up](verification/dashboard-favourite-details-fix/application-change.diff)
- [Validation](verification/dashboard-favourite-details-fix/validation.json),
  [database cleanup](verification/dashboard-favourite-details-fix/database-cleanup.json),
  [process cleanup](verification/dashboard-favourite-details-fix/process-cleanup.json)
  and [file hashes](verification/dashboard-favourite-details-fix/manifest.sha256)

Both issues are moved to the corrected section of the
[defect register](webui-refactor-existing-observations.md). The earlier notification
report remains historical evidence of their discovery. No branch, worktree,
staging, commit, history, remote or system-setting changes were made.
