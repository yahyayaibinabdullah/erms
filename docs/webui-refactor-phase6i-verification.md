# WebUI refactor: Phase 6I — Account, sign-in and preferences

**Status:** Complete for the approved local scope.

## Scope and state

Six small modules now own sign-in construction, password dialogs, profile/menu
population, preferences, localization coordination and authenticated startup.
`SessionContext` still owns authentication and identity cleanup. The root keeps
startup configuration, styles, shared shell elements and callback assembly.

The modules receive explicit identity/locale readers and setters, UI elements
and destination callbacks. They do not import `app.py`, receive its shared state
dictionary, create routes or add caches. Existing locale storage keys, ETags,
language/direction reload rules, temporary-password restrictions and optional
asset ordering remain intact. Cross-feature initialization continues through
explicit inspector, messaging, hold-navigation and destination callbacks.

## Requirement-to-verification map

| Preserved behavior / caller | Owner and evidence |
| --- | --- |
| Sign-in appearance, failed credentials, clearing password input and forced-password gate | `account_sign_in.py`; entire original dialog construction/handler bindings reconstructed; session lifecycle tests and real browser recovery |
| Ordinary/forced password validation, cancellation, errors and startup order after replacement | `account_password.py`; original/extracted parameterized interaction cases; original/extracted browser normal dialog and real-API temporary-password replacement |
| Profile identity, role names, previous sign-in and fresh profile reads | `account_profile.py`; exact function reconstruction, retained presentation contracts, EN/AR menu captures and multi-client identity tests |
| Personal language/timezone preferences, versioned writes and all-or-nothing locale-storage invalidation | `account_preferences.py`; success/error/cancel tests; actual browser language changes, focus and dialog appearance |
| Catalogue reuse, conditional reads, locale metadata and document direction | `account_localization.py`; existing locale tests retargeted without removing assertions; startup/configuration behavior tests; unchanged artifacts |
| Restored session, forced-password recovery, query/navigation restoration and optional-asset timing | `account_bootstrap.py`; original function reconstruction, retained ordering tests, full assembled suite and browser reconnect/session-isolation journeys |
| Organization, Settings, records, aggregation, search, inspector, messaging and hold callers | Existing explicit callbacks remain connected; 105 other direct host functions unchanged; full regression suites |

## Findings

The browser keyboard check originally sent Escape while opening a preference
selector, which dismissed the existing dialog. It now starts ordinary Tab
navigation from the heading and checks that focus remains inside the dialog.
It also reuses an already-open profile menu rather than toggling it closed.
These are test corrections; application event handling is unchanged.

Unit and interaction suites run in separate processes, as required by the
existing runner. A combined focused invocation exposed NiceGUI's empty-slot
state in an unrelated component-uploader unit test; isolated full suites are
the acceptance evidence.

## Verification

| Check | Result |
| --- | --- |
| Original focused behavior | 27 passed, including 11 new account-dialog cases |
| Full final unit / interaction / assembled suites | 1,603 / 296 / 57 passed |
| Chrome and Edge, original and extracted | All 10 groups per journey passed; 10 scenes including the independent second client |
| Focus and requests | Identical in both final browser pairs |
| Appearance | Only live previous-sign-in timestamps and the animated header differ; all other pixels match |
| Source reconstruction | 11 functions, including sign-in error formatting, and the complete sign-in dialog match the original; 105 other direct host functions unchanged |
| Translation/configuration | All 4,071 keys and artifact bytes preserved; active references, terminology, configuration authority and templates pass |
| Runner safety | 24 passed |
| Disposable databases | All 18 unique databases removed; independent PostgreSQL catalogue audit passed |

Two existing assembled tests attempted to click detail actions before those
controls rendered. They now wait for the visible Edit scheme / Access controls;
both corrected checks pass against the original application as well as the final
full suite. No application navigation or rendering change was made.

The initial Edge pair differed by one profile read before sign-out. Opening the
menu schedules that read; immediate sign-out can clear the principal before the
callback starts. The test now waits for the menu's existing read before clicking
Sign out. A fresh original/extracted Edge pair has equal requests, as do the final
Chrome and Edge runs. The original request difference remains recorded.

The sign-in-specific error formatter also moved into the sign-in owner, with its
existing root import preserved for callers. Acceptance above uses the finished
source, including that final move. No secrets appear in screenshots; password
fields retain their existing masking.

Firefox, Safari and CI remain deferred. Evidence:
`docs/verification/webui-refactor-phase6i/`; raw intermediate runs and original
snapshots: `.runtime/webui-refactor-phase6i/`. No artifact promotion, translation
review or operator configuration action is required. All changes remain local
and uncommitted on `refactor-API-python-file`.
