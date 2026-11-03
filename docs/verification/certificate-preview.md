# Digital destruction certificate preview — 3 November 2026

Requirement: destruction-process §16 certificate-generation/final-task behavior
and DEST-14. The Current Task certificate section must offer Preview certificate
alongside Download and Send by email. Preview remains available from the
completed job workspace to users with current component-view permission.
Viewing, downloading and emailing are optional and do not complete the task.
Only Complete this task completes the final task and job.

Implementation:

- `backend/services/api/disposition/completion.py::view` projects `can_preview`
  using the same current `record.component.view` check as the physical report
  and document list, separately from `can_download`, in the existing query.
- `frontend/webui/disposition/completion.py::controls` shows the localized,
  tooltipped Preview action before Download and Send by email. It delegates the
  saved governed record ID, filename and exact digital component ID to the same
  standard viewer callback used by the destruction request and physical report.
  It introduces no regeneration, download, email or task-completion command.
- No new API route, privilege, cache, environment setting or migration is needed.
  Current record/list/component authorization is retained. No initial read is
  added, and abandoned/busy forms do not open the viewer.

Verification:

- 76 English/Arabic UI tests passed across certificate completion, email and
  external approval controls. New tests cover exact saved component selection,
  available actions before/after completion, no API read/write from preview,
  busy/abandoned click suppression, and independent permission/viewer gates.
- One database-backed authorization test passed in disposable database
  `erms_messaging_test_acl_7d639ce2650d4991aefd2c9eddc4bc2a`, initialized from the
  canonical schema and then dropped. Removing component-view privilege hides
  preview while download remains authorized and the job remains active. No
  test targeted `demo`.
- A temporary database-free browser preview rendered the actual certificate
  controls in English/LTR and Arabic/RTL, including narrow-width wrapping.
  Its stub viewer confirmed callback activation without creating or completing
  jobs, sending mail or generating documents. This checks control layout and
  delegation, not PDF rendering; the production viewer itself is unchanged.
  Screenshots: [English](certificate-preview/english.png),
  [Arabic](certificate-preview/arabic.png). The preview server and tab were
  stopped after verification.
- One new contextual key, `disposition.ui.preview_digital_certificate`, was
  added to the sorted English and canonical Arabic artifacts. Existing text and
  provenance were preserved; the Arabic text is a generated draft. Catalogue
  coverage/reference/order, new-key terminology, placeholders, hash and
  `git diff --check` passed. The catalogues now contain 3,979 matching keys.
- The official Arabic seeder with `--missing-only` stored one unpublished draft
  in authorized local `demo`, protected the 3,978 prior entries, replaced none,
  and reported zero failures or missing generated values.

The destruction specification and `docs/disposition-workflow.md` explicitly
state the Preview/Download/Send actions and their independence from completion.
The preceding mandatory-preparer and Manager-delegation requirements remain
recorded in those same product documents and the required-job-preparer evidence.
