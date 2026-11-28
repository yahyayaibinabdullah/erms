# Custom code generator applicability verification

**Dates:** 27–28 November 2026

**Contract:** [Approved specification revision 0.6](../../specs/custom-code-generators.md),
especially CG-02, CG-06, CG-09–13. All changes remain local and uncommitted.

**Follow-up:** The two outdated checks recorded in this original run were repaired
on 28 November, without changing application behavior. All 166 affected-suite
tests passed and both new test databases were dropped. See the
[repair report](outdated-checks-2026-11-28.md). Original results below are retained
as the historical run, not replaced with a new full-project result.

## Implemented behavior

Primary Text fields offer **All items**, **Untyped items only**, and **One
selected type**. Only the third choice shows the type picker. Type-specific
Text fields remain restricted to their defining type. The listing and immutable
history describe applicability in English and Arabic.

Untyped-only and individual-type generators can coexist on the same primary
field. All-items generators overlap both populations and are rejected. The
database enforces this during simultaneous saves, including transactions with
older snapshots. Final creation, draft commit, direct file drop, recommendations
and field hints all use the same population membership rule. Changing an
existing item's type does not generate a new number.

Migration 127 preserves existing generator meaning, IDs, versions, counters,
stored values and history. Old requests that omit applicability retain their
previous meaning. Explicitly invalid combinations are rejected. Configuration
edits retain the existing reason, version, access and audit requirements.

## Executed checks

Evidence is retained under
`.runtime/custom-code-generators/applicability-20261127/`. Each database-backed
run owns newly created, uniquely named disposable databases. The explicit
missing-only Arabic seed described below is authorized catalogue maintenance,
not a test against the persistent database.

| Check | Result |
| --- | --- |
| Full WebUI unit suite | 1,731 passed; no skips. |
| Full WebUI interaction suite | 836 passed; no skips. |
| Full assembled API/WebUI suite | 82 passed; no skips; owned services stopped and database dropped. |
| Full assembled rerun after the capture fix | 80 passed; two unrelated screens timed out at their unchanged 10-second waits during concurrent tests. Both cases passed a targeted rerun (two passed, 80 deselected). Initial failures are retained; no screen code or timeout was changed. |
| Full API suite | 2,285 passed, nine initial failures corrected and verified in follow-ups, six historical-schema skips passed separately; exact coverage accounts for all 2,300 original cases. One additional real-PDF case also passed. |
| Complete applicability and authentication files after fixture corrections | 53 passed; one historical upgrade skipped in this ordinary-schema run and passed separately. |
| Complete message-capture and direct-creation files after the transaction fix | 59 passed, including the additional real-PDF rollback/provenance/replay case. |
| Broader applicability, typed creation, file-drop and draft follow-up | 56 passed; one separately passed historical upgrade skipped in this ordinary-schema run. |
| Full tools and text-indexer suites | 367 passed, one pre-existing baseline failure; no skips or fixture errors in the correctly provisioned final run. |
| Separate classification-scheme transfer suite | 131 passed, one pre-existing historical-view comparison failure. |
| Populated migration 126 | One passed, including rollback and records/drafts preservation. |
| Populated migration 127 | One passed, including rollback, restored triggers, existing configuration/history/counter preservation and actual creation before/after upgrade. |
| Other maintained populated-upgrade tests | Migrations 066, 082, 094 and 121 each passed in their required historical application/schema contexts; all four databases dropped. |
| Latest canonical schema versus independently migrated last-commit schema | Complete schema, data and sequence parity: 144 tables, six views, 378 functions, 354 triggers, 909 seeded rows and 70 sequences; three owned databases dropped. |
| Catalogue, Arabic terminology, policy generation and configuration checks | Passed; 4,339 active keys, 35 approved glossary mappings across 1,006 contextual uses, 131 settings and all 37 API environment settings. |
| Browser checks | Passed English/LTR and Arabic/RTL, desktop and narrow layouts. |

The case audit in `full-verification-summary.json` compares exact collected node
IDs with all four API JUnit files, verifies each corrected failure against its
passing follow-up, and accounts for every historical-schema case. Across all
maintained suites there are **5,450 distinct cases: 5,448 verified passes after
corrections/rechecks and two pre-existing unrelated failures**. Focused reruns
are not added again to that distinct-case total. This is an aggregate coverage
result, not a claim that the initial full runs were uniformly green.

`database-cleanup.json` verifies that all **39 explicitly observed owned test
databases** are absent, including the nested ACL/cache upgrade databases and
canonical comparison databases. Owned API/UI/preview processes stopped, and
there were no creation or cleanup failures left unresolved. All 105 corrected
implementation/test/schema/catalogue source hashes stayed unchanged through
final verification; all 98 changed/new Python sources parsed successfully.

The final tools run supplies separate disposable databases for ordinary migration
tests and the three legacy ACL-backfill rehearsals, as those tests require
different fixtures and database-name guards. The sole remaining failure is
`test_current_baseline_has_complete_source_and_setting_coverage`. It reports
the same six stale disposition-ledger reference hashes on both the working
tree and commit `997a49a2051d`: retention section 16 and internationalization
sections 14, 15, 16, 19 and 21.1. `preexisting-baseline.json` records that
comparison. No unrelated contract or baseline hash was changed to conceal it.

