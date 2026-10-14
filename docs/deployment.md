# Linux deployment

ERMS has four independently managed components: the FastAPI backend, the
NiceGUI web UI, the REST-only text indexer, and PostgreSQL. Use separate systemd units for the API, UI, and indexer
for an ongoing Linux deployment. They can run on the same server or on separate
servers; PostgreSQL can also be hosted independently.

## Deployment options

| Arrangement | Frontend API address | Load balancing |
| --- | --- | --- |
| One API and one UI on one server | `http://127.0.0.1:8000` | A reverse proxy can serve the UI over HTTPS; affinity is unnecessary with one UI instance. |
| One API and one UI on separate servers | Reachable private API address | No affinity is needed with one instance of each service. |
| Multiple API instances | API load balancer address | API requests can go to any instance sharing the same PostgreSQL database. |
| Multiple UI instances | API address or API load balancer address | The UI load balancer needs session affinity and WebSocket support; shared user storage is optional for preserving login data across instances. |

The request path is browser → UI proxy/load balancer → NiceGUI → API address or
load balancer → FastAPI → PostgreSQL. `WEBUI_API_URL` is used by the NiceGUI
server, so it must be reachable from the UI servers. Browsers do not need
direct access to the API for the current UI.

## Sessions and load balancing

The application-settings foundation requires migration 050 for existing
databases. SMTP passwords remain encrypted database settings; all API instances
for one database share the deployment-owned `APPLICATION_SETTINGS_ENCRYPTION_KEY`.
Production shell/service environment takes precedence over local `.env`.
See [upgrade and key configuration](application-settings-upgrade.md) before
deploying this change. Settings edits need no restart; deployment key changes do.

### API instances

API authentication uses an opaque token whose hash is stored in PostgreSQL's
`login_sessions` table. Cookies carry tokens for cookie-authenticated clients;
NiceGUI forwards its token as a Bearer credential. A cookie does not imply
server affinity: any API instance can validate the token against the shared
database. See [authentication](authentication.md).

Uploaded digital-component content is also stored in PostgreSQL, rather than
on an API server's local disk. See [content storage](content-storage.md).
Keep all API instances on the same application version and compatible
configuration, pointing to the same logical PostgreSQL database. They need
neither the same physical application server nor sticky sessions.

