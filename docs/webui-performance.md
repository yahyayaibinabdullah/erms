# Wathiq WebUI performance contract

**Status:** Normative  
**Applies to:** Wathiq browser WebUI, its FastAPI calls, and supporting localization runtime  
**Audience:** Human developers, reviewers, and agentic implementation tools  
**Prepared:** 26 September 2026

## 1. Purpose

This document defines the performance rules that new and changed Wathiq WebUI
work must preserve. It records the optimizations introduced after
internationalization increased page-render and dashboard latency, and turns
them into development constraints rather than one-time fixes.

Correctness, authorization, accessibility, localization, and freshness remain
mandatory. Performance work must not bypass authorization, expose one user's
cached data to another user, publish draft translations, or hide failures.

## 2. Performance model

A page transition has four distinct costs:

1. server-side Python and NiceGUI component construction;
2. API round trips and database execution;
3. serialization and transfer of response and UI updates;
4. browser layout, font loading, hydration, and painting.

Do not assume that a visible pause is a database problem. Measure or inspect
each tier. In particular, a fast API cannot compensate for repeatedly parsing
a large catalogue or rebuilding unchanged UI chrome.

## 3. Localization runtime

### 3.1 English manifest

`frontend/webui/i18n_catalogue.py::load_english_manifest` is a process-local,
memoized loader. It parses and validates `messages.en.json` once per frontend
process. Every message render must use that shared result.

Never:

- read or parse a catalogue file inside `render_message` call sites;
- copy the manifest into page-local state;
- clear the manifest cache during normal requests; or
- add filesystem polling to the message-render hot path.

Catalogue files are development/deployment artifacts. Restarting or reloading
the frontend process activates a changed English manifest.

### 3.2 Bootstrap and effective catalogue

`GET /api/v1/i18n/bootstrap` returns locale metadata only. It must not embed a
complete English message map. The effective catalogue is obtained separately
from `/api/v1/i18n/catalogues/{language_tag}`.

The browser session stores:

- localization context;
- effective messages;
- fallback keys; and
- the catalogue ETag.

If language and catalogue revision are unchanged, reuse the session catalogue.
If revalidation is required for the same language, send `If-None-Match` and
reuse cached messages on `304 Not Modified`. Never send an ETag unless the
corresponding cached message set is also available.

The catalogue endpoint keeps both its canonical JSON bytes and a deterministic
gzip representation in the revision-scoped server cache. Serve gzip only when
the client advertises support and include `Accept-Encoding` in `Vary`. Keep
this compression route-specific; global compression must not recompress PDFs,
archives, images, or other already-compressed responses.

A catalogue-revision change must not force a full browser reload. A full
reload is reserved for a language or document-direction change because those
alter the application shell. Saving user language preferences must clear the
context, messages, fallback keys, and ETag together before reloading.

### 3.3 Translation Inspector metadata

Encoding a contextual key into diagnostic metadata is memoized by key. Do not
re-encode the same key for every rendered occurrence. Inspector optimizations
must preserve its privilege gate and must not attach message keys to
user-authored or multilingual domain values.

The browser MutationObserver must be disconnected while the inspector is
unauthorized or disabled. Enabling the inspector performs one document scan
and then connects the observer; disabling it disconnects the observer again.
Never make an off-by-default diagnostic feature observe or walk ordinary page
mutations.

Diagnostic metadata is enabled only after the authenticated principal has the
`localization.administer` privilege and is removed immediately on sign-out or
privilege loss. The observer batches mutation roots per animation frame,
observes only translatable attributes, and must not observe `class` or `style`.
Inspector event listeners exist only while it is enabled. Inspection must never
cancel or modify an application event.

## 4. Initial application load

Authentication, locale selection, and the requested application page form the
critical path. Optional assets do not.

Load these after the authenticated workspace can proceed:

- Translation Inspector JavaScript;
- PDF viewer JavaScript; and
- decorative login animation assets.

