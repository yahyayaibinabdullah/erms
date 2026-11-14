# Phase 6J — translation administration and Inspector

**Status: complete for the approved local scope.** All changes remain local and uncommitted.
Chrome and Edge are the approved browser scope; Firefox, Safari and CI are deferred.

## Ownership and preservation

`translation_administration.py` owns the existing language cards, filters, grouped
paging, editor, draft/publication actions, import/export dialogs, scroll restoration
and latest-response guards. Its three persistent language/paging/expanded-context
fields now belong to a per-client closure, with the same lifetime as before. It
receives a current-page reader and a narrow entry callback, not the host state.

`translation_inspector.py` owns optional asset loading, privileged metadata,
toggle/restore, persistent brand refresh, inspect-and-open navigation and session
cleanup. Assembly supplies the existing UI elements and deferred destination
callbacks. Account profile refresh and session cleanup retain their ordering.

Source reconstruction matches all seven moved functions to their original syntax
trees. The other 98 direct host functions are identical. Inspector JavaScript and
both translation artifacts remain byte-identical. There are no new routes, history
rules, UI strings, caches, API contracts or database changes.

## Requirement → implementation → evidence

| Existing behavior | Owner | Verification |
| --- | --- | --- |
| Filters, grouped paging, language selection and stale-response rejection | Translation administration | Existing English/Arabic source-filter interaction tests; original/after browser journeys |
| Required text/reason, draft/publish version and provenance, failures and refresh | Translation administration editor | New interaction cases; real-API draft and publish journey |
| Bulk preview, invalid/empty gates and reason-bound confirmed write | Translation administration bulk dialog | New original/after interaction cases |
| Export preview, reviewed-draft selection, complete/incomplete download gate | Translation administration export dialog | New interaction cases; real-API preview; original/after browser captures |
| Artifact parsing, preview, reason gate and confirmed import | Translation administration import dialog | New interaction cases and complete Arabic artifact import through the original/after UI into disposable data |
| Language creation validation and error handling | Translation administration language dialog | New interaction cases; original/after dialog capture and cancellation |
| Inspector privilege, lazy-load order/retry, state restore and failures | Inspector controller | Ten new original/after behavior cases; retained source/JavaScript contract checks |
| Inspect/open, keyboard focus, menu toggle and cleanup | Inspector controller and explicit host callbacks | Original/after Chrome/Edge journeys; cleanup/guard behavior tests; assembled account/session regression |
| Wording and curated provenance | Unchanged catalogues | Byte hashes, active-key/source references and approved terminology checks |

## Baseline observations and test corrections

- NiceGUI's simulated user substitutes its own download handler. The new download
  spy was attached to that handler so the assertion observes the actual callback.
- The real-API test now waits for the single filtered edit button, rather than
  confusing initial unfiltered rows with a finished filter response. Icon-only
  controls are selected by their icon, not text they do not display.
- One initial Chrome session disconnected before completing its first translation
  check. Its raw failure and cleanup evidence are retained; later runs are reported
  separately.
- An original Inspector journey timed out after clicking Open administration. A
  subsequent diagnostic run passed both languages. Menu-show refresh restores the
  Inspector asynchronously, so the final harness observes that existing restore
  before interacting with the toggle. This only instruments the test session;
  application code and Inspector JavaScript are unchanged.

- Full-suite checks exposed earlier test readiness gaps: classification Edit
  was clicked before refreshed controls appeared; an indexer assertion began its
  own API read before the detail screen's final navigation registration. The ACL test
  also mistook an old Access control for the refreshed page; it now waits for the
  new control identity. These
  tests now wait for the relevant detail control. Application behavior is unchanged;
  each corrected test is checked against the original host before acceptance.
- Slow character-by-character browser typing could cross the existing debounce
  interval, causing intermediate filter requests. The final harness uses one
  native typing operation and focuses the same heading before list captures.
  Dialog keyboard-focus assertions remain independent and unchanged.

## Final verification

- **1,613 unit tests, 312 interaction tests and 59 assembled tests passed.**
- Before extraction: 20 focused interaction tests, 10 Inspector behavior tests and
  two real-API translation workflows passed. The three existing test-readiness
  corrections also passed separately against the original host.
- Chrome and Edge each passed 11 groups and captured 12 English/Arabic scenes,
  before and after extraction. Focus and request counters match exactly, excluding
  only the existing periodic unread/catch-up polling from request comparison.
  All translation list requests retain the 10-context-group page bound.
- Below the animated header, 23 of 24 paired scenes are pixel-identical. The only
  exception is 12 antialiasing pixels at the rounded corners of the Arabic editor's
  change-reason field in Chrome, differing by 3/255 per channel. Raw images were
  inspected; no screenshot masks or UI style changes were used.
- Configuration ownership (122 settings), API templates (36 settings), catalogue
  references, Arabic terminology and 24 runner-safety tests passed. All 4,071
  English/Arabic keys and both artifact files remain unchanged; prior placeholder,
  provenance and artifact validation therefore remain applicable.
- **All 22 uniquely named disposable databases were removed**, confirmed both by
  each runner and an independent PostgreSQL catalogue audit.

[Acceptance totals and archived evidence](verification/webui-refactor-phase6j/acceptance.json)
include the source reconstruction, XML results, browser screenshots/comparisons and
cleanup audit. Initial failures remain in the local `.runtime/webui-refactor-phase6j`
evidence; their causes and test corrections are described above. No product defect
was changed. Git history, branch and remote remain untouched.
