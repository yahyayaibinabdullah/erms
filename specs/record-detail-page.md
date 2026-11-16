# Record Detail Page — Technical Specification

**Status:** Implemented  
**Project:** ERMS  
**Prepared:** 18 September 2026

## Purpose

A record is a first-class records-management entity and must have a dedicated
page rather than a small details dialog. The page provides enough space for its
metadata, lifecycle state, actions, and digital components in one working
context.

## Navigation

Every action that opens a record—including Records search results, aggregation
record tables, the aggregation browser, Dashboard favourites and recent
activity, and audit-event navigation—opens the same dedicated Record Detail
page. The page provides a Back action that returns to the originating
aggregation when one exists, otherwise to the originating Dashboard or Records
page.

The containing aggregation is displayed as a clickable field and opens that
aggregation's dedicated page.

## Record metadata and actions

The page header shows the record title, number, type icon, Favourite, eligible
Preview, Back, and Details. See the [approved amendment](aggregation-and-record-page-amendment.md)
for the status icons and Details dialog. The identity icon stays
beside the title at the reading start; Favourite, Preview, and Back form the
opposite-side action group. In Arabic, the header mirrors this placement and
Back uses a right-pointing arrow after its label. The Metadata tab exposes the
existing Edit, Delete, and Event history actions.
Edit and Delete are unavailable when the containing aggregation hierarchy makes
the record read-only. The page explains that inherited closure explicitly.

The metadata area shows at least the description, originated timestamp, created
timestamp, and containing aggregation. Secondary fields are in Advanced
metadata. Relationships and Holds have their own tabs.

Permanent deletion retains its confirmation. The confirmation states that all
digital components and stored content are deleted with the record while
immutable event history remains.

## Digital components

The complete Digital Components interface appears immediately below the record
header. Viewing the component list requires no additional click or dialog.
It includes:

- multiple-file upload and drag-and-drop;
- component metadata and ordering;
- preview and original-file download;
- event history;
- reordering; and
- removal.

The section is always rendered. A record without components shows the upload
control and an explicit **No digital components have been uploaded yet** empty state; it
must never collapse into an empty or invisible container. The empty-state panel
spans the component grid and is centered horizontally in the available page
width.

When the record is read-only through aggregation closure, upload, reordering,
and removal are disabled while preview, download, and history remain available.
The existing standalone Digital Components dialog may remain as a list-level
shortcut, but it is not used inside the Record Detail page.

## Acceptance criteria

1. Opening a record from every supported entry point displays a page, not the
   former record-details dialog.
2. The title and Details button open the Metadata tab with authorized actions.
3. Digital components load below the header automatically.
4. Component management retains the same closure and audit behavior as the
   standalone interface.
5. Editing refreshes the page and deletion returns to the appropriate parent
   context.
