# WebUI refactor: Phase 6D — Classification

**Status:** Complete for the approved local scope; all final acceptance checks passed.
Phase 6E has not started.

## Scope and ownership

The existing single-page application, public URLs, browser history, visible text,
layout, permissions and API/schema contracts are preserved.

| Responsibility | Owner |
| --- | --- |
| Classification entry, restoration arguments, transfer permission, view token and per-client preferences | `classification_controller.py` |
| Direct retention lookup, editor field source, scheme publication-field restriction, retention payload rules, collection decoration and legacy list actions | `classification_editor.py` |
| Published-scheme type-ahead; existing editor and Advanced Search classification pickers | `classification_selectors.py` |
| Classification tree, branch paging, search, details, inherited retention, lifecycle actions and mutation refresh | Existing `classification_workspace.py`, unchanged |
| Import/export dialogs, uploads, download formats and language selection | Existing `classification_transfer.py`, unchanged |

The root keeps shell rendering/navigation callbacks and the shared editor assembly.
It passes explicit editor/history callbacks to the controller. Classification
modules do not import `app.py` or receive the shared application-state dictionary.
The controller is constructed after the audit workspace supplies its history
callback. Selection-control instances retain their original request revisions,
debounce timing, paging and selected-value handling.

The common editor still orchestrates metadata, direct-retention and translation
writes in their original order, and invokes the existing `on_saved` callback.
Classification payload decisions and field restrictions now belong to the feature
helpers; the existing entity registry and common translation widget are reused.

Preferences remain per root-page client and contain only filter, expansion and
paging choices. Identity cleanup replaces the preferences dictionary and clears
the view token, invalidating old callbacks. Existing workspace snapshots remain
scoped to that workspace's identity/language; existing mutation, selection and
refresh invalidation is unchanged. No new cache, request, timer or privilege is
introduced.

## Requirements and connected callers

| Preserved behavior / callers | Implementation and evidence |
| --- | --- |
| Drawer, breadcrumb restoration, Dashboard, audit entity links, translation-inspector entity links, aggregation parent-classification links and security-operations destinations | Existing `select_classification_workspace` wrapper delegates to the controller; original/extracted controller tests preserve argument forwarding, registration, unresolved-principal guard, permission and direction; full assembled/root suite and browser reload/return checks |
| Classification workspace create/edit callbacks, locked scheme/parent fields, direct and inherited retention | Existing workspace uses the shared editor with the same callbacks; ten original/extracted save cases cover payload/order/version/validation/failures; real API creation, editing and retention writes; existing workspace interactions and browser details |
| Scheme publication field and classification translation editing | Same field restriction and translation widget; assembled canonical/Arabic translation saves and history read; English/Arabic browser editor comparison |
| Aggregation editor terminal selection | Existing editor picker moved without changing its body apart from the direction reader; original/extracted interaction checks cover 26-row look-ahead, branch paging, selected-value retention, terminal selection and failed requests |
| Advanced Search classification selection and advanced aggregation scheme type-ahead | Existing independent picker preserved; same interaction cases in LTR/RTL; original/extracted scheme-selector cases cover debounce, cancellation and selected values; source assertions retargeted without weakening sorting or direction checks |
| List decoration, search prompt and legacy scheme actions | Exact statements moved; API method/path/version and refresh-call substitution checked against the original source; retained generic list styling remains unchanged |
| Import/export and lifecycle presentation | Existing workspace/transfer tests retained; browser import and Word-export entry, scheme/detail actions and empty state; original renderer and transfer module bytes unchanged |
| Identity isolation, repeated navigation, abandoned reads and preference restoration | Controller lifetime/reset/client-isolation tests; existing branch-abandonment and Dashboard/session tests; repeated browser visits, branch-page restoration and reload |

The captured dependency map includes call sites and both original shared-state
keys. Shell navigation and other feature entry points retain their existing order;
the root wrapper remains available to every existing caller.

## Verification results

| Check | Result |
| --- | --- |
| Original full unit / interaction baseline | 1,576 / 217 passed |
| Added original controller / save / picker / scheme-selector cases | 4 / 10 / 6 / 2 passed |
| Original assembled baseline | 46 existing cases passed; added classification create/edit/retention/translation/history case passed in its corrected focused run |
| Final full unit / interaction suites | 1,592 / 223 passed; no failures, errors or skips |
| Final full assembled suite | 47 passed; no failures, errors or skips |
| Original Chrome and Edge journeys | Both passed all 9 check groups in English/Arabic |
| Extracted browser journeys, visual/focus/request comparison | Chrome and Edge each passed all 9 groups; focus and application request counts match; 14/18 scenes per browser match exactly below the animated header, with only fixture timestamp digits differing in the other four |
| Source preservation | Three selector bodies identical after direction-reader substitution; retention-payload and decoration statements identical; legacy action bodies identical after refresh-callback substitution; 113 unaffected direct host functions unchanged; styling and message-key literals preserved |
| Translation artifacts and environment checks | All 4,071 keys ordered/matched, no blank/placeholder mismatches, original text/provenance bytes and artifact hash preserved; active catalogue and 966 contextual uses of 35 glossary mappings pass; 122 configuration owners and 36 API settings verified |
| Test-runner safety/privacy checks | 23 passed |
| Disposable databases | All 16 unique databases removed; independent PostgreSQL catalogue audit confirms none remain |

The full screenshot comparison excludes only the top 72 pixels containing the
animated header. The scheme details and Word-dialog scenes show the fixture's
existing First used / Last updated values at 17:03 in the baseline and 17:06 in
the extracted run. Visual inspection and a separate pixel check confirm every
differing pixel below the header is inside those two timestamp values. Original
screenshots are preserved without masking or styling changes. No layout difference
remains unexplained. Request comparisons omit only background message catch-up
and unread-count polling; all other method/path/query/status counts match.
All 62 source/harness hashes captured for each final browser run still match the
working files.

## Findings and corrections

Before extraction, the new tests needed corrections for existing UI structure:
scheme rows use a different container from classification nodes; text carries
invisible localization markers; export choices are menu items; successful scheme
creation already opens its details; canonical and translated title controls share
labels. NiceGUI's simulator requires clicking the owning card rather than relying
on browser event bubbling. The history assertion was corrected to use the
existing resource history endpoint. These corrections changed tests only.

The assembled acceptance run then caught a real assembly error in the extraction:
the controller initially referenced the history callback before audit construction.
Its construction was moved after the callback assignment. The failing run was
stopped and its disposable database removed; acceptance was restarted. The source
sorting/direction assertions were also retargeted to the extracted selector owner,
preserving their checks while allowing the changed indentation.

The runner safety checks require the API virtualenv's PostgreSQL driver. An initial
frontend-virtualenv attempt failed at collection; the correct environment passed
all 23 checks. The original scheme-selector wrapper reports a harmless pytest
import-rewrite warning from importing its dependencies before pytest.

No product defect fix, new UI text, catalogue edit or configuration change is part
of this phase. Work remains local and uncommitted on `refactor-API-python-file`.
Firefox, Safari and CI remain deferred; Safari and MailDev are untouched.

Evidence is stored in `docs/verification/webui-refactor-phase6d/`. Raw runs and the
pre-6D host snapshot remain in gitignored `.runtime/webui-refactor-phase6d/`.
Stop for approval before Phase 6E — Security configuration and access controls.
