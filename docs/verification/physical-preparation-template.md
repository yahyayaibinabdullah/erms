# Physical preparation collection report — 2 November 2026

The user approved the **By collection location** mockup. Destruction §14.1 /
DEST-37 now specifies this layout. No manual collection checkboxes were selected.

## Requirement and implementation

| Approved behavior | Implementation and verification |
| --- | --- |
| Group by effective current collection location; unknowns last | `document_snapshots.collection_rows` orders the complete existing free-text location, classification code and aggregation number. It never invents room/shelf components or substitutes assigned for current location. Pure and inherited-location database tests cover these distinctions. |
| Clear collection rows | Three columns show continuous serials, aggregation number/title with classification code/medium, and current location. Different assigned locations appear secondarily. Common ownership appears once; distinct owning units retain row attribution even when their display names match. |
| Prominent organization and appropriate language | Existing Disposition organization override and localized root-unit fallback are reused, along with the request values-language setting. Bilingual values use separate Arabic/English paragraphs; preferred English values use LTR table order. Headings remain bilingual. Titles and locations retain their authoritative stored text. |
| Concise, accurate totals | One summary counts physical/mixed aggregations to collect, physical records and mixed records once. Physical/mixed descendants beneath digital parents remain listed. Source snapshots retain the checksum, legacy descendant counts, classification totals and attribution. |
| Stable version history | A new repository `physical-preparation-report.default.v2.docx` and dedicated deterministic builder leave retained v1 bytes intact. Additive presentation keys allow retained v1 snapshots to validate/fill. Existing command receipts bypass regeneration and preserve saved PDFs, template reference and presentation after later setting/location changes. |
| Readable pages | Top-aligned serials, expanding unsplit aggregation rows, full-width location headings kept with their first row, repeating column headers, and job/version plus dynamic PAGE/NUMPAGES footer. Actual PDF font verification requires embedded Changa. |

The authoring source is `tools/build_physical_report_v2.py`; rebuild output
matches `defaults.json` exactly. The v2 checksum is
`401e16eed3dd92323ef68d79e8ff8a8a03ba7d474e8aea9bd3c12b7566d51881`.
Retained v1 remains
`8afe1ebaa45c87ee05993a64fec8aa4d358101ecc8aa5fe2d5199c9d11d06354`.

## Render evidence

All page PNGs were inspected after the final layout changes using the bundled
LibreOffice and Documents renderer. Five sample rows fit on one A4 page in
English and Arabic-first bilingual. A 30-row bilingual specimen with longer
titles spans five pages; all pages were reviewed for headers, wrapping, intact
rows, serial continuity, group boundaries, totals and footer placement. There
are no unresolved placeholders, substituted fonts or split summary-language
pairs. These specimens use illustrative data, not a production job.

- [English specimen](physical-preparation-template/english.pdf)
- [Arabic-first bilingual specimen](physical-preparation-template/arabic-first-bilingual.pdf)
- [Five-page specimen](physical-preparation-template/multipage.pdf)
- [Checksums and embedded-font results](physical-preparation-template/render-evidence.json)

The renderer was the bundled `LibreOfficeDev.app/Contents/MacOS/soffice`.
`SAL_FONTPATH` was supplied only to verification processes to expose the
repository's static Changa font to that bundled renderer. No font installation
or persistent environment change was required.

## Verification and local deployment

The focused physical presentation, physical workflow and controlled-template
regression run passed **81 tests** in a freshly created canonical disposable
database; it was dropped cleanly. The final focused run passed **11 tests**,
including the subsequent owner-identity refinement and additional real multipage
PDF case, and dropped its separate disposable database cleanly. These counts
overlap and are not added together. Database tests
never use `demo`. Source compilation, default validation and deterministic
template rebuild checks pass.

The requirement ledger updates DEST-37 and the destruction specification's
section coordinates/hash for revision 1.14. The repository-wide baseline checker
still reports 141 pre-existing findings concerning earlier unregistered
requirements, specification changes and schema anchors. Those unrelated entries
were not rewritten to make the checker pass; §14.1 and DEST-37 have explicit
implementation and test evidence here.

No schema migration, new setting, privilege or UI catalogue key is needed. The
local API/WebUI stack restarted and is healthy. Its first restart encountered a
MailDev command timeout; a retry through the existing launcher succeeded. The
official Arabic missing-only startup synchronization preserved all 3,971
existing translations, stored zero new drafts and reported zero failures.

A read-only inspection confirmed that `demo` uses the repository default for
physical preparation reports and has one earlier saved physical report. It was
not overwritten. On an eligible active physical task, **More → Create updated
report** saves a new version with the updated layout and current facts.
Administrator-uploaded template revisions continue to take precedence; this
change does not replace them.
