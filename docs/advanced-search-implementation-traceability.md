# Advanced Search implementation traceability

**Specification:** `specs/advanced-search.md`, approved revision 1.0  
**Approved extension:** `specs/advanced-search-effective-retention-extension.md`, 28 October 2026

**Current delivery phase:** Effective-retention extension — one implementation phase

| Requirement | Planned phase | Implementation evidence | Verification evidence | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| §§7.1–7.2 ownership, versioned definition, direct role/unit audiences and relational integrity | 1 | `database/schema.sql`; migration `018_add_advanced_search_phase1.sql` | `test_saved_searches.py`; canonical/migration disposable-database checks | verified | One owner; separate role/unit grant tables; direct units only |
| §§7.3, 8.1 creator/administrator update authority and audience authority | 1 | `backend/services/api/saved_searches.py` | ownership, audience and negative authorization API tests | verified | Owner update does not depend on retaining save; audience update does |
| §8.1 delete matrix | 1 | saved-search delete route and capabilities | owner/non-owner privilege matrix and dependency tests | verified | Non-owner requires delete plus administrator |
| §8.2 approved built-in profile grants | 1 | canonical schema, migration 018, `security/catalogue-seed.json` | catalogue and database privilege tests | verified | Manager and Officer intentionally differ by administrator privilege |
| §8.3 server-computed capabilities and reasons | 1 | saved-search serializer/capability evaluation | API capability tests | verified | Client state is non-authoritative |
| §§9.1–9.3, 9.5–9.6 list/create/read/update/delete/admin APIs | 1 | `backend/services/api/saved_searches.py`; router registration; policy registry | API tests and policy inventory | verified | CRUD and administration contract |
| §4 canonical, versioned, bounded definition validation | 1 | `SavedSearchDefinition`; `canonicalize_search_request` | grammar boundary/API tests | verified | Reuses the resource search validator without executing results |
| §11 immutable governed change history | 1 | saved-search history and reason triggers; API event metadata | history tests | verified | Execution history is Phase 2 and remains non-governed |
| §12 lifecycle and optimistic concurrency | 1 | FK/lifecycle-aware audience SQL; `If-Match`; DB version trigger | lifecycle and stale-write tests | verified | Ineffective grants remain stored |
| §13 lookup indexes | 1 | canonical schema and migration indexes | schema and migration initialization checks | verified | No result execution in Phase 1 |
| AS-01 navigation visibility and ordering | 2 | `frontend/webui/app.py`; `frontend/webui/capabilities.py` | capability unit tests and live browser DOM/visual inspection | verified | Advanced Search is above Aggregations and requires either supported view privilege |
| AS-02–AS-05 recursive controlled builder | 2 | typed builder helpers and Advanced Search workspace in `frontend/webui/app.py` | `test_advanced_search_builder.py`; live builder interaction | verified | Existing JSON grammar only; client guards 50 leaves/five levels; target change confirms reset |
| AS-06 pageable result cards | 2 | Advanced Search execution/result renderer in `frontend/webui/app.py` | live desktop and 390px responsive browser inspection; empty-state execution | verified | Uses Wathiq cards, not `ui.table`; First/Previous/Next/Last preserve builder state |
| AS-07 authorized results, snippets, component preview and freshness | 2–4 | existing governed `search_rows`; matched-component attribution enriched with authorized preview metadata while retaining safe snippets; preview action reusing `preview_record_components`; index-freshness response | search authorization coverage plus 178 frontend tests including match-only rendering and governed-viewer wiring | verified | Only attributed matching components render; unmatched record components are never added; unsupported/unavailable matches show a disabled preview icon |
| AS-09, AS-22 saved execution freshness and cap | 2 | `POST /api/v1/saved-searches/{id}/execute` | `test_execute_saved_search_uses_fresh_results_and_enforces_stored_cap`; disposable DB run | verified | Runtime may override only page size, offset and authorized debug; stored cap cannot be raised |
| AS-22 unsaved execution cap | Server enforcement | `POST /api/v1/{records,aggregations}/advanced-search` | `test_global_and_advanced_search_caps_keep_browse_available`; authenticated permission tests in `test_full_text_search_phase3.py` | verified | Default 1,000, maximum 5,000, bounded count, shortened final page and rejected out-of-range offset |
| AS-18 page states and accessibility | 2–3 | validation summary, loading spinner, empty/error/partial-index presentations, labelled groups and controls; saved-search dialogs and read-only presentation | helper tests; live keyboard-semantic DOM and desktop visual inspection | verified | Existing logical-layout and responsive conventions are preserved by the Phase 3 controls |
| AS-08, AS-10–AS-13, AS-15–AS-17, AS-19 | 1 | governed saved-search model, APIs, audience rules, policy catalogue and canonical/migration SQL | 36 focused API/security tests plus schema/migration verification | verified | Fresh disposable schema and migration databases were both dropped successfully |
| AS-14 optimistic concurrency UX | 3 | `If-Match` client methods; stale update/delete handling and latest-version reload dialog | API concurrency tests; client header unit test | verified | Winning stored definition is preserved and the client offers an explicit reload |
| §§5.2, 5.4, 5.5, 10 task-first and durable saved-search workspace UX | 3–4 | Desktop Criteria/Saved Search two-column workspace with responsive stacking; workspace-owned category metadata and independent suggestion list; explicit Update saved search action; search-first open dialog; durable workspace snapshot in `frontend/webui/app.py` | 178 frontend tests; arbitrary-category restore, category-authority/commit/update, workspace-layout, deferred-discard-confirmation, and drill-down restoration regression checks | verified | Restored categories are no longer passed as invalid values to an empty hidden select; arbitrary saved category text such as `General` survives save and Back/breadcrumb restoration |
| §9.6 administration filters | 3 | bounded owner, target, audience, name, category, maximum-results and update-date filters in API and UI | focused API filter test; live administration listing inspection | verified | Administrative discovery does not grant execute capability or reveal results |
| §4.3 and AS-23 component catalogue and result contract | 4 | controlled public-to-column catalogue and Records-only compiler path in `backend/services/api/search.py` | all-eight-field typed-operator tests; aggregation/sort/internal-field rejection; saved execution test | verified | Uses ordinary comparison leaves; component fields are filters only and result rows remain records |
| §4.3 and AS-24 same-component Boolean semantics | 4 | authorization-aware correlated component scope in `_compile_expression` | false cross-component trap, nested component-only `or`, independent `or`, complete negation, mixed record/component and record-only-alternative DB tests | verified | One authorized component satisfies predicates within an `and` scope without changing ordinary Boolean meaning when a record-only alternative succeeds |
| §4.3 and AS-25 security, bounds and performance | 4 | bound values, controlled identifiers, existing depth/leaf/operator validation, component sort exclusion, `digital_components_record_id_idx` correlation | hidden-component, injection/internal-field, limit, response-contract and forced-index query-plan tests | verified | Authorization is evaluated inside the correlated existence test before matching/counting |
| §5.3 and AS-26 component builder UX | 4 | grouped Record/Digital component field labels, typed and clearable controls, contextual same-component help, chip-rendered controlled content-status catalogue, sort exclusion and RTL logical-edge CSS in `frontend/webui/app.py` | 176 frontend tests including contextual-help, chip-rendering and controlled-selector regression checks | verified | Component guidance appears only when a component field is present; builder exposes no joins, quantifiers, SQL, component table names or component full-text operation |
| §5.3 governed relationship pickers | 4 | card-style searchable relationship options; classification and organization-unit Browse actions; classification-scheme-to-aggregation hierarchy browser in `frontend/webui/app.py` | 176 frontend tests including hierarchy-path regression checks | verified | Medium has a controlled selector; aggregation selection drills through governed classification and aggregation nodes; selected values remain IDs and can be cleared |

