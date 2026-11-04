# Dashboard isolation and performance verification

Verified 4 November 2026. The dashboard uses statement-local authorization sets,
without per-resource permission calls or a cross-request authorization cache.

## Correctness and isolation

The original dashboard snapshot survived identity changes without an identity
key, and an old request could write its result after logout. Snapshots now belong
to a login revision, identity, language, timezone, privilege set and role set.
Logout clears protected content before waiting for remote logout. Previous
responses, including 401s, cannot update or sign out a newer session. Navigation
and disconnected/deleted clients invalidate pending work. Same-user refreshes
retain their visible snapshot and restore the refresh control after failure.

Overview queries previously relied on search views which filter lifecycle state
but do not themselves authorize resources. Overview counts now enforce resource
visibility. Favourites also recheck their own resource visibility and redact
inaccessible parent references; revoking access cannot expose a saved favourite.

`backend/services/api/dashboard_visibility.py` implements the canonical view
predicates as sets: organizational activity, assigned/effective roles, global
privileges, clearance, governance clearance, contextual managers and nearest file
administrators, inherited aggregation ACL sources, and direct/inherited record
ACL grants. Custom child defaults, inheritance breaks and target ownership
remain significant. The inclusive ownership-assignment boundary and half-open
view/review-assignment boundary remain deliberately distinct.

The same authorized resource sets feed counts, ownership, storage, review
counts/previews, favourites and personal recent activity in one SQL statement.
The separate review-page endpoint uses the same set-based authorization.
Active holds propagate down the hierarchy once; direct record holds form a
separate set. Classification activity and inherited rule existence also propagate
once through the hierarchy. Administrative counts share one SQL request.

There are no dashboard calls to `current_user_can_view_*`,
`user_has_*_permission`, `role_effectively_active`, `user_matches_contextual_acl`,
`effective_holds_for_*`, or per-classification inheritance functions. Exact
counts still require set-based resource scans. Python only formats grouped
unit totals and bounded presentation data; it does not fetch/authorize individual
records or aggregations in a loop. No new cross-request cache was introduced.

## Index evidence

* Migration 098 adds `event_history_dashboard_resource_latest_idx`, matching
  actor/resource/operation latest-event ordering. The earlier isolated activity
  comparison improved from 239 ms to 34 ms with identical results.
* Migration 099 adds `event_history_dashboard_content_views_idx`, a partial
  covering index on actor/time/ID including component ID and operation,
  restricted to `digital_component` / `CONTENT_VIEWED`. The larger plan changed
  from 184,000 heap-backed event rows / 16,700 blocks to an index-only scan of
  1,512 blocks with zero heap fetches. Its scan fell from about 100 ms to 17 ms.
* Migration 100 adds `digital_components_dashboard_storage_idx` on record ID
  including byte size. At the larger scale, component storage changed from an
  818-block metadata heap scan to a 143-block index-only scan with zero heap
  fetches. The smaller fixture's planner can still choose its cheaper heap scan.
  Existing hierarchy, review, favourite and role-assignment indexes remain.

All three canonical index definitions and idempotent migrations are tested. New
empty databases use the self-contained canonical schema plus separate seeds;
existing installations apply migrations separately.

## Benchmark method and results

`tools/benchmark_dashboard.py` creates a uniquely named disposable database,
initializes the canonical schema and separate reference seeds, and starts its own
isolated API/WebUI. It refuses occupied benchmark ports and never reuses the
persistent stack. Each fixture contains exactly the requested record count:

| Fixture | Records | Aggregations | Components | Synthetic activity events |
| --- | ---: | ---: | ---: | ---: |
| Smaller | 1,840 | 840 | 3,680 | 110,400 |
| Larger | 18,400 | 8,400 | 36,800 | 1,104,000 |

Both use a balanced four-level aggregation hierarchy, one organizational unit,
1,001 classifications with inherited retention, two authorized identities
(governance and ordinary ACL access), and an identity without roles. They have
no active holds; separate correctness tests cover direct, inherited and
overlapping holds. Generated normal audit events exist in addition to the
synthetic activity volume. All event rows use source `seeding`.

