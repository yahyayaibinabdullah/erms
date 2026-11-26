# Translations in entity Add and Edit dialogs

Classification schemes, classifications, users, roles, organizational units,
security levels and authorization profiles share an optional Translations
disclosure in Add and Edit dialogs. Its visibility uses the entity-specific
metadata right in the internationalization specification §11.4; navigation or
`localization.administer` alone grants no translation access. Aggregations and
Records remain outside this subsystem.

Choose an enabled language and enter a title/name or description. Switching
languages preserves drafts. Remove discards the selected draft locally before
Save. No translation reads or writes are made for an entity that does not exist.
Translations are optional. Creation dialogs do not show or require a translation
change reason, including Profile creation and retries after a partial save.
Editing retains the existing reason requirement and the shared Profile reason.

Save validates all form inputs before creating the item. The existing create
request carries canonical fields and, for a classification, its optional direct
retention rule. The WebUI then sends each pending locale through the existing
translation PATCH endpoint, using the created ID and each returned entity version.
Creation requests automatically supply the audit note `Initial translations
supplied during creation` to satisfy the existing PATCH audit contract.
The create schema, API endpoints, permissions and database remain unchanged.

These requests are separate transactions. If a translation fails, the entity
already exists. The dialog shows this explicitly, keeps drafts, and locks its
canonical fields. Save retries pending translations without creating a second
item or repeating successful unchanged locales. Revised drafts can remove fields
or a locale already saved. A conflict retains the draft and stale version; it
does not automatically overwrite a concurrent edit. Cancel keeps the entity and
any accepted translations; reopening Edit provides the ordinary current-version
translation workflow. Success notification and destination refresh wait until
all pending translations succeed. Repeated Save clicks cannot overlap writes.

## Ownership and regression coverage

| Requirement | Owner | Regression evidence |
| --- | --- | --- |
| Seven-entity disclosure and existing rights | `entity_editor.py`, `capabilities.py` | `interaction/tests/test_entity_creation_translations.py` |
| Local drafts, removal, cancellation, reason-free creation and edit-time reason validation | `entity_translation_editor.py` | shared translation and creation interaction tests |
| Created identity, version chaining, partial retry and explicit removals | `entity_creation.py` | `tests/test_entity_creation.py` and creation interaction tests |
| Retention-rule payload and accepted-save refresh | `entity_editor.py`, `classification_editor.py` | classification Save and collection-refresh tests |
| Real REST persistence | shared forms and existing API | assembled creation-translation tests on a disposable database |
| Reopen, English→Arabic, repeated switches and stale English responses | shared translation editor | `tools/webui_browser_entity_translations.py` in native Chrome; assembled tests for all seven entities |
| Repeated create/reopen across classification depths | shared forms and classification workspace | `tools/webui_browser_translation_stress.py` with visible-field assertions and disposable database ownership |
| Edit drafts, reasons, all-language Save, version conflicts and partial retry | `entity_translation_drafts.py`, `entity_translation_editor.py`, `entity_editor.py` | `tests/test_entity_translation_drafts.py`, `interaction/tests/test_entity_edit_translation_drafts.py`, real-API and native browser checks |

Frontend paths in this table are relative to `frontend/webui`; `tools/` paths
are relative to the repository root. Run the database-free
suites with `frontend/webui/.venv/bin/python tools/run_webui_tests.py`. Run real
REST tests only with `backend/services/api/.venv/bin/python
tools/run_webui_integration.py`, which creates, initializes and drops a uniquely
named disposable database. Never point these tests at a persistent database.

The creation partial-result status adds one English catalogue key and one generated
Arabic draft. The additional Edit status is described below. Existing translations
and their review/publication provenance are retained.

## Edit draft retention — 26 November 2026

The unsaved Edit issue was reproduced in all seven entities: entering English,
selecting the saved Arabic translation and returning to English discarded the
English text. The old loader only staged creation/definition translations;
ordinary Edit cleared its fields and fetched the saved values at every switch.

Edit now retains values, baselines and translation reasons per language in
`EntityTranslationDrafts`. Its scope is one open dialog and entity. Language is
the map key; there is no shared, cross-identity or persistent cache. First visits
read the current API value, revisits restore the local draft, and explicit reload
refreshes clean values while retaining dirty values. Close/Cancel discards this
state. A different entity version cannot silently rebase outstanding drafts.
A newer clean read invalidates all earlier clean language snapshots while
retaining reason notes. Returning to those languages fetches their current
values before further edits, avoiding a stale locale paired with a newer version.
Inputs remain disabled with their previous values while another language loads;
the loader applies the selected values together, without an intermediate empty
input update. This also avoids an observed RTL blank-Title result during the
browser check after a successful translation read.