The transfer failure is `test_actor_redaction_upgrade_matches_canonical`: it
expects migration 046's historical audit view to equal the later type-aware
canonical view. The test, migration 046 and the complete current audit-view DDL
are unchanged from HEAD; `preexisting-transfer-view.json` records their hashes
and exact view equality. This unrelated historical-test problem is retained
without modifying the audit authorization implementation.

The initial full runs exposed outdated test fixtures: editor-save extraction
fixtures lacked the current generator controls' closure state, assembled
creation fixtures omitted required submission keys, and a translation assertion
did not recognize the user's previously approved one-line Arabic correction.
Those fixtures were corrected without changing production search or editor
behavior. The translation exception checks the exact approved text and complete
recorded provenance. Initial failures and subsequent passing results are retained.
An initial new draft test incorrectly supplied the type during draft creation;
it now selects the type during final commit, following the existing API contract.
Three additional new cases initially used display position zero for a type
field; their fixture now uses the required positive position. Two existing
bootstrap fixtures now use the guarded disposable-database helper around their
explicit table reset, restoring generator retention triggers before exercising
bootstrap. Production retention guards were not weakened. The complete affected
test files passed 53 cases in a fresh disposable database; the separately passed
historical upgrade was the only ordinary-schema skip.
The matching API translation-preservation assertion was also corrected to
recognize only that exact approved Arabic wording and its complete provenance.
The first archived migration-121 run lacked its test's seed-helper module and
stopped at collection. Supplying the two exact current helper functions in the
archived fixture resolved that setup error; the unchanged upgrade test then
passed. Both disposable databases were dropped.

The expanded API run also found a real message-capture integration defect.
Allocation's retry savepoint gave newly inserted capture history a subtransaction
ID, while its existing protection checks the outer transaction ID. This falsely
reported a new capture as already committed. Capture history now writes after
the retry savepoint is released, within the same creation transaction. The
existing database guard stays unchanged. A history failure still rolls back the
record, files, counter, request receipt and draft deletion together.

An additional real-PDF regression checks untyped-only generation, a failure after
history persistence, restoration of the original staged files, retry with the
same submission key, the generated number embedded in stored PDF provenance,
and a subsequent replay without another number allocation. The original full
API sweep began before this fix; the affected complete files, broader draft
creation cases and full assembled API/WebUI suite were rerun against the corrected
code. Their results are reported separately from the original failures.

The first unsharded API run was deliberately interrupted after 56 passing tests
to use the runner's four supported shards. Its database was dropped. This
partial run is not a substitute for the complete shard results.

## Browser and translation evidence

The browser fixture uses the actual generator components, application styles
and bounded-selector implementation with an in-memory API. Database/API
coexistence is verified separately through the real API and native constraints.
The desktop card is 822 × 714.66 pixels at a 1,692 × 895 viewport, retaining the
white background, scrolling settings and previously requested height increase.
Both languages were also checked at 375 × 812. The viewport override was reset,
the temporary tab closed and the owned preview stopped.

Screenshots and dimensions are retained as `selector-desktop-en.jpg`,
`selector-options-ar.jpg`, `selector-narrow-en.jpg`, `selector-narrow-ar.jpg`
and `browser-metrics.json` in the evidence directory.

Four contextual keys were added: `code_generation.ui.applies_to`, `all_items`,
`untyped_only` and `selected_type`. The retired checkbox/hint keys `named_type`
and `all_types` were removed from both active artifacts. All 4,335 remaining
Arabic entries and their provenance were preserved exactly by message key.
Canonical ordering, coverage and catalogue hashes agree. No administrator
export was promoted. The four new Arabic values remain generated drafts needing
human review. The explicit demo `--missing-only` seed stored four drafts,
protected 4,335 existing translations, and reported no failures or corrections;
it published nothing.

## Deployment and scope

Fresh installations use the self-contained latest `database/schema.sql` and
separate seeds. Existing installations on schema 126 apply migration
`127_code_generator_applicability.sql`; installations on schema 125 apply 126,
then 127. Upgrade API and WebUI together. See
[operator guidance](../custom-code-generators-operations.md).

This extension changes generator applicability lookup and generator constraints;
it adds no unrelated search optimization. Earlier controlled performance
measurements and reported overruns remain in the existing performance reports.
`unchanged-search-source.json` confirms exact hash equality against the preserved
pre-extension comparison snapshot for search, search cache, page processing,
browse, CRUD, typed search, disposition report presentation and code ordering.
Full-suite runs execute concurrently for correctness, so their elapsed times
are not isolated response-latency measurements or a new performance acceptance.
Database cleanup itself experienced checkpoint waits, including an observed
548-second DROP operation. `observed-cleanup-waits.json` retains observations
for the owned databases, including nested historical upgrade fixtures. No
server setting or search query was changed in response.

Local verification and requirement close-out are complete. Remote CI and deployment
were not performed; the user retains control of commits and publication.
