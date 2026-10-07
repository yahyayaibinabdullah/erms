# Organizational Ownership and Default ACLs — Technical Specification

**Status:** Approved — Phase 7 complete; exceptional bulk transfer deferred
**Approved:** 20 September 2026
**Project:** ERMS / wathiq
**Prepared:** 20 September 2026
**Revision:** 1.5 — removed ACL management from prospective creator defaults

Revision 1.5 is approved on 7 October 2026. Its creator-default changes apply
only to ACLs initialized after implementation. Existing grants remain unchanged.

## 1. Purpose

This specification defines organizational ownership metadata and safer default
access-control lists for aggregations and records in wathiq.

Every aggregation and record belongs to one owning organizational unit. The
owner supports grouping, filtering, searching, reporting, and organizational
accountability. It is not a workspace and is not an additional authorization
boundary.

New local ACLs receive useful defaults for:

- the effective role under which the creator is acting; and
- a new contextual pseudo-principal named **All org unit members**.

These defaults reduce routine ACL configuration while preserving global
privileges, security clearance, information-governance bypass, lifecycle
rules, and existing ACL inheritance.

## 2. Scope

### 2.1 Included

This feature includes:

- `owning_org_unit_id` on every aggregation and record;
- automatic ownership inheritance through aggregation containment;
- automatic ownership changes when resources move;
- optional filtering, grouping, searching, and reporting by owner;
- an **All org unit members** ACL pseudo-principal;
- creator-role and org-unit-member ACL defaults;
- a combined organizational-role selection for root ownership and creator ACL
  attribution;
- exceptional bulk transfer of all holdings from a defunct org unit;
- ownership and ACL event history;
- migration of existing governed content; and
- database, REST API, API-client, UI, and automated-test changes.

### 2.2 Excluded

This feature does not include:

- workspaces or a workspace switcher;
- a current workspace stored in a login session;
- access boundaries based solely on organizational ownership;
- information-governance cross-workspace mode;
- direct user ACL grants;
- ownership by more than one org unit;
- independently owned children or records;
- automatic access to every resource owned by an org unit outside the ACL
  mechanism; or
- automatic replacement of existing `Everyone` grants.

The separate organizational-workspaces specification remains unchanged and is
not implemented by this feature.

## 3. Design principles

1. **Ownership is custody metadata, not authorization.** A user outside the
   owning org unit may access a resource when the existing privilege,
   clearance, ACL, and lifecycle rules permit it.
2. **Containment determines ownership.** A child cannot have an owner different
   from its parent aggregation.
3. **ACLs remain authoritative for resource scope.** Organizational ownership
   neither grants nor denies access by itself.
4. **Global privileges remain mandatory.** An ACL grant cannot supply a global
   capability missing from all effective roles.
5. **Security clearance remains mandatory.** Neither creator status nor org-unit
   membership bypasses clearance.
6. **Information-governance bypass remains unchanged.** Effective governance
   roles may bypass resource ACLs only as already specified and implemented.
7. **Defaults are removable.** The creator-role and org-unit-member grants may
   be edited or removed through ordinary authorized ACL management.
8. **Server-side enforcement is authoritative.** Ownership propagation and ACL
   matching must not depend on UI behaviour.
9. **Existing ACL inheritance remains meaningful.** Creation defaults must not
   silently defeat a parent's deliberate child-ACL policy.

## 4. Terminology

### 4.1 Owning organizational unit

The org unit presently accountable for an aggregation and its contained
records. It is stored in `owning_org_unit_id`.

### 4.2 Selected organizational role

One of the user's effective roles selected for creation. A single selection
provides both values the create operation needs:

- the role's `org_unit_id` becomes the owning org unit for a new root; and
- the role receives the creator-role ACL defaults.

The selector displays both the org unit and role, for example
**Finance — Records Officer**. When a user holds several effective roles in one
unit, that unit appears in several options—once for each distinct effective
role. This is intentional because each option grants creator access to a
different role.

The selector operates on distinct effective roles, not individual assignment
rows. Overlapping effective assignments for the same role must not produce
duplicate options.

Creator access belongs to the selected role, not permanently to the individual
user. Users never receive direct ACL grants.

### 4.3 All org unit members

A contextual synthetic ACL principal. It matches a user when the user has at
least one currently effective role whose `org_unit_id` equals the resource's
`owning_org_unit_id`.

The recommended stored principal code is `org_unit_members`; the UI label is
**All org unit members**.

This is not a real role and must not be represented by a row in `roles`.

### 4.4 Everyone

The existing synthetic principal matching every otherwise-authorized
authenticated user. `Everyone` and `All org unit members` are distinct. The
meaning of `Everyone` must not change.

## 5. Ownership invariants

The following rules have no ordinary exceptions:

1. Every aggregation has exactly one owning org unit.
2. Every record has exactly one owning org unit.
3. A root aggregation receives its owning org unit during creation.
4. A child aggregation automatically receives its parent's owner.
5. A record automatically receives its containing aggregation's owner.
6. A child aggregation's owner always equals its parent's owner.
7. A record's owner always equals its containing aggregation's owner.
8. A client cannot directly choose the owner of a child aggregation or record.
9. Direct updates to ownership outside create and move operations are rejected.

The database must enforce these invariants even when a caller bypasses the
ordinary UI.

## 6. Ownership during creation and movement

### 6.1 Root aggregation creation

The user selects one organizational-role option from their currently effective
roles. The selected role's org unit becomes the root aggregation's
`owning_org_unit_id`, and the selected role receives the creator ACL grants.

If exactly one distinct effective role is eligible, the server may select it
automatically. Several roles in the same org unit remain separate options.

### 6.2 Child aggregation creation

The system ignores or rejects client-supplied ownership and copies
`owning_org_unit_id` from the parent aggregation.

The user must have at least one effective role in the parent's owning org unit.
Having create authority only through roles in other org units is insufficient.

### 6.3 Record creation

The system ignores or rejects client-supplied ownership and copies
`owning_org_unit_id` from the containing aggregation.

The user must have at least one effective role in the containing aggregation's
owning org unit. Having create authority only through roles in other org units
is insufficient.

### 6.4 Record movement

When a record moves to another aggregation, its `owning_org_unit_id` is set to
the destination aggregation's owner in the same transaction.

