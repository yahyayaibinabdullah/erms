# Custom Code Generators

**Status:** Approved

**Project:** ERMS / Wathiq

**Prepared:** 26 November 2026

**Revision:** 0.6

**Updated:** 27 November 2026

**Approved:** 27 November 2026

**Implementation planning:** [Phased implementation plan](custom-code-generators-implementation-plan.md).

## 1 Purpose and eligible fields

**CG-01.** Allow the system administrator to configure automatic codes for
user-editable **Text** primary metadata, such as record and aggregation numbers,
and **Text** type-specific metadata, such as contract numbers and employee codes.
Eligibility follows the metadata's declared type, not its database storage.
Integer, decimal, Boolean, date, datetime, single-choice and system-managed
fields are ineligible. Generated values remain ordinary stored text.

The [resource types](aggregation-and-record-types.md),
[records management](records-management-subsystem.md),
[ownership](organizational-ownership-and-default-acls.md),
[settings](administration-settings.md) and
[internationalization](internationalization-and-user-preferences.md) contracts
continue to apply except for the explicit extensions below.

## 2 Generator configuration

**CG-02.** Each generator has a stable identity and the following configuration:

| Setting | Meaning |
| --- | --- |
| Generator name | Required, nonblank administrator-defined display name for identifying the generator in the dialog, listing and audit history. |
| Target | Record or aggregation, and one eligible field identified by its stable key or field ID. A type-specific field belongs to its defining type; primary-field applicability is selected separately below. |
| Applies to | For primary metadata, a three-option selector: **All items** (typed and untyped), **Untyped items only** (no assigned type), or **One selected type** (requires a type). Default: All items. A type-specific field always applies only to its defining type. |
| Pattern | Literal text and supported placeholders, including exactly one `{SERIAL}`. |
| Starting number | Nonnegative whole number; default 1. |
| Increment | Positive whole number; default 1. |
| Counter scope | One counter for the generator, or separate counters per parent aggregation, effective classification or owning organizational unit. Organization-unit scope requires `{ORG_UNIT_CODE}` in the pattern. |
| Reset frequency | Never (default), Yearly or Monthly, explicitly selected by the administrator. Yearly requires a year placeholder; Monthly requires both month and year placeholders. `{DATE}` supplies both. |
| Zero-padding width | Optional nonnegative whole number. Unset or 0 (the default) disables padding. A positive value is the minimum number of serial digits: pad shorter serials on the left with zeros and leave longer serials unchanged. |
| Maximum code length | Required positive whole number limiting the complete generated code in Unicode characters, including literals, separators, all placeholder values and padding. Must not exceed the target field's maximum length when one exists. |
| Enabled | Whether the generator applies to future creations. |

The name is an editable label; the stable generator ID remains its reference.
Renaming a generator changes neither its binding nor its counters or stored
codes. Names do not decide which generator applies. Treat a rename as a
configuration edit, including its required reason and audit evidence.

Reject overlapping enabled generators for the same target field and resource
population. A field with an attached generator must remain Text; remove the
binding before deleting the field or making it ineligible. Generators do not
share counters with other generators.

For the same primary field on the same resource kind, apply these examples:

| First enabled generator covers | Second enabled generator covers | Result |
| --- | --- | --- |
| All items | All items | Reject: both apply to the same items. |
| All items | Untyped items only | Reject: All items includes untyped items. |
| All items | Contract | Reject: All items includes Contract. |
| Untyped items only | Untyped items only | Reject: both apply to untyped items. |
| Untyped items only | Contract | Allow: their covered items differ. |
| Contract | Contract | Reject: both apply to Contract items. |
| Contract | Employee file | Allow: the covered types differ. |

An untyped-only generator can coexist with generators for individual types on
the same primary field. All items is not a fallback overridden by a more
specific generator. Show the selected applicability in the listing and audit
history. In the dialog, replace the former type-restriction checkbox with the
three-option **Applies to** selector; show the type picker only for One selected
type. Type-specific metadata requires its defining type and does not offer
All items or Untyped items only.

Match applicability against the item's type at final creation in every creation
path, including final draft commit and direct file drop. Recommendations and
field-generation hints use the same rule. Untyped-only must never match a typed
item, and a selected-type generator must never match an untyped item or another
type. Applicability changes affect future creations only; assigning/changing a
type on an existing item does not regenerate its code.

Different resource kinds or target fields do not overlap. Identify type-specific
fields by their stable field IDs and defining type, not matching display names.
Counter scope and reset settings do not restrict which items a generator covers:
counting by organization unit does not make it an organization-unit-only rule.
Disabled definitions may coexist; recheck overlap when enabling or changing a
binding. Enforce the rules in the database, including simultaneous saves, and
show a clear error instead of choosing an arbitrary matching generator.

