# Creating records by dropping files on an aggregation

**Approved**

## Drop target and record creation

**AFD-1.** Show a page overlay like the record page’s while files are dragged
over the aggregation page. A single file can be dropped anywhere in the
aggregation page content, including on the **Create record** card. For
several files, show both targets below together in the overlay. Dropping
several files outside those two targets creates no records.
Dismiss the overlay on leave, cancellation, or drop. For a **Physical**
aggregation, disable dropping and show “Physical aggregations cannot accept
digital files.” Apply the existing **Add record** authorization and
eligibility checks to the drop and recheck them before saving.
[Aggregation and record pages](aggregation-and-record-page-amendment.md)

**AFD-2.** The target determines how the files are saved.

| Drop | Result |
| --- | --- |
| One file | Create one record with the file as its sole digital component. Use the full filename, including the extension, as the **Title**. |
| Several files on **Create separate records** | Create one unlinked record per file using the single-file rule. |
| Several files on **Create one record with all files** | Create one record with every dropped file as a digital component in the order confirmed in the dialog. Prefill an editable **Title** with the first filename supplied by the browser, including its extension, and require confirmation in a dialog before creating the record. |

**Drop order** means the order of files supplied by the browser, not the order
in which the user clicked to select them in Finder or another file manager.
The browser does not expose that selection history, so the first supplied
file may differ from the first file the user selected. For the multi-file
**Create one record with all files** target, always show the **Title** dialog
so the user can confirm or edit the suggested title. Replace the filename
dropdown with a numbered, scrollable list of all dropped filenames, including
extensions, initially in browser-supplied order. Show at least five complete
file rows before scrolling when five or more files are present. Provide
keyboard-accessible **Move earlier** / **Move later** controls, disabled at
the first/last position respectively.

Reordering proposes the new first filename as Title, including its extension,
while the title still matches the previous first filename. Preserve a custom
title when reordering. Users can edit Title freely and must click **Create
record** to confirm, using existing record-title validation. Create digital
components in exactly the final displayed order, with consecutive component
orders starting at 1. Track files independently even when filenames repeat;
reordering must preserve every file's original name and content. Cancelling or
dismissing the dialog creates no record or components. These ordering controls
apply only to multi-file **Create one record with all files**.

Set **Medium** to **Digital** for every record and create it directly in the
current aggregation. Assign the next available suggested **Record number** for
each record in drop order and enforce uniqueness at save.

**AFD-3.** Count eligible **Create for** choices after restricting the user's
currently effective roles to the aggregation's owning organizational unit.
With exactly one eligible choice, use that role and its direct organizational
unit, even if the user has other effective roles in other units. For a single
file or **Create separate records**, save automatically. For multi-file
**Create one record with all files**, show the editable **Title** and reorderable file
list and require confirmation as specified in AFD-2.

With multiple eligible choices, require **Create for** selection. For
multi-file **Create one record with all files**, show **Title**, the reorderable file
list and **Create for** together in the same dialog; for the other drop cases, show
only **Create for**. Submit with **Create record** when creating one record
or **Create records** when creating several. With no eligible choice, deny
creation. The selection applies to the entire drop.