Uniform status-1 fixture creation temporarily skips only the two disposition
insert-consistency triggers that would otherwise revalidate the same complete
unit once per inserted member. It verifies no disposition jobs and uniform
status, then restores both triggers before any dashboard query. Synthetic event
creation similarly skips reference-snapshot construction only. All triggers are
restored before measuring; query authorization, hierarchy/security constraints
and immutable-history guards remain enabled. Fixture construction time is not
included in dashboard population time. `VACUUM ANALYZE` precedes measurements.

HTTP samples use the actual local API, discard a warm-up request, then report
seven samples. Browser population is measured from submitting the already-loaded
sign-in form to the complete dashboard (including the final storage section).
Refresh is measured until replacement dashboard controls and data are present,
not merely until the request starts. These are warm-database local observations,
not cold-disk measurements or service-level guarantees.

Final measurements (administrator; medians):

| Records | API response, 7 samples | Sign-in to complete dashboard, 3 samples | Complete refresh, 7 samples |
| ---: | ---: | ---: | ---: |
| 1,840 | 41.29 ms | 387 ms | 288 ms |
| 18,400 | 305.99 ms | 779 ms | 499 ms |

The smaller API range was 37.04–46.85 ms; the larger range was 293.05–319.16 ms.
Ordinary ACL-reader API medians were 34.44 ms and 318.02 ms respectively;
identities without roles returned empty authorized summaries in about 3.4 ms
and 3.2 ms. The initial handler request on a new API process measured 77.24 ms
at the smaller scale. The larger fixture's original first request was 986.91 ms
before the fully covering index refinements; its final API median above was
measured after those refinements.

Browser sign-in samples were [347, 524, 387] ms and [703, 806, 779] ms.
Refresh samples were [285, 293, 280, 280, 288, 303, 290] ms and
[500, 499, 489, 495, 502, 512, 491] ms. An immediate programmatic refresh attempted
before the initial request finished was correctly coalesced/ignored and was not
included as a completed refresh sample. Menu/control readiness was checked
between login samples; those checks are outside the timed login interval.

The larger fixture's no-content-index and final complete summary values agree
for all three identities. Its preliminary API median before fully covering
indexes was 401.44 ms. Plan instrumentation times are kept separate from the
HTTP samples because instrumentation and cache state affect their absolute cost.
The smaller fixture was rebuilt and remeasured using the exact final code,
canonical schema and indexes.

Timing samples, complete response comparisons, execution plans and screenshots
are retained under gitignored `.runtime/dashboard-verification/1840/` and
`.runtime/dashboard-verification/18400/`. Plan comparisons are separate from
HTTP timing runs. Every benchmark query used a disposable database. The separate
`demo` deployment below happened after the benchmarks and explicit user approval.

## Regression evidence

The final API suite passed all 36 selected cases in a fresh disposable database.
An additional forced-generic-prepared-plan regression checks A→B→A, null identity,
private favourites and totals on the same physical connection; it also passed
in its own disposable run (37 API cases in all across these final runs).
The focused API cases cover lifecycle/governance combinations, hidden resources,
identity changes, ownership, review configuration, direct/inherited holds,
validity boundaries, ACL inheritance breaks, overlapping holds, component-count
multiplication, query-plan structure, canonical/idempotent indexes, and audited
image preview. Differential tests compare actual ID sets and privileges with
canonical functions across all ACL principal types, custom defaults, target
ownership changes, nearest file administrators, clearance changes, governance,
missing privileges, future/expired assignments, inactive organizational units,
suspended users, null identities, and destroyed resources. Classification tests
compare inherited rule/activity results directly with canonical functions.

Frontend regressions cover identity/language cache keys, same-account relogin,
delayed success/error/401, abandoned views, deleted/disconnected clients,
immediate sign-out clearing, actual NiceGUI A→B→A rendering, single-flight
refresh and non-destructive refresh errors. The latest frontend run passed all
90 selected cases. A previous broader entity run passed 144 cases with one
unrelated baseline translation-editor test explicitly excluded; no claim is made
that the whole repository suite is green.

