# Event history subsystem

The ERMS event history subsystem provides an immutable, chronological audit
trail for entity state changes. It currently records every insert, update, and
delete affecting aggregations, records, digital components, users,
organizational units, roles, and user-role assignments.

Event history is not event sourcing: the entity tables remain the source of
current state. History explains who or what changed an entity, when it changed,
which request caused it, and what its state was before and after the change.

## Transactional guarantees

History is written by PostgreSQL `AFTER` triggers in the same transaction as
the entity change:

```text
entity change succeeds + history insert succeeds -> both commit
entity change fails                              -> neither commits
history insert fails                             -> entity change rolls back
```

Because the trigger runs after defaults and `BEFORE` triggers, `after_state`
contains the final row values accepted by PostgreSQL. Changes made through SQL
outside FastAPI are also recorded.

## Table structure

The `event_history` table contains:

| Column | Purpose |
| --- | --- |
| `id` | Monotonic `bigserial` event identifier |
| `occurred_at` | Database time when the event was recorded |
| `transaction_id` | PostgreSQL transaction that contains the change |
| `entity_type` | `aggregation`, `record`, or `digital_component` |
| `entity_id` | Primary key of the affected entity |
| `operation` | `CREATE`, `UPDATE`, `DELETE`, or a future domain event |
| `actor_user_id` | Authenticated application-user identifier, when applicable |
| `actor_name` | Name snapshot captured when the event is written |
| `actor_email` | Email snapshot captured when the event is written |
| `actor_type` | Controlled event-actor category: `user`, `anonymous`, or `automated_process` |
| `source` | Component responsible for the change, such as `api` or `database` |
| `request_id` | Identifier for one API request |
| `correlation_id` | Identifier shared by a larger workflow |
| `before_state` | Complete row state before an update or deletion |
| `after_state` | Complete row state after a creation or update |
| `changed_fields` | Alphabetically ordered names of fields whose values changed |
| `reason` | Optional human-readable reason for the change |
| `metadata` | Optional structured, event-specific context |

Snapshots are JSON objects so historical events remain understandable as the
relational schemas evolve.

### Referenced-entity identity snapshots

Numeric foreign keys remain in `before_state`, `after_state`, and domain-event
metadata for technical traceability. For events created after migration 043,
the database also writes readable identities under
`metadata.reference_snapshots`. Recognized references include profiles,
security levels, classifications and schemes, aggregations, records, roles,
users, and organization units. A snapshot contains the stable information a
person needs to identify the referenced item, such as its code and name/title
or a person's name and email address.

Snapshots are captured when the event is inserted. They do not change when the
referenced row is later renamed or deleted. The Audit Trail uses them to show,
for example, `ALL_PRIVS — All privileges` instead of only `Profile ID 1`.
Domain events also snapshot the affected entity itself when it still exists.

Migration 043 intentionally does **not** backfill older events. Reconstructing
past identities from current rows could misrepresent what was true when an old
event occurred. Older events therefore continue to show their original numeric
references when no reliable historical identity is available.

## Operations and snapshots

### CREATE

```text
before_state = null
after_state  = complete new row
```

### UPDATE

```text
before_state   = complete previous row
after_state    = complete resulting row
changed_fields = only fields whose values differ
```

### DELETE

```text
before_state = complete deleted row
after_state  = null
```

## User-entered reasons in future API designs

For all new API designs, use a JSON request-body field for user-entered reasons,
including change reasons, justifications, and audit explanations. Do not
introduce new uses of `X-Change-Reason` for human-authored text. JSON provides
native Unicode support and makes the field's validation and requiredness
explicit in the endpoint schema and API documentation.

Validate the reason according to the operation's requirements, then pass the
validated Unicode text into the shared audit context before performing the
mutation, so the same reason is persisted in the resulting audit events.

Existing header-based endpoints remain supported for compatibility. Migrating
them to JSON requires a deliberate compatibility plan; this guidance does not
authorize removing or changing an existing endpoint's contract.

## Existing change-reason header encoding

