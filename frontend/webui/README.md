# ERMS NiceGUI frontend

The frontend is an independently deployable NiceGUI service. It communicates
with the FastAPI service over HTTP and does not access PostgreSQL directly.

## Layout and RTL troubleshooting

Start with standard NiceGUI components and documented layout/direction
configuration. Exhaust applicable NiceGUI solutions before using lower-level
Quasar primitives or custom CSS. For tricky problems, inspect the rendered UI
in the in-app browser before changing layout code; do not use speculative CSS
changes as a diagnostic method. Follow the required workflow in
[Design Language section 19.1](../../docs/webui-design-language.md#191-nicegui-first-layout-and-rtl-troubleshooting),
including documenting necessary fallbacks and verifying both LTR and RTL.

## Run locally

Start the API first, then run:

```bash
./run-webui.sh
```

Open `http://localhost:8080`. The launcher creates a dedicated virtual
environment under `frontend/webui/.venv` and installs only the frontend's
dependencies.

Message **Save record** capture also needs local veraPDF/Java tooling. Follow
[the tooling guide](../../docs/local-tooling.md) and
[the upgrade note](../../docs/upgrades/message-capture-validator.md).
The stack launcher warns if this optional feature prerequisite is missing.

To start the complete local stack instead, run:

```bash
./run-local-stack.sh
```

This reuses PostgreSQL, the API, or the UI when they are already running. If
PostgreSQL is unavailable at the default local URL, it creates a Docker
container initialized from `database/schema.sql`. Its data is retained in the
`erms-postgres-local-data` Docker volume between runs. Ctrl-C stops only the
processes and database container started by the script.

Configuration is read from the process environment, with `.env` as local
defaults:

- `DATABASE_DISPLAY_NAME` is the required default-language database name shown
  in the application footer
- `DATABASE_DISPLAY_NAME_<LANGUAGE>` optionally supplies a localized name using
  the uppercase base language tag, such as `DATABASE_DISPLAY_NAME_AR`; a blank
  or absent language-specific value falls back to `DATABASE_DISPLAY_NAME`
- `WEBUI_API_URL` defaults to `http://127.0.0.1:8000`
- `WEBUI_HOST` defaults to `0.0.0.0`
- `WEBUI_PORT` defaults to `8080`
- `WEBUI_RELOAD` defaults to `false`
- `WEBUI_STORAGE_SECRET` encrypts per-user authentication storage and must be
  changed outside local development
General defaults and preview/page limits are now database-owned under
Administration → Settings, not WebUI environment settings. Initial defaults are
`DEFAULT_WORKING_TIMEZONE=Asia/Dubai`, `DEFAULT_ROOT_AGGREGATION_MEDIUM=mixed`,
`REVIEW_WARNING_WINDOW_DAYS=30`, favourite/review previews `5`, recent items `4`,
recent days `30`, recent classification selections `4`, and user sessions `5`.
The API supplies current page/bootstrap values; changes propagate within 30
seconds without restart. Recent classifications retain server paging (20-row
windows), and user-detail sessions retain bounded server pages (at most 50).
See [the reviewed per-database migration procedure](../../docs/application-settings-upgrade.md)
before starting upgraded services. Private legacy entries are never removed or
imported automatically; content/authentication/search cutovers follow later.

Dashboard recent activity is attributed through the immutable audit event's
`actor_user_id`. Created and updated cards display the matching event's
`occurred_at` timestamp, rather than always displaying the entity creation date.
The Dashboard also presents authorized attention signals, records by
organizational unit and medium, review urgency, and a top-five organizational-unit
digital-storage ranking as additive charts while retaining the existing
overview cards, holdings rows, and review-reminder lists. Remaining storage
units are combined into an Other units summary. The charts use the consolidated
Dashboard summary and do not introduce separate data requests or authorization
scopes.
Dashboard and classification limits must be positive integers and take effect when the web UI process
is restarted. See [`../../docs/dashboard.md`](../../docs/dashboard.md) for the
Dashboard's system-wide and user-specific data semantics.

Real environment variables override `.env` values.

## Linux deployment

See the [deployment guide](../../docs/deployment.md) for one-server and
split-server deployments, separate API and UI systemd services, load balancing,
NiceGUI session affinity and shared storage, and temporary SSH deployment with
`tmux`.

## Current scope

The interface provides the shared application shell, local authentication,
login-session administration, role-aware user menu, list views, search-first
aggregation and record views, add/edit dialogs, optimistic concurrency
handling, and record-scoped digital-component upload/listing. Classification
schemes and classifications share a full-width, independently paged hierarchy
with dedicated scheme and classification details pages,
contextual root/child creation, classification search, and effective-rule
provenance. See [`../../docs/classification-schemes.md`](../../docs/classification-schemes.md)
for its behavior. The Aggregations page also provides a cursor-paginated,
lazy-loaded browser from published classification schemes through root and
child aggregations to records, with concise details shown beside the tree. See
[`../../docs/aggregation-classification-browser.md`](../../docs/aggregation-classification-browser.md).
Records open on a dedicated details page containing record metadata, actions,
and the complete Digital Components interface without an additional dialog.
See [`../../docs/record-details.md`](../../docs/record-details.md).
The Organization Structure section includes a lazy organization-unit, role, and
user browser with persistent tree state, cross-entity search, browse-enabled
lookup controls, and a dedicated user details view. See
[`../../docs/organization-structure-browser.md`](../../docs/organization-structure-browser.md).
Authenticated pages share a persistent navigation-history breadcrumb with
bounded overflow, page-state restoration, and detail-page Back integration.
See [`../../docs/navigation-breadcrumbs.md`](../../docs/navigation-breadcrumbs.md).
The normative design, component reuse, layout, interaction, accessibility,
responsive, RTL, testing, and review rules for new WebUI work are documented in
[`../../docs/webui-design-language.md`](../../docs/webui-design-language.md).
It incorporates and supersedes the deprecated
[`../../docs/ui-visual-design.md`](../../docs/ui-visual-design.md), which is
retained only as historical context and must not be used as a design authority.
The classification details page exposes deactivate,
reactivate, and delete actions. Delete is enabled only for an unused leaf in an
active, unpublished scheme; otherwise inline guidance explains the blocking
condition. Direct, ancestor-derived, and scheme-derived inactivity are visibly
distinguished. See
[`../../docs/authentication.md`](../../docs/authentication.md) for authentication
operations and security behavior. Digital components can be downloaded in their
original format or viewed through the bundled, self-hosted PDF.js viewer. See
[`../../docs/document-viewing.md`](../../docs/document-viewing.md). Authorization
remains a later subsystem. Direct and inherited closure behavior is described in
[`../../docs/aggregation-closure.md`](../../docs/aggregation-closure.md).

The classification redesign's field/action parity, RTL findings, catalogue
changes and validation evidence are recorded in
[`../../docs/classification-workspace-redesign-verification.md`](../../docs/classification-workspace-redesign-verification.md).
Its NiceGUI interaction tests run separately from the source/unit suite because
the NiceGUI user plugin resets global UI state:

```sh
DATABASE_URL='' frontend/webui/.venv/bin/python -m pytest frontend/webui/interaction/tests -q -o asyncio_mode=auto
```

These interaction tests use a fake API and never connect to a database.
