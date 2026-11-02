# Disposition jobs filtering and sorting

The jobs screen retains Wathiq's PageTable, standard expansion and grid
components, and server pagination. No CSS override, new cache, catalogue key,
permission or schema change was introduced.

- All five data columns filter and sort; translated owner/person values are
  resolved in SQL before filtering, ordering and paging, without row-by-row API
  requests. Canonical names remain searchable. Sort keys are allowlisted and
  all values are bound SQL parameters.
- Expansion state uses `disposition_job_filters:<authenticated-user-id>` in
  existing browser user storage; default is false. Lifecycle, type, text filters,
  unassigned selection and sorting retain the existing page-view mechanism.
- 32 WebUI regressions passed, including restored filters, sort-key mapping,
  disclosure callback, bounded concurrent initial requests and page state.
- 16 API query regressions passed against a new disposable database, including
  combined filters, localized display/search, counts, offsets, every allowed
  sort and rejection of invalid input. The disposable database was dropped.
- In-app browser checks of the real screen with fixtures verified default
  collapse, all controls, filtering, table headers and standard light-blue
  styling in English and Arabic/RTL. The temporary preview was cleaned up.
- Logs: `.runtime/job-filters-ui.log` and `.runtime/job-filters-api.log`.