The WebUI sends human-authored `X-Change-Reason` values as UTF-8 bytes.
The API decodes the ASGI Latin-1 header representation back to UTF-8 at the
header boundary, before validation or audit persistence. ASCII is unchanged;
non-UTF-8 legacy input retains its Latin-1 representation. JSON reason fields
are already Unicode and are not decoded again. The existing 2,000-character
limit applies to decoded characters, rather than encoded bytes.

## Request and correlation identifiers

`request_id` identifies one HTTP request. If one request changes several
entities, their events share the same request ID.

`correlation_id` connects multiple requests, jobs, or services participating in
one larger operation. For example, an import request and the background jobs it
creates can have different request IDs but share one correlation ID.

Clients may send valid UUIDs in these headers:

```text
X-Request-ID
X-Correlation-ID
```

The API generates a request ID when one is absent. If no correlation ID is
provided, it initially equals the request ID. Both identifiers are returned in
the response headers. Invalid UUID headers produce HTTP 400.

## Source and actor

`source` identifies the system path responsible for an event. Current values
are:

```text
web_ui   - request originated in the NiceGUI application
api      - request came from another REST client or did not identify a client
database - change executed directly without API request context
```

Approved values also include `bulk_import`, `scheduled_job`,
`background_worker`, `integration`, `migration`, `seeding`, `administrative_tool`, `cli`,
`oidc_sync`, and `directory_sync`.

`migration` is reserved for upgrading an existing database's schema or data to
a newer application version. `seeding` identifies optional reference,
demonstration, or test data loaded after the current schema is installed. Seed
utilities must not describe their events as migrations.

NiceGUI sends `X-Event-Source: web_ui` on every API request. FastAPI validates
this header against the controlled list and defaults an absent header to `api`.
The value describes the originating application or execution channel; all
ordinary application writes still pass through FastAPI as the enforcement
boundary.

Migration 014 changes legacy `api` events to `web_ui` for the documented period
when this development database was operated exclusively through NiceGUI. The
migration records its identifier, previous value, and attribution basis in each
affected event's metadata. Events with source `database` are not changed.

Migration 015 separately identifies the no-op user-management lifecycle events
generated by migration 009 and reclassifies their source from `database` to
`migration`. Genuine direct-SQL provisioning remains `database`. Future data
migrations that intentionally mutate audited entities should set transaction
context `app.event_source` to `migration` before making those changes.

### Actor type versus account type

`actor_type` describes **how an event was caused**. It is intentionally separate
from `users.account_type`, which describes **what kind of stored user identity
exists**.

The controlled audit actor values are:

```text
user              - an authenticated stored identity; actor_user_id is present
anonymous         - an unauthenticated request
automated_process - work performed without a stored user identity
```

An authenticated person account and an authenticated service account both
produce `actor_type: user`, because both resolve to a row in `users` and can be
identified by `actor_user_id`. The associated user snapshot and account data
can distinguish the two when necessary.

`automated_process` is used for migrations, the bootstrap provisioning utility,
direct database operations, scheduled internal work, or similar activity that
has no corresponding authenticated user row. `source` then identifies the
channel, such as `migration`, `administrative_tool`, `database`, or
`scheduled_job`.

Authenticated API changes take `actor_user_id` from the validated server-side
session, never from an arbitrary request body. Unauthenticated activity uses
`actor_type: anonymous`; direct database changes without application context
default to `actor_type: automated_process`.

Migration 018 replaces the former ambiguous audit value `system` with
`automated_process`, backfills existing events, changes database defaults and
event-writing functions, and constrains future values to the controlled set.
Each changed historical event records the terminology migration and previous
value in metadata.

For an application-user actor, `actor_name` and `actor_email` are copied from
the validated principal into the event at creation time. They are historical
snapshots, not live joins to `users`: later renaming, deactivation, or hard
deletion of the user cannot make an existing event's actor unintelligible.
Migration 013 initialized these columns on pre-existing events from the current
user row available at migration time. Future events capture the identity at the
actual event time.

### Retrospective legacy attribution

