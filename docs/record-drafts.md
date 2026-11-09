# Record creation drafts

Record drafts let a user assemble record metadata and digital components before
creating an authoritative record. Uploading a staged component does not create
or update a record. The record and every staged component become authoritative
only when the draft is committed.

## Lifecycle

1. `POST /api/v1/record-drafts` starts an open draft.
2. `PATCH /api/v1/record-drafts/{id}` saves its record metadata.
3. `POST /api/v1/record-drafts/{id}/components` stages one or more files.
4. Components may be listed, removed, or reordered while the draft is open.
5. `POST /api/v1/record-drafts/{id}/commit` validates and creates the complete
   record package in one database transaction.
6. `DELETE /api/v1/record-drafts/{id}` discards the metadata and staged blobs.

Open drafts expire after seven days by default. Expired drafts cannot be edited
or committed. A later housekeeping job should physically remove expired drafts.

## Preview staged files

After an upload completes, supported files have a **Preview** action beside
their component card. This opens the same viewer used for saved records,
including component switching, PDF navigation and native image/media viewing.
Preview does not save the record or change unsaved metadata, file order or draft
expiry. Unsupported or incomplete uploads have no Preview action. If conversion
is unavailable, the upload remains staged and the viewer shows the error.

`GET` and `HEAD /api/v1/record-drafts/{draft_id}/components/{component_id}/rendition`
require the current draft owner, an unexpired open draft and `record.create` on
every request, including byte-range requests. The component must belong to that
draft. Preview provides no staged Print or Download action. After commit, the
saved record's normal component permissions apply.

The viewer reuses the mounted editor's component metadata and requests bytes
only for the selected file. Closing the viewer or abandoning the editor prevents
late responses from updating it. See the approved
[preview contract](../specs/digital-component-preview-navigation.md#4-preview-staged-components-before-record-creation)
and [verification evidence](verification/staged-component-preview.md).

## Atomic commit

Commit locks the draft, validates its required aggregation, record number, and
title, then inserts the record, ordered component metadata, PostgreSQL blobs,
and content audit events. If any operation fails, the transaction rolls back and
no partial authoritative record remains.

## Authorization boundary

Every draft endpoint requires both draft ownership and the current
`record.create` global privilege. The draft metadata and its staged components
form one in-progress record-creation package: `record.create` therefore permits
the owner to edit the draft, stage, remove, and reorder its files, and commit the
package. Committing also requires `aggregation.add_record` on the selected
destination aggregation and all applicable clearance and closure checks.

`record.component.add` is deliberately **not** required to stage files or commit
them as part of a new record. Once commit succeeds, the creation boundary ends.
Subsequent metadata changes require `record.modify`, and subsequent component
addition, reorder, replacement, or removal requires its matching
`record.component.*` global privilege and resource permission. `record.create`
does not grant any of those post-commit operations.

## Component ordering

Both staged and committed reorder endpoints accept the complete desired order:

```json
{
  "components": [
    {"id": 31, "component_order": 1},
    {"id": 12, "component_order": 2}
  ]
}
```

The list must contain every component exactly once and positions must be
contiguous from 1. Removal automatically closes any numbering gap.
