# Outdated verification checks repaired

**Date:** 28 November 2026

**Scope:** The user authorized correcting the two pre-existing failures reported
during custom code generator verification. Application behavior, schema,
migrations, permissions and search code are unchanged. All changes are local
and uncommitted.

## Documentation references

Six disposition-ledger references had outdated line numbers. Their section
headings and SHA-256 fingerprints still exactly match the current text, so no
contract content changed. Updated only those line ranges and added a dated
reconciliation record containing the before/after references:

| Reference | Previous lines | Current lines |
| --- | --- | --- |
| Classification scheme audit history, section 16 | 728–749 | 740–761 |
| Internationalization, section 14 | 1318–1319 | 1375–1376 |
| Internationalization, section 15 | 1358–1379 | 1415–1436 |
| Internationalization, section 16 | 1380–1394 | 1437–1451 |
| Internationalization, section 19 | 1451–1452 | 1508–1509 |
| Internationalization, section 21.1 | 1744–1844 | 1812–1912 |

All six original fingerprints, requirement text, phase ownership, completion
status and historical implementation/test evidence are preserved. The baseline
checker and its drift detection were not changed.

## Historical audit upgrade

Migration 046 predates the type-aware audit view introduced by migration 120.
Its test now compares the result with the independently pinned historical view,
instead of expecting migration 046 alone to produce the latest definition.

The test still executes the actual migration body. It additionally proves that
an event whose resource is inaccessible exposes actor ID/name/email in the
deliberately damaged fixture and hides all three after the upgrade. The entire
fixture is rolled back, with explicit checks that the current view, migration
markers are restored and the fixture audit row does not persist. The application view and both
migration files are unchanged.

## Executed verification

Evidence is retained under `.runtime/outdated-checks-20261128/`.

| Check | Result |
| --- | --- |
| Disposition baseline and acceptance-check test files | **34 passed** in 1.65 seconds; no failures, errors or skips. |
| Complete classification-scheme transfer suite | **132 passed** in 41.05 seconds; no failures, errors or skips. |
| Baseline command-line checker | Valid: 388 owned entries, 100 settings and four approved decisions. |
| Database lifecycle | Two newly created disposable databases initialized from the canonical schema; both dropped successfully. No persistent database was used for tests. |

The two failures from the [original generator verification](custom-code-generator-applicability-2026-11-27.md)
are resolved. Its original failed-run evidence remains retained; the affected
checks were rerun rather than rewriting the historical results or claiming a
new full-project run.
