# Phase 6U — Messaging and notifications

**Status: complete for the approved local scope.** All Phase 6 sub-phases are now
complete. Work remains local and uncommitted on `refactor-API-python-file`.
Phases 7 and 8 have not started. Firefox, Safari and CI remain deferred.

`messaging_controller.py` owns mailbox, monitor, notification-administration,
resource and capture navigation. `message_stream.py` owns unread controls,
notifications and the dedicated live API client's lifecycle. Their separate
per-client state factories preserve the existing defaults and cleanup. The
existing workspace, monitor, notification, live adapter and session implementations
remain unchanged. No cache, public URL or browser-history behavior was added.

Source reconstruction verifies all six moved functions and 67 other host functions.
The existing runtime changes are confined to host wiring; catalogue bytes and
initial state values, including the live-client dictionary, are unchanged.

## Requirement → verification

| Existing behavior | Passing evidence |
| --- | --- |
| Inbox/outbox/draft dispatch and restricted administration | Original/extracted controller interaction cases |
| Record, aggregation, component, audit and disposition links | Controller cases, existing monitor-navigation cases and full assembled suite |
| Capture opening/abandonment and preview/editor handoff | Retargeted capture-preparation cases; existing record/capture gates |
| Compose, recipient validation, saved draft and send | Original/extracted real-root and real-API journey |
| Existing protection against deleting uncaptured/unexpired messages | Real-API outbox assertion; no weakening of the retention rule |
| Draft delete/restore and post-write freshness | English/Arabic Chrome and Edge journeys |
| Deleted mailbox message restoration, attachments/resource selectors, failed eligibility and recipient search | Existing messaging Phase 5/workspace interaction suites retained |
| Unread/toast isolation, notification cap, replacement stream, disconnect and client cleanup | 11 original/extracted owner cases plus eight existing live-adapter unit cases covering reconciliation/reconnect/cursors |
| Notification administration and monitor | Native destinations plus existing permissions/editing/abandonment tests |
| Focus, repeated navigation, language/direction, root URL/history and bounded requests | Paired Chrome/Edge evidence and full regression gates |

## Results

- **1,628 unit, 420 interaction and 74 assembled tests passed**, with no failures,
  errors or skips in these final gates.
- The original baseline passed 23 new controller/stream cases, eight live unit
  cases and the real-API compose/draft/send journey. After extraction, 34 focused
  cases include those 23 plus capture and monitor wiring checks.
- Chrome and Edge each passed five groups and ten scenes before and after.
  **16 of 20 paired scenes match exactly below the animated 72px header.**
  The remaining four differ only in digits of the monitor's live health-report
  timestamp. Full images were inspected; exact difference rectangles are recorded.
  No screenshot content or CSS was masked. No browser/server traceback occurred.
- Focus and request counts match. The comparison bijectively maps the two newly
  created synthetic draft UUIDs in each run; it preserves all methods, routes,
  query parameters, status codes, identity counts and request counts. Only the
  existing catch-up/unread polling is excluded. Raw requests remain available.
- Initial test development exposed two fixture assumptions: the officer fixture
  lacked message-exchange permission, and new uncaptured messages cannot be
  deleted. A temporary disposable-only assignment supplies an eligible recipient
  and is removed in `finally`; the test now asserts the existing deletion gate.
  Draft delete/restore and existing mailbox-restore tests provide that coverage.
- The earlier disposition-footer test observation recurred with the save still
  busy. Its helper returned after a fixed 20ms despite NiceGUI scheduling the
  action in the background. A controlled 50ms fixture response reproduced the
  failure in both languages. The helper now awaits that exact scheduled action
  with a bounded timeout. All 20 footer cases and the final full unit suite pass.
  This corrects a test race, not application behavior; raw failing evidence remains.
- Configuration ownership, API templates, catalogue references, Arabic terminology
  and all 24 runner-safety checks pass. No setting, wording, translation provenance
  or operator action changed. `git diff --check` passes.
- All **eight** uniquely named disposable databases were dropped, including test
  development failures. An independent PostgreSQL catalogue audit confirms absence.

Evidence: [acceptance](verification/webui-refactor-phase6u/acceptance.json),
[source proof](verification/webui-refactor-phase6u/source-proof.json),
[visual review](verification/webui-refactor-phase6u/visual-review.json),
[footer diagnosis](verification/webui-refactor-phase6u/footer-observation.json),
[cleanup](verification/webui-refactor-phase6u/database-cleanup.json).
