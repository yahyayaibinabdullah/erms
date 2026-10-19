# Phase 19 — Physical preparation and confirmation

Phase 19 implements preparation reports and the protected offline-confirmation
contract. **Operational physical and digital destruction remains unavailable**,
as required by the implementation plan. Recovery, digital execution and final
completion retain Phases 20–22 as their owners. No persistent database was
changed and no commit was created.

## Requirement → implementation → verification

| Approved contract | Implementation | Evidence |
| --- | --- | --- |
| Destruction §13; DEST-09; common disposition §14.3 | External approval routes from every aggregation and record in every active complete unit. Physical/mixed descendants and records cannot be hidden by a digital parent. Manager tasks use the same eligible-role queues as internal review. | Media matrix, legacy hierarchy, digital-only routing and multiple Manager queue acceptance in `test_disposition_physical.py`. |
| Destruction §14.1; DEST-37/38; medium/location contract | `physical.generate_report` automatically runs after received approval commits; rendering failure leaves a visible pending report that a current Manager can generate. Snapshots capture terminal classification, effective inherited assigned/current locations, prescribed descendant counts, direct non-overlapping classification/job totals and bilingual “Not specified.” Indexed bottom-up counting avoids recursion and repeated hierarchy scans. | Real inherited-location and 3,000-node tests; report freshness race; actual governed 11-page bilingual PDF, embedded Changa and visual cover/detail/final-page checks. |
| Destruction §14.1; governed records §11/12 | Existing controlled DOCX→PDF generation saves under the current Generated reports destination. Regeneration retains immutable source, template, checksum and report version. History displays/sorts report versions and identifies earlier versions. Exact retries retain the saved artifact. | Destination separation, versions/currentness/order, retry and stale-render rollback acceptance; live regeneration, authorized preview/download controls and version sorting/history. |
| Destruction §14.2; disposition §9/10.5; DEST-17 | The protected prework check locks and freshly rechecks complete-unit holds, vital/security protection and outside-job aggregation/record relationships before authorizing offline work. A repeated check never replays an obsolete authorization. Confirmation repeats all checks. | Concurrent relationship commit, repeated-check, current root/record hold, security, vital and both relationship kinds. |
| Destruction §14.2/18.7/18.13; DEST-10/25 | One immutable `disposition_physical_confirmations` row per job; global certificate-reference uniqueness; required successful checkbox, governed uploaded certificate, actual current Manager/own claim, server time, server-owned bilingual confirmation text/version and non-content physical/mixed scope. Certificate/confirmation/tasks/history commit together. | Missing file/checkbox/reference, Manager/claim authority, exact retry, duplicate reference, late rollback, sibling cancellation and corrective evidence version preserving the original confirmation. |
| Implementation-plan release boundary; later recovery/completion clauses | `physical_execution_released()` is a closed code boundary, not an environment/application setting. Both prework authorization and confirmation remain rejected. Existing final-execution and correction-transition guards remain in force. No content is destroyed. Physical-only finalization is deliberately not enabled here. | Normal HTTP rejection before upload staging; private contract tested only with a temporary fixture override in disposable databases, restored before/after every test. |
| WebUI performance, design and translation contracts | Native NiceGUI controls, current component preview/download authorization, existing Wathiq document/task tables, bounded history, no new cache, workspace projection instead of another page request, guarded async responses and warning/error/success toasts. | English/Arabic component coverage, abandonment checks, Gmail-profile Chrome LTR/RTL checks and retained screenshots. |

Legacy inconsistent-media fixtures verify that routing reads all existing items;
production medium-capture rules were not weakened. Ordinary correction/review
transitions from destruction stages were not expanded. Automatic approval review
rejected that proposed expansion because it could weaken irreversible-outcome
safeguards; it was left outside this change, with recovery in Phase 20.

## Verification

Logs and structured evidence are in `docs/verification/disposition-phase-19/`.
Overlapping runs are reported separately, not added as unique test totals.

- Canonical report/external/workspace/communications regression: **119 passed**.
- Final Phase 19 acceptance: **23 passed**.
- HEAD → 062 → 063 → 064 upgrade acceptance: **60 passed**, one previously
  verified large-PDF test deselected.
- Frontend/task/forms/audit/source checks: **92 passed**; final focused rerun: **62 passed**.
- Fresh/upgraded complete catalogue parity and preservation of every
  pre-existing public/private row passed.
- Prior Arabic entries preserved exactly: **3,619**. Added **22** contextual keys
  with Arabic drafts flagged `needs_human_review`; **3,641** aligned active keys.
  No administrator export was promoted and no new draft was published. Live
  Arabic therefore uses the approved English fallback for unpublished keys;
  bilingual component checks also exercise their Arabic draft text.
- All database-backed checks used uniquely named disposable databases. See
  `cleanup.json` for final independent absence and preview/tab cleanup.

The browser did not expose a download event to the automation tool. The content
route succeeded; the actual stored PDF was separately read through the authorized
Manager download check and its bytes matched the governed checksum. The report
was visually inspected on representative first, detail and final pages.

## Deployment

Apply `064_disposition_physical.sql` after pending **062**, **063** and all earlier
migrations; new empty databases use `database/schema.sql` alone. Restart API and
WebUI. Explicitly seed the new translation definitions/drafts through the existing
workflow and review/publish them before expecting translated new labels at runtime.
No environment variables or templates changed; the API template check still
covers all 36 existing settings. Do not enable the physical release boundary
until recovery and completion verification passes in the later owning phases.

Phase 17/18 workspace changes were preserved. Phase 20 is next.
