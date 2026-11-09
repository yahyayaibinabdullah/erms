# Authentication and Login-Session Lifecycle — Technical Specification

**Status:** Implemented
**Project:** ERMS  
**Prepared:** 18 September 2026  
**Revision:** 0.1

## 1. Purpose

This specification defines user authentication states, login-session behavior,
durable authentication auditing, session retention and cleanup, and the
operational relationship between transient `login_sessions` rows and immutable
`event_history` rows.

It ensures that:

- account lifecycle and temporary credential locking have distinct meanings;
- session rows can be revoked and cleaned up safely;
- deleting a user can remove transient sessions without erasing authentication
  history;
- authentication audit events remain intelligible without live session or user
  rows; and
- cleanup runs as a controlled operational process outside FastAPI.

Permanent deletion eligibility for users, roles, and organizational units is
defined separately in
[User, Role, and Organizational-Unit Deletion](user-role-org-unit-deletion.md).

## 2. User authentication states

### Sign-in feedback and language direction

When a sign-in attempt is rejected with HTTP 401, the form explains that the
credentials were not accepted and asks the user to check the login name and
password and retry. Use identical wording for an unknown login name and an
incorrect password. The generic session prompt “Sign in to continue” remains
appropriate for unauthenticated protected requests, not a failed sign-in attempt.
Other failures retain their specific existing error handling.

The sign-in panel, its labels, fields and actions follow the remembered UI
language and direction before authentication. Arabic uses RTL. Apply direction
to the document and dialog portal as well as the panel; do not wait for the
authenticated localization bootstrap. This keeps signed-out and signed-in
presentation consistent without requiring authentication to restore direction.
At desktop width the Arabic brand/marketing panel is on the right and the form
on the left. Field labels and placeholders align right; the password visibility
control appears at the field’s left edge. English mirrors these positions.
The entered login name and password use an isolated LTR text direction in
every UI language, so ASCII punctuation retains its entered order. This
applies to masked and revealed password text and does not restrict the
accepted character set or alter submitted credentials. Arabic field labels
and surrounding controls remain RTL.

### 2.1 Active

An active person account may authenticate and use an otherwise valid session.

```text
users.date_deactivated IS NULL
users.date_suspended IS NULL
```

### 2.2 Inactive or deactivated

Deactivation is a reversible account-lifecycle operation. It produces:

```text
users.date_deactivated IS NOT NULL
users.date_suspended IS NULL
```

An inactive user cannot authenticate or use an existing session. Deactivation
must revoke every active session in the same transaction. Reactivation returns
the user to `active` but does not restore revoked sessions.

### 2.3 Suspended

Suspension is a deliberate administrative security operation that temporarily
prevents account use without representing that the account has left service.

```text
users.date_deactivated IS NULL
users.date_suspended IS NOT NULL
```

`date_suspended` is the authoritative stored suspension state. Suspension is
appropriate for a security investigation, suspected compromise,
or another temporary administrative hold. It must revoke every active session
in the same transaction. Role assignments remain stored but cannot contribute
effective authorization while the user is suspended.

Unsuspension returns the user to `active` but does not restore revoked sessions.

### 2.4 Temporary credential lock

A credential lock is not a user lifecycle status. Repeated failed local-password
authentication attempts set `user_credentials.locked_until`. Until that time,
new local-password authentication is rejected.

Login and password-change current-password checks share the credential's
`failed_attempt_count`, `locked_until`, `AUTH_LOCKOUT_ATTEMPTS`, and
`AUTH_LOCKOUT_MINUTES`. Incorrect current passwords count as failed password
authentication; new-password validation errors (including insufficient length)
and confirmation mismatches do not increment or clear an existing counter.
Concurrent checks must serialize on the credential row so neither endpoint nor
another session can bypass the limit.

During a credential lock, password changes are also rejected. Login retains its
generic 401 response. Password changes return 429 with `Retry-After` seconds and
localized cooldown feedback, including on the failure that reaches the limit.
Blocked requests do not increase the counter or extend the deadline. Existing
sessions are not revoked by the credential lock.

At the next password check on or after `locked_until`, clear the expired lock
and reset the counter before evaluating the submitted password. The first
incorrect attempt after expiry counts as one of a fresh allowance. Preserve
that reset even if a correct current password is followed by an invalid new
password. Successful login, successful password change, and administrative
temporary-password/recovery issuance clear the failure counter and lock.
Failed password changes persist the counter and matching
`AUTHENTICATION_FAILED` event atomically before returning an error; safe event
metadata identifies `authentication_context` as `login` or `password_change`.