Every new record inherits the aggregation’s owning organizational unit.
**Create for** lists the user’s currently effective roles that belong directly
to that unit. The selected role receives the creator ACL grants on each new
record. If the user has no effective role in the owning unit, creation is
denied even if a role in another unit grants `record.create`.
[Ownership and role selection](organizational-ownership-and-default-acls.md#82-child-aggregation-and-record-creation)

**AFD-4.** Save all records and digital components from a multi-file drop in
one transaction for either target. If any file fails validation or saving,
report the cause and commit no records or components. After a successful
multi-file drop, show one toast with the number of records created.

## Recent Activity

**AFD-5.** Place **Recent Activity** beside the records listing, on the right in
English/LTR and on the left in Arabic/RTL. Use the Dashboard’s recent records
activity pattern for the signed-in user’s **Created**, **Updated**, and
**Viewed** events, newest first, with the same preview and **View all**
interaction. Scope both views to records directly in the current aggregation
and apply current record visibility before selecting entries. Entries open
the record page. The panel uses its own activity scope independently of the
records listing filter. Refresh the panel automatically after successful
record creation on this page, including through **Add record**, so new
records appear as **Created** activity. After a successful child-record
component preview, refresh the panel so the record appears as **Viewed**,
without reloading the records listing or changing its page and filters.
Reuse the existing batched activity
query, including creator attribution; rendering the preview or **View all**
must not perform per-record API requests or repeat authorization queries per
row. Fetch record details only when the user opens a record.
[Dashboard recent activity](../docs/dashboard.md#personal-recent-activity)

## List order and pagination

**AFD-6.** Sort records by originated timestamp (`date_originated`) ascending
and child aggregations by opened timestamp (`date_opened`) ascending. Use ID
ascending as the final tie-breaker in both lists. These timestamps represent
historical chronology, including legacy-system resources and bulk capture of
physical material; `date_created` records when the resource entered Wathiq.
For resources newly originated/opened in Wathiq, the historical and system
creation timestamps normally coincide. Aggregations use their existing Opened
field; no new Originated field is introduced.

This supersedes both item-number and system-creation ordering. Textual item
numbers can put `.10` before `.2`, while system creation time can put an old
migrated item after a newer historical item. A newly captured historical item
may appear on an earlier page; Recent Activity still makes the new capture
visible using its existing activity timestamps.

After a successful drop, refresh the current records page and count using
the submitted filter. Preserve any unsubmitted filter edits; do not jump to
the last page.
[Aggregation list contract](aggregation-and-record-page-amendment.md#3-aggregation-page)

**AFD-7.** Provide a keyboard-accessible **Last page** control on each of the
aggregation page’s two pagers. Use the list’s current sort and page size and
the submitted filter, if any. Disable the control on the last page.
[Wathiq pagination rules](../docs/webui-design-language.md#12-search-filtering-sorting-and-pagination)

## Acceptance checks

- **AFD-1–3.** Verify the Physical overlay and denied creation. Drop a single
  file on the page outside the central card in English and Arabic. Verify
  that several files dropped there create no records. Test the single target
  and both multi-file targets with one and multiple effective roles.
  With multiple effective roles but exactly one eligible owning-unit choice,
  verify automatic creation without a dialog for a single file and **Create
  separate records**. For multi-file **Create one record with all files**,
  verify a title-and-file-order confirmation dialog with that role assigned
  automatically. With several eligible choices, require selection and show
  **Title** alongside **Create for** only for the combined-record target;
  with none, deny creation. Check titles, suggested numbers, component counts
  and order, and zero relationship links. Verify that **Create for** offers only effective roles
  in the owning unit and that a caller with `record.create` whose roles all
  belong to other units cannot create records in the aggregation.
- **AFD-2–3: title confirmation.** Supply files in a known browser payload
  order that differs from alphabetical order and verify the suggested title
  is the first supplied filename, including its extension. Do not assert
  Finder selection-click order: it is unavailable to the application, which
  is why confirmation is required. Verify no record or components are created
  before **Create record** is clicked, with either one or multiple eligible
  roles. Test confirming the unchanged title, saving an edited title,
  existing title validation, and cancelling or dismissing the dialog.
  Verify edits affect only the record title, while all original filenames,
  file contents and confirmed component order are preserved. Check
  the dialog in English/LTR and Arabic/RTL.
- **AFD-2–3: file order.** Verify every dropped filename appears with its
  extension, initially in browser order. With more than five files, verify at
  least five complete rows are visible and the remainder can be scrolled to.
  Move files earlier/later, including by keyboard, and verify the numbered
  list and boundary controls update. Moving a different file to the first
  position updates an unedited suggested title; reordering preserves a custom
  title. Verify one record is created only after confirmation, with components
  numbered 1..N in exactly the final list order. Include duplicate filenames
  with different content and verify each file's identity, name and bytes are
  preserved. Exercise one/multiple eligible roles and English/LTR/Arabic/RTL.
- **AFD-4.** Fail one file on each multi-file target and verify zero records or
  components are saved. Verify one success toast with the correct record count
  for each target.
- **AFD-5.** Verify right/left placement in English and Arabic, current
  aggregation and visibility scope in the preview and **View all**, and
  automatic refresh after drop and normal **Add record** creation. Verify that
  preview and **View all** reuse one batched activity response with no per-row
  detail lookups, and discard responses after navigation or identity changes.
- **AFD-6.** Verify originated-timestamp ascending order for records and
  opened-timestamp ascending order for child aggregations across pages.
  Include migrated/bulk-captured items whose historical dates differ from
  their system creation dates, and numbers such as `.2` and `.10` whose text
  order differs. Verify a later-captured older item appears first. For equal
  historical timestamps, verify ID ascending across page boundaries even
  when creation timestamps differ, including filtered records. Confirm that
  a drop which adds a page leaves the current page selected. With a submitted
  filter that excludes the new record and different unsubmitted text, verify
  that the drop preserves the page and both filter values while Recent
  Activity shows the new record using the existing activity chronology.
- **AFD-7.** Use the keyboard to activate **Last page** on each aggregation
  page list. Verify that each control goes to its list’s last page and is
  disabled there. For records, verify that paging uses the submitted filter
  when the filter field contains unsubmitted edits.
