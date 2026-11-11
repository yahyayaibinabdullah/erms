# WebUI refactor: Phase 6C — shared entity controls

**Status:** Complete for the approved local scope. Final Chrome/Edge comparisons
and independent database cleanup audit passed. Phase 6D has not started.

## Boundary and ownership

This step separates reusable controls while preserving the single-page application.
It introduces no routes, browser-history entries, API/schema changes, wording,
translations, permissions or workflows. No existing feature rule was moved into a
replacement application module.

| Responsibility | Owner | Remaining feature adapter |
| --- | --- | --- |
| Bounded collection reads, request revisions, filter/paging events | `collection_controls.py` | Host supplies current resource/query, page settings, row acceptance, rendering and connection status |
| Selected-ID, ancestor and closure lookups | `collection_hydration.py` | `decorate_for_spec` retains each entity's display rules |
| Bounded relationship selectors, selected values, disabled choices and late-response handling | `entity_selectors.py` | Callers retain their eligibility, filtering and destination rules |
| Existing field controls, required-value validation and value conversion | `entity_editor_controls.py` | Registry field definitions and feature-specific form/save rules stay with their feature |
| Translation language, loaded baseline, version and pending changes | `entity_translation_editor.py` | Host decides eligibility/fields and supplies a shared profile change-reason control when required |
| Number suggestions and duplicate feedback | `resource_number_controls.py` | Resource editors retain placement context, validation and writes |
| Favourites and recent activity | `personal_resources.py` | One state owner per root-page client; existing Dashboard refresh and identity cleanup update that owner |
| Personal-resource panels and compact result presentation | `personal_resource_views.py`, `compact_resource_view.py` | Host supplies existing record, aggregation, preview and rendering callbacks |

The modules import no `app.py` and receive no whole application-state dictionary.
There is no new cache, timer or request. Favourites/recent values retain their
existing response-driven freshness. Selector revisions belong to individual
controls; the collection revision belongs to one page's loader; translation state
belongs to one dialog.

`open_editor` still owns feature permissions, field selection, business validation,
writes and post-save refresh rules. `render_table` still owns entity cards/actions.
`select_entity` retains shell/navigation order and deferred personal-section
refresh. Resource-specific result filters, pages, expansion and return anchors
remain in `render_entity_compact_results`. These adapters move with classification
(6D), security (6E), organization (6G), aggregations (6M), records (6N), search
(6Q/6R) and Dashboard (6S), as already approved.

## Requirement → implementation → verification

| Preserved contract and consumers | Verification |
| --- | --- |
| Profiles, security levels, users, roles and organization units: filters, sort, bounds, paging, accepted-save refresh | Existing request-schema and 49 editor-save cases use the real loader; real API create/update/translation cases; Chrome/Edge list, empty-state and editor journeys |
| Record/aggregation search, clear, late responses, component decoration and return state | Existing race/reset and localization tests, unchanged feature call sites, compact-resource/browser parent-navigation checks |
| Selected relationship values, bounded queries, disabled choices and abandoned requests | New before/after behavioral cases; 94 focused interactions through Settings, notifications, messaging, capture and background collection rendering |
| Classification and organization selectors, security/ACL/hold/search callers | Existing full unit/interaction suites, assembled destination checks and unchanged caller argument mappings recorded in the dependency inventory |
| All seven existing translatable entity kinds, canonical and translation-only saves, profile shared reason | Existing permission/save/version/error tests retargeted to the owner; three real-control interaction cases; real-API profile/unit/level creation, update and Arabic translation saves |
| Number conflicts, failed suggestions and changed placement/drafts | Four real-control interaction cases pass against the original functions and the extracted owner |
| Favourites/recent data across Dashboard, resource landings, searches, details and aggregation browse; identity cleanup | Before/after rollback, acceptance, identity/destination and activity-subset cases; Dashboard identity/cache tests; aggregation navigation tests; real favourite mutations and returns |
| Shared compact results for resource, global and advanced search, including component preview callbacks | Same renderer body, retained source contracts and complete unit/interaction suites; browser record results and parent links |
| English/Arabic layout, focus, navigation and request behavior | 36 before/after scenes per browser; native Tab checks in all five administration editors; strict request and existing-error comparisons |

