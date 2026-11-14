# WebUI refactor: Phase 1 inventory and baseline

**Date:** 10 November 2026  
**Contract:** [Approved architecture and migration specification](../specs/webui-modular-routing-refactor.md)  
**Source commit:** `3a4481d5de96df1b27f1c2e401316ab00b93567f`

Phase 1 records the existing application, its dependencies, test results, and
representative English/Arabic appearance. No production code, UI, API,
translation, configuration, URL, or navigation behavior was changed.

**The application is not ready for extraction.** The existing full WebUI runs
have ten failing cases. Browser observations also found incomplete aggregation
restoration. These are baseline findings, not regressions caused by this work.
Phase 2 must establish reliable checks before Phase 3 moves application code.

## 1 Evidence and limits

- [Readable source inventory](verification/webui-refactor-phase1/source-inventory.md):
  all 54 runtime Python modules, closure dependencies, and 121 dialog construction sites.
- [Detailed source inventory](verification/webui-refactor-phase1/source-inventory.json):
  source hashes, imports, every function, 66 navigation callsites, 829 shared-state
  accesses, and test definitions in 96 files. There are 177 direct function-scope
  entries under `index`, including 28 lambdas and two comprehensions; 147 are
  named functions. Counts describe source structure, not distinct user workflows.
- [Unit results](verification/webui-refactor-phase1/unit-results.xml) and
  [interaction results](verification/webui-refactor-phase1/interaction-results.xml)
  preserve individual case results and failure traces.
- Screenshots and measurements are in
  [the evidence directory](verification/webui-refactor-phase1/).

The inventory is exhaustive for the scanned Python functions and recognized
dialog/navigation/state call patterns. Dynamic variants, permission combinations,
and callbacks still need behavior checks. Neither static discovery nor a passing
source assertion proves that an assembled screen works. The feature map below
connects existing requirements, implementation entry points, and available tests;
it is a starting traceability map, not a declaration that every requirement has
passed end-to-end verification.

## 2 Current architecture and navigation

`frontend/webui/app.py` has 21,740 lines and one application page, `@ui.page('/')`.
The API entry point is `backend/services/api/main.py`, with supporting modules;
it is outside the extraction scope. Many WebUI features already have modules,
especially settings, classification, messaging, relationships, and disposition.
This refactor should complete their separation instead of replacing them.

The root page creates the API client, session state, shell, and feature callbacks.
Screens replace content inside that shell. `register_navigation` records the
current view, updates the trail and drawer, and cancels pending reads.
`restore_navigation_entry` dispatches saved destinations to their existing
loaders. `guarded_page_navigation` applies the existing unsaved-change check.
These are central dependencies, not independent entity routes.

The existing source uses URL replacement for search; it does not add a browser
history entry for each screen. Observed screen changes stayed at `/`. Actual
browser Back/Forward and exit behavior was not exercised in all four browsers.
Preserve `/`, `/?q=...`, current refresh/restoration behavior, breadcrumbs, and
in-app Back. Do not add public URLs, history interception, or browser exit traps.

The destination inventory includes:

| Family | Existing destination keys / additional views |
| --- | --- |
| Home and search | `dashboard`, `advanced-search`, `full-text-search`, `saved-search-administration`; global search, saved search and favourite entry points |
| Records and aggregations | `records`, `record-details`, `aggregations`, `aggregation-details`; aggregation browse/search modes, record draft/capture editor and component previews |
| Classification | `classification-schemes`, `classification-workspace`, `classification-scheme-details`, `classification-details`; import/export and retention controls |
| Organization and security | `organization-browser`, `org-units`, `org-unit-details`, `roles`, `role-details`, `users`, `user-details`, `security-levels`, `profiles`, `security-operations`, `governance-custody` |
| Administration | `application-settings`, `audit-trail`, `login-sessions`, `text-indexers`, `text-indexer-details`, `translations`, `relationship-types` |
| Holds | `holds`, `hold-details`; resource hold actions and effective hold details |
| Disposition | `disposition-eligibility`, `disposition-jobs`, `disposition-job`, `disposition-tasks`, `disposition-task`, `disposition-templates` |
| Messaging | `messages-inbox`, `messages-outbox`, `messages-drafts`, `messages-notifications`, `messages-monitor`; compose/detail, deleted mailbox, capture, notification administration and monitor subviews |
| Shell/session dialogs | Login and recovery flows, password change, preferences, account menu, notification controls, breadcrumb overflow and unsaved-change confirmation |

