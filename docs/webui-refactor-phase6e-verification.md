# WebUI refactor: Phase 6E — Security configuration and access controls

**Status:** Complete for the approved local scope; all final acceptance checks passed.
Phase 6F has not started.

## Scope and ownership

This step preserves the single-page application, URLs, browser history, visible
text, layout, permissions and API/schema contracts. No product defect fix is included.

| Responsibility | Owner |
| --- | --- |
| Resource ACLs, inherited/dormant overrides, child aggregation/record defaults, impact confirmation and contextual-role paging | `access_control_dialogs.py` |
| Access explanations, decision gates, contributing roles, hold restrictions, source links and bounded subject selection | `access_explanation_dialog.py` |
| Assignable security-level selectors, parent/clearance bounds, reviewed security-level changes and hierarchy remedies | `security_level_controls.py` |
| Profile labels, protected-profile editing rules, immutable profile codes, change reasons and privilege dependency editor | `security_administration.py` |
| Security-level/profile field definitions, shared metadata and translation forms, collection layout/paging, drawer and resource action visibility | Existing entity registry and shared host/control assembly, reused |

The feature modules do not import `app.py` or receive the shared application-state
dictionary. The root supplies the API client, current-principal/direction readers,
error presentation and explicit navigation/refresh callbacks. Existing pure
permission-dependency, privilege-dependency and authorization presentation helpers
remain authoritative and unchanged.

State stays inside each dialog/control: selected privileges, ACL grants and
versions, previewed security versions, picker offsets, debounce tasks and request
revisions. The factories introduce no cache, timer, new request or global state.
The host's client/language context, identity cleanup and API authorization remain
unchanged. Shared forms keep metadata/translation write ordering and refresh rules.

## Requirements and connected callers

| Preserved behavior / callers | Implementation and verification |
| --- | --- |
| Records and aggregations: resource ACL editor, required reason, complete grant payload, optimistic version and refresh | Original/extracted interaction cases; assembled real-API ACL write and reopen; Chrome/Edge EN/AR resource dialogs; identical moved function body |
| Aggregation Advanced actions: default child aggregation and record ACLs, dormant/custom mode, impact preview and confirmation | Original/extracted tests for both scopes, required reasons, dependency selection, dormant controls and conflict retention; browser default dialogs; original visibility tests retain both capability and administration privilege gates |
| Contextual managers and file administrators; organization browser role selection | Existing labels/permission checks and explicit organization callback retained; contextual paging/closed-response checks; bounded role selector remains the shared owner |
| Record/aggregation access explanations, allowed/denied decisions, subject privileges and redacted source/hold context | Original/extracted subject-gate and stale-response tests; bounded 26-row look-ahead subject paging; existing authorization/hold source assertions retargeted; both browser journeys and assembled explanation read |
| Aggregation creation/editing and resource security-level changes | Existing assignable selector tests cover server min/max bounds, invalid retained values, changed parents, stale responses and old API rejection; review/reason/conflict/version/refresh tests; browser record/aggregation change dialogs |
| Profile privilege actions from shared cards and legacy table | Original/extracted dependency selection, removal confirmation, required reason, save and refresh checks; real API verifies stored prerequisites; browser search/focus/cancellation in EN/AR |
| Profiles and security-level configuration metadata/translation forms | Shared form and registry reused; profile-only rules extracted; existing assembled create/edit/translation cases retained; protected-profile/immutable-code/reason tests; styling/message literals preserved |
| Remaining organization, record, aggregation, legal-hold, audit and security-operations callers | All 115 unaffected direct host functions retain identical bodies; complete unit/interaction and assembled suites; no change to later-phase feature implementations |

## Verification results

| Check | Result |
| --- | --- |
| Original full unit / interaction baseline | 1,592 / 223 passed |
| Added original security-dialog cases | 20 passed |
| Original assembled baseline | 48 cases passed in the full run; corrected ACL case and profile case passed in the focused run, covering all 49 cases |
| Final full unit suite | 1,603 passed; no failures, errors or skips |
| Final full interaction suite | 243 passed; no failures, errors or skips |
| Final full assembled suite | 49 passed; no failures, errors or skips |
| Chrome and Edge, original and extracted | Each passed all 9 check groups in English/Arabic; 20 scenes per browser |
| Browser comparison | Focus and application request counts match; 16/20 scenes match exactly below the animated header; the other four differ only in fixture timestamp digits |
| Source preservation | Six dialog/selector bodies and five label helpers identical after principal/direction reader substitution; complete shared editor identical after inlining profile helpers; 115 unaffected direct host functions unchanged; styling/message literals preserved |
| Translation artifacts | All 4,071 keys ordered/matched, no blanks or placeholder mismatches, unchanged text/provenance bytes and matching artifact hash; active references and 966 contextual uses of 35 glossary mappings verified |
| Configuration / runner checks | 122 setting owners and 36 API settings verified; templates agree; 23 runner safety/privacy tests passed |
| Disposable databases | All 15 unique databases removed; independent PostgreSQL catalogue audit confirms none remain |

The screenshot comparison excludes the top 72 pixels containing the animated
header. Visual inspection and a pixel check confirm that all remaining differences
are within the three Last updated timestamp values on background profile cards:
08:02 PM in the baseline and 08:05 PM after extraction. The four affected scenes
are the privilege editor and its filtered view in English/Arabic. Original images
remain intact. There is no unexplained layout difference. Request comparisons
omit only background message catch-up and unread-count polling; all other
method/path/query/status counts match. All 67 source/harness hashes captured for
each final browser run still match the working files.

The source proof compares the six extracted dialog/selector functions and five
label helpers, allowing only explicit principal/direction readers. It reconstructs
the complete original shared-editor body by inlining the narrow profile helpers,
and checks every styling/message-key literal. No existing runtime file except
`app.py` changed during 6E. Translation wording/provenance is unchanged.

## Baseline findings and test corrections

New tests were corrected for existing behavior: NiceGUI simulated clicks require
markers; operation/permission codes use resource prefixes; the two Search controls
need separate selectors; resource ACLs use `/permissions`; select controls have
both framework and application popup listeners. Dialog ordering is checked by
creation ID. None of these corrections changes product code or weakens assertions.

Browser focus checks were corrected to target an editable input, scroll it into
view through the existing dialog scroll area, and include search inputs. The
Advanced expansion is selected by its visible label. Earlier failed runs and their
disposable database cleanup are retained as evidence.

The pre-existing administration pagination icon error from 6C remains explicitly
checked: exactly four `TypeError: u.match is not a function` events on each profile
list entry. Any other browser error fails acceptance. It is not fixed in this
refactoring. Firefox, Safari and CI remain deferred; Safari and MailDev are untouched.

All work remains local and uncommitted on `refactor-API-python-file`, HEAD
`40bf384`. Stop for approval before Phase 6F — Login-session administration.

Evidence is stored in `docs/verification/webui-refactor-phase6e/`. Raw runs and
the original source snapshot remain in gitignored `.runtime/webui-refactor-phase6e/`.
No new translation drafts or operator configuration are required.
