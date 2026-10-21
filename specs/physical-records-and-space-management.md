# Physical Records and Space Management — Specification

**Status:** Review draft — D1–D10 and explicit additions approved; detailed recommendations remain for specification refinement; no implementation authorized  
**Prepared:** 21 October 2026  
**Project:** ERMS / Wathiq  
**Revision:** 0.27 — Scanner hardware note and application workflow explanations for bulk scan operations

## 1. Purpose and authority

Manage physical storage spaces, aggregation placement, inventory, movement,
requests, delivery, and return. This draft captures the requested capabilities
and proposes the detailed rules needed to implement them. Recommendations and
open decisions require approval before they become a product contract.

The [security specification](security-and-authorization-subsystem.md),ƒ
[location and medium draft](resource-medium-vital-status-review-and-location.md),
[event-history design](../docs/event-history.md),
[notifications specification](notifications-and-messaging.md), and
[WebUI performance contract](../docs/webui-performance.md) supply the existing
terminology and constraints. This document proposes replacing temporary
aggregation location codes with space references. It does not silently approve
or amend another draft or approved specification.

Requirement IDs identify proposed requirements for later implementation and
verification traceability. No requirement in this document is implemented or
verified merely by its inclusion here.

## 2. Scope and terms — SPM-01

A **space hierarchy** is an independently configured ordered selection of space
types. A **space** is a physical instance of one of those types. A **terminal
space** has the lowest configured type in its hierarchy. An unfinished branch
is not terminal merely because it currently has no children.

An **aggregation** is an individually requestable physical unit; its filing
hierarchy does not establish physical containment. D2 includes optional movable
**boxes** containing multiple aggregations, separate from fixed spaces, with
box scanning and movement subject to the recommendations below. Individual
record checkout, physical dimensions packing, RFID, offline synchronization,
external courier integration, and building access control remain outside the
proposed first release.
A worker badge identifies a user; it does not authenticate that user.

**Assigned location** is an aggregation's normal storage destination.
**Current location** is its presently registered physical space. **Custody**
identifies who holds or transports it and is separate from both references.

## 3. Hierarchies and codes — SPM-02

The allowed order is fixed:

| Order | Space type | Recommended prefix | Example |
| --- | --- | --- | --- |
| 1 | Site | `ST` | `ST01` |
| 2 | Building | `BL` | `BL01` |
| 3 | Floor | `F` | `F02` |
| 4 | Room | `RM` | `RM12` |
| 5 | Bay | `BY` | `BY03` |
| 6 | Row | `RW` | `RW04` |
| 7 | Shelf | `SH` | `SH07` |
| 8 | Slot | `SL` | `SL08` |

**Approved:** Site is mandatory and is the root type. New Sites start as Draft
and require explicit publication under section 4.2.1 before operational use. All descendant types may
be omitted while preserving order: `ST → BL → RM` and `ST → RM → SH` are valid;
`BL → RM` without a Site is invalid. Capacity and storage settings belong to
the specific Site consistently. The selected order cannot be reversed or repeated.
**D8 approved:** each hierarchy defines its selected types once and every branch
follows that template; a hierarchy may contain several Site roots. Different
branch templates require separate hierarchies.

Each non-root space has one parent of the immediately preceding configured
type, in the same hierarchy. Cycles, cross-hierarchy parent links, and parents
of the wrong type are rejected. A hierarchy has an immutable ID, unique code,
name, ordered types, active status, and concurrency version.

Recommended codes use uppercase ASCII and at least two digits for generated
numbers; widen naturally beyond 99. Permit meaningful exceptions such as `FG`
(ground floor), `FB01` (basement), or `RMARCH` (archive room). Codes identify
spaces rather than asserting their physical ordinal position.

Codes are case-insensitively unique among siblings; root codes are unique
within a hierarchy. A readable address includes hierarchy code and the entire
space path, for example `HQ/ST01/BL01/F02/RM12/BY03/RW04/SH07/SL08`.
References and machine labels use immutable IDs, so renaming a code does not
break assignments or labels. Do not reuse retired machine identifiers.

Changing a live hierarchy's template requires a preview and explicit migration
of affected assignments. Reject removal of a populated level or reparenting
that would invalidate location, security, capacity, or historical references.
Do not silently convert assigned intermediate spaces into nonterminal spaces.

### 3.1 Site hierarchy creation wizard — SPM-14, approved addition

Provide a wizard on each Site to automate creation of the descendant hierarchy.
Require `spaces.administer` and the corresponding Site scope. **The wizard is
available only when the Site has no sub-spaces at all.** Any existing descendant,
including an empty or deactivated space, blocks use regardless of whether it was
created manually or by a previous wizard run. This is a structural emptiness
check, not a check for stored holdings. Explain the restriction in the UI and
enforce it server-side when starting and committing generation. Serialize
creation against manual space creation and competing wizard runs so a Site
cannot cease to be empty between validation and creation. The wizard cannot
extend or fill gaps in an existing hierarchy. An idempotent retry of an already
committed operation returns that operation's result without creating again.

The administrator
selects the included descendant types in the fixed order and specifies the
number of children of each included type per parent of the preceding included
type. Site cannot be skipped; Building, Floor, Room, Bay, Row, Shelf, and Slot
can be skipped. Selection must agree with the hierarchy's D8 template; changing
an established template uses the approved restructuring workflow.

For example, skipping Building and Row produces these inputs:

- Floors per Site.
- Rooms per Floor.
- Bays per Room.
- Shelves per Bay.
- Slots per Shelf.

If Row is included, ask for Rows per Bay and Shelves per Row instead. If Floor
is omitted, Rooms are counted under the preceding included type, such as Site
or Building. Labels must name the actual parent, rather than assuming every
intermediate type exists. Counts are positive whole numbers for included types;
omission is explicit through type selection.

Generate the repeated structure and sibling codes using section 3's prefixes
and numbering, with readable names and valid parent links. The wizard must
collect or explicitly apply valid defaults for mandatory space attributes,
including security ceilings, and obey Site capacity and Box usage settings.
Before confirmation, preview selected types, per-parent counts, totals by type,
terminal capacity, example code paths, and required attribute values. For
example, 2 floors × 3 rooms × 2 bays × 5 shelves × 4 slots creates 6 rooms,
12 bays, 60 shelves, and 240 slots beneath the 2 floors.

Create only after confirmation, rechecking that the Site has no sub-spaces and
that its template is unchanged. Preview and generated-tree browsing remain
bounded and paginated; large totals must not require rendering the entire
prospective hierarchy at once. Record each created space in event history,
linked to the wizard operation.

After creation, the administrator may individually delete unwanted spaces when
they are completely empty, unassigned, and unreserved. This includes no physical
box or aggregation, no direct or effective assigned-location reference, and no
box-home or other live reservation. Recheck these conditions at commit to avoid
races with placement. Do not cascade-delete child spaces; prune empty branches
from their leaves upward. Deleting children does not change the configured
terminal type or make a now-childless intermediate space assignable. Preserve
historical evidence and never reuse deleted machine identifiers. A creation/audit
entry alone must not prevent deletion of an otherwise eligible generated space.

### 3.2 Site JSON export and import — SPM-16, approved addition

**Approved requirement:** export a built Site and its complete sub-space hierarchy
to a JSON file and import that definition into another Wathiq instance. Export
and import transfer space definitions, not the aggregations or boxes assigned
to them. The source Site need not be empty of holdings to export its definition.

The following transfer details are specification recommendations supporting the
approved requirement; they do not introduce another decision in the D1–D10 list
or authorize changes to the existing classification import/export contract.

**Transfer contents:** preserve the Site's code, name, address, telephone, contact
reference (subject to the export choice below), selected hierarchy types, and Site
settings (Box usage, box and
terminal capacity, loan duration, reminder and escalation settings). Preserve
all descendant spaces, parent relationships, physical storage ordering, types, codes, names, descriptions,
configured security ceilings (subject to the export choice below), activation
flags, and deactivation reasons,
including deactivated or currently unused spaces. Preserve maintained entity
translations where present. Export a consistent complete snapshot, independent
of UI filters, pagination, and expanded branches. Use a versioned UTF-8 JSON
format with explicit package-local references for Site, hierarchy, and parents;
final field schema is an implementation design deliverable.

**Excluded contents:** boxes, aggregations, records, contents/memberships,
current or assigned placements, reservations, custody, requests, inventory
sessions, movement history, notification deliveries, user accounts, credentials,
role assignments, and Site/aggregation permission grants. Do not transfer
occupancy counts, Full, inherited eligibility, or other computed state as stored
authority. Imported spaces start without holdings or reservations; recalculate
counts and eligibility from destination data. Preserve configuration, not
source workflow activity or source audit history. The Missing pseudo-space is
not part of any Site and is not exported as a descendant.

**Export choices — approved:** before generating the file, ask the exporting
user independently whether to **include** or **set to blank**:

1. Security level settings for the Site and every exported sub-space.
2. The Site's Contact User reference.

Either choice can be blank while the other is included. Blank means explicit
null values in the JSON, not a default security level, a default contact, or
inheritance of the source value. Do not retain the blanked reference's source
ID, identifying code, name, or matching metadata elsewhere in the package.
These choices affect only the exported file and never change the source Site
or its sub-spaces. Include enough matching reference data for values the user
chooses to export, without exporting user accounts or full security catalogues.

**Import reference resolution — approved:** check every included security level
and Contact User against the destination Wathiq database. When an unambiguous
matching entity exists, automatically assign its destination reference and show
the resolved assignment in the import preview. Do not reuse source database
primary keys as destination identities. Matching uses stable security codes and
user account identifiers, not display names; the exact interchange identifiers
must be documented in the final JSON schema.

