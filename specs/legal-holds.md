# Legal Holds — Technical Specification

**Status:** Approved for implementation  
**Approved:** 22 September 2026  
**Prepared:** 22 September 2026  
**Project:** ERMS / Wathiq  
**Revision:** 1.1

**Notification extension approved:** 3 October 2026

## 1. Purpose

This specification introduces legal holds in Wathiq. A hold identifies
aggregations and records that must be preserved for a legal, regulatory,
investigative, audit, or similar matter.

While a hold is effective, every resource directly assigned to it—and every
resource below an assigned aggregation—is protected from deletion and future
disposition. A hold may additionally freeze ordinary and governed resource
metadata changes, subject to narrow security and operational exceptions. A
resource may be protected by several holds at once.

The feature must be enforced consistently by PostgreSQL, the REST API,
capability responses, search and browse results, and the NiceGUI client. UI
hiding or validation alone is not sufficient.

## 2. Scope

### 2.1 Included

- create, view, update, and delete hold definitions;
- assign aggregations and records directly to one or more holds;
- remove a direct assignment from one hold or all holds;
- derive hold protection through the aggregation hierarchy;
- protect held resources from deletion and future disposition;
- optionally prevent ordinary and governed resource metadata changes;
- hold indicators and effective-hold details on aggregation and record UIs;
- a filterable, sortable, pageable held-items table on the hold detail page;
- privilege, authorization, capability, concurrency, and non-disclosure rules;
- immutable event history and proposed domain event types; and
- database, API, authorization, and UI test requirements.

### 2.2 Excluded

- the disposition workflow itself;
- notifications, acknowledgements, custodian questionnaires, legal discovery,
  export, collection, review, or production workflows;
- automatic held-item management based on search criteria;
- holds on digital components independently of their record;
- hold approval or multi-stage release workflows;
- scheduled jobs that copy effective status onto resource rows; and
- deleting resources merely because the final hold expires or is released.

## 3. Terminology and effective-time rule

### 3.1 Hold

A hold is a named preservation instruction with a stable code, description,
effective period, owner, designated contributors, and an optional enhanced
resource-state preservation policy.

### 3.2 Direct assignment

A direct assignment is an explicit relationship between a hold and one
aggregation or record. It remains stored when the hold is future-dated or
expired.

### 3.3 Inherited protection

An aggregation or record is indirectly protected when an ancestor aggregation
has a direct assignment to an effective hold. Inheritance follows the current
aggregation hierarchy at evaluation time; it is not copied to descendants.

### 3.4 Effective hold

All hold times are stored as `timestamptz`, compared using database/server
time, and exposed as ISO 8601 timestamps. A hold is effective at time `t` when:

```text
valid_from <= t AND (valid_to IS NULL OR t < valid_to)
```

The interval is deliberately half-open: `valid_from` is inclusive and
`valid_to` is exclusive. A null `valid_to` means the hold has no scheduled end.
Clients must not determine authority from their own clocks.

UI labels are:

| State | Rule |
| --- | --- |
| Scheduled | server time is before `valid_from` |
| Active | the effective-hold expression is true |
| Expired | `valid_to` is non-null and server time is at or after it |

There is no separately stored active flag. Changing either date may schedule,
activate, expire, or reactivate a hold immediately.

## 4. Functional rules

1. A resource may be directly assigned to any number of holds.
2. Assigning the same resource to the same hold twice is idempotent at the API
   boundary and impossible as duplicate database rows.
3. An effective direct assignment to an aggregation protects that aggregation,
   every descendant aggregation, and every record in that subtree.
4. An effective direct assignment to a record protects only that record and
   its components; it does not protect its parent or siblings.
5. Protection is the union of all effective direct and inherited holds.
6. Removing one assignment does not remove protection supplied by another
   direct assignment or an ancestor.
7. Expired and scheduled holds do not currently restrict resources and are not
   shown in a resource's effective-holds panel.
8. A hold cannot be deleted while it has any direct assignment, regardless of
   whether it is scheduled, active, or expired. The assignments must first be
   explicitly removed.
9. Deleting a hold never cascades to resources or silently removes held-item management.
10. Hold protection never grants access to a resource and never bypasses
    security clearance, ACL, lifecycle, or other integrity rules.

### 4.1 Hierarchy changes

Because inheritance is evaluated against the current hierarchy:

- moving an aggregation into a held subtree immediately protects its entire
  subtree;
- moving an aggregation out removes only the protection inherited from its old
  ancestors;
- moving a record into or out of a held aggregation similarly changes its
  inherited protection; and
- direct assignments move with their resources.

A state-preserving hold creates a special implication: an ordinary move
changes governed containment, not merely display metadata, but moving a held
resource out of scope could circumvent preservation controls. Therefore:

1. A resource that is protected by any effective hold must not be moved unless
   the caller has the ordinary move authorization and may manage held-item management for
   every effective hold whose coverage would change because of the move.
2. If any applicable effective hold has `preserve_resource_state = true`, the
   move is prohibited; the extra held-item management authority is not an override.
3. The move must not remove any **direct** hold assignment.
4. Moving into or out of inherited coverage is allowed with those authorities
   and produces a `HELD_RESOURCE_MOVED` domain event containing the effective
   hold IDs before and after the move.
5. A move is still rejected by closure, security-envelope, medium, ownership,
   or other independent rules.

This rule makes deliberate reorganization possible without letting ordinary
`aggregation.move` or `record.move` holders evade legal preservation.

## 5. Enhanced resource-state preservation

Every hold has `preserve_resource_state`, labelled **Preserve resource metadata
and state** in the UI. If at least one effective hold enables it, both ordinary
and governed resource metadata and lifecycle state are frozen, except for the
narrowly defined safety/control-plane operations below. The most restrictive
applicable hold wins.

