# Dashboard

This is the dashboard's feature and implementation guide. The
[optimization and maintenance reference](#optimization-and-maintenance) below
records the query design, identity isolation, indexes, performance evidence and
regression coverage verified on 4 November 2026.

The [WebUI performance contract](webui-performance.md) remains normative for
loading, refresh and caching. The separate
[verification report](verification/dashboard-isolation-performance.md) records
test outcomes, benchmark methods, execution plans and deployment receipts.
This guide documents the implemented design under those contracts; it does not
add privileges, lifecycle states or dashboard workflows.

## Client API

All dashboard clients, including web and mobile clients, should load the
dashboard through this single authenticated endpoint:

```http
GET /api/v1/dashboard/summary?recent_limit=4&recent_since=2026-08-22T00:00:00Z
```

Do not construct the dashboard by issuing separate entity-search, count,
favourites, recent-activity, classification-metric, or ownership-count
requests. That fan-out consumes multiple HTTP connections and database-pool
checkouts, can produce an internally inconsistent snapshot, and can overload a
small deployment when several dashboards refresh together. The summary
endpoint performs the complete read through one HTTP request and one database
pool checkout.

The query parameters are:

| Parameter | Required | Default | Meaning |
| --- | --- | ---: | --- |
| `recent_limit` | No | Database `DASHBOARD_RECENT_ITEM_LIMIT` (initial `4`, request window at most 50) | Maximum recent items for each entity-type/operation group; accepted range is 1–50 |
| `recent_since` | No | Database `DASHBOARD_RECENT_DAYS` (initial `30` days) | ISO 8601 timestamp; excludes older personal activity |

The response has this stable top-level shape:

```json
{
  "overview_counts": {"aggregations": 12, "records": 48, "holds": 3},
  "overview_medium_counts": {
    "aggregations": {"physical": 3, "digital": 5, "mixed": 4},
    "records": {"physical": 8, "digital": 32, "mixed": 8}
  },
  "overview_resource_attention_counts": {
    "aggregations": {"vital": 2, "held": 3},
    "records": {"vital": 7, "held": 11}
  },
  "overview_aggregation_status_counts": {"open": 9, "closed": 3},
  "overview_digital_component_metrics": {
    "component_count": 126,
    "storage_size_in_bytes": 58300824
  },
  "classification_metrics": {
    "published_scheme_count": 1,
    "draft_scheme_count": 0,
    "inactive_scheme_count": 0,
    "branch_count": 8,
    "terminal_count": 24,
    "assignable_terminal_count": 20,
    "draft_terminal_count": 0,
    "inactive_classification_count": 0
  },
  "unclassified_root_count": 2,
  "ownership_counts": [
    {
      "org_unit_id": 10,
      "org_unit_code": "FIN",
      "org_unit_name": "Finance",
      "aggregation_count": 6,
      "open_aggregation_count": 5,
      "closed_aggregation_count": 1,
      "record_count": 31,
      "physical_record_count": 8,
      "digital_record_count": 20,
      "mixed_record_count": 3,
      "vital_record_count": 4,
      "storage_size_in_bytes": 21048120
    }
  ],
  "favourites": {"aggregations": [], "records": []},
  "recent_activity": []
}
```

`overview_counts` always includes the aggregation and record counts visible to
the caller. `overview_medium_counts` breaks those visible totals down by
physical, digital, and mixed medium. `overview_aggregation_status_counts`
breaks the visible aggregation total down by open and closed state, using
whether `date_closed` is null. The attention counts report visible vital and
effectively held aggregations and records. Digital-component count and storage
size include components belonging to visible records only. The absolute system-wide hold total is
included only when the caller has `holds.administer`. Other administrative
entity totals are included only when the caller has their corresponding global
privileges; classification metrics remain zero
without classification-administration privilege. Holdings,
favourites, and recent activity use the same resource-visibility rules as their
normal APIs. `ownership_counts` contains only organizational units in which the
current user has a currently effective role, with each unit appearing once.
Favourites and recent activity are private to the authenticated user.

Clients should prevent overlapping refreshes of this endpoint. A refresh
requested while one is already in flight should reuse, await, or decline the
existing request rather than start another concurrent dashboard load.

The WebUI's navigation, caching, and non-destructive refresh behavior is
normatively defined in the
[WebUI performance contract](webui-performance.md#5-dashboard-navigation-and-refresh).
Returning to the Dashboard must render the last page-session summary
immediately and revalidate it in the background; it must not blank and rebuild
the page while waiting for this endpoint.

The Dashboard combines authorized entity totals with personal recent records
activity. Aggregation and record totals follow the caller's resource visibility.
Administrative totals are available only to callers with the corresponding
global privileges. Recent aggregation and record lists are scoped to the
currently authenticated user.

## Dashboard visualizations

The web Dashboard supplements its existing cards and lists with four compact
visualizations. They use the existing consolidated summary response and must
not issue additional API requests:

- **Attention signals** appears below the administration-count strip and uses
  grouped bars to compare visible vital and effectively held aggregations and
  records. The existing vital and held counts remain in the Aggregations and
  Records overview cards.
- **Records by medium** appears above the existing organizational-unit holdings
  rows. Each horizontal bar represents an eligible organizational unit and is
  split into physical, digital, and mixed record segments. The bar total is the
  unit's authorized record count. The existing clickable unit rows remain the
  detailed view.
- **Review urgency** appears beside the existing Overdue and Upcoming reminder
  lists. It divides the complete authorized review count between overdue items
  and items due within the configured warning window. The existing previews,
  dates, empty states, and **View all** actions remain. A complete review list
  is server-paginated at 25 visible rows. The client requests one additional
  look-ahead row only to determine whether **Next** is available; it must not
  download every authorized review before showing the first page.

Hold creation and contributor management use the existing governed user-search
endpoint. They request 25 active person accounts at a time, support searching
by name, email, or external identifier, and retain already-selected identities
while navigating result pages. These dialogs must not preload the complete user
directory or cache it as stable reference data.
- **Digital storage by organizational unit** is the final Dashboard section.
  It ranks eligible units by authorized digital-component storage, shows the
  largest five individually, and folds all remaining eligible units into one
  clearly labelled **Other units** summary. Exact formatted storage totals and
  percentage shares remain visible without squeezing every unit into the plot.

The visualizations are comparative presentations of counts already present in
the response. They do not create new data scopes, privileges, resources, or
drill-down operations. Zero-count categories remain valid, and a user with no
eligible organizational-unit holdings receives the existing holdings empty
state rather than an invented chart row.

## Dashboard data visibility

Access to the Dashboard and its four visualizations requires an authenticated
session. The API remains the authorization boundary; hiding or showing a UI
element is not a substitute for server-side filtering.

| Dashboard section | Data-visibility rule |
| --- | --- |
| Aggregations and Records overview | Counts include only resources visible to the caller through the normal authorization, clearance, and ACL predicates. Medium, open/closed, vital, held, component-count, and storage metrics use that same visible set. |
| Attention signals | Uses the authorized overview attention counts. No extra global privilege is required. A user sees only vital and effectively held aggregations and records they can already view. |
| Administration counts | Each item is included only when the caller has its corresponding global privilege: `classifications.administer` for Schemes and Classifications, `holds.administer` for Holds, `organization.administer` for Organization units and Roles, and `identity.users.administer` for Users. These privileges control the administration items, not the Attention signals chart beneath them. |
| Holdings by organizational unit and Records by medium | Includes each distinct organizational unit represented by a currently effective role held by the caller. Multiple effective roles in one unit produce one entry. Within each eligible unit, counts include only aggregations and records the caller is authorized to view. An eligible unit with no visible holdings reports zero. Future, expired, or ineffective roles do not add units. |
| Digital storage by organizational unit | Uses the same eligible organizational units as Holdings. Each unit's storage is the sum of digital-component bytes belonging to records the caller is authorized to view. The five largest totals are shown individually; all remaining eligible units are combined into **Other units**. Ranking and aggregation do not reveal units outside the caller's effective-role scope. |
| Review urgency and reminder lists | Includes only reviewable aggregations and records owned by an organizational unit represented by one of the caller's currently effective roles. Within that ownership scope, normal resource visibility, security-clearance, and ACL rules apply. The information-governance custodian bypass does not add unrelated organizational units. |
| Governance attention | Unclassified-root counts include only root aggregations visible to the caller. Classification administration metrics and navigation require `classifications.administer`. |
| Favourites and recent activity | Private to the authenticated user and filtered again through current resource visibility so deleted or no-longer-visible resources are omitted. |

A user does not need any of the four administration privileges to see the four
visualizations. An effective organizational-unit role is required for Holdings
Review, and Digital storage sections to contain organizationally scoped data;
without one, those sections show their existing empty or zero states. A user needs all four global
administration privileges listed above only to see every administration-count
item above Attention signals.

## Personal favourites

Authenticated users can mark aggregations and records as private favourites by
selecting the heart control in entity tables, aggregation content lists, and
the full aggregation or record interface. A filled heart removes the favourite.
Favourite state remains available across sessions and is isolated by user.

The Dashboard shows separate newest-first previews for favourite aggregations
and records. Each preview observes `DASHBOARD_FAVOURITE_ITEM_LIMIT`. When a
collection exceeds that limit, **View all** opens its complete scrollable list.
Selecting an entry opens the existing aggregation or record interface. Removing
an entry updates the preview and complete list without opening the entity.
The combined Favourites and Recent records activity panel appears immediately
after Overview and before Holdings by organizational unit.

The Aggregations and Records search and listing pages also show the
authenticated user's corresponding favourites preview above recent activity or
search results. They use the same limit and **View all** behavior as the
Dashboard previews.

Favourites are navigation preferences rather than governed entity changes.
They do not update entity versions or create event-history entries. Deleting a
user, aggregation, or record automatically removes its dependent favourite
relationships.

## Personal recent activity

An item qualifies when its immutable event-history entry:

- has `actor_user_id` equal to the authenticated user's ID;
- is a `CREATE` or `UPDATE` event for an aggregation or record, or a
  `CONTENT_VIEWED` event for one of a record's digital components; and
- occurred within the configured rolling period.

`CONTENT_VIEWED` activity is attributed to both the containing record and its
containing aggregation. The Dashboard's recent-record stream presents the
record attribution; the Records and Aggregations pages present the attribution
appropriate to their resource type. Viewing a governed component therefore
makes both resources recent without exposing the component through a separate
activity card. Only the newest qualifying view for each record or aggregation
is retained. Each category is ordered by `event_history.occurred_at`, newest
first. The time shown on a card is that activity timestamp. Deleted or
no-longer-visible entities are omitted because there is no currently authorized
resource to open.

## Optimization and maintenance

### Design and implementation map

The dashboard combines one client request with database aggregation and a
private, immediately revalidated visual snapshot. These optimizations preserve
the visibility rules above and the approved
[authorization](../specs/security-and-authorization-subsystem.md),
[organizational ownership](../specs/organizational-ownership-and-default-acls.md#121-dashboard-counts),
[resource review and attention](../specs/resource-medium-vital-status-review-and-location.md#14-dashboard-and-notifications)
and [disposition](../specs/disposition.md) specifications.

| Area | Implemented optimization | Implementation |
| --- | --- | --- |
| Client requests | One authenticated summary request and one database-pool checkout; charts reuse the same response. No separate configuration or favourites request is needed to populate the dashboard. | [API client](../frontend/webui/api_client.py), [WebUI](../frontend/webui/app.py) |
| Resource metrics | Shared statement-local authorized sets feed overview, ownership, storage, reviews, favourites, recent activity and relationship redaction. SQL returns aggregated metrics instead of Python fetching and authorizing individual resources. | [Dashboard API](../backend/services/api/dashboard.py) |
| Authorization | Roles, privileges, clearance, organizational context and ACL sources are computed as sets for the authenticated connection identity. | [Visibility SQL](../backend/services/api/dashboard_visibility.py) |
| Retained history | Nonterminal resource sets are selected before ACL/hold calculations; the hierarchy includes only those resources and their required ancestors/containers. | Visibility SQL and migrations 101–102 |
| Holds | Active aggregation holds propagate down the required hierarchy once; direct record holds form a distinct set. Overlapping assignments cannot multiply resource totals. | Dashboard API |
| Storage | Components are grouped by record before joining resource rollups, avoiding duplicated record counts. A covering index supplies record IDs and byte sizes. | Dashboard API and migration 100 |
| Activity | Latest personal events are grouped and capped in SQL, then candidate resource IDs join the shared authorized sets. Partial indexes avoid unrelated event categories and reduce sorting/heap reads. | Dashboard API and migrations 098–099 |
| Other totals | Administrative counts share one SQL request; classification activity and inherited retention-rule existence propagate through a recursive set. | Dashboard API |
| Rendering | Same-session navigation renders its existing snapshot immediately and refreshes once in the background. Refresh retains visible data while loading. | WebUI and API client |

One HTTP summary does not mean one SQL statement for every section. Resource
metrics share one statement; administrative and classification rollups use
additional statements on the same checked-out connection. Authorization sets
exist only for their statement and are never cached across requests or users.

### Snapshot scope, freshness and user isolation

The visual snapshot belongs to one browser-page client. Its key contains the
login-session revision, user ID, effective language, working timezone, known
global privileges and effective role IDs. It is held in page-session memory;
it is not persisted to browser storage or a shared server cache.

The implemented lifecycle is:

1. A fresh visit renders loading placeholders and obtains the first summary.
2. Return navigation renders a matching snapshot immediately, then always
   revalidates it. The snapshot has no TTL that suppresses this refresh.
3. Explicit Refresh follows the same path. Only one summary load may run for
   the current view at a time.
4. Successful login, sign-out and session rejection clear the snapshot and
   advance the revision, including a new login to the same account. Sign-out
   removes protected content before awaiting the remote logout response.
5. Every response is checked against its captured identity/key and unique view
   token before updating the snapshot, configuration, favourites or UI. A
   language/identity change, navigation, a newer view, or a disconnected/deleted
   client or container abandons the old response.
6. API-client credential changes also advance a request generation and cancel
   pending reads. A late response or 401 from an earlier login cannot update
   or sign out the newer user.

A failed same-user refresh retains that user's snapshot and restores the
Refresh control. A failed first load shows the existing error state without
displaying another identity's data. Favourite/review callbacks use the same
ownership guards. Returning after a mutation revalidates the data, so the
snapshot cannot become a permanent substitute for current authorization.

### Authorization, lifecycle and hierarchy correctness

`dashboard_visibility.py` is a set-based equivalent of
`current_user_can_view_aggregation` and `current_user_can_view_record` within
the nonterminal dashboard scope.
Differential tests compare it with those canonical functions. It preserves
global view privileges, account/role/unit effectiveness, clearance, governance
clearance, contextual managers, nearest file administrators, ACL inheritance
breaks, custom child defaults and the target resource's owning unit.

Assigned roles used for ownership retain the canonical inclusive
`valid_until >= CURRENT_TIMESTAMP` boundary. View/review effective roles retain
the exclusive `valid_until > CURRENT_TIMESTAMP` boundary. Consolidating SQL
must not silently normalize that deliberate distinction.

Disposed resources never enter dashboard live counts or supporting output:

| Status | Outcome | Dashboard live scope |
| ---: | --- | --- |
| 10 | Destroyed | Excluded |
| 11 | Permanently transferred | Excluded |
| 12 | Retained as local archives | Excluded |
| 13 | Partially disposed — action required | Included when normal authorization/scope permits |

This rule applies to every caller, including governance users, and every
resource section: overview, holdings, medium/vital/hold totals, components and
storage, reviews, favourites and activity. See the
[approved live-scope rule](../specs/disposition.md#4-disposition-status-catalogue).
The original destroyed rows remain as required by
[retained destruction metadata](../specs/disposition.md#142-metadata-retained-after-destruction),
so completed disposition does not imply that historical resource rows disappear
from the database. Filtering only
the final counts would still make historical rows enlarge ACL and hold work.
The live CTEs apply `disposition_status NOT IN (10,11,12)` at the start.

Here, **live means nonterminal**, rather than a new product lifecycle state.
The former governance exception for status-11/12 overview totals is removed.
Controlled retained-resource search/disposition/audit access elsewhere retains
its existing authority; it does not add disposed resources to the dashboard.

The required aggregation graph excludes unrelated disposed branches, while
retaining any ancestor or container needed by a nonterminal resource. This
also preserves canonical inherited ACL/hold behavior for legacy terminal-unit
shapes. Such retained ancestors provide calculation context; they are not
made visible in counts or relationship references. Hold validity remains
half-open, inherited holds cross ACL inheritance breaks, and each held resource
is counted once.

Favourites and recent activity remain private to the current user and recheck
current visibility. Inaccessible parent references are redacted independently
of the child's visibility. Recent activity preserves latest-per-resource/event
grouping and applies its per-group cap **before** joining visibility; moving
that cap would change which items qualify. Review pages reuse the same
visibility sets and retain server pagination.

### Database indexes

These five dashboard indexes are defined in the self-contained
[canonical schema](../database/schema.sql) and in upgrade migrations:

| Index | Keys, included columns and predicate | Purpose / migration |
| --- | --- | --- |
| `event_history_dashboard_resource_latest_idx` | `(actor_user_id, entity_type, entity_id, operation, occurred_at DESC, id DESC)`; only aggregation/record `CREATE` and `UPDATE` events | Match personal latest-event grouping and ordering; [098](../database/migrations/098_dashboard_resource_activity_index.sql) |
| `event_history_dashboard_content_views_idx` | `(actor_user_id, occurred_at DESC, id DESC) INCLUDE (entity_id, operation)`; only digital-component `CONTENT_VIEWED` events | Restrict personal views by actor/time and cover all required event columns; [099](../database/migrations/099_dashboard_content_activity_index.sql) |
| `digital_components_dashboard_storage_idx` | `(record_id) INCLUDE (size_in_bytes)` | Aggregate component counts/bytes without loading component metadata when an index-only scan is possible; [100](../database/migrations/100_dashboard_component_storage_index.sql) |
| `aggregations_dashboard_live_idx` | `(id) WHERE disposition_status NOT IN (10,11,12)` | Read nonterminal aggregations as retained history grows; [101](../database/migrations/101_dashboard_live_resource_indexes.sql), corrected by [102](../database/migrations/102_dashboard_nonterminal_resource_indexes.sql) |
| `records_dashboard_live_idx` | `(id) WHERE disposition_status NOT IN (10,11,12)` | Read nonterminal records as retained history grows; [101](../database/migrations/101_dashboard_live_resource_indexes.sql), corrected by [102](../database/migrations/102_dashboard_nonterminal_resource_indexes.sql) |

The live indexes deliberately exclude large titles and mutable metadata.
They complement existing hierarchy, owner, review, favourite and assignment
indexes. PostgreSQL can choose a sequential scan when most rows are live;
index-only scans also depend on normal vacuum/visibility-map maintenance.
Index presence alone is not performance evidence: inspect actual rows, loops,
buffers, heap fetches and discarded join pairs on representative data.

### Exact counts and measured limits

Exact authorized totals still process the nonterminal resource subset and
its relevant grants, components and context. An index reduces irrelevant
history reads; it does not store every user's exact, currently authorized
dashboard count. Personal audit-history work also grows independently of the
retained resource graph. There is no approximate counter, materialized dashboard
summary or cross-request authorization cache in this implementation.

The verified warm local measurements are summarized here. Full fixture shapes,
sample ranges, scope and cleanup evidence are in the
[benchmark report](verification/dashboard-isolation-performance.md#benchmark-method-and-results).

| Non-destroyed records | Summary API median | Sign-in to populated dashboard | Complete refresh |
| ---: | ---: | ---: | ---: |
| 1,840 | 41.29 ms | 387 ms | 288 ms |
| 18,400 | 305.99 ms | 779 ms | 499 ms |

Those full API/browser runs used the implementation through migration 100,
before migration 101. They include proportional aggregation/component/activity
volumes. The later isolated ordinary-reader resource-query comparison includes
95% destroyed metadata and live records distributed across live aggregations:

| Non-destroyed records | Destroyed record metadata | Resource SQL before | Resource SQL after |
| ---: | ---: | ---: | ---: |
| 1,840 | 34,960 | 120.32 ms | 11.75 ms |
| 18,400 | 349,600 | 9,194.31 ms | 81.26 ms |

The second table measures resource SQL without the bulk component/activity
payload of the first fixtures; it cannot replace full page-loading timings.
Both timing series predate migration 102. Their resource fixtures use statuses
1 and/or 10; the broader 10/11/12 exclusion is verified separately with mixed
terminal data and actual execution plans.
The earlier large plan discarded 154,541,600 record/ACL join pairs. Early
filtering eliminated that quadratic work; the new partial indexes reduced
resource reads further. The all-live 1,840-record comparison changed from
10.25 to 14.09 ms, showing the small fixed cost of the additional CTE stages.
See [retained-metadata evidence](verification/dashboard-isolation-performance.md#retained-destruction-metadata-comparison).

Timings are observations on the local development machine, not deployment
guarantees. There is no measured 184,000-record end-to-end result; the
[earlier projection](verification/dashboard-isolation-performance.md#projection-to-184000-records-not-measured)
is explicitly an estimate from the pre-101 all-live fixtures. Measure the target
hardware, ACL distribution, hierarchy, history, concurrency and cold/warm state
before setting a deployment latency target. More RAM/CPUs alone do not establish
the duration of a single request.

### Regression coverage and future changes

| Contract / failure mode | Implementation | Regression evidence |
| --- | --- | --- |
| No cross-user/language snapshots or late-response writes | `app.py`, `api_client.py` | [Session isolation](../frontend/webui/tests/test_dashboard_session_isolation.py), [API client](../frontend/webui/tests/test_api_client.py), [real NiceGUI identity interactions](../frontend/webui/interaction/tests/test_dashboard_identity.py) |
| Canonical ACL/role/clearance equivalence, including identity changes on one prepared connection | `dashboard_visibility.py` | [Differential visibility tests](../backend/services/api/tests/test_dashboard_set_visibility.py) |
| Hidden resources, private favourites and inaccessible parents | Shared authorized sets in `dashboard.py` | [Read authorization](../backend/services/api/tests/test_phase6_read_authorization.py) |
| Ownership and review-setting scopes | Grouped ownership/review SQL | [Ownership](../backend/services/api/tests/test_organizational_ownership_phase4.py), [application settings](../backend/services/api/tests/test_application_settings_phase4.py) |
| Lifecycle, holds, component multiplication, shared sets and canonical/idempotent indexes | Dashboard SQL and schema/migrations | [Dashboard regressions](../backend/services/api/tests/test_dashboard_regressions.py) |
| Disposed statuses 10/11/12 excluded for all callers/cards; status 13 preserved; required retained ancestors preserved; live indexes used; no quadratic ACL comparison | Live sets and required hierarchy | [Retained-metadata regressions](../backend/services/api/tests/test_dashboard_retained_metadata.py), [lifecycle/index upgrade tests](../backend/services/api/tests/test_dashboard_regressions.py) |

The verification report records 62 focused API and 90 frontend cases passing,
plus live English/Arabic, navigation, mutation freshness and account-isolation
checks. Those are dated verification outcomes, rather than a claim that every
repository test passed.

When changing these paths, preserve one summary request, identity/language
isolation, current authorization and non-destructive refresh. Keep permission,
role-effectiveness, contextual-ACL and hold-ancestor functions out of
per-resource dashboard loops. Validate actual work on both live-heavy and
history-heavy fixtures; set-based SQL can still acquire a costly nested-loop
plan when estimates change. Compare IDs and values with canonical behavior as
well as inspecting the plan. General localization/catalogue and initial-load
rules remain in the [WebUI performance contract](webui-performance.md).

All database-backed verification must use a newly named disposable database,
initialize it from the canonical schema and separate seeds, and drop it on
success or failure. Never benchmark or run test fixtures on `demo` or another
persistent database. The report contains the
[regression and benchmark commands](verification/dashboard-isolation-performance.md#regression-evidence).

### Deployment and maintenance

New databases load `database/schema.sql` and separate reference seeds; the
schema does not execute migrations. Existing installations apply pending
migrations 098–102 in order using the repository's
[database upgrade procedure](../database/README.md). Keep canonical definitions
and upgrade DDL equivalent, and retain idempotent upgrade tests.
Migration 102 rebuilds the two status-10-only indexes deployed by 101 with the
complete `NOT IN (10,11,12)` predicate. Keep the already-applied migration 101
unchanged; new databases receive the final definitions from the canonical schema.

After upgrading, verify migration receipts and valid/ready indexes and update
planner statistics for the affected resource, component and event tables.
Normal database vacuum maintenance remains necessary. Reload/restart the API
and WebUI for changed Python code unless development reloaders already picked
it up. Local stack startup does not apply migrations. These changes introduce
no environment settings, UI strings or translation-artifact changes.

Migrations 098–102 were applied to the authorized local `demo` database on
4 November 2026; the
[deployment record](verification/dashboard-isolation-performance.md#deployment)
contains the receipt locations and checks. That deployment is separate from
the disposable verification runs.

## Configuration

These settings are shared PostgreSQL application settings, edited through
Administration → Settings. The API supplies effective values in its page
responses; NiceGUI has no environment fallback or authoritative settings cache:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `DASHBOARD_FAVOURITE_ITEM_LIMIT` | `5` | Maximum entries in each Dashboard and entity-listing favourites preview |
| `DASHBOARD_RECENT_ITEM_LIMIT` | `4` | Maximum records shown in the combined created, updated, and content-viewed Dashboard preview |
| `DASHBOARD_RECENT_DAYS` | `30` | Rolling number of days included in personal recent activity |

All values must be positive integers. Changes propagate through the API's
30-second validated cache without a service restart. Existing custom environment
values require the reviewed upgrade procedure in
[application settings upgrade](application-settings-upgrade.md). The summary
also returns the finite `application_configuration` values used by its previews.
Review previews and user-detail session transport windows remain at most 50;
recent-classification selections are independently paged in at most 20-row
windows. A configured limit remains the maximum, not permission to download a
complete collection.
