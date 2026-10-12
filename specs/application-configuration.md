# Application Configuration — Specification

**Status:** Approved
**Approved:** 12 October 2026
**Project:** ERMS
**Prepared:** 2 October 2026
**Revision:** 1.0 — approved specification

## 1. Purpose

This specification separates ERMS configuration into two non-overlapping
categories:

1. **deployment configuration**, which remains in process environment variables
   or a local `.env` file; and
2. **application configuration**, which is stored only in PostgreSQL and may be
   changed through an authorized system-administration interface.

The separation makes PostgreSQL the single source of truth for shared
application behavior. It deliberately excludes copying settings between the
database and `.env`, exporting database settings to `.env`, PostgreSQL
notifications, a message broker, and distributed cache invalidation.

This document is the approved contract for application configuration.

## 2. Governing rules

1. Every production setting listed in this specification belongs to exactly one
   configuration ownership category: deployment-managed or database-managed.
   This is separate from the UI grouping category defined in section 7.
2. A database-managed setting must not also be read from the process environment
   or `.env`, including as a fallback.
3. A deployment setting must not be copied into the application-settings table
   or exposed for editing in the administration UI.
4. Database-managed defaults are defined by the canonical schema and application
   setting registry. They do not come from `.env` at startup.
5. Creating or migrating a database inserts any missing application-setting rows
   without changing existing rows. Concurrent API startup performs no setting
   seeding.
6. All API instances connected to one logical database use the settings stored
   in that database.
7. Database-managed settings are never written back to `.env`.
8. Test-only variables, command-line-tool variables, standard operating-system
   variables, and virtual-environment bootstrap variables are outside this
   specification.

## 3. Configuration categories

### 3.1 Deployment configuration

Deployment configuration describes how a particular process starts, connects,
binds, stores process-local state, or consumes machine resources. It is known
before the API can read PostgreSQL and normally changes through deployment
operations rather than the ERMS administration UI.

Deployment settings are read once at process startup. Changing one requires the
affected process to restart unless the owning runtime already documents
different behavior.

### 3.2 Database-managed application configuration

Application configuration describes shared product behavior for one logical
ERMS database. PostgreSQL is its only source of truth. Authorized changes take
effect without restarting API or WebUI instances, subject to the short cache
expiry in section 6.

The API owns reads, validation, updates, and audit. The WebUI must obtain these
values through the API; it must not retain equivalent environment settings.
The separately deployed text indexer has no database connection and therefore
keeps all of its process and extraction settings as deployment configuration.

## 4. Exact deployment-setting inventory

The following settings remain environment/`.env` settings.

### 4.1 FastAPI and PostgreSQL connectivity

| Setting | Current default or requirement | Reason |
| --- | --- | --- |
| `DATABASE_URL` | Required | Required before application configuration can be read; contains database location and credentials |
| `API_HOST` | `0.0.0.0` | Per-process network binding |
| `API_PORT` | `8000` | Per-process network binding |
| `API_WORKERS` | `1` | Per-instance process capacity |
| `API_RELOAD` | `false` | Development/process-launch behavior |
| `DB_POOL_MIN_SIZE` | `1` | Per-process database capacity |
| `DB_POOL_MAX_SIZE` | `10` | Per-process database capacity |
| `DB_POOL_TIMEOUT` | `10` seconds | Per-process connection-pool behavior |
| `WATHIQ_APPLICATION_REVISION` | Packaged Git revision when required | Build/deployment identity |

### 4.2 WebUI process and session infrastructure

| Setting | Current default or requirement | Reason |
| --- | --- | --- |
| `DATABASE_DISPLAY_NAME` | Required | Default-language deployment identity displayed by the WebUI |
| `DATABASE_DISPLAY_NAME_<LANGUAGE>` | Optional; falls back to `DATABASE_DISPLAY_NAME` | Localized deployment identity using the uppercase base language tag, for example `DATABASE_DISPLAY_NAME_AR` |
| `WEBUI_API_URL` | `http://127.0.0.1:8000` | Address used to reach the API or its load balancer |
| `WEBUI_HOST` | `0.0.0.0` | Per-process network binding |
| `WEBUI_PORT` | `8080` | Per-process network binding |
| `WEBUI_RELOAD` | `false` | Development/process-launch behavior |
| `WEBUI_STORAGE_SECRET` | Must be supplied securely outside local development | Secret used for UI user-storage protection |
| `NICEGUI_REDIS_URL` | Unset | Optional external session-storage infrastructure |
| `NICEGUI_REDIS_KEY_PREFIX` | Runtime default when Redis is used | Deployment/environment isolation |

### 4.3 Security and storage infrastructure

| Setting | Current default or requirement | Reason |
| --- | --- | --- |
| `AUTH_COOKIE_SECURE` | `false` locally; `true` in the production example | Depends on the deployment's HTTPS boundary and must not be weakened from the application UI |
| `CONTENT_STORAGE_BACKEND` | `postgresql` | Storage-provider/infrastructure selection |
| `LIBREOFFICE_BINARY` | Auto-discovered when unset | Host executable path |

### 4.4 Service orchestration controls

| Setting | Current default | Reason |
| --- | ---: | --- |
| `TEXT_INDEXER_ENABLED` | `false` | Controls whether local orchestration launches the separate service |
| `CONTENT_INDEXING_MAINTENANCE_ENABLED` | `true` | Controls whether local orchestration launches the maintenance process |

