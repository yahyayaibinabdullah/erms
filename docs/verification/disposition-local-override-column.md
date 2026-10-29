# Disposition local-override column — 29 October 2026

The reported defect was a presentation binding in the job membership table:
the Local override value contained the effective classification rule's origin,
while Effective retention-rule source displayed only its periods and action.
Read-only inspection confirmed that all four members of **DT-2026-2** use
classification rules and have zero rows in `aggregation_retention_rules`.

`frontend/webui/disposition/screens.py` now keeps the assigned classification
in Classification, puts the actual rule origin alongside periods and action
under Effective retention-rule source, and displays **No local override** for
classification-sourced rules. A real aggregation-local rule still displays
**Local override**. Unknown or redacted rule data uses the existing unavailable
marker, avoiding a false assertion that an override is absent. No API calls,
caches, retention rules, memberships, authorization or disposition behavior changed.
Destruction Process revision 1.6, aggregation-list contract and DEST-23 record
the approved presentation correction.

The bilingual real-workspace regression
`test_member_rule_origin_is_separate_from_local_override_and_unknown_is_not_absence`
checks assigned CHILD classification versus defining PARENT classification,
periods and action, a genuine local override, unavailable information, redaction,
and one bounded membership request. The complete disposition frontend and locale
suite passed **479 tests** in 14.12 seconds. Its temporary log is
`/tmp/erms-local-override-tests.log`. Compilation, current/stale keys, sorted
active-key coverage, Arabic terminology, blank/placeholder/markup validation,
provenance, hashes and whitespace checks passed.

Live verification used the real API/WebUI and a unique disposable database
initialized from the canonical schema. One admitted aggregation inherited its
classification rule and another retained a genuine local rule. Both English
and Arabic correctly distinguished those values, retained standard Wathiq table
presentation and repeated navigation refreshed the bounded membership page.
Arabic was published only inside the disposable fixture for visual verification.

- [English comparison](disposition-local-override-column/english.png)
- [Arabic comparison](disposition-local-override-column/arabic.png)

The English and Arabic catalogues add one key,
`disposition.ui.no_local_override`, for **3,914 active keys**. The Arabic draft is
**لا يوجد استثناء محلي**, with generation provenance, current hashes and a
human-review flag. All 3,913 retained artifact entries and deprecated history
are unchanged. No administrator export was promoted and nothing was published
in demo. The managed stack was restarted successfully. Its missing-only seed
stored one new Arabic draft, protected 3,913 translations and corrected none.
A read-only comparison verified all **3,965 existing Arabic database rows**
were exactly preserved. The new draft remains unpublished and unreviewed.

No demo aggregations, classification rules, local rules, memberships or user
preferences were modified. No persistent database test suite ran. Both the
successful disposable preview database and the failed first fixture-setup
database were dropped; their absence and removal of the temporary connection
file were verified. The owned preview services and browser tab were closed.
