# Custom Code Generators Phase 0 Verification

**Date:** 26 November 2026.

**Authority:** [Approved specification revision 0.4](../../specs/custom-code-generators.md).

**Status:** Phase 0 complete, with pre-existing latency failures recorded.
189 functional checks passed. Both search baselines completed correctness
checks but failed their latency gates. No custom generator is exposed in the
application.

## Contract mapping

The [integration design](../custom-code-generators-integration.md) maps direct
root/child aggregation and record creation, draft save/final commit, placement
correction, message capture, direct single/combined/separate drops and
drop-to-draft review. It records Text eligibility, default/required-value order,
Create for/ownership context, exact chosen-number validation, submission keys,
precise integer transport, errors/versions, lock order and sorting/cache paths.

The [traceability ledger](../custom-code-generators-implementation-traceability.md)
assigns all CG-01–15 requirements to implementation and verification phases.
Those requirements remain open until their new behavior is implemented and
verified.

## Functional baseline

| Check | Result | Disposable database and cleanup |
| --- | --- | --- |
| Existing numbering, file-drop, general API/drafts, type foundation, settings/audit, policy inventory and tab search-cache tests | 176 passed; 463.04 seconds | `erms_messaging_test_acl_e0a108da3ffa4f33a38c4a4b1aa5a921`; dropped successfully. |
| New draft/conflict characterizations plus existing message-capture rollback/authorization and typed drop/draft creation | 8 passed; 34.63 seconds | `erms_messaging_test_acl_06f5c3a54451408aa9e02d87000be7e8`; dropped successfully. |
| Existing WebUI duplicate-number choice and late-response checks | 4 passed; 2.72 seconds | Mock API and NiceGUI user simulation; no database. |
| Legacy creation timing, execute-call counts and observed parent-row contention | 1 passed; 3.94 seconds | `erms_messaging_test_acl_a60aefca6fe145dd97de9b2e5431a145`; dropped successfully. |

New characterization tests prove that omitted/null draft numbers survive
save/reopen/update with staged files, and that a duplicate final number leaves
the chosen number, title, description, existing record and staged document bytes
intact. They preserve current guarantees; they do not test a new allocator.

The first database command was blocked by the local sandbox before creating a
database. The authorized rerun used the disposable runner. The first standalone
WebUI command used pytest's strict async mode, which did not initialize
NiceGUI's async fixture; rerunning with `--asyncio-mode=auto` passed all four
checks. Preserve both failed-attempt logs alongside the passing results.

## Commands and artifacts

Run database suites with `backend/services/api/.venv/bin/python
tools/run_disposable_acl_tests.py`; the runner creates a uniquely named database,
initializes the canonical installation and separate seeds, points the whole
pytest process at that database and drops it in `finally`.

The first run selected:

- `test_number_suggestions.py`
- `test_aggregation_file_drop.py`
- `test_api.py`
- `test_resource_type_foundation.py`
- `test_application_settings.py`
- `test_policy_inventory.py`
- `test_tab_search_cache.py`

All are under `backend/services/api/tests/`. The follow-up selected
`test_code_generator_creation_baseline.py` and these existing checks:

- `test_messaging_phase5.py::test_capture_commit_failure_and_authorization_are_atomic`
- `test_messaging_phase5.py::test_capture_each_commit_boundary_rolls_back`
- `test_resource_type_access.py::test_bulk_drop_and_draft_apply_type_before_writing`

The WebUI command was:

```sh
frontend/webui/.venv/bin/python -m pytest -q --asyncio-mode=auto frontend/webui/interaction/tests/test_resource_number_controls.py
```

Logs and initial source hashes are retained under
`.runtime/custom-code-generators/phase0-20261126/`:

| Artifact | Contents |
| --- | --- |
| `source-hashes.json` | SHA-256 hashes of the initial production paths and approved documents. |
| `api-baseline.log` | Initial sandbox refusal before database creation. |
| `api-baseline-authorized.log` | 176 passing API checks and database creation/drop receipts. |
| `creation-path-baseline.log` | 8 passing creation-path checks and database creation/drop receipts. |
| `webui-number-controls.log` | Initial async-fixture setup failure. |
| `webui-number-controls-auto.log` | 4 passing WebUI checks with the correct async mode. |
| `creation-metrics.log` | Passing timing/contention probe and database creation/drop receipts. |

