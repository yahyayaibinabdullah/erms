# Task inbox layout verification

Verified on 21 October 2026 against a uniquely named disposable database initialized
from the canonical schema, using the in-app browser.

- Filters use NiceGUI's standard expansion component and start collapsed. The
  choice survives navigation and reloads in the same browser, keyed by signed-in
  user ID in NiceGUI user storage. Switching accounts preserves separate choices.
  Toggling the panel makes no additional API requests; abandoned-page callbacks
  cannot update the preference.
- Before the change, all 16 table headings had computed vertical alignment
  `middle`. NiceGUI column `headerStyle` now sets `vertical-align: top` for this
  table. No custom stylesheet is needed. All 16 headings were verified as `top`
  in LTR and RTL, retaining the established table presentation and sorting.
- Live checks covered initial collapse, expansion and collapse across return
  navigation, reload persistence, and account isolation. Screenshots show the
  desktop layout at 1440 × 900: [English](english.png) and
  [Arabic profile with filters expanded](arabic-expanded.png).
- The Arabic preview publishes eligible reviewed translations only; existing
  unpublished task labels fall back to English. RTL direction and right-aligned
  headings were verified. No translation keys, wording or provenance changed.
- The task and disposition screen tests passed (52 tests). Catalogue coverage,
  ordering and reference checks, approved Arabic terminology checks, and
  `git diff --check` passed.
