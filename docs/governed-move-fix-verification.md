# Governed Move — P1 fix and verification

**Status: P1 dialog crash fixed and locally verified on 11 November 2026.**
The user authorized this separate bug fix after completion of the WebUI refactor.
Work starts from `refactor-API-python-file`, HEAD
`3a0cd0042af4f69a36a0e0130f7010abb839215c`. All changes stay local and uncommitted.

## Cause and correction

The aggregation/record Move dialog used bounded remote destination search, but
still checked the removed `compatible_aggregations` list before opening. That
raised `NameError` for both resource types.

`aggregation_actions.py` now uses the existing selector's resolved-options
callback to show the existing empty-result hint. The selector stays enabled so
a different query can recover from an empty page. The hint starts hidden until
results arrive, and late search results are ignored after the dialog closes.
Selected destinations remain visible during subsequent searches.

The destination search remains bounded to 25 rows. Existing medium compatibility
and aggregation self-exclusion rules remain intact. The move preview, reason,
version, ownership confirmation, ACL policy and save/refresh callbacks are
unchanged. No API, schema, configuration, URL, layout or wording changes are made.
No cache is introduced. Both translation artifacts remain byte-identical.

## Requirement → implementation → verification

| Existing requirement | Implementation | Verification |
| --- | --- | --- |
| Both Move dialogs open | Remove stale list access; bind empty hint to remote results | Four failing-before cases, then passing English/Arabic aggregation/record cases |
| Bounded, compatible destination search | Existing remote selector, medium predicate and self-exclusion | Real selector tests: limit 25, empty-result recovery, selected-value retention; browser destination beyond first 25 rows |
| No mutation on invalid input or cancellation | Existing destination/reason/preview guards | Interaction tests and native cancellation/version checks |
| Reasoned, versioned move with explicit ACL choice | Existing preview and move payload | Both ACL choices and ownership flags in interaction tests; real moves and persisted ACL checks |
| API denial/conflict leaves the dialog usable | Existing `ApiError` handling | Denied preview and conflicting write tests; reason and dialog retained |
| Fresh destination and unchanged content after a move | Existing detail refresh and reload | Browser parent links, entity ID/title/medium, versions, nested aggregation and ACL verification |
| Abandoned destination reads cannot update a closed dialog | Selector `active` callback | Delayed response released after cancellation is ignored |
| Restricted resources remain undisclosed | Unchanged server authorization | Native test session expects the specified `404` for both preview endpoints |

## Verification

- **38 interaction tests passed**, including 32 new Move cases and six existing
  reopen/ownership-correction cases.
- **163 related unit tests passed**: entity contracts, relationship search and
  feature boundaries.
- **18 runner/diagnostic safety tests passed** with mocked database operations.
- Configuration authority, API template consistency, catalogue references and
  approved Arabic terminology checks passed. No keys or translations changed;
  no administrator export was promoted and no new translation review is needed.
- **Chrome 157.0.8103.40 and Edge 157.0.4341.42 passed**: 14 check groups,
  eight persisted moves and 12 screenshots per browser. Both resource types were
  verified in English/LTR and Arabic/RTL with both access-preservation choices.
  Cancellation, recovery from empty/incompatible searches, destinations beyond
  the first 25 rows, detail refresh and browser reload passed.
- No browser errors or unexpected failed requests occurred in either final run.
  Each run retained two expected `404` responses for restricted preview requests.
- All **six disposable databases**, including failed/interrupted development
  attempts, were dropped. An independent PostgreSQL catalogue query confirmed
  none remain. No test-path processes or Chrome/Edge drivers remain.

The acceptance evidence is [recorded here](verification/governed-move-fix/acceptance.json),
with [Chrome results](verification/governed-move-fix/chrome-final/browser-results.json),
[Edge results](verification/governed-move-fix/edge-final/browser-results.json),
screenshots, logs, test XML and source hashes alongside it. The 219 focused tests
are counted once; development attempts and repeat runs are not added to that total.
This is focused local verification, not a new full-suite, CI or performance-benchmark
certification. The dialog performs no initial destination request, subsequent
searches remain bounded, and abandoned reads are covered.

The browser journey is reusable through:

```sh
backend/services/api/.venv/bin/python tools/run_webui_integration.py --browser chrome --browser-scope governed-moves
backend/services/api/.venv/bin/python tools/run_webui_integration.py --browser edge --browser-scope governed-moves
```

Each command creates and removes its own uniquely named local PostgreSQL database,
initialized from the canonical schema. It never uses a persistent ERMS database.
The recorded runs used the existing cached native drivers through the retained
`run-browser.py`/`pinned-browser.py` wrappers; no drivers were installed or browser
settings changed. Git branch and HEAD are unchanged; no changes were committed,
staged or pushed.

## Separate existing defects exposed by the restored dialog

- **P2: aggregation subtree counts display zero.** The dialog reads
  `aggregation_count`/`record_count`, while the backend supplies
  `affected_aggregation_count`/`affected_record_count`. A real nested child was
  preserved by the move, but the preview displayed zero. The pre-fix source
  contains the same mismatch; it is separate from the repaired opening crash.
- **P3: Arabic Move titles contain the English resource name** (`aggregation` or
  `record`) because the existing title receives `resource.rstrip('s')` directly.
  Existing catalogue text and rendering are unchanged.

These were left open by the P1 repair, then separately authorized and corrected
in the [preview-count and Arabic-title follow-up](governed-move-details-fix-verification.md).
The [prioritized defect register](webui-refactor-existing-observations.md) records
their current status; the original P1 evidence above remains unchanged.

## Test-development observations

The initial regression reproduces the original `NameError` in both languages and
both resource types. NiceGUI also reports the same page exception at teardown.
The old test requiring that defect to remain is replaced by behavior coverage.

An initial combined unit/interaction invocation caused six unit UI-context
failures; the suites pass in separate processes. Runner safety tests require the
API virtual environment, which supplies psycopg. Neither issue required an
application change.

The new native journey needed corrections to wait for the asynchronously rendered
action panel, match the existing card-style destination option, and expect `404`
non-disclosure for a user without view permission (security specification §9.5).
The first complete Chrome move sequence passed all eight moves before the incorrect
`403` assertion failed. An owned Edge attempt was stopped to correct that same
assertion. Failed/interrupted attempts are retained and excluded from acceptance;
the production fix did not change during these test corrections.
