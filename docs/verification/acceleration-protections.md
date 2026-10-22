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