Optional-asset failure must not prevent the dashboard or another ordinary page
from opening. Await a browser response immediately after creating it, as
required by NiceGUI, but perform the containing optional workflow through a
background task.

Do not add a new script, font, diagnostic tool, previewer, or animation to the
critical path without evidence that the initial page requires it.

## 5. Dashboard navigation and refresh

The dashboard uses one authenticated summary endpoint. Do not replace it with
client fan-out to separate count, favourites, activity, classification, review,
or ownership endpoints.

Dashboard navigation follows stale-while-revalidate behavior:

1. On the first visit, render stable page chrome and localized loading
   placeholders while obtaining the first summary.
2. Store the successful summary in page-session state.
3. On return navigation, render that summary immediately.
4. Start one background summary refresh.
5. Keep existing dashboard content visible while refreshing.
6. Replace dashboard data when the fresh authorized response arrives.
7. Ignore the response if the client disconnected or navigated elsewhere.

The Refresh action uses the same non-destructive refresh path. It may display a
compact loading state on the Refresh control, but must not blank the dashboard.
Overlapping refreshes are prohibited.

The cached summary is only an immediate visual snapshot. It does not suppress
the background refresh, so returning after creating a record will update counts
and activity without requiring the user to press Refresh.

Dashboard summary data must not be shared between identities or languages.
Any future persistence beyond page-session state requires an explicit cache key
containing at least user identity and effective language, plus a documented
invalidation policy.

## 6. Page API orchestration

Long disposition operations must use the durable server-owned contract in
`specs/disposition.md` §17.10. A browser callback obtains acceptance, then releases
its busy state; it must not await application, bulk execution or PDF generation
through a long HTTP request or modal. Navigation and disconnect never cancel
accepted work. Poll only mounted views, stop/ignore abandoned responses, keep
reads bounded and treat failed status reads separately from failed work. Reopen
from fresh authorized server state. Approval has indeterminate phase progress;
digital destruction uses real committed-unit counts. Do not invent percentages.
No new progress cache is introduced; identities and languages retain their
existing page-session isolation.

Independent requests should run concurrently with `asyncio.gather`, within the
bounded request concurrency enforced by `ErmsApiClient`. Current examples are:

- favourites and recent activity on Records and Aggregations landing pages;
- recent activity and the aggregation hierarchy needed to decorate it; and
- role reference lists that are independent of one another.

Do not parallelize requests when one determines the authorization, identifier,
version, or parameters of another. Do not bypass the API client's request-slot
limit.

Before adding a supporting request, determine whether the page already loaded
the same rows. Pass already-loaded reference rows to decorators and selectors.
For example, an organization-unit listing must not immediately download the
complete organization-unit list again merely to resolve parent labels.

Avoid this pattern:

```python
rows = await api.list(resource)
return await decorate(rows)  # decorate downloads resource again
```

Prefer explicit dependency injection:

```python
rows = await api.list(resource)
return await decorate(rows, related_rows=rows)
```

Reference caches must have an invalidation rule. After create, update, delete,
translation change, privilege change, or identity change, either invalidate the
affected data or obtain it again. Never retain authorized entity data across
sign-out or use it for another identity.

Identical concurrent `GET` and `HEAD` requests made through one page's
`ErmsApiClient` are coalesced into one HTTP operation. Each caller receives a
deep copy because UI decorators may mutate returned dictionaries. Mutations
must never be coalesced. This is a final safety net, not permission to leave
known duplicate call sites in place: when one workflow uses the same response
twice, keep it in page/workspace state and invalidate it on an explicit refresh
or related mutation. The classification workspace follows this rule for paths
used to render ancestor navigation and retention provenance on its details page.

Small, deliberately complete catalogues may be cached by the API client for the
authenticated browser-page session. Cache entries are private to that client
and therefore to its identity. A mutation or identity/token change clears the
complete reference cache conservatively. After 30 seconds, a reused entry is
conditionally revalidated with its ETag; `304 Not Modified` refreshes its
validation time without transferring or decoding the collection again.
Reference endpoints must emit deterministic, private ETags over their effective
localized response.

