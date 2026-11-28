# Custom Code Generators Integration Design

**Authority:** [Approved specification revision 0.6](../specs/custom-code-generators.md),
CG-01–15, and the [implementation plan](../specs/custom-code-generators-implementation-plan.md).

**Updated:** 27 November 2026.

This design maps the approved behavior onto the current code. Administration
APIs, creation/replay adapters and phase 3 dialog safeguards are implemented.
Natural ordering and the administration UI remain later phases. The table below
retains the phase 0 behavior for comparison.
The specification governs product behavior, permissions and acceptance.

## Existing creation paths

| Entry point | Phase 0 behavior | Phase 3 integration |
| --- | --- | --- |
| `main.create_aggregation` | Resolves root/child permissions and Create for; prepares type values before inserting. | Generate eligible blank values after authorized context/default resolution and before required-value validation. Root and child paths use the same service. |
| `main.create_record` | Locks and authorizes the parent, selects the creator role, prepares type values, then inserts. | Use the shared generator service for primary and typed fields in the same transaction. |
| `main.create_record_draft`, `update_record_draft`, `get_record_draft` | The record number is optional/null. Uploads remain private staged components. | Keep numberless saves. Persist chosen-number provenance with the draft without allocating or reserving a serial. |
| `main.commit_record_draft` | Locks the draft and checks `record_number` before final creation; promotes components and deletes the draft on success. | Find an earlier completed submission first. Resolve authorized context, generate eligible blanks, then validate final required fields. Preserve draft/files after failure. |
| `main.commit_record_draft_placement_correction` | Performs the existing closed-placement checks and delegates to draft commit. | Preserve its reason and governance checks; share allocation/replay with ordinary final commit. |
| `messaging.capture` plus final draft commit | Creates a capture draft; finalization produces evidence using the final record ID and number. | Preserve capture access and PDF/component guarantees. Prepare conversion work before taking counter locks; final evidence must contain the number actually saved. |
| `main.create_records_from_file_drop` | Calls legacy `next_numbers` and creates either one combined record or a separate-record batch with components. | With a configured generator, obtain new available numbers automatically; one per record. Commit the whole batch or roll it back. |
| `record_collection_drop`, `record_capture` | Drops that need review enter the existing draft editor. | Keep draft/review behavior; a suggestion already placed in the field is fixed until explicitly changed. |
| `number_suggestions.suggest_number` | Read-only legacy suggestions from parent/classification context; no reservation. | Add type and existing Create for context; use the applicable generator and return provenance. Preserve legacy fallback when none applies. |
| `resource_number_controls`, `record_capture`, `entity_creation` | Store/display a number; the shared suggestion control protects against some late responses. | Retain automatic/manual origin, reject obsolete responses and carry the same creation identity across uncertain retries. Context changes cannot silently replace a chosen code. |
| `typed_metadata.prepare_metadata` | `resolve_resource_type_values` applies static defaults and immediately validates required values. | Separate default resolution from final required-value validation for creation so a generator can fill a blank required Text value. Ordinary update semantics stay intact. |
| Ordinary record/aggregation update and later type assignment | Existing field/lifecycle/permission validation. | No generator invocation or backfill. Authorized manual entry, including freed numbers, keeps existing validation and audit. |

Direct-create schemas now allow eligible Text inputs to be provisionally blank.
The service still requires valid final metadata after defaults and generation;
the database's live-resource identity constraints and ordinary update models
remain authoritative. Completed direct requests are looked up before
creation-only model validation: a review date that has since passed must not
prevent replay of an earlier success. New requests still enforce that rule.

The creation UI's required-field checks must use the applicable generator
bindings instead of rejecting every blank required Text control locally.
Provide a bounded creation-authorized binding lookup returning stable field
keys/IDs, without administrator configuration or business-resource values.
`GET /api/v1/code-generation/bindings` returns primary bindings and bindings for
at most 100 requested type-field IDs. The form requests visible fields; Save
checks visited definitions in batches of 90, leaving room for primary hints in
the 100-row response. It does not download all type fields or generator settings.
Recheck eligibility and all final required metadata on the server; a cached
form hint never authorizes generation. This also covers required typed Text
fields that currently fail before the allocator could fill them.

The server target catalogue must describe editable primary Text fields from the
actual create contracts, not every database text column. Current candidates are
record number/title/description and aggregation number/title/description plus
the editable aggregation location codes. Location codes retain their existing
200-character and governance rules. Dates, ownership IDs, enum/choice fields,
inherited record locations, disposition numbers and system timestamps are not
eligible merely because a projection or database column contains text.

