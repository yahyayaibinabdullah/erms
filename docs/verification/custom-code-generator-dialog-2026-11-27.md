# Custom code generator dialog corrections

**Date:** 27 November 2026. **Status:** Implemented and verified locally.

The generator listing and New/Edit dialog now use the standard white settings
surface. The “all types” hint appears only when the generator is not restricted
to one type. The checkbox now says “Apply only to one type”. Its underlying
applicability and validation rules are unchanged.

## Observed causes and correction

- `messaging-workspace` applied `#f5f8fc` to the generator listing and dialog.
  Reusing `application-settings-page` removes that messaging-specific tint and
  retains the established RTL row/field corrections. Tab bars inherit white.
- The dialog's `full-width` option stretched its card across the viewport.
  NiceGUI's Dialog exposes no size arguments, and the default minimized Quasar
  card limit overrides ordinary width classes. The option was removed and only
  this card receives dimensions through NiceGUI's supported `style()` API.
  Desktop width is half the previous width; height is two-thirds of the
  previous height. Viewport-bounded minimum sizes keep narrow screens usable.
  No global stylesheet or other dialog size was changed.
- The card's flex layout shrank the tab-panels container, whose hidden overflow
  clipped the taller panel. The outer card had no overflow left to scroll.
  A standard NiceGUI `ui.scroll_area` now owns the available tab-content space
  (`flex-1 min-h-0`). The heading, name, tabs, reason and action footer remain
  outside it. Settings, preview and history content can scroll independently
  of the footer; long help text remains fully reachable.
- The applicability hint was rendered unconditionally. It is now omitted when
  “Apply only to one type” is checked. Checking shows the type selector;
  unchecking removes it and restores the all-types hint.

## Browser verification

The in-app browser rendered the actual production components and application
styles with a deterministic in-memory API fixture. This layout verification
used no persistent database or stored generator changes.

| Viewport | Before | After | Observations |
| --- | --- | --- | --- |
| 1692 × 895, English | 1644 × 847 dialog | 822 × 564.66 dialog | Half width, two-thirds height; white surface; full scope help reachable |
| 1692 × 895, Arabic | Same original sizing rules | 822 × 564.66 dialog | RTL labels/actions; white surface; no horizontal overflow |
| 375 × 812, English | — | 327 × 509.33 dialog | Scrollable form; full scope help reachable; Save within dialog and viewport |
| 375 × 812, Arabic | — | 327 × 509.33 dialog | Scrollable form; full 64px-high scope explanation visible; no horizontal overflow |

Both New and Edit were opened. All three tabs were inspected. The preview
rendered five fixture values, R10 through R50. Checking/unchecking the type
restriction showed/hid the correct hint and selector in English and Arabic.
The existing light-blue table headers and standard table controls were retained
and inspected against the standard white settings panel. Temporary viewport
settings were reset and the owned preview server was stopped.

Screenshots and measurements are in
`.runtime/custom-code-generators/ui-refinement-20261127/`:
`english-new.jpg`, `english-edit.jpg`, `english-list.jpg`,
`english-desktop-help.jpg`, `english-narrow.jpg`, `english-narrow-help.jpg`,
`arabic-edit.jpg`, `arabic-narrow.jpg`, `arabic-narrow-help.jpg`, and
`layout-metrics.json`. The source-rendered preview is retained in `preview.py`.

## Checks and translation handoff

- Existing generator interaction suite: **19 passed** using
  `PYTHONPATH=. frontend/webui/.venv/bin/python -m pytest frontend/webui/interaction/tests/test_code_generator_administration.py --asyncio-mode=auto -q --tb=short`.
  The initial invocation omitted auto mode and failed to initialize async user
  fixtures; both logs are retained. No product fix was needed for that setup.
- Catalogue reference/stale-key/ordering validation passed.
- Canonical Arabic artifact completeness, placeholders, nonblank text,
  provenance and catalogue hash checks passed for **4,337 keys**.
- Approved Arabic terminology validation passed across 1,006 contextual uses
  of the 35 glossary mappings.
- Exactly one definition changed: `code_generation.ui.named_type`, in
  `frontend/webui/i18n/messages.en.json`. The corresponding generated Arabic
  draft in `messages.ar.generated.json` now reads «يُطبّق على نوع واحد فقط».
  Its former machine wording is retained in the guarded superseded-value map.
  All other translation entries and their provenance are unchanged when
  compared by message key. No key was added/removed and no administrator export promoted.
- The repository's explicit Arabic seed utility ran against authorized local
  `demo` with `--missing-only`: 4,337 protected, zero stored/corrected/failed,
  zero awaiting generation. Existing translated wording was preserved and
  nothing was published. The revised canonical Arabic wording requires human
  review; existing database wording is not replaced by the missing-only seed.

Application source changes are limited to `code_generator_administration.py`
and the two message catalogues. Existing backend, search, schema, specification
and implementation-plan changes remain intact. No optimization was performed.
The frontend process must reload/restart to pick up changed code and its cached
English catalogue. All changes remain local and uncommitted.

## Follow-up: 150px taller

The user then requested another 150px of dialog height. New and Edit now add
150px to the preceding responsive height, retaining the viewport maximum.
At 1692 × 895, English New and Arabic Edit measure **822 × 714.66px**;
the scrolling body grows from 234px to 384px. At 375 × 812, Arabic Edit measures
**327 × 659.33px**, also exactly 150px taller. The footer remains inside the
visible dialog, and there is no horizontal overflow. Browser viewport overrides
were reset and the owned in-memory preview was stopped. No UI wording changed.

Evidence: `taller-english-new.jpg` and `taller-layout-metrics.json` in the same
runtime evidence directory. The earlier screenshots/table retain the original
correction for comparison.
