# Digital component preview and collaboration roadmap

## Purpose

Deliver record-level digital-component preview improvements in three phases. Phases 1 and 2 are approved for implementation. Phase 3 documents future direction.

## Delivery phases

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Component switching and record-level Preview actions; authorization-aware Print and Download controls | Approved for implementation |
| 2 | Full PDF.js reader for saved and staged components | Approved for implementation, 19 November 2026 |
| 3 | Multi-user annotations saved to Wathiq | Deferred; detailed product specification required |

## Phase 1 — Preview navigation and authorized actions

### 1. Component switching in the existing viewer

- Opening Preview from a digital component continues to open the existing maximized viewer and initially renders the component whose Preview action was selected.
- The viewer header displays a compact component switcher containing one control for each previewable digital component in the record, ordered by `component_order` ascending.
- Each control identifies its component with a file-type icon and filename (truncated with a tooltip when necessary). The currently rendered component has a distinct selected state and exposes its selected state to assistive technology.
- Selecting another component loads it in the same viewer and updates the title, selected state, and media/PDF rendering controls. The viewer does not close between components.
- While a component is loading or being converted, show the existing preparation/loading treatment and prevent duplicate selection of that component. A failure is reported without closing the viewer; the user may select another component or retry.
- Existing rendering, page navigation, zoom, and close behavior remains unchanged. Page number and zoom state reset to their defaults when the selected component changes.
- Download is capability-controlled for the selected component. Show an enabled Download action only when the user has `record.component.download`; otherwise omit it from the viewer. Record ownership does not grant this capability implicitly, and the download API must independently enforce it.
- Print is capability-controlled for the selected component. Show an enabled Print action only when the user has `record.component.print`; otherwise omit it. Record ownership does not grant this capability implicitly, and the supported print workflow must independently enforce authorization.
- Recalculate Print and Download visibility whenever the selected component changes.
- When only one previewable component exists, show it as selected; the viewer otherwise behaves as it does today.

### 2. Aggregation details entry point

- In **Records in this aggregation**, add a Preview action alongside the existing row actions for an eligible record.
- Show Preview only when the record medium is not `physical`, the record has at least one previewable digital component, and the user has permission to view it.
- Selecting Preview opens the enhanced viewer with the record's first previewable component by `component_order` selected.
- Records that are physical, have no previewable components, or cannot be viewed by the user do not display the action. Other row actions remain aligned and unchanged.
- Tooltip and accessible label: **Preview digital components**.

### 3. Record details entry point

- In the Record details header, place Preview with the existing Favourite and Back actions.
- Apply the same visibility and authorization rules as the aggregation-table Preview action.
- Selecting Preview opens the enhanced viewer with the first previewable component by `component_order` selected.
- Tooltip and accessible label: **Preview digital components**.

### 4. Preview staged components before record creation

**Approved amendment: 3 November 2026.** The record-creation editor also offers
Preview on completed staged uploads in formats supported by the existing viewer.
Use the same maximized viewer, native image/audio/video rendering, PDF controls,
document conversion, ordering and component switching as saved records. Identify
this as staged preview and explain that previewing does not save/create the record.
Unsupported or incomplete uploads have no Preview action. Tooltip and accessible
name reuse **Preview digital component**, including Arabic translation.

Staged files remain in the private draft creation package. Every rendition GET
or HEAD, including range requests, must recheck the current authenticated draft
owner, unexpired draft and existing `record.create` authority. Match the component
to that draft; do not resolve a staged ID as a saved digital component. A guessed
component/draft combination, another owner's draft, expired/discarded/committed
draft or deleted component cannot return bytes. Uploads must be complete before
preview. Saved component permissions continue to apply after commit and are not
inherited merely from owning a draft.

