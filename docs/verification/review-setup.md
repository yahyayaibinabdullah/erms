# Remaining reviewer setup — 5 November 2026

Contract: Disposition revision 1.23 §10.2 and Destruction Process revision 1.21
§5.1.1 / DEST-28. The latter contains the normative scenario/exception table.

## Deliberate exceptions

New Standard destruction jobs require both designated, currently staffed
reviewers before Save. For an **existing** job before routing into File
Administrator review, no designation anywhere on the owning unit's ancestor
chain still **skips** File Administrator review. A configured but inactive or
unstaffed nearest role blocks; it cannot be skipped or bypassed for a higher
role. A designation removed from the owning unit may still inherit an ancestor's
role normally.

A task already in File Administrator review is not automatically cancelled or
rerouted by a read/Refresh. Existing administration/reassignment and current-task
eligibility remain authoritative. Unit Manager must be directly designated on
the job owner and staffed while that review remains. Completed/skipped reviews
are not reopened: at Unit Manager review only its own setup matters, and from
Records Manager review onward neither earlier setup causes these warnings.
Terminal jobs, other disposition types and other routes are excluded.

The warning does not confer authority: authorized Save is retained; losing one's
own current role/claim/access can still prevent editing. Existing permitted
returns for correction remain available and require comments. File Administrators
still have Complete review only and do not gain Reject/Return.

## Implementation and freshness

Migration 104 adds a private, read-only `job_review_setup` projection and updates
creation/progression validation. `route_review` is unchanged, including its skip
and existing immutable skip event. No new entity, status, monitor, notification
campaign, worker or automatic assignment was added. Existing job/task/proposal
history is not rewritten.

The authorized jobs/workspace response carries two advisory booleans under
`review_setup`: `file_administrator_missing` and `unit_manager_missing`.
Jobs use one batch over the server page's IDs; there is no directory fetch or
shared result cache. Page load/Refresh reads current facts. Identity/language
remain scoped to the existing client; current commands independently check the
database. Creation owner/type changes retain their request-revision and abandoned
response guards. No additional page requests or polling are introduced.

The Jobs list places a compact warning under the existing job number. Job/task
views place the detailed simple message above the tabs. Existing Wathiq PageTable
headers/borders/pagination and NiceGUI controls are retained. Submit/Complete
review are disabled when a remaining reviewer is unavailable; a stale command
rejection also disables repeated progression without discarding comments.
Authorized Save and existing correction actions are not disabled by this gate.

## Verification

- **65 upgrade cases passed** after initializing a unique disposable database
  from committed schema plus separate required reference data, then applying
  migrations 103 and 104. Coverage includes original routing/no-role skip,
  current assignments, missing/expired/future/inactive roles, atomic rejected
  creation/submission, fresh read/repair behavior, current-task preservation,
  later-stage exclusions and canonical function parity. The original routing
  function body was compared directly with the committed definition.
- Fresh-schema checks passed **39 cases**, followed by the focused File
  Administrator Save/blocked-completion case (**1 passed**). This also verifies
  retained notes, no task advancement and rollback. A draft test originally tried
  to give File Administrator a Reject action; verification confirmed that the
  existing contract prohibits it, and the test was corrected without changing
  that authorization rule. Other-route/type and terminated-job exclusions pass.
- **466 UI/catalogue checks passed** in English and Arabic: creation warnings,
  obsolete/abandoned responses, pending/busy Save, paginated jobs Refresh,
  disabled progression before/after Save, stale command handling, existing review
  forms/footer and preservation of previously curated Arabic entries.
- **82 schema/configuration/terminology tool checks passed**, plus configuration
  authority, API-template agreement, Python compilation and whitespace checks.
- Exact 4,043-key ordering/coverage, nonblank values, placeholders, disposition
  aliases, new-entry terminology/provenance and artifact hash passed.

Live browser verification used production components and Wathiq styling with
explicitly labelled **in-memory samples**, without mutating a real job. Checked
English/Arabic creation Save blocking; Jobs warning and Refresh removal; task
warning placement; editable comments and successful Save with Submit disabled;
then repair + Refresh removing the warning and enabling Submit. Repeated
navigation and both document directions were verified. Existing tables provided
the presentation comparison; no custom layout CSS was added.

- [English Jobs](review-setup/english-jobs.png)
- [Arabic Jobs](review-setup/arabic-jobs.png)
- [English task](review-setup/english-task.png)
- [Arabic task](review-setup/arabic-task.png)
- [English creation](review-setup/english-create.png)
- [Arabic creation](review-setup/arabic-create.png)

All five disposable databases used for this amendment, including exploratory
failed test runs, were dropped and independently confirmed absent. The temporary
preview server and tab were closed. Database-backed tests never targeted `demo`.
The broader release-ledger checker still reports pre-existing unrelated
application-configuration/reference-source and legacy anchor drift. This is
focused amendment evidence, not a full repository/release acceptance claim.

## Translation and deployment

Ten contextual definitions and best-effort Arabic drafts replace seven obsolete
technical UI messages: 4,040 → 4,043 active keys. Other wording and provenance
were preserved; the retired previously checked-in entry is retained under
`deprecated_items`. The database retains deprecated definitions/translations and
immutable history. No administrator export was promoted or whole artifact
regenerated.

Tested migration 104 was applied to authorized `demo`. Before/after JSON hashes
confirmed four jobs, 24 tasks, 16 memberships and 361 disposition history events
unchanged; the routing function body was identical. The recorded stack was
restarted and its explicit missing-only seed imported ten Arabic drafts,
protected all 4,033 other active translations, and reported zero corrections,
failures or awaiting-generation entries. Readback confirmed all ten are
unpublished drafts matching the artifact. Human review/publication is required.
API/WebUI health checks passed after restart.

Colleagues must apply migration 104 after 103 before deploying the matching
API/WebUI. Fresh databases use standalone `schema.sql`; `baseline.sql` registers
104 separately. Local startup imports missing Arabic drafts and preserves existing
translations. No environment settings or manual data repair are required.

## Literal punctuation in reviewer warnings

The create-job warning originally showed `General Manager&#x27;s Office` while
the owner selector correctly showed `General Manager's Office`. The shared
catalogue renderer HTML-escapes interpolated values; passing that string to a
NiceGUI label's literal text property displayed the entity verbatim.

The initial correction decoded one escaping layer in `review_setup_message`.
The later cross-screen correction supersedes that workaround: the shared
renderer now returns literal text for NiceGUI text properties and the warning
uses it directly. HTML/template boundaries explicitly escape messages; quoted
NiceGUI properties use Python quoting. See
[shared text rendering verification](shared-rendering.md) for the broader audit,
role-ordering regression and English/Arabic browser evidence.

**184 focused UI checks passed**, including 32 new punctuation cases in both
languages. Live browser checks reproduced the original failure before the fix,
then verified the actual create-job components in English and Arabic with the
same punctuation. The preview used in-memory sample data; no organization name,
translation wording, catalogue key, provenance, reviewer rule or database schema
was changed. The local stack was restarted to load the fix.

- [Correct English apostrophe](review-setup/english-punctuation.png)
- [Correct Arabic/mixed-direction apostrophe](review-setup/arabic-punctuation.png)