Keys identify internal navigation only. Visibility depends on permissions and
configuration. Entity registry entries such as `privileges` and `permissions`
do not imply new standalone pages. Shared editors and detail dialogs remain
dialogs; their callsites and enclosing callbacks are listed in the inventory.

## 3 Feature, dependency, and test map

Paths below are relative to `frontend/webui/`, unless stated otherwise.
Test filenames without a prefix are in `tests/`; `I/` means `interaction/tests/`.
The full test list and definitions are in the detailed inventory. Test references
identify relevant existing coverage; the results in section 6 govern pass/fail.

| Existing workflow / governing specification | Implementation and connected dependencies | Available checks / gap to close before extraction |
| --- | --- | --- |
| Login, recovery, expiry, password change and sign-out — [authentication](../specs/authentication-and-login-session-lifecycle.md) | `app.py::index`, login handlers, `show_change_password`, `sign_out`, `api_client.py`; localization and session reset | `test_login_feedback.py`, `test_api_client.py`, dashboard/search isolation tests. Add assembled login/recovery/expiry and two-identity browser journeys. |
| Drawer, breadcrumbs, in-app Back, refresh and unsaved navigation — [breadcrumbs](../specs/persistent-navigation-breadcrumbs.md) | `register_navigation`, `restore_navigation_entry`, `guarded_page_navigation`, `navigation_drawer.py`; all screen callbacks | `test_navigation_history.py`, drawer/heading tests, `test_advanced_search_unsaved_changes.py`. Add actual four-browser URL/history/restoration checks; investigate finding B1. |
| Dashboard, favourites, recent activity and review reminders — [favourites](../specs/user-favourites.md), [settings](../specs/administration-settings.md) | `select_dashboard`; dashboard summary API, resource openers, identity-scoped state | `test_dashboard_session_isolation.py`, `I/test_dashboard_identity.py`, `I/test_phase4_configuration.py`; EN/AR screenshots and warm navigation measured. Add mutation freshness and abandoned refresh journeys. |
| Full-text/global search, advanced queries, saved search and sharing — [full-text](../specs/full-text-search.md), [advanced search](../specs/advanced-search.md), [retention extension](../specs/advanced-search-effective-retention-extension.md) | search callbacks, `select_advanced_search`, `select_saved_search_administration`, bounded audience selectors; records/aggregations and URL replacement | Full-text phase3/4, advanced builder/unsaved, saved-search, search-isolation tests; `I/test_advanced_search_retention.py`, `I/test_phase6_search_configuration.py`. Add browser query, paging, results, restoration and permission journeys. |
| Record creation/editing, draft capture, physical/digital rules, components, previews and relationships — [record detail](../specs/record-detail-page.md), [records](../specs/records-management-subsystem.md), [preview](../specs/digital-component-preview-navigation.md), [relationships](../specs/record-and-aggregation-relationships.md) | `select_record_details`, `open_record_draft_editor`, `open_editor`, `show_components`, `preview_record_components`, `resource_relationships.py`; parent aggregation, ACL, holds, messaging capture | Entities, medium, staged-preview, relationship and collection-refresh tests; `I/test_capture_preparation.py`, `I/test_capture_destination_controls.py`, inspector/picker tests. Record list/detail captured EN/AR; add digital upload/preview/capture and write/failure workflows with real API. |
| Aggregation browse/search, hierarchy, create/edit, close/reopen, move, ownership, location, vital status and review — [browser](../specs/aggregation-classification-browser.md), [types](../specs/aggregation-and-record-types.md), [medium/review](../specs/resource-medium-vital-status-review-and-location.md) | `select_aggregation_browser`, `select_aggregation_search`, `open_aggregation`, `open_editor`, governed-action dialogs; classifications, records, holds, retention, permissions | `I/test_aggregation_browser.py`, collection/medium/hold/retention tests. Detail captured EN/AR; add all action outcomes and cross-feature return/refresh, including B1. |
| Classification schemes, hierarchy, translations, retention, import/export and selection — [classification](../specs/classification-scheme-subsystem.md), [transfer](../specs/classification-scheme-import-export.md) | `select_classification_workspace`, `classification_workspace.py`, `classification_transfer.py`, generic editor and remote selectors | `I/test_classification_workspace.py`, `I/test_classification_transfer.py`, entities/translation tests. Settings browse dialog captured; add real import/export, branch paging, inherited values and downstream navigation. |
| Organization tree, unit/role/user details, membership, editing and deletion — [organization browser](../specs/organization-structure-browser.md), [deletion](../specs/user-role-org-unit-deletion.md), [ownership](../specs/organizational-ownership-and-default-acls.md) | `select_organization_browser`, org/role/user detail callbacks, `show_memberships`, `open_editor`; role/profile/security selectors and API permissions | `I/test_organization_tree.py`, entity/profile, bounded collection, ACL tests. Add restricted-user and cross-feature mutation/refresh journeys. |
| ACL editor/defaults, explanation, security levels, profiles, oversight, break-glass and custody — [security](../specs/security-and-authorization-subsystem.md), [oversight](../specs/hierarchical-oversight-default-acls.md), [break-glass](../specs/break-glass-access.md) | `show_acl_editor`, `show_access_explanation`, `show_contextual_acl_roles`, `show_profile_privilege_editor`, `select_security_operations`, `select_governance_custody`; `authorization_ui.py`, `acl_editor.py`, settings link | ACL/defaults, hierarchical oversight, authorization, profile and security-localization tests; `I/test_security_level_selector.py`. Add authorized/denied assembled journeys and session isolation. |
| Settings categories, save/reason, secrets, validation, conflicts, audit link and bounded selectors — [settings](../specs/administration-settings.md) | `select_application_settings`, `application_settings.py::settings_page`; drawer, saved trail, audit event, custody warning | `I/test_application_settings.py`, `I/test_application_settings_audit.py`, phase4/6 configuration tests; category/dialog captures EN/AR. Pilot coverage must include every caller and failure/abandonment path. |
| Audit events/history, active sessions and text-indexer administration — [authentication](../specs/authentication-and-login-session-lifecycle.md), [full-text](../specs/full-text-search.md), [security](../specs/security-and-authorization-subsystem.md) | `select_audit_trail`, `show_event_detail`, `show_entity_history`, `select_login_sessions`, text-indexer list/detail; actor selector and resource links | Audit/export labels, `I/test_audit_actor_select.py`, settings-audit and phase4 tests. Add list/detail/filter/actions, authorization and return-state browser checks. |
| Holds: list/detail, create/edit, resource attachment/removal, state/reason and effective inheritance — [holds](../specs/legal-holds.md), [traceability](../specs/legal-holds-traceability.md) | hold callbacks in `app.py`, `hold_reason_dialog`, `open_hold_editor`, `add_resource_to_hold`, `show_effective_holds`; record/aggregation controls and notifications | `test_legal_holds_ui.py`, `test_hold_removal_localization.py`; source assertions do not establish full workflow coverage. Add real hold lifecycle and resource propagation checks. |
| Disposition eligibility, proposals, jobs/tasks, selection, review/approval, templates, artifacts, external/physical completion, history and recovery — [disposition](../specs/disposition.md) | `select_disposition`, existing `disposition/` modules and callbacks; resource pickers, acting role, messaging, settings | Existing `test_disposition_*.py` families cover many isolated contracts. Real preview fixture failed (B2); repair test setup, then cover connected lifecycle/permission/error paths before this feature moves. |
| Messaging compose/drafts, recipients, inbox/outbox/deleted restoration, attachments/capture, notification rules and monitor — [messaging](../specs/notifications-and-messaging.md), [external email](../specs/external-email-messaging-extension.md) | `select_messages`, `messaging_workspace.py`, `messaging_monitor.py`, `messaging_live.py`, `notification_administration.py`; records, disposition and session subscriptions | `I/test_messaging_workspace.py`, phase5, monitor/navigation, notification administration and capture tests; `test_messaging_live.py`. Resolve baseline failures; add real API journeys and live-update teardown/identity checks. No external mail was sent during Phase 1. |
| Relationship-type administration and resource relationship add/edit/remove/navigation — [relationships](../specs/record-and-aggregation-relationships.md) | `select_relationship_types`, `resource_relationships.py`, resource picker/inspector and resource openers | Relationship/search tests; `I/test_resource_picker.py`, `I/test_resource_inspector.py`. Add assembled writes, authorization, paging and linked-resource returns. |
| Preferences, language/direction, entity translations, catalogue administration and inspector — [internationalization](../specs/internationalization-and-user-preferences.md) | `show_preferences`, `select_translations`, translation editor/inspector, `locale_services.py`, `i18n_catalogue.py`, `rtl.py`; browser storage and reload | Locale/RTL/literal rendering, translation bulk/inspector/entity tests; `I/test_translation_source_filter.py`, collection localization. Preference dialog and EN/AR views captured; add preservation/provenance validation around later code moves. |