The authoritative operation matrix is:

| Operation class | Any effective hold | Effective hold preserving resource state |
| --- | --- | --- |
| Delete or dispose aggregation/record | Blocked | Blocked |
| Add, replace, remove, or reorder a digital component | Blocked | Blocked |
| Ordinary aggregation/record metadata (`modify`) | Allowed by normal authorization | Blocked |
| Close/reopen, classification, vital status, review date | Allowed by normal authorization | Blocked |
| Move aggregation/record | Allowed only under Section 4.1 | Blocked |
| Security-level change | Allowed by normal authorization | Allowed |
| ACL administration | Allowed by normal authorization | Allowed |
| Exceptional ownership correction | Allowed by normal authorization | Allowed |
| Aggregation location change | Allowed by normal authorization and fully audited | Allowed |
| Hold assignment/removal and hold administration | Allowed by Sections 7–9 | Allowed |
| View, download, share, or print | Allowed by normal authorization | Allowed |

For ordinary aggregation closure, a hold without `preserve_resource_state`
does not prevent closing the aggregation. If an applicable effective hold
enables that flag, closing is blocked as a lifecycle-state change. This rule
applies independently of disposition acceleration. Vital status by itself
also does not prevent closure; normal close authorization and date validation
still apply. Closing never removes a hold or clears vital status, and their
disposition protections remain in force.

The enhanced option covers governed operations because their separate
privileges describe **who may normally perform them**, not whether performing
them is compatible with a preservation instruction. Close/reopen changes the
resource's lifecycle state; classification and vital-status changes alter its
governance meaning; review-date changes alter its governance schedule; and a
move changes its filing context and inherited policy. Permitting those actions
would let a privileged user materially alter the identity, context, or
lifecycle of evidence while the UI claimed it was preserved. It would also
make the option difficult to explain and audit because “metadata” would mean
only fields handled by a general edit form rather than all substantive
resource state. Blocking them provides a stable evidentiary snapshot, a clear
most-restrictive-hold-wins rule, and consistent API, database, UI, and Access
Explainer behavior.

Security-level and ACL changes remain possible because a legal hold must not
force Wathiq to preserve an accidental information exposure. Exceptional
ownership correction remains possible for the same access-control and custody
reason. Location changes remain possible because Wathiq must record actual
physical custody accurately; freezing a stale location would weaken rather
than preserve accountability. These exceptions change control-plane or
operational-truth metadata, not the held record's substantive identity or
content, and retain their dedicated authorization and audit requirements.

All digital-component mutations—add, replace, remove, and reorder—are blocked
whenever the record is protected by any effective hold, even if
`preserve_resource_state` is false. Download, sharing, and printing do not
mutate the held record and remain governed by their existing privileges. They
must not be blocked merely because a hold applies: authorized access and
production are necessary for legal discovery and are common reasons for
creating a hold. The future disposition subsystem is always blocked by an
effective hold.

### 5.1 Special implementation implications

The exception for separately governed metadata has these consequences:

1. The implementation cannot use a blanket rule that rejects every `UPDATE`
   to `aggregations` or `records` while frozen because the safety/control-plane
   exceptions must remain possible.
2. Each mutable field must belong to an explicit operation class. New fields
   default to ordinary metadata, and therefore frozen, until a specification
   assigns them to a separately governed action.
3. General `PATCH` endpoints must reject governed fields or route them through
   the existing dedicated authorization paths. A caller must not smuggle a
   governed change into an ordinary update.
4. Database enforcement needs transaction-local authorization markers for the
   approved safety/control-plane action, following Wathiq's existing governed-
   action pattern. The trigger must permit only the columns belonging to that
   marked action.
5. One request that mixes frozen fields with permitted control-plane fields
   must fail atomically; it must not partially apply the permitted subset.
6. Effective holds and field classification must be rechecked under row locks
   in the write transaction to avoid a race with hold activation, date edits,
   assignment, removal, or resource movement.
7. Background jobs, imports, integrations, and direct SQL are subject to the
   same database restriction. There is no implicit system-administrator or
   information-governance bypass.

## 6. Data model

### 6.1 `holds`

| Column | Requirement |
| --- | --- |
| `id` | `bigserial` primary key |
| `code` | required, trimmed, maximum 100 characters, case-insensitively unique |
| `name` | required, trimmed, maximum 300 characters |
| `description` | nullable text, maximum 4,000 characters |
| `valid_from` | required `timestamptz` |
| `valid_to` | nullable `timestamptz`, strictly later than `valid_from` |
| `owner_user_id` | required FK to `users(id)` using `ON DELETE RESTRICT` |
| `preserve_resource_state` | required Boolean, default `false` |
| `date_created` / `date_updated` | required `timestamptz` |
| `version` | positive integer for optimistic concurrency |

The owner is the principal contact and accountable person for the hold. The
owner must be a person account. A newly selected owner must be active at write
time. Later deactivation does not invalidate the hold: the UI shows the owner
as inactive and hold administrators must appoint a replacement. Hard deletion
of an owner is blocked while referenced. Service accounts, roles, and
organizational units cannot be owners.

Codes are stable business identifiers. Changing a code is permitted to a hold
administrator in this draft but is audited; integrations must use `id` as the
immutable identity. A code change requires uniqueness validation, optimistic
concurrency, and a mandatory reason.

### 6.2 `hold_contributors`

```text
id, hold_id, user_id, date_created, version
UNIQUE (hold_id, user_id)
```

Both the hold and user foreign keys use `ON DELETE CASCADE`. A contributor is a
revocable delegation, not an integrity dependency of the hold, so an otherwise
permitted hard deletion of the user must not be blocked by either an active or
expired hold. The cascade removes only that user's contributor designation; it
does not alter the hold, its owner, its other contributors, or its resource
assignments.