These variables control processes, not shared runtime product behavior. An
external supervisor may provide equivalent orchestration without using them.

### 4.5 Text-indexer deployment

All text-indexer settings remain deployment settings because the indexer is a
separately deployed REST client with no direct PostgreSQL access.

| Setting | Current default or requirement |
| --- | --- |
| `TEXT_INDEXER_API_URL` | Required |
| `TEXT_INDEXER_API_KEY` | Required issued `wti_` credential |
| `TEXT_INDEXER_API_KEY_FILE` | `.secrets/text-indexer-api-key` for local provisioning |
| `TEXT_INDEXER_TIKA_HOME` | Required Tika installation path |
| `TEXT_INDEXER_WORKER_ID` | Required unique deployment identity in production |
| `TEXT_INDEXER_PROCESS_COUNT` | `2` |
| `TEXT_INDEXER_CLAIM_BATCH_SIZE` | `1` |
| `TEXT_INDEXER_POLL_SECONDS` | `5` |
| `TEXT_INDEXER_HEARTBEAT_SECONDS` | `60` |
| `TEXT_INDEXER_EXTRACTION_TIMEOUT_SECONDS` | `120` |
| `TEXT_INDEXER_MAX_INPUT_BYTES` | `52428800` |
| `TEXT_INDEXER_MAX_EXTRACTED_CHARACTERS` | `5000000` |
| `TEXT_INDEXER_CHUNK_TARGET_CHARACTERS` | `16000` |
| `TEXT_INDEXER_CHUNK_MAX_CHARACTERS` | `20000` |
| `TEXT_INDEXER_MAX_PAGES` | `1000` |
| `TEXT_INDEXER_MAX_TEMP_BYTES` | `1073741824` |
| `TEXT_INDEXER_TEMP_DIR` | Operating-system temporary directory plus `wathiq-text-indexer` |
| `TEXT_INDEXER_STALE_TEMP_HOURS` | `24` |
| `TEXT_INDEXER_TEMP_SWEEP_LIMIT` | `100` |

## 5. Exact database-managed setting inventory

The following settings move out of `.env` and become rows in the database. The
table records the initial canonical default. Approval of this specification
also approves removal of the corresponding environment lookup; it does not by
itself approve a particular API or UI layout.

Sections 5.6 and 5.7 add the organization-wide settings agreed in
[Administration Settings](administration-settings.md) and the
[Destruction Process](destruction-process.md). They use this same configuration
registry and persistence boundary, not a parallel store. Their business
behavior is defined by those approved specifications. The general settings
migration and these settings share the approved implementation plan.

### 5.1 General application behavior

| Setting key | Type | Initial default | Validation |
| --- | --- | ---: | --- |
| `DEFAULT_WORKING_TIMEZONE` | string | `Asia/Dubai` | Canonical IANA timezone identifier |
| `DEFAULT_ROOT_AGGREGATION_MEDIUM` | string | `mixed` | One of `digital`, `physical`, `mixed` |
| `REVIEW_WARNING_WINDOW_DAYS` | integer | `30` | At least `0` |

### 5.2 Content storage and document viewing policy

| Setting key | Type | Initial default | Validation |
| --- | --- | ---: | --- |
| `MAX_UPLOAD_SIZE_BYTES` | integer | `52428800` | At least `1` |
| `CONTENT_SEGMENT_SIZE_BYTES` | integer | `16777216` | At least `1` and within the safe range required by the segmented-storage specification |
| `CONTENT_SEGMENT_CHECKSUMS_ENABLED` | boolean | `true` | Boolean |
| `CONTENT_UPLOAD_SESSION_TTL_SECONDS` | integer | `86400` | At least `1` |
| `CONTENT_CLEANUP_INTERVAL_SECONDS` | integer | `3600` | At least `1` |
| `DOCUMENT_CONVERSION_TIMEOUT_SECONDS` | integer | `60` | At least `1` |
| `MAX_RENDITION_SIZE_BYTES` | integer | `104857600` | At least `1` |

### 5.3 Authentication and session policy

| Setting key | Type | Initial default | Validation |
| --- | --- | ---: | --- |
| `AUTH_SESSION_IDLE_MINUTES` | integer | `30` | At least `1` |
| `AUTH_SESSION_ABSOLUTE_HOURS` | integer | `12` | At least `1` |
| `AUTH_LOCKOUT_ATTEMPTS` | integer | `5` | At least `1` |
| `AUTH_LOCKOUT_MINUTES` | integer | `15` | At least `1` |
| `AUTH_PASSWORD_MIN_LENGTH` | integer | `12` | At least `8` |
| `AUTH_SESSION_RETENTION_DAYS` | integer | `90` | At least `0` |
| `AUTH_SESSION_CLEANUP_INTERVAL_SECONDS` | integer | `3600` | At least `1` |
| `AUTH_SESSION_CLEANUP_BATCH_SIZE` | integer | `500` | At least `1` |

Changing `AUTH_PASSWORD_MIN_LENGTH` affects validation of newly set or changed
passwords. It does not invalidate existing password hashes. Changes to session
lifetimes apply when a session is next evaluated; they do not recreate or
extend an already expired session.

