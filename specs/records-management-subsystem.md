# Records Management Subsystem — Reconstructed Implementation Contract

## 1. Status and purpose

This document describes the records-management behavior that is present in the
repository but is not already governed by another specification. It was
reverse-engineered from the canonical database schema, API schemas and routes,
WebUI behavior, and automated tests on 1 October 2026.

This is an **implementation-derived contract**, not evidence that the behavior
was previously approved as product policy. Each reconstructed requirement is
classified as one of:

- **Observed** — directly enforced or returned by the implementation and
  verified by a test.
- **Structural** — directly enforced by the canonical PostgreSQL schema.
- **Inferred** — the most conservative interpretation needed to connect
  observed behavior. Inferences are called out and require product approval
  before being treated as intentional policy.

No inferred requirements were needed for the core contract below.

## 2. Governing specifications and non-duplication boundary

The following specifications remain authoritative for their respective areas.
This document links to them and does not restate their requirements.

| Concern | Governing specification |
|---|---|
| Classification schemes, classifications, aggregation classification, and retention-rule inheritance | [Classification Scheme Subsystem](classification-scheme-subsystem.md) |
| Classification-led aggregation browsing | [Aggregations: Browse classification](aggregation-classification-browser.md) |
| Classification import and export | [Classification Scheme Import and Export](classification-scheme-import-export.md) |
| Resource medium, vital status, review dates, and physical location | [Resource Medium, Vital Status, Review, and Location](resource-medium-vital-status-review-and-location.md) |
| Security levels, privileges, resource ACLs, information-governance bypass, draft authorization, and placement correction | [Security and Authorization Subsystem](security-and-authorization-subsystem.md) |
| Organizational ownership and initial ACLs | [Organizational Ownership and Default ACLs](organizational-ownership-and-default-acls.md) |
| Organizational workspace behavior and custody transfer | [Organizational Workspaces](organizational-workspaces.md) |
| Legal holds | [Legal Holds](legal-holds.md) and [Legal Holds Implementation Traceability](legal-holds-traceability.md) |
| Retention eligibility and disposition | [Disposition](disposition.md) |
| Component content sets, segmented storage, upload/replacement/download, draft promotion, and cleanup | [Segmented PostgreSQL Digital Content Storage](segmented-postgresql-content-storage.md) |
| Record detail UI and component-management presentation | [Record Detail Page](record-detail-page.md) |
| Component preview and navigation | [Digital Component Preview and Collaboration Roadmap](digital-component-preview-navigation.md) |
| Record, aggregation, and component search | [Full-Text Search](full-text-search.md) and [Advanced Search and Saved Searches](advanced-search.md) |
| Personal favourites | [User Favourites](user-favourites.md) |
| Persistent navigation state | [Persistent Navigation Breadcrumbs](persistent-navigation-breadcrumbs.md) |
| User-visible terminology and localization | [Internationalization and User Preferences](internationalization-and-user-preferences.md) |

If this document and a linked governing specification overlap, the linked
specification controls. The requirements below cover only the residual core:
containment, identifiers and dates, basic lifecycle operations, effective
closure, component metadata and ordering, concurrency, and common event
history.

## 3. Domain model

### 3.1 Aggregation

An aggregation is a managed container that may be a root or a child of exactly
one other aggregation. It may contain child aggregations and records.

The core fields not delegated above are:

| Field | Reconstructed contract |
|---|---|
| `id` | Database-assigned identity. |
| `parent_aggregation_id` | Nullable self-reference; null denotes a root. |
| `aggregation_number` | Required, nonblank, and globally unique. |
| `title` | Required and nonblank. |
| `description` | Optional. |
| `date_created` | Server-assigned when omitted. |
| `date_opened` | Defaults to `date_created` when omitted or explicitly null. |
| `date_closed` | Optional; when present it may not precede `date_opened` or be in the future through the API. |
| `version` | Positive optimistic-concurrency version. |

**RM-AGG-01 (Structural).** The aggregation parent relation shall remain a true
acyclic hierarchy. An aggregation cannot parent itself, and an update cannot
make any descendant its parent.