A contributor must be an active person account when added. Later deactivation
makes the contributor ineffective for held-item management actions but preserves the
designation until a hold administrator removes it or the user is deleted. The
owner must not also be stored as a contributor: ownership already supplies the
same hold-specific eligibility, and the API rejects that duplicate
designation. Service accounts, roles, and organizational units cannot be
contributors.

The cascaded contributor deletion must produce the ordinary immutable
`hold_contributor` deletion history with the request actor, request/correlation
IDs, and user/hold identity snapshots. User-deletion preflight reports affected
contributor designations as informational cascades, not blockers. The required
`holds.owner_user_id` reference remains `ON DELETE RESTRICT`; an owner must be
replaced before that user can be hard-deleted.

Owner or active-contributor designation is the hold-specific authority to add
and remove resources from that hold. Neither relationship grants visibility of any
aggregation or record, security clearance, or resource ACL permission. Normal
resource authorization remains independently mandatory for every candidate.

Only `holds.administer` may change the owner or contributor roster. Updating
the roster uses hold optimistic concurrency and is audited. A hold administrator
may also manage held items. Users with `holds.held_items.manage_all` may change
held-item management on every hold without being appointed as its owner. The built-in
Information Governance Manager and Information Governance Officer profiles
include `holds.held_items.manage_all` by default.

### 6.3 `hold_aggregation_assignments`

```text
id, hold_id, aggregation_id, assigned_at, assigned_by_user_id, version
UNIQUE (hold_id, aggregation_id)
```

The hold foreign key uses `ON DELETE RESTRICT`; the aggregation foreign key
uses `ON DELETE CASCADE`. The effective-hold deletion trigger prevents the
cascade while protection applies. After all applicable holds expire, resource
deletion may proceed and removes the now-nonprotective assignment in the same
transaction, with its deletion captured in event history. The assignment actor
is retained as a nullable historical reference if Wathiq's user-deletion policy
requires it; event history remains the authoritative actor snapshot.

### 6.4 `hold_record_assignments`

```text
id, hold_id, record_id, assigned_at, assigned_by_user_id, version
UNIQUE (hold_id, record_id)
```

The hold foreign key uses `ON DELETE RESTRICT`; the record foreign key uses
`ON DELETE CASCADE`, for the same effective-protection and audit behavior as an
aggregation assignment. The assigning actor uses the same treatment.

Separate typed tables are preferred over one polymorphic table because they
provide real foreign keys, simple uniqueness, safe delete restrictions, and
clear query plans.

### 6.5 Derived state

Do not store `is_on_hold` or copy inherited assignments onto descendants.
Effective state is derived from assignments, the current hierarchy, and server
time. Central SQL functions/views must provide one authoritative calculation,
including:

```text
effective_holds_for_aggregation(aggregation_id, at_time)
effective_holds_for_record(record_id, at_time)
resource_has_effective_hold(resource_type, resource_id, at_time)
resource_state_changes_blocked(resource_type, resource_id, at_time)
```

Each effective-hold result identifies the hold and whether the path is
`direct`, `inherited`, or both, plus the nearest directly assigned ancestor
when inheritance applies. One hold appears only once per resource even when
several ancestors are directly assigned to it.

### 6.6 Indexes

At minimum:

- case-insensitive unique index on `holds.code`;
- indexes on `(valid_from, valid_to)` suitable for effective-state filtering;
- unique and reverse-lookup indexes for hold contributors;
- both directions of each held-item assignment relation;
- aggregation ancestry indexes already used by hierarchy traversal; and
- partial or covering indexes justified by query plans for the hold detail and
  resource indicator queries.

## 7. Privileges and authorization

Add this global privilege in category `administration`:

| Privilege | Meaning |
| --- | --- |
| `holds.administer` | Create, update, and delete empty holds |
| `holds.held_items.manage_all` | Add or remove resources from any hold |

No separate `holds.view`, `holds.held_items.manage`, or hold ACL is required.
Hold visibility and held-item management authority are derived from the hold relationship
and the governance rules below. This avoids requiring two independent grants
for a delegation that the hold administrator already makes explicitly and
audits when appointing an owner or contributor.

### 7.1 Hold visibility

There is no ACL on a hold. A user may view the complete hold definition and its
authorized held-item rows when any of these is true:

- the user is the hold's owner;
- the user is an active contributor;
- the user has `holds.administer`; or
- the user has `holds.held_items.manage_all`; or
- any of the user's effective roles is an information-governance role.

Information-governance visibility is universal across holds. Held-item management authority
is granted separately through the built-in profiles' `holds.held_items.manage_all`
privilege so custom information-governance roles may remain visibility-only.

Every held-item list is filtered through resource visibility: the viewer sees
only aggregations and records they are independently authorized to view.
Counts must likewise be authorized counts or be omitted, so hidden resources
are not leaked. Hold administration, ownership, contribution, and governance
status never grants resource clearance or ACL access.

Other users who can view a protected resource see only a generic **Protected
by an effective hold** state restriction. They do not receive the hold's code,
name, description, owner, contributors, dates, assigning ancestor identity, or
a link to the hold detail.

### 7.2 Held-item management authorization

Adding or removing a resource requires all of:

1. the caller is the hold's active owner, an active contributor, has
   `holds.administer`, or has `holds.held_items.manage_all`;
2. current authorization to view the resource, including clearance;
3. the resource's type-specific view privilege and ACL permission (or the
   existing information-governance ACL bypass); and
4. optimistic-concurrency and integrity checks.

Held-item management intentionally does not require `record.modify` or
`aggregation.modify`, because it is a separate governed action. It is not
blocked by the hold's own resource-state preservation option.

