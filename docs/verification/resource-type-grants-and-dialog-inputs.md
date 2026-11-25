# Resource type grants and dialog inputs

Both catalogues use the same administration dialog. Resource editors and Advanced Search share the same scalar and choice controls. A passing API check alone cannot establish what a user can type, paste or select in those controls.

| Coverage | Regression |
| --- | --- |
| Definition dialogs in English and Arabic | The [Chrome scenarios](../../tools/webui_browser_resource_types.py) enter signed integers and exact decimals, reject incomplete defaults on Save, check native date and datetime controls, and choose Boolean values. They check text length, field and choice ordering, steppers, edit boundaries, and single-choice configuration. |
| Resource data entry and Advanced Search | The [interaction matrix](../../frontend/webui/interaction/tests/test_type_metadata_controls.py) renders both controls for each of seven types and each resource kind. It checks accepted wire values, rejection of invalid input, time-zone conversion, a Unicode text limit, and predefined choice IDs. [Literal tests](../../frontend/webui/tests/test_type_metadata_ui.py) cover signed integer overflow, invalid dates and times, nonfinite decimals and Boolean input types. |
| Grants, search and revocation | The [grant tests](../../backend/services/api/tests/test_resource_type_ui.py) cover Everyone, named-role union, administration authorization and the effective-role prerequisite. The [saved-search tests](../../backend/services/api/tests/test_type_search.py) exercise Global Search, direct reads, shared query disclosure, execution, and cached paging before and after grant revocation. |
| Adding several roles | The [browser scenarios](../../tools/webui_browser_resource_types.py) select Everyone on the first page and a named role on the next, search for both, change their checkboxes and save different permissions together. The [API tests](../../backend/services/api/tests/test_resource_type_ui.py) check stale versions, unauthorized callers, duplicate, missing or already granted roles, transaction rollback, and preservation of other grants. Both suites cover both catalogues. |
| Large datasets | The [visibility benchmark](../../tools/resource_type_visibility_performance.py) checks expected membership with Everyone on each resource kind. The [catalogue benchmark](../../tools/type_ui_performance.py) checks first and last pages of configured and available roles against a 1,200-role directory fixture. |
| Database upgrade | The [populated upgrade rehearsal](../../tools/check_resource_type_upgrade.py) compares schema dumps and existing records against a fresh installation. The [migration check](../../database/tests/migration_checks/123_resource_type_everyone.after.sql) verifies that upgrades introduce zero Everyone grants and enforce uniqueness. |

## Local results, 23 November 2026

All 12 Chrome workflows passed across English and Arabic. The focused WebUI
suite passed 60 tests. The migration suite passed 59 tests. The populated upgrade
produced the same schema dump as a fresh installation. The API regressions
exercised authorization explanations, ordinary and governance access, legacy
bulk policy updates, and revocation during Global Search and shared saved searches.

The large fixture contained 51,003 aggregations and 153,009 records. The limit
was three seconds for each measured response. On the local PostgreSQL 18.4 build
JIT was unavailable.

| Workload | Samples | Slowest |
| --- | ---: | ---: |
| Type visibility, paging and related operations, including Everyone | 128 | 2.748 s |
| Structured type search | 237 | 2.672 s |
| Type administration and picker requests | 180 | 0.072 s |
| Standard search and lists, with concurrent test activity | 1,524 | 4.929 s |
| Standard search and lists, repeated after the other test jobs finished | 1,524 | 2.519 s |

The first standard run exceeded the limit six times. The captured broad record
plan evaluated the type-access set once in 0.102 ms. In the repeat, all 1,524
requests met the limit. The cause of the first run's variance remains unconfirmed.

The 12 Everyone-specific queries returned the expected IDs, with a slowest
response of 1.734 s. The 24 requests for filtered granted/available role pages
returned the expected counts and IDs, with a slowest response of 0.058 s.
The disposable databases used for these runs were dropped.

### Multi-role picker verification

The focused runs passed 24 API tests and 51 WebUI tests. Chrome verified the
picker in English and Arabic for both catalogues. One run timed out selecting
French in a subsequent translation-editor step. The full repeat passed all
12 workflows.

On the large fixture above, six requests each added 200 named roles with mixed
See and Use grants in one transaction. The responses took 47–88 ms. All 24
filtered role-directory reads finished within 49 ms. All 186 catalogue and
237 structured-search samples met the three-second limit. The benchmark used
a separate qualified custodian to exercise grant changes on populated types.

### Role-code search

The eight focused API tests passed. They include a role whose code, display
name and Arabic translation are distinct, and verify the same code before and
after the role receives a grant. The 12 English and Arabic Chrome workflows
passed, including searches by a mixed-case code fragment in both role dialogs.
With 1,200 synthetic directory roles, all 36 code-filter requests returned
the expected pages and counts in 4–256 ms. All 222 catalogue requests and 237
structured-search requests met the three-second limit.

### Type administration privilege rename, 23 November 2026

Migration 125 keeps both privilege IDs and groups both codes under Administration.
The API checks covered delegation in both directions. A role granted only
`aggregation_types.administer` could maintain aggregation types and received
HTTP 403 for record-type administration. The converse passed for
`record_types.administer`. The upgrade also carried a published Arabic label
to the new key with its wording and publication metadata intact.

The Phase 6 integrated collection passed 501 cases. The three focused delegation
and catalogue cases, the populated text-index rollback/retry case, and all 59
migration and canonical-schema tests passed. All 1,680 WebUI unit tests, 684
interaction tests, and 12 English/Arabic Chrome workflows passed. The English
and Arabic catalogue and terminology checks passed.

The five performance runs used 51,003 aggregations and 153,009 records on local
PostgreSQL 18.4 without LLVM JIT. Every measured request met the three-second
limit. Both additional timed text-edit commits finished within 0.016 seconds.

| Workload | Measured requests | Maximum seconds |
| --- | ---: | ---: |
| Standard search and lists, including type-specific text | 1,712 | 2.5461 |
| Larger text, including type-specific text | 643 | 2.9586 |
| Structured type search | 237 | 1.3874 |
| Type catalogue and role pickers | 222 | 0.0696 |
| Visibility and grant changes | 128 | 1.2922 |
| Broad queries and legacy saved searches after upgrade | 105 | 2.5914 |

All 296 standard, 19 larger-text and 24 upgraded result files with matching
baseline files compared byte for byte. The fresh and upgraded schema dumps
matched. The disposable databases were dropped. Per-request timings, plans,
rankings, browser screenshots, host I/O and cleanup records are in the local
evidence directory `.runtime/type-privilege-125/`.
