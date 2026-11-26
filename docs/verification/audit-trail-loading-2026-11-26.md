# Audit Trail loading verification — 26 November 2026

## Cause and implementation

The Audit Trail navigation reached its filters, then waited for the initial
event search. The `authorized_event_history` view contains a materialized
history-access CTE. PostgreSQL could not push the outer chronological sort and
page limit below that view's full snapshot projection. It evaluated resource
access and built redacted before/after/metadata values across the history before
selecting 50 rows. The observed Demo query remained active beyond 30 seconds.

`backend/services/api/search.py` now selects ordered event IDs through the same
authorized view, including every submitted filter, limit and offset. An
uncorrelated SQL array then restricts the full projection to those IDs using the
event primary-key index. A join-only experiment was rejected: its plan still
projected the full history before joining to the page.

Matching, authorization, sorting and paging remain in PostgreSQL. In particular,
actor predicates and actor sorting use authorized values before page selection;
raw actor snapshots never confer access. The canonical view still decides
redaction and type-history values. The configured result cap, bounded count,
50-row UI pages and deterministic chronological ordering are unchanged. There
are no migrations, settings, caches, environment variables or translation changes.

This implements the existing Audit Trail contract in
`specs/security-and-authorization-subsystem.md` §18.1. Regression coverage is in
`backend/services/api/tests/test_audit_page_projection.py`: the first, second and
shortened final capped page; executed permission-projection loops; immutable
actor snapshots; actor filtering/sorting before pagination; a signed-in auditor
without access to the resource; and denial without `audit.view`.

## Demo read-only comparison

The user requested verification against Demo. The diagnostic used the real
`search_rows` implementation and the saved original implementation in one
`REPEATABLE READ READ ONLY` snapshot, under the previously observed Demo
auditor's existing privileges. No API lifespan, test fixtures, seeds or writes
ran against Demo; the read-only transaction was rolled back at the end.

The snapshot contained 130,339 audit events, 524 aggregations and 1,893 records.
PostgreSQL was 18.4 on macOS arm64. LLVM/JIT was unavailable in this build;
this is not a Linux or production-concurrency measurement.

Times include application search processing and database execution, excluding
HTTP authentication/transport and browser rendering. Each original query ran
once; the fixed query ran three times on the first page and, for nonempty
cases, offsets 50 and 950. The complete first-page response from every repeat
matched the original response exactly, including snapshots and redaction.

| Search | Original first page | Fixed first page, three repeats |
| --- | ---: | ---: |
| Unfiltered entry | 44.463435 s | 0.086363–0.111902 s |
| Record events | 12.479454 s | 0.058952–0.074948 s |
| No matching entity type | 0.001493 s | 0.000823–0.000855 s |

All 21 fixed samples, including later pages, were below three seconds. Executed
plans showed the full permission projection bounded to the returned page.
All 24 before/after samples, page IDs, source hash, full plans, database counts
and read-only/rollback evidence are retained locally in
`.runtime/audit-page-performance/demo-44b53cd76ecd/report.json`.

Before application, a separate disposable A/B benchmark covered 175,243 audit
events on the canonical large fixture (51,003 aggregations and 153,009 records).
All 54 candidate API responses passed correctness and latency checks; maximum
0.231893 seconds. Original unfiltered requests took 19.225465–36.423269 seconds.
That comparison included a caller with `audit.view` but no resource ACL grants,
canonical redaction comparisons, hidden-actor matching, empty results, later
pages and a caller denied without `audit.view`. Its 72 total samples and cleanup
receipt are in `.runtime/audit-page-performance/run-b56f4442746b/`.

## Repeatable regression checks

The first disposable API run passed 11 tests:

```sh
backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py \
  backend/services/api/tests/test_audit_page_projection.py \
  backend/services/api/tests/test_application_settings_phase6.py::test_audit_cap_is_one_snapshot_for_count_page_and_response_and_no_env_fallback \
  backend/services/api/tests/test_api.py::test_event_history_is_read_only_and_searchable \
  backend/services/api/tests/test_disposition_history_display.py \
  backend/services/api/tests/test_entity_history_paging.py
```

The existing actor/index/cap/redaction suite passed 14 tests through
`backend/services/api/.venv/bin/python tools/test_scheme_transfer.py -k audit_search`.
All three databases created by these two runs were dropped successfully.

The API client, audit destination/workspace and English/Arabic actor-control
tests passed 79 tests:

