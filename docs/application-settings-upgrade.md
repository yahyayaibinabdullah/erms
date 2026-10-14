# Application settings upgrade (Disposition Phases 2–5)

The shared registry/API/schema is Phase 2, Settings UI is Phase 3, and general
application/WebUI consumer cutover and reviewed migration/readiness are Phase 4.
Content/authentication consumer cutovers are Phase 5. Search/indexing migration
remains Phase 6; actual
disposition operations and document delivery remain later phases.

## Database and API deployment

For a new empty database, initialize from `database/schema.sql` alone. For an
existing database already current through migration 049, inspect
`schema_migrations`, back up through the established deployment procedure, and
apply the missing upgrade:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/migrations/050_application_settings.sql
backend/services/api/.venv/bin/python -m pip install -r backend/services/api/requirements.txt
```

Migration 050 adds missing settings defaults without importing `.env`, preserves
existing configured rows, and grants `app.settings.manage` to System Administrator
and the existing All Privileges compatibility profile. It can be rerun safely.
Settings provenance and per-database/per-key completion support the explicit
reviewed legacy migration below. Deploying code or applying schema 050 alone
does not mark an existing database's legacy migration complete.

Restart API processes after deploying the code/schema/dependency changes. API
startup validates the complete settings registry. Missing or invalid rows fail
startup; unset optional disposition/email values and an unset encryption key
allow startup. Existing private environment assignments remain intact.

## SMTP encryption key

SMTP host, port, security, authentication, username, password, sender, reply-to,
and timeout are database settings. Only `APPLICATION_SETTINGS_ENCRYPTION_KEY`
belongs to the API deployment environment. Its default is unset. A valid key is
required to replace or resolve an SMTP password; ordinary settings remain usable
without it. The password is stored as authenticated Fernet ciphertext, bound to
its database identity and setting key. Public reads expose only whether it is set.

For local development, append a securely generated key only if the private `.env`
does not already define it:

```sh
backend/services/api/.venv/bin/python -m backend.services.api.application_settings_secret --init-local-key
```

The command never displays a key, changes existing assignments (including empty
ones), or imports business settings. Newly created files use mode 0600; existing
file permissions and bytes are preserved. The current workspace's missing key
has been initialized using this command.
An existing empty or invalid assignment must be configured deliberately; this
helper preserves it. Templates leave this optional setting commented out so
local reconciliation does not insert an empty assignment before initialization.

In production, supply a URL-safe base64 encoded 32-byte Fernet key through the
API process's shell/service environment. That environment takes precedence over
local `.env` (`load_dotenv(..., override=False)`). Supply the same key to all API
instances serving the same logical database, retain it securely with database
backups, and restart API processes after environment changes. Do not generate
independent keys for those instances. Preserve the existing key for saved
credentials: replacing the key alone cannot decrypt or re-encrypt them. No key
file setting, SMTP-password environment variable, or database key storage is added.

The key is documented in `.env.example` and the authoritative
`backend/services/api/deploy/api.env.example`; `.env.example.api` is regenerated
with `python3 tools/sync_api_env_template.py`. WebUI and text-indexer templates
do not consume the API key and are unchanged.

## Protected API

Authenticated people with `app.settings.manage` can read and update
`GET/PUT /api/v1/application-settings`. The API returns the 51 registered settings
with explicit categories, translated published labels/descriptions (English
fallback), validation metadata, versions, provenance, defaults/effective values,
and secret set-state. Infrastructure settings are excluded.

PUT requires a nonblank `X-Change-Reason` and a `changes` array with `key` and
`expected_version` for every submitted row. Provide `value` for a non-secret
replacement, `secret_value` for a password replacement, or `clear_secret: true`
to clear it. Omit the replacement field to retain a related value while checking
its version. Destination edits submit the scheme and both classifications;
SMTP edits submit all ten SMTP rows. Unrelated settings can be saved separately.
The proposed group, versions, audit evidence, provenance, and migration completion
commit atomically. A stale version returns 409; invalid groups return 422; an
unavailable encryption key during replacement returns a safe 503 without inputs.

When the stored SMTP port is unset, the effective port follows security mode:
587 for STARTTLS or 465 for implicit TLS. An explicitly configured port remains
unchanged when security mode changes. Authentication enabled requires both a
username and a protected password; incomplete optional send configuration blocks
server-side email capture and does not prevent startup.

General non-secret snapshots have a 30-second TTL measured from successful load
completion, keyed by database connection identity within each API process. A lock
serializes refresh. Successful saves invalidate the updating process after commit;
other instances expire normally. A failed refresh logs only its failure type and
can retain its last fully validated snapshot. No identity/language rendering or
password/ciphertext enters that cache. Job, artifact, and email capture helpers use
a separate current committed read with no cache fallback and retain one immutable
configuration for the operation. Later phases connect them to their workflows.

## Phases 4–5 reviewed legacy migration

Stop the affected services before this upgrade. Apply the required schema upgrade
first; then run the API Python interpreter from the repository root. Set
`DATABASE_URL` to the **one intended database**, or pass the same explicit
connection value on every command. Keep connection credentials private.

```sh
backend/services/api/.venv/bin/python tools/migrate_application_settings.py \
  --preview --database-url "$DATABASE_URL" --source-env .env \
  --plan /tmp/erms-settings-review.json

backend/services/api/.venv/bin/python tools/migrate_application_settings.py \
  --apply --database-url "$DATABASE_URL" --source-env .env \
  --plan /tmp/erms-settings-review.json --actor-user-id 123 \
  --reason 'Reviewed general, WebUI, content and authentication legacy configuration'

