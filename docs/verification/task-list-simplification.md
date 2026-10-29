# My Tasks and Active jobs default — 29 October 2026

The user's approved change is implemented. My Tasks retains its first
**Required action** column and removes the redundant **Action required**
indicator column and its row decoration. Required-action text, certificate
recovery actions, server-side indicator filters, progress, sorting and server
pagination remain available. Final-execution blocker facts, enforcement and
API contracts are unchanged. The existing job workspace shows blocker reasons
under Aggregations → Current blockers, including permitted relationship
endpoints and redaction of restricted endpoints.

Disposition Jobs now defaults its Job state filter to **Active** when opened
afresh. The existing server filter applies before pagination and counts.
Explicit Any, Active, Completed and Terminated selections are restored from
the existing navigation-history view state. Returning from a job to the saved
list retains its selection; opening the list afresh through the sidebar uses
Active. No new cache, endpoint, database migration or environment setting is
introduced.

## Traceability and verification

| Approved requirement | Implementation | Verification |
| --- | --- | --- |
| One task action column; blockers with reasons in job details | Destruction Process revision 1.4 §6.2 / DEST-21; `disposition/tasks.py` retains `action_label`, removes `indicator` display | Bilingual real-component inbox regression checks required-action text and no duplicate column, while retaining the indicator filter. Existing blocker dialog tests cover reasons, endpoints, redaction, errors and pagination. |
| Active jobs by default; history still accessible | Disposition revision 1.13, Jobs list filters; `disposition/screens.py` defaults only an absent saved lifecycle to `active` | Jobs request regression checks a single bounded concurrent page with Active; saved-state cases cover absent, Any, Active, Completed and Terminated with correct offset and API filter. |
| Standard tables and bilingual rendering | Existing Wathiq `PageTable`, styling, direction and locale messages | Live English and Arabic tables compared with the adjacent standard Jobs and workspace membership tables. |

The full disposition frontend and locale suite passed **475 tests** in 15.83
seconds. Python compilation, current/stale catalogue-key checks, approved Arabic
terminology checks, configuration authority, API template consistency and
`git diff --check` passed. The temporary test log is
`/tmp/erms-task-columns-tests.log`.

Live browser checks used the real API and WebUI against a unique disposable
canonical-schema database. An active preparation job contained two aggregations;
one had a relationship to an aggregation outside the job. An empty second job
was terminated through the normal job command for the historical-list fixture.

English and Arabic checks confirmed one Required action column and no second
indicator column; the current task still says Prepare destruction job. Both
jobs lists defaulted to Active and showed only the active job. Any showed both
the active and terminated jobs. Opening the active job and returning through
navigation history retained Any. Repeated navigation requested one bounded
page per load. Job blocker dialogs in both languages retained the final-only
reason and the source/target identities. Unit coverage verifies saved Completed
and Terminated filters as well. No persistent database test suite was run.

- [English My Tasks](task-list-simplification/tasks-en.png)
- [Arabic My Tasks](task-list-simplification/tasks-ar.png)
- [English Active jobs default](task-list-simplification/jobs-active-en.png)
- [Arabic Active jobs default](task-list-simplification/jobs-active-ar.png)
- [Any restored from job details](task-list-simplification/jobs-any-restored-en.png)
- [English blocker reasons](task-list-simplification/job-blockers-en.png)
- [Arabic blocker reasons](task-list-simplification/job-blockers-ar.png)

Arabic viewport captures use the normal viewport screenshot: the browser's
full-page capture displaced the RTL page horizontally despite correct viewport
rendering. No layout override was introduced. All temporary browser tabs and
preview services were closed; the final preview database and both failed
fixture setup databases were dropped. A read-only check confirmed all three
are absent and the preview connection file was removed.

The managed local stack was restarted successfully and **demo** loads the
changes. No demo jobs, resources, relationships, task priorities or language
preferences were changed. Existing English and Arabic messages are reused;
no catalogue keys, wording or provenance changed in this amendment and no
administrator export was promoted. The prior unpublished Arabic drafts retain
their review requirement.

## Priority investigation

`disposition_tasks.priority` defaults to integer **0** in the canonical schema.
All task-creation paths omit a priority override. The current application has
sorting and a Minimum priority filter but no priority-edit screen, command or
automatic calculation, and `disposition_jobs` has no priority field. The
approved specifications require a task priority field but define neither an
assignment authority nor a scale or business policy. The displayed zero is
therefore a default, not a risk, deadline, ageing or urgency assessment.
No priority behavior was invented or changed in this work. A useful priority
feature needs an explicitly approved assignment and ranking policy; hiding the
unused column is a smaller presentation option.

The user subsequently approved hiding the column. That follow-up is implemented
and verified in [Priority column hidden](task-priority-hidden.md).
