# My Tasks Priority column hidden — 29 October 2026

Destruction Process revision 1.5 §6.2 / DEST-21 records the user's approved
decision to hide the Priority column until its assignment and use are defined.
`frontend/webui/disposition/tasks.py` removes that column. A saved Priority sort
falls back to received-date ordering and clears its descending flag while
retaining the saved page size and offset. The existing stored field, shared
API contracts and minimum-priority filter retain their behavior.

The existing bilingual inbox regression now covers normal and formerly saved
Priority sorts, verifies the bounded offset and claimant projection, and checks
the hidden column. The disposition frontend and locale suite passed **477
tests** in 13.37 seconds; the temporary log is
`/tmp/erms-hide-priority-tests.log`.

Live browser verification used a uniquely named disposable canonical-schema
database with the real API and WebUI. Both English and Arabic tables retained
the standard Wathiq styling and fourteen columns, including Required action,
Age in days and Aggregations, with no Priority heading. Return navigation in
Arabic also retained the simplified table. The existing Jobs and workspace
tables provided the comparable presentation already verified in the preceding
[task-list amendment](task-list-simplification.md).

- [English task table](task-priority-hidden/english.png)
- [Arabic task table](task-priority-hidden/arabic.png)

The English manifest retires one unused key, `disposition.ui.priority`, for
**3,913 active keys**. The Arabic artifact has identical active-key order; all
retained entries are unchanged and the complete retired entry, including its
provenance, moved to `deprecated_items`. The root catalogue hash was updated.
No wording or drafts were generated, no administrator export was promoted and
nothing was published. Key coverage/order, blank/placeholder validation,
approved Arabic terminology, provenance preservation and artifact hashes pass.

The managed local stack was restarted successfully for **demo**. Its missing-only
seed stored zero drafts, protected 3,913 translations and corrected none. A
read-only check confirmed that the Priority definition is deprecated while its
entire Arabic database translation row is unchanged. Existing review requirements
remain. No schema, migration or environment setting changed.

The disposable database
`erms_messaging_test_acl_e98b6e7101ac49a080fc84d172477622` was dropped and its
absence verified read-only. The temporary connection file, owned preview
services and browser tab were removed. No persistent database test suite ran.
