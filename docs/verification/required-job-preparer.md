# Required job preparer — 3 November 2026

Approved requirements: disposition §10.1.0–10.1.1 / DISP-26 and destruction
§2.1, §5.1, §5.4 and job-creation clarification. Preparer is mandatory for all
new jobs, both standalone and from selected aggregations. Standard/Simplified
accept Officer or Manager preparers; Manager Only requires a Manager. A Manager
may add initial aggregations for the assigned Officer without taking over that
task. The saved route and current access/clearance checks remain authoritative.
No special post-creation unassigned-job dialog was introduced.

Implementation: creation form and API model; canonical guard, preparer and task
eligibility; bounded assignee queries and membership projections; migration
095 and fresh-install baseline. Certificate attribution omits the Records
Officer row when preparation was actually completed using a Manager role.

Verification:

- 19 focused database-backed tests passed: creation, missing/null API and SQL
  rejection, no numbering side effect on rejection, both profiles/all job types,
  self-preparation and submission through Standard/Simplified, delegated
  additions without task takeover, saved-route selectors and certificate
  participant routing. One additional delegated-admission test passed: the
  Manager cannot admit material the assigned Officer lacks clearance to view.
- 45 WebUI tests passed, including English/Arabic defaults, required validation,
  and unchanged number/reason behavior.
- Two disposable databases proved exact fresh/upgrade disposition catalogue
  parity, repeat-safe migration application, and preservation of a legacy empty
  unassigned job, resources, tasks, command receipts and event history.
- The wider initial run passed 170 tests. Eight newly changed expectations/test
  setups were corrected and passed the focused rerun above. Thirteen legacy
  foundation failures also reproduce against the unchanged HEAD schema in a
  separate disposable database: transfer fixtures lack a required governance
  creator profile, and older task fixtures attempt to claim tasks already
  automatically assigned. They remain pre-existing test debt; the entire
  foundation suite is not reported as passing.
- All test databases were dropped by their runners, including failing runs.
  No test suite targeted `demo`.
- Live `demo` browser inspection confirmed the Manager defaults into Preparer
  and clearing it blocks Save before creation. A temporary, database-free
  preview of the actual component verified both English/LTR and Arabic/RTL
  required-field guidance, without changing anyone's language preference or
  creating jobs. Screenshots: [English](required-job-preparer/english.png),
  [Arabic](required-job-preparer/arabic.png). The preview uses the new Arabic
  drafts; normal application publication still requires approval.
- Four new keys (`disposition.ui.preparer`, `preparer_guidance`,
  `preparer_required`, `required_fields`) were merged into the English and
  canonical Arabic artifacts, sorted by complete key: 3,978 matching keys.
  All 3,974 prior Arabic entries and per-item provenance were preserved exactly;
  the four new drafts passed wording, terminology, placeholder and artifact-hash
  checks. The strict machine terminology generator still flags existing curated
  entries (for example Vital Record wording and `Re:`); those protected entries
  were preserved, not regenerated or claimed to pass that stricter check.
- Repository catalogue-reference/order/coverage and environment-authority checks
  passed. No environment templates or private environment values changed.

Migration 095 was applied to authorized local `demo`; its jobs, assignments,
tasks, memberships and command receipts were compared before/after and remained
unchanged. An initial attempt rolled back because a diagnostic assertion about
DT-2026-3 was no longer current; the final application validates preservation
of the current state instead. The official Arabic seeder with `--missing-only`
stored four new unpublished drafts, replacing zero existing translations.

Local detailed logs and disposable upgrade probe are retained under gitignored
`.runtime/required-job-preparer/`. Apply migration 095 to colleagues' existing
databases through the normal upgrade process, then restart API/WebUI; fresh
installations use the current canonical schema and baseline.
