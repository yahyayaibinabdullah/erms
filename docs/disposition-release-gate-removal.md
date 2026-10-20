# Remove temporary destruction release gates

Status: complete. Approved by the user's 20 October 2026 request:
“Destruction should work once the migrations are applied, subject to the existing
permissions and workflow checks.”

## Implementation

Migration `071_remove_destruction_release_gates.sql` replaces the five affected
private workflow functions, then drops `physical_execution_released()` and
`digital_execution_released()` without CASCADE. It works whether the old gates
were disabled or enabled and changes no job, evidence, settings, grants or content
rows. The canonical schema independently includes the final guarded functions
without either temporary function or its callers. Earlier migrations remain the
historical upgrade path; existing databases must apply 071 before deploying the
matching API/WebUI/worker code.

API physical actions, digital work claiming, completion retry and completion
processing no longer consult release gates. Workspace actions follow current
actor/task eligibility and workflow state; obsolete `released` presentation flags
and release-pending banners are removed. Worker startup requires migration 071.
No replacement toggle, environment variable or application setting is introduced.

All existing command-scope guards, privilege/role and resource access checks,
claims, stages, explicit confirmation, evidence and current approval requirements,
stale versions, holds/security/vital/relationship blockers, physical-before-digital
ordering, protected erasure/finalization and certificate-only recovery remain.

[Operations section 14](operations.md#14-disposition-and-destruction-operations),
the rollout instructions and deployment/database guides now describe the normal
migrated behavior with no manual enablement step. Prior phase reports retain
historical disabled-gate observations; this approved change supersedes that
operational mechanism.

## Verification

Evidence: `docs/verification/disposition-release-gate-removal/`.

- Canonical fresh database: **119 physical/digital/completion/recovery/email and
  full integrated journey cases passed**, without gate fixture overrides.
- Prior committed database plus 071: **25 gate-absence, integrated journey and
  completion/recovery cases passed**.
- **635 WebUI/tool cases passed**, including both language variants of physical
  and digital controls, required confirmation, retry identity and abandonment.
- Fresh plus two populated upgrades through 050–071 passed schema/function/ACL
  parity and exact old data/grant/history preservation, reviewed per-database
  settings, API startup, guarded language seeding and all three worker commands.
  One upgrade starts with both old gates false; the other enables them before
  071. Both finish with the functions absent.
- Fifteen final API policy/catalogue/deprecation/gate-absence checks passed.
- Canonical SQL has no remaining gate calls; the gate-absence test also searches
  installed private function bodies. No test suite ran against demo.

## Translation and deployment handoff

Two obsolete active warning keys were removed from English and Arabic:
`disposition.ui.disposition_physical_release_pending` and
`disposition.ui.disposition_digital_release_pending`. Their exact previous
unreviewed machine-draft rows are retained in the Arabic artifact's
`deprecated_items`; no curated wording/provenance is changed or export promoted.
Both languages now have **3735 active keys**. The remaining **531** existing
machine drafts still need human review. Catalogue/hash/order/placeholder and
approved terminology checks pass. No new environment variables or template
changes are required.

Deploy schema 071 with the matching code and restart API/WebUI and disposition
workers. Applying the migration does not execute destruction or start workers.
Existing approved workflows still require their ordinary authorized user action
and explicit confirmation. Reverting code/settings cannot recover destroyed
content.

## Demo and resource cleanup

Migration 071 was applied to demo after the disposable checks. An independent
verification found both functions and all callers absent; existing workflow
function ownership/permissions/security attributes and business-table counts
were unchanged. Prior definitions were retained privately. No destruction was
performed and no demo workers were started. Restart consumers with the matching
code before use.

All ten databases created for this change were independently confirmed absent;
preview ports and the temporary browser tab were closed. Live English/Arabic
physical confirmations retain required reference, unchecked confirmation and
upload fields. Digital controls are covered in both-language native tests and
the full workflows; no digital action was submitted in the live browser.
One MutationObserver target error was observed at initial preview startup;
task loading, ordinary claiming and both-language dialogs continued to work.