**RM-AGG-02 (Structural).** Deleting an aggregation with a child aggregation or
record shall fail; containment is not recursively deleted.

**RM-AGG-03 (Observed).** Creating a child aggregation without `date_opened`
shall produce `date_opened = date_created`.

### 3.2 Record

A record is a managed item filed directly in exactly one aggregation. It is not
an unfiled or root-level entity.

The core fields not delegated above are:

| Field | Reconstructed contract |
|---|---|
| `id` | Database-assigned identity. |
| `aggregation_id` | Required aggregation reference. |
| `record_number` | Required, nonblank, and globally unique. |
| `title` | Required and nonblank. |
| `description` | Optional. |
| `date_created` | Server-assigned when omitted. |
| `date_originated` | Defaults to `date_created` when omitted or explicitly null. |
| `version` | Positive optimistic-concurrency version. |

**RM-REC-01 (Structural).** A record cannot exist without a containing
aggregation.

**RM-REC-02 (Observed).** Creating a record for a nonexistent aggregation shall
fail with a conflict response; the implementation does not silently create or
substitute a container.

**RM-REC-03 (Observed).** Moving a record changes its `aggregation_id`; moving a
component independently between records is not supported.

**RM-REC-04 (Structural).** Deleting a record shall cascade to its digital
components and their dependent stored content. Immutable event history remains
independent of the deleted live rows.

### 3.3 Digital component metadata

A digital component is an ordered file representation belonging to exactly one
record. The storage and content lifecycle are governed by the segmented-storage
specification; this section covers only core metadata and ordering.

| Field | Reconstructed contract |
|---|---|
| `id` | Database-assigned identity. |
| `record_id` | Required record reference. |
| `component_order` | Positive integer unique within the record. |
| `file_name` | Required and nonblank. |
| `date_created` | Server-assigned when omitted. |
| `date_originated` | Defaults to `date_created` when omitted or explicitly null. |
| `mime_type` | Required and nonblank. |
| `size_in_bytes` | Required and nonnegative. |
| `checksum_algo` | Required and nonblank. |
| `checksum_value` | Required and nonblank. |
| `version` | Positive optimistic-concurrency version. |

**RM-CMP-01 (Structural).** A digital component cannot exist without its
record, and two components of the same record cannot occupy the same order.

**RM-CMP-02 (Observed).** Component collection responses are ordered first by
record and then by ascending `component_order`.

**RM-CMP-03 (Observed).** A reorder request shall contain every component of
the record exactly once and shall assign exactly the contiguous positions
`1..N`. Duplicate IDs, missing components, foreign components, duplicate
positions, and gaps are rejected atomically.

**RM-CMP-04 (Observed).** After one component is deleted, the remaining
components are renumbered in their prior relative order to the contiguous
positions `1..N`.

**RM-CMP-05 (Observed).** A component may be moved one adjacent position by an
authorized record-scoped operation. The server locks the record's ordered
component set and swaps the two positions atomically, so the client does not
need to download the complete collection. Moving the first component upward or
the last component downward is an idempotent no-op.

**RM-CMP-06 (Observed).** Metadata update may rename or otherwise update a
component, but an attempted change of `record_id` to another record is rejected.

## 4. Containment and hierarchy invariants

The core containment graph is:

```text
Aggregation (root)
└── Aggregation (zero or more levels)
    └── Record
        └── Digital Component (ordered)
```

**RM-HIER-01 (Structural).** Aggregation depth has no implementation-defined
business limit. Cycle prevention, rather than a maximum depth, protects the
hierarchy.

**RM-HIER-02 (Observed).** General list endpoints may be filtered to immediate
children by `parent_aggregation_id` or `aggregation_id`; they do not return a
recursive subtree for those filters.

**RM-HIER-03 (Observed).** When the requested parent/container exists but is
not visible to the caller, its filtered child collection is returned as empty
rather than disclosing whether children exist. Detailed authorization and
redaction rules remain governed by the security specification.

