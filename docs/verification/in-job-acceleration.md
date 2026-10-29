# In-job acceleration — verification, 29 October 2026

Approved contract: Disposition revision 1.14 (sections 5.2, 6.1, 11 and DISP-24),
Destruction Process revision 1.7 and the implementation-plan amendment.
[Implementation and upgrade guide](../disposition-in-job-acceleration.md).

## Final behavior

A reopened active member can be accelerated within its existing compatible job.
The whole unit returns to the matching pending status; its original membership,
addition attribution and work remain. Only that member's reopening flag clears.
No workflow advance, automatic execution, permission grant or new membership
occurs. Existing blockers, closure authorization, preserve-state holds and
irreversible-work safeguards remain effective.

Closing an open member uses the current database timestamp. A member already
reclosed retains its supplied valid closure date, including the historical date
of a migrated physical file. Preparation-stage proposals and the current task,
stage and round remain unchanged. Approval validity uses the existing semantic
approved-facts comparison: exact restoration can retain approval; changed
approved facts require renewed review. No blanket reopening-event invalidation
was introduced.

## Automated evidence

- **226 API regressions passed** against a new canonical-schema disposable
  database: in-job recovery, common membership and edges, bounded projections,
  acceleration provenance, external approval/correction and localization
  catalogue behavior. The 18 recovery cases in that run cover all four job
  types, fresh closure and historical reclosure, identity/history preservation,
  exact retries, wrong-action/stale rollback, normal/preserve-state holds,
  vital/security protections, direct-SQL bypass denial, concurrent acceleration,
  remaining reopened members, unchanged preparation proposals/task/round, exact
  approved-state restoration and renewed approval after a changed approved title.
- **2 additional API cases passed**: a descendant failure after restoration
  starts rolls back closure, flags, root/job versions, statuses, events and
  temporary context; an already-reclosed preserve-state-held member permits
  status-only restoration while retaining its hold. Total: **228 API checks**.
- **300 frontend/tool checks passed**, including bilingual confirmation/error
  handling, exactly two concurrent advisory reads, disposition screen/task
  behavior, canonical-schema shape, and parity of all five changed private
  functions with migration 093.
- A separate populated upgrade from pinned pre-change schema commit
  `84b16cc0acff440df23dc9c2690664bf121d8771` reproduced the old rejection. Applying
  092 and then 093 twice retained the flagged membership exactly and permitted
  restoration without removal. The original semantic approval policy remains.
- Catalogue references, ordering, exact English/Arabic active-key coverage,
  nonblank/placeholder/provenance/hash checks and approved Arabic terminology
  pass (918 contextual glossary uses). Configuration authority, API-template
  consistency and whitespace checks pass. No environment settings changed.

Commands used:

```sh
backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py \
  backend/services/api/tests/test_disposition_in_job_acceleration.py \
  backend/services/api/tests/test_disposition_membership.py \
  backend/services/api/tests/test_disposition_membership_edges.py \
  backend/services/api/tests/test_disposition_queries.py \
  backend/services/api/tests/test_retention_acceleration_display.py \
  backend/services/api/tests/test_disposition_external.py \
  backend/services/api/tests/test_localization_catalogue.py -x

frontend/webui/.venv/bin/python -m pytest -q -o asyncio_mode=auto \
  frontend/webui/tests/test_disposition_in_job_acceleration.py \
  frontend/webui/tests/test_disposition_screens.py \
  frontend/webui/tests/test_disposition_tasks.py tools/tests/test_canonical_schema.py
```

The two additional rollback/hold cases were added after the broader run and
executed explicitly by their node IDs in another fresh disposable database.
No test suite ran against demo or another persistent database.

## Live browser evidence

English and Arabic confirmation, successful acceleration, current aggregation
status and retained job membership were verified using isolated API/WebUI
services and disposable databases. An open member became closed/Pending
destruction; the job remained in preparation and its one membership remained
Active with no reopening notice. Returning through aggregation/job navigation
showed fresh state. Existing Wathiq table presentation and NiceGUI dialog/RTL
behavior were retained; no CSS or direction workaround was required.
Screenshots were captured after dialog transitions completed.

- [English confirmation](in-job-acceleration/confirmation-ltr.png)
- [Arabic confirmation](in-job-acceleration/confirmation-rtl.png)
- [Retained active membership](in-job-acceleration/restored-membership-ltr.png)

All agent-created preview tabs and owned preview services were closed. Preview,
upgrade and regression databases were dropped; cleanup is recorded in
[in-job-acceleration/cleanup.json](in-job-acceleration/cleanup.json).

## Catalogue and demo

Three new messages provide the recovery alternative, conditional review guidance
and a specific invalid-state error. `disposition.ui.reopened` was retired; its
complete Arabic entry remains in `deprecated_items`. All 3,919 prior artifact
entries are preserved exactly, either active or retired. There are now **3,921
active keys**, including three new generated Arabic drafts. No administrator
export was promoted and no curated wording/provenance was overwritten.

Migration 093 was applied to demo and the managed stack restarted. Read-only
checks confirmed its five changed functions and unchanged semantic approval
function match canonical SQL. Aggregation 427, membership, job DT-2026-2 and
saved proposals remained unchanged by deployment. All **3,971** pre-existing
Arabic database rows were preserved; the three new values match the final
artifact and remain generated, unpublished drafts for review. API/WebUI health
checks passed. The user can retry acceleration with a fresh form and their
reason; deployment did not execute that governed action for them.

## Traceability boundary

The amendment is traced in the current specifications, implementation guide and
`in_job_acceleration_amendment` ledger entry. The legacy whole-project baseline
checker still reports pre-existing stale source snapshots and previously added
sections absent from its historical baseline. Those historical phase claims
were not rewritten or presented as a new whole-project acceptance run. This
report records verification of the approved amendment and affected regressions.