Migration 012 attributes events recorded as anonymous before authentication was
available to the agreed administrator account `y.abdullah@sa.gov.ae`. Each
affected event receives `actor_type: user`, that user's database ID, and an
`actor_attribution_backfill` metadata object recording the migration, email, and
basis for the retrospective attribution. Event identity, time, operation,
request context, entity snapshots, and changed fields remain unchanged.

This is an explicit historical correction based on the project's known
single-user development period; it is not a general rule that anonymous events
belong to a later administrator.

## Reason and metadata

Clients can attach a reason of at most 2,000 characters to a state-changing API
request:

```text
X-Change-Reason: Transferred to the Legal Department
```

The same reason is applied to every event generated by that request.

`metadata` is reserved for structured context that applies to particular event
types. Examples include import batch IDs, scheduled-job IDs, policy IDs, and
external ticket numbers. Important frequently queried properties should become
dedicated columns. Secrets, authentication tokens, and file content must never
be stored in metadata.

## Immutability

PostgreSQL triggers reject `UPDATE`, `DELETE`, and `TRUNCATE` operations against
`event_history`. The REST API exposes no mutation endpoint for history.

Database owners and superusers can disable triggers, so operational immutability
also depends on restricted administration, durable backups, and potentially a
future append-only external archive or signed periodic checkpoints.

## REST API

### List events

```text
GET /api/v1/event-history
```

Optional equality filters are `entity_type`, `entity_id`, `operation`,
`request_id`, and `correlation_id`. `limit` defaults to 100 and is capped at
500; `offset` defaults to zero. Results are newest first.

Example:

```text
GET /api/v1/event-history?entity_type=record&entity_id=42
```

### Retrieve one event

```text
GET /api/v1/event-history/{event_id}
```

### Entity timelines

```text
GET /api/v1/aggregations/{aggregation_id}/history
GET /api/v1/records/{record_id}/history
GET /api/v1/digital-components/{component_id}/history
```

Timelines remain available after an entity has been deleted because event rows
do not have foreign keys back to current entity rows.

### When a record or aggregation changes type

An auditor opens the history of a record now filed as **Correspondence**. It was previously filed as **Investigation**. The auditor may read the resource and its history and has See on Correspondence alone. The timeline identifies both types and the date of the reassignment. On the Investigation side it indicates that values were withheld. It does not reveal the former subject, a stored choice ID, or the label of the selected choice. On the Correspondence side the auditor can read the saved values.

| Viewer’s current access | What the viewer can read |
| --- | --- |
| May read the resource and its history, with See on B alone | A → B and the values on B’s side. A’s values are marked as withheld. |
| May read the resource and its history, with See on A and B | The transition and both sides’ values, subject to existing clearance checks. |
| Qualifying information-governance role | That role can satisfy See on either side where its own clearance is sufficient. The other history and resource gates still apply. |
| Lacks access to the current resource or its history | The resource timeline is unavailable. An otherwise authorized system-wide audit viewer receives the existing redacted event envelope. |

If the resource later moves to a third type, the same rule applies to the earlier event. A viewer with history access and See on Archive alone can read the Investigation → Correspondence transition. Both sides are marked as withheld. Granting that viewer See on Investigation reveals only the Investigation values.

