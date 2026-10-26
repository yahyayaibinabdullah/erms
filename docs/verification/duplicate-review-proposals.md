# Duplicate review proposals

Destruction-process section 5.3 requires one active proposal per equivalent
normalized effect in a job/review round. Migration 085 and the canonical schema
install a private semantic-key function and a BEFORE trigger ordered after the
existing authorization/fact guard. The existing command transaction lock and
serializable API transaction behavior protect concurrent saves. An active-round
index bounds comparisons to the job and round. No entity, state, privilege,
cache, environment variable, or resource mutation is introduced.

Removal keys identify an exact relationship independently of its chosen
endpoint. Creation keys use canonical relationship direction and symmetric-type
rules. Hold sets are sorted/deduplicated, reasons/authors are ignored, and blank
retention instructions normalize consistently. Revisions exclude themselves;
withdrawn/executed proposals and other rounds do not block new effects. Different
desired values retain the existing final-approval conflict checks. Failed saves
roll back the complete batch and history; exact command retries remain valid.

The task-scoped removal-candidates endpoint uses current claim/access/scope gates,
true pagination and selected-ID hydration. It annotates only relationships on
the requested page. It exposes an existing proposal reference only where its
target is readable; the details lookup uses the ordinary redacted projection.
The picker disables existing removals and restricted endpoints separately,
includes current unsaved removals, and filters both individual and page-wide
selection. Existing proposals can be inspected without exposing hidden facts.
No tenant-wide collection or client proposal list is downloaded.

The picker reuses Wathiq PageTable styling. NiceGUI exposes table selection and
supported scoped slots, but no per-row selectable callback; body/header
selection slots apply row eligibility and a page-local bulk-selection callback.
No CSS fallback is used. All action icons retain localized tooltips.

Upgrade preserves existing proposal rows, authors and immutable history. It does
not silently remove legacy duplicates. Operators should inspect duplicate groups
in active rounds and have an authorized reviewer withdraw redundant proposals.
New saves must not introduce or revise an active effect into a duplicate group.

Seven disposition.ui keys are added: disposition_proposal_duplicate,
removal_already_proposed, removal_access_required, removal_availability,
select_available_relationships, view_existing_proposal and removal_unavailable.
Arabic values are generated drafts for administrator review; curated entries
and provenance are preserved, and no administrator export is promoted.

## Verification — 26 October 2026

- The complete proposal/review/approval run passed 86 tests. Focused duplicate
  tests additionally passed both read-committed and serializable concurrency,
  normalized effects for all eight types, self-revision, withdrawal, whole-batch
  rollback, idempotent retry, cross-reviewer rejection and occupied migration
  preservation (14 focused cases). A separate HTTP test passed the 409 duplicate
  response and verified the saved proposal remained unchanged.
- 168 English/Arabic task/screen tests passed, including page-wide eligible-only
  selection, individual disabled rows, existing-proposal inspection and retained
  drafts. Superseded tests accepting duplicate proposals now verify rejection at
  Save, while distinct conflicting values retain final-approval checks.
- The live production-component preview reused Wathiq table styling and action
  tooltips. English and Arabic checkboxes disabled saved/restricted removals;
  page-wide selection checked only the available row, and the existing-proposal
  action opened the permitted partial details. A browser-observed selection-slot
  wrapper/initial-header issue was fixed using supported Quasar selection scopes
  without CSS overrides. Selection refreshes use current-page availability.
- All disposable test databases were dropped. Migration 085 applied to demo,
  preserving both task rows and both proposal rows. It found zero legacy
  duplicate groups. A read-only projection as Nad returned two already-proposed
  removals, zero selectable rows, two permitted proposal links, and concealed
  related identities.
- Catalogue references, language coverage/order, approved Arabic terminology,
  environment templates, Python compilation and git whitespace checks passed.
  Missing-only seeding stored seven Arabic drafts with zero corrections,
  failures or awaiting-generation entries, preserving 3,889 existing
  translations. Drafts were not published.

| Requirement | Implementation | Evidence |
| --- | --- | --- |
| Save rejects equivalent active effects across reviewers | private duplicate key/trigger in schema and migration 085 | test_equivalent_effect_is_rejected_at_save_without_history_changes; cross-reviewer and HTTP cases |
| Restricted and already-proposed relationships cannot be selected | task removal-candidates projection; ReviewForm selection slots/accept guard | removal-picker UI test and English/Arabic browser checks |
| Existing proposal can be inspected under normal redaction | proposal_id filter and existing-proposal action | picker link UI/API cases |
| Concurrency and upgrades preserve work/history | existing transaction locks plus duplicate trigger; additive migration | concurrent saves, atomic batch, idempotent retry and occupied-upgrade tests |
