# Eligibility browsing guidance — 5 November 2026

Contract: Disposition §18.2. The standalone eligibility page opens as a browsing
view, without instructions assuming the user is selecting items for a job.

Removed the unconditional selection hint from `eligibility_screen`. The explicit
job-scoped Add aggregations dialog retains its existing `picker_hint` and owning
unit/type guidance. Filters, table selection, admission actions, API requests and
authorization remain unchanged.

The unused `disposition.ui.select_hint` alias, English definition and corresponding
Arabic entry were removed together. All other **4,028** Arabic entries and their
per-item provenance were preserved exactly; active-key order and coverage agree,
and the artifact catalogue hash was updated. Runtime catalogue synchronization
deprecates the retired definition and retains its translations and audit history.
No new keys, generated drafts, administrator export replacement or publication
is required.

**63 existing UI checks passed** across the general disposition screens and
job-scoped picker. Live browser verification mounted the production eligibility
component with Wathiq styling over in-memory sample data. Both English and Arabic
start with the filter control; the former hint is absent and the table and
selection action remain available.

- [English](eligibility-browsing/english.jpg)
- [Arabic](eligibility-browsing/arabic.jpg)

No database-backed test or persistent job mutation was needed. Catalogue,
configuration and source checks accompany this change; broad release-baseline
traceability still has previously documented unrelated drift.
All 4,028 active keys passed exact-order/coverage, nonblank, placeholder and
artifact-hash checks. Catalogue references, environment consistency, Python
compilation and `git diff --check` passed. The local stack was restarted; readback
confirmed the retired hint is deprecated and its saved translations remain.
