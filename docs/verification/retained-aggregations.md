# Retained aggregation list and Add action — 5 November 2026

Approved contract: Disposition revision 1.21, compact aggregation listing;
Destruction task aggregation navigation. Removed items belong in job History,
not an optional membership view of the Aggregations tab.

## Requirement → implementation → evidence

| Requirement | Implementation | Verification |
| --- | --- | --- |
| No Membership dropdown or Show removed control | `job_screen` keeps only the search field and existing table controls; removes membership/removal columns | Real NiceGUI tests in both languages; live English/Arabic checks |
| Current and processed retained roots remain visible | Membership read supports `state=retained`, excluding removed episodes before counting and paging | Live database queries cover removal/re-addition, foreign-job isolation, search/count/pagination and terminated lists; completion test covers processed units before and after final task completion |
| Completed/terminated jobs show retained lists automatically | All workspaces use the same retained predicate, with no user-selected state | Lifecycle-parameterized UI tests; live English/Arabic completed/terminated views |
| Old navigation state cannot restore removed/all mode | Ignore saved `members.state` and removed-column sorts | UI tests mount old removed/all state for each lifecycle; removal and return-navigation regressions |
| Add aggregations belongs beside the list | One button inside the members panel for job and task views; existing authority conditions retained | Parameterized job/task tests open the same picker and verify refreshed tab/identity; live button absent from Job details and present in Aggregations |
| Preserve bounded reads and existing actions | Existing `PageTable`, selection, commands and job-scoped picker | 362 UI tests covering task forms, removal navigation, bulk actions, picker, shared footer, pending proposals and existing screens |

**22 API checks passed** in the canonical-schema disposable database
`erms_messaging_test_acl_4abddd6f29764cdea8682e5f15c5979e`; the runner dropped it
after the run. No test targeted `demo`. The API suite includes existing query
authorization/redaction checks and the final-task certificate completion test.

Live browser checks mounted the production `job_screen` and existing Wathiq
stylesheet over in-memory sample data. Of 35 sample episodes, only 33 retained
entries are counted; removed episodes are absent. The active sample includes a
completed unit. No raw CSS, new cache, catalogue wording or database schema was
introduced. Existing translated labels and curated Arabic values are preserved.
Catalogue reference validation, configuration-authority and API-template
consistency checks, Python compilation and `git diff --check` passed. The
recorded local stack was restarted and reported healthy with the changes.

- [English active job](retained-aggregations/english-active.jpg)
- [Arabic active job](retained-aggregations/arabic-active.jpg)
- [English completed job](retained-aggregations/english-completed.jpg)
- [Arabic terminated job](retained-aggregations/arabic-terminated.jpg)

The broad disposition-baseline checker has unrelated pre-existing source-range,
unowned-requirement and historical schema-anchor drift. This amendment updates
the modified Disposition/Destruction source locators and its verification only;
it does not claim release-wide traceability acceptance.
