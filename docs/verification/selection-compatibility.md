# Compatible aggregation selection and Standard job creation — 5 November 2026

> Follow-up: [Reviewer setup](review-setup.md) supersedes the technical warning
> wording and documents load/Refresh checks and the retained skip exceptions.
> The original verification results below describe the creation amendment.

Contract: Disposition §10.2 (revision 1.22) and Destruction Process §5.1.1,
§7.1 and DEST-28 (revision 1.20).

The eligibility page checks the displayed selected roots immediately, without
extra checkbox requests. Mixed disposition types and organizational trees with
no common ancestor disable Add and show inline explanations. Sibling branches
are allowed when they have a common ancestor: Records Unit + Audit Office may
prefill GM’s Office. This supersedes the earlier same-chain interpretation.

The chooser filters before server counts and pagination. It shows only the
matching disposition type and, for destruction, the exact nearest common owning
unit. It excludes higher ancestors and narrower/unrelated units. New-job creation
prefills type and nearest owner and explains the scope. The saved job’s admission
checks remain authoritative, including partial results, current access,
clearance, blockers and organizational scope. A Records Unit job cannot admit
Audit Office material without a compatible owning-unit change.

New Standard destruction jobs require the nearest configured effective File
Administrator role (inheritance allowed) and the owning unit’s directly designated
managing role. Both must have at least one currently effective assignment to an
active person. Future/expired assignments, inactive people/roles/organizational
branches and service accounts do not count. An empty nearer File Administrator
role cannot fall back to a staffed higher role. Multiple assignees are valid.

Save is disabled for missing definitions, missing effective assignments, pending
checks and failed checks. Inline messages distinguish definitions from staffing
and identify every problem. Owner/type changes recheck facts; obsolete and
abandoned responses cannot change the form. The create command checks readiness
again in the database, and rejected commands leave no job/task, number-counter
change or receipt. The form remains disabled during a command and supports retry
after a reported error. Existing jobs and other routes/types retain their
behavior; later routing still requires current access and clearance.

## Implementation and freshness

`queries.owner_review_setup` batches bounded selected/displayed owner IDs through
one SQL helper, shared with the creation trigger. No complete directory or
hierarchy is downloaded. Role facts are form-local snapshots, keyed by selected
owner and current request revision, with no shared cache. An owner change
invalidates the snapshot; failed checks fail closed. The command always reads
current database facts; a readiness rejection refreshes owner facts and updates
the disabled state and specific warnings. Language and identity remain isolated by the page/client.
The UI uses existing NiceGUI labels, buttons, selectors, enabled-state binding and
Wathiq PageTable components; no new CSS workaround or optional assets.

Migration `103_standard_destruction_owner_roles.sql` is required before deploying
the new API/UI on existing databases. Fresh databases receive the same definitions
from standalone `schema.sql`; `baseline.sql` records 103 separately. The migration
adds two private functions and an INSERT trigger; it does not rewrite jobs.

## Verification

- **460 UI checks passed**, including both languages, type/owner compatibility,
  configured/unconfigured/unstaffed roles, route exclusions, owner-change races,
  abandoned dialogs, pending Save, duplicate-click prevention and retry behavior.
- **19 fresh-schema creation checks passed**, including the 16 direct readiness
  cases and existing reason/HTTP contract checks with valid creation fixtures.
- **16 upgrade checks passed** in a fresh disposable database initialized from
  committed schema plus separately applied required reference data and migration
  103. They verify missing/empty/future/expired/inactive/nearest-inherited role
  cases, atomic rejection, stale HTTP previews, allowed alternative routes and
  canonical function/trigger parity.
- **36 routing checks passed** after adapting existing-job fixtures to satisfy
  creation readiness, then restoring their old configuration for subsequent
  lifecycle scenarios. The fixtures reuse current roles and do not weaken the
  production gate. Direct gate tests deliberately bypass this fixture helper.
- **70 schema/configuration tool checks and 12 terminology checks passed**.
  Configuration-authority, API-template consistency, Python compilation and
  whitespace checks also passed.

Live browser checks used the production components and Wathiq styling with
explicitly labelled in-memory sample data. English and Arabic render the missing
role/assignment messages with Save disabled. A configured/staffed form enables
Save; clearing the owner disables it; reselection with fresh valid facts clears
the warning and enables it again. Earlier screenshots also show type mismatch,
disconnected trees and exact chooser scope. No job was created through the QA UI.

- [English unstaffed roles](selection-compatibility/english-unstaffed.jpg)
- [Arabic unstaffed roles](selection-compatibility/arabic-unstaffed.jpg)
- [English ready form](selection-compatibility/english-ready.jpg)
- [Arabic ready after recheck](selection-compatibility/arabic-ready-after-recheck.jpg)
- [English mixed types](selection-compatibility/english-types.jpg)
- [Arabic mixed types](selection-compatibility/arabic-types.jpg)
- [English disconnected trees](selection-compatibility/english-branches.jpg)
- [Arabic disconnected trees](selection-compatibility/arabic-branches.jpg)
- [English scoped chooser](selection-compatibility/english-chooser.jpg)
- [Arabic scoped chooser](selection-compatibility/arabic-chooser.jpg)

## Translation and local deployment

This change adds 12 contextual English keys and best-effort Arabic drafts on top
of the prior 4,028 active keys, for 4,040 total. The generated Arabic artifact was
merged by key; all existing wording and provenance were retained. No administrator
export was promoted or replaced. English ordering, exact language coverage,
nonblank values, placeholders, catalogue references, new-entry terminology and
provenance, and the artifact hash passed. A pre-existing legacy entry without
per-item provenance was preserved rather than inventing provenance for it.

Migration 103 was applied to authorized `demo`. Before/after JSON hashes proved
its existing four jobs, tasks, memberships and event history unchanged. The
recorded stack was restarted. Its explicit missing-only Arabic seed imported
12 drafts, protected all 4,028 existing translations and reported zero failures
or awaiting-generation entries. Readback confirmed the new Arabic entries are
unpublished drafts; human review/publication remains required. No environment
settings changed. Colleagues with existing databases must apply migration 103.

The broad release-ledger checker still reports previously documented unrelated
application-configuration/source-anchor drift. This is not a claim of a complete
phase or full release acceptance; the changed requirements are linked to the
implementation and focused evidence above.


## Broader legacy test limits

A broader 197-case creation/foundation/membership run passed 181 cases and found
16 failures. Three direct creation fixtures needed the newly required role
configuration and were corrected, then passed with the readiness tests. The
remaining **13 foundation failures were reproduced against the prior committed
schema without migration 103**, in a separate disposable database. They concern
older preparer-profile expectations and claiming already auto-assigned tasks;
they are not acceptance evidence for a regression introduced by this gate. Their
production behavior was not weakened to make legacy tests pass. A separate
36-case current routing suite passed. This change does not claim a clean full
repository suite. All nine disposable databases used in these checks, including failed exploratory
runs, were independently verified absent after cleanup; the temporary browser verification server/tab were also closed.
