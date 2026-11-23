# Aggregation and Record Types

**Status:** Approved. All planned phases verified locally as of 21 November 2026. [Final implementation, upgrade and performance evidence](../docs/verification/aggregation-record-types-phase-6.md)

**Prepared:** 22 October 2026  
**Updated specification approved:** 18 November 2026 — includes the revised
shared-saved-search behavior, set-based query approach, accepted read-path
trade-offs, and large-dataset performance requirements.
The administration privilege additions/default grants and type-field sorting
semantics below were also approved on 18 November 2026. Section 10 records
future discussion topics separately from the implementation scope.

**Implementation planning:** [Phased plan](aggregation-and-record-types-implementation-plan.md)
approved. See the [pre-feature baseline](../docs/verification/aggregation-record-types-phase-0.md) and [Phase 1 foundation results](../docs/verification/aggregation-record-types-phase-1.md).

**Project:** ERMS / Wathiq

## 1. Purpose and scope

Aggregations and records shall support optional administrator-defined types,
each with its own fields. This specification captures the behavior approved
in the product discussion, including static defaults and single-choice
dropdowns.

The existing [records-management contract](records-management-subsystem.md),
[security specification](security-and-authorization-subsystem.md),
[internationalization specification](internationalization-and-user-preferences.md),
[full-text search specification](full-text-search.md),
[advanced-search specification](advanced-search.md), and
[WebUI performance contract](../docs/webui-performance.md) remain authoritative
for their respective concerns except for the explicit extensions below.

## 2. Types and field definitions

Maintain separate aggregation-type and record-type catalogues. An aggregation
or record may have zero or one type from its corresponding catalogue.

A type has a stable internal identifier, a required name, an optional
description, and an ordered list of field definitions. Type names must be
unique within their resource kind in the application's default language.

Each field has a stable internal identifier, a required name, a data type,
a required/optional setting, a display order, and an optional static default.
Text fields additionally have a maximum character length. Single-choice fields
additionally have an ordered list of choices. Field names must be unique within
their type in the application's default language.

| Data type | Stored value |
| --- | --- |
| Text | One plain-text value |
| Integer | Whole number |
| Decimal | Exact decimal number |
| Boolean | True or false |
| Date | Calendar date without a time zone |
| Datetime | An instant represented by PostgreSQL `timestamptz` |
| Single choice | One stable choice ID from that field's defined choices |

Each field stores at most one value. Unset values are distinct from populated
values, including zero and false. Datetimes use existing user time-zone
preferences for display.

## 3. Languages

Type names, type descriptions, field names, and choice labels shall support
multiple languages, including English and Arabic. Names and choice labels
require a nonblank value in the application's default language; additional
translations are optional. Optional descriptions need not be populated.

Forms, details pages, selectors, and advanced-search controls display these
definitions in the user's interface language using the application's
established language fallback rules. Data-type labels use interface
translations; underlying data types remain language-independent.

Definition identity, stored selections, and saved-search references use stable
IDs, never translated wording. Renaming or translating a definition or choice
must not alter existing values or invalidate saved searches.

Text-field values and text defaults store one literal value only. Do not
implement per-language values, translated text defaults, or automatic
translation of text-field content. The same stored text is presented to all
users, regardless of interface language. Other scalar values remain
language-independent and use the application's existing localized presentation.

The definition editor, resource editor and Advanced Search criterion editor
share type-aware controls. Signed integers retain the full PostgreSQL bigint
range. Decimal entry preserves the literal precision, including exponents.
Allow intermediate numeric edits such as a leading minus sign and reject
incomplete values on submission. Date and datetime controls validate calendar
values. Boolean and single-choice controls accept only the offered values.

## 4. Text length and required fields

Text fields require a positive maximum character length. The field-definition
form initially suggests 255 characters. Both type editors use a number control
with direct digit entry and increment/decrement buttons. An edit that would
put the limit outside 1 through 2,147,483,647 leaves the previous value in
place. Administrators can clear the control while editing. Saving requires
a value in range. The API and UI count text length in Unicode characters.

- A maximum of 255 characters or fewer uses a single-line text box.
- A maximum above 255 uses a multiline text area.
- Values exceeding the maximum are rejected, never silently truncated.
- Reducing a maximum is rejected if any existing value exceeds the new limit.