A remove-all request is atomic and succeeds only if the caller may manage the
held-item management of every direct hold assignment it would remove. It must not silently
skip unauthorized assignments. The UI offers
remove-all only when the caller is eligible for all affected direct holds;
otherwise it offers per-hold removal for the eligible subset.

## 8. Enforcement and concurrency

### 8.1 Authoritative database enforcement

PostgreSQL triggers must reject, at minimum:

- deletion of any aggregation protected directly or through an effective hold;
- deletion of any descendant subtree containing a protected resource;
- deletion of a held record;
- addition, deletion, replacement, or reordering of a digital component
  belonging to a held record;
- an ordinary or governed metadata update frozen by an effective hold, except
  for the safety/control-plane operations in Section 5;
- deletion of a non-empty hold;
- deletion of an assignment through an unauthorized direct database path; and
- disposal actions against any resource protected by an effective hold when
  the disposition subsystem is introduced.

API authorization is still required; database integrity is the final
non-bypassable boundary. The hold trigger must coexist with vital protection,
closure, retention, security-level, and medium rules. None overrides another.

### 8.2 Locking and race prevention

Mutations must lock the target resource and relevant hold/assignment rows in a
documented order. The following races must resolve safely rather than by last
writer wins:

- assignment versus resource deletion;
- hold date update versus resource mutation;
- assignment removal versus hold deletion;
- ancestor move versus descendant deletion or mutation; and
- owner or contributor change versus user deletion.

An operation authorized while no hold applies must not commit after a
concurrent transaction makes an effective hold applicable without rechecking.
Advisory locks keyed by resource ancestry or a serializable equivalent may be
used if ordinary row locks cannot protect predicate/ancestry changes cleanly.

### 8.3 Failure contract

Integrity failures return `409 Conflict` with a stable machine code and a safe
message. Proposed codes include:

```text
effective_hold_prevents_deletion
effective_hold_prevents_component_addition
effective_hold_prevents_component_deletion
effective_hold_prevents_component_reordering
effective_hold_prevents_component_replacement
effective_hold_prevents_metadata_change
hold_not_empty
hold_assignment_not_found
hold_held_item_manager_required
hold_held_item_management_required_for_held_move
```

Authorization or concealed-resource failures follow the existing non-leaking
`403`/`404` policy. Stale versions use the existing concurrency response.

### 8.4 Mandatory reasons for post-creation changes

Creating a hold does not require a reason, consistent with creation of other
Wathiq entities. Every post-creation hold mutation requires a non-blank reason
of at most 2,000 characters:

- hold update and deletion;
- owner or contributor changes made after creation;
- adding or removing one or more resource assignments; and
- remove-all-direct-assignments operations.

The API accepts the reason through Wathiq's common `X-Change-Reason` mechanism
unless a typed request body is already required for the operation, but the
reason is mandatory rather than optional. Missing or blank reasons fail with
`422` and `hold_change_reason_required`. Bulk operations use one reason for the
atomic request. Cascaded assignment or contributor deletions inherit the
reason from the initiating resource, hold, or user deletion request. Every
ordinary row event and domain event generated by the transaction records the
same reason. `HOLD_CREATED` and its row-creation history may have a null reason.

## 9. REST API

All collection endpoints use server-side filtering, sorting, and pagination.
Default page size is 25 and maximum page size is 100 unless the common API
contract establishes another limit.

### 9.1 Hold definitions

```text
GET    /api/v1/holds
POST   /api/v1/holds
GET    /api/v1/holds/{hold_id}
PATCH  /api/v1/holds/{hold_id}?version={version}
DELETE /api/v1/holds/{hold_id}?version={version}
GET    /api/v1/holds/{hold_id}/history
```

List filters include `q`, `state`, `owner_user_id`, `contributor_user_id`,
`preserve_resource_state`, `valid_from`, and `valid_to`. Supported sort keys
include code, name, state, valid-from, valid-to, owner, created, and updated.

Responses include computed `state`, `is_effective`, `direct_held_item_count` only
when its value can be disclosed without leaking hidden resources, and
capabilities such as `update`, `delete`, `manage_contributors`, and
`manage_held_items` with reason codes. `manage_held_items` is true when the caller is
the hold's active owner or contributor, has `holds.administer`, or has
`holds.held_items.manage_all`; every operation remains subject to per-resource
authorization.

Contributor administration may be represented within hold create/update
payloads or through dedicated endpoints:

```text
GET    /api/v1/holds/{hold_id}/contributors
PUT    /api/v1/holds/{hold_id}/contributors?version={hold_version}
```

Whichever representation is chosen, replacement is atomic, rejects unknown,
inactive, non-person, duplicate, or owner user IDs, and returns the updated
hold version.

### 9.2 Held-item management

```text
GET    /api/v1/holds/{hold_id}/held-items
POST   /api/v1/holds/{hold_id}/held-items
DELETE /api/v1/holds/{hold_id}/held-items/{resource_type}/{resource_id}
```

`resource_type` is `aggregation` or `record`. The first release lists direct
held items only; it does not expand every effectively protected descendant. An
expanded query may be specified in a later release after scale and disclosure
requirements are measured. Each row contains the type, identifier, number,
title, security level if otherwise visible, assignment time, assigning actor
snapshot/reference, and current resource navigation capability.

Single-add is idempotent: an existing assignment returns its current
representation without a second event. Bulk add/remove may be introduced as a
separate endpoint only with per-item validation, atomicity explicitly chosen,
and a shared correlation ID.

### 9.3 Resource hold status and actions