**RM-HIER-04 (Observed).** A read representation distinguishes an actually
absent aggregation parent from a parent relationship redacted by authorization.
For records, a null `aggregation_id` in an API representation means the required
existing relationship was redacted; it does not mean the record is unfiled.

## 5. Core lifecycle operations

### 5.1 Creation

**RM-LIFE-01 (Observed).** Aggregations, records, and digital components expose
create operations. Required business authorization, ownership, classification,
security, medium, holds, and closure checks are defined by the linked
specifications rather than repeated here.

**RM-LIFE-02 (Observed).** A duplicate aggregation number or record number
returns `409 Conflict` with the stable code `duplicate_resource_number` and a
resource discriminator.

### 5.2 Read and collection access

**RM-LIFE-03 (Observed).** Single-resource reads return `404` when the resource
does not exist or is nondisclosed under the authorization policy.

**RM-LIFE-04 (Observed).** Legacy collection endpoints accept `limit` from 1
through 500, defaulting to 100, and a nonnegative `offset`. These endpoints are
an implemented compatibility surface; new tenant-grown UI collections remain
subject to the repository's server-pagination performance contract.

### 5.3 Metadata update and movement

**RM-LIFE-05 (Observed).** Aggregation metadata update supports number, title,
description, and opening date. Record metadata update supports number, title,
description, and originating date. Field-specific governed changes are handled
by their linked specifications.

**RM-LIFE-06 (Observed).** Moving an aggregation changes its parent. Moving a
record changes its containing aggregation. Each move is atomic and cannot
leave a partially changed hierarchy.

**RM-LIFE-07 (Observed).** Moving a child aggregation to root additionally
requires root-creation authority. Destination-side receive permissions and
ownership/custody behavior are governed by the security and ownership
specifications.

### 5.4 Permanent deletion

**RM-LIFE-08 (Observed).** `DELETE` permanently removes an eligible live
aggregation, record, or component; it is not a soft-delete operation.

**RM-LIFE-09 (Observed).** Aggregation deletion is restricted by live children.
Record deletion cascades through component metadata and content. Component
deletion compacts component order. Other deletion blockers—holds, vital status,
closure, disposition, authorization, and referenced governance data—remain
defined by the linked specifications.

## 6. Aggregation closure

This section defines the residual closure mechanics. Disposition consequences
are governed by the disposition specification, while exceptional closed-file
placement correction is governed by the security specification.

### 6.1 Direct and effective closure

**RM-CLOSE-01 (Observed).** An aggregation is directly closed when its own
`date_closed` is non-null.

**RM-CLOSE-02 (Observed).** An aggregation is effectively closed when it or any
ancestor is directly closed. The effective-closure query returns the nearest
closed aggregation in the ancestry, including its identity, number, title, and
closure date.

**RM-CLOSE-03 (Observed).** Closing requires a date no earlier than the
aggregation's opening date and no later than the current time.

### 6.2 Frozen subtree

**RM-CLOSE-04 (Structural and observed).** Effective closure freezes ordinary
state changes throughout the closed aggregation subtree. This includes:

- ordinary aggregation metadata changes and hierarchy changes;
- creating child aggregations or records within the subtree;
- ordinary record metadata changes, moves, and deletion;
- component addition, metadata/content replacement, reordering, and deletion;
- direct mutation of protected content-set or blob rows.

Read, download, and authorized rendition operations remain available; closure
does not itself erase or conceal the resources.

Narrow governed exceptions, including location changes, review-date behavior,
reindexing, and placement correction, are defined only by their linked
specifications.

### 6.3 Reopening

**RM-CLOSE-05 (Observed).** Only a directly closed aggregation may be reopened
by clearing its own `date_closed`. Clearing an ancestor's closure unfreezes a
descendant only when no nearer closure remains.

**RM-CLOSE-06 (Observed).** Reopening requires a nonblank change reason. The
reason is stored with the correlated history event. A request without it
returns `422` with code `reopen_reason_required`.

## 7. Record drafts: residual core behavior

Authorization and content segmentation/promotion are governed by the security
and segmented-storage specifications. The following residual draft behavior is
implemented.

