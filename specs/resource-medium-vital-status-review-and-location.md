# Resource Medium, Vital Status, Review, and Location — Technical Specification

**Status:** Review draft — policy decisions incorporated; no implementation authorized
**Prepared:** 21 September 2026
**Project:** ERMS / Wathiq
**Revision:** 0.9

## 1. Purpose

This specification introduces physical-format, vital-record, and
review-scheduling metadata for aggregations and records, plus physical-location
metadata for aggregations. Records expose locations derived from their parent
aggregation rather than storing independent location values. It also defines
the integrity rules that follow from those values.

The scope defines five metadata names, although the two location fields are
stored only on aggregations:

- `medium`;
- `is_vital`;
- `date_of_next_review`;
- `current_location`; and
- `assigned_location`.

The feature must be enforced consistently by PostgreSQL, the REST API, search
and browse operations, capability responses, and every client UI. UI hiding or
validation alone is not sufficient.

## 2. Scope

### 2.1 Included

- `medium`, `is_vital`, and `date_of_next_review` on aggregations and records;
- `current_location` and `assigned_location` on aggregations, with derived
  read-only effective locations on records;
- medium-aware hierarchy and record-placement rules;
- medium-aware digital-component creation and maintenance;
- immutable protection against deleting vital resources;
- dashboard indicators and filters for reviews that are due or overdue;
- search, filtering, display, creation, and permitted editing of the fields;
- event-history capture;
- migration and seed-data treatment; and
- automated integrity, API, authorization, and UI tests.

### 2.2 Excluded

- warehouse, shelf, box, space, barcode, movement, or chain-of-custody models;
- notification delivery channels and user subscription preferences;
- a complete review case-management workflow;
- automatic security-level or vital-status decisions;
- automatic conversion, digitization, or destruction of physical holdings;
- physical-item inventory below record level; and
- bulk medium conversion.

`current_location` and `assigned_location` are deliberately temporary
aggregation-level location-code fields stored as PostgreSQL `text`. They must
be designed for later migration to the warehouse/space-management subsystem
without claiming referential integrity that does not yet exist. Individual
record checkout, custody, and movement are outside this phase.

## 3. Terminology

### 3.1 Medium

`medium` describes whether the holdings represented by a resource are digital,
physical, or a mixture of both:

| Value | Meaning |
| --- | --- |
| `digital` | The resource is managed as digital content only |
| `physical` | The resource represents physical holdings and cannot contain digital components |
| `mixed` | The resource includes, or may include, both physical and digital aspects |

For an aggregation, medium constrains the resources that may be filed beneath
it. A mixed aggregation may contain physical, digital, and mixed records; it
does not mean that the aggregation itself has digital components or that every
record is mixed. For a record, `mixed` means that the individual record has
both physical and digital parts.

### 3.2 Vital resource

A resource with `is_vital = true` is essential to continuing or restoring
business operations, protecting rights, or meeting critical obligations. Vital
status is a resource-state rule, not an ACL grant or security classification.

### 3.3 Next review

`date_of_next_review` is the next scheduled governance review of the resource's
metadata. Under the initial model, that review considers at least:

- whether the security level remains appropriate; and
- whether vital status remains appropriate.

The date does not itself change either value. A person must make and record the
review decision.

## 4. Data model

Both `aggregations` and `records` receive:

```text
medium                 text/tightly constrained enum, NOT NULL
is_vital               boolean, NOT NULL
date_of_next_review    timestamptz, nullable
```

Only `aggregations` receive stored location fields:

```text
current_location       text, nullable
assigned_location      text, nullable
```

Record representations expose, but do not persist as record metadata:

```text
effective_current_location     text, nullable, read-only
effective_assigned_location    text, nullable, read-only
```

### 4.1 Constraints and defaults

1. `medium` accepts only `digital`, `physical`, or `mixed`.
2. `medium` is mandatory at creation and must never be null after migration.
3. `is_vital` is mandatory and defaults to `false`.
4. `date_of_next_review` is nullable. Null means that no next review has been
   scheduled; it must not be interpreted as reviewed or exempt.
5. `date_of_next_review` is stored as `timestamptz` and exposed as ISO 8601.
6. Every non-null value newly assigned on create, or changed on update, must be
   strictly later than the server's current timestamp when the write is
   validated. An existing future value may naturally become due or overdue as
   time passes; that does not invalidate the stored row or block an unrelated
   update. Clearing the nullable field remains allowed.
7. Aggregation location values are trimmed. Blank-only values are normalized
   to null.
8. Locations are temporary location **codes**, not narrative descriptions.
   Each code has a maximum length of 200 characters.
9. The API uses `date_of_next_review` consistently. The shorter phrase
   “review date” may be used in UI labels, but `date_of_review` must not become
   a competing API or database name.