## 4 State ownership and extraction risks

| Existing state / dependency | Lifetime and preservation requirement |
| --- | --- |
| `ErmsApiClient`, `auth_state`, current identity and effective permissions | Created by the page/session; close and clean up on disconnect. Preserve sign-out, expiry and identity reset. Do not introduce a global client or identity cache. |
| Shared `state` dictionary | Holds current collection/rows, filters, aggregation mode/details, favourites, recent activity, search results/cursor/pages, result expansion/return anchors, collection pages, loading hosts and page tokens. Split only after mapping each reader/writer; keep current reset/persistence behavior. |
| `navigation_state`, trail and shell references | Own current destination, snapshots, breadcrumb entries and UI refresh callbacks. All screens depend on this coordination. Keep one owner while migrating. |
| `app.storage.user` | Persists session token, navigation trail, organization-browser state, disposition filter expansion and localization data/ETag/fallbacks. Preserve existing browser/session identity and language isolation; do not convert persisted data to module globals. |
| Localization context and document direction | Bound to the current client/language. Preserve catalogue keys, wording, provenance, formatting and reload behavior. No catalogue artifacts changed in Phase 1. |
| Page tokens, pending API reads and live-message subscriptions | Abandoned views must not overwrite the next view. Preserve cancellation and stale-response checks, live subscription cleanup and accepted server operations. |
| Remote selectors and relationship controls | Shared callbacks capture API and identity; retain bounded server search, selected IDs and independent branch pagination. |
| CSS, table patterns, header/drawer and shared content containers | Much of the shell/styles remains inside `index`. Moving it too early would affect every feature; defer broad extraction until after the pilot review. |

