> Superseded: Phase 16 was resumed and completed. See [the final handoff](disposition-phase-16.md) and its verification evidence. The checkpoint below is historical.

# Phase 16 checkpoint — 19 October 2026

Work stopped at the user's explicit request so they can restart the browser and
VS Code. **Phase 16 is in progress, uncommitted and not ready for handoff.** Do
not start Phase 17 or mark Phase 16 complete from this checkpoint.

## Workspace preservation

HEAD is `979490ee137f13155b1b5f025f8593574aac5d3e` (Phases 10–12).
The workspace already contained uncommitted Phase 13–15 implementation,
migrations 058–060, translations, tests and evidence when this phase began.
Preserve those changes. No commit, staging, persistent database migration,
translation publication, or production environment change was performed.

Phase 16 adds no migration or environment setting so far. No preview server,
Chrome process or test database remains intentionally running. All four
Phase 16 database test runs report successful database removal; see checkpoint
JSON for the exact names. Independent catalogue-of-databases verification is
still pending.

## Implemented so far

- `backend/services/api/disposition/workspace.py`: uncached job/task projection,
  eligible acting roles and server-derived actions; bounded complete-unit target
  selectors. Routes are appended to `disposition/routes.py`.
- `workflow.py`: task search/stage/type filters and additional applicable sort
  fields. `queries.py`: member search/state filtering/sort and classification,
  medium, effective-rule/source and proposal-count metadata; assignment/owner
  controls require management authority.
- `proposals.py`: bounded proposer/editor/note-author display names, readable
  security/relationship labels, compact review-round/decision projection mode.
- `frontend/webui/disposition/tasks.py`: My tasks using the existing Wathiq
  `PageTable`, real offsets, task/queue/claimant, dates/age, priority/count and
  removal-required indicator.
- `frontend/webui/disposition/review.py`: current-task controls, claim/release,
  explicit versioned atomic Save, notes and partial overall reason, Save before
  submission/decision/approval, exact-payload retry UUIDs, draft proposal forms
  for all eight types, remote targets/holds/security/relationship types,
  paginated proposal/note/round panels, report retry, readable proposal details
  and a native workflow timeline.
- `disposition/screens.py` and `app.py`: workspace integration, task-only
  navigation without global management privilege, protected management buttons,
  richer membership table and a dirty-work navigation guard.
- `messaging/reading.py`, `messaging_workspace.py`, `app.py`: task-assignment
  notification detail can open its authorized task workspace via a bounded
  envelope/source-event projection. This last integration needs focused tests.
- `tests/test_disposition_workspace.py` and frontend
  `tests/test_disposition_tasks.py`: current authority, bounded requests,
  Save/stale/retry/submit and bilingual component checks.

## Translation state

92 new contextual `disposition.ui.*` definitions and Arabic review drafts were
added. EN and AR now contain 3,506 keys. All 3,414 pre-existing Arabic items are
exactly preserved, including provenance/flags. No administrator export was
promoted. English ordering and catalogue source-reference checks passed.
Full placeholder, new-entry terminology, provenance and hash acceptance remains
pending. Check new generation metadata, especially accurate timestamps, before
handoff. The new-key list and preservation assertion are saved in
`verification/disposition-phase-16/checkpoint.json`.

## Verification to date

Evidence copies are in `docs/verification/disposition-phase-16/`.

- First workspace run: 4 passed, 1 fixture failure (wrong helper argument);
  corrected rerun: **5 passed**.
- Workspace + existing read projections: **16 passed**.
- Workspace + review + task notifications: **25 passed**.
- Latest combined frontend forms/screens: **23 passed, 3 failed**. This is
  diagnostic evidence, not completion. Some subsequent frontend cleanup has
  not been rerun in the combined invocation.
- Python compilation and catalogue source/reference completeness passed at
  their latest invocations; rerun after remaining changes.

### Immediate known test issues

1. The old removed/reopened-member test picks the first `ui.table` and assumes
   it is the membership table. Review tables now appear first. Select the table
   containing the membership row/column instead; do not weaken removal rules.
2. The proposal-dialog test invokes NiceGUI's click wrapper, which schedules the
   async callback and returns `None`. It asserts before that callback runs.
   Await the scheduled callback completion (or use the supported interaction
   fixture), then investigate any actual failure. Temporary `CALLBACK` debug
   printing remains in `frontend/webui/tests/test_disposition_tasks.py`; remove
   it. Latest diagnostic is `phase16-dialog-debug.log`.