### 5.4 Dashboard, selector, and administration-page limits

| Setting key | Type | Initial default | Validation |
| --- | --- | ---: | --- |
| `DASHBOARD_FAVOURITE_ITEM_LIMIT` | integer | `5` | At least `1` |
| `DASHBOARD_RECENT_ITEM_LIMIT` | integer | `4` | At least `1` |
| `DASHBOARD_RECENT_DAYS` | integer | `30` | At least `1` |
| `DASHBOARD_REVIEW_PREVIEW_LIMIT` | integer | `5` | At least `1` |
| `CLASSIFICATION_RECENT_SELECTION_LIMIT` | integer | `4` | At least `1` |
| `USER_DETAILS_SESSION_LIMIT` | integer | `5` | At least `1` |

### 5.5 Search and indexing policy owned by the API

| Setting key | Type | Initial default | Validation |
| --- | --- | ---: | --- |
| `FULL_TEXT_SEARCH_ENABLED` | boolean | `false` | Boolean |
| `CONTENT_INDEXING_SCHEDULING_ENABLED` | boolean | `false` | Boolean |
| `CONTENT_INDEXING_HISTORY_RETENTION_DAYS` | integer | `365` | At least `0` |
| `CONTENT_INDEXING_CLEANUP_INTERVAL_SECONDS` | integer | `3600` | At least `1` |
| `CONTENT_INDEXING_CLEANUP_BATCH_SIZE` | integer | `500` | At least `1` |
| `TEXT_INDEXER_CREDENTIAL_HISTORY_RETENTION_DAYS` | integer | `365` | At least `0` |
| `TEXT_INDEXER_RATE_LIMIT_PER_MINUTE` | integer | `600` | At least `1` |
| `SEARCH_RATE_LIMIT_PER_MINUTE` | integer | `600` | At least `1` |
| `MANUAL_REINDEX_RATE_LIMIT_PER_MINUTE` | integer | `60` | At least `1` |
| `AUDIT_TRAIL_SEARCH_RESULT_LIMIT` | integer | `1000` | At least `1`; limits Audit Trail matching results and count work |

The Audit Trail limit is editable through Administration Settings and uses the
general 30-second settings cache. Changes require no restart. Each request uses
one effective limit consistently for counting, pagination, and the returned
`result_cap`. Counts detect at most limit + 1 matches, pagination cannot cross
the limit, and the WebUI uses the API's cap rather than hard-coding 1000.
Migrate existing non-default values according to section 9 and remove the
environment lookup and template entries when consumers switch to database reads.

`WEBUI_FULL_TEXT_SEARCH_ENABLED` is removed rather than migrated. The WebUI
uses the API's effective `FULL_TEXT_SEARCH_ENABLED` value so the two layers
cannot disagree.

### 5.6 Disposition settings

| Setting | Type | Initial value | Validation and effect |
| --- | --- | --- | --- |
| Destruction review route | enum | Standard | Standard or Simplified; captured on each new job and immutable thereafter |
| Classification scheme | nullable scheme reference | Unset | Existing scheme selected through bounded search/Browse |
| Uploaded evidence classification | nullable classification reference | Unset | Terminal classification belonging to the selected scheme |
| Generated reports classification | nullable classification reference | Unset | Terminal classification belonging to the selected scheme |
| External archives authority name | string | Sharjah Archives | Nonblank recipient authority name used on new request forms |
| External archives authority email address | nullable email address | Unset | Valid address when set; used for request and digital-certificate email attempts |
| Destruction reminder interval | positive calendar-month interval | 6 months | Affects future reminder schedules, not historical reminders |

Scheme and destination references are saved as a validated consistent set.
The destination selectors use two-character bounded type-ahead and paged
Browse controls as defined by Administration Settings. Missing destinations
and missing suitable open roots produce the defined task/Governance Custody
warnings; no default classification is invented. New artifact saves use current
destinations even for existing jobs, with a task warning when earlier job
artifacts used different destinations. Earlier records are not moved.

### 5.7 Shared outgoing email settings

| Setting | Type | Initial value | Validation |
| --- | --- | --- | --- |
| SMTP server hostname | nullable string | Unset | Nonblank hostname when configured |
| SMTP port | integer | 587 for STARTTLS; 465 for implicit TLS | Valid port; default follows selected security mode |
| SMTP connection security | enum | Requires configuration | STARTTLS or implicit TLS; certificate verification enabled |
| SMTP authentication enabled | boolean | Requires configuration | Determines whether authentication credentials are required |
| SMTP username | nullable string | Unset | Required when authentication is enabled |
| SMTP password | protected secret | Unset | Required when authentication is enabled; protected at rest and never returned in plaintext |
| Sender email address | nullable email address | Unset | Valid address required for sending |
| Sender display name | nullable string | Unset | Display name when configured |
| Reply-to email address | nullable email address | Unset | Valid address when set |
| Connection and send timeout | positive seconds | 30 | Positive timeout |

Incomplete configuration does not prevent application startup; it prevents
the relevant email send and produces the defined task error. No SMTP server,
credential, or sender is copied from environment variables or invented.
These settings serve both request-form and digital-certificate delivery.
All system notifications still use the existing messaging and notifications
subsystem; external document sending does not introduce a replacement for it.