The source inventory records individual reads/writes and captured names rather
than treating all state as safe to share. Any later cache must satisfy the
[performance contract](webui-performance.md): scope, key, freshness,
invalidation, failure behavior, and identity/language isolation.

### Application Settings pilot boundary

The settings renderer is already separate. The smallest useful pilot is the
host callback `select_application_settings` (baseline `app.py:19518`) and its
explicit dependencies, while retaining `application_settings.py::settings_page`.
It captures 18 names: `add_button`, `add_record_button`, `aggregation_mode_bar`,
`api`, `auth_state`, `bind_remote_relationship_select`, `current_direction`,
`current_navigation_snapshot`, `guidance`, `navigation_state`,
`persist_navigation_trail`, `register_navigation`, `search_bar`,
`show_authenticated_view`, `state`, `subtitle`, `table_container`, and `title`.

Preserve all four entry paths: drawer click (`app.py:21313`), saved-navigation
restoration (`4650`, including category), audit-event setting link (`5134`,
including initial setting key), and custody warning (`17313`, disposition
category). Keep category persistence and the settings page token that prevents
late work from acting on a replaced view. Test these callers before extracting
the wrapper; do not use the pilot to introduce a general routing framework.

## 5 Browser and visual baseline

The required browser products are **Chrome, Edge, Firefox, and Safari**. Versions
and OS combinations must be recorded by the Phase 2 runner; the user has not
specified an older-version compatibility range.

| Browser | Phase 1 evidence | Remaining acceptance work |
| --- | --- | --- |
| Chrome | Existing repository evidence, but no new product-specific run in this phase | Repeatable product/version-specific run |
| Edge | No new product-specific run | Repeatable product/version-specific run |
| Firefox | No new product-specific run | Repeatable product/version-specific run |
| Safari | No new product-specific run | Repeatable Safari run; an engine substitute alone is insufficient |
| Codex embedded browser | New real UI/API observations and screenshots at 1440 × 1000 | Supplemental evidence only; not a substitute for the four rows above |

Captured in both English/LTR and Arabic/RTL: dashboard, Settings General,
Settings Disposition, preferences dialog, records table, record detail, and
aggregation detail. Settings' classification browse dialog was also captured in
English. Files use descriptive `*-en.png` and `*-ar.png` names. Screenshots are
viewport captures, not complete-page coverage. Blank-restoration captures are
defect evidence and must not become desired visual acceptance baselines.