## Generator and counter interfaces

Definitions use a stable generator ID, required nonblank name, resource kind,
primary key or type-field ID and explicit `applies_to` (`all`, `untyped`, `type`).
Only `type` carries a positive type ID. Type-specific fields always use `type`.
Name/applicability edits keep generator identity and counter keys. All items
includes typed and untyped items; untyped-only and individual-type bindings can
coexist on the same primary field. Overlaps are rejected rather than prioritized.
Stored `type_population` ranges cover all IDs, only the internal untyped point 0,
or the selected positive type ID. Creation bindings, recommendations and scoped
hints all use the same range-membership rule; no fake type is created for 0.
Missing applicability in legacy API bodies infers `type` from an existing type
ID, otherwise `all`. Migration 127 backfills that same meaning without changing
configuration versions, dates, counters or immutable history. Old audit snapshots
infer their original applicability from their captured type ID.

Use decimal digit strings on JSON transports for serials, starting numbers,
increments and explicit next numbers. Never pass them through JavaScript Number
or Python binary float. Validate whole numbers and operate exactly; padding
width and complete-code character limit remain ordinary bounded whole-number
lengths. Preserve existing raw typed-metadata JSON handling in
`metadata_json.py` rather than decoding and re-encoding precise values as floats.

The configuration service reads current committed definitions without a second
settings cache. It exposes bounded listing/target selection and reuses
`app.settings.manage`, `If-Match` and `X-Change-Reason` conventions. Creation
reasons are optional; updates, renames and explicit forward adjustments require
a nonblank reason. No new environment setting, privilege or name-based counter
identity is needed.

Use one captured server instant, the validated `DEFAULT_WORKING_TIMEZONE`, the
resolved parent/effective classification/scheme, owning unit and eligible
Create for role. Use Gregorian dates and ASCII digits. The counter key is
`(generator_id, scope_kind, scope_id, reset_frequency, period_bucket)` with
explicit normalized whole-generator/Never buckets, stable IDs and full year or
year/month periods. Keep state when configurations change or resources are deleted.

One parser/renderer supplies production and simulation behavior. Administration
simulations use unsaved validated definitions, fictional context and isolated
counters. They never read business-resource values to fill sample context or
change real counter state. Validate complete Unicode character length before
building oversized padding or accepting a rendered value.

Preview requests contain `configuration`, the selected `scenario` and
`sample_contexts`. The response contains five `items`, each with its complete
`value`, exact digit-string `serial`, simulated `date`, scope label and reset
marker. Sample contexts carry fictional codes, not permission to resolve live
business-resource IDs. Invalid configuration or output length returns validation
information instead of stale values presented as current results.

The administration API also flags an obvious independent-series risk: another
enabled generator for the same globally unique primary-number field has the
same pattern, starting number and effective padding width. This advisory is
shown on opening, previewing and saving a configuration; it does not reject
otherwise disjoint type bindings or replace the database's overlap rules.
An edit preview includes its optional `generator_id` so it excludes its own
saved definition. This is conservative detection, not a proof that other
patterns cannot collide. Save-time uniqueness and fresh-candidate skipping
remain mandatory, including collisions across different generator definitions.

## Exact chosen numbers

The recommendation response carries its number and automatic origin, including
the generator identity and the scope/period context needed to explain it. The
form retains that origin when it inserts the number. An explicit user edit
changes the origin to manual. Persist the origin when saving a draft so reopening
it cannot silently turn an accepted automatic number into manual entry.

On final creation, the allocator derives the next valid candidate itself from
the current locked counter and current authorized context. It compares the
rendered result with the exact chosen value before allocating. Browser-supplied
serials never advance counters. This needs neither a signed reservation nor a
new signing secret. If a changed counter, period, context or configuration makes
that exact allocation impossible, return a conflict/review result. Preserve the
chosen number, metadata and staged files. A stale definition version alone must
not bypass revalidation or silently authorize a different code.

For a blank field or a newly requested recommendation, skip occupied primary
numbers using the configured increment. Recommendations perform no counter
updates. Actual skip/allocation changes commit only with the final resource.
For an already chosen value, a collision ends the attempt; it never enters a
loop that selects a replacement. Ordinary typed Text values gain no uniqueness
constraint. Check hidden primary numbers without disclosing their resources.

The client must distinguish explicit value changes from rendering a returned
suggestion; identical displayed text is insufficient to establish origin.
Late requests must match the current context and field revision and must not
overwrite a number chosen or edited since the request began.