All four original Advanced Search phases are complete. The effective-retention
extension is reconciled separately below.

## Effective-retention extension — 28 October 2026

One phase covers the approved extension's query contract, effective-rule
semantics, implementation, Arabic drafts, and verification. Detailed evidence,
commands, database cleanup, performance measurements, and browser captures are
in [the verification record](verification/effective-retention-search.md).

| Requirement | Implementation evidence | Verification evidence | Status |
| --- | --- | --- | --- |
| §§1–2, AS-ER-01: current governing rule and inheritance | `AGGREGATION_RETENTION_SEARCH_FIELDS`, `_compile_expression`, `_search_from` in `backend/services/api/search.py`; existing `aggregation_effective_retention_rule` | API resolver parity, classification inheritance/change, local override/removal, child reparenting, open/closed and zero-year cases | verified |
| §1, AS-ER-02: typed, bounded aggregation-only filters | Existing comparison compiler plus controlled action and nonnegative integer validation; builder operator catalogue and filter-only sort exclusion | All permitted numeric/action operators, invalid types/values/operators, Boolean/full-text combinations, injection, 50-leaf/five-level/100-value bounds, Records/sort rejection; builder validation tests | verified |
| §3, AS-ER-03: authorization, paging and saved freshness | Existing authorized search views, visibility predicates and schema-version-1 saved-search execution; one optional lateral rule source for count/page | ACL-restricted totals, deterministic page slices, result shape, saved reopen/execution cap and freshness; existing saved-search and terminal-visibility regressions | verified |
| §3, AS-ER-04: bilingual controls and navigation | `frontend/webui/app.py`; five new English definitions and Arabic drafts merged by key with existing Arabic wording/provenance preserved | English/Arabic live browser criteria, action multiselect, numeric range/fraction validation, saved restore, navigation, mutation freshness, pending-request abandonment; catalogue/terminology checks | verified |
| §§3–4, AS-ER-05: performance and traceability | Optional resolver join only for retention predicates, shared source for count/page, no new cache/index/schema/environment setting | Authorized-query `EXPLAIN (ANALYZE, BUFFERS)` on 1,000 aggregations; complete evidence record and this reconciliation | verified |