Save validates every dirty locale before writing. It updates canonical metadata
once, then saves changed locales in language-tag order, chaining versions. Reasons
remain language-specific except for Profile's existing shared reason. Unchanged
and reverted locales are skipped. Clearing a single field sends null. The existing
immediate, audited Remove action is retained and preserves other drafts; clearing
all fields still requires Remove. Protected Role/Profile dialogs save translations
without canonical writes. Existing permissions and API/schema contracts are unchanged.

Accepted writes advance the local baseline individually. If a later request
fails, the dialog stays open, identifies partial success, retains pending values
and reasons, and locks canonical controls. Retry sends only pending translations
and does not repeat accepted metadata or retention-rule updates. Conflicts retain
the draft and stale version. Save and Remove writes are serialized, and form
controls cannot change during Save. Cancel retains changes already accepted by
the server. Creation keeps its existing multi-language, reason-free behavior.

The new partial-Edit status uses `entity_translation_editor.status.edit_pending`
in English and a generated Arabic draft. Existing Arabic text and provenance
are preserved by key; no administrator export is promoted. The Arabic draft
requires human review before publication.

### Verified Edit results

Final verification passed on 26 November 2026:

- The isolated full suites passed 1,715 unit tests and 800 interaction tests,
  with sockets and PostgreSQL access blocked before collection. Two additional
  retention-retry cases were then added; all fourteen classification Save-boundary
  cases passed, including retries after retention and locale failures.
- Eleven assembled real-API cases passed in a fresh disposable database. The
  seven entity cases create initial Arabic translations, reopen Edit, retain
  English and Arabic drafts and reasons across switches, and save both locales.
- Chrome 158.0.8127.88 and Edge 158.0.4370.33 each passed fifteen checks: sign-in
  plus all seven entities in English/LTR and Arabic/RTL. Visible input assertions
  cover creation drafts, unsaved Edit round trips, reason retention, all-language
  Save, reopening and Cancel. They also exercise a newer clean version that
  invalidates another language's old snapshot, delayed English reloads and a
  failed English PATCH after Arabic succeeds. Retry writes only English and
  does not repeat the accepted canonical or Arabic writes. Final application
  source hashes match both browser-run snapshots. Reopened Arabic Classification
  and Profile captures and the RTL partial-save status were visually inspected.
- All seven database-backed implementation-run lifecycle reports confirm
  disposable database cleanup, including earlier diagnostic attempts. No owned
  browser runner or WebDriver process remained.
- Active-key/stale-reference, ordering, nonblank, placeholder, approved terminology
  and hash checks passed. There are 4,196 active keys; all 4,195 prior Arabic
  entries and provenance are unchanged. The authorized local demo catalogue was
  updated with the explicit `--missing-only` seeder: one draft stored, 4,195
  protected, zero corrections/failures/awaiting-generation. Nothing was published.

Evidence is retained in ignored local output:
`.runtime/edit-drafts-complete-suites-20261126`,
`.runtime/edit-drafts-checks-20261126/retention-retries.xml`,
`.runtime/edit-drafts-real-api-20261126`,
`.runtime/edit-drafts-ui-chrome-verified-20261126`, and
`.runtime/edit-drafts-ui-edge-verified-20261126`. Source changes remain on the
existing branch, local and uncommitted. No API route, database schema, migration,
privilege or persistent environment configuration changed.

## Creation reason adjustment — 26 November 2026

Removed the translation reason field and validation from creation for all seven
entities, including partial-save retries. Creation supplies the fixed audit note
automatically; existing edit-time reason controls and validation are unchanged.
Updated the specification, dialog and browser regressions, and real-API tests.

Verification passed: 162 focused unit tests, 68 shared translation/creation
interaction cases, and eleven assembled real-API cases. These cover saving
without a reason input for all seven entities, retry behavior, initial direct
retention rules and unchanged edit-time reason validation. The disposable database
was dropped. Evidence is in `.runtime/entity-creation-no-reason-20261126`.
The browser journey now asserts that creation has no reason field; the full
browser suite was not rerun for this adjustment. Catalogue/stale-key and Arabic
terminology checks passed; keys and translated wording are unchanged, with only
the specification hash refreshed in the Arabic artifact.

## Reopening and language-switch investigation — 26 November 2026

The reported sequence is: create an Arabic Title, save, reopen Edit, select
English first, then select Arabic. The affected DEMO-1000 record's stored Arabic
Title and its initial-translation audit event were inspected read-only; the
value remained present. Storage alone does not establish correct display.

The focused native Chrome journey creates all seven multilingual entities
through their actual Add dialogs with Arabic Title/Name and Description, saves,
reopens Edit, and selects English→Arabic→English→Arabic. It also holds an English
response until Arabic has loaded, then releases English and asserts that Arabic
remains displayed. All seven cases passed on Chrome 158.0.8127.88. Screenshots
were retained, and the disposable database was dropped. Evidence:
`.runtime/entity-translation-reopen-create-switch-chrome`.
The same seven cases also passed on Edge 158.0.4370.33, including delayed
responses. Its disposable database was dropped; evidence is in
`.runtime/entity-translation-reopen-create-switch-edge-20261126`.

