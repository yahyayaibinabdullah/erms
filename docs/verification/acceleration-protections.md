# Accelerated eligibility and independent protections

Approved correction, 22 October 2026. Implements Disposition §7, §9, §11 and
DISP-13, and the common eligibility contract referenced by Destruction §2.
This supersedes the historical Phase 9 rule that admission protections also
rejected acceleration.

## Required behavior and implementation

`database/schema.sql` and migration
`database/migrations/077_acceleration_eligibility_protections.sql` implement the
same acceleration and held-resource guard definitions. Acceleration retains
current locking, authorization, reason, effective-rule, version, root and
active-job checks. It does not consult admission blockers to decide eligibility.
The hold guard permits only a protected command's status/version-only change
from not ready to an eligible status. Ordinary metadata changes and closure
still pass the existing guards. Admission and physical/digital execution gates
are unchanged.

| Scenario | Result | Verification in `backend/services/api/tests/test_disposition_membership.py` |
| --- | --- | --- |
| Closed root, vital root/descendant/record, or blocking security | Accelerates to the effective outcome; admission remains blocked | `test_current_protections_allow_acceleration_but_reject_admission` |
| Closed root under direct, inherited or record hold, normal or preserve-state | Same result, with unchanged closure and hold assignments; retry does not duplicate the event | Same test, across all four disposition outcomes (40 cases) |
| Open root under a normal hold | Closes and becomes eligible; hold still blocks admission | `test_acceleration_keeps_open_held_root_closure_rules` |
| Open root under a preserve-state hold that prohibits closure | Closure and eligibility roll back; no successful acceleration event | Same test |
| Open vital/security-protected unit | Closes and becomes eligible but cannot enter a job | `test_open_protected_unit_closes_and_accelerates_but_cannot_enter_job` |
| Hold removed after acceleration | Eligibility remains; no automatic admission; explicit admission succeeds after fresh checks | `test_removing_normal_hold_preserves_acceleration_without_automatic_admission` |
| Unrelated metadata edited within acceleration command | Rejected by the ordinary preserve-state hold guard | `test_held_acceleration_does_not_allow_metadata_edits_in_its_command_context` |
| Open held root, no close permission | No closure, version or status change | `test_open_held_acceleration_still_requires_close_permission` |
| Held-root API call without reason/version, stale version, or repeated command | Required-input/stale rejection; successful retry returns the saved result exactly once | `test_acceleration_api_keeps_reason_version_and_retry_contract_for_held_unit` |
| Failure after closure but before eligibility completes | Closure, status, versions and events all roll back | `test_acceleration_failure_after_closure_rolls_back_entire_unit` |

The existing eligibility tests verify that scheduled expiry also permits
protected units to become eligible. Existing membership edge tests cover
current locking, concurrency and recalculation. Physical and digital execution
tests continue to reject current holds, vital designations, security changes
and protections committed while execution waits for locks.

## Verification results

All database-backed tests used newly created, uniquely named disposable
PostgreSQL databases, never `demo`. Every database and the browser preview were
dropped after completion.

- Fresh canonical schema: **194 passed**, covering membership, membership edges,
  eligibility and localization catalogue tests.
- Committed pre-077 schema plus migration 077: **57 passed** acceleration and
  protection cases, including closure, reason, version, retry and API behavior.
- Physical/digital execution protection regressions: **13 passed**.
- WebUI disposition screen tests: **25 passed**.
- Compilation, `git diff --check` and API environment template check passed.
  No environment settings or templates changed.
- Live in-app browser: revised confirmation inspected in English/LTR and
  Arabic/RTL on an isolated preview. Only the revised Arabic confirmation was
  reviewed/published in that disposable preview; it remains a draft in the
  maintained source artifact. No persistent translations were published.

The only changed translation key is `disposition.ui.accelerate_scope`.
The existing generated draft was explicitly invalidated for the new meaning;
its prior wording is retained in `superseded_translations`. Other maintained
wording and provenance were preserved. Coverage/order and catalogue,
specification and terminology hashes pass. The revised Arabic key passes full
generator validation. The full artifact retains the same **12 pre-existing
strict generator warnings** as the committed artifact, including curated vital
terminology and `Re:`; this correction does not replace those unrelated values.
The broader historical disposition ledger also predates several earlier
specification amendments; this report provides the direct traceability for the
current correction without certifying those unrelated pending amendments.

## Existing database rollout

Apply 072 if missing, then 077. New databases use `database/schema.sql` alone.
On 22 October 2026, both missing prerequisite 072 and migration 077 were applied
to `demo`. These migrations replaced functions and recorded receipts; they did
not accelerate, close, dispose of or change protections on any existing resource.
The revised source definition was synchronized, preserving existing Arabic
wording for administrator review. API source synchronization marks a changed
translation for review; generated Arabic wording requires explicit review and
publication. The independent acceleration-notification follow-up in the
implementation plan remains separately pending.