Carry this origin in `generation_intent`, keyed by stable primary field key.
Each entry identifies `source` (`generator` or `legacy`) and, for a generator,
`generator_id`. The actual number stays in its ordinary Text field; origin is
not a second padded/unpadded copy. Direct JSON creates and draft saves carry
the object in their body. Draft commit uses the saved intent; multipart input
encodes the same object as JSON. Explicit manual edits clear its entry. The
server validates its shape/target and derives scope, period and serial itself.

## Errors and versions

Use structured `detail` with `code`, localized `message_key` and safe
`parameters`. Preserve existing authorization errors and
`duplicate_resource_number`; do not expose a hidden conflicting resource.
Definition updates use the existing positive-version `If-Match` parser. Counter
adjustments additionally accept version `0`, meaning that the selected bucket
has never been used. Reading an unused bucket does not insert a row. A missing
precondition returns 428 and a stale version returns 412 without a successful
change audit event. Do not relax version validation for other entity updates.

| Condition | HTTP status | Error code |
| --- | --- | --- |
| Invalid definition, name, pattern or numeric setting | 422 | `code_generator_invalid` |
| Enabled target populations overlap | 409 | `code_generator_overlap` |
| Required generation context is absent | 422 | `code_generator_missing_context` |
| Complete rendered code exceeds its allowed length | 422 | `code_generator_length_exceeded` |
| An accepted automatic number cannot still be allocated unchanged | 409 | `code_generator_recommendation_conflict` |
| A configuration edit/adjustment has no nonblank reason | 422 | `code_generator_reason_required` |
| An explicit next-number adjustment does not advance | 422 | `code_generator_backward_adjustment` |
| Final creation has no stable submission key | 428 | `creation_submission_key_required` |
| A completed submission key is reused with different inputs | 409 | `creation_submission_conflict` |

Create English and Arabic error catalogue entries in the same implementation
change that first exposes these messages. Invalid inputs, stale edits and
failed creations retain no partial allocation/configuration changes.

## Creation identity and replay

Use a dedicated `Idempotency-Key` UUID header for a final logical creation,
distinct from per-request audit IDs. The UI creates it once before submission
and retains it across a timeout or lost response. JSON creation, final draft
commit, placement-correction commit and multipart file-drop use the same header.
Draft editing/upload requests do not allocate codes and do not substitute for
that final creation identity. API clients must be updated to supply and retain
the key; rejecting a missing key must be documented as a client upgrade rather
than silently pretending a newly generated server key protects retries.

Scope the durable unique key to authenticated caller and operation. Derive a
server fingerprint from submitted inputs: stable relationship/type/role IDs,
exact primary and typed inputs and chosen-number origin. Direct multipart
creation includes ordered file identities and actual content checksums. Draft
commit identifies its saved draft and submitted commit options; lock and
validate that staged package before its first creation. Completed replay must
remain possible after that draft has been deleted. Exclude audit request IDs, request
timestamps and multipart boundary bytes. Canonicalize object key order without
float conversion. File order and contents remain significant.

Check a completed request before attempting to reopen a draft that a successful
commit has already deleted. Recheck the caller's current access before returning
its result. Persist completion with the resources and counters in one
transaction; a failed transaction leaves the same intended submission retryable.
Concurrent retries share the unique key and return the one completed outcome.
Different inputs for a completed key conflict. Keep completion information after
deletion and report the earlier outcome without recreating an item.

Completed responses also participate in the existing permanent-destruction and
retained-metadata erasure rules. The canonical authorized destruction procedure
now removes destroyed descriptive metadata from their response snapshots.
It retains the caller/operation/key, fingerprint and resource identities so a
retry reports the earlier unavailable outcome and cannot recreate it. The
receipt must not become an extra recoverable copy of erased metadata.
The response lookup uses an index on resource kind and safely decoded resource
ID; long manual/generated Text values are not index keys. The existing
destruction authority is required for this narrowly permitted receipt update.

A confirmed failed attempt followed by a deliberate correction uses the
corrected submission identity. An unknown-outcome retry retains the original
identity and payload until its outcome is resolved. Do not transparently create
a new key on each retry or allow a changed payload to conceal an earlier success.
An error carries `Creation-Outcome: not-created` only when the per-key lock found
no earlier completion and this attempt failed before finishing its transaction.
Clients may then correct the inputs. Authorization or validation errors before
that lookup do not prove the outcome of an earlier lost response. A completed
or potentially committed response never carries this proof. Error bodies retain
their existing contracts.