## 6. Runtime reads and short-expiry cache

Each API process maintains an in-memory snapshot of the complete validated
non-secret database-managed configuration for one logical database. The
general 30-second cache below does not govern the fresh operation reads
specified in Section 6.1 or decrypted SMTP credentials.

1. The cache lifetime is **30 seconds**, measured from completion of a successful
   database load.
2. A request may use the cached snapshot until it expires.
3. The first access after expiry reloads the complete snapshot in one database
   query. A process-local lock prevents duplicate simultaneous reloads.
4. A successful administration update invalidates the updating API process's
   cache immediately. Other API processes observe the change no later than 30
   seconds after their last successful load.
5. There is no cross-process notification, polling loop, message broker, or
   shared cache.
6. The WebUI does not maintain a second authoritative settings cache. Ordinary
   page data returned by the API may include the effective values needed to
   render that page.
7. If a refresh fails, the API records the failure and may use its last fully
   validated snapshot for requests that can otherwise proceed. It must never
   construct a partial snapshot or substitute environment values. Normal
   database-dependent operations continue to follow their existing database
   failure behavior.

Thirty seconds is an upper bound on normal cross-instance propagation, not a
guarantee that all in-flight requests change behavior simultaneously. The
administration UI must state that a saved value can take up to 30 seconds to be
used by every API instance.

### 6.1 Current settings at disposition operation boundaries

Job creation reads the committed review-route setting from PostgreSQL and
saves it on the job. Each new artifact save reads the current committed scheme
and destination classifications as one consistent set. Each document-email
attempt reads current recipient and SMTP settings and records the non-secret
values used for that attempt. These operations must not use the general
30-second cache or a stale fallback to override a newer committed setting.
If the required read fails, the operation cannot proceed using old settings.

The operation retains that consistent configuration for its own execution;
changes committed afterward apply to subsequent operations, not partway through
an already captured send or save. Existing jobs keep their captured route;
previous artifacts and send attempts keep their recorded references/addresses.
SMTP secrets are resolved only server-side for sending and are not included
in public configuration responses or ordinary cached snapshots. No restart
or cross-process invalidation mechanism is needed for these fresh reads.

## 7. Registry and persistence model

The application owns a closed registry containing, for every key in section 5:

- stable key;
- explicit `category` identifying its Administration Settings UI group;
- data type;
- default value;
- validation rule;
- sensitivity classification;
- editable status (enabled for every database-managed setting); and
- administrator-facing label and description keys.

The application registry defines each setting's category explicitly, aligned
with the functional groups in section 5, including Disposition and Email. The
settings API supplies this category and its translated display label to the UI.
Categories are not inferred from setting-key prefixes and are not duplicated
as columns in `application_settings`. Administrators edit setting values;
category assignments remain application-defined. Grouped saves follow related
setting dependencies; a category does not require every setting in it to be
changed together.

Unknown keys must not be accepted or used. SMTP passwords are secret
application configuration; the remaining settings are non-secret or carry
their declared sensitivity. Passwords are protected at rest and must not be
stored as plaintext typed JSON, exposed through list/get responses, or included
in ordinary logs or history. Use a protected secret representation within the
shared configuration mechanism. The UI shows only masked/set-state information
and accepts a replacement without returning the existing password.

The canonical schema contains an `application_settings` table with one row per
registered key. At minimum, each row stores the key, typed JSON value or
protected secret representation appropriate to its sensitivity, row
version, last-update timestamp, and last-updating user. The canonical schema
seeds every key with the defaults in section 5. The upgrade migration inserts
missing rows only and never overwrites an existing value.

The database representation and application registry must agree on every key,
type, default, and validation constraint. Schema-level constraints must enforce
the invariants that can be expressed portably in PostgreSQL; the API validates
the complete proposed change before writing it.

## 8. Administration and audit

The reusable **Administration → Settings** page presents all registered
database-managed keys in section 5 as editable. None becomes read-only after
installation. Secret settings remain editable through protected replacement
inputs; editability does not permit reading saved secrets. It groups settings
by the same functional areas, shows the effective value and validation rules,
and identifies the initial default. Secret deployment configuration is neither
returned by the API nor shown in this UI.

Each control includes visible, concise, translated explanatory text covering
purpose, data type in plain language, units, permitted values or limits, default
or unset meaning, dependencies, and when changes take effect. The registry's
label and description keys support this text. Do not rely on technical key
names or tooltips alone to explain a setting.

An update:

1. requires an authenticated person with `app.settings.manage`, granted to
   the System Administrator profile;
2. requires a non-blank change reason;
3. uses the existing optimistic-concurrency pattern so one administrator cannot
   silently overwrite another administrator's edit;
4. validates all submitted values before changing any row;
5. changes the submitted settings and writes their audit evidence in one
   PostgreSQL transaction; and
6. records actor, time, reason, old/new non-secret values, and resulting row
   version in durable event history. Secret changes record that the credential
   was changed, with actor/time/version, never its plaintext, encrypted value,
   or a reversible substitute.

Related settings are saved together in one validated, atomic operation. For
example, the classification scheme and both destination classifications form
one consistent set; related SMTP settings are also saved together. Validate the
resulting set and check the expected versions before saving. A validation or
concurrency failure leaves the entire submitted group unchanged. One change
reason applies to the group, with audit evidence for each changed setting.