Arabic additions remain unpublished drafts requiring administrator review.

## Matched-component result presentation

Advanced Search record cards treat component rows as search attribution rather
than as a list of every component attached to the record. Only components
identified by the executed criteria as matches may be rendered. Their safe
highlighted snippets remain visible, and their preview icons invoke the
existing governed component viewer. Authorized component metadata may enrich
those matched rows to determine previewability, but must never introduce an
unmatched component into the result card. A preview request independently
rechecks the caller's current component permissions.

## Phase 1 exit reconciliation

On 25 September 2026, the focused API/security suite completed with **33
passed**. A fresh uniquely named database initialized from `database/schema.sql`
and a separate uniquely named pre-Phase-1 database upgraded through migration
018 both passed verification. Cleanup was checked after the run; no disposable
Advanced Search database remained. No unexplained Phase 1 requirement omission
or implementation behavior was identified.

## Phase 2 exit reconciliation

On 25 September 2026, **35 focused API/security tests** passed against a newly
created disposable canonical-schema database, and the separate pre-Phase-1
database upgraded through migration 018 also passed and was dropped. The
complete frontend unit suite completed with **164 passed**. Live browser verification
confirmed navigation order, labelled controls and groups, client validation,
an executed empty state, responsive layout at 390 pixels, and no browser console
warnings or errors. Phase 3 retains saved-search management experiences and the
final expanded authorization, performance, security, and Arabic/RTL matrix.

## Phase 3 exit reconciliation

On 25 September 2026, **36 focused API/security tests** passed against a newly
created disposable canonical-schema database. The separate pre-Phase-1 database
upgraded through migration 018 also passed, and both databases were dropped by
the test harness. The complete frontend suite completed with **166 passed**.
Live browser verification covered structural-invalid action disabling, private
creation, owner context, accessible discovery, the separate administration
listing, and the unsaved-navigation guard. The browser-rendered workspace used
the established Wathiq cards and controls; no raw table was introduced.

## Phase 4 exit reconciliation

On 25 September 2026, **54 focused API/security/component-search tests** passed
against a newly created disposable canonical-schema database. The separate
pre-Phase-1 database upgraded through migration 018 also passed; both databases
were dropped by the harness. The complete frontend suite completed with **168
passed**. Live browser verification confirmed the separate Record and Digital
component labels, all eight component choices, contextual same-component help,
component-field exclusion from sorting, keyboard-semantic controls, and record
result empty-state behavior. RTL logical-edge rules cover the added indentation,
group boundary and trailing status alignment. No schema or migration change was
required because Phase 4 extends the version-1 controlled query compiler only.

## Authentication-boundary isolation regression

Advanced Search workspace snapshots (criteria, cached results, saved-search
context, and component details) are cleared at sign-out, session expiry, and
successful login through the shared search-session cleanup. The cleanup also
discards the old workspace's navigation guard. A session revision and principal
check prevent callbacks from the previous identity from persisting its snapshot.
Search responses and errors are ignored after identity change or navigation away,
including responses arriving during component-detail loading. This implements
the WebUI performance contract's identity isolation and abandoned-response rules.