`API_WORKERS` can increase the number of API worker processes on one server.
Each worker has its own database connection pool. Budget database connections
across all instances, including one dedicated messaging listener per worker,
as calculated in [PostgreSQL connection sizing](#postgresql-connection-sizing).
Increasing API capacity does not increase database capacity automatically.

### NiceGUI instances

NiceGUI maintains live page state and connections within an instance. When
running multiple UI instances, configure the frontend load balancer to keep
each browser's HTTP requests, Socket.IO traffic, and WebSocket connection or
reconnections on the same UI instance. A load-balancer affinity cookie is
separate from the API's authentication cookie. Enable WebSocket upgrades and
timeouts suitable for long-lived connections.

Affinity is still required when user storage is shared. Shared storage makes
the stored API token available across instances; it does not move live page
objects or callback state between them. A failed or restarted UI instance can
require users to reload the page. See
[NiceGUI's multi-instance guidance](https://github.com/zauberzeug/nicegui/discussions/1539).

The current frontend uses `app.storage.user` and defaults to local NiceGUI
storage. You can run multiple UI instances with affinity and local storage,
accepting that users routed to another instance may need to sign in again.
Redis is optional and does not preserve live pages. To enable shared storage:

1. Install NiceGUI's Redis extra into each frontend environment. The current
   `frontend/webui/requirements.txt` declares plain NiceGUI without this extra:

   ```bash
   frontend/webui/.venv/bin/python -m pip install 'nicegui[redis]>=2.24,<3'
   ```

   Include the extra in your deployment dependency installation so rebuilt
   environments retain Redis support.
2. Set `NICEGUI_REDIS_URL` on every UI instance to the same reachable Redis
   service. Configure it before starting the UI process.
3. Set the same strong `WEBUI_STORAGE_SECRET` on every UI instance, and use
   consistent Redis key prefixes. Separate environments must use separate
   Redis databases or `NICEGUI_REDIS_KEY_PREFIX` values.
4. Configure frontend affinity and verify login, navigation, reconnects, and
   behavior when a UI instance restarts.

Redis is additional infrastructure for shared UI storage; PostgreSQL remains
the authority for API authentication and records. See the
[NiceGUI Redis deployment example](https://github.com/zauberzeug/nicegui/tree/main/examples/redis_storage).

## PostgreSQL connection sizing

Wathiq does not reserve a PostgreSQL connection for each signed-in user or
browser tab. Each connected page has a long-lived messaging stream to the API
(through NiceGUI in the current WebUI). Every API worker shares **one dedicated
PostgreSQL `LISTEN` connection** across its connected messaging clients. This
connection is outside the application's request pool, but still counts toward
PostgreSQL's connection limit.

| Connection | Allocation | Uses the application database pool? |
| --- | --- | --- |
| Messaging WebSocket or SSE stream to the API | One per connected page/tab | No; this is an HTTP/WebSocket connection, not a database connection |
| PostgreSQL messaging listener | One per API worker process | No; dedicated, long-lived, autocommit connection |
| Ordinary queries, including catch-up, unread counts and stream authentication checks | Borrowed briefly as needed | Yes |

### Calculate the database connection budget

For instances with the same pool configuration:

```text
W = peak total API worker processes across all instances
P = DB_POOL_MAX_SIZE per worker
O = peak database connections from other services, jobs and tools
H = operational headroom for temporary or unexpected connections
R = superuser_reserved_connections + reserved_connections

API connection budget = W × (P + 1)
Required max_connections ≥ W × (P + 1) + O + H + R
```

For identical instances, `W = instance count × API_WORKERS`. Include autoscaling
peaks and old/new worker overlap during rolling restarts. If pool sizes differ,
sum `(pool maximum + 1 listener)` for every worker instead of using `W × (P + 1)`.
Count other database clients across the entire PostgreSQL server, including
other databases, direct maintenance jobs, migration tools and monitoring.
NiceGUI and REST-only text indexers do not add their own direct database pools;
their API requests consume the API pools already counted above.

The repository defaults are `DB_POOL_MIN_SIZE=1` and `DB_POOL_MAX_SIZE=10`.
Budget against the maximum, even though pools can use fewer connections when
idle. At these defaults, each API worker can use up to **11 database connections**.

Worked example (illustrative allocation, not a measured user-capacity guarantee):

| Allocation | Connections |
| --- | ---: |
| Two API instances, two workers each: `4 × (10 + 1)` | 44 |
| Other services, jobs and administrative tools | 10 |
| Operational headroom | 20 |
| Superuser reserve of 3; other reserved connections of 0 | 3 |
| **Required total** | **77** |

`max_connections=100` accommodates this example. If a rolling deployment
temporarily doubles those four API workers, the same calculation becomes
`8 × 11 + 10 + 20 + 3 = 121`; a limit of 100 would no longer cover that peak.

### PostgreSQL settings and inspection

For the first example, the PostgreSQL configuration would be:

```conf
max_connections = 100
superuser_reserved_connections = 3
reserved_connections = 0
```

Use the values calculated for the actual deployment. Reserved slots are part
of `max_connections`, not additional slots above it; exclude them from ordinary
application capacity. These settings require a PostgreSQL restart. Increasing
`max_connections` increases resource allocation, including shared memory, so
raising it alone is not a performance improvement. See the official
[PostgreSQL connection settings](https://www.postgresql.org/docs/18/runtime-config-connection.html).

Read the active settings and current connection usage with:

```sql
SELECT name, setting, pending_restart
FROM pg_settings
WHERE name IN ('max_connections', 'superuser_reserved_connections',
               'reserved_connections')
ORDER BY name;

SELECT datname, usename, application_name, state, count(*) AS connections
FROM pg_stat_activity
WHERE backend_type = 'client backend'
GROUP BY datname, usename, application_name, state
ORDER BY datname, usename, application_name, state;
```

Listener connections appear with `application_name='wathiq-message-listener'`.
An idle listener is expected: it waits outside a transaction. Observe usage
during peak traffic and deployment overlap, not only while the application is
idle. Also check any connection limits imposed on the application database role,
the database itself, or a database proxy; those limits can reject connections
before the server-wide maximum is reached.

If the request DSN uses a transaction-pooling proxy, set
`MESSAGING_LISTENER_DATABASE_URL` to a direct or session-pooled connection to
the **same database**. The listener must retain its PostgreSQL session. With
a transaction pooler, budget its actual maximum PostgreSQL server connections
instead of counting each application-to-pooler connection as a server connection;
then add the dedicated listeners and other direct clients separately.

### Relate the budget to concurrent users

There is no fixed conversion from concurrent users to PostgreSQL connections.
Users may have several tabs/devices, and active users generate different query
loads. Estimate peak connected pages and peak activity, load-test representative
workflows, and choose worker and pool counts from observed latency, pool waits,
database CPU, memory and I/O. Then apply the connection-budget formula above.

`MESSAGING_STREAM_MAX_CONNECTIONS=1000` is the default client-stream ceiling
**per API worker**, and `MESSAGING_STREAM_MAX_USER_CONNECTIONS=20` is the default
per-user ceiling per worker. Neither value allocates PostgreSQL connections or
proves that the deployment can support that many active clients. Allow for
uneven stream distribution and reconnection bursts. Stream heartbeats also make
short authentication queries through the existing request pool.

The API proxy must support WebSocket upgrades, disable SSE response buffering,
and allow idle timeouts longer than `MESSAGING_STREAM_HEARTBEAT_SECONDS`
(default 15 seconds). These transport settings are separate from PostgreSQL's
connection budget. See the [Phase 3 implementation report](notifications-and-messaging-phase-3.md)
for the event contract, queue limits, recovery behavior and verification evidence.

## Server preparation and configuration

Install Python 3.11 or newer with virtual-environment support and PostgreSQL 18
or newer, and place the
application at an absolute path such as `/opt/erms`. Create a dedicated Linux
account such as `erms` to run it. The launchers create their virtual environments
and install dependencies on first use, so the service account needs write
access to their environment directories. A UI server also needs write access
to its local NiceGUI storage directory when Redis is not used.

Initialize a new database or migrate an existing one using the
[database instructions](../database/README.md). Apply migrations once per
shared database, rather than from every API instance, and bootstrap the first
administrator as documented there. Prepare dependencies before enabling
services so routine restarts do not depend on package downloads. Pin the
resolved dependency versions in your deployment process for consistent replicas.

Full-text search requires the unmodified built-in `pg_catalog.simple`,
`pg_catalog.english`, and `pg_catalog.arabic` configurations. Schema creation
and migration 010 check these prerequisites atomically; do not create substitute
catalogue objects or change the database-wide default text-search configuration.

The indexer has no `DATABASE_URL`. Install Java 17+, Tesseract with `eng` and
`ara`, Poppler's `pdfinfo` and `pdftoppm`, and the complete official Apache
Tika 4.0.0 app binary distribution.
Verify the distribution archive against
`backend/services/text_indexer/TIKA-DISTRIBUTION.sha512`, extract it to a
root-owned/read-only directory, and set `TEXT_INDEXER_TIKA_HOME` to the
directory containing `tika-app-4.0.0.jar` and the adjacent `lib/` directory.
The startup self-test requires `lib/tika-pipes-fork-parser-4.0.0.jar`; neither
the Homebrew thin CLI package nor a Tika Docker service is supported.

For a developer checkout, run
`backend/services/text_indexer/install-tika.sh`. The installer downloads the
official pinned distribution, verifies the committed archive and application
JAR SHA-512 values, checks for the fork-parser JAR, and installs it under the
Git-ignored `vendor/tika/` directory.

The complete macOS contributor procedure, including installation of Java,
Tesseract with Arabic and English data, Poppler, LibreOffice and PostgreSQL 18,
is in [Full-text search local setup](full-text-search-local-setup.md).

Use the generated `.env.example.api` as the API-host environment template and
`.env.example.text_indexer` as the independently deployable indexer's template.
`TEXT_INDEXER_PROCESS_COUNT` belongs in the full-stack `.env`/`.env.example`
and the text-indexer templates because the supervisor consumes it. It is
intentionally absent from `.env.example.api`: an API-only process neither
starts nor configures text-indexer child processes.
The latter intentionally contains no database credential. Supply
`TEXT_INDEXER_API_KEY` through a protected environment file or deployment
secret store; never commit its value or place it on a command line.

Run `run-text-indexer.sh --self-test` during deployment, then supervise
`run-text-indexer.sh`. Production `TEXT_INDEXER_API_URL` must be HTTPS; plain
HTTP is rejected except on loopback. Deny outbound network access for the
indexer/extractor service at the OS or workload boundary while permitting only
the API destination and Tika's internal loopback Pipes IPC. Apply 2-CPU, 1-GiB
memory, 1-GiB private temporary-storage, and process-count controls in the
service manager in addition to the worker's timeout, JVM heap, file-size, and
Linux address-space limits. Supply the display-once API key through protected
secret storage, never an environment file in source control or command line.

For local development only, `TEXT_INDEXER_ENABLED=true` makes
`run-local-stack.sh` provision a least-privilege service account/key against a
loopback database, store it mode `0600` under `.secrets/`, start and monitor the
worker, and fail the stack if it exits. The default is explicitly disabled and
reported. Readiness is withheld until the worker has registered through a real
claim request. The managed database image is PostgreSQL 18.

Use separate environment files, for example `/etc/erms/api.env` and
`/etc/erms/webui.env`. Restrict access because they contain credentials. These
files use literal `KEY=value` assignments, not shell commands or references
to other variables. Process environment values override the repository's
`.env` defaults.

### Maintaining environment templates

Every new environment variable must be added to `.env.example` and every
applicable service template in the same change, even when the code has a default.
Renamed or removed variables and changed defaults require the same review.
Use the consuming service to select templates:

| Consumer | Relevant templates |
| --- | --- |
| API | `backend/services/api/deploy/api.env.example` and generated `.env.example.api` |
| WebUI | `frontend/webui/deploy/webui.env.example` |
| Text indexer | `.env.example.text_indexer` and `backend/services/text_indexer/deploy/text-indexer.env.example` |

Document purpose, default or required value, service ownership and restart
requirements. Preserve intentional deployment differences such as bindings and
secure cookies; use safe placeholders instead of private credentials or local
machine paths. Do not put unrelated service settings into service-only files.
Describe template changes and manual configuration or restart requirements in
the change handoff and deployment upgrade instructions. The agent-facing version
of this requirement is in `AGENTS.md` under Environment variable templates.

`backend/services/api/deploy/api.env.example` is the authoritative API-only
example. `.env.example.api` is generated from it; do not edit the generated copy.
After adding or changing an API environment setting, update the authoritative
example and run `python3 tools/sync_api_env_template.py`. The API environment
CI check runs `python3 tools/sync_api_env_template.py --check` and fails on drift.
Also document the setting and update the full-stack `.env.example` when relevant;
local binding, credentials and rollout values may intentionally differ.
Templates are never loaded automatically. The supplied systemd services load
`/etc/erms/api.env`; install the authoritative example there and configure it for
the server. Process values take precedence over repository-root `.env` fallbacks.
New template values do not update an existing server environment automatically.

For local development, `run-local-stack.sh` now runs
`tools/reconcile_local_env.py` under the launcher lock before loading `.env`.
It appends missing active assignments and their associated comments from
`.env.example`, reports added variable names, and preserves every existing
assignment (including empty values), credential and file permission. Repeated
runs add nothing once synchronized. Template values never replace explicitly
exported process values. Example credentials and unresolved placeholders are
reported rather than copied. A missing `WEBUI_STORAGE_SECRET` receives a new
random secret; a newly created `.env` has mode 0600. Optional commented settings
remain manual. You can run `python3 tools/reconcile_local_env.py` independently;
it does not start services. This startup hook applies to the local stack, not
the production systemd service.


Example `/etc/erms/api.env`:

```ini
DATABASE_URL=postgresql://erms:REPLACE_PASSWORD@db.internal:5432/erms
API_HOST=127.0.0.1
API_PORT=8000
API_WORKERS=1
API_RELOAD=false
DB_POOL_MIN_SIZE=1
DB_POOL_MAX_SIZE=10
CONTENT_STORAGE_BACKEND=postgresql
AUTH_COOKIE_SECURE=true
```

`DEFAULT_ROOT_AGGREGATION_MEDIUM` accepts `digital`, `physical`, or `mixed` and
defaults root-aggregation forms without preventing the creator from choosing a
different value. `REVIEW_WARNING_WINDOW_DAYS` controls how far ahead review
warnings appear and defaults to 30 days. `DASHBOARD_REVIEW_PREVIEW_LIMIT`
is a positive database setting, initially five items per review category.
These general defaults and UI limits are edited in Administration → Settings;
old shell/`.env` assignments have no effect after cutover. Runtime edits propagate
within 30 seconds without restarting services. Before starting an upgraded API
or local stack, follow [the reviewed per-database migration/readiness procedure](application-settings-upgrade.md).
Invalid canonical database values prevent API readiness.

Run segmented-content cleanup from exactly one dedicated worker or deployment
scheduler, not from every API worker:

```bash
python -m backend.services.api.content_cleanup --watch
```

Administrators can inspect or execute cleanup manually with `--dry-run` and
`--batch-size`. The worker uses a PostgreSQL advisory lock to prevent overlap.
The central [operational tools catalogue](operations.md) lists this worker,
login-session cleanup, authentication administration, database
operations, their scheduling alternatives, and required safeguards. Deployment
runbooks must use that catalogue rather than discovering operational commands
from feature documentation.

Run full-text indexing and retained text-indexer credential cleanup from one
API-owned supervised worker per logical database:

```bash
python -m backend.services.api.text_indexing_maintenance cleanup --watch
```

For the packaged Linux deployment, install
`backend/services/api/deploy/erms-text-indexing-maintenance.service` alongside
the API service. On macOS local development, `run-local-stack.sh` starts and
monitors the same worker automatically. A platform scheduler may instead run
the one-shot `cleanup` command hourly; do not use both scheduling models.

Example `/etc/erms/webui.env`:

```ini
DATABASE_DISPLAY_NAME="Production Database"
DATABASE_DISPLAY_NAME_AR="قاعدة بيانات الإنتاج"
WEBUI_API_URL=http://127.0.0.1:8000
WEBUI_HOST=127.0.0.1
WEBUI_PORT=8080
WEBUI_RELOAD=false
WEBUI_STORAGE_SECRET=REPLACE_WITH_A_STRONG_RANDOM_SECRET
```

## Full-text search staged rollout and rollback

Keep service orchestration separate from the two database rollout settings:
`CONTENT_INDEXING_SCHEDULING_ENABLED` and `FULL_TEXT_SEARCH_ENABLED`.
New databases start with both false. Header visibility follows the API setting.

1. Apply required schema upgrades through 051 and review/apply the 34-key legacy
   settings migration before API/worker startup. Confirm `/health` reports both
   flags false for a fresh installation. See [application-settings-upgrade.md](application-settings-upgrade.md).
2. Install and verify
   `backend/services/text_indexer/deploy/erms-text-indexer.service`, then set
   `TEXT_INDEXER_PROCESS_COUNT` to the worker-process capacity of the host.
   Inject its key as `TEXT_INDEXER_API_KEY` through the deployment's protected
   environment file or secret store, and enforce an egress firewall that
   permits only the HTTPS API peer and loopback Pipes IPC. Run
   `run-text-indexer.sh --self-test`, then enable the unit.
3. Enable `CONTENT_INDEXING_SCHEDULING_ENABLED` in Administration Settings;
   changes converge within 30 seconds without restart. Confirm new available content creates a queued job.
4. Run bounded backfill passes from **Administration → Text Indexers → Health**
   with **Queue backfill batch**, or with
   `backend/services/api/.venv/bin/python -m backend.services.api.text_indexing_maintenance reconcile --batch-size 500`.
   Repeat until a pass reports zero examined and zero queued.
   Observe `metrics` between passes; pause when database, API, extractor, or
   storage load approaches the environment's alert limits.
5. Run `quality-gate examples/samples/docs/phase2-worker-benchmark-results.json`
   and `readiness`. Do not expose search until both exit successfully and the
   operational observation window has no sustained queue growth, lease loss,
   cleanup failure, or unexpected extraction error trend.
6. Enable `FULL_TEXT_SEARCH_ENABLED` in Administration Settings and smoke-test
   the governed API and header, which share that value.

Rollback is non-destructive: disable the shared full-text search setting, then
automatic scheduling, and stop the indexer. Pending/stale status remains
truthful and source content is untouched. Do not drop index tables; their
removal requires a separately reviewed later migration. Re-enable in the same
staged order after remediation.

These loopback bindings suit a proxy on the same server. For separate servers
or remote load balancers, bind the appropriate service to its private interface
or `0.0.0.0`, and restrict ingress to the required peers. Set `WEBUI_API_URL`
to the private API endpoint or API load balancer. Use HTTPS for public browser
access, protect cross-server traffic appropriately, and keep PostgreSQL and
Redis accessible only to the services that need them. `AUTH_COOKIE_SECURE=true`
is required for HTTPS API cookie clients; HTTP cookie clients cannot send a
Secure cookie. NiceGUI uses Bearer authentication for its API requests.

## Separate systemd services

Ready-to-install Ubuntu unit files and environment templates are provided
within each service’s `deploy` directory:

- [`erms-api.service`](../backend/services/api/deploy/erms-api.service)
- [`erms-session-cleanup.service`](../backend/services/api/deploy/erms-session-cleanup.service)
- [`erms-webui.service`](../frontend/webui/deploy/erms-webui.service)
- [`erms-text-indexer.service`](../backend/services/text_indexer/deploy/erms-text-indexer.service)
- [`api.env.example`](../backend/services/api/deploy/api.env.example)
- [`webui.env.example`](../frontend/webui/deploy/webui.env.example)
- [`text-indexer.env.example`](../backend/services/text_indexer/deploy/text-indexer.env.example)

They assume `/opt/erms`, a service account and group named `erms`, and
`/etc/erms/api.env` and `/etc/erms/webui.env`. Adapt paths and account names
if needed. The repository currently has one backend application service:
FastAPI. Authentication, search, and document conversion run within it and do
not need separate units. PostgreSQL uses its independently managed service.

On Ubuntu with Python 3.11 or newer available, prepare the service account:

```bash
sudo apt update
sudo apt install python3 python3-venv curl
sudo useradd --system --user-group --home-dir /var/lib/erms --create-home --shell /usr/sbin/nologin erms
sudo install -d -m 0750 -o root -g erms /etc/erms
```

Create the account only if it does not already exist. Ubuntu releases whose
system Python is older than 3.11 need a supported newer Python; set
`PYTHON_BOOTSTRAP` in the environment files to its executable. For Office
file previews, install LibreOffice on the API server as described in
[document viewing](document-viewing.md).

Copy the application to `/opt/erms` before proceeding. Create writable runtime
directories while keeping the deployed source owned by the deploying account:

```bash
sudo install -d -m 0750 -o erms -g erms /opt/erms/backend/services/api/.venv
sudo install -d -m 0750 -o erms -g erms /opt/erms/frontend/webui/.venv /opt/erms/.nicegui
```

Ensure `erms` can read the source and execute the launchers. Build virtual
environments on the Ubuntu server; do not copy macOS virtual environments.
From the deployed project root, install the units and initial configuration:

```bash
sudo install -m 0644 backend/services/api/deploy/erms-api.service /etc/systemd/system/erms-api.service
sudo install -m 0644 backend/services/api/deploy/erms-session-cleanup.service /etc/systemd/system/erms-session-cleanup.service
sudo install -m 0644 frontend/webui/deploy/erms-webui.service /etc/systemd/system/erms-webui.service
sudo install -m 0644 backend/services/text_indexer/deploy/erms-text-indexer.service /etc/systemd/system/erms-text-indexer.service
sudo install -m 0600 backend/services/api/deploy/api.env.example /etc/erms/api.env
sudo install -m 0600 frontend/webui/deploy/webui.env.example /etc/erms/webui.env
sudo install -m 0600 backend/services/text_indexer/deploy/text-indexer.env.example /etc/erms/text-indexer.env
sudoedit /etc/erms/api.env /etc/erms/webui.env /etc/erms/text-indexer.env
```

Copy environment templates only during initial setup; copying them again would
replace existing configuration. Replace the database password and UI storage
secret before starting. On separate servers, install only the relevant unit,
environment file, and runtime directories. Set the API binding and
`WEBUI_API_URL` for cross-server connectivity as described above.

The units use the existing launchers, which prepare dependencies on first
startup. They send logs to the journal, restart after failures, stop child
processes as a group, and use a restrictive file-creation mask. You can verify
the installed unit configuration on Ubuntu before enabling it:

```bash
sudo systemd-analyze verify /etc/systemd/system/erms-api.service /etc/systemd/system/erms-session-cleanup.service /etc/systemd/system/erms-webui.service
sudo systemd-analyze verify /etc/systemd/system/erms-text-indexer.service
```

### Text-indexer process-pool examples

The deployment runs one `erms-text-indexer.service`. Its Python supervisor
starts `TEXT_INDEXER_PROCESS_COUNT` child workers. Every child claims exactly
one job at a time; the configured `TEXT_INDEXER_WORKER_ID` is only the base for
unique runtime IDs. A failed child slot is restarted without stopping healthy
siblings. systemd supervises the complete service and restarts it if the
supervisor itself exits.

#### Account and credential boundaries

The complete relationship is:

```text
Text Indexers service account
└── active API key stored by one deployed text-indexer service
    └── supervisor process
        ├── child worker 1 — one claimed job
        └── child worker 2 — one claimed job
```

Create the non-interactive account in **Administration → Text Indexers**. The
dedicated workflow assigns the protected built-in Text Indexer Service role
and displays the initial API key once. Store that key in the deployment's
protected secret store or `/etc/erms/text-indexer.env`; never commit it. Child
workers in the service pool share that account and key, while the supervisor
gives every child a distinct runtime worker ID. Do not create a service account
or API key for every child process.

The recommended production boundary is one Text Indexers account and key per
server or independently operated worker pool. Server A should normally use
account/key A and Server B account/key B. That permits independent audit
attribution, rotation, revocation, suspension, and incident containment. A
trusted identically managed group may share an account only when that shared
security boundary is intentional.

Suspending an account disables every service and child using it. Revoking a
key disables deployments using that key, without affecting a separate account
or another active key. To rotate safely, generate a new key, deploy it to the
intended service, restart and verify its workers in **Text Indexers → Health**,
and only then revoke the old key.

**Small production host — one concurrent extraction:**

```ini
TEXT_INDEXER_WORKER_ID=records-indexer-a
TEXT_INDEXER_PROCESS_COUNT=1
TEXT_INDEXER_CLAIM_BATCH_SIZE=1
```

This produces one runtime worker, for example
`records-indexer-a-1842-1`, and processes one document at a time.

**Normal production host — two concurrent extractions:**

```ini
TEXT_INDEXER_WORKER_ID=records-indexer-a
TEXT_INDEXER_PROCESS_COUNT=2
TEXT_INDEXER_CLAIM_BATCH_SIZE=1
```

This produces two child workers, such as `records-indexer-a-1842-1` and
`records-indexer-a-1842-2`. They share the service account/API key but lease
different jobs and run separate Tika/OCR subprocesses.

**Two production hosts:** configure a distinct base on each host, for example
`records-indexer-a` and `records-indexer-b`. With a process count of `2` on
each host, the deployment can extract four documents concurrently. All four
workers claim through the API; none connects directly to PostgreSQL. Normally,
provision a separate Text Indexers account/API key for each host, while the two
child workers on the same host share that host's credential.

After editing `/etc/erms/text-indexer.env`, start or restart the single service:

```bash
sudo systemctl enable --now erms-text-indexer.service
sudo systemctl restart erms-text-indexer.service
sudo systemctl status erms-text-indexer.service
```

The service unit's CPU, memory and task limits apply to the whole process pool.
Size those aggregate limits for the configured count. Keep
`TEXT_INDEXER_CLAIM_BATCH_SIZE=1`; concurrency comes from child processes, not
claim prefetching or threads.

The UI unit intentionally has no `Requires=erms-api.service`: systemd
dependencies refer to local units and cannot represent a remote API. Network
ordering also does not guarantee that PostgreSQL or the API is ready. Start
and verify PostgreSQL, then the API, then the UI. Manage PostgreSQL through its
own service, container supervisor, or managed database platform.

On a combined server, activate the units with:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now erms-api.service erms-session-cleanup.service erms-webui.service
sudo systemctl status erms-api.service erms-session-cleanup.service erms-webui.service
```

On separate servers, use only the service installed on that server. Logs and
routine lifecycle operations are independent:

```bash
sudo journalctl -u erms-api.service -f
sudo journalctl -u erms-webui.service -f
sudo systemctl restart erms-api.service
sudo systemctl restart erms-webui.service
```

Enabled services start at boot and run independently of SSH. Automatic restart
is subject to systemd start-rate limits; inspect the journal if repeated
failures leave a service stopped. See the
[systemd service reference](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml).

## Verification and upgrades

Check the API's `/health` endpoint and the UI's `/` endpoint using addresses
reachable from the checking host. For a local deployment:

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8080/
```

These probes confirm HTTP availability; also verify login and an authenticated
API operation to exercise database-backed authentication. With multiple API
instances, verify that the same token works against each instance. With
multiple UI instances, verify the load balancer retains affinity through page
load and reconnects, and, if enabled, that shared user storage works across instances.

Back up PostgreSQL, including uploaded content, before schema upgrades. Deploy
compatible application versions and apply required migrations once. Drain
instances before planned restarts where possible. API requests in progress
can be interrupted, and UI restarts lose live page state even when Redis
preserves user storage. Database availability and capacity remain shared
dependencies; adding application instances alone does not provide database
high availability. Test restoring backups as part of operations.

## Temporary SSH deployment with tmux

For testing, `tmux` can keep the existing local stack running after SSH logout.
Install it using the Linux server's package manager, then run from the project
root:

```bash
tmux new -s erms
./run-local-stack.sh
```

Once ready, press **Ctrl+B**, release both keys, then press **D** to detach.
You can log out and later return with `tmux attach -t erms`. Reattach and press
**Ctrl+C** to stop services started by the script. The script preserves the
database volume and leaves services it reused running. See
[tmux's documentation](https://github.com/tmux/tmux/wiki/Getting-Started).

The local stack permits only one launcher per checkout. A second invocation
exits before starting services or rotating the local indexer's credentials.
Stop the first launcher with Ctrl+C before restarting. The process lock lives
in `.cache/local-stack.lock`; do not delete it while services are running.
The operating system releases the lock when its holders exit, so the file
remaining on disk does not indicate a running stack.

During temporary API connection failures, timeouts, or HTTP 429/502/503/504
responses, indexer job polling retries with exponential backoff capped at
30 seconds. It logs the outage once and logs recovery when polling succeeds.
Authentication failures still stop the pool; they require fixing the service
credentials. One-shot execution still fails immediately on a failed claim.

The local stack requires Python 3, Docker, `curl`, and `psql`. Its automatic database
container uses development credentials and is intended for local testing.
`tmux` provides neither automatic boot startup nor restart after a crash. For
an ongoing deployment, use the separate systemd services and independently
managed database described above.

## System notification readiness and administration

For upgrades through messaging Phase 4, apply migrations 033, 034, 035, and
`036_notification_administration_guards.sql` in order. Initialize an empty
database from `database/schema.sql` alone, then run the separate catalogue seeds
as described in [the seed guide](../database/seeds/README.md).

Each API process explicitly assembles its code-owned notification definitions.
Startup compares these contracts with the database without repairing or seeding
them. `/health` returns HTTP 503 with `notification_readiness_failed` and safe
producer/error identifiers if a required contract or its active configuration
is missing or incompatible. Do not route traffic to an instance failing this
readiness check. Optional contract discrepancies are reported in the
`notifications.issues` health field; attempting to emit through an invalid
contract still fails closed.

Notification Administration, under Messages, requires
`messaging.notifications.administer`. This is independent of message exchange,
Monitor, and audit privileges. Before enabling a feature that requires a
notification, its owner must supply the approved Python definition and matching
feature seed/upgrade contract, and an administrator must save and activate a
valid configuration with published templates for every enabled language,
including English. A new language can be registered while disabled; add and
publish its templates in new active configuration versions before enabling it.
Language enablement and configuration activation are guarded against concurrent
changes in PostgreSQL.

This subsystem revision does not invent any business notification triggers.
The production definition list is initially empty. A separately approved
feature explicitly adds its definition to `application_definitions()` in
`backend/services/api/messaging/notification_registry.py`. The disposable
browser preview producer in `tools/notification_preview.py` is test tooling and
is never assembled by the production application.

Feature code calls `emit_system_notification` in
`backend/services/api/messaging/notifications.py` inside its already-open
repeatable-read or serializable PostgreSQL transaction. Pass the producer code,
a stable domain event ID, only declared typed context values, and optional
triggering-user provenance. Commit the domain change and notification together;
propagate errors so the complete transaction rolls back. Retry the complete
transaction on serialization failure, preserving the same domain event ID.
Never call the service after committing the domain change. There is no
production REST send endpoint or background notification retry queue.

Static audiences and registered dynamic resolvers are expanded under the same
transaction. Resource builders receive validated feature-owned presentation
configuration; every returned link is checked by ordinary resource policy at
the baseline security level. With no triggering user, that check uses the
backend principal already established by the caller's transaction. Registration
as a producer grants no resource permissions.

Controlled test sends use a separate endpoint and explicit individual
recipients. The defaults are 10 recipients per test, 20 test sends per
administrator per hour, and 30-day expiry; environment settings use the
`MESSAGING_TEST_` names in `.env.example`. Test history records safe provenance
and outcomes, without template context or message content. Test messages retain
an immutable test flag and prominent labels throughout the mailbox and live
notification paths. Retention execution and operational metrics are supplied by the Phase 5
lifecycle worker described below.

The connection-sizing calculation above is unchanged: producers reuse their
caller's transaction; test sends use a normal pooled transaction; there remains
one dedicated LISTEN connection per API process, not per recipient or browser.

## Message capture, retention, and Monitor

Upgrade an existing Phase 4 database with
`database/migrations/037_messaging_retention.sql`. New databases continue to use
`database/schema.sql` alone. Restart API and WebUI processes after upgrading and
synchronize the new catalogue definitions and generated Arabic drafts through the
normal seed/review workflow. No persistent database is upgraded by the test runner.

For colleagues syncing existing forks, see the
[message capture validator upgrade note](upgrades/message-capture-validator.md)
and [local tooling guide](local-tooling.md). The local stack performs a
non-blocking availability check; production capture still validates every PDF.

Capture uses WeasyPrint 68.1 from the API requirements and the bundled Changa
fonts in `backend/services/api/messaging/pdf_assets`. Install WeasyPrint's native
Pango/font dependencies for the deployment platform. Install the independent
veraPDF CLI and its supported Java runtime, then set `MESSAGING_PDF_VALIDATOR` to
its executable path (the default is `verapdf` on PATH). Acceptance verification
uses veraPDF 1.30.2. Both PDF/A-2u and PDF/UA-1 checks must pass for every generated
message and provenance component. Missing tools, timeouts, and validation errors
block capture; they never commit a partial record. The renderer cannot fetch
network resources or local files other than its bundled fonts.

Each rendering/validation subprocess is bounded to 60 seconds, within a total
600-second capture-generation budget. The WebUI allows 660 seconds for the
capture request. Configure the reverse proxy's request timeout to accommodate
this operation. The normal application transaction pool supplies capture and
cleanup connections. These operations do not create additional LISTEN connections;
the PostgreSQL connection-sizing calculation above still applies. Long captures
occupy a transaction while validating source permissions and preserving a
consistent amendment history, so include expected simultaneous captures in pool
load testing.

The default capture limits are 100 earlier messages plus the selected message and
provenance, and 50 MiB for all PDFs combined. The `MESSAGING_CAPTURE_` settings in
`.env.example` change those limits after restart; raising them requires capacity
and request-duration tests. A record capture requires the ordinary record-create
and destination permissions. An ordinary message draft is never a record capture.

Every API process runs a lifecycle worker. It snapshots gateway health every 15
seconds and starts cleanup at `MESSAGING_CLEANUP_INTERVAL_SECONDS` (default 3600).
`MESSAGING_CLEANUP_BATCH_SIZE` (default 500) bounds candidate pages, draft cleanup,
and transfer of group identifiers. Each connected group is locked and purged in
one transaction, even when larger than a page; a page boundary never splits a
conversation. Lock waits are limited to 3 seconds and cleanup statements to 60
seconds. A failed group is retained for a subsequent sweep. Large groups can
therefore remain stored until a complete attempt succeeds. Inspect the Monitor's
eligible-group age, group size, failures, and durations when tuning cleanup.

Envelope expiry and its restoration-period length are stored at send time.
Changing retention settings does not move existing expiry/restoration deadlines.
A manual deletion establishes its own deadline at that deletion. Restoring before
expiry returns the entry to normal expiry; restoring after expiry never extends
the original deadline. Capture drafts, unsent message drafts, and records do not
keep a messaging group alive. Captured records and immutable capture provenance
survive source purge under ordinary records-management rules.

Messages → Monitor requires `messaging.monitor`. It reports counters and mean
processing durations, current mailbox/expiry totals, bounded gateway and producer
pages, and cleanup-group observations from completed discovery attempts. Group
observations are not an instantaneous census before the worker has scanned them.
Gateway snapshots older than 45 seconds or a disconnected listener raise an
alert. Operational failures remain flagged until a successful corresponding
operation resolves the failure; counters remain cumulative. Metrics contain no
message bodies, subjects, recipient labels, or protected resource metadata.
Audit navigation additionally requires `audit.view`.

For deployment verification, use `tools/verify_messaging_pdf.py` with veraPDF,
Poppler (`pdffonts`, `pdftotext`, `pdftoppm`), and the API environment. It produces
English/Arabic PDFs, renderings, font reports, and independent validation reports.
Run database acceptance tests only through `tools/test_messaging.py`, which creates
fresh disposable databases, verifies upgrade parity, and drops them afterwards.

### Built-in legal-hold notifications

For an existing deployment, apply
`database/migrations/038_legal_hold_notifications.sql` after migration 037,
followed by `database/migrations/039_localized_notification_producer_names.sql`.
New databases use `database/schema.sql` alone. Then run the separate catalogue
seed `database/seeds/hold-notification-producers.sql` against that deployment.
The API explicitly registers the matching two Python contracts at startup.

After reviewing the supplied English/Arabic templates in
`database/seeds/hold-notification-templates.json`, install and activate their
initial configuration with an existing active person account that has
`messaging.notifications.administer`:

```sh
backend/services/api/.venv/bin/python -m tools.configure_hold_notifications \
  --administrator-id ADMINISTRATOR_ID \
  --operational-owner 'Legal governance'
```

The command records administrator-attributed configuration history with source
`seeding`. It does not replace existing configurations or pending administrator
drafts. It fails atomically if any enabled language lacks a valid template;
additional languages require reviewed templates through Notification
Administration. Subsequent changes, disabling, previews, and test sends use
that existing administration screen. No production database was configured as
part of development verification.

Until configured, these optional producers are dormant. Once enabled,
assignment-delivery failure rolls back the associated hold responsibility
change. Reminder failures roll back the reminder checkpoint and are retried by
the API lifecycle worker. The worker checks roughly once a minute, in bounded
100-hold batches, using one ordinary pooled connection and a transaction-scoped
leader lock across instances. There is no new dedicated PostgreSQL connection.
Hold/end-date checkpoints prevent repeats even after the original notification
has been purged. No reminders are sent after expiry.

### Localized notification producer names

Apply migration `039_localized_notification_producer_names.sql` after 038, then
rerun `database/seeds/hold-notification-producers.sql`. The seed fills missing
English and Arabic names without replacing existing names, localized wording,
active configuration versions, or message templates. Fresh databases use the
canonical schema and then the separate seed. No UI translation catalogue keys
are added for these entity names. Restart the API and WebUI to load the updated
name projection and rendering code if automatic reload is disabled.


### Message resource picker (migration 040)

After migrations through 039, apply
`database/migrations/040_message_record_aggregation_links.sql` before deploying
the record/aggregation-only message-link model. Fresh databases use the canonical
schema alone. The migration removes direct digital-component message/draft link
targets; message-to-record capture components remain unchanged. It fails safely
if unexpected component message links exist rather than deleting them.

Synchronize the nine new `resource_picker.*` catalogue definitions and Arabic
drafts through the normal seed/review workflow, then restart API and WebUI.
The Add resources dialog uses the existing record/aggregation search API and
full-text index, including its rollout setting, authorization, and indexing
freshness. No new search service or database connection pool is required.
See [implementation and verification](messaging-resource-picker.md).

For the local checkout on this machine, veraPDF 1.30.2 is installed in
`.local-tools/verapdf` (ignored by Git). The root `.env` sets
`MESSAGING_PDF_VALIDATOR` to its absolute executable path. Restart the API
after changing this setting. A temporary test installation under `/tmp` does
not configure the application, and should not be used as a permanent path.

### Legal-hold information governors (migration 043)

Apply `043_legal_hold_notification_governors.sql` before deploying producer
contract version 2. Approaching-expiry notifications include all active people with
effective information-governance roles. Apply migration 044 with the revised
assignment producer (contract version 3): assignment notifications go only to
the newly assigned person. Existing configuration versions and
wording are preserved; review existing personal-assignment wording before using
it for governors. New configurations use the neutral English/Arabic templates
in `database/seeds/hold-notification-templates.json`. New databases still use the
canonical schema alone, followed by the separate latest producer seed.

Content and authentication policies are now database-owned Administration Settings.
Review and apply the extended legacy migration before deploying Phase 5 code; see
[application-settings-upgrade.md](application-settings-upgrade.md). Cleanup CLI
arguments are per-invocation overrides; omit them to follow database defaults.

Search/indexing policy and Audit Trail result caps are database-owned. Configure
them through Administration Settings after bootstrap; environment assignments no
longer enable scheduling or search. The removed WebUI flag has no authority.
See [application-settings-upgrade.md](application-settings-upgrade.md) for the
reviewed 34-key upgrade and [configuration-authority-inventory.json](configuration-authority-inventory.json)
for ownership, defaults, consumers, service templates and restart requirements.