### 4.2 Location semantics

- **Assigned location** is the code of the physical storage location to which
  an aggregation is normally assigned and should ordinarily be returned.
- **Current location** is the code of where the aggregation is presently held.
- Neither value grants access or proves custody.
- No automatic relationship between the two values is imposed initially.
- Both values are governed metadata. Changing either value uses the governed
  location-change action defined in Section 11.1, including after closure.
- Digital aggregations may leave both fields blank. The initial release should
  not force them to null because a digital resource may still have a relevant
  operational location, such as offline media storage.
- PostgreSQL stores both values as `text`. PostgreSQL does not need `varchar`
  for storage efficiency; API validation and database checks enforce the
  200-character business limit.

### 4.3 Effective record location

A record does not store its own assigned or current location. Both are derived
from the effective location of its immediate parent aggregation:

```text
record.effective_assigned_location = parent.effective_assigned_location
record.effective_current_location = parent.effective_current_location
```

For an aggregation, each effective location is its own corresponding stored
value when non-null; otherwise it is inherited from the nearest ancestor with a
non-null value. A root with no value has an unknown effective location. This
allows a root or container move to affect all inheriting descendants without
copying location data into every row, while still allowing a child aggregation
that represents a separately stored physical container to establish its own
location.

Moving a record or child aggregation automatically changes any location it
derives from its parent. No independent record-location edit or
`record.location.change` permission exists in this phase. Future removal of an
individual physical record from its aggregation must be represented by a
controlled checkout/movement transaction in the space-management subsystem,
not by overwriting record metadata.

### 4.4 Why child aggregations may have independent locations

The aggregation hierarchy expresses an intellectual or filing relationship; it
does not prove physical co-location. A child aggregation may therefore store
its own `assigned_location`, `current_location`, or both. Common operational
cases include:

1. **Multi-volume files:** volumes of one case file occupy different shelves,
   while confidential exhibits are held in a secure room.
2. **Active and inactive portions:** current material remains with the business
   unit while older child files are transferred to an off-site records centre.
3. **Overflow storage:** later folders are placed in another cabinet after the
   original cabinet reaches capacity.
4. **Distributed operations:** regional offices physically maintain child files
   that remain part of one centrally managed aggregation.
5. **Special storage:** oversized drawings, photographs, or magnetic media are
   stored separately from ordinary paper folders.
6. **Temporary movement:** a child file is sent to Legal or an auditor while
   its assigned location remains the records centre.
7. **Partial archival transfer:** older child aggregations have been transferred
   to an archive while newer children remain with the originating organization.
8. **Resilience and vital holdings:** a vital child aggregation is deliberately
   stored at a separate secure or disaster-recovery facility.

Inheritance applies independently to each field. A child may, for example,
inherit `assigned_location` while overriding only `current_location` during a
temporary movement. Changing a parent field affects only descendants that
inherit that field; it must never overwrite an explicit child value. Clearing
an explicit child value restores inheritance from the nearest ancestor. The UI
must distinguish **Inherited** from **Set on this aggregation**, display the
source aggregation where authorized, and preview which inheriting descendants
will acquire a different effective value before a governed parent-location
change is confirmed.

The impact preview includes both descendant aggregations and records whose
effective assigned or current location would change. It reports only resources
the caller may view and indicates when the displayed list is truncated.

## 5. Medium hierarchy invariants

The following matrix is authoritative:

| Parent aggregation medium | Permitted child aggregation medium | Permitted child record medium |
| --- | --- | --- |
| `physical` | `physical` | `physical` |
| `digital` | `digital` | `digital` |
| `mixed` | `mixed` | `physical`, `digital`, `mixed` |

Consequently:

1. Every child aggregation has exactly the same medium as its parent.
2. A physical aggregation contains only physical records.
3. A digital aggregation contains only digital records.
4. A mixed aggregation may contain any mixture of physical, digital, and mixed
   records.
5. These rules apply to creation, move, import, correction, and direct database
   writes.
6. A record or aggregation move is rejected when the destination would violate
   the matrix.
7. Moving an aggregation validates its complete subtree atomically. A move
   cannot partially succeed.

## 6. Medium during creation

### 6.1 Root aggregation

The form initially fills `medium` from the
`DEFAULT_ROOT_AGGREGATION_MEDIUM` environment variable, whose default is
`mixed`. The configured value must be one of `digital`, `physical`, or
`mixed`; application startup fails clearly if it is invalid. This is only a
UI/API default, not an enforced policy: the creator may select a different
value before saving. The selected value remains independent of **Create for**,
organizational ownership, classification, and security level.

### 6.2 Child aggregation

The child medium is derived from the selected parent and is read-only in the
creation form. Clients must not invite a choice the server cannot honor. The API
may accept no child-medium field and assign the parent value itself; if a client
does submit a value, it must match the parent.