## Retention-section acceleration provenance (22 October 2026)

Approved follow-up: distinguish accelerated eligibility from the normal
retention due date in the aggregation overview (Disposition §11).

- `classification_management.effective_aggregation_rule` adds a nullable
  `acceleration` object (event ID, timestamp, actor snapshot and reason) to the
  existing authorized response. It reads the latest relevant event for one
  governing root using the existing entity-timeline index. No new request,
  collection download, cache, schema change or history rewrite is introduced.
- A later reopening or changed-rule recalculation suppresses the old marker;
  unchanged-rule recalculations preserve it. Current status remains independent
  of the provenance, including pending/completed job states. Hidden root
  provenance is not returned to a descendant reader.
- `retention_timeline.render_disposition_date` shows the acceleration, current
  status and the unchanged normal due date; actor/reason use plain text labels.
  It reuses `detail-action-row`. Browser inspection of the existing global RTL
  `.row` rule found `row-reverse` double-reversed native RTL flow. This existing
  Wathiq class restores `row` without adding custom CSS or Quasar components.
- `test_retention_acceleration_display.py`: 8 passing API regressions, covering
  all four outcomes, root/descendants, actor snapshot preservation, repeated
  reads after mutations, reopening, rule changes, later natural eligibility,
  admission/removal, re-acceleration and unauthorized access. The existing
  classification-management and localization-catalogue suites added 35 passing
  compatibility checks. All database tests ran in newly created disposable
  databases which were dropped, including failed development runs.
- `test_retention_timeline.py` and `test_rtl.py`: 27 passing checks, including
  both languages, statuses 2–6 and 10, literal actor/reason text, unchanged normal
  dates and ordinary non-accelerated presentation.
- An isolated NiceGUI preview using the real Wathiq stylesheet and direction
  helper was inspected in the in-app browser: English/LTR, Arabic/RTL, ordinary
  retention, navigation back to accelerated details and repeated refresh. Four
  component rows have computed `direction: rtl; flex-direction: row` in Arabic.
  The preview performs no API requests and changes no persistent data.
- A strictly read-only demo lookup confirmed event 141244 for
  `1141/DEMO/001/2026`: 22 October 2026 09:33 Asia/Dubai, actor Yahya Yai Abdullah,
  reason “For testing purposes”, with unchanged two-plus-three-year retention.

Five keys were added under `webui.open_aggregation.retention`:
`accelerated_on`, `accelerated_by`, `acceleration_reason`, `acceleration_effect`,
`normal_disposition_date`. English and Arabic key ordering, coverage,
placeholders, nonblank content and catalogue hash pass. All prior Arabic item
wording/provenance is byte-for-byte equivalent after JSON parsing; no new
administrator export was promoted. The five new Arabic entries pass strict
terminology/quality checks and were stored in demo as unreviewed drafts only.
The full strict Arabic validator still reports the identical pre-existing
baseline warnings documented above; this change adds no new warnings.

Development logs are in `.runtime/retention-acceleration/`. An intermediate
invalid placeholder type was caught by the tests and the running WebUI's
reload; it was corrected to the catalogue's supported `text` type. The managed
local stack was restarted after validation to restore the development WebUI
and activate the completed API/WebUI change.

## Eligibility table follow-up (22 October 2026)

The approved table presentation now uses **Normal retention due date**, an
**Accelerated · [date]** badge with actor/reason tooltip, and **Remaining
retention period waived** instead of days overdue for accelerated rows. The
redundant action subtitle is removed for every disposition status. Ordinary
rows still show days overdue; normal-date filtering/sorting, selection and
blockers retain their existing behavior.

`disposition/acceleration.py::current_accelerations` centralizes the same
current-episode history lookup used by both the details endpoint and
`queries.eligibility`. Eligibility first obtains its bounded server page and
then enriches only its visible root IDs in one SQL query. No per-row HTTP
request, whole-result history scan, cache or migration was added. The table
continues to use the existing Wathiq PageTable and supported NiceGUI table
slots; the badge uses the same slot mechanism as the existing tooltips.

Verification:

- `test_disposition_queries.py` covers current-page-only batch arguments,
  unchanged normal dates/overdue values, ordinary versus accelerated rows,
  invalidation, hidden-root provenance redaction, pagination and existing
  authorization/admission behavior. Its translation-quality fixture now sets
  an actual unresolved quality flag rather than depending on canonical draft
  wording retaining one; an acknowledged human-review marker alone is allowed
  by the existing publication contract.
