# Authentication subsystem

## Scope and model

ERMS currently supports local, database-backed authentication. Authentication
establishes identity; authorization remains a separate subsystem. Users have an
`account_type` of `person` or `service`. Service accounts represent software and
cannot use interactive password login. Administrative authority is assigned by
the reserved `system-administrator` role, never by a superuser flag on a user.

Future OIDC providers will map their subject identifiers to the same internal
users and issue the same internal sessions, keeping the rest of the application
independent of the authentication provider.

### Text-indexer service credentials

The full-text indexer uses a dedicated service account and the protected,
non-organizational `text-indexer-service` system role. That role is restricted
to service accounts and its `TEXT_INDEXER_SERVICE` profile contains exactly
`content.index.execute`. It is not an information-governance role and cannot be
assigned to a person account.

Indexer keys have the strict display-once form
`wti_<26-character identifier>.<43-character random secret>`. PostgreSQL stores
the identifier and the lowercase SHA-256 digest of the random-secret substring,
never the complete key or plaintext secret. Each credential has independent
expiry and revocation state. A service account cannot have an interactive
password or login session.

The API accepts these credentials only under
`/api/v1/internal/text-indexing/`. It rejects them on ordinary user routes, and
it rejects person sessions and cookies on the internal namespace. Phase 1
installs this authentication boundary and persistence model; Phase 2 adds the
lease-scoped worker operations. Until those operations and the approved
administration workflow exist, operators must not provision keys with ad-hoc
SQL.

## Credentials and passwords

`user_credentials` contains one optional local credential per person account.
Passwords are hashed with Argon2id and neither hashes nor plaintext passwords
are exposed by the API or copied to event history. Repeated failures cause a
temporary account lock. Relevant settings are:

- `AUTH_PASSWORD_MIN_LENGTH` (default `12`)
- `AUTH_LOCKOUT_ATTEMPTS` (default `5`)
- `AUTH_LOCKOUT_MINUTES` (default `15`)

Administrators issue a random temporary password from the Users page. It is
shown once, expires after 24 hours, revokes existing sessions, and forces a
password change before the user can access normal application functions.

## Sessions

`login_sessions` stores only SHA-256 hashes of opaque session and CSRF tokens.
Sessions are shared through PostgreSQL, so they work across API workers and can
be revoked immediately. The browser cookie is HttpOnly and SameSite=Lax.
Cookie-authenticated write requests require the matching CSRF header. The
NiceGUI service keeps its API token in encrypted user storage and sends it as a
Bearer credential to the API.

API instances sharing the same database do not require session affinity.
Multiple NiceGUI instances require frontend affinity; shared user storage is
optional for preserving login data across instances;
see the [deployment guide](deployment.md).

- `AUTH_SESSION_IDLE_MINUTES` controls sliding idle expiry (default `30`).
- `AUTH_SESSION_ABSOLUTE_HOURS` controls the maximum lifetime (default `12`).
- `WEBUI_STORAGE_SECRET` encrypts NiceGUI user storage and must be replaced in
  every non-development deployment.
- `AUTH_COOKIE_SECURE` must be `true` when the API is served over HTTPS
  (it defaults to `false` only for local HTTP development).

The Login sessions page lists user, status, creation and activity times, IP,
and client description. A user can revoke their own sessions. Members of the
`system-administrator` role can see all sessions, force logout one session, or
force logout all sessions for a user. Destructive actions require confirmation.