The move may therefore change which users match the record's
`org_unit_members` ACL grants. The confirmation interface must display the old
and new owning org units when they differ. An ownership-changing move requires
a non-blank reason and one explicit confirmation. No additional approval is
required because of size or sensitivity.

### 6.5 Aggregation movement

When a child aggregation moves to a parent owned by another org unit, the
system changes ownership for:

- the moved aggregation;
- every descendant aggregation; and
- every record contained anywhere in the moved subtree.

The move and complete ownership propagation occur atomically. A failure rolls
back the placement and every ownership update. Concurrent changes must not be
able to leave mixed ownership within the subtree.

The move preview and confirmation must show the source owner, destination
owner, and affected aggregation and record counts. An ownership-changing move
requires a non-blank reason and one explicit confirmation. No additional
approval is required because of size or sensitivity.

### 6.6 Governed correction of mistaken root ownership

An information-governance user may correct a root aggregation that was created
for the wrong organizational unit without changing its placement. This is not
an ordinary metadata edit.

The action requires `organization.ownership.correct`, an effective
information-governance role with sufficient clearance, an active destination
role, a preview, a non-blank reason, and one confirmation. It atomically:

- changes the root owner and propagates it through all descendants and records;
- retargets `org_unit_members` context automatically;
- replaces grants belonging to the original root creator ACL role with the
  selected destination role throughout the subtree, consolidating duplicates;
- preserves `Everyone` and all other named-role grants; and
- records `OWNERSHIP_CORRECTED` with affected counts and role mapping.

Child aggregations and records cannot use this command; their ownership changes
only through the governed Move action.

### 6.7 Exceptional bulk transfer from a defunct org unit

Bulk transfer of all holdings from a defunct org unit is a distinct exceptional
operation. It is not implemented as repeated ordinary record or aggregation
moves and does not change aggregation placement.

The operation selects exactly one source org unit and one active destination
org unit. It changes `owning_org_unit_id` for every aggregation and record
owned by the source unit while preserving all aggregation and record
relationships.

The bulk-transfer workflow must:

- require a dedicated exceptional privilege, proposed as
  `organization.holdings.transfer`;
- require an effective information-governance role;
- require sufficient security clearance for every affected resource;
- require the source unit to be inactive or otherwise formally marked
  defunct under an approved organizational process;
- reject an inactive destination;
- preview affected root aggregations, descendant aggregations, records,
  security levels, ACL consequences, and counts;
- require a non-blank reason, a completed ACL reconciliation plan, and one
  explicit confirmation by the authorized initiating user;
- run as one transaction or as a resumable governed batch whose partial state
  is never exposed as completed;
- preserve aggregation and record placement;
- include resource ACLs and both child-default ACL types in an ACL
  reconciliation plan;
- record the source and destination org units and complete affected counts in
  immutable history; and
- produce a completion report and a failure report when applicable.

### 6.7.1 ACL reconciliation policy

Ownership transfer and ACL reconciliation are one governed plan. The transfer
must not leave the fate of source-unit role grants implicit.

The following rules apply:

- `org_unit_members` grants remain present and automatically refer to members
  of the destination owning org unit after the ownership update;
- `Everyone` grants remain unchanged;
- named-role grants for roles belonging to org units other than the defunct
  source unit remain unchanged because they represent deliberate cross-unit
  access; and
- every named-role grant for a role belonging to the defunct source unit must
  have an explicit reconciliation decision before the transfer can commit.

For each source-unit role, the governance user must choose one of:

1. **Map to destination role.** Replace the source role with a selected active
   role in the destination unit while preserving the approved permissions.
2. **Remove grants.** Remove that source role's grants from the affected
   resource and child-default ACLs.
3. **Retain as exception.** Keep the source role grants only with a separate
   justification. This option is available only if policy permits the role to
   remain effective despite the unit being defunct.

There is no automatic mapping based on similar role names, codes, hierarchy,
or profile. A proposed mapping must pass permission-dependency, role-clearance,
and destination-role activity validation for every affected ACL. Two source
roles may map to one destination role; duplicate grants are consolidated.

The preview must show, per source role:

- affected resource and child-default grant counts;
- permissions to be retained, removed, or mapped;
- proposed destination role and its profile and clearance;
- validation failures;
- cross-unit role grants that will remain unchanged; and
- the effective access consequences of retargeting `org_unit_members`.

Ownership changes and ACL reconciliation commit atomically. If any mapping is
unresolved or invalid, the transfer does not begin. The immutable audit record
must retain the complete mapping/removal/exception plan and resulting counts.

## 7. Data model

### 7.1 Resource columns

Add:

| Table | Column | Rules |
| --- | --- | --- |
| `aggregations` | `owning_org_unit_id bigint` | Required; references `org_units(id)` with `ON DELETE RESTRICT` |
| `records` | `owning_org_unit_id bigint` | Required; references `org_units(id)` with `ON DELETE RESTRICT` |

Record ownership is deliberately stored for efficient filtering and search,
although it is derivable from the containing aggregation. Database enforcement
must prevent the stored value from drifting.

Recommended browse indexes are:

```sql
CREATE INDEX aggregations_owner_parent_number_browse_idx
    ON aggregations (
        owning_org_unit_id,
        parent_aggregation_id,
        aggregation_number COLLATE "C",
        id
    );

CREATE INDEX records_owner_aggregation_number_browse_idx
    ON records (
        owning_org_unit_id,
        aggregation_id,
        record_number COLLATE "C",
        id
    );
```

Additional search indexes should be chosen from measured query plans rather
than added speculatively.

### 7.2 ACL principal representation

The allowed ACL principal types become:

```text
role
everyone
org_unit_members
```

Their structural rules are:

| Principal type | `role_id` | Meaning |
| --- | --- | --- |
| `role` | Required | One named role |
| `everyone` | Null | Every otherwise-authorized authenticated user |
| `org_unit_members` | Null | Users with an effective role in the resource's owning org unit |

Every ACL grant table requires a unique partial index preventing duplicate
`org_unit_members` grants for the same resource and permission.

The codes and names `org_unit_members` and `All org unit members` must be
reserved so that a real role cannot impersonate the synthetic principal.

### 7.3 Contextual matching

An `org_unit_members` grant does not store an org-unit ID. It derives the
relevant unit from the resource whose effective ACL is being evaluated.

For a role to match:

```text
assignment is currently effective
AND role is effectively active
AND role.org_unit_id = resource.owning_org_unit_id
```

The match supplies only the ACL permission. Existing global-privilege and
security-clearance gates still apply independently.

## 8. Organizational-role selection

### 8.1 Combined selection

Creation uses one selector labeled **Create for**. Each option combines an org
unit and one distinct effective role:

```text
Finance — Records Officer
Finance — Manager
Legal Affairs — Records Coordinator
```

The same org unit appears more than once when the user has several effective
roles there. Selecting an option simultaneously determines:

- the owning org unit for a new root aggregation; and
- the concrete role that receives the creator ACL grants.

Wathiq must not choose by database order, role ID, role name, or assignment
age. If only one option is eligible, the server may select it automatically.
The server validates that the submitted role is currently effective for the
authenticated user and records it in creation history.

### 8.2 Child aggregation and record creation

Ownership always comes from the parent. The user must have at least one
currently effective role in the parent's owning org unit. If none exists, the
create operation is denied even if roles in other org units provide the global
create privilege or some ACL permission.

The **Create for** selector is restricted to the user's distinct effective
roles in the parent's owning org unit. The parent therefore fixes the org-unit
part of every option while the selected role determines which role receives
the creator ACL grants.

## 9. Default ACL grant sets

Defaults are allow grants. They never substitute for the corresponding global
privileges, security clearance, or lifecycle rules.

### 9.1 New aggregation — creator ACL role

Grant:

```text
aggregation.view
aggregation.modify_metadata
aggregation.add_child
aggregation.add_record
aggregation.close
aggregation.history.view
```

These defaults let an appropriately privileged creating role maintain ordinary
aggregation metadata, add content, close the aggregation, and inspect its
history. Creating a resource does not appoint the creator role
as its access administrator.

Do not grant automatically:

```text
aggregation.delete
aggregation.acl.manage
aggregation.reopen
aggregation.move
aggregation.receive_child
aggregation.receive_record
aggregation.reclassify
aggregation.security_level.change
```

`aggregation.reopen` is deliberately excluded. Reopening is restricted to
information-governance roles. Such roles already use the governed ACL bypass
and therefore do not need a resource-specific `aggregation.reopen` grant.

`aggregation.security_level.change` is deliberately excluded. Selecting the
initial security level is part of the aggregation create operation and is
authorized by the applicable create privilege and validation rules. Changing
the security level after creation is a distinct governed operation requiring
the global `aggregation.security_level.change` privilege and matching ACL
permission or information-governance bypass.

### 9.2 New aggregation — All org unit members

Grant:

```text
aggregation.view
aggregation.history.view
```

Do not grant modification, child creation, record creation, closure, movement,
reclassification, deletion, ACL management, reopening, receiving, or security
level changes by default.

### 9.3 New record — creator ACL role

Grant:

```text
record.view
record.history.view
record.component.list
record.component.view
record.component.download
record.component.share
record.component.print
```

Do not grant automatically:

```text
record.modify_metadata
record.acl.manage
record.delete
record.move
record.security_level.change
record.component.add
record.component.replace
record.component.remove
record.component.reorder
```

The defaults do not give the creator ACL role ACL-management, metadata, or
component-mutation permissions after the record has been saved. The creator role may view,
download, share, and print the record when its profile supplies the applicable
global privileges.

This is a default authorization posture, not a hard-coded information-
governance-only command rule. Profiles determine which global privileges a
role has; an ACL can only allow exercise of a privilege already supplied by an
effective role. An authorized administrator may therefore enable an ordinary
role to modify a record by configuring both its profile and the effective ACL.

`record.component.share` and `record.component.print` depend on
`record.component.view`; `record.component.view` and download depend on
`record.component.list`; and all record permissions depend on `record.view`.
The specified set contains the required dependency closure.

### 9.4 New record — All org unit members

Grant:

```text
record.view
record.component.list
record.component.view
record.component.download
```

Do not grant history, ACL management, metadata modification, movement,
deletion, security-level changes, component mutation, sharing, or printing by
default.

## 10. ACL inheritance

Creator status does not confer ACL-management authority. A role may receive
that authority through a separate authorized grant, and exercising it still
requires the matching global privilege. Information governors retain ultimate
responsibility for access administration. The Effective File Administrator
grants and delegated responsibility are defined in
[Hierarchical Oversight Default ACLs](hierarchical-oversight-default-acls.md).

Wathiq currently supports live ACL inheritance for child aggregations and
records. A local ACL may exist while remaining dormant because the resource
inherits its effective ACL from a parent policy.

This specification preserves that design:

- a root aggregation always uses a local ACL initialized with the grant sets
  in Sections 9.1 and 9.2;
- a child aggregation that inherits continues to use its parent's effective
  child-aggregation ACL policy;
- a record that inherits continues to use its containing aggregation's
  effective child-record ACL policy;
- every new child aggregation and record also receives a dormant local ACL
  initialized with the applicable creator ACL-role and `org_unit_members`
  grant sets; and
- when local override is selected, that initialized local ACL becomes
  effective unless the ACL manager replaces it.

The parent policy takes precedence over generic creation defaults. Creating a
child must not silently disable inheritance merely to give its creator broader
access. Initializing the dormant local ACL ensures a predictable starting point
if inheritance is later disabled.

When an inherited resource later switches to local override, the ACL editor
shows the dormant local ACL and makes that ACL effective. It does not require
the user to choose a source, rebuild the ACL, or complete a separate preview
workflow.

If the user previously enabled local override, edited the local ACL, and then
returned to inheritance, those local edits remain stored while dormant.
Enabling local override again restores the last locally saved ACL. Inheritance
must never overwrite or reset it implicitly. An authorized user can edit the
local ACL through the ordinary ACL editor before or after enabling it.

### 10.1 Parent default-child ACLs

When a new aggregation is created, its child-aggregation and child-record ACL
defaults should initially be based on the same organizational policy:

- the aggregation's creator ACL role receives the applicable creator grant set
  for future children; and
- `org_unit_members` receives the applicable org-unit-member grant set.

An authorized ACL manager can replace these defaults. A later child created by
a different creator ACL role receives that role in its dormant local ACL, but
the role is not injected into the parent's effective child policy. While the
child inherits, the established parent policy remains authoritative.

