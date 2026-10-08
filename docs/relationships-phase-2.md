# Relationships Phase 2 implementation

Implemented 8 October 2026. This completes the standalone relationship UI;
section 7 remains owned by the future disposition/destruction implementation.

## Delivered behavior

`frontend/webui/resource_relationships.py` supplies relationship panels on
aggregation and record details, plus Relationship Types administration under
Records Management. Administration has separate Aggregation and Record tabs,
type creation and label editing with the entity-style Translations expansion and
enabled-language selector, activation/deactivation, and deletion
of unused types. Stable code, endpoint kind and symmetry cannot be edited.
In-use deletion returns the specific localized relationship error, including
PostgreSQL RESTRICT violations.

Panels show the name from the current endpoint, an authorized target or a
restricted-resource placeholder, and localized controls. Creation makes the
selected direction clear in a preview. Both-endpoint access is rechecked by
the API. Add/remove controls require `relationships.link`; metadata-edit
permissions are not used. Restricted targets have no navigation or removal
action and cannot be selected. Catalogue navigation requires
`relationships.administer` independently of linking authority.

Lists use server pagination and server sorting. Catalogue search, relationship
type search and target search are bounded; selected options are retained and
individual IDs can be hydrated. No relationship results are cached across
pages. Each visit and successful mutation requests a fresh list. Page/principal
identity and request revisions reject late responses after navigation, sign-out,
or a newer search. Selector requests use the existing cancellation/debounce
mechanism. Only the bounded relationship-type catalogue loads initially;
related resources wait for at least two typed characters. Selector type metadata is limited to
the current page and selected value.

Native NiceGUI cards, tabs, fields and rows reuse the existing messaging RTL
treatment. Tables reuse `erms-page-table` light-blue headers, borders and
spacing. A localized native pager replaces untranslated Quasar bottom labels.
English fields and stable codes remain LTR; Arabic fields remain RTL, including
when the surrounding UI uses the other language. No new custom CSS is used.

## Requirement evidence

| Requirement | Phase 2 implementation and verification |
| --- | --- |
| REL-01–REL-04 | Phase 1 evidence remains applicable; separate UI catalogues, bilingual forms, immutable identity controls, deactivation preserving links, and in-use deletion were exercised in the browser |
| REL-05 | Browser: record forward creation, reverse navigation/removal, refreshed source on revisit; aggregation reverse creation and opposite-endpoint navigation in Arabic |
| REL-06 | Browser: revoked target access produces a placeholder with no identifier/title/actions; bounded search returns no inaccessible match. API regression covers access revocation and denied removal; UI row test covers disclosure/action gating |
| REL-07 | Browser: custom profile with only aggregation/record view and relationships.link can create/remove links without metadata-edit authority; catalogue navigation is hidden. UI capability and row tests verify privilege separation; Phase 1 tests enforce current access on both endpoints |
| REL-09 | Phase 1 attributable catalogue/link audit and ordinary-deletion cascade evidence apply to the same UI APIs. Protected disposition review reasons remain deferred |
| REL-10 | Browser: 29 links paged on the server, search finds a target beyond the initial bounded page, opposite endpoint and revisited pages refresh. UI tests cover abandoned/late responses, bounded page requests, selected-ID hydration, last-page correction and error clearing; existing selector tests cover retained selections and search-label echo |
| REL-12 | Browser: English/LTR and Arabic/RTL catalogues, forms, forward/reverse names, actions, pagers, and relationship panels. Source/artifact validation covers coverage, canonical order, placeholders, blanks, terminology, provenance and hash |
| REL-08, REL-11, REL-13 | Deferred to future disposition/destruction work; not implemented by Phase 2 |

## Verification

- 58 disposable-database API tests passed across relationship APIs,
  localization catalogue and global privilege enforcement. After the RESTRICT
  error fix, all 12 relationship API tests passed again, including the exact
  localized in-use error contract.
- 33 WebUI tests passed across the Phase 2 module, existing remote selectors
  and navigation capabilities. These tests use synthetic responses, not a
  database.
- Live in-app-browser verification used a separate disposable database with
  synthetic administrator and view-only users, three aggregations, 30 records,
  and 28 initial links. Checked creation, directions, removal, catalogue
  editing/deactivation/unused deletion, redaction after access revocation,
  permission-aware actions, empty/error states, pagination, navigation and
  both languages. Compared rendered presentation with existing Wathiq
  membership tables and the shared collection-table style. Relationship
  headers measured `rgb(238, 247, 253)`, with 7px/16px padding; Arabic headers
  align right and English headers align left.
- Catalogue reference and approved Arabic terminology checks pass. API
  environment-template reconciliation and `git diff --check` pass.