The privilege and System Administrator grant are agreed. No
`disposition.jobs.manage` grant or unrelated administrator privilege substitutes
for `app.settings.manage`. The Disposition and Email groups use the agreed
layout and controls in Administration Settings. SMTP secret input is allowed;
deployment secrets such as database credentials remain excluded.

## 9. Rollout and compatibility

There is no automatic import from `.env`.

For a new database, `database/schema.sql` creates the settings with the defaults
in section 5. For an existing database, the migration inserts missing defaults
without overwriting existing database values. Existing non-default environment
values for migrated settings must be preserved through an explicit, reviewed
migration using the governed administration path before switching their consumers
to database-only reads. They must not silently revert to defaults. Validate the
values and save related settings together. If a value is invalid or conflicts
with an existing database value, resolve that discrepancy explicitly before
switching the affected settings; do not silently choose or discard either value.
Verify the resulting database values before removing the migrated variables
from the deployment environment. Reconcile and remove the obsolete
`WEBUI_FULL_TEXT_SEARCH_ENABLED` flag against the API-owned full-text setting;
it must not become a second database setting. Startup never automatically
imports environment values or overwrites saved settings.

The checked-in environment examples must contain only section 4 settings after
the feature is implemented. Documentation for settings moved to PostgreSQL must
refer to the administration UI and database-backed defaults, not `.env`.

### 9.1 Local development migration after pulling updated code

Provide a one-time, explicit settings-migration command for colleagues upgrading
their local development environments. Publish its exact invocation with the
implementation. It must work before starting services that require the migrated
settings; it must not depend on those services already running.

The procedure is:

1. Pull the updated code and apply the required schema upgrades to the selected
   local database using the documented upgrade procedure.
2. Run the command in preview mode with an explicit target database and source
   `.env` file. Read only the registered legacy settings being migrated, validate
   them, and show the proposed non-secret values and conflicts. Do not import
   deployment credentials, paths, infrastructure settings, or unrelated entries.
3. Review and explicitly apply the migration. Preserve existing non-default
   values, use specified defaults for missing values, and validate related
   settings together. Missing values never reset an already configured database
   setting. Invalid values and conflicts require explicit resolution before the
   affected settings are marked ready for database-only use.
4. Verify the saved values, then start the updated application. These settings
   are now read exclusively from that database. Later edits to the old `.env`
   entries have no effect.
5. Review the command's list of obsolete entries that can be removed from the
   private `.env`. The command leaves the file intact. Checked-in environment
   templates no longer contain migrated settings.

For colleagues using several local databases, run the procedure separately for
each selected database. The same `.env` may supply their initial values, but
each database subsequently owns its settings independently. Never infer that
migrating one database has migrated another, or silently migrate every reachable
database. Retain the source entries until all intended databases have migrated.

### 9.2 Migration provenance and safe reruns

Persist enough provenance to distinguish untouched installation or migration
defaults from values deliberately configured by an administrator, even when a
configured value equals the default. Comparing values alone is insufficient.
An explicit migration may replace an untouched default with the reviewed legacy
value. A differing previously configured value is a conflict; preserve it until
the operator explicitly resolves the conflict through the governed update path.
Recheck versions when applying a preview so a concurrent edit cannot be lost.

Record applied changes and migration completion against the target database and
the applicable settings migration. Related values, their audit evidence, and
their completion state commit atomically. Failed groups remain incomplete and
can be retried. Actual upgrade events use source `migration`; default seeding
events use source `seeding`. Do not record secrets or the complete `.env` file.

Rerunning a completed migration must not reset settings or reimport later `.env`
edits. Later releases migrating additional keys track those keys separately
without overwriting earlier settings. Ordinary subsequent edits use Settings.

### 9.3 Local startup checks

`run-local-stack.sh` checks the configured target database's settings-migration
state before starting affected services. If migration is incomplete, it reports
the target and the exact preview/apply commands needed, without exposing secrets,
and does not start those services against unreviewed defaults. It never silently
imports `.env` settings on startup. An unreachable database or failed state check
is reported and cannot be treated as successful migration.

A fresh installation with no legacy settings uses the defined defaults and the
documented initialization path; it does not require a nonexistent legacy import.
Unset optional destinations or SMTP values retain their existing warning and
task-blocking behavior. This check is separate from local environment-file
reconciliation, which continues to preserve private values and add only missing
active deployment settings.

## 10. Existing-codebase impact analysis

This section records the expected impact of the proposal on the repository as it
exists on 2 October 2026. It is an implementation inventory, not authorization
to make the changes.

### 10.1 Database schema and migrations

`database/schema.sql` currently has no general application-settings table. An
implementation will need to:

- add the `application_settings` table, constraints, indexes, canonical rows,
  and any configuration-administration privilege to the self-contained latest
  schema;
- add a portable PostgreSQL migration for existing databases, repeating the
  required DDL and inserting missing settings without invoking the migration
  from `schema.sql`;
- extend the immutable event-history vocabulary and validation, if necessary,
  for configuration changes; and
- preserve source `migration` for actual upgrade events and use the existing
  API/web-UI audit source for administrator changes.

The migration cannot discover process environment values. Existing customized
environment values therefore require the explicit rollout reconciliation in
section 9. Schema and migration parity checks must include the new objects and
seeded rows.