## 11. Security and lifecycle behaviour

### 11.1 Initial security level

The creator selects the initial aggregation or record security level subject to
the existing create privilege, clearance, containment, and validation rules.
This does not require a `*.security_level.change` ACL grant because no existing
resource level is being changed.

After creation, changing a security level requires the corresponding global
privilege and ACL permission, unless an approved information-governance bypass
applies.

### 11.2 Saved-record authorization

Wathiq does not manage non-record documents and has no declaration or
undeclaration transition. Saving a new item creates a record. Deleting a record
is the effective removal or undeclaration operation, subject to existing delete
authorization and records-management rules.

After the initial save, access is determined by profiles, the effective ACL,
clearance, and lifecycle rules. This feature does not add a hard-coded command
rule restricting record modification to information-governance roles. The
default ACL merely omits metadata and component-mutation permissions from the
creator ACL role and `org_unit_members`.

### 11.3 Aggregation reopening

Ordinary roles receive no `aggregation.reopen` ACL grant from these defaults.
The reopen command must require an effective information-governance role, the
global `aggregation.reopen` privilege, sufficient clearance, and satisfaction
of all existing lifecycle and integrity rules. The information-governance ACL
bypass supplies resource scope.

Every reopen must also carry a non-blank reason. The web client collects it in
a mandatory confirmation dialog, the API enforces it for every caller, and the
automatic immutable `UPDATE` event stores it in `event_history.reason` with
`date_closed` identified in `changed_fields`.

## 12. Filtering, grouping, search, and reporting

Owning org unit should be available as an optional filter and response field
for:

- aggregation and record search;
- aggregation hierarchy browsing;
- classification-based browsing;
- dashboards and holdings summaries;
- retention and disposition reporting;
- exports; and
- governance reports.

Ownership filtering is not authorization. Search results must first satisfy
the existing authorization policy. The owner filter then narrows the already
authorized result set.

The API should filter by immutable org-unit ID. UI labels may show current
org-unit code and name.

### 12.1 Dashboard counts

The dashboard must show separate aggregation and record counts for each
distinct org unit represented by the user's currently effective roles.

Each org unit appears once even when the user has several effective roles in
that unit. Counts include only aggregations and records the user is authorized
to view; ownership alone must not reveal inaccessible holdings. A qualifying
org unit with no authorized resources displays zero rather than disappearing.
The dashboard heading must include adjacent explanatory text making clear that
the listed units come from the signed-in user's currently effective roles and
that the counts contain only resources the user is authorized to view.

The dashboard must supplement, and must not replace, the organizational-unit
holdings rows with a stacked horizontal **Records by medium** chart. Each unit's
bar represents its authorized `record_count` and is segmented by its authorized
physical, digital, and mixed record counts. Units use the same ordering and
eligibility rules as the holdings rows. The existing rows remain available as
the detailed, navigable presentation. A qualifying unit with zero authorized
records remains represented by its zero-valued row; the chart must not invent a
positive-width data segment.

The Dashboard must add a final **Digital storage by organizational unit**
section using the authorized `storage_size_in_bytes` values returned for the
same eligible organizational units. Units are ordered by storage descending,
then by name and immutable ID for deterministic ties. At most five units are
shown individually. When more than five eligible units exist, every remaining
unit is folded into one **Other units** summary containing their combined bytes
and share of the authorized total. The summary must not expose the names or
individual storage values of units outside the top five. Units outside the
caller's effective-role scope or containing only inaccessible records must not
contribute storage.

Dashboard loading must use a consolidated, self-only summary operation rather
than issuing one search request per card or hydrating recent activity through
per-resource requests. A refresh may have only one in-flight summary request
per browser page; repeated refresh actions while it is running are ignored.
The consolidated operation applies the same privilege, resource-visibility,
and clearance rules as the individual source operations and uses one database
pool checkout for the complete summary.

## 13. UI requirements

### 13.1 Ownership

- Creation shows one **Create for** selector listing each eligible combination
  as **{org unit name} — {role name}**.
- The same org unit appears once per distinct effective role held there.
- If the user has exactly one effective role, **Create for** is automatically
  populated with that role and its org unit and is read-only.
- For child aggregation and record creation, the selector lists only roles in
  the parent's owning org unit.
- Child-aggregation and record forms present the parent selector before
  **Create for**. Record creation keeps **Create for** disabled until a parent
  is selected. Aggregation creation keeps it available when Parent is blank
  because the selected role determines a new root's owner.
- The aggregation Parent field states that it is optional and that leaving it
  blank creates a root aggregation.
- Changing a parent preserves the selected role only while that role remains
  eligible. Otherwise the UI clears it and announces why in an accessible live
  status message. When no eligible role exists, the UI explains that creation
  under that parent is unavailable.
- Required fields use an asterisk in their label, and each creation or metadata
  form includes a visible `* Required fields` legend. Optional fields remain
  unmarked unless their blank value needs an explanatory hint.
- Child aggregation and record forms display the inherited owner as read-only
  context or omit the field entirely.
- Aggregation and record details display the owning org unit.
- **Create for** is creation context, not persistent resource metadata. After
  creation, ordinary details and edit views show **Owning organizational unit**;
  the selected role remains represented by the named-role ACL grants and audit
  history.
- Search and list pages may filter and group by owning org unit.
- Move confirmation displays an ownership change when the destination owner
  differs.

### 13.1.1 Advanced governed actions

To reduce visual clutter without changing authorization, aggregation details
place **Move**, **Correct ownership**, **Child defaults**, and **Record
defaults** in an **Advanced** section that is collapsed by default. Record
details place **Move** in the same kind of collapsed section. The server-issued
capability checks still determine whether each action is rendered; collapsing
the section is presentation only and is not a security control.

### 13.2 ACL editor

The ACL principal selector includes **All org unit members** alongside named
roles and `Everyone`.

Its explanatory text should state:

> Everyone currently working in **{org unit name}**. Membership updates
> automatically when role assignments change.

The editor must show that this principal is dynamic and contextual. It must not
show a selectable org-unit field for the principal. It is removable and
re-addable under the same authorization and optimistic-concurrency rules as
`Everyone`.

## 14. API requirements

API resource representations should add:

```json
{
  "owning_org_unit_id": 17,
  "owning_org_unit": {
    "id": 17,
    "code": "FIN",
    "name": "Finance"
  }
}
```

