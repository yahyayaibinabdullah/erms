# WebUI refactor: Phase 6B — audit and entity history

**Status:** Complete for the approved local Chrome/Edge scope. Stop for user
approval before 6C.

## Boundary

Audit filters, paging, timelines, event details, historical identities and
entity-history dialogs now live in `audit_workspace.py`. The existing actor selector,
audit/disposition labels and API client remain unchanged. The host supplies shell entry, current
identity, current destination, Settings access and existing entity openers.

The audit page's revision counter belongs to one workspace per root-page client.
The feature receives no shared application-state dictionary and imports no host
application. There is no new cache. Existing guards, shell-entry order, API
requests, dialog-close delays and resource-navigation order must remain unchanged.

No routes, URLs, browser-history behavior, schema, API, wording, translations or
layout changes are part of this step. Existing event-detail table presentation is
preserved as part of the approved refactoring contract.

## Requirement-to-verification map

| Existing contract | Implementation boundary | Evidence |
| --- | --- | --- |
| Historical actor/entity names, reference snapshots, export scheme identity and readable disposition events | Audit identity helpers, timeline and detail renderers; unchanged label modules | Focused identity, export and disposition tests; synthetic browser events with fixed historical identities |
| All filters, bounded actor suggestions, paging and reset, including monitor's initial scope | Audit workspace; unchanged `audit_actor_select.py` | English/Arabic interaction tests assert request conditions, 50-row pages, offsets, reset and stale responses; browser pagination and scope checks |
| Settings access and unsaved-navigation guard | Existing Settings controller through explicit callbacks | English/Arabic allowed/denied/blocked interaction cases; assembled real-API Settings mutation and event-link case |
| Resource lookup, cached entity reuse, missing/forbidden entities and retained proof | Audit navigation plus narrow host destination callback | Direct tests preserve calls, origin-dialog behavior and close delays; real browser opens record from its audit event |
| Timeline, detail and nested entity history keep their appearance and controls | Unchanged render bodies and shell styles | Before/after English/Arabic screenshots and native keyboard-focus sequence in Chrome/Edge |
| Empty/error results, abandoned reads, repeated navigation, reload and root URL/history | Per-client revision plus existing navigation/session services | Browser controlled errors, delayed reads, reload and history-length checks; interaction stale-result test |
| Remaining history callers retain their wiring | Host alias to shared feature handler | Source comparison plus full unit/interaction and assembled suites |

The history callers are digital components, record details, aggregation details,
governance cards and generic entity tables, organization-unit/role/user details,
and both hold list/detail views. Audit entry callers are drawer navigation,
saved-navigation restoration and Messages Monitor. The source comparison checks
these unchanged callers, not just the new module.

## Baseline development

The pre-extraction focused suite passes 44 cases; the audit-related interaction
baseline passes 15 cases. The assembled application passes all 43 existing cases.

Browser harness development identified incorrect test assumptions: a populated
correlation input's clear icon receives focus before Clear filters; filtering can
leave the same event text visible while replacing its DOM element; dialog cards
contain nested cards; and the drawer's Audit trail button also has a history icon.
The harness observes actual focus, waits for replaced results, scopes outer dialog
cards and selects the record's Event history action by caption. These are test
corrections made before production extraction, not application fixes.

Every database-backed attempt uses a fresh uniquely named database on the existing
local PostgreSQL cluster. Fixed synthetic audit events are inserted only in those
disposable databases with source `seeding`; no persistent application database is
used. Original failure evidence and cleanup outcomes are retained.

## Test corrections after extraction

All 44 focused cases and 15 audit-related interaction cases passed immediately
after the move. A new independent-workspace case passed alone but failed in the
full unit suite because it created UI controls without a NiceGUI page context.
It now runs through the interaction suite's `User` page fixture. Its assertions
were retained; no production change was made to resolve the test failure.

The original Chrome baseline recorded one scoped monitor search in English,
whereas Edge and the first extracted runs recorded the expected initial search
and reset search. Client diagnostics show that Chrome's original scoped search
was still pending when navigation to the next page began. The harness now waits
for the initial search and the reset search to complete before continuing. The
original baseline is retained: this request-count difference is reported, not
silently normalized into a claim of identical totals. Full filter/reset payloads
also remain covered by the English/Arabic interaction tests.