3. A real NiceGUI background-slot failure was fixed by explicitly entering
   `self.host` in the concurrent proposal/notes/round panel methods. Verify the
   actual mounted layout/order and localization context in browser.

## Remaining implementation and acceptance work

- Review and finish the new code; it is an intermediate implementation. Check
  every approved Phase 16 requirement against destruction §§6–10 and the
  performance/design/i18n contracts before calling it complete.
- Finish workflow diagram/branch presentation. The native timeline has explicit
  Start → active creation → preparation and Completed → End, route bypass labels,
  but is not yet the specified complete process diagram. The Standard FA-skip
  projection currently uses any matching historical event and needs to reflect
  the relevant latest route/round instead of incorrectly retaining an old skip.
- Add current review round/destruction number to header where applicable; render
  the exact task-specific form titles/instructions; review all current task
  action gates. Verify closed explicit task links and completed-job history.
- Add full revision-history disclosure for proposals and notes and detailed
  authorized job events. Existing job history currently shows basic rows only.
  Review decisions have a compact API mode but no dedicated rendered panel yet.
- Finish aggregation-row proposal-panel navigation/grouping and visible removal
  marks; expose active proposal type/target/current vs proposed state clearly.
- Inbox still needs comprehensive blocked/action-required indicators and the
  remaining applicable filters/sorts (currently search, state and stage are
  visible). Do not invent future execution behavior from Phases 17+.
- Verify reassign capability/controls against existing authorized APIs. Current
  UI implements claim/release; reassignment UI is not yet added.
- Check dialog cancellation, selection change races, remote identity/role
  changes, mandatory reason feedback, exact selected relationship retention,
  and all proposal type forms. Avoid API writes from a draft dialog before Save.
- Approval report failure can return `approval_committed=true` (503); the new
  frontend still needs explicit truthful handling/refresh for this case.
  Refresh proposal rows/versions if Save succeeds but a following decision
  fails. Never display a stale retry as success.
- Review the dirty guard with all workspace navigation, membership mutations,
  Refresh, role changes and successful reload. Drafts must not silently disappear.
- Add tests for compact rounds, readable attribution, new security candidates,
  membership metadata/filtering/redaction, task notification links and expiry,
  additional role/stage capability cases, stale/correction cycles and pagination.
- Run appropriate API regression using a fresh disposable DB for **every run**,
  canonical and migration-path validation where warranted; never use demo.
- Run focused frontend/messaging/performance/catalogue tests, translation
  acceptance, baseline ledger checks, env-template check and `git diff --check`.
- Update requirement ledger and create Phase 16 handoff only with evidence.

## Browser blocker and user steering

The user requested the **in-app browser**. Do not switch to a custom browser/CDP
setup. CUA inventory repeatedly returned no browsers and native pipe startup
failure. Explicit `cua.createBrowserTab('iab','about:blank',{visible:true})`
failed with `Browser is not available: iab`, including after `js_reset`.
The user also reports no Chrome in the @ menu. They are restarting the browser
and VS Code. On resume, retry the in-app browser first. A CUA session reset means
its first call must be one documented entry point only; read returned docs.

No role-by-role live browser checks, LTR/RTL visual comparison, table appearance,
evidence preview, repeated-navigation performance or concurrent-form live
acceptance has passed. The approved phase cannot be declared complete without
those checks. Do not repeatedly spend time troubleshooting unavailable browser
connections; report the precise tool result and finish independent work.

## Useful commands

```sh
frontend/webui/.venv/bin/python -m pytest frontend/webui/tests/test_disposition_screens.py frontend/webui/tests/test_disposition_tasks.py -q --tb=short
backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py backend/services/api/tests/test_disposition_workspace.py backend/services/api/tests/test_disposition_review.py backend/services/api/tests/test_disposition_task_notifications.py --tb=short
frontend/webui/.venv/bin/python frontend/webui/scripts/check_i18n_catalogue.py
python3 tools/sync_api_env_template.py --check
```

Database runner needs localhost PostgreSQL access with appropriate sandbox
approval. It creates/initializes a unique disposable DB and drops it in finally.
Retained temporary sources `/private/tmp/phase16-ar-baseline.json`,
`/private/tmp/phase16-new-keys.json`, `/private/tmp/phase16_catalogue.py` may aid
review, but **do not rerun** the catalogue creation script: its baseline capture
would replace the earlier baseline. The repository checkpoint JSON preserves
keys and preservation findings if temporary files disappear.
