# Disposition aggregation terminology — 29 October 2026

The user-approved wording rule in Disposition revision 1.11 is implemented:
disposition interface text uses aggregation/aggregations and Arabic ملف/ملفات
where root/roots means an aggregation. Twenty disposition messages and the
related Governance Custody destination warning changed. Examples include
“Add selected aggregations to job”, “Completed aggregations”, “Minimum
aggregations” and “Affected aggregations: {count}”. Technical message keys,
placeholders, API identifiers and disposition rules remain stable.

The English and Arabic catalogues retain all 3,909 keys in the canonical order.
Each of the 21 revised Arabic entries preserves its former artifact and demo
translation/provenance in generation metadata. A fresh complete demo export
also captured two newer published administrator corrections (`email_acceptance_hint`
and `prepare_hint`); those were merged by key, preserving their provenance.
The other 3,886 Arabic artifact entries are unchanged.

All 21 new Arabic texts are imported, unreviewed drafts in **demo**, with
needs-review set and normal publication validation passing. Their prior
published text, publisher and publication date remain intact. Every explicit
draft update has a seeding audit event and user-request reason. All 3,939
unrelated demo translation rows, including inactive entries, were preserved.
Nothing was published. Review through **Translations → Arabic → Status: Draft**
and **Review state: Unreviewed** before publishing.

The managed local stack was restarted to load English source changes and the
seed no-op safeguard. Its missing-only workflow preserves the revised drafts.
The safeguard prevents a known superseded value from being “corrected” when
it already equals the current candidate, avoiding duplicate writes and invalid
correction/protection counts. The existing catalogue seed regression covers it.

Verification passed: **29 API/catalogue tests** in a uniquely named disposable
database and **315 frontend tests** across disposition screens, tasks, history,
progress, recovery and locale services. Both disposable test runs cleaned up
their databases. Exact active-key coverage/order, nonblank text, placeholders,
markup, approved Arabic terminology, prior provenance, hashes, configuration
authority, API template consistency and whitespace checks passed. The existing
mixed-addition UI assertion was updated for the approved aggregation wording.

Per-key before/after wording and application evidence are recorded in
[the verification record](disposition-aggregation-wording.json).
