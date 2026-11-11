# Phase 6R — Advanced and saved search

**Status: complete for the approved local scope.** Changes remain local and
uncommitted on `refactor-API-python-file`, HEAD `839b770`. Chrome/Edge are covered;
Firefox, Safari and CI remain deferred.

`advanced_search.py` owns the builder, saved-query actions, sharing and unsaved
changes. `advanced_search_model.py` owns field definitions, grammar and validation.
`saved_search_audiences.py` owns bounded audience controls, and
`saved_search_administration.py` owns administration. `advanced_search_state.py`
creates the per-client workspace/revision/selection owner. Account cleanup and
navigation retain explicit callbacks. No cache or request policy changed.

Source reconstruction verifies all three moved controllers, nine model helpers,
five constant definitions and the other 77 host functions. Initial state values,
pre-existing feature files and catalogue bytes are unchanged.

## Requirement → verification

| Existing behavior | Passing evidence |
| --- | --- |
| Nested grammar, typed controls, effective retention and valid empty values | 82 original focused unit checks, ten original/extracted retention interaction cases, full unit gate |
| Bounded audience pages, selected values, eligibility and translated scope labels | Existing audience tests retained against the new owners; shared-query browser dialog |
| Save, execute, update and reasoned deletion | Original/extracted real-API assembled lifecycle |
| Administration permission denial, 25-row paging, selected edit identity and late-response/error handling | Five original/extracted interaction cases and actual viewer API denial |
| Unsaved guard, keep editing, discard and administered-query restoration | Existing callback tests and English/Arabic browser journeys |
| Identity isolation and stale callbacks | Existing session tests retained; independent state-owner test |
| Keyboard focus, existing URLs/history and request bounds | Paired Chrome/Edge journeys |
| Other features and shared callers | Full unit, interaction and assembled gates |

## Results and observations

- **1,626 unit, 384 interaction and 71 assembled tests passed.**
- All 15 focused interaction cases passed before and after extraction. Both new
  real-API cases passed against the original implementation.
- Both browsers passed five groups and 14 scenes before and after extraction.
  **27 of 28 paired scenes match exactly below the animated 72px header.** The
  remaining Chrome scene differs at ten rounded-border antialiasing pixels, by
  at most 3/255 per color channel. Both full images were reviewed: text, controls,
  geometry and content match. Focus, URL/history and request counters match.
  Only existing message catch-up/unread polling is excluded from request counters.
- Synthetic saved queries are inserted with fixed timestamps through the canonical
  schema, retaining triggers and `seeding` history. Test setup corrected a
  timestamp-update attempt that required a change reason, and scoped the Search
  locator to its submit row.
- A synthetic bare-condition saved definition exposed an original renderer
  limitation: reopening it raises `ValueError: Invalid value: contains_ci`.
  The browser fixture now uses the outer Boolean group produced by the UI.
  A separate check confirms the bare-condition failure is identical before and
  after extraction. It remains a pre-existing observation for later review;
  no product fix is included.
- Source tests now point to the new state/module owners; existing assertions were
  retained, including translation-style isolation from the search builder.
- Catalogue, Arabic terminology, configuration ownership, API templates and all
  24 runner-safety checks pass. No wording, artifact key or provenance changed.
- **All 12 disposable databases were removed**, independently checked against
  PostgreSQL's catalogue, including failed test-development attempts.

[Acceptance and archived evidence](verification/webui-refactor-phase6r/acceptance.json)
include the visual review and bare-condition observation. No functionality, UI,
UX, API, schema, public URL or history behavior changed. No branch, commit or push
was created. Phase 6S follows under the existing approval.