```text
GET    /api/v1/aggregations/{id}/effective-holds
GET    /api/v1/records/{id}/effective-holds
POST   /api/v1/aggregations/{id}/holds
POST   /api/v1/records/{id}/holds
DELETE /api/v1/aggregations/{id}/holds/{hold_id}
DELETE /api/v1/records/{id}/holds/{hold_id}
DELETE /api/v1/aggregations/{id}/holds
DELETE /api/v1/records/{id}/holds
```

The final two endpoints remove **all direct assignments on that resource**.
They cannot remove inherited assignments, because those belong to ancestors.
The response must report any remaining effective inherited holds so “Remove
from all holds” is not misrepresented as “make unheld.” The UI label should be
“Remove all direct hold assignments” when inherited protection exists.

The effective-holds responses exclude expired and scheduled holds and dedupe a
hold reached through several paths. They expose `source`,
`directly_assigned_resource`, `preserve_resource_state`, and the limited or
full hold summary allowed by Section 7.1.

### 9.4 Capability extensions

Aggregation and record capability responses add:

```text
is_on_effective_hold
resource_state_changes_blocked
effective_hold_count
add_to_hold
remove_from_hold
remove_all_direct_hold_assignments
```

Existing ordinary/governed modification, `delete`, `move`, and component-
mutation capabilities must be false when a hold integrity rule blocks them and
include stable reason codes. Capabilities are advisory snapshots; every write
reauthorizes.

### 9.5 Access Explainer integration

`POST /api/v1/authorization/explain` must evaluate effective-hold restrictions
as part of its live **Resource state rules** (`operation_integrity`) gate for
both the current user and another selected subject. At minimum it evaluates:

- aggregation and record deletion;
- ordinary and governed aggregation and record metadata modification;
- aggregation and record movement;
- digital-component addition, removal, replacement, and reordering through
  their containing record;
- held-item management changes; and
- future disposition operations.

The integrity evaluator must use the same centralized effective-hold SQL and
the same operation-to-field classification as the write path. It must not
reimplement an approximate frontend or Python-only version. Its stable details
include:

```text
effective_hold_prevents_deletion
effective_hold_prevents_component_addition
effective_hold_prevents_component_deletion
effective_hold_prevents_component_reordering
effective_hold_prevents_component_replacement
effective_hold_prevents_metadata_change
hold_held_item_manager_required
hold_held_item_management_required_for_held_move
```

For an effective-hold denial, the explanation response adds structured
`resource_state_constraints` (or an equivalent typed field) containing:

- `kind = effective_hold`;
- whether the restriction is direct, inherited, or both;
- the blocked effect (`deletion`, `metadata_change`, `component_addition`,
  `component_removal`, `component_replacement`, `component_reordering`,
  `movement`, or `disposition`);
- the number of applicable effective holds; and
- hold IDs, codes, names, assigning ancestor IDs, and resource-state-
  preservation flags
  only to the extent the **examiner** is authorized to see them.

The examiner's hold-visibility rights control diagnostic detail even when
another user is selected. Unless the examiner is the hold owner, an active
contributor, a hold administrator, or acting through an effective information-
governance role, the response gives a generic effective-hold constraint and no
hidden hold or ancestor identity. The explanation must not imply that the
selected subject could see a hold merely because the examiner can. Existing
`ACCESS_EXPLANATION_VIEWED` auditing continues to apply;
its metadata records that effective-hold constraints were evaluated without
copying confidential hold descriptions.

The NiceGUI Access Explanation dialog renders the failed Resource state rules
gate in business language—for example, “An effective legal hold prevents this
record from being deleted.” When detail is authorized, it shows the applicable
hold code/name, direct or inherited source, and whether enhanced state preservation
caused the denial. It must distinguish an effective-hold denial from closure,
vital-resource, retention, and other state restrictions. The dialog refreshes
the explanation after a hold is added, removed, edited, expires, or becomes
effective; it must not reuse a stale explanation as an authorization decision.
For held-item management operations it separately explains whether the subject has
hold-held-item management authority and whether the subject can view the target resource.
Hold authority cannot compensate for a failed resource-visibility gate.

## 10. User interface

### 10.1 Navigation and hold workspace

Hold owners, active contributors, hold administrators, and users with an
effective information-governance role receive a **Holds** item in the
governance or administration navigation area. Owners and contributors see only
their holds; administrators and information-governance users see all holds.
The workspace uses Wathiq's existing visual design and table conventions.

The hold list supports search, state/owner/contributor/date filters, sortable
columns, server pagination, and create/edit/delete actions according to
capabilities.
Create and edit forms include code, name, description, valid-from, valid-to,
owner, contributors, and **Preserve resource metadata and state**. Dates show timezone
clearly and the form explains the exclusive valid-to boundary in ordinary
language.

### 10.2 Hold detail

The page header shows code, name, state badge, validity, owner, contributors,
resource-state-preservation setting, and description. The held items table is
filterable, sortable, and
pageable, using the application's standard `ui.table` treatment. Columns are:

- type icon and type;
- number;
- title;
- security level when visible;
- assigned at;
- assigned by; and
- **Open** link/action; and
- row actions.

Filters include free text, resource type, assignment date, and assigning user.
The explicit **Open** action navigates to that aggregation or record when the
caller remains authorized; it is hidden or disabled otherwise. Users with
held-item management authority under Section 7.2 receive:

- **Add aggregations or records**, opening an authorized resource picker;
- per-row **Remove from this hold**; and
- multi-select removal after a confirmation that names the hold and count.

The add picker excludes or marks already-directly-assigned resources and never
searches above the caller's visibility. Removing a held item requires a
confirmation because it may release protection. If other effective holds or
ancestor assignments remain, the dialog says the resource will remain held.

Delete is disabled with “Remove all direct held items before deleting this hold”
when any direct held item exists. The server remains authoritative.

### 10.3 Aggregation and record pages