The assembled real-API creation tests also reopen all seven editors, choose
English before Arabic, and assert the displayed component values. Native browser
coverage supplements this simulator evidence by executing browser events and
checking rendered inputs. These passing checks have not reproduced the reported
blank Arabic Title and do not establish a root cause for that report.

An independent in-app browser session also reopened the stress fixture's
DEMO-2000 (Demo 2000), selected English, then selected Arabic. Both the visible
Title input and the accessibility tree contained `عرض توضيحي 2000`.

Two strict stress attempts stopped on a separate parent-screen read failure,
after the Arabic-field assertions had passed. The diagnostic attempt completed
161 cycles before an `httpx.ReadError` surfaced as a service-unavailable screen
for `GET /api/v1/classification-schemes/31`; no translation mismatch occurred.
The runner dropped that disposable database. Evidence:
`.runtime/translation-ui-stress-2000-diagnostic-20261126`. This connection failure
does not establish the cause of the reported language-switch symptom. No
production retry or translation behavior was changed on that basis.

The stress harness now records a visible service-unavailable navigation error
outside the dialog, captures it, and clicks the existing Retry button once. It
reports those events separately as `navigation_retries`. Translation loading and
display assertions remain strict; a blank, disabled or incorrect Arabic field
still fails without retry. Runner ownership/cleanup regressions passed (11
database-free tests).

### Stress run stopped at the user's limit

The user reduced the requested run from 2,000 cycles to 300. The stop signal was
issued when the progress counter reached exactly 300; one already running cycle
completed during shutdown, giving 301 completed UI cycles in 596.08 seconds.
All completed cycles showed the expected Arabic Title after reopening Edit and
selecting English first. There were 152 title-only cases, 149 cases with Title
and Description, 101 immediate switches and 200 switches after English loaded.
This final batch needed no navigation retries.

The planned run grouped 400 cycles per depth, so this interrupted batch covered
root classifications only. Separate shorter runs covered depths 0, 1, 2, 5 and
10. The final 20-cycle pilot passed four cycles at every depth and included
browser reloads; its evidence is in
`.runtime/translation-ui-stress-reload-and-ancestors-pilot-20261126`. This is
not evidence of 300 cycles at every depth or a completed 2,000-cycle run.

Final-run evidence is in
`.runtime/translation-ui-stress-2000-hierarchy-links-20261126`. Raw results retain
four worker-disconnection entries caused by the requested shutdown;
`user-stop.json` records the interruption and both counters. The run is marked
user-interrupted, not a completed 2,000-cycle pass. Its disposable database was
dropped, all fourteen investigation-run lifecycle reports confirm cleanup, and
no test runner or WebDriver process remained. All source changes remain local
and uncommitted.

At that investigation checkpoint, the reported blank Arabic Title remained
unreproduced and no production fix for that symptom had been claimed. The later
Edit draft and language-loading work above uses separately captured UI evidence.
The creation-dialog fix and reason-free creation behavior remain in the local changes.

## Local verification — 25 November 2026

- The isolated full suites passed: 1,708 unit and 760 interaction tests, with
  network/database access blocked before collection. After tightening the final
  partial-save canonical-control lock, all 1,708 unit tests and 68 focused shared
  translation/creation interaction cases passed again. The latter includes
  partial failure and retry for every one of the seven entities.
- Eleven assembled real-API cases passed on a uniquely named disposable database:
  initial translations for all seven entities, existing shared edit flows, and
  Classification creation with a direct retention rule plus translations.
- Thirteen Chrome browser checks passed in English/LTR and Arabic/RTL. Root and
  child Classification creation persisted their initial translations; both
  creation-dialog screenshots were visually inspected. Existing navigation,
  editing, lifecycle, history, and bounded hierarchy checks also passed.
- Every owned disposable database was dropped, including runs that exposed test
  helper issues. Persistent databases were not used for tests.
- Catalogue reference/stale-key and approved Arabic terminology checks passed.
  All 4,195 active entries are ordered, nonblank and placeholder-safe, and artifact
  hashes agree. The 4,194 pre-existing Arabic entries and provenance are preserved
  exactly. Only `entity_translation_editor.status.creation_pending` was added;
  its Arabic value remains a generated draft for human review. No administrator
  export was promoted and no existing wording was regenerated.

Legacy test helpers now choose canonical fields before same-named translation
fields and recognize the create/edit disclosure. The pre-existing extracted
aggregation-browser fixture also receives its owning module's globals, including
the classification label helper; its two failing cases now execute the actual
selection behavior without changing application code.

Reproducible evidence is under `.runtime/entity-creation-translations-*` (ignored
local test output): `regressions-final` contains the full suite reports and latest
unit rerun; `retention-verified` contains the eleven assembled cases;
`chrome-verified` contains browser results, source hashes, screenshots and database
lifecycle confirmation.