The existing `tools.preview_application_settings --phase 4` fixture supplied
28 classification schemes, 1,036 classifications, nine aggregations and five
physical records, plus synthetic administrator/officer/viewer identities. The
browser run used the administrator. Preference changes affected only that
disposable identity. The fixture has sparse messaging/hold/component data and
does not exercise their workflows. Its “Phase 4” labels refer to the existing
settings fixture, not this refactor's migration phase.

Fixture timestamps use the run date and the trail grew during navigation.
Therefore these are initial appearance references, not automatically comparable
pixel-test goldens. Phase 2 must stabilize time, identity, trail, viewport,
fonts, data and loading completion, and cover restricted, loading, empty, error,
dialog, keyboard and focus states. Existing English-only accessible labels
were observed in Arabic (for example breadcrumb overflow and “Add to favourites”);
record and investigate separately, without silently changing translations.

### Performance observations

| Warm navigation | English samples, ms | Arabic samples, ms |
| --- | --- | --- |
| Settings entry | 295, 283, 284 | 280, 280, 281 |
| Dashboard return | 300, 284, 284 | 286, 287, 286 |

[Raw timing samples](verification/webui-refactor-phase1/navigation-timings.json)
measure automation click to visible target and include tool overhead. Dashboard
content can appear from its existing cache before refresh finishes. These are
descriptive samples, not network latency measurements or pass/fail thresholds.
Three warmed Arabic Settings/Dashboard cycles generated exactly three settings
GETs and three summary GETs, all HTTP 200, with no duplicate calls to those
endpoints in that measured scope
([request evidence](verification/webui-refactor-phase1/navigation-requests-ar.json)).
Cold-load timing, mutation freshness, delayed/abandoned tasks and all-feature
request budgets remain Phase 2/feature-gate work.

## 6 Test baseline and findings

Installed environments: Python 3.11.9; WebUI NiceGUI 2.24.2, pytest 8.4.2,
pytest-asyncio 1.4.0, httpx 0.28.1; API FastAPI 0.141.1, psycopg 3.3.5,
uvicorn 0.53.0. No dependencies were upgraded.

The two WebUI suites ran in separate processes with database URLs cleared and
the fallback API URL pointing to an unused loopback port. These suites use
source/unit checks and fake APIs; no database was needed. Commands from the
repository root:

```sh
DATABASE_URL='' MESSAGING_LISTENER_DATABASE_URL='' WEBUI_API_URL='http://127.0.0.1:1' frontend/webui/.venv/bin/python -m pytest frontend/webui/tests -q --junitxml=docs/verification/webui-refactor-phase1/unit-results.xml
DATABASE_URL='' MESSAGING_LISTENER_DATABASE_URL='' WEBUI_API_URL='http://127.0.0.1:1' frontend/webui/.venv/bin/python -m pytest frontend/webui/interaction/tests -q -o asyncio_mode=auto --junitxml=docs/verification/webui-refactor-phase1/interaction-results.xml
```

| Run | Passed | Failed | Skipped | Duration |
| --- | ---: | ---: | ---: | ---: |
| Full unit/source suite | 1,482 | 2 | 0 | 93.35 s |
| Full NiceGUI interaction suite | 201 | 8 | 0 | 97.00 s |
| Capture-destination file alone | 5 | 0 | 0 | 1.00 s |
| Four selected messaging cases | 1 | 3 | 0 | 3.18 s |

Focused runs diagnose failures; they do not supersede the full-run failures.
Their XML evidence is saved as `capture-isolated-results.xml` and
`messaging-focused-results.xml`. Of 96 test files, 53 contain source-reading or
inspection patterns (this count also includes catalogue reads). Source-location
dependence makes extraction particularly likely to break tests without proving
a product regression, while still leaving assembled behavior untested.