The saved dependency map lists every pre-move call site and direct personal-state
reader/writer. It includes Dashboard's response/removal updates, resource personal
panels, aggregation browse, entry refresh and identity cleanup. Tests that previously
compiled host functions now invoke the extracted controls; partial host fixtures
receive the same explicit personal-state owner. Assertions were retained and
retargeted, not dropped.

## Baseline findings and test preparation

The untouched application emits `TypeError: u.match is not a function` when drawing
administration pagination. Next/Last use the Boolean `icon-right` prop, while
Quasar's icon renderer expects a string. Each list entry renders twice and produces
four such errors. Both original browsers reproduce this for all five lists in both
languages. The harness asserts exactly that signature/count per list and rejects
any other errors. This existing defect is preserved; a product fix needs separate
approval.

Initial harness corrections covered releasing the Command key when clearing text,
waiting for the previous list to be replaced, and re-adding the favourite removed
on the second language pass. The original checks and failures are retained.

The first visual comparison identified only run-time timestamps on profile, user
and organization-unit cards. The final fixture fixes those synthetic dates inside
the runner-owned database. Its profile timestamp trigger is disabled and restored
within one setup transaction; all application requests use normal triggers and
validation. No production schema or persistent database setting changes.

A further comparison exposed a blinking input caret and selector focus styling
while the menu's bounded load was settling. Keyboard observations now wait for
that update; screenshots then use ordinary clicks on non-interactive headings
or empty-state content to remove transient caret/selection focus. No styling is
hidden or overridden, and no pixels below the animated header are masked.

The added real-save tests also needed to account for existing invisible inspector
and bidirectional text markers, the actual PATCH endpoints, and a security-level
fixture below the existing maximum. The initial higher-level fixture received a
409; server validation was not changed. The corrected cases pass on the original
application as well as the extracted one.

Original application reruns load the captured pre-6C host in a separate disposable
process without replacing working files. `baseline-overlay.json` identifies that
snapshot and its hash; ordinary source manifests still describe on-disk files.

## Verification results

| Check | Result |
| --- | --- |
| Pre-move full unit / interaction baseline | 1,563 / 210 passed |
| Additional shared-control behavior baseline and extracted cases | 13 passed before and after |
| Number-control baseline and extracted interactions | 4 passed before and after |
| Final full unit suite | 1,576 passed |
| Final full interaction suite | 217 passed |
| Expanded assembled real-root / real-API suite | 46 passed on original and extracted application |
| Initial extracted Chrome/Edge journeys | Both passed, 14 check groups per browser |
| Final fixed-date Chrome/Edge journeys and pixel comparison | Original and extracted runs each passed all 14 groups; all 36 screenshots per browser match exactly below the animated header; keyboard focus and application request counts match |
| Test-runner safety/privacy checks | 23 passed |
| Translation artifacts | All 4,071 keys ordered/matched; placeholders, blanks, active references, artifact hashes and provenance preserved; 966 contextual uses of 35 glossary mappings checked |
| Environment authority / API template consistency | Passed; no environment templates or values changed |
| Disposable database cleanup | All 26 unique disposable databases dropped; independent PostgreSQL catalogue audit confirms none remain |

The successful full suites have no failures, errors or skips. The original-snapshot
pytest wrappers report an import-rewrite warning because their setup imports
NiceGUI before pytest; their assertions and tests pass.

The final browser comparisons exclude only the top 72 pixels containing the
animated header. Request comparisons exclude the existing background message
catch-up and unread-count polling; all other method/path/query/status counts
match. The 58 source and harness hashes captured for each final extracted run
still match the working files. The saved comparisons, screenshots, focus records,
request logs and cleanup audit are in the evidence directory below.

Source verification confirms 25 moved functions are identical after the documented
state/accessor substitutions, and 116 retained direct host functions are unchanged
under that same normalization. The translation editor's complete body is identical
after explicit parameter substitution. Entity decoration branches and every styling
literal are unchanged. Only `app.py` changed among pre-existing runtime files;
all other runtime modules, assets and catalogue bytes are unchanged, including 6A
and 6B. The collection loader's behavioral tests cover the new narrow adapters.

Evidence is under `docs/verification/webui-refactor-phase6c/`; raw runs and the
original snapshot remain under gitignored `.runtime/webui-refactor-phase6c/`.
All work stays local and uncommitted on `refactor-API-python-file`. Firefox, Safari
and CI remain deferred. Safari and MailDev were not changed. Stop for approval
before Phase 6D.
