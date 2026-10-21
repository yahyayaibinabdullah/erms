# Disposition eligibility layout

Verified on 21 October 2026 in the in-app browser against disposable canonical-schema
databases. Both databases were removed after verification.

- The existing NiceGUI expansion starts collapsed and remembers toggles per
  signed-in user in browser user storage, independently of My tasks and language.
  Live checks confirmed expansion and collapse survive return navigation in
  English, and expansion survives return navigation in the Arabic profile.
- Baseline headers used computed `vertical-align: middle`. Supported NiceGUI
  column `headerStyle` now sets the seven labelled headers to `top`, verified
  in LTR and RTL (with right alignment retained). The empty selection header has
  no label. Existing Wathiq table presentation, pagination and selection remain.
- 56 focused screen/task tests passed, including restored expanded/collapsed
  choices in both languages, no refetch on toggling, and abandoned callback guards.
- No visible wording or translation artifacts changed. As in the task inbox
  preview, unpublished Arabic disposition labels fall back to English.

Screenshots: [English, collapsed](english.png),
[Arabic profile, expanded](arabic-expanded.png).