The first image comparison matched all 12 Chrome scenes and 11 Edge scenes
exactly below the animated header. Edge's remaining scene differed at 12 pixels
by at most one channel level (out of 255), at rounded card corners behind the
nested dialog's dimmed overlay. The images were inspected; positions, content
and styling match. Original images are retained without masks or replacement.

## Final verification

| Check | Result |
| --- | --- |
| Focused audit/history baseline and extracted cases | 44 passed before and after |
| Audit-related interaction baseline and extracted cases | 15 passed before and after; additional workspace-isolation case passes |
| Full WebUI unit suite | 1,563 passed |
| Full WebUI interaction suite | 210 passed |
| Assembled real-root / real-API suite | 43 passed before and after |
| Chrome feature journey | 11 check groups passed before and after, in English/Arabic |
| Edge feature journey | 11 check groups passed before and after, in English/Arabic |
| Final visual comparison | All 12 scenes per browser match pixel-for-pixel below the animated header |
| Keyboard focus | Same correlation-input → clear icon → Clear filters sequence in both languages and browsers |
| Request comparison | Edge counts/queries/outcomes match; Chrome matches outside the explicitly recorded monitor/reset baseline timing gap |
| Runner safety and diagnostic privacy | 23 passed |
| Database cleanup | All 15 disposable databases dropped; independent catalogue check found none remaining |

The final full suites have no failures, errors or skips. The failed initial unit
attempt is retained beside its corrected full rerun. Both final browser runs use
the strengthened monitor/reset waits and the same frozen production source.
The final images match exactly; the first Edge run's tiny colour-level variation
did not recur. Original baselines and both extracted runs remain available.
Only the unchanged animated header above y72 is excluded from pixel comparison.

All 131 other direct host functions are AST-identical to the pre-6B working copy.
The five identity/value helpers, timeline renderer and history dialog are
AST-identical. The detail renderer changes only its principal accessor; navigation
changes only the explicit Settings/destination callbacks. The audit filter/paging
body, shell-entry statements and resource-dispatch statements are unchanged.
The revision counter moves to the per-client workspace. Existing logout cleanup
selects Dashboard and cancels reads, so the selected-page check still invalidates
abandoned audit views. Existing actor-selection and stale-response tests remain.

Only `app.py` changes among existing runtime files; `audit_workspace.py` is new.
All other captured runtime modules, shell styles and catalogue artifacts are
byte-identical to the baseline. The host retains assembly, shell entry and resource
destination adapters deliberately. No second application-state dictionary or
replacement monolith was introduced.

Successful uncontrolled audit/history request durations under shared local load:
Chrome median 84.86 → 101.37 ms, maximum 306.86 → 308.33 ms; Edge median
86.17 → 107.305 ms, maximum 429.60 → 344.52 ms. These are server-request
observations, not end-to-end latency guarantees. Chrome has 43 → 44 such requests
because of the recorded baseline reset timing; Edge has 44 → 44. The final monitor
segments complete exactly two searches per language: initial load and reset.
All other request counts, queries and controlled outcomes match.

All 4,071 translation keys, wording and provenance remain unchanged. Coverage,
ordering, blanks, placeholders, catalogue hash and source references pass, as do
all 35 approved terminology mappings across 966 contextual uses. No artifact was
replaced or administrator export promoted; no new translation review is required.
There are no environment-template, dependency, API or schema changes.

No email was sent, and no Safari or MailDev setting/process was changed. Firefox,
Safari and CI remain deferred. Work is local and uncommitted on
`refactor-API-python-file`; no branch, worktree, commit or push was created.

Evidence: [local verification files](verification/webui-refactor-phase6b/),
including the source comparison, raw browser evidence, final comparison,
translation checks and database-cleanup record. Runtime service logs remain in
gitignored `.runtime/webui-refactor-phase6b/`.

**Next approval:** 6C — shared entity controls. Implementation has not started.
