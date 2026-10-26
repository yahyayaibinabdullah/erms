# Review submission return and destination confirmation

Records Officer submission and resubmission from task details return to My Tasks
only after a successful submit-review response. Draft Save remains in place;
validation/concurrency failures preserve the page and comments. Abandoned page
callbacks do not navigate. The job overview does not inherit task-only navigation.

The API adds next_recipients to the successful submission response, projecting
actual destination users or role queues for that submitted review round/stage.
Names follow exact/base-language/canonical fallback. Shared queues are explicitly
labelled; no individual is inferred from role membership. The frontend displays
an eight-second confirmation before switching to My Tasks. No schema migration,
cache, additional frontend lookup, environment setting or workflow change.

Verification: 152 WebUI task/screen tests passed in English and Arabic, including
successful navigation, failed submission retention and toast-before-navigation.
Three database tests cover standard routing, absent File Administrator routing,
and simplified routing, with Arabic queue names and English fallback. The fresh
disposable database was dropped after the run. Catalogue and approved terminology
checks passed. Three new English keys (submitted, submitted_to, next_role_queue)
and matching generated Arabic drafts were merged without changing existing text
or provenance. The explicit demo missing-only seed stored three drafts, protected
3833 existing translations, and published none. Drafts need administrator review.

Single-reviewer routing enhancement: submission confirmation now prefers the
actual claimant when routing automatically assigns the sole eligible reviewer.
Unclaimed stages continue to show their shared queues. The destination query is
restricted to the submitted review round and stage, including command retries.


## Intermediate review handoff — 26 October 2026

File Administrator and Unit Manager completion now use the same actual-recipient
projection as submission. The review-decision API adds localized `next_recipients`
after completing its command. The query includes only open/claimed tasks in the
routed stage/round, uses the current job round when the decision result omits it,
and excludes closed historical claimants. The toast says “Review completed.
Next task: …” for eight seconds, naming the actual claimant/direct assignee or
labelling shared role queues explicitly. With no recipient, it says “Review
completed.” It does not infer a name from role membership, add a frontend lookup,
cache a recipient, alter task navigation or change workflow routing.

Two English keys and matching generated Arabic drafts were merged by key into
the canonical artifacts: `disposition.ui.review_completed` and
`disposition.ui.review_completed_to`. Existing wording/provenance is preserved;
no administrator export is promoted. Arabic drafts remain unpublished for review.

The same confirmation now covers every stage handoff: preparation/correction
submission, both intermediate reviews and rejection, Records Manager final
approval, generated-request recovery, external approval/rejection, physical
confirmation, successful digital execution and completed certificate generation.
A shared API projection reads the actual current stage and open/claimed tasks;
physical-only completion reports the job complete, and completed digital jobs
can identify the manager's remaining certificate-download task. Automated
certificate generation is labelled as an automatic next stage, without naming
an invented human assignee. Digital execution requests are still described as
queued; completion messages occur only when the worker's progress is successful.
Failed work and failed polling do not announce a handoff. Poll enrichment is
limited to successful terminal progress, avoiding repeated recipient queries
while workers are running. Existing page-liveness checks suppress late messages
from abandoned views. No shared recipient cache or extra frontend request exists.

Three further contextual keys cover the shared presentation:
`disposition.ui.job_completed`, `disposition.ui.completion_next_task` and
`disposition.ui.completion_next_automatic`, with matching Arabic drafts.
The `next_stage` and `workflow_completed` response fields complement
`next_recipients`; none changes task assignment, claim or authorization rules.

Final verification: 226 WebUI task/screen/external/physical/digital/completion
cases passed across English and Arabic. The broader phase regression run passed
129 cases; final focused runs passed 15 HTTP/localization/queue cases and four
post-review integration cases, including both languages and physical-only
completion. The full-flow checks verify the durable queued certificate work
before the job's stored stage label catches up, and confirm completed jobs never
advertise a nonexistent next stage. Every database-backed run used a newly
created disposable database initialized from the canonical schema; all were
cleanly dropped, including fixture-debugging runs. Catalogue key/order/blank/
placeholder/provenance coverage, artifact hash, approved terminology, Python
compilation, environment-template consistency and diff checks passed.

Live in-app browser verification used production ReviewForm and notification
code with isolated mock API data: the English toast named the actual person;
the Arabic RTL toast showed the translated shared queue with its explicit queue
qualifier. The temporary browser tab and preview process were closed afterward.
The demo missing-only Arabic seed stored five drafts, preserved 3896 existing
non-source-copy translations, reported zero awaiting generation and published
none. Administrator review remains required for those drafts. No demo review
or disposition task was completed as part of verification.


## Return every completed task to My Tasks — 26 October 2026

The shared WebUI `task_finished` helper applies the existing task-page inbox
callback to every successful completion, rather than Records Officer submission
alone. Intermediate review, review rejection, Records Manager approval, external
decision and physical confirmation notify the user first and return to My Tasks.
The inbox is shown even if the same user owns the next task. Committed approval
with pending document generation also returns without repeating approval.

Digital execution and certificate/final-completion views retain their progress,
outcome and download context. Physical-only completion stays visible too. Draft
Save, unsuccessful commands and abandoned views do not navigate. Job overviews
have no inbox callback, so retain the job context. External request recovery and
renewal use the same helper when an action hands off the task. No API/schema,
assignment, permission, environment, cache or user-visible message changes are
needed; the existing five translated handoff messages remain unchanged.


Verification of the inbox-return change: all 272 task/screen/external/physical/
digital/completion WebUI cases passed across English and Arabic. Live in-app
browser checks confirmed review completion replaced the task with the actual
My Tasks component while retaining the named-person/translated shared-queue
confirmation. The temporary preview/tab were cleaned up. Catalogue references,
approved terminology, environment-template agreement, compilation and diff
checks passed. There are no new or changed translation keys in this follow-up,
and no database-backed tests or demo task mutations were needed.
