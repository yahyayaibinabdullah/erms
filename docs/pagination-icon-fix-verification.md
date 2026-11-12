# Administration pagination icons

**Status: fixed and locally verified on 12 November 2026.**
The user explicitly approved this repair. Changes remain local and uncommitted
on `refactor-API-python-file`, preserving previous work.

## Cause and correction

Five buttons passed Boolean `icon-right` to Quasar, whose icon renderer expects
an icon-name string. This caused `TypeError: u.match is not a function`.

Every affected button already supplies a valid icon through NiceGUI's `icon`
argument. The fix removes only the invalid extra Boolean prop, preserving that
existing icon, wording, styling, enabled state and event callback. Credential
Previous/Next retain their existing language-dependent arrow directions.

The three application files and their consumers are:

| Owner | Affected consumers |
| --- | --- |
| `administration_cards.py` | Profiles, security levels, users, roles, organization units |
| `login_sessions.py` | Global and user-scoped session administration |
| `text_indexer_details.py` | Text-indexer credential paging |

No API/schema, permissions, translations, navigation/history, request or cache
changes are introduced. Existing valid `icon-right=<name>` uses are preserved.

## Requirement → verification

| Requirement | Verification |
| --- | --- |
| Valid icon values in every affected consumer | Fourteen real-widget cases: seven consumers × English/Arabic |
| Preserve paging callbacks and bounded requests | First/Previous/Next/Last offsets, credential next/previous offsets and existing session/collection tests |
| Correct native icons without browser exceptions | Exactly one expected glyph per button; zero browser-error assertions |
| Preserve enabled boundaries and empty results | First/last-page controls; filtered-empty administration and session lists |
| Preserve keyboard operation | Native Enter activation of pager buttons |
| Preserve RTL behavior | Arabic rendering; existing credential arrow mapping asserted |

## Verification

- **51 interaction tests passed**, including the 14 new icon/paging cases and
  existing login-session, credential and collection-localization coverage.
- **50 unit tests passed** for bounded collections, filter requests, save refresh
  and feature boundaries: **101 focused tests** in total.
- The corrected before-fix run fails all 14 new cases on the invalid Boolean prop.
  Captured pre-fix factories run in memory; working-tree source is not replaced.
- **Chrome 157.0.8103.51 and Edge 157.0.4341.46 passed**, each with 15 check
  groups and 28 screenshots. All seven consumers pass in both English/LTR and
  Arabic/RTL. The checks verify exactly one expected icon per button, keyboard
  paging, offsets, disabled boundary controls and applicable empty states.
- Native visual inspection covered shared administration, session and credential
  pagers in both directions. Credential arrows retain the existing RTL mapping.
  Both final runs recorded zero browser errors, unsuccessful API requests or
  server tracebacks. No deletion, revocation or credential rotation was performed.
- All 187 recorded application/harness source hashes per run match current files;
  screenshots and regression-test source hashes are retained. The icon audit
  confirms that remaining `icon-right` uses specify explicit icon names and the
  old browser-error allowances are gone.
- Catalogue coverage, approved Arabic terminology, ordering, nonblank wording,
  placeholders, provenance and unchanged catalogue hashes pass. Configuration
  authority, API template consistency, Python syntax and `git diff --check` pass.
- All **seven uniquely named disposable PostgreSQL databases** were initialized
  through the canonical runner and dropped, including the unsuccessful attempts.
  An independent catalogue query confirms removal; no owned test processes or
  native drivers remain. No persistent database was used for the tests.

The maintained collection, security, organization, session, text-indexer and
assembled-application browser journeys now require zero errors instead of
allowing the old icon exception. A reusable `pagination` browser scope verifies
all seven pagers with disposable synthetic data: 51 matching rows for each
administration list, 41 sessions and 11 credentials. Credentials are metadata-only
fixtures; the one-time setup key is discarded and not captured.

This is focused local verification, not a full-suite, CI or timing benchmark.
No catalogue keys, wording, placeholder contracts, ordering or Arabic provenance
change. No translation export or persistent database translation is modified;
no new translation review is required.

## Development evidence

The initial Arabic test locator resolved labels outside its client context. It
now resolves them inside the actual page client. The credential fixture also
echoes requested offsets so its Previous control reflects a real paged response.
Initial development results are retained separately from acceptance.

Chrome's first run stopped at the version guard before the test journey: the
installed browser was `157.0.8103.51`, while the earlier snapshot expected
`157.0.8103.40`. Application metadata confirmed the new version. The rerun uses
that version with the already-cached driver; this task installed or updated
neither browser nor driver. The first run's disposable database was removed.

The first synthetic paging seed omitted the required organization unit on its
roles. Both runs stopped during fixture creation; their transactions rolled back
and databases were dropped. The fixture now supplies the existing test unit.
No schema constraint or application rule was changed.

A later native attempt passed the complete English security-level pager, then
typed into Profiles during its initial empty-to-loaded render. Both drivers
reported a stale element. The new journey now uses the existing collection
readiness pattern: wait for the previous list to be replaced and loaded cards
to appear before editing its filter. The failed evidence is retained; no
application change was required.

## Retained evidence

- [Acceptance record](verification/pagination-icon-fix/acceptance.json)
- [Chrome results](verification/pagination-icon-fix/chrome/browser-results.json)
  and [Edge results](verification/pagination-icon-fix/edge/browser-results.json)
- [Focused before/after comparison](verification/pagination-icon-fix/focused-comparison.json),
  [interaction results](verification/pagination-icon-fix/interaction/tests.xml)
  and [unit results](verification/pagination-icon-fix/unit/tests.xml)
- [Application changes](verification/pagination-icon-fix/application-change.diff)
  and [remaining icon audit](verification/pagination-icon-fix/icon-audit.json)
- [Validation](verification/pagination-icon-fix/validation.json),
  [database cleanup](verification/pagination-icon-fix/database-cleanup.json),
  [process cleanup](verification/pagination-icon-fix/process-cleanup.json)
  and [file hashes](verification/pagination-icon-fix/manifest.sha256)

The defect is moved to the corrected section of the
[defect register](webui-refactor-existing-observations.md). Earlier phase reports
remain historical evidence of the original error. No branch, worktree, staging,
commit, history, remote or system-setting changes were made.
