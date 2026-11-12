# Classification-scheme refresh callback repair

**Superseded:** the user later authorized [removal of the obsolete scheme table](classification-scheme-table-removal-verification.md).
This report and its evidence describe the earlier implementation.

**Status: fixed and locally verified on 12 November 2026.**

## Scope and correction

The user authorized repairing the remaining classification-scheme refresh
callback while preserving saved navigation and existing UX. All changes remain
local and uncommitted on `refactor-API-python-file`.

The legacy table tried to refresh using `render_governance_cards` and
`card_host`, neither available in that path. It now uses the ordinary bounded
collection reload and table renderer. The callback checks its actual table
before starting a read and while accepting the result, so a completed mutation
or read cannot repaint a destination the user has left.

Two related blockers in the same workflow are also corrected:

- Fresh scheme collection state uses its existing `title` field for the default
  sort, rather than the nonexistent `name` field. Existing query, sort, limit
  and offset settings remain intact.
- Deactivate/reactivate requests use fixed API action identifiers. Translated
  wording remains presentation text, rather than becoming an Arabic API URL.
  The existing automatic audit-reason format uses the action identifier too.

No saved navigation entries are migrated, removed or redirected to another
feature. The dedicated workspace and its callbacks are unchanged. No layout,
visible text, translations, controls, permissions, schema, cache or public URL
changes are introduced. No new confirmation step is added to the legacy actions.

## Verification

- **74 unit tests and 41 interaction tests passed** (115 total).
- Fourteen new real-widget cases exercise the actual collection-table factory,
  action bindings and bounded loader in English and Arabic: publish/deactivate/
  reactivate with fresh versions; default and retained custom paging/filter/sort;
  navigation during a mutation or read; mutation/read errors; empty refresh.
- Captured pre-fix factories run in memory reproduce each problem separately:
  four callback failures with `render_governance_cards` unavailable; invalid
  default-sort failures in both languages; Arabic lifecycle URL failures.
  Working-tree source was never replaced. The old default-sort page failure also
  produces NiceGUI teardown error reports; these are expected pre-fix evidence,
  separate from the passing acceptance run.
- Existing saved-navigation, collection loading/save/filter, feature-boundary,
  classification controller/editor/workspace and collection-language tests pass.

| Browser | English and Arabic result | Passing groups | Screenshots |
| --- | --- | ---: | ---: |
| Chrome 157.0.8103.51 | Pass | 7 | 10 |
| Edge 157.0.4341.46 | Pass | 7 | 10 |

Both browser runs passed on their first attempt. Each verified restored legacy
navigation, root reload, all three actions in each language, changed row state,
fresh versions, one mutation and exactly one successful bounded refresh per
action, unchanged application URL/history during actions, and return to the
dedicated workspace followed by reload. This includes four publications, four
deactivations and four reactivations across the two browsers/languages.

There were no browser errors, unsuccessful recorded API requests or server
tracebacks. All 188 application/harness source hashes per run match the verified
files. The legacy table's LTR/RTL captures were visually inspected in both
browsers; existing headers, spacing, action treatment and direction are retained.

Both uniquely named disposable PostgreSQL databases were initialized through
the canonical runner and dropped. An independent catalogue query confirms
cleanup; no owned test processes or native drivers remain. No persistent
database was used. Branch and HEAD are unchanged, with no staging, commits,
pushes, history operations or branch/worktree changes.

Catalogue reference/stale-key checks, ordered English/Arabic key coverage,
nonblank wording, placeholders, provenance, approved terminology and unchanged
artifact hashes pass. No keys or translations changed, no administrator export
was promoted and no translation review is newly required. Configuration authority,
API template consistency, Python syntax and `git diff --check` pass.

This is focused local verification. No full-suite, CI, Firefox/Safari or
comparative performance benchmark is claimed. The refresh introduces no cache
and makes one bounded read after a successful mutation; delayed/abandoned-view
cases and retained request settings are covered by the interaction tests.

## Test fixture boundary

The `legacy-schemes` browser scope installs one test-only fixture page in the
runner-owned WebUI. It requires a disposable database and signed-in test session,
writes an old `classification-schemes` navigation entry to that session, and
returns to the ordinary application root. The real application bootstrap,
navigation restoration, renderer, API and actions perform the checks.

Production startup never installs this fixture page. No application callback,
API response, style or translation is substituted. Each language uses a fresh
synthetic scheme, so publication, deactivation and reactivation are all tested
in both languages. The ordinary classification menu and detail reload are also
checked after returning from the legacy table.

## Preserved observations

The restored legacy collection retains its existing default “Dashboard” heading
and English action tooltips/date formatting in Arabic. These are presentation
issues in the old view, not refresh failures, and remain outside this repair.
The current dedicated classification workspace remains the menu destination.
The legacy table's client pager also remains local to its bounded server page;
it has no equivalent of the dedicated workspace's server-page controls. This
pre-existing completeness limitation needs separate review, rather than a new
pagination UX in this callback repair.

## Retained evidence

- [Acceptance record](verification/classification-scheme-refresh-fix/acceptance.json)
- [Application-only diff from the initial checkpoint](verification/classification-scheme-refresh-fix/application-change.diff)
  and [pre-fix comparisons](verification/classification-scheme-refresh-fix/before-after.json)
- [Unit results](verification/classification-scheme-refresh-fix/unit/tests.xml)
  and [interaction results](verification/classification-scheme-refresh-fix/interaction/tests.xml)
- [Chrome results](verification/classification-scheme-refresh-fix/chrome/browser-results.json)
  and [Edge results](verification/classification-scheme-refresh-fix/edge/browser-results.json)
- [Validation](verification/classification-scheme-refresh-fix/validation.json),
  [database cleanup](verification/classification-scheme-refresh-fix/database-cleanup.json),
  [process cleanup](verification/classification-scheme-refresh-fix/process-cleanup.json)
  and [evidence hashes](verification/classification-scheme-refresh-fix/manifest.sha256)

The callback defect is moved to the corrected section of the
[defect register](webui-refactor-existing-observations.md). Prior cleanup reports
remain historical evidence of the earlier preserved defect.
