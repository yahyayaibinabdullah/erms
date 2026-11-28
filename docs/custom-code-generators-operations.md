# Operating Custom Code Generators

This guide accompanies the [approved specification](../specs/custom-code-generators.md).
Deployment and persistent-database upgrades remain operator actions.
The implementation is delivered as local, uncommitted changes for the user's
review and testing. The [integrated verification report](verification/custom-code-generators-phase6.md)
records test evidence and search timings. Search responses over three seconds
are reported for separate optimization work under the user's 27 November
instruction; feature completion is not a claim that the strict latency gate passed.

## Upgrade

Use `database/schema.sql` alone for a new empty database, followed by the normal
separate seeds. For an existing installation at the preceding schema version,
apply `database/migrations/126_custom_code_generators.sql`, then
`database/migrations/127_code_generator_applicability.sql`, through the normal
migration procedure after a backup. An installation already at 126 needs only
127. Migration 127 preserves existing all-items and selected-type meanings;
none becomes untyped-only automatically. It preserves counters, versions, stored
codes and audit history while rebuilding the generator-population constraint.
It takes an access-exclusive lock on `code_generators` for its transaction. The migration is transactional. It creates
the shared definition, counter and completed-request tables and their indexes;
it neither enables generators nor rewrites existing resource codes.

The database must support ICU and the existing deterministic
`erms_code_natural` collation. The migration installs `btree_gist` for the
enabled-binding exclusion constraint. Run it with the database/schema owner's
normal DDL authority. Keep the canonical schema and application versions in
step: the new API expects these tables and guards.

The protected `begin_closed_record_creation(bigint,bigint)` function is not
executable by PUBLIC. If the API uses a separate database role, the schema
owner must explicitly grant that role execution. This preserves the existing
authorized closed-placement creation workflow; it grants no Wathiq privilege.
See [the integration design](custom-code-generators-integration.md) for the
transaction-bound checks.

DDL can wait for existing transactions and briefly block concurrent writes.
Schedule the upgrade accordingly. Retain rollback and space headroom for the
normal migration process. The disposable populated-upgrade measurements in the
[phase 1 report](verification/custom-code-generators-phase1.md) are evidence
for that fixture, not a production locking-duration guarantee. No environment
variable, vector-storage rewrite or server-wide planner change is required.

## Configure or continue a series

1. Open Administration → Settings → Code generation with
   `app.settings.manage`.
2. Enter a name and choose a record/aggregation Text field. For primary metadata,
   choose **All items**, **Untyped items only**, or **One selected type** under
   Applies to. The last option requires a type. Untyped-only can coexist with
   individual-type generators; All items overlaps both. A type-specific field
   belongs only to its defining type. Enabled bindings must not overlap.
3. Set the pattern, start, increment, scope, reset and maximum complete-code
   length. Optional zero-padding is a minimum width, not a serial digit limit.
   Start 10 and increment 10 gives 10, 20, 30, 40, 50.
4. Preview all five values and the applicable date/scope transitions. Samples
   use fictional contexts and fresh counters; they neither reserve numbers nor
   inspect the live next number. An independent-pattern warning calls for
   reviewing how the separate series are distinguished.
5. Save. A creation reason is optional; all later edits require one. History
   preserves the name and target at the time of each change.
6. To continue imported or legacy numbering, open Next numbers, select the exact
   scope and period, load its next number and advance it with a reason. The
   adjustment is versioned and forward-only. Check every relevant retained
   scope/period; advancing one does not advance the others.

Changes affect future final creations. Existing resources and ordinary edits
are not backfilled. Saved draft values stay as entered; finishing a draft uses
the current configuration and may reject a stale automatic suggestion. Manual
nonblank values remain supported. Numberless drafts can be saved without
consuming a serial. Direct file-drop
creation obtains fresh numbers automatically; a multi-record batch is atomic.

## Conflicts and recovery

A form suggestion is unreserved. Once shown in the actual number field, final
creation either uses that exact number or reports a conflict. It never quietly
substitutes another number. Preserve the draft and files, explicitly request
and accept a new suggestion or enter a manual value, and correct any document
that contains the earlier number before replacing its uploaded component.

If a save's outcome is unknown, retry the original submission with its original
inputs and key. Do not create a new submission merely because the response was
lost. A completed retry returns the same result subject to current access.
When the API confirms that no creation occurred, the user may correct inputs
and make a new logical submission.

Disable a generator to stop future generation while retaining its history and
counters. Re-enable it to continue the retained series. Removing its binding
also removes natural-sort attachment semantics; disablement alone does not.
Never delete or rewind counter rows to repair a series. Use a reasoned forward
adjustment. A deleted resource's available code may be reused manually with
normal permissions; the generator itself keeps moving forward.

## API-client upgrade

Final record/aggregation creation, draft commit, capture and direct file-drop
requests require a UUID `Idempotency-Key` for each logical submission. Keep it
stable across retries and preserve the exact inputs and ordered file bytes.
Draft saves and preview requests do not allocate numbers and do not require
this creation key. Send automatic/manual generation provenance using the
documented creation payload; do not turn a stale automatic suggestion into a
manual value to bypass a conflict. Existing clients must be upgraded together
with the API. Missing creation keys are rejected explicitly.

## Sorting and maintenance

Codes remain a single stored Text value. Only attached code-field ordering uses
`erms_code_natural`; matching, relevance and uniqueness retain their existing
rules. Numeric ordering is guaranteed for digit runs up to 254 significant
digits. Longer runs remain valid and follow ICU's ordering. Optional padding
does not change that ICU limitation.

Follow PostgreSQL's normal collation-version maintenance after an ICU upgrade:
check actual versus recorded versions and rebuild affected indexes before
refreshing recorded versions. Do not add unrestricted full-Text B-tree indexes
merely because a field has a generator; long legitimate values must remain
writable. Adopt extra indexes only with measured plans and complete request
timings. The existing normalized counter key supports independent generators
and scopes; requests for one counter necessarily serialize briefly while
allocating it.

The checked-in Arabic additions are generated drafts requiring human review.
Use the normal catalogue synchronization and explicit `--missing-only` seed
workflow when upgrading an authorized database. Preserve existing translations;
review and publish drafts through Translation Administration. A disposable
browser fixture's publication is not production translation approval.