### 10.2 API configuration boundary

`backend/services/api/config.py` currently provides generic environment readers
used for both deployment and application settings. It will need to retain
environment parsing only for section 4 and delegate section 5 keys to a new
database-backed application-configuration component.

The new component will need:

- the closed typed registry described in section 7;
- complete-snapshot loading and validation;
- the 30-second non-secret process-local cache and reload lock, plus fresh
  disposition/send-boundary reads and protected SMTP-secret resolution;
- an explicit test clock or equivalent deterministic cache-expiry seam;
- lookup methods that do not fall back to `os.getenv`; and
- a safe way to load settings through an existing connection without recursively
  invoking the normal request connection dependency.

API startup currently validates `DEFAULT_WORKING_TIMEZONE` before opening the
connection pool. The order in `backend/services/api/main.py` must change so the
pool opens first, the complete database configuration is loaded and validated,
and startup fails clearly if the canonical rows are missing or invalid. A failed
startup load must not fall back to environment values.

`backend/services/api/database.py` currently obtains
`CONTENT_INDEXING_SCHEDULING_ENABLED` from the environment while establishing
each request's PostgreSQL session context. That value must instead come from the
validated cached snapshot. Database URL and pool sizing remain environment
reads and must remain usable before the settings cache exists.

### 10.3 API call sites that must become runtime lookups

Several modules resolve application settings into module-level constants at
import time. Those constants must be removed because they would prevent an
administrator's change from taking effect without restart:

- `backend/services/api/authentication.py`: session idle/absolute lifetimes,
  lockout policy, and minimum password length;
- `backend/services/api/main.py`: default aggregation medium and review warning
  window;
- `backend/services/api/dashboard.py`: review warning window and review preview
  limit; and
- `backend/services/api/database.py`: content-index scheduling session context.

The following existing environment reads must also be routed through the same
component at their point of use:

- `backend/services/api/content_storage.py`: upload limit, segment size,
  per-segment checksums, and upload-session lifetime;
- `backend/services/api/document_conversion.py`: conversion timeout and maximum
  rendition size, while leaving the LibreOffice executable path in the
  environment;
- `backend/services/api/search.py` and API health responses: full-text-search
  availability;
- API middleware in `backend/services/api/main.py`: search, manual-reindex, and
  text-indexer request limits;
- `backend/services/api/localization.py`: working timezone;
- `backend/services/api/session_cleanup.py`: retention, interval, and batch
  settings;
- `backend/services/api/content_cleanup.py`: cleanup interval;
- `backend/services/api/text_indexing_maintenance.py`: indexing retention,
  cleanup interval, cleanup batch size, and credential retention; and
- `backend/services/api/user_management.py`: text-indexer credential-history
  retention.

Functions that already receive a database connection should use a snapshot
associated with that request or operation instead of issuing individual setting
queries. Code that does not currently receive a connection will need an explicit
configuration dependency or a narrowly scoped snapshot argument; hidden global
database calls should not be scattered through domain modules.

The health response currently exposes selected feature flags. It may continue
to expose non-secret effective values, but it must obtain them from the same
snapshot and must not become an unrestricted settings endpoint.

### 10.4 Operational API-owned workers

The session cleanup, content cleanup, and text-indexing maintenance commands run
outside API request handling but connect to the same logical database. Their
database-managed defaults must no longer be argparse defaults sourced from the
environment.

For one-shot execution, each command loads one validated settings snapshot at
the start of the run. For `--watch` execution, it uses the same 30-second cache
and re-evaluates interval, retention, and batch settings before each pass.
Explicit command-line arguments remain per-invocation operator overrides and do
not modify database settings; help output must distinguish an explicit override
from the database-managed default. Existing advisory-lock and single-logical-
database execution requirements are unchanged.

The text-indexer worker itself remains unaffected by the database settings
component. Its existing `backend/services/text_indexer/config.py` environment
model remains intact. Only the API-owned policies around indexing and indexer
credentials move to PostgreSQL.

### 10.5 Administration API and authorization

No current API router provides general application-setting administration. An
implementation will require endpoints to:

- list the registered editable settings and their effective values, types,
  validation metadata, defaults, versions, and last-update metadata; and
- update related settings together in an atomic batch with `If-Match`/expected
  versions and a mandatory change reason.

Request and response models must be explicit; the generic CRUD routes must not
be used to bypass registry validation, authorization, optimistic concurrency,
or auditing. Deployment settings must be impossible to retrieve through these
endpoints.

Implementation must add the agreed `app.settings.manage` privilege and grant
it to the System Administrator profile through the normal authorization
model. Role-name checks must not replace privilege enforcement. SMTP password
inputs are write-only; list responses expose set-state, not secret values.

### 10.6 WebUI behavior and configuration module

`frontend/webui/config.py` currently reads the working timezone, root medium,
full-text feature flag, Dashboard limits, recent-classification limit, and user-
session page size from the environment. Those functions must be removed or
changed to consume API-provided effective configuration. Its deployment-only
functions for API URL, host, port, reload, and storage secret remain.