| ID | Existing failure / observation | Evidence and Phase 2 action |
| --- | --- | --- |
| T1 | `test_entities::test_entity_translation_editor_loads_selected_language_automatically` | Source slice expects `if not creating and spec.key in multilingual_fields:`; current code also checks `translation_edit_allowed`. Update the test around the existing permission-aware behavior and preserve its assertions; do not remove the permission check. |
| T2 | `test_legal_holds_ui::test_aggregation_command_centre_matches_the_approved_two_column_layout` | Expected literal class string omits current `detail-action-row`. Stale structural assertion; verify layout in browser and make assertion resilient without weakening layout coverage. |
| T3 | `test_capture_destination_controls::test_capture_medium_remains_digital_before_and_after_parent_selection` (`None`, `digital`, `mixed`) and `test_ordinary_record_medium_remains_editable_in_mixed_parent` | Four empty-slot-stack failures in the full interaction run; all five file cases pass alone. Repair test UI-context/lifecycle isolation, then repeat the full suite and relevant file-order combinations. |
| T4 | `test_messaging_phase5::test_deleted_mailbox_restore_uses_own_route_and_refresh` (EN/AR) and `test_capture_button_is_busy_until_staging_finishes` | Three missing “Open”/“فتح” locator failures persist in focused runs. Check fixture, locator and actual user flow; current evidence does not establish which is wrong. |
| T5 | `test_messaging_workspace::test_two_character_mixed_search_keeps_to_and_cc_separate` | “Message sent” absent in full run; selected case passes in focused run. Investigate order/timing sensitivity and assert completion deterministically. |
| B1 | Aggregation details incomplete after reload/restoration | In the disposable preview, open Records → Phase 4 record 5 → parent aggregation. Normal entry shows complete details. Reload restores heading and Add buttons but leaves body blank. Also observed after changing Arabic to English on that aggregation; normal navigation restores full content. Both incomplete screenshots and normal EN/AR detail screenshots are saved. No captured browser console error; cause not established. Add reproduction/diagnosis; a product fix requires separate approval. |
| B2 | Existing disposition preview seed fails | `tools.preview_disposition --phase 10` raised `disposition_reviewers_required` during fixture creation. Its unique database was dropped. Correct the fixture to meet existing rules before using it as baseline evidence; do not weaken database/application validation. |

No baseline failures were hidden, marked expected, skipped, or fixed in
production code. A source mismatch is not automatically a product defect;
a passing isolated rerun is not proof of full-suite stability.

## 7 Disposable environment and cleanup

The browser preview used a new uniquely named PostgreSQL database, initialized
from the canonical `database/schema.sql` through `tools.initialize_database`,
with separate seed scripts. The complete API and WebUI processes used that
database; the messaging listener fallback was also restricted to it. Storage,
cookie name, and generated preview secrets were isolated. No persistent ERMS
database was tested or changed, and no local `.env` values were edited.

| Disposable database | Outcome |
| --- | --- |
| `erms_messaging_test_acl_a83641cf03084e5c983b53d86e88affc` | Disposition seed failed; helper reported successful drop. |
| `erms_messaging_test_acl_6d3840bbf75a4e56a06a93afd48215f6` | Settings/browser baseline completed; owned servers stopped and helper reported successful drop. |

The preview tab was closed and its temporary viewport override reset. Existing
development services were not stopped. Lifecycle logs remain under gitignored
`.runtime/webui-refactor-phase1/`; checked-in evidence contains synthetic data,
test results and measurements, not private environment values.
An independent read of PostgreSQL's database catalogue confirmed that neither
disposable database remains. All 54 inventoried runtime module hashes still
match the original baseline; existing tracked files have no changes.

## 8 Phase 2 gate and subsequent order

1. Repair the test runner and the test defects above. Run unit and interaction
   suites separately, enforce database isolation for integration runs, preserve
   diagnostics and guaranteed cleanup, and demonstrate repeatability. Classify
   any real product defects separately; do not silently fix or normalize them.
2. Add assembled-application smoke coverage of every destination family and
   detailed Settings coverage of all four callers, categories, permissions,
   save/cancel/reason/conflict/error states, restoration, and abandoned work.
3. Establish real Chrome, Edge, Firefox and Safari checks, with English/Arabic
   visual comparison, navigation/history, keyboard/focus and console/network
   failure detection. Record exact versions/OS; stabilize fixtures and time.
4. Add selected real-API cross-feature journeys and mutation/identity/task
   freshness checks. Link requirement → current implementation → actual test
   evidence, expanding the map before each feature is moved.

**No extraction until the Phase 2 gate passes.** Keep Settings as Phase 3's
small pilot and retain Phase 4's explicit review before shared infrastructure.
Then choose small feature batches using the dependency inventory: already
modular workspaces first where practical; tightly coupled record/aggregation,
security and cross-feature workflows only after their coverage is ready.
Do not assign a rigid entity-by-entity order before the pilot reveals the real
interface costs. Whole-application verification and cleanup remain separate
Phases 7 and 8.

Phase 1 provides the inventory and an honest baseline with recorded gaps. It
does not certify regression freedom or authorize any change to existing UX.