For each included reference that does not exist, explicitly tell the importer
which Security Level or Contact User was not found in the destination and offer:

- **Specify replacements:** select the corresponding existing destination
  security levels or contact user through bounded selectors.
- **Cancel import:** stop without creating any Site or sub-spaces.

Do not silently pick a default, drop an unresolved reference, create an account,
or create a security level. Resolve all missing references before importing.
Ambiguous matches also require explicit resolution or cancellation. Reuse an
explicit security-level mapping for each occurrence of the same source level,
and validate parent/child ceilings against destination ordering after mapping.
Recheck that mapped entities still exist and remain valid at commit.

When a field was deliberately exported blank, identify it as **not supplied**,
not as a missing destination entity. Because Site contacts and space security
ceilings remain required, collect their values from existing destination users
and security levels before completion, or allow cancellation. Blank export does
not authorize creating an incomplete Site. Other configured external references,
such as responsible notification recipients, still require valid destination
mapping; source permissions and governance status are never imported.

**Destination identity and collisions:** recommend importing as a new Site,
with newly allocated destination IDs and scan identifiers; retain source-to-local
mapping as import provenance. Readable codes and names are preserved unless a
collision requires an explicitly reviewed replacement. Source printed labels
must not silently become destination identifiers. Do not overwrite, merge into,
or replace an existing populated hierarchy. Report Site/hierarchy code conflicts
and resolve them before creation. This is a definition-transfer operation, not
a synchronization or restoration of live physical inventory.

**Validation and execution:** show a preview of structure, totals, settings,
reference mappings, and conflicts. Apply the same required-field, mandatory-Site,
ordered-type, parent, uniqueness, security, capacity-setting, and Box usage
validation as normal creation. Reject unsupported format versions, broken
references, cycles, invalid counts/settings, and unexpected operational holdings
in the package rather than importing them. Validate the whole Site before
creating it; recommend atomic import per Site and idempotent retry. A failed
validation must leave no partially imported hierarchy. Define resource limits
and clear oversized-file errors in the implementation contract.

**Publication after import — approved:** the imported Site and every imported
sub-space begin again as **Draft in the destination Wathiq database**, regardless
of their publication status in the source database. Sub-spaces inherit this
Draft status from the imported Site; they do not require separate publication
workflows. Source publication status must never make imported spaces operational.
The destination Site administrator must review and explicitly publish the Site
under section 4.2.1 before it or its sub-spaces can be used operationally.
Preserve exported deactivation flags independently; import and later publication
do not implicitly reactivate spaces.

**Authority and audit:** recommend using `spaces.administer` with the applicable
Site administration scope for export and normal authorized Site-creation rules
for import, without new import/export privileges. The imported file does not supply authorization grants or governance status.
The normal approved creation rules in section 9.1.1 establish initial Site
permissions for the creating role. Record the export/import actor, time,
package version, operation correlation, and affected Site; imported space
creation uses local immutable history. Source history is not replayed as local
activity. Import does not relax the wizard rule: once imported sub-spaces exist,
the Site wizard is unavailable.

## 4. Space attributes and eligibility — SPM-03

| Attribute | Proposed meaning |
| --- | --- |
| Immutable ID | Stable reference independent of code and path |
| Code and name | Required concise code and human-readable label |
| Hierarchy, type, parent | Required structural references; parent absent only at root |
| Physical storage order | Ordering/continuity used for contiguous-space recommendations; independent of code/name sorting |
| Description | Optional physical directions or identifying notes |
| Maximum security level | Required reference to the existing ordered security catalogue |
| Publication status (Site only) | Draft or Published; sub-spaces inherit the Site's operational publication status |
| Deactivated | Local flag; blocks new assignments/placements in this space and descendants while preserving existing assignments and their loan/return |
| Deactivation reason | Required when deactivating; retained in history |
| Slot count | Derived number of descendant terminal slots, including self for a slot |
| Occupied/reserved/available slots | Derived counts with distinct meanings |
| Full | Derived physical occupancy indicator; not an editable checkbox |
| Effective eligibility | Derived active/security/capacity result with explanation |
| Barcode/QR identifier | Unique stable typed label identifier |
| Version and timestamps | Concurrency, creation, and modification evidence |

**Required Site details — SPM-15, approved addition:** every Site has a name,
address, telephone number, and contact person. The contact person is a reference
to a user in the system, not free text; use a bounded user search selector and
retain the selected user when the search changes. Store telephone numbers as
text to preserve international prefixes and formatting. Being named as a Site
contact grants no role, privilege, Site permission, approval authority, or
custody responsibility. Site creation and editing validate and retain these
fields alongside its required code and other mandatory space attributes.

Optional recommendations: responsible service team, additional building contact
details, environmental notes, accessibility instructions, and last completed
inventory timestamp. These do not introduce storage-condition
certification or an environmental monitoring workflow.

### 4.1 Security

A space permits holdings at its configured security level and below. Its
effective ceiling is the lowest ceiling on its ancestor path, including itself.
Child configuration above an ancestor ceiling is rejected as misleading.

Placement validates the highest security level of the physical holdings being
moved, including physically accompanying descendants and records; checking only
the parent aggregation's label is insufficient. Independently located child
aggregations are not automatically included in a move.

Reject lowering a ceiling or changing security ordering if any existing current
placement or assigned location would become incompatible. Show only authorized
conflict details. Security ceilings do not grant a user clearance or content
access. Classification changes to stored holdings must also preserve placement
compatibility; the UI must explain when relocation is required first.

### 4.2 Site publication and deactivation — approved

Publication and deactivation are independent. Publication marks the Site ready
for operational use; deactivation stops new assignments without withdrawing
existing holdings or their permitted loan/return workflows.

#### 4.2.1 Draft and Published Sites — SPM-17

Every newly created or imported Site starts as **Draft**. Authorized Site
administrators can configure it, build its hierarchy manually or with the wizard,
and review/edit/delete eligible sub-spaces. Draft Sites and their descendants
are unavailable to ordinary operational users and cannot be selected or used
for box or aggregation storage, assignment, reservations, moves, or physical
requests. Enforce this on the server, not only in selectors; direct IDs and scans
cannot bypass it. Administrative access still requires existing authority.

A Site administrator explicitly **publishes** the Site when construction and
configuration are complete. Require `spaces.administer` globally and for the
Site; no separate approver or publication privilege is introduced. Before
publication, validate required Site details, hierarchy integrity, security
settings, storage/Box usage compatibility, and at least one usable terminal
space. Apply existing rules for optional capacity limits; publication must not
silently make an optional setting mandatory. Revalidate against current versions
at commit. A failed validation leaves the Site Draft and reports the errors.

Publication makes the Site and its eligible sub-spaces available under existing
access rules. Each sub-space inherits the Site's publication status; no separate
per-space publication workflow exists. Publication does not override local or
ancestor deactivation, security ceilings, capacity, or permissions. Record the
publishing actor and timestamp in immutable history. The administrator's action
attests that setup is complete; structural validation alone does not establish
physical readiness. A Site already in use cannot revert to Draft; use
deactivation to stop new assignments while preserving ongoing operations.

#### 4.2.2 Deactivation preserves existing holdings and returns

Effective deactivation is the logical OR of local and ancestor flags, including
the hierarchy flag. Deactivating a Site therefore affects every space within it;
deactivating a sub-space affects that branch. Reactivating a child cannot
override a deactivated ancestor.

Do not allow additional boxes or aggregations to be assigned or newly placed in
an effectively deactivated space. Existing assignments, box memberships, home
claims, and reservations remain intact. Do not automatically evict, unassign,
reassign, or cancel existing loans when deactivating a space.

Continue to support requests, dispatch/loan, receipt, and return/reshelving of
aggregations already assigned there, subject to ordinary authorization,
security, capacity, and custody checks. Returning an already assigned item to
its retained home is allowed despite deactivation and is not a new assignment.
The same distinction applies to an already assigned box returning to its home.
Do not require reactivation or relocation merely to receive such a return.

Allow boxes and aggregations to move out to another eligible Site or space.
Permanent reassignment removes the old home claim; a subsequent attempt to
assign the item back into the deactivated branch is a new assignment and must
be rejected. A temporary absence that retains the original assignment preserves
the right to return. Moving an item into a different space within the same
deactivated branch is not an existing-home return and cannot bypass the new
assignment restriction. Existing reserved capacity remains protected throughout.

Display existing placements and assigned return destinations to authorized
users, including while deactivated. Operational selection and scanning distinguish
new placement from return to an existing home; server commands verify the retained
assignment rather than trusting a client-provided return label. Audit deactivation,
reactivation, retained-home returns, and outgoing movements under section 10.

### 4.3 Boxes, capacity, and reservations — approved D2 rules

**User-confirmed rules:** a slot holds one box, which may contain multiple
aggregations; the previous one-aggregation-per-slot proposal is rejected.
Aggregation capacity per box is configured for the specific mandatory Site. An aggregation away from its assigned location retains its
home reservation. A slot cannot be reused while any aggregation's effective
assigned location still references it. Track occupied, reserved, and available
separately. For slot-based storage, Full means all slots physically contain boxes.

The user approved the following capacity and box rules, with boxes optional
for direct storage in suitable terminal spaces:

- Model a box as a movable container with stable ID, code, barcode/QR label,
  current and assigned terminal-space references, and separately tracked current
  contents and assigned membership. A box is not another fixed hierarchy level.
  Aggregation locations continue to reference spaces, with box membership kept
  separately. A loaned aggregation retains its assigned box membership even
  though it is no longer physically inside that box.
- Set the default maximum aggregations per box to **4**, configurable on each
  Site. Different Sites may have different limits. Count the union
  of current contents and assigned members, deduplicated, when admitting a new
  aggregation, so temporary absence cannot consume another item's return place.
- Distinguish slot occupancy (one box) from box fullness (aggregation capacity).
  A slot containing an empty box is physically occupied. A shelf may be full of
  boxes while those boxes still have room for more aggregations. Show both facts.
- Reserve a slot for its assigned box and aggregations even if physically empty.
  Slot reuse requires no current box, no remaining box home claim, and no effective
  aggregation assigned-location reference. Returning the assigned box or adding
  an aggregation to that same box within capacity is not reuse by a different box.
  Occupancy and reservation can overlap; never add those counts as disjoint totals.
- Moving a box previews and updates the locations of its actual contents, not
  loaned/absent members. Permanent home reassignment separately previews all
  assigned members, including loaned items, retaining their actual custody and
  current location. Validate all contents, capacity, permissions, and security.
  Scanning a box identifies its registered contents; it does not certify that
  every expected item was physically inspected during an inventory.

#### Box codes and disposable-container lifecycle — approved

Boxes may be continuously added and physically disposed of when worn out or
torn. Every box receives an automatically generated tracking code, for example
`BX000001`, that identifies that physical container for its lifetime.

- Codes are unique across the Wathiq instance, not merely within a Site or shelf.
- Use `BX` followed by an increasing number padded to at least six digits.
  Six digits are a minimum display width, not a capacity limit; numbering expands
  naturally, for example from `BX999999` to `BX1000000`.
- Allocate numbers safely under concurrent creation. Never reuse a previously
  allocated code, including after retirement; gaps do not require renumbering.
- The code remains with the box when it moves between spaces or Sites. It does
  not encode its location and is displayed separately from the full space address.
- The registered box retains an immutable identity used by its barcode/QR label.
  Reprinting a damaged label preserves the same box code and scan identity.
- Replacing the physical box creates a new registered box with a new code and
  scan identity. Do not relabel the replacement with the retired box's code.

When replacing a damaged box, staff transfer its actual contents and assigned
memberships to the replacement through an authorized, audited operation. Update
current box references for transferred contents and assigned box references for
assigned members, including those away on loan. Preserve absent items' actual
current locations, current boxes, and custody. Space locations change only if
the replacement is placed or assigned somewhere different. Apply ordinary
capacity, security, membership, and location integrity checks to the transfer.

Retire the old box after its contents and assigned memberships have been
resolved. It cannot accept new contents, assigned members, or active placements.
Release the old box's own active occupancy and home claim as part of the
replacement, while preserving the replacement's and aggregations' reservations;
replacement in the same slot must not temporarily commit two occupying boxes.
Retirement does not delete history. Preserve the old code, its past placements,
contents and movements, and the link to the replacement box. Record the transfer
and retirement in box history and global history, with affected aggregation
membership/location changes also visible in each aggregation's history.

#### Aggregation box fields and location semantics

Each independently tracked physical or mixed aggregation supports two optional
box references in addition to its existing current and assigned space locations:

| Field | UI label | Meaning |
| --- | --- | --- |
| `current_box_id` | Current box | Reference to the box physically containing the aggregation; null when it is not in a box |
| `assigned_box_id` | Assigned box | Reference to the box in which the aggregation normally belongs and should be returned; null when it has no assigned box |

These are references to a registered box's immutable ID, displayed using its
human-readable code/number; they are not free-text box numbers. They record
current membership and assigned membership independently. A box's current and
assigned contents are obtained from these relationships, rather than maintained
as conflicting independent lists.

`current_location` and `assigned_location` continue to reference terminal spaces
(or the approved special states); neither field ever references a box. Examples:

| Arrangement | Current location | Current box | Assigned location | Assigned box |
| --- | --- | --- | --- | --- |
| Boxed in assigned slot | `HQ/ST01/RM01/SH07/SL03` | `BX000012` | `HQ/ST01/RM01/SH07/SL03` | `BX000012` |
| Boxed on terminal shelf without slots | `ARCH/ST02/RM01/SH07` | `BX000012` | `ARCH/ST02/RM01/SH07` | `BX000012` |
| Normally stored loose on terminal shelf | `ARCH/ST02/RM01/SH07` | Blank | `ARCH/ST02/RM01/SH07` | Blank |
| Individually loaned out of its assigned box | Outside registered spaces | Blank | `HQ/ST01/RM01/SH07/SL03` | `BX000012` |

Optional boxes therefore do not change what a location means. A terminal shelf
may hold both loose and boxed aggregations, subject to Site Box usage and
capacity settings. Slots continue to hold boxes only. Display the space and
box together where useful, for example **Box BX000012 —
HQ/ST01/RM01/SH07/SL03**. Current and assigned locations display the complete
address through all configured levels, never an ambiguous shelf/slot code alone.
The table illustrates alternative arrangements, not simultaneous placements.

Packing, unpacking, and transfer commands keep current membership and physical
location consistent in one transaction. Permanent packing/reassignment also
updates the assigned box and home space explicitly. An aggregation physically
in a box has the same current space as that box; its assigned box determines
the corresponding assigned home space. Removing an individual aggregation for
a loan clears its current box but retains its assigned box and assigned space.
Returning it records actual receipt and placement before restoring current box
membership; it must not appear inside the box merely because the loan ended.

Moving a box updates current locations only for its actual contents. Changing
the box's permanent home updates assigned locations for its assigned members,
including items away on loan, while preserving their actual current location,
current box, and custody. Record these changes in the affected aggregations'
histories and global event history. A box cannot be removed while a current or
assigned aggregation reference still depends on it.

### 4.4 Capacity without slots — approved D2 rules

Support a Site setting for maximum aggregations per terminal space of the
configured lowest type, for example 40 per terminal shelf or 200 per terminal
room. These are examples, not default values. Apply the Site setting to each
terminal space independently. Require a positive configured limit to enable
capacity enforcement and the Full indicator; an unset limit means capacity
unknown and Full unavailable, not unlimited proven capacity.

Count physical aggregations, whether loose or boxed, once; do not count the
box itself as another aggregation. Full means physical aggregation count has
reached capacity. Available capacity subtracts the distinct union of physically
present and home-assigned aggregations, preserving room for returns. Parent
Full is derived from its terminal descendants; if any applicable capacity is
unknown, do not assert a complete parent fullness result. Slot count remains
zero in a hierarchy without slots even though aggregation capacity is known.

A Site setting change must preview existing occupancy and reservations; reject
reductions below commitments rather than evicting holdings. Cross-site moves
validate the receiving Site's box and terminal-space limits before commit.
Serialize competing admissions to prevent capacity overbooking. Inherited
locations do not count intellectual descendants as additional physical units.

### 4.5 Optional boxes — approved D2 Site setting

**Approved requirement:** boxes are optional; aggregations may be stored directly
on a terminal shelf or another terminal space without slots. Box membership is
therefore optional and must not be required to request, scan, move, or reserve
an individual aggregation.

**Approved:** provide a Site setting named
**Box usage** with three choices: **Required**, **Optional**, and **Not used**.
Optional permits boxed and loose aggregations in the same terminal shelf or
other space without slots. Required requires a box for new storage placements;
Not used permits direct storage only. Preserve the approved rule that a slot
holds one box: a hierarchy ending in slots is incompatible with Not used, and
Optional does not permit loose placement into a slot. This does not authorize
placement on a nonterminal shelf above configured slots.

In spaces without slots, the same configured aggregation capacity includes both
loose items and box contents without double counting; each box additionally
respects its own capacity limit. Preview changes to Box usage and reject changes
incompatible with current holdings or assigned return commitments. These Site
settings are operational application data, not environment variables.

## 5. Aggregation locations and selection — SPM-04

Both stored location values become nullable references to terminal spaces or
the special **Missing** pseudo-space, with stable ID and readable label in
representations. Physical space references include their readable code path.
They may refer to different hierarchies. Do not persist a code string as the
authority.

**D9 approved:** inheritance applies separately
to current and assigned location, from the nearest ancestor aggregation with
an explicit value. Records expose read-only effective parent locations. An
explicit child override is never overwritten by changing its parent. Clearing
an override restores inheritance and therefore requires the same impact checks
as assigning a location. Existing digital-medium location values must be
reconciled explicitly; this draft does not silently prohibit them.

Determine separate physical tracking from existing metadata, without introducing
a separate physical-item flag. A physical or mixed aggregation with its own
explicit assigned location, current location, or both is tracked separately.
An explicit value counts even when it equals the inherited space. Missing and
Outside registered spaces are explicit states for this purpose, not empty
values. A child with neither explicit location derives its locations from its
parent and is not counted as another physical unit. Clearing only one override
does not end separate tracking while the other remains explicit; clearing both
restores inherited treatment, subject to the approved impact preview, custody,
box-membership, reservation, and integrity checks. Digital-only aggregations do
not consume physical aggregation capacity merely because they carry location
metadata. A root without locations remains unlocated; do not invent a containing
physical item or charge unknown placement to a space.

Capacity counts actual physical units identified by these rules. Separately
tracked physical aggregations each count at their effective physical locations,
while descendants that merely derive location from their containing physical
unit do not count again. Records display their containing aggregation's
effective locations without consuming additional aggregation capacity. Explicit
Missing and Outside registered spaces states never fall back to an ancestor's
location; absence of a physical-space reference does not mean inherit.

