# Phase 17 — external requests and decisions

Approved destruction jobs now generate an immutable Request for Destruction
Form and receive the external authority's approval or rejection with its
required governed letter. External rejection returns the assigned preparer to
correction and repeats the saved review route. Prior requests, decisions,
letters and executed proposals remain historical.

## Requirement-to-implementation-to-test traceability

| Approved requirements | Implementation and verification |
| --- | --- |
| Destruction §§10.1, 11–11.3; DEST-07 | `external.generate_request` freezes post-execution remaining membership, terminal classification, effective rule including local source/instructions, nested counts/media, actual job/assignee/authority and review summaries. Removed units are excluded. Existing controlled Word/PDF pipeline retains template revision, checksum, round and source snapshot. Tests cover all routes, local/classification grouping, removal, 2,000 roots, renderer failure and changed facts during rendering. Actual Standard, Simplified and Manager Only PDFs were inspected; a 120-group, 42-page request retains the final group. |
| Destruction §§5.5, 6.6, 12, 12.2, 18.6; DISP-33; DEST-08, 25 | Migration 062 protects received decisions and request-task linkage. Number, governed approval letter, decision, task completion and audit commit atomically. Free-format numbers retain exact characters/spaces, with 1–20 characters and permanent cross-job reservations, including after termination. Current task/person/role/version/document authorization is checked. Retry and simultaneous submissions have one winner without duplicate letters or claims. Live Standard saves an exact 20-character number; Manager Only uses its actual Manager role. |
| Destruction §12.1; DEST-30, 40 | Rejection requires authority notes and its letter in the same transaction, records actual actor/role/request/round and creates one correction task. Saved Standard/Simplified/Manager Only routes repeat; new approval generates a new immutable form without executing old proposals again. Tests cover all routes and repeated retries; live Standard repeats Officer → File Administrator → Unit Manager → Records Manager → new request → external approval. |
| Destruction §12 and approved-fact invalidation | Immutable semantic facts distinguish changed membership/retention/approved content from independent protective blockers. Stale approved facts prevent request use and permit the authorized preparer/Manager to return for complete renewed review. Vital/security/hold/link blockers preserve approval history for later final-action checks. Legacy approvals without semantic snapshots fail closed on their original versions. Tests verify stale facts, current blockers, rendering races, timezone independence and retained request bytes after authority-setting changes. |
| DISP-41; DEST-16, 32, 33, 38, 39; Destruction §18.13 | Reuses governed upload, configured current destinations, record/component authorization, version history and controlled bilingual Changa templates. Hidden letter/request evidence redacts decision rows and event snapshots. SQL bypass/immutability and rollback tests cover decision/task/number protection. Shared event labels render existing operation codes readably in both languages; existing job event links apply. |
| UI, performance and translation contracts | Native NiceGUI forms, explicit required-field/conflict/success toasts, preserved failed inputs/files and busy guards; bounded sortable lazy Wathiq PageTable history with readable request/letter names. No new data cache or unbounded catalogue reads. English/Arabic component tests and LTR/RTL live checks cover task-specific actions, destination/letter upload, history and refreshed state. All 3,560 prior Arabic items are preserved; 37 new contextual drafts require human review. |

## Verification

Evidence is in `docs/verification/disposition-phase-17/`. Runs overlap and
must not be added as unique test totals.

- Final HEAD → migration 062 acceptance: **45 passed**; disposable DB dropped.
- Canonical external request/decision acceptance: **23 passed** before the
  additional final cases; large real PDF pagination separately passed.
- Earlier broad upgrade regression: **188 passed**, with two legacy fixtures
  requiring real protected external transitions. Both fixtures were corrected
  and passed in the final 45-test run. The diagnostic run is retained honestly.
- Final frontend/forms/artifacts/templates/audit/navigation/bounded collection
  and Arabic grammar run: **80 passed**.
- Canonical/upgrade full catalogue and existing-data parity passed; both
  databases removed. Traceability checks: **24 passed**.
- Catalogue references, key order/coverage, placeholders, nonblank values,
  new-entry terminology/quality/provenance/timestamps/hash, exact prior Arabic
  preservation, API environment template agreement and whitespace checks passed.

Live verification uses only synthetic disposable data in the requested Yahya
Gmail Chrome profile. Arabic-direction pages use existing published wording
and English fallback for new review drafts; bilingual component tests exercise
the new Arabic drafts without publishing them. PDF and screenshot evidence is
retained alongside live outcomes and cleanup results.

## Deployment and phase boundary

Apply **062_disposition_external_approval.sql** after **061** and any pending
predecessors, then restart API and WebUI. Empty databases use
`database/schema.sql` alone. No new environment settings or template changes.
No persistent ERMS database, including `demo`, was tested or migrated.
Explicitly seed the new translation drafts, review and publish through the
existing translation administration workflow; no publication was performed.

Phase 17 records received authority decisions. A successful approval completes
its external-decision task and displays the saved approval; physical/digital
execution routing belongs to subsequent phases. Email and reminder delivery
belong to Phase 18. All 20 owned disposable databases were independently confirmed absent, both
preview ports are closed, and the owned browser tab is closed. Changes remain
uncommitted.