Each dialog owns a `CreationAttempt`. An uncertain response freezes its inputs
and offers **Retry original creation**, preserving the original key and body.
Draft retry goes straight to commit, without trying to edit a draft already
deleted by a successful commit. Direct file drops retain owned temporary files
and rewind them for retry. After confirmed failure, **Correct details** retains
those files and uses a new key if the inputs change. These are per-form states,
not a configuration or result cache; page deletion releases owned temporary
files after any active request finishes. No preview or recommendation reserves
a number.

NiceGUI's upload callback retains files synchronously before scheduling the API
request. Disk-backed uploads retain an owned descriptor, avoiding a full copy
or checksum pass on the UI event loop. Local upload identities distinguish
duplicate filenames; the API still fingerprints the actual ordered checksums.
Larger retry files stay on temporary disk and are released on completion or
abandonment. An active request finishes before its owned files are closed.

The existing closed-placement creation route previously set a context that the
database closure guard did not recognize. Its phase 3 repair follows security
specification section 12.4: a protected database function checks the existing
creation/correction privileges, governance clearance and reason, locks the
destination ancestry and binds one new internal record ID to the transaction,
backend, caller, destination and clearance. Birth-content authority is established
only by that record's insert. It permits the initial component promotion, not
later edits to a closed record or its files. No closure date, application
privilege, public API flag or additional table is introduced.

`begin_closed_record_creation(bigint,bigint)` has no PUBLIC execute grant. The
API database role must own it or receive an explicit execute grant from the
schema owner during deployment. This is database-role setup, not a new user
privilege. The database checks the required user authority independently of
the API; setting the old context flag cannot supply governance clearance.

## Transactions and lock order

Creation currently takes the shared authorization-continuity lock, then existing
parent/draft/resource locks; type metadata participates in that transaction.
Preserve those protections. Generator locking must follow them, with request
identity coordination before resource mutation and counter locks last:

1. Authenticate and locate/recheck any completed logical request.
2. Finish upload receipt, inspection and external conversion preparation before
   counter allocation; retain the existing staging/cleanup ownership.
3. Take the existing continuity and authorized parent/draft/resource locks in
   their established order. Resolve type/default/context values. Acquire needed
   field-definition share locks in stable field-ID order before binding guards.
   Parent lookups use the final `FOR UPDATE` mode already required by resource
   authorization and medium guards. Starting with `FOR KEY SHARE` and later
   upgrading it deadlocked concurrent sibling creations; the integrated load
   regression verifies acquiring the final mode before counter allocation.
4. Coordinate the relevant target with shared transaction-scoped binding guards,
   including targets for which no generator exists. Re-read definitions after
   acquiring the guard so enabling/retargeting cannot race a stale lookup.
5. Lock/initialize needed counter rows in deterministic generator/scope/period
   order, render and validate, then persist resources/typed values/components,
   completion information and existing audit events in the same transaction.