| Product contract | Implementation | Verification |
| --- | --- | --- |
| Authorized overview, holdings, storage and review scopes | `dashboard_visibility.py`, `dashboard.py` | `test_dashboard_set_visibility.py`, `test_phase6_read_authorization.py`, ownership/settings suites |
| Private favourites, activity and relationship references | Shared authorized sets and current-user predicates in `dashboard.py` | Hidden-resource and second-identity cases; live A→B→A |
| Hold/lifecycle semantics and exact component totals | Batched rollups in `dashboard.py` | `test_dashboard_regressions.py` |
| Identity/language snapshot and late-response isolation | `app.py`, `api_client.py` | Session/client tests and real NiceGUI interaction tests |
| Set processing and index parity | SQL CTEs, canonical schema, migrations 098–100 | Execution-plan assertions, idempotent migration cases and benchmark plans |

Live verification includes both fixture sizes, repeated refresh/navigation,
favourite removal followed by navigation, first-load account isolation without
manual Refresh, and Arabic/RTL. Database creation/cleanup outcomes are recorded
by the runners. Both final benchmark databases and every regression database
were dropped cleanly, including databases from interrupted fixture preparation.
The owned benchmark API/WebUI processes were stopped; the persistent local stack
was not stopped. Python compilation and `git diff --check` also pass.

Reproduce the fixture and API timing run (omit `--serve` for automatic exit):

```sh
backend/services/api/.venv/bin/python tools/benchmark_dashboard.py --records 1840 --serve
backend/services/api/.venv/bin/python tools/benchmark_dashboard.py --records 18400 --serve
```

Run one at a time; Ctrl-C stops only the owned API/WebUI and drops that fixture.
Reproduce the focused API suite in another uniquely named disposable database:

```sh
backend/services/api/.venv/bin/python tools/run_disposable_acl_tests.py \
  backend/services/api/tests/test_dashboard_regressions.py \
  backend/services/api/tests/test_dashboard_set_visibility.py \
  backend/services/api/tests/test_phase6_read_authorization.py \
  backend/services/api/tests/test_organizational_ownership_phase4.py \
  backend/services/api/tests/test_application_settings_phase4.py \
  backend/services/api/tests/test_api.py::test_browser_native_image_preview_preserves_mime_type_and_is_audited
```

## Deployment

On 4 November 2026, following explicit user approval, pending migrations 098,
099 and 100 were applied to `demo`. The prior 97 migration receipts were retained;
all three new receipts and valid/ready indexes were verified, with no remaining
pending migrations. Planner statistics for `event_history` and
`digital_components` were updated with `ANALYZE`. The managed local stack reported
ready after the upgrade. No regression suite or benchmark was run on `demo`.

The private deployment receipt, including migration hashes, timings and index
definitions, is `.runtime/dashboard-verification/demo-migrations-20261104.json`.
These index additions are available to running services. Deployment of changed
Python code requires restarting API/WebUI unless the running development services
already reload that code. Local stack startup does not apply migrations.
No environment variables, UI strings or translation artifacts changed. Arabic
publication for browser verification was confined to disposable fixtures.


## Projection to 184,000 records (not measured)

A straight-line fit through the two warm administrator API medians predicts
2,952.99 ms at 184,000 records. A separate fit through the sign-in-to-populated
medians predicts 4,699 ms. Use approximately 3 seconds for the API and 4–5 seconds
for sign-in to full population as provisional planning figures, not acceptance
evidence. Refresh can be budgeted around 3–3.5 seconds using the API projection
plus the observed browser refresh overhead. Independently extrapolating the two
refresh medians produces an implausible 2.609 seconds, below the API projection;
this demonstrates why two noisy end-to-end samples do not establish a reliable
scaling model for every stage.

These estimates assume the same machine, warm caches, comparable concurrency,
four-level hierarchy, one unit, no active holds and proportional growth to
84,000 aggregations, 368,000 components and 11,040,000 synthetic activity events.
Different query plans, cache capacity, disk spills, ACL structure and data
changes can make the actual result slower. No 184,000-record fixture was run.