- The shared details provenance regressions remain in
  `test_retention_acceleration_display.py`.
- `test_disposition_screens.py` and `test_retention_timeline.py`: 52 passing UI
  tests, including English/Arabic date formatting in the working timezone,
  removal of the redundant subtitle, tooltip data as literal text, fresh data
  after invalidation, two initial page requests only, and abandoned-response
  protection from the existing PageTable suite.
- In-app browser: the real eligibility screen with Wathiq's actual stylesheet
  and RTL helper was compared with its established table styling. English and
  Arabic badges, actor/reason tooltips, separate blockers, ordinary overdue
  counts and Refresh were verified. No new CSS overrides were introduced.
- Two new keys, `disposition.ui.accelerated_badge` and
  `disposition.ui.retention_wait_waived`, have matching English and Arabic
  entries. Existing due-date/actor/reason labels are reused. Coverage, ordering,
  placeholders, nonblank text, new-key terminology and catalogue hash pass;
  every prior Arabic entry and provenance remains unchanged. Both new entries
  were stored as drafts in demo, with no publication or administrator export
  promotion. Full-artifact pre-existing warnings remain as documented above.

Logs and the isolated database-free browser preview are under
`.runtime/eligibility-acceleration/`.

Final API run: **21 passed** across the query and shared provenance suites.
Every disposable test database, including failed development runs, was dropped.
Local API and WebUI health checks both returned HTTP 200 after auto-reload.

## Eligibility admission cues and active-job filter (22 October 2026)

- Reused the existing Wathiq PageTable body slot and standard amber utility
  classes; no custom CSS, opacity changes, extra request or cache was added.
- Blocked and active-job rows have amber backgrounds and focusable, accessible
  locks with reasons. Authorized Open, blockers and job buttons stay enabled.
  Combined reasons and redacted rows are covered by the UI regression.
- `active_job=false` is the API and first-visit UI default. Explicit `true` and
  `all` filter before counts and pagination. Active-job pending roots are now
  included when requested; removed memberships no longer count.
- `test_active_job_filter_includes_pending_roots_and_excludes_removed_memberships`
  checks membership changes, paging, HTTP defaults, all/true and invalid input.
  The full disposition query module passed 14 tests in disposable database
  `erms_messaging_test_acl_e4ee346d764246ae81f0d52f24a15026`, which was dropped.
- The disposition UI module passed 27 tests, including EN/AR default filter,
  explicit all encoding, refresh, combined blockers/job reasons and redaction.
- In-app browser verification used the real screen and Wathiq stylesheet with
  database-free fixtures. Confirmed English/Arabic default excludes active jobs,
  explicit active-job filtering, combined listing, pale backgrounds, readable
  text, mirrored RTL layout, and unchanged enabled details buttons. Preview
  was isolated from demo; its process and tab were cleaned up.
- Added only `disposition.ui.in_active_job` and `disposition.ui.no_active_job`
  to both catalogues. New Arabic values pass strict validation and were stored
  as unreviewed drafts in demo. No administrator export was promoted; existing
  artifact wording/provenance was preserved. Coverage, ordering and hash checks
  pass. Full Arabic validation still reports the same 12 pre-existing issues
  documented above; none were introduced by these two keys.
- Logs: `.runtime/eligibility-acceleration/api-job-filter.log` and
  `.runtime/eligibility-acceleration/ui-job-filter.log`.

### Eligibility owning-unit localization

The eligibility API now resolves the owning organization's name using the
requesting user's preferred entity language and the shared `localized_projection`
fallback rules. Translations come from the existing joined organization row;
there is no per-row lookup, new cache, catalogue key, or data rewrite. The raw
translation map is removed before returning the response, and hidden rows keep
the existing redaction behavior. Existing owner ordering remains unchanged.

Read-only verification in demo confirmed Records Management Department has
Arabic name `إدارة الوثائق` and Records Unit has `وحدة الوثائق`.
`test_eligibility_owner_uses_preferred_entity_translation_and_fallback` covers
Arabic, regional-language fallback, English fallback, HTTP preference changes,
and exclusion of the raw translation map. Database tests use a disposable
schema, never demo. Log: `.runtime/eligibility-acceleration/owner-localization.log`.

### Acceleration actor localization

The shared bounded provenance query joins user translations once and applies
the existing entity-language resolver. Details and eligibility pass the viewer's
preferred language; no per-row request or cache is added. The response omits
the raw translations and actor identifier. Missing translations/users fall back
to the immutable event name, never a subsequently renamed canonical user name.
The API regression covers Arabic on both endpoints, switching back to English,
missing Arabic, and unchanged audit history. No catalogue text or database
content is changed. Log: `.runtime/eligibility-acceleration/actor-localization.log`.
