# Phase 6P — Governance custody

**Status: complete for the approved local scope.** Changes remain local and
uncommitted on `refactor-API-python-file`, HEAD `839b770`. Chrome and Edge are
covered; Firefox, Safari and CI remain deferred.

`governance_custody.py` owns the existing report, status explanations, both pagers
and Settings/organization links. Its refresh token is private to each client;
report and pager state remain private to each rendering. Principal, navigation
and Settings access use explicit callbacks. No new cache was introduced.

Source reconstruction confirms all 424 lines of the moved function and all other
103 host functions retain their behavior. All pre-existing feature files and
translation artifact bytes remain unchanged.

## Requirement → verification

| Existing behavior | Passing evidence |
| --- | --- |
| Healthy, warning and critical reports; empty guidance | Original/extracted interaction checks; English/Arabic browser scenes |
| Unauthorized or signed-out access | Interaction checks and real-API denial/navigation checks |
| Ignore responses after navigation, identity change or a newer refresh | Three original/extracted interaction cases |
| Keep the visible report during refresh or refresh failure | Original/extracted interaction checks |
| Five-row custody and attention paging | Interaction and native Chrome/Edge journeys |
| Settings disposition tab, user and role destinations and return | Interaction, real-API and browser journeys |
| Keyboard focus, existing URL/history behavior and request bounds | Paired English/Arabic Chrome/Edge journeys |
| Shared consumers and other screens | Full unit, interaction and assembled suites |

## Results and observations

- **1,624 unit, 370 interaction and 68 assembled tests passed.**
- All 11 focused interaction cases passed against the original and extracted
  implementation. Both new real-API baseline cases passed before extraction.
- Each browser passed five groups and 18 scenes before and after extraction.
  **All 36 paired scenes match exactly below the animated 72px header.**
  Focus, URL/history and request counters match. Only existing message
  catch-up/unread polling is excluded from request counters.
- Test preparation corrected fixtures to respect existing active-user assignment
  and protected-role rules. A focus assertion was corrected to recognize the
  existing icon prefix. Application behavior and validation were unchanged.
- An old hold test depended accidentally on custody pager source. It now checks
  the actual hold action row; the original custody pager assertion is retained
  against its new module. Both assertions pass.
- The aggregation test that timed out once in 6O passes in the full assembled run.
  The 6O observation remains recorded for Phase 7, without a claimed product fix.
- Catalogue, Arabic terminology, configuration ownership, API-template consistency
  and all 24 runner-safety checks pass. No text or artifact keys changed.
- **All nine disposable databases were removed**, including test-development
  attempts, independently verified in PostgreSQL's catalogue.

[Acceptance and archived evidence](verification/webui-refactor-phase6p/acceptance.json)
record these results. No functionality, UI, UX, API, schema, public URL or history
change was made. No branch, commit or push was created. Phase 6Q follows under the
existing approval.