`frontend/webui/tests/test_search_session_isolation.py` exercises the actual
cleanup and callback functions with synthetic state: normal persistence, identity
boundary cleanup, stale persistence, and delayed success/error/cancellation.
These tests do not access a database. No translation keys or artifacts changed.

## Saved-search audience guidance and scoped browsing

Section 10 audience selectors reuse the eligibility predicate from AS-10/AS-11
in both type-ahead and browse APIs. The optional `audience` browse scope filters
roots, children and search before pagination; recursive ancestor paths remain
navigable, while `audience_selectable` prevents choosing context-only units.
The shared general organization browser retains its existing scope. No cache,
privilege, schema or migration was added.

`test_saved_audience_tree.py`, `test_browse.py` and `test_saved_searches.py` passed
13 tests against a newly created canonical-schema disposable database, which
was dropped afterward. Coverage includes ordinary/admin scope, hidden siblings,
disabled ancestor metadata, branch paging, matching type-ahead choices, and fresh
results after assignment removal. `test_saved_audience_paging.py` verifies the
selection predicate and propagation of scope through every browse request.

Two contextual keys (`webui.saved_audience.roles_help` and `.units_help`) were
added in English and Arabic. Existing administrator-exported translations and
provenance are preserved; the new Arabic wording is flagged for human review.

The focused frontend/locale run passed 27 tests. Catalogue reference, exact-key,
ordering, blank, placeholder, terminology, source hash and unchanged-existing-
provenance checks passed. No new administrator export was promoted. Live Arabic
UI inspection confirmed note placement, currently using English fallback until
the new drafts are reviewed and published. The local API process still serves
the old browse implementation and requires restart; live scoped-tree and full
LTR/RTL verification remain pending that reload/publication.

## Criteria edits reset pagination

The identity-scoped Advanced Search workspace compares criteria, target, sort
and maximum-result settings with its previous snapshot when persisting changes.
A change resets offset to zero, including invalid intermediate criteria edits;
unchanged criteria preserve ordinary pagination and same-session restoration.
The existing builder callbacks all flow through this persistence boundary.
`test_search_session_isolation.py` passed 15 tests, including later-page edits
to values, operators, group logic, added/removed conditions, full-text queries,
and sorting, followed by normal paging with unchanged criteria. No database or
translation artifacts changed for this fix. Live browser verification remains
pending.

### Unsaved-change confirmation correction (4 November 2026)

Approved clarification to §§5.3–5.4 and AS-05: target changes prompt only for
unsaved edits; untouched defaults and loaded saved searches do not prompt.
The target callback checks baseline dirty state and ignores programmatic,
superseded, and abandoned-view events. Result page size is excluded from dirty
signatures, including normalization of baselines persisted by older processes.
Loading a saved definition clears previous execution results, counts, record
capabilities, expansion, anchor and status, so navigation cannot relabel stale
results with the new target.

Verification: 63 focused automated checks pass in
`test_advanced_search_unsaved_changes.py`, `test_advanced_search_builder.py`,
`test_saved_search_errors.py`, `test_saved_search_localization.py`, and
`test_full_text_search_phase4_ui.py`. These tests do not access a database.
The new callback tests cover clean defaults/saved searches, dirty confirm/cancel,
loading and delayed events, abandoned views, page-size changes, reverted edits,
legacy valid/incomplete baselines, clean navigation, and stale-result clearing.

Live in-app browser verification used separately created disposable PostgreSQL
databases, canonical schema initialization plus separate reference/fixture seeds,
isolated API/UI ports 18030/18083, and temporary UI storage. No persistent ERMS
database was tested or modified. The final fixture contained saved searches for
both targets, nine aggregations and 35 records. English and Arabic catalogues
were available; effective Arabic body/main direction was confirmed as RTL.

| Scenario | Observed result |
| --- | --- |
| Untouched default Records → Aggregations, English and Arabic | Target and blank builder change with no dialog |
| Open unchanged saved search for another target and leave for Dashboard | Completes without a warning; repeated return preserves criteria |
| Switch target on unchanged saved search | No warning; builder resets and stored definition remains available |
| Edit criteria then switch target | Exactly one target confirmation; Cancel restores target and keeps edited criteria |
| Edit criteria then leave | Discard confirmation; Keep editing retains workspace |
| Revert criteria to baseline, English and Arabic | Navigation completes without warning |
| Select another saved search while dirty | Opening picker is silent; selecting replacement prompts; cancellation retains picker/edits; acceptance loads clean baseline |
| Execute saved query and use actual next page, English and Arabic | 1–25 then 26–35 of 35; no false dirty warning on navigation |
| Change page size | No false dirty warning; saved criteria remain clean |
| Save criteria update, navigate and reopen | Updated value is loaded, and no warning on leaving |
| Load another target after execution, navigate away and return | Zero stale result cards; old results are not relabelled |
| Change maximum results or sort direction | Edits are protected; accepted target change produces no second dialog; reverting sort permits navigation |
| Leave during search, then return | Dashboard remains usable; return has an enabled Search control and no false warning |