Login sessions are transient operational security state rather than the durable
authentication ledger. The session-cleanup worker audits terminal
session details and removes expired or long-revoked rows after a configurable
retention period. See the
[operational tools catalogue](operations.md#6-login-session-cleanup) and the
[authentication and login-session lifecycle specification](../specs/authentication-and-login-session-lifecycle.md).

The user profile menu shows **Previous sign-in** as the most recent successful
authentication event other than the current session. This value comes from the
immutable event history, not from transient login-session rows. It therefore
remains available after session cleanup. The menu shows **First sign-in** when
there is no earlier successful authentication event. Session administration
remains available on the dedicated Login sessions page; the profile menu does
not duplicate that navigation action. The profile identity also uses the same
stable, user-specific initials and avatar colour as other user displays.

## API

- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me` (includes nullable `previous_login_at`)
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/change-password`
- `GET /api/v1/auth/sessions`
- `DELETE /api/v1/auth/sessions/{session_id}`
- `DELETE /api/v1/auth/users/{user_id}/sessions`
- `POST /api/v1/auth/users/{user_id}/temporary-password`

All `/api/v1` endpoints except login require an active session. Health and API
documentation remain public. Suspended/inactive users and service accounts
cannot authenticate interactively.

## Initial bootstrap administrator

After loading `database/schema.sql`, the required reference-data seed and
`database/baseline.sql` into a genuinely empty database, provision
the first administrator with the API service's own Python environment:

```bash
backend/services/api/.venv/bin/python -m backend.services.api.manage_auth \
  bootstrap \
  --name "Bootstrap Administrator" \
  --email bootstrap@erms.local
```

`DATABASE_URL` selects the target database. As elsewhere in the application, a
real process environment variable takes precedence over the local `.env` file.
The command performs one transaction and creates:

- the reserved `SYSTEM — Platform Administration` organizational unit;
- the reserved `system-administrator — SYSTEM — System Administrator` role;
- one active person account, defaulting to `Bootstrap Administrator
  <bootstrap@erms.local>`;
- the user's active role assignment; and
- an Argon2id credential containing a newly generated temporary password.

The password is printed exactly once, expires after 24 hours, and has
`must_change_password = true`. The user may authenticate immediately but can
only change the password, inspect their principal, or sign out until the
password has been changed. The plaintext password is never placed in SQL,
source control, `.env`, API responses, or event history.

The forced password-change dialog provides **Back to sign in**. This signs out
and revokes the restricted temporary session before returning to the login
screen. It does not recover or reveal a forgotten temporary password; an
administrator must issue a new temporary password through the supported reset
workflow.

The bootstrap login has `account_type = person`, despite its administrative
name. In this model, `service` accounts are non-interactive identities for
software and cannot log in with passwords. The bootstrap user's administrative
authority is derived from the normal reserved role; its email address or
external ID is not a hidden authorization bypass. A user never belongs directly
to an organizational unit. Every ordinary person role—including this reserved
platform role—belongs to exactly one; the protected service-only text-indexer
role is the sole non-organizational system-role exception.

### Bootstrap safeguards

Bootstrap succeeds only while the `users` table is empty. It refuses without
changing anything when either:

- an active, effective `system-administrator` already exists; or
- any user row already exists, even if there is currently no administrator.

These rules prevent the provisioning utility from becoming a second path for
privilege escalation in an established database. A failed command is rolled
back as a whole. Re-running it cannot reset the existing bootstrap user's
password or reveal a replacement password.

For this check, an **active system administrator** means an active person account
with a currently valid assignment to the role whose stable code is
`system-administrator`. The role itself must be active and its owning
organizational unit and all ancestor units must be active. The command evaluates
those same effective-role rules used when resolving a logged-in principal; it
does not infer authority from the user's name, email, external ID, or database
primary key.

The four entity events created for the organizational unit, user, role, and
assignment are grouped by one correlation ID and recorded with actor type
`automated_process`, source `administrative_tool`, reason `Initial system
bootstrap`, and secret-free bootstrap metadata. The actor is an automated
process because the utility runs before the new bootstrap user has authenticated;
it does not impersonate that user.

Do not confuse this with `users.account_type = service`. Account type classifies
a stored identity (`person` or `service`), while event actor type classifies how
an event was caused (`user`, `anonymous`, or `automated_process`). An
authenticated text-indexer identity is recorded as actor type
`automated_process` with its own `actor_user_id`. See the actor taxonomy in
[`event-history.md`](event-history.md#actor-type-versus-account-type).

After signing in, change the temporary password, create the real organizational
structure and named administrators, and verify that at least one other active
user has the effective `system-administrator` role. The original bootstrap
account can then be deactivated; deactivation revokes all of its active login
sessions. Do not deactivate the reserved role or `SYSTEM` organizational unit
while any required administrator still depends on them.

## Password recovery and promotion

For an existing person account, issue a new temporary password with:

```bash
backend/services/api/.venv/bin/python -m backend.services.api.manage_auth \
  reset-password administrator@example.org
```

To create or assign the reserved administrator role during deliberate recovery,
identify the existing organizational unit that will own it:

```bash
backend/services/api/.venv/bin/python -m backend.services.api.manage_auth \
  reset-password administrator@example.org \
  --make-system-administrator \
  --org-unit-code ROOT
```

The original command form without the explicit `reset-password` word remains
accepted for compatibility. Password recovery revokes the target user's old
sessions and prints a new single-use temporary password exactly once.

## Audit history

Authentication emits secret-free domain events including
`AUTHENTICATION_SUCCEEDED`, `AUTHENTICATION_FAILED`, `PASSWORD_CHANGED`,
`PASSWORD_RESET`, and `SESSION_REVOKED`. Authenticated data changes populate
`actor_user_id` and use actor type `user`. Credential and session tables do not
use automatic snapshot triggers because their rows contain security secrets.

## OIDC extension point

A future `user_identities` table will associate `(provider, subject)` pairs
with internal users. After provider validation, OIDC login will create the same
opaque internal session used by local authentication. Roles, audit attribution,
session administration, and future authorization will therefore work the same
way for either provider.

## Runtime database policy

The five authentication/password and three session-cleanup settings are owned by
Administration Settings, with canonical defaults from Application Configuration
section 5.3 and 30-second API cache convergence. Obsolete environment assignments
cannot override them. Cookie security remains deployment-owned.

Session lifetimes are evaluated from creation/last activity at the next session
check. A shorter policy can expire a session immediately; that expiry is persisted
so a later increase cannot restore it. Previously expired/revoked sessions remain
unusable. Existing password hashes remain accepted when the minimum changes;
new password changes and generated temporary/recovery passwords use current
policy. Cleanup defaults come from the same validated registry. One-shot commands
load a fresh snapshot; watch commands re-evaluate cached policy before each pass.
Explicit CLI arguments remain overrides and never update settings. See the
[upgrade procedure](application-settings-upgrade.md).
