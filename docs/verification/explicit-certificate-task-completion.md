# Explicit final certificate task completion

Approved change to destruction-process §16 and DEST-14: certificate generation
and storage prepare the final Records Manager task. The job remains active.
The **Complete this task** action completes this task and the job atomically,
then returns My Tasks, where the completed task is no longer listed.
Neither a certificate download nor an email attempt completes the task or is
required to complete it. Physical-only confirmation already completes its last
task with the job and retains that behavior.

The API command uses the existing governance scope, current task eligibility,
Records Manager role, job/task versions, command receipt and fresh transaction.
The database requires a saved available certificate and no remaining open or
claimed tasks before marking the job completed. Failed/stale/unauthorized
commands do not complete either object. An exact command retry is idempotent.
The certificate worker and final user command never repeat destruction.

Migration 091 installs the updated private primitives and repairs previously
completed jobs with an unfinished certificate task. It restores only the job's
active lifecycle/pending-destruction status, leaves destroyed resource states,
certificate bytes, tasks and immutable completion history untouched, and appends
an audited migration correction referencing the earlier completion event.
A transaction-wide exclusive table lock protects the narrow data repair; guards
are restored before commit. The migration is safe to repeat. The canonical
schema independently defines the current functions and invariants.

Verification: API certificate workflow and policy inventory regressions run
against fresh disposable databases; English/Arabic native UI tests cover the
explicit button, completion without download permission, and return to My Tasks.
An upgrade regression recreates pre-091 premature completion, applies the
migration twice, checks preserved certificate/history, and explicitly completes
the pending task. Database creation and cleanup are recorded in the local logs.

Four new contextual UI keys cover the button, optional-download guidance,
final-task title and completion notice. Existing Arabic wording/provenance is
preserved; new generated Arabic drafts require human review and publication.
No administrator export was promoted. Environment templates are unchanged.

Results (27 October 2026): 27 API workflow/policy tests passed; one additional
upgrade/repeated-migration test passed; 227 English/Arabic completion and inbox
UI tests passed. Every disposable database was dropped. The demo migration
restored DT-2026-1 to Active and retained open task 7 for the user. Managed
stack startup imported the four missing Arabic drafts without publication.
Live Chrome verification under Fathiya showed Active, Complete destruction job,
optional download/email guidance, and an enabled Complete this task button.
The My Tasks row uses the same final-task title and standard Wathiq table
presentation; opening it returns to the ready task. The demo task was not
completed during verification.

The legacy bootstrap translator's whole-artifact quality heuristic rejects
some previously curated wording and the intentional Re: email prefix. Those
existing translations were preserved. The four new drafts pass that generator's
checks; maintained-catalogue key/placeholder/nonblank/hash checks, reference
checks, and the approved terminology checker all pass for this change.
