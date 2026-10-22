# Disposition job creation — 22 October 2026

Approved contract: disposition §10.1.0 and destruction-process job creation
clarification. Creation is independent of preparation/review authorization.

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Officers and Managers create all four types on every route | `guard_workflow` creation branch; create-dialog type options | Six profile/route cases, all four types; existing workflow suite |
| DT/PT/ST/LA annual numbering in application timezone | Private transactional counters and `create_job`; public API omits number | Sequence, separate type/year counters, preserved legacy number, retry, rollback and concurrent allocation |
| Editable creator default only if eligible | Context supplies creator; form uses route/profile and resets default on type change | Three assignment cases and changing selection; live English/Arabic preview |
| No creation reason; other commands retain reasons | Reason gate exemption only for job_create, receipt constraint, form omits reason | Blank creation, HTTP without reason, update rejection |
| Existing databases upgrade safely | Migration 078 repeats canonical SQL | HEAD schema plus 078 and nine new creation tests; applied to demo |

The membership/workflow regression run passed 120 tests. The creation-specific
suite passed nine tests on both the canonical schema and the upgrade path.
The WebUI module passed 30 tests. Database runs created uniquely named disposable
databases and dropped them afterward. No test suite ran against demo.

The in-app browser used the real create form with database-free fixtures and
Wathiq styles in English/Arabic. Confirmed Destruction is visible to a Manager
on Standard, number/reason inputs are absent, non-destruction defaults to the
creator, and the owning-unit field and hint hide together. The temporary
preview process/tab were closed after verification.

Existing translation keys are reused; no catalogue text or artifact changed
for this task. The creator's name uses existing entity translations. No
permissions, review-route settings, existing job numbers or assignments were
changed in demo; migration 078 adds counters and updates creation gates.

Logs: `.runtime/job-creation-api.log`, `.runtime/job-creation-new-tests.log`,
`.runtime/job-creation-migration.log`, `.runtime/job-creation-ui.log`, and
`.runtime/job-creation-final.log`.

## Creation from the eligibility job chooser (2026-10-22)

`choose_job_dialog` reuses `create_dialog` and routes its returned ID to the
existing membership confirmation callback. Eligibility retains its selected
root IDs/versions; no membership command runs on job creation itself.
`test_chooser_creates_job_and_resumes_selection_only_while_open` covers English
and Arabic, cancellation/search preservation, single selection and abandoned
callbacks. The screen suite passes all 34 tests. The in-app browser verified the
real chooser and nested form using a fixture API in English and Arabic, including
successful creation closing the chooser. No demo records were created.
Existing catalogue keys are reused; no translation or database changes required.

## Owner suggestion from selected roots (2026-10-22)

Destruction Process §5.1.1 maps to `queries.suggested_owner`, the bounded GET
`/api/v1/disposition/suggested-owner?root_ids=...` (1–100 IDs), and the chooser's
creation callback. The response contains `owner` (localized ID/name or null)
and `basis` (`same_unit`, `common_ancestor`, `no_common_ancestor`). It is advisory,
uncached, manager-authorized and rejects missing/inaccessible/non-root inputs
without returning ownership. Only selected roots and their ancestor chains are
read. Existing admission checks remain authoritative.

Verification: 18 query/API tests and 37 screen tests passed. Disposable database
`erms_messaging_test_acl_c31316dc31a44035b29bad9a3ab63298` was created and dropped.
Coverage includes direct owner, duplicate selection, nearest/deeper common
ancestor, parent-plus-descendant, changed hierarchy, disconnected units, missing
root rejection, request bounds, localized names, editable prefill, message
selection, callback propagation and abandonment. In-app fixture previews verified
English prefill/explanation and Arabic RTL no-common-ancestor presentation.

Added catalogue keys `disposition.ui.owner_common_ancestor` and
`disposition.ui.owner_no_common_ancestor`. Existing wording/provenance was
preserved; new Arabic values are review-only drafts. Full key order/coverage and
new-key validation pass. The full Arabic validator retains the 12 pre-existing
terminology/source-copy findings; no unrelated translation was overwritten.
No schema migration is required.

