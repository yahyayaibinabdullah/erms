# WebUI refactor: Phase 5 verification

**Status:** Complete for the approved local scope, with the non-reproduced Edge timeout noted below.  
**Starting revision:** `541aad12e66b666f79b7009be13e90ecf369fb01`  
**Authorization:** User requested Phase 5 on 10 November 2026 and subsequently explicitly approved completion with the initial, non-reproduced Edge loading problem recorded.

All work remains local and uncommitted on `refactor-API-python-file`. No branches,
worktrees, commits, history changes, pushes or pull requests were made. Chrome
and Edge are the approved local browser scope. Firefox, Safari and CI remain
deferred; no Safari setting was touched.

## Scope and boundaries

This phase separates shared interfaces while preserving the single-page
application. It adds no routes, URLs, history entries, workflows, permissions,
UI text or visual changes. Browser Back/Forward retains its existing behavior,
including the ability to leave for a previously visited website.

| Step | Implementation | Evidence |
| --- | --- | --- |
| 5A Navigation data | Existing identity, duplicate handling, trail limit and visible-index helpers moved to `navigation_data.py` | 15 focused cases passed before movement; 1,509 unit and 209 interaction cases after; helper ASTs unchanged |
| 5B Shell presentation | Header, footer, drawer and content builders in `application_shell.py`; original controls returned as explicit handles | 1,523 unit, 209 interaction, 42 assembled; 11 shell checks / 19 images and 12 keyboard groups / 58 observations per browser; all four construction AST comparisons match |
| 5C Navigation coordination | `navigation_controller.py` owns trail, persistence calls, registration, breadcrumb restoration/fallback, in-app Back and existing discard guards | 20 baseline cases before movement; 1,537 unit, 209 interaction, 42 assembled and 18 navigation checks per browser after |
| 5D Session lifecycle | `session_context.py` supplies per-page API/identity/locale access and coordinates sign-in, sign-out and unauthorized cleanup through explicit owner callbacks | Eight lifecycle baseline cases before movement; 35 direct lifecycle/dashboard cases after; 43 assembled and six session checks per browser before and after |

Each production step waited for the preceding step's acceptance. Later-step test
preparation ran independently against the existing behavior before that code moved.
The final acceptance set passes. The user explicitly accepted completion with the
initial, non-reproduced Edge timeout documented below; its cause remains unresolved.

Feature snapshots, dispatch, localized breadcrumb rendering, styling, password and
localization bootstrap, private feature caches and live-message connections retain
their existing host callbacks. Those will move with their owners in later phases.
The session identity mapping and control aliases are temporary host adapters;
features receive explicit readers and callbacks, not the large application state.
The new modules do not import `app.py`, create independent caches, or duplicate
feature logic. Phase 6 has not started.

## Behavior and isolation evidence

The navigation baseline covers invalid indices, cancelled guards, registration
order, consecutive visits, saved state, trail truncation, restoration flags,
403/404 fallback, other errors and synchronous/asynchronous Back fallbacks.
Assembled tests exercise actual forbidden/missing breadcrumb targets, with only
those target responses controlled; all other requests use the real API. Existing
real-browser journeys cover restored search URLs, saved-search discard prompts,
category restoration, record-to-aggregation navigation and browser exit behavior.
All main drawer destinations remain covered by the assembled suite.

Session checks cover cleanup before a delayed or failing logout, invalid sessions
without a storage request context, password restrictions before ordinary workspace
reads and language rebuilds without extra dashboard loading. Browser checks use
two independent drivers simultaneously: an Arabic administrator and an English
restricted user. Reconnect retains the current page and restarts unread reconciliation.
A held request from the old identity returns its expected 401 after another identity
signs in; it cannot restore the old screen or affect the other driver. Existing API
unit tests also reject late success/401 responses from an old session, including
operations that cannot be cancelled as reads. Existing accepted-write checks remain.

Recovery uses the application's existing administrator-issued temporary password:
the person can return to sign-in or replace that password and enter the dashboard.
There is no invented self-service password-recovery workflow. This path passes
through both the real assembled application and each real browser.

## Visual and focus comparisons

Shell geometry, fonts, directions, control identities and focus match. Thirteen
shell scenes per browser are pixel-identical below the live animated header;
six differ only in real previous-sign-in timestamps. Full original screenshots
are retained. Both browsers passed all 12 keyboard groups, with 58 observations
and 54 screenshots each. At the shell gate, only focus-animation opacity differed
(by less than 0.003); the unchanged Quasar transition lasts 0.4 seconds and the
observation occurs at 0.35 seconds. Labels, position, visibility, focus state and
all other indicator styles match exactly.

A Chrome resize discrepancy was investigated before navigation extraction. The
original committed application, run from an ordinary temporary source copy with
the same current harness, reproduces the open drawer on return to desktop width
in both languages. Its complete 19-scene comparison matches the extracted version.
The earlier harness captured a closed drawer with different transition timing.
Both observations are retained; application drawer behavior was not changed.

Navigation images match below the animated header except for real saved-search
update timestamps. All four session images per browser match exactly below the
header, including forced-password and recovered-user scenes. See the
[shell comparison](verification/webui-refactor-phase5/5b/comparison.json),
[navigation comparison](verification/webui-refactor-phase5/5c/visual-comparison.json)
and [session comparison](verification/webui-refactor-phase5/5d/comparison.json).

