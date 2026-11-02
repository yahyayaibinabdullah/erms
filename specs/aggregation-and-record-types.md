# Aggregation and Record Types

**Status:** Approved — specification only; implementation not yet verified  
**Prepared:** 22 October 2026  
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

## 4. Text length and required fields

Text fields require a positive maximum character length. The field-definition
form initially suggests 255 characters. Length is counted in Unicode
characters, not bytes, in both API and UI validation.

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

## 7. Assignment, authorization, and definition changes

The existing global privilege `aggregations.administer` authorizes creating
and maintaining aggregation types, fields, choices, translations, and defaults.
The existing global privilege `records.administer` provides the corresponding
authority for record types. No new administration privilege is introduced.

Assigning, changing, or removing a resource's type and editing its field values
use existing resource creation/update authorization and lifecycle restrictions.
Definition-administration privileges do not independently authorize resource
edits. Types and values are not inherited from parent aggregations.

Only fields belonging to the assigned type may contain values. Untyped
resources have no type-specific values. Invalid assignments or values are
rejected without partial saves.

Changing or removing a type clears the old type's current values. When values
will be cleared, require explicit confirmation. Do not map values by matching
field names. Save the type change and values atomically and capture the change
and affected values through existing event-history conventions. Defaults for a
newly assigned type follow section 5.

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

Required indicators, validation, defaults, translated labels, localized scalar
display, and single-choice labels must behave consistently in English and
Arabic/RTL. Existing accessibility and performance contracts apply.

## 9. Search

Advanced search shall filter by assigned type, absence of a type, and individual
type-specific fields using existing operators appropriate to their data types.
Fields are identified by their owning type and stable IDs. A field comparison
applies only to resources assigned that type; an unset comparison means that
type is assigned but the field has no value.

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
metadata-index freshness requirements continue to apply.

## 10. Explicit deferrals

Formulas, dynamic defaults, validation expressions, field-specific permissions,
multilingual text values/defaults, multiple-choice selection, dependent
dropdowns, and choices fetched from other entities are deferred. Static
defaults and administrator-defined single-choice dropdowns are included.

## 11. Acceptance and traceability

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
| ART-09 | Existing administration privileges and resource edit authorization/lifecycle restrictions, including negative authorization tests |
| ART-10 | Confirmed clearing on type changes/removal, atomic saves, event history, and no name-based mapping or inheritance |
| ART-11 | Safe field/type definition changes and clear saved-search errors for removed definitions |
| ART-12 | Delineated metadata sections and correct form/detail controls in live English/LTR and Arabic/RTL views |
| ART-13 | Typed advanced filters, untyped/unset semantics, text-value full-text matching, exclusion of choice labels, authorization, pagination, and index freshness |
