# Draft specification: Dashboard, Records, and faster creation

**Status:** Draft for review. This proposal covers the Dashboard and Records
actions, **Needs attention**, simpler creation dialogs, field help, and
creating a record by dropping files. Implementation has not started.

## 1. Dashboard and Records

| ID | Entry point | Required behavior |
|---|---|---|
| UI-1 | Dashboard | Show **New record** as the primary page-header action and **New aggregation** as the secondary action. **New aggregation** creates a root aggregation. |
| UI-2 | Records | Show **New record** in the page header. Preserve the existing search, results, and navigation. |
| UI-3 | Aggregations | The collection-level creation action creates a root aggregation and is labelled **New root aggregation**. |
| UI-4 | Aggregation detail | Offer **New child aggregation** and **New record** according to the existing permissions and closure rules. Any eligible aggregation can be a parent, including one that is itself a child. |

Show the root aggregation creation actions only to users with `aggregation.create_root`.
Show the Dashboard and Records **New record** actions and enable file-drop
capture only for users with `record.create`. The destination picker and server
must still enforce placement permissions. On an aggregation detail page,
child creation also requires `aggregation.add_child`, and record creation
requires `aggregation.add_record`, alongside the corresponding global
privilege and existing eligibility rules.
[Security and authorization specification](security-and-authorization-subsystem.md)

## 2. Needs attention

**DA-1.** Place **Needs attention** immediately below the Dashboard header.
Show the following metrics using the existing authorized counts:

| Metric | Count and action |
|---|---|
| **Overdue reviews** | Count overdue aggregation and record reviews. Open the corresponding authorized review list, oldest due date first. |
| **Reviews due soon** | Count reviews inside the configured upcoming window. Show the window in the label or supporting text. Open the corresponding list, earliest due date first. |
| **Unclassified roots** | Count visible root aggregations missing their governing classification. Show this item when the count is positive. Open the filtered Aggregations results. An aggregation with a parent the user cannot see is still a child. |

**DA-2.** Counts represent the complete authorized result, including rows
beyond the first page. A confirmed zero is distinct from loading or failure.
The drill-downs use bounded server pagination and retain current visibility,
clearance, and review ownership rules. Keep the existing Dashboard overview
and review information available.