Configuration writers take exclusive guards for old/new logical targets in a
consistent order. A native GiST exclusion constraint enforces overlapping
primary-field type populations, including All items versus untyped-only or named types, even
with an older transaction snapshot. Partial unique indexes reject identical
enabled bindings and duplicate type-field bindings. The trusted PostgreSQL
[`btree_gist` extension](https://www.postgresql.org/docs/18/btree-gist.html)
supplies the text equality operator class used with the type range. Fresh
initialization and upgrades install it transactionally; deployment requires it
to be available to the database installer. No persistent database was migrated
during implementation. Allocations share target guards and do not serialize globally.
Coordinate direct field-definition changes with eligibility/length checks.
Definition writers must also lock referenced fields before binding guards:
otherwise a field edit could hold its row while waiting for the guard, as a
generator edit holds the guard while waiting for the field. Verify that reversed
ordering cannot appear in direct database writes as well as API operations.

Do not hold a definition row lock while waiting in the reverse order for a
binding guard. PostgreSQL UPDATE obtains its row lock before a row trigger;
allocation should read the guarded definition without an additional conflicting
definition-row lock. Verify direct-write, configuration and multi-counter races
in disposable databases rather than assuming this order prevents every cycle.

Field-length reductions use PostgreSQL's normal Read Committed mode. A frozen
Repeatable Read or Serializable snapshot can miss a generator-limit increase
committed by another transaction, despite the advisory guard. The database
therefore rejects a field-length reduction in those snapshot modes with a
retryable `40001` error; retry the whole operation at Read Committed. Unchanged
limits, compatible increases and label edits retain their existing transaction
modes. Native foreign keys protect datatype/deletion changes. This addresses a
reproduced stale-snapshot race, rather than assuming that waiting on a lock
refreshes the transaction's snapshot. See PostgreSQL's
[transaction isolation rules](https://www.postgresql.org/docs/18/transaction-iso.html).

Only recover from the intended record/aggregation number uniqueness violation,
using a savepoint that preserves a usable transaction. Unrelated integrity or
authorization errors roll back the whole creation. `nextval` cannot allocate
business serials because its advancement survives rollback.

Message-capture evidence needs the final record ID and number before rendering.
Its slow preparation now precedes counter locks; final persistence verifies the
prepared number exactly. A competing creation can take that number while
rendering, in which case capture returns a conflict and preserves its draft and
original staged bytes. Only an ordinary internal resource ID is preallocated;
business serials remain transactional and unreserved.

Write capture history after allocation's retry savepoint is released, within
the same outer creation transaction. This preserves its existing same-transaction
history guard. A history failure still rolls back the record, files, counter,
request receipt and draft deletion together.

## Sorting and cache integration

| Existing area | Implemented phase 4 behavior; measured overruns recorded separately |
| --- | --- |
| `crud.list_rows` and resource collection routes | Apply natural ordering only when the requested field has an attached generator; authorize/filter/sort before the page limit. |
| `browse._page` and resource relationship selectors | Change both sort expressions and keyset comparisons from the current `C` comparison together. Scope cursors to submitted criteria and current ordering. |
| `search.search_rows`, `type_search.sort_sql`/`sort_joins` | Apply the same attached-field rule to primary and type-specific Text sorts; preserve native non-Text sorts and existing null/tie rules. |
| `search_cache` and saved execution | Include current ordering semantics in reuse/invalidation so an affected cached list cannot retain the former ordering. Keep the one session/tab slot. |
| `search_page` and collection hydration | Apply attached-number natural ordering to both contained-record page selection and final row ordering; retain the existing display/capability retrieval. |

`code_ordering.natural_fields` performs one bounded distinct lookup for the
requested eligible Text sort fields. Disabled, still-bound definitions count;
unbound definitions do not. No lookup is needed for ID/relevance or unrelated
sorts. A primary field uses one consistent ordering across its stored values,
including legacy/manual values; its applicability choice does not
create a different collation for individual rows. Typed fields use stable
defining-type/field identity. No definition cache is introduced.

Ranked fingerprints contain the attached natural-sort field set, rather than
generator names, patterns, enabled flags or versions. Hierarchy cursor scopes
identify natural ordering and reject a cursor from the previous ordering.
Disposition aggregation report rows use the same attached-number collation.

Generic-search joins and result limiting, browse authorization/display/count
projections, and execution-setting guards retain their original implementation.
The unrelated experiments made during timing investigations were removed on
27 November at the user's direction. Search optimization belongs to a separate
session; the historical measurements are retained in the verification reports.

Keep one stored Text value. Use the existing deterministic `erms_code_natural`
collation, with stable IDs as the final tie-breaker. Preserve matching,
uniqueness, GIN/trigram/prefix indexes and relevance. Adopt matching-collation
B-tree indexes only after actual plans and complete API timings, including
valid long-code writes and storage/write costs.

The user accepted ICU's existing 254-significant-digit run limit on 27 November
2026 (specification revision 0.5). The disposable diagnostic under
`.runtime/custom-code-generators/ordering-metrics/` records the installed
deterministic ICU collation and the verified boundary. Longer digit runs remain
valid codes and follow ICU ordering; no new validation limit or stored sort
representation is introduced.

## Verification workload

Phase 0 runs the existing numbering, creation/draft/file-drop, type, settings,
policy and cache regressions plus explicit numberless/conflict-preservation
characterizations. The standard and larger-text runners each own a new
disposable database, retain their source hashes/plans/timings and drop it in
`finally`. Do not run either performance measurement concurrently with another
test workload. Preserve failed baseline samples without changing search SQL or
the accepted compressed-storage policy just to improve a phase 0 number.

Later phases add concentrated same-counter and independent-counter workloads,
simultaneous first definitions/allocations, binding/configuration/adjustment
races, batches with multiple generated fields, hidden occupied values and lost
responses. Record statement counts, complete request timings and lock waits.
No baseline test is evidence that the new generator itself is complete.
