# Saved-search reopening — standalone conditions

**Status: fixed and locally verified in Chrome and Edge, English and Arabic.**
The user authorized this separate repair after the WebUI refactor. Work remains
local and uncommitted on `refactor-API-python-file`, preserving earlier changes.

## Cause and correction

Canonical saved-search expressions may contain a single structured or full-text
condition. The visual builder expects an outer Boolean group. Loading a bare
structured condition passed its operator, such as `contains_ci`, to the group
selector, causing `ValueError`. A bare full-text condition also lacked the
builder's outer group and did not render its condition properly.

The saved-definition loader now wraps a standalone condition in a one-child
**All/AND** group before constructing controls. This preserves its meaning and
uses the existing builder presentation. Existing AND/OR/NOT groups are unchanged,
including a valid five-level expression.

Opening does not modify the stored saved search. An unchanged query still executes
through the saved-search endpoint using the original stored definition. Explicitly
saving an edited standalone condition stores its equivalent one-child AND form.
The loader establishes the clean baseline after building controls, so opening
alone does not cause an unsaved-changes prompt.

No query operators, fields, privileges, API grammar, URLs, wording or translations
are added. The fix introduces no cache or extra request. The sole application file
changed by this follow-up is `frontend/webui/advanced_search.py`.

## Requirement → verification

| Requirement | Verification |
| --- | --- |
| Reopen valid standalone conditions | Actual workspace factory tests for text, Boolean, null-check and full-text roots; both resource types and languages |
| Preserve existing grouped criteria | AND, OR, NOT and five-level cases compile back to their original expressions |
| Keep opening read-only and clean | Stored definition equality, no update call, clean navigation guard and saved-endpoint execution assertions |
| Preserve editing and persistence | Versioned updates, clean baseline after saving, and reopened edited criteria |
| Keep native results equivalent | Compare displayed IDs with real saved-search API results before and after editing |
| Preserve nearby UX | Existing grouped-search, sharing, keyboard focus, unsaved-change guard and administration journeys |

## Verification

Acceptance date: **12 November 2026**.

- **37 interaction tests passed**: 32 new workspace cases and five existing
  saved-search administration cases.
- **63 related unit tests passed** for query grammar, dirty-state handling,
  localization, error handling and feature boundaries. Total: **100 focused tests**.
- Before the fix, the corrected regression had 16 passing grouped cases and 16
  failing standalone cases. The 12 structured-condition page exceptions are also
  reported at teardown; these are the same failures, not extra test cases.
- **Chrome 157.0.8103.40 and Edge 157.0.4341.46 passed**, each with nine check
  groups and 22 screenshots. Each covers both resource types and languages:
  opening, clean navigation away/back, execution, editing, saving and reopening.
  Eight successful versioned updates were verified across the two final runs.
- Native English and Arabic captures were inspected. Existing grouped-query,
  sharing, administration, unsaved-change and keyboard-focus journeys also pass.
  The final runs have no unexpected browser errors or unsuccessful API requests.
- All 186 recorded source hashes per final browser run match the current source;
  screenshot hashes and the new regression-test sources are recorded.
- Catalogue coverage, Arabic terminology, artifact ordering/placeholders/provenance
  and unchanged catalogue hashes pass. Configuration authority and API template
  consistency checks pass; `git diff --check` passes.
- All **three** uniquely named disposable PostgreSQL databases, including the
  first Chrome attempt, were initialized through the canonical runner and dropped.
  An independent catalogue query confirms removal; no test processes or native
  drivers remain. No persistent database was used for these tests.

The first Chrome native attempt passed the grouped journeys in both languages
and standalone conditions in English, then timed out waiting for the saved-search
picker to close at the first Arabic standalone query. The captured screen still
shows that picker, with no browser error or server exception. The cause is
unproven; the evidence is retained in `chrome-first-attempt`. A fresh disposable
run passed all nine groups with native-click observations, without retrying
clicks or changing the application. The timeout did not recur in that run.
The original timeout remains an observation, not a separately diagnosed or fixed
product defect.

This is focused local verification, not a new full-suite, CI or timing benchmark.
The reusable browser journey is the `advanced-search` scope of
`tools/run_webui_integration.py`, run with the API virtual environment and
`--browser chrome` or `--browser edge`.

Both existing catalogues are reused without changing keys, wording, placeholders,
ordering or provenance. No administrator export or persistent database translation
is modified, and no new translation review is required.

## Test-development note

The first new test used a finder that requires an element to exist while asserting
that no dialog existed. The corrected assertion checks the client's element
inventory. The corrected pre-fix result and the initial development attempt are
retained separately from passing acceptance. No application change was needed for
that test correction.

## Retained evidence

- [Acceptance and source identity](verification/saved-search-reopen-fix/acceptance.json)
- [Chrome final results](verification/saved-search-reopen-fix/chrome/browser-results.json)
  and [Edge final results](verification/saved-search-reopen-fix/edge/browser-results.json)
- [Focused interaction results](verification/saved-search-reopen-fix/interaction/tests.xml)
  and [unit results](verification/saved-search-reopen-fix/unit/tests.xml)
- [Corrected pre-fix failures](verification/saved-search-reopen-fix/before-corrected/tests.xml)
  and [first Chrome attempt](verification/saved-search-reopen-fix/chrome-first-attempt/browser-results.json)
- [Validation](verification/saved-search-reopen-fix/validation.json),
  [database cleanup](verification/saved-search-reopen-fix/database-cleanup.json),
  [process cleanup](verification/saved-search-reopen-fix/process-cleanup.json)
  and [file hashes](verification/saved-search-reopen-fix/manifest.sha256)

All changes remain local and uncommitted on the user's existing branch. No branch,
worktree, commit, history, remote or system-setting changes were made.