**DA-3.** Dashboard content, including all three counts, continues to load
through one `GET /api/v1/dashboard/summary` request per load or refresh.
Opening a drill-down can fetch its results on demand. A refresh keeps the
last authorized snapshot visible until the new result arrives. After
successful creation, refresh the active Dashboard once, or revalidate when
the user next returns. The Records page retains its search when a record is
created.
[Dashboard refresh contract](../docs/webui-performance.md#5-dashboard-navigation-and-refresh) ·
[Review count and scope rules](resource-medium-vital-status-review-and-location.md#14-dashboard-and-notifications)

## 3. Creation dialogs and field help

**CR-1.** Use one compact dialog and one create action per scenario. Give the
fields the user needs to complete the most prominence. Show fixed context as
labelled read-only text. Keep effective values such as **Medium** and
**Security level** visible when their editable controls are under
**More details**. Preserve the existing **Suggest next number** action.

| Scenario | Initial view |
|---|---|
| **Root aggregation** | Show **Create for**, **Classification**, **Title**, and **Aggregation number**. The classification must be eligible for root assignment. Omit the **Parent aggregation** label and field entirely. |
| **Child aggregation** | Show the current parent as read-only context. Show the inherited classification and medium without offering an override. Ask for title, number, and **Create for** when a role choice is required. |
| **Record from Dashboard or Records** | Show a searchable **Aggregation** selector before **Create for**. Ask for title and number. Once a destination is selected, show the eligible roles and applicable medium and security values. |
| **Record from an aggregation page** | Show the current aggregation as read-only context. Ask for title, number, and any remaining role choice. |
| **Record from dropped files** | Use the record dialog with **Add files** expanded, the dropped files listed, and the available defaults and suggestions ready for review. The user chooses the destination before creating the record. |

**CR-2.** **Create for** fills automatically and is read-only when exactly
one role is eligible. With several eligible roles, require a choice. With
none, explain the blocker beside the field. If a destination change
invalidates a role, medium, or security selection, explain the change and
preserve the user’s other edits. Destination selectors use bounded server
search.

**CR-3.** Put optional description, dates, and other applicable metadata under
**More details**. Keep **Add files** separate and easy to find for digital
and mixed records. Keep required choices visible. If validation fails for a
field inside a collapsed section, expand it, focus the field, and preserve
the entered values.

**CR-4.** Provide a labelled **Show field help** / **Hide field help** toggle.
Explanations appear beside their fields. Help starts collapsed and the
user’s choice follows them across these dialogs within their signed-in
session. Required-field markers, short instructions needed to complete the
task, validation errors, and explanations of blocked choices remain visible
independently of the toggle. Support keyboard operation and English and
Arabic layouts.

**Specification change:** The root and child entry points replace the current
requirement for an optional Parent field in the aggregation creation dialog.
Parent placement becomes a choice of where to start in the WebUI. The API
continues to enforce the existing root and child creation rules.
[Current ownership UI specification](organizational-ownership-and-default-acls.md#131-ownership)

## 4. Drag-and-drop record creation

**DD-1. Overlay.** Reserve no upload space on the Dashboard or Records page.
When a file drag enters the content area, show **Drop files to create a
record** over the page without moving the underlying content. The whole
content area accepts the drop. Hide the overlay on leave, cancellation,
drop, or navigation. Ordinary text and link drags do not activate it.
**New record → Add files** remains available for keyboard and touch users.

**DD-2. Draft and staging.** One drop opens one record draft. Each dropped
file becomes a component of that draft. Open the dialog immediately and
show each filename, size, and staging status under **Add files**. Let the
user review and edit metadata while uploads run. A failed file stays visible
with a reason and **Retry** or **Remove**. A retry must not duplicate a
component. Preserve the existing staged file preview and ordering controls
where applicable.

**DD-3. Defaults and suggestions.**

- **Title.** For one file, use its filename without the final extension,
  with separators converted to spaces. For multiple files, take the shared
  leading words across all cleaned filenames, comparing without regard to
  case. Use the result only when it contains a meaningful word beyond
  generic labels such as `scan`, `document`, `file`, or `image`.
  `supplier-renewal-agreement.pdf` and `supplier-renewal-summary.docx`
  suggest **Supplier renewal**. Unrelated filenames and a batch such as
  `scan-001.pdf` and `scan-002.pdf` leave the title blank. Suggestions may
  update when the batch changes until the user edits or clears the title.
  No LLM is involved.
- **Security level and Vital.** Default security to the **lowest level
  available** under the user’s permissions and the destination’s rules.
  Keep the value visible and editable within the allowed choices. Leave
  **Vital** unchecked by default.
- **Medium.** Default to **Digital**. While digital files are staged, offer
  only eligible destinations that accept digital components. Allow **Mixed**
  where the selected aggregation permits it.
- **Destination and number.** Require the user to choose the destination.
  Then populate an available record-number suggestion using the existing
  numbering rules. Preserve a number the user has entered, and surface a
  conflict for correction if it cannot be used.

**DD-4. Commit and cancel.** Keep **Create record** unavailable while any
included upload is pending or failed. On create, recheck authorization,
destination eligibility, required metadata, and component readiness. Commit
the record and its included components atomically. If creation fails,
preserve the editable draft and show the cause. Cancelling discards the
draft and staged files through the existing draft lifecycle.
[Record drafts and atomic commit](../docs/record-drafts.md#atomic-commit)

## 5. Acceptance checks

| Requirements | Verify |
|---|---|
| UI-1–4, CR-1–2 | Root-only, child-only, record-creator, and read-only users see the correct actions. Root creation has no parent field. Child and in-context record creation use the current aggregation. Closed or unauthorized destinations cannot be used. |
| DA-1–3 | The three counts match their authorized drill-downs, including when results span pages. Dashboard load uses one summary request, and creation refreshes counts without clearing the page. |
| CR-3–4 | Required fields stay discoverable, invalid collapsed fields are revealed, and help follows the user across dialogs without leaking to another account. Verify keyboard use and both English and Arabic layouts. |
| DD-1–2 | On both pages, a file drag shows the overlay without layout movement. Leaving and cancelling clear it. Dropping several files opens one draft. A failed upload can be retried or removed without losing metadata. |
| DD-3–4 | Test one file, shared filenames, unrelated filenames, generic scan names, and a manually edited title. Verify the defaults, number conflict handling, atomic commit, and cleanup on cancel. |