A parent-location change previews all affected inheriting aggregations and
records. Physical movement requires confirmation of which independently
tracked units actually accompany the parent. Intellectual containment alone
must never assert that a separately stored child physically moved.

Each selector supports bounded remote code/name/path search, hierarchy and type
filters, and branch-by-branch paginated browsing. Intermediate spaces navigate
and filter; only configured terminal types and the separate Missing option can
be selected. Retain selected
values across searches and fetch selected IDs individually. Show ancestors,
security ceiling, availability, inherited status, and why an option is disabled.
Draft Sites are excluded from operational location selection. Historical or
deactivated selections remain readable to authorized users; they cannot be
selected for new assignments, but an existing assigned home remains available
for its permitted return/reshelving workflow under section 4.2.2. Search and counts must not disclose inaccessible holdings.
Validate again at commit; a previously eligible search result is not a guarantee.

### 5.1 Missing pseudo-space — approved user requirement

Provide a special pseudo-space named **Missing** to mark physical items as
missing. It is available for both current location and assigned location. Every
command setting either location to Missing must include a non-blank reason;
this applies equally to individual edits, bulk commands, imports, and inventory
reconciliation. Bulk commands must retain the applicable reason for each affected
aggregation. Reject missing or whitespace-only reasons server-side.

Missing is an explicit value, not an unset/inherited location or a real terminal
space. It belongs outside the physical hierarchy and has no storage capacity,
security ceiling, or descendants. It cannot be used as a physical delivery or
reshelving destination. Selecting it does not bypass the governed location-change
authorization or audit requirements. Record the old and new value, reason, actor,
and time in aggregation and global event history as a missing-location declaration,
without claiming that a physical movement occurred.

Changing only current location to Missing preserves the assigned home; changing
assigned location to Missing requires an explicit change to that field. An
inventory discrepancy alone never sets Missing automatically. Missing is distinct
from known custody outside storage during an authorized loan or transit.

## 6. Bulk relocation and reassignment — SPM-05

Provide explicit modes:

1. **Move now:** update current location; retain assigned home.
2. **Reassign home:** update assigned location; do not claim a physical move.
3. **Relocate permanently:** update both after physical confirmation.

Select a source aggregation set or source space/subtree and a destination in the
same or another hierarchy. For a terminal destination, validate each selected
unit against its capacity. Under revised D2, a slot accepts one box; multiple
aggregations may share that box within its configured capacity. Do not place
multiple boxes in one slot or treat loose aggregations as boxes.

For a nonterminal destination, provide a reviewed mapping from each selected
unit to a terminal destination, including one-to-one source/destination branch
mapping where appropriate. Never guess mappings from similar codes or use an
intermediate node as a stored location. A preview shows source, destination,
mode, inherited effects, reservations, conflicts, and counts. Selection explicitly
states whether it matches current location, assigned location, or both.

Require reason, authorization on each affected unit, Published destination Site,
and active destination ancestry for new placements. The existing-home return
exception in section 4.2.2 permits deactivated ancestry without bypassing
security, capacity, custody/request compatibility, or fresh-version checks. Recheck
all at commit. **D10, amended by the later whole-group assignment requirement:**
every confirmed bulk assignment is atomic across the entire selected group of
boxes and aggregations. Reject the whole assignment on any conflict; do not
split one confirmation into independently committed batches. Internal batching
may be used only within the same transaction. If the selection exceeds supported
transaction limits, reject it before changing anything and report the limit.
These guarantees concern recorded changes, not reversal of physical handling
already performed. Retries use idempotency keys and return the original result
without repeating assignments, movements, or history events.

A stock relocation cannot bypass checkout or transfer custody implicitly. A home
reassignment for a loaned unit updates its planned return destination and notifies
responsible participants; its current custody remains unchanged.

### 6.1 Contiguous empty-space recommendations — SPM-18, approved addition

When assigning a selected group of boxes and/or aggregations to spaces within
a Site, offer **Recommend contiguous spaces**. Calculate capacity from the actual
selection and the chosen current/home/permanent assignment mode. Recommend
eligible runs of empty terminal spaces within that Site sufficient for the
whole group, and present the proposed item-to-space mapping for confirmation.
This action assists selection; it does not make assignments or reserve spaces.

Use the Site's configured physical storage order to determine consecutive
terminal spaces, respecting its hierarchy and omitted types. Preserve the full
paths in the recommendation so users can see shelf, row, room, and other
boundaries. Readable codes may be renamed and are not themselves proof of physical
adjacency: maintain storage ordering independently from code/name sorting.
Do not collapse occupied, reserved, deactivated, or otherwise ineligible gaps
and then describe the remaining scattered spaces as contiguous. Hierarchy
boundaries must not be treated as physically continuous unless the configured
storage order establishes that continuity.

An empty candidate has no current box or separately tracked physical aggregation.
It must also be unassigned and unreserved: a physically empty home retained for
a box or loaned aggregation is unavailable. Candidates must be in a Published
Site, have active ancestry, satisfy security ceilings for the proposed holdings,
and be usable under the caller's Site permissions and aggregation access.
Do not recommend Missing, Outside, intermediate spaces, or unfinished branches.

Apply the approved capacity rules, not merely a count of selected rows:

- A slot holds one box; box contents do not each consume another slot.
- Each box respects the destination Site's aggregation limit and retained member
  commitments. Separately selected contents of a selected box are deduplicated.
- For terminal spaces without slots, count loose aggregations and box contents
  under the configured terminal aggregation capacity without counting the box
  itself as another aggregation.
- Respect Required/Optional/Not used Box usage and current/assigned membership.
  Loose aggregations cannot be assigned directly to slots. A recommendation
  requiring boxed placement needs a valid, explicitly reviewed box grouping;
  do not silently create boxes or repack items.
- Unknown capacity cannot be represented as a verified fit for a requested group.

Show the complete assignment totals, required and available capacity, and full
addresses, with bounded/paginated candidate results. If no sufficiently large
contiguous eligible run exists, report that result without substituting a
scattered or partial allocation. Do not expose inaccessible holdings in conflict
or availability explanations.

On confirmation, re-read and validate the entire selected group, destination
spaces, current assignments/reservations, Site settings, security, permissions,
publication/deactivation state, storage order, and versions. Protect validation
and writes within one database transaction using appropriate locking or equivalent
serialization; a check followed by unlocked writes is insufficient. Competing
assignment paths, including manual and scanned commands, must participate in the
same occupancy/reservation integrity enforcement.

Either **all** selected box/aggregation assignments, affected membership/location
updates, reservations, and successful-change history commit, or **none** do.
Any stale recommendation or other conflict rolls back the whole operation, reports
the conflict safely, and lets the user request fresh recommendations. Never
silently choose a different destination after confirmation. Repeated confirmation
of the same operation returns its original result without duplicate changes.
This whole-group atomicity also applies to manually mapped bulk assignments;
requesting recommendations is optional.

## 7. Labels, scanning, and worker attribution — SPM-06

Support printed QR and Code 128 labels for every aggregation and space, with
human-readable code/path. Label payloads contain a versioned, typed opaque
identifier, not titles, security details, credentials, or mutable path strings.
Server resolution requires authentication and authorization. Labels are
identifiers, never bearer access tokens. Retired/replaced labels remain audited
and cannot silently resolve to a different entity.

Support keyboard-wedge scanners and an accessible manual-code fallback.
Camera scanning is recommended where supported, subject to explicit browser
permission. No offline execution is proposed.

A scan session declares its action and scope, scans the space, scans each
aggregation, and scans the worker badge before confirmation. The authenticated
operator remains the audit actor; the verified worker is recorded separately.
Badge scanning cannot impersonate a user, grant privileges, or approve a request.
**D6 approved:** the worker signs in using their own account and scans their own
badge. The badge must resolve to that same active authenticated user. Reject a
mismatch before confirmation. Record the user as both operator and performing
worker. Recording another person as the worker through a supervised workflow is
not supported in this release. This identity rule does not replace any action,
resource, or Site authorization check.

Wrong entity type, unknown or retired code, duplicate scan, inaccessible item,
and an ineligible destination produce clear safe feedback. Draft destinations
are ineligible; deactivated destinations allow only the existing-home returns
defined in section 4.2.2. Duplicate scans do not
increase counts. Scans stage evidence; only an authorized final command changes
locations. Store observed time and server receipt time separately where needed.
A failed network response must permit safe retry and recovery of session state.

### 7.1 Inventory — SPM-07

Scan the scope space, then every independently tracked physical aggregation
within the selected scope, then the worker. Declare direct-space or subtree
scope explicitly. Compare with registered current placement, not assigned home.
Capture the expected manifest/version at start and revalidate changes before
completion. Classify observations as found as expected, expected but not scanned,
found elsewhere, or unresolved/unauthorized. An incomplete survey must not label
unscanned items conclusively missing.

Inventory records observations and discrepancies; it does not automatically move
items, clear locations, or declare loss. An authorized reconciliation command
reviews each discrepancy and records any location correction with reason and
history. Do not expose restricted items through expected counts or scan results.
An operator lacking complete scope authorization cannot certify a complete
inventory; record the limited scope explicitly.

### 7.2 Scanned moves — SPM-08

Scan destination, scan units, scan worker, review source/destination and conflicts,
and confirm. Apply section 6's mode, mapping, transaction, and validation rules.
Use move-now as the proposed default; permanent reassignment is an explicit mode.
A scan cannot check out an already loaned unit or silently receive a return.