Caching is not permission to download an unbounded collection. Organization
units, roles, users, aggregations, records, classifications, holds, and any
other tenant-grown entity must use server search or paging even when the rows
are used only as selector labels. Operational collections such as audit events,
reviews, and search results are never stable-reference cached.

### 6.1 Bounded collection and relationship contract

Every relationship/reference collection request and every non-search-first
administration listing request made for a screen or dialog must be one of:

1. a server page, normally 25 rows and never more than 50 without a documented
   screen-specific reason;
2. a server-side type-ahead search page for a relationship selector;
3. direct reads of the small set of IDs already selected or present in the
   current result page; or
4. an explicitly documented finite catalogue whose complete membership is
   required by the UI (the permission matrix is the current example).

Do not call `api.list(resource)` for a tenant-grown resource. The client's
historical default limit is a compatibility detail, not a safe UI contract.
Do not fetch 100 or 500 rows and then apply browser-side filtering or
pagination; that is truncation disguised as pagination.

Relationship selectors must:

- load no large option list when the dialog opens;
- request at most 25 matching rows when opened or searched;
- debounce typed searches;
- retain the selected row even when it is not in the current result page;
- exclude ineligible rows on the authoritative query path where possible; and
- revalidate eligibility when saving.

Hierarchies load roots and children independently. Each branch uses look-ahead
paging and an explicit Load more action. Never download an entire hierarchy to
resolve a parent label, effective closure, or inherited status. Use direct ID
reads, walk only the selected ancestor chain, or expose a narrow authorized API
such as `aggregations/{id}/effective-closure`.

Non-search-first administration listings use true server pagination. Search,
status, account type, sort, page size, and offset belong in the API request.
Page totals come from the server. Client-side pagination is permitted only
after the server has returned a deliberately complete finite result. Primary
record/aggregation search-result limits are governed separately by each search
screen's result contract and must still avoid an unbounded download.

Dashboard complete-review lists use true server pagination: 25 visible rows
plus one look-ahead row to determine whether another page exists. Do not loop
through every review page merely to populate the first screen. This avoids a
separate count query while bounding each request and rendered component set.

Hold owner and contributor selectors also use server-side pages of 25 active
person accounts with name, email, and external-identifier search. Selected
identities remain available across pages, but the complete user directory is
never prefetched or stored in the stable-reference cache.

Starting a committed navigation cancels unfinished reads from the previous
page. Page-specific tasks must tolerate `CancelledError` without displaying a
failure notification or modifying the newly selected page.

## 7. Rendering rules

- Preserve stable page chrome while data refreshes.
- Update the smallest practical data region instead of blanking and rebuilding
  the whole page.
- Do not show a full-page loading state when usable prior data exists.
- Prevent stale background tasks from modifying a page that has been deleted or
  is no longer current.
- Do not render the same page twice solely to establish its empty and loaded
  states when a stable container and targeted data update can express both.
- Keep large collections search-first and paginated; do not load every entity
  merely to display an initial listing.
- A UI pagination widget over a 100/500-row download is not pagination. Verify
  that changing pages changes the request offset.
- Render primary page controls and results before below-the-fold or secondary
  personal sections. Update the secondary section's retained host rather than
  clearing and rebuilding the complete page when its data arrives.

These rules supplement the normative
[Wathiq WebUI Design Language](webui-design-language.md).

## 8. API and database rules

- Prefer a cohesive endpoint that returns one internally consistent page
  snapshot over many small calls for the same screen.
- Keep authorization inside every query or authoritative API boundary.
- Avoid repeatedly evaluating the same expensive authorized view or function
  for several cards in one response; consolidate compatible aggregates when
  query plans show material repetition.
- Select only fields needed by the client. Do not embed complete catalogues or
  unrelated reference collections in bootstrap responses.
- Add indexes or rewrite queries only with plan evidence and representative
  data. Never weaken row visibility to improve a query plan.
