# Authorized demo schema upgrade — 20 October 2026

The user explicitly authorized migrations 053–070 on demo. A private custom-format
pre-upgrade backup was created and its archive listing verified before DDL.
All 18 migrations are installed and their receipts independently verified.
Application settings remain valid. Physical and digital execution gates are false.
No seeds, operational workers, destruction actions or settings edits were run on demo.

The upgrade exposed missing receipts in migrations 056, 057 and 064. Their
migration SQL and the self-contained canonical schema now record those versions.
064 is also explicitly transactional. For 056/064, already committed during this
request, the receipt was completed only after verifying the installed structures;
the non-repeatable DDL was not replayed.

The rollout rehearsal now asserts all 050–070 receipts on fresh and upgraded
schemas, supplementing structural parity. Its fresh/two-populated-database run
passed (`migration-receipts-regression.log`); all three disposable databases were
independently confirmed absent. No test suite ran against demo.

## Subsequently authorized execution release — 20 October 2026

The user separately authorized enabling physical and digital destruction on demo.
Both `disposition_private.physical_execution_released()` and
`disposition_private.digital_execution_released()` were changed from constant
false to constant true in that database, atomically. A new read-only connection
verified both values. Function ownership, permissions and security attributes
were preserved. No queued/running destruction existed before release; resource,
job, confirmation and run counts stayed unchanged. No destruction was executed
and no worker was started by this operation.

Original definitions and a private execution record were retained locally for
reversal. The checked-in canonical schema/migrations still default to false;
other databases were not changed. Closing a release gate does not undo content
already destroyed through a later authorized workflow action.