Administrators specify whether each field is **required** or **optional**.
When a type is assigned, all its required fields must have valid values before
resource creation or a metadata update succeeds. Required text cannot be empty
or whitespace-only. Zero and false satisfy required fields; null does not.
Optional fields may remain unset. API and form validation must agree.

Adding a required field or changing an optional field to required preserves
existing resources and their values. All required fields are enforced on the
next successful metadata update. Unrelated operations, such as downloading
content, do not trigger this validation. Administration shall explain this
effect before saving the definition change.

## 5. Static defaults

A field may define one literal default matching its declared data type and
constraints. A text default is subject to the field's maximum length. A
single-choice default references a choice ID belonging to that field. Zero and
false are valid defaults and must not be confused with the absence of a default.

Defaults initialize fields when a type is first assigned to a resource,
including assignment during creation or changing to another type. They are
editable initial values: users may override or clear them subject to required
field validation. A submitted value takes precedence, and an explicitly cleared
value must not be silently restored by default application. API and UI behavior
must agree.

Changing a default affects future type assignments only. Ordinary updates,
changes to field definitions, and adding fields to an already assigned type
must not backfill defaults into existing resources. Existing resources missing
a newly required value follow section 4.

Defaults are not expressions. Dynamic defaults such as today's date, the
current time, or the current user are deferred.

## 6. Single-choice dropdowns

Administrators define ordered choices for a single-choice field. Each choice
has a stable internal ID and translated labels as described in section 3.
Resources store only the selected ID. A supplied choice must belong to that
field; arbitrary labels and IDs from other fields are invalid.

Only one choice can be selected. Required/optional and default behavior follows
sections 4 and 5. Forms use a single-choice dropdown; details and search
controls show the label in the user's interface language.

Choices may be renamed, translated, and reordered without changing existing
selections. Deleting a choice is blocked while stored values reference it.
A choice referenced by a default cannot be removed without clearing or changing
that default. Definitions must never retain a dangling default reference.

Multiple selection, dependent dropdowns, and choices fetched from other
entities are explicitly deferred.

**Approved choice-entry rule.**
Keep single-choice values restricted to administrator-defined choices in this
version. This preserves stable IDs, consistent filtering, translated labels,
and predictable ordering. Accepting arbitrary strings in the same field would
introduce a second value representation and require additional rules for
validation, search, sorting, duplicates, and later promotion to defined choices.

An administrator can already define a normal choice labelled **Other** and a
separate optional text field, such as **Other document category**. For example,
`Document category = Other` and `Other document category = Inspection log`.
The dropdown still stores the Other choice's stable ID; the companion field
stores one untranslated text value. It follows normal text validation/search
rules, while the dropdown follows choice filtering and ordering.

Both controls remain visible and independent. Conditional display, conditional
requiredness and automatic clearing of a companion field are deferred for
later specification. The dropdown accepts predefined choice IDs only.

## 7. Assignment, authorization, and definition changes

### 7.1 Definition administration

The resource-type implementation introduced two global privileges.

| Privilege code | English display name | UI group |
| --- | --- | --- |
| `aggregation_types.administer` | Administer aggregation types | Administration |
| `record_types.administer` | Administer record types | Administration |

Each privilege authorizes creating and maintaining definitions for its resource
kind, including fields, choices, translations, defaults, and See/Use role grants.

Grant both by default to `INFO_GOV_MGR`, `INFO_GOV_OFFICER`, and `ALL_PRIVS`.
Other profiles receive them only through explicit profile administration.
Fresh-install seeds and populated upgrades must establish these grants while
preserving unrelated/custom profile grants and role assignments. Do not infer
these capabilities from the governance flag alone.

Authority to administer a definition does not independently authorize viewing
or changing resources of that type. This keeps catalogue maintenance separate
from access to business information. Governance See/Use bypass likewise does
not itself grant definition administration.

**Rationale:** Business metadata administration is a distinct capability from
editing individual resources or administering the whole authorization system.
The two privileges permit separate aggregation/record delegation without
requiring `authorization.administer`. Default grants to both governance
profiles fit their existing classification-administration duties; `ALL_PRIVS`
continues to contain the full catalogue.

**Examples:** An administrator with `record_types.administer` can add a record-type
field or configure its See roles, but must still pass all resource gates to
open a record. A role with `record.modify` and Use access can edit an authorized
record's values but cannot change its field definitions. A custom governance
role without either administration privilege bypasses See/Use restrictions
within its permitted scope, but cannot maintain the type catalogue.

