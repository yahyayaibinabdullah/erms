# Dashboard

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