This amendment adds Preview only: draft previews have no Print or Download action
and do not use saved-record content/print routes. No record, permanent component,
content set, record content-view event or disposition processing-copy entity is
created by previewing a private staging package. Upload order, original bytes,
checksums, metadata and draft expiry remain unchanged. Conversion reuses existing
format/size/time limits and isolated temporary-directory cleanup, with one temporary PDF per visited converted component in each viewer dialog. Returning to a component reuses that PDF. Release and expiry follow the
[converted-preview transport specification](optimize-preview-rendering.md#cleanup-and-deployment). Original supported native files remain inline, non-cacheable,
MIME-safe responses with existing HEAD/range semantics.

Use the mounted editor's current component metadata when opening staged Preview;
do not add a second metadata download. The switcher renders at most 50 entries
per page and fetches bytes only for the selected component. Closing the viewer or
leaving its source editor invalidates pending responses; late results must not
reopen or repaint an abandoned view. Conversion, authorization and missing-file
errors leave the viewer closable and allow another component to be selected.
Closing Preview returns to the unchanged editor. Saving or cancelling record
creation remains an explicit, separate action.

Acceptance checks: PDF/native/converted preview and original-byte preservation;
owner/expiry/revoked-authority/cross-draft/deleted/incomplete checks; unsupported
format and conversion failures; HEAD/ranges and no-cache headers; no implicit
record creation or promotion; LTR/RTL labels and component order/switching; no
Print/Download; bounded rendering, abandonment and saved-viewer regressions.

### Phase 1 definitions and constraints

- For saved records, a **previewable digital component** is an available component that the existing preview service/viewer supports and that the current user is authorized to view. Components still processing, unavailable, or unsupported are excluded from launch eligibility and the switcher.
- The backend remains authoritative for record medium, component order, availability, and access. Hidden controls are not a substitute for API authorization.
- Preview authorization is distinct from download and print authorization. The viewer must derive control visibility from the current component's effective capabilities, not from ownership or from the ability to preview it.
- UI restrictions are not digital-rights management: because preview requires document content to reach the browser, the product cannot prevent screenshots or a technically capable user from capturing rendered content. It must nevertheless avoid exposing unauthorized download and print actions or endpoints.
- This enhancement adds no new roles, privileges, record states, component types, or changes to component ordering.
- Filenames, tooltips, focus indicators, icon-button accessible names, keyboard navigation, and selected/loading states must remain usable at supported desktop widths. If the component controls exceed the available width, the switcher scrolls horizontally without wrapping the PDF toolbar.
- Phase 1 retains the current custom canvas-based PDF renderer. Selectable text, search, annotation layers, and the other capabilities of the full PDF.js viewer are outside Phase 1.

### Phase 1 acceptance criteria

1. Previewing component 2 of a four-component record opens the viewer on component 2 and shows all four eligible components in record order.
2. Selecting component 4 renders component 4 in the same viewer and recalculates Download and Print visibility from component 4's effective capabilities.
3. A record-level Preview from either details page opens the first eligible component in record order.
4. A physical record, a record with no previewable components, and a record lacking view permission show no record-level Preview action.
5. A single-component record opens normally and shows that sole component as selected.
6. A failed component load leaves the viewer open and permits another component to be selected.
7. The new controls are keyboard reachable, have accessible names, and expose the active component state.
8. A user with Preview but without Download sees no Download action, and direct use of the protected download workflow is rejected by the backend.
9. A user with Preview but without Print sees no Print action, and direct use of the supported print workflow is rejected by its authorization boundary.
10. A user with the applicable Download or Print capability sees the corresponding enabled action for the selected component.

## Phase 2 — Full PDF.js viewer

**Approved 19 November 2026.** The shared maximized preview embeds Mozilla’s full PDF.js viewer for original PDFs and converted PDF renditions. The component switcher selects files. The viewer sidebar selects pages within the current file.

| Requirement | Acceptance check |
| --- | --- |
| PDF-01. Show page thumbnails, page navigation, zoom, selectable text, in-document find, and existing PDF annotations and links. | Open a multi-page text-backed PDF, select text, find a match, navigate by thumbnail, read an embedded annotation, and zoom. Converted text uses the same viewer. Image-only scans require an existing OCR text layer for selection and find. |
| PDF-02. Disable annotation editing and hide the editor controls. Use the existing Wathiq actions for authorized Print and Download Original. | Verify the read-only annotation layer, disabled editor and absence of alternate save, print, open-file and attachment-export paths, including keyboard commands. Draft preview offers neither Print nor Download. |
| PDF-03. Use the effective Wathiq language and direction. | Verify English/LTR and Arabic/RTL controls, keyboard access, page content direction, and independent component and page navigation. |
| PDF-04. Preserve the Phase 1 saved/draft lifecycle and native media paths. | Switch between an image and a PDF, close during loading, reopen, and verify selected-component-only fetches and the existing saved/staged activity behavior. |

This phase uses the current authorized, whole-document base64 handoff and the existing API and database contracts. The subsequent [Optimize Preview Rendering](optimize-preview-rendering.md) specification governs transport upgrades after viewer integration. Collaborative annotation storage remains in Phase 3.

### Phase 2 implementation and verification

The shared [preview dialog](../frontend/webui/component_preview.py) selects the
authorized rendition and supplies its bytes and language to the
[viewer adapter](../frontend/webui/static/pdfjs/erms-viewer.mjs).
[Reader configuration](../frontend/webui/static/pdfjs/wathiq-viewer-config.mjs)
sets the annotation and file-operation behavior.

- PDF-01 and PDF-03 are exercised by the [component browser journey](../tools/webui_browser_components.py). Chrome and Edge passed the English and Arabic journeys on 19 November 2026, including page thumbnails, selectable text, find, zoom and an existing annotation on page two.
- PDF-02 and PDF-04 are covered by the [draft browser journey](../tools/webui_browser_records.py), [shared preview tests](../frontend/webui/tests/test_staged_component_preview.py), and [activity tests](../frontend/webui/interaction/tests/test_aggregation_preview_activity.py). Chrome passed staged preview and cancellation with an English PDF and an Arabic text upload converted by LibreOffice. The draft toolbar exposed only Close.
- The [saved permission tests](../backend/services/api/tests/test_phase8_content_authorization.py) and [staging API tests](../backend/services/api/tests/test_staged_component_preview.py) exercise the existing authorization boundary. The selected print-denial and staged-preview regressions passed against a disposable database.

## Phase 3 — Multi-user annotations saved to Wathiq

**Status: deferred to a future implementation and not yet implementation-ready.**

Add multi-user annotations that are persisted in Wathiq and associated with the applicable record and digital component. Before implementation, a separate approved specification must define:

- supported annotation types and editing behavior;
- persistence model, component/version association, and concurrency handling;
- who may create, view, modify, and delete annotations;
- attribution, timestamps, event history, retention, export, and audit requirements;
- behavior when a component is reordered, replaced, superseded, or deleted; and
- whether annotations alter the source PDF, generate a derivative, or remain a separate Wathiq data layer.

No annotation permissions, storage entities, lifecycle rules, or workflows are introduced by this roadmap document.

## Phase 1 UI mockups

Conceptual mockups follow; final spacing and iconography should reuse the established Wathiq/NiceGUI design tokens and action patterns.

### Enhanced viewer with component switcher

![Enhanced viewer with component switcher](assets/digital-component-preview/enhanced-viewer.png)

### Preview action in “Records in this aggregation”

![Aggregation details preview action](assets/digital-component-preview/aggregation-record-preview.png)

### Preview action in the Record details header

![Record details preview action](assets/digital-component-preview/record-header-preview.png)
