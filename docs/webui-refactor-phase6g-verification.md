# WebUI refactor: Phase 6G — Organization workspace

**Status:** Complete for the approved local scope.

## Scope and ownership

Units, roles, users, memberships, deletion and the organization browser now have
separate modules. Organization editor rules, list hydration, legacy table actions
and shared avatars also have explicit owners. Existing security-level/profile
cards share `administration_cards.py`; this supporting move avoids duplicating
their presentation when extracting organization lists.

No feature imports `app.py` or receives its shared state dictionary. The host
supplies explicit navigation, shell, identity, direction and refresh callbacks.
The User Details view token now belongs to its per-client factory. Its existing
identity, page and token checks still reject abandoned responses. Tree expansion,
selection, branch counts and scroll state retain their existing session-storage
format and SessionContext cleanup. Collection pages remain the existing narrow
navigation-restored map. No cache, request, timer, URL or history change is added.

## Requirement-to-verification map

| Preserved behavior / connected callers | Owner and evidence |
| --- | --- |
| Unit details, inherited status, designated roles, ownership and permanent deletion | `organization_units.py`, `organization_deletion.py`; original/extracted real-API lifecycle, designation-preserving edit and deletion cases; browser details/edit/cancel; exact view reconstruction |
| Role details, protected roles, profile privileges, security clearance and sensitive-change reasons | `organization_roles.py`, `organization_editor.py`; retained rule/source tests, shared-editor reconstruction, EN/AR role detail/edit/focus and membership journeys |
| User details, status/password actions, role assignments, service-account redirects and embedded session paging | `organization_users.py`; complete original function reconstruction, identity checks retained, assembled membership write/removal and all drawer checks; browser user detail/editor/empty membership view |
| User/role membership selection, validity/status filtering, paging, writes and errors | `organization_memberships.py`; nine new original dialog tests, existing pure filters, assembled real-API assign/remove, browser tables/dialogs in both directions |
| Organization tree, branch paging, permissions, selectors, recipient/audience consumers and saved state | `organization_browser.py`; 17 existing interaction cases retargeted without removing assertions; saved-audience scope checks; EN/AR browser expansion and navigation restoration |
| Bounded unit/role/user list hydration, localized values and inherited inactivity | `organization_collections.py`; original projection branches identical; collection filter/save tests and browser requests |
| Shared organization/security administration cards, filters and empty states | `administration_cards.py`; entire original body reconstructed; full suites and all shared-card browser consumers |
| Remaining legacy table slots and actions | `organization_table.py`, `organization_collection_actions.py`; original conditionals/action bodies preserved; source-contract checks retained |
| Audit, security, Settings, records, aggregations, capture, messaging and search consumers | Explicit callbacks remain connected; 108 other direct host functions unchanged; full unit/interaction/assembled suites and connected resource journeys |

## Verification

| Check | Result |
| --- | --- |
| New dialog baseline | 9 passed against original |
| Extracted tree/dialog focused checks | 26 passed |
| Retargeted unit and interaction checks | 208 passed; further affected tests 17 passed after fixture/source-location corrections |
| New original real-API workflows | 4 passed: assignment/removal, inherited lifecycle, deletion and designation-preserving edit |
| Full final unit suite | 1,603 passed |
| Full final interaction suite | 264 passed |
| Full final assembled suite | 55 passed |
| Original/extracted organization Chrome and Edge | Each passed all 10 groups in EN/AR; 24 scenes per browser |
| Organization browser comparison | Focus and request counts identical; 45/48 scenes exact below the animated header; three differ only in a few selector-edge/icon anti-alias pixels |
| Shared-card Chrome/Edge consumer comparison | 14 groups and 36 scenes per browser/version pass; all 72 scenes exact below header, focus identical; settled Edge rerun confirms equal request counts |
| Source preservation | Six views, seven pure helpers, three projection branches and retained table actions checked; shared-card body and complete shared editor reconstructed; styling/message literals preserved |
| Translation/configuration/runner checks | 4,071 artifact keys and bytes unchanged; reference/terminology checks pass; configuration authority and templates agree; 23 runner safety checks pass |
| Disposable databases | All 21 uniquely named databases dropped; independent PostgreSQL catalogue audit passed |

The organization screenshot comparison excludes the animated top 72 pixels.
The three remaining differences contain 25, 25 and 91 pixels, with a maximum
colour-channel difference of 6/255, at rounded selector borders and circular link
icons. Text and every other pixel match. The reviewed regions and original images
are retained. Request comparisons omit only existing message catch-up/unread polling.

The initial shared-card Edge comparison differed by two record-component requests.
The test clicked the parent link before the existing component section completed.
The original English run cancelled those requests; both versions completed them
in Arabic. Both source functions are unchanged. Waiting for the existing component
empty state before leaving gives equal requests, focus and all 36 screenshots in
a fresh original/extracted Edge pair. This changes only test readiness.

## Findings and test corrections

Browser selectors now distinguish the main Quasar header from semantic headers
inside role details, inspect action icons within labeled buttons, wait for the
tree disclosure to load, and preserve an already-expanded branch. Membership
valid-from timestamps are fixed only in each disposable fixture for comparison.
No application behavior changed to accommodate these checks.

The simulated membership removal uses NiceGUI's existing listener-event format.
The designation test selects the canonical Name field, separately from the
translation field, using the established diagnostic/bidi label normalizer.
Shared-editor test fixtures now supply the moved organization reason helper and
its existing form context. Source-location assertions follow the new owners;
their behavior requirements were retained.

The pre-existing Boolean `icon-right` pagination errors remain strictly counted
and separately recorded. No product defect was fixed. Firefox, Safari and CI
remain deferred; Safari, MailDev and persistent databases are untouched.

All changes remain local and uncommitted on `refactor-API-python-file`.
Evidence: `docs/verification/webui-refactor-phase6g/`; original snapshots and raw
intermediate failures: `.runtime/webui-refactor-phase6g/`. No translation or
operator configuration action is required.
