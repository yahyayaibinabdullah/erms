# Compatible medium changes — verification

Approved rule amendment: 29 October 2026, specification revision 0.10,
section 8.1. The amendment replaces empty-only aggregation medium changes with
compatibility checks. The specification and implementation document explicitly
list Physical → Mixed, Digital → Mixed, pure-medium contradictions, both
Mixed narrowing cases, and every empty-root transition.

## Implementation evidence

`backend/services/api/main.py::update_aggregation` and the PostgreSQL hierarchy
trigger share `aggregation_medium_contents_compatible`. It validates all
contained aggregations, records and drafts without changing them. Existing
permissions, closure, reason, version and digital-component guards remain.
`MEDIUM_CHANGED` retains its old/new medium, actor and reason.

The WebUI recognizes medium error codes, renders safe localized messages, and
marks the Medium selector using supported NiceGUI error properties. Selecting
another value clears the error. The editor retains all values after rejection.
No new catalogue parsing, collection fetch, page request or cache is introduced.

## Automated checks

- API medium, hierarchy, component, closure and version regressions:
  **78 passed** (`test_compatible_medium_changes.py` and `test_api.py`, before
  the ten additional explicit-transition cases were added).
- Final expanded medium-transition and localization catalogue regressions:
  **54 passed**, including the ten new transition cases, concurrency in both
  lock orders, audit/data preservation and migration idempotence.
- Focused bilingual validation, locale/catalogue runtime and canonical-schema
  regressions: **68 passed**.
- Broader frontend run: **212 passed, 1 pre-existing failure** in
  `test_entity_translation_editor_loads_selected_language_automatically`.
  The test searches for an editor-source marker absent both in the working
  tree and in pre-change commit `84b16cc0acff440df23dc9c2690664bf121d8771`.
  This translation-editor source assertion is outside the medium amendment.
- Canonical SQL function bodies match migration 092. A separate disposable
  upgrade initialized the pinned pre-change canonical schema, reference data
  and baseline; it reproduced the old empty-only rejection, applied migration
  092 twice, preserved records and successfully changed Digital → Mixed.
- Source key references, exact English/Arabic active-key coverage, placeholders,
  nonblank values, canonical ordering, generated provenance and artifact hash
  checks pass. All 3,914 existing active Arabic artifact entries and deprecated
  history are unchanged. Five generated drafts were added (3,919 active keys).
- Approved Arabic terminology: 916 contextual uses across 35 glossary mappings.
  Configuration authority, API template consistency and whitespace checks pass.

## Live browser evidence

A disposable database/API/WebUI exercised an open digital aggregation with two
digital records. Digital → Physical was rejected with the specific toast and
visible Medium error. The reason and form values remained. Selecting Mixed
cleared the error, saving succeeded and details showed Mixed with both original
digital records. Navigation and language switching reloaded current data.
Arabic Mixed → Physical was rejected and Mixed → Digital succeeded. A second
Arabic Digital → Physical attempt confirmed the same incompatibility feedback.
Rapid navigation away from Dashboard to Aggregations did not restore an
abandoned page. No layout or direction overrides were needed.

- [English Medium validation](compatible-medium-changes/rejected-ltr.png)
- [Arabic Medium validation](compatible-medium-changes/rejected-rtl.png)

The preview tab and owned services were closed; its database was dropped.
Arabic drafts were published only inside this disposable fixture for RTL checks.

## Demo application

Migration 092 was applied without modifying aggregation **1141/DEMO/012/2026**
(id 427), which remains Digital at version 7 for the user to retry. The managed
local stack activates the updated API/WebUI and seeds missing Arabic drafts
without publication. Read-only verification confirmed all 3,966 pre-existing
Arabic database rows were unchanged and five generated drafts were filled.
The live compatibility predicate permits Mixed and rejects Physical for the
user aggregation. API and WebUI health checks passed; all completed disposable
databases were absent. No environment settings or operator configuration are
required.

## Follow-up: repeated Medium selection (29 October 2026)

Demo logs at 10:52–10:53 showed `KeyError: error` during repeated medium
selection. The initial clear handler removed NiceGUI's required `error` prop.
It now uses the supported `control.error = None` setter, preserving validation
state. A bilingual regression changes the selector repeatedly after simulated
server errors and verifies that the required prop and cleared message remain
valid. All 14 medium-validation tests pass. This is independent of the later
10:57 acceleration conflict: aggregation 427 remained an active member of
DT-2026-2 with `removal_required_reason = reopened`, which the approved
no-active-job acceleration gate correctly rejects. No membership was changed.

The later [in-job acceleration amendment](../disposition-in-job-acceleration.md)
supersedes that historical no-active-job rejection for compatible reopened
members. The medium-selector correction remains unchanged.