| Condition | Cause | Duration | Scope | Existing sessions |
| --- | --- | --- | --- | --- |
| Active | Normal lifecycle state | Until changed | Entire account | Remain usable |
| Inactive | Account lifecycle decision | Until reactivated | Entire account | Revoked |
| Suspended | Administrator security action | Until unsuspended | Entire account | Revoked |
| Credential lock | Automatic failed-password protection | Until `locked_until` or recovery | New local-password authentication and password changes | Remain usable |

The UI may display **Temporarily locked until ...** as a derived credential
condition, but `locked` must not be added to `users.status`. An administrator
who needs an indefinite manual restriction must suspend the user.

## 3. Lifecycle API and UI

The API provides explicit lifecycle operations:

```text
POST /api/v1/users/{id}/activate
POST /api/v1/users/{id}/deactivate
POST /api/v1/users/{id}/suspend
POST /api/v1/users/{id}/unsuspend
```

Valid transitions are:

```text
active    --deactivate--> inactive
active    --suspend-----> suspended
suspended --unsuspend---> active
suspended --deactivate--> inactive
inactive  --activate----> active
```

Calling an endpoint from an incompatible state returns `409 Conflict`. Every
operation requires the current version through `If-Match` and a non-blank change
reason.

`users.status` is a read-only generated projection derived from
`date_deactivated` and `date_suspended`; it is retained for stable query and API
contracts but is never written independently. Generic user updates must not
accept `status`, `date_deactivated`, or `date_suspended`. Lifecycle
state may be changed only through these endpoints so session revocation and
audit behavior cannot be bypassed.

The user-administration UI must display distinct Activate, Deactivate, Suspend,
and Unsuspend actions as applicable. It must distinguish Active, Inactive,
Suspended, and derived Temporarily locked conditions.

## 4. Purpose of `login_sessions`

`login_sessions` is an operational security table. Its purposes are to:

- resolve an opaque session token to an authenticated user;
- store only hashes of session and CSRF secrets;
- enforce sliding idle and absolute expiry;
- record recent activity needed for idle-expiry enforcement;
- support immediate revocation of one or all sessions;
- show users and administrators current and recently terminated sessions; and
- provide short-term client, IP-address, expiry, and revocation information for
  security operations.

The table is not the permanent authentication ledger. Session rows may be
deleted with their user and may be removed after a configured retention period
once they are expired or revoked.

## 5. Durable authentication history

### 5.1 Authority

`event_history` is the immutable, durable authentication audit trail. It must
remain intelligible after a session row or user row has been deleted.

Authentication events must never include a plaintext password, password hash,
session token, session-token hash, CSRF token, or CSRF-token hash.

### 5.2 Required metadata

Subject to the field being available, authentication-event metadata must include
the following security-safe context:

| Metadata field | Requirement |
| --- | --- |
| `session_id` | Required for events concerning an established session |
| `client_ip` | Required when the request supplies a valid client address |
| `user_agent` | Required when supplied; length must be bounded |
| `session_created_at` | Required for terminal session events |
| `last_seen_at` | Required for terminal session events |
| `expires_at` | Required for successful authentication and terminal session events |
| `absolute_expires_at` | Required for successful authentication and terminal session events |
| `revoked_at` | Required for session-revocation events |
| `revocation_scope` | Required for revocation: `current`, `individual`, or `all` |
| `revocation_reason` | Required when caused by lifecycle or credential administration |
| `sessions_revoked` | Required for summary operations affecting multiple sessions |
| `failed_attempt_count` | Required for a failed authentication against a known credential |
| `lock_applied` | Required for failed authentication; boolean |
| `locked_until` | Required when a credential lock is applied |

IP addresses and user-agent values are security audit data and may contain
personal information. Access to them must be restricted to authorized security
or system administrators. Proxy-derived addresses may be accepted only from
explicitly trusted proxies.

### 5.3 Event semantics

- `AUTHENTICATION_SUCCEEDED`: one event for each successful authentication,
  including session ID, client context, and initial expiry values.
- `AUTHENTICATION_FAILED`: one event for each failed authentication against a
  known account, including client context, failure count, and lock outcome. The
  public response must not reveal whether an account exists.
- `SESSION_REVOKED`: one event for an explicit individual-session revocation,
  containing the final security-safe session snapshot and authenticated actor.
- Bulk revocation caused by revoke-all, suspension, deactivation, password
  change, password reset, or another administrative operation: one summary
  event containing the reason, affected count, and required final session
  information. The lifecycle or password event may serve as the summary only
  when it contains all required metadata.
- `SESSION_EXPIRED`: one terminal event written by cleanup before an expired
  session row is removed. Passing an expiry boundary alone does not create an
  event; cleanup creates it when it observes and removes the row.

The system must not append an event for every authenticated request or every
`last_seen_at` update. The terminal revocation or expiry event captures the
final `last_seen_at`, preserving the session summary without unbounded audit
noise.