**RM-DRFT-01 (Observed).** A draft is a private, expiring, pre-commit record
package with timestamps and a positive version. The existence of the row means
the draft is open. Successful commit atomically creates the record and deletes
the draft rather than retaining a post-commit draft.

**RM-DRFT-02 (Observed).** Reading or mutating a draft requires it to exist, be
owned by the caller, remain unexpired, and pass the current record-creation
authorization check. An expired draft returns `410 Gone`.

**RM-DRFT-03 (Observed).** Draft metadata may be incomplete while the draft is
open. Ordinary commit requires a destination aggregation, medium, record
number, and title.

**RM-DRFT-04 (Observed).** Draft components use the same positive, unique,
contiguous ordering contract as committed components. Reorder requires the
complete exact component set. Removing one compacts the remaining order.

**RM-DRFT-05 (Observed).** Ordinary commit is atomic: it creates the record,
promotes every complete staged component in order, and removes the draft. If
required fields are missing or any upload is incomplete, no partial record or
component set is committed.

**RM-DRFT-06 (Observed).** Discarding a draft permanently deletes the draft and
its staged components; dependent staged segments are removed by cascade as
defined by the segmented-storage specification.

## 8. Optimistic concurrency and transaction behavior

**RM-CONC-01 (Observed).** Mutable live aggregations, records, and digital
components carry a positive version that is incremented on update.

**RM-CONC-02 (Observed).** Update and delete operations require the expected
version through `If-Match`. A stale version returns a conflict and the attempted
mutation does not partially apply.

**RM-CONC-03 (Observed).** Multi-row operations—including component reorder,
draft commit, record deletion with dependent content, and hierarchy moves—are
transactional. Database constraint or policy failure rolls back the complete
operation and its ordinary audit event.

## 9. Common event history

Feature-specific event requirements remain in their governing specifications.
This section describes the common persistence contract used by aggregations,
records, and components.

### 9.1 Event shape

**RM-HIST-01 (Structural).** Each event stores an event identity and time,
transaction identity, entity type and identity, operation, actor snapshot,
actor type, source, request and correlation identities, before and after state,
changed fields, optional reason, and metadata.

**RM-HIST-02 (Structural).** Ordinary row events use these state shapes:

- `CREATE`: null before-state and populated after-state;
- `UPDATE`: populated before-state and after-state;
- `DELETE`: populated before-state and null after-state.

**RM-HIST-03 (Observed).** Ordinary updates list only changed fields. Creation,
update, and deletion history is committed in the same transaction as the live
change, so rolled-back changes leave no successful row-change event.

### 9.2 Durability and intelligibility

**RM-HIST-04 (Structural and observed).** Event history is append-only. Update,
delete, and truncate operations against history are rejected.

**RM-HIST-05 (Observed).** History survives deletion of the live entity and
retains its before-state, actor name/email snapshot, and available snapshots of
referenced entities so that the event remains intelligible.

**RM-HIST-06 (Observed).** API-originated changes propagate or generate valid
request and correlation UUIDs. The permitted event source is controlled; an
arbitrary client-supplied source is rejected.

**RM-HIST-07 (Observed).** Resource history is returned newest first and remains
readable after deletion, subject to the authorization and nondisclosure rules in
the security specification. Event-history mutation endpoints do not exist.

## 10. API surface covered by this contract

This is an inventory, not a second definition of linked feature contracts.

| Resource | Core implemented operations |
|---|---|
| Aggregations | Create; filtered list; search; read; capabilities; patch; delete; effective closure; history |
| Records | Create; filtered list; search; read; capabilities; patch/move; delete; history |
| Digital components | Metadata create/list/search/read/patch/delete; record-scoped reorder; content operations delegated to the storage spec |
| Record drafts | Create/read/patch/discard; list/add/remove/reorder staged components; ordinary commit; correction commit delegated to the security spec |
| Event history | Filtered list; search; read; resource timelines; no mutation |

## 11. Verification traceability

The table maps each reconstructed requirement group to current implementation
and verification evidence. Line numbers are intentionally omitted because they
are unstable; symbol and test names are the durable trace.