- Database-backed performance tests must follow `AGENTS.md`: use a uniquely
  named disposable database and remove it after the run.

## 9. Cache safety and invalidation

Every cache must document:

| Property | Required decision |
| --- | --- |
| Scope | process, page client, browser session, identity, or shared server |
| Key | language, revision, user, privilege context, query parameters, and other dependencies |
| Freshness | immutable, explicit revision, TTL, or stale-while-revalidate |
| Invalidation | the exact event that clears or supersedes the value |
| Failure behavior | safe fallback when cache or revalidation fails |
| Security | proof that one identity cannot receive another identity's data |

Use revision or ETag validation for immutable/versioned resources. Use
stale-while-revalidate for overview information where immediate navigation and
automatic freshness are both required. Do not cache mutation responses as if
they were generally reusable reads.

## 10. Verification requirements

For performance-sensitive WebUI changes:

1. Compile changed Python modules.
2. Run focused tests for the affected page, API client, and localization path.
3. Run `git diff --check`.
4. Inspect the live browser when layout, loading state, or navigation behavior
   changed.
5. Confirm that repeated navigation does not create overlapping requests.
6. Confirm that creating or updating relevant data becomes visible after the
   automatic refresh.
7. Confirm English/LTR and Arabic/RTL behavior.
8. Record a reproducible timing or request-count comparison for a material
   performance change when practical.

Tests should assert architectural invariants, including catalogue memoization,
ETag reuse, absence of duplicate requests, background dashboard revalidation,
and prevention of destructive loading states.

## 11. Human and AI implementation checklist

Before declaring a new or changed screen complete, answer all of the following:

- Am I parsing, validating, formatting, or encoding immutable data repeatedly?
- Am I issuing the same API request twice during one page transition?
- Can independent API calls safely run concurrently?
- Can already-loaded reference data be passed to the renderer?
- Does returning to the page preserve useful chrome and prior data?
- Are background responses prevented from updating an abandoned page?
- Is each cache scoped and invalidated correctly for identity and language?
- Did I accidentally put an optional asset on the initial critical path?
- Does the page still show fresh data automatically after a relevant mutation?
- Have I verified the behavior in both LTR and RTL modes?
- Does every tenant-grown collection request have a visible page/search/branch
  boundary, and does the API receive its limit and offset?
- Am I fetching only selected relationship IDs rather than all possible values?

If any answer is uncertain, the implementation is not ready for completion.

## 12. Implemented optimization inventory

The following optimizations are present as of 26 September 2026. This section
is implementation traceability; the earlier sections remain the normative
contract for future work.

