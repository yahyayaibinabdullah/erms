# Return to task aggregation review

Approved requirement: preserve the task Aggregations tab, page, filters, sorting
and last-opened membership when navigating back from aggregation details.

Implementation: job_screen receives the existing navigation entry's saved state
and remember callback. Membership page loads save only view state and identifiers;
no API result cache is introduced. Open saves its membership identifier before
resource navigation. Restored pages fetch current data, mark a visible authorized
match with the localized Last viewed marker and scroll to it. Nested details do
not change the saved originating navigation entry. State is scoped to the existing
user navigation trail and job/task entry. Missing state keeps the normal default
Current task/Job details tab. Missing or inaccessible rows get no marker.

Verification: 89 English/Arabic task UI tests passed, including page-three,
filter, sort and page-size restoration, marker identity and saving a newly opened
row before navigation. Real NiceGUI preview inspected in the in-app browser in
English and Arabic: Aggregations selected, page 3 retained, marker visible on the
middle row, scrolled into view, existing Wathiq table styling preserved. No demo
data was changed and no migration is needed.

Catalogue: one new key disposition.ui.last_viewed in English and the maintained
Arabic artifact. Arabic remains a generated draft requiring administrator review;
no existing wording or provenance was replaced. Coverage/order/hash, new draft
validation and catalogue reference checks passed.
