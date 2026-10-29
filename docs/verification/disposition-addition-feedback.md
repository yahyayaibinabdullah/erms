# Disposition addition feedback — 29 October 2026

The user-approved amendment in Disposition revision 1.12 / DISP-27 is implemented
in `frontend/webui/disposition/screens.py`. Complete success produces one toast
with the actual added count and destination job number. There is no persistent
success list. Partial success reports added/selected and failed counts; zero
success gives a warning. A compact **View failures (count)** action opens only
failed additions, ten per page, with permitted identities and safe reasons.
The existing API per-item outcomes and transaction behavior remain authoritative.

The membership command suppresses its generic notification so it emits one
outcome toast. It reloads the current eligibility page and clears selection.
Feedback and failure-dialog callbacks check page liveness. Inaccessible
identities are redacted and unknown error codes are replaced with safe wording.
Failure details use only the bounded command response; no new request or cache
is introduced. Other commands retain their existing notifications.

| Requirement | Implementation and verification |
| --- | --- |
| Complete success: counted toast, no result list | `addition_feedback`; bilingual tests with one and 100 successes; live API/browser addition of two aggregations |
| Mixed/zero outcomes stay truthful | Separate localized outcome messages; bilingual mixed and zero tests; live results of 1/2 and 0/2 |
| Failure details only, ten per page | Standard NiceGUI dialog/cards; test with 83 successes and 17 failures verifies pages of ten and seven with no success identities |
| Safe identity/reason disclosure | Access-denial identity redaction and safe fallback; stale-identity/raw-error regression |
| Fresh page and abandoned navigation | Real eligibility/command-dialog test verifies reload, deselection and one toast; abandoned-page regression; live return to refreshed eligibility |
| LTR/RTL and localization | Bilingual frontend tests and live English/Arabic browser flows; approved terminology, key coverage, ordering, placeholder, blank, markup, provenance and hash validation |

## Verification results

The disposition frontend and locale suite passed **471 tests**:

```sh
frontend/webui/.venv/bin/python -m pytest -q -o asyncio_mode=auto \
  frontend/webui/tests/test_disposition_*.py \
  frontend/webui/tests/test_locale_services.py
```

The selected API run passed **38 tests** and failed **five existing task-claim
tests**. The mixed-membership persistence test, localization catalogue suite and
new outside-job relationship regression passed. The five failures reproduce in
a separate disposable database when selected alone; the task-claim implementation,
canonical schema and those test bodies are unchanged by this work:

- `test_queue_claim_gates_and_task_only_reviewer`
- `test_reassignment_candidates_scope_and_current_indicator_filters`
- `test_committed_claim_preserves_timestamp_when_saving_in_a_new_transaction[standard-True]`
- `test_committed_claim_preserves_timestamp_when_saving_in_a_new_transaction[standard-False]`
- `test_committed_claim_preserves_timestamp_when_saving_in_a_new_transaction[simplified-False]`

These expect an unclaimed task / claim operation where the current workflow has
already claimed it; observed failures include action-list mismatches and
`disposition_stale_task`. They remain an unresolved test-suite limitation.
Commands and temporary logs from this run:

```sh
backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py \
  backend/services/api/tests/test_disposition_membership.py::test_multi_add_keeps_success_and_rolls_back_stale_blocked_wrong_type_and_hidden_items \
  backend/services/api/tests/test_disposition_workspace.py \
  backend/services/api/tests/test_localization_catalogue.py

backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py \
  backend/services/api/tests/test_disposition_workspace.py \
  -k 'queue_claim_gates_and_task_only_reviewer or reassignment_candidates_scope_and_current_indicator_filters or committed_claim_preserves_timestamp'
```

Logs: `/tmp/erms-addition-ui-final.log`, `/tmp/erms-addition-api-tests.log` and
`/tmp/erms-addition-claim-baseline.log`. Catalogue references, approved Arabic
terminology (907 contextual uses / 35 glossary mappings), configuration authority,
API environment-template consistency and whitespace checks passed.

## Live preview and demo

Live browser verification used an isolated canonical-schema database, API on
18000 and WebUI on 18080. The fixture job `PREVIEW-2026-1` exercised complete
success (2/2), partial success (1/2) and zero success (0/2) through the real API.
Holds created through the test fixture between selection and submission produced
the failures. Only the three successful aggregations joined the job; failure
details contained only failed identities. Arabic was published solely inside
the disposable fixture to verify RTL. Returning through Dashboard to eligibility
showed fresh rows without old outcome details. The temporary browser tab and
services were closed, its connection file removed and its database dropped.

- [Success and refreshed list](disposition-addition-feedback/success-ltr.png)
- [Partial success and compact failure action](disposition-addition-feedback/partial-ltr.png)
- [Arabic zero-success warning](disposition-addition-feedback/none-rtl.png)
- [Arabic failure-only dialog](disposition-addition-feedback/failures-rtl.png)

The managed local stack was restarted successfully against **demo**. Its explicit
missing-only seed stored **seven new Arabic drafts**, protected 3,907 existing
active translations and corrected none. Nothing was published in demo. All
3,958 pre-existing Arabic database rows retained their text, status, origin,
review timestamp and review flag. The previous 21 terminology drafts remain
available; there are now 28 active unreviewed Arabic drafts.

There are **3,914 active catalogue keys**: seven added and two retired
(`disposition.ui.added`, `disposition.ui.results`). All 3,907 retained Arabic
artifact entries are unchanged from the start of this amendment. The complete
retired entries are preserved in `deprecated_items`, and their database rows
remain intact. New drafts have generator provenance, current catalogue/spec/
terminology hashes and `needs_human_review`. Review them through Translations
before publication. No environment variables, schema or migrations changed.

## My Tasks diagnosis

Read-only inspection of the user's **DT-2026-2** job found four active
aggregations at `officer_preparation`, zero protection blockers, and three
outside-job relationships across two aggregations. Those relationships block
**final destruction**, even though they do not block admission or preparation.
The current “Destruction blocked” label under “Action required” expresses that
final-execution flag, as required by Destruction Process section 6.2. Preparation
can continue. The new regression
`test_outside_job_relationship_blocks_final_destruction_without_blocking_preparation`
verifies the distinction and verifies that including the other endpoint clears
the final-block flag. No demo jobs, resources or relationships were changed.
The label and blocker rules were not changed by the feedback amendment.

The [machine-readable verification record](disposition-addition-feedback.json)
contains final counts, hashes, diagnosis and confirmation that all four
disposable databases used during this work are absent.