### 7.2 See and Use role grants

Each type defines two allow-only role grants:

| Setting | Meaning, subject to all remaining authorization gates |
| --- | --- |
| **Who can see this type** | View resources of this type and reference the type or its fields in Advanced Search conditions and sorting |
| **Who can use this type** | Create, edit, delete, or otherwise mutate resources of this type |

Use requires See for the same role. Selecting Use also selects See; removing
See requires removing Use. The server enforces this invariant. An empty See
list grants no ordinary visibility; an empty Use list grants no ordinary
mutation authority. Governance bypass is defined in section 7.4.

The **Role access** dialog lists configured grants. **Add** opens a server-paged
directory of all principals still available, including Everyone. Both the
configured-grants table and the picker support case-insensitive substring
searches across role codes, names and translated names before pagination.
Everyone is searchable by its name and translations. An administrator can choose See for one
role and See and Use for another in the same dialog. Selections survive paging,
sorting and new searches. Add saves the entire selection in one version-checked
transaction so a stale policy or an unavailable role cannot leave a partially
applied change. Cancel discards all pending selections. To remove an existing
grant, edit its row and clear See. Other grants are preserved. Existing types
acquire no Everyone grant on upgrade. [Role access guide](../docs/security-authorization-operations.md#configure-access-to-aggregation-and-record-types)

Everyone matches an authenticated account that has passed the effective-role
gate. Its grant combines with named-role grants. For example, Everyone can See
Employee File while only Personnel Officers have an explicit Use grant. An officer
still needs the applicable privilege, clearance and resource ACL. Removing Everyone
immediately restores the named-role policy, including on the next search page.

Evaluate named grants against the user's **current effective roles**, using the
existing assignment, account, role, and organization rules. Any matching role
satisfies the relevant grant; a nonmatching role never vetoes another role.
Keep the complete effective-role set for subsequent gates. The role supplying
type access may differ from those supplying global privileges, clearance, and
ACL access. Filtering the role set by type would incorrectly change existing
union-based authorization.

Add one **Resource type** gate immediately after Effective role assignment and
before Resource state rules:

Authentication → Effective roles → Resource type → Resource state rules →
Global privilege → Security clearance → Resource ACL.

The gate checks See or Use according to the operation. Untyped resources pass
it as **Not applicable** and retain existing authorization. Types and values
are not inherited from parent aggregations. A child's own type controls its
type gate; existing parent/child authorization requirements still apply.

### 7.3 Operation coverage

| Operation | Required type access |
| --- | --- |
| View, list, search, count, or disclose a resource | See its current type |
| Create a typed resource, including committing a draft or copying/importing one | Use the selected type |
| Edit primary or type-specific metadata; delete a resource | Use its current type |
| Assign a type to an untyped resource | Use the destination type |
| Reassign type A to B | Use both A and B |
| Remove a type | Use the current type |
| Other mutations, including moves, closure/reopening, ACL or security-level changes, and component changes | Use each affected resource's type, alongside existing operation-specific checks |
| Read or retrieve a record's components | See the owning record's type, alongside existing component permissions |
| Reference a type or its fields in a query condition or sort | See every explicitly referenced type |

Both source and destination checks on reassignment prevent escaping a type
restriction by relabelling a resource. Type grants add prerequisites; they do
not create new operations or override existing privileges, lifecycle rules,
clearance, ACLs, or component permissions. The operation-policy inventory must
map each affected endpoint to these requirements, including bulk operations.

See restrictions apply consistently to direct URLs, API responses, lists,
counts, search results, favourites, relationships, navigation, exports, and
component access. Apply them before counts, ranking, pagination, and result
caps. Hiding a type in a selector alone is insufficient: other entry points
would still disclose its resources.

### 7.4 Information-governance bypass

Effective information-governance roles bypass **both See and Use restrictions
for every type**, as well as the existing resource ACL gate. No explicit type
grant is needed. When accessing a resource, the qualifying governance role
must itself have sufficient clearance, following the existing governance rule;
another role cannot lend it clearance. Type definitions have no resource
security level, so an effective governance role may reference any type in a
query, while each result still passes resource clearance and all other gates.

This does not bypass authentication, role effectiveness, required global
privileges, clearance, lifecycle/integrity rules, or custody continuity. It
does not confer type-definition administration without the privileges in
section 7.1. Existing specific lifecycle exceptions remain unchanged.

Governance staff need access across types to perform records custody and
oversight. Requiring grants on every present and future type would make those
duties depend on incidental catalogue configuration. Keep security clearance
and operation privileges as the existing independent limits on that mandate.

The access explanation adds the Resource type gate in the stated position,
identifies the required See/Use access and contributing roles, and identifies
governance bypass when used. Existing restrictions on explanation disclosure
and security-sensitive audit events apply.

### 7.5 Custody continuity, policy changes, and freshness

Type-policy changes and type assignment, reassignment, or removal participate
in existing transactional custody-continuity checks. Evaluate the proposed
post-change state and reject a change that leaves an affected resource without
an authorized human custodian. Governance bypass means a restrictive type list
alone cannot exclude a qualified governor; it does not replace checks for
effective assignments, privileges, clearance, and continuous custody.

Audit role-grant changes and type changes through existing event-history
conventions. Type-policy changes, reassignment, and role-effectiveness changes
must participate in authorization freshness and cache invalidation. Recheck
current access on execution and paging; old results or capabilities never
preserve revoked access. Retain the existing search-cache scope and contract.

#### Historical values after reassignment — approved 19 November 2026

For both aggregations and records, a viewer who is authorized to read the resource’s history may see that it moved from type A to type B, including the names of both types. Naming A in this event does not confer permission to open other resources of type A or to use A in a search.

Apply the viewer’s **current See access independently to each historical side**. A side with a type requires an effective See grant for that type or an effective governance role with sufficient clearance for the resource on that side. An untyped side has no type restriction. Existing history, resource and clearance checks still apply. Use and type-administration privileges are unnecessary for this read.

For example, an Investigation record becomes a Correspondence record. An authorized history viewer with See on Correspondence alone sees the transition, the two type names and the permitted Correspondence values. The Investigation side identifies its type and indicates that its values are withheld. It exposes no former record values, selected choice IDs or selected labels. The same rule applies to ordinary resource snapshots and to the separate type-metadata event. A later grant or revocation changes the next history read. Preserve the original evidence in the immutable event, subject to existing destruction rules.

The transition explains how the resource acquired its current type. A catalogue name identifies a category. A stored field value, including a selected choice, discloses information about a particular resource. Checking the two sides separately preserves this distinction and lets an auditor distinguish a withheld value from one that was never entered. If the viewer cannot access the resource or its history, the existing denial and whole-event redaction rules continue to apply.

### 7.6 Shared enforcement and verification

**Approved approach — 18 November 2026:** Extend the existing set-based query
structure. For a search or resource-list query, resolve effective roles,
privileges, clearance, and type access once within the SQL query and reuse
those authorization sets across candidate resources, alongside ACL checks.
Filter unauthorized resources before counting, sorting/ranking, pagination,
and result caps. Do not fetch candidates and authorize them in Python or the UI.

The new type gate must not add a database round trip per resource, repeated
permission-function evaluation per candidate, or independent repetition of
authorization work across query branches. Reuse the query's existing role and
authority context to derive type access as a set. Each subsequent paging
request checks current permissions using the same batched approach; cached
IDs or results never preserve revoked access.

This is a query-execution requirement, not a requirement that the entire HTTP
request execute one SQL statement or that every authorization path use one
database function. Python evaluation, database functions, and SQL-building code
may express the same policy in the forms appropriate to their responsibilities.
Keep equivalent decisions through shared helpers where useful and differential
tests; no general consolidation or policy-code generator is required.

The user accepts the existing repeated work for page enrichment, separate
record/aggregation paging batches, non-tab fallback count/result and per-item
attribution queries, and some relationship/index-freshness checks. Eliminating
those cases is not a prerequisite for this feature. They are specified exceptions
to the once-per-query objective, not permission for the new type gate to add
per-resource queries or repeated type-access resolution. Within each affected
query, add type access as a reusable set, including in existing fallback paths.

Creation, update, and deletion are outside this particular query-efficiency
concern. They still enforce all type, lifecycle, privilege, clearance, ACL,
transaction, and custody requirements; their implementation need not use the
same batching strategy as search.

**Rationale:** Shared SQL sets avoid database work that grows with every
candidate, preserve complete authorized counts and ranking, and fit the
existing measured search design. Accepting the current extra read stages keeps
this feature focused; fresh checks on later requests preserve revocation.

[Resource-type authorization design](resource-type-authorization-design.md)
records the inspection, accepted trade-offs, and integration guidance. This
decision supersedes the earlier proposal requiring one authoritative database
evaluator for every path. Approval is not implementation or performance evidence.

### 7.7 Assignment and value changes

Only fields belonging to the assigned type may contain values. Untyped
resources have no type-specific values. Invalid assignments or values are
rejected without partial saves.

Changing or removing a type clears the old type's current values. When values
will be cleared, require explicit confirmation. Do not map values by matching
field names. Save the type change and values atomically and capture the change
and affected values through existing event-history conventions. Defaults for a
newly assigned type follow section 5.

Field positions start at 1 and are unique and consecutive within each aggregation or record type. A new field goes last by default. For a type with N fields, Display order accepts whole numbers from 1 through N when editing and 1 through N + 1 when adding. The editor enforces this range during entry and on Save, using the total field count across all pages and filters. Entering an occupied position inserts the field there and shifts the intervening fields. Moving or deleting a field closes its previous position. The Fields table provides Move earlier and Move later arrows in the unfiltered ascending display order, including across page boundaries. Each arrow swaps the field with its immediate neighbor. Each move uses the current type version so concurrent edits cannot silently overwrite one another.

For example, inserting a field at position 2 in a three-field type moves the former second and third fields to 3 and 4. Migration 122 gives existing fields consecutive positions in their previously displayed order, breaking old ties by field ID. Field IDs, stored values, and choice order are preserved.

Administrators may add fields and rename, translate, or reorder definitions.
Existing resources initially have no value for added fields. A field's data
type may change only when it has no stored values; any default must remain valid
for the resulting definition. Deleting fields containing values and deleting
assigned types are blocked. Definition changes must not leave invalid defaults.

Saved searches referencing a deleted definition must produce a clear validation
error rather than silently dropping the condition.

## 8. Forms and details

Creation and editing forms provide an optional type selector and appropriate
controls for its fields. Clearly separate **Primary metadata** from
**Type-specific metadata** on forms and details pages. Identify the assigned
type and present fields in administrator-defined order. Untyped resources have
no type-specific fields.

For both aggregations and records, retain the existing details dialog and its
tabs. Add the type-specific metadata section below the primary metadata section
in the first tab. This is an incremental extension of the current dialog, not a
replacement, major overhaul, or redesign of its layout or navigation.

Required indicators, validation, defaults, translated labels, localized scalar
display, and single-choice labels must behave consistently in English and
Arabic/RTL. Existing accessibility and performance contracts apply.

The latest mockups are approved in general, subject to these written rules.
Implementation must reuse the existing pages', dialogs', tables', controls',
and action conventions. Reuse the existing entity **Translations** editor and
its supported-language selector for type names/descriptions, field names, and
choice labels; do not limit translation editing to English and Arabic. Choice
administration must support adding, translating, reordering, and safely
removing choices and selecting a literal default.

Retain the existing Advanced Search group/condition builder. Extend a condition
or sort row with a type selector followed by a selector limited to that type's
fields. Use bounded searchable selectors and existing pagination conventions;
never place every type-specific field into one combined dropdown. Creation
selectors offer usable types; search selectors offer visible types. UI
filtering reflects server decisions and does not replace their enforcement.

## 9. Search

### 9.1 Type criteria, sorting, and visibility

Advanced search shall filter by assigned type, absence of a type, and individual
type-specific fields using existing operators appropriate to their data types.
Fields are identified by their owning type and stable IDs. A field comparison
applies only to resources assigned that type; an unset comparison means that
type is assigned but the field has no value.

A query may mix primary metadata with conditions for multiple types of its
selected resource kind, using the existing Boolean groups. It is not limited
to one defined type. Sorting may reference type-specific fields; references
must identify the owning type and stable field ID. Different types' fields
remain distinct even when their translated names match. Preserve deterministic
pagination using the sorting rules below.

Validate See access to every explicitly referenced type, including references
inside OR/NOT groups and sort clauses, before execution. Reject unauthorized
references; never drop or rewrite conditions to make a query executable.
Independently apply resource See authorization in SQL even when the query has
no explicit type condition. Sharing a saved definition does not grant type or
resource access.

Single-choice fields use structured choice filters referencing stable choice
IDs. Search selectors display translated choice labels. Label renaming and
translation must not change the meaning of saved filters.

Basic/header and full-text search include populated text-field values in the
resource's existing metadata search source. Numeric, boolean, date, datetime,
and single-choice values use structured comparisons and are not converted to
text for keyword matching. Translated choice labels are excluded from
keyword/full-text indexing in this version.

Search each resource's own assigned type and values, without parent inheritance.
Existing authorization, Boolean-expression rules, pagination, and synchronous
metadata-index freshness requirements continue to apply. Stored type text uses the description weight. Values follow stable field-ID order so renaming or translating a field preserves existing phrase positions. Changes to stored text and its search document commit together. Clearing a value, reassigning a type, or destroying the descriptive metadata removes the old terms from the resource’s index. A record metadata hit and an aggregation snippet use the existing result conventions.

#### 9.1.1 Type-field sorting — approved 18 November 2026

For every type-specific sort key, place missing values **last in both ascending
and descending order**. A value is missing for that key when the resource has
the field's type but no value, has another type, or is untyped. These cases share
the missing sort position; their distinction remains available in conditions.
Zero, false, and any valid populated value are not missing. Do not substitute
a static default at query time.

Use subsequent requested sort keys for equal values, then the existing
deterministic resource-ID tie-breaker (append `id ASC` when ID is not already
part of the requested sort). This also orders missing entries; do not create
an additional order by the reason a value is missing. Existing primary-metadata
sort semantics are unchanged.

Single-choice fields sort by **administrator-defined choice order**. Ascending
follows that order; descending reverses the populated choices while keeping
missing values last. Do not sort by translated labels or internal choice IDs.

| Example: choices configured as Low → Normal → Urgent | Result |
| --- | --- |
| Ascending | Low, Normal, Urgent, missing |
| Descending | Urgent, Normal, Low, missing |
| Interface language changes or labels are renamed | The choice order is unchanged; display the current translated labels |
| Administrator reorders choices to Urgent → Normal → Low | Ascending now follows Urgent, Normal, Low, missing |

Choice reordering intentionally changes sort meaning. Invalidate affected
cached ranked lists and rebuild them using their submitted criteria under the
existing search-cache contract. Preserve the saved query's stable IDs; label
renaming/translation alone does not change the sort order.

Other field types use native value ordering and existing scalar conventions:
numbers numerically, dates chronologically, datetimes by instant, and text and
booleans according to the existing corresponding field conventions. For an
Invoice Amount field with values 0, 10 and 25, ascending returns 0, 10, 25,
then missing entries; descending returns 25, 10, 0, then missing entries.
An Invoice without an amount and a non-Invoice resource both belong to that
missing group, ordered by subsequent keys and the ID tie-breaker.

**Rationale:** Missing-last ordering keeps populated results useful in either
direction. Choice order supports meaningful priorities and is stable across
languages; labels would produce language-dependent order and IDs would reflect
creation history. No user-selectable null-ordering or choice-sorting mode is
introduced.

### 9.2 Shared saved searches — approved 18 November 2026

**Retain the audience-authorized list entry,
but prevent opening/loading and execution if any explicit type reference is
forbidden.** This applies to conditions and sorting, whether the query was
shared, saved earlier, or supplied through the API. A previously valid query can become unavailable
after a type-policy or effective-role change.

- Keep the saved search's summary in the recipient's existing audience-
  authorized list. Disable Open and Execute and explain: “This saved search
  references a type you are not permitted to see.” Do not enumerate forbidden
  type names. The list entry is not permission to read its query definition.
- Check every referenced type on the server before returning the definition,
  including through list responses, direct reads, and workspace restoration.
  For ordinary recipients lacking See, withhold the entire query definition;
  do not load a partial or redacted query into the builder. Preserve the full
  canonical definition on the server. Existing independently authorized
  administrative inspection is a separate path and does not permit execution.
- Recheck server-side on execution and subsequent paging; disabling UI actions
  is guidance, not enforcement. Never return a successful empty result to
  disguise an authorization failure, execute only permitted OR branches, or
  silently remove a restricted sort. Revocation also blocks reuse of a
  previously loaded definition or cached results.
- A general search containing no forbidden explicit type references remains
  executable. SQL excludes resources whose type or other authorization gates
  fail; a legitimate search may consequently return zero results.
- Re-evaluate current permissions when opening or executing again. The query
  becomes loadable and executable when all referenced types are permitted,
  provided the existing audience, privilege, version, and resource checks pass.

See is sufficient for query access; Use is not required. A user who may See a
type but cannot create or edit its resources may still search it. Effective
governance roles receive the approved type-gate bypass.

This separates permission to receive a saved search from permission to use its
criteria. Hiding the search would obscure why a shared item disappeared;
returning no matches would misrepresent a permission problem as a data result.
Executing explicit forbidden criteria would undermine the See rule and make
mixed-type queries appear complete when some requested types are unavailable.
Authored names/descriptions remain subject to existing sharing rules;
withholding the definition cannot remove information an author manually put
in them. Executing an opaque server-side definition without loading it is
technically possible for option 4, but would introduce a separate interaction
and relax the rule against explicit forbidden type references. It is excluded
from this approved behavior.

## 10. Explicit deferrals

Formulas, dynamic defaults, validation expressions, field-specific permissions,
multilingual text values/defaults, multiple-choice selection, dependent
dropdowns, and choices fetched from other entities are deferred. Static
defaults and administrator-defined single-choice dropdowns are included.

### 10.1 Additional topics deferred for discussion and specification

These topics are recorded for future work only. The descriptions and examples
explain intent; they do not add current fields, constraints, UI behavior, or
acceptance requirements.

| Topic | Intended capability and illustrative example | Matters to settle later |
| --- | --- | --- |
| **Default classification and permitted classification subtree for aggregation types** | Associate an aggregation type with a default classification, with aggregations of that type classified at that node or within its descendant subtree. For example, a Procurement File type could default to Procurement and permit a more specific descendant such as Tendering. | When the default is applied; whether the subtree is an enforced restriction; explicit selections; existing parent-based classification rules; type reassignment; existing instances; inactive, moved or removed classifications. |
| **Hiding optional type-specific fields after use** | Allow administrators to hide optional fields even after the type and field have been used. For example, stop showing a legacy optional Fax reference field without treating hiding as deletion of its definition. | Which forms/details/search/export surfaces hide it; treatment of stored values and history; editability, restoration and defaults; required-field transitions. Presentation hiding must be distinguished from the separately deferred field-permission topic. |
| **Permitted parent aggregation types for record types** | Configure which aggregation types may contain records of a given record type. For example, Invoice records could be placed only under Procurement File or Finance File aggregations, narrowing the parent choices during record creation. | Whether rules are configured from either catalogue; direct-parent versus ancestor scope; untyped records/aggregations; existing placements; imports/copies/moves; later type/policy changes; interaction with authorization and lifecycle rules. |

The final topic is a **record-type/parent-aggregation-type compatibility rule**.
It expresses structural eligibility, separate from whether the caller may use
the types or add records to a particular aggregation. Its enforcement and
exceptions require a later specification; current placement rules remain in
effect until then.

## 11. Acceptance and traceability

See the [role grant and typed input regression matrix](../docs/verification/resource-type-grants-and-dialog-inputs.md) for the administration, data entry and search dialogs.

Implementation must maintain requirement-to-implementation-to-test traceability.
This specification's approval does not constitute implementation or verification
evidence. No feature may be declared complete while an approved requirement
lacks implementation and verification evidence.

| ID | Required verification |
| --- | --- |
| ART-01 | Separate catalogues; zero or one compatible type; stable identities and name uniqueness |
| ART-02 | Correct storage and API/UI validation for all seven data types, including exact decimals and datetime instants |
| ART-03 | Translated definitions and choices, default-language names, fallback, English/Arabic display, and unchanged IDs after renaming |
| ART-04 | Single untranslated text values/defaults regardless of user language |
| ART-05 | Unicode character limits, 255-character control threshold, no truncation, and rejection of incompatible length reductions |
| ART-06 | Required/optional validation, including null, blank text, zero, false, and next-metadata-update enforcement after definition changes |
| ART-07 | Literal default validation, initial assignment, explicit overrides/clearing, no update-time reapplication or backfill, and future-only default changes |
| ART-08 | Single-choice membership validation, translated labels, stable saved filters, default references, and deletion safeguards |
| ART-09 | New `aggregation_types.administer` / `record_types.administer` catalogue entries and default grants to the two governance profiles and `ALL_PRIVS`; explicit delegation elsewhere; definition/resource authorization separation and negative tests |
| ART-10 | Confirmed clearing on type changes/removal, atomic saves, event history, and no name-based mapping or inheritance |
| ART-11 | Safe field/type definition changes and clear saved-search errors for removed definitions. For both kinds, verify consecutive field positions after insertion, moves and deletion, stable ordering across the upgrade, and rejection of stale concurrent moves. |
| ART-12 | Delineated metadata sections and correct form/detail controls in live English/LTR and Arabic/RTL views; existing aggregation and record details dialogs retained, with type-specific metadata below primary metadata in the first tab |
| ART-13 | Typed advanced filters, untyped/unset semantics, text-value full-text matching, exclusion of choice labels, authorization, pagination, and index freshness |
| ART-14 | See/Use grants, Use-implies-See, empty grants, untyped resources, union of effective roles, expiry/inactive ancestry, and the new gate order |
| ART-15 | Governance bypasses See/Use and ACL without explicit type grants; own-clearance, privilege, lifecycle, administration, and custody boundaries remain enforced |
| ART-16 | Create/edit/delete, reassignment/removal, components and other mutations enforce the correct source/destination types; bulk and direct API negative cases |
| ART-17 | Type-policy/reassignment custody checks, immutable history, concurrent changes, revocation and cached-page freshness |
| ART-18 | Identified consumers and Python/database/batch SQL decision equivalence; no leakage through lists, counts, relationships, exports, components, or explanations |
| ART-19 | Mixed-type Boolean criteria and sorting; missing values last in both directions; administrator-defined choice order independent of language/IDs; choice-reorder cache invalidation; stable field identity/tie-breaking and validation of every explicit type reference |
| ART-20 | Existing UI conventions and details tabs preserved, scoped field selectors, all-supported-language translation editor, and choice administration |
| ART-21 | Before/after regression and performance evidence for changed authorization and search paths, including broad, selective, empty, and denied cases |
| ART-22 | Shared-search summaries remain visible; forbidden definitions are withheld from list/read/restore, builder loading and execution are blocked, See without Use permits search, and restored/revoked access is enforced |
| ART-23 | Type access reuses query authorization sets before counts/ranking/paging/caps, adds no per-resource database queries or repeated type checks across branches, and rechecks current permissions on subsequent pages; accepted existing read-path repetitions remain separately identified |

After approval and implementation, run existing authorization, search, saved-
search, custody, and UI regressions plus the cases above. Record before/after
timings on comparable datasets for single-resource operations, type-policy
changes/reassignment, and every affected search/list flow. Tests must use newly
created disposable databases and report cleanup; never run them against a
persistent ERMS database.

Run and extend `tools/check_search_performance.py` for the type gate, typed
criteria and sorts, mixed types, governance access, denied access, and permission
changes between pages. Follow the [performance contract](../docs/search-performance.md):
more than 50,000 aggregations and 150,000 records, a 1,000-result cap, exact
counts/ranking/order, and every measured response within 3 seconds. Preserve
all samples, plans, dataset details, PostgreSQL/JIT information, and cleanup
evidence; report the impact relative to the baseline.

The large-dataset run must explicitly include broad queries matching most or
all resources, both with and without type-specific criteria, alongside selective,
empty, and denied cases. Exercise mixed typed/untyped resources, many types and
role grants, governance access, type-field sorting, and initial/cached pages.
Measure existing queries as well as new typed queries: adding the visibility
gate affects searches even when users specify no type condition. Cover every
changed search/list flow, including its broadest supported criteria. Compare
complete API response times before and after the change on comparable fixtures;
SQL timings alone are insufficient. Report individual samples and their changes,
not only averages or medians. Existing thresholds remain mandatory; the accepted
extra read stages do not relax them. Fix new failures before declaring the
feature's performance verification complete.

Preserve the documented
14 November 2026 compressed-storage exception within its original scope; it
does not excuse new regressions. Run `tools/check_large_text_search_performance.py`
when full-text scoring or evidence changes. No implementation or performance
claim is made by this documentation amendment.

Section 9.2 requires saved-search cases covering recipient See loss,
summary-only listing, withheld definitions on list/read/restore, blocked builder
loading and API execution, no OR-branch pruning, cached paging after revocation,
restored access, See without Use, administration without execution authority,
and generic queries filtered by current resource access.