## Creation measurements

These are single baseline observations on the small API fixture, including
authentication. They establish comparison points, not production latency or
throughput promises. Execute counts do not include statements inside PostgreSQL
functions or triggers.

| Operation | Complete HTTP time | Cursor execute calls |
| --- | --- | --- |
| Number recommendation | 0.0146 s | 9 |
| Manual record creation | 0.0486 s | 21 |
| Numberless draft save | 0.0132 s | 10 |
| Combined two-file direct creation | 0.0573 s | 41 |

The parent-lock probe observed `Lock / transactionid` through
`pg_blocking_pids`; creation completed after release in 0.0541 s total. Current
parent authorization/ownership protection can serialize creation under the
same parent independently of future counter locking. Later independent-counter
measurements must distinguish that existing resource lock from counter contention.

Full values are in
`.runtime/custom-code-generators/creation-metrics/erms_messaging_test_acl_a60aefca6fe145dd97de9b2e5431a145.json`.

## Standard search baseline

The standard runner retained 1,755 HTTP timing samples and completed correctness
checks but failed its strict latency
gate on one reader request: `records / filtered_descending`, repeat 0, offset 0,
4.207 seconds. This is an unchanged-application baseline failure, not an accepted
generator performance result. Preserve the failed sample and its actual plan;
the earlier compressed-storage acceptance does not turn this sample into a pass.

The fixture contained 51,003 aggregations, 153,009 records and 306,018 small
file-text chunks, with typed Text values and existing compressed storage policy.
PostgreSQL reported JIT enabled by default but unavailable in this local build;
the existing search-scoped setting/restoration remains unchanged.

Artifacts are under
`.runtime/search-performance/code-generators-phase0-standard-20261126-run1/`,
including `results.json`, per-flow samples/rankings/plans, `type-text.json`,
`environment.json`, `failure.json`, host observations and `cleanup.json`.
The database `erms_search_perf_0b75b78732934bb9ad5167959820c6a8` was dropped
successfully. The command exited 1 and is recorded as a failed latency gate.

## Larger-text search baseline

The larger-text runner completed 428 main and 216 typed-text HTTP samples,
with all correctness checks completing. Eleven main first-page responses
exceeded three seconds; the maximum was 4.620738 s for `broad_combined`, repeat 1.
Other failing cases were broad words, AND, phrase and negative phrase. Typed-text
checks recorded no latency failures. Preserve every individual failure in
`results.json`; neither averages nor the previous storage acceptance turn these
failures into passes.

The fixture had 51,003 aggregations, 153,009 records and 180,630 chunks. All
180,630 large vectors were verified as LZ4 compressed under MAIN storage.
Both runners used native PostgreSQL 18.4 (Postgres.app), arm64 Apple build;
JIT was unavailable locally. No server-wide planner or storage settings changed.

Artifacts are under
`.runtime/search-performance/code-generators-phase0-large-text-20261126-run1/`,
including exact expected/returned ranks, all timings, plans, environment/source
hashes, `waits-and-host-io.jsonl`, host observations, `failure.json` and
`cleanup.json`. The command exited 1. The database
`erms_large_text_003382b1b8484c268d96259785135472` was dropped successfully.

The [creation measurement](../../backend/services/api/tests/test_code_generator_baseline_metrics.py)
ran between the two search workloads. Search workloads did not overlap each
other or another test run. Comparing initial hashes after the baselines confirmed
that all measured production source paths were unchanged.

## Phase outcome

Contract mapping, all requirement owners/planned tests, functional baselines,
creation counts/lock waits, both full search baselines and cleanup receipts are
recorded. All five created disposable databases were dropped. The phase is a
completed baseline, not a search performance pass. Retain the twelve latency
failures for later comparison; do not reopen the earlier storage-tuning round
solely to make this phase appear green.

Schema/allocation, administration APIs, creation integration, natural ordering,
production UI and final feature verification remain later phases.