### 7.3 Additional recommended scan actions

- Pick-list verification before dispatch: confirm the requested units were picked.
- Delivery/return verification: match units and recipient or receiving worker to
  the active request before custody transitions.
- Reshelving verification: scan each unit and its assigned terminal destination.
- Label replacement: reprint a damaged box label with the same code and scan
  identity; replacing the physical box uses a new identity and the audited
  transfer/retirement process in section 4.3.

These recommendations require approval with the rest of this draft. A scan of a
worker or recipient badge alone does not prove physical handover; confirmation
records the authenticated operator's attestation.

### 7.4 Scanner hardware and application workflow note

This note explains how the section 7 workflows operate with scanner hardware.
It does not introduce a scanner-specific authorization system or expand the
status of the additional actions in section 7.3, which remain recommendations.

#### 7.4.1 Hardware and connection requirements

HID means **Human Interface Device**. In HID keyboard mode, a scanner sends the
decoded label text to the host as keyboard input. The scanner reads identifiers;
Wathiq determines the entity type, builds the operation, applies validation,
and performs the business transaction. A special bulk-operation scanner is not
required.

For the ordinary scanner integration, use a device that:

- Reads **Code 128 and QR codes**; select a **2D imager** explicitly supporting
  both, rather than a 1D-only reader.
- Supports **HID keyboard/keyboard-wedge input** on the chosen host device.
- Can append **Enter** after each decoded label to mark the end of the scan.

| Hardware arrangement | Connection to Wathiq |
| --- | --- |
| USB scanner | HID keyboard input to the browser on its connected computer |
| Bluetooth scanner | HID keyboard input to a compatible paired computer, tablet, or phone running the browser |
| Handheld mobile computer with integrated scanner | Browser on the handheld receives decoded scans through the manufacturer's keyboard-output facility, such as DataWedge |
| Phone/tablet camera | Requires camera decoding in Wathiq and browser camera permission; this is the separately recommended camera option, not HID input |

The HID path uses ordinary browser input and does not require a
manufacturer-specific scanner SDK. Verify the actual model's supported
symbologies, interface mode, host compatibility, keyboard layout, and suffix
configuration. Camera support and devices using proprietary interfaces need
their applicable application integration. The current workflows require an
online authenticated Wathiq session; collecting scans offline and uploading
them later is outside this release.

