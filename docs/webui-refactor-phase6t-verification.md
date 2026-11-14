# Phase 6T — Disposition

**Status: complete for the approved local scope.** Changes remain local and
uncommitted on `refactor-API-python-file`. Firefox, Safari and CI remain deferred.

The existing disposition package now owns its host controller. Per-client saved
views and page tokens belong to `disposition_state.py`. Explicit callbacks retain
resource selection, preview, dirty-navigation guards and job/task destinations.
Existing eligibility, review, completion, templates, artifacts and recovery
implementations are unchanged. Source reconstruction verifies the moved function,
73 other host functions, state defaults and unchanged catalogue bytes.

## Requirement → verification

| Existing behavior | Evidence |
| --- | --- |
| Dispatch, permissions, saved job/task IDs and dirty-navigation guards | 13 original and extracted controller interaction cases |
| Abandoned requests, identity changes, replacement page tokens and errors | Controller interaction cases |
| Real proposal/job creation and task/job return paths | Original real-API journey and full assembled suite |
| Approval, physical/external completion, artifacts, recovery and failures | 277 unique backend lifecycle cases; 886 original disposition unit cases |
| Filters, bounded owner/preparer controls, templates and settings returns | English/Arabic Chrome and Edge journeys |
| Focus, URLs, browser history, request counts and other consumers | Paired native evidence and full WebUI gates |

## Results and observations

- **1,626 unit, 397 interaction and 73 assembled tests passed.**
- **277 unique backend lifecycle cases are covered:** 241 unaffected cases from
  the initial run plus the corrected 15-test integrated and 21-test artifact
  suites. The original 11 failures and an explicit case-by-case coverage mapping
  are retained; they are not rewritten as a clean initial run.
- The Phase 1 preview fixture B2 omitted required reviewer designations. Its
  original failure was reproduced, then the fixture was corrected using existing
  roles and rules. The disposable preview now creates 28 jobs and 133 aggregations.
- Integrated tests incorrectly expected certificate generation to finish a
  digital job automatically. The approved destruction specification requires
  explicit task completion. Tests now perform that existing action and separately
  request optional email. One queued-review fixture also lacked its required unit
  manager. Only tests/fixtures changed; API behavior and schema did not.
- The first full unit run had one footer retry failure in an unchanged module.
  The complete 18-test footer suite, five independent English/Arabic retry pairs,
  and the repeated full 1,626-test suite passed. Diagnostic assertions remain.
  Its cause is unknown; Phase 7 should revisit this test-stability observation.
- An Edge test clicked Create while a filter panel was collapsing. Its click log
  identifies the page container as the target. The driver now waits for that
  existing animation to finish; no UI timing or application code was changed.
- Chrome and Edge each passed five groups and 12 scenes before and after.
  All **24 paired scenes match exactly below the animated 72px header**, without
  content/CSS masks. Focus and request counts match; existing message polling is
  excluded from request counters. No browser or server traceback remains in these journeys.
- Catalogue, Arabic terminology, configuration, API templates and all 24 runner
  safety checks pass. No wording, provenance, settings or operator action changed.
- All **31** uniquely named disposable databases were dropped, including failed
  development runs. An independent PostgreSQL catalogue audit confirmed removal.

Evidence: [acceptance](verification/webui-refactor-phase6t/acceptance.json),
[source proof](verification/webui-refactor-phase6t/source-proof.json),
[backend coverage](verification/webui-refactor-phase6t/backend-coverage.json),
[footer observation](verification/webui-refactor-phase6t/footer-observation.json),
[cleanup](verification/webui-refactor-phase6t/database-cleanup.json).

Later diagnosis: [6U](webui-refactor-phase6u-verification.md) reproduced the footer
observation as a fixed-wait test race and corrected the helper. The original 6T
failure and reruns remain unchanged in this historical report.