| Area | Implemented behavior | Primary implementation |
| --- | --- | --- |
| English catalogue | Parse and validate once per frontend process with `lru_cache` | `frontend/webui/i18n_catalogue.py` |
| Inspector key encoding | Encode each immutable contextual key once | `frontend/webui/i18n_catalogue.py` |
| Bootstrap payload | Return locale metadata without duplicating the full English catalogue | `backend/services/api/localization.py` |
| Catalogue client cache | Reuse session messages by language and revision; retain fallback keys and ETag | `frontend/webui/app.py` |
| HTTP revalidation | Send `If-None-Match` and handle `304 Not Modified` without downloading or reparsing messages | `frontend/webui/api_client.py` and `backend/services/api/localization.py` |
| Catalogue transport | Cache deterministic gzip bytes by language revision and negotiate with `Accept-Encoding` | `backend/services/api/localization.py` |
| Reload behavior | Reload only for effective-language or document-direction changes, not a revision-only update | `frontend/webui/app.py` |
| Preference invalidation | Clear context, messages, fallback keys, and ETag as one unit | `frontend/webui/app.py` |
| Initial critical path | Defer Inspector, PDF viewer, and decorative login assets | `frontend/webui/app.py` |
| Dashboard duplicate request | Obtain favourites from the dashboard summary rather than requesting them immediately beforehand | `frontend/webui/app.py` |
| Dashboard return navigation | Render cached page-session summary immediately and refresh in the background | `frontend/webui/app.py` |
| Dashboard refresh | Preserve visible content and show loading state on the Refresh control | `frontend/webui/app.py` |
| Abandoned refresh | Decline updates when the page client, dashboard container, or current resource is no longer valid | `frontend/webui/app.py` |
| Entity landing requests | Load favourites and recent activity concurrently | `frontend/webui/app.py` |
| Recent-resource decoration | Resolve only relationship IDs present in the 50-row activity result and query effective closure narrowly | `frontend/webui/app.py` |
| Organization-unit decoration | Resolve the current page's direct relationships and required ancestor chains only | `frontend/webui/app.py` |
| Concurrent duplicate reads | Coalesce identical in-flight `GET`/`HEAD` operations per page client and return isolated response copies | `frontend/webui/api_client.py` |
| Classification path | Reuse one path response for ancestors and retention provenance; clear on selection/refresh | `frontend/webui/classification_workspace.py` |
| Reference data | Cache identity-scoped stable lists, invalidate on mutation/token change, and revalidate after 30 seconds | `frontend/webui/api_client.py` |
| Reference ETags | Emit deterministic private ETags for schemes, org units, roles, profiles, privileges, profile references, and security levels | `backend/services/api/http_cache.py` and resource routes |
| Abandoned navigation | Cancel unfinished reads when another page transition is committed | `frontend/webui/app.py` and `frontend/webui/api_client.py` |
| Secondary entity sections | Render Records/Aggregations chrome immediately, load personal sections in the background, and update only their retained host | `frontend/webui/app.py` |
| Complete review lists | Request 25 visible rows plus one look-ahead row and navigate with server-side offsets | `frontend/webui/app.py` and `frontend/webui/api_client.py` |
| Hold people selectors | Search active person accounts on the server in 25-row pages while preserving selected identities | `frontend/webui/app.py` and `frontend/webui/api_client.py` |
| Relationship selectors | Use reusable debounced 25-row server searches and preserve selected options | `frontend/webui/app.py` and `frontend/webui/api_client.py` |
| Administration listings | Send filter, status, account type, sort, limit, and offset to server search endpoints | `frontend/webui/app.py` |
| Membership editor | Page assignments and fetch only counterpart rows present on the current assignment page | `frontend/webui/app.py` |
| Aggregation details | Page child aggregations and contained records; walk only the selected ancestor chain | `frontend/webui/app.py` |
| Effective closure | Use one narrow authorized endpoint instead of downloading the aggregation hierarchy | `backend/services/api/main.py` and `frontend/webui/api_client.py` |
| Advanced Search relationships | Load relationship choices on demand through server type-ahead rather than preloading 100 rows per field | `frontend/webui/app.py` |
| Classification branches | Load 25 children with look-ahead and explicit Load more controls | `frontend/webui/app.py` |
| Classification schemes | Page administrative scheme lists and use bounded type-ahead for published-scheme selectors | `frontend/webui/app.py` and `backend/services/api/browse.py` |
| Organization browser | Page roots and each unit/role branch independently, including exact-path reveal across unloaded pages | `frontend/webui/app.py` and `backend/services/api/browse.py` |
| Hold assignment | Search and page holds instead of opening the dialog with 100 rows | `frontend/webui/app.py` |
| Inspector DOM cost | Disconnect the MutationObserver while unauthorized or disabled; scan and reconnect only when enabled | `frontend/webui/static/translation-inspector.js` |

### 12.1 Measured evidence

The process-local English catalogue validation was measured at approximately
10.5 ms for the initial load in the development environment. After caching,
10,000 message renders completed in approximately 9.3 ms with one cache miss
and 10,000 hits. These numbers are diagnostic measurements, not production
service-level objectives; their significance is the removal of repeated full
catalogue parsing from each label render.