`frontend/webui/app.py` currently uses those helpers in localization fallback,
aggregation creation, Dashboard rendering, favourites previews,
classification selection, and user-session pagination. Those consumers must
use values returned by existing bounded page/bootstrap responses or a single
bounded configuration response. The implementation must not add one settings
request per widget or introduce duplicate page requests, in accordance with
`docs/webui-performance.md`.

The duplicate `WEBUI_FULL_TEXT_SEARCH_ENABLED` path must be deleted. UI feature
visibility and the API's enforcement must derive from the same database value;
API enforcement remains authoritative during the cache propagation window.

The reusable Administration → Settings page defined in Administration Settings
is required; no separate disposition-only settings store or page is introduced.
Before implementation,
its user-visible text must follow sections 7.5 and 7.8.1–7.8.4 of
`specs/internationalization-and-user-preferences.md`. English keys must remain
lexicographically ordered, maintained-language artifacts must preserve curated
translations and follow the identical key order, and live LTR/RTL behavior must
be verified. If a settings table is used, it must follow the established Wathiq
table pattern rather than a raw/default NiceGUI table.

### 10.7 Environment examples, launchers, and documentation

Implementation will remove every section 5 key and
`WEBUI_FULL_TEXT_SEARCH_ENABLED` from:

- `.env.example`;
- `.env.example.api` where present;
- `backend/services/api/deploy/api.env.example`; and
- `frontend/webui/deploy/webui.env.example` where present.

Text-indexer example files retain the complete section 4.5 inventory. Local
stack launch scripts must stop interpreting database-managed keys as process
configuration, while retaining the service-orchestration controls in section
4.4.

At minimum, `docs/deployment.md`, `docs/operations.md`,
`docs/authentication.md`, `docs/dashboard.md`, `docs/document-viewing.md`,
`docs/content-storage.md`, `docs/full-text-search-local-setup.md`, and
`frontend/webui/README.md` require reconciliation wherever they currently
describe a migrated setting as an environment variable or restart-only value.
Existing feature specifications that normatively define one of these defaults
must be cross-referenced or amended without silently changing their approved
product behavior.

### 10.8 Test impact

Tests that currently change environment variables or reload modules to exercise
section 5 settings must instead insert/update rows in a newly created disposable
test database and explicitly expire or replace the test cache. Pure registry and
validation tests may remain database-free.

Required additions include:

- canonical-schema, migration, and schema/migration parity coverage;
- registry-to-database completeness and type/default agreement tests;
- no-environment-fallback tests using deliberately conflicting environment
  values;
- deterministic cache hit, expiry, refresh-failure, local invalidation, and
  multi-instance convergence tests;
- concurrent-administrator optimistic-conflict and atomic rollback tests;
- privilege and deployment-setting non-disclosure tests;
- worker one-shot, watch-mode refresh, and command-line-override tests;
- API/WebUI integration tests proving that feature visibility and enforcement
  share one value; and
- rendered administration-page comparison in LTR and RTL, including validation,
  empty/loading/error states, and narrow viewports.

No database-backed test may reuse a development or other persistent database.
Each such run must create, initialize, target, and finally drop a uniquely named
disposable PostgreSQL database as required by the repository instructions.

### 10.9 Principal risks and mitigations

| Risk | Required mitigation |
| --- | --- |
| Import-time constants preserve stale values forever | Remove section 5 module-level constants and resolve through the cached snapshot at use time |
| API instances disagree for up to one cache lifetime | Document the 30-second bound; keep enforcement server-side; test controlled-clock convergence |
| A setting change produces internally inconsistent behavior within one request | Capture one immutable snapshot for the request/operation and pass it to all affected logic |
| Startup cannot validate database configuration because pool opening depends on configuration | Keep connectivity/pool settings in the environment and load database settings only after the pool opens |
| Existing customized `.env` values are lost during rollout | Require the section 9 pre-deployment comparison and explicit database entry before removing variables |
| WebUI adds repeated settings requests or a second cache | Include needed effective values in bounded bootstrap/page responses and keep the API authoritative |
| Invalid direct SQL edits break every instance | Enforce database constraints, validate the complete snapshot, fail startup on an invalid initial load, and retain only a previously validated runtime snapshot |
| Cleanup workers silently retain startup values | Re-evaluate settings before each watch pass through the same short-expiry component |
| Administrators expose or mutate infrastructure secrets | Keep section 4 keys outside the table, API models, event metadata, and UI |
| Feature flag changes are visible before all instances enforce them | State the propagation window in the UI and treat the API instance handling each request as authoritative |

### 10.10 Estimated implementation breadth

This is a cross-cutting configuration migration rather than a localized UI
change. It affects the canonical schema and one migration, the API configuration
and connection lifecycle, multiple API domain modules, three API-owned
operational workers, WebUI configuration consumers, authorization and audit,
environment examples, operational documentation, and both unit and browser
test suites. The text-indexer process configuration and deployment-level API/UI
startup settings remain deliberately outside the change.

Implementation should be phased so the database table and read path exist before
environment fallbacks are removed, but no phase may leave two production
authorities for a section 5 key. A compatibility phase may write and verify the
database values while the old code remains deployed; the cutover release must
switch each migrated key to database-only authority and remove its environment
lookup together.

## 11. Acceptance and traceability requirements