## Failed attempts and existing limitations

Retained shell attempts exposed test assumptions: icon ligatures remain in a
collapsed button's text; Preferences is persistent and closes through Cancel;
headless Chrome enforces a minimum window width; an open narrow drawer covers
its header toggle; native resize and server-backed accessible state settle at
different times. The harness observes stable actual geometry and uses the visible
backdrop. It does not change CSS or force application state.

The exact existing resize notification, `ResizeObserver loop completed with
undelivered notifications.`, is explicitly recorded. Only that exact resize event
is allowed by the shell harness; every other browser error remains a failure.
This is a baseline limitation, not a bug fix or a claim of error-free resizing.

Location-dependent unit/interaction fixtures were retargeted to the extracted
modules without dropping assertions. Their initial failed runs and corrected full
runs are retained. An assembled recovery assertion was corrected to observe the
closed drawer itself: NiceGUI's simulator still lists its child controls. Real
browser checks separately verify that those controls are hidden. All failed-run
databases were dropped. No newly discovered application defect was silently fixed.

## Final acceptance

The frozen production source passed these final local checks:

| Check | Result |
| --- | --- |
| Complete unit suite | 1,538 passed; no failures, errors or skips |
| Complete interaction suite | 209 passed; no failures, errors or skips |
| Real-root / real-API assembled suite | 43 passed |
| Chrome full workflows | 44 passed; 29 screenshots |
| Edge full workflows | 44 passed; 29 screenshots |
| Final Chrome and Edge keyboard checks | 12 groups, 58 observations and 54 screenshots per browser; no semantic focus differences |
| Supplemental session checks | Six passed per browser before and after extraction |
| Runner cleanup and diagnostic privacy checks | 23 passed |
| Disposable database cleanup | All 37 dropped; independent catalogue check found none remaining |

All Settings request counts match the Phase 3 baseline. Repeated visits, current
values after mutation, abandoned reads and accepted email sends pass. Both full
browser runs have 27 pixel-identical scenes below the animated header; the other
two differ only in real saved-search timestamps. Request timings and their limits
are retained: medians are comparable, but peak durations vary with local load.
Matched original/refactored 12-transition diagnostics recorded whole-transition
medians of 2.858 / 3.106 seconds and maxima of 6.531 / 4.425 seconds; these include
browser automation and reload waits, not just application processing.

[Final browser comparison](verification/webui-refactor-phase5/final/browser-comparison.json),
[final focus comparison](verification/webui-refactor-phase5/final/focus-comparison.json),
[unit/interaction results](verification/webui-refactor-phase5/final/isolated/summary.json),
[assembled results](verification/webui-refactor-phase5/final/assembled/assembled.xml),
and [database cleanup](verification/webui-refactor-phase5/database-cleanup.json).

### Accepted observation: initial Edge loading timeout

The first final Edge run timed out at Governance custody's loading message. No
custody HTTP request appeared in the API log and no browser error was recorded.
That attempt lacked UI-client request diagnostics, so its cause cannot be established
from the retained evidence. The full Edge rerun passed all 44 checks; identical
12-transition diagnostics also passed against both the original committed application
and the refactor. This does **not** establish a cause or prove an existing defect.
Read-only request/cancellation diagnostics now preserve metadata, never credentials
or request/response payloads, for any recurrence. Their privacy and cancellation
behavior have direct tests. See the [investigation record](verification/webui-refactor-phase5/final/custody-investigation.json).

The approved [Phase 4 review](webui-refactor-phase4-review.md) says: “Any unexplained
functional, visual, focus, permission or performance difference blocks that step.”
After reviewing this observation and the passing reruns, the user explicitly
authorized marking Phase 5 complete with a note that the first loading problem
was not replicable. This is a specific acceptance exception for this observation;
the general regression gate remains unchanged. Phase 5 is therefore **complete
for the approved local scope**. The timeout did not recur after diagnostic logging
was added, including 12 transitions on the refactor and 12 on the original code.
Its cause remains unresolved, and no product fix is claimed or applied. Retain the
diagnostics to investigate if it recurs. Phase 6 has not started.

Separately, the first final Chrome run polled a table detached by navigation even
though the screenshot showed the correct loaded relationship-types table. The
harness now waits for the current breadcrumb and reacquires the table; the full
rerun passed. Both failed runs remain in `final/initial-attempts`. A preliminary
original-source diagnostic was deliberately interrupted to avoid overlapping local
email recipients, cleaned up normally, and is not counted as a passing run.

The existing MailDev instance (PID 44350 at inspection) is reused for synthetic
local email with verified TLS. It was not started or stopped by this work. All owned test services and driver
sessions were closed, and the ordinary temporary source copy was removed.
Persistent application databases and environment settings are unchanged.

All 4,071 English/Arabic keys, wording and provenance remain byte-identical to the
starting revision. No keys were added, removed or changed and no administrator
export was promoted. Coverage, ordering, blanks, placeholders, artifact hashes
and catalogue-reference checks pass. Configuration authority and API-template
synchronization checks also pass; there are no template changes or operator actions.
See [source/owner audit](verification/webui-refactor-phase5/source-audit.json) and
[translation evidence](verification/webui-refactor-phase5/translation-check.json).