The checked-in Arabic artifact measured 439,053 bytes uncompressed and 72,030
bytes with deterministic gzip level 5, an 83.6% reduction. Actual endpoint
size varies with the published catalogue revision.

The complete frontend regression set covering the API client, localization,
page architecture, entity UI, and the bounded-collection static contract
completed with 245 passing tests after these optimizations. The complete API
and database suite completed with 329 passing tests against a disposable
PostgreSQL database, including schema and migration validation and the
operation-policy inventory. Python compilation and `git diff --check` also
passed. Database-backed tests remain subject to the disposable-database rule
in `AGENTS.md`.

### 12.2 Required regression coverage

Do not remove or weaken tests proving:

- one manifest load followed by cache hits;
- cached Inspector key encoding;
- catalogue ETag transmission and `304` handling;
- no full reload for revision-only catalogue changes;
- optional authenticated assets remain outside the critical path;
- dashboard cached rendering followed by background refresh;
- absence of a duplicate favourites request before dashboard summary;
- concurrent independent entity landing requests;
- reuse of already-loaded organization-unit reference rows; and
- coalescing of identical concurrent reads without coalescing mutations;
- one classification-path request per selection/reveal transition; and
- cached reference reuse, ETag revalidation, mutation invalidation, and result isolation;
- cancellation of abandoned reads;
- deferred personal-section loading with a targeted host update; and
- bounded server-side pagination for complete Dashboard review lists; and
- paginated server search for Hold owner and contributor selectors; and
- absence of unbounded `api.list` calls for tenant-grown resources;
- relationship search request limits and offsets;
- narrow effective-closure lookup rather than hierarchy download; and
- no Inspector MutationObserver connection while inspection is disabled.

### Relationship description matching

Record and aggregation relationship selectors include `description` in their
case-insensitive server-side type-ahead match, alongside each control's existing
search fields. They retain the same bounded page size, filters, authorization,
primary sort field, and selected-value behavior. Other entity selectors retain
their configured search fields. No additional cache or catalogue text is added.
`frontend/webui/tests/test_relationship_search.py` covers English and Arabic
queries, both resource types, duplicate-field avoidance, unchanged other entity
fields, and preservation of pagination and filters.

Classification workspace cache, paging, RTL evidence and regression results are
recorded in [the redesign verification report](classification-workspace-redesign-verification.md).

### Collection guidance localization during background refreshes

Aggregations/Records personal-section refreshes call `render_table` from a
background task without an inherited NiceGUI slot. Enter the owning
`table_container` before resolving translated guidance and subtitle text, as
well as before rendering its children. Resolving text before entering the slot
can read an empty task catalogue and overwrite Arabic labels with English.
The client catalogue remains the existing per-page, language-scoped registry;
no extra catalogue parsing, cache or API request is introduced.

`test_collection_refresh_localization.py` runs the real callback with an empty
inherited catalogue for Aggregations and Records in both English and Arabic.
All four cases pass. A database-free browser preview confirmed repeated refresh
and navigation retain the expected English and Arabic labels. No translation
keys or wording changed. The owned preview process and tab were shut down.

### Dashboard identity isolation and batched summaries (4 November 2026)

The visual snapshot remains private to one browser-page client. Its key is the
login-session revision, user ID, effective language, working timezone, known
global privileges and effective role IDs. Sign-out, session rejection and every
successful login clear the snapshot and advance the revision, including another
login as the same account. Unknown/legacy keys are never rendered. No snapshot
is written to browser storage or shared server state.

Each dashboard view captures its principal, key and a unique view token.
Responses are checked before writing any cache, application configuration,
favourites or UI. An identity/language change, disconnected/deleted client,
deleted container, navigation or newer dashboard view invalidates the response.
The API client also advances a token generation, cancels pending reads and
discards late responses (including 401s) from previous credentials. Old 401s
must not sign out the new identity. Review and favourite callbacks use the same
session/view guards. Sign-out removes protected content before remote logout
finishes. Failed same-user background refreshes retain the visible snapshot and
restore the Refresh control; fresh-load failures show an error without another
identity's data.

