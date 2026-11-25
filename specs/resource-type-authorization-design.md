# Resource-type authorization: approved query approach

**Status:** Query approach and existing read-path trade-offs approved — 18 November 2026; not implemented or benchmarked

**Inspected:** 18 November 2026

The [type specification](aggregation-and-record-types.md) defines the product
rules, including the approved shared-saved-search behavior. This document
records the approved set-based query approach and accepted existing read-path
trade-offs. It supersedes the earlier proposal for one authoritative database
evaluator across every authorization path. No general authorization rewrite,
role-resolver extraction, or policy-code generator is required by this decision.

## 1. What the inspection found

The current architecture has shared entry points and policy expressed in
Python and SQL. The user accepts these separate representations. The concern
addressed here is additional database queries and repeated authorization work
when reading/searching resources, not the number of files or policy expressions.

| Area and inspected source | Finding |
| --- | --- |
| [Python evaluator](../backend/services/api/authorization_policy.py), `resolve_effective_roles` and `authorize` | Independently evaluates effective assignments, maximum clearance, privilege union, ACL matching, and same-role governance clearance. Used for global privilege dependencies and access explanations; it is not the sole enforcement engine for resource routes. |
| [Database functions](../database/schema.sql), `disposition_private.original_aggregation_access` / `original_record_access`, `user_can_*_operation`, and `user_has_governance_clearance` | SQL independently evaluates overlapping privileges, effective assignments, clearance, and governance bypass. Aggregation and record access contain parallel implementations; operation wrappers call view checks plus operation privileges/permissions. |
| [Batch visibility](../backend/services/api/dashboard_visibility.py), `visibility_ctes` | Independently expresses effective roles, clearance, contextual/inherited ACL matching, and governance bypass as shared SQL sets. This is semantic overlap with the database functions, not merely a call to them. |
| [Resource adapters](../backend/services/api/resource_authorization.py) | Mostly call database functions, which is appropriate reuse. `require_clearance_for_level` and `governance_role_snapshot` also repeat role/clearance predicates. Audit attribution currently infers governance use from ACL failure; a type-only bypass would need explicit attribution. |
| [Access explanations](../backend/services/api/governance_authorization.py) | Loads facts and calls the Python evaluator. Its operation map and integrity adapter must remain aligned with actual enforcement; an explanation is not itself the enforcement path. |
| [Operation declarations](../backend/services/api/operation_policy.py) | Describe route policy for the generated inventory; the decorator does not execute authorization. A declaration alone cannot enforce the new gate. |
| [Saved searches](../backend/services/api/saved_searches.py), `_serialize` and `list_saved_searches`; [builder](../frontend/webui/advanced_search.py), `load_saved_into_workspace` | The serializer currently includes the stored definition, including in list responses, and Open loads it directly. The approved restriction requires filtering the server response before serialization, not only disabling Open. |
| [Continuity](../backend/services/api/authorization_admin.py), `assert_continuity`; [locking](../backend/services/api/continuity_lock.py) | Existing custody checks and shared/exclusive transaction locks are separate safeguards. They must participate in type-policy/reassignment transactions; passing the type gate is not a custody decision. |

The batch form was introduced to avoid repeated permission computation for each
candidate, file, and chunk. The [measured optimization lessons](../docs/postgresql-search-optimization-lessons.md)
explain why replacing it with per-row permission calls would be a regression
risk. Existing [differential tests](../backend/services/api/tests/test_dashboard_set_visibility.py)
compare its decisions with canonical database functions, within each resource
state scope. Separate policy expressions are not, by themselves, a reason to
refactor these paths. This inspection did not establish an authorization defect.

Consumers of the shared batch builder include search, cached-page revalidation,
dashboard, favourites, recent activity, and messaging text filters. Database
search views and retained-resource access also use database permission paths.
Updating only the Python evaluator, only normal resource views, or only the
interactive search endpoint would therefore leave gaps.

## 2. Approved query contract

For a search or resource-list query:

1. Resolve effective roles, privileges, clearance, and type access once within
   the SQL query, using shared authorization sets.
2. Apply those sets to all candidate resources alongside ACL checks.
3. Filter unauthorized resources before counting, sorting/ranking, pagination,
   and result caps.
4. Do not fetch candidates to authorize them in Python or the WebUI. The new
   type gate must not add separate visibility queries per resource, repeated
   permission-function evaluations per candidate, or independent repetition of
   authorization work across query branches.
5. Check current permissions again on each subsequent paging request using the
   same batched approach. Cached IDs/scores do not carry authorization forward.

Integrate type access into the existing shared SQL-building structure in
`dashboard_visibility.py` and its consumers. Derive ordinary See/Use grants
from the already-resolved effective roles, preserving each governance role's
own clearance for its bypass. Join candidates to the resulting type-access
sets; do not introduce a separate role-resolution query for each type or hit.
Reuse type-access results across branches with the same authorization context.

The query builder and database permission functions may express the policy in
different appropriate forms. Reuse helpers where useful and prove equivalent
decisions, including access explanations. A single database evaluator or
cross-language policy generator is not an acceptance requirement. The chosen
SQL shape must be justified by actual plans and timings, not by its use of a
particular function, view, or CTE syntax.

## 3. Accepted existing trade-offs and boundaries

The user explicitly accepts these cases of repeated work in the current
implementation:

| Existing path | Accepted behavior |
| --- | --- |
| [Page enrichment](../backend/services/api/search_page.py), `page_details` | A separate batched query computes page snippets, parent labels, component capabilities, and their authorization. |
| [Cached Global Search paging](../backend/services/api/search.py), `_global_search_page` | Records and aggregations are checked in separate batches; further batches can fill gaps caused by revoked access. |
| [Non-tab search fallback](../backend/services/api/search.py), `search_rows` / `_attribution` | Separate count/result queries and, when full-text attribution is requested, queries per returned item and condition. |
| [Relationship projections](../backend/services/api/crud.py), `redact_hidden_relationships`, and search index-freshness checks | Some SQL still calls resource permission functions rather than reusing the main query's authorization set. |

The once-within-SQL objective applies with these specified exceptions for
existing work. It is not a promise of one SQL statement or one authorization
calculation for the whole HTTP request. Eliminating these accepted cases is
not a prerequisite for resource types. They do not permit adding per-resource
queries or repeated type-access calculations: add the new gate as a reusable
set within each affected query, including fallback paths. Preserve existing
security checks and their separate resource/component scopes.

Creation, update, and deletion are outside this particular query-efficiency
concern. They still enforce the approved See/Use mapping, source/destination
type requirements, other gates, transactional revalidation, and custody
continuity. They need not adopt the same batching strategy as search.

## 4. Rationale and integration scope

Shared authorization sets avoid work that multiplies with the number of
candidate resources, files, or chunks. Filtering before counts and ranking
also prevents hidden resources from affecting totals or displacing authorized
results at the cap. The existing measured batch design provides a suitable
foundation; adding a new gate should extend it rather than reintroduce the
per-resource checks it removed.

Separate page and later-request checks can serve different disclosure needs
and reflect changed permissions. The user accepts their current cost. This
keeps implementation focused on adding type access, without making unrelated
query consolidation a condition of delivery.

Apply the new gate through all relevant shared paths: search, list/count,
cache revalidation, database read/operation checks, component access, and
access explanations. Preserve live/retained-resource distinctions and existing
operation declarations. Type access must not be enforced only in the UI.
Audit type-only governance bypass even when the resource ACL already allows
access, and retain existing custody checks for policy/reassignment changes.

For saved searches, retain the approved summary-only behavior when any explicit
type reference is forbidden. Collect type references from conditions and sorts
and resolve their access together; do not query permissions separately for each
condition or saved-search list item. Reuse those decisions for disclosure and
Open/Execute capabilities. Recheck on later requests; ordinary recipients must
never receive a forbidden definition. Independent administrative inspection
remains separate from normal builder access.

### Reading a resource’s type history

Type A → B is a historical fact about one resource. Once the caller has permission to read its history, expose the transition and both type names. Evaluate See against each side at read time. Protect the original snapshots centrally in the authorized audit projection so a history list, direct event read, search or export cannot return a second copy of a withheld value. Ordinary grants follow the effective-role union. A governance bypass uses that role’s own clearance against the corresponding historical security level. The stored history remains intact under the existing retention rules.

### Expected extent of refactoring

The inspected main search paths already build shared authorization sets, so
the type gate is expected to extend those sets and their joins rather than
replace the search engine, ranking algorithm, result cache, or pagination model.
Page enrichment and cached-page checks should reuse the extended batch builder.

Some older listing and non-tab search paths use scalar visibility predicates
or authorized views. These need targeted query changes so adding the type gate
does not introduce per-resource type lookups. Their existing separate count,
result, and enrichment stages may remain. Changes also reach database access
checks, explanations, and saved-search disclosure; this is more than a one-line
predicate addition, but a broad search/listing rewrite is not an architectural
prerequisite. Actual plans and regression results determine whether additional
localized changes are necessary. Type-specific value filtering, sorting, and
indexing are additional feature work, distinct from inserting the access gate.

## 5. Verification requirements

The [type specification, section 11](aggregation-and-record-types.md#11-acceptance-and-traceability)
remains the acceptance contract. During implementation:

- Identify every affected read/query path and record its existing accepted
  extra queries before making changes. Preserve this baseline for comparison.
- Test expected allow/deny results and equivalence across Python, canonical
  database functions, and batch SQL, with matching identity, time, and resource
  state. Cover See without Use, governance own-clearance limits, untyped
  resources, revoked grants, and changed effective roles.
- Inspect actual SQL plans and database statement counts for selective, broad,
  empty, denied, mixed-type, and many-type cases. Verify that the new type gate
  uses shared sets and introduces no per-resource database round trips or
  independent repeated authorization work across branches. Do not mistake a
  CTE's presence or a single SQL statement for proof of efficient execution.
- Cover both initial and cached-page requests, component evidence, relationship
  disclosure, saved-search list/read/restore/execute responses, and retained
  resources. Preserve counts, complete authorized ranking, deterministic paging,
  and current permissions.
- Run the required regression and performance gates in uniquely created
  disposable databases. Retain before/after timings, plans, exact expected
  results, JIT information, and cleanup evidence. Existing accepted repetitions
  are not failures merely because they remain; additional work and regressions
  introduced by the type gate must satisfy the performance contract.

Large-dataset acceptance uses more than 50,000 aggregations and 150,000 records
and a 1,000-result cap. Every measured response must meet the existing
three-second threshold. Include broad queries matching most or all resources,
with and without explicit type criteria, as well as selective, empty, denied,
mixed-type, governance, type-sort, and initial/cached-page cases. Measure every
changed search/list flow and preserve comparable before/after complete API
response times, individual samples, and exact results. A passing average or a
benchmark of an unrelated endpoint is not acceptance evidence. Fix new
threshold failures before declaring performance verification complete; the
accepted repeated read stages do not create a latency exception.

Preserve the separately documented 14 November compressed-storage exception
within its original scope. This approval neither broadens that exception nor
claims that the new gate has passed correctness or performance tests. The
current task changes specifications only.