Screenshots are retained locally in gitignored `.runtime/search-verification/`:
`english-default-switch.jpg`, `arabic-default-switch.jpg`,
`arabic-edited-confirmation.jpg`, and `arabic-clean-saved-switch.jpg`.
No user-visible text or translation artifacts were changed.

Separate existing issues observed, outside this correction: the Arabic discard
message interpolates English action text (for example `leave this page`); and a
saved definition created directly through the API with a bare condition root
cannot be rendered by the group-only builder. Live workflow checks used grouped
roots produced by the WebUI; the API-only fixture was corrected to that shape.
These findings are not claimed fixed by this change.

Both disposable databases were dropped successfully after their runs:
`erms_messaging_test_acl_c9876a9062544d8eb83a7a3b1dd05f62` and
`erms_messaging_test_acl_89bb576ddd814181a117133f5f245227`.
The fixture-owned API/UI processes were stopped by their launcher. The initial
sandboxed database connection was denied before creation; the authorized retry
created the disposable database successfully. No cleanup failures occurred.

### Follow-up: choosing the initial target is setup

The user reported the missing sequence: new Advanced Search → choose
Aggregations → open a saved search. The first correction allowed the target
switch but still compared later actions against the original Records baseline.
The follow-up establishes a clean baseline after a target switch when the
workspace was already clean and no saved search was open. Repeated target
switches therefore remain clean. Actual subsequent criteria edits still warn;
changing an opened saved search's target remains a saved-definition edit.
The specification §5.4 now explicitly states this exception.

The regression test
`test_target_only_setup_then_open_saved_search_is_clean_but_later_edits_warn`
executes the actual target, signature, dirty-state and discard-guard callbacks
in sequence. It covers three target switches, subsequent saved-search opening
and page leaving, then an actual criterion edit. The clean-saved-target test
also asserts that an opened saved search's baseline is not overwritten.

Follow-up verification: all 64 focused checks passed. In a fresh isolated
in-app browser fixture, English and Arabic/RTL both passed the exact sequence:
Advanced Search (Records) → Aggregations → open picker → select saved search.
No discard confirmation appeared, and the saved criteria loaded. English also
passed choosing the target then leaving for Dashboard. Arabic confirmed that
an actual subsequent criterion edit still prompts on saved-search selection.
Evidence: `.runtime/search-verification/english-target-then-saved.jpg` and
`.runtime/search-verification/arabic-target-then-saved.jpg`.
The fixture launcher stopped its API/UI and successfully dropped disposable
`erms_messaging_test_acl_0f48ecb9acab4328b2d2ac8592c0fd25`.

### Follow-up: protect the loaded saved definition on target changes

The latest user clarification supersedes the earlier allowance for switching
an unchanged loaded saved search without confirmation. The active contract in
§§5.3–5.4 and AS-05 now distinguishes two cases: target-only setup for an
untouched new search stays silent; changing the target while any saved search
is open requires confirmation before its loaded criteria are reset. Ordinary
navigation away from an unchanged saved search remains silent.

`change_target` checks both dirty state and the presence of an open saved
search. Acceptance preserves the original saved baseline and context, making
the new definition dirty without updating the stored saved search. Cancellation
restores the target and preserves criteria, results, context and baseline.
The new behavioral regression test exercises both target directions and both
Cancel/Confirm outcomes with the actual target/signature/dirty callbacks.
All 68 focused automated checks pass. Earlier observations in this document
that allowed silent target changes for loaded saved searches are historical
and superseded by this clarification.

