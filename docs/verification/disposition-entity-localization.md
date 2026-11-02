# Disposition task entity localization — 26 October 2026

The relationship-removal proposal editor now passes the current UI language for
both paginated links and selected-link hydration. It reuses the relationship
API's directional forward/reverse labels, including record relationships.

Membership projections resolve owning-unit names from saved translations.
Proposal projections resolve original/revising users and their roles. Job and
task workspace projections resolve owning units, assignees, role queues and
claimants. Exact language, base language and canonical fallback follow the
existing entity-localization contract. Translation dictionaries are removed
before responses; existing visibility/redaction checks remain in place.

These are bounded, uncached projections using existing joins. No additional
per-row requests, catalogue keys, translations, schema changes or data migrations
are introduced. Existing administrator translations are preserved.

Verification: 146 task/screen tests passed, including English and Arabic
selected-relationship hydration. Four membership and four proposal/workspace
localization cases cover English, Arabic, Arabic regional fallback and absent
French translation. Database tests used fresh disposable databases, dropped
afterward. The real proposal dialog was inspected in a local browser fixture in
Arabic RTL and English; the fixture selects labels from the request language,
confirming the dialog sends it. Standard table presentation is unchanged.