backend/services/api/.venv/bin/python tools/migrate_application_settings.py \
  --check --database-url "$DATABASE_URL" --source-env .env
```

Replace `123` with an existing active person who currently holds
`app.settings.manage`. Preview is a read-only database transaction. Its JSON lists
only the 24 active registered non-secret settings, their current/proposed values,
versions/provenance, validation/conflict codes, logical database identity and
obsolete source keys. It never contains the complete source file, deployment
credentials or an invalid raw value. The plan file must be new; choose another
filename when making a revised preview. The source file is never overwritten,
including when a plan path accidentally names that source file.

The original Phase 4 inventory is `DEFAULT_WORKING_TIMEZONE`,
`DEFAULT_ROOT_AGGREGATION_MEDIUM`, `REVIEW_WARNING_WINDOW_DAYS`,
`DASHBOARD_FAVOURITE_ITEM_LIMIT`, `DASHBOARD_RECENT_ITEM_LIMIT`,
`DASHBOARD_RECENT_DAYS`, `DASHBOARD_REVIEW_PREVIEW_LIMIT`,
`CLASSIFICATION_RECENT_SELECTION_LIMIT`, and `USER_DETAILS_SESSION_LIMIT`.
Only these entries are considered; other legacy groups await their owning phase.

Resolve every issue explicitly before applying. Correct an invalid source entry
and make a new preview, or add `--keep-database KEY` to that new preview to retain
its validated database value. For a configured-value conflict, use
`--keep-database KEY` or `--use-legacy KEY` in the revised preview. The latter
uses the ordinary governed update function before marking completion, in the
same transaction, with current authorization, reason and migration audit source.
It never silently overrides an administrator's configured default.

Apply locks the active rows in stable order and rebuilds the reviewed plan. A
changed target, source meaning or unfinished row/version requires a new review.
All values, events and per-key completion commit together. Missing source values
use canonical defaults only for untouched rows and retain configured values.
Completed keys ignore later source edits and ordinary Settings versions; reruns
never reimport them. The same migration identity tracks future additional keys
separately. Verify values before removing obsolete entries manually, and retain
source entries until every intended database has migrated.

`run-local-stack.sh` performs the read-only check before any affected service or
worker starts or is reused. Incomplete migration reports the selected database
and preview/apply invocations, then exits; a failed/unreachable state check also
exits. It never imports on startup. API startup rejects an incomplete **upgrade**
database independently. A fresh canonical installation with no applicable legacy
entries needs no import; local fresh databases with explicit legacy entries still
require a reviewed initialization for those entries.

The nine consumer values are now read only from the API's validated cache.
Ordinary bootstrap, Dashboard and favourites responses include the finite page
configuration; dialogs/user details can use one authenticated bounded
`GET /api/v1/application-configuration` response. It contains only those nine
non-secret values, has no administration mutation authority, and exposes no
SMTP, deployment or encryption-key data. Saved personal timezones continue to
win; only API-marked fallback timezones follow a changed shared default.

The WebUI has no settings TTL or persistent business-settings copy. Its transient
page values refresh from ordinary API responses or dialog/page entry; remembered
locale metadata excludes the configuration dictionary. Session requests return
their effective page size, keeping offsets and controls consistent after changes.
Existing transport bounds remain: recent-classification windows at most 20,
review/session windows at most 50, and Dashboard recent-activity requests at most
50. Configured positive limits are maxima; they do not authorize a full download.

All nine keys were removed from relevant checked-in templates. The authoritative
API template was synchronized to `.env.example.api`; WebUI and root templates
were reconciled, while text-indexer templates contain no affected consumers.
Existing private `.env` values remain intact. Restart services to load the new
code after the reviewed migration; subsequent setting edits need no restart.

## Phase 5 extension of the same migration

The active command now includes all seven content keys in section 5.2 and all
eight authentication/session keys in section 5.3, in addition to the original
nine general/interface keys. Apply a **new preview from this code version**
before starting upgraded API or cleanup workers. Existing completion markers
for Phase 4 keys are retained; those keys never reimport later environment edits.
New content/authentication keys require review independently. Configured rows,
including explicit default values, remain preserved or require a conflict choice.
Boolean legacy values accept true/false, 1/0, yes/no and on/off case-insensitively;
invalid values require an explicit decision. The source file remains untouched.

The content keys are MAX_UPLOAD_SIZE_BYTES, CONTENT_SEGMENT_SIZE_BYTES,
CONTENT_SEGMENT_CHECKSUMS_ENABLED, CONTENT_UPLOAD_SESSION_TTL_SECONDS,
CONTENT_CLEANUP_INTERVAL_SECONDS, DOCUMENT_CONVERSION_TIMEOUT_SECONDS and
MAX_RENDITION_SIZE_BYTES. Authentication keys are AUTH_SESSION_IDLE_MINUTES,
AUTH_SESSION_ABSOLUTE_HOURS, AUTH_LOCKOUT_ATTEMPTS, AUTH_LOCKOUT_MINUTES,
AUTH_PASSWORD_MIN_LENGTH, AUTH_SESSION_RETENTION_DAYS,
AUTH_SESSION_CLEANUP_INTERVAL_SECONDS and AUTH_SESSION_CLEANUP_BATCH_SIZE.
These 15 obsolete entries were removed from root and API environment templates.
WebUI/text-indexer service templates do not consume them and require no change.
No new environment variable or schema migration is required. Existing private
values remain intact until an operator deliberately removes obsolete entries.
