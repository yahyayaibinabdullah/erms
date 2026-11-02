# Eligibility selection alignment — 30 October 2026

The disposition eligibility table now centers locks and checkboxes on the same
vertical axis, including when adding aggregations to an existing job.

Live inspection of the affected table found a 72px selection cell with 16px
horizontal padding and start-aligned content. The lock is 24px wide, while the
checkbox control is 40px wide. Their centers therefore differed by 8px.

The existing custom NiceGUI body slot owns the selection cell; column `align`
configuration applies to the data columns rather than this cell. The correction
uses the table's built-in `text-center` utility on that one selection cell.
It retains native checkbox selection, focusable lock tooltips, the standard
Wathiq table presentation and server pagination. No custom CSS, extra wrapper,
direction override, request, cache or translation change was introduced.

## Verification

The real screen and application stylesheet were rendered in the in-app browser
with an in-memory API fixture. Both controls have the same horizontal center:

| Viewport | Direction | Lock center | Checkbox center |
| --- | --- | --- | --- |
| 1280×720 | English LTR | 94px | 94px |
| 1280×720 | Arabic RTL | 1186px | 1186px |
| 390×844 | English LTR | 94px | 94px |
| 390×844 | Arabic RTL | 296px | 296px |

Vertical centering remains within 0.5px of each row's midpoint. Checking an
available row enables Add in both languages; Refresh clears selection and
disables Add. Unavailable rows retain locks rather than selection controls.
Repeated language navigation retains alignment. The light-blue headers,
borders, typography, pagination and row actions match the running Wathiq table.

All 43 tests in `frontend/webui/tests/test_disposition_screens.py` pass.
`git diff --check` passes. No database-backed test suite was run.

The managed local stack was restarted successfully. In the restored demo page,
all four locks and the checkbox share center x=415px (previously 407px versus
415px). The isolated preview was stopped and its tab closed after verification.

- [Running demo](eligibility-selection-alignment/demo-english.png)
- [English](eligibility-selection-alignment/english.png)
- [Arabic](eligibility-selection-alignment/arabic.png)
- [English narrow](eligibility-selection-alignment/english-narrow.png)
- [Arabic narrow](eligibility-selection-alignment/arabic-narrow.png)