| Requirement | Required verification |
| --- | --- |
| ACFG-01 — Every production setting has exactly one configuration ownership category; every database-managed setting has an explicit registry UI category supplied by the API | Inventory tests comparing registry, environment reads and documented tables; API/UI grouping and translated-category tests without key-prefix inference |
| ACFG-02 — Database-managed keys have no environment lookup or fallback | Static/source test and runtime tests with conflicting environment values |
| ACFG-03 — Canonical schema and migration create all settings without overwriting existing database values; reviewed rollout preserves existing non-default environment values before database-only cutover | Fresh-schema and upgrade tests using separate disposable databases, non-default preservation, conflicting/invalid-value handling, and repeat-rollout tests |
| ACFG-04 — Types, defaults, and validation match section 5 | Registry/schema contract tests and invalid-update API tests |
| ACFG-05 — General cached settings converge within 30 seconds; disposition creation/save/send operations read current committed settings directly without notifications | Controlled-clock multi-instance cache and fresh-operation-read tests |
| ACFG-06 — A failed refresh never exposes a partial or environment-derived snapshot | Unit and database-failure integration tests |
| ACFG-07 — All database-managed settings are editable; related settings are saved together through authorized, reasoned, optimistic, atomic, audited updates | Registry/UI editability coverage, protected-secret replacement, grouped validation, authorization, concurrent group conflict, complete rollback, and per-setting event-history tests |
| ACFG-08 — The WebUI has no duplicate feature flag or business-setting authority | UI/API integration and source inventory tests |
| ACFG-09 — Deployment secrets and infrastructure values are absent from the settings API and UI | API negative tests and UI tests |
| ACFG-10 — Environment examples and operational documentation contain only deployment settings | Documentation/inventory check |
| ACFG-11 — LTR and RTL administration UI behavior, concise visible explanations for every setting, and all maintained translations are verified | Browser verification of purpose/type/units/limits/default/effect explanations and internationalization artifact checks |
| ACFG-12 — app.settings.manage is granted to System Administrator and governs the reusable Settings page and updates | Privilege/profile, unauthorized role, API, and UI authorization tests |
| ACFG-13 — SMTP password is protected at rest, masked/write-only, and absent from logs, audit values, and public/cache snapshots | Secret storage, input/output, failure-log, audit-redaction, and server-only resolution tests |
| ACFG-14 — Disposition settings preserve per-job routes, current artifact destinations and warnings, and per-attempt recipient/SMTP configuration | Route snapshot, changed-destination warning, original-record preservation, fresh-send configuration, and concurrent-setting-change tests |
| ACFG-15 — Unset optional disposition/SMTP settings do not prevent startup but produce the required warnings or task errors | Unconfigured startup, custody/task warnings, missing-root handling, and disabled-send tests |
| ACFG-16 — Explicit local migration previews and preserves legacy values independently for each selected database, distinguishes untouched defaults from configured values, and is safe to rerun | Disposable-database preview/no-write, non-default and configured-default preservation, invalid/conflicting values, concurrent edit, grouped rollback, provenance, multiple-database isolation, and completed-rerun tests |
| ACFG-17 — Local startup checks migration readiness without importing settings; private environment files are preserved and fresh installation remains supported | Launcher tests for incomplete/completed migration, failed database checks, exact actionable commands, no silent import, unchanged private files, obsolete-entry reporting, and fresh-install defaults |

Database-backed verification must follow the repository rule requiring a newly
created, uniquely named disposable PostgreSQL database for each run and clean
removal after the run, whether the run passes or fails.

## 12. Approved configuration decisions

1. The general settings cache lifetime is 30 seconds. Section 6.1 operations
   still read current committed settings directly.
2. Settings administration uses `app.settings.manage`, granted to System Administrator.
3. Every database-managed setting is editable, subject to validation and
   protected-secret handling.
4. Migration preserves existing non-default values through the reviewed rollout
   in section 9; defaults must not silently replace them.
5. Related settings are saved together in a validated atomic operation.
6. `AUDIT_TRAIL_SEARCH_RESULT_LIMIT` is database-managed, with default 1000,
   positive-integer validation, and the general 30-second cache.
7. UI grouping uses an explicit registry `category` supplied by the API, not
   setting-key prefixes or a duplicated database column.

These decisions and the specification are approved. No configuration decision
remains open in this section.

The database-managed Audit Trail decision supersedes the earlier decision to
keep this limit deployment-managed. Its result-count and pagination protections
remain as defined in section 5.5.


## Approved local environment reconciliation

Separately approved for implementation: `run-local-stack.sh` reconciles the root
`.env` against `.env.example` before loading configuration and after acquiring
its launcher lock. Append missing active settings with associated comments;
never overwrite or remove an existing assignment, including empty values.
Report added names without their values. Skip example credentials and unresolved
placeholders and report them for manual configuration. Generate a random WebUI
storage secret if absent. Preserve existing file permissions; create a new file
with mode 0600. Repeated reconciliation must be idempotent. Explicit process
environment values retain precedence. This behavior does not alter production
service startup or automatically configure optional commented overrides.

Traceability: `tools/reconcile_local_env.py`, the launcher startup hook, and
`tools/tests/test_reconcile_local_env.py`. Three tests verify byte/value and
permission preservation, idempotence, credential skipping, secret creation and
startup ordering. Shell syntax validation passes. Direct reconciliation of the
current local file reports no missing settings without starting services.