Validate the pattern against the selected reset and scope rules. A year
placeholder is `{YYYY}`, `{YY}` or `{DATE}`; a month placeholder is `{MM}` or
`{DATE}`. Warn that `{YY}` repeats after 100 years. For globally unique record
and aggregation numbers, parent scope requires `{PARENT_AGGREGATION_NUMBER}`;
classification scope requires both `{CLASSIFICATION_SCHEME_CODE}` and
`{CLASSIFICATION_CODE}`. Flag obvious conflicts between independent generators
targeting the same globally unique number field. Runtime collision handling
remains mandatory; valid placeholders alone do not prove uniqueness.

## 3 Pattern placeholders

**CG-03.** Support these placeholders. Literal separators such as `/`, `-` and
`.` are retained. `{{` and `}}` produce literal braces. Unknown placeholders,
unbalanced braces and expressions are invalid.

| Placeholder | Source |
| --- | --- |
| `{YYYY}` / `{YY}` | Four-digit year / last two year digits. |
| `{MM}` / `{DD}` | Two-digit month / day of the month. |
| `{DATE}` | Complete date as `YYYYMMDD`. |
| `{PARENT_AGGREGATION_NUMBER}` | Immediate parent aggregation's number; for a record, its containing aggregation's number. Unavailable for a root aggregation. |
| `{CLASSIFICATION_CODE}` | Code of the classification assigned to the root aggregation. Descendant aggregations and records use that same effective classification. |
| `{CLASSIFICATION_SCHEME_CODE}` | Code of the scheme containing that effective classification, distinguishing classification codes that repeat across schemes. |
| `{ORG_UNIT_CODE}` | Resource's owning organizational unit code, resolved through the existing ownership rules. |
| `{ROLE_CODE}` | Code of the eligible organizational role selected through the existing **Create for** field, also used for creator ACL attribution. |
| `{SERIAL}` | Allocated serial formatted using the optional zero-padding width. |

Capture one server-side generation instant for the creation. Date placeholders
and yearly/monthly resets use its Gregorian date in the application's validated
default working timezone, independently of personal display preferences.
Generated digits use `0` through `9`; language changes do not alter stored codes.

Reuse **Create for** without adding another role selector. Preserve its existing
eligibility checks and automatic selection when only one role is eligible.
Adding a date or organization-unit placeholder does not enable a reset or change
the counter scope automatically. The administrator must select those options.
The role placeholder does not introduce role-scoped numbering.
Missing required context prevents generation; never substitute an empty code.

## 4 Serial allocation and formatting

**CG-04.** For each counter, allocate `start`, then `start + increment`, then
`start + 2 × increment`, and so on, except for the explicit forward adjustments
in CG-14. Identify parent, classification and organization-unit scopes by stable
database IDs, never their displayed numbers or codes. Classification scope means
the effective classification above, not an ancestor branch. Organization-unit
scope uses the resource's resolved owner under the existing ownership rules.

With Yearly reset, keep a separate counter per scope and full calendar year.
With Monthly reset, keep one per scope and full year/month, so January in
different years has separate counters. Each new period starts at the configured
starting number. Never reset continues the same counter across date changes.
A root aggregation cannot use parent-aggregation scope. Scope and reset choices
are independent, subject to the required pattern placeholders in CG-02.

**CG-05.** Zero-padding width controls minimum formatting width. With width 4,
serial 7 renders as `0007`, 123 as `0123`, and 10000 as `10000`. With the width
unset or 0, serial 7 renders as `7`. Reject negative or fractional widths.
Serials can grow beyond the configured width without truncation, reset or
rejection for exceeding that width. Validate the complete rendered code against
the generator's maximum code length and the target field's existing constraints.
Reject configuration whose known minimum output cannot fit. Recheck actual
placeholder lengths at generation time; a code that is too long fails atomically
without truncation or counter advancement. Manual values retain the target
field's existing validation rules.

## 5 Generation and existing values

**CG-06.** Generate during resource creation, including final record-draft
commit, when an enabled generator's target is blank or contains an accepted,
unedited generator recommendation as described in CG-10. Blank means omitted,
null, empty or whitespace-only. Apply existing static-default rules first;
a resulting nonblank value is preserved. A manually supplied nonblank value
takes precedence and does not advance the counter. Generated fields remain
editable under the field's normal permissions and validation.

Creating, saving or updating a record draft must allow its record number to
remain unset. A draft is not yet the final record. Saving a draft neither
requires generation nor advances a counter. Only the final **Create record**
action requires complete metadata: fill a blank number with the applicable
generator before final required-field validation. With no applicable generator,
preserve existing numbering behavior; a valid number must be supplied before
final creation. Preserve the existing ability to store incomplete drafts and
their staged digital components.

