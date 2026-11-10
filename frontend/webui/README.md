# ERMS NiceGUI frontend

The frontend is an independently deployable NiceGUI service. It communicates
with the FastAPI service over HTTP and does not access PostgreSQL directly.

## Shared infrastructure boundary

Shared shell construction now lives in `application_shell.py`. Its header,
footer, drawer and content builders run inside the current NiceGUI page context
and return explicit handles to the existing controls. They do not receive
application state, create routes or perform API requests. `app.py` retains its
existing control aliases and callback wiring during the incremental migration.
See the [Phase 5 verification report](../../docs/webui-refactor-phase5-verification.md)
for completed local checks and the accepted, non-reproduced Edge loading observation.

`navigation_controller.py` owns the per-client trail, persistence calls, registration,
breadcrumb navigation, Back and existing discard guards. `navigation_data.py`
contains the pure trail helpers. Feature snapshots, dispatch, localized breadcrumb
rendering and shell updates remain explicit host callbacks during migration.
There are no entity routes or new browser-history entries.

`session_context.py` supplies the existing per-page API client, identity and current
locale, and coordinates sign-in, sign-out and unauthorized cleanup. It adds no
cache. Its small identity mapping is a temporary host adapter; features should
receive a principal reader rather than mutate it. Private feature-cache cleanup,
password/localization bootstrap and the separate live-message connection retain
their existing owners and order. Never share a context/controller between clients.

These modules do not import `app.py` or receive its large state dictionary.
Remaining host callbacks will move with their feature owners; they are not a
second implementation of the extracted infrastructure.

## Application Settings pilot boundary

`application_settings_controller.py` owns Settings authorization, its four entry
paths, the selected category and each view's lifetime. Create one controller per
NiceGUI client, inside `index`; never share it across sessions. Its `open`,
`restore`, `open_from_drawer`, `open_from_event` and `open_from_custody` methods
preserve the existing navigation behavior and saved `settings_category` format.

`application_settings.py` continues to own the unchanged forms, selectors,
dialogs and API interactions. `app.py` supplies the existing API client, identity
and direction readers, navigation guard, relationship binding and two small
shell callbacks. The feature does not receive the shared application/navigation
dictionaries or import the entry point. Navigation still owns read cancellation;
the feature's identity/view checks reject abandoned callbacks. Accepted writes
retain the renderer's existing behavior.

See the [Phase 3 verification report](../../docs/webui-refactor-phase3-verification.md)
before extending this pattern to other features. The
[Phase 4 review](../../docs/webui-refactor-phase4-review.md) defines the shared
infrastructure gates and incremental migration order.

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

## Refactor regression checks

Use the isolated runner for both suites. It clears database configuration,
disables dotenv loading, blocks Python socket and PostgreSQL connections before
test collection, and runs each suite in a separate process and storage folder.
Install test dependencies from `frontend/webui/requirements-test.txt`.

```sh
frontend/webui/.venv/bin/python tools/run_webui_tests.py --repeat 2
```

The assembled checks exercise the real root page and real REST API using the
NiceGUI simulator. The owning runner creates a uniquely named disposable
PostgreSQL database, initializes the canonical schema and separate seeds, starts
its own API, and drops the database on success, failure, or interruption:

```sh
backend/services/api/.venv/bin/python tools/run_webui_integration.py
```

Use `--preview` for real-browser checks. It prints the loopback URL and keeps its
disposable API and WebUI alive until Ctrl-C. Synthetic sign-in identities are
`admin@test.invalid`, `officer@test.invalid`, and `viewer@test.invalid`; their
fixture password is `Temporary-Test-Password-123!`. Never reuse it elsewhere.
The viewer has no assigned role. The preview uses the existing richer Settings
fixture; the assembled suite uses `tools/seed_webui_regression.py`.

For repeatable browser baselines, add `--fixed-fixture` to `--preview`. This
uses the smaller synthetic fixture with record dates fixed to 1 January 2026,
28 schemes, paged classification branches, UTC display, enabled search and
the checked-in Arabic wording published only in that disposable database.
The fixture version is recorded in `lifecycle.json`. Audit/session timestamps
still reflect the real run; avoid treating those changing timestamps as fixed
pixel baselines. Match the browser, viewport, zoom, language and navigation
trail when comparing captures.

For the automated browser journey, install
`frontend/webui/requirements-browser-test.txt` in a separate virtual environment
at `.runtime/webui-browser-venv`, then run:

```sh
backend/services/api/.venv/bin/python tools/run_webui_integration.py --browser chrome
```

Repeat with `edge`, `firefox` and `safari`. These use the installed browser
products on macOS and separate WebDriver sessions. Selenium may download the
matching driver; browser downloads are disabled. Safari requires the user's
approval to temporarily enable remote automation; restore its previous setting
after testing. The runner automatically selects the fixed disposable fixture.
API request metadata, browser errors, screenshots and individual checks are
recorded in the output directory. Test-only instrumentation injects controlled
delays and errors; the email busy-state test intercepts the send before it can
reach SMTP. It does not establish successful email delivery.

To include successful delivery, start the repository MailDev helper and add
`--maildev`. The runner checks that managed instance, trusts its local certificate
only in its test processes, and configures SMTP only in the disposable database:

```sh
./run-maildev.py up --owner webui-browser-check
backend/services/api/.venv/bin/python tools/run_webui_integration.py --browser chrome --maildev
./run-maildev.py down --owner webui-browser-check
```

The owner check leaves a previously running MailDev instance alone. Follow
`docs/local-tooling.md` for port or Node runtime options. No outside email is
sent. `--browser-scope navigation` is available for diagnosing the navigation
subset; its results do not satisfy the full browser gate.

For the supplemental keyboard/focus baseline, use `--browser chrome
--browser-scope keyboard` or `--browser edge --browser-scope keyboard`, without
`--maildev`. This records native Tab/Shift-Tab, Enter, arrows and Escape journeys
in English and Arabic, including the active control and unchanged screenshots
for human review. It sends no email. It supplements the full workflow run and
does not introduce new focus behavior or constitute an accessibility redesign.

The supplemental `--browser-scope shell` measures header, drawer, breadcrumbs,
account controls and narrow-screen behavior in English and Arabic. The
`--browser-scope session` checks independent clients, reconnect, old-identity
responses, sign-out and the existing administrator-issued temporary-password
recovery flow. Both use disposable databases and supplement the full gate.
The current refactor acceptance scope is Chrome and Edge only; Firefox, Safari
and CI remain deferred by the user.

Both commands save logs and XML under `.runtime/`; `--output` selects a new
evidence directory and refuses to overwrite an existing one. The API runner
also records request counts/timings and database cleanup in `lifecycle.json`.
Check `database_dropped: true` after every database-backed run. Do not run
`frontend/webui/assembled/tests` directly against a running development stack.
The simulator does not execute browser JavaScript or prove visual/history parity.

The [Phase 2 report](../../docs/webui-refactor-phase2-verification.md) records
completed checks, browser limits, and the remaining gate before extraction.
The [browser checklist](interaction/browser/webui_refactor.md) covers the four
required browser products. The prepared CI workflow runs the isolated suites
twice, runner safety checks, and the assembled suite against an ephemeral
PostgreSQL service. Its execution remains unverified while changes stay local.

Full-text header visibility now follows the API's saved FULL_TEXT_SEARCH_ENABLED
value in bootstrap/page configuration. WEBUI_FULL_TEXT_SEARCH_ENABLED is removed.
No WebUI feature cache or extra bootstrap/widget settings request is introduced.
See docs/application-settings-upgrade.md before deploying this cutover.