Exact embedding may follow existing concise-reference conventions. Create and
move commands must obey these rules:

- root aggregation create accepts a validated `creator_acl_role_id`; the server
  derives `owning_org_unit_id` from that role rather than trusting a separate
  client-supplied owner;
- child aggregation and record create may accept a validated
  `creator_acl_role_id`, restricted to effective roles in the parent's owning
  org unit;
- child aggregation and record create do not accept an owner;
- moves derive the new owner from the destination parent;
- ordinary update endpoints reject `owning_org_unit_id`; and
- ACL payloads accept `principal_type = "org_unit_members"` only with a null
  or absent `role_id`.

ACL responses and authorization explanations must identify whether a required
permission was supplied by a named role, `Everyone`, `org_unit_members`, or
information-governance bypass.

`GET /api/v1/dashboard/summary` returns the authorized overview counts,
classification metrics available to classification administrators, governance
attention counts, per-effective-org-unit holdings, favourites, and hydrated
self-only recent activity. This endpoint exists to bound dashboard database
concurrency; it must not broaden any source dataset merely because several
dashboard sections share one response.

The Records and Aggregations landing pages use the authenticated user's
self-only recent activity. Their lists include `CREATE`, `UPDATE`, and
`CONTENT_VIEWED`. A digital-component `CONTENT_VIEWED` event is attributed to
both its containing record and that record's containing aggregation; only the
newest qualifying view per resource is retained. The UI labels these entries
**Viewed**, applies current resource-visibility checks, and does not expose the
component as a separate activity item.

## 15. Event history and audit

Creation history must include the initial owning org unit and selected
organizational role.

When a move changes ownership, history must preserve:

- old and new parent where applicable;
- old and new owning org-unit IDs;
- snapshots of org-unit code and name;
- initiating user and selected organizational role where applicable;
- reason where the move workflow requires one;
- affected aggregation and record counts for subtree moves; and
- request or correlation ID.

ACL initialization, addition, removal, and replacement continue to generate
immutable ACL history under the existing authorization specification.

## 16. Existing-data migration

The migration below describes the original ownership feature. Revision 1.5
does not repeat that ACL initialization on existing resources. Preserve all
existing resource grants, dormant local grants, and default-child ACL grants,
including existing creator-role ACL-management grants. Change only the
initializer for subsequently created resources and templates; do not rerun or
rewrite migration 049 to remove existing permissions.

Wathiq is currently a greenfield project without a production holdings
database. Existing development and test resources may therefore receive a
deterministic best-effort owner and creator ACL role rather than requiring
manual governance review.

The migration must be staged:

1. Add nullable ownership columns and supporting indexes.
2. Build a stable ordered list of eligible roles whose role and org-unit
   hierarchies are active.
3. For each existing root aggregation, score eligible roles using normalized
   matches between the aggregation title and description and the org-unit and
   role code, name, and description.
4. Choose the unique highest-scoring role when one exists.
5. Resolve a tied or unmatched root through deterministic distribution across
   the stable role list, using roots ordered by aggregation number and ID.
6. Derive the root's owner from the selected role's `org_unit_id`.
7. Propagate the root owner to all descendant aggregations and records.
8. Initialize the root resource ACL and child-default ACLs from Section 9 using
   the selected role and `org_unit_members`.
9. Initialize each descendant aggregation and record's dormant local ACL using
   the same selected role and the appropriate Section 9 defaults, while
   preserving its inheritance setting.
10. Verify complete ownership and ACL consistency.
11. Add or enable invariant enforcement and make both ownership columns
    `NOT NULL`.

The assignment algorithm must be reproducible. It must not call PostgreSQL
`random()`, depend on unspecified row order, or produce different results when
rerun against the same input. Semantic matching is best-effort test-data
enrichment, not a claim that the inferred unit historically owned the content.

The migration report must list every root, selected role, derived org unit,
match score or fallback reason, descendant counts, record counts, and ACL rows
initialized. It must fail clearly if no eligible role exists.

Because this is a greenfield migration, the generated defaults replace the
existing permissive generated ACL contents for migrated resources. Existing
inheritance flags and resource placement remain unchanged. This migration must
not be reused unchanged after a real production database exists; a production
upgrade would require an explicit reviewed mapping and preservation or
reconciliation of intentional ACL customizations.

The migration and the complete self-contained `database/schema.sql` must
contain equivalent portable PostgreSQL definitions. The canonical schema must
not invoke the migration.

## 17. Impact on existing implementation

### 17.1 Database

Changes are required to:

- `aggregations` and `records` columns, foreign keys, and indexes;
- create and move enforcement functions or triggers;
- recursive aggregation-move ownership propagation;
- exceptional defunct-org-unit bulk transfer and reporting;
- all four ACL grant/default tables;
- principal-type checks and unique indexes;
- ACL dependency validation;
- reserved synthetic-principal names;
- event-history reference snapshots; and
- canonical schema and ordered migration documentation.

### 17.2 Authorization policy

Both PostgreSQL authorization predicates and the Python policy/explanation
model must recognize `org_unit_members`. Effective-role loading already
contains role and org-unit relationships but must expose the owning-unit match
to ACL evaluation.

Information-governance bypass, privilege evaluation, clearance evaluation, and
permission dependencies otherwise remain unchanged.

### 17.3 Resource ACL services

Changes are required to:

- request and response schemas;
- principal validation;
- grant grouping and display;
- ACL replacement and preview;
- effective ACL resolution;
- child-default ACL handling;
- clearance validation for synthetic principals; and
- authorization-explanation output.

### 17.4 Resource commands

Aggregation and record creation must validate the selected organizational role,
derive or verify the owner from its org unit, and initialize effective and
dormant ACLs as specified. Move commands must derive and propagate ownership.
Ordinary update commands must reject direct owner changes. A separate
exceptional command must perform defunct-org-unit bulk transfer and its ACL
reconciliation plan.

### 17.5 Query and presentation layers

Search, browse, list, detail, dashboard, export, and API-client models require
owner fields and optional filters. The dashboard requires authorized counts by
each org unit represented by the user's effective roles. NiceGUI forms and
detail pages require the combined organizational-role selector, owner,
pseudo-principal, move preview, and bulk-transfer ACL-reconciliation UI.