Every visible aggregation and record displays an **On hold** shield/badge when
at least one effective hold applies. No badge is shown for scheduled or expired
holds. Opening the badge displays deduplicated effective holds, distinguishing:

- **Direct** assignment;
- **Inherited from** an ancestor aggregation; and
- **Direct and inherited** when both apply.

For users without full visibility of that hold under Section 7.1, the panel
shows only the generic protection explanation. For authorized users, hold
names link to their details.

Users with held-item management authority under Section 7.2 receive actions to:

- add the resource to a selected hold;
- remove a selected direct assignment; and
- remove all direct assignments.

Inherited holds cannot be removed from the child. The UI links to the assigning
ancestor when it is visible and instructs the user to remove the assignment there.
After every action, both capabilities and effective holds are refreshed.

Blocked ordinary/governed edit, delete, move, component-mutation, and future
disposition controls are disabled or hidden according to normal Wathiq
conventions and explain the hold restriction. The API must still reject forged
or stale requests.

Security Level remains present during resource creation. After creation, Security
Level is not shown in the Edit Metadata form. A separately authorized **Change
security level** action is the consistent UI path whether or not ordinary metadata
editing is blocked by closure or an effective state-preserving hold. It requires a
non-blank reason and uses the security-level preview/apply workflow and its existing
hierarchy, clearance, downgrade, concurrency, and event-history controls.

## 11. Event history

The `holds` and both assignment tables receive ordinary trigger-generated
`CREATE`, `UPDATE`, and `DELETE` row events. Add reference snapshots for holds
(`code`, `name`) and assignment targets (`number`, `title`, type), consistent
with the existing event-history identity-snapshot mechanism.

In addition, use these domain events:

| Operation | Entity timeline | When | Required metadata |
| --- | --- | --- | --- |
| `HOLD_CREATED` | hold | hold created | complete business fields and owner/contributor snapshots |
| `HOLD_UPDATED` | hold | business fields changed | old/new changed values, previous/new effective state |
| `HOLD_CONTRIBUTORS_REPLACED` | hold | contributor roster changed | added/removed user IDs and identity snapshots |
| `HOLD_DELETED` | hold | empty hold deleted | final hold identity and state |
| `RESOURCE_ADDED_TO_HOLD` | hold and resource | direct assignment added | hold/resource snapshots, assignment ID |
| `RESOURCE_REMOVED_FROM_HOLD` | hold and resource | direct assignment removed | hold/resource snapshots, remaining effective hold IDs |
| `ALL_DIRECT_HOLDS_REMOVED` | resource | remove-all action | removed hold snapshots/IDs, remaining inherited effective hold IDs |
| `HELD_RESOURCE_MOVED` | resource | held resource changes parent | old/new parent snapshots, effective hold IDs before/after |
| `HOLD_OPERATION_BLOCKED` | resource or hold | an integrity rule denies mutation | attempted action, applicable hold IDs, stable reason code |

`HOLD_CREATED`, `HOLD_UPDATED`, and `HOLD_DELETED` are proposed semantic names.
To avoid duplicate audit noise, implementation should either suppress ordinary
row history for the same logical change and emit the domain event, as existing
governed actions do, or retain ordinary row events and omit these three. The
preferred Wathiq convention is one human-meaningful domain event per logical
action, while low-level assignment row events may remain for forensic detail.

Adding/removing held-item management must be discoverable from both the hold and resource
history. This may be implemented by two linked events sharing request and
correlation IDs, or by extending history queries to include related-entity
metadata. Two linked events are preferred for simple timeline queries.

Automatic passage of time does **not** create `HOLD_ACTIVATED` or
`HOLD_EXPIRED` events: no database mutation or attributable actor occurs. The
audited dates and `HOLD_UPDATED` event prove why state changed. If the business
requires explicit activation/expiry events, a reliable scheduled job and its
operational semantics must be specified separately.

Denied-event metadata must not contain hidden hold names or resource details.
No record content or secrets may enter event metadata.

## 12. Search, browse, and reporting

Authorized aggregation and record representations may include a compact
`is_on_effective_hold` Boolean for badges and filtering. Search adds filters:

```text
on_effective_hold = true | false
resource_state_changes_blocked = true | false
effective_hold_id = <id>       # only when the caller can fully view that hold
```

Search and counts preserve clearance and ACL filtering. Hold predicates must
not make inaccessible resources discoverable. Effective calculations use one
captured database timestamp per query so a page cannot be internally split at
a validity boundary.

## 13. Performance and scale

The read path must avoid one effective-hold query per result row. Browse and
search queries should obtain badge Booleans/counts in set-based SQL. Hold
details use server-side pagination and must not expand an aggregation's entire
descendant tree merely to list direct held items.

Before release, query plans must be measured on representative deep and broad
hierarchies with multiple overlapping holds. If recursive ancestry becomes a
bottleneck, Wathiq may add a closure table or materialized ancestry structure;
it must not denormalize time-dependent hold state onto every resource.

## 14. Migration and compatibility

1. Add the new tables, constraints, indexes, functions, triggers, privileges,
   reference-snapshot support, and API policy inventory entries to the complete
   canonical `database/schema.sql`.
2. Provide a portable PostgreSQL migration for existing databases. No `.sql`
   file may contain `psql` meta-commands.
3. Grant no new hold privilege silently to ordinary profiles. Update the
   controlled all-privileges and approved governance profiles only after
   business authorization.
4. Existing resources begin with no assignments and therefore unchanged
   behavior.
5. API additions are backward compatible, but clients that expose delete/edit
   controls must consume the new capability blockers before feature release.

## 15. Acceptance criteria

At minimum, automated tests prove:

1. scheduled, active, open-ended, and expired boundary behavior using database
   time, including exactly at `valid_from` and `valid_to`;
