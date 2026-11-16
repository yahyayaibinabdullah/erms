# Aggregation and record pages — amendment

**Status:** Approved 14 November 2026

**Record file layout update:** 15 November 2026

**Project:** ERMS

## 1. Scope

Users should be able to browse an aggregation’s contents or work with a
record’s files as soon as they open the page. Keep both dedicated pages in the
Wathiq shell. Put secondary information and governed actions in a Details
dialog on each page.

This amendment replaces the on-page placement requirements in the
[Record Detail Page specification](record-detail-page.md) for metadata, actions,
and Digital Components. Align the [Wathiq design language](../docs/webui-design-language.md)
§§6.3 and 7.8 and the [resource detail presentation rules](resource-medium-vital-status-review-and-location.md#132-resource-detail-and-lists)
with this layout. Existing permissions, lifecycle rules, confirmation steps,
and audit requirements continue to apply.

## 2. Header and status summaries

Both pages show the item type icon, number, title, and a compact row of Vital,
Closure, and Holds icons. The title and number form one control that opens the
same dialog as the visible **Details** button. Keep **Back** and **Favourite**
in the header. Keep eligible **Preview** on the record header and authorized
**Add child aggregation** and **Add record** actions on the aggregation page.

Use the same symbol for direct Vital status on both pages. Each icon has a localized name.
Its tooltip and accessible description report the current state. Clicking,
tapping, or pressing Enter or Space opens a short summary next to the icon.
Opening another summary closes the first. Escape dismisses the summary and
returns focus to its icon. The summary stays within the viewport in either
reading direction. Use icon shape and words to convey state as well as color.

| Icon | Summary |
| --- | --- |
| Vital | Keep the button the same size as the other status buttons. Use a solid red asterisk when the item itself is marked vital, a red outlined asterisk when only its descendants are vital, and a muted asterisk when neither is vital. Mention vital descendants in the tooltip and summary, including when the aggregation itself is vital. |
| Closure | Say whether the item is open, closed directly, or closed through an aggregation. For a record, closure always comes from its containing aggregation or an ancestor. When authorized, show the nearest closure source and its closure date and time in the user’s working timezone. If the source is restricted, show the inherited read-only state and withhold restricted details. |
| Holds | Show the count of effective holds under the existing disclosure rules, or **No active holds** when confirmed. List the first three holds whose names the user may see, in the same order as the full hold list. Add an ellipsis when additional authorized names are available. Indicate when some hold details are restricted. **View holds** opens the Holds tab. |

An unavailable status read shows that the status could not be confirmed. A
failed read must never appear as open, non-vital, or free of holds. Status
summaries are read-only. Changes use the existing governed actions.

## 3. Aggregation page

Show **Child aggregations** as cards and **Records in this aggregation** as
rows directly below the header, in that order. Keep both sections visible with
their own counts, paging controls, and loading, empty, and error states. Keep
existing card and row actions, including eligible record preview. The lists
show direct children and records assigned directly to the current aggregation.
Below each contained record title, show the labelled originated date, for
example **Originated 5 Apr 2024**, followed by the medium icon used in search.
Use the medium name alone as the tooltip and accessible label. Localize the
date and the label. Omit disposition status and keep the file count beside the
row actions.

- Page on the server. Application Settings controls the two page sizes
  independently. The defaults are 10 child aggregations and 25 records, and
  each setting accepts 1 to 100 items. Sort by the corresponding item number
  with ID as the final tie-breaker. Apply authorization and any submitted filter before calculating
  counts or selecting a page. Ordinary browsing can reach every authorized item.
- Paging makes one listing request for the affected list. Filtering also
  refreshes only that list. Keep the submitted record filter separate from
  the text being edited. Applying a filter starts
  on page one. Paging continues to use the submitted filter. Keep the filter
  available on zero matches. The submitted filter uses the existing shared
  search slot for the signed-in session and browser tab. If the slot is replaced
  or expires, rebuild from the submitted filter when the user pages. The shared
  search result cap applies to submitted filters only.
- Supply the capabilities needed by the cards or rows in the list response or
  through one batch capability request for that list page. Resolve them on the
  server for the returned items and current user. Never make a capability
  request per item. If capability data is unavailable, omit the affected actions
  and show the authorized rows. Action endpoints still enforce permissions.

The Details dialog opens on **Metadata**. It contains the following tabs.

| Tab | Contents |
| --- | --- |
| Metadata | Existing metadata and authorized actions. Place secondary fields behind **Advanced metadata** and retain the collapsed **Advanced** actions section. |
| Retention rule | Existing effective rule timeline, source, and disposition timing. Show **Retention and disposal instructions** in the **Rule details** expansion, with a dash for an empty value. Keep existing authorized override and acceleration actions. |
| Relationships | Existing paged relationship list and authorized add and remove actions. Keep the current target search and redaction rules. |
| Holds | Existing effective hold list and authorized hold actions. Distinguish direct, inherited, and combined protection and preserve restricted entries. |

In **Advanced**, group actions under **Metadata and review**, **Security,
access and audit**, and **Aggregation management**. Use bold headings in
sentence case. Put Move, ownership correction, Child defaults, Record defaults,
and Delete under **Aggregation management** when authorized.

## 4. Record page

Every existing entry point opens the dedicated record page. Show the
**Containing aggregation** link under the record title and status icons when
the user may see the aggregation. The link opens the containing aggregation.
The **Digital components** heading contains only controls for the record's files.

Place **Digital components** directly below the header. Show each file in a
collapsed row with its filename, file icon, size, availability, and eligible
preview and download actions. The filename and chevron expand the row with a
pointer or keyboard. Show the file type, dates, indexing status and time,
position, storage backend, and checksum in the expanded area. Put the existing
authorized reorder, reindex, history, and remove actions there. Keep the
existing pagination and use the existing component viewer for previews.

Show **Add digital components** in the section heading when the user can add
files. It opens the file chooser and accepts multiple files. When one or more
files are dragged over an eligible record page, show a drop target over the
page. Dismiss it on drop, drag leave, or cancellation. Other dragged items
do not trigger it. Both entry points use the existing upload flow and refresh
the list after upload. Keep the physical-record and closure rules. Show the
empty state only when the record has no digital components.

The Details dialog opens on **Metadata** and also offers **Relationships** and
**Holds**. Metadata includes the existing description, originated and created dates,
containing aggregation, lifecycle status, and authorized actions. The containing
aggregation remains a link when visible to the user. Keep advanced fields and
specialist actions in collapsed sections. Use the existing deletion confirmation.
Use the same heading and body text sizes for the Closed and Vital notices.

In **Advanced**, use the same heading styles as the aggregation page. Group
Vital status and Next review under **Metadata and review**. Group Security
level, Why this access?, and Access under **Security, access and audit**.
Group Move, Reindex components, and Delete under **Record management**.
Show only available actions and omit empty groups.

**Defer the record Retention rule tab.** Disposition is scheduled for the
governing root aggregation. A future amendment must define which inherited
rule details a record viewer may see, including when the governing root or
rule source is restricted. The record continues to show its existing lifecycle
status in Metadata.

## 5. Navigation and refresh

- Use the existing Back and breadcrumb navigation. When returning from a record
  to the aggregation it was opened from, restore both page positions, the
  submitted filter and any draft text, expanded record rows, and focus on the
  originating row if it is still visible. If the row is gone, focus the records
  section. Other entry points retain their existing return destinations.
- Closing Details with Escape or the close button restores focus to the control
  that opened it. Existing editors and confirmations remain reachable from the
  dialog with a clear return path. Relationship links recheck target access.
- Load the primary lists or Digital Components without waiting for unopened
  detail tabs. Run independent reads concurrently within the client’s limits.
  Ignore responses after the user leaves the relevant view. Refresh affected
  lists, statuses, and open details after a successful change.

## 6. Acceptance criteria

| ID | Required evidence |
| --- | --- |
| ARP-01 | Both aggregation lists and the record’s Digital Components are reachable without opening Details. Verify existing record entry points, action visibility, and the three record dialog tabs. |
| ARP-02 | Check that the icon tooltips report the current state. Open each summary with pointer and keyboard. Verify direct and inherited closure, restricted sources, vital descendants, zero holds, more than three visible hold names, restricted holds, and an unavailable status. Check Escape and focus restoration. |
| ARP-03 | Use a fixture with multiple pages in both lists. Reach the final pages, verify counts and order, and confirm that actions match the current user’s access. Verify the originated date, medium icon and exact tooltip below each record title, and the file count beside the actions. Request traces show at most one capability batch per rendered list page and no per-item capability calls. One list’s pager does not reload the other. |
| ARP-04 | Edit a filter without applying it, page the submitted results, open a record, then return. Both pages, filter values, expansions, and row focus are restored. Verify empty results, clearing the filter, and recovery after another search replaces the shared slot. |
| ARP-05 | Verify fresh state after edits, closure changes, hold changes, and relationship changes. Check closed branches, read-only users, redacted targets, and permitted and denied previews. Navigate away during a load and verify that late results do not alter the next view. |
| ARP-06 | Verify desktop and narrow layouts in English/LTR and Arabic/RTL. Check keyboard access, visible focus, long titles, icon labels, and dialog and summary placement. Validate the English and Arabic catalogues. |
| ARP-07 | Verify the containing aggregation link in the record header and its visibility under restricted access. Open and close a file row with pointer and keyboard. Verify authorized file actions, pagination, long filenames, and the empty state. |
| ARP-08 | Add one or several files through the chooser and by dropping them on a record page. Verify the overlay appears only for file drags, clears on exit, cancellation, or drop, and stays hidden for physical, closed, and upload-restricted records. Verify lists refresh after upload and show any files saved before a partial failure. |
| ARP-09 | Check that a viewer without audit access receives creator names for visible items only. Verify translated current names, fallback to the name on the creation event, and omission when no name is available. Verify one creator lookup for each returned page and no separate request for names. |

Use a disposable database for database-backed checks and drop it after the run.
Extend and run the [search performance gate](../docs/search-performance.md#required-repeatable-gate)
for changed search paths or result processing. For new or changed protected
routes, verify allowed and denied requests, including a signed-in user without
access to the resource. Update the policy inventory when route policy changes.

## 7. Created by in listings

Use the creator's user ID from the creation event to show their current name
in the viewer's language. Use the current canonical name if no translation
exists. If the user is unavailable, use the name stored on the event.
Show the name to anyone who can see the listed item. If the name cannot be
resolved, omit the field and keep the listing available. Fetch names in one
batch for the authorized items on each returned page using the existing event
history index.

Global Search, Advanced Search, and the main aggregation and record filters
use **Search results per page** as their default. It defaults to 25 and accepts
1 to 100 items. Existing per-search page-size choices can override the default.
The complete API response for an ordinary 25-record page targets 200 ms,
including creator names. The user accepted a measured 261 ms cold first
response. The large search fixture keeps the three-second threshold for each
measured page.