| Requirement | Implementation evidence | Verification evidence |
|---|---|---|
| RM-AGG-01–03 | `database/schema.sql`: `aggregations`, `prevent_aggregation_cycle`, default-date triggers | `database/tests/core_records_management.sql`; `test_aggregation_crud_and_hierarchy` |
| RM-REC-01–04 | `database/schema.sql`: `records` FK and component cascade; `main.py`: `create_record`, `update_record`, `delete_record` | `test_record_crud_and_required_aggregation`; `test_record_deletion_cascades_to_components_and_content` |
| RM-CMP-01–06 | `digital_components` constraints; `main.py`: `_reorder_components`, `move_digital_component`, component CRUD | `test_digital_component_crud_and_order`; `test_committed_components_can_be_reordered_and_removed_without_order_gaps`; `test_component_search_pages_and_single_move_cross_page_boundary` |
| RM-HIER-01–04 | hierarchy constraints; `list_aggregations`, `list_records`; `AggregationRead` and `RecordRead` redaction state | `database/tests/core_records_management.sql`; `test_aggregation_crud_and_hierarchy`; authorization API tests |
| RM-LIFE-01–09 | aggregation, record, and component CRUD routes; database FK actions and duplicate mapping | `test_api.py` CRUD, duplicate, parent-deletion, and cascade tests |
| RM-CLOSE-01–06 | `protect_closed_aggregation_hierarchy`, record/component/blob/content-set closure triggers; `_effective_closure`; aggregation patch | `test_closed_aggregation_makes_its_entire_subtree_immutable` |
| RM-DRFT-01–06 | `record_drafts`, `record_draft_components`; `_open_draft`; draft routes; `commit_record_draft` | `test_record_draft_commits_metadata_and_ordered_content_atomically`; `test_record_draft_component_can_be_removed_and_incomplete_commit_rolls_back`; Phase 8 authorization tests |
| RM-CONC-01–03 | version triggers; `expected_version`; `update_row`; transactional request-scoped connections | CRUD stale-version tests; ACL atomicity tests; draft rollback tests |
| RM-HIST-01–07 | `event_history`; row-history and immutability triggers; request context middleware; history routes | `database/tests/event_history.sql`; `test_api_change_creates_correlated_history`; `test_update_and_delete_snapshots_remain_available`; `test_event_history_is_read_only_and_searchable` |

Primary source locations:

- [`database/schema.sql`](../database/schema.sql)
- [`database/tests/core_records_management.sql`](../database/tests/core_records_management.sql)
- [`database/tests/event_history.sql`](../database/tests/event_history.sql)
- [`backend/services/api/schemas.py`](../backend/services/api/schemas.py)
- [`backend/services/api/main.py`](../backend/services/api/main.py)
- [`backend/services/api/tests/test_api.py`](../backend/services/api/tests/test_api.py)

## 12. Known implementation-contract limitations

These are observations, not new product requirements:

1. The core list endpoints use bounded offset pagination and return bare arrays;
   newer browse/search APIs use stronger server-pagination contracts. New UI
   work must not treat the legacy 100/500-row surface as sufficient pagination.
2. The deprecated generic component-create endpoint can create metadata
   independently of uploaded bytes, leaving content lifecycle state to the
   storage subsystem. Its OpenAPI operation directs callers that need a usable
   file to the upload workflow governed by the storage spec.
3. Direct database constraints are intentionally stronger than API-only
   validation for hierarchy, containment, closure, holds, security, ownership,
   medium, and vital-resource integrity.

Any decision to change these behaviors is a product or compatibility change and
requires an approved specification update before implementation.

### Staged digital-component preview (approved 3 November 2026)

Before creating a record, its owner can preview supported, completed staged
uploads using the existing component viewer. Preview leaves the creation package
unchanged and never commits the record. Current draft ownership, expiry and
`record.create` authority are rechecked for every content request. Saved-record
preview/print/download permissions remain separate after commit. Detailed behavior
and acceptance checks: digital-component-preview-navigation.md §4.
