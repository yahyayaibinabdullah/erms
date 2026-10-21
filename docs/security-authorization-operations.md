# Security and authorization operations runbook

This is the operational reference for monitoring, reconciling, backing up, and recovering the authorization subsystem. Commands are read-only unless a step explicitly says otherwise.

For administrator-facing privilege and ACL recipes, see
[Authorization configuration scenarios](security-authorization-scenarios.md).

## Role governance designation and Profiles

Keep **Information-governance role** (`roles.is_information_governance`) on the
Role. A Profile supplies reusable action capabilities; a Role identifies an
organizational responsibility with its own clearance and assigned people. Two
roles can therefore share one Profile while only one is designated for
information governance. Moving the flag to a shared Profile would couple that
designation across every attached role and require Profile duplication when
their responsibilities differ.

Configure the role flag explicitly; do not infer it from a role name, a Profile
name, or assignment of a governance Profile. Changing a Profile can change
capabilities and qualification for operations, but must not implicitly toggle
the role flag. Existing governance checks, clearance requirements, and continuity
safeguards continue to apply. Run reconciliation after relevant configuration
changes as described below. This guidance changes no stored data or access rule.
See the [governance designation rationale](../specs/security-and-authorization-subsystem.md#371-why-governance-status-belongs-to-the-role).

## Daily monitoring

The **Security operations** page requires `audit.view`. It reports a rolling 24-hour aggregate of authorization denials, authentication failures, lockouts, governance bypasses, access explanations, security-level changes, ACL changes, and profile changes. It never returns event snapshots, request bodies, credentials, tokens, component content, or protected resource metadata.

The page also displays a persistent advisory warning whenever any role is assigned
a profile containing every currently defined privilege. This includes the built-in
**All privileges** (`ALL_PRIVS`) profile and any custom profile with the same full
set. `ALL_PRIVS` exists for initial setup, migration compatibility, and testing;
renaming or copying it must not evade the warning. A fully privileged custom
profile presents the same operational risk and should likewise be replaced with a
purpose-specific profile before production use. The warning lists every affected
role, including inactive roles, because the risky configuration remains present
even when a role is not currently effective. This is organizational policy
guidance only: it does not block saving, activation, or deployment.

The role editor repeats this warning directly below the Profile field whenever a
fully privileged profile is selected, so the administrator sees the consequence
before saving. The profile privilege editor also warns as soon as every available
privilege is selected.

Review:

- sudden increases in `AUTHORIZATION_DENIED` or `AUTHENTICATION_FAILED`;
- any `ACCOUNT_LOCKED` cluster;
- unexpected `INFORMATION_GOVERNANCE_BYPASS_USED` activity;
- security-level downgrades and ACL/profile changes; and
- repeated denials for one privilege that may indicate a misconfigured profile or client.

The protected text-indexer authorization surface consists of two catalogue
operations. `content.index.execute` belongs only to the service-only
`TEXT_INDEXER_SERVICE` profile (and the deliberately comprehensive
`ALL_PRIVS` profile); it authenticates the internal worker namespace, while
Phase 2 applies exact live job ID, random lease token, and generation scope to
heartbeat, content, staging, completion, and failure. Credentials are accepted
only under `/api/v1/internal/text-indexing/`, are rate-limited per credential,
and cannot enumerate content. `search.query.debug`
is granted to `ALL_PRIVS`, `SYS_ADMIN`, `INFO_GOV_MGR`, and
`INFO_GOV_OFFICER`; it never grants access to another user's results or permits
raw SQL, plans, vectors, snippets, parameters, or protected metadata in
diagnostics.

The same aggregate is available to monitoring systems:

```sh
PYTHONPATH=. python tools/security_operations.py summary \
  --database-url "$DATABASE_URL" --hours 24
```

## Continuity reconciliation and alerting

The reconciliation endpoint/page requires `authorization.administer`. The command-line equivalent is:

```sh
PYTHONPATH=. python tools/security_operations.py reconcile \
  --database-url "$DATABASE_URL" --fail-on-critical
```

Exit status `2` means at least one critical finding; `0` means no critical finding. Advisory findings do not change the exit status.

Critical conditions:

- zero active users with `authorization.administer` through an effective assignment;
- zero effective highest-clearance information-governance custodians with the complete custody privilege set; or
- an aggregation/record security level above its parent, indicating invariant corruption.

Advisories:

- exactly one authorization administrator; or
- exactly one universal governance custodian.

Policy recommends at least two active person assignees for the highest-clearance universal governance-custodian role in production. This remains an organizational policy, not a system activation block.

Run reconciliation after role, profile, assignment, organization-unit, or security-level administration and before any future permanent deletion operation.

## Explaining access

Use **Why this access?** on an aggregation or record. The current user may explain their own decision. A user with `authorization.explain` may select another person; that action creates `ACCESS_EXPLANATION_VIEWED`.

Read gates in order:

1. effective account/assignment/role/organization ancestry;
2. exact global privilege;
3. maximum effective security clearance;
4. effective resource ACL, or the narrow governance ACL bypass; and
5. resource integrity/state constraints.

Do not attempt to diagnose access by editing production rows directly. Explanation always evaluates live policy without impersonating the subject.

## Backup and restore

Use a `pg_dump` client with the same major version as the PostgreSQL server. Back up the complete database, not only authorization tables: ACLs reference records, aggregations, roles, profiles, and immutable event history.

After restoring into an isolated database, verify at minimum:

- `current_user_can_view_record` and the other authorization predicates exist;
- security levels, privileges, profiles, permissions, dependencies, and ACL grants exist;
- immutable audit actor snapshots remain populated;
- schema migration 038 and the security-event monitoring index exist; and
- no application process points at the restored database until validation succeeds.

The disposable test harness performs this exercise automatically through [backup_restore_authorization.sh](/Users/yahyayai/Offline-Documents/code/erms/database/tests/backup_restore_authorization.sh).

## Recovery scenarios

### Last administrator unavailable

Do not grant privileges by direct SQL during ordinary operations. Restore service through another existing authorization administrator. If none exists, use the separately approved break-glass procedure; no break-glass mechanism is enabled by Phase 11.

### Zero universal governance custodians

Treat as critical. An existing authorization administrator should assign qualified active people to an effective highest-clearance governance role whose profile contains the complete custody privilege set. Investigate the transition in the audit trail.

### Suspected privilege or ACL corruption

1. Make the application read-only at the deployment layer.
2. Preserve the current database and logs.
3. Run reconciliation and export the relevant audit envelopes.
4. Restore the latest verified backup into an isolated database.
5. Compare catalogues, assignments, profiles, security levels, ACL grants, and events.
6. Repair through supported APIs where possible and document approval/reason.
7. Re-run all reconciliation and access explanations before reopening traffic.

## Performance and caching

Phase 11 verifies the monitoring index and a 25-request summary workload within five seconds in the disposable integration environment. Existing relationship-redaction query counts remain bounded.

No authorization decision cache is used. Every request reloads current session, assignment, role, organization ancestry, profile, clearance, and ACL state. This guarantees immediate revocation and avoids invalidation races. Introduce caching only after production measurements demonstrate a need and a separate design specifies transaction-safe invalidation for every contributing entity.