## 18. Verification requirements

Automated verification must cover at least:

### 18.1 Ownership

- root ownership derived from the selected effective role's org unit;
- child and record ownership copied from the parent;
- rejection of client-supplied or directly updated ownership;
- record ownership change during a move;
- atomic recursive ownership propagation during aggregation moves;
- rollback after any failed subtree update; and
- ownership history and snapshots.

Bulk-transfer tests must cover inactive-source and active-destination
validation, privilege and governance requirements, complete affected counts,
preserved placement, contextual ACL effects, source-role mapping/removal/retain
decisions, clearance and dependency validation, consolidation of duplicate
mapped grants, unresolved-plan rejection, failure rollback or safe resumption,
and immutable completion reporting.

### 18.2 Organizational-role selection

- one option per distinct effective role;
- repeated org-unit display when several effective roles belong to that unit;
- suppression of duplicate options caused by overlapping assignments to the
  same role;
- automatic selection with one eligible role;
- read-only selector state when the user has exactly one effective role;
- explicit selection with several eligible roles;
- owner derivation from the selected role for root creation;
- restriction to the parent's owning unit for child and record creation;
- rejection of ineffective, inactive, foreign-user, or wrong-org-unit roles;
- event attribution to the selected role; and
- prevention of arbitrary role selection.

### 18.3 ACL defaults

- exact creator aggregation grants from Section 9.1;
- exact org-unit-member aggregation grants from Section 9.2;
- exact creator record grants from Section 9.3;
- exact org-unit-member record grants from Section 9.4;
- absence of every permission listed as excluded;
- no creator-role `aggregation.acl.manage` or `record.acl.manage` grant in newly
  initialized local ACLs or default-child templates;
- preservation of existing ACL-management grants during the revision 1.5
  upgrade, including dormant local ACLs and default-child templates;
- complete permission dependencies;
- removable and re-addable `org_unit_members` grants; and
- unchanged historical ACLs during migration.

### 18.4 Dynamic membership

- a current effective role in the owning unit matches;
- a role in another unit does not match;
- future and expired assignments do not match;
- inactive roles and inactive org-unit hierarchies do not match;
- loss of the last qualifying assignment removes the match immediately;
- restoration of an effective assignment restores the match; and
- global privilege and clearance are still independently required.

### 18.5 ACL inheritance

- root ACL initialization;
- parent policy governing inherited children and records;
- no silent disabling of inheritance;
- dormant local ACL initialization for every new child and record;
- local-override activation of the last saved dormant ACL;
- preservation of local ACL edits across local-to-inherited-to-local
  round-trips;
- parent child-default initialization; and
- movement preserving valid effective ACL resolution after ownership changes.

### 18.6 Lifecycle and record integrity

- creator role may close an aggregation when global privilege and all other
  rules allow;
- creator role receives no reopen or security-level-change grant;
- only qualified information-governance access can reopen;
- initial security-level selection does not require a change permission;
- later security-level changes do require the existing change authorization;
- creator ACL defaults omit record metadata and component-mutation
  permissions;
- a later profile and ACL configuration can authorize those operations without
  an information-governance-only command restriction;
- creator role can view, download, share, and print when global privileges
  allow; and
- org-unit members can view and download but cannot share or print by default.

### 18.7 Dashboard reporting

- each distinct org unit represented by an effective role appears once;
- aggregation and record counts are separate;
- counts include only resources the user is authorized to view;
- an eligible unit with no authorized resources displays zero;
- future, expired, and ineffective roles do not add dashboard units; and
- counts refresh when assignments, ACLs, ownership, or resource visibility
  changes;
- the Records by medium chart uses exactly the physical, digital, mixed, and
  total record counts returned for those authorized unit rows; and
- the chart is additive and does not remove or weaken the existing holdings
  rows, their zero state, or their organizational-unit navigation;
- digital storage ranks no more than five eligible units individually and
  combines the remaining eligible units into one Other units summary; and
- digital storage includes components belonging only to records the caller is
  authorized to view within units represented by currently effective roles.

All database-backed tests must run only against a newly created, uniquely named
disposable PostgreSQL database initialized from the canonical schema or the
required migration path. Cleanup is mandatory whether the run passes or fails.

## 19. Advantages

The feature provides:

- explicit organizational custody and accountability;
- consistent ownership throughout every aggregation subtree;
- useful organizational search, filters, grouping, and reports;
- predictable ownership changes following structural moves;
- useful ACLs without routine manual setup;
- dynamic access for current members of the owning unit;
- automatic loss and restoration of the pseudo-principal match as role
  assignments change;
- creator access tied to a role rather than a person;
- conservative saved-record ACL defaults;
- routine aggregation closure without ordinary reopening rights;
- continued support for deliberate cross-unit access through named-role or
  `Everyone` grants; and
- a foundation for future custody-transfer or workspace features without
  implementing them now.

## 20. Limitations and risks

1. Ownership is not an isolation boundary and must not be presented as one.
2. Existing broad `Everyone` ACLs remain broad unless separately reviewed.
3. Users with several eligible roles select one combined org-unit-and-role
   option, even when several options display the same org unit.
4. `org_unit_members` requires changes throughout ACL storage, evaluation,
   editing, and explanations.
5. Moving content between owners dynamically changes which users match the
   pseudo-principal.
6. Aggregation subtree moves require recursive, transactional updates.
7. Stored record ownership is redundant and therefore requires strong
   database consistency enforcement.
8. Sensitive material may require removal of the default org-unit-member
   grants.
9. ACL inheritance means a child's creator does not necessarily receive a new
   effective grant when the parent policy says otherwise.
10. Users may still be confused when an ACL grant exists but a global privilege
    or clearance gate denies the operation.
11. Org-unit mergers, splits, and deactivation require explicit ownership
    policy and use of the exceptional bulk-transfer process.
12. Granting share and print to the creator role remains harmless only when the
    corresponding reserved global privileges are tightly controlled.

## 21. Recorded and remaining decisions

### 21.1 Recorded decisions

The review has established:

1. The field is named `owning_org_unit_id`.
2. Ownership is stored on both aggregations and records with enforced equality
   to the containing aggregation.
3. The stored pseudo-principal code is `org_unit_members`; its UI label is
   **All org unit members**.
