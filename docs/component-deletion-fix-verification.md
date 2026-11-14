# Digital-component deletion — notification and refresh

**Status: fixed and locally verified on 11 November 2026.**
The user authorized this separate repair after the WebUI refactor. Earlier local
work is preserved on `refactor-API-python-file`; no branch, commit, history or
remote changes are made.

## Cause and correction

The delete callback first redraws the component cards optimistically. This removes
the clicked card and its NiceGUI event slot. When the API returns, the success
notification tries to find its client through that deleted slot and raises an
exception. The automatic refresh never runs. Error notifications after rollback
have the same context problem.

The callback now performs its API operation, feedback and refresh inside the
surviving component container, following the context pattern already used for
upload feedback. This supplies the correct client and language after the card is
removed. The existing versioned delete, optimistic removal, API-failure rollback,
bounded refresh and immediate-delete interaction are preserved. No confirmation
dialog, wording, layout, API, schema or cache changes are introduced.

## Requirement → verification

| Requirement | Verification |
| --- | --- |
| Notify successfully after the originating card is gone | New tests use the real NiceGUI notifier and release the deleted slot's parent; English/Arabic and inline/standalone contexts |
| Refresh remaining cards and totals automatically | Native tests assert the updated `1–1 / 1` pager after deletion, without reopening |
| Remove the last component cleanly | Real callback and native tests assert the empty state and disappearance of paging controls |
| Roll back a rejected deletion and report the error | Versioned `409` cases restore both cards and send negative feedback from the surviving context |
| Handle a failed refresh after successful deletion | Existing success feedback followed by negative refresh feedback; deleted card stays removed |
| Preserve nearby component operations | Existing permission, closure, physical-record, upload, ordering, viewer, keyboard focus, close and page-restoration checks |
| Persist the correct deletion | Native API totals and repeated record entry; one DELETE request per tested click |

## Verification

- **27 component interaction tests passed**, including 16 new context-sensitive
  cases spanning both languages, inline/standalone presentation, successful and
  rejected deletes, failed refreshes and deletion of the last component.
- **170 related unit tests passed** for entity contracts, module boundaries and
  staged component previews. Total: **197 focused tests**.
- The corrected pre-fix regression reproduced the deleted-slot exception in all
  16 new cases. The existing notification test substitute had bypassed NiceGUI's
  slot/client lookup, which explains why older interaction cases passed.
- Configuration authority, API template consistency, catalogue references,
  approved Arabic terminology and the existing pure artifact validator passed.
- **Chrome 157.0.8103.40 and Edge 157.0.4341.46 passed** all seven groups each,
  covering English/LTR and Arabic/RTL. Each browser completed four successful
  deletions and retained 16 screenshots. The translated success notifications,
  authoritative remaining count, automatic empty-state refresh and repeated
  record entry all passed, along with upload, reorder and viewer checks.
- Neither final run recorded browser errors, unsuccessful API requests or the
  deleted-slot exception. Visual review confirmed the refreshed remaining-card
  and empty-state presentation in both browsers and directions.
- All **three disposable databases** were removed, including the initial Edge
  version-guard attempt. An independent PostgreSQL catalogue query confirmed none
  remain; no owned browser-test processes or native drivers remain.

Evidence: [acceptance record](verification/component-deletion-fix/acceptance.json),
[Chrome results](verification/component-deletion-fix/chrome/browser-results.json),
[Edge results](verification/component-deletion-fix/edge-final/browser-results.json),
and [cleanup audit](verification/component-deletion-fix/database-cleanup.json).
Raw logs, screenshots, test XML, source hashes and unsuccessful development
attempts are retained alongside them. Final source hashes match the application
and harness. The sole application file changed by this follow-up is
`frontend/webui/components.py`.

The reusable native check is the existing `components` scope of
`tools/run_webui_integration.py`, invoked through the API virtual environment with
`--browser chrome` or `--browser edge`. The recorded runs used the retained wrappers
to select existing cached drivers. Branch and HEAD remain unchanged; nothing was
staged, committed or pushed.

The maintained `components` browser scope replaces its previous expectation of
the known error with notification and refresh assertions. The Phase 6L report
remains historical evidence of the original defect. This is focused local
verification, not a new full-suite, CI or timing-benchmark certification.

Both translation catalogues remain unchanged: no keys, wording, parameters,
ordering or provenance are modified. No administrator export is promoted or
persistent database translations touched, and no new draft review is required.
The application adds no requests or cache; it allows the existing bounded refresh
to run after the successful notification.

## Test-development note

The first new harness attempt awaited NiceGUI's synchronous event wrapper and
failed with `TypeError`. The corrected harness captures the actual removal
callback passed to the real card renderer and awaits it in the originating card's
slot, while invoking the real notification function. This reproduces the native
failure without changing application code. Both development evidence and the
corrected failing-before result are retained separately from passing acceptance.

The initial Edge attempt stopped at the test's version guard before its journeys:
the installed browser reported `157.0.4341.46`, while the prior snapshot expected
`157.0.4341.42`. The installed application metadata confirmed `.46`; the rerun uses
that version and its already-cached matching driver. No browser or driver was
installed, updated or reconfigured by this task. The initial attempt's database
was removed and its evidence retained.
