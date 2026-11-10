# Refactor browser acceptance checklist

Use `tools/run_webui_integration.py --preview --fixed-fixture` from the repository root, with
the API virtualenv. Use only its printed loopback URL and disposable identities.
Record `lifecycle.json`, source revision, browser product/version, OS, viewport,
zoom, device scale, language, identity and exact fixture before each run. Stop
with Ctrl-C and verify database cleanup. Never use the development stack.

Run the remaining Phase 2 checks in actual Chrome and Edge. The user deferred
Firefox and Safari on 10 November 2026; preserve their partial evidence without
reporting a pass. Engine substitutes and NiceGUI's simulated User are supplemental
evidence only. Keep failures and untested rows visible. Do not automatically
accept new screenshots.

The automated journey runs through `tools/run_webui_integration.py --browser
chrome --maildev` (or `--browser edge`) using the API virtualenv and a running
repository-managed MailDev instance. It creates and removes its own disposable
database and records screenshots, API observations and per-check results. See
the WebUI README for setup. The concurrent conflict uses a separate API session;
it is not a second browser window. Review the visual evidence separately.

## Settings pilot

1. Sign in as the administrator. Open Settings from the drawer. Check its
   heading, all seven category tabs, fields, help text, selection lists, reason
   field and actions against the existing page. Capture General and Disposition.
2. Change Review warning window. Save without a reason: the existing warning
   must appear, the draft must remain, and no write must occur. Enter a reason,
   save once, and verify the saved value after leaving, returning and reloading.
3. Open Settings in a second session and save a different value. Save the older
   first-session draft: retain its text/reason and show the existing conflict.
   Refresh explicitly and verify the current saved value.
4. Exercise the Disposition scheme-first lookup, two-character remote searches,
   selected-value retention, branch paging, browse dialog, clear and cancel.
   Confirm the existing destination validation and atomic save.
5. Check Email password replacement/clear and the test-email dialog's cancel,
   required recipient and busy state. Use the repository MailDev workflow for
   an actual send; never send to an outside address or disable TLS validation.
6. Enter Settings from each existing caller: drawer, saved navigation on reload,
   a Settings audit event, and the governance-custody warning. Check the selected
   category/setting and retained breadcrumb state.
7. Navigate away during a delayed read, then resolve it. The old result must not
   replace the new view. Verify bounded requests, no duplicate saves, and data
   freshness. Record request counts and descriptive timings; avoid machine-speed
   thresholds. Existing fake-API tests cover controlled failures/delays too.
8. Sign out and sign in as the restricted viewer. Settings must disappear and
   the previous identity's content and drafts must not reappear.

## Navigation, visual and browser checks

- Repeat Settings → Dashboard → Settings, category changes, breadcrumb returns,
  reload and sign-out. Preserve the root URL and current browser history. Check
  Back/Forward with a preceding disposable local page: do not introduce a new
  history entry, exit trap, or disabled browser control.
- Check `/?q=...` with the existing enabled-search fixture, and the existing
  unsaved-change confirmation in a workflow that already has it. Do not add a
  new Settings navigation prompt for the purpose of this test.
- Use Tab/Shift-Tab, arrows, Enter and Escape. Check focus after dialogs, failed
  validation, category changes and return navigation. Compare loading, empty,
  restricted, error and dialog states.
- Repeat in English/LTR and Arabic/RTL through the ordinary Preferences UI.
  Keep data, trail, viewport, zoom, fonts and completion state identical for
  before/after screenshots. Native full-window screenshots with uncontrolled
  browser chrome are observations, not pixel-test goldens.
- Review console errors and failed requests for every browser. Correlate with
  owned API/WebUI logs. Explain expected failures such as permission denials;
  a visible heading alone does not establish a passing workflow.
- Check the separately approved B1 fix: open a record's parent aggregation,
  reload, and verify that the existing content panel remains visible. Repeat
  in Arabic. Keep the original Phase 1 failure evidence.

Record each result as pass, fail or not run, with its evidence path. The local
Phase 2 baseline is now complete for the approved Chrome/Edge scope: 44 workflow
checks plus 12 supplemental keyboard/focus groups per browser, in English and
Arabic. The latter use `--browser-scope keyboard` without MailDev; native key
actions, focus observations and original screenshots were reviewed together.
Existing page-level focus and dialog-boundary differences are recorded, not
silently changed. Firefox/Safari and CI remain explicitly deferred. See the
[verification report](../../../../docs/webui-refactor-phase2-verification.md).
