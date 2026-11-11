# WebUI refactor: Phase 6F — Login-session administration

**Status:** Complete for the approved local scope.

## Scope and ownership

`login_sessions.py` owns the existing session list, filters, bounded paging,
session cards and single/all-user revocation confirmations. The root supplies
shell entry, a current-principal reader and the original current-session cleanup
callback. No shared application-state dictionary enters the module.

Each opening retains its own offset, total, active count and loading flag. No
cache, route, timer, request or navigation behavior is added. The session panel
inside User Details remains part of the organization workspace in 6G.

## Requirement-to-verification map

| Preserved behavior and callers | Evidence |
| --- | --- |
| Drawer entry and navigation restoration; optional user-specific list | Full assembled drawer checks; original/extracted entry tests; Chrome/Edge Settings return and unchanged URL/history |
| Query, status, dates, sorting, 20/50/100 paging, shrinking pages and empty results | Exact original function reconstruction; interaction request assertions and shrink/error cases; browser server paging and empty results |
| Active/revoked/expired states and administrative action visibility | Original/extracted parameterized privilege/status tests |
| Cancel, single-session and all-user revocation; failed writes | Original/extracted confirmation, cancel, 403, refresh and cleanup cases; real-API single-session revocation |
| Current-session sign-out and identity/token cleanup | Original/extracted single/all-user cases; assembled real-API current-session revocation |
| English/Arabic layout, focus and existing navigation | Original/extracted Chrome and Edge journeys and screenshot/focus comparisons |
| Remaining feature consumers | Full unit, interaction and assembled suites; 115 other direct host functions unchanged |

## Verification

| Check | Result |
| --- | --- |
| Added original / extracted focused interaction checks | 12 / 12 passed |
| Added assembled checks against original | 2 passed |
| Full final unit suite | 1,603 passed |
| Full final interaction suite | 255 passed |
| Full final assembled suite | 51 passed |
| Chrome and Edge, original and extracted | Each passed 6 groups in English/Arabic; 8 scenes per browser |
| Browser comparisons | Focus and application request counts identical; 13 of 16 scenes pixel-identical below the animated header; remaining differences are insertion carets |
| Source preservation | Complete original session function reconstructed exactly by inlining two host callbacks and the principal reader; styling/message literals unchanged |
| Translation/configuration checks | 4,071 translation keys/artifact bytes unchanged; active references and terminology pass; configuration authority and API templates agree |
| Runner safety | 23 passed |
| Disposable databases | All 6 unique databases dropped; independent catalogue audit confirms none remain |

Screenshot comparison excludes only the animated header's top 72 pixels. Each
remaining difference occupies a single 1×24-pixel blinking caret in the focused
query input. No unexplained layout difference remains. Request comparison excludes
only background message catch-up/unread-count polling.

The existing Boolean `icon-right` pagination defect is retained: exactly two
`TypeError: u.match is not a function` events per session-list construction. Other
browser errors fail the checks. No product defect was fixed.

## Test corrections and limits

Source assertions in the entity/layout and legal-hold suites now also inspect the
new owner; their assertions were retained. The first full interaction run exposed
a runner setup defect: NiceGUI storage had a missing parent directory. The runner
now creates each suite's isolated parent, and its safety test checks that setup.
An intermediate direct unit invocation omitted the required asyncio option; its
58 asynchronous-test failures were invocation errors. Final acceptance uses the
standard runner with that option and with network access blocked.

Evidence: `docs/verification/webui-refactor-phase6f/`; original snapshot and raw
intermediate failures: `.runtime/webui-refactor-phase6f/`.
Firefox, Safari and CI remain deferred. No translation or operator action is
required. All changes remain local and uncommitted on `refactor-API-python-file`.
