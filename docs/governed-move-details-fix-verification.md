# Governed Move — preview counts and Arabic titles

**Status: both fixes completed and locally verified on 11 November 2026.**
This is the separately authorized follow-up to the [P1 dialog repair](governed-move-fix-verification.md).
All changes remain local and uncommitted on `refactor-API-python-file`, starting
at HEAD `3a0cd0042af4f69a36a0e0130f7010abb839215c`. Earlier uncommitted work is preserved.

## Corrections and traceability

| Defect | Correction | Verification |
| --- | --- | --- |
| Aggregation preview always displayed zero subtree counts | Read the API's `affected_aggregation_count` and `affected_record_count` fields | English/Arabic interaction cases for 0/0, 2/3 and 7/11; native fixture with one nested aggregation and two records |
| Arabic titles included `aggregation` or `record` | Interpolate the existing translated singular resource label | Exact `نقل ملف` and `نقل وثيقة` assertions; existing English `Move aggregation` / `Move record` preserved |

Only `frontend/webui/aggregation_actions.py` changes application behavior in this
follow-up. Titles use the existing plain-text translation renderer inside the
existing complete title message, retaining its Inspector metadata and bidirectional
isolation. Record dialogs continue to omit aggregation subtree counts.

No API/schema, ACL rules, move payload, layout, URLs or navigation changes are
needed. Existing bounded search, cancellation, detail refresh and reload checks
remain in the native journey. The nested aggregation and both nested records must
retain their identities and relationships after each move.

## Verification

- **48 interaction tests passed**, including ten new title/count cases.
- **163 related unit tests passed** for entities, relationships and module boundaries.
- **16 literal-message rendering tests passed** for escaping, interpolation and
  Inspector framing. Total: **227 focused tests**, counted once.
- Configuration authority, API template consistency, catalogue references,
  approved Arabic terminology and the existing pure artifact validator passed.
- **Chrome 157.0.8103.40 and Edge 157.0.4341.42 passed**: each completed
  14 check groups and eight saved moves across English/LTR and Arabic/RTL.
  Each browser checked 12 localized dialog titles and six nonzero subtree
  previews, covering cancellation and both access-preservation choices.
  Nested-child preservation, fresh detail links and browser reload passed.
- Visual review confirmed the corrected Arabic aggregation and record titles
  in both browsers, along with the English presentation and nonzero counts.
  Each final run retains 12 screenshots.
- Neither final run reported browser errors or unexpected failed requests.
  Each retained two expected `404` responses for restricted preview requests.
- All **four disposable databases** were dropped, including the initial failed
  attempts. An independent PostgreSQL catalogue query confirmed none remain.
  No owned test processes or Chrome/Edge drivers remain.

Evidence: [acceptance record](verification/governed-move-details-fix/acceptance.json),
[Chrome results](verification/governed-move-details-fix/chrome-final/browser-results.json),
[Edge results](verification/governed-move-details-fix/edge-final/browser-results.json),
and [cleanup audit](verification/governed-move-details-fix/database-cleanup.json).
Screenshots, raw logs, test XML, source hashes and development attempts are retained
alongside them. Final native source hashes match the current application and harness.

The reusable journey is `tools/run_webui_integration.py --browser chrome|edge
--browser-scope governed-moves --fixed-fixture`, run with the API virtual environment.
Recorded runs used the retained wrappers to select existing cached native drivers.
No browser settings, persistent application database or local stack were changed.
This is focused local verification; no full-suite, CI or new timing-benchmark claim
is made. Branch and HEAD are unchanged; nothing was staged, committed or pushed.

Both catalogues remain byte-identical to their starting hashes: no keys, wording,
parameters, ordering or provenance changed. Existing approved resource labels are
reused; no export was promoted, no persistent database translations were touched,
and no new draft review is required. No new cache, request or catalogue parsing is
introduced on the application render path.

## Development attempts

The first new assertions compared text without accounting for existing Unicode
bidirectional isolation. Corrected assertions ignore those non-visible delimiters.
Against the captured pre-fix module, the corrected tests reproduce six failures
(two Arabic titles and four nonzero count cases), while English titles and zero
counts pass. All ten then pass with the fix.

The first native attempts stopped on an incorrect test-helper import before
exercising Move. Correcting `clean` to the existing `plain` helper required no
application change. Both disposable databases were removed before the final runs.

An attempted direct import of the API artifact-test module stopped because the
isolated environment intentionally had no database URL. The existing pure
validation function was then loaded without API imports or database fixtures and
passed. Failed/development attempts remain separate from acceptance evidence.
