# Custom Code Generators: Phase 3 Verification

**Dates:** 26–27 November 2026. **Status:** Complete. The authority remains
[approved specification revision 0.4](../../specs/custom-code-generators.md).

Backend final creation, draft completion, capture and direct file drops now use
the shared generator. Manual values and static defaults retain precedence.
Drafts save without a number and retain automatic recommendation provenance.
An accepted number is inserted exactly or rejected with a conflict. Automatic
file drops obtain fresh numbers and save their complete batch atomically.

Completed-request receipts preserve the original response for an authorized
retry, including a retry after the draft has gone or a review date has passed.
Current permissions are checked again. Permanent destruction removes related
saved response metadata through the existing destruction procedure while
retaining completion identities, preventing accidental recreation. The receipt
lookup index contains resource identifiers, not generated or manual Text values.

## Executed checks

Logs below are in `.runtime/custom-code-generators/phase0-20261126/`.
Each database-backed run used a new disposable database; all were dropped.
These are overlapping focused runs, not an aggregate unique-test count.

| Log | Result |
| --- | --- |
| `phase3-batch-foundation.log` | Six passed; one context lookup failed. The nonexistent helper was replaced with the actual parent lineage query. |
| `phase3-context-correction.log` | Both affected context/rollback checks passed. |
| `phase3-direct-creation.log` | Invalid test selector: no tests ran; disposable database dropped. |
| `phase3-direct-creation-rerun.log` | 16 passed: direct generation, manual/default rules, exact chosen values, replay, deletion/manual reuse, primary context and existing creation/role behavior. |
| `phase3-draft-capture.log` | 10 passed: numberless drafts, retained files and chosen values on conflict, completed-draft replay, capture preparation without counter locks and existing capture boundary failures. |
| `phase3-file-drop.log` | 27 passed: generated combined/separate drops, safe replay, rollback, legacy file drops, permissions and type-specific metadata. |
| `phase3-recommendations.log` | 13 passed: current type/Create for context, non-consuming suggestions, long codes, scoped denial, current-access replay and retained legacy behavior. |
| `phase3-canonical-erasure-parity.log` | 45 canonical/migration parity checks passed. |
| `phase3-populated-upgrade.log` | Fixture failed to provide the old schema's required owning unit. |
| `phase3-populated-upgrade-rerun.log` | Populated upgrade passed after correcting the historical fixture; existing records/drafts survived and a forced failure restored both old schema and destruction procedure. |
| `phase3-receipt-erasure.log` | Two passed; one historical fixture had the same missing owning unit. |
| `phase3-receipt-erasure-rerun.log` | Corrected permanent-destruction case passed with 5,003 receipts; related responses were removed and unrelated responses and completion identities were preserved. |
| `phase3-temporal-replay-before-fix.log` | Reproduced a completed request being blocked after its review date passed. |
| `phase3-temporal-replay-fixed.log` | Three passed after moving completed-request lookup before creation-only model validation. New requests still enforce future review dates. |
| `phase3-client-retry.log` | Ten client-state/entity-creation checks passed: stable request identity, frozen uncertain inputs and original-result reuse. |
| `phase3-retry-proof-corrected.log` | Three passed: confirmed rollback proof, completed/deleted replay and creation-only date validation. An earlier selector failed to collect tests, and a test assertion initially counted the parent aggregation's receipt; both failures are retained. |
| `phase3-creation-races.log` | Four passed: four simultaneous retries create one record/event/receipt; a competing manual number advances only an unchosen number; an exact chosen number conflicts; scoped hints remain denied. |
| `phase3-retry-proof-bindings-rerun.log` | Requested-field pagination and configuration non-disclosure passed; the unrelated parent-receipt count assertion failed and was corrected in the preceding listed run. |
| `phase3-placement-access-audit-rerun.log` | 17 passed, two failed: reproduced the existing closed-placement database guard failure and an outdated policy-inventory expectation. Receipt-failure rollback, access and Arabic artifact checks passed. |
| `phase3-closure-policy-corrected.log` | 16 passed after the narrow closure repair and corrected conditional-policy declaration/inventory assertions. |
| `phase3-typed-closure-final.log` | Three passed: typed/untyped correction creation and replay, initial files, unchanged closure, rejected later metadata/file edits, protected database function and Arabic artifact validation. |
| `phase3-closed-correction-denied-corrected.log` | Signed-in caller with creation/correction privileges and parent ACL access remains denied without governance clearance, through both API and native SQL; draft/files survive. The first fixture used a stale CSRF header and was corrected to use its bearer session. |
| `phase3-closure-populated-upgrade-final.log` | Final occupied upgrade/rollback/locking check passed; existing records/drafts survived, and the disposable database was dropped. |
| `phase3-final-schema-parity.log` | Final schema/upgrade definition parity passed. Earlier full canonical run: 45 passed. A missing statement delimiter in an intermediate migration was caught and corrected before database verification. |
| `phase3-stale-contexts.log` | Four passed: changed parent number, configuration, month and forward adjustment reject an old chosen number without changing counters. |
| `phase3-integrated-creation-regression.log` | 170 passed, one existing catalogue-order assumption failed. This run includes all generator creation adapters plus existing API, draft, numbering, file-drop, type and governance behavior. |
| `phase3-catalogue-isolation-corrected.log` | All three affected/seeding cases passed after selecting the intended type by its submitted filter, rather than assuming an empty catalogue. |
| `phase3-no-backfill.log` | Both optional/required later type assignment and field-edit cases passed without invoking a generator. |
| `phase3-final-dialog-regression.log` | 55 passed: suggestions, provenance, edit/revert, late/closed/save responses, generated Text blanks, draft retry, capture preparation and file drops. |
| `phase3-existing-dialog-regression.log` | 168 existing client, creation and translation-dialog checks passed. |
| `phase3-owned-files-final.log` | 31 passed with owned memory/disk uploads, duplicate filenames, retained exact bytes and corrected/lost-response retries. Intermediate double-click and background-slot failures were reproduced and corrected; their logs remain. |

`phase3-run-inventory.json` records all focused runs and their disposable
database creation/cleanup identities. The runs overlap. The final integrated
run's 170 passes plus the corrected affected cases are not represented as a
clean first-run pass or added together as a unique test count.

Nineteen generator messages now have English definitions and Arabic drafts;
all 4,196 original curated items and their provenance are preserved. The active
catalogues contain 4,215 identically ordered keys. New-message blank,
placeholder and terminology validation and full artifact/hash/coverage checks
passed. Catalogue reference checks passed. New drafts remain unpublished for
human review. The unrelated curated glossary failure recorded in phase 2
remains unchanged and is still an outstanding full translation gate.

Receipt cleanup plans and timings are retained under
`.runtime/custom-code-generators/erasure-metrics/`. The measured response lookup
used `resource_creation_requests_response_resource` (0.008 ms); complete
destruction took 0.246 seconds in this small fixture. This is not evidence for
the separate search performance gate or a production migration-time estimate.

## Later-phase work

Phase 3's creation, provenance, retry and file-retention safeguards are complete.
The closed-placement repair uses existing approved security authority and
one new-record transaction context; it does not grant later mutations to closed
records. Deployment must grant its protected helper to a separate API database
role if that role does not own the function; see the integration design.

Natural ordering, the settings UI, full search/performance verification,
translation gates, browser verification and the final operator handoff remain
open. No persistent database was upgraded, and all changes remain local and
uncommitted.