### 6.3 Record

The parent aggregation is selected before medium. The medium selector then
offers only values permitted by the matrix:

- physical parent: `physical`, read-only;
- digital parent: `digital`, read-only; and
- mixed parent: `physical`, `digital`, or `mixed`.

If a parent change invalidates the selected medium, the client clears or safely
reselects medium and displays an accessible explanation.

### 6.4 Drafts and staged components

Record drafts must carry medium before accepting files.

- `digital` and `mixed` drafts may stage digital components.
- `physical` drafts must hide or disable upload controls, and the API must
  reject component staging.
- Changing a draft to `physical` is blocked while staged components exist. The
  user must remove the staged components first; they must never be silently
  discarded.

## 7. Digital-component rules

1. A committed record whose medium is `physical` cannot have digital
   components.
2. Component upload, add, replace, and any operation that would introduce a
   component are rejected for a physical record, regardless of privileges and
   ACL permissions.
3. Component list, view, download, print, share, removal, and reorder continue
   to use their existing authorization rules for digital and mixed records.
4. Capability responses return component-add as false for physical records and
   include a resource-state explanation code such as
   `physical_record_disallows_digital_components`.
5. The record UI replaces the uploader with an explanation such as:
   **This is a physical record. Digital files cannot be added.**
6. PostgreSQL enforces the invariant so imports and non-UI clients cannot attach
   a component to a physical record.

There should be no existing physical record with components. Migration must
validate this before enabling the constraint.

## 8. Changing medium after creation

### 8.1 Recommendation

Allow an aggregation's medium to change through ordinary authorized metadata
editing **only while it is empty**:

- it has no child aggregations;
- it has no child records; and
- if it is itself a child, the new value is compatible with its parent—which,
  under the matrix, means it must still equal the parent's medium.

In practice, an empty child aggregation cannot change independently because all
child aggregations must equal their parent. An empty root aggregation may
change freely among the three values.

Once an aggregation contains anything, its medium should be treated as
immutable in this phase. Do not cascade a parent medium change into descendants:
doing so would rewrite factual metadata and could misrepresent physical or
digital holdings. Do not merely validate that the present subtree happens to be
compatible; future operational meaning and migration risk justify the simpler,
stable boundary.

A future governed conversion workflow may support non-empty changes using an
impact preview, reason, authorization, validation of every descendant, and an
atomic event history. That workflow is outside this scope.

### 8.2 Record medium changes

**Recommended initial rule:** a record's medium may change only when all of the
following are true:

- the destination value is permitted by its parent aggregation;
- the record has no digital components when changing to `physical`;
- the record is not effectively closed;
- the caller passes the existing metadata-change authorization gates; and
- a non-blank reason is recorded.

The system must never delete components implicitly to permit a medium change.
Record medium therefore remains editable under constraints; it does not become
immutable merely because the record has been saved.

## 9. Vital-status deletion protection

### 9.1 Resource-state gate

For delete operations, vital status is evaluated in the authorization engine's
existing **operation and integrity/resource-state gate**, before global
privilege and ACL success can produce an allow decision.

- A record with `is_vital = true` cannot be deleted.
- An aggregation with `is_vital = true` cannot be deleted.
- An aggregation cannot be deleted if any descendant aggregation or record is
  vital. This prevents parent deletion from bypassing a descendant's vital
  protection.
- Information-governance ACL bypass does not bypass vital protection.
- No ordinary privilege, ACL permission, or administrator role bypasses the
  rule.

The denial should use a stable code such as `vital_resource_deletion_blocked`.
For an aggregation with vital descendants, the response should provide safe
counts but must not reveal descendants the caller cannot otherwise view.