4. The exact grant sets are those in Section 9.
5. Creation uses one combined **Create for** selector showing org unit and
   role. A unit appears once for each distinct effective role the user holds in
   it.
6. Child and record creation requires an effective role in the parent's owning
   org unit.
7. Every child and record receives a dormant local ACL containing its creator
   ACL-role and org-unit-member defaults while inheritance remains effective.
8. Record modification is governed by profiles and effective ACLs; this
   feature adds no information-governance-only command restriction.
9. Saving creates a record. There is no declaration or undeclaration state.
10. `record.component.share` and `record.component.print` remain reserved
    global privileges while appearing in the creator ACL default.
11. Moves that change ownership require a reason and explicit confirmation.
12. Defunct-unit bulk transfer is a separate exceptional operation.
13. Defunct-unit transfer automatically retargets `org_unit_members`, preserves
    `Everyone` and named roles from other units, and requires explicit
    reconciliation of every named role belonging to the defunct source unit.
14. **Create for** is the approved label for the combined
    **{org unit} — {role}** selector.
15. `organization.holdings.transfer` requires an effective information-
    governance role, the dedicated global privilege, sufficient clearance for
    all affected resources, a valid ACL reconciliation plan, a reason, and one
    explicit confirmation. It does not require dual approval.
16. Because the project is greenfield, existing development roots receive a
    deterministic best-effort role assignment based on title and description,
    with stable distribution as the fallback. Manual governance approval is
    not required for this development-data migration.
17. An ordinary ownership-changing move requires a reason and one explicit
    confirmation, with no additional size- or sensitivity-based approval.

### 21.2 Remaining decisions

No decisions remain open from the review items previously recorded in this
section. Further review may still revise the proposed privilege code or other
implementation details before the specification is approved.

## 22. Suggested phased implementation plan

Each phase must be independently reviewable and must end with a verification
gate. A later phase must not begin until the preceding phase's schema,
application behaviour, tests, and documentation agree.

Deployment may combine adjacent phases, but implementation should preserve
their dependency order. Partially implemented behaviour must remain behind a
disabled feature flag or otherwise unavailable to users until all requirements
for that behaviour are complete.

### Phase 0 — Design and catalogue preparation

Finalize the implementation contract before changing persisted data:

- approve this specification;
- confirm `organization.holdings.transfer` as the exceptional privilege code
  or approve its replacement;
- add the approved privilege and permission descriptions to the authorization
  catalogue design;
- confirm the **Create for** option format and end-user wording;
- approve the deterministic development-data ownership and role-assignment
  algorithm;
- inventory every aggregation and record create, move, search, browse,
  dashboard, export, ACL, and history path affected by ownership; and
- prepare migration rollback, monitoring, and verification procedures.

**Gate:** schema design, authorization changes, UI contract, migration
responsibility, and test matrix have been reviewed. No production behaviour has
changed.

### Phase 1 — Ownership schema foundation

Introduce ownership storage without enforcing completeness yet:

- add nullable `owning_org_unit_id` columns to `aggregations` and `records`;
- add foreign keys using `ON DELETE RESTRICT`;
- add owner-oriented indexes;
- add org-unit reference snapshots to event-history support;
- add consistency diagnostics for child aggregation and record ownership;
- add the equivalent definitions to the self-contained canonical schema; and
- expose no editable owner field to ordinary clients.

The upgrade migration uses nullable columns because historical roots do not yet
have approved owners. New empty databases may use the final definitions only
after all canonical-schema changes for the complete feature have been assembled
and verified.

**Gate:** migration and canonical-schema structures are equivalent, existing
data remains readable, foreign-key behaviour is verified, and diagnostics
identify every missing or inconsistent owner.

### Phase 2 — Existing-content ownership assignment

Assign owners to existing holdings:

- deterministically score each root against eligible org units and roles using
  its title and description;
- distribute tied or unmatched roots reproducibly across the stable eligible
  role list;
- record the selected role, derived org unit, score, and fallback reason;
- apply the derived owner to roots;
- propagate each root owner to every descendant aggregation and record;
- produce before-and-after counts by org unit; and
- stop and report any missing eligible role, orphan, cycle, or inconsistent
  result.

This phase changes ownership metadata only and retains the selected-role
mapping for Phase 6. It must not yet rewrite ACLs or change resource placement.

**Gate:** no aggregation or record has a null owner; every child and record
matches its containing aggregation; aggregate before-and-after counts reconcile;
and the deterministic mapping and execution report are retained.

### Phase 3 — Ownership invariants and runtime propagation

Make ownership reliable for ongoing operations:

- enforce non-null ownership on aggregations and records;
- enforce parent-child and aggregation-record equality in the database;
- derive child and record ownership during creation;
- reject direct ownership changes through ordinary update APIs;
- propagate ownership during record moves;
- propagate ownership atomically through aggregation-subtree moves;
- require a reason and one confirmation for ownership-changing moves; and
- record ownership creation and movement in immutable history.

This phase does not yet introduce `org_unit_members` or change ACL defaults.

**Gate:** create and move concurrency tests pass, failed moves roll back fully,
direct inconsistent writes are rejected, and event history reconstructs every
ownership change.

### Phase 4 — Ownership presentation, filters, and dashboard reporting

Expose ownership as organizational metadata:

- add concise owning-org-unit data to aggregation and record API responses;
- display ownership on detail and move-confirmation interfaces;
- add optional owner filters to search, browse, reporting, and exports;
- add separate authorized aggregation and record counts per eligible org unit
  to the dashboard;
- ensure counts include only resources the user may view; and
- update API-client models and relevant documentation.

Ownership remains a filter and reporting dimension, not an authorization
boundary.

**Gate:** filters, counts, pagination, exports, and dashboard results reconcile
with direct authorized queries, and no owner-based interface reveals an
otherwise inaccessible resource.

### Phase 5 — `org_unit_members` ACL principal

Introduce the new pseudo-principal end to end without yet making it a creation
default:

- extend all resource and child-default ACL tables and unique indexes;
- update principal constraints, validation, and permission-dependency checks;
- update PostgreSQL and Python authorization evaluation;
- update effective-ACL resolution and authorization explanations;
- update ACL request and response schemas;
- add **All org unit members** to the ACL editor using the approved accessible
  explanation;
- reserve the pseudo-principal code and label against real roles; and
- verify immediate membership changes after assignment or org-unit lifecycle
  changes.