2. multiple simultaneous holds and removal of only one protection source;
3. direct and inherited protection through arbitrary hierarchy depth;
4. deduplication when one hold is assigned at multiple ancestors or directly
   and indirectly;
5. moving resources into and out of held subtrees with the required ordinary
   move authority plus applicable owner/contributor authority and complete
   audit;
6. deletion blocked for directly or indirectly held aggregations and records,
   and add/replace/remove/reorder blocked for their components, including
   direct SQL attempts;
7. disposition integration points always block while any hold is effective;
8. resource-state preservation blocks ordinary metadata, close/reopen, classification,
   vital status, review date, and movement while security level, ACL,
   exceptional ownership correction, location, and hold operations retain
   their own independently authorized behavior;
9. no partial update when a request mixes frozen and permitted fields;
10. hold deletion blocked by any direct held-item assignment, including expired holds;
11. remove-all affects only direct assignments and reports remaining inherited
    protection;
12. separation between hold visibility, `holds.administer`, per-hold owner
    authority, and `holds.held_items.manage_all`;
13. owner/contributor/administrator/global-manager held-item management authority and
    atomic remove-all behavior;
14. security-level, ACL, and count non-disclosure in hold lists and pickers;
15. optimistic-concurrency behavior for holds, contributor rosters, and
    assignments;
16. assignment/deletion, activation/update, movement, and owner/contributor
    deletion race tests, including contributor cascade and required-owner
    restriction behavior;
17. event types, actor snapshots, request/correlation IDs, reasons, and
    reference snapshots;
18. server-side filtering, sorting, and pagination;
19. creation without a reason, mandatory non-blank reasons for every post-
    creation hold mutation, and reason propagation to cascaded and domain
    events;
20. direct-held-item-only listing and an authorized **Open** action for every
    navigable held item row;
21. UI badges, effective-hold panel, disabled actions, inherited-source
    explanation, and refresh after held-item management changes; and
22. Access Explainer API and frontend results for direct, inherited,
    resource-state-preserving, destructive-component, movement, and disposition
    hold restrictions, including disclosure redaction and another-user
    diagnosis.

Database-backed tests must follow the repository rule: create a uniquely named
disposable PostgreSQL database, initialize it from the canonical schema or the
required migration path, point the entire test process to it, then terminate
connections and drop it whether the run passes or fails.

## 16. Implementation phases

The work is divided into three independently verifiable phases. These phases
separate the non-bypassable policy foundation, its application interfaces, and
the user-facing release without splitting closely coupled work into artificial
increments. The feature must not be exposed to users until Phase 3 is complete.

### Phase 1 — Persistence and non-bypassable policy enforcement

Implement the complete database and authorization foundation:

- add the canonical-schema and portable migration definitions for `holds`,
  `hold_contributors`, and both typed assignment tables;
- add `holds.administer` and `holds.held_items.manage_all` to the privilege
  catalogue and approved profiles;
- implement the centralized effective-hold and resource-state-preservation SQL
  functions/views, including direct, inherited, overlapping, scheduled,
  open-ended, and expired cases;
- implement database enforcement for deletion, disposition integration points,
  component mutation, enhanced resource-state preservation, movement, hold
  deletion, owner deletion, and contributor cascades;
- implement transaction locking and retry-safe ordering for the races listed in
  Section 8.2;
- extend event-history entity/reference snapshots and implement the required
  row and domain events; and
- add focused disposable-database tests for constraints, time boundaries,
  hierarchy inheritance, overlapping holds, direct SQL bypass attempts,
  cascades, concurrency, and canonical-schema/migration parity.

**Phase 1 exit gate:** all database tests pass against a newly created
disposable database and against the migration fixture; cleanup succeeds; direct
SQL cannot bypass an effective hold; and schema-parity checks pass. No UI or
public navigation is enabled.

### Phase 2 — Complete API, authorization, audit, and query integration

Build the server-side feature on the Phase 1 policy primitives:

- add schemas and endpoints for hold administration, contributor replacement,
  direct held-item assignment, resource-centric hold actions, effective-hold status, and
  hold history;
- enforce owner/contributor, hold-administrator, and global held-item manager
  authority; universal information-governance visibility; ordinary resource
  visibility/clearance/ACL rules; mandatory
  post-creation reasons, optimistic concurrency, and non-disclosing errors;
- extend aggregation, record, and component capabilities with stable hold
  blockers and reason codes;
- extend the Access Explainer response and evaluation path with effective-hold
  resource-state constraints and authorized redaction;
- add set-based hold indicators and filters to browse/search without N+1
  queries or count leakage;
- update the API policy inventory and API client methods; and
- add API, authorization, event-history, race, search, pagination, disclosure,
  and representative query-plan tests.

**Phase 2 exit gate:** every acceptance criterion that does not require a
browser passes; forged and stale requests are rejected; Access Explainer and
actual mutations return consistent decisions; query plans are acceptable on
representative deep and broad hierarchies; and the feature remains hidden from
ordinary UI navigation.

### Phase 3 — NiceGUI workflow and release verification

Deliver the complete user workflow and verify it end to end:

- add role-aware Holds navigation, the searchable hold list, create/edit forms,
  hold detail, owner/contributor management, and the direct held-items table with
  filtering, sorting, pagination, selection, removal, and **Open** actions;
- add aggregation and record hold badges, authorized detail panels, direct and
  inherited-source explanations, add/remove/remove-all actions, and capability-
  driven disabled-state guidance;
- extend the Access Explanation dialog with hold-specific resource-state
  explanations and disclosure-safe details;
- add mandatory-reason dialogs for every post-creation hold mutation;
- add focused UI unit tests and browser end-to-end tests for administration,
  held-item management, inheritance, overlapping holds, expiry, enhanced preservation,
  restricted visibility, and stale-state refresh; and