Vital status on an aggregation or its descendants does not prevent ordinary
closure. An authorized user may close a vital aggregation without clearing
its vital designation. A normal legal hold likewise does not prevent closure;
an effective hold with `preserve_resource_state = true` retains the closure
restriction defined in [Legal Holds Section 5](legal-holds.md#5-enhanced-resource-state-preservation).
Normal close permission, closure-date and integrity checks remain required.
This distinction applies whether or not disposition is being accelerated.
Closing does not waive vital protection against deletion or disposition.

### 9.2 Database enforcement

The API and capability endpoint provide explanations, but PostgreSQL must be
the final authority. Deletion triggers or controlled delete functions must
block direct deletion and cascading deletion of vital resources. A transaction
must not partially delete a branch before discovering a vital descendant.

### 9.3 Changing vital status

Simply allowing anyone who can edit metadata to clear `is_vital` would make the
deletion rule easy to circumvent. Changing vital status is a separate governed
operation requiring:

- the corresponding new global privilege:
  `aggregation.vital_status.change` or `record.vital_status.change`;
- sufficient security clearance;
- the corresponding new ACL permission:
  `aggregation.vital_status.change` or `record.vital_status.change`, unless the
  caller qualifies for the existing information-governance ACL bypass;
- a non-blank reason; and
- an immutable event recording the old value, new value, reason, actor, and
  authorization basis.

The global privilege authorizes the governed class of action; the effective ACL
permission authorizes it on the particular resource. Profiles assigned to
information-governance roles should carry the new global privileges. Their
existing ACL bypass means they need not be named in each resource ACL, but it
does not bypass security clearance or resource-state rules. Other profiles may
receive the privileges only if policy intentionally delegates this governed
action; those users still require the resource ACL permission.

### 9.4 Ancestor indication

Every aggregation containing a vital descendant at any depth must clearly show
that condition in its detail view. The same indication should appear in tree
and list views where practical, including on the root and every intermediate
parent—not only on the direct parent of the vital resource.

The aggregation read and browse contracts should expose an authorization-safe
derived boolean such as `has_vital_descendants`. It is not stored as
authoritative metadata. The UI label should be explicit, for example
**Contains vital resources**, with help text explaining that the aggregation
cannot be deleted while any descendant is vital. The indicator must not reveal
the titles, identifiers, or locations of descendants the caller cannot view.
If a count is displayed, it must also be authorization-safe; otherwise show
only the boolean warning.

## 10. Review scheduling

### 10.1 Can one date serve both purposes?

Yes, one `date_of_next_review` can serve both purposes **if Wathiq defines a
single combined governance review** that always considers security level and
vital status together. This is the recommended initial model because it is
clear, economical, and matches the stated purpose.

One date becomes inadequate when the two subjects have different review
frequencies, reviewers, escalation rules, or completion dates. If that need is
known now, use two fields instead:

```text
security_review_due_at
vital_status_review_due_at
```

Do not keep one ambiguous date and infer its purpose from unrelated history.
Longer term, if reviews need assignment, status, findings, evidence, approvals,
or recurrence, replace bare dates with a review entity rather than adding more
columns.

### 10.2 Recommended initial semantics

1. Retain one nullable `date_of_next_review`.
2. A review is due when the timestamp is less than or equal to the current time.
3. A review is upcoming only when its timestamp is later than now and no later
   than the configured warning-window boundary.
4. Merely changing the date does not prove that a review occurred.
5. This phase has no **Complete review** action, review note, review outcome, or
   review-completion event. Changing `date_of_next_review` is only a scheduling
   metadata update and must never be represented as evidence that a review was
   performed.
6. A complete review workflow and subsystem—including assignment, findings,
   evidence, outcome, completion, rescheduling, and approvals—is future scope.
7. No automated job changes security level or vital status.
8. Time comparisons use UTC; clients display the user's configured/local time.

The absence of a `last_reviewed_at`, outcome, reviewer, and review status means
the initial feature is a reminder mechanism, not a full compliance workflow.

### 10.3 Warning-window configuration

`REVIEW_WARNING_WINDOW_DAYS` controls the upcoming-review window and defaults
to `30`. It must be a non-negative integer and invalid configuration must fail
application startup clearly. The boundary is evaluated by the API using the
server clock:

```text
now < date_of_next_review <= now + REVIEW_WARNING_WINDOW_DAYS
```

The backend is authoritative and returns the configured window or its computed
boundary through the appropriate configuration/summary response; clients must
not independently assume 30 days. A value of `0` produces no upcoming items
but does not suppress already due or overdue items.

## 11. Authorization model

The new rules compose with existing gates; they do not replace them.

| Operation | Existing authorization | Additional resource-state rule |
| --- | --- | --- |
| Create aggregation/record | Existing create privilege, parent permission, clearance, ownership, classification, and closure rules | Medium must satisfy the hierarchy matrix |
| Move aggregation/record | Existing source/destination authorization and confirmation | Destination and complete affected subtree must remain medium-compatible |
| Add component | Existing component privilege, record permission, clearance, and closure rules | Record medium must be `digital` or `mixed` |
| Change medium | Existing metadata authorization plus reason | Empty-aggregation/parent/component/closure constraints |
| Delete aggregation/record | Existing delete privilege, ACL permission, clearance, closure, and dependency rules | Resource and aggregation descendants must not be vital |
| Change vital status | Matching global privilege and effective ACL permission, or information-governance ACL bypass | Reason and governance qualification required; permitted on closed resources |
| Change next-review date | Matching `aggregation.review_date.change` or `record.review_date.change` global privilege and effective ACL permission, or information-governance ACL bypass | Governed reason required; value must be null or strictly in the future; permitted on closed resources; scheduling only, not review completion |
| Change aggregation location | `aggregation.location.change` global privilege and effective ACL permission, or information-governance ACL bypass | Governed, reasoned action permitted on open or closed aggregations |

Capability endpoints and access explanations must identify the relevant
resource-state denial instead of returning a generic forbidden response.

### 11.1 Governed location changes

Changing an aggregation's `assigned_location` or `current_location` is a governed
operation because it records the physical custody context of holdings. It
requires:

- the new `aggregation.location.change` global privilege;
- the effective `aggregation.location.change` ACL permission, unless the
  caller qualifies for the existing information-governance ACL bypass;
- sufficient security clearance;
- a non-blank reason; and
- immutable event history containing the old and new location values, reason,
  actor, timestamp, and authorization basis.

The governed command produces one `RESOURCE_LOCATION_CHANGED` event. The same
row mutation must not also produce a generic `UPDATE` event. The same
single-event rule applies to `VITAL_STATUS_CHANGED` and `REVIEW_DATE_CHANGED`.

The action may update either or both location fields atomically. It is allowed
when an aggregation is closed because closure of its contents does not imply
that its physical files or containers can no longer move. Location authority
does not authorize changing medium, content, security level, vital status,
hierarchy, or other metadata. Records have no equivalent command in this phase.

## 12. REST API contract

### 12.1 Resource representations

Aggregation and record create/read/update/search schemas expose `medium`,
`is_vital`, and `date_of_next_review`. Creation forms require medium and may
omit `is_vital` to receive the false default. Read responses always contain
`medium` and `is_vital`. Aggregation representations additionally expose stored
and effective assigned/current locations. Record read and search representations
expose only `effective_assigned_location` and `effective_current_location`.

### 12.2 Server-derived choices

Clients must not be trusted to enforce parent compatibility. On every create or
move, the API locks and re-reads the relevant parent and validates medium in the
same transaction as the write.

### 12.3 Governed command boundaries

Post-creation location changes use a dedicated aggregation location command
rather than the ordinary metadata-update endpoint. This preserves the
authorization, reason, event-history, and closed-resource exception as one
atomic server-side operation. Ordinary metadata updates must reject attempts to
alter either stored aggregation location field. Initial aggregation locations
may still be supplied as part of an authorized create request. Record create
and update requests must reject `assigned_location` and `current_location` as
nonexistent writable fields and must reject the derived effective fields as
read-only.

### 12.4 Errors

Errors use stable codes and accessible messages. Suggested codes include:

- `aggregation_medium_mismatch`;
- `record_medium_not_allowed_by_parent`;
- `physical_record_disallows_digital_components`;
- `medium_change_requires_empty_aggregation`;
- `medium_change_requires_component_removal`;
- `next_review_date_must_be_future`;
- `location_change_reason_required`;
- `record_location_is_derived`;
- `vital_resource_deletion_blocked`; and
- `vital_descendant_deletion_blocked`.

### 12.5 Search and browse

Aggregation and record search support exact filters for `medium` and
`is_vital`, and date-range/null filters for `date_of_next_review`. Stored
aggregation locations participate in authorized text search. Record search may
offer filters over derived effective locations, provided it uses the same
ancestor-inheritance semantics as Section 4.3. Browse responses include
effective locations and the fields needed for badges and due-review indicators
without additional per-resource requests.

## 13. User interface

### 13.1 Forms

- Medium is a required, accessible select labelled **Medium**, with help text:
  **Indicates whether the aggregation or record is digital, physical, or a
  mixture of both.**
- Vital status is a clearly labelled checkbox or switch, not an unexplained
  icon.
- The review field is labelled **Next review** and includes date and time.
- The next-review control must prevent selecting a value that is not in the
  future and provide an accessible validation message. Server validation remains
  authoritative because client clocks and stale forms cannot be trusted.
- Aggregation forms expose optional location-code fields labelled **Assigned
  location** and **Current location**.
- On a closed aggregation, authorized users can still invoke a clearly labelled
  governed location action. The UI requires a reason and explains that this
  updates storage-location metadata without reopening the aggregation.
- Record forms never offer writable location fields. Record details display
  **Effective assigned location** and **Effective current location** as read-only,
  identify that they come from the containing aggregation, and show
  **Unknown** when no ancestor supplies a value.
- Child forms derive or constrain medium immediately after parent selection and
  explain why unavailable values cannot be selected.
- Edit forms show medium even when it is read-only and explain the blocking
  condition.

### 13.2 Resource detail and lists

Medium and vital status are visible metadata. Vital resources receive a text
label as well as an icon so status is not communicated by color alone. Due and
overdue review indicators must be accessible and must display the exact date.
An aggregation with a vital descendant at any depth displays **Contains vital
resources** on its detail page and, where supported, in browse trees and lists.

### 13.3 Delete controls

Delete is disabled or omitted for a vital resource according to the existing UI
convention. The user-facing explanation is:

> This resource is marked as vital and cannot be deleted. Its vital status must
> be reviewed and changed through the governed action first.

For an aggregation with vital descendants, the explanation states that the
branch contains vital resources without exposing unauthorized titles.

## 14. Dashboard and notifications

The consolidated dashboard summary endpoint should be extended rather than
adding per-widget requests. It should return authorized counts and bounded
previews for:

- overdue aggregation reviews;
- upcoming aggregation reviews;
- overdue record reviews; and
- upcoming record reviews.

Each count represents the complete authorized result, not merely the preview.
`DASHBOARD_REVIEW_PREVIEW_LIMIT` controls the maximum number of resources in
each preview and defaults to `5`. It must be a non-negative integer; `0` returns
counts without preview items. Invalid configuration must fail application
startup clearly.

Overdue previews sort by `date_of_next_review ASC`, placing the oldest and most
overdue item first. Upcoming previews also sort by
`date_of_next_review ASC`, placing the soonest review first. Resource ID sorts
ascending as the deterministic secondary key. Each non-empty category provides
a **View all** action opening the corresponding authorized filtered search.

Upcoming sections include only resources satisfying the configured
`REVIEW_WARNING_WINDOW_DAYS` boundary. Resources scheduled months or years
beyond that boundary are omitted from upcoming counts and previews. Overdue
sections remain separate and are not suppressed by the upcoming window. The
warning-window duration is configuration, not hard-coded UI behavior.
Dashboard review results are limited to holdings whose `owning_org_unit_id` is
an organizational unit represented by one of the caller's currently effective
roles. Within that ownership scope, normal visibility, clearance, and ACL rules
apply. A qualifying information-governance custodian uses the existing ACL
bypass and can therefore see every resource in that ownership scope that is
otherwise visible at their security clearance; the bypass does not itself add
unrelated organizational units to the scope. A future notification worker
should use an idempotent delivery design and the same authorization-safe data
source.

The Dashboard must supplement the existing review reminder lists with a
**Review urgency** part-to-whole chart. The chart uses the complete
`overdue_review_count` and `upcoming_review_count`, not the bounded preview
lengths. Upcoming means due within the configured warning window. The chart is
additive: the Overdue and Upcoming lists, dates, empty states, totals, and
**View all** actions remain present and authoritative for item-level detail.

The Dashboard must also supplement the Aggregations and Records overview with
an **Attention signals** grouped bar chart immediately below the administration
count strip. It compares the existing authorized vital and effectively held
counts for aggregations and records. The chart requires no administration
privilege beyond an authenticated session and must remain visible even when the
caller has no administration-count items. Administration-count visibility
continues to depend independently on the corresponding global privileges. The
chart does not replace the existing vital and held values in the two overview
cards.

## 15. Event history

Automatic `CREATE` events include all fields applicable to that resource, and
ordinary `UPDATE` events include the applicable fields in before/after state
and `changed_fields`. Successful governed aggregation-location changes produce
one explicit
`RESOURCE_LOCATION_CHANGED` event instead of a duplicate ordinary update event,
so they remain distinguishable even when performed on a closed aggregation.

The following changes require a non-blank reason:

- medium changes;
- `is_vital` changes; and
- aggregation `assigned_location` or `current_location` changes.

Deletion denials do not create a misleading successful delete event. Existing
authorization-denial monitoring may record the safe denial code. No
`RESOURCE_REVIEW_COMPLETED` event exists in this phase. A future review
subsystem may introduce one with outcome metadata; a date edit alone must never
produce that event.

## 16. Closure interaction

Existing effective-closure rules continue to freeze content and ordinary
metadata mutation. Governed security-level and vital-status actions remain
available on closed resources under their respective authorization rules; this
does not constitute or complete a review. A governed aggregation-location
action may also change `assigned_location`, `current_location`, or both without
reopening the aggregation.

These exceptions do not permit medium, content, component, hierarchy, or
unrelated metadata changes. Each changed value must pass its own authorization
rule, including the new vital-status or location privilege and permission. Each
governed action requires a non-blank reason and immutable event history. Medium
remain subject to ordinary closed-resource metadata restrictions in this
phase. `date_of_next_review` is changed through the separately governed
`aggregation.review_date.change` or `record.review_date.change` action, with a
mandatory reason and immutable `REVIEW_DATE_CHANGED` event. That action is
permitted on closed resources because closed holdings still require governance
review of security and vital status. A future review subsystem may define a narrower
rescheduling exception.

## 17. Migration and existing data

Before making medium non-null, migration must inventory:

- records with and without digital components;
- aggregation trees and the records beneath them;
- values that would violate the proposed matrix; and
- any existing seed or fixture generators.

Because this is a greenfield system and `mixed` is compatible with existing
digital components as well as component-free and physical holdings, migration
sets every existing aggregation and record to `mixed`. This creates a valid
hierarchy deterministically and avoids guessing a physical or digital medium
from incomplete evidence. Random medium assignment is not acceptable.

Existing rows receive `is_vital = false` and null review dates. Existing
aggregations receive null stored locations unless migration input explicitly
provides reviewed values; records receive no location columns. Seed scripts
must target the final schema. Existing generated seeds default aggregations and
records to `mixed`; a seed may use another medium only when it deliberately
creates an entirely hierarchy-compatible scenario.

## 18. Database enforcement and concurrency

PostgreSQL must enforce:

- valid non-null medium values;
- parent/child aggregation medium equality;
- record/parent medium compatibility;
- the absence of components for physical records;
- safe medium changes;
- future-only non-null next-review values at insertion or when that field is
  changed, using a trigger or controlled write function rather than a volatile
  `CHECK` constraint; an already stored date becoming overdue is valid and must
  not block unrelated updates;
- vital resource and vital-descendant deletion protection; and
- move/create checks under concurrency.

Creation, move, medium change, component insertion, and deletion must lock the
necessary resource or hierarchy rows in stable order. Validation and mutation
occur in one transaction. No check-then-write race may create an invalid state.

## 19. Testing requirements

Tests must cover at least:

- every cell in the medium compatibility matrix;
- root, child, record, move, and subtree-move behavior;
- digital/mixed component creation and physical rejection;
- draft medium changes with staged files;
- empty and non-empty aggregation medium changes;
- record medium changes with and without components;
- vital record and aggregation deletion denial;
- attempted parent deletion with a vital descendant;
- governance bypass not bypassing vital protection;
- capability and access-explanation denial codes;
- review due/upcoming timezone boundaries;
- future-date validation at create/update boundaries, including equality with
  the server time, stale forms, null clearing, and dates becoming overdue
  without subsequent writes;
- valid and invalid `DEFAULT_ROOT_AGGREGATION_MEDIUM` and
  `REVIEW_WARNING_WINDOW_DAYS` and `DASHBOARD_REVIEW_PREVIEW_LIMIT`
  configuration values;
- root-form defaulting without preventing the creator from selecting another
  valid medium;
- dashboard exclusion immediately beyond the warning boundary and inclusion at
  the exact boundary;
- complete dashboard counts independent of preview limits, zero-item previews,
  oldest-overdue and soonest-upcoming ordering, stable ID tie-breaking, and
  **View all** filters;
- dashboard visibility and single-summary-request behavior;
- API rejection despite stale or manipulated UI state;
- direct SQL invariant enforcement;
- event-history values and required reasons;
- aggregation-location privilege/permission enforcement, ACL bypass, reason
  validation, atomic two-field updates, and changes on closed aggregations;
- nearest-ancestor effective-location derivation, record moves, aggregation
  moves, independent per-field child overrides, clearing an override to restore
  inheritance, preservation of explicit child values during parent changes,
  null/unknown locations, and rejection of record-location writes;
- migration validation and seed compatibility; and
- concurrency races between component upload/medium change and
  deletion/vital-status change.

Database-backed tests must use a fresh disposable PostgreSQL database in
accordance with project policy.

## 20. Suggested phased implementation

### Phase 0 — Policy approval and inventory

- formally approve the policies recorded in Section 22;
- inventory schema, API, forms, drafts, moves, deletion, search, dashboard,
  event history, and seeds;
- define migration treatment and stable error codes.
- document `DEFAULT_ROOT_AGGREGATION_MEDIUM=mixed` and
  `REVIEW_WARNING_WINDOW_DAYS=30` and `DASHBOARD_REVIEW_PREVIEW_LIMIT=5` in
  `.env.example` and deployment guidance.

### Phase 1 — Schema and read models

- add nullable migration columns;
- update the canonical schema independently;
- expose read/search fields;
- update seeds and fixtures;
- backfill and validate medium before applying non-null constraints.

### Phase 2 — Creation and hierarchy integrity

- implement root, child, record, and move compatibility;
- add database enforcement and API validation;
- implement medium-aware creation forms.

### Phase 3 — Digital-component integrity

- extend drafts and component endpoints;
- enforce the physical-record prohibition;
- update capability responses and record UI.

### Phase 4 — Vital-status governance and deletion

- implement the approved vital-status authorization policy;
- block direct and cascading deletion;
- update deletion preflight, capability explanations, UI, and event history.

### Phase 5 — Review and location experience

- add aggregation location editing and effective-location display for
  aggregations and records;
- extend search and the consolidated dashboard summary;
- add due/upcoming indicators and configuration.

### Phase 6 — Operational hardening

- complete concurrency and migration tests;
- document client contracts and administrator policy;
- verify backup/restore, seed compatibility, accessibility, and performance.

A full review-workflow entity, notification delivery service, warehouse/space
management, and non-empty medium conversion remain future phases unless
separately approved.

## 21. Risks and limitations

1. **Broad mixed semantics:** a mixed aggregation can contain physical,
   digital, and mixed records. Users may need help text explaining that it is
   a mixed-medium filing context, not a requirement that every record itself
   have both media.
2. **Deletion circumvention:** protecting only the selected aggregation but not
   its descendants would allow vital content to be deleted indirectly.
3. **Status circumvention:** ordinary vital-status editing could reduce the
   deletion protection to a two-click bypass.
4. **Migration ambiguity:** lack of a digital component does not prove a record
   is physical.
5. **Location quality:** temporary unvalidated aggregation location codes can
   still contain spelling, naming, and stale-location problems until structured
   space management exists.
6. **Individual record movement:** the initial model cannot represent a record
   temporarily removed from its aggregation. Such movement must wait for the
   checkout/custody model rather than being recorded as an inaccurate location
   override.
7. **Review ambiguity:** a bare date proves neither completion nor outcome.
8. **Closed-resource governance:** review and physical-location changes require
   narrow exceptions that must not accidentally enable unrelated metadata or
   content mutation.
9. **Hierarchy cost:** vital-descendant, subtree-medium, and effective-location
   queries require proper
   recursive-query indexes and concurrency design.
10. **Stale clients:** older clients may omit mandatory medium or attempt to
   submit record location fields; deployment needs
   a coordinated compatibility plan.
11. **Terminology:** “medium” requires localization and help text so users do
    not confuse it with file format, record type, subject, or storage location.

## 22. Approved policy decisions

1. A mixed aggregation may contain physical, digital, and mixed records. A
   mixed record itself has both physical and digital parts.
2. Record medium remains editable when compatible with its parent; changing to
   physical is prohibited while digital components exist.
3. Vital-status changes use distinct aggregation and record global privileges
   and corresponding ACL permissions as defined in Section 9.3.
4. Governed security-level and vital-status actions may operate on a closed
   resource without reopening it, but they do not constitute a completed
   review. The next-review date remains ordinary scheduling metadata in this
   phase.
5. Dashboard review results are ownership-scoped to the organizational units of
   the caller's effective roles, with the established information-governance
   ACL bypass applying inside that scope.
6. Existing aggregations and records, including component-free records and
   empty aggregations, are backfilled as `mixed`; seed scripts are updated for
   the final schema.
7. One combined `date_of_next_review` is sufficient for the initial release.
8. A non-null next-review date must be in the future when written. This phase
   provides warnings only and has no review-completion workflow or event.
9. Root aggregation forms default medium from
   `DEFAULT_ROOT_AGGREGATION_MEDIUM`, which defaults to `mixed`; creators may
   choose another permitted medium before saving.
10. Upcoming-review warnings use `REVIEW_WARNING_WINDOW_DAYS`, defaulting to 30,
    and dashboards omit future reviews beyond that boundary.
11. Dashboard review previews contain at most
    `DASHBOARD_REVIEW_PREVIEW_LIMIT` items, defaulting to five. Overdue items
    show oldest first; upcoming items show soonest first; both use ascending
    resource ID as a stable secondary sort. Counts remain complete.
12. Aggregation medium may change only while the aggregation is empty and no
   cascading conversion occurs.
13. Stored assigned and current locations exist only on aggregations. Their
    changes are governed by the `aggregation.location.change` global privilege
    and matching ACL permission, require a reason, and may be performed on
    closed aggregations without reopening them.
14. Records expose read-only effective locations inherited from the nearest
    containing aggregation with a stored value. Individual record movement is
    deferred to the future space-management checkout/custody model.
15. Location values are temporary codes stored as PostgreSQL `text`, with a
    200-character business limit enforced by the API and database.

## 23. Remaining decisions and implementation issues

### 23.1 Remaining decisions for this scope

The principal domain policy is settled. One bounded data-entry decision remains
open:

1. Define the temporary location-code character, whitespace, case-preservation,
   and comparison conventions. Codes are not guaranteed unique or
   referentially valid until the future space-management subsystem replaces
   them.
This decision does not change the approved medium, vital-status, deletion,
location-inheritance, or review-warning rules.

### 23.2 Deferred or engineering matters

- The future space-management subsystem must define checkout,
  borrower/custodian, destination, expected return, return completion, and
  movement history for an individual record removed from its aggregation.
- Recursive vital-descendant checks, subtree validation, and derived-location
  queries must be benchmarked on deep trees. Transactionally maintained summary
  state should be considered only if direct queries cannot meet performance
  requirements without weakening correctness.