A type name explains why the current record has a different set of fields. A stored value describes that individual record. The same distinction applies to aggregations, including when a later permission change makes older values visible or withdraws access. Granting See on Investigation lets the auditor read the earlier values on the next request. Revoking it withholds them again. Neither change rewrites the event. The stored evidence remains subject to the normal retention and destruction rules. [Approved history rule](../specs/aggregation-and-record-types.md#historical-values-after-reassignment--approved-19-november-2026)

### Advanced search

```text
POST /api/v1/event-history/search
```

This endpoint uses the controlled JSON grammar described in
[`search-grammar.md`](search-grammar.md). Searchable event fields are:

```text
id, occurred_at, transaction_id, entity_type, entity_id, operation,
actor_user_id, actor_type, source, request_id, correlation_id, reason
```

Example:

```json
{
  "where": {
    "and": [
      { "field": "entity_type", "operator": "eq", "value": "record" },
      { "field": "entity_id", "operator": "eq", "value": 42 },
      { "field": "operation", "operator": "in", "value": ["UPDATE", "DELETE"] },
      { "field": "occurred_at", "operator": "gte", "value": "2026-01-01T00:00:00Z" }
    ]
  },
  "sort": [
    { "field": "occurred_at", "direction": "desc" }
  ],
  "limit": 100,
  "offset": 0
}
```

Snapshot and metadata JSON are intentionally not generally searchable yet.
Targeted operators and indexes should be introduced only for demonstrated audit
or reporting requirements.

## Frontend UI

The NiceGUI application exposes event history in two read-only views:

- **Audit trail** in the left navigation shows the system-wide timeline. It can
  be filtered by entity type and ID, operation, source, actor type, date range,
  and correlation ID.
- **Event history** actions on entity rows and detail views open a timeline for
  that particular aggregation, record, digital component, organizational unit,
  role, or user.

Select an event to inspect its before and after values, changed fields, actor,
source, reason, request and correlation identifiers, transaction identifier,
and metadata. The UI deliberately provides no edit or delete controls because
the event history is immutable. Timeline entries identify entities using their
business identifier and name or title, and provide navigation to an entity that
still exists. A **Correlation group** heading groups events created by the same
request or coordinated operation.

For events attributed to an application user, the Audit Trail displays the
event's immutable `actor_name` and `actor_email` snapshots in both the timeline
and event detail dialog. It does not depend on the current user row, and the
numeric foreign key is not presented as the user-facing identity.

User-role assignment events also preserve an `assignment_parties` object in
`metadata`. It contains a snapshot of the assigned user's ID, name, and email,
and the assigned role's ID, code, and name. The Audit Trail therefore displays
an assignment as, for example, `Yahya Yai Abdullah (y.abdullah@sa.gov.ae) →
SYS-ADMIN — System Administrator`, rather than `User #4 — Role #3`.

These are event-time snapshots, not live joins. Later renaming or hard deletion
of either party cannot make the historical assignment unintelligible. Migration
016 backfills the snapshots for existing assignment events from the user and
role rows present when the migration is run.

## Adding future audited entities

PostgreSQL has no global row trigger covering every table. Each future entity
must explicitly register the reusable trigger:

```sql
CREATE TRIGGER example_entities_record_history
AFTER INSERT OR UPDATE OR DELETE ON example_entities
FOR EACH ROW EXECUTE FUNCTION record_entity_history('example_entity');
```

Tests for every new subsystem should verify that creation, update, deletion,
rollback, and actor/request context behave correctly.

## Future domain events

Aggregation reopening is currently represented by the authoritative automatic
`UPDATE` event rather than a second domain event. A successful reopen has
`date_closed` in `changed_fields` and must contain a non-blank `reason`. This
avoids recording two history entries for one state change. A future dedicated
`REOPEN` event would replace, not duplicate, that representation.

The schema permits operations beyond the three automatic row-change events.
Potential domain events include:

```text
MOVE
CLOSE
RECLASSIFY
DECLARE_AS_RECORD
VIEW
DOWNLOAD
PERMISSION_GRANTED
PERMISSION_REVOKED
RETENTION_DISPOSITION
```

Domain events will be appended through controlled database functions rather
than direct client writes. Activity events such as `VIEW` and `DOWNLOAD` must be
recorded explicitly because they do not modify an entity row and therefore
cannot be detected by row triggers.

## Localized operation names

`frontend/webui/event_labels.py::EVENT_MESSAGE_KEYS` is the shared WebUI
presentation catalogue for the 52 event codes currently emitted by the API and
canonical schema. Audit Trail filters, timelines, event details, resource
history, and Security Operations resolve those keys in the current session's
language. The friendly text is maintained in the standard English and Arabic
translation catalogues and Translation Administration.

Operation codes remain unchanged in stored events, API payloads, filter values,
and diagnostic tooltips. Unrecognized historical or integration codes are
shown verbatim rather than assigned a potentially misleading translation.
When adding an event emitter, add its display key and maintained-language
translations to this catalogue. The emitter-coverage test checks literal SQL
and Python event emitters and the Security Operations subset; dynamically
selected operation names must also be reviewed when their emitter changes.