Ordinary edits, later type assignment and enabling a generator do not backfill
existing resources. Changing a parent, classification, owner, role code,
pattern or language does not regenerate an existing value. Renaming a source
code affects future generation only. Generation remains limited to future
resource creations, including their final draft commits.

**CG-07.** Allocate serials and persist all generated values with the resource
in one database transaction. Concurrent requests must not receive the same
serial from the same counter. Failure rolls back the resource and its counter
changes. Previews, number recommendations and cancelled drafts consume no
serials; recommendations are tentative, not reservations. Deleting an item or
manually replacing its code does not release an allocated serial. Gapless
numbering is not guaranteed.

Preserve existing uniqueness rules: record numbers and aggregation numbers
remain globally unique in their respective catalogues. When obtaining a new
automatic number for a blank field or a fresh recommendation, skip occupied
candidates, including manual or imported numbers, using the configured increment.
Resolve concurrent collisions safely and keep all skip/allocation changes in
the resource transaction. Do not repeatedly fail on the same occupied candidate.
For an already accepted number, follow CG-10: a conflict stops final creation
instead of silently choosing a different number.
Manually submitted duplicate numbers still produce a conflict; do not change
the user's value automatically. Check hidden resources without revealing them.
Ordinary Text fields acquire no new uniqueness constraint; uniqueness for
type-specific field values is a deferred future enhancement.

After a record or aggregation is deleted, its number may be manually entered
when creating or updating another item, provided no existing item in the same
catalogue holds it. Apply all normal create/update permissions, type access,
clearance, ACL, lifecycle and field-validation rules. Manual reuse neither
advances nor rewinds a generator counter and follows the existing resource
audit rules. Historical use alone does not permanently reserve a number.

Automatic generation continues forward from each counter's retained position;
it never searches earlier gaps made available by deletion or manual changes.
For example, if the next serial is 111 and item 101 is deleted, an authorized
user may manually reuse 101, while the generator continues from 111. This rule
applies within each generator/scope/reset period; explicitly configured yearly
or monthly resets still start a new period at its starting number.

Configuration changes affect future values only and must not rewind an
existing counter. Keep the counter state needed to prevent backward allocation after
disable/re-enable or scope/reset changes. For an existing counter, a changed
increment applies after its last allocation; a changed starting number applies
only to counters that have not allocated yet. Changing or clearing zero-padding
width affects future generation only; it changes neither counters nor stored codes.
Changing maximum code length also affects future generated values only.

## 6 Sorting

**CG-08.** Wherever an attached generator's target field is available for
sorting, use PostgreSQL's existing **`erms_code_natural`** collation across
generated, manual and legacy values. It uses the ICU provider and locale
`und-u-kn`, enabling numeric comparison of digit sequences within text.
Thus `EMP-1`, `EMP-2`, `EMP-10`, `EMP-11` sort in that order, with or without
zero filling. Other characters and differences between otherwise equivalent
representations follow the collation's existing deterministic comparison.
Use subsequent requested sort keys for equal values, then the existing stable
resource-ID tie-breaker. For example:

```sql
ORDER BY record_number COLLATE erms_code_natural ASC, id ASC
```