- run the complete schema, migration, database, API, authorization, UI, browser,
  accessibility, and performance verification required for release.

**Phase 3 exit gate:** all acceptance criteria in Section 15 pass, no hold
operation is available solely because the UI exposes it, the disposable test
database is cleaned up, and the feature is ready to enable in navigation.

### Future disposition-subsystem obligation

Disposition is not a gratuitous fourth phase of this implementation because
that subsystem does not yet exist. Phase 1 must expose and test one
authoritative effective-hold predicate for it. When disposition is implemented, every
eligibility, approval, scheduling, batch, and execution path must consume that
predicate and prove end to end that an effective hold blocks disposition. The
disposition work cannot be considered complete until those integration tests
pass.

## 17. Approved policy decisions

1. **Hold codes are mutable.** A hold administrator may rename a code, subject
   to uniqueness, optimistic concurrency, mandatory reason, and audit.
2. **Held movement follows the proposed controlled rule.** Without enhanced
   resource-state preservation, movement requires normal move authority plus
   held-item management authority for every hold whose coverage changes. Enhanced
   preservation blocks movement.
3. **Non-mutating component actions remain available.** Download, share, and
   print continue under their normal authorization because legal discovery and
   production are important purposes of a hold.
4. **Owners and contributors are active person users only when selected.**
   Service accounts, roles, and organizational units are ineligible.
5. **Creation does not require a reason; later changes do.** Updates,
   assignment or removal, post-creation roster changes, and deletion require a
   non-blank reason as specified in Section 8.4.
6. **The first-release held-items table lists direct held items only.** Every row
   provides an authorized **Open** action to navigate to the aggregation or
   record. Effectively protected descendants are not expanded in this table.

## Built-in system notifications (approved 3 October 2026)

The legal-hold subsystem registers two optional producers under MSG-018 and
MSG-019 of the notifications and messaging specification. These notifications
are informational: they request neither read receipts nor action completion.
They do not change the hold's protections or resource permissions.

### Responsibility assignment — `holds.responsibility_assigned`

After creating a hold, notify its owner and each initial contributor. After
changing the owner, notify the newly assigned owner. After replacing
contributors, notify only newly added contributors. Unchanged assignments,
removals, rejected changes, and changes to unrelated fields create no assignment
notification. Each newly assigned person receives a separate envelope so that
one assignment does not disclose other responsible people.

Revised audience approval, 4 October 2026: the assignment audience is only the
newly assigned active person, resolved from the persisted hold responsibility.
Information governors are not included solely because of their governance role;
a governor who is personally assigned still receives their own assignment
notification. Clients cannot supply notification audiences
or content. The event identifier combines the committed hold event-history ID
and the assigned user ID. Typed context consists of integer `hold_id` and
`user_id`; neither appears in the supplied template. Retries of the same event
must not create a second delivery.

### Approaching end — `holds.approaching_end`

An active hold becomes eligible when its non-null end timestamp is no more than
seven days away and remains strictly later than the current database time.
Scheduled holds, expired holds, and holds without an end date are excluded.
One reminder is sent to the current active owner, active contributors, and all
active people with a currently effective information-governance role,
deduplicated by person. If no eligible person exists, no reminder is recorded;
the worker may try again while the hold remains eligible.

The reminder is unique for the pair `(hold ID, end timestamp)`. Changing the end
timestamp permits a reminder for the new timestamp once it becomes eligible.
Returning to a timestamp already notified does not create another reminder.
Changing responsibilities alone does not repeat an already-sent reminder.
Worker retries, restarts, multiple API instances, and later message purge must
not repeat a processed pair. Processing after downtime sends only still-eligible
reminders; it never sends a reminder after expiry.

The context contains integer `hold_id` and datetime `end_date`. The backend
resolves the current audience; only the localized end timestamp appears in the
supplied template. Delivery does not imply that resources become deletable at
that time: other holds and controls may continue to apply.

### Configuration, privacy, and transaction behavior

Both producers are optional and use normal priority initially. The only allowed
audience mode for each is its feature-owned resolver; neither supports static
recipients or structured resource links. The initial templates contain no hold
name, code, case description, resource title, or confidential content. Messages
use the messaging subsystem's baseline security level.

The producer catalogue is seeded separately from schema creation. A governed
configuration installer provides English and Arabic templates, attributed to a
named notification administrator, and activates them through the ordinary
configuration service. Existing active configurations and pending administrator
drafts are preserved. Unconfigured producers remain dormant; administrators may
disable configured producers. No historical assignment notifications are sent
on activation. Enabling the reminder producer permits still-eligible reminders.

An enabled assignment notification and its responsibility change commit in one
consistent-snapshot transaction. Failure rolls back both. An enabled reminder
and its processed-pair checkpoint likewise commit together; failure leaves the
pair retryable. Disabling the reminder producer does not mark pairs processed.
Recipient and fan-out limits remain those of MSG-018; they are not bypassed.

The API lifecycle worker checks for reminders approximately once per minute,
using a bounded batch of at most 100 holds and a transaction-scoped leader lock.
It uses the ordinary application connection pool. Durable checkpoints are
independent of message retention and are removed when their hold is deleted.

Notification templates are versioned notification configuration, not new UI
catalogue keys. Arabic templates reuse the checked-in terminology
«تعليق قنوني». Existing UI translations and their provenance remain unchanged.

The two producers use these feature-seeded display names independently of their
notification templates:

| Producer | English | Arabic |
| --- | --- | --- |
| `holds.approaching_end` | Legal hold approaching expiry | اقتراب انتهاء تعليق قنوني |
| `holds.responsibility_assigned` | Legal hold responsibility assigned | إسناد مسؤولية بشأن تعليق قنوني |
