# Physical preparation report actions — 2 November 2026

Destruction specification §14.1 / DEST-37 now presents an existing report through
one main **View preparation report** action and a secondary **More** menu:
**Download PDF** and **Create updated report**. The accompanying note explains
that updating saves a new version and keeps earlier versions. If generation
has not produced a report, the authorized Manager instead sees **Generate
preparation report** beside the existing pending-report guidance.

`frontend/webui/disposition/physical.py` uses standard NiceGUI Button, Menu and
MenuItem components, following existing Wathiq secondary-action menus. The
existing `detail-action-row` presentation supplies wrapping and logical RTL
order. No new CSS or Quasar layout fallback is needed. The main action and More
icon retain localized tooltips. Menu items have explicit accessible menu-item
roles, and native keyboard opening/dismissal works.

## Behavior and verification

Preview and download still address the same saved record/component/document;
neither generates a report. Generation uses the existing protected command,
role, optimistic version, retry identity and post-save refresh. Independent
preview/download/generation permissions remain authoritative, and there is no
empty More menu. Inactive-page guards prevent starting reads or painting late
results. Rendering the actions adds no API request or cache.

All **22** checks in `frontend/webui/tests/test_disposition_physical.py` pass,
including English and Arabic, six access combinations, the saved-document
preview/download callbacks, generation failure and exact retry, initial
generation, abandoned responses, and physical-confirmation validation.
No database-backed test suite was run.

Live in-app-browser checks rendered the actual controls and application
stylesheet at 1280×720 and 390×844. Both languages expose two report controls
outside the menu. The native menus fit within the phone viewport: English
x=186.48–352.11px (165.63px wide), Arabic x=87.31–220.65px (133.34px wide).
Client and scroll widths agree. Language navigation, reopening the menu and
keyboard dismissal retain the controls and expected direction.

## Catalogues and local application

Three existing keys changed: `disposition.ui.preview_physical_report`,
`disposition.ui.download_physical_report`, and
`disposition.ui.generate_physical_report`. Three keys were added:
`disposition.ui.physical_report_more`,
`disposition.ui.update_physical_report`, and
`disposition.ui.physical_report_update_hint`.

Both checked-in catalogues contain 3,971 active keys in the same lexicographic
order. Each new/changed label has a generated Arabic draft; prior generated
wording/provenance is retained in the changed items' metadata. All other Arabic
items are unchanged, and no administrator export was promoted. Catalogue
references/stale keys, nonblank/placeholder/markup validation, artifact hash,
the approved Arabic glossary checker, and `git diff --check` pass.

The managed local stack restarted successfully with the new controls. Its
official `--missing-only` synchronization stored three Arabic drafts, protected
3,968 existing translations, and reported zero failures/corrections/awaiting
generations. Changed-source translations are marked for review while their
existing wording is preserved. Arabic drafts remain unpublished for human
review and reconciliation. The isolated preview is closed after verification.

## Evidence

- [English menu](physical-report-actions/english-menu.png)
- [Arabic menu](physical-report-actions/arabic-menu.png)
- [English phone menu](physical-report-actions/english-menu-narrow.png)
- [Arabic phone menu](physical-report-actions/arabic-menu-narrow.png)
