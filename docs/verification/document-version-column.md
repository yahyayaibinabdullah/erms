# Combined document version column — 3 November 2026

The approved Evidence and documents presentation has one sortable **Version**
column, displaying **Version 2 · Current** or **Version 1 · Earlier**. The
separate Version status column is removed. Template revision stays separate.

The existing Wathiq PageTable is retained. Its column name and server sort key
remain `evidence_version`; only the displayed field becomes the localized
`version_label`. Numeric evidence versions, generated preparation-report
versions, current/earlier determination, document history, actions and server
pagination remain unchanged. No new endpoint, request, cache or migration.

Verification:

- 11 existing artifact/template UI tests passed; catalogue reference, ordering,
  coverage and new-key terminology/placeholder/hash validation passed.
- Live local `demo`, DT-2026-3: inspected the standard light-blue table with six
  document rows, a single Version column and **Version 1 · Current**. Clicking
  its heading issued the existing paged request with `sort=evidence_version`,
  `limit=25`, `offset=0`, and received HTTP 200. See
  [live English table](document-version-column/live-english.png).
- A temporary database-free preview of the actual documents panel, using
  unchanged Wathiq table styles and synthetic evidence versions 2/current and
  1/earlier, verified Arabic/RTL text, column order and alignment. See
  [Arabic table](document-version-column/arabic.png). Its tab/server were closed.
- During editing, an invalid catalogue parameter type was caught and corrected
  to `integer`; focused tests and catalogue checks were rerun successfully.
  The live WebUI was reloaded and verified operational afterward.
- Two contextual keys were added: `disposition.ui.document_version_current` and
  `disposition.ui.document_version_earlier`. Canonical English/Arabic artifacts
  remain sorted with 3,981 matching keys. Existing translations and provenance
  were preserved. The official `--missing-only` seeder stored two new
  unpublished Arabic drafts in `demo`, protected 3,979 prior entries, and
  reported zero replacements, failures or missing generated values.

The destruction specification's workspace requirement and
`docs/disposition-workflow.md` document the combined Version column. No
business documents or versions were changed and no database test was needed.
