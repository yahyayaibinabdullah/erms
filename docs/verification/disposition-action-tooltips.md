# Disposition action tooltips and Arabic draft coverage

Requested on 26 October 2026: every disposition/destruction action icon must
have a translated tooltip, including the Review Proposals actions; populate
untranslated Arabic drafts and maintain coverage during future UI work.

The disposition screens use native NiceGUI button tooltips and existing
QTooltip slots inside their established Wathiq tables. All 52 directly defined
icon buttons now have tooltips. Previously missing slot tooltips cover proposal
details/revision/withdrawal, note history, review-round proposals/report generation,
retained-record details and job selection. Existing localized accessible names
and operation gates remain in place. The disabled job-selection button uses a
focusable inline wrapper so the tooltip can explain why it cannot be selected;
a disabled native button cannot receive pointer events. No CSS overrides,
new caches, collection downloads or supporting requests were added.

Browser verification used the actual ReviewForm and job picker, production table
styles and English/Arabic catalogues with bounded in-memory preview responses.
The proposal revision tooltip rendered as “Revise proposal” and “تعديل المقترح”.
Arabic document direction was RTL. Disabled picker actions exposed the localized
selection restriction in their tooltips. Table header, action and pagination
presentation remained consistent with existing Wathiq tables.

The existing Arabic canonical artifact already covered all 83 active untranslated
messages in demo. The explicit seed now accepts `--missing-only`, which fills
untouched source copies while skipping even declared superseded corrections.
The default correction mode remains available for deliberate repair deployments.
A disposable-database regression checks preservation of a published superseded
translation, draft-only filling and repeat-run idempotence. AGENTS.md and the
internationalization maintenance guide require future UI changes to supply
Arabic drafts and fill the authorized demo queue without publication.

Demo result: 83 drafts filled, zero active untranslated messages remain; all
3,793 pre-existing non-source-copy Arabic rows were compared and unchanged.
Nothing was reviewed or published. Four deprecated source-copy rows remain
outside the active queue. Seeding evidence is retained locally in
`.runtime/translation-repair/result-oct26.json`.

No English keys were added/removed/changed for tooltips: existing contextual
labels are reused. One invalid, unreviewed machine draft,
`disposition.ui.history_held`, was corrected to the approved Legal Hold glossary
wording; its previous value remains in `superseded_translations`. No curated
wording or administrator export was replaced/promoted. All 3,833 active keys
have matching Arabic coverage/order, nonblank text and placeholder contracts;
the catalogue hash and approved terminology checks pass. Generated drafts still
require administrator review before publication.

Verification: 262 disposition WebUI tests and 24 localization tests passed.
The localization suite ran only against uniquely named disposable databases,
initialized from schema.sql and dropped afterward. Both the normal Arabic seed
and the new missing-only path passed their existing regressions. Environment
synchronization and whitespace checks passed; no environment variables or
schema changes were introduced for this request.

The managed local stack was restarted to activate these changes; API, WebUI,
MailDev and all managed backend workers passed the launcher health checks.
