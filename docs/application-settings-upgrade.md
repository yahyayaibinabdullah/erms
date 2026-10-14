# Application settings foundation upgrade (Disposition Phase 2)

Phase 2 introduces the shared database configuration foundation. It does not
switch existing environment-backed business consumers; their reviewed migration
and cutover remain in Phases 4–6. Administration Settings UI is Phase 3, and
disposition operation integration and document delivery belong to later phases.

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
legacy migration command delivered with the consumer cutovers; this phase does
not provide that command or declare legacy migration complete.

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