Live follow-up verification passed in English and Arabic/RTL: open unchanged
Aggregation saved search → choose Records → one target confirmation. Cancel
preserves `Phase 4` criteria and Aggregations target; leaving after Cancel
reaches Dashboard without warning. Confirm clears the builder while keeping
the saved context; attempting to leave then prompts for unsaved changes.
English reopening restored the original stored `Phase 4` definition. The
untouched new-search target-switch → picker → saved-selection flow was also
rechecked and remained silent. Screenshots:
`.runtime/search-verification/english-saved-target-protected.jpg` and
`.runtime/search-verification/arabic-saved-target-protected.jpg`.
The fixture-owned API/UI stopped successfully and disposable database
`erms_messaging_test_acl_ea4ecae13a6f4465aa8a21ac8365385e` was dropped.

### Follow-up: confirmed target changes detach the saved search

The user's screenshot clarified that confirming a target reset must start a
new search, not leave the previous saved search attached. This supersedes the
previous follow-up's preservation of saved context after confirmation.
`change_target` now sets the selected resource and invokes the existing
`reset_search(clear_metadata=True)` callback. The standard defaults, blank
criteria and clean baseline are established; saved association, name,
category, description, audience and recipient IDs are cleared. The existing
saved-action renderer therefore displays the unsaved-search context and hides
the prior details and saved-only actions. Stored saved definitions are never
updated by this action. Reset also clears execution expansion/capability/anchor
state, results and freshness status. Cancel remains non-destructive.

The specification §§5.3–5.4 reflects this clarified behavior. Callback tests
now execute the actual shared reset implementation and cover both target
directions and confirmation outcomes, metadata/audience/control clearing,
standard defaults, a clean new baseline and later edits becoming dirty.
All 68 focused automated checks pass.

Live panel verification passed in English and Arabic/RTL: load Aggregations
saved search → choose Records → Cancel preserves the criteria and saved panel;
Confirm displays the new unsaved-search context, Save search, and no old name,
Update saved search, Edit metadata, Save as or Delete controls. Leaving and
returning preserves the detached context without a false dirty warning.
English Save search opened blank name/category/description and a private
audience; saving created a third, separate Records search. Reopening the
original still restored Aggregations and its original `Phase 4` criteria.
Arabic also passed reopening the original unchanged.
Evidence: `.runtime/search-verification/english-confirmed-new-search.jpg` and
`.runtime/search-verification/arabic-confirmed-new-search.jpg`.
Fixture API/UI shutdown succeeded, and disposable database
`erms_messaging_test_acl_aa146f72194447d880b9a4ae7ecddf9b` was dropped.
No user-visible wording or maintained translation artifacts changed.

## Shared tab cache extension — 13 November 2026

| Requirement | Implementation | Regression evidence |
| --- | --- | --- |
| One slot across Global, Advanced, saved executions and record/aggregation filters | `search_cache.py`, `search.py`, shared `search_results_cache` primary key | `test_tab_search_cache.py::test_one_slot_shared_across_screens_rebuilds_expired_or_replaced_page` |
| Never read another search type's list | User/session/tab/list IDs plus endpoint/criteria/sort/version/settings fingerprint | `test_fingerprint_blocks_reuse_with_different_criteria_sort_or_endpoint`, copied-tab/login tests |
| Same administrator cap on collection filters | `cached_search_rows`, compact result cap notice | `test_filtered_search_uses_admin_cap_and_rechecks_permissions` |
| Reuse submitted criteria on paging; discard abandoned responses | `advanced_search.py`, `collection_controls.py`, `global_search.py` | `test_search_session_isolation.py`, `test_collection_filter_requests.py` |
| Framework tab identity survives reload, duplicates remain separate | NiceGUI connected `client.tab_id` | `tools/webui_browser_global_search.py` reload and opener-copy assertions, English/Arabic |
| Preserve cache entries and lifecycle during rename | Migration 111, canonical schema and baseline; independent cleanup queries | `test_migration_111_preserves_entries_unlogged_storage_and_login_cascade`, cleanup suite |
| Preserve results and ordered cache; measure actual changed endpoints | Candidate selection, scoring, permissions and sorting in SQL | `test_cached_search_preserves_results_sort_and_scores`; `tools/search_cache_performance.py` called by the mandatory large-fixture runner |

Verification results, failed attempts, timing scope and deployment requirements
are recorded in the [shared-cache verification report](verification/shared-search-cache-2026-11-13.md).
The final large-fixture run passed all 876 requests across Global and shared
Advanced/saved/filter cases (maximum 2.3503 seconds); every valid Next retained
its list ID. The report preserves the exact timing scope, preparation interval,
earlier failures and cleanup rather than treating this as a concurrent-load SLA.