Existing ACL rows remain unchanged in this phase.

**Gate:** the new principal is removable and re-addable, matches only effective
members of the resource's owner, observes privilege and clearance gates, and
behaves correctly in resource ACLs and both child-default ACL types.

### Phase 6 — Combined creation selector and ACL defaults

Enable the complete creation and default-ACL behaviour:

- add the **Create for** `{org unit} — {role}` selector;
- automatically populate it and make it read-only when exactly one effective
  role is eligible;
- deduplicate overlapping assignments to the same role while retaining
  separate options for separate roles in one unit;
- derive root ownership from the selected role's org unit;
- restrict child and record options to effective roles in the parent's owning
  unit;
- initialize root effective ACLs with the exact Section 9 grant sets;
- initialize parent child-aggregation and child-record defaults;
- initialize every new inherited child and record with the specified dormant
  local ACL;
- preserve live ACL inheritance as the effective policy by default; and
- audit the selected organizational role and initialized grants.

For greenfield development data, use the deterministic selected-role mapping
from Phase 2 to replace existing generated ACL contents with the applicable
Section 9 root, child-default, and dormant local defaults. Preserve inheritance
flags and placement. New resources receive the same defaults prospectively.

**Gate:** every grant and deliberate omission in Section 9 is verified; ACL
dependencies are complete; child inheritance and dormant local ACL behaviour
are verified; and users without an effective role in the parent owner cannot
create children or records.

**Implementation status:** Complete. Migration 049 applies the approved ACL
defaults to mapped greenfield holdings and installs the prospective creation
initializer. The API validates effective role choices and records the choice in
creation audit metadata. The aggregation and saved-record creation interfaces
use the combined selector, including automatic read-only selection when only
one role is eligible.

**Revision 1.5 amendment — implementation pending:** the completed phase above
describes the earlier defaults. Update prospective creation initialization to
omit creator-role ACL-management grants as required by Sections 9.1 and 9.3.
Verify the revised grant sets and preservation of all existing grants before
marking this amendment implemented. **Create for** selection remains unchanged.

### Phase 7 — Operational hardening and core-feature release

Complete the ordinary feature before considering exceptional bulk transfer:

- run the full authorization, clearance, lifecycle, concurrency, history,
  search, dashboard, and migration regression suites;
- test large ordinary subtree moves and measure query plans;
- verify cache invalidation and background-process behaviour;
- update administrator, governance, and end-user documentation;
- add monitoring for invariant violations and failed ownership propagation;
- rehearse deployment and rollback against a production-shaped disposable
  database; and
- complete security and information-governance review.

**Gate:** all acceptance criteria unrelated to defunct-unit bulk transfer pass.
At this point organizational ownership, filtering, dashboard reporting,
`org_unit_members`, creation defaults, and ordinary ownership-changing moves
form a complete deployable feature.

**Implementation status:** Complete. The security reconciliation endpoint
monitors ownership invariant violations alongside security hierarchy and
authorization-continuity findings. A production-shaped rehearsal verifies a
150-aggregation subtree with 150 records moves atomically across owners,
retains audit evidence, leaves diagnostics empty, meets the test latency
budget, and uses the owner/browse indexes. Canonical-schema, migration,
authorization, search, dashboard, lifecycle, concurrency, history,
backup/restore, import, and frontend regression gates pass. Wathiq maintains no
separate ownership authorization cache, so there is no stale cache to
invalidate; database invariants apply equally to API, background-worker,
scheduled-job, seed, and migration writes.

### Phase 8 — Exceptional defunct-unit bulk transfer (deferrable final phase)

Implement Section 6.7 only when the organization needs it:

- add `organization.holdings.transfer` to the privilege catalogue;
- implement source and destination eligibility checks;
- build inventory, impact preview, and ACL reconciliation planning;
- support explicit source-role mapping, removal, and exceptional retention;
- validate destination-role activity, clearance, and permission dependencies;
- implement atomic execution or a safely resumable governed batch;
- add immutable plan, progress, completion, and failure history;
- produce downloadable completion and exception reports; and
- add operational recovery and interruption tests at production-shaped scale.

Deferring this phase does not block deployment of Phases 0–7. Until Phase 8 is
implemented, defunct-unit holdings must be reassigned through an approved
administrative migration or other separately governed process; the UI and API
must not present a bulk-transfer action.

**Gate:** every source-unit named-role grant is resolved before execution,
ownership and ACL reconciliation cannot partially diverge, affected counts
reconcile, interruption recovery is proven, and the complete transfer is
historically reconstructable.

All database-backed verification in every phase must use a newly created,
uniquely named disposable PostgreSQL database initialized from the canonical
schema or required migration path. The test process must target only that
database, and cleanup is mandatory whether verification passes or fails.

## 23. Acceptance criteria

### 23.1 Core feature acceptance — Phases 0–7

The ordinary organizational-ownership and default-ACL feature is complete when:

- every aggregation and record has one valid owner;
- containment and owner values cannot diverge;
- creates and moves derive ownership exactly as specified;
- `org_unit_members` dynamically matches only effective members of the owning
  unit;
- all four default permission sets match Section 9 exactly;
- initial security-level selection does not require change authorization;
- later security-level changes remain governed operations;
- ordinary creators may close but not reopen aggregations by default;
- the creator and org-unit-member ACL defaults contain exactly the
  approved record permissions;
- ACL inheritance remains predictable and explainable;
- every new inherited child and record has the approved dormant local ACL;
- the dashboard reports authorized aggregation and record counts separately
  for each org unit represented by the user's effective roles;
- greenfield development ACLs are deterministically initialized from the
  approved defaults while inheritance flags are preserved;
- owner filters never replace resource authorization;
- all ownership and ACL changes are historically reconstructable; and
- canonical schema, migration, API, UI, documentation, and tests agree.

### 23.2 Exceptional bulk-transfer acceptance — Phase 8 only

If Phase 8 is implemented:

- exceptional defunct-unit bulk transfer is privileged, confirmed, complete,
  and auditable;
- every source-unit named-role grant is explicitly mapped, removed, or
  exceptionally retained before ownership changes;
- ownership and ACL reconciliation cannot partially diverge;
- completion and failure reports reconcile with the affected holdings; and
- interruption recovery and historical reconstruction are verified.