Manufacturer references: [keyboard-wedge input](https://docs.zebra.com/us/en/scanners/general/sp72-prg/c-sp72-keyboard-wedge-interface.html),
[Enter suffix](https://docs.zebra.com/us/en/scanners/multi-plane/mp72pg/r-mp72-enter-key.html),
[Bluetooth HID](https://docs.zebra.com/us/en/scanners/general/ds4-series/ds4678-prg/radio-communications/radio-communications-host-types/keyboard-emulation-%28hid%29/hid-bluetooth-low-energy-%28discoverable%29-.html),
[DataWedge keyboard output](https://techdocs.zebra.com/datawedge/7-6/guide/output/keystroke/),
and [example 2D scanner symbologies](https://prod-www.zebra.com/us/en/products/spec-sheets/scanners/general-purpose-scanners/handheld/ds4600-dpe.html).
These explain interface capabilities and are not a requirement to purchase a
particular brand or model.

#### 7.4.2 Common application interaction

The worker signs in and chooses the action before scanning. Wathiq displays the
expected next scan, for example **Scan space**, **Scan items**, then **Scan your
badge**. A focused scan input receives the identifier and Enter suffix. On each
complete scan, Wathiq resolves it server-side and updates the session's running
list, item count, full space addresses, box codes, and acceptance/error feedback.
The input remains ready for the next scan; support the same flow through manual
code entry. Handle scan framing and focus without relying solely on typing speed.

Keep **finish item scanning**, **worker verification**, and **confirm operation**
as deliberate application steps. Enter appended by the scanner completes one
scan; it must not submit the whole operation or activate an unrelated focused
button. Scanning a worker badge verifies the signed-in worker under D6 and is
not itself final confirmation. A scanner's decode beep only means it read a
label; Wathiq separately indicates whether the scan was accepted.

Reject wrong entity types for the current step, duplicate/retired identifiers,
and unauthorized items with the safe feedback described above. Deduplicate an
aggregation scanned individually and also included through a scanned box.
Resolve a box's actual contents for movement preview, excluding loaned members;
box scanning is not evidence of individual content inspection during inventory.
Scans stage a session and do not silently commit location or custody changes.

Before confirmation show the selected items, action, current/assigned effects,
destination mapping, worker identity, and applicable conflicts. Revalidate at
commit. Bulk assignment/movement of the confirmed group uses section 6's single
atomic transaction, including reservations and history; concurrent conflicts
commit none of it. Failed or lost responses permit recovery and idempotent retry,
not duplicate movement. Request workflows continue supporting explicitly selected
item subsets and partial delivery/return under section 8; do not silently omit
failed items from the group the worker confirmed.

#### 7.4.3 Interaction for each scan operation

| Operation | Worker/application sequence | Effect after confirmation |
| --- | --- | --- |
| **Inventory** — section 7.1 | Choose inventory and direct-space/subtree scope; scan scope space; scan each observed aggregation and any box being checked; finish scanning; scan own badge; review expected/found/unscanned/discrepancy results; submit | Save the observed inventory and attributed result. A box scan records the container, not proof of every expected content. Corrections or Missing declarations require the separate authorized reasoned action; no automatic movement follows inventory. |
| **Bulk assignment or movement** — sections 6 and 7.2 | Choose current/home/permanent mode; scan destination and successive boxes/aggregations; for several terminal destinations review the per-item mapping and scan/verify its spaces; finish; scan own badge; review; confirm | Recheck every item, placement, membership, permission, capacity, and reservation, then commit all selected assignments or none. A single slot cannot accept several boxes; an intermediate-space scan can scope mapping but cannot become the stored location. New home assignment alone never claims a physical move. |
| **Pick-list verification** — section 7.3 recommendation | Open the approved request/pick list; scan selected items as picked; finish; scan own badge; review mismatches and confirm verification | Record which approved items were picked. Picking alone does not prove dispatch, handover, or borrower receipt and does not start the four-day dispatch-relative clock. |
| **Dispatch** — section 8 | Open the eligible request and selected dispatch lines; scan/verify each departing item; finish; scan own badge; review destination/Taken to, custody, and dispatch details; confirm | Record actual dispatch, outside-space current state and custody for departing items, clear current box for individually removed items while retaining assigned membership/home, and establish each dispatched line's due timestamp under D5. Unapproved or conflicting requests cannot bypass review through scanning. |
| **Delivery/handover verification** — section 7.3 recommendation | Open the dispatched request lines; scan delivered items and verify the intended recipient, using a badge when available; scan performing worker's own badge; review and confirm actual handover | Record recipient, time, custody and delivered item lines. A recipient badge is an identifier, not authentication or proof that delivery happened; the authenticated worker confirms that fact. |
| **Return receipt verification** — section 7.3 recommendation | Open the outstanding loan lines; scan returned items and the receiving location when it is a registered space; scan receiving worker's own badge; review condition/discrepancies and confirm physical receipt | Record actual receipt and actual registered location or custody. Stop borrower return reminders for received items. Preserve assigned homes and keep reshelving outstanding until placement is confirmed. Returning to a retained home in a deactivated branch remains allowed. |
| **Reshelving verification** — section 7.3 recommendation | Scan the destination terminal space, the returned items, and the box when restoring box membership; repeat for distinct destinations; scan own badge; review against current assigned home/box and confirm | Verify actual placement and restore current space/box membership as applicable; mark only the confirmed lines reshelved. A different home requires the governed reassignment action, not silent acceptance of a mismatched scan. |
| **Label reprint** — sections 4.3 and 7.3 | Identify the existing entity by scanning or authorized lookup; select reprint; review identity and print | Produce a replacement label for the same registered identity. Reprinting does not move holdings or create a new physical box. |
| **Physical box replacement** — section 4.3 | Identify the old box and newly registered replacement; review actual contents and assigned members, including those away; scan/check transferred items, verify placement and own badge, then confirm replacement | Transfer the applicable current/assigned memberships, preserve absent items' actual custody/location, and retire the old box with linked history. The replacement has a new code/scan identity; apply the approved capacity, slot occupancy, reservation, and transaction rules. |

Each operation's resulting mutation or completed inventory/verification record
is attributable to its worker and authenticated actor through the existing event
history rules. Scanner input does not replace authorization, physical confirmation,
or server-side integrity enforcement.

## 8. Requests, loans, delivery, and return — SPM-09

A user submits a request for one or more authorized physical aggregations with
purpose, requested delivery/collection window, proposed return date, and delivery
instructions. Requested recipients must remain within their content clearance
and access rights. An administrator does not grant access by approving a loan.
**D3 approved:** physical aggregations are eligible for storage, movement, and
loans. Mixed aggregations are eligible for their physical holdings; their digital
content remains governed by existing access controls. Digital-only aggregations
are excluded from physical loans. Individual records cannot be checked out
independently in this release; request their containing aggregation instead.
Moving a parent aggregation affects only holdings physically accompanying it,
not separately stored children merely linked by the filing hierarchy. Moving a
box affects its actual contents and excludes absent or loaned members. These
rules do not remove legacy location metadata from digital-only aggregations.

Maintain a request header and independently tracked item lines; partial approval,
delivery, and return are possible and must not close outstanding lines.
Recommended line lifecycle:

`submitted → under_review → awaiting_approval (optional) → approved → preparing
→ in_transit → on_loan → return_in_transit → received → reshelved`.

`rejected` and `cancelled` apply before dispatch; after dispatch, use recall and
return rather than cancellation that erases custody. Overdue is derived from an
outstanding loan and its due timestamp, not a replacement lifecycle state.
Allowed transitions, actor, reason, timestamps, and versions are recorded.

**D4 approved:** the space administrator reviews availability, competing requested
periods, existing loans, access, and delivery feasibility. Use human reconciliation:
show conflicts, queue or reject with reason, or propose a changed window for
requester acceptance. No automatic priority is implied. Concurrent approval must
not create overlapping exclusive allocations for the same physical unit.
Ancestor/descendant requests conflict when they refer to the same physically
accompanying unit; filing ancestry alone does not make them identical units.

The administrator may approve routine requests directly or refer them to a
Records Manager (Information Governance Manager) or another authorized approver
with `physical_requests.approve`. Referral is discretionary initially; no automatic
approval requirement based on security category is introduced. Approval requires
an explicit recorded decision, never silence. Record referral, decision, and
reason; block dispatch while approval is outstanding.

Nobody may approve their own request, including a space administrator, **except
the Records Manager (Information Governance Manager)**. Recognize this exception
using the existing effective-role information-governance qualification, including
`roles.is_information_governance`. The user withdrew the proposed Profile-based
interpretation: do not relocate the flag to Profiles or introduce a Profile-name,
role-name, or role-code match for this exception. Preserve existing governance
qualification checks. The exception permits self-approval only; applicable approval authority,
view access, clearance, scope, availability, and integrity checks still apply.
Record use of this exception in the approval history. Changes to requested items,
recipient, or approved loan period require revalidation and renewed approval.

**Explicit access prerequisite:** users cannot request any aggregation they cannot
view under the existing privileges, effective resource permissions, and security
clearance rules. Apply the same view decision to selectors, searches, scans,
request submission, and direct API requests; knowledge of an ID is insufficient.
Revalidate recipient/requester access during approval and before dispatch. A
request or approval never grants access to an otherwise inaccessible aggregation.

Dispatch and handover record each item, sender/worker, recipient, actual times,
request line, and due timestamp. A planned delivery is not proof of delivery.
Returns record receipt and condition/discrepancy notes, followed by confirmed
reshelving to the current assigned location. Do not mark a loan complete merely
because a return was requested or an item arrived at a receiving desk.

Extensions require review, conflict checking, a reason, and any required renewed
approval. A recall records a revised return instruction and notifies participants;
it cannot retrospectively fabricate a physical return. Failed delivery retains
actual custody and requires a recorded next action.

### 8.1 Location while outside storage — D1 approved

A borrower and an in-transit shipment are not configured terminal storage spaces.
Keep custody/loan state separately and set effective current
location to explicitly **outside registered spaces** during those stages, with
its last confirmed space retained in movement history. Assigned location remains
the home. A receiving desk may be a real configured terminal space if desired.

This requires distinguishing an explicit outside-space current state from an
unset value that inherits. Use an explicit current-location mode
`inherit | space | missing | outside | unknown`; `space` references a physical
space and `missing` identifies the approved Missing pseudo-space. The precise
representation remains a technical design detail.
`outside` requires active custody evidence. Do not represent outside custody by
an ordinary null that accidentally inherits a storage location. Display custody
and last confirmed space together. No synthetic borrower-space records are
created automatically.

Provide an additional free-text **Taken to** field describing where the item has
been taken, for example “Sharjah Police” or “Sessions Courts”. Display it alongside
the outside-space current location and custodian. It describes the external
place or organization independently of the person responsible for custody; it
does not require creating a registered space. Capture its value and subsequent
changes in the relevant movement/custody history so historical destinations are
preserved when the item is returned or taken elsewhere. A previous destination
must not appear as the current destination after the item returns to storage.

D1 is approved with this additional destination field. Final API/database field
names remain implementation design details.

### 8.2 Due dates and notifications — SPM-10

**D5 approved:** a return deadline is required for each loaned aggregation.
The Site's default loan duration is **4 days after the dispatch date**. Confirm
the deadline or the dispatch-relative duration during approval and establish the
actual due timestamp on dispatch, rather than starting the clock at submission
or approval. An explicitly approved deadline takes precedence over the default;
changes to an approved deadline remain subject to D4. Track the deadline per
item line, including partial dispatches, as a timezone-aware timestamp and show
it in the user's preferred timezone.

Configure reminders per Site, defaulting to three days before, one day before,
at the deadline, and daily while overdue. Escalate to the responsible Records
Manager after seven overdue days, with that interval configurable per Site.
An approved extension replaces the reminder schedule. Confirmed physical receipt
stops borrower return reminders; reshelving remains an outstanding staff task.
Retain completed requests, approvals, custody, movements, and return evidence;
this feature introduces no automatic deletion of that history. Site defaults
must not silently rewrite deadlines already established for dispatched items.

Notify requester/borrower, responsible space administrators, assigned handling
workers, and the involved approver on relevant submission, conflict, referral,
decision, dispatch/delivery, changed due date, reminder, overdue, receipt, and
completion events. Resolve authorized responsible recipients rather than
broadcasting to everyone with a privilege. Deduplicate users across roles.
Notifications must not disclose protected item metadata after access changes.

Use the existing durable in-app notification subsystem with transactional
scheduling/outbox intent and retry-safe delivery. Workflow authority remains in
this subsystem, not a message's read or action-completion state. Email requires
the separately approved external-channel integration and is not assumed here.
Notification failure must not lose a due obligation or repeat a physical move.

## 9. Approved authorization model — SPM-11

Approved global privilege catalogue, granted through role Profiles:

| Privilege | Capability |
| --- | --- |
| `spaces.view` | Browse authorized space structure and operational details |
| `spaces.administer` | Create/import/publish Sites; configure hierarchies, spaces, ceilings, and activation; conduct inventories; grant/revoke Site permissions |
| `aggregation.location.change` | Existing implemented governed location capability; use for individual and bulk changes |
| `physical_requests.create` | Request authorized aggregations |
| `physical_requests.manage` | Review requests, reconcile conflicts, coordinate, extend, and recall |
| `physical_requests.approve` | Make a referred approval decision |
| `physical_requests.fulfil` | Pick, dispatch, hand over, receive, and reshelve |
| `physical_requests.view_all` | Inspect requests within operational scope rather than only own participation |

### 9.1 Resource and Site permissions — D7 approved

Use the existing `aggregation.view` global privilege and resource ACL permission
as the view prerequisite, together with clearance and the existing qualified
information-governance ACL bypass. The new resource ACL keys are:

| Aggregation ACL permission | Paired global privilege | Purpose |
| --- | --- | --- |
| `aggregation.physical_request.create` | `physical_requests.create` | Request this aggregation |
| `aggregation.physical_request.fulfil` | `physical_requests.fulfil` | Pick, dispatch, hand over, receive, or reshelve this aggregation |

Reuse the existing `aggregation.location.change` global privilege and ACL
permission for location changes, including movement, home reassignment, Missing,
and inventory reconciliation that changes placement. Fulfilment that changes
locations requires this gate in addition to the fulfilment gate. Inventory
observation requires `spaces.administer`, its Site scope, and aggregation view
access; it does not itself grant location-change access.
Request review and approval need view access, their respective global privilege,
and Site permission; no additional aggregation approve/manage ACL is proposed.
Ordinary requesters need the create privilege and request/view resource permissions,
not staff Site-operational grants merely to submit an eligible request.

Use these exact keys for role-to-Site grants, in a separate Site-permission
catalogue, reusing the corresponding global capability names:

- `spaces.view`
- `spaces.administer`
- `aggregation.location.change`
- `physical_requests.manage`
- `physical_requests.approve`
- `physical_requests.fulfil`
- `physical_requests.view_all`

A Site permission does not grant its global privilege, and neither replaces
aggregation view/access checks. Existing information-governance ACL bypass
retains its limits and does not automatically bypass this new Site scope.
Closed content may move through the existing governed location action without
reopening it. No `self_approve` privilege or role-name exception is introduced;
section 8 retains the existing role-based information-governance qualification.

D7 approves role-to-Site operational grants for browse, administration, inventory,
request management, approval, and fulfilment. These are grants to roles, not
direct grants to users or organizational units. With Site now mandatory, use the specific Site as
the operational scope boundary, covering its descendants. Global privilege and
Site scope are both required; cross-site operations require source and destination
scope.
Aggregation ACLs still apply independently. Global privileges alone must not
implicitly confer access to every storage site or its contents.

System administration does not automatically confer physical operations or loan
approval. Worker and recipient badges convey no authority. Own-request visibility
is limited to permitted participation and current content access. Revoked access
must block further lending and initiate authorized review of outstanding custody;
it must not erase the obligation or prevent authorized staff receiving a return.

### 9.1.1 Site creation and permission administration — approved clarification

The global `spaces.administer` privilege permits creating or importing a new
Site; no pre-existing Site grant is required for a Site that does not yet exist.
Grant the creating effective role all Site permissions corresponding to that
role's global privileges, atomically with Site creation, and audit those grants.
The creation command identifies the effective role used for creation.

A role with both the global `spaces.administer` privilege and that permission
on an existing Site may grant or revoke its Site permissions for itself and
other roles. No additional authorization administrator or
`authorization.administer` privilege is required. These grants cover the Site
and its descendants only; they cannot change Profiles, global privileges,
security clearance, or aggregation permissions. Every operation still checks
the corresponding global privilege, even if a Site permission has been granted.
Reject access changes that would leave the Site without an effective
administrator. Record Site permission changes in immutable history.

### 9.2 D7 clarification: labels, inventory, and built-in Profiles

D7 is approved, including these simplifications.
A space label is the physical barcode/QR label attached to a Site, room, shelf,
slot, or other space, plus its readable code. It is not the space's display name.

**Approved:** omit standalone `spaces.labels.manage` and
`aggregation.labels.manage` privileges, their Site grants, and the aggregation
label ACL. Printing/reprinting an existing label requires existing view
authorization for the entity and displayed metadata. Changing or retiring its
registered identifier requires relevant administration/edit authority and an
audit entry: space administration for spaces and existing aggregation
metadata-edit authorization for aggregations. Never reassign an old identifier
to a different entity.

**Approved:** do not introduce `spaces.inventory`. Inventory is part of
`spaces.administer`, subject to its Site scope and existing aggregation access
checks. This includes creating inventory sessions, recording scans, observations
and discrepancies, and submitting completed results with worker attribution and
history. Inventory does not itself authorize movements, setting Missing,
changing assigned locations, approving requests, or seeing inaccessible
aggregations. Location corrections still require `aggregation.location.change`
and a reason. A role without `spaces.administer` cannot submit an inventory.

**Approved:** provide one built-in reusable Profile, `SPACE_MANAGER`, for
administering spaces and Site settings, conducting inventory, governing location
changes, reviewing/coordinating requests, approving requests where authorized,
and fulfilling them. Do not introduce the previously proposed `SPACE_OPERATOR`
Profile in this release. `SPACE_MANAGER` contains the eight global privileges
listed in section 9, plus the existing `aggregation.view` prerequisite. Profile
assignment alone does not grant Site scope or aggregation ACL permissions.

The Profile does not confer information-governance status or override Site scope,
resource permissions, or clearance. Do not create a universal built-in Space
Supervisor role or automatically assign users. Administrators create ordinary
organization-owned Site-specific roles, attach `SPACE_MANAGER`, set clearance,
grant Site scopes and aggregation permissions, and assign workers. Existing
Records Manager roles continue using their existing governance mechanism.
Adding physical-operation privileges to existing Profiles requires an explicit
approved grant mapping. **Reaffirmed:** retain `roles.is_information_governance` on the Role. Profiles
define reusable capabilities, while Roles define organizational responsibilities;
roles sharing a Profile may have different governance designations. Profile edits
must not implicitly toggle that designation. See the [security specification's
rationale](security-and-authorization-subsystem.md#371-why-governance-status-belongs-to-the-role).
Existing governance qualification and clearance rules remain authoritative.

## 10. Event history and integrity — SPM-12

**Comprehensive audit coverage — approved:** capture every successful creation,
update, and deletion of a Site, sub-space, or box, and every box/aggregation
assignment, removal/unassignment, packing/unpacking, transfer, or movement.
Existing aggregation creation/update/deletion history remains mandatory. Include
Draft setup edits, wizard/import creation, publication, activation/deactivation,
Site settings/contact changes, and box replacement/retirement. A change to box
membership or assigned home is auditable even when the physical space is
unchanged. A deletion preserves the before-state and readable identity rather
than deleting its audit evidence.

Record these operations in global event history and the affected entity's history.
For a box operation affecting aggregations, record each affected aggregation's
membership/location effect and correlate it with the box operation. For Site or
space changes, retain the entity event and relevant reference snapshots. Capture
actor, time, operation, old/new values, applicable reason, and correlation ID.
Audit state changes in the same transaction as the change, including writes
outside the UI. Failed commands must not emit a successful-change event.

Every confirmed physical movement appears in the aggregation's event history and
the global Audit Trail, using the same underlying immutable event, rather than
two independently maintained logs. Bulk movement links per-aggregation events to
a common operation/session ID. Reuse `RESOURCE_LOCATION_CHANGED` for governed
location changes where semantically applicable; distinguish move, reassignment,
dispatch, handover, receipt, reshelving, and correction in structured metadata.
Custody changes without changed space IDs still require explicit domain events.
Final event codes require a consistent catalogue before implementation.

Capture authenticated actor, separately verified worker, recipient/custodian,
server timestamp, observed physical time, old/new explicit and effective space,
readable path snapshots, assigned-home changes, custody transition, reason,
request/line, scan session, correlation/idempotency identity, and authorization
basis. Do not place raw badge credentials in history. Renamed spaces must not
rewrite historical addresses.

Changes to inherited effective location must remain traceable from every affected
aggregation: append correlated impact events or provide an equivalently immutable
indexed history link. A parent event visible only on the parent is insufficient.
Records retain derived locations; this release does not claim individual record
movement or individual record custody evidence.

Audit hierarchy edits, publication, activation/security changes, label lifecycle, inventory
completion/reconciliation, request decisions, extensions, and due-date changes.
Database mutation and audit evidence commit together; audit failure rolls back
the mutation. Direct SQL cannot bypass structural, placement, occupancy, or audit
invariants. Scan observations never substitute for confirmed movement evidence.

Use concurrency control for slots, unit custody, request allocation, locations,
and hierarchy edits. Durable job state and retries must preserve exactly one
business result for a repeated confirmed command. Space deletion follows section 3.1: require empty, unassigned, unreserved
spaces and preserve historical evidence. Audit references alone must not block
cleanup; retain readable snapshots and retired machine identities without
requiring the live space row. Live operational dependencies must be resolved
before deletion. Deactivation remains available when deletion is ineligible.

## 11. UI, migration, and implementation boundaries — SPM-13

Proposed screens: hierarchy administration/browser with Draft/Published status and publication
validation; space detail with authorized
holdings and capacity; aggregation current/home selectors and movement history;
bulk move preview; scan workbench and inventory reconciliation; requester loans;
and administrator/approver/fulfilment work queues.

Use existing Wathiq table presentation, sortable server-paginated results,
bounded selectors, explicit loading/empty/error states, keyboard scanning focus,
English/LTR and Arabic/RTL support, and accessible status text. Page each hierarchy
branch independently. Never download all spaces, users, or aggregations to build
a selector or calculate inherited state. Define cache scope, keys, freshness,
invalidation, failure behavior, and identity/language isolation if adding caches.
Verify repeated navigation, abandoned background work, and freshness after moves.

Migration must inventory existing text codes and explicit/inherited values, build
an operator-reviewed mapping to terminal space IDs, and report ambiguous/unmapped
values. Do not infer a hierarchy by splitting text or silently discard unknown
codes. Preserve originals and migration evidence until reconciliation is approved;
ordinary new assignments use references only. Review inherited occupancy,
security mismatches, and existing current/home differences before enabling writes.
Reconcile this design with the earlier location draft and actual implemented state
before selecting migration sequence or API compatibility behavior.

Canonical schema changes belong independently in `database/schema.sql`; upgrade
migrations must preserve existing data. Seed event source is `seeding`. Any new
settings require all consumer-appropriate environment templates and documented
operator/restart guidance. Future UI catalogue changes must preserve curated
Arabic wording and provenance under the internationalization specification.
This draft changes no runtime configuration, schema, or translation artifacts.

## 12. Decisions required before approval

Review protocol requested by the user: present the existing D1–D10 decisions in
order, one at a time, with clarifications. Record the user's decision before
presenting the next. This list is fixed for this review; do not invent additional
decisions during the sequence. D1 is approved with a free-text Taken to field;
D2 is approved, including capacity, reservations, optional boxes, and all three
Site Box usage choices and their interaction with slots. Site is mandatory,
including for the later D8 review. D3 is approved for physical and mixed
aggregations, excluding independent record loans and digital-only loans, with
physical accompaniment confirmed. D4 is approved with the Records Manager
(Information Governance Manager) self-approval exception and an explicit existing
view-authorization prerequisite for requests. D5 is approved with a Site default
of four days after dispatch, configurable reminders and seven-day overdue
escalation, receipt-based reminder cessation, and retained history. D6 is
approved: worker badge and authenticated operator must identify the same user;
no supervised attribution in this release. D7 is approved, including one
SPACE_MANAGER Profile, Site grants, resource permission gates, and role-based
governance status. D8 is approved. The Site creation wizard and required Site
name/address/telephone/system-user contact are additionally approved; the wizard
requires a Site with no sub-spaces. D9 and D10 are approved in full. All ten
decisions in the fixed review list are complete. Site-definition JSON transfer
without assigned boxes or aggregations is also an approved addition, including
independent include/blank choices for security levels and Contact User and
automatic destination matching or explicit replacement/cancellation. The Missing
pseudo-space requirement in section 5.1 is already approved separately. Site
Draft/Published status, deactivation preserving existing assignments and
loan/return/outgoing moves, and comprehensive event history are approved additions.
Contiguous empty-space recommendations and atomic assignment of the entire
confirmed group are also approved; the latter supersedes D10's earlier allowance
for separately committed batches within a single bulk assignment.

| ID | Decision | Recommended starting point |
| --- | --- | --- |
| D1 — Approved | Current location during transit/loan; inheritance interaction | Explicit outside-space mode plus independent custody and free-text Taken to destination; retain assigned home |
| D2 — Approved | Optional boxes, Site capacity settings, and reservations | One box per slot; default 4 aggregations per box; retained home claims; configured no-slot capacity; Site Box usage Required/Optional/Not used with slot compatibility rules |
| D3 — Approved | Eligible units, medium, and physical accompaniment | Physical and mixed aggregation holdings; no digital-only or independent record loans; moves affect actual accompanying holdings and box contents only |
| D4 — Approved | Approval policy and conflict priority | Human conflict resolution; discretionary referral; no self-approval except Records Manager (Information Governance Manager); existing view authorization required; changes require renewed approval |
| D5 — Approved | Due-date defaults, reminders, escalation, and retention | Site default 4 days after dispatch; 3-day/1-day/due/daily reminders; escalation after 7 overdue days; approved extensions replace schedule; receipt stops borrower reminders; retain history |
| D6 — Approved | Worker identification and supervised scanning | Worker signs in and scans own badge; same active user recorded as operator and worker; reject mismatches; no supervised attribution |
| D7 — Approved | Operational authorization scope and Profiles | No separate label/inventory privileges; inventory under spaces.administer; one SPACE_MANAGER Profile; locally configured roles; global privilege + Site scope + aggregation access; retain governance flag on Role |
| D8 — Approved | Template consistency and restructuring | One selected-type template per hierarchy; reviewed remapping for live structure changes; Site wizard and eligible individual deletion added |
| D9 — Approved | Location inheritance and tracked units | Independent current/home inheritance; explicit child overrides; clearing restores inheritance with preview/checks; records derive parent location; count actual physical units only; Missing/outside never fall back |
| D10 — Approved, subsequently amended | Bulk transaction boundary | Preview/mapping and fresh checks; later requirement makes the entire confirmed bulk assignment atomic, including recommended or manual destinations; no partial batch commits; retry-safe confirmation |

The D1–D10 review is complete; do not reopen it or invent additional decision IDs.
Recommendations elsewhere not expressly covered by those approvals, including
detailed JSON interchange mechanics, remain identified as recommendations.
`SPACE_MANAGER` receives its approved section 9 capabilities; grants to other
existing Profiles are not automatic. API routes, payload schemas, hard batch
limits, and setting names remain technical specification work. No implementation
or verification completion is implied by approval of these product decisions.

## 13. Requirement-to-verification plan

All rows below are **planned; implementation and verification pending**. Future
handoff must link concrete schema/API/UI changes and executed evidence per ID.

| Requirement | Required verification evidence |
| --- | --- |
| SPM-01 Scope | Physical/mixed holdings eligible; digital-only loans and independent record loans rejected; box and parent moves exclude absent or separately stored members; no accidental record-level custody or filing-tree mutation |
| SPM-02 Hierarchies | Mandatory Site; omitted descendant levels; multiple Site roots/hierarchies; invalid order/cycle/type rejected; rename-safe IDs; populated restructure blocked |
| SPM-03 Attributes | Ancestor deactivation/security; reject new incoming assignments while preserving existing box/aggregation homes and reservations; permit their loan/return and outgoing moves; reject new assignment back after permanent reassignment; reject return-label spoofing; incompatible classification/ceiling edits; slot occupancy versus box fullness; retained slot and box membership reservations; configured no-slot aggregation capacity versus unknown capacity; nullable current_box_id/assigned_box_id references displayed by code; loose storage leaves box references blank; individual loan clears current box and retains assigned box/home; box-space consistency on packing and movement; assigned members away retain actual current state during box home changes; optional box membership and mixed loose/boxed capacity without double counting; root limit changes and cross-root moves; concurrent last-place contention |
| SPM-04 Locations | Separate tracking derived from physical/mixed medium and either explicit location, without a new flag; same-as-inherited explicit values remain separate; Missing/outside remain explicit; clearing one versus both overrides; unlocated roots and digital-only locations do not consume unknown physical capacity; terminal physical references and explicit Missing pseudo-space; mandatory non-blank Missing reason on either field and every write path; Missing does not inherit or claim physical movement; independent current/home hierarchy; inherited and overridden children; outside mode never inherits; free-text Taken to destination shown with custody and preserved historically without stale current destination after return; bounded selectors and inaccessible results |
| SPM-05 Bulk operations | All three modes; cross-site mapping; insufficient capacity/security; stale preview rolls back entire selected group; no partial commits through internal batching; oversized assignment rejected before mutation; idempotent retry; no physical move from home reassignment |
| SPM-06 Labels | Instance-wide increasing BX codes with minimum six digits; concurrent uniqueness and expansion beyond 999999; codes never reused; box moves preserve identity; label reprint preserves code/scan identity; physical replacement creates new identity; transfer includes loaned assigned members without false current movement; same-slot replacement preserves occupancy/reservations; retirement blocks new use and retains linked history; barcode/QR resolution; rename; retired/wrong/duplicate labels; USB/Bluetooth HID and handheld keyboard-output input; Code 128/QR 2D decoding; Enter terminates only the scan and cannot confirm the operation; focus, framing, application acceptance feedback versus scanner beep, manual fallback, and retry recovery; worker badge must match active authenticated operator; mismatch rejected; worker badge cannot authenticate or grant authority |
| SPM-07 Inventory | Space/items/own-badge/review submission flow; box scan does not certify contents; expected/found/unscanned discrepancies; incomplete and restricted manifests; concurrent movement; no silent location correction |
| SPM-08 Scanned movement | Destination/items/own-badge/review confirmation; deduplicate individual and box-contained items; single-slot/multi-box rejection and explicit multi-destination mapping; atomic failure; retry after lost response; no unintended loan transition |
| SPM-09 Requests | Concurrent/conflicting requests; referral blocks dispatch; self-approval denied except authorized Records Manager with recorded exception; inaccessible aggregations excluded and direct requests rejected; changed items/recipient/loan dates require renewed approval; partial item decisions/delivery/return; extension and recall; failed delivery; reshelving completion |
| SPM-10 Notifications | Default due date 4 days after actual dispatch per item, including partial dispatch; explicit approved deadline precedence; Site setting changes preserve existing deadlines; due/overdue computation across timezones; seven-day escalation; receipt stops borrower reminders while reshelving remains pending; completed history retained; changed due date cancels obsolete reminders; deduplication; restart/retry; access revocation; authorized recipient coverage |
| SPM-11 Authorization | Create/import with global spaces.administer and audited atomic initial role grants; Site administrator may grant/revoke own and other role Site permissions without authorization.administer; prevent last-administrator lockout; grants do not modify Profiles/clearance/aggregation ACLs; every global privilege/scope/ACL/clearance gate independently denied; cross-site scopes; closed resources; operator versus worker; no existence leakage |
| SPM-12 History | Every Site/sub-space/box creation, update, deletion, publication, activation/deactivation, and box/aggregation assignment/removal/move audited; unchanged-space membership changes captured; deletion history retained; every movement visible in aggregation/global history; inherited impacts; custody-only event; readable historical paths; audit failure rollback; direct SQL constraints |
| SPM-13 Delivery | Explicit legacy mapping; ambiguous migration blocks cutover; latest empty schema and upgrade path; LTR/RTL browser comparison; performance and translation checks |
| SPM-14 Site wizard | Site with zero sub-spaces required; manual, previous-wizard, empty, and deactivated descendants all block; server start/commit checks and concurrent manual/wizard creation exclusion; committed-operation retry returns prior result; required Site and ordered optional types; counts use actual selected parent; generated counts/code uniqueness; preview and mandatory attributes; Site settings/security validation; retry without duplication; existing data preserved; delete empty unassigned/unreserved leaves; reject occupied/reserved/assigned deletion including inherited references; concurrent placement protection; retained history; intermediate leaf remains unassignable |
| SPM-15 Site details | Required name/address/telephone/user contact; referenced user integrity; bounded search retains selected contact; telephone formatting preserved; contact grants no operational authority |
| SPM-16 Site JSON transfer | Complete Site/descendant definition round trip, including settings and inactive spaces; no boxes/aggregations/assignments/reservations or account/grant payloads; destination counts recalculated; four independent include/blank combinations; blank reference metadata absent and source unchanged; included destination matches assigned automatically; missing reference identified with replacement-or-cancel choice; blank mandatory values collected before completion; ambiguity, concurrent reference changes, and cancellation leave no partial Site; mandatory contact and security mappings; fresh identities and provenance; code conflicts and unsupported/malformed packages; authorization; failed import leaves no hierarchy; retry without duplication; local import/export audit; imported sub-spaces disable wizard; imported Site and every sub-space restart as Draft in the destination database regardless of source publication state; operational use blocked until destination Site publication; deactivation preserved independently |
| SPM-17 Site publication | New/manual/imported Sites start Draft; authorized administration permitted; ordinary operational visibility and assignments/reservations/moves/requests blocked in UI/API/scans; publication requires spaces.administer and Site scope without another approver; validate mandatory details, structure, security, compatible settings, and usable terminal space; stale or invalid publication remains Draft; sub-spaces inherit status; publication retains deactivation gates; used Site cannot revert to Draft; actor/time recorded |
| SPM-18 Contiguous recommendations | Actual group demand with deduplicated box contents; storage-order continuity and skipped levels; occupied/reserved/inactive gaps not hidden; slot/no-slot capacities and Box usage; unknown capacity not advertised as fit; Published and authorized candidates only; full-address mapping and no-fit result; recommendation makes no reservation; two competing confirmations cannot both allocate the same capacity; concurrent manual/scan assignment, security/settings changes, and stale order invalidate as appropriate; any conflict rolls back every item/reservation/event; no silent remapping or partial batching; retry returns original result |

All database-backed verification must use a newly created uniquely named
disposable PostgreSQL database, initialize it from canonical schema or the
required migration path, point every fixture/process exclusively to it, and
terminate connections/drop it after success or failure. Report creation or
cleanup failures. Never use persistent ERMS databases for these tests.