## Standard organization selector (2026-10-22)

Disposition owner fields now reuse `relationship_select` extracted unchanged
from the main WebUI into a shared module, with an explicit organization icon so
Arabic labels do not affect icon selection. This preserves the existing Wathiq
avatar, unit-name/code-badge menu and field presentation rather than introducing
CSS. Search and selected-ID hydration return code and localized name; translated
names are searchable. Suggested owners retain their code/name on initial render.
Two-character bounded remote search, selected values and admission checks remain.

54 screen/relationship tests and 19 API query tests passed. The disposable test
database was dropped. English and Arabic fixture menus were inspected in the
in-app browser against the existing shared selector presentation. No catalogue
text, schema, environment or persistent database settings changed.

## Routine admission and destination compatibility (2026-10-22)

Disposition §10.2 maps to migration 079/canonical `begin_command` and receipt
constraint, API `add_items(reason_required=False)`, and the reason-free membership
confirmation. Only `job_create` and `membership_add` permit blank reasons.
The bounded jobs read accepts optional `root_ids` and annotates the displayed
page with `selection_error`; the chooser disables that action and explains it
using existing localized messages. Ownership checks require every selected root
to lie in the destruction owner's current subtree. Type/status, stage,
assignment/preparer, task, closure, protection and assignee access checks are
advisory; mutation-time locks and checks remain authoritative.

39 screen tests and 51 query/membership-edge tests passed on the canonical
schema. Two focused tests also passed through HEAD + migrations 078/079,
including no-reason API admission, exact retry, preserved audit attribution,
mandatory removal reason and owner-subtree/type compatibility. Both disposable
databases were dropped. Migration 079 was applied to demo and its constraint
verified. In-app fixture checks showed disabled incompatible jobs with an
explanation in English/Arabic and the reason-free Arabic confirmation.
No new catalogue keys or environment settings were introduced.

Owning-unit mismatch explanations now also show the job's localized owner name,
using the existing owner label and bounded jobs response (no extra requests).
The dynamic name is escaped by Vue interpolation and isolated with `bdi`.
All 39 screen tests pass; English and Arabic fixture rendering was checked in
the in-app browser. No catalogue changes or migration required.

## Review-proposal selectors (2026-10-22)

Security Level and Relationship Type use the shared relationship selector and
load at most 25 authorized reference choices on opening, with server-side
filtering. Legal Holds and Related Aggregation use bounded two-character remote
search with visible guidance and empty-result feedback; selected IDs survive
search changes. Correct resource metadata enables standard security-level labels.
Related Aggregation also uses the existing paged classification/aggregation
browser; a selected ID is revalidated through the task candidate API before it
updates the field. Leaving the dialog or changing proposal type abandons pending
browser callbacks. Existing task, hold access and proposal validation remain.

One contextual Browse key was added with an Arabic review draft; existing
translations/provenance were preserved. No database migration is needed.

Selector verification: 85 task/screen tests passed, including EN/AR selector
configuration and browser callback revalidation. The bounded-reference API test
passed on disposable database
`erms_messaging_test_acl_1c07f14dbecb44ae91db15818b75d597`, which was dropped.
English security dropdown and Arabic hold-search results were inspected in the
in-app fixture preview. Full catalogue coverage/order and new-key validation
passed; the previously documented 12 unrelated full-Arabic validation findings
remain outside this change. The new Arabic Browse value remains a draft.

### Directional relationship selectors — 22 October 2026

- Requirement: keep Direction adjacent to Relationship type, after Related
  aggregation/Browse; display and search the localized directional name.
- Implementation: ReviewForm rebuilds only the type selector with an abandonment
  guard, retains its selected ID, and requests direction-aware review candidates.
- Verification: `test_relationship_direction_order_and_selected_label` covers
  both UI languages and switching back and forth;
  `test_relationship_candidate_direction_and_localized_search` covers forward,
  reverse, Arabic search, and symmetric names in a disposable database.
- In-app fixture browser verified English/LTR and Arabic/RTL field ordering and
  selected reverse labels. No catalogue keys, published translations, or database
  migrations changed.