- Every disposable regression database was dropped. The live-probe database
  and processes were also removed after verification. No persistent ERMS
  database was migrated, seeded, or tested.

## Localization and deployment

Added 43 `relationships.ui.*` keys to `messages.en.json` and merged only their
missing Arabic entries into the canonical `messages.ar.generated.json`.
Existing translations and provenance were preserved. No administrator export
was promoted. These new Arabic values are generated drafts requiring human
review and publication through the existing translation workflow. Publication
in the disposable database was solely a visual-test fixture.

Follow the Phase 1 migration and separate relationship-type seed deployment
steps, then restart the API and WebUI so message definitions and screens are
current. Explicitly run
`database/seeds/004_seed_generated_arabic_ui_translations.py` against each target
database before reviewing/publishing Arabic drafts. Restarting alone does not
replace English source placeholders with generated Arabic text. The Arabic
seeder preserves protected translations.
Grant the approved privileges to intended custom profiles through normal
profile administration. No environment variables or templates changed.

## Multilingual editor correction

The fixed Arabic inputs were replaced with the Users/Roles/Organization Units
translation pattern: canonical English names plus a collapsible Translations
section, enabled-language selector, and forward/reverse inputs whose direction
follows the selected language. Switching languages retains pending edits.
Creation submits all entered translations; editing patches only changed language
entries and preserves other languages. Optional translations can be removed;
Arabic remains required by the approved spec. Existing JSONB storage is reused,
so this correction requires no database migration or reseeding.

The type API accepts language-keyed `translations`; legacy Arabic payload fields
remain accepted for existing clients. It validates enabled language tags, trimmed
nonblank labels and symmetric names, preserves omitted languages, and accepts
null to remove an optional language. Catalogue search includes every language;
display uses exact language, base-language, then canonical English fallback.

Verified 13 relationship API regressions in a fresh disposable database and 9 UI
tests, including third-language persistence, removal, fallback, enabled-language
choices, and pending edits across language switches. Browser checks compare the
existing Role editor and verify Arabic/French creation and reopening in LTR and
RTL. The translation editor reuses existing labels. A later wording correction updates
`relationships.ui.symmetric` to “Same meaning in both directions” and its
Arabic generated draft; all other canonical Arabic values/provenance are preserved.
The revised Arabic draft requires human review. Restart API and WebUI to load this change.

English is included in the enabled-language selector. A language-keyed `en`
translation can override canonical English names; removing that override restores
the canonical names. Regional English tags use exact-tag, base-English, then
canonical fallback when those languages are enabled. The checkbox reads
“Same meaning in both directions” Verification adds an English override
API regression (14 relationship tests total) and covers English selection in
the translation-editor UI regression.

Catalogue panel spacing uses the native NiceGUI column `p-5` utility (20px on
all sides), consistent with existing detail panels. Browser inspection found
the catalogue host had zero padding before the correction. English/LTR and
Arabic/RTL measurements now show 20px insets for guidance, tabs, search/actions
and the pager; the standard table retains its own additional inset. No CSS
override, message-catalogue change or database change is required.

## Related-resource selector correction

The related-resource field reuses `RemoteSelect` and the shared remote selector
binder with a two-character minimum. Opening the form or field does not request
resource options; clearing or shortening a query retains only the selected value.
After the 200ms debounce, API searches match number, title or description and
return at most 25 authorized targets, excluding the source. Individual selected
IDs remain hydratable regardless of the search threshold. The API also enforces
the two-character minimum for ordinary target searches.

Browse reuses the existing classification/aggregation tree browser. Users drill
down through classifications and aggregations; record selection shows records
beneath their aggregation. Each branch is independently paged (50 items per
request). Only the requested resource kind is selectable, and the source cannot
be selected. Target visibility is rechecked before returning the selection. The
shared browser retains its existing RTL layout and adds no target preload or cache.

Verification: 15 disposable-database relationship API tests, 12 relationship UI
tests, including shared hierarchy traversal and selection for both resource kinds,
and 25 related search/capability tests.
Browser/API logs confirm zero target requests on opening or one-character input,
a bounded query for REC-030 beyond the first 25, and one-ID visibility recheck
on Browse confirmation. One new contextual key,
`relationships.ui.target_search_hint`, was merged into the English manifest and
canonical Arabic artifact; the Arabic draft requires review/publication.

Hierarchy browser verification: live English record selection and Arabic record
and aggregation selection passed. The existing RTL grid places expanders on the
right and selection actions on the left; no new CSS was needed. Browser testing
used a uniquely named disposable database, which was dropped after verification.
This tree-browser correction introduces no new translation keys, schema changes,
or environment settings.