Numeric ordering is guaranteed for uninterrupted digit runs up to **254
significant digits**, ignoring leading zeroes. Longer runs follow ICU's
ordering and may differ from mathematical numeric order. No digit cap is
added, and zero-padding remains optional. Count the whole digit run, including
adjacent date/context digits and serial digits. This is the existing
[ICU numeric-collation limit](https://unicode-org.github.io/icu-docs/apidoc/released/icu4c/ucol_8h.html),
accepted by the user on 27 November 2026.

Store only one Text value per field, formatted using the optional zero-padding
width. Numeric ordering requires no second padded/unpadded copy or separately
maintained sort-value column. Padding width controls formatting only;
within the collation's supported digit-run size, padding is unnecessary for
correct numeric sorting.
The generator's numeric counter state is separate from each stored field value.

Apply this ordering in PostgreSQL before page selection. Preserve existing
authorization, missing-value placement and search-cache rules. This explicitly
extends the existing text-sort contract only for fields with an attached
generator; other fields retain their current sorting. Use the collation
explicitly for sorting without changing the database default or existing
equality and uniqueness rules. Any index intended to support this ordering
must use the same collation; verify actual execution plans and complete API
timings before adopting index changes. See the
[database collation guide](../docs/database-collation.md#sorting-equality-and-numeric-order).

Numeric ICU comparison can add CPU cost relative to bytewise `C` comparison.
Existing `C` or default-collation indexes do not supply this different ordering;
a broad code-sorted query may otherwise require an expensive explicit sort.
Keep full-text, substring and prefix matching on their existing predicates and
indexes; apply natural collation to code ordering only. Preserve relevance
ranking and all unaffected sort paths. Verify both affected and unaffected
search flows, including broad/selective criteria and pagination, with actual
plans and the repository performance gates. No latency guarantee follows from
merely adding a collation or index. Binding changes that alter sort semantics
must invalidate affected cached ranked lists under the existing cache contract.

## 7 Administration and delivery

**CG-09.** Provide **Code generation** under **Administration → Settings**, using
the existing `app.settings.manage` privilege and settings administration, audit
and concurrent-edit conventions. Generator persistence follows section 9.
Show each generator's name beside its target in the listing, and require the
name in the create/edit dialog. Offer eligible field selection, configuration
validation and the sequence preview defined in CG-11. Changes require no restart;
actual generation uses the current committed configuration. Administration grants no resource
access. All existing create privileges, type See/Use, clearance, ACL and
lifecycle checks remain mandatory.

**CG-10.** Keep the existing number-suggestion controls, including suggestions
after a conflict. Use the configured generator when one applies and the existing
numbering rules otherwise. Showing or accepting a suggestion does not reserve it.

Once a suggested number is placed in the actual number field, keep that exact
value unless the user explicitly changes it. This includes suggestions inserted
automatically by a form. At final creation, save that number exactly or stop
and explain why it cannot be used. Never silently replace it with another
number, or silently treat an outdated automatic suggestion as manual entry.
The database must enforce availability during the save; an earlier check in
the form is insufficient when several users are creating items.

### Drafts and creation paths

Saving a draft stores unfinished work. **Create record** turns it into a final
record. These are separate operations. A draft may be saved, reopened and edited
without a record number or a number suggestion. Draft saves do not allocate
numbers. Keep the existing drop-to-draft and direct-creation flows distinct.
Normal draft access, expiry and cleanup rules still apply.

| Path or action | Numbering behavior |
| --- | --- |
| Create, save, reopen or update a record draft | The number may remain unset. Preserve the draft and staged files without allocating a serial. |
| Cancel/discard a draft, or let it expire | Follow the existing draft cleanup rules. Its unused suggestions have not consumed or reserved numbers. |
| Final Create record with an empty number | Generate an available number if a generator applies; otherwise require a manually supplied number. Check the remaining required metadata before creation succeeds. |
| Final creation with an accepted suggestion | Save the exact number shown, provided it remains available and valid. Otherwise stop and preserve the draft, metadata, chosen number and staged files. |
| Final creation with a manually entered number | Preserve it and apply existing field, uniqueness and authorization checks. Do not advance a generator counter for manual entry. |
| Drag-and-drop directly creates one record | Obtain its number automatically from the applicable generator. Skip occupied candidates. Use the old numbering rules only when no generator applies. |
| Several dropped files create one combined record | Obtain one number for that record, using the same direct-creation rule. |
| Several dropped files create separate records | Obtain one number for each record. Create the complete batch atomically; a failed batch leaves no partial records or counter changes. |
| Dropping files opens a draft for review | Keep it as a draft until Create record is chosen. It may have no number. If a suggestion is put in its number field, do not silently change it at final creation. |
| Create an aggregation | Apply the same empty/manual/accepted-number rules to its aggregation number, with all existing root/child creation checks. |
| Edit an existing record or aggregation, or assign a type later | Do not generate or replace codes automatically. Authorized manual edits remain available. |

### Conflicts and numbers copied into documents

Use optimistic conflict handling: try the chosen number at final creation and
stop if it can no longer be used. Remember that a suggested number came from
the generator, so the correct counter is updated when creation succeeds.
If the user deliberately edits the number, treat it as manual entry.

| Situation | Required behavior |
| --- | --- |
| A user copies the suggested number into a document and uploads it | Successful final creation must use that exact chosen number. The system must not silently save the record under a different one. |
| Two users choose the same suggested number | Only one final item may hold it at a time. The other user receives a conflict; their draft, chosen number and files remain intact. Reveal no details of an inaccessible conflicting item. |
| The user wants to recover from a conflict | They explicitly request and accept another suggestion, or edit the number manually. If a document contains the old number, the user must correct it and replace the uploaded component as needed before retrying. The system does not silently rewrite documents. |
| The month/year, parent, type, owning unit, Create for role, generator settings or next-number adjustment changes | Recheck the chosen number against the relevant current rules. If it cannot still be allocated unchanged, stop for review; keep the displayed number and files. Never substitute an updated number automatically. |
| A late suggestion response arrives after the user has chosen or edited a number | Ignore the outdated response; do not overwrite the field. |
| Final creation fails | Roll back the final record and its counter changes. Keep the original draft, metadata and staged components so the user can correct the problem. |
| Final creation succeeded but its response was lost | Retrying the same submission returns the original creation result and number under CG-15, without creating a second record or allocating another number. |
| A failed attempt is confirmed and the user chooses a new number | Allow a corrected submission. Distinguish it from a retry whose earlier outcome is still unknown; do not create duplicates after a lost response. |
| An earlier record/aggregation was deleted | Authorized manual entry may reuse its now-available number. The generator continues forward within its counter; it does not search old gaps. |

### Chosen approach and tradeoffs

**Decision approved on 26 November 2026:** Use optimistic conflict handling for
record and aggregation number suggestions. Suggestions do not reserve numbers.
Final creation saves the exact chosen number or stops with a clear conflict,
preserving the draft and files. The user can then explicitly choose another
number and correct any affected documents before retrying.

This is the approach to implement. Reservation was considered and is not selected
for this version; it is not an alternative administrator setting. Explain that
a suggestion may become unavailable before final creation.

| Approach | Benefit | Cost or limitation |
| --- | --- | --- |
| Optimistic checking at final creation — chosen | Simpler: no numbers are held for abandoned drafts, and no reservation expiry/release process is needed. The saved number cannot silently differ from the chosen one. | Another user can take the number first. The user may have to choose another number and correct documents before retrying. |
| Reserving the number before final creation — not selected | The number remains available to its holder while the reservation is valid, making advance document preparation easier and reducing number-conflict retries during that time. | Requires rules and storage for expiry, cancellation, release and changed context. Unused reservations can leave gaps; an expired reservation can no longer promise availability. |

The five-value administration preview remains a demonstration with fictional
counters. It does not choose or reserve a number for a real record.

Use the same generation and validation rules in every supported creation path,
including forms, APIs, record capture and draft commit.
Deliver localized controls and errors in English and Arabic, and verify both
LTR and RTL presentation. Preserve historical values and existing configuration
during upgrades; supply matching canonical schema and populated-database migration
changes where required.

**CG-11.** Once the generator is fully configured and valid, offer a **Preview
sequence** action showing **five successive complete generated values**. Use the
configuration currently being edited, including unsaved changes, and the same
pattern, formatting and counter rules as actual generation. Display each value's
simulated date and scope so the administrator can verify the result. Apply the
complete-code length limit to samples and report validation errors against the
sample context.

Use clearly labelled sample dates and fictional parent, classification,
organization-unit and role contexts wherever the pattern requires them. Start
each simulation with fresh, isolated counters at the configured starting number.
Provide these scenarios:

- **Same scope and year:** five successive allocations in one context.
- **Year transition:** three allocations on 31 December followed by two on
  1 January of the next year, using the application's default working timezone.
  Yearly and Monthly reset restart the counter; Never continues it.
- **Month transition:** three allocations on the last day of one month followed
  by two on the first day of the next month in the same year. Monthly reset
  restarts the counter; Yearly and Never continue it.
- **Different scopes:** interleave sample contexts A, A, B, A, B. Parent-scoped
  counters use distinct sample parents; classification-scoped counters use
  distinct sample classifications; organization-unit scope uses distinct sample
  owning units. Generator-wide counters continue across both contexts. Include
  a combined scope/period simulation when a reset and separate scopes are both
  configured, demonstrating each scope's own yearly or monthly reset.

Refresh the results when configuration or sample context changes. Label these
results as simulations: they consume or reserve no real numbers, change no live
counter or system date, save no configuration and create no resources. Actual
creation-dialog recommendations continue to use the current live counter state
as defined in CG-10.

**CG-12.** Capture generator creation and every successful configuration change
in the existing immutable `event_history` audit trail, including name,
target/binding, pattern, start, increment, scope, reset frequency, padding width,
maximum code length, enable/disable, binding removal and any permitted deletion.
Record the stable generator identity, name at the time of the event, actor,
timestamp, before/after configuration, version and existing
request/correlation/source context. A change reason is optional when
creating a generator and required and nonblank when updating or editing an
existing generator. Creation is fully audited even when no reason is supplied;
preserve an optional supplied reason. Snapshot the generator name and target
identities needed to understand history after later renames or removal. A rename
records both old and new names without rewriting earlier audit events.

Enforce audit capture at the database boundary using the established history
mechanism. Configuration changes and audit events commit together; an audit
failure rolls back the change. Preserve optimistic version checks and reject
stale edits without a successful-change event. Historical events survive
disablement or removal. Ordinary serial increments are runtime state, not
configuration changes; preserve the existing resource-creation history without
misreporting each increment as an administrator configuration edit.
Explicit administrator adjustments of the next number under CG-14 require the
same audit protections, recording the affected scope/period and old/new next
numbers separately from ordinary allocation.

## 8 Examples and acceptance

These examples use 26 November 2026, parent `FIN-12`, classification `3110`
in scheme `WTH`, owning unit `FIN`, selected Create for role `FIN-OFFICER`, serial 7 and
zero-padding width 4.

| Pattern | Generated value |
| --- | --- |
| `REC-{YYYY}-{SERIAL}` | `REC-2026-0007` |
| `{PARENT_AGGREGATION_NUMBER}/{SERIAL}` | `FIN-12/0007` |
| `{CLASSIFICATION_SCHEME_CODE}/{CLASSIFICATION_CODE}/{YYYY}/{SERIAL}` | `WTH/3110/2026/0007` |
| `{ORG_UNIT_CODE}/{YYYY}/{MM}/{SERIAL}` | `FIN/2026/11/0007` |
| `{ORG_UNIT_CODE}-{ROLE_CODE}-{DATE}-{SERIAL}` | `FIN-FIN-OFFICER-20261126-0007` |

For **start 10** and **increment 10**, the preview scenarios produce the following
serials. The preview renders each serial through the complete configured pattern
and optional zero-padding width.

| Scenario | Five successive serials |
| --- | --- |
| Same scope and year | `10, 20, 30, 40, 50` |
| Year transition after the third value, Yearly or Monthly reset | `10, 20, 30, 10, 20` |
| Year transition after the third value, Never reset | `10, 20, 30, 40, 50` |
| Month transition within one year after the third value, Monthly reset | `10, 20, 30, 10, 20` |
| Month transition within one year after the third value, Yearly or Never reset | `10, 20, 30, 40, 50` |
| Separate scopes, contexts A, A, B, A, B | `10, 20, 10, 30, 20` |
| Organization-unit scope, units FIN, FIN, HR, FIN, HR | `10, 20, 10, 30, 20` |
| Generator-wide counter, contexts A, A, B, A, B | `10, 20, 30, 40, 50` |
| Separate scopes with Yearly or Monthly reset: A/period 1, A/period 1, B/period 1, A/period 2, B/period 2 | `10, 20, 10, 10, 10` |

Implementation must retain requirement-to-code-to-test traceability and pass:

| Requirements | Required evidence |
| --- | --- |
| CG-01–03 | Required generator names reject missing, empty and whitespace-only input; renaming preserves stable IDs, bindings, counters and stored codes. Only declared Text targets accepted; stable bindings; every allowed/rejected overlap example, including all/untyped/selected-type coverage, untyped-plus-individual-type coexistence, typed/untyped recommendations and every creation path, enable/retarget and concurrent saves; every placeholder and brace escape; parent/classification/scheme resolution; existing Create for selection, multiple-role eligibility and ownership inheritance; missing context rejected; required year/month/org-unit/scope placeholders enforced, two-digit year warning, and obvious cross-generator conflicts flagged. |
| CG-04–05 | Start 10 and increment 5 yield 10, 15, 20; independent parent/classification/owning-unit scopes; rename stability; Never/Yearly/Monthly reset; month/year boundaries, leap day and the configured timezone; January in different years; explicit configuration rather than placeholder-triggered resets/scopes; unset/zero/positive padding widths, invalid widths, serial growth beyond width, and complete-code/field length validation including Unicode and variable placeholder lengths. |
| CG-06–07 | Drafts created/saved/reopened/updated without a number and without allocation; manual/default precedence, future final creation only and no edit/later-type-assignment/backfill generation; transactional concurrent allocation, rollback and cancellation; new automatic candidates skipped using the increment, including occupied manual/imported/hidden numbers; accepted-number conflicts stop instead of substitution; manual duplicates rejected; many occupied candidates; authorized manual reuse after deletion, denied callers, unchanged counters and normal audit evidence; forward-only progress and configured resets preserved. |
| CG-08 | Single stored Text value; explicit `erms_code_natural` ordering of padded/unpadded and mixed legacy values, multiple numeric segments, deterministic numeric ties, ascending/descending, missing values and stable server pagination; matching index collations and actual execution plans where indexes are used; cache invalidation when binding changes alter sort semantics; unchanged matching/relevance paths and preserved matching indexes. Run the repository search correctness/performance gates for affected flows and regression checks for unaffected searches. |
| CG-09–10 | Generator names shown in the listing and create/edit dialog. Allowed and denied administration/creation API requests, including a signed-in caller without target resource/type access; all creation-path and conflict-table cases; generator/legacy suggestions; exact accepted number or a clear conflict with draft/files preserved; simultaneous selections, copied-document scenario, late responses and context/date/configuration/counter changes; direct single/combined/separate file-drop allocation versus drop-to-draft review; manual edits and explicit corrected retry; upgrades; English/LTR and Arabic/RTL browser checks and translation-artifact validation. |
| CG-11 | Fully configured preview using unsaved inputs; exactly five complete valid values per scenario with dates and scopes; correct formatting and length validation; year/month transitions with Never/Yearly/Monthly reset; generator-wide, parent, classification and owning-unit scopes; combined scope/period resets; refreshed results after edits; no real allocation, reservation, counter/configuration/clock change or resource creation. |
| CG-12 | Creation succeeds and is audited without a reason; an optional creation reason is preserved; updates/edits, including renames, require a nonblank reason through UI and API. Every configuration operation and explicit next-number adjustment captures the stable generator ID, name at event time, actor, applicable reason, before/after values, version, target/scope/period identity and request context; rename events show old/new names and preserve earlier name snapshots; stale-edit rejection, database-boundary coverage, audit-failure rollback and history retention; ordinary counter increments distinguished from administrator edits. |
| CG-13 | Shared-table constraints/indexes, concurrent first allocation, independent-counter progress, same-counter contention, multi-field lock ordering, configuration/allocation races, rollback and scoped/year/month counter retention including resource deletion; unique creation-request identity; no historical reservation constraint preventing permitted manual reuse. Retain lock-wait measurements and actual plans at representative concurrency and data volumes. |
| CG-14 | Existing/imported series continued through an audited, advance-only next-number adjustment for one scope/period; no backward change or stored-code rewrite; subsequent increments and occupied-candidate skipping; stale adjustment, concurrent allocation and audit-failure rollback. |
| CG-15 | Lost-response and concurrent retries return one completed creation result with one set of allocated codes; changed inputs rejected for an already used key; current permissions rechecked; complete rollback remains retryable; batches and deleted-result retries never create duplicate resources. |

Run database-backed checks only in uniquely named disposable databases, initialized
from the canonical schema or required upgrade path, and drop them after the run.

## 9 Database design

**CG-13.** Use two shared tables for generator definitions and counters; creating
a generator does not create another table or PostgreSQL sequence. A separate
shared creation-request table supports safe retries under CG-15.

| Table | Contents |
| --- | --- |
| `code_generators` | One row per generator: stable ID, required nonblank name, target references, configuration from section 2, optimistic version and update metadata. |
| `code_generator_counters` | One row per generator, scope kind, scope identity, reset frequency and period bucket, storing the last allocated exact whole-number serial, any explicit forward adjustment of its next number, and a concurrency version. Use full year/month for monthly periods and explicit normalized buckets for generator-wide scope and reset disabled. |
| `resource_creation_requests` | A shared durable link from a creation-submission key and submitted-input fingerprint to its completed creation result, subject to the caller and operation checks in CG-15. |

These are normalized generator definitions and runtime state, extending the
Settings page's closed scalar registry. Do not duplicate them as another JSON
configuration in `application_settings`. Generated codes remain single values
in existing primary metadata columns or type-specific value rows; the counter
table does not contain a copy of every issued code. Reuse `event_history` for
configuration auditing rather than adding another audit store.

Retain counter state when resources are deleted; do not cascade those deletions
into a counter reset. No permanent issued-number reservation table or historical
uniqueness constraint is required: manual reuse follows CG-07, and audit history
records earlier use without preventing an otherwise valid assignment.

Use a unique B-tree key on
`(generator_id, scope_kind, scope_id, reset_frequency, period_bucket)`
with no ambiguous null buckets. Index enabled target lookups and enforce the
binding-overlap rules under concurrent configuration edits. Store an explicit
`applies_to` value (`all`, `untyped`, or `type`); require a positive `type_id`
only for `type`, including type-specific fields. Both `all` and `untyped` have
no type ID. Existing generators keep their meaning on upgrade: a selected type
becomes `type`, otherwise `all`; none becomes untyped-only automatically.
Preserve existing counters, versions, values and audit history. For compatibility,
a request omitting `applies_to` retains the previous interpretation: a type ID
means `type`, otherwise `all`. New clients send the explicit selection.
Retain counter
identity/history through configuration changes as required by CG-07; changing
the configuration version must not silently create a fresh counter.
Enforce the unique caller/operation/submission key on creation requests so
concurrent retries cannot create independent results.

Allocate with an atomic insert/update returning the serial, resolving concurrent
first use through the unique counter key. Updates serialize only on the counter
being allocated. Read one consistent configuration version per operation and
coordinate configuration edits with allocation. Acquire multiple counter locks
in a consistent order and keep the allocation transaction short, with no waits
for uploads, user input or external services. Commit counter updates with the
resource as required by CG-07. Ordinary `nextval` allocation is unsuitable here
because its advancement is not rolled back with a failed resource transaction.

Many generators sharing these tables is not itself a reason for partitioning.
Measure concurrent allocations: a heavily used single counter can cause row-lock
waits even with perfect indexes. Avoid global allocation locks or one shared
settings-row rewrite per issued code. Maintain appropriate autovacuum for the
updated counter table. Do not introduce serial-range reservations or additional
business scopes to bypass contention; those would alter the stated allocation
semantics.

For code ordering, evaluate matching B-tree indexes on existing value storage,
for example `(aggregation_id, record_number COLLATE erms_code_natural, id)` for
records within one aggregation, and an appropriate field-ID/text-value expression
index for type-specific Text values. Different global or parent-filtered lists
may require different index shapes. Preserve existing uniqueness and matching
indexes, account for extra write/storage costs, and adopt only indexes supported
by measured plans and complete API timings.

PostgreSQL references:
[row locking](https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-ROWS),
[sequence rollback behavior](https://www.postgresql.org/docs/18/functions-sequence.html),
[index collations](https://www.postgresql.org/docs/18/indexes-collations.html) and
[indexes for ordering](https://www.postgresql.org/docs/18/indexes-ordering.html).
See also [uniqueness checks during concurrent saves](https://www.postgresql.org/docs/18/index-unique-checks.html).

## 10 Continuing a series and safe retries

**CG-14.** Allow an administrator with `app.settings.manage` to set the next
number for one selected generator, scope and reset period. Show its current next
number and accept only a whole-number advance beyond it. For example, after an
import used numbers through 500, set the next candidate to 501 rather than
changing the starting number for every scope.

The next allocation starts from the explicitly selected candidate, then follows
the configured increment, skipping occupied candidates under CG-07. Preserve
stored codes and other counters. Coordinate the adjustment with live allocation,
require an expected counter version and a nonblank reason, and save its before/
after audit evidence in the same transaction. Changing Starting number alone
still applies only to previously unused counters.

**CG-15.** Give each logical creation submission a stable key that is reused
when the same submission is retried after a timeout or lost response. Scope it
to the authenticated caller and creation operation, and bind it to the submitted
inputs. Concurrent or later retries of a completed submission return its saved
creation result rather than creating another item or allocating more codes.

Reject a completed key reused with different inputs. Recheck current permissions
before returning an earlier result. A rolled-back attempt remains retryable.
Persist the completion link atomically with all created resources, generated
codes and counter changes, including atomic batches. Retain enough completion
information after resource deletion to report the earlier outcome without
recreating deleted items. UI forms, drafts and API callers must preserve the
same submission identity across retries; a new intended creation uses a new key.

## 11 Deferred enhancements

Uniqueness rules for type-specific field values, including employee codes and
contract numbers, are a separately planned future enhancement. This version
does not add those constraints to Text fields. Fiscal-year resets, check digits
and shared counters across different fields also remain outside this version.

## 12 Revision history

Advance the revision number and update the date and history whenever this
specification changes substantively. Revision 0.2 consolidates the discussion
changes that were previously left unversioned; they were not separate numbered
releases.

| Revision | Date | Changes |
| --- | --- | --- |
| 0.1 | 26 November 2026 | Initial draft covering Text targets, patterns, contextual placeholders and serial generation. |
| 0.2 | 26 November 2026 | Consolidated review changes: explicit natural collation and single-value storage; optional zero-padding width and complete-code length; five-value previews and simulations; monthly resets and owning-unit scopes; shared database design, audit and reason rules; collision skipping, forward adjustments and safe retries; manual number reuse after deletion; numberless drafts and distinct file-drop paths; overlap examples; approved optimistic conflict handling with exact chosen numbers, preserved drafts/files and documented tradeoffs. Type-specific value uniqueness remains deferred. |
| 0.3 | 26 November 2026 | Reconciled all CG-01–15 requirements with the implementation phases and verification coverage. Clarified that generator naming remains a separate proposal. Approved at the user's direction after correcting revision history and completing the consistency review; implementation has not started. |
| 0.4 | 26 November 2026 | Added the user-approved required generator name to configuration, storage, dialog, listing and audit history. Renaming preserves stable identity, bindings, counters and stored codes; name changes require the existing edit reason and audit protections. Added validation and rename verification and aligned the implementation plan. |
| 0.5 | 27 November 2026 | Documented the user-approved ICU limit: numeric ordering is guaranteed for runs of up to 254 significant digits; longer runs retain ICU ordering. Kept `erms_code_natural`, one stored Text value, optional padding and no additional digit cap. Verified the boundary in a disposable PostgreSQL database and aligned implementation-plan verification. |
| 0.6 | 27 November 2026 | Added the user-approved three-option Applies to selector: All items, Untyped items only, or One selected type. Allowed untyped-only and individual-type generators to coexist, retained overlap rejection for All items, and required consistent creation/recommendation/hint matching, explicit storage, audit display and compatible upgrades. |