## 6. Session revocation

An individual revocation records the exact session. A bulk operation records
its cause and the number and required final details of affected sessions.

Lifecycle and credential operations use these reasons where applicable:

```text
logout
administrator_revocation
user_deactivated
user_suspended
password_changed
password_reset
user_deleted
```

`login_sessions.revoked_by` is a convenient live relationship while both the
session and revoking user exist. It is not authoritative history. Its foreign
key uses `ON DELETE SET NULL`. If the revoking user is deleted, the revocation
event retains the actor user ID, name snapshot, and email snapshot.

## 7. User deletion integration

Deleting a user deletes every login-session row belonging to the user in the
same transaction. Before those rows are removed, the deletion operation writes
a summary authentication event containing the count and required final session
information, using the same correlation context as user deletion.

Deleting session rows does not delete or rewrite existing authentication events.
See the deletion specification for the remaining user-deletion conditions and
cascades.

## 8. Retention and cleanup

### 8.1 Eligibility and initial retention

The initial retention period is 90 days:

- a revoked session becomes eligible 90 days after `revoked_at`; and
- an unrevoked expired session becomes eligible 90 days after the first
  applicable idle or absolute expiry.

Active sessions are never eligible. Retention must be configurable.

### 8.2 Operational implementation

Cleanup is a separate operational command outside FastAPI. Its module is
`backend.services.api.session_cleanup`.

It supports:

- one-shot execution suitable for an external scheduler;
- `--dry-run` without committed events or deletions;
- bounded batches;
- a dedicated `--watch` mode;
- a session-cleanup-specific PostgreSQL advisory lock;
- idempotent overlapping invocation; and
- structured counts and nonzero failure exits.

Production may schedule the one-shot command or supervise exactly one `--watch`
process per logical database. Cleanup must never start from each FastAPI worker.

Commands and configuration are maintained in the central
[Operational Tools Catalogue](../docs/operations.md#6-login-session-cleanup).
Every future operational tool must be added to that catalogue with its
implementation.

### 8.3 Cleanup transaction

For each bounded batch, the worker must:

1. acquire its advisory lock;
2. select eligible rows deterministically with row locking and skip-locked
   behavior;
3. write any missing required terminal event without copying secrets;
4. delete only the rows successfully represented in durable history;
5. commit events and deletions atomically; and
6. report selected, audited, deleted, skipped, and failed counts.

Revoked sessions must already have durable revocation information. Cleanup must
verify or supply the required terminal event before deleting them.

## 9. Configuration

| Setting | Initial default | Meaning |
| --- | --- | --- |
| `AUTH_SESSION_IDLE_MINUTES` | `30` | Sliding idle lifetime |
| `AUTH_SESSION_ABSOLUTE_HOURS` | `12` | Maximum session lifetime |
| `AUTH_LOCKOUT_ATTEMPTS` | `5` | Shared incorrect login/current-password attempts before temporary lock |
| `AUTH_LOCKOUT_MINUTES` | `15` | Temporary credential-lock duration |
| `AUTH_SESSION_RETENTION_DAYS` | `90` | Retention after revocation or effective expiry |
| `AUTH_SESSION_CLEANUP_INTERVAL_SECONDS` | `3600` | Continuous-worker delay |
| `AUTH_SESSION_CLEANUP_BATCH_SIZE` | `500` | Default maximum rows per cleanup pass |

## 10. Acceptance criteria

- The UI and API provide explicit suspend and unsuspend operations.
- Generic user updates cannot bypass lifecycle operations.
- Suspension and deactivation revoke active sessions transactionally.
- Reactivation and unsuspension do not restore revoked sessions.
- Credential lock remains derived from `locked_until`, not `users.status`.
- Login and password-change attempts share a limit across sessions and concurrent requests.
- Cooldown expiry resets failures before the next check; successes and recovery clear them.
- New-password validation and confirmation errors never count as incorrect-current-password attempts.
- Password-change lock responses include localized feedback and `Retry-After` without extending the lock.
- Successful and failed authentication events contain required safe metadata.
- Individual and bulk revocations contain required durable audit information.
- No authentication event contains credential, session-token, or CSRF secrets.
- Cleanup never selects active sessions.
- Dry-run commits neither terminal events nor deletions.
- Cleanup writes or verifies terminal events before atomically deleting rows.
- Cleanup is bounded, advisory-locked, idempotent, and safe under overlap.
- Deleting a user records the session-removal summary before session rows
  cascade and preserves all earlier authentication events.
- Deleting a revoking user may clear live `revoked_by` without losing immutable
  actor attribution.
- Database-backed tests use a newly created disposable PostgreSQL database and
  remove it cleanly after the test run.
