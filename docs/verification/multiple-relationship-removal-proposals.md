# Multiple relationship removal proposals

Approved contract: destruction-process.md section 5 review proposals. New removal
proposals support multiple links; each saved proposal still identifies one exact
relationship. Existing proposal revision stays single-selection.

Implementation: ReviewForm.edit uses the standard PageTable multiple selector,
queues a distinct change and readable link summary per selected ID, and clears
selection when changing target. Existing review-work Save submits the pending set
atomically. No API contract, privilege, migration or translation key is added.

Verification on 23 October 2026:
- 87 task UI tests passed, including both aggregation and record multi-selection,
  exact batched Save payloads, individual revision, and English/Arabic cases.
- Two focused disposable-database API tests passed: multiple removal proposals
  and all proposal types save atomically without executing resource changes.
  A failing second proposal rolls the first back. The database was dropped.
- In-app browser fixture: selected both rows individually in English and via
  Select all in Arabic; Continue produced two readable pending entries. Standard
  Wathiq table styling and RTL were visually checked. No demo data was changed.
- Catalogue references, API environment template synchronization and diff checks
  passed. Existing English/Arabic keys and wording are reused unchanged.
