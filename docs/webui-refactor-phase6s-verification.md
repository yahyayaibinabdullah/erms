# Phase 6S — Dashboard

**Status: complete for the approved local scope.** Changes remain uncommitted on
`refactor-API-python-file`. Chrome/Edge are covered; Firefox, Safari and CI remain deferred.

`dashboard.py` now owns the overview, personal lists, reminders and refresh logic.
`dashboard_state.py` owns the per-client snapshot, cache key and refresh token.
The existing identity/language/configuration cache policy and background refresh
are unchanged. Source reconstruction verifies the three moved functions, all 74
other host functions, initial state values and unchanged catalogue bytes.

## Requirement → verification

| Existing behavior | Passing evidence |
| --- | --- |
| Identity, language, same-user login revision and stale-response isolation | 26 original dashboard unit checks and four original/extracted interaction cases |
| Cached content remains visible, one background refresh, failure retains content | Interaction checks and held-response Chrome/Edge journeys |
| Record-count and favourite freshness after mutation | Original/extracted real-API assembled test |
| Favourite navigation, complete-list dialog and removal | English/Arabic browser journeys; API confirms removal |
| Keyboard focus, URLs, history and request counts | Identical paired Chrome/Edge results |
| Other callers and features | Full unit, interaction and assembled gates |

## Results and preserved observation

- **1,626 unit, 384 interaction and 72 assembled tests passed.**
- Chrome and Edge each passed five groups and eight scenes before and after.
  All **16 paired scenes match exactly below the animated 72px header**, without
  content/CSS masks. Focus and request counts match; only existing message
  catch-up/unread polling is excluded from request counters.
- Native browsers exposed an existing favourite-removal notification failure.
  Removal succeeds and the row disappears, then `remove_dashboard_favourite`
  calls `ui.notify` from the deleted row's slot and raises
  `RuntimeError: The parent element this slot belongs to has been deleted.`
  Both browsers reproduce the same two errors (English and Arabic) before and
  after extraction. The simulator's notification check does not expose it.
  This is explicitly recorded, preserved and excluded only by its exact function,
  error and count in the evidence gate. No product fix or general error exemption
  was introduced. Phase 7 should revisit it separately.
- Initial browser checks used an incorrect loading-button locator. The final
  driver checks the actual disabled attribute while holding the response.
  Source assertions were retargeted to the new owner; none were removed.
- Catalogue, Arabic terminology, configuration ownership, API-template and all
  24 runner-safety checks pass. No text, translation provenance or setting changed.
- All **10** disposable databases, including unsuccessful locator runs, were
  dropped. An independent PostgreSQL catalogue check confirmed their absence.

Evidence: [acceptance](verification/webui-refactor-phase6s/acceptance.json),
[source proof](verification/webui-refactor-phase6s/source-proof.json),
[notification observation](verification/webui-refactor-phase6s/favourite-notification-observation.json),
[cleanup](verification/webui-refactor-phase6s/database-cleanup.json).