The summary authorizes record/aggregation sets with request-local materialized
CTEs equivalent to the canonical view predicates within the dashboard live
scope. Effective roles, global
privileges, maximum clearance, governance clearance, organizational activity,
contextual managers/file administrators and ACL sources are calculated as sets.
Inherited aggregation ACL sources propagate down the hierarchy once, respecting
custom child defaults and inheritance breaks. Direct/inherited record ACLs join
those sets without calling a permission function per record. These visible sets
feed counts, medium/vital/held totals, ownership, storage, true root counts,
review counts/previews, favourites, relationship redaction and recent activity.
This is SQL statement reuse, not a cross-request cache. All dashboard resource
outputs exclude disposed statuses 10, 11 and 12, including for governance users.
Status 13 remains in scope subject to normal authorization. Overview
authorization must be explicit: the
search views' names alone do not confer visibility.

Materialize nonterminal resources (`disposition_status NOT IN (10,11,12)`)
before computing ACL targets and hold propagation. Historical metadata is retained,
so filtering only the final authorized output permits historical data to enlarge
the working graph. Include only nonterminal aggregations/records and the
ancestors/containers they actually need. Preserve a required ancestor even if
it has terminal status: pruning must remain equivalent to canonical inherited
ACL and hold rules. Do not add unrelated disposed branches to that graph.

Active hold assignments propagate down the hierarchy once with a distinct
recursive set. Direct record holds are calculated once. This must remain
equivalent to the canonical effective-hold functions, including half-open
validity windows, inherited holds across ACL inheritance breaks, overlapping
holds and holds without resource-state preservation. Avoid restoring an
ancestry walk per dashboard record.

Classification activity and inherited retention-rule existence also propagate
as sets, rather than walking each terminal's ancestors. Differential tests must
compare batched authorization/classification results with the canonical functions
when either implementation changes. No dashboard SQL may restore per-resource
permission, role-effectiveness, contextual-ACL or hold-ancestry function calls.
Iterating a small set of grouped unit totals to localize response labels is
permitted; fetching or authorizing resources in a Python loop is not.

Recent activity retains the same latest-event grouping, per-group cap,
visibility checks and ordering, but resolves only bounded candidate IDs against
the reused authorized sets. Index `event_history_dashboard_resource_latest_idx`
matches resource-activity filters and ordering; the partial covering
`event_history_dashboard_content_views_idx` handles personal component-view
activity by actor/time without unrelated history. Include both component ID
and operation so the content-view query is covered completely. The covering
`digital_components_dashboard_storage_idx` on record ID including byte size
allows storage totals without loading component metadata. All three indexes
are in the standalone canonical schema; existing installations apply migrations
`098_dashboard_resource_activity_index.sql`,
`099_dashboard_content_activity_index.sql` and
`100_dashboard_component_storage_index.sql` separately.
Migration `101_dashboard_live_resource_indexes.sql` adds the narrow partial
indexes `aggregations_dashboard_live_idx` and `records_dashboard_live_idx` on
ID. Its original status-10-only predicate is replaced by
`102_dashboard_nonterminal_resource_indexes.sql` with
`disposition_status NOT IN (10,11,12)`, matching the live-resource queries.
The final definitions are also in the canonical schema. They allow history-heavy
tables to read the nonterminal subset without
filtering the entire metadata heap. The planner can still choose a cheaper
sequential scan when most rows are live. Avoid covering these indexes with
large titles or other unbounded metadata. Exact counts still process the
authorized live subset; personal audit-history work is a separate cost.
No setting or translation catalogue changes are needed. Restart the API/WebUI
after deploying the code; local stack startup does not apply migrations.

The dashboard-specific design, index inventory, maintenance rules and regression
map are in the [dashboard guide](dashboard.md#optimization-and-maintenance).
Regression matrix, query plans, benchmark scope and cleanup evidence are in
[dashboard isolation and performance verification](verification/dashboard-isolation-performance.md).