```sh
frontend/webui/.venv/bin/python -m pytest -q --asyncio-mode=auto \
  frontend/webui/tests/test_api_client.py frontend/webui/tests/test_audit_workspace.py \
  frontend/webui/interaction/tests/test_audit_workspace.py \
  frontend/webui/interaction/tests/test_audit_actor_select.py
```

The first frontend invocation omitted `--asyncio-mode=auto`, producing 17 async
runner/fixture errors and 62 passes. The corrected invocation above passed all
79 without application changes.

## Large-data gate

`tools/check_search_performance.py` now includes Audit Trail checks for both
the permitted resource reader and an auditor without resource access. It checks
unfiltered/record/empty criteria, offsets 0/50/950, exact ordered IDs and capped
counts, canonical protected values, and actual projection-node execution counts.
Every measured response must finish within three seconds. Query plans, expected
IDs/counts, all timings, JIT availability and database cleanup are retained.

Run the complete gate, including existing searches:

```sh
backend/services/api/.venv/bin/python tools/check_search_performance.py \
  --output .runtime/search-performance/audit-trail-20261126 --repeats 3
```

For a focused rerun, add `--audit-only` with a new output directory. This keeps
the same large resource/ACL/event fixture and omits irrelevant file-text chunks.
The tool still owns a fresh database and drops it in `finally`.

The complete run used 51,003 aggregations, 153,009 records, 306,018 chunks and
175,242 audit events before application startup. All correctness assertions
passed. Its 42 Audit Trail responses passed, with maxima of 0.172795 seconds
for the resource reader and 0.152101 seconds for the auditor without resource
access. Every executed full-detail projection was bounded to the returned page.
The database `erms_search_perf_12392b740b8346f49c9c288255800270` was dropped.

**The overall gate failed on latency.** Twelve responses in unchanged full-text
paths exceeded three seconds:

| Identity and flow | Failing samples | Range |
| --- | ---: | ---: |
| Reader, broad combined Global Search | 3 | 3.0314–3.6846 s |
| Reader, Global Search UI first pages | 6 | 3.6301–5.1116 s |
| Caller without resource access, record content search | 3 | 6.0426–7.9729 s |

Those paths do not execute the changed event-history branch. The failure is
retained in `results.json` and `failure.json`, with timings, rankings, plans,
host observations and cleanup under
`.runtime/search-performance/audit-trail-20261126/`. Their cause was not isolated
in this Audit Trail change. The recorded full-gate outcome and its thresholds
remain unchanged.

**User scope decision — 26 November 2026.** The user explicitly directed that
the broad full-text results be ignored for now when completing this Audit Trail
fix. The user reports intermittent failures on the same laptop and large
dataset, with competing processes on a non-dedicated host as the likely
explanation. Further full-text investigation is deferred. These retained
full-text samples do not block the Audit Trail change; its verification is
complete based on the Demo comparison, regression tests, focused performance
gate and live navigation/paging checks below. This decision is scoped to the
current fix and does not change future benchmark thresholds.

A separate fresh run exercised the focused command and its cold initial
requests without the unrelated full-text workload:

```sh
backend/services/api/.venv/bin/python tools/check_search_performance.py \
  --audit-only --output .runtime/search-performance/audit-trail-only-20261126 \
  --repeats 3
```

All 42 responses passed: maximum 0.495683 seconds for the reader and 0.156278
seconds for the auditor without resource access. The same large resource/ACL
fixture contained 175,242 audit events and omitted file-text chunks. Expected
IDs/counts, protected-value checks, executed plans, all samples and cleanup are
retained in the output directory. Database
`erms_search_perf_17169efa1013403eb2055fce854628bb` was dropped. This focused pass
does not replace or erase the complete gate's failures above.

## Signed-in Demo browser

After the user signed in, the real Demo page loaded 50 event cards and showed
`1–50 of 1000` with Apply enabled. Next showed `51–100 of 1000` while an edited,
unsubmitted Correlation ID remained in the control. Clearing that draft and
Previous returned to `1–50`. Two subsequent Dashboard-to-Audit returns loaded
the first page successfully. The user's new 14:03 authentication event was
visible, providing a freshness check. No browser console errors were observed.

The captured server-log segment contains exactly one filter-options GET and
one search POST for each return, plus the expected Previous search. Request
evidence is in `.runtime/audit-page-performance/demo-browser.json`; the final
English/LTR screenshot is
`.runtime/audit-page-performance/audit-trail-demo-en.jpg`. Live browser checks
used English; the interaction suite above covered English and Arabic actor
controls without changing the user's saved language preference.

Changed Python modules compile and `git diff --check` passes. Changes remain
local and uncommitted on the user's existing branch.
