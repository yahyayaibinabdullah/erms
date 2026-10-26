# Claim a task without a reason

Destruction-process section 6.3 specifies that accepting responsibility through
Claim requires no user-written reason. The ReviewForm claim dialog hides the
reason field; release retains it. The claim endpoint permits an absent
X-Change-Reason header, and the database begin_command guard exempts only
 task_claim alongside the previously exempt creation/addition commands.

Actor, task, time and claimant remain audited. Current authorization, clearance,
access, optimistic versioning, atomic claiming and idempotency are unchanged.
Migration 084 changes the command function only; existing tasks and audit history
are preserved. No UI strings or translation keys are added, changed or removed;
the shared reason label remains in use elsewhere and its Arabic wording is kept.

Verification uses the real NiceGUI claim/release dialogs in English and Arabic,
and the workflow API/database suite in a newly created disposable database.
The API test claims with no header, verifies attribution and history, and checks
that release/reassignment still reject omitted reasons.

Verified 26 October 2026: 119 English/Arabic UI tests and 36 workflow
API/database tests passed. The disposable database was dropped after the run.
Catalogue references, approved Arabic terminology, environment templates and
`git diff --check` passed. Migration 084 was applied to demo with both existing
task rows verified unchanged. Existing translation artifacts were preserved.
